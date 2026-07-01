import { notebook, view } from "../stores/notebook.svelte";
import { getDb } from "./duckdb";
import type {
  Cell,
  CellEndEvent,
  CellManifestItem,
  CellStartEvent,
  NotebookHeaderEvent,
  ParamsEvent,
  ArtifactsEvent,
  RunStartEvent,
} from "./types";

// Pre-warm DuckDB-WASM in background (~8MB lazy load, cached after first load)
getDb();

let eventSource: EventSource | null = null;

// `notebook` / `view` are deep $state proxies, so every handler below folds an
// SSE event by mutating them in place — the browser twin of the daemon's
// `_fold_state`. The proxy tracks the write and re-renders exactly the affected
// Cell; no cloning or reference-swapping is needed to signal a change.
const findCell = (id: number): Cell | undefined =>
  notebook.cells.find((c) => c.id === id);

export function connectStream(path: string) {
  if (eventSource) {
    eventSource.close();
  }

  // Reset the mirror before (re)subscribing so switching notebooks never flashes
  // the previous notebook's cells before the new snapshot arrives.
  notebook.path = path;
  notebook.header = null;
  notebook.source = null;
  notebook.cells = [];
  notebook.params = {};
  notebook.artifacts = [];

  view.connection = "connecting";
  // The path identifies which notebook's stream to subscribe to; the daemon
  // keeps per-notebook state keyed by this exact (resolved) path.
  eventSource = new EventSource("/stream?path=" + encodeURIComponent(path));

  eventSource.onopen = () => {
    view.connection = "connected";
  };

  eventSource.addEventListener("notebook_header", (e) => {
    const data: NotebookHeaderEvent = JSON.parse(e.data);
    notebook.path = data.path;
    if (data.docstring) {
      notebook.header = data.docstring;
    }
    if (data.code !== undefined) {
      notebook.source = data.code;
    }
  });

  eventSource.addEventListener("run_start", (e) => {
    const data: RunStartEvent = JSON.parse(e.data);
    // A fresh run clears the previous error banner; this is the only place it
    // is cleared, which is what keeps it sticky across run_end.
    view.error = null;
    // A partial run targets only the cells in the manifest; skipping reconcile
    // leaves every other cell (and its output) untouched. Each targeted cell is
    // updated in place by its own cell_start / display_record / cell_end events.
    if (!data.partial) {
      reconcile(data.cell_manifest);
    }
  });

  eventSource.addEventListener("cell_start", (e) => {
    const { cell_id, title }: CellStartEvent = JSON.parse(e.data);
    view.running = { id: cell_id, title };
    const cell = findCell(cell_id);
    if (cell) {
      cell.status = "running";
      cell.stale = false;
      cell.profiling = null;
      cell.title = title;
      // Keep existing records mounted; overwrite them in place as new
      // display_record events arrive (tracked by _cursor). Leftover records
      // beyond the cursor are truncated at cell_end. This avoids tearing down
      // and rebuilding output components (and the DataTable DuckDB re-init
      // flash) on every run.
      cell._cursor = 0;
    }
  });

  eventSource.addEventListener("display_record", (e) => {
    const { cell_id, type, payload } = JSON.parse(e.data);
    const cell = findCell(cell_id);
    if (cell) {
      const cursor = cell._cursor ?? cell.records.length;
      // Assigning into the proxied records array re-renders just this output.
      cell.records[cursor] = { type, payload };
      cell._cursor = cursor + 1;
    }
  });

  eventSource.addEventListener("cell_end", (e) => {
    const { cell_id, wall_ms, cpu_ms, status, error }: CellEndEvent =
      JSON.parse(e.data);
    const cell = findCell(cell_id);
    if (cell) {
      cell.status = status;
      cell.profiling = { wall_ms, cpu_ms };
      if (status === "error") {
        // Sticky banner in the header; survives run_end, cleared on next run_start.
        view.error = { id: cell_id, title: cell.title, message: error };
      }
      // Drop any records left over from a previous run that this run did not
      // re-emit (outputs that no longer exist). Truncating the proxied array
      // in place drops exactly those trailing outputs.
      const cursor = cell._cursor ?? 0;
      if (cell.records.length > cursor) {
        cell.records.length = cursor;
      }
    }
  });

  eventSource.addEventListener("params", (e) => {
    const data: ParamsEvent = JSON.parse(e.data);
    notebook.params = data.params;
  });

  eventSource.addEventListener("artifacts", (e) => {
    const data: ArtifactsEvent = JSON.parse(e.data);
    notebook.artifacts = data.artifacts;
  });

  eventSource.addEventListener("run_end", () => {
    view.running = null;
    finalizeRun();
  });

  eventSource.onerror = (err) => {
    view.running = null;
    view.connection = "disconnected";
    console.error("EventSource connection error:", err);
  };
}

function reconcile(manifest: CellManifestItem[]) {
  const current = notebook.cells;
  const manifestIds = new Set(manifest.map((c) => c.id));
  const updated: Cell[] = [];

  for (const item of manifest) {
    const existing = current.find((c) => c.id === item.id);
    if (existing) {
      // Mutating the surviving proxy cell in place marks it stale/pending on
      // the mounted Cell; its records stay put until this run overwrites them.
      existing.stale = true;
      existing.status = "pending";
      updated.push(existing);
    } else {
      updated.push({
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
  for (const existing of current) {
    if (!manifestIds.has(existing.id)) {
      existing.absent = true;
      updated.push(existing);
    }
  }

  updated.sort((a, b) => a.id - b.id);
  notebook.cells = updated;
}

function finalizeRun() {
  notebook.cells = notebook.cells.filter((c) => !c.absent);
}
