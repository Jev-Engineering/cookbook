"""Deterministic synthetic test images for multimodal recipes (#314).

Every multimodal recipe needs readable images whose content is fully known: a UI with an error
banner, a shelf with one gap, a plate with a scratch. This module draws them from code, so no
fixture holds a real photograph, brand, person, product screenshot or third-party image, and
every gold rectangle is *derived from the pixels that were drawn* instead of typed by hand.

What it is built on, and why
----------------------------
* **Byte-for-byte reproducible by construction.** An image's bytes are part of the replay key
  (``backends.replay_key``), so a regenerated asset must never differ silently. Pillow's
  rasterisers, FreeType and zlib all change between releases (Pillow's wheels moved to zlib-ng,
  for one), so none of them touches the output. Pixels are integer ``numpy`` arrays written by
  the code below (integer geometry, an embedded 5 x 7 bitmap font, a SplitMix64 random
  generator); the PNG is written by ``encode_png`` here, which uses a fixed-Huffman deflate
  stream of its own. The result depends only on this file, ``numpy``'s integer array semantics
  and ``zlib.crc32``/``zlib.adler32`` (both fixed by their definitions). Python 3.10 to 3.14 and
  any Pillow, FreeType, zlib or numpy 1.x/2.x on any platform give the same bytes;
  ``tests/test_synthetic_images.py`` pins SHA-256 digests to prove it on every CI Python.
  Pillow is used only to *read* a file back for verification and in the tests.
* **No fonts to ship.** Text uses the 5 x 7 bitmap font defined below (written for this
  repository, released with it under the repository licence), scaled by an integer of at least
  :data:`MIN_TEXT_SCALE`, so a glyph is at least 14 pixels tall. Supported characters are in
  :data:`SUPPORTED_CHARS`; lower case is folded to upper case.
* **Gold geometry.** Every drawing call returns a :class:`Placed`: the tight pixel bounds of
  what that call changed and the same rectangle as a normalized ``Box`` mapping
  (``Placed.box``), accepted by :mod:`jev_cookbook.vision`.
* **Provenance.** Each finished :class:`SyntheticImage` carries ``provenance`` (origin,
  generator, generator version, seed, parameters) and, once written, a flat manifest record from
  :meth:`SavedImage.manifest_entry`. The assets manifest (#308) is the intended consumer; this
  module does not depend on its file format.

Policy: committed bytes are canonical
-------------------------------------
:func:`write_asset` writes a new file but never replaces an existing one. A recipe's
``build_fixtures.py`` calls it on every run: identical bytes give status ``"identical"``,
different bytes with identical decoded pixels give ``"pixel-equal"`` (an older encoder or a
hand-made file; nothing is rewritten) and anything else raises :class:`AssetMismatchError`.
Changing what a generator draws or how it encodes means bumping :data:`GENERATOR_VERSION` and
regenerating deliberately, which changes image hashes and therefore replay keys; the hash-pinned
tests make that impossible to do by accident.

All geometry is in integer pixels, ``(left, top, right, bottom)`` with exclusive right and
bottom edges, matching Pillow crops and :func:`jev_cookbook.vision.normalized_to_pixels`.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from .vision import IMAGE_LIMITS, image_asset

__all__ = [
    "FICTIONAL_BRANDS",
    "GENERATORS",
    "GENERATOR_VERSION",
    "GLYPH_HEIGHT",
    "MAX_ASSET_BYTES",
    "MIN_TEXT_SCALE",
    "SUPPORTED_CHARS",
    "AssetMismatchError",
    "Canvas",
    "Frame",
    "FrameSequence",
    "Placed",
    "Rng",
    "SavedImage",
    "SyntheticImage",
    "TextRun",
    "appearing_object_frames",
    "compare_asset",
    "contrast_ratio",
    "deck_builder_hud",
    "defect_panel",
    "document_page",
    "encode_png",
    "moving_object_frames",
    "product_shelf",
    "read_text",
    "save_sequence",
    "schematic",
    "shapes_scene",
    "text_size",
    "ui_mock",
    "wordmark",
    "with_gold_boxes",
    "wrap_text",
    "write_asset",
]

# Bump when a generator's drawing or the encoder changes: every output hash (and every replay
# key built on one) changes with it. The hash-pinned tests fail until the pins are updated.
GENERATOR_VERSION = "1"

# The repository's per-file cap (tools/check_recipe_assets.py MAX_FILE_BYTES; a test compares).
MAX_ASSET_BYTES = 1024 * 1024

Color = tuple[int, int, int]
Bounds = tuple[int, int, int, int]

# --- random numbers ---------------------------------------------------------------------

_MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


def _mix64(z: int) -> int:
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return z ^ (z >> 31)


def _check_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
        raise ValueError("seed must be an integer from 0 to 2**63 - 1")
    return seed


class Rng:
    """SplitMix64: a tiny generator whose output is fixed by its definition.

    ``random.Random`` is stable for ``random()`` but its ``randrange``/``shuffle`` algorithms
    have changed between Python releases; this class cannot drift.
    """

    def __init__(self, seed: int) -> None:
        self._state = _check_seed(seed)

    def u64(self) -> int:
        self._state = (self._state + _GOLDEN) & _MASK64
        return _mix64(self._state)

    def integer(self, low: int, high: int) -> int:
        """An integer in ``[low, high]`` (inclusive; modulo bias is below 2**-40 and fixed)."""
        if high < low:
            raise ValueError("high must be at least low")
        return low + self.u64() % (high - low + 1)

    def choice(self, items: Sequence[Any]) -> Any:
        if not items:
            raise ValueError("cannot choose from an empty sequence")
        return items[self.integer(0, len(items) - 1)]

    def shuffled(self, items: Sequence[Any]) -> list[Any]:
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.integer(0, i)
            out[i], out[j] = out[j], out[i]
        return out


def _u64_array(seed: int, count: int) -> np.ndarray:
    """The first ``count`` outputs of ``Rng(seed)`` as a uint64 array (vectorised)."""
    index = np.arange(1, count + 1, dtype=np.uint64)
    z = np.uint64(seed) + index * np.uint64(_GOLDEN)  # uint64 arithmetic wraps modulo 2**64
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


def _derive(seed: int, *salt: int) -> int:
    value = _check_seed(seed)
    for part in salt:
        value = _mix64((value + part * 0x9E3779B1 + 1) & _MASK64)
    return value & (2**63 - 1)


# --- colours ----------------------------------------------------------------------------


def _rgb(color: Any) -> Color:
    if isinstance(color, str):
        text = color.lstrip("#")
        if len(text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in text):
            raise ValueError(f"colour {color!r} must be '#RRGGBB'")
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    try:
        r, g, b = color
    except (TypeError, ValueError):
        raise ValueError(f"colour {color!r} must be '#RRGGBB' or an (r, g, b) tuple") from None
    if not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in (r, g, b)):
        raise ValueError(f"colour {color!r} needs three integers from 0 to 255")
    return (r, g, b)


def _luminance(color: Color) -> float:
    def channel(value: int) -> float:
        s = value / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: Any, second: Any) -> float:
    """WCAG contrast ratio, 1.0 (identical) to 21.0 (black on white)."""
    a, b = _luminance(_rgb(first)), _luminance(_rgb(second))
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


INK: Color = (30, 30, 30)
WHITE: Color = (255, 255, 255)
PAPER: Color = (245, 243, 238)
GRAY: Color = (150, 154, 160)
MIDGRAY: Color = (107, 107, 107)
LIGHTGRAY: Color = (222, 224, 228)
RED: Color = (178, 40, 30)
GREEN: Color = (30, 120, 70)
AMBER: Color = (232, 160, 20)

# --- the bitmap font --------------------------------------------------------------------

GLYPH_HEIGHT = 7
GLYPH_WIDTH = 5
MIN_TEXT_SCALE = 2  # 14 pixel tall capitals: the smallest text a recipe may draw

_FONT_ROWS = {
    "A": ".###. #...# #...# ##### #...# #...# #...#",
    "B": "####. #...# #...# ####. #...# #...# ####.",
    "C": ".###. #...# #.... #.... #.... #...# .###.",
    "D": "####. #...# #...# #...# #...# #...# ####.",
    "E": "##### #.... #.... ####. #.... #.... #####",
    "F": "##### #.... #.... ####. #.... #.... #....",
    "G": ".###. #...# #.... #.### #...# #...# .####",
    "H": "#...# #...# #...# ##### #...# #...# #...#",
    "I": ".###. ..#.. ..#.. ..#.. ..#.. ..#.. .###.",
    "J": "..### ...#. ...#. ...#. ...#. #..#. .##..",
    "K": "#...# #..#. #.#.. ##... #.#.. #..#. #...#",
    "L": "#.... #.... #.... #.... #.... #.... #####",
    "M": "#...# ##.## #.#.# #.#.# #...# #...# #...#",
    "N": "#...# ##..# #.#.# #..## #...# #...# #...#",
    "O": ".###. #...# #...# #...# #...# #...# .###.",
    "P": "####. #...# #...# ####. #.... #.... #....",
    "Q": ".###. #...# #...# #...# #.#.# #..#. .##.#",
    "R": "####. #...# #...# ####. #.#.. #..#. #...#",
    "S": ".#### #.... #.... .###. ....# ....# ####.",
    "T": "##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
    "U": "#...# #...# #...# #...# #...# #...# .###.",
    "V": "#...# #...# #...# #...# #...# .#.#. ..#..",
    "W": "#...# #...# #...# #.#.# #.#.# ##.## #...#",
    "X": "#...# #...# .#.#. ..#.. .#.#. #...# #...#",
    "Y": "#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..",
    "Z": "##### ....# ...#. ..#.. .#... #.... #####",
    "0": ".###. #...# #..## #.#.# ##..# #...# .###.",
    "1": "..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.",
    "2": ".###. #...# ....# ...#. ..#.. .#... #####",
    "3": "####. ....# ....# .###. ....# ....# ####.",
    "4": "...#. ..##. .#.#. #..#. ##### ...#. ...#.",
    "5": "##### #.... ####. ....# ....# #...# .###.",
    "6": "..##. .#... #.... ####. #...# #...# .###.",
    "7": "##### ....# ...#. ..#.. .#... .#... .#...",
    "8": ".###. #...# #...# .###. #...# #...# .###.",
    "9": ".###. #...# #...# .#### ....# ...#. .##..",
    " ": "..... ..... ..... ..... ..... ..... .....",
    ".": "..... ..... ..... ..... ..... .##.. .##..",
    ",": "..... ..... ..... ..... .##.. ..#.. .#...",
    ":": "..... .##.. .##.. ..... .##.. .##.. .....",
    ";": "..... .##.. .##.. ..... .##.. ..#.. .#...",
    "!": "..#.. ..#.. ..#.. ..#.. ..#.. ..... ..#..",
    "?": ".###. #...# ....# ...#. ..#.. ..... ..#..",
    "-": "..... ..... ..... ##### ..... ..... .....",
    "+": "..... ..#.. ..#.. ##### ..#.. ..#.. .....",
    "/": "....# ....# ...#. ..#.. .#... #.... #....",
    "\\": "#.... #.... .#... ..#.. ...#. ....# ....#",
    "(": "...#. ..#.. .#... .#... .#... ..#.. ...#.",
    ")": ".#... ..#.. ...#. ...#. ...#. ..#.. .#...",
    "[": ".###. .#... .#... .#... .#... .#... .###.",
    "]": ".###. ...#. ...#. ...#. ...#. ...#. .###.",
    "%": "##..# ##..# ...#. ..#.. .#... #..## #..##",
    "#": ".#.#. .#.#. ##### .#.#. ##### .#.#. .#.#.",
    "$": "..#.. .#### #.#.. .###. ..#.# ####. ..#..",
    "'": "..#.. ..#.. .#... ..... ..... ..... .....",
    '"': ".#.#. .#.#. .#.#. ..... ..... ..... .....",
    "=": "..... ..... ##### ..... ##### ..... .....",
    "_": "..... ..... ..... ..... ..... ..... #####",
    "*": "..... ..#.. #.#.# .###. #.#.# ..#.. .....",
    "<": "...#. ..#.. .#... #.... .#... ..#.. ...#.",
    ">": ".#... ..#.. ...#. ....# ...#. ..#.. .#...",
    "@": ".###. #...# #.### #.#.# #.### #.... .####",
    "&": ".##.. #..#. #.#.. .#... #.#.# #..#. .##.#",
}
SUPPORTED_CHARS = "".join(_FONT_ROWS)
_GLYPHS: dict[str, np.ndarray] = {
    char: np.array([[c == "#" for c in row] for row in rows.split()], dtype=bool)
    for char, rows in _FONT_ROWS.items()
}


def _fold(text: str) -> str:
    if not isinstance(text, str) or not text:
        raise ValueError("text must be a nonempty string")
    folded = text.upper()
    bad = sorted({c for c in folded if c not in _GLYPHS})
    if bad:
        raise ValueError(
            f"unsupported character(s) {bad!r}; the bitmap font has only {SUPPORTED_CHARS!r}"
        )
    return folded


def _check_scale(scale: int) -> int:
    if isinstance(scale, bool) or not isinstance(scale, int) or scale < MIN_TEXT_SCALE:
        raise ValueError(
            f"text scale must be an integer of at least {MIN_TEXT_SCALE} "
            f"(glyphs {GLYPH_HEIGHT * MIN_TEXT_SCALE} pixels tall); smaller text is not readable"
        )
    return scale


def text_size(text: str, scale: int = 3) -> tuple[int, int]:
    """``(width, height)`` in pixels of ``text`` drawn at ``scale`` (ink plus no padding)."""
    n = len(_fold(text))
    scale = _check_scale(scale)
    return ((GLYPH_WIDTH + 1) * n - 1) * scale, GLYPH_HEIGHT * scale


def _text_mask(text: str, scale: int) -> np.ndarray:
    folded = _fold(text)
    width = ((GLYPH_WIDTH + 1) * len(folded) - 1) * _check_scale(scale)
    cells = np.zeros((GLYPH_HEIGHT, (GLYPH_WIDTH + 1) * len(folded) - 1), dtype=bool)
    for i, char in enumerate(folded):
        cells[:, i * (GLYPH_WIDTH + 1) : i * (GLYPH_WIDTH + 1) + GLYPH_WIDTH] = _GLYPHS[char]
    mask = np.kron(cells, np.ones((scale, scale), dtype=bool)).astype(bool)
    assert mask.shape[1] == width
    return mask


def wrap_text(text: str, scale: int, max_width: int) -> list[str]:
    """Greedy word wrap to ``max_width`` pixels; a word wider than that raises ``ValueError``."""
    lines: list[str] = []
    current = ""
    for word in _fold(text).split():
        candidate = word if not current else current + " " + word
        if text_size(candidate, scale)[0] <= max_width:
            current = candidate
        elif text_size(word, scale)[0] > max_width:
            raise ValueError(f"the word {word!r} is wider than {max_width} pixels at scale {scale}")
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# --- fictional names --------------------------------------------------------------------

# Invented words (eight letters at most so they fit a label). They are not registered anywhere
# and were not checked against trademark registers: a builder must still never use a real mark.
FICTIONAL_BRANDS = (
    "ZORVA",
    "QUILLEN",
    "BRANTO",
    "VELMORA",
    "TAVRIK",
    "OSMARA",
    "LUMEXA",
    "DRUVEN",
)


# --- geometry records -------------------------------------------------------------------


@dataclass(frozen=True)
class Placed:
    """The tight pixel bounds of what one drawing call changed.

    ``bounds`` is ``(left, top, right, bottom)`` with exclusive right and bottom;
    ``image_size`` is ``(width, height)`` of the canvas, so ``box`` is a normalized rectangle
    that :mod:`jev_cookbook.vision` accepts directly. Pixels drawn later may cover this
    rectangle; it describes the call, not the final picture.
    """

    name: str
    bounds: Bounds
    image_size: tuple[int, int]

    @property
    def box(self) -> dict[str, float]:
        left, top, right, bottom = self.bounds
        width, height = self.image_size
        return {
            "left": left / width,
            "top": top / height,
            "right": right / width,
            "bottom": bottom / height,
        }

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]

    @property
    def center(self) -> tuple[int, int]:
        return (self.bounds[0] + self.bounds[2]) // 2, (self.bounds[1] + self.bounds[3]) // 2

    def contains(self, other: Placed) -> bool:
        a, b = self.bounds, other.bounds
        return a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]

    @staticmethod
    def union(name: str, *parts: Placed) -> Placed:
        if not parts:
            raise ValueError("union needs at least one part")
        sizes = {p.image_size for p in parts}
        if len(sizes) != 1:
            raise ValueError("parts come from different canvases")
        return Placed(
            name,
            (
                min(p.bounds[0] for p in parts),
                min(p.bounds[1] for p in parts),
                max(p.bounds[2] for p in parts),
                max(p.bounds[3] for p in parts),
            ),
            parts[0].image_size,
        )


@dataclass(frozen=True)
class TextRun:
    """One string drawn by :meth:`Canvas.text`: layout origin, scale, colour and the ink box."""

    text: str
    origin: tuple[int, int]
    scale: int
    color: Color
    placed: Placed


def read_text(pixels: np.ndarray, run: TextRun) -> str:
    """Read a :class:`TextRun` back from an *unperturbed* image by matching its glyph cells.

    The check that text was really rendered (and is recognisable) rather than merely recorded.
    """
    x0, y0 = run.origin
    out = []
    for i in range(len(run.text)):
        cell = np.zeros((GLYPH_HEIGHT, GLYPH_WIDTH), dtype=bool)
        for row in range(GLYPH_HEIGHT):
            for col in range(GLYPH_WIDTH):
                px = x0 + (i * (GLYPH_WIDTH + 1) + col) * run.scale + run.scale // 2
                py = y0 + row * run.scale + run.scale // 2
                cell[row, col] = tuple(int(v) for v in pixels[py, px]) == run.color
        matches = [c for c, glyph in _GLYPHS.items() if np.array_equal(glyph, cell)]
        out.append(matches[0] if matches else "�")
    return "".join(out)


# --- masks ------------------------------------------------------------------------------


def _ellipse_mask(width: int, height: int) -> np.ndarray:
    ys = (2 * np.arange(height, dtype=np.int64) + 1 - height)[:, None]
    xs = (2 * np.arange(width, dtype=np.int64) + 1 - width)[None, :]
    return xs * xs * height * height + ys * ys * width * width <= width * width * height * height


def _round_rect_mask(width: int, height: int, radius: int) -> np.ndarray:
    radius = max(0, min(radius, width // 2, height // 2))
    xs = 2 * np.arange(width, dtype=np.int64)[None, :] + 1
    ys = 2 * np.arange(height, dtype=np.int64)[:, None] + 1
    dx = np.maximum(np.maximum(2 * radius - xs, xs - (2 * width - 2 * radius)), 0)
    dy = np.maximum(np.maximum(2 * radius - ys, ys - (2 * height - 2 * radius)), 0)
    return dx * dx + dy * dy <= 4 * radius * radius


def _polygon_mask(points: Sequence[tuple[int, int]], bounds: Bounds) -> np.ndarray:
    left, top, right, bottom = bounds
    xs = 2 * np.arange(left, right, dtype=np.int64)[None, :] + 1
    ys = 2 * np.arange(top, bottom, dtype=np.int64)[:, None] + 1
    signs = []
    for i, (ax, ay) in enumerate(points):
        bx, by = points[(i + 1) % len(points)]
        signs.append((2 * (bx - ax)) * (ys - 2 * ay) - (2 * (by - ay)) * (xs - 2 * ax))
    inside = np.ones((bottom - top, right - left), dtype=bool)
    outside = np.ones_like(inside)
    for cross in signs:
        inside &= cross >= 0
        outside &= cross <= 0
    return inside | outside


def _line_mask(start: tuple[int, int], end: tuple[int, int], width: int, bounds: Bounds):
    left, top, right, bottom = bounds
    xs = 2 * np.arange(left, right, dtype=np.int64)[None, :] + 1
    ys = 2 * np.arange(top, bottom, dtype=np.int64)[:, None] + 1
    ax, ay = 2 * start[0] + 1, 2 * start[1] + 1
    bx, by = 2 * end[0] + 1, 2 * end[1] + 1
    dx, dy = bx - ax, by - ay
    px, py = xs - ax, ys - ay
    den = dx * dx + dy * dy
    if den == 0:
        return px * px + py * py <= width * width
    dot = px * dx + py * dy
    cross = px * dy - py * dx
    along = (dot >= 0) & (dot <= den)
    near_start = px * px + py * py <= width * width
    qx, qy = xs - bx, ys - by
    near_end = qx * qx + qy * qy <= width * width
    return (along & (cross * cross <= width * width * den)) | near_start | near_end


def _box_blur_axis(values: np.ndarray, radius: int, axis: int) -> np.ndarray:
    size = 2 * radius + 1
    pad = [(0, 0)] * values.ndim
    pad[axis] = (radius, radius)
    padded = np.pad(values, pad, mode="edge")
    zero_shape = list(padded.shape)
    zero_shape[axis] = 1
    sums = np.concatenate(
        [np.zeros(zero_shape, dtype=np.int64), np.cumsum(padded, axis=axis, dtype=np.int64)],
        axis=axis,
    )
    high = np.take(sums, range(size, size + values.shape[axis]), axis=axis)
    low = np.take(sums, range(0, values.shape[axis]), axis=axis)
    return (high - low + size // 2) // size


# --- the canvas -------------------------------------------------------------------------


class Canvas:
    """A mutable RGB canvas with integer drawing primitives that return their gold geometry.

    Width and height must satisfy the Images limits (:data:`jev_cookbook.vision.IMAGE_LIMITS`),
    so every canvas can be saved as a valid asset. Colours are ``(r, g, b)`` tuples or
    ``'#RRGGBB'`` strings. Every drawing method returns a :class:`Placed` whose bounds are the
    tight rectangle of the pixels that call changed, and raises ``ValueError`` if it changed
    none (so a gold box can never describe nothing).
    """

    def __init__(self, width: int = 640, height: int = 480, background: Any = PAPER) -> None:
        for name, side in (("width", width), ("height", height)):
            if isinstance(side, bool) or not isinstance(side, int):
                raise ValueError(f"{name} must be an integer")
            if not IMAGE_LIMITS["min_side"] <= side <= IMAGE_LIMITS["max_side"]:
                raise ValueError(
                    f"{name} {side} is outside {IMAGE_LIMITS['min_side']} to "
                    f"{IMAGE_LIMITS['max_side']} pixels"
                )
        if not IMAGE_LIMITS["min_area"] <= width * height <= IMAGE_LIMITS["max_area"]:
            raise ValueError(
                f"{width} x {height} is outside the {IMAGE_LIMITS['min_area']:,} to "
                f"{IMAGE_LIMITS['max_area']:,} pixel area limits"
            )
        self.width, self.height = width, height
        self.pixels = np.empty((height, width, 3), dtype=np.uint8)
        self.pixels[:, :] = _rgb(background)
        self.text_runs: list[TextRun] = []

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    # -- plumbing --

    def _bounds(self, bounds: Sequence[int]) -> Bounds:
        try:
            left, top, right, bottom = bounds
        except (TypeError, ValueError):
            raise ValueError("bounds must be (left, top, right, bottom)") from None
        if not all(
            isinstance(v, int) and not isinstance(v, bool) for v in (left, top, right, bottom)
        ):
            raise ValueError("bounds must be integers")
        if right <= left or bottom <= top:
            raise ValueError(f"bounds {tuple(bounds)} are empty or inverted")
        return left, top, right, bottom

    def _paint(self, bounds: Bounds, mask: np.ndarray, color: Color, name: str) -> Placed:
        left, top, right, bottom = bounds
        cl, ct, cr, cb = max(left, 0), max(top, 0), min(right, self.width), min(bottom, self.height)
        if cr <= cl or cb <= ct:
            raise ValueError(
                f"{name}: nothing of {bounds} lies on the {self.width}x{self.height} canvas"
            )
        mask = mask[ct - top : cb - top, cl - left : cr - left]
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        if rows.size == 0:
            raise ValueError(f"{name}: drew no pixels")
        self.pixels[ct:cb, cl:cr][mask] = color
        return Placed(
            name,
            (cl + int(cols[0]), ct + int(rows[0]), cl + int(cols[-1]) + 1, ct + int(rows[-1]) + 1),
            self.size,
        )

    def _changed(self, before: np.ndarray, name: str) -> Placed:
        diff = (self.pixels != before).any(axis=2)
        rows, cols = np.flatnonzero(diff.any(axis=1)), np.flatnonzero(diff.any(axis=0))
        if rows.size == 0:
            raise ValueError(f"{name}: changed no pixels")
        return Placed(
            name,
            (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1),
            self.size,
        )

    def _region(self, region: Sequence[int] | Placed | None) -> Bounds:
        if region is None:
            return 0, 0, self.width, self.height
        bounds = self._bounds(region.bounds if isinstance(region, Placed) else region)
        left, top, right, bottom = bounds
        clipped = max(left, 0), max(top, 0), min(right, self.width), min(bottom, self.height)
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            raise ValueError("region lies outside the canvas")
        return clipped

    # -- shapes --

    def rect(
        self,
        bounds: Sequence[int],
        fill: Any = None,
        *,
        outline: Any = None,
        outline_width: int = 2,
        radius: int = 0,
        name: str = "rect",
    ) -> Placed:
        """A (rounded) rectangle, filled, outlined or both. Returns the bounds of its pixels."""
        left, top, right, bottom = bounds = self._bounds(bounds)
        w, h = right - left, bottom - top
        shape = _round_rect_mask(w, h, radius)
        placed = None
        if fill is not None:
            placed = self._paint(bounds, shape, _rgb(fill), name)
        if outline is not None:
            if outline_width < 1 or 2 * outline_width >= min(w, h):
                raise ValueError("outline_width must be at least 1 and under half the shorter side")
            inner = np.zeros_like(shape)
            iw, ih = w - 2 * outline_width, h - 2 * outline_width
            inner[outline_width : outline_width + ih, outline_width : outline_width + iw] = (
                _round_rect_mask(iw, ih, max(0, radius - outline_width))
            )
            ring = self._paint(bounds, shape & ~inner, _rgb(outline), name)
            placed = ring if placed is None else Placed.union(name, placed, ring)
        if placed is None:
            raise ValueError("rect needs a fill, an outline or both")
        return placed

    def ellipse(
        self,
        bounds: Sequence[int],
        fill: Any = None,
        *,
        outline: Any = None,
        outline_width: int = 2,
        name: str = "ellipse",
    ) -> Placed:
        """An ellipse inscribed in ``bounds``, filled, outlined or both."""
        left, top, right, bottom = bounds = self._bounds(bounds)
        w, h = right - left, bottom - top
        shape = _ellipse_mask(w, h)
        placed = None
        if fill is not None:
            placed = self._paint(bounds, shape, _rgb(fill), name)
        if outline is not None:
            if outline_width < 1 or 2 * outline_width >= min(w, h):
                raise ValueError("outline_width must be at least 1 and under half the shorter side")
            inner = np.zeros_like(shape)
            iw, ih = w - 2 * outline_width, h - 2 * outline_width
            inner[outline_width : outline_width + ih, outline_width : outline_width + iw] = (
                _ellipse_mask(iw, ih)
            )
            ring = self._paint(bounds, shape & ~inner, _rgb(outline), name)
            placed = ring if placed is None else Placed.union(name, placed, ring)
        if placed is None:
            raise ValueError("ellipse needs a fill, an outline or both")
        return placed

    def polygon(
        self, points: Sequence[tuple[int, int]], fill: Any, *, name: str = "polygon"
    ) -> Placed:
        """A filled convex polygon (three or more integer vertices, either winding)."""
        pts = [(int(x), int(y)) for x, y in points]
        if len(pts) < 3:
            raise ValueError("a polygon needs at least three vertices")
        turns = []
        for i in range(len(pts)):
            a, b, c = pts[i], pts[(i + 1) % len(pts)], pts[(i + 2) % len(pts)]
            turns.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
        if any(t > 0 for t in turns) and any(t < 0 for t in turns):
            raise ValueError("polygon must be convex")
        bounds = (
            min(x for x, _ in pts),
            min(y for _, y in pts),
            max(x for x, _ in pts) + 1,
            max(y for _, y in pts) + 1,
        )
        return self._paint(bounds, _polygon_mask(pts, bounds), _rgb(fill), name)

    def line(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        color: Any,
        width: int = 3,
        *,
        name: str = "line",
    ) -> Placed:
        """A straight segment ``width`` pixels thick with round ends."""
        if isinstance(width, bool) or not isinstance(width, int) or width < 1:
            raise ValueError("line width must be a positive integer")
        pad = width // 2 + 2
        bounds = (
            min(start[0], end[0]) - pad,
            min(start[1], end[1]) - pad,
            max(start[0], end[0]) + pad + 1,
            max(start[1], end[1]) + pad + 1,
        )
        return self._paint(bounds, _line_mask(start, end, width, bounds), _rgb(color), name)

    def polyline(
        self,
        points: Sequence[tuple[int, int]],
        color: Any,
        width: int = 3,
        *,
        name: str = "polyline",
    ) -> Placed:
        if len(points) < 2:
            raise ValueError("a polyline needs at least two points")
        parts = [
            self.line(points[i], points[i + 1], color, width, name=name)
            for i in range(len(points) - 1)
        ]
        return Placed.union(name, *parts)

    # -- text --

    def text(
        self,
        xy: tuple[int, int],
        text: str,
        *,
        scale: int = 3,
        color: Any = INK,
        name: str = "text",
        min_contrast: float = 3.0,
    ) -> Placed:
        """Draw ``text`` with its top-left layout corner at ``xy``; return the ink bounds.

        The whole string must lie on the canvas, ``scale`` must be at least
        :data:`MIN_TEXT_SCALE`, and the colour must contrast with the pixels beneath it by at
        least ``min_contrast`` (WCAG ratio, per-channel median of the area), so the text is
        readable by construction.
        """
        folded = _fold(text)
        mask = _text_mask(folded, scale)
        x, y = xy
        h, w = mask.shape
        if x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            raise ValueError(f"text {folded!r} ({w}x{h}) does not fit on the canvas at {xy}")
        rgb = _rgb(color)
        under = self.pixels[y : y + h, x : x + w].reshape(-1, 3)
        background = tuple(int(v) for v in np.median(under, axis=0))
        ratio = contrast_ratio(rgb, background)
        if ratio < min_contrast:
            raise ValueError(
                f"text {folded!r} has contrast {ratio:.2f} against its background; "
                f"need at least {min_contrast}"
            )
        placed = self._paint((x, y, x + w, y + h), mask, rgb, name)
        self.text_runs.append(TextRun(folded, (x, y), scale, rgb, placed))
        return placed

    def text_centered(self, center: tuple[int, int], text: str, **kwargs: Any) -> Placed:
        """Like :meth:`text`, with the layout box centred on ``center``."""
        w, h = text_size(text, kwargs.get("scale", 3))
        return self.text((center[0] - w // 2, center[1] - h // 2), text, **kwargs)

    def text_block(
        self,
        xy: tuple[int, int],
        text: str,
        *,
        max_width: int,
        scale: int = 3,
        color: Any = INK,
        line_gap: int = 6,
        name: str = "text_block",
    ) -> tuple[Placed, list[Placed]]:
        """Wrapped text. Returns the block's bounds and one :class:`Placed` per line."""
        lines = wrap_text(text, scale, max_width)
        step = GLYPH_HEIGHT * scale + line_gap
        placed = [
            self.text((xy[0], xy[1] + i * step), line, scale=scale, color=color, name=f"{name}_{i}")
            for i, line in enumerate(lines)
        ]
        return Placed.union(name, *placed), placed

    # -- defects --

    def erase(self, part: Placed, fill: Any, *, name: str = "missing_part") -> Placed:
        """Paint ``fill`` over a part's rectangle so the part is missing; return that rectangle."""
        left, top, right, bottom = part.bounds
        self.pixels[top:bottom, left:right] = _rgb(fill)
        return Placed(name, part.bounds, self.size)

    def scratch(
        self,
        within: Placed,
        seed: int,
        *,
        color: Any = (70, 72, 78),
        width: int = 2,
        segments: int = 7,
        name: str = "scratch",
    ) -> Placed:
        """A thin jagged scratch wholly inside ``within`` (a polyline from a seeded walk)."""
        rng = Rng(seed)
        left, top, right, bottom = within.bounds
        margin = width + 3
        if right - left < 6 * margin or bottom - top < 6 * margin:
            raise ValueError("the target is too small for a scratch")
        xs = np.linspace(left + margin, right - margin, segments + 1).astype(int).tolist()
        y = rng.integer(top + margin, bottom - margin - 1)
        points = []
        for x in xs:
            points.append((x, y))
            y = min(max(y + rng.integer(-24, 24), top + margin), bottom - margin - 1)
        if rng.integer(0, 1):
            points.reverse()
        return self.polyline(points, color, width, name=name)

    def dent(self, within: Placed, *, strength: int = 70, name: str = "dent") -> Placed:
        """Shade an ellipse in ``within`` lighter on one side and darker on the other."""
        left, top, right, bottom = within.bounds
        w, h = right - left, bottom - top
        before = self.pixels.copy()
        ellipse = _ellipse_mask(w, h)
        xs = (2 * np.arange(w, dtype=np.int64) + 1 - w)[None, :]
        delta = (-xs * strength) // w
        region = self.pixels[top:bottom, left:right].astype(np.int64)
        shaded = np.clip(region + delta[:, :, None], 0, 255).astype(np.uint8)
        region_view = self.pixels[top:bottom, left:right]
        region_view[ellipse] = shaded[ellipse]
        return self._changed(before, name)

    # -- perturbations --

    def blur(
        self, radius: int = 2, *, passes: int = 2, region: Any = None, name: str = "blur"
    ) -> Placed:
        """Integer box blur (``passes`` times) of ``region``; returns the pixels it changed."""
        if radius < 1 or passes < 1:
            raise ValueError("radius and passes must be positive")
        left, top, right, bottom = self._region(region)
        before = self.pixels.copy()
        patch = self.pixels[top:bottom, left:right].astype(np.int64)
        for _ in range(passes):
            patch = _box_blur_axis(_box_blur_axis(patch, radius, 0), radius, 1)
        self.pixels[top:bottom, left:right] = patch.astype(np.uint8)
        return self._changed(before, name)

    def noise(
        self,
        amplitude: int,
        seed: int,
        *,
        region: Any = None,
        color_noise: bool = False,
        name: str = "noise",
    ) -> Placed:
        """Add uniform integer noise in ``[-amplitude, amplitude]`` (grey unless ``color_noise``).

        Noisy images compress badly: a full 640 x 480 canvas of noise is close to the 1 MiB cap.
        Prefer a ``region`` or a small amplitude.
        """
        if not 1 <= amplitude <= 127:
            raise ValueError("amplitude must be 1 to 127")
        left, top, right, bottom = self._region(region)
        h, w = bottom - top, right - left
        channels = 3 if color_noise else 1
        raw = _u64_array(seed, h * w * channels)
        delta = (raw % np.uint64(2 * amplitude + 1)).astype(np.int64) - amplitude
        delta = delta.reshape(h, w, channels)
        before = self.pixels.copy()
        patch = self.pixels[top:bottom, left:right].astype(np.int64) + delta
        self.pixels[top:bottom, left:right] = np.clip(patch, 0, 255).astype(np.uint8)
        return self._changed(before, name)

    def lighting(
        self,
        strength: int,
        direction: str = "left",
        *,
        region: Any = None,
        name: str = "lighting",
    ) -> Placed:
        """Uneven light: ``strength`` percent brighter on the lit side, darker on the far side.

        ``direction`` is ``left``, ``right``, ``top``, ``bottom`` (the lit side) or
        ``vignette`` (bright centre). A negative ``strength`` dims instead.
        """
        if not -100 <= strength <= 100 or strength == 0:
            raise ValueError("strength must be a nonzero integer from -100 to 100")
        left, top, right, bottom = self._region(region)
        h, w = bottom - top, right - left
        if direction in ("left", "right"):
            pos = np.arange(w, dtype=np.int64)[None, :] * 1000 // max(w - 1, 1)
            pos = np.broadcast_to(pos, (h, w))
            pos = pos if direction == "left" else 1000 - pos
            ramp = 1000 - 2 * pos
        elif direction in ("top", "bottom"):
            pos = np.arange(h, dtype=np.int64)[:, None] * 1000 // max(h - 1, 1)
            pos = np.broadcast_to(pos, (h, w))
            pos = pos if direction == "top" else 1000 - pos
            ramp = 1000 - 2 * pos
        elif direction == "vignette":
            dx = (2 * np.arange(w, dtype=np.int64) + 1 - w)[None, :] * 1000 // w
            dy = (2 * np.arange(h, dtype=np.int64) + 1 - h)[:, None] * 1000 // h
            ramp = 1000 - np.minimum((dx * dx + dy * dy) // 1000, 2000)
        else:
            raise ValueError("direction must be left, right, top, bottom or vignette")
        factor = 256 + strength * 256 * ramp // 100_000
        before = self.pixels.copy()
        patch = self.pixels[top:bottom, left:right].astype(np.int64)
        patch = (patch * factor[:, :, None] + 128) >> 8
        self.pixels[top:bottom, left:right] = np.clip(patch, 0, 255).astype(np.uint8)
        return self._changed(before, name)

    def dim(self, percent: int, *, region: Any = None, name: str = "dim") -> Placed:
        """Darken ``region`` by ``percent`` (a modal overlay's scrim)."""
        if not 1 <= percent <= 95:
            raise ValueError("percent must be 1 to 95")
        left, top, right, bottom = self._region(region)
        before = self.pixels.copy()
        patch = self.pixels[top:bottom, left:right].astype(np.int64)
        self.pixels[top:bottom, left:right] = ((patch * (100 - percent) + 50) // 100).astype(
            np.uint8
        )
        return self._changed(before, name)

    def occlude(
        self, bounds: Sequence[int] | Placed, color: Any = (60, 60, 64), *, name: str = "occluder"
    ) -> Placed:
        """Cover a rectangle with a flat block (partial occlusion for hard cases)."""
        raw = bounds.bounds if isinstance(bounds, Placed) else bounds
        return self.rect(raw, color, name=name)

    # -- finishing --

    def finish(
        self,
        generator: str,
        parameters: Mapping[str, Any],
        seed: int,
        elements: Mapping[str, Placed],
    ) -> SyntheticImage:
        data = {
            "origin": "generated",
            "generator": f"jev_cookbook.synthetic_images.{generator}",
            "generator_version": GENERATOR_VERSION,
            "seed": _check_seed(seed),
            "parameters": json.loads(json.dumps(parameters)),
        }
        pixels = self.pixels.copy()
        pixels.setflags(write=False)
        return SyntheticImage(pixels, MappingProxyType(dict(elements)), tuple(self.text_runs), data)


# --- the PNG encoder --------------------------------------------------------------------


def _fixed_huffman_tables() -> tuple[list[tuple[int, int]], dict[int, tuple[int, int, int]]]:
    def reverse(code: int, bits: int) -> int:
        return int(format(code, f"0{bits}b")[::-1], 2)

    symbols: list[tuple[int, int]] = []
    for sym in range(288):
        if sym < 144:
            code, bits = 0x30 + sym, 8
        elif sym < 256:
            code, bits = 0x190 + sym - 144, 9
        elif sym < 280:
            code, bits = sym - 256, 7
        else:
            code, bits = 0xC0 + sym - 280, 8
        symbols.append((reverse(code, bits), bits))
    base = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31]
    base += [35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258]
    extra = [0] * 8 + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [5] * 4 + [0]
    lengths: dict[int, tuple[int, int, int]] = {}
    for length in range(3, 259):
        index = max(i for i, b in enumerate(base) if b <= length)
        if length == 258:
            index = 28
        lengths[length] = (257 + index, extra[index], length - base[index])
    return symbols, lengths


