import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import click

from nb import daemon

NOTEBOOK_URL = "http://localhost:7777"

# How often `--watch` polls the notebook's mtime for changes.
WATCH_POLL_SECONDS = 0.3


def _functions(n: int) -> str:
    return "function" if n == 1 else "functions"


class _DaemonUnavailable(Exception):
    """Raised when the daemon socket can't be reached."""


def _send_run(socket_path: Path, req: dict) -> bool:
    """Send one run request and print the daemon's reply.

    Returns True if the notebook ran successfully, False on an execution error.
    Raises _DaemonUnavailable if the daemon socket can't be reached.
    """
    if not socket_path.exists():
        raise _DaemonUnavailable()

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(str(socket_path))
    except (OSError, ConnectionRefusedError) as e:
        # Socket file exists but nothing is listening — a leftover from a
        # daemon that died; remove it so the next start can rebind.
        try:
            socket_path.unlink()
        except OSError:
            pass
        raise _DaemonUnavailable() from e

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
                return False
            msg = json.loads(line)
            status = msg.get("status")
            if status == "cache":
                _report_cache(msg.get("cache") or {})
                continue
            if status == "ok":
                click.echo(
                    f"Notebook execution requested successfully. View output at {NOTEBOOK_URL}"
                )
                return True
            click.echo(f"Execution failed: {msg.get('message')}", err=True)
            return False
    except Exception as e:
        click.echo(f"Error communicating with daemon: {e}", err=True)
        return False
    finally:
        s.close()


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
@click.option(
    "--watch",
    "-w",
    is_flag=True,
    default=False,
    help="Re-run the notebook automatically whenever the file changes "
    "(Ctrl-C to stop).",
)
def run(notebook: Path, clear_cache: str | None, clear_cache_all: bool, watch: bool) -> None:
    notebook_path = notebook.resolve()
    socket_path = Path.cwd() / ".nb.sock"

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

    # Initial run.
    try:
        ok = _send_run(socket_path, req)
    except _DaemonUnavailable:
        click.echo("Could not connect to daemon. Is it running?", err=True)
        sys.exit(1)

    if not watch:
        sys.exit(0 if ok else 1)

    # Watch loop: re-run on every change to the notebook file. Execution errors
    # are non-fatal here (fix the file and save again); only the daemon going
    # away stops the loop.
    click.echo(f"Watching {notebook_path} for changes (Ctrl-C to stop)...")
    try:
        last_mtime = notebook_path.stat().st_mtime
        while True:
            time.sleep(WATCH_POLL_SECONDS)
            try:
                mtime = notebook_path.stat().st_mtime
            except OSError:
                # File transiently missing (e.g. atomic save mid-rename); retry.
                continue
            if mtime == last_mtime:
                continue
            last_mtime = mtime
            click.echo("Change detected, re-running...")
            try:
                _send_run(socket_path, req)
            except _DaemonUnavailable:
                click.echo("Daemon no longer reachable; stopping watch.", err=True)
                sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nStopped watching.")


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
