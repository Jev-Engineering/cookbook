"""Python's half of recipe 39: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.

The use case is a two-stage cascade over a short purchase document, run once per document:

Stage 1 (one request): for every field this document has at least one candidate value for, a
``Choice`` picks which candidate states that field, or the shared fallback ``not_found``. The
two fields' Choice questions are independent of each other (neither answer depends on the
other), so they are asked together in one request.

Stage 2 (a later request, only when stage 1 named a real candidate for at least one field): a
``Noul`` verifies each selection against its own source text -- "does this really state the
field, as opposed to a related but different figure or reference". A field's stage-2 question
depends on its own stage-1 answer (the question is only built, and only asked, once a candidate
has been named), so stage 2 can never be sent before stage 1 returns. The two fields' stage-2
propositions are still independent of *each other* (verifying field A does not depend on field
B's answer), so when both fields have a candidate to verify, both propositions travel together
in one, later, request.

A document with no candidate for a field never asks a stage-1 question for it (Python reports
``not_found`` directly); a field stage 1 itself resolves to ``not_found`` never reaches stage 2
either. ``plan_requests`` returns the exact shape -- which fields are bundled into which
request -- so the notebook can print it and make the request boundary visible instead of
asserting it in prose.
"""

import re
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice, Noul
from jev_cookbook.evaluation import noul_confidence

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The two document fields this recipe extracts, in a fixed order. A Choice needs at least two
# options, so a field only gets a stage-1 question once it has at least one real candidate (the
# candidate plus the shared fallback); a field with none is resolved directly in Python
# (CONTRIBUTING.md section 3, "Single-option Choice" in docs/backends.md).
FIELDS: tuple[str, ...] = ("invoice_number", "total_amount")

# The explicit fallback outcome this use case names: a Choice option, built by Python and added
# to every field's own option list, never a separate path Jev reaches by failing to answer
# (CONTRIBUTING.md section 3: "Include none, other, no_match, or uncertain outcomes when the use
# case calls for them.").
NOT_FOUND = "not_found"

# Outcomes a field's composed result can carry.
EXTRACTED = "extracted"
REVIEW = "review"

# Reasons a field is sent to review. The confidence-gate reason is pinned to this exact string
# (docs/glossary.md#review): two recipes' readers see the same words for the same cause.
REASON_CONFIDENCE = "confidence below the threshold"
REASON_INCONSISTENT = "verification did not support this selection"
REASON_FOREIGN = "not a candidate value for this field"
REASON_NO_CANDIDATES = "no candidate value was extracted for this field"
REASON_NOT_STATED = "no candidate value states this field"

_NOT_FOUND_DESCRIPTION = {
    "invoice_number": (
        "None of the candidate spans above states this document's own invoice number: the "
        "document may instead name a purchase order, a tracking number, a reference to a "
        "previous invoice, or no number of this kind at all."
    ),
    "total_amount": (
        "None of the candidate spans above states the total amount due on this document: the "
        "document may instead show only a subtotal, a tax or shipping line, a previous "
        "balance, or no dollar figure of this kind at all."
    ),
}

_STAGE_1_INSTRUCTIONS = {
    "invoice_number": (
        "Which one of the candidate spans below, if any, states this document's own invoice "
        "number -- not a purchase order number, a tracking number, or a reference to a "
        "previous invoice? Choose 'not_found' if none of them does."
    ),
    "total_amount": (
        "Which one of the candidate spans below, if any, states the total amount due on this "
        "document -- not a subtotal, a tax or shipping line, or a previous balance? Choose "
        "'not_found' if none of them does."
    ),
}

_STAGE_2_INSTRUCTIONS = {
    "invoice_number": (
        "The text given above for 'invoice_number' was selected as this document's own "
        "invoice number. Does it really state that -- as opposed to a purchase order number, "
        "a tracking number, or a reference to a previous, now-superseded invoice? Answer "
        "true only if it genuinely states this document's own invoice number."
    ),
    "total_amount": (
        "The text given above for 'total_amount' was selected as the total amount due on this "
        "document. Does it really state that -- as opposed to a subtotal, a tax or shipping "
        "line, or a previous balance? Answer true only if it genuinely states the total "
        "amount due."
    ),
}

# --------------------------------------------------------------------------------------------
# Extraction: real, deterministic text processing. Nothing below is a model; it runs once per
# document in build_fixtures.py and again, identically, in the notebook, so the state Jev sees
# and the state the fixtures were built from can never drift from each other.
# --------------------------------------------------------------------------------------------

