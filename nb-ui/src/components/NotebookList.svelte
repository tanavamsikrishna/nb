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

  function href(path: string): string {
    return "/?path=" + encodeURIComponent(path);
  }

  onMount(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  });
</script>

<div class="app-wrapper">
  <header class="app-header">
    <div class="header-content">
      <div class="logo-area">
        <span class="logo-nb">nb</span>
        <span class="logo-separator">/</span>
        <span class="logo-sub">notebooks</span>
      </div>
    </div>
  </header>

  <main class="main-container">
    {#if loaded && notebooks.length > 0}
      <ul class="nb-list">
        {#each notebooks as nb (nb.path)}
          <li>
            <a class="nb-item" href={href(nb.path)}>
              <span class="nb-name">{nb.name}</span>
              <span class="nb-path">{nb.path}</span>
              <span class="nb-meta">
                <span class="nb-cells"
                  >{nb.num_cells}
                  {nb.num_cells === 1 ? "cell" : "cells"}</span
                >
              </span>
            </a>
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
  </main>
</div>

<style>
  .app-wrapper {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }

  .app-header {
    background: var(--bg-header);
    border-bottom: 1px solid var(--border-default);
    position: sticky;
    top: 0;
    z-index: 50;
  }

  .header-content {
    max-width: 960px;
    margin: 0 auto;
    padding: 16px 24px;
    display: flex;
    align-items: center;
  }

  .logo-area {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
    font-family: var(--font-sans);
  }

  .logo-nb {
    font-size: 1.5rem;
    background: linear-gradient(
      135deg,
      var(--color-primary) 0%,
      var(--color-secondary) 100%
    );
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.05em;
  }

  .logo-separator {
    color: var(--border-default);
    font-weight: 300;
  }

  .logo-sub {
    font-size: 0.875rem;
    color: var(--fg-secondary);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }

  .main-container {
    max-width: 960px;
    width: 100%;
    margin: 0 auto;
    padding: 40px 24px;
    flex-grow: 1;
    box-sizing: border-box;
  }

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
    text-decoration: none;
    color: inherit;
    transition:
      border-color 0.12s ease,
      background 0.12s ease;
  }

  .nb-item:hover {
    border-color: var(--color-primary);
    background: var(--bg-sunken);
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

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    background: var(--bg-muted);
    border: 1px dashed var(--border-subtle);
    border-radius: var(--radius-xl);
    padding: 60px 40px;
    margin-top: 40px;
  }

  .empty-state h2 {
    font-size: 1.5rem;
    font-weight: 600;
    margin: 0 0 12px;
    color: var(--fg-primary);
    font-family: var(--font-sans);
  }

  .empty-state p {
    color: var(--fg-secondary);
    max-width: 400px;
    font-size: 0.95rem;
    line-height: 1.6;
    margin: 0 0 24px;
  }

  .cmd-example {
    font-family: var(--font-mono);
    font-size: 0.9rem;
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    padding: 10px 20px;
    border-radius: var(--radius-md);
    color: var(--color-primary);
  }

  .cmd-example .arg {
    color: var(--fg-secondary);
  }
</style>
