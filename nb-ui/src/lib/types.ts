/*
 * Shared domain types for the nb-notebook stream UI.
 *
 * These mirror the events and payloads emitted by the Python daemon
 * (nb/runner.py, nb/framework.py) and flow store → stream → components.
 * Kept as one source of truth so the literal unions stay in sync with the
 * emitter rather than being re-declared inline per component.
 */

/** Render kind of a display record. Mirrors nb/framework.py `_create_display_record`. */
export type RecordType =
  | "md"
  | "html"
  | "text"
  | "object"
  | "table"
  | "plotly"
  | "altair"
  | "params";

/** Base64-encoded Parquet payload for a `table` record (see `_serialize_table`). */
export interface TablePayload {
  data: string;
  total_rows: number;
  label?: string | null;
}

/** A Plotly figure dict (`figure.to_json()`), passed to Plotly.react. */
export interface PlotlyPayload {
  data: unknown[];
  layout?: Record<string, unknown>;
  config?: Record<string, unknown>;
}

/**
 * A single rendered output. Discriminated on `type` so consumers (Cell.svelte)
 * narrow `payload` to the right shape per branch.
 */
export type DisplayRecord =
  | { type: "md" | "html" | "text"; payload: string }
  | { type: "table"; payload: TablePayload }
  | { type: "plotly"; payload: PlotlyPayload }
  | { type: "altair"; payload: unknown }
  | { type: "object"; payload: unknown }
  /** Experiment hyperparameters from `params(...)`; payload is a flat kv map. */
  | { type: "params"; payload: Record<string, unknown> };

/** Lifecycle state of a cell. `ok`/`error` are the terminal run outcomes. */
export type CellStatus = "pending" | "running" | "ok" | "error";

export interface Profiling {
  wall_ms: number;
  cpu_ms: number;
}

/** One notebook cell as tracked in the `cells` store. */
export interface Cell {
  id: number;
  status: CellStatus;
  stale: boolean;
  records: DisplayRecord[];
  profiling: Profiling | null;
  title: string | null;
  /** Write cursor for in-place record updates across re-runs (see stream.ts). */
  _cursor?: number;
  /** Marked for removal after run_end when a re-run no longer emits this cell. */
  absent?: boolean;
}

export interface RunningCell {
  id: number;
  title: string | null;
}

export interface RunError {
  id: number;
  title: string | null;
  message: string;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

/* ── /notebooks (index page picker; see nb/daemon.py notebooks_handler) ── */

export interface NotebookListItem {
  /** Resolved absolute path — the session key and the `?path=` value. */
  path: string;
  /** Basename, for display. */
  name: string;
  num_cells: number;
  /** True when the daemon holds a live session (streamable at `?path=`). */
  active?: boolean;
  /** True when the notebook has stored experiments (`?view=experiments`). */
  has_experiments?: boolean;
}

export interface NotebooksResponse {
  notebooks: NotebookListItem[];
}

/* ── Experiment tracking (see nb/experiments.py, daemon experiments_handler) ── */

/** One saved run's metadata; `children` are partial runs of a full parent run. */
export interface ExperimentRun {
  run_id: string;
  parent_run_id: string | null;
  kind: "full" | "partial";
  started_at: string;
  dur_ms: number;
  status: "ok" | "error";
  error: string | null;
  cell_ids: number[];
  params: Record<string, unknown>;
  children: ExperimentRun[];
}

export interface ExperimentsResponse {
  runs: ExperimentRun[];
}

/** A single loaded run for the read-only viewer (`/experiment`). */
export interface ExperimentDetail {
  meta: Omit<ExperimentRun, "children">;
  code: string;
  docstring: string | null;
  cells: Cell[];
}

/* ── SSE event payloads (the `data` field of each event; see nb/runner.py) ── */

export interface CellManifestItem {
  id: number;
  title: string;
}

export interface NotebookHeaderEvent {
  path: string;
  docstring?: string;
  code?: string;
}

export interface RunStartEvent {
  cell_manifest: CellManifestItem[];
  /**
   * A partial run re-executes only the cells in `cell_manifest` (a single cell
   * or a contiguous range) against the daemon's saved namespace. The frontend
   * skips reconcile so cells outside the manifest keep their output untouched.
   */
  partial?: boolean;
}

export interface CellStartEvent {
  cell_id: number;
  title: string;
  source_line: number;
}

export interface CellEndEvent {
  cell_id: number;
  wall_ms: number;
  cpu_ms: number;
  status: CellStatus;
  error?: string;
}
