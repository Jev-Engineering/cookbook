"""Exercise chronological reasoning, sampling limits and the actual frozen policy."""

import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
EXAMPLES = load_inputs(RECIPE)
LABELS = load_labels(RECIPE)


def example(ident):
    return next(row for row in EXAMPLES if row.id == ident)


def answer(value):
    return NoulAnswer(value, Provenance.synthetic())


def results_for(rows):
    runner = helpers.SessionRunner(get_backend(fixtures=responses_path(RECIPE)), root=RECIPE)
    return {row.id: runner.decide(row.fields) for row in rows}


def test_stored_answers_are_not_all_right():
    validation = [row for row in EXAMPLES if row.split == "validation"]
    results = results_for(validation)
    threshold, _ = helpers.select_policy(
        validation, results, LABELS, objective="correct_minus_four_errors"
    )
    assert threshold == 0.6
    heldout = [row for row in EXAMPLES if row.split == "test"]
    test_results = results_for(heldout)
    outcomes = [
        helpers.route(row.fields, test_results[row.id].answers, threshold) for row in heldout
    ]
    assert any(
        out.accepted and out.event != LABELS[row.id]["event"]
        for row, out in zip(heldout, outcomes, strict=True)
    )
    wrong = outcomes[next(i for i, row in enumerate(heldout) if row.id == "t10")]
    assert wrong.accepted and wrong.event == 9000 and LABELS["t10"]["event"] == 5400


def test_notebook_pins_policy_objective_and_freezes_before_test():
    cells = json.loads((RECIPE / "notebook.ipynb").read_text())["cells"]
    sources = {cell["id"]: "".join(cell["source"]) for cell in cells}
    source = sources["evaluation-validation"]
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "select_policy"
    ]
    assert len(calls) == 1
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in calls[0].keywords}
    assert keywords == {"objective": "correct_minus_four_errors"}
    assert list(sources).index("evaluation-validation") < list(sources).index("evaluation-test")
    with pytest.raises(ValueError, match="validation"):
        helpers.select_policy([example("t01")], {}, LABELS, objective=helpers.OBJECTIVE)
    with pytest.raises(ValueError, match="objective"):
        helpers.select_policy([example("v01")], {}, LABELS, objective="coverage")


def test_request_is_complete_bounded_history_without_labels():
    row = example("v01")
    state, questions, assets = helpers.request(row.fields, RECIPE)
    assert len(state["frames"]) == 8 and len(state["logs"]) >= 211
    assert len(questions) == 15 and len(assets) == 8
    assert [frame["timestamp_seconds"] for frame in state["frames"]] == list(range(0, 12601, 1800))
    assert all(question.type == "noul" for question in questions.values())
    assert state["logs"] == sorted(state["logs"], key=lambda event: event["timestamp_seconds"])
    changed = copy.deepcopy(row.fields)
    changed.update(label="secret answer", split="test", render_plan={"collapsed": True})
    assert helpers.request(changed, RECIPE) == (state, questions, assets)
    assert all(frame["image"].startswith("image:sha256:") for frame in state["frames"])
    for asset in assets.values():
        assert set(asset) == {"type", "format", "data_base64"}


def test_stored_keys_bind_pixels_questions_and_history(tmp_path):
    row = example("v01")
    state, questions, assets = helpers.request(row.fields, RECIPE)
    key = replay_key(state, questions, assets=assets)
    assert row.replay_keys == (key,)
    modified_state = copy.deepcopy(state)
    modified_state["logs"][0]["message"] += "changed"
    assert replay_key(modified_state, questions, assets=assets) != key
    modified_time = copy.deepcopy(row.fields)
    modified_time["frames"][0]["timestamp_seconds"] += 1
    new_state, new_questions, new_assets = helpers.request(modified_time, RECIPE)
    assert replay_key(new_state, new_questions, assets=new_assets) != key
    reference = next(iter(assets))
    source = RECIPE / helpers.ordered_frames(row.fields)[0]["path"]
    with Image.open(source) as image:
        image.putpixel((479, 359), (1, 2, 3))
        image.save(tmp_path / "changed.png")
    changed_assets = dict(assets)
    changed_assets[reference] = image_asset(tmp_path / "changed.png")
    assert replay_key(state, questions, assets=changed_assets) != key


def test_sort_is_not_filename_or_input_order():
    fields = copy.deepcopy(example("v01").fields)
    original = helpers.request(fields, RECIPE)
    fields["frames"].reverse()
    fields["logs"].reverse()
    assert helpers.request(fields, RECIPE) == original


@pytest.mark.parametrize("bad_time", [-1, float("nan"), float("inf"), True, "1800"])
def test_invalid_timestamps_are_rejected_before_a_call(bad_time):
    fields = copy.deepcopy(example("v01").fields)
    fields["frames"][0]["timestamp_seconds"] = bad_time
    runner = helpers.SessionRunner(SimpleNamespace(), root=RECIPE)
    with pytest.raises(ValueError):
        runner.decide(fields)
    assert runner.calls == 0


def test_duplicate_times_and_oversized_history_are_rejected():
    fields = copy.deepcopy(example("v01").fields)
    fields["frames"][0]["timestamp_seconds"] = fields["frames"][1]["timestamp_seconds"]
    with pytest.raises(ValueError, match="duplicate"):
        helpers.request(fields, RECIPE)
    fields = copy.deepcopy(example("v01").fields)
    fields["frames"].append(fields["frames"][0])
    with pytest.raises(ValueError, match="frame count"):
        helpers.request(fields, RECIPE)
    fields = copy.deepcopy(example("v01").fields)
    fields["logs"] *= 2
    with pytest.raises(ValueError, match="log count"):
        helpers.request(fields, RECIPE)
    fields = copy.deepcopy(example("v01").fields)
    fields["logs"][0]["message"] = "x" * helpers.MAX_CONTEXT_CHARACTERS
    with pytest.raises(ValueError, match="text context"):
        helpers.request(fields, RECIPE)


