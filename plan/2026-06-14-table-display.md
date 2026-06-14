# Table Display Implementation Plan

> **For agentic workers:** Use the executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add interactive table display with DuckDB-WASM-powered SQL querying, sorting, and pagination for Polars DataFrames.

**Architecture:** Python serializes DataFrames as Parquet (base64) via a `Table` wrapper. Frontend loads DuckDB-WASM once as a singleton, registers each table's buffer, creates a named view, and provides an interactive SQL query interface with sorting and pagination.

**Tech Stack:** Python (Polars, Parquet), Svelte 5, DuckDB-WASM, Vite

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `nb/framework.py` | Modify | Add `Table` dataclass and `_serialize_table()` function |
| `nb/tests/test_framework.py` | Create | Unit tests for `Table` serialization |
| `nb-ui/vite.config.js` | Modify | Exclude DuckDB-WASM from Vite's pre-bundler |
| `nb-ui/package.json` | Modify | Add `@duckdb/duckdb-wasm` dependency |
| `nb-ui/src/lib/duckdb.js` | Create | DuckDB-WASM initialization singleton |
| `nb-ui/src/lib/stream.js` | Modify | Pre-warm DuckDB at startup |
| `nb-ui/src/components/DataTable.svelte` | Create | Buffer registration, view creation, destroy cleanup |
| `nb-ui/src/components/DataTableView.svelte` | Create | Query box, sorting, pagination, table rendering |
| `nb-ui/src/components/Cell.svelte` | Modify | Dispatch on `record.type === 'table'` |

---

### Task 1: Add `Table` Wrapper to Python Framework

**Files:**
- Modify: `nb/framework.py:1-20` (imports and dataclasses)
- Test: `nb/tests/test_framework.py`

- [ ] **Step 1: Write failing test for `Table` serialization**

Create `nb/tests/test_framework.py`:

```python
import base64
import io

import polars as pl
import pytest

from nb.framework import Table, DisplayRecord, _create_display_record


def test_table_dataclass():
    df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    table = Table(df)
    assert table.df is df


def test_table_serialization():
    df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    record = _create_display_record(Table(df))

    assert isinstance(record, DisplayRecord)
    assert record.type == "table"

    payload = record.payload
    assert "data" in payload
    assert "total_rows" in payload
    assert payload["total_rows"] == 3

    # Verify it's valid base64-encoded Parquet
    raw = base64.b64decode(payload["data"])
    buf = io.BytesIO(raw)
    result = pl.read_parquet(buf)
    assert result.frame_equal(df)


def test_table_auto_dispatch():
    """Table should be dispatched before plain Polars DataFrame."""
    df = pl.DataFrame({"x": [10, 20]})
    record = _create_display_record(Table(df))
    assert record.type == "table"


def test_plain_dataframe_still_html():
    """Plain Polars DataFrame (not wrapped) should still render as HTML."""
    df = pl.DataFrame({"x": [10, 20]})
    record = _create_display_record(df)
    assert record.type == "html"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/vamsi/repo/nb && python -m pytest nb/tests/test_framework.py -v`
Expected: FAIL with `ImportError: cannot import name 'Table' from 'nb.framework'`

- [ ] **Step 3: Add `Table` wrapper and serialization to `framework.py`**

Add after the `Object` class definition (around line 50):

```python
@dataclass
class Table:
    """Wrapper for Polars DataFrames to enable interactive table display."""
    df: Any  # pl.DataFrame — typed as Any to avoid hard import at module level
```

Add `_serialize_table` function after `_serialize_object`:

```python
def _serialize_table(obj: Table) -> dict:
    import io
    import base64

    buf = io.BytesIO()
    obj.df.write_parquet(buf, compression="snappy")
    return {
        "data": base64.b64encode(buf.getvalue()).decode(),
        "total_rows": len(obj.df),
    }
```

Modify `_create_display_record` to dispatch on `Table` **before** the Polars DataFrame check. Add this block as case 3 (shifting existing cases down):

```python
    # 3. Table wrapper (must come before plain Polars DataFrame)
    if isinstance(obj, Table):
        return DisplayRecord(type="table", payload=_serialize_table(obj))
```

