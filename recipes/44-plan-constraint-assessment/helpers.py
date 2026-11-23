"""Python's half of recipe 44: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.

Design in one paragraph: a candidate plan is checked against four of the user's own
constraints -- budget, timeline, vendor and data handling -- one independent ``Noul``
proposition per (plan, constraint) pair, all four asked together in one request per plan
(CONTRIBUTING.md section 3: independent questions over the same state go in one request).
Each proposition reads "true" as a problem: the plan *violates* that one constraint. Python
never asks the model to weigh the four against each other -- ``decide`` composes the four
label decisions deterministically into exactly one of three outcomes: ``ineligible`` (at
least one constraint is confidently violated), ``review`` (at least one constraint's
judgment is not confident enough to trust, and none is yet a confirmed violation), or
``eligible`` (every constraint confidently clears). A confident violation on any one
constraint is enough to make a plan ineligible even when every other constraint is
confidently clear -- the named hard case this recipe ships is exactly a plan that satisfies
every constraint but one, and it is still ineligible.

Two of the four constraints are decided by arithmetic, not by Jev. Whether a plan's cost is
over the budget limit and whether its completion date falls after the deadline are
comparisons of quantities, and TypeSafe says Jev reads dates as text and cannot reliably
judge whether two numbers are near each other, so ``budget_check`` and ``timeline_check``
compare them in Python from the structured ``cost``, ``budget_limit``, ``completion`` and
``deadline`` fields and the state carries only the named bucket they return. The ``budget`` and
``timeline`` propositions are therefore pure readbacks of a fact Python already holds: they
stay in the request so every plan still carries four independent propositions through one
shared multi-label evaluation, but they add no judgment of their own. Jev's real judgment is the
other two constraints, ``vendor`` and ``data_handling``, which are about prose.
"""

from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------------------------
# The four independent propositions, asked together in one request per plan. Each is written
# so that "true" is a problem: a confirmed violation can only ever push a plan toward
# "ineligible" or "review", never toward "eligible" -- the asymmetry ``decide`` enforces below.
# --------------------------------------------------------------------------------------------

BUDGET = "budget"
TIMELINE = "timeline"
VENDOR = "vendor"
DATA_HANDLING = "data_handling"
CONSTRAINTS: tuple[str, ...] = (BUDGET, TIMELINE, VENDOR, DATA_HANDLING)
LABELS = CONSTRAINTS  # the name jev_cookbook.evaluation's multi-label helpers expect

# The three outcomes ``decide`` can report. REVIEW is the lexicon's own outcome string
# (docs/glossary.md#review), shared by every other recipe's confidence-gated outcome;
# ELIGIBLE and INELIGIBLE are this recipe's own two complete answers.
ELIGIBLE = "eligible"
REVIEW = "review"
INELIGIBLE = "ineligible"

# The named buckets Python computes for the two comparisons it owns. These strings are the only
# form in which the budget and timeline comparisons reach Jev.
BUDGET_OVER = "over the limit"
BUDGET_WITHIN = "within the limit"
TIMELINE_LATE = "after the deadline"
TIMELINE_ON_TIME = "on or before the deadline"

REASON_REVIEW_CONFIDENCE = "confidence below the threshold"
REASON_ELIGIBLE = "confident match on every constraint"


def _reason_ineligible(violated: tuple[str, ...]) -> str:
    return "confidently violates: " + ", ".join(violated)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value!r}")
    return float(value)


def _iso_date(value: Any, name: str) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"{name} must be an ISO date string YYYY-MM-DD, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be an ISO date string YYYY-MM-DD, got {value!r}") from None


def budget_check(cost: Any, limit: Any) -> str:
    """Python's budget comparison: ``BUDGET_OVER`` when ``cost`` is strictly above ``limit``,
    else ``BUDGET_WITHIN`` (spending exactly the limit stays within it, as the constraint's
    "must not exceed" says). Both arguments are numbers, never text."""
    return BUDGET_OVER if _number(cost, "cost") > _number(limit, "budget_limit") else BUDGET_WITHIN


