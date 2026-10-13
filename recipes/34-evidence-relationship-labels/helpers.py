"""Python's half of recipe 34: the state, the question and the two-stage rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.

Design in one paragraph: a knowledge-graph candidate is one ordered entity pair
(``entity_a``, ``entity_b``) together with one or more evidence passages someone retrieved for
that pair. For every passage, Jev answers one independent ``Choice``: which of a fixed set of
relationship types the passage itself states holds between the two entities, with
``no_supported_relation`` as the fallback when the passage does not settle it -- the question is
always about what *this passage* says, never about whether the relation is true in the world.
Python gates each passage decision on confidence (:func:`classify_passage`), then composes every
passage decision for one entity pair into a single task-level label with
:func:`compose_relation`: the one function this recipe's deterministic rule lives in, and the
one place its two review branches -- a passage below the confidence gate, or two confident
passages naming different relations -- are applied.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed relationship types this knowledge graph allows, plus the fallback outcome the use
# case names for a passage that does not state any of them. Order is fixed and meaningful (the
# order Jev sees the options in, and the order this file lists them), with the fallback last, as
# every other recipe's own "none"-shaped option is.
WORKS_FOR = "works_for"
FOUNDER_OF = "founder_of"
ACQUIRED_BY = "acquired_by"
SUPPLIER_OF = "supplier_of"
NO_SUPPORTED_RELATION = "no_supported_relation"
RELATIONS: tuple[str, ...] = (WORKS_FOR, FOUNDER_OF, ACQUIRED_BY, SUPPLIER_OF)
OPTIONS: tuple[str, ...] = (*RELATIONS, NO_SUPPORTED_RELATION)

# Each description is directional and names both entity roles explicitly, so the same wording
# is literally true whichever two names ``entity_a``/``entity_b`` hold for a given example.
_DESCRIPTIONS = {
    WORKS_FOR: (
        "The passage states that entity_a is an employee of, or works for, entity_b -- for "
        "example naming a role, a job, or a period of employment at entity_b."
    ),
    FOUNDER_OF: (
        "The passage states that entity_a founded, started, or co-founded entity_b -- not "
        "merely that entity_a currently works there or sits on its board."
    ),
    ACQUIRED_BY: (
        "The passage states that entity_b acquired, bought, or took over entity_a, so that "
        "entity_a was acquired by entity_b."
    ),
    SUPPLIER_OF: (
        "The passage states that entity_a supplies goods, materials, or services that "
        "entity_b uses -- entity_a is a supplier of entity_b."
    ),
    NO_SUPPORTED_RELATION: (
        "The passage does not state any of the relationships above holding between entity_a "
        "and entity_b. This covers a passage that is silent on how they relate, one that only "
        "places them in the same setting (an event, an industry, a report) without relating "
        "them, and one that describes some other kind of connection between them (such as a "
        "board seat, a rivalry, or an unconfirmed report) that is not one of the relationships "
        "above."
    ),
}

ACCEPTED = "accepted"
REVIEW = "review"
REASON_GATE = "confidence below the threshold"
REASON_DISAGREE = "evidence passages disagree on the relation"

# The objective the confidence gate is selected by, and its keyword: the notebook calls
# jev_cookbook.evaluation.select_confidence_threshold(val_correct, val_confidence,
# min_coverage=MIN_COVERAGE) on the per-passage (per-question) validation decisions, never
# target_accuracy (CONTRIBUTING.md's guidance against forcing validation accuracy to 1.0 by
# construction). Pinned here, in one place, so the notebook and tests/test_helpers.py cannot
# silently drift onto different objectives.
MIN_COVERAGE = 0.85


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one (entity pair, passage) question: the two entity names and the
    passage text, and nothing else.

    ``fields`` also carries ``pair_id`` and ``passage_id``, bookkeeping identifiers Python keeps
    for itself and attaches to the outcome afterwards; neither passes through the model.
    """
    return {
        "entity_a": fields["entity_a"],
        "entity_b": fields["entity_b"],
        "passage": fields["passage"],
    }


