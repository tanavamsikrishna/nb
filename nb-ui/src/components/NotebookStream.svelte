<!--
  NotebookStream.svelte — live SSE notebook view (?path=X).

  Connects to the daemon's event stream and renders the live notebook state.
  Live-only chrome (connection status, exec/error bar) lives here; common
  content (docstring, cells, source, timings) is delegated to NotebookView.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { notebook, view } from "../stores/notebook.svelte";
  import { connectStream } from "../lib/stream";
  import { tooltip } from "../lib/tooltip";
  import AppShell from "./AppShell.svelte";
  import NotebookView from "./NotebookView.svelte";

  let { path }: { path: string } = $props();

  onMount(() => {
    connectStream(path);
  });
</script>

<AppShell>
  {#snippet breadcrumb()}
    <a class="logo-nb logo-home" href="/" title="All notebooks">nb</a>
    <span class="logo-separator">/</span>
    <span class="logo-sub">notebook stream</span>
    {#if notebook.path}
      <span class="notebook-path" use:tooltip={notebook.path}>
        <span class="notebook-path-text">{"‎" + notebook.path}</span>
      </span>
    {/if}
  {/snippet}

  {#snippet aside()}
    <div class="conn-status {view.connection}">
      <div class="conn-dot"></div>
      {#if view.connection === "connected"}
        connected to daemon
      {:else if view.connection === "connecting"}
        connecting...
      {:else}
        disconnected
      {/if}
    </div>
  {/snippet}

  {#snippet bar()}
    {#if view.error}
      <div class="exec-bar error">
        <div class="exec-content">
          <span class="exec-num">Cell {view.error.id + 1}</span>
          {#if view.error.title}
            <span class="exec-title">{view.error.title}</span>
          {/if}
          <span class="error-message">{view.error.message}</span>
        </div>
      </div>
    {:else if view.running}
      <div class="exec-bar">
        <div class="exec-content">
          <div class="run-dot" aria-hidden="true"></div>
          <span class="exec-num">Cell {view.running.id + 1}</span>
          {#if view.running.title}
            <span class="exec-title">{view.running.title}</span>
          {/if}
        </div>
      </div>
    {/if}
  {/snippet}

  <NotebookView
    cells={notebook.cells}
    docstring={notebook.header}
    code={notebook.source}
  >
    {#snippet emptyState()}
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
    {/snippet}
  </NotebookView>
</AppShell>

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

  @keyframes flash {
    0% {
      opacity: 0.4;
    }
    100% {
      opacity: 1;
    }
  }
</style>
