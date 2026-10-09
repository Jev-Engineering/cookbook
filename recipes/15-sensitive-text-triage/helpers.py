"""Python's half of recipe 15: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

import re
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The one proposition this recipe asks, written as a statement that is true or false
# (CONTRIBUTING.md section 3: "Noul propositions are written as statements that can be true or
# false"), not as a question. "A real, identifiable person" carries the weight of this recipe's
# hard cases: a shared mailbox, a number that only looks like a personal identifier, and a bare
# first name or surname are all close to this statement without making it true, and a narrative
# detail with no name or number at all can still make it true.
STATEMENT = "This document may contain personal information about a real, identifiable person."

_CRITERIA = {
    "true": (
        "The document contains, or clearly conveys, information that could identify a "
        "specific person: a full name together with any contact or location detail, a home "
        "address, a phone number, an email address, a government or account identifier, or a "
        "narrative detail specific enough that someone familiar with the context could "
        "identify who it is about. A fragment counts if it is specific enough on its own, even "
        "without every other detail (for example initials or a surname plus a working phone "
        "number or address)."
    ),
    "false": (
        "The document does not identify a specific person. This covers text with no personal "
        "details at all, a shared or organizational contact point (a team mailbox, a support "
        "line, a corporate address) that is not tied to one person, a number or string that "
        "merely resembles a personal identifier (an order number, a tracking reference, a "
        "product code) without being one, a public figure's name mentioned in a public role "
        "with no personal contact details, and a bare first name, initials, or surname alone "
        "with nothing else to tie it to a specific person."
    ),
}

# Three outcomes, not two. CONTRIBUTING.md section 4: "Uncertain or inconsistent results go to
# an explicit review outcome." A Noul has no `confidence` field in the API response, but
# `jev_cookbook.evaluation.noul_confidence` computes one anyway: the Choice confidence formula
# applied to a yes/no Choice, `|2p - 1|` (docs/evaluation.md, "Noul three-path pattern", S03). A
# document whose confidence does not clear the confidence gate (`min_confidence`) goes to REVIEW
# regardless of which side of the business threshold its probability sits on. Only once a
# document clears the confidence gate does the business threshold decide FLAGGED or CLEARED.
# Both FLAGGED and REVIEW documents go into the redaction-check queue; only CLEARED ones do not.
FLAGGED = "flagged"
REVIEW = "review"
CLEARED = "cleared"

# --------------------------------------------------------------------------- Candidate spans
#
# A simple, deterministic pre-scan Python runs before any document reaches Jev: three narrow
# patterns that *resemble* a personal identifier, never a judgment about whether one is really
# present. It is shown to the reader next to the document (CONTRIBUTING.md section 3: "Option
# lists, candidates, spans, and identifiers are built by Python and carried through to the
# output unchanged"), and it is deliberately imperfect in both directions: a tracking reference
# formatted like a phone number (this recipe's "-lookalike" fixtures) matches the phone pattern
# without being personal information, and a narrative detail specific enough to identify someone
# with no email, phone, or street address in it at all (this recipe's "v05-pii" and "t05-pii")
# matches nothing. Neither case is resolved by Python; both are left for the one Noul proposition
# to judge. None of these patterns are sent to Jev -- only `build_state`'s document text is.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\b\d{3}-\d{3,4}\b")
_STREET_RE = re.compile(
    r"\b\d{1,5}\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?\s+"
    r"(?:Lane|Ln|Street|St|Avenue|Ave|Drive|Dr|Road|Rd|Court|Ct|Row|Walk|Close|Terrace|Way|"
    r"Mews|Crescent|Alley|Boulevard|Blvd)\b"
)
_PATTERNS = (_EMAIL_RE, _PHONE_RE, _STREET_RE)


def find_candidate_spans(text: str) -> list[str]:
    """Substrings of ``text`` that resemble an email address, a phone number, or a street
    address -- in the order they appear, each listed once. A heuristic, not a judgment: see the
    module docstring above for what it gets wrong in both directions."""
    spans: list[str] = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            found = match.group()
            if found not in spans:
                spans.append(found)
    return spans


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one document: the text, nothing else.

    ``fields`` also carries ``doc_id``, a bookkeeping identifier, and the candidate spans are
    computed separately by ``find_candidate_spans`` for the reader's benefit. Neither reaches
    the model: the proposition is judged on the document text alone.
    """
    return {"document": fields["text"]}


