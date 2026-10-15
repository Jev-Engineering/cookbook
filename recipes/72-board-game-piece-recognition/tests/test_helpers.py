"""Policy, pixel lineage, and frozen-objective checks for the fictional piece catalog."""

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


@pytest.mark.parametrize("choice", [*helpers.CATALOG, "unknown", "invented", None])
@pytest.mark.parametrize("confidence", [None, -1, 0, 0.5, 0.9, 1, 2, float("nan"), True])
def test_python_owns_acceptance_under_arbitrary_answers(choice, confidence):
    answer = SimpleNamespace(choice=choice, confidence=confidence)
    result = helpers.route("crop", answer, 0.8)
    accepted = (
        choice in helpers.CATALOG and type(confidence) in (int, float) and 0.8 <= confidence <= 1
    )
    assert (result.outcome != helpers.REVIEW) == accepted
    assert result.item == "crop"


@pytest.mark.parametrize("threshold", [-1, 1.1, None, float("nan"), float("inf")])
def test_invalid_threshold_is_refused(threshold):
    with pytest.raises(ValueError):
        helpers.route("crop", SimpleNamespace(choice="sun_token", confidence=1), threshold)


def test_boundary_and_no_confidence():
    answer = SimpleNamespace(choice="sun_token", confidence=0.8)
    assert helpers.route("crop", answer, 0.8).outcome == "sun_token"
    assert helpers.route("crop", answer, 0.800001).outcome == helpers.REVIEW
    assert helpers.route("crop", object(), 0.8).outcome == helpers.REVIEW


def test_criteria_are_defined_by_reference_images_and_state_has_only_pixels():
    fields = {"crop": "assets/q01.png", "gold": "bad", "split": "leak", "rotation": 77}
    state, questions, assets = helpers.build_request(fields, RECIPE)
    assert set(state) == {"piece_crop"}
    assert list(questions["piece"].criteria) == [
        "sun_token",
        "ring_token",
        "bridge_tile",
        "scout_figurine",
        "river_card",
        "unknown",
    ]
    for name in helpers.CATALOG:
        assert "image:sha256:" in questions["piece"].criteria[name]
    assert len(assets) == 6
    assert not any(word in json.dumps(state) for word in ("gold", "split", "rotation", "q01"))


def test_current_keys_bind_state_reference_criteria_and_image_bytes():
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
    old = replay_key(state, questions, assets=assets)
    assert old != replay_key({**state, "note": "changed context"}, questions, assets=assets)
    changed = dict(assets)
    ref = next(iter(changed))
    changed[ref] = image_asset(RECIPE / "assets/q01.png")
    assert old != replay_key(state, questions, assets=changed)


def test_query_pixels_are_distinct_across_splits_and_from_references():
    pixels = set()
    for example in load_inputs(RECIPE):
        with Image.open(RECIPE / example.fields["crop"]) as image:
            assert image.size == (384, 320)
            digest = hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()
        assert digest not in pixels
        pixels.add(digest)
    for path in helpers.CATALOG.values():
        with Image.open(RECIPE / path) as image:
            assert hashlib.sha256(image.convert("RGB").tobytes()).hexdigest() not in pixels


def test_baseline_reads_pixels_not_labels_ids_or_drawing_parameters():
    baseline = helpers.ReferenceBaseline(RECIPE)
    fields = {"crop": "assets/q01.png"}
    actual = baseline.predict(fields)
    assert actual == baseline.predict(
        {**fields, "label": "river_card", "split": "test", "angle": 99}
    )
    for option, path in helpers.CATALOG.items():
        assert baseline.predict({"crop": path}).choice == option
    assert baseline.predict({"crop": "assets/q11.png"}).choice == "unknown"
    assert baseline.predict({"crop": "assets/q02.png"}).choice != actual.choice


def test_unknown_is_in_review_queue_and_never_coverage():
    examples = [SimpleNamespace(id="one"), SimpleNamespace(id="two")]
    answers = [
        SimpleNamespace(choice="unknown", confidence=1),
        SimpleNamespace(choice="sun_token", confidence=1),
    ]
    report = helpers.report(examples, answers, ["unknown", "sun_token"], 0.8)
    assert report["raw_accuracy"] == 1
    assert report["selective"].n_answered == 1
    assert report["abstention"] == 0.5
    assert report["review_queue"].pending()[0].item == {"piece_id": "one"}


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    validation = [e for e in examples if e.split == "validation"]
    named = [(helpers.decide(backend, e, RECIPE)["piece"], labels[e.id]) for e in validation]
    named = [(a, g) for a, g in named if a.choice in helpers.CATALOG]
    threshold = select_confidence_threshold(
        [a.choice == g for a, g in named], [a.confidence for a, _ in named], target_accuracy=1.0
    )
    test = [e for e in examples if e.split == "test"]
    answers = [helpers.decide(backend, e, RECIPE)["piece"] for e in test]
    wrong_and_confident = [
        e.id
        for e, a in zip(test, answers, strict=True)
        if a.choice != labels[e.id]
        and a.confidence >= threshold
        and helpers.route(e.id, a, threshold).outcome != helpers.REVIEW
    ]
    assert "t06" in wrong_and_confident
    assert len(wrong_and_confident) >= 1


def test_notebook_pins_the_threshold_objective_to_target_accuracy():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "python-rule")
    source = "".join(cell["source"])
    tree = ast.parse(source)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 2
    for call in calls:
        keywords = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
        assert keywords == {"target_accuracy": 1.0}
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
