"""Require a committed figure in every published recipe (#256).

``figure_titles_check_only`` and ``print_what_you_plot`` in ``test_recipe_guard.py``
are vacuous without this guard: both can pass when there are no plotting cells at all.
This check reads committed ``image/png`` outputs, independent of plotting idioms, and
does not execute notebooks. A source call, a printed table or a markdown image is not
a committed figure output.

Hard failure is the default. The issue's orchestrator ruling permits a named exemption
for a recipe genuinely better served by tables alone, with a stated reason and an
explicit pytest skip rather than a silent pass. The exemption dict is meant to stay
nearly empty; a foundation change must justify any addition. A stale exemption fails once a
figure is present, so it cannot hide a later accidental loss of that figure.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RECIPES_DIR = REPO / "recipes"
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
# Publication is notebook existence for a catalog slug, as in test_recipe_guard.py
# and test_recipe_sources.py. The scaffold _template is not a published recipe.
PUBLISHED = [
    recipe
    for recipe in CATALOG["recipes"]
    if (RECIPES_DIR / recipe["slug"] / "notebook.ipynb").is_file()
]
# Empty since #622 gave recipe 56 its figure: every published recipe now commits an
# image/png. An entry is a named, time-bounded known gap, not a table-only design decision,
# and it fails as stale as soon as a figure is committed. No recipe may use this route
# without its own orchestrator ruling.
NAMED_FIGURELESS_EXEMPTIONS: dict[str, str] = {}


def _has_committed_png(recipe_dir: Path) -> bool:
    notebook = json.loads((recipe_dir / "notebook.ipynb").read_text("utf-8"))
    return any(
        output.get("output_type") in {"display_data", "execute_result"}
        and output.get("data", {}).get("image/png")
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
        for output in cell.get("outputs", [])
    )


def _must_fail_not_skip(recipe_dir: Path, match: str) -> None:
    """Expect an assertion failure; reaching the exemption skip is a hard failure.

    ``pytest.raises(AssertionError)`` does not catch ``pytest.skip``, so a deleted
    check would otherwise turn its test into a green skip.
    """
    try:
        _require_committed_png(recipe_dir)
    except pytest.skip.Exception as skipped:
        pytest.fail(f"expected a failure, but the exemption skip was reached: {skipped}")
    except AssertionError as failure:
        assert re.search(match, str(failure)), str(failure)
    else:
        pytest.fail("expected a failure, but the guard passed")


def _require_committed_png(recipe_dir: Path) -> None:
    has_figure = _has_committed_png(recipe_dir)
    slug = recipe_dir.name
    if slug in NAMED_FIGURELESS_EXEMPTIONS:
        reason = NAMED_FIGURELESS_EXEMPTIONS[slug]
        assert isinstance(reason, str) and reason.strip(), (
            f"{slug}: exemption needs a stated reason"
        )
        assert not has_figure, f"{slug}: remove the stale figureless exemption; a PNG is present"
        pytest.skip(f"{slug}: {reason} (named figureless exemption)")
    assert has_figure, (
        f"{slug}/notebook.ipynb: no committed image/png output; commit at least one figure"
    )


def test_the_published_set_is_not_empty():
    assert PUBLISHED, "no published recipes were discovered; the figure guard would check nothing"


def test_figureless_exemptions_name_published_recipes():
    unknown = NAMED_FIGURELESS_EXEMPTIONS.keys() - {recipe["slug"] for recipe in PUBLISHED}
    assert not unknown, f"figureless exemptions must name published recipes: {sorted(unknown)}"


@pytest.mark.parametrize("recipe", PUBLISHED, ids=lambda recipe: recipe["slug"])
def test_every_published_recipe_has_a_committed_png(recipe):
    _require_committed_png(RECIPES_DIR / recipe["slug"])


def test_removing_the_png_from_a_passing_published_recipe_fails(tmp_path):
    # Recipe 41 prompted the issue. Test its actual committed notebook, then remove
    # only the PNG MIME entries in a throwaway copy, keeping source and text outputs.
    slug = "41-approval-scope-review"
    recipe_dir = tmp_path / slug
    recipe_dir.mkdir()
    notebook_path = recipe_dir / "notebook.ipynb"
    shutil.copyfile(RECIPES_DIR / slug / "notebook.ipynb", notebook_path)
    _require_committed_png(recipe_dir)

    notebook = json.loads(notebook_path.read_text("utf-8"))
    removed = 0
    for cell in notebook["cells"]:
        for output in cell.get("outputs", []):
            data = output.get("data", {})
            if "image/png" in data:
                del data["image/png"]
                removed += 1
    assert removed > 0, "mutation must remove at least one real committed PNG"
    notebook_path.write_text(json.dumps(notebook), "utf-8")

    with pytest.raises(
        AssertionError, match=f"{slug}/notebook.ipynb: no committed image/png output"
    ):
        _require_committed_png(recipe_dir)


def _write_notebook(tmp_path: Path, cells: list[dict], name: str = "figure-presence-probe") -> Path:
    recipe_dir = tmp_path / name
    recipe_dir.mkdir()
    (recipe_dir / "notebook.ipynb").write_text(json.dumps({"cells": cells}), "utf-8")
    return recipe_dir


@pytest.mark.parametrize("output_type", ["display_data", "execute_result"])
def test_a_png_output_counts_without_a_plot_helper_call(tmp_path, output_type):
    recipe_dir = _write_notebook(
        tmp_path,
        [
            {
                "cell_type": "code",
                "source": "display(an_image)",
                "outputs": [{"output_type": output_type, "data": {"image/png": "stored-png"}}],
            }
        ],
    )
    _require_committed_png(recipe_dir)


@pytest.mark.parametrize(
    "cells",
    [
        [],
        [{"cell_type": "code", "source": "plot_threshold_sweep(curve)", "outputs": []}],
        [
            {
                "cell_type": "code",
                "outputs": [{"output_type": "stream", "text": "image/png: a printed table"}],
            }
        ],
        [
            {
                "cell_type": "markdown",
                "source": "![figure](attachment:figure.png)",
                "attachments": {"figure.png": {"image/png": "stored-png"}},
            }
        ],
        *[
            [{"cell_type": "code", "outputs": [{"output_type": kind, "data": data}]}]
            for kind, data in [
                ("display_data", {"image/svg+xml": "<svg/>"}),
                ("display_data", {"text/plain": "image/png"}),
                ("display_data", {"image/png": ""}),
                ("execute_result", {"image/png": []}),
                ("stream", {"image/png": "stored-png"}),
            ]
        ],
    ],
    ids=[
        "empty-notebook",
        "unrendered-plot-call",
        "printed-table",
        "markdown-attachment",
        "svg-only",
        "mime-name-in-text",
        "empty-png-string",
        "empty-png-list",
        "png-in-a-stream",
    ],
)
def test_source_text_attachments_and_empty_pngs_do_not_satisfy_the_guard(tmp_path, cells):
    with pytest.raises(AssertionError, match="no committed image/png output"):
        _require_committed_png(_write_notebook(tmp_path, cells))


def test_a_named_exemption_reports_its_reason_as_a_skip(tmp_path, monkeypatch):
    recipe_dir = _write_notebook(tmp_path, [])
    monkeypatch.setitem(
        NAMED_FIGURELESS_EXEMPTIONS, recipe_dir.name, "A justified table-only design"
    )
    with pytest.raises(pytest.skip.Exception, match="A justified table-only design"):
        _require_committed_png(recipe_dir)


@pytest.mark.parametrize("reason", ["", " \n", None])
def test_a_reasonless_exemption_cannot_turn_a_missing_figure_into_a_skip(
    tmp_path, monkeypatch, reason
):
    recipe_dir = _write_notebook(tmp_path, [])
    monkeypatch.setitem(NAMED_FIGURELESS_EXEMPTIONS, recipe_dir.name, reason)
    _must_fail_not_skip(recipe_dir, "exemption needs a stated reason")


def test_an_exemption_for_an_unknown_recipe_fails(monkeypatch):
    monkeypatch.setitem(NAMED_FIGURELESS_EXEMPTIONS, "unpublished-probe", "A reason")
    with pytest.raises(AssertionError, match="figureless exemptions must name published recipes"):
        test_figureless_exemptions_name_published_recipes()


def _copy_notebook(tmp_path, slug, dest_name=None):
    recipe_dir = tmp_path / (dest_name or slug)
    recipe_dir.mkdir()
    shutil.copyfile(RECIPES_DIR / slug / "notebook.ipynb", recipe_dir / "notebook.ipynb")
    return recipe_dir


def test_a_figure_makes_its_exemption_stale(tmp_path, monkeypatch):
    slug = "41-approval-scope-review"
    recipe_dir = _copy_notebook(tmp_path, slug)
    monkeypatch.setitem(NAMED_FIGURELESS_EXEMPTIONS, slug, "A table-only design")
    _must_fail_not_skip(recipe_dir, "remove the stale figureless exemption")


@pytest.mark.parametrize(
    "lookalike",
    [
        "56-adversarial-harness-evaluationX",
        "56-adversarial-harness-evaluation-x",
        "56-adversarial-harness",
        "x56-adversarial-harness-evaluation",
    ],
)
def test_a_lookalike_slug_is_not_exempt(tmp_path, lookalike):
    recipe_dir = _write_notebook(tmp_path, [], name=lookalike)
    _must_fail_not_skip(recipe_dir, "no committed image/png output")
