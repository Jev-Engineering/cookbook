"""Behaviour of build_fixtures.py beyond the scaffold's own checks (tests/test_build_fixtures.py
is fixed by tools/new_recipe.py): --force restores the exact committed bytes, and the first-stage
settings are frozen once per run. Unreadable or malformed responses require explicit --force."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "raw",
    [
        b'<<<<<<< recorded\n{"answer": {"model": "jev-1.13.0"}}\n=======\n{}\n>>>>>>> synthetic\n',
        b'{"answer":',
        b"",
        b'{"answer": "\xff"}',
        b"[]\n",
        b"null\n",
        b"42\n",
        b'"synthetic"\n',
        b"true\n",
        b'{"answer": null}\n',
        b'{"answer": {}}\n',
    ],
    ids=[
        "merge-markers",
        "truncated-json",
        "empty",
        "invalid-utf8",
        "array",
        "null",
        "number",
        "string",
        "boolean",
        "non-object-entry",
        "missing-model",
    ],
)
def test_ambiguous_responses_require_force_and_preserve_the_existing_bytes(tmp_path, raw):
    copy = _copy(tmp_path)
    folder = copy / "fixtures"
    folder.mkdir()
    responses = folder / "responses.json"
    responses.write_bytes(raw)
    for name in ("inputs.jsonl", "labels.jsonl"):
        (folder / name).write_bytes(b"corrupted")

    command = [sys.executable, str(copy / "build_fixtures.py")]
    refused = subprocess.run(command, capture_output=True, text=True)
    assert refused.returncode != 0
    assert "refusing to overwrite" in refused.stderr
    assert "--force" in refused.stderr
    assert "Traceback" not in refused.stderr
    assert responses.read_bytes() == raw
    # Refusal protects only responses; inputs and labels still regenerate from ROWS.
    for name in ("inputs.jsonl", "labels.jsonl"):
        assert (folder / name).read_bytes() == (RECIPE / "fixtures" / name).read_bytes()

    forced = subprocess.run([*command, "--force"], capture_output=True, text=True)
    assert forced.returncode == 0, forced.stderr
    assert responses.read_bytes() == (RECIPE / "fixtures" / "responses.json").read_bytes()


def test_valid_synthetic_responses_still_regenerate_without_force(tmp_path):
    copy = _copy(tmp_path)
    folder = copy / "fixtures"
    folder.mkdir()
    responses = folder / "responses.json"
    data = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    # A readable synthetic response object may have been reformatted.
    responses.write_text(json.dumps(data), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(copy / "build_fixtures.py")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert responses.read_bytes() == (RECIPE / "fixtures" / "responses.json").read_bytes()


@pytest.mark.parametrize("force", [False, True], ids=["refused", "explicit-force"])
def test_simulated_responses_read_failure_requires_force(tmp_path, force):
    """Inject a read error in a real subprocess; mode bits are unreliable when run as root."""
    copy = _copy(tmp_path)
    folder = copy / "fixtures"
    folder.mkdir()
    responses = folder / "responses.json"
    raw = b'{"recorded-answer": {"model": "jev-1.13.0"}}\n'
    responses.write_bytes(raw)
    driver = """
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

script = sys.argv[1]
sys.argv = sys.argv[1:]
original = Path.read_text

def unreadable(path, *args, **kwargs):
    if path.name == "responses.json":
        raise PermissionError("simulated read failure")
    return original(path, *args, **kwargs)

with patch.object(Path, "read_text", unreadable):
    runpy.run_path(script, run_name="__main__")
