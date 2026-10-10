"""Python's half of recipe 24: the state, the two Score questions, the fixed category and
priority mappings, and the rule that gates and composes them.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Score
from jev_cookbook.evaluation import score_level

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# Business impact rubric, lowest level first. Every level is evaluated on its own against the
# incident report ("Every level is evaluated separately. The model doesn't see a level's number
# or its neighbours, so 'worse than the previous level' means nothing to it.",
# https://docs.typesafe.ai/primitives/score), so each description stands alone: it names the
# scope of the effect on customers and operations, never "bigger than the level above".
IMPACT_MINOR = (
    "The effect is contained to a small number of customers or to one non-critical feature; "
    "core operations, revenue and data are unaffected."
)
IMPACT_MODERATE = (
    "A noticeable but partial segment of customers, or one feature many customers rely on, is "
    "degraded; there is some effect on revenue or operations, but most customers are unaffected."
)
IMPACT_MAJOR = (
    "A core feature is broken or unavailable, or a large share of customers cannot complete "
    "what they came to do, with a clear effect on revenue, operations or customer trust."
)
IMPACT_CRITICAL = (
    "The whole customer base or a core system is affected outright, with severe effect on "
    "revenue, data integrity, safety, or legal or regulatory exposure."
)
IMPACT_LEVELS = (IMPACT_MINOR, IMPACT_MODERATE, IMPACT_MAJOR, IMPACT_CRITICAL)  # level 0 to 3
IMPACT_CATEGORIES = ("minor", "moderate", "major", "critical")  # the named category per level

# Urgency rubric: how quickly a response is needed, a different question from how severe the
# incident is. Level 0 ("minor" impact) and level 0 here ("low" urgency) name unrelated things
# that merely share a number; a ticket's urgency and its business impact are judged from the
# same report text by two independent questions, and either can land on any level regardless
# of where the other one lands.
URGENCY_LOW = (
    "There is no deadline pressure: the incident can be scheduled into normal work with no "
    "special handling."
)
URGENCY_MEDIUM = (
    "A response is expected within the current work week; nothing described is actively "
    "getting worse while it waits."
)
URGENCY_HIGH = (
    "A response is expected within hours: the situation described is actively worsening, or a "
    "deadline is close."
)
URGENCY_CRITICAL = (
    "A response is needed immediately: the situation described is worsening by the minute, or "
    "a hard deadline has already passed or is minutes away."
)
URGENCY_LEVELS = (URGENCY_LOW, URGENCY_MEDIUM, URGENCY_HIGH, URGENCY_CRITICAL)  # level 0 to 3
URGENCY_CATEGORIES = ("low", "medium", "high", "critical")  # the named category per level

# The service-priority matrix: a fixed lookup from (impact category, urgency category) to the
# priority an on-call process assigns. It is data, not a formula spelled out in prose, so every
# cell can be read, tested and changed on its own; no level-dependent arithmetic runs on the
# model's own output, only this table lookup. P1 is the most severe, P4 the least.
PRIORITY_MATRIX: dict[tuple[str, str], str] = {
    ("minor", "low"): "P4",
    ("minor", "medium"): "P4",
    ("minor", "high"): "P3",
    ("minor", "critical"): "P3",
    ("moderate", "low"): "P4",
    ("moderate", "medium"): "P3",
    ("moderate", "high"): "P3",
    ("moderate", "critical"): "P2",
    ("major", "low"): "P3",
    ("major", "medium"): "P3",
    ("major", "high"): "P2",
    ("major", "critical"): "P1",
    ("critical", "low"): "P3",
    ("critical", "medium"): "P2",
    ("critical", "high"): "P1",
    ("critical", "critical"): "P1",
}

ACCEPTED = "accepted"
REVIEW = "review"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one incident ticket: the report text, and nothing else.

    ``fields`` also carries ``ticket_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the outcome itself, so it never passes through the model.
    """
    return {"report": fields["report"]}


def build_questions() -> dict[str, Score]:
    """The two questions asked about every ticket, in one request: business impact and
    urgency, each against its own four-level rubric built from the constants above."""
    return {
        "business_impact": Score(
            instructions=(
                "How much business impact does this incident have on customers and operations?"
            ),
            criteria=list(IMPACT_LEVELS),
        ),
        "urgency": Score(
            instructions="How urgently does this incident need a response?",
            criteria=list(URGENCY_LEVELS),
        ),
    }


