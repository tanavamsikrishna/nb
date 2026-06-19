<!--
  NotebookHeader.svelte — Renders notebook-level docstring as styled Markdown.

  Displays the notebook's module docstring in a prominent card above the
  cell list. Markdown rendering is delegated to the Markdown component.

  Props:
    docstring  string  — raw Markdown content (default: "")

  Dependencies: Markdown.svelte.
  Exports: None (render-only component).
  Side-effects: None.
  Constraints: Svelte 5 runes ($props).
-->
<script lang="ts">
  import Markdown from "./Markdown.svelte";

  // Svelte 5 props
  let { docstring = "" }: { docstring?: string } = $props();
</script>

<div class="notebook-header">
  <Markdown source={docstring} variant="hero" />
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
</style>