_SENTENCE_END = re.compile(r"[.!?]\s+")


def split_sentences(document: str) -> list[tuple[int, int]]:
    """``(start, end)`` character offsets of every sentence in ``document``, in reading order.

    Splits on a sentence-ending punctuation mark followed by whitespace. A decimal amount such
    as ``$540.00`` is not split in the middle: the period inside it is followed by a digit, not
    whitespace, so the regex does not match there. The final sentence (after the last split, or
    the whole document if there is no split at all) is included even without trailing
    punctuation.
    """
    bounds = []
    start = 0
    for m in _SENTENCE_END.finditer(document):
        bounds.append((start, m.end()))
        start = m.end()
    if start < len(document):
        bounds.append((start, len(document)))
    return [(s, e) for s, e in bounds if document[s:e].strip()]


# A sentence is a candidate for 'invoice_number' when it both names one of these reference-ish
# keywords and contains a number-shaped token -- the keyword is what makes "12 cartons of
# paper" not a candidate even though it has a number, and the broad keyword list (not only
# "invoice") is what makes a purchase-order or tracking-number decoy a candidate too: Python
# hands Jev every number-shaped reference it found, and lets the model (and the verification
# stage) decide which one, if any, is this document's own invoice number.
_INVOICE_KEYWORDS = (
    "invoice",
    "purchase order",
    "po number",
    "po #",
    "po-",
    "tracking number",
    "reference",
)
_NUMBER_TOKEN = re.compile(r"\b[A-Z]{0,4}-?\d{3,8}\b")
_AMOUNT_TOKEN = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")


def _is_invoice_candidate(sentence: str) -> bool:
    low = sentence.lower()
    return any(k in low for k in _INVOICE_KEYWORDS) and bool(_NUMBER_TOKEN.search(sentence))


def _is_amount_candidate(sentence: str) -> bool:
    return bool(_AMOUNT_TOKEN.search(sentence))


_CANDIDATE_TEST = {
    "invoice_number": _is_invoice_candidate,
    "total_amount": _is_amount_candidate,
}


def extract_candidates(document: str, field: str) -> list[dict[str, Any]]:
    """The candidate spans for ``field``: every sentence of ``document`` that names one, in
    reading order, each given a fresh id (``s1``, ``s2``, ...) and its exact character
    offsets. A document with no qualifying sentence returns an empty list -- there is nothing
    to extract, and ``stage1_fields`` below never builds a question for it."""
    test = _CANDIDATE_TEST[field]
    spans = []
    for start, end in split_sentences(document):
        if test(document[start:end]):
            spans.append({"id": f"s{len(spans) + 1}", "start": start, "end": end})
    return spans


def span_text(document: str, start: int, end: int) -> str:
    """The exact text of one span: ``document[start:end]``, nothing else. Never retyped or
    paraphrased, so a confident pick hands back exactly this slice (CONTRIBUTING.md section 3:
    "candidates, spans, and identifiers are built by Python and carried through to the output
    unchanged")."""
    if not 0 <= start <= end <= len(document):
        raise ValueError(
            f"span offsets ({start}, {end}) are out of range for a document of length "
            f"{len(document)}"
        )
    return document[start:end]


def spans_by_id(fields: dict[str, Any], field: str) -> dict[str, str]:
    """``{span id: exact text}`` for every candidate span ``extract_candidates`` finds for
    ``field`` in ``fields['document']``, in reading order (Python dicts keep insertion
    order)."""
    document = fields["document"]
    return {
        span["id"]: span_text(document, span["start"], span["end"])
        for span in extract_candidates(document, field)
    }


# --------------------------------------------------------------------------------------------
# Stage 1: candidate selection. One Choice per field that has at least one candidate, all
# independent of each other, bundled into one request.
# --------------------------------------------------------------------------------------------


def stage1_fields(fields: dict[str, Any]) -> list[str]:
    """The fields, in ``FIELDS`` order, that have at least one candidate span in this document
    -- the fields stage 1 asks a question about at all. A field missing from this list never
    gets a question: ``no_candidates`` below resolves it directly."""
    return [f for f in FIELDS if spans_by_id(fields, f)]


