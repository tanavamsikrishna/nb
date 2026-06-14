# `nb` — Python Notebook Infrastructure: Specification

---

## 1. Notebook Format

Plain `.py` files with `# %%` cell delimiters.

The module-level docstring is treated as the notebook's title/description and is
rendered at the top of the browser UI (see §4.3, §5).

---

## 2. Caching Subsystem

### 2.1 `@nb_cache` Decorator

Wraps a function with input-hash-based caching. At decoration time, all display
primitives in the function's globals are replaced with capturing versions using
`types.FunctionType` over a copied globals dict. This means display calls inside
`@nb_cache` are permitted — they are intercepted, not forwarded.

The same decorator works on named lambdas.

```python
import types
from functools import wraps
from typing import TypeVar, Callable, cast

F = TypeVar('F', bound=Callable)

def nb_cache(func: F = None, *, keys: list[str] | None = None) -> F:
    def decorator(func: F) -> F:
        _capture_stack: list[list[DisplayRecord]] = []

        def nb_display(payload):
            if _capture_stack:
                _capture_stack[-1].append(DisplayRecord("display", payload))
        # repeat for display_md, embed_plotly, display_html, display_structured, embed_altair

        new_globals = func.__globals__.copy()
        new_globals["display"] = nb_display
        # assign remaining interceptors into new_globals

        new_func = types.FunctionType(
            func.__code__, new_globals, func.__name__,
            func.__defaults__, func.__closure__
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = compute_key(new_func, args, kwargs, keys)

            if cache_key in _cache:
                entry = _cache[cache_key]
                for record in entry.display_records:
                    emit(record)            # replay to SSE stream
                return entry.result

            records: list[DisplayRecord] = []
            _capture_stack.append(records)
            try:
                result = new_func(*args, **kwargs)
            finally:
                _capture_stack.pop()

            _cache[cache_key] = CacheEntry(result=result, display_records=records)
            return result

        return cast(F, wrapper)

    if func is not None:
        return decorator(func)      # bare @nb_cache
    return decorator                 # @nb_cache(keys=[...])
```

`_capture_stack` is a per-decorator-instance stack, making capture correct for
nested `@nb_cache` calls.

**Purity linter** — run at decoration time, before the function is wrapped.
`@nb_cache` functions must not mutate or rebind globals. The linter walks the
bytecode recursively (including nested code objects) and raises `SyntaxError`
immediately if any `STORE_GLOBAL` or `DELETE_GLOBAL` instruction is found.
Reading globals via `LOAD_GLOBAL` — including imported names — is permitted.

```python
def _check_purity(code: types.CodeType, func_name: str) -> None:
    for instr in dis.get_instructions(code):
        if instr.opname in ('STORE_GLOBAL', 'DELETE_GLOBAL'):
            raise SyntaxError(
                f"@nb_cache '{func_name}' assigns to global '{instr.argval}'. "
                f"@nb_cache functions must be pure."
            )
        elif instr.opname == 'LOAD_CONST' and isinstance(instr.argval, types.CodeType):
            _check_purity(instr.argval, func_name)
```

Mutable in-place operations (e.g. `some_list.append(x)`) cannot be detected
statically and are documented as a convention violation rather than an enforced one.

### 2.2 Cache Entry

```python
@dataclass
class CacheEntry:
    result: Any
    display_records: list[DisplayRecord]
```

### 2.3 Cache Key

```
cache_key = blake2b(
    source_hash(func)                      # function body
  + input_hash(args, kwargs)               # type-dispatched, kwargs sorted
  + globals_hash(keys)                     # only when keys= is provided (§2.6)
)
```

`source_hash` invalidates the cache when the function body changes. When `keys=`
is provided, `globals_hash` invalidates the cache when any listed global changes
(see §2.6). When `keys=` is omitted, the cache key covers only source and inputs.

### 2.4 Type-Dispatch Hashing

Explicit allowlist. Unsupported types raise `TypeError` immediately.

| Type | Strategy |
|---|---|
| `polars.DataFrame` | `hash_rows()` + schema bytes |
| `numpy.ndarray` | `.tobytes()` + dtype + shape |
| Pydantic models | `model_dump_json()` |
| Primitives (`int`, `str`, `float`, `bool`, `bytes`) | `pickle.dumps()` |
| Notebook-defined functions (`__module__ == '__main__'`) | `inspect.getsource()` bytes |
| Other | `TypeError` |

