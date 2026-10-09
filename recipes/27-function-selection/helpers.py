"""Python's half of recipe 27: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

import re
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice
from jev_cookbook.fixtures import stable_shuffle
from jev_cookbook.simulation import ActionLog, ReviewQueue

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The seed key every per-item shuffle below is derived from: ``f"{RECIPE_SLUG}:{item_id}"``
# (docs/fixtures.md, "Per-item option order"). This is the recipe folder's own slug, not a
# citation of anything private.
RECIPE_SLUG = "27-function-selection"

# --------------------------------------------------------------------------------------------
# The preapproved catalog. Six fabricated functions, each with a one-line description and an
# argument schema: every argument is typed, marked required or optional, and an "enum" argument
# also carries the fixed set of values it accepts. This is the complete list of actions Jev may
# ever be offered -- nothing it answers can add a seventh one, and nothing in this dict is ever
# mutated after module load, so the same catalog object is safe to share across every request.
# --------------------------------------------------------------------------------------------

FUNCTIONS: dict[str, dict[str, Any]] = {
    "send_email": {
        "description": "Send an email message to one recipient.",
        "schema": {
            "to": {"type": "email", "required": True},
            "subject": {"type": "string", "required": True},
            "body": {"type": "string", "required": True},
            "priority": {"type": "enum", "required": False, "enum": ("low", "normal", "high")},
        },
    },
    "schedule_meeting": {
        "description": "Schedule a calendar meeting with one or more attendees.",
        "schema": {
            "title": {"type": "string", "required": True},
            "attendees": {"type": "email_list", "required": True},
            "duration_minutes": {"type": "integer", "required": True},
            "date": {"type": "date", "required": True},
        },
    },
    "create_ticket": {
        "description": "File a new ticket in the support tracking system.",
        "schema": {
            "title": {"type": "string", "required": True},
            "priority": {
                "type": "enum",
                "required": True,
                "enum": ("low", "medium", "high", "critical"),
            },
            "assignee": {"type": "string", "required": False},
        },
    },
    "set_reminder": {
        "description": "Create a reminder that fires at a future date.",
        "schema": {
            "message": {"type": "string", "required": True},
            "remind_at": {"type": "date", "required": True},
            "channel": {"type": "enum", "required": False, "enum": ("email", "sms", "push")},
        },
    },
    "update_record": {
        "description": "Update one field of an existing customer record.",
        "schema": {
            "record_id": {"type": "record_id", "required": True},
            "field": {"type": "enum", "required": True, "enum": ("status", "owner", "notes")},
            "value": {"type": "string", "required": True},
        },
    },
    "lookup_contact": {
        "description": "Search the contact directory for matching people.",
        "schema": {
            "query": {"type": "string", "required": True},
            "max_results": {"type": "integer", "required": False},
        },
    },
}

# The fallback the use case names: no catalog function should be called. A Choice option like
# any other, built by Python, never a separate code path Jev reaches by failing to answer.
NO_FUNCTION = "no_function"

OPTION_NAMES: tuple[str, ...] = (*FUNCTIONS, NO_FUNCTION)

# Outcomes the composed rule below can produce.
EXECUTED = "executed"
REVIEW = "review"
NO_FUNCTION_OUTCOME = "no_function"

REASON_CONFIDENCE = "confidence below the threshold"
REASON_NO_FUNCTION = "no catalog function fits this request"
REASON_EXECUTED = "confident match, valid arguments"

# --------------------------------------------------------------------------------------------
# Stage 1 state: the request Jev reads, and the tested extractor Python runs over the same
# text to recover the arguments the request supplies. Jev is never asked about the arguments
# themselves -- only which function (if any) fits the request -- so the extractor's output
# never appears in `build_state`; it feeds stage 2 (`validate_arguments`) directly.
# --------------------------------------------------------------------------------------------

ARGUMENTS_MARKER = "Arguments: "


def extract_arguments(request: str) -> dict[str, str]:
    """Return the ``{name: value}`` pairs the request's own ``"Arguments: "`` trailer supplies.

    The trailer, when present, is everything after the marker: ``key=value`` pairs separated by
    ``"; "``. A list-valued argument (``attendees``) packs its members with ``"|"`` inside one
    pair's value, so splitting on ``"; "`` never breaks a list apart. A request with no trailer
    at all (nothing was supplied) returns an empty mapping, never an error: a request is allowed
    to name a function with zero arguments, and stage 2 then reports every one of that
    function's required arguments as missing. A malformed pair (no ``"="``) and a blank pair
    (a trailing ``"; "``) are both skipped rather than raised on, so the extractor never invents
    a key for text it cannot parse; whatever it misses that way surfaces as a missing-required
    violation downstream instead of a crash here.
    """
    if ARGUMENTS_MARKER not in request:
        return {}
    trailer = request.split(ARGUMENTS_MARKER, 1)[1].strip()
    arguments: dict[str, str] = {}
    for pair in trailer.split("; "):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        arguments[name.strip()] = value.strip()
    return arguments


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one request: the request text, verbatim, and nothing else.

    ``fields`` also carries the item's bookkeeping id under ``request_id`` when present;
    Python keeps that for itself and never passes it through the model.
    """
    return {"request": fields["request"]}


