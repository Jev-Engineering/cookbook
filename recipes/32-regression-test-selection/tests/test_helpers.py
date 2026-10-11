"""Tests for recipe 32's helpers. They load the helpers by file path."""

import json
import math
from pathlib import Path

import pytest

from jev_cookbook import Provenance, ScoreAnswer, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import (
    evaluate_outcomes,
    evaluate_selective,
    recall_at_budget,
    score_level,
    select_confidence_threshold,
)
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
LEVELS = list(helpers.RELEVANCE_LEVELS)


def answer(probabilities):
    return ScoreAnswer.from_probabilities(probabilities, LEVELS, Provenance.synthetic())


CONFIDENT_DIRECT = answer([0.02, 0.03, 0.10, 0.85])  # level 3, high confidence
CONFIDENT_UNRELATED = answer([0.75, 0.15, 0.07, 0.03])  # level 0, high confidence

# One low-confidence answer peaking at each of the four levels, spread close to even, so a rule
# that exempted one level from the confidence gate would still fail the parametrized test below.
LOW_CONFIDENCE_BY_LEVEL = {
    0: answer([0.28, 0.26, 0.24, 0.22]),
    1: answer([0.24, 0.28, 0.26, 0.22]),
    2: answer([0.22, 0.24, 0.28, 0.26]),
    3: answer([0.22, 0.24, 0.26, 0.28]),
}


def candidate(
    test_id,
    patch="a patch",
    test="a test",
    changed_files=("area/f.py",),
    test_path="tests/area/test_f.py",
    position=0,
):
    return helpers.Candidate(test_id, "task", patch, test, changed_files, test_path, position)


# ----------------------------------------------------------------------------------- The question


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["relevance"]
    relevance = questions["relevance"]
    assert list(relevance.criteria) == list(helpers.RELEVANCE_LEVELS)
    assert len(relevance.criteria) == 4
    assert all(isinstance(level, str) and level for level in relevance.criteria)
    assert isinstance(relevance.instructions, str) and relevance.instructions


def test_the_four_levels_are_distinct_and_in_order():
    # Every level stands alone (no two levels say the same thing), and the tuple's own order
    # (0..3) is the order BUSINESS_CUTOFF and score_level rely on.
    levels = helpers.RELEVANCE_LEVELS
    assert len(set(levels)) == 4
    assert levels[0] is helpers.UNRELATED
    assert levels[1] is helpers.SAME_AREA
    assert levels[2] is helpers.EXERCISES_CHANGE
    assert levels[3] is helpers.DIRECT_REGRESSION


def test_the_state_hides_bookkeeping_fields():
    fields = {
        "task_id": "p99",
        "test_id": "p99__test_x",
        "patch": "This patch changes `f` so that X.",
        "test": "def test_x(): assert f() == 1",
        "changed_files": ["area/f.py"],
        "test_path": "tests/area/test_x.py",
        "position": 0,
    }
    assert helpers.build_state(fields) == {
        "patch": "This patch changes `f` so that X.",
        "test": "def test_x(): assert f() == 1",
    }


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# -------------------------------------------------------------------------------------- classify


def test_a_confident_answer_at_or_above_the_cutoff_is_relevant():
    result = helpers.classify("t1", CONFIDENT_DIRECT, 0.3)
    assert (result.test_id, result.level, result.outcome) == ("t1", 3, helpers.RELEVANT)
    assert result.reason == "modal level clears the business cutoff"


def test_a_confident_answer_below_the_cutoff_is_not_relevant():
    result = helpers.classify("t1", CONFIDENT_UNRELATED, 0.3)
    assert (result.test_id, result.level, result.outcome) == ("t1", 0, helpers.NOT_RELEVANT)
    assert result.reason == "modal level below the business cutoff"


@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_a_low_confidence_answer_goes_to_review_whatever_the_level(level):
    a = LOW_CONFIDENCE_BY_LEVEL[level]
    result = helpers.classify("t1", a, 0.5)
    assert a.confidence < 0.5
    assert result.outcome == helpers.REVIEW
    assert result.reason == "confidence below the threshold"


