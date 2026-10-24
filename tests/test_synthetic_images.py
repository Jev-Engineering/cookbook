"""jev_cookbook.synthetic_images (#314): determinism, gold geometry, readability, asset contract.

The four properties the module promises, each tested against the real thing:

* **Byte stability.** Hash-pinned outputs (``PINNED``) on every CI Python; the encoder is proved
  independent of zlib and Pillow's encoder by making both unusable while generating.
* **Gold geometry.** Every drawing call is wrapped so the pixels it changed are compared with the
  rectangle it returned; generators are checked element by element.
* **Readability.** Every text run is read back from the pixels, is at least 14 pixels tall and
  contrasts with its background.
* **Contract.** Every generator output passes ``tools/check_recipe_assets.py`` and
  ``vision.image_asset``, and respects ``vision.IMAGE_LIMITS``.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from jev_cookbook import synthetic_images as si
from jev_cookbook import vision

REPO = Path(__file__).resolve().parent.parent
CHECKER = REPO / "tools" / "check_recipe_assets.py"
GALLERY = REPO / "docs" / "assets" / "synthetic-images"

spec = importlib.util.spec_from_file_location("check_recipe_assets_for_synthetic", CHECKER)
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)

ASSET_PATH = "recipes/01-demo/assets/image.png"


def assert_contract(image: si.SyntheticImage) -> bytes:
    data = image.png_bytes()
    assert checker.check_image(ASSET_PATH, data) == []
    asset = {
        "type": "image",
        "format": "png",
        "data_base64": base64.b64encode(data).decode(),
    }
    assert vision.validate_image_asset(asset) == data
    return data


# Every generator in several configurations, including the hard and ambiguous ones.
CASES = {
    "shapes_scene": lambda: si.shapes_scene(0),
    "shapes_scene_hard": lambda: si.shapes_scene(
        3, count=6, perturbations=[("blur", 1), ("dim", 30)]
    ),
    "ui_mock_occluded": lambda: si.ui_mock(4, occlude="button_save", perturbations=[("glare", 30)]),
    "ui_mock": lambda: si.ui_mock(0),
    "ui_mock_error_spinner": lambda: si.ui_mock(1, error="SAVE FAILED", spinner=True),
    "ui_mock_dialog": lambda: si.ui_mock(2, dialog="DISCARD CHANGES? THIS CANNOT BE UNDONE."),
    "ui_mock_three_fields": lambda: si.ui_mock(
        3, height=620, fields=("A", "B", "C"), buttons=("OK", "NO", "HELP"), error="BAD INPUT"
    ),
    "wordmark": lambda: si.wordmark(0),
    "wordmark_variants": lambda: si.wordmark(1, brand="TAVRIK", variant=2),
    "document_page": lambda: si.document_page(0),
    "document_unstamped": lambda: si.document_page(1, stamp=None, signature=False),
    "product_shelf": lambda: si.product_shelf(0),
    "product_shelf_gaps": lambda: si.product_shelf(1, count=5, gaps=[1, 3]),
    "defect_none": lambda: si.defect_panel(0, defect=None),
    "defect_scratch": lambda: si.defect_panel(0, defect="scratch"),
    "defect_dent": lambda: si.defect_panel(0, defect="dent"),
    "defect_missing": lambda: si.defect_panel(0, defect="missing_part"),
    "defect_hard": lambda: si.defect_panel(
        2, defect="scratch", perturbations=[("blur", 2), ("vignette", 40)]
    ),
    "deck_builder_hud": lambda: si.deck_builder_hud(0),
    "deck_builder_hud_full": lambda: si.deck_builder_hud(1, hand=7, health=(0, 50)),
    "schematic": lambda: si.schematic(0),
    "schematic_two": lambda: si.schematic(1, components=("lamp", "resistor")),
}

# SHA-256 of the PNG bytes. Changing a generator or the encoder changes these on purpose, with a
# GENERATOR_VERSION bump (see the module docstring): update them in the same commit.
PINNED = {
    "deck_builder_hud": "e620ae9988355a31d024eb20a5df20dceadf524a342afc979548a81ec35dc64c",
    "deck_builder_hud_full": "8027318b4a9907acd1366839774662136e6c5bdc26b6e5a11ff94b123880a566",
    "defect_dent": "955aefca34b9ffcdf5573f1880a1eed3cd946d9937a6a122afdbbe84a9c10923",
    "defect_hard": "8857ab719ca7b278d74d64e5e8bbd81fd4209337a83fb7d6195afaad361de981",
    "defect_missing": "66a5aa3e4f04f5c65bab137ed54c0d2329fe5bffa75699dcaddaa7a50e8ef636",
    "defect_none": "324d3d42733acfc6085462131724405ec7503bdb94e5780f7e6cfe8a1d2f6705",
    "defect_scratch": "26c77c57e3ef108458917bf09ef9d30672ca55efb098fe7873b6acc3f6aed9ca",
    "document_page": "6e545e2cf8c9b67e3384687bba5090ccf635f0224d0e94f603b57998b897b2ac",
    "document_unstamped": "817f7f2efa02ba09410ae99ccee5eaccb31105095548531b9134a5250ba93a85",
    "product_shelf": "38bbe84adcd293f789d65fb7d3e16edb09990ee54206137565f284343ccd3498",
    "product_shelf_gaps": "7c07759b2a95652484ff5d93041d4489faa0d1025fc4589e594b62880f62ec07",
    "schematic": "28970b48465781b46129aac53552888894558ed391df4a33bff31924f8922e28",
    "schematic_two": "5f00601cf4e22a96ff86c41c8bade4ace0179099aeabd950bd1ae5b8e428de64",
    "shapes_scene": "5cb7889f91279177bdcc9143b8215299b8d8ef427f17bfb876ae05ca13d18a8b",
    "shapes_scene_hard": "351675f3a40a86cccf7ace3508704448ac87ead0caeb208d80f9c3fb7dfe3ed2",
    "ui_mock": "f07b398adcbb1f5f2849fb8f4e271ebfdda24e4b91693ca86cd648a1a1014308",
    "ui_mock_dialog": "28c5a4d934263fe61248be827d25b61d29a86c959cf574f2dfbca31f0beae980",
    "ui_mock_error_spinner": "cdbeae0c258a38bebd7d90d2d05f5a741bd6e3a4a2c391b06a15232832241bf0",
    "ui_mock_occluded": "3e765f5082917073204b9fe168818ae28f0810aba0fefa5251f81426824072ba",
    "ui_mock_three_fields": "2d9fd099a28f2d0a2c952c5fbcd7c491b54928be80fb482b6e542c8b20aa1024",
    "wordmark": "8a78aaed7afa9f6451124eecb934c6e164a74045cd04adbdc6dfca90d3177522",
    "wordmark_variants": "79db843b8502436b9004b3543859699e3d656cc413404e7e38db2c645329876a",
}


def build(name: str) -> si.SyntheticImage:
    return CASES[name]()


# -- the random generator --------------------------------------------------------------------


def test_splitmix64_matches_the_published_reference_values():
    # Reference outputs of SplitMix64 seeded with 0 (Steele, Lea & Flood; Vigna's splitmix64.c).
    rng = si.Rng(0)
    assert [rng.u64() for _ in range(3)] == [
        0xE220A8397B1DCDAF,
        0x6E789E6AA1B965F4,
        0x06C45D188009454F,
    ]


def test_rng_helpers_and_the_vectorised_stream_agree_with_the_scalar_one():
    scalar = si.Rng(12345)
    assert [scalar.u64() for _ in range(50)] == [int(v) for v in si._u64_array(12345, 50)]
    rng = si.Rng(9)
    values = [rng.integer(3, 7) for _ in range(200)]
    assert set(values) == {3, 4, 5, 6, 7}
    assert sorted(si.Rng(4).shuffled(range(10))) == list(range(10))
    assert si.Rng(4).shuffled(range(10)) == si.Rng(4).shuffled(range(10))


@pytest.mark.parametrize("seed", [-1, 2**63, 1.5, True, "3"])
def test_bad_seeds_are_rejected(seed):
    with pytest.raises(ValueError, match="seed"):
        si.Rng(seed)
    with pytest.raises(ValueError, match="seed"):
        si.shapes_scene(seed)


# -- the PNG encoder -------------------------------------------------------------------------


def chunks(data: bytes):
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        yield data[pos + 4 : pos + 8].decode(), data[pos + 8 : pos + 8 + length]
        pos += 12 + length


def test_encoder_writes_only_critical_chunks_and_round_trips_through_zlib_and_pillow():
    rng = np.random.default_rng(5)
    arrays = {
        "flat": np.full((300, 300, 3), 200, dtype=np.uint8),
        "noise": rng.integers(0, 256, (280, 281, 3), dtype=np.uint8),
        "stripes": np.tile(np.arange(300, dtype=np.uint8)[None, :, None], (300, 1, 3)),
        "blocks": np.kron(
            rng.integers(0, 256, (7, 7, 3), dtype=np.uint8), np.ones((43, 43, 1), dtype=np.uint8)
        ),
    }
    for name, array in arrays.items():
        data = si.encode_png(array)
        assert [kind for kind, _ in chunks(data)] == ["IHDR", "IDAT", "IEND"], name
        with Image.open(io.BytesIO(data)) as decoded:
            assert decoded.format == "PNG" and decoded.mode == "RGB"
            assert np.array_equal(np.array(decoded), array), name
        assert checker.check_image(ASSET_PATH, data) == [], name


@pytest.mark.parametrize(
    "length", [1, 2, 3, 4, 5, 6, 7, 257, 258, 259, 260, 261, 262, 516, 517, 518]
)
def test_deflate_run_lengths_around_the_258_byte_match_limit(length):
    data = b"			" + bytes([9]) * length
    assert zlib.decompressobj(-15).decompress(si._deflate_runs(data)) == data


def test_encoder_is_independent_of_zlib_compression_and_pillow_encoding(monkeypatch):
    expected = si.shapes_scene(0).png_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("the encoder must not use zlib's compressor or Pillow's PNG writer")

    monkeypatch.setattr(zlib, "compress", forbidden)
    monkeypatch.setattr(zlib, "compressobj", forbidden)
    monkeypatch.setattr(Image.Image, "save", forbidden)
    assert si.shapes_scene(0).png_bytes() == expected


def test_encoder_rejects_the_wrong_array_shape():
    for bad in (np.zeros((300, 300), dtype=np.uint8), np.zeros((300, 300, 3), dtype=np.int16)):
        with pytest.raises(ValueError, match="uint8 array"):
            si.encode_png(bad)


# -- byte stability --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CASES))
def test_output_is_pinned_and_repeatable(name):
    first = build(name).png_bytes()
    assert build(name).png_bytes() == first
    assert hashlib.sha256(first).hexdigest() == PINNED[name], (
        f"{name}: the bytes changed. If intended, bump GENERATOR_VERSION and update PINNED."
    )


def test_every_pinned_case_has_a_pin_and_no_pin_is_stale():
    assert set(PINNED) == set(CASES)


@pytest.mark.parametrize("name", ["shapes_scene", "ui_mock", "product_shelf", "defect_scratch"])
def test_a_different_seed_changes_the_picture(name):
    func = {
        "shapes_scene": si.shapes_scene,
        "ui_mock": si.ui_mock,
        "product_shelf": si.product_shelf,
        "defect_scratch": si.defect_panel,
    }[name]
    kwargs = {"defect": "scratch"} if name == "defect_scratch" else {}
    digests = {func(seed, **kwargs).sha256() for seed in range(6)}
    assert len(digests) > 1


def test_output_does_not_depend_on_the_interpreter_hash_seed():
    code = (
        "from jev_cookbook import synthetic_images as s; "
        "print(s.ui_mock(1, error='X', spinner=True).sha256()); "
        "print(s.product_shelf(1, count=5, gaps=[1]).sha256())"
    )
    outputs = set()
    for hash_seed in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        outputs.add(result.stdout)
    assert len(outputs) == 1
    here = (
        si.ui_mock(1, error="X", spinner=True).sha256()
        + "\n"
        + si.product_shelf(1, count=5, gaps=[1]).sha256()
        + "\n"
    )
    assert outputs == {here}


def test_provenance_reproduces_the_file():
    for name in sorted(CASES):
        image = build(name)
        record = image.provenance
        assert record["origin"] == "generated"
        assert record["generator_version"] == si.GENERATOR_VERSION
        generator = record["generator"].removeprefix("jev_cookbook.synthetic_images.")
        again = si.GENERATORS[generator](record["seed"], **record["parameters"])
        assert again.png_bytes() == image.png_bytes(), name
        json.dumps(record)  # serialisable as written


# -- the asset contract ----------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_generator_output_passes_the_checker_and_the_vision_loader(name):
    image = build(name)
    data = assert_contract(image)
    assert len(data) <= si.MAX_ASSET_BYTES
    lim = vision.IMAGE_LIMITS
    assert lim["min_side"] <= image.width <= lim["max_side"]
    assert lim["min_side"] <= image.height <= lim["max_side"]
    assert lim["min_area"] <= image.width * image.height <= lim["max_area"]


def test_the_size_cap_matches_the_checker_and_the_limits_are_the_apis():
    assert si.MAX_ASSET_BYTES == checker.MAX_FILE_BYTES
    assert (
        vision.IMAGE_LIMITS["min_side"],
        vision.IMAGE_LIMITS["max_side"],
        vision.IMAGE_LIMITS["min_area"],
        vision.IMAGE_LIMITS["max_area"],
    ) == (checker.MIN_SIDE, checker.MAX_SIDE, checker.MIN_PIXELS, checker.MAX_PIXELS)


@pytest.mark.parametrize(
    ("width", "height"),
    [(279, 400), (400, 279), (1569, 400), (400, 1569), (1568, 1568 + 1), (280.0, 300)],
)
def test_canvas_rejects_sizes_outside_the_api_limits(width, height):
    with pytest.raises(ValueError):
        si.Canvas(width, height)


def test_canvas_accepts_the_extreme_valid_sizes_and_saves_them_as_valid_assets():
    for width, height in ((280, 280), (1568, 1568), (1568, 280), (280, 1568)):
        canvas = si.Canvas(width, height, "#336699")
        canvas.rect((10, 10, 100, 100), "#CC3333", name="r")
        data = assert_contract(canvas.finish("manual", {}, 0, {}))
        assert len(data) < si.MAX_ASSET_BYTES


def test_write_asset_creates_verifies_and_never_replaces(tmp_path):
    image = si.ui_mock(0)
    path = tmp_path / "recipes" / "01-demo" / "assets" / "ui.png"
    first = si.write_asset(image, path)
    assert first.status == "created" and path.read_bytes() == image.png_bytes()
    assert checker.check_image(ASSET_PATH, path.read_bytes()) == []
    again = si.write_asset(image, path)
    assert again.status == "identical" and again.sha256 == first.sha256

    other = si.ui_mock(1)
    with pytest.raises(si.AssetMismatchError, match="canonical"):
        si.write_asset(other, path)
    assert path.read_bytes() == image.png_bytes()  # untouched

    # The same pixels in different bytes (another encoder wrote the committed file): kept.
    buffer = io.BytesIO()
    Image.fromarray(np.array(image.pixels), "RGB").save(buffer, "PNG", optimize=True)
    path.write_bytes(buffer.getvalue())
    result = si.write_asset(image, path)
    assert result.status == "pixel-equal" and path.read_bytes() == buffer.getvalue()


def test_write_asset_location_suffix_and_size_rules(tmp_path):
    image = si.shapes_scene(0)
    with pytest.raises(ValueError, match="assets"):
        si.write_asset(image, tmp_path / "fixtures" / "a.png")
    with pytest.raises(ValueError, match="lowercase .png"):
        si.write_asset(image, tmp_path / "assets" / "a.PNG")
    with pytest.raises(ValueError, match="lowercase .png"):
        si.write_asset(image, tmp_path / "assets" / "a.jpg")
    noisy = si.Canvas(1000, 1000)
    noisy.noise(120, 1, color_noise=True)
    with pytest.raises(ValueError, match="byte cap"):
        si.write_asset(noisy.finish("manual", {}, 0, {}), tmp_path / "assets" / "n.png")
    assert not (tmp_path / "assets" / "n.png").exists()


def test_a_written_recipe_tree_passes_the_whole_tree_checker(tmp_path):
    root = tmp_path / "recipes" / "01-demo"
    entries = []
    for index, name in enumerate(sorted(CASES)):
        saved = si.write_asset(build(name), root / "assets" / f"{index:02d}-{name}.png")
        entries.append(
            checker.Entry(
                f"recipes/01-demo/assets/{saved.path.name}", "100644", saved.path.read_bytes()
            )
        )
    assert checker.check_entries(entries) == []


def test_manifest_entry_carries_origin_generator_seed_parameters_and_file_facts(tmp_path):
    image = si.defect_panel(4, defect="dent")
    saved = si.write_asset(image, tmp_path / "assets" / "plate.png")
    entry = saved.manifest_entry("assets/plate.png")
    assert entry["path"] == "assets/plate.png"
    assert entry["origin"] == "generated"
    assert entry["generator"] == "jev_cookbook.synthetic_images.defect_panel"
    assert entry["generator_version"] == si.GENERATOR_VERSION
    assert entry["seed"] == 4 and entry["parameters"]["defect"] == "dent"
    assert (
        entry["sha256"]
        == hashlib.sha256((tmp_path / "assets" / "plate.png").read_bytes()).hexdigest()
    )
    assert (entry["bytes"], entry["width"], entry["height"]) == (
        saved.path.stat().st_size,
        640,
        480,
    )
    json.dumps(entry)


# -- text: readable, big enough, contrasting ------------------------------------------------


def test_every_glyph_is_five_by_seven_nonblank_and_distinct():
    seen = {}
    for char, glyph in si._GLYPHS.items():
        assert glyph.shape == (7, 5), char
        if char != " ":
            assert glyph.any(), char
        key = glyph.tobytes()
        assert key not in seen, f"{char!r} looks like {seen[key]!r}"
        seen[key] = char
    assert set(si.SUPPORTED_CHARS) >= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;!?-+/()%#$")


@pytest.mark.parametrize("scale", [2, 3, 5])
def test_every_supported_character_is_rendered_and_read_back(scale):
    text = si.SUPPORTED_CHARS
    per_line = 40
    canvas = si.Canvas(1568, 560, "#FFFFFF")
    runs = []
    for i in range(0, len(text), per_line):
        piece = text[i : i + per_line]
        y = 10 + (i // per_line) * (7 * scale + 6)
        canvas.text((8, y), piece, scale=scale, color="#000000")
        runs.append(canvas.text_runs[-1])
    for run in runs:
        assert si.read_text(canvas.pixels, run) == run.text


def test_text_has_a_minimum_glyph_size_and_fails_loudly():
    canvas = si.Canvas(400, 300, "#FFFFFF")
    assert si.MIN_TEXT_SCALE * si.GLYPH_HEIGHT == 14
    for bad in (1, 0, -3, 2.5, True):
        with pytest.raises(ValueError, match="scale"):
            canvas.text((10, 10), "HI", scale=bad)
    placed = canvas.text((10, 10), "HI", scale=2)
    assert placed.height == 14
    with pytest.raises(ValueError, match="unsupported"):
        canvas.text((10, 40), "café 中", scale=3)
    with pytest.raises(ValueError, match="fit"):
        canvas.text((380, 10), "OVERFLOW", scale=3)
    with pytest.raises(ValueError, match="nonempty"):
        canvas.text((10, 10), "", scale=3)


def test_lower_case_is_folded_and_low_contrast_text_is_refused():
    canvas = si.Canvas(400, 300, "#FFFFFF")
    canvas.text((10, 10), "mixed Case", scale=3)
    assert canvas.text_runs[-1].text == "MIXED CASE"
    with pytest.raises(ValueError, match="contrast"):
        canvas.text((10, 60), "FAINT", scale=3, color="#EEEEEE")
    canvas.text((10, 60), "FAINT", scale=3, color="#EEEEEE", min_contrast=1.0)  # explicit opt-out
    assert si.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert si.contrast_ratio("#777777", "#777777") == pytest.approx(1.0)


def test_wrap_text_respects_the_width_and_rejects_an_unbreakable_word():
    lines = si.wrap_text("ONE TWO THREE FOUR FIVE SIX", 2, 200)
    assert all(si.text_size(line, 2)[0] <= 200 for line in lines) and len(lines) > 1
    assert " ".join(lines) == "ONE TWO THREE FOUR FIVE SIX"
    with pytest.raises(ValueError, match="wider"):
        si.wrap_text("SUPERCALIFRAGILISTIC", 3, 100)


# Generators whose final pixels still show every text run exactly (no scrim or perturbation).
READABLE = [
    n
    for n in sorted(CASES)
    if n not in {"ui_mock_dialog", "shapes_scene_hard", "defect_hard", "ui_mock_occluded"}
]


@pytest.mark.parametrize("name", READABLE)
def test_every_text_in_a_generated_image_is_rendered_big_and_contrasting(name):
    image = build(name)
    assert image.text_runs, "a generator with no text has nothing to read"
    for run in image.text_runs:
        assert run.scale >= si.MIN_TEXT_SCALE
        assert si.read_text(image.pixels, run) == run.text, (name, run.text)
        left, top, right, bottom = run.placed.bounds
        assert bottom - top >= si.MIN_TEXT_SCALE * 5  # even a dash-only line is tall enough
        patch = image.pixels[top:bottom, left:right].reshape(-1, 3)
        behind = patch[(patch != np.array(run.color, dtype=np.uint8)).any(axis=1)]
        assert len(behind), "text with no background pixels beside the ink"
        background = tuple(int(v) for v in np.median(behind, axis=0))
        assert si.contrast_ratio(run.color, background) >= 3.0, (name, run.text)


def test_dialog_text_is_readable_and_the_scrim_dims_what_is_behind_it():
    image = si.ui_mock(2, dialog="DISCARD CHANGES? THIS CANNOT BE UNDONE.")
    dialog = image.elements["dialog"]
    inside = [r for r in image.text_runs if dialog.contains(r.placed)]
    assert {r.text for r in inside} >= {"OK"} and len(inside) >= 3
    for run in inside:
        assert si.read_text(image.pixels, run) == run.text
    plain = si.ui_mock(2)
    corner = (3, 3)
    assert int(image.pixels[corner].sum()) < int(plain.pixels[corner].sum())


# -- gold geometry ---------------------------------------------------------------------------


def changed_bounds(before: np.ndarray, after: np.ndarray):
    diff = (before != after).any(axis=2)
    rows, cols = np.flatnonzero(diff.any(axis=1)), np.flatnonzero(diff.any(axis=0))
    if not rows.size:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


@pytest.fixture
def audited_canvas(monkeypatch):
    """Every ``_paint``/``_changed`` call must return bounds containing every pixel it changed."""
    calls = []
    real_paint = si.Canvas._paint

    def paint(self, bounds, mask, color, name):
        before = self.pixels.copy()
        placed = real_paint(self, bounds, mask, color, name)
        moved = changed_bounds(before, self.pixels)
        if moved is not None:
            left, top, right, bottom = placed.bounds
            assert left <= moved[0] and top <= moved[1] and right >= moved[2] and bottom >= moved[3]
        calls.append(placed)
        return placed

    monkeypatch.setattr(si.Canvas, "_paint", paint)
    return calls


@pytest.mark.parametrize("name", sorted(CASES))
def test_drawn_pixels_lie_inside_the_returned_box_for_every_call_of_every_generator(
    name, audited_canvas
):
    build(name)
    assert len(audited_canvas) >= 3


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_element_is_a_valid_on_canvas_normalized_box_that_maps_back_to_its_pixels(name):
    image = build(name)
    assert image.elements
    for key, placed in image.elements.items():
        left, top, right, bottom = placed.bounds
        assert 0 <= left < right <= image.width and 0 <= top < bottom <= image.height, key
        box = vision.normalized_box(placed.box)  # also validates the range and the ordering
        assert vision.normalized_to_pixels(box, image.width, image.height) == placed.bounds, key
        assert image.box(key) == placed.box


def test_a_shape_box_is_exactly_the_pixels_that_were_drawn():
    for draw in (
        lambda c: c.rect((20, 30, 120, 90), "#FF0000"),
        lambda c: c.rect((20, 30, 120, 90), "#FF0000", radius=20),
        lambda c: c.rect((20, 30, 120, 90), outline="#FF0000", outline_width=5),
        lambda c: c.ellipse((20, 30, 121, 91), "#00FF00"),
        lambda c: c.ellipse((20, 30, 121, 91), outline="#00FF00", outline_width=4),
        lambda c: c.polygon([(50, 20), (120, 200), (10, 180)], "#0000FF"),
        lambda c: c.line((30, 40), (200, 120), "#FF00FF", 5),
        lambda c: c.polyline([(30, 40), (200, 120), (90, 260)], "#FF00FF", 3),
        lambda c: c.text((15, 25), "BOX", scale=3, color="#000000"),
        lambda c: c.text_block((15, 25), "SOME WORDS TO WRAP", max_width=120, scale=2)[0],
    ):
        canvas = si.Canvas(400, 300, "#FFFFFF")
        before = canvas.pixels.copy()
        placed = draw(canvas)
        assert changed_bounds(before, canvas.pixels) == placed.bounds


def test_partly_off_canvas_shapes_are_clipped_and_fully_off_canvas_ones_refused():
    canvas = si.Canvas(300, 300, "#FFFFFF")
    placed = canvas.rect((-50, -50, 40, 40), "#000000")
    assert placed.bounds == (0, 0, 40, 40)
    with pytest.raises(ValueError, match="nothing"):
        canvas.rect((400, 400, 500, 500), "#000000")
    with pytest.raises(ValueError, match="empty or inverted"):
        canvas.rect((50, 50, 50, 90), "#000000")
    with pytest.raises(ValueError, match="needs a fill"):
        canvas.rect((50, 50, 90, 90))
    with pytest.raises(ValueError, match="convex"):
        canvas.polygon([(0, 0), (100, 0), (50, 20), (100, 100), (0, 100)], "#000000")
    with pytest.raises(ValueError, match="width"):
        canvas.line((0, 0), (9, 9), "#000000", 0)


def test_shapes_have_the_expected_area_and_symmetry():
    canvas = si.Canvas(400, 400, "#FFFFFF")
    canvas.ellipse((100, 100, 300, 300), "#000000")
    area = int((canvas.pixels[:, :, 0] == 0).sum())
    assert abs(area - np.pi * 100 * 100) < 250
    assert np.array_equal(canvas.pixels, canvas.pixels[:, ::-1])  # mirror symmetric
    assert np.array_equal(canvas.pixels, canvas.pixels[::-1])


def test_shapes_scene_labels_each_shape_and_boxes_do_not_overlap():
    image = si.shapes_scene(5, count=6)
    shapes = [n for n in image.elements if not n.startswith("label_")]
    assert len(shapes) == 6
    boxes = [image.elements[n].bounds for n in shapes]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
    for name in shapes:
        color_word, kind_word = name.upper().split("_")
        label = next(r for r in image.text_runs if r.placed is image.elements[f"label_{name}"])
        assert label.text == f"{color_word} {kind_word}"
        interior = image.elements[name].center
        assert tuple(image.pixels[interior[1], interior[0]]) in {c for _, c in si._SHAPE_COLORS}


def test_ui_mock_elements_contain_what_their_names_say():
    image = si.ui_mock(1, error="SAVE FAILED", spinner=True, fields=("NAME", "EMAIL"))
    el = image.elements
    assert el["window"].contains(el["title_bar"]) and el["window"].contains(el["button_save"])
    assert el["error_banner"].bounds[1] > el["title_bar"].bounds[3] - 1
    assert (
        tuple(image.pixels[el["error_banner"].bounds[1] + 3, el["error_banner"].bounds[0] + 40])
        == si.RED
    )
    assert el["input_name"].bounds[3] <= el["input_email"].bounds[1]
    assert el["spinner"].width == el["spinner"].height
    runs = {r.text for r in image.text_runs}
    assert {"ORBITAL DESK", "SAVE FAILED", "SAVE", "CANCEL", "NAME", "EMAIL"} <= runs
    plain = si.ui_mock(1)
    assert "error_banner" not in plain.elements and "spinner" not in plain.elements


def test_ui_mock_refuses_layouts_that_would_collide():
    with pytest.raises(ValueError, match="too short"):
        si.ui_mock(0, height=320, fields=("A", "B", "C"))
    with pytest.raises(ValueError, match="at most three"):
        si.ui_mock(0, fields=("A", "B", "C", "D"))


def test_product_shelf_has_a_gold_box_per_stocked_slot_and_a_gap_per_empty_one():
    image = si.product_shelf(3, count=5, gaps=[1, 3])
    assert {n for n in image.elements if n.startswith("product_")} == {
        "product_0",
        "product_2",
        "product_4",
    }
    assert {n for n in image.elements if n.startswith("gap_")} == {"gap_1", "gap_3"}
    for gap in ("gap_1", "gap_3"):
        left, top, right, bottom = image.elements[gap].bounds
        assert len(np.unique(image.pixels[top:bottom, left:right].reshape(-1, 3), axis=0)) == 1
    for name in ("product_0", "product_2", "product_4"):
        left, top, right, bottom = image.elements[name].bounds
        assert len(np.unique(image.pixels[top:bottom, left:right].reshape(-1, 3), axis=0)) > 2
    assert all(
        run.text in si.FICTIONAL_BRANDS or run.text.startswith("$") for run in image.text_runs
    )
    with pytest.raises(ValueError, match="gap"):
        si.product_shelf(0, count=3, gaps=[3])


def test_defects_are_derived_from_changed_pixels_and_lie_on_the_part():
    clean = si.defect_panel(7, defect=None)
    assert "defect" not in clean.elements
    for kind in ("scratch", "dent", "missing_part"):
        image = si.defect_panel(7, defect=kind)
        defect = image.elements["defect"]
        assert image.elements["part"].contains(defect), kind
        # Outside the defect rectangle the picture is identical to the defect-free one.
        left, top, right, bottom = defect.bounds
        mask = np.ones(image.pixels.shape[:2], dtype=bool)
        mask[top:bottom, left:right] = False
        if kind == "missing_part":
            victim = next(f"bolt_{i}" for i in range(4) if f"bolt_{i}" not in image.elements)
            assert victim and f"bolt_{victim[-1]}" in clean.elements
        assert np.array_equal(image.pixels[mask], clean.pixels[mask]), kind
        assert not np.array_equal(
            image.pixels[top:bottom, left:right], clean.pixels[top:bottom, left:right]
        ), kind
        assert changed_bounds(clean.pixels, image.pixels) is not None
    with pytest.raises(ValueError, match="defect must be"):
        si.defect_panel(0, defect="crack")


def test_dent_shades_one_side_lighter_and_the_other_darker():
    canvas = si.Canvas(400, 400, (150, 150, 150))
    site = si.Placed("site", (100, 100, 220, 220), canvas.size)
    placed = canvas.dent(site, strength=80)
    assert site.contains(placed)
    left, right = canvas.pixels[160, 110, 0], canvas.pixels[160, 210, 0]
    assert left > 150 > right


def test_scratch_stays_inside_its_target_and_is_seeded():
    target = None
    results = []
    for seed in (1, 1, 2):
        canvas = si.Canvas(500, 400, (150, 150, 150))
        target = si.Placed("t", (50, 50, 450, 350), canvas.size)
        results.append(canvas.scratch(target, seed))
        assert target.contains(results[-1])
    assert results[0] == results[1] and results[0] != results[2]
    with pytest.raises(ValueError, match="too small"):
        si.Canvas(300, 300).scratch(si.Placed("t", (10, 10, 30, 30), (300, 300)), 0)


def test_missing_part_erases_to_the_background():
    canvas = si.Canvas(300, 300, (90, 90, 90))
    bolt = canvas.ellipse((100, 100, 140, 140), (10, 10, 10), name="bolt")
    hole = canvas.erase(bolt, (90, 90, 90))
    assert hole.bounds == bolt.bounds
    assert np.all(canvas.pixels == 90)


def test_deck_hud_and_schematic_elements():
    hud = si.deck_builder_hud(2, hand=4, health=(25, 100))
    assert [n for n in hud.elements if n.startswith("card_") and n[5:].isdigit()] == [
        f"card_{i}" for i in range(4)
    ]
    runs = {r.text for r in hud.text_runs}
    assert {"HP 25/100", "END TURN"} <= runs
    cards = [hud.elements[f"card_{i}"].bounds for i in range(4)]
    assert all(a[2] <= b[0] for a, b in zip(cards, cards[1:], strict=False))
    with pytest.raises(ValueError, match="hand"):
        si.deck_builder_hud(0, hand=8)

    circuit = si.schematic(3, components=("resistor", "resistor", "lamp"))
    assert {"resistor_1", "resistor_2", "lamp_1", "battery_1"} <= set(circuit.elements)
    assert {r.text for r in circuit.text_runs} == {"R1", "R2", "L1", "B1"}
    with pytest.raises(ValueError, match="components"):
        si.schematic(0, components=("diode",))


def test_wordmark_uses_an_invented_name_and_boxes_emblem_and_text():
    for seed in range(8):
        image = si.wordmark(seed)
        assert image.provenance["parameters"]["brand"] in si.FICTIONAL_BRANDS
        assert image.elements["logo"].contains(image.elements["emblem"])
        assert image.elements["logo"].contains(image.elements["wordmark"])
    assert all(len(b) <= 8 and b.isalpha() and b.isupper() for b in si.FICTIONAL_BRANDS)
    with pytest.raises(ValueError, match="too long"):
        si.wordmark(0, brand="ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    with pytest.raises(ValueError, match="variant"):
        si.wordmark(0, variant=3)


def test_document_page_has_header_body_signature_and_stamp():
    image = si.document_page(2)
    assert {"header", "title", "body", "signature", "stamp"} <= set(image.elements)
    assert image.elements["body"].contains(image.elements["line_0"])
    left, top, right, bottom = image.elements["stamp"].bounds
    assert tuple(image.pixels[top + 1, (left + right) // 2]) == si.RED


# -- perturbations ---------------------------------------------------------------------------


def test_blur_softens_edges_deterministically_and_reports_the_changed_region():
    def make():
        canvas = si.Canvas(300, 300, "#FFFFFF")
        canvas.rect((100, 100, 200, 200), "#000000")
        return canvas

    a, b = make(), make()
    placed = a.blur(3)
    b.blur(3)
    assert np.array_equal(a.pixels, b.pixels)
    assert 90 <= placed.bounds[0] < 100 and 200 < placed.bounds[2] <= 210
    assert 0 < int(a.pixels[100, 98, 0]) < 255  # a soft edge now
    assert a.pixels[150, 150, 0] == 0  # the interior is untouched
    region = make()
    inner = region.blur(3, region=(0, 0, 150, 300))
    assert inner.bounds[2] <= 150
    with pytest.raises(ValueError, match="no pixels"):
        si.Canvas(300, 300, "#FFFFFF").blur(2)  # nothing to soften


def test_noise_is_seeded_bounded_and_confined_to_its_region():
    def make(seed, **kw):
        canvas = si.Canvas(320, 320, (128, 128, 128))
        placed = canvas.noise(10, seed, region=(50, 50, 150, 150), **kw)
        return canvas, placed

    a, placed = make(1)
    b, _ = make(1)
    c, _ = make(2)
    assert np.array_equal(a.pixels, b.pixels) and not np.array_equal(a.pixels, c.pixels)
    assert a.pixels.min() >= 118 and a.pixels.max() <= 138
    assert (50, 50, 150, 150)[0] <= placed.bounds[0] and placed.bounds[2] <= 150
    outside = a.pixels.copy()
    outside[50:150, 50:150] = 128
    assert np.all(outside == 128)
    grey, _ = make(1)
    assert np.all(grey.pixels[:, :, 0] == grey.pixels[:, :, 1])
    colour, _ = make(1, color_noise=True)
    assert not np.all(colour.pixels[:, :, 0] == colour.pixels[:, :, 1])
    with pytest.raises(ValueError, match="amplitude"):
        si.Canvas(300, 300).noise(0, 1)


def test_lighting_directions_and_dim_and_occlusion():
    lit_then_dark = {
        "left": ((10, 150), (290, 150)),
        "right": ((290, 150), (10, 150)),
        "top": ((150, 10), (150, 290)),
        "bottom": ((150, 290), (150, 10)),
    }
    for direction, (bright, dark) in lit_then_dark.items():
        canvas = si.Canvas(300, 300, (128, 128, 128))
        canvas.lighting(60, direction)
        assert canvas.pixels[bright[1], bright[0], 0] > 128 > canvas.pixels[dark[1], dark[0], 0]
    vignette = si.Canvas(300, 300, (128, 128, 128))
    vignette.lighting(50, "vignette")
    assert vignette.pixels[150, 150, 0] > 128 > vignette.pixels[2, 2, 0]
    for bad in (0, 101, -101):
        with pytest.raises(ValueError, match="strength"):
            si.Canvas(300, 300).lighting(bad)
    with pytest.raises(ValueError, match="direction"):
        si.Canvas(300, 300).lighting(10, "sideways")

    dimmed = si.Canvas(300, 300, (200, 100, 50))
    dimmed.dim(50)
    assert tuple(dimmed.pixels[0, 0]) == (100, 50, 25)

    canvas = si.Canvas(300, 300, "#FFFFFF")
    target = canvas.rect((50, 50, 150, 150), "#336699")
    cover = canvas.occlude(target)
    assert cover.bounds == target.bounds


def test_generators_accept_hard_case_options_and_keep_the_gold_box():
    base = si.defect_panel(3, defect="scratch")
    hard = si.defect_panel(
        3, defect="scratch", perturbations=[("blur", 1), ("glare", 40)], occlude="part"
    )
    assert hard.elements["defect"] == base.elements["defect"]  # gold geometry is unchanged
    assert hard.provenance["parameters"]["perturbations"] == [["blur", 1], ["glare", 40]]
    assert hard.provenance["parameters"]["occlude"] == "part"
    assert hard.png_bytes() != base.png_bytes()
    with pytest.raises(ValueError, match="unknown perturbation"):
        si.shapes_scene(0, perturbations=[("sepia", 3)])
    with pytest.raises(ValueError, match="no element"):
        si.shapes_scene(0, occlude="no_such_element")


def test_a_noisy_full_canvas_is_documented_to_be_heavy_but_stays_under_the_cap():
    image = si.shapes_scene(0, perturbations=[("noise", 6)])
    size = len(assert_contract(image))
    assert 0.8 * si.MAX_ASSET_BYTES < size < si.MAX_ASSET_BYTES


# -- frame sequences ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "times",
    [[0.0], [], [1.0, 1.0], [2.0, 1.0], [-1.0, 1.0], [0.0, float("nan")], [0.0, float("inf")]],
)
def test_frame_timestamps_must_be_explicit_finite_and_strictly_increasing(times):
    with pytest.raises(ValueError):
        si.moving_object_frames(times)
    with pytest.raises(ValueError):
        si.appearing_object_frames(times, appear_at=0.5)


def test_moving_object_frames_move_by_elapsed_time_and_have_exact_targets():
    times = [0.0, 0.5, 2.0]
    sequence = si.moving_object_frames(times, seed=1, start=(0.2, 0.5), end=(0.8, 0.5))
    assert [f.timestamp_seconds for f in sequence.frames] == times
    centers = [f.target.center[0] for f in sequence.frames]
    assert centers[0] < centers[1] < centers[2]
    assert centers[1] - centers[0] == pytest.approx((centers[2] - centers[0]) * 0.25, abs=2)
    for frame in sequence.frames:
        assert_contract(frame.image)
        left, top, right, bottom = frame.target.bounds
        assert tuple(frame.image.pixels[top + 20, left + 3]) == (200, 80, 60)
    assert len({f.image.sha256() for f in sequence.frames}) == 3
    # Frames differ only where the object was and is.
    a, b = sequence.frames[0], sequence.frames[1]
    moved = changed_bounds(a.image.pixels, b.image.pixels)
    both = si.Placed.union("both", a.target, b.target).bounds
    assert (
        both[0] <= moved[0] and moved[2] <= both[2] and both[1] <= moved[1] <= moved[3] <= both[3]
    )


def test_appearing_object_frames_have_no_target_until_the_object_arrives_and_after_it_leaves():
    sequence = si.appearing_object_frames(
        [0.0, 1.0, 2.0, 3.0, 4.0], seed=2, appear_at=1.5, disappear_at=3.5
    )
    assert [f.target is not None for f in sequence.frames] == [False, False, True, True, False]
    empty, present = sequence.frames[0], sequence.frames[2]
    assert "object" not in empty.image.elements and "object" in present.image.elements
    assert (
        empty.image.sha256()
        == sequence.frames[1].image.sha256()
        == sequence.frames[4].image.sha256()
    )
    assert present.image.sha256() == sequence.frames[3].image.sha256()
    assert changed_bounds(empty.image.pixels, present.image.pixels) == present.target.bounds
    with pytest.raises(ValueError, match="after appear_at"):
        si.appearing_object_frames([0, 1], appear_at=1.0, disappear_at=1.0)


def test_save_sequence_writes_assets_that_load_frames_accepts(tmp_path):
    recipe = tmp_path / "recipe"
    sequence = si.moving_object_frames([0.0, 0.75, 1.5], seed=3)
    rows = si.save_sequence(sequence, recipe / "assets" / "frames", "belt", root=recipe)
    assert [(t, path) for t, path, _ in rows] == [
        (0.0, "assets/frames/belt-00.png"),
        (0.75, "assets/frames/belt-01.png"),
        (1.5, "assets/frames/belt-02.png"),
    ]
    state, assets = vision.load_frames([(t, p) for t, p, _ in rows], root=recipe)
    assert [row["timestamp_seconds"] for row in state] == [0.0, 0.75, 1.5]
    assert len(assets) == 3
    again = si.save_sequence(sequence, recipe / "assets" / "frames", "belt", root=recipe)
    assert {saved.status for _, _, saved in again} == {"identical"}
    assert sequence.provenance["generator"].endswith("moving_object_frames")
    assert all(
        f.image.provenance["parameters"]["frame_index"] == i for i, f in enumerate(sequence.frames)
    )


# -- the gallery -----------------------------------------------------------------------------


def test_the_committed_gallery_is_exactly_what_the_script_produces(tmp_path):
    out = tmp_path / "assets" / "gallery"
    result = subprocess.run(
        [sys.executable, str(GALLERY / "make_gallery.py"), "--out", str(out)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "created" in result.stdout
    produced = {p.name: p.read_bytes() for p in out.glob("*.png")}
    committed = {p.name: p.read_bytes() for p in GALLERY.glob("*.png")}
    assert produced == committed and len(produced) >= 20
    for name, data in committed.items():
        assert checker.check_image(f"recipes/01-demo/assets/{name}", data) == [], name
    # Running the script over the committed folder verifies instead of rewriting.
    verify = subprocess.run(
        [sys.executable, str(GALLERY / "make_gallery.py"), "--out", str(GALLERY)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "created" not in verify.stdout


def test_the_docs_gallery_references_exist_and_every_committed_image_is_documented():
    doc = (REPO / "docs" / "synthetic-images.md").read_text(encoding="utf-8")
    referenced = set(re.findall(r"assets/synthetic-images/([a-z0-9-]+\.png)", doc))
    committed = {p.name for p in GALLERY.glob("*.png")}
    assert referenced == committed


def test_the_python_examples_in_the_docs_run(tmp_path):
    doc = (REPO / "docs" / "synthetic-images.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", doc, flags=re.S)
    assert blocks
    recipe = tmp_path / "recipes" / "07-demo"
    recipe.mkdir(parents=True)
    for block in blocks:
        namespace = {"__file__": str(recipe / "build_fixtures.py"), "__name__": "docs_example"}
        exec(compile(block, "docs/synthetic-images.md", "exec"), namespace)
        assert namespace["manifest_row"]["origin"] == "generated"
        assert namespace["label"]["box"] == namespace["image"].box("error_banner")
    assert (recipe / "assets" / "save-error.png").exists()