@dataclass(frozen=True)
class Composition:
    """The deterministic composition of two Score answers: each answer's modal level and named
    category, and the priority ``PRIORITY_MATRIX`` assigns to that pair of categories.
    ``Composition`` holds no confidence and makes no review decision; :func:`compose_priority`
    adds that on top of it."""

    impact_level: int
    impact_category: str
    urgency_level: int
    urgency_category: str
    priority: str


def categorize(impact_answer: Any, urgency_answer: Any) -> Composition:
    """Map two Score answers to their named categories and the matrix's priority for that pair.

    Uses each answer's modal level (:func:`score_level`, ties going to the lower level), never
    its expected ``score``, because both the categories and the matrix are defined over whole
    levels, not a continuous position between them. Deterministic: the same pair of modal levels
    always gives the same ``Composition``, and every cell of ``PRIORITY_MATRIX`` is reachable by
    some pair of levels.
    """
    impact_level = score_level(impact_answer)
    urgency_level = score_level(urgency_answer)
    impact_category = IMPACT_CATEGORIES[impact_level]
    urgency_category = URGENCY_CATEGORIES[urgency_level]
    priority = PRIORITY_MATRIX[(impact_category, urgency_category)]
    return Composition(impact_level, impact_category, urgency_level, urgency_category, priority)


def gate_confidence(impact_answer: Any, urgency_answer: Any) -> float:
    """The one confidence value the rule's gate actually compares to a threshold: the weaker of
    the two questions' own Score confidence. A ticket goes to review when *either* answer is
    below the threshold, which is exactly what comparing this minimum once decides."""
    return min(impact_answer.confidence, urgency_answer.confidence)


@dataclass(frozen=True)
class Outcome:
    """What Python decided for one ticket: the composition (always computed, even for a
    deferred ticket, so a reviewer has context) and the outcome Python takes it to."""

    ticket_id: str
    composition: Composition
    outcome: str
    reason: str


def compose_priority(
    ticket_id: str, impact_answer: Any, urgency_answer: Any, min_confidence: float
) -> Outcome:
    """Act on one ticket's two Score answers: gate on confidence, then apply the fixed matrix.

    Both answers must be confident enough to trust before the matrix result is reported as a
    final priority: if either answer's confidence is below ``min_confidence``
    (:func:`gate_confidence`), the ticket goes to an explicit ``review`` outcome, whatever
    categories the model named, because a spread-out distribution on *either* question is not
    solid ground for a priority call. At or above the gate, the rule reports the matrix's
    priority for the two modal categories. The rule is code, so it holds whatever the model
    answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    composition = categorize(impact_answer, urgency_answer)
    if gate_confidence(impact_answer, urgency_answer) < min_confidence:
        return Outcome(ticket_id, composition, REVIEW, "confidence below the threshold")
    return Outcome(ticket_id, composition, ACCEPTED, "priority matrix applied")


def compose_split(examples: Any, decisions: dict[str, Any], min_confidence: float) -> list[Outcome]:
    """:func:`compose_priority` applied to every example of one split, in order.

    ``examples`` is a sequence of fixture examples (each with an ``.id``) and ``decisions`` maps
    each example's id to its ``(impact_answer, urgency_answer)`` pair. The notebook calls this
    once per split and so does ``tests/test_helpers.py``, so there is exactly one place this
    recipe decides what happens to a ticket's two answers.
    """
    return [compose_priority(e.id, *decisions[e.id], min_confidence) for e in examples]


def submit_reviews(
    queue: Any, examples: Any, decisions: dict[str, Any], results: list[Outcome]
) -> None:
    """Submit every ``review`` outcome in ``results`` to ``queue``, in order; skip every
    ``accepted`` one. ``results`` must align with ``examples`` (the output of
    :func:`compose_split` on the same two arguments does). This is this recipe's one simulated
    side effect (CONTRIBUTING.md section 4): nothing here changes a ticket, it only queues it for
    a person to look at, with the composed categories and both Score answers attached so a
    reviewer has context. The notebook calls this once per split, into the same queue, so a
    ticket from either split that needed review ends up findable in one place; the tests call it
    the same way, so a change to what gets queued shows up in both without being re-typed twice.
    """
    for example, result in zip(examples, results, strict=True):
        if result.outcome == REVIEW:
            queue.submit(
                {
                    "ticket_id": example.id,
                    "impact_category": result.composition.impact_category,
                    "urgency_category": result.composition.urgency_category,
                },
                result.reason,
                answer={
                    "business_impact": decisions[example.id][0].to_dict(),
                    "urgency": decisions[example.id][1].to_dict(),
                },
            )
