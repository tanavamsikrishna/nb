import { writable } from "svelte/store";

export const notebookHeader = writable(null);
export const notebookPath = writable(null);
export const cells = writable([]);
export const connectionStatus = writable("disconnected");
