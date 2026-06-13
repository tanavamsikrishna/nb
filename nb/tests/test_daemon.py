import pytest
import asyncio
import json
import socket
import shutil
import tempfile
import aiohttp
from pathlib import Path
import nb.daemon as daemon

def unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

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

    # 2. Test Unix Socket runner IPC
    notebook_path = tmp_path / "notebook.py"
    notebook_path.write_text("# %%\nprint(456)\n")

    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    req = {"path": str(notebook_path)}
    writer.write(json.dumps(req).encode('utf-8') + b"\n")
    await writer.drain()

    line = await reader.readline()
    resp = json.loads(line.decode('utf-8'))
    assert resp["status"] == "ok"

    writer.close()
    await writer.wait_closed()

    try:
        # Stop the daemon task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)