def timeline_check(completion: Any, deadline: Any) -> str:
    """Python's timeline comparison: ``TIMELINE_LATE`` when ``completion`` is strictly after
    ``deadline``, else ``TIMELINE_ON_TIME`` (finishing on the deadline day is on time, as "must
    be completed by" says). Both arguments are ISO ``YYYY-MM-DD`` strings parsed to dates."""
    late = _iso_date(completion, "completion") > _iso_date(deadline, "deadline")
    return TIMELINE_LATE if late else TIMELINE_ON_TIME


def computed_checks(fields: dict[str, Any]) -> dict[str, str]:
    """The two comparisons Python owns, computed from the plan's structured fields."""
    return {
        BUDGET: budget_check(fields["cost"], fields["budget_limit"]),
        TIMELINE: timeline_check(fields["completion"], fields["deadline"]),
    }


def build_state(fields: dict[str, Any]) -> dict[str, Any]:
    """The state Jev sees for one candidate plan: the vendor and data handling constraint
    statements, the plan's own description, and the two checks Python computed.

    ``fields`` also carries the structured ``cost``, ``budget_limit``, ``completion`` and
    ``deadline``. They never reach Jev: ``computed_checks`` compares them in Python and the
    state holds only the resulting bucket, so Jev is never asked to compare a date or an
    amount written as text. The budget and timeline statements stay in
    ``fields["user_constraints"]`` for the human reviewer but are not sent, because the
    comparison they describe is already done.
    """
    constraints = fields["user_constraints"]
    return {
        "user_constraints": {c: constraints[c] for c in (VENDOR, DATA_HANDLING)},
        "plan": fields["plan"],
        "computed_checks": computed_checks(fields),
    }


def build_questions() -> dict[str, Noul]:
    """The four independent violation propositions asked about every candidate plan, in one
    request.

    They stay four separate ``Noul`` propositions rather than one multi-option ``Choice``
    because they are not mutually exclusive readings of a single judgment: a plan can violate
    any subset of the four constraints, including several at once or none at all, and
    CONTRIBUTING.md section 3 asks for one independent question per concern. Each question's
    own wording is generic and fixed, so the same four questions serve every plan: ``vendor``
    and ``data_handling`` are judged against the constraint statements in ``user_constraints``
    in the state; ``budget`` and ``timeline`` are readbacks of the checks Python computed
    (``computed_checks`` in the state), with no limit, deadline, cost or date in the question.
    """
    return {
        BUDGET: Noul(
            instructions=(
                "The computed budget check reports that the plan is over the user's budget limit."
            ),
            criteria={
                "true": "The computed budget check says the plan's total cost is over the limit.",
                "false": "The computed budget check says the plan's total cost is within the limit.",
            },
        ),
        TIMELINE: Noul(
            instructions=(
                "The computed timeline check reports that the plan completes after the user's "
                "deadline."
            ),
            criteria={
                "true": "The computed timeline check says the plan completes after the deadline.",
                "false": (
                    "The computed timeline check says the plan completes on or before the deadline."
                ),
            },
        ),
        VENDOR: Noul(
            instructions=(
                "The plan violates the user's stated vendor constraint: it uses a vendor the "
                "constraint does not name as pre-approved, or the plan's own text leaves it "
                "unclear which vendor is actually used."
            ),
            criteria={
                "true": (
                    "The plan's own description names, or implies the use of, a vendor that "
                    "is not on the vendor constraint's pre-approved list, or does not make "
                    "clear which vendor is used."
                ),
                "false": (
                    "The plan's own description makes clear that every vendor it uses is on "
                    "the vendor constraint's pre-approved list."
                ),
            },
        ),
        DATA_HANDLING: Noul(
            instructions=(
                "The plan violates the user's stated data handling constraint: it shares the "
                "user's personal data with a party the constraint does not approve, or the "
                "plan's own text leaves unclear who the data actually reaches."
            ),
            criteria={
                "true": (
                    "The plan's own description shares, or implies sharing, the user's "
                    "personal data with a party beyond what the data handling constraint "
                    "approves, or does not make clear who receives it."
                ),
                "false": (
                    "The plan's own description makes clear that the user's personal data "
                    "reaches no one beyond what the data handling constraint approves."
                ),
            },
        ),
    }


