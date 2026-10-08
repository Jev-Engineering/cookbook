"""Is a committed notebook what a fresh offline run produces? (#69)

    python tools/check_notebook_fresh.py recipes/NN-slug/notebook.ipynb /scratch/NN-slug/notebook.ipynb

The first file is the committed notebook, the second the same recipe executed from scratch by
``tools/execute_notebook.py`` in a copy. Exit 0 when they agree, 1 with one line per problem
when they do not, 2 for a usage error or a file that is not a notebook. Standard library plus
numpy and Pillow (both installed with matplotlib); only the figure comparison needs them.

The comparison, in full (it is documented in ``docs/notebook-ci.md``):

1. An ``error`` output (what a cell tagged ``raises-exception`` commits) is a problem, in either
   file. So is a ``stderr`` stream output. So is a code cell tagged ``skip-execution``: nbclient's
   default (``tools/execute_notebook.py`` does not override it) never executes such a cell, so
   whatever it commits, output or none, did not come from the run being checked. (nbclient only
   ever skips code cells; a markdown or raw cell has no outputs to fabricate, so the rule does
   not apply to one even if it happens to carry the tag.)
2. Every ``outputs[*].data["image/png"]`` is replaced by a marker that records only that a PNG is
   there. Nothing else is normalised: after that the two notebooks, parsed as JSON, must be
   equal (sources, metadata, execution counts, text outputs, ids, every other output).
3. Each pair of PNGs is then compared by what it shows rather than by its bytes, because the
   bytes change with the matplotlib version, the platform and the pixel size. See ``compare_png``.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import io
import json
import sys
from pathlib import Path
from typing import Any

PNG_PRESENT = "<image/png: present>"
MAX_PROBLEMS = 12
MAX_TEXT = 90

# Tags nbclient honours to skip a cell's execution entirely (``skip-execution`` is
# ``NotebookClient.skip_cells_with_tag``'s own default, which ``tools/execute_notebook.py`` leaves
# unset). A skipped cell keeps whatever it already had, run or not, so its presence defeats the
# freshness comparison regardless of what the cell outputs.
SKIP_EXECUTION_TAGS = frozenset({"skip-execution"})

# Figure comparison (``compare_png``). Both images are flattened onto white and shrunk with a box
# filter to a fixed GRID of cells, so the pixel size does not matter. A cell of one image is
# "unmatched" when no cell of the other image within SHIFT cells of it (a 3 by 3 window) is
# within LEVEL of 255 in every colour channel. The shift forgives what rendering does: the same
# chart drawn by another matplotlib version or platform moves edges by a pixel or two and rescales
# the plot area by a few percent, which leaves a line of unmatched cells along every hard edge.
# Two figures differ when a 2 by 2 block of cells is unmatched, which a line is not and a changed
# bar, recoloured highlight or changed heat-map cell is. Calibrated on the template's figures and
# on probes; the numbers and what the rule cannot see are in docs/notebook-ci.md.
GRID = (64, 48)
SHIFT = 1
LEVEL = 30
ASPECT_TOLERANCE = 0.08


class NotebookError(Exception):
    """A file that is not a notebook this tool can read."""


def load_notebook(path: Path) -> dict[str, Any]:
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NotebookError(f"{path}: cannot read as a notebook ({error})") from error
    if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
        raise NotebookError(f"{path}: not a notebook (no cell list)")
    return nb


def _text(value: Any) -> str:
    return "".join(value) if isinstance(value, list) else str(value)


def _where(index: int, cell: Any, out_index: int | None = None) -> str:
    name = cell.get("id", "no id") if isinstance(cell, dict) else "?"
    suffix = "" if out_index is None else f", output {out_index}"
    return f"cell {index} ({name}){suffix}"


def _outputs(cell: Any) -> list[Any]:
    outputs = cell.get("outputs", []) if isinstance(cell, dict) else []
    return outputs if isinstance(outputs, list) else []


def _tags(cell: Any) -> list[Any]:
    metadata = cell.get("metadata") if isinstance(cell, dict) else None
    tags = metadata.get("tags") if isinstance(metadata, dict) else None
    return tags if isinstance(tags, list) else []


def _is_code_cell(cell: Any) -> bool:
    return isinstance(cell, dict) and cell.get("cell_type") == "code"


def output_problems(nb: dict[str, Any], label: str) -> list[str]:
    """Every ``error`` output, every ``stderr`` stream output, and every skipped code cell in
    ``nb``. nbclient only ever skips a code cell, so a markdown or raw cell that happens to carry
    the tag is not flagged: it has no outputs to fabricate."""
    problems = []
    for index, cell in enumerate(nb["cells"]):
        skip_tags = sorted(set(_tags(cell)) & SKIP_EXECUTION_TAGS) if _is_code_cell(cell) else []
        if skip_tags:
            problems.append(
                f"{label}: {_where(index, cell)} is tagged {skip_tags[0]!r}; nbclient never "
                "executes a code cell with this tag, so its outputs cannot have come from a real "
                "run and a recipe must not use it"
            )
        for out_index, output in enumerate(_outputs(cell)):
            if not isinstance(output, dict):
                continue
            kind = output.get("output_type")
            if kind == "error":
                problems.append(
                    f"{label}: {_where(index, cell, out_index)} holds an error output "
                    f"({output.get('ename', '?')}); a notebook must run clean "
                    "(a raises-exception tag does not make it acceptable)"
                )
            elif kind == "stream" and output.get("name") == "stderr":
                problems.append(f"{label}: {_where(index, cell, out_index)} holds stderr output")
    return problems


def normalise(nb: dict[str, Any]) -> tuple[dict[str, Any], dict[tuple[int, int], Any]]:
    """A copy of ``nb`` with every ``image/png`` value replaced by ``PNG_PRESENT``, and the
    original values by (cell index, output index). This is the only normalisation."""
    result = copy.deepcopy(nb)
    images: dict[tuple[int, int], Any] = {}
    for index, cell in enumerate(result["cells"]):
        for out_index, output in enumerate(_outputs(cell)):
            data = output.get("data") if isinstance(output, dict) else None
            if isinstance(data, dict) and "image/png" in data:
                images[(index, out_index)] = data["image/png"]
                data["image/png"] = PNG_PRESENT
    return result, images


def _clip(value: Any) -> str:
    text = repr(value) if isinstance(value, str) else json.dumps(value, ensure_ascii=True)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 3] + "..."


def differences(a: Any, b: Any, path: str = "notebook") -> list[str]:
    """Where two parsed JSON values differ, as ``path: committed X, fresh Y`` lines."""
    if isinstance(a, dict) and isinstance(b, dict):
        found = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                found.append(f"{path}.{key}: only in the fresh run")
            elif key not in b:
                found.append(f"{path}.{key}: only in the committed notebook")
            else:
                found.extend(differences(a[key], b[key], f"{path}.{key}"))
        return found
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} items committed, {len(b)} in the fresh run"]
        found = []
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found.extend(differences(x, y, f"{path}[{i}]"))
        return found
    if a != b or type(a) is not type(b):
        return [f"{path}: committed {_clip(a)}, fresh {_clip(b)}"]
    return []


def decode_png(value: Any) -> Any:
    """The image as an RGB ``PIL.Image`` flattened onto white."""
    from PIL import Image

    try:
        raw = base64.b64decode(_text(value), validate=False)
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (binascii.Error, OSError, ValueError) as error:
        raise ValueError(f"not a decodable PNG ({type(error).__name__})") from error
    rgba = image.convert("RGBA")
    flat = Image.alpha_composite(Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba)
    return flat.convert("RGB")


def _unmatched(cells_a: Any, cells_b: Any) -> Any:
    """Boolean grid: cells of ``cells_a`` with no match in ``cells_b`` within ``SHIFT`` cells."""
    import numpy as np

    height, width, _ = cells_a.shape
    padded = np.pad(cells_b, ((SHIFT, SHIFT), (SHIFT, SHIFT), (0, 0)), mode="edge")
    best = np.full((height, width), np.inf)
    for dy in range(2 * SHIFT + 1):
        for dx in range(2 * SHIFT + 1):
            shifted = padded[dy : dy + height, dx : dx + width]
            best = np.minimum(best, np.abs(cells_a - shifted).max(axis=2))
    return best > LEVEL


def _blocks(mask: Any) -> int:
    """How many 2 by 2 blocks of ``mask`` are entirely set."""
    return int((mask[:-1, :-1] & mask[1:, :-1] & mask[:-1, 1:] & mask[1:, 1:]).sum())


def compare_png(committed: Any, fresh: Any) -> tuple[bool, str]:
    """Do two ``image/png`` values show the same figure? Returns (same, detail).

    Equal bytes are the same without decoding. Otherwise the figures differ when their aspect
    ratios differ by more than ``ASPECT_TOLERANCE`` or when a 2 by 2 block of ``GRID`` cells is
    unmatched in either direction (see the comment at ``GRID``).
    """
    import numpy as np
    from PIL import Image

    if _text(committed).strip() == _text(fresh).strip():
        return True, "identical bytes"
    try:
        a, b = decode_png(committed), decode_png(fresh)
    except ValueError as error:
        return False, str(error)
    ratio_a, ratio_b = a.width / a.height, b.width / b.height
    if abs(ratio_a - ratio_b) > ASPECT_TOLERANCE * ratio_a:
        return False, f"shape differs ({a.width}x{a.height} committed, {b.width}x{b.height} fresh)"
    cells_a = np.asarray(a.resize(GRID, Image.BOX), dtype=float)
    cells_b = np.asarray(b.resize(GRID, Image.BOX), dtype=float)
    blocks = max(_blocks(_unmatched(cells_a, cells_b)), _blocks(_unmatched(cells_b, cells_a)))
    return blocks == 0, f"{blocks} unmatched 2x2 blocks of {GRID[0]}x{GRID[1]} cells"


def check(committed: dict[str, Any], fresh: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(problems, notes): what is wrong, and one line per figure that was compared."""
    problems = output_problems(committed, "committed") + output_problems(fresh, "fresh run")
    norm_a, images_a = normalise(committed)
    norm_b, images_b = normalise(fresh)
    found = differences(norm_a, norm_b)
    problems.extend(found[:MAX_PROBLEMS])
    if len(found) > MAX_PROBLEMS:
        problems.append(f"... and {len(found) - MAX_PROBLEMS} more differences")
    notes = []
    if not found:
        for key in sorted(images_a):
            where = _where(key[0], committed["cells"][key[0]], key[1])
            same, detail = compare_png(images_a[key], images_b[key])
            notes.append(f"{where}: figure {'matches' if same else 'DIFFERS'}, {detail}")
            if not same:
                problems.append(
                    f"{where}: the committed figure is stale, it does not match a fresh run "
                    f"({detail})"
                )
    return problems, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("committed", type=Path, help="the notebook in the repository")
    parser.add_argument("fresh", type=Path, help="the same notebook after a fresh execution")
    args = parser.parse_args(argv)
    try:
        committed, fresh = load_notebook(args.committed), load_notebook(args.fresh)
    except NotebookError as error:
        print(error, file=sys.stderr)
        return 2
    problems, notes = check(committed, fresh)
    for note in notes:
        print(note)
    for problem in problems:
        print(f"STALE: {problem}")
    if problems:
        print(
            f"{args.committed}: not fresh; run python tools/execute_notebook.py on the "
            "recipe folder and commit the result",
            file=sys.stderr,
        )
        return 1
    print(f"{args.committed}: matches a fresh offline run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
