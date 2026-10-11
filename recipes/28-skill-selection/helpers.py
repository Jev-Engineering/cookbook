"""Python's half of recipe 28: the state, the question, the small lexical retriever that
stands in for a skill catalog's search step, and the rule that turns several per-skill Score
answers into one task-level decision.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

import re
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Score
from jev_cookbook.evaluation import select_confidence_threshold

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------- The skill catalog

# A fixed, Python-owned catalog of skills an agent could dispatch a task to. Jev never sees the
# catalog: build_state passes it exactly one skill's own description at a time, alongside the
# task, so a request never lets the model compare skills against each other. The dict's
# insertion order is also the tie-break order ``retrieve_candidates`` uses, so it is written
# once and never reordered.
SKILL_CATALOG: dict[str, str] = {
    "calendar_scheduling": (
        "Schedules a meeting: checks attendees' availability and books a free slot on the calendar."
    ),
    "travel_booking": (
        "Books travel for a trip: reserves a flight, a hotel room, or a rental car and "
        "confirms the itinerary."
    ),
    "expense_report": (
        "Files an expense report: submits a receipt for reimbursement and reports the status "
        "of a submitted claim."
    ),
    "doc_search": (
        "Searches the internal knowledge base: finds the internal documentation article that "
        "answers a written question."
    ),
    "code_review_summary": (
        "Summarizes a code change for review: reads a pull request's diff and lists what it "
        "changes and which tests it touches."
    ),
}

CANDIDATES_PER_TASK = 3  # how many catalog skills Python retrieves for every task

# ------------------------------------------------------------------------------- The retriever

# A small, deliberately dumb lexical scorer standing in for a real skill-catalog search: it
# counts matching words between the task and a skill's own description, nothing more (no
# stemming, no synonyms, no term weighting). "Python retrieves candidate skill descriptions"
# (the use case) is exactly this one countable rule, not a black box, and it is what decides
# which skills Jev is even asked to score -- the model never sees a skill that was not
# retrieved for its task.
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "before", "by", "can", "do", "does", "for",
        "from", "has", "have", "how", "i", "if", "in", "is", "it", "its", "my", "next", "of",
        "on", "or", "our", "please", "that", "the", "this", "to", "up", "want", "we", "what",
        "when", "will", "with", "you", "your",
    }
)  # fmt: skip


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS)


def lexical_overlap(task: str, description: str) -> int:
    """Count of the task's distinct, non-stopword words that also appear in ``description``."""
    return len(_words(task) & _words(description))


def retrieve_candidates(
    task: str, catalog: dict[str, str] | None = None, k: int = CANDIDATES_PER_TASK
) -> list[str]:
    """The ``k`` catalog skill ids whose description overlaps ``task`` the most, highest
    overlap first, ties broken by the catalog's own insertion order (so retrieval is
    deterministic and does not depend on dict hashing or an incidental sort order).

    Raises ``ValueError`` if ``catalog`` has fewer than ``k`` skills: retrieval cannot return
    more candidates than the catalog holds.
    """
    catalog = SKILL_CATALOG if catalog is None else catalog
    if k > len(catalog):
        raise ValueError(f"k={k} exceeds the catalog size ({len(catalog)} skills)")
    ids = list(catalog)
    ranked = sorted(ids, key=lambda sid: (-lexical_overlap(task, catalog[sid]), ids.index(sid)))
    return ranked[:k]


# -------------------------------------------------------------------------------- The question

# The relevance rubric, lowest level first. Each level is judged on its own against one
# (task, skill) pair ("Every level is evaluated separately. The model doesn't see a level's
# number or its neighbours, so 'worse than the previous level' means nothing to it.",
# https://docs.typesafe.ai/primitives), so every description stands alone: it says what the
# skill's own description states about this task, never "less suitable than the level above".
NOT_SUITABLE = (
    "The skill's description names a different kind of action, or a different kind of "
    "information, than what the task asks for. Nothing the description states would let this "
    "skill carry out the task."
)
RELATED = (
    "The skill's description names the same general area of work as the task, but it does not "
    "state that it performs the specific action, on the specific kind of thing, that the task "
    "asks for."
)
SUITABLE = (
    "The skill's description states that it performs the specific action the task asks for. "
    "The description may also cover other actions the task does not need, or may not name "
    "every secondary detail the task mentions."
)
IDEAL = (
    "The skill's description states that it performs the specific action the task asks for, "
    "and also names, by itself, the particular detail (the kind of item, the system, or the "
    "scope) that the task asks about."
)
SUITABILITY_LEVELS = (NOT_SUITABLE, RELATED, SUITABLE, IDEAL)  # level 0 to level 3
N_LEVELS = len(SUITABILITY_LEVELS)

