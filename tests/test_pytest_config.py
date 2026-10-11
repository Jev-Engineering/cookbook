"""`pyproject.toml` registers the `catalog_audit` marker and deselects it by default (#203):
without both, `tests/test_recipe_guard.py::test_every_recipe_is_linked_from_some_other_recipes_
next_steps` would either warn as unregistered or run in every per-PR `pytest` invocation, which
it cannot pass on a new recipe's own pull request (see that test's docstring and the module
docstring's scope decisions for why). Read as plain text, not parsed as TOML, so this needs no
TOML library on either supported Python (the package floor is 3.10, which has none in the
standard library) -- simple literal substring assertions are enough to pin the two lines.

Registering and deselecting the marker in `pyproject.toml` is not by itself enough: something in
`tests/test_recipe_guard.py` has to actually apply `@pytest.mark.catalog_audit` to the one test
it is meant to deselect, or the registration is a marker nothing uses. The third test below pins
that link -- deleting the decorator from the test file makes it fail (a fast, loud, local-to-this-
module signal), where before it would have silently let the audit test back into every per-PR
run with no complaint from anything in this file; see the pull request comment that added this
test for the before/after `pytest` runs proving it."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYPROJECT_TEXT = (REPO / "pyproject.toml").read_text("utf-8")
RECIPE_GUARD_TEXT = (REPO / "tests" / "test_recipe_guard.py").read_text("utf-8")


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


def test_catalog_audit_marks_exactly_the_inbound_links_test():
    """The registration above is only half the mechanism: `tests/test_recipe_guard.py` has to
    apply `@pytest.mark.catalog_audit`, and only to
    `test_every_recipe_is_linked_from_some_other_recipes_next_steps` (#203's "mark only that one
    test"). Asserts the decorator appears exactly once in the module, immediately above that
    test's own `@pytest.mark.parametrize` line, which is immediately above the `def` -- not
    merely present somewhere in the file, and not applied to any other test."""
    assert len(re.findall(r"^@pytest\.mark\.catalog_audit$", RECIPE_GUARD_TEXT, re.MULTILINE)) == 1
    pinned = re.compile(
        r"^@pytest\.mark\.catalog_audit\n"
        r"@pytest\.mark\.parametrize\([^\n]*\)\n"
        r"def test_every_recipe_is_linked_from_some_other_recipes_next_steps\(",
        re.MULTILINE,
    )
    assert pinned.search(RECIPE_GUARD_TEXT), (
        "@pytest.mark.catalog_audit must sit directly above "
        "test_every_recipe_is_linked_from_some_other_recipes_next_steps's own "
        "@pytest.mark.parametrize line"
    )
