"""The ``.[dev,ml]`` README rule in ``tests/readme_install.py``: its one known wrong refusal (the
template's back-reference sentence, #358 item 3a) and the "byte-for-byte" and "byte-identical"
spellings of a reproduction paragraph (#358 item 3b, in part), each pinned on a small README
written for the case. Everything else gives the same verdict as main's rule."""

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
_SENTENCE = "`.[dev,ml]` above is for `ruff` and `pytest`"


def _ml_template() -> str:
    # the template as a scikit-learn recipe adapts it: tests install and back-reference both .[dev,ml]
    readme = readme_install.with_documented_test_install(TEMPLATE_README.read_text("utf-8"))
    readme = readme.replace("`.[dev]` above is for", "`.[dev,ml]` above is for", 1)
    assert "`.[dev,ml]` above is for" in readme
    return readme


def test_an_ml_recipes_back_reference_to_the_tests_install_is_not_refused():
    # The back-reference names the tests' install; the reproduction install in the same
    # paragraph is still ``.[ml]``.
    assert readme_install.combined_reproduction_installs(_ml_template()) == []


def test_the_back_reference_exemption_does_not_hide_a_combined_reproduction_install():
    # the same paragraph with the reproduction install itself changed to ``.[dev,ml]`` is refused
    readme = readme_install.with_pre_162_reproduction_install(_ml_template())
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


@pytest.mark.parametrize(
    "readme",
    [
        # the template's sentence wrapped across lines, with runs of whitespace between the words
        "To reproduce, install `.[ml]` (`.[dev,ml]`\nabove is for `ruff`\n   and `pytest`).\n",
        "To reproduce, install `.[ml]` (`.[dev,ml]`   above\n  is  for\n`ruff` and\n`pytest`).\n",
        f"To reproduce, install `x` first; {_SENTENCE}.\n",
    ],
)
def test_a_wrapped_back_reference_or_one_after_other_code_spans_is_not_refused(readme):
    assert readme_install.combined_reproduction_installs(readme) == []


@pytest.mark.parametrize(
    "readme",
    [
        # #470 Gate B at 95a3d4f, finding 5: the span is part of the install, not a back-reference
        "To reproduce the outputs run `pip install -e` `.[dev,ml]` above is for everything.\n",
        # #470 Gate B at 1d670fb, finding 2: only the template's wording is a back-reference
        f"To reproduce the outputs run `{_INSTALL}` above all else.\n",
        "To reproduce the outputs run `.[dev,ml]` above all else.\n",
        # anything other than "above is for `ruff` and `pytest`" after the span
        "To reproduce, `.[dev,ml]` above is for the notebook too.\n",
        "To reproduce, `.[dev,ml]` above is for `ruff`.\n",
        "To reproduce, `.[dev,ml]`above is for `ruff` and `pytest`.\n",
        # .[dev,ml] inside a longer span is an install whatever follows it
        f"To reproduce, `{_INSTALL}` above is for `ruff` and `pytest`.\n",
        "To reproduce, `pip install -e .[dev,ml]` above is for `ruff` and `pytest`.\n",
        # exactly the span `.[dev,ml]`, not a double-backtick span
        "To reproduce, ``.[dev,ml]`` above is for `ruff` and `pytest`.\n",
        # the back-reference cancels its own occurrence only
        f"To reproduce, run `{_INSTALL}`; {_SENTENCE}.\n",
    ],
)
def test_anything_but_the_templates_back_reference_is_refused_as_on_main(readme):
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


# The template's own sentence (recipes/_template/README.md, tools/new_recipe.py), adapted to ml.
_TEMPLATE_SENTENCE = (
    "Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs "
    "for the `Notebook (<recipe>)` job: "
    '`pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python 3.14; `nbclient` and '
    "`ipykernel` are core dependencies, so this alone is enough to execute the notebook — "
    "`.[dev,ml]` above is for `ruff` and `pytest`, which that job does not run; see "
    "[docs/recipe-template.md](../../docs/recipe-template.md) step 6).\n"
)


def test_the_full_template_sentence_adapted_to_ml_is_not_refused():
    assert readme_install.combined_reproduction_installs(_TEMPLATE_SENTENCE) == []


@pytest.mark.parametrize(
    "readme",
    [
        # #470 code review at e40100e, finding 1: the exemption was a prefix match
        "To reproduce the outputs use the constraints. `.[dev,ml]` above is for `ruff` and "
        "`pytest` and also reproduces the notebook outputs.\n",
        "To reproduce run pip install -e `.[dev,ml]` above is for `ruff` and `pytest` "
        "-c .github/constraints-notebooks.txt.\n",
        # a boundary, but the rest of the sentence is itself about reproducing
        "To reproduce, `.[dev,ml]` above is for `ruff` and `pytest`, and it reproduces the outputs.\n",
        "To reproduce, `.[dev,ml]` above is for `ruff` and `pytest`; also byte for byte outputs.\n",
        "Outputs: `.[dev,ml]` above is for `ruff` and `pytest`, "
        "with -c .github/constraints-notebooks.txt.\n",
    ],
)
def test_the_back_reference_must_end_its_clause_and_not_go_on_about_reproducing(readme):
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


@pytest.mark.parametrize(
    "readme",
    [
        # #470 Gate B at 2bf6a14, finding 3: the backtick before .[dev,ml] closes the span `x`
        "To reproduce the outputs install `x`.[dev,ml]` above is for y.\n",
        "To reproduce the outputs install ``x``.[dev,ml]`` above is for y.\n",
        # the same with the template's tail: still not a span that the backtick opens
        "To reproduce the outputs install `x`.[dev,ml]` above is for `ruff` and `pytest`.\n",
    ],
)
def test_a_closing_backtick_does_not_make_a_back_reference(readme):
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


@pytest.mark.parametrize(
    "words",
    [
        "For byte-identical outputs, install",
        "For byte-for-byte outputs, install",
        "For BYTE-FOR-BYTE outputs, install",
        "For byte for byte outputs, install",
        "To reproduce the outputs, install",
    ],
)
def test_a_reproduction_paragraph_is_recognised_by_its_synonyms(words):
    readme = f"# Recipe\n\n{words} `{_INSTALL}` and run the notebook.\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


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
