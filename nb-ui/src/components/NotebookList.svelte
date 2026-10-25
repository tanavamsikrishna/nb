<!--
  NotebookList.svelte — the index view at "/" (no ?path= in the URL).

  Lists notebooks the daemon knows about (GET /notebooks): live sessions and
  those with stored experiments. Each row shows the basename (foo.nb.py) then
  the project-relative parent folder, and links to the live stream and/or
  experiment history. A search box filters the full relative path
  (whitespace-split tokens, case-insensitive substring AND). Polls so the list
  stays current. Navigation is a full-page load, so each view is a fresh SPA
  instance that connects to its own stream.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import type { NotebookListItem, NotebooksResponse } from "../lib/types";
  import { notebookRelParts, pathMatchesQuery } from "../lib/notebookPath";
  import { tooltip } from "../lib/tooltip";
  import AppShell from "./AppShell.svelte";

  let notebooks = $state<NotebookListItem[]>([]);
  let loaded = $state(false);
  let failed = $state(false);
  let query = $state("");

  const POLL_MS = 3000;

  const visible = $derived(
    notebooks.filter((nb) => pathMatchesQuery(nb.rel, query)),
  );

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

  function onSearchKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") query = "";
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
    <input
      type="search"
      class="nb-search"
      placeholder="Search notebooks…"
      bind:value={query}
      onkeydown={onSearchKeydown}
      spellcheck="false"
      autocomplete="off"
    />
    {#if visible.length > 0}
      <ul class="nb-list">
        {#each visible as nb (nb.path)}
          {@const parts = notebookRelParts(nb.rel)}
          <li>
            <div class="nb-item">
              <span class="nb-title">
                <span
                  class="nb-name"
                  use:tooltip={{ value: nb.rel, onlyIfOverflow: true }}
                  >{parts.name}</span
                >
                {#if parts.parent}
                  <span
                    class="nb-dir"
                    use:tooltip={{ value: parts.parent, onlyIfOverflow: true }}
                    >{parts.parent}</span
                  >
                {/if}
              </span>
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
    {:else}
      <p class="no-match">No matching notebooks</p>
    {/if}
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
  .nb-search {
    display: block;
    width: 100%;
    box-sizing: border-box;
    margin-bottom: 16px;
    font-family: var(--font-mono);
    font-size: 0.85rem;
    background: var(--bg-sunken);
    color: var(--fg-primary);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    padding: 10px 12px;
    outline: none;
    transition: border-color 0.2s;
  }

  .nb-search:focus {
    border-color: var(--color-primary);
  }

  .nb-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .nb-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px 16px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    background: var(--bg-muted);
    color: inherit;
    transition:
      border-color 0.12s ease,
      background 0.12s ease;
  }

  .nb-item:hover {
    border-color: var(--color-primary);
    background: var(--bg-sunken);
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

  /* Filename first, parent folder after — same row rhythm as experiment runs. */
  .nb-title {
    display: flex;
    align-items: baseline;
    gap: 10px;
    min-width: 0;
    font-family: var(--font-mono);
  }

  .nb-name {
    flex: 0 1 auto;
    max-width: 70%;
    font-size: 0.75rem;
    font-weight: 400;
    color: var(--fg-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .nb-dir {
    flex: 1 1 0;
    min-width: 0;
    color: var(--fg-tertiary);
    font-size: 0.75rem;
    font-weight: 400;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .nb-meta {
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: var(--font-sans);
    font-size: 0.75rem;
    color: var(--fg-secondary);
  }

  .no-match {
    font-family: var(--font-sans);
    font-size: 0.9rem;
    color: var(--fg-secondary);
    padding: 24px 0;
    text-align: center;
  }
</style>
