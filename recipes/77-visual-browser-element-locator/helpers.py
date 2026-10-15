"""Visual judgments propose a region; Python decides whether to simulate an action."""

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
    localization_metrics,
    normalized_box,
    normalized_to_pixels,
)

PRESENCE_CANDIDATES = (0.80, 0.90, 0.95)
BOX_CANDIDATES = (0.80, 0.90, 0.95)
IOU_TARGET = 0.50
OBJECTIVE = "task_success_then_fewer_unsafe_actions"
REVIEW = "review"
BASELINE_PIXELS = {
    "button": (306, 282, 466, 326),
    "input": (64, 138, 448, 182),
    "menu": (300, 104, 470, 144),
}


@dataclass(frozen=True)
class Policy:
    presence: float
    box: float

    def __post_init__(self):
        if not 0.5 < self.presence <= 1 or not 0 <= self.box <= 1:
            raise ValueError("invalid policy thresholds")


@dataclass(frozen=True)
class Observation:
    judgments: dict
    location: object | None


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str
    box: dict | None = None
    point: tuple | None = None


def request_data(fields, recipe_dir):
    """Use only the target description and an opaque, content-derived image reference."""
    asset = image_asset(Path(recipe_dir) / fields["image"])
    ref = image_reference(asset)
    state = {"screenshot": ref, "target": fields["target"], "kind": fields["kind"]}
    return state, {ref: asset}


def build_questions():
    """Independent propositions share the first image-bearing request."""
    return {
        "present": Noul(instructions="The screenshot visibly contains the named target control."),
        "unique": Noul(
            instructions=(
                "Exactly one visible control matches the target name and kind; "
                "there is no second equally plausible matching control."
            )
        ),
        "enabled": Noul(
            instructions=(
                "The named target control is visibly enabled for interaction, "
                "rather than greyed out, disabled, or covered."
            )
        ),
    }


def box_questions():
    return {
        "target_box": Box(
            instructions=(
                "Locate the single named target control in the screenshot. "
                "Return its complete outer rectangle, excluding its surrounding card "
                "and excluding any separate text label above an input."
            )
        )
    }


def first_gate(judgments, threshold):
    """Confident absence is an answer; uncertainty, duplicates and disability defer."""
    p = judgments["present"].noul
    if 1 - p >= threshold:
        return Outcome("absent", "target judged absent")
    if p < threshold:
        return Outcome(REVIEW, "presence uncertain")
    if judgments["unique"].noul < threshold:
        return Outcome(REVIEW, "target is ambiguous or uniqueness is uncertain")
    if judgments["enabled"].noul < threshold:
        return Outcome(REVIEW, "target is disabled or enabled state is uncertain")
    return None


def observe(backend, fields, recipe_dir, presence_threshold):
    """Request Box only after the first gate has passed."""
    state, assets = request_data(fields, recipe_dir)
    judgments = dict(backend.decide(state, build_questions(), assets=assets).answers)
    if first_gate(judgments, presence_threshold) is not None:
        return Observation(judgments, None)
    location = backend.decide(state, box_questions(), assets=assets)["target_box"]
    return Observation(judgments, location)