The final dispatch order becomes: Plotly → Altair → Table → Polars DataFrame → MD → HTML → Object → text fallback.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/vamsi/repo/nb && python -m pytest nb/tests/test_framework.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add nb/framework.py nb/tests/test_framework.py
git commit -m "feat: add Table wrapper with Parquet serialization"
```

---

### Task 2: Install DuckDB-WASM and Configure Vite

**Files:**
- Modify: `nb-ui/package.json`
- Modify: `nb-ui/vite.config.js`

- [ ] **Step 1: Install DuckDB-WASM**

Run: `cd /Users/vamsi/repo/nb/nb-ui && npm install @duckdb/duckdb-wasm`

Verify `package.json` now contains `"@duckdb/duckdb-wasm"` in dependencies.

- [ ] **Step 2: Update Vite config to exclude DuckDB-WASM from pre-bundling**

Replace `nb-ui/vite.config.js` with:

```javascript
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  optimizeDeps: {
    exclude: ['@duckdb/duckdb-wasm']
  },
  server: {
    proxy: {
      '/stream': 'http://localhost:7777'
    }
  }
})
```

- [ ] **Step 3: Verify dev server starts**

Run: `cd /Users/vamsi/repo/nb/nb-ui && timeout 5 npm run dev || true`
Expected: Vite starts without DuckDB-related errors (timeout is intentional — just checking startup)

- [ ] **Step 4: Commit**

```bash
git add nb-ui/package.json nb-ui/package-lock.json nb-ui/vite.config.js
git commit -m "feat: add DuckDB-WASM dependency with Vite config"
```

---

### Task 3: Create DuckDB-WASM Singleton

**Files:**
- Create: `nb-ui/src/lib/duckdb.js`

- [ ] **Step 1: Create DuckDB singleton module**

Create `nb-ui/src/lib/duckdb.js`:

```javascript
/**
 * DuckDB-WASM initialization singleton.
 *
 * Provides a single, shared AsyncDuckDB instance for the browser session.
 * Call `getDb()` anywhere — it returns the same stable promise every time.
 *
 * Dependencies: @duckdb/duckdb-wasm
 * Exports: getDb()
 * Side-effects: Spawns a Web Worker on first call.
 * Constraints: Must be excluded from Vite pre-bundling (see vite.config.js).
 */
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

/**
 * Returns a promise that resolves to the shared AsyncDuckDB instance.
 * Safe and cheap to call multiple times.
 * @returns {Promise<duckdb.AsyncDuckDB>}
 */
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

- [ ] **Step 2: Verify module syntax**

Run: `cd /Users/vamsi/repo/nb/nb-ui && node -e "import('./src/lib/duckdb.js').then(() => console.log('OK')).catch(e => console.error(e.message))"`
Expected: May fail due to Vite-specific `?url` imports outside Vite — that's expected. The module will work correctly within the Vite dev server.

- [ ] **Step 3: Commit**

```bash
git add nb-ui/src/lib/duckdb.js
git commit -m "feat: add DuckDB-WASM singleton module"
```

---

### Task 4: Pre-warm DuckDB in Stream Module

**Files:**
- Modify: `nb-ui/src/lib/stream.js:1-10`

- [ ] **Step 1: Add pre-warm import to stream.js**

At the top of `nb-ui/src/lib/stream.js`, add the import and fire-and-forget call:

```javascript
import { getDb } from './duckdb.js';
import { cells, notebookHeader, connectionStatus } from '../stores/cells.js';

// Pre-warm DuckDB-WASM in background (~8MB lazy load, cached after first load)
getDb();
```

This replaces the existing first line (`import { cells, ... }`). The rest of the file stays unchanged.

- [ ] **Step 2: Verify no syntax errors**

Run: `cd /Users/vamsi/repo/nb/nb-ui && node -c src/lib/stream.js 2>&1 || echo "Syntax check may fail due to ES modules — expected"`
Expected: Module-level check may report import issues outside Vite, which is expected.

- [ ] **Step 3: Commit**

