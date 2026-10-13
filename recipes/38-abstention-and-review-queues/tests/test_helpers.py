"""Tests for recipe 38's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

EXPECTED_OPTIONS = [
    "self_serve",
    "tier1_support",
    "tier2_engineering",
    "insufficient_information",
]


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def _confident(label):
    """A clearly confident answer for ``label``, with the rest of the mass spread evenly."""
    others = [o for o in helpers.OPTIONS if o != label]
    rest = (1.0 - 0.9) / len(others)
    return answer({label: 0.9, **{o: rest for o in others}})


def _low_confidence(label):
    """A low-confidence answer for ``label``: barely ahead of the other three options."""
    others = [o for o in helpers.OPTIONS if o != label]
    rest = (1.0 - 0.27) / len(others)
    return answer({label: 0.27, **{o: rest for o in others}})


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["queue"]
    queue = questions["queue"]
    assert list(queue.criteria) == EXPECTED_OPTIONS
    assert all(isinstance(d, str) and d for d in queue.criteria.values())
    assert isinstance(queue.instructions, str) and queue.instructions


@pytest.mark.parametrize("label", ["self_serve", "tier1_support", "tier2_engineering"])
def test_a_confident_real_queue_is_answered_whatever_the_label(label):
    a = _confident(label)
    result = helpers.route_ticket("T1", a, 0.3)
    assert (result.ticket_id, result.label, result.outcome) == ("T1", label, helpers.ANSWERED)
    assert result.reason == "confident match"


@pytest.mark.parametrize("label", ["self_serve", "tier1_support", "tier2_engineering"])
def test_a_low_confidence_real_queue_goes_to_review_whatever_the_label(label):
    a = _low_confidence(label)
    assert a.choice == label
    result = helpers.route_ticket("T1", a, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.label == label
    assert result.reason == "confidence below the threshold"


@pytest.mark.parametrize("top_probability", [0.95, 0.30])
def test_insufficient_information_is_never_answered_whatever_its_confidence(top_probability):
    # top_probability=0.30 keeps insufficient_information as the top option (ahead of an even
    # third of the rest, 0.2333) while landing a low confidence, (0.30 - 0.25) / 0.75 = 0.0667:
    # a mutation that only checked low confidence would miss the 0.95 case, and one that only
    # checked high confidence would miss this one -- checking both ends is what proves the
    # branch is unconditional, not merely usually taken.
    others = [o for o in helpers.OPTIONS if o != helpers.INSUFFICIENT_INFORMATION]
    rest = (1.0 - top_probability) / len(others)
    a = answer({helpers.INSUFFICIENT_INFORMATION: top_probability, **{o: rest for o in others}})
    assert a.choice == helpers.INSUFFICIENT_INFORMATION
    result = helpers.route_ticket("T1", a, 0.0)  # a threshold of 0.0 would pass any confidence
    assert result.outcome == helpers.REVIEW
    assert result.label == helpers.INSUFFICIENT_INFORMATION
    assert result.reason == "not enough information to classify"


def test_the_threshold_is_inclusive():
    a = _confident("self_serve")
    t = a.confidence
    assert helpers.route_ticket("T1", a, t).outcome == helpers.ANSWERED
    assert helpers.route_ticket("T1", a, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.route_ticket("T1", _confident("self_serve"), bad)


def test_the_state_hides_the_ticket_id():
    fields = {"ticket_id": "TKT-9", "subject": "Subject", "description": "Description."}
    assert helpers.build_state(fields) == {"subject": "Subject", "description": "Description."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# The top choice each committed row is meant to store, written once by hand here, independent
# of build_fixtures.py: a fixture-building shorthand must never default the label-bearing
# field (CONTRIBUTING's generator rule -- recipe 30's "bare float" shorthand once defaulted the
# top choice to the positive label for every row, silently mislabelling the stored answers of
# rows whose gold was the negative label). This recipe's ``answers_for`` always takes a full,
# explicit probability tuple rather than such a shorthand, so there is no default to drift --
# but checking the stored answer against ``build_fixtures.ROWS`` itself would not catch a
# *future* shorthand doing exactly that, because the bug and the check would then read from the
# same place and agree by construction. Keeping this table by hand, separate from
# build_fixtures.py, is what makes it an independent check rather than a round trip: it is
# whatever the row's own description says the model should think, not whatever the generator
# code currently computes. Note several rows are deliberately wrong relative to their own gold
# label (v08/t08, t16) -- this table still names the row's intended top choice, not its gold.
EXPECTED_TOP_CHOICE = {
    "v01-ss-reset-password": "self_serve",
    "v02-ss-billing-cycle": "self_serve",
    "v03-ambiguous-ss-tier1": "tier1_support",
    "v04-tier1-add-teammate": "tier1_support",
    "v05-tier1-refund-seats": "tier1_support",
    "v06-tier2-export-spins": "tier2_engineering",
    "v07-tier2-totals-mismatch": "tier2_engineering",
    "v08-ambiguous-tier1-tier2": "tier1_support",
    "v09-ss-permissions-explained": "self_serve",
    "v10-ss-invoice-pdf": "self_serve",
    "v11-insufficient-vague": "insufficient_information",
    "v12-insufficient-offtopic": "insufficient_information",
    "v13-insufficient-mixed": "insufficient_information",
    "v14-tier1-resend-receipt": "tier1_support",
    "v15-tier2-search-empty": "tier2_engineering",
    "v16-ss-trial-length": "self_serve",
    "v17-tier1-add-billing-contact": "tier1_support",
    "v18-tier1-vague-refund-lowconf": "tier1_support",
    "v19-ambiguous-ss-tier1-device": "self_serve",
    "v20-tier2-crash-on-open": "tier2_engineering",
    "t01-ss-reset-password": "self_serve",
    "t02-ss-plan-limits": "self_serve",
    "t03-ambiguous-ss-tier1": "tier1_support",
    "t04-tier1-add-admin": "tier1_support",
    "t05-tier1-refund-duplicate-seat": "tier1_support",
    "t06-tier2-export-blank-pdf": "tier2_engineering",
    "t07-tier2-totals-mismatch": "tier2_engineering",
    "t08-ambiguous-tier1-tier2": "tier1_support",
    "t09-ss-saved-views": "self_serve",
    "t10-ss-export-csv-howto": "self_serve",
    "t11-insufficient-vague": "insufficient_information",
    "t12-insufficient-offtopic": "insufficient_information",
    "t13-insufficient-mixed": "insufficient_information",
    "t14-tier1-resend-receipt": "tier1_support",
    "t15-tier2-search-wrong-workspace": "tier2_engineering",
    "t16-ss-trial-length-lowconf-wrong": "tier1_support",
    "t17-tier1-change-billing-contact": "tier1_support",
    "t18-tier1-vague-refund-lowconf": "tier1_support",
    "t19-ambiguous-ss-tier1-device": "self_serve",
    "t20-tier2-crash-on-open": "tier2_engineering",
    "d01-ambiguous-ss-tier1": "tier1_support",
    "d02-insufficient-vague": "insufficient_information",
}


def test_every_stored_answers_top_choice_matches_its_spec():
    """For every committed example, the stored answer's top choice is exactly the option
    ``EXPECTED_TOP_CHOICE`` names for it -- a table kept by hand, not derived from
    ``build_fixtures.py``, so a future generator bug that silently defaults the top choice (the
    shorthand this rule exists to rule out) cannot pass by agreeing with its own mistake. This
    covers every example in the fixtures, ``demo`` included, and is independent of whether the
    stored choice matches the row's *gold* label: several rows are deliberately wrong on
    purpose (v08, t08, t16), and this test still requires their stored answer to be the
    specific wrong choice intended, not merely *a* choice."""
    examples = load_inputs(RECIPE)
    assert {e.id for e in examples} == set(EXPECTED_TOP_CHOICE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    for example in examples:
        stored = backend.decide(helpers.build_state(example.fields), questions)["queue"]
        expected = EXPECTED_TOP_CHOICE[example.id]
        assert stored.choice == expected, (
            f"{example.id}: stored answer names {stored.choice!r}, expected {expected!r}"
        )


def test_route_ticket_disagrees_with_a_naive_confidence_only_view_on_a_confident_fallback():
    """``route_ticket``'s ``insufficient_information`` branch is unconditional, not
    confidence-gated: a view that only ever checks ``confidence >= threshold`` cannot see it,
    and would misclassify a confident ``insufficient_information`` answer as answered. This is
    exactly the "outcomes versus confidence-only view" distinction docs/evaluation.md names
    (``evaluate_outcomes`` vs. ``evaluate_selective``), proved here against a real committed
    fixture rather than argued in prose: a threshold of 0.1 would pass this answer's confidence
    comfortably, and the rule still sends it to review."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    example = next(e for e in examples if e.id == "t12-insufficient-offtopic")
    assert labels[example.id] == helpers.INSUFFICIENT_INFORMATION
    answer_ = backend.decide(helpers.build_state(example.fields), questions)["queue"]
    assert answer_.choice == helpers.INSUFFICIENT_INFORMATION
    assert answer_.confidence >= 0.1
    routing = helpers.route_ticket(example.id, answer_, min_confidence=0.1)
    assert routing.outcome == helpers.REVIEW
    assert routing.reason == "not enough information to classify"