def build_questions() -> dict[str, Choice]:
    """The one question asked about every (entity pair, passage): which relationship, if any,
    this passage states holds between ``entity_a`` and ``entity_b``. The options come from
    ``OPTIONS``, built by Python and carried through to the output unchanged."""
    return {
        "relation": Choice(
            instructions=(
                "Which relationship, if any, does this passage state holds between entity_a "
                "and entity_b? Judge only what the passage itself says, not what you may know "
                "or guess about the two entities from elsewhere."
            ),
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


@dataclass(frozen=True)
class PassageDecision:
    """What Python decided for one evidence passage: the label Jev chose, its confidence, and
    whether the confidence gate accepts it or sends it to review."""

    passage_id: str
    label: str
    confidence: float
    outcome: str
    reason: str


def classify_passage(passage_id: str, answer: Any, min_confidence: float) -> PassageDecision:
    """Gate one passage's ``Choice`` answer on confidence alone.

    Every option in ``OPTIONS`` -- ``no_supported_relation`` included -- is a label Python is
    willing to report for a single passage, so a passage decision has only one review branch:
    confidence below ``min_confidence``. (The *disagreement* branch belongs to
    :func:`compose_relation`, once more than one passage is on the table; a lone passage cannot
    disagree with itself.) The rule is code, so it holds whatever the model answers, and
    ``passage_id`` passes through unchanged on both outcomes.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    confidence = float(answer.confidence)
    if confidence < min_confidence:
        return PassageDecision(passage_id, answer.choice, confidence, REVIEW, REASON_GATE)
    return PassageDecision(passage_id, answer.choice, confidence, ACCEPTED, "confident match")


@dataclass(frozen=True)
class TaskOutcome:
    """Python's composed, task-level decision for one entity pair: the label (``None`` when the
    pair goes to review), the reason, the evidence passage ids the label is attached to (empty
    when the pair goes to review), and every passage decision it was composed from, so a reader
    or a reviewer can see the whole evidence bundle."""

    pair_id: str
    label: str | None
    outcome: str
    reason: str
    evidence: tuple[str, ...]
    decisions: tuple[PassageDecision, ...]


def compose_relation(pair_id: str, decisions: tuple[PassageDecision, ...]) -> TaskOutcome:
    """Compose every passage decision for one entity pair into a single task-level label.

    This is the one rule this recipe enforces whatever the model answers, and the only place
    more than one passage's decision is combined. In order:

    1. Any passage gated by the confidence gate (:func:`classify_passage`) sends the whole pair
       to ``review``: a reviewer, not a forced guess, decides a pair Python is not confident
       enough about on even one piece of evidence, whichever way its own label reads.
    2. Otherwise, collect the distinct real relationship types (``RELATIONS``, excluding
       ``no_supported_relation``) named by the accepted passages. More than one distinct
       relationship means the evidence disagrees, so the pair goes to ``review`` rather than
       Python silently preferring one passage over another. Exactly one relationship -- named by
       one or every accepted passage -- is reported as the pair's label, attached to every
       passage that named it. Zero relationships (every accepted passage named
       ``no_supported_relation``) reports ``no_supported_relation`` itself, attached to every
       accepted passage.

    Args:
        pair_id: The entity pair's own identifier.
        decisions: Every passage decision for this pair, in a fixed order (the order the notebook
            asked them), non-empty.

    Returns:
        A :class:`TaskOutcome`.
    """
    if not decisions:
        raise ValueError("compose_relation needs at least one passage decision")
    if any(d.outcome == REVIEW for d in decisions):
        return TaskOutcome(pair_id, None, REVIEW, REASON_GATE, (), decisions)
    named = sorted({d.label for d in decisions if d.label != NO_SUPPORTED_RELATION})
    if len(named) > 1:
        return TaskOutcome(pair_id, None, REVIEW, REASON_DISAGREE, (), decisions)
    if len(named) == 1:
        label = named[0]
    else:
        label = NO_SUPPORTED_RELATION
    evidence = tuple(d.passage_id for d in decisions if d.label == label)
    return TaskOutcome(pair_id, label, ACCEPTED, "composed from its evidence", evidence, decisions)


def passage_states(fields: dict[str, Any]):
    """Yield ``(passage_id, state)`` for every evidence passage in one task's ``fields``, in
    the fixed order the notebook (and the fixture generator) asks them in. A single place both
    read ``fields["passages"]`` from, so the field shape cannot drift between them."""
    for passage in fields["passages"]:
        passage_fields = {
            "entity_a": fields["entity_a"],
            "entity_b": fields["entity_b"],
            "passage": passage["text"],
        }
        yield passage["passage_id"], build_state(passage_fields)


def queue_item(pair_id: str, fields: dict[str, Any], outcome: TaskOutcome) -> dict[str, Any]:
    """What a human reviewer sees for one queued entity pair: its id, the two entity names, and
    every passage decision ``outcome`` was composed from -- not only an identifier
    (CONTRIBUTING.md section 4: the queue is the side effect a ``review`` outcome triggers, and
    an item with nothing to read is not something a person can actually review)."""
    return {
        "pair_id": pair_id,
        "entity_a": fields["entity_a"],
        "entity_b": fields["entity_b"],
        "decisions": [
            {
                "passage_id": d.passage_id,
                "label": d.label,
                "confidence": d.confidence,
                "outcome": d.outcome,
            }
            for d in outcome.decisions
        ],
    }


def submit_reviews(queue: Any, examples: Any, outcomes: dict[str, TaskOutcome]) -> None:
    """Submit every ``review`` task outcome in ``outcomes`` to ``queue``, in example order; skip
    every ``accepted`` one.

    This is this recipe's one simulated side effect (CONTRIBUTING.md section 4): nothing here
    changes the knowledge graph, it only queues the entity pair for a person to look at, with
    every passage decision attached so a reviewer has context. The notebook calls this once per
    split, into the same queue, so a pair from either split that needed review ends up findable
    in one place.
    """
    for example in examples:
        outcome = outcomes[example.id]
        if outcome.outcome == REVIEW:
            queue.submit(
                queue_item(example.id, example.fields, outcome),
                outcome.reason,
                answer={
                    d.passage_id: {"label": d.label, "confidence": d.confidence}
                    for d in outcome.decisions
                },
            )


def passage_gold(label_record: dict[str, Any], passage_id: str) -> str:
    """The gold label for one passage inside a task's label record (``{"task": ..., "passages":
    {passage_id: label}}``), read directly rather than derived from the task-level gold -- every
    passage's gold is its own independently authored fact, even when several passages share a
    task."""
    return label_record["passages"][passage_id]


def task_gold(label_record: dict[str, Any]) -> str:
    """The gold label for one task's composed, pair-level relationship, read directly from the
    label record rather than recomputed from the passages' own gold labels."""
    return label_record["task"]
