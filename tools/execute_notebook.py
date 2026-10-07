"""Execute a recipe's notebook in place, offline, with the recipe folder as working directory.

    python tools/execute_notebook.py recipes/NN-slug

It runs ``notebook.ipynb`` in a fresh kernel and writes the outputs back to the same file.
Three things are fixed so that running it twice gives the same file:

* the kernel's environment has no ``JEV_COOKBOOK_*`` variable and no ``TYPESAFE_API_KEY``, so
  the run is offline and replays the fixtures whatever the shell had set;
* execution timings are not recorded;
* the notebook metadata is reset to the Python version independent minimum (kernel name and
  language ``python``), so the file does not change with the interpreter that ran it.

Exit status is 0 when the notebook ran to the end, 1 when a cell failed (the file is left
unchanged), and 2 for a usage error. #69 builds CI (network guard, staleness check) on this.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

NOTEBOOK = "notebook.ipynb"
KERNEL_NAME = "python3"
SCRUBBED_ENV = ("TYPESAFE_API_KEY",)  # plus every variable starting with JEV_COOKBOOK_
TIMEOUT_SECONDS = 300
METADATA = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": KERNEL_NAME},
    "language_info": {"name": "python"},
}


def offline_environment(environ: dict[str, str]) -> dict[str, str]:
    """A copy of ``environ`` without the live switch, its settings, and the API key."""
    return {
        k: v
        for k, v in environ.items()
        if not k.startswith("JEV_COOKBOOK_") and k not in SCRUBBED_ENV
    }


def execute(recipe_dir: Path) -> None:
    """Run ``recipe_dir/notebook.ipynb`` and write it back with outputs. Raises on a failure."""
    recipe_dir = recipe_dir.resolve()
    path = recipe_dir / NOTEBOOK
    nb = nbformat.read(path, as_version=4)
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(offline_environment(saved))
    try:
        client = NotebookClient(
            nb,
            kernel_name=KERNEL_NAME,
            timeout=TIMEOUT_SECONDS,
            record_timing=False,
            resources={"metadata": {"path": str(recipe_dir)}},
        )
        client.execute()
    finally:
        os.environ.clear()
        os.environ.update(saved)
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
    except CellExecutionError as error:
        print(f"{folder.name}: a cell failed; {NOTEBOOK} left unchanged\n{error}", file=sys.stderr)
        return 1
    print(f"{folder.name}: executed {NOTEBOOK} offline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
