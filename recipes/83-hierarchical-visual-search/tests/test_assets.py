"""Fixtures and authored PNG bytes reproduce; recorded answers are protected."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def generator(path):
    spec = importlib.util.spec_from_file_location(
        "recipe83_fixture_builder", path / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_recipe(tmp_path):
    copy = tmp_path / "recipe83"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        shutil.copyfile(RECIPE / name, copy / name)
    return copy


def build(path, *args):
    return subprocess.run(
        [sys.executable, str(path / "build_fixtures.py"), *args],
        capture_output=True,
        text=True,
    )


def test_generated_fixtures_and_pixels_match_committed_bytes(tmp_path):
    copy = copy_recipe(tmp_path)
    result = build(copy)
    assert result.returncode == 0, result.stderr
    for folder in ("fixtures", "assets"):
        expected = {path.name: path.read_bytes() for path in (RECIPE / folder).iterdir()}
        actual = {path.name: path.read_bytes() for path in (copy / folder).iterdir()}
        assert actual == expected


def test_malformed_existing_responses_fail_closed(tmp_path):
    module = generator(RECIPE)
    path = tmp_path / "responses.json"
    path.write_text("{broken", encoding="utf-8")
    assert module.is_recorded(path)
