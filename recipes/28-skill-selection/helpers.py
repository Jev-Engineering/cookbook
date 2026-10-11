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
from jev_cookbook.evaluation import score_level, select_confidence_threshold

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
        "on", "or", "our", "please", "s", "that", "the", "this", "to", "up", "want", "we",
        "what", "when", "will", "with", "you", "your",
    }
)  # fmt: skip
# "s" is in the stopword list on purpose: the word regex has no apostrophe handling, so a
# possessive like "request's" tokenizes into "request" and the bare letter "s". Left out of
# the stopword list, that bare "s" token would match the same bare "s" split out of every other
# possessive in the catalog (several skill descriptions have one), crediting retrieval with an
# overlap point neither task actually earned.


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
    """One scored candidate: the skill, its modal level, and its expected score. Built from a
    ``ScoreAnswer`` so the composition below never re-reads the answer object itself."""

    skill_id: str
    level: int
    score: float


def judgment_from_answer(skill_id: str, answer: Any) -> Judgment:
    """A :class:`Judgment` for one candidate, read from its own ``ScoreAnswer`` (or anything
    duck-typed the same way): ``skill_id`` plus the answer's modal level
    (:func:`jev_cookbook.evaluation.score_level`) and its expected ``score``. Every call site
    that builds a ``Judgment`` from a real answer -- the notebook's several evaluation cells and
    the tests -- calls this one function, so the two fields can never be read from the answer
    two different ways.
    """
    return Judgment(skill_id, score_level(answer), answer.score)


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


# Why this rule has two review branches, not three. This rule has no third, separate check on
# each top answer's own Score `.confidence` (the reason a review would carry, had it fired:
# "confidence below the threshold" -- the lexicon's exact words for a confidence-gated review,
# docs/glossary.md#review) -- not because a `Score` recipe never needs one (it can, and most of
# this cookbook's recipes do), but because, specifically on this recipe's own committed
# fixtures, with the margin threshold this recipe actually freezes, one could not do useful
# work. This is a measured property of this fixture set and this frozen threshold, not a
# property of the rubric or of `Score` answers in general; a different recipe, or a
# differently-drawn set of tasks for this one, could easily need the gate back.
#
# The measurement: at the frozen margin threshold, every task this rule auto-selects (never
# reviewed) on `validation` and `test` combined ranges from confidence 0.19 up to 0.78. Exactly
# two of those selections are wrong (`v22`, `t05`), and both sit at 0.78 -- the top of that
# range, tied with two genuinely correct selections there too (`v01`, `t01`). That is the
# highest confidence among auto-selected tasks' own top answers, not the highest confidence of
# any stored answer anywhere: `t05`'s own `doc_search` candidate, never selected, scores higher
# still, at 0.92. Any gate at or below 0.78 keeps both mistakes in the auto-selected set, since
# confidence alone does not distinguish them from the correct answers tied with them there; the
# only gate that excludes the mistakes is one set strictly above 0.78, and that gate excludes
# every other selection this rule gets right too. On these fixtures, a confidence gate can only
# cost coverage -- it cannot reduce risk, because the mistakes are not distinguishable by
# confidence from the correct answers they are tied with. `tests/test_helpers.py` checks this
# measurement directly, per split
# (``test_no_confidence_gate_could_have_caught_the_wrong_selections_without_also_losing_correct_ones``),
# so a future fixture edit that changes it is caught rather than leaving this comment stale.
def select_skill(task_id: str, judgments: list[Judgment], margin_threshold: float) -> Selection:
    """Select the top-ranked skill only when its score clears the business cutoff *and* it
    clearly beats the runner-up; otherwise send the task to review so a person can clarify
    which skill is meant.

    Two independent conditions decide this, checked in this order, and each can send a task to
    review on its own:

    - **The business cutoff** (``BUSINESS_CUTOFF``, fixed): the top skill's modal level
      (:func:`jev_cookbook.evaluation.score_level`, ties going to the lower level) must be
      ``SUITABLE`` or better. A skill whose description does not even state that it can do
      the task is never selected, however far ahead of the runner-up it scored.
    - **The margin** (``margin_threshold``, chosen on validation and frozen): the gap between
      the top skill's expected score and the runner-up's, normalized to 0-1 by dividing by
      ``N_LEVELS - 1`` (the largest a gap between two scores on this rubric can be), must clear
      ``margin_threshold``. This is the case the use case names explicitly: two skills whose
      descriptions both plausibly fit the task score close together, and picking either one
      without asking is a guess Python should not make automatically.

    The rule is code, so it holds whatever the model answers; it never asks Jev to compare
    skills itself. Raises ``ValueError`` if ``margin_threshold`` is outside ``[0, 1]``.
    """
    if not 0.0 <= margin_threshold <= 1.0:
        raise ValueError(f"margin_threshold must be between 0 and 1, got {margin_threshold!r}")
    top, runner_up = rank_judgments(judgments)[:2]
    margin = (top.score - runner_up.score) / (N_LEVELS - 1)
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