_SYMBOLS, _LENGTHS = _fixed_huffman_tables()
_DISTANCE_3 = (int(format(2, "05b")[::-1], 2), 5)  # fixed 5-bit distance code 2 means distance 3


def _deflate_runs(data: bytes) -> bytes:
    """A raw deflate stream: fixed Huffman, matches only at distance 3 (one RGB pixel back).

    Long flat areas become matches of up to 258 bytes; everything else is literal. The stream
    is a pure function of ``data``, unlike zlib's, whose output depends on its version.
    """
    out = bytearray()
    acc = 3  # BFINAL = 1, BTYPE = 01 (fixed Huffman), written least significant bit first
    nbits = 3
    symbols, lengths = _SYMBOLS, _LENGTHS
    n = len(data)
    array = np.frombuffer(data, dtype=np.uint8)
    # break_at[k] is True where byte k (k >= 3) differs from the byte three before it.
    breaks = (np.flatnonzero(array[3:] != array[:-3]) + 3).tolist() if n > 3 else []
    from bisect import bisect_left

    def put(code: int, bits: int) -> None:
        nonlocal acc, nbits
        acc |= code << nbits
        nbits += bits
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8

    i = 0
    while i < n:
        if i >= 3 and data[i] == data[i - 3]:
            at = bisect_left(breaks, i)
            end = breaks[at] if at < len(breaks) else n
            run = end - i
            if run >= 3:
                while run > 0:
                    take = min(run, 258)
                    if 0 < run - take < 3:
                        take -= 3 - (run - take)
                    symbol, extra_bits, extra_value = lengths[take]
                    put(*symbols[symbol])
                    if extra_bits:
                        put(extra_value, extra_bits)
                    put(*_DISTANCE_3)
                    run -= take
                i = end
                continue
            for k in range(i, end):
                put(*symbols[data[k]])
            i = end
            continue
        put(*symbols[data[i]])
        i += 1
    put(*symbols[256])
    if nbits:
        out.append(acc & 0xFF)
    return bytes(out)


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def encode_png(pixels: np.ndarray) -> bytes:
    """Encode an ``(height, width, 3)`` uint8 array as an 8-bit RGB PNG, deterministically.

    The file holds exactly ``IHDR``, one ``IDAT`` and ``IEND``: no text, time, colour-profile or
    physical-size chunk, so it passes ``tools/check_recipe_assets.py`` by construction. Rows use
    the PNG "Up" filter and a pure-Python fixed-Huffman deflate stream, so the bytes do not
    depend on the zlib that ``zlib.compress`` or Pillow link against.
    """
    array = np.asarray(pixels)
    if array.ndim != 3 or array.shape[2] != 3 or array.dtype != np.uint8:
        raise ValueError("pixels must be a uint8 array of shape (height, width, 3)")
    height, width = array.shape[:2]
    rows = array.reshape(height, width * 3).astype(np.int16)
    above = np.vstack([np.zeros((1, width * 3), dtype=np.int16), rows[:-1]])
    filtered = np.empty((height, 1 + width * 3), dtype=np.uint8)
    filtered[:, 0] = 2
    filtered[:, 1:] = ((rows - above) & 0xFF).astype(np.uint8)
    raw = filtered.tobytes()
    stream = b"\x78\x01" + _deflate_runs(raw) + struct.pack(">I", zlib.adler32(raw))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", stream)
        + _chunk(b"IEND", b"")
    )


