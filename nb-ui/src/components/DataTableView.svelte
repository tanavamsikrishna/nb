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
<script>
  const MAX_DISPLAY_ROWS = 25;

  let { conn, viewName, totalRows } = $props();

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
            <th class:numeric={col.numeric}>
              <span class="col-name">{col.name}</span>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each rows as row, i (i)}
          <tr>
            {#each columns as col}
              <td class:numeric={col.numeric}>
                {#if row[col.name] === null}
                  <span class="null-val">—</span>
                {:else}
                  {row[col.name]}
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
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 0.85rem;
    background: rgba(15, 23, 42, 0.6);
    color: #e2e8f0;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    padding: 8px 12px;
    outline: none;
    transition: border-color 0.2s;
  }

  .query-input:focus {
    border-color: rgba(99, 102, 241, 0.5);
  }

  .btn {
    font-size: 0.8rem;
    font-weight: 500;
    padding: 8px 14px;
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(30, 41, 59, 0.6);
    color: #cbd5e1;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }

  .btn:hover:not(:disabled) {
    background: rgba(51, 65, 85, 0.6);
    border-color: rgba(255, 255, 255, 0.15);
  }

  .btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .btn-run.dirty {
    border-color: rgba(99, 102, 241, 0.6);
    color: #a5b4fc;
    font-weight: 600;
  }

  .btn-reset {
    color: #94a3b8;
  }

  /* Error */
  .query-error {
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 0.8rem;
    color: #f87171;
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.2);
    border-radius: 6px;
    padding: 8px 12px;
    margin-bottom: 8px;
    white-space: pre-wrap;
  }

  /* Table */
  .table-scroll {
    overflow-x: auto;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    transition: opacity 0.2s;
  }

  .table-scroll.dimmed {
    opacity: 0.4;
  }

  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.85rem;
  }

  thead th {
    background: rgba(15, 23, 42, 0.6);
    color: #f1f5f9;
    font-weight: 600;
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    white-space: nowrap;
  }

  thead th.numeric {
    text-align: right;
  }

  tbody td {
    padding: 6px 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    color: #cbd5e1;
  }

  tbody td.numeric {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  tbody tr:hover {
    background: rgba(255, 255, 255, 0.02);
  }

  .null-val {
    color: #475569;
    font-style: italic;
  }

  .empty-msg {
    text-align: center;
    color: #475569;
    font-style: italic;
    padding: 16px;
  }

  /* Footer */
  .footer {
    font-size: 0.75rem;
    color: #475569;
    padding-top: 6px;
    text-align: right;
  }
</style>
