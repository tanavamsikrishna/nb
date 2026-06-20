import asyncio
import json
import os
import re
import signal
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set

from aiohttp import web

import nb.framework as fw
from nb import runner

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
    cells: list[dict] = field(default_factory=list)


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
    }


def _state_find_cell(cells: list[dict], cell_id: int) -> dict | None:
    for cell in cells:
        if cell["id"] == cell_id:
            return cell
    return None


def _new_cell_state(cell_id: int, title: str | None = None) -> dict:
    return {
        "id": cell_id,
        "title": title,
        "source_line": None,
        "status": "pending",
        "stale": False,
        "profiling": None,
        "records": [],
    }


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
    elif event_type == "run_start":
        manifest = data.get("cell_manifest", [])
        if data.get("partial"):
            # Mark only the targeted cells stale/pending; leave the rest exactly
            # as they are (their output stays visible across the partial re-run).
            for item in manifest:
                cell = _state_find_cell(cells, item["id"])
                if cell is None:
                    cell = _new_cell_state(item["id"], item.get("title"))
                    cells.append(cell)
                cell["title"] = item.get("title", cell["title"])
                cell["stale"] = True
                cell["status"] = "pending"
            cells.sort(key=lambda c: c["id"])
        else:
            # Full run: rebuild the cell list to the manifest, preserving the
            # records of surviving ids and dropping absent ones (mirrors the
            # frontend reconcile + finalizeRun, resolved immediately).
            existing = {c["id"]: c for c in cells}
            rebuilt = []
            for item in manifest:
                cell = existing.get(item["id"])
                if cell is None:
                    cell = _new_cell_state(item["id"], item.get("title"))
                else:
                    cell["title"] = item.get("title", cell["title"])
                    cell["stale"] = True
                    cell["status"] = "pending"
                rebuilt.append(cell)
            rebuilt.sort(key=lambda c: c["id"])
            session.cells = rebuilt
    elif event_type == "cell_start":
        cell = _state_find_cell(cells, data["cell_id"])
        if cell is None:
            cell = _new_cell_state(data["cell_id"], data.get("title"))
            cells.append(cell)
            cells.sort(key=lambda c: c["id"])
        cell["status"] = "running"
        cell["stale"] = False
        cell["title"] = data.get("title", cell["title"])
        cell["source_line"] = data.get("source_line", cell["source_line"])
        cell["profiling"] = None
        cell["records"] = []
    elif event_type == "display_record":
        cell = _state_find_cell(cells, data["cell_id"])
        if cell is not None:
            cell["records"].append({"type": data["type"], "payload": data["payload"]})
    elif event_type == "cell_end":
        cell = _state_find_cell(cells, data["cell_id"])
        if cell is not None:
            cell["status"] = data.get("status")
            cell["profiling"] = {"wall_ms": data.get("wall_ms"), "cpu_ms": data.get("cpu_ms")}


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
    events.append({"event": "notebook_header", "data": header})

    manifest = [{"id": c["id"], "title": c["title"] or ""} for c in session.cells]
    events.append({"event": "run_start", "data": {"cell_manifest": manifest, "partial": False}})

    for cell in session.cells:
        events.append(
            {
                "event": "cell_start",
                "data": {
                    "cell_id": cell["id"],
                    "source_line": cell["source_line"],
                    "title": cell["title"] or "",
                },
            }
        )
        for record in cell["records"]:
            events.append(
                {
                    "event": "display_record",
                    "data": {
                        "cell_id": cell["id"],
                        "type": record["type"],
                        "payload": record["payload"],
                    },
                }
            )
        profiling = cell["profiling"] or {}
        # Coerce a non-terminal status (a cell still running/pending when the
        # client connected) to "ok"; the subsequent live events correct it.
        status = cell["status"] if cell["status"] in ("ok", "error") else "ok"
        events.append(
            {
                "event": "cell_end",
                "data": {
                    "cell_id": cell["id"],
                    "wall_ms": profiling.get("wall_ms", 0),
                    "cpu_ms": profiling.get("cpu_ms", 0),
                    "status": status,
                },
            }
        )
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
    finally:
        active_clients.discard(client)
    return response


async def notebooks_handler(request: web.Request) -> web.Response:
    """List the notebooks the daemon currently holds state for — the index page's
    picker. Each has run at least once this session, so each has a streamable
    snapshot at `/?path=<path>`."""
    notebooks = [
        {
            "path": path,
            "name": os.path.basename(path),
            "num_cells": len(session.cells),
        }
        for path, session in _sessions.items()
    ]
    notebooks.sort(key=lambda nb: nb["path"])
    return web.json_response({"notebooks": notebooks})


STATIC_DIR = Path(__file__).parent / "static"


async def index_handler(request: web.Request) -> web.FileResponse | web.Response:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return web.Response(
            text="UI build not found. Please run `make build` first to compile and install the frontend.",
            status=404,
        )
    return web.FileResponse(index_file)


async def handle_ipc_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    async with run_lock:
        try:
            line = await reader.readline()
            if not line:
                return

            req = json.loads(line.decode("utf-8"))
            notebook_path = Path(req["path"])
            ns_key = str(notebook_path)  # session key + the path this run's events route to
            clear_cache_names = req.get("clear_cache")
            clear_cache_all = req.get("clear_cache_all", False)
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

                # Execute notebook in separate thread so exec doesn't block the main event loop
                errored = await loop.run_in_executor(
                    None,
                    runner.run_notebook,
                    notebook_path,
                    session.exec_ns,
                    thread_safe_emit_event,
                    cli_log,
                    target_lines,
                )

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
    socket_path = project_dir / ".nb.sock"
    if socket_path.exists():
        socket_path.unlink()

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    app = web.Application()
    app.router.add_get("/stream", stream_handler)
    app.router.add_get("/notebooks", notebooks_handler)
    app.router.add_get("/", index_handler)
    app.router.add_static("/", STATIC_DIR)

    socket_server = await asyncio.start_unix_server(handle_ipc_client, path=str(socket_path))

    runner_http = web.AppRunner(app)
    await runner_http.setup()
    site = web.TCPSite(runner_http, host, port)
    await site.start()

    site_url = f"http://localhost:{port}"

    print(f"Daemon started. Unix socket at {socket_path}, HTTP at {site_url}", flush=True)

    _task = asyncio.create_task(open_site_in_browser(site_url))

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
