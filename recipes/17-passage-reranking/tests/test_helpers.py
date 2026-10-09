"""Tests for recipe 17's helpers. They load the helpers by file path."""

import math
from pathlib import Path

import pytest

from jev_cookbook import Provenance, ScoreAnswer, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import score_level, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
LEVELS = list(helpers.RELEVANCE_LEVELS)


def answer(probabilities):
    return ScoreAnswer.from_probabilities(probabilities, LEVELS, Provenance.synthetic())


CONFIDENT_DIRECT = answer([0.02, 0.03, 0.10, 0.85])  # level 3, high confidence
CONFIDENT_NOT_RELEVANT = answer([0.72, 0.16, 0.08, 0.04])  # level 0, high confidence

# One low-confidence answer peaking at each of the four levels, spread close to even, so a rule
# that exempted one level from the confidence gate would still fail the parametrized test below.
LOW_CONFIDENCE_BY_LEVEL = {
    0: answer([0.28, 0.26, 0.24, 0.22]),
    1: answer([0.24, 0.28, 0.26, 0.22]),
    2: answer([0.22, 0.24, 0.28, 0.26]),
    3: answer([0.22, 0.24, 0.26, 0.28]),
}


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["relevance"]
    relevance = questions["relevance"]
    assert list(relevance.criteria) == list(helpers.RELEVANCE_LEVELS)
    assert len(relevance.criteria) == 4
    assert all(isinstance(level, str) and level for level in relevance.criteria)
    assert isinstance(relevance.instructions, str) and relevance.instructions


def test_a_confident_answer_at_or_above_the_cutoff_is_a_match():
    result = helpers.classify("KB-1", CONFIDENT_DIRECT, 0.3)
    assert (result.passage_id, result.level, result.outcome) == ("KB-1", 3, helpers.MATCH)


def test_a_confident_answer_below_the_cutoff_is_no_match():
    result = helpers.classify("KB-1", CONFIDENT_NOT_RELEVANT, 0.3)
    assert (result.passage_id, result.level, result.outcome) == ("KB-1", 0, helpers.NO_MATCH)


@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_a_low_confidence_answer_goes_to_review_whatever_the_level(level):
    a = LOW_CONFIDENCE_BY_LEVEL[level]
    result = helpers.classify("KB-1", a, 0.5)
    assert a.confidence < 0.5
    assert result.outcome == helpers.REVIEW
    assert result.reason == "confidence below the threshold"


