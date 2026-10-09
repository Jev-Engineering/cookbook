"""Tests for recipe 11's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_outcomes
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# Literal expected values, independent of helpers.OPTIONS/helpers.CLARIFYING_QUESTIONS, so a
# test failure means the rule's actual behaviour moved, not just that it still agrees with
# itself.
EXPECTED_OPTIONS = [
    "ask_deadline",
    "ask_recipient",
    "ask_scope",
    "ask_format",
    "ask_budget",
    "ask_access_level",
    "no_clarification_needed",
]
ASK_LABELS = [
    "ask_deadline",
    "ask_recipient",
    "ask_scope",
    "ask_format",
    "ask_budget",
    "ask_access_level",
]
# The stored payload Python hands back for a confident match is the thing this recipe exists to
# keep out of the model's hands; this literal, independent of helpers.CLARIFYING_QUESTIONS, is
# what pins it (a test against the same dict the rule reads would pass even if every value were
# swapped for another option's).
EXPECTED_QUESTIONS = {
    "ask_deadline": "By when do you need this finished?",
    "ask_recipient": "Who should receive the result once it's ready?",
    "ask_scope": "Which records or time period should this cover?",
    "ask_format": "What file format or type should the result be in?",
    "ask_budget": "Is there a budget or spending limit this needs to stay under?",
    "ask_access_level": "Who besides you should be able to view or edit this once it's created?",
}


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def _confident(label):
    """A clearly confident answer for ``label``, with the rest of the mass spread evenly."""
    others = [o for o in helpers.OPTIONS if o != label]
    rest = (1.0 - 0.9) / len(others)
    return answer({label: 0.9, **{o: rest for o in others}})


def _low_confidence(label):
    """A low-confidence answer for ``label``: barely ahead of the other six options."""
    others = [o for o in helpers.OPTIONS if o != label]
    rest = (1.0 - 0.20) / len(others)
    return answer({label: 0.20, **{o: rest for o in others}})


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["clarification"]
    clarification = questions["clarification"]
    assert list(clarification.criteria) == EXPECTED_OPTIONS
    assert all(isinstance(d, str) and d for d in clarification.criteria.values())
    assert isinstance(clarification.instructions, str) and clarification.instructions


@pytest.mark.parametrize("label", ASK_LABELS)
def test_a_confident_catalog_question_is_asked_whatever_the_label(label):
    a = _confident(label)
    result = helpers.select_followup("T1", a, 0.3)
    assert (result.task_id, result.label, result.outcome, result.question) == (
        "T1",
        label,
        helpers.ASK,
        EXPECTED_QUESTIONS[label],
    )


@pytest.mark.parametrize("label", ASK_LABELS)
def test_a_low_confidence_catalog_question_goes_to_review_whatever_the_label(label):
    a = _low_confidence(label)
    assert a.choice == label
    assert a.confidence < 0.5
    result = helpers.select_followup("T1", a, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.question is None
    assert result.reason == "confidence below the threshold"


@pytest.mark.parametrize("top_probability", [0.95, 0.20])
def test_no_clarification_needed_is_never_gated_on_confidence_whatever_its_value(
    top_probability,
):
    # top_probability=0.20 keeps no_clarification_needed as the top option (barely ahead of an
    # even seventh, ~0.143) while its confidence, (0.20 - 1/7) / (6/7) =~ 0.067, is well below
    # the 0.3 threshold used here. A mutation that exempted no_clarification_needed from the
    # gate only when it is also confident would still fail this case, because it is checked at
    # both ends.
    others = [o for o in helpers.OPTIONS if o != helpers.NO_CLARIFICATION_NEEDED]
    rest = (1.0 - top_probability) / len(others)
    a = answer({helpers.NO_CLARIFICATION_NEEDED: top_probability, **{o: rest for o in others}})
    assert a.choice == helpers.NO_CLARIFICATION_NEEDED
    result = helpers.select_followup("T1", a, 0.3)
    assert result.outcome == helpers.PROCEED
    assert result.question is None
    assert result.label == helpers.NO_CLARIFICATION_NEEDED


def test_the_threshold_is_inclusive():
    a = _confident("ask_deadline")
    t = a.confidence
    assert helpers.select_followup("T1", a, t).outcome == helpers.ASK
    assert helpers.select_followup("T1", a, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.select_followup("T1", _confident("ask_deadline"), bad)


def test_a_foreign_option_goes_to_review_defensively():
    # build_questions never offers an option outside OPTIONS, so this can only happen if the
    # rule's own defensive check is removed; the test still names the behaviour it protects.
    class FakeAnswer:
        choice = "ask_something_not_in_the_catalog"
        confidence = 0.99

    result = helpers.select_followup("T1", FakeAnswer(), 0.3)
    assert result.outcome == helpers.REVIEW
    assert "catalog" in result.reason


def test_the_state_hides_the_task_id():
    fields = {"task_id": "T9", "text": "Pull together the onboarding checklist."}
    assert helpers.build_state(fields) == {"task": "Pull together the onboarding checklist."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# --- outcome_accounting, composed with jev_cookbook.evaluation.evaluate_outcomes -------------


def _selection(task_id, label, outcome):
    return helpers.Selection(task_id, label, outcome, None, "test fixture")


def test_outcome_accounting_counts_ask_and_proceed_as_answered():
    results = [
        _selection("a", "ask_deadline", helpers.ASK),
        _selection("b", "no_clarification_needed", helpers.PROCEED),
        _selection("c", "ask_recipient", helpers.REVIEW),
    ]
    gold = {"a": "ask_deadline", "b": "no_clarification_needed", "c": "ask_recipient"}
    accepted, correct = helpers.outcome_accounting(results, gold)
    assert accepted == [True, True, False]
    assert correct == [True, True, True]
    summary = evaluate_outcomes(accepted, correct)
    assert summary.n_total == 3
    assert summary.n_answered == 2
    assert summary.coverage == pytest.approx(2 / 3)
    assert summary.accuracy == pytest.approx(1.0)
    assert summary.risk == pytest.approx(0.0)


def test_outcome_accounting_counts_a_wrong_proceed_against_accuracy():
    # "b" is answered no_clarification_needed, but the gold label asks for something: the rule
    # never gated this on confidence (no_clarification_needed has no gate), so it is a wrong,
    # answered result, not an abstention.
    results = [
        _selection("a", "ask_deadline", helpers.ASK),
        _selection("b", "no_clarification_needed", helpers.PROCEED),
    ]
    gold = {"a": "ask_deadline", "b": "ask_recipient"}
    accepted, correct = helpers.outcome_accounting(results, gold)
    assert accepted == [True, True]
    assert correct == [True, False]
    summary = evaluate_outcomes(accepted, correct)
    assert summary.n_answered == 2
    assert summary.accuracy == pytest.approx(0.5)
    assert summary.risk == pytest.approx(0.5)


def test_outcome_accounting_rejects_empty_input():
    with pytest.raises(ValueError, match="at least one"):
        helpers.outcome_accounting([], {})