# The objective below freezes the highest-accuracy cut-off among those that still answer at
# least this share of the margin pool, rather than `target_accuracy=1.0`: a perfect-
# validation-accuracy target is true by construction here (the pool has a feasible threshold
# that clears every wrong example) and would tell a reader nothing about the trade-off
# actually made. Chosen, not derived -- a different value would freeze a different threshold,
# which is exactly why `tests/test_helpers.py` pins this constant and the fact that
# `select_margin_threshold` calls `min_coverage=`, never `target_accuracy=`.
MARGIN_MIN_COVERAGE = 0.5


def is_safe_auto_answer(skill_id: str, gold_best: frozenset[str]) -> bool:
    """Whether auto-answering with ``skill_id`` was *safe* for the margin threshold to have
    allowed: true only when ``gold_best`` names exactly one skill and ``skill_id`` is it.

    This is stricter than "is the pick acceptable" (:func:`gold_best_skills` can legitimately
    name more than one skill -- the "two skills equally plausible" hard case -- and a
    selection naming either one is a correct *top-1 pick*, scored that way everywhere else in
    this recipe, including :func:`outcome_accounting`). For *choosing* the margin threshold
    specifically, that permissive view is the wrong question: a threshold loose enough to
    auto-answer a genuinely tied task is not vindicated by one of the two guesses landing
    acceptably -- the point of the margin check is to not guess on a task like that at all.
    Scoring a tied task as a success here would give the threshold search no reason to ever
    raise the bar above a razor-thin margin, so this pools a tied task as unsafe regardless of
    which retrieved skill happened to rank first.

    A tie is not always the "two skills equally plausible" hard case specifically: v03 and t03
    tie all three of their retrieved skills at the same gold level too, but at a *low* one
    (every retrieved skill is merely related, none actually suitable) -- "equally mediocre",
    not "equally excellent". ``gold_best_skills`` cannot tell the two shapes apart; both read
    as a tie. It happens not to matter here, because ``pool_for_margin_selection`` already
    drops a task that fails the business cutoff before this function is ever asked about it,
    so v03/t03's own tie is never read -- but a future recipe reusing this pattern with a
    cutoff that lets a low tie through would need to tell the two shapes apart explicitly.
    """
    return len(gold_best) == 1 and skill_id in gold_best


def pool_for_margin_selection(
    judgments_by_task: dict[str, list[Judgment]], gold_best_by_task: dict[str, frozenset[str]]
) -> tuple[list[bool], list[float]]:
    """``(safe, margin)`` pairs for :func:`select_margin_threshold`, one pair per task whose
    top-ranked skill already clears ``BUSINESS_CUTOFF`` -- the same filter ``select_skill``
    applies before it ever looks at the margin, so only a task the margin threshold could
    actually affect sets the bar for it (the template's own pattern: "only an answer that
    names a queue can be routed automatically, so only those can set the bar."). A task whose
    top skill fails the business cutoff is left out entirely: it is sent to review for that
    reason alone, whatever the margin among its candidates happens to be. ``safe`` comes from
    :func:`is_safe_auto_answer`, not the permissive ``gold_best_skills`` membership check --
    see that function's docstring for why the margin pool needs the stricter one.
    """
    safe, margins = [], []
    for task_id, judgments in judgments_by_task.items():
        top, runner_up = rank_judgments(judgments)[:2]
        if top.level < BUSINESS_CUTOFF:
            continue
        margins.append((top.score - runner_up.score) / (N_LEVELS - 1))
        safe.append(is_safe_auto_answer(top.skill_id, gold_best_by_task[task_id]))
    return safe, margins


def select_margin_threshold(safe: list[bool], margin: list[float]) -> float:
    """The margin threshold to freeze, chosen on validation: the highest-accuracy cut-off
    among those with coverage at least ``MARGIN_MIN_COVERAGE`` over ``(safe, margin)`` (see
    :func:`pool_for_margin_selection`), ties going to the lower threshold (more coverage). A
    thin, named wrapper around :func:`jev_cookbook.evaluation.select_confidence_threshold` --
    which reads its first argument as "was this example right", so here it reads as "was
    auto-answering this example safe" -- so the notebook and the tests call the exact same
    objective rather than each spelling out ``min_coverage=...`` by hand.
    """
    return select_confidence_threshold(safe, margin, min_coverage=MARGIN_MIN_COVERAGE)


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
    ``select_skill`` checks two independent review branches -- the business cutoff and the
    margin -- and a task can be sent to review by either one once the other has already
    passed it. ``correct`` here uses the permissive ``gold_best_skills`` membership check
    (either tied skill counts as a correct top-1 pick), unlike :func:`pool_for_margin_selection`,
    which uses the stricter :func:`is_safe_auto_answer` for choosing the threshold itself.
    """
    if not selections:
        raise ValueError("outcome_accounting needs at least one selection")
    accepted = [s.outcome != REVIEW for s in selections]
    correct = [s.skill_id in gold_best_by_task[s.task_id] for s in selections]
    return accepted, correct
