<!--
  Cell.svelte — Single notebook cell with status header and output renderer.

  Displays a cell's status (pending/running/done/error), optional profiling
  stats, and renders all output records (markdown, table, HTML, Plotly,
  Altair, JSON object, plain text).

  Props:
    cell  Object  — cell data from the cells store (id, status, records, profiling, etc.)

  Dependencies:
    - marked            (markdown → HTML)
    - JSONTree.svelte   (recursive object renderer)
    - DataTable.svelte  (DuckDB-backed table viewer)
    - lib/lazy_load.js  (loadPlotly, loadVega — deferred heavy libs)

  Exports: None (render-only component).
  Side-effects: Lazy-loads Plotly/Vega on first use via Svelte actions.
  Constraints: Svelte 5 runes ($props, $state, $derived).
-->
<script lang="ts">
  import { marked } from "marked";
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
          Plotly.newPlot(
            node,
            payload.data,
            payload.layout,
            payload.config || {},
          );
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
  <div class="cell-header">
    <div class="left-header">
      <span class="status-indicator"></span>
      {#if cell.cell_header}
        <span class="cell-header">{cell.cell_header}</span>
      {/if}
      {#if cell.stale}
        <span class="stale-badge">Stale</span>
      {/if}
    </div>

    {#if cell.profiling}
      <div class="profiling-stats">
        <span class="stat-item">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            class="icon"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm.5-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z"
              clip-rule="evenodd"
            />
          </svg>
          {cell.profiling.wall_ms}ms wall
        </span>
        <span class="stat-divider">•</span>
        <span class="stat-item">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            class="icon"
          >
            <path
              d="M12 9a1 1 0 011-1h3a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1V9z"
            />
            <path
              fill-rule="evenodd"
              d="M19.307 2.193a.75.75 0 00-1.147-.193l-3.58 3.033A2.247 2.247 0 0013.25 5H6.75A2.25 2.25 0 004.5 7.25v5.5A2.25 2.25 0 006.75 15h6.5a2.24 2.24 0 001.33-.433l3.58 3.033a.75.75 0 001.147-.193c.12-.224.08-.502-.103-.686l-2.029-2.03A3.722 3.722 0 0018 12.75v-5.5c0-1.042-.435-1.983-1.135-2.656l2.029-2.03a.75.75 0 00.413-.671zM15 7.25v5.5a.75.75 0 01-.75.75h-6.5a.75.75 0 01-.75-.75v-5.5a.75.75 0 01.75-.75h6.5a.75.75 0 01.75.75z"
              clip-rule="evenodd"
            />
          </svg>
          {cell.profiling.cpu_ms}ms cpu
        </span>
      </div>
    {/if}
  </div>

  <!-- Cell Outputs -->
  {#if cell.records.length != 0}
    <div class="cell-outputs">
      {#each cell.records as record, i}
        <div class="output-item">
          {#if record.type === "md"}
            <div class="markdown-output">
              {@html marked.parse(record.payload)}
            </div>
          {:else if record.type === "table"}
            <DataTable
              payload={record.payload}
              cellId={cell.id}
              recordIndex={i}
            />
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
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    margin-bottom: 20px;
    overflow: hidden;
    transition:
      border-color 0.3s ease,
      box-shadow 0.3s ease,
      opacity 0.3s ease;
    box-shadow: var(--shadow-md);
  }

  .cell-container:hover {
    border-color: var(--border-default);
  }

  /* Status specific styles */
  .cell-container.running {
    border-color: var(--color-primary);
    box-shadow: 0 0 15px rgba(139, 105, 20, 0.2);
  }

  .cell-container.error {
    border-color: var(--color-error);
    box-shadow: 0 0 15px rgba(192, 57, 43, 0.15);
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
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 16px;
    background: var(--bg-header);
    border-bottom: 1px solid var(--border-subtle);
  }

  .left-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .status-indicator {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: var(--fg-secondary);
    transition:
      background-color 0.3s ease,
      box-shadow 0.3s ease;
  }

  .cell-container.pending .status-indicator {
    background-color: var(--fg-secondary);
  }

  .cell-container.running .status-indicator {
    background-color: var(--color-primary);
    box-shadow: 0 0 8px var(--color-primary);
    animation: pulse 1.5s infinite alternate;
  }

  .cell-container.done .status-indicator {
    background-color: var(--color-success);
    box-shadow: 0 0 6px rgba(46, 125, 50, 0.4);
  }

  .cell-container.error .status-indicator {
    background-color: var(--color-error);
    box-shadow: 0 0 8px var(--color-error);
  }

  .cell-name {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--fg-secondary);
    font-family: var(--font-sans);
  }

  .cell-header {
    background: rgba(139, 105, 20, 0.12);
    color: var(--color-primary);
    border: 1px solid rgba(139, 105, 20, 0.2);
    padding: 2px 8px;
    border-radius: var(--radius-full);
    font-size: 0.75rem;
    font-weight: 500;
  }

  .stale-badge {
    background: rgba(196, 154, 60, 0.12);
    color: var(--color-warning);
    border: 1px solid rgba(196, 154, 60, 0.2);
    padding: 2px 8px;
    border-radius: var(--radius-full);
    font-size: 0.75rem;
    font-weight: 500;
  }

  .profiling-stats {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.75rem;
    color: var(--fg-secondary);
  }

  .stat-item {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .icon {
    width: 12px;
    height: 12px;
    opacity: 0.7;
  }

  .stat-divider {
    color: var(--border-default);
  }

  /* Outputs Area */
  .cell-outputs {
    padding: 16px;
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

  /* Markdown custom overrides */
  .markdown-output {
    font-size: 0.95rem;
    line-height: 1.6;
    color: var(--fg-primary);
  }

  .markdown-output :global(p) {
    margin-top: 0;
    margin-bottom: 12px;
  }

  .markdown-output :global(p:last-child) {
    margin-bottom: 0;
  }

  .markdown-output :global(pre) {
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 12px;
    overflow-x: auto;
  }

  .markdown-output :global(code) {
    font-family: var(--font-mono);
    font-size: 0.85em;
    background: var(--bg-muted);
    padding: 1px 3px;
    border-radius: var(--radius-sm);
    color: var(--color-accent);
    line-height: 1;
  }

  .markdown-output :global(h1),
  .markdown-output :global(h2),
  .markdown-output :global(h3) {
    font-family: var(--font-sans);
    color: var(--fg-primary);
    margin-top: 16px;
    margin-bottom: 8px;
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

  @keyframes pulse {
    0% {
      opacity: 0.6;
    }
    100% {
      opacity: 1;
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
