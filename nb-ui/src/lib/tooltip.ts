/*
 * tooltip.ts — `use:tooltip` Svelte action for an instant, styled hover tooltip.
 *
 * Shows the full value of an element on hover via a single shared,
 * `position: fixed` element appended to <body>. Fixed positioning (rather than
 * a per-node child) means the tooltip escapes any ancestor `overflow: hidden`
 * or scroll clipping, so it works the same inside table cells, scroll
 * containers, and plain inline text.
 *
 * Usage:  <span use:tooltip={fullValue}>{truncatedValue}</span>
 *
 * A null/undefined/empty value suppresses the tooltip. The tooltip flips above
 * the node, or shifts left, when it would overflow the viewport edge.
 *
 * Styling lives in the global `.tooltip-floating` class (app.css) because the
 * element is mounted outside any component's scoped-style tree.
 */

const GAP = 4; // px between the node and the tooltip
const MARGIN = 8; // px min distance kept from the viewport edges

// One shared element reused by every `use:tooltip` node.
let el: HTMLDivElement | null = null;

function ensureEl(): HTMLDivElement {
  if (el) return el;
  el = document.createElement("div");
  el.className = "tooltip-floating";
  el.setAttribute("role", "tooltip");
  el.style.display = "none";
  document.body.appendChild(el);
  return el;
}

function place(node: HTMLElement, tip: HTMLDivElement) {
  const r = node.getBoundingClientRect();
  const { offsetWidth: tw, offsetHeight: th } = tip;
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  // Default: just below, left-aligned to the node. Shift left to stay in view.
  let left = Math.min(r.left, vw - MARGIN - tw);
  left = Math.max(MARGIN, left);

  // Below by default; flip above if it would overflow the bottom edge.
  let top = r.bottom + GAP;
  if (top + th > vh - MARGIN) {
    const above = r.top - GAP - th;
    top = above >= MARGIN ? above : Math.max(MARGIN, vh - MARGIN - th);
  }

  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}

export function tooltip(node: HTMLElement, value: unknown) {
  let current = value;

  function show() {
    if (current === null || current === undefined || current === "") return;
    const tip = ensureEl();
    tip.textContent = String(current);
    tip.style.display = "block";
    place(node, tip); // measure after display+text so sizing is correct
  }

  function hide() {
    if (el) el.style.display = "none";
  }

  node.addEventListener("mouseenter", show);
  node.addEventListener("mouseleave", hide);

  return {
    update(next: unknown) {
      current = next;
      // Keep a currently-visible tooltip in sync (e.g. data swapped on re-run).
      if (el && el.style.display === "block") {
        if (next === null || next === undefined || next === "") hide();
        else {
          el.textContent = String(next);
          place(node, el);
        }
      }
    },
    destroy() {
      node.removeEventListener("mouseenter", show);
      node.removeEventListener("mouseleave", hide);
      hide();
    },
  };
}
