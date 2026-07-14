<!--
  Markdown.svelte — Renders raw Markdown content as styled HTML.

  Centralises markdown rendering and typography so every consumer (cells,
  notebook header, future surfaces) shares one consistent style system.

  Props:
    source   string            — raw Markdown text (default: "")
    variant  "inline" | "hero" — rendering context (default: "inline")
      "inline" — compact cell output (tighter spacing, smaller headings)
      "hero"   — prominent card header (large headings, gradient h1)

  Dependencies: marked (markdown → HTML, configured with `breaks: true`).
  Exports: None (render-only component).
  Side-effects: None.
  Constraints: Svelte 5 runes ($props, $derived).
-->
<script lang="ts">
  import { marked } from "$lib/marked";

  let {
    source = "",
    variant = "inline",
  }: { source?: string; variant?: "inline" | "hero" } = $props();

  let html = $derived(source ? marked.parse(source) : "");
</script>

<div class="markdown markdown--{variant}">
  {@html html}
</div>

<style>
  /* ── Base wrapper ───────────────────────────────────────────────── */
  .markdown {
    color: var(--fg-primary);
  }

  /* ── Shared structural typography (all variants) ────────────────── */

  .markdown :global(pre) {
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 12px;
    overflow-x: auto;
  }

  .markdown :global(pre code) {
    background: none;
    padding: 0;
    border-radius: 0;
    color: inherit;
  }

  .markdown :global(code) {
    font-family: var(--font-mono);
    font-size: 0.85em;
    padding: 1px 3px;
    border-radius: var(--radius-sm);
    line-height: 1;
  }

  .markdown :global(table) {
    font-family: var(--font-mono);
    border-collapse: collapse;
    width: 100%;
    font-size: 0.85rem;
    margin: 8px 0;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    overflow: hidden;
  }

  .markdown :global(th) {
    background: var(--bg-header);
    color: var(--fg-primary);
    font-weight: 600;
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-default);
  }

  .markdown :global(td) {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-subtle);
    color: var(--fg-primary);
  }

  .markdown :global(tr:hover) {
    background: var(--bg-sunken);
  }

  .markdown :global(ol),
  .markdown :global(ul) {
    margin-left: 1rem;
  }

  /* ── Variant: inline (cell output) ──────────────────────────────── */

  .markdown--inline {
    font-size: 0.95rem;
    /* line-height: 1.6; */
  }

  .markdown--inline :global(h1),
  .markdown--inline :global(h2),
  .markdown--inline :global(h3) {
    font-family: var(--font-sans);
    color: var(--fg-primary);
  }

  .markdown--inline :global(code) {
    background: var(--bg-muted);
    color: var(--color-accent);
  }

  /* ── Variant: hero (notebook header card) ───────────────────────── */

  .markdown--hero {
    line-height: 1.7;
  }

  .markdown--hero :global(h1) {
    font-family: var(--font-sans);
    font-size: 2.25rem;
    font-weight: 800;
    color: var(--fg-primary);
    letter-spacing: -0.025em;
  }

  .markdown--hero :global(h2) {
    font-family: var(--font-sans);
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--fg-primary);
  }

  .markdown--hero :global(h3) {
    font-family: var(--font-sans);
    font-size: 1.15rem;
    font-weight: 600;
    color: var(--fg-primary);
  }

  .markdown--hero :global(code) {
    background: var(--bg-sunken);
    color: var(--color-primary);
  }
</style>
