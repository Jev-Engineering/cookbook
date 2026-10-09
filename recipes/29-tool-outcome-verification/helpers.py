"""Python's half of recipe 29: the state, the question, and the two-stage rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice
from jev_cookbook.simulation import ActionLog, ReviewQueue

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed outcome set the use case names. ``complete`` is listed last, not first: if a model
# leaned toward whichever option is listed first, listing the costly outcome last points that
# lean away from it rather than toward it -- a wrong ``complete`` leaves a false success
# standing, which is exactly the mistake CONTRIBUTING.md section 4 asks every option to be
# gated against, so the fixed order does not also give that mistake a head start. "Evaluation"
# in the notebook prints how often the raw answer actually lands on the first-listed option
# (``unverifiable``), on both splits, so the claim is checked against this fixture set rather
# than merely asserted.
UNVERIFIABLE = "unverifiable"
FAILED = "failed"
PARTIAL = "partial"
COMPLETE = "complete"
OUTCOMES = (UNVERIFIABLE, FAILED, PARTIAL, COMPLETE)

REVIEW = "review"

# Descriptions say what belongs to each outcome and, for the pair that is easiest to confuse
# (failed vs. unverifiable, over a run that reports success with nothing to back it up),
# what does *not* belong to the other outcome: ``unverifiable`` is a lack of evidence either
# way; ``failed`` needs a positive sign the request was not carried out (an error, a wrong or
# missing artefact, a contradiction with what was reported), not merely silence.
_DESCRIPTIONS = {
    UNVERIFIABLE: (
        "The evidence does not establish whether the request was carried out or not, either "
        "way. It may be missing, too thin to judge, or simply not about what the request "
        "actually asked for. This is different from failed: nothing here shows the request "
        "was NOT fulfilled, there just is not enough to show that it was."
    ),
    FAILED: (
        "The evidence shows the request was not fulfilled: an error message, a wrong or "
        "missing artefact, or an exit status that contradicts what the tool reported. This "
        "holds even when the tool's own reported status says the run succeeded -- a reported "
        "status is not itself evidence, and the rest of the record governs when it disagrees "
        "with it."
    ),
    PARTIAL: (
        "The evidence shows some, but not all, of the request was carried out: part of the "
        "work is confirmed done, and part is confirmed missing, skipped, or unsuccessful, both "
        "visible in the same record."
    ),
    COMPLETE: (
        "The evidence shows the entire request was carried out: the tool's reported status, "
        "its output, and the artefacts it lists all agree that every part of what was asked "
        "for is done, with nothing contradicting it."
    ),
}


def render_evidence(fields: dict[str, Any]) -> str:
    """Render one tool-run record into the text excerpt Jev actually reads.

    Every field that could justify a gold label is in this rendering: the tool's own reported
    status, its exit code, the artefacts it listed, and its stdout/stderr excerpts. Nothing a
    stored answer's probabilities are based on is held back from this text.
    """
    artifacts = fields["artifacts"]
    listed = ", ".join(artifacts) if artifacts else "(none listed)"
    stdout = fields["stdout_excerpt"] or "(no stdout captured)"
    stderr = fields["stderr_excerpt"] or "(no stderr captured)"
    return "\n".join(
        [
            f"Tool: {fields['tool']}",
            f"Reported status: {fields['reported_status']}",
            f"Exit code: {fields['exit_code']}",
            f"Artefacts listed: {listed}",
            "Stdout excerpt:",
            stdout,
            "Stderr excerpt:",
            stderr,
        ]
    )


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one tool run: the original request and the rendered evidence.

    ``fields`` also carries ``call_id``, bookkeeping Python keeps to itself and attaches to the
    outcome afterwards; it never passes through the model.
    """
    return {"request": fields["request"], "evidence": render_evidence(fields)}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every tool run. The options come from ``OUTCOMES``."""
    return {
        "outcome": Choice(
            instructions=(
                "An agent asked a tool to carry out the request above. Given the request and "
                "the evidence the tool run reports below, which outcome best describes whether "
                "the request was fulfilled? Judge from the evidence as a whole, not from the "
                "reported status alone."
            ),
            criteria={name: _DESCRIPTIONS[name] for name in OUTCOMES},
        )
    }


# What Python does next with an accepted answer. ``complete`` hands the result off as a
# finished piece of work; ``partial`` and ``failed`` both name work that still needs doing, so
# both schedule a retry, with the reason recording which of the two it was and why.
# ``unverifiable`` names neither a finished result nor work Python knows how to retry -- it
# says the evidence cannot tell, which is a question for a person, not an automated remedy --
# so it is never logged to ``ActionLog``, confident or not (see ``classify`` below).
ACTION_HANDOFF = "handoff accepted"
ACTION_RETRY = "retry scheduled"

_RETRY_REASONS = {
    PARTIAL: "partial completion: the evidence confirms part of the request was not done",
    FAILED: "reported failure: the evidence shows the request was not fulfilled",
}

# The next step CONTRIBUTING.md section 4 and this use case's build notes compose from the
# verified outcome, read off the gold label alone (ignoring what Jev answered): what the system
# *should* do once the true outcome is known. ``next_step_agreement`` below compares this
# against what the rule actually did, which is the task-level metric this recipe's own
# "Evaluation" reports alongside per-question accuracy.
NEXT_STEP = {
    COMPLETE: ACTION_HANDOFF,
    PARTIAL: ACTION_RETRY,
    FAILED: ACTION_RETRY,
    UNVERIFIABLE: REVIEW,
}


@dataclass(frozen=True)
class Outcome:
    """What Python decided for one tool run: ``outcome`` is the gold-comparable label when the
    gate accepted the answer (one of ``OUTCOMES``), or ``"review"`` when the gate rejected it
    for low confidence; ``action`` is the ``ActionLog`` entry it recorded, or ``None`` when the
    run went to the ``ReviewQueue`` instead; ``reason`` is why."""

    call_id: str
    outcome: str
    action: str | None
    reason: str


def classify(
    call_id: str,
    answer: Any,
    min_confidence: float,
    *,
    actions: ActionLog,
    queue: ReviewQueue,
) -> Outcome:
    """Decide what happens with one verified tool outcome.

    Every option goes through the same confidence gate first, whatever it is: an answer below
    ``min_confidence`` is sent to ``queue`` with the reason ``"confidence below the threshold"``,
    and that is the only condition under which this reason is used. There is no exemption for
    any option -- CONTRIBUTING.md section 4's no-gate exemption is for a fallback that records
    no action and costs nothing beyond the missed item when wrong, and a wrong ``complete``
    here fails that on both counts: it is recorded to ``actions`` as a finished handoff, and
    being wrong about it leaves a run that was really ``partial``, ``failed``, or
    ``unverifiable`` standing as accepted work, with nobody told to look again.

    Once an answer clears the gate, ``unverifiable`` is still not a result Python can act on:
    it says the evidence itself cannot settle the question, which is a person's call, so it is
    sent to ``queue`` too, with its own reason -- accepted by the gate, not rejected for low
    confidence, but still a human decision either way. ``complete`` is logged to ``actions`` as
    an accepted handoff; ``partial`` and ``failed`` are both logged to ``actions`` as a
    scheduled retry, with the reason naming which of the two it was.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.confidence < min_confidence:
        queue.submit(
            {"call": call_id, "choice": answer.choice},
            "confidence below the threshold",
            answer=answer,
        )
        return Outcome(call_id, REVIEW, None, "confidence below the threshold")
    # Every question option is a key of ``_DESCRIPTIONS`` (``OUTCOMES`` and ``_DESCRIPTIONS``
    # are built from the same names), and the backend already rejects an answer whose choice is
    # outside the question's own options before this rule ever sees it (docs/backends.md):
    # this relies on that guarantee rather than re-checking it, which docs/recipe-template.md
    # documents as an equally acceptable alternative to a defensive membership branch.
    if answer.choice == UNVERIFIABLE:
        queue.submit(
            {"call": call_id, "choice": answer.choice},
            "evidence does not establish the outcome",
            answer=answer,
        )
        return Outcome(call_id, UNVERIFIABLE, None, "evidence does not establish the outcome")
    if answer.choice == COMPLETE:
        actions.record(ACTION_HANDOFF, {"call": call_id}, answer=answer, rule="confident complete")
        return Outcome(call_id, COMPLETE, ACTION_HANDOFF, "confident complete")
    reason = _RETRY_REASONS[answer.choice]
    actions.record(
        ACTION_RETRY,
        {"call": call_id, "reason": reason},
        answer=answer,
        rule=f"confident {answer.choice}",
    )
    return Outcome(call_id, answer.choice, ACTION_RETRY, reason)


