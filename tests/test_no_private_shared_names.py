"""#209: no recipe, and nothing the scaffolder emits, reaches into a private (underscore-prefixed)
name of the shared ``jev_cookbook`` package.

A leading underscore tells a reader the name is internal and may change without notice. Recipes
are what readers copy, so a recipe that imports ``jev_cookbook.live._dump`` teaches that reaching
into another module's privates is normal, and ties every recipe to a name the package is free to
change. The shared package exposes ``jev_cookbook.dump_responses`` instead. ``live._dump`` itself
stays as a supported alias for code written before the rename (see its comment in ``live.py``);
this test is about who may *use* a private name, not about whether it still exists.

The scan is syntactic on purpose and says so: it parses every ``.py`` under ``recipes/`` and each
notebook's code cells with ``ast`` and flags (a) ``from jev_cookbook[.x] import _name`` and (b) an
attribute access ``jev_cookbook.x._name`` through the imported package name. It does not follow
``getattr`` or ``importlib`` strings. The scaffold half scaffolds a real recipe and scans the
result, so the scaffolder is checked on what it emits, not on what its source text looks like.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RECIPES = REPO / "recipes"


def private_shared_uses(source: str) -> list[str]:
    """Every use of an underscore-prefixed name from ``jev_cookbook`` in ``source``."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "jev_cookbook":
            found += [f"from {node.module} import {a.name}" for a in node.names if a.name[0] == "_"]
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            parts = []
            cur = node.value
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id == "jev_cookbook":
                found.append(".".join(["jev_cookbook", *reversed(parts), node.attr]))
    return found


def python_sources(folder: Path):
    for path in sorted(folder.rglob("*.py")):
        yield path, path.read_text("utf-8")
    for path in sorted(folder.rglob("*.ipynb")):
        for cell in json.loads(path.read_text("utf-8"))["cells"]:
            if cell["cell_type"] == "code":
                yield path, "".join(cell["source"])


def test_the_detector_flags_what_it_claims_to():
    """Mutation proof: the old spellings are flagged, the public one is not."""
    assert private_shared_uses("from jev_cookbook.live import _dump") == [
        "from jev_cookbook.live import _dump"
    ]
    assert private_shared_uses("import jev_cookbook\njev_cookbook.live._dump({})") == [
        "jev_cookbook.live._dump"
    ]
    assert private_shared_uses("from jev_cookbook import dump_responses, get_backend") == []
    assert private_shared_uses("x._private; self._dump; from pathlib import _x") == []


def test_no_published_recipe_or_the_template_uses_a_private_shared_name():
    offenders = {}
    for path, source in python_sources(RECIPES):
        hits = private_shared_uses(source)
        if hits:
            offenders[path.relative_to(REPO).as_posix()] = hits
    assert not offenders, offenders


@pytest.mark.parametrize("mode", ["replay", "scripted"])
def test_the_scaffolder_emits_no_private_shared_name(tmp_path, mode):
    spec = importlib.util.spec_from_file_location(
        "new_recipe_private_names", REPO / "tools" / "new_recipe.py"
    )
    new_recipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(new_recipe)
    catalog = tmp_path / "recipes.json"
    shutil.copy(REPO / "catalog" / "recipes.json", catalog)
    out = tmp_path / "recipes"
    argv = ["4", "--catalog", str(catalog), "--recipes-dir", str(out)]
    if mode == "scripted":
        argv += ["--mode", "scripted"]
    assert new_recipe.main(argv) == 0
    emitted = list(python_sources(out))
    assert any(p.name == "notebook.ipynb" for p, _ in emitted)
    assert any(p.name == "test_build_fixtures.py" for p, _ in emitted) == (mode == "replay")
    for path, source in emitted:
        assert private_shared_uses(source) == [], path
