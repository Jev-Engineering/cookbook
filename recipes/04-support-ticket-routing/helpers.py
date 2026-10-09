"""Python's half of recipe 04: the state, the question and the rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed service categories the catalog's use case names, each mapped to the simulated queue
# Python routes a confident, accepted answer to. ``UNCLEAR_REQUEST`` is not a queue: it is the
# explicit fallback outcome this use case names for a ticket that does not resolve to one of the
# categories below (CONTRIBUTING.md section 3: "Include none, other, no_match, or uncertain
# outcomes when the use case calls for them.").
BILLING = "billing"
TECHNICAL_ISSUE = "technical_issue"
ACCOUNT_ACCESS = "account_access"
FEATURE_REQUEST = "feature_request"
UNCLEAR_REQUEST = "unclear_request"

QUEUES = {
    BILLING: "billing-queue",
    TECHNICAL_ISSUE: "tech-support-queue",
    ACCOUNT_ACCESS: "account-queue",
    FEATURE_REQUEST: "product-queue",
}
OPTIONS = (*QUEUES, UNCLEAR_REQUEST)

# Outcomes Python's rule can produce.
ROUTED = "routed"
REVIEW = "review"
UNCLEAR = "unclear"

# Descriptions say what belongs to each category and, for the two pairs that are easiest to
# confuse (billing vs. account_access; technical_issue vs. feature_request), what belongs to
# the other option instead (TypeSafe's guidance for options that are easy to confuse: say what
# doesn't belong to a neighbouring option).
_DESCRIPTIONS = {
    BILLING: (
        "The ticket is about a charge, invoice, payment method, subscription renewal, or "
        "refund. A request to change who can sign in or what they can do belongs to "
        "account_access instead, even if the ticket also mentions a charge."
    ),
    TECHNICAL_ISSUE: (
        "The ticket reports the product failing to work as built: an error message, a crash, "
        "a page or feature that does not load, or data that looks wrong. A request for a "
        "capability the product does not have belongs to feature_request instead."
    ),
    ACCOUNT_ACCESS: (
        "The ticket is about signing in, resetting a password, two-factor codes, or who is "
        "allowed to use the account. A charge or invoice question belongs to billing instead, "
        "even if the customer also mentions being logged out."
    ),
    FEATURE_REQUEST: (
        "The ticket asks for a capability the product does not currently have, or a change to "
        "how it behaves by design. A report that an existing feature is broken belongs to "
        "technical_issue instead, even if the customer frames it as a suggestion."
    ),
    UNCLEAR_REQUEST: (
        "The ticket does not contain enough information to assign one of the other categories, "
        "raises several unrelated requests that do not resolve to a single category, or is not "
        "about the product or the account at all."
    ),
}


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one ticket: the subject and the description, kept as two
    structured fields rather than concatenated into one string, so Python (and a reader) can
    always tell which part of the ticket a word came from.

    ``fields`` also carries ``ticket_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the outcome, so it never needs to pass through the model.
    """
    return {"subject": fields["subject"], "description": fields["description"]}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every ticket. The options come from ``OPTIONS``."""
    return {
        "category": Choice(
            instructions="Which service category does this support ticket belong to?",
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


@dataclass(frozen=True)
class Routing:
    """What Python decided: the category Jev chose, the outcome, the simulated queue (only
    when the outcome is ``routed``), and why."""

    ticket_id: str
    label: str
    outcome: str
    queue: str | None
    reason: str


def route_ticket(ticket_id: str, answer: Any, min_confidence: float) -> Routing:
    """Route a ticket to its simulated queue only when the answer names a real category and is
    confident enough.

    ``unclear_request`` is never routed to a queue, whatever its confidence: the option itself
    already says the ticket does not resolve to one category, so Python lists it separately
    instead of running it past the confidence gate meant for a queue it will never enter. Any
    other answer that is not confident enough goes to an explicit ``review`` outcome instead of
    being reported as a routed result. The rule is code, so it holds whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == UNCLEAR_REQUEST:
        return Routing(
            ticket_id, UNCLEAR_REQUEST, UNCLEAR, None, "the ticket does not resolve to one category"
        )
    if answer.confidence < min_confidence:
        return Routing(ticket_id, answer.choice, REVIEW, None, "confidence below the threshold")
    return Routing(ticket_id, answer.choice, ROUTED, QUEUES[answer.choice], "confident match")
