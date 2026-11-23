"""Load a Python module by path for tests that work with tools or temporary recipe files."""

import importlib.util
import sys


def load_module_at(path, name):
    """Import a .py file so its functions and module-level values are plain Python objects."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_module_at_isolated(path, name):
    """Like load_module_at, but leave ``sys.modules`` as it was.

    Executing a test module a second time re-registers the private tool modules it loads (for
    example ``check_recipe_scope.py_for_recipe_guard``), replacing the copy the first load's
    functions belong to. Restore the table so identity assertions hold in any collection order.
    """
    saved = dict(sys.modules)
    try:
        return load_module_at(path, name)
    finally:
        for key in set(sys.modules) - set(saved):
            del sys.modules[key]
        sys.modules.update(saved)
