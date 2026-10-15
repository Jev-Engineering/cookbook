"""Bounded HUD perception, exact geometry, and simulated intents for recipe 80."""

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from jev_cookbook import Box, Choice, replay_key
from jev_cookbook.evaluation import accuracy, evaluate_outcomes
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import (
    box_confidence,
    box_iou,
    image_asset,
    image_reference,
    normalized_box,
    normalized_to_pixels,
)

WIDTH, HEIGHT = 640, 400
REVIEW = "review"
TARGETS = {
    "energy_meter": "the ENERGY panel showing the player's energy, not the decoration",
    "card": "the hand card titled SPARK, excluding the similarly colored DECOY card",
    "action_button": "the END TURN button, excluding the HISTORY tab",
    "enemy_indicator": "the ENEMY intent panel above the enemy, excluding the STATUS panel",
}
EVENTS = {
    "energy_meter": "observe_energy",
    "card": "select_card",
    "action_button": "end_turn",
    "enemy_indicator": "inspect_enemy",
}
PHASES = {
    "combat": "A combat board is active, without a menu or reward overlay.",
    "menu": "The pause or main menu is open, even if a combat board is visible behind it.",
    "reward": "A victory/reward screen is open, even if combat controls remain visible.",
    "ambiguous": "The visible screen does not establish one of these phases clearly.",
}
PRESENCE = {
    "visible": "The requested target is identifiable with all four outer edges visible.",
    "absent": "The requested target is absent from this screenshot.",
    "uncertain": "Occlusion, overlapping look-alikes, or unclear content prevents localization.",
}
ENABLED = {
    "enabled": "The requested card or action button is visibly enabled.",
    "disabled": "The requested card or action button is visibly disabled.",
    "not_applicable": "The target is a read-only meter/indicator, or no such control is visible.",
    "uncertain": "Whether the requested control is enabled cannot be determined.",
}
ENERGY = {
    "0": "The ENERGY panel explicitly displays zero.",
    "1": "The ENERGY panel explicitly displays one.",
    "2": "The ENERGY panel explicitly displays two.",
    "3": "The ENERGY panel explicitly displays three.",
    "unreadable": "The displayed value is unreadable or outside the supplied values.",
}

# Fixed-layout baseline anchors. These are design-time constants, never gold lookups.
FIXED_PIXELS = {
    "energy_meter": (26, 275, 116, 355),
    "card": (180, 248, 300, 370),
    "action_button": (470, 310, 610, 366),
    "enemy_indicator": (460, 95, 598, 160),
}
TARGET_COLORS = {
    "energy_meter": (31, 120, 168),
    "card": (232, 163, 61),
    "action_button": (45, 134, 111),
    "enemy_indicator": (143, 107, 168),
}
PHASE_COLORS = {
    "combat": (49, 81, 90),
    "menu": (92, 65, 112),
    "reward": (148, 106, 42),
}
DISABLED_COLOR = (105, 108, 113)


def pixel_box(bounds, width=WIDTH, height=HEIGHT):
    """Exact normalization of exclusive pixel edges; no resizing is implicit."""
    left, top, right, bottom = bounds
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("pixel box must lie inside the image")
    return dict(top=top / height, bottom=bottom / height, left=left / width, right=right / width)


def prepare(fields, recipe_dir=None):
    """Only the image and requested target enter state; labels and filenames do not."""
    if set(fields) != {"image", "target"} or fields["target"] not in TARGETS:
        raise ValueError("fields must contain a local image and a supported target")
    root = Path.cwd() if recipe_dir is None else Path(recipe_dir)
    relative = Path(fields["image"])
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("assets",):
        raise ValueError("image must be inside the recipe's assets folder")
    path = root / relative
    asset = image_asset(path)
    ref = image_reference(asset)
    state = {"screenshot": ref, "requested_target": TARGETS[fields["target"]]}
    with Image.open(path) as image:
        size = image.size
    return state, {ref: asset}, size


