import asyncio
import importlib
import json
import linecache
import shutil
import socket
import sys
import tempfile
from pathlib import Path

import aiohttp
import pytest

import nb.daemon as daemon
from nb.daemon import CellRecord


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
        daemon.emit_event(
            "cell_start", {"cell_id": cid, "source_line": cid * 3 + 2, "title": title}, path
        )
        daemon.emit_event(
            "display_record", {"cell_id": cid, "type": "object", "payload": payload}, path
        )
        daemon.emit_event(
            "cell_end", {"cell_id": cid, "wall_ms": 1, "cpu_ms": 1, "status": "ok"}, path
        )
    daemon.emit_event("run_end", {"status": "ok"}, path)
    return session


def test_notebook_state_folds_full_then_partial_run() -> None:
    """A full run builds the session's render state; a partial re-run updates
    only its cells, leaving the rest of the notebook untouched."""
    session = _emit_full_run("/tmp/nb.py", [(0, "a", "hello"), (1, "b", 15)])

    cells = session.cells
    assert [c.id for c in cells] == [0, 1]
    assert cells[0].records == [CellRecord(type="object", payload="hello")]
    assert cells[1].records == [CellRecord(type="object", payload=15)]

    # Partial re-run of cell 1 only, producing new output.
    daemon.emit_event(
        "run_start", {"cell_manifest": [{"id": 1, "title": "b"}], "partial": True}, "/tmp/nb.py"
    )
    daemon.emit_event("cell_start", {"cell_id": 1, "source_line": 5, "title": "b"}, "/tmp/nb.py")
    daemon.emit_event(
        "display_record", {"cell_id": 1, "type": "object", "payload": 99}, "/tmp/nb.py"
    )
    daemon.emit_event(
        "cell_end", {"cell_id": 1, "wall_ms": 1, "cpu_ms": 1, "status": "ok"}, "/tmp/nb.py"
    )
    daemon.emit_event("run_end", {"status": "ok"}, "/tmp/nb.py")

    cells = session.cells
    # Cell 0 untouched; cell 1 carries the re-run's output.
    assert cells[0].records == [CellRecord(type="object", payload="hello")]
    assert cells[1].records == [CellRecord(type="object", payload=99)]


@pytest.mark.asyncio
async def test_artifact_handler_serves_only_within_experiments_store(tmp_path: Path) -> None:
    """The artifact route serves files inside the project's experiments store and
    rejects anything outside it (no arbitrary-file reads via a crafted ?file=)."""
    from aiohttp.test_utils import make_mocked_request

    store = tmp_path / ".nb" / "experiments" / "slug" / "run1" / "artifacts"
    store.mkdir(parents=True)
    artifact = store / "model.pt"
    artifact.write_bytes(b"weights")

    secret = tmp_path / "secret.txt"  # outside the experiments store
    secret.write_text("nope")

    old_project = daemon._project_dir
    daemon._project_dir = tmp_path
    try:
        # Missing ?file= → 400.
        resp = await daemon.artifact_handler(make_mocked_request("GET", "/artifact"))
        assert resp.status == 400

        # A path outside the store → 404, even though the file exists.
        import urllib.parse

        q = urllib.parse.quote(str(secret), safe="")
        resp = await daemon.artifact_handler(make_mocked_request("GET", f"/artifact?file={q}"))
        assert resp.status == 404

        # A real file inside the store → served (FileResponse points at it).
        q = urllib.parse.quote(str(artifact), safe="")
        resp = await daemon.artifact_handler(make_mocked_request("GET", f"/artifact?file={q}"))
        assert isinstance(resp, daemon.web.FileResponse)
        assert Path(resp._path).resolve() == artifact.resolve()  # type: ignore[attr-defined]
    finally:
        daemon._project_dir = old_project


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
            daemon.emit_event(
                "display_record", {"cell_id": cid, "type": "object", "payload": payload}, path
            )
            daemon.emit_event(
                "cell_end", {"cell_id": cid, "wall_ms": 1, "cpu_ms": 1, "status": "ok"}, path
            )
        daemon.emit_event("run_end", {"status": "ok"}, path)

    full_run("/tmp/a.py", [(0, "a0", "A0"), (1, "a1", "A1")])
    full_run("/tmp/b.py", [(0, "b0", "B0"), (1, "b1", "B1")])  # B ran most recently

    # Partial re-run of A's cell 1. The events carry A's path, so they must fold
    # into A, not the most-recently-displayed B.
    daemon.emit_event(
        "run_start", {"cell_manifest": [{"id": 1, "title": "a1"}], "partial": True}, "/tmp/a.py"
    )
    daemon.emit_event("cell_start", {"cell_id": 1, "source_line": 5, "title": "a1"}, "/tmp/a.py")
    daemon.emit_event(
        "display_record", {"cell_id": 1, "type": "object", "payload": "A1*"}, "/tmp/a.py"
    )
    daemon.emit_event(
        "cell_end", {"cell_id": 1, "wall_ms": 1, "cpu_ms": 1, "status": "ok"}, "/tmp/a.py"
    )
    daemon.emit_event("run_end", {"status": "ok"}, "/tmp/a.py")

    a_cells = daemon._sessions["/tmp/a.py"].cells
    b_cells = daemon._sessions["/tmp/b.py"].cells
    assert a_cells[1].records == [CellRecord(type="object", payload="A1*")]  # A updated
    assert b_cells[1].records == [CellRecord(type="object", payload="B1")]  # B untouched

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