def build_stage1_questions(fields: dict[str, Any], which: list[str]) -> dict[str, Choice]:
    """The stage-1 request's questions: one ``Choice`` per field in ``which`` (call with
    ``stage1_fields(fields)``, or a subset for a single-field request), each built fresh from
    this document's own candidate spans plus the shared ``not_found`` fallback."""
    questions: dict[str, Choice] = {}
    for field in which:
        criteria: dict[str, Any] = {sid: None for sid in spans_by_id(fields, field)}
        criteria[NOT_FOUND] = _NOT_FOUND_DESCRIPTION[field]
        questions[field] = Choice(instructions=_STAGE_1_INSTRUCTIONS[field], criteria=criteria)
    return questions


def build_stage1_state(fields: dict[str, Any], which: list[str]) -> dict[str, Any]:
    """The state for the stage-1 request: each field in ``which`` mapped to its own candidate
    spans by id, and nothing else -- never the full document, so Jev is never asked to find a
    value Python did not already shortlist as a candidate."""
    return {field: spans_by_id(fields, field) for field in which}


# --------------------------------------------------------------------------------------------
# Stage 2: verification. One Noul per field stage 1 named a real candidate for, all
# independent of each other (each depends only on its own field's stage-1 answer), bundled
# into one later request.
# --------------------------------------------------------------------------------------------


def stage2_fields(stage1_choices: dict[str, str]) -> list[str]:
    """The fields, in ``FIELDS`` order, whose stage-1 choice named a real candidate (not
    ``not_found``) -- the fields stage 2 verifies. ``stage1_choices`` is ``{field:
    answer.choice}`` for exactly the fields a stage-1 question was asked about."""
    return [f for f in FIELDS if f in stage1_choices and stage1_choices[f] != NOT_FOUND]


def build_stage2_questions(which: list[str]) -> dict[str, Noul]:
    """The stage-2 request's questions: one ``Noul`` per field in ``which``, each a fixed,
    reusable proposition -- the candidate text being verified lives in the state (below), not
    in the instructions, so the question itself never changes from one document to the next."""
    return {field: Noul(instructions=_STAGE_2_INSTRUCTIONS[field]) for field in which}


def build_stage2_state(
    fields: dict[str, Any], stage1_choices: dict[str, str], which: list[str]
) -> dict[str, Any]:
    """The state for the stage-2 request: for each field in ``which``, the exact text of the
    span stage 1 selected for it -- the same slice ``span_text`` produced, carried through
    unchanged, never retyped."""
    return {field: spans_by_id(fields, field)[stage1_choices[field]] for field in which}


# --------------------------------------------------------------------------------------------
# The request plan: what the notebook prints to make the independent/dependent boundary
# visible. Deterministic and tested, not merely a notebook print statement.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestPlan:
    """One request this document's cascade makes. ``stage`` is 1 or 2. ``fields`` is the
    questions bundled into this one request, in ``FIELDS`` order. ``depends_on`` names the
    fields whose stage-1 answer this request's own questions were built from (empty for a
    stage-1 request, which depends on no earlier answer at all)."""

    stage: int
    fields: tuple[str, ...]
    depends_on: tuple[str, ...]


def plan_requests(stage1: list[str], stage2: list[str]) -> list[RequestPlan]:
    """The sequence of requests one document's cascade makes: a stage-1 request only when
    ``stage1`` is non-empty, a stage-2 request only when ``stage2`` is non-empty (and, when it
    exists, always after the stage-1 request, since it depends on stage 1's own answers for
    exactly the fields it bundles). A document whose fields all lack candidates, or whose
    stage-1 answers all name ``not_found``, makes zero or one request and never two."""
    plans = []
    if stage1:
        plans.append(RequestPlan(1, tuple(stage1), ()))
    if stage2:
        plans.append(RequestPlan(2, tuple(stage2), tuple(stage2)))
    return plans


# --------------------------------------------------------------------------------------------
# Composing a field's result: the rule Python enforces whatever the model answers.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldResult:
    """What Python decided for one field of one document. ``choice`` is the stage-1 pick
    (a candidate id, ``not_found``, or ``None`` when no stage-1 question was ever asked).
    ``value`` is the exact extracted text, set only when ``outcome`` is ``EXTRACTED``."""

    doc_id: str
    field: str
    choice: str | None
    outcome: str
    value: str | None
    reason: str


def no_candidates(doc_id: str, field: str) -> FieldResult:
    """The result for a field with no candidate spans at all: Python already knows no span can
    support it, so it reports ``not_found`` directly and never builds a stage-1 question --
    there is nothing for a model to judge."""
    return FieldResult(doc_id, field, None, NOT_FOUND, None, REASON_NO_CANDIDATES)


