# `nb` Theme — Design Fix Plan

Covers `theme.css` and `app.css`. Six issues, ordered by severity.

---

## 1. Fix Green-Cast Backgrounds (palette coherence)

`--bg-sunken` and `--bg-header` have a green tint that breaks from the warm amber family.

```css
/* Current — green tint */
--bg-sunken: #ebf0e0;
--bg-header: #e6ebd8;

/* Fix — stay in warm amber family */
--bg-sunken: #e8e2cc;
--bg-header: #e2dcc8;
```

---

## 2. Separate Warning from Secondary (semantic conflict)

`--color-warning` and `--color-secondary` are currently identical (`#c49a3c`).
A component styled with `--color-secondary` will visually read as a warning.

```css
/* Current */
--color-warning: #c49a3c;   /* same as --color-secondary */

/* Fix — shift warning to a more saturated amber-orange */
--color-warning: #c47a20;
```

---

## 3. Fix `fg-on-accent` Contrast (accessibility failure)

`#faf6e7` on `#a0845c` = ~3.2:1. Fails WCAG AA (4.5:1 required for normal text).

Two options — pick one:

```css
/* Option A: darken the accent color */
--color-accent: #7a6040;    /* contrast with #faf6e7 → ~5.8:1 */

/* Option B: use near-black text on accent instead */
--fg-on-accent: #1a1a1a;   /* contrast with #a0845c → ~6.5:1 */
```

---

## 4. Clarify Accent vs Secondary Roles (naming/hierarchy)

`--color-accent` (#a0845c) is more muted than `--color-secondary` (#c49a3c).
This is inverted — accent is conventionally the most vivid interactive color.

Either swap the names, or establish explicit roles:

```css
/* Proposed: rename to reflect actual usage */
--color-brand:       #c49a3c;   /* brand expression (badges, headings) */
--color-interactive: #8b6914;   /* buttons, links, focus rings */
--color-surface-tint: #a0845c;  /* tinted surfaces, scrollbar, dividers */
```

---

## 5. Add Interactive State Tokens (missing)

No hover/active/focus tokens exist. These will be needed for SQL input boxes,
pagination controls, and submit buttons.

```css
--color-interactive:        #8b6914;
--color-interactive-hover:  #6e530f;
--color-interactive-active: #52400b;
--color-focus-ring:         #8b6914;
--color-focus-ring-offset:  #f5f5dc;
```

---

## 6. Add Missing Tokens for Code and Spacing (gap)

The UI renders Markdown with inline code and code blocks — no token exists for these.
No spacing scale exists; component CSS will drift toward magic numbers.

```css
/* Code surface */
--fg-code:        #5a3e1b;
--bg-code-inline: #ede7cf;
--bg-code-block:  #e8e2cc;

/* Spacing scale */
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-6: 24px;
--space-8: 32px;
--space-12: 48px;
```

---

## Minor / Optional

- **Selection color:** `--color-selection-bg: #a8d0e6` is a cool blue; consider
  `#e6c97a` (warm amber tint) to stay cohesive with the palette.
- **Google Fonts import:** currently in `app.css` but fonts are declared in
  `theme.css` (loaded first). Move the `@import` to `theme.css` to co-locate
  font loading with font token declarations.
- **`fg-primary` color:** current `#1a1a1a` (neutral near-black) is safe. A warm
  dark like `#2a1f0e` would be more harmonious with the palette if you want to
  lean into the parchment feel. Avoid `#42535a` (teal-grey) — readable at 7.25:1
  contrast but introduces a cool hue that conflicts with the warm token set.
