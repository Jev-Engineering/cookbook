"""Tests for recipe 23's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# Literal expected values, independent of helpers.OPTIONS/helpers.LABELS, so a test failure
# names exactly what changed instead of comparing the module against itself.
EXPECTED_OPTIONS = ("first", "second", "tie", "insufficient_evidence")
EXPECTED_LABELS = ("a", "b", "tie", "insufficient_evidence")


def test_the_options_are_the_four_positional_outcomes():
    options = list(helpers.build_questions()["verdict"].criteria)
    assert options == list(EXPECTED_OPTIONS)


def test_the_labels_are_a_b_tie_and_insufficient_evidence():
    assert helpers.LABELS == EXPECTED_LABELS


def test_build_questions_criteria_order_follows_the_options_tuple():
    # build_questions must actually depend on OPTIONS, not merely agree with it by coincidence:
    # reorder OPTIONS and the question's criteria order must reorder with it.
    assert list(helpers.build_questions()["verdict"].criteria) == list(helpers.OPTIONS)
    reordered = (helpers.TIE, helpers.INSUFFICIENT, helpers.FIRST, helpers.SECOND)
    original = helpers.OPTIONS
    try:
        helpers.OPTIONS = reordered
        assert list(helpers.build_questions()["verdict"].criteria) == list(reordered)
    finally:
        helpers.OPTIONS = original


# --------------------------------------------------------------------------- build_state


FIELDS = {
    "question": "Which is bigger?",
    "criterion": "Which answer gives a number?",
    "candidate_a": "Answer A text",
    "candidate_b": "Answer B text",
    "a_shown_first": True,
}


def test_build_state_shows_a_first_when_a_shown_first_is_true():
    state = helpers.build_state(FIELDS, swap=False)
    assert state == {
        "question": "Which is bigger?",
        "criterion": "Which answer gives a number?",
        "first_answer": "Answer A text",
        "second_answer": "Answer B text",
    }


def test_build_state_swap_puts_b_first_when_a_shown_first_is_true():
    state = helpers.build_state(FIELDS, swap=True)
    assert state == {
        "question": "Which is bigger?",
        "criterion": "Which answer gives a number?",
        "first_answer": "Answer B text",
        "second_answer": "Answer A text",
    }


def test_build_state_without_swap_is_the_default():
    assert helpers.build_state(FIELDS) == helpers.build_state(FIELDS, swap=False)


def test_build_state_hides_which_candidate_is_a_or_b():
    state = helpers.build_state(FIELDS)
    assert "a_shown_first" not in state
    assert set(state) == {"question", "criterion", "first_answer", "second_answer"}


def test_first_is_a_reads_a_shown_first_and_swap_flips_it():
    assert helpers.first_is_a(FIELDS, swap=False) is True
    assert helpers.first_is_a(FIELDS, swap=True) is False
    flipped = {**FIELDS, "a_shown_first": False}
    assert helpers.first_is_a(flipped, swap=False) is False
    assert helpers.first_is_a(flipped, swap=True) is True


# --------------------------------------------------------------------------- relabel


def test_relabel_first_is_a_when_a_is_first():
    assert helpers.relabel(helpers.FIRST, a_first=True) == "a"


def test_relabel_first_is_b_when_b_is_first():
    assert helpers.relabel(helpers.FIRST, a_first=False) == "b"


def test_relabel_second_is_b_when_a_is_first():
    assert helpers.relabel(helpers.SECOND, a_first=True) == "b"


def test_relabel_second_is_a_when_b_is_first():
    assert helpers.relabel(helpers.SECOND, a_first=False) == "a"


@pytest.mark.parametrize("a_first", [True, False])
def test_relabel_tie_and_insufficient_evidence_never_change(a_first):
    assert helpers.relabel(helpers.TIE, a_first) == helpers.TIE
    assert helpers.relabel(helpers.INSUFFICIENT, a_first) == helpers.INSUFFICIENT


# --------------------------------------------------------------------------- assign_first_shown


def test_assign_first_shown_is_deterministic():
    ids = [f"c{i:03d}" for i in range(200)]
    first = helpers.assign_first_shown(ids, seed=23)
    second = helpers.assign_first_shown(ids, seed=23)
    assert first == second


def test_assign_first_shown_depends_on_the_seed():
    ids = [f"c{i:03d}" for i in range(200)]
    assert helpers.assign_first_shown(ids, seed=1) != helpers.assign_first_shown(ids, seed=2)


def test_assign_first_shown_is_roughly_balanced():
    # Not a claim of exact balance: a seeded coin flip over 200 ids should land nowhere near
    # all-one-way. This guards against an assignment that is secretly constant or patterned.
    ids = [f"c{i:03d}" for i in range(200)]
    assignment = helpers.assign_first_shown(ids)
    share_a_first = sum(assignment.values()) / len(assignment)
    assert 0.35 < share_a_first < 0.65


def test_assign_first_shown_looks_only_at_ids():
    # Decided by assign_first_shown alone from the id string: nothing about a gold label or
    # candidate text can reach it, because it is never passed any.
    ids = ["x1", "x2", "x3"]
    assert helpers.assign_first_shown(ids) == helpers.assign_first_shown(list(ids))


def test_assign_first_shown_does_not_depend_on_an_ids_position_in_the_list():
    # Each id's bit comes from hashing the id alone, not its position: shuffling the list, or
    # dropping unrelated ids, must never change the bit any id already had. A sequential
    # random-number stream (one rng.random() call per id, in list order) would fail this,
    # because then an id's bit would depend on how many ids came before it.
    ids = [f"c{i:03d}" for i in range(50)]
    whole = helpers.assign_first_shown(ids)
    shuffled = helpers.assign_first_shown(list(reversed(ids)))
    assert whole == shuffled
    subset = helpers.assign_first_shown(ids[::2])
    assert all(subset[i] == whole[i] for i in subset)


# --------------------------------------------------------------------------- read_verdict_answer


class _StubAnswer:
    def __init__(self, choice, confidence):
        self.choice = choice
        self.confidence = confidence


def test_read_verdict_answer_relabels_and_passes_confidence_through():
    answer = _StubAnswer(helpers.SECOND, 0.77)
    label, confidence = helpers.read_verdict_answer(answer, FIELDS, swap=False)
    assert (label, confidence) == ("b", 0.77)  # a is first, so "second" means b
    label, confidence = helpers.read_verdict_answer(answer, FIELDS, swap=True)
    assert (label, confidence) == ("a", 0.77)  # swapped: b is first, so "second" means a


# --------------------------------------------------------------------------- judge_pair


def test_consistent_confident_a_is_accepted():
    v = helpers.judge_pair("c1", "a", 0.9, "a", 0.85, min_confidence=0.5)
    assert (v.label, v.outcome) == ("a", helpers.ACCEPTED)


def test_consistent_confident_b_is_accepted():
    v = helpers.judge_pair("c1", "b", 0.9, "b", 0.85, min_confidence=0.5)
    assert (v.label, v.outcome) == ("b", helpers.ACCEPTED)


def test_consistent_confident_tie_is_accepted():
    v = helpers.judge_pair("c1", "tie", 0.9, "tie", 0.85, min_confidence=0.5)
    assert (v.label, v.outcome) == ("tie", helpers.ACCEPTED)


def test_consistent_insufficient_evidence_is_accepted_even_at_low_confidence():
    v = helpers.judge_pair(
        "c1", "insufficient_evidence", 0.0, "insufficient_evidence", 0.0, min_confidence=0.99
    )
    assert (v.label, v.outcome) == ("insufficient_evidence", helpers.ACCEPTED)
    assert v.reason == "insufficient evidence, agreed by both orders"


@pytest.mark.parametrize("label", ["a", "b", "tie"])
def test_low_confidence_goes_to_review_whatever_the_label(label):
    v = helpers.judge_pair("c1", label, 0.2, label, 0.3, min_confidence=0.5)
    assert v.outcome == helpers.REVIEW
    assert v.label is None
    assert v.reason == "confidence below the threshold"


@pytest.mark.parametrize(
    "label1,label2",
    [("a", "b"), ("b", "a"), ("a", "tie"), ("tie", "a"), ("insufficient_evidence", "b")],
)
def test_orders_disagree_goes_to_review_whatever_either_confidence_is(label1, label2):
    v = helpers.judge_pair("c1", label1, 0.99, label2, 0.99, min_confidence=0.0)
    assert v.outcome == helpers.REVIEW
    assert v.label is None
    assert v.reason == "orders disagree"


def test_orders_disagree_is_checked_before_the_confidence_gate():
    # Both confidences are 0.0, well below any sane threshold, and the labels disagree: the
    # reason must still name the disagreement, not the confidence, because disagreement is
    # checked first.
    v = helpers.judge_pair("c1", "a", 0.0, "b", 0.0, min_confidence=0.5)
    assert v.reason == "orders disagree"


def test_the_gate_uses_the_lower_of_the_two_confidences():
    v = helpers.judge_pair("c1", "a", 0.95, "a", 0.40, min_confidence=0.5)
    assert v.outcome == helpers.REVIEW
    assert v.reason == "confidence below the threshold"


def test_the_threshold_is_inclusive():
    accepted = helpers.judge_pair("c1", "a", 0.5, "a", 0.5, min_confidence=0.5)
    assert accepted.outcome == helpers.ACCEPTED
    rejected = helpers.judge_pair("c1", "a", 0.5, "a", 0.5 - 1e-9, min_confidence=0.5)
    assert rejected.outcome == helpers.REVIEW


def test_an_accepted_verdict_names_the_consistent_and_confident_reason():
    v = helpers.judge_pair("c1", "a", 0.9, "a", 0.85, min_confidence=0.5)
    assert v.reason == "orders agree and confidence clears the threshold"


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.judge_pair("c1", "a", 0.9, "a", 0.9, min_confidence=bad)


# --------------------------------------------------------------------------- fixtures


def test_every_example_lists_two_replay_keys_in_request_order():
    # This recipe makes two requests per comparison (the candidates, then the same two with the
    # order swapped), so every example's replay_keys has exactly two entries, in that order
    # (docs/fixtures.md: "More than one when a later request depends on an earlier answer, in
    # the order the notebook makes the requests").
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        expected = (
            replay_key(helpers.build_state(example.fields, swap=False), questions),
            replay_key(helpers.build_state(example.fields, swap=True), questions),
        )
        assert example.replay_keys == expected


def test_stored_answers_are_not_all_right():
    # Mirrors the notebook's own threshold-selection and rule application exactly, so this test
    # fails the moment either of two different gaps reopens. These are two separate assertions,
    # not one disjunction, because judge_pair reaches them through two different branches and a
    # single combined check would still pass if either fixture alone were removed: t04-shaped
    # mistakes go through the confidence gate (the gate's whole job is to catch most of them,
    # but not this one); t20-shaped mistakes never reach the gate at all, because an agreed
    # insufficient_evidence is accepted unconditionally, so "clearing the gate" is not even the
    # right question to ask about it.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    inputs = {e.id: e for e in load_inputs(RECIPE)}
    labels = load_labels(RECIPE)

    def both_orders(example):
        a1 = backend.decide(helpers.build_state(example.fields, swap=False), questions)["verdict"]
        a2 = backend.decide(helpers.build_state(example.fields, swap=True), questions)["verdict"]
        label1, conf1 = helpers.read_verdict_answer(a1, example.fields, swap=False)
        label2, conf2 = helpers.read_verdict_answer(a2, example.fields, swap=True)
        return label1, conf1, label2, conf2

    val = [e for e in inputs.values() if e.split == "validation"]
    test = [e for e in inputs.values() if e.split == "test"]
    pairs = {e.id: both_orders(e) for e in val + test}

    eligible = [
        (pairs[e.id][0] == labels[e.id], min(pairs[e.id][1], pairs[e.id][3]))
        for e in val
        if pairs[e.id][0] == pairs[e.id][2] and pairs[e.id][0] != helpers.INSUFFICIENT
    ]
    threshold = select_confidence_threshold(
        [ok for ok, _ in eligible], [c for _, c in eligible], target_accuracy=1.0
    )

    # t04-shaped: both orders agree on a/b/tie, the gate is cleared, gold disagrees.
    wrong_but_gated_accept = [
        e.id
        for e in test
        if pairs[e.id][0] == pairs[e.id][2]
        and pairs[e.id][0] != helpers.INSUFFICIENT
        and min(pairs[e.id][1], pairs[e.id][3]) >= threshold
        and pairs[e.id][0] != labels[e.id]
    ]
    assert wrong_but_gated_accept, (
        "test should contain a comparison whose two orders agree on a/b/tie, clear the "
        "validation-chosen confidence gate, and still disagree with gold"
    )

    # t20-shaped: both orders agree on insufficient_evidence (exempt from the gate entirely),
    # but gold is some other, judgeable label.
    wrong_insufficient_evidence = [
        e.id
        for e in test
        if pairs[e.id][0] == pairs[e.id][2] == helpers.INSUFFICIENT
        and labels[e.id] != helpers.INSUFFICIENT
    ]
    assert wrong_insufficient_evidence, (
        "test should contain a comparison whose two orders agree on insufficient_evidence "
        "while gold is some other, judgeable label"
    )
