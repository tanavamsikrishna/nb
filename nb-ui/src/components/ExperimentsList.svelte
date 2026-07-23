<!--
  ExperimentsList.svelte — run history for one notebook (?view=experiments&path=).

  Fetches GET /experiments?path= (a parent/child forest, newest-first) and lists
  each full run with its partial child runs nested underneath. Every run links to
  its read-only viewer at ?path=<path>&run=<run_id>.

  Full (top-level) runs can be multi-selected (max 2) to open a code diff modal
  via GET /experiment/diff (server-side difft).
-->
<script lang="ts">
  import { onMount } from "svelte";
  import type {
    ExperimentRun,
    ExperimentsResponse,
    ParamsMap,
  } from "../lib/types";
  import AppShell from "./AppShell.svelte";
  import CodeDiffModal from "./CodeDiffModal.svelte";

  let { path }: { path: string } = $props();

  let runs = $state<ExperimentRun[]>([]);
  let loaded = $state(false);
  let failed = $state(false);

  /** Selected full-run ids (at most two). */
  let selectedIds = $state<string[]>([]);
  let showDiff = $state(false);

  let name = $derived(path.split("/").pop() || path);
  let canCompare = $derived(runs.length >= 2);
  let selectedSet = $derived(new Set(selectedIds));
  // run_ids are timestamp-prefixed → lexical order is chronological (older first).
  let pair = $derived(
    selectedIds.length === 2
      ? selectedIds[0] <= selectedIds[1]
        ? ([selectedIds[0], selectedIds[1]] as [string, string])
        : ([selectedIds[1], selectedIds[0]] as [string, string])
      : null,
  );

  function runHref(runId: string): string {
    return (
      "/?path=" + encodeURIComponent(path) + "&run=" + encodeURIComponent(runId)
    );
  }

  function when(iso: string): string {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleString();
  }

  function duration(ms: number): string {
    if (ms < 1000) return `${ms} ms`;
    return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
  }

  function paramSummary(params: ParamsMap): string {
    const entries = Object.entries(params);
    if (entries.length === 0) return "";
    return entries.map(([k, v]) => `${k}=${v}`).join("  ·  ");
  }

  async function load() {
    try {
      const resp = await fetch("/experiments?path=" + encodeURIComponent(path));
      if (!resp.ok) throw new Error(String(resp.status));
      const data: ExperimentsResponse = await resp.json();
      runs = data.runs;
      failed = false;
    } catch {
      failed = true;
    } finally {
      loaded = true;
    }
  }

  onMount(load);
</script>

