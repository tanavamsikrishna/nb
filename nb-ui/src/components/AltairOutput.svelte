<!--
  AltairOutput.svelte — renders a single Altair/Vega-Lite chart record.

  Props:
    payload  unknown  — a Vega/Vega-Lite spec

  Dependencies: lib/lazy_load (loadVega — deferred heavy lib)
  Side-effects: lazy-loads vega-embed on first use; finalizes the view on destroy.

  Lifecycle note: outputs are updated in place across runs (records are
  overwritten, not remounted), so this component re-renders on `payload` change
  rather than only on mount.
-->
<script lang="ts">
  import { onDestroy } from "svelte";
  import { loadVega } from "../lib/lazy_load";

  let { payload }: { payload: unknown } = $props();

  let node: HTMLDivElement;
  let active = true;
  let view: any = null;

  // Detach from the $state proxy before Vega mutates the spec — see the note in
  // PlotlyOutput.svelte for why this snapshot is required (and is the single
  // boundary that keeps the notebook store safely reactive).
  $effect(() => {
    const spec = $state.snapshot(payload);
    loadVega()
      .then((vegaEmbed) => {
        if (!active) return;
        if (view) {
          view.finalize?.();
          node.innerHTML = "";
        }
        vegaEmbed(node, spec, { actions: false })
          .then((res) => {
            if (active) view = res;
            else res.finalize?.();
          })
          .catch((err) => {
            node.innerHTML = `<span class="error-msg">Failed to render Altair: ${err.message || err}</span>`;
          });
      })
      .catch((err) => {
        if (active) {
          node.innerHTML = `<span class="error-msg">Failed to render Altair: ${err.message || err}</span>`;
        }
      });
  });

  onDestroy(() => {
    active = false;
    view?.finalize?.();
  });
</script>

<div class="altair-output" bind:this={node}></div>

<style>
  .altair-output {
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 12px;
    min-height: 100px;
    overflow: hidden;
  }

  /* The error span is injected imperatively via innerHTML, so it carries no
     scope hash — target it globally (scoped under the container). */
  .altair-output :global(.error-msg) {
    color: var(--color-error);
    font-size: 0.85rem;
    font-weight: 500;
  }
</style>
