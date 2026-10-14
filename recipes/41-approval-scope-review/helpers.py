"""Python's half of recipe 41: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.

Design in one paragraph: a proposed tool action carries two things Python checks on its own,
never asking the model about either -- the *approval binding* (does the action cite the
approval that is actually on file for it, is that approval active, unconsumed, bound to the
right actor, and does the action's own tool and target resource sit inside what that approval
names) -- and one thing it asks the model about: whether the action's own description is a
*semantic* fit for the approved task, a judgment natural-language text calls for and an exact
binary check cannot make. Two independent ``Noul`` propositions, asked together in one request
per action, describe that semantic fit; ``decide`` below composes the binding check and the two
label decisions into exactly one of three outcomes, and the binding check runs, and can refuse,
*before* either proposition is ever read. No value either proposition takes can turn a binding
refusal into an executed action -- "The safety asymmetry" in ``tests/test_helpers.py`` proves
this by sweeping the full ``[0, 1]`` answer space, not by sampling it.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------------------------
# The two independent propositions, asked together in one request per action (CONTRIBUTING.md
# section 3: independent questions over the same state go in one request). Both read "true"
# as a problem: a confirmed proposition can only ever push the outcome toward review, never
# toward execution -- see ``decide`` below for where that asymmetry is actually enforced.
# --------------------------------------------------------------------------------------------

INTENT_MISMATCH = "intent_mismatch"
SCOPE_CREEP = "scope_creep"
LABELS: tuple[str, ...] = (INTENT_MISMATCH, SCOPE_CREEP)

# The three outcomes ``decide`` can report. REVIEW is the lexicon's own outcome string
# (docs/glossary.md#review), shared by every other recipe's confidence-gated outcome; DENIED
# and EXECUTED are this recipe's own two complete answers.
DENIED = "denied"
REVIEW = "review"
EXECUTED = "executed"

REASON_REVIEW_CONFIDENCE = "confidence below the threshold"
REASON_REVIEW_INTENT = "the proposed action's purpose does not match the approved task"
REASON_REVIEW_SCOPE = "the proposed action's effect reaches beyond what the approved task named"
REASON_EXECUTED = "confident match, within approved scope, binding valid"

# The six independent ways ``check_binding`` can refuse an action. Order is the order
# ``check_binding`` checks them in and the order its reasons are ever reported in.
REASON_BINDING_CITE = "the action cites a different approval than the one on file for it"
REASON_BINDING_STATUS = "approval is {status}"
REASON_BINDING_CONSUMED = "approval has no uses remaining"
REASON_BINDING_ACTOR = "actor does not match the approval"
REASON_BINDING_TOOL = "tool not in the approval's approved scope"
REASON_BINDING_RESOURCE = "target resource outside the approval's approved scope"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one proposed action: the approved task's own description, and the
    proposed action's own description, nothing else.

    ``fields`` also carries ``approval`` and ``action`` in full (approval ids, actor ids, tool
    names, resource names, status, uses) -- every one of those is what Python's own binding
    check reads, and none of them ever reaches the model: the model is asked only whether two
    pieces of text describe the same undertaking, never asked to read a permission a second
    time.
    """
    return {
        "approved_task": fields["approval"]["task"],
        "proposed_action": fields["action"]["description"],
    }


