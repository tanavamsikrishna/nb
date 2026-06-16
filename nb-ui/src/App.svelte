<!--
  App.svelte — Root application shell for nb-notebook stream UI.

  Renders the sticky header bar (logo + connection status badge) and the
  main content area containing the optional NotebookHeader and the list of
  Cell components. Shows an empty-state placeholder when no cells exist.

  Dependencies:
    - stores/cells.js       (cells, notebookHeader, connectionStatus stores)
    - lib/stream.js         (connectStream — SSE connection on mount)
    - components/NotebookHeader.svelte
    - components/Cell.svelte

  Exports: None (top-level mount target).
  Side-effects: Calls connectStream() on mount to open the SSE channel.
  Constraints: Svelte 5 runes ($props, $state, $derived, $effect).
-->
<script lang="ts">
  import { onMount } from "svelte";
  import {
    cells,
    notebookHeader,
    notebookPath,
    connectionStatus,
  } from "./stores/cells";
  import { connectStream } from "./lib/stream";
  import NotebookHeader from "./components/NotebookHeader.svelte";
  import Cell from "./components/Cell.svelte";

  onMount(() => {
    connectStream();
  });
</script>

<div class="app-wrapper">
  <!-- Top Navigation Bar -->
  <header class="app-header">
    <div class="header-content">
      <div class="logo-area">
        <span class="logo-nb">nb</span>
        <span class="logo-separator">/</span>
        <span class="logo-sub">notebook stream</span>
        {#if $notebookPath}
          <span class="notebook-path" title={$notebookPath}
            >{$notebookPath}</span
          >
        {/if}
      </div>

      <div class="conn-status {$connectionStatus}">
        <div class="conn-dot"></div>
        {#if $connectionStatus === "connected"}
          connected to daemon
        {:else if $connectionStatus === "connecting"}
          connecting...
        {:else}
          disconnected
        {/if}
      </div>
    </div>
  </header>

  <!-- Main Content Area -->
  <main class="main-container">
    {#if $notebookHeader}
      <NotebookHeader docstring={$notebookHeader} />
    {/if}

    <div class="cells-list">
      {#each $cells as cell (cell.id)}
        <Cell {cell} />
      {:else}
        <div class="empty-state">
          <div class="empty-icon-wrap">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="1.5"
              stroke="currentColor"
              class="empty-icon"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5"
              />
            </svg>
          </div>
          <h2>No Active Notebook Stream</h2>
          <p>
            The UI is waiting for a notebook execution. Start a run using the
            command line:
          </p>
          <code class="cmd-example"
            >nb run <span class="arg">my_notebook.py</span></code
          >
        </div>
      {/each}
    </div>
  </main>
</div>

<style>
  :global(body) {
    background-color: var(--bg-base);
    color: var(--fg-primary);
    font-family: var(--font-serif);
    margin: 0;
    padding: 0;
    min-height: 100vh;
  }

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
    justify-content: space-between;
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

  .notebook-path {
    font-size: 0.75rem;
    color: var(--fg-tertiary);
    font-family: var(--font-mono);
    font-weight: 400;
    text-transform: none;
    letter-spacing: normal;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin-left: 8px;
    padding: 2px 8px;
    background: var(--bg-sunken);
    border-radius: var(--radius-sm);
  }

  /* Connection status */
  .conn-status {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    color: #6A8A6A;
    margin-left: auto;
  }

  .conn-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #5A9A5A;
  }

  .conn-status.disconnected {
    color: #A04030;
  }

  .conn-status.disconnected .conn-dot {
    background: #C05040;
  }

  .conn-status.connecting {
    color: #8A7A5A;
  }

  .conn-status.connecting .conn-dot {
    background: #A09050;
    animation: flash 1s infinite alternate;
  }

  /* Container */
  .main-container {
    max-width: 960px;
    width: 100%;
    margin: 0 auto;
    padding: 40px 24px;
    flex-grow: 1;
    box-sizing: border-box;
  }

  .cells-list {
    display: flex;
    flex-direction: column;
  }

  /* Empty state */
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

  .empty-icon-wrap {
    width: 64px;
    height: 64px;
    background: var(--bg-sunken);
    color: var(--color-primary);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 24px;
  }

  .empty-icon {
    width: 32px;
    height: 32px;
  }

  .empty-state h2 {
    font-size: 1.5rem;
    font-weight: 600;
    margin-top: 0;
    margin-bottom: 12px;
    color: var(--fg-primary);
    font-family: var(--font-sans);
  }

  .empty-state p {
    color: var(--fg-secondary);
    max-width: 400px;
    font-size: 0.95rem;
    line-height: 1.6;
    margin-top: 0;
    margin-bottom: 24px;
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

  @keyframes flash {
    0% {
      opacity: 0.4;
    }
    100% {
      opacity: 1;
    }
  }
</style>
