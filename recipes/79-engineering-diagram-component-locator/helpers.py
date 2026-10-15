"""Pixel-grounded requests and a bounded diagram-annotation policy."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import Box, Noul
from jev_cookbook.evaluation import evaluate_outcomes, select_confidence_threshold
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import (
    box_confidence,
    box_iou,
    image_asset,
    image_reference,
    localization_metrics,
    normalized_box,
    normalized_to_pixels,
    run_record,
)

TARGETS = {
    "V-101": "manual isolation valve",
    "V-102": "manual isolation valve",
    "C-201": "flanged pipe connector",
    "P-301": "pump symbol",
}
REVIEW = "review"
ACQUISITION_FLOOR = 0.4
IOU_MINIMUM = 0.5
INK = (30, 30, 30)
PAPER = (254, 254, 254)
FONT = ImageFont.load_default(size=16)


def build_state(fields, recipe_dir=Path(".")):
    """Allowlist the target and expose only the image and legitimate lookup context."""
    target = fields["target"]
    if target not in TARGETS:
        raise ValueError("target is outside Python's fixed label set")
    asset = image_asset(Path(recipe_dir) / fields["image"])
    reference = image_reference(asset)
    return {
        "diagram": reference,
        "target_label": target,
        "target_kind": TARGETS[target],
        "scope": "Process drawing above the legend. Follow label leaders; exclude legend samples.",
    }, {reference: asset}


def build_questions():
    """The two independent propositions share one request."""
    return {
        "present": Noul(
            instructions=(
                "At least one process symbol of target_kind is visibly linked to target_label "
                "in diagram. A partly clipped symbol can be present. Legend samples, free text, "
                "and labels linked to another kind of symbol do not count."
            )
        ),
        "unique": Noul(
            instructions=(
                "Exactly one process symbol of target_kind is unambiguously linked to "
                "target_label in diagram. Follow leader endpoints, not nearest text; duplicate "
                "labels or uncertain bindings make this proposition false."
            )
        ),
    }


def build_box_question():
    return {
        "component": Box(
            instructions=(
                "Enclose the single process symbol of target_kind linked to target_label in "
                "diagram. Use its symbol body only, including valve handle when shown; exclude "
                "text, label leaders, and long connecting pipes. Return normalized edges."
            )
        )
    }


def certainty(answer):
    return abs(2 * float(answer.noul) - 1)


def first_stage(result, threshold):
    if not ACQUISITION_FLOOR <= threshold <= 1:
        raise ValueError("threshold must be between acquisition floor and 1")
    present, unique = result["present"], result["unique"]
    if min(certainty(present), certainty(unique)) < threshold:
        return REVIEW
    if present.noul < 0.5 and unique.noul < 0.5:
        return "absent"
    if present.noul > 0.5 and unique.noul > 0.5:
        return "eligible"
    return REVIEW


@dataclass(frozen=True)
class Trace:
    first: object
    second: object | None
    requests: int
    records: tuple


@dataclass(frozen=True)
class Outcome:
    status: str
    box: dict | None
    reason: str


def collect(fields, backend, recipe_dir=Path("."), threshold=ACQUISITION_FLOOR):
    """At most two requests. No Box call until both propositions pass."""
    state, assets = build_state(fields, recipe_dir)
    first = backend.decide(state, build_questions(), assets=assets)
    results = [first]
    second = None
    if first_stage(first, threshold) == "eligible":
        second = backend.decide(state, build_box_question(), assets=assets)
        results.append(second)
    return Trace(
        first,
        second,
        len(results),
        tuple(run_record(result, mode=backend.mode) for result in results),
    )


def decide(trace, threshold):
    """Fail closed on uncertain binding, missing confidence, invalid or clipped boxes."""
    stage = first_stage(trace.first, threshold)
    if stage == "absent":
        return Outcome("absent", None, "confident absence")
    if stage == REVIEW:
        return Outcome(REVIEW, None, "presence or unique binding unresolved")
    if trace.second is None:
        return Outcome(REVIEW, None, "eligible target has no box answer")
    answer = trace.second["component"]
    try:
        confidence = box_confidence(answer)
        box = normalized_box(answer)
    except (ValueError, TypeError, KeyError, AttributeError):
        return Outcome(REVIEW, None, "invalid box or confidence")
    if confidence is None:
        return Outcome(REVIEW, None, "box confidence missing")
    if confidence < threshold:
        return Outcome(REVIEW, None, "confidence below the threshold")
    if min(box["left"], box["top"]) <= 0 or max(box["right"], box["bottom"]) >= 1:
        return Outcome(REVIEW, None, "symbol touches image boundary")
    if (box["right"] - box["left"]) * (box["bottom"] - box["top"]) > 0.15:
        return Outcome(REVIEW, None, "box exceeds symbol area limit")
    return Outcome("located", box, "presence, unique binding and box gates passed")


def correct(outcome, gold):
    if gold["status"] == "located":
        return outcome.status == "located" and box_iou(outcome.box, gold["box"]) >= IOU_MINIMUM
    return outcome.status == gold["status"]


def score(trace):
    """Real certainty values only; unconditional reviews have no selectable score."""
    outcome = decide(trace, ACQUISITION_FLOOR)
    if outcome.status == REVIEW:
        return None
    value = min(certainty(trace.first["present"]), certainty(trace.first["unique"]))
    if outcome.status == "located":
        value = min(value, box_confidence(trace.second["component"]))
    return value


def choose_threshold(traces, labels):
    """Maximize answered fraction subject to validation accepted accuracy >= 0.9."""
    candidates = [
        (trace, gold)
        for trace, gold in zip(traces, labels, strict=True)
        if score(trace) is not None
    ]
    return select_confidence_threshold(
        [correct(decide(trace, ACQUISITION_FLOOR), gold) for trace, gold in candidates],
        [score(trace) for trace, _ in candidates],
        target_accuracy=0.9,
    )


def summarize(outcomes, labels):
    accepted = [outcome.status != REVIEW for outcome in outcomes]
    selection = evaluate_outcomes(
        accepted, [correct(o, g) for o, g in zip(outcomes, labels, strict=True)]
    )
    # Ambiguous gold has no single box and is excluded from the localization denominator.
    resolved = [
        (o, g)
        for o, g in zip(outcomes, labels, strict=True)
        if o.status != REVIEW and g["status"] != REVIEW
    ]
    loc = (
        localization_metrics([g["box"] for _, g in resolved], [o.box for o, _ in resolved])
        if resolved
        else None
    )
    present = [(o, g) for o, g in zip(outcomes, labels, strict=True) if g["status"] == "located"]
    absent = [(o, g) for o, g in zip(outcomes, labels, strict=True) if g["status"] == "absent"]
    return {
        "N": len(outcomes),
        "answered": selection.n_answered,
        "review": sum(not a for a in accepted),
        "coverage": round(selection.coverage, 4),
        "accuracy": round(selection.accuracy, 4),
        "risk": round(selection.risk, 4),
        "localization_N": len(resolved),
        "resolved_mean_iou": None if loc is None else round(loc.mean_iou, 4),
        "resolved_misses": None if loc is None else loc.missed,
        "absent_N": len(absent),
        "false_positive_absence": sum(o.status == "located" for o, _ in absent),
        "present_N": len(present),
        "present_unlocalized_including_review": sum(o.status != "located" for o, _ in present),
        "present_wrong_box": sum(o.status == "located" and not correct(o, g) for o, g in present),
        "required_review_N": sum(g["status"] == REVIEW for g in labels),
        "required_review_accepted": sum(
            o.status != REVIEW and g["status"] == REVIEW
            for o, g in zip(outcomes, labels, strict=True)
        ),
    }


def simulate(ident, outcome, size, actions: ActionLog, reviews: ReviewQueue):
    if outcome.status == REVIEW:
        reviews.submit({"diagram": ident}, outcome.reason)
    elif outcome.status == "located":
        pixels = normalized_to_pixels(outcome.box, *size)
        actions.record(
            "annotate_diagram", {"diagram": ident, "pixels": list(pixels)}, rule=outcome.reason
        )
    return outcome


def symbol(kind, rotated=False):
    """Authored teaching glyphs, also the baseline's public canonical templates."""
    im = Image.new("RGB", (41, 41), PAPER)
    d = ImageDraw.Draw(im)
    d.line((0, 20, 40, 20), fill=INK, width=2)
    if kind == "valve":
        d.polygon([(5, 10), (20, 20), (5, 30)], fill=PAPER, outline=INK, width=2)
        d.polygon([(35, 10), (20, 20), (35, 30)], fill=PAPER, outline=INK, width=2)
        d.line((20, 20, 20, 4), fill=INK, width=2)
        d.line((12, 4, 28, 4), fill=INK, width=2)
    elif kind == "connector":
        d.line((16, 8, 16, 32), fill=INK, width=3)
        d.line((24, 8, 24, 32), fill=INK, width=3)
    elif kind == "pump":
        d.ellipse((5, 5, 35, 35), fill=PAPER, outline=INK, width=2)
        d.polygon([(13, 11), (28, 20), (13, 29)], fill=INK)
    elif kind == "junction":
        d.line((20, 0, 20, 40), fill=INK, width=2)
        d.ellipse((15, 15, 25, 25), fill=INK)
    else:
        raise ValueError("unknown teaching glyph")
    return im.transpose(Image.Transpose.ROTATE_90) if rotated else im


