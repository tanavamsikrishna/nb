<!--
  DataTableView.svelte — Interactive table with SQL query.

  Receives a DuckDB connection and view name, manages all interactive state:
  SQL editing, display limited to first 25 rows.

  Props:
    conn       AsyncDuckDB.Connection  — active DuckDB connection
    viewName   string  — name of the registered view (e.g. "t_2_0")
    totalRows  number  — total rows in the original DataFrame

  Dependencies: None (receives conn from parent)
  Exports: None (render-only component)
  Side-effects: Executes SQL queries against DuckDB on user interaction.
  Constraints: conn must be an active AsyncDuckDB connection.
-->
<script lang="ts">
  const MAX_DISPLAY_ROWS = 25;

  const { conn, viewName, totalRows } = $props();

  const defaultSql = `SELECT * FROM ${viewName} `;
  let sql = $state(defaultSql);
  let submittedSql = $state(defaultSql);
  let dirty = $derived(sql !== submittedSql);

  let rows = $state([]);
  let columns = $state([]);
  let totalResultRows = $state(0);
  let queryError = $state(null);
  let loading = $state(false);

  async function execute() {
    loading = true;
    queryError = null;
    try {
      const dataResult = await conn.query(submittedSql);
      totalResultRows = dataResult.numRows;

      // Extract columns from Arrow schema
      columns = dataResult.schema.fields.map((f) => ({
        name: f.name,
        numeric: isNumericType(f.type),
      }));

      // Convert Arrow table to array of row objects (first 25 only)
      const displayRows = Math.min(dataResult.numRows, MAX_DISPLAY_ROWS);
      rows = [];
      for (let i = 0; i < displayRows; i++) {
        const row = {};
        for (const col of columns) {
          const val = dataResult.getChild(col.name)?.get(i);
          row[col.name] = val === null || val === undefined ? null : val;
        }
        rows.push(row);
      }
    } catch (err) {
      queryError = err.message;
    } finally {
      loading = false;
    }
  }

  function isNumericType(type) {
    const typeId = type?.typeId;
    // Arrow type IDs: Int = 2, Float = 3, Decimal = 7
    return typeId === 2 || typeId === 3 || typeId === 7;
  }

  const SIG_FIGS = 5;

  // Round a number (or Int64 BigInt) to SIG_FIGS significant digits for display.
  // Trailing zeros from the rounding are dropped (via Number()), so e.g.
  // 123456 -> "123460", 0.123456 -> "0.12346", 1.5 -> "1.5".
  function toSigFigs(value) {
    const num = typeof value === "bigint" ? Number(value) : value;
    if (!Number.isFinite(num)) return String(value);
    if (num === 0) return "0";
    return String(Number(num.toPrecision(SIG_FIGS)));
  }

  // Value shown in the cell: numeric columns are rounded to SIG_FIGS; the full
  // value is preserved in the cell's title tooltip (see template).
  function displayValue(value, numeric) {
    if (numeric && (typeof value === "number" || typeof value === "bigint")) {
      return toSigFigs(value);
    }
    return value;
  }

  function submit() {
    submittedSql = sql;
    execute();
  }

  function reset() {
    sql = defaultSql;
    submittedSql = defaultSql;
    execute();
  }

  function handleKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  // Initial execution
  execute();
</script>

