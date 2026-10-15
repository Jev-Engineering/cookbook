"""Locate visible document marks; never authenticate a signer or grant an approval."""

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from jev_cookbook import Box, Noul
from jev_cookbook.evaluation import evaluate_outcomes
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import (
    box_iou,
    crop_box,
    draw_boxes,
    image_asset,
    image_reference,
    normalized_box,
    normalized_to_pixels,
    run_record,
)

REVIEW = "review"
PRESENCE_CANDIDATES = (0.80, 0.90, 0.95)
BOX_CANDIDATES = (0.70, 0.85, 0.95)
DEMO_PRESENCE = 0.90
OBJECTIVE = "correct_resolutions_minus_twice_wrong_crops"
IOU_TARGET = 0.50
TARGETS = {
    "signature": "the handwritten signature mark, excluding the printed name and blank line",
    "stamp": "an approval stamp containing APPROVED, excluding decorative seals",
}


@dataclass(frozen=True)
class Policy:
    presence: float
    box: float

    def __post_init__(self):
        if not _probability(self.presence) or not 0.5 < self.presence <= 1:
            raise ValueError("presence threshold must be in (0.5, 1]")
        if not _probability(self.box):
            raise ValueError("box threshold must be in [0, 1]")


@dataclass(frozen=True)
class Observation:
    judgments: dict
    location: object | None
    accounting: tuple = ()


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str
    box: dict | None = None
    pixels: tuple | None = None


class RequestBudget:
    """Cap logical requests before calling a backend; the live backend caps retries too."""

    def __init__(self, limit=52):
        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a nonnegative integer")
        self.limit = limit
        self.used = 0

    def spend(self):
        if self.used >= self.limit:
            raise RuntimeError("document request budget exhausted")
        self.used += 1


def _probability(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 1
    )


def request_data(fields, recipe_dir):
    """Whitelist pixels and the requested mark; neither filenames nor labels reach Jev."""
    kind = fields["kind"]
    if kind not in TARGETS:
        raise ValueError("unsupported requested mark")
    asset = image_asset(Path(recipe_dir) / fields["image"])
    ref = image_reference(asset)
    return {"document": ref, "requested_mark": TARGETS[kind]}, {ref: asset}


def build_questions():
    """The two independent judgments are batched in one image-bearing request."""
    return {
        "present": Noul(
            instructions=(
                "The document visibly contains at least one instance of the requested mark. "
                "Judge visible marks only; printed names and empty signature lines are not "
                "handwritten signatures. A decorative seal is not an APPROVED stamp."
            )
        ),
        "unique": Noul(
            instructions=(
                "Exactly one visible region matches the requested mark; there is no second "
                "equally plausible matching region. This statement is false if none is visible."
            )
        ),
    }


def box_questions():
    return {
        "mark_box": Box(
            instructions=(
                "Locate the one requested mark. Enclose all of its visible ink, including the "
                "outer border of a stamp, with a tight axis-aligned rectangle. Exclude printed "
                "names, signature guide lines and surrounding form fields. For clipped marks "
                "enclose only the visible ink. Do not infer authenticity, identity or authority."
            )
        )
    }


def first_gate(judgments, threshold):
    Policy(threshold, 0)
    p = getattr(judgments.get("present"), "noul", None)
    u = getattr(judgments.get("unique"), "noul", None)
    if not _probability(p) or not _probability(u):
        return Outcome(REVIEW, "invalid presence or uniqueness answer")
    if 1 - p >= threshold:
        if u >= threshold:
            return Outcome(REVIEW, "contradictory absence and uniqueness")
        return Outcome("absent", "requested mark judged absent")
    if p < threshold:
        return Outcome(REVIEW, "presence uncertain")
    if u < threshold:
        return Outcome(REVIEW, "multiple candidates or uniqueness uncertain")
    return None


