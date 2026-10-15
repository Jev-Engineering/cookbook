"""Visual composition, abstention, replay identity, and frozen-policy regression tests."""

import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from jev_cookbook import NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answers(values):
    return {
        name: NoulAnswer(value, Provenance.synthetic())
        for name, value in zip(helpers.QUESTION_NAMES, values, strict=True)
    }


def pool(split):
    backend = get_backend(fixtures=RECIPE / "fixtures/responses.json")
    labels = load_labels(RECIPE)
    rows = []
    for example in load_inputs(RECIPE):
        if example.split == split:
            state, questions, assets = helpers.build_request(example.fields)
            result = backend.decide(state, questions, assets=assets)
            rows.append((example, helpers.compose(result.answers), labels[example.id]["outcome"]))
    return rows


def test_arbitrary_combinations_cannot_bypass_abstention_or_create_an_action():
    for probabilities in itertools.product((0.01, 0.5, 0.99), repeat=4):
        evidence = helpers.compose(answers(probabilities))
        outcome = helpers.route("asset", evidence, 0.7)
        actions, reviews = ActionLog(), ReviewQueue()
        helpers.log_outcome(outcome, actions, reviews)
        if outcome.accepted:
            assert probabilities[0] > 0.5
            assert probabilities.count(0.5) == 0
            assert sum(p > 0.5 for p in probabilities[1:]) <= 1
            assert evidence.confidence >= 0.7
            assert outcome.label in ("conforming", "nonconforming")
            assert len(actions) == 1 and len(reviews) == 0
            assert actions.to_dicts()[0]["executed"] is False
        else:
            assert outcome.label == "review"
            assert len(actions) == 0 and len(reviews) == 1


def test_inspectability_is_required_even_when_match_is_certain():
    evidence = helpers.compose(answers((0.01, 0.99, 0.01, 0.01)))
    assert helpers.route("tiny", evidence, 0).label == "review"


def test_multiple_approved_matches_are_conflicting_not_more_certain():
    evidence = helpers.compose(answers((0.99, 0.99, 0.01, 0.99)))
    assert helpers.route("conflict", evidence, 0).label == "review"
    assert evidence.reason == "conflicting approved variants"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -1, 2, True, "1"])
def test_invalid_or_missing_probabilities_abstain(bad):
    data = answers((0.99, 0.99, 0.01, 0.01))
    data["light"] = SimpleNamespace(noul=bad)
    assert helpers.route("invalid", helpers.compose(data), 0).label == "review"
    data.pop("light")
    assert helpers.compose(data).label == "review"
    data["publish"] = SimpleNamespace(noul=0.99)
    assert helpers.compose(data).label == "review"


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_invalid_gate_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.route("asset", helpers.compose(answers((0.99, 0.99, 0.01, 0.01))), bad)


def test_confidence_gate_is_inclusive():
    evidence = helpers.compose(answers((0.99, 0.85, 0.01, 0.01)))
    assert helpers.route("asset", evidence, evidence.confidence).accepted
    assert not helpers.route("asset", evidence, evidence.confidence + 1e-9).accepted


def test_reference_images_are_inside_question_instructions_and_metadata_is_hidden():
    example = load_inputs(RECIPE)[0]
    poisoned = dict(example.fields, label="conforming", split="test", alteration="none")
    state, questions, assets = helpers.build_request(poisoned)
    assert set(state) == {"displayed_asset"}
    assert len(questions) == 4 and len(assets) == 4
    assert set(questions) == {"inspectable", "light", "dark", "monochrome"}
    for variant in helpers.REFERENCES:
        assert "image:sha256:" in questions[variant].instructions
    text = json.dumps(state) + " ".join(q.instructions for q in questions.values())
    assert "asset-001" not in text
    assert "alteration" not in text and '"split"' not in text
    assert helpers.build_request(poisoned) == helpers.build_request(example.fields)


def test_replay_key_binds_query_reference_bytes_and_state(tmp_path):
    example = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(example.fields)
    key = replay_key(state, questions, assets=assets)
    assert key == example.replay_keys[0]
    assert replay_key(dict(state, context="different"), questions, assets=assets) != key
    for reference in assets:
        changed = dict(assets)
        with Image.open(RECIPE / example.fields["image"]) as image:
            image.putpixel((0, 0), (1, 2, 3))
            path = tmp_path / "changed.png"
            image.save(path)
        changed[reference] = image_asset(path)
        assert replay_key(state, questions, assets=changed) != key


