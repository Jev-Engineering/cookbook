"""Python's half of recipe 25: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions, the state and the rule cannot disagree.

Design in one paragraph: a proposed change record (a fabricated change-ticket narrative, the
kind a change-advisory process would read before approving a deployment) is passed to Jev
unchanged -- Python adds nothing and removes nothing from it. Jev answers three independent
``Noul`` propositions about the same record in one request: does it provide sufficient
implementation evidence, sufficient validation evidence, and sufficient rollback evidence.
Python turns each answer into a business tag against its own frozen threshold, applies a
shared confidence gate to all three, and composes the three label decisions into one of three
checklist outcomes -- ``ready``, ``gaps`` or ``review`` -- in ``review_checklist`` below, the
one function every rule this recipe enforces lives in.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The three independent propositions, asked together in one request per change record
# (CONTRIBUTING.md section 3: independent questions over the same state go in one request).
# Each is named with an "_evidence" suffix throughout this recipe, deliberately: two of this
# recipe's fixture splits are themselves named "validation" and "test", so a proposition
# bluntly named "validation" would read, in prose and in code, as if it meant the split. A
# dict, not a set, so Python's own build order is stable.
IMPLEMENTATION_EVIDENCE = "implementation_evidence"
VALIDATION_EVIDENCE = "validation_evidence"
ROLLBACK_EVIDENCE = "rollback_evidence"
LABELS: tuple[str, ...] = (IMPLEMENTATION_EVIDENCE, VALIDATION_EVIDENCE, ROLLBACK_EVIDENCE)

# The three checklist outcomes ``review_checklist`` can report. REVIEW is the lexicon's own
# outcome string (docs/glossary.md#review), shared by every other recipe's confidence-gated
# outcome.
READY = "ready"
GAPS = "gaps"
REVIEW = "review"

REASON_REVIEW = "confidence below the threshold"
REASON_READY = "all three evidence types are sufficient"


def reason_gaps(gaps: frozenset) -> str:
    """The reason string ``review_checklist`` reports for a non-empty gap list: the gap names,
    sorted, so the same set of gaps always reads the same way regardless of dict order."""
    return f"missing evidence: {', '.join(sorted(gaps))}"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one change record: the record text, and nothing else.

    ``fields`` carries only ``record``, the fabricated change-ticket narrative. The example id
    is never part of the state, and Python adds no excerpting or redaction here: unlike a
    retrieved document, a change record submitted for review is read in full by whoever
    approves it, so there is nothing for Python to trim before Jev sees the same thing a human
    reviewer would."""
    return {"record": fields["record"]}


def build_questions() -> dict[str, Noul]:
    """The three independent propositions asked about every change record, in one request.

    All three describe the same record, so ``backend.decide`` sends them together: TypeSafe's
    primitives page (S02) says independent questions over the same state belong in one
    request. Each is written as a statement that is true or false, as CONTRIBUTING.md requires
    of a ``Noul``, never as a question: a record can independently provide or lack
    implementation evidence, validation evidence, and rollback evidence, so they stay three
    separate ``Noul`` propositions rather than one ``Choice`` or one combined question -- a
    ``Choice`` would force Jev to adjudicate the combination itself, when the combination is
    exactly what CONTRIBUTING.md section 3 asks Python to decompose and compose in code."""
    return {
        IMPLEMENTATION_EVIDENCE: Noul(
            instructions=(
                "The change record describes what was actually implemented in enough "
                "concrete detail to identify the change that was made."
            ),
            criteria={
                "true": (
                    "The record names specific components, files, configuration, or steps "
                    "that were changed, with enough detail that a reader could identify "
                    "exactly what was modified."
                ),
                "false": (
                    "The record does not say what was actually changed, or only vaguely "
                    "gestures at it (for example 'the change was made' or 'implementation "
                    "attached') without naming any specific component, file, or step."
                ),
            },
        ),
        VALIDATION_EVIDENCE: Noul(
            instructions=(
                "The change record describes how the change was tested or validated before "
                "being proposed for deployment, including what was checked and what the "
                "result was."
            ),
            criteria={
                "true": (
                    "The record names a specific test, check, or validation activity that "
                    "was performed against this change, and states its outcome -- for "
                    "example which suite ran, what was checked, and that it passed or what "
                    "it showed."
                ),
                "false": (
                    "The record does not describe any specific validation activity or its "
                    "result, or only asserts that validation happened (for example "
                    "'validated per process', 'QA signed off', or 'tested') without naming "
                    "what was actually checked or what the result was."
                ),
            },
        ),
        ROLLBACK_EVIDENCE: Noul(
            instructions=(
                "The change record describes the concrete steps that would be taken to roll "
                "the change back if it needed to be reversed."
            ),
            criteria={
                "true": (
                    "The record names the specific actions that would undo this change if "
                    "needed -- for example which commit, build, backup, or configuration to "
                    "restore, and how."
                ),
                "false": (
                    "The record does not describe how to undo the change, even if it says a "
                    "rollback plan exists (for example 'a rollback plan is in place' or "
                    "'rollback plan: see runbook') or states no rollback is needed without "
                    "explaining why none is needed."
                ),
            },
        ),
    }


@dataclass(frozen=True)
class LabelDecision:
    """What Python decided for one (change record, proposition) pair: the business tag against
    that proposition's own frozen threshold, and whether the shared confidence gate sends it to
    review."""

    label: str
    noul: float
    tag: bool
    confidence: float
    gated: bool


