"""How long a test may wait for tools/execute_notebook.py in a subprocess (#328, #117).

A test that runs the tool in a subprocess gives ``subprocess.run`` a ``timeout`` so that a hang is
a named test failure, with the tool's output attached, not a stalled suite. That timeout has to be
longer than anything the tool may legitimately do, or a slow start on a busy machine fails the
test with ``TimeoutExpired`` whatever it asserts (the fixed 90, 180 and 240 seconds this replaces
were all shorter than one 180 second start wait), and shorter than the CI job that runs the suite,
or the job is killed first and the failure is not named at all.

The arithmetic, for a run that has nothing wrong with its notebook (seconds):

    font-cache warm-up      30   a cold build takes about one; the tool's own cap, WARM_TIMEOUT
                                 (300), is a hang, not an expectation
    silent kernel          360   START_WAIT (180) x 2 starts, the slow failure
    quick-exit kernels      60   15 x 4 starts; a kernel that exits before replying costs about
                                 2 (measured), so this is generous for the three that can fail
    the cell(s)           0-45   what the notebook itself is given, per user
    slack                   30
    ----------------------------------------------------------------------------------------
    total             480-525

The job running the suite (``.github/workflows/ci.yml``, ``test``) is killed at its
``timeout-minutes`` (20, 1200 s). ``SUITE_SECONDS`` is the room reserved for everything else in
that job, set from a measurement: on 20 green ``Tests`` jobs (both Python versions, the 10 latest
completed ``ci.yml`` runs of ``main``, 2026-11-14 to 2026-11-17: 44113766564, 43548719512,
43547789988, 43546902789, 43546036249, 43545101814, 43544155609, 43543486345, 43541850720,
43535601674), the whole job, set-up and install included, took 276 to 463 s
(``MEASURED_JOB_SECONDS``). The reserve is that maximum plus about 21%, 560 s, so no guard here may
exceed what is left, 640 s; the largest (525) leaves 115 s. When the suite grows past the reserve,
raise ``MEASURED_JOB_SECONDS`` and ``SUITE_SECONDS`` from a new measurement and, if a guard then no
longer fits, the job's ``timeout-minutes``: never shorten a guard below what the tool may
legitimately take.
``test_every_hang_guard_fits_in_the_ci_test_job`` in tests/test_new_recipe.py checks this against
the file, not a copy of the number, and its failure message (``fit_problem``) names both numbers.
This models one guard firing in a job, with the rest of the suite covered by the reserve. It
does not guarantee that the job survives multiple guarded subprocesses hanging in the same run;
the three users share the kernel start path. The constant checks below do not measure current
suite duration: re-measure when the suite grows.

This is a plain module (not a test file), loaded by path like the other helpers in tests/.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
EXECUTOR_TOOL = REPO / "tools" / "execute_notebook.py"
CI_TEST_JOB = "test"

SLOW_START = "Kernel didn't respond"
QUICK_START = "Kernel died before replying"

WARM_UP_SECONDS = 30
QUICK_START_SECONDS = 15
SLACK_SECONDS = 30
MEASURED_JOB_SECONDS = 463  # longest of the 20 Tests jobs measured above (run 44113766564, py3.10)
SUITE_SECONDS = 560  # MEASURED_JOB_SECONDS 463 s, plus about 21%

# What the notebooks the three users run need for their cells, on top of the start-up.
NO_CELLS = 0  # tests/test_new_recipe.py: a dead kernel, a cell that loops for 3 seconds
NETGUARD_CELLS = 30  # tests/test_notebook_ci_netguard.py: cells that try (and fail) the network
TEMPLATE_CELLS = 45  # tests/test_notebook_ci_fresh.py: the whole template notebook (about 5)


def hang_guard(executor, cell_seconds: int = NO_CELLS) -> int:
    """The ``timeout`` for running ``executor`` (the loaded tools/execute_notebook.py module) in a
    subprocess on a notebook whose cells need up to ``cell_seconds``."""
    silent = executor.START_WAIT * executor.START_ATTEMPTS[SLOW_START]
    quick = QUICK_START_SECONDS * executor.START_ATTEMPTS[QUICK_START]
    return WARM_UP_SECONDS + silent + quick + cell_seconds + SLACK_SECONDS


def ci_test_job_seconds(workflow: Path = CI_WORKFLOW) -> int:
    """``timeout-minutes`` of the job that runs the suite, in seconds, read from ci.yml."""
    text = workflow.read_text(encoding="utf-8")
    job = re.search(rf"^  {CI_TEST_JOB}:\n(.*?)(?=^  \S|\Z)", text, re.DOTALL | re.MULTILINE)
    if job is None:
        raise ValueError(f"no job {CI_TEST_JOB!r} in {workflow}")
    minutes = re.search(r"^    timeout-minutes:\s*(\d+)\s*$", job.group(1), re.MULTILINE)
    if minutes is None:
        raise ValueError(f"job {CI_TEST_JOB!r} in {workflow} has no timeout-minutes")
    return int(minutes.group(1)) * 60


def fits_in_the_ci_test_job(guard: int, job_seconds: int | None = None) -> bool:
    """Whether a hang guard of ``guard`` seconds can fire before the job is killed, given that the
    rest of the suite (``SUITE_SECONDS``) has run in the same job."""
    return fit_problem("", guard, job_seconds) is None


def fit_problem(user: str, guard: int, job_seconds: int | None = None) -> str | None:
    """None if the guard fits; otherwise the failure message, naming the numbers to update."""
    job = ci_test_job_seconds() if job_seconds is None else job_seconds
    total = guard + SUITE_SECONDS
    if total <= job:
        return None
    budget_path = Path(__file__).resolve().relative_to(REPO).as_posix()
    workflow_path = CI_WORKFLOW.relative_to(REPO).as_posix()
    executor_path = EXECUTOR_TOOL.relative_to(REPO).as_posix()
    return (
        f"{user}: hang guard {guard} s + SUITE_SECONDS {SUITE_SECONDS} s = "
        f"{total} s exceeds the CI {CI_TEST_JOB!r} job's timeout-minutes "
        f"({job} s). Re-measure the Tests job duration and update MEASURED_JOB_SECONDS and "
        f"SUITE_SECONDS together (and the measurement in the module docstring) in "
        f"{budget_path}, or raise timeout-minutes in {workflow_path}; do not "
        f"shorten the guard below what {executor_path} may legitimately take."
    )


def every_guard(executor) -> dict[str, int]:
    """Every hang guard that follows from ``executor``, by the user it is for."""
    return {
        "tests/test_new_recipe.py": hang_guard(executor, NO_CELLS),
        "tests/test_notebook_ci_netguard.py": hang_guard(executor, NETGUARD_CELLS),
        "tests/test_notebook_ci_fresh.py": hang_guard(executor, TEMPLATE_CELLS),
    }
