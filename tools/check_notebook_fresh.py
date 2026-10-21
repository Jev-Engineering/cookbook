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
2. Every ``outputs[*].data["image/png"]`` and ``["image/jpeg"]`` is replaced by a marker that
   records only that an image of that type is there. Nothing else is normalised: after that the
   two notebooks, parsed as JSON, must be equal (sources, metadata, execution counts, text
   outputs, ids, every other output).
3. Each pair of images is then compared by what it shows rather than by its bytes, because the
   bytes change with the matplotlib version, the encoder version, the platform and the pixel
   size. See ``compare_png`` (it decodes either format).
4. The outputs of all the cells together may weigh at most ``MAX_OUTPUT_BYTES``, in either file.
5. Every embedded image in either file obeys the metadata rules of ``tools/check_recipe_assets.py``
   (``embedded_image_problems``), because comparing pixels cannot see EXIF or text in the bytes: a
   PNG or JPEG output, or a ``data:image`` URI in an output, may hold no metadata (a PNG may
   hold matplotlib's ``Software`` line); a Markdown or raw cell may embed no image at all.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

PNG_PRESENT = "<image/png: present>"
# Output types whose payload is compared by what it shows. A JPEG is normalised like a PNG because
# Pillow offers every image it displays as both (``_repr_png_`` and ``_repr_jpeg_``), and the bytes
# of a JPEG depend on the libjpeg that Pillow bundles.
IMAGE_MIMES = ("image/png", "image/jpeg")
MAX_PROBLEMS = 12
MAX_TEXT = 90

# Tags nbclient honours to skip a cell's execution entirely (``skip-execution`` is
# ``NotebookClient.skip_cells_with_tag``'s own default, which ``tools/execute_notebook.py`` leaves
# unset). A skipped cell keeps whatever it already had, run or not, so its presence defeats the
# freshness comparison regardless of what the cell outputs.
SKIP_EXECUTION_TAGS = frozenset({"skip-execution"})

# The most a notebook's ``outputs`` may weigh in all: the UTF-8 length of each output serialised as
# compact JSON (base64 images included), summed over every cell. The largest notebook on ``main`` at
# the time of writing is about 0.2 MiB. Displaying a ``PIL.Image`` re-encodes its pixels as both a
# PNG and a JPEG, which weighs 8 to 22 times the fixture file (measured: a 120 KB noisy 1280x720
# JPEG displays as 1.98 MB; a flat 384x320 JPEG of 10 KB as 92 KB), whereas
# ``IPython.display.Image(filename=path)`` embeds the file's own bytes once (160 KB for that 120 KB
# frame). docs/notebook-ci.md gives the guidance.
MAX_OUTPUT_BYTES = 2 * 1024 * 1024

# An image written into a text cell or output as a data URI.
DATA_IMAGE_URI = re.compile(
    r"data:\s*image/([\w.+-]+)(?:;[^;,]*)*;base64,([A-Za-z0-9+/=\s]+)", re.IGNORECASE
)
# Any data URI that names an image type, in any spelling (case, parameters, base64 or not). In a
# text cell or in metadata nothing is decoded: an embedded image there is a problem.
ANY_DATA_IMAGE = re.compile(r"data:\s*image/", re.IGNORECASE)
# The image types a recipe notebook output may hold; anything else with an ``image/`` prefix (a
# GIF, a WebP) is a problem. ``image/svg+xml`` is text, compared byte for byte.
OUTPUT_IMAGE_MIMES = ("image/png", "image/jpeg", "image/svg+xml")

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
    problems.extend(embedded_image_problems(nb, label))
    weight = output_bytes(nb)
    if weight > MAX_OUTPUT_BYTES:
        problems.append(
            f"{label}: outputs weigh {weight:,} bytes; the cap is {MAX_OUTPUT_BYTES:,} (2 MiB). "
            "Display a fixture with IPython.display.Image(filename=path), which embeds the "
            "file once, instead of a PIL.Image (re-encoded as PNG and JPEG, 8 to 22 times the "
            "file); or show fewer images, or a Image.thumbnail((640, 640)) copy"
        )
    return problems


def _asset_rules() -> Any:
    """``tools/check_recipe_assets.py`` loaded by path (this script runs from any directory)."""
    name = "_check_recipe_assets_for_fresh"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).resolve().parent / "check_recipe_assets.py"
        )
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[name] = module  # a dataclass looks its module up here
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    return sys.modules[name]


def _strings(node: Any) -> Any:
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key not in OUTPUT_IMAGE_MIMES:
                yield from _strings(value)


