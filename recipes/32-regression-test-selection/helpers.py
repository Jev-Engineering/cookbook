"""Python's half of recipe 32: the state, the question, the rule Python enforces, the small
file-path-and-lexical baseline, and the suite-composition function that proposes a bounded
regression suite from one task's candidate tests.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from jev_cookbook import Score
from jev_cookbook.evaluation import recall_at_budget, score_level

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The relevance rubric, lowest level first. Each level is judged on its own against the
# (patch, test) pair ("Every level is evaluated separately. The model doesn't see a level's
# number or its neighbours, so 'worse than the previous level' means nothing to it.",
# https://docs.typesafe.ai/primitives/score), so every description stands alone: it says what
# the test itself exercises, never "less relevant than the level above".
UNRELATED = (
    "The test exercises code that has nothing to do with the module, function, or behavior the "
    "patch changes. Nothing the patch does could make this test start or stop passing."
)
SAME_AREA = (
    "The test exercises the same module or feature area the patch touches, but not the "
    "function or branch the patch changes. A defect in the patch's own change could pass this "
    "test without being caught."
)
EXERCISES_CHANGE = (
    "The test calls the function or exercises the branch the patch changes, and would fail if "
    "that changed behavior were removed, but it does not exercise the exact edge case or "
    "boundary condition the patch adds or alters."
)
DIRECT_REGRESSION = (
    "The test exercises exactly the edge case, boundary, or condition the patch adds or "
    "alters, and would fail if the patch's own change were reverted."
)
RELEVANCE_LEVELS = (UNRELATED, SAME_AREA, EXERCISES_CHANGE, DIRECT_REGRESSION)  # level 0 to 3

# The business cutoff lives in code: a test whose most likely level is below EXERCISES_CHANGE
# (level 2) would not catch a regression in what the patch changes, so Python does not propose
# it for the suite. This is a fixed editorial decision, not a value chosen by searching
# validation: unlike the confidence gate below, there is no "selecting" step for it, which is
# also why it is a plain module constant and not an argument.
BUSINESS_CUTOFF = 2

# The size budget: at most this many tests are proposed per patch, regardless of how many
# candidates clear the business cutoff. Also a fixed editorial decision (a reviewer has time to
# run and read a handful of tests per patch, not the whole candidate set), not something learned
# from data. "Evaluation" below measures, and demonstrates by counterfactual, that this number
# is the thing actually constraining the proposed suite on some tasks, not a number that happens
# to be large enough never to bind.
SUITE_BUDGET = 2

RELEVANT = "relevant"
NOT_RELEVANT = "not_relevant"
REVIEW = "review"

# A fixed, finite stand-in ranking score for a candidate :func:`propose_suite` would never
# propose: lower than any score a 4-level rubric (levels 0 to 3) can ever produce, so it never
# wins a budget slot in :func:`effective_scores`. Negative infinity would say the same thing
# more plainly, but jev_cookbook.evaluation.recall_at_budget requires every score to be finite.
EXCLUDED_SCORE = -1.0


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one (patch, candidate test) pair: the patch description and the
    candidate test's own code, and nothing else.

    ``fields`` also carries ``task_id``, ``test_id``, ``test_path`` and ``changed_files``, all
    bookkeeping Python keeps for itself. None of these reach the model; all are reattached to
    the outcome afterwards, so every proposed test still traces back to its task and its path.
    """
    return {"patch": fields["patch"], "test": fields["test"]}


def build_questions() -> dict[str, Score]:
    """The one question asked about every (patch, candidate test) pair. The levels come from
    ``RELEVANCE_LEVELS``."""
    return {
        "relevance": Score(
            instructions=(
                "How relevant is this candidate test to the behavior this patch changes? Judge "
                "only what this test itself exercises, not what the patch's description claims "
                "about the test, and not any other test."
            ),
            criteria=list(RELEVANCE_LEVELS),
        )
    }


@dataclass(frozen=True)
class Classification:
    """What Python decided about one candidate test: the level Jev's answer most likely holds,
    and the outcome."""

    test_id: str
    level: int
    outcome: str
    reason: str


