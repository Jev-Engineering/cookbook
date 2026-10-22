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
import re
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType
from typing import Any

from PIL import Image, ImageDraw, UnidentifiedImageError

from ._canonical import canonical_image_format
from .backends import _string_values
from .evaluation import sum_usage
from .style import INK, PAPER, PINK

__all__ = [
    "DEFAULT_MAX_TILES",
    "IMAGE_LIMITS",
    "REQUEST_IMAGE_LIMITS",
    "AssetPathError",
    "ImageRequestProfile",
    "ImageRequestTooLarge",
    "ImageTile",
    "ImageTransform",
    "LocalizationMetrics",
    "LocalizationReport",
    "box_confidence",
    "box_iou",
    "crop_bounds",
    "crop_box",
    "draw_boxes",
    "expand_box",
    "generate_tiles",
    "gold_box",
    "image_asset",
    "image_assets",
    "image_reference",
    "image_request_profile",
    "image_to_tile",
    "load_frames",
    "localization_metrics",
    "localization_report",
    "normalized_box",
    "normalized_to_pixels",
    "preflight_image_request",
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
# The same page lists three aggregate caps of 32 MiB: "Request body" (including the JSON, base64
# text and multipart framing), "All images in the request" (shared by every distinct image after
# the API processes it) and "Expanded request" (the text, questions, structure, and images after
# every reference is replaced by its image). Local file validation sees none of them (see
# ``validate_image_asset``). ``preflight_image_request`` checks the two image caps in file bytes;
# the request-body cap is not modelled.
REQUEST_IMAGE_LIMITS = {
    "distinct_bytes": 32 * 1024 * 1024,
    "expanded_bytes": 32 * 1024 * 1024,
}
_FORMATS = {"PNG": "png", "JPEG": "jpeg"}
_EDGES = ("top", "bottom", "left", "right")
PixelBounds = tuple[int, int, int, int]


_ORIENTATION_MESSAGE = (
    "rotate EXIF orientation into pixels with ImageOps.exif_transpose "
    "and save the upright image before loading it"
)


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
                raise ValueError(_ORIENTATION_MESSAGE)
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


@dataclass(frozen=True)
class ImageRequestProfile:
    """What a request's image references expand to, counted from the request alone.

    ``distinct_assets`` / ``distinct_bytes``: the assets whose reference appears at least once,
    and the encoded file bytes of those assets, each counted once (the upload). ``copies`` /
    ``expanded_bytes``: every place a reference is replaced by its image, and the bytes of all of
    those copies. ``state_copies`` are the copies in the state (sent once per request);
    ``per_question`` maps each question name to the copies in that question's own instructions and
    criteria values, so ``copies == state_copies + sum(per_question.values())``. Bytes are the
    encoded file sizes, not what the API holds after processing, and no content is kept.
    """

    distinct_assets: int
    distinct_bytes: int
    copies: int
    expanded_bytes: int
    state_copies: int
    per_question: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "per_question", MappingProxyType(dict(self.per_question)))


class ImageRequestTooLarge(ValueError):
    """A request's images exceed an aggregate cap; raised before anything is sent."""


def _encoded_size(asset: Mapping[str, Any]) -> int:
    """Decoded byte length of ``asset["data_base64"]`` from its length alone (no decoding)."""
    try:
        encoded = asset["data_base64"]
    except (KeyError, TypeError):
        raise ValueError("image asset needs data_base64") from None
    if not isinstance(encoded, str) or len(encoded) % 4:
        raise ValueError("data_base64 must be a padded base64 string")
    return len(encoded) // 4 * 3 - (len(encoded) - len(encoded.rstrip("=")))


