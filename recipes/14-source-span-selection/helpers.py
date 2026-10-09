"""Python's half of recipe 14: the state, the questions and the rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The explicit fallback outcome this use case names, for a document that does not state who
# the supplier is. It is a Choice option like the candidate spans, built by Python and added
# to every document's option list, never a separate path Jev reaches by failing to answer
# (CONTRIBUTING.md section 3: "Include none, other, no_match, or uncertain outcomes when the
# use case calls for them.").
NOT_STATED = "not_stated"

# Outcomes the rule below can produce.
SUPPORTED = "supported"
NOT_STATED_OUTCOME = "not_stated"
REVIEW = "review"

_NOT_STATED_DESCRIPTION = (
    "None of the candidate spans above states who the supplier is: the document may name a "
    "buyer, a shipping carrier, a bank, or a company mentioned for some other reason, but "
    "nothing here identifies the party the goods or services were actually purchased from."
)


def span_text(document: str, start: int, end: int) -> str:
    """The exact text of one span: ``document[start:end]``, nothing else.

    Python slices the fabricated source document by character offset, the same offsets
    ``build_fixtures.py`` recorded when it extracted the candidate spans. The text this
    returns is never retyped, paraphrased or stored separately: a confident pick hands back
    exactly this slice, so every result traces back to the document it came from
    (CONTRIBUTING.md section 3: "candidates, spans, and identifiers are built by Python and
    carried through to the output unchanged").
    """
    if not 0 <= start <= end <= len(document):
        raise ValueError(
            f"span offsets ({start}, {end}) are out of range for a document of length "
            f"{len(document)}"
        )
    return document[start:end]


def spans_by_id(fields: dict[str, Any]) -> dict[str, str]:
    """``{span id: exact text}`` for every candidate span Python extracted from this
    document, sliced by offset from ``fields['document']``."""
    return {
        span["id"]: span_text(fields["document"], span["start"], span["end"])
        for span in fields["spans"]
    }


def build_state(fields: dict[str, Any]) -> dict[str, Any]:
    """The state Jev sees for one document: the candidate spans Python already extracted,
    by id, as plain text -- never the full document and never an offset.

    ``fields`` also carries ``doc_id`` and the full ``document`` text with each span's
    character offsets. Python keeps all three; only the already-sliced text of each
    candidate span crosses into the model's state, so Jev is never asked to find a supplier
    name Python did not already decide was a candidate.
    """
    return {"spans": spans_by_id(fields)}


def build_questions(fields: dict[str, Any]) -> dict[str, Choice]:
    """The one question asked about this document.

    The option list is not the same for every document: Python builds it fresh from this
    document's own candidate spans (their ids only -- the text already crossed into
    ``state`` above, so the option itself carries no description) plus the shared fallback
    ``not_stated``. Because the option set is per-document, the replay key is too: a key
    computed for one document's spans can never replay for another document, even one with
    the same number of candidates (the same consequence recipe 07's per-word sense inventory
    has for its options).
    """
    criteria: dict[str, Any] = {span["id"]: None for span in fields["spans"]}
    criteria[NOT_STATED] = _NOT_STATED_DESCRIPTION
    return {
        "supplier_span": Choice(
            instructions=(
                "Which one of the candidate spans below, if any, states who the supplier "
                "is for this purchase -- the party the goods or services were bought from? "
                "Choose 'not_stated' if none of them does."
            ),
            criteria=criteria,
        )
    }


@dataclass(frozen=True)
class Selection:
    """What Python decided: the option Jev chose, the outcome, the exact source text (only
    when the outcome is ``supported``), and why."""

    doc_id: str
    choice: str
    outcome: str
    span_text: str | None
    reason: str


def select_span(
    doc_id: str,
    answer: Any,
    spans: dict[str, str],
    min_confidence: float,
) -> Selection:
    """Return the exact source text of the chosen span only when it names a real candidate
    for this document and the answer is confident enough.

    ``not_stated`` is reported as a final result whatever its confidence: the option itself
    already says no candidate span states the supplier, and there is no source text a
    confidence check could protect (the same reasoning recipe 08's ``no_match`` uses for a
    question none of its FAQs addresses). Any other choice that does not name one of this
    document's own candidate spans goes to ``review`` regardless of confidence --
    defensive, since the criteria ``build_questions`` asks with never offer such an option,
    but the rule does not trust that silently. Everything else goes to ``review`` only when
    confidence falls below ``min_confidence``. The rule is code, so it holds whatever the
    model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == NOT_STATED:
        return Selection(
            doc_id, NOT_STATED, NOT_STATED_OUTCOME, None, "no candidate span supports it"
        )
    if answer.choice not in spans:
        return Selection(
            doc_id, answer.choice, REVIEW, None, "not a candidate span for this document"
        )
    if answer.confidence < min_confidence:
        return Selection(doc_id, answer.choice, REVIEW, None, "confidence below the threshold")
    return Selection(doc_id, answer.choice, SUPPORTED, spans[answer.choice], "confident match")


def matches_gold(choice: str, spans: dict[str, str], gold: str) -> bool:
    """Whether naming ``choice`` (Jev's raw pick, before any confidence gate) would be right
    for ``gold``: ``not_stated`` is right only when ``gold`` is the literal string
    ``"not_stated"``; any other choice is right only when it names one of this document's
    own candidate spans whose text contains ``gold`` verbatim (a document may state the
    supplier's name in more than one span -- the letterhead and a "remit payment to" line, say
    -- so a correct pick is not required to be one particular span id, only to point at text
    that actually names the supplier).
    """
    if choice == NOT_STATED:
        return gold == NOT_STATED
    return choice in spans and gold in spans[choice]


def is_correct(selection: Selection, gold: str) -> bool:
    """Whether ``selection`` -- what the rule actually reported -- matches ``gold``.

    A ``review`` outcome is neither right nor wrong: Python reported nothing for it to be
    judged against. A ``not_stated`` outcome is right only when ``gold`` is the literal
    string ``"not_stated"``. A ``supported`` outcome is right only when ``gold`` is an
    actual supplier name and it appears, verbatim, in the returned span text.
    """
    if selection.outcome == REVIEW:
        return False
    if selection.outcome == NOT_STATED_OUTCOME:
        return gold == NOT_STATED
    return gold != NOT_STATED and gold in selection.span_text