def classify(test_id: str, answer: Any, confidence_gate: float) -> Classification:
    """Act on a relevance answer: trust it only when confident enough, then apply the cutoff.

    The confidence gate decides whether the score is trustworthy at all: below
    ``confidence_gate`` the outcome is an explicit ``review``, whatever level the answer names,
    because a spread-out distribution over levels is not solid ground for a suite-membership
    decision. At or above it, the rule applies the fixed ``BUSINESS_CUTOFF``: a trusted answer
    whose most likely level (:func:`jev_cookbook.evaluation.score_level`, the modal level, ties
    going to the lower one) falls below ``EXERCISES_CHANGE`` is ``not_relevant``; the rest are
    ``relevant``. The rule is code, so it holds whatever the model answers.

    This function decides only whether to *trust and act on* one candidate's relevance call. It
    does not decide which tests end up in the proposed suite: see :func:`propose_suite`, which
    composes several of these classifications, under a size budget, into one task's suite.
    """
    if not 0.0 <= confidence_gate <= 1.0:
        raise ValueError(f"confidence_gate must be between 0 and 1, got {confidence_gate!r}")
    level = score_level(answer)
    if answer.confidence < confidence_gate:
        return Classification(test_id, level, REVIEW, "confidence below the threshold")
    if level < BUSINESS_CUTOFF:
        return Classification(test_id, level, NOT_RELEVANT, "modal level below the business cutoff")
    return Classification(test_id, level, RELEVANT, "modal level clears the business cutoff")


# --------------------------------------------------------------------------------- The baseline

# A small, deliberately dumb file-path-and-lexical scorer: it checks whether a candidate test
# lives in the same feature area as a file the patch changes, and counts matching words between
# the patch description and the test, and nothing else (no stemming, no term weighting, no
# understanding of what the test actually calls). This is a small lexical scorer written in
# plain Python, standing in for however a candidate set might otherwise be ranked without a
# semantic judgment, with one more deterministic signal (file-path overlap) added to it. A test
# whose name or body is phrased differently from the patch description (a paraphrase) can defeat
# the lexical half of this score on purpose: that is the gap a semantic judgment is for.
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do", "does",
        "for", "from", "have", "how", "i", "if", "in", "is", "it", "its", "of", "on",
        "or", "that", "the", "this", "to", "was", "when", "will", "with",
    }
)  # fmt: skip


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS)


def lexical_score(patch: str, test: str) -> int:
    """Count of the patch description's distinct, non-stopword words that also appear in the
    candidate test."""
    return len(_words(patch) & _words(test))


def _area(path: str) -> str:
    """The feature-area directory name of a file path: the parent directory's own name, so
    ``"billing/discount_engine.py"`` and ``"tests/billing/test_discount_engine.py"`` both give
    ``"billing"`` regardless of a ``tests/`` prefix."""
    return PurePosixPath(path).parent.name


def file_path_score(changed_files: tuple[str, ...], test_path: str) -> int:
    """1 if ``test_path`` shares a feature area with any of ``changed_files``, else 0."""
    return 1 if _area(test_path) in {_area(f) for f in changed_files} else 0


# File-path overlap is weighted above a single shared word, so that a test in the right feature
# area still ranks ahead of an out-of-area test that happens to reuse a few of the patch's words
# (a changed file's own area name, echoed in an unrelated test's docstring, say). Both numbers
# are plain Python integers; this weighting is the only arithmetic the baseline does, and it
# never asks the model for anything.
FILE_PATH_WEIGHT = 2


@dataclass(frozen=True)
class Candidate:
    """One candidate test for one patch, carried through scoring, ranking and proposal
    unchanged."""

    test_id: str
    task_id: str
    patch: str
    test: str
    changed_files: tuple[str, ...]
    test_path: str
    position: int  # 0-based: the order this candidate was listed in, before any scoring


def baseline_score(candidate: Candidate) -> float:
    """The baseline's own ranking score for one candidate: file-path overlap (weighted) plus
    lexical overlap between the patch description and the test. Deterministic, and computed
    with no reference to any Jev answer."""
    return FILE_PATH_WEIGHT * file_path_score(
        candidate.changed_files, candidate.test_path
    ) + lexical_score(candidate.patch, candidate.test)


def baseline_rank(candidates: list[Candidate]) -> dict[str, int]:
    """The 0-based rank of each candidate under :func:`baseline_score`: highest score first,
    ties broken by ``position`` (the order the candidates were originally listed in). This is a
    strict order with no further ties, and it is the baseline this use case names: "file-path
    and lexical overlap between patch and test."
    """
    ordered = sorted(candidates, key=lambda c: (-baseline_score(c), c.position))
    return {c.test_id: rank for rank, c in enumerate(ordered)}


# -------------------------------------------------------------------------- Suite composition


