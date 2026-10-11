"""Python's half of recipe 33: the state, the one Choice question, and the two-stage rule
that validates a proposed schema mapping.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.

Jev is asked, once per source field, which field of a fixed target schema it corresponds to
(or ``ambiguous``/``unmapped``). Python never asks Jev to compare two source fields or to see
a whole table at once: each source field is judged on its own, from its name, declared type
and description. Everything that needs the *whole* table -- whether a declared type is
compatible with the target it was mapped to, and whether two source fields were mapped to the
same target -- is arithmetic and set membership, so it stays in :func:`apply_one_to_one` and
the type check inside :func:`gate_field`, never in a request.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.


@dataclass(frozen=True)
class TargetField:
    """One field of the fixed target schema: its data type category and what it holds."""

    type: str
    description: str


# The target schema every source field is mapped against -- Marrowfield Mercantile's order and
# customer record, fabricated for this recipe (CONTRIBUTING.md section 5). Every option Jev can
# ever be offered comes from here, plus the two fallbacks below; Jev never invents a target name.
TARGET_SCHEMA: dict[str, TargetField] = {
    "customer_email": TargetField(
        "string",
        "The customer's email address, used for account contact and order receipts.",
    ),
    "customer_id": TargetField(
        "integer",
        "The internal numeric identifier assigned to the customer account.",
    ),
    "order_total": TargetField(
        "decimal",
        "The total monetary amount charged for the order, in the store's currency.",
    ),
    "order_date": TargetField(
        "date",
        "The calendar date the order was placed.",
    ),
    "loyalty_tier": TargetField(
        "string",
        "The customer's named loyalty-program tier, such as a membership level.",
    ),
    "shipping_country": TargetField(
        "string",
        "The country the order is being shipped to.",
    ),
    "product_sku": TargetField(
        "string",
        "The stock-keeping unit code identifying the exact product variant ordered.",
    ),
    "is_gift_order": TargetField(
        "boolean",
        "Whether the order was marked as a gift at checkout.",
    ),
}

# The two fallback outcomes the use case names (CONTRIBUTING.md section 3: "Include none,
# other, no_match, or uncertain outcomes when the use case calls for them"). AMBIGUOUS is a
# deferral: it asks a person to pick between candidates the description itself does not
# settle, so it always goes to review, whatever its confidence. UNMAPPED is a complete answer
# ("this source field has no place in the target schema"), so it is gated on confidence and
# the declared-type check like every real target, exactly as CONTRIBUTING.md section 4's
# three-part test allows -- and, like the template's own `none`, this recipe still gates it
# rather than claim the exemption.
AMBIGUOUS = "ambiguous"
UNMAPPED = "unmapped"

# A source export's own declared type names, folded to the fixed category vocabulary
# TARGET_SCHEMA.values() uses. This normalization is itself part of Python's validation: a
# legacy export's type names never match a target schema's spelling, so the comparison that
# matters is between categories, not between literal type strings.
SOURCE_TYPE_TO_CATEGORY: dict[str, str] = {
    "varchar": "string",
    "text": "string",
    "int": "integer",
    "numeric": "decimal",
    "bool": "boolean",
    "date": "date",
}

ACCEPTED = "accepted"
REVIEW = "review"

REASON_AMBIGUOUS = "the model found more than one target field equally plausible"
REASON_INVALID_OPTION = "not a known option"
REASON_LOW_CONFIDENCE = "confidence below the threshold"
REASON_TYPE_MISMATCH = "declared type does not match the target field's type"
REASON_CONFLICT = "one-to-one constraint violated"
REASON_UNMAPPED_ACCEPTED = "no target field fits the description"
REASON_MAPPED_ACCEPTED = "type compatible and confidence at or above the threshold"


def normalize_type(declared_type: str) -> str:
    """The fixed type category (``string``, ``integer``, ``decimal``, ``boolean``, ``date``)
    a source export's own declared type name folds to. Raises ``KeyError`` on a declared type
    this recipe's fixtures never use, rather than guessing a category for it."""
    return SOURCE_TYPE_TO_CATEGORY[declared_type]


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one source field: its name, its declared type, and the full
    description of what it actually contains -- nothing else.

    ``fields`` also carries ``task_id``, Python's own grouping of which source table a field
    came from. Python keeps it and attaches it to the outcome, so it never needs to pass
    through the model: Jev judges one field at a time and never sees the rest of its table, and
    the one-to-one constraint that needs the whole table is exactly what Python checks
    afterward, in :func:`apply_one_to_one`.
    """
    return {
        "field_name": fields["field_name"],
        "declared_type": fields["declared_type"],
        "description": fields["description"],
    }


def build_questions() -> dict[str, Choice]:
    """The one question asked about every source field. The options are built from
    ``TARGET_SCHEMA`` plus the two fallbacks, never typed out by hand twice."""
    criteria = {
        name: f"{name} ({target.type}): {target.description}"
        for name, target in TARGET_SCHEMA.items()
    }
    criteria[AMBIGUOUS] = (
        "The field's name and declared type together fit more than one of the target fields "
        "above equally well, and nothing in the description resolves which one; choose this "
        "only when the description itself leaves it open, not merely because the field name "
        "alone is unclear."
    )
    criteria[UNMAPPED] = (
        "No target field above corresponds to this source field at all; it has no place in "
        "the target schema, whatever its name or declared type suggest."
    )
    return {
        "target": Choice(
            instructions=(
                "A source field from a legacy export is described below by its field name, "
                "its declared data type, and a full description of what it actually contains. "
                "Which target schema field does it correspond to? Judge by the description, "
                "not by the field name alone: a field's name can be a misleading holdover from "
                "an older system or a column that was repurposed, but its description is "
                "accurate. Choose ambiguous only when the description itself fits more than "
                "one target field equally well, and unmapped when no target field corresponds "
                "to this source field at all."
            ),
            criteria=criteria,
        )
    }


@dataclass(frozen=True)
class FieldOutcome:
    """What Python decided for one source field: the model's raw choice, the outcome, the
    target it was finally accepted for (``None`` while under review, or ``UNMAPPED``), and why.

    ``task_id`` and ``field_name`` are carried through so a reviewer, or a later aggregation by
    task, never has to look the field back up elsewhere.
    """

    field_id: str
    task_id: str
    field_name: str
    choice: str
    outcome: str
    final_target: str | None
    reason: str


def gate_field(
    field_id: str,
    task_id: str,
    field_name: str,
    declared_type: str,
    answer: Any,
    min_confidence: float,
) -> FieldOutcome:
    """Decide one source field's outcome from its typed answer alone: confidence and declared-
    type compatibility, with no knowledge yet of any other field in its task.

    In order: ``ambiguous`` is an unconditional deferral, sent to review whatever its
    confidence (CONTRIBUTING.md section 4 part (a): it asks a person to decide, so it never
    counts as answered). An option outside the fixed set is rejected defensively, the same
    guard several other recipes' rules keep even though ``jev_cookbook`` already enforces a
    Choice's own option set at construction. A confidence below ``min_confidence`` goes to
    review next, before the type check even runs, because a type-compatible answer is no more
    trustworthy than an incompatible one when the model itself was unsure which option to
    pick. ``unmapped`` is then a complete, final answer at any remaining confidence -- it names
    no target to type-check. Only a real target field reaches the declared-type comparison:
    ``normalize_type(declared_type)`` must equal that target's own type, or the field is sent
    to review instead of being accepted into a schema it does not actually fit. This function
    never checks whether some *other* field in the same task was also mapped here; that is
    :func:`apply_one_to_one`'s job, run once every field in a task has reached an outcome here.
    The rule is code, so it holds whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == AMBIGUOUS:
        return FieldOutcome(
            field_id, task_id, field_name, answer.choice, REVIEW, None, REASON_AMBIGUOUS
        )
    if answer.choice != UNMAPPED and answer.choice not in TARGET_SCHEMA:
        return FieldOutcome(
            field_id, task_id, field_name, answer.choice, REVIEW, None, REASON_INVALID_OPTION
        )
    if answer.confidence < min_confidence:
        return FieldOutcome(
            field_id, task_id, field_name, answer.choice, REVIEW, None, REASON_LOW_CONFIDENCE
        )
    if answer.choice == UNMAPPED:
        return FieldOutcome(
            field_id,
            task_id,
            field_name,
            answer.choice,
            ACCEPTED,
            UNMAPPED,
            REASON_UNMAPPED_ACCEPTED,
        )
    target = TARGET_SCHEMA[answer.choice]
    if normalize_type(declared_type) != target.type:
        return FieldOutcome(
            field_id, task_id, field_name, answer.choice, REVIEW, None, REASON_TYPE_MISMATCH
        )
    return FieldOutcome(
        field_id,
        task_id,
        field_name,
        answer.choice,
        ACCEPTED,
        answer.choice,
        REASON_MAPPED_ACCEPTED,
    )


