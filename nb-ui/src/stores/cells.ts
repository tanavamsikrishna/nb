import { writable } from "svelte/store";

export const notebookHeader = writable(null);
export const notebookPath = writable(null);
export const cells = writable([]);
export const connectionStatus = writable("disconnected");

// The cell currently executing, or null when idle. Drives the header's live
// "executing" indicator. Shape: { id, title }.
export const runningCell = writable(null);
