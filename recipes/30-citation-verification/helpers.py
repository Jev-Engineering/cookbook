"""Python's half of recipe 30: the corpus, the state, the question and the two-stage rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice
from jev_cookbook.simulation import ActionLog, ReviewQueue

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------------------------
# The corpus. A small, fixed set of fabricated internal documents (CONTRIBUTING.md section 5:
# fabricated names only), each split into numbered sections. This is the only place passage
# text lives: a claim's fixture never carries the passage itself, only a citation -- a
# document id and a section number -- that Python resolves against this table. Nothing here
# is a real product, vendor or policy.
# --------------------------------------------------------------------------------------------
CORPUS: dict[str, dict[str, str]] = {
    "RATE-LIMITS": {
        "1": (
            "The public API enforces a default rate limit of 100 requests per minute per "
            "API key. Requests beyond the limit receive a 429 response with a Retry-After "
            "header."
        ),
        "2": (
            "The rate limit window slides continuously over the trailing 60 seconds; it does "
            "not reset on the calendar minute. A burst of 100 requests just before the "
            "minute rolls over and another 100 just after can both succeed within a couple "
            "of seconds of each other."
        ),
        "3": (
            "A verified partner account may request a higher rate limit, up to 1,000 "
            "requests per minute, by filing a quota increase request through the partner "
            "portal."
        ),
        "4": (
            "Rate limit counters are tracked per API key, not per account, so an account "
            "with three API keys has three independent 100-requests-per-minute allowances."
        ),
    },
    "AUTH-TOKENS": {
        "1": (
            "Access tokens issued by the login endpoint expire 15 minutes after issue and "
            "cannot be renewed; a client must request a new token from the login endpoint "
            "once the old one expires."
        ),
        "2": (
            "Refresh tokens expire 30 days after issue, or immediately if the account's "
            "password is changed, whichever comes first."
        ),
        "3": (
            "A token's audience claim must name the service receiving it; a service that "
            "receives a token naming a different audience must reject it, even if the "
            "signature is otherwise valid."
        ),
    },
    "RETRY-POLICY": {
        "1": (
            "A client that receives a 503 response should retry the same request after "
            "waiting at least 2 seconds, doubling the wait on each subsequent 503, up to a "
            "maximum of 5 attempts."
        ),
        "2": (
            "A client must never retry a 400 or 422 response automatically: both indicate a "
            "problem with the request itself that a retry cannot fix."
        ),
        "3": (
            "Retries are not attempted for requests that are not idempotent (for example, a "
            "payment submission) unless the client supplies an idempotency key."
        ),
    },
    "STORAGE-QUOTAS": {
        "1": (
            "Each workspace on the standard plan may store up to 50 GB of attached files; "
            "the enterprise plan raises this to 500 GB."
        ),
        "2": (
            "A file exceeding 2 GB in size is rejected at upload time, regardless of how "
            "much quota remains in the workspace."
        ),
        "3": (
            "Deleted files are retained for 14 days in a recovery area before being "
            "permanently erased, and still count against the workspace's quota during that "
            "period."
        ),
    },
}

# The fixed option set the use case names, in the order it names them. Adapted from TypeSafe's
# citation-checking cookbook (S06, https://docs.typesafe.ai/cookbooks/citation_check): a Choice
# named "relation" with three options -- one for a passage that backs the claim, one for a
# passage that states the opposite, and a third for a passage that settles neither way. That
# third option is "unsupported" here, and it is also the use case's own fallback outcome
# (CONTRIBUTING.md section 3): it covers a passage that is simply about something else, one
# that only settles a narrower or different point, and -- the hard case this recipe's build
# notes name -- a passage that is the wrong one for an otherwise correct claim. Unlike recipe
# 20's three-way "relation" (whose first two descriptions below are adapted from, closely
# following its wording), there is no model-facing citation-resolution option here at all: a
# citation that does not resolve to any passage is resolved by Python alone, below, before a
# question is ever built.
SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
CONTRADICTED = "contradicted"
OPTIONS = (SUPPORTED, UNSUPPORTED, CONTRADICTED)

_DESCRIPTIONS = {
    SUPPORTED: (
        "The passage states the claim, or directly implies that it is true. A passage that "
        "states a strictly stronger fact also supports a weaker claim it logically contains."
    ),
    UNSUPPORTED: (
        "The passage does not establish whether the claim is true or false. This covers a "
        "passage that is simply about a different topic, one that only settles a narrower "
        "or different point than the claim makes, and one that shares words with the claim "
        "without actually addressing what the claim asserts."
    ),
    CONTRADICTED: (
        "The passage states the opposite of the claim, or gives a number, a date, or "
        "another concrete detail that is inconsistent with it."
    ),
}


def resolve_citation(fields: dict[str, Any]) -> str | None:
    """Python's first stage, and the only one that ever runs for every claim: look up
    ``fields["doc"]``/``fields["section"]`` in :data:`CORPUS` and return the passage text it
    names, or ``None`` when the citation does not resolve -- an unknown document, an unknown
    section, or both.

    This never reaches Jev. A citation that does not resolve leaves nothing for a ``Choice``
    to weigh: there is no passage to check the claim against, so -- exactly as
    CONTRIBUTING.md section 3 describes for a Choice with no real options -- the decision
    belongs to Python, not to a request, and :func:`classify` below never builds one for it.
    """
    return CORPUS.get(fields["doc"], {}).get(fields["section"])


def trust_citation_baseline(fields: dict[str, Any]) -> str:
    """A baseline with no judgment about the passage at all: trust that a citation which
    resolves to a real passage supports the claim, without ever reading what the passage
    says. A citation that does not resolve is ``unsupported`` here too -- the same forced
    call :func:`classify` makes for it, since there is no passage behind it either way."""
    return SUPPORTED if resolve_citation(fields) is not None else UNSUPPORTED


def citation_label(fields: dict[str, Any]) -> str:
    """The citation as a reader would write it, for printing: ``"RATE-LIMITS§4"``."""
    return f"{fields['doc']}§{fields['section']}"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one claim: the claim and the passage its citation names.

    Call this only once :func:`resolve_citation` has already found a passage for ``fields``
    -- never for a citation that does not resolve, which never reaches this function, let
    alone Jev. ``fields["doc"]`` and ``fields["section"]`` are bookkeeping Python keeps to
    itself; neither passes through the model, and :func:`classify` reattaches the citation to
    the outcome afterwards so every result still traces back to where it came from.
    """
    passage = resolve_citation(fields)
    if passage is None:
        raise ValueError(
            f"build_state called with a citation that does not resolve: {citation_label(fields)}"
        )
    return {"claim": fields["claim"], "passage": passage}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every claim whose citation resolves. The options come
    from :data:`OPTIONS`."""
    return {
        "relation": Choice(
            instructions="How does the passage relate to the claim?",
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


# What Python does with an accepted verdict. A kept claim needed no correction; a flagged one
# did -- whether because the model named it unsupported or contradicted with enough
# confidence, or because Python never found a passage to check it against in the first place.
ACTION_KEEP = "kept as cited"
ACTION_FLAG = "flagged for correction"

REVIEW = "review"
REASON_NOT_RESOLVED = "citation identifier does not resolve"
REASON_LOW_CONFIDENCE = "confidence below the threshold"

# The use case's own flag decision, read off a label alone: a supported claim needs no
# correction; an unsupported or contradicted one does. helpers.flag_agreement below compares
# this, computed from the TRUE gold label, against what the rule actually did.
_FLAG_FOR = {SUPPORTED: False, UNSUPPORTED: True, CONTRADICTED: True}


@dataclass(frozen=True)
class Verdict:
    """What Python decided for one claim: ``citation_resolved`` is whether stage 1 found a
    passage at all; ``verdict`` is one of :data:`OPTIONS` when the claim was decided (the
    model's accepted choice, or the forced ``unsupported`` of an unresolved citation), or
    ``"review"`` when it was sent to a person instead; ``action`` is the ``ActionLog`` entry
    recorded, or ``None`` when ``verdict`` is ``"review"``; ``reason`` says why."""

    claim_id: str
    citation_resolved: bool
    verdict: str
    action: str | None
    reason: str


def classify(
    claim_id: str,
    fields: dict[str, Any],
    answer: Any | None,
    min_confidence: float,
    *,
    actions: ActionLog,
    queue: ReviewQueue,
) -> Verdict:
    """Decide what happens with one cited claim.

    ``answer`` is the stored ``relation`` answer for this claim, or ``None`` when
    :func:`resolve_citation` found no passage for it -- the caller never asks a question in
    that case, so there is no answer object to pass, and this is the only way ``classify``
    itself learns the citation did not resolve. That branch is not a confidence-gated review:
    nothing was asked, nothing was uncertain, there is simply no passage behind the citation,
    so Python flags it for correction directly and the claim never passes through the
    confidence gate below. Flagging it this way, rather than sending it to ``queue``, matches
    the fallback test in CONTRIBUTING.md section 4: it is a complete answer ("this citation
    has nothing behind it"), not a deferral asking a person to settle the same question again.

    Once a citation resolves, every option goes through the same confidence gate: an answer
    below ``min_confidence`` is sent to ``queue`` with the reason
    ``"confidence below the threshold"``. At or above it, ``supported`` is kept as cited;
    ``unsupported`` and ``contradicted`` are both flagged for correction, the recorded reason
    naming which.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    citation = citation_label(fields)
    if answer is None:
        actions.record(
            ACTION_FLAG,
            {"claim": claim_id, "citation": citation},
            rule=REASON_NOT_RESOLVED,
        )
        return Verdict(claim_id, False, UNSUPPORTED, ACTION_FLAG, REASON_NOT_RESOLVED)
    if answer.confidence < min_confidence:
        queue.submit(
            {"claim": claim_id, "citation": citation, "choice": answer.choice},
            REASON_LOW_CONFIDENCE,
            answer=answer,
        )
        return Verdict(claim_id, True, REVIEW, None, REASON_LOW_CONFIDENCE)
    if answer.choice == SUPPORTED:
        actions.record(
            ACTION_KEEP,
            {"claim": claim_id, "citation": citation},
            answer=answer,
            rule="confident supported",
        )
        return Verdict(claim_id, True, SUPPORTED, ACTION_KEEP, "confident supported")
    reason = f"confident {answer.choice}"
    actions.record(
        ACTION_FLAG, {"claim": claim_id, "citation": citation}, answer=answer, rule=reason
    )
    return Verdict(claim_id, True, answer.choice, ACTION_FLAG, reason)


def accepted_and_correct(
    verdicts: list[Verdict], gold: dict[str, str]
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``.

    ``accepted[i]`` is whether ``classify`` reported a real verdict for claim ``i`` rather
    than sending it to ``queue`` -- ``review`` is the only value this excludes, so a forced
    ``unsupported`` from an unresolved citation counts as accepted: Python answered the
    question on its own, it did not ask anyone to decide it. ``correct[i]`` is whether that
    verdict equals the gold label (computed, but not meaningful, where ``accepted[i]`` is
    False, exactly as ``evaluate_outcomes`` documents).
    """
    accepted = [v.verdict != REVIEW for v in verdicts]
    correct = [v.verdict == gold[v.claim_id] for v in verdicts]
    return accepted, correct


def should_flag(gold_label: str) -> bool:
    """The flag decision the TRUE outcome calls for, read off the gold label alone: a
    supported claim needs no correction (``False``); an unsupported or contradicted one does
    (``True``)."""
    return _FLAG_FOR[gold_label]


def actual_flag(verdict: Verdict) -> bool | None:
    """What the rule actually did with one claim: ``True`` (flagged for correction), ``False``
    (kept as cited), or ``None`` (sent to review -- nobody decided either way)."""
    if verdict.verdict == REVIEW:
        return None
    return _FLAG_FOR[verdict.verdict]


def flag_agreement(verdicts: list[Verdict], gold: dict[str, str]) -> float:
    """The task-level metric: the share of claims whose actual flag/keep decision
    (:func:`actual_flag`) agrees with the flag decision the TRUE gold label calls for
    (:func:`should_flag`), read off the gold label regardless of what the model answered. A
    claim sent to review counts as disagreement whatever the gold label says -- nobody
    decided whether to flag it, so "sent to review" is never counted as the right action,
    only as a coverage cost (see "Evaluation" in the notebook for what that costs here). This
    is a different question from per-claim accuracy against the three labels:
    ``unsupported``-for-``contradicted`` is a wrong label but the right flag decision (both
    are flagged), so this can exceed raw per-question accuracy, and a correct label that
    nonetheless went to review for low confidence still disagrees here.
    """
    if not verdicts:
        raise ValueError("verdicts must not be empty")
    agreement = [actual_flag(v) == should_flag(gold[v.claim_id]) for v in verdicts]
    return sum(agreement) / len(agreement)
