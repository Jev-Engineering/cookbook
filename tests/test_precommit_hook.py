"""The optional pre-commit ruff-format hook must see the same files as CI's `ruff format .`.

CI runs `ruff format --check .`, which also formats Python code blocks in Markdown. The
real-hook test runs the actual `pre-commit` and `ruff` and is skipped where pre-commit is not
installed (it is not a dev dependency); the pattern test needs only the standard library.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".pre-commit-config.yaml"

BAD_MD = '# T\n\n```python\nx   =  {"a":1}\n```\n'
GOOD_MD = '# T\n\n```python\nx = {"a": 1}\n```\n'


def _hook_files_pattern() -> re.Pattern[str]:
    block = re.search(
        r"- id: ruff-format\n(?P<body>(?:[ \t]+.*\n|\n)+?)(?=\s*- id:)", CONFIG.read_text()
    )
    assert block, "ruff-format hook not found"
    files = re.search(r"^\s+files:\s*(\S+)\s*$", block.group("body"), re.MULTILINE)
    assert files, "ruff-format hook has no files pattern"
    return re.compile(files.group(1))


@pytest.mark.parametrize(
    "name",
    ["README.md", "recipes/01-x/README.md", "docs/a.md", "a.py", "a.pyi", "n.ipynb", "w.pyw"],
)
def test_hook_receives_everything_ruff_format_dot_formats(name):
    assert _hook_files_pattern().search(name)


@pytest.mark.parametrize("name", ["a.markdown", "a.mdx", "a.txt", "a.json", "a.md.bak", ".env"])
def test_hook_skips_what_ruff_would_reject_or_ignore(name):
    assert not _hook_files_pattern().search(name)


def _ruff() -> str | None:
    """The ruff of this interpreter's environment (the pinned one), never a global one."""
    for name in ("ruff", "ruff.exe"):
        beside = Path(sys.executable).parent / name
        if beside.exists():
            return str(beside)
    return None


@pytest.mark.skipif(
    importlib.util.find_spec("pre_commit") is None or _ruff() is None,
    reason="pre-commit or the environment's ruff is not installed",
)
def test_real_precommit_hook_fails_unformatted_markdown_and_passes_formatted(tmp_path):
    import os

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for name in (".pre-commit-config.yaml", "pyproject.toml"):
        shutil.copy(ROOT / name, repo / name)
    (repo / "bad.md").write_text(BAD_MD)
    (repo / "good.md").write_text(GOOD_MD)
    (repo / "bad.markdown").write_text(BAD_MD)  # `ruff format .` ignores it; so must the hook
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {**os.environ, "PATH": f"{Path(_ruff()).parent}{os.pathsep}{os.environ['PATH']}"}

    def hook(name: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pre_commit", "run", "ruff-format", "--files", name],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    bad, good, ignored = hook("bad.md"), hook("good.md"), hook("bad.markdown")
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "Failed" in bad.stdout
    assert good.returncode == 0, good.stdout + good.stderr
    assert "Passed" in good.stdout
    assert ignored.returncode == 0 and "Skipped" in ignored.stdout
    # The same verdicts as CI's whole-tree command.
    ci = subprocess.run(
        [_ruff(), "format", "--check", "."], cwd=repo, capture_output=True, text=True
    )
    assert ci.returncode == 1 and "bad.md" in ci.stdout + ci.stderr
