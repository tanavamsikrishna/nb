import asyncio
import base64
import contextlib
import importlib.abc
import importlib.util
import io
import json
import linecache
import os
import re
import signal
import site
import sys
import sysconfig
import tempfile
import time
import traceback
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.machinery import ModuleSpec, PathFinder, SourceFileLoader
from pathlib import Path
from typing import Any, Set, TypeGuard

import aiohttp
import msgspec
from aiohttp import web

import nb.framework as fw
from nb import experiments, runner


class CellRecord(msgspec.Struct):
    type: str
    payload: Any


class CellProfiling(msgspec.Struct):
    wall_ms: float | None
    cpu_ms: float | None


class CellState(msgspec.Struct):
    id: int
    title: str | None
    source_line: int | None
    status: str
    stale: bool
    profiling: CellProfiling | None
    records: list[CellRecord]


class NotebookEntry(msgspec.Struct):
    path: str
    name: str
    num_cells: int
    active: bool
    has_experiments: bool


class RenderedTable(msgspec.Struct, tag_field="type", tag="table", omit_defaults=True):
    schema: dict[str, str]
    rows: int
    preview: str
    label: str | None
    path: str | None = None


class RenderedSpilled(msgspec.Struct):
    type: str
    path: str


class RenderedInline(msgspec.Struct):
    type: str
    content: Any


RenderedRecord = RenderedTable | RenderedSpilled | RenderedInline


# Project root the daemon serves, set once in `main`. Experiments are persisted
# under `<_project_dir>/.nb/experiments` and listed/loaded from there.
_project_dir: Path = Path.cwd()

# Snapshot of sys.modules taken before any notebook runs. Used by --clear-imports
# to identify and remove only user-added modules (local files the notebook imported)
# while leaving stdlib, aiohttp, nb.* and other daemon dependencies untouched.
_baseline_modules: frozenset[str] = frozenset(sys.modules)


def _build_package_prefixes() -> frozenset[str]:
    """Directory prefixes where stdlib and installed packages live."""
    prefixes: set[str] = set()
    for key in ("stdlib", "purelib", "platlib"):
        p = sysconfig.get_path(key)
        if p:
            prefixes.add(p)
    try:
        prefixes.update(site.getsitepackages())
    except AttributeError:
        pass
    usp = site.getusersitepackages()
    if usp:
        prefixes.add(usp)
    return frozenset(prefixes)


# Installed-package and stdlib path prefixes — modules whose __file__ starts
# with one of these are left alone by --clear-imports.
_package_prefixes: frozenset[str] = _build_package_prefixes()


def _iter_user_modules():
    """Yield (name, file) for each currently-imported local/user module — the same
    set --clear-imports targets: a `.py` __file__, not present at daemon startup,
    and not living under an installed-package/stdlib prefix."""
    for k, m in list(sys.modules.items()):
        if k in _baseline_modules:
            continue
        f = getattr(m, "__file__", None)
        if (
            f is not None
            and f.endswith(".py")
            and not any(f.startswith(p) for p in _package_prefixes)
        ):
            yield k, f


def _is_frozen_entry(entry) -> TypeGuard[tuple[int, None, list[str], str]]:
    """True if `entry` is one of our permanent linecache pins: a 4-tuple with a None
    mtime slot (a lazy-cache entry is a 1-tuple; a normal disk-cached entry has a
    float mtime). linecache.checkcache skips such entries, so they survive on-disk
    edits — that's what keeps the shown source aligned with the bytecode that ran."""
    return entry is not None and len(entry) == 4 and entry[1] is None


def _freeze_linecache(filename: str, text: str) -> None:
    """Pin `text` as the linecache source for `filename` with mtime=None (permanent —
    checkcache skips it), so tracebacks render this exact source even after the file
    changes on disk. Mirrors the notebook-source freeze in runner.py."""
    linecache.cache[filename] = (len(text), None, text.splitlines(keepends=True), filename)


class _PinningLoader(SourceFileLoader):
    """SourceFileLoader that pins a module's source into linecache the instant it is
    loaded — reading the .py itself, so it captures the source even when the bytecode
    comes from a cached .pyc (no compile happens then). Freezing at import time, before
    any later on-disk edit, is what lets a traceback show the code that actually ran —
    even for a module edited *while the notebook is still running*."""

    def get_code(self, fullname):
        try:
            text = importlib.util.decode_source(self.get_data(self.path))  # PEP 263 cookie
            _freeze_linecache(self.path, text)
        except Exception:
            pass  # pinning must never break the import that triggered it
        return super().get_code(fullname)