def build_questions():
    """Independent screen judgments share the first request."""
    return {
        "phase": Choice(instructions="Identify the currently visible UI phase.", criteria=PHASES),
        "presence": Choice(
            instructions="Determine whether requested_target can be localized.", criteria=PRESENCE
        ),
        "enabled": Choice(
            instructions="Classify the visible enabled state of requested_target.", criteria=ENABLED
        ),
    }


def localization_questions(target):
    questions = {
        "target_box": Box(
            instructions=(
                "Locate requested_target in screenshot. Return its tight outer rectangle, "
                "excluding neighboring controls. Coordinates are relative to the full image."
            )
        )
    }
    if target == "energy_meter":
        questions["energy"] = Choice(
            instructions="Read the explicitly displayed ENERGY value; do not calculate a value.",
            criteria=ENERGY,
        )
    return questions


@dataclass(frozen=True)
class Policy:
    confidence: float
    max_requests: int = 2
    min_box_pixels: int = 12

    def __post_init__(self):
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if type(self.max_requests) is not int or not 0 <= self.max_requests <= 2:
            raise ValueError("max_requests must be an integer from 0 to 2")
        if type(self.min_box_pixels) is not int or self.min_box_pixels < 1:
            raise ValueError("min_box_pixels must be positive")


@dataclass
class Observation:
    ident: str
    target: str
    phase: str = "ambiguous"
    presence: str = "uncertain"
    enabled: str = "uncertain"
    event: str = REVIEW
    reason: str = ""
    box: dict | None = None
    raw_box: dict | None = None
    energy: int | None = None
    requests: int = 0
    keys: list = field(default_factory=list)
    results: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    reviews: list = field(default_factory=list)


def gate_first(result, target, policy):
    """Return (outcome, reason); every final no-action answer is confidence gated too."""
    phase, presence, enabled = (result[name] for name in ("phase", "presence", "enabled"))
    if phase.choice == "ambiguous" or presence.choice == "uncertain":
        return "review", "ambiguous phase or target"
    if any(answer.confidence < policy.confidence for answer in (phase, presence, enabled)):
        return "review", "confidence below the threshold"
    if phase.choice != "combat":
        return "no_action", "phase is not combat"
    if presence.choice == "absent":
        return "no_action", "target absent"
    if enabled.choice == "uncertain":
        return "review", "enabled state uncertain"
    if target in ("card", "action_button"):
        if enabled.choice == "disabled":
            return "no_action", "control disabled"
        if enabled.choice != "enabled":
            return "review", "control enabled state inconsistent"
    elif enabled.choice != "not_applicable":
        return "review", "read-only target enabled state inconsistent"
    return "localize", "phase, presence and enabled gates passed"


def gate_box(answer, size, policy):
    """Never clip invalid coordinates or replace a missing confidence with certainty."""
    try:
        box = normalized_box(answer)
        pixels = normalized_to_pixels(box, *size)
        confidence = box_confidence(answer)
    except (TypeError, ValueError, OverflowError):
        return None, "invalid bounding box"
    if confidence is None:
        return None, "box confidence missing"
    if confidence < policy.confidence:
        return None, "confidence below the threshold"
    left, top, right, bottom = pixels
    if right - left < policy.min_box_pixels or bottom - top < policy.min_box_pixels:
        return None, "box too small for this policy"
    return box, "box gates passed"


