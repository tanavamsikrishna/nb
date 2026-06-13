import pytest
from pathlib import Path
from typing import List, Tuple
from nb.runner import parse_notebook, run_notebook, Cell


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

    assert cells[0].label == "cell1"
    assert cells[0].source_line == 5
    assert "print" in cells[0].code

    assert cells[1].label == "cell2"
    assert cells[1].source_line == 8


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

    assert ("display_record", {"cell_id": 0, "type": "text", "payload": "10"}) in events
    assert events[-1] == ("run_end", {"status": "ok"})
    assert exec_ns.get("x") == 10
