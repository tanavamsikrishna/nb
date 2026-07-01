<!--
  NotebookView.svelte — shared body rendered by both the live stream and the
  saved-run viewer. Accepts inert props; never re-wraps cells in $state.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Artifact, Cell, ParamsMap } from "../lib/types";
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
    params = {},
    artifacts = [],
    emptyState,
  }: {
    cells: Cell[];
    docstring?: string | null;
    code?: string | null;
    params?: ParamsMap;
    artifacts?: Artifact[];
    emptyState?: Snippet;
  } = $props();

  let highlightedCode = $derived(
    code ? hljs.highlight(code, { language: "python" }).value : null,
  );

  let paramEntries = $derived(Object.entries(params));

  // Download through the daemon, which validates the path lives inside the
  // experiments store (see daemon.artifact_handler).
  function artifactHref(a: Artifact): string {
    return "/artifact?file=" + encodeURIComponent(a.path);
  }

  // Suggested download filename: the logged name, plus the file's real extension
  // when the name doesn't already carry one (the on-disk name is a temp string).
  function downloadName(a: Artifact): string {
    if (a.name.includes(".")) return a.name;
    const dot = a.path.lastIndexOf(".");
    const slash = Math.max(a.path.lastIndexOf("/"), a.path.lastIndexOf("\\"));
    const ext = dot > slash ? a.path.slice(dot) : "";
    return a.name + ext;
  }

  // Which artifact path was just copied, for transient "Copied" feedback.
  let copiedPath = $state<string | null>(null);
  let copiedTimer: ReturnType<typeof setTimeout> | undefined;

  async function copyPath(path: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(path);
    } catch {
      // Fallback for non-secure contexts where the async clipboard API is blocked.
      const ta = document.createElement("textarea");
      ta.value = path;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    copiedPath = path;
    clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => (copiedPath = null), 1500);
  }
</script>

{#if docstring}
  <NotebookHeader {docstring} />
{/if}

{#if paramEntries.length > 0}
  <section class="params-block">
    <h3>Parameters</h3>
    <table class="params-table">
      <tbody>
        {#each paramEntries as [key, value]}
          <tr>
            <th>{key}</th>
            <td>{value}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </section>
{/if}

{#if artifacts.length > 0}
  <section class="artifacts-block">
    <h3>Files</h3>
    <ul class="artifacts-list">
      {#each artifacts as artifact}
        <li>
          <a
            class="artifact-link"
            href={artifactHref(artifact)}
            download={downloadName(artifact)}
          >
            <svg
              class="artifact-icon"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M12 3v12m0 0l-4-4m4 4l4-4" />
              <path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
            </svg>
            <span class="artifact-name">{artifact.name}</span>
            <span class="artifact-file">{downloadName(artifact)}</span>
          </a>
          <button
            type="button"
            class="artifact-copy"
            title={artifact.path}
            aria-label="Copy full path"
            onclick={() => copyPath(artifact.path)}
          >
            {#if copiedPath === artifact.path}
              <svg
                class="artifact-icon"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M20 6L9 17l-5-5" />
              </svg>
              <span>Copied</span>
            {:else}
              <svg
                class="artifact-icon"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <rect x="9" y="9" width="11" height="11" rx="2" />
                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
              </svg>
              <span>Copy path</span>
            {/if}
          </button>
        </li>
      {/each}
    </ul>
  </section>
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
  .params-block {
    margin-bottom: 32px;
  }

  .params-block h3 {
    font-family: var(--font-sans);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--fg-secondary);
    margin: 0 0 12px;
  }

  .params-table {
    border-collapse: collapse;
    font-family: var(--font-mono);
    font-size: 0.85rem;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    overflow: hidden;
  }

  .params-table th {
    text-align: left;
    font-weight: 600;
    color: var(--fg-secondary);
    background: var(--bg-header);
    padding: 6px 12px;
    border-bottom: 1px solid var(--border-subtle);
    border-right: 1px solid var(--border-subtle);
    white-space: nowrap;
  }

  .params-table td {
    padding: 6px 12px;
    color: var(--fg-primary);
    border-bottom: 1px solid var(--border-subtle);
  }

  .params-table tr:last-child th,
  .params-table tr:last-child td {
    border-bottom: none;
  }

  .artifacts-block {
    margin-bottom: 32px;
  }

  .artifacts-block h3 {
    font-family: var(--font-sans);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--fg-secondary);
    margin: 0 0 12px;
  }

  .artifacts-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .artifacts-list li {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .artifact-link {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 6px 12px;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    background: var(--bg-muted);
    text-decoration: none;
    color: inherit;
    width: fit-content;
    max-width: 100%;
    transition:
      border-color 0.12s ease,
      background 0.12s ease;
  }

  .artifact-link:hover {
    border-color: var(--color-primary);
    background: var(--bg-sunken);
  }

  .artifact-icon {
    width: 15px;
    height: 15px;
    color: var(--fg-tertiary);
    flex-shrink: 0;
  }

  .artifact-name {
    font-family: var(--font-mono);
    font-size: 0.85rem;
    color: var(--fg-primary);
  }

  .artifact-file {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--fg-tertiary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .artifact-copy {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    background: var(--bg-muted);
    color: var(--fg-secondary);
    font-family: var(--font-sans);
    font-size: 0.75rem;
    cursor: pointer;
    flex-shrink: 0;
    transition:
      border-color 0.12s ease,
      background 0.12s ease,
      color 0.12s ease;
  }

  .artifact-copy:hover {
    border-color: var(--color-primary);
    background: var(--bg-sunken);
    color: var(--fg-primary);
  }

  .artifact-copy .artifact-icon {
    color: currentColor;
  }

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