# The business cutoff lives in code: a skill whose most likely level is below SUITABLE
# (level 2) does not state that it can perform the task, so Python never treats it as usable --
# whatever its score. This is a fixed editorial decision, not a value chosen by searching
# validation (unlike the margin threshold below), which is also why it is a plain module
# constant and not an argument.
BUSINESS_CUTOFF = 2

SELECT = "select"
REVIEW = "review"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one (task, skill) pair: the task description and one skill's own
    description, and nothing else.

    ``fields`` also carries ``task_id`` and ``skill_id``, both bookkeeping Python keeps for
    itself. Neither reaches the model; both are reattached to the outcome afterwards, so every
    decision still traces back to its task and the skill it was asked about.
    """
    return {"task": fields["task"], "skill": fields["skill"]}


def build_questions() -> dict[str, Score]:
    """The one question asked about every (task, skill) pair. The levels come from
    ``SUITABILITY_LEVELS``, built by Python."""
    return {
        "relevance": Score(
            instructions=(
                "How well does this skill's own description show that it can carry out this "
                "task? Judge only what this skill's description itself states, not what any "
                "other skill might do."
            ),
            criteria=list(SUITABILITY_LEVELS),
        )
    }


# --------------------------------------------------------------------------- Python's part


@dataclass(frozen=True)
class Judgment:
    """One scored candidate: the skill, its modal level, its expected score, and the answer's
    own ``confidence``. Built from a ``ScoreAnswer`` so the composition below never re-reads
    the answer object itself."""

    skill_id: str
    level: int
    score: float
    confidence: float


@dataclass(frozen=True)
class Selection:
    """What Python decided for one task: the top-ranked skill, its modal level and the
    normalized margin it won by, the outcome, and why."""

    task_id: str
    skill_id: str
    level: int
    margin: float
    outcome: str
    reason: str


def rank_judgments(judgments: list[Judgment]) -> list[Judgment]:
    """``judgments`` ordered by expected score, highest first. A tie is resolved by Python's
    sort being stable: it keeps whichever candidate came first in ``judgments``, which is
    retrieval order (the order :func:`retrieve_candidates` returned), never an incidental later
    reordering. Needs at least two judgments, because the margin below compares the top two.
    """
    if len(judgments) < 2:
        raise ValueError("rank_judgments needs at least two candidate judgments")
    return sorted(judgments, key=lambda j: -j.score)


# docs/glossary.md#review: "the reason string for a confidence-gated review is exactly
# 'confidence below the threshold'". That is a separate thing from the margin and the business
# cutoff below (neither of which reads an answer's own `.confidence`), so it gets the lexicon's
# exact words and nothing else does.
REASON_STRING = "confidence below the threshold"


def select_skill(
    task_id: str, judgments: list[Judgment], confidence_gate: float, margin_threshold: float
) -> Selection:
    """Select the top-ranked skill only when its own judgment is trustworthy, its score clears
    the business cutoff, *and* it clearly beats the runner-up; otherwise send the task to
    review so a person can clarify which skill is meant.

    Three independent conditions decide this, checked in this order, and each can send a task
    to review on its own:

    - **The confidence gate** (``confidence_gate``, chosen on validation and frozen): the top
      skill's own answer ``confidence`` -- how peaked its probability distribution over the
      four levels is, nothing to do with the other candidates -- must clear this gate. A
      spread-out distribution is not solid ground for acting on, whatever level it happens to
      peak at or how far ahead of the runner-up it scored.
    - **The business cutoff** (``BUSINESS_CUTOFF``, fixed): the top skill's modal level
      (:func:`jev_cookbook.evaluation.score_level`, ties going to the lower level) must be
      ``SUITABLE`` or better. A skill whose description does not even state that it can do
      the task is never selected.
    - **The margin** (``margin_threshold``, chosen on validation and frozen): the gap between
      the top skill's expected score and the runner-up's, normalized to 0-1 by dividing by
      ``N_LEVELS - 1`` (the largest a gap between two scores on this rubric can be), must clear
      ``margin_threshold``. This is the case the use case names explicitly: two skills whose
      descriptions both plausibly fit the task score close together, and picking either one
      without asking is a guess Python should not make automatically.

    The rule is code, so it holds whatever the model answers; it never asks Jev to compare
    skills itself. Raises ``ValueError`` if ``confidence_gate`` or ``margin_threshold`` is
    outside ``[0, 1]``.
    """
    if not 0.0 <= confidence_gate <= 1.0:
        raise ValueError(f"confidence_gate must be between 0 and 1, got {confidence_gate!r}")
    if not 0.0 <= margin_threshold <= 1.0:
        raise ValueError(f"margin_threshold must be between 0 and 1, got {margin_threshold!r}")
    top, runner_up = rank_judgments(judgments)[:2]
    margin = (top.score - runner_up.score) / (N_LEVELS - 1)
    if top.confidence < confidence_gate:
        return Selection(task_id, top.skill_id, top.level, margin, REVIEW, REASON_STRING)
    if top.level < BUSINESS_CUTOFF:
        return Selection(
            task_id,
            top.skill_id,
            top.level,
            margin,
            REVIEW,
            "the top skill's modal level is below the business cutoff",
        )
    if margin < margin_threshold:
        return Selection(
            task_id,
            top.skill_id,
            top.level,
            margin,
            REVIEW,
            "the margin between the top two skills is below the threshold",
        )
    return Selection(
        task_id, top.skill_id, top.level, margin, SELECT, "clearly the best-fitting skill"
    )


def gold_best_skills(gold_levels: dict[str, int]) -> frozenset[str]:
    """The skill id(s) a task's candidates agree are the best fit: whichever carry the
    highest gold relevance level among ``gold_levels`` (``{skill_id: level}``, this task's own
    retrieved candidates only). More than one id comes back exactly when two (or more) retrieved
    skills are tied at the top gold level -- the "two skills equally plausible" hard case the
    use case names -- so a selection naming either one counts as a correct top-1 pick.
    """
    if not gold_levels:
        raise ValueError("gold_levels must not be empty")
    best = max(gold_levels.values())
    return frozenset(skill_id for skill_id, level in gold_levels.items() if level == best)


def group_by_task_id(examples: list[Any]) -> dict[str, list[Any]]:
    """``examples`` (any objects with a ``.fields["task_id"]``) grouped by that task id,
    in first-seen order. Plain data plumbing, shared so the notebook and the tests never build
    this grouping two different ways."""
    groups: dict[str, list[Any]] = {}
    for example in examples:
        groups.setdefault(example.fields["task_id"], []).append(example)
    return groups


def pool_for_confidence_selection(
    judgments_by_task: dict[str, list[Judgment]], gold_best_by_task: dict[str, frozenset[str]]
) -> tuple[list[bool], list[float]]:
    """``(correct, confidence)`` pairs for :func:`select_confidence_gate`, one pair per task,
    from the top-ranked candidate's own answer confidence. Unlike
    :func:`pool_for_margin_selection`, this pool is never filtered by the business cutoff or
    the margin: the confidence gate is the first thing ``select_skill`` checks, before either
    of those, so every task's top judgment -- whatever its level or margin -- sets the bar for
    it.
    """
    correct, confidences = [], []
    for task_id, judgments in judgments_by_task.items():
        top = rank_judgments(judgments)[0]
        confidences.append(top.confidence)
        correct.append(top.skill_id in gold_best_by_task[task_id])
    return correct, confidences


# Both objectives below freeze the highest-accuracy cut-off among those that still answer at
# least this share of their own pool, rather than `target_accuracy=1.0` (CONTRIBUTING's rule
# 12 risk: a perfect-validation-accuracy target is true by construction and tells a reader
# nothing). Chosen, not derived -- a different value would freeze a different threshold, which
# is exactly why `tests/test_helpers.py` pins both constants and the fact that the two
# selectors below call `min_coverage=`, never `target_accuracy=`.
CONFIDENCE_MIN_COVERAGE = 0.5
MARGIN_MIN_COVERAGE = 0.5


def select_confidence_gate(correct: list[bool], confidence: list[float]) -> float:
    """The confidence gate to freeze, chosen on validation: the highest-accuracy cut-off among
    those with coverage at least ``CONFIDENCE_MIN_COVERAGE`` over ``(correct, confidence)``
    (see :func:`pool_for_confidence_selection`), ties going to the lower threshold (more
    coverage). A thin, named wrapper around
    :func:`jev_cookbook.evaluation.select_confidence_threshold` so the notebook and the tests
    call the exact same objective rather than each spelling out ``min_coverage=...`` by hand.
    """
    return select_confidence_threshold(correct, confidence, min_coverage=CONFIDENCE_MIN_COVERAGE)


def pool_for_margin_selection(
    judgments_by_task: dict[str, list[Judgment]], gold_best_by_task: dict[str, frozenset[str]]
) -> tuple[list[bool], list[float]]:
    """``(correct, margin)`` pairs for :func:`select_margin_threshold`, one pair per task whose
    top-ranked skill already clears ``BUSINESS_CUTOFF`` -- the same filter ``select_skill``
    applies before it ever looks at the margin, so only tasks the margin threshold could
    actually affect set the bar for it (the template's own pattern: "only an answer that names
    a queue can be routed automatically, so only those can set the bar."). A task whose top
    skill fails the business cutoff is left out entirely: it is sent to review for that reason
    alone, whatever the margin among its candidates happens to be. This pool is independent of
    the confidence gate -- chosen separately, from a pool filtered only by the one condition
    (the business cutoff) that the margin check itself sits behind, regardless of which gate a
    task is ultimately caught by when both are applied together in :func:`select_skill`.
    """
    correct, margins = [], []
    for task_id, judgments in judgments_by_task.items():
        top, runner_up = rank_judgments(judgments)[:2]
        if top.level < BUSINESS_CUTOFF:
            continue
        margins.append((top.score - runner_up.score) / (N_LEVELS - 1))
        correct.append(top.skill_id in gold_best_by_task[task_id])
    return correct, margins


def select_margin_threshold(correct: list[bool], margin: list[float]) -> float:
    """The margin threshold to freeze, chosen on validation: the highest-accuracy cut-off
    among those with coverage at least ``MARGIN_MIN_COVERAGE`` over ``(correct, margin)``
    (see :func:`pool_for_margin_selection`), ties going to the lower threshold (more
    coverage). A thin, named wrapper around
    :func:`jev_cookbook.evaluation.select_confidence_threshold` so the notebook and the tests
    call the exact same objective rather than each spelling out ``min_coverage=...`` by hand.
    """
    return select_confidence_threshold(correct, margin, min_coverage=MARGIN_MIN_COVERAGE)


def outcome_accounting(
    selections: list[Selection], gold_best_by_task: dict[str, frozenset[str]]
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``, built from a
    list of ``Selection`` results and ``gold_best_by_task`` (``{task_id: gold_best_skills(...)}``).

    ``accepted[i]`` is whether ``select_skill`` answered task ``i`` (outcome ``select``) rather
    than sending it to ``review``, exactly as the rule itself decided; ``correct[i]`` is whether
    the selected skill is one of the task's gold-best skills, computed for every task
    (``evaluate_outcomes`` requires a value even where ``accepted`` is ``False``, though it never
    reads it there). This is deliberately not ``jev_cookbook.evaluation.evaluate_selective``
    reapplied to every task: that helper gates every example on one confidence value alone, but
    ``select_skill`` checks three independent review branches -- the confidence gate, the
    business cutoff, and the margin -- and a task can be sent to review by either of the last
    two even once the first has already passed it.
    """
    if not selections:
        raise ValueError("outcome_accounting needs at least one selection")
    accepted = [s.outcome != REVIEW for s in selections]
    correct = [s.skill_id in gold_best_by_task[s.task_id] for s in selections]
    return accepted, correct