### 2.5 Cache State Location

The cache dict lives in `sys.modules['nb']._cache` — inside the framework module,
not the per-run execution namespace. The execution namespace is discarded after each
run; the framework module persists in the daemon's import namespace for the lifetime
of the process.

```python
# nb/framework.py
_cache: dict[str, CacheEntry] = {}
```

### 2.6 Explicit Globals Keying via `keys=`

When `keys=` is provided, the listed global variable names are included in the
cache key. At **call time**, each name is looked up in `func.__globals__` and
hashed via the type-dispatch table (§2.4).

```python
@nb_cache(keys=["WINDOW", "THRESHOLD"])
def compute(df):
    return df.rolling(WINDOW).mean() > THRESHOLD
```

- If a name in `keys` is missing from globals → `KeyError` with a clear message.
- If a value's type is not in the type-dispatch table → `TypeError` with a clear
  message.

When `keys=` is omitted, the cache key covers only the function source and
inputs. Cache validity for upstream state is the user's responsibility via
`nb.clear_cache()` or `nb.clear_cache(func)`.

---

## 3. Performance Profiling

Wall time and CPU time are injected around each top-level cell statement. Stats are
emitted as part of the `cell_end` SSE event and rendered in a stats bar attached to
each cell's output block in the browser.

---

## 4. Display Architecture

### 4.1 Protocol

SSE (Server-Sent Events), backend → frontend only. The browser is a display surface;
no commands are sent from browser to backend.

The SSE connection persists across multiple `nb run` invocations. The browser never
disconnects or navigates between runs.

### 4.2 Streaming Granularity

`DisplayRecord`-level. Each record is emitted as it is produced. Each cell has a
`cell_id` and an ordered list of records that grows as the cell executes.

### 4.3 SSE Event Schema

```
event: notebook_header
data: {"docstring": "..."}

event: run_start
data: {"cell_manifest": [{"id": 0, "content_hash": "a1b2..."}, ...]}

event: cell_start
data: {"cell_id": 2, "source_line": 42, "label": "load_data"}

event: display_record
data: {"cell_id": 2, "type": "display_md", "payload": "..."}

event: cell_end
data: {"cell_id": 2, "wall_ms": 1240, "cpu_ms": 980, "status": "ok"}

event: run_end
data: {"status": "ok"}
```

`notebook_header` is the first event emitted on every run. The docstring is
extracted before execution via `ast.get_docstring(ast.parse(source))` and rendered
as Markdown above all cell output. Omitted if the notebook has no module-level
docstring.

`display_record.type` is one of: `display`, `display_md`, `display_html`,
`embed_plotly`, `display_structured`, `embed_altair`.

### 4.4 Scroll Stability

The browser must not scroll or reset position when new output arrives. This is
achieved via Svelte's keyed `{#each cells as cell (cell.id)}`. Cell DOM containers
are updated in-place rather than destroyed and recreated, so page height never
collapses and scroll position is unaffected.

### 4.5 Cell Identity

Two separate concerns:

| Concern | Value |
|---|---|
| DOM key | Positional serial index (`0, 1, 2, ...`) |
| Change detector | `hash(cell source)` |

The DOM key is the Svelte loop key. The content hash detects whether a cell's code
changed between runs — used to determine staleness of existing output.

### 4.6 Run Reconciliation

On `run_start`, the browser receives the full `cell_manifest` and reconciles:

| Condition | Action |
|---|---|
| Same index, same hash | Unchanged — existing output remains |
| Same index, different hash | Edited — existing output marked stale |
| New index | Insert container at correct position |
| Index absent from new manifest | Mark for removal after `run_end` |

---

## 5. Frontend

### 5.1 Stack

Svelte + Vite. The `nb-ui/` project is developed standalone; the Vite dev server
proxies `/stream` to the daemon for SSE during UI development (hot reload without
daemon involvement). Production: `vite build` → `dist/` → served as static files by
the daemon.

```javascript
// nb-ui/vite.config.js
export default defineConfig({
    plugins: [svelte()],
    server: { proxy: { '/stream': 'http://localhost:7777' } }
});
```

### 5.2 Store

