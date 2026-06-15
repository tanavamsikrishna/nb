<!--
  JSONTree.svelte — Recursive JSON object/array tree viewer.

  Renders expandable/collapsible nodes for objects, arrays, and primitive
  values. Auto-expands the first two depth levels.

  Props:
    val    any     — value to render
    label  string  — key name (omitted for array items)
    depth  number  — nesting depth (controls auto-expand)
    isLast boolean — whether this is the last sibling (controls trailing comma)

  Dependencies: None (self-referential recursive component).
  Exports: None (render-only component).
  Side-effects: None.
  Constraints: Svelte 5 runes ($props, $state, $derived).
-->
<script lang="ts">
  import JSONTree from "./JSONTree.svelte";

  let { val, label = "", depth = 0, isLast = true } = $props();

  /* svelte-ignore state_referenced_locally */
  let expanded = $state(depth < 2);

  function toggle(e) {
    e.stopPropagation();
    expanded = !expanded;
  }

  let type = $derived(
    val === null ? "null" : Array.isArray(val) ? "array" : typeof val,
  );
  let isObjectOrArray = $derived(type === "object" || type === "array");
  let keys = $derived(type === "object" ? Object.keys(val) : []);
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

  {#if type === "object"}
    <span class="brace">{"{"}</span>
    {#if expanded}
      <div class="nested">
        {#each keys as key, idx (key)}
          <JSONTree
            val={val[key]}
            label={key}
            depth={0}
            isLast={idx === keys.length - 1}
          />
        {/each}
      </div>
      <span class="brace">{"}"}{isLast ? "" : ","}</span>
    {:else}
      <button class="collapsed-preview" onclick={toggle}>...</button>
      <span class="brace">{"}"}{isLast ? "" : ","}</span>
    {/if}
  {:else if type === "array"}
    <span class="brace">{"["}</span>
    {#if expanded}
      <div class="nested">
        {#each val as item, idx (idx)}
          <JSONTree val={item} depth={0} isLast={idx === val.length - 1} />
        {/each}
      </div>
      <span class="brace">{"]"}{isLast ? "" : ","}</span>
    {:else}
      <button class="collapsed-preview" onclick={toggle}>...</button>
      <span class="brace">{"]"}{isLast ? "" : ","}</span>
    {/if}
  {:else if type === "string"}
    <span class="string">"{val}"</span>{isLast ? "" : ","}
  {:else if type === "number"}
    <span class="number">{val}</span>{isLast ? "" : ","}
  {:else if type === "boolean"}
    <span class="boolean">{val}</span>{isLast ? "" : ","}
  {:else if type === "null"}
    <span class="null">null</span>{isLast ? "" : ","}
  {:else}
    <span class="other">{val}</span>{isLast ? "" : ","}
  {/if}
</div>

<style>
  .json-node {
    font-family: var(--font-mono);
    font-size: 0.875rem;
    line-height: 1.6;
    color: var(--fg-primary);
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
    color: var(--fg-secondary);
    vertical-align: middle;
  }

  .toggle-btn:hover {
    color: var(--fg-primary);
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
    color: var(--color-error);
  }

  .colon {
    color: var(--fg-secondary);
  }

  .brace {
    color: var(--fg-primary);
  }

  .string {
    color: var(--color-success);
    word-break: break-all;
  }

  .number {
    color: var(--color-warning);
  }

  .boolean {
    color: var(--color-info);
  }

  .null {
    color: var(--fg-secondary);
    font-weight: 600;
  }

  .other {
    color: var(--color-link-visited);
  }

  .collapsed-preview {
    background: var(--bg-muted);
    border: 1px solid var(--border-subtle);
    padding: 0px 6px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-size: 0.75rem;
    color: var(--fg-secondary);
    font-family: inherit;
    line-height: 1.2;
    vertical-align: middle;
    margin: 0 4px;
  }

  .collapsed-preview:hover {
    background: var(--bg-sunken);
    color: var(--fg-primary);
  }

  .nested {
    border-left: 1px dashed var(--border-subtle);
    padding-left: 14px;
    margin-left: 6px;
  }
</style>
