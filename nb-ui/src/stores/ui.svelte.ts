// Per-session, client-only UI preferences. NOT part of the notebook mirror
// (notebook.svelte.ts) — these never come from the daemon and are deliberately
// not persisted across reloads. A single global $state so a preference set in
// one view (live stream, experiment run) is reflected everywhere at once.
export interface UiState {
  /** Whether the notebook spec (docstring) card is collapsed. Collapsed by
   *  default so cells stay front-and-center; shared across all notebooks. */
  specCollapsed: boolean;
}

export const ui = $state<UiState>({
  specCollapsed: true,
});
