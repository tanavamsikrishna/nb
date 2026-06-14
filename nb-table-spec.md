# `nb` — Table Display: Specification

---

## 1. Python API

### 1.1 `Table` Wrapper

`Table` is a dataclass passed to `display()`. The existing `display()` function
dispatches on wrapper type to determine serialization and display record type.

```python
@dataclass
class Table:
    df: pl.DataFrame
```

Usage:

```python
display(Table(summary_df))
```

Truncation (`max_rows`) is deferred — see §8.

### 1.2 Serialization

Dispatched inside `display()` on `isinstance(obj, Table)`:

```python
import io, base64

def _serialize_table(obj: Table) -> dict:
    buf = io.BytesIO()
    obj.df.write_parquet(buf, compression="snappy")
    return {
        "data": base64.b64encode(buf.getvalue()).decode(),
        "total_rows": len(obj.df),
    }
```

### 1.3 Display Record

```python
DisplayRecord(type="table", payload=_serialize_table(obj))
```

Fits the existing SSE schema unchanged:

```
event: display_record
data: {"cell_id": 2, "type": "table", "payload": {"data": "<base64>", "total_rows": 42000}}
```

---

## 2. DuckDB-WASM Setup

### 2.1 Vite Configuration

DuckDB-WASM spawns an internal Web Worker. Vite's esbuild pre-bundler breaks
this. It must be excluded, and the WASM binary and worker script referenced via
Vite's `?url` suffix (which resolves to the correct hashed asset path after
build):

```javascript
// nb-ui/vite.config.js
export default defineConfig({
    plugins: [svelte()],
    optimizeDeps: {
        exclude: ['@duckdb/duckdb-wasm']
    },
    server: { proxy: { '/stream': 'http://localhost:7777' } }
});
```

### 2.2 Initialization Singleton

DuckDB is initialized once per browser session. `getDb()` returns a stable
promise — safe and cheap to call multiple times.

```javascript
// nb-ui/src/lib/duckdb.js
import * as duckdb from '@duckdb/duckdb-wasm';
import mvp_wasm   from '@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url';
import mvp_worker from '@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url';
import eh_wasm    from '@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url';
import eh_worker  from '@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url';

const BUNDLES = {
    mvp: { mainModule: mvp_wasm, mainWorker: mvp_worker },
    eh:  { mainModule: eh_wasm,  mainWorker: eh_worker  },
};

let _promise = null;

export function getDb() {
    if (!_promise) _promise = _init();
    return _promise;
}

async function _init() {
    const bundle = await duckdb.selectBundle(BUNDLES);
    const worker = new Worker(bundle.mainWorker);
    const db     = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(), worker);
    await db.instantiate(bundle.mainModule);
    return db;
}
```

### 2.3 Pre-warming

`getDb()` is called once at app startup in `stream.js`, before any table record
arrives. DuckDB-WASM (~8MB) is a lazy import, so this costs nothing on
notebooks with no tables after the first cached load:

```javascript
// nb-ui/src/lib/stream.js  (top of module, alongside EventSource setup)
import { getDb } from './duckdb.js';
getDb();  // fire-and-forget; warms the WASM load in background
```

---

## 3. Table Naming

Each `DataTable` instance derives a unique, deterministic view name from its
props:

```javascript
const viewName = `t_${cellId}_${recordIndex}`;  // e.g. "t_2_0", "t_5_1"
const bufName  = `_nb_${viewName}.parquet`;      // e.g. "_nb_t_2_0.parquet"
```

`cellId` is the cell's positional serial index (the DOM key, per main spec §4.5).
`recordIndex` is the record's position within the cell's `records` array.

For a typical notebook where each cell has at most one table, names are
`t_0_0`, `t_1_0`, `t_2_0`, etc. The view lives in DuckDB's default schema.
No schema management needed. Cleanup on destroy: `DROP VIEW IF EXISTS "t_2_0"`.

---

## 4. Query Model

### 4.1 Query Box

Pre-filled with the table's view name, e.g.:

```sql
FROM t_2_0
```

DuckDB supports `FROM`-first syntax (`SELECT *` implied). The user may freely
overwrite this with any valid DuckDB SQL — aggregations, CTEs, window
functions, etc.

### 4.2 Sorting

Column header clicks cycle: `unsorted → ASC → DESC → unsorted`.

Sort state wraps the user's SQL; the query box is never modified:

```sql
-- Sort active:
SELECT * FROM (<user_sql>) _q
ORDER BY "<col>" <ASC|DESC>
LIMIT <page_size> OFFSET <page * page_size>

-- No sort:
SELECT * FROM (<user_sql>) _q
LIMIT <page_size> OFFSET <page * page_size>
```

Sortable columns are those in the query result — not the original DataFrame
schema. If the user rewrites the query (e.g., a GROUP BY), result columns
update and the sort state resets.

### 4.3 Pagination

Fixed page size: **100 rows**. Two queries run concurrently on each state change:

```sql
-- Data query
SELECT * FROM (<user_sql>) _q [ORDER BY ...] LIMIT 100 OFFSET <page * 100>

-- Count query
SELECT COUNT(*) FROM (<user_sql>) _q
```

Page controls: `← Prev  |  Page N of M  |  Next →`. Disabled at boundaries.

### 4.4 Execution Triggers

| Trigger | Executes | Side effects |
|---|---|---|
| Submit button click | Immediately | Reset page=0, reset sort |
| Enter key in SQL box | Immediately | Reset page=0, reset sort |
| Reset button click | Immediately | Restore SQL to `FROM t_{cellId}_{recordIndex}`, clear sort, reset page=0 |
| Column header click | Immediately | Reset page=0 |
| Prev / Next click | Immediately | — |

