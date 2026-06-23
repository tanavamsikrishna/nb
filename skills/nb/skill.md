---
name: nb
description: >-
  Use when writing or editing notebooks for the `nb` framework in this project.
  Covers cell structure, all display types, @nb_cache caching decorator, and the
  CLI workflow for running notebooks.
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

## Running a Notebook

```bash
# Terminal 1 — start the daemon once per project session
uv run nb daemon .

# Terminal 2 — trigger execution
uv run nb run <notebook.py>
```

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
