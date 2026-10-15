"""Check the real image requests, policy boundary, baseline and held-out failure."""

import inspect
import json
import math
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_outcomes, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import image_asset, image_reference

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(group="broadleaf", probability=0.9):
    probabilities = {option: (1 - probability) / 4 for option in helpers.OPTIONS}
    probabilities[group] = probability
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def session():
    return helpers.Session(get_backend(fixtures=RECIPE / "fixtures/responses.json"))


def test_python_options_and_images_are_the_only_request_inputs():
    example = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(example.fields)
    assert list(questions["group"].criteria) == [
        "broadleaf",
        "needlelike",
        "rosette",
        "fernlike",
        "unknown",
    ]
    assert list(state) == ["query_image"]
    assert len(assets) == 5
    refs = [questions["group"].criteria[g]["example"] for g in helpers.REFERENCES]
    assert set(refs + [state["query_image"]]) == set(assets)
    polluted = dict(example.fields, label="fernlike", split="test", seed=555, category="wrong")
    assert helpers.build_request(polluted) == (state, questions, assets)
    text = json.dumps([state, questions["group"].to_dict()])
    assert "assets/" not in text and "validation" not in text and "seed" not in text


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    s = session()
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
        assert s.decide(example)["group"].choice in helpers.OPTIONS
    assert s.attempts == 26


def test_state_query_and_reference_bytes_change_replay_identity(tmp_path):
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    example = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(example.fields, tmp_path)
    before = replay_key(state, questions, assets=assets)
    assert before != replay_key(dict(state, note="different task"), questions, assets=assets)
    for relative in (example.fields["image"], "assets/ref-03.png"):
        path = tmp_path / relative
        with Image.open(path) as original:
            image = original.copy()
        image.putpixel((0, 0), (10, 20, 30))
        image.save(path)
        new_state, new_questions, new_assets = helpers.build_request(example.fields, tmp_path)
        assert replay_key(new_state, new_questions, assets=new_assets) != before
        changed = dict(assets)
        old_ref = image_reference(image_asset(RECIPE / relative))
        changed[old_ref] = image_asset(path)
        assert replay_key(state, questions, assets=changed) != before


@pytest.mark.parametrize("group", ["broadleaf", "needlelike", "rosette", "fernlike"])
def test_threshold_is_inclusive_and_side_effects_are_simulated(group):
    typed = answer(group)
    actions, reviews = ActionLog(), ReviewQueue()
    match = helpers.route("case", typed, typed.confidence, actions, reviews)
    assert match.outcome == "accepted" and len(actions) == 1 and len(reviews) == 0
    assert actions.to_dicts()[0]["executed"] is False
    match = helpers.route("case2", typed, typed.confidence + 1e-8, actions, reviews)
    assert match.outcome == "review" and len(actions) == 1 and len(reviews) == 1
    assert match.reason == "confidence below the threshold"


def test_unknown_is_review_at_full_confidence_and_zero_threshold():
    actions, reviews = ActionLog(), ReviewQueue()
    result = helpers.route("ambiguous", answer("unknown", 1.0), 0.0, actions, reviews)
    assert result.outcome == "review" and len(actions) == 0 and len(reviews) == 1
    metrics = evaluate_outcomes([result.outcome == "accepted"], [True])
    assert metrics.coverage == 0 and math.isnan(metrics.accuracy)


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), -0.1, 1.1, True])
def test_arbitrary_invalid_answer_never_produces_a_suggestion(confidence):
    odd = SimpleNamespace(choice="broadleaf", confidence=confidence)
    assert helpers.classify("x", odd, 0.0).outcome == "review"


@pytest.mark.parametrize("group", [[], {}, None, 12])
def test_malformed_group_defers(group):
    assert (
        helpers.classify("x", SimpleNamespace(choice=group, confidence=1.0), 0.0).outcome
        == "review"
    )


def test_foreign_option_does_not_escape_the_python_catalog():
    odd = ChoiceAnswer.from_probabilities(
        {"species-name": 1.0, "unknown": 0.0}, Provenance.synthetic()
    )
    actions, reviews = ActionLog(), ReviewQueue()
    assert helpers.route("x", odd, 0.0, actions, reviews).outcome == "review"
    assert len(actions) == 0 and len(reviews) == 1


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf"), True, None])
def test_invalid_threshold_stops_before_routing(threshold):
    with pytest.raises(ValueError, match="finite"):
        helpers.classify("x", answer(), threshold)


