<!--
  Cell.svelte — Single notebook cell with status header and output renderer.

  Displays a cell's status (pending/running/done/error), optional profiling
  stats, and renders all output records (markdown, table, HTML, Plotly,
  Altair, JSON object, plain text).

  Props:
    cell  Object  — cell data from the cells store (id, status, records, profiling, etc.)

  Dependencies:
    - Markdown.svelte   (markdown rendering & typography)
    - JSONTree.svelte   (recursive object renderer)
    - DataTable.svelte  (DuckDB-backed table viewer)
    - lib/lazy_load.js  (loadPlotly, loadVega — deferred heavy libs)

  Exports: None (render-only component).
  Side-effects: Lazy-loads Plotly/Vega on first use via Svelte actions.
  Constraints: Svelte 5 runes ($props, $state, $derived).
-->
<script lang="ts">
  import Markdown from "./Markdown.svelte";
  import JSONTree from "./JSONTree.svelte";
  import DataTable from "./DataTable.svelte";
  import { loadPlotly, loadVega } from "../lib/lazy_load";

  // Svelte 5 props
  let { cell } = $props();

  // Svelte actions for third party rendering
  function plotlyAction(node, payload) {
    let active = true;
    loadPlotly()
      .then((Plotly) => {
        if (active) {
          // Default to a usable height; without one Plotly falls back to the
          // container's height  and collapses. The figure's own layout.height still wins if it sets one.
          const layout = { autosize: true, height: 450, ...payload.layout };
          const config = { responsive: true, ...(payload.config || {}) };
          Plotly.newPlot(node, payload.data, layout, config);
        }
      })
      .catch((err) => {
        if (active) {
          node.innerHTML = `<span class="error-msg">Failed to render Plotly: ${err.message || err}</span>`;
        }
      });

    return {
      destroy() {
        active = false;
      },
    };
  }

  function altairAction(node, payload) {
    let active = true;
    loadVega()
      .then((vegaEmbed) => {
        if (active) {
          vegaEmbed(node, payload, { actions: false });
        }
      })
      .catch((err) => {
        if (active) {
          node.innerHTML = `<span class="error-msg">Failed to render Altair: ${err.message || err}</span>`;
        }
      });

    return {
      destroy() {
        active = false;
      },
    };
  }
</script>

<div
  class="cell-container {cell.status} {cell.stale ? 'stale' : ''} {cell.absent
    ? 'absent'
    : ''}"
