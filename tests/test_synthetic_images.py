"""jev_cookbook.synthetic_images (#314): the shared generator of synthetic test images.

Most expectations here are worked out by hand from the definitions (a 5x5 ellipse has rows of
3, 5, 5, 5 and 3 pixels; the first splitmix64 outputs for seed 0 are published; a one-pixel
blur spreads 255 - 85 into a 3x3 block of 227) rather than read back from the code. The
``GOLDEN`` tables near the end are the exception: they are regression pins that make an
unintended change to an example scene fail, and they say nothing about whether a scene is right.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import string
import sys
from pathlib import Path

import PIL
import pytest
from PIL import Image, ImageChops, features

from jev_cookbook import synthetic_images as si
from jev_cookbook import vision
from jev_cookbook.fixtures import _assets as assets_module

REPO = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_recipe_assets_for_synth", REPO / "tools" / "check_recipe_assets.py"
)
checker = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = checker
_spec.loader.exec_module(checker)

W, H = 300, 280  # a small canvas just above the API's 280 pixel minimum
BLANK = (250, 250, 245)  # PALETTE["paper"]


def blank() -> si.Canvas:
    return si.Canvas(W, H)


def changed(before: Image.Image, after: Image.Image) -> tuple[int, int, int, int] | None:
    """The bounding box of every pixel that differs: the drawn pixels, found independently."""
    return ImageChops.difference(before.convert("RGB"), after.convert("RGB")).getbbox()


def drawn_pixels(canvas: si.Canvas) -> set[tuple[int, int]]:
    base = Image.new("RGB", canvas.size, canvas.background)
    diff = ImageChops.difference(base, canvas.image)
    data = diff.convert("L").tobytes()
    return {(i % canvas.width, i // canvas.width) for i, v in enumerate(data) if v}


# -- the random stream and names ------------------------------------------------------------


def test_the_stream_is_splitmix64_with_its_published_seed_zero_outputs():
    rng = si.Rng(0)
    assert [rng.u64() for _ in range(3)] == [
        0xE220A8397B1DCDAF,
        0x6E789E6AA1B965F4,
        0x06C45D188009454F,
    ]


def test_the_stream_depends_only_on_the_seed_and_validates_it():
    assert [si.Rng(7).u64() for _ in range(2)] == [si.Rng(7).u64(), si.Rng(7).u64()]
    assert si.Rng(1).u64() != si.Rng(2).u64()
    for bad in (-1, 2**64, 1.5, True, "0"):
        with pytest.raises(ValueError):
            si.Rng(bad)


def test_below_and_between_stay_in_range_and_reach_every_value():
    rng = si.Rng(3)
    seen = {rng.below(5) for _ in range(200)}
    assert seen == {0, 1, 2, 3, 4}
    assert {rng.between(-2, 1) for _ in range(200)} == {-2, -1, 0, 1}
    with pytest.raises(ValueError):
        rng.below(0)
    with pytest.raises(ValueError):
        rng.between(3, 2)
    with pytest.raises(ValueError):
        rng.choice([])


def test_bytes_are_the_stream_in_little_endian_order():
    # 0xE220A8397B1DCDAF written least significant byte first
    assert si.Rng(0).bytes(10) == bytes.fromhex("afcd1d7b39a820e2") + bytes.fromhex("f465")


def raw_names():
    """Every string the generator's syllable table can spell, before the deny filter."""
    import itertools

    syllables = [onset + vowel for onset in si._ONSETS for vowel in si._VOWELS]
    for count in (2, 3):
        for chain in itertools.product(syllables, repeat=count):
            stem = "".join(chain)
            for coda in si._CODAS:
                yield (stem + coda).upper()


def test_no_name_the_generator_can_return_contains_a_denied_word():
    # The generator is a loop over draws from a finite table that returns the first clean one, so
    # whatever seed it is given (all 2**64 of them) the result is one of the clean strings of
    # this exhaustively enumerated space. The enumeration is checked independently of the
    # module's own filter, by a regular expression built from the published list.
    pattern = re.compile("|".join(si._DENY))
    total = rejected = 0
    clean = set()
    for name in raw_names():
        total += 1
        if pattern.search(name):
            rejected += 1
        else:
            clean.add(name)
    assert total == (80**2 + 80**3) * 6  # 3,110,400 strings
    assert (
        0 < rejected < total // 20
    )  # the list bites, and is small enough not to hollow out the space
    assert all(not pattern.search(name) for name in clean)
    for seed in range(0, 250_000):
        name = si.fictional_name(seed)
        assert name in clean, (seed, name)


def first_draw(seed: int) -> str:
    """What fictional_name returned before the deny filter existed: the first draw of the seeded
    stream, built from the same syllable table (so no offensive word is written out here)."""
    rng = si.Rng(seed)
    syllables = [rng.choice(si._ONSETS) + rng.choice(si._VOWELS) for _ in range(rng.between(2, 3))]
    return ("".join(syllables) + rng.choice(si._CODAS)).upper()


def test_the_names_reviewers_found_are_gone_and_every_other_name_is_unchanged():
    # Seeds 1996, 395 and 159 were found by reviewers: their first draws spell offensive words.
    # Seeds 1996 (BONER) and 159 (FAGIPON) are each caught by one entry of the deny-list. Seed 395
    # (NIGANUS) is caught by two, ANUS and NIG, so removing either one alone still rejects it. Each
    # entry is pinned on its own by the single-catch tests at the end of this file.
    caught = {
        seed: {word for word in si._DENY if word in first_draw(seed)} for seed in (1996, 395, 159)
    }
    assert caught == {1996: {"BONER"}, 395: {"ANUS", "NIG"}, 159: {"FAG"}}
    for seed in (1996, 395, 159):
        assert not si._is_clean(first_draw(seed)), seed
        assert si.fictional_name(seed) != first_draw(seed), seed
        assert re.fullmatch(r"[A-Z]{4,10}", si.fictional_name(seed))
        assert not any(word in si.fictional_name(seed) for word in si._DENY)
    # a seed whose first draw is clean maps to the same name as before (the gallery depends on it)
    assert [si.fictional_name(seed) for seed in (1, 2, 3, 4)] == [
        "MAREBAM",
        "DEGUM",
        "PUZEMIR",
        "BIVEN",
    ]


def test_the_deny_list_is_short_plain_ascii_and_upper_case():
    assert 5 <= len(si._DENY) <= 20
    assert all(word.isascii() and word.isupper() and word.isalpha() for word in si._DENY)
    assert len(set(si._DENY)) == len(si._DENY)


def test_fictional_names_are_deterministic_upper_case_and_varied():
    assert si.fictional_name(5) == si.fictional_name(5)
    names = {si.fictional_name(seed) for seed in range(30)}
    assert len(names) >= 20
    assert all(re.fullmatch(r"[A-Z]{4,10}", name) for name in names)


# -- the font ---------------------------------------------------------------------------------


def test_every_glyph_is_five_by_seven_and_the_fold_is_documented():
    assert all(len(rows) == 7 for rows in (g.split("/") for g in si._GLYPH_SOURCE.values()))
    assert all(len(r) == 5 for g in si._GLYPH_SOURCE.values() for r in g.split("/"))
    assert si.text_width("A", 1) == 5
    assert si.text_width("HH", 2) == 22  # (2 * 6 - 1) * 2
    c = blank()
    assert c.text(10, 10, "ab", "ink", 1).attrs["text"] == "AB"


def test_text_draws_the_hand_written_pixels_of_an_h():
    c = blank()
    c.text(10, 10, "H", (0, 0, 0), 1)
    ink = (0, 0, 0)
    px = c.image.load()
    # H is #...# on rows 0-2 and 4-6 and ##### on row 3
    assert [px[10 + x, 10] for x in range(5)] == [ink, BLANK, BLANK, BLANK, ink]
    assert [px[10 + x, 13] for x in range(5)] == [ink] * 5
    assert [px[10 + x, 16] for x in range(5)] == [ink, BLANK, BLANK, BLANK, ink]
    assert px[9, 13] == BLANK and px[15, 13] == BLANK and px[12, 17] == BLANK


def test_scale_multiplies_pixels_and_the_line_box_is_the_cell_box():
    c = blank()
    box = c.text(10, 20, "HH", "ink", 2)
    assert box.pixels == (10, 20, 32, 34)
    assert changed(Image.new("RGB", c.size, BLANK), c.image) == (
        10,
        20,
        32,
        34,
    )  # H touches all sides


def test_text_ink_stays_inside_the_returned_box_for_every_character():
    for char in si.SUPPORTED_CHARACTERS:
        c = blank()
        if char == " ":
            # three spaces have no ink at all, so they are refused rather than drawn as an empty box
            with pytest.raises(ValueError, match="no visible"):
                c.text(30, 40, char * 3, "ink", 3)
            continue
        box = c.text(30, 40, char * 3, "ink", 3)
        ink = changed(Image.new("RGB", c.size, c.background), c.image)
        assert ink is not None
        assert box.left <= ink[0] and ink[2] <= box.right
        assert box.top <= ink[1] and ink[3] <= box.bottom


def test_a_character_without_a_glyph_is_refused_not_drawn_blank():
    with pytest.raises(ValueError, match="no glyph"):
        blank().text(0, 0, "caf\u00e9")  # LATIN SMALL LETTER E WITH ACUTE
    with pytest.raises(ValueError):
        blank().text(0, 0, "")
    with pytest.raises(ValueError):
        blank().text(0, 0, "A", "ink", 0)


def test_fit_scale_picks_the_largest_scale_that_fits():
    assert si.fit_scale("AB", 22, 14) == 2  # width 22 at scale 2, height 14
    assert si.fit_scale("AB", 21, 14) == 1
    assert si.fit_scale("AB", 1000, 1000, maximum=3) == 3
    with pytest.raises(ValueError):
        si.fit_scale("AB", 10, 7)


def test_text_block_lines_are_ten_rows_apart_at_leading_three():
    c = blank()
    block = c.text_block(10, 20, ["ABC", "WXYZ"], "ink", 1, name="note")
    assert [p.pixels for p in block.parts] == [(10, 20, 27, 27), (10, 30, 33, 37)]
    assert block.pixels == (10, 20, 33, 37)
    assert set(c.objects) == {"note", "note.line0", "note.line1"}


def test_text_block_skips_a_blank_line_but_keeps_its_pitch():
    c = blank()
    block = c.text_block(10, 10, ["A", " ", "B"], "ink", 2, name="b")
    # the pitch is (7 + 3) * 2 = 20, and the blank line still uses up its row, so "B" starts at 50
    assert block.parts[0].top == 10
    assert block.parts[1].top == 10 + 2 * 20
    assert [p.name for p in block.parts] == ["b.line0", "b.line2"]
    assert block.attrs["lines"] == 3  # the blank line is counted in the input
    rows = c.image.crop((0, 30, c.width, 50))  # the rows of the blank line
    assert changed(Image.new("RGB", rows.size, c.background), rows) is None
    assert block.top == min(p.top for p in block.parts)
    assert block.bottom == max(p.bottom for p in block.parts)
    # a blank first or last line is skipped too, and the surviving line keeps its input index
    lone = blank().text_block(10, 10, ["  ", "A", " "], name="b")
    assert [p.name for p in lone.parts] == ["b.line1"]
    assert lone.parts[0].top == 10 + 20
    with pytest.raises(ValueError):
        blank().text_block(10, 10, ["A", ""])  # an empty string is not a blank line


# -- the canvas and the shapes ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "ok"),
    [((280, 280), True), ((279, 300), False), ((300, 1569), False), ((1568, 1568), True)],
)
def test_the_canvas_enforces_the_api_size(size, ok):
    if ok:
        assert si.Canvas(*size).size == size
    else:
        with pytest.raises(ValueError):
            si.Canvas(*size)


def test_1568_squared_is_exactly_the_maximum_area_and_a_float_is_not_a_size():
    assert 1568 * 1568 == vision.IMAGE_LIMITS["max_area"]
    with pytest.raises(ValueError):
        si.Canvas(280.0, 280)


def test_rect_returns_its_exact_pixels_and_normalized_box():
    c = blank()
    box = c.rect(10, 20, 30, 40, (0, 0, 0), name="r")
    assert box.pixels == (10, 20, 40, 60)
    assert box.box == {"top": 20 / 280, "bottom": 60 / 280, "left": 10 / 300, "right": 40 / 300}
    assert changed(Image.new("RGB", c.size, BLANK), c.image) == (10, 20, 40, 60)
    assert c.objects["r"] is box
    assert box.center == (25, 40)
    assert box.label() == {"present": True, "box": box.box}


def test_rect_outline_is_inside_the_box_and_fill_is_inset():
    c = blank()
    c.rect(10, 10, 20, 20, (255, 255, 255), outline=(0, 0, 0), outline_width=2)
    px = c.image.load()
    assert px[10, 10] == px[11, 15] == px[28, 15] == (0, 0, 0)
    assert px[12, 12] == px[27, 15] == px[15, 27] == (255, 255, 255)
    assert px[30, 15] == BLANK


def test_a_shape_is_clipped_to_the_canvas_and_one_fully_outside_is_refused():
    c = blank()
    assert c.rect(280, 270, 50, 50, "ink").pixels == (280, 270, 300, 280)
    with pytest.raises(ValueError, match="outside"):
        c.rect(300, 10, 5, 5, "ink")
    with pytest.raises(ValueError):
        c.rect(0, 0, 0, 5, "ink")
    with pytest.raises(ValueError):
        c.rect(0, 0, 5, 5)


def test_a_name_can_be_used_once():
    c = blank()
    c.rect(0, 0, 5, 5, "ink", name="a")
    with pytest.raises(ValueError, match="already used"):
        c.rect(10, 0, 5, 5, "ink", name="a")


