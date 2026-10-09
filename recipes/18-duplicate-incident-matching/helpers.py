"""Python's half of recipe 18: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

import re
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------------------------
# The fixed pool of open incidents. A new ticket is matched against this pool, never invented
# by Jev: every option the question can ever offer comes from here (plus the fallback below).
# --------------------------------------------------------------------------------------------

OPEN_INCIDENTS: dict[str, dict[str, str]] = {
    "INC-101": {
        "service": "checkout-api",
        "symptoms": "Checkout fails with a 500 error when a promo code is applied at payment confirmation.",
    },
    "INC-102": {
        "service": "auth-service",
        "symptoms": "Users are intermittently signed out mid-session with no error message shown.",
    },
    "INC-103": {
        "service": "search-index",
        "symptoms": "Search returns zero results for queries that matched items yesterday.",
    },
    "INC-104": {
        "service": "email-notifications",
        "symptoms": "Order confirmation emails arrive more than two hours after checkout.",
    },
    "INC-105": {
        "service": "billing-gateway",
        "symptoms": "Card payments are declined intermittently even though the card is valid and has funds.",
    },
    "INC-106": {
        "service": "checkout-api",
        "symptoms": "The cart subtotal does not update after a second item is added.",
    },
    "INC-107": {
        "service": "mobile-app",
        "symptoms": "The app crashes immediately after launch on the newest OS update.",
    },
    "INC-108": {
        "service": "search-index",
        "symptoms": "Autocomplete suggestions show items from the wrong product category.",
    },
}

# The explicit fallback the use case names, for a new ticket that matches none of the retrieved
# candidates. It is a Choice option like the others, built by Python, not a separate code path
# Jev reaches by failing to answer.
NO_MATCH = "no_match"

# How many candidates Python retrieves for each new ticket. Fixed, so every question offers the
# same number of options (the retrieved candidates plus NO_MATCH), whatever ticket it is about.
SHORTLIST_SIZE = 3

# Outcomes the rule below can produce.
LINKED = "linked"
NO_DUPLICATE = "no_duplicate"
REVIEW = "review"

_STOPWORDS = {
    "a", "an", "the", "is", "are", "to", "at", "on", "for", "with", "and", "or", "of", "after",
    "when", "that", "this", "it", "in", "mid", "no", "even", "though", "has", "have", "than",
    "more", "from", "its", "but", "not", "shows", "show",
}  # fmt: skip


def _tokens(text: str) -> set[str]:
    """Lowercase, punctuation-stripped words of ``text``, with common stopwords removed."""
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


def _similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets: shared words over the union. 0.0 if either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity_scores(symptoms: str) -> dict[str, float]:
    """The Jaccard similarity between ``symptoms`` and every open incident's own symptoms --
    the raw numbers ``shortlist`` ranks by, exposed so a reader can see the retrieval step work
    rather than only its result."""
    new_tokens = _tokens(symptoms)
    return {
        incident_id: _similarity(new_tokens, _tokens(incident["symptoms"]))
        for incident_id, incident in OPEN_INCIDENTS.items()
    }


def shortlist(symptoms: str, k: int = SHORTLIST_SIZE) -> list[str]:
    """Python's retrieval step: the ``k`` open incidents whose symptom text most overlaps the new
    ticket's, by plain word overlap -- no model call, no learned embedding. Ties (including every
    incident tying at zero overlap) break on the incident id, so the result is deterministic.

    This ranks on symptom text alone; it does not look at the affected service at all, on purpose.
    A textually similar incident on a different service can still be retrieved, because telling
    "the same incident" apart from "similar wording, different service" is exactly the judgment
    the question below asks Jev to make -- not something Python's retrieval should pre-filter away
    before Jev ever sees it.
    """
    scores = similarity_scores(symptoms)
    ranked = sorted(
        OPEN_INCIDENTS,
        key=lambda incident_id: (
            -scores[incident_id],
            incident_id,
        ),
    )
    return ranked[:k]


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one new ticket: its symptoms and affected service, as separate
    fields, and nothing else.

    ``fields`` also carries ``ticket_id``, a bookkeeping identifier. Python keeps it and attaches
    it to the outcome, so it never needs to pass through the model. The shortlist Python
    retrieved is not stored here: ``shortlist(fields["symptoms"])`` is a deterministic function
    of the symptoms text alone, so it is recomputed wherever it is needed rather than carried as
    a second piece of state that could drift out of sync with it.
    """
    return {"symptoms": fields["symptoms"], "service": fields["service"]}


def _candidate_description(incident_id: str) -> str:
    incident = OPEN_INCIDENTS[incident_id]
    return (
        f"Existing incident {incident_id}, affecting the {incident['service']} service. "
        f"Reported symptoms: {incident['symptoms']}"
    )


