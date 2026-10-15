"""Python's half of recipe 42: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------- Sharing rules
#
# Two sharing rules, supplied by Python, each written as a statement that is true or false of a
# proposed outbound message (CONTRIBUTING.md section 3: "Noul propositions are written as
# statements that can be true or false"). Both are asked together, in one request, about every
# message -- one independent Noul per supplied sharing rule for each proposed outbound message
# (CONTRIBUTING.md section 3: "Independent questions go in one request"). Jev never sees the
# rule names below, only the ``instructions`` text each one carries.
PRICING = "pricing"
CONTACT = "contact"
RULES = (PRICING, CONTACT)

_STATEMENTS = {
    PRICING: (
        "This message states a specific price, discount percentage, budget figure, or deal "
        "term for a Meridian Robotics product, service, or contract that Meridian Robotics has "
        "not already published."
    ),
    CONTACT: (
        "This message discloses a specific individual's personal contact details -- a direct "
        "phone number, a home address, or a personal email address -- or an internal employee "
        "badge or system account identifier, specific enough to reach or identify that one "
        "person or system."
    ),
}

_CRITERIA = {
    PRICING: {
        "true": (
            "The message states a specific number that functions as a price, a discount, a "
            "budget figure, or a deal term for a Meridian Robotics product, service, or "
            "contract, and that figure is not already part of Meridian Robotics' published "
            "price list or a public announcement. It counts even when it is only one detail "
            "among several in the message, and even when it is described in words rather than "
            'digits ("forty percent off").'
        ),
        "false": (
            "The message states no such figure, states only a figure that is already part of "
            "Meridian Robotics' published price list or a public announcement, discusses "
            "pricing only in general terms with no number attached, or gives a number that is "
            "not a price, discount, budget, or deal term at all -- a date, an order or ticket "
            "reference, a quantity of items, or a percentage describing something other than a "
            "discount."
        ),
    },
    CONTACT: {
        "true": (
            "The message gives a specific individual's personal phone number, home address, or "
            "personal email address, or an internal employee badge or system account "
            "identifier, specific enough that a reader could use it to reach or identify that "
            "one person or system directly."
        ),
        "false": (
            "The message gives no such detail: it names only a shared or official contact "
            "point (a general support line, a company's own published office address, a team "
            "mailbox), it mentions a person by name alone with no contact or identifying detail "
            "attached, or it uses a number or reference that is not a personal contact detail "
            "or an identifier at all -- an order number, a tracking reference, a date."
        ),
    },
}


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one proposed message: its text, nothing else.

    ``fields`` also carries ``thread_id`` and ``sequence``, Python's own bookkeeping for the
    thread-escalation policy below. Neither reaches the model: two messages with the same text
    but different thread bookkeeping share one replay key, the same pattern recipe 15's
    text-only state uses.
    """
    return {"message": fields["text"]}


def build_questions() -> dict[str, Noul]:
    """The sharing-rule battery: one independent Noul per rule in ``RULES``, built from the
    same names every other function here uses, so the questions and the rule can never drift
    apart."""
    return {rule: Noul(instructions=_STATEMENTS[rule], criteria=_CRITERIA[rule]) for rule in RULES}


# --------------------------------------------------------------------------- Per-rule verdicts
#
# Three outcomes per rule, not two -- the same shape as the Noul three-path pattern
# (docs/evaluation.md): a confidence gate first (whichever way the probability leans), then a
# business threshold. CONTRIBUTING.md section 4: "Uncertain or inconsistent results go to an
# explicit review outcome."
VIOLATES = "violates"
CLEAR = "clear"
REVIEW = "review"


@dataclass(frozen=True)
class RuleVerdict:
    """One sharing rule's own outcome for one message: ``violates``, ``clear``, or ``review``,
    with the ``noul`` it was decided from carried alongside it (CONTRIBUTING.md section 3:
    every result traces back to its source)."""

    rule: str
    verdict: str
    noul: float
    reason: str


