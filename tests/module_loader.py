"""Load a Python module by path for tests that work with tools or temporary recipe files."""

import importlib.util


def load_module_at(path, name):
    """Import a .py file so its functions and module-level values are plain Python objects."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