def test_budget_counts_failed_attempts_and_cached_answers_do_not_spend_again():
    examples = load_inputs(RECIPE)
    s = helpers.Session(get_backend(fixtures=RECIPE / "fixtures/responses.json"), max_requests=1)
    first = s.decide(examples[0])
    assert s.decide(examples[0]) == first and s.attempts == 1
    with pytest.raises(RuntimeError, match="budget"):
        s.decide(examples[1])

    class Failed:
        calls = 0

        def decide(self, *args, **kwargs):
            self.calls += 1
            raise OSError("simulated transport failure")

    failed = Failed()
    bounded = helpers.Session(failed, max_requests=1)
    with pytest.raises(OSError):
        bounded.decide(examples[0])
    with pytest.raises(RuntimeError, match="budget"):
        bounded.decide(examples[0])
    assert failed.calls == 1


def test_stored_answers_are_not_all_right():
    s, labels = session(), load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    validation = [e for e in examples if e.split == "validation"]
    named = [
        (s.decide(e)["group"].confidence, s.decide(e)["group"].choice == labels[e.id])
        for e in validation
        if s.decide(e)["group"].choice in helpers.REFERENCES
    ]
    threshold = select_confidence_threshold(
        [ok for _, ok in named], [c for c, _ in named], target_accuracy=1.0
    )
    assert threshold == helpers.select_policy(
        validation, labels, {e.id: s.decide(e)["group"] for e in validation}
    )
    test = [e for e in examples if e.split == "test"]
    wrong_and_confident = [
        e.id
        for e in test
        if s.decide(e)["group"].choice != labels[e.id]
        and s.decide(e)["group"].confidence >= threshold
        and helpers.classify(e.id, s.decide(e)["group"], threshold).outcome == "accepted"
    ]
    assert wrong_and_confident, "expected an accepted confidently wrong held-out answer"
    assert "t10" in wrong_and_confident


def test_selection_objective_is_pinned_to_the_real_helper_source():
    source = inspect.getsource(helpers.select_policy)
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
    baseline_source = inspect.getsource(helpers.select_baseline_policy)
    assert "m.coverage >= 0.5" in baseline_source
    assert "(rm[1].accuracy, rm[1].coverage, -rm[0])" in baseline_source
    assert helpers.RADIUS_CANDIDATES == (0.1, 0.2, 0.35, 0.5, 0.8, 1.5)


def test_selection_refuses_test_and_stops_when_no_gate_can_be_fit():
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    test = [e for e in examples if e.split == "test"]
    with pytest.raises(ValueError, match="validation"):
        helpers.select_policy(test, labels, {})
    with pytest.raises(ValueError, match="validation"):
        helpers.select_baseline_policy(test, labels, {})
    validation = [e for e in examples if e.split == "validation"]
    with pytest.raises(ValueError):
        helpers.select_policy(validation, labels, {e.id: answer("unknown") for e in validation})
    with pytest.raises(ValueError):
        helpers.select_policy(
            validation, labels, {e.id: answer("broadleaf", 1) for e in validation}
        )


def test_baseline_reads_pixels_not_names_labels_or_parameters(tmp_path):
    fields = load_inputs(RECIPE)[0].fields
    expected = helpers.nearest_reference(fields)
    assert (
        helpers.nearest_reference(dict(fields, label="wrong", group="unknown", seed=1)) == expected
    )
    original = RECIPE / fields["image"]
    renamed = tmp_path / "unfamiliar-filename.png"
    shutil.copyfile(original, renamed)
    np.testing.assert_array_equal(helpers.pixel_features(original), helpers.pixel_features(renamed))
    Image.new("RGB", (384, 320), (235, 235, 235)).save(renamed)
    assert helpers.pixel_features(renamed) is None
    assert helpers.baseline_match("x", ("unknown", math.inf), 0.35).outcome == "review"
    assert helpers.baseline_match("x", ("broadleaf", 0.350001), 0.35).outcome == "review"
    assert helpers.baseline_match("x", ("broadleaf", 0.35), 0.35).outcome == "accepted"
