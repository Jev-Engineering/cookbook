"""Additional protection and reproducibility checks for the second model arm and images."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from jev_cookbook.live import _dump

RECIPE = Path(__file__).resolve().parent.parent


def test_second_arm_and_all_images_reproduce_and_recorded_second_arm_is_protected(tmp_path):
    copy = tmp_path / "recipe-copy"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    command = [sys.executable, str(copy / "build_fixtures.py")]
    done = subprocess.run(command, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    second = "responses-jev-1.14.0.json"
    assert (copy / "fixtures" / second).read_bytes() == (RECIPE / "fixtures" / second).read_bytes()
    for image in (RECIPE / "assets").glob("*.png"):
        assert (copy / "assets" / image.name).read_bytes() == image.read_bytes()
    spec = importlib.util.spec_from_file_location(
        "recipe96_second_arm", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (RECIPE / "fixtures" / second).read_text() == _dump(
        module.build_responses(module.ROWS, 1)
    )
    path = copy / "fixtures" / second
    records = json.loads(path.read_text())
    for record in records.values():
        record["model"] = "jev-1.14.0"
    path.write_text(json.dumps(records))
    before = {p.name: p.read_bytes() for p in (copy / "fixtures").glob("responses*.json")}
    refused = subprocess.run(command, capture_output=True, text=True)
    assert refused.returncode != 0 and "--force" in refused.stderr
    assert all((copy / "fixtures" / name).read_bytes() == data for name, data in before.items())
    forced = subprocess.run(command + ["--force"], capture_output=True, text=True)
    assert forced.returncode == 0, forced.stderr
    assert path.read_bytes() == (RECIPE / "fixtures" / second).read_bytes()
