"""Extra checks on build_fixtures.py that the scaffolded tests/test_build_fixtures.py (kept
byte-identical to the scaffold by the recipe guard) does not make: the exact bytes ``--force``
restores, and the spec check that keeps the second option ahead of the rest."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jev_cookbook import dump_responses

RECIPE = Path(__file__).resolve().parent.parent


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_force_restores_the_exact_synthetic_bytes(tmp_path):
    """After a recorded-looking responses.json, ``--force`` rewrites the file byte for byte as
    ``dump_responses(build_responses(ROWS))`` computes it, not merely with ``model`` reset."""
    copy = tmp_path / "51-stalled-loop-detection"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    script = copy / "build_fixtures.py"
    first = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    responses = copy / "fixtures" / "responses.json"
    data = json.loads(responses.read_text("utf-8"))
    for value in data.values():
        value["model"] = "jev-1.13.0"
    responses.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True
    )
    assert forced.returncode == 0, forced.stderr
    module = _load(script, "recipe51_build_fixtures_for_exact_bytes")
    assert responses.read_bytes() == dump_responses(module.build_responses(module.ROWS)).encode()


def test_a_spec_whose_remainder_would_tie_the_second_option_is_refused():
    """With top A at 86 and second R at 4 the remainder 10 splits 4, 3, 3 over the three other
    options, so the earliest of them would tie R at 4: the second option must lead the rest."""
    module = _load(RECIPE / "build_fixtures.py", "recipe51_build_fixtures_for_percentages")
    with pytest.raises(ValueError, match="second option must lead the rest"):
        module._percentages(("advancing", 86, "repeating", 4))
    assert sum(module._percentages(("advancing", 80, "repeating", 11)).values()) == 100


def test_a_spec_whose_top_two_shares_exceed_100_is_refused():
    module = _load(RECIPE / "build_fixtures.py", "recipe51_build_fixtures_for_overflow")
    with pytest.raises(ValueError, match="sum to at most 100"):
        module._percentages(("advancing", 84, "repeating", 20))
