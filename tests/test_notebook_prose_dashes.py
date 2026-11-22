"""Apply the CommonMark documentation dash rule to every published notebook."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# pytest uses importlib mode, so sibling test modules are not top-level imports.
# Load the canonical scanner by its exact repository path; keep one grammar.
_spec = importlib.util.spec_from_file_location(
    "notebook_dash_docs_facts", ROOT / "tests/test_docs_facts.py"
)
_docs_facts = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _docs_facts
_spec.loader.exec_module(_docs_facts)
_dash_lines = _docs_facts._dash_lines


def _notebook_dash_problems(notebook):
    """Return zero-based cell and one-based enclosing prose-block line."""
    return [
        (index, line)
        for index, cell in enumerate(notebook["cells"])
        if cell["cell_type"] == "markdown"
        for line in _dash_lines("".join(cell["source"]))
    ]


def _published_notebooks():
    catalog = json.loads((ROOT / "catalog/recipes.json").read_text(encoding="utf-8"))
    paths = [ROOT / "recipes" / recipe["slug"] / "notebook.ipynb" for recipe in catalog["recipes"]]
    published = [path for path in paths if path.is_file()]
    assert published, "the published notebook inventory must not be empty"
    return published


@pytest.mark.parametrize("path", _published_notebooks(), ids=lambda path: path.parent.name)
def test_published_notebook_markdown_uses_em_dashes(path):
    problems = _notebook_dash_problems(json.loads(path.read_text(encoding="utf-8")))
    assert not problems, f"{path.relative_to(ROOT)}: use an em dash in prose: {problems}"


def test_template_notebook_markdown_uses_em_dashes():
    path = ROOT / "recipes/_template/notebook.ipynb"
    assert not _notebook_dash_problems(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("as_list", [False, True])
@pytest.mark.parametrize(
    "source",
    [
        "A decision -- a bounded one -- stays typed.",
        "# Heading -- aside",
        "> Quoted prose -- aside",
        "- List prose -- aside",
        "[Visible -- label](https://example.invalid/path)",
        "**Emphasized -- aside**",
        "| Topic | Meaning |\n| --- | --- |\n| prose -- aside | a value |",
        '<span title="attribute -- allowed">Visible -- aside</span>',
        "```python\n# code -- permitted\n```\n\nProse -- rejected.",
        "`unmatched\n\nVisible -- aside\n\n`also unmatched",
    ],
)
def test_notebook_dash_prose_mutation_is_detected(source, as_list):
    notebook = {
        "cells": [
            {"cell_type": "code", "source": "# code -- permitted"},
            {
                "cell_type": "markdown",
                "source": source.splitlines(keepends=True) if as_list else source,
            },
        ]
    }
    assert _notebook_dash_problems(notebook)
    assert all(cell == 1 for cell, _ in _notebook_dash_problems(notebook))


@pytest.mark.parametrize("as_list", [False, True])
@pytest.mark.parametrize(
    "source",
    [
        "A decision â€” a bounded one â€” stays typed.",
        "` -- ` quotes the code spelling.",
        "```python\n# code -- permitted\n```",
        "~~~bash\npython tool.py -- value\n~~~",
        "    code -- permitted\n",
        "> ```\n> code -- permitted\n> ```",
        "- item\n\n      code -- permitted",
        "``code ` -- ` permitted``",
        "[visible](<https://example.invalid/a -- b>)",
        '<span title="attribute -- permitted">Visible prose.</span>',
        "word--word and --flag and a single - stay unchanged.",
        "---\n\n| --- | --- |",
    ],
)
def test_notebook_dash_code_mutation_remains_allowed(source, as_list):
    notebook = {
        "cells": [
            {"cell_type": "code", "source": "# code -- permitted\nvalue = ' -- '"},
            {"cell_type": "raw", "source": "raw -- permitted"},
            {
                "cell_type": "markdown",
                "source": source.splitlines(keepends=True) if as_list else source,
            },
        ]
    }
    assert not _notebook_dash_problems(notebook)


def test_notebook_guard_reports_cell_and_block_start_without_fabricating_offsets():
    notebook = {
        "cells": [
            {"cell_type": "code", "source": "# -- allowed"},
            {"cell_type": "markdown", "source": ["# Title\n", "\n", "Paragraph -- aside.\n"]},
        ]
    }
    assert _notebook_dash_problems(notebook) == [(1, 3)]


@pytest.mark.parametrize(
    "literal",
    [
        "Quick heads-up -- we've shifted your renewal date up by two weeks, "
        "just wanted you to know!",
        "I know this isn't the answer you were hoping for, and I'm sorry -- "
        "we're not able to approve the refund as requested",
    ],
)
def test_fixture_quote_mutation_requires_code_context(literal):
    notebook = {"cells": [{"cell_type": "markdown", "source": f"Quoted `{literal}`."}]}
    assert not _notebook_dash_problems(notebook)
    notebook["cells"][0]["source"] = f"Quoted {literal}."
    assert _notebook_dash_problems(notebook) == [(0, 1)]
