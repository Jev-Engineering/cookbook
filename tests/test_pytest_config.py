"""`pyproject.toml` registers the `catalog_audit` marker and deselects it by default (#203):
without both, `tests/test_recipe_guard.py::test_every_recipe_is_linked_from_some_other_recipes_
next_steps` would either warn as unregistered or run in every per-PR `pytest` invocation, which
it cannot pass on a new recipe's own pull request (see that test's docstring and the module
docstring's scope decisions for why). Read as plain text, not parsed as TOML, so this needs no
TOML library on either supported Python (the package floor is 3.10, which has none in the
standard library) -- simple literal substring assertions are enough to pin the two lines."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYPROJECT_TEXT = (REPO / "pyproject.toml").read_text("utf-8")


def test_catalog_audit_marker_is_registered():
    """A marker used with `@pytest.mark.catalog_audit` but never registered in `[tool.pytest.
    ini_options]`'s `markers` would make every use emit `PytestUnknownMarkWarning`."""
    assert "catalog_audit:" in PYPROJECT_TEXT


def test_addopts_deselects_catalog_audit_by_default():
    """The marker expression `-m 'not catalog_audit'` keeps the per-PR `pytest` invocation (CI's
    `Tests (py3.10)` / `Tests (py3.14)` jobs and the local command in docs/development.md run
    plain `pytest`, so whatever `addopts` says here is what they get) from selecting the wave
    close-out audit test, while the pre-existing `--import-mode=importlib` option stays in force."""
    assert "--import-mode=importlib" in PYPROJECT_TEXT
    assert "-m 'not catalog_audit'" in PYPROJECT_TEXT
