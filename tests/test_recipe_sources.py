"""Ties each published recipe's documented source list to catalog/recipes.json, so the two
cannot drift again (#130 item 3; #137 extends this to the notebook's intro cell, which carries
its own "Sources:" bullet list independent of the README's "## Sources" section).

recipes/_template is not a catalog slug (see tests/test_template_render.py), so it has no
catalog "sources" list to compare against and is correctly never selected here: this file's
checks pass vacuously for it, by construction, the same way the renderer never counts it as
published.
"""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))

SOURCE_ID = re.compile(r"^- (S\d+):", re.MULTILINE)


def _is_published(recipe: dict) -> bool:
    return (REPO / "recipes" / recipe["slug"] / "notebook.ipynb").is_file()


def _readme_source_ids(readme_text: str) -> list[str]:
    """The ``S<N>`` ids bulleted under the README's "## Sources" heading (its last section, so
    no later heading needs to bound the slice)."""
    marker = "\n## Sources\n"
    if marker not in readme_text:
        return []
    section = readme_text.split(marker, 1)[1]
    return SOURCE_ID.findall(section)


PUBLISHED = [r for r in CATALOG["recipes"] if _is_published(r)]


def test_at_least_one_recipe_is_published():
    # Otherwise the parametrized test below would silently check nothing.
    assert PUBLISHED


@pytest.mark.parametrize("recipe", PUBLISHED, ids=lambda r: r["slug"])
def test_the_readme_sources_match_the_catalog(recipe):
    readme = (REPO / "recipes" / recipe["slug"] / "README.md").read_text("utf-8")
    documented = _readme_source_ids(readme)
    cataloged = recipe.get("sources", [])
    assert documented, f"{recipe['slug']}/README.md has no '## Sources' bullet list"
    assert set(documented) == set(cataloged), (
        f"{recipe['slug']}: README.md lists sources {sorted(documented)} but "
        f"catalog/recipes.json lists {sorted(cataloged)} for rank {recipe['rank']}"
    )


def _notebook_intro_source_ids(recipe: dict) -> list[str]:
    """The ``S<N>`` ids bulleted under the first cell's "Sources:" line (tools/new_recipe.py's
    ``_source_lines``), the same list the README's "## Sources" section repeats."""
    notebook = json.loads((REPO / "recipes" / recipe["slug"] / "notebook.ipynb").read_text("utf-8"))
    intro = notebook["cells"][0]["source"]
    text = intro if isinstance(intro, str) else "".join(intro)
    marker = "\nSources:\n\n"
    if marker not in text:
        return []
    section = text.split(marker, 1)[1].split("\n## ", 1)[0]
    return SOURCE_ID.findall(section)


@pytest.mark.parametrize("recipe", PUBLISHED, ids=lambda r: r["slug"])
def test_the_notebook_intro_sources_match_the_catalog(recipe):
    documented = _notebook_intro_source_ids(recipe)
    cataloged = recipe.get("sources", [])
    assert documented, f"{recipe['slug']}/notebook.ipynb's intro cell has no 'Sources:' bullets"
    assert set(documented) == set(cataloged), (
        f"{recipe['slug']}: notebook.ipynb lists sources {sorted(documented)} but "
        f"catalog/recipes.json lists {sorted(cataloged)} for rank {recipe['rank']}"
    )