```javascript
// src/stores/cells.js
export const notebookHeader = writable(null);  // string | null
export const cells = writable([]);

// Cell shape:
// {
//   id: 2,
//   content_hash: "a1b2...",
//   status: 'pending' | 'running' | 'done' | 'error',
//   records: [],                    // DisplayRecord[]
//   profiling: null | { wall_ms, cpu_ms }
// }
```

### 5.3 SSE → Store

```javascript
const es = new EventSource('/stream');

es.addEventListener('notebook_header', e => {
    notebookHeader.set(JSON.parse(e.data).docstring);
});

es.addEventListener('run_start', e => {
    reconcile(cells, JSON.parse(e.data).cell_manifest);
});

es.addEventListener('display_record', e => {
    const { cell_id, type, payload } = JSON.parse(e.data);
    cells.update(cs => {
        cs.find(c => c.id === cell_id).records.push({ type, payload });
        return cs;
    });
});

es.addEventListener('cell_end', e => {
    const { cell_id, wall_ms, cpu_ms, status } = JSON.parse(e.data);
    cells.update(cs => {
        const cell = cs.find(c => c.id === cell_id);
        cell.status = status;
        cell.profiling = { wall_ms, cpu_ms };
        return cs;
    });
});
```

### 5.4 Template

```svelte
{#if $notebookHeader}
  <NotebookHeader docstring={$notebookHeader} />
{/if}

{#each $cells as cell (cell.id)}
  <Cell {cell} />
{/each}
```

---

## 6. Daemon

Persistent background process with two interfaces:

| Interface | Protocol | Purpose |
|---|---|---|
| Unix socket | IPC | Receives `nb run` from CLI |
| HTTP (`:7777`) | HTTP + SSE | Serves UI, streams output |

Maintains a persistent import namespace (survives across runs) and a fresh execution
namespace per run (discarded after each run).

Routes:

```
GET /       → nb/static/index.html
GET /stream → SSE endpoint
```

Static dir resolved relative to package:

```python
STATIC_DIR = Path(__file__).parent / "static"
```

---

## 7. Display Primitives

Available in notebook cells, outside `@nb_cache` (or inside, where they are
intercepted by the decorator):

| Primitive | Output type |
|---|---|
| `display(obj)` | Auto-detected |
| `display_md(text)` | Rendered Markdown |
| `display_html(html)` | Raw HTML |
| `embed_plotly(fig)` | Interactive Plotly figure |
| `display_structured(obj)` | Collapsible JSON tree |
| `embed_altair(chart)` | Altair/Vega-Lite chart |

### 7.1 Payload Serialization

| Primitive | Serialization | Payload in `DisplayRecord` |
|---|---|---|
| `embed_plotly(fig)` | `fig.to_json()` | `{data, layout, config}` dict |
| `embed_altair(chart)` | `chart.to_dict()` | Vega-Lite spec dict |
| `display_md(text)` | Identity | Markdown string |
| `display_html(html)` | Identity | HTML string |
| `display_structured(obj)` | JSON-compatible dict | Nested dict/list |
| `display(obj)` | Auto-detected | Depends on detected type |

Plotly and Altair payloads use the libraries' native JSON serialization. The
frontend renders them directly via `Plotly.newPlot(div, data, layout, config)` and
`vegaEmbed(div, spec)` respectively. No intermediate format is needed — the native
spec is the display record.

JS libraries (Plotly, Vega-Lite) are included in `<head>` conditionally, based on
which record types appear in the run's `cell_manifest`.

---

## 8. Project Structure

```
repo/
  nb/
    __init__.py
    framework.py        ← @nb_cache, DisplayRecord, CacheEntry, display primitives
    daemon.py           ← Unix socket listener, HTTP + SSE server
    cli.py              ← nb run, nb build-ui
    static/             ← gitignored, populated at build
  nb-ui/
    src/
      App.svelte
      stores/cells.js
      components/Cell.svelte
      lib/stream.js
    dist/               ← gitignored
    vite.config.js
    package.json
  pyproject.toml
  Makefile
```

### Build

```makefile
build-ui:
    cd nb-ui && npm run build

build: build-ui
    cp -r nb-ui/dist/* nb/static/
    pip install .
```

---

## 9. CLI

```
nb run notebook.py    ← send execution request to daemon via Unix socket
nb build-ui           ← vite build + copy dist → nb/static/
```
