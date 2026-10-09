"""Tests for recipe 16's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# The gate recipe 16's notebook chooses over all of validation and freezes before test (see
# notebook.ipynb, "Python's part"): the lowest confidence whose answered subset -- every
# category, allowed included -- is perfectly accurate. It happens to be the same value as the
# recipe's first fix round (0.7600 printed; "v03-trigger-word" and "v13-violating-harass" both
# carry it exactly), not by coincidence but because validation's "allowed" examples were raised
# above it precisely so that re-selecting the gate over every category, not just the two flagged
# ones, would not quietly lower it. Written here as a literal, to the precision
# select_confidence_threshold actually returns it, so a change to this rule's behaviour, not
# merely to the fixtures, is what the frozen-gate tests below are pinned against.
FROZEN_GATE = 0.7599999999999998

ALL_CATEGORIES = [helpers.ALLOWED, helpers.REVIEW_NEEDED, helpers.POTENTIALLY_VIOLATING]


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def _confident(label):
    """A clearly confident answer for ``label``, with the rest of the mass spread evenly."""
    others = [o for o in helpers.OPTIONS if o != label]
    rest = (1.0 - 0.9) / len(others)
    return answer({label: 0.9, **{o: rest for o in others}})


def _low_confidence(label):
    """A low-confidence answer for ``label``: barely ahead of the other two options."""
    others = [o for o in helpers.OPTIONS if o != label]
    rest = (1.0 - 0.36) / len(others)
    return answer({label: 0.36, **{o: rest for o in others}})


_EXPECTED_ACTION = {
    helpers.ALLOWED: helpers.IGNORE,
    helpers.REVIEW_NEEDED: helpers.WARN,
    helpers.POTENTIALLY_VIOLATING: helpers.HIDE,
}


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["triage"]
    triage = questions["triage"]
    assert list(triage.criteria) == ["review_needed", "potentially_violating", "allowed"]
    assert all(isinstance(d, str) and d for d in triage.criteria.values())
    assert isinstance(triage.instructions, str) and triage.instructions


@pytest.mark.parametrize("label", ALL_CATEGORIES)
def test_a_confident_category_acts_whatever_the_label(label):
    # The standard three-path pattern: every category, allowed included, is gated the same way.
    result = helpers.moderate("M1", _confident(label), 0.5)
    assert (result.label, result.action) == (label, _EXPECTED_ACTION[label])


@pytest.mark.parametrize("label", ALL_CATEGORIES)
def test_a_low_confidence_category_is_escalated_whatever_the_label(label):
    a = _low_confidence(label)
    assert a.choice == label
    result = helpers.moderate("M1", a, 0.9)
    assert result.action == helpers.ESCALATE
    assert result.reason == "confidence below the threshold"


def test_an_option_outside_the_fixed_set_is_escalated():
    # The defensive membership branch: the backend already rejects a foreign option, but the
    # rule does not trust that alone (CONTRIBUTING.md section 3: options are a fixed, supplied
    # set). ``from_probabilities`` accepts any option names and computes choice/confidence from
    # them, so an answer naming an option outside this recipe's three is still easy to build.
    # The membership check runs before the confidence gate, so a very high confidence does not
    # help a foreign option either.
    odd = ChoiceAnswer.from_probabilities({"mystery": 0.9, "allowed": 0.1}, Provenance.synthetic())
    result = helpers.moderate("M1", odd, 0.0)
    assert result.action == helpers.ESCALATE
    assert result.reason == "not one of the fixed categories"


def test_the_gate_is_inclusive():
    a = _confident(helpers.POTENTIALLY_VIOLATING)
    t = a.confidence
    assert helpers.moderate("M1", a, t).action == helpers.HIDE
    assert helpers.moderate("M1", a, t + 1e-9).action == helpers.ESCALATE


def test_the_gate_applies_to_allowed_too():
    # The central claim this recipe makes after its first review round: allowed is not exempt.
    # A confident allowed answer is accepted; the identical answer, gated at a threshold just
    # above its own confidence, is escalated rather than ignored outright.
    a = _confident(helpers.ALLOWED)
    assert helpers.moderate("M1", a, a.confidence).action == helpers.IGNORE
    assert helpers.moderate("M1", a, a.confidence + 1e-9).action == helpers.ESCALATE


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.moderate("M1", _confident(helpers.ALLOWED), bad)


def test_the_state_hides_python_owned_fields():
    fields = {"message_id": "MSG-9", "author": "nova_badger", "message": "hello there"}
    state = helpers.build_state(fields)
    assert set(state) == {"rule", "message"}
    assert state["message"] == "hello there"
    # Literal substrings of the rule text, independent of helpers.RULE_TEXT, so a build_state
    # that silently swapped in a different rule (not merely a different message) still fails.
    assert "Lumen Games Community" in state["rule"]
    assert "Do not harass, threaten, demean, or target a member" in state["rule"]
    assert state["rule"] == helpers.RULE_TEXT


def test_the_review_queue_preserves_submission_order():
    # Recipe 15's review asked for this: the populated moderator queue must come back in the
    # order items were escalated, not merely hold the right items.
    queue = ReviewQueue()
    ids = ["M1", "M2", "M3", "M4"]
    for message_id in ids:
        low = _low_confidence(helpers.REVIEW_NEEDED)
        result = helpers.moderate(message_id, low, 0.9)
        assert result.action == helpers.ESCALATE
        queue.submit({"message_id": message_id}, result.reason, answer=low)
    assert [item["item"]["message_id"] for item in queue.to_dicts()] == ids


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    wrong = [
        e.id
        for e in load_inputs(RECIPE)
        if e.id in labels
        and backend.decide(helpers.build_state(e.fields), questions)["triage"].choice
        != labels[e.id]
    ]
    assert wrong, "the fixtures should contain some wrong answers"


def test_a_wrong_stored_answer_is_confident_at_or_above_the_frozen_gate():
    """The honest-gate guard: a gate is only informative if it is shown not catching every
    mistake. ``t17-false-flag`` and ``t20-missed-violation`` are both wrong and confident
    (0.7750 each), clearing ``FROZEN_GATE`` (printed as 0.7600): one hides an allowed message,
    the other lets a violating one stand as ``allowed`` -- the gate applies to every category
    alike, and still does not catch either."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    confident_and_wrong = []
    for e in load_inputs(RECIPE):
        if e.id not in labels:
            continue
        triage = backend.decide(helpers.build_state(e.fields), questions)["triage"]
        if triage.choice != labels[e.id] and triage.confidence >= FROZEN_GATE:
            confident_and_wrong.append(e.id)
    assert confident_and_wrong, "at least one wrong answer should clear the frozen gate"
