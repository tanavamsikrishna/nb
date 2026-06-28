<!--
  ExperimentView.svelte — read-only view of one saved run (?path=X&run=R).

  Fetches GET /experiment?path=&run_id= and renders the run's metadata, params,
  source code, and saved outputs. The saved `cells` are byte-for-byte the daemon's
  render-state shape, so they render through the same Cell.svelte the live stream
  uses — no SSE involved.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import Cell from "./Cell.svelte";
  import type { ExperimentDetail } from "../lib/types";

  let { path, runId }: { path: string; runId: string } = $props();

  // $state.raw (not $state): the fetched run is rendered through the shared
  // Cell.svelte, whose plotly/altair actions hand record payloads straight to
  // Plotly/Vega — libraries that MUTATE the data array in place. A deep $state
  // proxy would turn those writes into reactive updates, re-invoking the action
  // and looping forever (the live page avoids this by using plain store objects,
  // not runes). $state.raw keeps the nested cells/records as plain objects while
  // still re-rendering when `detail` is reassigned.
  let detail = $state.raw<ExperimentDetail | null>(null);
  let loaded = $state(false);
  let failed = $state(false);

  let name = $derived(path.split("/").pop() || path);

  function experimentsHref(): string {
    return "/?view=experiments&path=" + encodeURIComponent(path);
  }

  function when(iso: string): string {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleString();
  }

  async function load() {
    try {
      const resp = await fetch(
        "/experiment?path=" +
          encodeURIComponent(path) +
          "&run_id=" +
          encodeURIComponent(runId),
      );
      if (!resp.ok) throw new Error(String(resp.status));
      detail = (await resp.json()) as ExperimentDetail;
      failed = false;
    } catch {
      failed = true;
    } finally {
      loaded = true;
    }
  }

  onMount(load);

  let visibleCells = $derived(
    (detail?.cells ?? []).filter((c) => c.records.length > 0),
  );
</script>

<div class="app-wrapper">
  <header class="app-header">
    <div class="header-content">
      <div class="logo-area">
        <a class="logo-nb logo-home" href="/" title="All notebooks">nb</a>
        <span class="logo-separator">/</span>
        <a class="logo-sub logo-link" href={experimentsHref()}>experiments</a>
        <span class="logo-separator">/</span>
        <span class="notebook-name">{name}</span>
      </div>
    </div>
  </header>

  <main class="main-container">
    {#if loaded && detail}
      <div class="run-meta">
        <span class="run-kind {detail.meta.kind}">{detail.meta.kind}</span>
        <span class="run-status {detail.meta.status}">{detail.meta.status}</span
        >
        <span class="run-when">{when(detail.meta.started_at)}</span>
        <span class="run-id">{detail.meta.run_id}</span>
      </div>

      {#if Object.keys(detail.meta.params).length > 0}
        <section class="block">
          <h3>Parameters</h3>
          <table class="params-table">
            <tbody>
              {#each Object.entries(detail.meta.params) as [key, value]}
                <tr>
                  <th>{key}</th>
                  <td
                    >{typeof value === "object" && value !== null
                      ? JSON.stringify(value)
                      : String(value)}</td
                  >
                </tr>
              {/each}
            </tbody>
          </table>
        </section>
      {/if}

      {#if visibleCells.length > 0}
        <section class="block">
          <h3>Outputs</h3>
          <div class="cells-list">
            {#each visibleCells as cell (cell.id)}
              <Cell {cell} />
            {/each}
          </div>
        </section>
      {/if}

      <section class="block">
        <details>
          <summary>Source code</summary>
          <pre class="code-block">{detail.code}</pre>
        </details>
      </section>
    {:else if loaded}
      <div class="empty-state">
        <h2>Run not found</h2>
        {#if failed}
          <p>Couldn't load this run. Is the daemon running?</p>
        {/if}
      </div>
    {/if}
  </main>
</div>

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

  .logo-link {
    text-decoration: none;
  }

  .logo-link:hover {
    text-decoration: underline;
  }

  .notebook-name {
    font-size: 0.8rem;
    color: var(--fg-tertiary);
    font-family: var(--font-mono);
    font-weight: 400;
    text-transform: none;
    letter-spacing: normal;
    margin-left: 0;
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

  .run-meta {
    display: flex;
    align-items: center;
    gap: 12px;
    font-family: var(--font-sans);
    font-size: 0.85rem;
    margin-bottom: 24px;
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

  .run-id {
    color: var(--fg-tertiary);
    font-family: var(--font-mono);
    font-size: 0.75rem;
  }

  .block {
    margin-bottom: 32px;
  }

  .block h3 {
    font-family: var(--font-sans);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--fg-secondary);
    margin: 0 0 12px;
  }

  .params-table {
    border-collapse: collapse;
    font-family: var(--font-mono);
    font-size: 0.85rem;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    overflow: hidden;
  }

  .params-table th {
    text-align: left;
    font-weight: 600;
    color: var(--fg-secondary);
    background: var(--bg-header);
    padding: 6px 12px;
    border-bottom: 1px solid var(--border-subtle);
    border-right: 1px solid var(--border-subtle);
    white-space: nowrap;
  }

  .params-table td {
    padding: 6px 12px;
    color: var(--fg-primary);
    border-bottom: 1px solid var(--border-subtle);
  }

  .params-table tr:last-child th,
  .params-table tr:last-child td {
    border-bottom: none;
  }

  .cells-list {
    display: flex;
    flex-direction: column;
  }

  summary {
    cursor: pointer;
    font-family: var(--font-sans);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--fg-secondary);
  }

  .code-block {
    margin: 12px 0 0;
    padding: 16px;
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    font-family: var(--font-mono);
    font-size: 0.8rem;
    line-height: 1.5;
    color: var(--fg-primary);
    overflow-x: auto;
    white-space: pre;
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
    font-size: 0.95rem;
    margin: 0;
  }
</style>