def test_a_5x5_ellipse_has_rows_of_3_5_5_5_3_pixels():
    # pixel centres inside (dx/2.5)^2 + (dy/2.5)^2 <= 1: row 0 holds 3, rows 1-3 hold 5
    c = blank()
    box = c.ellipse(100, 100, 5, 5, (0, 0, 0))
    rows = {}
    for _x, y in drawn_pixels(c):
        rows[y] = rows.get(y, 0) + 1
    assert [rows[y] for y in range(100, 105)] == [3, 5, 5, 5, 3]
    assert box.pixels == (100, 100, 105, 105)
    assert (100, 100) not in drawn_pixels(c) and (101, 100) in drawn_pixels(c)


def test_ellipse_outline_leaves_a_ring():
    c = blank()
    c.ellipse(100, 100, 40, 40, (255, 255, 255), outline=(0, 0, 0), outline_width=3)
    px = c.image.load()
    assert px[120, 100] == (0, 0, 0) and px[120, 102] == (0, 0, 0)
    assert px[120, 103] == (255, 255, 255) and px[120, 120] == (255, 255, 255)
    assert px[100, 100] == BLANK  # the corner is outside the ellipse


def test_triangle_up_5x3_has_rows_of_1_3_5_pixels():
    c = blank()
    box = c.triangle(50, 50, 5, 3, (0, 0, 0))
    assert drawn_pixels(c) == {
        (52, 50),
        (51, 51),
        (52, 51),
        (53, 51),
        *((x, 52) for x in range(50, 55)),
    }
    assert box.pixels == (50, 50, 55, 53)


def test_triangle_directions_put_the_apex_where_named():
    right = blank()
    right.triangle(10, 10, 3, 5, "ink", direction="right")  # 1, 3, 5 pixels per column
    assert drawn_pixels(right) == {
        (12, 12),
        (11, 11),
        (11, 12),
        (11, 13),
        *((10, y) for y in range(10, 15)),
    }
    down = blank()
    down.triangle(10, 10, 5, 3, "ink", direction="down")
    assert (12, 12) in drawn_pixels(down) and (10, 12) not in drawn_pixels(down)
    assert (10, 10) in drawn_pixels(down)
    with pytest.raises(ValueError):
        blank().triangle(0, 0, 5, 3, "ink", direction="sideways")


def test_a_triangle_box_is_the_drawn_extent_not_the_requested_one():
    # at 4x4 the apex row (half-width 0.25 pixels) holds no pixel centre, so the first row is empty
    c = blank()
    box = c.triangle(10, 10, 4, 4, "ink")
    assert box.pixels == (10, 11, 14, 14)


def test_line_horizontal_diagonal_and_thick_boxes():
    c = blank()
    assert c.line(10, 20, 19, 20, "ink").pixels == (10, 20, 20, 21)
    assert c.line(10, 30, 19, 30, "ink", 3).pixels == (9, 29, 21, 32)  # brush offset (3 - 1) // 2
    d = blank()
    assert d.line(10, 10, 14, 14, "ink").pixels == (10, 10, 15, 15)
    assert drawn_pixels(d) == {(10 + i, 10 + i) for i in range(5)}


def test_bresenham_ties_round_up_as_y_equals_x_over_2():
    c = blank()
    c.line(0, 0, 4, 2, "ink")
    assert drawn_pixels(c) == {(0, 0), (1, 1), (2, 1), (3, 2), (4, 2)}
    reverse = blank()
    reverse.line(4, 2, 0, 0, "ink")
    assert len(drawn_pixels(reverse)) == 5


def test_a_line_leaving_the_canvas_is_clipped_to_it():
    c = blank()
    box = c.line(-10, 5, 20, 5, "ink")
    assert box.pixels == (0, 5, 21, 6)


def test_labelled_objects_report_the_shape_box_and_centre_the_label():
    c = blank()
    obj = c.labelled_object(40, 50, 100, 40, "blue", name="gate", label="OK", shape="rect")
    assert obj.pixels == (40, 50, 140, 90)
    label = obj.parts[1]
    assert label.attrs["text"] == "OK"
    assert label.pixels == (79, 63, 101, 77)  # x 40 + 39, y 50 + 13, a 22 x 14 label
    assert obj.attrs["label"] == "OK"
    with pytest.raises(ValueError):
        c.labelled_object(0, 0, 10, 10, "red", name="x", shape="hexagon")


def test_a_label_too_big_for_its_shape_is_an_error():
    with pytest.raises(ValueError, match="does not fit"):
        blank().labelled_object(0, 0, 20, 20, "red", name="x", label="LONG LABEL")


@pytest.mark.parametrize("kind", ["resistor", "capacitor", "valve", "ground"])
def test_a_symbol_box_is_exactly_the_pixels_it_changed(kind):
    c = blank()
    drawn = c.schematic_symbol(20, 30, 60, 40, kind)
    assert changed(Image.new("RGB", c.size, BLANK), c.image) == drawn.pixels


def test_stamp_and_signature_boxes_are_exact_too():
    c = blank()
    stamp = c.stamp(20, 20, 90, 90, "OK", paper=BLANK)
    assert changed(Image.new("RGB", c.size, BLANK), c.image) == stamp.pixels
    d = blank()
    sig = d.signature(150, 30, 100, 40)
    assert changed(Image.new("RGB", d.size, BLANK), d.image) == sig.pixels


def test_a_signature_is_seeded_and_stays_in_its_area():
    shapes = set()
    for seed in range(5):
        c = si.Canvas(W, H, seed=seed)
        sig = c.signature(150, 30, 100, 40)
        assert 150 <= sig.left and sig.right <= 250 and 30 <= sig.top and sig.bottom <= 70
        shapes.add(sig.pixels)
        again = si.Canvas(W, H, seed=seed)
        assert again.signature(150, 30, 100, 40).pixels == sig.pixels
    assert len(shapes) > 1


# -- gold geometry agrees with jev_cookbook.vision --------------------------------------------


def test_normalized_boxes_round_trip_through_the_vision_helpers():
    c = blank()
    drawn = c.rect(13, 27, 111, 53, "ink")
    assert vision.normalized_to_pixels(drawn.box, W, H) == drawn.pixels
    assert vision.gold_box(drawn.label()) == drawn.box
    assert vision.gold_box(si.absent_label()) is None
    assert vision.crop_box(c.image, drawn.box).size == (111, 53)


def test_a_drawn_rectangle_must_be_non_empty_and_inside_its_canvas():
    with pytest.raises(ValueError):
        si.Drawn("x", "rect", 5, 5, 5, 9, (300, 280))
    with pytest.raises(ValueError):
        si.Drawn("x", "rect", 0, 0, 301, 9, (300, 280))


def test_grid_positions_walk_rows_left_to_right():
    assert si.grid_positions(10, 20, 3, 2, 50, 40, 5) == [
        (10, 20),
        (65, 20),
        (120, 20),
        (10, 65),
        (65, 65),
        (120, 65),
    ]
    with pytest.raises(ValueError):
        si.grid_positions(0, 0, 0, 1, 5, 5)


# -- the UI mock -------------------------------------------------------------------------------


def test_window_has_a_title_bar_controls_and_a_content_area():
    c = blank()
    win = c.window(20, 20, 260, 200, "DEMO", name="w")
    assert win.pixels == (20, 20, 280, 220)
    assert win.attrs["title"] == "DEMO"
    assert win.attrs["content"] == (21, 46, 279, 219)  # below the 26 pixel bar, inside the frame
    assert c.objects["w.title_bar"].pixels == (20, 20, 280, 46)
    assert c.objects["w.close"].pixels == (258, 25, 274, 41)  # a 16 pixel square, 5 below the top
    assert c.image.getpixel((22, 22)) == si.PALETTE["dark"]
    with pytest.raises(ValueError):
        c.window(0, 0, 100, 100, "TOO SMALL")
    with pytest.raises(ValueError, match="title"):
        blank().window(20, 20, 200, 100, "A VERY LONG WINDOW TITLE")


def test_button_styles_and_centred_label():
    c = blank()
    primary = c.button(20, 20, 120, 40, "GO", name="b")
    assert primary.pixels == (20, 20, 140, 60)
    assert primary.attrs == {"style": "primary", "label": "GO"}
    assert c.image.getpixel((22, 22)) == si.PALETTE["blue"]
    c.button(20, 80, 120, 40, "GO", style="disabled")
    assert c.image.getpixel((22, 82)) == si.PALETTE["grey"]
    with pytest.raises(ValueError, match="does not fit"):
        c.button(20, 140, 40, 40, "TOO WIDE")
    with pytest.raises(ValueError):
        c.button(20, 140, 120, 40, "OK", style="fancy")


def test_text_input_shows_value_mask_or_placeholder_and_flags_state():
    c = blank()
    masked = c.text_input(20, 40, 200, 34, "SECRET", masked=True, name="pw", label="PASSWORD")
    assert masked.attrs["value"] == "******"
    assert masked.pixels == (20, 40, 220, 74)
    # the label sits 6 pixels above the field, 14 tall: y 20..34, 94 wide, outside the box
    assert c.objects["pw.label"].pixels == (20, 20, 114, 34)
    bad = c.text_input(20, 100, 200, 34, invalid=True, placeholder="NAME")
    assert c.image.getpixel((20, 100)) == si.PALETTE["red"]
    assert bad.attrs["placeholder"] == "NAME" and bad.attrs["value"] == ""
    with pytest.raises(ValueError, match="does not fit"):
        c.text_input(20, 160, 60, 34, "WAY TOO LONG FOR IT")


def test_error_banner_levels_and_dialog_with_backdrop_dim():
    c = blank()
    banner = c.error_banner(10, 10, 280, 32, "FAILED", name="e")
    assert banner.attrs == {"level": "error", "message": "FAILED"}
    assert c.image.getpixel((10, 10)) == si.PALETTE["red"]
    assert c.image.getpixel((14, 14)) == (252, 228, 228)
    with pytest.raises(ValueError):
        c.error_banner(10, 60, 100, 32, "A MESSAGE THAT IS FAR TOO LONG")
    d = blank()
    dialog = d.dialog(
        40, 40, 220, 180, "NOTICE", ["BODY"], buttons=("OK",), dim_backdrop=50, name="d"
    )
    # the backdrop is the canvas colour at 50 percent, each channel rounded half up: 125, 125, 122.5 -> 123
    assert d.image.getpixel((0, 0)) == (125, 125, 123)
    assert dialog.pixels == (40, 40, 260, 220)
    ok = d.objects["d.button0"]
    assert (ok.right, ok.bottom, ok.width, ok.height) == (244, 206, 80, 30)
    with pytest.raises(ValueError, match="do not fit"):
        blank().dialog(10, 10, 100, 60, "T", ["A LINE"], buttons=("OK",))


def test_mix_rounds_half_up_with_hand_computed_values():
    # 40 * 43 + 200 * 57 = 13120 -> +50 -> 131; 100 * 43 + 203 * 57 = 15871 -> 159; 220 * 43 + 210 * 57 = 21430 -> 214
    assert si.mix((40, 100, 220), (200, 203, 210), 57) == (131, 159, 214)
    assert si.mix("black", "white", 0) == (0, 0, 0)
    assert si.mix("black", "white", 100) == (255, 255, 255)
    assert si.mix((0, 0, 0), (255, 255, 255), 50) == (128, 128, 128)  # 127.5 up
    with pytest.raises(ValueError):
        si.mix("black", "white", 101)
    with pytest.raises(ValueError):
        si.mix("black", (1, 2), 5)


def test_spinner_box_is_the_union_of_eight_spokes_and_phase_moves_the_dark_one():
    # radius 20: inner 8, thickness 3, brush offset 1; the up spoke runs from y 92 to 80, the left
    # spoke ends at x 80 and the right and down spokes at 120, so the box is (79, 79, 122, 122)
    c = blank()
    s = c.spinner(100, 100, 20, name="s")
    assert s.pixels == (79, 79, 122, 122)
    assert c.image.getpixel((100, 85)) == si.PALETTE["blue"]  # spoke 0 is darkest at phase 0
    assert c.image.getpixel((100, 115)) == (131, 159, 214)  # the down spoke, 4 steps on: 57 percent
    d = blank()
    d.spinner(100, 100, 20, phase=4)
    assert d.image.getpixel((100, 115)) == si.PALETTE["blue"]
    assert d.image.getpixel((100, 85)) == (131, 159, 214)
    assert changed(Image.new("RGB", c.size, BLANK), d.image) == s.pixels


def test_bar_fills_floor_fraction_times_the_interior():
    c = blank()
    bar = c.bar(10, 10, 102, 12, 0.5, name="hp")
    assert bar.pixels == (10, 10, 112, 22)
    assert bar.attrs["filled_pixels"] == 50
    assert c.image.getpixel((60, 15)) == si.PALETTE["green"]
    assert c.image.getpixel((61, 15)) == si.PALETTE["dark"]
    assert blank().bar(10, 10, 102, 12, 1).attrs["filled_pixels"] == 100
    with pytest.raises(ValueError):
        blank().bar(10, 10, 102, 12, 1.5)


# -- the logo ------------------------------------------------------------------------------------


def test_a_wordmark_is_deterministic_and_each_seed_looks_different():
    a, b = blank(), blank()
    a.wordmark(20, 20, 220, 60, style_seed=4, name="m")
    b.wordmark(20, 20, 220, 60, style_seed=4)
    assert a.image.tobytes() == b.image.tobytes()
    seen = set()
    for seed in range(8):
        c = blank()
        c.wordmark(20, 20, 220, 60, style_seed=seed)
        seen.add(c.image.tobytes())
    assert len(seen) == 8


def test_wordmark_overrides_make_an_off_brand_variant_and_report_what_was_used():
    c = blank()
    mark = c.wordmark(20, 20, 220, 60, style_seed=1, text="Zorvex", emblem="disc", colour="red")
    assert mark.attrs == {"text": "ZORVEX", "emblem": "disc", "colour": [210, 50, 50]}
    emblem, text = mark.parts
    assert emblem.pixels == (20, 20, 80, 80)  # a 60 pixel disc
    assert text.left == 20 + 60 + 15  # the gap is h // 4 = 15
    assert changed(Image.new("RGB", c.size, BLANK), c.image) == mark.pixels
    with pytest.raises(ValueError):
        blank().wordmark(20, 20, 100, 60, text="A MUCH TOO LONG NAME")
    with pytest.raises(ValueError):
        blank().wordmark(20, 20, 220, 60, emblem="star")


