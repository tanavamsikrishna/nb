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
  import PlotlyOutput from "./PlotlyOutput.svelte";
  import AltairOutput from "./AltairOutput.svelte";
  import type { Cell } from "../lib/types";

  // Svelte 5 props
  let { cell }: { cell: Cell } = $props();

  // Each output type has its own renderer component (Markdown, DataTable,
  // PlotlyOutput, AltairOutput, JSONTree). The plotly/altair components own the
  // $state.snapshot boundary that detaches proxied payloads before their
  // mutating libraries touch them (see PlotlyOutput.svelte).
</script>

<!-- A cell with no output renders nothing at all — no header, no container.
     (Output-less and not-yet-emitted cells are simply absent from the view.) -->
{#if cell.records.length > 0}
  <div
    class="cell-container {cell.status} {cell.stale ? 'stale' : ''} {cell.absent
      ? 'absent'
      : ''}"
  >
    <!-- Cell Header / Status Bar -->
    <div class="cell-header">
      <div class="left-header">
        {#if cell.status === "running"}
          <div class="run-dot" aria-hidden="true"></div>
        {/if}
        <span class="cell-num">Cell {cell.id + 1}</span>
        {#if cell.title}
          <span class="cell-title">{cell.title}</span>
        {/if}
        {#if cell.stale}
          <span class="stale-badge">Stale</span>
        {/if}
      </div>
    </div>

    <!-- Cell Outputs -->
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
            <PlotlyOutput payload={record.payload} />
          {:else if record.type === "altair"}
            <AltairOutput payload={record.payload} />
          {:else if record.type === "object"}
            <div class="object-output">
              <JSONTree val={record.payload} />
            </div>
          {:else if record.type === "text"}
            <pre class="text-output">{record.payload}</pre>
          {/if}
        </div>
      {/each}
    </div>
  </div>
{/if}

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

  .cell-num {
    font-size: 11px;
    font-weight: 600;
    color: var(--fg-tertiary);
    font-family: var(--font-mono);
    flex-shrink: 0;
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

  .object-output {
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 12px;
    overflow-x: auto;
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
</style>
