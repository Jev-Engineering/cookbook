"""The matching policy and its frozen validation choice are independent of image labels."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers
from jev_cookbook.evaluation import evaluate_outcomes, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(choice, probability=0.90):
    probabilities = dict.fromkeys(helpers.OPTIONS, (1 - probability) / (len(helpers.OPTIONS) - 1))
    probabilities[choice] = probability
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


@pytest.mark.parametrize("choice", ["sku_101", "sku_102", "sku_103", "sku_104", "no_match"])
def test_a_confident_catalog_match_or_no_match_is_only_a_proposal(choice):
    result = helpers.classify("query-a", answer(choice), 0.5)
    assert (result.query_id, result.label, result.outcome) == ("query-a", choice, "accepted")
    assert result.reason == "proposed visual match only"


@pytest.mark.parametrize("threshold", [0.0, 0.5, 1.0])
def test_unknown_is_always_review_even_when_certain(threshold):
    result = helpers.classify("query-a", answer("unknown", 1.0), threshold)
    assert result.outcome == "review"
    assert result.reason == "insufficient visible evidence"


@pytest.mark.parametrize("choice", ["sku_101", "no_match"])
def test_both_matches_and_no_match_obey_the_confidence_gate(choice):
    prediction = answer(choice, 0.60)
    result = helpers.classify("query-a", prediction, prediction.confidence + 1e-9)
    assert result.outcome == "review"
    assert result.reason == "confidence below the threshold"


@pytest.mark.parametrize("choice", ["sku_101", "no_match"])
def test_the_confidence_boundary_is_inclusive(choice):
    prediction = answer(choice)
    assert helpers.classify("query-a", prediction, prediction.confidence).outcome == "accepted"
    assert helpers.classify("query-a", prediction, prediction.confidence + 1e-9).outcome == "review"


@pytest.mark.parametrize("choice", ["purchase-now", "sku_999", "", None])
def test_a_foreign_option_cannot_be_accepted(choice):
    prediction = SimpleNamespace(choice=choice, confidence=1.0)
    result = helpers.classify("query-a", prediction, 0.0)
    assert result.outcome == "review"
    assert result.reason == "option outside the Python catalog"


@pytest.mark.parametrize(
    "threshold",
    [-0.1, 1.1, float("nan"), float("inf"), -float("inf"), True, False, "0.5", None],
)
def test_the_threshold_must_be_a_finite_number_between_zero_and_one(threshold):
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        helpers.classify("query-a", answer("sku_101"), threshold)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf"), -float("inf")])
def test_invalid_external_confidence_is_review(confidence):
    prediction = SimpleNamespace(choice="sku_101", confidence=confidence)
    result = helpers.classify("query-a", prediction, 0.0)
    assert result.outcome == "review"
    assert result.reason == "invalid confidence"


def test_coverage_uses_the_actual_policy_including_unknown_deferral():
    predictions = [answer("sku_101"), answer("no_match"), answer("unknown", 1.0)]
    decisions = [helpers.classify(str(index), item, 0.0) for index, item in enumerate(predictions)]
    result = evaluate_outcomes(
        [item.outcome == helpers.ACCEPTED for item in decisions], [True, False, True]
    )
    assert helpers.REVIEW == "review"
    assert result.n_total == 3
    assert result.n_answered == 2
    assert result.coverage == pytest.approx(2 / 3)
    assert result.accuracy == 0.5
    assert result.risk == 0.5


def test_the_pixel_radius_is_selected_on_the_supplied_validation_examples():
    evidence = [
        helpers.PixelEvidence("sku_101", 0.15, 0.85),
        helpers.PixelEvidence("sku_102", 0.30, 0.70),
    ]
    assert helpers.select_baseline_radius(evidence, ["sku_101", "no_match"]) == 0.20
    assert helpers.select_baseline_radius(evidence, ["no_match", "no_match"]) == 0.10


def test_pixel_radius_ties_choose_the_smaller_radius():
    evidence = [helpers.PixelEvidence("sku_101", 0.05, 0.95)]
    assert helpers.select_baseline_radius(evidence, ["sku_101"]) == 0.10


@pytest.mark.parametrize("evidence,gold", [([], []), ([], ["sku_101"])])
def test_pixel_radius_selection_requires_nonempty_aligned_validation(evidence, gold):
    with pytest.raises(ValueError, match="nonempty and aligned"):
        helpers.select_baseline_radius(evidence, gold)


def test_pixel_radius_boundary_and_missing_evidence():
    evidence = helpers.PixelEvidence("sku_101", 0.20, 0.80)
    assert helpers.baseline_prediction(evidence, 0.20).choice == "sku_101"
    assert helpers.baseline_prediction(evidence, 0.20 - 1e-9).choice == "no_match"
    missing = helpers.PixelEvidence("unknown", 1.0, 0.0)
    assert helpers.baseline_prediction(missing, 1.0).choice == "unknown"


def test_the_committed_notebook_pins_the_validation_coverage_objective():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "evaluation-validation")
    source = "".join(cell["source"])
    assert "min_coverage=0.5" in source
    assert "target_accuracy" not in source
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 2
    for call in calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert set(keywords) == {"min_coverage"}
        assert ast.literal_eval(keywords["min_coverage"]) == 0.5


def test_stored_answers_are_not_all_right():
    """At least one wrong test answer must survive the frozen gate and the actual policy."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)

    def decide(example):
        state, questions, assets = helpers.build_request(example.fields)
        return backend.decide(state, questions, assets=assets)["sku"]

    validation = [
        (example, decide(example)) for example in examples if example.split == "validation"
    ]
    eligible = [
        (prediction.choice == labels[example.id], prediction.confidence)
        for example, prediction in validation
        if prediction.choice != helpers.UNKNOWN
    ]
    threshold = select_confidence_threshold(
        [correct for correct, _ in eligible],
        [confidence for _, confidence in eligible],
        min_coverage=0.5,
    )
    test = [(example, decide(example)) for example in examples if example.split == "test"]
    wrong_and_accepted = [
        example.id
        for example, prediction in test
        if prediction.choice != labels[example.id]
        and prediction.confidence >= threshold
        and helpers.classify(example.id, prediction, threshold).outcome == helpers.ACCEPTED
    ]
    assert wrong_and_accepted, "expected a wrong test answer that survives both policy and gate"