def build_questions() -> dict[str, Noul]:
    """The two independent propositions asked about every proposed action, in one request.

    Both describe the same pair of texts, so ``backend.decide`` sends them together: TypeSafe's
    primitives page (S02) says independent questions over the same state belong in one request.
    They stay two separate ``Noul`` propositions rather than one two-option ``Choice`` because
    they are not mutually exclusive readings of a single judgment -- a proposed action can in
    principle read as both at once, or as neither -- and because CONTRIBUTING.md section 3 asks
    for one independent question per concern.
    """
    return {
        INTENT_MISMATCH: Noul(
            instructions=(
                "The proposed action's purpose does not match what the approved task asked "
                "for -- it would accomplish something other than what was approved, even if "
                "it uses a plausible-sounding tool."
            ),
            criteria={
                "true": (
                    "The proposed action pursues a different purpose than the approved task "
                    "describes: a different goal, a different kind of change, or a change "
                    "the approved task never asked for at all, however reasonable it sounds "
                    "on its own."
                ),
                "false": (
                    "The proposed action is a reasonable, ordinary way to carry out the "
                    "approved task's own stated purpose, with no different goal smuggled in."
                ),
            },
        ),
        SCOPE_CREEP: Noul(
            instructions=(
                "The proposed action's own description claims an effect broader than, or "
                "different from, what the approved task specifically named -- a wider target, "
                "an additional recipient, a longer time window, or a bigger change than the "
                "approved task scoped."
            ),
            criteria={
                "true": (
                    "The proposed action's description names a target, quantity, or effect "
                    "that goes beyond what the approved task specifically named -- affecting "
                    "more than, or something other than, the one thing the approved task "
                    "scoped, even if the underlying tool is the right kind of tool."
                ),
                "false": (
                    "The proposed action's description stays limited to exactly what the "
                    "approved task specifically named, with no broader or additional effect "
                    "implied."
                ),
            },
        ),
    }


# --------------------------------------------------------------------------------------------
# The binding check: pure Python, no model, no confidence, and it reads nothing either
# proposition above ever answers. ``decide`` below runs this first and ``decide`` is the only
# place a model answer is read at all -- so this function's own return value can never depend
# on one, which ``tests/test_helpers.py`` also checks directly (``check_binding`` takes no
# answer argument at all; there is nothing to sweep).
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BindingResult:
    """Whether a proposed action's approval binding holds, and every reason it does not.

    ``reasons`` lists every violation found (not only the first), in the fixed order
    ``check_binding`` checks them, so a reader can see every problem with a binding at once
    rather than fixing one violation per re-check.
    """

    ok: bool
    reasons: tuple[str, ...]


def check_binding(
    action: dict[str, Any], approval: dict[str, Any], uses_spent: int = 0
) -> BindingResult:
    """Every independent way a proposed action's binding to ``approval`` can fail.

    ``uses_spent`` is how many of ``approval``'s uses an earlier, already-executed action has
    already spent -- supplied by the caller, never read from anywhere mutable here, so this
    function stays a pure check of one action against one approval snapshot and one integer.
    The stateful walkthrough in the notebook is what threads a running count of spent uses
    across a sequence of actions that cite the same approval; this function only ever compares
    the count it is given against ``approval["max_uses"]``.

    Six independent checks, every one of which fires on its own fixtures (``tests/
    test_helpers.py`` proves each is independently consequential): the action cites the
    approval actually on file for it; the approval is active (not expired or revoked); the
    approval has a use remaining; the action's actor matches the approval's actor; the action's
    tool is in the approval's own approved-tool list; the action's target resource is in the
    approval's own approved-resource list.
    """
    if type(uses_spent) is not int or uses_spent < 0:
        raise ValueError(f"uses_spent must be a non-negative int, got {uses_spent!r}")
    reasons: list[str] = []
    if action["cited_approval_id"] != approval["approval_id"]:
        reasons.append(REASON_BINDING_CITE)
    if approval["status"] != "active":
        reasons.append(REASON_BINDING_STATUS.format(status=approval["status"]))
    if uses_spent >= approval["max_uses"]:
        reasons.append(REASON_BINDING_CONSUMED)
    if action["actor_id"] != approval["actor_id"]:
        reasons.append(REASON_BINDING_ACTOR)
    if action["tool_name"] not in approval["approved_tools"]:
        reasons.append(REASON_BINDING_TOOL)
    if action["target_resource"] not in approval["resource_scope"]:
        reasons.append(REASON_BINDING_RESOURCE)
    return BindingResult(not reasons, tuple(reasons))


