"""Load a recipe's ``helpers.py`` by file path, without name collisions.

Every recipe may have a ``helpers.py``, and pytest runs every recipe's tests in one process, so
``import helpers`` cannot work: the second recipe would get the first one's module. ``load_helpers``
loads the file under a name made from the recipe folder, so two recipes never meet::

    from jev_cookbook import load_helpers

    helpers = load_helpers()  # in a notebook, whose working directory is the recipe folder
    helpers = load_helpers(Path(__file__).resolve().parent.parent)  # in recipe/tests/test_*.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from os import PathLike
from pathlib import Path
from types import ModuleType

HELPERS_FILE = "helpers.py"

# resolved path -> (SHA-256 of the file as loaded, module)
_loaded: dict[Path, tuple[str, ModuleType]] = {}


def helpers_module_name(recipe_dir: str | PathLike[str] | None = None) -> str:
    """The module name ``load_helpers`` gives a recipe's helpers, for example
    ``recipe_01_sentiment_classification_helpers`` for ``recipes/01-sentiment-classification``."""
    folder = _folder(recipe_dir)
    return (
        "recipe_" + (re.sub(r"\W+", "_", folder.name).strip("_").lower() or "recipe") + "_helpers"
    )


def _folder(recipe_dir: str | PathLike[str] | None) -> Path:
    return Path(recipe_dir if recipe_dir is not None else Path.cwd()).resolve()


def load_helpers(
    recipe_dir: str | PathLike[str] | None = None, *, reload: bool = False
) -> ModuleType:
    """Load ``recipe_dir/helpers.py`` (default: the current directory) and return the module.

    The module is named after the recipe folder (see ``helpers_module_name``), so recipes whose
    helpers define the same names do not collide. The result is cached per resolved path and
    file contents: repeated calls return the same module object while ``helpers.py`` is
    unchanged, and an edited file is executed again, so a running notebook never serves stale
    code. ``reload=True`` executes the file again even when it is unchanged.

    The module is in ``sys.modules`` only while its file executes (``dataclasses`` needs that)
    and is removed afterwards, along with nothing else: ``sys.path`` is never touched, and a
    different module that happened to hold the same name is put back. A consequence is that
    objects from helpers cannot be pickled by name; keep them out of anything that is pickled.

    Raises ``FileNotFoundError`` naming the folder when there is no ``helpers.py``; an
    exception raised by the file itself propagates unchanged and nothing is cached.
    """
    folder = _folder(recipe_dir)
    path = folder / HELPERS_FILE
    if not path.is_file():
        raise FileNotFoundError(f"{HELPERS_FILE} not found in recipe folder {folder.name!r}")
    source = path.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if not reload and path in _loaded and _loaded[path][0] == digest:
        return _loaded[path][1]
    name = helpers_module_name(folder)
    module = ModuleType(name)
    module.__file__ = str(path)
    missing = object()
    previous = sys.modules.get(name, missing)
    sys.modules[name] = module
    try:
        # Compile from the source, not through the import system's bytecode cache: that cache
        # trusts the file's mtime and size, so a quick edit could load stale code, and it would
        # write __pycache__ folders into recipes.
        # Bytes, not text: ``compile`` then honours a UTF-8 byte order mark (which Windows
        # PowerShell writes) and a coding cookie, as ``import`` would.
        exec(compile(source, str(path), "exec"), module.__dict__)
    finally:
        if previous is missing:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    _loaded[path] = (digest, module)
    return module