def verdict_for_rule(
    rule: str, noul: float, threshold: float, min_confidence: float
) -> RuleVerdict:
    """Decide one rule's outcome for one message.

    The confidence gate (``min_confidence``, ``noul_confidence``: distance from an even split)
    is checked first, independently of which way the probability leans: a verdict whose
    confidence does not clear the gate is ``review``, whatever its probability is. Only once a
    verdict clears the confidence gate does the business ``threshold`` decide ``violates`` or
    ``clear``. The rule is code, so it holds whatever the model answers.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold!r}")
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    confidence = noul_confidence([noul])[0]
    if confidence < min_confidence:
        return RuleVerdict(rule, REVIEW, noul, "confidence below the threshold")
    if noul >= threshold:
        return RuleVerdict(rule, VIOLATES, noul, f"noul at or above the {rule} threshold")
    return RuleVerdict(rule, CLEAR, noul, f"noul below the {rule} threshold")


# --------------------------------------------------------------------------- Message-level screening
#
# Nothing in this recipe sends a message. ``ALLOWED`` means Python would release the message in
# the simulation -- see the notebook's "Python's part" section, where the simulated action is
# logged and never executed. ``HELD`` means the message waits for a person, whatever the reason.
HELD = "held"
ALLOWED = "allowed"


@dataclass(frozen=True)
class ScreeningResult:
    """What Python decided about one proposed outbound message. ``verdicts`` is each rule's own
    ``RuleVerdict``, carried through unchanged, so a reader can see exactly which rule (if any)
    caused a hold -- never recomputed from ``noul`` a second time."""

    message_id: str
    outcome: str
    reason: str
    verdicts: tuple[RuleVerdict, ...]


def screen_message(
    message_id: str, verdicts: tuple[RuleVerdict, ...], thread_escalated: bool
) -> ScreeningResult:
    """Decide ``held`` or ``allowed`` for one message, from its own rules' verdicts and from
    whether its thread was already escalated by an earlier held message in the same thread.

    In order, most restrictive first:

    1. a thread already escalated by an earlier message holds this one outright, whatever its
       own verdicts say -- a deterministic policy rule, not a re-judgment of this message's own
       content (CONTRIBUTING.md section 4: Python owns every stop condition, and this one holds
       for any model answer because it never reads one);
    2. any rule confidently ``violates`` holds the message, naming which rule(s);
    3. any rule's confidence gate was not cleared (``review``) holds the message for a person to
       decide, naming which rule(s) were uncertain;
    4. otherwise every rule confidently cleared: the message is ``allowed``.

    This function never calls a backend and never reads an answer object directly -- only the
    ``RuleVerdict``s already decided -- which is what makes it, and the thread escalation below,
    testable against any combination of verdicts a model could ever produce.
    """
    if thread_escalated:
        return ScreeningResult(message_id, HELD, "thread previously held", verdicts)
    violated = [v.rule for v in verdicts if v.verdict == VIOLATES]
    if violated:
        return ScreeningResult(message_id, HELD, f"violates: {', '.join(violated)}", verdicts)
    uncertain = [v.rule for v in verdicts if v.verdict == REVIEW]
    if uncertain:
        return ScreeningResult(message_id, HELD, f"uncertain: {', '.join(uncertain)}", verdicts)
    return ScreeningResult(message_id, ALLOWED, "every rule confidently clear", verdicts)


def screen_thread(
    entries: list[tuple[str, dict[str, float]]],
    thresholds: dict[str, float],
    min_confidence: float,
) -> list[ScreeningResult]:
    """Screen every message of one thread, in sequence order, carrying the escalation state
    forward from one message to the next.

    ``entries`` is ``(message_id, noul_by_rule)`` in the order the messages were proposed.
    Returns one ``ScreeningResult`` per entry, in the same order. Once any message in the
    thread is held, every later message in it is held outright by ``screen_message``'s thread
    rule, regardless of what its own verdicts say -- a deterministic safety-net policy, not a
    re-judgment of later content. Calling this once per thread, over the whole thread in order,
    is what makes the escalation state apply correctly; screening a thread's messages one at a
    time elsewhere would lose it.
    """
    escalated = False
    results = []
    for message_id, noul_by_rule in entries:
        verdicts = tuple(
            verdict_for_rule(rule, noul_by_rule[rule], thresholds[rule], min_confidence)
            for rule in RULES
        )
        result = screen_message(message_id, verdicts, escalated)
        if result.outcome == HELD:
            escalated = True
        results.append(result)
    return results


# --------------------------------------------------------------------------- Message-level metrics
#
# This recipe's own three metrics. They are scoped to the final held/allowed decision against
# each message's own content -- CONTRIBUTING.md's accuracy/precision/recall lexicon names none of
# these, so they are this recipe's own, not a jev_cookbook.evaluation function.
@dataclass(frozen=True)
class ScreeningMetrics:
    """``missed_disclosure_rate``: of the messages whose own content violates at least one
    sharing rule, the share that were allowed anyway -- a real disclosure that slipped through.
    NaN when no message's content violates anything (nothing to miss), never 0.0, the same
    undefined-is-NaN convention ``jev_cookbook.evaluation`` uses throughout.

    ``false_hold_rate``: of the messages whose own content violates no sharing rule, the share
    that were held anyway, for any reason (the confidence gate or thread escalation) -- the
    reviewer workload this rule spends on messages that needed no hold on their own content.
    NaN when every message's content violates something.

    ``hold_rate``: the share of every scored message that was held, whatever the reason.
    """

    missed_disclosure_rate: float
    false_hold_rate: float
    hold_rate: float
    n_total: int
    n_content_violates: int
    n_content_clear: int
    n_held: int


def screening_metrics(content_violates: list[bool], held: list[bool]) -> ScreeningMetrics:
    """``content_violates[i]``: does message ``i``'s own content violate at least one sharing
    rule, by its gold labels (never from a model). ``held[i]``: the final system decision --
    ``screen_message``'s ``outcome == HELD`` -- for the same message, gate and thread escalation
    both included. Both are required and must have the same length (``ValueError`` otherwise, no
    metric for no data, matching ``jev_cookbook.evaluation``'s own rule)."""
    if len(content_violates) != len(held):
        raise ValueError("content_violates and held must have the same length")
    if not content_violates:
        raise ValueError("screening_metrics needs at least one message")
    n_total = len(content_violates)
    violates_idx = [i for i, v in enumerate(content_violates) if v]
    clear_idx = [i for i, v in enumerate(content_violates) if not v]
    missed = sum(1 for i in violates_idx if not held[i])
    false_held = sum(1 for i in clear_idx if held[i])
    n_held = sum(1 for h in held if h)
    missed_rate = missed / len(violates_idx) if violates_idx else float("nan")
    false_rate = false_held / len(clear_idx) if clear_idx else float("nan")
    return ScreeningMetrics(
        missed_disclosure_rate=missed_rate,
        false_hold_rate=false_rate,
        hold_rate=n_held / n_total,
        n_total=n_total,
        n_content_violates=len(violates_idx),
        n_content_clear=len(clear_idx),
        n_held=n_held,
    )