# --------------------------------------------------------------------------------------------
# The two label decisions (business threshold and shared confidence gate), and the composed
# rule. decide_labels never reads a binding; decide reads a binding first and only calls
# decide_labels when the binding holds -- so a label decision can add a review, and can never
# turn a refused binding into an executed action.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelDecision:
    """What Python decided for one (action, proposition) pair: the business tag against that
    proposition's own frozen threshold, and whether the shared confidence gate sends it to
    review."""

    label: str
    noul: float
    tag: bool
    confidence: float
    gated: bool


def decide_labels(
    noul_values: dict[str, float], thresholds: dict[str, float], confidence_gate: float
) -> dict[str, LabelDecision]:
    """Apply each proposition's own business threshold and the shared confidence gate to one
    action's two Noul probabilities.

    ``noul_values`` is a plain ``{label: probability}`` mapping (never a typed answer object),
    so this function -- and the exhaustive safety sweep built on it -- can be called directly
    with any value in ``[0, 1]`` for either label, not only ones a stored answer ever produced.
    For every label in ``LABELS``: the business tag is ``noul >= thresholds[label]``; confidence
    is ``noul_confidence(noul)`` (S03, ``|2p - 1|``); ``gated`` is ``confidence <
    confidence_gate``, whatever the business tag says.
    """
    if not 0.0 <= float(confidence_gate) <= 1.0:
        raise ValueError(f"confidence_gate must be between 0 and 1, got {confidence_gate!r}")
    if set(thresholds) != set(LABELS):
        raise ValueError(f"thresholds must name exactly LABELS {LABELS}, got {sorted(thresholds)}")
    if set(noul_values) != set(LABELS):
        raise ValueError(
            f"noul_values must name exactly LABELS {LABELS}, got {sorted(noul_values)}"
        )
    decisions: dict[str, LabelDecision] = {}
    for label in LABELS:
        noul = float(noul_values[label])
        if not 0.0 <= noul <= 1.0:
            raise ValueError(f"noul for {label!r} must be between 0 and 1, got {noul!r}")
        threshold = thresholds[label]
        if not 0.0 <= float(threshold) <= 1.0:
            raise ValueError(f"threshold for {label!r} must be between 0 and 1, got {threshold!r}")
        tag = noul >= threshold
        confidence = noul_confidence([noul])[0]
        gated = confidence < confidence_gate
        decisions[label] = LabelDecision(label, noul, tag, confidence, gated)
    return decisions


@dataclass(frozen=True)
class Resolution:
    """Python's composed, task-level decision for one proposed action: one of ``DENIED``,
    ``REVIEW`` or ``EXECUTED``, the reason, the binding result, and the two label decisions
    (``None`` for both when the binding itself already refused, since neither was then needed
    to reach a decision -- see ``decide``)."""

    outcome: str
    reason: str
    binding: BindingResult
    intent_mismatch: "LabelDecision | None"
    scope_creep: "LabelDecision | None"


