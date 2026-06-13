<script>
  import { marked } from 'marked';
  import JSONTree from './JSONTree.svelte';
  import { loadPlotly, loadVega } from '../lib/lazy_load.js';

  // Svelte 5 props
  let { cell } = $props();

  // Svelte actions for third party rendering
  function plotlyAction(node, payload) {
    let active = true;
    loadPlotly()
      .then(Plotly => {
        if (active) {
          Plotly.newPlot(node, payload.data, payload.layout, payload.config || {});
        }
      })
      .catch(err => {
        if (active) {
          node.innerHTML = `<span class="error-msg">Failed to render Plotly: ${err.message || err}</span>`;
        }
      });

    return {
      destroy() {
        active = false;
      }
    };
  }

  function altairAction(node, payload) {
    let active = true;
    loadVega()
      .then(vegaEmbed => {
        if (active) {
          vegaEmbed(node, payload, { actions: false });
        }
      })
      .catch(err => {
        if (active) {
          node.innerHTML = `<span class="error-msg">Failed to render Altair: ${err.message || err}</span>`;
        }
      });

    return {
      destroy() {
        active = false;
      }
    };
  }
</script>

<div class="cell-container {cell.status} {cell.stale ? 'stale' : ''} {cell.absent ? 'absent' : ''}">
  <!-- Cell Header / Status Bar -->
  <div class="cell-header">
    <div class="left-header">
      <span class="status-indicator"></span>
      <span class="cell-name">Cell #{cell.id}</span>
      {#if cell.label}
        <span class="cell-label">{cell.label}</span>
      {/if}
      {#if cell.stale}
        <span class="stale-badge">Stale</span>
      {/if}
    </div>
    
    {#if cell.profiling}
      <div class="profiling-stats">
        <span class="stat-item">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="icon">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.5-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clip-rule="evenodd" />
          </svg>
          {cell.profiling.wall_ms}ms wall
        </span>
        <span class="stat-divider">•</span>
        <span class="stat-item">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="icon">
            <path d="M12 9a1 1 0 011-1h3a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1V9z" />
            <path fill-rule="evenodd" d="M19.307 2.193a.75.75 0 00-1.147-.193l-3.58 3.033A2.247 2.247 0 0013.25 5H6.75A2.25 2.25 0 004.5 7.25v5.5A2.25 2.25 0 006.75 15h6.5a2.24 2.24 0 001.33-.433l3.58 3.033a.75.75 0 001.147-.193c.12-.224.08-.502-.103-.686l-2.029-2.03A3.722 3.722 0 0018 12.75v-5.5c0-1.042-.435-1.983-1.135-2.656l2.029-2.03a.75.75 0 00.413-.671zM15 7.25v5.5a.75.75 0 01-.75.75h-6.5a.75.75 0 01-.75-.75v-5.5a.75.75 0 01.75-.75h6.5a.75.75 0 01.75.75z" clip-rule="evenodd" />
          </svg>
          {cell.profiling.cpu_ms}ms cpu
        </span>
      </div>
    {/if}
  </div>

  <!-- Cell Outputs -->
  <div class="cell-outputs">
    {#each cell.records as record}
      <div class="output-item">
        {#if record.type === 'md'}
          <div class="markdown-output">
            {@html marked.parse(record.payload)}
          </div>
        {:else if record.type === 'html'}
          <div class="html-output">
            {@html record.payload}
          </div>
        {:else if record.type === 'plotly'}
          <div class="plotly-output" use:plotlyAction={record.payload}></div>
        {:else if record.type === 'altair'}
          <div class="altair-output" use:altairAction={record.payload}></div>
        {:else if record.type === 'object'}
          <div class="object-output">
            <JSONTree val={record.payload} />
          </div>
        {:else if record.type === 'text'}
          <pre class="text-output">{record.payload}</pre>
        {/if}
      </div>
    {:else}
      {#if cell.status === 'pending'}
        <div class="placeholder-msg">Waiting for execution...</div>
      {:else if cell.status === 'running' && cell.records.length === 0}
        <div class="placeholder-msg pulsing">Running cell...</div>
      {/if}
    {/each}
  </div>
</div>

<style>
  .cell-container {
    background: rgba(30, 41, 59, 0.4);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    margin-bottom: 20px;
    overflow: hidden;
    transition: border-color 0.3s ease, box-shadow 0.3s ease, opacity 0.3s ease;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
  }

  .cell-container:hover {
    border-color: rgba(255, 255, 255, 0.12);
  }

  /* Status specific styles */
  .cell-container.running {
    border-color: rgba(99, 102, 241, 0.6);
    box-shadow: 0 0 15px rgba(99, 102, 241, 0.2);
  }
  
  .cell-container.error {
    border-color: rgba(239, 68, 68, 0.5);
    box-shadow: 0 0 15px rgba(239, 68, 68, 0.15);
  }

  .cell-container.stale {
    opacity: 0.6;
    background: rgba(15, 23, 42, 0.2);
    border-style: dashed;
  }

  .cell-container.absent {
    opacity: 0.3;
    filter: grayscale(80%);
  }

  /* Header & Stats */
  .cell-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 16px;
    background: rgba(15, 23, 42, 0.3);
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }

  .left-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .status-indicator {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: #64748b;
    transition: background-color 0.3s ease, box-shadow 0.3s ease;
  }

  .cell-container.pending .status-indicator {
    background-color: #475569;
  }

  .cell-container.running .status-indicator {
    background-color: #6366f1;
    box-shadow: 0 0 8px #6366f1;
    animation: pulse 1.5s infinite alternate;
  }

  .cell-container.done .status-indicator {
    background-color: #10b981;
    box-shadow: 0 0 6px rgba(16, 185, 129, 0.4);
  }

  .cell-container.error .status-indicator {
    background-color: #ef4444;
    box-shadow: 0 0 8px #ef4444;
  }

  .cell-name {
    font-size: 0.85rem;
    font-weight: 600;
    color: #94a3b8;
  }

  .cell-label {
    background: rgba(99, 102, 241, 0.15);
    color: #a5b4fc;
    border: 1px solid rgba(99, 102, 241, 0.2);
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 500;
  }

  .stale-badge {
    background: rgba(245, 158, 11, 0.15);
    color: #fcd34d;
    border: 1px solid rgba(245, 158, 11, 0.2);
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 500;
  }

  .profiling-stats {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.75rem;
    color: #64748b;
  }

  .stat-item {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .icon {
    width: 12px;
    height: 12px;
    opacity: 0.7;
  }

  .stat-divider {
    color: #334155;
  }

  /* Outputs Area */
  .cell-outputs {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .output-item {
    width: 100%;
  }

  .placeholder-msg {
    font-size: 0.85rem;
    color: #475569;
    font-style: italic;
  }

  .placeholder-msg.pulsing {
    color: #818cf8;
    animation: textPulse 1.5s infinite alternate;
  }

  /* Plain text rendering */
  .text-output {
    margin: 0;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.875rem;
    color: #cbd5e1;
    background: rgba(15, 23, 42, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    padding: 12px;
    white-space: pre-wrap;
    word-break: break-all;
    overflow-x: auto;
  }

  /* Markdown custom overrides */
  .markdown-output {
    font-size: 0.95rem;
    line-height: 1.6;
    color: #cbd5e1;
  }

  .markdown-output :global(p) {
    margin-top: 0;
    margin-bottom: 12px;
  }

  .markdown-output :global(p:last-child) {
    margin-bottom: 0;
  }

  .markdown-output :global(pre) {
    background: rgba(15, 23, 42, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    padding: 12px;
    overflow-x: auto;
  }

  .markdown-output :global(code) {
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.85em;
    background: rgba(0, 0, 0, 0.2);
    padding: 2px 4px;
    border-radius: 4px;
    color: #f472b6;
  }

  .markdown-output :global(h1),
  .markdown-output :global(h2),
  .markdown-output :global(h3) {
    color: #f1f5f9;
    margin-top: 16px;
    margin-bottom: 8px;
  }

  /* HTML tables and plots */
  .html-output :global(table) {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.85rem;
    margin: 8px 0;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    overflow: hidden;
  }

  .html-output :global(th) {
    background: rgba(15, 23, 42, 0.6);
    color: #f1f5f9;
    font-weight: 600;
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  }

  .html-output :global(td) {
    padding: 8px 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    color: #cbd5e1;
  }

  .html-output :global(tr:hover) {
    background: rgba(255, 255, 255, 0.02);
  }

  .plotly-output, .altair-output {
    background: rgba(255, 255, 255, 0.01);
    border: 1px solid rgba(255, 255, 255, 0.04);
    border-radius: 8px;
    padding: 12px;
    min-height: 100px;
    overflow: hidden;
  }

  .object-output {
    background: rgba(15, 23, 42, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.04);
    border-radius: 8px;
    padding: 12px;
    overflow-x: auto;
  }

  .error-msg {
    color: #f87171;
    font-size: 0.85rem;
    font-weight: 500;
  }

  @keyframes pulse {
    0% {
      opacity: 0.6;
    }
    100% {
      opacity: 1;
    }
  }

  @keyframes textPulse {
    0% {
      opacity: 0.5;
    }
    100% {
      opacity: 0.9;
    }
  }
</style>
