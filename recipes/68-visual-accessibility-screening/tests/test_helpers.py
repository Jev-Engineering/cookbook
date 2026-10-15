"""Rules, evidence identity, frozen policy and independent pixel-baseline checks."""

import ast
import inspect
import itertools
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
from jev_cookbook.evaluation import noul_confidence, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.vision import image_asset, image_reference

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def result(values=(0.02, 0.02, 0.02, 0.02), readable=0.98):
    return DecisionResult(
        {
            name: NoulAnswer(p, Provenance.synthetic())
            for name, p in zip((*helpers.FLAGS, "readable"), (*values, readable), strict=True)
        },
        "synthetic",
    )


def replay():
    examples = load_inputs(RECIPE)
    run = helpers.ScreeningRun(get_backend(fixtures=responses_path(RECIPE)), RECIPE)
    return examples, {e.id: run.decide(e) for e in examples}, load_labels(RECIPE)


def test_independent_questions_and_arbitrary_answer_routing():
    assert list(helpers.build_questions()) == [
        "clipping",
        "low_contrast",
        "crowding",
        "overlap",
        "readable",
    ]
    thresholds = dict.fromkeys(helpers.FLAGS, 0.8)
    for values in itertools.product((0.0, 0.49, 1.0), repeat=4):
        decision = helpers.screen(result(values), thresholds)
        expected_review = 0.49 in values
        assert (decision.outcome == "review") == expected_review
        if expected_review:
            assert not decision.flags
        else:
            assert decision.flags == frozenset(
                f for f, p in zip(helpers.FLAGS, values, strict=True) if p == 1.0
            )
        assert helpers.screen(result(values, readable=0.84), thresholds).outcome == "review"


def test_boundary_and_missing_invalid_answers():
    thresholds = dict.fromkeys(helpers.FLAGS, 0.8)
    boundary = result((0.9, 0.9, 0.9, 0.9), readable=0.85)
    assert helpers.screen(boundary, thresholds).outcome == "screened"
    for value in (None, float("nan"), float("inf"), -1, 2, True):
        fake = dict(boundary.answers)
        fake["clipping"] = SimpleNamespace(noul=value)
        assert helpers.screen(SimpleNamespace(answers=fake), thresholds).outcome == "review"
    assert helpers.screen(SimpleNamespace(answers={}), thresholds).outcome == "review"
    for value in (-1, 2, float("nan")):
        with pytest.raises(ValueError):
            helpers.screen(boundary, dict.fromkeys(helpers.FLAGS, value))


def test_exact_contrast_computation_known_colors():
    assert helpers.contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21)
    assert helpers.contrast_ratio((77, 77, 77), (77, 77, 77)) == 1
    assert helpers.contrast_ratio((119, 119, 119), (255, 255, 255)) == pytest.approx(4.47808945)
    assert helpers.relative_luminance((255, 0, 0)) == pytest.approx(0.2126)
    with pytest.raises(ValueError):
        helpers.relative_luminance((256, 0, 0))


def test_baseline_measures_pixels_without_gold_or_layout_metadata():
    image = Image.new("RGB", (480, 360), (255, 255, 255))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 85, 80, 105), fill=(0, 0, 0))
    draw.rectangle((35, 160, 210, 215), fill=helpers.CONTROL_COLORS[0])
    draw.rectangle((240, 160, 415, 215), fill=helpers.CONTROL_COLORS[1])
    decision, ratio = helpers.pixel_baseline(image)
    assert ratio == pytest.approx(21)
    assert not decision.flags
    draw.rectangle((35, 85, 80, 105), fill=(188, 188, 188))
    assert "low_contrast" in helpers.pixel_baseline(image)[0].flags
    draw.rectangle((455, 86, 455, 105), fill=(188, 188, 188))
    assert "clipping" in helpers.pixel_baseline(image)[0].flags
    draw.rectangle((175, 175, 350, 230), fill=helpers.CONTROL_COLORS[1])
    assert {"overlap", "crowding"} <= helpers.pixel_baseline(image)[0].flags
    assert list(inspect.signature(helpers.pixel_baseline).parameters) == ["image"]


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    seen_pixels = {}
    for e in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(e.fields, RECIPE)
        assert e.replay_keys == (replay_key(state, questions, assets=assets),)
        assert not {"split", "label", "flags", "variant", "image"} & set(state)
        with Image.open(RECIPE / e.fields["image"]) as image:
            assert image.size == (480, 360)
            identity = image.tobytes()
        assert identity not in seen_pixels
        seen_pixels[identity] = e.split


