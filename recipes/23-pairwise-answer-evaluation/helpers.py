"""Python's half of recipe 23: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

import hashlib
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# Jev is asked a purely *positional* question: given the two candidate answers as shown, in the
# order they are shown, which one better satisfies the one rubric criterion for this comparison?
# Jev never sees which candidate is "a" and which is "b" -- those labels, and which one was
# actually placed first, are Python-owned bookkeeping that never reaches the model (the same
# principle the template uses for a ticket reference: "the state is everything Jev sees, and
# Python builds it"). FIRST/SECOND name a position in the prompt, not a candidate identity.
FIRST = "first"
SECOND = "second"
TIE = "tie"
INSUFFICIENT = "insufficient_evidence"
OPTIONS = (FIRST, SECOND, TIE, INSUFFICIENT)

# The original candidate identities, Python-side only, and the two outcomes a verdict can carry
# unchanged across a position swap. A verdict's final label is one of these four.
A = "a"
B = "b"
LABELS = (A, B, TIE, INSUFFICIENT)

ACCEPTED = "accepted"
REVIEW = "review"

_DESCRIPTIONS = {
    FIRST: (
        "The first candidate answer, as shown above, satisfies the stated criterion better than "
        "the second."
    ),
    SECOND: (
        "The second candidate answer, as shown above, satisfies the stated criterion better than "
        "the first."
    ),
    TIE: (
        "Both candidate answers can be judged against the criterion, and they come out equal: "
        "either both clearly satisfy it, or both clearly fail it, to the same degree."
    ),
    INSUFFICIENT: (
        "The criterion cannot be judged at all from what is here: the question and the two "
        "candidate answers do not contain the fact, number, name, or kind of claim the criterion "
        "is about, in either candidate, so there is nothing to compare them on."
    ),
}

# The seed for Python's own randomisation of which candidate is shown first. It has nothing to
# do with any model: it only sets the inputs to the hash below, which decides, once and
# deterministically, how build_fixtures.py lays out the two requests this recipe makes for every
# comparison. Picked once as a plain constant (the recipe number), not searched for a balanced
# table: "The questions" below reports the table this draw happens to give, not a guarantee.
ORDER_SEED = 23


def assign_first_shown(comparison_ids: list[str], seed: int = ORDER_SEED) -> dict[str, bool]:
    """Deterministically decide, for every id in ``comparison_ids``, whether candidate ``a`` is
    the one shown first in that comparison's first request (``True``) or candidate ``b`` is
    (``False``).

    Each id's bit comes from hashing ``seed`` and that id alone (SHA-256, first byte even or
    odd), not from the id's position in ``comparison_ids`` or from any other id: shuffling the
    list, or reading one id's bit, changes nothing about any other id's bit. That is a stronger
    property than "looks at nothing but the id" alone would be -- a per-id hash cannot be made to
    track an id's *position* in a list the way a sequential random-number stream can, which
    matters here because ``ROWS`` in ``build_fixtures.py`` happens to be grouped by gold label, so
    a position-based draw would have been a label proxy even without reading the label directly.
    The function still never reads the gold label or the candidate text, but that is necessary,
    not sufficient, for the realised assignment to come out balanced across gold labels: it is a
    fact about one draw, checked by printing it, not a property the function proves on its own.
    """
    assignment = {}
    for comparison_id in comparison_ids:
        digest = hashlib.sha256(f"{seed}:{comparison_id}".encode()).digest()
        assignment[comparison_id] = digest[0] % 2 == 0
    return assignment


def first_is_a(fields: dict[str, Any], swap: bool) -> bool:
    """Whether candidate ``a`` is the one placed first in *this* request's state.

    ``fields["a_shown_first"]`` is the assignment for the comparison's first request (made by
    ``assign_first_shown`` when the fixtures were built); the second request swaps it.
    """
    return fields["a_shown_first"] if not swap else not fields["a_shown_first"]


def build_state(fields: dict[str, Any], swap: bool = False) -> dict[str, str]:
    """The state Jev sees for one request: the question, the one rubric criterion, and the two
    candidate answers in position order.

    ``fields`` also carries ``candidate_a``, ``candidate_b`` and ``a_shown_first``; Python decides
    from them, and from ``swap``, which text goes in ``first_answer`` and which in
    ``second_answer``. Jev is given no identifier for either candidate beyond its position.
    """
    a_first = first_is_a(fields, swap)
    return {
        "question": fields["question"],
        "criterion": fields["criterion"],
        "first_answer": fields["candidate_a"] if a_first else fields["candidate_b"],
        "second_answer": fields["candidate_b"] if a_first else fields["candidate_a"],
    }


def build_questions() -> dict[str, Choice]:
    """The one question asked about every comparison. The options, in order, are ``OPTIONS``;
    ``criteria`` is built from that tuple, not from ``_DESCRIPTIONS`` directly, so reordering
    ``OPTIONS`` reorders the question Jev is actually asked (and its replay key) rather than
    silently doing nothing."""
    return {
        "verdict": Choice(
            instructions=(
                "A question, one rubric criterion, and two candidate answers to the question, "
                "shown as 'first_answer' and 'second_answer'. Judging only by the stated "
                "criterion (ignore anything else that might make one answer seem better), does "
                "the first candidate answer satisfy it better, does the second, do the two come "
                "out equal, or does the criterion have nothing to go on in either one?"
            ),
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


def relabel(choice: str, a_first: bool) -> str:
    """Map one request's positional answer (``first``/``second``/``tie``/``insufficient_evidence``)
    back to the comparison's own vocabulary (``a``/``b``/``tie``/``insufficient_evidence``),
    using which candidate was actually placed first in that request.

    ``tie`` and ``insufficient_evidence`` carry across a position swap unchanged; only ``first``
    and ``second`` need relabelling, because they name a position, not a candidate.
    """
    if choice == FIRST:
        return A if a_first else B
    if choice == SECOND:
        return B if a_first else A
    return choice


def read_verdict_answer(answer: Any, fields: dict[str, Any], swap: bool) -> tuple[str, float]:
    """The relabelled candidate label and the confidence of one request's raw answer."""
    return relabel(answer.choice, first_is_a(fields, swap)), answer.confidence