def decide_labels(
    answers: Any, thresholds: dict[str, float], confidence_gate: float
) -> dict[str, LabelDecision]:
    """Apply each proposition's own business threshold and the shared confidence gate to one
    request's three answers.

    ``answers`` is a mapping from label name to a Noul answer (or anything with a ``.noul``).
    For every label in ``LABELS``:

    - the business tag is ``noul >= thresholds[label]`` (sufficient evidence of that kind);
    - ``confidence`` is ``noul_confidence(noul)`` (S03, ``|2p - 1|``);
    - ``gated`` is ``confidence < confidence_gate``, whatever the business tag says.

    ``review_checklist`` below is what actually turns a gated label into the ``review``
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


@dataclass(frozen=True)
class ChecklistResult:
    """Python's composed, task-level decision for one change record: one of ``READY``,
    ``GAPS`` or ``REVIEW``, the reason it was reached, the set of evidence types the checklist
    found insufficient (empty for ``READY``, and left empty rather than guessed at for
    ``REVIEW``, since no final checklist was reached), and the three label decisions it was
    composed from."""

    outcome: str
    reason: str
    gaps: frozenset
    implementation_evidence: LabelDecision
    validation_evidence: LabelDecision
    rollback_evidence: LabelDecision


def review_checklist(decisions: dict[str, LabelDecision]) -> ChecklistResult:
    """Compose the three per-proposition decisions into one checklist outcome.

    This is the one rule this recipe enforces whatever the model answers, and it is the only
    place the three propositions are combined. In order:

    1. Any label gated by the shared confidence gate sends the whole change record to
       ``REVIEW``, whichever way its own business tag reads: a reviewer, not a forced guess,
       decides a record Python is not confident enough about on even one dimension.
    2. Otherwise, the gap list is every label whose business tag reads insufficient
       (``tag`` is ``False``). An empty gap list reports ``READY``; a non-empty one reports
       ``GAPS`` with the reason naming exactly which evidence types are missing.

    Args:
        decisions: ``{label: LabelDecision}`` as returned by :func:`decide_labels`, naming
            exactly the three labels in ``LABELS``.

    Returns:
        A :class:`ChecklistResult`.
    """
    implementation = decisions[IMPLEMENTATION_EVIDENCE]
    validation = decisions[VALIDATION_EVIDENCE]
    rollback = decisions[ROLLBACK_EVIDENCE]
    if implementation.gated or validation.gated or rollback.gated:
        return ChecklistResult(
            REVIEW, REASON_REVIEW, frozenset(), implementation, validation, rollback
        )
    gaps = frozenset(label for label, decision in decisions.items() if not decision.tag)
    if gaps:
        return ChecklistResult(GAPS, reason_gaps(gaps), gaps, implementation, validation, rollback)
    return ChecklistResult(READY, REASON_READY, frozenset(), implementation, validation, rollback)


def gold_gap_set(label: dict) -> frozenset:
    """The gold gap set for one example's label record: every proposition in ``LABELS`` whose
    gold value is ``False``, exactly the set :func:`review_checklist` would report as ``gaps``
    if every stored decision matched its gold value. Used to evaluate the checklist's gap list
    against the gold evidence record at task level, never to derive one proposition's gold
    value from another's -- every entry of ``label`` is an independent, separately authored
    boolean; this only reads them."""
    return frozenset(name for name in LABELS if not label[name])


def review_sort_key(result: ChecklistResult) -> float:
    """The ascending key a notebook sorts ``REVIEW`` change records by before submitting them
    to the simulated queue: the lowest of the three labels' own confidence, so the record
    Python is least sure about -- on any of the three propositions -- surfaces first. Ties are
    broken by submission id, which the notebook supplies separately (this function sees no
    identifier)."""
    return min(
        result.implementation_evidence.confidence,
        result.validation_evidence.confidence,
        result.rollback_evidence.confidence,
    )


def gating_label(result: ChecklistResult) -> str:
    """The name of the proposition whose confidence is :func:`review_sort_key`'s minimum for
    ``result`` -- the one that actually sent the record to review when ``result.outcome`` is
    ``REVIEW``. Ties break in ``LABELS`` order, the same tie-break ``review_sort_key`` itself
    relies on when a notebook sorts queued records by ``(review_sort_key(result), example_id)``.
    A queue entry's recorded ``answer`` should be this label's, not an arbitrary other one, so
    a reviewer reading "the typed answer that sent this item to review" is shown the answer the
    reason is actually about."""
    return min(LABELS, key=lambda label: getattr(result, label).confidence)


def queue_item(example_id: str, fields: dict[str, Any], result: ChecklistResult) -> dict[str, Any]:
    """What a human reviewer sees for one queued change record: its id, the record Jev was
    actually asked about, and all three label decisions -- not only an identifier
    (CONTRIBUTING.md section 4: the queue is the side effect a ``review`` outcome triggers, and
    an item with nothing to read is not something a person can actually review)."""
    return {
        "id": example_id,
        "record": fields["record"],
        IMPLEMENTATION_EVIDENCE: {
            "noul": result.implementation_evidence.noul,
            "confidence": result.implementation_evidence.confidence,
        },
        VALIDATION_EVIDENCE: {
            "noul": result.validation_evidence.noul,
            "confidence": result.validation_evidence.confidence,
        },
        ROLLBACK_EVIDENCE: {
            "noul": result.rollback_evidence.noul,
            "confidence": result.rollback_evidence.confidence,
        },
    }
