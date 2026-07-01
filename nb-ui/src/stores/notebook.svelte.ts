import type {
  Cell,
  ConnectionStatus,
  RunningCell,
  RunError,
} from "../lib/types";

// Client-side mirror of the daemon's per-notebook render state (NotebookSession:
// path / docstring / code / cells). The SSE events are a delta protocol that
// stream.ts folds into this object in place — the browser twin of the daemon's
// `_fold_state`. It is a deep Svelte 5 $state proxy, so mutating a cell
// (`cell.status = ...`, `cell.records[i] = ...`) re-renders exactly that Cell
// without swapping references.
//
// Record payloads are proxied here too, but Plotly/Vega MUTATE the data they're
// handed and would loop a proxy back into a reactive update — so PlotlyOutput /
// AltairOutput $state.snapshot the payload before rendering. That snapshot is the
// single boundary that lets this state stay reactive; a new mutating renderer
// must snapshot there too.
export interface NotebookState {
  path: string | null;
  header: string | null;
  source: string | null;
  cells: Cell[];
}

export const notebook = $state<NotebookState>({
  path: null,
  header: null,
  source: null,
  cells: [],
});

// Transient, client-only view state — deliberately NOT part of the notebook
// mirror above. The daemon never persists these (running/run_end are live-only
// transient events, and the error banner is synthesized on the client from a
// cell_end), so they don't belong in a "clone of backend state".
//
// - connection: EventSource state, drives the header's connection dot.
// - running: the cell currently executing, or null when idle.
// - error: the most recent run's error, or null. NOT cleared on run_end — it
//   persists (sticky banner) until the next run_start clears it.
export interface ViewState {
  connection: ConnectionStatus;
  running: RunningCell | null;
  error: RunError | null;
}

export const view = $state<ViewState>({
  connection: "disconnected",
  running: null,
  error: null,
});
