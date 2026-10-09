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
        "under test."
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

# What Python does next for each outcome, keyed by outcome exactly as the build notes ask for.
# The three substantive outcomes name an automated remedy that a real system would act on
# (rerun the suite, pin and rebuild dependencies, requeue on a fresh runner), so Python only
# logs one of them as chosen (via `ActionLog`, which never executes anything) when the answer
# is both confident and a workflow Python recognises; UNKNOWN's workflow, manual triage, commits
# to no automated remedy at all, so delivering it needs no confidence gate (CONTRIBUTING.md,
# section 4: a low-confidence fallback option may be a final result when choosing it has no
# side effect).
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
DEPENDENCY_RE = re.compile(
    r"ModuleNotFoundError"
    r"|ImportError: cannot import"
    r"|No matching distribution found"
    r"|Could not find a version that satisfies"
    r"|ERESOLVE"
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
    this trimming does instead. When nothing matches (a flaky or inconclusive log), the excerpt
    is the first ``max_lines`` lines, so the reader still sees where the log starts.
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
    """What Python decided for one build: an outcome and, when one applies, the simulated
    next diagnostic workflow Python chose to log."""

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

    ``unknown`` is delivered as a final result with no confidence gate at all: Python's own
    ``WORKFLOWS`` table sends it straight to ``manual_triage``, which is logged in ``actions``
    like every other workflow but commits to no automated remedy, so there is nothing left for
    a confidence gate to protect (CONTRIBUTING.md, section 4). Every other option names an
    automated remedy, which Python is only willing to log as chosen when the answer names a
    workflow it recognises *and* is confident enough; anything else, including an answer naming
    an option this rule does not have a workflow for, goes to ``queue`` with the reason recorded
    instead, and no workflow is logged.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == UNKNOWN:
        workflow = WORKFLOWS[UNKNOWN]
        actions.record(workflow, {"build": build_id}, answer=answer, rule="no option fits")
        return Diagnosis(build_id, UNKNOWN, workflow, "no option fits")
    if answer.choice not in WORKFLOWS:
        # Defensive, not required: the backend already rejects an answer whose choice is
        # outside the question's own options before this rule ever sees it (docs/backends.md).
        # Kept anyway, with its own reason, because naming the boundary is worth the branch.
        queue.submit(
            {"build": build_id, "choice": answer.choice},
            "not a workflow Python may use",
            answer=answer,
        )
        return Diagnosis(build_id, REVIEW, None, "not a workflow Python may use")
    if answer.confidence < min_confidence:
        queue.submit(
            {"build": build_id, "choice": answer.choice},
            "confidence below the threshold",
            answer=answer,
        )
        return Diagnosis(build_id, REVIEW, None, "confidence below the threshold")
    workflow = WORKFLOWS[answer.choice]
    actions.record(workflow, {"build": build_id}, answer=answer, rule="confident match")
    return Diagnosis(build_id, answer.choice, workflow, "confident match")
