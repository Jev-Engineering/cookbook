"""Tests for recipe 28's helpers. They load the helpers by file path."""

import math
from pathlib import Path

import pytest

from jev_cookbook import Provenance, ScoreAnswer, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_outcomes, score_level, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
LEVELS = list(helpers.SUITABILITY_LEVELS)


def judgment(skill_id, probabilities):
    answer = ScoreAnswer.from_probabilities(list(probabilities), LEVELS, Provenance.synthetic())
    return helpers.Judgment(skill_id, score_level(answer), answer.score)


IDEAL_CONFIDENT = (0.02, 0.03, 0.10, 0.85)  # modal level 3, score 2.78
SUITABLE_CONFIDENT = (0.03, 0.09, 0.73, 0.15)  # modal level 2, score 2.00
RELATED_CONFIDENT = (0.09, 0.71, 0.14, 0.06)  # modal level 1, score 1.17
NOT_SUITABLE_CONFIDENT = (0.72, 0.16, 0.08, 0.04)  # modal level 0, score 0.44


# ------------------------------------------------------------------------------- The question


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["relevance"]
    relevance = questions["relevance"]
    assert list(relevance.criteria) == list(helpers.SUITABILITY_LEVELS)
    assert len(relevance.criteria) == 4
    assert all(isinstance(level, str) and level for level in relevance.criteria)
    assert isinstance(relevance.instructions, str) and relevance.instructions


def test_the_state_hides_bookkeeping_fields():
    fields = {
        "task_id": "x99",
        "task": "Book a conference room for Friday.",
        "skill_id": "calendar_scheduling",
        "skill": "Schedules a meeting.",
    }
    assert helpers.build_state(fields) == {
        "task": "Book a conference room for Friday.",
        "skill": "Schedules a meeting.",
    }


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example;
    # adapt this when an example needs a dependent second request (CONTRIBUTING: a question that
    # depends on an earlier answer goes in a later request), where the example lists a key for
    # each request in order.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# ------------------------------------------------------------------------------- The retriever


def test_retrieve_candidates_orders_by_overlap_then_catalog_order():
    catalog = {"a": "cats and dogs", "b": "cats and birds", "c": "fish and birds"}
    # "cats" matches a and b (overlap 1 each); "birds" matches b and c (overlap 1 each). b
    # scores 2 and is listed first; a and c tie at 1, so the catalog's own insertion order
    # (a before c) breaks the tie, not an incidental sort order.
    assert helpers.retrieve_candidates("cats and birds", catalog, k=3) == ["b", "a", "c"]


def test_retrieve_candidates_is_case_insensitive_and_ignores_punctuation():
    catalog = {"a": "Cats, and DOGS!", "b": "fish only"}
    assert helpers.retrieve_candidates("CATS? dogs.", catalog, k=1) == ["a"]


def test_retrieve_candidates_k_larger_than_catalog_is_an_error():
    with pytest.raises(ValueError, match="exceeds the catalog size"):
        helpers.retrieve_candidates("x", {"a": "y"}, k=2)


def test_retrieve_candidates_defaults_to_the_shared_catalog():
    candidates = helpers.retrieve_candidates("Book a flight for my trip to Denver.")
    assert len(candidates) == helpers.CANDIDATES_PER_TASK
    assert set(candidates) <= set(helpers.SKILL_CATALOG)


def test_lexical_overlap_counts_shared_non_stopwords():
    assert helpers.lexical_overlap("Book a flight to Denver", "Books a flight and a hotel") == 1
    assert helpers.lexical_overlap("schedule a meeting", "schedule a meeting now") == 2


def test_lexical_overlap_has_no_overlap_for_unrelated_text():
    assert helpers.lexical_overlap("book a flight", "submit an expense report") == 0


# -------------------------------------------------------------------------------- The ranking


def test_rank_judgments_orders_by_score_descending():
    js = [judgment("a", NOT_SUITABLE_CONFIDENT), judgment("b", IDEAL_CONFIDENT)]
    assert [j.skill_id for j in helpers.rank_judgments(js)] == ["b", "a"]


def test_rank_judgments_breaks_a_tie_by_retrieval_order():
    # "b" and "c" are given the same score; "b" comes first in the input list, which is
    # retrieval order, so a stable sort must keep it first rather than reorder by skill_id.
    tie = (0.03, 0.10, 0.35, 0.52)
    js = [judgment("c", tie), judgment("b", tie), judgment("a", NOT_SUITABLE_CONFIDENT)]
    assert [j.skill_id for j in helpers.rank_judgments(js)] == ["c", "b", "a"]


def test_rank_judgments_needs_at_least_two():
    with pytest.raises(ValueError, match="at least two"):
        helpers.rank_judgments([judgment("a", IDEAL_CONFIDENT)])


# ------------------------------------------------------------------------------ select_skill