def option_order_for(item_id: str) -> tuple[str, ...]:
    """The per-item shuffled option order for one request: ``OPTION_NAMES``, reordered by
    ``stable_shuffle`` seeded from this recipe's slug and the item's own id (docs/fixtures.md,
    "Per-item option order"), never from ``random.shuffle`` and never from the order
    ``OPTION_NAMES`` already lists them in -- so a rule that always answers "the first option
    shown" cannot score well merely because the catalog happens to list the gold function
    first for most requests.
    """
    return stable_shuffle(f"{RECIPE_SLUG}:{item_id}", OPTION_NAMES)


def _option_description(name: str) -> str:
    if name == NO_FUNCTION:
        return (
            "None of the functions above should be called: the request does not ask for any "
            "catalog action, or no catalog function's purpose matches what it is asking for."
        )
    spec = FUNCTIONS[name]
    arguments = ", ".join(spec["schema"])
    return f"{spec['description']} Arguments: {arguments}."


def build_questions(option_order: tuple[str, ...]) -> dict[str, Choice]:
    """The one question asked about every request: which catalog function, if any, fits it.

    ``option_order`` is this request's own shuffled order from ``option_order_for``; Choice
    option order is part of the replay key (docs/backends.md, "Replay key"), so passing a
    different order here than the fixtures were built with is a replay miss, not a silent
    mismatch.
    """
    criteria = {name: _option_description(name) for name in option_order}
    return {
        "function": Choice(
            instructions=(
                "A user sent the request below to an assistant that may call one function "
                "from a preapproved catalog on the user's behalf. Which function should "
                "handle this request? Choose the catalog function whose purpose matches "
                "what the user is asking for, or no_function when the request does not "
                "match any of them, even if it looks like it could be handled by combining "
                "or guessing at a function not listed here."
            ),
            criteria=criteria,
        )
    }


# --------------------------------------------------------------------------------------------
# Stage 2: Python's own argument validator. Deterministic, has no confidence of its own, and
# runs before any simulated execution, whatever the model answered. The three violation kinds
# the use case names, in the order a function's own schema fields are declared.
# --------------------------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RECORD_ID_RE = re.compile(r"^REC-\d+$")
_INTEGER_RE = re.compile(r"^-?\d+$")


def _fits_type(value: str, arg_type: str) -> bool:
    """True if ``value`` (always a string: every extracted argument is text) is well formed for
    ``arg_type``. ``"enum"`` is not handled here: enumeration membership is its own violation
    kind, checked separately in ``validate_arguments``."""
    if arg_type == "string":
        return bool(value)
    if arg_type == "email":
        return bool(_EMAIL_RE.match(value))
    if arg_type == "email_list":
        members = [part for part in value.split("|") if part]
        return bool(members) and all(_EMAIL_RE.match(part) for part in members)
    if arg_type == "integer":
        return bool(_INTEGER_RE.match(value))
    if arg_type == "date":
        return bool(_DATE_RE.match(value))
    if arg_type == "record_id":
        return bool(_RECORD_ID_RE.match(value))
    raise ValueError(f"unknown argument type {arg_type!r}")


