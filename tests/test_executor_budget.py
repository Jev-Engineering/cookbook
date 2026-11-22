"""The CI-fit message of tests/executor_budget.py names the numbers to update (#347)."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from .module_loader import load_module_at

EXECUTE_NOTEBOOK = Path(__file__).resolve().parent.parent / "tools" / "execute_notebook.py"


def read_constants(path: Path, names: tuple[str, ...]) -> SimpleNamespace:
    """The literal values of the module-level assignments ``names`` in ``path``, read from its
    source without executing it. Raises ``ValueError`` for a name that is not assigned at module
    level or whose value is not a literal; the last module-level assignment of a name wins, as it
    would when the module runs."""
    found: dict[str, object] = {}
    for node in ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in names:
                try:
                    found[target.id] = ast.literal_eval(value)
                except ValueError as error:
                    raise ValueError(f"{target.id} in {path} is not a literal: {error}") from error
    missing = [name for name in names if name not in found]
    if missing:
        raise ValueError(f"{', '.join(missing)} not assigned at module level in {path}")
    return SimpleNamespace(**found)


# START_WAIT and START_ATTEMPTS are all hang_guard needs; reading them as literals avoids running
# the whole of tools/execute_notebook.py (its imports and module-level setup) for two numbers.
execute_notebook = read_constants(EXECUTE_NOTEBOOK, ("START_WAIT", "START_ATTEMPTS"))
executor_budget = load_module_at(
    Path(__file__).with_name("executor_budget.py"), "executor_budget_for_message"
)


def test_the_fit_message_names_the_reserve_and_the_job_timeout_to_update():
    message = executor_budget.fit_problem("tests/x.py", 900, job_seconds=1200)
    assert "tests/x.py" in message
    assert f"SUITE_SECONDS {executor_budget.SUITE_SECONDS} s" in message
    assert "update MEASURED_JOB_SECONDS and SUITE_SECONDS together" in message
    assert f"{900 + executor_budget.SUITE_SECONDS} s exceeds" in message
    assert "(1200 s)" in message
    assert "tests/executor_budget.py" in message and ".github/workflows/ci.yml" in message


def test_the_reserve_covers_the_recorded_measurement_constant():
    # MEASURED_JOB_SECONDS: the longest of the green Tests jobs measured for #347 (see the module
    # docstring); a reserve below the measurement would let the largest guard fire after the job
    # is killed.
    measured = executor_budget.MEASURED_JOB_SECONDS
    assert executor_budget.SUITE_SECONDS >= measured
    doc = " ".join(executor_budget.__doc__.split())
    assert f" to {measured} s (``MEASURED_JOB_SECONDS``)" in doc


def test_the_reserve_and_the_largest_guard_fit_the_job_as_read_from_ci_yml():
    job = executor_budget.ci_test_job_seconds()
    largest = max(executor_budget.every_guard(execute_notebook).values())
    assert executor_budget.fits_in_the_ci_test_job(largest, job)
    # both sides of the boundary: a guard that uses exactly what is left fits, one more second not
    room = job - executor_budget.SUITE_SECONDS
    assert executor_budget.fits_in_the_ci_test_job(room, job)
    assert not executor_budget.fits_in_the_ci_test_job(room + 1, job)
    assert executor_budget.fit_problem("tests/x.py", room, job) is None
    assert executor_budget.fit_problem("tests/x.py", room + 1, job) is not None


def test_fit_checks_read_the_job_only_when_no_budget_is_supplied(monkeypatch):
    calls = []

    def job_seconds():
        calls.append(None)
        return executor_budget.SUITE_SECONDS + 10

    monkeypatch.setattr(executor_budget, "ci_test_job_seconds", job_seconds)
    assert executor_budget.fits_in_the_ci_test_job(10)
    assert executor_budget.fit_problem("tests/x.py", 11) is not None
    assert len(calls) == 2
    assert executor_budget.fits_in_the_ci_test_job(10, executor_budget.SUITE_SECONDS + 10)
    assert executor_budget.fit_problem("tests/x.py", 11, executor_budget.SUITE_SECONDS + 10)
    assert len(calls) == 2


def test_the_fit_message_uses_the_current_module_and_workflow_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_budget, "REPO", tmp_path)
    monkeypatch.setattr(executor_budget, "__file__", str(tmp_path / "checks" / "reserve.py"))
    monkeypatch.setattr(executor_budget, "CI_WORKFLOW", tmp_path / "workflows" / "checks.yml")
    monkeypatch.setattr(executor_budget, "EXECUTOR_TOOL", tmp_path / "tools" / "runner.py")
    message = executor_budget.fit_problem("tests/x.py", 900, job_seconds=1200)
    assert "checks/reserve.py" in message
    assert "workflows/checks.yml" in message
    assert "tools/runner.py" in message
    assert "tests/executor_budget.py" not in message
    assert ".github/workflows/ci.yml" not in message


def test_the_docstring_figures_are_the_ones_the_numbers_give():
    # every figure the module docstring derives is recomputed here, so changing the reserve, the
    # job timeout or a guard without updating the prose fails
    doc = " ".join(executor_budget.__doc__.split())
    job = executor_budget.ci_test_job_seconds()
    reserve = executor_budget.SUITE_SECONDS
    largest = max(executor_budget.every_guard(execute_notebook).values())
    margin = round((reserve / executor_budget.MEASURED_JOB_SECONDS - 1) * 100)
    assert f"plus about {margin}%, {reserve} s" in doc
    assert f"({job // 60}, {job} s)" in doc
    assert f"what is left, {job - reserve} s" in doc
    assert f"the largest ({largest}) leaves {job - reserve - largest} s" in doc


def test_the_constant_reader_refuses_a_missing_or_non_literal_constant(tmp_path):
    source = tmp_path / "tool.py"
    source.write_text("START_WAIT = 180\nSTART_ATTEMPTS = {'a': 2}\n", encoding="utf-8")
    read = read_constants(source, ("START_WAIT", "START_ATTEMPTS"))
    assert (read.START_WAIT, read.START_ATTEMPTS) == (180, {"a": 2})
    source.write_text("START_WAIT = 180\n", encoding="utf-8")
    with pytest.raises(ValueError, match="START_ATTEMPTS not assigned"):
        read_constants(source, ("START_WAIT", "START_ATTEMPTS"))
    source.write_text("def f():\n    START_WAIT = 1\nSTART_ATTEMPTS = {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="START_WAIT not assigned"):
        read_constants(source, ("START_WAIT", "START_ATTEMPTS"))
    source.write_text("START_WAIT = 90 + 90\nSTART_ATTEMPTS = {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="START_WAIT .* is not a literal"):
        read_constants(source, ("START_WAIT", "START_ATTEMPTS"))
    source.write_text("START_WAIT = 1\nSTART_ATTEMPTS = dict(a=2)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="START_ATTEMPTS .* is not a literal"):
        read_constants(source, ("START_WAIT", "START_ATTEMPTS"))


def test_the_constants_read_from_the_tool_are_the_ones_it_runs_with():
    assert execute_notebook.START_WAIT == 180
    assert set(execute_notebook.START_ATTEMPTS) == {
        executor_budget.SLOW_START,
        executor_budget.QUICK_START,
    }
