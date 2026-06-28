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
    runningCell,
    runError,
  } from "./stores/cells";
  import { connectStream } from "./lib/stream";
  import { tooltip } from "./lib/tooltip";
  import NotebookHeader from "./components/NotebookHeader.svelte";
  import Cell from "./components/Cell.svelte";
  import RunSummary from "./components/RunSummary.svelte";
  import NotebookList from "./components/NotebookList.svelte";
  import ExperimentsList from "./components/ExperimentsList.svelte";
  import ExperimentView from "./components/ExperimentView.svelte";
  import AppShell from "./components/AppShell.svelte";

  // The view is selected by query params (navigation is a full-page load, so each
  // view is a fresh SPA):
  //   (none)                      → index list of notebooks
  //   ?view=experiments&path=X    → run history for notebook X
  //   ?path=X&run=R               → read-only view of saved run R
  //   ?path=X                     → notebook X's live stream
  const params = new URLSearchParams(window.location.search);
  const path = params.get("path");
  const view = params.get("view");
  const run = params.get("run");
  const liveStream = !!path && view !== "experiments" && !run;

  onMount(() => {
    if (liveStream) {
      // Show the path in the header immediately, before the first event arrives.
      notebookPath.set(path!);
      connectStream(path!);
    }
  });
</script>

{#if path && view === "experiments"}
  <ExperimentsList {path} />
{:else if path && run}
  <ExperimentView {path} runId={run} />
{:else if !path}
  <NotebookList />
{:else}
  <AppShell>
    {#snippet breadcrumb()}
      <a class="logo-nb logo-home" href="/" title="All notebooks">nb</a>
      <span class="logo-separator">/</span>
      <span class="logo-sub">notebook stream</span>
      {#if $notebookPath}
        <span class="notebook-path" use:tooltip={$notebookPath}>
          <span class="notebook-path-text">{"‎" + $notebookPath}</span>
        </span>
      {/if}
    {/snippet}

    {#snippet aside()}
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
    {/snippet}

    {#snippet bar()}
      <!-- Sticky error banner: shown after a run fails, persists until the next
         run starts. Takes precedence over the live indicator. -->
      {#if $runError}
        <div class="exec-bar error">
          <div class="exec-content">
            <span class="exec-num">Cell {$runError.id + 1}</span>
            {#if $runError.title}
              <span class="exec-title">{$runError.title}</span>
            {/if}
            <span class="error-message">{$runError.message}</span>
          </div>
        </div>
        <!-- Live "now executing" indicator: only present while a cell runs. -->
      {:else if $runningCell}
        <div class="exec-bar">
          <div class="exec-content">
            <div class="run-dot" aria-hidden="true"></div>
            <span class="exec-num">Cell {$runningCell.id + 1}</span>
            {#if $runningCell.title}
              <span class="exec-title">{$runningCell.title}</span>
            {/if}
          </div>
        </div>
      {/if}
    {/snippet}

    {#if $notebookHeader}
      <NotebookHeader docstring={$notebookHeader} />
    {/if}

    {#if $cells.length === 0}
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
    {:else}
      <!-- Only cells that produced output are rendered; cells with no display
         records (imports, pure computation) stay hidden. Cell ids are kept
         as-is so visible numbers still match the notebook. -->
      <div class="cells-list">
        {#each $cells.filter((c) => c.records.length > 0) as cell (cell.id)}
          <Cell {cell} />
        {/each}
      </div>

      <RunSummary cells={$cells} />
    {/if}
  </AppShell>
{/if}

<style>
  /* Live executing indicator */
  .exec-bar {
    border-top: 1px solid var(--border-subtle);
    background: var(--bg-sunken);
  }

  .exec-bar.error {
    background: color-mix(in srgb, var(--color-error) 10%, var(--bg-sunken));
    border-top: 1px solid var(--color-error);
  }

  .exec-bar.error .exec-num {
    color: var(--color-error);
  }

  .error-message {
    color: var(--color-error);
    font-family: var(--font-mono);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .exec-content {
    max-width: 960px;
    margin: 0 auto;
    padding: 6px 24px;
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: var(--font-sans);
    font-size: 12px;
  }

  .exec-bar .run-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #b36200;
    flex-shrink: 0;
    animation: nb-pulse 1.2s ease-in-out infinite;
  }

  .exec-num {
    font-weight: 600;
    color: var(--fg-secondary);
    flex-shrink: 0;
  }

  .exec-title {
    color: var(--fg-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @keyframes nb-pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.3;
    }
  }

  /* Connection status */
  .conn-status {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    color: var(--color-success);
    margin-left: auto;
  }

  .conn-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-success);
  }

  .conn-status.disconnected {
    color: var(--color-error);
  }

  .conn-status.disconnected .conn-dot {
    background: var(--color-error);
  }

  .conn-status.connecting {
    color: var(--color-warning);
  }

  .conn-status.connecting .conn-dot {
    background: var(--color-warning);
    animation: flash 1s infinite alternate;
  }

  .cells-list {
    display: flex;
    flex-direction: column;
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