def validate_arguments(function_name: str, arguments: dict[str, str]) -> list[str]:
    """Every violation of ``function_name``'s own schema in ``arguments``, in schema field
    order: ``"missing required argument: X"``, ``"wrong type for argument: X"``, or
    ``"value outside the enumeration for argument: X"``. An empty list means the arguments are
    valid for this function. Never looks at confidence, and never raises on an unknown
    (unscheduled) argument key: this recipe's extractor only ever produces keys it read from the
    request text, and a key the schema does not name is simply not one of these three things.
    """
    schema = FUNCTIONS[function_name]["schema"]
    violations: list[str] = []
    for name, spec in schema.items():
        if name not in arguments:
            if spec["required"]:
                violations.append(f"missing required argument: {name}")
            continue
        value = arguments[name]
        if spec["type"] == "enum":
            if value not in spec["enum"]:
                violations.append(f"value outside the enumeration for argument: {name}")
        elif not _fits_type(value, spec["type"]):
            violations.append(f"wrong type for argument: {name}")
    return violations


# --------------------------------------------------------------------------------------------
# The composed rule: confidence gate first (every option, ``no_function`` included -- see "The
# simulated side effects" in the notebook for why ``no_function`` is gated like everything else
# rather than exempted), then, for a real function cleared at the gate, stage 2's argument
# validation before any simulated execution.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    """What Python decided for one request.

    ``violations`` is non-empty only when ``outcome`` is ``REVIEW`` because stage 2 rejected the
    arguments; it is empty for a confidence-gated review and for every other outcome.
    """

    item_id: str
    choice: str
    outcome: str
    reason: str
    violations: tuple[str, ...] = ()


def resolve(
    item_id: str,
    answer: Any,
    arguments: dict[str, str],
    min_confidence: float,
    *,
    actions: ActionLog,
    queue: ReviewQueue,
) -> Resolution:
    """Decide what happens with one answered request, and record the simulated side effect.

    Every option goes through the same confidence gate first: an answer below
    ``min_confidence`` is sent to ``queue`` with the reason ``"confidence below the
    threshold"``, whatever option it names, ``no_function`` included. ``no_function`` passes
    every part of CONTRIBUTING.md section 4's three-part test on its own (it is a complete
    answer, not a deferral; choosing it writes nothing; being wrong leaves nothing standing
    beyond the missed action itself, exactly what sending it to review would also have left
    pending) -- see "The simulated side effects" in the notebook for the full argument -- but
    this rule still gates it like every other option rather than claim that exemption: gating a
    qualifying fallback anyway is compliant (CONTRIBUTING.md section 4). A real function cleared
    at the gate is validated against its own schema (``validate_arguments``) before anything is
    simulated: invalid arguments send the request to ``queue`` with a reason naming the first
    violation, never to ``actions``; valid arguments are recorded in ``actions`` as a simulated
    execution, which never actually calls or changes anything.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.confidence < min_confidence:
        queue.submit(
            {"request": item_id, "choice": answer.choice},
            REASON_CONFIDENCE,
            answer=answer,
        )
        return Resolution(item_id, answer.choice, REVIEW, REASON_CONFIDENCE)
    if answer.choice == NO_FUNCTION:
        return Resolution(item_id, NO_FUNCTION, NO_FUNCTION_OUTCOME, REASON_NO_FUNCTION)
    violations = validate_arguments(answer.choice, arguments)
    if violations:
        reason = violations[0]
        queue.submit(
            {"request": item_id, "choice": answer.choice, "violations": list(violations)},
            reason,
            answer=answer,
        )
        return Resolution(item_id, answer.choice, REVIEW, reason, tuple(violations))
    actions.record(
        answer.choice,
        {"request": item_id, "arguments": dict(arguments)},
        answer=answer,
        rule=REASON_EXECUTED,
    )
    return Resolution(item_id, answer.choice, EXECUTED, REASON_EXECUTED)


