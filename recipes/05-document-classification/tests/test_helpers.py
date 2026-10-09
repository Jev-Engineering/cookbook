"""Tests for recipe 05's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


CLEAR_INVOICE = answer(
    {"invoice": 0.88, "meeting_note": 0.03, "policy": 0.03, "technical_guide": 0.03, "other": 0.03}
)
CLEAR_POLICY = answer(
    {"invoice": 0.03, "meeting_note": 0.05, "policy": 0.86, "technical_guide": 0.03, "other": 0.03}
)

# One low-confidence answer per label, each barely ahead of the other four (confidence 0.0375),
# so a rule that exempts only one label from the threshold still fails this file's test for it.
LOW_CONFIDENCE_BY_LABEL = {
    "invoice": answer(
        {
            "invoice": 0.23,
            "meeting_note": 0.195,
            "policy": 0.195,
            "technical_guide": 0.19,
            "other": 0.19,
        }
    ),
    "meeting_note": answer(
        {
            "invoice": 0.195,
            "meeting_note": 0.23,
            "policy": 0.195,
            "technical_guide": 0.19,
            "other": 0.19,
        }
    ),
    "policy": answer(
        {
            "invoice": 0.195,
            "meeting_note": 0.19,
            "policy": 0.23,
            "technical_guide": 0.195,
            "other": 0.19,
        }
    ),
    "technical_guide": answer(
        {
            "invoice": 0.19,
            "meeting_note": 0.195,
            "policy": 0.19,
            "technical_guide": 0.23,
            "other": 0.195,
        }
    ),
    "other": answer(
        {
            "invoice": 0.19,
            "meeting_note": 0.19,
            "policy": 0.195,
            "technical_guide": 0.195,
            "other": 0.23,
        }
    ),
}


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["doc_type"]
    doc_type = questions["doc_type"]
    assert list(doc_type.criteria) == [
        "invoice",
        "meeting_note",
        "policy",
        "technical_guide",
        "other",
    ]
    assert all(isinstance(d, str) and d for d in doc_type.criteria.values())
    assert isinstance(doc_type.instructions, str) and doc_type.instructions


def test_a_confident_answer_is_accepted_whatever_the_label():
    for a in (CLEAR_INVOICE, CLEAR_POLICY):
        result = helpers.classify("D1", a, 0.3)
        assert (result.doc_id, result.label, result.outcome) == (
            "D1",
            a.choice,
            helpers.ACCEPTED,
        )


@pytest.mark.parametrize("label", ["invoice", "meeting_note", "policy", "technical_guide", "other"])
def test_a_low_confidence_answer_goes_to_review_whatever_the_label(label):
    a = LOW_CONFIDENCE_BY_LABEL[label]
    assert a.choice == label
    assert a.confidence < 0.5
    result = helpers.classify("D1", a, 0.5)
    assert result.outcome == helpers.REVIEW
    assert "threshold" in result.reason


def test_the_threshold_is_inclusive():
    t = CLEAR_INVOICE.confidence
    assert helpers.classify("D1", CLEAR_INVOICE, t).outcome == helpers.ACCEPTED
    assert helpers.classify("D1", CLEAR_INVOICE, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify("D1", CLEAR_INVOICE, bad)


def test_the_state_hides_the_doc_id():
    fields = {"doc_id": "D9", "text": "Invoice #1. Total due $10.00."}
    assert helpers.build_state(fields) == {"text": "Invoice #1. Total due $10.00."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example;
    # adapt this when an example needs a dependent second request (CONTRIBUTING: a question that
    # depends on an earlier answer goes in a later request), where the example lists a key for
    # each request in order.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)