def test_all_assets_valid_and_no_query_pixels_cross_splits_or_equal_references():
    seen = {}
    reference_pixels = {Image.open(RECIPE / path).tobytes() for path in helpers.REFERENCES.values()}
    for example in load_inputs(RECIPE):
        path = RECIPE / example.fields["image"]
        image_asset(path)
        with Image.open(path) as image:
            assert image.size == (480, 320)
            pixels = image.tobytes()
        assert pixels not in reference_pixels
        assert pixels not in seen
        seen[pixels] = example.split
        state, questions, assets = helpers.build_request(example.fields)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
    assert len(seen) == 30


def test_request_budget_prevents_a_second_backend_call_and_batches_four_questions():
    class CountingBackend:
        def __init__(self):
            self.calls = []

        def decide(self, state, questions, *, assets):
            self.calls.append((state, questions, assets))
            return "one result"

    backend = CountingBackend()
    run = helpers.InspectionRun(backend, max_requests=1)
    fields = load_inputs(RECIPE)[0].fields
    assert run.decide(fields) == "one result"
    with pytest.raises(RuntimeError, match="budget exhausted"):
        run.decide(fields)
    assert len(backend.calls) == 1
    assert len(backend.calls[0][1]) == 4


def test_pixel_baseline_uses_same_references_and_cannot_read_gold():
    example = load_inputs(RECIPE)[0]
    first = helpers.baseline_evidence(example.fields)
    poisoned = dict(example.fields, label="nonconforming", split="train", alteration="word")
    assert helpers.baseline_evidence(poisoned) == first
    assert set(helpers.REFERENCES) == {"light", "dark", "monochrome"}
    assert helpers.baseline_route("x", None, (0.03, 0.35)).label == "review"
    assert helpers.baseline_route("x", 0.10, (0.03, 0.35)).label == "review"


def test_pixel_alignment_preserves_aspect_difference(tmp_path):
    path = RECIPE / helpers.REFERENCES["light"]
    with Image.open(path) as original:
        rgb = np.asarray(original)
        mask = np.max(np.abs(rgb.astype(float) - rgb[0, 0]), axis=2) > 30
        ys, xs = np.nonzero(mask)
        crop = original.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
        shifted = Image.new("RGB", original.size, tuple(rgb[0, 0]))
        shifted.paste(crop, (130, 90))
        shifted_path = tmp_path / "shifted.png"
        shifted.save(shifted_path)
        stretched = Image.new("RGB", original.size, tuple(rgb[0, 0]))
        stretched.paste(crop.resize((int(crop.width * 1.2), crop.height)), (20, 120))
        stretched_path = tmp_path / "stretched.png"
        stretched.save(stretched_path)
    normal = helpers.pixel_features(path)
    translated = helpers.pixel_features(shifted_path)
    stretched = helpers.pixel_features(stretched_path)
    assert np.allclose(normal[0], translated[0])
    assert normal[1] == translated[1]
    assert stretched[1] > normal[1] * 1.19


def test_stored_answers_are_not_all_right():
    validation = pool("validation")
    eligible = [(evidence, gold) for _, evidence, gold in validation if evidence.label != "review"]
    threshold = select_confidence_threshold(
        [e.label == g for e, g in eligible],
        [e.confidence for e, _ in eligible],
        target_accuracy=1.0,
    )
    assert threshold == pytest.approx(0.64)
    wrong_and_confident = [
        example.id
        for example, evidence, gold in pool("test")
        if evidence.label != gold
        and evidence.confidence >= threshold
        and helpers.route(example.id, evidence, threshold).accepted
    ]
    assert wrong_and_confident == ["t08"]


def test_notebook_pins_validation_objective_and_test_never_selects_policy():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    source = "".join(next(c for c in notebook["cells"] if c["id"] == "python-rule")["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
    test_source = "".join(
        next(c for c in notebook["cells"] if c["id"] == "evaluation-test")["source"]
    )
    assert "select_confidence_threshold" not in test_source
    assert "select_baseline_policy" not in test_source


def test_baseline_policy_selection_objective_and_tie_break_are_exercised():
    assert helpers.select_baseline_policy([0.02, 0.10], ["conforming", "nonconforming"]) == (
        0.03,
        0.08,
    )
    assert helpers.select_baseline_policy([0.02, 0.10], ["conforming", "review"]) == (0.03, 0.35)
    with pytest.raises(ValueError, match="no baseline policy"):
        helpers.select_baseline_policy([0.0], ["nonconforming"])