class _PinningFinder(importlib.abc.MetaPathFinder):
    """Meta-path finder that swaps in _PinningLoader for local (user) source modules,
    leaving stdlib/site-packages on their stock loader (they don't get pinned, matching
    --clear-imports scope and avoiding pinning every library's source)."""

    def find_spec(self, fullname, path, target=None) -> ModuleSpec | None:
        spec = PathFinder.find_spec(fullname, path, target)
        origin = spec.origin if spec else None
        if (
            spec is not None
            and origin is not None
            and origin.endswith(".py")
            and not any(origin.startswith(p) for p in _package_prefixes)
        ):
            spec.loader = _PinningLoader(fullname, origin)
        return spec


def _stale_user_modules() -> list[tuple[str, str]]:
    """(name, file) for imported user modules whose on-disk source has diverged from
    the pinned source that actually ran (see _PinningLoader). These keep
    executing the old bytecode until --clear-imports, so the caller warns about them
    before a run. Modules with no frozen entry (never ran, or lazily cached) have no
    baseline to compare against and are skipped."""
    stale: list[tuple[str, str]] = []
    for name, f in _iter_user_modules():
        entry = linecache.cache.get(f)
        if not _is_frozen_entry(entry):
            continue  # not frozen — no known "what ran" baseline
        frozen = "".join(entry[2])  # splitlines(keepends=True) round-trips exactly
        try:
            with open(f, "r", encoding="utf-8") as fh:
                current = fh.read()
        except OSError:
            continue
        if current != frozen:
            stale.append((name, f))
    return stale


@dataclass(eq=False)  # identity hash: each connection is a distinct object
class Client:
    """One connected /stream subscriber, bound to the notebook it asked for via
    `?path=`. Live events are delivered only to clients bound to the notebook
    that produced them (see `emit_event`). A client with no `?path=` is bound to
    nothing and receives no live events (the `/` index page is the path-less
    surface, not a stream)."""

    queue: "asyncio.Queue"
    path: str | None


active_clients: Set[Client] = set()
run_lock = asyncio.Lock()


@dataclass
class NotebookSession:
    """Everything the daemon remembers about one notebook, keyed by resolved path.

    Groups the two long-lived, per-notebook things that used to be separate
    globals:

    - `exec_ns`: the persistent execution namespace (the notebook's "kernel").
      A full `nb run` replaces it with a fresh one before executing; a partial
      re-run (`nb run file.py:42`) reuses it so the targeted cells see the state
      the last full run left behind. Lives in the daemon's long-lived process
      (like `fw._cache`), not the per-run exec scope, so it survives across runs.
    - `docstring` / `cells`: the authoritative render state mirrored to the
      browser — what a freshly-connected tab must display, not a log of past
      events. State-bearing events fold into it (`_fold_state`); a new client
      gets a snapshot regenerated from it (`_snapshot_events`).
    """

    path: str
    exec_ns: dict = field(default_factory=dict)
    docstring: str | None = None
    code: str | None = None
    cells: list[CellState] = field(default_factory=list)
    # Auto-detected experiment parameters (SCREAMING_SNAKE_CASE globals) from the
    # most recent run, shown at the top of the notebook. Folded from the `params`
    # event and replayed in snapshots; persisted with each saved run.
    params: dict = field(default_factory=dict)
    # Output files logged during the most recent run via log_artifact, an ordered
    # list of {name, path}. Folded from the `artifacts` event and replayed in
    # snapshots; persisted with each saved run.
    artifacts: list = field(default_factory=list)
    # run_id of this notebook's most recent *full* run. A partial re-run is saved
    # as a child experiment of it (None until the first full run; a fresh daemon
    # with no session falls back to a full run, so a child never lacks a parent).
    parent_run_id: str | None = None


# Every notebook the daemon has run this session, keyed by resolved path. Render
# state is kept per notebook; each `/stream?path=` client reads its own session,
# and the `/` index page (`/notebooks`) lists them all.
_sessions: dict[str, NotebookSession] = {}


def _fresh_exec_ns() -> dict:
    return {
        "__name__": "__main__",
        "__builtins__": __builtins__,
        "display": fw.display,
        "nb_cache": fw.nb_cache,
        "artifact_path": fw.artifact_path,
        "log_artifact": fw.log_artifact,
    }


def _state_find_cell(cells: list[CellState], cell_id: int | None) -> CellState | None:
    for cell in cells:
        if cell.id == cell_id:
            return cell
    return None