>
  <!-- Cell Header / Status Bar -->
  <div
    class="cell-header"
    class:no-output={cell.records.length === 0 && cell.status === "done"}
  >
    <div class="left-header">
      {#if cell.status === "running"}
        <div class="run-dot" aria-hidden="true"></div>
      {/if}
      {#if cell.title}
        <span class="cell-title">{cell.title}</span>
      {/if}
      {#if cell.stale}
        <span class="stale-badge">Stale</span>
      {/if}
    </div>

    {#if cell.profiling && (cell.profiling.wall_ms >= 1 || cell.profiling.cpu_ms >= 1)}
      <div class="cell-stats">
        <span>{cell.profiling.wall_ms}ms wall</span>
        <span>{cell.profiling.cpu_ms}ms cpu</span>
      </div>
    {/if}
  </div>

  <!-- Cell Outputs -->
  {#if cell.records.length != 0}
    <div class="cell-outputs">
      {#each cell.records as record}
        <div class="output-item">
          {#if record.type === "md"}
            <Markdown source={record.payload} variant="inline" />
          {:else if record.type === "table"}
            <DataTable payload={record.payload} />
          {:else if record.type === "html"}
            <div class="html-output">
              {@html record.payload}
            </div>
          {:else if record.type === "plotly"}
            <div class="plotly-output" use:plotlyAction={record.payload}></div>
          {:else if record.type === "altair"}
            <div class="altair-output" use:altairAction={record.payload}></div>
          {:else if record.type === "object"}
            <div class="object-output">
              <JSONTree val={record.payload} />
            </div>
          {:else if record.type === "text"}
            <pre class="text-output">{record.payload}</pre>
          {/if}
        </div>
      {:else}
        {#if cell.status === "pending"}
          <div class="placeholder-msg">Waiting for execution...</div>
        {:else if cell.status === "running" && cell.records.length === 0}
          <div class="placeholder-msg pulsing">Running cell...</div>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  .cell-container {
    background: var(--bg-elevated);
    border: 1px solid var(--border-default, #c4cad6);
    border-radius: 4px;
    margin-bottom: 20px;
    overflow: hidden;
    transition:
      border-color 0.3s ease,
      opacity 0.3s ease;
  }

  /* Running state */
  .cell-container.running {
    border-left: 2px solid var(--color-primary);
  }

  .cell-container.stale {
    opacity: 0.6;
    background: var(--bg-muted);
    border-style: dashed;
  }

  .cell-container.absent {
    opacity: 0.3;
    filter: grayscale(80%);
  }

  /* Header & Stats */
  .cell-header {
    background: var(--bg-header);
    border-bottom: 1px solid var(--border-default);
    padding: 7px 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .cell-header.no-output {
    border-bottom: none;
  }

  .left-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .run-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #b36200;
    margin-right: 7px;
    flex-shrink: 0;
    animation: nb-pulse 1.2s ease-in-out infinite;
  }

  .cell-name {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--fg-secondary);
    font-family: var(--font-sans);
  }

  .cell-title {
    color: var(--fg-primary);
    font-weight: 500;
    font-size: 12px;
    font-family: var(--font-sans);
    letter-spacing: 0.01em;
  }

  .stale-badge {
    background: rgba(74, 111, 165, 0.1);
    color: var(--color-warning);
    border: 1px solid rgba(74, 111, 165, 0.2);
    padding: 2px 8px;
    border-radius: var(--radius-full);
    font-size: 0.75rem;
    font-weight: 500;
  }

  .cell-stats {
    margin-left: auto;
    font-size: 10px;
    color: var(--fg-tertiary);
    font-family: var(--font-mono);
    display: flex;
    gap: 10px;
  }

  /* Outputs Area */
  .cell-outputs {
    background: var(--bg-elevated);
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .output-item {
    width: 100%;
  }

  .placeholder-msg {
    font-size: 0.85rem;
    color: var(--fg-secondary);
    font-style: italic;
  }

  .placeholder-msg.pulsing {
    color: var(--color-primary);
    animation: textPulse 1.5s infinite alternate;
  }

  /* Plain text rendering — unstyled, flows like markdown */
  .text-output {
    margin: 0;
    font-family: var(--font-serif);
    font-size: 0.95rem;
    line-height: 1.6;
    color: var(--fg-primary);
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* HTML tables and plots */
  .html-output :global(table) {
    font-family: var(--font-mono);
    border-collapse: collapse;
    width: 100%;
    font-size: 0.85rem;
    margin: 8px 0;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    overflow: hidden;
  }

  .html-output :global(th) {
    background: var(--bg-header);
    color: var(--fg-primary);
    font-weight: 600;
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-default);
  }

  .html-output :global(td) {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-subtle);
    color: var(--fg-primary);
  }

  .html-output :global(tr:hover) {
    background: var(--bg-sunken);
  }

  .plotly-output,
  .altair-output {
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 12px;
    min-height: 100px;
    overflow: hidden;
  }

  .object-output {
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 12px;
    overflow-x: auto;
  }

  .error-msg {
    color: var(--color-error);
    font-size: 0.85rem;
    font-weight: 500;
  }

  @keyframes nb-pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.3;
    }
  }

  @keyframes textPulse {
    0% {
      opacity: 0.5;
    }
    100% {
      opacity: 0.9;
    }
  }
</style>
