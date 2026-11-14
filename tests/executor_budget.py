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
``timeout-minutes`` (15, 900 s); the rest of the suite takes about 275 s on Python 3.14, so
``SUITE_SECONDS`` reserves 300 of the 900 and no guard here may exceed what is left, 600 s; the
largest (525) leaves 75 s. ``test_every_hang_guard_fits_in_the_ci_test_job`` in
tests/test_new_recipe.py checks this against the file, not a copy of the number.

This is a plain module (not a test file), loaded by path like the other helpers in tests/.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
CI_TEST_JOB = "test"

SLOW_START = "Kernel didn't respond"
QUICK_START = "Kernel died before replying"

WARM_UP_SECONDS = 30
QUICK_START_SECONDS = 15
SLACK_SECONDS = 30
SUITE_SECONDS = 300

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
    job = ci_test_job_seconds() if job_seconds is None else job_seconds
    return guard + SUITE_SECONDS <= job


def every_guard(executor) -> dict[str, int]:
    """Every hang guard that follows from ``executor``, by the user it is for."""
    return {
        "tests/test_new_recipe.py": hang_guard(executor, NO_CELLS),
        "tests/test_notebook_ci_netguard.py": hang_guard(executor, NETGUARD_CELLS),
        "tests/test_notebook_ci_fresh.py": hang_guard(executor, TEMPLATE_CELLS),
    }
