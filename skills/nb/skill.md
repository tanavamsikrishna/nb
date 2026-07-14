---
name: nb
description: >-
  Use when writing or editing notebooks for the `nb` framework in this project.
  Covers cell structure, the run/query/cache CLI workflow, and points to guide.py
  for the full display and @nb_cache API.
---

# nb — Python Notebook Framework

`nb` is a lightweight Python notebook runner. Notebooks are plain `.py` files;
the daemon executes them cell-by-cell and streams output to a Svelte UI at
`http://localhost:7777`.

Read `skills/nb/guide.py` for the full annotated API reference.

## Notebook Structure

Cells are delimited by `# %%`. Everything after `# %%` on the same line is the
cell title shown in the UI sidebar. The module-level docstring is rendered as the
notebook description.

```python
"""
Notebook description (Markdown supported).
"""

# %% Cell Title
# code...
```

### Cell granularity

A cell should map to a **top-level section** of the notebook — a coherent unit of
work such as "Data exploration", "Data preparation", "OOS analysis", or whatever
sections are idiosyncratic to the notebook — not to a single output.

Do **not** create a new cell for each individual `display(...)`. A section that
produces several outputs (a summary table, a distribution plot, a couple of
sanity-check values) belongs in **one** cell that emits all of them. Splitting
every output into its own cell fragments the notebook, bloats the sidebar with
dozens of tiny entries, and buries the actual structure of the analysis.

```python
# %% Data exploration
# One section, several related outputs — all in this cell.
df = load_data()
display(df.describe(), label="Summary stats")
display(px.histogram(df, x="value"))
display(f"{df['id'].n_unique()} unique ids", as_="md")

# %% Data preparation
# The next distinct section starts a new cell.
clean = df.drop_nulls().filter(pl.col("value") > 0)
display(clean.head(), label="Cleaned")
```

## Running a Notebook

```bash
# Terminal 1 — start the daemon once per project session
uv run nb daemon .

# Terminal 2 — trigger execution
uv run nb run <notebook.py>
```

All `run`/`query` commands need the daemon; for pure authoring you only need
`skills/nb/guide.py` and the cell-structure rules above.

## Querying State (for agents)

`nb query` reads the daemon's saved state for a notebook that has already run — a
headless alternative to opening the browser. All three operations require the
daemon to be running and the notebook to have run at least once.

```bash
uv run nb query cells <notebook.py>            # list cells: id, title, line span, status, record count
uv run nb query records <notebook.py> <CELL>   # display records of a cell (by numeric id)
uv run nb query exec <notebook.py> -c "CODE"   # run Python against the notebook's live namespace
```

- `records` prints text/markdown/html inline. **Tables** show their column→dtype schema
  and a CSV preview of the first rows; when the table has more rows than the preview, the
  full data is also written to a CSV file and its path is printed. **Plots** (Plotly/Altair)
  are written to a JSON file and only the path is printed.
- `exec` runs against the **live, persistent namespace** the last run left behind, so
  it sees every notebook variable and *can mutate them* (changes persist into later
  runs — same as a Jupyter kernel). It prints captured stdout/stderr, renders any
  `display(...)` calls the same way `records` does, and exits non-zero on an uncaught
  exception. Code may also be piped via stdin (omit `-c`).

If a query errors with no daemon reply, start the daemon (`uv run nb daemon .`)
and run the notebook once (`uv run nb run <notebook.py>`) before querying.

## Experiment Tracking

Every `nb run` is persisted as an experiment under `.nb/experiments/` at the
project root (survives daemon restarts). Each run saves its source code, the
display records it produced, its hyperparameters, and any output files it logged.
Parameters are auto-detected: any top-level global whose name is SCREAMING_SNAKE_CASE
is collected and shown at the top of the notebook (strings verbatim, everything else
`repr`'d):

```python
LEARNING_RATE = 0.01   # auto-detected params: shown in the UI *and* logged
EPOCHS = 10
MODEL = "resnet"
```

**Artifacts** are output files (a model checkpoint, a saved plot, a CSV) recorded
against the run. `artifact_path(filename)` creates a fresh empty file with that
name inside the run's own directory and returns its full path;
`log_artifact(path, name=None)` records it (name defaults to the file's basename):

```python
p = artifact_path("model.pt")  # -> .nb/experiments/<slug>/<run_id>/artifacts/model.pt
torch.save(model, p)
log_artifact(p)                # records {name: "model.pt", path: p} against the run
```

Unlike params, artifacts are an ordered *list* — logging the same name twice
(e.g. a `checkpoint` per epoch) keeps every entry. Both functions are injected
into the notebook namespace (no import needed).

A full-notebook run is a *parent* experiment; a partial re-run
(`nb run file.py:LINE`) is saved as a *child* of the most recent full run. Browse
history from the index page's per-notebook **Experiments** link (parents
newest-first, children nested); click a run to view its saved code, params, and
outputs. See `skills/nb/guide.py` for the parameters and artifacts examples.

## Cache Management

Caches are invalidated from the command line, not from notebook code.

```bash
uv run nb run mynotebook.py --clear-cache get_data          # clear one function
uv run nb run mynotebook.py --clear-cache get_data,build    # clear several (comma-separated)
uv run nb run mynotebook.py --clear-cache-all              # clear everything
```

Names match either a function's short name or its qualname. A short name clears **all** entries
with that name — so if two functions in different scopes share a short name (e.g. two nested
functions both called `inner`, or a nested and a top-level function both called `process`),
both are cleared. Use the full qualname to target only one:

```bash
uv run nb run mynotebook.py --clear-cache "outer1.<locals>.inner"   # only this one
```

After the run, the CLI reports how many functions were cleared and warns about any
name that matched nothing (a likely typo) — a name that matches nothing is otherwise
a harmless no-op.
