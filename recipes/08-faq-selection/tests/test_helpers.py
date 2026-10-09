"""Tests for recipe 08's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

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

# Literal expected answer text, independent of helpers.ANSWERS: select_faq returns
# ANSWERS[answer.choice] directly, so comparing against that same dict would only ever check
# that the rule agrees with itself, never that the stored text is still what it should be.
EXPECTED_ANSWERS = {
    "password_reset": (
        "Open the sign-in page, select 'Forgot password', and follow the link we email you to "
        "set a new one. The link expires after 30 minutes."
    ),
    "change_email": (
        "Go to Account settings > Profile, enter the new email address, and confirm it from the "
        "verification link we send there."
    ),
    "cancel_subscription": (
        "Go to Account settings > Subscription > Cancel plan. Cancelling takes effect at the end "
        "of the current billing period; you keep access until then."
    ),
    "billing_cycle": (
        "Your plan renews every 30 days from the date you subscribed. The next charge date is "
        "shown on the Billing page under Account settings."
    ),
    "export_data": (
        "Go to Account settings > Data > Export, choose a format, and we will email a download "
        "link within 24 hours."
    ),
    "delete_account": (
        "Go to Account settings > Delete account, confirm by email, and the account and its data "
        "are permanently removed after a 14-day grace period."
    ),
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
        EXPECTED_ANSWERS[label],
    )


@pytest.mark.parametrize("label", REAL_FAQS)
def test_a_low_confidence_real_faq_goes_to_review_whatever_the_label(label):
    a = _low_confidence(label)
    assert a.choice == label
    assert a.confidence < 0.5
    result = helpers.select_faq("Q1", a, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.answer is None
    assert result.reason == "confidence below the threshold"


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


def test_stored_answers_are_not_all_right():
    """A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    caught every mistake, which would hide the exact lesson this fixture set exists to teach.
    Re-derive the threshold the way the notebook does (the lowest confidence at which every
    validation answer naming a real FAQ is correct) and require a wrong `test` answer at or
    above it: a mistake the gate would still let through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["faq"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    real_match = [
        (decide(e).choice == labels[e.id], decide(e).confidence)
        for e in validation
        if decide(e).choice != helpers.NO_MATCH
    ]
    threshold = select_confidence_threshold(
        [ok for ok, _ in real_match], [c for _, c in real_match], target_accuracy=1.0
    )

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id
        for e in test
        if decide(e).choice != helpers.NO_MATCH
        and decide(e).choice != labels[e.id]
        and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