```bash
git add nb-ui/src/lib/stream.js
git commit -m "feat: pre-warm DuckDB-WASM at app startup"
```

---

### Task 5: Create DataTable Wrapper Component

**Files:**
- Create: `nb-ui/src/components/DataTable.svelte`

- [ ] **Step 1: Create DataTable.svelte**

Create `nb-ui/src/components/DataTable.svelte`:

```svelte
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
  import { onDestroy } from 'svelte';
  import { getDb }     from '$lib/duckdb.js';
  import DataTableView from './DataTableView.svelte';

  let { payload, cellId, recordIndex } = $props();

  const viewName = `t_${cellId}_${recordIndex}`;
  const bufName  = `_nb_${viewName}.parquet`;

  let conn = $state(null);

  const ready = getDb().then(async (db) => {
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

<style>
  .db-loading {
      font-size: 0.85rem;
      color: #64748b;
      font-style: italic;
      padding: 8px 0;
  }

  .db-error {
      font-size: 0.85rem;
      color: #f87171;
      font-weight: 500;
      padding: 8px 0;
  }
</style>
```

- [ ] **Step 2: Verify Svelte compilation**

Run: `cd /Users/vamsi/repo/nb/nb-ui && npx svelte-check --threshold error 2>&1 | head -20`
Expected: May warn about DataTableView not existing yet — that's fine, will resolve in next task.

- [ ] **Step 3: Commit**

```bash
git add nb-ui/src/components/DataTable.svelte
git commit -m "feat: add DataTable wrapper component with DuckDB registration"
```

---

### Task 6: Create DataTableView Interactive Component

**Files:**
- Create: `nb-ui/src/components/DataTableView.svelte`

- [ ] **Step 1: Create DataTableView.svelte**

Create `nb-ui/src/components/DataTableView.svelte`:

