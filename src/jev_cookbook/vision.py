"""Local images, rectangle geometry and small, explicit vision evaluation helpers.

Images are raw HTTP asset dictionaries, never SDK objects. Geometry accepts normalized
edge mappings or objects with a ``box`` attribute; no answer classes are imported.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from numbers import Integral, Real
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, UnidentifiedImageError

from ._canonical import canonical_image_format
from .evaluation import sum_usage
from .style import INK, PAPER, PINK

__all__ = [
    "DEFAULT_MAX_TILES",
    "IMAGE_LIMITS",
    "AssetPathError",
    "ImageTile",
    "ImageTransform",
    "LocalizationMetrics",
    "TileStep",
    "box_confidence",
    "box_from_original",
    "box_to_original",
    "box_iou",
    "crop_box",
    "draw_boxes",
    "expand_box",
    "generate_tiles",
    "image_asset",
    "image_assets",
    "image_reference",
    "image_to_tile",
    "load_frames",
    "localization_metrics",
    "normalized_box",
    "normalized_to_pixels",
    "point_from_original",
    "point_to_original",
    "prepare_image",
    "resolve_asset_path",
    "run_record",
    "tile_to_image",
    "validate_image_asset",
]

# The Images API limits this module enforces locally. Source of truth: the "Limits" table at
# https://docs.typesafe.ai/images (fetched 2026-10-20): "Width and height: 280 to 1568 pixels
# each", "Total pixels (width x height): 78,400 to 2,458,624" and "16 MiB per image file". All
# ranges include both ends. tests/test_vision.py pins these numbers against docs/vision.md.
IMAGE_LIMITS = {
    "min_side": 280,
    "max_side": 1568,
    "min_area": 78_400,
    "max_area": 2_458_624,
    "max_bytes": 16 * 1024 * 1024,
}
_MIN_SIDE = IMAGE_LIMITS["min_side"]
_MAX_SIDE = IMAGE_LIMITS["max_side"]
_MIN_AREA = IMAGE_LIMITS["min_area"]
_MAX_AREA = IMAGE_LIMITS["max_area"]
_MAX_IMAGE_BYTES = IMAGE_LIMITS["max_bytes"]
DEFAULT_MAX_TILES = 256
_FORMATS = {"PNG": "png", "JPEG": "jpeg"}
_EDGES = ("top", "bottom", "left", "right")
PixelBounds = tuple[int, int, int, int]


def _image_format(data: bytes) -> str:
    if not data or len(data) > _MAX_IMAGE_BYTES:
        raise ValueError("image must contain 1 byte to 16 MiB of encoded PNG or JPEG data")
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = _FORMATS.get(image.format)
            if fmt is None:
                raise ValueError("image bytes must be PNG or JPEG")
            if getattr(image, "is_animated", False):
                raise ValueError("image must be a still image, not an animation")
            width, height = image.size
            if not (_MIN_SIDE <= width <= _MAX_SIDE and _MIN_SIDE <= height <= _MAX_SIDE):
                raise ValueError(
                    f"image width and height must each be {_MIN_SIDE} to {_MAX_SIDE} pixels"
                )
            if not _MIN_AREA <= width * height <= _MAX_AREA:
                raise ValueError(f"image area must be {_MIN_AREA:,} to {_MAX_AREA:,} pixels")
            image.verify()
        # verify() checks file integrity; load() also catches truncated pixel data.
        with Image.open(io.BytesIO(data)) as image:
            if image.getexif().get(274, 1) != 1:
                raise ValueError(
                    "rotate EXIF orientation into pixels with ImageOps.exif_transpose "
                    "and save the upright image before loading it"
                )
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("image bytes are damaged or are not a supported still image") from exc
    return fmt


def validate_image_asset(asset: Mapping[str, Any]) -> bytes:
    """Validate a raw image asset and return its original encoded bytes.

    Checks actual PNG/JPEG content, stillness, orientation, dimensions (each side 280 to
    1568 pixels, area 78,400 to 2,458,624; a side under 280 is rejected by the API) and the
    16 MiB file limit. This does not certify aggregate request limits or API acceptance.
    """
    if not isinstance(asset, Mapping) or set(asset) != {"type", "format", "data_base64"}:
        raise ValueError("image asset needs exactly type, format and data_base64")
    if asset["type"] != "image":
        raise ValueError("image asset type must be image")
    declared = canonical_image_format(asset["format"])
    encoded = asset["data_base64"]
    if not isinstance(encoded, str):
        raise ValueError("data_base64 must be a base64 string")
    if len(encoded) > 4 * ((_MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError("image exceeds the 16 MiB file limit")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("data_base64 must be standard base64 without whitespace") from exc
    detected = _image_format(data)
    if detected != declared:
        raise ValueError("declared image format does not match the image bytes")
    return data


class AssetPathError(ValueError):
    """An asset path is absolute, a URL, or resolves (through ``..`` or a symlink) outside its root."""


def resolve_asset_path(path: str | Path, *, root: str | Path) -> Path:
    """Resolve ``path`` (relative to ``root``) to a real file path that must stay inside ``root``.

    Use this, or the ``root=`` argument of the loaders that call it, for any path that comes
    from data such as a fixture ``fields`` value. Absolute paths, drive-qualified paths, URLs,
    and relative paths that leave ``root`` through ``..`` or through a symlink all raise
    :class:`AssetPathError` (a ``ValueError``) before any file is opened. Symlinks are followed
    first and the *real* path is compared to the real ``root``, so a link inside the recipe
    folder that points outside it is refused; ``assets/../assets/a.png`` stays allowed.
    A contained path that does not exist is still returned (resolved), so opening it raises
    ``FileNotFoundError``.
    """
    text = str(path)
    if "://" in text or text.startswith("data:"):
        raise AssetPathError("image_asset requires a local file path, not a URL")
    relative = Path(path)
    if relative.is_absolute() or relative.anchor:
        raise AssetPathError(f"asset path {text!r} must be relative to the recipe folder")
    try:
        base = Path(root).resolve()
        resolved = (base / relative).resolve()
    except (OSError, RuntimeError) as exc:  # symlink loop, unreadable component
        raise AssetPathError(f"asset path {text!r} cannot be resolved") from exc
    if not resolved.is_relative_to(base):
        raise AssetPathError(
            f"asset path {text!r} resolves outside the recipe folder {str(root)!r}"
        )
    return resolved


def image_asset(path: str | Path, *, root: str | Path | None = None) -> dict[str, str]:
    """Read a local image as ``{type, format, data_base64}``, preserving its bytes.

    File extensions do not decide the format. URL fetching, resizing, EXIF rotation
    and re-encoding are deliberately explicit preparation steps outside this loader.
    A missing file raises ``FileNotFoundError``; invalid image content raises ``ValueError``.

    A path read from a fixture or any other data must be loaded with ``root=`` (normally the
    recipe folder): the path is then resolved by :func:`resolve_asset_path` and an escaping
    path raises :class:`AssetPathError` instead of being opened. Without ``root`` the path is
    trusted as written (for literal paths in your own code).
    """
    if root is None:
        if "://" in str(path) or str(path).startswith("data:"):
            raise ValueError("image_asset requires a local file path, not a URL")
    else:
        path = resolve_asset_path(path, root=root)
    with Path(path).open("rb") as source:
        data = source.read(_MAX_IMAGE_BYTES + 1)
    fmt = _image_format(data)
    return {"type": "image", "format": fmt, "data_base64": base64.b64encode(data).decode("ascii")}


def image_reference(asset: Mapping[str, Any]) -> str:
    """Stable ``image:sha256:<hex>`` reference for validated, encoded image bytes.

    Renaming a file keeps its reference. Changing pixels or encoded metadata changes
    it; this hashes the supplied file, not a perceptual or decoded-pixel fingerprint.
    Colons delimit the hexadecimal digest from its descriptive prefix so fixture
    hygiene recognizes a content hash rather than a combined high-entropy token.
    """
    return "image:sha256:" + hashlib.sha256(validate_image_asset(asset)).hexdigest()


def image_assets(
    paths: Mapping[str, str | Path], *, root: str | Path | None = None
) -> dict[str, dict[str, str]]:
    """Load reusable named assets from a reference-to-local-path mapping.

    ``root`` contains every path exactly as in :func:`image_asset`.

    Prefer distinctive references: the API also substitutes references inside sentences.
    Include only assets used by the request's state, instructions or criteria.
    """
    if not isinstance(paths, Mapping):
        raise ValueError("paths must map image references to local paths")
    size = 0
    for reference in paths:
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("image references must be nonblank strings")
        length = len(reference.encode("utf-8"))
        if length > 1024:
            raise ValueError("an image reference must be at most 1,024 UTF-8 bytes")
        size += length
    if size > 65_536:
        raise ValueError("image references together must be at most 65,536 UTF-8 bytes")
    return {reference: image_asset(path, root=root) for reference, path in paths.items()}


def _number(value: Any, name: str, *, unit: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if number < 0 or (unit and number > 1):
        raise ValueError(f"{name} must be {'in [0, 1]' if unit else 'non-negative'}")
    return number


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def normalized_box(box: Any) -> dict[str, float]:
    """Copy and validate four normalized edges, including a Box answer's ``.box``.

    A raw answer mapping with a ``box`` key is also accepted. Every edge must be a
    finite number in [0, 1], with positive width and height. ``None`` is absence, not
    a rectangle, and raises here; :func:`localization_metrics` handles absent targets.
    """
    if isinstance(box, Mapping) and "box" in box:
        box = box["box"]
    else:
        box = getattr(box, "box", box)
    try:
        values = {
            edge: _number(
                box[edge] if isinstance(box, Mapping) else getattr(box, edge), edge, unit=True
            )
            for edge in _EDGES
        }
    except (KeyError, AttributeError) as exc:
        raise ValueError("box needs top, bottom, left and right edges") from exc
    if values["left"] >= values["right"] or values["top"] >= values["bottom"]:
        raise ValueError("box must have positive width and height")
    return values


def _pixel_edge(coordinate: float, dimension: int) -> float:
    scaled = coordinate * dimension
    nearest = round(scaled)
    # Undo the division/multiplication round-trip error of an integer pixel edge.
    # The inverse check preserves other nearby, genuinely fractional coordinates.
    if abs(scaled - nearest) <= math.ulp(scaled) and coordinate == nearest / dimension:
        return float(nearest)
    return scaled


def normalized_to_pixels(box: Any, width: int, height: int) -> PixelBounds:
    """Enclosing integer ``(left, top, right, bottom)`` bounds for a Pillow crop.

    Starts round down, ends round up; right and bottom are exclusive. Multiplication
    uses width and height, not width-1 and height-1. A full-image box is (0, 0, w, h).
    An edge within one floating-point increment of an integer snaps to it only when
    the normalized coordinate equals that integer divided by its image dimension.
    This restores exact pixel-edge round trips while preserving fractional edges.
    """
    width, height = _positive_int(width, "width"), _positive_int(height, "height")
    edges = normalized_box(box)
    return (
        math.floor(_pixel_edge(edges["left"], width)),
        math.floor(_pixel_edge(edges["top"], height)),
        math.ceil(_pixel_edge(edges["right"], width)),
        math.ceil(_pixel_edge(edges["bottom"], height)),
    )


def box_iou(first: Any, second: Any) -> float:
    """Intersection area divided by union area of two valid normalized rectangles.

    Raises ``ValueError`` when both areas are so small that the union underflows to zero.
    """
    a, b = normalized_box(first), normalized_box(second)
    intersection = max(0.0, min(a["right"], b["right"]) - max(a["left"], b["left"])) * max(
        0.0, min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
    )
    area_a = (a["right"] - a["left"]) * (a["bottom"] - a["top"])
    area_b = (b["right"] - b["left"]) * (b["bottom"] - b["top"])
    union = area_a + area_b - intersection
    if union <= 0.0:
        # A valid box can be so small that its area underflows to 0.0; the ratio is then
        # undefined, and 0.0 would wrongly call two identical boxes disjoint.
        raise ValueError("box areas are too small to compare: the union underflows to zero")
    return intersection / union


def expand_box(box: Any, fraction: float = 0.0) -> dict[str, float]:
    """Add ``fraction * box_size`` on each side, clipped to the image boundary."""
    edges = normalized_box(box)
    fraction = _number(fraction, "fraction")
    dx = (edges["right"] - edges["left"]) * fraction
    dy = (edges["bottom"] - edges["top"]) * fraction
    return {
        "top": max(0.0, edges["top"] - dy),
        "bottom": min(1.0, edges["bottom"] + dy),
        "left": max(0.0, edges["left"] - dx),
        "right": min(1.0, edges["right"] + dx),
    }


def _min_side(value: Any) -> int | None:
    return None if value is None else _positive_int(value, "min_side")


def crop_box(
    image: Image.Image, box: Any, *, expand: float = 0.0, min_side: int | None = None
) -> Image.Image:
    """Copy the enclosed crop, with optional proportional expansion and clipping.

    ``min_side`` (default ``None``: no check) refuses a crop with either side under that many
    pixels by raising ``ValueError``. Pass ``min_side=IMAGE_LIMITS["min_side"]`` for a crop
    that will be sent to the API, which rejects anything under 280 px; or crop without it and
    pad or scale the result with :func:`prepare_image`.
    """
    minimum = _min_side(min_side)
    bounds = normalized_to_pixels(expand_box(box, expand), *image.size)
    if minimum is not None and min(bounds[2] - bounds[0], bounds[3] - bounds[1]) < minimum:
        raise ValueError(
            f"crop of {bounds[2] - bounds[0]} x {bounds[3] - bounds[1]} pixels is under "
            f"min_side={minimum}; expand the box or pad/scale the crop with prepare_image"
        )
    return image.crop(bounds)


def _pixel_bounds(bounds: Any, width: int, height: int) -> PixelBounds:
    try:
        left, top, right, bottom = bounds
    except (TypeError, ValueError) as exc:
        raise ValueError("tile bounds need four integer pixel edges") from exc
    if any(isinstance(x, bool) or not isinstance(x, Integral) for x in (left, top, right, bottom)):
        raise ValueError("tile bounds need four integer pixel edges")
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("tile bounds must have positive area inside the whole image")
    return int(left), int(top), int(right), int(bottom)


def tile_to_image(box: Any, tile_bounds: PixelBounds, width: int, height: int) -> dict[str, float]:
    """Map tile-local normalized edges to whole-image normalized edges by affine scaling.

    ``tile_bounds`` are the exact pixel bounds used to crop the tile. This also works
    after an entire tile is resized without changing its aspect-relative coordinates.
    """
    width, height = _positive_int(width, "width"), _positive_int(height, "height")
    left, top, right, bottom = _pixel_bounds(tile_bounds, width, height)
    edges = normalized_box(box)
    return {
        "top": (top + edges["top"] * (bottom - top)) / height,
        "bottom": (top + edges["bottom"] * (bottom - top)) / height,
        "left": (left + edges["left"] * (right - left)) / width,
        "right": (left + edges["right"] * (right - left)) / width,
    }


@dataclass(frozen=True)
class ImageTile:
    """A copied image tile and its exact, exclusive pixel bounds in the source."""

    bounds: PixelBounds
    image: Image.Image


def generate_tiles(
    image: Image.Image,
    *,
    tile_size: tuple[int, int] = (512, 512),
    overlap: int = 0,
    max_tiles: int = DEFAULT_MAX_TILES,
    min_side: int | None = None,
) -> list[ImageTile]:
    """Cover an image in row-major order with tiles of at most ``(width, height)``.

    ``overlap`` is the minimum overlap in pixels. Final windows are anchored to the
    right/bottom boundary, so they may overlap more. Images smaller than a tile yield
    their full extent. Tile sizes are geometry choices; validate saved tiles with
    :func:`image_asset` before sending them to the API.

    The number of tiles grows with the inverse square of the stride (tile size minus
    ``overlap``), so the tile count is computed first and a configuration above
    ``max_tiles`` (default 256) raises ``ValueError`` before any tile is cropped. Each tile
    is usually one API call, so the cap bounds cost as well as memory. Raise ``max_tiles``
    deliberately.

    ``min_side`` (default ``None``: no check) refuses, before any tile is cropped, a tile with
    either side under that many pixels. Every tile has the same size, ``min(tile, image)`` per
    axis, so this fires when the requested tile or the whole image is that small. Pass
    ``min_side=IMAGE_LIMITS["min_side"]`` for tiles that will be sent to the API, or pad or
    scale each tile with :func:`prepare_image`.
    """
    max_tiles = _positive_int(max_tiles, "max_tiles")
    minimum = _min_side(min_side)
    try:
        tile_width, tile_height = tile_size
    except (TypeError, ValueError) as exc:
        raise ValueError("tile_size must contain width and height") from exc
    tile_width = _positive_int(tile_width, "tile width")
    tile_height = _positive_int(tile_height, "tile height")
    if (
        isinstance(overlap, bool)
        or not isinstance(overlap, Integral)
        or not 0 <= overlap < min(tile_width, tile_height)
    ):
        raise ValueError("overlap must be a non-negative integer smaller than both tile sizes")
    width, height = image.size
    _positive_int(width, "image width")
    _positive_int(height, "image height")

    def starts(length: int, window: int) -> list[int]:
        if length <= window:
            return [0]
        positions = list(range(0, length - window + 1, window - int(overlap)))
        if positions[-1] != length - window:
            positions.append(length - window)
        return positions

    if minimum is not None and min(min(tile_width, width), min(tile_height, height)) < minimum:
        raise ValueError(
            f"tiles of {min(tile_width, width)} x {min(tile_height, height)} pixels are under "
            f"min_side={minimum}; use a larger tile_size or pad/scale each tile with "
            "prepare_image"
        )
    rows, columns = starts(height, tile_height), starts(width, tile_width)
    if len(rows) * len(columns) > max_tiles:
        raise ValueError(
            f"tile_size={tile_width, tile_height} with overlap={overlap} would make "
            f"{len(rows) * len(columns):,} tiles, above max_tiles={max_tiles:,}; "
            "use a larger tile, less overlap or a larger max_tiles"
        )
    tiles = []
    for top in rows:
        for left in columns:
            bounds = (left, top, min(left + tile_width, width), min(top + tile_height, height))
            tiles.append(ImageTile(bounds, image.crop(bounds)))
    return tiles


def draw_boxes(image: Image.Image, boxes: Mapping[str, Any]) -> Image.Image:
    """Draw labeled pink rectangles on a new RGB image using the cookbook palette."""
    output = image.convert("RGB")
    draw = ImageDraw.Draw(output)
    for label, box in boxes.items():
        left, top, right, bottom = normalized_to_pixels(box, *output.size)
        draw.rectangle((left, top, right - 1, bottom - 1), outline=PINK, width=2)
        # Pillow's ASCII fallback font keeps this display deterministic without a font file.
        text = str(label)
        if text:
            text_bounds = draw.textbbox((left + 3, top + 3), text)
            draw.rectangle(text_bounds, fill=PAPER)
            draw.text((left + 3, top + 3), text, fill=INK)
    return output


def box_confidence(answer: Any) -> float | None:
    """Read confidence conservatively: absent or null stays ``None``, never a number.

    A reported ``0.0`` or ``1.0`` is returned as reported; only absence is never coerced
    into a confidence. A non-numeric or out-of-range value raises ``ValueError``.
    """
    value = (
        answer.get("confidence")
        if isinstance(answer, Mapping)
        else getattr(answer, "confidence", None)
    )
    return None if value is None else _number(value, "confidence", unit=True)


@dataclass(frozen=True)
class LocalizationMetrics:
    """IoU over present gold targets, with absent targets and detection errors counted.

    ``mean_iou`` includes a zero for every missed present target and is NaN when no
    gold target is present. Absent gold never contributes an invented IoU.
    """

    n_examples: int
    present: int
    absent: int
    missed: int
    false_positives: int
    mean_iou: float


def localization_metrics(gold: Iterable[Any], predicted: Iterable[Any]) -> LocalizationMetrics:
    """Evaluate rectangles; ``None`` explicitly denotes an absent target.

    Predictions must already have passed the recipe's presence/confidence policy.
    A review outcome is not an absent prediction: report reviews separately through
    ``evaluation.evaluate_outcomes`` and use this function on the resolved subset.
    Invalid rectangles raise, including predictions on absent gold examples. A
    ``ValueError`` from :func:`box_iou` (both areas underflow to zero) means a degenerate
    gold label, since the union is at least as large as the gold box's own area.
    """
    actual, guesses = list(gold), list(predicted)
    if not actual or len(actual) != len(guesses):
        raise ValueError("gold and predicted must be nonempty and have the same length")
    overlaps: list[float] = []
    absent = missed = false_positives = 0
    for target, guess in zip(actual, guesses, strict=True):
        target = None if target is None else normalized_box(target)
        guess = None if guess is None else normalized_box(guess)
        if target is None:
            absent += 1
            false_positives += guess is not None
        elif guess is None:
            missed += 1
            overlaps.append(0.0)
        else:
            overlaps.append(box_iou(target, guess))
    return LocalizationMetrics(
        len(actual),
        len(overlaps),
        absent,
        missed,
        false_positives,
        math.fsum(overlaps) / len(overlaps) if overlaps else float("nan"),
    )


def load_frames(
    frames: Iterable[tuple[float, str | Path]], *, root: str | Path | None = None
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Load explicitly timestamped stills in strictly increasing elapsed seconds.

    Returns ``(state_frames, assets)``. Each state row has ``timestamp_seconds`` and
    ``image`` (the stable reference); identical files share an asset. This neither
    decodes video nor infers timestamps from filenames or a nominal frame rate.
    ``root`` contains every path exactly as in :func:`image_asset`.
    """
    entries = list(frames)
    if not entries:
        raise ValueError("frames must not be empty")
    prepared = []
    previous = -1.0
    for timestamp, path in entries:
        timestamp = _number(timestamp, "timestamp_seconds")
        if timestamp <= previous:
            raise ValueError("frame timestamps must be strictly increasing")
        prepared.append((timestamp, path))
        previous = timestamp
    state = []
    assets = {}
    for timestamp, path in prepared:
        asset = image_asset(path, root=root)
        reference = image_reference(asset)
        assets[reference] = asset
        state.append({"timestamp_seconds": timestamp, "image": reference})
    return state, assets


