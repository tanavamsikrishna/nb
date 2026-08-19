<!--
  DataTableView.svelte — Interactive table with a caption-as-editor SQL query.

  Receives a DuckDB connection and view name. SQL lives in a muted caption
  above the grid: click (or Enter/Space) to edit, Enter to run, Escape to
  cancel. Display is limited to the first MAX_DISPLAY_ROWS rows.

  Props:
    conn       AsyncDuckDB.Connection  — active DuckDB connection
    viewName   string  — name of the registered view (e.g. "t_2_0")
    totalRows  number  — total rows in the original DataFrame
    label      string | null  — optional title from display(..., label=...)
    reload     number  — bumped by the parent when the view's buffer is swapped
                         (re-run); re-executes the current query in place

  Dependencies: None (receives conn from parent)
  Exports: None (render-only component)
  Side-effects: Executes SQL queries against DuckDB on user interaction.
  Constraints: conn must be an active AsyncDuckDB connection. Resting and
    editing caption states share one row height so toggling does not shift
    the table.
-->
<script lang="ts">
  import { tick } from "svelte";
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

  const MAX_DISPLAY_ROWS = 10;

  const {
    conn,
    viewName,
    totalRows,
    label,
    reload,
  }: {
    conn: AsyncDuckDBConnection;
    viewName: string;
    totalRows: number;
    label?: string | null;
    reload: number;
  } = $props();

  const defaultSql = `SELECT * FROM ${viewName} `;
  let sql = $state(defaultSql);
  let submittedSql = $state(defaultSql);
  let editing = $state(false);
  let dirty = $derived(sql !== submittedSql);
  let customized = $derived(submittedSql !== defaultSql);
  let showReset = $derived(sql !== defaultSql);

  let rows = $state<Row[]>([]);
  let columns = $state<Column[]>([]);
  let totalResultRows = $state(0);
  let queryError = $state<string | null>(null);
  let loading = $state(false);

  const defaultCount = $derived(
    `${rows.length} of ${totalResultRows.toLocaleString()} rows shown (${totalRows.toLocaleString()} total in table)`,
  );
  const shortCount = $derived(
    `${rows.length} of ${totalResultRows.toLocaleString()}`,
  );

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

      // Convert Arrow table to array of row objects (first MAX_DISPLAY_ROWS only)
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
  // strings; numeric columns are rounded to SIG_FIGS. When the display hides
  // information, cellTooltip supplies a hover value (see below).
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

  // Hover tooltip: type rules when the cell text compresses the value, else
  // CSS overflow detection for strings (and anything else that only needs a
  // tooltip when the ellipsis is real).
  //
  // Type rules:
  //   - tz-aware timestamp → always UTC ISO (unambiguous instant)
  //   - naive timestamp / time → only when sub-second detail exists
  //   - date → no type compression (overflow-only if somehow clipped)
  //   - numeric → full value when 5-sig-fig display differs; else overflow-only
  // Strings / other: full text only when the <td> is visually clipped.
  function cellTooltip(
    value: any,
    col: Column,
  ): { value: unknown; onlyIfOverflow?: boolean } | null {
    if (value === null || value === undefined) return null;
    const t = col.temporal;
    if (t?.kind === "timestamp") {
      if (t.local) {
        return { value: `${new Date(num(value)).toISOString()} (UTC)` };
      }
      const full = fmtTimestamp(value, false, true);
      return full !== fmtTimestamp(value, false) ? { value: full } : null;
    }
    if (t?.kind === "time") {
      const full = fmtTime(value, t.unit, true);
      return full !== fmtTime(value, t.unit) ? { value: full } : null;
    }
    if (t?.kind === "date") {
      return { value: fmtDate(value), onlyIfOverflow: true };
    }
    if (
      col.numeric &&
      (typeof value === "number" || typeof value === "bigint")
    ) {
      const display = toSigFigs(value);
      const full = String(value);
      if (display !== full) return { value: full };
      return { value: full, onlyIfOverflow: true };
    }
    return { value, onlyIfOverflow: true };
  }

  function submit() {
    submittedSql = sql;
    editing = false;
    execute();
  }

  function reset() {
    sql = defaultSql;
    submittedSql = defaultSql;
    editing = false;
    execute();
  }

  async function startEdit() {
    editing = true;
    await tick();
    captionEl?.querySelector("input")?.focus();
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      sql = submittedSql;
      editing = false;
    }
  }

  let captionEl: HTMLDivElement | undefined;

  // Exit edit on click-outside. Deferred so unmounting the caption button
  // (relatedTarget is null) doesn't cancel the edit before the input focuses.
  // Run/Reset also mousedown-preventDefault so they don't steal focus.
  function handleCaptionFocusOut() {
    requestAnimationFrame(() => {
      if (!captionEl) return;
      const active = document.activeElement;
      if (active && captionEl.contains(active)) return;
      editing = false;
    });
  }

  function keepFocus(e: MouseEvent) {
    e.preventDefault();
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
  {#if label}
    <div class="table-label">{label}</div>
  {/if}

  <div class="table-block">
    <!-- Caption: row counts at rest; same-height SQL editor when open. -->
    <div
      class="table-caption"
      bind:this={captionEl}
      onfocusout={handleCaptionFocusOut}
    >
      {#if editing}
        <input
          type="text"
          class="query-input"
          bind:value={sql}
          onkeydown={handleKeydown}
          spellcheck="false"
          placeholder="SELECT …"
          aria-label="SQL query"
        />
        {#if dirty}
          <button
            type="button"
            class="btn btn-run dirty"
            onclick={submit}
            onmousedown={keepFocus}
            disabled={loading}
          >
            Run ●
          </button>
        {/if}
        {#if showReset}
          <button
            type="button"
            class="btn btn-reset"
            onclick={reset}
            onmousedown={keepFocus}
          >
            Reset
          </button>
        {/if}
      {:else}
        <button
          type="button"
          class="caption-toggle"
          onclick={startEdit}
          title="Query this table"
        >
          {#if customized}
            <!-- prettier-ignore -->
            <span
              class="caption-sql"
              use:tooltip={{ value: submittedSql, onlyIfOverflow: true }}
            >{submittedSql}</span><span class="caption-meta">
              · {shortCount}</span
            >
          {:else}
            <span class="caption-meta">{defaultCount}</span>
          {/if}
          {#if dirty}
            <span class="dirty-dot" aria-hidden="true">●</span>
          {/if}
        </button>
      {/if}
    </div>

    {#if queryError}
      <div class="query-error">{queryError}</div>
    {/if}

    <div class="table-scroll" class:dimmed={loading}>
      <table>
        <thead>
          <tr>
            {#each columns as col}
              <th class:numeric={col.numeric} title={col.name}>
                <span class="col-name">{col.name}</span>
                {#if col.zoneLabel}<span class="col-zone"
                    >({col.zoneLabel})</span
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
                  use:tooltip={cellTooltip(row[col.name], col)}
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
  </div>
</div>

<style>
  .table-wrapper {
    font-family: var(--font-mono);
    font-size: 0.85rem;
    margin-top: 8px;
  }

  .table-label {
    font-weight: 600;
    font-size: 0.85rem;
    color: var(--fg-primary);
    margin-bottom: 6px;
  }

  /* Caption + table share one column sized by the grid. */
  .table-block {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    width: max-content;
    max-width: 100%;
  }

  /*
    Resting and editing share this height so toggling (and Run/Reset
    appearing) cannot shift the table. Input/buttons use a transparent 1px
    border so focus never adds pixels.
  */
  .table-caption {
    display: flex;
    align-items: center;
    gap: 6px;
    box-sizing: border-box;
    height: 22px;
    margin-bottom: 6px;
    /* Don't contribute intrinsic width — the table sizes the block; the
       caption stretches to that width and ellipsizes. */
    width: 0;
    min-width: 100%;
    max-width: 100%;
    font-size: 0.75rem;
    line-height: 1.25;
    color: var(--fg-secondary);
    flex-wrap: nowrap;
  }

  .caption-toggle {
    display: flex;
    align-items: center;
    min-width: 0;
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0 1px;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    background: none;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: text;
    overflow: hidden;
  }

  .caption-toggle:hover,
  .caption-toggle:focus-visible {
    color: var(--fg-primary);
    outline: none;
  }

  .caption-sql {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--fg-secondary);
  }

  .caption-meta {
    flex-shrink: 0;
    white-space: nowrap;
  }

  .dirty-dot {
    flex-shrink: 0;
    margin-left: 6px;
    color: var(--color-primary);
    font-size: 0.65rem;
  }

  .query-input {
    flex: 1;
    min-width: 0;
    height: 100%;
    box-sizing: border-box;
    margin: 0;
    padding: 0 1px;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    background: transparent;
    font: inherit;
    font-family: var(--font-mono);
    color: var(--fg-primary);
    outline: none;
  }

  .query-input:focus {
    color: var(--fg-primary);
  }

  .btn {
    box-sizing: border-box;
    height: 100%;
    flex-shrink: 0;
    font: inherit;
    font-size: 0.75rem;
    font-weight: 500;
    padding: 0 8px;
    border-radius: var(--radius-sm);
    border: 1px solid transparent;
    background: transparent;
    color: var(--fg-primary);
    cursor: pointer;
    white-space: nowrap;
  }

  .btn:hover:not(:disabled) {
    color: var(--fg-primary);
    background: var(--bg-sunken);
  }

  .btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .btn-run.dirty {
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
       container — at which point overflow-x scrolls. The caption above
       stretches to this same column width. */
    width: max-content;
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
       header. Clipped text is revealed via use:tooltip (type rules or
       onlyIfOverflow when the ellipsis is real). */
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
</style>
