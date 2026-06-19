import asyncio
import json
import shutil
import socket
import tempfile
from pathlib import Path

import aiohttp
import pytest

import nb.daemon as daemon


def unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _run_request(socket_path: Path, req: dict) -> dict:
    """Send a run request and drain the line-delimited reply stream.

    Returns {"terminal": <ok|error msg>, "stdout": str, "stderr": str},
    coalescing the non-terminal stdout/stderr passthrough messages.
    """
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(json.dumps(req).encode("utf-8") + b"\n")
    await writer.drain()

    out, err = "", ""
    terminal: dict = {}
    while True:
        line = await reader.readline()
        if not line:
            break
        msg = json.loads(line.decode("utf-8"))
        status = msg.get("status")
        if status == "stdout":
            out += msg.get("data", "")
        elif status == "stderr":
            err += msg.get("data", "")
        else:  # cache / ok / error are terminal-ish; ok/error end the run
            terminal = msg
            if status in ("ok", "error"):
                break

    writer.close()
    await writer.wait_closed()
    return {"terminal": terminal, "stdout": out, "stderr": err}


@pytest.mark.asyncio
async def test_daemon_lifecycle(tmp_path: Path) -> None:
    project_dir = Path(tempfile.mkdtemp(prefix="nb-test-", dir="/private/tmp"))
    socket_path = project_dir / ".nb.sock"
    port = unused_tcp_port()

    # Mock STATIC_DIR so index_handler can serve from tmp_path
    daemon.STATIC_DIR = tmp_path
    (tmp_path / "index.html").write_text("Hello UI")

    # Start the daemon in a background asyncio task using isolated test paths.
    task = asyncio.create_task(daemon.main(project_dir, host="127.0.0.1", port=port))

    # Wait for the Unix socket to become available
    for _ in range(30):
        if socket_path.exists():
            break
        await asyncio.sleep(0.1)

    assert socket_path.exists()

    # 1. Test HTTP static serving
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{port}/") as resp:
            assert resp.status == 200
            assert await resp.text() == "Hello UI"

    # 2. Test Unix Socket runner IPC — print() is forwarded to the CLI as a
    #    stdout passthrough message, and the run reports ok.
    notebook_path = tmp_path / "notebook.py"
    notebook_path.write_text("# %%\nprint(456)\n")

    result = await _run_request(socket_path, {"path": str(notebook_path)})
    assert result["terminal"]["status"] == "ok"
    assert "456" in result["stdout"]

    # 3. A cell that raises reports error (so `nb run` exits non-zero) and the
    #    full traceback is streamed to the CLI via the stderr channel.
    err_path = tmp_path / "boom.py"
    err_path.write_text("# %%\nraise ValueError('boom')\n")

    result = await _run_request(socket_path, {"path": str(err_path)})
    assert result["terminal"]["status"] == "error"
    assert "ValueError" in result["stderr"]
    assert "boom" in result["stderr"]

    try:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_stream_replays_last_run() -> None:
    """A client that connects after a run receives the buffered run events."""
    daemon.last_run_events.clear()

    # Simulate a completed run's event sequence.
    daemon.emit_event("notebook_header", {"path": "/tmp/nb.py"})
    daemon.emit_event("run_start", {"cell_manifest": [{"id": 0, "title": ""}]})
    daemon.emit_event("run_end", {"status": "ok"})

    # A new run resets the buffer (notebook_header is always first).
    daemon.emit_event("notebook_header", {"path": "/tmp/other.py"})
    daemon.emit_event("run_end", {"status": "ok"})

    replayed = [e["event"] for e in daemon.last_run_events]
    assert replayed == ["notebook_header", "run_end"]
    assert daemon.last_run_events[0]["data"]["path"] == "/tmp/other.py"

    # Buffered events serialize to valid SSE frames.
    frame = daemon._format_sse(daemon.last_run_events[0])
    assert frame.startswith(b"event: notebook_header\ndata: ")
    assert frame.endswith(b"\n\n")
