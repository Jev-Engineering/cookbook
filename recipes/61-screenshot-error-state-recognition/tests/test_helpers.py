"""Policy, evidence isolation, pixel baseline and frozen-selection checks."""

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, select_split
from jev_cookbook.simulation import BudgetExceeded
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


@pytest.mark.parametrize("choice", helpers.RESOLVED)
@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), -1, 1.01, True, "1"])
def test_missing_or_invalid_confidence_never_passes(choice, confidence):
    answer = SimpleNamespace(choice=choice, confidence=confidence)
    assert not helpers.classify("sample", answer, 0).accepted


@pytest.mark.parametrize("choice", ["uncertain", "reload_now", None])
@pytest.mark.parametrize("confidence", [0, 0.5, 1])
def test_deferrals_and_unknown_options_never_pass(choice, confidence):
    answer = SimpleNamespace(choice=choice, confidence=confidence)
    assert not helpers.classify("sample", answer, 0).accepted


def test_inclusive_threshold():
    answer = SimpleNamespace(choice="normal", confidence=0.7)
    assert helpers.classify("sample", answer, 0.7).label == "normal"
    assert not helpers.classify("sample", answer, 0.70001).accepted


@pytest.mark.parametrize("threshold", [-1, 2, float("nan"), float("inf"), None, True])
def test_invalid_threshold_fails(threshold):
    with pytest.raises(ValueError, match="threshold"):
        helpers.classify("sample", SimpleNamespace(choice="normal", confidence=1), threshold)


def test_pixels_only_request_and_fixed_options():
    example = load_inputs(RECIPE)[0]
    fields = dict(example.fields, gold="crash", split="test", scenario="crash")
    state, assets = helpers.build_state(fields, RECIPE)
    assert set(state) == {"screenshot"}
    assert list(assets) == [state["screenshot"]]
    assert state["screenshot"].startswith("image:sha256:")
    assert list(helpers.build_questions()["screen_state"].criteria) == [
        "crash",
        "loading",
        "authentication_failure",
        "normal",
        "uncertain",
    ]


def test_every_replay_key_and_pixel_identity(tmp_path):
    questions = helpers.build_questions()
    seen = set()
    for example in load_inputs(RECIPE):
        state, assets = helpers.build_state(example.fields, RECIPE)
        key = replay_key(state, questions, assets=assets)
        assert example.replay_keys == (key,)
        with Image.open(RECIPE / example.fields["image"]) as image:
            digest = sha256(image.convert("RGB").tobytes()).hexdigest()
        assert digest not in seen, "a screenshot was duplicated across examples"
        seen.add(digest)
    original = load_inputs(RECIPE)[0]
    state, assets = helpers.build_state(original.fields, RECIPE)
    original_key = replay_key(state, questions, assets=assets)
    with Image.open(RECIPE / original.fields["image"]) as image:
        image.putpixel((0, 0), (17, 19, 23))
        changed = tmp_path / "changed.png"
        image.save(changed)
    swapped = {state["screenshot"]: image_asset(changed)}
    assert replay_key(state, questions, assets=swapped) != original_key
    assert (
        replay_key(dict(state, context="different task"), questions, assets=assets) != original_key
    )


def test_baseline_reads_pixels_and_handles_meaningful_cases(tmp_path):
    examples = {e.id: e for e in load_inputs(RECIPE)}
    expected = {
        "v01": "normal",
        "v02": "normal",
        "v03": "authentication_failure",
        "v04": "loading",
        "v05": "crash",
    }
    for ident, label in expected.items():
        assert helpers.baseline_for(examples[ident], RECIPE) == label
    original = RECIPE / examples["v03"].fields["image"]
    renamed = tmp_path / "normal.png"
    renamed.write_bytes(original.read_bytes())
    with Image.open(renamed) as image:
        assert helpers.pixel_baseline(image) == "authentication_failure"
    # The benign modal fools the palette heuristic: it cannot understand the button text.
    assert helpers.baseline_for(examples["v07"], RECIPE) != "normal"


def test_request_budget_and_cache():
    backend = get_backend(fixtures=RECIPE / "fixtures" / "responses.json")
    session = helpers.Session(backend, RECIPE, limit=1)
    first, second = load_inputs(RECIPE)[:2]
    assert session.decide(first) is session.decide(first)
    assert session.budget.used("requests") == 1
    with pytest.raises(BudgetExceeded):
        session.decide(second)
    assert session.budget.used("requests") == 1
    assert second.id not in session.results


def test_cache_identity_includes_changed_evidence():
    backend = get_backend(fixtures=RECIPE / "fixtures" / "responses.json")
    session = helpers.Session(backend, RECIPE)
    first, second = load_inputs(RECIPE)[:2]
    session.decide(first)
    changed = SimpleNamespace(id=first.id, fields=second.fields)
    assert session.decide(changed) is not session.decide(first)
    assert session.budget.used("requests") == 2


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=RECIPE / "fixtures" / "responses.json")
    session = helpers.Session(backend, RECIPE)
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = [e for e in examples if e.split == "validation"]
    named = [
        (session.decide(e)["screen_state"], labels[e.id])
        for e in validation
        if session.decide(e)["screen_state"].choice in helpers.RESOLVED
    ]
    threshold = select_confidence_threshold(
        [answer.choice == gold for answer, gold in named],
        [answer.confidence for answer, _ in named],
        target_accuracy=1.0,
    )
    test = [e for e in examples if e.split == "test"]
    wrong_and_confident = [
        e.id
        for e in test
        if session.decide(e)["screen_state"].choice != labels[e.id]
        and session.decide(e)["screen_state"].confidence >= threshold
        and helpers.classify(e.id, session.decide(e)["screen_state"], threshold).accepted
    ]
    assert wrong_and_confident == ["t06"]
    outcomes, review = helpers.review_outcomes(test, session.results, threshold)
    assert len(review) == sum(not outcome.accepted for outcome in outcomes)
    assert all(o.outcome == "review" for o in outcomes if not o.accepted)
    assert {item.item["screenshot_id"] for item in review.pending()} == {"t08", "t10", "t11"}


def test_notebook_pins_selection_objective():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source


@pytest.mark.parametrize("choice", ["uncertain", "normal"])
def test_unqualified_validation_stops_before_test_requests(choice):
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    source = "".join(next(c for c in notebook["cells"] if c["id"] == "python-rule")["source"])
    examples = load_inputs(RECIPE)
    requested = []

    class FixedSession:
        results = {}

        def decide(self, example):
            requested.append(example)
            self.results[example.id] = {
                "screen_state": SimpleNamespace(choice=choice, confidence=1.0)
            }

    scope = {
        "examples": examples,
        "labels": {e.id: "crash" for e in examples},
        "session": FixedSession(),
        "helpers": helpers,
        "select_split": select_split,
        "select_confidence_threshold": select_confidence_threshold,
    }
    with pytest.raises(RuntimeError, match="No validation policy qualified"):
        exec(compile(source, "<validation-policy-cell>", "exec"), scope)
    assert requested
    assert all(e.split == "validation" for e in requested)
