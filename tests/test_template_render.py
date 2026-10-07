"""The catalog renderer does not treat recipes/_template as a recipe."""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "render_catalog.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("render_catalog_for_template_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_template_is_not_a_catalog_slug():
    catalog = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
    assert "_template" not in {r["slug"] for r in catalog["recipes"]}


def test_a_template_folder_changes_nothing_in_the_rendered_readme(tmp_path, monkeypatch):
    tool = load_tool()
    catalog = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
    readme = (REPO / "README.md").read_text("utf-8")
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    before = tool.render(readme, catalog)
    template = tmp_path / "recipes" / "_template"
    template.mkdir(parents=True)
    (template / "notebook.ipynb").write_text("{}", encoding="utf-8")
    assert not any(tool.is_published(r) for r in catalog["recipes"])
    assert tool.render(readme, catalog) == before
    assert "published" in before and "0 of 60" in before