def gold_outcome(gold_function: str, arguments: dict[str, str]) -> tuple[str, str]:
    """The outcome and the executed-function name a flawless rule would produce for one
    request, given its gold intended function and the arguments Python actually extracted from
    it. This never depends on a model answer: it is the same ``validate_arguments`` call
    ``resolve`` makes, applied to the gold function instead of whatever Jev named, so a request
    needs only one gold label (the intended function) and never a second, hand-written "is this
    one valid" label that could drift out of sync with the schema.
    """
    if gold_function == NO_FUNCTION:
        return NO_FUNCTION_OUTCOME, NO_FUNCTION
    if validate_arguments(gold_function, arguments):
        return REVIEW, gold_function
    return EXECUTED, gold_function


def task_correct(resolution: Resolution, gold_function: str, arguments: dict[str, str]) -> bool:
    """Task-level correctness: the resolution's outcome, and, for an executed request, which
    function it executed, must both match ``gold_outcome``. A request where Jev named the wrong
    function but that wrong function's own schema happens to accept the arguments still executes
    -- the wrong action, confidently -- and this reports that as incorrect even though
    ``resolution.outcome == EXECUTED``: selection accuracy alone could not tell this case apart
    from a right one, which is exactly why this recipe evaluates at task level and not only on
    the raw choice.
    """
    expected_outcome, expected_choice = gold_outcome(gold_function, arguments)
    if resolution.outcome != expected_outcome:
        return False
    if resolution.outcome == EXECUTED:
        return resolution.choice == expected_choice
    return True


def accepted_and_correct(
    resolutions: list[Resolution],
    gold_functions: dict[str, str],
    arguments_by_id: dict[str, dict[str, str]],
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``: ``accepted[i]``
    is whether ``resolve`` answered the request (``executed`` or ``no_function``) rather than
    sending it to review, whatever its confidence; ``correct[i]`` is the task-level correctness
    from ``task_correct`` (ignored, but still computed, where ``accepted[i]`` is False, exactly
    as ``evaluate_outcomes`` documents). This rule's review branch is more than the confidence
    gate alone -- an invalid-argument rejection is unconditional on confidence -- so
    ``evaluate_outcomes``, not ``evaluate_selective``, is the function that reports it
    (see "Selective prediction" in docs/evaluation.md).
    """
    accepted = [r.outcome != REVIEW for r in resolutions]
    correct = [
        task_correct(r, gold_functions[r.item_id], arguments_by_id[r.item_id]) for r in resolutions
    ]
    return accepted, correct


def invalid_argument_hard_cases(
    gold_functions: dict[str, str], arguments_by_id: dict[str, dict[str, str]]
) -> list[str]:
    """Ids of the use case's named hard case: the gold function is a real catalog function, but
    the arguments Python actually extracted from the request fail that function's own schema.
    """
    return [
        item_id
        for item_id, function_name in gold_functions.items()
        if function_name != NO_FUNCTION
        and validate_arguments(function_name, arguments_by_id[item_id])
    ]


def invalid_argument_rejection_rate(
    resolutions: dict[str, Resolution], hard_case_ids: list[str]
) -> float:
    """Of the invalid-argument hard cases, the fraction the pipeline did NOT execute an action
    for: a resolution of ``review`` (caught by stage 2's own validation, or by the confidence
    gate) or ``no_function`` both count as rejected; only ``executed`` -- which here can only
    happen when Jev confidently named a *different*, wrong function whose own schema happens to
    accept these particular arguments -- counts against the rate. Raises ``ValueError`` on an
    empty ``hard_case_ids`` rather than silently reporting an undefined rate as a number.
    """
    if not hard_case_ids:
        raise ValueError("no invalid-argument hard cases to measure a rejection rate over")
    rejected = sum(1 for item_id in hard_case_ids if resolutions[item_id].outcome != EXECUTED)
    return rejected / len(hard_case_ids)
