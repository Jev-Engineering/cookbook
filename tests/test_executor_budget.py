"""The CI-fit message of tests/executor_budget.py names the numbers to update (#347)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "executor_budget_for_message", Path(__file__).with_name("executor_budget.py")
)
executor_budget = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = executor_budget
_spec.loader.exec_module(executor_budget)


def test_the_fit_message_names_the_reserve_and_the_job_timeout_to_update():
    message = executor_budget.fit_problem("tests/x.py", 900, job_seconds=1200)
    assert "tests/x.py" in message
    assert f"SUITE_SECONDS {executor_budget.SUITE_SECONDS} s" in message
    assert f"{900 + executor_budget.SUITE_SECONDS} s exceeds" in message
    assert "(1200 s)" in message
    assert "tests/executor_budget.py" in message and ".github/workflows/ci.yml" in message


def test_the_reserve_is_at_least_the_largest_measured_tests_job():
    # 408 s: the longest of 16 green Tests jobs measured for #347 (see the module docstring); a
    # reserve below the measurement would let the largest guard fire after the job is killed.
    assert executor_budget.SUITE_SECONDS >= 408
    assert "282 to 408 s" in executor_budget.__doc__


def test_the_reserve_and_the_largest_guard_fit_the_job_as_read_from_ci_yml():
    job = executor_budget.ci_test_job_seconds()
    assert executor_budget.fits_in_the_ci_test_job(525, job)
    assert not executor_budget.fits_in_the_ci_test_job(job - executor_budget.SUITE_SECONDS + 1, job)
