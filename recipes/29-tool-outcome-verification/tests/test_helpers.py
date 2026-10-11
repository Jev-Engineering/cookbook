"""Tests for recipe 29's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer_for(choice: str, p_max: float = 0.9):
    """A synthetic Choice answer naming ``choice`` at top probability ``p_max``, the rest of
    the mass split evenly over the other three outcomes."""
    rest = (1.0 - p_max) / 3.0
    probabilities = {name: (p_max if name == choice else rest) for name in helpers.OUTCOMES}
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def test_the_options_come_from_outcomes():
    # Against a literal expected value, not helpers.OUTCOMES itself: comparing against the
    # module's own data would still pass if OUTCOMES and the options it feeds drifted together.
    options = list(helpers.build_questions()["outcome"].criteria)
    assert options == ["unverifiable", "failed", "partial", "complete"]


@pytest.mark.parametrize("outcome", helpers.OUTCOMES)
def test_low_confidence_goes_to_review_whatever_the_outcome(outcome):
    actions, queue = ActionLog(), ReviewQueue()
    result = helpers.classify("c1", answer_for(outcome, 0.4), 0.5, actions=actions, queue=queue)
    assert result.outcome == helpers.REVIEW
    assert result.action is None
    assert result.reason == "confidence below the threshold"
    assert len(actions) == 0
    assert len(queue) == 1


def test_confident_complete_is_an_accepted_handoff():
    actions, queue = ActionLog(), ReviewQueue()
    result = helpers.classify("c1", answer_for(helpers.COMPLETE), 0.5, actions=actions, queue=queue)
    assert (result.outcome, result.action) == (helpers.COMPLETE, "handoff accepted")
    assert len(actions) == 1
    assert len(queue) == 0
    assert actions.to_dicts()[0]["kind"] == "handoff accepted"


@pytest.mark.parametrize("outcome", [helpers.PARTIAL, helpers.FAILED])
def test_confident_partial_or_failed_schedules_a_retry_naming_which(outcome):
    actions, queue = ActionLog(), ReviewQueue()
    result = helpers.classify("c1", answer_for(outcome), 0.5, actions=actions, queue=queue)
    assert (result.outcome, result.action) == (outcome, "retry scheduled")
    assert len(actions) == 1
    assert len(queue) == 0
    entry = actions.to_dicts()[0]
    assert entry["kind"] == "retry scheduled"
    assert entry["payload"]["reason"] == result.reason
    assert (
        outcome in result.reason or "not done" in result.reason or "not fulfilled" in result.reason
    )


def test_confident_unverifiable_is_a_review_not_an_action():
    actions, queue = ActionLog(), ReviewQueue()
    result = helpers.classify(
        "c1", answer_for(helpers.UNVERIFIABLE), 0.5, actions=actions, queue=queue
    )
    assert result.outcome == helpers.UNVERIFIABLE
    assert result.action is None
    assert result.reason == "evidence does not establish the outcome"
    assert len(actions) == 0
    assert len(queue) == 1
    assert queue.to_dicts()[0]["reason"] == "evidence does not establish the outcome"


def test_the_threshold_is_inclusive():
    a = answer_for(helpers.COMPLETE, 0.7)
    assert helpers.classify(
        "c1", a, a.confidence, actions=ActionLog(), queue=ReviewQueue()
    ).outcome == (helpers.COMPLETE)
    just_below = helpers.classify(
        "c1", a, a.confidence + 1e-9, actions=ActionLog(), queue=ReviewQueue()
    )
    assert just_below.outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify(
            "c1", answer_for(helpers.COMPLETE), bad, actions=ActionLog(), queue=ReviewQueue()
        )


def test_the_state_hides_the_call_id():
    fields = {
        "call_id": "call-42",
        "request": "Do the thing.",
        "tool": "a_tool",
        "reported_status": "success",
        "exit_code": 0,
        "stdout_excerpt": "done",
        "stderr_excerpt": "",
        "artifacts": [],
    }
    state = helpers.build_state(fields)
    assert set(state) == {"request", "evidence"}
    assert "call-42" not in state["request"]
    assert "call-42" not in state["evidence"]


def test_accepted_and_correct_marks_review_and_unverifiable_as_not_accepted():
    actions, queue = ActionLog(), ReviewQueue()
    outcomes = [
        helpers.classify("c1", answer_for(helpers.COMPLETE), 0.5, actions=actions, queue=queue),
        helpers.classify("c2", answer_for(helpers.PARTIAL), 0.5, actions=actions, queue=queue),
        helpers.classify("c3", answer_for(helpers.FAILED), 0.5, actions=actions, queue=queue),
        helpers.classify("c4", answer_for(helpers.UNVERIFIABLE), 0.5, actions=actions, queue=queue),
        helpers.classify(
            "c5", answer_for(helpers.COMPLETE, 0.4), 0.5, actions=actions, queue=queue
        ),
    ]
    gold = {
        "c1": helpers.COMPLETE,
        "c2": helpers.PARTIAL,
        "c3": helpers.COMPLETE,
        "c4": helpers.FAILED,
        "c5": helpers.COMPLETE,
    }
    accepted, correct = helpers.accepted_and_correct(outcomes, gold)
    assert accepted == [True, True, True, False, False]
    assert correct == [True, True, False, False, False]


def test_next_step_agreement_reads_the_gold_label_not_the_answer():
    actions, queue = ActionLog(), ReviewQueue()
    # c1: gold partial, answered failed -- different raw labels, same next step (both retry).
    # c2: gold complete, gated to review for low confidence -- next step disagrees with gold.
    outcomes = [
        helpers.classify("c1", answer_for(helpers.FAILED), 0.5, actions=actions, queue=queue),
        helpers.classify(
            "c2", answer_for(helpers.COMPLETE, 0.3), 0.5, actions=actions, queue=queue
        ),
    ]
    gold = {"c1": helpers.PARTIAL, "c2": helpers.COMPLETE}
    assert helpers.actual_next_step(outcomes[0]) == "retry scheduled"
    assert helpers.actual_next_step(outcomes[1]) == helpers.REVIEW
    assert helpers.next_step_agreement(outcomes, gold) == 0.5


def test_next_step_agreement_rejects_empty_input():
    with pytest.raises(ValueError, match="empty"):
        helpers.next_step_agreement([], {})


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("success", "complete"),
        ("failure", "failed"),
        ("partial_success", "partial"),
        ("in_progress", "unverifiable"),
        ("unknown", "unverifiable"),
    ],
)
def test_self_report_baseline_trusts_the_reported_status_literally(status, expected):
    assert helpers.self_report_baseline(status) == expected


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if a confidence gate
    # caught every mistake. Re-derive the threshold the way the notebook does (the lowest
    # confidence at which every validation answer is right) and require a wrong `test` answer
    # at or above it: a mistake the gate would still let through.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["outcome"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: decide(e) for e in validation}
    correct = [val_answers[e.id].choice == labels[e.id] for e in validation]
    confidence = [val_answers[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id for e in test if decide(e).choice != labels[e.id] and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