def image_request_profile(
    state: Any, questions: Mapping[str, Any], assets: Mapping[str, Mapping[str, Any]] | None
) -> ImageRequestProfile:
    """Count the image copies and bytes a request expands to. Pure: no file is read, no bytes kept.

    Follows https://docs.typesafe.ai/images (fetched 2026-10-22): "A string that is exactly a
    reference becomes that image. In longer strings, references are replaced from left to right,
    and matches never overlap", and "every place its reference appears adds another copy". So:

    - every occurrence of a reference in a state string value or a criteria value is one copy
      (``Choice`` option names and object keys are text, never a place for a reference);
    - an occurrence in a question's ``instructions`` is one copy for that question, so an image
      in the instructions of three questions is three copies, while the same image in the state
      once is one copy ("put it in the ``state`` once and refer to it by path");
    - where two references start at the same place the longer one is replaced (the page does not
      say; this is the reading that keeps a longer reference from being shadowed by its prefix).

    ``assets`` maps reference to a raw asset dictionary, as for ``decide``; sizes come from the
    length of ``data_base64`` (the file bytes), so the asset is not decoded or validated here.
    """
    for ref in assets or ():
        if type(ref) is not str or not ref.strip():
            raise ValueError("asset references must be non-empty, non-whitespace strings")
    sizes = {ref: _encoded_size(asset) for ref, asset in (assets or {}).items()}
    if not sizes:
        return ImageRequestProfile(0, 0, 0, 0, 0, {name: 0 for name in questions})
    # Longest first, so at one position the alternation takes the longest reference.
    pattern = re.compile("|".join(re.escape(ref) for ref in sorted(sizes, key=len, reverse=True)))
    seen: dict[str, int] = {}

    def count(values: Iterable[str]) -> int:
        total = 0
        for value in values:
            for ref in pattern.findall(value):
                seen[ref] = seen.get(ref, 0) + 1
                total += 1
        return total

    state_copies = count(_string_values(state))
    per_question = {}
    for name, question in questions.items():
        per_question[name] = count(_string_values(question.instructions)) + count(
            _string_values(getattr(question, "criteria", None))
        )
    return ImageRequestProfile(
        distinct_assets=len(seen),
        distinct_bytes=sum(sizes[ref] for ref in seen),
        copies=sum(seen.values()),
        expanded_bytes=sum(sizes[ref] * times for ref, times in seen.items()),
        state_copies=state_copies,
        per_question=per_question,
    )


def preflight_image_request(profile: ImageRequestProfile) -> None:
    """Raise :class:`ImageRequestTooLarge` when the images alone exceed an aggregate cap.

    Uses no network and spends nothing. Passing is necessary, not sufficient: the API measures the
    images after processing, counts the text and structure of the expanded request as well, and
    has a separate request-body cap (base64 text and multipart framing included) checked here not
    at all.
    """

    def size(n: int) -> str:
        return f"{n:,} bytes ({n / (1024 * 1024):.2f} MiB)"

    if profile.distinct_bytes > REQUEST_IMAGE_LIMITS["distinct_bytes"]:
        raise ImageRequestTooLarge(
            f"the request's {profile.distinct_assets} distinct image(s) are "
            f"{size(profile.distinct_bytes)}, over the 32 MiB "
            f"({REQUEST_IMAGE_LIMITS['distinct_bytes']:,} bytes) cap on all images in a "
            "request; use fewer or smaller images. Nothing was sent."
        )
    if profile.expanded_bytes > REQUEST_IMAGE_LIMITS["expanded_bytes"]:
        raise ImageRequestTooLarge(
            f"the request expands to {profile.copies} image copies of "
            f"{size(profile.expanded_bytes)}, over the 32 MiB "
            f"({REQUEST_IMAGE_LIMITS['expanded_bytes']:,} bytes) cap on the expanded request "
            f"(each use of a reference adds the image again; {profile.state_copies} in the state, "
            f"per question {dict(profile.per_question)}). Put a shared image in the state once "
            "and refer to it by path, or use fewer references. Nothing was sent."
        )


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


def gold_box(label: Any) -> dict[str, float] | None:
    """Decode a gold Box label: a validated rectangle for a present target, ``None`` if absent.

    The label format (``docs/fixtures.md``) is ``{"present": true, "box": {top, bottom, left,
    right}}`` for a target that is in the image and ``{"present": false}`` for one that is
    not. ``present`` must be a JSON boolean; a present label has exactly ``present`` and
    ``box``, an absent one exactly ``present`` (a ``box`` on an absent label is contradictory
    and raises). The box must have exactly the four edges, each finite in [0, 1], positive
    width and height, and an area that does not underflow to zero (such a gold box cannot
    be scored, since :func:`box_iou` is undefined against it). Raises ``ValueError``.
    """
    if not isinstance(label, Mapping):
        raise ValueError("a gold Box label must be an object with a boolean 'present'")
    present = label.get("present")
    if not isinstance(present, bool):
        raise ValueError("a gold Box label needs 'present' to be true or false")
    if not present:
        if set(label) != {"present"}:
            raise ValueError("an absent gold Box label must be exactly {'present': false}")
        return None
    if set(label) != {"present", "box"}:
        raise ValueError("a present gold Box label must be exactly 'present' and 'box'")
    raw = label["box"]
    if not isinstance(raw, Mapping) or set(raw) != set(_EDGES):
        raise ValueError("a gold Box label's box needs exactly top, bottom, left and right")
    box = normalized_box(raw)
    if (box["right"] - box["left"]) * (box["bottom"] - box["top"]) <= 0.0:
        raise ValueError("gold box area underflows to zero; it cannot be scored")
    return box


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


