"""Execute a recipe's notebook in place, offline, with the recipe folder as working directory.

    python tools/execute_notebook.py recipes/NN-slug

It runs ``notebook.ipynb`` in a fresh kernel and writes the outputs back to the same file.
These things are fixed so that running it twice gives the same file:

* the kernel's environment has no ``JEV_COOKBOOK_*`` and no ``TYPESAFE_*`` variable, so the
  run is offline and replays the fixtures whatever the shell had set. The environment is built
  as a copy and passed to the kernel; this process's own environment is never changed, so
  several notebooks can be executed in parallel (on Windows, starting several kernels at the same
  time can fail with a ZMQ "Address in use" error, which the tool absorbs by starting a fresh kernel
  once more, see below);
* the kernel is the interpreter running this tool (``sys.executable``), not whichever
  ``python3`` kernelspec Jupyter finds first, so a user-level kernelspec cannot swap the
  environment the committed outputs were made in;
* stream output is coalesced (``coalesce_streams``), so a printed line is never split into two
  stream outputs by an IOPub flush that lands between its text and its newline;
* execution timings are not recorded;
* the notebook metadata is reset to the Python version independent minimum (kernel name and
  language ``python``), so the file does not change with the interpreter that ran it;
* the kernel application's own log level is raised (``--Application.log_level=ERROR``), so
  ipykernel's unconditional startup notice about its TCP transport cannot be captured as a cell's
  stderr output under #69's CI sandbox and rejected as if a cell had printed it;
* when this process is PID 1 of an isolated PID namespace (CI's sandbox wraps it in one so that
  nothing a cell starts can outlive it), every other process still alive in that namespace is
  killed, and confirmed dead, immediately before the result is written
  (``kill_everyone_else_in_my_pid_namespace``) -- a cell can start a detached process that survives
  the kernel's own shutdown and keeps running during this process's, so the write is not the last
  word on the file's contents unless nothing else can still act on it when it happens. Whether
  that guard is active is inferred (``os.getpid() == 1``, confirmed against ``/proc/self`` too --
  see ``in_an_isolated_pid_namespace``); it is silent and a no-op when it is not, so a later change
  that stops this process landing on PID 1 would disable it without failing anything. Setting
  ``JEV_COOKBOOK_REQUIRE_PID_NAMESPACE`` in the environment (CI's sandboxed execute step does this)
  turns that inference into a demand: ``require_pid_namespace_if_demanded`` raises, before anything
  is written, if the namespace is not actually active, and otherwise prints "pid namespace:
  active", which the workflow step greps for (#108 fix round 6, B6 M1).

A run in which any cell wrote to stderr also fails: stderr carries warnings and absolute paths,
which must not be committed.

Exit status is 0 when the notebook ran to the end, 1 when a cell failed, a cell ran longer than
the timeout (``--timeout``, default 300 seconds, at least 1), the kernel died or never started, a
cell wrote to stderr (one line on stderr, the file left unchanged), or
``JEV_COOKBOOK_REQUIRE_PID_NAMESPACE`` was set and the PID namespace it demands was not active, and
2 for a usage error. #69 builds CI (network guard, staleness check) on this.

Starting the kernel is retried once, and only that: when the machine is loaded (several notebooks
executing at once) a kernel can lose a race for a TCP port ("Address in use"), exit before it
replies, or take longer than jupyter_client's default 60 seconds to answer. Each of those is a
``RuntimeError`` raised before any cell has run, so a second attempt with a fresh kernel cannot hide
a failing cell; a cell that fails, times out or kills the kernel is never retried. The wait for the
kernel to answer is ``START_WAIT`` seconds (not ``--timeout``, which is per cell), so a kernel that
never starts fails after at most two such waits (2 x ``START_WAIT``, 360 seconds).

Known limitation: "the kernel never started" is recognised by two jupyter_client messages
("Kernel didn't respond", "Kernel died before replying"). Any other start-up ``RuntimeError`` is
printed as a traceback; the exit status (1) and the unchanged file are the same.
"""

from __future__ import annotations

import argparse
import atexit
import os
import signal
import sys
import time
from pathlib import Path

import nbformat
from ipykernel.kernelspec import get_kernel_dict
from jupyter_client.kernelspec import KernelSpec, KernelSpecManager
from jupyter_client.manager import AsyncKernelManager
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError, CellTimeoutError, DeadKernelError