def test_the_confidence_gate_is_inclusive():
    t = CONFIDENT_DIRECT.confidence
    assert helpers.classify("KB-1", CONFIDENT_DIRECT, t).outcome == helpers.MATCH
    assert helpers.classify("KB-1", CONFIDENT_DIRECT, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_confidence_gate_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify("KB-1", CONFIDENT_DIRECT, bad)


def test_the_business_cutoff_is_exactly_at_relevant():
    # BUSINESS_CUTOFF marks the boundary: RELEVANT (level 2) and above are a match; below it,
    # no_match.
    just_below = answer([0.05, 0.85, 0.05, 0.05])  # level 1
    just_at = answer([0.05, 0.05, 0.85, 0.05])  # level 2
    assert helpers.classify("KB-1", just_below, 0.0).outcome == helpers.NO_MATCH
    assert helpers.classify("KB-1", just_at, 0.0).outcome == helpers.MATCH


def test_the_state_hides_bookkeeping_fields():
    fields = {
        "query_id": "Q99",
        "query": "How do I reset my password?",
        "passage_id": "KB-999",
        "passage": "Open the sign-in page and select Forgot password.",
    }
    assert helpers.build_state(fields) == {
        "query": "How do I reset my password?",
        "passage": "Open the sign-in page and select Forgot password.",
    }


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example;
    # adapt this when an example needs a dependent second request (CONTRIBUTING: a question that
    # depends on an earlier answer goes in a later request), where the example lists a key for
    # each request in order.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# ---------------------------------------------------------------------------------- The baseline


def test_lexical_score_counts_shared_non_stopwords():
    # "how", "do", "i", "my" are stopwords; "reset" and "password" are shared.
    assert helpers.lexical_score("How do I reset my password?", "Reset your password here.") == 2
    assert helpers.lexical_score("profile picture size", "a profile picture of your dog") == 2


def test_lexical_score_is_case_insensitive_and_ignores_punctuation():
    assert helpers.lexical_score("Refund TIMING?", "The refund, timing!! is fixed.") == 2


def test_lexical_score_has_no_overlap_for_unrelated_text():
    assert helpers.lexical_score("password reset", "profile picture upload") == 0


def test_baseline_rank_orders_by_lexical_score_then_breaks_ties_by_position():
    a = helpers.Candidate("A", "refund timing", "unrelated text here", 0)
    b = helpers.Candidate("B", "refund timing", "a refund post, with timing details", 1)
    c = helpers.Candidate("C", "refund timing", "another refund and timing passage", 2)
    # B and C tie on lexical_score (2 each); A has 0. Ties go to the lower position (B before
    # C). The candidates are passed in as [C, B, A] -- out of position order, and with C (the
    # higher-position member of the tie) listed before B -- on purpose: presenting them already
    # sorted by position would let Python's own stable sort produce the right-looking answer
    # even with baseline_rank's position tie-break removed, so that ordering could not tell the
    # two apart.
    ranks = helpers.baseline_rank([c, b, a])
    assert ranks == {"B": 0, "C": 1, "A": 2}


def test_rerank_orders_by_score_then_baseline_rank_on_ties():
    candidates = [
        helpers.Candidate("A", "q", "p", 0),
        helpers.Candidate("B", "q", "p", 1),
        helpers.Candidate("C", "q", "p", 2),
    ]
    scores = {"A": 1.0, "B": 2.0, "C": 1.0}  # A and C tie
    ranks = {"A": 1, "B": 0, "C": 0}  # baseline prefers C over A on the tie
    ordered = helpers.rerank(candidates, scores, ranks)
    assert [c.passage_id for c in ordered] == ["B", "C", "A"]


def test_rerank_keeps_each_passages_source_reference():
    # Reranking must not lose or rewrite a candidate's identity: every field survives unchanged.
    original = helpers.Candidate("KB-42", "a query", "a passage", 0)
    (ordered,) = helpers.rerank([original], {"KB-42": 1.5}, {"KB-42": 0})
    assert ordered == original


# ------------------------------------------------------------------------- The top-1 ranking gap


def test_top1_accuracy_credits_a_clear_winner():
    # One query, three passages; the second one (index 1) is gold-relevant and scores highest.
    assert helpers.top1_accuracy([([0, 1, 0], [0.1, 0.9, 0.2])]) == 1.0


def test_top1_accuracy_zero_when_the_top_scored_item_is_not_relevant():
    assert helpers.top1_accuracy([([0, 1, 0], [0.9, 0.1, 0.2])]) == 0.0


def test_top1_accuracy_averages_over_queries():
    queries = [
        ([0, 1], [0.1, 0.9]),  # correct
        ([1, 0], [0.1, 0.9]),  # wrong
    ]
    assert helpers.top1_accuracy(queries) == 0.5


def test_top1_accuracy_gives_fractional_credit_on_a_tie_at_the_top():
    # Two items tie for the top score and exactly one of them is relevant: the same
    # expectation-over-tie-orders rule recall_at_budget uses gives half credit.
    assert helpers.top1_accuracy([([1, 0], [0.5, 0.5])]) == 0.5


def test_top1_accuracy_empty_queries_is_an_error():
    with pytest.raises(ValueError):
        helpers.top1_accuracy([])


def test_top1_accuracy_raises_when_no_query_has_a_relevant_item():
    with pytest.raises(ValueError):
        helpers.top1_accuracy([([0, 0], [0.1, 0.9])])


def test_top1_accuracy_differs_from_recall_at_a_budget_of_one():
    # Two of three passages are gold-relevant, and the top-scored passage is one of them: the
    # single top-scored item IS relevant, so top-1 ranking accuracy is 1.0. But reviewing only
    # that one item finds just one of the two relevant passages, so recall at a budget of 1
    # item is 0.5. An earlier version of top1_accuracy computed the mean of
    # evaluation.recall_at_budget(relevant, scores, 1) over queries, on the mistaken assumption
    # that the two always agree; this fixture is exactly the case where they do not.
    from jev_cookbook.evaluation import recall_at_budget

    relevant, scores = [1, 1, 0], [0.9, 0.1, 0.2]
    assert helpers.top1_accuracy([(relevant, scores)]) == 1.0
    assert recall_at_budget(relevant, scores, 1) == 0.5


def test_top1_accuracy_is_one_when_every_passage_is_relevant():
    assert helpers.top1_accuracy([([1, 1, 1], [0.9, 0.1, 0.2])]) == 1.0


# ----------------------------------------------------------------- The fixtures tell this story


def test_stored_answers_are_not_all_right():
    """At least one stored `test` answer is wrong (its modal level does not match the gold
    label) while confident enough to clear the frozen confidence gate -- the fixture that
    keeps selective risk on `test` non-zero rather than a threshold that happens to look
    perfect (docs/fixtures.md, "Avoid synthetic responses so tidy that every model-free
    baseline scores perfectly on test")."""
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    questions = helpers.build_questions()
    backend = get_backend(fixtures=responses_path(RECIPE))

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["relevance"]

    val_examples = select_split(examples, "validation")
    val_answers = [decide(e) for e in val_examples]
    val_gold = [labels[e.id] for e in val_examples]
    val_correct = [score_level(a) == g for a, g in zip(val_answers, val_gold, strict=True)]
    val_confidence = [a.confidence for a in val_answers]
    gate = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)

    test_examples = select_split(examples, "test")
    test_answers = [decide(e) for e in test_examples]
    test_gold = [labels[e.id] for e in test_examples]
    wrong_and_confident = [
        a
        for a, g in zip(test_answers, test_gold, strict=True)
        if score_level(a) != g and a.confidence >= gate
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
    assert not math.isnan(gate)
