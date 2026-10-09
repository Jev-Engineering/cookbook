"""build_fixtures.py follows the recipes/_template/build_fixtures.py pattern (#124, #129):
inputs/labels generation is separate from responses generation, a recorded responses.json is
never silently overwritten, and the committed file matches jev_cookbook.live's writer exactly."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from jev_cookbook.live import _dump

RECIPE = Path(__file__).resolve().parent.parent
SCRIPT = RECIPE / "build_fixtures.py"


def load_module_at(path, name):
    """Import build_fixtures.py by file path so its functions and module-level values (ROWS,
    build_responses) are plain Python objects, not subprocess output or a re-dump of the file
    it wrote."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_responses_are_byte_identical_to_the_recorders_writer():
    """jev_cookbook.live._dump sorts only the top-level keys; json.dumps(..., sort_keys=True)
    sorts every nested dict too and so disagrees with it on every response's field order. The
    committed file must match _dump exactly, not just agree with it on top-level order.

    Comparing against _dump(json.loads(raw)) (re-dumping the file's own parsed content) cannot
    catch a sort_keys=True regression: json.loads preserves whatever nested order the file
    already has, and _dump only re-sorts the top level, so that round trip would pass no matter
    which writer produced the file. Instead, import build_fixtures.py and compare against _dump
    of what build_responses computes directly from ROWS, independent of what main() actually
    wrote to disk."""
    raw = (RECIPE / "fixtures" / "responses.json").read_text("utf-8")
    module = load_module_at(SCRIPT, "recipe03_build_fixtures_for_test")
    assert len(module.ROWS) > 1
    assert raw == _dump(module.build_responses(module.ROWS))


def test_build_fixtures_separates_inputs_labels_from_responses(tmp_path):
    """Mutation check: regenerating must never silently overwrite a recorded responses.json,
    and --force must restore the exact synthetic bytes. (Removing the refusal in build_fixtures
    main() makes this test fail.)"""
    copy = tmp_path / "03-response-clarity-scoring"
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
    before = responses.read_bytes()

    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert responses.read_bytes() == before

    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True
    )
    assert forced.returncode == 0, forced.stderr
    after = json.loads(responses.read_text("utf-8"))
    assert all(v["model"] == "synthetic" for v in after.values())


def test_the_generator_reproduces_the_committed_fixtures(tmp_path):
    copy = tmp_path / "03-response-clarity-scoring"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    done = subprocess.run(
        [sys.executable, str(copy / "build_fixtures.py")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    for name in ("inputs.jsonl", "labels.jsonl", "responses.json"):
        assert (copy / "fixtures" / name).read_bytes() == (RECIPE / "fixtures" / name).read_bytes()