NOTEBOOK = "notebook.ipynb"
KERNEL_NAME = "python3"
SCRUBBED_PREFIXES = ("JEV_COOKBOOK_", "TYPESAFE_")
TIMEOUT_SECONDS = 300
START_WAIT = 180
START_FAILURES = ("Kernel didn't respond", "Kernel died before replying")
METADATA = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": KERNEL_NAME},
    "language_info": {"name": "python"},
}


class RunningInterpreterSpecs(KernelSpecManager):
    """Kernelspecs where ``python3`` is always ``sys.executable`` running ipykernel."""

    def get_kernel_spec(self, kernel_name: str) -> KernelSpec:
        if kernel_name != KERNEL_NAME:
            return super().get_kernel_spec(kernel_name)
        return KernelSpec(**get_kernel_dict())


def offline_environment(environ: dict[str, str]) -> dict[str, str]:
    """A copy of ``environ`` without the live switch, its settings, and every TypeSafe variable
    (the API key, the base URL, anything else), matched case-insensitively."""
    return {k: v for k, v in environ.items() if not k.upper().startswith(SCRUBBED_PREFIXES)}


class KernelStartError(Exception):
    """The kernel did not start (nbclient reports it as a bare ``RuntimeError``)."""


class StderrOutput(Exception):
    """A cell wrote to stderr, which can carry absolute paths and so must not be committed."""


def check_no_stderr(nb: nbformat.NotebookNode) -> None:
    """Raise ``StderrOutput`` naming the first cell that produced stderr output."""
    for index, cell in enumerate(nb.cells):
        for output in cell.get("outputs", []):
            if output.get("output_type") == "stream" and output.get("name") == "stderr":
                raise StderrOutput(
                    f"cell {index} ({cell.get('id', 'no id')}) wrote to stderr; "
                    "fix its cause rather than hiding it"
                )


def run_in_fresh_kernel(nb: nbformat.NotebookNode, recipe_dir: Path, timeout: int) -> None:
    """Execute ``nb`` in a new kernel, in place. A kernel that does not start raises
    ``RuntimeError`` (see ``START_FAILURES``) before any cell runs."""
    # An async manager is needed for nbclient to notice a dead kernel (``os._exit``, a crash);
    # with a blocking one a dead kernel hangs the run and the cell timeout never applies.
    manager = AsyncKernelManager(
        kernel_name=KERNEL_NAME, kernel_spec_manager=RunningInterpreterSpecs()
    )
    client = NotebookClient(
        nb,
        km=manager,
        kernel_name=KERNEL_NAME,
        timeout=timeout,
        startup_timeout=START_WAIT,
        record_timing=False,
        coalesce_streams=True,
        # ipykernel's own startup unconditionally logs a WARNING ("Kernel is running over TCP
        # without encryption...") to the kernel process's stderr before the kernel redirects
        # stdout/stderr to the notebook's streams (ipykernel/kernelapp.py, init_sockets). Under the
        # extra process layers #69's CI sandbox wraps the kernel in (sudo, a network namespace,
        # setpriv), that one-line, non-actionable framework notice can land inside the first code
        # cell's own stderr output instead of the terminal, which check_no_stderr then (correctly,
        # by its own rule) treats as a run to reject. The warning is about a transport choice this
        # tool already offline and namespace-isolates; raising the kernel application's own log
        # level is the flag the sandboxed run needs so framework noise cannot be mistaken for a
        # cell's own output. A real startup failure still raises (KernelStartError, DeadKernelError)
        # rather than merely logging, so this cannot hide one.
        extra_arguments=["--Application.log_level=ERROR"],
        resources={"metadata": {"path": str(recipe_dir)}},
    )
    # ``env`` replaces the kernel's whole environment; this process's is left alone.
    try:
        client.execute(env=offline_environment(dict(os.environ)))
    except BaseException:
        # nbclient registers an exit-time kernel cleanup and, when the start fails, never removes
        # it; at interpreter exit it then raises an ``AssertionError`` (km is None) on stderr.
        # The kernel was already cleaned up when the error propagated, so drop the hook.
        atexit.unregister(client._cleanup_kernel)
        raise


