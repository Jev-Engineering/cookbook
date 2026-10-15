"""Prove temporal integrity and effect gates independently of authored replay answers."""

import ast
import copy
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import (
    DecisionResult,
    NoulAnswer,
    Provenance,
    get_backend,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def result(post=0.98, initial=0.98):
    return DecisionResult(
        {
            "postcondition": NoulAnswer(post, Provenance.synthetic()),
            "initially_absent": NoulAnswer(initial, Provenance.synthetic()),
        },
        "synthetic",
    )


def example(ident="d01"):
    return next(e for e in load_inputs(RECIPE) if e.id == ident)


def route(ident="d01", answer=None, gate=0.8):
    actions, queue = ActionLog(), ReviewQueue()
    outcome = helpers.classify(
        example(ident),
        answer if answer is not None else result(),
        gate,
        RECIPE,
        actions=actions,
        queue=queue,
    )
    return outcome, actions, queue


def test_valid_positive_records_only_a_simulated_handoff():
    outcome, actions, queue = route()
    assert outcome.outcome == "success"
    assert len(queue) == 0
    assert actions.to_dicts()[0]["executed"] is False
    assert actions.to_dicts()[0]["kind"] == "simulated handoff accepted"


def test_confident_negative_is_answered_without_action_or_review():
    outcome, actions, queue = route(answer=result(0.02))
    assert outcome.outcome == "not_observed"
    assert len(actions) == len(queue) == 0


def test_confident_loading_verdict_is_not_observed_at_the_capture_time():
    outcome, actions, queue = route("v06", answer=result(0.01, 0.99))
    assert outcome.outcome == load_labels(RECIPE)["v06"] == "not_observed"
    assert len(actions) == len(queue) == 0


@pytest.mark.parametrize("answer", [result(0.52), result(0.98, 0.51), result(0.98, 0.02)])
def test_uncertain_or_already_present_state_goes_to_review(answer):
    outcome, actions, queue = route(answer=answer)
    assert outcome.outcome == "review"
    assert len(actions) == 0
    assert len(queue) == 1


@pytest.mark.parametrize("post, initial", [(0.5, 0.99), (0.99, 0.5), (0.01, 0.5), (0.5, 0.5)])
def test_exact_ties_propose_review_and_abstain_with_a_selected_zero_gate(post, initial):
    tied = SimpleNamespace(id="tied", split="validation", fields=example("v01").fields)
    clear = SimpleNamespace(id="clear", split="validation", fields=example("v02").fields)
    answers = {tied.id: result(post, initial), clear.id: result(0.99, 0.99)}
    labels = {tied.id: "review", clear.id: "success"}
    assert helpers.proposed_outcome(answers[tied.id]) == "review"
    gate = helpers.freeze_gate([tied, clear], answers, labels)
    assert gate == 0.0
    actions, queue = ActionLog(), ReviewQueue()
    outcome = helpers.classify(tied, answers[tied.id], gate, RECIPE, actions=actions, queue=queue)
    assert outcome.outcome == "review"
    assert outcome.reason == "visual proposition is exactly undecided"
    assert len(actions) == 0
    assert len(queue) == 1
    assert queue.to_dicts()[0]["reason"] == outcome.reason


@pytest.mark.parametrize("post, expected", [(0.01, "not_observed"), (0.99, "success")])
def test_zero_gate_can_answer_untied_propositions(post, expected):
    outcome, actions, queue = route(answer=result(post, 0.99), gate=0.0)
    assert outcome.outcome == expected
    assert len(queue) == 0
    assert len(actions) == int(expected == "success")


@pytest.mark.parametrize("ident", ["v08", "v09", "t08", "t09"])
def test_missing_or_reversed_frames_override_a_certain_positive(ident):
    outcome, actions, queue = route(ident)
    assert outcome.outcome == "review"
    assert len(actions) == 0
    assert len(queue) == 1


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf")])
def test_gate_must_be_finite_unit_interval(bad):
    with pytest.raises(ValueError, match="finite"):
        route(gate=bad)


def test_gate_is_inclusive():
    answer = result(0.9, 0.9)
    gate = helpers.certainty(answer)
    assert route(answer=answer, gate=gate)[0].outcome == "success"
    assert route(answer=answer, gate=gate + 1e-8)[0].outcome == "review"


@pytest.mark.parametrize("mutation", ["equal_time", "action_after", "bad_phase", "negative_time"])
def test_bad_timestamps_and_roles_are_rejected(mutation):
    fields = copy.deepcopy(example().fields)
    if mutation == "equal_time":
        fields["frames"][1]["timestamp_ms"] = fields["frames"][0]["timestamp_ms"]
    elif mutation == "action_after":
        fields["action_timestamp_ms"] = 9000
    elif mutation == "bad_phase":
        fields["frames"][1]["phase"] = "before"
    else:
        fields["frames"][0]["timestamp_ms"] = -1
    assert helpers.frame_problem(fields, RECIPE)
    with pytest.raises(ValueError):
        helpers.build_request(fields, RECIPE)


@pytest.mark.parametrize("kind", ["missing", "corrupt", "truncated", "dimensions"])
def test_invalid_images_are_reviewed_without_a_call(tmp_path, kind):
    fields = copy.deepcopy(example().fields)
    for frame in fields["frames"]:
        destination = tmp_path / frame["asset"]
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes((RECIPE / frame["asset"]).read_bytes())
    path = tmp_path / fields["frames"][-1]["asset"]
    if kind == "missing":
        path.unlink()
    elif kind == "corrupt":
        path.write_bytes(b"not an image")
    elif kind == "truncated":
        path.write_bytes(path.read_bytes()[:100])
    else:
        Image.new("RGB", (100, 100)).save(path)
    item = SimpleNamespace(id="damage", fields=fields)

    class NoCalls:
        def decide(self, *_args, **_kwargs):
            raise AssertionError("invalid images must not be sent")

    assert helpers.collect([item], NoCalls(), tmp_path) == {"damage": None}
    actions, queue = ActionLog(), ReviewQueue()
    outcome = helpers.classify(item, result(), 0.0, tmp_path, actions=actions, queue=queue)
    assert outcome.outcome == "review" and len(queue) == 1 and len(actions) == 0


def test_state_excludes_labels_ids_paths_and_render_scenes():
    state, questions, assets = helpers.build_request(example().fields, RECIPE)
    assert set(state) == {
        "simulated_action",
        "action_timestamp_ms",
        "desired_postcondition",
        "frames_in_capture_order",
    }
    assert set(questions) == {"postcondition", "initially_absent"}
    text = json.dumps(state)
    assert "d01" not in text and "assets/" not in text and "gold" not in text
    assert assets and all(frame["image"] in assets for frame in state["frames_in_capture_order"])


def test_replay_identity_tracks_pixels_order_time_and_intent(tmp_path):
    state, questions, assets = helpers.build_request(example().fields, RECIPE)
    original = replay_key(state, questions, assets=assets)
    changed = copy.deepcopy(state)
    changed["frames_in_capture_order"].reverse()
    assert replay_key(changed, questions, assets=assets) != original
    changed = copy.deepcopy(state)
    changed["frames_in_capture_order"][-1]["timestamp_ms"] += 1
    assert replay_key(changed, questions, assets=assets) != original
    assert (
        replay_key(state, helpers.build_questions("save_notifications"), assets=assets) != original
    )
    fields = copy.deepcopy(example().fields)
    for frame in fields["frames"]:
        path = tmp_path / frame["asset"]
        path.parent.mkdir(exist_ok=True)
        path.write_bytes((RECIPE / frame["asset"]).read_bytes())
    path = tmp_path / fields["frames"][-1]["asset"]
    with Image.open(path) as source:
        image = source.convert("RGB")
    image.putpixel((0, 0), (200, 10, 100))
    image.save(path)
    new_state, new_questions, new_assets = helpers.build_request(fields, tmp_path)
    assert replay_key(new_state, new_questions, assets=new_assets) != original


def test_pixel_baseline_falsely_accepts_an_unrelated_banner():
    assert helpers.pixel_baseline(example("d02").fields, RECIPE) == "success"
    assert helpers.pixel_baseline(example("v03").fields, RECIPE) == "not_observed"
    assert helpers.changed_fraction(example("v03").fields, RECIPE) == 0.0


def test_every_replay_key_matches_current_pixels_and_questions():
    for item in load_inputs(RECIPE):
        if helpers.frame_problem(item.fields, RECIPE):
            assert item.replay_keys == ()
        else:
            state, questions, assets = helpers.build_request(item.fields, RECIPE)
            assert item.replay_keys == (replay_key(state, questions, assets=assets),)


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE), images=True, model="jev-1.14.0")
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = select_split(examples, "validation")
    validation_results = helpers.collect(validation, backend, RECIPE)
    eligible = [
        e
        for e in validation
        if validation_results[e.id] is not None
        and validation_results[e.id]["initially_absent"].noul >= 0.5
    ]
    gate = select_confidence_threshold(
        [helpers.proposed_outcome(validation_results[e.id]) == labels[e.id] for e in eligible],
        [helpers.certainty(validation_results[e.id]) for e in eligible],
        target_accuracy=1.0,
    )
    assert gate == helpers.freeze_gate(validation, validation_results, labels)
    test = select_split(examples, "test")
    results = helpers.collect(test, backend, RECIPE)
    actions, queue = ActionLog(), ReviewQueue()
    outcomes = [
        helpers.classify(e, results[e.id], gate, RECIPE, actions=actions, queue=queue) for e in test
    ]
    assert any(o.outcome == "success" and labels[o.example_id] != "success" for o in outcomes)
    wrong_above_gate = [
        e.id
        for e in test
        if results[e.id] is not None
        and helpers.certainty(results[e.id]) >= gate
        and helpers.proposed_outcome(results[e.id]) != labels[e.id]
    ]
    assert wrong_above_gate


def test_the_gate_selector_objective_is_pinned_to_target_accuracy():
    source = ast.parse(inspect.getsource(helpers.freeze_gate))
    calls = [
        node
        for node in ast.walk(source)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    assert [(kw.arg, ast.literal_eval(kw.value)) for kw in calls[0].keywords] == [
        ("target_accuracy", 1.0)
    ]


def test_gate_selection_refuses_test_data():
    with pytest.raises(ValueError, match="validation"):
        helpers.freeze_gate([example("t01")], {}, {})
