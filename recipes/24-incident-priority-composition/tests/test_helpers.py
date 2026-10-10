"""Tests for recipe 24's helpers. They load the helpers by file path."""

from itertools import product
from pathlib import Path

import pytest

from jev_cookbook import Provenance, ScoreAnswer, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_outcomes, select_confidence_threshold
from jev_cookbook.fixtures import (
    load_inputs,
    load_labels,
    responses_path,
    select_split,
    validate_recipe,
)
from jev_cookbook.simulation import ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
IMPACT_LEVELS = list(helpers.IMPACT_LEVELS)
URGENCY_LEVELS = list(helpers.URGENCY_LEVELS)


def impact_answer(probabilities):
    return ScoreAnswer.from_probabilities(probabilities, IMPACT_LEVELS, Provenance.synthetic())


def urgency_answer(probabilities):
    return ScoreAnswer.from_probabilities(probabilities, URGENCY_LEVELS, Provenance.synthetic())


CONFIDENT = {
    0: (0.85, 0.10, 0.03, 0.02),
    1: (0.08, 0.80, 0.08, 0.04),
    2: (0.04, 0.08, 0.80, 0.08),
    3: (0.02, 0.03, 0.10, 0.85),
}
# One low-confidence answer peaking at each of the four levels, spread close to even, so a rule
# that exempted one level from the confidence gate would still fail the parametrized test below.
LOW_CONFIDENCE = {
    0: (0.28, 0.26, 0.24, 0.22),
    1: (0.24, 0.28, 0.26, 0.22),
    2: (0.22, 0.24, 0.28, 0.26),
    3: (0.22, 0.24, 0.26, 0.28),
}


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["business_impact", "urgency"]
    impact = questions["business_impact"]
    urgency = questions["urgency"]
    assert list(impact.criteria) == list(helpers.IMPACT_LEVELS)
    assert list(urgency.criteria) == list(helpers.URGENCY_LEVELS)
    assert all(isinstance(level, str) and level for level in impact.criteria)
    assert all(isinstance(level, str) and level for level in urgency.criteria)
    assert isinstance(impact.instructions, str) and impact.instructions
    assert isinstance(urgency.instructions, str) and urgency.instructions
    # Independent questions (CONTRIBUTING.md section 3) share no option text: a reader who sees
    # only the criteria should not be able to confuse one rubric for the other.
    assert set(impact.criteria).isdisjoint(urgency.criteria)


def test_the_matrix_covers_every_cell_of_both_rubrics():
    assert set(helpers.PRIORITY_MATRIX) == set(
        product(helpers.IMPACT_CATEGORIES, helpers.URGENCY_CATEGORIES)
    )
    assert set(helpers.PRIORITY_MATRIX.values()) == {"P1", "P2", "P3", "P4"}


# (impact_category, urgency_category) -> priority, copied from the matrix for the test below to
# compare against, not read back from the dict it is testing.
EXPECTED_PRIORITY = {
    ("minor", "low"): "P4",
    ("minor", "medium"): "P4",
    ("minor", "high"): "P3",
    ("minor", "critical"): "P3",
    ("moderate", "low"): "P4",
    ("moderate", "medium"): "P3",
    ("moderate", "high"): "P3",
    ("moderate", "critical"): "P2",
    ("major", "low"): "P3",
    ("major", "medium"): "P3",
    ("major", "high"): "P2",
    ("major", "critical"): "P1",
    ("critical", "low"): "P3",
    ("critical", "medium"): "P2",
    ("critical", "high"): "P1",
    ("critical", "critical"): "P1",
}


@pytest.mark.parametrize(("impact_category", "urgency_category"), list(EXPECTED_PRIORITY))
def test_categorize_matches_every_cell_of_the_matrix_by_hand(impact_category, urgency_category):
    """A literal table, typed independently of helpers.PRIORITY_MATRIX, pinned per cell: a
    mutation to one entry of the matrix fails exactly the one test for that cell."""
    impact_level = helpers.IMPACT_CATEGORIES.index(impact_category)
    urgency_level = helpers.URGENCY_CATEGORIES.index(urgency_category)
    composition = helpers.categorize(
        impact_answer(CONFIDENT[impact_level]), urgency_answer(CONFIDENT[urgency_level])
    )
    assert (composition.impact_category, composition.urgency_category) == (
        impact_category,
        urgency_category,
    )
    assert composition.priority == EXPECTED_PRIORITY[(impact_category, urgency_category)]


def test_categorize_depends_on_both_inputs():
    """Changing either answer on its own changes the composition: the function is not secretly
    a function of only one of its two arguments."""
    base = helpers.categorize(impact_answer(CONFIDENT[0]), urgency_answer(CONFIDENT[0]))
    changed_impact = helpers.categorize(impact_answer(CONFIDENT[3]), urgency_answer(CONFIDENT[0]))
    changed_urgency = helpers.categorize(impact_answer(CONFIDENT[0]), urgency_answer(CONFIDENT[3]))
    assert changed_impact != base
    assert changed_urgency != base
    assert changed_impact != changed_urgency


