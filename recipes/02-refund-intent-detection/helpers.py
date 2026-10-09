"""Python's half of recipe 02: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence

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
        "The message asks, right now, for money back on a purchase: using the word refund, or "
        "an unmistakable equivalent such as 'give me my money back'. The request can be calm, "
        "angry, buried in a longer message, or as short as 'Refund now.'; it is still explicit "
        "if a reasonable reader has no doubt the customer wants their money back for this "
        "order, even if the ask is hedged ('if that's possible')."
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

# Three outcomes, not two. CONTRIBUTING.md section 4: "Uncertain or inconsistent results go to
# an explicit review outcome." A Noul has no `confidence` field, but TypeSafe's confidence page
# (S03) gives the certainty reading for one anyway: distance from an even split, |2p - 1| (the
# Choice confidence formula applied to a yes/no Choice), which `jev_cookbook.evaluation.noul_confidence`
# computes. A message whose certainty does not clear `min_confidence` goes to REVIEW regardless
# of which side of `threshold` its probability sits on, matching the three-path pattern
# (TypeSafe's own Noul documentation: act above a high cut-off, act below a low one, and route
# the mid-range to human review). Only a message that clears both the certainty gate and the
# business threshold is FLAGGED for the refund workflow; one that clears the certainty gate but
# not the threshold is NOT_FLAGGED, confidently.
FLAGGED = "flagged"
REVIEW = "review"
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
    """What Python decided: flag for the refund workflow, send to review, or do nothing.

    ``would_flag`` is the business decision alone (``noul >= threshold``), computed whatever
    ``outcome`` turns out to be, so that code which needs it (the evaluation's selective-prediction
    numbers) can read it here instead of re-deriving it from ``noul`` and ``threshold`` a second
    time.
    """

    ticket_id: str
    outcome: str
    would_flag: bool
    reason: str


def route(ticket_id: str, answer: Any, threshold: float, min_confidence: float) -> RefundRoute:
    """Decide one of three outcomes for a message, in this order: review, then flag, then nothing.

    ``min_confidence`` gates on certainty (``noul_confidence``, distance from an even split),
    independently of which way the probability leans: a message too close to 0.5 to trust either
    way goes to ``REVIEW``, whatever its probability is. Only once a message clears that gate
    does ``threshold`` decide the business action: ``FLAGGED`` when the probability is at or
    above it, ``NOT_FLAGGED`` otherwise. The rule is code, so it holds whatever the model
    answers, and it is the only place this decision is made: the evaluation calls this function
    rather than re-checking ``noul >= threshold`` itself.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold!r}")
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    would_flag = answer.noul >= threshold
    certainty = noul_confidence([answer.noul])[0]
    if certainty < min_confidence:
        return RefundRoute(
            ticket_id,
            REVIEW,
            would_flag,
            "too close to an even split to trust either way: needs a person",
        )
    if would_flag:
        return RefundRoute(
            ticket_id,
            FLAGGED,
            True,
            "noul at or above the threshold: queued for the refund workflow",
        )
    return RefundRoute(
        ticket_id, NOT_FLAGGED, False, "noul below the threshold: no refund action needed"
    )
