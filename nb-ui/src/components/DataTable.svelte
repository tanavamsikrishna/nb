<!--
  DataTable.svelte — DuckDB buffer registration wrapper.

  Receives a table payload (base64 Parquet), registers it in DuckDB-WASM,
  creates a uniquely named view, then renders DataTableView.

  Props:
    payload      { data: string, total_rows: number }  — base64 Parquet + row count
    cellId       number  — cell's positional serial index
    recordIndex  number  — record's position within cell.records

  Dependencies: $lib/duckdb.js, ./DataTableView.svelte
  Exports: None (render-only component)
  Side-effects: Registers a file buffer and creates a view in DuckDB-WASM.
  Constraints: Must be used inside Cell.svelte where cellId and recordIndex are available.
-->
<script>
  import { onDestroy } from "svelte";
  import { getDb } from "$lib/duckdb.js";
  import DataTableView from "./DataTableView.svelte";

  let { payload, cellId, recordIndex } = $props();

  const viewName = `t_${cellId}_${recordIndex}`;
  const bufName = `_nb_${viewName}.parquet`;

  let conn = $state(null);

  const ready = getDb().then(async (db) => {
    const buf = Uint8Array.from(atob(payload.data), (c) => c.charCodeAt(0));
    await db.registerFileBuffer(bufName, buf);
    conn = await db.connect();
    await conn.query(
      `CREATE OR REPLACE VIEW "${viewName}" AS FROM '${bufName}'`,
    );
    return conn;
  });

  onDestroy(async () => {
    if (conn) {
      await conn.query(`DROP VIEW IF EXISTS "${viewName}"`);
      await conn.close();
    }
  });
</script>

{#await ready}
  <p class="db-loading">Loading query engine…</p>
{:then conn}
  <DataTableView {conn} {viewName} totalRows={payload.total_rows} />
{:catch err}
  <p class="db-error">Failed to initialize: {err.message}</p>
{/await}

<style>
  .db-loading {
    font-size: 0.85rem;
    color: var(--fg-secondary);
    font-style: italic;
    padding: 8px 0;
  }

  .db-error {
    font-size: 0.85rem;
    color: var(--color-error);
    font-weight: 500;
    padding: 8px 0;
  }
</style>