<AppShell>
  {#snippet breadcrumb()}
    <a class="logo-nb logo-home" href="/" title="All notebooks">nb</a>
    <span class="logo-separator">/</span>
    <span class="logo-sub">experiments</span>
    <span class="notebook-name">{name}</span>
  {/snippet}

  {#if loaded && runs.length > 0}
    <ul class="run-list">
      {#each runs as run (run.run_id)}
        <li>
          {@render runRow(run, false)}
          {#if run.children.length > 0}
            <ul class="child-list">
              {#each run.children as child (child.run_id)}
                <li>{@render runRow(child, true)}</li>
              {/each}
            </ul>
          {/if}
        </li>
      {/each}
    </ul>
  {:else if loaded}
    <div class="empty-state">
      <h2>No experiments yet</h2>
      {#if failed}
        <p>Couldn't reach the daemon. Is it running?</p>
      {:else}
        <p>Run this notebook to record an experiment.</p>
      {/if}
    </div>
  {/if}
</AppShell>

{#if canCompare && selectedIds.length > 0}
  <div class="compare-bar" role="region" aria-label="Compare selection">
    <span class="compare-count">
      {#if pair}
        2 selected
      {:else}
        Select one more run to compare
      {/if}
    </span>
    <div class="compare-actions">
      <button
        type="button"
        class="btn primary"
        disabled={!pair}
        onclick={() => (showDiff = true)}
      >
        Compare code
      </button>
      <button
        type="button"
        class="btn ghost"
        onclick={() => {
          selectedIds = [];
          showDiff = false;
        }}
      >
        Clear
      </button>
    </div>
  </div>
{/if}

{#if showDiff && pair}
  <CodeDiffModal
    {path}
    aId={pair[0]}
    bId={pair[1]}
    onclose={() => (showDiff = false)}
  />
{/if}

{#snippet runRow(run: ExperimentRun, isChild: boolean)}
  {@const checked = selectedSet.has(run.run_id)}
  <div class="run-row {isChild ? 'child' : ''} {checked ? 'selected' : ''}">
    {#if !isChild && canCompare}
      <label class="run-check" title="Select for code compare">
        <input
          type="checkbox"
          {checked}
          disabled={!checked && selectedIds.length >= 2}
          onchange={(e) => {
            const on = e.currentTarget.checked;
            selectedIds = on
              ? [...selectedIds, run.run_id]
              : selectedIds.filter((id) => id !== run.run_id);
          }}
        />
      </label>
    {/if}
    <a class="run-item" href={runHref(run.run_id)}>
      <span class="run-top">
        <span class="run-status {run.status}">{run.status}</span>
        <span class="run-when">{when(run.started_at)}</span>
        <span class="run-dur">{duration(run.dur_ms)}</span>
        {#if isChild}
          <span class="run-cells">cells {run.cell_ids.join(", ")}</span>
        {/if}
      </span>
      {#if paramSummary(run.params)}
        <span class="run-params">{paramSummary(run.params)}</span>
      {/if}
    </a>
  </div>
{/snippet}

<style>
  .run-list,
  .child-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .run-list {
    gap: 12px;
  }

  .child-list {
    margin-top: 8px;
    margin-left: 24px;
    border-left: 2px solid var(--border-subtle);
    padding-left: 12px;
  }

  .run-row {
    display: flex;
    align-items: stretch;
    gap: 8px;
  }

  .run-row.selected .run-item {
    border-color: var(--color-primary);
    background: var(--bg-sunken);
  }

  .run-check {
    display: flex;
    align-items: center;
    padding: 0 4px;
    cursor: pointer;
    flex-shrink: 0;
  }

  .run-check input {
    width: 15px;
    height: 15px;
    cursor: pointer;
    accent-color: var(--color-primary);
  }

  .run-check input:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  .run-item {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px 16px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    background: var(--bg-muted);
    text-decoration: none;
    color: inherit;
    transition:
      border-color 0.12s ease,
      background 0.12s ease;
  }

  .run-item:hover {
    border-color: var(--color-primary);
    background: var(--bg-sunken);
  }

  .run-row.child .run-item {
    background: var(--bg-elevated);
  }

  .run-top {
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: var(--font-sans);
    font-size: 0.8rem;
  }

  .run-status {
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 0.05em;
  }

  .run-status.ok {
    color: var(--color-success);
  }

  .run-status.error {
    color: var(--color-error);
  }

  .run-when {
    color: var(--fg-primary);
  }

  .run-dur,
  .run-cells {
    color: var(--fg-tertiary);
    font-family: var(--font-mono);
    font-size: 0.75rem;
  }

  .run-params {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--fg-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .compare-bar {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 60;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px 18px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
    font-family: var(--font-sans);
    font-size: 0.85rem;
    max-width: calc(100vw - 32px);
  }

  .compare-count {
    color: var(--fg-primary);
    font-weight: 500;
    white-space: nowrap;
  }

  .compare-actions {
    display: flex;
    gap: 8px;
    margin-left: auto;
  }

  .btn {
    font-family: var(--font-sans);
    font-size: 0.8rem;
    font-weight: 500;
    padding: 6px 14px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-default);
    background: var(--bg-elevated);
    color: var(--fg-primary);
    cursor: pointer;
    white-space: nowrap;
  }

  .btn:hover:not(:disabled) {
    border-color: var(--color-primary);
  }

  .btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .btn.primary {
    background: var(--color-primary);
    border-color: var(--color-primary);
    color: var(--fg-on-accent);
  }

  .btn.primary:hover:not(:disabled) {
    background: var(--color-interactive-hover);
    border-color: var(--color-interactive-hover);
  }

  .btn.ghost {
    background: transparent;
  }
</style>
