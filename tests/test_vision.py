"""Offline image validation and geometry tests with independently computed expectations."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import random
from dataclasses import is_dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import vision
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
