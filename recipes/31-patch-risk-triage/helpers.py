"""Python's half of recipe 31: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions, the state and the rule cannot disagree.

Design in one paragraph: a small patch (a fabricated unified-diff-style excerpt, schematic
rather than runnable, naming only invented files, functions and packages) is passed to Jev
unchanged -- Python adds nothing and removes nothing from it. Jev answers three independent
``Noul`` propositions about the same patch in one request: does it weaken or bypass an
authentication check, does it leave untrusted input unvalidated before a sensitive operation,
and does it risk permanent, unrecoverable data loss. Python turns each answer into a business
tag against its own frozen threshold, applies a shared confidence gate to all three, and
composes the three tags into one of three review priorities -- ``urgent``, ``elevated`` or
``routine`` -- or an explicit ``review`` outcome when the gate is not cleared, in
``review_priority`` below, the one function every rule this recipe enforces lives in. This
prioritises which patches a human reviewer looks at first; it is not a security scanner and
finds nothing on its own that Python and Jev were not each explicitly asked to check.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence, select_confidence_threshold, select_threshold

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The three independent propositions, asked together in one request per patch (CONTRIBUTING.md
# section 3: independent questions over the same state go in one request). Each is named with
# a "_concern" suffix throughout this recipe, deliberately: one fixture split is itself named
# "validation" and a proposition about input checking would otherwise read, in prose and in
# code, as if it meant the split. A dict, not a set, so Python's own build order is stable.
AUTHENTICATION_CONCERN = "authentication_concern"
INPUT_VALIDATION_CONCERN = "input_validation_concern"
DATA_LOSS_CONCERN = "data_loss_concern"
LABELS: tuple[str, ...] = (AUTHENTICATION_CONCERN, INPUT_VALIDATION_CONCERN, DATA_LOSS_CONCERN)

# The review priorities review_priority can report, ascending. REVIEW is the lexicon's own
# outcome string (docs/glossary.md#review), shared by every other recipe's confidence-gated
# outcome, and takes precedence over all three.
ROUTINE = "routine"
ELEVATED = "elevated"
URGENT = "urgent"
REVIEW = "review"

REASON_REVIEW = "confidence below the threshold"
REASON_ROUTINE = "no concerns flagged"

# The shared confidence gate's objective parameter: the minimum answered share the gate must
# keep, among thresholds meeting it the one with the highest pooled accuracy (ties going to
# the lower threshold, i.e. more coverage). Chosen over a 1.0 accuracy target deliberately:
# a target of 1.0 forces validation accuracy to 1.0 by construction, which is not a property
# this recipe wants to report (see the notebook's "Python's part" section). Named once here so
# that both the notebook and tests/test_helpers.py select by exactly the same objective and
# parameter; a test asserts the frozen gate cannot change without this constant changing too.
MIN_COVERAGE = 0.8


def reason_concerns(concerns: frozenset) -> str:
    """The reason string :func:`review_priority` reports for a non-empty flagged-concern set:
    the concern names, sorted, so the same set of concerns always reads the same way regardless
    of dict order."""
    return f"flagged concerns: {', '.join(sorted(concerns))}"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one patch: the diff excerpt, and nothing else.

    ``fields`` carries only ``diff``, the fabricated patch excerpt. The example id is never
    part of the state, and Python adds no trimming here: a patch submitted for review is read
    in full by whoever triages it, so there is nothing for Python to excerpt before Jev sees
    the same text a human reviewer would."""
    return {"diff": fields["diff"]}


