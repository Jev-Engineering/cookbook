"""Deterministic synthetic test images for the multimodal recipes (docs/synthetic-images.md).

Pillow and the standard library only; no system font, no real photograph, brand or screenshot.
Everything is drawn with integer arithmetic (a built-in 5x7 bitmap font, integer ellipse,
triangle and line rasterisers, a splitmix64 random stream); a float argument is converted
exactly through ``fractions.Fraction`` before it can matter, and floats otherwise appear only in
reported values (``Drawn.box``, timestamps) and comparisons. So the *pixels* of an image are a
pure function of the arguments and the seed. They do not depend on FreeType, on Pillow's
anti-aliasing or on the platform. Only the PNG *encoding* of those pixels (zlib) can differ
between Pillow builds, which is what :func:`write_asset` and :func:`bytes_are_canonical` handle.

Every primitive returns a :class:`Drawn` with the exact pixel rectangle it drew, and its
normalized ``box`` (``top``/``bottom``/``left``/``right``, the form ``jev_cookbook.vision``
and the gold Box labels use), so a recipe derives its labels instead of typing them.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import importlib
import inspect
import io
import json
import math
import os
import re
import struct
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import accumulate
from pathlib import Path
from typing import Any

import PIL
from PIL import Image, ImageChops, ImageDraw, features

from .vision import IMAGE_LIMITS, resolve_asset_path, validate_image_asset

__all__ = [
    "CANONICAL_PILLOW",
    "CANONICAL_ZLIB",
    "GLYPH_HEIGHT",
    "GLYPH_PITCH",
    "GLYPH_WIDTH",
    "MAX_ASSET_BYTES",
    "PALETTE",
    "SCENES",
    "SUPPORTED_CHARACTERS",
    "Canvas",
    "Drawn",
    "Frame",
    "RegenerationMismatch",
    "Rng",
    "absent_label",
    "bytes_are_canonical",
    "build_frames",
    "check_reproducible",
    "deck_hud",
    "encode_png",
    "fictional_name",
    "fit_scale",
    "grid_positions",
    "interpolate",
    "login_screen",
    "manifest_entry",
    "mix",
    "moving_object_frame",
    "moving_object_frames",
    "part_photo",
    "pixels_sha256",
    "png_pixels_equal",
    "reproduce",
    "save_frames",
    "text_width",
    "write_asset",
    "write_png",
]

# The environment whose PNG encoder produced the committed bytes. The bytes of a PNG come from
# Pillow's encoder (filter choice, written chunks) and from the zlib it is linked to, so both are
# recorded. CANONICAL_PILLOW is the Pillow pinned in .github/constraints-notebooks.txt (a test
# keeps the two equal); CANONICAL_ZLIB is the zlib that pinned PyPI wheel bundles, as reported by
# PIL.features.version("zlib") (the 12.3.0 and 13.0.0 wheels both bundle 1.2.13, which is why
# their bytes agree today). Only when BOTH match are the bytes the contract; under any other
# environment, including a Pillow 12.3.0 linked against a system zlib, the decoded pixels are
# (see write_asset and bytes_are_canonical). After a Pillow pin bump re-record both constants,
# the byte digests in tests/test_synthetic_images.py and the gallery (docs/synthetic-images.md).
CANONICAL_PILLOW = "12.3.0"
CANONICAL_ZLIB = "1.2.13"
# This repository's per-file cap (tools/check_recipe_assets.py MAX_FILE_BYTES; a test compares).
MAX_ASSET_BYTES = 1024 * 1024
# The only PNG chunks the encoder may emit; tools/check_recipe_assets.py allows more, this is
# stricter so a Pillow release that starts adding metadata is caught at save time.
_PNG_CHUNKS = (b"IHDR", b"IDAT", b"IEND")
_PNG_SAVE = {"compress_level": 9, "optimize": False}

Colour = tuple[int, int, int]

PALETTE: dict[str, Colour] = {
    "paper": (250, 250, 245),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "ink": (30, 32, 40),
    "dark": (60, 66, 82),
    "mid": (140, 146, 158),
    "grey": (200, 203, 210),
    "light": (232, 235, 241),
    "blue": (40, 100, 220),
    "teal": (20, 150, 160),
    "green": (40, 160, 90),
    "amber": (240, 170, 30),
    "red": (210, 50, 50),
    "purple": (130, 70, 200),
    "pink": (230, 110, 160),
    "navy": (24, 28, 44),
}

# --- the 5x7 bitmap font ----------------------------------------------------------------------
# Drawn by hand for this module (MIT, like the repository). Upper case only: lower case input is
# folded to upper case and the folded text is what Drawn.attrs["text"] reports. A character
# outside this table raises ValueError rather than drawing a blank.

GLYPH_WIDTH = 5
GLYPH_HEIGHT = 7
GLYPH_PITCH = 6  # one blank column between glyphs

_GLYPH_SOURCE = {
    "A": ".###./#...#/#...#/#####/#...#/#...#/#...#",
    "B": "####./#...#/#...#/####./#...#/#...#/####.",
    "C": ".###./#...#/#..../#..../#..../#...#/.###.",
    "D": "####./#...#/#...#/#...#/#...#/#...#/####.",
    "E": "#####/#..../#..../####./#..../#..../#####",
    "F": "#####/#..../#..../####./#..../#..../#....",
    "G": ".###./#...#/#..../#.###/#...#/#...#/.###.",
    "H": "#...#/#...#/#...#/#####/#...#/#...#/#...#",
    "I": ".###./..#../..#../..#../..#../..#../.###.",
    "J": "..###/...#./...#./...#./...#./#..#./.##..",
    "K": "#...#/#..#./#.#../##.../#.#../#..#./#...#",
    "L": "#..../#..../#..../#..../#..../#..../#####",
    "M": "#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#",
    "N": "#...#/##..#/#.#.#/#..##/#...#/#...#/#...#",
    "O": ".###./#...#/#...#/#...#/#...#/#...#/.###.",
    "P": "####./#...#/#...#/####./#..../#..../#....",
    "Q": ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#",
    "R": "####./#...#/#...#/####./#.#../#..#./#...#",
    "S": ".####/#..../#..../.###./....#/....#/####.",
    "T": "#####/..#../..#../..#../..#../..#../..#..",
    "U": "#...#/#...#/#...#/#...#/#...#/#...#/.###.",
    "V": "#...#/#...#/#...#/#...#/#...#/.#.#./..#..",
    "W": "#...#/#...#/#...#/#.#.#/#.#.#/##.##/#...#",
    "X": "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",
    "Y": "#...#/#...#/.#.#./..#../..#../..#../..#..",
    "Z": "#####/....#/...#./..#../.#.../#..../#####",
    "0": ".###./#...#/#..##/#.#.#/##..#/#...#/.###.",
    "1": "..#../.##../..#../..#../..#../..#../.###.",
    "2": ".###./#...#/....#/...#./..#../.#.../#####",
    "3": "####./....#/....#/.###./....#/....#/####.",
    "4": "...#./..##./.#.#./#..#./#####/...#./...#.",
    "5": "#####/#..../####./....#/....#/#...#/.###.",
    "6": ".###./#..../#..../####./#...#/#...#/.###.",
    "7": "#####/....#/...#./..#../.#.../.#.../.#...",
    "8": ".###./#...#/#...#/.###./#...#/#...#/.###.",
    "9": ".###./#...#/#...#/.####/....#/....#/.###.",
    " ": "...../...../...../...../...../...../.....",
    ".": "...../...../...../...../...../...../..#..",
    ",": "...../...../...../...../...../..#../.#...",
    ":": "...../..#../...../...../...../..#../.....",
    ";": "...../..#../...../...../..#../.#.../.....",
    "-": "...../...../...../#####/...../...../.....",
    "_": "...../...../...../...../...../...../#####",
    "+": "...../..#../..#../#####/..#../..#../.....",
    "=": "...../...../#####/...../#####/...../.....",
    "/": "....#/....#/...#./..#../.#.../#..../#....",
    "(": "...#./..#../.#.../.#.../.#.../..#../...#.",
    ")": ".#.../..#../...#./...#./...#./..#../.#...",
    "!": "..#../..#../..#../..#../..#../...../..#..",
    "?": ".###./#...#/....#/...#./..#../...../..#..",
    "%": "##..#/##..#/...#./..#../.#.../#..##/#..##",
    "#": ".#.#./.#.#./#####/.#.#./#####/.#.#./.#.#.",
    "*": "...../#.#.#/.###./#####/.###./#.#.#/.....",
    "'": "..#../..#../.#.../...../...../...../.....",
    '"': ".#.#./.#.#./...../...../...../...../.....",
    ">": "#..../.#.../..#../...#./..#../.#.../#....",
    "<": "....#/...#./..#../.#.../..#../...#./....#",
    "[": ".###./.#.../.#.../.#.../.#.../.#.../.###.",
    "]": ".###./...#./...#./...#./...#./...#./.###.",
}


def _compile_glyphs() -> dict[str, tuple[tuple[int, int, int], ...]]:
    """Per glyph, the lit runs as ``(row, first_column, last_column)``."""
    compiled = {}
    for char, source in _GLYPH_SOURCE.items():
        rows = source.split("/")
        if len(rows) != GLYPH_HEIGHT or any(len(row) != GLYPH_WIDTH for row in rows):
            raise ValueError(f"glyph {char!r} is not {GLYPH_WIDTH}x{GLYPH_HEIGHT}")
        runs = []
        for y, row in enumerate(rows):
            x = 0
            while x < GLYPH_WIDTH:
                if row[x] == "#":
                    start = x
                    while x + 1 < GLYPH_WIDTH and row[x + 1] == "#":
                        x += 1
                    runs.append((y, start, x))
                x += 1
        compiled[char] = tuple(runs)
    return compiled


_GLYPHS = _compile_glyphs()
SUPPORTED_CHARACTERS = "".join(_GLYPHS)


def _fold(text: str) -> str:
    if not isinstance(text, str) or not text:
        raise ValueError("text must be a non-empty string")
    folded = text.upper()
    bad = sorted({c for c in folded if c not in _GLYPHS})
    if bad:
        raise ValueError(f"the built-in font has no glyph for {bad!r}; see SUPPORTED_CHARACTERS")
    return folded


def _scale(scale: Any) -> int:
    if isinstance(scale, bool) or not isinstance(scale, int) or not 1 <= scale <= 32:
        raise ValueError("scale must be an integer from 1 to 32")
    return scale


def text_width(text: str, scale: int = 2) -> int:
    """Pixel width of ``text`` at ``scale``: 6 columns per character minus the trailing gap."""
    return (len(_fold(text)) * GLYPH_PITCH - 1) * _scale(scale)


def fit_scale(text: str, max_width: int, max_height: int, *, maximum: int = 8) -> int:
    """The largest scale (at most ``maximum``) at which ``text`` fits; ValueError if scale 1 does not."""
    for scale in range(min(maximum, 32), 0, -1):
        if text_width(text, scale) <= max_width and GLYPH_HEIGHT * scale <= max_height:
            return scale
    raise ValueError(f"{text!r} does not fit in {max_width}x{max_height} pixels even at scale 1")


# --- colours and numbers ------------------------------------------------------------------------


def _colour(value: Any) -> Colour:
    if isinstance(value, str):
        if value not in PALETTE:
            raise ValueError(f"unknown colour name {value!r}; use one of {sorted(PALETTE)}")
        return PALETTE[value]
    if (
        isinstance(value, Sequence)
        and len(value) == 3
        and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in value)
    ):
        return (value[0], value[1], value[2])
    raise ValueError("a colour is a PALETTE name or three integers from 0 to 255")


def mix(first: Any, second: Any, percent: int) -> Colour:
    """Integer blend: ``percent`` 0 is ``first``, 100 is ``second``; halves round up."""
    if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
        raise ValueError("percent must be an integer from 0 to 100")
    a, b = _colour(first), _colour(second)
    return (
        (a[0] * (100 - percent) + b[0] * percent + 50) // 100,
        (a[1] * (100 - percent) + b[1] * percent + 50) // 100,
        (a[2] * (100 - percent) + b[2] * percent + 50) // 100,
    )


def _int(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _fraction(value: Any, name: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        raise ValueError(f"{name} must be a number from 0 to 1")
    try:
        result = Fraction(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number from 0 to 1") from exc
    if not 0 <= result <= 1:
        raise ValueError(f"{name} must be from 0 to 1")
    return result


def _round_half_up(value: Fraction) -> int:
    return math.floor(value + Fraction(1, 2))


# --- the random stream --------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1


class Rng:
    """splitmix64: a 64-bit stream defined by integer arithmetic alone.

    The standard library's ``random`` is stable for ``random()`` but its other methods have
    changed between Python releases; this stream is the same on every Python and platform.
    ``Rng(0).u64()`` is ``0xE220A8397B1DCDAF``, the published first output for seed 0.
    """

    def __init__(self, seed: int = 0) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= _MASK64:
            raise ValueError("seed must be an integer from 0 to 2**64 - 1")
        self._state = seed

    def u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        """An unbiased integer in ``range(n)`` (rejection sampling)."""
        n = _int(n, "n", minimum=1)
        limit = (1 << 64) - (1 << 64) % n
        while True:
            value = self.u64()
            if value < limit:
                return value % n

    def between(self, low: int, high: int) -> int:
        """An integer from ``low`` to ``high``, both included."""
        if _int(high, "high") < _int(low, "low"):
            raise ValueError("high must not be below low")
        return low + self.below(high - low + 1)

    def choice(self, items: Sequence[Any]) -> Any:
        if not items:
            raise ValueError("cannot choose from an empty sequence")
        return items[self.below(len(items))]

    def bytes(self, count: int) -> bytes:
        count = _int(count, "count", minimum=0)
        out = bytearray()
        while len(out) < count:
            out += self.u64().to_bytes(8, "little")
        return bytes(out[:count])


_ONSETS = ("b", "br", "d", "f", "g", "k", "l", "m", "n", "p", "pr", "r", "s", "t", "v", "z")
_VOWELS = ("a", "e", "i", "o", "u")
_CODAS = ("", "n", "x", "m", "r", "s")
# Substrings no generated name may contain (upper case, plain ASCII, kept short: the obvious slurs
# and vulgarities that a random syllable chain can spell, including across a syllable boundary).
_DENY = (
    "ANUS", "BONER", "COCK", "CUNT", "DICK", "FAG", "FUCK", "NAZI", "NIG", "PISS", "RAPE", "SEX",
    "SHIT", "TIT",
)  # fmt: skip


def _is_clean(name: str) -> bool:
    return not any(word in name for word in _DENY)


def fictional_name(seed: int = 0) -> str:
    """A pronounceable invented name in upper case, e.g. for a wordmark.

    The name never contains a substring of ``_DENY`` (a short list of offensive words): a draw
    that would is discarded and the next one from the same seeded stream is used, so every seed
    still maps to one fixed name and a seed whose first draw is clean is unaffected. The output
    space is finite (about 3.1 million strings), and a test enumerates it. A name is **not** a
    trademark search: a reviewer still rejects one that happens to match a real company, and an
    author should read the name before committing the picture it appears in.
    """
    rng = Rng(seed)
    while True:
        syllables = [rng.choice(_ONSETS) + rng.choice(_VOWELS) for _ in range(rng.between(2, 3))]
        name = ("".join(syllables) + rng.choice(_CODAS)).upper()
        if _is_clean(name):
            return name


# --- gold geometry ------------------------------------------------------------------------------

Pixels = tuple[int, int, int, int]  # left, top, right (exclusive), bottom (exclusive)


@dataclass(frozen=True)
class Drawn:
    """What one primitive drew: its pixel rectangle and the normalized box derived from it.

    ``left``/``top`` are the first pixel drawn and ``right``/``bottom`` one past the last, as in
    a Pillow crop, clipped to the canvas. For shapes, lines, defects and text it is the extent of
    the drawn pixels (for text, the line box: the first glyph cell to the last, 7 rows tall; ink
    never leaves it). ``parts`` are the pieces of a composite; ``attrs`` hold primitive-specific
    facts (label, style, text, fraction, ...).
    """

    name: str | None
    kind: str
    left: int
    top: int
    right: int
    bottom: int
    image_size: tuple[int, int]
    parts: tuple[Drawn, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        width, height = self.image_size
        if not (0 <= self.left < self.right <= width and 0 <= self.top < self.bottom <= height):
            raise ValueError(f"{self.kind} {self.name!r} has an empty or out-of-canvas rectangle")

    @property
    def pixels(self) -> Pixels:
        return (self.left, self.top, self.right, self.bottom)

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        """The middle pixel (rounded down): where a simulated click would land."""
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)

    @property
    def box(self) -> dict[str, float]:
        """The normalized box: pixel edge divided by the image width or height."""
        width, height = self.image_size
        return {
            "top": self.top / height,
            "bottom": self.bottom / height,
            "left": self.left / width,
            "right": self.right / width,
        }

    def label(self) -> dict[str, Any]:
        """The gold Box label for a present target: ``{"present": True, "box": {...}}``."""
        return {"present": True, "box": self.box}


def absent_label() -> dict[str, bool]:
    """The gold Box label for a target that is not in the image."""
    return {"present": False}


def grid_positions(
    x: int, y: int, columns: int, rows: int, cell_width: int, cell_height: int, gap: int = 0
) -> list[tuple[int, int]]:
    """Top-left corners of a ``columns`` x ``rows`` grid, row by row (shelves, boards, tiles)."""
    for value, name in ((columns, "columns"), (rows, "rows"), (cell_width, "cell_width")):
        _int(value, name, minimum=1)
    _int(cell_height, "cell_height", minimum=1)
    _int(gap, "gap", minimum=0)
    return [
        (x + c * (cell_width + gap), y + r * (cell_height + gap))
        for r in range(rows)
        for c in range(columns)
    ]


def interpolate(start: int, end: int, t: Any, t0: Any, t1: Any) -> int:
    """Integer position at time ``t`` on a straight path from ``start`` (at ``t0``) to ``end`` (at ``t1``).

    Exact rational arithmetic, clamped to the endpoints outside ``[t0, t1]``, halves round up.
    """
    if not t1 > t0:
        raise ValueError("t1 must be after t0")
    progress = min(max((Fraction(t) - Fraction(t0)) / (Fraction(t1) - Fraction(t0)), 0), 1)
    return start + _round_half_up((end - start) * progress)


def _merge(a: Pixels, b: Pixels) -> Pixels:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _sub(name: str | None, part: str) -> str | None:
    return None if name is None else f"{name}.{part}"


def _json_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """The parameters as plain JSON data (tuples become lists), or ValueError."""
    try:
        return json.loads(json.dumps(dict(parameters), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("parameters must be JSON data (numbers, strings, lists, objects)") from exc


# --- integer rasterisers ------------------------------------------------------------------------
# Each yields (row, first_column, last_column) spans (columns included) in the shape's own
# coordinates. A pixel is inside when its centre is, tested with integers only.


def _ellipse_spans(w: int, h: int) -> Iterable[tuple[int, int, int]]:
    for y in range(h):
        t = 2 * y + 1 - h
        m = math.isqrt((w * w * (h * h - t * t)) // (h * h))
        first = max(-((-(w - 1 - m)) // 2), 0)
        last = min((w - 1 + m) // 2, w - 1)
        if first <= last:
            yield y, first, last


def _triangle_up_columns(w: int, h: int) -> Iterable[tuple[int, int, int]]:
    for r in range(h):
        m = (w * (2 * r + 1)) // (2 * h)
        first = max(-((-(w - 1 - m)) // 2), 0)
        last = min((w - 1 + m) // 2, w - 1)
        if first <= last:
            yield r, first, last


def _triangle_spans(w: int, h: int, direction: str) -> Iterable[tuple[int, int, int]]:
    if direction == "up":
        yield from _triangle_up_columns(w, h)
    elif direction == "down":
        for r, first, last in _triangle_up_columns(w, h):
            yield h - 1 - r, first, last
    elif direction in ("left", "right"):
        # Rotate an up-pointing triangle of width h and height w: its row r becomes column r.
        # The result is spans of one row each.
        for r, first, last in _triangle_up_columns(h, w):
            x = r if direction == "left" else w - 1 - r
            for y in range(first, last + 1):
                yield y, x, x
    else:
        raise ValueError("direction must be 'up', 'down', 'left' or 'right'")


_EMBLEMS = ("disc", "ring", "triangle", "bars", "stack")
_LOGO_COLOURS = ("blue", "teal", "green", "amber", "red", "purple")
_SHAPES = ("rect", "ellipse", "triangle", "triangle-down", "triangle-left", "triangle-right")


class Canvas:
    """An RGB image plus a ledger of everything drawn on it.

    ``objects`` maps each name given to a primitive to its :class:`Drawn`; a name can be used
    once. ``rng`` is the canvas's own :class:`Rng`, advanced only by primitives that need
    randomness (scratch and dent placement, noise), so a fixed call sequence and seed always
    produce the same pixels. ``generator`` and ``parameters`` say how to rebuild the canvas for
    the provenance manifest; the example scenes set them, a hand-written scene calls
    :meth:`provenance`.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 400,
        background: Any = "paper",
        *,
        seed: int = 0,
    ) -> None:
        _int(width, "width")
        _int(height, "height")
        lo, hi = IMAGE_LIMITS["min_side"], IMAGE_LIMITS["max_side"]
        if not (lo <= width <= hi and lo <= height <= hi):
            raise ValueError(f"each side must be {lo} to {hi} pixels, got {width}x{height}")
        if not IMAGE_LIMITS["min_area"] <= width * height <= IMAGE_LIMITS["max_area"]:
            raise ValueError(f"{width}x{height} is outside the API's total pixel limits")
        self.width = width
        self.height = height
        self.background = _colour(background)
        self.seed = seed
        self.rng = Rng(seed)
        self.image = Image.new("RGB", (width, height), self.background)
        self.objects: dict[str, Drawn] = {}
        self.generator: str | None = None
        self.parameters: dict[str, Any] | None = None
        self._draw = ImageDraw.Draw(self.image)

    # -- bookkeeping --

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def provenance(self, generator: str, parameters: Mapping[str, Any]) -> Canvas:
        """Record the manifest ``generator`` and ``parameters`` of a hand-written scene."""
        self.generator = generator
        self.parameters = _json_parameters(parameters)
        return self

    def _clip(self, x0: int, y0: int, x1: int, y1: int) -> Pixels | None:
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, self.width), min(y1, self.height)
        return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None

    def _fill(self, x0: int, y0: int, x1: int, y1: int, colour: Colour) -> Pixels | None:
        rect = self._clip(x0, y0, x1, y1)
        if rect:
            self._draw.rectangle([rect[0], rect[1], rect[2] - 1, rect[3] - 1], fill=colour)
        return rect

    def _record(
        self,
        name: str | None,
        kind: str,
        rect: Pixels | None,
        parts: tuple[Drawn, ...] = (),
        **attrs: Any,
    ) -> Drawn:
        if rect is None:
            raise ValueError(f"{kind} {name!r} lies entirely outside the {self.size} canvas")
        if name is not None and name in self.objects:
            raise ValueError(f"the name {name!r} is already used on this canvas")
        drawn = Drawn(name, kind, *rect, self.size, parts, attrs)
        if name is not None:
            self.objects[name] = drawn
        return drawn

    def _union(self, items: Sequence[Drawn]) -> Pixels:
        return (
            min(i.left for i in items),
            min(i.top for i in items),
            max(i.right for i in items),
            max(i.bottom for i in items),
        )

    def _target(self, target: Any) -> Pixels:
        """A Drawn, a name on this canvas, or a ``(left, top, right, bottom)`` pixel tuple."""
        if isinstance(target, str):
            if target not in self.objects:
                raise ValueError(f"no object named {target!r} on this canvas")
            return self.objects[target].pixels
        if isinstance(target, Drawn):
            return target.pixels
        if isinstance(target, Sequence) and len(target) == 4:
            left, top, right, bottom = (_int(v, "pixel edge") for v in target)
            rect = self._clip(left, top, right, bottom)
            if rect is None or rect != (left, top, right, bottom):
                raise ValueError("the region must be a non-empty rectangle inside the canvas")
            return rect
        raise ValueError("target must be a Drawn, an object name or (left, top, right, bottom)")

    # -- shapes --

    def rect(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        fill: Any = None,
        *,
        outline: Any = None,
        outline_width: int = 1,
        name: str | None = None,
        kind: str = "rect",
        **attrs: Any,
    ) -> Drawn:
        """A rectangle ``w`` x ``h`` with its top-left pixel at ``(x, y)``."""
        _int(x, "x"), _int(y, "y"), _int(w, "w", minimum=1), _int(h, "h", minimum=1)
        if fill is None and outline is None:
            raise ValueError("a rectangle needs a fill, an outline or both")
        ow = 0
        if outline is not None:
            colour = _colour(outline)
            ow = min(_int(outline_width, "outline_width", minimum=1), (min(w, h) + 1) // 2)
            self._fill(x, y, x + w, y + ow, colour)
            self._fill(x, y + h - ow, x + w, y + h, colour)
            self._fill(x, y + ow, x + ow, y + h - ow, colour)
            self._fill(x + w - ow, y + ow, x + w, y + h - ow, colour)
        if fill is not None:
            self._fill(x + ow, y + ow, x + w - ow, y + h - ow, _colour(fill))
        return self._record(name, kind, self._clip(x, y, x + w, y + h), **attrs)

    def _spans(
        self, x: int, y: int, spans: Iterable[tuple[int, int, int]], colour: Colour
    ) -> Pixels | None:
        bounds = None
        for row, first, last in spans:
            rect = self._fill(x + first, y + row, x + last + 1, y + row + 1, colour)
            if rect:
                bounds = rect if bounds is None else _merge(bounds, rect)
        return bounds

    def ellipse(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        fill: Any,
        *,
        outline: Any = None,
        outline_width: int = 1,
        name: str | None = None,
        kind: str = "ellipse",
        **attrs: Any,
    ) -> Drawn:
        """An ellipse inscribed in the ``w`` x ``h`` rectangle at ``(x, y)``."""
        _int(x, "x"), _int(y, "y"), _int(w, "w", minimum=1), _int(h, "h", minimum=1)
        bounds = None
        inner = (x, y, w, h)
        if outline is not None:
            ow = _int(outline_width, "outline_width", minimum=1)
            bounds = self._spans(x, y, _ellipse_spans(w, h), _colour(outline))
            inner = (x + ow, y + ow, w - 2 * ow, h - 2 * ow)
        if inner[2] >= 1 and inner[3] >= 1:
            ix, iy, iw, ih = inner
            got = self._spans(ix, iy, _ellipse_spans(iw, ih), _colour(fill))
            if got:
                bounds = got if bounds is None else _merge(bounds, got)
        return self._record(name, kind, bounds, **attrs)

    def triangle(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        fill: Any,
        *,
        direction: str = "up",
        name: str | None = None,
        kind: str = "triangle",
        **attrs: Any,
    ) -> Drawn:
        """An isosceles triangle in the ``w`` x ``h`` rectangle, apex up, down, left or right."""
        _int(x, "x"), _int(y, "y"), _int(w, "w", minimum=1), _int(h, "h", minimum=1)
        spans = list(_triangle_spans(w, h, direction))
        return self._record(
            name, kind, self._spans(x, y, spans, _colour(fill)), direction=direction, **attrs
        )

    def line(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        colour: Any,
        width: int = 1,
        *,
        name: str | None = None,
        kind: str = "line",
        **attrs: Any,
    ) -> Drawn:
        """A Bresenham line drawn with a ``width`` x ``width`` square brush (centred, rounding up)."""
        for value, label in ((x0, "x0"), (y0, "y0"), (x1, "x1"), (y1, "y1")):
            _int(value, label)
        _int(width, "width", minimum=1)
        paint = _colour(colour)
        offset = (width - 1) // 2
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        step_x, step_y = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        error = dx + dy
        bounds = None
        x, y = x0, y0
        while True:
            rect = self._fill(x - offset, y - offset, x - offset + width, y - offset + width, paint)
            if rect:
                bounds = rect if bounds is None else _merge(bounds, rect)
            if x == x1 and y == y1:
                break
            doubled = 2 * error
            if doubled >= dy:
                error += dy
                x += step_x
            if doubled <= dx:
                error += dx
                y += step_y
        return self._record(name, kind, bounds, **attrs)

    # -- text --

    def text(
        self,
        x: int,
        y: int,
        text: str,
        colour: Any = "ink",
        scale: int = 2,
        *,
        name: str | None = None,
        kind: str = "text",
    ) -> Drawn:
        """One line of text in the built-in font; ``(x, y)`` is the top-left of the first cell."""
        _int(x, "x"), _int(y, "y")
        scale = _scale(scale)
        folded = _fold(text)
        paint = _colour(colour)
        for index, char in enumerate(folded):
            left = x + index * GLYPH_PITCH * scale
            for row, first, last in _GLYPHS[char]:
                self._fill(
                    left + first * scale,
                    y + row * scale,
                    left + (last + 1) * scale,
                    y + (row + 1) * scale,
                    paint,
                )
        rect = self._clip(x, y, x + text_width(folded, scale), y + GLYPH_HEIGHT * scale)
        return self._record(name, kind, rect, text=folded, scale=scale)

    def centered_text(
        self, box: Any, text: str, colour: Any = "ink", scale: int = 2, *, name: str | None = None
    ) -> Drawn:
        """Text centred in ``box`` (a Drawn or pixel rectangle); ValueError if it does not fit."""
        left, top, right, bottom = self._target(box)
        width, height = text_width(text, scale), GLYPH_HEIGHT * scale
        if width > right - left or height > bottom - top:
            raise ValueError(f"{text!r} at scale {scale} does not fit in its box")
        return self.text(
            left + (right - left - width) // 2,
            top + (bottom - top - height) // 2,
            text,
            colour,
            scale,
            name=name,
        )

    def text_block(
        self,
        x: int,
        y: int,
        lines: Sequence[str],
        colour: Any = "ink",
        scale: int = 2,
        *,
        leading: int = 3,
        name: str | None = None,
    ) -> Drawn:
        """Lines of text, ``7 + leading`` glyph rows apart. ``parts`` are the lines."""
        if isinstance(lines, str) or not lines:
            raise ValueError("lines must be a non-empty sequence of strings")
        pitch = (GLYPH_HEIGHT + _int(leading, "leading", minimum=0)) * _scale(scale)
        parts = tuple(
            self.text(x, y + i * pitch, line, colour, scale, name=_sub(name, f"line{i}"))
            for i, line in enumerate(lines)
        )
        return self._record(name, "text-block", self._union(parts), parts, lines=len(parts))

    # -- labelled objects, stamps, signatures, symbols --

    def labelled_object(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        fill: Any,
        *,
        name: str,
        label: str | None = None,
        shape: str = "rect",
        outline: Any = "ink",
        text_colour: Any = "white",
        scale: int = 2,
    ) -> Drawn:
        """A named shape, optionally with a centred label; its Drawn is the gold box of ``name``."""
        if shape not in _SHAPES:
            raise ValueError(f"shape must be one of {_SHAPES}")
        if shape == "rect":
            body = self.rect(x, y, w, h, fill, outline=outline)
        elif shape == "ellipse":
            body = self.ellipse(x, y, w, h, fill, outline=outline)
        else:
            direction = "up" if shape == "triangle" else shape.split("-")[1]
            body = self.triangle(x, y, w, h, fill, direction=direction)
        parts = [body]
        if label is not None:
            inset = body.pixels
            if shape.startswith("triangle"):
                inset = (
                    body.left + body.width // 4,
                    body.top + body.height // 2,
                    body.right - body.width // 4,
                    body.bottom,
                )
            parts.append(self.centered_text(inset, label, text_colour, scale))
        return self._record(name, shape, body.pixels, tuple(parts), label=label)

    def stamp(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        text: str,
        colour: Any = "red",
        *,
        paper: Any = "paper",
        scale: int = 2,
        name: str | None = None,
    ) -> Drawn:
        """A round approval-style stamp: a ring in ``colour`` around centred text."""
        ring = self.ellipse(x, y, w, h, paper, outline=colour, outline_width=3)
        label = self.centered_text((x + 6, y + 6, x + w - 6, y + h - 6), text, colour, scale)
        return self._record(name, "stamp", ring.pixels, (ring, label), text=label.attrs["text"])

    def signature(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        colour: Any = "navy",
        *,
        strokes: int = 8,
        name: str | None = None,
    ) -> Drawn:
        """A scribble that stands for a signature: a seeded zig-zag across the ``w`` x ``h`` area.

        It never reads as a name. The box is the extent of the strokes (2 pixels wide), which
        stays inside the area.
        """
        _int(strokes, "strokes", minimum=2)
        if w < 20 or h < 10:
            raise ValueError("a signature needs at least 20x10 pixels")
        points = [
            (x + 1 + (i * (w - 3)) // (strokes - 1), y + 1 + self.rng.below(h - 3))
            for i in range(strokes)
        ]
        parts = tuple(self.line(*points[i], *points[i + 1], colour, 2) for i in range(strokes - 1))
        return self._record(name, "signature", self._union(parts), parts)

    def schematic_symbol(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        symbol: str,
        colour: Any = "ink",
        *,
        name: str | None = None,
    ) -> Drawn:
        """A line-drawn symbol ('resistor', 'capacitor', 'valve' or 'ground') with leads."""
        if w < 40 or h < 24:
            raise ValueError("a symbol needs at least 40x24 pixels")
        cx, cy = x + w // 2, y + h // 2
        pen = _colour(colour)
        parts: list[Drawn]
        if symbol == "resistor":
            step = (w - 2 * (w // 6)) // 6
            xs = [x + w // 6 + i * step for i in range(7)]
            zig = [(xs[i], cy + (h // 4 if i % 2 else -(h // 4))) for i in range(1, 6)]
            path = [(x, cy), (xs[0], cy), *zig, (xs[6], cy), (x + w - 1, cy)]
            parts = [self.line(*a, *b, pen, 2) for a, b in zip(path, path[1:], strict=False)]
        elif symbol == "capacitor":
            gap = max(3, w // 12)
            tall = (h * 3) // 4
            parts = [
                self.line(x, cy, cx - gap, cy, pen, 2),
                self.line(cx - gap, cy - tall // 2, cx - gap, cy + tall // 2, pen, 3),
                self.line(cx + gap, cy - tall // 2, cx + gap, cy + tall // 2, pen, 3),
                self.line(cx + gap, cy, x + w - 1, cy, pen, 2),
            ]
        elif symbol == "valve":
            half, tall = w // 4, (h * 3) // 4
            parts = [
                self.line(x, cy, cx - half, cy, pen, 2),
                self.triangle(cx - half, cy - tall // 2, half, tall, pen, direction="right"),
                self.triangle(cx, cy - tall // 2, half, tall, pen, direction="left"),
                self.line(cx + half, cy, x + w - 1, cy, pen, 2),
            ]
        elif symbol == "ground":
            parts = [self.line(cx, y, cx, y + h // 2, pen, 2)]
            for i in range(3):
                half = (w // 2) - i * (w // 6)
                row = y + h // 2 + i * 5
                parts.append(self.line(cx - half, row, cx + half, row, pen, 2))
        else:
            raise ValueError("symbol must be 'resistor', 'capacitor', 'valve' or 'ground'")
        return self._record(name, "symbol", self._union(parts), tuple(parts), symbol=symbol)

    # -- a UI mock: window, button, input, dialog, banner, spinner, bar --

    def window(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        title: str,
        *,
        name: str | None = None,
        title_height: int = 26,
        scale: int = 2,
    ) -> Drawn:
        """A window with a title bar and three control squares. ``attrs["content"]`` is the
        pixel rectangle below the title bar, inside the frame."""
        _int(title_height, "title_height", minimum=GLYPH_HEIGHT * scale + 4)
        control = title_height - 10
        if w < 160 or h < title_height + 40:
            raise ValueError("a window needs at least 160 pixels across and title_height + 40 down")
        if text_width(title, scale) > w - 20 - 3 * (control + 4):
            raise ValueError(f"the title {title!r} does not fit the title bar")
        body = self.rect(
            x, y, w, h, "white", outline="dark", name=_sub(name, "body"), kind="window-body"
        )
        bar = self.rect(
            x, y, w, title_height, "dark", name=_sub(name, "title_bar"), kind="title-bar"
        )
        label = self.text(
            x + 10, y + (title_height - GLYPH_HEIGHT * scale) // 2, title, "white", scale
        )
        top = y + 5
        close = self.rect(
            x + w - 6 - control,
            top,
            control,
            control,
            "red",
            name=_sub(name, "close"),
            kind="close",
        )
        self.line(close.left + 3, close.top + 3, close.right - 4, close.bottom - 4, "white")
        self.line(close.left + 3, close.bottom - 4, close.right - 4, close.top + 3, "white")
        maximise = self.rect(
            x + w - 10 - 2 * control,
            top,
            control,
            control,
            "grey",
            outline="light",
            name=_sub(name, "maximize"),
            kind="maximize",
        )
        minimise = self.rect(
            x + w - 14 - 3 * control,
            top,
            control,
            control,
            "grey",
            name=_sub(name, "minimize"),
            kind="minimize",
        )
        self.line(
            minimise.left + 3, minimise.bottom - 5, minimise.right - 4, minimise.bottom - 5, "ink"
        )
        return self._record(
            name,
            "window",
            body.pixels,
            (body, bar, label, close, maximise, minimise),
            title=label.attrs["text"],
            content=(x + 1, y + title_height, x + w - 1, y + h - 1),
        )

    def button(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        label: str,
        *,
        style: str = "primary",
        scale: int = 2,
        name: str | None = None,
    ) -> Drawn:
        """A button; ``style`` is 'primary', 'secondary', 'danger' or 'disabled'."""
        styles = {
            "primary": ("blue", "white", "dark"),
            "secondary": ("white", "ink", "mid"),
            "danger": ("red", "white", "dark"),
            "disabled": ("grey", "mid", "grey"),
        }
        if style not in styles:
            raise ValueError(f"style must be one of {sorted(styles)}")
        if text_width(label, scale) > w - 8 or GLYPH_HEIGHT * scale > h - 4:
            raise ValueError(f"the label {label!r} does not fit a {w}x{h} button")
        fill, ink, edge = styles[style]
        body = self.rect(x, y, w, h, fill, outline=edge)
        text = self.centered_text(body, label, ink, scale)
        return self._record(
            name, "button", body.pixels, (body, text), style=style, label=text.attrs["text"]
        )

    def text_input(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        value: str = "",
        *,
        placeholder: str = "",
        label: str | None = None,
        focused: bool = False,
        invalid: bool = False,
        masked: bool = False,
        scale: int = 2,
        name: str | None = None,
    ) -> Drawn:
        """A text field. ``label`` is drawn above it (outside the returned box); ``masked``
        shows one asterisk per character; an empty ``value`` shows ``placeholder`` in grey."""
        edge, width = ("red", 2) if invalid else (("blue", 2) if focused else ("mid", 1))
        shown = "*" * len(value) if masked else value
        content = shown or placeholder
        if content and text_width(content, scale) > w - 12:
            raise ValueError(f"{content!r} does not fit a {w}-pixel input")
        if GLYPH_HEIGHT * scale > h - 4:
            raise ValueError(f"an input {h} pixels tall cannot hold scale-{scale} text")
        parts = []
        if label is not None:
            parts.append(
                self.text(
                    x, y - GLYPH_HEIGHT * scale - 6, label, "ink", scale, name=_sub(name, "label")
                )
            )
        body = self.rect(x, y, w, h, "white", outline=edge, outline_width=width)
        parts.append(body)
        if content:
            parts.append(
                self.text(
                    x + 6,
                    y + (h - GLYPH_HEIGHT * scale) // 2,
                    content,
                    "ink" if shown else "mid",
                    scale,
                )
            )
        return self._record(
            name,
            "text-input",
            body.pixels,
            tuple(parts),
            value=shown,
            placeholder=placeholder,
            focused=focused,
            invalid=invalid,
        )

    def dialog(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        title: str,
        message: Sequence[str],
        *,
        buttons: Sequence[str] = ("OK",),
        dim_backdrop: int | None = None,
        scale: int = 2,
        name: str | None = None,
    ) -> Drawn:
        """A modal dialog: title strip, message lines and a right-aligned row of buttons.

        ``dim_backdrop`` (a brightness percent such as 55) darkens everything already drawn
        before the dialog goes on; the dialog's box excludes the backdrop.
        """
        title_height, button_height = 26, 30
        widths = [max(80, text_width(b, scale) + 24) for b in buttons]
        row = sum(widths) + 10 * (len(widths) - 1)
        lines_height = len(message) * (GLYPH_HEIGHT + 3) * scale
        if (
            not buttons
            or row > w - 32
            or title_height + 14 + lines_height + 14 + button_height + 14 > h
            or any(text_width(m, scale) > w - 32 for m in message)
            or text_width(title, scale) > w - 20
        ):
            raise ValueError("the dialog's title, message and buttons do not fit its size")
        if dim_backdrop is not None:
            self.lighting(dim_backdrop)
        body = self.rect(x, y, w, h, "white", outline="ink", outline_width=2, kind="dialog-body")
        bar = self.rect(x + 2, y + 2, w - 4, title_height - 2, "dark", kind="title-bar")
        label = self.text(
            x + 10, y + 2 + (title_height - 2 - GLYPH_HEIGHT * scale) // 2, title, "white", scale
        )
        text = self.text_block(x + 16, y + title_height + 14, message, "ink", scale)
        parts = [body, bar, label, text]
        left = x + w - 16 - row
        for index, caption in enumerate(buttons):
            parts.append(
                self.button(
                    left,
                    y + h - 14 - button_height,
                    widths[index],
                    button_height,
                    caption,
                    style="primary" if index == 0 else "secondary",
                    scale=scale,
                    name=_sub(name, f"button{index}"),
                )
            )
            left += widths[index] + 10
        return self._record(
            name,
            "dialog",
            body.pixels,
            tuple(parts),
            title=label.attrs["text"],
            buttons=list(buttons),
        )

    def error_banner(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        message: str,
        *,
        level: str = "error",
        scale: int = 2,
        name: str | None = None,
    ) -> Drawn:
        """A banner with a round icon and one line of text; ``level`` is error, warning or info."""
        levels = {
            "error": ((252, 228, 228), "red", "!"),
            "warning": ((253, 240, 213), "amber", "!"),
            "info": ((225, 236, 252), "blue", "I"),
        }
        if level not in levels:
            raise ValueError(f"level must be one of {sorted(levels)}")
        fill, accent, glyph = levels[level]
        icon_size = h - 12
        if icon_size < GLYPH_HEIGHT * scale + 4 or text_width(message, scale) > w - icon_size - 36:
            raise ValueError(f"the banner message {message!r} does not fit a {w}x{h} banner")
        body = self.rect(x, y, w, h, fill, outline=accent, outline_width=2)
        icon = self.ellipse(x + 10, y + 6, icon_size, icon_size, accent)
        mark = self.centered_text(icon, glyph, "white", scale)
        text = self.text(
            x + 20 + icon_size, y + (h - GLYPH_HEIGHT * scale) // 2, message, "ink", scale
        )
        return self._record(
            name,
            "banner",
            body.pixels,
            (body, icon, mark, text),
            level=level,
            message=text.attrs["text"],
        )

    def spinner(
        self,
        cx: int,
        cy: int,
        radius: int,
        *,
        phase: int = 0,
        colour: Any = "blue",
        track: Any = "grey",
        name: str | None = None,
    ) -> Drawn:
        """Eight spokes around ``(cx, cy)``; spoke ``phase`` is darkest and the rest fade to
        ``track``. Two phases of one spinner differ only in which spoke is dark."""
        _int(radius, "radius", minimum=10)
        phase = _int(phase, "phase") % 8
        inner, thickness = (radius * 4) // 10, max(2, radius // 6)
        diagonal = lambda n: (n * 707) // 1000  # noqa: E731 - sin 45 degrees, in integers
        directions = [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)]
        parts = []
        for spoke, (dx, dy) in enumerate(directions):
            ratio = diagonal if dx and dy else (lambda n: n)
            shade = mix(colour, track, ((spoke - phase) % 8) * 100 // 7)
            parts.append(
                self.line(
                    cx + dx * ratio(inner),
                    cy + dy * ratio(inner),
                    cx + dx * ratio(radius),
                    cy + dy * ratio(radius),
                    shade,
                    thickness,
                )
            )
        return self._record(name, "spinner", self._union(parts), tuple(parts), phase=phase)

    def bar(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        fraction: Any,
        *,
        fill: Any = "green",
        back: Any = "dark",
        outline: Any = "ink",
        name: str | None = None,
    ) -> Drawn:
        """A progress or health bar. The filled part is ``floor(fraction * (w - 2))`` pixels."""
        share = _fraction(fraction, "fraction")
        if w < 6 or h < 4:
            raise ValueError("a bar needs at least 6x4 pixels")
        body = self.rect(x, y, w, h, back, outline=outline)
        filled = math.floor(share * (w - 2))
        if filled:
            self._fill(x + 1, y + 1, x + 1 + filled, y + h - 1, _colour(fill))
        return self._record(
            name, "bar", body.pixels, (body,), fraction=float(share), filled_pixels=filled
        )

    # -- a fictional logo --

    def wordmark(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        style_seed: int = 0,
        text: str | None = None,
        emblem: str | None = None,
        colour: Any = None,
        name: str | None = None,
    ) -> Drawn:
        """An invented logo: a geometric emblem (``h`` x ``h``) and a name beside it.

        ``style_seed`` picks the name, emblem and colour; any of them can be overridden, which
        is how a recipe makes an off-brand variant of a reference logo. The names come from
        :func:`fictional_name`; they are pronounceable nonsense and not cleared against real
        trademarks, so a reviewer rejects any that happens to match a real brand.
        """
        rng = Rng(style_seed)
        text = _fold(text if text is not None else fictional_name(style_seed))
        emblem = emblem if emblem is not None else rng.choice(_EMBLEMS)
        colour = _colour(colour if colour is not None else rng.choice(_LOGO_COLOURS))
        if emblem not in _EMBLEMS:
            raise ValueError(f"emblem must be one of {_EMBLEMS}")
        side, gap = h, max(6, h // 4)
        if w < side + gap + text_width(text, 1):
            raise ValueError(f"{text!r} does not fit a {w}x{h} wordmark")
        if emblem == "disc":
            mark = self.ellipse(x, y, side, side, colour)
        elif emblem == "ring":
            mark = self.ellipse(x, y, side, side, colour)
            hole = self.ellipse(
                x + side // 4, y + side // 4, side - side // 2, side - side // 2, self.background
            )
            mark = Drawn(None, "ring", *mark.pixels, self.size, (mark, hole))
        elif emblem == "triangle":
            mark = self.triangle(x, y, side, side, colour)
        elif emblem == "bars":
            bar_w = max(1, side // 5)
            bars = [
                self.rect(x, y, bar_w, side, colour),
                self.rect(x + (side - bar_w) // 2, y + side // 3, bar_w, side - side // 3, colour),
                self.rect(x + side - bar_w, y + side // 2, bar_w, side - side // 2, colour),
            ]
            mark = Drawn(None, "bars", *self._union(bars), self.size, tuple(bars))
        else:
            third = max(1, side // 3)
            tiers = [
                self.rect(x, y, side, third, colour),
                self.rect(x + side // 6, y + (side - third) // 2, side - side // 3, third, colour),
                self.rect(x, y + side - third, side, third, colour),
            ]
            mark = Drawn(None, "stack", *self._union(tiers), self.size, tuple(tiers))
        scale = fit_scale(text, w - side - gap, h)
        words = self.text(x + side + gap, y + (h - GLYPH_HEIGHT * scale) // 2, text, colour, scale)
        return self._record(
            name,
            "wordmark",
            self._union([mark, words]),
            (mark, words),
            text=text,
            emblem=emblem,
            colour=list(colour),
        )

    # -- defects --

    def scratch(
        self,
        target: Any,
        *,
        colour: Any = "light",
        width: int = 1,
        start: Sequence[int] | None = None,
        end: Sequence[int] | None = None,
        name: str | None = None,
    ) -> Drawn:
        """A thin line across ``target`` (a Drawn, a name or a pixel rectangle).

        Without ``start``/``end`` the ends are drawn from the canvas's random stream, the start
        in the left 40 percent and the end in the right 40 percent of the target, both at least
        10 percent in from the top and bottom, so the scratch never leaves the target.
        """
        left, top, right, bottom = self._target(target)
        tw, th = right - left, bottom - top
        if tw < 40 or th < 40:
            raise ValueError("a scratch needs a target at least 40x40 pixels")
        width = _int(width, "width", minimum=1)
        if start is None:
            start = (
                left + tw // 10 + self.rng.below(tw * 3 // 10),
                top + th // 10 + self.rng.below(th * 8 // 10),
            )
        if end is None:
            end = (
                right - tw // 10 - 1 - self.rng.below(tw * 3 // 10),
                top + th // 10 + self.rng.below(th * 8 // 10),
            )
        for px, py in (start, end):
            if not (left + width <= px < right - width and top + width <= py < bottom - width):
                raise ValueError("a scratch must stay inside its target")
        drawn = self.line(*start, *end, colour, width, kind="scratch")
        return self._record(name, "scratch", drawn.pixels, start=list(start), end=list(end))

    def dent(
        self,
        target: Any,
        *,
        depth_percent: int = 30,
        size_percent: int = 40,
        name: str | None = None,
    ) -> Drawn:
        """Radial shading: an ellipse inside ``target`` whose centre is darkened by up to
        ``depth_percent`` and fades to nothing at its rim. The box is the pixels that changed."""
        left, top, right, bottom = self._target(target)
        tw, th = right - left, bottom - top
        if tw < 30 or th < 30:
            raise ValueError("a dent needs a target at least 30x30 pixels")
        if not 1 <= _int(depth_percent, "depth_percent") <= 100:
            raise ValueError("depth_percent must be from 1 to 100")
        if not 10 <= _int(size_percent, "size_percent") <= 100:
            raise ValueError("size_percent must be from 10 to 100")
        dw, dh = max(6, tw * size_percent // 100), max(6, th * size_percent // 100)
        ox, oy = left + self.rng.below(tw - dw + 1), top + self.rng.below(th - dh + 1)
        q = dw * dw * dh * dh
        pixels = self.image.load()
        changed = None
        for row, first, last in _ellipse_spans(dw, dh):
            ty = 2 * row + 1 - dh
            for col in range(first, last + 1):
                tx = 2 * col + 1 - dw
                depth = depth_percent * (q - tx * tx * dh * dh - ty * ty * dw * dw)
                old = pixels[ox + col, oy + row]
                new = tuple((v * (100 * q - depth) + 50 * q) // (100 * q) for v in old)
                if new != old:
                    pixels[ox + col, oy + row] = new
                    cell = (ox + col, oy + row, ox + col + 1, oy + row + 1)
                    changed = cell if changed is None else _merge(changed, cell)
        if changed is None:
            raise ValueError(
                "the dent changed no pixel; raise depth_percent or use a darker surface"
            )
        return self._record(name, "dent", changed, depth_percent=depth_percent)

    def missing_part(self, part: Any, fill: Any = None, *, name: str | None = None) -> Drawn:
        """Remove a drawn part by painting its rectangle with ``fill`` (default: the canvas
        background). The part's name leaves the ledger; the returned Drawn (kind
        'missing-part') is the box where the part should have been."""
        left, top, right, bottom = self._target(part)
        before = self.image.crop((left, top, right, bottom))
        self._fill(left, top, right, bottom, _colour(fill if fill is not None else self.background))
        box = ImageChops.difference(before, self.image.crop((left, top, right, bottom))).getbbox()
        if box is None:
            raise ValueError("painting over the part changed nothing; it was already this colour")
        label = part.name if isinstance(part, Drawn) else part if isinstance(part, str) else None
        if label is not None:
            self.objects.pop(label, None)
        return self._record(
            name,
            "missing-part",
            (left + box[0], top + box[1], left + box[2], top + box[3]),
            part=label,
        )

    # -- perturbations --

    def _region(self, region: Any) -> Pixels:
        return (0, 0, self.width, self.height) if region is None else self._target(region)

    def blur(self, radius: int, *, region: Any = None, name: str | None = None) -> Drawn:
        """Separable integer box blur, window ``2 * radius + 1``, edges clamped to the region."""
        radius = _int(radius, "radius", minimum=1)
        if radius > 20:
            raise ValueError("radius must be at most 20")
        rect = self._region(region)
        patch = self.image.crop(rect)
        patch = _box_blur_rows(patch, radius)
        patch = _box_blur_rows(patch.transpose(Image.Transpose.TRANSPOSE), radius)
        self.image.paste(patch.transpose(Image.Transpose.TRANSPOSE), rect[:2])
        return self._record(name, "blur", rect, radius=radius)

    def noise(
        self, amount: int, *, region: Any = None, grey: bool = True, name: str | None = None
    ) -> Drawn:
        """Add noise of about ``-amount..amount`` per channel from the canvas's random stream
        (a byte modulo ``2 * amount + 1``, so very slightly uneven); ``grey`` adds the same
        value to the three channels. Results clamp to 0..255."""
        amount = _int(amount, "amount", minimum=1)
        if amount > 127:
            raise ValueError("amount must be at most 127")
        rect = self._region(region)
        patch = self.image.crop(rect)
        count = patch.width * patch.height
        table = bytes(b % (2 * amount + 1) for b in range(256))
        if grey:
            single = self.rng.bytes(count).translate(table)
            noise = bytearray(3 * count)
            noise[0::3] = noise[1::3] = noise[2::3] = single
        else:
            noise = bytearray(self.rng.bytes(3 * count).translate(table))
        data = patch.tobytes()
        mixed = bytes(
            0 if v < 0 else 255 if v > 255 else v
            for v in (a + b - amount for a, b in zip(data, noise, strict=True))
        )
        self.image.paste(Image.frombytes("RGB", patch.size, mixed), rect[:2])
        return self._record(name, "noise", rect, amount=amount, grey=grey)

    def lighting(
        self,
        brightness_percent: int = 100,
        *,
        gradient_percent: int = 0,
        region: Any = None,
        name: str | None = None,
    ) -> Drawn:
        """Scale brightness to ``brightness_percent`` (100 = unchanged, halves round up). With a
        ``gradient_percent`` the percent rises left to right by that many points across the
        region, centred on ``brightness_percent`` (a shadow or glare)."""
        _int(brightness_percent, "brightness_percent", minimum=0)
        _int(gradient_percent, "gradient_percent")
        rect = self._region(region)
        patch = self.image.crop(rect)
        if gradient_percent == 0:
            patch = patch.point(_brightness_table(brightness_percent))
        else:
            width = patch.width
            for column in range(width):
                percent = max(
                    0,
                    brightness_percent
                    + (gradient_percent * (2 * column + 1 - width)) // (2 * width),
                )
                strip = patch.crop((column, 0, column + 1, patch.height))
                patch.paste(strip.point(_brightness_table(percent)), (column, 0))
        self.image.paste(patch, rect[:2])
        return self._record(
            name,
            "lighting",
            rect,
            brightness_percent=brightness_percent,
            gradient_percent=gradient_percent,
        )

    def occlude(
        self,
        target: Any,
        *,
        fraction: Any = 0.5,
        side: str = "right",
        fill: Any = "black",
        name: str | None = None,
    ) -> Drawn:
        """Cover ``fraction`` of ``target`` from one ``side`` ('left', 'right', 'top', 'bottom')
        with a solid patch of ``round_half_up(fraction * extent)`` pixels. The returned Drawn is
        the patch; the target keeps its own gold box (it is still there, partly hidden)."""
        left, top, right, bottom = self._target(target)
        share = _fraction(fraction, "fraction")
        if side not in ("left", "right", "top", "bottom"):
            raise ValueError("side must be 'left', 'right', 'top' or 'bottom'")
        horizontal = side in ("left", "right")
        depth = _round_half_up(share * ((right - left) if horizontal else (bottom - top)))
        if depth < 1:
            raise ValueError("the occluder would be less than one pixel")
        rects = {
            "left": (left, top, left + depth, bottom),
            "right": (right - depth, top, right, bottom),
            "top": (left, top, right, top + depth),
            "bottom": (left, bottom - depth, right, bottom),
        }
        x0, y0, x1, y1 = rects[side]
        return self.rect(
            x0,
            y0,
            x1 - x0,
            y1 - y0,
            fill,
            name=name,
            kind="occlusion",
            side=side,
            fraction=float(share),
        )

    # -- output --

    def png(self) -> bytes:
        """The canvas as canonical PNG bytes (see :func:`encode_png`)."""
        return encode_png(self.image)

    def write(self, recipe_dir: Any, path: str, *, overwrite: bool = False) -> str:
        """:func:`write_asset` for this canvas."""
        return write_asset(self.image, recipe_dir, path, overwrite=overwrite)

    def manifest_entry(
        self, recipe_dir: Any, path: str, description: str, licence: str = "CC0-1.0"
    ) -> dict[str, Any]:
        """The manifest entry of the saved file, with this canvas's generator and parameters."""
        if self.generator is None or self.parameters is None:
            raise ValueError(
                "call provenance(generator, parameters) first, or use an example scene"
            )
        return manifest_entry(
            recipe_dir, path, self.generator, self.parameters, description, licence
        )


def _brightness_table(percent: int) -> list[int]:
    return [min(255, (v * percent + 50) // 100) for v in range(256)] * 3


def _box_blur_rows(image: Image.Image, radius: int) -> Image.Image:
    """Horizontal box blur of an RGB image with clamped edges and integer rounding."""
    width, height = image.size
    window = 2 * radius + 1
    data = image.tobytes()
    out = bytearray(len(data))
    stride = width * 3
    for y in range(height):
        row = data[y * stride : (y + 1) * stride]
        for channel in range(3):
            values = row[channel::3]
            padded = [values[0]] * radius + list(values) + [values[-1]] * radius
            total = list(accumulate(padded, initial=0))
            out[y * stride + channel : (y + 1) * stride : 3] = bytes(
                (total[i + window] - total[i] + radius) // window for i in range(width)
            )
    return Image.frombytes("RGB", image.size, bytes(out))


# --- PNG output, the byte-stability policy and the manifest -------------------------------------


class RegenerationMismatch(ValueError):
    """A regenerated image differs from the committed file; nothing was written.

    A different image changes every replay key that hashes it (``backends.replay_key``), so a
    mismatch is a decision for a person: fix the generator, or pass ``overwrite=True`` and then
    rebuild the fixtures' ``replay_keys`` and responses.
    """


def _check_png(data: bytes) -> None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    position, names = 8, []
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        names.append(data[position + 4 : position + 8])
        position += 12 + length
    stray = [n.decode("ascii", "replace") for n in names if n not in _PNG_CHUNKS]
    if stray or position != len(data):
        raise ValueError(f"the PNG holds chunks beyond IHDR, IDAT and IEND: {stray}")
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError(f"the PNG is {len(data)} bytes; a recipe asset may hold {MAX_ASSET_BYTES}")


def encode_png(image: Image.Image) -> bytes:
    """RGB PNG bytes with only the IHDR, IDAT and IEND chunks (no text, time, profile or dpi).

    The *pixels* are exactly the image's; the *bytes* come from Pillow's zlib at a fixed
    compression level and are canonical only where :func:`bytes_are_canonical` is true (see
    :func:`write_asset`). Raises ``ValueError`` before anything is written for an image outside
    the API's limits (``vision.validate_image_asset``: a side under 280 pixels, say), for stray
    chunks, and for a file over ``MAX_ASSET_BYTES``.
    """
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "PNG", **_PNG_SAVE)
    data = buffer.getvalue()
    _check_png(data)
    # The API's size limits (280 to 1568 pixels a side, the area range): checked on the exact
    # bytes that would be written, so a rejected image never reaches the disk.
    validate_image_asset(
        {"type": "image", "format": "png", "data_base64": base64.b64encode(data).decode("ascii")}
    )
    return data


def _pixels(data: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(io.BytesIO(data)) as decoded:
        rgb = decoded.convert("RGB")
    return rgb.size, rgb.tobytes()


def png_pixels_equal(first: bytes, second: bytes) -> bool:
    """Do two PNG files decode to the same size and RGB pixels? (Their bytes may differ.)"""
    return _pixels(first) == _pixels(second)


def pixels_sha256(source: Image.Image | bytes) -> str:
    """SHA-256 of the decoded RGB pixels (``<w>x<h>:`` then the raw bytes), for PNG bytes or an image."""
    if isinstance(source, bytes):
        size, raw = _pixels(source)
    else:
        rgb = source.convert("RGB")
        size, raw = rgb.size, rgb.tobytes()
    return hashlib.sha256(f"{size[0]}x{size[1]}:".encode() + raw).hexdigest()


_ASSET_PATH = re.compile(r"^assets/([A-Za-z0-9][A-Za-z0-9_.-]*/)*[A-Za-z0-9][A-Za-z0-9_.-]*[.]png$")


def bytes_are_canonical() -> bool:
    """Are the PNG bytes this environment produces the repository's canonical bytes?

    True only for the pinned Pillow (``CANONICAL_PILLOW``) linked to the zlib its wheel bundles
    (``CANONICAL_ZLIB``). Elsewhere equal decoded pixels are what counts.
    """
    return PIL.__version__ == CANONICAL_PILLOW and features.version("zlib") == CANONICAL_ZLIB


def _compare(existing: bytes, regenerated: bytes, label: str) -> str:
    """'unchanged' or 'kept-committed-bytes', else RegenerationMismatch."""
    if existing == regenerated:
        return "unchanged"
    try:
        same_pixels = png_pixels_equal(existing, regenerated)
    except (OSError, ValueError):
        same_pixels = False
    if not same_pixels:
        raise RegenerationMismatch(
            f"{label}: the regenerated pixels differ from the committed file, so the generator, "
            "its parameters or the seed changed the picture; nothing written"
        )
    if bytes_are_canonical():
        # The pixels are equal, so this encoder would have written exactly the committed bytes
        # had it written them: the committed file was not written by the canonical encoder.
        # The generator is not at fault.
        raise RegenerationMismatch(
            f"{label}: same pixels, but the committed bytes are not what the canonical encoder "
            f"(Pillow {CANONICAL_PILLOW}, zlib {CANONICAL_ZLIB}) writes for them, so the file "
            "was created under another Pillow or zlib, re-saved by another tool, or written with "
            "other encoder settings. Recreate it under the notebook constraints pin "
            "(docs/synthetic-images.md) with overwrite=True; nothing written"
        )
    return "kept-committed-bytes"


def write_asset(
    image: Image.Image | Canvas, recipe_dir: Any, path: str, *, overwrite: bool = False
) -> str:
    """Save ``image`` as ``recipe_dir/path`` (``assets/<name>.png``) under the byte policy.

    * file absent: written; returns ``'created'``;
    * same bytes: returns ``'unchanged'``;
    * different bytes, same decoded pixels, and ``bytes_are_canonical()`` is false: the committed
      bytes are kept (they are canonical); returns ``'kept-committed-bytes'``;
    * different pixels, or different bytes where ``bytes_are_canonical()`` is true: raises
      :class:`RegenerationMismatch` and writes nothing, unless ``overwrite=True`` (returns
      ``'rewritten'``). Rewriting changes the file's hash, so rebuild ``replay_keys`` after it.

    Create committed assets under the notebook constraints pin, so the bytes are canonical.
    Everything is checked before any file is touched: the path (``vision.resolve_asset_path``),
    the image against the API's limits (``vision.validate_image_asset``), the chunks and the
    1 MiB cap. A rejected image raises ``ValueError`` and leaves nothing on disk; a file is
    written to a temporary name and renamed, so a failure part-way leaves none either.
    """
    if not isinstance(path, str) or not _ASSET_PATH.match(path):
        raise ValueError("path must look like 'assets/name.png' (forward slashes, lowercase .png)")
    return _store(image, resolve_asset_path(path, root=recipe_dir), overwrite)


def write_png(image: Image.Image | Canvas, target: Any, *, overwrite: bool = False) -> str:
    """:func:`write_asset` for any file path (documentation images, scratch files): the same
    four outcomes and the same checks, without the ``assets/`` path rule."""
    return _store(image, Path(target), overwrite)


def _store(image: Image.Image | Canvas, target: Path, overwrite: bool) -> str:
    if isinstance(image, Canvas):
        image = image.image
    data = encode_png(image)  # raises before anything exists on disk
    status = "created"
    if target.exists():
        existing = target.read_bytes()
        if existing == data:
            return "unchanged"
        if not overwrite:
            return _compare(existing, data, target.name)
        status = "rewritten"
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(name, target)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return status


def _check_generator(recipe_dir: Path, generator: str) -> None:
    module, _, function = generator.partition(":")
    if module.endswith(".py"):
        script = recipe_dir / module
        if not script.is_file() or function not in script.read_text("utf-8"):
            raise ValueError(f"{module} is not a script in the recipe that mentions {function!r}")
    elif module.startswith("jev_cookbook."):
        try:
            target = getattr(importlib.import_module(module), function, None)
        except ImportError as exc:
            raise ValueError(f"{module} cannot be imported") from exc
        if not callable(target):
            raise ValueError(f"{generator} does not name a function")
    else:
        raise ValueError("generator must be 'script.py:function' or 'jev_cookbook.module:function'")


def manifest_entry(
    recipe_dir: Any,
    path: str,
    generator: str,
    parameters: Mapping[str, Any],
    description: str,
    licence: str = "CC0-1.0",
) -> dict[str, Any]:
    """One ``assets-manifest.json`` entry for the saved file (docs/fixtures.md).

    The hash, format and size are read from the file; the five attestations are the true ones
    for a generated image (``synthetic`` only). ``generator`` must exist: a ``script.py:function``
    in the recipe that mentions the function, or a function of a ``jev_cookbook`` module. The
    current directory does not matter.
    """
    root = Path(recipe_dir)
    _check_generator(root, generator)
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must say what the image shows")
    data = (root / path).read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        fmt, (width, height) = image.format, image.size
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": fmt,
        "width": width,
        "height": height,
        "origin": "generated",
        "generator": generator,
        "parameters": _json_parameters(parameters),
        "licence": licence,
        "description": description,
        "attestations": {
            "synthetic": True,
            "real_photo": False,
            "real_brand": False,
            "real_person": False,
            "third_party_content": False,
        },
    }


def reproduce(generator: str, parameters: Mapping[str, Any]) -> Canvas:
    """Rebuild a canvas from a manifest ``generator`` and ``parameters``.

    Only the example scenes of this module (:data:`SCENES`) can be rebuilt this way; a recipe's
    own ``script.py:function`` is rebuilt by running its script.
    """
    module, _, function = generator.partition(":")
    if module != "jev_cookbook.synthetic_images" or function not in SCENES:
        raise ValueError(f"{generator!r} is not one of {sorted(SCENES)} of this module")
    return SCENES[function](**parameters)


def check_reproducible(recipe_dir: Any, entry: Mapping[str, Any]) -> str:
    """Regenerate a manifest entry's image from its generator and parameters and compare it
    with the committed file under the byte policy. Returns 'unchanged' or
    'kept-committed-bytes'; raises :class:`RegenerationMismatch` otherwise. Writes nothing."""
    canvas = reproduce(entry["generator"], entry["parameters"])
    committed = (Path(recipe_dir) / entry["path"]).read_bytes()
    return _compare(committed, canvas.png(), entry["path"])


# --- frame sequences ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    """One still of a sequence: its elapsed time in seconds and the canvas drawn for it."""

    timestamp_seconds: float
    canvas: Canvas

    @property
    def image(self) -> Image.Image:
        return self.canvas.image

    @property
    def objects(self) -> dict[str, Drawn]:
        return self.canvas.objects


def build_frames(times: Sequence[float], draw_frame: Callable[[float], Canvas]) -> list[Frame]:
    """Call ``draw_frame(t)`` for each explicit time. Times must be finite, non-negative and
    strictly increasing (as ``vision.load_frames`` requires), so no spacing is assumed."""
    if isinstance(times, (str, bytes)) or not times:
        raise ValueError("times must be a non-empty sequence of seconds")
    previous = -1.0
    for t in times:
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
            raise ValueError("every time must be a finite, non-negative number of seconds")
        if t <= previous:
            raise ValueError("times must be strictly increasing")
        previous = t
    return [Frame(float(t), draw_frame(t)) for t in times]


def save_frames(
    frames: Sequence[Frame], recipe_dir: Any, stem: str, *, overwrite: bool = False
) -> list[tuple[float, str]]:
    """Write ``assets/<stem>-00.png``, ``-01``, ... under the byte policy of
    :func:`write_asset`, and return ``(timestamp_seconds, path)`` pairs, which is exactly what
    ``vision.load_frames(pairs, root=recipe_dir)`` takes."""
    pairs = []
    for index, frame in enumerate(frames):
        path = f"assets/{stem}-{index:02d}.png"
        write_asset(frame.canvas, recipe_dir, path, overwrite=overwrite)
        pairs.append((frame.timestamp_seconds, path))
    return pairs


# --- example scenes -----------------------------------------------------------------------------
# Pure functions of JSON-able keyword arguments, so a manifest's generator and parameters rebuild
# them. Changing what a scene draws is a foundation change: tests pin its pixels.

SCENES: dict[str, Callable[..., Canvas]] = {}


def _scene(function: Callable[..., Canvas]) -> Callable[..., Canvas]:
    signature = inspect.signature(function)

    @functools.wraps(function)
    def wrapper(**kwargs: Any) -> Canvas:
        bound = signature.bind(**kwargs)
        bound.apply_defaults()
        canvas = function(**bound.arguments)
        return canvas.provenance(
            f"jev_cookbook.synthetic_images:{function.__name__}", bound.arguments
        )

    SCENES[function.__name__] = wrapper
    return wrapper


@_scene
def login_screen(*, state: str = "normal", seed: int = 0) -> Canvas:
    """A 640x400 sign-in window in one of four states: 'normal', 'error' (banner and a red
    field), 'loading' (disabled button and a spinner) or 'crash' (a dimmed modal dialog).

    Objects: window, logo, username, password, submit, and error_banner, spinner or dialog.
    ``seed`` picks the invented product name and logo.
    """
    if state not in ("normal", "error", "loading", "crash"):
        raise ValueError("state must be 'normal', 'error', 'loading' or 'crash'")
    c = Canvas(640, 400, "light", seed=seed)
    brand = fictional_name(seed)
    c.window(60, 30, 520, 340, f"{brand} SIGN IN", name="window")
    c.wordmark(400, 112, 160, 48, style_seed=seed, text=brand, name="logo")
    if state == "error":
        c.error_banner(80, 66, 480, 32, "INCORRECT PASSWORD. TRY AGAIN.", name="error_banner")
    c.text_input(
        80, 132, 300, 34, "DEMO.USER", label="USERNAME", focused=state == "normal", name="username"
    )
    c.text_input(
        80,
        200,
        300,
        34,
        "SECRET1",
        label="PASSWORD",
        masked=True,
        invalid=state == "error",
        name="password",
    )
    if state == "loading":
        c.button(80, 262, 140, 40, "SIGNING IN", style="disabled", name="submit")
        c.spinner(250, 282, 16, name="spinner")
    else:
        c.button(80, 262, 140, 40, "SIGN IN", name="submit")
    if state == "crash":
        c.dialog(
            150,
            110,
            340,
            170,
            "APPLICATION ERROR",
            ["UNEXPECTED FAILURE.", "CODE E-500"],
            buttons=("RESTART", "CLOSE"),
            dim_backdrop=55,
            name="dialog",
        )
    return c


@_scene
def part_photo(*, defect: str = "none", seed: int = 0) -> Canvas:
    """A 480x360 drawing of a metal plate with four screws and a connector, optionally with
    one defect: 'scratch', 'dent' (both on the connector or plate) or 'missing_screw'.

    Objects: part, screw_tl/tr/bl/br (not the missing one), connector, and ``defect`` when there
    is one. ``seed`` picks the plate colour and where a scratch or dent lands.
    """
    if defect not in ("none", "scratch", "dent", "missing_screw"):
        raise ValueError("defect must be 'none', 'scratch', 'dent' or 'missing_screw'")
    c = Canvas(480, 360, "grey", seed=seed)
    plate = [(150, 156, 166), (166, 150, 140), (140, 160, 150)][Rng(seed).below(3)]
    c.rect(90, 50, 300, 250, plate, outline="dark", outline_width=3, name="part")
    for key, (sx, sy) in {
        "tl": (110, 70),
        "tr": (346, 70),
        "bl": (110, 256),
        "br": (346, 256),
    }.items():
        c.ellipse(sx, sy, 24, 24, "mid", outline="ink", name=f"screw_{key}")
        c.line(sx + 5, sy + 12, sx + 18, sy + 12, "ink", 2)
    c.rect(170, 130, 140, 80, "amber", outline="ink", outline_width=2, name="connector")
    for pin in range(4):
        c.rect(186 + pin * 30, 146, 14, 48, "ink")
    c.text(190, 226, "UNIT 0417", "ink", 2, name="serial")
    if defect == "scratch":
        c.scratch("part", colour="white", width=2, name="defect")
    elif defect == "dent":
        c.dent("part", depth_percent=45, size_percent=30, name="defect")
    elif defect == "missing_screw":
        c.missing_part("screw_br", plate, name="defect")
    return c


@_scene
def deck_hud(
    *, cards: int = 3, enemies: int = 2, energy: int = 3, energy_max: int = 3, seed: int = 0
) -> Canvas:
    """An 800x450 HUD for an invented deck-building game: a player, up to three enemies with
    intent text and health bars, an energy orb, up to five cards and an end-turn button.

    Objects: player, player_hp, enemy_i (+ .intent, .hp), energy, card_i (+ .cost), end_turn.
    No existing game's art, names or layout is reproduced.
    """
    for value, low, high, label in ((cards, 1, 5, "cards"), (enemies, 0, 3, "enemies")):
        if not low <= _int(value, label) <= high:
            raise ValueError(f"{label} must be from {low} to {high}")
    if not 0 <= _int(energy, "energy") <= energy_max <= 9:
        raise ValueError("energy must be from 0 to energy_max, which is at most 9")
    c = Canvas(800, 450, "navy", seed=seed)
    c.rect(0, 300, 800, 150, (40, 46, 68))
    c.rect(0, 0, 800, 36, "dark")
    c.text(12, 10, "FLOOR 3", "white", 2, name="floor_label")
    c.text(620, 10, "GOLD 120", "amber", 2, name="gold_label")
    c.labelled_object(80, 170, 90, 110, "teal", name="player", shape="ellipse")
    c.bar(70, 290, 110, 12, Fraction(4, 5), name="player_hp")
    for i in range(enemies):
        x = 440 + i * 120
        shape = c.rng.choice(["ellipse", "triangle"])
        fill = c.rng.choice(["red", "purple", "pink"])
        c.labelled_object(x, 120, 100, 120, fill, name=f"enemy_{i}", shape=shape)
        c.text(x, 90, f"ATTACK {c.rng.between(4, 12)}", "white", 2, name=f"enemy_{i}.intent")
        c.bar(x, 254, 100, 12, Fraction(c.rng.between(2, 10), 10), fill="red", name=f"enemy_{i}.hp")
    c.ellipse(20, 330, 80, 80, "blue", outline="white", outline_width=3, name="energy")
    c.centered_text((26, 336, 94, 404), f"{energy}/{energy_max}", "white", 3)
    titles, costs = ["JAB", "BRACE", "SURGE", "PARRY", "VOLLEY"], [1, 1, 2, 0, 2]
    for i in range(cards):
        x = 130 + i * 110
        c.rect(x, 300, 100, 140, "white", outline="ink", outline_width=2, name=f"card_{i}")
        cost = c.ellipse(x + 6, 306, 26, 26, "blue", name=f"card_{i}.cost")
        c.centered_text(cost, str(costs[i]), "white", 2)
        c.text(x + 8, 344, titles[i], "ink", 2)
        c.text(x + 8, 372, f"DEAL {c.rng.between(3, 12)}", "dark", 1)
    c.button(676, 386, 112, 48, "END TURN", name="end_turn")
    return c


@_scene
def moving_object_frame(
    *,
    t: float,
    seed: int = 0,
    width: int = 400,
    height: int = 300,
    start: Sequence[int] = (20, 110),
    end: Sequence[int] = (320, 110),
    object_size: Sequence[int] = (60, 50),
    travel_seconds: Sequence[float] = (0.0, 4.0),
    appear_at: float | None = None,
    disappear_at: float | None = None,
) -> Canvas:
    """One still of an item travelling on a belt: at ``t`` seconds it is at the position
    interpolated from ``start`` (at ``travel_seconds[0]``) to ``end`` (at ``travel_seconds[1]``),
    clamped outside that interval, and present only from ``appear_at`` until ``disappear_at``.

    Objects: belt, and ``item`` when present. Position arithmetic is :func:`interpolate`.
    """
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
        raise ValueError("t must be a finite, non-negative number of seconds")
    c = Canvas(width, height, "light", seed=seed)
    ow, oh = object_size
    c.rect(0, start[1] + oh, width, 30, "dark", name="belt")
    for stripe in range(0, width, 40):
        c.rect(stripe, start[1] + oh + 12, 8, 6, "mid")
    t0, t1 = travel_seconds
    present = (appear_at is None or t >= appear_at) and (disappear_at is None or t < disappear_at)
    if present:
        colour = Rng(seed).choice(["blue", "green", "amber", "purple", "teal"])
        x = interpolate(start[0], end[0], t, t0, t1)
        y = interpolate(start[1], end[1], t, t0, t1)
        c.rect(x, y, ow, oh, colour, outline="ink", outline_width=2, name="item")
    return c


def moving_object_frames(times: Sequence[float], **parameters: Any) -> list[Frame]:
    """:func:`moving_object_frame` at each of ``times`` (same keyword arguments, without ``t``)."""
    return build_frames(times, lambda t: moving_object_frame(t=t, **parameters))