def process_state(pid: int) -> str | None:
    """The single-character state field of ``/proc/<pid>/stat`` ('Z' for a zombie, which cannot
    run or write anything), or ``None`` if the process is already gone. The command-name field is
    parenthesised and may itself contain ``)``, so the split is on the *last* one.

    Procfs-only: on a platform with no ``/proc`` (Windows, macOS) every PID looks gone, since
    reading the path always raises ``FileNotFoundError``. That is the documented sentinel for
    "cannot tell" as well as "gone" -- harmless here, because the only caller
    (``kill_everyone_else_in_my_pid_namespace``) is itself unconditionally a no-op on those
    platforms (a Python process cannot be PID 1 of a namespace there), so this function's result
    is never acted on off Linux.
    """
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return None
    return text.rsplit(")", 1)[1].split()[0]


PID_NAMESPACE_REQUIRED_ENV = "JEV_COOKBOOK_REQUIRE_PID_NAMESPACE"


def in_an_isolated_pid_namespace() -> bool:
    """Whether this process is PID 1 of a dedicated PID namespace, confirmed two ways.

    ``os.getpid() == 1`` alone is not proof (#108 fix round 6, A6 suggestion S1 / B6 suggestion 2):
    it is also true for PID 1 of a container, and for ``unshare --pid --fork`` run *without*
    ``--mount-proc``, where this process is PID 1 of the new namespace but ``/proc`` is still a
    view of the *host's* processes (measured in review: ``/proc/self`` resolved to the real host
    PID while ``os.getpid()`` said 1). Requiring ``/proc/self`` to also resolve to ``"1"`` means
    the namespace's own procfs is actually mounted, which is what makes reading ``/proc`` below
    (in ``kill_everyone_else_in_my_pid_namespace``) mean anything at all.
    """
    if os.getpid() != 1:
        return False
    try:
        return os.readlink("/proc/self") == "1"
    except OSError:
        return False


class PidNamespaceNotActive(RuntimeError):
    """``JEV_COOKBOOK_REQUIRE_PID_NAMESPACE`` demanded an isolated PID namespace and this process
    is not PID 1 of one."""


def require_pid_namespace_if_demanded() -> None:
    """A no-op unless ``JEV_COOKBOOK_REQUIRE_PID_NAMESPACE`` is set in the environment.

    #108 fix round 6, B6 M1: ``kill_everyone_else_in_my_pid_namespace`` below only does anything
    when this process happens to be PID 1, which the sandboxed execute step arranges by `exec`-ing
    straight into ``python`` -- nothing asserted that at runtime, so a later edit that stops it
    (wrapping the command in something that forks instead of `exec`-ing, a ``timeout 600`` added
    after a hung job, say) silently turned the one layer that stops a demonstrated attack into a
    no-op, with every existing test and check still green. The execute step sets this variable so
    that case is no longer silent: with it set, raises ``PidNamespaceNotActive`` (the file is left
    unchanged; see ``execute``) if ``in_an_isolated_pid_namespace()`` is not true, and otherwise
    prints "pid namespace: active", which the workflow step's own log is grepped for immediately
    afterwards. Unset -- a local run, every test in this repository, the ``Tests`` jobs -- this is
    a no-op, exactly like the kill helper itself.
    """
    if not os.environ.get(PID_NAMESPACE_REQUIRED_ENV):
        return
    if not in_an_isolated_pid_namespace():
        raise PidNamespaceNotActive(
            f"{PID_NAMESPACE_REQUIRED_ENV} is set but this process is not PID 1 of an isolated, "
            "procfs-mounted PID namespace; refusing to write the result"
        )
    print("pid namespace: active")


KILL_OTHER_PROCESSES_TIMEOUT = 2.0


def kill_everyone_else_in_my_pid_namespace(timeout: float = KILL_OTHER_PROCESSES_TIMEOUT) -> None:
    """If this process is PID 1 of an isolated PID namespace (``in_an_isolated_pid_namespace()``),
    kill and wait out every other, non-zombie process still in it. A no-op outside a PID namespace
    (a local run, or any test that calls ``execute`` directly).

    #108 fix round 5, M1: a PID namespace guarantees that nothing survives PID 1 *exiting*, but a
    cell can start a detached (``setsid``) process that outlives the kernel nbclient manages and
    keeps running during this process's own shutdown -- the gap between the write this guards and
    this process actually exiting is real, even if small, and a fast enough loop (a 5 ms rewrite of
    ``notebook.ipynb``, reproduced in review) can still win it; narrowing the gap is not enough.
    Explicitly killing everything else first, and confirming it is gone before writing, closes it
    instead of narrowing it further. Raises ``RuntimeError`` (the job then fails, rather than
    silently trusting an unverified write) if something will not die within ``timeout`` seconds.
    """
    if not in_an_isolated_pid_namespace():
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [
            pid
            for pid in (int(entry) for entry in os.listdir("/proc") if entry.isdigit())
            if pid != 1 and process_state(pid) not in (None, "Z")
        ]
        if not alive:
            return
        for pid in alive:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.01)
    raise RuntimeError(
        "a process in the sandbox's PID namespace would not die; refusing to write the result"
    )