def build_questions() -> dict[str, Noul]:
    """The three independent propositions asked about every patch, in one request.

    All three describe the same diff, so ``backend.decide`` sends them together: TypeSafe's
    primitives page (S02) says independent questions over the same state belong in one
    request. Each is written as a statement that is true or false, as CONTRIBUTING.md requires
    of a ``Noul``, never as a question: a patch can independently weaken authentication, leave
    input unvalidated, and risk data loss, so they stay three separate ``Noul`` propositions
    rather than one ``Choice`` or one combined question -- a ``Choice`` would force Jev to
    adjudicate the combination itself, when the combination is exactly what CONTRIBUTING.md
    section 3 asks Python to decompose and compose in code."""
    return {
        AUTHENTICATION_CONCERN: Noul(
            instructions=(
                "The patch weakens, removes, or bypasses an authentication or authorization "
                "check that was previously enforced."
            ),
            criteria={
                "true": (
                    "The diff removes, disables, short-circuits, or lowers the strength of a "
                    "check that verifies who a caller is or what a caller is allowed to do -- "
                    "for example by deleting a verification call, adding an unconditional "
                    "bypass, or widening who is accepted without an equivalent check "
                    "elsewhere."
                ),
                "false": (
                    "The diff does not touch any authentication or authorization check, or it "
                    "only strengthens or leaves an existing check intact."
                ),
            },
        ),
        INPUT_VALIDATION_CONCERN: Noul(
            instructions=(
                "The patch leaves external input unvalidated or unsanitized before that input "
                "reaches a sensitive operation such as a query, a file path, a command, or a "
                "template."
            ),
            criteria={
                "true": (
                    "The diff removes, skips, or narrows a check that validates or sanitizes "
                    "input from outside the system before that input is used to build a "
                    "query, a file path, a command, or similar, or it introduces a new path "
                    "that reaches such an operation with no validation at all."
                ),
                "false": (
                    "The diff does not change how external input reaches a sensitive "
                    "operation, or it only adds or keeps validation that was already there."
                ),
            },
        ),
        DATA_LOSS_CONCERN: Noul(
            instructions=(
                "The patch risks permanent, unrecoverable loss of data that is already stored."
            ),
            criteria={
                "true": (
                    "The diff deletes, overwrites, or shortens the retention of stored data "
                    "with no backup, snapshot, soft-delete, or confirmation step guarding it, "
                    "or it removes a safeguard that previously existed."
                ),
                "false": (
                    "The diff does not put any stored data at risk of permanent loss, or it "
                    "keeps or adds a safeguard (a backup, a snapshot, a soft delete, a "
                    "confirmation step) around a destructive operation."
                ),
            },
        ),
    }


@dataclass(frozen=True)
class LabelDecision:
    """What Python decided for one (patch, proposition) pair: the business tag against that
    proposition's own frozen threshold, and whether the shared confidence gate sends it to
    review."""

    label: str
    noul: float
    tag: bool
    confidence: float
    gated: bool


def decide_concerns(
    answers: Any, thresholds: dict[str, float], confidence_gate: float
) -> dict[str, LabelDecision]:
    """Apply each proposition's own business threshold and the shared confidence gate to one
    request's three answers.

    ``answers`` is a mapping from label name to a Noul answer (or anything with a ``.noul``).
    For every label in ``LABELS``:

    - the business tag is ``noul >= thresholds[label]`` (the concern is flagged);
    - ``confidence`` is ``noul_confidence(noul)`` (S03, ``|2p - 1|``);
    - ``gated`` is ``confidence < confidence_gate``, whatever the business tag says.

    ``review_priority`` below is what actually turns a gated label into the ``review``
    outcome; this function only records the two ingredients it needs.

    Args:
        answers: ``{label: NoulAnswer-like}``, one per label in ``LABELS``.
        thresholds: The frozen per-label business thresholds (chosen on ``validation``); must
            name exactly the labels in ``LABELS``, no more and no fewer.
        confidence_gate: The frozen shared confidence gate (chosen on ``validation``, pooled
            across all three labels; see the notebook's "Python's part" section for why one
            shared value is used rather than three separate parameters).

    Returns:
        ``{label: LabelDecision}``, one entry per label in ``LABELS``.
    """
    if not 0.0 <= float(confidence_gate) <= 1.0:
        raise ValueError(f"confidence_gate must be between 0 and 1, got {confidence_gate!r}")
    if set(thresholds) != set(LABELS):
        raise ValueError(f"thresholds must name exactly LABELS {LABELS}, got {sorted(thresholds)}")
    decisions: dict[str, LabelDecision] = {}
    for label in LABELS:
        threshold = thresholds[label]
        if not 0.0 <= float(threshold) <= 1.0:
            raise ValueError(f"threshold for {label!r} must be between 0 and 1, got {threshold!r}")
        noul = float(answers[label].noul)
        tag = noul >= threshold
        confidence = noul_confidence([noul])[0]
        gated = confidence < confidence_gate
        decisions[label] = LabelDecision(label, noul, tag, confidence, gated)
    return decisions


