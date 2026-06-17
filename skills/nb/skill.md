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

## Cache Management

Caches are invalidated from the command line, not from notebook code.

```bash
uv run nb run mynotebook.py --clear-cache get_data          # clear one function
uv run nb run mynotebook.py --clear-cache get_data,build    # clear several (comma-separated)
uv run nb run mynotebook.py --clear-cache                   # clear everything (prompts to confirm)
```

Names match either a function's short name or its qualname. A short name clears **all** entries
with that name — so if two functions in different scopes share a short name (e.g. two nested
functions both called `inner`, or a nested and a top-level function both called `process`),
both are cleared. Use the full qualname to target only one:

```bash
uv run nb run mynotebook.py --clear-cache "outer1.<locals>.inner"   # only this one
```

A name that matches nothing is a harmless no-op.