def propose_suite(
    candidates: list[Candidate],
    classifications: dict[str, Classification],
    scores: dict[str, float],
    ranks: dict[str, int],
    budget: int,
) -> list[str]:
    """The regression suite Python proposes for one task's candidates, under a size budget.

    Only a candidate :func:`classify` calls ``relevant`` -- confidence cleared the gate *and*
    the modal level cleared ``BUSINESS_CUTOFF`` -- is eligible to be proposed. Everything else
    -- a candidate confidently judged ``not_relevant``, or one sent to ``review`` because its
    confidence did not clear the gate -- is never proposed, however high its expected score:
    `tests/test_helpers.py` checks this filter fires on real, committed fixtures, not only in a
    unit test built to exercise it. Eligible candidates are then ranked by ``scores`` (each
    candidate's expected Score, highest first), ties broken by ``ranks`` (the baseline order
    from :func:`baseline_rank`, ascending), and the first ``budget`` are returned as the
    proposed suite, in that order. All arithmetic and sorting here is Python's; nothing asks
    the model to rank, weigh, or choose among candidates.

    Args:
        candidates: One task's candidate tests.
        classifications: ``{test_id: Classification}`` from :func:`classify`, one per candidate.
        scores: ``{test_id: float}``, each candidate's Jev expected score.
        ranks: ``{test_id: int}``, each candidate's baseline rank, from :func:`baseline_rank`.
        budget: Maximum number of tests to propose, at least 1.

    Returns:
        The proposed test ids, in the order they were selected (highest score first). May hold
        fewer than ``budget`` ids when fewer than ``budget`` candidates are eligible.
    """
    if budget < 1:
        raise ValueError(f"budget must be at least 1, got {budget!r}")
    eligible = [c for c in candidates if classifications[c.test_id].outcome == RELEVANT]
    ordered = sorted(eligible, key=lambda c: (-scores[c.test_id], ranks[c.test_id]))
    return [c.test_id for c in ordered[:budget]]


def effective_scores(
    candidates: list[Candidate],
    classifications: dict[str, Classification],
    scores: dict[str, float],
    ranks: dict[str, int],
) -> dict[str, float]:
    """The ranking score :func:`jev_cookbook.evaluation.recall_at_budget` must use to reproduce
    :func:`propose_suite`'s own selection exactly, with no tie for it to average over.

    Eligible candidates (:func:`classify` called them ``relevant``) are ordered exactly as
    :func:`propose_suite` orders them -- by ``scores`` (each candidate's expected Score, highest
    first), ties broken by ``ranks`` (the baseline order from :func:`baseline_rank`, which is
    itself a strict order with no ties of its own) -- and then assigned strictly decreasing
    synthetic scores (the most preferred gets ``len(eligible)``, the next
    ``len(eligible) - 1``, and so on down to ``1``). Every other candidate (confidently
    ``not_relevant``, or sent to ``review``) gets ``EXCLUDED_SCORE`` (always below every eligible
    synthetic score, so it can never occupy a budget slot), while still being counted in
    ``recall_at_budget``'s own "all relevant items" denominator (it is not removed from the
    task, only ranked last).

    The synthetic scores, not the raw expected ``scores``, are what close a gap a real expected
    score could otherwise open: two eligible candidates that tied on expected score would tie in
    ``recall_at_budget`` too, which credits a tie in expectation over tie orders -- a different
    number from ``propose_suite``'s own single, deterministic pick, which breaks that same tie
    with ``ranks``. Assigning strictly decreasing integers after applying the identical
    tie-break removes the possibility of a tie at the source, so the two can never diverge
    (`tests/test_helpers.py` exercises this directly on a constructed tie, and also pins the
    true reproduction on every real, committed fixture).

    ``recall_at_budget`` requires every score to be finite, so negative infinity is not an
    option for ``EXCLUDED_SCORE``; a fixed, finite out-of-range constant serves the same
    purpose. This is not the sentinel docs/recipe-template.md warns against: that page's
    sentinel is a stand-in fed to a function that validates its input to ``[0, 1]`` (a
    confidence), so an out-of-range value can itself be mistaken for a chosen threshold;
    ``recall_at_budget`` places no such range on ``scores``, and nothing here derives a
    threshold from this value.
    """
    eligible = [c for c in candidates if classifications[c.test_id].outcome == RELEVANT]
    ordered = sorted(eligible, key=lambda c: (-scores[c.test_id], ranks[c.test_id]))
    out: dict[str, float] = {c.test_id: EXCLUDED_SCORE for c in candidates}
    n = len(ordered)
    for position, c in enumerate(ordered):
        out[c.test_id] = float(n - position)
    return out