def _fold_state(event_type: str, data: dict, path: str) -> None:
    """Fold a state-bearing event into the render state of the notebook it belongs
    to (`path`, the notebook being run). No-op for transient events (run_end and
    any future scroll/toast/collapse), which are live-only, and when that notebook
    has no session yet."""
    session = _sessions.get(path)
    if session is None:
        return
    cells = session.cells

    if event_type == "notebook_header":
        session.docstring = data.get("docstring")
        if "code" in data:
            session.code = data.get("code")
    elif event_type == "params":
        session.params = data.get("params", {})
    elif event_type == "artifacts":
        session.artifacts = data.get("artifacts", [])
    elif event_type == "run_start":
        manifest = data.get("cell_manifest", [])
        if data.get("partial"):
            # Mark only the targeted cells stale/pending; leave the rest exactly
            # as they are (their output stays visible across the partial re-run).
            for item in manifest:
                cell = _state_find_cell(cells, item["id"])
                if cell is None:
                    cell = CellState(
                        id=item["id"],
                        title=item.get("title"),
                        source_line=None,
                        status="pending",
                        stale=False,
                        profiling=None,
                        records=[],
                    )
                    cells.append(cell)
                cell.title = item.get("title", cell.title)
                cell.stale = True
                cell.status = "pending"
            cells.sort(key=lambda c: c.id)
        else:
            # Full run: rebuild the cell list to the manifest, preserving the
            # records of surviving ids and dropping absent ones (mirrors the
            # frontend reconcile + finalizeRun, resolved immediately).
            existing = {c.id: c for c in cells}
            rebuilt = []
            for item in manifest:
                cell = existing.get(item["id"])
                if cell is None:
                    cell = CellState(
                        id=item["id"],
                        title=item.get("title"),
                        source_line=None,
                        status="pending",
                        stale=False,
                        profiling=None,
                        records=[],
                    )
                else:
                    cell.title = item.get("title", cell.title)
                    cell.stale = True
                    cell.status = "pending"
                rebuilt.append(cell)
            rebuilt.sort(key=lambda c: c.id)
            session.cells = rebuilt
    elif event_type == "cell_start":
        cell = _state_find_cell(cells, data["cell_id"])
        if cell is None:
            cell = CellState(
                id=data["cell_id"],
                title=data.get("title"),
                source_line=None,
                status="pending",
                stale=False,
                profiling=None,
                records=[],
            )
            cells.append(cell)
            cells.sort(key=lambda c: c.id)
        cell.status = "running"
        cell.stale = False
        cell.title = data.get("title", cell.title)
        cell.source_line = data.get("source_line", cell.source_line)
        cell.profiling = None
        cell.records = []
    elif event_type == "display_record":
        cell = _state_find_cell(cells, data["cell_id"])
        if cell is not None:
            cell.records.append(CellRecord(type=data["type"], payload=data["payload"]))
    elif event_type == "cell_end":
        cell = _state_find_cell(cells, data["cell_id"])
        if cell is not None:
            cell.status = data.get("status", "ok")
            cell.profiling = CellProfiling(wall_ms=data.get("wall_ms"), cpu_ms=data.get("cpu_ms"))


def _snapshot_events(session: NotebookSession | None) -> list[dict]:
    """Regenerate the canonical event sequence that reproduces `session`'s render
    state in a freshly-connected client. The frontend's live-event handlers
    hydrate the store identically, so there is a single renderer path (live or
    snapshot). Empty until the session has cells (blank UI before the first run)."""
    if session is None or not session.cells:
        return []

    events: list[dict] = []
    header: dict = {"path": session.path}
    if session.docstring is not None:
        header["docstring"] = session.docstring
    if session.code is not None:
        header["code"] = session.code
    events.append({"event": "notebook_header", "data": header})

    manifest = [{"id": c.id, "title": c.title or ""} for c in session.cells]
    events.append({"event": "run_start", "data": {"cell_manifest": manifest, "partial": False}})

    for cell in session.cells:
        events.append(
            {
                "event": "cell_start",
                "data": {
                    "cell_id": cell.id,
                    "source_line": cell.source_line,
                    "title": cell.title or "",
                },
            }
        )
        for record in cell.records:
            events.append(
                {
                    "event": "display_record",
                    "data": {
                        "cell_id": cell.id,
                        "type": record.type,
                        "payload": record.payload,
                    },
                }
            )
        profiling = cell.profiling
        # Coerce a non-terminal status (a cell still running/pending when the
        # client connected) to "ok"; the subsequent live events correct it.
        status = cell.status if cell.status in ("ok", "error") else "ok"
        events.append(
            {
                "event": "cell_end",
                "data": {
                    "cell_id": cell.id,
                    "wall_ms": (profiling.wall_ms or 0) if profiling else 0,
                    "cpu_ms": (profiling.cpu_ms or 0) if profiling else 0,
                    "status": status,
                },
            }
        )
    # Auto-detected params, replayed before run_end the same way a live run emits
    # them (see runner.emit_params), so a freshly-connected client shows them.
    events.append({"event": "params", "data": {"params": session.params}})
    # Logged artifacts, replayed the same way (see runner.emit_artifacts).
    events.append({"event": "artifacts", "data": {"artifacts": session.artifacts}})
    # Terminal event of a completed run: clears the client's live "running"
    # indicator (set by each cell_start above) and finalizes. The snapshot
    # represents a finished run, so it must settle the client to idle the same
    # way a real run_end does. run_end is still never folded into stored state.
    events.append({"event": "run_end", "data": {"status": "ok"}})
    return events


