"""Python's half of recipe 40: the taxonomy, the questions, and the policy that routes a
document through it in stages, carrying more than one department forward when the first stage
is uncertain.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------------------------
# The taxonomy: two levels, built by Python, never by the model. A document is routed to
# exactly one department first, then (unless the department is the fallback) to one topic
# inside that department. The fallback department, UNCLASSIFIED, is terminal: it has no topics
# of its own, so Python never builds a second-stage question for it (CONTRIBUTING.md section 3,
# "Single-option Choice" in docs/backends.md: a department with no real topics never reaches a
# request).
# --------------------------------------------------------------------------------------------

ACCOUNT_BILLING = "account_billing"
PRODUCT_TECHNICAL = "product_technical"
PEOPLE_POLICY = "people_policy"
UNCLASSIFIED = "unclassified"

REAL_DEPARTMENTS = (ACCOUNT_BILLING, PRODUCT_TECHNICAL, PEOPLE_POLICY)
DEPARTMENTS = (*REAL_DEPARTMENTS, UNCLASSIFIED)

# Two of the three real departments, deliberately, share a topic name ("general_question"):
# account_billing's catch-all for a billing message that is not an invoice or a refund, and
# product_technical's catch-all for a product message that is not a bug report or a how-to
# question. Comparing a predicted document against its gold label on the BARE topic name alone
# would score "account_billing.general_question" and "product_technical.general_question" as
# the same answer; this recipe's own gold labels and its policy's final result are always the
# full "<department>.<topic>" path for exactly this reason (see "The shared-name trap" in the
# notebook and tests/test_helpers.py::test_the_shared_topic_name_would_be_a_false_match).
LEAVES_BY_DEPARTMENT: dict[str, tuple[str, ...]] = {
    ACCOUNT_BILLING: ("invoice_question", "refund_request", "general_question"),
    PRODUCT_TECHNICAL: ("bug_report", "how_to_question", "general_question"),
    PEOPLE_POLICY: ("leave_policy", "security_policy"),
}

# Every full path, plus the fallback itself: the flat baseline's option set (CONTRIBUTING.md
# section 3's "Choice needs at least two options" is satisfied many times over -- 9 options).
FLAT_LEAVES: tuple[str, ...] = tuple(
    f"{department}.{topic}"
    for department in REAL_DEPARTMENTS
    for topic in LEAVES_BY_DEPARTMENT[department]
) + (UNCLASSIFIED,)

ANSWERED = "answered"
REVIEW = "review"

_DEPARTMENT_DESCRIPTIONS = {
    ACCOUNT_BILLING: (
        "The message is about money owed, paid, or refunded on this account: an invoice, a "
        "charge, a subscription payment, or a request for money back. A message that reports "
        "the product itself failing to work, even about a billing page, belongs to "
        "product_technical instead."
    ),
    PRODUCT_TECHNICAL: (
        "The message reports the product failing to behave as built, or asks how to use a "
        "feature: an error, a crash, a page that will not load, or a how-to question about "
        "the product. A message asking to change a charge or a subscription, with no sign "
        "anything is broken, belongs to account_billing instead."
    ),
    PEOPLE_POLICY: (
        "The message is about a company policy that governs people at work: time off, leave, "
        "or workplace security requirements. It is not about this account's product or its "
        "billing at all."
    ),
    UNCLASSIFIED: (
        "The message does not resolve to one of the above: it is too vague, raises several "
        "unrelated topics at once, or is not a work request at all (a thank-you note, small "
        "talk, something off-topic)."
    ),
}

_LEAF_DESCRIPTIONS: dict[str, dict[str, str]] = {
    ACCOUNT_BILLING: {
        "invoice_question": (
            "A question about a specific invoice or charge already issued: its amount, date, "
            "or where to find it."
        ),
        "refund_request": (
            "A request for money back, in part or in full, for a charge already made."
        ),
        "general_question": (
            "A billing question that is not about one specific invoice and is not a refund "
            "request: how billing works in general, or a request to change a subscription."
        ),
    },
    PRODUCT_TECHNICAL: {
        "bug_report": (
            "A specific report that something in the product is broken: an error, a crash, or "
            "a feature that will not do what it is supposed to."
        ),
        "how_to_question": (
            "A question about how to use a feature that is working as built; nothing is "
            "reported broken."
        ),
        "general_question": (
            "A product question that is neither a bug report nor a how-to question: general "
            "feedback or a question too vague to be either."
        ),
    },
    PEOPLE_POLICY: {
        "leave_policy": "A question about time off, vacation, or leave entitlement.",
        "security_policy": (
            "A question about workplace security requirements: passwords, device rules, or "
            "access policy."
        ),
    },
}

_FLAT_DESCRIPTIONS: dict[str, str] = {
    f"{department}.{topic}": (
        f"{_DEPARTMENT_DESCRIPTIONS[department]} Specifically: {_LEAF_DESCRIPTIONS[department][topic]}"
    )
    for department in REAL_DEPARTMENTS
    for topic in LEAVES_BY_DEPARTMENT[department]
}
_FLAT_DESCRIPTIONS[UNCLASSIFIED] = _DEPARTMENT_DESCRIPTIONS[UNCLASSIFIED]


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one document: its text, and nothing else.

    ``fields`` also carries ``doc_id``, a bookkeeping identifier. Python keeps it and attaches
    it to every outcome below, so it never needs to pass through the model.
    """
    return {"text": fields["text"]}