@dataclass(frozen=True)
class Verdict:
    """What Python decided about one comparison: the agreed label (``None`` when sent to
    review), whether it is ``accepted`` or sent to ``review``, and why."""

    comparison_id: str
    label: str | None
    outcome: str
    reason: str


def judge_pair(
    comparison_id: str,
    label_first_request: str,
    confidence_first_request: float,
    label_second_request: str,
    confidence_second_request: float,
    min_confidence: float,
) -> Verdict:
    """Decide one comparison from its two position-swapped requests.

    A verdict is accepted only when both requests agree, once relabelled back to ``a``/``b``/
    ``tie``/``insufficient_evidence`` (``relabel``), on the same label -- otherwise the pair goes
    to ``review`` with the reason ``"orders disagree"``, whatever either confidence is: an
    inconsistent pair is exactly the case this recipe exists to catch, and no confidence number
    excuses it. Among consistent pairs, ``insufficient_evidence`` is accepted as soon as both
    requests agree on it, with no further confidence check: choosing it promotes neither
    candidate and triggers no side effect, so there is nothing left for a confidence gate to
    protect (CONTRIBUTING.md section 4, the same rule the template's ``none`` option and recipe
    08's ``no_match`` option could use). Every other agreed label (``a``, ``b``, ``tie``) still
    needs the lower of the two requests' confidences to clear ``min_confidence``; below it, the
    pair goes to ``review`` with the reason ``"confidence below the threshold"``. The rule is
    code, so it holds whatever the model answers.

    Args:
        comparison_id: The comparison's id.
        label_first_request: The first request's answer, already relabelled to ``a``/``b``/
            ``tie``/``insufficient_evidence`` (``read_verdict_answer`` does the relabelling).
        confidence_first_request: The first request's raw ``confidence``.
        label_second_request: The second (position-swapped) request's relabelled answer.
        confidence_second_request: The second request's raw ``confidence``.
        min_confidence: The confidence gate, chosen on ``validation`` and frozen before ``test``.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if label_first_request != label_second_request:
        return Verdict(comparison_id, None, REVIEW, "orders disagree")
    label = label_first_request
    if label == INSUFFICIENT:
        return Verdict(
            comparison_id, label, ACCEPTED, "insufficient evidence, agreed by both orders"
        )
    gate = min(confidence_first_request, confidence_second_request)
    if gate < min_confidence:
        return Verdict(comparison_id, None, REVIEW, "confidence below the threshold")
    return Verdict(
        comparison_id, label, ACCEPTED, "orders agree and confidence clears the threshold"
    )