def _session_for_stream(requested_path: str | None) -> NotebookSession | None:
    """Resolve which notebook a /stream client sees. The frontend always sends
    `?path=` (the per-notebook view); we honor it strictly so a client asking for
    notebook X only ever sees X (empty snapshot, then live events, even before X
    has run). A client with no `?path=` has no notebook to stream — the path-less
    landing surface is the `/` index page (a list of all notebooks), not a
    stream."""
    if requested_path is None:
        return None
    return _sessions.get(requested_path)


def emit_event(event_type: str, event_data: dict, path: str) -> None:
    """Fold and fan out an event for the notebook `path` (the one being run; the
    caller supplies it). Routing is by `path`, not by any global, so an event
    always reaches the right session and the right clients."""
    event = {"event": event_type, "data": event_data}
    # Fold state-bearing events into that notebook's session; transient ones are
    # no-ops there (live fan-out below still delivers them to connected clients).
    _fold_state(event_type, event_data, path)
    # Deliver only to clients bound to this notebook (`?path=`); others are
    # untouched by this run.
    for client in list(active_clients):
        if client.path == path:
            client.queue.put_nowait(event)


def _format_sse(event: dict) -> bytes:
    data_str = json.dumps(event["data"])
    return f"event: {event['event']}\ndata: {data_str}\n\n".encode("utf-8")


