<script>
  import { onMount } from 'svelte';
  import { cells, notebookHeader, connectionStatus } from './stores/cells.js';
  import { connectStream } from './lib/stream.js';
  import NotebookHeader from './components/NotebookHeader.svelte';
  import Cell from './components/Cell.svelte';

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
      </div>

      <div class="status-badge {$connectionStatus}">
        <span class="badge-dot"></span>
        <span class="badge-text">
          {#if $connectionStatus === 'connected'}
            connected to daemon
          {:else if $connectionStatus === 'connecting'}
            connecting...
          {:else}
            disconnected
          {/if}
        </span>
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
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="empty-icon">
              <path stroke-linecap="round" stroke-linejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
            </svg>
          </div>
          <h2>No Active Notebook Stream</h2>
          <p>The UI is waiting for a notebook execution. Start a run using the command line:</p>
          <code class="cmd-example">nb run <span class="arg">my_notebook.py</span></code>
        </div>
      {/each}
    </div>
  </main>
</div>

<style>
  :global(body) {
    background-color: #0b0f19;
    color: #f1f5f9;
    font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
    margin: 0;
    padding: 0;
    min-height: 100vh;
    background-image: radial-gradient(circle at top right, rgba(99, 102, 241, 0.08), transparent 450px),
                      radial-gradient(circle at bottom left, rgba(192, 132, 252, 0.05), transparent 400px);
    background-attachment: fixed;
  }

  .app-wrapper {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }

  .app-header {
    background: rgba(15, 23, 42, 0.6);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
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
  }

  .logo-nb {
    font-size: 1.5rem;
    background: linear-gradient(135deg, #818cf8 0%, #a78bfa 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.05em;
  }

  .logo-separator {
    color: #334155;
    font-weight: 300;
  }

  .logo-sub {
    font-size: 0.875rem;
    color: #64748b;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }

  /* Connection badge */
  .status-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 9999px;
    padding: 6px 14px;
    font-size: 0.75rem;
    font-weight: 500;
    transition: all 0.3s ease;
  }

  .badge-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: #64748b;
  }

  .status-badge.connected {
    background: rgba(16, 185, 129, 0.06);
    border-color: rgba(16, 185, 129, 0.2);
    color: #34d399;
  }

  .status-badge.connected .badge-dot {
    background-color: #10b981;
    box-shadow: 0 0 8px #10b981;
  }

  .status-badge.connecting {
    background: rgba(245, 158, 11, 0.06);
    border-color: rgba(245, 158, 11, 0.2);
    color: #fbbf24;
  }

  .status-badge.connecting .badge-dot {
    background-color: #f59e0b;
    animation: flash 1s infinite alternate;
  }

  .status-badge.disconnected {
    background: rgba(239, 68, 68, 0.06);
    border-color: rgba(239, 68, 68, 0.2);
    color: #f87171;
  }

  .status-badge.disconnected .badge-dot {
    background-color: #ef4444;
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
    background: rgba(30, 41, 59, 0.2);
    border: 1px dashed rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 60px 40px;
    margin-top: 40px;
  }

  .empty-icon-wrap {
    width: 64px;
    height: 64px;
    background: rgba(99, 102, 241, 0.1);
    color: #818cf8;
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
    color: #f1f5f9;
  }

  .empty-state p {
    color: #94a3b8;
    max-width: 400px;
    font-size: 0.95rem;
    line-height: 1.6;
    margin-top: 0;
    margin-bottom: 24px;
  }

  .cmd-example {
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.9rem;
    background: #0f172a;
    border: 1px solid rgba(255, 255, 255, 0.08);
    padding: 10px 20px;
    border-radius: 8px;
    color: #818cf8;
  }

  .cmd-example .arg {
    color: #cbd5e1;
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
