"""Side-by-side code diff for experiment runs.

`CodeDiff` is the service other modules depend on. `register()` wires the
concrete tool at the composition root. The binary, its flags, and its
environment isolation stay in this module.
"""

import os
import subprocess
from pathlib import Path
from typing import Protocol

from nb.services import set_service

# UI color scheme (`prefers-color-scheme`). Implementations map this to a palette.
COLOR_SCHEMES = ("light", "dark")

# Side-by-side column count. CodeDiffModal is sized to match
# (~min(1400px, 96vw) at 0.75rem mono).
DIFF_COLUMNS = 180


class CodeDiff(Protocol):
    """Render a side-by-side diff of two source files as ANSI text."""

    def diff(self, left: Path, right: Path, *, color_scheme: str) -> str:
        """Diff `left` against `right`.

        `color_scheme` is one of `COLOR_SCHEMES`. Returns ANSI text.
        Raises if the underlying tool is missing or fails.
        """


class DeltaCodeDiff:
    """`CodeDiff` backed by the system `delta` binary."""

    def diff(self, left: Path, right: Path, *, color_scheme: str) -> str:
        # Isolate delta from the developer's terminal theme so the scheme the UI
        # sent is what gets painted. BAT_THEME overrides --light/--dark otherwise.
        env = os.environ.copy()
        env.pop("BAT_THEME", None)
        env.pop("DELTA_FEATURES", None)
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        env["GIT_CONFIG_SYSTEM"] = "/dev/null"
        env["GIT_CONFIG_NOSYSTEM"] = "1"

        # --paging=never / --true-color=always: ANSI even when stdout is a pipe.
        # --syntax-theme=none: delta highlights each hunk from scratch, so a
        # docstring whose opening quotes sit above the hunk is tokenized as code
        # (English "in" painted as a keyword). Line backgrounds are the diff.
        # --width: non-TTY has no terminal size.
        # --file-style=omit: both sides are store copies of code.py; the modal
        # already labels the runs, and the absolute paths blow the column width.
        proc = subprocess.run(
            [
                "delta",
                "--side-by-side",
                "--paging=never",
                "--true-color=always",
                "--syntax-theme=none",
                "--config=/dev/null",
                f"--{color_scheme}",
                f"--width={DIFF_COLUMNS}",
                "--file-style=omit",
                str(left),
                str(right),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        # delta exits 1 when the inputs differ (same convention as git diff).
        if proc.returncode not in (0, 1) or not proc.stdout:
            raise subprocess.CalledProcessError(
                proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr
            )
        return proc.stdout


def register() -> None:
    """Register the default `CodeDiff`. Call from the composition root only."""
    set_service(CodeDiff, DeltaCodeDiff())
