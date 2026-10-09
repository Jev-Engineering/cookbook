"""Guards catalog/recipes.json's per-row shape and sources against silent drift (#151, from the
Opus review of #149, comment 6071881469).

Nothing else in CI parametrizes over every catalog row regardless of publication status.
tests/test_recipe_sources.py only compares a *published* recipe's own README and notebook
against its catalog row, and tools/render_catalog.py --check only compares the generated README
regions against whatever the catalog says right now, so both are blind to a catalog edit that is
internally self-consistent but wrong on its own terms: dropping "S02" from an unpublished row
leaves every existing check green (it was never compared against anything). This file checks the
catalog data on its own, independent of what has been published: every row's rank, slug,
decision_types and sources.
"""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
RECIPES = CATALOG["recipes"]

SOURCE_ID_RE = re.compile(r"^S\d+$")
SLUG_RE = re.compile(r"^(\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*$")
KNOWN_DECISION_TYPES = {"Choice", "Noul", "Score"}
REQUIRED_SOURCES = {"S02", "S03"}  # Primitives and Confidence: every recipe asks a typed
# question (S02) and every recipe's helpers derive or threshold a confidence (S03), even one
# that does not report it, because jev_cookbook.evaluation.noul_confidence and the Choice
# probability path are always in play (see CONTRIBUTING.md "Questions are narrow and typed").


def _readme_source_ids() -> set[str]:
    """The ``S<N>`` ids in the root README's generated "## Sources" table (rendered by
    tools/render_catalog.py's render_sources from this same catalog; see
    tests/test_recipe_sources.py's ``_readme_source_ids`` for the per-recipe equivalent)."""
    readme = (REPO / "README.md").read_text("utf-8")
    marker = "<!-- catalog:sources:start -->"
    end_marker = "<!-- catalog:sources:end -->"
    assert marker in readme and end_marker in readme, "README.md has no generated sources region"
    section = readme.split(marker, 1)[1].split(end_marker, 1)[0]
    return set(re.findall(r"\|\s*(S\d+)\s*\|", section))


README_SOURCE_IDS = _readme_source_ids()


def test_readme_sources_region_is_not_empty():
    # Otherwise every "known id" check below would pass vacuously.
    assert README_SOURCE_IDS


def test_catalog_has_sixty_recipes():
    assert len(RECIPES) == 60


def test_ranks_are_one_to_sixty_contiguous_and_in_order():
    ranks = [r["rank"] for r in RECIPES]
    assert ranks == list(range(1, 61))


def test_slugs_are_unique():
    slugs = [r["slug"] for r in RECIPES]
    assert len(slugs) == len(set(slugs)), f"duplicate slug in catalog/recipes.json: {slugs}"


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda r: r["slug"])
def test_slug_matches_the_nn_slug_convention_and_its_own_rank(recipe):
    match = SLUG_RE.match(recipe["slug"])
    assert match, f"{recipe['slug']!r} does not match the 'NN-slug' folder convention"
    assert int(match.group(1)) == recipe["rank"], (
        f"{recipe['slug']!r}'s numeric prefix does not match its rank {recipe['rank']}"
    )


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda r: r["slug"])
def test_decision_types_are_non_empty_and_known(recipe):
    decision_types = recipe.get("decision_types")
    assert decision_types, f"{recipe['slug']}: decision_types is empty"
    unknown = sorted(set(decision_types) - KNOWN_DECISION_TYPES)
    assert not unknown, f"{recipe['slug']}: unknown decision_types {unknown}"


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda r: r["slug"])
def test_sources_are_non_empty_sorted_unique_and_known(recipe):
    sources = recipe.get("sources")
    assert sources, f"{recipe['slug']}: sources is empty"
    not_an_id = [s for s in sources if not SOURCE_ID_RE.match(s)]
    assert not not_an_id, f"{recipe['slug']}: sources {not_an_id} are not 'S<digits>' ids"
    assert sources == sorted(sources), f"{recipe['slug']}: sources {sources} is not sorted by id"
    assert len(sources) == len(set(sources)), f"{recipe['slug']}: sources {sources} has a duplicate"
    unknown = sorted(set(sources) - README_SOURCE_IDS)
    assert not unknown, (
        f"{recipe['slug']}: sources {unknown} are not in the README's '## Sources' table"
    )


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda r: r["slug"])
def test_every_row_lists_primitives_and_confidence(recipe):
    missing = sorted(REQUIRED_SOURCES - set(recipe.get("sources", [])))
    assert not missing, f"{recipe['slug']}: missing required source(s) {missing}"
