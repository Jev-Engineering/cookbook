"""Python's half of recipe 14: the state, the questions and the rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

import re
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
NO_CANDIDATES_REASON = "no candidate spans were extracted from this document"

_NOT_STATED_DESCRIPTION = (
    "None of the candidate spans above states who the supplier is: the document may name a "
    "buyer, a shipping carrier, a bank, or a company mentioned for some other reason, but "
    "nothing here identifies the party the goods or services were actually purchased from."
)

# --------------------------------------------------------------------------------------------
# Extraction: a real, deterministic span extractor. Nothing in this section is a model; it is
# plain text processing, run once per document by build_fixtures.py and again, identically,
# by the notebook (so the state Jev sees and the state the fixtures were built from can never
# drift from each other).
# --------------------------------------------------------------------------------------------

# A sentence boundary is a '.', '!' or '?' followed by whitespace, except right after one of
# these abbreviations (so "Riverside Packaging Co. was our vendor" does not end a sentence at
# "Co."). This is a short, fixed list because the fixtures are a small, controlled vocabulary,
# not a general-purpose sentence splitter.
_ABBREVIATIONS = frozenset({"co", "inc", "llc", "ltd", "corp", "mr", "mrs", "dr", "jr", "sr"})
_SENTENCE_END = re.compile(r"[.!?]\s+")
_LAST_WORD = re.compile(r"(\w+)[.!?]$")


def split_sentences(document: str) -> list[tuple[int, int]]:
    """``(start, end)`` character offsets of every sentence in ``document``, in reading order.

    Splits on a sentence-ending punctuation mark followed by whitespace, unless the word right
    before the punctuation is a known abbreviation (``_ABBREVIATIONS``), in which case the
    split is skipped and the sentence continues. The final sentence (after the last split, or
    the whole document if there is no split at all) is included even without trailing
    punctuation.
    """
    bounds = []
    start = 0
    for m in _SENTENCE_END.finditer(document):
        boundary = m.start() + 1  # just past the punctuation mark
        word = _LAST_WORD.search(document[start:boundary])
        if word and word.group(1).lower() in _ABBREVIATIONS:
            continue
        bounds.append((start, m.end()))
        start = m.end()
    if start < len(document):
        bounds.append((start, len(document)))
    return [(s, e) for s, e in bounds if document[s:e].strip()]


# A sentence is a candidate span when it names an organisation: a run of one to four
# capitalized words immediately followed by a legal-entity-shaped suffix. This is a cue, not a
# judgment of who the supplier is -- a sentence naming a buyer, a bank or a carrier is just as
# much a candidate as one naming the real supplier; the whole point of the fixed option set is
# that Python hands Jev every organisation it found and lets the model decide which one, if
# any, is the supplier.
_ORG_SUFFIXES = (
    "Inc", "LLC", "Co", "Ltd", "Corp", "Group", "Partners", "Bank", "Mills", "Supply",
    "Services", "Solutions", "Analytics", "Trading", "Consulting", "Chemicals", "Electronics",
    "Manufacturing", "Hardware", "Textiles", "Fasteners", "Packaging", "Logistics",
    "Interiors", "Goods", "Media", "Printing", "Stationery", "Shipping", "Insurance",
)  # fmt: skip
_ORG_CUE = re.compile(r"\b(?:[A-Z][A-Za-z&]*\s+){1,4}(?:" + "|".join(_ORG_SUFFIXES) + r")\b\.?")


def extract_spans(document: str) -> list[dict[str, Any]]:
    """The candidate spans Python extracts from ``document``: every sentence containing an
    organisation cue (``_ORG_CUE``), in reading order, each given a fresh id (``s1``, ``s2``,
    ...) and its exact character offsets. A document with no organisation-bearing sentence at
    all returns an empty list -- there is nothing to extract, and "Python's part" below acts
    on that directly, without ever building a question."""
    spans = []
    for start, end in split_sentences(document):
        if _ORG_CUE.search(document[start:end]):
            spans.append({"id": f"s{len(spans) + 1}", "start": start, "end": end})
    return spans


def span_text(document: str, start: int, end: int) -> str:
    """The exact text of one span: ``document[start:end]``, nothing else.

    The text this returns is never retyped, paraphrased or stored separately: a confident
    pick hands back exactly this slice, so every result traces back to the document it came
    from (CONTRIBUTING.md section 3: "candidates, spans, and identifiers are built by Python
    and carried through to the output unchanged").
    """
    if not 0 <= start <= end <= len(document):
        raise ValueError(
            f"span offsets ({start}, {end}) are out of range for a document of length "
            f"{len(document)}"
        )
    return document[start:end]


def spans_by_id(fields: dict[str, Any]) -> dict[str, str]:
    """``{span id: exact text}`` for every candidate span ``extract_spans`` finds in
    ``fields['document']``, in reading order (Python dicts keep insertion order)."""
    document = fields["document"]
    return {
        span["id"]: span_text(document, span["start"], span["end"])
        for span in extract_spans(document)
    }


def build_state(fields: dict[str, Any]) -> dict[str, Any]:
    """The state Jev sees for one document: the candidate spans Python already extracted,
    by id, as plain text -- never the full document and never an offset.

    ``fields`` carries ``doc_id`` and the full ``document`` text; Python keeps both. Only the
    already-sliced text of each candidate span crosses into the model's state, so Jev is
    never asked to find a supplier name Python did not already decide was a candidate. Call
    only when ``extract_spans(fields['document'])`` is non-empty: "Python's part" below
    short-circuits a document with no candidates before any question is built.
    """
    return {"spans": spans_by_id(fields)}


def build_questions(fields: dict[str, Any]) -> dict[str, Choice]:
    """The one question asked about this document. Call only when this document has at least
    one candidate span (see ``build_state``); a ``Choice`` needs a non-empty option set.

    The option list is not the same for every document: Python builds it fresh from this
    document's own candidate spans (their ids only -- the text already crossed into
    ``state`` above, so the option itself carries no description) plus the shared fallback
    ``not_stated``. Because the option set is per-document, the replay key is too: a key
    computed for one document's spans can never replay for another document, even one with
    the same number of candidates (the same consequence recipe 07's per-word sense inventory
    has for its options).
    """
    spans = extract_spans(fields["document"])
    criteria: dict[str, Any] = {span["id"]: None for span in spans}
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
    """What Python decided: the option Jev chose (``None`` when no question was ever asked),
    the outcome, the exact source text (only when the outcome is ``supported``), and why."""

    doc_id: str
    choice: str | None
    outcome: str
    span_text: str | None
    reason: str


def no_candidates(doc_id: str) -> Selection:
    """The result for a document with no candidate spans at all: Python already knows no
    span can support the supplier, so it reports ``not_stated`` directly and never builds a
    question, asks Jev, or spends a request -- there is nothing for a model to judge
    (CONTRIBUTING.md's opening: Python owns everything exact)."""
    return Selection(doc_id, None, NOT_STATED_OUTCOME, None, NO_CANDIDATES_REASON)


def select_span(
    doc_id: str,
    answer: Any,
    spans: dict[str, str],
    min_confidence: float,
) -> Selection:
    """Return the exact source text of the chosen span only when it names a real candidate
    for this document and the answer is confident enough. Call only when ``spans`` is
    non-empty (a document with no candidates never reaches here; see ``no_candidates``).

    ``not_stated`` is reported as a final result whatever its confidence: CONTRIBUTING.md
    section 4 allows a low-confidence fallback to be delivered as a final result, instead of
    going to review, exactly when choosing it triggers no side effect -- here, nothing is
    routed, answered or moved, and there is no stored span text for a confidence check to
    protect (the same reasoning recipe 08 uses for ``no_match``). That is a real trade-off,
    not a free pass: "Evaluation" below shows a confidence-only view of the same answers that
    *would* catch a wrong ``not_stated`` pick, at the cost this rule accepts instead. Any
    other choice that does not name one of this document's own candidate spans goes to
    ``review`` regardless of confidence -- defensive, since the criteria ``build_questions``
    asks with never offer such an option, but the rule does not trust that silently.
    Everything else goes to ``review`` only when confidence falls below ``min_confidence``.
    The rule is code, so it holds whatever the model answers.
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
    """Whether naming ``choice`` would be right for ``gold``: ``not_stated`` is right only
    when ``gold`` is the literal string ``"not_stated"``; any other choice is right only when
    it names one of this document's own candidate spans whose text contains ``gold``
    verbatim -- "exact match on the supplier name" means the returned span text contains the
    gold name exactly as written, not that one particular span id is the sole correct answer.
    A document may state the supplier's name in more than one span (the letterhead and a
    "remit payment to" line, say), so a correct pick is not required to be one particular
    span id, only to point at text that actually names the supplier."""
    if choice == NOT_STATED:
        return gold == NOT_STATED
    return choice in spans and gold in spans[choice]


def is_correct(selection: Selection, gold: str) -> bool:
    """Whether ``selection`` -- what the rule actually reported -- matches ``gold``.

    A ``review`` outcome is neither right nor wrong: Python reported nothing for it to be
    judged against. A ``not_stated`` outcome (whether from ``select_span`` or from
    ``no_candidates``) is right only when ``gold`` is the literal string ``"not_stated"``. A
    ``supported`` outcome is right only when ``gold`` is an actual supplier name and it
    appears, verbatim, in the returned span text.
    """
    if selection.outcome == REVIEW:
        return False
    if selection.outcome == NOT_STATED_OUTCOME:
        return gold == NOT_STATED
    return gold != NOT_STATED and gold in selection.span_text


def gold_positions(spans: dict[str, str], gold: str) -> list[int]:
    """The 1-based position(s), among this document's own candidate spans in reading order,
    whose text contains ``gold`` verbatim. Empty for ``gold == "not_stated"`` or for a
    document where no span names the supplier (which should not happen for a labelled,
    named-gold document -- see ``tests/test_helpers.py``'s answerability test)."""
    if gold == NOT_STATED:
        return []
    return [i for i, text in enumerate(spans.values(), start=1) if gold in text]


# --------------------------------------------------------------------------------------------
# Model-free baselines: no Jev answer is used by any of these. Each one, like
# ``select_span``, returns a raw pick (a span id or ``not_stated``) that ``matches_gold``
# scores the same way -- they exist only so "Evaluation" can show that position and a simple
# lexical cue do not already solve this task on their own.
# --------------------------------------------------------------------------------------------


def last_span_baseline(spans: dict[str, str]) -> str:
    """Always pick the last candidate span, or ``not_stated`` when there are none."""
    return next(reversed(spans), NOT_STATED)


def first_span_baseline(spans: dict[str, str]) -> str:
    """Always pick the first candidate span, or ``not_stated`` when there are none."""
    return next(iter(spans), NOT_STATED)


# A short, literal cue list -- not the fixed vocabulary of the recipe's own rule, just a
# stand-in for "grep the spans for a word that sounds like a supplier disclosure". It is
# deliberately naive: a decoy span can contain one of these words too (see build_fixtures.py),
# which is exactly what makes a lexical-cue baseline unreliable in a way a confident pick is
# not.
CUE_WORDS = ("supplier", "vendor", "remit", "sold by", "supplied by")


def cue_regex_baseline(spans: dict[str, str]) -> str:
    """Pick the last candidate span whose text contains one of ``CUE_WORDS`` (case
    insensitive), or ``not_stated`` when none does (including when there are no spans at
    all)."""
    matches = [sid for sid, text in spans.items() if any(c in text.lower() for c in CUE_WORDS)]
    return matches[-1] if matches else NOT_STATED
