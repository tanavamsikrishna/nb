import ast
import linecache
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Tuple

import nb.framework as fw

# Callback that receives notebook console output: (stream_name, text) where
# stream_name is "stdout" or "stderr". The daemon forwards these to the `nb run`
# CLI socket; a None sink leaves the real streams in place (standalone/tests).
LogSink = Callable[[str, str], None]


class _StreamProxy:
    """File-like stand-in for sys.stdout/sys.stderr during a run.

    Writes from the executing notebook (which runs on `exec_thread_id`) are
    forwarded to `log_sink` tagged with `name`. Writes from any other thread —
    e.g. the daemon's asyncio loop logging while a run is in flight — fall
    through to the original stream untouched, so only notebook output is
    captured.
    """

    def __init__(self, name: str, log_sink: LogSink, original, exec_thread_id: int) -> None:
        self._name = name
        self._log_sink = log_sink
        self._original = original
        self._exec_thread_id = exec_thread_id

    def write(self, s: str) -> int:
        if threading.get_ident() == self._exec_thread_id:
            if s:
                self._log_sink(self._name, s)
            return len(s)
        return self._original.write(s)

    def flush(self) -> None:
        self._original.flush()

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False


@dataclass
class Cell:
    id: int
    title: str
    source_line: int
    code: str


def _first_nonempty_line(code: str) -> str:
    for line in code.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _make_cell(cell_id: int, label: str, source_line: int, code: str) -> "Cell":
    # A cell's title is fabricated here so the frontend only ever renders a
    # finished string. An explicit `# %% label` wins; otherwise we derive one
    # from the first non-empty line of code and wrap it in quotes to mark it as
    # derived rather than author-provided.
    title = label
    if not title:
        first = _first_nonempty_line(code)
        if first:
            title = f'"{first}"'
    return Cell(id=cell_id, title=title, source_line=source_line, code=code)