def build_questions(candidates: list[str]) -> dict[str, Choice]:
    """The one question asked about a new ticket, given the ``candidates`` Python retrieved.

    Every new ticket shares one question shape (which open incident, if any, is this the same
    problem as), but the option list is built fresh per ticket from its own shortlist, so a
    ticket about the search service is never asked to choose a checkout candidate's identifier,
    and the replay key changes with the shortlist as a result.
    """
    criteria = {incident_id: _candidate_description(incident_id) for incident_id in candidates}
    criteria[NO_MATCH] = (
        "None of the candidate incidents above describes the same underlying problem on the "
        "same service as this new report. Choose this when every candidate differs in "
        "symptoms, in affected service, or both."
    )
    return {
        "match": Choice(
            instructions=(
                "A new incident report is below. Does it describe the same underlying problem "
                "as any of the candidate incidents, or none of them? Two incidents are the same "
                "only when they describe the same underlying problem and affect the same "
                "service; similar symptoms on a different service are not a match."
            ),
            criteria=criteria,
        )
    }


@dataclass(frozen=True)
class Resolution:
    """What Python decided: the option Jev chose, the outcome, and why.

    ``candidates`` is the shortlist this ticket was actually offered, kept alongside the
    decision so a review item or a link action can show what was on the table.
    """

    ticket_id: str
    candidates: tuple[str, ...]
    label: str
    outcome: str
    reason: str


def match_incident(
    ticket_id: str, candidates: list[str], answer: Any, min_confidence: float
) -> Resolution:
    """Decide what to do with one typed answer: link, call it a new incident, or hold it for
    review.

    ``no_match`` is never run past the confidence gate, whatever its confidence: the option
    itself already says no candidate is the same incident, and there is no side effect (no
    link) a confidence check could protect -- the fallback is final only because it triggers
    nothing. Choosing anything that is not one of the retrieved candidates and not ``no_match``
    goes to review (defensive: ``build_questions`` never offers such an option, but the rule
    does not trust that silently, the same guard recipe 07's word-sense rule keeps). A real
    candidate below ``min_confidence`` also goes to review, instead of linking on a guess. Only
    a real candidate named with enough confidence is linked -- the one outcome with a side
    effect. The rule is code, so it holds whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == NO_MATCH:
        return Resolution(
            ticket_id, tuple(candidates), NO_MATCH, NO_DUPLICATE, "no open incident matches"
        )
    if answer.choice not in candidates:
        return Resolution(
            ticket_id,
            tuple(candidates),
            answer.choice,
            REVIEW,
            "not one of the retrieved candidates",
        )
    if answer.confidence < min_confidence:
        return Resolution(
            ticket_id, tuple(candidates), answer.choice, REVIEW, "confidence below the threshold"
        )
    return Resolution(ticket_id, tuple(candidates), answer.choice, LINKED, "confident match")


def record_resolution(resolution: Resolution, answer: Any, actions: Any, queue: Any) -> None:
    """Carry out Python's simulated side effect for one resolution.

    A ``linked`` resolution is recorded in ``actions`` (a ``jev_cookbook.simulation.ActionLog``):
    simulated, never executed, the only outcome of this recipe that does anything at all. A
    ``review`` resolution is queued in ``queue`` (a ``ReviewQueue``) with the candidates it was
    offered, so a person can see what Jev was choosing between. A ``no_duplicate`` resolution
    records nothing: the fallback is final specifically because it has no side effect to log.
    """
    if resolution.outcome == LINKED:
        actions.record(
            "link_incident",
            {"new_incident": resolution.ticket_id, "linked_to": resolution.label},
            answer=answer,
            rule=resolution.reason,
        )
    elif resolution.outcome == REVIEW:
        queue.submit(
            {"new_incident": resolution.ticket_id, "candidates": list(resolution.candidates)},
            resolution.reason,
            answer=answer,
        )


def accepted_and_correct(
    results: list[Resolution], gold: dict[str, Any]
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``: ``accepted[i]``
    is whether ``match_incident`` answered (``linked`` or ``no_duplicate``) rather than sent to
    ``review``, and ``correct[i]`` is whether that result's label is the gold match (ignored,
    but still computed, where ``accepted[i]`` is False, exactly as ``evaluate_outcomes``
    documents). ``evaluate_outcomes`` is the shared helper for a rule like this one, whose review
    branch is more than a single confidence gate (see "Selective prediction" in
    ``docs/evaluation.md``); it reports coverage, accuracy and risk. It has no notion of a
    second, narrower outcome inside "accepted" (``linked`` versus ``no_duplicate``), which is
    what :func:`false_merge_rate` below computes instead.
    """
    accepted = [r.outcome != REVIEW for r in results]
    correct = [r.label == gold[r.ticket_id] for r in results]
    return accepted, correct


def false_merge_rate(results: list[Resolution], gold: dict[str, Any]) -> float:
    """The share of ``linked`` resolutions whose chosen incident is not the gold match -- the
    only way this recipe's simulated side effect (linking two incidents together) can be wrong.

    This is narrower than the risk ``jev_cookbook.evaluation.evaluate_outcomes`` reports: a wrong
    ``no_duplicate`` call (missing a real duplicate) lowers that risk too, but it is not a false
    merge, because ``no_duplicate`` triggers no side effect at all. NaN when nothing was linked,
    matching ``jev_cookbook.evaluation``'s own convention (undefined is NaN, never 0.0).
    """
    if not results:
        raise ValueError("false_merge_rate needs at least one result")
    linked = [r for r in results if r.outcome == LINKED]
    if not linked:
        return float("nan")
    wrong = sum(1 for r in linked if r.label != gold[r.ticket_id])
    return wrong / len(linked)
