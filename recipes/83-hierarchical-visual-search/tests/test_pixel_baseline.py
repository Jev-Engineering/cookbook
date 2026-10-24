"""Independent image and arithmetic oracles for the deterministic third arm."""

import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from jev_cookbook import load_helpers

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
PINK = (243, 134, 161)
GOLD = {"left": 0.125, "top": 0.25, "right": 0.375, "bottom": 0.5}


def canvas(size=(128, 96)):
    return Image.new("RGB", size, (254, 254, 254))


def paint_marker(image, origin, *, pink=PINK, white=(255, 255, 255), remove_white=0):
    """Draw a fixed 24px square and 75px plus without calling the fixture generator."""
    x, y = origin
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((x, y, x + 23, y + 23), fill=(30, 30, 30))
    drawing.rectangle((x + 2, y + 2, x + 21, y + 21), fill=pink)
    cross = {
        (dx, dy)
        for dx in range(24)
        for dy in range(24)
        if (11 <= dx <= 13 and 5 <= dy <= 18) or (5 <= dx <= 18 and 11 <= dy <= 13)
    }
    assert len(cross) == 75
    for dx, dy in sorted(cross)[remove_white:]:
        image.putpixel((x + dx, y + dy), white)


def view(image):
    return helpers.View(image, (0, 0, *image.size))


def expected_box(image, origin):
    x, y = origin
    return {
        "left": x / image.width,
        "top": y / image.height,
        "right": (x + 24) / image.width,
        "bottom": (y + 24) / image.height,
    }


@pytest.mark.parametrize("origin", [(17, 29), (0, 0), (104, 72)])
def test_complete_marker_recovers_outer_bounds_at_translations_and_edges(origin):
    image = canvas()
    paint_marker(image, origin)
    candidates = helpers.pixel_candidates(view(image))
    assert len(candidates) == 1
    assert candidates[0]["shape_score"] == 1
    assert candidates[0]["box"] == pytest.approx(expected_box(image, origin))
    outcome = helpers.pixel_baseline(view(image), shape_threshold=0.95)
    assert outcome.status == "localized"
    assert outcome.box == pytest.approx(expected_box(image, origin))
    assert outcome.calls == 0
    assert outcome.trace == ()


@pytest.mark.parametrize(
    ("pink", "detected"),
    [
        ((213, 134, 161), True),
        ((212, 134, 161), False),
        ((243, 104, 131), True),
        ((243, 103, 161), False),
    ],
)
def test_color_tolerance_includes_thirty_but_excludes_thirty_one(pink, detected):
    image = canvas()
    paint_marker(image, (20, 30), pink=pink)
    outcome = helpers.pixel_baseline(view(image), shape_threshold=0.95)
    assert outcome.status == ("localized" if detected else "absent")


@pytest.mark.parametrize(
    ("white", "detected"),
    [((245, 245, 245), True), ((255, 244, 255), False)],
)
def test_every_white_channel_must_reach_the_fixed_cutoff(white, detected):
    image = canvas()
    paint_marker(image, (20, 30), white=white)
    outcome = helpers.pixel_baseline(view(image), shape_threshold=0.65)
    assert outcome.status == ("localized" if detected else "absent")


def test_shape_threshold_is_inclusive_with_an_independent_sixty_of_seventy_five_oracle():
    image = canvas()
    paint_marker(image, (20, 30), remove_white=15)
    candidates = helpers.pixel_candidates(view(image))
    assert len(candidates) == 1
    assert candidates[0]["shape_score"] == 60 / 75
    assert helpers.pixel_baseline(view(image), shape_threshold=0.8).status == "localized"
    assert (
        helpers.pixel_baseline(view(image), shape_threshold=math.nextafter(0.8, 1)).status
        == "absent"
    )


def test_extra_white_pixels_reduce_template_iou_even_when_the_entire_plus_is_present():
    image = canvas()
    paint_marker(image, (20, 30))
    ImageDraw.Draw(image).rectangle((23, 33, 27, 37), fill="white")
    candidates = helpers.pixel_candidates(view(image))
    assert len(candidates) == 1
    assert candidates[0]["shape_score"] == 75 / 100
    assert helpers.pixel_baseline(view(image), shape_threshold=0.65).status == "localized"
    assert helpers.pixel_baseline(view(image), shape_threshold=0.8).status == "absent"


@pytest.mark.parametrize("threshold", [0, -0.1, 1.01, float("nan"), float("inf"), True])
def test_invalid_threshold_is_rejected_before_scanning_pixels(monkeypatch, threshold):
    def forbidden(_root):
        pytest.fail("invalid threshold reached the image scan")

    monkeypatch.setattr(helpers, "pixel_candidates", forbidden)
    with pytest.raises(ValueError):
        helpers.pixel_baseline(view(canvas()), shape_threshold=threshold)


def test_nearly_white_background_is_not_a_target():
    outcome = helpers.pixel_baseline(view(canvas()), shape_threshold=0.65)
    assert (outcome.status, outcome.box, outcome.calls, outcome.trace) == ("absent", None, 0, ())