def test_select_skill_selects_a_confident_clear_winner():
    js = [
        judgment("a", IDEAL_CONFIDENT),
        judgment("b", NOT_SUITABLE_CONFIDENT),
        judgment("c", NOT_SUITABLE_CONFIDENT),
    ]
    result = helpers.select_skill("t1", js, margin_threshold=0.5)
    assert (result.skill_id, result.level, result.outcome) == ("a", 3, helpers.SELECT)
    assert result.reason == "clearly the best-fitting skill"


def test_select_skill_reviews_when_the_top_skill_is_below_the_business_cutoff():
    # Every candidate is modal level 1 (related), below BUSINESS_CUTOFF (2): review, whatever
    # the margin among them is.
    js = [
        judgment("a", RELATED_CONFIDENT),
        judgment("b", RELATED_CONFIDENT),
    ]
    result = helpers.select_skill("t1", js, margin_threshold=0.0)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "the top skill's modal level is below the business cutoff"


def test_select_skill_reviews_when_the_margin_is_below_the_threshold():
    # Both candidates clear the business cutoff (modal level 3), but the margin between them
    # is small: the "two skills equally plausible" hard case.
    tie_high = (0.03, 0.10, 0.35, 0.52)
    tie_low = (0.03, 0.12, 0.38, 0.47)
    js = [judgment("a", tie_high), judgment("b", tie_low)]
    result = helpers.select_skill("t1", js, margin_threshold=0.5)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "the margin between the top two skills is below the threshold"