def _is_empty_or_only_docstring(code: str) -> bool:
    stripped = code.strip()
    if not stripped:
        return True
    try:
        tree = ast.parse(code)
        if not tree.body:
            return True
        if len(tree.body) == 1:
            stmt = tree.body[0]
            if (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                return True
    except Exception:
        pass
    return False


def parse_notebook(source: str) -> Tuple[str | None, List[Cell]]:
    try:
        parsed_ast = ast.parse(source)
        docstring = ast.get_docstring(parsed_ast)
    except Exception:
        docstring = None

    lines = source.splitlines(keepends=True)
    cells: List[Cell] = []
    current_cell_lines: List[str] = []
    current_label = ""
    current_source_line = 1
    cell_id = 0

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# %%"):
            code = "".join(current_cell_lines)
            # Skip only the leading header segment (module docstring / comments
            # before the first `# %%`). Every real `# %%` cell is kept and
            # numbered by position, so UI cell numbers line up with the
            # notebook. Cells that render nothing are hidden by the frontend,
            # but their number is still reserved here.
            if cell_id == 0 and _is_empty_or_only_docstring(code):
                pass
            else:
                cells.append(_make_cell(cell_id, current_label, current_source_line, code))
                cell_id += 1

            current_cell_lines = []
            current_label = stripped[4:].strip()
            current_source_line = idx + 2  # Next line is the start of cell content
        else:
            current_cell_lines.append(line)

    code = "".join(current_cell_lines)
    if cell_id == 0 and _is_empty_or_only_docstring(code):
        pass
    else:
        cells.append(_make_cell(cell_id, current_label, current_source_line, code))
        cell_id += 1

    if not cells:
        cells.append(
            Cell(
                id=0,
                title="",
                source_line=1,
                code="",
            )
        )

    # Skipping a docstring-only cell 0 leaves a gap, so renumber consecutively.
    for idx, cell in enumerate(cells):
        cell.id = idx

    return docstring, cells


def _cell_for_line(cells: List["Cell"], line: int) -> "Cell":
    """The cell that owns `line`: the last cell whose `# %%` header line
    (`source_line - 1`) is at or before `line`. Forgiving of a cursor sitting on
    the header line or anywhere in the body. A line before the first cell maps to
    the first cell."""
    chosen = cells[0]
    for cell in cells:
        if cell.source_line - 1 <= line:
            chosen = cell
        else:
            break
    return chosen


def run_notebook(
    path: Path,
    exec_ns: dict,
    emit_event: Callable[[str, dict], None],
    log_sink: LogSink | None = None,
    target_lines: Tuple[int, int] | None = None,
) -> Tuple[bool, str, list[int]]:
    """Execute the notebook at `path`. Returns `(errored, run_code, ran_cell_ids)`.

    `errored` is True if a cell (or load) errored. `run_code` is the source to
    persist for experiment tracking: the whole file for a full run, or only the
    code of the cells that actually ran for a partial run (empty on a read error).
    `ran_cell_ids` are the ids of the cells this run executed — the full notebook
    for a full run, the targeted subset for a partial one (so a saved partial run
    records only its own cells, not the parent's surviving render state).

    `log_sink`, when provided, receives the notebook's stdout/stderr and full
    tracebacks (raw passthrough for the `nb run` terminal); the browser gets
    only a brief error notice via the error `cell_end` event.

    `target_lines`, when given as `(start, end)`, restricts execution to the
    contiguous range of cells owning those lines (a single cell when both land in
    the same one) — a *partial* run against the supplied (persisted) namespace.
    Partial runs skip the `notebook_header` event and tag `run_start` with
    `partial: True` so neither the daemon's state model nor the frontend treats
    the shortened manifest as the whole notebook.
    """
    # Cache invalidation happens in the daemon before this runs (see handle_ipc_client),
    # so the cleared-cache report can be sent to the CLI before the notebook executes.
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        emit_event("run_end", {"status": "error", "error": f"Failed to read file: {e}"})
        return True, "", []

    # Inject the exact source we're about to run into linecache, keyed by path.
    # Cells are compiled with file-relative line numbers (see padding below), so
    # tracebacks resolve source text from here instead of re-reading from disk.
    # mtime=None makes the entry permanent (linecache.checkcache skips it), so the
    # displayed source stays byte-identical to what ran even after the file changes
    # on disk between runs (e.g. under `nb run -w`).
    linecache.cache[str(path)] = (
        len(source),
        None,
        source.splitlines(keepends=True),
        str(path),
    )

    docstring, cells = parse_notebook(source)

    partial = target_lines is not None
    if partial:
        # Map both endpoints to cells and keep the inclusive index range between
        # them (cell.id == position after renumbering, so slicing by id works).
        lo, hi = sorted(
            (_cell_for_line(cells, target_lines[0]).id, _cell_for_line(cells, target_lines[1]).id)
        )
        cells = cells[lo : hi + 1]

    # Source to persist for experiment tracking: the whole file for a full run,
    # or only the run cells (with their headers reconstructed) for a partial run.
    if partial:
        run_code = "\n\n".join(f"# %% {cell.title}\n{cell.code}" for cell in cells)
    else:
        run_code = source
    # Filled as cells actually execute (not upfront), so a run that errors partway
    # records only the cells that ran — the trailing, never-executed cells are
    # excluded from the saved experiment's cell_ids.
    ran_cell_ids: list[int] = []

    # A partial run leaves the notebook header untouched (path/docstring haven't
    # changed); emitting it would reset the daemon's notebook_state. A full run
    # always emits, even without a docstring, so the frontend receives the path.
    if not partial:
        header_data: dict = {"path": str(path), "code": source}
        if docstring is not None:
            header_data["docstring"] = docstring
        emit_event("notebook_header", header_data)

    cell_manifest = [{"id": cell.id, "title": cell.title} for cell in cells]
    run_start_data: dict = {"cell_manifest": cell_manifest}
    if partial:
        run_start_data["partial"] = True
    emit_event("run_start", run_start_data)

    exec_ns.setdefault("__name__", "__main__")
    exec_ns.setdefault("__builtins__", __builtins__)
    exec_ns.setdefault("display", fw.display)
    exec_ns.setdefault("record_params", fw.record_params)
    exec_ns.setdefault("nb_cache", fw.nb_cache)

    old_emitter = fw._active_emitter
    installed_runner_emitter = old_emitter is None

    if installed_runner_emitter:

        def runner_emitter(record: fw.DisplayRecord) -> None:
            emit_event(
                "display_record",
                {"cell_id": fw._current_cell_id, "type": record.type, "payload": record.payload},
            )

        fw._active_emitter = runner_emitter

    # Capture notebook stdout/stderr for the duration of the run and route it to
    # the CLI via log_sink. Process-global, but safe: run_lock serializes runs
    # and the proxies only capture writes from this (the exec) thread.
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    installed_proxies = log_sink is not None
    if installed_proxies:
        exec_thread_id = threading.get_ident()
        sys.stdout = _StreamProxy("stdout", log_sink, old_stdout, exec_thread_id)
        sys.stderr = _StreamProxy("stderr", log_sink, old_stderr, exec_thread_id)

    errored = False
    try:
        for cell in cells:
            emit_event(
                "cell_start",
                {"cell_id": cell.id, "source_line": cell.source_line, "title": cell.title},
            )

            # Tag the cell so display primitives know which cell they belong to.
            fw._current_cell_id = cell.id
            ran_cell_ids.append(cell.id)

            # Default so the except block has values even if compile() raises
            # (e.g. a SyntaxError in the cell) before timing starts.
            wall_ms = 0
            cpu_ms = 0
            try:
                # Prepend blank lines so the cell's code occupies its true file
                # line range; tracebacks then report file-relative line numbers.
                padded = "\n" * (cell.source_line - 1) + cell.code
                compiled = compile(padded, str(path), "exec")

                wall_start = time.perf_counter()
                cpu_start = time.process_time()
                try:
                    exec(compiled, exec_ns)
                finally:
                    wall_ms = int((time.perf_counter() - wall_start) * 1000)
                    cpu_ms = int((time.process_time() - cpu_start) * 1000)

                emit_event(
                    "cell_end",
                    {"cell_id": cell.id, "wall_ms": wall_ms, "cpu_ms": cpu_ms, "status": "ok"},
                )
            except Exception as exc:
                # Drop the runner's own leading frame(s) (the `exec(compiled, ...)`
                # call, or the `compile` call for a SyntaxError) so the traceback
                # shows only the user's notebook stack.
                exc_tb = exc.__traceback__
                while exc_tb is not None and exc_tb.tb_frame.f_code.co_filename == __file__:
                    exc_tb = exc_tb.tb_next
                tb = "".join(traceback.format_exception(type(exc), exc, exc_tb))
                # Full traceback goes to the CLI (raw stderr passthrough); the
                # browser gets only a brief notice carried on cell_end.
                if log_sink is not None:
                    log_sink("stderr", tb)
                else:
                    old_stderr.write(tb)
                summary = f"{type(exc).__name__}: {exc}"

                emit_event(
                    "cell_end",
                    {
                        "cell_id": cell.id,
                        "wall_ms": wall_ms,
                        "cpu_ms": cpu_ms,
                        "status": "error",
                        "error": summary,
                    },
                )

                emit_event("run_end", {"status": "error"})
                errored = True
                return errored, run_code, ran_cell_ids

        emit_event("run_end", {"status": "ok"})
        return errored, run_code, ran_cell_ids
    finally:
        fw._current_cell_id = None
        if installed_runner_emitter:
            fw._active_emitter = old_emitter
        if installed_proxies:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
