"""Tests for recipe 02's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import NoulAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(noul):
    return NoulAnswer(noul, Provenance.synthetic())


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["refund_requested"]
    proposition = questions["refund_requested"]
    assert proposition.instructions == helpers.STATEMENT
    assert set(proposition.criteria) == {"true", "false"}
    assert all(isinstance(d, str) and d for d in proposition.criteria.values())


@pytest.mark.parametrize("noul", [0.80, 0.85, 0.93, 1.0])
def test_a_message_at_or_above_the_threshold_is_flagged(noul):
    result = helpers.route("RF1", answer(noul), 0.80)
    assert (result.ticket_id, result.flagged, result.outcome) == (
        "RF1",
        True,
        helpers.FLAGGED,
    )


@pytest.mark.parametrize("noul", [0.0, 0.20, 0.50, 0.79])
def test_a_message_below_the_threshold_is_not_flagged(noul):
    result = helpers.route("RF1", answer(noul), 0.80)
    assert (result.ticket_id, result.flagged, result.outcome) == (
        "RF1",
        False,
        helpers.NOT_FLAGGED,
    )


def test_the_threshold_is_inclusive():
    assert helpers.route("RF1", answer(0.80), 0.80).flagged is True
    assert helpers.route("RF1", answer(0.80 - 1e-9), 0.80).flagged is False


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.route("RF1", answer(0.5), bad)


def test_the_state_hides_the_ticket_id():
    fields = {"ticket_id": "RF9", "text": "Please refund my order."}
    assert helpers.build_state(fields) == {"text": "Please refund my order."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)
