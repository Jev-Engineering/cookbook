"""Tests for recipe 13's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# Literal expected values, independent of helpers.OPTIONS, so a test failure means the rule's
# actual behaviour moved, not just that it still agrees with itself.
EXPECTED_OPTIONS = ["candidate_1", "candidate_2", "candidate_3", "no_suitable_rewrite"]


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
    rest = (1.0 - 0.30) / len(others)
    return answer({label: 0.30, **{o: rest for o in others}})


CANDIDATES = {
    "candidate_1": "the first rewrite",
    "candidate_2": "the second rewrite",
    "candidate_3": "the third rewrite",
}


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["rewrite"]
    rewrite = questions["rewrite"]
    assert list(rewrite.criteria) == EXPECTED_OPTIONS
    assert all(isinstance(d, str) and d for d in rewrite.criteria.values())
    assert isinstance(rewrite.instructions, str) and rewrite.instructions


@pytest.mark.parametrize("label", list(CANDIDATES))
def test_a_confident_candidate_is_accepted_whatever_the_position(label):
    a = _confident(label)
    result = helpers.select_rewrite("R1", a, "original sentence", CANDIDATES, 0.3)
    assert (result.item_id, result.label, result.outcome, result.text) == (
        "R1",
        label,
        helpers.ACCEPTED,
        CANDIDATES[label],
    )


@pytest.mark.parametrize("label", list(CANDIDATES))
def test_a_low_confidence_candidate_goes_to_review_whatever_the_position(label):
    a = _low_confidence(label)
    assert a.choice == label
    assert a.confidence < 0.5
    result = helpers.select_rewrite("R1", a, "original sentence", CANDIDATES, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.text is None
    assert result.reason == "confidence below the threshold"


@pytest.mark.parametrize("top_probability", [0.95, 0.30])
def test_no_suitable_rewrite_is_never_gated_on_confidence_whatever_its_value(top_probability):
    # top_probability=0.30 keeps no_suitable_rewrite as the top option (barely ahead of an even
    # quarter, 0.25) while its confidence, (0.30 - 1/4) / (3/4) =~ 0.067, is well below the 0.3
    # threshold used here. A mutation that exempted no_suitable_rewrite from the gate only when
    # it is also confident would still fail this case, because it is checked at both ends.
    others = [o for o in helpers.OPTIONS if o != helpers.NO_SUITABLE_REWRITE]
    rest = (1.0 - top_probability) / len(others)
    a = answer({helpers.NO_SUITABLE_REWRITE: top_probability, **{o: rest for o in others}})
    assert a.choice == helpers.NO_SUITABLE_REWRITE
    result = helpers.select_rewrite("R1", a, "original sentence", CANDIDATES, 0.3)
    assert result.outcome == helpers.KEPT_ORIGINAL
    assert result.text == "original sentence"
    assert result.label == helpers.NO_SUITABLE_REWRITE


def test_the_threshold_is_inclusive():
    a = _confident("candidate_1")
    t = a.confidence
    assert helpers.select_rewrite("R1", a, "o", CANDIDATES, t).outcome == helpers.ACCEPTED
    assert helpers.select_rewrite("R1", a, "o", CANDIDATES, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.select_rewrite("R1", _confident("candidate_1"), "o", CANDIDATES, bad)


def test_the_state_hides_the_item_id():
    fields = {
        "item_id": "R9",
        "original": "We can't do that.",
        "requested_tone": "polite",
        "candidates": ("a", "b", "c"),
    }
    assert helpers.build_state(fields) == {
        "original": "We can't do that.",
        "requested_tone": "polite",
        "candidate_1": "a",
        "candidate_2": "b",
        "candidate_3": "c",
    }


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
        and backend.decide(helpers.build_state(e.fields), questions)["rewrite"].choice
        != labels[e.id]
    ]
    assert wrong, "the fixtures should contain some wrong answers"


def test_a_wrong_answer_is_at_or_above_the_frozen_threshold_on_test():
    # The stronger guard the lexicon lessons ask for: not just "some wrong answer exists
    # anywhere" (the generic check above), but specifically that the confidence gate, as
    # select_rewrite actually applies it, lets at least one wrong candidate through on `test` --
    # otherwise the recipe's selective risk would be a vacuous zero. The threshold is computed
    # exactly as the notebook computes it: chosen on `validation`, over the candidate-vs-gold
    # comparisons Jev actually matched to a real candidate (no_suitable_rewrite answers are
    # excluded from this selection, because select_rewrite never gates them on confidence).
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    val_examples = select_split(examples, "validation")
    val_answers = [
        backend.decide(helpers.build_state(e.fields), questions)["rewrite"] for e in val_examples
    ]
    val_gold = [labels[e.id] for e in val_examples]
    real_match = [
        (a.choice == g, a.confidence)
        for a, g in zip(val_answers, val_gold, strict=True)
        if a.choice != helpers.NO_SUITABLE_REWRITE
    ]
    threshold = select_confidence_threshold(
        [c for c, _ in real_match], [conf for _, conf in real_match], target_accuracy=1.0
    )

    test_examples = select_split(examples, "test")
    wrong_and_confident = []
    for e in test_examples:
        answer = backend.decide(helpers.build_state(e.fields), questions)["rewrite"]
        candidates = dict(zip(helpers.CANDIDATES, e.fields["candidates"], strict=True))
        result = helpers.select_rewrite(e.id, answer, e.fields["original"], candidates, threshold)
        if result.outcome == helpers.ACCEPTED and result.label != labels[e.id]:
            wrong_and_confident.append((e.id, answer.confidence, threshold))

    assert wrong_and_confident, (
        "the test split should contain at least one wrong answer the frozen confidence gate "
        "lets through (confidence at or above the threshold)"
    )
    for _ident, confidence, frozen in wrong_and_confident:
        assert confidence >= frozen
