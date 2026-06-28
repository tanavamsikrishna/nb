from pathlib import Path
from typing import List, Tuple

from nb.runner import _cell_for_line, parse_notebook, run_notebook


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
    errored, _, _ = run_notebook(nb_file, exec_ns, emit_event)

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

    errored, _, _ = run_notebook(
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

    errored, _, _ = run_notebook(nb_file, {}, lambda t, d: None)
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
    errored, _, _ = run_notebook(nb_file, {}, emit_event, lambda s, d: logs.append((s, d)))

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


def test_cell_for_line_maps_lines_to_owning_cell() -> None:
    # cell 0 header on line 1 (source_line 2); cell 1 header on line 4 (source_line 5).
    source = "# %% first\nx = 1\ndisplay(x)\n# %% second\ny = 2\ndisplay(y)\n"
    _, cells = parse_notebook(source)
    assert [c.source_line for c in cells] == [2, 5]

    # A line before the first cell falls back to cell 0.
    assert _cell_for_line(cells, 0).id == 0
    # The `# %%` header line and any body line of cell 0 map to cell 0.
    assert _cell_for_line(cells, 1).id == 0  # header line
    assert _cell_for_line(cells, 3).id == 0  # body line
    # The header and body lines of cell 1 map to cell 1.
    assert _cell_for_line(cells, 4).id == 1  # header line
    assert _cell_for_line(cells, 6).id == 1  # body line
    # A line past the end still maps to the last cell.
    assert _cell_for_line(cells, 99).id == 1


def test_run_notebook_partial_reuses_namespace(tmp_path: Path) -> None:
    # A partial run executes only the targeted cell(s) against a shared namespace,
    # so a later cell can read state an earlier full run left behind.
    nb_file = tmp_path / "partial_nb.py"
    nb_file.write_text(
        "# %% first\n"  # line 1 (header), cell 0 source_line 2
        "x = 10\n"  # line 2
        "display(x)\n"  # line 3
        "# %% second\n"  # line 4 (header), cell 1 source_line 5
        "y = x + 5\n"  # line 5
        "display(y)\n"  # line 6
    )

    ns: dict = {}
    run_notebook(nb_file, ns, lambda t, d: None)  # full run seeds x and y
    assert ns["x"] == 10 and ns["y"] == 15

    # Re-run only cell 1 (line 5). It reads x from the persisted namespace.
    events: List[Tuple[str, dict]] = []
    errored, _, _ = run_notebook(nb_file, ns, lambda t, d: events.append((t, d)), None, (5, 5))

    assert errored is False
    types = [t for t, _ in events]
    # No notebook_header on a partial run; run_start is flagged partial with a
    # manifest of just the targeted cell.
    assert "notebook_header" not in types
    run_start = next(d for t, d in events if t == "run_start")
    assert run_start["partial"] is True
    assert [c["id"] for c in run_start["cell_manifest"]] == [1]
    # Only cell 1 emits a lifecycle; cell 0 is untouched.
    assert {d["cell_id"] for t, d in events if t == "cell_start"} == {1}
    assert {d["cell_id"] for t, d in events if t == "cell_end"} == {1}
    assert ("display_record", {"cell_id": 1, "type": "object", "payload": 15}) in events


def test_run_notebook_partial_runs_cell_range_in_order(tmp_path: Path) -> None:
    # A line range re-runs every cell between the owning cells, in notebook order.
    nb_file = tmp_path / "range_nb.py"
    nb_file.write_text(
        "# %% a\n"  # line 1, cell 0 source_line 2
        "order = []\n"  # line 2
        "# %% b\n"  # line 3, cell 1 source_line 4
        "order.append('b')\n"  # line 4
        "# %% c\n"  # line 5, cell 2 source_line 6
        "order.append('c')\n"  # line 6
        "# %% d\n"  # line 7, cell 3 source_line 8
        "order.append('d')\n"  # line 8
    )

    ns: dict = {}
    run_notebook(nb_file, ns, lambda t, d: None)  # full run; order == ['b','c','d']
    ns["order"] = []  # reset so the partial run's contribution is observable

    events: List[Tuple[str, dict]] = []
    # Range covering cell 1 (line 4) through cell 2 (line 6).
    run_notebook(nb_file, ns, lambda t, d: events.append((t, d)), None, (4, 6))

    run_start = next(d for t, d in events if t == "run_start")
    assert [c["id"] for c in run_start["cell_manifest"]] == [1, 2]
    started = [d["cell_id"] for t, d in events if t == "cell_start"]
    assert started == [1, 2]  # in order, cells 0 and 3 excluded
    assert ns["order"] == ["b", "c"]


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
