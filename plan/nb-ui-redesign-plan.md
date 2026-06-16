# nb UI — Design Revision Plan

This document describes precise, targeted changes to the `nb-ui/` Svelte frontend.
Make only the changes listed here. Do not refactor unrelated code.

---

## Context

The cell chrome (borders, headers, status indicators) currently draws more visual
attention than the cell content. The goal is to reverse that: make the chrome
recede so data and output dominate.

File targets:
- `nb-ui/src/App.svelte` — topbar, notebook header docstring
- `nb-ui/src/components/Cell.svelte` — cell chrome, header, stats, status indicator

If CSS is currently in a shared file (e.g. `app.css` or a `<style>` block in
`App.svelte`), keep it there. All changes below are in terms of effect, not which
file to put them in.

---

## Design Tokens

Replace the existing values for the following wherever they appear. These are the
ground truth for the new design.

```
--nb-border:        #C4C0B4   (all cell borders)
--nb-header-bg:     #E4E0D6   (cell header background)
--nb-cell-bg:       #EAE7DE   (cell body background)
--nb-label-color:   #2C2820   (cell label text)
--nb-stats-color:   #A09C92   (profiling stat text)
--nb-running-color: #8C6A10   (amber — used ONLY for running state)
```

---

## Change 1 — Cell border: shadow → flat border

**Remove** any `box-shadow` on `.cell` or equivalent cell wrapper.

**Replace with:**
```css
.cell {
  border: 1px solid var(--nb-border);   /* was box-shadow */
  border-radius: 4px;                   /* was ~12px */
}
```

No drop shadow of any kind. No `filter: drop-shadow`. No `box-shadow`.

---

## Change 2 — Cell header: remove decorative bullet

The cell header currently renders a bullet dot (•) or a filled circle element
before the cell label for all cells regardless of state.

**Remove** that element entirely.

The header should contain only:
1. The cell label text (left-aligned)
2. The profiling stats (right-aligned, see Change 4)

No bullet, no dot, no icon, no decorative mark in the idle/done/error states.

---

## Change 3 — Cell label: color → neutral dark

**Before:** cell label text is amber / golden (something like `#A06B10` or a CSS
variable pointing to an accent color).

**After:**
```css
.cell-label {
  color: #2C2820;      /* near-black, warm */
  font-weight: 500;
  font-size: 12px;
}
```

The amber color must now appear **exclusively** as part of the running state
indicator (Change 5). It must not appear in any idle, done, or error state.

---

## Change 4 — Profiling stats: hidden when sub-millisecond

**Current behavior:** profiling stats (`Xms wall · Xms cpu`) are always shown in
the cell header once available.

**New behavior:** conditionally render the stats block. Hide it entirely when both
values round to zero — i.e. when neither has accumulated a full millisecond.

Svelte condition:
```svelte
{#if cell.profiling && (cell.profiling.wall_ms >= 1 || cell.profiling.cpu_ms >= 1)}
  <div class="cell-stats">
    <span>{cell.profiling.wall_ms}ms wall</span>
    <span>{cell.profiling.cpu_ms}ms cpu</span>
  </div>
{/if}
```

When hidden, the cell header should still render correctly with the label text
left-aligned and nothing on the right.

Stats styling when shown:
```css
.cell-stats {
  margin-left: auto;
  font-size: 10px;
  color: #A09C92;
  font-family: monospace;
  display: flex;
  gap: 10px;
}
```

Remove any clock/cpu icon glyphs from the stats if they exist — plain text only.

---

## Change 5 — Running state indicator

When `cell.status === 'running'`, apply two visual changes and only these two.
No changes for any other status.

**5a. Left border accent:**
```css
/* Apply when cell.status === 'running' */
.cell.running {
  border-left: 2px solid #8C6A10;
  /* The 2px left border replaces the 1px from Change 1 on that side only */
}
```

In Svelte: `<div class="cell" class:running={cell.status === 'running'}>`.

**5b. Pulsing dot in header:**
Render a small dot at the left of the cell header, only when running:
```svelte
{#if cell.status === 'running'}
  <div class="run-dot" aria-hidden="true"></div>
{/if}
```

```css
.run-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #8C6A10;
  margin-right: 7px;
  flex-shrink: 0;
  animation: nb-pulse 1.2s ease-in-out infinite;
}

@keyframes nb-pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}
```

This is the only place amber appears in the UI. It signals "actively executing"
and disappears when the cell transitions to `done` or `error`.

---

## Change 6 — Cell header background

```css
.cell-header {
  background: #E4E0D6;
  border-bottom: 1px solid #C4C0B4;
  padding: 7px 14px;
  display: flex;
  align-items: center;
}
```

**Exception:** for cells that produce no output (empty `cell.records` and
status is `done`), suppress `border-bottom` on the header so the header
is the entire cell with no bottom seam showing. Apply:
```css
.cell-header.no-output {
  border-bottom: none;
}
```

Condition in Svelte:
```svelte
<div
  class="cell-header"
  class:no-output={cell.records.length === 0 && cell.status === 'done'}
>
```

---

## Change 7 — "Connected to daemon" badge

**Current:** rendered as a pill/badge with a border, border-radius, and padding —
visually prominent.

**New:** plain inline text with a status dot. No border, no background, no pill shape.

```svelte
<div class="conn-status">
  <div class="conn-dot"></div>
  connected to daemon
</div>
```

```css
.conn-status {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #6A8A6A;         /* muted green for connected */
  margin-left: auto;
}

.conn-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #5A9A5A;
}
```

For a disconnected state (if one exists), change `conn-dot` background to `#C05040`
and text to a corresponding muted red.

---

## Change 8 — Cell body background

```css
.cell-body {
  background: #EAE7DE;
  padding: 16px 20px;
}
```

Ensure no inner shadow or inset effect.

---

## Non-changes (do not touch)

- The warm cream page background (`#F0EDE4` or equivalent) — keep as-is.
- The topbar layout and file path display — keep as-is, just apply Change 7 to
  the connection badge.
- The `NotebookHeader` docstring component — keep layout and padding as-is.
- The `DataTable` Svelte component — no changes to its internal table styling.
- The Altair / Plotly embed containers — no changes.
- The SQL input box and Run/Reset buttons inside `DataTable` — no changes.
- All SSE event handling and store logic — no changes.
- `vite.config.js`, `pyproject.toml`, and all backend files — no changes.

---

## Verification checklist

After applying changes, confirm:

- [ ] No `box-shadow` anywhere on cell wrappers
- [ ] Border radius on cells is `4px`
- [ ] Amber (`#8C6A10`) appears only in `.run-dot` and `.cell.running` left border
- [ ] Cell label text is dark (`#2C2820`), not amber, in all non-running states
- [ ] Profiling stats are absent for cells where both values are `< 1`
- [ ] Cells with empty output have no bottom border on their header
- [ ] Connection badge has no pill/border shape
- [ ] No bullet dot in cell header for idle/done/error cells
