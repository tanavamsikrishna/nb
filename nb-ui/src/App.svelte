<script lang="ts">
  import NotebookList from "./components/NotebookList.svelte";
  import ExperimentsList from "./components/ExperimentsList.svelte";
  import ExperimentView from "./components/ExperimentView.svelte";
  import NotebookStream from "./components/NotebookStream.svelte";

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
</script>

{#if path && view === "experiments"}
  <ExperimentsList {path} />
{:else if path && run}
  <ExperimentView {path} runId={run} />
{:else if path}
  <NotebookStream {path} />
{:else}
  <NotebookList />
{/if}