@pytest.mark.parametrize("emblem", ["disc", "ring", "triangle", "bars", "stack"])
def test_every_emblem_stays_inside_its_square(emblem):
    c = blank()
    mark = c.wordmark(20, 20, 220, 60, emblem=emblem, text="ABC")
    assert changed(Image.new("RGB", c.size, BLANK), c.image) == mark.pixels
    first = mark.parts[0]
    assert 20 <= first.left and first.right <= 80 and 20 <= first.top and first.bottom <= 80


# -- defects ----------------------------------------------------------------------------------


def test_scratch_with_explicit_ends_has_the_hand_computed_box():
    c = blank()
    c.rect(40, 40, 100, 100, (120, 120, 120), name="part")
    scratch = c.scratch("part", start=(50, 60), end=(100, 90), colour=(255, 255, 255), name="s")
    assert scratch.pixels == (50, 60, 101, 91)
    assert scratch.kind == "scratch" and scratch.attrs["start"] == [50, 60]
    assert c.image.getpixel((50, 60)) == (255, 255, 255)
    assert c.image.getpixel((100, 90)) == (255, 255, 255)
    with pytest.raises(ValueError, match="inside"):
        c.scratch("part", start=(40, 60), end=(100, 90))


def test_a_seeded_scratch_stays_inside_its_target_and_is_reproducible():
    for seed in range(12):
        c = si.Canvas(W, H, seed=seed)
        target = c.rect(40, 40, 100, 100, (120, 120, 120))
        scratch = c.scratch(target, colour="white")
        assert target.left <= scratch.left and scratch.right <= target.right
        assert target.top <= scratch.top and scratch.bottom <= target.bottom
        assert (
            scratch.width >= 100 - 2 * 10 - 2 * 30 - 1
        )  # start in the left 40%, end in the right 40%
        twin = si.Canvas(W, H, seed=seed)
        twin.rect(40, 40, 100, 100, (120, 120, 120))
        assert twin.scratch(target, colour="white").pixels == scratch.pixels
    with pytest.raises(ValueError):
        blank().scratch((0, 0, 30, 30))


def test_a_dent_darkens_exactly_four_centre_pixels_to_100_and_reports_what_changed():
    # 200 grey, depth 50 percent, 40 x 40 ellipse (size_percent 40 of a 100 pixel target). Each
    # of the four centre pixels has (2x+1-40)^2 = (2y+1-40)^2 = 1, so with q = 40^4 the new value is
    # (200 * (100q - 50 * (q - 3200)) + 50q) // 100q = 100 (100.6 rounded down).
    c = si.Canvas(W, H, (200, 200, 200), seed=2)
    target = c.rect(50, 50, 100, 100, (200, 200, 200))
    dent = c.dent(target, depth_percent=50, size_percent=40, name="d")
    lows = [
        (x, y) for x in range(W) for y in range(H) if c.image.getpixel((x, y)) == (100, 100, 100)
    ]
    assert len(lows) == 4
    xs, ys = sorted({x for x, _ in lows}), sorted({y for _, y in lows})
    assert xs[1] - xs[0] == 1 and ys[1] - ys[0] == 1
    assert target.left <= dent.left and dent.right <= target.right
    assert target.top <= dent.top and dent.bottom <= target.bottom
    assert changed(Image.new("RGB", c.size, (200, 200, 200)), c.image) == dent.pixels
    values = c.image.tobytes()
    assert min(values) == 100 and max(values) == 200  # darker only, never lighter


def test_a_dent_that_changes_nothing_is_refused():
    c = si.Canvas(W, H, (0, 0, 0))
    with pytest.raises(ValueError, match="changed no pixel"):
        c.dent((0, 0, 100, 100), depth_percent=50)


def test_missing_part_paints_the_part_out_and_reports_where_it_was():
    c = blank()
    c.ellipse(100, 100, 24, 24, "mid", outline="ink", name="screw")
    gone = c.missing_part("screw", name="gap")
    assert gone.pixels == (100, 100, 124, 124)
    assert gone.attrs["part"] == "screw" and gone.kind == "missing-part"
    assert "screw" not in c.objects and "gap" in c.objects
    assert changed(Image.new("RGB", c.size, BLANK), c.image) is None
    with pytest.raises(ValueError, match="nothing"):
        c.missing_part((10, 10, 30, 30))


# -- perturbations ----------------------------------------------------------------------------


def test_a_radius_one_blur_spreads_one_black_pixel_into_a_3x3_block_of_227():
    # horizontal pass: (255 + 255 + 0 + 1) // 3 = 170 on x 149..151; vertical pass over
    # (255, 170, 255) and its neighbours: (255 + 255 + 170 + 1) // 3 = 227 on y 139..141
    c = si.Canvas(W, H, (255, 255, 255))
    c.image.putpixel((150, 140), (0, 0, 0))
    region = c.blur(1)
    assert region.pixels == (0, 0, W, H)
    px = c.image.load()
    block = {(x, y) for x in range(149, 152) for y in range(139, 142)}
    assert {(x, y) for x in range(W) for y in range(H) if px[x, y] != (255, 255, 255)} == block
    assert all(px[x, y] == (227, 227, 227) for x, y in block)


def test_blur_clamps_at_the_region_edge():
    c = si.Canvas(W, H, (255, 255, 255))
    for y in range(H):
        c.image.putpixel((0, y), (0, 0, 0))
    c.blur(1)
    # x 0: (0 + 0 + 255 + 1) // 3 = 85 (the missing left neighbour repeats x 0); x 1: 511 // 3 = 170
    assert [c.image.getpixel((x, 100))[0] for x in range(4)] == [85, 170, 255, 255]


def test_blur_only_touches_its_region_and_checks_its_arguments():
    c = si.Canvas(W, H, (255, 255, 255))
    c.image.putpixel((150, 140), (0, 0, 0))
    c.image.putpixel((10, 10), (0, 0, 0))
    region = c.blur(2, region=(100, 100, 200, 200))
    assert region.pixels == (100, 100, 200, 200)
    assert c.image.getpixel((10, 10)) == (0, 0, 0)
    # radius 2: (4 * 255 + 0 + 2) // 5 = 204 across, then (4 * 255 + 204 + 2) // 5 = 245 down
    assert c.image.getpixel((150, 140)) == (245, 245, 245)
    with pytest.raises(ValueError):
        c.blur(0)
    with pytest.raises(ValueError):
        c.blur(21)
    with pytest.raises(ValueError):
        c.blur(1, region=(0, 0, W + 1, H))


def test_noise_follows_the_published_splitmix_stream():
    # the first stream bytes for seed 0 are af cd 1d 7b; each mod 11 (amount 5) minus 5 is added
    # to a 128 grey: 175 % 11 = 10 -> 133, 205 % 11 = 7 -> 130, 29 % 11 = 7 -> 130, 123 % 11 = 2 -> 125
    c = si.Canvas(W, H, (128, 128, 128), seed=0)
    c.noise(5)
    assert [c.image.getpixel((x, 0)) for x in range(4)] == [
        (133, 133, 133),
        (130, 130, 130),
        (130, 130, 130),
        (125, 125, 125),
    ]
    values = c.image.tobytes()
    assert min(values) >= 123 and max(values) <= 133


def test_colour_noise_differs_per_channel_and_noise_clamps():
    c = si.Canvas(W, H, (128, 128, 128), seed=0)
    c.noise(5, grey=False)
    assert c.image.getpixel((0, 0)) == (133, 130, 130)  # bytes af cd 1d
    white = si.Canvas(W, H, (255, 255, 255), seed=0)
    white.noise(100)
    assert max(white.image.tobytes()) == 255
    with pytest.raises(ValueError):
        white.noise(128)


def test_lighting_scales_brightness_with_half_up_rounding():
    c = si.Canvas(W, H, (101, 201, 255))
    region = c.lighting(50)
    assert region.pixels == (0, 0, W, H)
    assert c.image.getpixel((5, 5)) == (51, 101, 128)  # 5100 // 100, 10100 // 100, 12800 // 100


def test_a_lighting_gradient_runs_left_to_right_around_the_brightness():
    # region 100 wide, 100 percent, gradient 40: column 0 gets 100 + (40 * -99) // 200 = 80
    # (floor of -19.8 is -20) and column 99 gets 100 + (40 * 99) // 200 = 119
    c = si.Canvas(W, H, (200, 200, 200))
    c.lighting(100, gradient_percent=40, region=(0, 0, 100, 280))
    assert c.image.getpixel((0, 5)) == (160, 160, 160)
    assert c.image.getpixel((99, 5)) == (238, 238, 238)  # (200 * 119 + 50) // 100
    assert c.image.getpixel((100, 5)) == (200, 200, 200)


@pytest.mark.parametrize(
    ("side", "fraction", "expected"),
    [
        ("left", 0.25, (50, 30, 75, 70)),
        ("right", 0.5, (100, 30, 150, 70)),
        ("top", 0.25, (50, 30, 150, 40)),
        ("bottom", 0.5, (50, 50, 150, 70)),
    ],
)
def test_occlusion_covers_the_stated_fraction_from_the_named_side(side, fraction, expected):
    c = blank()
    c.rect(50, 30, 100, 40, (0, 120, 0), name="target")
    patch = c.occlude("target", fraction=fraction, side=side, name="o")
    assert patch.pixels == expected
    assert patch.kind == "occlusion" and patch.attrs["side"] == side
    assert c.objects["target"].pixels == (50, 30, 150, 70)  # the target keeps its own gold box


def test_occlusion_rounds_half_up_and_refuses_nothing_or_bad_sides():
    c = blank()
    c.rect(50, 30, 25, 40, (0, 120, 0), name="narrow")
    assert c.occlude("narrow", fraction=0.5, side="left").width == 13  # 12.5 rounds up
    with pytest.raises(ValueError):
        c.occlude("narrow", fraction=0.0)
    with pytest.raises(ValueError):
        c.occlude("narrow", side="middle")
    with pytest.raises(ValueError):
        c.occlude("missing")


# -- frame sequences ----------------------------------------------------------------------------


def test_interpolate_is_exact_clamped_and_rounds_half_up():
    assert si.interpolate(20, 320, 1, 0, 4) == 95
    assert si.interpolate(20, 320, 2.5, 0, 4) == 208  # 187.5 rounds up to 188
    assert si.interpolate(20, 320, -3, 0, 4) == 20
    assert si.interpolate(20, 320, 9, 0, 4) == 320
    assert si.interpolate(100, 40, 1, 0, 2) == 70  # downwards: 100 - 30
    assert si.interpolate(0, 1, 0.1 + 0.2, 0, 1) == 0  # 0.30000000000000004 is still below .5
    with pytest.raises(ValueError):
        si.interpolate(0, 1, 0, 2, 2)


def test_a_moving_object_has_a_gold_box_per_frame_and_none_before_it_appears():
    frames = si.moving_object_frames([0, 1, 2.5, 4], appear_at=0.5)
    assert [f.timestamp_seconds for f in frames] == [0.0, 1.0, 2.5, 4.0]
    assert "item" not in frames[0].objects
    assert frames[1].objects["item"].pixels == (95, 110, 155, 160)
    assert frames[2].objects["item"].pixels == (208, 110, 268, 160)
    assert frames[3].objects["item"].pixels == (320, 110, 380, 160)
    assert frames[1].objects["item"].box["left"] == 95 / 400
    assert changed(frames[0].image, frames[1].image) == (95, 110, 155, 160)


def test_an_object_can_leave_and_stay_gone():
    frames = si.moving_object_frames([0, 1, 2], disappear_at=1)
    assert "item" in frames[0].objects and "item" not in frames[1].objects
    assert frames[1].image.tobytes() == frames[2].image.tobytes()  # the belt alone, both times


def test_frame_times_must_be_explicit_finite_and_increasing():
    for bad in ([], [1, 1], [2, 1], [-1], [float("nan")], [True], "01"):
        with pytest.raises(ValueError):
            si.build_frames(bad, lambda t: si.Canvas())
    with pytest.raises(ValueError):
        si.moving_object_frame(t=-1)
    with pytest.raises(TypeError):
        si.moving_object_frame(0.0)  # keyword only, so a manifest's parameters can rebuild it


def test_save_frames_returns_pairs_that_load_frames_accepts(tmp_path):
    frames = si.moving_object_frames([0, 0.75, 1.5], appear_at=0)
    pairs = si.save_frames(frames, tmp_path, "belt")
    assert pairs == [
        (0.0, "assets/belt-00.png"),
        (0.75, "assets/belt-01.png"),
        (1.5, "assets/belt-02.png"),
    ]
    state, assets = vision.load_frames(pairs, root=tmp_path)
    assert [row["timestamp_seconds"] for row in state] == [0.0, 0.75, 1.5]
    assert len(assets) == 3  # three different pictures, three assets
    assert si.save_frames(frames, tmp_path, "belt") == pairs  # unchanged files are accepted again


# -- every primitive reports the box of the pixels it changed -------------------------------------

