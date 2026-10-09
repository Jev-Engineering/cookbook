"""Python's half of recipe 10: the state, the questions and the rules.

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
# false"), not as a question. "Actually asked" carries the weight of this recipe's hard cases: a
# fluent, on-topic-sounding reply that answers a *different* question is the near miss this
# wording is written to exclude, and build_fixtures.py includes several of exactly that shape.
STATEMENT = "This response addresses the question the user actually asked."

_CRITERIA = {
    "true": (
        "The response engages with what the user is actually asking, and gives information a "
        "reader could use to answer their question -- even if the answer is brief, incomplete, "
        "or only partly covers what was asked. A response that confirms, explains, or resolves "
        "the real ask counts as addressing it, however it is phrased."
    ),
    "false": (
        "The response does not engage with what the user is actually asking. This covers a "
        "reply that is fluent and on-topic for the general subject but actually answers a "
        "different question, a generic or templated reply with no information specific to this "
        "question, a reply that only repeats the question back, a reply that deflects or hedges "
        "without giving an answer, and a reply about an unrelated subject entirely."
    ),
}

# Three outcomes, not two. CONTRIBUTING.md section 4: "Uncertain or inconsistent results go to
# an explicit review outcome." A Noul has no `confidence` field in the API response, but
# `jev_cookbook.evaluation.noul_confidence` computes one anyway: the Choice confidence formula
# applied to a yes/no Choice, `|2p - 1|`, on the same 0-1 scale as Choice and Score confidence
# (docs/evaluation.md, "Noul three-path pattern", S03). A pair whose confidence does not clear
# `min_confidence` goes to REVIEW regardless of which side of `threshold` its probability sits
# on, matching that three-path pattern (TypeSafe's own Noul documentation: act above a high
# cut-off, act below a low one, and route the mid-range to human review). Only a pair that clears
# both the confidence gate and the business threshold is RELEVANT; one that clears the confidence
# gate but falls below the threshold is NOT_RELEVANT, confidently.
RELEVANT = "relevant"
REVIEW = "review"
NOT_RELEVANT = "not_relevant"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one pair: the question and the candidate response, nothing else.

    ``fields`` also carries ``pair_id``, a bookkeeping identifier. Python keeps it and attaches
    it to the outcome, so it never needs to pass through the model.
    """
    return {"question": fields["question"], "response": fields["response"]}


def build_questions() -> dict[str, Noul]:
    """The one proposition asked about every (question, response) pair."""
    return {"relevant": Noul(instructions=STATEMENT, criteria=_CRITERIA)}


@dataclass(frozen=True)
class RelevanceCheck:
    """What Python decided: relevant, not relevant, or sent to review.

    ``is_relevant`` is the business decision alone (``noul >= threshold``), computed whatever
    ``outcome`` turns out to be, so that code which needs it (the evaluation's selective-
    prediction numbers) can read it here instead of re-deriving it from ``noul`` and
    ``threshold`` a second time.
    """

    pair_id: str
    outcome: str
    is_relevant: bool
    reason: str


def check_relevance(
    pair_id: str, answer: Any, threshold: float, min_confidence: float
) -> RelevanceCheck:
    """Decide one of three outcomes for a (question, response) pair: review, then relevant,
    then not relevant, in that order.

    ``min_confidence`` gates on certainty (``noul_confidence``, distance from an even split),
    independently of which way the probability leans: a pair too close to 0.5 to trust either
    way goes to ``REVIEW``, whatever its probability is. Only once a pair clears that gate does
    ``threshold`` decide the business outcome: ``RELEVANT`` when the probability is at or above
    it, ``NOT_RELEVANT`` otherwise. The rule is code, so it holds whatever the model answers, and
    it is the only place this decision is made: the evaluation calls this function rather than
    re-checking ``noul >= threshold`` itself.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold!r}")
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    is_relevant = answer.noul >= threshold
    certainty = noul_confidence([answer.noul])[0]
    if certainty < min_confidence:
        return RelevanceCheck(
            pair_id,
            REVIEW,
            is_relevant,
            "too close to an even split to trust either way: needs a person",
        )
    if is_relevant:
        return RelevanceCheck(
            pair_id, RELEVANT, True, "noul at or above the threshold: the response addresses it"
        )
    return RelevanceCheck(
        pair_id,
        NOT_RELEVANT,
        False,
        "noul below the threshold: the response does not address it",
    )