async def stream_handler(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["Access-Control-Allow-Origin"] = "*"
    await response.prepare(request)

    # Pick which notebook this client streams (see `_session_for_stream`). The
    # same path binds the connection so live events stay scoped to it.
    requested_path = request.query.get("path")
    session = _session_for_stream(requested_path)

    # Snapshot current notebook state and subscribe with no await in between, so
    # the single-threaded event loop can't slip a live event past us: anything
    # emitted after this point lands on the queue, never duplicating the
    # snapshot. (emit_event also runs on this loop thread.)
    buffered = _snapshot_events(session)
    client = Client(queue=asyncio.Queue(), path=requested_path)
    active_clients.add(client)
    try:
        for event in buffered:
            await response.write(_format_sse(event))
        while True:
            event = await client.queue.get()
            await response.write(_format_sse(event))
    except asyncio.CancelledError:
        pass
    except aiohttp.ClientConnectionResetError:
        print("Connection to frontend reset")
    finally:
        active_clients.discard(client)
    return response


async def notebooks_handler(request: web.Request) -> web.Response:
    """List notebooks for the index page: the union of those the daemon currently
    holds live state for (streamable at `/?path=<path>`) and those with stored
    experiments (browsable at `/?view=experiments&path=<path>`) even when no
    session is live. `num_cells` is 0 for an experiments-only notebook."""
    by_path: dict[str, NotebookEntry] = {}
    for path, session in _sessions.items():
        by_path[path] = NotebookEntry(
            path=path,
            name=os.path.basename(path),
            num_cells=len(session.cells),
            active=True,
            has_experiments=False,
        )
    for nb in experiments.list_notebooks(_project_dir):
        entry = by_path.get(nb.path)
        if entry is None:
            entry = NotebookEntry(
                path=nb.path,
                name=nb.name,
                num_cells=0,
                active=False,
                has_experiments=False,
            )
            by_path[nb.path] = entry
        entry.has_experiments = nb.run_count > 0

    notebooks = sorted(by_path.values(), key=lambda nb: nb.path)
    return web.Response(
        body=msgspec.json.encode({"notebooks": notebooks}),
        content_type="application/json",
    )


async def experiments_handler(request: web.Request) -> web.Response:
    """Run history for one notebook as a parent/child forest (newest-first)."""
    path = request.query.get("path")
    if not path:
        return web.json_response({"error": "missing path"}, status=400)
    return web.json_response({"runs": experiments.list_runs_tree(_project_dir, path)})


async def experiment_handler(request: web.Request) -> web.Response:
    """One saved run: `{meta, code, cells}` for the read-only viewer."""
    path = request.query.get("path")
    run_id = request.query.get("run_id")
    if not path or not run_id:
        return web.json_response({"error": "missing path or run_id"}, status=400)
    run = experiments.load_run(_project_dir, path, run_id)
    if run is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(run)


async def artifact_handler(request: web.Request) -> web.FileResponse | web.Response:
    """Serve one artifact file for download. `file` is the absolute path recorded
    in a run's meta (see fw.log_artifact / experiments.finalize_run). It is served
    only after confirming it resolves to a real file *inside this project's
    experiments store*, so a crafted `?file=` can't read arbitrary files off disk.
    The Content-Disposition filename names the download (it takes precedence over
    a link's `download` attribute); the on-disk basename is the real artifact
    name, per fw.artifact_path."""
    file = request.query.get("file")
    if not file:
        return web.json_response({"error": "missing file"}, status=400)
    store_root = Path(_project_dir).joinpath(*experiments.EXPERIMENTS_SUBDIR).resolve()
    try:
        target = Path(file).resolve()
    except (OSError, RuntimeError, ValueError):
        return web.json_response({"error": "bad path"}, status=400)
    if not target.is_relative_to(store_root) or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(
        target, headers={"Content-Disposition": f'attachment; filename="{target.name}"'}
    )


STATIC_DIR = Path(__file__).parent / "static"


async def index_handler(request: web.Request) -> web.FileResponse | web.Response:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return web.Response(
            text="UI build not found. Please run `make build` first to compile and install the frontend.",
            status=404,
        )
    return web.FileResponse(index_file)


def _query_cells(session: NotebookSession) -> dict:
    """Summarize a notebook's cells: title, line span, run status, record count.

    A cell spans from its `# %%` header line through the line before the next
    cell's header; the last cell runs to EOF (read from the file). `source_line`
    is the first content line (header + 1), so the header is `source_line - 1` —
    matching the line `nb run file.py:LINE` resolves to this cell. It can be None
    for a pending cell (never started a run); its span is then reported as null."""
    cells = session.cells
    try:
        total_lines = len(Path(session.path).read_text(encoding="utf-8").splitlines())
    except OSError:
        total_lines = None

    # Header line of each cell (the `# %%` line), in order.
    headers = [(c.source_line - 1) if c.source_line is not None else None for c in cells]
    out = []
    for i, cell in enumerate(cells):
        start = headers[i]
        end = None
        if start is not None:
            nxt = next((h for h in headers[i + 1 :] if h is not None), None)
            end = (nxt - 1) if nxt is not None else total_lines
        out.append(
            {
                "id": cell.id,
                "title": cell.title,
                "start_line": start,
                "end_line": end,
                "status": cell.status,
                "records": len(cell.records),
            }
        )
    return {"status": "ok", "count": len(out), "cells": out}


# How many leading rows of a table are inlined (as CSV) for a preview. The full
# data is spilled to a CSV file only when the table has more rows than this, so a
# reader always gets the schema and a preview, plus the complete data when there
# is more of it.
_TABLE_PREVIEW_ROWS = 50


def _spill(session: NotebookSession, tag: str, n: int, suffix: str, data: bytes) -> str:
    """Write `data` to a stable temp path and return it. The name is keyed by
    notebook + tag + index (`c3` for a cell, `exec` for query exec), so
    re-querying the same record overwrites its file instead of leaking a fresh
    temp file on every call."""
    stem = Path(session.path).stem
    fpath = Path(tempfile.gettempdir()) / f"nb-query-{stem}-{tag}-{n}{suffix}"
    fpath.write_bytes(data)
    return str(fpath)


def _render_record(
    record: CellRecord, session: NotebookSession, tag: str, n: int
) -> RenderedRecord:
    """Map one display record to a query-reply entry.

    - table: always returns `schema` (column -> dtype) and a CSV `preview` of the
      first `_TABLE_PREVIEW_ROWS` rows; when the table is larger, the full data is
      also written to a CSV file and its `path` is returned. `schema` carries the
      dtypes that CSV itself does not.
    - plotly/altair: the spec is not human-readable, so it is always written to a
      JSON file and only the `path` is returned.
    - everything else (text/md/html/object): inlined as-is."""
    rtype = record.type
    payload = record.payload

    if rtype == "table":
        import polars as pl  # present in-process: a table record means polars made it

        df = pl.read_parquet(io.BytesIO(base64.b64decode(payload["data"])))
        total = payload.get("total_rows", df.height)
        spill_path = (
            _spill(session, tag, n, ".csv", df.write_csv().encode("utf-8"))
            if total > _TABLE_PREVIEW_ROWS
            else None
        )
        return RenderedTable(
            schema={name: str(dtype) for name, dtype in zip(df.columns, df.dtypes)},
            rows=total,
            preview=df.head(_TABLE_PREVIEW_ROWS).write_csv(),
            label=payload.get("label"),
            path=spill_path,
        )

    if rtype in ("plotly", "altair"):
        return RenderedSpilled(
            type=rtype,
            path=_spill(session, tag, n, ".json", json.dumps(payload).encode("utf-8")),
        )

    return RenderedInline(type=rtype, content=payload)


def _query_records(session: NotebookSession, cell_id: int | None) -> dict:
    cell = _state_find_cell(session.cells, cell_id)
    if cell is None:
        ids = [c.id for c in session.cells]
        return {"status": "error", "message": f"No cell {cell_id}. Available cells: {ids}"}
    cid = cell.id
    records = [_render_record(r, session, f"c{cid}", n) for n, r in enumerate(cell.records)]
    return {"status": "ok", "cell": cid, "records": records}


def _exec_in_ns(session: NotebookSession, code: str) -> dict:
    """Exec `code` against the notebook's live namespace, capturing stdout/stderr,
    any traceback, and any `display(...)` records (rendered like `query records`,
    tables spilled to Parquet). Runs in an executor thread so it can't block the
    event loop. A capturing emitter is installed for the call only; run_lock
    guarantees no concurrent run is touching `fw._active_emitter`."""
    out, err = io.StringIO(), io.StringIO()
    exc: str | None = None
    captured: list[fw.DisplayRecord] = []
    old_emitter = fw._active_emitter
    fw._active_emitter = captured.append
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                exec(compile(code, "<nb query exec>", "exec"), session.exec_ns)
            except BaseException:
                exc = traceback.format_exc()
    finally:
        fw._active_emitter = old_emitter
    records = [
        _render_record(CellRecord(type=r.type, payload=r.payload), session, "exec", n)
        for n, r in enumerate(captured)
    ]
    return {
        "status": "ok",
        "stdout": out.getvalue(),
        "stderr": err.getvalue(),
        "exception": exc,
        "records": records,
    }


async def _handle_query(req: dict, writer: asyncio.StreamWriter) -> None:
    """Serve a read-only `nb query` request against a notebook's saved session.

    Replies with exactly one line-delimited JSON message. Queries run under the
    same `run_lock` as runs (the caller holds it), so they never observe a
    half-finished run. `exec` runs against the live `exec_ns` and may mutate it;
    its `display(...)` calls are captured into the reply (not streamed to
    browsers) by a temporary emitter (see `_exec_in_ns`)."""
    path = str(Path(req["path"]))
    session = _sessions.get(path)
    if session is None:
        reply: dict = {"status": "error", "message": f"Notebook {path} has not been run yet."}
    else:
        loop = asyncio.get_running_loop()
        op = req.get("op")
        if op == "cells":
            reply = _query_cells(session)
        elif op == "records":
            # Rendering a table decodes Parquet and writes CSV to disk; run it off
            # the event loop so a large table can't stall live SSE to browsers.
            reply = await loop.run_in_executor(None, _query_records, session, req.get("cell"))
        elif op == "exec":
            if not session.exec_ns:
                reply = {
                    "status": "error",
                    "message": "Notebook has no execution namespace yet; run it first.",
                }
            else:
                reply = await loop.run_in_executor(None, _exec_in_ns, session, req.get("code", ""))
        else:
            reply = {"status": "error", "message": f"Unknown query op: {op!r}."}

    writer.write(msgspec.json.encode(reply) + b"\n")
    await writer.drain()


async def handle_ipc_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    async with run_lock:
        try:
            line = await reader.readline()
            if not line:
                return

            req = json.loads(line.decode("utf-8"))

            # `command` defaults to "run" so the existing CLI protocol is
            # unchanged. `query` is a read path for agents (see _handle_query):
            # it reads the notebook's saved session state and replies once.
            if req.get("command") == "query":
                await _handle_query(req, writer)
                return

            notebook_path = Path(req["path"])
            ns_key = str(notebook_path)  # session key + the path this run's events route to
            clear_cache_names = req.get("clear_cache")
            clear_cache_all = req.get("clear_cache_all", False)
            clear_imports = req.get("clear_imports", False)
            lines = req.get("lines")  # [start, end] for a partial re-run, else None

            loop = asyncio.get_running_loop()

            def active_emitter(record: fw.DisplayRecord) -> None:
                event_data = {
                    "cell_id": fw._current_cell_id,
                    "type": record.type,
                    "payload": record.payload,
                }
                # Display primitives run in the executor thread, so hop back to
                # the event loop thread to touch the client queues.
                loop.call_soon_threadsafe(emit_event, "display_record", event_data, ns_key)

            old_emitter = fw._active_emitter
            fw._active_emitter = active_emitter

            def thread_safe_emit_event(event_type: str, event_data: dict) -> None:
                loop.call_soon_threadsafe(emit_event, event_type, event_data, ns_key)

            def cli_log(stream: str, data: str) -> None:
                # Notebook console output (stdout/stderr/tracebacks) runs in the
                # executor thread; hop to the loop thread to write the CLI socket.
                # Fire-and-forget like thread_safe_emit_event; the drain before the
                # terminal reply flushes the buffer.
                msg = json.dumps({"status": stream, "data": data}).encode("utf-8") + b"\n"
                loop.call_soon_threadsafe(writer.write, msg)

            try:
                # Invalidate caches up-front, before any cell runs, so cached
                # functions recompute on this run. Done here (not in run_notebook)
                # so the cleared-cache count can be reported to the CLI immediately,
                # rather than only with the end-of-run reply. Safe to mutate
                # fw._cache directly: run_lock serializes runs.
                cache_result: dict | None = None
                if clear_cache_all:
                    functions = len({e.qualname for e in fw._cache.values()})
                    fw.clear_all_cache()
                    cache_result = {"all": True, "functions": functions, "unmatched": []}
                elif clear_cache_names:
                    functions, unmatched = fw.clear_cache_by_name(clear_cache_names)
                    cache_result = {"all": False, "functions": functions, "unmatched": unmatched}

                if cache_result is not None:
                    writer.write(
                        json.dumps({"status": "cache", "cache": cache_result}).encode("utf-8")
                        + b"\n"
                    )
                    await writer.drain()

                if clear_imports:
                    to_remove = list(_iter_user_modules())
                    for k, f in to_remove:
                        sys.modules.pop(k, None)
                        # Drop the pinned source so the re-import re-pins fresh
                        # (see _PinningLoader).
                        linecache.cache.pop(f, None)
                    writer.write(
                        json.dumps(
                            {"status": "imports", "imports": {"count": len(to_remove)}}
                        ).encode("utf-8")
                        + b"\n"
                    )
                    await writer.drain()

                # Warn (don't reload) about modules edited on disk since they were
                # imported: the daemon keeps running the old bytecode, so the coming
                # run — and any traceback from it — reflects the stale version. After
                # a --clear-imports the affected modules were dropped above, so this
                # correctly reports nothing until they're re-imported and re-run.
                for name, _f in _stale_user_modules():
                    cli_log(
                        "stderr",
                        f"[nb] warning: '{name}' changed on disk since it was imported; "
                        "still running the previously imported version "
                        "(re-run with --clear-imports to reload it).\n",
                    )

                # Resolve the session and run mode. Events route by `ns_key`
                # (passed to emit_event), so folding lands in this notebook's
                # render state. A partial re-run reuses the session's saved
                # namespace; if none exists (daemon just started, or this notebook
                # hasn't run yet), fall back to a full run, which seeds it — so the
                # command always works.
                session = _sessions.get(ns_key)
                target_lines: tuple[int, int] | None = None
                if lines is not None and session is not None:
                    # Partial re-run: keep the existing namespace and render state.
                    target_lines = (int(lines[0]), int(lines[1]))
                else:
                    if lines is not None:
                        cli_log("stdout", "No saved state for this notebook; running it in full.\n")
                    # Full run: fresh namespace ("purge"); keep any existing render
                    # cells so the full-run reconcile can preserve surviving output.
                    if session is None:
                        session = NotebookSession(path=ns_key)
                        _sessions[ns_key] = session
                    session.exec_ns = _fresh_exec_ns()

                # Create the run's experiment directory *before* it executes so
                # artifacts (fw.artifact_path) land straight in it; meta/code/records
                # are written by finalize_run after the run. Saving must never break
                # a run, so a failure here just disables persistence for this run.
                run_handle: experiments.RunHandle | None = None
                try:
                    run_handle = experiments.begin_run(_project_dir, ns_key)
                except Exception as exc:
                    cli_log("stderr", f"[nb] failed to start experiment: {exc}\n")
                fw._current_run_dir = run_handle.artifacts_dir if run_handle else None
                fw._artifacts = []

                # Execute notebook in separate thread so exec doesn't block the main event loop
                started_at = datetime.now(timezone.utc).isoformat()
                t0 = time.perf_counter()
                errored, run_code, ran_cell_ids = await loop.run_in_executor(
                    None,
                    runner.run_notebook,
                    notebook_path,
                    session.exec_ns,
                    thread_safe_emit_event,
                    cli_log,
                    target_lines,
                )
                dur_ms = int((time.perf_counter() - t0) * 1000)

                # Persist the run as an experiment, filling in the directory
                # begin_run created above. By the time the executor future resolves,
                # session.cells/params/artifacts are fully folded (run_end was
                # scheduled via call_soon_threadsafe before the executor returned,
                # and the loop drains those FIFO before resuming here). A full run
                # becomes a parent; a partial run is saved as a child of the last
                # full run. run_code is "" only on a file-read failure — nothing
                # worth saving, so the empty run directory is discarded.
                if run_handle is not None and run_code:
                    is_partial = target_lines is not None
                    # A partial run leaves the parent's other cells in session.cells;
                    # save only the cells this run actually executed (spec: a child
                    # run records only its own cells, not the parent's).
                    ran_ids = set(ran_cell_ids)
                    saved_cells = [c for c in session.cells if c.id in ran_ids]
                    try:
                        saved_id = experiments.finalize_run(
                            run_handle,
                            run_code,
                            saved_cells,
                            params=session.params,
                            artifacts=session.artifacts,
                            parent_run_id=session.parent_run_id if is_partial else None,
                            kind="partial" if is_partial else "full",
                            started_at=started_at,
                            dur_ms=dur_ms,
                            status="error" if errored else "ok",
                            error="Notebook execution failed." if errored else None,
                        )
                        if not is_partial:
                            session.parent_run_id = saved_id
                    except Exception as exc:
                        # Saving an experiment must never break the run itself.
                        cli_log("stderr", f"[nb] failed to save experiment: {exc}\n")
                elif run_handle is not None:
                    # Nothing to save (file-read failure): remove the empty dir.
                    experiments.discard_run(run_handle)

                # Reply reflects the run outcome so `nb run` exits non-zero on a
                # cell error (the full traceback already streamed via cli_log).
                if errored:
                    reply = {
                        "status": "error",
                        "message": "Notebook execution failed (see output above).",
                    }
                else:
                    reply = {"status": "ok"}
                writer.write(json.dumps(reply).encode("utf-8") + b"\n")
                await writer.drain()
            finally:
                fw._active_emitter = old_emitter
                fw._current_run_dir = None

        except Exception as e:
            resp = {"status": "error", "message": str(e)}
            try:
                writer.write(json.dumps(resp).encode("utf-8") + b"\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def open_site_in_browser(site_url: str) -> None:
    await asyncio.sleep(0.5)

    process = await asyncio.subprocess.create_subprocess_exec(
        "chrome-cli", "list", "tabs", stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    tab_infos = stdout.decode().strip().splitlines()

    tab_ids = [g.group(1) for e in tab_infos if (g := re.match(r"\[(?:\d+:)?(\d+)\] nb-ui", e))]
    if len(tab_ids) > 0:
        tab_id = tab_ids[0]
        active_process = await asyncio.subprocess.create_subprocess_exec(
            "chrome-cli", "activate", "-t", tab_id
        )
        await active_process.wait()
    else:
        webbrowser.open(site_url)


async def main(project_dir: Path, *, host: str = "0.0.0.0", port: int = 7777) -> None:
    global _project_dir
    _project_dir = project_dir
    # Pin module sources at import time so tracebacks show the code that ran even if
    # the file is edited while the notebook is still running (see _PinningLoader).
    # Inserted at the front of meta_path to wrap the loader before a module is loaded.
    sys.meta_path.insert(0, _PinningFinder())
    socket_path = project_dir / ".nb.sock"
    if socket_path.exists():
        socket_path.unlink()

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    app = web.Application()
    app.router.add_get("/stream", stream_handler)
    app.router.add_get("/notebooks", notebooks_handler)
    app.router.add_get("/experiments", experiments_handler)
    app.router.add_get("/experiment", experiment_handler)
    app.router.add_get("/artifact", artifact_handler)
    app.router.add_get("/", index_handler)
    app.router.add_static("/", STATIC_DIR)

    socket_server = await asyncio.start_unix_server(handle_ipc_client, path=str(socket_path))

    runner_http = web.AppRunner(app)
    await runner_http.setup()
    site = web.TCPSite(runner_http, host, port)
    await site.start()

    site_url = f"http://localhost:{port}"

    print(f"Daemon started. Unix socket at {socket_path}, HTTP at {site_url}", flush=True)

    # _task = asyncio.create_task(open_site_in_browser(site_url))

    # First SIGINT/SIGTERM shuts down gracefully; a second one forces exit.
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    shutting_down = False

    def _signal_handler() -> None:
        nonlocal shutting_down
        if shutting_down:
            if socket_path.exists():
                socket_path.unlink()
            os._exit(1)
        shutting_down = True
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        await shutdown_event.wait()
    finally:
        socket_server.close()
        await socket_server.wait_closed()
        if socket_path.exists():
            socket_path.unlink()
        await runner_http.cleanup()


def start_daemon(project_dir: Path) -> None:
    asyncio.run(main(project_dir))
