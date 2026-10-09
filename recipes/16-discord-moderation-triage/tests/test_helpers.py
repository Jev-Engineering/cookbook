"""Tests for recipe 16's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# The threshold recipe 16's notebook chooses on validation and freezes before test (see
# notebook.ipynb, "Python's part"): the lowest confidence among the gated validation examples
# (review_needed or potentially_violating) whose answered subset is perfectly accurate -- which
# is "v13-violating-harass"'s own stored confidence, printed as 0.7600 but not exactly that in
# floating point (the Choice confidence formula divides by 2/3). Written here as a literal, to
# the precision select_confidence_threshold actually returns it, so a change to this rule's
# behaviour, not merely to the fixtures, is what the frozen-threshold tests below are pinned
# against.
FROZEN_THRESHOLD = 0.7599999999999998

REAL_FLAGGED_CATEGORIES = [helpers.REVIEW_NEEDED, helpers.POTENTIALLY_VIOLATING]


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


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["triage"]
    triage = questions["triage"]
    assert list(triage.criteria) == ["allowed", "review_needed", "potentially_violating"]
    assert all(isinstance(d, str) and d for d in triage.criteria.values())
    assert isinstance(triage.instructions, str) and triage.instructions


def test_allowed_is_always_ignored_confident_or_not():
    confident = helpers.moderate("M1", _confident(helpers.ALLOWED), 0.9)
    unsure = helpers.moderate("M1", _low_confidence(helpers.ALLOWED), 0.9)
    assert (confident.label, confident.action) == (helpers.ALLOWED, helpers.IGNORE)
    assert (unsure.label, unsure.action) == (helpers.ALLOWED, helpers.IGNORE)


@pytest.mark.parametrize("label", REAL_FLAGGED_CATEGORIES)
def test_a_confident_flagged_category_acts_whatever_the_label(label):
    result = helpers.moderate("M1", _confident(label), 0.5)
    expected_action = helpers.WARN if label == helpers.REVIEW_NEEDED else helpers.HIDE
    assert (result.label, result.action) == (label, expected_action)


@pytest.mark.parametrize("label", REAL_FLAGGED_CATEGORIES)
def test_a_low_confidence_flagged_category_is_escalated_whatever_the_label(label):
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
    odd = ChoiceAnswer.from_probabilities({"mystery": 0.9, "allowed": 0.1}, Provenance.synthetic())
    result = helpers.moderate("M1", odd, 0.0)
    assert result.action == helpers.ESCALATE
    assert result.reason == "not one of the fixed categories"


def test_the_threshold_is_inclusive():
    a = _confident(helpers.POTENTIALLY_VIOLATING)
    t = a.confidence
    assert helpers.moderate("M1", a, t).action == helpers.HIDE
    assert helpers.moderate("M1", a, t + 1e-9).action == helpers.ESCALATE


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


def test_a_wrong_stored_answer_is_confident_at_or_above_the_frozen_threshold():
    """The honest-threshold guard: a threshold is only informative if it is shown not catching
    every mistake. ``t15-false-allow`` and ``t17-false-flag`` are wrong and, respectively,
    0.7000 and 0.7750 confident; the second clears ``FROZEN_THRESHOLD`` (printed as 0.7600), and
    both show a cost the confidence gate does not (``t15``, "allowed" never passes through the
    gate) or does not always (``t17``, confident enough to clear it) prevent."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    confident_and_wrong = []
    for e in load_inputs(RECIPE):
        if e.id not in labels:
            continue
        triage = backend.decide(helpers.build_state(e.fields), questions)["triage"]
        if triage.choice != labels[e.id] and triage.confidence >= FROZEN_THRESHOLD:
            confident_and_wrong.append(e.id)
    assert confident_and_wrong, "at least one wrong answer should clear the frozen threshold"
