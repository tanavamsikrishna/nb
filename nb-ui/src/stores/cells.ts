import { writable } from "svelte/store";

export const notebookHeader = writable(null);
export const notebookPath = writable(null);
export const cells = writable([]);
export const connectionStatus = writable("disconnected");

// The cell currently executing, or null when idle. Drives the header's live
// "executing" indicator. Shape: { id, title }.
export const runningCell = writable(null);

// The error from the most recent run, or null. Drives the header's sticky error
// banner. Unlike runningCell it is NOT cleared on run_end — it persists until the
// next run starts. Shape: { id, title, message }.
export const runError = writable(null);