def perceive(example, backend, policy, recipe_dir=None):
    """At most two requests; the only effect is an in-memory simulated ActionLog."""
    state, assets, size = prepare(example.fields, recipe_dir)
    target = example.fields["target"]
    obs = Observation(example.id, target)
    log, review = ActionLog(), ReviewQueue()

    def finish(event, reason, answer=None):
        obs.event, obs.reason = event, reason
        if event == "review":
            review.submit({"id": example.id, "target": target}, reason, answer=answer)
        obs.actions, obs.reviews = log.to_dicts(), review.to_dicts()
        return obs

    def request(questions):
        if obs.requests >= policy.max_requests:
            return None
        obs.requests += (
            1  # decision calls count even if the backend raises; retries are backend-owned
        )
        obs.keys.append(replay_key(state, questions, assets=assets))
        result = backend.decide(state, questions, assets=assets)
        obs.results.append(result)
        return result

    first = request(build_questions())
    if first is None:
        return finish("review", "request budget exhausted")
    obs.phase, obs.presence, obs.enabled = (
        first[name].choice for name in ("phase", "presence", "enabled")
    )
    event, reason = gate_first(first, target, policy)
    if event != "localize":
        return finish(event, reason, first)
    second = request(localization_questions(target))
    if second is None:
        return finish("review", "request budget exhausted", first)
    try:
        obs.raw_box = normalized_box(second["target_box"])
    except (TypeError, ValueError):
        pass
    box, reason = gate_box(second["target_box"], size, policy)
    if box is None:
        return finish("review", reason, second)
    if target == "energy_meter":
        answer = second["energy"]
        if answer.choice not in {"0", "1", "2", "3"}:
            return finish("review", "energy unreadable", second)
        if answer.confidence < policy.confidence:
            return finish("review", "confidence below the threshold", second)
        obs.energy = int(answer.choice)
    obs.box = box
    left, top, right, bottom = normalized_to_pixels(box, *size)
    log.record(
        EVENTS[target],
        {
            "id": example.id,
            "target": target,
            "box": box,
            "center_pixel": [(left + right - 1) // 2, (top + bottom - 1) // 2],
            "energy": obs.energy,
        },
        answer=second,
        rule="combat + visible + enabled as applicable + confidence + valid box + budget",
    )
    return finish(EVENTS[target], "simulated intent only")


class RequestCache:
    """Memoize validation requests; threshold comparisons never resend an identical request."""

    def __init__(self, backend):
        self.backend = backend
        self.results = {}

    def decide(self, state, questions, *, assets):
        key = replay_key(state, questions, assets=assets)
        if key not in self.results:
            self.results[key] = self.backend.decide(state, questions, assets=assets)
        return self.results[key]


def event_correct(obs, gold):
    """A matching action name alone is insufficient: localization and energy must agree too."""
    if obs.event != gold["event"]:
        return False
    if obs.event in ("review", "no_action"):
        return True
    return (
        obs.box is not None
        and gold["box"] is not None
        and box_iou(obs.box, gold["box"]) >= 0.5
        and (obs.target != "energy_meter" or obs.energy == gold["energy"])
    )


def summarize(observations, labels):
    gold = [labels[obs.ident] for obs in observations]
    correct = [event_correct(obs, label) for obs, label in zip(observations, gold, strict=True)]
    resolved = evaluate_outcomes([obs.event != "review" for obs in observations], correct)
    pairs = [
        box_iou(obs.raw_box, label["box"])
        for obs, label in zip(observations, gold, strict=True)
        if obs.raw_box is not None and label["box"] is not None
    ]
    required = [
        0.0 if obs.box is None else box_iou(obs.box, label["box"])
        for obs, label in zip(observations, gold, strict=True)
        if label["event"] in EVENTS.values()
    ]
    return {
        "N": len(observations),
        "phase_accuracy": accuracy([g["phase"] for g in gold], [o.phase for o in observations]),
        "presence_accuracy": accuracy(
            [g["presence"] for g in gold], [o.presence for o in observations]
        ),
        "event_accuracy": sum(correct) / len(correct),
        "abstention": 1 - resolved.coverage,
        "resolved_accuracy": resolved.accuracy,
        "raw_box_pairs": len(pairs),
        "raw_box_mean_iou": sum(pairs) / len(pairs) if pairs else None,
        "required_targets": len(required),
        "required_target_mean_iou": sum(required) / len(required) if required else None,
        "false_localizations_on_absent": sum(
            o.box is not None and g["presence"] == "absent"
            for o, g in zip(observations, gold, strict=True)
        ),
        "requests": sum(o.requests for o in observations),
        "simulated_intents": sum(len(o.actions) for o in observations),
        "wrong_simulated_intents": sum(
            bool(o.actions) and not ok for o, ok in zip(observations, correct, strict=True)
        ),
    }


def select_policy(examples, labels, backend, recipe_dir=None, *, min_coverage=0.5):
    """Validation objective: lowest resolved error, then greatest coverage, then lowest gate."""
    if not examples or any(example.split != "validation" for example in examples):
        raise ValueError("policy selection accepts only the validation split")
    if not 0 < min_coverage <= 1:
        raise ValueError("min_coverage must be in (0, 1]")
    cache = RequestCache(backend)
    rows = []
    for threshold in (0.55, 0.75, 0.90):
        policy = Policy(threshold)
        observations = [perceive(e, cache, policy, recipe_dir) for e in examples]
        metrics = summarize(observations, labels)
        rows.append({"threshold": threshold, **metrics})
    feasible = [row for row in rows if 1 - row["abstention"] >= min_coverage]
    if not feasible:
        raise ValueError("no validation policy meets minimum coverage")
    chosen = min(
        feasible,
        key=lambda row: (
            1 - row["resolved_accuracy"],
            row["abstention"],
            row["threshold"],
        ),
    )
    return Policy(chosen["threshold"]), rows, list(cache.results.values())


def fixed_layout(example, recipe_dir=None):
    """Image-only baseline: fixed crops and visible-color occupancy, with no label access."""
    root = Path.cwd() if recipe_dir is None else Path(recipe_dir)
    with Image.open(root / example.fields["image"]) as source:
        image = np.asarray(source.convert("RGB"))
    height, width = image.shape[:2]
    if (width, height) != (WIDTH, HEIGHT):
        raise ValueError("the frozen fixed-layout baseline requires 640 x 400 pixels")
    target = example.fields["target"]
    obs = Observation(example.id, target)

    def fraction(bounds, color):
        left, top, right, bottom = bounds
        crop = image[top:bottom, left:right]
        return float(np.all(crop == color, axis=-1).mean())

    phase_scores = {
        phase: fraction((20, 20, 620, 65), color) for phase, color in PHASE_COLORS.items()
    }
    phase = max(phase_scores, key=phase_scores.get)
    obs.phase = phase if phase_scores[phase] >= 0.70 else "ambiguous"
    bounds = FIXED_PIXELS[target]
    colored = fraction(bounds, TARGET_COLORS[target])
    disabled = fraction(bounds, DISABLED_COLOR)
    obs.presence = "visible" if max(colored, disabled) >= 0.30 else "absent"
    obs.enabled = (
        "not_applicable"
        if target in ("energy_meter", "enemy_indicator")
        else "disabled"
        if disabled > colored
        else "enabled"
    )
    if obs.phase == "ambiguous":
        obs.reason = "fixed header did not establish a phase"
        obs.reviews = [{"reason": obs.reason}]
        return obs
    if obs.phase != "combat" or obs.presence == "absent" or obs.enabled == "disabled":
        obs.event, obs.reason = "no_action", "fixed-layout phase or presence or enabled gate"
        return obs
    obs.box = obs.raw_box = pixel_box(bounds)
    if target == "energy_meter":
        # Three known slots encode the displayed 0..3 value in this authored mock HUD.
        obs.energy = sum(
            bool(np.array_equal(image[333, 41 + i * 22], (254, 254, 254))) for i in range(3)
        )
    obs.event, obs.reason = EVENTS[target], "fixed-layout simulated intent"
    log = ActionLog()
    log.record(obs.event, {"id": obs.ident, "box": obs.box, "energy": obs.energy})
    obs.actions = log.to_dicts()
    return obs


def printable(metrics):
    """Stable scalar text, preserving missing measurements as None."""
    return {
        key: round(value, 4) if isinstance(value, float) and math.isfinite(value) else value
        for key, value in metrics.items()
    }