# --------------------------------------------------------------------------------------------
# The per-constraint business threshold and shared confidence gate, and the composed rule.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelDecision:
    """What Python decided for one (plan, constraint) pair: the business tag against that
    constraint's own frozen threshold, and whether the shared confidence gate sends it to
    review."""

    label: str
    noul: float
    tag: bool
    confidence: float
    gated: bool


def decide_labels(
    noul_values: dict[str, float], thresholds: dict[str, float], confidence_gate: float
) -> dict[str, LabelDecision]:
    """Apply each constraint's own business threshold and the shared confidence gate to one
    plan's four Noul probabilities.

    ``noul_values`` is a plain ``{constraint: probability}`` mapping (never a typed answer
    object), so this function -- and the exhaustive sweeps built on it -- can be called
    directly with any value in ``[0, 1]`` for any constraint, not only one a stored answer
    ever produced. For every constraint in ``CONSTRAINTS``: the business tag ("violates") is
    ``noul >= thresholds[constraint]``; confidence is ``noul_confidence(noul)`` (S03,
    ``|2p - 1|``); ``gated`` is ``confidence < confidence_gate``, whatever the tag says.
    """
    if not 0.0 <= float(confidence_gate) <= 1.0:
        raise ValueError(f"confidence_gate must be between 0 and 1, got {confidence_gate!r}")
    if set(thresholds) != set(CONSTRAINTS):
        raise ValueError(
            f"thresholds must name exactly CONSTRAINTS {CONSTRAINTS}, got {sorted(thresholds)}"
        )
    if set(noul_values) != set(CONSTRAINTS):
        raise ValueError(
            f"noul_values must name exactly CONSTRAINTS {CONSTRAINTS}, got {sorted(noul_values)}"
        )
    decisions: dict[str, LabelDecision] = {}
    for constraint in CONSTRAINTS:
        noul = float(noul_values[constraint])
        if not 0.0 <= noul <= 1.0:
            raise ValueError(f"noul for {constraint!r} must be between 0 and 1, got {noul!r}")
        threshold = thresholds[constraint]
        if not 0.0 <= float(threshold) <= 1.0:
            raise ValueError(
                f"threshold for {constraint!r} must be between 0 and 1, got {threshold!r}"
            )
        tag = noul >= threshold
        confidence = noul_confidence([noul])[0]
        gated = confidence < confidence_gate
        decisions[constraint] = LabelDecision(constraint, noul, tag, confidence, gated)
    return decisions


@dataclass(frozen=True)
class Resolution:
    """Python's composed, plan-level decision: one of ``ELIGIBLE``, ``REVIEW`` or
    ``INELIGIBLE``, the reason, and every constraint's own :class:`LabelDecision`."""

    outcome: str
    reason: str
    decisions: dict[str, LabelDecision] = field(default_factory=dict)


def decide(
    noul_values: dict[str, float], thresholds: dict[str, float], confidence_gate: float
) -> Resolution:
    """Compose the four label decisions into one plan-level outcome.

    This is the one rule this recipe enforces whatever the model answers: a plan is
    ``ineligible`` as soon as any one constraint is confidently flagged as violated --
    ``gated`` or not on any *other* constraint does not change that, which is exactly what
    makes the named hard case (a plan that satisfies every constraint but one) still
    ineligible. Only once no constraint is a confirmed violation does an unresolved
    (``gated``) constraint matter at all, and then it sends the plan to review rather than
    letting it through. A plan is ``eligible`` only when every constraint is both confidently
    resolved and confidently clear.

    Args:
        noul_values: ``{constraint: probability}`` for every constraint in ``CONSTRAINTS`` --
            a plain mapping, not a typed answer, so an exhaustive sweep can call this with any
            point in ``[0, 1]^4``, not only a value a stored answer ever produced.
        thresholds: The frozen per-constraint business thresholds.
        confidence_gate: The frozen shared confidence gate.

    Returns:
        A :class:`Resolution`.
    """
    decisions = decide_labels(noul_values, thresholds, confidence_gate)
    violated = tuple(c for c in CONSTRAINTS if decisions[c].tag and not decisions[c].gated)
    gated = tuple(c for c in CONSTRAINTS if decisions[c].gated)
    if violated:
        return Resolution(INELIGIBLE, _reason_ineligible(violated), decisions)
    if gated:
        return Resolution(REVIEW, REASON_REVIEW_CONFIDENCE, decisions)
    return Resolution(ELIGIBLE, REASON_ELIGIBLE, decisions)