PRIMITIVES = {
    "rect": lambda c: c.rect(10, 10, 50, 30, "blue", outline="ink", outline_width=3),
    "ellipse": lambda c: c.ellipse(10, 10, 50, 30, "blue", outline="ink", outline_width=2),
    "triangle-up": lambda c: c.triangle(10, 10, 50, 30, "red"),
    "triangle-down": lambda c: c.triangle(10, 10, 50, 30, "red", direction="down"),
    "triangle-left": lambda c: c.triangle(10, 10, 31, 50, "red", direction="left"),
    "triangle-right": lambda c: c.triangle(10, 10, 31, 50, "red", direction="right"),
    "line": lambda c: c.line(10, 10, 80, 50, "ink", 3),
    "text": lambda c: c.text(10, 10, "HELLO 42", "ink", 3),
    "text_block": lambda c: c.text_block(10, 10, ["AB", "CD"], "ink", 2),
    "labelled_rect": lambda c: c.labelled_object(10, 10, 80, 40, "teal", name="o", label="OK"),
    "labelled_ellipse": lambda c: c.labelled_object(
        10, 10, 80, 40, "teal", name="o", label="OK", shape="ellipse"
    ),
    "labelled_triangle": lambda c: c.labelled_object(
        10, 10, 80, 60, "teal", name="o", label="A", shape="triangle"
    ),
    "window": lambda c: c.window(10, 10, 260, 200, "DEMO"),
    "button": lambda c: c.button(10, 10, 120, 40, "GO", style="danger"),
    "text_input": lambda c: c.text_input(10, 10, 200, 34, "HELLO"),
    "dialog": lambda c: c.dialog(10, 10, 240, 180, "NOTICE", ["BODY", "MORE"], buttons=("A", "B")),
    "banner": lambda c: c.error_banner(10, 10, 280, 32, "FAILED", level="warning"),
    "bar": lambda c: c.bar(10, 10, 102, 12, 0.3),
    "stamp": lambda c: c.stamp(10, 10, 90, 90, "OK", paper=BLANK),
    "signature": lambda c: c.signature(10, 10, 120, 40),
    "wordmark": lambda c: c.wordmark(10, 10, 220, 60, style_seed=2),
    "spinner": lambda c: c.spinner(100, 100, 24, phase=3),
}


@pytest.mark.parametrize("name", sorted(PRIMITIVES))
def test_a_primitive_changes_exactly_the_pixels_of_its_box(name):
    c = blank()
    before = c.image.copy()
    drawn = PRIMITIVES[name](c)
    assert changed(before, c.image) == drawn.pixels
    # and the normalized box maps back to those pixels through the vision helpers
    assert vision.normalized_to_pixels(drawn.box, *c.size) == drawn.pixels


# -- the example scenes ---------------------------------------------------------------------------


def test_login_screen_geometry_is_stable_and_state_specific():
    for state in ("normal", "error", "loading", "crash"):
        c = si.login_screen(state=state, seed=3)
        assert c.size == (640, 400)
        assert c.objects["window"].pixels == (60, 30, 580, 370)
        assert c.objects["username"].pixels == (80, 132, 380, 166)
        assert c.objects["password"].pixels == (80, 200, 380, 234)
        assert c.objects["submit"].pixels == (80, 262, 220, 302)
        assert c.objects["window"].attrs["title"] == f"{si.fictional_name(3)} SIGN IN"
        extras = {"error_banner", "spinner", "dialog"} & set(c.objects)
        assert (
            extras
            == {
                "normal": set(),
                "error": {"error_banner"},
                "loading": {"spinner"},
                "crash": {"dialog"},
            }[state]
        )
    error = si.login_screen(state="error")
    assert error.objects["error_banner"].pixels == (80, 66, 560, 98)
    assert error.objects["password"].attrs["invalid"] is True
    loading = si.login_screen(state="loading")
    assert loading.objects["submit"].attrs == {"style": "disabled", "label": "SIGNING IN"}
    assert loading.objects["spinner"].pixels == (234, 266, 268, 300)
    crash = si.login_screen(state="crash")
    assert crash.objects["dialog"].pixels == (150, 110, 490, 280)
    assert crash.image.getpixel((0, 0)) == (
        128,
        129,
        133,
    )  # the 232, 235, 241 backdrop at 55 percent
    with pytest.raises(ValueError):
        si.login_screen(state="blank")


def test_the_four_login_states_are_four_different_pictures():
    images = {
        s: si.login_screen(state=s).image.tobytes() for s in ("normal", "error", "loading", "crash")
    }
    assert len(set(images.values())) == 4
    assert si.login_screen(seed=1).image.tobytes() != si.login_screen(seed=2).image.tobytes()


def test_part_photo_geometry_and_each_defect():
    clean = si.part_photo()
    assert clean.size == (480, 360)
    assert clean.objects["part"].pixels == (90, 50, 390, 300)
    assert clean.objects["screw_tl"].pixels == (110, 70, 134, 94)
    assert clean.objects["screw_br"].pixels == (346, 256, 370, 280)
    assert clean.objects["connector"].pixels == (170, 130, 310, 210)
    assert "defect" not in clean.objects
    part = clean.objects["part"]
    scratch = si.part_photo(defect="scratch", seed=5).objects["defect"]
    dent = si.part_photo(defect="dent", seed=5).objects["defect"]
    for found in (scratch, dent):
        assert part.left <= found.left and found.right <= part.right
        assert part.top <= found.top and found.bottom <= part.bottom
    assert (scratch.kind, dent.kind) == ("scratch", "dent")
    gone = si.part_photo(defect="missing_screw")
    assert gone.objects["defect"].pixels == (346, 256, 370, 280)
    assert "screw_br" not in gone.objects and "screw_bl" in gone.objects
    assert gone.image.getpixel((358, 268)) == gone.image.getpixel((350, 150))  # plate shows through
    with pytest.raises(ValueError):
        si.part_photo(defect="rust")


def test_each_defect_makes_a_different_picture_and_the_seed_moves_it():
    pictures = {
        d: si.part_photo(defect=d, seed=5).image.tobytes()
        for d in ("none", "scratch", "dent", "missing_screw")
    }
    assert len(set(pictures.values())) == 4
    assert (
        si.part_photo(defect="scratch", seed=1).objects["defect"].pixels
        != si.part_photo(defect="scratch", seed=2).objects["defect"].pixels
    )


def test_deck_hud_geometry_counts_and_limits():
    hud = si.deck_hud(cards=5, enemies=3, energy=2, seed=4)
    assert hud.size == (800, 450)
    assert hud.objects["end_turn"].pixels == (676, 386, 788, 434)
    assert hud.objects["energy"].pixels == (20, 330, 100, 410)
    assert hud.objects["player"].pixels == (80, 170, 170, 280)
    assert hud.objects["card_0"].pixels == (130, 300, 230, 440)
    assert hud.objects["card_4"].pixels == (570, 300, 670, 440)
    assert {n for n in hud.objects if re.fullmatch(r"card_\d", n)} == {
        f"card_{i}" for i in range(5)
    }
    assert {n for n in hud.objects if re.fullmatch(r"enemy_\d", n)} == {
        "enemy_0",
        "enemy_1",
        "enemy_2",
    }
    for i in range(3):
        enemy = hud.objects[f"enemy_{i}"]
        assert (enemy.left, enemy.right) == (440 + 120 * i, 540 + 120 * i) or enemy.width <= 100
        assert enemy.top >= 120 and enemy.bottom <= 240
    quiet = si.deck_hud(cards=1, enemies=0)
    assert not [n for n in quiet.objects if n.startswith("enemy")]
    for bad in (
        {"cards": 0},
        {"cards": 6},
        {"enemies": 4},
        {"energy": 4},
        {"energy": 1, "energy_max": 10},
    ):
        with pytest.raises(ValueError):
            si.deck_hud(**bad)


def test_every_object_of_every_scene_round_trips_through_vision_and_stays_in_bounds():
    scenes = [
        *(si.login_screen(state=s, seed=1) for s in ("normal", "error", "loading", "crash")),
        *(si.part_photo(defect=d, seed=1) for d in ("none", "scratch", "dent", "missing_screw")),
        si.deck_hud(cards=5, enemies=3),
        *si.moving_object_frames([0, 2, 4]),
    ]
    scenes = [s.canvas if isinstance(s, si.Frame) else s for s in scenes]
    seen = 0
    for scene in scenes:
        for drawn in scene.objects.values():
            assert 0 <= drawn.left < drawn.right <= scene.width
            assert 0 <= drawn.top < drawn.bottom <= scene.height
            assert vision.normalized_to_pixels(drawn.box, *scene.size) == drawn.pixels
            vision.normalized_box(drawn.box)
            seen += 1
    assert seen > 100


# -- saving, the checker and the byte policy -------------------------------------------------------


def chunk_names(data: bytes) -> list[bytes]:
    import struct

    names, position = [], 8
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        names.append(data[position + 4 : position + 8])
        position += 12 + length
    return names


def example_canvases() -> dict[str, si.Canvas]:
    out = {
        f"login-{s}": si.login_screen(state=s, seed=3)
        for s in ("normal", "error", "loading", "crash")
    }
    out.update(
        {
            f"part-{d}": si.part_photo(defect=d, seed=1)
            for d in ("none", "scratch", "dent", "missing_screw")
        }
    )
    out["hud"] = si.deck_hud(cards=5, enemies=3, energy=2, seed=4)
    out["belt"] = si.moving_object_frame(t=1.0, appear_at=0.5)
    return out


def test_encoded_pngs_hold_only_the_three_chunks_and_pass_the_repository_checker():
    for name, canvas in example_canvases().items():
        data = canvas.png()
        names = chunk_names(data)
        assert names[0] == b"IHDR" and names[-1] == b"IEND", name
        assert set(names) <= {b"IHDR", b"IDAT", b"IEND"}, name
        assert checker.check_image(f"recipes/99-demo/assets/{name}.png", data) == [], name
        assert len(data) < checker.MAX_FILE_BYTES


def test_a_png_over_the_byte_cap_is_refused_at_encode_time():
    c = si.Canvas(700, 700, (128, 128, 128), seed=1)
    c.noise(127, grey=False)
    with pytest.raises(ValueError, match="may hold"):
        c.png()


def tree(folder: Path) -> list[str]:
    """Every file and folder under ``folder``, so "nothing was written" is checked literally."""
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))


def icc_tagged() -> Image.Image:
    image = Image.new("RGB", (300, 300))
    image.info["icc_profile"] = b"x" * 128  # Pillow writes an iCCP chunk for this
    return image


def noisy_canvas() -> si.Canvas:
    canvas = si.Canvas(700, 700, (128, 128, 128), seed=1)
    canvas.noise(127, grey=False)  # colour noise does not compress: over the 1 MiB cap
    return canvas


REJECTED = {
    "16x16": lambda: Image.new("RGB", (16, 16), "white"),
    "279 wide": lambda: Image.new("RGB", (279, 300), "white"),
    "279 tall": lambda: Image.new("RGB", (300, 279), "white"),
    "1569 wide": lambda: Image.new("RGB", (1569, 300), "white"),
    "metadata": icc_tagged,
    "over 1 MiB": lambda: noisy_canvas().image,
}


def rejected_image(kind: str) -> Image.Image:
    return REJECTED[kind]()


@pytest.mark.parametrize("kind", sorted(REJECTED))
def test_write_asset_rejects_an_unfit_image_before_writing_anything(tmp_path, kind):
    with pytest.raises(ValueError):
        si.write_asset(rejected_image(kind), tmp_path, "assets/a.png")
    assert tree(tmp_path) == []  # not the file, not the assets folder, not a temporary file


@pytest.mark.parametrize("kind", sorted(REJECTED))
def test_write_png_and_encode_png_reject_the_same_images(tmp_path, kind):
    with pytest.raises(ValueError):
        si.write_png(rejected_image(kind), tmp_path / "docs" / "x.png")
    assert tree(tmp_path) == []
    with pytest.raises(ValueError):
        si.encode_png(rejected_image(kind))


def test_a_rejected_image_leaves_the_committed_file_alone(tmp_path):
    si.login_screen().write(tmp_path, "assets/a.png")
    committed = (tmp_path / "assets" / "a.png").read_bytes()
    with pytest.raises(ValueError, match="280 to 1568"):
        si.write_asset(Image.new("RGB", (16, 16)), tmp_path, "assets/a.png", overwrite=True)
    assert (tmp_path / "assets" / "a.png").read_bytes() == committed
    assert tree(tmp_path) == ["assets", "assets/a.png"]


def test_the_api_limits_are_checked_through_vision_on_the_encoded_bytes(monkeypatch, tmp_path):
    calls = []
    real = si.validate_image_asset

    def spy(asset):
        calls.append(asset)
        return real(asset)

    monkeypatch.setattr(si, "validate_image_asset", spy)
    c = si.login_screen()
    c.write(tmp_path, "assets/a.png")
    assert len(calls) == 1
    assert set(calls[0]) == {"type", "format", "data_base64"} and calls[0]["format"] == "png"
    import base64

    assert base64.b64decode(calls[0]["data_base64"]) == (tmp_path / "assets" / "a.png").read_bytes()
    monkeypatch.setattr(
        si, "validate_image_asset", lambda asset: (_ for _ in ()).throw(ValueError("no"))
    )
    with pytest.raises(ValueError, match="no"):
        c.write(tmp_path, "assets/b.png")
    assert not (tmp_path / "assets" / "b.png").exists()