def test_the_confidence_gate_is_inclusive():
    t = CONFIDENT_DIRECT.confidence
    assert helpers.classify("t1", CONFIDENT_DIRECT, t).outcome == helpers.RELEVANT
    assert helpers.classify("t1", CONFIDENT_DIRECT, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_confidence_gate_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify("t1", CONFIDENT_DIRECT, bad)


def test_the_business_cutoff_is_exactly_at_exercises_change():
    # BUSINESS_CUTOFF marks the boundary: EXERCISES_CHANGE (level 2) and above are relevant;
    # below it, not_relevant.
    just_below = answer([0.05, 0.85, 0.05, 0.05])  # level 1
    just_at = answer([0.05, 0.05, 0.85, 0.05])  # level 2
    assert helpers.classify("t1", just_below, 0.0).outcome == helpers.NOT_RELEVANT
    assert helpers.classify("t1", just_at, 0.0).outcome == helpers.RELEVANT


# ---------------------------------------------------------------------------------- The baseline


def test_lexical_score_counts_shared_non_stopwords():
    assert (
        helpers.lexical_score("How does the refund timing work?", "Refund timing is fixed here.")
        == 2
    )
    assert helpers.lexical_score("profile picture size", "a profile picture of your dog") == 2


def test_lexical_score_is_case_insensitive_and_ignores_punctuation():
    assert helpers.lexical_score("Refund TIMING?", "The refund, timing!! is fixed.") == 2


def test_lexical_score_has_no_overlap_for_unrelated_text():
    assert helpers.lexical_score("discount threshold boundary", "profile picture upload") == 0


def test_file_path_score_matches_on_the_shared_feature_area():
    assert helpers.file_path_score(("billing/discount_engine.py",), "tests/billing/test_x.py") == 1
    assert helpers.file_path_score(("billing/discount_engine.py",), "tests/auth/test_x.py") == 0


def test_file_path_score_checks_every_changed_file():
    changed = ("billing/discount_engine.py", "auth/session_refresh.py")
    assert helpers.file_path_score(changed, "tests/auth/test_x.py") == 1
    assert helpers.file_path_score(changed, "tests/export/test_x.py") == 0


def test_baseline_score_weights_file_path_overlap_above_a_single_word():
    # A file-area match alone (no lexical overlap) must still outrank a lexical-only match of
    # fewer than FILE_PATH_WEIGHT shared words, so the baseline's own weighting is real, not
    # window dressing.
    in_area_no_words = candidate(
        "a",
        patch="apply the discount boundary",
        test="def test_y(): pass",
        changed_files=("billing/x.py",),
        test_path="tests/billing/test_y.py",
    )
    out_of_area_one_word = candidate(
        "b",
        patch="apply the discount boundary",
        test="def test_discount(): pass",
        changed_files=("billing/x.py",),
        test_path="tests/auth/test_discount.py",
    )
    assert helpers.baseline_score(in_area_no_words) > helpers.baseline_score(out_of_area_one_word)


def test_baseline_rank_orders_by_baseline_score_then_breaks_ties_by_position():
    a = candidate(
        "A",
        patch="refund timing",
        test="unrelated text here",
        changed_files=("x/y.py",),
        test_path="tests/w/test_a.py",
        position=0,
    )
    b = candidate(
        "B",
        patch="refund timing",
        test="a refund post, with timing details",
        changed_files=("x/y.py",),
        test_path="tests/z/test_b.py",
        position=1,
    )
    c = candidate(
        "C",
        patch="refund timing",
        test="another refund and timing passage",
        changed_files=("x/y.py",),
        test_path="tests/z/test_c.py",
        position=2,
    )
    # B and C tie on lexical_score (2 each) and file_path_score (0, "z" != "x"); A has neither.
    # Presented out of position order, with C (the higher-position tie member) listed before B,
    # on purpose: a sort that happened to preserve input order could look right by accident.
    ranks = helpers.baseline_rank([c, b, a])
    assert ranks == {"B": 0, "C": 1, "A": 2}


# ------------------------------------------------------------------------- Suite composition


def _classifications(ids_outcomes):
    return {
        test_id: helpers.Classification(test_id, 3, outcome, "r")
        for test_id, outcome in ids_outcomes.items()
    }


def test_propose_suite_excludes_not_relevant_and_review_however_high_their_score():
    cands = [candidate("a"), candidate("b"), candidate("c")]
    classifs = _classifications(
        {"a": helpers.RELEVANT, "b": helpers.NOT_RELEVANT, "c": helpers.REVIEW}
    )
    # b and c score far higher than a, but neither is eligible.
    scores = {"a": 0.5, "b": 3.0, "c": 3.0}
    ranks = {"a": 0, "b": 1, "c": 2}
    assert helpers.propose_suite(cands, classifs, scores, ranks, budget=2) == ["a"]


def test_propose_suite_orders_by_score_then_baseline_rank_on_ties():
    cands = [candidate("a"), candidate("b"), candidate("c")]
    classifs = _classifications(
        {"a": helpers.RELEVANT, "b": helpers.RELEVANT, "c": helpers.RELEVANT}
    )
    scores = {"a": 1.0, "b": 2.0, "c": 1.0}  # a and c tie
    ranks = {"a": 1, "b": 0, "c": 0}  # baseline prefers c over a on the tie
    assert helpers.propose_suite(cands, classifs, scores, ranks, budget=3) == ["b", "c", "a"]


def test_propose_suite_truncates_at_the_budget():
    cands = [candidate(t) for t in ("a", "b", "c")]
    classifs = _classifications({t: helpers.RELEVANT for t in ("a", "b", "c")})
    scores = {"a": 3.0, "b": 2.0, "c": 1.0}
    ranks = {"a": 0, "b": 1, "c": 2}
    assert helpers.propose_suite(cands, classifs, scores, ranks, budget=2) == ["a", "b"]


def test_propose_suite_returns_fewer_than_budget_when_fewer_are_eligible():
    cands = [candidate("a"), candidate("b")]
    classifs = _classifications({"a": helpers.RELEVANT, "b": helpers.NOT_RELEVANT})
    scores = {"a": 1.0, "b": 2.0}
    ranks = {"a": 0, "b": 1}
    assert helpers.propose_suite(cands, classifs, scores, ranks, budget=5) == ["a"]


@pytest.mark.parametrize("bad_budget", [0, -1])
def test_propose_suite_rejects_a_budget_below_one(bad_budget):
    with pytest.raises(ValueError, match="budget must be at least 1"):
        helpers.propose_suite([], {}, {}, {}, budget=bad_budget)


def test_effective_scores_keeps_the_real_score_for_relevant_candidates_only():
    cands = [candidate("a"), candidate("b"), candidate("c")]
    classifs = _classifications(
        {"a": helpers.RELEVANT, "b": helpers.NOT_RELEVANT, "c": helpers.REVIEW}
    )
    scores = {"a": 2.5, "b": 2.9, "c": 2.9}
    eff = helpers.effective_scores(cands, classifs, scores)
    assert eff == {"a": 2.5, "b": helpers.EXCLUDED_SCORE, "c": helpers.EXCLUDED_SCORE}


def test_effective_budget_caps_at_the_eligible_count():
    cands = [candidate("a"), candidate("b"), candidate("c")]
    classifs = _classifications(
        {"a": helpers.RELEVANT, "b": helpers.NOT_RELEVANT, "c": helpers.REVIEW}
    )
    assert helpers.effective_budget(cands, classifs, budget=2) == 1  # only "a" is eligible
    classifs_two = _classifications(
        {"a": helpers.RELEVANT, "b": helpers.RELEVANT, "c": helpers.REVIEW}
    )
    assert helpers.effective_budget(cands, classifs_two, budget=5) == 2  # capped at the budget too


@pytest.mark.parametrize("bad_budget", [0, -1])
def test_effective_budget_rejects_a_budget_below_one(bad_budget):
    with pytest.raises(ValueError, match="budget must be at least 1"):
        helpers.effective_budget([], {}, budget=bad_budget)


def test_effective_budget_and_effective_scores_reproduce_propose_suite_on_a_fixture_shaped_case():
    # The exact shape a "gate" task takes in this recipe's fixtures: one high-confidence direct
    # candidate and one low-confidence (but high-scoring) exercises_change candidate, among
    # four total. Without the cap, recall_at_budget would award the excluded candidate partial
    # credit for tying with the not_relevant/review candidates at EXCLUDED_SCORE (the bug
    # effective_budget exists to prevent); capping at the eligible count removes that tie.
    cands = [candidate(t) for t in ("direct", "exercises_low", "same_area", "unrelated")]
    classifs = _classifications(
        {
            "direct": helpers.RELEVANT,
            "exercises_low": helpers.REVIEW,
            "same_area": helpers.NOT_RELEVANT,
            "unrelated": helpers.NOT_RELEVANT,
        }
    )
    scores = {"direct": 2.78, "exercises_low": 2.28, "same_area": 1.11, "unrelated": 0.38}
    ranks = {"direct": 0, "exercises_low": 1, "same_area": 2, "unrelated": 3}
    gold_relevant = [1, 1, 0, 0]  # direct and exercises_low are both gold-relevant

    suite = helpers.propose_suite(cands, classifs, scores, ranks, budget=2)
    assert suite == ["direct"]  # exercises_low is excluded, however high its score

    eff_scores = helpers.effective_scores(cands, classifs, scores)
    eff_budget = helpers.effective_budget(cands, classifs, budget=2)
    assert eff_budget == 1
    recall = recall_at_budget(gold_relevant, [eff_scores[c.test_id] for c in cands], eff_budget)
    assert recall == pytest.approx(0.5)  # found "direct"; missed "exercises_low"; 1 of 2

    # Without the cap (the bug this function exists to prevent), recall_at_budget would instead
    # give "exercises_low" partial tie credit for the second, nonexistent slot.
    uncapped = recall_at_budget(gold_relevant, [eff_scores[c.test_id] for c in cands], 2)
    assert uncapped == pytest.approx(2 / 3)
    assert uncapped != recall


# ---------------------------------------------------------- The fixtures tell the right story


def _decide_all(recipe_examples, backend, questions):
    return {
        e.id: backend.decide(helpers.build_state(e.fields), questions)["relevance"]
        for e in recipe_examples
    }


def _by_task(split_examples):
    by_task = {}
    for e in split_examples:
        by_task.setdefault(e.fields["task_id"], []).append(e)
    return by_task


def _frozen_gate():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    answers = _decide_all(examples, backend, questions)
    val = select_split(examples, "validation")
    val_gold = [labels[e.id] for e in val]
    val_correct = [score_level(answers[e.id]) == g for e, g in zip(val, val_gold, strict=True)]
    val_confidence = [answers[e.id].confidence for e in val]
    gate = select_confidence_threshold(val_correct, val_confidence, min_coverage=0.8)
    return examples, labels, backend, questions, answers, gate


def test_stored_answers_are_not_all_right():
    """At least one stored `test` answer is wrong (its modal level does not match the gold
    label) while confident enough to clear the frozen confidence gate -- the fixture that keeps
    selective risk on `test` non-zero rather than a threshold that happens to look perfect."""
    examples, labels, _backend, _questions, answers, gate = _frozen_gate()
    test = select_split(examples, "test")
    test_gold = [labels[e.id] for e in test]
    wrong_and_confident = [
        e.id
        for e, g in zip(test, test_gold, strict=True)
        if score_level(answers[e.id]) != g and answers[e.id].confidence >= gate
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
    assert not math.isnan(gate)


def test_the_confidence_gate_is_selected_with_min_coverage_not_target_accuracy():
    # Pins the objective (min_coverage, never target_accuracy=1.0) *and* its parameter (0.8):
    # changing either would freeze a different gate without this test noticing otherwise.
    examples, labels, _backend, _questions, answers, gate = _frozen_gate()
    val = select_split(examples, "validation")
    val_gold = [labels[e.id] for e in val]
    val_correct = [score_level(answers[e.id]) == g for e, g in zip(val, val_gold, strict=True)]
    val_confidence = [answers[e.id].confidence for e in val]
    reselected = select_confidence_threshold(val_correct, val_confidence, min_coverage=0.8)
    assert reselected == gate
    assert gate == pytest.approx(0.48)
    looser = select_confidence_threshold(val_correct, val_confidence, min_coverage=0.5)
    tighter = select_confidence_threshold(val_correct, val_confidence, min_coverage=0.99)
    assert not (looser == gate == tighter)  # the parameter is load-bearing, not just the keyword


def test_every_task_has_at_least_one_eligible_candidate_under_the_frozen_gate():
    # effective_budget's n_eligible == 0 branch is never exercised on committed data; this is
    # what makes that true, on both splits.
    examples, labels, _backend, _questions, answers, gate = _frozen_gate()
    for split in ("validation", "test"):
        by_task = _by_task(select_split(examples, split))
        for task_id, task_examples in by_task.items():
            n_eligible = sum(
                1
                for e in task_examples
                if helpers.classify(e.id, answers[e.id], gate).outcome == helpers.RELEVANT
            )
            assert n_eligible >= 1, f"{task_id} has no eligible candidate"


def test_both_not_relevant_and_review_outcomes_occur_on_both_splits():
    # propose_suite's eligibility filter ("only `relevant`") is meaningless if one of the two
    # excluded outcomes never actually fires on real data.
    examples, labels, _backend, _questions, answers, gate = _frozen_gate()
    for split in ("validation", "test"):
        split_examples = select_split(examples, split)
        outcomes = {helpers.classify(e.id, answers[e.id], gate).outcome for e in split_examples}
        assert helpers.NOT_RELEVANT in outcomes
        assert helpers.REVIEW in outcomes


def _task_recall(task_examples, labels, answers, gate, budget):
    cands = [
        helpers.Candidate(
            e.id,
            e.fields["task_id"],
            e.fields["patch"],
            e.fields["test"],
            tuple(e.fields["changed_files"]),
            e.fields["test_path"],
            e.fields["position"],
        )
        for e in task_examples
    ]
    classifs = {e.id: helpers.classify(e.id, answers[e.id], gate) for e in task_examples}
    scores = {e.id: answers[e.id].score for e in task_examples}
    ranks = helpers.baseline_rank(cands)
    gold_relevant = [1 if labels[e.id] >= helpers.BUSINESS_CUTOFF else 0 for e in task_examples]
    eff_scores = helpers.effective_scores(cands, classifs, scores)
    eff_budget = helpers.effective_budget(cands, classifs, budget)
    suite = helpers.propose_suite(cands, classifs, scores, ranks, budget)
    recall = recall_at_budget(gold_relevant, [eff_scores[e.id] for e in task_examples], eff_budget)
    return recall, suite, gold_relevant


def test_recall_at_budget_agrees_with_propose_suite_on_every_task_in_both_splits():
    """`recall_at_budget` (fed effective_scores/effective_budget) must never disagree with
    `propose_suite`'s own pick about how many gold-relevant candidates were actually proposed --
    the "no reimplementation" proof CONTRIBUTING.md asks for: both are derived from the same
    helpers, so a bug in either shows up as a mismatch here instead of in two silently-drifting
    numbers."""
    examples, labels, _backend, _questions, answers, gate = _frozen_gate()
    for split in ("validation", "test"):
        by_task = _by_task(select_split(examples, split))
        for task_id, task_examples in by_task.items():
            recall, suite, gold_relevant = _task_recall(
                task_examples, labels, answers, gate, helpers.SUITE_BUDGET
            )
            ids = [e.id for e in task_examples]
            found = sum(1 for test_id in suite if gold_relevant[ids.index(test_id)])
            total_relevant = sum(gold_relevant)
            assert recall == pytest.approx(found / total_relevant), task_id


def test_the_confidence_gate_is_load_bearing_for_task_level_recall():
    """Deleting the confidence gate (setting it to 0.0, so nothing is ever sent to review)
    changes mean recall at the budget on both splits -- the gate is not a branch that could be
    removed without changing anything this recipe reports."""
    examples, labels, _backend, _questions, answers, gate = _frozen_gate()
    for split in ("validation", "test"):
        by_task = _by_task(select_split(examples, split))
        with_gate = [
            _task_recall(items, labels, answers, gate, helpers.SUITE_BUDGET)[0]
            for items in by_task.values()
        ]
        without_gate = [
            _task_recall(items, labels, answers, 0.0, helpers.SUITE_BUDGET)[0]
            for items in by_task.values()
        ]
        assert sum(without_gate) / len(without_gate) > sum(with_gate) / len(with_gate)


def test_the_suite_budget_is_load_bearing_for_task_level_recall():
    """Deleting the size budget (proposing every eligible candidate) changes mean recall at the
    budget on both splits -- the budget is not a number large enough that it never binds."""
    examples, labels, _backend, _questions, answers, gate = _frozen_gate()
    for split in ("validation", "test"):
        by_task = _by_task(select_split(examples, split))
        with_budget = [
            _task_recall(items, labels, answers, gate, helpers.SUITE_BUDGET)[0]
            for items in by_task.values()
        ]
        unbounded = [
            _task_recall(items, labels, answers, gate, 1000)[0] for items in by_task.values()
        ]
        assert sum(unbounded) / len(unbounded) > sum(with_budget) / len(with_budget)


def test_the_confidence_gate_catches_a_real_review_task_but_the_budget_catches_a_different_one():
    """The two mechanisms bind on disjoint tasks in this fixture set: at least one task's
    recall rises only when the gate is removed (not the budget), and at least one task's recall
    rises only when the budget is removed (not the gate) -- so neither mechanism is redundant
    with the other."""
    examples, labels, _backend, _questions, answers, gate = _frozen_gate()
    val = select_split(examples, "validation")
    by_task = _by_task(val)
    gate_only, budget_only = [], []
    for task_id, items in by_task.items():
        base = _task_recall(items, labels, answers, gate, helpers.SUITE_BUDGET)[0]
        no_gate = _task_recall(items, labels, answers, 0.0, helpers.SUITE_BUDGET)[0]
        no_budget = _task_recall(items, labels, answers, gate, 1000)[0]
        if no_gate > base and no_budget == base:
            gate_only.append(task_id)
        if no_budget > base and no_gate == base:
            budget_only.append(task_id)
    assert gate_only, "expected at least one task the gate alone constrains"
    assert budget_only, "expected at least one task the budget alone constrains"


def test_evaluate_selective_and_evaluate_outcomes_agree_for_this_confidence_only_rule():
    """`classify`'s only review branch is the confidence gate (no unconditional fallback, no
    membership check), so the confidence-only view and the rule's own outcomes must agree on
    every field but `threshold` -- checked directly, not only argued, on real `test` data."""
    examples, labels, _backend, _questions, answers, gate = _frozen_gate()
    test = select_split(examples, "test")
    test_gold = [labels[e.id] for e in test]
    classifs = {e.id: helpers.classify(e.id, answers[e.id], gate) for e in test}
    accepted = [classifs[e.id].outcome != helpers.REVIEW for e in test]
    correct = [
        (classifs[e.id].outcome == helpers.RELEVANT) == (g >= helpers.BUSINESS_CUTOFF)
        for e, g in zip(test, test_gold, strict=True)
    ]
    confidence = [answers[e.id].confidence for e in test]
    outcomes = evaluate_outcomes(accepted, correct)
    selective = evaluate_selective(correct, confidence, gate)
    assert (
        outcomes.n_total,
        outcomes.n_answered,
        outcomes.coverage,
        outcomes.accuracy,
        outcomes.risk,
    ) == (
        selective.n_total,
        selective.n_answered,
        selective.coverage,
        selective.accuracy,
        selective.risk,
    )


def test_notebook_pins_min_coverage_not_target_accuracy():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    assert "min_coverage=0.8" in source
    assert "target_accuracy" not in source
