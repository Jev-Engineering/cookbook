"""Tests for tools/render_catalog.py, run against throwaway project trees.

The tool locates the project through its module-level ROOT. Every test points ROOT at a
temporary directory, so nothing here reads or writes the real README.md, catalog/ or recipes/.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "render_catalog.py"
REGION_NAMES = ["progress", "levels", "categories", "recipes", "sources"]

CATALOG = {
    "title": "Test catalog",
    "levels": [
        {"level": 1, "name": "Beginner", "scope": "One bounded judgment."},
        {"level": 2, "name": "Intermediate", "scope": "Several judgments."},
    ],
    "sources": [
        {"id": "S01", "reference": "Docs", "url": "https://example.test/docs", "supports": "Facts"}
    ],
    "recipes": [
        {
            "rank": 1,
            "slug": "01-alpha",
            "title": "Alpha",
            "level": 1,
            "category": "Cat A",
            "decision_types": ["Choice"],
            "use_case": "First use case.",
            "issue": 11,
        },
        {
            "rank": 2,
            "slug": "02-beta",
            "title": "Beta",
            "level": 2,
            "category": "Cat B",
            "decision_types": ["Choice", "Score"],
            "use_case": "Second use case.",
        },
    ],
}


@pytest.fixture(scope="module")
def tool_module():
    spec = importlib.util.spec_from_file_location("render_catalog_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_readme(body: str = "") -> str:
    parts = ["# Title\n\nHand-written intro.\n"]
    for name in REGION_NAMES:
        parts.append(f"\n<!-- catalog:{name}:start -->\n{body}<!-- catalog:{name}:end -->\n")
    parts.append("\nHand-written outro.\n")
    return "".join(parts)


@pytest.fixture
def project(tmp_path, tool_module, monkeypatch):
    """A temporary project tree with a catalog and an empty-region README."""
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "recipes.json").write_text(json.dumps(CATALOG), encoding="utf-8")
    (tmp_path / "README.md").write_text(make_readme(), encoding="utf-8", newline="\n")
    monkeypatch.setattr(tool_module, "ROOT", tmp_path)
    return tmp_path


def publish(project: Path, slug: str) -> None:
    folder = project / "recipes" / slug
    folder.mkdir(parents=True)
    (folder / "notebook.ipynb").write_text("{}", encoding="utf-8")


def run_main(tool_module, monkeypatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["render_catalog.py", *args])
    return tool_module.main()


# Region replacement


def test_render_fills_every_region_and_keeps_prose(project, tool_module):
    out = tool_module.render(make_readme(), CATALOG)
    assert out.startswith("# Title\n\nHand-written intro.\n")
    assert out.endswith("Hand-written outro.\n")
    assert "**Alpha**<br>First use case." in out
    assert "| **Cat A** | 1 | 1 | `01` |" in out
    assert "| S01 | [Docs](https://example.test/docs) | Facts |" in out
    assert "`Choice` + `Score`" in out
    assert (
        "| **1** | [Beginner](#level-1--beginner) | One bounded judgment. | 1<br><sub>01 to 01</sub> |"
        in out
    )
    assert "| **2** | [Intermediate](#level-2--intermediate) | Several judgments. |" in out
    assert "Categories-2-" in out
    assert "Levels-2-" in out


def test_render_replaces_stale_region_content(project, tool_module):
    out = tool_module.render(make_readme("STALE CONTENT\n"), CATALOG)
    assert "STALE CONTENT" not in out
    for name in REGION_NAMES:
        assert out.count(f"<!-- catalog:{name}:start -->") == 1
        assert out.count(f"<!-- catalog:{name}:end -->") == 1


def test_render_is_idempotent(project, tool_module):
    once = tool_module.render(make_readme(), CATALOG)
    assert tool_module.render(once, CATALOG) == once


def test_render_leaves_text_outside_regions_untouched(project, tool_module):
    readme = make_readme().replace("Hand-written outro.", "Edited outro, still mine.")
    out = tool_module.render(readme, CATALOG)
    assert out.startswith("# Title\n\nHand-written intro.\n")
    assert out.endswith("Edited outro, still mine.\n")
    # Each marker pair stays on its own lines, so the regions remain replaceable.
    for name in REGION_NAMES:
        assert f"<!-- catalog:{name}:start -->\n" in out
        assert f"\n<!-- catalog:{name}:end -->\n" in out


def test_render_missing_markers_exits_naming_the_region(project, tool_module):
    readme = make_readme().replace("<!-- catalog:sources:start -->\n", "")
    with pytest.raises(SystemExit) as excinfo:
        tool_module.render(readme, CATALOG)
    assert "catalog:sources" in str(excinfo.value)


# Published detection


def test_unpublished_recipes_are_coming_soon(project, tool_module):
    out = tool_module.render(make_readme(), CATALOG)
    assert "Coming soon · [#11](https://github.com/Jev-Engineering/cookbook/issues/11)" in out
    assert "Open notebook" not in out
    assert "0 of 2 published" in out
    assert "Status-coming%20soon" in out


def test_notebook_marks_a_recipe_published(project, tool_module):
    publish(project, "01-alpha")
    assert tool_module.is_published(CATALOG["recipes"][0])
    assert not tool_module.is_published(CATALOG["recipes"][1])
    out = tool_module.render(make_readme(), CATALOG)
    assert "[Open notebook](recipes/01-alpha/notebook.ipynb)" in out
    assert "1 of 2 published" in out
    assert "Status-in%20progress" in out
    # The other recipe is still listed as coming soon, without an issue link.
    assert "| Coming soon |" in out


def test_all_notebooks_present_is_complete(project, tool_module):
    publish(project, "01-alpha")
    publish(project, "02-beta")
    out = tool_module.render(make_readme(), CATALOG)
    assert "2 of 2 published" in out
    assert "Status-complete" in out
    assert "Coming soon" not in out


def test_folder_without_notebook_is_not_published(project, tool_module):
    (project / "recipes" / "01-alpha").mkdir(parents=True)
    (project / "recipes" / "01-alpha" / "README.md").write_text("notes", encoding="utf-8")
    assert not tool_module.is_published(CATALOG["recipes"][0])


def test_notebook_directory_is_not_a_notebook(project, tool_module):
    (project / "recipes" / "01-alpha" / "notebook.ipynb").mkdir(parents=True)
    assert not tool_module.is_published(CATALOG["recipes"][0])


# --check exit codes


def test_check_exits_1_with_message_on_stale_readme(project, tool_module, monkeypatch, capsys):
    before = (project / "README.md").read_bytes()
    assert run_main(tool_module, monkeypatch, "--check") == 1
    assert "out of date" in capsys.readouterr().out
    assert (project / "README.md").read_bytes() == before, "--check must not write"


def test_check_exits_0_when_readme_is_current(project, tool_module, monkeypatch, capsys):
    assert run_main(tool_module, monkeypatch) == 0
    capsys.readouterr()
    assert run_main(tool_module, monkeypatch, "--check") == 0
    assert capsys.readouterr().out == ""


def test_check_detects_a_hand_edit_inside_a_region(project, tool_module, monkeypatch):
    run_main(tool_module, monkeypatch)
    readme = project / "README.md"
    text = readme.read_text(encoding="utf-8").replace("Alpha", "Altered")
    readme.write_text(text, encoding="utf-8", newline="\n")
    assert run_main(tool_module, monkeypatch, "--check") == 1


def test_check_goes_stale_when_a_notebook_appears(project, tool_module, monkeypatch):
    run_main(tool_module, monkeypatch)
    assert run_main(tool_module, monkeypatch, "--check") == 0
    publish(project, "01-alpha")
    assert run_main(tool_module, monkeypatch, "--check") == 1


def test_write_mode_rewrites_readme_and_reports(project, tool_module, monkeypatch, capsys):
    assert run_main(tool_module, monkeypatch) == 0
    assert "README.md updated" in capsys.readouterr().out
    assert "**Beta**" in (project / "README.md").read_text(encoding="utf-8")
    # Raw bytes: text mode would fold CRLF into LF and hide a wrong newline setting.
    assert b"\r" not in (project / "README.md").read_bytes()
    # A second run has nothing to do and says nothing.
    assert run_main(tool_module, monkeypatch) == 0
    assert capsys.readouterr().out == ""


def test_check_with_missing_markers_exits_nonzero(project, tool_module, monkeypatch):
    (project / "README.md").write_text("# no markers\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        run_main(tool_module, monkeypatch, "--check")
    assert excinfo.value.code not in (0, None)
