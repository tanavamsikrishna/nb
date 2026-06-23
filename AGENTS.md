# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`nb` is a lightweight Python notebook runner. Notebooks are plain `.py` files with `# %%`
cell delimiters. A persistent daemon executes them cell-by-cell and streams output over SSE
to a Svelte UI at `http://localhost:7777`. The browser is a display surface only — no commands
flow from browser back to the daemon.

The repo has two sub-projects:
- `nb/` — Python daemon, CLI, and execution framework. Managed by `uv` (see `pyproject.toml`).
- `nb-ui/` — Svelte 5 + Vite frontend. Managed by `pnpm`.

## Commands

```bash
# Setup (installs all optional + dev deps via uv)
make install              # == uv sync --extra all --extra dev

# Run the notebook system (two terminals)
uv run nb daemon .          # start the daemon once per project session (serves :7777)
uv run nb run example.py    # send a run request to the daemon over the .nb.sock unix socket
uv run nb run -w example.py # --watch: re-run automatically on every file save (Ctrl-C to stop)

# Query a notebook's saved daemon state without a browser (for agents)
uv run nb query cells example.py            # list cells: id, title, line span, status, record count
uv run nb query records example.py 1        # display records of a cell (tables spill to a Parquet file)
uv run nb query exec example.py -c "CODE"   # run Python against the notebook's live namespace

# Python tests (pytest + pytest-asyncio)
uv run pytest                                   # all tests
uv run pytest nb/tests/test_framework.py        # one file
uv run pytest nb/tests/test_cache.py::test_name # one test

# Frontend
cd nb-ui && pnpm dev          # vite dev server; proxies /stream -> :7777 (daemon must run)
cd nb-ui && pnpm build        # production build -> nb-ui/dist
cd nb-ui && pnpm format       # prettier
make build                    # pnpm build + copy dist -> nb/static/
```

`nb/static/` and `nb-ui/dist/` are gitignored build artifacts. The daemon serves the prebuilt
UI from `nb/static/`; if it's missing, `make build` must be run first.

## Architecture

**Execution flow.** `nb/cli.py` (`nb run`) connects to the per-project unix socket `.nb.sock`
and sends `{"path": ...}`. `nb/daemon.py` handles it under a `run_lock`, sets a global
`_active_emitter`, and runs `nb/runner.py:run_notebook` in a thread executor (so `exec` never
blocks the asyncio loop). `runner.py` parses cells, compiles and `exec`s each one, and emits
SSE events (`notebook_header`, `run_start`, `cell_start`, `display_record`, `cell_end`,
`run_end`) which `daemon.emit_event` fans out to all connected `/stream` clients.

**Two namespaces.** The daemon process holds a long-lived *import* namespace (so the
`nb.framework` module — and its `_cache` — persists across runs). Each run gets a *fresh
exec namespace*, discarded afterward. The cache deliberately lives in `nb.framework._cache`,
not the exec namespace, so it survives between runs.

**Display.** The single entry point is `display(obj, *, as_=None, label=None)` in
`nb/framework.py`. `as_` is one of `md | html | text | object | table`, or
omitted to auto-detect (Plotly figure → `plotly`, Altair chart → `altair`, polars DataFrame →
`table`, `str` → `text`, else → `object`). Display primitives tag records with the current
cell via the module globals `_current_cell_id` / `_active_emitter`. Tables are serialized as
base64 Parquet and rendered client-side with DuckDB-WASM (`nb-ui/src/lib/duckdb.ts`).

**Caching.** `@nb_cache` (in `nb/framework.py`) wraps a function with input-hash-based
caching keyed by `blake2b(source + inputs + optional keys=[...] globals)`. A purity linter
(`_check_purity`) runs at decoration time and raises `SyntaxError` if the function has any
`STORE_GLOBAL`/`DELETE_GLOBAL`. Inside an `@nb_cache` function, `display(...)` calls are
captured into the cache entry and replayed to the SSE stream on a cache hit. Argument hashing
is a strict allowlist (`_hash_value`): polars DataFrame, numpy ndarray, pydantic model,
primitives, and `__main__`-defined functions — anything else raises `TypeError`.

**Frontend.** Svelte 5 + Vite. `nb-ui/src/lib/stream.ts` opens `EventSource('/stream')` and
maps SSE events into the `cells` store (`nb-ui/src/stores/cells.ts`). Cells are keyed by
positional id for stable DOM; `run_start` reconciles the manifest (marking edited cells stale,
removing absent ones after `run_end`) so scroll position is preserved across runs.

## Notebook authoring

When writing or editing `.py` notebooks, the canonical, up-to-date API reference is
`skills/nb/guide.py` (annotated) and `skills/nb/skill.md`. `example.py` is a working sample.