def execute(recipe_dir: Path, timeout: int = TIMEOUT_SECONDS) -> None:
    """Run ``recipe_dir/notebook.ipynb`` and write it back with outputs.

    Raises ``CellExecutionError`` when a cell fails, ``CellTimeoutError`` when one runs longer than
    ``timeout`` seconds, ``DeadKernelError`` when the kernel dies, ``KernelStartError`` when it
    never starts and ``StderrOutput`` when a cell writes to stderr; the file is left unchanged in
    every case.
    """
    recipe_dir = recipe_dir.resolve()
    path = recipe_dir / NOTEBOOK
    for attempt in (1, 2):
        nb = nbformat.read(path, as_version=4)
        try:
            run_in_fresh_kernel(nb, recipe_dir, timeout)
            break
        except RuntimeError as error:
            if isinstance(error, DeadKernelError) or not any(
                message in str(error) for message in START_FAILURES
            ):
                raise
            # No cell has run: the kernel never answered, so a fresh one is tried once.
            if attempt == 2:
                raise KernelStartError(str(error)) from error
    check_no_stderr(nb)
    nb.metadata = nbformat.from_dict(METADATA)
    nbformat.validate(nb)
    # #108 fix round 6, B6 M1: fail loudly, before the kill helper runs, if the sandboxed execute
    # step's demand for a PID namespace is not actually met -- see require_pid_namespace_if_
    # demanded's docstring.
    require_pid_namespace_if_demanded()
    # See kill_everyone_else_in_my_pid_namespace's docstring: nothing else may still be alive when
    # the write below happens.
    kill_everyone_else_in_my_pid_namespace()
    # Always LF, so the file is the same bytes on every platform (nbformat.write would follow
    # the operating system's newline).
    text = nbformat.writes(nb) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def positive_seconds(text: str) -> int:
    """``--timeout`` value: nbclient treats 0 as no limit, so anything below 1 is refused."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"must be a whole number of seconds, got {text!r}"
        ) from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1 second, got {value}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute a recipe notebook in place, offline.")
    parser.add_argument("recipe_dir", help="a recipe folder, such as recipes/01-slug")
    parser.add_argument(
        "--timeout",
        type=positive_seconds,
        default=TIMEOUT_SECONDS,
        help=f"seconds one cell may run (default {TIMEOUT_SECONDS})",
    )
    args = parser.parse_args(argv)
    folder = Path(args.recipe_dir)
    if not (folder / NOTEBOOK).is_file():
        print(f"no {NOTEBOOK} in {folder.name!r}", file=sys.stderr)
        return 2
    try:
        execute(folder, args.timeout)
    except StderrOutput as error:
        print(f"{folder.name}: {error}; {NOTEBOOK} left unchanged", file=sys.stderr)
        return 1
    except PidNamespaceNotActive as error:
        print(f"{folder.name}: {error}", file=sys.stderr)
        return 1
    except DeadKernelError as error:
        print(
            f"{folder.name}: the kernel died ({error}); {NOTEBOOK} left unchanged", file=sys.stderr
        )
        return 1
    except CellTimeoutError as error:
        print(
            f"{folder.name}: a cell ran longer than {args.timeout} s ({error}); "
            f"{NOTEBOOK} left unchanged",
            file=sys.stderr,
        )
        return 1
    except KernelStartError as error:
        print(
            f"{folder.name}: the kernel did not start ({error}); {NOTEBOOK} left unchanged",
            file=sys.stderr,
        )
        return 1
    except CellExecutionError as error:
        print(f"{folder.name}: a cell failed; {NOTEBOOK} left unchanged\n{error}", file=sys.stderr)
        return 1
    print(f"{folder.name}: executed {NOTEBOOK} offline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
