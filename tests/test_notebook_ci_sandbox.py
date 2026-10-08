"""``tools/execute_notebook.py``'s defence against a detached process winning the write race.

#108 fix round 5, M1: a PID namespace (``unshare --pid --fork --mount-proc``, in
``.github/workflows/notebooks.yml``) guarantees that nothing survives PID 1 of that namespace
*exiting*, but it does not guarantee that the executor's own write of the result is the *last*
write before that exit -- the gap between the write and the process actually terminating (kernel
teardown already happened, but Python's own interpreter shutdown is not instant) is real, and a
cell can start a detached (``setsid``) process that keeps running in it. A 5 ms rewrite loop
reproducibly won that gap in CI (see the pull request's throwaway-PR proof) even with the PID
namespace in place. ``kill_everyone_else_in_my_pid_namespace`` closes it from inside the executor
itself: immediately before writing, it kills and waits out every other non-zombie process in its
own PID namespace, so nothing capable of writing anything is left alive when the write happens.

These are unit tests of that helper in isolation (``os.listdir``, ``os.kill``, ``time.sleep``,
``os.readlink`` and ``process_state`` are monkeypatched): they do not require root, a PID namespace
or `unshare`, none of which this machine may have (the one exception is
``test_process_state_of_self_is_a_recognisable_running_state``, which reads this process's own
``/proc/self/stat`` for real and is skipped where ``/proc`` does not exist). The real mechanism is
proved end to end on GitHub, as the pull request's fix-round section records.

#108 fix round 6, A6 M1 / B6 M1: two things changed here. ``process_state`` reads real procfs and
every test but one of its own callers was already fully monkeypatched; the one that was not
(``test_process_state_of_self_is_a_recognisable_running_state``) fails on Windows and macOS, which
have none -- it is now the only test in this file marked ``skipif``. And
``kill_everyone_else_in_my_pid_namespace``'s activation -- previously ``os.getpid() == 1`` alone --
is now also proved against ``/proc/self`` (``in_an_isolated_pid_namespace``, A6 suggestion S1 / B6
suggestion 2), and ``require_pid_namespace_if_demanded`` turns that detection into a hard
requirement when ``JEV_COOKBOOK_REQUIRE_PID_NAMESPACE`` is set, which is what the sandboxed execute
step in ``notebooks.yml`` now does (see ``tests/test_notebook_ci_workflows.py``).
"""

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

NO_PROCFS = not Path("/proc/self/stat").exists()

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "execute_notebook.py"

spec = importlib.util.spec_from_file_location("execute_notebook_for_test", TOOL)
execute_notebook = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = execute_notebook
spec.loader.exec_module(execute_notebook)


def test_is_a_noop_outside_a_pid_namespace(monkeypatch):
    """``os.getpid() == 1`` is true only when this process is PID 1 of an isolated PID namespace
    (never in a test process, never in a plain local run); anything else must touch nothing. PID
    is not 1, so ``in_an_isolated_pid_namespace`` short-circuits before reading ``/proc/self``."""
    monkeypatch.setattr(os, "getpid", lambda: 12345)

    def boom(*_a, **_k):
        raise AssertionError("must not inspect /proc when not PID 1")

    monkeypatch.setattr(os, "listdir", boom)
    monkeypatch.setattr(os, "kill", boom)
    execute_notebook.kill_everyone_else_in_my_pid_namespace()  # must not raise


def test_in_an_isolated_pid_namespace_requires_getpid_1(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 12345)
    assert execute_notebook.in_an_isolated_pid_namespace() is False


def test_in_an_isolated_pid_namespace_requires_proc_self_to_agree(monkeypatch):
    """#108 fix round 6, A6 suggestion S1 / B6 suggestion 2: ``os.getpid() == 1`` alone is not
    proof -- it also holds for PID 1 of a container, or inside ``unshare --pid --fork`` run
    *without* ``--mount-proc``, where ``/proc`` is still the host's (measured in review:
    ``/proc/self`` resolved to the real host PID while ``os.getpid()`` said 1)."""
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr(os, "readlink", lambda _p: "386042")
    assert execute_notebook.in_an_isolated_pid_namespace() is False


