"""Offline image validation and geometry tests with independently computed expectations."""

from __future__ import annotations

import base64
import contextlib
import datetime
import hashlib
import importlib.util
import io
import json
import math
import random
import re
import sys
from dataclasses import is_dataclass
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import Choice, Noul, Score, live, vision
from jev_cookbook._canonical import canonical_image_format
from jev_cookbook.fixtures._scan import scan_text

FULL = {"top": 0.0, "bottom": 1.0, "left": 0.0, "right": 1.0}
BOX = {"top": 0.25, "bottom": 0.75, "left": 0.125, "right": 0.625}


def save_image(tmp_path, *, size=(320, 280), fmt="PNG", name="image", color="white", **kwargs):
    path = tmp_path / name
    Image.new("RGB", size, color).save(path, format=fmt, **kwargs)
    return path


@pytest.fixture
def image_path(tmp_path):
    return save_image(tmp_path)


@pytest.fixture
def asset(image_path):
    return {
        "type": "image",
        "format": "png",
        "data_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
    }


@pytest.mark.parametrize("fmt,expected", [("PNG", "png"), ("JPEG", "jpeg")])
def test_image_asset_uses_actual_format_and_preserves_encoded_bytes(tmp_path, fmt, expected):
    path = save_image(tmp_path, fmt=fmt, name="wrong-extension.gif")
    result = vision.image_asset(path)
    assert result == {
        "type": "image",
        "format": expected,
        "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }
    assert vision.validate_image_asset(result) == path.read_bytes()


@pytest.mark.parametrize("size", [(280, 280), (280, 1568), (1568, 280), (1568, 1568), (320, 280)])
def test_image_asset_accepts_boundary_dimensions(tmp_path, size):
    assert vision.image_asset(save_image(tmp_path, size=size))["type"] == "image"


@pytest.mark.parametrize(
    "size",
    [
        (279, 400),  # width one under the 280 minimum
        (400, 279),  # height one under the 280 minimum
        (279, 279),
        (256, 307),  # accepted before the minimum was corrected from 256 to 280
        (255, 400),
        (400, 255),
        (1569, 280),
        (280, 1569),
    ],
)
def test_image_asset_rejects_invalid_dimensions(tmp_path, size):
    with pytest.raises(ValueError, match="width and height must each be 280 to 1568"):
        vision.image_asset(save_image(tmp_path, size=size))


@pytest.mark.parametrize("size", [(279, 400), (400, 279)])
def test_validate_image_asset_rejects_a_279_pixel_side_on_either_axis(tmp_path, size):
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    with pytest.raises(ValueError, match="280 to 1568"):
        vision.validate_image_asset({"type": "image", "format": "png", "data_base64": encoded})
    # 280 on the same axis is accepted.
    good = (280, size[1] + 1) if size[0] == 279 else (size[0] + 1, 280)
    buffer = io.BytesIO()
    Image.new("RGB", good, "white").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    asset = {"type": "image", "format": "png", "data_base64": encoded}
    assert vision.validate_image_asset(asset) == buffer.getvalue()


# The upstream numbers, copied by hand from the "Limits" table at
# https://docs.typesafe.ai/images (fetched 2026-10-20). If the page changes, update this
# table, vision.IMAGE_LIMITS and docs/vision.md together.
UPSTREAM_LIMITS = {
    "min_side": 280,
    "max_side": 1568,
    "min_area": 78_400,
    "max_area": 2_458_624,
    "max_bytes": 16 * 1024 * 1024,
}


def test_image_limits_match_the_upstream_table_and_the_docs():
    assert vision.IMAGE_LIMITS == UPSTREAM_LIMITS
    assert UPSTREAM_LIMITS["min_area"] == UPSTREAM_LIMITS["min_side"] ** 2
    assert UPSTREAM_LIMITS["max_area"] == UPSTREAM_LIMITS["max_side"] ** 2
    docs = (Path(__file__).resolve().parents[1] / "docs" / "vision.md").read_text("utf-8")
    flat = " ".join(docs.split())
    sides = f"{UPSTREAM_LIMITS['min_side']}–{UPSTREAM_LIMITS['max_side']}"
    areas = f"{UPSTREAM_LIMITS['min_area']:,}–{UPSTREAM_LIMITS['max_area']:,}"
    assert f"dimension {sides} and total area {areas} pixels" in flat
    assert "at most 16 MiB" in flat
    assert "256–1568" not in flat
    assert "280 to 1568" in " ".join((vision.validate_image_asset.__doc__ or "").split())


def test_image_asset_missing_file_and_url(tmp_path):
    with pytest.raises(FileNotFoundError):
        vision.image_asset(tmp_path / "missing.png")
    with pytest.raises(ValueError):
        vision.image_asset("https://example.invalid/image.png")


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "WEBP"])
def test_image_asset_rejects_unsupported_actual_formats(tmp_path, fmt):
    with pytest.raises(ValueError):
        vision.image_asset(save_image(tmp_path, fmt=fmt, name="deceptive.png"))


def test_image_asset_rejects_corruption_and_oversized_file(tmp_path, image_path):
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(image_path.read_bytes()[:80])
    with pytest.raises(ValueError):
        vision.image_asset(corrupt)
    image_path.write_bytes(image_path.read_bytes() + b"\0" * (16 * 1024 * 1024))
    with pytest.raises(ValueError):
        vision.image_asset(image_path)


def test_image_asset_rejects_animated_png(tmp_path):
    path = tmp_path / "animated.png"
    Image.new("RGB", (320, 280), "white").save(
        path,
        save_all=True,
        append_images=[Image.new("RGB", (320, 280), "black")],
        duration=100,
        loop=0,
    )
    with pytest.raises(ValueError):
        vision.image_asset(path)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_image_asset_rejects_exif_rotation_but_accepts_upright(tmp_path, fmt):
    exif = Image.Exif()
    exif[274] = 6
    path = save_image(tmp_path, fmt=fmt, exif=exif)
    with pytest.raises(ValueError):
        vision.image_asset(path)
    exif[274] = 1
    path = save_image(tmp_path, fmt=fmt, exif=exif)
    assert vision.image_asset(path)["type"] == "image"


@pytest.mark.parametrize(
    "change",
    [
        {"type": "text"},
        {"format": "gif"},
        {"format": "jpeg"},
        {"data_base64": "!invalid!"},
        {"data_base64": ""},
        {"extra": "unexpected"},
    ],
)
def test_validate_image_asset_rejects_bad_fields(asset, change):
    with pytest.raises(ValueError):
        vision.validate_image_asset({**asset, **change})


@pytest.mark.parametrize("missing", ["type", "format", "data_base64"])
def test_validate_image_asset_requires_exact_fields(asset, missing):
    del asset[missing]
    with pytest.raises(ValueError):
        vision.validate_image_asset(asset)


def test_validate_image_asset_requires_strict_base64_and_valid_image(asset):
    for data in [
        asset["data_base64"] + "\n",
        base64.b64encode(b"not an image").decode("ascii"),
        asset["data_base64"].encode("ascii"),
    ]:
        with pytest.raises(ValueError):
            vision.validate_image_asset({**asset, "data_base64": data})


def test_validate_image_asset_accepts_jpg_alias(tmp_path):
    path = save_image(tmp_path, fmt="JPEG")
    asset = vision.image_asset(path)
    assert vision.validate_image_asset({**asset, "format": "jpg"}) == path.read_bytes()


def test_the_canonical_format_function_is_the_only_alias_table():
    assert [canonical_image_format(v) for v in ("png", "PNG", "jpeg", "jpg", "JPG")] == [
        "png",
        "png",
        "jpeg",
        "jpeg",
        "jpeg",
    ]
    for bad in ("gif", "", " png", "jpe", None, 7, b"png"):
        with pytest.raises(ValueError):
            canonical_image_format(bad)


def test_validate_image_asset_accepts_every_spelling_of_a_format(tmp_path):
    path = save_image(tmp_path, fmt="JPEG")
    asset = vision.image_asset(path)
    for spelling in ("jpeg", "jpg", "JPEG", "JPG"):
        assert vision.validate_image_asset({**asset, "format": spelling}) == path.read_bytes()
    with pytest.raises(ValueError, match="does not match"):
        vision.validate_image_asset({**asset, "format": "PNG"})


@pytest.fixture
def recipe(tmp_path):
    """A recipe folder with a nested asset, plus an image and a symlink outside it."""
    folder = tmp_path / "recipe"
    (folder / "assets" / "nested").mkdir(parents=True)
    save_image(folder / "assets" / "nested", name="inside.png")
    save_image(tmp_path, name="outside.png", color="black")
    return folder


def test_root_loads_a_legitimate_nested_relative_path(recipe):
    inside = recipe / "assets" / "nested" / "inside.png"
    expected = vision.image_asset(inside)
    assert vision.image_asset("assets/nested/inside.png", root=recipe) == expected
    assert vision.image_asset(Path("assets/nested/inside.png"), root=str(recipe)) == expected
    # `..` that stays inside the folder is not an escape.
    assert vision.image_asset("assets/../assets/nested/inside.png", root=recipe) == expected
    assert vision.resolve_asset_path("assets/nested/inside.png", root=recipe) == inside.resolve()
    assert vision.image_assets({"a": "assets/nested/inside.png"}, root=recipe) == {"a": expected}
    state, assets = vision.load_frames([(0.0, "assets/nested/inside.png")], root=recipe)
    assert list(assets.values()) == [expected] and state[0]["image"] in assets


def test_root_refuses_dot_dot_traversal(recipe):
    for escaping in (
        "../outside.png",
        "assets/../../outside.png",
        "assets/nested/../../../outside.png",
    ):
        assert (recipe / escaping).resolve().is_file()  # it is a real, valid image
        with pytest.raises(vision.AssetPathError, match="outside"):
            vision.image_asset(escaping, root=recipe)
        with pytest.raises(vision.AssetPathError):
            vision.resolve_asset_path(escaping, root=recipe)
    # Refused before existence is revealed.
    with pytest.raises(vision.AssetPathError):
        vision.image_asset("../nothing-here.png", root=recipe)


def test_root_refuses_absolute_paths_even_inside_the_root(recipe, tmp_path):
    for absolute in (tmp_path / "outside.png", recipe / "assets" / "nested" / "inside.png"):
        assert absolute.is_absolute()
        with pytest.raises(vision.AssetPathError, match="relative"):
            vision.image_asset(absolute, root=recipe)
        with pytest.raises(vision.AssetPathError, match="relative"):
            vision.image_asset(str(absolute), root=recipe)


def test_root_refuses_urls(recipe):
    for url in ("https://example.invalid/a.png", "data:image/png;base64,AAAA"):
        with pytest.raises(vision.AssetPathError, match="URL"):
            vision.image_asset(url, root=recipe)


def test_root_refuses_a_symlink_that_escapes(recipe, tmp_path):
    try:
        (recipe / "assets" / "link.png").symlink_to(tmp_path / "outside.png")
        (recipe / "assets" / "dirlink").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("symlinks unavailable")
    for escaping in ("assets/link.png", "assets/dirlink/outside.png"):
        with pytest.raises(vision.AssetPathError, match="outside"):
            vision.image_asset(escaping, root=recipe)
        with pytest.raises(vision.AssetPathError):
            vision.image_assets({"x": escaping}, root=recipe)
        with pytest.raises(vision.AssetPathError):
            vision.load_frames([(0.0, escaping)], root=recipe)
    # Without root the caller has opted out, so the same link is followed as written.
    assert vision.image_asset(recipe / "assets" / "link.png")["type"] == "image"


def test_root_allows_a_symlink_that_stays_inside(recipe):
    try:
        (recipe / "assets" / "alias.png").symlink_to(recipe / "assets" / "nested" / "inside.png")
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("symlinks unavailable")
    assert vision.image_asset("assets/alias.png", root=recipe) == vision.image_asset(
        recipe / "assets" / "nested" / "inside.png"
    )


def test_a_contained_missing_file_is_still_file_not_found(recipe):
    with pytest.raises(FileNotFoundError):
        vision.image_asset("assets/missing.png", root=recipe)


def test_containment_errors_are_value_errors_and_never_swallowed(recipe):
    assert issubclass(vision.AssetPathError, ValueError)
    with pytest.raises(ValueError):
        vision.image_assets({"a": "assets/nested/inside.png", "b": "../outside.png"}, root=recipe)
    with pytest.raises(ValueError):
        vision.load_frames(
            [(0.0, "assets/nested/inside.png"), (1.0, "../outside.png")], root=recipe
        )


def test_image_references_follow_content_not_path(tmp_path, image_path, asset):
    copy = tmp_path / "copy.png"
    copy.write_bytes(image_path.read_bytes())
    changed = save_image(tmp_path, name="different.png", color="black")
    ref = vision.image_reference(asset)
    assert isinstance(ref, str) and ref
    assert ref == vision.image_reference(vision.image_asset(copy))
    assert ref != vision.image_reference(vision.image_asset(changed))


def test_image_references_preserve_full_digest_without_fixture_secret_scan_hits(tmp_path):
    inputs = []
    legacy_inputs = []
    for seed in range(16):
        pixels = random.Random(seed).randbytes(280 * 280 * 3)
        path = tmp_path / f"random-{seed}.png"
        Image.frombytes("RGB", (280, 280), pixels).save(path, compress_level=0)
        asset = vision.image_asset(path)
        reference = vision.image_reference(asset)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert reference == f"image:sha256:{digest}"
        assert reference == vision.image_reference(vision.image_asset(path))
        inputs.append({"id": str(seed), "fields": {"image": reference}})
        legacy_inputs.append({"id": str(seed), "fields": {"image": f"image-sha256-{digest}"}})

    assert len({row["fields"]["image"] for row in inputs}) == 16
    assert scan_text("\n".join(json.dumps(row) for row in inputs)) == []
    # Prove this sample catches the old prefix's combined-alphabet entropy false positive.
    legacy_text = "\n".join(json.dumps(row) for row in legacy_inputs)
    assert any(rule == "high-entropy-token" for _, rule, _ in scan_text(legacy_text))


def test_image_assets_preserves_requested_references(image_path, asset):
    assert vision.image_assets({"first": image_path, "second": image_path}) == {
        "first": asset,
        "second": asset,
    }


@pytest.mark.parametrize("reference", ["", "  ", None, 7])
def test_image_assets_rejects_invalid_references(image_path, reference):
    with pytest.raises(ValueError):
        vision.image_assets({reference: image_path})