# --------------------------------------------------------------------------------------------
# Three pure-Python baselines, zero model requests each (CONTRIBUTING.md asks a recipe to
# compare against a named baseline when the use case names one; this use case names none, so
# these are the three its own three-outcome shape suggests -- approve everything, reject
# everything, or never decide automatically at all).
# --------------------------------------------------------------------------------------------


def approve_all_outcome() -> str:
    """The outcome a rule with no model request at all, and no opinion, would report for
    every plan: always ``ELIGIBLE``. Its accuracy and risk on any split are structurally
    determined by that split's own gold labels (wrong on every plan that gold actually finds
    ineligible, right on every other), not measured."""
    return ELIGIBLE


def reject_all_outcome() -> str:
    """The opposite zero-request extreme: always ``INELIGIBLE``. Structurally wrong on every
    plan gold finds eligible, structurally right on every other -- also not measured."""
    return INELIGIBLE


def always_review_outcome() -> str:
    """The maximally conservative zero-request rule: never decide automatically at all. Zero
    coverage, so its accuracy and risk among answered plans are undefined (NaN)."""
    return REVIEW


# --------------------------------------------------------------------------------------------
# Gold outcome, correctness and coverage accounting.
# --------------------------------------------------------------------------------------------


def gold_outcome(gold_violates: dict[str, bool]) -> str:
    """The outcome a flawless rule would produce for one plan, given its four independent
    gold violation labels (each taken from an explicit, independent fact about the plan --
    never derived from another constraint's own label). A flawless rule has no confidence
    gate to clear (it is never unsure), so the only two outcomes it can reach are
    ``INELIGIBLE`` (at least one constraint is actually violated) and ``ELIGIBLE`` (none is).
    """
    if set(gold_violates) != set(CONSTRAINTS):
        raise ValueError(
            f"gold_violates must name exactly CONSTRAINTS {CONSTRAINTS}, got {sorted(gold_violates)}"
        )
    return INELIGIBLE if any(gold_violates[c] for c in CONSTRAINTS) else ELIGIBLE


def task_correct(resolution: Resolution, gold: str) -> bool:
    """Plan-level correctness: the resolution's outcome matches the gold outcome. A
    ``REVIEW`` resolution is never scored as an error against anything --
    ``evaluate_outcomes`` ignores ``correct`` wherever ``accepted`` is False, exactly as
    ``docs/evaluation.md`` documents -- so this is computed uniformly for every resolution,
    not only the accepted ones."""
    return resolution.outcome == gold


