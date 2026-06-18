import {
  cells,
  connectionStatus,
  notebookHeader,
  notebookPath,
} from "../stores/cells";
import { getDb } from "./duckdb";

// Pre-warm DuckDB-WASM in background (~8MB lazy load, cached after first load)
getDb();

let eventSource = null;

export function connectStream() {
  if (eventSource) {
    eventSource.close();
  }

  connectionStatus.set("connecting");
  eventSource = new EventSource("/stream");

  eventSource.onopen = () => {
    connectionStatus.set("connected");
  };

  eventSource.addEventListener("notebook_header", (e) => {
    const data = JSON.parse(e.data);
    notebookPath.set(data.path);
    if (data.docstring) {
      notebookHeader.set(data.docstring);
    }
  });

  eventSource.addEventListener("run_start", (e) => {
    const data = JSON.parse(e.data);
    reconcile(data.cell_manifest);
  });

  eventSource.addEventListener("cell_start", (e) => {
    const { cell_id, title } = JSON.parse(e.data);
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
    const { cell_id, wall_ms, cpu_ms, status } = JSON.parse(e.data);
    cells.update((cs) => {
      const cell = cs.find((c) => c.id === cell_id);
      if (cell) {
        cell.status = status;
        cell.profiling = { wall_ms, cpu_ms };
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
    finalizeRun();
  });

  eventSource.onerror = (err) => {
    connectionStatus.set("disconnected");
    console.error("EventSource connection error:", err);
  };
}

function reconcile(manifest) {
  cells.update((currentCells) => {
    const manifestIds = new Set(manifest.map((c) => c.id));
    const updatedCells = [];

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
