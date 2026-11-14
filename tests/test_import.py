"""Importing jev_cookbook must not import the SDK, read a key, or touch the network."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import jev_cookbook

PROBE = r"""
import importlib.abc
import os
import sys

events = []


class BlockSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"typesafe", "typesafe_sdk"}:
            events.append("import " + name)
            raise ImportError("blocked by test: " + name)
        return None


class WatchedEnv(type(os.environ)):
    def __getitem__(self, key):
        if "TYPESAFE" in key or key.startswith("JEV_"):
            events.append("env " + key)
        return super().__getitem__(key)


def on_audit(event, args):
    if event.startswith(("socket.", "urllib.")):
        events.append(event)


sys.meta_path.insert(0, BlockSdk())
e = os.environ
os.environ = WatchedEnv(e._data, e.encodekey, e.decodekey, e.encodevalue, e.decodevalue)
sys.addaudithook(on_audit)

import jev_cookbook  # noqa: E402, F401

print("\n".join(events))
sys.exit(1 if events else 0)
"""


def test_package_has_version():
    assert isinstance(jev_cookbook.__version__, str)
    assert jev_cookbook.__version__


def test_import_has_no_side_effects():
    env = {
        k: v for k, v in os.environ.items() if k not in {"TYPESAFE_API_KEY", "JEV_COOKBOOK_LIVE"}
    }
    result = subprocess.run(
        [sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


# What `pip install -e ".[ml]"` and `".[live]"` bring in that no core module may import. The
# distribution names scikit-learn and typesafe-sdk are imported as `sklearn` and `typesafe_sdk`.
EXTRAS = ("sklearn", "scipy", "typesafe", "typesafe_sdk")

ML_PROBE = r"""
import importlib
import importlib.abc
import pkgutil
import sys

BLOCKED = __BLOCKED__

# A finder inserted now never sees a module that start-up code (a sitecustomize, a .pth file,
# PYTHONSTARTUP) already put in sys.modules, so a guard run in that interpreter would pass on the
# very mutation it exists to catch. Refuse to report a pass instead.
already = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)
if already:
    print("ALREADY IMPORTED before the guard was installed: " + ", ".join(already))
    print("Something at interpreter start-up imported it, so this probe cannot see who imports it.")
    sys.exit(2)

if len(sys.argv) > 1:  # a copy of the package to probe instead of the installed one
    sys.path.insert(0, sys.argv[1])

events = []
failures = []


def importer():
    # The first frame outside the import machinery is the module whose import statement ran
    # (frame 0 is this function, frame 1 the finder's find_spec).
    frame = sys._getframe(2)
    names = []
    first = None
    while frame is not None:
        name = frame.f_globals.get("__name__", "?")
        if not name.startswith(("importlib", "_frozen_importlib")):
            if first is None:
                first = f"{name} ({frame.f_code.co_filename}:{frame.f_lineno})"
            if not names or names[-1] != name:
                names.append(name)
        frame = frame.f_back
    return first, " <- ".join(names)


class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            where, chain = importer()
            events.append(f"BLOCKED {name}, imported by {where}; chain: {chain}")
            raise ImportError("blocked by test: " + name)
        return None


sys.meta_path.insert(0, Block())

modules = []
try:
    import jev_cookbook

    modules.append("jev_cookbook")
    for info in pkgutil.walk_packages(
        jev_cookbook.__path__,
        "jev_cookbook.",
        onerror=lambda name: failures.append(f"could not import {name}"),
    ):
        try:
            importlib.import_module(info.name)
            modules.append(info.name)
        except Exception as exc:
            failures.append(f"{info.name} failed: {type(exc).__name__}: {exc}")
except Exception as exc:
    failures.append(f"jev_cookbook failed: {type(exc).__name__}: {exc}")

if events or failures:
    print("\n".join(events + failures))
    sys.exit(1)
print(f"imported {len(modules)} modules from {jev_cookbook.__file__} without {', '.join(BLOCKED)}")
"""


def run_ml_probe(src=None, isolated=True, extra_env=None):
    """Run the probe in a fresh interpreter. Isolated (`-I`) ignores every PYTHON* variable and
    the user site; the environment is scrubbed of them anyway, as the probe above does for the
    variables that would change what it measures."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "TYPESAFE_", "JEV_"))}
    env.update(extra_env or {})
    code = ML_PROBE.replace("__BLOCKED__", repr(set(EXTRAS)))
    command = [sys.executable, *(["-I"] if isolated else []), "-c", code]
    command += [str(src)] if src else []
    return subprocess.run(command, env=env, capture_output=True, text=True, check=False)


