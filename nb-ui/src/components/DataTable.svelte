<!--
  DataTable.svelte — DuckDB buffer registration wrapper.

  Receives a table payload (base64 Parquet), registers it in DuckDB-WASM under a
  file name, creates a view, then renders DataTableView.

  Props:
    payload  { data: string, total_rows: number }  — base64 Parquet + row count

  Dependencies: $lib/duckdb.js, ./DataTableView.svelte
  Exports: None (render-only component)
  Side-effects: Registers a file buffer and creates a view in DuckDB-WASM.

  Lifecycle note: outputs are updated in place across runs (see stream.ts), so
  this component is NOT remounted on re-run — instead `payload` changes. The view
  name (`viewName`) is stable for the component's life so DataTableView's SQL
  editor state stays valid; on each new payload we register a fresh buffer under
  a registration-unique file name, repoint the stable view at it, drop the old
  buffer, and bump `reload` so DataTableView re-executes. Registration-unique
  buffer names (vs. re-registering one name) avoid the stale-handle "No magic
  bytes found at end of file" bug and let a late async teardown never clobber a
  live buffer. Teardown drops the view AND the current file buffer.
-->
<script module lang="ts">
  let _seq = 0;
  const nextName = () => `t_${_seq++}`;
</script>

<script lang="ts">
  import { onDestroy } from "svelte";
  import type { AsyncDuckDB, AsyncDuckDBConnection } from "@duckdb/duckdb-wasm";
  import { getDb } from "$lib/duckdb";
  import type { TablePayload } from "$lib/types";
  import DataTableView from "./DataTableView.svelte";

  let { payload }: { payload: TablePayload } = $props();

  const viewName = nextName();

  let conn: AsyncDuckDBConnection | null = null;
  let bufSeq = 0;
  let currentBuf: string | null = null; // file name the stable view currently points at
  let lastData: string | null = null; // last payload.data registered (skip redundant work)
  let reload = $state(0); // bump to signal DataTableView to re-execute

  // Register payload.data as a fresh buffer and repoint the stable view at it,
  // then drop the previously-registered buffer.
  async function register(db: AsyncDuckDB, data: string) {
    const newBuf = `_nb_${viewName}_${bufSeq++}.parquet`;
    const buf = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
    await db.registerFileBuffer(newBuf, buf);
    await conn.query(
      `CREATE OR REPLACE VIEW "${viewName}" AS FROM '${newBuf}'`,
    );
    const prev = currentBuf;
    currentBuf = newBuf;
    if (prev) db.dropFile?.(prev);
    lastData = data;
  }

  const ready = getDb().then(async (db) => {
    conn = await db.connect();
    await register(db, payload.data);
    return conn;
  });

  // React to subsequent payload changes (the initial render is handled by the
  // `ready` promise above, so skip the effect's first invocation).
  let primed = false;
  $effect(() => {
    const data = payload.data; // track
    if (!primed) {
      primed = true;
      return;
    }
    if (data === lastData) return;
    (async () => {
      await ready; // ensure conn exists
      const db = await getDb();
      await register(db, data);
      reload++; // tell DataTableView to re-run its current query
    })();
  });

  onDestroy(async () => {
    try {
      if (conn) {
        await conn.query(`DROP VIEW IF EXISTS "${viewName}"`);
        await conn.close();
      }
    } finally {
      const db = await getDb();
      if (currentBuf) db.dropFile?.(currentBuf);
    }
  });
</script>

{#await ready}
  <p class="db-loading">Loading query engine…</p>
{:then resolvedConn}
  <DataTableView
    conn={resolvedConn}
    {viewName}
    totalRows={payload.total_rows}
    {reload}
  />
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