def build_department_question() -> Choice:
    """The first-stage question, asked about every document: which department should handle
    it? The fixed option set is ``DEPARTMENTS`` -- the three real departments, plus the
    fallback this use case names (CONTRIBUTING.md section 3)."""
    return Choice(
        instructions="Which department should handle this message?",
        criteria={name: _DEPARTMENT_DESCRIPTIONS[name] for name in DEPARTMENTS},
    )


def build_topic_question(department: str) -> Choice:
    """The second-stage question, asked only for a real department: which topic inside it best
    fits this document? Raises ``ValueError`` for ``UNCLASSIFIED`` (and any other name that is
    not a real department): the fallback is terminal, so Python never builds a question for it
    -- a document routed there is a complete answer in itself, not a request waiting to be
    asked (docs/backends.md, "Single-option Choice")."""
    if department not in LEAVES_BY_DEPARTMENT:
        raise ValueError(f"{department!r} has no topic question: not a real department")
    topics = LEAVES_BY_DEPARTMENT[department]
    return Choice(
        instructions=f"Which {department} topic best fits this message?",
        criteria={name: _LEAF_DESCRIPTIONS[department][name] for name in topics},
    )


def build_flat_question() -> Choice:
    """The flat baseline's one question: every full taxonomy path at once, with no stages."""
    return Choice(
        instructions=(
            "Which entry in the taxonomy below -- department and topic together -- best fits "
            "this message?"
        ),
        criteria=dict(_FLAT_DESCRIPTIONS),
    )


def department_of(full_path: str) -> str:
    """The department named by a full path (``"account_billing.invoice_question"`` ->
    ``"account_billing"``), or ``UNCLASSIFIED`` unchanged. Used to recover the gold department
    from a gold leaf label without ever deriving one gold value from another: both are read
    from the same stored string, never guessed."""
    return UNCLASSIFIED if full_path == UNCLASSIFIED else full_path.split(".", 1)[0]


def rank_real_departments(department_answer: Any) -> list[str]:
    """The three real departments, ranked by the department answer's own probability,
    descending; ties broken by name so the ranking is deterministic for any model answer."""
    probabilities = department_answer.probabilities
    return sorted(REAL_DEPARTMENTS, key=lambda name: (-probabilities[name], name))


def best_topic(topic_answer: Any) -> tuple[str, float]:
    """A topic answer's own top choice and its own probability (the probability of exactly the
    option the answer already names, read from the answer's own ``probabilities`` -- never
    assumed equal to ``topic_answer.confidence``, which is a *rescaled* quantity, not the raw
    top probability; see the confidence formula in docs/glossary.md)."""
    return topic_answer.choice, topic_answer.probabilities[topic_answer.choice]


@dataclass(frozen=True)
class ResolvedPath:
    """What the policy decided for one document, before any review gate: the department and
    topic it settled on, the full path, the composite confidence that path carries, whether
    more than one department was explored, and how many requests that took."""

    doc_id: str
    department: str
    leaf: str
    path_confidence: float
    branched: bool
    requests: int


