<!--
  NotebookList.svelte — the index view at "/" (no ?path= in the URL).

  Lists the notebooks the daemon currently holds state for (GET /notebooks) and
  links each to its per-notebook stream view at "/?path=<abs path>". Polls so the
  list stays current as new notebooks are run. Navigation is a full-page load,
  so each view is a fresh SPA instance that connects to its own stream.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import type { NotebookListItem, NotebooksResponse } from "../lib/types";
  import AppShell from "./AppShell.svelte";

  let notebooks = $state<NotebookListItem[]>([]);
  let loaded = $state(false);
  let failed = $state(false);

  const POLL_MS = 3000;

  async function load() {
    try {
      const resp = await fetch("/notebooks");
      if (!resp.ok) throw new Error(String(resp.status));
      const data: NotebooksResponse = await resp.json();
      notebooks = data.notebooks;
      failed = false;
    } catch {
      failed = true;
    } finally {
      loaded = true;
    }
  }

  function streamHref(path: string): string {
    return "/?path=" + encodeURIComponent(path);
  }

  function experimentsHref(path: string): string {
    return "/?view=experiments&path=" + encodeURIComponent(path);
  }

  onMount(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  });
</script>

<AppShell>
  {#snippet breadcrumb()}
    <span class="logo-nb">nb</span>
    <span class="logo-separator">/</span>
    <span class="logo-sub">notebooks</span>
  {/snippet}

  {#if loaded && notebooks.length > 0}
    <ul class="nb-list">
      {#each notebooks as nb (nb.path)}
        <li>
          <div class="nb-item">
            <span class="nb-name">{nb.name}</span>
            <span class="nb-path">{nb.path}</span>
            <span class="nb-meta">
              {#if nb.active}
                <a class="nb-link" href={streamHref(nb.path)}>
                  Live stream
                  <span class="nb-cells"
                    >· {nb.num_cells}
                    {nb.num_cells === 1 ? "cell" : "cells"}</span
                  >
                </a>
              {/if}
              {#if nb.has_experiments}
                <a class="nb-link" href={experimentsHref(nb.path)}>
                  Experiments
                </a>
              {/if}
            </span>
          </div>
        </li>
      {/each}
    </ul>
  {:else if loaded}
    <div class="empty-state">
      <h2>No notebooks yet</h2>
      {#if failed}
        <p>Couldn't reach the daemon. Is it running?</p>
      {:else}
        <p>Run a notebook to see it here:</p>
        <code class="cmd-example"
          >nb run <span class="arg">my_notebook.py</span></code
        >
      {/if}
    </div>
  {/if}
</AppShell>

<style>
  .nb-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .nb-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 14px 18px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    background: var(--bg-muted);
    color: inherit;
  }

  .nb-link {
    font-family: var(--font-sans);
    color: var(--color-primary);
    text-decoration: none;
    font-weight: 600;
  }

  .nb-link:hover {
    text-decoration: underline;
  }

  .nb-name {
    font-family: var(--font-sans);
    font-weight: 600;
    font-size: 1rem;
    color: var(--fg-primary);
  }

  .nb-path {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--fg-tertiary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .nb-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
    font-family: var(--font-sans);
    font-size: 0.75rem;
    color: var(--fg-secondary);
  }
</style>
