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

import hashlib
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
RECIPES = CATALOG["recipes"]

SOURCE_ID_RE = re.compile(r"^S\d+$")
SLUG_RE = re.compile(r"^([0-9]{2}|100)-[a-z0-9]+(?:-[a-z0-9]+)*$")
KNOWN_DECISION_TYPES = {"Choice", "Noul", "Score", "Box"}
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


def test_catalog_has_one_hundred_recipes():
    assert len(RECIPES) == 100


def test_ranks_are_one_to_one_hundred_contiguous_and_in_order():
    ranks = [r["rank"] for r in RECIPES]
    assert ranks == list(range(1, 101))


def test_original_sixty_rows_are_preserved_exactly():
    # Frozen before the multimodal expansion (b4e39ce); includes rank/slug/issue mappings,
    # titles, use cases, levels and sources. Reordering JSON object keys is harmless.
    encoded = json.dumps(RECIPES[:60], sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == (
        "78b5452c5d4bb5f9a47d205bf92aee9562c34bfb4e52e2f7df70894439b4ac80"
    )


def test_tracks_partition_the_catalog_without_changing_recipe_numbers():
    tracks = CATALOG["tracks"]
    assert [(t["id"], t["first_rank"], t["last_rank"]) for t in tracks] == [
        ("original", 1, 60),
        ("multimodal", 61, 100),
    ]
    for recipe in RECIPES:
        assert sum(t["first_rank"] <= recipe["rank"] <= t["last_rank"] for t in tracks) == 1


def test_issue_assignments_are_unique_positive_integers_or_explicitly_unassigned():
    assigned = []
    for recipe in RECIPES:
        issue = recipe["issue"]
        assert issue is None or (type(issue) is int and issue > 0)
        if issue is not None:
            assigned.append(issue)
    assert len(assigned) == len(set(assigned))
    # Existing 61–100 issues track foundation work, not these new recipe ranks.
    assert not set(assigned) & set(range(61, 101))


# Rank -> recipe issue for the multimodal track, recorded from the issue titles
# ("Recipe <rank>: <catalog title>") on the owner decision of 2026-11-13. A rank is not its issue
# number; this table is the only place the pairs are typed, so a reassignment fails here.
MULTIMODAL_ISSUES = {
    61: 411, 62: 405, 63: 412, 64: 413, 65: 414, 66: 415, 67: 416, 68: 417, 69: 402, 70: 418,
    71: 419, 72: 420, 73: 421, 74: 422, 75: 423, 76: 424, 77: 403, 78: 425, 79: 426, 80: 406,
    81: 427, 82: 428, 83: 407, 84: 429, 85: 404, 86: 430, 87: 431, 88: 408, 89: 432, 90: 433,
    91: 434, 92: 435, 93: 436, 94: 437, 95: 409, 96: 438, 97: 439, 98: 410, 99: 440, 100: 441,
}  # fmt: skip


def test_multimodal_ranks_record_their_recipe_issues():
    assert sorted(MULTIMODAL_ISSUES.values()) == list(range(402, 442))
    assert {r["rank"]: r["issue"] for r in RECIPES if r["rank"] >= 61} == MULTIMODAL_ISSUES


def test_multimodal_rows_cite_images_and_box_rows_cite_box():
    by_url = {s["url"]: s["id"] for s in CATALOG["sources"]}
    images = by_url["https://docs.typesafe.ai/images"]
    box = by_url["https://docs.typesafe.ai/primitives/box"]
    for recipe in RECIPES[60:]:
        assert images in recipe["sources"]
        if "Box" in recipe["decision_types"]:
            assert box in recipe["sources"]


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
    assert match.group(1) == f"{recipe['rank']:02d}"


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