# --- finished images, saving and the byte-stability policy ------------------------------


@dataclass(frozen=True)
class SyntheticImage:
    """Finished pixels, the named gold geometry of what was drawn, and provenance."""

    pixels: np.ndarray
    elements: Mapping[str, Placed]
    text_runs: tuple[TextRun, ...]
    provenance: dict[str, Any]

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    def png_bytes(self) -> bytes:
        return encode_png(self.pixels)

    def sha256(self) -> str:
        return hashlib.sha256(self.png_bytes()).hexdigest()

    def box(self, name: str) -> dict[str, float]:
        """The normalized gold box of the element called ``name``."""
        try:
            return self.elements[name].box
        except KeyError:
            raise KeyError(f"no element {name!r}; have {sorted(self.elements)}") from None

    def to_pil(self):
        """The pixels as a ``PIL.Image`` (for display or tests; saving goes through
        :func:`write_asset`, never ``Image.save``)."""
        from PIL import Image

        return Image.fromarray(np.array(self.pixels), "RGB")


class AssetMismatchError(Exception):
    """An existing asset differs from what the generator now produces. Nothing was rewritten."""


@dataclass(frozen=True)
class SavedImage:
    """A written (or verified) asset and the facts a manifest entry needs."""

    path: Path
    status: str  # "created", "identical" or "pixel-equal"
    sha256: str
    size_bytes: int
    width: int
    height: int
    provenance: dict[str, Any]

    def manifest_entry(self, relative_path: str | None = None) -> dict[str, Any]:
        """A flat provenance record for the assets manifest (#308).

        ``origin`` is ``generated``; ``generator`` names the function and ``generator_version``
        the module revision; ``seed`` and ``parameters`` reproduce the file. The key names are
        this module's, to be reconciled with #308's schema when that merges.
        """
        return {
            "path": relative_path if relative_path is not None else self.path.name,
            **self.provenance,
            "sha256": self.sha256,
            "bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
        }


