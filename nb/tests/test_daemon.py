import asyncio
import json
import shutil
import socket
import tempfile
from pathlib import Path

import aiohttp
import pytest

import nb.daemon as daemon


def _snapshot_payloads(session) -> list:
    """display_record payloads in a session's regenerated snapshot, in order."""
    return [
        e["data"]["payload"]
        for e in daemon._snapshot_events(session)
        if e["event"] == "display_record"
    ]


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


def _activate_session(path: str) -> "daemon.NotebookSession":
    """Reset the session registry and register a session for `path`, so
    emit_event(..., path) can fold into it (the daemon creates it at run start)."""
    daemon._sessions.clear()
    session = daemon.NotebookSession(path=path)
    daemon._sessions[path] = session
    return session


def _emit_full_run(path: str, cells: list[tuple[int, str, object]]) -> "daemon.NotebookSession":
    """Activate a session for `path` and drive emit_event through a full run.
    Each cell is (id, title, payload). Returns the session."""
    session = _activate_session(path)
    daemon.emit_event("notebook_header", {"path": path}, path)
    manifest = [{"id": cid, "title": title} for cid, title, _ in cells]
    daemon.emit_event("run_start", {"cell_manifest": manifest}, path)
    for cid, title, payload in cells:
        daemon.emit_event("cell_start", {"cell_id": cid, "source_line": cid * 3 + 2, "title": title}, path)
        daemon.emit_event("display_record", {"cell_id": cid, "type": "object", "payload": payload}, path)
        daemon.emit_event("cell_end", {"cell_id": cid, "wall_ms": 1, "cpu_ms": 1, "status": "ok"}, path)
    daemon.emit_event("run_end", {"status": "ok"}, path)
    return session


def test_notebook_state_folds_full_then_partial_run() -> None:
    """A full run builds the session's render state; a partial re-run updates
    only its cells, leaving the rest of the notebook untouched."""
    session = _emit_full_run("/tmp/nb.py", [(0, "a", "hello"), (1, "b", 15)])

    cells = session.cells
    assert [c["id"] for c in cells] == [0, 1]
    assert cells[0]["records"] == [{"type": "object", "payload": "hello"}]
    assert cells[1]["records"] == [{"type": "object", "payload": 15}]

    # Partial re-run of cell 1 only, producing new output.
    daemon.emit_event("run_start", {"cell_manifest": [{"id": 1, "title": "b"}], "partial": True}, "/tmp/nb.py")
    daemon.emit_event("cell_start", {"cell_id": 1, "source_line": 5, "title": "b"}, "/tmp/nb.py")
    daemon.emit_event("display_record", {"cell_id": 1, "type": "object", "payload": 99}, "/tmp/nb.py")
    daemon.emit_event("cell_end", {"cell_id": 1, "wall_ms": 1, "cpu_ms": 1, "status": "ok"}, "/tmp/nb.py")
    daemon.emit_event("run_end", {"status": "ok"}, "/tmp/nb.py")

    cells = session.cells
    # Cell 0 untouched; cell 1 carries the re-run's output.
    assert cells[0]["records"] == [{"type": "object", "payload": "hello"}]
    assert cells[1]["records"] == [{"type": "object", "payload": 99}]


def test_snapshot_reproduces_state_without_transient_events() -> None:
    """The regenerated snapshot rebuilds the active session's state. Transient
    events are never folded into stored state (covered by the folding test), but
    the snapshot still emits the single terminal run_end so a reconnecting client
    settles to idle the same way a completed live run does."""
    session = _emit_full_run("/tmp/nb.py", [(0, "a", "hello"), (1, "b", 15)])

    snapshot = daemon._snapshot_events(session)
    types = [e["event"] for e in snapshot]

    # A clean canonical sequence: header, a full run_start, then per-cell spans.
    assert types[0] == "notebook_header"
    assert types[1] == "run_start"
    assert snapshot[1]["data"]["partial"] is False
    assert [item["id"] for item in snapshot[1]["data"]["cell_manifest"]] == [0, 1]
    # Exactly one terminal run_end, closing the sequence so the client goes idle.
    assert types[-1] == "run_end"
    assert types.count("run_end") == 1

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


def test_live_events_scoped_to_subscribed_path() -> None:
    """A /stream client only receives live events for the notebook it subscribed
    to; a run of another notebook never reaches it, and a path-less client (no
    `?path=`) is bound to nothing and receives no events. Routing is by the path
    passed to emit_event, not by any global."""
    daemon._sessions.clear()
    daemon.active_clients.clear()

    a = daemon.Client(queue=asyncio.Queue(), path="/tmp/a.py")
    b = daemon.Client(queue=asyncio.Queue(), path="/tmp/b.py")
    pathless = daemon.Client(queue=asyncio.Queue(), path=None)
    daemon.active_clients.update({a, b, pathless})

    try:
        # Emit an event for notebook A (the running notebook).
        daemon.emit_event("run_start", {"cell_manifest": [], "partial": False}, "/tmp/a.py")

        assert not a.queue.empty()  # A's tab gets A's event
        assert b.queue.empty()  # B's tab is undisturbed by A's run
        assert pathless.queue.empty()  # path-less is bound to nothing
    finally:
        daemon.active_clients.clear()
        daemon._sessions.clear()


