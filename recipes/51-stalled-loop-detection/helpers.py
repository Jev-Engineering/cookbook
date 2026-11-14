"""Python's half of recipe 51: the state, the question, and the supervision policy.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question, the state and the policy cannot disagree.

Jev is asked one narrow thing at each checkpoint of a recorded agent transcript: how does the
latest turn compare with the turns before it? Everything that follows from that judgment is
code: the confidence gate, the mapping from a progress label to continue / change strategy /
stop, the limit of one strategy change per transcript, and the hard turn budget.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice
from jev_cookbook.evaluation import select_confidence_threshold

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

ADVANCING = "advancing"
REPEATING = "repeating"
REGRESSING = "regressing"
COMPLETE = "complete"
UNCLEAR = "unclear"

# One fixed order for every checkpoint. It carries no meaning a position statistic could use,
# and the notebook prints none.
OPTIONS = (ADVANCING, REPEATING, REGRESSING, COMPLETE, UNCLEAR)
STALLS = frozenset({REPEATING, REGRESSING})

_DESCRIPTIONS = {
    ADVANCING: (
        "The latest turn moves the task forward: it produces a result the earlier turns did "
        "not have, fixes or narrows something they left open, or tries a genuinely different "
        "approach after one that did not work."
    ),
    REPEATING: (
        "The latest turn redoes something an earlier turn already did and learns nothing new "
        "from it: the same step, possibly reworded or with trivially different options, "
        "ending in the same result or the same error as before."
    ),
    REGRESSING: (
        "The latest turn undoes or breaks progress an earlier turn had made: something that "
        "worked now fails, a result that was in place is removed or overwritten, or the task "
        "is further from the goal than it was before this turn."
    ),
    COMPLETE: (
        "The latest turn shows the goal is met: the result the goal asks for is present and "
        "confirmed by the turn's own output, with nothing in the turns contradicting it."
    ),
    UNCLEAR: (
        "The turns shown do not settle which of the other four describes the latest turn: "
        "its result is missing, cut off, or not about the goal at all."
    ),
}

INSTRUCTIONS = (
    "An agent is working toward the goal below, one turn at a time. Each turn lists the action "
    "the agent took, the result it observed, and the agent's own note. Judging the latest turn "
    "against the turns before it, which describes the agent's progress toward the goal? Judge "
    "from the actions and the results; the agent's own note is a claim, not evidence."
)

# Policy settings. Python owns them; no answer can change them.
MAX_TURNS = 8  # the supervisor stops any transcript at this turn, whatever the answer
MAX_STRATEGY_CHANGES = 1  # after this many changes, a further confident repeat stops the run

CONTINUE = "continue"
REVIEW = "review"
CHANGE_STRATEGY = "change_strategy"
STOP = "stop"

REASON_LOW_CONFIDENCE = "confidence below the threshold"
REASON_UNCLEAR = "progress unclear from the turns shown"
REASON_ADVANCING = "confident advancing"
REASON_COMPLETE = "task complete"
REASON_REGRESSING = "regressing: progress was lost"
REASON_REPEATING = "repeating: change strategy"
REASON_REPEATING_AGAIN = "still repeating after a strategy change"
REASON_REPEATING_AT_BUDGET = "repeating at the turn budget"
REASON_BUDGET = "turn budget reached"

# A stop or a strategy change for one of these reasons is a stall intervention, the event
# detection delay is measured to. A stop for "task complete" or for "turn budget reached" (the
# budget decided, whatever the label) is not. A confident stall label at the budget turn keeps a
# stall reason of its own, so the action log and detection read the same reason.
STALL_REASONS = frozenset(
    {REASON_REGRESSING, REASON_REPEATING, REASON_REPEATING_AGAIN, REASON_REPEATING_AT_BUDGET}
)


def render_turns(turns: list[dict[str, str]]) -> str:
    """The turns as the text Jev reads, oldest first, the latest one marked."""
    lines = []
    last = len(turns)
    for number, turn in enumerate(turns, start=1):
        marker = " (latest)" if number == last else ""
        lines.append(f"Turn {number}{marker}")
        lines.append(f"  action: {turn['action']}")
        lines.append(f"  result: {turn['result']}")
        lines.append(f"  note: {turn['note']}")
    return "\n".join(lines)


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees at one checkpoint: the goal and the turns up to and including it.

    ``fields`` also carries the transcript reference and the checkpoint's turn number. Python
    keeps both and attaches them to the outcome, so neither passes through the model.
    """
    return {"goal": fields["goal"], "turns": render_turns(fields["turns"])}