def _decoded(data: bytes) -> np.ndarray:
    import io

    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        return np.array(image.convert("RGB"))


def compare_asset(path: str | Path, image: SyntheticImage) -> str:
    """``"identical"`` (same bytes), ``"pixel-equal"`` (same decoded pixels) or ``"different"``."""
    existing = Path(path).read_bytes()
    if existing == image.png_bytes():
        return "identical"
    try:
        same = np.array_equal(_decoded(existing), image.pixels)
    except Exception:  # an unreadable file is simply different
        return "different"
    return "pixel-equal" if same else "different"


def write_asset(image: SyntheticImage, path: str | Path) -> SavedImage:
    """Write ``image`` as a PNG asset, or verify the committed file; never replace one.

    ``path`` must end in a lowercase ``.png`` and sit under a folder named ``assets``
    (``recipes/<slug>/assets/`` for a recipe), and the encoded file must be within
    :data:`MAX_ASSET_BYTES`. A new file is written, re-read through
    :func:`jev_cookbook.vision.image_asset` and compared with the pixels. An existing file is
    compared (:func:`compare_asset`): ``"identical"`` and ``"pixel-equal"`` leave it alone,
    ``"different"`` raises :class:`AssetMismatchError`. Committed bytes are canonical, so a
    regeneration can never silently change a replay key.
    """
    target = Path(path)
    if target.suffix != ".png":
        raise ValueError(f"{target.name}: assets must use a lowercase .png suffix")
    if "assets" not in target.parent.parts:
        raise ValueError(f"{path}: an image may only be written under an 'assets' folder")
    data = image.png_bytes()
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError(
            f"{target.name}: {len(data):,} bytes exceeds the {MAX_ASSET_BYTES:,} byte cap; "
            "use a smaller canvas, less noise or fewer colours"
        )
    if target.exists():
        status = compare_asset(target, image)
        if status == "different":
            raise AssetMismatchError(
                f"{target} differs from what the generator produces now "
                f"(sha256 {image.sha256()[:12]}...). Committed bytes are canonical and were "
                "not changed; if the change is intended, bump GENERATOR_VERSION, delete the "
                "file and regenerate every dependent replay key on purpose."
            )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        status = "created"
        asset = image_asset(target)  # the same validation a recipe applies on load
        if (
            not np.array_equal(_decoded(target.read_bytes()), image.pixels)
            or asset["format"] != "png"
        ):
            target.unlink()
            raise AssetMismatchError(f"{target}: the written file did not decode to its pixels")
    return SavedImage(
        target,
        status,
        hashlib.sha256(data).hexdigest(),
        len(data),
        image.width,
        image.height,
        dict(image.provenance),
    )


