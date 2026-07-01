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


def _save_full(
    root: Path,
    nb_path: str,
    cells: list[CellState],
    code: str = "# %%\nx = 1\n",
    params: dict | None = None,
) -> str:
    return experiments.save_run(
        root,
        nb_path,
        code,
        cells,
        params=params or {},
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


def test_params_saved_into_meta(tmp_path: Path) -> None:
    # The auto-detected params dict is persisted verbatim into meta["params"].
    run_id = _save_full(
        tmp_path,
        "/proj/example.py",
        [_cell(0, [{"type": "text", "payload": "hi"}])],
        params={"LR": "0.01", "EPOCHS": "10"},
    )
    loaded = experiments.load_run(tmp_path, "/proj/example.py", run_id)
    assert loaded is not None
    assert loaded["meta"]["params"] == {"LR": "0.01", "EPOCHS": "10"}


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
        params={},
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
        params={},
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


def test_collect_params_autodetects_screaming_snake_globals() -> None:
    ns = {
        "LR": 0.01,  # -> repr: "0.01"
        "EPOCHS": 10,  # -> repr: "10"
        "MODEL": "resnet",  # str passes through as-is (no quotes)
        "USE_GPU": True,  # -> repr: "True"
        "LAYERS": [64, 32],  # -> repr: "[64, 32]"
        "N2": 5,  # digit-containing name still matches
        "lr": 0.5,  # lowercase — not a param
        "Model": "x",  # mixed case — not a param
        "__name__": "__main__",  # dunder — not a param
    }
    # Every SCREAMING_SNAKE global is kept; strings verbatim, everything else repr'd.
    assert fw.collect_params(ns) == {
        "LR": "0.01",
        "EPOCHS": "10",
        "MODEL": "resnet",
        "USE_GPU": "True",
        "LAYERS": "[64, 32]",
        "N2": "5",
    }


def test_collect_params_surfaces_repr_failure_without_crashing() -> None:
    # A value whose __repr__ raises must be surfaced as a placeholder, never dropped
    # silently and never allowed to break param collection.
    class Boom:
        def __repr__(self) -> str:
            raise RuntimeError("nope")

    params = fw.collect_params({"BOOM": Boom()})
    assert set(params) == {"BOOM"}
    assert params["BOOM"].startswith("<unrepr-able Boom:")


def test_begin_run_creates_dirs_and_finalize_writes_meta(tmp_path: Path) -> None:
    # begin_run makes the run + artifacts dirs before the run; finalize_run fills in
    # meta/code/records with the logged artifacts, round-tripping through load_run.
    handle = experiments.begin_run(tmp_path, "/proj/example.py")
    assert handle.run_dir.is_dir()
    assert handle.artifacts_dir.is_dir()
    assert handle.artifacts_dir.parent == handle.run_dir

    artifacts = [
        {"name": "model", "path": str(handle.artifacts_dir / "m.pt")},
        {"name": "checkpoint", "path": str(handle.artifacts_dir / "c1.pt")},
        {"name": "checkpoint", "path": str(handle.artifacts_dir / "c2.pt")},
    ]
    run_id = experiments.finalize_run(
        handle,
        "# %%\nx = 1\n",
        [_cell(0, [{"type": "text", "payload": "hi"}])],
        params={"LR": "0.01"},
        artifacts=artifacts,
        parent_run_id=None,
        kind="full",
        started_at="2026-06-28T10:00:00+00:00",
        dur_ms=42,
        status="ok",
        error=None,
    )
    assert run_id == handle.run_id

    loaded = experiments.load_run(tmp_path, "/proj/example.py", run_id)
    assert loaded is not None
    # Ordered list preserved verbatim, including the two "checkpoint" entries.
    assert loaded["meta"]["artifacts"] == artifacts


def test_discard_run_removes_directory(tmp_path: Path) -> None:
    # A run that produces nothing worth saving is removed by discard_run.
    handle = experiments.begin_run(tmp_path, "/proj/example.py")
    assert handle.run_dir.is_dir()
    experiments.discard_run(handle)
    assert not handle.run_dir.exists()
    # Best-effort: a second discard (already gone) must not raise.
    experiments.discard_run(handle)


def test_save_run_defaults_artifacts_to_empty_list(tmp_path: Path) -> None:
    # The one-shot save_run (no artifacts logged) records an empty list.
    run_id = _save_full(tmp_path, "/proj/example.py", [_cell(0, [])])
    loaded = experiments.load_run(tmp_path, "/proj/example.py", run_id)
    assert loaded is not None
    assert loaded["meta"]["artifacts"] == []


def test_artifact_path_writes_into_current_run_dir(tmp_path: Path) -> None:
    # artifact_path creates an empty file inside fw._current_run_dir with the given
    # suffix; log_artifact appends {name, path} in call order (dups kept).
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    old_dir, old_list = fw._current_run_dir, fw._artifacts
    fw._current_run_dir = artifacts_dir
    fw._artifacts = []
    try:
        p1 = fw.artifact_path(".pt")
        p2 = fw.artifact_path(".png")
        assert Path(p1).parent == artifacts_dir
        assert Path(p1).is_file() and Path(p1).suffix == ".pt"
        assert Path(p2).suffix == ".png"

        fw.log_artifact("model", p1)
        fw.log_artifact("model", p2)  # same name twice — both kept
        assert fw.collect_artifacts() == [
            {"name": "model", "path": p1},
            {"name": "model", "path": p2},
        ]
    finally:
        fw._current_run_dir, fw._artifacts = old_dir, old_list


def test_artifact_path_falls_back_to_temp_dir_outside_run() -> None:
    # With no active run, artifact_path still creates a usable file (system temp).
    old_dir = fw._current_run_dir
    fw._current_run_dir = None
    p = ""
    try:
        p = fw.artifact_path(".txt")
        assert Path(p).is_file() and Path(p).suffix == ".txt"
    finally:
        if p:
            Path(p).unlink(missing_ok=True)
        fw._current_run_dir = old_dir
