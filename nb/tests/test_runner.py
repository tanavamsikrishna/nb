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
    run_notebook(nb_file, exec_ns, emit_event)

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


def test_run_notebook_syntax_error(tmp_path: Path) -> None:
    # A SyntaxError raises in compile() before timing starts. The error handler
    # must still report the cell/run as failed rather than blowing up on
    # unbound wall_ms/cpu_ms (regression test).
    nb_file = tmp_path / "bad_nb.py"
    nb_file.write_text("# %%\nx = (\n")  # unterminated — SyntaxError at compile

    events: List[Tuple[str, dict]] = []

    def emit_event(event_type: str, event_data: dict) -> None:
        events.append((event_type, event_data))

    # Should not raise (previously NameError on wall_ms in the except block).
    run_notebook(nb_file, {}, emit_event)

    cell_end = next(d for t, d in events if t == "cell_end")
    assert cell_end["status"] == "error"
    assert cell_end["wall_ms"] == 0 and cell_end["cpu_ms"] == 0
    # The traceback is surfaced as a text record, and the run ends in error.
    assert any(t == "display_record" and d["type"] == "text" for t, d in events)
    assert events[-1] == ("run_end", {"status": "error"})