def test_in_an_isolated_pid_namespace_true_when_both_agree(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr(os, "readlink", lambda _p: "1")
    assert execute_notebook.in_an_isolated_pid_namespace() is True


def test_require_pid_namespace_is_a_noop_when_not_demanded(monkeypatch):
    """Unset -- a local run, every other test in this file, the ``Tests`` jobs -- this must touch
    nothing, exactly like the kill helper itself."""
    monkeypatch.delenv(execute_notebook.PID_NAMESPACE_REQUIRED_ENV, raising=False)
    monkeypatch.setattr(os, "getpid", lambda: 12345)

    def boom(*_a, **_k):
        raise AssertionError("must not even check the PID when not demanded")

    monkeypatch.setattr(os, "readlink", boom)
    execute_notebook.require_pid_namespace_if_demanded()  # must not raise


def test_require_pid_namespace_raises_when_demanded_and_not_active(monkeypatch, capsys):
    """#108 fix round 6, B6 M1: the scenario that defeated the kill helper silently -- wrapping the
    execute step's command in something that forks rather than `exec`s (``timeout 600``, say)
    leaves ``python`` at PID 2, not PID 1."""
    monkeypatch.setenv(execute_notebook.PID_NAMESPACE_REQUIRED_ENV, "1")
    monkeypatch.setattr(os, "getpid", lambda: 2)
    with pytest.raises(execute_notebook.PidNamespaceNotActive, match="refusing to write"):
        execute_notebook.require_pid_namespace_if_demanded()
    assert "pid namespace: active" not in capsys.readouterr().out


def test_require_pid_namespace_prints_the_line_the_workflow_greps_for(monkeypatch, capsys):
    monkeypatch.setenv(execute_notebook.PID_NAMESPACE_REQUIRED_ENV, "1")
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr(os, "readlink", lambda _p: "1")
    execute_notebook.require_pid_namespace_if_demanded()
    assert capsys.readouterr().out.strip() == "pid namespace: active"


@pytest.mark.skipif(NO_PROCFS, reason="reads this process's own real /proc/self/stat")
def test_process_state_of_self_is_a_recognisable_running_state():
    assert execute_notebook.process_state(os.getpid()) in ("R", "S", "D", "T", "I")


def test_process_state_of_a_nonexistent_pid_is_none():
    assert execute_notebook.process_state(2**30) is None


def test_process_state_splits_on_the_last_close_paren(monkeypatch):
    # The command-name field is parenthesised and may itself contain ")" (a process can name
    # itself almost anything via argv[0] or prctl); splitting on the first ")" would misparse it.
    class FakeStat:
        def read_text(self):
            return "123 (weird)name)) S 1 1 1 0 -1 ...\n"

    monkeypatch.setattr(execute_notebook, "Path", lambda _p: FakeStat())
    assert execute_notebook.process_state(123) == "S"


def test_kills_every_non_zombie_process_and_returns_once_none_remain(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr(os, "readlink", lambda _p: "1")
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    calls = {"listdir": 0}

    def fake_listdir(_path):
        calls["listdir"] += 1
        # First pass: two real processes (one running, one sleeping) and a zombie that must be
        # ignored. Second pass: both real ones are gone (killed), proving the loop re-checks.
        return ["2", "3", "4"] if calls["listdir"] == 1 else []

    states = {2: "R", 3: "S", 4: "Z"}
    killed = []
    monkeypatch.setattr(os, "listdir", fake_listdir)
    monkeypatch.setattr(execute_notebook, "process_state", lambda pid: states.get(pid))
    monkeypatch.setattr(os, "kill", lambda pid, _sig: killed.append(pid))

    execute_notebook.kill_everyone_else_in_my_pid_namespace()

    assert sorted(killed) == [2, 3]  # the zombie (4) was never signalled
    assert calls["listdir"] == 2  # it re-checked after killing, rather than trusting the kill


def test_pid_1_itself_is_never_a_candidate(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr(os, "readlink", lambda _p: "1")
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    monkeypatch.setattr(os, "listdir", lambda _p: ["1"])
    monkeypatch.setattr(execute_notebook, "process_state", lambda _pid: "R")

    def boom(*_a, **_k):
        raise AssertionError("must never signal its own PID 1")

    monkeypatch.setattr(os, "kill", boom)
    execute_notebook.kill_everyone_else_in_my_pid_namespace()  # must not raise, must not kill


def test_a_process_that_will_not_die_fails_closed(monkeypatch):
    """If something keeps respawning or ignoring SIGKILL (which SIGKILL cannot itself be blocked
    from, but the test exercises the timeout path regardless of why), the helper must raise rather
    than let the caller write an unverified result."""
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr(os, "readlink", lambda _p: "1")
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    monkeypatch.setattr(os, "listdir", lambda _p: ["7"])
    monkeypatch.setattr(execute_notebook, "process_state", lambda _pid: "R")
    monkeypatch.setattr(os, "kill", lambda _pid, _sig: None)

    with pytest.raises(RuntimeError, match="would not die"):
        execute_notebook.kill_everyone_else_in_my_pid_namespace(timeout=0.03)


def test_execute_calls_the_guard_before_writing(monkeypatch, tmp_path):
    """Pins the ordering in ``execute()`` itself: the guard must run after validation and before
    the file write, not merely exist somewhere in the module. ``require_pid_namespace_if_demanded``
    is left real, not mocked: with the variable unset (as here) it is a no-op and adds nothing to
    ``order``, exactly as it must on every local run and in the ``Tests`` jobs."""
    import nbformat

    monkeypatch.delenv(execute_notebook.PID_NAMESPACE_REQUIRED_ENV, raising=False)
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell("1 + 1")]
    notebook_path = recipe_dir / execute_notebook.NOTEBOOK
    nbformat.write(nb, notebook_path)

    order = []
    monkeypatch.setattr(
        execute_notebook,
        "run_in_fresh_kernel",
        lambda nb, recipe_dir, timeout: order.append("run"),
    )
    monkeypatch.setattr(execute_notebook, "check_no_stderr", lambda nb: order.append("check"))
    monkeypatch.setattr(
        execute_notebook,
        "kill_everyone_else_in_my_pid_namespace",
        lambda: order.append("kill"),
    )
    real_write_text = Path.write_text

    def spy_write_text(self, *a, **k):
        order.append("write")
        return real_write_text(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", spy_write_text)

    execute_notebook.execute(recipe_dir)

    assert order == ["run", "check", "kill", "write"]


def test_execute_itself_raises_and_leaves_the_file_unwritten_when_the_namespace_is_demanded_and_absent(
    monkeypatch, tmp_path
):
    """#108 fix round 7, B8 M2: nothing pinned that ``execute()`` actually calls
    ``require_pid_namespace_if_demanded()`` -- deleting that one line from ``execute()`` left
    every existing test green. ``test_execute_calls_the_guard_before_writing`` above deliberately
    leaves ``JEV_COOKBOOK_REQUIRE_PID_NAMESPACE`` unset, so the call (if present at all) is a
    no-op and invisible to its ``order`` list either way; the dedicated unit tests for the guard
    (``test_require_pid_namespace_raises_when_demanded_and_not_active`` and its neighbours) call
    ``require_pid_namespace_if_demanded`` directly, never through ``execute()``. This test instead
    drives the real ``execute()`` call path with the demand set and the namespace absent
    (``os.getpid`` patched off 1, so ``in_an_isolated_pid_namespace()`` is genuinely ``False``,
    not mocked away): if the call in ``execute()`` is ever deleted, ``execute()`` instead reaches
    ``kill_everyone_else_in_my_pid_namespace`` (itself a no-op outside a namespace) and writes the
    file, so this test would see no raise and a changed file instead of the required one."""
    import nbformat

    monkeypatch.setenv(execute_notebook.PID_NAMESPACE_REQUIRED_ENV, "1")
    monkeypatch.setattr(os, "getpid", lambda: 12345)  # not PID 1: not an isolated namespace
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell("1 + 1")]
    notebook_path = recipe_dir / execute_notebook.NOTEBOOK
    nbformat.write(nb, notebook_path)
    before = notebook_path.read_bytes()

    monkeypatch.setattr(
        execute_notebook, "run_in_fresh_kernel", lambda nb, recipe_dir, timeout: None
    )
    monkeypatch.setattr(execute_notebook, "check_no_stderr", lambda nb: None)

    with pytest.raises(execute_notebook.PidNamespaceNotActive, match="refusing to write"):
        execute_notebook.execute(recipe_dir)

    assert notebook_path.read_bytes() == before, (
        "the file must be left exactly as it was when the namespace is demanded and absent"
    )
