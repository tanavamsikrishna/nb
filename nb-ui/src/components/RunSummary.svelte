<!--
  RunSummary.svelte — Per-run timing overview.

  Collects every executed cell's wall/cpu timing into a single table at the
  foot of the notebook, so individual cells stay uncluttered. Renders nothing
  until at least one cell has profiling data.

  Props:
    cells  Array  — the cells store value (id, title, profiling, status).

  Dependencies: none.
  Constraints: Svelte 5 runes ($props, $derived).
-->
<script lang="ts">
  let { cells = [] } = $props();

  // Only cells that actually ran carry profiling. Preserve run order by id.
  let timed = $derived(
    cells
      .filter((c) => c.profiling)
      .slice()
      .sort((a, b) => a.id - b.id),
  );

  let totalWall = $derived(
    timed.reduce((sum, c) => sum + (c.profiling.wall_ms || 0), 0),
  );
  let totalCpu = $derived(
    timed.reduce((sum, c) => sum + (c.profiling.cpu_ms || 0), 0),
  );
</script>

{#if timed.length > 0}
  <section class="run-summary">
    <div class="summary-title">Run timings</div>
    <table>
      <thead>
        <tr>
          <th class="col-cell">Cell</th>
          <th class="col-num">wall</th>
          <th class="col-num">cpu</th>
        </tr>
      </thead>
      <tbody>
        {#each timed as cell (cell.id)}
          <tr class:errored={cell.status === "error"}>
            <td class="col-cell">
              <span class="cell-num">{cell.id + 1}</span>
              {#if cell.title}<span class="cell-name">{cell.title}</span>{/if}
            </td>
            <td class="col-num">{cell.profiling.wall_ms}ms</td>
            <td class="col-num">{cell.profiling.cpu_ms}ms</td>
          </tr>
        {/each}
      </tbody>
      <tfoot>
        <tr>
          <td class="col-cell">Total</td>
          <td class="col-num">{totalWall}ms</td>
          <td class="col-num">{totalCpu}ms</td>
        </tr>
      </tfoot>
    </table>
  </section>
{/if}

<style>
  .run-summary {
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md, 6px);
    padding: 16px 20px;
    margin-top: 12px;
  }

  .summary-title {
    font-family: var(--font-sans);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--fg-secondary);
    margin-bottom: 10px;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-family: var(--font-mono);
    font-size: 12px;
  }

  th {
    text-align: left;
    font-weight: 500;
    color: var(--fg-tertiary);
    padding: 4px 8px;
    border-bottom: 1px solid var(--border-subtle);
  }

  td {
    padding: 4px 8px;
    border-bottom: 1px solid var(--border-subtle);
    color: var(--fg-primary);
  }

  tbody tr:last-child td {
    border-bottom: none;
  }

  .col-num {
    text-align: right;
    width: 80px;
    color: var(--fg-secondary);
  }

  .cell-num {
    display: inline-block;
    min-width: 1.4em;
    color: var(--fg-tertiary);
  }

  .cell-name {
    color: var(--fg-primary);
    margin-left: 6px;
  }

  tr.errored .cell-name {
    color: var(--color-error);
  }

  tfoot td {
    border-top: 1px solid var(--border-default);
    border-bottom: none;
    font-weight: 600;
    color: var(--fg-primary);
  }
</style>
