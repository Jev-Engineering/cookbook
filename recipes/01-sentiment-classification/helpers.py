"""Python's half of recipe 01: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed option set the catalog's use case names. There is no separate "none of the above"
# option: every short customer review has *some* overall sentiment, and a review with genuinely
# conflicting signal is exactly what MIXED is for, not a reason to force it into POSITIVE or
# NEGATIVE.
POSITIVE = "positive"
NEUTRAL = "neutral"
NEGATIVE = "negative"
MIXED = "mixed"
OPTIONS = (POSITIVE, NEUTRAL, NEGATIVE, MIXED)

ACCEPTED = "accepted"
REVIEW = "review"

# Descriptions that say what each option covers and, where two options are easy to confuse,
# what belongs to the other one instead (TypeSafe's guidance for options that are easy to
# confuse: say what doesn't belong to a neighbouring option).
_DESCRIPTIONS = {
    POSITIVE: (
        "The review is favorable overall: the customer is satisfied or pleased, with no "
        "significant complaint. A short review with only praise is positive, not mixed."
    ),
    NEUTRAL: (
        "The review states facts about the order, the product or the experience without "
        "expressing satisfaction or dissatisfaction, or expresses no strong feeling either way."
    ),
    NEGATIVE: (
        "The review is unfavorable overall: the customer is dissatisfied or frustrated, with "
        "no significant praise. A short review with only a complaint is negative, not mixed."
    ),
    MIXED: (
        "The review expresses both praise and complaint about the same purchase, such as "
        "liking one thing about it while disliking another, or being satisfied with the "
        "product but not the service (or the reverse)."
    ),
}


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one review: the review text, and nothing else.

    ``fields`` also carries ``review_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the outcome, so it never needs to pass through the model.
    """
    return {"text": fields["text"]}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every review. The options come from ``OPTIONS``."""
    return {
        "sentiment": Choice(
            instructions="What is the overall sentiment of this customer review?",
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


@dataclass(frozen=True)
class Classification:
    """What Python decided: the label Jev chose, and whether it is accepted or sent to review."""

    review_id: str
    label: str
    outcome: str
    reason: str


def classify(review_id: str, answer: Any, min_confidence: float) -> Classification:
    """Accept the chosen sentiment only when the answer is confident enough.

    Every option is a label Python is willing to report (there is no option to reject, unlike
    a router that only recognises some options as queues), so the only question is confidence:
    an answer at or above ``min_confidence`` is accepted as is; anything below it goes to an
    explicit ``review`` outcome instead of being reported as a result. The rule is code, so it
    holds whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.confidence < min_confidence:
        return Classification(review_id, answer.choice, REVIEW, "confidence below the threshold")
    return Classification(review_id, answer.choice, ACCEPTED, "confident")
