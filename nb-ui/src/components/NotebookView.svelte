<!--
  NotebookView.svelte — shared body rendered by both the live stream and the
  saved-run viewer. Accepts inert props; never re-wraps cells in $state.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Cell } from "../lib/types";
  import NotebookHeader from "./NotebookHeader.svelte";
  import Cell_ from "./Cell.svelte";
  import RunSummary from "./RunSummary.svelte";
  import hljs from "highlight.js/lib/core";
  import python from "highlight.js/lib/languages/python";
  import "highlight.js/styles/github.css";

  hljs.registerLanguage("python", python);

  let {
    cells,
    docstring = null,
    code = null,
    emptyState,
  }: {
    cells: Cell[];
    docstring?: string | null;
    code?: string | null;
    emptyState?: Snippet;
  } = $props();

  let highlightedCode = $derived(
    code ? hljs.highlight(code, { language: "python" }).value : null,
  );
</script>

{#if docstring}
  <NotebookHeader {docstring} />
{/if}

{#if cells.length === 0}
  {@render emptyState?.()}
{:else}
  <div class="cells-list">
    {#each cells as cell (cell.id)}
      <Cell_ {cell} />
    {/each}
  </div>

  <RunSummary {cells} />
{/if}

{#if code}
  <section class="source-block">
    <details>
      <summary>Source code</summary>
      <pre class="code-block"><code class="hljs">{@html highlightedCode}</code
        ></pre>
    </details>
  </section>
{/if}

<style>
  .cells-list {
    display: flex;
    flex-direction: column;
  }

  .source-block {
    margin-top: 32px;
  }

  summary {
    cursor: pointer;
    font-family: var(--font-sans);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--fg-secondary);
  }

  .code-block {
    margin: 12px 0 0;
    padding: 16px;
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    font-family: var(--font-mono);
    font-size: 0.8rem;
    line-height: 1.5;
    color: var(--fg-primary);
    overflow-x: auto;
    white-space: pre;
  }

  /* Let the .code-block surface control the background; hljs theme sets its own */
  .code-block :global(.hljs) {
    background: transparent;
    padding: 0;
  }
</style>
