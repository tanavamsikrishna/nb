<script>
  import JSONTree from './JSONTree.svelte';

  let { val, label = '', depth = 0, isLast = true } = $props();

  /* svelte-ignore state_referenced_locally */
  let expanded = $state(depth < 2);

  function toggle(e) {
    e.stopPropagation();
    expanded = !expanded;
  }

  let type = $derived(val === null ? 'null' : Array.isArray(val) ? 'array' : typeof val);
  let isObjectOrArray = $derived(type === 'object' || type === 'array');
  let keys = $derived(type === 'object' ? Object.keys(val) : []);
</script>

<div class="json-node" style="margin-left: {depth * 14}px">
  {#if isObjectOrArray}
    <button class="toggle-btn" onclick={toggle} aria-label="Toggle node">
      <span class="toggle-icon {expanded ? 'open' : ''}">▶</span>
    </button>
  {/if}

  {#if label}
    <span class="key">"{label}"</span><span class="colon">: </span>
  {/if}

  {#if type === 'object'}
    <span class="brace">{"{"}</span>
    {#if expanded}
      <div class="nested">
        {#each keys as key, idx (key)}
          <JSONTree val={val[key]} label={key} depth={0} isLast={idx === keys.length - 1} />
        {/each}
      </div>
      <span class="brace">{"}"}{isLast ? '' : ','}</span>
    {:else}
      <button class="collapsed-preview" onclick={toggle}>...</button>
      <span class="brace">{"}"}{isLast ? '' : ','}</span>
    {/if}
  {:else if type === 'array'}
    <span class="brace">{"["}</span>
    {#if expanded}
      <div class="nested">
        {#each val as item, idx (idx)}
          <JSONTree val={item} depth={0} isLast={idx === val.length - 1} />
        {/each}
      </div>
      <span class="brace">{"]"}{isLast ? '' : ','}</span>
    {:else}
      <button class="collapsed-preview" onclick={toggle}>...</button>
      <span class="brace">{"]"}{isLast ? '' : ','}</span>
    {/if}
  {:else if type === 'string'}
    <span class="string">"{val}"</span>{isLast ? '' : ','}
  {:else if type === 'number'}
    <span class="number">{val}</span>{isLast ? '' : ','}
  {:else if type === 'boolean'}
    <span class="boolean">{val}</span>{isLast ? '' : ','}
  {:else if type === 'null'}
    <span class="null">null</span>{isLast ? '' : ','}
  {:else}
    <span class="other">{val}</span>{isLast ? '' : ','}
  {/if}
</div>

<style>
  .json-node {
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.875rem;
    line-height: 1.6;
    color: #e2e8f0;
    text-align: left;
    display: block;
  }

  .toggle-btn {
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    color: #64748b;
    vertical-align: middle;
  }

  .toggle-btn:hover {
    color: #cbd5e1;
  }

  .toggle-icon {
    font-size: 0.65rem;
    transition: transform 0.15s ease;
    transform: rotate(0deg);
  }

  .toggle-icon.open {
    transform: rotate(90deg);
  }

  .key {
    color: #f43f5e;
  }

  .colon {
    color: #94a3b8;
  }

  .brace {
    color: #cbd5e1;
  }

  .string {
    color: #34d399;
    word-break: break-all;
  }

  .number {
    color: #fbbf24;
  }

  .boolean {
    color: #60a5fa;
  }

  .null {
    color: #94a3b8;
    font-weight: 600;
  }

  .other {
    color: #c084fc;
  }

  .collapsed-preview {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    padding: 0px 6px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.75rem;
    color: #94a3b8;
    font-family: inherit;
    line-height: 1.2;
    vertical-align: middle;
    margin: 0 4px;
  }

  .collapsed-preview:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #cbd5e1;
  }

  .nested {
    border-left: 1px dashed rgba(255, 255, 255, 0.08);
    padding-left: 14px;
    margin-left: 6px;
  }
</style>
