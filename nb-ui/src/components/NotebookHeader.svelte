<!--
  NotebookHeader.svelte — Renders notebook-level docstring as styled Markdown.

  Displays the notebook's module docstring in a prominent card above the
  cell list. Markdown rendering is delegated to the Markdown component.

  Collapse behaviour (per-session, shared across all notebooks and both the
  live and experiment views via the `ui` store): the title row (chevron +
  hero title) is always rendered identically — it never moves or restyles.
  Toggling only shows/hides the body below it. Collapsed by default so cells
  stay front-and-centre. The title heading is hoisted into the row and
  stripped from the body so it isn't shown twice.

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

  // Split the docstring into its title (first non-empty line, minus any
  // leading `#`) and the remaining body. The title is always shown in the
  // toggle row and stripped from the body so it never renders twice.
  const spec = $derived(parseSpec(docstring));

  // Title rendered as inline Markdown (parseInline drops the block <p> wrapper)
  // so `code`/emphasis in the heading stay styled.
  const titleHtml = $derived(marked.parseInline(spec.title) as string);

  function parseSpec(md: string): { title: string; body: string } {
    const lines = md.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (!line) continue;
      const heading = line.match(/^#{1,6}\s+(.*?)\s*#*$/);
      const title = heading ? heading[1] : line;
      const body = [...lines.slice(0, i), ...lines.slice(i + 1)].join("\n");
      return { title, body };
    }
    return { title: "Spec", body: "" };
  }

  const toggle = () => (ui.specCollapsed = !ui.specCollapsed);
</script>

<div class="notebook-header" class:collapsed={ui.specCollapsed}>
  <button
    class="spec-header"
    aria-expanded={!ui.specCollapsed}
    onclick={toggle}
  >
    <span class="chev" class:open={!ui.specCollapsed}>▸</span>
    <h1 class="spec-title">{@html titleHtml}</h1>
  </button>
  {#if !ui.specCollapsed && spec.body.trim()}
    <Markdown source={spec.body} variant="hero" />
  {/if}
</div>

<style>
  .notebook-header {
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    padding: 16px 28px;
    margin-bottom: 32px;
    color: var(--fg-primary);
    box-shadow: var(--shadow-lg);
  }

  /* Toggle row: chevron + hero title. Identical in both states. */
  .spec-header {
    display: flex;
    align-items: center;
    gap: 14px;
    width: 100%;
    padding: 0;
    background: none;
    border: none;
    text-align: left;
    cursor: pointer;
  }

  /* Body appears below the title row when expanded. */
  .notebook-header :global(.markdown--hero) {
    margin-top: 14px;
  }

  .chev {
    flex: none;
    font-size: 1.1rem;
    color: var(--fg-muted);
    transition: transform 0.15s ease, color 0.12s;
  }

  .chev.open {
    transform: rotate(90deg);
  }

  .spec-header:hover .chev {
    color: var(--fg-secondary);
  }

  .spec-title {
    margin: 0;
    font-family: var(--font-sans);
    font-size: 2.25rem;
    font-weight: 800;
    letter-spacing: -0.025em;
    background: linear-gradient(
      135deg,
      var(--color-primary) 0%,
      var(--color-secondary) 100%
    );
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  .spec-title :global(code) {
    font-family: var(--font-mono);
    font-size: 0.85em;
  }
</style>