SQL box edits do **not** trigger execution. The table continues showing the
last submitted query's results while the box contains unsubmitted changes.
The Submit button gains a visual indicator (bold border) when the box content
differs from the last executed SQL.

Sort and page changes always use the last *submitted* SQL, not any pending
edits in the box.

On each execution: run data query and count query concurrently via
`Promise.all`. On error: display message below query box; retain previous rows.

---

## 5. Svelte Components

### 5.1 `DataTable.svelte`

Owns the DuckDB setup for this record instance. Registers the Parquet buffer,
creates a uniquely named view, then hands the connection and view name to
`DataTableView`.

```svelte
<script>
  import { onDestroy } from 'svelte';
  import { getDb }     from '$lib/duckdb.js';
  import DataTableView from './DataTableView.svelte';

  export let payload;       // { data: string, total_rows: number }
  export let cellId;        // number — cell's positional serial index
  export let recordIndex;   // number — record's position within cell.records

  const viewName = `t_${cellId}_${recordIndex}`;
  const bufName  = `_nb_${viewName}.parquet`;

  let conn;

  const ready = getDb().then(async db => {
      const buf = Uint8Array.from(atob(payload.data), c => c.charCodeAt(0));
      await db.registerFileBuffer(bufName, buf);
      conn = await db.connect();
      await conn.query(`CREATE OR REPLACE VIEW "${viewName}" AS FROM '${bufName}'`);
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
```

### 5.2 `DataTableView.svelte`

All interactive state lives here. Receives `conn`, `viewName`, and `totalRows`.

**State:**

```javascript
const defaultSql = `FROM ${viewName}`;
let sql          = defaultSql;  // contents of the text box
let submittedSql = defaultSql;  // last executed SQL; used by sort and page changes
let dirty        = false;       // sql !== submittedSql
let sortCol     = null;
let sortDir     = 'ASC';        // 'ASC' | 'DESC'
let page        = 0;

let rows       = [];
let columns    = [];     // [{ name: string, numeric: boolean }] from Arrow schema
let count      = 0;
let queryError = null;
let loading    = false;
```

**Execution:**

`submit()` sets `submittedSql = sql`, resets sort and page, then calls
`execute()`. `reset()` sets both `sql` and `submittedSql` back to `defaultSql`,
clears sort, resets page, then calls `execute()`. Sort and page changes call
`execute()` directly using `submittedSql` (not `sql`).

`dirty` is `sql !== submittedSql`. The Submit button renders with a bold border
when `dirty` is true.

**Template structure:**

```
[query input box — full width, monospace]  [Submit*]  [Reset]
  (* bold border when dirty)
[error line — shown when queryError is set]
[result table]
  thead: column headers with sort indicators
  tbody: data rows; nulls rendered as — (em-dash, muted)
[pagination bar: ← Prev | Page N of M | Next →]
[footer: "N total rows in table" using totalRows prop]
```

---

## 6. UI Behaviour

### 6.1 Sort Indicators

Each column header shows:

| State | Indicator |
|---|---|
| Unsorted | `↕` muted |
| ASC | `↑` active |
| DESC | `↓` active |

### 6.2 Column Alignment

Determined from the Arrow result schema, not the original Polars dtypes:

| Arrow type | Alignment |
|---|---|
| Int8 … Int64, Float32, Float64, Decimal | Right |
| All others (Utf8, Date, Timestamp, Bool, …) | Left |

### 6.3 Null Rendering

Null values: `—` (U+2014, em-dash) in muted colour. Distinguishable from the
literal strings `"null"` or `"None"`.

### 6.4 Submit and Reset Buttons

Both buttons sit inline to the right of the query box.

Submit label: `Run` (or `Run ●` when dirty — implementation choice). Bold
border when `dirty` is true. Disabled while a query is in-flight.

Reset label: `Reset`. Always enabled. Restores `sql` to `FROM {viewName}`,
clears sort, resets page, and executes immediately. This returns the table to
exactly the data received in the `DisplayRecord`.

### 6.5 Loading State

While a query is in-flight, the table body reduces to `opacity: 0.4`. No
spinner, no layout shift — consistent with the scroll stability goal in main
spec §4.4.

### 6.6 Query Errors

DuckDB error messages are displayed verbatim below the query box (monospace,
error colour). Previous rows remain visible. Error clears on the next successful
execution.

---

## 7. Project Structure Additions

```
nb/
  framework.py       ← add: Table dataclass, _serialize_table(), display() dispatch

nb-ui/src/
  lib/
    duckdb.js        ← new: DuckDB-WASM singleton (§2.2)
    stream.js        ← modify: add getDb() pre-warm call (§2.3)
  components/
    DataTable.svelte      ← new: buffer registration, {#await} wrapper (§5.1)
    DataTableView.svelte  ← new: query state, table render (§5.2)
    Cell.svelte           ← modify: dispatch on record.type === 'table'
```

`Cell.svelte` dispatch addition. `recordIndex` is the record's position in
the cell's `records` array, available from the `{#each}` loop index:

```svelte
{#each cell.records as record, i}
  {#if record.type === 'table'}
    <DataTable
      payload={record.payload}
      cellId={cell.id}
      recordIndex={i}
    />
  {/if}
{/each}
```

---

## 8. Future: Truncation

`Table` gains `max_rows`:

```python
@dataclass
class Table:
    df: pl.DataFrame
    max_rows: int = 10_000
```

`_serialize_table` serializes only `df.head(max_rows)`. The payload gains
`shown_rows` alongside `total_rows`. The UI footer becomes:

```
Showing 10,000 of 500,000 rows — filter in notebook for full data.
```

Active only when `shown_rows < total_rows`. No other changes to the query
model or components.
