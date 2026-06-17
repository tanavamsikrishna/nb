import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import click

from nb import daemon

NOTEBOOK_URL = "http://localhost:7777"


@click.group()
def main() -> None:
    pass


@main.command()
@click.argument("notebook", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def run(notebook: Path) -> None:
    notebook_path = notebook.resolve()
    project_dir = Path.cwd()
    socket_path = project_dir / ".nb.sock"

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    if socket_path.exists():
        try:
            s.connect(str(socket_path))
        except (socket.error, ConnectionRefusedError):
            # Clean up stale socket file
            try:
                socket_path.unlink()
            except Exception:
                pass
            click.echo("Could not connect to daemon. Is it running?", err=True)
            sys.exit(1)

    # Request notebook run
    req = {"path": str(notebook_path)}
    print(f"Requesting notebook run with params: {req}")
    try:
        s.sendall(json.dumps(req).encode("utf-8") + b"\n")
        resp_data = s.recv(4096)
        if not resp_data:
            click.echo("Daemon closed connection without response.", err=True)
            sys.exit(1)
        resp = json.loads(resp_data.decode("utf-8").strip())
        if resp.get("status") == "ok":
            click.echo(f"Notebook execution requested successfully. View output at {NOTEBOOK_URL}")
        else:
            click.echo(f"Execution failed: {resp.get('message')}", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error communicating with daemon: {e}", err=True)
        sys.exit(1)
    finally:
        s.close()


@main.command("daemon")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def start_daemon(project_dir: Path) -> None:
    daemon.start_daemon(project_dir.resolve())


@main.command()
def build_ui() -> None:
    repo_dir = Path(__file__).parent.parent.resolve()
    ui_dir = repo_dir / "nb-ui"
    static_dir = repo_dir / "nb" / "static"

    if not ui_dir.exists():
        click.echo(f"Frontend directory not found at {ui_dir}", err=True)
        sys.exit(1)

    click.echo("Building Svelte UI...")

    # Run pnpm install if node_modules doesn't exist
    node_modules = ui_dir / "node_modules"
    if not node_modules.exists():
        click.echo("Running pnpm install...")
        res = subprocess.run(["pnpm", "install"], cwd=str(ui_dir))
        if res.returncode != 0:
            click.echo("pnpm install failed", err=True)
            sys.exit(1)

    res = subprocess.run(["pnpm", "build"], cwd=str(ui_dir))
    if res.returncode != 0:
        click.echo("pnpm build failed", err=True)
        sys.exit(1)

    click.echo(f"Copying build artifacts to {static_dir}...")
    dist_dir = ui_dir / "dist"
    if static_dir.exists():
        shutil.rmtree(static_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dist_dir, static_dir, dirs_exist_ok=True)
    click.echo("Build complete!")


if __name__ == "__main__":
    main()