@pytest.mark.parametrize(
    "ident,reason",
    [
        ("v05", "missing fresh"),
        ("v06", "conflicting"),
        ("v07", "missing or irregular"),
        ("v12", "already visible"),
        ("t11", "missing fresh"),
    ],
)
def test_structural_reviews_survive_confident_answers(ident, reason):
    row = example(ident)
    answers = dict(results_for([row])[ident].answers)
    answers = {name: answer(1 if value.noul > 0.5 else 0) for name, value in answers.items()}
    outcome = helpers.route(row.fields, answers, 0.6)
    assert not outcome.accepted and outcome.event == helpers.REVIEW
    assert reason in outcome.reason


def test_all_previous_candidates_must_be_resolved_and_earliest_wins():
    row = example("v09")
    answers = dict(results_for([row])[row.id].answers)
    assert helpers.route(row.fields, answers, 0.6).event == 3600
    answers["c1_visible"] = answer(0.5)
    assert helpers.route(row.fields, answers, 0.6).event == helpers.REVIEW
    answers["c1_visible"] = answer(0.02)
    answers["c2_associated"] = answer(0.02)
    assert helpers.route(row.fields, answers, 0.6).event == helpers.REVIEW


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), -0.2, 1.2, "yes", True])
def test_arbitrary_bad_probability_cannot_accept(invalid):
    row = example("v01")
    answers = dict(results_for([row])[row.id].answers)
    answers["c1_visible"] = SimpleNamespace(noul=invalid)
    assert not helpers.route(row.fields, answers, 0.6).accepted


def test_missing_or_foreign_answers_and_ties_go_to_review():
    row = example("v03")
    answers = dict(results_for([row])[row.id].answers)
    assert helpers.route(row.fields, answers, 0.6).event == helpers.NONE
    answers["c1_visible"] = answer(0.5)
    assert helpers.route(row.fields, answers, 0).event == helpers.REVIEW
    del answers["c1_visible"]
    assert helpers.route(row.fields, answers, 0).event == helpers.REVIEW
    answers["alien"] = answer(1)
    assert helpers.route(row.fields, answers, 0).event == helpers.REVIEW


@pytest.mark.parametrize("threshold", [-1, 1.1, float("nan"), float("inf"), True, None])
def test_invalid_threshold_fails_closed(threshold):
    with pytest.raises(ValueError):
        helpers.route(example("v01").fields, {}, threshold)


@pytest.mark.parametrize("mutation", ["session", "operation", "stale", "future", "old_event"])
def test_log_scope_and_freshness_are_exact(mutation):
    fields = copy.deepcopy(example("v01").fields)
    candidate = helpers.candidates(fields)[3]
    selected = next(log for log in fields["logs"] if log["operation_id"] == "refresh-4")
    if mutation == "session":
        selected["session_id"] = "SESSION-OTHER"
    elif mutation == "operation":
        selected["operation_id"] = "refresh-99"
    elif mutation == "stale":
        selected["timestamp_seconds"] -= 100
    elif mutation == "future":
        selected["emitted_at_seconds"] = candidate["end_seconds"] + 1
    else:
        selected["timestamp_seconds"] = candidate["start_seconds"]
    assert helpers.log_guard(fields, candidate) is not None


def test_baseline_reads_actual_pixels_and_logs_without_gold():
    fields = copy.deepcopy(example("v01").fields)
    frames = helpers.ordered_frames(fields)
    fields["frames"] = [
        dict(frames[3], timestamp_seconds=0),
        dict(frames[4], timestamp_seconds=1800),
    ]
    fields["logs"] = [{"timestamp_seconds": 1799, "message": "ERROR chart height"}]
    assert helpers.baseline(fields, RECIPE).event == 1800
    fields["label"] = {"event": "none"}
    assert helpers.baseline(fields, RECIPE).event == 1800
    fields["frames"][1]["path"] = fields["frames"][0]["path"]
    assert helpers.baseline(fields, RECIPE).event == helpers.NONE
    fields["frames"][1]["path"] = frames[4]["path"]
    fields["logs"][0]["message"] = "refresh complete"
    assert helpers.baseline(fields, RECIPE).event == helpers.NONE


def test_request_budget_cache_and_failed_attempt_accounting():
    backend = get_backend(fixtures=responses_path(RECIPE))
    runner = helpers.SessionRunner(backend, max_requests=1, root=RECIPE)
    fields = example("v01").fields
    first = runner.decide(fields)
    assert runner.decide(fields) is first and runner.calls == 1
    with pytest.raises(RuntimeError, match="budget"):
        runner.decide(example("v02").fields)
    assert runner.calls == 1

    class FailingBackend:
        def decide(self, *args, **kwargs):
            raise OSError("simulated failed request")

    failed = helpers.SessionRunner(FailingBackend(), max_requests=1, root=RECIPE)
    with pytest.raises(OSError):
        failed.decide(fields)
    with pytest.raises(RuntimeError, match="budget"):
        failed.decide(fields)
    assert failed.calls == 1


def test_review_is_not_coverage():
    outcomes = [
        helpers.Outcome("review", False, "missing evidence"),
        helpers.Outcome("none", True, "complete answer"),
    ]
    summary = helpers.summarize(outcomes, [{"event": "review"}, {"event": "none"}])
    assert summary["coverage"] == 0.5 and summary["event_accuracy_accepted"] == 1
