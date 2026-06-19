from pathlib import Path
from typing import List, Tuple

from nb.runner import parse_notebook, run_notebook


def test_parse_notebook() -> None:
    source = '''"""
This is a test notebook.
"""
# %% cell1
print("Hello cell 1")

# %% cell2
a = 1
b = 2
'''
    docstring, cells = parse_notebook(source)
    assert docstring == "This is a test notebook."
    assert len(cells) == 2

    assert cells[0].title == "cell1"
    assert cells[0].source_line == 5
    assert "print" in cells[0].code

    assert cells[1].title == "cell2"
    assert cells[1].source_line == 8


def test_cells_kept_with_stable_numbering_and_titles() -> None:
    source = '''"""header"""
# %% setup
import os

# %%
df = load()
display(df)

# %%

# %% last
z = 2
'''
    _, cells = parse_notebook(source)

    # The leading docstring is the notebook header, not a cell. Every `# %%`
    # cell is kept and numbered by position — including the empty-body cell
    # (id 2) — so UI numbers line up with the notebook. The UI hides cells
    # that render nothing; it does not renumber them away.
    assert [c.id for c in cells] == [0, 1, 2, 3]

    # Explicit label kept verbatim.
    assert cells[0].title == "setup"
    # No label -> fabricated from the first non-empty line, wrapped in quotes.
    assert cells[1].title == '"df = load()"'
    # Empty-body cell: no label and no source line to derive from.
    assert cells[2].title == ""
    assert cells[3].title == "last"


def test_run_notebook(tmp_path: Path) -> None:
    nb_file = tmp_path / "test_nb.py"
    nb_file.write_text("""# %%
x = 10
display(x)
""")

    events: List[Tuple[str, dict]] = []

    def emit_event(event_type: str, event_data: dict) -> None:
        events.append((event_type, event_data))

    exec_ns = {}
    errored = run_notebook(nb_file, exec_ns, emit_event)

    assert errored is False
    event_types = [e[0] for e in events]
    assert "run_start" in event_types
    assert "cell_start" in event_types
    assert "display_record" in event_types
    assert "cell_end" in event_types
    assert "run_end" in event_types

    # A bare non-str object falls back to an "object" record (JSON-serialized).
    assert ("display_record", {"cell_id": 0, "type": "object", "payload": 10}) in events
    assert events[-1] == ("run_end", {"status": "ok"})
    assert exec_ns.get("x") == 10


def test_run_notebook_captures_stdout_stderr(tmp_path: Path) -> None:
    # print()/stderr writes are routed to log_sink (→ the `nb run` terminal),
    # NOT emitted as display records to the browser.
    nb_file = tmp_path / "io_nb.py"
    nb_file.write_text("""# %%
import sys
print("hello stdout")
print("oops", file=sys.stderr)
""")

    events: List[Tuple[str, dict]] = []
    logs: List[Tuple[str, str]] = []

    errored = run_notebook(
        nb_file,
        {},
        lambda t, d: events.append((t, d)),
        lambda stream, data: logs.append((stream, data)),
    )

    assert errored is False
    assert ("stdout", "hello stdout") in logs
    assert ("stdout", "\n") in logs  # print() writes the newline separately
    assert ("stderr", "oops") in logs
    # Console output must not leak into the browser as display records.
    assert not any(t == "display_record" for t, _ in events)


def test_run_notebook_log_sink_optional(tmp_path: Path) -> None:
    # Without a log_sink the real streams stay in place (standalone/test usage).
    nb_file = tmp_path / "io_nb.py"
    nb_file.write_text('# %%\nprint("standalone")\n')

    errored = run_notebook(nb_file, {}, lambda t, d: None)
    assert errored is False


def test_run_notebook_syntax_error(tmp_path: Path) -> None:
    # A SyntaxError raises in compile() before timing starts. The error handler
    # must still report the cell/run as failed rather than blowing up on
    # unbound wall_ms/cpu_ms (regression test).
    nb_file = tmp_path / "bad_nb.py"
    nb_file.write_text("# %%\nx = (\n")  # unterminated — SyntaxError at compile

    events: List[Tuple[str, dict]] = []
    logs: List[Tuple[str, str]] = []

    def emit_event(event_type: str, event_data: dict) -> None:
        events.append((event_type, event_data))

    # Should not raise (previously NameError on wall_ms in the except block).
    errored = run_notebook(nb_file, {}, emit_event, lambda s, d: logs.append((s, d)))

    assert errored is True
    cell_end = next(d for t, d in events if t == "cell_end")
    assert cell_end["status"] == "error"
    assert cell_end["wall_ms"] == 0 and cell_end["cpu_ms"] == 0
    # The brief notice rides on cell_end (shown in the UI header); the full
    # traceback goes to the CLI via log_sink, NOT to the browser.
    assert "error" in cell_end and cell_end["error"]
    assert any(stream == "stderr" and "SyntaxError" in data for stream, data in logs)
    assert not any(t == "display_record" for t, d in events)
    assert events[-1] == ("run_end", {"status": "error"})


def test_traceback_uses_file_relative_line_numbers(tmp_path: Path) -> None:
    # A header + a non-first cell so the raising statement's file line differs from
    # its cell-relative line. `1 / 0` sits on file line 9 but is the 2nd line of its
    # cell (cell-relative line 2); the traceback must report the file line.
    nb_file = tmp_path / "err_nb.py"
    nb_file.write_text(
        '"""\n'  # line 1
        "Header docstring\n"  # line 2
        '"""\n'  # line 3
        "# %% first\n"  # line 4
        "x = 1\n"  # line 5
        "\n"  # line 6
        "# %% second\n"  # line 7
        "y = 2\n"  # line 8
        "1 / 0\n"  # line 9  <- raises here
    )

    events: List[Tuple[str, dict]] = []
    logs: List[Tuple[str, str]] = []

    def emit_event(event_type: str, event_data: dict) -> None:
        events.append((event_type, event_data))

    run_notebook(nb_file, {}, emit_event, lambda s, d: logs.append((s, d)))

    # The full traceback is streamed to the CLI via log_sink (stderr stream).
    tb = next(data for stream, data in logs if stream == "stderr")
    assert "ZeroDivisionError" in tb
    # The notebook frame reports the file-relative line (9), not the cell-relative
    # line (2). Match the notebook file's frame specifically so we don't pick up
    # unrelated "line N" text from the runner's own frames.
    assert f'"{nb_file}", line 9' in tb
    assert f'"{nb_file}", line 2' not in tb
    # The injected linecache makes the offending source line render correctly too.
    assert "1 / 0" in tb
    # The runner's own exec/compile frames are stripped; only notebook frames show.
    assert "runner.py" not in tb
    assert events[-1] == ("run_end", {"status": "error"})