def test_categorize_uses_the_modal_level_not_the_expected_score():
    """LOW_CONFIDENCE[0]'s modal level is 0, but its expected score is 1.40, which rounds to 1;
    LOW_CONFIDENCE[3]'s modal level is 3, but its expected score is 1.60, which rounds to 2. A
    categorize that read round(answer.score) instead of score_level(answer) would get both
    wrong -- confirmed locally by swapping the two calls in helpers.categorize for
    round(impact_answer.score) / round(urgency_answer.score): this test is the one that then
    fails, out of the whole suite."""
    composition = helpers.categorize(
        impact_answer(LOW_CONFIDENCE[0]), urgency_answer(LOW_CONFIDENCE[3])
    )
    assert (composition.impact_level, composition.urgency_level) == (0, 3)


def test_categorize_ties_go_to_the_lower_level():
    """helpers.categorize's own docstring and the notebook's "python-md" cell both promise
    score_level's tie-break ("ties going to the lower one"); an exact tie between two levels is
    what actually exercises that promise rather than merely citing it. Confirmed locally by
    patching score_level's tie-break to the higher level: this test is the one that fails."""
    tie = (0.0, 0.5, 0.5, 0.0)  # levels 1 and 2 exactly tied; the lower, 1, wins
    composition = helpers.categorize(impact_answer(tie), urgency_answer(CONFIDENT[0]))
    assert composition.impact_level == 1


def test_a_confident_ticket_at_or_above_the_gate_is_accepted():
    result = helpers.compose_priority(
        "T1", impact_answer(CONFIDENT[2]), urgency_answer(CONFIDENT[2]), 0.3
    )
    assert result.outcome == helpers.ACCEPTED
    assert result.composition.priority == "P2"
    assert result.reason == "priority matrix applied"


@pytest.mark.parametrize("weak_level", [0, 1, 2, 3])
def test_either_question_below_the_gate_sends_the_ticket_to_review(weak_level):
    """The gate is "either", not "both": a confident impact answer paired with an unconfident
    urgency answer (at every level) still goes to review, and so does the reverse."""
    weak = LOW_CONFIDENCE[weak_level]
    confident_impact_weak_urgency = helpers.compose_priority(
        "T1", impact_answer(CONFIDENT[2]), urgency_answer(weak), 0.5
    )
    weak_impact_confident_urgency = helpers.compose_priority(
        "T1", impact_answer(weak), urgency_answer(CONFIDENT[2]), 0.5
    )
    for result in (confident_impact_weak_urgency, weak_impact_confident_urgency):
        assert result.outcome == helpers.REVIEW
        assert result.reason == "confidence below the threshold"


def test_the_gate_is_inclusive():
    t = helpers.gate_confidence(impact_answer(CONFIDENT[2]), urgency_answer(CONFIDENT[2]))
    at = helpers.compose_priority(
        "T1", impact_answer(CONFIDENT[2]), urgency_answer(CONFIDENT[2]), t
    )
    above = helpers.compose_priority(
        "T1", impact_answer(CONFIDENT[2]), urgency_answer(CONFIDENT[2]), t + 1e-9
    )
    assert at.outcome == helpers.ACCEPTED
    assert above.outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_gate_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.compose_priority(
            "T1", impact_answer(CONFIDENT[2]), urgency_answer(CONFIDENT[2]), bad
        )


def test_gate_confidence_is_the_minimum_of_the_two_questions():
    weaker = helpers.gate_confidence(impact_answer(CONFIDENT[2]), urgency_answer(LOW_CONFIDENCE[1]))
    assert weaker == urgency_answer(LOW_CONFIDENCE[1]).confidence


