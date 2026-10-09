"""Tests for recipe 08's helpers. They load the helpers by file path."""

import math
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

REAL_FAQS = [
    "password_reset",
    "change_email",
    "cancel_subscription",
    "billing_cycle",
    "export_data",
    "delete_account",
]

# Literal expected values, independent of helpers.OPTIONS/helpers.ANSWERS, so a test failure
# means the rule's actual behaviour moved, not just that it still agrees with itself.
EXPECTED_OPTIONS = [
    "password_reset",
    "change_email",
    "cancel_subscription",
    "billing_cycle",
    "export_data",
    "delete_account",
    "no_match",
]


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
    assert list(questions) == ["faq"]
    faq = questions["faq"]
    assert list(faq.criteria) == EXPECTED_OPTIONS
    assert all(isinstance(d, str) and d for d in faq.criteria.values())
    assert isinstance(faq.instructions, str) and faq.instructions


@pytest.mark.parametrize("label", REAL_FAQS)
def test_a_confident_real_faq_is_matched_whatever_the_label(label):
    a = _confident(label)
    result = helpers.select_faq("Q1", a, 0.3)
    assert (result.question_id, result.label, result.outcome, result.answer) == (
        "Q1",
        label,
        helpers.MATCHED,
        helpers.ANSWERS[label],
    )


@pytest.mark.parametrize("label", REAL_FAQS)
def test_a_low_confidence_real_faq_goes_to_review_whatever_the_label(label):
    a = _low_confidence(label)
    assert a.choice == label
    assert a.confidence < 0.5
    result = helpers.select_faq("Q1", a, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.answer is None
    assert "threshold" in result.reason


@pytest.mark.parametrize("top_probability", [0.95, 0.20])
def test_no_match_is_never_gated_on_confidence_whatever_its_value(top_probability):
    # top_probability=0.20 keeps no_match as the top option (barely ahead of an even
    # seventh, ~0.143) while its confidence, (0.20 - 1/7) / (6/7) =~ 0.067, is well below the
    # 0.3 threshold used here. A mutation that exempted no_match from the gate only when it is
    # also confident would still fail this case, because it is checked at both ends.
    others = [o for o in helpers.OPTIONS if o != helpers.NO_MATCH]
    rest = (1.0 - top_probability) / len(others)
    a = answer({helpers.NO_MATCH: top_probability, **{o: rest for o in others}})
    assert a.choice == helpers.NO_MATCH
    result = helpers.select_faq("Q1", a, 0.3)
    assert result.outcome == helpers.NO_MATCH_OUTCOME
    assert result.answer is None
    assert result.label == helpers.NO_MATCH


def test_the_threshold_is_inclusive():
    a = _confident("password_reset")
    t = a.confidence
    assert helpers.select_faq("Q1", a, t).outcome == helpers.MATCHED
    assert helpers.select_faq("Q1", a, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.select_faq("Q1", _confident("password_reset"), bad)


def test_the_state_hides_the_question_id():
    fields = {"question_id": "Q9", "text": "How do I reset my password?"}
    assert helpers.build_state(fields) == {"question": "How do I reset my password?"}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# --- summarize_outcomes ----------------------------------------------------------------------


def _selection(question_id, label, outcome):
    return helpers.Selection(question_id, label, outcome, None, "test fixture")


def test_summarize_outcomes_counts_matched_and_no_match_as_answered():
    results = [
        _selection("a", "password_reset", helpers.MATCHED),
        _selection("b", "no_match", helpers.NO_MATCH_OUTCOME),
        _selection("c", "change_email", helpers.REVIEW),
    ]
    gold = {"a": "password_reset", "b": "no_match", "c": "change_email"}
    summary = helpers.summarize_outcomes(results, gold)
    assert summary.n_total == 3
    assert summary.n_answered == 2
    assert summary.coverage == pytest.approx(2 / 3)
    assert summary.accuracy == pytest.approx(1.0)
    assert summary.risk == pytest.approx(0.0)


def test_summarize_outcomes_counts_a_wrong_no_match_against_accuracy():
    # "b" is answered no_match, but the gold label is a real FAQ: the rule never gated this on
    # confidence (no_match has no gate), so it is a wrong, answered result, not an abstention.
    results = [
        _selection("a", "password_reset", helpers.MATCHED),
        _selection("b", "no_match", helpers.NO_MATCH_OUTCOME),
    ]
    gold = {"a": "password_reset", "b": "export_data"}
    summary = helpers.summarize_outcomes(results, gold)
    assert summary.n_answered == 2
    assert summary.accuracy == pytest.approx(0.5)
    assert summary.risk == pytest.approx(0.5)


def test_summarize_outcomes_is_nan_when_nothing_was_answered():
    results = [_selection("a", "password_reset", helpers.REVIEW)]
    summary = helpers.summarize_outcomes(results, {"a": "password_reset"})
    assert summary.n_answered == 0
    assert summary.coverage == 0.0
    assert math.isnan(summary.accuracy)
    assert math.isnan(summary.risk)


def test_summarize_outcomes_rejects_empty_input():
    with pytest.raises(ValueError, match="at least one"):
        helpers.summarize_outcomes([], {})