def apply_one_to_one(outcomes: list[FieldOutcome]) -> list[FieldOutcome]:
    """Enforce the one-to-one constraint across one task's fields: no two source fields may be
    accepted into the same real target field.

    Only fields :func:`gate_field` already accepted into a *real* target (not ``unmapped``,
    which many fields may legitimately share, since "no target fits" is not a target) compete
    for this check. Every target chosen by more than one field is a conflict: every field that
    proposed it is sent to review, not just one of them, because nothing in a per-field answer
    tells Python which proposal (if either) is right -- that is exactly the judgment a person
    reviewing the conflict is for. A field with no competitor passes through unchanged. Pass
    this only the outcomes of one task: fields from different tasks name independent target
    schemas and must never be checked against each other.
    """
    target_counts = Counter(
        o.final_target for o in outcomes if o.outcome == ACCEPTED and o.final_target != UNMAPPED
    )
    result = []
    for outcome in outcomes:
        if (
            outcome.outcome == ACCEPTED
            and outcome.final_target != UNMAPPED
            and target_counts[outcome.final_target] > 1
        ):
            result.append(
                replace(outcome, outcome=REVIEW, final_target=None, reason=REASON_CONFLICT)
            )
        else:
            result.append(outcome)
    return result


def compose_task(
    task_id: str,
    rows: list[tuple[str, str, str, Any]],
    min_confidence: float,
) -> list[FieldOutcome]:
    """The full, two-stage composition for one task: gate every field on its own answer, then
    enforce the one-to-one constraint across the whole task.

    ``rows`` is ``(field_id, field_name, declared_type, answer)`` for every source field of this
    one task, in any order. The notebook and the tests both call this (never a separate
    reimplementation of either stage), so there is exactly one place this recipe decides a
    mapping.
    """
    gated = [
        gate_field(field_id, task_id, field_name, declared_type, answer, min_confidence)
        for field_id, field_name, declared_type, answer in rows
    ]
    return apply_one_to_one(gated)