def build_questions() -> dict[str, Choice]:
    """The one question asked at every checkpoint. The options come from ``OPTIONS``."""
    return {
        "progress": Choice(
            instructions=INSTRUCTIONS,
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


def threshold_pool(
    answers: list[Any], gold: list[str], turns: list[int]
) -> tuple[list[bool], list[float]]:
    """``(correct, confidences)`` for the answers that may set the gate.

    ``turns`` is each answer's checkpoint turn. Two kinds of answer are left out, because the
    gate cannot act on them: an ``unclear`` answer (a confident one goes to review whatever the
    threshold, so only answers naming one of the four actionable labels can set the bar), and a
    checkpoint at ``turn >= MAX_TURNS`` (the budget stops the run there whatever the answer, so
    the gate has no effect on it and its correctness cannot say where the gate should sit).

    This is the one place that decides which answers are in the selection. The notebook, the
    tests and ``choose_threshold`` all call it.
    """
    if not len(answers) == len(gold) == len(turns):
        raise ValueError("answers, gold and turns must have the same length")
    correct, confidences = [], []
    for a, g, t in zip(answers, gold, turns, strict=True):
        if a.choice != UNCLEAR and t < MAX_TURNS:
            correct.append(a.choice == g)
            confidences.append(a.confidence)
    return correct, confidences


def choose_threshold(answers: list[Any], gold: list[str], turns: list[int]) -> float:
    """The frozen gate: the lowest confidence at which every answer that clears it is right.

    The selection pool comes from ``threshold_pool``, so the result does not depend on the
    caller having filtered anything first. The tests derive the threshold through this function.
    The notebook calls ``threshold_pool`` and then ``select_confidence_threshold`` in its own
    cell, so that its objective is visible there, and a test checks that the two agree.
    """
    correct, confidences = threshold_pool(answers, gold, turns)
    return select_confidence_threshold(correct, confidences, target_accuracy=1.0)


def _answer_decision(
    choice: str, confidence: float, threshold: float, changes_used: int
) -> tuple[str, str]:
    """The table for one answer, before the turn budget: the gate, then the label."""
    if choice not in OPTIONS:
        raise ValueError(f"unknown progress label {choice!r}")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold!r}")
    if confidence < threshold:
        return REVIEW, REASON_LOW_CONFIDENCE
    if choice == UNCLEAR:
        return REVIEW, REASON_UNCLEAR
    if choice == ADVANCING:
        return CONTINUE, REASON_ADVANCING
    if choice == COMPLETE:
        return STOP, REASON_COMPLETE
    if choice == REGRESSING:
        return STOP, REASON_REGRESSING
    # REPEATING: one change of strategy is allowed; a further confident repeat stops the run.
    if changes_used < MAX_STRATEGY_CHANGES:
        return CHANGE_STRATEGY, REASON_REPEATING
    return STOP, REASON_REPEATING_AGAIN


def transition(
    choice: str, confidence: float, threshold: float, changes_used: int, turn: int
) -> tuple[str, str]:
    """``(decision, reason)`` for one checkpoint, from the answer, the run's state and the turn.

    A pure function and the one table: the supervised run, the gold run, the baseline,
    ``checkpoint_answered``, the review queue and the action log all use it, so they can differ
    only in the labels they are fed. A label taken at face value (a gold label, or the
    baseline's) is passed with confidence 1.0, which clears any threshold.

    The turn budget is part of the table. At ``turn >= MAX_TURNS`` the run stops whatever the
    answer: the budget is a hard stop owned by Python, so a below-threshold or ``unclear``
    answer at that turn is stopped, not queued for review, and a confident ``repeating`` is
    stopped instead of asking for a change, with the stall reason "repeating at the turn
    budget". An answer that stops the run anyway (``complete``, ``regressing``, a further
    ``repeating``) keeps its own reason; every other answer stops with the reason "turn budget
    reached", which says the budget decided and not the label.
    """
    decision, reason = _answer_decision(choice, confidence, threshold, changes_used)
    if turn >= MAX_TURNS and decision != STOP:
        if decision == CHANGE_STRATEGY:
            return STOP, REASON_REPEATING_AT_BUDGET
        return STOP, REASON_BUDGET
    return decision, reason


def checkpoint_answered(answer: Any, threshold: float, turn: int) -> bool:
    """Whether the model's answer decides what the policy does at this checkpoint, judged on
    its own: the answer is passed to ``transition`` as the run's first chance to change strategy
    (``changes_used=0``), not with the run's actual count of changes so far.

    Built from ``transition`` rather than re-typed. A checkpoint is not answered when it is sent
    to review (below the gate, or a confident ``unclear``, whatever its confidence) or when the
    turn budget decides the outcome (reason "turn budget reached"): the run stops at the budget
    turn whatever the label, so the label was not acted on. A budget-turn answer that stops the
    run for its own reason (``complete``, ``regressing``, ``repeating``) is answered.

    With the current table a confident ``repeating`` is answered whether or not a change was
    already used (it asks for a change, or stops the run), so this agrees with every run; a test
    checks that over multi-checkpoint runs. A table that sent the post-change branch to review
    would make the two differ, and that test would fail.
    """
    decision, reason = transition(answer.choice, answer.confidence, threshold, 0, turn)
    return decision != REVIEW and reason != REASON_BUDGET


@dataclass(frozen=True)
class Step:
    """What the supervisor decided at one checkpoint."""

    transcript: str
    turn: int
    choice: str
    decision: str
    reason: str


@dataclass(frozen=True)
class Run:
    """One transcript replayed under the policy, up to the checkpoint where it stopped."""

    transcript: str
    steps: tuple[Step, ...]
    stopped_at: int | None  # the turn of the stop, or None when the transcript ran out first
    stop_reason: str | None
    stall_interventions: tuple[int, ...]  # the turn of every stall intervention, in order

    @property
    def first_stall_intervention(self) -> int | None:
        """The turn of the first stall intervention, if any."""
        return self.stall_interventions[0] if self.stall_interventions else None


def _run(
    transcript: str, checkpoints: list[tuple[int, str, float]], threshold: float, on_step=None
) -> Run:
    """Walk ``(turn, choice, confidence)`` in turn order through ``transition``, the one table."""
    turns = [turn for turn, _, _ in checkpoints]
    if turns != sorted(turns) or len(set(turns)) != len(turns):
        raise ValueError(f"{transcript}: checkpoints must be in strictly increasing turn order")
    steps: list[Step] = []
    changes = 0
    stalls: list[int] = []
    for turn, choice, confidence in checkpoints:
        decision, reason = transition(choice, confidence, threshold, changes, turn)
        step = Step(transcript, turn, choice, decision, reason)
        steps.append(step)
        if on_step is not None:
            on_step(step)
        if reason in STALL_REASONS:
            stalls.append(turn)
        if decision == CHANGE_STRATEGY:
            changes += 1
        if decision == STOP:
            return Run(transcript, tuple(steps), turn, reason, tuple(stalls))
    return Run(transcript, tuple(steps), None, None, tuple(stalls))


def label_run(transcript: str, labelled: list[tuple[int, str]]) -> Run:
    """The policy applied to labels taken at face value (gold labels, or a baseline's).

    Nothing is written, and every label is passed with confidence 1.0, so each one clears the
    gate: a label here is taken as an answer the supervisor was sure of.
    """
    return _run(transcript, [(turn, label, 1.0) for turn, label in labelled], 1.0)


def supervise(
    transcript: str,
    answers: list[tuple[int, Any]],
    threshold: float,
    *,
    queue: Any,
    actions: Any,
) -> Run:
    """Replay one transcript's answered checkpoints under the policy, writing what it does.

    Before the turn budget every answer is gated the same way, with no exemption: below
    ``threshold`` it goes to the review queue with the reason "confidence below the threshold";
    a confident ``unclear`` goes there too, with its own reason, and the loop continues in both
    cases. At turn ``MAX_TURNS`` the budget is a hard stop owned by Python: whatever the answer,
    including one the gate would have sent to review, the run stops, the stop is recorded in the
    action log (reason "turn budget reached", "repeating at the turn budget" for a confident
    first ``repeating``, or the answer's own reason when it stops the run anyway), and nothing is
    queued. A strategy change or a stop is recorded in the action log
    (simulated: nothing is executed). Checkpoints after a stop are never consumed.
    """
    by_turn = {turn: answer for turn, answer in answers}

    def write(step: Step) -> None:
        answer = by_turn[step.turn]
        item = {"transcript": step.transcript, "turn": step.turn, "choice": step.choice}
        if step.decision == REVIEW:
            queue.submit(item, step.reason, answer=answer, step=step.turn)
        elif step.decision in (CHANGE_STRATEGY, STOP):
            actions.record(step.decision, item, step=step.turn, answer=answer, rule=step.reason)

    checkpoints = [(turn, answer.choice, answer.confidence) for turn, answer in answers]
    return _run(transcript, checkpoints, threshold, on_step=write)


def stall_onset(labelled: list[tuple[int, str]]) -> int | None:
    """The first turn whose gold label is a stall (``repeating`` or ``regressing``), if any."""
    for turn, label in labelled:
        if label in STALLS:
            return turn
    return None


@dataclass(frozen=True)
class Detection:
    """How one run's stall interventions line up with the gold stall onset."""

    transcript: str
    onset: int | None
    intervened: int | None  # the first stall intervention at or after the onset
    outcome: str  # "detected" or "missed" when there is a stall point, else "no stall"
    delay: int | None  # intervened - onset, for a detected stall only
    false_alarm: int | None  # the turn of the first stall intervention before the onset, or on a
    # transcript that never stalls; reported apart from the outcome


def detection(run: Run, onset: int | None) -> Detection:
    """Compare a run's stall interventions with the gold onset.

    A transcript with a stall point is ``detected`` when the run has a stall intervention at or
    after the onset (the first one is the detection, and its distance from the onset is the
    delay) and ``missed`` otherwise, including a run that stopped for another reason first. So
    detected plus missed is the number of transcripts with a stall point. A stall intervention
    before the onset, or any on a transcript that never stalls, is a false alarm: it is recorded
    in ``false_alarm`` and does not change the outcome, so an early false alarm cannot hide a
    later correct detection.
    """
    turns = run.stall_interventions
    if onset is None:
        return Detection(run.transcript, None, None, "no stall", None, turns[0] if turns else None)
    early = [t for t in turns if t < onset]
    false_alarm = early[0] if early else None
    seen = next((t for t in turns if t >= onset), None)
    if seen is None:
        return Detection(run.transcript, onset, None, "missed", None, false_alarm)
    return Detection(run.transcript, onset, seen, "detected", seen - onset, false_alarm)


def exact_repeat_baseline(turns: list[dict[str, str]]) -> str:
    """A rule with no judgment: ``repeating`` when the latest action and result are identical,
    character for character, to an earlier turn's; ``advancing`` otherwise.

    It never says ``regressing``, ``complete`` or ``unclear``.
    """
    *earlier, latest = turns
    key = (latest["action"], latest["result"])
    if any((t["action"], t["result"]) == key for t in earlier):
        return REPEATING
    return ADVANCING