def decide(
    action: dict[str, Any],
    approval: dict[str, Any],
    uses_spent: int,
    noul_values: dict[str, float],
    thresholds: dict[str, float],
    confidence_gate: float,
) -> Resolution:
    """Compose the binding check and the two label decisions into one outcome.

    This is the one rule this recipe enforces whatever the model answers, and the whole safety
    property rests on its order: ``check_binding`` runs first, reads no ``noul_values`` at all,
    and ``decide`` returns ``DENIED`` immediately when it refuses -- ``decide_labels`` is never
    even called in that branch, so there is no value either proposition could take that reaches
    this function's return statement. Only once the binding holds does either label decision
    matter, and even then only to add a review: a confident, flagged proposition (or either
    gated by low confidence) reports ``REVIEW``; otherwise, with the binding holding and both
    propositions confidently clear, the only remaining outcome is ``EXECUTED``.

    Args:
        action: This action's fields (``cited_approval_id``, ``actor_id``, ``tool_name``,
            ``target_resource``, ``description``).
        approval: The approval snapshot actually on file for this action (``approval_id``,
            ``actor_id``, ``task``, ``approved_tools``, ``resource_scope``, ``status``,
            ``max_uses``).
        uses_spent: Uses of ``approval`` already spent by earlier, already-executed actions.
        noul_values: ``{label: probability}`` for both labels in ``LABELS`` -- a plain mapping,
            not a typed answer, so the exhaustive safety sweep can call this with any point in
            ``[0, 1]^2``, not only a value a stored answer ever produced.
        thresholds: The frozen per-label business thresholds.
        confidence_gate: The frozen shared confidence gate.

    Returns:
        A :class:`Resolution`.
    """
    binding = check_binding(action, approval, uses_spent)
    if not binding.ok:
        return Resolution(DENIED, "; ".join(binding.reasons), binding, None, None)
    decisions = decide_labels(noul_values, thresholds, confidence_gate)
    intent = decisions[INTENT_MISMATCH]
    scope = decisions[SCOPE_CREEP]
    if intent.gated or scope.gated:
        return Resolution(REVIEW, REASON_REVIEW_CONFIDENCE, binding, intent, scope)
    if intent.tag:
        return Resolution(REVIEW, REASON_REVIEW_INTENT, binding, intent, scope)
    if scope.tag:
        return Resolution(REVIEW, REASON_REVIEW_SCOPE, binding, intent, scope)
    return Resolution(EXECUTED, REASON_EXECUTED, binding, intent, scope)


# --------------------------------------------------------------------------------------------
# Two pure-Python baselines with no model request at all, reported alongside `decide` in the
# notebook's evaluation section (CONTRIBUTING.md asks a recipe to compare against a named
# baseline when the use case names one; this use case names none, so these are the two its own
# shape suggests -- act on the binding alone, or never act automatically at all).
# --------------------------------------------------------------------------------------------


def permission_only_outcome(
    action: dict[str, Any], approval: dict[str, Any], uses_spent: int
) -> str:
    """The outcome a rule that enforces only the binding -- never asking the model anything --
    would report: ``EXECUTED`` whenever the binding holds, ``DENIED`` otherwise. Zero model
    requests; it cannot catch a semantic mismatch a binding-valid action still carries."""
    return EXECUTED if check_binding(action, approval, uses_spent).ok else DENIED


def always_review_outcome(action: dict[str, Any], approval: dict[str, Any], uses_spent: int) -> str:
    """The outcome a maximally conservative rule -- deny on a bad binding, otherwise always
    send to review, never auto-execute anything -- would report. Also zero model requests, and
    never wrongly executes anything, at the cost of automatically executing nothing at all."""
    return DENIED if not check_binding(action, approval, uses_spent).ok else REVIEW


# --------------------------------------------------------------------------------------------
# Gold outcome, correctness and coverage accounting, mirroring recipe 27's pattern: one gold
# label per proposition (never derived from the other), composed with the same deterministic
# binding check `decide` itself uses, so a flawless rule's outcome needs no separate hand-
# written "is this one valid" label that could drift out of sync with `check_binding`.
# --------------------------------------------------------------------------------------------


def gold_outcome(
    action: dict[str, Any],
    approval: dict[str, Any],
    uses_spent: int,
    gold_intent_mismatch: bool,
    gold_scope_creep: bool,
) -> str:
    """The outcome a flawless rule would produce for one proposed action, given its two
    independent gold propositions (never derived from each other) and the same deterministic
    ``check_binding`` ``decide`` itself calls. A flawless rule has no confidence gate to clear
    (it is never unsure), so the only two outcomes it can reach are ``DENIED`` (binding refused)
    and either ``REVIEW`` or ``EXECUTED`` (binding held): ``REVIEW`` when either gold proposition
    is true, ``EXECUTED`` when both are false.
    """
    if not check_binding(action, approval, uses_spent).ok:
        return DENIED
    if gold_intent_mismatch or gold_scope_creep:
        return REVIEW
    return EXECUTED


