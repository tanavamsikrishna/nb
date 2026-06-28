"""Persistent experiment tracking for `nb`.

Each notebook *run* is saved as a flat directory under the project root so that
run history survives daemon restarts and can be browsed from the UI:

    .nb/experiments/
      <notebook-slug>/
        notebook.json              {"path": <abs>, "name": <basename>}
        <run_id>/
          meta.json                run metadata (see save_run)
          code.py                  source that ran (whole file, or run cells)
          records.json             the daemon's `session.cells` render state

`<notebook-slug>` is the basename plus a short hash of the absolute path, so two
notebooks that share a filename in different directories don't collide. The saved
`records.json` is byte-for-byte the shape the daemon already keeps in
`session.cells`, so the read-only run viewer renders it with the same components
the live stream uses.

These helpers do no locking of their own: the daemon calls `save_run` while
holding `run_lock`, which already serializes runs.
"""

import ast
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPERIMENTS_SUBDIR = (".nb", "experiments")

# run_id is minted by us and only ever travels back as an opaque token; still,
# validate it before joining onto a filesystem path (it arrives over HTTP).
_RUN_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]*$")


def _store_dir(root: Any) -> Path:
    return Path(root).joinpath(*EXPERIMENTS_SUBDIR)


def _slug(notebook_path: Any) -> str:
    key = str(notebook_path)
    h = hashlib.blake2b(key.encode("utf-8"), digest_size=4).hexdigest()
    safe = "".join(c if c.isalnum() else "_" for c in os.path.basename(key))
    return f"{safe}-{h}"


def _notebook_dir(root: Any, notebook_path: Any) -> Path:
    return _store_dir(root) / _slug(notebook_path)


def _mint_run_id() -> str:
    # Microsecond UTC timestamp keeps ids lexically sortable (newest sorts last);
    # the random suffix guards against any same-microsecond collision.
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return f"{ts}-{os.urandom(2).hex()}"


def _collect_params(cells: list[dict]) -> dict:
    """Merge every ``params(...)`` record across the run's cells into one dict."""
    out: dict = {}
    for cell in cells:
        for rec in cell.get("records", []):
            if rec.get("type") == "params" and isinstance(rec.get("payload"), dict):
                out.update(rec["payload"])
    return out


def save_run(
    root: Any,
    notebook_path: Any,
    code: str,
    cells: list[dict],
    *,
    parent_run_id: str | None,
    kind: str,
    started_at: str,
    dur_ms: int,
    status: str,
    error: str | None,
) -> str:
    """Persist one run; returns the minted run_id.

    `cells` is the daemon's `session.cells` render state. `kind` is
    "full" | "partial"; a partial run carries `parent_run_id` of the full run it
    descends from.
    """
    nb_dir = _notebook_dir(root, notebook_path)
    nb_dir.mkdir(parents=True, exist_ok=True)

    nb_json = nb_dir / "notebook.json"
    if not nb_json.exists():
        nb_json.write_text(
            json.dumps({"path": str(notebook_path), "name": os.path.basename(str(notebook_path))}),
            encoding="utf-8",
        )

    run_id = _mint_run_id()
    run_dir = nb_dir / run_id
    run_dir.mkdir()

    meta = {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "kind": kind,
        "started_at": started_at,
        "dur_ms": dur_ms,
        "status": status,
        "error": error,
        "cell_ids": [c["id"] for c in cells],
        "params": _collect_params(cells),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (run_dir / "code.py").write_text(code, encoding="utf-8")
    (run_dir / "records.json").write_text(json.dumps(cells), encoding="utf-8")
    return run_id


def list_notebooks(root: Any) -> list[dict]:
    """Every notebook that has at least one stored experiment."""
    store = _store_dir(root)
    out: list[dict] = []
    if not store.is_dir():
        return out
    for nb_dir in store.iterdir():
        nb_json = nb_dir / "notebook.json"
        if not nb_json.is_file():
            continue
        try:
            info = json.loads(nb_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_count = sum(
            1 for d in nb_dir.iterdir() if d.is_dir() and (d / "meta.json").is_file()
        )
        out.append({"path": info["path"], "name": info["name"], "run_count": run_count})
    return out


def list_runs(root: Any, notebook_path: Any) -> list[dict]:
    """All run metas for a notebook, newest run first."""
    nb_dir = _notebook_dir(root, notebook_path)
    if not nb_dir.is_dir():
        return []
    metas: list[dict] = []
    for d in nb_dir.iterdir():
        meta_file = d / "meta.json"
        if d.is_dir() and meta_file.is_file():
            try:
                metas.append(json.loads(meta_file.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    metas.sort(key=lambda m: m.get("run_id", ""), reverse=True)
    return metas


def list_runs_tree(root: Any, notebook_path: Any) -> list[dict]:
    """Run metas as a parent/child forest: parents newest-first, each with a
    `children` list (also newest-first) of its partial runs. A child whose parent
    is missing (e.g. pruned) surfaces as its own root so nothing is hidden."""
    runs = list_runs(root, notebook_path)  # newest-first
    by_id = {r["run_id"]: {**r, "children": []} for r in runs}
    roots: list[dict] = []
    for r in runs:
        node = by_id[r["run_id"]]
        parent_id = r.get("parent_run_id")
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


def load_run(root: Any, notebook_path: Any, run_id: str) -> dict | None:
    """Load one saved run: `{meta, code, cells}`, or None if it doesn't exist."""
    if not _RUN_ID_RE.match(run_id):
        return None
    run_dir = _notebook_dir(root, notebook_path) / run_id
    meta_file = run_dir / "meta.json"
    if not meta_file.is_file():
        return None
    code_file = run_dir / "code.py"
    records_file = run_dir / "records.json"
    code = code_file.read_text(encoding="utf-8") if code_file.is_file() else ""
    try:
        docstring = ast.get_docstring(ast.parse(code))
    except Exception:
        docstring = None
    return {
        "meta": json.loads(meta_file.read_text(encoding="utf-8")),
        "code": code,
        "docstring": docstring,
        "cells": (
            json.loads(records_file.read_text(encoding="utf-8"))
            if records_file.is_file()
            else []
        ),
    }