def symlink_or_skip(link: Path, target: Path) -> None:
    """Create a directory symlink, or skip the test where the platform cannot (Windows without
    Developer Mode raises OSError 1314). The idiom of tests/test_fixtures_assets.py's _symlink
    and tests/test_vision.py's escape test."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("this platform cannot create symbolic links")


def test_a_path_that_escapes_the_recipe_is_refused_before_any_write(tmp_path):
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_or_skip(recipe / "assets", outside)
    with pytest.raises(vision.AssetPathError):
        si.login_screen().write(recipe, "assets/a.png")
    assert tree(outside) == []


@pytest.mark.parametrize(
    "error",
    [OSError(1314, "A required privilege is not held by the client"), NotImplementedError()],
)
def test_the_symlink_test_skips_where_symlinks_cannot_be_created(tmp_path, monkeypatch, error):
    def refuse(self, target, target_is_directory=False):
        raise error

    monkeypatch.setattr(Path, "symlink_to", refuse)
    with pytest.raises(pytest.skip.Exception, match="cannot create symbolic links"):
        test_a_path_that_escapes_the_recipe_is_refused_before_any_write(tmp_path)
    assert tree(tmp_path) == ["outside", "recipe"]  # it skipped before writing anything


def test_a_failure_while_writing_leaves_no_file_and_no_temporary_file(tmp_path, monkeypatch):
    def broken(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr(si.os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        si.login_screen().write(tmp_path, "assets/a.png")
    assert tree(tmp_path) == ["assets"]


def test_a_non_rgb_image_is_converted_and_stray_chunks_are_refused():
    rgba = Image.new("RGBA", (300, 300), (10, 20, 30, 255))
    assert si.pixels_sha256(si.encode_png(rgba)) == si.pixels_sha256(rgba.convert("RGB"))
    tagged = Image.new("RGB", (300, 300))
    tagged.info["icc_profile"] = b"x" * 128  # Pillow would write an iCCP chunk for this
    with pytest.raises(ValueError, match="chunks"):
        si.encode_png(tagged)


def test_pixels_sha256_is_the_hash_of_size_and_raw_pixels():
    image = Image.new("RGB", (280, 281), (1, 2, 3))
    expected = hashlib.sha256(b"280x281:" + bytes((1, 2, 3)) * (280 * 281)).hexdigest()
    assert si.pixels_sha256(image) == expected
    assert si.pixels_sha256(si.encode_png(image)) == expected
    assert not si.png_pixels_equal(
        si.encode_png(image), si.encode_png(Image.new("RGB", (281, 280), (1, 2, 3)))
    )


def other_encoding(canvas: si.Canvas) -> bytes:
    buffer = io.BytesIO()
    canvas.image.save(
        buffer, "PNG", compress_level=1
    )  # the same pixels through a different zlib setting
    return buffer.getvalue()


def test_write_asset_creates_then_recognises_its_own_file(tmp_path):
    c = si.login_screen(seed=2)
    assert c.write(tmp_path, "assets/a.png") == "created"
    assert (tmp_path / "assets" / "a.png").read_bytes() == c.png()
    assert c.write(tmp_path, "assets/a.png") == "unchanged"
    assert vision.image_asset("assets/a.png", root=tmp_path)["format"] == "png"


def test_other_bytes_with_the_same_pixels_are_kept_off_the_canonical_pillow(tmp_path, monkeypatch):
    c = si.login_screen(seed=2)
    target = tmp_path / "assets" / "a.png"
    c.write(tmp_path, "assets/a.png")
    foreign = other_encoding(c)
    assert foreign != c.png() and si.png_pixels_equal(foreign, c.png())
    target.write_bytes(foreign)  # as if committed by a build with another zlib
    monkeypatch.setattr(si, "CANONICAL_PILLOW", "0.0.0")
    assert not si.bytes_are_canonical()
    assert c.write(tmp_path, "assets/a.png") == "kept-committed-bytes"
    assert target.read_bytes() == foreign  # never rewritten


def test_other_bytes_under_the_canonical_pillow_are_a_mismatch_not_a_rewrite(tmp_path, monkeypatch):
    c = si.login_screen(seed=2)
    target = tmp_path / "assets" / "a.png"
    c.write(tmp_path, "assets/a.png")
    foreign = other_encoding(c)
    target.write_bytes(foreign)
    monkeypatch.setattr(si, "CANONICAL_PILLOW", PIL.__version__)
    monkeypatch.setattr(si.features, "version", lambda name: "1.3")
    assert si.bytes_are_canonical()
    with pytest.raises(si.RegenerationMismatch, match="canonical") as raised:
        c.write(tmp_path, "assets/a.png")
    assert target.read_bytes() == foreign
    # equal pixels cannot be the generator's doing, and the message says what to do instead
    message = str(raised.value)
    assert "generator" not in message.split("Recreate")[0]
    assert "created under another Pillow or zlib" in message and "constraints pin" in message


def test_different_pixels_blame_the_generator_not_the_encoder(tmp_path):
    first, second = si.login_screen(state="normal"), si.login_screen(state="error")
    first.write(tmp_path, "assets/a.png")
    with pytest.raises(si.RegenerationMismatch) as raised:
        second.write(tmp_path, "assets/a.png")
    assert "generator, its parameters or the seed changed the picture" in str(raised.value)
    assert "Pillow" not in str(raised.value)


@pytest.mark.parametrize(
    ("zlib", "canonical"),
    [
        ("1.2.13", True),  # the PyPI wheels of Pillow 12.3.0 and 13.0.0
        ("1.3", True),  # Pillow 12.3.0 on the GitHub Actions runner: same bytes, measured
        ("1.3.1", True),
        ("1.3.1.zlib-ng", False),  # zlib-ng deflates differently
        ("2.2.4", False),
        ("", False),
        (None, False),  # no zlib reported
        # Forks that report a plain upstream number cannot be told apart; the GOLDEN digests are
        # what catch them.
        ("1.2.11-ipp", False),
        ("1.3.1-cf", False),
        ("1.3.0.cloudflare", False),
        ("1.2.11.1", False),
        ("1.3.1 custom", False),
        ("1", False),
        ("zlib 1.3", False),
    ],
)
def test_the_byte_gate_needs_the_pinned_pillow_and_a_classic_zlib(monkeypatch, zlib, canonical):
    monkeypatch.setattr(si, "CANONICAL_PILLOW", PIL.__version__)
    monkeypatch.setattr(si.features, "version", lambda name: zlib)
    assert si.bytes_are_canonical() is canonical
    monkeypatch.setattr(si, "CANONICAL_PILLOW", "0.0.0")  # another Pillow, whatever the zlib
    assert not si.bytes_are_canonical()


def test_different_pixels_are_a_mismatch_until_overwrite_is_explicit(tmp_path):
    first, second = si.login_screen(state="normal"), si.login_screen(state="error")
    target = tmp_path / "assets" / "a.png"
    first.write(tmp_path, "assets/a.png")
    committed = target.read_bytes()
    with pytest.raises(si.RegenerationMismatch, match="pixels differ"):
        second.write(tmp_path, "assets/a.png")
    assert target.read_bytes() == committed
    assert second.write(tmp_path, "assets/a.png", overwrite=True) == "rewritten"
    assert si.png_pixels_equal(target.read_bytes(), second.png())


def test_an_unreadable_committed_file_is_a_mismatch(tmp_path):
    c = si.login_screen()
    target = tmp_path / "assets" / "a.png"
    target.parent.mkdir()
    target.write_bytes(b"not a png")
    with pytest.raises(si.RegenerationMismatch):
        c.write(tmp_path, "assets/a.png")
    assert target.read_bytes() == b"not a png"


@pytest.mark.parametrize(
    "path",
    [
        "a.png",
        "assets/a.jpg",
        "assets/A.PNG",
        "assets/../a.png",
        "/abs/a.png",
        "assets\\a.png",
        "assets/.hidden.png",
    ],
)
def test_write_asset_refuses_paths_the_manifest_would_refuse(tmp_path, path):
    with pytest.raises(ValueError, match="assets/name.png"):
        si.login_screen().write(tmp_path, path)
    assert list(tmp_path.iterdir()) == []


def test_write_png_has_the_same_outcomes_for_any_path(tmp_path):
    c = si.login_screen()
    target = tmp_path / "docs" / "x.png"
    assert si.write_png(c, target) == "created"
    assert si.write_png(c.image, target) == "unchanged"
    with pytest.raises(si.RegenerationMismatch):
        si.write_png(si.login_screen(state="error"), target)


# -- the manifest --------------------------------------------------------------------------------


def read_json(path):
    return json.loads(path.read_text("utf-8")), None


def problems(recipe: Path) -> list:
    return assets_module.check_assets(
        recipe, [], read_json=read_json, leak_splits=("train", "validation", "test")
    )


def write_manifest(recipe: Path, entries: list) -> None:
    (recipe / "assets-manifest.json").write_text(
        json.dumps({"schema": 1, "assets": entries}), "utf-8"
    )


def test_scene_manifest_entries_pass_the_fixture_validator(tmp_path):
    entries = []
    for index, (name, canvas) in enumerate(example_canvases().items()):
        path = f"assets/{name}.png"
        canvas.write(tmp_path, path)
        entries.append(canvas.manifest_entry(tmp_path, path, f"Example scene {index}."))
    write_manifest(tmp_path, entries)
    assert problems(tmp_path) == []
    entry = entries[0]
    assert entry["generator"] == "jev_cookbook.synthetic_images:login_screen"
    assert entry["parameters"] == {"state": "normal", "seed": 3}
    assert entry["origin"] == "generated" and entry["licence"] == "CC0-1.0"
    assert entry["attestations"] == {
        "synthetic": True,
        "real_photo": False,
        "real_brand": False,
        "real_person": False,
        "third_party_content": False,
    }
    assert (entry["width"], entry["height"], entry["format"]) == (640, 400, "PNG")


def test_a_script_generator_must_exist_in_the_recipe_and_name_the_function(tmp_path):
    c = si.Canvas(300, 300)
    c.rect(10, 10, 50, 50, "blue", name="box")
    c.write(tmp_path, "assets/a.png")
    c.provenance("build_fixtures.py:draw_box", {"size": 50})
    with pytest.raises(ValueError, match="build_fixtures.py"):
        c.manifest_entry(tmp_path, "assets/a.png", "A blue box.")
    (tmp_path / "build_fixtures.py").write_text("def other():\n    pass\n", "utf-8")
    with pytest.raises(ValueError, match="draw_box"):
        c.manifest_entry(tmp_path, "assets/a.png", "A blue box.")
    (tmp_path / "build_fixtures.py").write_text("def draw_box(size):\n    pass\n", "utf-8")
    write_manifest(tmp_path, [c.manifest_entry(tmp_path, "assets/a.png", "A blue box.")])
    assert problems(tmp_path) == []


def test_a_shared_generator_must_name_a_real_function():
    c = si.Canvas(300, 300)
    for bad in ("jev_cookbook.synthetic_images:nope", "jev_cookbook.no_such_module:x", "os:system"):
        c.provenance(bad, {})
        with pytest.raises(ValueError):
            c.manifest_entry(Path("."), "assets/a.png", "x")


def test_manifest_entry_needs_provenance_and_a_description(tmp_path):
    c = si.Canvas(300, 300)
    c.write(tmp_path, "assets/a.png")
    with pytest.raises(ValueError, match="provenance"):
        c.manifest_entry(tmp_path, "assets/a.png", "x")
    c.provenance("jev_cookbook.synthetic_images:login_screen", {"seed": 1})
    with pytest.raises(ValueError, match="description"):
        c.manifest_entry(tmp_path, "assets/a.png", "  ")
    with pytest.raises(ValueError, match="JSON"):
        c.provenance("jev_cookbook.synthetic_images:login_screen", {"seed": object()})
    with pytest.raises(ValueError, match="JSON"):
        c.provenance("jev_cookbook.synthetic_images:login_screen", {"seed": float("nan")})


def test_a_tampered_file_fails_the_validator_hash_check(tmp_path):
    c = si.login_screen()
    c.write(tmp_path, "assets/a.png")
    write_manifest(tmp_path, [c.manifest_entry(tmp_path, "assets/a.png", "A screen.")])
    assert problems(tmp_path) == []
    (tmp_path / "assets" / "a.png").write_bytes(si.login_screen(state="error").png())
    assert any("[hash-mismatch]" in message for _, message, _ in problems(tmp_path))


def test_manifest_entry_equals_the_helper_printed_in_fixtures_md(tmp_path):
    text = (REPO / "docs" / "fixtures.md").read_text("utf-8")
    code = re.search(r"```python\n(import hashlib\n.*?)\n```", text, re.S)
    scope: dict = {}
    exec(code.group(1), scope)  # our own documentation snippet
    c = si.part_photo(defect="dent", seed=2)
    c.write(tmp_path, "assets/p.png")
    mine = si.manifest_entry(tmp_path, "assets/p.png", c.generator, c.parameters, "A part.")
    docs = scope["manifest_entry"](tmp_path, "assets/p.png", c.generator, c.parameters, "A part.")
    assert mine == docs == c.manifest_entry(tmp_path, "assets/p.png", "A part.")


def test_every_scene_generator_matches_the_schemas_pattern_and_rebuilds_from_json():
    assert set(si.SCENES) == {"login_screen", "part_photo", "deck_hud", "moving_object_frame"}
    for name, scene in si.SCENES.items():
        canvas = scene(t=1.0) if name == "moving_object_frame" else scene()
        assert assets_module._GENERATOR.fullmatch(canvas.generator)
        assert canvas.generator == f"jev_cookbook.synthetic_images:{name}"
        rebuilt = si.reproduce(canvas.generator, json.loads(json.dumps(canvas.parameters)))
        assert rebuilt.image.tobytes() == canvas.image.tobytes()
        assert rebuilt.parameters == canvas.parameters


def test_parameters_hold_every_argument_with_its_default_and_tuples_become_lists():
    assert si.part_photo().parameters == {"defect": "none", "seed": 0}
    belt = si.moving_object_frame(t=2.5)
    assert belt.parameters["start"] == [20, 110] and belt.parameters["travel_seconds"] == [0.0, 4.0]
    assert belt.parameters["appear_at"] is None and belt.parameters["t"] == 2.5


def test_reproduce_runs_only_the_scenes_of_this_module():
    for bad in (
        "os:system",
        "jev_cookbook.synthetic_images:Canvas",
        "jev_cookbook.vision:image_asset",
        "login_screen",
    ):
        with pytest.raises(ValueError):
            si.reproduce(bad, {})


def test_check_reproducible_accepts_a_matching_file_and_rejects_another_picture(tmp_path):
    c = si.login_screen(state="error", seed=2)
    c.write(tmp_path, "assets/a.png")
    entry = c.manifest_entry(tmp_path, "assets/a.png", "A screen.")
    assert si.check_reproducible(tmp_path, entry) == "unchanged"
    entry["parameters"] = {"state": "normal", "seed": 2}
    with pytest.raises(si.RegenerationMismatch):
        si.check_reproducible(tmp_path, entry)


# -- constants that must agree with the rest of the repository ----------------------------------


def test_canonical_pillow_is_the_version_pinned_for_the_notebooks():
    pins = (REPO / ".github" / "constraints-notebooks.txt").read_text("utf-8")
    pinned = re.search(r"(?mi)^pillow==(\S+)$", pins).group(1)
    assert pinned == si.CANONICAL_PILLOW, (
        f"the notebook constraints now pin Pillow {pinned} but CANONICAL_PILLOW is "
        f"{si.CANONICAL_PILLOW}. After a pin bump: (1) set CANONICAL_PILLOW in "
        "src/jev_cookbook/synthetic_images.py and check that the new wheel's zlib "
        '(PIL.features.version("zlib")) is still a classic zlib 1.x, not zlib-ng; '
        "(2) re-record the PNG byte digests "
        "(the second element of each GOLDEN entry in this file); (3) run "
        "`python docs/assets/synthetic-images/build_gallery.py --overwrite` and commit the "
        "gallery if its bytes moved; (4) rebuild every recipe's committed assets, manifest "
        "hashes and replay_keys that a changed byte touches. See 'Byte stability and "
        "regeneration' in docs/synthetic-images.md."
    )


def test_the_pinned_pillow_is_linked_to_a_classic_zlib():
    if PIL.__version__ != si.CANONICAL_PILLOW:
        pytest.skip(f"only the pinned Pillow {si.CANONICAL_PILLOW} is the canonical encoder")
    assert si.bytes_are_canonical(), (
        f"Pillow {PIL.__version__} reports zlib {features.version('zlib')}, which is not a classic "
        "zlib 1.x. If a Pillow pin bump moved the wheel to zlib-ng, the committed PNG bytes and "
        "the GOLDEN byte digests must be re-recorded and the gate in bytes_are_canonical "
        "reconsidered (docs/synthetic-images.md, 'Bumping the Pillow pin')."
    )


def test_limits_agree_with_the_checker_and_vision():
    assert si.MAX_ASSET_BYTES == checker.MAX_FILE_BYTES
    assert (vision.IMAGE_LIMITS["min_side"], vision.IMAGE_LIMITS["max_side"]) == (
        checker.MIN_SIDE,
        checker.MAX_SIDE,
    )
    assert (vision.IMAGE_LIMITS["min_area"], vision.IMAGE_LIMITS["max_area"]) == (
        checker.MIN_PIXELS,
        checker.MAX_PIXELS,
    )
    assert si._PNG_CHUNKS and set(si._PNG_CHUNKS) <= {
        c.encode() for c in checker.PNG_ALLOWED_CHUNKS
    }


def test_the_module_uses_no_font_file_or_pillow_text_rendering():
    source = (REPO / "src" / "jev_cookbook" / "synthetic_images.py").read_text("utf-8")
    for word in (
        "ImageFont",
        "truetype",
        "load_default",
        "textbbox",
        "textlength",
        "import random",
    ):
        assert word not in source, word


def test_every_name_in___all___exists():
    assert all(hasattr(si, name) for name in si.__all__)
    assert len(set(si.__all__)) == len(si.__all__)


# Regression pins: (sha256 of the decoded pixels, sha256 of the PNG bytes) of each example scene.
# They were recorded from the code and say nothing about whether a scene is right (the tests above
# do); they make an unintended change to a scene fail, and they were identical on Python 3.10 and
# 3.14 and on Pillow 12.3.0 and 13.0.0. Changing a scene on purpose means re-recording them, and
# re-running every recipe that uses it (its committed images, hashes and replay keys).
GOLDEN = {
    "login-normal": (
        "5995bdfd5fdd7f79bc40fa6e86a932597a2f79fc056464e1ddce144e187da936",
        "d672e369432cef4326e03e177ddbb176c859446622b3a652e652e91de0eb7792",
    ),
    "login-error": (
        "5af6c9279222cb68c3cba166c23d52d6c3b0cca59924994110b4bcc5b598bd61",
        "60717a841404d6ac926c793597b75856d8fe140f050c112d77bc5673398f1387",
    ),
    "login-loading": (
        "57882af9a9af257f06eb85fdeea8812590a8e909998916f7943de4c0e3170f8d",
        "9467f71c92e892794386426ba66f64208a717b26b4a9d3f699d3ad4f07e20d1c",
    ),
    "login-crash": (
        "e75b2eedd876fb8424220166eb5b590fd1f6528cc1a7922b2fa3b6e3575ba17e",
        "21064f0b0358bb302d66f844c420318be93843d9436db55f3b713d0f490a00ac",
    ),
    "part-none": (
        "1792ef17d695f71013bf7ff42078e849e032ee52dd3d9e7c5bfb6b5bcd410cc2",
        "c7e557048ed070802d9d3196c80cad267caf673a547d55ce12b6a15ea01e3b76",
    ),
    "part-scratch": (
        "41f05210b8f4c9fab2a5875f14e52965f7da66af9ac3581ea768251dc9be041c",
        "15cc9d99f9a5673811a80023654b83b2a8e1f79937247c56f686244d95172269",
    ),
    "part-dent": (
        "1d5224d7b1d1b98a16942e1a4abbf46164dd9d16df3dea4c69a684284ae0236d",
        "a6e5a161eac203aa19d140073c0fe92ede862edf51c21e6f145d6915ac351bda",
    ),
    "part-missing_screw": (
        "f01cdc628ce08f0ff9387add8fd07ec0f94776dd76cc3d6401d1473d8843d4e6",
        "dac83bf4cdb4e45c3ad0590f1f86b8ded70ce473f8f08c25dc4e6eeb856084b2",
    ),
    "hud": (
        "cfdde47152eb7af0c6b1f1f821603950c4a053ca841e67adae9665cd9423c218",
        "c1002d3b58370c31ab9ced87a15550c53ccb1e75f4235fc392c17d355f620546",
    ),
    "belt": (
        "db279bc3550c583438573090dd6a5824bb702a8a9507607122da7939e6146084",
        "823c2993c49988c277d2d761ad214e104032d8e4676a0aad16fb63551a379dcf",
    ),
}


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_example_scene_pixels_are_pinned_on_every_python_and_pillow(name):
    assert si.pixels_sha256(example_canvases()[name].image) == GOLDEN[name][0]


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_example_scene_bytes_are_pinned_under_the_canonical_encoder(name):
    # Which CI leg runs these: Pillow 13 needs Python 3.11 or later, so the unpinned
    # `Tests (py3.10)` job resolves the canonical Pillow 12.3.0 and runs them, while
    # `Tests (py3.14)` resolves a newer Pillow and skips them (the pixel pins above still run).
    # No job installs with the notebook constraints. Run them anywhere with:
    #   pip install -e ".[dev]" -c .github/constraints-notebooks.txt
    if not si.bytes_are_canonical():
        pytest.skip(
            f"PNG bytes are canonical only under Pillow {si.CANONICAL_PILLOW} with a classic "
            f"zlib; this is Pillow {PIL.__version__}, zlib {features.version('zlib')}"
        )
    assert hashlib.sha256(example_canvases()[name].png()).hexdigest() == GOLDEN[name][1]


def test_the_golden_table_covers_every_scene_and_every_state():
    assert set(GOLDEN) == set(example_canvases())
    assert len({pixels for pixels, _ in GOLDEN.values()}) == len(GOLDEN)  # ten different pictures


# -- the documentation ----------------------------------------------------------------------------

DOC = REPO / "docs" / "synthetic-images.md"
BLOCKS = re.findall(r"```python\n(.*?)```", DOC.read_text("utf-8"), re.S)


def block_with(text: str) -> str:
    found = [b for b in BLOCKS if text in b]
    assert len(found) == 1, f"expected exactly one documented block containing {text!r}"
    return found[0]


def run_script(folder: Path, *args: str):
    import subprocess

    return subprocess.run(
        [sys.executable, "build_fixtures.py", *args],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def demo_recipe(tmp_path):
    recipe = tmp_path / "99-demo"
    recipe.mkdir()
    (recipe / "build_fixtures.py").write_text(block_with("def draw_shelf"), "utf-8")
    return recipe


def test_the_worked_example_builds_a_recipe_the_validators_accept(demo_recipe):
    first = run_script(demo_recipe)
    assert first.returncode == 0, first.stderr
    lines = first.stdout.splitlines()
    assert lines[:4] == [
        "created: assets/login-normal.png",
        "created: assets/login-error.png",
        "created: assets/shelf-full.png",
        "created: assets/shelf-gap.png",
    ]
    # the label of the gap is product 3's slot: x 30 + 2 * 70 .. +60, y 40 .. 130 on a 480 x 320 image
    label = json.loads(lines[4])
    assert label == {
        "present": True,
        "box": {"top": 40 / 320, "bottom": 130 / 320, "left": 170 / 480, "right": 230 / 480},
    }
    assert re.fullmatch(r"image:sha256:[0-9a-f]{64}", lines[5])
    assert problems(demo_recipe) == []
    for image in sorted((demo_recipe / "assets").iterdir()):
        data = image.read_bytes()
        assert checker.check_image(f"recipes/99-demo/assets/{image.name}", data) == []
    manifest = json.loads((demo_recipe / "assets-manifest.json").read_text("utf-8"))
    generators = [entry["generator"] for entry in manifest["assets"]]
    assert (
        generators
        == ["jev_cookbook.synthetic_images:login_screen"] * 2 + ["build_fixtures.py:draw_shelf"] * 2
    )
    assert manifest["assets"][3]["parameters"] == {"gaps": [2], "seed": 0}


def test_the_worked_example_is_stable_and_refuses_a_changed_picture(demo_recipe):
    assert run_script(demo_recipe).returncode == 0
    again = run_script(demo_recipe)
    assert again.returncode == 0 and again.stdout.count("unchanged: ") == 4
    target = demo_recipe / "assets" / "shelf-gap.png"
    original = target.read_bytes()
    # the committed picture is no longer what the code draws (a different scene was saved over it)
    target.write_bytes((demo_recipe / "assets" / "shelf-full.png").read_bytes())
    refused = run_script(demo_recipe)
    assert (
        refused.returncode == 1
        and "refused:" in refused.stdout
        and "pixels differ" in refused.stdout
    )
    assert target.read_bytes() != original  # nothing was rewritten
    accepted = run_script(demo_recipe, "--overwrite")
    assert accepted.returncode == 0 and "rewritten: assets/shelf-gap.png" in accepted.stdout
    assert target.read_bytes() == original


def test_the_other_documented_blocks_run(demo_recipe, monkeypatch):
    assert run_script(demo_recipe).returncode == 0
    monkeypatch.chdir(demo_recipe)
    for needle in ("Path.cwd()", "screen.blur(1)", "moving_object_frames([0.0, 1.0, 2.5, 4.0]"):
        exec(
            compile(block_with(needle), str(DOC), "exec"), {"__name__": "__docs__"}
        )  # our own docs


def test_every_documented_block_is_lint_clean_and_the_set_is_complete():
    import subprocess

    assert len(BLOCKS) == 4
    for index, block in enumerate(BLOCKS):
        done = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--stdin-filename", f"block{index}.py", "-"],
            input=block,
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert done.returncode == 0, done.stdout + done.stderr


def test_the_docs_link_to_the_page_and_its_images_exist():
    text = DOC.read_text("utf-8")
    links = re.findall(r"\]\((assets/synthetic-images/[^)]+)\)", text)
    assert len(links) >= 6
    for link in links:
        assert (REPO / "docs" / link).is_file(), link
    for page in ("vision.md", "fixtures.md"):
        assert "synthetic-images.md" in (REPO / "docs" / page).read_text("utf-8")
    for needle in ("no real photograph", "fictional", "invented", "byte"):
        assert needle in text.lower().replace("**", "")


GALLERY = REPO / "docs" / "assets" / "synthetic-images"


def load_gallery():
    spec = importlib.util.spec_from_file_location(
        "build_gallery_for_test", GALLERY / "build_gallery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_gallery_is_what_the_script_draws():
    module = load_gallery()
    drawn = module.gallery()
    assert sorted(drawn) == sorted(p.name for p in GALLERY.glob("*.png"))
    for name, image in drawn.items():
        committed = (GALLERY / name).read_bytes()
        assert si.pixels_sha256(committed) == si.pixels_sha256(image), name
        assert checker.check_image(f"docs/assets/synthetic-images/{name}", committed) == [], name
        if si.bytes_are_canonical():
            assert committed == si.encode_png(image), name


def test_the_gallery_script_refuses_a_changed_picture_and_never_rewrites_it(
    tmp_path, monkeypatch, capsys
):
    module = load_gallery()
    monkeypatch.setattr(module, "HERE", tmp_path)
    assert module.main([]) == 0
    stale = tmp_path / "deck-hud.png"
    original = stale.read_bytes()
    stale.write_bytes((tmp_path / "frames.png").read_bytes())
    assert module.main([]) == 1
    assert "MISMATCH" in capsys.readouterr().out
    assert stale.read_bytes() != original
    assert module.main(["--overwrite"]) == 0
    assert stale.read_bytes() == original


def test_the_package_does_not_import_the_drawing_kit_on_import():
    import subprocess

    code = "import sys, jev_cookbook; print('jev_cookbook.synthetic_images' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


# -- energy_max is a plain integer ----------------------------------------------------------------


@pytest.mark.parametrize("bad", ["3", 3.0, True, None])
def test_deck_hud_refuses_an_energy_max_that_is_not_a_plain_integer(bad):
    with pytest.raises(ValueError, match="energy_max"):
        si.deck_hud(energy=1, energy_max=bad)


def test_deck_hud_accepts_every_energy_max_from_0_to_9():
    for energy_max in range(10):
        assert si.deck_hud(energy=energy_max, energy_max=energy_max).size == (800, 450)


def test_deck_hud_refuses_energy_above_energy_max_and_energy_max_above_9():
    with pytest.raises(ValueError):
        si.deck_hud(energy=4, energy_max=3)
    with pytest.raises(ValueError):
        si.deck_hud(energy=1, energy_max=10)


# -- reproduce and check_reproducible report bad input as ValueError ------------------------------


def test_reproduce_names_a_bad_parameter_and_keeps_the_type_error_as_its_cause():
    with pytest.raises(ValueError, match="login_screen") as raised:
        si.reproduce("jev_cookbook.synthetic_images:login_screen", {"nope": 1})
    assert isinstance(raised.value.__cause__, TypeError)


@pytest.mark.parametrize(
    ("generator", "parameters"),
    [
        ("jev_cookbook.synthetic_images:login_screen", [1]),  # not a mapping
        ("jev_cookbook.synthetic_images:moving_object_frame", {}),  # t is required
        ("jev_cookbook.synthetic_images:moving_object_frame", {"t": 1.0, "start": 5}),
    ],
)
def test_reproduce_turns_unusable_parameters_into_value_errors(generator, parameters):
    with pytest.raises(ValueError):
        si.reproduce(generator, parameters)


@pytest.mark.parametrize("key", ["generator", "parameters", "path"])
def test_check_reproducible_names_a_missing_manifest_key(tmp_path, key):
    c = si.login_screen(seed=2)
    c.write(tmp_path, "assets/a.png")
    entry = c.manifest_entry(tmp_path, "assets/a.png", "A screen.")
    del entry[key]
    with pytest.raises(ValueError, match=key):
        si.check_reproducible(tmp_path, entry)


# -- Canvas.line bounds ----------------------------------------------------------------------------


@pytest.mark.parametrize("position", ["x0", "y0", "x1", "y1"])
@pytest.mark.parametrize("value", [8193, -8193])
def test_a_line_endpoint_beyond_8192_pixels_is_refused_before_anything_is_drawn(position, value):
    ends = {"x0": 0, "y0": 0, "x1": 0, "y1": 0, position: value}
    c = si.Canvas(640, 400)
    before = c.image.copy()
    with pytest.raises(ValueError, match="coordinate"):
        c.line(ends["x0"], ends["y0"], ends["x1"], ends["y1"], "ink")
    assert changed(before, c.image) is None


def test_a_line_far_past_the_canvas_is_refused_instead_of_walked_pixel_by_pixel():
    # the old code took one step per pixel of the 100000 and returned a Drawn for the visible part
    with pytest.raises(ValueError, match="coordinate"):
        si.Canvas(640, 400).line(0, 0, 100_000, 0, "ink")


def test_a_line_endpoint_at_8192_pixels_is_accepted_and_clipped():
    assert si.Canvas(640, 400).line(0, 0, 8192, 0, "ink").pixels == (0, 0, 640, 1)
    assert si.Canvas(640, 400).line(-8192, 5, 5, 5, "ink").pixels == (0, 5, 6, 6)


def test_a_line_brush_wider_than_1568_pixels_is_refused_and_1568_is_accepted():
    with pytest.raises(ValueError, match="width"):
        si.Canvas(640, 400).line(10, 10, 11, 10, "ink", 1569)
    # a 1568 brush centred on (10, 10) and (11, 10) covers the whole 640 x 400 canvas
    assert si.Canvas(640, 400).line(10, 10, 11, 10, "ink", 1568).pixels == (0, 0, 640, 400)


# -- all-blank text is refused ----------------------------------------------------------------------


def test_a_run_of_spaces_has_no_visible_ink_and_is_refused():
    for text in ("   ", " "):
        with pytest.raises(ValueError, match="no visible"):
            blank().text(10, 10, text)
    block = blank().text_block(10, 10, ["A", "  "])  # a blank line is skipped, not refused
    assert len(block.parts) == 1
    with pytest.raises(ValueError, match="no visible"):
        blank().text_block(10, 10, ["  ", " "])
    with pytest.raises(ValueError, match="no visible"):
        blank().text_input(10, 10, 200, 34, placeholder="  ")
    with pytest.raises(ValueError, match="no visible"):
        blank().centered_text((10, 10, 200, 60), "  ")


def test_text_with_a_letter_still_draws_and_a_space_still_measures():
    assert blank().text(10, 10, "A B").attrs["text"] == "A B"
    assert blank().text(10, 10, " A").attrs["text"] == " A"
    assert si.text_width(" ", 1) == 5  # layout code measures spaces at scale 1


# -- save_frames pads each index to the width of the largest one ------------------------------------


@pytest.mark.parametrize("count", [1, 2, 100, 101, 1000, 1001])
def test_save_frames_pads_each_index_to_the_width_of_the_largest(monkeypatch, tmp_path, count):
    written = []

    def record(canvas, recipe_dir, path, *, overwrite=False):
        written.append(path)
        return "created"

    monkeypatch.setattr(si, "write_asset", record)
    canvas = si.Canvas(280, 280)
    frames = [si.Frame(float(i), canvas) for i in range(count)]
    pairs = si.save_frames(frames, tmp_path, "belt")
    width = max(2, len(str(count - 1)))
    expected = [f"assets/belt-{i:0{width}d}.png" for i in range(count)]
    assert written == expected
    assert [path for _, path in pairs] == expected
    assert written == sorted(written)  # index order is sort order, so a listing reads in order


# -- which deny-list entry catches which seed -----------------------------------------------------

# Each seed's first draw spells a word that exactly one entry of _DENY catches. Removing that
# entry, and only that entry, makes fictional_name return the first draw again.
SINGLE_CATCH = [
    ("FAG", 159, "FAGIPON"),
    ("RAPE", 280, "SARAPEM"),
    ("SEX", 343, "REGASEX"),
    ("TIT", 753, "TITIR"),
    ("NAZI", 1275, "NAZIR"),
    ("BONER", 1996, "BONER"),
    ("NIG", 2862, "NIGEDUR"),
    ("ANUS", 5025, "BANUS"),
]


@pytest.mark.parametrize(("entry", "seed", "word"), SINGLE_CATCH)
def test_a_single_catch_seed_is_rejected_by_exactly_its_entry(entry, seed, word):
    assert first_draw(seed) == word
    assert {w for w in si._DENY if w in word} == {entry}
    name = si.fictional_name(seed)
    assert name != word
    assert not any(w in name for w in si._DENY)


@pytest.mark.parametrize(("entry", "seed", "word"), SINGLE_CATCH)
def test_removing_one_entry_lets_its_single_catch_seed_return_its_first_draw(
    monkeypatch, entry, seed, word
):
    monkeypatch.setattr(si, "_DENY", tuple(w for w in si._DENY if w != entry))
    assert si.fictional_name(seed) == first_draw(seed) == word


@functools.cache
def reachable_deny_entries() -> frozenset[str]:
    """Which _DENY entries some raw name contains, from one pass over every raw name."""
    pattern = re.compile("|".join(si._DENY))
    found: set[str] = set()
    for name in raw_names():
        if pattern.search(name):
            found.update(word for word in si._DENY if word in name)
    return frozenset(found)


def test_exactly_eight_deny_entries_are_reachable_from_the_syllable_table():
    # COCK, CUNT, DICK, FUCK, PISS and SHIT cannot be spelled: the syllable table has no C and no
    # H, and two S in a row never occur. They are kept as defence in depth. If a future edit to
    # the syllable table makes one of them reachable, this test fails, and that entry then needs
    # a seed pin in SINGLE_CATCH: a seed whose first draw spells it and no other entry.
    assert reachable_deny_entries() == frozenset(
        {"ANUS", "BONER", "FAG", "NAZI", "NIG", "RAPE", "SEX", "TIT"}
    )


# -- file modes of written assets (POSIX) ----------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes; Windows has no umask")
@pytest.mark.parametrize(("umask", "mode"), [(0o022, 0o644), (0o002, 0o664)])
def test_written_assets_follow_the_umask_not_the_private_mode_of_a_temporary_file(
    tmp_path, umask, mode
):
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    target = recipe / "assets" / "a.png"
    previous = os.umask(umask)
    try:
        assert si.login_screen(state="normal").write(recipe, "assets/a.png") == "created"
        assert stat.S_IMODE(target.stat().st_mode) == mode
        assert si.login_screen(state="error").write(recipe, "assets/a.png", overwrite=True) == (
            "rewritten"
        )
        assert stat.S_IMODE(target.stat().st_mode) == mode
    finally:
        os.umask(previous)
    assert sorted(p.name for p in (recipe / "assets").iterdir()) == ["a.png"]  # no temporary left


# -- a committed file that cannot be decoded is unreadable, not a changed picture ------------------


def truncated_copy() -> bytes:
    data = si.login_screen().png()
    return data[: len(data) // 2]


UNREADABLE = {
    "text": lambda: b"not a png at all",
    "empty": lambda: b"",
    "truncated": truncated_copy,
}


@pytest.mark.parametrize("kind", sorted(UNREADABLE))
def test_an_undecodable_committed_file_is_unreadable_and_is_kept_unless_overwritten(tmp_path, kind):
    c = si.login_screen()
    target = tmp_path / "assets" / "a.png"
    target.parent.mkdir()
    damaged = UNREADABLE[kind]()
    target.write_bytes(damaged)
    with pytest.raises(si.RegenerationMismatch, match="cannot be read as an image") as raised:
        c.write(tmp_path, "assets/a.png")
    assert "generator, its parameters or the seed changed the picture" not in str(raised.value)
    assert target.read_bytes() == damaged
    assert c.write(tmp_path, "assets/a.png", overwrite=True) == "rewritten"
    assert target.read_bytes() == c.png()


@pytest.mark.parametrize("kind", sorted(UNREADABLE))
def test_check_reproducible_reports_an_undecodable_committed_file_as_unreadable(tmp_path, kind):
    c = si.login_screen()
    c.write(tmp_path, "assets/a.png")
    entry = c.manifest_entry(tmp_path, "assets/a.png", "A screen.")
    target = tmp_path / "assets" / "a.png"
    damaged = UNREADABLE[kind]()
    target.write_bytes(damaged)
    with pytest.raises(si.RegenerationMismatch, match="cannot be read as an image") as raised:
        si.check_reproducible(tmp_path, entry)
    assert "generator, its parameters or the seed changed the picture" not in str(raised.value)
    assert target.read_bytes() == damaged


# -- the CI leg that runs the byte pins -------------------------------------------------------------


def python_floor() -> tuple[int, int]:
    """The requires-python floor of pyproject.toml, read with a regular expression."""
    text = (REPO / "pyproject.toml").read_text("utf-8")
    match = re.search(r'requires-python\s*=\s*"\s*>=\s*(\d+)\.(\d+)\s*"', text)
    assert match, 'pyproject.toml has no requires-python = ">=X.Y" line'
    return int(match.group(1)), int(match.group(2))


def byte_pins_skipped_on_ci_floor_leg(environ, version_info, canonical, floor):
    """Why the byte pins skip on this run, or None.

    They skip only on a GitHub Actions run of the floor interpreter without the canonical Pillow.
    The unpinned floor leg is the one CI job that resolves the canonical Pillow and runs them.
    """
    on_floor = tuple(version_info[:2]) == tuple(floor)
    if environ.get("GITHUB_ACTIONS") == "true" and on_floor and not canonical:
        return f"CI runs Python {floor[0]}.{floor[1]} without the canonical Pillow"
    return None


@pytest.mark.parametrize(
    ("environ", "version", "canonical", "skipped"),
    [
        ({"GITHUB_ACTIONS": "true"}, (3, 10, 12), False, True),  # floor leg, newer Pillow
        ({"GITHUB_ACTIONS": "true"}, (3, 10, 12), True, False),  # floor leg, canonical Pillow
        ({"GITHUB_ACTIONS": "true"}, (3, 14, 0), False, False),  # newest leg: expected to skip
        ({}, (3, 10, 12), False, False),  # a local run is never a CI leg
    ],
)
def test_the_floor_leg_guard_reports_a_skip_only_where_ci_lacks_the_canonical_pillow(
    environ, version, canonical, skipped
):
    reason = byte_pins_skipped_on_ci_floor_leg(environ, version, canonical, (3, 10))
    assert (reason is not None) is skipped


def test_the_ci_leg_that_runs_the_byte_pins_still_runs_them():
    reason = byte_pins_skipped_on_ci_floor_leg(
        os.environ, sys.version_info, si.bytes_are_canonical(), python_floor()
    )
    assert reason is None, (
        f"{reason}. The unpinned floor-Python CI leg (Tests (py3.10)) is the only one that checks "
        "the PNG byte pins. A Pillow release that this leg now resolves, or a zlib change, turns "
        "them off silently. Either pin that leg to the canonical Pillow, or re-record "
        "CANONICAL_PILLOW and the GOLDEN digests per docs/synthetic-images.md."
    )


def test_the_floor_is_python_3_10():
    assert python_floor() == (3, 10)


def test_the_ci_matrix_keeps_the_job_name_template_and_the_floor_entry():
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    assert "Tests (py${{ matrix.python-version }})" in text
    assert re.search(r'python-version:\s*\[[^\]]*"3\.10"', text)


# -- the docs name the job that runs the byte pins ----------------------------------------------------


def byte_pin_ci_section() -> str:
    text = DOC.read_text("utf-8")
    start = text.index("Which CI job runs the byte pins")
    return text[start : text.index("\n## ", start)]


def test_the_docs_name_the_job_that_runs_the_byte_pins_and_point_at_the_guard_test():
    section = byte_pin_ci_section()
    assert "Tests (py3.10)" in section
    assert "Tests (py3.14)" in section
    assert "the guard test" in section


# -- Cyrillic and Greek letters ---------------------------------------------------------------------
# Every non-ASCII character in this section is written as a \u escape with its Unicode name in a
# comment, so a look-alike letter (a Cyrillic A that looks like a Latin A) is unambiguous in review.

# The ASCII part of SUPPORTED_CHARACTERS before the extension, in table order. Built from pieces so
# the literal is not one 36-character run that the hygiene scanner reads as a token.
ORIGINAL = string.ascii_uppercase + string.digits + " .,:;-_+=/()!?%#*'\"><[]"
PRIVET_LOWER = "\u043f\u0440\u0438\u0432\u0435\u0442"  # small PE ER I VE IE TE: "privet", hello
PRIVET = "\u041f\u0420\u0418\u0412\u0415\u0422"  # capital PE ER I VE IE TE
VNIMANIE = "\u0412\u041d\u0418\u041c\u0410\u041d\u0418\u0415"  # capital VE EN I EM A EN I IE
MAMA_CYRILLIC = "\u041c\u0410\u041c\u0410"  # capital EM A EM A: every letter looks Latin
LOGOS = "\u039b\u039f\u0393\u039f\u03a3"  # capital LAMDA OMICRON GAMMA OMICRON SIGMA (Greek)
UNSUPPORTED = (
    "\u0401",  # CAPITAL IO
    "\u0386",  # GREEK CAPITAL ALPHA WITH TONOS
    "\u00e9",  # LATIN SMALL E WITH ACUTE
    "\u4e2d",  # CJK ideograph (middle)
    "\u0627",  # ARABIC LETTER ALEF
    "\u05d0",  # HEBREW LETTER ALEF
)

CYRILLIC_TO_LATIN = {
    "\u0410": "A",  # CAPITAL A (looks like Latin A)
    "\u0412": "B",  # CAPITAL VE
    "\u0415": "E",  # CAPITAL IE
    "\u041a": "K",  # CAPITAL KA
    "\u041c": "M",  # CAPITAL EM
    "\u041d": "H",  # CAPITAL EN
    "\u041e": "O",  # CAPITAL O
    "\u0420": "P",  # CAPITAL ER
    "\u0421": "C",  # CAPITAL ES
    "\u0422": "T",  # CAPITAL TE
    "\u0425": "X",  # CAPITAL HA
}
GREEK_TO_LATIN = {
    "\u0391": "A",  # CAPITAL ALPHA
    "\u0392": "B",  # CAPITAL BETA
    "\u0395": "E",  # CAPITAL EPSILON
    "\u0396": "Z",  # CAPITAL ZETA
    "\u0397": "H",  # CAPITAL ETA
    "\u0399": "I",  # CAPITAL IOTA
    "\u039a": "K",  # CAPITAL KAPPA
    "\u039c": "M",  # CAPITAL MU
    "\u039d": "N",  # CAPITAL NU
    "\u039f": "O",  # CAPITAL OMICRON
    "\u03a1": "P",  # CAPITAL RHO
    "\u03a4": "T",  # CAPITAL TAU
    "\u03a5": "Y",  # CAPITAL UPSILON
    "\u03a7": "X",  # CAPITAL CHI
}
CYRILLIC_GREEK = [
    ("\u0413", "\u0393"),  # CAPITAL GHE and CAPITAL GAMMA
    ("\u041f", "\u03a0"),  # CAPITAL PE and CAPITAL PI
    ("\u0424", "\u03a6"),  # CAPITAL EF and CAPITAL PHI
]


def shape_classes() -> set[frozenset[str]]:
    """Groups of supported characters with one identical 5 x 7 shape (single characters dropped)."""
    groups: dict[str, set[str]] = {}
    for char in si.SUPPORTED_CHARACTERS:
        groups.setdefault(si._GLYPH_SOURCE[char], set()).add(char)
    return {frozenset(group) for group in groups.values() if len(group) > 1}


def linked_classes(pairs) -> set[frozenset[str]]:
    """The classes of the graph whose edges are ``pairs`` (union-find without path compression)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)
    groups: dict[str, set[str]] = {}
    for x in list(parent):
        groups.setdefault(find(x), set()).add(x)
    return {frozenset(group) for group in groups.values() if len(group) > 1}


