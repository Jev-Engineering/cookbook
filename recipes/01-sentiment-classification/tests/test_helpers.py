"""Tests for recipe 01's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, ScriptedBackend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, validate_recipe

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


CLEAR_POSITIVE = answer({"positive": 0.90, "neutral": 0.04, "negative": 0.03, "mixed": 0.03})
CLEAR_MIXED = answer({"positive": 0.22, "neutral": 0.05, "negative": 0.18, "mixed": 0.55})
NEAR_EVEN = answer({"positive": 0.30, "neutral": 0.26, "negative": 0.24, "mixed": 0.20})


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["sentiment"]
    sentiment = questions["sentiment"]
    assert list(sentiment.criteria) == ["positive", "neutral", "negative", "mixed"]
    assert all(isinstance(d, str) and d for d in sentiment.criteria.values())
    assert isinstance(sentiment.instructions, str) and sentiment.instructions


def test_a_confident_answer_is_accepted_whatever_the_label():
    for a in (CLEAR_POSITIVE, CLEAR_MIXED):
        result = helpers.classify("R1", a, 0.3)
        assert (result.review_id, result.label, result.outcome) == (
            "R1",
            a.choice,
            helpers.ACCEPTED,
        )


def test_a_low_confidence_answer_goes_to_review_whatever_the_label():
    assert NEAR_EVEN.confidence < 0.5
    result = helpers.classify("R1", NEAR_EVEN, 0.5)
    assert result.outcome == helpers.REVIEW
    assert "threshold" in result.reason


def test_the_threshold_is_inclusive():
    t = CLEAR_POSITIVE.confidence
    assert helpers.classify("R1", CLEAR_POSITIVE, t).outcome == helpers.ACCEPTED
    assert helpers.classify("R1", CLEAR_POSITIVE, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify("R1", CLEAR_POSITIVE, bad)


def test_the_state_hides_the_review_id():
    fields = {"review_id": "R9", "text": "It works fine."}
    assert helpers.build_state(fields) == {"text": "It works fine."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can.
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    if validate_recipe(RECIPE).mode == "scripted":
        # A scripted recipe replays nothing: no example lists a key, and helpers.script gives the
        # same answer to the same request every time (a fresh backend each time, same seed).
        for example in examples:
            assert example.replay_keys == ()
            state = helpers.build_state(example.fields)
            first = ScriptedBackend(helpers.script, helpers.SEED).decide(state, questions)
            second = ScriptedBackend(helpers.script, helpers.SEED).decide(state, questions)
            assert first.to_dict() == second.to_dict()
        return
    # A replay recipe: one request per example; adapt this when an example needs a dependent
    # second request (CONTRIBUTING: a question that depends on an earlier answer goes in a later
    # request), where the example lists a key for each request in order.
    for example in examples:
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)