def resolve_not_found(doc_id: str, field: str) -> FieldResult:
    """The result when stage 1 itself named the fallback: ``not_found`` is reported as a final
    result whatever its confidence. It passes the three-part test in CONTRIBUTING.md section 4:
    (a) it is a complete answer, not a deferral -- it says plainly that no candidate states
    this field, rather than asking a person to decide again; (b) choosing it records no action,
    since nothing is routed, extracted or moved; (c) being wrong leaves nothing standing beyond
    the missed field itself, because there is no extracted value a confidence check could have
    protected either way. Stage 2 is never reached for this field: there is no candidate text
    to verify."""
    return FieldResult(doc_id, field, NOT_FOUND, NOT_FOUND, None, REASON_NOT_STATED)


def finalize_field(
    doc_id: str,
    field: str,
    choice: str,
    spans: dict[str, str],
    noul: float,
    confidence: float,
    business_threshold: float,
    confidence_gate: float,
) -> FieldResult:
    """The result once stage 2 has verified a real candidate. Reached only when ``choice``
    names a real candidate for this document (not ``not_found``: see ``resolve_not_found``).

    Three checks, in order, any of which sends the field to review -- "uncertain or
    inconsistent", per the use case:

    1. a defensive membership check: ``choice`` must actually name one of this document's own
       candidates. The backend already rejects an answer naming an option outside the question
       it was asked (docs/backends.md), so this should never fire on a real answer, but the
       rule does not trust that silently.
    2. **uncertain**: ``confidence`` (``noul_confidence`` of the verification Noul) below
       ``confidence_gate`` -- the model is not sure enough, either way, to trust automatically.
    3. **inconsistent**: ``noul`` below ``business_threshold`` -- the model is confident, but
       its verification says this candidate does not really support the field.

    A candidate that clears both the confidence gate and the business threshold is reported as
    the field's extracted value: the exact span text, carried through unchanged.
    """
    if choice not in spans:
        return FieldResult(doc_id, field, choice, REVIEW, None, REASON_FOREIGN)
    if confidence < confidence_gate:
        return FieldResult(doc_id, field, choice, REVIEW, None, REASON_CONFIDENCE)
    if noul < business_threshold:
        return FieldResult(doc_id, field, choice, REVIEW, None, REASON_INCONSISTENT)
    return FieldResult(doc_id, field, choice, EXTRACTED, spans[choice], "confident and verified")


# --------------------------------------------------------------------------------------------
# Composing the document: the deterministic combination of every field's own result.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentOutcome:
    """The task-level result for one document: ``accepted`` is true only when every one of its
    fields' own results is something other than ``review`` -- the deterministic combination of
    the per-field results in ``fields`` (``{field: FieldResult}``), computed in
    ``compose_document_outcome``. Flipping any one field's own result (a different stage-1
    choice, a different stage-2 verification) can flip this."""

    doc_id: str
    fields: dict[str, FieldResult]
    accepted: bool


def compose_document_outcome(doc_id: str, fields: dict[str, FieldResult]) -> DocumentOutcome:
    """A document is ``accepted`` only when none of its fields went to review: the record is
    ready to use automatically only once every field in it is. Any single field's ``review``
    outcome, from either stage, is enough to withhold the whole document -- deterministic,
    computed from the field results already decided, and never re-asks a question."""
    accepted = all(result.outcome != REVIEW for result in fields.values())
    return DocumentOutcome(doc_id, dict(fields), accepted)


def matches_gold(result: FieldResult, gold: str) -> bool:
    """Whether ``result`` is right for ``gold``. A ``review`` outcome is neither right nor
    wrong: Python reported nothing for it to be judged against. ``not_found`` is right only
    when ``gold`` is the literal string ``"not_found"``. ``extracted`` is right only when
    ``gold`` is an actual value and it appears, verbatim, in the extracted text."""
    if result.outcome == REVIEW:
        return False
    if result.outcome == NOT_FOUND:
        return gold == NOT_FOUND
    return gold != NOT_FOUND and result.value is not None and gold in result.value


def document_correct(fields: dict[str, FieldResult], gold: dict[str, str]) -> bool:
    """Whether every field of a document's own result matches its gold value -- the task-level
    notion of "right", used only for documents ``compose_document_outcome`` accepted (an
    unaccepted document is never itself scored as right or wrong; see ``evaluate_outcomes`` in
    ``jev_cookbook.evaluation``, which requires but never reads this value for a document that
    was not accepted)."""
    return all(matches_gold(fields[f], gold[f]) for f in FIELDS)


