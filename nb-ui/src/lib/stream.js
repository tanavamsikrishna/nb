import { getDb } from "./duckdb.js";
import { cells, notebookHeader, connectionStatus } from "../stores/cells.js";

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
    notebookHeader.set(data.docstring);
  });

  eventSource.addEventListener("run_start", (e) => {
    const data = JSON.parse(e.data);
    reconcile(data.cell_manifest);
  });

  eventSource.addEventListener("cell_start", (e) => {
    const { cell_id } = JSON.parse(e.data);
    cells.update((cs) => {
      const cell = cs.find((c) => c.id === cell_id);
      if (cell) {
        cell.status = "running";
        cell.stale = false;
        cell.records = [];
        cell.profiling = null;
      }
      return cs;
    });
  });

  eventSource.addEventListener("display_record", (e) => {
    const { cell_id, type, payload } = JSON.parse(e.data);
    cells.update((cs) => {
      const cell = cs.find((c) => c.id === cell_id);
      if (cell) {
        cell.records = [...cell.records, { type, payload }];
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
        if (existing.content_hash === item.content_hash) {
          existing.stale = false;
          existing.status = "pending";
          updatedCells.push(existing);
        } else {
          updatedCells.push({
            id: item.id,
            content_hash: item.content_hash,
            status: "pending",
            stale: true,
            records: [],
            profiling: null,
          });
        }
      } else {
        updatedCells.push({
          id: item.id,
          content_hash: item.content_hash,
          status: "pending",
          stale: false,
          records: [],
          profiling: null,
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