<div class="table-wrapper">
  <!-- Query Box -->
  <div class="query-bar">
    <input
      type="text"
      class="query-input"
      bind:value={sql}
      onkeydown={handleKeydown}
      spellcheck="false"
      placeholder="Enter SQL query..."
    />
    <button class="btn btn-run" class:dirty onclick={submit} disabled={loading}>
      Run{dirty ? " ●" : ""}
    </button>
    <button class="btn btn-reset" onclick={reset}>Reset</button>
  </div>

  <!-- Error Display -->
  {#if queryError}
    <div class="query-error">{queryError}</div>
  {/if}

  <!-- Data Table -->
  <div class="table-scroll" class:dimmed={loading}>
    <table>
      <thead>
        <tr>
          {#each columns as col}
            <th class:numeric={col.numeric} title={col.name}>
              <span class="col-name">{col.name}</span>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each rows as row, i (i)}
          <tr>
            {#each columns as col}
              <td
                class:numeric={col.numeric}
                title={row[col.name] === null ? "" : String(row[col.name])}
              >
                {#if row[col.name] === null}
                  <span class="null-val">—</span>
                {:else}
                  {displayValue(row[col.name], col.numeric)}
                {/if}
              </td>
            {/each}
          </tr>
        {:else}
          <tr>
            <td colspan={columns.length || 1} class="empty-msg">
              No results
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <!-- Footer -->
  <div class="footer">
    {rows.length} of {totalResultRows.toLocaleString()} rows shown ({totalRows.toLocaleString()}
    total in table)
  </div>
</div>

<style>
  .table-wrapper {
    font-family: var(--font-mono);
    font-size: 0.85rem;
    margin-top: 8px;
  }

  /* Query Bar */
  .query-bar {
    display: flex;
    gap: 8px;
    margin-bottom: 8px;
    align-items: center;
  }

  .query-input {
    flex: 1;
    font-family: var(--font-mono);
    font-size: 0.85rem;
    background: var(--bg-sunken);
    color: var(--fg-primary);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    padding: 8px 12px;
    outline: none;
    transition: border-color 0.2s;
  }

  .query-input:focus {
    border-color: var(--color-primary);
  }

  .btn {
    font-size: 0.8rem;
    font-weight: 500;
    padding: 8px 14px;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-default);
    background: var(--bg-muted);
    color: var(--fg-primary);
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }

  .btn:hover:not(:disabled) {
    background: var(--bg-header);
    border-color: var(--border-default);
  }

  .btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .btn-run.dirty {
    border-color: var(--color-primary);
    color: var(--color-primary);
    font-weight: 600;
  }

  .btn-reset {
    color: var(--fg-secondary);
  }

  /* Error */
  .query-error {
    font-family: var(--font-mono);
    font-size: 0.8rem;
    color: var(--color-error);
    background: rgba(192, 57, 43, 0.06);
    border: 1px solid rgba(192, 57, 43, 0.15);
    border-radius: var(--radius-md);
    padding: 8px 12px;
    margin-bottom: 8px;
    white-space: pre-wrap;
  }

  /* Table */
  .table-scroll {
    overflow-x: auto;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    transition: opacity 0.2s;
    /* Shrink-wrap the bordered box to the table, but never exceed the
       container — at which point overflow-x scrolls. The query bar above is a
       separate full-width element, so it keeps its width. */
    width: fit-content;
    max-width: 100%;
  }

  .table-scroll.dimmed {
    opacity: 0.4;
  }

  table {
    border-collapse: collapse;
    /* Table hugs the combined width of its columns; each column hugs its own
       content (table-layout: auto). When that exceeds the container the
       .table-scroll wrapper scrolls horizontally. */
    width: max-content;
    table-layout: auto;
    font-size: 0.85rem;
  }

  thead th {
    background: var(--bg-header);
    color: var(--fg-primary);
    font-weight: 600;
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-default);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    /* Generous cap so a single long-value column can't dominate; content
       beyond this truncates with an ellipsis. */
    max-width: 480px;
  }

  thead th.numeric {
    text-align: right;
  }

  tbody td {
    padding: 6px 12px;
    border-bottom: 1px solid var(--border-subtle);
    color: var(--fg-primary);
    /* Hug content on one line, capped at the same generous max-width as the
       header; full value is available via the cell's title tooltip. */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 480px;
  }

  tbody td.numeric {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  tbody tr:hover {
    background: var(--bg-sunken);
  }

  .null-val {
    color: var(--fg-secondary);
    font-style: italic;
  }

  .empty-msg {
    text-align: center;
    color: var(--fg-secondary);
    font-style: italic;
    padding: 16px;
  }

  /* Footer */
  .footer {
    font-size: 0.75rem;
    color: var(--fg-secondary);
    padding-top: 6px;
    text-align: right;
  }
</style>