@pytest.mark.parametrize(
    "value",
    [
        BOX,
        {"box": BOX, "confidence": 0.8},
        SimpleNamespace(box=BOX),
        SimpleNamespace(box=SimpleNamespace(**BOX)),
    ],
)
def test_normalized_box_accepts_answer_shapes_and_copies(value):
    result = vision.normalized_box(value)
    assert result == BOX
    assert result is not BOX
    result["top"] = 0.5
    assert BOX["top"] == 0.25


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"box": None},
        {},
        {"top": 0.0, "bottom": 1.0, "left": 0.0},
        {**BOX, "top": True},
        {**BOX, "top": math.nan},
        {**BOX, "right": math.inf},
        {**BOX, "left": -0.01},
        {**BOX, "bottom": 1.01},
        {**BOX, "top": 0.75},
        {**BOX, "top": 0.8},
        {**BOX, "right": 0.125},
        {**BOX, "right": 0.0},
    ],
)
def test_normalized_box_rejects_invalid_coordinates(bad):
    with pytest.raises(ValueError):
        vision.normalized_box(bad)


def test_normalized_to_pixels_rounds_outward_with_half_open_edges():
    # x=(1.375,6.875), y=(1.75,5.25): floor the starts, ceil the ends.
    assert vision.normalized_to_pixels(BOX, 11, 7) == (1, 1, 7, 6)
    assert vision.normalized_to_pixels(FULL, 11, 7) == (0, 0, 11, 7)
    tiny = {"top": 0.31, "bottom": 0.32, "left": 0.41, "right": 0.42}
    assert vision.normalized_to_pixels(tiny, 10, 10) == (4, 3, 5, 4)


def test_normalized_to_pixels_restores_integer_edges_with_float_round_trip_drift():
    bounds = (1, 49, 53, 55)
    box = vision.tile_to_image(FULL, bounds, 1568, 777)
    # These exact pixel boundaries multiply back just below starts and above ends.
    assert box["left"] * 1568 < 1
    assert box["right"] * 1568 > 53
    assert box["top"] * 777 < 49
    assert box["bottom"] * 777 > 55
    assert vision.normalized_to_pixels(box, 1568, 777) == bounds


@pytest.mark.parametrize(
    "offset,expected",
    [(-1e-9, (511, 255, 1024, 768)), (1e-9, (512, 256, 1025, 769))],
)
def test_normalized_to_pixels_preserves_real_fractional_pixel_edges(offset, expected):
    box = {
        "left": (512 + offset) / 1568,
        "right": (1024 + offset) / 1568,
        "top": (256 + offset) / 1024,
        "bottom": (768 + offset) / 1024,
    }
    assert vision.normalized_to_pixels(box, 1568, 1024) == expected


@pytest.mark.parametrize(
    "direction,expected",
    [(-math.inf, (255, 255, 768, 768)), (math.inf, (256, 256, 769, 769))],
)
@pytest.mark.parametrize("steps", [1, 3])
def test_normalized_to_pixels_preserves_noncanonical_edges_a_few_ulps_away(
    direction, expected, steps
):
    start, end = 0.25, 0.75
    for _ in range(steps):
        start = math.nextafter(start, direction)
        end = math.nextafter(end, direction)
    # Power-of-two scaling is exact: these coordinates really lie outside/inside
    # pixel edges 256 and 768, even when only one floating-point increment away.
    assert start != 256 / 1024 and end != 768 / 1024
    assert not (start * 1024).is_integer() and not (end * 1024).is_integer()
    box = {"left": start, "top": start, "right": end, "bottom": end}
    assert vision.normalized_to_pixels(box, 1024, 1024) == expected


@pytest.mark.parametrize("width,height", [(0, 4), (4, -1), (True, 4), (4, 2.5)])
def test_normalized_to_pixels_rejects_invalid_dimensions(width, height):
    with pytest.raises(ValueError):
        vision.normalized_to_pixels(BOX, width, height)


def test_box_iou_uses_intersection_over_union():
    first = {"top": 0.0, "bottom": 0.5, "left": 0.0, "right": 0.5}
    second = {"top": 0.25, "bottom": 0.75, "left": 0.25, "right": 0.75}
    # Intersection=1/16, union=1/4+1/4-1/16=7/16.
    assert vision.box_iou(first, second) == pytest.approx(1 / 7)
    assert vision.box_iou(second, first) == pytest.approx(1 / 7)
    assert vision.box_iou(first, first) == 1.0
    assert vision.box_iou(first, FULL) == pytest.approx(0.25)
    for left in [0.5, 0.75]:
        assert vision.box_iou(first, {**first, "left": left, "right": 1.0}) == 0.0


@pytest.mark.parametrize("a,b", [(None, BOX), (BOX, None), (BOX, {**BOX, "right": -1})])
def test_box_iou_rejects_invalid_and_absent_boxes(a, b):
    with pytest.raises(ValueError):
        vision.box_iou(a, b)


def test_expand_box_adds_fraction_per_side_and_clips():
    # Each side expands by 0.25 times its original 0.5 extent, or 0.125.
    assert vision.expand_box(BOX, fraction=0.25) == pytest.approx(
        {"top": 0.125, "bottom": 0.875, "left": 0.0, "right": 0.75}
    )
    assert vision.expand_box(BOX, fraction=10) == FULL
    result = vision.expand_box(BOX)
    assert result == BOX and result is not BOX


@pytest.mark.parametrize("fraction", [-0.1, math.nan, math.inf, True])
def test_expand_box_rejects_invalid_fraction(fraction):
    with pytest.raises(ValueError):
        vision.expand_box(BOX, fraction=fraction)


def coordinate_image(width, height):
    image = Image.new("RGB", (width, height))
    image.putdata([(x, y, (x + y) % 256) for y in range(height) for x in range(width)])
    return image


def test_crop_box_returns_independent_pixels_with_optional_expansion():
    image = coordinate_image(16, 8)
    before = image.tobytes()
    crop = vision.crop_box(image, BOX)
    assert crop.size == (8, 4)
    assert crop.getpixel((0, 0)) == (2, 2, 4)
    assert crop.getpixel((7, 3)) == (9, 5, 14)
    expanded = vision.crop_box(image, BOX, expand=0.25)
    assert expanded.size == (12, 6)
    assert expanded.getpixel((0, 0)) == (0, 1, 1)
    crop.putpixel((0, 0), (255, 0, 0))
    assert image.tobytes() == before


def test_generate_tiles_anchor_last_windows_in_row_major_order():
    image = coordinate_image(11, 7)
    before = image.tobytes()
    tiles = vision.generate_tiles(image, tile_size=(4, 3))
    expected = [(left, top, left + 4, top + 3) for top in [0, 3, 4] for left in [0, 4, 7]]
    assert [tile.bounds for tile in tiles] == expected
    for tile in tiles:
        assert tile.image.size == (4, 3)
        assert tile.image.tobytes() == image.crop(tile.bounds).tobytes()
    tiles[0].image.putpixel((0, 0), (255, 255, 255))
    assert image.tobytes() == before


def test_generate_tiles_smaller_image_produces_one_independent_tile():
    image = coordinate_image(3, 2)
    tiles = vision.generate_tiles(image, tile_size=(4, 4))
    assert len(tiles) == 1
    assert tiles[0].bounds == (0, 0, 3, 2)
    assert tiles[0].image is not image
    assert tiles[0].image.tobytes() == image.tobytes()


def test_second_default_tile_round_trip_preserves_crop_pixels():
    size = (1568, 1024)
    pixels = random.Random(0).randbytes(size[0] * size[1] * 3)
    image = Image.frombytes("RGB", size, pixels)
    tile = vision.generate_tiles(image)[1]
    assert tile.bounds == (512, 0, 1024, 512)
    box = vision.tile_to_image(FULL, tile.bounds, *size)
    assert vision.normalized_to_pixels(box, *size) == tile.bounds
    cropped = vision.crop_box(image, box)
    assert cropped.size == tile.image.size == (512, 512)
    assert cropped.tobytes() == tile.image.tobytes()


@pytest.mark.parametrize("size", [(1568, 1024), (1024, 1568), (1000, 777), (997, 769)])
@pytest.mark.parametrize("overlap", [0, 73])
def test_all_tile_bounds_round_trip_through_normalized_whole_image(size, overlap):
    image = Image.new("RGB", size)
    tiles = vision.generate_tiles(image, overlap=overlap)
    assert tiles[-1].bounds[2:] == size
    for tile in tiles:
        box = vision.tile_to_image(FULL, tile.bounds, *size)
        assert vision.normalized_to_pixels(box, *size) == tile.bounds


def test_generate_tiles_overlap_is_measured_in_pixels():
    tiles = vision.generate_tiles(coordinate_image(10, 7), tile_size=(4, 3), overlap=1)
    assert [tile.bounds for tile in tiles] == [
        (left, top, left + 4, top + 3) for top in [0, 2, 4] for left in [0, 3, 6]
    ]


@pytest.mark.parametrize("size", [(4, 3), (8, 6)])
def test_generate_tiles_does_not_duplicate_exact_final_windows(size):
    tiles = vision.generate_tiles(coordinate_image(*size), tile_size=(4, 3))
    assert [tile.bounds for tile in tiles] == [
        (left, top, left + 4, top + 3)
        for top in range(0, size[1], 3)
        for left in range(0, size[0], 4)
    ]


@pytest.mark.parametrize("overlap", [-1, True, 0.5, 3, 4])
def test_generate_tiles_rejects_invalid_overlap(overlap):
    with pytest.raises(ValueError):
        vision.generate_tiles(Image.new("RGB", (10, 7)), tile_size=(4, 3), overlap=overlap)


@pytest.mark.parametrize("tile_size", [(0, 3), (4, -1), (True, 3), (4, 2.5)])
def test_generate_tiles_rejects_invalid_tile_dimensions(tile_size):
    with pytest.raises(ValueError):
        vision.generate_tiles(Image.new("RGB", (10, 7)), tile_size=tile_size)


def test_tile_to_image_uses_exact_pixel_bounds():
    # Tile (20,10)..(60,50): local x=(5,25), y=(10,30), then translate.
    assert vision.tile_to_image(BOX, (20, 10, 60, 50), 100, 80) == pytest.approx(
        {"left": 0.25, "right": 0.45, "top": 0.25, "bottom": 0.5}
    )
    assert vision.tile_to_image(FULL, (20, 10, 60, 50), 100, 80) == pytest.approx(
        {"left": 0.2, "right": 0.6, "top": 0.125, "bottom": 0.625}
    )


@pytest.mark.parametrize(
    "bounds",
    [(0, 0, 0, 5), (-1, 0, 5, 5), (0, 0, 101, 5), (0, 0, 5, 81), (0, 0, 1.5, 5)],
)
def test_tile_to_image_rejects_invalid_pixel_bounds(bounds):
    with pytest.raises(ValueError):
        vision.tile_to_image(BOX, bounds, 100, 80)


def test_draw_boxes_uses_palette_and_preserves_original():
    image = Image.new("RGBA", (160, 80), (255, 255, 255, 255))
    before = image.tobytes()
    result = vision.draw_boxes(image, {"predicted": BOX})
    assert result.mode == "RGB" and result.size == image.size
    assert result is not image
    assert result.getpixel((20, 40)) == (243, 134, 161)  # Cookbook PINK #F386A1.
    assert result.getpixel((140, 70)) == (255, 255, 255)
    assert image.tobytes() == before


@pytest.mark.parametrize("answer", [{}, {"confidence": None}, SimpleNamespace()])
def test_box_confidence_missing_is_none(answer):
    assert vision.box_confidence(answer) is None


@pytest.mark.parametrize("confidence", [0.0, 0.25, 1.0])
def test_box_confidence_accepts_mapping_and_object(confidence):
    assert vision.box_confidence({"confidence": confidence}) == confidence
    assert vision.box_confidence(SimpleNamespace(confidence=confidence)) == confidence


@pytest.mark.parametrize("confidence", [True, math.nan, math.inf, -0.1, 1.1])
def test_box_confidence_rejects_invalid_values(confidence):
    with pytest.raises(ValueError):
        vision.box_confidence({"confidence": confidence})


def test_localization_metrics_keep_presence_and_misses_distinct():
    result = vision.localization_metrics([FULL, BOX, None, None], [BOX, None, FULL, None])
    assert is_dataclass(result)
    assert (result.n_examples, result.present, result.absent) == (4, 2, 2)
    assert result.missed == 1
    assert result.false_positives == 1
    # Present example IoUs are 1/4 and 0: their mean is 1/8.
    assert result.mean_iou == pytest.approx(0.125)


def test_localization_metrics_with_no_present_gold_has_nan_iou():
    result = vision.localization_metrics([None, None], [None, FULL])
    assert (result.present, result.absent, result.missed, result.false_positives) == (0, 2, 0, 1)
    assert math.isnan(result.mean_iou)


@pytest.mark.parametrize(
    "gold,predicted",
    [
        ([], []),
        ([FULL], []),
        ([FULL], [FULL, FULL]),
        ([None], [{"top": 0.0}]),
        ([{**BOX, "top": math.nan}], [None]),
    ],
)
def test_localization_metrics_rejects_malformed_inputs_even_for_absent_gold(gold, predicted):
    with pytest.raises(ValueError):
        vision.localization_metrics(gold, predicted)


def test_load_frames_preserves_order_and_deduplicates_identical_bytes(tmp_path, image_path):
    duplicate = tmp_path / "duplicate.png"
    duplicate.write_bytes(image_path.read_bytes())
    changed = save_image(tmp_path, name="changed.png", color="black")
    frames, assets = vision.load_frames(iter([(0, image_path), (0.25, duplicate), (1, changed)]))
    assert [frame["timestamp_seconds"] for frame in frames] == [0.0, 0.25, 1.0]
    assert all(isinstance(frame["timestamp_seconds"], float) for frame in frames)
    assert all(set(frame) == {"timestamp_seconds", "image"} for frame in frames)
    assert frames[0]["image"] == frames[1]["image"] != frames[2]["image"]
    assert len(assets) == 2
    assert assets[frames[0]["image"]] == vision.image_asset(image_path)
    assert assets[frames[2]["image"]] == vision.image_asset(changed)


@pytest.mark.parametrize(
    "timestamps",
    [[], [0, 0], [1, 0], [-0.1], [math.nan], [math.inf], [True]],
)
def test_load_frames_rejects_empty_invalid_or_nonascending_times(image_path, timestamps):
    with pytest.raises(ValueError):
        vision.load_frames((timestamp, image_path) for timestamp in timestamps)


@pytest.mark.parametrize("mode", ["synthetic", "scripted"])
def test_run_record_does_not_turn_fixture_usage_into_measurements(mode):
    result = SimpleNamespace(
        source="synthetic",
        model="fixture-model",
        usage={"input_tokens": 50, "output_tokens": 8},
        latency_seconds=0.3,
        cost_usd=0.001,
    )
    assert vision.run_record(result, mode=mode) == {
        "mode": mode,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "latency_seconds": None,
        "cost_usd": None,
    }


