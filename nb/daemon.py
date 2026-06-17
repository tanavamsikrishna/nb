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

# Global set of active SSE client queues
active_clients: Set[asyncio.Queue] = set()
run_lock = asyncio.Lock()


def emit_event(event_type: str, event_data: dict) -> None:
    event = {"event": event_type, "data": event_data}
    for queue in list(active_clients):
        queue.put_nowait(event)


async def stream_handler(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["Access-Control-Allow-Origin"] = "*"
    await response.prepare(request)

    queue = asyncio.Queue()
    active_clients.add(queue)
    try:
        while True:
            event = await queue.get()
            event_type = event["event"]
            data_str = json.dumps(event["data"])
            msg = f"event: {event_type}\ndata: {data_str}\n\n"
            await response.write(msg.encode("utf-8"))
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
            text="UI build not found. Please run `nb build-ui` first to compile and install the frontend.",
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

            loop = asyncio.get_running_loop()

            # Callback for capture in display primitives
            def active_emitter(record: fw.DisplayRecord) -> None:
                event_data = {
                    "cell_id": fw._current_cell_id,
                    "type": record.type,
                    "payload": record.payload,
                }
                # Display primitives are executed in thread, call_soon_threadsafe is required
                loop.call_soon_threadsafe(emit_event, "display_record", event_data)

            # Store original emitter
            old_emitter = fw._active_emitter
            fw._active_emitter = active_emitter

            def thread_safe_emit_event(event_type: str, event_data: dict) -> None:
                loop.call_soon_threadsafe(emit_event, event_type, event_data)

            try:
                # Pre-populate execution namespace with framework builtins
                exec_ns = {
                    "__name__": "__main__",
                    "__builtins__": __builtins__,
                    "display": fw.display,
                    "nb_cache": fw.nb_cache,
                    "clear_cache": fw.clear_cache,
                }

                # Execute notebook in separate thread so exec doesn't block the main event loop
                await loop.run_in_executor(
                    None, runner.run_notebook, notebook_path, exec_ns, thread_safe_emit_event
                )

                resp = {"status": "ok"}
                writer.write(json.dumps(resp).encode("utf-8") + b"\n")
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


async def open_site_in_browser(site_url):
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

    # Ensure static directory structure exists
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize aiohttp Application
    app = web.Application()
    app.router.add_get("/stream", stream_handler)
    app.router.add_get("/", index_handler)
    app.router.add_static("/", STATIC_DIR)

    # Start Unix Socket Server
    socket_server = await asyncio.start_unix_server(handle_ipc_client, path=str(socket_path))

    # Start HTTP Server on port 7777
    runner_http = web.AppRunner(app)
    await runner_http.setup()
    site = web.TCPSite(runner_http, host, port)
    await site.start()

    site_url = f"http://localhost:{port}"

    print(f"Daemon started. Unix socket at {socket_path}, HTTP at {site_url}", flush=True)

    _task = asyncio.create_task(open_site_in_browser(site_url))

    # Graceful shutdown event — triggered by SIGINT/SIGTERM
    # First signal: graceful shutdown. Second signal: force exit.
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