def _metadata_strings(nb: dict[str, Any]) -> Any:
    """(location, text) for every key and string under the notebook's and each cell's metadata."""

    def walk(node: Any, where: str) -> Any:
        if isinstance(node, str):
            yield where, node
        elif isinstance(node, list):
            for item in node:
                yield from walk(item, where)
        elif isinstance(node, dict):
            for key, value in node.items():
                yield where, str(key)
                yield from walk(value, where)

    yield from walk(nb.get("metadata"), "notebook metadata")
    for index, cell in enumerate(nb["cells"]):
        if isinstance(cell, dict):
            yield from walk(cell.get("metadata"), f"{_where(index, cell)} metadata")


def embedded_image_problems(nb: dict[str, Any], label: str) -> list[str]:
    """Metadata and embedding rules for every image stored in ``nb`` (see the module docstring).

    Pixels are compared elsewhere; this reads the bytes. A committed image can hold EXIF, GPS,
    an author or a local path that a fresh run (whose input is the stripped asset) never
    reproduces, so it is checked in both files, whatever the comparison says.
    """
    rules = _asset_rules()
    problems = []

    def check(where: str, mime: str, value: Any) -> None:
        try:
            raw = base64.b64decode(_text(value), validate=False)
        except (binascii.Error, ValueError):
            problems.append(f"{label}: {where} holds an undecodable {mime} payload")
            return
        for finding in rules.inspect_embedded(mime, raw):
            problems.append(
                f"{label}: {where} holds a {mime} that breaks [{finding.rule}]: {finding.message}"
            )

    for where, text in _metadata_strings(nb):
        if ANY_DATA_IMAGE.search(text) or text.lower().startswith("image/"):
            problems.append(
                f"{label}: {where} holds an embedded image in metadata; link a file under "
                "assets/ instead"
            )
    for index, cell in enumerate(nb["cells"]):
        if isinstance(cell, dict) and cell.get("cell_type") != "code":
            source = _text(cell.get("source", ""))
            if cell.get("attachments") or ANY_DATA_IMAGE.search(source):
                problems.append(
                    f"{label}: {_where(index, cell)} embeds an image in a text cell (an "
                    "attachment or a data: URI); link a file under assets/ by its relative path "
                    "instead"
                )
        for out_index, output in enumerate(_outputs(cell)):
            if not isinstance(output, dict):
                continue
            where = _where(index, cell, out_index)
            data = output.get("data")
            for mime in data if isinstance(data, dict) else ():
                if mime in ("image/png", "image/jpeg"):
                    check(where, mime, data[mime])
                elif mime.startswith("image/") and mime not in OUTPUT_IMAGE_MIMES:
                    problems.append(f"{label}: {where} holds an {mime} output; only PNG and JPEG")
            for text in _strings(output):
                for match in DATA_IMAGE_URI.finditer(text):
                    mime = "image/" + match.group(1).lower().replace("jpg", "jpeg")
                    check(f"{where} (data: URI)", mime, match.group(2))
    return problems


def output_bytes(nb: dict[str, Any]) -> int:
    """The UTF-8 length of every output of every cell, each serialised as compact JSON."""
    return sum(
        len(json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        for cell in nb["cells"]
        for output in _outputs(cell)
    )


def normalise(nb: dict[str, Any]) -> tuple[dict[str, Any], dict[tuple[int, int, str], Any]]:
    """A copy of ``nb`` with every ``image/png`` and ``image/jpeg`` value replaced by a marker
    (``PNG_PRESENT`` for a PNG), and the original values by (cell index, output index, mime type).
    This is the only normalisation."""
    result = copy.deepcopy(nb)
    images: dict[tuple[int, int], Any] = {}
    for index, cell in enumerate(result["cells"]):
        for out_index, output in enumerate(_outputs(cell)):
            data = output.get("data") if isinstance(output, dict) else None
            for mime in IMAGE_MIMES if isinstance(data, dict) else ():
                if mime in data:
                    images[(index, out_index, mime)] = data[mime]
                    data[mime] = f"<{mime}: present>"
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
    """The image (PNG or JPEG) as an RGB ``PIL.Image`` flattened onto white."""
    from PIL import Image

    try:
        raw = base64.b64decode(_text(value), validate=False)
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (binascii.Error, OSError, ValueError) as error:
        raise ValueError(f"not a decodable image ({type(error).__name__})") from error
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
    """Do two ``image/png`` (or two ``image/jpeg``) values show the same figure? Returns (same, detail).

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
                    f"{where}: the committed {key[2]} is stale, it does not match a fresh run "
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
