"""Python's half of the template recipe: what Jev sees, what Jev is asked, and what is done.

A recipe's helpers hold logic that is too long to read comfortably in a notebook cell. The
fixture generator, the notebook and the tests all load this one file with
``jev_cookbook.load_helpers``, so the questions, the state and the rule cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# The queues Python is allowed to send a ticket to. Jev never sees these names as actions: it
# only picks an option, and Python decides what that option may do.
QUEUES = {
    "billing": "billing-team",
    "bug": "support-engineering",
    "account": "account-help",
}
NONE = "none"
REVIEW = "human_review"

_DESCRIPTIONS = {
    "billing": "charges, invoices, refunds, payment methods and renewals",
    "bug": "the product misbehaving: errors, crashes, pages that do not load",
    "account": "signing in, passwords, profile details and who can use the account",
    NONE: "anything else, or a message that fits none of the other options",
}


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one ticket: the subject and the message, nothing else.

    ``fields`` also carries the ticket reference. Python keeps it and attaches it to the
    outcome, so it never needs to pass through the model.
    """
    return {"subject": fields["subject"], "message": fields["message"]}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every ticket. The options come from ``QUEUES``."""
    criteria = {name: _DESCRIPTIONS[name] for name in (*QUEUES, NONE)}
    return {
        "route": Choice(
            instructions="Which kind of support request is this message?",
            criteria=criteria,
        )
    }


@dataclass(frozen=True)
class Routing:
    """What Python decided: a queue, or ``human_review`` with the reason."""

    ticket: str
    outcome: str
    reason: str


def route(ticket: str, answer: Any, min_confidence: float) -> Routing:
    """Send a ticket to a queue only when the answer is a known queue and confident enough.

    Everything else goes to ``human_review``: the ``none`` option, an option that is not one
    of ``QUEUES``, and any confidence below ``min_confidence``. The rule is code, so it holds
    whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == NONE:
        return Routing(ticket, REVIEW, "no option fits")
    if answer.choice not in QUEUES:
        return Routing(ticket, REVIEW, "not a queue Python may use")
    if answer.confidence < min_confidence:
        return Routing(ticket, REVIEW, "confidence below the threshold")
    return Routing(ticket, QUEUES[answer.choice], "confident match")