async def _query_request(socket_path: Path, req: dict) -> dict:
    """Send a `command: query` request and return the single JSON reply."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(json.dumps({"command": "query", **req}).encode("utf-8") + b"\n")
    await writer.drain()
    line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return json.loads(line.decode("utf-8"))


@pytest.mark.asyncio
async def test_query_cells_records_and_exec(tmp_path: Path) -> None:
    """`nb query` exposes a run's saved state: the cell list, a cell's display
    records (small tables/plots inline, large ones spilled to a file), and
    arbitrary code run against the live, persistent namespace."""
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
        import polars as pl

        nb_path = tmp_path / "q.py"
        nb_path.write_text(
            "# %% intro\n"
            'display("hello")\n'
            "# %% data\n"
            "import polars as pl\n"
            'display(pl.DataFrame({"a": [1, 2, 3]}))\n'
            "# %% big\n"
            'display(pl.DataFrame({"n": list(range(5000))}))\n'
            "# %% plot\n"
            "import plotly.graph_objects as go\n"
            "display(go.Figure(go.Scatter(x=list(range(2000)), y=list(range(2000)))))\n"
            "# %% state\n"
            "x = 41\n"
        )
        run = await _run_request(socket_path, {"path": str(nb_path)})
        assert run["terminal"]["status"] == "ok"

        # cells: titles preserved, statuses ok, record counts, and a start line
        # for each (the `# %%` header line).
        cells = await _query_request(socket_path, {"op": "cells", "path": str(nb_path)})
        assert cells["status"] == "ok"
        assert cells["count"] == 5
        by_title = {c["title"]: c for c in cells["cells"]}
        assert set(by_title) == {"intro", "data", "big", "plot", "state"}
        assert by_title["data"]["records"] == 1
        assert by_title["state"]["records"] == 0
        assert all(c["status"] == "ok" for c in cells["cells"])
        assert by_title["intro"]["start_line"] == 1

        # records: the text cell returns its content inline.
        intro_id = by_title["intro"]["id"]
        recs = await _query_request(
            socket_path, {"op": "records", "path": str(nb_path), "cell": intro_id}
        )
        assert recs["status"] == "ok"
        assert recs["records"] == [{"type": "text", "content": "hello"}]

        # records: a small table fits in the preview — schema + full CSV, no file.
        recs = await _query_request(
            socket_path, {"op": "records", "path": str(nb_path), "cell": by_title["data"]["id"]}
        )
        table = recs["records"][0]
        assert table["type"] == "table" and table["rows"] == 3 and "path" not in table
        assert table["schema"] == {"a": "Int64"}
        assert table["preview"] == "a\n1\n2\n3\n"

        # records: a large table still previews inline (head) AND writes the full
        # data to a CSV file — no information cliff.
        recs = await _query_request(
            socket_path, {"op": "records", "path": str(nb_path), "cell": by_title["big"]["id"]}
        )
        big = recs["records"][0]
        assert big["type"] == "table" and big["rows"] == 5000
        assert big["preview"].count("\n") == daemon._TABLE_PREVIEW_ROWS + 1  # header + N rows
        assert big["path"].endswith(".csv")
        assert pl.read_csv(big["path"]).height == 5000  # plain text: header + 5000 rows
        Path(big["path"]).unlink()

        # records: a plot is always spilled to a JSON file holding the figure spec.
        recs = await _query_request(
            socket_path, {"op": "records", "path": str(nb_path), "cell": by_title["plot"]["id"]}
        )
        plot = recs["records"][0]
        assert plot["type"] == "plotly" and "content" not in plot
        assert "data" in json.loads(Path(plot["path"]).read_text())
        Path(plot["path"]).unlink()

        # records: unknown cell id is a clean error listing the valid ids.
        bad = await _query_request(
            socket_path, {"op": "records", "path": str(nb_path), "cell": 999}
        )
        assert bad["status"] == "error" and "Available cells" in bad["message"]

        # exec: runs against the live namespace — sees x = 41, and a mutation
        # persists to the next exec (it is the same kernel).
        out = await _query_request(
            socket_path, {"op": "exec", "path": str(nb_path), "code": "print(x)"}
        )
        assert out["status"] == "ok" and out["stdout"] == "41\n" and out["exception"] is None

        await _query_request(socket_path, {"op": "exec", "path": str(nb_path), "code": "x = 100"})
        out = await _query_request(
            socket_path, {"op": "exec", "path": str(nb_path), "code": "print(x)"}
        )
        assert out["stdout"] == "100\n"

        # exec: display(...) calls are captured into the reply (same rendering as
        # `records` — small table inlined as CSV here) rather than no-oping.
        out = await _query_request(
            socket_path,
            {
                "op": "exec",
                "path": str(nb_path),
                "code": 'display("captured")\ndisplay(pl.DataFrame({"b": [9, 8]}))',
            },
        )
        assert out["records"][0] == {"type": "text", "content": "captured"}
        table = out["records"][1]
        assert table["type"] == "table" and table["rows"] == 2 and "path" not in table
        assert table["schema"] == {"b": "Int64"} and table["preview"] == "b\n9\n8\n"

        # exec: an error is captured as a traceback, not a daemon crash.
        out = await _query_request(
            socket_path, {"op": "exec", "path": str(nb_path), "code": "1 / 0"}
        )
        assert out["exception"] is not None and "ZeroDivisionError" in out["exception"]

        # Every op errors cleanly for a notebook that was never run.
        never = tmp_path / "never.py"
        never.write_text("# %%\npass\n")
        miss = await _query_request(socket_path, {"op": "cells", "path": str(never)})
        assert miss["status"] == "error" and "has not been run" in miss["message"]
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


def test_pinning_loader_survives_disk_edit(tmp_path: Path) -> None:
    # The loader pins source at load time, so a file edited afterward (without a
    # re-import) still resolves to the code that actually ran, not the disk contents.
    mod_file = tmp_path / "pin_loader_mod.py"
    mod_file.write_text("def boom():\n    raise ValueError('original')\n")
    f = str(mod_file)
    try:
        daemon._PinningLoader("pin_loader_mod", f).get_code("pin_loader_mod")
        assert daemon._is_frozen_entry(linecache.cache.get(f))

        # Edit on disk with shifted line numbers (as a mid-run edit would).
        mod_file.write_text("# added\n# added 2\ndef boom():\n    raise ValueError('EDITED')\n")
        linecache.checkcache(f)
        assert "original" in linecache.getline(f, 2)  # pinned line, not the edited disk line
        assert "EDITED" not in linecache.getline(f, 2)
    finally:
        linecache.cache.pop(f, None)


def test_pin_finder_wraps_only_user_modules(tmp_path: Path) -> None:
    mod_file = tmp_path / "pin_finder_user_mod.py"
    mod_file.write_text("X = 1\n")
    sys.path.insert(0, str(tmp_path))
    finder = daemon._PinningFinder()
    try:
        # A local module (not under a package prefix) gets the pinning loader.
        user_spec = finder.find_spec("pin_finder_user_mod", None)
        assert user_spec is not None
        assert isinstance(user_spec.loader, daemon._PinningLoader)

        # A stdlib module lives under a package prefix and keeps its stock loader.
        std_spec = finder.find_spec("textwrap", None)
        assert std_spec is not None
        assert not isinstance(std_spec.loader, daemon._PinningLoader)
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))


def test_source_pin_survives_pyc_load(tmp_path: Path) -> None:
    # The gap the audit hook couldn't close: a module re-loaded from a fresh .pyc runs
    # no compile, yet the loader reads the .py itself, so it still pins the source.
    mod_name = "nb_pin_pyc_mod"
    mod_file = tmp_path / f"{mod_name}.py"
    mod_file.write_text("def boom():\n    raise ValueError('RAN')\n")
    f = str(mod_file)
    sys.path.insert(0, str(tmp_path))
    finder = daemon._PinningFinder()
    sys.meta_path.insert(0, finder)
    try:
        importlib.import_module(mod_name)  # compiles, writes .pyc, pins
        # Simulate --clear-imports WITHOUT editing: the fresh .pyc is reused on reimport.
        sys.modules.pop(mod_name, None)
        linecache.cache.pop(f, None)
        importlib.import_module(mod_name)  # loads .pyc (no compile), loader still pins
        assert daemon._is_frozen_entry(linecache.cache.get(f))
    finally:
        sys.meta_path.remove(finder)
        importlib.invalidate_caches()
        sys.modules.pop(mod_name, None)
        linecache.cache.pop(f, None)
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))


def test_stale_user_modules_detects_disk_drift(tmp_path: Path) -> None:
    mod_name = "nb_drift_helper_mod"
    mod_file = tmp_path / f"{mod_name}.py"
    mod_file.write_text("VALUE = 1\n")
    f = str(mod_file)
    sys.path.insert(0, str(tmp_path))
    finder = daemon._PinningFinder()
    sys.meta_path.insert(0, finder)
    try:
        importlib.import_module(mod_name)  # pins at import
        assert (mod_name, f) in list(daemon._iter_user_modules())

        # Unedited: disk matches the pinned source, so no drift is reported.
        assert all(name != mod_name for name, _ in daemon._stale_user_modules())

        # Edit on disk without re-importing: the pinned source now diverges.
        mod_file.write_text("VALUE = 2\n")
        assert (mod_name, f) in daemon._stale_user_modules()

        # Simulate --clear-imports (drop module + pinned entry); with no baseline
        # there is nothing to compare against, so no stale warning is produced.
        sys.modules.pop(mod_name, None)
        linecache.cache.pop(f, None)
        assert all(name != mod_name for name, _ in daemon._stale_user_modules())
    finally:
        sys.meta_path.remove(finder)
        importlib.invalidate_caches()
        sys.modules.pop(mod_name, None)
        linecache.cache.pop(f, None)
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
