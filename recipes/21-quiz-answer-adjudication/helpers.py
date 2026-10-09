"""Python's half of recipe 21: the state, the question, the normaliser and the rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question, the state and the rule cannot disagree.

Design in one paragraph: a quiz response is adjudicated against a Python-built candidate set
of accepted phrasings. A normaliser checks for an exact match first (case, whitespace,
punctuation and a leading article folded away); only a response the normaliser cannot settle
is sent to Jev. A quiz question whose accepted answer is a number is never sent to Jev at all,
whatever the response looks like: TypeSafe's own notes on Jev 1.13 (S07) say plainly that "Jev
is not a calculator" and recommend keeping arithmetic in code, so a number comparison is
exact Python arithmetic, settled every time.
"""

import re
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

TEXT = "text"
NUMBER = "number"

# The fixed outcome set the use case names. Jev never invents one of these; Python supplies
# the list, Jev only picks among it, and `needs_review` is the fallback outcome the use case
# names explicitly, not an afterthought.
MATCH = "match"
PARTIAL_MATCH = "partial_match"
NO_MATCH = "no_match"
NEEDS_REVIEW = "needs_review"
OUTCOMES = (MATCH, PARTIAL_MATCH, NO_MATCH, NEEDS_REVIEW)

# `NEEDS_REVIEW` is this recipe's own domain-specific name for the outcome
# docs/glossary.md#review names generically "review" -- it is both one of Jev's own `Choice`
# options (see `_CRITERIA` and `build_questions` below) and the tag `adjudicate` gives any
# response it defers rather than grades, whatever sent it there (the model naming
# `needs_review` itself, or a confidence below the threshold). The glossary allows a recipe to
# keep its own domain-specific sub-reason name for this outcome; REVIEW documents that mapping
# for anything that reads this file looking for the canonical value, without renaming
# `NEEDS_REVIEW`, which is also the literal option name baked into every stored response,
# gold label and replay key in `fixtures/`.
REVIEW = "review"

_CRITERIA = {
    MATCH: (
        "The response names the accepted answer itself, or adds wording before or after it "
        "(a title, a role, or another detail) that does not point at someone or something "
        "else instead, or is a misspelling close enough that no other reading fits."
    ),
    PARTIAL_MATCH: (
        "The response names a person or thing related to the accepted answer, such as a role "
        "connected to it, a group it is part of, or someone closely associated with it, but "
        "not the accepted answer itself."
    ),
    NO_MATCH: (
        "The response names something that is not the accepted answer and is not closely "
        "related to it: a different person, place or thing that the question is not about."
    ),
    NEEDS_REVIEW: (
        "The response hedges between two or more distinct options instead of committing to "
        "one, or the text gives no reasonable way to tell which of the other three outcomes "
        "applies."
    ),
}

# Fabricated trivia state: every question, person, place and number below belongs to an
# invented quiz world and names no real fact. `kind` decides whether a response is ever sent
# to Jev: `TEXT` questions reach Jev when the normaliser cannot settle them; `NUMBER`
# questions never do (see the module docstring and S07).
QUESTION_BANK: dict[str, dict[str, Any]] = {
    "tower": {
        "kind": TEXT,
        "question": "Who first lit the Observatory Tower in the city of Veyla?",
        "accepted": ("Petra Lindqvist", "Lindqvist"),
    },
    "capital": {
        "kind": TEXT,
        "question": "What is the capital of the kingdom of Threnvale?",
        "accepted": ("Mirrowgate",),
    },
    "guild": {
        "kind": TEXT,
        "question": "Who founded the Lantern Guild of Ashcombe?",
        "accepted": ("Doran Hale", "Hale"),
    },
    "sonata": {
        "kind": TEXT,
        "question": "Who composed the Starlight Sonata performed at the Veyla festival?",
        "accepted": ("Imra Costas", "Costas"),
    },
    "reef": {
        "kind": TEXT,
        "question": "Who discovered the Ember Reef off the coast of Saltmere?",
        "accepted": ("Nia Brack", "Brack"),
    },
    "moons": {
        "kind": NUMBER,
        "question": "How many moons orbit the planet Ordolyn in the Starward Atlas?",
        "value": 3,
        "accepted": ("3",),
    },
    "siege": {
        "kind": NUMBER,
        "question": "How many years did the Siege of Caldenhall last?",
        "value": 7,
        "accepted": ("7",),
    },
    "council": {
        "kind": NUMBER,
        "question": "How many members sit on the Lantern Guild council?",
        "value": 5,
        "accepted": ("5",),
    },
}