def test_partial_run_folds_into_its_own_session_not_the_active_one() -> None:
    """A partial re-run of notebook A folds into A's render state even when B is
    the notebook last fully run. Folding follows the path passed to emit_event,
    which is what prevents one notebook's re-run from corrupting another's
    displayed output."""
    daemon._sessions.clear()

    def full_run(path: str, cells: list[tuple[int, str, object]]) -> None:
        daemon._sessions[path] = daemon.NotebookSession(path=path)
        manifest = [{"id": cid, "title": t} for cid, t, _ in cells]
        daemon.emit_event("notebook_header", {"path": path}, path)
        daemon.emit_event("run_start", {"cell_manifest": manifest}, path)
        for cid, t, payload in cells:
            daemon.emit_event("cell_start", {"cell_id": cid, "source_line": 2, "title": t}, path)
            daemon.emit_event("display_record", {"cell_id": cid, "type": "object", "payload": payload}, path)
            daemon.emit_event("cell_end", {"cell_id": cid, "wall_ms": 1, "cpu_ms": 1, "status": "ok"}, path)
        daemon.emit_event("run_end", {"status": "ok"}, path)

    full_run("/tmp/a.py", [(0, "a0", "A0"), (1, "a1", "A1")])
    full_run("/tmp/b.py", [(0, "b0", "B0"), (1, "b1", "B1")])  # B ran most recently

    # Partial re-run of A's cell 1. The events carry A's path, so they must fold
    # into A, not the most-recently-displayed B.
    daemon.emit_event("run_start", {"cell_manifest": [{"id": 1, "title": "a1"}], "partial": True}, "/tmp/a.py")
    daemon.emit_event("cell_start", {"cell_id": 1, "source_line": 5, "title": "a1"}, "/tmp/a.py")
    daemon.emit_event("display_record", {"cell_id": 1, "type": "object", "payload": "A1*"}, "/tmp/a.py")
    daemon.emit_event("cell_end", {"cell_id": 1, "wall_ms": 1, "cpu_ms": 1, "status": "ok"}, "/tmp/a.py")
    daemon.emit_event("run_end", {"status": "ok"}, "/tmp/a.py")

    a_cells = daemon._sessions["/tmp/a.py"].cells
    b_cells = daemon._sessions["/tmp/b.py"].cells
    assert a_cells[1]["records"] == [{"type": "object", "payload": "A1*"}]  # A updated
    assert b_cells[1]["records"] == [{"type": "object", "payload": "B1"}]  # B untouched

    # B's snapshot is unaffected by A's partial re-run.
    b_payloads = {
        e["data"]["cell_id"]: e["data"]["payload"]
        for e in daemon._snapshot_events(daemon._sessions["/tmp/b.py"])
        if e["event"] == "display_record"
    }
    assert b_payloads == {0: "B0", 1: "B1"}


@pytest.mark.asyncio
async def test_partial_rerun_reuses_saved_namespace(tmp_path: Path) -> None:
    """`nb run file.py:LINE` re-runs one cell against the namespace the prior
    full run saved; with no saved namespace it falls back to a full run."""
    project_dir = Path(tempfile.mkdtemp(prefix="nb-test-", dir="/private/tmp"))
    socket_path = project_dir / ".nb.sock"
    port = unused_tcp_port()
    daemon.STATIC_DIR = tmp_path
    daemon._sessions.clear()

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


@pytest.mark.asyncio
async def test_notebooks_listing_and_path_scoped_stream(tmp_path: Path) -> None:
    """`/notebooks` lists every notebook with a session; `/stream?path=` serves
    that notebook's snapshot, and a path-less stream has no notebook to serve."""
    project_dir = Path(tempfile.mkdtemp(prefix="nb-test-", dir="/private/tmp"))
    socket_path = project_dir / ".nb.sock"
    port = unused_tcp_port()
    daemon.STATIC_DIR = tmp_path
    daemon._sessions.clear()

    task = asyncio.create_task(daemon.main(project_dir, host="127.0.0.1", port=port))
    for _ in range(30):
        if socket_path.exists():
            break
        await asyncio.sleep(0.1)
    assert socket_path.exists()

    try:
        a_path = tmp_path / "a.py"
        a_path.write_text("# %%\ndisplay(111)\n")
        b_path = tmp_path / "b.py"
        b_path.write_text("# %%\ndisplay(222)\n")

        await _run_request(socket_path, {"path": str(a_path)})
        await _run_request(socket_path, {"path": str(b_path)})

        # /notebooks lists both notebooks the daemon has run.
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/notebooks") as resp:
                assert resp.status == 200
                data = await resp.json()
        by_path = {nb["path"]: nb for nb in data["notebooks"]}
        assert str(a_path) in by_path and str(b_path) in by_path
        assert by_path[str(a_path)]["name"] == "a.py"

        # Each /stream client is served its own notebook's snapshot.
        assert _snapshot_payloads(daemon._session_for_stream(str(a_path))) == [111]
        assert _snapshot_payloads(daemon._session_for_stream(str(b_path))) == [222]
        # A path-less stream has no notebook to serve (the `/` index is the
        # path-less surface); an unknown path likewise yields no session.
        assert daemon._session_for_stream(None) is None
        assert daemon._session_for_stream(str(tmp_path / "missing.py")) is None
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        shutil.rmtree(project_dir, ignore_errors=True)
