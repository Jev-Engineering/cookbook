"""Execute a recipe's notebook in place, offline, with the recipe folder as working directory.

    python tools/execute_notebook.py recipes/NN-slug

It runs ``notebook.ipynb`` in a fresh kernel and writes the outputs back to the same file.
Three things are fixed so that running it twice gives the same file:

* the kernel's environment has no ``JEV_COOKBOOK_*`` and no ``TYPESAFE_*`` variable, so the
  run is offline and replays the fixtures whatever the shell had set. The environment is built
  as a copy and passed to the kernel; this process's own environment is never changed, so
  several notebooks can be executed in parallel (on Windows, starting several kernels at the same
  time can fail with a ZMQ "Address in use" error: run them one after another, or retry once);
* the kernel is the interpreter running this tool (``sys.executable``), not whichever
  ``python3`` kernelspec Jupyter finds first, so a user-level kernelspec cannot swap the
  environment the committed outputs were made in;
* stream output is coalesced (``coalesce_streams``), so a printed line is never split into two
  stream outputs by an IOPub flush that lands between its text and its newline;
* execution timings are not recorded;
* the notebook metadata is reset to the Python version independent minimum (kernel name and
  language ``python``), so the file does not change with the interpreter that ran it.

A run in which any cell wrote to stderr also fails: stderr carries warnings and absolute paths,
which must not be committed.

Exit status is 0 when the notebook ran to the end, 1 when a cell failed, the kernel died or a cell
wrote to stderr (the file is left unchanged), and 2 for a usage error. #69 builds CI (network guard, staleness check) on this.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import nbformat
from ipykernel.kernelspec import get_kernel_dict
from jupyter_client.kernelspec import KernelSpec, KernelSpecManager
from jupyter_client.manager import AsyncKernelManager
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError, DeadKernelError

NOTEBOOK = "notebook.ipynb"
KERNEL_NAME = "python3"
SCRUBBED_PREFIXES = ("JEV_COOKBOOK_", "TYPESAFE_")
TIMEOUT_SECONDS = 300
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


def execute(recipe_dir: Path) -> None:
    """Run ``recipe_dir/notebook.ipynb`` and write it back with outputs.

    Raises ``CellExecutionError`` when a cell fails, ``DeadKernelError`` when the kernel dies
    and ``StderrOutput`` when a cell writes to stderr; the file is left unchanged in every case.
    """
    recipe_dir = recipe_dir.resolve()
    path = recipe_dir / NOTEBOOK
    nb = nbformat.read(path, as_version=4)
    # An async manager is needed for nbclient to notice a dead kernel (``os._exit``, a crash);
    # with a blocking one a dead kernel hangs the run and the cell timeout never applies.
    manager = AsyncKernelManager(
        kernel_name=KERNEL_NAME, kernel_spec_manager=RunningInterpreterSpecs()
    )
    client = NotebookClient(
        nb,
        km=manager,
        kernel_name=KERNEL_NAME,
        timeout=TIMEOUT_SECONDS,
        record_timing=False,
        coalesce_streams=True,
        resources={"metadata": {"path": str(recipe_dir)}},
    )
    # ``env`` replaces the kernel's whole environment; this process's is left alone.
    client.execute(env=offline_environment(dict(os.environ)))
    check_no_stderr(nb)
    nb.metadata = nbformat.from_dict(METADATA)
    nbformat.validate(nb)
    # Always LF, so the file is the same bytes on every platform (nbformat.write would follow
    # the operating system's newline).
    text = nbformat.writes(nb) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute a recipe notebook in place, offline.")
    parser.add_argument("recipe_dir", help="a recipe folder, such as recipes/01-slug")
    args = parser.parse_args(argv)
    folder = Path(args.recipe_dir)
    if not (folder / NOTEBOOK).is_file():
        print(f"no {NOTEBOOK} in {folder.name!r}", file=sys.stderr)
        return 2
    try:
        execute(folder)
    except StderrOutput as error:
        print(f"{folder.name}: {error}; {NOTEBOOK} left unchanged", file=sys.stderr)
        return 1
    except DeadKernelError as error:
        print(
            f"{folder.name}: the kernel died ({error}); {NOTEBOOK} left unchanged", file=sys.stderr
        )
        return 1
    except CellExecutionError as error:
        print(f"{folder.name}: a cell failed; {NOTEBOOK} left unchanged\n{error}", file=sys.stderr)
        return 1
    print(f"{folder.name}: executed {NOTEBOOK} offline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