# --------------------------------------------------------------------------------------------
# Running the cascade end to end for one document, and turning its answers into a result --
# the two steps both the notebook and the tests share, so neither has to duplicate the other.
# --------------------------------------------------------------------------------------------


def decide_document(backend: Any, fields: dict[str, Any]):
    """Run this document's full two-stage cascade against ``backend``: a stage-1 request only
    for the fields with a real candidate, then, only once stage 1 has answered, a stage-2
    request only for the fields stage 1 named a real candidate for. Returns ``(stage1_fields,
    stage1_answers, stage2_fields, stage2_answers)``; ``stage1_answers``/``stage2_answers`` map
    field name to the typed answer, and are empty dicts when that stage makes no request at
    all for this document."""
    s1 = stage1_fields(fields)
    stage1_answers: dict[str, Any] = {}
    if s1:
        q1 = build_stage1_questions(fields, s1)
        state1 = build_stage1_state(fields, s1)
        stage1_answers = dict(backend.decide(state1, q1).answers)
    stage1_choices = {field: answer.choice for field, answer in stage1_answers.items()}
    s2 = stage2_fields(stage1_choices)
    stage2_answers: dict[str, Any] = {}
    if s2:
        q2 = build_stage2_questions(s2)
        state2 = build_stage2_state(fields, stage1_choices, s2)
        stage2_answers = dict(backend.decide(state2, q2).answers)
    return s1, stage1_answers, s2, stage2_answers


def decide_document_cached(
    backend: Any, cache: dict[str, tuple[Any, ...]], doc_id: str, fields: dict[str, Any]
):
    """``decide_document(backend, fields)``, reusing ``cache[doc_id]`` when this document has
    already been decided -- so a document shown individually and later scored (or shown more
    than once) issues no second request for it. ``cache`` is a plain ``{doc_id:
    decide_document(...)}`` dict the caller owns and shares across every call it makes, so a
    whole notebook run decides each document at most once."""
    if doc_id not in cache:
        cache[doc_id] = decide_document(backend, fields)
    return cache[doc_id]


def field_result(
    doc_id: str,
    field: str,
    fields: dict[str, Any],
    stage1_answers: dict[str, Any],
    stage2_answers: dict[str, Any],
    business_threshold: float,
    confidence_gate: float,
) -> FieldResult:
    """One field's ``FieldResult``, from the answers ``decide_document`` returned for this
    document: ``no_candidates`` when stage 1 never asked about this field,
    ``resolve_not_found`` when stage 1 named the fallback, and otherwise ``finalize_field``
    against the frozen ``business_threshold`` and ``confidence_gate``."""
    if field not in stage1_answers:
        return no_candidates(doc_id, field)
    choice = stage1_answers[field].choice
    if choice == NOT_FOUND:
        return resolve_not_found(doc_id, field)
    spans = spans_by_id(fields, field)
    noul_answer = stage2_answers[field]
    confidence = noul_confidence([noul_answer.noul])[0]
    return finalize_field(
        doc_id,
        field,
        choice,
        spans,
        noul_answer.noul,
        confidence,
        business_threshold,
        confidence_gate,
    )


# --------------------------------------------------------------------------------------------
# Pooling field-level decisions across documents for evaluation, with a fixed, single
# iteration order (document, then FIELDS within it) so that two different orderings of the
# same work cannot attribute one field's correctness to another's confidence.
# --------------------------------------------------------------------------------------------


def flatten_fields(
    doc_ids: list[str],
    results: dict[str, dict[str, FieldResult]],
    gold: dict[str, dict[str, str]],
) -> tuple[list[tuple[str, str]], list[bool], list[bool]]:
    """``(keys, accepted, correct)`` for every scored (document, field) pair, in a single
    fixed order: documents in ``doc_ids`` order, fields in ``FIELDS`` order within each
    document. ``keys[i]`` is the ``(doc_id, field)`` pair ``accepted[i]``/``correct[i]``
    describe, so a caller can always trace a pooled row back to its document and field."""
    keys: list[tuple[str, str]] = []
    accepted: list[bool] = []
    correct: list[bool] = []
    for doc_id in doc_ids:
        for field in FIELDS:
            result = results[doc_id][field]
            keys.append((doc_id, field))
            accepted.append(result.outcome != REVIEW)
            correct.append(matches_gold(result, gold[doc_id][field]))
    return keys, accepted, correct
