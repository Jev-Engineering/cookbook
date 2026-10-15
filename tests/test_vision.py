"""Offline image validation and geometry tests with independently computed expectations."""

from __future__ import annotations

import base64
import math
from dataclasses import is_dataclass
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import vision

FULL = {"top": 0.0, "bottom": 1.0, "left": 0.0, "right": 1.0}
BOX = {"top": 0.25, "bottom": 0.75, "left": 0.125, "right": 0.625}


def save_image(tmp_path, *, size=(320, 256), fmt="PNG", name="image", color="white", **kwargs):
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


@pytest.mark.parametrize("size", [(280, 280), (256, 307), (1568, 1568)])
def test_image_asset_accepts_boundary_dimensions(tmp_path, size):
    assert vision.image_asset(save_image(tmp_path, size=size))["type"] == "image"


@pytest.mark.parametrize("size", [(255, 400), (400, 255), (256, 306), (1569, 256), (256, 1569)])
def test_image_asset_rejects_invalid_dimensions(tmp_path, size):
    with pytest.raises(ValueError):
        vision.image_asset(save_image(tmp_path, size=size))


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
    Image.new("RGB", (320, 256), "white").save(
        path,
        save_all=True,
        append_images=[Image.new("RGB", (320, 256), "black")],
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


def test_image_references_follow_content_not_path(tmp_path, image_path, asset):
    copy = tmp_path / "copy.png"
    copy.write_bytes(image_path.read_bytes())
    changed = save_image(tmp_path, name="different.png", color="black")
    ref = vision.image_reference(asset)
    assert isinstance(ref, str) and ref
    assert ref == vision.image_reference(vision.image_asset(copy))
    assert ref != vision.image_reference(vision.image_asset(changed))


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