def template_matches(pixels, template):
    """Exact binary template search with cheap anchors before a full pixel comparison."""
    mask = np.asarray(template.convert("L")) < 90
    height, width = mask.shape
    ph, pw = pixels.shape
    shape = (ph - height + 1, pw - width + 1)
    if min(shape) < 1:
        return []
    candidates = np.ones(shape, dtype=bool)
    for value in (True, False):
        positions = np.argwhere(mask == value)
        for y, x in positions[:: max(1, len(positions) // 18)]:
            candidates &= pixels[y : y + shape[0], x : x + shape[1]] == value
    matches = []
    for y, x in np.argwhere(candidates):
        if np.array_equal(pixels[y : y + height, x : x + width], mask):
            matches.append((int(x), int(y)))
    return matches


def baseline(image, target):
    """Same pixels and allowed target; no fixture IDs, gold, or drawing coordinates."""
    if target not in TARGETS:
        raise ValueError("unknown target")
    width, height = image.size
    pixels = np.asarray(image.convert("L")) < 90
    pixels = pixels[: int(height * 0.78)]  # published page convention: legend occupies footer
    kind = {"V": "valve", "C": "connector", "P": "pump"}[target[0]]
    glyphs = template_matches(pixels, symbol(kind))
    label = Image.new("RGB", (48, 20), PAPER)
    ImageDraw.Draw(label).text((0, 0), target, font=FONT, fill=INK)
    labels = template_matches(pixels, label)
    if not labels:
        return Outcome("absent", None, "canonical tag pixels absent")
    bindings = []
    for x, y in glyphs:
        # Canonical convention: label sits centered 44 pixels above symbol center.
        if any(abs(lx - (x - 4)) <= 8 and abs(ly - (y - 24)) <= 8 for lx, ly in labels):
            bindings.append((x, y))
    if len(bindings) != 1:
        return Outcome(REVIEW, None, "fixed template or label region unresolved")
    x, y = bindings[0]
    left, top, right, bottom = {
        "valve": (4, 3, 37, 32),
        "connector": (14, 7, 27, 34),
        "pump": (4, 4, 37, 37),
    }[kind]
    return Outcome(
        "located",
        {
            "left": (x + left) / width,
            "top": (y + top) / height,
            "right": (x + right) / width,
            "bottom": (y + bottom) / height,
        },
        "canonical glyph and label region matched",
    )


def record_examples(
    backend, examples, destination, recipe_dir=Path("."), threshold=ACQUISITION_FLOOR
):
    """Opt-in capture using the same questions; no call occurs merely by importing helpers."""
    from jev_cookbook import ReplayBackend, record

    if not ACQUISITION_FLOOR <= threshold <= 1:
        raise ValueError("threshold must be between acquisition floor and 1")
    if Path(destination).exists() and ReplayBackend.from_json(Path(destination)).mode != "recorded":
        raise ValueError("capture destination must be fresh or already recorded")
    prepared = [build_state(example.fields, recipe_dir) for example in examples]
    report_first = record(
        backend, [(state, build_questions(), assets) for state, assets in prepared], destination
    )
    replay = ReplayBackend.from_json(Path(destination))
    dependent = []
    for state, assets in prepared:
        first = replay.decide(state, build_questions(), assets=assets)
        if first_stage(first, threshold) == "eligible":
            dependent.append((state, build_box_question(), assets))
    report_boxes = record(backend, dependent, destination)
    return report_first, report_boxes