def resolve_path(
    doc_id: str,
    department_answer: Any,
    topic_answers: dict[str, Any],
    branch_margin: float,
) -> ResolvedPath:
    """The composed routing decision: ask the department question once; if its own confidence
    clears ``branch_margin``, commit to the single top-ranked REAL department (greedy, one
    further request for its topic -- ``rank_real_departments`` ranks only the real
    departments, so the department this commits to is never the fallback); otherwise, carry
    the top two real departments forward and ask the topic question for each of them, so an
    early, uncertain judgment never forecloses a department the model was not sure to rule
    out. Either way, at least one topic request is always spent: the fallback is an additional
    candidate, scored at no request of its own from the department answer's own probability
    for it, but it never substitutes for the topic request already spent on a real
    department, so no document resolves in fewer than two requests.

    ``branch_margin = 0.0`` makes this never branch (confidence is never less than 0), which is
    exactly the greedy single-path baseline this use case names -- the same tested function, not a
    second copy of it, parametrised at the one value that turns branching off.

    Every candidate path's own confidence is the product of the department's probability for
    that department and the topic's own probability for the chosen topic (both already in
    [0, 1], so the product is too): a document Jev is unsure is even in a department, that
    department's model is in turn unsure how to classify further, correctly ends up with a low
    composite confidence, whatever either stage's raw probability alone would suggest. The
    fallback, UNCLASSIFIED, has no topic of its own, so its candidate confidence is simply the
    department answer's own probability for it.

    ``topic_answers`` must carry exactly the departments this call explores (``KeyError``
    otherwise, naming which key the caller omitted) -- the notebook decides which departments
    to explore from ``department_answer`` and ``branch_margin`` before spending any topic
    request, and this function re-derives the same set to pick among the answers it was given,
    so the two can never silently disagree about which departments were explored.
    """
    if not 0.0 <= branch_margin <= 1.0:
        raise ValueError(f"branch_margin must be between 0 and 1, got {branch_margin!r}")
    ranked = rank_real_departments(department_answer)
    branched = department_answer.confidence < branch_margin
    explored = ranked[:2] if branched else ranked[:1]

    candidates: list[tuple[float, str, str]] = []
    for department in explored:
        if department not in topic_answers:
            raise KeyError(f"no topic answer supplied for explored department {department!r}")
        topic, topic_probability = best_topic(topic_answers[department])
        score = department_answer.probabilities[department] * topic_probability
        candidates.append((score, department, topic))
    candidates.append((department_answer.probabilities[UNCLASSIFIED], UNCLASSIFIED, UNCLASSIFIED))

    best_score, best_department, best_topic_name = max(candidates, key=lambda c: c[0])
    leaf = (
        UNCLASSIFIED if best_department == UNCLASSIFIED else f"{best_department}.{best_topic_name}"
    )
    requests = 1 + len(explored)
    return ResolvedPath(doc_id, best_department, leaf, best_score, branched, requests)


@dataclass(frozen=True)
class Routing:
    """A resolved path, gated: the final outcome a reader of the review queue actually sees."""

    doc_id: str
    leaf: str
    path_confidence: float
    outcome: str
    reason: str


def gate_path(resolved: ResolvedPath, review_gate: float) -> Routing:
    """Accept a resolved path as a final result only when its own composite confidence clears
    ``review_gate``; anything below goes to an explicit ``review`` outcome instead. The rule is
    code, so it holds whatever the model answers, however many departments were explored to
    reach it.
    """
    if not 0.0 <= review_gate <= 1.0:
        raise ValueError(f"review_gate must be between 0 and 1, got {review_gate!r}")
    if resolved.path_confidence < review_gate:
        return Routing(
            resolved.doc_id,
            resolved.leaf,
            resolved.path_confidence,
            REVIEW,
            "confidence below the threshold",
        )
    return Routing(
        resolved.doc_id, resolved.leaf, resolved.path_confidence, ANSWERED, "confident path"
    )


def classify_flat(doc_id: str, flat_answer: Any) -> tuple[str, str, int]:
    """The flat baseline: one request, no stages, no review branch. Returns
    ``(doc_id, leaf, requests)`` with ``requests`` always 1, so it lines up with
    ``ResolvedPath.requests`` for the request-count comparison."""
    return doc_id, flat_answer.choice, 1
