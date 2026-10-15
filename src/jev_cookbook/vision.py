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
from numbers import Integral, Real
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, UnidentifiedImageError

from ._canonical import canonical_image_format
from .evaluation import sum_usage
from .style import INK, PAPER, PINK

__all__ = [
    "AssetPathError",
    "ImageTile",
    "LocalizationMetrics",
    "box_confidence",
    "box_iou",
    "crop_box",
    "draw_boxes",
    "expand_box",
    "generate_tiles",
    "image_asset",
    "image_assets",
    "image_reference",
    "load_frames",
    "localization_metrics",
    "normalized_box",
    "normalized_to_pixels",
    "resolve_asset_path",
    "run_record",
    "tile_to_image",
    "validate_image_asset",
]

_MAX_IMAGE_BYTES = 16 * 1024 * 1024
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
            if not (256 <= width <= 1568 and 256 <= height <= 1568):
                raise ValueError("image width and height must each be 256 to 1568 pixels")
            if not 78_400 <= width * height <= 2_458_624:
                raise ValueError("image area must be 78,400 to 2,458,624 pixels")
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

    Checks actual PNG/JPEG content, stillness, orientation, dimensions and the 16 MiB
    file limit. This does not certify aggregate request limits or API acceptance.
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
    """Intersection area divided by union area of two valid normalized rectangles."""
    a, b = normalized_box(first), normalized_box(second)
    intersection = max(0.0, min(a["right"], b["right"]) - max(a["left"], b["left"])) * max(
        0.0, min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
    )
    area_a = (a["right"] - a["left"]) * (a["bottom"] - a["top"])
    area_b = (b["right"] - b["left"]) * (b["bottom"] - b["top"])
    return intersection / (area_a + area_b - intersection)


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


def crop_box(image: Image.Image, box: Any, *, expand: float = 0.0) -> Image.Image:
    """Copy the enclosed crop, with optional proportional expansion and clipping."""
    return image.crop(normalized_to_pixels(expand_box(box, expand), *image.size))


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
    image: Image.Image, *, tile_size: tuple[int, int] = (512, 512), overlap: int = 0
) -> list[ImageTile]:
    """Cover an image in row-major order with tiles of at most ``(width, height)``.

    ``overlap`` is the minimum overlap in pixels. Final windows are anchored to the
    right/bottom boundary, so they may overlap more. Images smaller than a tile yield
    their full extent. Tile sizes are geometry choices; validate saved tiles with
    :func:`image_asset` before sending them to the API.
    """
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

    tiles = []
    for top in starts(height, tile_height):
        for left in starts(width, tile_width):
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
    """Read confidence conservatively: absent or null stays ``None``, never zero or one."""
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
    Invalid rectangles raise, including predictions on absent gold examples.
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
