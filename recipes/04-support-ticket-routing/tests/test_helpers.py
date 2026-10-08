"""Tests for recipe 04's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

REAL_CATEGORIES = ["billing", "technical_issue", "account_access", "feature_request"]


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def _confident(label):
    """A clearly confident answer for ``label``, with the rest of the mass spread evenly."""
    others = [o for o in helpers.OPTIONS if o != label]
    rest = (1.0 - 0.9) / len(others)
    return answer({label: 0.9, **{o: rest for o in others}})


def _low_confidence(label):
    """A low-confidence answer for ``label``: barely ahead of the other four options."""
    others = [o for o in helpers.OPTIONS if o != label]
    rest = (1.0 - 0.24) / len(others)
    return answer({label: 0.24, **{o: rest for o in others}})


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["category"]
    category = questions["category"]
    assert list(category.criteria) == list(helpers.OPTIONS)
    assert all(isinstance(d, str) and d for d in category.criteria.values())
    assert isinstance(category.instructions, str) and category.instructions


@pytest.mark.parametrize("label", REAL_CATEGORIES)
def test_a_confident_real_category_is_routed_to_its_queue_whatever_the_label(label):
    a = _confident(label)
    result = helpers.route_ticket("T1", a, 0.3)
    assert (result.ticket_id, result.label, result.outcome, result.queue) == (
        "T1",
        label,
        helpers.ROUTED,
        helpers.QUEUES[label],
    )


@pytest.mark.parametrize("label", REAL_CATEGORIES)
def test_a_low_confidence_real_category_goes_to_review_whatever_the_label(label):
    a = _low_confidence(label)
    assert a.choice == label
    assert a.confidence < 0.5
    result = helpers.route_ticket("T1", a, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.queue is None
    assert "threshold" in result.reason


@pytest.mark.parametrize("top_probability", [0.95, 0.22])
def test_unclear_request_is_never_routed_to_a_queue_whatever_its_confidence(top_probability):
    # top_probability=0.22 keeps unclear_request as the top option (barely ahead of an even
    # fifth, 0.2) while landing its confidence, (0.22 - 0.2) / 0.8 = 0.025, below the 0.3
    # threshold used here. A mutation that exempted unclear_request from this rule only when
    # it is also low-confidence would still fail this case, because it is checked at both ends.
    others = [o for o in helpers.OPTIONS if o != helpers.UNCLEAR_REQUEST]
    rest = (1.0 - top_probability) / len(others)
    a = answer({helpers.UNCLEAR_REQUEST: top_probability, **{o: rest for o in others}})
    assert a.choice == helpers.UNCLEAR_REQUEST
    result = helpers.route_ticket("T1", a, 0.3)
    assert result.outcome == helpers.UNCLEAR
    assert result.queue is None
    assert result.label == helpers.UNCLEAR_REQUEST


def test_the_threshold_is_inclusive():
    a = _confident("billing")
    t = a.confidence
    assert helpers.route_ticket("T1", a, t).outcome == helpers.ROUTED
    assert helpers.route_ticket("T1", a, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.route_ticket("T1", _confident("billing"), bad)


def test_the_state_hides_the_ticket_id():
    fields = {"ticket_id": "TKT-9", "subject": "Subject", "description": "Description."}
    assert helpers.build_state(fields) == {"subject": "Subject", "description": "Description."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)
