import { writable } from "svelte/store";
import type {
  Cell,
  ConnectionStatus,
  RunningCell,
  RunError,
} from "../lib/types";

export const notebookHeader = writable<string | null>(null);
export const notebookPath = writable<string | null>(null);
export const notebookSource = writable<string | null>(null);
export const cells = writable<Cell[]>([]);
export const connectionStatus = writable<ConnectionStatus>("disconnected");

// The cell currently executing, or null when idle. Drives the header's live
// "executing" indicator.
export const runningCell = writable<RunningCell | null>(null);

// The error from the most recent run, or null. Drives the header's sticky error
// banner. Unlike runningCell it is NOT cleared on run_end — it persists until the
// next run starts.
export const runError = writable<RunError | null>(null);
