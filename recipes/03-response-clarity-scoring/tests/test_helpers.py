"""Tests for recipe 03's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import Provenance, ScoreAnswer, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import score_level, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, validate_recipe

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
LEVELS = list(helpers.CLARITY_LEVELS)


def answer(probabilities):
    return ScoreAnswer.from_probabilities(probabilities, LEVELS, Provenance.synthetic())


CONFIDENT_EXEMPLARY = answer([0.01, 0.02, 0.08, 0.89])  # level 3, high confidence
CONFIDENT_CONFUSING = answer([0.80, 0.12, 0.05, 0.03])  # level 0, high confidence

# One low-confidence answer peaking at each of the four levels, spread close to even, so a rule
# that exempted one level from the threshold would still fail the parametrized test below.
LOW_CONFIDENCE_BY_LEVEL = {
    0: answer([0.28, 0.26, 0.24, 0.22]),
    1: answer([0.24, 0.28, 0.26, 0.22]),
    2: answer([0.22, 0.24, 0.28, 0.26]),
    3: answer([0.22, 0.24, 0.26, 0.28]),
}


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["clarity"]
    clarity = questions["clarity"]
    assert list(clarity.criteria) == list(helpers.CLARITY_LEVELS)
    assert all(isinstance(level, str) and level for level in clarity.criteria)
    assert isinstance(clarity.instructions, str) and clarity.instructions


def test_a_confident_answer_at_or_above_the_cutoff_is_accepted():
    result = helpers.classify("R1", CONFIDENT_EXEMPLARY, 0.3)
    assert (result.response_id, result.level, result.outcome) == ("R1", 3, helpers.ACCEPTED)


def test_a_confident_answer_below_the_cutoff_needs_an_edit():
    result = helpers.classify("R1", CONFIDENT_CONFUSING, 0.3)
    assert (result.response_id, result.level, result.outcome) == ("R1", 0, helpers.NEEDS_EDIT)


@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_a_low_confidence_answer_goes_to_review_whatever_the_level(level):
    a = LOW_CONFIDENCE_BY_LEVEL[level]
    result = helpers.classify("R1", a, 0.5)
    assert a.confidence < 0.5
    assert result.outcome == helpers.REVIEW
    assert "threshold" in result.reason


def test_the_threshold_is_inclusive():
    t = CONFIDENT_EXEMPLARY.confidence
    assert helpers.classify("R1", CONFIDENT_EXEMPLARY, t).outcome == helpers.ACCEPTED
    assert helpers.classify("R1", CONFIDENT_EXEMPLARY, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify("R1", CONFIDENT_EXEMPLARY, bad)


def test_the_cutoff_is_exactly_at_clear():
    # EDIT_CUTOFF marks the boundary: CLEAR (level 2) and above need no edit; below it, do.
    just_below = answer([0.05, 0.85, 0.05, 0.05])  # level 1
    just_at = answer([0.05, 0.05, 0.85, 0.05])  # level 2
    assert helpers.classify("R1", just_below, 0.0).outcome == helpers.NEEDS_EDIT
    assert helpers.classify("R1", just_at, 0.0).outcome == helpers.ACCEPTED


def test_the_state_hides_the_response_id():
    fields = {"response_id": "R9", "response": "Your order has shipped."}
    assert helpers.build_state(fields) == {"response": "Your order has shipped."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    assert validate_recipe(RECIPE).mode == "replay"
    for example in examples:
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    """A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    caught every mistake, which would hide the exact lesson this fixture set exists to teach.
    Re-derive the threshold the way the notebook does (the lowest confidence at which every
    validation answer's modal level matches the gold level) and require a wrong `test` answer
    at or above it: a mistake the gate would still let through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["clarity"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_correct = [score_level(decide(e)) == labels[e.id] for e in validation]
    val_confidence = [decide(e).confidence for e in validation]
    threshold = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id
        for e in test
        if score_level(decide(e)) != labels[e.id] and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
