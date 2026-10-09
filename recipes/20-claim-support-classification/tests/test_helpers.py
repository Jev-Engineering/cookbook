"""Tests for recipe 20's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, validate_recipe

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# Literal expected values: this guard must fail if someone edits OPTIONS or the descriptions in
# helpers.py without updating this file, so it compares against values typed here, never against
# helpers' own data (which would make the assertion self-referential and unable to catch a
# mutation to either side at once).
EXPECTED_OPTIONS = ["supports", "contradicts", "unresolved"]


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


CLEAR_SUPPORTS = answer({"supports": 0.88, "contradicts": 0.05, "unresolved": 0.07})
CLEAR_UNRESOLVED = answer({"supports": 0.08, "contradicts": 0.07, "unresolved": 0.85})

# One low-confidence answer per label, each barely ahead of the other two (confidence 0.045),
# so a rule that exempted even one label from the threshold would still fail this file's test.
LOW_CONFIDENCE_BY_LABEL = {
    "supports": answer({"supports": 0.36, "contradicts": 0.32, "unresolved": 0.32}),
    "contradicts": answer({"supports": 0.32, "contradicts": 0.36, "unresolved": 0.32}),
    "unresolved": answer({"supports": 0.32, "contradicts": 0.32, "unresolved": 0.36}),
}


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["relation"]
    relation = questions["relation"]
    assert list(relation.criteria) == EXPECTED_OPTIONS
    assert all(isinstance(d, str) and d for d in relation.criteria.values())
    assert isinstance(relation.instructions, str) and relation.instructions


def test_a_confident_answer_is_accepted_whatever_the_label():
    for a in (CLEAR_SUPPORTS, CLEAR_UNRESOLVED):
        result = helpers.classify("PSG9001", a, 0.3)
        assert (result.passage_id, result.label, result.outcome) == (
            "PSG9001",
            a.choice,
            helpers.ACCEPTED,
        )
        assert result.reason == "confident"


@pytest.mark.parametrize("label", EXPECTED_OPTIONS)
def test_a_low_confidence_answer_goes_to_review_whatever_the_label(label):
    a = LOW_CONFIDENCE_BY_LABEL[label]
    assert a.choice == label
    assert a.confidence < 0.5
    result = helpers.classify("PSG9002", a, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "confidence below the threshold"


@pytest.mark.parametrize("outcome_answer", [CLEAR_SUPPORTS, LOW_CONFIDENCE_BY_LABEL["unresolved"]])
def test_the_passage_id_is_carried_through_for_every_outcome(outcome_answer):
    # Whether the rule accepts or sends an answer to review, the result must still name the
    # same passage it decided about: a result that dropped or swapped the identifier would be
    # silently unusable, because nothing else in the pipeline would know which passage it was.
    result = helpers.classify("PSG9003", outcome_answer, 0.5)
    assert result.passage_id == "PSG9003"
    assert result.outcome in (helpers.ACCEPTED, helpers.REVIEW)


def test_the_threshold_is_inclusive():
    t = CLEAR_SUPPORTS.confidence
    assert helpers.classify("PSG9001", CLEAR_SUPPORTS, t).outcome == helpers.ACCEPTED
    assert helpers.classify("PSG9001", CLEAR_SUPPORTS, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify("PSG9001", CLEAR_SUPPORTS, bad)


def test_the_state_hides_the_passage_id():
    fields = {"passage_id": "PSG9999", "claim": "X happened.", "passage": "X happened on Tuesday."}
    assert helpers.build_state(fields) == {
        "claim": "X happened.",
        "passage": "X happened on Tuesday.",
    }


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can.
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    assert validate_recipe(RECIPE).mode == "replay"
    for example in examples:
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)