@pytest.mark.parametrize("mode", ["synthetic", "scripted"])
@pytest.mark.parametrize(
    "measurement", [{"measured_latency_seconds": 0.0}, {"measured_cost_usd": 0.0}]
)
def test_run_record_rejects_synthetic_measurements(mode, measurement):
    with pytest.raises(ValueError):
        vision.run_record(SimpleNamespace(source="synthetic"), mode=mode, **measurement)


@pytest.mark.parametrize("mode", ["recorded", "live"])
def test_run_record_reports_real_model_usage_and_only_explicit_measurements(mode):
    result = SimpleNamespace(
        source="recorded",
        model="jev-test-model",
        usage=SimpleNamespace(input_tokens=50, output_tokens=8),
        latency_seconds=999,
        cost_usd=999,
    )
    record = vision.run_record(result, mode=mode)
    assert record == {
        "mode": mode,
        "model": "jev-test-model",
        "input_tokens": 50,
        "output_tokens": 8,
        "latency_seconds": None,
        "cost_usd": None,
    }
    measured = vision.run_record(
        result, mode=mode, measured_latency_seconds=0.25, measured_cost_usd=0.0
    )
    assert measured == {**record, "latency_seconds": 0.25, "cost_usd": 0.0}


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": None, "output_tokens": None}])
def test_run_record_preserves_unreported_token_counts_as_none(usage):
    result = SimpleNamespace(source="recorded", model="jev-test-model", usage=usage)
    record = vision.run_record(result, mode="recorded")
    assert record["input_tokens"] is None
    assert record["output_tokens"] is None


@pytest.mark.parametrize("mode", ["synthetic", "scripted"])
def test_run_record_rejects_real_source_in_fixture_mode(mode):
    result = SimpleNamespace(source="recorded", model="jev-test-model", usage=None)
    with pytest.raises(ValueError):
        vision.run_record(result, mode=mode)


@pytest.mark.parametrize("mode", ["recorded", "live"])
@pytest.mark.parametrize(
    "source,model",
    [
        ("synthetic", "jev-test-model"),
        ("live", "jev-test-model"),
        ("recorded", "synthetic"),
        ("recorded", ""),
        ("recorded", "  "),
        ("recorded", None),
    ],
)
def test_run_record_requires_real_provenance(mode, source, model):
    with pytest.raises(ValueError):
        vision.run_record(SimpleNamespace(source=source, model=model, usage=None), mode=mode)


@pytest.mark.parametrize("value", [True, -1, 1.5])
def test_run_record_validates_reported_token_counts(value):
    result = SimpleNamespace(
        source="recorded",
        model="jev-test-model",
        usage={"input_tokens": value, "output_tokens": 8},
    )
    with pytest.raises(ValueError):
        vision.run_record(result, mode="recorded")


@pytest.mark.parametrize("value", [True, -0.1, math.nan, math.inf])
@pytest.mark.parametrize("field", ["measured_latency_seconds", "measured_cost_usd"])
def test_run_record_rejects_invalid_explicit_measurements(value, field):
    result = SimpleNamespace(source="recorded", model="jev-test-model", usage=None)
    with pytest.raises(ValueError):
        vision.run_record(result, mode="recorded", **{field: value})


def test_run_record_rejects_unknown_mode():
    with pytest.raises(ValueError):
        vision.run_record(SimpleNamespace(), mode="unknown")


# -- capture date and N on a run record; context size; the comparison table --------------------

RECORDED = SimpleNamespace(
    source="recorded",
    model="jev-1.13.0",
    usage=SimpleNamespace(input_tokens=50, output_tokens=8),
)
SIX_KEYS = {"mode", "model", "input_tokens", "output_tokens", "latency_seconds", "cost_usd"}


@pytest.mark.parametrize("mode", ["recorded", "live"])
def test_run_record_has_no_capture_date_or_n_keys_unless_they_are_given(mode):
    assert set(vision.run_record(RECORDED, mode=mode)) == SIX_KEYS
    assert set(vision.run_record(RECORDED, mode=mode, measured_latency_seconds=0.5)) == SIX_KEYS


@pytest.mark.parametrize("mode", ["recorded", "live"])
def test_run_record_adds_capture_date_and_n_when_given(mode):
    base = vision.run_record(RECORDED, mode=mode)
    both = vision.run_record(RECORDED, mode=mode, capture_date="2026-10-31", n=12)
    assert both == {**base, "capture_date": "2026-10-31", "n": 12}
    only_date = vision.run_record(RECORDED, mode=mode, capture_date="2026-10-31")
    assert only_date == {**base, "capture_date": "2026-10-31"}
    assert vision.run_record(RECORDED, mode=mode, n=1) == {**base, "n": 1}


@pytest.mark.parametrize("mode", ["synthetic", "scripted"])
def test_synthetic_and_scripted_rows_accept_n_but_refuse_a_capture_date(mode):
    synthetic = SimpleNamespace(source="synthetic")
    row = vision.run_record(synthetic, mode=mode, n=3)
    assert row == {
        "mode": mode,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "latency_seconds": None,
        "cost_usd": None,
        "n": 3,
    }
    with pytest.raises(ValueError, match="capture_date"):
        vision.run_record(synthetic, mode=mode, capture_date="2026-10-31")


@pytest.mark.parametrize(
    "bad",
    [
        "2026-02-30",
        "20261031",
        "2026-1-5",
        "2026-10-31\n",
        " 2026-10-31",
        "",
        "٢٠٢٦-١٠-٣١",
        20261031,
        datetime.date(2026, 10, 31),
    ],
)
def test_run_record_rejects_a_capture_date_that_is_not_a_real_yyyy_mm_dd_string(bad):
    with pytest.raises(ValueError, match="capture_date"):
        vision.run_record(RECORDED, mode="recorded", capture_date=bad)


@pytest.mark.parametrize("bad", [True, 0, -1, 2.0, "3"])
def test_run_record_rejects_an_n_that_is_not_a_positive_integer(bad):
    with pytest.raises(ValueError, match="n must"):
        vision.run_record(RECORDED, mode="recorded", n=bad)
    with pytest.raises(ValueError, match="n must"):
        vision.run_record(SimpleNamespace(source="synthetic"), mode="synthetic", n=bad)


def test_measured_latency_flows_from_the_ledger_into_a_recorded_row(tmp_path):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "key-with-latency": {
                    "status": "recorded",
                    "model": "jev-1.13.0",
                    "date": "2026-10-31",
                    "latency_seconds": 0.75,
                },
                "key-without-latency": {
                    "status": "recorded",
                    "model": "jev-1.13.0",
                    "date": "2026-10-31",
                },
            }
        ),
        encoding="utf-8",
    )
    found = live.load_ledger_latency(ledger, "key-with-latency")
    row = vision.run_record(
        RECORDED,
        mode="recorded",
        measured_latency_seconds=found.latency_seconds,
        capture_date=found.date,
        n=1,
    )
    assert row["latency_seconds"] == 0.75 and row["capture_date"] == "2026-10-31"
    # A call with no captured latency stays unmeasured; nothing is taken from replay timing.
    assert live.load_ledger_latency(ledger, "key-without-latency") is None
    assert vision.run_record(RECORDED, mode="recorded")["latency_seconds"] is None


CONTEXT_CASES = [
    # (state, questions, characters, utf8_bytes), each counted by hand in the comment beside it
    ("abc", {"q": Noul(instructions="Is it?")}, 10, 10),  # 3 + name 1 + instructions 6
    (["ab", "cd"], {"q": Noul(instructions="Is it?")}, 11, 11),  # 2 + 2 + 1 + 6
    ({"k": "vv"}, {"q": Noul(instructions="Is it?")}, 10, 10),  # key 1 + value 2 + 1 + 6
    ({"a": {"bb": ["c", "dd"]}}, {"q": Noul(instructions="Is it?")}, 13, 13),  # 1+2+1+2 + 7
    ({"n": 1, "b": True, "z": None}, {"q": Noul(instructions="Is it?")}, 10, 10),  # keys 3 + 7
    (
        "",
        {"c": Choice(criteria={"yes": "y d", "no": None}, instructions="i")},
        10,
        10,
    ),  # name 1 + option names 3 + 2 + description 3 + instructions 1
    ("", {"s": Score(criteria=["lo", "high"])}, 7, 7),  # name 1 + levels 2 + 4
    ("", {"q": Noul(instructions={"rule": "r1"})}, 7, 7),  # name 1 + key 4 + value 2
    ("", {"a": Noul(instructions="xx"), "b": Noul(instructions="xx")}, 6, 6),  # shared text twice
    ("é€\U0001f600", {}, 3, 9),  # 3 characters, 2 + 3 + 4 UTF-8 bytes
]


@pytest.mark.parametrize("state, questions, characters, utf8_bytes", CONTEXT_CASES)
def test_context_size_counts_characters_and_utf8_bytes_by_hand(
    state, questions, characters, utf8_bytes
):
    assert vision.context_size(state, questions) == {
        "characters": characters,
        "utf8_bytes": utf8_bytes,
    }


def test_context_size_has_exactly_two_keys_and_none_names_tokens():
    size = vision.context_size({"d": "x" * 100}, {"q": Noul(instructions="Is it?")})
    assert set(size) == {"characters", "utf8_bytes"}
    assert not any("token" in key.lower() for key in size)
    assert all(type(value) is int for value in size.values())


def test_context_size_of_one_question_plus_the_state_is_the_per_question_count():
    state = "abc"
    both = {"a": Noul(instructions="xx"), "b": Noul(instructions="yyyy")}
    whole = vision.context_size(state, both)["characters"]
    only_a = vision.context_size(state, {"a": both["a"]})["characters"]
    only_b = vision.context_size(state, {"b": both["b"]})["characters"]
    assert (only_a, only_b, whole) == (3 + 1 + 2, 3 + 1 + 4, 3 + 1 + 2 + 1 + 4)
    assert whole == only_a + only_b - vision.context_size(state, {})["characters"]


def test_context_size_rejects_a_lone_surrogate_and_a_non_mapping_of_questions():
    with pytest.raises(ValueError, match="UTF-8"):
        vision.context_size("\ud800", {"q": Noul(instructions="Is it?")})
    with pytest.raises(TypeError):
        vision.context_size("abc", [Noul(instructions="Is it?")])


def _row(result, label, **kwargs):
    return {**vision.run_record(result, **kwargs), "label": label}


def test_comparison_table_prints_not_measured_wherever_a_value_is_none():
    unreported = SimpleNamespace(source="recorded", model="jev-1.13.0", usage=None)
    rows = [
        {
            **_row(SimpleNamespace(source="synthetic"), "full", mode="synthetic", n=4),
            "characters": 120,
            "utf8_bytes": 130,
        },
        _row(
            RECORDED,
            "retrieved",
            mode="recorded",
            capture_date="2026-10-31",
            n=4,
            measured_latency_seconds=0.25,
        ),
        _row(unreported, "no usage", mode="recorded"),
    ]
    assert vision.comparison_table(rows) == "\n".join(
        [
            "label      mode       model         characters  utf8_bytes  input_tokens  "
            "output_tokens  latency_seconds  cost_usd      capture_date  n",
            "---------  ---------  ------------  ----------  ----------  ------------  "
            "-------------  ---------------  ------------  ------------  -",
            "full       synthetic  not measured  120         130         not measured  "
            "not measured   not measured     not measured  -             4",
            "retrieved  recorded   jev-1.13.0    -           -           50            "
            "8              0.25             not measured  2026-10-31    4",
            "no usage   recorded   jev-1.13.0    -           -           not measured  "
            "not measured   not measured     not measured  -             -",
        ]
    )


@pytest.mark.parametrize(
    "column", ["model", "input_tokens", "output_tokens", "latency_seconds", "cost_usd"]
)
def test_comparison_table_reads_not_measured_for_a_none_in_each_measured_column(column):
    table = vision.comparison_table([{"mode": "recorded", column: None}])
    assert table.splitlines()[-1].split("  ")[-1].strip() == "not measured"
    assert vision.comparison_table([{"mode": "recorded", column: 5}]).splitlines()[-1].endswith("5")


def test_comparison_table_shows_a_missing_key_as_a_dash_and_accepts_any_iterable():
    assert vision.comparison_table([{"mode": "synthetic"}]) == "mode\n---------\nsynthetic"
    assert vision.comparison_table(iter([{"mode": "recorded", "n": 2}, {"mode": "live"}])) == (
        "mode      n\n--------  -\nrecorded  2\nlive      -"
    )


def test_comparison_table_does_not_change_its_rows():
    rows = [{"mode": "recorded", "input_tokens": None}]
    vision.comparison_table(rows)
    assert rows == [{"mode": "recorded", "input_tokens": None}]


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"input_token": 1}],
        [{"mode": "synthetic", "model": "jev-1.13.0"}],
        [{"mode": "synthetic", "input_tokens": 5}],
        [{"mode": "scripted", "output_tokens": 0}],
        [{"mode": "scripted", "latency_seconds": 0.0}],
        [{"mode": "synthetic", "cost_usd": 0.0}],
    ],
)
def test_comparison_table_refuses_unknown_columns_and_measurements_on_fixture_rows(rows):
    with pytest.raises(ValueError):
        vision.comparison_table(rows)


def test_comparison_table_needs_mapping_rows():
    with pytest.raises(TypeError):
        vision.comparison_table([5])


TINY = {"top": 0.0, "bottom": 1e-200, "left": 0.0, "right": 1e-200}


@pytest.mark.parametrize("other", [TINY, {**TINY, "right": 2e-200}])
def test_box_iou_raises_a_value_error_when_both_areas_underflow(other):
    # Valid boxes (positive width and height) whose areas are 0.0 in floating point.
    assert vision.normalized_box(TINY) == TINY
    assert (TINY["right"] - TINY["left"]) * (TINY["bottom"] - TINY["top"]) == 0.0
    with pytest.raises(ValueError, match="union underflows"):
        vision.box_iou(TINY, other)


def test_localization_metrics_propagates_the_underflow_as_a_value_error():
    with pytest.raises(ValueError, match="union underflows"):
        vision.localization_metrics([TINY], [TINY])


def test_box_iou_with_one_underflowing_box_is_still_defined():
    assert vision.box_iou(TINY, BOX) == 0.0
    assert vision.box_iou(BOX, TINY) == 0.0


def test_generate_tiles_refuses_a_configuration_above_the_tile_cap_before_cropping(monkeypatch):
    image = Image.new("RGB", (1568, 1568))
    # The reviewed case that exhausted memory: overlap 511 on a 512 tile is ~1.1 million tiles.
    monkeypatch.setattr(
        Image.Image, "crop", lambda *a, **k: pytest.fail("cropped before checking the tile cap")
    )
    with pytest.raises(ValueError, match="would make 1,[0-9,]+ tiles, above max_tiles=256"):
        vision.generate_tiles(image, tile_size=(512, 512), overlap=511)
    with pytest.raises(ValueError, match="above max_tiles=4"):
        vision.generate_tiles(image, tile_size=(512, 512), max_tiles=4)


