"""Interlocks, image identity, selection discipline and a deliberately surviving error."""

import ast
import inspect
import json
from pathlib import Path

import pytest
from PIL import Image

from jev_cookbook import (
    BoxAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    ReplayBackend,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import image_asset, image_reference

ROOT = Path(__file__).resolve().parent.parent
helpers = load_helpers(ROOT)
PROVENANCE = Provenance.synthetic()
BOX = {"top": 0.1, "bottom": 0.4, "left": 0.2, "right": 0.5}


def evidence(p, u, confidence=0.95):
    screen = DecisionResult(
        {"present": NoulAnswer(p, PROVENANCE), "unique": NoulAnswer(u, PROVENANCE)}, "synthetic"
    )
    located = DecisionResult(
        {"target": BoxAnswer(box=BOX, confidence=confidence, provenance=PROVENANCE)}, "synthetic"
    )
    return helpers.Evidence(screen, located, 2)


@pytest.mark.parametrize("p", [0, 0.19, 0.2, 0.3, 0.5, 0.79, 0.8, 1])
@pytest.mark.parametrize("u", [0, 0.19, 0.2, 0.3, 0.5, 0.79, 0.8, 1])
def test_presence_and_unique_interlock_under_arbitrary_answers(p, u):
    outcome = helpers.route(evidence(p, u), 0.84)
    assert (outcome.outcome == "located") == (p >= 0.8 and u >= 0.8)
    assert (outcome.outcome == "absent") == (p <= 0.2 and u <= 0.2)
    if outcome.outcome != "located":
        assert outcome.box is None


@pytest.mark.parametrize("confidence", [None, 0.0, 0.83])
def test_missing_and_low_box_confidence_require_review(confidence):
    assert helpers.route(evidence(0.99, 0.99, confidence), 0.84).outcome == helpers.REVIEW


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan"), float("inf")])
def test_bad_threshold_is_rejected(threshold):
    with pytest.raises(ValueError):
        helpers.route(evidence(0.99, 0.99), threshold)


def test_search_budget_and_dependent_box():
    class Spy:
        def __init__(self, p, u):
            self.ev = evidence(p, u)
            self.calls = []

        def decide(self, state, questions, *, assets):
            self.calls.append(questions)
            return self.ev.screen if "present" in questions else self.ev.located

    fields = load_inputs(ROOT)[0].fields
    for p, u, expected in ((0.99, 0.99, 2), (0.01, 0.02, 1), (0.99, 0.02, 1), (0.01, 0.99, 1)):
        spy = Spy(p, u)
        found = helpers.search(spy, fields, ROOT)
        assert found.requests == len(spy.calls) == expected
        assert set(spy.calls[0]) == {"present", "unique"}
    for budget in (0, 1):
        spy = Spy(0.99, 0.99)
        found = helpers.search(spy, fields, ROOT, max_requests=budget)
        assert len(spy.calls) == budget
        assert helpers.route(found, 0.84).outcome == helpers.REVIEW
    with pytest.raises(ValueError):
        helpers.search(Spy(1, 1), fields, ROOT, max_requests=3)


def test_actions_are_only_highlights_and_reviews_never_count_as_actions():
    actions, reviews = ActionLog(), ReviewQueue()
    for idx, ev in enumerate((evidence(0.99, 0.99), evidence(0.01, 0.02), evidence(0.99, 0.1))):
        helpers.simulate(str(idx), helpers.route(ev, 0.84), actions, reviews)
    assert len(actions) == len(reviews) == 1
    assert actions.to_dicts()[0]["kind"] == "highlight"
    assert actions.to_dicts()[0]["executed"] is False


def test_replay_keys_cover_reference_in_instructions_and_every_pixel(tmp_path):
    examples = load_inputs(ROOT)
    backend = ReplayBackend.from_json(ROOT / "fixtures/responses.json")
    for example in examples:
        for index, stage in enumerate(("screen", "box")):
            state, questions, assets = helpers.request(example.fields, ROOT, stage=stage)
            key = replay_key(state, questions, assets=assets)
            assert key == example.replay_keys[index]
            backend.decide(state, questions, assets=assets)
            assert set(state) == {"scene"}
            assert len(assets) == 2
            rref = image_reference(image_asset(ROOT / example.fields["reference"]))
            assert all(rref in question.instructions for question in questions.values())
    fields = examples[0].fields
    state, questions, assets = helpers.request(fields, ROOT, stage="box")
    original = replay_key(state, questions, assets=assets)
    assert replay_key({**state, "note": "different context"}, questions, assets=assets) != original
    for ref in assets:
        original_path = fields["query"] if ref == state["scene"] else fields["reference"]
        with Image.open(ROOT / original_path) as image:
            changed = image.copy()
        changed.putpixel((0, 0), (1, 2, 3))
        path = tmp_path / "pixel.png"
        changed.save(path)
        assert replay_key(state, questions, assets={**assets, ref: image_asset(path)}) != original
    changed_fields = {**fields, "reference": "assets/reference-2.png"}
    new_state, new_questions, new_assets = helpers.request(changed_fields, ROOT, stage="box")
    assert replay_key(new_state, new_questions, assets=new_assets) != original


def test_query_lineage_is_disjoint_and_references_are_independent():
    examples = load_inputs(ROOT)
    refs = {image_reference(image_asset(ROOT / e.fields["reference"])) for e in examples}
    hashes = {}
    for example in examples:
        with Image.open(ROOT / example.fields["query"]) as image:
            pixels = image.tobytes()
        assert pixels not in hashes
        hashes[pixels] = example.id
        assert image_reference(image_asset(ROOT / example.fields["query"])) not in refs
    labels = load_labels(ROOT)
    assert {label["case"] for label in labels.values()} >= {
        "rotated",
        "occluded",
        "lookalike",
        "multiple",
        "absent",
        "instruction",
    }


def test_stored_answers_are_not_all_right():
    examples, labels = load_inputs(ROOT), load_labels(ROOT)
    backend = ReplayBackend.from_json(ROOT / "fixtures/responses.json")
    validation = [e for e in examples if e.split == "validation"]
    stored = {e.id: helpers.search(backend, e.fields, ROOT) for e in validation}
    pairs = helpers.validation_pairs(validation, stored, labels)
    threshold = select_confidence_threshold(
        [right for right, _ in pairs],
        [confidence for _, confidence in pairs],
        target_accuracy=1.0,
    )
    assert threshold == helpers.choose_gate(validation, stored, labels) == 0.84
    wrong_above_gate = []
    for example in [e for e in examples if e.split == "test"]:
        ev = helpers.search(backend, example.fields, ROOT)
        outcome = helpers.route(ev, threshold)
        if ev.located is not None:
            confidence = ev.located.answers["target"].confidence
            if confidence is not None and confidence >= threshold:
                wrong_above_gate.append(
                    outcome.outcome != helpers.REVIEW
                    and not helpers.correct(outcome, labels[example.id])
                )
    assert any(wrong_above_gate)


def test_objective_is_pinned_to_the_production_call():
    source = inspect.getsource(helpers.choose_gate)
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    assert {kw.arg: ast.literal_eval(kw.value) for kw in calls[0].keywords} == {
        "target_accuracy": 1.0
    }
    assert "target_accuracy=1.0" in source
    notebook = json.loads((ROOT / "notebook.ipynb").read_text())
    validation = next(cell for cell in notebook["cells"] if cell["id"] == "evaluation-validation")
    assert "helpers.choose_gate(validation, evidence, labels)" in "".join(validation["source"])
    baseline_source = inspect.getsource(helpers.choose_template_tolerance)
    assert '3 * report["accepted_errors"] + report["review"]' in baseline_source


def test_selection_rejects_test_data():
    test = [e for e in load_inputs(ROOT) if e.split == "test"]
    with pytest.raises(ValueError, match="validation"):
        helpers.choose_gate(test, {}, {})
    with pytest.raises(ValueError, match="validation"):
        helpers.choose_template_tolerance(test, {}, {})


def test_baseline_depends_on_pixels_not_filename_or_labels(tmp_path):
    example = load_inputs(ROOT)[0]
    query, reference = ROOT / example.fields["query"], ROOT / example.fields["reference"]
    first = helpers.template_candidates(query, reference)
    renamed = tmp_path / "arbitrary.png"
    renamed.write_bytes(query.read_bytes())
    assert helpers.template_candidates(renamed, reference) == first
    Image.new("RGB", (480, 360), "white").save(renamed)
    blank = helpers.template_candidates(renamed, reference)
    assert blank != first
    assert helpers.template_outcome(blank, 0.1).outcome == "absent"


def test_baseline_retains_two_horizontal_matches_before_suppression(tmp_path):
    reference = ROOT / "assets/reference-0.png"
    with Image.open(reference) as image:
        bottle = image.crop((136, 72, 248, 248)).resize((56, 88))
    query = Image.new("RGB", (480, 360), (218, 214, 201))
    query.paste(bottle, (40, 80))
    query.paste(bottle, (240, 80))
    query_path = tmp_path / "two.png"
    query.save(query_path)
    candidates = helpers.template_candidates(query_path, reference)
    assert helpers.template_outcome(candidates, 0.16).outcome == helpers.REVIEW


def test_metrics_count_review_separately_from_absence_and_ambiguity():
    examples = load_inputs(ROOT)[:4]
    labels = {e.id: {"boxes": [BOX]} for e in examples}
    labels[examples[2].id] = {"boxes": []}
    labels[examples[3].id] = {"boxes": [BOX, BOX]}
    outcomes = {
        examples[0].id: helpers.Outcome(helpers.REVIEW, None, "unclear"),
        examples[1].id: helpers.Outcome("absent", None, "missed"),
        examples[2].id: helpers.Outcome("located", BOX, "false positive"),
        examples[3].id: helpers.Outcome("located", BOX, "ambiguous"),
    }
    report = helpers.summarize(examples, outcomes, labels)
    assert report["review"] == report["unique_present_review"] == 1
    assert report["unique_present_N"] == report["unique_present_undelivered"] == 2
    assert report["unique_present_delivery_mean_iou"] == 0
    assert report["accepted"] == report["accepted_errors"] == 3
    assert report["localization"]["resolved_N"] == 2
    assert report["localization"]["missed"] == report["localization"]["false_positives"] == 1
    assert report["multiple_accepted"] == 1
