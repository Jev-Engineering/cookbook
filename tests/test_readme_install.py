"""The ``.[dev,ml]`` README rule in ``tests/readme_install.py``: its one known wrong refusal and its
two blind spots (#358), each pinned on a small README written for the case."""

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
    readme = "To reproduce the outputs:\n\n```\nfirst\n\n\nsecond\n```\n\nAfter.\n"
    assert readme_install.paragraphs(readme) == [
        "To reproduce the outputs: ``` first second ```",
        "After.",
    ]


def test_an_unclosed_fence_runs_to_the_end_and_joins_the_prose_before_it():
    readme = 'To reproduce the outputs:\n\n```bash\npip install -e ".[dev,ml]"\n'
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


def test_a_readme_without_a_fence_is_split_by_blank_lines_only():
    # as before #358: blank (or whitespace-only) lines split, nothing else does
    readme = "One\nline.\n\n  \nTwo.\n"
    assert readme_install.paragraphs(readme) == ["One line.", "Two."]


# The cases below are the Gate B findings on #470 (round 1), each pinned on the README that showed it.

_REPRODUCTION_SENTENCE = (
    "Reproducing the committed outputs byte for byte needs\n"
    '`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`.'
)


def test_a_tests_install_fence_introduced_after_a_reproduction_sentence_is_not_refused():
    # the paragraph's last sentence introduces the tests, so the fence is not reproduction prose's
    readme = (
        "# Recipe\n\n"
        f"{_REPRODUCTION_SENTENCE} To run the tests:\n\n"
        "```bash\n"
        'pip install -e ".[dev,ml]"\n'
        "pytest recipes/NN-slug\n"
        "```\n"
    )
    assert readme_install.combined_reproduction_installs(readme) == []


def test_a_fence_comment_saying_regenerate_does_not_make_the_tests_install_a_reproduction():
    readme = (
        "## Run it offline\n\n"
        'From the repository root, in an environment with `pip install -e ".[dev,ml]"`:\n\n'
        "```bash\n"
        "pytest recipes/NN-slug\n"
        "python tools/execute_notebook.py recipes/NN-slug   # regenerate the committed outputs\n"
        "```\n"
    )
    assert readme_install.combined_reproduction_installs(readme) == []


def test_only_the_templates_above_is_for_wording_is_a_back_reference():
    readme = 'To reproduce the outputs run `pip install -e ".[dev,ml]"` above all else.\n'
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


def test_inline_triple_backtick_code_at_the_start_of_a_line_is_not_a_fence():
    readme = (
        "## Run it offline\n\n"
        '```pip install -e ".[dev,ml]"``` for the tests.\n\n'
        f"{_REPRODUCTION_SENTENCE}\n\n"
        "## Switch to live\n"
    )
    assert len(readme_install.paragraphs(readme)) == 4
    assert readme_install.combined_reproduction_installs(readme) == []


def test_triple_backticks_inside_an_indented_code_block_are_not_a_fence():
    readme = (
        "An example of a fence:\n\n"
        "    ```bash\n"
        '    pip install -e ".[dev,ml]"\n\n'
        f"{_REPRODUCTION_SENTENCE}\n"
    )
    assert len(readme_install.paragraphs(readme)) == 3
    assert readme_install.combined_reproduction_installs(readme) == []


def test_a_fence_indented_under_a_list_item_is_still_a_fence():
    readme = (
        "1. To reproduce the committed outputs, run:\n\n"
        "    ```bash\n"
        '    pip install -e ".[dev,ml]"\n\n'
        "    python tools/execute_notebook.py recipes/NN-slug\n"
        "    ```\n"
    )
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


def test_a_fence_closes_only_on_its_own_character_and_length_with_no_info_string():
    readme = (
        "Intro.\n\n"
        "````md\n"
        "```bash\n"
        "x\n"
        "```\n"
        "still inside\n"
        "````\n\n"
        "~~~\n"
        "```\n"
        "~~~text\n"
        "still inside\n"
        "~~~~\n\n"
        "After.\n"
    )
    assert readme_install.paragraphs(readme) == [
        "Intro.",
        "````md ```bash x ``` still inside ````",
        "~~~ ``` ~~~text still inside ~~~~",
        "After.",
    ]


def test_an_install_fence_a_few_steps_below_the_reproduction_prose_is_refused():
    readme = (
        "## Reproduce the outputs\n\n"
        "To reproduce the committed outputs:\n\n"
        "1. Create a fresh virtual environment.\n\n"
        "2. Install the package.\n\n"
        "```bash\n"
        'pip install -e ".[dev,ml]"\n'
        "```\n"
    )
    found = readme_install.combined_reproduction_installs(readme)
    assert len(found) == 1
    assert found[0].startswith("To reproduce the committed outputs:")


@pytest.mark.parametrize(
    "between",
    [
        "## Run the tests\n\n",  # a heading: the fence is in another section
        "One.\n\nTwo.\n\nThree.\n\nFour.\n\n",  # more blocks than the rule reaches back over
        "```text\nan earlier fence\n```\n\n",  # the prose introduced that fence, not this one
        "To run the tests:\n\n",  # a nearer introduction, not about reproducing
    ],
)
def test_the_reach_back_from_a_fence_to_reproduction_prose_is_bounded(between):
    readme = (
        "To reproduce the committed outputs:\n\n"
        f"{between}"
        "```bash\n"
        'pip install -e ".[dev,ml]"\n'
        "```\n"
    )
    assert readme_install.combined_reproduction_installs(readme) == []
