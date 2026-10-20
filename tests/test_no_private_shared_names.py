"""#209: no recipe, and nothing the scaffolder emits, reaches into a private (underscore-prefixed)
name of the shared ``jev_cookbook`` package.

A leading underscore tells a reader the name is internal and may change without notice. Recipes
are what readers copy, so a recipe that imports ``jev_cookbook.live._dump`` teaches that reaching
into another module's privates is normal, and ties every recipe to a name the package is free to
change. The shared package exposes ``jev_cookbook.dump_responses`` instead. ``live._dump`` itself
stays as a supported alias for code written before the rename (see its comment in ``live.py``);
this test is about who may *use* a private name, not about whether it still exists.

The scan is syntactic on purpose and says so: it parses every ``.py`` under ``recipes/`` and each
notebook's code cells with ``ast`` and flags (a) any import whose dotted path has a private segment
(``jev_cookbook._canonical``, ``jev_cookbook.fixtures._scan``), (b) an imported underscore name
(``from jev_cookbook.live import _dump``), and (c) a private attribute reached through a local name
bound to the package or one of its modules or subpackages (``live._dump``). Dunders such as
``__version__`` are public. It does not follow ``getattr`` or ``importlib`` strings. The scaffold
half scaffolds a real recipe and scans the result, so the scaffolder is checked on what it emits,
not on what its source text looks like.
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


PACKAGE = REPO / "src" / "jev_cookbook"
# Every module or subpackage a recipe could bind a local name to: ``*.py`` stems and package
# directories (``fixtures``).
SUBMODULES = {path.stem for path in PACKAGE.glob("*.py")} | {
    path.parent.name for path in PACKAGE.glob("*/__init__.py")
}


def is_private(name: str) -> bool:
    """A leading underscore that is not a dunder: ``_dump`` and ``_canonical`` are private,
    ``__version__`` is public."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def private_shared_uses(source: str) -> list[str]:
    """Every use of a private name or module of ``jev_cookbook`` in ``source``: an import whose
    dotted path has a private segment, an imported private name, or a private attribute reached
    through a local name bound to the package or one of its modules."""
    tree = ast.parse(source)
    roots = {"jev_cookbook"}  # local names that stand for jev_cookbook or one of its modules
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] != "jev_cookbook":
                    continue
                if any(is_private(seg) for seg in a.name.split(".")):
                    found.append(f"import {a.name}")
                if a.asname:
                    roots.add(a.asname)
        elif (
            isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "jev_cookbook"
        ):
            if any(is_private(seg) for seg in node.module.split(".")):
                found.append(f"from {node.module} import ...")
            for a in node.names:
                if is_private(a.name):
                    found.append(f"from {node.module} import {a.name}")
                if a.name in SUBMODULES:
                    roots.add(a.asname or a.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and is_private(node.attr):
            parts = []
            cur = node.value
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id in roots:
                found.append(".".join([cur.id, *reversed(parts), node.attr]))
    return found


def python_sources(folder: Path):
    for path in sorted(folder.rglob("*.py")):
        yield path, path.read_text("utf-8")
    for path in sorted(folder.rglob("*.ipynb")):
        for cell in json.loads(path.read_text("utf-8"))["cells"]:
            if cell["cell_type"] == "code":
                yield path, "".join(cell["source"])


@pytest.mark.parametrize(
    "source",
    [
        "from jev_cookbook.live import _dump",
        "import jev_cookbook\njev_cookbook.live._dump({})",
        "import jev_cookbook.live as live\nlive._dump({})",
        "from jev_cookbook import live as L\nL._dump({})",
        "from jev_cookbook import _canonical",
        "from jev_cookbook.vision import _MAX_IMAGE_BYTES",
        # private modules, by every spelling
        "from jev_cookbook._canonical import plain_json",
        "import jev_cookbook._canonical",
        "import jev_cookbook._canonical as c",
        "from jev_cookbook.fixtures._scan import scan_text",
        "import jev_cookbook.fixtures._schema as s",
        "from jev_cookbook import fixtures\nfixtures._scan",
    ],
)
def test_the_detector_flags_every_private_spelling(source):
    """Mutation proof: each way of reaching a private name or module is reported."""
    assert private_shared_uses(source), source


@pytest.mark.parametrize(
    "source",
    [
        "from jev_cookbook import dump_responses, get_backend",
        "from jev_cookbook.fixtures import load_inputs, responses_path",
        "import jev_cookbook\nprint(jev_cookbook.__version__)",
        "from jev_cookbook import __version__",
        "x._private; self._dump; from pathlib import _x",
        "import os._exit_hooks_are_not_ours",
    ],
)
def test_the_detector_does_not_flag_public_or_foreign_names(source):
    """Dunders are public, and a private name from another package is not this guard's concern."""
    assert private_shared_uses(source) == [], source


def test_submodules_include_the_fixtures_package_and_the_flat_modules():
    assert {"live", "vision", "fixtures", "_canonical"} <= SUBMODULES


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