def test_the_state_hides_the_ticket_id():
    fields = {"ticket_id": "INC-9999", "report": "auth-broker is down for everyone."}
    assert helpers.build_state(fields) == {"report": "auth-broker is down for everyone."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per ticket,
    # asking both questions together.
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    assert validate_recipe(RECIPE).mode == "replay"
    for example in examples:
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    """A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    caught every mistake, which would hide the exact lesson this fixture set exists to teach.
    Re-derive the threshold the way the notebook does (the lowest gate confidence at which
    every validation ticket's composed priority matches its gold priority) and require a wrong
    `test` ticket at or above it: a mistake the gate would still let through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        result = backend.decide(helpers.build_state(example.fields), questions)
        return result["business_impact"], result["urgency"]

    def gold_priority(example_id):
        label = labels[example_id]
        return helpers.PRIORITY_MATRIX[(label["impact"], label["urgency"])]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_decisions = {e.id: decide(e) for e in validation}
    val_correct = [
        helpers.categorize(*val_decisions[e.id]).priority == gold_priority(e.id) for e in validation
    ]
    val_confidence = [helpers.gate_confidence(*val_decisions[e.id]) for e in validation]
    threshold = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    test_decisions = {e.id: decide(e) for e in test}
    wrong_and_confident = [
        e.id
        for e in test
        if helpers.categorize(*test_decisions[e.id]).priority != gold_priority(e.id)
        and helpers.gate_confidence(*test_decisions[e.id]) >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test ticket"


def test_evaluate_outcomes_reports_a_nonzero_task_level_risk_on_test():
    """evaluate_outcomes is called on the rule's own outcomes (never reimplemented), and the
    fixture set is built so this is not vacuous: coverage, accuracy and risk are all strictly
    between 0 and 1 on test at the threshold the notebook actually freezes."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        result = backend.decide(helpers.build_state(example.fields), questions)
        return result["business_impact"], result["urgency"]

    def gold_priority(example_id):
        label = labels[example_id]
        return helpers.PRIORITY_MATRIX[(label["impact"], label["urgency"])]

    validation = select_split(examples, "validation")
    val_decisions = {e.id: decide(e) for e in validation}
    val_correct = [
        helpers.categorize(*val_decisions[e.id]).priority == gold_priority(e.id) for e in validation
    ]
    val_confidence = [helpers.gate_confidence(*val_decisions[e.id]) for e in validation]
    threshold = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)

    test = select_split(examples, "test")
    test_decisions = {e.id: decide(e) for e in test}
    results = [helpers.compose_priority(e.id, *test_decisions[e.id], threshold) for e in test]
    accepted = [r.outcome == helpers.ACCEPTED for r in results]
    correct = [
        helpers.categorize(*test_decisions[e.id]).priority == gold_priority(e.id) for e in test
    ]
    outcome = evaluate_outcomes(accepted, correct)
    assert 0.0 < outcome.coverage < 1.0
    assert 0.0 < outcome.accuracy < 1.0
    assert 0.0 < outcome.risk < 1.0


def test_the_review_queue_holds_every_review_outcome_from_both_splits_and_nothing_else():
    """The notebook submits every ``review`` outcome from `validation` and `test` into one
    `ReviewQueue` as it evaluates each split, and nothing else: no `demo` ticket (never scored,
    so never composed), no `accepted` ticket.

    The notebook and this test both build the queue through ``helpers.compose_split`` and
    ``helpers.submit_reviews`` -- the one place this recipe decides what happens to a ticket and
    the one place it turns a `review` outcome into a queued item -- so there is a single
    implementation to get right rather than two copies that could silently drift apart. The
    expected ids, their count, their order and the fact that both splits contributed are all
    written down below as literals, independent of the loop that builds the queue: a change that
    dropped the `validation` split, reversed the two splits, or let a `demo` ticket in would
    change what the queue holds without changing what this test expects, so it would fail.
    """
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        result = backend.decide(helpers.build_state(example.fields), questions)
        return result["business_impact"], result["urgency"]

    def gold_priority(example_id):
        label = labels[example_id]
        return helpers.PRIORITY_MATRIX[(label["impact"], label["urgency"])]

    validation = select_split(examples, "validation")
    val_decisions = {e.id: decide(e) for e in validation}
    val_correct = [
        helpers.categorize(*val_decisions[e.id]).priority == gold_priority(e.id) for e in validation
    ]
    val_confidence = [helpers.gate_confidence(*val_decisions[e.id]) for e in validation]
    threshold = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)

    test = select_split(examples, "test")
    test_decisions = {e.id: decide(e) for e in test}

    # Written independently of the submission below: the exact ids this fixture set's
    # `validation` and `test` splits send to review at the frozen threshold, in the order the
    # notebook submits them (validation, then test, each in fixture order).
    EXPECTED_REVIEWED_IDS = [
        "v17-one-confident",
        "v18-wrong",
        "v19-one-confident",
        "t09",
        "t17-one-confident",
        "t18-one-confident",
    ]

    queue = ReviewQueue()
    val_results = helpers.compose_split(validation, val_decisions, threshold)
    helpers.submit_reviews(queue, validation, val_decisions, val_results)
    test_results = helpers.compose_split(test, test_decisions, threshold)
    helpers.submit_reviews(queue, test, test_decisions, test_results)

    submitted_ids = [item["item"]["ticket_id"] for item in queue.to_dicts()]
    assert submitted_ids == EXPECTED_REVIEWED_IDS
    assert len(queue) == 6
    validation_ids = {e.id for e in validation}
    test_ids = {e.id for e in test}
    assert any(i in validation_ids for i in submitted_ids), "expected a reviewed validation ticket"
    assert any(i in test_ids for i in submitted_ids), "expected a reviewed test ticket"
    assert all(item["reason"] == "confidence below the threshold" for item in queue.to_dicts())
    demo_ids = {e.id for e in select_split(examples, "demo")}
    assert demo_ids.isdisjoint(submitted_ids)
