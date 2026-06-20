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


def _reset_notebook_state() -> None:
    daemon.notebook_state = {"path": None, "docstring": None, "cells": []}


def _emit_full_run(path: str, cells: list[tuple[int, str, object]]) -> None:
    """Drive emit_event through a full run: each cell is (id, title, payload)."""
    daemon.emit_event("notebook_header", {"path": path})
    manifest = [{"id": cid, "title": title} for cid, title, _ in cells]
    daemon.emit_event("run_start", {"cell_manifest": manifest})
    for cid, title, payload in cells:
        daemon.emit_event("cell_start", {"cell_id": cid, "source_line": cid * 3 + 2, "title": title})
        daemon.emit_event("display_record", {"cell_id": cid, "type": "object", "payload": payload})
        daemon.emit_event("cell_end", {"cell_id": cid, "wall_ms": 1, "cpu_ms": 1, "status": "ok"})
    daemon.emit_event("run_end", {"status": "ok"})


def test_notebook_state_folds_full_then_partial_run() -> None:
    """A full run builds notebook_state; a partial re-run updates only its cells."""
    _reset_notebook_state()
    _emit_full_run("/tmp/nb.py", [(0, "a", "hello"), (1, "b", 15)])

    cells = daemon.notebook_state["cells"]
    assert [c["id"] for c in cells] == [0, 1]
    assert cells[0]["records"] == [{"type": "object", "payload": "hello"}]
    assert cells[1]["records"] == [{"type": "object", "payload": 15}]

    # Partial re-run of cell 1 only, producing new output.
    daemon.emit_event("run_start", {"cell_manifest": [{"id": 1, "title": "b"}], "partial": True})
    daemon.emit_event("cell_start", {"cell_id": 1, "source_line": 5, "title": "b"})
    daemon.emit_event("display_record", {"cell_id": 1, "type": "object", "payload": 99})
    daemon.emit_event("cell_end", {"cell_id": 1, "wall_ms": 1, "cpu_ms": 1, "status": "ok"})
    daemon.emit_event("run_end", {"status": "ok"})

    cells = daemon.notebook_state["cells"]
    # Cell 0 untouched; cell 1 carries the re-run's output.
    assert cells[0]["records"] == [{"type": "object", "payload": "hello"}]
    assert cells[1]["records"] == [{"type": "object", "payload": 99}]


def test_snapshot_reproduces_state_without_transient_events() -> None:
    """The regenerated snapshot rebuilds the current state and omits transient
    events (run_end), which are live-only and must not replay to a new tab."""
    _reset_notebook_state()
    _emit_full_run("/tmp/nb.py", [(0, "a", "hello"), (1, "b", 15)])

    snapshot = daemon._snapshot_events()
    types = [e["event"] for e in snapshot]

    # A clean canonical sequence: header, a full run_start, then per-cell spans.
    assert types[0] == "notebook_header"
    assert types[1] == "run_start"
    assert snapshot[1]["data"]["partial"] is False
    assert [item["id"] for item in snapshot[1]["data"]["cell_manifest"]] == [0, 1]
    # No transient events are buffered into the snapshot.
    assert "run_end" not in types

    # Replaying reproduces each cell's latest records.
    payloads = {
        e["data"]["cell_id"]: e["data"]["payload"]
        for e in snapshot
        if e["event"] == "display_record"
    }
    assert payloads == {0: "hello", 1: 15}

    # Snapshot events serialize to valid SSE frames.
    frame = daemon._format_sse(snapshot[0])
    assert frame.startswith(b"event: notebook_header\ndata: ")
    assert frame.endswith(b"\n\n")


@pytest.mark.asyncio
async def test_partial_rerun_reuses_saved_namespace(tmp_path: Path) -> None:
    """`nb run file.py:LINE` re-runs one cell against the namespace the prior
    full run saved; with no saved namespace it falls back to a full run."""
    project_dir = Path(tempfile.mkdtemp(prefix="nb-test-", dir="/private/tmp"))
    socket_path = project_dir / ".nb.sock"
    port = unused_tcp_port()
    daemon.STATIC_DIR = tmp_path
    daemon._exec_namespaces.clear()

    task = asyncio.create_task(daemon.main(project_dir, host="127.0.0.1", port=port))
    for _ in range(30):
        if socket_path.exists():
            break
        await asyncio.sleep(0.1)
    assert socket_path.exists()

    try:
        nb_path = tmp_path / "stateful.py"
        nb_path.write_text("# %% a\nx = 41\n# %% b\nprint(x + 1)\n")

        # Full run seeds the namespace (x = 41) and prints 42.
        result = await _run_request(socket_path, {"path": str(nb_path)})
        assert result["terminal"]["status"] == "ok"
        assert "42" in result["stdout"]

        # Edit the file so cell `a` would set x = 999 — but a partial re-run of
        # cell `b` (line 4) must NOT re-run `a`; it reads the saved x = 41.
        nb_path.write_text("# %% a\nx = 999\n# %% b\nprint(x + 100)\n")
        result = await _run_request(socket_path, {"path": str(nb_path), "lines": [4, 4]})
        assert result["terminal"]["status"] == "ok"
        assert "141" in result["stdout"]  # 41 (saved) + 100, not 999 + 100
        assert "1099" not in result["stdout"]

        # A notebook never run this session falls back to a full run.
        fresh = tmp_path / "fresh.py"
        fresh.write_text("# %% a\nx = 7\nprint(x)\n")
        result = await _run_request(socket_path, {"path": str(fresh), "lines": [2, 2]})
        assert result["terminal"]["status"] == "ok"
        assert "No saved state" in result["stdout"]
        assert "7" in result["stdout"]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        shutil.rmtree(project_dir, ignore_errors=True)
