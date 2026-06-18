<!--
  DataTable.svelte — DuckDB buffer registration wrapper.

  Receives a table payload (base64 Parquet), registers it in DuckDB-WASM under a
  process-unique file name, creates a view, then renders DataTableView.

  Props:
    payload  { data: string, total_rows: number }  — base64 Parquet + row count

  Dependencies: $lib/duckdb.js, ./DataTableView.svelte
  Exports: None (render-only component)
  Side-effects: Registers a file buffer and creates a view in DuckDB-WASM.

  Lifecycle note: the parent {#each} is not keyed and `cell_start` clears records
  on every run, so each refresh remounts this component. A process-unique name
  per mount means a buffer is never re-registered under a still-live file name
  (which left a stale handle -> "No magic bytes found at end of file"), and a
  late async teardown of an old mount can never clobber a new one. Teardown drops
  the view AND the file buffer.
-->
<script module lang="ts">
  let _seq = 0;
  const nextName = () => `t_${_seq++}`;
</script>

<script lang="ts">
  import { onDestroy } from "svelte";
  import { getDb } from "$lib/duckdb";
  import DataTableView from "./DataTableView.svelte";

  let { payload } = $props();

  const viewName = nextName();
  const bufName = `_nb_${viewName}.parquet`;

  let conn = null;

  const ready = getDb().then(async (db) => {
    const buf = Uint8Array.from(atob(payload.data), (c) => c.charCodeAt(0));
    await db.registerFileBuffer(bufName, buf);
    conn = await db.connect();
    await conn.query(`CREATE OR REPLACE VIEW "${viewName}" AS FROM '${bufName}'`);
    return conn;
  });

  onDestroy(async () => {
    try {
      if (conn) {
        await conn.query(`DROP VIEW IF EXISTS "${viewName}"`);
        await conn.close();
      }
    } finally {
      const db = await getDb();
      db.dropFile?.(bufName);
    }
  });
</script>

{#await ready}
  <p class="db-loading">Loading query engine…</p>
{:then resolvedConn}
  <DataTableView conn={resolvedConn} {viewName} totalRows={payload.total_rows} />
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