def accepted_and_correct(
    outcomes: list[Outcome], gold: dict[str, str]
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``.

    ``accepted[i]`` is whether ``classify`` reported one of the two substantive, actionable
    outcomes (``complete``, or ``partial``/``failed``) for run ``i``, rather than sending it to
    a person -- ``review`` (rejected for low confidence) and ``unverifiable`` (accepted by the
    gate, but a deferral: it answers "we cannot tell", not the question that was asked) both
    count as not accepted, whatever confidence produced either one. ``correct[i]`` is whether
    that outcome equals the gold label (computed, but not meaningful, where ``accepted[i]`` is
    False, exactly as ``evaluate_outcomes`` documents)."""
    accepted = [o.outcome not in (REVIEW, UNVERIFIABLE) for o in outcomes]
    correct = [o.outcome == gold[o.call_id] for o in outcomes]
    return accepted, correct


def actual_next_step(outcome: Outcome) -> str:
    """The next step the rule actually took for one run: ``"handoff accepted"``,
    ``"retry scheduled"``, or ``"review"`` (both the confidence-gated and the ``unverifiable``
    paths to the ``ReviewQueue`` count as the same next step, since both ask a person rather
    than acting)."""
    if outcome.outcome in (REVIEW, UNVERIFIABLE):
        return REVIEW
    return outcome.action


def next_step_agreement(outcomes: list[Outcome], gold: dict[str, str]) -> float:
    """The share of runs whose actual next step (above) matches the next step
    ``helpers.NEXT_STEP`` names for the true gold label -- the task-level metric: not "did Jev
    name the right outcome" but "did the composed system do the right thing next", read off
    the gold label alone regardless of what produced the match. This can exceed or trail raw
    per-question accuracy: ``partial`` and ``failed`` share one next step, so naming one gold
    class as the other still agrees here, while a correct ``unverifiable`` sent to review by
    the gate for low confidence, rather than because the gate recognised it as unverifiable,
    still agrees with gold too."""
    if not outcomes:
        raise ValueError("outcomes must not be empty")
    agreement = [actual_next_step(o) == NEXT_STEP[gold[o.call_id]] for o in outcomes]
    return sum(agreement) / len(agreement)


def self_report_baseline(reported_status: str) -> str:
    """A trivial baseline with no judgment at all: trust the tool's own reported status.

    ``"success"`` -> ``complete``, ``"failure"`` -> ``failed``, ``"partial_success"`` ->
    ``partial``, anything else (``"in_progress"``, ``"unknown"``, ...) -> ``unverifiable``. This
    is wrong on exactly the hard cases this recipe is built to show: a run that reports success
    with nothing to back it up, and a run that reports success while its own output
    contradicts it, both read as ``complete`` by this baseline alone.
    """
    return {"success": COMPLETE, "failure": FAILED, "partial_success": PARTIAL}.get(
        reported_status, UNVERIFIABLE
    )