@pytest.mark.parametrize("distractor", ["blue_plus", "pink_circle", "pink_diagonal", "single_bar"])
def test_color_and_shape_distractors_do_not_match(distractor):
    image = canvas()
    drawing = ImageDraw.Draw(image)
    if distractor == "blue_plus":
        paint_marker(image, (20, 30), pink=(31, 120, 168))
    elif distractor == "pink_circle":
        drawing.ellipse((20, 30, 43, 53), fill=PINK, outline=(30, 30, 30), width=2)
    else:
        drawing.rectangle((20, 30, 43, 53), fill=(30, 30, 30))
        drawing.rectangle((22, 32, 41, 51), fill=PINK)
        if distractor == "pink_diagonal":
            drawing.line((24, 34, 39, 49), fill=(30, 30, 30), width=3)
        else:
            drawing.rectangle((31, 35, 33, 48), fill="white")
    assert helpers.pixel_baseline(view(image), shape_threshold=0.65).status == "absent"


@pytest.mark.parametrize(
    ("inner_size", "candidate_count"),
    [
        ((11, 11), 0),
        ((12, 12), 1),
        ((48, 48), 1),
        ((49, 49), 0),
        ((12, 15), 1),
        ((12, 16), 0),
        ((15, 12), 1),
        ((16, 12), 0),
    ],
)
def test_component_size_and_aspect_ratio_have_explicit_inclusive_bounds(
    inner_size, candidate_count
):
    image = canvas()
    width, height = inner_size
    ImageDraw.Draw(image).rectangle((10, 10, 10 + width - 1, 10 + height - 1), fill=PINK)
    candidates = helpers.pixel_candidates(view(image))
    assert len(candidates) == candidate_count
    assert all(candidate["shape_score"] == 0 for candidate in candidates)


def test_multiple_matches_require_review_and_do_not_pick_the_first():
    image = canvas()
    paint_marker(image, (8, 8))
    paint_marker(image, (80, 60))
    outcome = helpers.pixel_baseline(view(image), shape_threshold=0.95)
    assert (outcome.status, outcome.reason, outcome.box) == (
        "review",
        "pixel_multiple_matches",
        None,
    )
    assert outcome.calls == 0


