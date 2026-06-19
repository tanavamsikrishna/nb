import ast
import linecache
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Tuple

import nb.framework as fw


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
    # Extract module-level docstring
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

    # Append the last cell
    code = "".join(current_cell_lines)
    if cell_id == 0 and _is_empty_or_only_docstring(code):
        pass
    else:
        cells.append(_make_cell(cell_id, current_label, current_source_line, code))
        cell_id += 1

    # Fallback to single empty cell if empty
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


def run_notebook(
    path: Path,
    exec_ns: dict,
    emit_event: Callable[[str, dict], None],
) -> None:
    # Cache invalidation happens in the daemon before this runs (see handle_ipc_client),
    # so the cleared-cache report can be sent to the CLI before the notebook executes.
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        emit_event("run_end", {"status": "error", "error": f"Failed to read file: {e}"})
        return

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

    # Always emit, even without a docstring, so the frontend receives the path.
    header_data: dict = {"path": str(path)}
    if docstring is not None:
        header_data["docstring"] = docstring
    emit_event("notebook_header", header_data)

    cell_manifest = [{"id": cell.id, "title": cell.title} for cell in cells]
    emit_event("run_start", {"cell_manifest": cell_manifest})

    exec_ns.setdefault("__name__", "__main__")
    exec_ns.setdefault("__builtins__", __builtins__)
    exec_ns.setdefault("display", fw.display)
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

    try:
        for cell in cells:
            emit_event(
                "cell_start",
                {"cell_id": cell.id, "source_line": cell.source_line, "title": cell.title},
            )

            # Tag the cell so display primitives know which cell they belong to.
            fw._current_cell_id = cell.id

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
                emit_event("display_record", {"cell_id": cell.id, "type": "text", "payload": tb})

                emit_event(
                    "cell_end",
                    {"cell_id": cell.id, "wall_ms": wall_ms, "cpu_ms": cpu_ms, "status": "error"},
                )

                emit_event("run_end", {"status": "error"})
                return

        emit_event("run_end", {"status": "ok"})
    finally:
        fw._current_cell_id = None
        if installed_runner_emitter:
            fw._active_emitter = old_emitter