def accepted_and_correct(
    resolutions: list[Resolution], golds: list[str]
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``.

    ``accepted[i]`` is whether ``decide`` answered the plan outright (``ineligible`` or
    ``eligible``) rather than sending it to review: both are complete answers under
    CONTRIBUTING.md section 4 part (a) -- an ``ineligible`` resolution is a real judgment,
    "do not proceed with this plan", not a deferral that asks a person the same question
    again -- so both count toward coverage. ``correct[i]`` is ``task_correct`` against this
    plan's own gold outcome. This rule's review branch is more than the confidence gate alone
    -- a confidently-flagged constraint is unconditional on any other constraint's gate -- so
    ``evaluate_outcomes``, not ``evaluate_selective``, is the function that reports it
    (``docs/evaluation.md``, "Selective prediction").
    """
    if len(resolutions) != len(golds):
        raise ValueError("resolutions and golds must be the same length")
    accepted = [r.outcome != REVIEW for r in resolutions]
    correct = [task_correct(r, g) for r, g in zip(resolutions, golds, strict=True)]
    return accepted, correct


def single_violation_ineligible_ids(
    ids: list[str],
    resolutions: dict[str, Resolution],
    gold_violates_by_label: dict[str, dict[str, bool]],
) -> list[str]:
    """Ids of this recipe's named hard case: a plan whose gold labels violate exactly one of
    the four constraints -- it satisfies every constraint but one -- and whose resolution is
    nonetheless ``INELIGIBLE``. This is "deterministic policy rejects ineligible plans" made
    concrete: a single confidently-flagged constraint is enough, however clean the other
    three read.
    """
    out = []
    for item_id in ids:
        violated_count = sum(gold_violates_by_label[c][item_id] for c in CONSTRAINTS)
        if violated_count == 1 and resolutions[item_id].outcome == INELIGIBLE:
            out.append(item_id)
    return out


def review_sort_key(result: Resolution) -> float:
    """The ascending key a notebook sorts ``REVIEW`` plans by before submitting them to the
    simulated queue: the lowest confidence among the four constraints, so the pair Python is
    least sure about -- on any constraint -- surfaces first."""
    if not result.decisions:
        raise ValueError("review_sort_key needs label decisions; this resolution has none")
    return min(d.confidence for d in result.decisions.values())


def gating_label(result: Resolution) -> str:
    """The name of the constraint whose answer actually sent this plan to review: the one whose
    confidence is :func:`review_sort_key`'s minimum (a gated constraint is below the shared
    gate by definition, so the lowest-confidence constraint is always a gated one). Ties break
    in ``CONSTRAINTS`` order. A queue entry's recorded answer should be this constraint's, not
    always ``budget``, so a reviewer reading "the typed answer that sent this item to review" is
    shown the answer the reason is actually about."""
    if not result.decisions:
        raise ValueError("gating_label needs label decisions; this resolution has none")
    return min(CONSTRAINTS, key=lambda c: result.decisions[c].confidence)


def queue_item(plan_id: str, fields: dict[str, Any], result: Resolution) -> dict[str, Any]:
    """What a human reviewer sees for one queued plan: its id, the plan's own text, the
    user's own four constraint statements, the plan's cost and completion date beside the limit
    and deadline with the two checks Python computed from them, and every constraint's label
    decision -- not only
    an identifier (CONTRIBUTING.md section 4: the queue is the side effect a ``review``
    outcome triggers, and an item with nothing to read is not something a person can actually
    review)."""
    return {
        "id": plan_id,
        "plan": fields["plan"],
        "user_constraints": dict(fields["user_constraints"]),
        "cost": fields["cost"],
        "budget_limit": fields["budget_limit"],
        "completion": fields["completion"],
        "deadline": fields["deadline"],
        "computed_checks": computed_checks(fields),
        **{c: {"noul": d.noul, "confidence": d.confidence} for c, d in result.decisions.items()},
    }


# --------------------------------------------------------------------------------------------
# A stateful walkthrough: Python's own running remaining-budget figure, threaded across a
# sequence of plans proposed against the same department budget -- never read from the model.
# The number itself IS part of what the model reads (the budget constraint names a concrete
# limit), but which number that is, at each step, is Python's own bookkeeping: the caller
# recomputes it after each plan and bakes the new figure into the next plan's own
# ``user_constraints["budget"]`` text before ``build_state`` ever runs.
# --------------------------------------------------------------------------------------------


def remaining_budget_after(remaining_budget: float, outcome: str, cost: float) -> float:
    """The running remaining budget after one plan in a sequence is resolved against it.

    An ``ELIGIBLE`` plan is the only kind that spends anything: ``remaining_budget - cost``.
    An ``INELIGIBLE`` or ``REVIEW`` plan is never actually run (CONTRIBUTING.md section 4: no
    plan is ever executed), so it commits nothing and the remaining budget is unchanged for
    whatever plan in the sequence comes next.
    """
    if outcome == ELIGIBLE:
        return remaining_budget - cost
    return remaining_budget
