<!--
  ExperimentsList.svelte — run history for one notebook (?view=experiments&path=).

  Fetches GET /experiments?path= (a parent/child forest, newest-first) and lists
  each full run with its partial child runs nested underneath. Every run links to
  its read-only viewer at ?path=<path>&run=<run_id>.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import type { ExperimentRun, ExperimentsResponse } from "../lib/types";

  let { path }: { path: string } = $props();

  let runs = $state<ExperimentRun[]>([]);
  let loaded = $state(false);
  let failed = $state(false);

  let name = $derived(path.split("/").pop() || path);

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

  function paramSummary(params: Record<string, unknown>): string {
    const entries = Object.entries(params);
    if (entries.length === 0) return "";
    return entries
      .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
      .join("  ·  ");
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

<div class="app-wrapper">
  <header class="app-header">
    <div class="header-content">
      <div class="logo-area">
        <a class="logo-nb logo-home" href="/" title="All notebooks">nb</a>
        <span class="logo-separator">/</span>
        <span class="logo-sub">experiments</span>
        <span class="notebook-name">{name}</span>
      </div>
    </div>
  </header>

  <main class="main-container">
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
  </main>
</div>

{#snippet runRow(run: ExperimentRun, isChild: boolean)}
  <a class="run-item {isChild ? 'child' : ''}" href={runHref(run.run_id)}>
    <span class="run-top">
      <span class="run-kind {run.kind}">{run.kind}</span>
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
{/snippet}

<style>
  .app-wrapper {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }

  .app-header {
    background: var(--bg-header);
    border-bottom: 1px solid var(--border-default);
    position: sticky;
    top: 0;
    z-index: 50;
  }

  .header-content {
    max-width: 960px;
    margin: 0 auto;
    padding: 16px 24px;
    display: flex;
    align-items: center;
  }

  .logo-area {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
    font-family: var(--font-sans);
  }

  .logo-nb {
    font-size: 1.5rem;
    background: linear-gradient(
      135deg,
      var(--color-primary) 0%,
      var(--color-secondary) 100%
    );
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.05em;
  }

  .logo-home {
    text-decoration: none;
    cursor: pointer;
  }

  .logo-separator {
    color: var(--border-default);
    font-weight: 300;
  }

  .logo-sub {
    font-size: 0.875rem;
    color: var(--fg-secondary);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }

  .notebook-name {
    font-size: 0.8rem;
    color: var(--fg-tertiary);
    font-family: var(--font-mono);
    font-weight: 400;
    margin-left: 8px;
    padding: 2px 8px;
    background: var(--bg-sunken);
    border-radius: var(--radius-sm);
  }

  .main-container {
    max-width: 960px;
    width: 100%;
    margin: 0 auto;
    padding: 40px 24px;
    flex-grow: 1;
    box-sizing: border-box;
  }

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

  .run-item {
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

  .run-item.child {
    background: var(--bg-elevated);
  }

  .run-top {
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: var(--font-sans);
    font-size: 0.8rem;
  }

  .run-kind {
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    padding: 2px 8px;
    border-radius: var(--radius-full);
    background: var(--bg-sunken);
    color: var(--fg-secondary);
  }

  .run-kind.full {
    color: var(--color-primary);
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

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    background: var(--bg-muted);
    border: 1px dashed var(--border-subtle);
    border-radius: var(--radius-xl);
    padding: 60px 40px;
    margin-top: 40px;
  }

  .empty-state h2 {
    font-size: 1.5rem;
    font-weight: 600;
    margin: 0 0 12px;
    color: var(--fg-primary);
    font-family: var(--font-sans);
  }

  .empty-state p {
    color: var(--fg-secondary);
    max-width: 400px;
    font-size: 0.95rem;
    line-height: 1.6;
    margin: 0;
  }
</style>
