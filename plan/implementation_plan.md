# `nb` — Python Notebook Infrastructure: Implementation Plan

This document describes the full implementation of the `nb` framework as specified in [nb-spec.md](file:///Users/vamsi/repo/nb/nb-spec.md). The project is a lightweight Python notebook runner: `.py` files with `# %%` cell delimiters are executed by a persistent daemon, which streams output to a Svelte frontend via SSE.

---

## Design Decisions (Resolved)

| Question | Decision |
|---|---|
| Unix socket path | Per-project — `.nb.sock` in the notebook's project directory |
| Display API | Single `display(obj)` with wrapper types + class auto-detection (see §Display API below) |
| `Object` serialization | stdlib `json` for primitives/dicts/lists + Pydantic models via `model_dump()` |

> [!NOTE]
> **JS library conditional inclusion**: Plotly and Vega-Lite `<script>` tags are injected lazily by the frontend on first encounter of a matching record type, since `cell_manifest` only carries content hashes, not display types.

---

## Proposed Changes

### Component 0 — Display API Design

This is a cross-cutting design decision that affects `framework.py`, the frontend renderer, and `@nb_cache` interceptors.

**Single entry point**: `display(obj)` — the only function a notebook author needs.

**Wrapper types** — used when the type cannot be auto-detected:

| Wrapper | Usage | Rendered as |
|---|---|---|
| `MD("...")` | `display(MD("# heading"))` | Markdown |
| `HTML("...")` | `display(HTML("<b>hi</b>"))` | Raw HTML |
| `Object(obj)` | `display(Object(my_dict))` | Collapsible JSON tree |

**Auto-detected types** — detected by `isinstance` check in priority order:

| Type | Detection | Rendered as |
|---|---|---|
| `plotly.graph_objs.Figure` | `isinstance(obj, plotly.graph_objs.BaseFigure)` | Interactive Plotly |
| `altair.Chart` (any Altair top-level) | `isinstance(obj, altair.TopLevelMixin)` | Vega-Lite chart |
| `polars.DataFrame` | `isinstance(obj, polars.DataFrame)` | HTML table |
| `MD` instance | wrapper type check | Markdown |
| `HTML` instance | wrapper type check | Raw HTML |
| `Object` instance | wrapper type check | JSON tree |
| Fallback | anything else | `repr(obj)` as plain text |

**`@nb_cache` interceptor**: The decorator replaces `display` in the copied globals with a capturing version — only the single `display` symbol needs to be intercepted. `MD`, `HTML`, `Object` are pure data wrappers with no side effects.

---

### Component 1 — Project Scaffold & Config

#### [MODIFY] [pyproject.toml](file:///Users/vamsi/repo/nb/pyproject.toml)

- Add runtime dependencies: `aiohttp` (async HTTP + SSE daemon), `click` (CLI), stdlib `hashlib` for `blake2b`.
- Add `[project.scripts]` entry: `nb = "nb.cli:main"`.
- Add optional extras for `polars`, `numpy`, `pydantic`, `plotly`, `altair`.

#### [NEW] [Makefile](file:///Users/vamsi/repo/nb/Makefile)

- `build-ui` target: `cd nb-ui && pnpm build`
- `build` target: `build-ui` + `cp -r nb-ui/dist/* nb/static/` + `pip install .`

#### [MODIFY] [.gitignore](file:///Users/vamsi/repo/nb/.gitignore)

- Add `nb/static/` and `nb-ui/dist/`.

---

### Component 2 — Python Package Skeleton

#### [DELETE] [main.py](file:///Users/vamsi/repo/nb/main.py)

Replaced by the proper package entry point via `pyproject.toml`.

#### [NEW] `nb/__init__.py`

Re-exports the public API: `nb_cache`, `clear_cache`, all display primitives, `_cache`.

#### [NEW] `nb/framework.py`

Core logic. See §2 and §7 of spec. Contains:

1. **Wrapper types** (pure data, no side effects):
   - `MD(text: str)` — Markdown string wrapper.
   - `HTML(text: str)` — Raw HTML string wrapper.
   - `Object(obj)` — JSON-serializable object wrapper. Serializes via stdlib `json`; if `obj` is a Pydantic model, calls `obj.model_dump()` first.

2. **`DisplayRecord`** dataclass — `type: str`, `payload: Any`.

3. **`CacheEntry`** dataclass — `result: Any`, `display_records: list[DisplayRecord]`.

4. **`_cache: dict[str, CacheEntry]`** — module-level, lives in `sys.modules['nb']._cache`.

5. **`display(obj)`** — single display entry point. Auto-detects type in priority order:
   - `plotly.graph_objs.BaseFigure` → serialize with `fig.to_json()` → `DisplayRecord(type='plotly', payload=...)`
   - `altair.TopLevelMixin` → `chart.to_dict()` → `DisplayRecord(type='altair', payload=...)`
   - `polars.DataFrame` → `df.to_html()` → `DisplayRecord(type='html', payload=...)`
   - `MD` instance → `DisplayRecord(type='md', payload=obj.text)`
   - `HTML` instance → `DisplayRecord(type='html', payload=obj.text)`
   - `Object` instance → serialize to JSON dict → `DisplayRecord(type='object', payload=...)`
   - Fallback → `DisplayRecord(type='text', payload=repr(obj))`
   
   Each branch emits the resulting `DisplayRecord` to the active SSE queue via `_emit()`.

   > Plotly and Altair imports are guarded with `try/except ImportError` so the framework loads without them installed.

6. **Type-dispatch hasher** (`_hash_value`) — for `@nb_cache` key computation. Raises `TypeError` for unsupported types.
   - `polars.DataFrame` → `hash_rows()` bytes + schema bytes
   - `numpy.ndarray` → `.tobytes()` + dtype + shape
   - Pydantic models → `model_dump_json()` bytes
   - Primitives (`int`, `str`, `float`, `bool`, `bytes`) → `pickle.dumps()`
   - Notebook functions (`__module__ == '__main__'`) → `inspect.getsource()` bytes

7. **`_check_purity(code, func_name)`** — bytecode walker raising `SyntaxError` on `STORE_GLOBAL`/`DELETE_GLOBAL`.

8. **`nb_cache` decorator** — full implementation per spec §2.1:
   - Bare `@nb_cache` and `@nb_cache(keys=[...])` both supported.
   - Per-instance `_capture_stack`.
   - Only `display` needs to be intercepted in copied globals (wrapper types are pure data).
   - Cache key = `blake2b(source_hash + input_hash [+ globals_hash])`.
   - On hit: replays `display_records` to the live SSE emitter, returns cached result.
   - `keys=` validation: `KeyError` on missing name, `TypeError` on unhashable type.

9. **`clear_cache(func=None)`** — clears all or per-function cache entries.

10. **`_emit(record: DisplayRecord)`** — forwards to active SSE queue (set by daemon at run time via a module-level `_active_emitter` callback).

---

### Component 3 — Notebook Parser & Executor

#### [NEW] `nb/runner.py`

Responsible for parsing and executing a `.py` notebook file. Called by the daemon on each `nb run`.

1. **`parse_notebook(source: str) -> list[Cell]`**
   - Splits on `# %%` boundaries.
   - Each `Cell` has: `id` (positional index), `label` (text after `# %%`, if any), `source_line` (1-based), `code` (string), `content_hash` (blake2b of code bytes).
   - Extracts module-level docstring via `ast.get_docstring(ast.parse(source))`.

2. **`run_notebook(path: Path, exec_ns: dict, emit_event: Callable)`**
   - Emits `notebook_header` (docstring or omit).
   - Builds `cell_manifest` → emits `run_start`.
   - For each cell:
     - Emits `cell_start`.
     - Records `time.perf_counter()` + `time.process_time()` before.
     - `exec(compile(cell.code, path, 'exec'), exec_ns)` with per-statement timing (wrap top-level statements via AST transformation).
     - Emits `cell_end` with `wall_ms`, `cpu_ms`, `status`.
   - Emits `run_end`.

3. **Per-statement timing** — AST transform wraps each top-level `stmt` in a try/finally with timing. Wall time and CPU time are accumulated per cell.

---

### Component 4 — Daemon

#### [NEW] `nb/daemon.py`

Persistent background process. Runs once and handles all subsequent `nb run` requests.

**Two interfaces:**

| Interface | Details |
|---|---|
| Unix socket | `.nb.sock` in the **project directory** (resolved relative to the notebook file being run). Listens for `nb run <path>` IPC messages. |
| HTTP `:7777` | `GET /` → serves `nb/static/index.html`; `GET /stream` → SSE endpoint. |

**Socket path convention**: `Path(notebook_path).parent / ".nb.sock"`. The CLI and daemon both resolve the socket path this way, enabling per-project daemon isolation.

**Implementation outline (using `aiohttp`):**

1. **`start_daemon(project_dir: Path)`** — entry point, runs `asyncio.run(main())`. Creates `.nb.sock` in `project_dir`.
2. **SSE handler** — maintains an `asyncio.Queue` of SSE events. On `GET /stream`, streams events as they arrive. Multiple browser clients broadcast from the same queue.
3. **Unix socket handler** — `asyncio` Unix socket server. On receiving a run request, calls `run_notebook(...)` in a thread executor (so `exec` does not block the event loop), forwarding each SSE event to the queue.
4. **Execution namespace** — `exec_ns` is a fresh `dict` per run. The import namespace (`sys.modules`) is the persistent daemon namespace.
5. **Static file serving** — `aiohttp.web.static` reading from `nb/static/`.
6. **Lock** — only one notebook run at a time. Concurrent `nb run` calls are serialized.

---

### Component 5 — CLI

#### [NEW] `nb/cli.py`

Uses `click`.

```
nb run <notebook.py>     Send run request to daemon via Unix socket.
                         If daemon not running, start it first.
nb build-ui              Run vite build and copy dist → nb/static/.
```

- **`nb run`**: Resolves `.nb.sock` as `Path(notebook).parent / ".nb.sock"`. Connects to socket, sends path, receives ack.
- **Daemon auto-start**: If socket doesn't exist or connection refused, spawn `nb _daemon <project_dir>` as a detached background subprocess, poll until socket appears (max ~3s), then send run request.
- **`nb _daemon`** (internal): Hidden click command that starts the daemon; invoked only by auto-start.
- **`nb build-ui`**: Shells out to `cd nb-ui && pnpm build`, then copies `nb-ui/dist/*` → `nb/static/`.

---

### Component 6 — Frontend (`nb-ui/`)

Svelte + Vite project. Built standalone; served as static files by the daemon in production.

#### [NEW] `nb-ui/package.json`

Dependencies: `svelte`, `vite`, `@sveltejs/vite-plugin-svelte`.

#### [NEW] `nb-ui/vite.config.js`

Proxies `/stream` to `http://localhost:7777` for dev-time hot reload.

#### [NEW] `nb-ui/src/stores/cells.js`

```javascript
export const notebookHeader = writable(null);   // string | null
export const cells = writable([]);
// Cell shape per spec §5.2
```

#### [NEW] `nb-ui/src/lib/stream.js`

SSE `EventSource` listener. Handles all event types:
- `notebook_header` → sets `notebookHeader` store.
- `run_start` → `reconcile(cells, cell_manifest)` per §4.6 logic.
- `cell_start` → sets cell `status = 'running'`.
- `display_record` → appends to `cell.records`.
- `cell_end` → sets `status`, sets `profiling`.
- `run_end` → removes cells absent from last manifest.

**`reconcile` logic** per §4.6:
- Same index + same hash → keep, clear stale marker.
- Same index + different hash → keep container, mark stale, clear records.
- New index → insert new cell object.
- Absent index → mark for removal (removed on `run_end`).

#### [NEW] `nb-ui/src/App.svelte`

```svelte
{#if $notebookHeader}
  <NotebookHeader docstring={$notebookHeader} />
{/if}

{#each $cells as cell (cell.id)}
  <Cell {cell} />
{/each}
```

#### [NEW] `nb-ui/src/components/Cell.svelte`

Renders a single cell:
- Status indicator (`pending` / `running` / `done` / `error`).
- Stats bar: `wall_ms`, `cpu_ms` from `cell.profiling`.
- Ordered list of `DisplayRecord` renders, dispatching on `record.type`:

| `record.type` | Renderer |
|---|---|
| `md` | Markdown via `marked` library |
| `html` | `{@html record.payload}` |
| `plotly` | `Plotly.newPlot(div, ...)` — script injected lazily |
| `altair` | `vegaEmbed(div, spec)` — script injected lazily |
| `object` | `<JSONTree>` collapsible component |
| `text` | `<pre>{record.payload}</pre>` |

#### [NEW] `nb-ui/src/components/NotebookHeader.svelte`

Renders the module docstring as Markdown at the top.

#### [NEW] `nb-ui/index.html`

Conditionally includes Plotly and Vega-Lite CDN `<script>` tags. Since scripts are injected lazily by the frontend on first encounter of the relevant record type, they start absent and are appended to `<head>` dynamically.

---

## Implementation Order

The components have the following dependency graph. Implementation should proceed in this order:

```
1. Project scaffold (pyproject.toml, Makefile, .gitignore)
2. nb/framework.py  (DisplayRecord, CacheEntry, _cache, display primitives, nb_cache)
3. nb/runner.py     (parser + executor, depends on framework)
4. nb/daemon.py     (HTTP + Unix socket server, depends on runner + framework)
5. nb/cli.py        (depends on daemon socket protocol)
6. nb/__init__.py   (re-exports from framework, depends on framework)
7. nb-ui/           (Svelte frontend, depends on SSE schema from daemon)
8. Makefile build   (ties everything together)
```

---

## Verification Plan

### Automated Tests
- `pytest nb/tests/test_cache.py` — unit tests for `nb_cache`:
  - Cache hit/miss behavior.
  - Purity linter (valid function, function with `STORE_GLOBAL`).
  - `keys=` missing name raises `KeyError`.
  - `keys=` unsupported type raises `TypeError`.
  - Type-dispatch hasher for each supported type.
- `pytest nb/tests/test_runner.py` — notebook parsing and execution:
  - Cell splitting on `# %%`.
  - `cell_manifest` generation.
  - SSE event sequence correctness.
- `pytest nb/tests/test_daemon.py` — HTTP routes, SSE stream format.

### Manual Verification
- Run `nb run` against a sample notebook (`example.py`) with `# %%` cells.
- Open `http://localhost:7777` in browser and verify:
  - Notebook header rendered.
  - Cells appear in order.
  - `display_md` renders Markdown.
  - `embed_plotly` renders interactive figure.
  - Page does not scroll on new output (§4.4).
  - Stale output is marked on re-run with edited cell.
