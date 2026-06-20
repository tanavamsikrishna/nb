<!--
  DataTableView.svelte — Interactive table with SQL query.

  Receives a DuckDB connection and view name, manages all interactive state:
  SQL editing, display limited to first 25 rows.

  Props:
    conn       AsyncDuckDB.Connection  — active DuckDB connection
    viewName   string  — name of the registered view (e.g. "t_2_0")
    totalRows  number  — total rows in the original DataFrame
    reload     number  — bumped by the parent when the view's buffer is swapped
                         (re-run); re-executes the current query in place

  Dependencies: None (receives conn from parent)
  Exports: None (render-only component)
  Side-effects: Executes SQL queries against DuckDB on user interaction.
  Constraints: conn must be an active AsyncDuckDB connection.
-->
<script lang="ts">
  import type { AsyncDuckDBConnection } from "@duckdb/duckdb-wasm";
  import { tooltip } from "../lib/tooltip";

  // Classification of a temporal column, derived from the Arrow type (see
  // temporalInfo). `null` for non-temporal columns.
  type TemporalInfo =
    | { kind: "timestamp"; local: boolean }
    | { kind: "date" }
    | { kind: "time"; unit: number }
    | null;

  interface Column {
    name: string;
    numeric: boolean;
    temporal: TemporalInfo;
    zoneLabel: string;
  }

  // The slice of an Arrow `DataType` the formatters actually read. Structural
  // so we don't pull in apache-arrow's generic types just to annotate.
  type ArrowType = { typeId?: number; timezone?: string | null; unit?: number };

  type Row = Record<string, any>;

  const MAX_DISPLAY_ROWS = 25;

  const {
    conn,
    viewName,
    totalRows,
    reload,
  }: {
    conn: AsyncDuckDBConnection;
    viewName: string;
    totalRows: number;
    reload: number;
  } = $props();

  const defaultSql = `SELECT * FROM ${viewName} `;
  let sql = $state(defaultSql);
  let submittedSql = $state(defaultSql);
  let dirty = $derived(sql !== submittedSql);

  let rows = $state<Row[]>([]);
  let columns = $state<Column[]>([]);
  let totalResultRows = $state(0);
  let queryError = $state<string | null>(null);
  let loading = $state(false);

  async function execute() {
    loading = true;
    queryError = null;
    try {
      const dataResult = await conn.query(submittedSql);
      totalResultRows = dataResult.numRows;

      // Extract columns from Arrow schema
      columns = dataResult.schema.fields.map((f) => {
        const temporal = temporalInfo(f.type);
        return {
          name: f.name,
          numeric: isNumericType(f.type),
          temporal,
          // tz-aware timestamps are converted to the browser's local zone, so
          // label the column once with that zone (rather than per cell).
          zoneLabel:
            temporal?.kind === "timestamp" && temporal.local ? LOCAL_TZ : "",
        };
      });

      // Convert Arrow table to array of row objects (first 25 only)
      const displayRows = Math.min(dataResult.numRows, MAX_DISPLAY_ROWS);
      rows = [];
      for (let i = 0; i < displayRows; i++) {
        const row: Row = {};
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

  function isNumericType(type: ArrowType): boolean {
    const typeId = type?.typeId;
    // Arrow type IDs: Int = 2, Float = 3, Decimal = 7
    return typeId === 2 || typeId === 3 || typeId === 7;
  }

  // Classify temporal columns from the Arrow schema. Returns null for
  // non-temporal types. Arrow type IDs: Date = 8, Time = 9, Timestamp = 10.
  // For timestamps, `local` distinguishes tz-aware (a true instant → convert to
  // the browser zone) from naive (a bare wall-clock → render verbatim, no zone).
  function temporalInfo(type: ArrowType): TemporalInfo {
    const id = type?.typeId;
    if (id === 10) return { kind: "timestamp", local: type.timezone != null };
    if (id === 8) return { kind: "date" };
    if (id === 9) return { kind: "time", unit: type.unit };
    return null;
  }

  // The browser's IANA zone (e.g. "America/Los_Angeles"), shown next to
  // tz-aware timestamp columns so the displayed local times are unambiguous.
  const LOCAL_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const num = (v: number | bigint): number =>
    typeof v === "bigint" ? Number(v) : v;
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");

  // apache-arrow returns timestamps as ms-since-epoch. For tz-aware columns the
  // ms is a real instant → use local getters. For naive columns the ms encodes
  // the wall clock as if UTC → use UTC getters so we don't shift it by the
  // local offset. Sub-second detail is omitted unless `withFrac` (cells stay to
  // second resolution; the tooltip shows the full value).
  function fmtTimestamp(ms: number | bigint, local: boolean, withFrac = false) {
    const d = new Date(num(ms));
    const [Y, Mo, D, h, m, s, frac] = local
      ? [
          d.getFullYear(),
          d.getMonth() + 1,
          d.getDate(),
          d.getHours(),
          d.getMinutes(),
          d.getSeconds(),
          d.getMilliseconds(),
        ]
      : [
          d.getUTCFullYear(),
          d.getUTCMonth() + 1,
          d.getUTCDate(),
          d.getUTCHours(),
          d.getUTCMinutes(),
          d.getUTCSeconds(),
          d.getUTCMilliseconds(),
        ];
    let out = `${Y}-${pad(Mo)}-${pad(D)} ${pad(h)}:${pad(m)}:${pad(s)}`;
    if (withFrac && frac) out += `.${pad(frac, 3)}`;
    return out;
  }

  // Date is a calendar date (ms at UTC midnight) — format date-only via UTC.
  function fmtDate(ms: number | bigint) {
    const d = new Date(num(ms));
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  }

  // Time is a count since midnight in the column's unit (0=s,1=ms,2=us,3=ns).
  // Sub-second detail is omitted unless `withFrac` (tooltip only).
  function fmtTime(value: number | bigint, unit: number, withFrac = false) {
    const div = [1, 1e3, 1e6, 1e9][unit] ?? 1;
    const totalSec = num(value) / div;
    const sInt = Math.floor(totalSec % 60);
    const frac = totalSec % 1;
    let out = `${pad(Math.floor(totalSec / 3600))}:${pad(Math.floor((totalSec % 3600) / 60))}:${pad(sInt)}`;
    if (withFrac && frac > 1e-9) out += `.${pad(Math.round(frac * 1000), 3)}`;
    return out;
  }

  const SIG_FIGS = 5;

  // Round a number (or Int64 BigInt) to SIG_FIGS significant digits for display.
  // Trailing zeros from the rounding are dropped (via Number()), so e.g.
  // 123456 -> "123460", 0.123456 -> "0.12346", 1.5 -> "1.5".
  function toSigFigs(value: number | bigint) {
    const num = typeof value === "bigint" ? Number(value) : value;
    if (!Number.isFinite(num)) return String(value);
    if (num === 0) return "0";
    return String(Number(num.toPrecision(SIG_FIGS)));
  }

  // Value shown in the cell: temporal columns are formatted as date/time
  // strings; numeric columns are rounded to SIG_FIGS. The full / unambiguous
  // value is preserved in the hover tooltip (see tooltipValue + template).
  function displayValue(value: any, col: Column) {
    const t = col.temporal;
    if (t) {
      if (t.kind === "timestamp") return fmtTimestamp(value, t.local);
      if (t.kind === "date") return fmtDate(value);
      if (t.kind === "time") return fmtTime(value, t.unit);
    }
    if (
      col.numeric &&
      (typeof value === "number" || typeof value === "bigint")
    ) {
      return toSigFigs(value);
    }
    return value;
  }

  // Hover tooltip value. Cells are shown to second resolution; the tooltip
  // carries the full sub-second detail (and, for tz-aware timestamps, the
  // unambiguous UTC instant). Naive timestamps and times only get a tooltip
  // when they actually have sub-second detail to reveal; dates never do.
  // Non-temporal columns fall back to the full untruncated/unrounded value.
  function tooltipValue(value: any, col: Column) {
    if (value === null || value === undefined) return null;
    const t = col.temporal;
    if (t?.kind === "timestamp") {
      if (t.local) return `${new Date(num(value)).toISOString()} (UTC)`;
      const full = fmtTimestamp(value, false, true);
      return full !== fmtTimestamp(value, false) ? full : null;
    }
    if (t?.kind === "time") {
      const full = fmtTime(value, t.unit, true);
      return full !== fmtTime(value, t.unit) ? full : null;
    }
    if (t) return null; // date: no sub-second detail
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

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  // Initial execution
  execute();

  // Re-execute the current query when the parent swaps the view's buffer on a
  // re-run. The view name is stable, so `submittedSql` stays valid; this just
  // re-runs it against the new data in place (no remount). Skip the effect's
  // first invocation — the initial run is handled by execute() above.
  let primed = false;
  $effect(() => {
    reload; // track
    if (!primed) {
      primed = true;
      return;
    }
    execute();
  });
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
              {#if col.zoneLabel}<span class="col-zone">({col.zoneLabel})</span
                >{/if}
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
                use:tooltip={tooltipValue(row[col.name], col)}
              >
                {#if row[col.name] === null}
                  <span class="null-val">—</span>
                {:else}
                  {displayValue(row[col.name], col)}
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
    font-size: 0.81rem;
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

  .col-zone {
    margin-left: 4px;
    font-weight: 400;
    color: var(--fg-secondary);
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
    text-align: left;
    /* Hug the table's width so the status reads directly under the table's
       left edge rather than drifting to the far right of the full-width
       wrapper. */
    width: fit-content;
    max-width: 100%;
  }
</style>