def observe(backend, fields, recipe_dir, presence_threshold, budget):
    """A Box request depends on the first gate. Never retry a rejected candidate."""
    state, assets = request_data(fields, recipe_dir)
    budget.spend()
    result = backend.decide(state, build_questions(), assets=assets)
    judgments = dict(result.answers)
    accounting = [run_record(result, mode=backend.mode)]
    location = None
    if first_gate(judgments, presence_threshold) is None:
        budget.spend()
        result = backend.decide(state, box_questions(), assets=assets)
        location = result["mark_box"]
        accounting.append(run_record(result, mode=backend.mode))
    return Observation(judgments, location, tuple(accounting))


def dimensions(fields, recipe_dir):
    with Image.open(Path(recipe_dir) / fields["image"]) as image:
        return image.size


def route(observation, policy, size):
    blocked = first_gate(observation.judgments, policy.presence)
    if blocked is not None:
        return blocked
    answer = observation.location
    confidence = getattr(answer, "confidence", None)
    if confidence is None:
        return Outcome(REVIEW, "box confidence unavailable")
    if not _probability(confidence):
        return Outcome(REVIEW, "invalid box confidence")
    if confidence < policy.box:
        return Outcome(REVIEW, "confidence below the threshold")
    try:
        box = normalized_box(answer)
        pixels = normalized_to_pixels(box, *size)
    except (ValueError, TypeError, AttributeError):
        return Outcome(REVIEW, "invalid box or image dimensions")
    return Outcome("located", "visible mark proposed for a crop", box, pixels)


def simulate(ident, outcome, actions, reviews):
    """The sole allowed action describes a crop. It cannot approve a document."""
    if outcome.status == "located":
        actions.record(
            "simulate_crop",
            {"example": ident, "pixels": list(outcome.pixels)},
            rule="presence, uniqueness, confidence and bounds gates",
        )
    elif outcome.status == REVIEW:
        reviews.submit({"example": ident}, outcome.reason)


def resolved_correct(outcome, gold):
    if outcome.status == REVIEW:
        return False
    if not gold["present"]:
        return outcome.status == "absent"
    return (
        gold["unique"]
        and outcome.box is not None
        and box_iou(outcome.box, gold["boxes"][0]) >= IOU_TARGET
    )


def summarize(examples, outcomes, labels):
    """IoU includes zero for every missed unique present mark, including abstentions."""
    pairs = [(outcomes[e.id], labels[e.id]) for e in examples]
    accepted = [out.status != REVIEW for out, _ in pairs]
    correct = [resolved_correct(out, gold) for out, gold in pairs]
    selective = evaluate_outcomes(accepted, correct)
    positives = [(out, gold) for out, gold in pairs if gold["present"] and gold["unique"]]
    ious = [
        box_iou(out.box, gold["boxes"][0]) if out.box is not None else 0.0
        for out, gold in positives
    ]
    wrong_crops = sum(
        out.status == "located" and not resolved_correct(out, gold) for out, gold in pairs
    )
    return {
        "N": len(pairs),
        "answered": sum(accepted),
        "correct_resolutions": sum(correct),
        "reviews": len(pairs) - sum(accepted),
        "coverage": selective.coverage,
        "answered_accuracy": selective.accuracy,
        "answered_risk": selective.risk,
        "unique_present_N": len(positives),
        "mean_iou_with_misses": sum(ious) / len(ious) if ious else 0.0,
        "misses": sum(out.box is None for out, _ in positives),
        "below_iou_target": sum(iou < IOU_TARGET for iou in ious),
        "absent_N": sum(not gold["present"] for _, gold in pairs),
        "absent_false_positives": sum(
            out.box is not None and not gold["present"] for out, gold in pairs
        ),
        "ambiguous_N": sum(gold["present"] and not gold["unique"] for _, gold in pairs),
        "ambiguous_crops": sum(
            out.box is not None and gold["present"] and not gold["unique"] for out, gold in pairs
        ),
        "wrong_crops": wrong_crops,
        "objective_value": sum(correct) - 2 * wrong_crops,
    }