def rows_for_task(
    examples: Any, decisions: dict[str, Any]
) -> dict[str, list[tuple[str, str, str, Any]]]:
    """``{task_id: [(field_id, field_name, declared_type, answer), ...]}`` for every example in
    ``examples``, grouping each one's own batch together -- the shape :func:`compose_task`
    consumes. ``decisions`` maps each example's id to its typed answer.

    This is the one place a split's fields are grouped into the batches the one-to-one
    constraint checks them within; the notebook and ``tests/test_helpers.py`` both call it (and
    :func:`compose_split` below), rather than each keeping its own copy of the grouping, because
    a grouping bug (an example attributed to the wrong batch, or every example merged into one)
    would otherwise be invisible to a test that never calls the code it is meant to guard.
    """
    by_task: dict[str, list[tuple[str, str, str, Any]]] = {}
    for example in examples:
        fields = example.fields
        by_task.setdefault(fields["task_id"], []).append(
            (example.id, fields["field_name"], fields["declared_type"], decisions[example.id])
        )
    return by_task


def compose_split(
    examples: Any, decisions: dict[str, Any], min_confidence: float
) -> list[FieldOutcome]:
    """:func:`compose_task` applied to every batch among ``examples``, in task-id order -- the
    one place this recipe composes a whole split's worth of fields. The notebook and
    ``tests/test_helpers.py`` both call this function, never a separate reimplementation of the
    grouping or the composition, so a change to either stays visible to both at once.
    """
    outcomes = []
    for task_id, rows in sorted(rows_for_task(examples, decisions).items()):
        outcomes.extend(compose_task(task_id, rows, min_confidence))
    return outcomes


def field_accepted_and_correct(
    outcomes: list[FieldOutcome], gold: dict[str, Any]
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``, at the field
    (per-question) level: ``accepted[i]`` is whether the field's outcome is ``accepted`` rather
    than sent to review, and ``correct[i]`` is whether its final target equals the field's gold
    label (ignored, but still computed, where ``accepted[i]`` is ``False``, exactly as
    ``evaluate_outcomes`` documents)."""
    accepted = [o.outcome == ACCEPTED for o in outcomes]
    correct = [o.final_target == gold[o.field_id] for o in outcomes]
    return accepted, correct


def task_accepted_and_correct(
    outcomes: list[FieldOutcome], gold: dict[str, Any]
) -> tuple[list[str], list[bool], list[bool]]:
    """``(task_ids, accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``, at
    the task level: a task counts as ``accepted`` only when every one of its fields was
    individually accepted (nothing in it needs a person), and as ``correct`` only when every
    one of its fields' final target also equals that field's gold label -- the whole proposed
    mapping for that table, not just one field of it. ``task_ids`` is returned sorted, so the
    two boolean lists have a stable, reproducible order to zip against.
    """
    by_task: dict[str, list[FieldOutcome]] = defaultdict(list)
    for outcome in outcomes:
        by_task[outcome.task_id].append(outcome)
    task_ids = sorted(by_task)
    accepted = [all(o.outcome == ACCEPTED for o in by_task[t]) for t in task_ids]
    correct = [all(o.final_target == gold[o.field_id] for o in by_task[t]) for t in task_ids]
    return task_ids, accepted, correct


def conflict_count(outcomes: list[FieldOutcome]) -> int:
    """How many fields, among ``outcomes``, were sent to review because of the one-to-one
    constraint specifically (as opposed to ambiguity, low confidence, or a type mismatch)."""
    return sum(1 for o in outcomes if o.reason == REASON_CONFLICT)


def submit_reviews(queue: Any, outcomes: list[FieldOutcome], answers: dict[str, Any]) -> None:
    """Submit every ``review`` outcome in ``outcomes`` to ``queue``, in order; skip every
    ``accepted`` one. This recipe's one simulated side effect (CONTRIBUTING.md section 4):
    nothing here changes a schema or applies a mapping, it only queues the field for a person
    to look at, with the model's raw choice and the reason attached so a reviewer has context.
    ``answers`` maps each field's id to its typed answer, so the queued item can show it.
    """
    for outcome in outcomes:
        if outcome.outcome == REVIEW:
            queue.submit(
                {
                    "field_id": outcome.field_id,
                    "task_id": outcome.task_id,
                    "field_name": outcome.field_name,
                    "choice": outcome.choice,
                },
                outcome.reason,
                answer=answers[outcome.field_id].to_dict(),
            )
