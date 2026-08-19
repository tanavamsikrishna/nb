"""CLI-level tests for argument parsing and input handling (no daemon)."""

import io
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from nb.cli import _read_exec_source, main


class _TtyStdin(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_read_exec_source_uses_c_flag() -> None:
    assert _read_exec_source("print(1)") == "print(1)"


def test_read_exec_source_ignores_stdin_when_c_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("ignored"))
    assert _read_exec_source("print(1)") == "print(1)"


def test_read_exec_source_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(2)\n"))
    assert _read_exec_source(None) == "print(2)\n"


def test_read_exec_source_errors_on_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", _TtyStdin(""))
    with pytest.raises(SystemExit) as exc:
        _read_exec_source(None)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "No Python given" in err
    assert "-c CODE" in err


def test_query_exec_sends_c_flag_as_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    nb = tmp_path / "n.py"
    nb.write_text("# %%\npass\n")
    seen: dict = {}

    def fake_query(req: dict, sock) -> dict:
        seen.update(req)
        return {"stdout": "", "records": []}

    monkeypatch.setattr("nb.cli._query", fake_query)
    result = CliRunner().invoke(
        main, ["query", "exec", str(nb), "-c", "print(y)"], input="ignored"
    )
    assert result.exit_code == 0
    assert seen["code"] == "print(y)"
    assert seen["op"] == "exec"


def test_query_exec_sends_stdin_as_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    nb = tmp_path / "n.py"
    nb.write_text("# %%\npass\n")
    seen: dict = {}

    def fake_query(req: dict, sock) -> dict:
        seen.update(req)
        return {"stdout": "", "records": []}

    monkeypatch.setattr("nb.cli._query", fake_query)
    result = CliRunner().invoke(main, ["query", "exec", str(nb)], input="print(x)\n")
    assert result.exit_code == 0
    assert seen["code"] == "print(x)\n"
    assert seen["op"] == "exec"
