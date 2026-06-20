import json
import re
import socket
import sys
import time
from pathlib import Path

import click

from nb import daemon

NOTEBOOK_URL = "http://localhost:7777"

# How often `--watch` polls the notebook's mtime for changes.
WATCH_POLL_SECONDS = 0.3

# A line spec: a single line `N` or an inclusive range `X-Y`.
_LINE_SPEC_RE = re.compile(r"(\d+)(?:-(\d+))?$")


def _functions(n: int) -> str:
    return "function" if n == 1 else "functions"


def _split_line_suffix(arg: str) -> tuple[str, str | None]:
    """Split an editor-style trailing `:N` / `:X-Y` line spec off a notebook
    path (e.g. `example.py:42`, `example.py:42-118`). Only treats the suffix as a
    spec when it matches the grammar, so paths containing a stray colon pass
    through unchanged."""
    head, sep, tail = arg.rpartition(":")
    if sep and head and _LINE_SPEC_RE.fullmatch(tail):
        return head, tail
    return arg, None


def _parse_line_spec(spec: str) -> list[int]:
    """Normalize a line spec to a `[start, end]` pair (`N` -> `[N, N]`)."""
    m = _LINE_SPEC_RE.fullmatch(spec.strip())
    if not m:
        raise ValueError(f"Invalid line spec {spec!r}: expected N or X-Y.")
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    return [start, end]


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
            if status == "stdout":
                # Raw passthrough so notebook output looks like a normal program's.
                click.echo(msg.get("data", ""), nl=False)
                continue
            if status == "stderr":
                click.echo(msg.get("data", ""), nl=False, err=True)
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
@click.argument("notebook", type=str)
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
    "--lines",
    "lines_opt",
    default=None,
    metavar="SPEC",
    help="Re-run only the cell(s) owning line N (or the range X-Y), against the namespace "
    "the last full run left behind. Equivalent to the NOTEBOOK:SPEC suffix.",
)
@click.option(
    "--watch",
    "-w",
    is_flag=True,
    default=False,
    help="Re-run the notebook automatically whenever the file changes (Ctrl-C to stop).",
)
def run(
    notebook: str,
    clear_cache: str | None,
    clear_cache_all: bool,
    lines_opt: str | None,
    watch: bool,
) -> None:
    # Accept an editor-style NOTEBOOK:SPEC suffix (example.py:42 / :42-118); the
    # explicit --lines option takes precedence if both are given.
    path_str, suffix = _split_line_suffix(notebook)
    spec = lines_opt if lines_opt is not None else suffix

    notebook_path = Path(path_str)
    if not notebook_path.is_file():
        click.echo(f"Notebook not found: {path_str}", err=True)
        sys.exit(1)
    notebook_path = notebook_path.resolve()
    socket_path = Path.cwd() / ".nb.sock"

    if clear_cache_all and clear_cache is not None:
        click.echo("Use either --clear-cache or --clear-cache-all, not both.", err=True)
        sys.exit(1)

    req: dict = {"path": str(notebook_path)}
    if spec is not None:
        try:
            req["lines"] = _parse_line_spec(spec)
        except ValueError as e:
            click.echo(str(e), err=True)
            sys.exit(1)
    if clear_cache_all:
        req["clear_cache_all"] = True
    elif clear_cache is not None:
        names = [n.strip() for n in clear_cache.split(",") if n.strip()]
        if not names:
            click.echo("--clear-cache needs one or more function names.", err=True)
            sys.exit(1)
        req["clear_cache"] = names

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


if __name__ == "__main__":
    main()