def test_repeated_detection_is_deterministic_and_never_builds_a_model_request(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("pixel baseline attempted to build or record a model request")

    for name in ("tile_request", "presence_request", "box_request", "record"):
        monkeypatch.setattr(helpers, name, forbidden)
    image = canvas()
    paint_marker(image, (40, 30))
    before = image.tobytes()
    first = helpers.pixel_baseline(view(image), shape_threshold=0.8)
    assert helpers.pixel_baseline(view(image), shape_threshold=0.8) == first
    assert first.calls == 0
    assert first.trace == ()
    assert image.tobytes() == before


def outcome(status, box=None):
    return helpers.Outcome(status, "test", box, 0, ())


def test_metric_partitions_separate_misses_wrong_rectangles_and_absent_false_positives():
    wrong_overlap = {"left": 0.25, "top": 0.25, "right": 0.5, "bottom": 0.5}
    outcomes = [
        outcome("localized", GOLD),
        outcome("localized", wrong_overlap),
        outcome("absent"),
        outcome("review"),
        outcome("localized", GOLD),
        outcome("absent"),
        outcome("review"),
        outcome("review"),
        outcome("localized", GOLD),
        outcome("absent"),
    ]
    labels = (
        [{"status": "present", "box": GOLD}] * 4
        + [{"status": "absent", "box": None}] * 3
        + [{"status": "review", "box": None}] * 3
    )
    metrics = helpers.summarize(outcomes, labels)
    assert metrics["n"] == 10
    assert metrics["gold_present"] == metrics["iou_denominator"] == 4
    assert metrics["gold_absent"] == metrics["gold_ambiguous"] == 3
    assert metrics["present_localization_hits"] == 1
    assert metrics["present_wrong_rectangles"] == 1
    assert metrics["present_misses"] == 2
    assert metrics["present_failed_localizations"] == 3
    assert metrics["present_localization_hit_rate"] == 0.25
    # The shifted delivered rectangle has IoU 1/3, although it fails the 0.5 hit criterion.
    assert metrics["mean_iou_all_present"] == pytest.approx((1 + 1 / 3) / 4)
    assert metrics["absent_false_positives"] == 1
    assert metrics["absent_false_positive_rate"] == pytest.approx(1 / 3)
    assert metrics["absent_correct"] == metrics["absent_reviews"] == 1
    assert metrics["hits"] == 3
    assert metrics["wrong_accepted"] == 5
    assert metrics["coverage"] == 0.7
    assert metrics["risk"] == pytest.approx(5 / 7)
    assert metrics["review"] == 3
    assert metrics["gold_present"] == (
        metrics["present_localization_hits"]
        + metrics["present_wrong_rectangles"]
        + metrics["present_misses"]
    )
    assert metrics["gold_absent"] == (
        metrics["absent_false_positives"] + metrics["absent_correct"] + metrics["absent_reviews"]
    )
    assert metrics["n"] == metrics["hits"] + metrics["wrong_accepted"] + 1 + 1


def test_exactly_half_iou_counts_as_a_localization_hit():
    half = {"left": 0.125, "top": 0.25, "right": 0.25, "bottom": 0.5}
    metrics = helpers.summarize([outcome("localized", half)], [{"status": "present", "box": GOLD}])
    assert metrics["mean_iou_all_present"] == 0.5
    assert metrics["present_localization_hits"] == 1
    assert metrics["present_failed_localizations"] == 0
    assert metrics["present_wrong_rectangles"] == 0


@pytest.mark.parametrize("gold_status", ["present", "absent", "review"])
def test_empty_metric_denominators_remain_undefined(gold_status):
    prediction = outcome("localized", GOLD) if gold_status == "present" else outcome(gold_status)
    metrics = helpers.summarize(
        [prediction],
        [{"status": gold_status, "box": GOLD if gold_status == "present" else None}],
    )
    if gold_status != "present":
        assert metrics["gold_present"] == metrics["iou_denominator"] == 0
        assert metrics["mean_iou_all_present"] is None
        assert metrics["present_localization_hit_rate"] is None
    if gold_status != "absent":
        assert metrics["gold_absent"] == 0
        assert metrics["absent_false_positive_rate"] is None
    if gold_status == "review":
        assert metrics["gold_ambiguous"] == 1
        assert metrics["coverage"] == 0
        assert metrics["risk"] is None
        assert metrics["hits"] == 1
        assert metrics["wrong_accepted"] == 0


def test_selector_rejects_held_out_examples_before_loading_pixels(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("held-out example reached pixel loading")

    monkeypatch.setattr(helpers, "load_view", forbidden)
    held_out = [SimpleNamespace(id="held-out", split="test", fields={"image": "missing.png"})]
    with pytest.raises(ValueError, match="validation"):
        helpers.select_pixel_threshold(held_out, {}, objective=helpers.PIXEL_OBJECTIVE)


def test_selector_requires_the_declared_objective_before_loading_pixels(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid objective reached pixel loading")

    monkeypatch.setattr(helpers, "load_view", forbidden)
    examples = [SimpleNamespace(id="v", split="validation", fields={"image": "missing.png"})]
    with pytest.raises(ValueError, match="objective"):
        helpers.select_pixel_threshold(examples, {}, objective="different objective")
    with pytest.raises(TypeError):
        helpers.select_pixel_threshold(examples, {})


def test_validation_selection_breaks_equal_scores_toward_the_higher_threshold(tmp_path):
    examples, labels = [], {}
    for index, status in enumerate(("present", "absent", "review")):
        image = canvas()
        if status != "absent":
            paint_marker(image, (8, 8))
        if status == "review":
            paint_marker(image, (80, 60))
        filename = f"validation-{index}.png"
        image.save(tmp_path / filename)
        ident = f"v{index}"
        examples.append(SimpleNamespace(id=ident, split="validation", fields={"image": filename}))
        labels[ident] = {
            "status": status,
            "box": expected_box(image, (8, 8)) if status == "present" else None,
        }
    threshold, rows = helpers.select_pixel_threshold(
        examples, labels, tmp_path, objective=helpers.PIXEL_OBJECTIVE
    )
    assert threshold == 0.95
    assert [row["shape_threshold"] for row in rows] == [0.65, 0.8, 0.95]
    assert all(row["hits"] == 3 and row["wrong_accepted"] == 0 for row in rows)
    assert all(row["calls"] == 0 for row in rows)


def test_validation_objective_can_select_below_the_maximum_threshold(tmp_path):
    image = canvas()
    paint_marker(image, (20, 30))
    ImageDraw.Draw(image).rectangle((23, 33, 27, 37), fill="white")
    image.save(tmp_path / "validation-target.png")
    canvas().save(tmp_path / "validation-empty.png")
    examples = [
        SimpleNamespace(id="target", split="validation", fields={"image": "validation-target.png"}),
        SimpleNamespace(id="empty", split="validation", fields={"image": "validation-empty.png"}),
    ]
    labels = {
        "target": {"status": "present", "box": expected_box(image, (20, 30))},
        "empty": {"status": "absent", "box": None},
    }
    threshold, rows = helpers.select_pixel_threshold(
        examples, labels, tmp_path, objective=helpers.PIXEL_OBJECTIVE
    )
    assert threshold == 0.65
    assert rows[0]["hits"] == 2
    assert rows[0]["wrong_accepted"] == 0
    assert all(row["hits"] == 1 and row["wrong_accepted"] == 1 for row in rows[1:])


def test_notebook_pins_the_pixel_objective_as_an_explicit_literal():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    calls = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        calls.extend(
            node
            for node in ast.walk(ast.parse("".join(cell["source"])))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "helpers"
            and node.func.attr == "select_pixel_threshold"
        )
    assert len(calls) == 1
    assert any(
        keyword.arg == "objective"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value == helpers.PIXEL_OBJECTIVE
        for keyword in calls[0].keywords
    )
