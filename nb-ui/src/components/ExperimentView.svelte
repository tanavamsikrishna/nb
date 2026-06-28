<!--
  ExperimentView.svelte — read-only view of one saved run (?path=X&run=R).

  Fetches GET /experiment?path=&run_id= and renders the run's metadata, params,
  source code, and saved outputs. The saved `cells` are byte-for-byte the daemon's
  render-state shape, so they render through the same Cell.svelte the live stream
  uses — no SSE involved.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import type { ExperimentDetail } from "../lib/types";
  import AppShell from "./AppShell.svelte";
  import NotebookView from "./NotebookView.svelte";

  let { path, runId }: { path: string; runId: string } = $props();

  // $state.raw (not $state): the fetched run is rendered through the shared
  // Cell.svelte, whose plotly/altair actions hand record payloads straight to
  // Plotly/Vega — libraries that MUTATE the data array in place. A deep $state
  // proxy would turn those writes into reactive updates, re-invoking the action
  // and looping forever (the live page avoids this by using plain store objects,
  // not runes). $state.raw keeps the nested cells/records as plain objects while
  // still re-rendering when `detail` is reassigned.
  let experimentDetail = $state.raw<ExperimentDetail | null>(null);
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
      experimentDetail = (await resp.json()) as ExperimentDetail;
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
    <a class="logo-sub logo-link" href={experimentsHref()}>experiments</a>
    <span class="logo-separator">/</span>
    <span class="notebook-name">{name}</span>
  {/snippet}

  {#if loaded && experimentDetail}
    <div class="run-meta">
      <span class="run-status {experimentDetail.meta.status}"
        >{experimentDetail.meta.status}</span
      >
      <span class="run-when">{when(experimentDetail.meta.started_at)}</span>
      <span class="run-id">{experimentDetail.meta.run_id}</span>
    </div>

    {#if Object.keys(experimentDetail.meta.params).length > 0}
      <section class="block">
        <h3>Parameters</h3>
        <table class="params-table">
          <tbody>
            {#each Object.entries(experimentDetail.meta.params) as [key, value]}
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

    <NotebookView
      cells={experimentDetail.cells}
      docstring={experimentDetail.docstring}
      code={experimentDetail.code}
    />
  {:else if loaded}
    <div class="empty-state">
      <h2>Run not found</h2>
      {#if failed}
        <p>Couldn't load this run. Is the daemon running?</p>
      {/if}
    </div>
  {/if}
</AppShell>

<style>
  .run-meta {
    display: flex;
    align-items: center;
    gap: 12px;
    font-family: var(--font-sans);
    font-size: 0.85rem;
    margin-bottom: 24px;
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
</style>
