"""Behaviour of build_fixtures.py beyond the scaffold's own checks (tests/test_build_fixtures.py
is fixed by tools/new_recipe.py): --force restores the exact committed bytes, and the first-stage
settings are frozen once per run."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def _copy(tmp_path):
    copy = tmp_path / "57-evidence-graph-updates"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    return copy


def test_force_restores_the_exact_committed_responses_bytes(tmp_path):
    copy = _copy(tmp_path)
    script = copy / "build_fixtures.py"
    assert subprocess.run([sys.executable, str(script)], capture_output=True).returncode == 0
    responses = copy / "fixtures" / "responses.json"
    data = json.loads(responses.read_text("utf-8"))
    for value in data.values():
        value["model"] = "jev-1.13.0"
    responses.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    forced = subprocess.run([sys.executable, str(script), "--force"], capture_output=True)
    assert forced.returncode == 0
    assert responses.read_bytes() == (RECIPE / "fixtures" / "responses.json").read_bytes()


def test_build_fixtures_freezes_the_first_stage_once_per_run(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "recipe57_build_fixtures_count", copy / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    original = module.helpers.freeze_stage_one

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module.helpers, "freeze_stage_one", counting)
    monkeypatch.setattr(sys, "argv", ["build_fixtures.py"])
    module.main()
    assert len(calls) == 1