def test_generate_tiles_cap_is_inclusive_and_can_be_raised():
    image = Image.new("RGB", (12, 8))
    count = len(vision.generate_tiles(image, tile_size=(4, 4)))
    assert count == 6 and vision.DEFAULT_MAX_TILES >= count
    assert len(vision.generate_tiles(image, tile_size=(4, 4), max_tiles=6)) == 6
    with pytest.raises(ValueError, match="above max_tiles=5"):
        vision.generate_tiles(image, tile_size=(4, 4), max_tiles=5)
    # A deliberate larger cap permits a heavily overlapping grid that the default refuses.
    crowded = Image.new("RGB", (60, 60))
    with pytest.raises(ValueError, match="max_tiles=256"):
        vision.generate_tiles(crowded, tile_size=(4, 4), overlap=3)
    tiles = vision.generate_tiles(crowded, tile_size=(4, 4), overlap=3, max_tiles=10_000)
    assert len(tiles) == 57 * 57


@pytest.mark.parametrize("max_tiles", [0, -1, True, 2.5, "9"])
def test_generate_tiles_rejects_invalid_max_tiles(max_tiles):
    with pytest.raises(ValueError, match="max_tiles"):
        vision.generate_tiles(Image.new("RGB", (10, 7)), tile_size=(4, 3), max_tiles=max_tiles)


def test_box_confidence_docstring_matches_its_behaviour():
    doc = vision.box_confidence.__doc__ or ""
    assert "never zero or one" not in doc
    assert "0.0" in doc and "1.0" in doc
    assert vision.box_confidence({"confidence": 0.0}) == 0.0
    assert vision.box_confidence({"confidence": 1.0}) == 1.0
    assert vision.box_confidence({}) is None


# ------------------------------------------------------------------ gold Box labels and the report
#
# Every expected value below is computed by hand from these rectangles (all edges are dyadic
# fractions, so the IoUs are exact). GOLD has area 0.25.
#   SAME     identical to GOLD:                      intersection 0.25,   union 0.25  -> 1
#   HALF     the top half of GOLD:                   intersection 0.125,  union 0.25  -> 1/2
#   QUARTER  a 0.125-wide strip of GOLD:             intersection 0.0625, union 0.25  -> 1/4
#   FAR      the opposite corner, touching at a point: no intersection                -> 0
GOLD = {"top": 0.0, "bottom": 0.5, "left": 0.0, "right": 0.5}
SAME = dict(GOLD)
HALF = {"top": 0.0, "bottom": 0.25, "left": 0.0, "right": 0.5}
QUARTER = {"top": 0.0, "bottom": 0.5, "left": 0.0, "right": 0.125}
FAR = {"top": 0.5, "bottom": 1.0, "left": 0.5, "right": 1.0}
PRESENT = {"present": True, "box": GOLD}
ABSENT = {"present": False}
LOCATED_TINY = {"top": 0.0, "bottom": 1e-200, "left": 0.0, "right": 1e-200}


def test_gold_box_decodes_present_and_absent_labels():
    decoded = vision.gold_box(PRESENT)
    assert decoded == GOLD
    assert decoded is not PRESENT["box"]  # a validated copy
    assert vision.gold_box(ABSENT) is None
    assert vision.gold_box(json.loads(json.dumps(PRESENT))) == GOLD


@pytest.mark.parametrize(
    "label",
    [
        None,
        "present",
        [PRESENT],
        {},
        {"box": GOLD},
        {"present": None},
        {"present": 1},
        {"present": 0},
        {"present": "false"},
        {"present": True},
        {"present": True, "box": None},
        {"present": True, "box": [0, 0, 1, 1]},
        {"present": True, "box": {"top": 0, "bottom": 1, "left": 0}},
        {"present": True, "box": {**GOLD, "extra": 0.5}},
        {"present": True, "box": GOLD, "confidence": 0.9},
        {"present": False, "box": GOLD},
        {"present": False, "box": None},
        {"present": False, "extra": 1},
        {"present": True, "box": {**GOLD, "right": 1.5}},
        {"present": True, "box": {**GOLD, "left": -0.1}},
        {"present": True, "box": {**GOLD, "right": float("nan")}},
        {"present": True, "box": {**GOLD, "right": 0.0}},  # zero width
        {"present": True, "box": {**GOLD, "bottom": 0.0}},  # zero height
        {"present": True, "box": {**GOLD, "left": 0.5}},  # left == right
        {"present": True, "box": {**GOLD, "left": "0"}},
        {"present": True, "box": {**GOLD, "left": True}},
        {"present": True, "box": LOCATED_TINY},  # valid edges, but the area underflows to 0.0
    ],
)
def test_gold_box_rejects_malformed_labels(label):
    with pytest.raises(ValueError):
        vision.gold_box(label)


def test_gold_box_rejects_a_degenerate_gold_box_before_any_score_is_computed():
    with pytest.raises(ValueError, match="underflows to zero"):
        vision.gold_box({"present": True, "box": LOCATED_TINY})
    with pytest.raises(ValueError, match=r"example 1: .*underflows to zero"):
        vision.localization_report(
            [PRESENT, {"present": True, "box": LOCATED_TINY}],
            [("located", SAME), ("located", LOCATED_TINY)],
        )


def counted_once(report) -> None:
    """The invariant every report must keep: each example is in exactly one table cell."""
    assert sum(report.present_table.values()) == report.n_present
    assert sum(report.absent_table.values()) == report.n_absent
    assert report.n_present + report.n_absent == report.n_total
    assert len(report.ious) == report.n_total


def test_report_mixed_outcomes_by_hand():
    # Present gold (5): IoU 1, IoU 1/2, IoU 1/4, said absent, sent to review.
    # Absent gold (4): a box was returned, correct absent, correct absent, sent to review.
    gold = [PRESENT] * 5 + [ABSENT] * 4
    outcomes = [
        ("located", SAME),
        ("located", HALF),
        ("located", QUARTER),
        ("absent", None),
        ("review", None),
        ("located", SAME),
        ("absent", None),
        ("absent", None),
        ("review", None),
    ]
    report = vision.localization_report(gold, outcomes)
    counted_once(report)
    assert (report.n_total, report.n_present, report.n_absent) == (9, 5, 4)
    assert report.present_table == {"located": 3, "absent": 1, "review": 1}
    assert report.absent_table == {"located": 1, "absent": 2, "review": 1}
    assert (report.present_located, report.present_missed, report.present_review) == (3, 1, 1)
    assert (report.false_positives, report.correct_absents, report.absent_review) == (1, 2, 1)
    # (1 + 1/2 + 1/4) / 3 located present targets = 7/12; the false positive adds no IoU.
    assert report.mean_iou_located == pytest.approx(7 / 12)
    # (1 + 1/2 + 1/4 + 0 + 0) / 5 present targets = 7/20.
    assert report.mean_iou_present == pytest.approx(0.35)
    # Hits at IoU >= 0.5 are the first two present targets: 2 of 5.
    assert report.hits == 2
    assert report.hit_rate == pytest.approx(0.4)
    assert report.false_positive_rate == pytest.approx(0.25)  # 1 of 4 absent targets
    assert report.correct_absent_rate == pytest.approx(0.5)  # 2 of 4 absent targets
    assert report.ious == (1.0, 0.5, 0.25, None, None, None, None, None, None)
    assert report.denominators == {
        "mean_iou_located": 3,
        "mean_iou_present": 5,
        "hit_rate": 5,
        "false_positive_rate": 4,
        "correct_absent_rate": 4,
    }


def test_report_all_absent_has_no_iou_and_no_invented_zero():
    gold = [ABSENT, ABSENT, ABSENT]
    outcomes = [("absent", None), ("located", FAR), ("review", None)]
    report = vision.localization_report(gold, outcomes)
    counted_once(report)
    assert (report.n_total, report.n_present, report.n_absent) == (3, 0, 3)
    assert report.absent_table == {"located": 1, "absent": 1, "review": 1}
    assert report.present_table == {"located": 0, "absent": 0, "review": 0}
    assert math.isnan(report.mean_iou_located)
    assert math.isnan(report.mean_iou_present)
    assert math.isnan(report.hit_rate)
    assert report.hits == 0
    assert report.false_positive_rate == pytest.approx(1 / 3)
    assert report.correct_absent_rate == pytest.approx(1 / 3)
    text = str(report)
    assert "3 examples (0 present + 3 absent)" in text
    assert "mean IoU over located present targets: n/a (denominator 0" in text
    assert "hit rate at IoU >= 0.5: n/a (denominator 0" in text
    assert "false positive rate: 1/3 = 0.3333 (denominator 3: all absent targets)" in text


def test_report_all_absent_and_all_correct():
    report = vision.localization_report([ABSENT, ABSENT], [("absent", None)] * 2)
    assert (report.correct_absents, report.false_positives) == (2, 0)
    assert report.correct_absent_rate == 1.0
    assert report.false_positive_rate == 0.0


def test_report_all_review_keeps_every_example_in_the_denominator():
    gold = [PRESENT, ABSENT, PRESENT]
    report = vision.localization_report(gold, [("review", None)] * 3)
    counted_once(report)
    assert report.n_total == 3
    assert report.present_table == {"located": 0, "absent": 0, "review": 2}
    assert report.absent_table == {"located": 0, "absent": 0, "review": 1}
    # No located target: the located mean has nothing to average, but the all-present mean is
    # 0/2, not undefined: both reviewed present targets are in its denominator at 0.
    assert math.isnan(report.mean_iou_located)
    assert report.mean_iou_present == 0.0
    assert report.hit_rate == 0.0
    assert report.hits == 0
    # A review is not an absent prediction: nothing counts as a correct absent or a miss.
    assert (report.correct_absents, report.false_positives, report.present_missed) == (0, 0, 0)
    assert report.correct_absent_rate == 0.0
    assert report.false_positive_rate == 0.0


def test_a_reviewed_present_target_changes_the_denominator_instead_of_vanishing():
    gold = [PRESENT, PRESENT]
    resolved = vision.localization_report(gold, [("located", SAME), ("located", HALF)])
    reviewed = vision.localization_report(gold, [("located", SAME), ("review", None)])
    for report in (resolved, reviewed):
        counted_once(report)
        assert (report.n_total, report.n_present) == (2, 2)
    assert resolved.mean_iou_located == 0.75  # (1 + 1/2) / 2
    assert resolved.mean_iou_present == 0.75
    assert resolved.denominators["mean_iou_located"] == 2
    # The reviewed target is not located (denominator 1) but still present (denominator 2).
    assert reviewed.mean_iou_located == 1.0  # 1 / 1
    assert reviewed.mean_iou_present == 0.5  # (1 + 0) / 2
    assert reviewed.denominators["mean_iou_located"] == 1
    assert reviewed.denominators["mean_iou_present"] == 2
    assert reviewed.hit_rate == 0.5  # 1 hit of 2 present targets
    text = str(reviewed)
    assert "1.0000 (denominator 1: located present targets)" in text
    assert "0.5000 (denominator 2: all present targets)" in text
    assert "sent to review 1" in text


def test_box_returned_for_an_absent_target_is_a_false_positive_never_an_iou():
    # The box is identical to a rectangle that would score IoU 1 on a present target.
    report = vision.localization_report([ABSENT], [("located", SAME)])
    counted_once(report)
    assert report.absent_table == {"located": 1, "absent": 0, "review": 0}
    assert report.false_positives == 1
    assert report.false_positive_rate == 1.0
    assert report.correct_absent_rate == 0.0
    assert report.ious == (None,)
    assert math.isnan(report.mean_iou_present)
    # Mixed with a present target, the false positive leaves the IoU means untouched.
    both = vision.localization_report([PRESENT, ABSENT], [("located", HALF), ("located", SAME)])
    assert both.mean_iou_located == 0.5
    assert both.mean_iou_present == 0.5
    assert both.hit_rate == 1.0


def test_a_present_target_called_absent_is_a_miss_and_not_a_correct_absent():
    report = vision.localization_report([PRESENT], [("absent", None)])
    assert report.present_table == {"located": 0, "absent": 1, "review": 0}
    assert report.correct_absents == 0
    assert report.mean_iou_present == 0.0
    assert math.isnan(report.mean_iou_located)


def test_report_uses_each_examples_own_gold_box():
    other = {"present": True, "box": {"top": 0.25, "bottom": 0.75, "left": 0.25, "right": 0.75}}
    # GOLD against `other`: intersection 0.25 * 0.25 = 1/16, union 1/4 + 1/4 - 1/16 = 7/16.
    report = vision.localization_report([other], [("located", GOLD)])
    assert report.ious[0] == pytest.approx(1 / 7)
    assert report.hits == 0


def test_report_hit_threshold_is_inclusive_and_configurable():
    gold = [PRESENT] * 3
    outcomes = [("located", HALF), ("located", QUARTER), ("located", FAR)]
    default = vision.localization_report(gold, outcomes)
    assert default.iou_threshold == 0.5
    assert default.hits == 1  # IoU exactly 1/2 counts
    strict = vision.localization_report(gold, outcomes, iou_threshold=0.6)
    assert (strict.hits, strict.hit_rate) == (0, 0.0)
    loose = vision.localization_report(gold, outcomes, iou_threshold=0.25)
    assert (loose.hits, loose.hit_rate) == (2, pytest.approx(2 / 3))  # IoU 1/2 and 1/4
    assert vision.localization_report(gold, outcomes, iou_threshold=1).hits == 0
    assert "hit rate at IoU >= 0.25" in str(loose)
    # FAR touches GOLD at a corner: IoU 0, and its zero is in the mean over 3 located targets.
    assert default.mean_iou_located == pytest.approx((0.5 + 0.25 + 0.0) / 3)


def test_report_prints_every_denominator_for_the_documented_example():
    text = str(
        vision.localization_report(
            [PRESENT] * 4 + [ABSENT] * 3,
            [
                ("located", SAME),
                ("located", HALF),
                ("review", None),
                ("absent", None),
                ("located", SAME),
                ("absent", None),
                ("review", None),
            ],
        )
    )
    assert text.splitlines() == [
        "Localization report: 7 examples (4 present + 3 absent), each counted once",
        "Present targets (n = 4): box returned 2, said absent (missed) 1, sent to review 1",
        "  mean IoU over located present targets: 0.7500 (denominator 2: located present targets)",
        "  mean IoU over all present targets, missed and review counted as 0: "
        "0.3750 (denominator 4: all present targets)",
        "  hit rate at IoU >= 0.5: 2/4 = 0.5000 (denominator 4: all present targets)",
        "Absent targets (n = 3): box returned (false positive) 1, correct absent 1, "
        "sent to review 1",
        "  false positive rate: 1/3 = 0.3333 (denominator 3: all absent targets)",
        "  correct absent rate: 1/3 = 0.3333 (denominator 3: all absent targets)",
    ]


