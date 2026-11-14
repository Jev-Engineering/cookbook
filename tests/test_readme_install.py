"""The ``.[dev,ml]`` README rule in ``tests/readme_install.py``: its one known wrong refusal and its
two blind spots (#358), each pinned on a small README written for the case."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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


def test_an_install_in_a_fence_below_the_reproduction_prose_is_refused():
    readme = (
        "# Recipe\n\n"
        "To reproduce the committed notebook outputs, run:\n\n"
        "```bash\n"
        'pip install -e ".[dev,ml]"\n'
        "\n"
        "python tools/execute_notebook.py recipes/NN-slug\n"
        "```\n\n"
        "## Switch to live\n"
    )
    found = readme_install.combined_reproduction_installs(readme)
    assert len(found) == 1
    assert "reproduce" in found[0] and ".[dev,ml]" in found[0]


def test_a_fence_below_unrelated_prose_may_install_dev_and_ml():
    # the tests' install in a fence under "Run it offline" prose is the place the string is right
    readme = (
        "# Recipe\n\n"
        "## Run it offline\n\n"
        "From the repository root:\n\n"
        "```bash\n"
        'pip install -e ".[dev,ml]"\n'
        "pytest recipes/NN-slug\n"
        "```\n\n"
        "Reproducing the committed outputs byte for byte needs\n"
        '`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`.\n'
    )
    assert readme_install.combined_reproduction_installs(readme) == []


def test_blank_lines_inside_a_fence_do_not_split_it():
    readme = "Intro.\n\n```\nfirst\n\n\nsecond\n```\n\nAfter.\n"
    assert readme_install.paragraphs(readme) == ["Intro. ``` first second ```", "After."]


def test_an_unclosed_fence_runs_to_the_end_and_joins_the_prose_before_it():
    readme = 'To reproduce the outputs:\n\n```bash\npip install -e ".[dev,ml]"\n'
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


def test_the_template_and_published_readmes_split_as_before_where_they_have_no_fence():
    # a README with no fence is split exactly by blank lines, as before #358
    readme = "One\nline.\n\n  \nTwo.\n"
    assert readme_install.paragraphs(readme) == ["One line.", "Two."]
