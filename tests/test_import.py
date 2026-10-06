"""Importing jev_cookbook must not import the SDK, read a key, or touch the network."""

import os
import subprocess
import sys

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
