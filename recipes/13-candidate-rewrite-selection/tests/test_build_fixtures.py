"""build_fixtures.py: inputs and labels generation is separate from responses generation, a
recorded responses.json is never silently overwritten, and the committed file matches
jev_cookbook.live's writer exactly. Copied from recipes/_template/tests/test_build_fixtures.py
(tools/new_recipe.py's build_fixtures_test_text); keep the two in step."""

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


def _jsonl(rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


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
    module = load_module_at(SCRIPT, "recipe13_build_fixtures_for_test")
    assert len(module.ROWS) > 1
    assert raw == _dump(module.build_responses(module.ROWS))


def test_build_fixtures_separates_inputs_labels_from_responses(tmp_path):
    """Mutation check: regenerating must never silently overwrite a recorded responses.json,
    and --force must restore the exact synthetic bytes. inputs.jsonl and labels.jsonl are
    rewritten from ROWS on every run, refused or not: only responses.json is guarded, and this
    also proves it by corrupting both files before the refused run and checking that they come
    back exactly as build_inputs_and_labels(ROWS) computes them, not merely "changed"."""
    copy = tmp_path / "13-candidate-rewrite-selection"
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

    inputs_path = copy / "fixtures" / "inputs.jsonl"
    labels_path = copy / "fixtures" / "labels.jsonl"
    inputs_path.write_bytes(b"corrupted")
    labels_path.write_bytes(b"corrupted")

    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert responses.read_bytes() == before
    module = load_module_at(script, "recipe13_build_fixtures_for_test_refused")
    expected_inputs, expected_labels = module.build_inputs_and_labels(module.ROWS)
    assert inputs_path.read_text("utf-8") == _jsonl(expected_inputs)
    assert labels_path.read_text("utf-8") == _jsonl(expected_labels)

    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True
    )
    assert forced.returncode == 0, forced.stderr
    after = json.loads(responses.read_text("utf-8"))
    assert all(v["model"] == "synthetic" for v in after.values())


def test_the_generator_reproduces_the_committed_fixtures(tmp_path):
    copy = tmp_path / "13-candidate-rewrite-selection"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    done = subprocess.run(
        [sys.executable, str(copy / "build_fixtures.py")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    for name in ("inputs.jsonl", "labels.jsonl", "responses.json"):
        assert (copy / "fixtures" / name).read_bytes() == (RECIPE / "fixtures" / name).read_bytes()
