"""Python's half of recipe 38: the state, the question and the rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed queues this use case names, plus the explicit fallback option (CONTRIBUTING.md
# section 3: "Include none, other, no_match, or uncertain outcomes when the use case calls for
# them."). A ticket is routed to exactly one of these; Python, not Jev, decides what happens
# next with that choice.
SELF_SERVE = "self_serve"
TIER1_SUPPORT = "tier1_support"
TIER2_ENGINEERING = "tier2_engineering"
INSUFFICIENT_INFORMATION = "insufficient_information"

OPTIONS = (SELF_SERVE, TIER1_SUPPORT, TIER2_ENGINEERING, INSUFFICIENT_INFORMATION)
# The three options a confidence gate can ever route automatically. insufficient_information is
# deliberately excluded: it is never a candidate for automatic routing, so only an answer naming
# one of these three can set (or clear) the confidence threshold below.
REAL_QUEUES = (SELF_SERVE, TIER1_SUPPORT, TIER2_ENGINEERING)

# Outcomes Python's rule can produce.
ANSWERED = "answered"
REVIEW = "review"

# Descriptions say what belongs to each option and, for the two pairs that are easiest to
# confuse (self_serve vs. tier1_support; tier1_support vs. tier2_engineering), what belongs to
# the neighbouring option instead (TypeSafe's guidance for options that are easy to confuse: say
# what doesn't belong to a neighbouring option).
_DESCRIPTIONS = {
    SELF_SERVE: (
        "The request is a common how-to question the help center already answers without any "
        "account-specific investigation: resetting a password while still signed in, how a "
        "billing cycle or a trial works, where a feature lives. A request that needs a human to "
        "verify identity, change something only support can reach, or look into this specific "
        "account belongs to tier1_support instead."
    ),
    TIER1_SUPPORT: (
        "The request needs a support agent to look at or change something specific to this "
        "account: verifying identity to recover access, adjusting a subscription or refund, "
        "granting a teammate access, or resending a document support alone can issue. A report "
        "that the product is failing to work as built belongs to tier2_engineering instead, "
        "even if a human still has to look at the account to confirm it."
    ),
    TIER2_ENGINEERING: (
        "The request reports the product failing to behave as it was built to: an error, a "
        "crash, a page or export that will not load, or data that is visibly wrong. A request "
        "to change how the account itself is set up, with no sign the product is broken, "
        "belongs to tier1_support instead."
    ),
    INSUFFICIENT_INFORMATION: (
        "The message does not contain enough information to tell which of the above applies, "
        "raises several unrelated requests that do not resolve to one queue, or is not about "
        "the product or the account at all."
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
        "queue": Choice(
            instructions="Which support queue should this ticket be routed to?",
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


@dataclass(frozen=True)
class Routing:
    """What Python decided for one ticket: the label Jev named, the outcome, and why.

    ``label`` is always the raw choice, whatever the outcome -- a ``review`` routing still
    names which queue (or ``insufficient_information``) Jev picked, so a reader of the review
    queue can see what the model thought even though Python did not act on it automatically.
    """

    ticket_id: str
    label: str
    outcome: str
    reason: str


def route_ticket(ticket_id: str, answer: Any, min_confidence: float) -> Routing:
    """Route a ticket automatically only when the answer names a real queue and is confident
    enough; everything else goes to an explicit ``review`` outcome instead of being reported as
    an automatic routing.

    ``insufficient_information`` is never routed automatically, whatever its confidence: the
    option itself already says the ticket does not resolve to one queue, so sending it to a
    person is not conditioned on the confidence gate meant for a queue it will never enter (the
    same shape recipe 4's ``unclear_request`` and the template's ``none`` use). This passes every
    part of CONTRIBUTING.md section 4's three-part test on its own -- it is a complete answer,
    not a deferral; nothing is recorded as an action; being wrong leaves nothing standing beyond
    the missed ticket itself -- but this rule still sends it to review like every other
    unconfident or unrecognized case rather than claim that exemption, exactly as the template's
    ``none`` does: the test names when the exemption is *available*, not when it is required.
    The rule is code, so it holds whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == INSUFFICIENT_INFORMATION:
        return Routing(
            ticket_id,
            INSUFFICIENT_INFORMATION,
            REVIEW,
            "not enough information to classify",
        )
    if answer.confidence < min_confidence:
        return Routing(ticket_id, answer.choice, REVIEW, "confidence below the threshold")
    return Routing(ticket_id, answer.choice, ANSWERED, "confident match")
