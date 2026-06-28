<script lang="ts">
  import type { Snippet } from "svelte";
  let {
    breadcrumb,
    aside,
    bar,
    children,
  }: {
    breadcrumb: Snippet;
    aside?: Snippet;
    bar?: Snippet;
    children: Snippet;
  } = $props();
</script>

<div class="app-wrapper">
  <header class="app-header">
    <div class="header-content">
      <div class="logo-area">{@render breadcrumb()}</div>
      {@render aside?.()}
    </div>
    {@render bar?.()}
  </header>
  <main class="main-container">{@render children()}</main>
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

  .main-container {
    max-width: 960px;
    width: 100%;
    margin: 0 auto;
    padding: 40px 24px;
    flex-grow: 1;
    box-sizing: border-box;
  }
</style>