def test_the_supported_characters_are_the_original_set_then_cyrillic_then_greek():
    cyrillic, greek = si.SUPPORTED_SCRIPTS["Cyrillic"], si.SUPPORTED_SCRIPTS["Greek"]
    assert si.SUPPORTED_CHARACTERS == ORIGINAL + cyrillic + greek
    assert si.SUPPORTED_SCRIPTS["Latin"] == "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    assert cyrillic == "".join(chr(c) for c in range(0x410, 0x430))  # U+0410..U+042F, no YO
    assert greek == "".join(chr(c) for c in range(0x391, 0x3AA) if c != 0x3A2)  # no U+03A2
    assert (len(si.SUPPORTED_SCRIPTS["Latin"]), len(cyrillic), len(greek)) == (26, 32, 24)


def test_the_script_helpers_are_public():
    assert {"SUPPORTED_SCRIPTS", "text_scripts", "looks_like_latin"} <= set(si.__all__)


def test_the_hand_drawn_non_ascii_shapes_are_pinned_by_digest():
    # The 56 Cyrillic and Greek shapes are a deliberate pin. To re-record one after a deliberate
    # change, run the same expression on si._GLYPH_SOURCE, look at the shapes, and paste the new
    # hexdigest here.
    entries = {c: src for c, src in si._GLYPH_SOURCE.items() if not c.isascii()}
    assert len(entries) == 56
    text = "\n".join(f"{ord(c):04X} {src}" for c, src in sorted(entries.items()))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert digest == "b6d3441d5f9e2754d18adf79474f719217f8a2f9726d9b860a88fd8fc438f21a"
    assert set(entries) == set(si.SUPPORTED_SCRIPTS["Cyrillic"] + si.SUPPORTED_SCRIPTS["Greek"])