def copy_of_the_package(tmp_path, vision_suffix=""):
    """A copy of `src/jev_cookbook` under `tmp_path/src`, with `vision_suffix` appended to one
    module (the installed tree is never touched)."""
    src = tmp_path / "src"
    shutil.copytree(
        Path(jev_cookbook.__file__).parent,
        src / "jev_cookbook",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    with (src / "jev_cookbook" / "vision.py").open("a", encoding="utf-8") as handle:
        handle.write("\n" + vision_suffix)
    return src


def plant_sitecustomize(tmp_path):
    """A directory for PYTHONPATH whose `sitecustomize.py` imports a stand-in `sklearn` before
    any test code runs (a stand-in, so this needs neither the extra nor the network)."""
    plant = tmp_path / "plant"
    (plant / "sklearn").mkdir(parents=True)
    (plant / "sklearn" / "__init__.py").write_text("", encoding="utf-8")
    (plant / "sitecustomize.py").write_text("import sklearn\n", encoding="utf-8")
    return plant


def test_the_package_imports_without_either_optional_extra():
    """The Tests jobs install the `ml` extra (#238) and the 3.14 job the `live` extra, so a core
    module that imported scikit-learn, SciPy or the SDK would no longer fail there: this keeps the
    dependency policy (the extras are for recipes and live runs, the package needs only the core
    dependencies) enforced by a test instead of by an install that happened to lack them. Every
    submodule is imported, not only what `jev_cookbook/__init__.py` pulls in, with all four names
    blocked."""
    result = run_ml_probe()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("imported "), result.stdout
    count = int(result.stdout.split()[1])
    assert count >= 19, result.stdout  # all of them, the subpackage included
    assert "BLOCKED" not in result.stdout


@pytest.mark.parametrize(
    ("line", "blocked"),
    [
        ("import sklearn\n", "sklearn"),
        ("from sklearn.naive_bayes import BernoulliNB\n", "sklearn"),
        ("import scipy.stats\n", "scipy"),
        ("import typesafe_sdk\n", "typesafe_sdk"),
        # swallowed: the import fails inside the module and the module still imports
        ("try:\n    import sklearn\nexcept ImportError:\n    sklearn = None\n", "sklearn"),
        ("import importlib\nimportlib.import_module('scipy')\n", "scipy"),
    ],
    ids=["plain", "from-submodule", "scipy", "sdk", "swallowed", "import_module"],
)
def test_the_guard_names_what_was_blocked_and_who_imported_it(tmp_path, line, blocked):
    """A failing guard says which package, which module and where; it never prints the success
    message (the first version printed `imported 19 modules without scikit-learn or scipy` as the
    whole output of a failure, for a swallowed import)."""
    src = copy_of_the_package(tmp_path, line)
    result = run_ml_probe(src)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"BLOCKED {blocked}," in result.stdout, result.stdout
    assert "imported by jev_cookbook.vision (" in result.stdout, result.stdout
    assert "vision.py:" in result.stdout, result.stdout
    assert "chain: jev_cookbook.vision" in result.stdout, result.stdout
    assert "modules from" not in result.stdout, result.stdout


def test_a_planted_sitecustomize_does_not_hide_a_real_import(tmp_path):
    """The guard runs isolated (`-I`), so a `sitecustomize.py` on PYTHONPATH that imports sklearn
    first is not even loaded, and the module-level import in the package is still caught. (Before
    this, the probe passed on exactly this mutation: the finder never saw an import that had
    already happened.)"""
    src = copy_of_the_package(tmp_path, "import sklearn\n")
    plant = plant_sitecustomize(tmp_path)
    result = run_ml_probe(src, extra_env={"PYTHONPATH": str(plant)})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BLOCKED sklearn," in result.stdout and "jev_cookbook.vision" in result.stdout


def test_start_up_imports_fail_the_guard_instead_of_passing_it(tmp_path):
    """Isolation is not the only way something imports a package before the finder exists (a
    `.pth` file in the environment does the same), so the probe also refuses a pass when a blocked
    name is already in `sys.modules`. Here the isolation is switched off to reproduce that."""
    src = copy_of_the_package(tmp_path, "import sklearn\n")
    plant = plant_sitecustomize(tmp_path)
    result = run_ml_probe(src, isolated=False, extra_env={"PYTHONPATH": str(plant)})
    assert result.returncode == 2, result.stdout + result.stderr
    assert "ALREADY IMPORTED" in result.stdout and "sklearn" in result.stdout
    assert "modules from" not in result.stdout