def task_correct(resolution: Resolution, gold: str) -> bool:
    """Task-level correctness: the resolution's outcome matches the gold outcome. A ``REVIEW``
    resolution is never scored as an error against a ``REVIEW`` gold or against anything else --
    ``evaluate_outcomes`` ignores ``correct`` wherever ``accepted`` is False, exactly as
    ``docs/evaluation.md`` documents -- so this is computed uniformly for every resolution, not
    only the accepted ones."""
    return resolution.outcome == gold


def accepted_and_correct(
    resolutions: list[Resolution], golds: list[str]
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``.

    ``accepted[i]`` is whether ``decide`` answered the action outright (``denied`` or
    ``executed``) rather than sending it to review: both are complete answers under
    CONTRIBUTING.md section 4 part (a) (a denial is a real judgment, "do not proceed", not a
    deferral that asks a person the same question again), so both count toward coverage, exactly
    as ``no_function`` does in recipe 27. ``correct[i]`` is ``task_correct`` against this
    action's own gold outcome. This rule's review branch is more than the confidence gate alone
    -- a refused binding is unconditional on confidence, and so is a confidently-flagged
    proposition -- so ``evaluate_outcomes``, not ``evaluate_selective``, is the function that
    reports it (``docs/evaluation.md``, "Selective prediction").
    """
    if len(resolutions) != len(golds):
        raise ValueError("resolutions and golds must be the same length")
    accepted = [r.outcome != REVIEW for r in resolutions]
    correct = [task_correct(r, g) for r, g in zip(resolutions, golds, strict=True)]
    return accepted, correct


def denied_but_semantically_clear_ids(
    ids: list[str],
    resolutions: dict[str, Resolution],
    gold_intent_mismatch: dict[str, bool],
    gold_scope_creep: dict[str, bool],
) -> list[str]:
    """Ids of the use case's sharpest hard case: the binding was refused (``DENIED``), and the
    proposed action's own gold propositions both read ``False`` -- this is the action that, on
    its text alone, looks like a perfectly ordinary match for its approved task. These are the
    rows that make "the model's answer can add a hold and can never grant an action" concrete
    rather than abstract: every one of them is denied regardless of what either proposition
    reads, confidently clear included.
    """
    return [
        item_id
        for item_id in ids
        if resolutions[item_id].outcome == DENIED
        and not gold_intent_mismatch[item_id]
        and not gold_scope_creep[item_id]
    ]


def review_sort_key(result: Resolution) -> float:
    """The ascending key a notebook sorts ``REVIEW`` actions by before submitting them to the
    simulated queue: the lower of the two labels' own confidence, so the pair Python is least
    sure about -- on either proposition -- surfaces first. Never called on a ``DENIED``
    resolution, whose label decisions are ``None``."""
    if result.intent_mismatch is None or result.scope_creep is None:
        raise ValueError("review_sort_key needs label decisions; this resolution has none")
    return min(result.intent_mismatch.confidence, result.scope_creep.confidence)


def queue_item(example_id: str, fields: dict[str, Any], result: Resolution) -> dict[str, Any]:
    """What a human reviewer sees for one queued action: its id, the two texts Jev was actually
    asked about, and both label decisions -- not only an identifier (CONTRIBUTING.md section 4:
    the queue is the side effect a ``review`` outcome triggers, and an item with nothing to read
    is not something a person can actually review)."""
    return {
        "id": example_id,
        "approved_task": fields["approval"]["task"],
        "proposed_action": fields["action"]["description"],
        INTENT_MISMATCH: {
            "noul": result.intent_mismatch.noul,
            "confidence": result.intent_mismatch.confidence,
        },
        SCOPE_CREEP: {
            "noul": result.scope_creep.noul,
            "confidence": result.scope_creep.confidence,
        },
    }