def test_the_margin_gate_is_inclusive():
    js = [judgment("a", IDEAL_CONFIDENT), judgment("b", NOT_SUITABLE_CONFIDENT)]
    margin = helpers.select_skill("t1", js, margin_threshold=0.0).margin
    assert helpers.select_skill("t1", js, margin_threshold=margin).outcome == helpers.SELECT
    assert helpers.select_skill("t1", js, margin_threshold=margin + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_margin_threshold_outside_zero_to_one_is_an_error(bad):
    js = [judgment("a", IDEAL_CONFIDENT), judgment("b", NOT_SUITABLE_CONFIDENT)]
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.select_skill("t1", js, margin_threshold=bad)


# --------------------------------------------------------------------------- gold_best_skills


def test_gold_best_skills_is_a_single_id_when_one_skill_is_clearly_best():
    assert helpers.gold_best_skills({"a": 3, "b": 1, "c": 0}) == {"a"}


def test_gold_best_skills_is_every_tied_id_at_the_top():
    # The "two skills equally plausible" hard case: both carry the highest gold level.
    assert helpers.gold_best_skills({"a": 3, "b": 3, "c": 0}) == {"a", "b"}


def test_gold_best_skills_empty_is_an_error():
    with pytest.raises(ValueError):
        helpers.gold_best_skills({})


# ----------------------------------------------------------------------------- outcome_accounting


def test_outcome_accounting_reads_the_rules_own_outcomes():
    selections = [
        helpers.Selection("t1", "a", 3, 0.9, helpers.SELECT, "clearly the best-fitting skill"),
        helpers.Selection("t2", "a", 1, 0.0, helpers.REVIEW, "cutoff"),
    ]
    gold_best_by_task = {"t1": frozenset({"a"}), "t2": frozenset({"b"})}
    accepted, correct = helpers.outcome_accounting(selections, gold_best_by_task)
    assert accepted == [True, False]
    assert correct == [True, False]  # t2's correctness is computed but unused by evaluate_outcomes
    result = evaluate_outcomes(accepted, correct)
    assert (result.n_total, result.n_answered, result.coverage) == (2, 1, 0.5)
    assert result.accuracy == 1.0


def test_outcome_accounting_empty_is_an_error():
    with pytest.raises(ValueError):
        helpers.outcome_accounting([], {})


# --------------------------------------------------------------- the margin threshold itself


def test_margin_min_coverage_is_pinned():
    # Rule 12: pin the objective (min_coverage, not target_accuracy) and its parameter, so
    # changing either cannot leave this test green.
    assert helpers.MARGIN_MIN_COVERAGE == 0.5


def test_select_margin_threshold_uses_min_coverage_not_target_accuracy():
    # A target_accuracy=1.0 search would freeze the lowest threshold whose answered subset is
    # still 100% right: 0.8 (coverage 0.4), since the wrong example at margin 0.7 has to stay
    # excluded. min_coverage instead freezes the highest-accuracy cut-off that still answers at
    # least half the pool: 0.1 (coverage 1.0, accuracy 0.8), the best accuracy among the
    # cut-offs that clear that coverage floor. The two objectives disagree on this pool, so
    # pinning that select_margin_threshold reproduces the min_coverage answer is a real
    # assertion, not one both objectives would satisfy anyway.
    correct = [True, True, False, True, True]
    margin = [0.9, 0.8, 0.7, 0.6, 0.1]
    by_min_coverage = select_confidence_threshold(correct, margin, min_coverage=0.5)
    by_target_accuracy = select_confidence_threshold(correct, margin, target_accuracy=1.0)
    assert by_min_coverage != by_target_accuracy
    assert helpers.select_margin_threshold(correct, margin) == by_min_coverage


def test_pool_for_margin_selection_excludes_tasks_below_the_business_cutoff():
    judgments_by_task = {
        "t1": [judgment("a", IDEAL_CONFIDENT), judgment("b", NOT_SUITABLE_CONFIDENT)],
        "t2": [judgment("a", RELATED_CONFIDENT), judgment("b", RELATED_CONFIDENT)],
    }
    gold_best_by_task = {"t1": frozenset({"a"}), "t2": frozenset({"a", "b"})}
    correct, margin = helpers.pool_for_margin_selection(judgments_by_task, gold_best_by_task)
    # Only t1 clears the business cutoff; t2's candidates are both modal level 1 and never
    # reach the pool, whatever their margin is.
    assert correct == [True]
    assert len(margin) == 1


# ------------------------------------------------------------- consequentiality, on real fixtures


def _real_backend_and_questions():
    backend = get_backend(fixtures=responses_path(RECIPE))
    return backend, helpers.build_questions()


def _real_judgments(task_id, examples_by_task, backend, questions):
    answers = {
        e.fields["skill_id"]: backend.decide(helpers.build_state(e.fields), questions)["relevance"]
        for e in examples_by_task[task_id]
    }
    return {
        skill_id: helpers.Judgment(skill_id, score_level(a), a.score)
        for skill_id, a in answers.items()
    }


def test_the_business_cutoff_is_consequential_on_a_real_fixture():
    # t01 (test): calendar_scheduling is confidently selected (modal level 3). Flip its stored
    # answer's modal level below the business cutoff and the composed outcome must change from
    # select to review, with the cutoff's own reason -- proof the cutoff is not a dead branch.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(load_inputs(RECIPE))
    judgments = _real_judgments("t01", examples_by_task, backend, questions)
    before = helpers.select_skill("t01", list(judgments.values()), margin_threshold=0.5)
    assert before.outcome == helpers.SELECT

    mutated = dict(judgments)
    mutated["calendar_scheduling"] = judgment("calendar_scheduling", RELATED_CONFIDENT)
    after = helpers.select_skill("t01", list(mutated.values()), margin_threshold=0.5)
    assert after.outcome == helpers.REVIEW
    assert after.reason == "the top skill's modal level is below the business cutoff"


def test_the_margin_threshold_is_consequential_on_a_real_fixture():
    # t01 (test): calendar_scheduling wins by a wide margin over its filler candidates. Raise
    # one filler's score to close the margin and the composed outcome must change from select
    # to review, with the margin's own reason.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(load_inputs(RECIPE))
    judgments = _real_judgments("t01", examples_by_task, backend, questions)
    before = helpers.select_skill("t01", list(judgments.values()), margin_threshold=0.5)
    assert before.outcome == helpers.SELECT

    mutated = dict(judgments)
    mutated["travel_booking"] = judgment("travel_booking", IDEAL_CONFIDENT)
    after = helpers.select_skill("t01", list(mutated.values()), margin_threshold=0.5)
    assert after.outcome == helpers.REVIEW
    assert after.reason == "the margin between the top two skills is below the threshold"


def test_margin_threshold_frozen_on_validation_matches_the_committed_fixtures():
    # End to end, on the committed fixtures: the exact value the notebook freezes.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(
        [e for e in load_inputs(RECIPE) if e.split == "validation"]
    )
    labels = load_labels(RECIPE)
    judgments_by_task = {
        tid: _real_judgments(tid, examples_by_task, backend, questions) for tid in examples_by_task
    }
    judgments_by_task = {tid: list(js.values()) for tid, js in judgments_by_task.items()}
    gold_best_by_task = {
        tid: helpers.gold_best_skills({e.fields["skill_id"]: labels[e.id] for e in exs})
        for tid, exs in examples_by_task.items()
    }
    correct, margin = helpers.pool_for_margin_selection(judgments_by_task, gold_best_by_task)
    assert len(correct) == 4  # v03 fails the business cutoff and never joins the pool
    threshold = helpers.select_margin_threshold(correct, margin)
    assert math.isclose(threshold, 0.78, abs_tol=1e-9)


# --------------------------------------------------------------------- not all answers are right


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if a confidence gate
    # caught every mistake. Mirror your notebook's own threshold selection here, including any
    # filter on which answers can set the bar (the lowest confidence at which every validation
    # answer *that counts* is right -- an unfiltered selection over every validation answer can
    # choose a different, usually lower, threshold than your notebook's own one does), and
    # require a wrong `test` answer at or above it: a mistake the gate would still let through,
    # which is what evaluating on `test` exists to catch. This checks the *per-question* Score
    # answers directly (each (task, skill) request against its own gold level), independent of
    # the task-level margin/business-cutoff rule checked above.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    name = next(iter(questions))
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)[name]

    def predicted(answer):
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
