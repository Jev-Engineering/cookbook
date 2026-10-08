"""Python's half of recipe 02: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The one proposition this recipe asks, written as a statement that is true or false
# (CONTRIBUTING.md section 3: "Noul propositions are written as statements that can be true or
# false"), not as a question. "Explicitly" is doing real work here: a complaint, a policy
# question, or a mention of some other refund are all close to this statement without making it
# true, and the fixtures (build_fixtures.py) include one of each as a near miss.
STATEMENT = "This message explicitly asks for a refund for the customer's current order."

_CRITERIA = {
    "true": (
        "The message asks, right now, for money back on a purchase: using the word refund, "
        "asking for a replacement's cost back, or an unmistakable equivalent such as 'give me "
        "my money back'. The request can be calm, angry, buried in a longer message, or as "
        "short as 'Refund now.'; it is still explicit if a reasonable reader has no doubt the "
        "customer wants their money back for this order."
    ),
    "false": (
        "The message does not currently ask for money back on this order. This covers a plain "
        "complaint with no request attached, a question about refund policy in general, a "
        "request for a replacement or store credit instead of a refund, a refund mentioned only "
        "in passing (a past order, a hypothetical, a future possibility), and a request to "
        "cancel a subscription or return an item without saying the word refund or its "
        "equivalent."
    ),
}

FLAGGED = "flagged"
NOT_FLAGGED = "not_flagged"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one message: the message text, and nothing else.

    ``fields`` also carries ``ticket_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the outcome, so it never needs to pass through the model.
    """
    return {"text": fields["text"]}


def build_questions() -> dict[str, Noul]:
    """The one proposition asked about every message."""
    return {"refund_requested": Noul(instructions=STATEMENT, criteria=_CRITERIA)}


@dataclass(frozen=True)
class RefundRoute:
    """What Python decided: whether the message is flagged for the refund workflow."""

    ticket_id: str
    flagged: bool
    outcome: str
    reason: str


def route(ticket_id: str, answer: Any, threshold: float) -> RefundRoute:
    """Flag a message for the refund workflow queue when its noul clears the threshold.

    A Noul answer has no confidence field (unlike Choice or Score), so there is nothing to
    gate on besides the probability itself: ``flagged`` is simply ``answer.noul >= threshold``.
    A flagged message is queued for a person on the refund team to review and act on; an
    unflagged one needs no further action. The rule is code, so it holds whatever the model
    answers, and it is the only place this decision is made: the evaluation below calls this
    function rather than re-checking ``noul >= threshold`` itself.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold!r}")
    if answer.noul >= threshold:
        return RefundRoute(
            ticket_id, True, FLAGGED, "noul at or above the threshold: queued for refund review"
        )
    return RefundRoute(
        ticket_id, False, NOT_FLAGGED, "noul below the threshold: no refund action needed"
    )
