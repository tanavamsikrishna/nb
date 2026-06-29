import json
from pathlib import Path

import msgspec

import nb.framework as fw
from nb import experiments
from nb.daemon import CellProfiling, CellRecord, CellState


def _cell(cell_id: int, records: list[dict], *, title: str = "", status: str = "ok") -> CellState:
    """Build a cell in the daemon's `session.cells` render-state shape."""
    return CellState(
        id=cell_id,
        title=title,
        source_line=cell_id * 3 + 2,
        status=status,
        stale=False,
        profiling=CellProfiling(wall_ms=1.0, cpu_ms=1.0),
        records=[CellRecord(type=r["type"], payload=r["payload"]) for r in records],
    )


def _save_full(root: Path, nb_path: str, cells: list[CellState], code: str = "# %%\nx = 1\n") -> str:
    return experiments.save_run(
        root,
        nb_path,
        code,
        cells,
        parent_run_id=None,
        kind="full",
        started_at="2026-06-28T10:00:00+00:00",
        dur_ms=42,
        status="ok",
        error=None,
    )


def test_save_and_load_run(tmp_path: Path) -> None:
    nb_path = "/proj/example.py"
    cells = [_cell(0, [{"type": "text", "payload": "hi"}])]
    run_id = _save_full(tmp_path, nb_path, cells, code="# %%\nx = 1\n")

    loaded = experiments.load_run(tmp_path, nb_path, run_id)
    assert loaded is not None
    assert loaded["code"] == "# %%\nx = 1\n"
    assert loaded["cells"] == json.loads(msgspec.json.encode(cells))
    assert loaded["meta"]["run_id"] == run_id
    assert loaded["meta"]["kind"] == "full"
    assert loaded["meta"]["parent_run_id"] is None
    assert loaded["meta"]["cell_ids"] == [0]


def test_params_extracted_into_meta(tmp_path: Path) -> None:
    # params records anywhere in the run are merged into meta["params"].
    cells = [
        _cell(0, [{"type": "params", "payload": {"lr": 0.01}}]),
        _cell(
            1, [{"type": "text", "payload": "noise"}, {"type": "params", "payload": {"epochs": 10}}]
        ),
    ]
    run_id = _save_full(tmp_path, "/proj/example.py", cells)
    loaded = experiments.load_run(tmp_path, "/proj/example.py", run_id)
    assert loaded is not None
    assert loaded["meta"]["params"] == {"lr": 0.01, "epochs": 10}


def test_list_notebooks(tmp_path: Path) -> None:
    _save_full(tmp_path, "/proj/a.py", [_cell(0, [])])
    _save_full(tmp_path, "/proj/a.py", [_cell(0, [])])
    _save_full(tmp_path, "/proj/b.py", [_cell(0, [])])

    nbs = {nb.path: nb for nb in experiments.list_notebooks(tmp_path)}
    assert set(nbs) == {"/proj/a.py", "/proj/b.py"}
    assert nbs["/proj/a.py"].run_count == 2
    assert nbs["/proj/a.py"].name == "a.py"
    assert nbs["/proj/b.py"].run_count == 1


def test_same_basename_different_dirs_dont_collide(tmp_path: Path) -> None:
    _save_full(tmp_path, "/proj/one/example.py", [_cell(0, [])])
    _save_full(tmp_path, "/proj/two/example.py", [_cell(0, [])])
    paths = {nb.path for nb in experiments.list_notebooks(tmp_path)}
    assert paths == {"/proj/one/example.py", "/proj/two/example.py"}


def test_parent_child_tree(tmp_path: Path) -> None:
    nb_path = "/proj/example.py"
    parent_id = _save_full(tmp_path, nb_path, [_cell(0, []), _cell(1, [])])
    child_id = experiments.save_run(
        tmp_path,
        nb_path,
        "# %% second\ny = 2\n",
        [_cell(1, [{"type": "text", "payload": "y"}])],
        parent_run_id=parent_id,
        kind="partial",
        started_at="2026-06-28T10:05:00+00:00",
        dur_ms=5,
        status="ok",
        error=None,
    )

    tree = experiments.list_runs_tree(tmp_path, nb_path)
    assert len(tree) == 1  # only the parent surfaces at the top level
    parent = tree[0]
    assert parent["run_id"] == parent_id
    assert [c["run_id"] for c in parent["children"]] == [child_id]
    assert parent["children"][0]["kind"] == "partial"
    assert parent["children"][0]["cell_ids"] == [1]


def test_list_runs_newest_first(tmp_path: Path) -> None:
    nb_path = "/proj/example.py"
    first = _save_full(tmp_path, nb_path, [_cell(0, [])])
    second = _save_full(tmp_path, nb_path, [_cell(0, [])])
    runs = experiments.list_runs(tmp_path, nb_path)
    assert [r["run_id"] for r in runs] == [second, first]


def test_orphan_child_surfaces_as_root(tmp_path: Path) -> None:
    # A child whose parent isn't stored must not be hidden.
    nb_path = "/proj/example.py"
    experiments.save_run(
        tmp_path,
        nb_path,
        "# %%\n",
        [_cell(0, [])],
        parent_run_id="nonexistent-parent",
        kind="partial",
        started_at="2026-06-28T10:00:00+00:00",
        dur_ms=1,
        status="ok",
        error=None,
    )
    tree = experiments.list_runs_tree(tmp_path, nb_path)
    assert len(tree) == 1
    assert tree[0]["children"] == []


def test_load_run_rejects_traversal(tmp_path: Path) -> None:
    assert experiments.load_run(tmp_path, "/proj/example.py", "../../etc/passwd") is None
    assert experiments.load_run(tmp_path, "/proj/example.py", "missing") is None


def test_list_missing_notebook_is_empty(tmp_path: Path) -> None:
    assert experiments.list_runs(tmp_path, "/proj/nope.py") == []
    assert experiments.list_runs_tree(tmp_path, "/proj/nope.py") == []
    assert experiments.list_notebooks(tmp_path) == []


def test_params_emits_params_record() -> None:
    # params(...) flows through the active sink as a distinct "params" record.
    captured: list[fw.DisplayRecord] = []
    old = fw._active_emitter
    fw._active_emitter = captured.append
    try:
        fw.params(lr=0.01, epochs=10)
    finally:
        fw._active_emitter = old
    assert len(captured) == 1
    assert captured[0].type == "params"
    assert captured[0].payload == {"lr": 0.01, "epochs": 10}