def crop_bounds(box: Any, width: int, height: int, *, expand: float = 0.0) -> PixelBounds:
    """Pixel ``(left, top, right, bottom)`` that :func:`crop_box` crops, for a ``width`` x ``height`` image.

    Use these bounds with :meth:`ImageTransform.crop` to map a box found on the crop back to
    the image it was cut from.
    """
    return normalized_to_pixels(expand_box(box, expand), width, height)


def _require_min_side(width: int, height: int, min_side: Any, what: str) -> None:
    """Refuse a ``what`` (a crop or tile) with a side under ``min_side``; ``None`` skips the check."""
    if min_side is None:
        return
    min_side = _positive_int(min_side, "min_side")
    if min(width, height) < min_side:
        raise ValueError(
            f"{what} would be {width} x {height} pixels, under min_side={min_side} on a side; "
            "the API rejects such an image. Pad or scale it up with prepare_image, or use a "
            "larger region"
        )


def crop_box(
    image: Image.Image, box: Any, *, expand: float = 0.0, min_side: int | None = None
) -> Image.Image:
    """Copy the enclosed crop, with optional proportional expansion and clipping.

    With ``min_side`` (use ``IMAGE_LIMITS["min_side"]``, 280) a crop with a side under it raises
    ``ValueError`` before anything is cropped, instead of returning an image the API would
    reject. The default ``None`` checks nothing: a small crop must still go through
    :func:`prepare_image` before it is saved as an asset.
    """
    bounds = crop_bounds(box, *image.size, expand=expand)
    _require_min_side(bounds[2] - bounds[0], bounds[3] - bounds[1], min_side, "crop")
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
    after an entire tile is resized without changing its aspect-relative coordinates. A tile
    that was padded or cropped again needs :class:`ImageTransform` (``crop(...).then(...)``);
    :func:`image_to_tile` is the inverse of this function.
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

    With ``min_side`` (use ``IMAGE_LIMITS["min_side"]``, 280) a request whose tiles would have
    a side under it raises ``ValueError``: a ``tile_size`` under ``min_side``, or a source
    narrower than it (a source smaller than a tile keeps its extent). Every tile has the same
    size, ``min(tile_width, width)`` by ``min(tile_height, height)``, so the check is made
    once, before any tile is cropped. The default ``None`` checks nothing; send small tiles
    through :func:`prepare_image` instead.

    The number of tiles grows with the inverse square of the stride (tile size minus
    ``overlap``), so the tile count is computed first and a configuration above
    ``max_tiles`` (default 256) raises ``ValueError`` before any tile is cropped. Each tile
    is usually one API call, so the cap bounds cost as well as memory. Raise ``max_tiles``
    deliberately.
    """
    max_tiles = _positive_int(max_tiles, "max_tiles")
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
    _require_min_side(min(tile_width, width), min(tile_height, height), min_side, "tile")

    def starts(length: int, window: int) -> list[int]:
        if length <= window:
            return [0]
        positions = list(range(0, length - window + 1, window - int(overlap)))
        if positions[-1] != length - window:
            positions.append(length - window)
        return positions

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


_Edges = tuple[Fraction, Fraction, Fraction, Fraction]  # left, top, right, bottom
_FULL: _Edges = (Fraction(0), Fraction(0), Fraction(1), Fraction(1))


def _snap(value: float, dimension: int) -> Fraction:
    """``value`` exactly, except the double nearest ``k / dimension`` is read as ``k / dimension``.

    A pixel edge stored as ``k / dimension`` is not exactly that fraction in binary (0.2 is a
    hair above 1/5), so a box that really touches a tile edge would overlap it by 1e-17 and
    leave a sliver. This is the same rule :func:`normalized_to_pixels` applies to integer edges.
    """
    nearest = round(value * dimension)
    return Fraction(nearest, dimension) if value == nearest / dimension else Fraction(value)


def _edges(box: Any, size: tuple[int, int]) -> _Edges:
    """A validated normalized box on a ``size`` image as exact ``(left, top, right, bottom)``."""
    box = normalized_box(box)
    return (
        _snap(box["left"], size[0]),
        _snap(box["top"], size[1]),
        _snap(box["right"], size[0]),
        _snap(box["bottom"], size[1]),
    )


def _clip(edges: _Edges, window: _Edges) -> _Edges | None:
    """The part of ``edges`` inside ``window``, or ``None`` when it has no area there."""
    left, top = max(edges[0], window[0]), max(edges[1], window[1])
    right, bottom = min(edges[2], window[2]), min(edges[3], window[3])
    return (left, top, right, bottom) if left < right and top < bottom else None


def _remap(edges: _Edges, source: _Edges, target: _Edges) -> _Edges:
    """Carry edges linearly from the ``source`` window onto the ``target`` window."""
    fx = (target[2] - target[0]) / (source[2] - source[0])
    fy = (target[3] - target[1]) / (source[3] - source[1])
    return (
        target[0] + (edges[0] - source[0]) * fx,
        target[1] + (edges[1] - source[1]) * fy,
        target[0] + (edges[2] - source[0]) * fx,
        target[1] + (edges[3] - source[1]) * fy,
    )


def _as_box(edges: _Edges) -> dict[str, float]:
    left, top, right, bottom = (float(value) for value in edges)
    if left >= right or top >= bottom:
        raise ValueError("the mapped box is too small to represent as a float rectangle")
    return {"top": top, "bottom": bottom, "left": left, "right": right}


def _size_pair(value: Any, name: str) -> tuple[int, int]:
    try:
        width, height = value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a (width, height) pair of positive integers") from exc
    return _positive_int(width, f"{name} width"), _positive_int(height, f"{name} height")


@dataclass(frozen=True)
class ImageTransform:
    """How a box on one image maps to and from the image derived from it.

    The *original* image is the one you started from and the *derived* image is what you sent
    to Jev: a tile or crop of the original, an original resized and padded by
    :func:`prepare_image`, or a chain of those joined by :meth:`then`. Boxes on both images are
    normalized ``top/bottom/left/right`` mappings.

    Two windows say which part of each image the transform covers, as exact
    ``(left, top, right, bottom)`` fractions of that image:

    * ``original_window``: the part of the original the derived image shows (the whole
      original for a resize or a pad; the tile or crop rectangle for a crop);
    * ``derived_window``: where that part sits in the derived image (the whole derived image
      for a crop; the content rectangle, inside the padding, after a pad).

    :meth:`to_derived` and :meth:`to_original` map linearly between the windows and clip to
    them. Arithmetic is exact (:class:`fractions.Fraction`) and each edge is rounded to a float
    once, so a box mapped through any chain of steps equals the true position rounded once, not
    the sum of a rounding error per step. An input edge that is the double nearest ``k / width``
    (or ``k / height``) of the image the box is on is read as exactly that pixel edge, so a box
    that touches a tile edge does not spill a sliver across it. Build one with :meth:`crop`, :func:`prepare_image`
    or :meth:`then`; the constructor only checks that the sizes and windows are valid.
    """

    original_size: tuple[int, int]
    derived_size: tuple[int, int]
    original_window: _Edges
    derived_window: _Edges

    def __post_init__(self) -> None:
        _size_pair(self.original_size, "original_size")
        _size_pair(self.derived_size, "derived_size")
        for name in ("original_window", "derived_window"):
            window = getattr(self, name)
            if (
                not isinstance(window, tuple)
                or len(window) != 4
                or not all(isinstance(value, Fraction) for value in window)
            ):
                raise ValueError(f"{name} must be four exact fractions: left, top, right, bottom")
            left, top, right, bottom = window
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                raise ValueError(f"{name} must be a positive-area rectangle inside the image")

    @classmethod
    def crop(cls, bounds: PixelBounds, width: int, height: int) -> ImageTransform:
        """The transform of cutting ``bounds`` (pixel ``left, top, right, bottom``) from an image.

        ``bounds`` is a tile's ``.bounds`` or :func:`crop_bounds`, and ``width`` and ``height``
        are the size of the image it was cut from. The derived image is the cut, unscaled.
        """
        width, height = _positive_int(width, "width"), _positive_int(height, "height")
        left, top, right, bottom = _pixel_bounds(bounds, width, height)
        return cls(
            (width, height),
            (right - left, bottom - top),
            (
                Fraction(left, width),
                Fraction(top, height),
                Fraction(right, width),
                Fraction(bottom, height),
            ),
            _FULL,
        )

    def to_derived(self, box: Any) -> dict[str, float] | None:
        """Map a box on the original image onto the derived image, clipped to what it shows.

        Returns ``None`` when the box has no area inside ``original_window`` (a box beside the
        tile, or one that only touches its edge). A box the window cuts is clipped to it, so the
        result covers only the visible part: use :meth:`visible_fraction` to decide whether
        enough of the target remains to count it as present.
        """
        visible = _clip(_edges(box, self.original_size), self.original_window)
        if visible is None:
            return None
        return _as_box(_remap(visible, self.original_window, self.derived_window))

    def to_original(self, box: Any) -> dict[str, float] | None:
        """Map a box on the derived image back to the original, clipped to the content.

        Padding is not part of the original, so a box that extends into padding is clipped to
        the content, and a box entirely in padding returns ``None``. A box found partly in
        padding is a signal worth checking, not a result to trust blindly.
        """
        visible = _clip(_edges(box, self.derived_size), self.derived_window)
        if visible is None:
            return None
        return _as_box(_remap(visible, self.derived_window, self.original_window))

    def visible_fraction(self, box: Any) -> float:
        """The fraction of an original-image box's area that the derived image shows.

        Exactly ``1.0`` when the whole box is visible and ``0.0`` when :meth:`to_derived`
        returns ``None``. Use it to state the per-tile rule for a target that a tile edge cuts.
        """
        edges = _edges(box, self.original_size)
        visible = _clip(edges, self.original_window)
        if visible is None:
            return 0.0
        whole = (edges[2] - edges[0]) * (edges[3] - edges[1])
        return float(((visible[2] - visible[0]) * (visible[3] - visible[1])) / whole)

    def then(self, other: ImageTransform) -> ImageTransform:
        """Chain ``other`` (made from this transform's derived image) after this one.

        The result maps between this transform's original image and ``other``'s derived image
        in one step, for any number of levels (``a.then(b).then(c)``). ``other.original_size``
        must equal ``self.derived_size``. Raises ``ValueError`` when ``other`` shows none of
        this transform's content (it cropped only padding), since nothing could be mapped.
        """
        if not isinstance(other, ImageTransform):
            raise ValueError("then() needs another ImageTransform")
        if self.derived_size != other.original_size:
            raise ValueError(
                f"cannot chain: the first transform makes a {self.derived_size} image but the "
                f"second starts from a {other.original_size} image"
            )
        shared = _clip(self.derived_window, other.original_window)
        if shared is None:
            raise ValueError("the second transform shows none of the first transform's content")
        return ImageTransform(
            self.original_size,
            other.derived_size,
            _remap(shared, self.derived_window, self.original_window),
            _remap(shared, other.original_window, other.derived_window),
        )


def image_to_tile(
    box: Any, tile_bounds: PixelBounds, width: int, height: int
) -> dict[str, float] | None:
    """Map a whole-image box into a tile, the inverse of :func:`tile_to_image`.

    ``tile_bounds`` are the tile's exact pixel bounds in the ``width`` x ``height`` image. The
    result is tile-local, clipped to the tile: a box the tile edge cuts keeps only its visible
    part. ``None`` means the box has no area inside the tile (disjoint, or only touching an
    edge), so a gold label for that tile is "absent". See :meth:`ImageTransform.visible_fraction`
    to apply a minimum-visible-fraction rule first.
    """
    return ImageTransform.crop(tile_bounds, width, height).to_derived(box)


_PAD_COLOR = (128, 128, 128)
_PREPARABLE_MODES = ("1", "L", "P", "RGB", "CMYK", "YCbCr")


def _pad_color(value: Any) -> tuple[int, int, int]:
    channels = (value,) * 3 if isinstance(value, Integral) else value
    try:
        red, green, blue = channels
    except (TypeError, ValueError):
        red = None
    else:
        if all(
            isinstance(c, Integral) and not isinstance(c, bool) and 0 <= c <= 255
            for c in (red, green, blue)
        ):
            return int(red), int(green), int(blue)
    raise ValueError("pad_color must be a gray level 0-255 or an (r, g, b) tuple of 0-255")


def prepare_image(
    image: Image.Image,
    *,
    min_side: int = _MIN_SIDE,
    max_side: int = _MAX_SIDE,
    pad_color: int | tuple[int, int, int] = _PAD_COLOR,
    upscale: bool = False,
) -> tuple[Image.Image, ImageTransform]:
    """Resize and pad an image to the API's side limits; return it with its transform.

    Returns ``(prepared, transform)``: a new RGB image whose width and height are each between
    ``min_side`` and ``max_side`` (default 280 and 1568, the Images API limits), and the
    :class:`ImageTransform` that maps a box on ``prepared`` back to ``image`` and a box on
    ``image`` forward. The area limits follow: 280 x 280 = 78,400 and 1568 x 1568 = 2,458,624.

    1. An image whose longest side exceeds ``max_side`` is scaled down, keeping its aspect
       ratio, until that side is ``max_side``.
    2. With ``upscale=True``, an image that is not too large and has a side under ``min_side``
       is scaled up, keeping its aspect ratio, until its shorter side is ``min_side`` (not
       beyond ``max_side`` on the long side). The default ``upscale=False`` never scales up:
       it adds no pixels that were not there.
    3. A side still under ``min_side`` is padded with ``pad_color`` (a gray level or an
       ``(r, g, b)`` tuple, default mid-gray, not measured against Jev), the content centered,
       the odd pixel going right or bottom.

    Scaled sizes are the exact ratio rounded half up, so they are reproducible; resampling is
    Lanczos. Nothing is cropped. An image that already fits comes back as a pixel-identical RGB
    copy with an identity transform. An image with transparency (an alpha channel, or a palette
    with transparency) raises ``ValueError``: flatten it onto an explicit background first,
    since the RGB it hides is arbitrary. The input is not modified.

    The result carries no metadata from ``image`` on any path (no ICC profile, EXIF or text in
    ``.info``), so saving it as PNG writes none of the chunks the image-file contract in
    ``docs/fixtures.md`` forbids. Because that drops the EXIF tag, an image whose EXIF
    orientation is not 1 raises ``ValueError`` (as :func:`image_asset` does): rotate the pixels
    first with ``ImageOps.exif_transpose``.
    """
    min_side, max_side = _positive_int(min_side, "min_side"), _positive_int(max_side, "max_side")
    if min_side > max_side:
        raise ValueError("min_side must not exceed max_side")
    fill = _pad_color(pad_color)
    if image.mode not in _PREPARABLE_MODES or "transparency" in image.info:
        raise ValueError(
            f"cannot prepare a {image.mode!r} image with transparency or an unusual pixel mode; "
            "flatten it onto an explicit background and convert it to RGB first"
        )
    try:
        orientation = image.getexif().get(274, 1)  # the rebuild below drops EXIF and this evidence
    except (struct.error, SyntaxError, OSError) as exc:
        raise ValueError("the image's EXIF data is damaged; remove it before preparing") from exc
    if orientation != 1:
        raise ValueError(_ORIENTATION_MESSAGE)
    width, height = image.size
    _positive_int(width, "image width")
    _positive_int(height, "image height")
    longest, shortest = max(width, height), min(width, height)
    numerator = denominator = 1
    if longest > max_side:
        numerator, denominator = max_side, longest
    elif upscale and shortest < min_side:
        # Grow until the short side reaches min_side, unless the long side would pass max_side.
        if longest * min_side <= max_side * shortest:
            numerator, denominator = min_side, shortest
        else:
            numerator, denominator = max_side, longest

    def scaled(length: int) -> int:
        rounded = (2 * length * numerator + denominator) // (2 * denominator)
        return min(max_side, max(1, rounded))

    content = (scaled(width), scaled(height))
    size = (max(content[0], min_side), max(content[1], min_side))
    left, top = (size[0] - content[0]) // 2, (size[1] - content[1]) // 2
    prepared = image.convert("RGB")
    if content != (width, height):
        prepared = prepared.resize(content, Image.Resampling.LANCZOS)
    if size != content:
        canvas = Image.new("RGB", size, fill)
        canvas.paste(prepared, (left, top))
        prepared = canvas
    window = (
        Fraction(left, size[0]),
        Fraction(top, size[1]),
        Fraction(left + content[0], size[0]),
        Fraction(top + content[1], size[1]),
    )
    # convert() and resize() copy the source's .info (an ICC profile would become an iCCP chunk
    # when saved); only the pad path starts from a fresh canvas. Rebuild from the pixel bytes so
    # every path returns an image with no metadata.
    prepared = Image.frombytes("RGB", prepared.size, prepared.tobytes())
    return prepared, ImageTransform((width, height), size, _FULL, window)


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

    Kept for compatibility; prefer :func:`localization_report`, the recommended entry for
    a Box recipe. This function cannot see reviews: the caller must filter them out first,
    so a present target sent to review silently leaves ``mean_iou``'s denominator, and it
    reports no correct-absent count or hit rate. :func:`localization_report` takes review
    outcomes itself and names every denominator.

    Predictions must already have passed the recipe's presence/confidence policy.
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


_OUTCOMES = ("located", "absent", "review")


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else float("nan")


def _share(numerator: int, denominator: int, what: str) -> str:
    if not denominator:
        return f"n/a (denominator 0: {what})"
    value = numerator / denominator
    return f"{numerator}/{denominator} = {value:.4f} (denominator {denominator}: {what})"


def _mean(value: float, denominator: int, what: str) -> str:
    if not denominator:
        return f"n/a (denominator 0: {what})"
    return f"{value:.4f} (denominator {denominator}: {what})"


@dataclass(frozen=True)
class LocalizationReport:
    """Box outcomes against gold, counting every example exactly once.

    ``n_total`` equals ``n_present + n_absent`` and each side is split by outcome:

    * present gold: ``present_located`` (a box was returned after the presence check),
      ``present_missed`` (the pipeline said absent), ``present_review``;
    * absent gold: ``false_positives`` (a box was returned), ``correct_absents``,
      ``absent_review``.

    ``mean_iou_located`` averages IoU over the ``present_located`` targets only (denominator
    ``present_located``). ``mean_iou_present`` averages over all ``n_present`` with missed and
    reviewed targets counted as 0 (denominator ``n_present``). ``hit_rate`` is ``hits`` (located
    present targets with IoU >= ``iou_threshold``) over ``n_present``. A mean or rate with an
    empty denominator is NaN. ``ious`` has one entry per example: the IoU of a located present
    target, otherwise ``None``. Absent gold never contributes an IoU, and a review is never
    counted as an absent prediction. ``str(report)`` names every denominator.
    """

    n_total: int
    n_present: int
    n_absent: int
    present_located: int
    present_missed: int
    present_review: int
    false_positives: int
    correct_absents: int
    absent_review: int
    iou_threshold: float
    hits: int
    mean_iou_located: float
    mean_iou_present: float
    hit_rate: float
    ious: tuple[float | None, ...]

    @property
    def present_table(self) -> dict[str, int]:
        """Present gold by outcome; the values sum to ``n_present``."""
        return {
            "located": self.present_located,
            "absent": self.present_missed,
            "review": self.present_review,
        }

    @property
    def absent_table(self) -> dict[str, int]:
        """Absent gold by outcome; the values sum to ``n_absent``."""
        return {
            "located": self.false_positives,
            "absent": self.correct_absents,
            "review": self.absent_review,
        }

    @property
    def false_positive_rate(self) -> float:
        """``false_positives / n_absent`` (NaN when no target is absent)."""
        return _rate(self.false_positives, self.n_absent)

    @property
    def correct_absent_rate(self) -> float:
        """``correct_absents / n_absent`` (NaN when no target is absent)."""
        return _rate(self.correct_absents, self.n_absent)

    @property
    def denominators(self) -> dict[str, int]:
        """The denominator of every mean and rate in the report, by name."""
        return {
            "mean_iou_located": self.present_located,
            "mean_iou_present": self.n_present,
            "hit_rate": self.n_present,
            "false_positive_rate": self.n_absent,
            "correct_absent_rate": self.n_absent,
        }

    def __str__(self) -> str:
        located = _mean(self.mean_iou_located, self.present_located, "located present targets")
        overall = _mean(self.mean_iou_present, self.n_present, "all present targets")
        return "\n".join(
            [
                f"Localization report: {self.n_total} examples "
                f"({self.n_present} present + {self.n_absent} absent), each counted once",
                f"Present targets (n = {self.n_present}): box returned {self.present_located}, "
                f"said absent (missed) {self.present_missed}, sent to review {self.present_review}",
                f"  mean IoU over located present targets: {located}",
                f"  mean IoU over all present targets, missed and review counted as 0: {overall}",
                f"  hit rate at IoU >= {self.iou_threshold:g}: "
                + _share(self.hits, self.n_present, "all present targets"),
                f"Absent targets (n = {self.n_absent}): box returned (false positive) "
                f"{self.false_positives}, correct absent {self.correct_absents}, "
                f"sent to review {self.absent_review}",
                "  false positive rate: "
                + _share(self.false_positives, self.n_absent, "all absent targets"),
                "  correct absent rate: "
                + _share(self.correct_absents, self.n_absent, "all absent targets"),
            ]
        )


def localization_report(
    gold: Iterable[Any], outcomes: Iterable[Any], *, iou_threshold: float = 0.5
) -> LocalizationReport:
    """Score Box outcomes against gold Box labels without letting any example drop out.

    ``gold`` holds one label per example in the format :func:`gold_box` decodes (a malformed
    or degenerate label raises). ``outcomes`` holds one pair per example, produced by the
    recipe's presence and confidence policy: ``("located", box)``, ``("absent", None)`` or
    ``("review", None)``. A review is never an absent prediction, and a returned rectangle
    is never evidence the target exists: a ``located`` box on absent gold is a false
    positive. Every example lands in exactly one cell of the present or absent table. An
    example is a hit when its IoU is at least ``iou_threshold``, a number in (0, 1].
    Empty or unequal-length inputs, an unknown outcome kind, a ``located`` outcome without
    a valid box, or a box attached to ``absent``/``review`` raise ``ValueError``.
    """
    if isinstance(iou_threshold, bool) or not isinstance(iou_threshold, Real):
        raise ValueError("iou_threshold must be a number in (0, 1]")
    if not (math.isfinite(iou_threshold) and 0 < iou_threshold <= 1):
        raise ValueError("iou_threshold must be a number in (0, 1]")
    targets, results = list(gold), list(outcomes)
    if not targets or len(targets) != len(results):
        raise ValueError("gold and outcomes must be nonempty and have the same length")
    present_table = dict.fromkeys(_OUTCOMES, 0)
    absent_table = dict.fromkeys(_OUTCOMES, 0)
    ious: list[float | None] = []
    for index, (label, outcome) in enumerate(zip(targets, results, strict=True)):
        try:
            target = gold_box(label)
            if (
                isinstance(outcome, (str, bytes))
                or not isinstance(outcome, (tuple, list))
                or len(outcome) != 2
            ):
                raise ValueError("an outcome must be a (kind, box-or-None) pair")
            kind, box = outcome
            if kind not in _OUTCOMES:
                raise ValueError(f"outcome kind must be one of {_OUTCOMES}, not {kind!r}")
            if kind == "located":
                guess = normalized_box(box)
            elif box is not None:
                raise ValueError(f"a {kind!r} outcome must carry None, not a box")
        except ValueError as exc:
            raise ValueError(f"example {index}: {exc}") from exc
        if target is None:
            absent_table[kind] += 1
            ious.append(None)
        else:
            present_table[kind] += 1
            ious.append(box_iou(target, guess) if kind == "located" else None)
    overlaps = [value for value in ious if value is not None]
    n_present, n_absent = sum(present_table.values()), sum(absent_table.values())
    hits = sum(value >= iou_threshold for value in overlaps)
    # Targets that are not located score 0 in the all-present mean, so its sum is the located sum.
    return LocalizationReport(
        n_total=len(targets),
        n_present=n_present,
        n_absent=n_absent,
        present_located=present_table["located"],
        present_missed=present_table["absent"],
        present_review=present_table["review"],
        false_positives=absent_table["located"],
        correct_absents=absent_table["absent"],
        absent_review=absent_table["review"],
        iou_threshold=float(iou_threshold),
        hits=hits,
        mean_iou_located=math.fsum(overlaps) / len(overlaps) if overlaps else float("nan"),
        mean_iou_present=math.fsum(overlaps) / n_present if n_present else float("nan"),
        hit_rate=_rate(hits, n_present),
        ious=tuple(ious),
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
