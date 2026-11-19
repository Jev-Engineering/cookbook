"""The ``.[dev,ml]`` README rule in ``tests/readme_install.py``: its one known wrong refusal (the
back-reference, #358 item 3a) and its "regenerate" and "byte-identical" blind spot (#358 item 3b),
each pinned on a small README written for the case. Paragraphs are split exactly as on main."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Loaded by path like test_new_recipe.py and test_recipe_guard.py do. Their loaders are not reused:
# tests/ has no __init__.py, so they cannot be imported reliably, and loading either file by path
# would run its module-level setup (tools/new_recipe.py, all of test_recipe_guard.py) to get 4 lines.
_spec = importlib.util.spec_from_file_location(
    "readme_install_for_own_test", Path(__file__).with_name("readme_install.py")
)
readme_install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(readme_install)
TEMPLATE_README = Path(__file__).resolve().parents[1] / "recipes" / "_template" / "README.md"


def test_an_ml_recipes_back_reference_to_the_tests_install_is_not_refused():
    # A scikit-learn recipe documents ``.[dev,ml]`` for its tests and updates the template's
    # back-reference in the reproduction paragraph to match. That names the tests' install; the
    # reproduction install in the same paragraph is still ``.[ml]``.
    readme = readme_install.with_documented_test_install(TEMPLATE_README.read_text("utf-8"))
    readme = readme.replace("`.[dev]` above is for", "`.[dev,ml]` above is for", 1)
    assert "`.[dev,ml]` above is for" in readme
    assert readme_install.combined_reproduction_installs(readme) == []


def test_the_back_reference_exemption_does_not_hide_a_combined_reproduction_install():
    # the same paragraph with the reproduction install itself changed to ``.[dev,ml]`` is refused
    readme = readme_install.with_documented_test_install(TEMPLATE_README.read_text("utf-8"))
    readme = readme.replace("`.[dev]` above is for", "`.[dev,ml]` above is for", 1)
    readme = readme_install.with_pre_162_reproduction_install(readme)
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


@pytest.mark.parametrize(
    "words",
    [
        "To regenerate the committed outputs, install",
        "For byte-identical outputs, install",
        "For byte-for-byte outputs, install",
        "To reproduce the outputs, install",
    ],
)
def test_a_reproduction_paragraph_is_recognised_by_its_synonyms(words):
    readme = f'# Recipe\n\n{words} `pip install -e ".[dev,ml]"` and run the notebook.\n'
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


def test_a_readme_without_a_fence_is_split_by_blank_lines_only():
    # as before #358: blank (or whitespace-only) lines split, nothing else does
    readme = "One\nline.\n\n  \nTwo.\n"
    assert readme_install.paragraphs(readme) == ["One line.", "Two."]


# The cases below are the Gate B findings on #470 (round 1), each pinned on the README that showed it.


def test_a_fence_comment_saying_regenerate_does_not_make_the_tests_install_a_reproduction():
    readme = (
        "## Run it offline\n\n"
        # no blank line before the fence: the prose and the fence are one paragraph, as on main
        'From the repository root, in an environment with `pip install -e ".[dev,ml]"`:\n'
        "```bash\n"
        "pytest recipes/NN-slug\n"
        "python tools/execute_notebook.py recipes/NN-slug   # regenerate the committed outputs\n"
        "```\n"
    )
    assert readme_install.combined_reproduction_installs(readme) == []


def test_only_the_templates_above_is_for_wording_is_a_back_reference():
    readme = 'To reproduce the outputs run `pip install -e ".[dev,ml]"` above all else.\n'
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


# The cases below are the Gate B findings on #470 (round 2, at f922ff0), each pinned on the README
# that showed it. Findings 1-3 were regressions there: each README is refused, as it is on main.

_INSTALL = 'pip install -e ".[dev,ml]"'
_FENCE = f"```bash\n{_INSTALL}\n```\n"


@pytest.mark.parametrize(
    "readme",
    [
        # finding 1: prose directly above the fence, no blank line, whatever it ends with
        f"To reproduce the committed outputs, run the following.\n{_FENCE}",
        f"To reproduce the committed outputs:\n{_FENCE}",
        # finding 2: prose directly below the closing fence, no blank line
        f"{_FENCE}This reproduces the committed outputs.\n",
    ],
)
def test_prose_touching_a_fence_is_in_its_paragraph_as_on_main(readme):
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


@pytest.mark.parametrize("install", ['`pip install -e ".[dev,ml]"`', "`pip install -e .[dev,ml]`"])
def test_an_install_followed_by_above_is_for_is_refused_as_on_main(install):
    # finding 3: only the span `.[dev,ml]` on its own is a back-reference, not an install command
    readme = f"To reproduce, {install} above is for the notebook too.\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


@pytest.mark.parametrize(
    "readme",
    [
        # finding 4: the catalog's and the fixtures' regeneration are not reproduction
        "The catalog is regenerated by `tools/render_catalog.py` in an environment with "
        f"`{_INSTALL}`.\n",
        f"To regenerate the fixtures, run:\n\n{_FENCE}",
        # finding 4: nor is a "# regenerate" comment inside the tests' fence
        "## Run it offline\n\n"
        "```bash\n"
        f"{_INSTALL}\n"
        "pytest recipes/NN-slug\n"
        "python tools/execute_notebook.py recipes/NN-slug   # regenerate the committed outputs\n"
        "```\n",
    ],
)
def test_regenerating_something_other_than_the_outputs_is_not_refused(readme):
    assert readme_install.combined_reproduction_installs(readme) == []


# The cases below are the Gate B findings on #470 (round 3, at 2bf6a14) that apply to 3a and 3b.


@pytest.mark.parametrize(
    "readme",
    [
        # finding 3: the backtick before .[dev,ml] closes the span `x`, it does not open one
        "To reproduce the outputs install `x`.[dev,ml]` above is for y.\n",
        "To reproduce the outputs install ``x``.[dev,ml]`` above is for y.\n",
    ],
)
def test_a_closing_backtick_does_not_make_a_back_reference(readme):
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


@pytest.mark.parametrize(
    "readme",
    [
        "To reproduce, install `x` first; `.[dev,ml]` above is for `ruff` and `pytest`.\n",
        "To reproduce, `.[dev,ml]`\nabove is for `ruff` and `pytest`.\n",
        "To reproduce, ``.[dev,ml]`` above is for `ruff` and `pytest`.\n",
    ],
)
def test_a_back_reference_after_other_code_spans_or_a_line_break_is_not_refused(readme):
    assert readme_install.combined_reproduction_installs(readme) == []


@pytest.mark.parametrize(
    "words",
    [
        # finding 8: passive and possessive forms
        "The committed outputs are regenerated with",
        "To regenerate the recipe's committed outputs run",
        "The notebook is regenerated with",
        "The notebook outputs can only be regenerated with",
    ],
)
def test_regenerating_the_outputs_in_the_passive_or_possessive_is_recognised(words):
    readme = f"# Recipe\n\n{words} `{_INSTALL}`.\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


@pytest.mark.parametrize(
    "readme",
    [
        f"The fixtures are regenerated with `{_INSTALL}`.\n",
        f"The fixture outputs are regenerated with `{_INSTALL}`.\n",
        f"To regenerate the notebook's fixtures, run `{_INSTALL}`.\n",
        # a blank line splits the fence into two paragraphs, but the second is still fenced code
        "## Run it offline\n\n"
        "```bash\n"
        "pytest recipes/NN-slug\n"
        "\n"
        f"{_INSTALL}\n"
        "python tools/execute_notebook.py recipes/NN-slug   # regenerate the committed outputs\n"
        "```\n",
    ],
)
def test_regenerating_other_things_or_in_a_fence_after_a_blank_line_is_not_refused(readme):
    assert readme_install.combined_reproduction_installs(readme) == []


def _readmes():
    root = Path(__file__).resolve().parents[1] / "recipes"
    return sorted(root.glob("*/README.md"))


@pytest.mark.parametrize("path", _readmes(), ids=lambda path: path.parent.name)
def test_the_prose_is_what_the_scope_checks_fence_reader_keeps(path):
    # fenced code is what tools/check_recipe_scope.py's without_code_fences removes, nothing else
    readme = path.read_text("utf-8")
    prose = " ".join(readme_install.paragraph_prose(readme)).split()
    assert prose == readme_install._scope.without_code_fences(readme).split()
    assert len(readme_install.paragraph_prose(readme)) == len(readme_install.paragraphs(readme))