def build_questions() -> dict[str, Noul]:
    """The one proposition asked about every document."""
    return {"contains_pii": Noul(instructions=STATEMENT, criteria=_CRITERIA)}


@dataclass(frozen=True)
class TriageResult:
    """What Python decided: flagged, cleared, or sent to review.

    ``may_contain_pii`` is the business decision alone (``noul >= threshold``), computed
    whatever ``outcome`` turns out to be, so that code which needs it (the evaluation's
    selective-prediction numbers) can read it here instead of re-deriving it from ``noul`` and
    ``threshold`` a second time.
    """

    doc_id: str
    outcome: str
    may_contain_pii: bool
    reason: str


def triage(doc_id: str, answer: Any, threshold: float, min_confidence: float) -> TriageResult:
    """Decide one of three outcomes for a document: review, then flagged, then cleared, in
    that order.

    The confidence gate (``min_confidence``, ``noul_confidence``: distance from an even split)
    is checked first, independently of which way the probability leans: a document whose
    confidence does not clear the gate goes to ``REVIEW``, whatever its probability is. Only
    once a document clears the confidence gate does the business threshold decide the outcome:
    ``FLAGGED`` when the probability is at or above it, ``CLEARED`` otherwise. The rule is code,
    so it holds whatever the model answers, and it is the only place this decision is made: the
    evaluation calls this function rather than re-checking ``noul >= threshold`` itself. This
    function does not redact anything and does not guarantee detection; it only decides where a
    document goes next.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold!r}")
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    may_contain_pii = answer.noul >= threshold
    confidence = noul_confidence([answer.noul])[0]
    if confidence < min_confidence:
        return TriageResult(
            doc_id,
            REVIEW,
            may_contain_pii,
            "confidence below the threshold",
        )
    if may_contain_pii:
        return TriageResult(
            doc_id,
            FLAGGED,
            True,
            "noul at or above the business threshold: likely to contain personal information",
        )
    return TriageResult(
        doc_id,
        CLEARED,
        False,
        "noul below the business threshold: unlikely to contain personal information",
    )


@dataclass(frozen=True)
class QueueItem:
    """One document queued for a redaction check: the identifier and text a reviewer needs,
    the ``TriageResult`` that sent it there, the candidate spans Python already found in it
    (carried through unchanged, CONTRIBUTING.md section 3), and the typed answer the queue is
    ordered by (``answer.noul``)."""

    doc_id: str
    text: str
    result: TriageResult
    candidate_spans: list[str]
    answer: Any


def queue_candidates(
    entries: list[tuple[str, str, Any]], threshold: float, min_confidence: float
) -> list[QueueItem]:
    """The documents ``triage`` does not clear -- ``flagged`` or ``review`` -- as a list of
    ``QueueItem``, sorted by ``noul`` descending.

    ``entries`` is ``(doc_id, text, answer)`` for every document to consider, from every split
    at once: a redaction queue ordered by risk has to be sorted once, over its whole contents,
    because ``jev_cookbook.simulation.ReviewQueue`` has no reordering of its own and keeps
    submissions in the order they arrive (``to_dicts()``/``pending()``: "oldest first"). Calling
    this once with every candidate, in one list, and submitting in the order it returns, is the
    only way the queue ends up actually sorted; sorting and submitting separate batches (the
    up-close documents, then validation, then test) leaves three independently-sorted runs
    concatenated, not one sorted queue. Ties in ``noul`` keep their relative order from
    ``entries`` (Python's ``sorted`` is stable).
    """
    items = []
    for doc_id, text, answer in entries:
        result = triage(doc_id, answer, threshold, min_confidence)
        if result.outcome != CLEARED:
            items.append(QueueItem(doc_id, text, result, find_candidate_spans(text), answer))
    return sorted(items, key=lambda item: -item.answer.noul)