def test_replay_identity_binds_state_and_image_bytes(tmp_path):
    e = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(e.fields, RECIPE)
    original = replay_key(state, questions, assets=assets)
    assert replay_key({**state, "task": "Different request"}, questions, assets=assets) != original
    image = Image.open(RECIPE / e.fields["image"]).convert("RGB")
    image.putpixel((0, 0), (1, 2, 3))
    image.save(tmp_path / "changed.png")
    asset = image_asset(tmp_path / "changed.png")
    ref = image_reference(asset)
    assert replay_key({**state, "screenshot": ref}, questions, assets={ref: asset}) != original
    polluted = {**e.fields, "label": "overlap", "split": "test", "variant": "hidden"}
    assert helpers.build_request(polluted, RECIPE) == (state, questions, assets)


def test_request_cap_cache_and_error_consumption():
    examples = load_inputs(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    run = helpers.ScreeningRun(backend, RECIPE, max_requests=1)
    assert run.decide(examples[0]) is run.decide(examples[0])
    assert run.calls == 1
    with pytest.raises(RuntimeError, match="budget"):
        run.decide(examples[1])

    class Failing:
        def decide(self, *args, **kwargs):
            raise ValueError("request failed")

    run = helpers.ScreeningRun(Failing(), RECIPE, max_requests=1)
    with pytest.raises(ValueError, match="failed"):
        run.decide(examples[0])
    with pytest.raises(RuntimeError, match="budget"):
        run.decide(examples[0])


def test_stored_answers_are_not_all_right():
    examples, results, labels = replay()
    validation = [e for e in examples if e.split == "validation"]
    thresholds = helpers.select_policy(validation, results, labels)
    wrong_and_confident = []
    for flag in helpers.FLAGS:
        eligible = [
            e
            for e in validation
            if labels[e.id]["assessable"] and results[e.id]["readable"].noul >= 0.85
        ]
        correct = [
            (results[e.id][flag].noul >= 0.5) == (flag in labels[e.id]["flags"]) for e in eligible
        ]
        threshold = select_confidence_threshold(
            correct, noul_confidence([results[e.id][flag] for e in eligible]), target_accuracy=1.0
        )
        assert threshold == thresholds[flag]
        for e in [e for e in examples if e.split == "test"]:
            confidence = noul_confidence([results[e.id][flag]])[0]
            wrong = (results[e.id][flag].noul >= 0.5) != (flag in labels[e.id]["flags"])
            if wrong and confidence >= threshold:
                if helpers.screen(results[e.id], thresholds).outcome == "screened":
                    wrong_and_confident.append(e.id)
    assert wrong_and_confident
    assert {"t08", "t09"} <= set(wrong_and_confident)


def test_threshold_objective_is_pinned_from_production_source():
    source = inspect.getsource(helpers.select_policy)
    calls = [
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in calls[0].keywords}
    assert keywords == {"target_accuracy": 1.0}


def test_selection_rejects_test_and_actual_decisions_drive_coverage():
    examples, results, labels = replay()
    validation = [e for e in examples if e.split == "validation"]
    test = [e for e in examples if e.split == "test"]
    with pytest.raises(ValueError, match="validation"):
        helpers.select_policy(test, results, labels)
    thresholds = helpers.select_policy(validation, results, labels)
    decisions, queue = helpers.review_outcomes(test, results, thresholds)
    report = helpers.metrics(test, labels, decisions)
    assert report["selective"].n_answered == len(test) - len(queue)
    assert decisions["t11"].outcome == "review"
    assert report["unsafe_unassessable_accepts"] == 0
    assert report["selective"].accuracy < 1
    for item in queue.pending():
        assert item.reason and item.answer


def test_notebook_freezes_validation_before_test_requests():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text())
    code = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    assert code.index("helpers.select_policy(") < code.index("test_results =")
