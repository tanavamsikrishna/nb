<!--
  PlotlyOutput.svelte — renders a single Plotly figure record.

  Props:
    payload  PlotlyPayload  — { data, layout?, config? } (a Plotly figure spec)

  Dependencies: lib/lazy_load (loadPlotly — deferred heavy lib)
  Side-effects: lazy-loads Plotly on first use; purges the figure on destroy.

  Lifecycle note: outputs are updated in place across runs (records are
  overwritten, not remounted), so this component re-renders on `payload` change
  rather than only on mount. `Plotly.react` diffs against the current figure and
  updates in place (no flash).
-->
<script lang="ts">
  import { onDestroy } from "svelte";
  import { loadPlotly } from "../lib/lazy_load";
  import type { PlotlyPayload } from "../lib/types";

  let { payload }: { payload: PlotlyPayload } = $props();

  let node: HTMLDivElement;
  let active = true;

  // $state.snapshot detaches from the $state proxy before Plotly MUTATES the
  // data arrays it's handed — otherwise those writes would loop back into a
  // reactive update and re-run this effect forever. The effect re-runs only on a
  // genuine payload change (a new run swaps in a fresh record); Plotly's own
  // mutations touch the detached snapshot, never the proxy. (On the experiments
  // view the payload is already plain — snapshot is then a harmless clone.)
  // This is the single boundary that lets the notebook store stay reactive.
  $effect(() => {
    const p = $state.snapshot(payload) as PlotlyPayload;
    loadPlotly()
      .then((Plotly) => {
        if (!active) return;
        // Default to a usable height; without one Plotly falls back to the
        // container's height and collapses. The figure's own layout.height
        // still wins if it sets one.
        const layout = { autosize: true, height: 450, ...p.layout };
        const config = { responsive: true, ...(p.config || {}) };
        Plotly.react(node, p.data, layout, config);
      })
      .catch((err) => {
        if (active) {
          node.innerHTML = `<span class="error-msg">Failed to render Plotly: ${err.message || err}</span>`;
        }
      });
  });

  onDestroy(() => {
    active = false;
    loadPlotly()
      .then((Plotly) => Plotly.purge(node))
      .catch(() => {});
  });
</script>

<div class="plotly-output" bind:this={node}></div>

<style>
  .plotly-output {
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 12px;
    min-height: 100px;
    overflow: hidden;
  }

  /* The error span is injected imperatively via innerHTML, so it carries no
     scope hash — target it globally (scoped under the container). */
  .plotly-output :global(.error-msg) {
    color: var(--color-error);
    font-size: 0.85rem;
    font-weight: 500;
  }
</style>
