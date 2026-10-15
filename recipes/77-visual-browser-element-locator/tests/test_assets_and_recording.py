"""The authoring script reproduces assets and never silently replaces recorded answers."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jev_cookbook.live import _dump

RECIPE = Path(__file__).resolve().parent.parent


def generator(path):
    spec = importlib.util.spec_from_file_location("recipe77_generator_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_generator(tmp_path):
    target = tmp_path / "recipe"
    target.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (target / name).write_bytes((RECIPE / name).read_bytes())
    return target


def run_generator(target, *args):
    return subprocess.run(
        [sys.executable, str(target / "build_fixtures.py"), *args], capture_output=True, text=True
    )


def test_generator_reproduces_every_fixture_and_screenshot(tmp_path):
    target = copy_generator(tmp_path)
    result = run_generator(target)
    assert result.returncode == 0, result.stderr
    for folder in ("fixtures", "assets"):
        actual = {p.name: p.read_bytes() for p in (target / folder).iterdir()}
        expected = {p.name: p.read_bytes() for p in (RECIPE / folder).iterdir()}
        assert actual == expected


def test_responses_use_exact_recorder_serialization(tmp_path):
    target = copy_generator(tmp_path)
    module = generator(target / "build_fixtures.py")
    responses = module.build_responses(module.ROWS, target)
    assert (RECIPE / "fixtures" / "responses.json").read_text("utf-8") == _dump(responses)


def test_recorded_guard_preserves_answers_but_regenerates_inputs_and_labels(tmp_path):
    target = copy_generator(tmp_path)
    first = run_generator(target)
    assert first.returncode == 0, first.stderr
    path = target / "fixtures" / "responses.json"
    data = json.loads(path.read_text("utf-8"))
    next(iter(data.values()))["model"] = "jev-1.14.0"
    path.write_text(json.dumps(data), encoding="utf-8")
    protected_bytes = path.read_bytes()
    for name in ("inputs.jsonl", "labels.jsonl"):
        (target / "fixtures" / name).write_text("broken", encoding="utf-8")
    refused = run_generator(target)
    assert refused.returncode != 0 and "--force" in refused.stderr and "recorded" in refused.stderr
    assert path.read_bytes() == protected_bytes
    for name in ("inputs.jsonl", "labels.jsonl"):
        assert (target / "fixtures" / name).read_bytes() == (
            RECIPE / "fixtures" / name
        ).read_bytes()
    forced = run_generator(target, "--force")
    assert forced.returncode == 0, forced.stderr
    assert path.read_bytes() == (RECIPE / "fixtures" / "responses.json").read_bytes()


def test_malformed_response_file_is_also_protected(tmp_path):
    target = copy_generator(tmp_path)
    assert run_generator(target).returncode == 0
    path = target / "fixtures" / "responses.json"
    path.write_text("{broken", encoding="utf-8")
    refused = run_generator(target)
    assert refused.returncode != 0 and path.read_text("utf-8") == "{broken"


@pytest.mark.parametrize(
    "data", [{"key": {"model": "synthetic"}}, {"key": {"model": "synthetic", "answers": {}}}]
)
def test_structurally_malformed_response_is_protected(tmp_path, data):
    target = copy_generator(tmp_path)
    module = generator(target / "build_fixtures.py")
    path = target / "responses.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert module.protected(path)
