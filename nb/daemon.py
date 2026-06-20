import asyncio
import json
import os
import re
import signal
import webbrowser
from pathlib import Path
from typing import Set

from aiohttp import web

import nb.framework as fw
from nb import runner

active_clients: Set[asyncio.Queue] = set()
run_lock = asyncio.Lock()

# Persistent exec namespaces, keyed by resolved notebook path. A full `nb run`
# stores a fresh namespace here before executing; a partial re-run (`nb run
# file.py:42`) reuses it so the targeted cells see the state the last full run
# left behind. Lives in the daemon's long-lived process (like `fw._cache`), not
# the per-run exec scope, so it survives across runs.
_exec_namespaces: dict[str, dict] = {}

# Authoritative render state of the notebook — what a freshly-connected browser
# tab must display, not a log of past events. State-bearing events fold into
# this (see `_fold_state`); transient events (run_end, future scroll/toast) only
# fan out live. A new client gets a snapshot regenerated from this state
# (`_snapshot_events`), so partial re-runs need no event-log splicing.
notebook_state: dict = {"path": None, "docstring": None, "cells": []}


def _state_find_cell(cell_id: int) -> dict | None:
    for cell in notebook_state["cells"]:
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


def _fold_state(event_type: str, data: dict) -> None:
    """Update `notebook_state` from a state-bearing event. No-op for transient
    events (run_end and any future scroll/toast/collapse), which are live-only."""
    if event_type == "notebook_header":
        notebook_state["path"] = data.get("path")
        notebook_state["docstring"] = data.get("docstring")
    elif event_type == "run_start":
        manifest = data.get("cell_manifest", [])
        if data.get("partial"):
            # Mark only the targeted cells stale/pending; leave the rest exactly
            # as they are (their output stays visible across the partial re-run).
            for item in manifest:
                cell = _state_find_cell(item["id"])
                if cell is None:
                    cell = _new_cell_state(item["id"], item.get("title"))
                    notebook_state["cells"].append(cell)
                cell["title"] = item.get("title", cell["title"])
                cell["stale"] = True
                cell["status"] = "pending"
            notebook_state["cells"].sort(key=lambda c: c["id"])
        else:
            # Full run: rebuild the cell list to the manifest, preserving the
            # records of surviving ids and dropping absent ones (mirrors the
            # frontend reconcile + finalizeRun, resolved immediately).
            existing = {c["id"]: c for c in notebook_state["cells"]}
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
            notebook_state["cells"] = rebuilt
    elif event_type == "cell_start":
        cell = _state_find_cell(data["cell_id"])
        if cell is None:
            cell = _new_cell_state(data["cell_id"], data.get("title"))
            notebook_state["cells"].append(cell)
            notebook_state["cells"].sort(key=lambda c: c["id"])
        cell["status"] = "running"
        cell["stale"] = False
        cell["title"] = data.get("title", cell["title"])
        cell["source_line"] = data.get("source_line", cell["source_line"])
        cell["profiling"] = None
        cell["records"] = []  # fresh records buffer; display_records append below
    elif event_type == "display_record":
        cell = _state_find_cell(data["cell_id"])
        if cell is not None:
            cell["records"].append({"type": data["type"], "payload": data["payload"]})
    elif event_type == "cell_end":
        cell = _state_find_cell(data["cell_id"])
        if cell is not None:
            cell["status"] = data.get("status")
            cell["profiling"] = {"wall_ms": data.get("wall_ms"), "cpu_ms": data.get("cpu_ms")}


def _snapshot_events() -> list[dict]:
    """Regenerate the canonical event sequence that reproduces `notebook_state`
    in a freshly-connected client. The frontend's live-event handlers hydrate the
    store identically, so there is a single renderer path (live or snapshot)."""
    if notebook_state["path"] is None and not notebook_state["cells"]:
        return []

    events: list[dict] = []
    header: dict = {"path": notebook_state["path"]}
    if notebook_state["docstring"] is not None:
        header["docstring"] = notebook_state["docstring"]
    events.append({"event": "notebook_header", "data": header})

    manifest = [{"id": c["id"], "title": c["title"] or ""} for c in notebook_state["cells"]]
    events.append({"event": "run_start", "data": {"cell_manifest": manifest, "partial": False}})

    for cell in notebook_state["cells"]:
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
    return events


def emit_event(event_type: str, event_data: dict) -> None:
    event = {"event": event_type, "data": event_data}
    # Fold state-bearing events into notebook_state; transient ones are no-ops
    # there (live fan-out below still delivers them to connected clients).
    _fold_state(event_type, event_data)
    for queue in list(active_clients):
        queue.put_nowait(event)


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

    # Snapshot current notebook state and subscribe with no await in between, so
    # the single-threaded event loop can't slip a live event past us: anything
    # emitted after this point lands on the queue, never duplicating the
    # snapshot. (emit_event also runs on this loop thread.)
    buffered = _snapshot_events()
    queue = asyncio.Queue()
    active_clients.add(queue)
    try:
        for event in buffered:
            await response.write(_format_sse(event))
        while True:
            event = await queue.get()
            await response.write(_format_sse(event))
    except asyncio.CancelledError:
        pass
    finally:
        active_clients.remove(queue)
    return response


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
                loop.call_soon_threadsafe(emit_event, "display_record", event_data)

            old_emitter = fw._active_emitter
            fw._active_emitter = active_emitter

            def thread_safe_emit_event(event_type: str, event_data: dict) -> None:
                loop.call_soon_threadsafe(emit_event, event_type, event_data)

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

                # Resolve the namespace and run mode. A partial re-run reuses the
                # namespace the last full run saved; if none exists (daemon just
                # started, or this notebook hasn't run yet), fall back to a full
                # run, which seeds it — so the command always works.
                ns_key = str(notebook_path)
                target_lines: tuple[int, int] | None = None
                if lines is not None and ns_key in _exec_namespaces:
                    exec_ns = _exec_namespaces[ns_key]
                    target_lines = (int(lines[0]), int(lines[1]))
                else:
                    if lines is not None:
                        cli_log("stdout", "No saved state for this notebook; running it in full.\n")
                    exec_ns = {
                        "__name__": "__main__",
                        "__builtins__": __builtins__,
                        "display": fw.display,
                        "nb_cache": fw.nb_cache,
                    }
                    _exec_namespaces[ns_key] = exec_ns

                # Execute notebook in separate thread so exec doesn't block the main event loop
                errored = await loop.run_in_executor(
                    None,
                    runner.run_notebook,
                    notebook_path,
                    exec_ns,
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