def test_stored_answers_are_not_all_right():
    """A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    caught every mistake, which would hide the exact lesson this fixture set exists to teach.
    Re-derive the threshold the way the notebook does -- ``min_coverage=0.75`` over the
    validation answers that name a real queue (``helpers.REAL_QUEUES``; an answer of
    ``insufficient_information`` is never a candidate for the gate, so it cannot set the bar) --
    and require a wrong ``test`` answer at or above it: a mistake the gate would still let
    through. This re-derivation is deliberately local to this function rather than routed
    through a shared selection helper: its purpose is an independent check of the notebook's own
    selection, and calling the same helper the notebook calls would make the two agree by
    construction rather than by checking anything."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["queue"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: decide(e) for e in validation}
    named = [e for e in validation if val_answers[e.id].choice in helpers.REAL_QUEUES]
    correct = [val_answers[e.id].choice == labels[e.id] for e in named]
    confidence = [val_answers[e.id].confidence for e in named]
    threshold = select_confidence_threshold(correct, confidence, min_coverage=0.75)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    test_answers = {e.id: decide(e) for e in test}
    wrong_and_confident = [
        e.id
        for e in test
        if test_answers[e.id].choice != labels[e.id] and test_answers[e.id].confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"


def test_validation_accuracy_of_the_raw_choice_is_not_perfect():
    """The notebook's "Python's part" section gives a reason for preferring ``min_coverage``
    over ``target_accuracy=1.0``: that a perfect-accuracy target is not guaranteed to hold by
    construction here, because the raw choice is not perfect on ``validation`` either. That is
    a property of the fixture pool, not a number the notebook merely prints, so a future edit to
    the validation fixtures could silently make it false while every other check stays green.
    Pinning it here is what keeps that specific prose claim honest."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    correct = [
        backend.decide(helpers.build_state(e.fields), questions)["queue"].choice == labels[e.id]
        for e in validation
    ]
    assert not all(correct), "expected at least one wrong validation answer"


