"""Behaviour of build_fixtures.py beyond the scaffold's own checks (tests/test_build_fixtures.py
is fixed by tools/new_recipe.py): --force restores the exact committed bytes, and the first-stage
settings are frozen once per run."""

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