def test_cyrillic_de_has_a_flat_top_and_feet():
    shape = si._GLYPH_SOURCE["\N{CYRILLIC CAPITAL LETTER DE}"]  # CYRILLIC CAPITAL DE
    assert shape == ".###./.#.#./.#.#./.#.#./#####/#...#/#...#"
    assert shape.split("/")[0] == ".###."  # the flat top bar, not the old ..##.
    assert [char for char, src in si._GLYPH_SOURCE.items() if src == shape] == [
        "\N{CYRILLIC CAPITAL LETTER DE}"
    ]
    c = blank()
    c.text(10, 10, "\N{CYRILLIC CAPITAL LETTER DE}", (0, 0, 0), 1)
    px = c.image.load()
    assert px[11, 10] == (0, 0, 0)  # column 1 of row 0 is ink
    assert px[10, 10] == BLANK  # column 0 of row 0 is not


def test_the_shape_sharing_is_exactly_the_documented_set():
    expected = linked_classes(
        [*CYRILLIC_TO_LATIN.items(), *GREEK_TO_LATIN.items(), *CYRILLIC_GREEK]
    )
    assert shape_classes() == expected
    assert si._GLYPH_SOURCE["\u0417"] != si._GLYPH_SOURCE["3"]  # CAPITAL ZE differs from digit 3
    assert si._GLYPH_SOURCE["\u0423"] != si._GLYPH_SOURCE["Y"]  # CAPITAL U differs from Latin Y