def test_t08_and_t16_are_the_deliberately_wrong_test_examples_the_notebook_names():
    """The notebook's evaluation cells name two specific test tickets by id:
    ``t08-ambiguous-tier1-tier2`` as wrong and confident (so the gate lets it through, which is
    where the reported task-level risk comes from) and
    ``t16-ss-trial-length-lowconf-wrong`` as wrong but low-confidence (so the gate catches it).
    Both are properties of the fixture pool a future edit could silently break while every other
    check stays green (the aggregate "some confidently wrong answer exists" guard above would
    still pass as long as *some* example took over the role, even a different one from the pair
    the notebook's prose names) -- so this test pins the two specific ids and the specific
    confidence/threshold relationship the prose relies on, independent of the notebook's own
    frozen threshold value."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(ident):
        example = next(e for e in examples if e.id == ident)
        return backend.decide(helpers.build_state(example.fields), questions)["queue"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: decide(e.id) for e in validation}
    named = [e for e in validation if val_answers[e.id].choice in helpers.REAL_QUEUES]
    correct = [val_answers[e.id].choice == labels[e.id] for e in named]
    confidence = [val_answers[e.id].confidence for e in named]
    threshold = select_confidence_threshold(correct, confidence, min_coverage=0.75)

    confident_wrong = decide("t08-ambiguous-tier1-tier2")
    low_confidence_wrong = decide("t16-ss-trial-length-lowconf-wrong")
    assert confident_wrong.choice != labels["t08-ambiguous-tier1-tier2"]
    assert confident_wrong.confidence >= threshold
    assert low_confidence_wrong.choice != labels["t16-ss-trial-length-lowconf-wrong"]
    assert low_confidence_wrong.confidence < threshold
