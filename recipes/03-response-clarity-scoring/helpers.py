"""Python's half of recipe 03: the state, the question and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Score
from jev_cookbook.evaluation import score_level

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The clarity rubric, lowest level first. Each level is judged on its own against the response
# text (TypeSafe's jaggedness notes, S07 item 1: the model sees the description and nothing
# else, not a level's number or its neighbours), so every description stands alone: it names
# what a reader of the response can and cannot do, never "clearer than the level above".
CONFUSING = (
    "The reader cannot tell what happened to their request or what to do next without asking "
    "a follow-up question. The response omits the key fact, uses an undefined internal term or "
    "acronym, or contains two statements that contradict each other."
)
NEEDS_WORK = (
    "The reader can find the outcome or the next step only by rereading or by filling in "
    "something the response does not state. The response does answer the question, but a "
    "pronoun or reference could point to more than one thing, a term is used without being "
    "defined, or part of the action is left for the reader to work out."
)
CLEAR = (
    "The reader understands the outcome and the next step the first time they read the "
    "response. The language is specific and the step is stated, though a sentence could be "
    "shorter, better ordered, or a term could be spelled out without changing what the "
    "response says."
)
EXEMPLARY = (
    "The reader understands the outcome and the exact next step immediately, in plain "
    "language. Every term is already defined or is not needed, there is no detail that does "
    "not bear on the outcome, and nothing is left for the reader to infer."
)
CLARITY_LEVELS = (CONFUSING, NEEDS_WORK, CLEAR, EXEMPLARY)  # level 0 to level 3

# The cutoff lives in code, per the issue: a response whose most likely level is below CLEAR
# (level 2) needs an edit before it reaches a customer. This is a fixed editorial decision, not
# a value chosen by searching validation: unlike the confidence threshold below, there is no
# "selecting" step for it, which is also why it is a plain module constant and not an argument.
EDIT_CUTOFF = 2

NEEDS_EDIT = "needs_edit"
ACCEPTED = "accepted"
REVIEW = "review"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one support response: the response text, and nothing else.

    ``fields`` also carries ``response_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the outcome, so it never needs to pass through the model.
    """
    return {"response": fields["response"]}


def build_questions() -> dict[str, Score]:
    """The one question asked about every response. The levels come from ``CLARITY_LEVELS``."""
    return {
        "clarity": Score(
            instructions=("How clear is this support response to the customer who will read it?"),
            criteria=list(CLARITY_LEVELS),
        )
    }


@dataclass(frozen=True)
class Classification:
    """What Python decided: the level Jev's answer most likely holds, and the outcome."""

    response_id: str
    level: int
    outcome: str
    reason: str


def classify(response_id: str, answer: Any, min_confidence: float) -> Classification:
    """Act on a clarity answer: trust it only when confident enough, then apply the cutoff.

    Confidence gates whether the score is trustworthy at all: below ``min_confidence`` the
    answer goes to an explicit ``review`` outcome, whatever its level, because a spread-out
    distribution is not solid ground for an editorial call. At or above it, the rule applies
    the fixed ``EDIT_CUTOFF``: a trusted answer whose most likely level (:func:`score_level`,
    the modal level, ties going to the lower one) falls below ``CLEAR`` is flagged
    ``needs_edit``; the rest are ``accepted`` as not needing one. The rule is code, so it holds
    whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    level = score_level(answer)
    if answer.confidence < min_confidence:
        return Classification(response_id, level, REVIEW, "confidence below the threshold")
    if level < EDIT_CUTOFF:
        return Classification(response_id, level, NEEDS_EDIT, "score below the clarity cutoff")
    return Classification(response_id, level, ACCEPTED, "clear enough, no edit needed")
