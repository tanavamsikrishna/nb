<script>
  import { marked } from 'marked';
  
  // Svelte 5 props
  let { docstring = '' } = $props();
  
  // Svelte 5 derived state
  let html = $derived(docstring ? marked.parse(docstring) : '');
</script>

<div class="notebook-header">
  {@html html}
</div>

<style>
  .notebook-header {
    background: rgba(30, 41, 59, 0.7);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 28px;
    margin-bottom: 32px;
    color: #cbd5e1;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
  }

  .notebook-header :global(h1) {
    font-size: 2.25rem;
    font-weight: 800;
    margin-top: 0;
    margin-bottom: 18px;
    background: linear-gradient(135deg, #818cf8 0%, #c084fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.025em;
  }

  .notebook-header :global(h2) {
    font-size: 1.5rem;
    font-weight: 600;
    color: #f1f5f9;
    margin-top: 24px;
    margin-bottom: 12px;
  }

  .notebook-header :global(p) {
    font-size: 1.05rem;
    line-height: 1.7;
    margin-bottom: 16px;
  }

  .notebook-header :global(code) {
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    background: rgba(15, 23, 42, 0.6);
    padding: 3px 6px;
    border-radius: 6px;
    font-size: 0.9em;
    color: #a78bfa;
    border: 1px solid rgba(255, 255, 255, 0.05);
  }
</style>
