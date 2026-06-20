import {
  cells,
  connectionStatus,
  notebookHeader,
  notebookPath,
  runningCell,
  runError,
} from "../stores/cells";
import { getDb } from "./duckdb";
import type {
  Cell,
  CellEndEvent,
  CellManifestItem,
  CellStartEvent,
  NotebookHeaderEvent,
  RunStartEvent,
} from "./types";

// Pre-warm DuckDB-WASM in background (~8MB lazy load, cached after first load)
getDb();

let eventSource: EventSource | null = null;

export function connectStream(path: string) {
  if (eventSource) {
    eventSource.close();
  }

  connectionStatus.set("connecting");
  // The path identifies which notebook's stream to subscribe to; the daemon
  // keeps per-notebook state keyed by this exact (resolved) path.
  eventSource = new EventSource("/stream?path=" + encodeURIComponent(path));

  eventSource.onopen = () => {
    connectionStatus.set("connected");
  };

  eventSource.addEventListener("notebook_header", (e) => {
    const data: NotebookHeaderEvent = JSON.parse(e.data);
    notebookPath.set(data.path);
    if (data.docstring) {
      notebookHeader.set(data.docstring);
    }
  });

  eventSource.addEventListener("run_start", (e) => {
    const data: RunStartEvent = JSON.parse(e.data);
    // A fresh run clears the previous error banner; this is the only place it
    // is cleared, which is what keeps it sticky across run_end.
    runError.set(null);
    // A partial run targets only the cells in the manifest; skipping reconcile
    // leaves every other cell (and its output) untouched. Each targeted cell is
    // updated in place by its own cell_start / display_record / cell_end events.
    if (!data.partial) {
      reconcile(data.cell_manifest);
    }
  });

  eventSource.addEventListener("cell_start", (e) => {
    const { cell_id, title }: CellStartEvent = JSON.parse(e.data);
    runningCell.set({ id: cell_id, title });
    cells.update((cs) => {
      const cell = cs.find((c) => c.id === cell_id);
      if (cell) {
        cell.status = "running";
        cell.stale = false;
        cell.profiling = null;
        cell.title = title;
        // Keep existing records mounted; overwrite them in place as new
        // display_record events arrive (tracked by _cursor). Leftover records
        // beyond the cursor are truncated at cell_end. This avoids tearing
        // down and rebuilding output components (and the DataTable DuckDB
        // re-init flash) on every run.
        cell._cursor = 0;
      }
      return cs;
    });
  });

  eventSource.addEventListener("display_record", (e) => {
    const { cell_id, type, payload } = JSON.parse(e.data);
    cells.update((cs) => {
      const cell = cs.find((c) => c.id === cell_id);
      if (cell) {
        const cursor = cell._cursor ?? cell.records.length;
        const records = cell.records.slice();
        records[cursor] = { type, payload };
        cell.records = records;
        cell._cursor = cursor + 1;
      }
      return cs;
    });
  });

  eventSource.addEventListener("cell_end", (e) => {
    const { cell_id, wall_ms, cpu_ms, status, error }: CellEndEvent =
      JSON.parse(e.data);
    cells.update((cs) => {
      const cell = cs.find((c) => c.id === cell_id);
      if (cell) {
        cell.status = status;
        cell.profiling = { wall_ms, cpu_ms };
        if (status === "error") {
          // Sticky banner in the header; survives run_end, cleared on next run_start.
          runError.set({ id: cell_id, title: cell.title, message: error });
        }
        // Drop any records left over from a previous run that this run did
        // not re-emit (outputs that no longer exist).
        const cursor = cell._cursor ?? 0;
        if (cell.records.length > cursor) {
          cell.records = cell.records.slice(0, cursor);
        }
      }
      return cs;
    });
  });

  eventSource.addEventListener("run_end", (e) => {
    runningCell.set(null);
    finalizeRun();
  });

  eventSource.onerror = (err) => {
    runningCell.set(null);
    connectionStatus.set("disconnected");
    console.error("EventSource connection error:", err);
  };
}

function reconcile(manifest: CellManifestItem[]) {
  cells.update((currentCells) => {
    const manifestIds = new Set(manifest.map((c) => c.id));
    const updatedCells: Cell[] = [];

    for (const item of manifest) {
      const existing = currentCells.find((c) => c.id === item.id);
      if (existing) {
        existing.stale = true;
        existing.status = "pending";
        updatedCells.push(existing);
      } else {
        updatedCells.push({
          id: item.id,
          status: "pending",
          stale: false,
          records: [],
          profiling: null,
          title: item.title || null,
        });
      }
    }

    // Keep absent cells temporarily, marked for deletion after run_end
    for (const existing of currentCells) {
      if (!manifestIds.has(existing.id)) {
        existing.absent = true;
        updatedCells.push(existing);
      }
    }

    updatedCells.sort((a, b) => a.id - b.id);
    return updatedCells;
  });
}

function finalizeRun() {
  cells.update((currentCells) => {
    return currentCells.filter((c) => !c.absent);
  });
}
