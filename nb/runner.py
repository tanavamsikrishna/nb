import ast
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
            if cell_id == 0 and _is_empty_or_only_docstring(code):
                # Skip cell 0 if it contains only the docstring/comments
                pass
            else:
                cells.append(
                    Cell(
                        id=cell_id,
                        title=current_label,
                        source_line=current_source_line,
                        code=code,
                    )
                )
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
        cells.append(
            Cell(
                id=cell_id,
                title=current_label,
                source_line=current_source_line,
                code=code,
            )
        )
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

    # Re-index all cells consecutively starting at 0
    for idx, cell in enumerate(cells):
        cell.id = idx

    return docstring, cells


def run_notebook(path: Path, exec_ns: dict, emit_event: Callable[[str, dict], None]) -> None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        emit_event("run_end", {"status": "error", "error": f"Failed to read file: {e}"})
        return

    docstring, cells = parse_notebook(source)

    # Emit notebook header (always emit so frontend receives the path)
    header_data: dict = {"path": str(path)}
    if docstring is not None:
        header_data["docstring"] = docstring
    emit_event("notebook_header", header_data)

    # Build and emit cell manifest
    cell_manifest = [{"id": cell.id, "title": cell.title} for cell in cells]
    emit_event("run_start", {"cell_manifest": cell_manifest})

    # Prepare execution namespace
    exec_ns.setdefault("__name__", "__main__")
    exec_ns.setdefault("__builtins__", __builtins__)
    exec_ns.setdefault("display", fw.display)
    exec_ns.setdefault("nb_cache", fw.nb_cache)
    exec_ns.setdefault("clear_cache", fw.clear_cache)

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

            # Set active cell ID in framework so that display primitives can tag themselves
            fw._current_cell_id = cell.id

            try:
                compiled = compile(cell.code, str(path), "exec")

                # Wrap the whole cell in timing
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
            except Exception:
                # Format and emit traceback as plain text
                tb = traceback.format_exc()
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
