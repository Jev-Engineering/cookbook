"""build_fixtures.py follows the recipes/_template/build_fixtures.py pattern: inputs and
labels generation is separate from responses generation, a recorded responses.json is never
silently overwritten, and the committed file matches jev_cookbook.live's writer exactly."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jev_cookbook.evaluation import score_level
from jev_cookbook.live import _dump

RECIPE = Path(__file__).resolve().parent.parent
SCRIPT = RECIPE / "build_fixtures.py"


def load_module_at(path, name):
    """Import build_fixtures.py by file path so its functions and module-level values (TASKS,
    build_responses) are plain Python objects, not subprocess output or a re-dump of the file
    it wrote."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jsonl(rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


MODULE = load_module_at(SCRIPT, "recipe28_build_fixtures_for_test")
ROWS = MODULE._rows(MODULE.TASKS)


def test_the_committed_responses_are_byte_identical_to_the_recorders_writer():
    """jev_cookbook.live._dump sorts only the top-level keys; json.dumps(..., sort_keys=True)
    sorts every nested dict too and so disagrees with it on every response's field order. The
    committed file must match _dump exactly, not just agree with it on top-level order.

    Comparing against _dump(json.loads(raw)) (re-dumping the file's own parsed content) cannot
    catch a sort_keys=True regression: json.loads preserves whatever nested order the file
    already has, and _dump only re-sorts the top level, so that round trip would pass no matter
    which writer produced the file. Instead, import build_fixtures.py and compare against _dump
    of what build_responses computes directly from TASKS, independent of what main() actually
    wrote to disk."""
    raw = (RECIPE / "fixtures" / "responses.json").read_text("utf-8")
    assert len(ROWS) > 1
    assert raw == _dump(MODULE.build_responses(ROWS))


def test_every_committed_stored_answers_top_choice_is_the_one_its_row_names():
    """CONTRIBUTING's rule 11: a fixture-building spec must never let the stored answer's own
    top choice silently drift from what the row itself says it should be. Every row in TASKS
    names its own ``intended_level`` directly, never defaulted or inferred from the gold level
    (two of the thirteen tasks' rows deliberately disagree: ``gold_level`` is what a skill
    really deserves, ``intended_level`` is the modal level the row's own probabilities are
    written to land on). This checks every one of the 39 committed rows against that
    declaration."""
    responses = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    questions = MODULE.helpers.build_questions()
    for ident, _split, fields, _gold_level, intended_level, _probabilities in ROWS:
        key = MODULE.replay_key(MODULE.helpers.build_state(fields), questions)
        stored = responses[key]
        answer = stored["answers"]["relevance"]
        from jev_cookbook import answer_from_dict

        level = score_level(answer_from_dict(answer))
        assert level == intended_level, f"{ident}: stored level {level}, row names {intended_level}"


def test_check_intended_levels_catches_a_mismatch():
    """Mutation proof for the test above: check_intended_levels (what build_fixtures.py itself
    runs before writing anything) must actually fail when a row's intended_level disagrees with
    what its probabilities land on, not merely pass by construction."""
    good = MODULE._rows(MODULE.TASKS)
    MODULE.check_intended_levels(good)  # no error on the real rows

    mutated = list(good)
    ident, split, fields, gold_level, intended_level, probabilities = mutated[0]
    mutated[0] = (ident, split, fields, gold_level, (intended_level + 1) % 4, probabilities)
    with pytest.raises(SystemExit, match="intended_level"):
        MODULE.check_intended_levels(mutated)


def test_retrieval_matches_every_tasks_own_spec():
    """TASKS names each task's candidates only implicitly, through their own dict keys;
    _rows() calls the real helpers.retrieve_candidates to decide which skills are asked about,
    and raises if retrieval ever disagrees with what a task's own spec names (so TASKS cannot
    silently drift from what the recipe's own retriever would actually return)."""
    for task_id, _split, task, specs in MODULE.TASKS:
        candidates = MODULE.helpers.retrieve_candidates(task)
        assert set(candidates) == set(specs), task_id


def test_build_fixtures_separates_inputs_labels_from_responses(tmp_path):
    """Mutation check: regenerating must never silently overwrite a recorded responses.json,
    and --force must restore the exact synthetic bytes. inputs.jsonl and labels.jsonl are
    rewritten from TASKS on every run, refused or not: only responses.json is guarded, and this
    also proves it by corrupting both files before the refused run and checking that they come
    back exactly as build_inputs_and_labels(rows) computes them, not merely "changed"."""
    copy = tmp_path / "28-skill-selection"
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
    module = load_module_at(script, "recipe28_build_fixtures_for_test_refused")
    rows = module._rows(module.TASKS)
    expected_inputs, expected_labels = module.build_inputs_and_labels(rows)
    assert inputs_path.read_text("utf-8") == _jsonl(expected_inputs)
    assert labels_path.read_text("utf-8") == _jsonl(expected_labels)

    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True
    )
    assert forced.returncode == 0, forced.stderr
    after = json.loads(responses.read_text("utf-8"))
    assert all(v["model"] == "synthetic" for v in after.values())


def test_the_generator_reproduces_the_committed_fixtures(tmp_path):
    copy = tmp_path / "28-skill-selection"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    done = subprocess.run(
        [sys.executable, str(copy / "build_fixtures.py")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    for name in ("inputs.jsonl", "labels.jsonl", "responses.json"):
        assert (copy / "fixtures" / name).read_bytes() == (RECIPE / "fixtures" / name).read_bytes()
