"""Tests for recipe 06's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import NoulAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

LABELS = list(helpers.LABELS)
THRESHOLDS = {label: 0.5 for label in LABELS}  # a fixed, simple rule for the tests below


def answer(noul):
    return NoulAnswer(noul, Provenance.synthetic())


def answers(**by_label):
    """``{label: NoulAnswer}`` for every label in ``LABELS``; labels not passed default to a
    clear, confident "no" (0.05) so a test only has to name the labels it cares about."""
    return {label: answer(by_label.get(label, 0.05)) for label in LABELS}


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == LABELS
    for label in LABELS:
        question = questions[label]
        assert question.type == "noul"
        assert isinstance(question.instructions, str) and question.instructions
        assert set(question.criteria) == {"true", "false"}


@pytest.mark.parametrize("label", LABELS)
def test_a_confident_yes_is_tagged_yes_whatever_the_label(label):
    decisions = helpers.decide_tags(answers(**{label: 0.90}), THRESHOLDS, confidence_cutoff=0.3)
    assert decisions[label].outcome == helpers.YES
    assert helpers.tag_set(decisions) == {label}
    assert helpers.uncertain_labels(decisions) == ()


@pytest.mark.parametrize("label", LABELS)
def test_a_confident_no_is_tagged_no_whatever_the_label(label):
    decisions = helpers.decide_tags(answers(**{label: 0.05}), THRESHOLDS, confidence_cutoff=0.3)
    assert decisions[label].outcome == helpers.NO
    assert label not in helpers.tag_set(decisions)
    assert helpers.uncertain_labels(decisions) == ()


@pytest.mark.parametrize("label", LABELS)
def test_a_low_confidence_answer_is_uncertain_whatever_the_label_or_business_tag(label):
    # noul = 0.52: just above the 0.5 threshold (a "yes" by the business rule alone), but its
    # confidence |2*0.52 - 1| = 0.04 is well below any reasonable cutoff, so the three-path
    # rule must still send it to review rather than reporting it as a tag either way.
    decisions = helpers.decide_tags(answers(**{label: 0.52}), THRESHOLDS, confidence_cutoff=0.3)
    assert decisions[label].outcome == helpers.UNCERTAIN
    assert decisions[label].tag is True  # the business rule alone would have said yes
    assert label not in helpers.tag_set(decisions)
    assert helpers.uncertain_labels(decisions) == (label,)


def test_the_business_threshold_is_inclusive():
    decisions = helpers.decide_tags(answers(pricing=0.5), THRESHOLDS, confidence_cutoff=0.0)
    assert decisions["pricing"].outcome == helpers.YES
    just_below = helpers.decide_tags(answers(pricing=0.4999999), THRESHOLDS, confidence_cutoff=0.0)
    assert just_below["pricing"].outcome == helpers.NO


def test_the_confidence_cutoff_is_inclusive():
    # noul = 0.75: |2*0.75 - 1| = 0.5 exactly.
    at_cutoff = helpers.decide_tags(answers(pricing=0.75), THRESHOLDS, confidence_cutoff=0.5)
    assert at_cutoff["pricing"].outcome == helpers.YES
    above_cutoff = helpers.decide_tags(
        answers(pricing=0.75), THRESHOLDS, confidence_cutoff=0.5 + 1e-9
    )
    assert above_cutoff["pricing"].outcome == helpers.UNCERTAIN


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_business_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.decide_tags(answers(), {"pricing": bad}, confidence_cutoff=0.3)


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_confidence_cutoff_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.decide_tags(answers(), THRESHOLDS, confidence_cutoff=bad)


def test_tag_set_can_be_empty_or_hold_several_labels():
    all_no = helpers.decide_tags(answers(), THRESHOLDS, confidence_cutoff=0.3)
    assert helpers.tag_set(all_no) == frozenset()
    all_yes = helpers.decide_tags(
        answers(**{label: 0.9 for label in LABELS}), THRESHOLDS, confidence_cutoff=0.3
    )
    assert helpers.tag_set(all_yes) == frozenset(LABELS)


def test_the_state_hides_the_feedback_id():
    fields = {"feedback_id": "FB-9", "text": "It works fine."}
    assert helpers.build_state(fields) == {"text": "It works fine."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example
    # (every label's Noul question is sent together); adapt this when an example needs a
    # dependent second request (CONTRIBUTING: a question that depends on an earlier answer goes
    # in a later request), where the example lists a key for each request in order.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)
