"""Tests for the template's helpers. A recipe's tests load its helpers like this."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


CLEAR = answer({"billing": 0.85, "bug": 0.05, "account": 0.05, "none": 0.05})
VAGUE = answer({"billing": 0.30, "bug": 0.28, "account": 0.22, "none": 0.20})
NOTHING = answer({"billing": 0.03, "bug": 0.03, "account": 0.04, "none": 0.90})


def test_confident_known_option_goes_to_its_queue():
    routing = helpers.route("T-1", CLEAR, 0.5)
    assert (routing.ticket, routing.outcome) == ("T-1", "billing-team")


def test_low_confidence_goes_to_review_whatever_the_option():
    assert helpers.route("T-1", VAGUE, 0.5).outcome == helpers.REVIEW


def test_none_goes_to_review_even_when_certain():
    assert NOTHING.confidence > 0.8
    assert helpers.route("T-1", NOTHING, 0.0).outcome == helpers.REVIEW


def test_an_option_that_is_not_a_queue_goes_to_review():
    odd = answer({"refund_everything": 0.9, "none": 0.1})
    routing = helpers.route("T-1", odd, 0.0)
    assert routing.outcome == helpers.REVIEW
    assert "queue" in routing.reason


def test_the_threshold_is_inclusive():
    assert helpers.route("T-1", CLEAR, CLEAR.confidence).outcome == "billing-team"
    assert helpers.route("T-1", CLEAR, CLEAR.confidence + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.route("T-1", CLEAR, bad)


def test_the_state_hides_the_ticket_reference():
    fields = {"ticket": "T-9", "subject": "Hello", "message": "Hi there."}
    assert helpers.build_state(fields) == {"subject": "Hello", "message": "Hi there."}


def test_the_options_come_from_the_queues():
    # Against literal expected values, not helpers.QUEUES itself: comparing against the
    # module's own data would still pass if QUEUES and the options it feeds drifted together
    # (for example, two entries swapped), which is exactly the drift this test exists to catch.
    options = list(helpers.build_questions()["route"].criteria)
    assert options == ["billing", "bug", "account", "none"]


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    """A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    caught every mistake, which would hide the exact lesson this fixture set exists to teach.
    Re-derive the threshold the way the notebook does (the lowest confidence at which every
    validation answer naming a queue is correct) and require a wrong `test` answer at or above
    it: a mistake the gate would still let through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["route"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    named = [
        (decide(e).confidence, decide(e).choice == labels[e.id])
        for e in validation
        if decide(e).choice in helpers.QUEUES
    ]
    threshold = min(c for c, _ in named if all(ok for c2, ok in named if c2 >= c))

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id for e in test if decide(e).choice != labels[e.id] and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
