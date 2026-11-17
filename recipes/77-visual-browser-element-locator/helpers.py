"""Visual judgments propose a region; Python decides whether to simulate an action."""

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from jev_cookbook import Box, Noul
from jev_cookbook.evaluation import (
    evaluate_outcomes,
    noul_confidence,
    select_confidence_threshold,
)
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import (
    box_iou,
    crop_box,
    draw_boxes,
    gold_box,
    image_asset,
    image_reference,
    image_request_profile,
    localization_report,
    normalized_box,
    normalized_to_pixels,
    preflight_image_request,
)

COLLECTION_THRESHOLD = 0.5
IOU_TARGET = 0.50
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
        if not 0.5 <= self.presence <= 1 or not 0 <= self.box <= 1:
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
                "Return the visible part of its outer rectangle, excluding its surrounding card "
                "and excluding any separate text label above an input."
            )
        )
    }


def first_gate(judgments, threshold, *, ungated=None):
    """Use the same validation-selected probability bound for the independent propositions."""
    p = judgments["present"].noul
    gate = noul_confidence([threshold])[0]
    if ungated != "present" and noul_confidence([p])[0] < gate:
        return Outcome(REVIEW, "confidence below the threshold")
    if p <= 0.5:
        return Outcome("absent", "target judged absent")
    for name, reason in (
        ("unique", "target is ambiguous"),
        ("enabled", "target is disabled"),
    ):
        probability = judgments[name].noul
        if ungated != name and noul_confidence([probability])[0] < gate:
            return Outcome(REVIEW, "confidence below the threshold")
        if probability <= 0.5:
            return Outcome(REVIEW, reason)
    return None


def image_decide(backend, state, questions, assets):
    """Check the aggregate image size before either request stage."""
    preflight_image_request(image_request_profile(state, questions, assets))
    return backend.decide(state, questions, assets=assets)


def observe(backend, fields, recipe_dir, presence_threshold):
    """Request Box only after the first gate has passed."""
    state, assets = request_data(fields, recipe_dir)
    judgments = dict(image_decide(backend, state, build_questions(), assets).answers)
    if first_gate(judgments, presence_threshold) is not None:
        return Observation(judgments, None)
    location = image_decide(backend, state, box_questions(), assets)["target_box"]
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
    return gold_box(label["target"]) is not None and label["unique"] and label["enabled"]


def success(outcome, label):
    target = gold_box(label["target"])
    if target is None:
        return outcome.status == "absent"
    if not actionable(label):
        return outcome.status == "review"
    return outcome.box is not None and box_iou(outcome.box, target) >= IOU_TARGET


def summarize(examples, outcomes, labels):
    """Score every example, including disabled, duplicated and absent targets."""
    pairs = [(outcomes[e.id], labels[e.id]) for e in examples]
    accepted = [out.status != "review" for out, _ in pairs]
    correct = [success(out, gold) for out, gold in pairs]
    selective = evaluate_outcomes(accepted, correct)
    spatial = localization_report(
        [gold["target"] for _, gold in pairs],
        [(out.status, out.box) for out, _ in pairs],
        iou_threshold=IOU_TARGET,
    )
    return spatial, {
        "N": len(pairs),
        "answered": sum(accepted),
        "reviewed": len(pairs) - sum(accepted),
        "simulated_actions": sum(out.box is not None for out, _ in pairs),
        "task_success": sum(correct) / len(pairs),
        "unsafe_actions": sum(
            out.box is not None and not success(out, gold) for out, gold in pairs
        ),
        "abstention": 1 - selective.coverage,
        "coverage": selective.coverage,
        "answered_accuracy": selective.accuracy,
        "answered_risk": selective.risk,
    }


def select_presence_gate(examples, observations, labels):
    """Choose the highest answered presence accuracy at the required validation coverage."""
    if not examples or any(e.split != "validation" for e in examples):
        raise ValueError("policy selection requires only validation examples")
    probabilities = [observations[e.id].judgments["present"].noul for e in examples]
    correct = [
        (p > 0.5) == (gold_box(labels[e.id]["target"]) is not None)
        for e, p in zip(examples, probabilities, strict=True)
    ]
    return select_confidence_threshold(correct, noul_confidence(probabilities), min_coverage=0.7)


def select_policy(examples, observations, labels):
    """Freeze presence before selecting the Box gate from eligible validation proposals."""
    presence = (1 + select_presence_gate(examples, observations, labels)) / 2
    confidences, correct = [], []
    for example in examples:
        seen = observations[example.id]
        if first_gate(seen.judgments, presence) is not None:
            continue
        box = seen.location
        if box is None or box.confidence is None:
            continue
        gold = labels[example.id]
        confidences.append(box.confidence)
        correct.append(
            actionable(gold) and box_iou(box.box, gold_box(gold["target"])) >= IOU_TARGET
        )
    if not confidences:
        raise ValueError("no eligible validation boxes with confidence; cannot freeze a Box gate")
    threshold = select_confidence_threshold(correct, confidences, min_coverage=0.5)
    return Policy(presence, threshold)


def measure_noul_gates(policy):
    """Compare first-stage outcomes over a grid with one Noul confidence gate removed."""
    from types import SimpleNamespace

    def disposition(outcome):
        return outcome.status if outcome else "request_box"

    counts = {}
    for name in build_questions():
        changed = [0, 0]
        for step in range(101):
            probability = step / 100
            judgments = {
                question: SimpleNamespace(noul=probability if question == name else 1.0)
                for question in build_questions()
            }
            with_gate = first_gate(judgments, policy.presence)
            without = first_gate(judgments, policy.presence, ungated=name)
            changed[probability > 0.5] += disposition(with_gate) != disposition(without)
        counts[name] = tuple(changed)
    return counts


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