def test_the_documented_localization_example_runs_and_prints_what_the_docs_show():
    text = (Path(__file__).resolve().parent.parent / "docs" / "vision.md").read_text("utf-8")
    start = text.index("from jev_cookbook.vision import localization_report")
    code = text[start : text.index("```", start)]
    printed = text[text.index("```text\n", start) + len("```text\n") :]
    printed = printed[: printed.index("```")]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(code, "docs/vision.md", "exec"), {})
    assert out.getvalue() == printed


_DOCS = Path(__file__).resolve().parent.parent / "docs"


def _section(text: str, heading: str, level: str = "###") -> str:
    start = text.index(f"{level} {heading}\n")
    following = re.search(rf"\n#{{1,{len(level)}}} ", text[start + 1 :])
    return text[start : start + 1 + following.start()] if following else text[start:]


def _box_label_objects(value):
    """Every dict under `value` (itself included) that has a `present` key."""
    found = []
    if isinstance(value, dict):
        if "present" in value:
            found.append(value)
        for child in value.values():
            found.extend(_box_label_objects(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_box_label_objects(child))
    return found


def _contains_tile_key(value) -> bool:
    if isinstance(value, dict):
        return any("tile" in str(key).lower() or _contains_tile_key(v) for key, v in value.items())
    if isinstance(value, list):
        return any(_contains_tile_key(v) for v in value)
    return False


def test_every_label_example_in_the_box_labels_docs_is_valid_and_consistent():
    """Each JSON example in docs/fixtures.md "Box labels" must decode with gold_box, and no
    example stores a tile choice beside the Box label (the gold lives once, full-image)."""
    section = _section((_DOCS / "fixtures.md").read_text("utf-8"), "Box labels")
    lines = [
        line
        for block in section.split("```json\n")[1:]
        for line in block[: block.index("```")].splitlines()
        if line.strip()
    ]
    labels = [json.loads(line)["label"] for line in lines]
    nested = [label for label in labels if "present" not in label]
    assert len(labels) >= 3 and nested, "the section must show flat and nested examples"
    for label in labels:
        boxes = _box_label_objects(label)
        assert boxes, label
        for box_label in boxes:
            vision.gold_box(box_label)  # raises on a self-contradictory example
        assert not _contains_tile_key(label), f"a tile choice stored with the gold: {label}"
    flat = " ".join(section.split())
    assert '"tile":' not in flat, "an inline example stores a tile choice beside the gold"
    assert "Store the gold box once, for the whole image" in flat
    assert "does not store a tile choice" in flat
    assert "must cover every split" in flat


def test_the_docs_say_a_tiled_recipe_reports_per_image_not_per_tile():
    vision_md = " ".join(
        _section((_DOCS / "vision.md").read_text("utf-8"), "Tiled and hierarchical recipes").split()
    )
    for required in (
        "one example is one image, not one tile",
        "The headline report is per image",
        "after `tile_to_image`",
        '"no match" on an image whose gold is present is `("absent", None)`',
        '`("review", None)`',
        "stage diagnostic",
        "a target a tile edge cuts",
    ):
        assert required in vision_md, required
    evaluation = " ".join((_DOCS / "evaluation.md").read_text("utf-8").split())
    assert "In a tiled or hierarchical recipe the headline report is per image" in evaluation
    assert "vision.md#tiled-and-hierarchical-recipes" in evaluation
    assert "vision.md#tiled-and-hierarchical-recipes" in " ".join(
        (_DOCS / "fixtures.md").read_text("utf-8").split()
    )


@pytest.mark.parametrize(
    ("gold", "outcomes", "match"),
    [
        ([], [], "nonempty"),
        ([PRESENT], [], "same length"),
        ([PRESENT], [("located", SAME)] * 2, "same length"),
        ([{"present": "yes"}], [("absent", None)], "example 0: .*'present'"),
        ([PRESENT, {"present": False, "box": GOLD}], [("absent", None)] * 2, "example 1"),
        ([PRESENT], ["located"], "pair"),
        ([PRESENT], [("located",)], "pair"),
        ([PRESENT], [None], "pair"),
        ([PRESENT], [("maybe", None)], "outcome kind"),
        ([PRESENT], [("LOCATED", SAME)], "outcome kind"),
        ([PRESENT], [("located", None)], "example 0"),
        ([ABSENT], [("located", None)], "example 0"),
        ([PRESENT], [("located", {**SAME, "right": 2.0})], "example 0"),
        ([ABSENT], [("located", {**SAME, "right": 2.0})], "example 0"),  # absent gold still checked
        ([PRESENT], [("absent", SAME)], "must carry None"),
        ([ABSENT], [("review", SAME)], "must carry None"),
    ],
)
def test_report_rejects_malformed_inputs(gold, outcomes, match):
    with pytest.raises(ValueError, match=match):
        vision.localization_report(gold, outcomes)


@pytest.mark.parametrize(
    "threshold", [0, -0.1, 1.01, float("nan"), float("inf"), True, "0.5", None]
)
def test_report_rejects_a_bad_threshold(threshold):
    with pytest.raises(ValueError, match="iou_threshold"):
        vision.localization_report([PRESENT], [("located", SAME)], iou_threshold=threshold)


def test_report_accepts_lists_a_box_answer_object_and_any_iterable():
    answer = SimpleNamespace(box=HALF, confidence=0.9)
    report = vision.localization_report(
        iter([PRESENT, ABSENT]), iter([["located", answer], ["absent", None]])
    )
    assert report.ious == (0.5, None)
    assert report.correct_absents == 1


def test_a_tiny_returned_box_on_a_present_target_scores_zero_without_raising():
    report = vision.localization_report([PRESENT], [("located", LOCATED_TINY)])
    assert report.ious == (0.0,)
    assert report.mean_iou_located == 0.0


def test_report_is_a_frozen_dataclass_and_localization_metrics_remains():
    report = vision.localization_report([ABSENT], [("absent", None)])
    assert is_dataclass(report)
    with pytest.raises(AttributeError):
        report.n_total = 5
    assert "localization_report" in vision.__all__
    assert "gold_box" in vision.__all__
    assert "localization_report" in (vision.localization_metrics.__doc__ or "")
    assert vision.localization_metrics([GOLD, None], [GOLD, None]).mean_iou == 1.0


# ---------------------------------------------------------------------------------------------
# Image preparation, the tile inverse, multi-level mapping and the 280 px minimum (#310).
# Every expectation below is worked out by hand in the comment beside it.
# ---------------------------------------------------------------------------------------------

GRAY = (128, 128, 128)


def nb(left, top, right, bottom):
    return {"top": top, "bottom": bottom, "left": left, "right": right}


# image_to_tile ------------------------------------------------------------------------------

# A 1000 x 800 image and the tile (200, 100)-(700, 500): 500 x 400 pixels.
WHOLE, TILE = (1000, 800), (200, 100, 700, 500)


def test_image_to_tile_maps_a_box_inside_the_tile_by_hand():
    # x 0.25..0.5 is pixels 250..500 and y 0.25..0.5 is pixels 200..400. In the tile (origin
    # 200, 100; 500 x 400) that is x 50..300 -> 0.1..0.6 and y 100..300 -> 0.25..0.75.
    box = nb(0.25, 0.25, 0.5, 0.5)
    assert vision.image_to_tile(box, TILE, *WHOLE) == nb(0.1, 0.25, 0.6, 0.75)


def test_image_to_tile_clips_a_box_the_tile_edge_cuts():
    # x 0.125..0.5 is pixels 125..500, y 0.0625..0.5 is pixels 50..400. The tile starts at x=200
    # and y=100, so the visible part is x 200..500 -> 0..0.6 and y 100..400 -> 0..0.75.
    box = nb(0.125, 0.0625, 0.5, 0.5)
    assert vision.image_to_tile(box, TILE, *WHOLE) == nb(0.0, 0.0, 0.6, 0.75)
    # The whole box is 375 x 350 = 131,250 px and the visible 300 x 300 = 90,000 px of it is 24/35.
    transform = vision.ImageTransform.crop(TILE, *WHOLE)
    assert transform.visible_fraction(box) == 90_000 / 131_250


def test_image_to_tile_clips_a_box_covering_the_tile_to_the_tile():
    assert vision.image_to_tile(FULL, TILE, *WHOLE) == FULL
    # A box larger than the tile on every side is clipped to all four tile edges.
    assert vision.image_to_tile(nb(0.125, 0.0625, 0.875, 0.875), TILE, *WHOLE) == FULL


def test_image_to_tile_is_none_for_a_box_that_misses_the_tile():
    # The tile covers x 0.2..0.7 and y 0.125..0.625.
    assert vision.image_to_tile(nb(0.75, 0.25, 1.0, 0.5), TILE, *WHOLE) is None  # right of it
    assert vision.image_to_tile(nb(0.25, 0.75, 0.5, 1.0), TILE, *WHOLE) is None  # below it
    assert vision.image_to_tile(nb(0.0, 0.25, 0.125, 0.5), TILE, *WHOLE) is None  # left of it
    assert vision.image_to_tile(nb(0.25, 0.0, 0.5, 0.0625), TILE, *WHOLE) is None  # above it


def test_image_to_tile_is_none_for_a_box_that_only_touches_the_tile_edge():
    # 0.2 is not exactly 1/5 in binary (it is a hair above), so without reading it as pixel 200
    # this box would overlap the tile by 1e-17 and return a sliver instead of None.
    assert Fraction(0.2) > Fraction(1, 5)
    assert vision.image_to_tile(nb(0.0, 0.25, 0.2, 0.5), TILE, *WHOLE) is None
    assert vision.image_to_tile(nb(0.7, 0.25, 0.9, 0.5), TILE, *WHOLE) is None
    assert vision.image_to_tile(nb(0.25, 0.0, 0.5, 0.125), TILE, *WHOLE) is None
    # One pixel of overlap is a real overlap: x 0.201 is pixel 201, one pixel inside the tile.
    one_pixel = vision.image_to_tile(nb(0.0, 0.25, 0.201, 0.5), TILE, *WHOLE)
    assert one_pixel == nb(0.0, 0.25, 1 / 500, 0.75)


def test_image_to_tile_inverts_tile_to_image_for_every_generated_tile():
    size = (1568, 1024)
    box = nb(0.25, 0.125, 0.75, 0.5)
    for tile in vision.generate_tiles(Image.new("RGB", size), tile_size=(512, 512), overlap=64):
        local = vision.image_to_tile(box, tile.bounds, *size)
        if local is None:
            continue
        back = vision.tile_to_image(local, tile.bounds, *size)
        visible = vision.ImageTransform.crop(tile.bounds, *size).visible_fraction(box)
        if visible == 1.0:
            assert back == pytest.approx(box, abs=1e-12)
        else:  # a cut box maps back to its visible part, which is inside the original box
            assert 0.0 < visible < 1.0
            assert back["left"] >= box["left"] - 1e-12 and back["right"] <= box["right"] + 1e-12
            assert back["top"] >= box["top"] - 1e-12 and back["bottom"] <= box["bottom"] + 1e-12


def test_image_to_tile_matches_tile_to_image_on_a_hand_computed_tile():
    # Tile (20,10)-(60,50) of 100 x 80, from test_tile_to_image_uses_exact_pixel_bounds:
    # the tile-local box BOX maps to x 0.25..0.45, y 0.25..0.5 of the image, and back.
    whole = nb(0.25, 0.25, 0.45, 0.5)
    local = vision.image_to_tile(whole, (20, 10, 60, 50), 100, 80)
    assert local == pytest.approx(BOX)
    assert vision.tile_to_image(local, (20, 10, 60, 50), 100, 80) == pytest.approx(whole)


@pytest.mark.parametrize(
    "bounds", [(0, 0, 0, 5), (-1, 0, 5, 5), (0, 0, 101, 5), (0, 0, 5, 81), (0, 0, 1.5, 5)]
)
def test_image_to_tile_rejects_invalid_pixel_bounds(bounds):
    with pytest.raises(ValueError):
        vision.image_to_tile(BOX, bounds, 100, 80)


def test_image_to_tile_rejects_an_invalid_box_and_an_absent_one():
    for bad in (None, {"left": 0.5, "right": 0.5, "top": 0, "bottom": 1}):
        with pytest.raises(ValueError):
            vision.image_to_tile(bad, TILE, *WHOLE)


# ImageTransform.crop, validation and the float edge ----------------------------------------


def test_crop_transform_records_the_windows_by_hand():
    transform = vision.ImageTransform.crop((512, 0, 1024, 512), 1568, 1024)
    assert transform.original_size == (1568, 1024) and transform.derived_size == (512, 512)
    # x 512/1568 = 16/49, 1024/1568 = 32/49; y 0 and 512/1024 = 1/2.
    assert transform.original_window == (
        Fraction(16, 49),
        Fraction(0),
        Fraction(32, 49),
        Fraction(1, 2),
    )
    assert transform.derived_window == (Fraction(0), Fraction(0), Fraction(1), Fraction(1))
    assert transform.to_original(FULL) == nb(512 / 1568, 0.0, 1024 / 1568, 0.5)
    assert transform.to_derived(nb(512 / 1568, 0.0, 1024 / 1568, 0.5)) == FULL


def test_the_transform_constructor_checks_sizes_and_windows():
    unit = (Fraction(0), Fraction(0), Fraction(1), Fraction(1))
    assert vision.ImageTransform((4, 4), (4, 4), unit, unit).to_original(BOX) == BOX
    bad_windows = [
        (0.0, 0.0, 1.0, 1.0),  # floats are not exact
        (Fraction(0), Fraction(0), Fraction(1)),  # three edges
        (Fraction(1, 2), Fraction(0), Fraction(1, 2), Fraction(1)),  # zero width
        (Fraction(0), Fraction(0), Fraction(3, 2), Fraction(1)),  # outside the image
        (Fraction(-1, 2), Fraction(0), Fraction(1), Fraction(1)),
        [Fraction(0), Fraction(0), Fraction(1), Fraction(1)],  # a list, not a tuple
    ]
    for window in bad_windows:
        with pytest.raises(ValueError, match="original_window"):
            vision.ImageTransform((4, 4), (4, 4), window, unit)
        with pytest.raises(ValueError, match="derived_window"):
            vision.ImageTransform((4, 4), (4, 4), unit, window)
    for size in [(0, 4), (4, -1), (True, 4), (4, 2.5), (4,), 4]:
        with pytest.raises(ValueError):
            vision.ImageTransform(size, (4, 4), unit, unit)
        with pytest.raises(ValueError):
            vision.ImageTransform((4, 4), size, unit, unit)


def test_a_mapped_box_too_small_for_a_float_rectangle_raises_instead_of_collapsing():
    # The right half of a square. A derived box one float step wide at the far edge maps to
    # 0.5 + (1 - 2**-53) / 2 = 1 - 2**-54 on the left edge, which rounds to 1.0, the right edge.
    transform = vision.ImageTransform.crop((500, 0, 1000, 1000), 1000, 1000)
    sliver = nb(math.nextafter(1.0, 0.0), 0.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="too small"):
        transform.to_original(sliver)


def test_transforms_are_immutable_and_compare_by_value():
    first = vision.ImageTransform.crop(TILE, *WHOLE)
    assert first == vision.ImageTransform.crop(TILE, *WHOLE)
    assert first != vision.ImageTransform.crop((0, 0, 500, 400), *WHOLE)
    with pytest.raises(AttributeError):
        first.original_size = (1, 1)


# prepare_image --------------------------------------------------------------------------------


def window_of(transform):
    return tuple(transform.derived_window)


def test_prepare_image_pads_one_axis_and_keeps_every_pixel():
    image = coordinate_image(300, 200)  # pixel (x, y) = (x, y, (x + y) % 256)
    prepared, transform = vision.prepare_image(image, min_side=256)
    # Height 200 -> 256: 56 rows of padding, 28 above and 28 below. Width 300 is untouched.
    assert prepared.size == (300, 256) and prepared.mode == "RGB"
    assert transform.original_size == (300, 200) and transform.derived_size == (300, 256)
    assert window_of(transform) == (Fraction(0), Fraction(7, 64), Fraction(1), Fraction(57, 64))
    assert prepared.getpixel((10, 27)) == GRAY and prepared.getpixel((10, 228)) == GRAY
    assert prepared.getpixel((10, 28)) == (10, 0, 10)  # the original's first row
    assert prepared.getpixel((200, 227)) == (200, 199, 143)  # its last row; (200 + 199) % 256 = 143
    assert prepared.crop((0, 28, 300, 228)).tobytes() == image.tobytes()


def test_prepare_image_transform_maps_a_prepared_box_back_to_the_original_exactly():
    _, transform = vision.prepare_image(coordinate_image(300, 200), min_side=256)
    # Rows 28..228 of 256 are the picture: 28/256 = 0.109375 and 228/256 = 0.890625.
    assert transform.to_original(nb(0.0, 0.109375, 1.0, 0.890625)) == FULL
    # Prepared y 0.5 (row 128) is 100 rows into the 200 row picture; 0.75 (row 192) is row 164.
    assert transform.to_original(nb(0.25, 0.5, 0.75, 0.75)) == nb(0.25, 0.5, 0.75, 0.82)
    # And forward: original y 0.5 (row 100) is prepared row 128 of 256.
    assert transform.to_derived(nb(0.25, 0.5, 0.75, 0.82)) == nb(0.25, 0.5, 0.75, 0.75)


def test_prepare_image_clips_a_box_that_reaches_into_the_padding():
    _, transform = vision.prepare_image(coordinate_image(300, 200), min_side=256)
    # A box over rows 0..128 of the prepared image shows picture rows 28..128 -> 0..0.5.
    assert transform.to_original(nb(0.0, 0.0, 1.0, 0.5)) == nb(0.0, 0.0, 1.0, 0.5)
    # A box wholly inside the padding (rows 0..16) is nothing in the original.
    assert transform.to_original(nb(0.0, 0.0, 1.0, 0.0625)) is None
    # One that only touches the picture (rows 0..28) is nothing as well.
    assert transform.to_original(nb(0.0, 0.0, 1.0, 0.109375)) is None


def test_a_box_cropped_from_the_prepared_image_holds_the_same_pixels_as_in_the_original():
    image = coordinate_image(300, 200)
    prepared, transform = vision.prepare_image(image, min_side=256)
    box = nb(0.25, 0.25, 0.75, 0.75)  # original pixels x 75..225, y 50..150
    mapped = transform.to_derived(box)
    assert mapped == nb(0.25, 78 / 256, 0.75, 178 / 256)  # prepared y = 28 + 50 .. 28 + 150
    assert vision.crop_bounds(mapped, 300, 256) == (75, 78, 225, 178)
    assert vision.crop_box(prepared, mapped).tobytes() == vision.crop_box(image, box).tobytes()


def test_prepare_image_with_the_api_limits_pads_a_short_image_to_280():
    image = coordinate_image(300, 200)
    prepared, transform = vision.prepare_image(image)
    assert prepared.size == (300, 280)  # 40 rows of padding above and below
    assert prepared.getpixel((0, 39)) == GRAY and prepared.getpixel((0, 40)) == (0, 0, 0)
    assert prepared.getpixel((0, 239)) == (0, 199, 199) and prepared.getpixel((0, 240)) == GRAY
    assert window_of(transform) == (Fraction(0), Fraction(1, 7), Fraction(1), Fraction(6, 7))


def test_prepare_image_pads_both_axes_and_puts_the_odd_pixel_right_and_below():
    prepared, transform = vision.prepare_image(Image.new("RGB", (200, 100), (255, 0, 0)))
    # 200 -> 280 is 80 columns (40 each side); 100 -> 280 is 180 rows (90 each side).
    assert prepared.size == (280, 280)
    assert window_of(transform) == (
        Fraction(1, 7),
        Fraction(9, 28),
        Fraction(6, 7),
        Fraction(19, 28),
    )
    assert prepared.getpixel((39, 100)) == GRAY and prepared.getpixel((40, 100)) == (255, 0, 0)
    assert prepared.getpixel((239, 100)) == (255, 0, 0) and prepared.getpixel((240, 100)) == GRAY
    assert prepared.getpixel((100, 89)) == GRAY and prepared.getpixel((100, 90)) == (255, 0, 0)
    assert prepared.getpixel((100, 189)) == (255, 0, 0) and prepared.getpixel((100, 190)) == GRAY
    # Odd padding: 201 -> 280 is 79 columns, 39 on the left and 40 on the right.
    odd, odd_transform = vision.prepare_image(Image.new("RGB", (201, 100), (255, 0, 0)))
    assert odd.getpixel((38, 100)) == GRAY and odd.getpixel((39, 100)) == (255, 0, 0)
    assert odd.getpixel((239, 100)) == (255, 0, 0) and odd.getpixel((240, 100)) == GRAY
    assert odd_transform.derived_window[0] == Fraction(39, 280)
    assert odd_transform.derived_window[2] == Fraction(240, 280)


def test_prepare_image_leaves_an_image_that_fits_alone():
    image = coordinate_image(400, 300)
    prepared, transform = vision.prepare_image(image)
    assert prepared is not image and prepared.tobytes() == image.tobytes()
    unit = (Fraction(0), Fraction(0), Fraction(1), Fraction(1))
    assert transform == vision.ImageTransform((400, 300), (400, 300), unit, unit)
    assert transform.to_original(BOX) == BOX and transform.to_derived(BOX) == BOX
    # The limits themselves fit: 280 x 280 and 1568 x 1568 are not changed.
    for side in (280, 1568):
        assert vision.prepare_image(Image.new("RGB", (side, side)))[0].size == (side, side)


def test_prepare_image_scales_a_large_image_down_by_the_exact_ratio():
    image = Image.new("RGB", (1601, 1000), (0, 0, 255))
    prepared, transform = vision.prepare_image(image)
    # 1601 -> 1568; 1000 * 1568 / 1601 = 979.39 -> 979. Nothing is under 280, so no padding.
    assert prepared.size == (1568, 979)
    assert transform.derived_window == (Fraction(0), Fraction(0), Fraction(1), Fraction(1))
    # A tall image: 1000 x 3136 -> 500 x 1568 (a ratio of exactly one half).
    assert vision.prepare_image(Image.new("RGB", (1000, 3136)))[0].size == (500, 1568)
    # A square at 3136 -> 1568.
    assert vision.prepare_image(Image.new("RGB", (3136, 3136)))[0].size == (1568, 1568)


def test_prepare_image_rounds_scaled_sizes_half_up():
    # max_side 5: 10 x 3 scales by 1/2 to 5 x 1.5, and 1.5 rounds up to 2.
    assert vision.prepare_image(Image.new("RGB", (10, 3)), min_side=1, max_side=5)[0].size == (5, 2)
    # 7 x 5 with max_side 4 scales by 4/7: 4 x 2.857 -> 4 x 3.
    assert vision.prepare_image(Image.new("RGB", (7, 5)), min_side=1, max_side=4)[0].size == (4, 3)
    # A side that would round to 0 stays 1 pixel: 100 x 1 with max_side 10 -> 10 x 0.1 -> 10 x 1.
    assert vision.prepare_image(Image.new("RGB", (100, 1)), min_side=1, max_side=10)[0].size == (
        10,
        1,
    )


def test_prepare_image_scales_down_then_pads_an_extreme_aspect_ratio():
    prepared, transform = vision.prepare_image(Image.new("RGB", (4000, 100), (0, 128, 0)))
    # 4000 -> 1568 (x0.392); 100 * 1568 / 4000 = 39.2 -> 39 rows, padded to 280: 241 -> 120 above.
    assert prepared.size == (1568, 280)
    assert window_of(transform) == (
        Fraction(0),
        Fraction(120, 280),
        Fraction(1),
        Fraction(159, 280),
    )
    assert prepared.getpixel((800, 119)) == GRAY and prepared.getpixel((800, 120)) == (0, 128, 0)
    assert prepared.getpixel((800, 158)) == (0, 128, 0) and prepared.getpixel((800, 159)) == GRAY
    # The picture's middle row (original y 0.5, 19.5 of its 39 rows) is prepared row 120 + 19.5
    # = 139.5 of 280; its bottom edge is row 159.
    assert transform.to_derived(nb(0.0, 0.5, 0.25, 1.0)) == nb(0.0, 139.5 / 280, 0.25, 159 / 280)


def test_prepare_image_scale_up_is_opt_in_and_keeps_the_aspect_ratio():
    image = Image.new("RGB", (200, 100), (255, 0, 0))
    # Default: padded, not scaled (the picture stays 200 x 100).
    assert vision.prepare_image(image)[0].size == (280, 280)
    # upscale: the short side 100 -> 280, so 200 -> 560. Nothing to pad.
    prepared, transform = vision.prepare_image(image, upscale=True)
    assert prepared.size == (560, 280)
    assert transform.derived_window == (Fraction(0), Fraction(0), Fraction(1), Fraction(1))
    # 101 x 100 -> 283 x 280 (101 * 2.8 = 282.8).
    assert vision.prepare_image(Image.new("RGB", (101, 100)), upscale=True)[0].size == (283, 280)
    # 100 x 200 -> 280 x 560 (portrait).
    assert vision.prepare_image(Image.new("RGB", (100, 200)), upscale=True)[0].size == (280, 560)


def test_prepare_image_scale_up_stops_at_max_side_and_pads_the_rest():
    # 1568 x 100 cannot grow at all (its long side is already 1568): padded to 1568 x 280,
    # picture rows 90..190.
    prepared, transform = vision.prepare_image(Image.new("RGB", (1568, 100)), upscale=True)
    assert prepared.size == (1568, 280)
    assert transform.derived_window[1] == Fraction(90, 280)
    # 800 x 100 grows by 1568 / 800 = 1.96 (not 2.8): 1568 x 196, padded to 280 rows -> 42 above.
    prepared, transform = vision.prepare_image(Image.new("RGB", (800, 100)), upscale=True)
    assert prepared.size == (1568, 280)
    assert transform.derived_window[1] == Fraction(42, 280)
    assert transform.derived_window[3] == Fraction(238, 280)
    # An oversized image is scaled down and never up, whatever upscale says.
    assert vision.prepare_image(Image.new("RGB", (4000, 100)), upscale=True)[0].size == (1568, 280)


def test_prepare_image_resized_content_lands_where_the_transform_says():
    image = Image.new("RGB", (2000, 1000), (255, 255, 255))
    image.paste((0, 0, 255), (500, 250, 1000, 750))  # blue square at x 0.25..0.5, y 0.25..0.75
    prepared, transform = vision.prepare_image(image)
    assert prepared.size == (1568, 784)  # exactly x0.784
    box = nb(0.25, 0.25, 0.5, 0.75)
    # In the prepared image that is x 392..784, y 196..588.
    assert transform.to_derived(box) == nb(0.25, 0.25, 0.5, 0.75)
    assert vision.crop_bounds(transform.to_derived(box), 1568, 784) == (392, 196, 784, 588)
    assert prepared.getpixel((392 + 6, 196 + 6)) == (0, 0, 255)
    assert prepared.getpixel((784 - 6, 588 - 6)) == (0, 0, 255)
    assert prepared.getpixel((392 - 6, 300)) == (255, 255, 255)
    assert prepared.getpixel((600, 588 + 6)) == (255, 255, 255)


SIZES = [
    (300, 200),  # pad one axis
    (200, 300),
    (200, 100),  # pad both
    (279, 1000),
    (1000, 279),
    (4000, 100),  # scale down, then pad
    (100, 4000),
    (3136, 2048),  # scale down only
    (1601, 1000),
    (2000, 2000),
    (400, 300),  # nothing to do
]


@pytest.mark.parametrize("upscale", [False, True])
@pytest.mark.parametrize("size", SIZES)
def test_prepared_images_meet_the_api_limits_for_every_aspect_ratio(size, upscale):
    prepared, _ = vision.prepare_image(Image.new("RGB", size, (10, 20, 30)), upscale=upscale)
    width, height = prepared.size
    assert 280 <= width <= 1568 and 280 <= height <= 1568
    buffer = io.BytesIO()
    prepared.save(buffer, format="PNG")
    asset = {
        "type": "image",
        "format": "png",
        "data_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }
    assert vision.validate_image_asset(asset) == buffer.getvalue()


@pytest.mark.parametrize("upscale", [False, True])
@pytest.mark.parametrize("size", SIZES)
def test_boxes_round_trip_through_prepare_image_at_every_aspect_ratio(size, upscale):
    _, transform = vision.prepare_image(Image.new("RGB", size), upscale=upscale)
    for box in (
        FULL,
        BOX,
        nb(0.0, 0.0, 0.125, 0.125),
        nb(0.875, 0.875, 1.0, 1.0),
        nb(0.1, 0.2, 0.3, 0.4),
    ):
        derived = transform.to_derived(box)
        assert derived is not None
        assert transform.to_original(derived) == pytest.approx(box, abs=1e-12)
        # The picture's box sits inside the content window of the prepared image.
        window = transform.derived_window
        assert (
            float(window[0]) - 1e-12
            <= derived["left"]
            < derived["right"]
            <= float(window[2]) + 1e-12
        )
        assert (
            float(window[1]) - 1e-12
            <= derived["top"]
            < derived["bottom"]
            <= float(window[3]) + 1e-12
        )
        # And the other way: a prepared box inside the content maps to an original box that
        # maps forward to it.
        assert transform.to_derived(transform.to_original(derived)) == pytest.approx(
            derived, abs=1e-12
        )


def test_prepare_image_does_not_modify_the_input_and_returns_new_pixels():
    image = coordinate_image(300, 200)
    before = image.tobytes()
    prepared, _ = vision.prepare_image(image)
    prepared.putpixel((10, 100), (1, 2, 3))
    assert image.tobytes() == before and image.size == (300, 200)


def test_prepare_image_pad_color_accepts_a_gray_level_or_an_rgb_tuple():
    image = Image.new("RGB", (300, 200), (1, 2, 3))
    assert vision.prepare_image(image, pad_color=255)[0].getpixel((0, 0)) == (255, 255, 255)
    assert vision.prepare_image(image, pad_color=0)[0].getpixel((0, 0)) == (0, 0, 0)
    assert vision.prepare_image(image, pad_color=(250, 245, 235))[0].getpixel((5, 5)) == (
        250,
        245,
        235,
    )
    assert vision.prepare_image(image)[0].getpixel((5, 5)) == GRAY


@pytest.mark.parametrize(
    "pad_color", [256, -1, True, 1.5, "red", (1, 2), (1, 2, 3, 4), (1, 2, 256), (1.0, 2, 3), None]
)
def test_prepare_image_rejects_an_invalid_pad_color(pad_color):
    with pytest.raises(ValueError, match="pad_color"):
        vision.prepare_image(Image.new("RGB", (300, 200)), pad_color=pad_color)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_side": 0},
        {"min_side": -280},
        {"min_side": True},
        {"min_side": 280.0},
        {"max_side": 0},
        {"max_side": "1568"},
        {"min_side": 300, "max_side": 299},
    ],
)
def test_prepare_image_rejects_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        vision.prepare_image(Image.new("RGB", (300, 200)), **kwargs)


