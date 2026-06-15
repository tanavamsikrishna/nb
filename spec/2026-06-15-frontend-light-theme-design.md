# Frontend Light Theme Redesign

## Overview

Restyle the nb-notebook frontend from a dark slate/indigo theme to a warm earthy light theme. Introduce a global CSS custom properties file for design tokens. Use serif, sans-serif, and monospace fonts for distinct element categories.

**Inspiration sources:**
- `/Users/vamsi/repo/scripts/marimo/styling.css` — warm earthy palette (primary source)
- `/Users/vamsi/repo/obsidian-config/snippets/obsidian.css` — beige/sage direction (secondary)

## Approach

**Single global `theme.css` + component variable migration.**

Create `src/theme.css` with all design tokens as CSS custom properties. Import it once in `main.js`. Components keep their `<style>` blocks but replace hardcoded hex/rgba values with `var(--token)` references.

## Design Tokens (`src/theme.css`)

### Typography

```css
--font-serif: "New York", Georgia, serif;       /* Headings */
--font-sans: "Outfit", -apple-system, BlinkMacSystemFont, sans-serif;  /* Body */
--font-mono: "JetBrains Mono", ui-monospace, monospace;  /* Code */
```

Font loading: Outfit and JetBrains Mono via Google Fonts (existing import in `app.css`). New York is an Apple system font — no web import needed; Georgia as cross-platform fallback.

### Backgrounds

```css
--bg-base: #f5f5dc;          /* Main background (beige) */
--bg-elevated: #faf6e7;      /* Cards, cells */
--bg-sunken: #f0ead0;        /* Code blocks, tables */
--bg-muted: #ede7cf;         /* Inputs, muted areas */
--bg-header: #ebe5c8;        /* Headers, sidebars */
```

### Foreground / Text

```css
--fg-primary: #1a1a1a;       /* Main text */
--fg-secondary: #6b5d4a;     /* Muted text */
--fg-on-accent: #faf6e7;     /* Text on primary/accent backgrounds */
```

### Borders

```css
--border-default: #c9c0a5;
--border-subtle: #d4cbb0;
```

### Primary / Accent

```css
--color-primary: #8b6914;    /* Gold */
--color-secondary: #c49a3c;  /* Amber */
--color-accent: #a0845c;     /* Brown */
```

### Semantic

```css
--color-error: #c0392b;
--color-success: #2e7d32;
--color-warning: #c49a3c;
--color-info: #4a7fb5;
--color-link: #4a7fb5;
--color-link-visited: #7a5a9e;
```

### Shadows

```css
--shadow-sm: 0 1px 2px hsla(40, 30%, 50%, 15%);
--shadow-md: 0 4px 6px -1px hsla(40, 30%, 50%, 20%);
--shadow-lg: 0 10px 15px -3px hsla(40, 30%, 50%, 25%);
```

### Spacing / Radii

```css
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-xl: 16px;
--radius-full: 9999px;
```

### Selection

```css
--color-selection-bg: #a8d0e6;
--color-selection-fg: #000000;
```

## Font Assignment

| Element | Font Variable | Example |
|---------|--------------|---------|
| Page headings (h1-h3) | `var(--font-serif)` | New York |
| Body text, labels, UI | `var(--font-sans)` | Outfit |
| Code blocks, terminal output | `var(--font-mono)` | JetBrains Mono |
| Cell names, status text | `var(--font-sans)` | Outfit |
| Logo ("nb") | `var(--font-sans)` | Outfit |

## Files to Modify

### New file

- `src/theme.css` — all design tokens listed above

### Modified files

| File | Summary of Changes |
|------|-------------------|
| `src/main.js` | Add `import './theme.css'` |
| `src/app.css` | Update body `background-color` and `color` to use `var(--bg-base)` / `var(--fg-primary)`. Update scrollbar track/thumb to light-theme colors. Keep font import. |
| `src/App.svelte` | Replace hardcoded dark colors with variables. Remove `backdrop-filter` from header; use solid `var(--bg-header)`. Update logo gradient to use gold/amber. Update status badge colors to semantic variables. Update empty state colors. |
| `src/components/Cell.svelte` | Replace all hardcoded colors (~53 values) with token references. Update cell container, header, status indicators, outputs, markdown styles, error styles. Set code output to `var(--font-mono)`. |
| `src/components/DataTableView.svelte` | Replace ~28 hardcoded color values with token references. |
| `src/components/JSONTree.svelte` | Replace ~19 hardcoded color values with token references. |
| `src/components/NotebookHeader.svelte` | Replace ~9 hardcoded color values with token references. Set heading to `var(--font-serif)`. |
| `src/components/DataTable.svelte` | Replace ~2 hardcoded color values with token references. |

## Minor Layout Tweaks

1. **Header**: Remove `backdrop-filter: blur(16px)` glass-morphism. Use solid `var(--bg-header)` background — cleaner on light theme, better performance.
2. **Border-radius**: Already consistent at 12px/8px — just swap to `var(--radius-lg)` / `var(--radius-md)` for token consistency.
3. **Status badge gradient**: Replace the indigo/purple logo gradient with a gold/amber gradient (`var(--color-primary)` → `var(--color-secondary)`).

## Color Mapping (Dark → Light)

| Dark Theme Value | Light Theme Token |
|-----------------|-------------------|
| `#0b0f19` (body bg) | `var(--bg-base)` |
| `#f1f5f9` (text) | `var(--fg-primary)` |
| `rgba(30, 41, 59, 0.4)` (cell bg) | `var(--bg-elevated)` |
| `rgba(15, 23, 42, 0.3)` (header bg) | `var(--bg-header)` |
| `rgba(255, 255, 255, 0.06)` (borders) | `var(--border-default)` |
| `#818cf8` / `#6366f1` (primary/indigo) | `var(--color-primary)` |
| `#94a3b8` (muted text) | `var(--fg-secondary)` |
| `#64748b` (secondary muted) | `var(--fg-secondary)` |
| `#10b981` (success) | `var(--color-success)` |
| `#ef4444` (error) | `var(--color-error)` |
| `#f59e0b` (warning) | `var(--color-warning)` |

## Out of Scope

- Dark mode / theme toggle (runtime switching is possible later with CSS variables, but not in this scope)
- Component structure changes
- New features or functionality
- Build tooling changes (no SCSS, no new dependencies)