def run_record(
    result: Any,
    *,
    mode: str,
    measured_latency_seconds: float | None = None,
    measured_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Make one accounting row without estimating tokens, latency or cost.

    ``result`` has the ``source``, ``model`` and ``usage`` attributes of DecisionResult.
    Synthetic/scripted records always contain null usage, latency, cost and model.
    Recorded/live rows take reported tokens and only explicitly supplied measurements.
    Recorded latency must come from capture, never the elapsed time of replay.
    """
    if mode not in ("synthetic", "scripted", "recorded", "live"):
        raise ValueError("mode must be synthetic, scripted, recorded or live")
    row: dict[str, Any] = dict.fromkeys(
        ("model", "input_tokens", "output_tokens", "latency_seconds", "cost_usd")
    )
    row["mode"] = mode
    if mode in ("synthetic", "scripted"):
        if getattr(result, "source", None) != "synthetic":
            raise ValueError("synthetic/scripted mode requires a synthetic result")
        if measured_latency_seconds is not None or measured_cost_usd is not None:
            raise ValueError("synthetic/scripted runs cannot report measured API latency or cost")
        return row
    model = getattr(result, "model", None)
    if (
        getattr(result, "source", None) != "recorded"
        or not isinstance(model, str)
        or not model.strip()
        or model == "synthetic"
    ):
        raise ValueError("recorded/live mode requires a recorded result with its returned model")
    usage = sum_usage([getattr(result, "usage", None)])
    row.update(
        model=model,
        input_tokens=None if usage.requests_missing_input else usage.input_tokens,
        output_tokens=None if usage.requests_missing_output else usage.output_tokens,
        latency_seconds=(
            None
            if measured_latency_seconds is None
            else _number(measured_latency_seconds, "measured_latency_seconds")
        ),
        cost_usd=(
            None if measured_cost_usd is None else _number(measured_cost_usd, "measured_cost_usd")
        ),
    )
    return row


# --- Image preparation and multi-level coordinate transforms (#310) -------------------------
#
# Everything below is exact rational arithmetic (fractions.Fraction) converted to float once,
# at the end, so a long chain of crops, pads and resizes does not accumulate rounding error.
# Python owns this arithmetic: the model only ever sees the image it was sent and answers in
# that image's normalized coordinates.

_ZERO, _ONE = Fraction(0), Fraction(1)
_Axes = tuple[tuple[Fraction, Fraction], tuple[Fraction, Fraction]]


class _AffineStep:
    """One child-image to parent-image coordinate map: per axis ``parent = a * child + b``.

    Both maps are expressed on normalized coordinates in [0, 1] of the image they belong to.
    The child's whole [0, 1] square lands inside the parent for a tile, and the parent's whole
    square lands inside the child for a padded transform; mapping the other way is clipped.
    """

    def _axes(self) -> _Axes:
        raise NotImplementedError

    def to_parent(self, box: Any) -> dict[str, float] | None:
        """Map a child-image box to the parent image, clipped; ``None`` if nothing is left."""
        return box_to_original(box, self)

    def from_parent(self, box: Any) -> dict[str, float] | None:
        """Map a parent-image box into the child image, clipped; ``None`` if nothing is left."""
        return box_from_original(box, self)

    def point_to_parent(self, point: Any) -> dict[str, float] | None:
        """Map a child-image point to the parent image; ``None`` if it falls outside."""
        return point_to_original(point, self)

    def point_from_parent(self, point: Any) -> dict[str, float] | None:
        """Map a parent-image point into the child image; ``None`` if it falls outside."""
        return point_from_original(point, self)


@dataclass(frozen=True)
class TileStep(_AffineStep):
    """A crop of ``bounds`` (exclusive right/bottom pixels) out of a ``parent_size`` image.

    Use one step per level of a progressive search: the tile cut from the full image, the
    crop cut from that tile, and so on. ``bounds`` are in the pixels of the image that was cut,
    so ``parent_size`` must be the size of *that* image (the full image for the first level,
    the previous level's image for the next). Resizing a whole level uniformly before asking
    does not change its normalized coordinates, so it needs no step; padding does, and has
    :class:`ImageTransform`.
    """

    bounds: PixelBounds
    parent_size: tuple[int, int]

    def __post_init__(self) -> None:
        try:
            width, height = self.parent_size
        except (TypeError, ValueError) as exc:
            raise ValueError("parent_size must contain width and height") from exc
        width, height = _positive_int(width, "width"), _positive_int(height, "height")
        object.__setattr__(self, "bounds", _pixel_bounds(self.bounds, width, height))
        object.__setattr__(self, "parent_size", (width, height))

    def _axes(self) -> _Axes:
        (left, top, right, bottom), (width, height) = self.bounds, self.parent_size
        return (
            (Fraction(right - left, width), Fraction(left, width)),
            (Fraction(bottom - top, height), Fraction(top, height)),
        )


@dataclass(frozen=True)
class ImageTransform(_AffineStep):
    """How :func:`prepare_image` placed an image: scaled to ``content_size``, then padded.

    The original image, resized to ``content_size``, sits at pixel ``offset`` (left, top) inside
    the ``prepared_size`` canvas; everything else is padding. ``to_original`` maps a box or
    point found on the prepared image back to the original image and ``to_prepared`` maps the
    other way (for example to draw a gold box on the prepared image). Normalized coordinates
    are used throughout, so a box that overlaps the padding is clipped to the original image's
    area and a box lying wholly in the padding maps to ``None``.
    """

    original_size: tuple[int, int]
    prepared_size: tuple[int, int]
    content_size: tuple[int, int]
    offset: tuple[int, int]

    def __post_init__(self) -> None:
        sizes = {}
        for name in ("original_size", "prepared_size", "content_size", "offset"):
            try:
                first, second = getattr(self, name)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must contain two integers") from exc
            if name == "offset":
                for value in (first, second):
                    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
                        raise ValueError("offset must contain two non-negative integers")
                sizes[name] = (int(first), int(second))
            else:
                sizes[name] = (_positive_int(first, name), _positive_int(second, name))
        content, offset, prepared = sizes["content_size"], sizes["offset"], sizes["prepared_size"]
        if any(offset[i] + content[i] > prepared[i] for i in (0, 1)):
            raise ValueError("the content must fit inside the prepared image")
        for name, value in sizes.items():
            object.__setattr__(self, name, value)

    def _axes(self) -> _Axes:
        (width, height), (cw, ch) = self.prepared_size, self.content_size
        ox, oy = self.offset
        # original = (prepared * size - offset) / content: parent = child * a + b.
        return (
            (Fraction(width, cw), Fraction(-ox, cw)),
            (Fraction(height, ch), Fraction(-oy, ch)),
        )

    def to_original(self, box: Any) -> dict[str, float] | None:
        """Prepared-image box to original-image box (clipped to the content; may be ``None``)."""
        return self.to_parent(box)

    def to_prepared(self, box: Any) -> dict[str, float] | None:
        """Original-image box to prepared-image box (always inside; never ``None``)."""
        return self.from_parent(box)

    def point_to_original(self, point: Any) -> dict[str, float] | None:
        """Prepared-image point to original-image point (``None`` if it lies in the padding)."""
        return self.point_to_parent(point)

    def point_to_prepared(self, point: Any) -> dict[str, float] | None:
        """Original-image point to prepared-image point."""
        return self.point_from_parent(point)


def _steps(steps: Any) -> list[_AffineStep]:
    if isinstance(steps, _AffineStep):
        return [steps]
    try:
        found = list(steps)
    except TypeError as exc:
        raise ValueError("steps must be a TileStep, an ImageTransform or a sequence") from exc
    if not all(isinstance(step, _AffineStep) for step in found):
        raise ValueError("every step must be a TileStep or an ImageTransform")
    return found


def _map_interval(
    low: Fraction, high: Fraction, axis: tuple[Fraction, Fraction], *, up: bool
) -> tuple[Fraction, Fraction]:
    scale, offset = axis
    if up:
        low, high = scale * low + offset, scale * high + offset
    else:
        low, high = (low - offset) / scale, (high - offset) / scale
    return max(low, _ZERO), min(high, _ONE)


def _map_box(box: Any, steps: Any, *, up: bool) -> dict[str, float] | None:
    edges = normalized_box(box)
    x0, x1 = Fraction(edges["left"]), Fraction(edges["right"])
    y0, y1 = Fraction(edges["top"]), Fraction(edges["bottom"])
    found = _steps(steps)
    for step in reversed(found) if up else found:
        x_axis, y_axis = step._axes()
        (x0, x1), (y0, y1) = (
            _map_interval(x0, x1, x_axis, up=up),
            _map_interval(y0, y1, y_axis, up=up),
        )
        if x0 >= x1 or y0 >= y1:
            return None
    result = {"top": float(y0), "bottom": float(y1), "left": float(x0), "right": float(x1)}
    if result["left"] >= result["right"] or result["top"] >= result["bottom"]:
        return None  # a sliver thinner than one float increment is no rectangle
    return result


def _point(value: Any) -> tuple[Fraction, Fraction]:
    try:
        x, y = (value["x"], value["y"]) if isinstance(value, Mapping) else tuple(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("a point needs x and y, as a mapping or a pair") from exc
    return Fraction(_number(x, "x", unit=True)), Fraction(_number(y, "y", unit=True))


def _map_point(point: Any, steps: Any, *, up: bool) -> dict[str, float] | None:
    x, y = _point(point)
    found = _steps(steps)
    for step in reversed(found) if up else found:
        (xa, xb), (ya, yb) = step._axes()
        x, y = (xa * x + xb, ya * y + yb) if up else ((x - xb) / xa, (y - yb) / ya)
        if not (_ZERO <= x <= _ONE and _ZERO <= y <= _ONE):
            return None
    return {"x": float(x), "y": float(y)}


def box_to_original(box: Any, steps: Any) -> dict[str, float] | None:
    """Map a box found on the deepest image back through ``steps`` to the outermost one.

    ``steps`` lists the levels outermost first, in the order the images were derived: for
    example ``[TileStep(tile_bounds, full_size), TileStep(crop_bounds, tile_size), transform]``
    for a tile, a crop of that tile and a :func:`prepare_image` of the crop. The box is in the
    last level's normalized coordinates; the result is in the first level's (the original
    image), computed exactly and rounded to a float once. A level whose region does not
    contain the whole box (only a padded transform can do that) clips it; if nothing is left
    the result is ``None``. An empty ``steps`` returns a validated copy of ``box``.
    """
    return _map_box(box, steps, up=True)


def box_from_original(box: Any, steps: Any) -> dict[str, float] | None:
    """Inverse of :func:`box_to_original`: a box on the outermost image, in the deepest image.

    The result is clipped to the deepest image, and is ``None`` as soon as the box no longer
    overlaps a level (touching only along an edge is no overlap). This labels gold boxes per
    tile or per crop to evaluate a tile-selection step.
    """
    return _map_box(box, steps, up=False)


def point_to_original(point: Any, steps: Any) -> dict[str, float] | None:
    """:func:`box_to_original` for a point ``{"x": ..., "y": ...}`` (or ``(x, y)``).

    A point is not clipped: it returns ``None`` when it lies in padding.
    """
    return _map_point(point, steps, up=True)


def point_from_original(point: Any, steps: Any) -> dict[str, float] | None:
    """:func:`box_from_original` for a point; ``None`` when it is outside a level."""
    return _map_point(point, steps, up=False)


def image_to_tile(
    box: Any, tile_bounds: PixelBounds, width: int, height: int
) -> dict[str, float] | None:
    """Inverse of :func:`tile_to_image`: a whole-image box as seen inside one tile.

    ``tile_bounds`` are the exact pixel bounds of the tile in the ``width`` x ``height`` image.
    Returns the tile-local normalized box clipped to the tile, or ``None`` when the box does
    not intersect the tile with positive area (touching along an edge does not count).
    Use it to label a gold box for every tile.
    """
    return TileStep(tile_bounds, (width, height)).from_parent(box)


def _pad_color(value: Any) -> tuple[int, int, int]:
    try:
        red, green, blue = value
    except (TypeError, ValueError) as exc:
        raise ValueError("pad_color must be an (r, g, b) tuple of integers 0-255") from exc
    if any(isinstance(c, bool) or not isinstance(c, Integral) or not 0 <= c <= 255 for c in value):
        raise ValueError("pad_color must be an (r, g, b) tuple of integers 0-255")
    return int(red), int(green), int(blue)


def prepare_image(
    image: Image.Image,
    *,
    min_side: int = _MIN_SIDE,
    max_side: int = _MAX_SIDE,
    pad_color: tuple[int, int, int] = (255, 255, 255),
    upscale: bool = True,
) -> tuple[Image.Image, ImageTransform]:
    """Resize and/or pad ``image`` so both sides are in ``[min_side, max_side]``.

    The defaults are the API limits (``IMAGE_LIMITS``: 280 to 1568 pixels per side; the area
    limits follow from them). Returns ``(prepared_image, transform)``; ``transform`` maps boxes
    and points between the prepared and the original image. The steps, all deterministic:

    1. If the longest side exceeds ``max_side``, scale down uniformly so it equals ``max_side``.
    2. Otherwise, if ``upscale`` and the shortest side is under ``min_side``, scale up
       uniformly to ``min_side``, but no further than the longest side reaching ``max_side``.
    3. Pad any side still under ``min_side`` with ``pad_color``, centered (the extra pixel of
       an odd margin goes to the right or bottom).

    Scaled sizes are rounded half up to whole pixels and the transform records the sizes
    actually produced, so rounding never skews a mapped box. Resampling is Lanczos, which is
    reproducible for a given Pillow version but not a promise across versions. A very elongated
    image (for example 5000 x 100) is padded on its short axis: it becomes valid, but the
    content may be a thin strip, and ``upscale=False`` pads instead of scaling up a small one.
    The output is RGB, or RGBA when the input has an alpha channel or transparency; the input
    is not modified. An image already within the limits comes back as an identical copy with
    an identity transform. This does not apply EXIF orientation: transpose first.
    """
    min_side, max_side = _positive_int(min_side, "min_side"), _positive_int(max_side, "max_side")
    if min_side > max_side:
        raise ValueError("min_side must not exceed max_side")
    red, green, blue = _pad_color(pad_color)
    width, height = image.size
    longest, shortest = max(width, height), min(width, height)
    scale = _ONE
    if longest > max_side:
        scale = Fraction(max_side, longest)
    elif upscale and shortest < min_side:
        scale = min(Fraction(min_side, shortest), Fraction(max_side, longest))

    def scaled(length: int) -> int:
        return max(1, min(max_side, math.floor(length * scale + Fraction(1, 2))))

    content = (scaled(width), scaled(height))
    prepared = (max(content[0], min_side), max(content[1], min_side))
    offset = ((prepared[0] - content[0]) // 2, (prepared[1] - content[1]) // 2)
    alpha = "A" in image.getbands() or "transparency" in image.info
    base = image.convert("RGBA" if alpha else "RGB")
    if content != (width, height):
        base = base.resize(content, Image.Resampling.LANCZOS)
    canvas = Image.new(base.mode, prepared, (red, green, blue, 255)[: len(base.getbands())])
    canvas.paste(base, offset)
    return canvas, ImageTransform((width, height), prepared, content, offset)
