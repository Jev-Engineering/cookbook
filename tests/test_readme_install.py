"""The ``.[dev,ml]`` README rule in ``tests/readme_install.py``: the "byte-for-byte" spelling of a
reproduction paragraph (#358 item 3b, in part), pinned on a small README written for the case.
Everything else gives the same verdict as main's rule, including the template's back-reference
sentence once a scikit-learn recipe adapts it (#358 item 3a, #592)."""

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

_INSTALL = 'pip install -e ".[dev,ml]"'


@pytest.mark.parametrize(
    "words",
    [
        "For byte-for-byte outputs, install",
        "For BYTE-FOR-BYTE outputs, install",
        "For byte for byte outputs, install",
        "To reproduce the outputs, install",
    ],
)
def test_a_reproduction_paragraph_is_recognised_by_its_synonyms(words):
    readme = f"# Recipe\n\n{words} `{_INSTALL}` and run the notebook.\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


def test_a_tests_paragraph_that_says_byte_identical_is_not_refused():
    # #470 code review at 672b254, finding 1: "byte-identical" also describes what the tests check
    # (docs/recipe-template.md), so it does not make a paragraph a reproduction paragraph.
    readme = (
        f"# Recipe\n\nRun the tests with `{_INSTALL}`; they check responses.json is"
        " byte-identical to dump_responses.\n"
    )
    assert readme_install.combined_reproduction_installs(readme) == []


def test_an_ml_recipes_back_reference_sentence_is_refused_as_on_main():
    """Pins main's known wrong refusal of this sentence, tracked in #592: when #592 lands this test
    is meant to fail and be changed to assert the sentence is accepted."""
    # The template as a scikit-learn recipe adapts it: the tests' install and the back-reference
    # sentence both say .[dev,ml]. The sentence sits in the reproduction paragraph, so main refuses
    # that paragraph and so does this rule; an exemption for it is #592.
    readme = readme_install.with_documented_test_install(TEMPLATE_README.read_text("utf-8"))
    assert "`.[dev]` above is for" in readme, "the template's back-reference sentence was reworded"
    readme = readme.replace("`.[dev]` above is for", "`.[dev,ml]` above is for", 1)
    refused = readme_install.combined_reproduction_installs(readme)
    assert len(refused) == 1
    assert "`.[dev,ml]` above is for `ruff` and `pytest`" in refused[0]


@pytest.mark.parametrize(
    "readme",
    [
        # #470 Gate B at 95a3d4f, findings 1-3 and 6: refused there, passed on main. The word
        # "regenerate" alone does not make a paragraph a reproduction paragraph.
        f"To regenerate the notebook fixtures, run `{_INSTALL}`.\n",
        f"To regenerate the output fixtures, run `{_INSTALL}`.\n",
        f"To regenerate the outputs of `tools/render_catalog.py`, run `{_INSTALL}`.\n",
        f"To regenerate the notebook’s fixtures, run `{_INSTALL}`.\n",
        "10. Install:\n\n    ```bash\n"
        f"    {_INSTALL}\n"
        "    python tools/execute_notebook.py x  # regenerate the committed outputs\n    ```\n",
        f"<!-- regenerate the committed outputs -->\nInstall `{_INSTALL}` to run pytest.\n",
        # #470 Gate B at 1d670fb, finding 1: the tests' fence after a reproduction paragraph
        "Reproducing the outputs byte for byte needs "
        '`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`. To run the tests:\n\n'
        f"```bash\n{_INSTALL}\npytest recipes/NN\n```\n",
    ],
)
def test_what_main_does_not_refuse_is_not_refused(readme):
    assert readme_install.combined_reproduction_installs(readme) == []


def test_paragraphs_are_split_by_blank_lines_only_as_on_main():
    # blank (or whitespace-only) lines split, nothing else does
    readme = "One\nline.\n\n  \nTwo.\n```bash\nx\n```\n"
    assert readme_install.paragraphs(readme) == ["One line.", "Two. ```bash x ```"]