def route(observation, policy, dimensions):
    """Reject first, then derive a center from validated normalized coordinates."""
    blocked = first_gate(observation.judgments, policy.presence)
    if blocked is not None:
        return blocked
    answer = observation.location
    if answer is None or answer.confidence is None:
        return Outcome(REVIEW, "box confidence unavailable")
    if (
        isinstance(answer.confidence, bool)
        or not isinstance(answer.confidence, (int, float))
        or not math.isfinite(answer.confidence)
        or not 0 <= answer.confidence <= 1
    ):
        return Outcome(REVIEW, "box confidence invalid")
    if answer.confidence < policy.box:
        return Outcome(REVIEW, "confidence below the threshold")
    try:
        box = normalized_box(answer.box)
        width, height = dimensions
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise ValueError("invalid image dimensions")
        left, top, right, bottom = normalized_to_pixels(box, width, height)
    except (TypeError, ValueError, KeyError):
        return Outcome(REVIEW, "box outside image bounds or invalid")
    point = ((left + right - 1) // 2, (top + bottom - 1) // 2)
    if not (0 <= point[0] < width and 0 <= point[1] < height):
        return Outcome(REVIEW, "center outside image bounds")
    return Outcome("located", "all gates passed", box, point)


def dimensions(fields, recipe_dir):
    """Read actual image dimensions; do not trust a field supplied by a model."""
    with Image.open(Path(recipe_dir) / fields["image"]) as image:
        return image.size


def simulate(example, observation, policy, recipe_dir, actions=None, reviews=None):
    """Append an explicitly simulated action or review; never control a browser."""
    actions = ActionLog() if actions is None else actions
    reviews = ReviewQueue() if reviews is None else reviews
    outcome = route(observation, policy, dimensions(example.fields, recipe_dir))
    evidence = {name: answer.to_dict() for name, answer in observation.judgments.items()}
    if observation.location is not None:
        evidence["target_box"] = observation.location.to_dict()
    if outcome.status == "located":
        kind = "simulate_focus" if example.fields["kind"] == "input" else "simulate_click"
        actions.record(
            kind,
            {"example": example.id, "target": example.fields["target"], "point": outcome.point},
            answer=evidence,
            rule="presence + unique + enabled + box confidence + bounds",
        )
    elif outcome.status == "review":
        reviews.submit({"example": example.id}, outcome.reason, answer=evidence)
    return outcome, actions, reviews


def actionable(label):
    return label["present"] and label["unique"] and label["enabled"]


def success(outcome, label):
    if not label["present"]:
        return outcome.status == "absent"
    if not actionable(label):
        return outcome.status == "review"
    return outcome.box is not None and box_iou(outcome.box, label["boxes"][0]) >= IOU_TARGET


def summarize(examples, outcomes, labels):
    """Whole-split outcomes, including absent targets and zero-IoU misses."""
    pairs = [(outcomes[e.id], labels[e.id]) for e in examples]
    positives = [(out, gold) for out, gold in pairs if actionable(gold)]
    accepted = [out.status != "review" for out, _ in pairs]
    correct = [success(out, gold) for out, gold in pairs]
    selective = evaluate_outcomes(accepted, correct)
    # Only unambiguous, enabled positives have one gold localization target.
    spatial = (
        localization_metrics(
            [gold["boxes"][0] for _, gold in positives],
            [out.box for out, _ in positives],
        )
        if positives
        else None
    )
    n = len(pairs)
    positive_success = sum(success(out, gold) for out, gold in positives)
    return {
        "N": n,
        "answered": sum(accepted),
        "simulated_actions": sum(out.box is not None for out, _ in pairs),
        "actionable_present": len(positives),
        "gold_absent": sum(not gold["present"] for _, gold in pairs),
        "task_success": sum(correct) / n,
        "localization_success": positive_success / len(positives) if positives else 0.0,
        "mean_iou_present_misses_zero": spatial.mean_iou if spatial else math.nan,
        "missed_actionable": sum(out.box is None for out, _ in positives),
        "false_localizations_absent": sum(
            out.box is not None and not gold["present"] for out, gold in pairs
        ),
        "unsafe_actions": sum(
            out.box is not None and not success(out, gold) for out, gold in pairs
        ),
        "abstention": sum(out.status == "review" for out, _ in pairs) / n,
        "coverage": selective.coverage,
        "answered_accuracy": selective.accuracy,
        "answered_risk": selective.risk,
    }


def select_policy(examples, observations, labels, recipe_dir, *, objective):
    """Choose only from validation; prioritize correct tasks, then unsafe simulations."""
    if objective != OBJECTIVE:
        raise ValueError("unsupported objective")
    if not examples or any(e.split != "validation" for e in examples):
        raise ValueError("policy selection requires only validation examples")
    rows = []
    for presence in PRESENCE_CANDIDATES:
        for box in BOX_CANDIDATES:
            policy = Policy(presence, box)
            outcomes = {
                e.id: route(observations[e.id], policy, dimensions(e.fields, recipe_dir))
                for e in examples
            }
            metrics = summarize(examples, outcomes, labels)
            rows.append({"presence": presence, "box": box, **metrics})
    chosen = max(
        rows,
        key=lambda r: (r["task_success"], -r["unsafe_actions"], r["presence"], r["box"]),
    )
    return Policy(chosen["presence"], chosen["box"]), rows


def baseline(fields, size):
    """A frozen known-layout locator has no image interpretation or abstention."""
    width, height = size
    left, top, right, bottom = BASELINE_PIXELS[fields["kind"]]
    box = normalized_box(
        {
            "left": left / width,
            "top": top / height,
            "right": right / width,
            "bottom": bottom / height,
        }
    )
    return Outcome("located", "fixed known-layout coordinates", box)


def show_location(fields, recipe_dir, outcome):
    """Annotated screenshot and actual crop, displayed with the cookbook's figure style."""
    from matplotlib.figure import Figure

    with Image.open(Path(recipe_dir) / fields["image"]) as source:
        image = source.convert("RGB")
    fig = Figure(figsize=(10, 4), layout="constrained")
    full, close = fig.subplots(1, 2, gridspec_kw={"width_ratios": [2, 1]})
    overlay = draw_boxes(image, {"predicted target": outcome.box}) if outcome.box else image
    full.imshow(overlay)
    full.set_title(fields["target"])
    full.axis("off")
    if outcome.box:
        close.imshow(crop_box(image, outcome.box, expand=0.10))
        close.set_title("Crop of proposed region")
    else:
        close.text(0.5, 0.5, outcome.reason, ha="center", va="center", wrap=True)
        close.set_title("No action")
    close.axis("off")
    return fig
