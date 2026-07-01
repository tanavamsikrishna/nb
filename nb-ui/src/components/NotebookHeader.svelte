<!--
  NotebookHeader.svelte — Renders notebook-level docstring as styled Markdown.

  Displays the notebook's module docstring in a prominent card above the
  cell list. Markdown rendering is delegated to the Markdown component.

  Collapse behaviour (per-session, shared across all notebooks and both the
  live and experiment views via the `ui` store):
    - Collapsed (default): a quiet full-width strip showing a chevron + the
      docstring's first heading. Click anywhere on it to expand.
    - Expanded: the hero card. Clicking its first line (the title) collapses
      it again; a hover cue (pointer + ▾) hints at this without adding chrome.

  Props:
    docstring  string  — raw Markdown content (default: "")

  Dependencies: Markdown.svelte, stores/ui.svelte.
  Exports: None (render-only component).
  Side-effects: Mutates ui.specCollapsed on toggle.
  Constraints: Svelte 5 runes ($props, $derived).
-->
<script lang="ts">
  import Markdown from "./Markdown.svelte";
  import { marked } from "$lib/marked";
  import { ui } from "../stores/ui.svelte";

  // Svelte 5 props
  let { docstring = "" }: { docstring?: string } = $props();

  // Summary shown on the collapsed strip: the docstring's first Markdown
  // heading, else its first non-empty line, else a generic label — rendered
  // as inline Markdown (parseInline drops the block <p> wrapper so it stays a
  // single ellipsised line) to keep `code`/emphasis styled.
  const titleHtml = $derived(marked.parseInline(firstLine(docstring)) as string);

  function firstLine(md: string): string {
    for (const raw of md.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      const heading = line.match(/^#{1,6}\s+(.*?)\s*#*$/);
      return heading ? heading[1] : line;
    }
    return "Spec";
  }

  // Collapse only when the click lands on the card's first rendered block
  // (the title) — never on body text, so selecting/copying stays safe.
  function onCardClick(e: MouseEvent) {
    const first = e.currentTarget instanceof HTMLElement
      ? e.currentTarget.querySelector(".markdown")?.firstElementChild
      : null;
    if (first && e.target instanceof Node && first.contains(e.target)) {
      ui.specCollapsed = true;
    }
  }
</script>

{#if ui.specCollapsed}
  <button
    class="spec-strip"
    aria-expanded="false"
    onclick={() => (ui.specCollapsed = false)}
  >
    <span class="chev">▸</span>
    <span class="spec-title">{@html titleHtml}</span>
  </button>
{:else}
  <div class="notebook-header" onclick={onCardClick} role="presentation">
    <Markdown source={docstring} variant="hero" />
  </div>
{/if}

<style>
  /* ── Collapsed: quiet breadcrumb-like strip ─────────────────────── */
  .spec-strip {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    margin: 0 0 12px;
    padding: 5px 6px;
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    color: var(--fg-secondary);
    font-family: var(--font-sans);
    font-size: 0.9rem;
    text-align: left;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }

  .spec-strip:hover {
    background: var(--bg-sunken);
    color: var(--fg-primary);
  }

  .chev {
    flex: none;
    font-size: 0.75rem;
    color: var(--fg-muted);
  }

  .spec-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .spec-title :global(code) {
    font-family: var(--font-mono);
    font-size: 0.85em;
    padding: 1px 3px;
    border-radius: var(--radius-sm);
    background: var(--bg-muted);
    color: var(--color-accent);
  }

  /* ── Expanded: the hero card (unchanged) ────────────────────────── */
  .notebook-header {
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    padding: 28px;
    margin-bottom: 32px;
    color: var(--fg-primary);
    box-shadow: var(--shadow-lg);
  }

  /* Title (first rendered block) is the collapse affordance: invisible at
     rest, revealed on hover so it stays crisp and out of the way. */
  .notebook-header :global(.markdown--hero > :first-child) {
    cursor: pointer;
    width: fit-content;
  }

  .notebook-header :global(.markdown--hero > :first-child)::after {
    content: " ▾";
    font-size: 0.6em;
    vertical-align: middle;
    opacity: 0;
    color: var(--fg-muted);
    -webkit-text-fill-color: var(--fg-muted);
    transition: opacity 0.12s;
  }

  .notebook-header :global(.markdown--hero > :first-child:hover)::after {
    opacity: 1;
  }
</style>
