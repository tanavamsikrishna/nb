<!--
  CodeDiffModal.svelte — large modal showing difft side-by-side output for two
  full experiment runs (always older → newer). Fetches GET /experiment/diff;
  ANSI → HTML via ansi_up.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { AnsiUp } from "ansi_up";
  import type {
    ExperimentDiffResponse,
    ExperimentDiffSide,
    ParamsMap,
  } from "../lib/types";

  let {
    path,
    aId,
    bId,
    onclose,
  }: {
    path: string;
    /** Older run (base / left). */
    aId: string;
    /** Newer run (updated / right). */
    bId: string;
    onclose: () => void;
  } = $props();

  let data = $state.raw<ExperimentDiffResponse | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(true);

  const ansi = new AnsiUp();
  // Inline styles (not classes) so difft's palette works without custom CSS.
  ansi.use_classes = false;

  function when(iso: string): string {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleString();
  }

  function paramSummary(params: ParamsMap): string {
    const entries = Object.entries(params);
    if (entries.length === 0) return "";
    return entries.map(([k, v]) => `${k}=${v}`).join("  ·  ");
  }

  function sideLabel(side: ExperimentDiffSide): string {
    const params = paramSummary(side.params);
    return params
      ? `${when(side.started_at)}  ·  ${params}`
      : when(side.started_at);
  }

  let diffHtml = $derived(
    data && !data.identical && data.diff ? ansi.ansi_to_html(data.diff) : "",
  );

  async function load() {
    loading = true;
    error = null;
    data = null;
    try {
      const resp = await fetch(
        "/experiment/diff?path=" +
          encodeURIComponent(path) +
          "&a=" +
          encodeURIComponent(aId) +
          "&b=" +
          encodeURIComponent(bId),
      );
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.error ?? `HTTP ${resp.status}`);
      }
      data = (await resp.json()) as ExperimentDiffResponse;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") onclose();
  }

  onMount(() => {
    load();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="backdrop" onclick={onclose} role="presentation">
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions a11y_interactive_supports_focus -->
  <div
    class="modal"
    role="dialog"
    aria-modal="true"
    aria-label="Code diff"
    tabindex="-1"
    onclick={(e) => e.stopPropagation()}
  >
    <header class="modal-header">
      <div class="sides">
        <div class="side">
          <span class="side-tag">Older</span>
          <span class="side-label">{data ? sideLabel(data.a) : aId}</span>
        </div>
        <span class="arrow" aria-hidden="true">→</span>
        <div class="side">
          <span class="side-tag">Newer</span>
          <span class="side-label">{data ? sideLabel(data.b) : bId}</span>
        </div>
      </div>
      <button type="button" class="btn ghost" onclick={onclose}>Close</button>
    </header>

    <div class="modal-body">
      {#if loading}
        <p class="status-msg">Computing diff…</p>
      {:else if error}
        <p class="status-msg error">{error}</p>
      {:else if data?.identical}
        <p class="status-msg">No code changes</p>
      {:else if diffHtml}
        <pre class="diff-pre"><code>{@html diffHtml}</code></pre>
      {:else}
        <p class="status-msg">Empty diff output</p>
      {/if}
    </div>
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 100;
    background: rgba(30, 28, 24, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }

  .modal {
    background: var(--bg-elevated);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg);
    /* Keep in sync with difft --width=180 in experiments.diff_run_code. */
    width: min(1400px, 96vw);
    max-height: min(90vh, 900px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--border-default);
  }

  .modal-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-subtle);
    background: var(--bg-header);
    flex-shrink: 0;
  }

  .sides {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
    flex: 1;
    font-family: var(--font-sans);
    font-size: 0.8rem;
  }

  .side {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .side-tag {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--fg-tertiary);
  }

  .side-label {
    color: var(--fg-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--font-mono);
    font-size: 0.75rem;
  }

  .arrow {
    color: var(--fg-tertiary);
    flex-shrink: 0;
  }

  .btn {
    font-family: var(--font-sans);
    font-size: 0.8rem;
    font-weight: 500;
    padding: 6px 12px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-default);
    background: transparent;
    color: var(--fg-primary);
    cursor: pointer;
    flex-shrink: 0;
  }

  .btn:hover {
    border-color: var(--color-primary);
    color: var(--color-primary);
  }

  .modal-body {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 16px 20px;
    background: var(--bg-code-block);
  }

  .status-msg {
    font-family: var(--font-sans);
    font-size: 0.9rem;
    color: var(--fg-secondary);
    text-align: center;
    padding: 48px 16px;
  }

  .status-msg.error {
    color: var(--color-error);
  }

  .diff-pre {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 0.75rem;
    line-height: 1.45;
    white-space: pre;
    overflow-x: auto;
    color: var(--fg-code);
  }

  .diff-pre code {
    font-family: inherit;
  }
</style>
