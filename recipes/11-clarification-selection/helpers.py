"""Python's half of recipe 11: the state, the question and the rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed clarification catalog: each entry is one follow-up question Python may ask before a
# task moves to its next step, and the one piece of information that question is for. Jev never
# writes the question text; it only picks which entry, if any, applies. Options come from this
# predefined catalog of follow-up questions plus no_clarification_needed: Python decides between
# asking and proceeding, and the model never writes the question.
ASK_DEADLINE = "ask_deadline"
ASK_RECIPIENT = "ask_recipient"
ASK_SCOPE = "ask_scope"
ASK_FORMAT = "ask_format"
ASK_BUDGET = "ask_budget"
ASK_ACCESS_LEVEL = "ask_access_level"
# The explicit fallback outcome the use case names, for a task description that already states
# everything the next step needs. It is a Choice option like the six above, built by Python, not
# a separate code path Jev reaches by failing to answer (CONTRIBUTING.md section 3: "Include
# none, other, no_match, or uncertain outcomes when the use case calls for them.").
NO_CLARIFICATION_NEEDED = "no_clarification_needed"

ASK_OPTIONS = (
    ASK_DEADLINE,
    ASK_RECIPIENT,
    ASK_SCOPE,
    ASK_FORMAT,
    ASK_BUDGET,
    ASK_ACCESS_LEVEL,
)
OPTIONS = (*ASK_OPTIONS, NO_CLARIFICATION_NEEDED)

# The stored follow-up question text Python returns for a confident ask_* match. Jev never sees
# this text and never writes it; it only picks the identifier, the same shape as recipe 08's
# stored FAQ answers.
CLARIFYING_QUESTIONS = {
    ASK_DEADLINE: "By when do you need this finished?",
    ASK_RECIPIENT: "Who should receive the result once it's ready?",
    ASK_SCOPE: "Which records or time period should this cover?",
    ASK_FORMAT: "What file format or type should the result be in?",
    ASK_BUDGET: "Is there a budget or spending limit this needs to stay under?",
    ASK_ACCESS_LEVEL: "Who besides you should be able to view or edit this once it's created?",
}

# Descriptions say what each option is for and, for the two pairs that are easiest to confuse
# (a stated recipient vs. a stated, but narrower, access list; a stated scope vs. a stated, but
# undetermined, format), what belongs to the other option instead (TypeSafe's guidance for
# options that are easy to confuse: say what doesn't belong to a neighbouring option).
_DESCRIPTIONS = {
    ASK_DEADLINE: (
        "The task asks for something to be prepared or delivered but never says, in any form, "
        "when it is needed: no date, no day of the week, no 'by end of day/week', no event it "
        "must be ready before. Pick this only when timing is the one thing missing; a task "
        "that already gives a date or a relative deadline does not need this question, even "
        "when other details are also missing."
    ),
    ASK_RECIPIENT: (
        "The task asks for something to be produced but never says who should receive it or "
        "who it is for: no name, team, role, or 'send to' instruction. A task that already "
        "names who gets the result, even only by role ('the finance team', 'my manager'), does "
        "not need this question; naming the recipient is not the same as saying who besides "
        "the requester may edit a shared item once it exists, which belongs to "
        "ask_access_level instead."
    ),
    ASK_SCOPE: (
        "The task refers to data, records, or a report ('the numbers', 'the report', 'the "
        "list') without saying which time period, dataset, region, or category it should "
        "cover. A task whose subject is already fully specific (a single named document, a "
        "single named account) does not need this question, and neither does a task with no "
        "data or records involved at all. A missing scope is not the same as a missing "
        "deliverable shape, which belongs to ask_format instead."
    ),
    ASK_FORMAT: (
        "The task asks for a deliverable to be produced but never says what form it should "
        "take: document, spreadsheet, slide deck, PDF, or similar. Pick this only when the "
        "deliverable's shape is genuinely undetermined; a task that names the deliverable type "
        "directly ('slide deck', 'spreadsheet') does not need this question even if which data "
        "it covers is described loosely, which belongs to ask_scope instead."
    ),
    ASK_BUDGET: (
        "The task asks to book, buy, or reserve something on the requester's behalf without "
        "stating a spending limit or budget. A task that already states an amount, a price "
        "ceiling, or 'use the standard rate' does not need this question, and a task that "
        "involves no spending at all does not need it either."
    ),
    ASK_ACCESS_LEVEL: (
        "The task asks for something to be created as a shared document, folder, or dashboard "
        "without saying who besides the requester should be able to view or edit it. A task "
        "that already states who gets access, or that only produces something for the "
        "requester's own use, not shared with anyone else, does not need this question; a "
        "stated recipient of the finished result is not the same as a stated edit or view "
        "list for a shared item, which is what this option is for."
    ),
    NO_CLARIFICATION_NEEDED: (
        "The task already states everything the next step needs: what to produce, and "
        "whichever of a deadline, a recipient, a scope, a format, a budget, or an access list "
        "actually applies to this particular task. Pick this when no other option's missing "
        "piece actually applies here, not only when the task happens to mention many details."
    ),
}

# Outcomes the rule below can produce.
ASK = "ask"
PROCEED = "proceed"
REVIEW = "review"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one task: its description, and nothing else.

    ``fields`` also carries ``task_id``, a bookkeeping identifier. Python keeps it and attaches
    it to the outcome, so it never needs to pass through the model.
    """
    return {"task": fields["text"]}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every task. The options come from ``OPTIONS``: the six
    catalog follow-up questions plus the fallback ``no_clarification_needed``, all built by
    Python."""
    return {
        "clarification": Choice(
            instructions=(
                "Which single follow-up question, if any, should be asked before this task "
                "description moves to the next step?"
            ),
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


@dataclass(frozen=True)
class Selection:
    """What Python decided: the option Jev chose, the outcome, the clarifying question text
    (only when the outcome is ``ask``), and why."""

    task_id: str
    label: str
    outcome: str
    question: str | None
    reason: str


def select_followup(task_id: str, answer: Any, min_confidence: float) -> Selection:
    """Ask the stored clarifying question only when Jev names a real catalog entry and is
    confident enough; otherwise either proceed or hold the task for review.

    ``no_clarification_needed`` is never run past the confidence gate, whatever its confidence:
    the option itself already says the task needs no follow-up, so there is no clarifying
    question a confidence check could protect here (the same shape as recipe 08's
    ``no_match``). Accepting it unconditionally means a low-confidence
    ``no_clarification_needed`` answer can still be final -- but it triggers no side effect in
    this recipe: Python only returns a "proceed, nothing to ask" result, never a simulated
    action, so a wrong one costs this pipeline check some accuracy and nothing else here (it is
    exactly the mistake ``risk``, in the notebook's evaluation, is counting; in a real pipeline
    the cost would be the task moving on without the information it needed -- the notebook's
    "Python's part" section says this explicitly). Choosing a real catalog option
    that is not in ``OPTIONS`` at all (defensive: ``build_questions`` never offers such an
    option, but the rule does not trust that silently) or one whose confidence is below
    ``min_confidence`` goes to an explicit ``review`` outcome instead of asking a possibly wrong
    question. The rule is code, so it holds whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == NO_CLARIFICATION_NEEDED:
        return Selection(
            task_id, NO_CLARIFICATION_NEEDED, PROCEED, None, "the task already states everything"
        )
    if answer.choice not in ASK_OPTIONS:
        return Selection(task_id, answer.choice, REVIEW, None, "not a catalog follow-up question")
    if answer.confidence < min_confidence:
        return Selection(task_id, answer.choice, REVIEW, None, "confidence below the threshold")
    return Selection(
        task_id, answer.choice, ASK, CLARIFYING_QUESTIONS[answer.choice], "confident match"
    )


def outcome_accounting(
    results: list[Selection], gold: dict[str, Any]
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``, built from a
    list of ``Selection`` results against ``gold`` (``{task_id: label}``).

    ``accepted[i]`` is whether ``select_followup`` answered example ``i`` -- ``ask`` or
    ``proceed``, either one a real result handed back -- rather than held for ``review``, as the
    rule itself decided it; ``correct[i]`` is whether that result's label is right, computed for
    every example (``evaluate_outcomes`` requires a value even where ``accepted`` is False,
    though it never reads it there). This is deliberately not
    ``jev_cookbook.evaluation.evaluate_selective`` reapplied to every example: that helper gates
    every example on one confidence gate, but ``select_followup`` never gates
    ``no_clarification_needed`` on confidence at all, so reapplying a confidence gate to a
    ``no_clarification_needed`` answer would score a gate the rule does not have.
    """
    if not results:
        raise ValueError("outcome_accounting needs at least one result")
    accepted = [r.outcome != REVIEW for r in results]
    correct = [r.label == gold[r.task_id] for r in results]
    return accepted, correct
