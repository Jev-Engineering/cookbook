"""Tests for recipe 07's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

WORDS = list(helpers.SENSE_INVENTORY)


def answer(word, probabilities):
    """A ChoiceAnswer over ``word``'s own options (its senses plus ``unclear``)."""
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def confident(word, sense):
    """A clearly confident answer naming ``sense`` for ``word``."""
    others = [s for s in helpers.senses_for(word) if s != sense]
    probabilities = {sense: 0.90}
    remainder = 0.10 / len(others)
    probabilities.update({s: remainder for s in others})
    return answer(word, probabilities)


def low_confidence(word, sense):
    """A barely-ahead answer naming ``sense`` for ``word``, confidence well under 0.5."""
    others = [s for s in helpers.senses_for(word) if s != sense]
    probabilities = {sense: 0.36}
    remainder = 0.64 / len(others)
    probabilities.update({s: remainder for s in others})
    return answer(word, probabilities)


def confident_unclear(word):
    """A confident ``unclear`` answer: the model is sure context does not decide."""
    senses = [s for s in helpers.senses_for(word) if s != helpers.UNCLEAR]
    probabilities = {helpers.UNCLEAR: 0.90}
    remainder = 0.10 / len(senses)
    probabilities.update({s: remainder for s in senses})
    return answer(word, probabilities)


def confident_foreign(word):
    """A confident answer naming an option that is not one of ``word``'s own senses and is not
    ``unclear`` either -- a sense `resolve` must still reject, even though the criteria
    `build_questions` actually asks with never offer such an option (see `resolve`'s docstring:
    the check is defensive, not reachable through replay or live)."""
    return answer(word, {"not_a_real_sense_of_this_word": 0.90, "also_not_one": 0.10})


def test_each_words_options_are_its_senses_plus_unclear():
    for word in WORDS:
        questions = helpers.build_questions(word)
        assert list(questions) == ["sense"]
        sense = questions["sense"]
        assert list(sense.criteria) == [*helpers.SENSE_INVENTORY[word], helpers.UNCLEAR]
        assert all(isinstance(d, str) and d for d in sense.criteria.values())
        assert isinstance(sense.instructions, str) and word in sense.instructions


def test_senses_for_an_unknown_word_is_an_error():
    with pytest.raises(KeyError, match="spoon"):
        helpers.senses_for("spoon")


def test_the_state_hides_the_sentence_id():
    fields = {"sentence_id": "S9", "word": "bank", "sentence": "The bank was closed."}
    assert helpers.build_state(fields) == {"word": "bank", "sentence": "The bank was closed."}


@pytest.mark.parametrize("word", WORDS)
def test_a_confident_known_sense_is_accepted_whatever_the_word_and_sense(word):
    for sense in helpers.SENSE_INVENTORY[word]:
        a = confident(word, sense)
        result = helpers.resolve("E1", word, a, 0.5)
        assert (result.sense, result.outcome) == (sense, helpers.ACCEPTED)


@pytest.mark.parametrize("word", WORDS)
def test_a_low_confidence_answer_goes_to_review_whatever_the_word_and_sense(word):
    for sense in helpers.SENSE_INVENTORY[word]:
        a = low_confidence(word, sense)
        assert a.choice == sense
        assert a.confidence < 0.5
        result = helpers.resolve("E1", word, a, 0.5)
        assert result.outcome == helpers.REVIEW
        assert "threshold" in result.reason


@pytest.mark.parametrize("word", WORDS)
def test_choosing_unclear_goes_to_review_even_when_confident(word):
    a = confident_unclear(word)
    assert a.choice == helpers.UNCLEAR
    assert a.confidence > 0.8
    result = helpers.resolve("E1", word, a, 0.0)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "chose unclear"


@pytest.mark.parametrize("word", WORDS)
def test_choosing_a_sense_outside_the_word_goes_to_review_even_when_confident(word):
    a = confident_foreign(word)
    assert a.choice not in helpers.SENSE_INVENTORY[word]
    assert a.choice != helpers.UNCLEAR
    assert a.confidence >= 0.8
    result = helpers.resolve("E1", word, a, 0.0)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "not a sense of this word"


def test_the_threshold_is_inclusive():
    a = confident("bank", "financial_institution")
    t = a.confidence
    assert helpers.resolve("E1", "bank", a, t).outcome == helpers.ACCEPTED
    assert helpers.resolve("E1", "bank", a, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    a = confident("bank", "financial_institution")
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.resolve("E1", "bank", a, bad)


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example,
    # built from that example's own word (the option list, and so the replay key, depends on it).
    for example in load_inputs(RECIPE):
        word = example.fields["word"]
        questions = helpers.build_questions(word)
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    """A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    caught every mistake, which would hide the exact lesson this fixture set exists to teach.
    Re-derive the threshold the way the notebook does (the lowest confidence at which every
    validation answer naming a real sense is correct) and require a wrong `test` answer at or
    above it: a mistake the gate would still let through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    questions_by_word = {word: helpers.build_questions(word) for word in helpers.SENSE_INVENTORY}

    def decide(example):
        word = example.fields["word"]
        return backend.decide(helpers.build_state(example.fields), questions_by_word[word])["sense"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    named = [
        (decide(e).choice == labels[e.id], decide(e).confidence)
        for e in validation
        if decide(e).choice in helpers.SENSE_INVENTORY[e.fields["word"]]
    ]
    threshold = select_confidence_threshold(
        [ok for ok, _ in named], [c for _, c in named], target_accuracy=1.0
    )

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id
        for e in test
        if decide(e).choice in helpers.SENSE_INVENTORY[e.fields["word"]]
        and decide(e).choice != labels[e.id]
        and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