def test_prepare_image_accepts_color_modes_and_refuses_transparency():
    gray = Image.new("L", (300, 200), 7)
    prepared, _ = vision.prepare_image(gray)
    assert prepared.mode == "RGB" and prepared.getpixel((0, 100)) == (7, 7, 7)
    palette = Image.new("P", (300, 200), 0)
    palette.putpalette([9, 8, 7] + [0] * 765)
    assert vision.prepare_image(palette)[0].getpixel((0, 100)) == (9, 8, 7)
    assert vision.prepare_image(Image.new("1", (300, 200), 1))[0].getpixel((0, 100)) == (255,) * 3
    transparent_palette = palette.copy()
    transparent_palette.info["transparency"] = 0
    for image in (
        Image.new("RGBA", (300, 200), (1, 2, 3, 0)),
        Image.new("LA", (300, 200)),
        transparent_palette,
        Image.new("F", (300, 200)),
        Image.new("I;16", (300, 200)),
    ):
        with pytest.raises(ValueError, match="flatten"):
            vision.prepare_image(image)


# Tile and crop minimums ----------------------------------------------------------------------


def test_generate_tiles_min_side_accepts_the_documented_example_and_the_exact_minimum():
    image = Image.new("RGB", (1000, 800))
    tiles = vision.generate_tiles(image, tile_size=(320, 280), overlap=32, min_side=280)
    assert len(tiles) == len(vision.generate_tiles(image, tile_size=(320, 280), overlap=32))
    assert all(tile.image.size == (320, 280) for tile in tiles)
    # 280 is allowed (the range includes both ends).
    assert len(vision.generate_tiles(image, tile_size=(280, 280), min_side=280)) == 4 * 3
    # A source smaller than a tile keeps its extent, which is fine while it is >= 280.
    only = vision.generate_tiles(Image.new("RGB", (300, 290)), tile_size=(512, 512), min_side=280)
    assert [tile.bounds for tile in only] == [(0, 0, 300, 290)]