def choose_label_threshold(gold: Any, noul: Any) -> float:
    """The business threshold for one concern, chosen on ``validation`` by F1. A thin wrapper
    around :func:`jev_cookbook.evaluation.select_threshold` so the objective this recipe
    selects by is named in exactly one place, and a test can check that place rather than
    re-deriving the threshold with a second, possibly different, call."""
    return select_threshold(gold, noul, objective="f1")


def choose_gate(correct: Any, confidence: Any) -> float:
    """The shared confidence gate, chosen on the pooled (patch, concern) decisions by
    :data:`MIN_COVERAGE`. A thin wrapper around
    :func:`jev_cookbook.evaluation.select_confidence_threshold` so the objective and its
    parameter are named in exactly one place, never inlined at the call site, and a test can
    assert that this function -- not a differently-parameterised call written elsewhere --
    is what the notebook's own selection runs."""
    return select_confidence_threshold(correct, confidence, min_coverage=MIN_COVERAGE)


def priority_from_concerns(flagged: frozenset) -> tuple[str, str]:
    """The explicit rule that turns a set of flagged concerns into a review priority, with no
    confidence involved: the one place this recipe states which combinations of authentication,
    input-validation and data-loss concerns count as more urgent than others.

    A patch that risks permanent data loss is ``URGENT`` on its own -- a reviewer cannot undo a
    wrong call about it later the way they could reopen a ticket -- and so is any patch that
    combines an authentication weakness with an unvalidated input path, because together they
    describe a route an outside caller could use to reach something they should not. A patch
    with exactly one of the authentication or input-validation concerns, and no data-loss
    concern, is ``ELEVATED``: worth a reviewer's attention sooner than routine, but not on its
    own the combination this recipe treats as urgent. A patch with none of the three flagged is
    ``ROUTINE``.

    This function is called both by :func:`review_priority` (on Python's business tags) and by
    this recipe's fixture generator (on the gold labels), so the composition a stored answer is
    scored against and the composition the gold combination implies are never two separate
    implementations of the same rule.

    Args:
        flagged: The subset of :data:`LABELS` whose business tag (or gold value) is True.

    Returns:
        ``(priority, reason)``: ``priority`` is one of :data:`URGENT`, :data:`ELEVATED` or
        :data:`ROUTINE`; ``reason`` is :data:`REASON_ROUTINE` when ``flagged`` is empty, or
        :func:`reason_concerns` of ``flagged`` otherwise.
    """
    if not flagged:
        return ROUTINE, REASON_ROUTINE
    if DATA_LOSS_CONCERN in flagged or (
        AUTHENTICATION_CONCERN in flagged and INPUT_VALIDATION_CONCERN in flagged
    ):
        return URGENT, reason_concerns(flagged)
    return ELEVATED, reason_concerns(flagged)


@dataclass(frozen=True)
class PriorityResult:
    """Python's composed, task-level decision for one patch: one of :data:`URGENT`,
    :data:`ELEVATED`, :data:`ROUTINE` or :data:`REVIEW`, the reason it was reached, the set of
    concerns the triage found flagged (empty for ``ROUTINE``, and left empty rather than guessed
    at for ``REVIEW``, since no final priority was reached), and the three label decisions it
    was composed from."""

    priority: str
    reason: str
    concerns: frozenset
    authentication_concern: LabelDecision
    input_validation_concern: LabelDecision
    data_loss_concern: LabelDecision