```svelte
<!--
  DataTableView.svelte — Interactive table with SQL query, sorting, pagination.

  Receives a DuckDB connection and view name, manages all interactive state:
  SQL editing, column sorting (3-state cycle), pagination (100 rows/page).

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
  const PAGE_SIZE = 100;

  let { conn, viewName, totalRows } = $props();

  const defaultSql = `FROM ${viewName}`;
  let sql          = $state(defaultSql);
  let submittedSql = $state(defaultSql);
  let dirty        = $derived(sql !== submittedSql);

  let sortCol   = $state(null);
  let sortDir   = $state('ASC');
  let page      = $state(0);

  let rows       = $state([]);
  let columns    = $state([]);
  let count      = $state(0);
  let queryError = $state(null);
  let loading    = $state(false);

  let totalPages = $derived(Math.max(1, Math.ceil(count / PAGE_SIZE)));

  function buildDataQuery(baseSql, col, dir, pg) {
      let wrapped = `SELECT * FROM (${baseSql}) _q`;
      if (col) {
          wrapped += ` ORDER BY "${col}" ${dir}`;
      }
      wrapped += ` LIMIT ${PAGE_SIZE} OFFSET ${pg * PAGE_SIZE}`;
      return wrapped;
  }

  function buildCountQuery(baseSql) {
      return `SELECT COUNT(*) AS cnt FROM (${baseSql}) _q`;
  }

  async function execute() {
      loading = true;
      queryError = null;
      try {
          const dataSql  = buildDataQuery(submittedSql, sortCol, sortDir, page);
          const countSql = buildCountQuery(submittedSql);

          const [dataResult, countResult] = await Promise.all([
              conn.query(dataSql),
              conn.query(countSql),
          ]);

          // Extract columns from Arrow schema
          columns = dataResult.schema.fields.map(f => ({
              name: f.name,
              numeric: isNumericType(f.type),
          }));

          // Convert Arrow table to array of row objects
          rows = [];
          for (let i = 0; i < dataResult.numRows; i++) {
              const row = {};
              for (const col of columns) {
                  const val = dataResult.getChild(col.name)?.get(i);
                  row[col.name] = val === null || val === undefined ? null : val;
              }
              rows.push(row);
          }

          count = Number(countResult.getChild('cnt')?.get(0) ?? 0);
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
      sortCol = null;
      sortDir = 'ASC';
      page = 0;
      execute();
  }

  function reset() {
      sql = defaultSql;
      submittedSql = defaultSql;
      sortCol = null;
      sortDir = 'ASC';
      page = 0;
      execute();
  }

  function handleKeydown(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          submit();
      }
  }

  function toggleSort(colName) {
      if (sortCol !== colName) {
          sortCol = colName;
          sortDir = 'ASC';
      } else if (sortDir === 'ASC') {
          sortDir = 'DESC';
      } else {
          sortCol = null;
          sortDir = 'ASC';
      }
      page = 0;
      execute();
  }

  function prevPage() {
      if (page > 0) {
          page--;
          execute();
      }
  }

  function nextPage() {
      if (page < totalPages - 1) {
          page++;
          execute();
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
      <button class="btn btn-run" class:dirty={dirty} onclick={submit} disabled={loading}>
          Run{dirty ? ' ●' : ''}
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
                      <th
                          class:numeric={col.numeric}
                          onclick={() => toggleSort(col.name)}
                      >
                          <span class="col-name">{col.name}</span>
                          <span class="sort-indicator">
                              {#if sortCol === col.name}
                                  {sortDir === 'ASC' ? '↑' : '↓'}
                              {:else}
                                  ↕
                              {/if}
                          </span>
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

  <!-- Pagination -->
  {#if totalPages > 1}
      <div class="pagination">
          <button class="btn btn-page" onclick={prevPage} disabled={page === 0}>
              ← Prev
          </button>
          <span class="page-info">Page {page + 1} of {totalPages}</span>
          <button class="btn btn-page" onclick={nextPage} disabled={page >= totalPages - 1}>
              Next →
          </button>
      </div>
  {/if}

  <!-- Footer -->
  <div class="footer">{totalRows.toLocaleString()} total rows in table</div>
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
      font-family: 'JetBrains Mono', ui-monospace, monospace;
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

  .btn-page {
      font-size: 0.75rem;
      padding: 6px 10px;
  }

  /* Error */
  .query-error {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
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
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
  }

  thead th:hover {
      background: rgba(30, 41, 59, 0.8);
  }

  thead th.numeric {
      text-align: right;
  }

  .col-name {
      margin-right: 4px;
  }

  .sort-indicator {
      font-size: 0.75rem;
      opacity: 0.5;
  }

  thead th:hover .sort-indicator {
      opacity: 0.8;
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

  /* Pagination */
  .pagination {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
      padding: 10px 0;
  }

  .page-info {
      font-size: 0.8rem;
      color: #94a3b8;
  }

  /* Footer */
  .footer {
      font-size: 0.75rem;
      color: #475569;
      padding-top: 6px;
      text-align: right;
  }
</style>
```

- [ ] **Step 2: Verify Svelte compilation**

Run: `cd /Users/vamsi/repo/nb/nb-ui && npx svelte-check --threshold error 2>&1 | head -20`
Expected: No errors (warnings about unused CSS are acceptable)

- [ ] **Step 3: Commit**

```bash
git add nb-ui/src/components/DataTableView.svelte
git commit -m "feat: add DataTableView with SQL query, sorting, pagination"
```

---

### Task 7: Wire Table Display into Cell.svelte

**Files:**
- Modify: `nb-ui/src/components/Cell.svelte:1-10` (imports)
- Modify: `nb-ui/src/components/Cell.svelte:~95-115` (record dispatch in template)

- [ ] **Step 1: Add DataTable import**

At the top of the `<script>` block in `Cell.svelte`, add the import after the existing imports:

```javascript
  import { marked } from 'marked';
  import JSONTree from './JSONTree.svelte';
  import DataTable from './DataTable.svelte';
  import { loadPlotly, loadVega } from '../lib/lazy_load.js';
```

- [ ] **Step 2: Add table dispatch in template**

In the `{#each cell.records as record}` block, add the table case **before** the `{:else if record.type === 'html'}` branch. The modified block becomes:

```svelte
        {#if record.type === 'md'}
          <div class="markdown-output">
            {@html marked.parse(record.payload)}
          </div>
        {:else if record.type === 'table'}
          <DataTable
            payload={record.payload}
            cellId={cell.id}
            recordIndex={records.indexOf(record)}
          />
        {:else if record.type === 'html'}
```

Wait — `records` isn't available in scope. The `{#each}` loop variable is `record`. We need the index. Let me check the existing template...

The existing template is:
```svelte
    {#each cell.records as record}
```

We need to change it to capture the index:
```svelte
    {#each cell.records as record, i}
```

Then the DataTable usage becomes:
```svelte
        {:else if record.type === 'table'}
          <DataTable
            payload={record.payload}
            cellId={cell.id}
            recordIndex={i}
          />
```

So the full modification to the `{#each}` block is:

1. Change `{#each cell.records as record}` → `{#each cell.records as record, i}`
2. Add the `table` branch before `html`:

```svelte
    {#each cell.records as record, i}
      <div class="output-item">
        {#if record.type === 'md'}
          <div class="markdown-output">
            {@html marked.parse(record.payload)}
          </div>
        {:else if record.type === 'table'}
          <DataTable
            payload={record.payload}
            cellId={cell.id}
            recordIndex={i}
          />
        {:else if record.type === 'html'}
          <div class="html-output">
            {@html record.payload}
          </div>
        {:else if record.type === 'plotly'}
```

- [ ] **Step 3: Verify build**

Run: `cd /Users/vamsi/repo/nb/nb-ui && npm run build 2>&1 | tail -10`
Expected: Build succeeds with no errors.

- [ ] **Step 4: Commit**

```bash
git add nb-ui/src/components/Cell.svelte
git commit -m "feat: wire DataTable into Cell component"
```

---

### Task 8: End-to-End Smoke Test

**Files:**
- Modify: `example.py` (temporary addition for testing)

- [ ] **Step 1: Add a Table display to the example notebook**

Add a new cell at the end of `example.py`:

```python
# %% Cell 6: Table Display
from nb import Table

big_df = pl.DataFrame({
    "id": list(range(1, 251)),
    "name": [f"Item {i}" for i in range(1, 251)],
    "value": [round(i * 1.5, 2) for i in range(1, 251)],
    "category": [["A", "B", "C"][i % 3] for i in range(250)],
})
display(Table(big_df))
```

- [ ] **Step 2: Start daemon and run notebook**

In terminal 1:
```bash
cd /Users/vamsi/repo/nb && python -m nb.daemon
```

In terminal 2:
```bash
cd /Users/vamsi/repo/nb && python -m nb.cli run example.py
```

- [ ] **Step 3: Verify in browser**

Open `http://localhost:7777` and verify:
1. Table renders with 250 rows (3 pages: 100 + 100 + 50)
2. Query box pre-filled with `FROM t_5_0`
3. Column headers show `↕` sort indicators
4. Clicking a column header sorts and shows `↑`/`↓`
5. Pagination controls work (← Prev / Next →)
6. Typing a custom query (e.g., `SELECT category, COUNT(*) as cnt FROM t_5_0 GROUP BY category`) and clicking Run shows aggregated results
7. Reset button restores original view
8. Null values display as `—`
9. Numeric columns are right-aligned

- [ ] **Step 4: Clean up example.py**

Remove the Cell 6 addition from `example.py` to keep the example clean.

- [ ] **Step 5: Commit**

```bash
git add example.py
git commit -m "chore: clean up example.py after smoke test"
```

---

### Task 9: Export `Table` from Package Init

**Files:**
- Modify: `nb/__init__.py`

- [ ] **Step 1: Add Table to package exports**

Check current `nb/__init__.py`:

```bash
cat nb/__init__.py
```

Add `Table` to the imports. The file should export: `display`, `nb_cache`, `clear_cache`, `MD`, `HTML`, `Object`, `Table`.

- [ ] **Step 2: Verify import works**

Run: `cd /Users/vamsi/repo/nb && python -c "from nb import Table; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run all Python tests**

Run: `cd /Users/vamsi/repo/nb && python -m pytest nb/tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add nb/__init__.py
git commit -m "feat: export Table from nb package"
```