@pytest.mark.parametrize(
    "tile_size,message",
    [
        ((320, 279), "tile would be 320 x 279 pixels, under min_side=280"),
        ((279, 320), "tile would be 279 x 320 pixels, under min_side=280"),
        ((100, 100), "tile would be 100 x 100 pixels"),
    ],
)
def test_generate_tiles_min_side_refuses_a_small_tile_size_before_cropping(
    monkeypatch, tile_size, message
):
    image = Image.new("RGB", (1000, 800))
    monkeypatch.setattr(Image.Image, "crop", lambda *a, **k: pytest.fail("cropped before check"))
    with pytest.raises(ValueError, match=message):
        vision.generate_tiles(image, tile_size=tile_size, min_side=280)


def test_generate_tiles_min_side_refuses_a_source_narrower_than_the_minimum():
    # A 270 wide source with 512 tiles yields 270 x 512 tiles: refused. 1000 x 270 likewise.
    with pytest.raises(ValueError, match="tile would be 270 x 512 pixels"):
        vision.generate_tiles(Image.new("RGB", (270, 1000)), min_side=280)
    with pytest.raises(ValueError, match="tile would be 512 x 270 pixels"):
        vision.generate_tiles(Image.new("RGB", (1000, 270)), min_side=280)
    # With no min_side the same call still works (the default checks nothing).
    assert len(vision.generate_tiles(Image.new("RGB", (270, 1000)))) == 2


def test_generate_tiles_min_side_message_points_at_prepare_image():
    with pytest.raises(ValueError, match="prepare_image"):
        vision.generate_tiles(Image.new("RGB", (1000, 800)), tile_size=(200, 200), min_side=280)


@pytest.mark.parametrize("min_side", [0, -1, True, 280.0, "280"])
def test_generate_tiles_and_crop_box_reject_an_invalid_min_side(min_side):
    with pytest.raises(ValueError, match="min_side"):
        vision.generate_tiles(Image.new("RGB", (1000, 800)), min_side=min_side)
    with pytest.raises(ValueError, match="min_side"):
        vision.crop_box(Image.new("RGB", (1000, 800)), FULL, min_side=min_side)


def test_crop_box_min_side_accepts_exactly_280_and_refuses_279():
    image = Image.new("RGB", (1000, 800))
    # 0.28 * 1000 = 280 pixels wide; the full height is 800.
    crop = vision.crop_box(image, nb(0.0, 0.0, 0.28, 1.0), min_side=280)
    assert crop.size == (280, 800)
    with pytest.raises(ValueError, match="crop would be 279 x 800 pixels, under min_side=280"):
        vision.crop_box(image, nb(0.0, 0.0, 279 / 1000, 1.0), min_side=280)
    with pytest.raises(ValueError, match="crop would be 1000 x 279 pixels"):
        vision.crop_box(image, nb(0.0, 0.0, 1.0, 279 / 800), min_side=280)


def test_crop_box_min_side_counts_the_expanded_crop_and_checks_before_cropping(monkeypatch):
    image = Image.new("RGB", (1000, 800))
    # 0.1 x 0.125 box = 100 x 100 px; expanding by 1.0 adds 100 px each side -> 300 x 300.
    box = nb(0.2, 0.25, 0.3, 0.375)
    with pytest.raises(ValueError, match="crop would be 100 x 100 pixels"):
        vision.crop_box(image, box, min_side=280)
    assert vision.crop_box(image, box, expand=1.0, min_side=280).size == (300, 300)
    monkeypatch.setattr(Image.Image, "crop", lambda *a, **k: pytest.fail("cropped before check"))
    with pytest.raises(ValueError, match="under min_side"):
        vision.crop_box(image, box, min_side=280)


def test_crop_box_without_min_side_still_returns_a_small_crop():
    assert vision.crop_box(Image.new("RGB", (1000, 800)), nb(0.2, 0.25, 0.3, 0.375)).size == (
        100,
        100,
    )


def test_crop_bounds_are_the_pixels_crop_box_cuts():
    # BOX on 16 x 8: x 2..10, y 2..6 (the crop is 8 x 4 starting at (2, 2)).
    assert vision.crop_bounds(BOX, 16, 8) == (2, 2, 10, 6)
    # Expanded by 0.25 of its size on each side: x 0..12 (clipped at 0), y 1..7.
    assert vision.crop_bounds(BOX, 16, 8, expand=0.25) == (0, 1, 12, 7)
    image = coordinate_image(16, 8)
    for expand in (0.0, 0.25):
        assert (
            vision.crop_box(image, BOX, expand=expand).tobytes()
            == image.crop(vision.crop_bounds(BOX, 16, 8, expand=expand)).tobytes()
        )


# Multi-level mapping -------------------------------------------------------------------------


def test_a_box_found_two_levels_down_maps_to_the_full_image_exactly():
    size = (1568, 1024)
    # Level 1: the default 512 tile at (512, 0). Level 2: a 256 x 256 sub-tile at (128, 256)
    # inside it. A box over x 0.25..0.75 and y 0.25..0.5 of that sub-tile is, in sub-tile
    # pixels, x 64..192 and y 64..128; in the full image that is x 512+128+64 = 704 .. 832 and
    # y 0+256+64 = 320 .. 384.
    level_1 = vision.ImageTransform.crop((512, 0, 1024, 512), *size)
    level_2 = vision.ImageTransform.crop((128, 256, 384, 512), 512, 512)
    found = nb(0.25, 0.25, 0.75, 0.5)
    expected = nb(704 / 1568, 320 / 1024, 832 / 1568, 384 / 1024)
    both = level_1.then(level_2)
    assert both.original_size == size and both.derived_size == (256, 256)
    assert both.to_original(found) == expected  # equal, not approximately equal
    # The step-by-step route through the existing function gives the same box to the last bit
    # only by luck; it must at least agree to a tight tolerance.
    stepwise = vision.tile_to_image(
        vision.tile_to_image(found, (128, 256, 384, 512), 512, 512), (512, 0, 1024, 512), *size
    )
    assert stepwise == pytest.approx(expected, abs=1e-12)
    # Forward is exact too: the full-image box is the sub-tile box.
    assert both.to_derived(expected) == found


def test_three_levels_with_a_pad_in_the_middle_map_to_the_full_image_exactly():
    size = (1568, 1024)
    tile = vision.generate_tiles(Image.new("RGB", size))[1]
    assert tile.bounds == (512, 0, 1024, 512)
    level_1 = vision.ImageTransform.crop(tile.bounds, *size)
    level_2 = vision.ImageTransform.crop((128, 256, 384, 512), 512, 512)  # 256 x 256: too small
    sub_image = Image.new("RGB", (256, 256))
    padded, level_3 = vision.prepare_image(sub_image)
    # 256 -> 280 is 24 pixels, 12 each side: the picture is x, y 12..268 of 280.
    assert padded.size == (280, 280)
    assert level_3.derived_window == (Fraction(3, 70),) * 2 + (Fraction(67, 70),) * 2
    chain = level_1.then(level_2).then(level_3)
    # A box at prepared pixels x 76..204, y 76..140 is picture pixels 64..192 and 64..128, the
    # same box as in the previous test.
    found = nb(76 / 280, 76 / 280, 204 / 280, 140 / 280)
    expected = nb(704 / 1568, 320 / 1024, 832 / 1568, 384 / 1024)
    assert chain.to_original(found) == expected
    assert chain.to_derived(expected) == found
    # then() is associative: the grouping does not change the result.
    assert level_1.then(level_2.then(level_3)) == chain
    assert chain.original_size == size and chain.derived_size == (280, 280)
    # A box in the padding of the last level is not in the full image at all.
    assert chain.to_original(nb(0.0, 0.0, 0.03, 0.03)) is None


def test_chained_transforms_agree_with_pixels_on_real_images():
    size = (1568, 1024)
    image = Image.new("RGB", size, (255, 255, 255))
    image.paste((0, 0, 255), (704, 320, 832, 384))  # the target, in full-image pixels
    tile = vision.generate_tiles(image)[1]
    sub = tile.image.crop((128, 256, 384, 512))
    padded, level_3 = vision.prepare_image(sub)
    chain = (
        vision.ImageTransform.crop(tile.bounds, *size)
        .then(vision.ImageTransform.crop((128, 256, 384, 512), 512, 512))
        .then(level_3)
    )
    # The target in prepared pixels is x 76..204, y 76..140: find it from the pixels alone.
    blue = padded.point(lambda v: 255 if v < 50 else 0).getchannel("R")
    assert blue.getbbox() == (76, 76, 204, 140)
    left, top, right, bottom = blue.getbbox()
    found = nb(left / 280, top / 280, right / 280, bottom / 280)
    assert chain.to_original(found) == nb(704 / 1568, 320 / 1024, 832 / 1568, 384 / 1024)
    assert vision.normalized_to_pixels(chain.to_original(found), *size) == (704, 320, 832, 384)


def test_a_resize_then_a_crop_maps_exactly():
    # 3136 x 2048 is halved to 1568 x 1024 by prepare_image; the tile (512, 0)-(1024, 512) of that
    # is x 1024..2048 and y 0..1024 of the original: 1024/3136 = 16/49, 2048/3136 = 32/49, 1/2.
    _, resize = vision.prepare_image(Image.new("RGB", (3136, 2048)))
    chain = resize.then(vision.ImageTransform.crop((512, 0, 1024, 512), 1568, 1024))
    assert chain.original_size == (3136, 2048) and chain.derived_size == (512, 512)
    assert chain.to_original(FULL) == nb(1024 / 3136, 0.0, 2048 / 3136, 0.5)


def test_a_crop_then_a_resize_and_pad_maps_exactly():
    # A 150 x 100 region cut at (400, 300) of a 1000 x 800 image, then padded to 280 x 280:
    # 130 columns (65 each side) and 180 rows (90 each side).
    region = vision.ImageTransform.crop((400, 300, 550, 400), 1000, 800)
    _, prep = vision.prepare_image(Image.new("RGB", (150, 100)))
    chain = region.then(prep)
    # Prepared pixel x 65..215, y 90..190 is the whole region = x 400..550 of 1000, y 300..400 of 800.
    assert chain.to_original(nb(65 / 280, 90 / 280, 215 / 280, 190 / 280)) == nb(
        0.4, 0.375, 0.55, 0.5
    )
    # Prepared x 140..210 and y 140..175 are region pixels x 75..145 and y 50..85, so image pixels
    # x 475..545 of 1000 and y 350..385 of 800.
    assert chain.to_original(nb(0.5, 0.5, 0.75, 0.625)) == nb(
        475 / 1000, 350 / 800, 545 / 1000, 385 / 800
    )
    # Prepared y 140..210 runs 20 rows into the bottom padding: clipped to the region's bottom, 400.
    assert chain.to_original(nb(0.5, 0.5, 0.75, 0.75)) == nb(475 / 1000, 350 / 800, 545 / 1000, 0.5)


