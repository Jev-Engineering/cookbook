"""Temporal semantics, actual policy outcomes, pixel isolation, and replay identity."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_outcomes, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(choice, probability=0.94):
    return ChoiceAnswer.from_probabilities(
        {
            name: probability if name == choice else (1 - probability) / 3
            for name in helpers.OPTIONS
        },
        Provenance.synthetic(),
    )


def replay_all():
    backend = get_backend(fixtures=responses_path(RECIPE))
    results = {}
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        results[example.id] = backend.decide(state, questions, assets=assets)["end_phase"]
    return results


@pytest.mark.parametrize("choice", helpers.OPTIONS)
@pytest.mark.parametrize("probability", [0.40, 0.60, 0.80, 1.0])
def test_policy_and_containers_for_arbitrary_distributions(choice, probability):
    actions, reviews = ActionLog(), ReviewQueue()
    a = answer(choice, probability)
    outcome = helpers.annotate("clip", a, 0.75, actions, reviews)
    expected = choice != "unrecognized" and a.confidence >= 0.75
    assert outcome.accepted is expected
    assert (len(actions), len(reviews)) == (int(expected), int(not expected))
    assert all(row["executed"] is False for row in actions.to_dicts())


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), -1, 2, True, "high"])
def test_malformed_confidence_defers(confidence):
    a = SimpleNamespace(choice="execution", confidence=confidence)
    assert not helpers.classify("clip", a, 0.75).accepted


def test_unknown_foreign_and_inclusive_boundaries():
    assert not helpers.classify("clip", answer("unrecognized", 1.0), 0).accepted
    assert not helpers.classify(
        "clip", SimpleNamespace(choice="shoot_now", confidence=1.0), 0
    ).accepted
    a = answer("execution")
    assert helpers.classify("clip", a, a.confidence).accepted
    assert not helpers.classify("clip", a, a.confidence + 1e-9).accepted


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError, match="threshold"):
        helpers.classify("clip", answer("execution"), threshold)


def test_sampling_keeps_chronology_and_endpoints_without_metadata():
    fields = load_inputs(RECIPE)[0].fields
    selected = helpers.sample_frames(fields)
    assert [f["timestamp_seconds"] for f in selected] == [0, 0.4, 0.8, 1.2]
    altered = copy.deepcopy(fields)
    altered.update(gold="execution", split="test", poses="EEEE")
    assert helpers.build_request(fields, RECIPE) == helpers.build_request(altered, RECIPE)
    state, questions, _ = helpers.build_request(fields, RECIPE)
    assert set(state) == {
        "movement",
        "target",
        "window_start_seconds",
        "window_end_seconds",
        "frames",
    }
    assert set(questions) == {"end_phase"}
    assert list(questions["end_phase"].criteria) == [
        "preparation",
        "execution",
        "recovery",
        "unrecognized",
    ]
    assert "END" in questions["end_phase"].instructions
    assert all(f["image"].startswith("image:sha256:") for f in state["frames"])


@pytest.mark.parametrize(
    "times",
    [
        [0, 0, 1, 2],
        [0, 2, 1, 3],
        [-1, 0, 1, 2],
        [0, 1, 2, float("nan")],
        [0, 1, 2, 5],
        [0, 0.1, 0.2, 3],
    ],
)
def test_invalid_chronology_or_sampling_gap_refuses(times):
    with pytest.raises(ValueError):
        helpers.sample_frames(
            {"frames": [{"timestamp_seconds": t, "path": "unused"} for t in times]}
        )


@pytest.mark.parametrize("count", [0, 3, 61])
def test_frame_limit(count):
    with pytest.raises(ValueError, match="4 to 60"):
        helpers.sample_frames({"frames": [{} for _ in range(count)]})


def test_bad_image_paths_rejected():
    with pytest.raises(ValueError, match="inside assets"):
        helpers.frame_path(RECIPE, "../../README.md")


def test_budget_stops_before_call_and_failures_are_spent():
    calls = []

    class FailingBackend:
        def decide(self, *args, **kwargs):
            calls.append(1)
            raise RuntimeError("simulated backend failure")

    runner = helpers.WindowRunner(FailingBackend(), RECIPE, max_windows=1)
    fields = load_inputs(RECIPE)[0].fields
    with pytest.raises(RuntimeError, match="backend failure"):
        runner.decide(fields)
    with pytest.raises(RuntimeError, match="budget"):
        runner.decide(fields)
    assert len(calls) == runner.attempts == 1


def test_every_replay_key_matches_and_state_and_pixels_change_identity(tmp_path):
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        original = replay_key(state, questions, assets=assets)
        assert example.replay_keys == (original,)
        changed = copy.deepcopy(state)
        changed["frames"][0]["timestamp_seconds"] += 0.01
        assert replay_key(changed, questions, assets=assets) != original
    reference = next(iter(assets))
    sample = helpers.sample_frames(example.fields)[0]
    with Image.open(RECIPE / sample["path"]) as image:
        image.putpixel((0, 0), (1, 2, 3))
        image.save(tmp_path / "changed.png")
    altered_assets = dict(assets)
    altered_assets[reference] = image_asset(tmp_path / "changed.png")
    assert replay_key(state, questions, assets=altered_assets) != original


def test_baseline_uses_pixels_and_temporal_history_without_gold(tmp_path):
    examples = load_inputs(RECIPE)
    demo = next(e for e in examples if e.id == "d01")
    fields = copy.deepcopy(demo.fields)
    assert helpers.pixel_pose_baseline(fields, RECIPE) == "recovery"
    fields.update(gold="preparation", end_phase="preparation", prediction="preparation")
    assert helpers.pixel_pose_baseline(fields, RECIPE) == "recovery"
    folder = tmp_path / "assets"
    folder.mkdir()
    for frame in fields["frames"]:
        target = folder / Path(frame["path"]).name
        Image.new("RGB", (400, 320), "white").save(target)
        frame["path"] = f"assets/{target.name}"
    assert helpers.pixel_pose_baseline(fields, tmp_path) == "unrecognized"


def test_pixels_are_disjoint_across_scored_splits():
    hashes = {"validation": set(), "test": set()}
    for example in load_inputs(RECIPE):
        if example.split in hashes:
            for frame in example.fields["frames"]:
                with Image.open(RECIPE / frame["path"]) as image:
                    hashes[example.split].add(
                        hashlib.sha256(image.convert("RGB").tobytes()).digest()
                    )
    assert not (hashes["validation"] & hashes["test"])


def test_stored_answers_are_not_all_right():
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    answers = replay_all()
    named = [
        e for e in examples if e.split == "validation" and answers[e.id].choice in helpers.PHASES
    ]
    threshold = select_confidence_threshold(
        [answers[e.id].choice == labels[e.id]["end_phase"] for e in named],
        [answers[e.id].confidence for e in named],
        target_accuracy=1.0,
    )
    wrong_and_confident = [
        e.id
        for e in examples
        if e.split == "test"
        and answers[e.id].choice != labels[e.id]["end_phase"]
        and answers[e.id].confidence >= threshold
        and helpers.classify(e.id, answers[e.id], threshold).accepted
    ]
    assert wrong_and_confident == ["t07"]
    test = [e for e in examples if e.split == "test"]
    outcomes = [helpers.classify(e.id, answers[e.id], threshold) for e in test]
    correct = [answers[e.id].choice == labels[e.id]["end_phase"] for e in test]
    metrics = evaluate_outcomes([o.accepted for o in outcomes], correct)
    assert metrics.n_total == 12 and metrics.n_answered == 8
    assert metrics.accuracy == 7 / 8


def test_the_notebook_pins_the_actual_selection_objective():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source


@pytest.mark.parametrize("choice", helpers.OPTIONS)
def test_no_feasible_validation_policy_defers_even_certain_answers(choice):
    actions, reviews = ActionLog(), ReviewQueue()
    result = helpers.annotate("clip", answer(choice, 1.0), None, actions, reviews)
    assert result.outcome == "review"
    assert not result.accepted
    assert len(actions) == 0 and len(reviews) == 1