def review_priority(decisions: dict[str, LabelDecision]) -> PriorityResult:
    """Compose the three per-proposition decisions into one review priority.

    This is the one rule this recipe enforces whatever the model answers, and it is the only
    place the three propositions are combined. In order:

    1. Any label gated by the shared confidence gate sends the whole patch to ``REVIEW``,
       whichever way its own business tag reads: a reviewer, not a forced guess, decides a
       patch Python is not confident enough about on even one dimension.
    2. Otherwise, the flagged-concern set is every label whose business tag reads True, and
       :func:`priority_from_concerns` turns it into ``URGENT``, ``ELEVATED`` or ``ROUTINE``.

    Args:
        decisions: ``{label: LabelDecision}`` as returned by :func:`decide_concerns`, naming
            exactly the three labels in ``LABELS``.

    Returns:
        A :class:`PriorityResult`.
    """
    authentication = decisions[AUTHENTICATION_CONCERN]
    input_validation = decisions[INPUT_VALIDATION_CONCERN]
    data_loss = decisions[DATA_LOSS_CONCERN]
    if authentication.gated or input_validation.gated or data_loss.gated:
        return PriorityResult(
            REVIEW, REASON_REVIEW, frozenset(), authentication, input_validation, data_loss
        )
    concerns = frozenset(label for label, decision in decisions.items() if decision.tag)
    priority, reason = priority_from_concerns(concerns)
    return PriorityResult(priority, reason, concerns, authentication, input_validation, data_loss)


def gold_concern_set(label: dict) -> frozenset:
    """The gold flagged-concern set for one example's label record: every proposition in
    ``LABELS`` whose gold value is ``True``, exactly the set :func:`review_priority` would
    report as ``concerns`` if every stored decision matched its gold value. Used to evaluate the
    composed priority against the gold combination at task level, never to derive one
    proposition's gold value from another's -- every entry of ``label`` is an independent,
    separately authored boolean; this only reads them."""
    return frozenset(name for name in LABELS if label[name])


def review_sort_key(result: PriorityResult) -> float:
    """The ascending key a notebook sorts ``REVIEW`` patches by before submitting them to the
    simulated queue: the lowest of the three labels' own confidence, so the patch Python is
    least sure about -- on any of the three propositions -- surfaces first. Ties are broken by
    submission id, which the notebook supplies separately (this function sees no identifier)."""
    return min(
        result.authentication_concern.confidence,
        result.input_validation_concern.confidence,
        result.data_loss_concern.confidence,
    )


def gating_label(result: PriorityResult) -> str:
    """The name of the proposition whose confidence is :func:`review_sort_key`'s minimum for
    ``result`` -- the one that actually sent the patch to review when ``result.priority`` is
    ``REVIEW``. Ties break in ``LABELS`` order, the same tie-break :func:`review_sort_key` itself
    relies on when a notebook sorts queued patches by ``(review_sort_key(result), example_id)``.
    A queue entry's recorded answer should be this label's, not an arbitrary other one, so a
    reviewer reading "the typed answer that sent this item to review" is shown the answer the
    reason is actually about."""
    return min(LABELS, key=lambda label: getattr(result, label).confidence)


def queue_item(example_id: str, fields: dict[str, Any], result: PriorityResult) -> dict[str, Any]:
    """What a human reviewer sees for one queued patch: its id, the diff Jev was actually asked
    about, and all three label decisions -- not only an identifier (CONTRIBUTING.md section 4:
    the queue is the side effect a ``review`` outcome triggers, and an item with nothing to read
    is not something a person can actually review)."""
    return {
        "id": example_id,
        "diff": fields["diff"],
        AUTHENTICATION_CONCERN: {
            "noul": result.authentication_concern.noul,
            "confidence": result.authentication_concern.confidence,
        },
        INPUT_VALIDATION_CONCERN: {
            "noul": result.input_validation_concern.noul,
            "confidence": result.input_validation_concern.confidence,
        },
        DATA_LOSS_CONCERN: {
            "noul": result.data_loss_concern.noul,
            "confidence": result.data_loss_concern.confidence,
        },
    }