def select_policy(examples, observations, labels, recipe_dir, *, objective):
    if objective != OBJECTIVE:
        raise ValueError("unsupported selection objective")
    if not examples or any(e.split != "validation" for e in examples):
        raise ValueError("only validation examples may select policy")
    rows = []
    for presence in PRESENCE_CANDIDATES:
        for box in BOX_CANDIDATES:
            policy = Policy(presence, box)
            outcomes = {
                e.id: route(observations[e.id], policy, dimensions(e.fields, recipe_dir))
                for e in examples
            }
            rows.append({"presence": presence, "box": box, **summarize(examples, outcomes, labels)})
    best = max(
        rows,
        key=lambda row: (
            row["objective_value"],
            row["correct_resolutions"],
            row["presence"],
            row["box"],
        ),
    )
    return Policy(best["presence"], best["box"]), rows


def baseline(fields, recipe_dir):
    """Fixed lower-page colored-ink component detector, with no labels or learned metadata."""
    with Image.open(Path(recipe_dir) / fields["image"]) as source:
        image = source.convert("RGB")
    width, height = image.size
    pixels = image.load()
    candidates = set()
    for y in range(height // 2, height - 40):
        for x in range(30, width - 30):
            red, green, blue = pixels[x, y]
            colored = (
                blue > red + 25 and blue > green + 15
                if fields["kind"] == "signature"
                else red > green + 35 and red > blue + 20
            )
            if colored:
                candidates.add((x, y))
    components = []
    while candidates:
        seed = min(candidates)
        candidates.remove(seed)
        pending, component = [seed], []
        while pending:
            x, y = pending.pop()
            component.append((x, y))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                neighbor = (x + dx, y + dy)
                if neighbor in candidates:
                    candidates.remove(neighbor)
                    pending.append(neighbor)
        if len(component) >= 50:
            components.append(component)
    if not components:
        return Outcome("absent", "no colored ink component in fixed lower-page region")
    component = max(components, key=len)
    xs, ys = zip(*component, strict=True)
    box = {
        "left": min(xs) / width,
        "top": min(ys) / height,
        "right": (max(xs) + 1) / width,
        "bottom": (max(ys) + 1) / height,
    }
    return Outcome(
        "located", "largest colored ink component", box, normalized_to_pixels(box, *image.size)
    )


def show_location(fields, recipe_dir, outcome):
    from matplotlib.figure import Figure

    with Image.open(Path(recipe_dir) / fields["image"]) as source:
        image = source.convert("RGB")
    fig = Figure(figsize=(9, 6), layout="constrained")
    whole, detail = fig.subplots(1, 2, gridspec_kw={"width_ratios": [1.2, 1]})
    whole.imshow(draw_boxes(image, {"proposed crop": outcome.box}) if outcome.box else image)
    whole.set_title("Synthetic document")
    whole.axis("off")
    if outcome.box:
        detail.imshow(crop_box(image, outcome.box, expand=0.10))
        detail.set_title("Visible ink crop (10% margin)")
    else:
        detail.text(0.5, 0.5, outcome.reason, ha="center", va="center", wrap=True)
        detail.set_title(outcome.status)
    detail.axis("off")
    return fig


def record_stage(backend, examples, recipe_dir, responses_file, presence_threshold):
    """Explicit opt-in recording, using triples and actual returned answers to gate Box."""
    from jev_cookbook import ReplayBackend, record

    budget = RequestBudget(2 * len(examples))
    for example in examples:
        state, assets = request_data(example.fields, recipe_dir)
        budget.spend()
        record(backend, [(state, build_questions(), assets)], responses_file)
        replay = ReplayBackend.from_json(responses_file)
        judgments = replay.decide(state, build_questions(), assets=assets).answers
        threshold = DEMO_PRESENCE if example.split == "demo" else presence_threshold
        if first_gate(judgments, threshold) is None:
            budget.spend()
            record(backend, [(state, box_questions(), assets)], responses_file)
    return budget.used


def empty_logs():
    return ActionLog(), ReviewQueue()