_ARTICLE_RE = re.compile(r"^(a|an|the)\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def normalize_text(text: str) -> str:
    """Case, whitespace, punctuation and a single leading article folded away.

    ``"The Mirrowgate."`` and ``"mirrowgate"`` normalise to the same string; a mid-sentence
    "the" is left alone (only a *leading* article is a fixed phrase people drop or add without
    changing what they mean).
    """
    folded = text.strip().lower()
    folded = _PUNCT_RE.sub(" ", folded)
    folded = _WS_RE.sub(" ", folded).strip()
    return _ARTICLE_RE.sub("", folded)


def parse_number(text: str) -> float | None:
    """The first number ``text`` names, as digits or as one of the words zero to twenty, or
    ``None`` if it names no number at all. Used only for `NUMBER`-kind questions; S07 is why
    this is Python arithmetic rather than a model judgment."""
    folded = normalize_text(text)
    found = _NUMBER_RE.search(folded)
    if found is not None:
        return float(found.group())
    for word in folded.split():
        if word in _NUMBER_WORDS:
            return float(_NUMBER_WORDS[word])
    return None


def candidate_set(quiz_id: str) -> list[str]:
    """The accepted phrasings for ``quiz_id``, built by Python and shown to the reader before
    any adjudication, model-assisted or not."""
    return list(QUESTION_BANK[quiz_id]["accepted"])


def queue_item(fields: dict[str, Any]) -> dict[str, Any]:
    """What a human adjudicator sees for one queued response: the quiz id, the question text,
    and the response itself, not only an identifier (CONTRIBUTING.md section 4: the queue is
    the side effect a `needs_review` outcome triggers, and an item with nothing to read is not
    something a person can actually adjudicate)."""
    quiz = QUESTION_BANK[fields["quiz_id"]]
    return {
        "quiz_id": fields["quiz_id"],
        "question": quiz["question"],
        "response": fields["response"],
    }


def build_state(fields: dict[str, Any]) -> dict[str, Any]:
    """The state Jev sees for one response: the question, the candidate set, and the
    response. ``fields`` also carries ``quiz_id``, which stays in Python: it is only a lookup
    key into ``QUESTION_BANK`` and never needs to pass through the model."""
    quiz = QUESTION_BANK[fields["quiz_id"]]
    return {
        "question": quiz["question"],
        "accepted_answers": candidate_set(fields["quiz_id"]),
        "response": fields["response"],
    }


def build_questions() -> dict[str, Choice]:
    """The one question asked about every response that the normaliser could not settle."""
    return {
        "adjudication": Choice(
            instructions=(
                "Compare the response to the accepted answers for this quiz question and "
                "judge whether it is correct, partly correct, incorrect, or too ambiguous to "
                "call."
            ),
            criteria=dict(_CRITERIA),
        )
    }


def settle(fields: dict[str, Any]) -> str | None:
    """The outcome Python can decide without asking Jev, or ``None`` if the response needs a
    model call.

    A `NUMBER`-kind question is always settled here, never sent to Jev (S07: "Jev is not a
    calculator"): ``parse_number`` either finds the same value as the accepted one (`match`) or
    it does not (`no_match`), including when the response names no number at all. A
    `TEXT`-kind question is settled only when its normalised response exactly equals the
    normalised form of some accepted phrasing (`match`); anything else, including a
    misspelling, an over-specific answer, a hedge or a wrong answer, needs Jev's judgment and
    this returns ``None``. An alternative phrasing this recipe did not anticipate (one not in
    ``QUESTION_BANK``'s own ``accepted`` tuple) is exactly that "anything else": it is not
    settled here either, whatever its meaning, because the normaliser only ever certifies a
    match against a phrasing Python was told about in advance; telling a genuine alternative
    apart from a wrong answer is Jev's job, not this function's.
    """
    quiz = QUESTION_BANK[fields["quiz_id"]]
    response = fields["response"]
    if quiz["kind"] == NUMBER:
        value = parse_number(response)
        return MATCH if value is not None and value == quiz["value"] else NO_MATCH
    response_norm = normalize_text(response)
    accepted_norms = {normalize_text(answer) for answer in quiz["accepted"]}
    return MATCH if response_norm in accepted_norms else None


@dataclass(frozen=True)
class Adjudication:
    """What Python decided for one response: which example this is, the outcome, why, and
    whether a model call was needed to reach it.

    ``example_id`` is whatever the caller passes as the first argument to ``adjudicate``
    (this recipe always passes the fixture's own id, such as ``"d02-review"``); it is not a
    quiz id. A quiz id (such as ``"tower"``) is in ``fields["quiz_id"]``, unchanged, and in
    ``queue_item``'s output, for anything that needs to look the quiz up.
    """

    example_id: str
    outcome: str
    reason: str
    settled_without_a_call: bool


def adjudicate(
    example_id: str, fields: dict[str, Any], answer: Any, min_confidence: float
) -> Adjudication:
    """Adjudicate one response.

    The normaliser goes first (``settle``) and wins whenever it can decide, unconditionally:
    even a supplied ``answer`` that disagrees with it is never read, not only when ``answer``
    is ``None``. Otherwise ``answer`` must be Jev's `Choice` answer to the question
    ``build_questions`` returns, and two independent conditions each send it to
    ``needs_review`` instead of reporting a grade: Jev choosing `needs_review` itself (an
    outcome Python never second-guesses), and a confidence below ``min_confidence`` for any of
    the other three choices. `needs_review` is never a final score: CONTRIBUTING.md section 4
    treats awarding or withholding a point as a side effect, so every `needs_review` outcome,
    whatever sent it there, is for a simulated human adjudicator, not this rule, to resolve.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    settled = settle(fields)
    if settled is not None:
        return Adjudication(example_id, settled, "settled by the normaliser, no model call", True)
    if answer is None:
        raise ValueError(f"{example_id} was not settled by the normaliser and needs a Jev answer")
    if answer.choice == NEEDS_REVIEW:
        return Adjudication(example_id, NEEDS_REVIEW, "the model chose needs_review", False)
    if answer.confidence < min_confidence:
        return Adjudication(example_id, NEEDS_REVIEW, "confidence below the threshold", False)
    return Adjudication(example_id, answer.choice, "confidence met the threshold", False)
