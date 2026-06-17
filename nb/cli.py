import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import click

from nb import daemon

NOTEBOOK_URL = "http://localhost:7777"


def _functions(n: int) -> str:
    return "function" if n == 1 else "functions"


@click.group()
def main() -> None:
    pass


@main.command()
@click.argument("notebook", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--clear-cache",
    "clear_cache",
    default=None,
    metavar="NAMES",
    help="Comma-separated function names whose @nb_cache entries to clear before running "
    "(matches the short name or qualname).",
)
@click.option(
    "--clear-cache-all",
    "clear_cache_all",
    is_flag=True,
    default=False,
    help="Clear the entire @nb_cache before running.",
)
def run(notebook: Path, clear_cache: str | None, clear_cache_all: bool) -> None:
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
    if clear_cache_all and clear_cache is not None:
        click.echo("Use either --clear-cache or --clear-cache-all, not both.", err=True)
        sys.exit(1)

    req: dict = {"path": str(notebook_path)}
    if clear_cache_all:
        req["clear_cache_all"] = True
    elif clear_cache is not None:
        names = [n.strip() for n in clear_cache.split(",") if n.strip()]
        if not names:
            click.echo("--clear-cache needs one or more function names.", err=True)
            sys.exit(1)
        req["clear_cache"] = names

    try:
        s.sendall(json.dumps(req).encode("utf-8") + b"\n")
        # The daemon clears caches up-front and reports it on a "cache" message that
        # arrives before the run finishes; the run then ends with an "ok"/"error"
        # message. Read line-delimited messages until a terminal one arrives.
        reader = s.makefile("r", encoding="utf-8")
        while True:
            line = reader.readline()
            if not line:
                click.echo("Daemon closed connection without response.", err=True)
                sys.exit(1)
            msg = json.loads(line)
            status = msg.get("status")
            if status == "cache":
                _report_cache(msg.get("cache") or {})
                continue
            if status == "ok":
                click.echo(
                    f"Notebook execution requested successfully. View output at {NOTEBOOK_URL}"
                )
                break
            click.echo(f"Execution failed: {msg.get('message')}", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error communicating with daemon: {e}", err=True)
        sys.exit(1)
    finally:
        s.close()


def _report_cache(cache: dict) -> None:
    n = cache.get("functions", 0)
    if cache.get("all"):
        click.echo(f"Cleared entire cache ({n} {_functions(n)}).")
    else:
        click.echo(f"Cleared {n} cached {_functions(n)}.")
    unmatched = cache.get("unmatched") or []
    if unmatched:
        click.echo(f"Warning: no cached function matched: {', '.join(unmatched)}", err=True)


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
