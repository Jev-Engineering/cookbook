"""Python's half of recipe 19: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

import re
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice
from jev_cookbook.simulation import ActionLog, ReviewQueue

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed option set the use case names. There is no separate "none of the above" option
# distinct from UNKNOWN: a log that does not clearly support one of the other three outcomes
# is exactly what UNKNOWN is for.
TEST_REGRESSION = "test_regression"
DEPENDENCY_PROBLEM = "dependency_problem"
INFRASTRUCTURE_FAILURE = "infrastructure_failure"
UNKNOWN = "unknown"
OUTCOMES = (TEST_REGRESSION, DEPENDENCY_PROBLEM, INFRASTRUCTURE_FAILURE, UNKNOWN)

REVIEW = "review"

_DESCRIPTIONS = {
    TEST_REGRESSION: (
        "A real behaviour change in the code under test broke a test that used to pass: the "
        "failure is a genuine assertion about the code's output, not about the environment "
        "the code ran in."
    ),
    DEPENDENCY_PROBLEM: (
        "A package could not be installed, imported, or resolved to a compatible version. "
        "This also covers a failing test whose traceback ends in an import or module error: "
        "the test did not find a real behaviour change, it could not even load the package "
        "under test. When an excerpt shows both an import or module error and an unrelated "
        "assertion failure elsewhere, the import or module error governs: nothing the other "
        "test asserted can be trusted once a dependency the run needs is missing."
    ),
    INFRASTRUCTURE_FAILURE: (
        "The build or test runner itself failed, independent of the code under test: it lost "
        "its connection, ran out of memory or disk, or was killed or shut down mid-run. This "
        "also covers a test that is reported as failed only because the runner disappeared "
        "while it was in progress, before the test itself produced a real result."
    ),
    UNKNOWN: (
        "The excerpt does not clearly support one of the other three outcomes: a flaky test "
        "that failed and then passed on rerun with no other signal, or a log with conflicting "
        "or inconclusive evidence."
    ),
}

# What Python does next when it accepts an answer, keyed by outcome exactly as the build notes
# ask for: the next diagnostic workflow. The three substantive outcomes each name an automated
# remedy a real system would act on (rerun the suite, pin and rebuild dependencies, requeue on
# a fresh runner), so an accepted answer naming one of them is logged to `ActionLog`, which
# never executes anything. `unknown`'s workflow, manual triage, names no automated remedy at
# all -- it names asking a person -- so an accepted `unknown` answer is logged to `ReviewQueue`
# instead of `ActionLog`: accepting it still means Jev was confident enough to be believed, but
# what it is confident *of* is that nobody should act automatically here.
WORKFLOWS = {
    TEST_REGRESSION: "rerun_suite_with_bisect",
    DEPENDENCY_PROBLEM: "pin_and_rebuild_dependencies",
    INFRASTRUCTURE_FAILURE: "requeue_on_fresh_runner",
    UNKNOWN: "manual_triage",
}

# Lines that name a dependency or infrastructure problem are kept wherever they fall in the
# log, however far from the first failure; only the first line that names a test failure
# anchors a window, because a log can carry many of those once a suite starts failing and
# keeping every one of them would crowd out a decisive line that appears once, far away.
# Public (no leading underscore): the notebook's keyword-regex baseline reuses these same
# patterns directly, rather than re-deriving a second, possibly-drifting set.
DEPENDENCY_RE = re.compile(
    r"ModuleNotFoundError"
    r"|ImportError: cannot import"
    r"|No matching distribution found"
    r"|Could not find a version that satisfies"
    r"|conflicting dependencies"
    r"|version solving failed"
)
INFRASTRUCTURE_RE = re.compile(
    r"runner has received a shutdown signal"
    r"|[Ll]ost communication with the (runner|server)"
    r"|This step has timed out"
    r"|OOMKilled"
    r"|exit code 137"
    r"|exit code 143"
    r"|Connection reset by peer"
    r"|self-hosted runner lost"
    r"|The operation was canceled"
)
FAILURE_RE = re.compile(r"FAILED |AssertionError")

EXCERPT_CONTEXT = 1
MAX_EXCERPT_LINES = 16


def trim_log(
    full_log: str, *, context: int = EXCERPT_CONTEXT, max_lines: int = MAX_EXCERPT_LINES
) -> str:
    """Return the excerpt of ``full_log`` that Jev is asked about.

    A window of ``context`` lines is kept around every line naming a dependency or
    infrastructure problem, wherever it falls, and around the first line naming a test
    failure. A naive "window around the first failure" would miss a decisive line that sits
    far from it; scanning the whole log for the dependency and infrastructure patterns is what
    this trimming does instead. When nothing matches (an inconclusive log), the excerpt is the
    first ``max_lines`` lines, so the reader still sees where the log starts.
    """
    lines = full_log.splitlines()
    keep: set[int] = set()
    for i, line in enumerate(lines):
        if DEPENDENCY_RE.search(line) or INFRASTRUCTURE_RE.search(line):
            keep.update(range(max(0, i - context), min(len(lines), i + context + 1)))
    first_failure = next((i for i, line in enumerate(lines) if FAILURE_RE.search(line)), None)
    if first_failure is not None:
        keep.update(
            range(max(0, first_failure - context), min(len(lines), first_failure + context + 1))
        )
    if not keep:
        keep = set(range(min(len(lines), max_lines)))
    ordered = sorted(keep)[:max_lines]
    excerpt: list[str] = []
    previous: int | None = None
    for i in ordered:
        if previous is not None and i != previous + 1:
            excerpt.append("...")
        excerpt.append(lines[i])
        previous = i
    return "\n".join(excerpt)


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one build: the trimmed log excerpt, and nothing else.

    ``fields`` also carries ``build_id`` and the untrimmed ``full_log``. Python keeps both: the
    identifier never needs to pass through the model, and the full log stays in the fixtures so
    the trimming above can be checked against it, but only the excerpt is ever sent to Jev.
    """
    return {"log_excerpt": trim_log(fields["full_log"])}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every build. The options come from ``OUTCOMES``."""
    return {
        "outcome": Choice(
            instructions=(
                "This is an excerpt from a continuous-integration log. Which outcome best "
                "explains why the build failed?"
            ),
            criteria={name: _DESCRIPTIONS[name] for name in OUTCOMES},
        )
    }


@dataclass(frozen=True)
class Diagnosis:
    """What Python decided for one build: ``outcome`` is the gold-comparable label when the
    gate accepted the answer (one of ``OUTCOMES``, ``unknown`` included), or ``"review"`` when
    the gate rejected it; ``workflow`` is the table entry for an accepted answer, or ``None``."""

    build_id: str
    outcome: str
    workflow: str | None
    reason: str


def classify(
    build_id: str,
    answer: Any,
    min_confidence: float,
    *,
    actions: ActionLog,
    queue: ReviewQueue,
) -> Diagnosis:
    """Decide what happens with one classified CI failure.

    Every option goes through the same confidence gate first, whatever it is: an answer below
    ``min_confidence`` is sent to ``queue`` with ``"confidence below the threshold"``, and that
    is the only condition under which this happens. An answer at or above the gate is accepted;
    what Python then does with it depends only on the workflow the table names for it, not on a
    second gate. The three substantive outcomes name an automated remedy, logged to ``actions``.
    ``unknown``'s workflow, manual triage, names no automated remedy, so an accepted ``unknown``
    answer is logged to ``queue`` instead -- accepted, not rejected for low confidence, but
    still a human's decision to make rather than an action Python proposes on its own.

    "Accepted" here means exactly ``answer.confidence >= min_confidence``: nothing else about
    the answer changes whether the gate lets it through, which is why this rule's own
    accept/review split is reported with ``jev_cookbook.evaluation.evaluate_selective`` rather
    than reimplemented.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.confidence < min_confidence:
        queue.submit(
            {"build": build_id, "choice": answer.choice},
            "confidence below the threshold",
            answer=answer,
        )
        return Diagnosis(build_id, REVIEW, None, "confidence below the threshold")
    # Every question option is a key of WORKFLOWS (OUTCOMES and WORKFLOWS are built from the
    # same names), and the backend already rejects an answer whose choice is outside the
    # question's own options before this rule ever sees it (docs/backends.md): indexing
    # directly relies on that guarantee rather than re-checking it, as backends.md documents as
    # an equally acceptable alternative to a defensive membership branch.
    workflow = WORKFLOWS[answer.choice]
    if answer.choice == UNKNOWN:
        queue.submit(
            {"build": build_id, "choice": answer.choice, "workflow": workflow},
            "no option fits",
            answer=answer,
        )
        return Diagnosis(build_id, UNKNOWN, workflow, "no option fits")
    actions.record(workflow, {"build": build_id}, answer=answer, rule="confident match")
    return Diagnosis(build_id, answer.choice, workflow, "confident match")
