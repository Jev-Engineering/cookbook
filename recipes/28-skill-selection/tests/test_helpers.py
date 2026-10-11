"""Tests for recipe 28's helpers. They load the helpers by file path."""

import contextlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

from jev_cookbook import (
    Provenance,
    ScoreAnswer,
    answer_from_dict,
    get_backend,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import evaluate_outcomes, score_level, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
LEVELS = list(helpers.SUITABILITY_LEVELS)


def _load_build_fixtures():
    """build_fixtures.py by file path, so its ROWS (and TASK_SPECS, _rows, check_intended_levels)
    are plain Python objects -- the same way tests/test_build_fixtures.py loads it, but this
    module keeps its own import so a recipe's rule tests never depend on that guarded file's
    exact content."""
    spec = importlib.util.spec_from_file_location(
        "recipe28_build_fixtures_for_rule_tests", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def judgment(skill_id, probabilities):
    answer = ScoreAnswer.from_probabilities(list(probabilities), LEVELS, Provenance.synthetic())
    return helpers.judgment_from_answer(skill_id, answer)


IDEAL_CONFIDENT = (0.02, 0.03, 0.10, 0.85)  # modal level 3, score 2.78
SUITABLE_CONFIDENT = (0.03, 0.09, 0.73, 0.15)  # modal level 2, score 2.00
RELATED_CONFIDENT = (0.09, 0.71, 0.14, 0.06)  # modal level 1, score 1.17
RELATED_HIGH = (0.02, 0.49, 0.47, 0.02)  # modal level 1, score 1.49: near the level-1 ceiling
NOT_SUITABLE_CONFIDENT = (0.72, 0.16, 0.08, 0.04)  # modal level 0, score 0.44
NOT_SUITABLE_AT_ALL = (0.95, 0.03, 0.01, 0.01)  # modal level 0, score 0.08


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


def test_the_business_cutoff_can_bind_even_with_a_wide_margin():
    # A modal-level-1 top, scored near the ceiling a genuinely modal-1 answer can reach,
    # against two confidently-unrelated fillers: the margin (wide) would pass on its own, but
    # the business cutoff still rejects it outright. This is the shape of v23/t22.
    js = [
        judgment("a", RELATED_HIGH),
        judgment("b", NOT_SUITABLE_AT_ALL),
        judgment("c", NOT_SUITABLE_AT_ALL),
    ]
    result = helpers.select_skill("t1", js, margin_threshold=0.1)
    assert (result.margin >= 0.1) is True  # the margin check alone would have passed
    assert result.outcome == helpers.REVIEW
    assert result.reason == "the top skill's modal level is below the business cutoff"


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


# ------------------------------------------------------------------------- is_safe_auto_answer


def test_is_safe_auto_answer_true_only_for_the_sole_best_skill():
    assert helpers.is_safe_auto_answer("a", frozenset({"a"})) is True
    assert helpers.is_safe_auto_answer("b", frozenset({"a"})) is False


def test_is_safe_auto_answer_is_false_for_a_tie_whichever_one_is_picked():
    # Unlike gold_best_skills membership (used for the permissive, reported top-1 accuracy),
    # a tie is never "safe" for the margin threshold to have let through automatically --
    # picking either tied skill does not make guessing on it safe.
    tied = frozenset({"a", "b"})
    assert helpers.is_safe_auto_answer("a", tied) is False
    assert helpers.is_safe_auto_answer("b", tied) is False


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


def test_outcome_accounting_uses_the_permissive_membership_check_unlike_the_margin_pool():
    # A tied task counts as correct here (either tied skill is an acceptable top-1 pick), the
    # opposite of is_safe_auto_answer's stricter rule for choosing the margin threshold itself.
    selections = [
        helpers.Selection("t1", "a", 3, 0.9, helpers.SELECT, "clearly the best-fitting skill")
    ]
    gold_best_by_task = {"t1": frozenset({"a", "b"})}
    _, correct = helpers.outcome_accounting(selections, gold_best_by_task)
    assert correct == [True]


# --------------------------------------------------------------- the margin threshold itself


def test_margin_min_coverage_is_pinned():
    # Pin the objective (min_coverage, not target_accuracy) and its parameter, so changing
    # either cannot leave this test green.
    assert helpers.MARGIN_MIN_COVERAGE == 0.5


def test_select_margin_threshold_uses_min_coverage_not_target_accuracy():
    # A target_accuracy=1.0 search would freeze the lowest threshold whose answered subset is
    # still 100% right: 0.8 (coverage 0.4), since the wrong example at margin 0.7 has to stay
    # excluded. min_coverage instead freezes the highest-accuracy cut-off that still answers at
    # least half the pool: 0.1 (coverage 1.0, accuracy 0.8), the best accuracy among the
    # cut-offs that clear that coverage floor. The two objectives disagree on this pool, so
    # pinning that select_margin_threshold reproduces the min_coverage answer is a real
    # assertion, not one both objectives would satisfy anyway.
    safe = [True, True, False, True, True]
    margin = [0.9, 0.8, 0.7, 0.6, 0.1]
    by_min_coverage = select_confidence_threshold(safe, margin, min_coverage=0.5)
    by_target_accuracy = select_confidence_threshold(safe, margin, target_accuracy=1.0)
    assert by_min_coverage != by_target_accuracy
    assert helpers.select_margin_threshold(safe, margin) == by_min_coverage


def test_pool_for_margin_selection_excludes_tasks_below_the_business_cutoff():
    judgments_by_task = {
        "t1": [judgment("a", IDEAL_CONFIDENT), judgment("b", NOT_SUITABLE_CONFIDENT)],
        "t2": [judgment("a", RELATED_CONFIDENT), judgment("b", RELATED_CONFIDENT)],
    }
    gold_best_by_task = {"t1": frozenset({"a"}), "t2": frozenset({"a", "b"})}
    safe, margin = helpers.pool_for_margin_selection(judgments_by_task, gold_best_by_task)
    # Only t1 clears the business cutoff; t2's candidates are both modal level 1 and never
    # reach the pool, whatever their margin is.
    assert safe == [True]
    assert len(margin) == 1


def test_pool_for_margin_selection_marks_a_tie_unsafe_regardless_of_which_side_ranks_first():
    judgments_by_task = {"t1": [judgment("a", IDEAL_CONFIDENT), judgment("b", IDEAL_CONFIDENT)]}
    gold_best_by_task = {"t1": frozenset({"a", "b"})}
    safe, margin = helpers.pool_for_margin_selection(judgments_by_task, gold_best_by_task)
    assert safe == [False]


# ------------------------------------------------------------- consequentiality, on real fixtures


def _real_backend_and_questions():
    backend = get_backend(fixtures=responses_path(RECIPE))
    return backend, helpers.build_questions()


def _real_judgments(task_id, examples_by_task, backend, questions):
    answers = {
        e.fields["skill_id"]: backend.decide(helpers.build_state(e.fields), questions)["relevance"]
        for e in examples_by_task[task_id]
    }
    return {skill_id: helpers.judgment_from_answer(skill_id, a) for skill_id, a in answers.items()}


def _frozen_margin_threshold(backend, questions, labels):
    """The margin threshold the notebook itself freezes, computed the same way it is there --
    calling the real ``helpers.select_margin_threshold`` on the real ``validation`` pool --
    rather than a magic constant repeated at every call site. (A test below pins the number
    this returns against the committed fixtures directly.)"""
    val_examples_by_task = helpers.group_by_task_id(
        [e for e in load_inputs(RECIPE) if e.split == "validation"]
    )
    judgments_by_task = {
        tid: list(_real_judgments(tid, val_examples_by_task, backend, questions).values())
        for tid in val_examples_by_task
    }
    gold_best_by_task = {
        tid: helpers.gold_best_skills({e.fields["skill_id"]: labels[e.id] for e in exs})
        for tid, exs in val_examples_by_task.items()
    }
    safe, margin = helpers.pool_for_margin_selection(judgments_by_task, gold_best_by_task)
    return helpers.select_margin_threshold(safe, margin)


def test_the_business_cutoff_is_consequential_on_a_real_fixture():
    # t01 (test): calendar_scheduling is confidently selected (modal level 3). Flip its stored
    # answer to RELATED_HIGH -- modal level 1, but still scored well clear of t01's own
    # fillers (margin 0.35 against the frozen margin_threshold=0.3 used here, so the margin
    # check alone would still have passed) -- and the composed outcome must change from select
    # to review, with the cutoff's own reason. Using RELATED_CONFIDENT instead (as an earlier
    # version of this test did) would also drop the margin below 0.3, so the flip would be
    # over-determined: either check alone could explain the review, and the reason assertion
    # would be all that distinguishes them. RELATED_HIGH keeps the margin check passing so this
    # proof isolates the cutoff on its own.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(load_inputs(RECIPE))
    judgments = _real_judgments("t01", examples_by_task, backend, questions)
    before = helpers.select_skill("t01", list(judgments.values()), margin_threshold=0.3)
    assert before.outcome == helpers.SELECT

    mutated = dict(judgments)
    mutated["calendar_scheduling"] = judgment("calendar_scheduling", RELATED_HIGH)
    after = helpers.select_skill("t01", list(mutated.values()), margin_threshold=0.3)
    assert after.margin >= 0.3  # the margin check alone would still have passed
    assert after.outcome == helpers.REVIEW
    assert after.reason == "the top skill's modal level is below the business cutoff"


def test_the_margin_threshold_is_consequential_on_a_real_fixture():
    # t01 (test): calendar_scheduling wins by a wide margin over its filler candidates. Raise
    # one filler's score to close the margin and the composed outcome must change from select
    # to review, with the margin's own reason.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(load_inputs(RECIPE))
    judgments = _real_judgments("t01", examples_by_task, backend, questions)
    before = helpers.select_skill("t01", list(judgments.values()), margin_threshold=0.4)
    assert before.outcome == helpers.SELECT

    mutated = dict(judgments)
    mutated["travel_booking"] = judgment("travel_booking", IDEAL_CONFIDENT)
    after = helpers.select_skill("t01", list(mutated.values()), margin_threshold=0.4)
    assert after.outcome == helpers.REVIEW
    assert after.reason == "the margin between the top two skills is below the threshold"


@contextlib.contextmanager
def _cutoff_disabled():
    """Patches ``helpers.BUSINESS_CUTOFF`` to a value its own check inside ``select_skill``
    (``top.level < BUSINESS_CUTOFF``) can never satisfy -- a modal level is always 0, 1, 2 or
    3, never negative, so 0 makes the comparison always false. This calls the real
    ``select_skill`` with its cutoff branch structurally unreachable, rather than a second
    implementation of the branch standing in for "deleted": if the branch were actually
    deleted from ``select_skill``'s own source, patching this constant would do nothing (there
    would be no comparison left to defeat), and the tests below that rely on this context
    manager would then compute the same selections with or without it -- which is exactly the
    failure that proves they are reading the real function, not a copy of its logic."""
    original = helpers.BUSINESS_CUTOFF
    helpers.BUSINESS_CUTOFF = 0
    try:
        yield
    finally:
        helpers.BUSINESS_CUTOFF = original


def _selections(split, margin_threshold, backend, questions, examples_by_task, labels):
    """Selections from the real ``helpers.select_skill`` for every task in ``split`` -- never a
    second implementation of its branches. Margin is "deleted" by passing
    ``margin_threshold=0.0``: margin is a normalized gap between two scores and is therefore
    always ``>= 0``, so ``margin < 0.0`` can never be true and that branch cannot fire, the
    same structural-unreachability trick :func:`_cutoff_disabled` uses for the cutoff."""
    selections, gold_best_by_task = [], {}
    for task_id, exs in sorted(examples_by_task.items()):
        if exs[0].split != split:
            continue
        judgments = list(_real_judgments(task_id, examples_by_task, backend, questions).values())
        gold_best_by_task[task_id] = helpers.gold_best_skills(
            {e.fields["skill_id"]: labels[e.id] for e in exs}
        )
        selections.append(helpers.select_skill(task_id, judgments, margin_threshold))
    return selections, gold_best_by_task


def test_deleting_the_business_cutoff_changes_a_reported_outcome_on_the_committed_fixtures():
    # The stronger standard: not just "a mutation flips one example in isolation", but "the
    # real rule, called on the committed fixtures with the business cutoff structurally
    # unreachable, reports a different coverage and a different accuracy". v23 and t22 are
    # built exactly to make this true: a modal-level-1 top, scored near the ceiling, with a
    # margin wide enough to pass on its own.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(load_inputs(RECIPE))
    labels = load_labels(RECIPE)
    margin_threshold = _frozen_margin_threshold(backend, questions, labels)

    for split in ("validation", "test"):
        with_cutoff, gold_best = _selections(
            split, margin_threshold, backend, questions, examples_by_task, labels
        )
        with _cutoff_disabled():
            without_cutoff, _ = _selections(
                split, margin_threshold, backend, questions, examples_by_task, labels
            )
        accepted_with, correct_with = helpers.outcome_accounting(with_cutoff, gold_best)
        accepted_without, correct_without = helpers.outcome_accounting(without_cutoff, gold_best)
        result_with = evaluate_outcomes(accepted_with, correct_with)
        result_without = evaluate_outcomes(accepted_without, correct_without)
        assert result_with.coverage != result_without.coverage
        assert result_with.accuracy != result_without.accuracy


def test_deleting_the_margin_check_changes_a_reported_outcome_on_the_committed_fixtures():
    # Same standard, for the margin: without it (margin_threshold=0.0, which the real
    # select_skill's own `margin < margin_threshold` comparison can never fail against a
    # margin that is always >= 0), the "two skills equally plausible" tasks (v04, t04) become
    # automatic, unreviewed guesses, changing both coverage and accuracy.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(load_inputs(RECIPE))
    labels = load_labels(RECIPE)
    margin_threshold = _frozen_margin_threshold(backend, questions, labels)

    for split in ("validation", "test"):
        with_margin, gold_best = _selections(
            split, margin_threshold, backend, questions, examples_by_task, labels
        )
        without_margin, _ = _selections(split, 0.0, backend, questions, examples_by_task, labels)
        accepted_with, correct_with = helpers.outcome_accounting(with_margin, gold_best)
        accepted_without, correct_without = helpers.outcome_accounting(without_margin, gold_best)
        result_with = evaluate_outcomes(accepted_with, correct_with)
        result_without = evaluate_outcomes(accepted_without, correct_without)
        assert result_with.coverage != result_without.coverage
        assert result_with.accuracy != result_without.accuracy


def test_no_confidence_gate_could_have_caught_the_wrong_selections_without_also_losing_correct_ones():
    # The measurement helpers.py's own comment above select_skill relies on, checked directly,
    # per split rather than pooled: each split's own wrong auto-selection shares the highest
    # confidence among that split's auto-selected tasks with a genuinely correct one, so no
    # confidence gate -- at any threshold -- can separate that split's mistake from the correct
    # answers it is tied with. Checking per split (not just the pooled maxima) means lowering
    # either v22's or t05's confidence alone, leaving the other at the top, still fails this
    # test on the split that moved -- not only when both move together.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(load_inputs(RECIPE))
    labels = load_labels(RECIPE)
    margin_threshold = _frozen_margin_threshold(backend, questions, labels)

    for split in ("validation", "test"):
        selections, gold_best = _selections(
            split, margin_threshold, backend, questions, examples_by_task, labels
        )
        wrong_confidences, correct_confidences = [], []
        for s in selections:
            if s.outcome != helpers.SELECT:
                continue
            exs = examples_by_task[s.task_id]
            answer = next(
                backend.decide(helpers.build_state(e.fields), questions)["relevance"]
                for e in exs
                if e.fields["skill_id"] == s.skill_id
            )
            (
                correct_confidences if s.skill_id in gold_best[s.task_id] else wrong_confidences
            ).append(answer.confidence)

        assert wrong_confidences, f"expected at least one wrong auto-selection on {split}"
        assert correct_confidences, f"expected at least one correct auto-selection on {split}"
        assert math.isclose(max(wrong_confidences), max(correct_confidences), abs_tol=1e-9), (
            f"expected {split}'s wrong selection's confidence to be tied with the highest "
            f"confidence among {split}'s correct selections -- the property a confidence gate "
            f"cannot act on"
        )


def test_margin_threshold_frozen_on_validation_matches_the_committed_fixtures():
    # End to end, on the committed fixtures: the exact value the notebook freezes.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(
        [e for e in load_inputs(RECIPE) if e.split == "validation"]
    )
    labels = load_labels(RECIPE)
    judgments_by_task = {
        tid: list(_real_judgments(tid, examples_by_task, backend, questions).values())
        for tid in examples_by_task
    }
    gold_best_by_task = {
        tid: helpers.gold_best_skills({e.fields["skill_id"]: labels[e.id] for e in exs})
        for tid, exs in examples_by_task.items()
    }
    safe, margin = helpers.pool_for_margin_selection(judgments_by_task, gold_best_by_task)
    assert len(safe) == 22  # every validation task except v03 and v23, which fail the cutoff
    assert safe.count(False) == 3  # v04 (tied), v05 and v22 (wrong), each unsafe to auto-answer
    margin_threshold = helpers.select_margin_threshold(safe, margin)
    assert math.isclose(margin_threshold, 0.4033333333333334, abs_tol=1e-9)


def test_perfect_validation_accuracy_is_infeasible_on_the_margin_pool():
    # The property helpers.py's own comment above MARGIN_MIN_COVERAGE relies on, checked
    # directly: on the real margin pool, a target_accuracy=1.0 objective is not merely a
    # weaker choice than min_coverage -- it is unreachable, because the pool's own
    # joint-maximum margin is held by both a safe example (v01) and an unsafe one (v22), so
    # no non-empty answered set is ever error-free. A fixture edit that made a perfect
    # threshold reachable again (by, say, giving v22 a margin below every safe example's)
    # would make this test stop raising, catching the comment going stale a second time.
    backend, questions = _real_backend_and_questions()
    examples_by_task = helpers.group_by_task_id(
        [e for e in load_inputs(RECIPE) if e.split == "validation"]
    )
    labels = load_labels(RECIPE)
    judgments_by_task = {
        tid: list(_real_judgments(tid, examples_by_task, backend, questions).values())
        for tid in examples_by_task
    }
    gold_best_by_task = {
        tid: helpers.gold_best_skills({e.fields["skill_id"]: labels[e.id] for e in exs})
        for tid, exs in examples_by_task.items()
    }
    safe, margin = helpers.pool_for_margin_selection(judgments_by_task, gold_best_by_task)

    max_margin = max(margin)
    holders_safe = {s for s, m in zip(safe, margin, strict=True) if m == max_margin}
    assert holders_safe == {True, False}, (
        "expected the pool's joint-maximum margin to be held by both a safe and an unsafe "
        "example -- the property that makes target_accuracy=1.0 infeasible here"
    )
    with pytest.raises(ValueError, match="no threshold reaches accuracy 1.0"):
        select_confidence_threshold(safe, margin, target_accuracy=1.0)


# --------------------------------------------------------------------- not all answers are right


def test_test_split_has_a_wrong_task_that_clears_the_frozen_margin_threshold():
    # The standard "stored answers are not all right" guard, adapted to this recipe's actual
    # mechanism: a task-level margin threshold, not a per-question confidence gate (this
    # recipe has no per-answer confidence check to mirror -- see helpers.select_skill's own
    # comment for why). Reproduces the notebook's own threshold selection by calling the same
    # shared helpers it calls, never reimplementing them, then requires a `test` task the
    # frozen gates still wrongly select -- the mistake evaluating on `test` exists to catch.
    backend, questions = _real_backend_and_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    examples_by_task = helpers.group_by_task_id(examples)

    val_tasks = {tid: exs for tid, exs in examples_by_task.items() if exs[0].split == "validation"}
    judgments_by_task = {
        tid: list(_real_judgments(tid, val_tasks, backend, questions).values()) for tid in val_tasks
    }
    gold_best_by_task = {
        tid: helpers.gold_best_skills({e.fields["skill_id"]: labels[e.id] for e in exs})
        for tid, exs in val_tasks.items()
    }
    safe, margin = helpers.pool_for_margin_selection(judgments_by_task, gold_best_by_task)
    threshold = helpers.select_margin_threshold(safe, margin)

    test_tasks = {tid: exs for tid, exs in examples_by_task.items() if exs[0].split == "test"}
    wrong_and_selected = []
    for task_id, exs in test_tasks.items():
        judgments = list(_real_judgments(task_id, test_tasks, backend, questions).values())
        selection = helpers.select_skill(task_id, judgments, threshold)
        gold_best = helpers.gold_best_skills({e.fields["skill_id"]: labels[e.id] for e in exs})
        if selection.outcome == helpers.SELECT and selection.skill_id not in gold_best:
            wrong_and_selected.append(task_id)
    assert wrong_and_selected, "expected at least one test task the frozen gates wrongly select"


def test_stored_answers_are_not_all_right():
    # The standard per-question guard: re-derive a confidence threshold from validation's own
    # (correct, confidence) pairs and require a wrong `test` answer at or above it. This is a
    # property of the stored answers themselves, independent of the task-level margin rule
    # above (which does not gate on any answer's own `.confidence` -- see helpers.select_skill's
    # comment for why): a question-level answer can still be wrong and confident even though
    # the composed task-level decision has no confidence check to catch it with.
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


# ------------------------------------------- build_fixtures.py's own rows and declared levels


def test_every_committed_stored_answers_top_choice_is_the_one_its_row_names():
    """A fixture-building spec must never let the stored answer's own top choice silently
    drift from what the row itself says it should be. Every row in build_fixtures.py's
    ``TASK_SPECS`` names its own ``intended_level`` directly, never defaulted or inferred from
    the gold level (several of the fifty tasks' rows deliberately disagree: ``gold_level`` is
    what a skill really deserves, ``intended_level`` is the modal level the row's own
    probabilities are written to land on). This checks every committed row against that
    declaration."""
    module = _load_build_fixtures()
    responses = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    questions = helpers.build_questions()
    for ident, _split, fields, _gold_level, intended_level, _probabilities in module.ROWS:
        key = replay_key(helpers.build_state(fields), questions)
        stored = responses[key]
        answer = answer_from_dict(stored["answers"]["relevance"])
        level = score_level(answer)
        assert level == intended_level, f"{ident}: stored level {level}, row names {intended_level}"


def test_check_intended_levels_catches_a_mismatch():
    """Mutation proof for the test above: check_intended_levels (what build_fixtures.py itself
    runs before writing anything) must actually fail when a row's intended_level disagrees with
    what its probabilities land on, not merely pass by construction."""
    module = _load_build_fixtures()
    module.check_intended_levels(module.ROWS)  # no error on the real rows

    mutated = list(module.ROWS)
    ident, split, fields, gold_level, intended_level, probabilities = mutated[0]
    mutated[0] = (ident, split, fields, gold_level, (intended_level + 1) % 4, probabilities)
    with pytest.raises(SystemExit, match="intended_level"):
        module.check_intended_levels(mutated)


def test_retrieval_matches_every_tasks_own_spec():
    """TASK_SPECS names each task's candidates only implicitly, through their own dict keys;
    build_fixtures.py's ``_rows`` calls the real ``retrieve_candidates`` to decide which skills
    are asked about, and raises if retrieval ever disagrees with what a task's own spec names
    (so TASK_SPECS cannot silently drift from what the recipe's own retriever would actually
    return)."""
    module = _load_build_fixtures()
    for task_id, _split, task, specs in module.TASK_SPECS:
        candidates = helpers.retrieve_candidates(task)
        assert set(candidates) == set(specs), task_id
