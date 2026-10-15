"""Image reproduction and extra recorded-response overwrite protection."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from jev_cookbook.live import _dump

RECIPE = Path(__file__).resolve().parent.parent


def load_builder(path):
    spec = importlib.util.spec_from_file_location("recipe88_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_builder(tmp_path):
    for name in ("helpers.py", "build_fixtures.py"):
        (tmp_path / name).write_bytes((RECIPE / name).read_bytes())
    return tmp_path / "build_fixtures.py"


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


def test_responses_match_the_recorders_serialization():
    builder = load_builder(RECIPE / "build_fixtures.py")
    assert (RECIPE / "fixtures/responses.json").read_text("utf-8") == _dump(
        builder.build_responses(builder.ROWS)
    )


def test_all_fixture_and_image_bytes_reproduce(tmp_path):
    script = copy_builder(tmp_path)
    done = run(script)
    assert done.returncode == 0, done.stderr
    for directory in ("fixtures", "assets"):
        for original in (RECIPE / directory).iterdir():
            assert (tmp_path / directory / original.name).read_bytes() == original.read_bytes()


def test_recorded_response_is_preserved_until_explicit_force(tmp_path):
    script = copy_builder(tmp_path)
    assert run(script).returncode == 0
    path = tmp_path / "fixtures/responses.json"
    data = json.loads(path.read_text("utf-8"))
    for entry in data.values():
        entry["model"] = "jev-1.14.0"
        for answer in entry["answers"].values():
            answer["provenance"] = {
                "source": "recorded",
                "model": "jev-1.14.0",
                "date": "2026-10-14",
            }
    path.write_text(json.dumps(data), "utf-8")
    original = path.read_bytes()
    for name in ("inputs.jsonl", "labels.jsonl"):
        (tmp_path / "fixtures" / name).write_text("damaged", "utf-8")
    refused = run(script)
    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert path.read_bytes() == original
    builder = load_builder(script)
    inputs, labels = builder.build_inputs_and_labels(builder.ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        assert (tmp_path / "fixtures" / name).read_text("utf-8") == "".join(
            json.dumps(row) + "\n" for row in rows
        )
    forced = run(script, "--force")
    assert forced.returncode == 0, forced.stderr
    assert all(
        entry["model"] == "synthetic" for entry in json.loads(path.read_text("utf-8")).values()
    )
