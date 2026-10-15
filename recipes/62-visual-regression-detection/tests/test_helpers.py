"""The confidence gate, screenshot baseline, and image-backed replay contract."""

import ast
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from jev_cookbook import (
    NoulAnswer,
    Provenance,
    ReplayMiss,
    ScoreAnswer,
    get_backend,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answers(*, probabilities=None, severity=(1.0, 0.0, 0.0, 0.0)):
    probabilities = {} if probabilities is None else probabilities
    provenance = Provenance.synthetic()
    result = {
        name: NoulAnswer(probabilities.get(name, 0.0), provenance)
        for name in ("missing", "misaligned", "clipped", "unexpected")
    }
    result["severity"] = ScoreAnswer.from_probabilities(severity, helpers.LEVELS, provenance)
    return result


@pytest.mark.parametrize(
    ("labels", "severity", "expected"),
    [((), 0, "clear"), (("missing",), 3, "flag")],
)
def test_clear_and_flag_pass_the_same_inclusive_confidence_gate(labels, severity, expected):
    assessment = helpers.Assessment(labels, severity, 0.8, True)
    accepted = helpers.route(assessment, 0.8)
    assert (accepted.outcome, accepted.labels, accepted.severity) == (
        expected,
        labels,
        severity,
    )
    rejected = helpers.route(assessment, 0.8 + 1e-9)
    assert rejected.outcome == helpers.REVIEW
    assert rejected.labels == ()
    assert rejected.reason == "confidence below the threshold"


@pytest.mark.parametrize("boundary", [0.0, 1.0])
def test_confidence_gate_accepts_endpoints(boundary):
    assessment = helpers.Assessment((), 0, boundary, True)
    assert helpers.route(assessment, boundary).outcome == "clear"


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("-inf"), float("inf")])
def test_invalid_confidence_thresholds_are_rejected(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.route(helpers.Assessment((), 0, 1.0, True), bad)


@pytest.mark.parametrize(
    ("probabilities", "severity", "expected_level"),
    [
        ({"missing": 1.0}, (1.0, 0.0, 0.0, 0.0), 0),
        ({}, (0.0, 0.0, 0.0, 1.0), 3),
    ],
)
def test_inconsistent_labels_and_severity_always_go_to_review(
    probabilities, severity, expected_level
):
    assessment = helpers.assess(answers(probabilities=probabilities, severity=severity))
    assert not assessment.consistent
    assert assessment.certainty == 1.0
    outcome = helpers.route(assessment, 0.0)
    assert (outcome.outcome, outcome.labels, outcome.severity) == (
        helpers.REVIEW,
        (),
        expected_level,
    )
    assert outcome.reason == "labels and severity disagree"


def test_inconsistency_takes_precedence_over_low_confidence():
    outcome = helpers.route(helpers.Assessment(("missing",), 0, 0.1, False), 0.9)
    assert outcome.outcome == helpers.REVIEW
    assert outcome.reason == "labels and severity disagree"


@pytest.mark.parametrize("weak_label", ["missing", "misaligned", "clipped", "unexpected"])
def test_certainty_includes_every_label_even_an_absent_one(weak_label):
    assessment = helpers.assess(answers(probabilities={weak_label: 0.4}))
    assert assessment.labels == ()
    assert assessment.certainty == pytest.approx(0.2)
    assert helpers.route(assessment, 0.5).outcome == helpers.REVIEW


def test_severity_certainty_can_be_the_weakest_signal():
    assessment = helpers.assess(answers(severity=(0.6, 0.4, 0.0, 0.0)))
    assert assessment.certainty == pytest.approx(0.6)
    assert helpers.route(assessment, 0.7).outcome == helpers.REVIEW


def test_assessment_uses_modal_severity_and_inclusive_label_boundary():
    result = answers(
        probabilities={"missing": 0.5, "clipped": 0.9},
        severity=(0.4, 0.0, 0.0, 0.6),
    )
    assert result["severity"].score == pytest.approx(1.8)
    assessment = helpers.assess(result)
    assert assessment.severity == 3
    assert assessment.labels == ("missing", "clipped")
    assert assessment.certainty == 0.0
    assert assessment.consistent


def test_tied_modal_severity_uses_the_lowest_level():
    assessment = helpers.assess(answers(severity=(0.5, 0.0, 0.0, 0.5)))
    assert assessment.severity == 0
    assert assessment.consistent


def test_correct_requires_exact_defects_and_severity_but_not_label_order():
    assessment = helpers.Assessment(("missing", "misaligned"), 3, 0.1, True)
    assert helpers.correct(assessment, {"defects": ["misaligned", "missing"], "severity": 3})
    assert not helpers.correct(assessment, {"defects": ["missing"], "severity": 3})
    assert not helpers.correct(
        assessment, {"defects": ["missing", "misaligned", "clipped"], "severity": 3}
    )
    assert not helpers.correct(assessment, {"defects": ["missing", "misaligned"], "severity": 2})


def test_request_state_excludes_gold_changes_ids_splits_and_file_paths():
    fields = {
        "before_ref": "image-before",
        "after_ref": "image-after",
        "before_path": "assets/before.png",
        "after_path": "assets/after.png",
        "id": "private-example-id",
        "split": "test",
        "change": "save_missing",
        "defects": ["missing"],
        "severity": 3,
        "gold": {"defects": ["missing"], "severity": 3},
    }
    state = helpers.build_state(fields)
    assert state == {
        "before": "image-before",
        "after": "image-after",
        "comparison_policy": helpers.POLICY,
    }


def write_pair(tmp_path, before, after):
    fields = {"before_path": "before.png", "after_path": "after.png"}
    Image.fromarray(np.asarray(before, dtype=np.uint8)).save(tmp_path / fields["before_path"])
    Image.fromarray(np.asarray(after, dtype=np.uint8)).save(tmp_path / fields["after_path"])
    return fields


def test_pixel_baseline_counts_actual_changed_pixels_with_strict_channel_tolerance(tmp_path):
    before = [
        [[0, 0, 0], [100, 100, 100]],
        [[255, 0, 0], [0, 0, 0]],
    ]
    after = [
        [[20, 0, 0], [100, 121, 100]],
        [[0, 0, 0], [0, 0, 255]],
    ]
    fields = write_pair(tmp_path, before, after)
    fraction, mask = helpers.pixel_difference(fields, tmp_path, tolerance=20)
    assert fraction == 0.75
    assert mask.dtype == np.bool_
    np.testing.assert_array_equal(mask, [[False, True], [True, True]])


@pytest.mark.parametrize(("tolerance", "expected"), [(0, 0.5), (255, 0.0)])
def test_pixel_tolerance_endpoints(tmp_path, tolerance, expected):
    fields = write_pair(tmp_path, [[[0, 0, 0], [0, 0, 0]]], [[[0, 0, 0], [255, 0, 0]]])
    fraction, _ = helpers.pixel_difference(fields, tmp_path, tolerance=tolerance)
    assert fraction == expected


@pytest.mark.parametrize("bad", [-1, 256, 1.0, True, float("nan")])
def test_invalid_pixel_tolerances_are_rejected_before_reading_images(tmp_path, bad):
    with pytest.raises(ValueError, match="integer between 0 and 255"):
        helpers.pixel_difference({}, tmp_path, tolerance=bad)


def test_pixel_baseline_rejects_different_shapes_even_with_equal_pixel_count(tmp_path):
    fields = write_pair(tmp_path, np.zeros((2, 3, 3)), np.zeros((3, 2, 3)))
    with pytest.raises(ValueError, match="equal image dimensions"):
        helpers.pixel_difference(fields, tmp_path)


def test_fixture_fields_and_assets_do_not_reveal_the_gold_labels():
    for example in load_inputs(RECIPE):
        assert set(example.fields) == {"before_path", "after_path", "before_ref", "after_ref"}
        for side in ("before", "after"):
            relative = Path(example.fields[f"{side}_path"])
            assert relative.parent == Path("assets")
            assert len(relative.stem) == 64
            int(relative.stem, 16)


def test_every_fixture_replay_key_matches_its_images_and_questions():
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        fields = example.fields
        key = replay_key(
            helpers.build_state(fields),
            questions,
            assets=helpers.build_assets(fields, RECIPE),
        )
        assert example.replay_keys == (key,)


def test_changing_pixels_under_the_same_reference_invalidates_replay(tmp_path):
    example = next(
        e for e in load_inputs(RECIPE) if e.fields["before_ref"] != e.fields["after_ref"]
    )
    fields = dict(example.fields)
    for side in ("before", "after"):
        path = tmp_path / f"{side}.png"
        path.write_bytes((RECIPE / fields[f"{side}_path"]).read_bytes())
        fields[f"{side}_path"] = path.name
    state = helpers.build_state(fields)
    questions = helpers.build_questions()
    original_assets = helpers.build_assets(fields, tmp_path)
    original_key = replay_key(state, questions, assets=original_assets)
    assert original_key == example.replay_keys[0]

    path = tmp_path / fields["after_path"]
    with Image.open(path) as stored:
        changed = stored.convert("RGB")
    red, green, blue = changed.getpixel((0, 0))
    changed.putpixel((0, 0), (red ^ 1, green, blue))
    changed.save(path)
    altered_assets = helpers.build_assets(fields, tmp_path)
    assert replay_key(state, questions, assets=altered_assets) != original_key
    backend = get_backend(fixtures=responses_path(RECIPE))
    with pytest.raises(ReplayMiss):
        backend.decide(state, questions, assets=altered_assets)


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    assessments = {
        example.id: helpers.assess(
            backend.decide(
                helpers.build_state(example.fields),
                questions,
                assets=helpers.build_assets(example.fields, RECIPE),
            )
        )
        for example in examples
        if example.id in labels
    }
    validation = [
        example
        for example in examples
        if example.split == "validation" and assessments[example.id].consistent
    ]
    threshold = select_confidence_threshold(
        [helpers.correct(assessments[e.id], labels[e.id]) for e in validation],
        [assessments[e.id].certainty for e in validation],
        target_accuracy=1.0,
    )
    test = [example for example in examples if example.split == "test"]
    outcomes = {e.id: helpers.route(assessments[e.id], threshold) for e in test}
    wrong_and_confident = [
        e.id
        for e in test
        if assessments[e.id].certainty >= threshold
        and outcomes[e.id].outcome != helpers.REVIEW
        and not helpers.correct(assessments[e.id], labels[e.id])
    ]
    assert wrong_and_confident, "the held-out split must expose a confidently wrong accepted answer"
    assert any(outcome.reason == "confidence below the threshold" for outcome in outcomes.values())
    assert any(outcome.reason == "labels and severity disagree" for outcome in outcomes.values())
    assert {outcome.outcome for outcome in outcomes.values()} == {"clear", "flag", helpers.REVIEW}


def test_notebook_pins_validation_selection_objectives_in_executable_source():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(cell for cell in notebook["cells"] if cell.get("id") == "evaluation-validation")
    tree = ast.parse("".join(cell["source"]))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    confidence_calls = [node for node in calls if node.func.id == "select_confidence_threshold"]
    pixel_calls = [node for node in calls if node.func.id == "select_threshold"]
    assert len(confidence_calls) == len(pixel_calls) == 1
    confidence_keywords = {keyword.arg: keyword.value for keyword in confidence_calls[0].keywords}
    assert ast.literal_eval(confidence_keywords["target_accuracy"]) == 1.0
    assert "min_coverage" not in confidence_keywords
    pixel_keywords = {keyword.arg: keyword.value for keyword in pixel_calls[0].keywords}
    assert ast.literal_eval(pixel_keywords["objective"]) == "f1"