# --- generators -------------------------------------------------------------------------

# (kind, level) pairs, applied in order after drawing: blur radius in pixels, noise amplitude,
# dim percent (uniform darkening), vignette and glare strength in percent.
PERTURBATIONS = ("blur", "noise", "dim", "vignette", "glare")


def _apply_perturbations(
    canvas: Canvas, perturbations: Sequence[tuple[str, int]], seed: int
) -> None:
    for index, item in enumerate(perturbations):
        kind, level = item
        if kind == "blur":
            canvas.blur(int(level))
        elif kind == "noise":
            canvas.noise(int(level), _derive(seed, 7, index))
        elif kind == "dim":
            canvas.dim(int(level))
        elif kind == "vignette":
            canvas.lighting(int(level), "vignette")
        elif kind == "glare":
            canvas.lighting(int(level), "top")
        else:
            raise ValueError(f"unknown perturbation {kind!r}; use one of {PERTURBATIONS}")


def _finish_scene(
    canvas: Canvas,
    generator: str,
    parameters: dict[str, Any],
    seed: int,
    elements: dict[str, Placed],
    perturbations: Sequence[tuple[str, int]],
    occlude: str | None,
) -> SyntheticImage:
    parameters = {
        **parameters,
        "perturbations": [list(p) for p in perturbations],
        "occlude": occlude,
    }
    if occlude is not None:
        if occlude not in elements:
            raise ValueError(f"no element {occlude!r} to occlude; have {sorted(elements)}")
        target = elements[occlude]
        left, top, right, bottom = target.bounds
        canvas.occlude((left + target.width // 2, top, right, bottom), name=f"{occlude}_occluder")
    _apply_perturbations(canvas, perturbations, seed)
    return canvas.finish(generator, parameters, seed, elements)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


_SHAPE_COLORS = (
    ("RED", (200, 50, 50)),
    ("BLUE", (40, 90, 200)),
    ("GREEN", (30, 140, 70)),
    ("AMBER", (230, 160, 20)),
    ("PURPLE", (120, 60, 160)),
    ("TEAL", (20, 140, 150)),
)
_SHAPE_KINDS = ("CIRCLE", "SQUARE", "TRIANGLE", "DIAMOND")


def shapes_scene(
    seed: int = 0,
    *,
    width: int = 640,
    height: int = 480,
    count: int = 5,
    perturbations: Sequence[tuple[str, int]] = (),
    occlude: str | None = None,
) -> SyntheticImage:
    """Labelled coloured shapes on a plain background, one per grid cell, in a seeded order.

    Elements are ``<color>_<kind>`` (the shape, the gold box) and ``label_<color>_<kind>``.
    """
    if not 1 <= count <= len(_SHAPE_COLORS):
        raise ValueError(f"count must be 1 to {len(_SHAPE_COLORS)}")
    rng = Rng(seed)
    canvas = Canvas(width, height)
    cols = min(count, 3)
    rows = -(-count // cols)
    cell_w, cell_h = width // cols, height // rows
    size = min(cell_w - 40, cell_h - 14 - 8 - 24)
    if size < 48:
        raise ValueError("canvas too small for that many shapes")
    colors = rng.shuffled(_SHAPE_COLORS)[:count]
    cells = rng.shuffled(range(cols * rows))[:count]
    kinds = rng.shuffled(_SHAPE_KINDS)
    elements: dict[str, Placed] = {}
    for i, ((color_name, rgb), cell) in enumerate(zip(colors, cells, strict=True)):
        kind = kinds[i % 4]
        cx0, cy0 = (cell % cols) * cell_w, (cell // cols) * cell_h
        slack_x, slack_y = cell_w - size, cell_h - size - 22
        left = cx0 + rng.integer(slack_x // 4, slack_x - slack_x // 4)
        top = cy0 + rng.integer(12, max(12, slack_y // 2))
        b = (left, top, left + size, top + size)
        name = f"{color_name.lower()}_{kind.lower()}"
        if kind == "CIRCLE":
            elements[name] = canvas.ellipse(b, rgb, name=name)
        elif kind == "SQUARE":
            elements[name] = canvas.rect(b, rgb, name=name)
        elif kind == "TRIANGLE":
            pts = [
                (left + size // 2, top),
                (left + size - 1, top + size - 1),
                (left, top + size - 1),
            ]
            elements[name] = canvas.polygon(pts, rgb, name=name)
        else:
            mid_x, mid_y = left + size // 2, top + size // 2
            pts = [(mid_x, top), (left + size - 1, mid_y), (mid_x, top + size - 1), (left, mid_y)]
            elements[name] = canvas.polygon(pts, rgb, name=name)
        label = f"{color_name} {kind}"
        lw, _ = text_size(label, 2)
        if lw > cell_w - 8:
            raise ValueError("canvas too narrow for the shape labels")
        elements[f"label_{name}"] = canvas.text(
            (left + size // 2 - lw // 2, top + size + 8), label, scale=2, name=f"label_{name}"
        )
    return _finish_scene(
        canvas,
        "shapes_scene",
        {"width": width, "height": height, "count": count},
        seed,
        elements,
        perturbations,
        occlude,
    )


_THEMES = (
    {"desktop": (205, 214, 232), "accent": (35, 82, 160)},
    {"desktop": (214, 230, 214), "accent": (28, 110, 78)},
    {"desktop": (236, 220, 206), "accent": (150, 70, 40)},
    {"desktop": (222, 212, 234), "accent": (95, 52, 150)},
)


def ui_mock(
    seed: int = 0,
    *,
    width: int = 800,
    height: int = 560,
    title: str = "ORBITAL DESK",
    buttons: Sequence[str] = ("SAVE", "CANCEL"),
    fields: Sequence[str] = ("NAME", "EMAIL"),
    error: str | None = None,
    dialog: str | None = None,
    spinner: bool = False,
    perturbations: Sequence[tuple[str, int]] = (),
    occlude: str | None = None,
) -> SyntheticImage:
    """A fictional application window: title bar, labelled inputs, buttons and optional states.

    ``error`` adds a red banner under the title bar, ``spinner`` a dotted activity ring and
    ``dialog`` dims the window and opens a modal box with an OK button. The seed picks the
    colour theme and a small window offset. Elements: ``window``, ``title_bar``, ``title``,
    ``close_button``, ``input_<field>`` and ``label_<field>``, ``button_<label>``,
    ``error_banner``, ``spinner``, ``dialog``, ``dialog_message`` and ``dialog_button``.
    """
    if len(fields) > 3 or len(buttons) > 3:
        raise ValueError("at most three fields and three buttons")
    rng = Rng(seed)
    theme = rng.choice(_THEMES)
    jitter = rng.integer(0, 8)
    canvas = Canvas(width, height, theme["desktop"])
    m = 24 + jitter
    el: dict[str, Placed] = {}
    el["window"] = canvas.rect(
        (m, m, width - m, height - m), WHITE, outline=GRAY, radius=8, name="window"
    )
    win_l, win_t, win_r, win_b = el["window"].bounds
    el["title_bar"] = canvas.rect(
        (win_l + 2, win_t + 2, win_r - 2, win_t + 46), theme["accent"], radius=6, name="title_bar"
    )
    el["title"] = canvas.text((win_l + 20, win_t + 14), title, scale=3, color=WHITE, name="title")
    el["close_button"] = canvas.rect(
        (win_r - 50, win_t + 8, win_r - 14, win_t + 40),
        (230, 232, 238),
        radius=4,
        name="close_button",
    )
    canvas.text_centered((win_r - 32, win_t + 24), "X", scale=3, color=INK, name="close_mark")
    y = win_t + 62
    if error is not None:
        el["error_banner"] = canvas.rect(
            (win_l + 20, y, win_r - 20, y + 48), RED, radius=4, name="error_banner"
        )
        canvas.text((win_l + 34, y + 13), error, scale=3, color=WHITE, name="error_text")
        y += 64
    field_right = win_l + (win_r - win_l) * 11 // 20
    for field in fields:
        slug = _slug(field)
        el[f"label_{slug}"] = canvas.text(
            (win_l + 20, y), field, scale=2, color=INK, name=f"label_{slug}"
        )
        el[f"input_{slug}"] = canvas.rect(
            (win_l + 20, y + 22, field_right, y + 66),
            WHITE,
            outline=MIDGRAY,
            radius=3,
            name=f"input_{slug}",
        )
        canvas.text((win_l + 32, y + 36), "TYPE HERE", scale=2, color=MIDGRAY, name=f"hint_{slug}")
        y += 88
    button_top = win_b - 24 - 48
    if y > button_top - 8:
        raise ValueError("canvas too short for that many fields")
    x = win_l + 20
    for index, label in enumerate(buttons):
        slug = _slug(label)
        bw = text_size(label, 3)[0] + 40
        primary = index == 0
        el[f"button_{slug}"] = canvas.rect(
            (x, button_top, x + bw, button_top + 48),
            theme["accent"] if primary else LIGHTGRAY,
            outline=None if primary else GRAY,
            radius=6,
            name=f"button_{slug}",
        )
        canvas.text_centered(
            (x + bw // 2, button_top + 24),
            label,
            scale=3,
            color=WHITE if primary else INK,
            name=f"label_button_{slug}",
        )
        x += bw + 16
    if spinner:
        cx, cy = win_r - 110, win_t + 190
        dots = []
        for k in range(8):
            ang = k * math.pi / 4
            px, py = cx + round(40 * math.cos(ang)), cy + round(40 * math.sin(ang))
            shade = 60 + 24 * k
            dots.append(
                canvas.ellipse(
                    (px - 7, py - 7, px + 7, py + 7), (shade, shade, shade + 20), name="dot"
                )
            )
        el["spinner"] = Placed.union("spinner", *dots)
    if dialog is not None:
        canvas.dim(55, name="scrim")
        dw, dh = min(460, width - 160), 230
        dl, dt = (width - dw) // 2, (height - dh) // 2
        el["dialog"] = canvas.rect(
            (dl, dt, dl + dw, dt + dh), WHITE, outline=INK, radius=8, name="dialog"
        )
        el["dialog_message"], _ = canvas.text_block(
            (dl + 24, dt + 28), dialog, max_width=dw - 48, scale=3, name="dialog_message"
        )
        el["dialog_button"] = canvas.rect(
            (dl + dw // 2 - 50, dt + dh - 70, dl + dw // 2 + 50, dt + dh - 22),
            theme["accent"],
            radius=6,
            name="dialog_button",
        )
        canvas.text_centered(
            (dl + dw // 2, dt + dh - 46), "OK", scale=3, color=WHITE, name="label_ok"
        )
    return _finish_scene(
        canvas,
        "ui_mock",
        {
            "width": width,
            "height": height,
            "title": title,
            "buttons": list(buttons),
            "fields": list(fields),
            "error": error,
            "dialog": dialog,
            "spinner": spinner,
        },
        seed,
        el,
        perturbations,
        occlude,
    )


def wordmark(
    seed: int = 0,
    *,
    brand: str | None = None,
    width: int = 640,
    height: int = 280,
    variant: int | None = None,
    perturbations: Sequence[tuple[str, int]] = (),
    occlude: str | None = None,
) -> SyntheticImage:
    """A fictional logo: a geometric emblem beside an invented wordmark.

    ``brand`` defaults to a seeded pick from :data:`FICTIONAL_BRANDS`; ``variant`` (0 to 2)
    picks the emblem. Elements: ``emblem``, ``wordmark`` and ``logo`` (both).
    """
    rng = Rng(seed)
    name = brand if brand is not None else rng.choice(FICTIONAL_BRANDS)
    variant = rng.integer(0, 2) if variant is None else variant
    if variant not in (0, 1, 2):
        raise ValueError("variant must be 0, 1 or 2")
    hue = rng.choice(_SHAPE_COLORS)[1]
    canvas = Canvas(width, height, WHITE)
    scale = 6
    tw, th = text_size(name, scale)
    emblem_size = 120
    gap = 28
    total = emblem_size + gap + tw
    if total > width - 40:
        scale = 4
        tw, th = text_size(name, scale)
        total = emblem_size + gap + tw
        if total > width - 40:
            raise ValueError("brand name too long for this width")
    left = (width - total) // 2
    top = (height - emblem_size) // 2
    b = (left, top, left + emblem_size, top + emblem_size)
    if variant == 0:
        parts = [
            canvas.ellipse(b, hue, name="emblem"),
            canvas.polygon(
                [(left + 36, top + 30), (left + 92, top + 60), (left + 36, top + 90)],
                WHITE,
                name="inner",
            ),
        ]
    elif variant == 1:
        parts = [
            canvas.rect(b, hue, radius=24, name="emblem"),
            canvas.polygon(
                [
                    (left + 60, top + 24),
                    (left + 96, top + 60),
                    (left + 60, top + 96),
                    (left + 24, top + 60),
                ],
                WHITE,
                name="inner",
            ),
        ]
    else:
        parts = [
            canvas.ellipse((left, top, left + 90, top + 90), hue, name="emblem"),
            canvas.ellipse((left + 30, top + 30, left + 120, top + 120), INK, name="emblem"),
        ]
    el = {"emblem": Placed.union("emblem", *parts)}
    el["wordmark"] = canvas.text(
        (left + emblem_size + gap, top + (emblem_size - th) // 2),
        name,
        scale=scale,
        color=INK,
        name="wordmark",
    )
    el["logo"] = Placed.union("logo", el["emblem"], el["wordmark"])
    return _finish_scene(
        canvas,
        "wordmark",
        {"width": width, "height": height, "brand": name, "variant": variant},
        seed,
        el,
        perturbations,
        occlude,
    )


_BODY_SENTENCES = (
    "ITEMS WERE COUNTED AND SEALED AT THE NORTH DOCK.",
    "THE CARRIER ARRIVED AT NINE AND LEFT AT TEN.",
    "TWELVE CRATES WERE ACCEPTED, ONE WAS RETURNED.",
    "STORE THIS NOTE WITH THE WEEKLY LEDGER.",
)


def document_page(
    seed: int = 0,
    *,
    width: int = 640,
    height: int = 800,
    title: str = "DELIVERY NOTE",
    organisation: str = "QUILLEN WORKS",
    stamp: str | None = "APPROVED",
    signature: bool = True,
    perturbations: Sequence[tuple[str, int]] = (),
    occlude: str | None = None,
) -> SyntheticImage:
    """A fictional form: header, wrapped body text, a signature scribble and a stamp.

    Elements: ``header``, ``title``, ``body`` (and ``line_<i>``), ``signature``,
    ``signature_label`` and ``stamp`` when requested.
    """
    rng = Rng(seed)
    canvas = Canvas(width, height, WHITE)
    el: dict[str, Placed] = {}
    el["header"] = canvas.rect((0, 0, width, 70), (40, 52, 84), name="header")
    canvas.text((24, 24), organisation, scale=3, color=WHITE, name="organisation")
    el["title"] = canvas.text((24, 100), title, scale=4, color=INK, name="title")
    sentences = rng.shuffled(_BODY_SENTENCES)[:3]
    el["body"], lines = canvas.text_block(
        (24, 160), " ".join(sentences), max_width=width - 48, scale=2, name="line"
    )
    for i, line in enumerate(lines):
        el[f"line_{i}"] = line
    y = 160 + len(lines) * 20 + 60
    canvas.line((24, y + 70), (width // 2, y + 70), INK, 2, name="rule")
    el["signature_label"] = canvas.text(
        (24, y + 82), "SIGNED", scale=2, color=INK, name="signature_label"
    )
    if signature:
        points = []
        for k in range(9):
            points.append((40 + k * 24, y + 30 + rng.integer(-14, 14) + (k % 2) * 16))
        el["signature"] = canvas.polyline(points, (20, 40, 130), 3, name="signature")
    if stamp is not None:
        sw = text_size(stamp, 3)[0] + 40
        sl, st = width - sw - 40, y - 10
        frame = canvas.rect(
            (sl, st, sl + sw, st + 70), outline=RED, outline_width=4, radius=6, name="stamp"
        )
        canvas.text_centered((sl + sw // 2, st + 35), stamp, scale=3, color=RED, name="stamp_text")
        el["stamp"] = frame
    return _finish_scene(
        canvas,
        "document_page",
        {
            "width": width,
            "height": height,
            "title": title,
            "organisation": organisation,
            "stamp": stamp,
            "signature": signature,
        },
        seed,
        el,
        perturbations,
        occlude,
    )


_PRODUCT_COLORS = ((200, 70, 70), (60, 110, 200), (60, 150, 90), (225, 165, 40), (130, 80, 170))


def product_shelf(
    seed: int = 0,
    *,
    width: int = 800,
    height: int = 480,
    count: int = 4,
    gaps: Sequence[int] = (),
    perturbations: Sequence[tuple[str, int]] = (),
    occlude: str | None = None,
) -> SyntheticImage:
    """A shelf of invented products (box, bottle, can) with brand labels and price tags.

    ``gaps`` lists slot indexes left empty. Elements: ``product_<i>`` for stocked slots (the
    gold box), ``gap_<i>`` for empty ones (the slot's layout rectangle, not painted pixels),
    ``price_<i>`` and ``brand_<i>``.
    """
    if not 2 <= count <= 6:
        raise ValueError("count must be 2 to 6")
    if any(g < 0 or g >= count for g in gaps):
        raise ValueError("gap indexes must be within the slot count")
    rng = Rng(seed)
    canvas = Canvas(width, height, (232, 230, 224))
    shelf_top = height - 110
    canvas.rect((0, shelf_top, width, shelf_top + 26), (120, 90, 60), name="plank")
    canvas.rect((0, shelf_top + 26, width, height), (200, 196, 188), name="fascia")
    slot_w = width // count
    el: dict[str, Placed] = {}
    for i in range(count):
        left = i * slot_w
        right = left + slot_w
        price = f"${rng.integer(1, 9)}.{rng.integer(0, 99):02d}"
        pw = text_size(price, 3)[0] + 20
        pcx = (left + right) // 2
        canvas.rect(
            (pcx - pw // 2, shelf_top + 40, pcx + pw // 2, shelf_top + 84),
            WHITE,
            outline=GRAY,
            name="tag",
        )
        el[f"price_{i}"] = canvas.text_centered(
            (pcx, shelf_top + 62), price, scale=3, name=f"price_{i}"
        )
        pl, pr = left + 14, right - 14
        slot = Placed(f"gap_{i}", (pl, 40, pr, shelf_top), canvas.size)
        brand = FICTIONAL_BRANDS[rng.integer(0, len(FICTIONAL_BRANDS) - 1)]
        kind = rng.choice(("box", "bottle", "can"))
        color = rng.choice(_PRODUCT_COLORS)
        if i in gaps:
            el[f"gap_{i}"] = slot
            continue
        top = rng.integer(60, 100)
        parts: list[Placed] = []
        if kind == "bottle":
            neck_l = pcx - (pr - pl) // 8
            parts.append(
                canvas.rect((neck_l, top, pcx + (pr - pl) // 8, top + 40), color, name="neck")
            )
            parts.append(
                canvas.rect((neck_l - 2, top - 14, pcx + (pr - pl) // 8 + 2, top), INK, name="cap")
            )
            body = canvas.rect((pl + 6, top + 30, pr - 6, shelf_top), color, radius=22, name="body")
        elif kind == "can":
            body = canvas.rect((pl + 6, top + 20, pr - 6, shelf_top), color, radius=10, name="body")
            parts.append(
                canvas.rect(
                    (pl + 10, top + 14, pr - 10, top + 30), (210, 212, 216), radius=6, name="lid"
                )
            )
        else:
            body = canvas.rect(
                (pl, top + 10, pr, shelf_top),
                color,
                outline=INK,
                outline_width=2,
                radius=4,
                name="body",
            )
        parts.append(body)
        band_t = body.bounds[1] + body.height // 2 - 28
        band = canvas.rect(
            (body.bounds[0] + 4, band_t, body.bounds[2] - 4, band_t + 56), WHITE, name="band"
        )
        scale = 3 if text_size(brand, 3)[0] <= band.width - 8 else 2
        if text_size(brand, scale)[0] > band.width - 4:
            raise ValueError("canvas too narrow for the brand labels; use fewer products")
        el[f"brand_{i}"] = canvas.text_centered(band.center, brand, scale=scale, name=f"brand_{i}")
        el[f"product_{i}"] = Placed.union(f"product_{i}", *parts, band)
    return _finish_scene(
        canvas,
        "product_shelf",
        {"width": width, "height": height, "count": count, "gaps": sorted(gaps)},
        seed,
        el,
        perturbations,
        occlude,
    )


def defect_panel(
    seed: int = 0,
    *,
    width: int = 640,
    height: int = 480,
    defect: str | None = "scratch",
    perturbations: Sequence[tuple[str, int]] = (),
    occlude: str | None = None,
) -> SyntheticImage:
    """A metal-coloured plate with four bolts and a part number, optionally defective.

    ``defect`` is ``None``, ``"scratch"``, ``"dent"`` or ``"missing_part"`` (one bolt absent).
    Elements: ``part``, ``bolt_<i>``, ``label_plate`` and, when defective, ``defect`` (the gold
    box derived from the pixels the defect changed).
    """
    if defect not in (None, "scratch", "dent", "missing_part"):
        raise ValueError("defect must be None, 'scratch', 'dent' or 'missing_part'")
    rng = Rng(seed)
    plate_color = (156, 160, 166)
    canvas = Canvas(width, height, (58, 62, 68))
    el: dict[str, Placed] = {}
    el["part"] = canvas.rect(
        (60, 60, width - 60, height - 60),
        plate_color,
        outline=(100, 104, 110),
        outline_width=4,
        radius=16,
        name="part",
    )
    pl, pt, pr, pb = el["part"].bounds
    bolts = []
    for i, (bx, by) in enumerate(
        ((pl + 44, pt + 44), (pr - 44, pt + 44), (pl + 44, pb - 44), (pr - 44, pb - 44))
    ):
        bolts.append(
            canvas.ellipse(
                (bx - 18, by - 18, bx + 18, by + 18),
                (88, 92, 98),
                outline=(60, 62, 66),
                outline_width=3,
                name=f"bolt_{i}",
            )
        )
        el[f"bolt_{i}"] = bolts[-1]
    el["label_plate"] = canvas.text(
        (width // 2 - text_size("PN 4471-B", 3)[0] // 2, pt + 40),
        "PN 4471-B",
        scale=3,
        color=INK,
        name="label_plate",
    )
    inner = Placed("inner", (pl + 90, pt + 100, pr - 90, pb - 60), canvas.size)
    if defect == "scratch":
        el["defect"] = canvas.scratch(inner, _derive(seed, 3))
    elif defect == "dent":
        side = rng.integer(90, 120)
        x0 = rng.integer(inner.bounds[0], inner.bounds[2] - side)
        y0 = rng.integer(inner.bounds[1], inner.bounds[3] - side)
        el["defect"] = canvas.dent(Placed("dent_site", (x0, y0, x0 + side, y0 + side), canvas.size))
    elif defect == "missing_part":
        victim = rng.integer(0, 3)
        el["defect"] = canvas.erase(bolts[victim], plate_color)
        el.pop(f"bolt_{victim}")
    return _finish_scene(
        canvas,
        "defect_panel",
        {"width": width, "height": height, "defect": defect},
        seed,
        el,
        perturbations,
        occlude,
    )


_CARD_NAMES = ("EMBER", "WARD", "SURGE", "DRIFT", "SHARD", "BLOOM", "ECHO", "VAULT")


def deck_builder_hud(
    seed: int = 0,
    *,
    width: int = 960,
    height: int = 540,
    hand: int = 5,
    health: tuple[int, int] = (42, 80),
    energy: tuple[int, int] = (3, 3),
    perturbations: Sequence[tuple[str, int]] = (),
    occlude: str | None = None,
) -> SyntheticImage:
    """A fictional deck-builder battle HUD: enemy, health bar, energy orb, a hand of cards.

    Entirely invented art (geometric shapes and invented card names). Elements: ``enemy``,
    ``health_bar``, ``health_text``, ``energy_orb``, ``energy_text``, ``end_turn_button``,
    ``card_<i>`` and ``card_cost_<i>``.
    """
    if not 1 <= hand <= 7 or not 0 <= health[0] <= health[1] or health[1] < 1:
        raise ValueError("hand must be 1 to 7 and health (current, maximum) consistent")
    rng = Rng(seed)
    canvas = Canvas(width, height, (28, 30, 46))
    el: dict[str, Placed] = {}
    ex = width // 2
    body = canvas.ellipse((ex - 90, 50, ex + 90, 230), (120, 70, 150), name="enemy")
    canvas.ellipse((ex - 50, 100, ex - 20, 130), WHITE, name="eye")
    canvas.ellipse((ex + 20, 100, ex + 50, 130), WHITE, name="eye")
    el["enemy"] = body
    bar_l, bar_t = 30, 256
    el["health_bar"] = canvas.rect(
        (bar_l, bar_t, bar_l + 260, bar_t + 30),
        (70, 20, 24),
        outline=WHITE,
        outline_width=2,
        name="health_bar",
    )
    filled = 252 * health[0] // health[1]
    if filled > 0:
        canvas.rect(
            (bar_l + 4, bar_t + 4, bar_l + 4 + filled, bar_t + 26),
            (210, 60, 70),
            name="health_fill",
        )
    el["health_text"] = canvas.text(
        (bar_l, bar_t + 40), f"HP {health[0]}/{health[1]}", scale=3, color=WHITE, name="health_text"
    )
    el["energy_orb"] = canvas.ellipse(
        (width - 160, 240, width - 60, 340),
        AMBER,
        outline=WHITE,
        outline_width=3,
        name="energy_orb",
    )
    el["energy_text"] = canvas.text_centered(
        (width - 110, 290), f"{energy[0]}/{energy[1]}", scale=3, color=INK, name="energy_text"
    )
    el["end_turn_button"] = canvas.rect(
        (width - 190, height - 80, width - 30, height - 30),
        (60, 140, 90),
        radius=8,
        name="end_turn_button",
    )
    canvas.text_centered(
        (width - 110, height - 55), "END TURN", scale=2, color=WHITE, name="end_turn_text"
    )
    card_h, gap = 170, 14
    room = width - 220  # the hand stops before the end-turn button and the energy orb
    card_w = min(120, (room - 20 - (hand - 1) * gap) // hand)
    if card_w < 80:
        raise ValueError("canvas too narrow for that many cards")
    total = hand * card_w + (hand - 1) * gap
    x = max(20, (room - total) // 2)
    names = rng.shuffled(_CARD_NAMES)[:hand]
    for i, card in enumerate(names):
        top = height - card_h - 20 - rng.integer(0, 8)
        el[f"card_{i}"] = canvas.rect(
            (x, top, x + card_w, top + card_h),
            (236, 230, 214),
            outline=(200, 160, 60),
            outline_width=3,
            radius=10,
            name=f"card_{i}",
        )
        el[f"card_cost_{i}"] = canvas.ellipse(
            (x + 6, top + 6, x + 38, top + 38), (40, 90, 200), name=f"card_cost_{i}"
        )
        canvas.text_centered(
            (x + 22, top + 22), str(rng.integer(0, 3)), scale=2, color=WHITE, name="cost_digit"
        )
        canvas.text_centered(
            (x + card_w // 2, top + 100), card, scale=2, color=INK, name=f"card_name_{i}"
        )
        x += card_w + gap
    return _finish_scene(
        canvas,
        "deck_builder_hud",
        {
            "width": width,
            "height": height,
            "hand": hand,
            "health": list(health),
            "energy": list(energy),
        },
        seed,
        el,
        perturbations,
        occlude,
    )


_SCHEMATIC_KINDS = ("resistor", "capacitor", "lamp", "switch")


def schematic(
    seed: int = 0,
    *,
    width: int = 720,
    height: int = 360,
    components: Sequence[str] = ("resistor", "capacitor", "lamp", "switch"),
    perturbations: Sequence[tuple[str, int]] = (),
    occlude: str | None = None,
) -> SyntheticImage:
    """A line-drawn circuit loop: components on the top wire, a battery on the bottom wire.

    Elements: ``<kind>_<n>`` for each symbol (leads included), ``label_<kind>_<n>`` and
    ``battery_1`` / ``label_battery_1``. ``components`` are drawn left to right, in order.
    """
    if not 1 <= len(components) <= 4 or any(c not in _SCHEMATIC_KINDS for c in components):
        raise ValueError(f"components must be 1 to 4 of {_SCHEMATIC_KINDS}")
    rng = Rng(seed)
    canvas = Canvas(width, height, WHITE)
    wire = (30, 30, 30)
    left, right, top, bottom = 50, width - 50, 90, height - 80
    el: dict[str, Placed] = {}
    count = len(components)
    pitch = (right - left) // count
    centers = [left + pitch // 2 + k * pitch for k in range(count)]
    canvas.line((left, top), (left, bottom), wire, 3, name="wire")
    canvas.line((right, top), (right, bottom), wire, 3, name="wire")

    def symbol(kind: str, cx: int, cy: int, tag: str) -> Placed:
        parts = []
        if kind == "resistor":
            parts.append(canvas.line((cx - 40, cy), (cx - 25, cy), wire, 3, name=tag))
            zig = [
                (cx - 25 + 50 * k // 6, cy + (-14 if k % 2 else 14) * (1 if 0 < k < 6 else 0))
                for k in range(7)
            ]
            parts.append(canvas.polyline(zig, wire, 3, name=tag))
            parts.append(canvas.line((cx + 25, cy), (cx + 40, cy), wire, 3, name=tag))
        elif kind in ("capacitor", "battery"):
            long_h, short_h = (22, 22) if kind == "capacitor" else (24, 12)
            parts.append(canvas.line((cx - 40, cy), (cx - 6, cy), wire, 3, name=tag))
            parts.append(
                canvas.line((cx - 6, cy - long_h), (cx - 6, cy + long_h), wire, 3, name=tag)
            )
            parts.append(
                canvas.line((cx + 6, cy - short_h), (cx + 6, cy + short_h), wire, 3, name=tag)
            )
            parts.append(canvas.line((cx + 6, cy), (cx + 40, cy), wire, 3, name=tag))
        elif kind == "lamp":
            parts.append(canvas.line((cx - 40, cy), (cx - 20, cy), wire, 3, name=tag))
            parts.append(
                canvas.ellipse(
                    (cx - 20, cy - 20, cx + 20, cy + 20), outline=wire, outline_width=3, name=tag
                )
            )
            parts.append(canvas.line((cx - 12, cy - 12), (cx + 12, cy + 12), wire, 3, name=tag))
            parts.append(canvas.line((cx - 12, cy + 12), (cx + 12, cy - 12), wire, 3, name=tag))
            parts.append(canvas.line((cx + 20, cy), (cx + 40, cy), wire, 3, name=tag))
        else:  # switch
            parts.append(canvas.line((cx - 40, cy), (cx - 20, cy), wire, 3, name=tag))
            parts.append(canvas.ellipse((cx - 24, cy - 4, cx - 16, cy + 4), wire, name=tag))
            parts.append(canvas.ellipse((cx + 16, cy - 4, cx + 24, cy + 4), wire, name=tag))
            parts.append(canvas.line((cx - 20, cy), (cx + 14, cy - 22), wire, 3, name=tag))
            parts.append(canvas.line((cx + 20, cy), (cx + 40, cy), wire, 3, name=tag))
        return Placed.union(tag, *parts)

    previous = left
    seen: dict[str, int] = {}
    order = list(components)
    for cx, kind in zip(centers, order, strict=True):
        seen[kind] = seen.get(kind, 0) + 1
        tag = f"{kind}_{seen[kind]}"
        canvas.line((previous, top), (cx - 40, top), wire, 3, name="wire")
        el[tag] = symbol(kind, cx, top, tag)
        prefix = {"resistor": "R", "capacitor": "C", "lamp": "L", "switch": "S"}[kind]
        el[f"label_{tag}"] = canvas.text_centered(
            (cx, top + 46), f"{prefix}{seen[kind]}", scale=2, name=f"label_{tag}"
        )
        previous = cx + 40
    canvas.line((previous, top), (right, top), wire, 3, name="wire")
    mid = (left + right) // 2 + rng.integer(-40, 40)
    canvas.line((left, bottom), (mid - 40, bottom), wire, 3, name="wire")
    el["battery_1"] = symbol("battery", mid, bottom, "battery_1")
    el["label_battery_1"] = canvas.text_centered(
        (mid, bottom + 46), "B1", scale=2, name="label_battery_1"
    )
    canvas.line((mid + 40, bottom), (right, bottom), wire, 3, name="wire")
    return _finish_scene(
        canvas,
        "schematic",
        {"width": width, "height": height, "components": list(components)},
        seed,
        el,
        perturbations,
        occlude,
    )


def with_gold_boxes(
    image: SyntheticImage,
    names: Sequence[str] | None = None,
    *,
    color: Any = (243, 134, 161),
    outline_width: int = 3,
) -> SyntheticImage:
    """A copy of ``image`` with a rectangle drawn just outside each named element's gold box.

    For documentation and debugging: it shows what a recipe's labels will say. The result is
    for display; never use it as a fixture image (the boxes are not part of the scene).
    """
    chosen = list(image.elements) if names is None else list(names)
    canvas = Canvas(image.width, image.height)
    canvas.pixels[:] = image.pixels
    for name in chosen:
        left, top, right, bottom = image.elements[name].bounds
        pad = outline_width
        canvas.rect(
            (left - pad, top - pad, right + pad, bottom + pad),
            outline=color,
            outline_width=outline_width,
            name=f"box_{name}",
        )
    return canvas.finish(
        "with_gold_boxes",
        {"base": image.provenance, "boxes": chosen},
        image.provenance["seed"],
        image.elements,
    )


# --- frame sequences --------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    """One still of a sequence: its explicit timestamp, the image and the target's geometry."""

    timestamp_seconds: float
    image: SyntheticImage
    target: Placed | None  # None while the object is absent from the scene


@dataclass(frozen=True)
class FrameSequence:
    frames: tuple[Frame, ...]
    provenance: dict[str, Any]


def _check_timestamps(timestamps: Sequence[float]) -> list[float]:
    values = [float(t) for t in timestamps]
    if len(values) < 2:
        raise ValueError("a sequence needs at least two timestamps")
    if any(not math.isfinite(t) or t < 0 for t in values):
        raise ValueError("timestamps must be finite and nonnegative")
    if any(b <= a for a, b in zip(values, values[1:], strict=False)):
        raise ValueError("timestamps must be strictly increasing")
    return values


def _track_frame(
    seed: int, width: int, height: int, label: str, center: tuple[int, int] | None, size: int
) -> tuple[Canvas, Placed | None]:
    canvas = Canvas(width, height, (236, 238, 242))
    canvas.rect((0, height // 2 + size // 2 + 10, width, height), (176, 180, 188), name="floor")
    canvas.rect((20, 20, width - 20, 52), (60, 64, 80), name="rail")
    canvas.text((32, 28), "STATION 3", scale=2, color=WHITE, name="station")
    placed = None
    if center is not None:
        cx, cy = center
        half = size // 2
        placed = canvas.rect(
            (cx - half, cy - half, cx + half, cy + half),
            (200, 80, 60),
            outline=INK,
            radius=8,
            name="object",
        )
        canvas.text_centered((cx, cy), label, scale=2, color=WHITE, name="object_label")
    return canvas, placed


def moving_object_frames(
    timestamps: Sequence[float],
    seed: int = 0,
    *,
    start: tuple[float, float] = (0.2, 0.5),
    end: tuple[float, float] = (0.8, 0.5),
    width: int = 640,
    height: int = 360,
    size: int = 96,
    label: str = "UNIT 7",
) -> FrameSequence:
    """An object that moves in a straight line, one image per explicit timestamp.

    Position is linear in elapsed time between the first and last timestamp (``start`` and
    ``end`` are fractions of the frame). Every frame's ``target`` is the object's geometry.
    """
    times = _check_timestamps(timestamps)
    frames = []
    span = times[-1] - times[0]
    for index, t in enumerate(times):
        progress = (t - times[0]) / span
        cx = round(width * (start[0] + (end[0] - start[0]) * progress))
        cy = round(height * (start[1] + (end[1] - start[1]) * progress))
        canvas, placed = _track_frame(seed, width, height, label, (cx, cy), size)
        image = canvas.finish(
            "moving_object_frames",
            {
                "width": width,
                "height": height,
                "start": list(start),
                "end": list(end),
                "size": size,
                "label": label,
                "frame_index": index,
                "timestamp_seconds": t,
            },
            seed,
            {"object": placed},
        )
        frames.append(Frame(t, image, placed))
    return FrameSequence(tuple(frames), _sequence_provenance("moving_object_frames", seed, times))


def appearing_object_frames(
    timestamps: Sequence[float],
    seed: int = 0,
    *,
    appear_at: float,
    disappear_at: float | None = None,
    position: tuple[float, float] = (0.5, 0.5),
    width: int = 640,
    height: int = 360,
    size: int = 96,
    label: str = "UNIT 7",
) -> FrameSequence:
    """A stationary object present only from ``appear_at`` until ``disappear_at`` (exclusive).

    Frames outside that interval show the empty scene and have ``target`` None, so an arrival
    or departure label is derived from the timestamps rather than typed.
    """
    times = _check_timestamps(timestamps)
    if disappear_at is not None and disappear_at <= appear_at:
        raise ValueError("disappear_at must be after appear_at")
    frames = []
    cx, cy = round(width * position[0]), round(height * position[1])
    for index, t in enumerate(times):
        present = t >= appear_at and (disappear_at is None or t < disappear_at)
        canvas, placed = _track_frame(
            seed, width, height, label, (cx, cy) if present else None, size
        )
        image = canvas.finish(
            "appearing_object_frames",
            {
                "width": width,
                "height": height,
                "appear_at": appear_at,
                "disappear_at": disappear_at,
                "position": list(position),
                "size": size,
                "label": label,
                "frame_index": index,
                "timestamp_seconds": t,
            },
            seed,
            {"object": placed} if placed is not None else {},
        )
        frames.append(Frame(t, image, placed))
    return FrameSequence(
        tuple(frames), _sequence_provenance("appearing_object_frames", seed, times)
    )


def _sequence_provenance(generator: str, seed: int, times: list[float]) -> dict[str, Any]:
    return {
        "origin": "generated",
        "generator": f"jev_cookbook.synthetic_images.{generator}",
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "parameters": {"timestamps_seconds": times},
    }


def save_sequence(
    sequence: FrameSequence,
    directory: str | Path,
    stem: str,
    *,
    root: str | Path | None = None,
) -> list[tuple[float, str, SavedImage]]:
    """Write every frame as ``<stem>-<index>.png`` under an ``assets`` ``directory``.

    Returns ``(timestamp_seconds, relative_path, SavedImage)`` rows; the relative path is
    relative to ``root`` (the recipe folder; default: the parent of ``directory``) and uses
    forward slashes, ready for a fixture's ``fields`` and for
    :func:`jev_cookbook.vision.load_frames` with the same ``root=``.
    """
    folder = Path(directory)
    base = Path(root) if root is not None else folder.parent
    rows = []
    for index, frame in enumerate(sequence.frames):
        saved = write_asset(frame.image, folder / f"{stem}-{index:02d}.png")
        rows.append((frame.timestamp_seconds, saved.path.relative_to(base).as_posix(), saved))
    return rows


GENERATORS: Mapping[str, Callable[..., SyntheticImage]] = MappingProxyType(
    {
        "shapes_scene": shapes_scene,
        "ui_mock": ui_mock,
        "wordmark": wordmark,
        "document_page": document_page,
        "product_shelf": product_shelf,
        "defect_panel": defect_panel,
        "deck_builder_hud": deck_builder_hud,
        "schematic": schematic,
    }
)