"""
    command = [sys.executable, "-c", driver, str(copy / "build_fixtures.py")]
    done = subprocess.run(
        [*command, *(["--force"] if force else [])], capture_output=True, text=True
    )
    if force:
        assert done.returncode == 0, done.stderr
        assert responses.read_bytes() == (RECIPE / "fixtures" / "responses.json").read_bytes()
    else:
        assert done.returncode != 0
        assert "refusing to overwrite" in done.stderr and "--force" in done.stderr
        assert "Traceback" not in done.stderr
        assert responses.read_bytes() == raw
    for name in ("inputs.jsonl", "labels.jsonl"):
        assert (folder / name).read_bytes() == (RECIPE / "fixtures" / name).read_bytes()


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


def test_a_row_with_no_candidate_has_no_request_and_does_not_move_the_frozen_settings(tmp_path):
    """The notebook sends no request for a mention with no candidate and skips the row when it
    freezes request 1's settings; the generator must do the same."""
    copy = _copy(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "recipe57_build_fixtures_nocandidate", copy / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    extra = (
        "v99-no-candidate",
        "validation",
        module._fields("Lena Smith", "O1", ("Local paper", "Lena Smith joined Brightwater Labs.")),
        {"entity": "no_match", "conflict": True, "update": module.NOTHING},
        None,
    )
    rows = [*module.ROWS, extra]
    requests = dict(module.requests_for(rows))
    assert requests["v99-no-candidate"] == []
    assert dict(module.requests_for(module.ROWS)).items() <= requests.items()
    assert module.stage_one_settings(rows) == module.stage_one_settings(module.ROWS)
    # the helpers path (ask_first, as the notebook runs it) skips the row the same way
    answered = {**module._first_results(module.ROWS), "v99-no-candidate": module.helpers.UNMATCHED}
    validation = [r for r in rows if r[1] == "validation"]
    from_helpers = module.helpers.freeze_stage_one(
        [answered[r[0]] for r in validation], [r[3] for r in validation]
    )
    assert from_helpers == module.stage_one_settings(rows)
    inputs, labels = module.build_inputs_and_labels(rows)
    assert [r["replay_keys"] for r in inputs if r["id"] == "v99-no-candidate"] == [[]]
    assert len(module.build_responses(rows)) == len(module.build_responses(module.ROWS))


def _module(tmp_path, name):
    copy = _copy(tmp_path)
    spec = importlib.util.spec_from_file_location(name, copy / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _with_spec(module, ident, replace):
    rows = []
    for row in module.ROWS:
        if row[0] == ident:
            probs, conflict, second = row[4]
            row = (*row[:4], (probs, conflict, replace(second)))
        rows.append(row)
    return rows


def test_a_second_answer_present_when_request_two_is_not_asked_is_refused(tmp_path):
    module = _module(tmp_path, "recipe57_build_fixtures_present")
    rows = _with_spec(module, "v07-conflict", lambda _second: (0.5, 0.5))
    with pytest.raises(ValueError, match=r"v07-conflict: request 2 is not asked .* absent"):
        module.requests_for(rows)


def test_a_second_answer_missing_when_request_two_is_asked_is_refused(tmp_path):
    module = _module(tmp_path, "recipe57_build_fixtures_missing")
    rows = _with_spec(module, "v01", lambda _second: None)
    with pytest.raises(ValueError, match=r"v01: request 2 is asked .* present"):
        module.requests_for(rows)


def test_a_row_with_candidates_but_no_spec_is_refused_by_name(tmp_path):
    """A row whose mention has candidates needs request 1's answers; a missing spec
    is an error that names the row, not a TypeError from unpacking None."""
    module = _module(tmp_path, "recipe57_build_fixtures_nospec")
    rows = [(*row[:4], None) if row[0] == "v01" else row for row in module.ROWS]
    with pytest.raises(ValueError, match=r"^v01: the mention has candidates"):
        module.requests_for(rows)


def test_unresolved_keys_tolerates_a_responses_file_that_is_not_valid_utf8(tmp_path):
    """The desynchronisation warning is advisory: a responses file whose bytes are not UTF-8
    must yield no keys, not an exception that replaces the refusal message."""
    module = _module(tmp_path, "recipe57_build_fixtures_unresolved")
    responses = tmp_path / "responses.json"
    responses.write_bytes(b'{"key": "\xff\xfe"}')
    assert module._unresolved_keys([{"replay_keys": ["key"]}], responses) == []
