"""Tests for recipe 32's helpers. They load the helpers by file path."""

from pathlib import Path

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import score_level, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def test_questions_are_built_by_python():
    # TODO: assert the option lists and criteria against literal expected values (not
    # helpers' own data, which would make the assertion self-referential), then test every rule
    # in helpers.py
    assert helpers.build_questions()


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example;
    # adapt this when an example needs a dependent second request (CONTRIBUTING: a question that
    # depends on an earlier answer goes in a later request), where the example lists a key for
    # each request in order.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if a confidence gate
    # caught every mistake. Mirror your notebook's own threshold selection here, including any
    # filter on which answers can set the bar (the lowest confidence at which every validation
    # answer *that counts* is right -- an unfiltered selection over every validation answer can
    # choose a different, usually lower, threshold than your notebook's own one does), and
    # require a wrong `test` answer at or above it: a mistake the gate would still let through,
    # which is what evaluating on `test` exists to catch. Adapt `predicted`/`confidence` below
    # for a question with no native confidence (a Noul: use
    # jev_cookbook.evaluation.noul_confidence(answer.noul) in place of answer.confidence), or
    # repeat this per question when more than one needs the check.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    name = next(iter(questions))
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)[name]

    def predicted(answer):
        # A Score's own gold label is a level, so compare against score_level(answer) (the
        # most probable level), never answer.score (the probability-weighted expected value,
        # which is a float that almost never equals an integer gold level).
        return answer.choice if hasattr(answer, "choice") else score_level(answer)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: decide(e) for e in validation}
    correct = [predicted(val_answers[e.id]) == labels[e.id] for e in validation]
    confidence = [val_answers[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id
        for e in test
        if predicted(decide(e)) != labels[e.id] and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