def effective_budget(
    candidates: list[Candidate], classifications: dict[str, Classification], budget: int
) -> int:
    """The budget to pass to :func:`jev_cookbook.evaluation.recall_at_budget` together with
    :func:`effective_scores`, so that function's own top-budget selection reproduces
    :func:`propose_suite` exactly even when fewer than ``budget`` candidates are eligible.

    ``recall_at_budget`` always fills its budget from the whole list it is given, ranked by
    score; it has no notion of "eligible" and cannot return fewer than ``min(budget, len(list))``
    selections. ``propose_suite`` can: it returns only its eligible candidates, truncated at
    ``budget``, and returns fewer than ``budget`` ids outright when fewer are eligible. Calling
    ``recall_at_budget`` with the raw ``budget`` on :func:`effective_scores`' output would paper
    over that gap by reaching into the tied ``EXCLUDED_SCORE`` candidates for the remaining
    slot(s), crediting whichever of them happens to be gold-relevant with a fraction of a slot
    :func:`propose_suite` never gives it. Passing ``min(budget, n_eligible)`` instead closes it:
    every eligible candidate's synthetic score (``effective_scores``) is higher than
    ``EXCLUDED_SCORE``, so the top ``effective_budget`` selection can never reach an excluded one.

    Requires at least one eligible candidate: with none, every candidate ties at
    ``EXCLUDED_SCORE`` and there is no well-defined non-empty budget to cap at, so a caller
    reaches this only after ruling that case out itself (:func:`task_recall` does, by returning
    the correct recall directly instead of calling this at all).
    """
    if budget < 1:
        raise ValueError(f"budget must be at least 1, got {budget!r}")
    n_eligible = sum(1 for c in candidates if classifications[c.test_id].outcome == RELEVANT)
    if n_eligible < 1:
        raise ValueError("no eligible candidate: there is no budget to cap at")
    return min(budget, n_eligible)


def task_recall(
    candidates: list[Candidate],
    classifications: dict[str, Classification],
    scores: dict[str, float],
    ranks: dict[str, int],
    gold_relevant: list[int],
    budget: int,
) -> float:
    """One patch's recall of its own gold-relevant candidates within :func:`propose_suite`'s
    actual proposed suite -- the single source both the notebook and `tests/test_helpers.py`
    call, so the per-patch table and the mean it is averaged into can never silently drift apart
    (CONTRIBUTING.md section 7 asks for exactly one place this composition is computed).

    When at least one candidate is eligible, this is
    ``jev_cookbook.evaluation.recall_at_budget`` on :func:`effective_scores` and
    :func:`effective_budget`. When none is, :func:`propose_suite` would propose nothing, so the
    recall is ``0.0`` whenever any candidate is gold-relevant, or ``NaN`` when none is (the same
    undefined-is-NaN convention ``jev_cookbook.evaluation`` uses throughout) -- computed
    directly, never by handing ``recall_at_budget`` a list where every candidate ties at
    ``EXCLUDED_SCORE``, which would instead credit a tie-break share of whichever excluded
    candidate happens to be gold-relevant (`tests/test_helpers.py` exercises this directly: it
    is the zero-eligible counterpart of the tie :func:`effective_scores` closes).
    """
    n_eligible = sum(1 for c in candidates if classifications[c.test_id].outcome == RELEVANT)
    if n_eligible < 1:
        return 0.0 if any(gold_relevant) else float("nan")
    eff_scores = effective_scores(candidates, classifications, scores, ranks)
    eff_budget = effective_budget(candidates, classifications, budget)
    return recall_at_budget(gold_relevant, [eff_scores[c.test_id] for c in candidates], eff_budget)


def baseline_recall(
    candidates: list[Candidate], ranks: dict[str, int], gold_relevant: list[int], budget: int
) -> float:
    """The file-path-and-lexical baseline's own recall of the gold-relevant candidates within
    its own proposed suite: the top ``budget`` candidates under :func:`baseline_rank`'s order.

    Every candidate is unconditionally rankable under the baseline (it has no confidence gate
    and so no notion of "eligible" to exclude anyone), so this is simply
    ``jev_cookbook.evaluation.recall_at_budget`` on the strict rank order
    ``-ranks[c.test_id]`` -- never the raw, possibly-tied :func:`baseline_score` directly, which
    would let ``recall_at_budget`` credit a tie in expectation over tie orders where
    ``baseline_rank`` itself (ties broken by listed position) already picks one deterministic
    winner. Feeding the tied score instead of the rank would be asymmetric with how the Jev
    side is scored (:func:`effective_scores` is deterministic by construction): the two sides
    must be ranked under their own stated order for a recall comparison between them to mean
    anything.
    """
    strict_scores = {c.test_id: float(-ranks[c.test_id]) for c in candidates}
    return recall_at_budget(gold_relevant, [strict_scores[c.test_id] for c in candidates], budget)
