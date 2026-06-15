<!--
  NotebookHeader.svelte — Renders notebook-level docstring as styled Markdown.

  Converts the docstring (from the notebook's module docstring) to HTML via
  marked and displays it in a prominent card above the cell list.

  Props:
    docstring  string  — raw Markdown content (default: "")

  Dependencies: marked (markdown → HTML).
  Exports: None (render-only component).
  Side-effects: None.
  Constraints: Svelte 5 runes ($props, $derived).
-->
<script>
  import { marked } from "marked";

  // Svelte 5 props
  let { docstring = "" } = $props();

  // Svelte 5 derived state
  let html = $derived(docstring ? marked.parse(docstring) : "");
</script>

<div class="notebook-header">
  {@html html}
</div>

<style>
  .notebook-header {
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    padding: 28px;
    margin-bottom: 32px;
    color: var(--fg-primary);
    box-shadow: var(--shadow-lg);
  }

  .notebook-header :global(h1) {
    font-family: var(--font-serif);
    font-size: 2.25rem;
    font-weight: 800;
    margin-top: 0;
    margin-bottom: 18px;
    background: linear-gradient(
      135deg,
      var(--color-primary) 0%,
      var(--color-secondary) 100%
    );
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.025em;
  }

  .notebook-header :global(h2) {
    font-family: var(--font-serif);
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--fg-primary);
    margin-top: 24px;
    margin-bottom: 12px;
  }

  .notebook-header :global(p) {
    font-size: 1.05rem;
    line-height: 1.7;
    margin-bottom: 16px;
  }

  .notebook-header :global(code) {
    font-family: var(--font-mono);
    background: var(--bg-sunken);
    padding: 1px 3px;
    border-radius: var(--radius-sm);
    font-size: 0.9em;
    color: var(--color-primary);
    line-height: 1.5;
  }
</style>