def test_then_refuses_mismatched_sizes_and_content_that_is_all_padding():
    tile = vision.ImageTransform.crop((0, 0, 400, 300), 1000, 800)  # derived 400 x 300
    other = vision.ImageTransform.crop((0, 0, 100, 100), 500, 500)
    with pytest.raises(ValueError, match=r"cannot chain.*\(400, 300\).*\(500, 500\)"):
        tile.then(other)
    with pytest.raises(ValueError, match="another ImageTransform"):
        tile.then("not a transform")
    # A 200 x 100 image is padded to 280 x 280 with the picture in rows 90..190. A crop of rows
    # 0..50 shows only padding.
    _, pad = vision.prepare_image(Image.new("RGB", (200, 100)))
    padding_only = vision.ImageTransform.crop((0, 0, 280, 50), 280, 280)
    with pytest.raises(ValueError, match="none of the first transform's content"):
        pad.then(padding_only)
    # A crop of rows 0..100 shows ten rows of picture (90..100): fine, and clipped on the way back.
    partial = pad.then(vision.ImageTransform.crop((0, 0, 280, 100), 280, 280))
    # Its derived box over the whole 280 x 100 crop is picture rows 0..10 and columns 0..200.
    assert partial.to_original(FULL) == nb(0.0, 0.0, 1.0, 0.1)
    # Where the crop's content sits in the *crop*: the picture is columns 40..240 of 280 and
    # rows 90..100 of its 100 rows, i.e. x 1/7..6/7 and y 9/10..1. This is the second remap in
    # then(); using the second step's whole derived image instead would give (0, 0, 1, 1).
    assert partial.derived_window == (Fraction(1, 7), Fraction(9, 10), Fraction(6, 7), Fraction(1))
    # So the top half of the crop (rows 0..50) is padding only: nothing in the original ...
    assert partial.to_original(nb(0.0, 0.0, 1.0, 0.5)) is None
    # ... and a box on picture rows 90..95 of the crop (y 0.9..0.95) is original rows 0..5 of
    # 100 (0.0..0.05); its x 0.5..1.0 is clipped at the content's right edge (6/7), so the
    # original x runs (1/2 - 1/7) / (5/7) = 1/2 to 1.
    assert partial.to_original(nb(0.5, 0.9, 1.0, 0.95)) == nb(0.5, 0.0, 1.0, 0.05)


def test_chain_clips_at_every_level_not_just_the_last():
    # Level 1 shows x 0.25..0.75 (a 500-wide strip of 1000). Level 2 is the right half of that
    # strip, x 250..500 of the strip = 0.5..1.0 of it = 0.5..0.75 of the image.
    first = vision.ImageTransform.crop((250, 0, 750, 800), 1000, 800)
    second = vision.ImageTransform.crop((250, 0, 500, 800), 500, 800)
    chain = first.then(second)
    assert chain.original_window == (Fraction(1, 2), Fraction(0), Fraction(3, 4), Fraction(1))
    # A full-image box 0.25..1.0 only has its 0.5..0.75 part visible two levels down.
    assert chain.to_derived(nb(0.25, 0.0, 1.0, 1.0)) == FULL
    assert chain.visible_fraction(nb(0.25, 0.0, 1.0, 1.0)) == pytest.approx(1 / 3)
    # A box in the middle strip but outside level 2 is nothing for the chain, though level 1 sees it.
    assert first.to_derived(nb(0.25, 0.25, 0.5, 0.5)) is not None
    assert chain.to_derived(nb(0.25, 0.25, 0.5, 0.5)) is None


def test_crop_transforms_agree_with_tile_to_image_for_generated_tiles():
    size = (1000, 777)
    boxes = [FULL, BOX, nb(0.1, 0.2, 0.3, 0.4), nb(0.6, 0.55, 0.95, 0.99)]
    for tile in vision.generate_tiles(Image.new("RGB", size), tile_size=(300, 300), overlap=20):
        transform = vision.ImageTransform.crop(tile.bounds, *size)
        for box in boxes:
            assert transform.to_original(box) == pytest.approx(
                vision.tile_to_image(box, tile.bounds, *size), abs=1e-12
            )


def test_visible_fraction_by_hand():
    transform = vision.ImageTransform.crop(TILE, *WHOLE)  # x 200..700, y 100..500 of 1000 x 800
    assert transform.visible_fraction(nb(0.25, 0.25, 0.5, 0.5)) == 1.0
    assert transform.visible_fraction(nb(0.75, 0.25, 1.0, 0.5)) == 0.0
    # x 0.5..0.9 is pixels 500..900, of which 500..700 (half) are in the tile; y fully inside.
    assert transform.visible_fraction(nb(0.5, 0.25, 0.9, 0.5)) == 0.5
    # A box cut at a corner: x 600..800, y 400..600 -> visible 100 x 100 of 200 x 200 = 1/4.
    assert transform.visible_fraction(nb(0.6, 0.5, 0.8, 0.75)) == 0.25
    # A box that only touches the edge shows nothing.
    assert transform.visible_fraction(nb(0.0, 0.25, 0.2, 0.5)) == 0.0
    with pytest.raises(ValueError):
        transform.visible_fraction(None)


def test_new_names_are_exported():
    for name in ("ImageTransform", "crop_bounds", "image_to_tile", "prepare_image"):
        assert name in vision.__all__ and hasattr(vision, name)
    assert sorted(vision.__all__) == sorted(set(vision.__all__))


def _code_block(section: str, language: str, after: str = "") -> str:
    start = section.index(f"```{language}\n", section.index(after) if after else 0)
    start += len(f"```{language}\n")
    return section[start : section.index("```", start)]


def test_the_documented_worked_example_runs_and_prints_what_the_docs_show():
    text = (_DOCS / "vision.md").read_text("utf-8")
    # Not _section(): the example's "# 1. Tile" comments look like headings to it.
    start = text.index("### Worked example: tile, choose, crop, prepare, Box, map back\n")
    section = text[start : text.index("\n## ", start)]
    code, printed = _code_block(section, "python"), _code_block(section, "text")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(code, "docs/vision.md", "exec"), {})
    assert out.getvalue() == printed
    # The numbers the prose quotes: padded box 80-200 x 110-170, pad (40, 80), crop (200, 300),
    # tile (600, 0): x 600 + 200 + (80 - 40) = 840 ... 960, y 0 + 300 + (110 - 80) = 330 ... 390.
    assert (600 + 200 + (80 - 40), 600 + 200 + (200 - 40)) == (840, 960)
    assert (0 + 300 + (110 - 80), 0 + 300 + (170 - 80)) == (330, 390)
    assert "box in the padded\ncrop is pixels 80-200 by 110-170" in section


def test_the_documented_prepare_image_table_matches_the_function():
    section = _section((_DOCS / "vision.md").read_text("utf-8"), "Preparing an image for the API")
    rows = re.findall(r"^\| (\d+) × (\d+)(, `upscale=True`)? \| (\d+) × (\d+)", section, re.M)
    assert len(rows) == 7
    for width, height, upscale, out_width, out_height in rows:
        prepared, _ = vision.prepare_image(
            Image.new("RGB", (int(width), int(height))), upscale=bool(upscale)
        )
        assert prepared.size == (int(out_width), int(out_height)), (width, height, upscale)
    # The content rectangles quoted in the third column.
    _, transform = vision.prepare_image(Image.new("RGB", (201, 100)))
    assert transform.derived_window[0] * 280 == 39 and transform.derived_window[2] * 280 == 240
    _, transform = vision.prepare_image(Image.new("RGB", (4000, 100)))
    assert transform.derived_window[1] * 280 == 120 and transform.derived_window[3] * 280 == 159


def test_the_docs_describe_the_new_helpers_and_no_longer_say_a_transform_is_missing():
    flat = " ".join((_DOCS / "vision.md").read_text("utf-8").split())
    assert "Padding or further cropping requires its own transform" not in flat
    for name in ("prepare_image", "image_to_tile", "ImageTransform", "visible_fraction"):
        assert name in flat
    assert "min_side=IMAGE_LIMITS[" in flat and "`min_side` defaults to `None`" in flat
    assert "a pixel-identical copy" in flat
    for text in (vision.generate_tiles.__doc__, vision.crop_box.__doc__):
        assert "min_side" in text and "prepare_image" in text


# Review fixes for #341 ------------------------------------------------------------------------


def _asset_checker():
    """The repository's image-file contract (tools/check_recipe_assets.py), loaded by path."""
    path = Path(__file__).resolve().parent.parent / "tools" / "check_recipe_assets.py"
    spec = importlib.util.spec_from_file_location("check_recipe_assets_for_vision_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


def _png_chunk_names(data: bytes) -> list[str]:
    names, position = [], 8
    while position < len(data):
        length = int.from_bytes(data[position : position + 4], "big")
        names.append(data[position + 4 : position + 8].decode("ascii"))
        position += 12 + length
    return names


@pytest.mark.parametrize(
    "size",
    [(400, 300), (2000, 1500), (300, 200), (4000, 100)],
    ids=["already-fits", "resize-only", "pad-only", "resize-and-pad"],
)
def test_prepared_images_carry_no_source_metadata_and_pass_the_image_file_contract(size):
    source = Image.new("RGB", size, (200, 30, 60))
    # A source that was opened from a file with an ICC profile, EXIF, a resolution and text.
    exif = Image.Exif()
    exif[0x010E] = "a description"  # ImageDescription: personal text a real file could carry
    source.info.update(
        icc_profile=b"not-a-real-profile", exif=exif.tobytes(), dpi=(72, 72), Comment="x"
    )
    prepared, _ = vision.prepare_image(source)
    assert prepared.info == {}
    buffer = io.BytesIO()
    prepared.save(buffer, "PNG")
    data = buffer.getvalue()
    assert _png_chunk_names(data) == ["IHDR", "IDAT", "IEND"]
    checker = _asset_checker()
    assert checker.check_image("recipes/01-demo/assets/prepared.png", data) == []
    # The same source saved without preparation is exactly what the contract rejects.
    raw = io.BytesIO()
    source.save(raw, "PNG")
    findings = checker.check_image("recipes/01-demo/assets/raw.png", raw.getvalue())
    assert [finding.rule for finding in findings] == ["png-metadata"]
    assert "iCCP" in findings[0].message


def test_prepare_image_rejects_a_zero_sized_image_with_a_value_error():
    for upscale in (False, True):
        with pytest.raises(ValueError, match="image width must be a positive integer"):
            vision.prepare_image(Image.new("RGB", (0, 0)), upscale=upscale)
        with pytest.raises(ValueError, match="image height must be a positive integer"):
            vision.prepare_image(Image.new("RGB", (300, 0)), upscale=upscale)


def test_prepare_image_resamples_with_an_averaging_filter_not_nearest_neighbour():
    # Left 1001 columns black, the rest white, scaled by 0.784 (2000 -> 1568): the edge lands at
    # column 784.78, inside a pixel. A point-sampling filter (NEAREST) can only return 0 or 255;
    # any filter that averages, Lanczos included, returns a grey there. This does not pin the
    # kernel's exact values, which Pillow is free to refine.
    image = Image.new("RGB", (2000, 1000), (255, 255, 255))
    image.paste((0, 0, 0), (0, 0, 1001, 1000))
    prepared, _ = vision.prepare_image(image)
    assert prepared.size == (1568, 784)
    row = [prepared.getpixel((x, 392))[0] for x in range(1568)]
    assert row[0] == 0 and row[-1] == 255
    assert any(0 < value < 255 for value in row[780:790])


def test_the_docs_say_how_to_report_a_mapped_back_answer_and_when_to_upscale():
    flat = " ".join((_DOCS / "vision.md").read_text("utf-8").split())
    tiled = " ".join(
        _section((_DOCS / "vision.md").read_text("utf-8"), "Tiled and hierarchical recipes").split()
    )
    assert "after `ImageTransform.to_original` on the chain that `.then` built" in tiled
    assert 'report `("review", None)`, never `("absent", None)`' in tiled
    assert 'a `None` from `to_original` is reported as `("review", None)`' in flat
    assert "Choose `upscale` once per recipe" in flat
    assert "the content covering 0.13% of the image" in flat
    assert "has not been measured against Jev; treat it as a design decision" in flat
    assert "too little for Jev" not in flat
    assert "orientation is not 1 raises `ValueError`" in flat
    assert (
        "carries none of its metadata" in flat and "`image_asset` does not check PNG chunks" in flat
    )
    evaluation = " ".join((_DOCS / "evaluation.md").read_text("utf-8").split())
    assert "after `ImageTransform.to_original` on the chain of steps" in evaluation
    assert "(`None`) as `review`" in evaluation
    # The 10 x 10 figure: 100 of 78,400 pixels is 0.13% (0.1276 rounds up).
    prepared, transform = vision.prepare_image(Image.new("RGB", (10, 10)))
    assert prepared.size == (280, 280)
    assert round(100 / 78_400 * 100, 2) == 0.13
    assert transform.derived_window == (
        Fraction(27, 56),
        Fraction(27, 56),
        Fraction(29, 56),
        Fraction(29, 56),
    )


def _jpeg_with_orientation(orientation, size=(320, 300)):
    exif = Image.Exif()
    exif[274] = orientation
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buffer, "JPEG", exif=exif)
    return Image.open(io.BytesIO(buffer.getvalue()))


@pytest.mark.parametrize("orientation", [2, 3, 6, 8])
def test_prepare_image_refuses_a_non_identity_exif_orientation_like_image_asset(
    orientation, tmp_path
):
    image = _jpeg_with_orientation(orientation)
    assert image.getexif()[274] == orientation
    with pytest.raises(ValueError, match="rotate EXIF orientation into pixels"):
        vision.prepare_image(image)
    # image_asset gives the same refusal for the same file, with the same message.
    path = tmp_path / "rotated.jpg"
    image.save(path, "JPEG", exif=image.getexif())
    with pytest.raises(ValueError, match="rotate EXIF orientation into pixels"):
        vision.image_asset(path)


def test_prepare_image_accepts_exif_orientation_one_and_no_exif():
    for image in (_jpeg_with_orientation(1), Image.new("RGB", (320, 300))):
        prepared, _ = vision.prepare_image(image)
        assert prepared.size == (320, 300) and prepared.info == {}


def test_prepare_image_reports_damaged_exif_as_a_value_error():
    image = Image.new("RGB", (320, 300))
    image.info["exif"] = b"Exif\x00\x00II*\x00"  # a header and nothing else
    with pytest.raises(ValueError, match="EXIF data is damaged"):
        vision.prepare_image(image)
