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

# Buffer of the most recent run's events, replayed to clients that connect (or
# refresh) after the run. Without it, a freshly-opened browser shows a blank
# page until the next run, since /stream is otherwise live-only. Reset at the
# start of each run ("notebook_header" is always the first event runner emits).
last_run_events: list[dict] = []


def emit_event(event_type: str, event_data: dict) -> None:
    event = {"event": event_type, "data": event_data}
    if event_type == "notebook_header":
        last_run_events.clear()
    last_run_events.append(event)
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

    # Snapshot the last run and subscribe with no await in between, so the
    # single-threaded event loop can't slip a live event past us: anything
    # emitted after this point lands on the queue, never duplicating the
    # snapshot. (emit_event also runs on this loop thread.)
    buffered = list(last_run_events)
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

                exec_ns = {
                    "__name__": "__main__",
                    "__builtins__": __builtins__,
                    "display": fw.display,
                    "nb_cache": fw.nb_cache,
                }

                # Execute notebook in separate thread so exec doesn't block the main event loop
                errored = await loop.run_in_executor(
                    None,
                    runner.run_notebook,
                    notebook_path,
                    exec_ns,
                    thread_safe_emit_event,
                    cli_log,
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