def test_lower_case_cyrillic_and_greek_fold_to_capitals():
    assert blank().text(10, 10, PRIVET_LOWER).attrs["text"] == PRIVET
    assert blank().text(10, 10, "\u03c2").attrs["text"] == "\u03a3"  # final sigma folds to sigma


def test_decomposed_input_is_normalised_to_one_letter_and_text_width_counts_letters():
    box = blank().text(10, 10, "\u0438\u0306", "ink", 1)  # small I then combining breve
    assert box.attrs["text"] == "\u0419"  # CAPITAL SHORT I
    assert box.width == 5
    assert si.text_width("\u0438\u0306", 1) == 5
    assert si.text_width(PRIVET, 1) == (6 * 6 - 1) * 1  # six letters, not twelve code units


@pytest.mark.parametrize("word", [PRIVET, LOGOS])
def test_text_ink_stays_inside_the_box_for_a_cyrillic_and_a_greek_word(word):
    c = blank()
    box = c.text(30, 40, word, "ink", 3)
    ink = changed(Image.new("RGB", c.size, c.background), c.image)
    assert ink is not None
    assert box.left <= ink[0] and ink[2] <= box.right
    assert box.top <= ink[1] and ink[3] <= box.bottom


def test_drawing_a_cyrillic_word_is_deterministic():
    first, second = blank(), blank()
    first.text(10, 10, VNIMANIE, "ink", 2)
    second.text(10, 10, VNIMANIE, "ink", 2)
    assert first.image.tobytes() == second.image.tobytes()


def test_cyrillic_vnimanie_draws_differently_from_latin_bhnmahne():
    # Latin N stands where the Cyrillic I (CAPITAL I, a shape of its own) stands, so the pictures
    # differ even though the two strings have the same length
    latin, cyrillic = blank(), blank()
    latin.text(10, 10, "BHNMAHNE", "ink", 2)
    cyrillic.text(10, 10, VNIMANIE, "ink", 2)
    assert latin.image.tobytes() != cyrillic.image.tobytes()


def test_text_scripts_names_the_scripts_used_in_fixed_order():
    assert si.text_scripts("ABC 123") == ("Latin",)
    assert si.text_scripts(PRIVET) == ("Cyrillic",)
    assert si.text_scripts("A\u0411\u0393") == ("Latin", "Cyrillic", "Greek")  # BE, GAMMA
    assert si.text_scripts("123 .,!") == ()
    assert si.text_scripts(PRIVET_LOWER) == ("Cyrillic",)  # lower case is folded first
    assert si.text_scripts("abc") == ("Latin",)
    with pytest.raises(ValueError):
        si.text_scripts("caf\u00e9")


def test_looks_like_latin_compares_shapes_so_a_homoglyph_word_passes_and_proves_nothing():
    assert si.looks_like_latin("HELLO") is True
    assert si.looks_like_latin(MAMA_CYRILLIC) is True
    assert si.looks_like_latin(PRIVET) is False
    assert si.looks_like_latin("\u0391\u0392\u0393") is False  # CAPITAL ALPHA, BETA, GAMMA


def test_a_homoglyph_word_draws_the_same_pixels_as_latin_but_reports_its_own_text():
    latin, cyrillic = blank(), blank()
    latin_box = latin.text(10, 10, "MAMA", "ink", 2)
    cyrillic_box = cyrillic.text(10, 10, MAMA_CYRILLIC, "ink", 2)
    assert latin.image.tobytes() == cyrillic.image.tobytes()
    assert latin_box.attrs["text"] == "MAMA"
    assert cyrillic_box.attrs["text"] == MAMA_CYRILLIC


@pytest.mark.parametrize("char", UNSUPPORTED)
def test_a_letter_outside_latin_cyrillic_and_greek_is_refused_with_no_glyph(char):
    with pytest.raises(ValueError, match="no glyph"):
        blank().text(0, 0, char)


@pytest.mark.parametrize("text", ["caf\u00e9", "cafe\u0301"])  # precomposed and decomposed
def test_a_word_with_an_accent_is_refused_in_either_spelling(text):
    with pytest.raises(ValueError, match="no glyph"):
        blank().text(0, 0, text)


# MICRO SIGN upper-cases to GREEK CAPITAL MU, which draws as a Latin M, so "5 us" would read "5 MS".
# Every entry point that folds refuses it by name instead.
@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(lambda: blank().text(10, 10, "5 \N{MICRO SIGN}s"), id="text"),  # MICRO SIGN
        pytest.param(lambda: si.text_width("5 \N{MICRO SIGN}s"), id="text_width"),  # MICRO SIGN
        pytest.param(lambda: si.text_scripts("\N{MICRO SIGN}"), id="text_scripts"),  # MICRO SIGN
        pytest.param(lambda: si.looks_like_latin("\N{MICRO SIGN}"), id="looks_like_latin"),
    ],
)
def test_the_micro_sign_is_refused_by_name_not_drawn_as_a_latin_m(entry):
    with pytest.raises(ValueError, match="MICRO SIGN") as info:
        entry()
    assert "U+00B5" in str(info.value)


def test_the_ohm_and_kelvin_signs_keep_their_canonical_folds():
    ohm = blank()
    ohm_box = ohm.text(10, 10, "\N{OHM SIGN}")  # OHM SIGN, which NFC folds to GREEK CAPITAL OMEGA
    assert ohm_box.attrs["text"] == "\N{GREEK CAPITAL LETTER OMEGA}"  # GREEK CAPITAL OMEGA
    assert changed(Image.new("RGB", ohm.size, ohm.background), ohm.image) is not None
    omega = blank()
    omega.text(10, 10, "\N{GREEK CAPITAL LETTER OMEGA}")
    assert ohm.image.tobytes() == omega.image.tobytes()
    kelvin = blank()
    kelvin_box = kelvin.text(10, 10, "\N{KELVIN SIGN}")  # KELVIN SIGN, which NFC folds to LATIN K
    assert kelvin_box.attrs["text"] == "K"
    latin_k = blank()
    latin_k.text(10, 10, "K")
    assert kelvin.image.tobytes() == latin_k.image.tobytes()
    # GREEK SMALL LETTER MU still upper-cases to GREEK CAPITAL MU; only MICRO SIGN is refused
    small_mu = blank().text(10, 10, "\N{GREEK SMALL LETTER MU}")
    assert small_mu.attrs["text"] == "\N{GREEK CAPITAL LETTER MU}"  # small MU folds up to capital


def test_the_docs_list_both_alphabets_and_say_a_synthetic_test_does_not_prove_quality():
    text = DOC.read_text("utf-8")
    for letter in si.SUPPORTED_SCRIPTS["Cyrillic"] + si.SUPPORTED_SCRIPTS["Greek"]:
        assert letter in text, f"U+{ord(letter):04X} is not listed in {DOC.name}"
    assert "Cyrillic" in text and "Greek" in text
    assert "does not prove" in text
