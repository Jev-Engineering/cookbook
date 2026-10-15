"""Bounded visual search; semantic answers never perform geometry or actions."""

import base64
import io
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from jev_cookbook import Box, Choice, ReplayBackend, record, replay_key
from jev_cookbook.evaluation import evaluate_outcomes
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import (
    box_iou,
    generate_tiles,
    image_reference,
    normalized_box,
    normalized_to_pixels,
    tile_to_image,
)

TARGET = (
    "the small pink square marker with a white plus sign in its center; "
    "exclude blue squares, pink circles, and pink squares with a dark diagonal"
)
POLICIES = {"compact": 64, "wide": 128}
GATES = (0.4, 0.7, 0.9)
OBJECTIVE = "hits - 2 * wrong_accepted; ties: fewer_calls, higher_gate, compact"
MAX_DEPTH = 2
MAX_CALLS = 3
REVIEW = "review"
CONFIDENCE_REASON = "confidence below the threshold"


@dataclass(frozen=True)
class View:
    image: object
    bounds: tuple


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str
    box: dict | None
    calls: int
    trace: tuple


def load_view(fields, recipe_dir=None):
    """Only authored pixels enter the request; file names and labels stay local."""
    root = Path.cwd() if recipe_dir is None else Path(recipe_dir)
    with Image.open(root / fields["image"]) as source:
        image = source.convert("RGB")
    return View(image, (0, 0, *image.size))


def asset_for(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    asset = {
        "type": "image",
        "format": "png",
        "data_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }
    return image_reference(asset), asset


def split_view(view, policy):
    """Four corner-anchored overlapping tiles, with absolute original-image offsets."""
    if policy not in POLICIES:
        raise ValueError("unknown tile policy")
    width, height = view.image.size
    margin = POLICIES[policy]
    size = ((width + 1) // 2 + margin, (height + 1) // 2 + margin)
    if size[0] >= width or size[1] >= height:
        raise ValueError("tiles would not progressively shrink")
    if min(size) < 256 or size[0] * size[1] < 78_400:
        raise ValueError("tile violates the image dimension/area limits")
    tiles = generate_tiles(view.image, tile_size=size, overlap=2 * margin)
    if len(tiles) != 4:
        raise ValueError("policy requires exactly four tiles")
    x, y, _, _ = view.bounds
    return [
        View(tile.image, (x + left, y + top, x + right, y + bottom))
        for tile in tiles
        for left, top, right, bottom in [tile.bounds]
    ]


def tile_request(views):
    assets, criteria = {}, {}
    for index, view in enumerate(views):
        reference, asset = asset_for(view.image)
        assets[reference] = asset
        criteria[f"tile_{index}"] = {"image": reference}
    criteria["none"] = "No tile contains the requested marker."
    criteria["uncertain"] = "Identity is unclear, or multiple distinct markers match."
    question = Choice(
        instructions=(
            "Select the tile containing the complete requested marker. Overlapping tiles can "
            "show the same marker: choose the first tile containing it completely. If no tile "
            "contains it completely but one contains part, choose that tile. If distinct "
            "matching markers exist, choose uncertain. Inspect pixels only."
        ),
        criteria=criteria,
    )
    return {"target": TARGET}, {"tile": question}, assets


def presence_request(view):
    reference, asset = asset_for(view.image)
    return (
        {"image": reference, "target": TARGET},
        {
            "presence": Choice(
                instructions="Does this image contain exactly one complete requested marker?",
                criteria={
                    "present": "Exactly one complete requested marker is visible.",
                    "none": "No requested marker is visible.",
                    "uncertain": "Partial, unclear, or multiple distinct matching markers.",
                },
            )
        },
        {reference: asset},
    )


def box_request(view):
    reference, asset = asset_for(view.image)
    return (
        {"image": reference, "target": TARGET},
        {
            "location": Box(
                instructions=(
                    "Return one tight rectangle around the entire pink square marker with "
                    "the white plus sign. Coordinates refer only to this supplied image."
                )
            )
        },
        {reference: asset},
    )


class RequestCache:
    """Keep validation sweeps and demonstrations from repeating live requests."""

    def __init__(self, backend):
        self.backend = backend
        self.results = {}
        self.requests = {}

    def decide(self, state, questions, *, assets):
        key = replay_key(state, questions, assets=assets)
        if key not in self.results:
            result = self.backend.decide(state, questions, assets=assets)
            self.results[key] = result
            self.requests[key] = (state, questions, assets)
        return self.results[key]


class CaptureBackend:
    """Opt-in adaptive capture: each dependent request is recorded before its answer is used."""

    def __init__(self, live_backend, output_path, *, ledger_path):
        if live_backend.mode != "live":
            raise ValueError("capture requires an explicitly selected live backend")
        self.live_backend = live_backend
        self.output_path = output_path
        self.ledger_path = ledger_path

    def decide(self, state, questions, *, assets):
        record(
            self.live_backend,
            [(state, questions, assets)],
            self.output_path,
            ledger_path=self.ledger_path,
        )
        return ReplayBackend.from_json(self.output_path).decide(state, questions, assets=assets)


def _validate_limits(gate, max_depth, max_calls):
    if isinstance(gate, bool) or not math.isfinite(gate) or not 0 <= gate <= 1:
        raise ValueError("gate must be finite in [0,1]")
    if type(max_depth) is not int or not 0 <= max_depth <= MAX_DEPTH:
        raise ValueError("max_depth must be an integer from zero to two")
    if type(max_calls) is not int or max_calls < 0:
        raise ValueError("max_calls must be a nonnegative integer")


def search(backend, root, *, policy="wide", gate=0.7, max_depth=2, max_calls=3):
    """At most two dependent Choice calls, then one Box; no absence inferred from Box."""
    _validate_limits(gate, max_depth, max_calls)
    if policy not in POLICIES:
        raise ValueError("unknown tile policy")
    current, trace = root, []

    def finish(status, reason, box=None):
        return Outcome(status, reason, box, len(trace), tuple(trace))

    for depth in range(max_depth):
        if len(trace) >= max_calls:
            return finish("review", "request_budget")
        try:
            views = split_view(current, policy)
        except ValueError:
            return finish("review", "tile_size")
        state, questions, assets = tile_request(views)
        answer = backend.decide(state, questions, assets=assets)["tile"]
        trace.append({"stage": "tile", "depth": depth, "answer": answer, "views": views})
        if answer.choice == "uncertain":
            return finish("review", "uncertain_identity")
        if answer.confidence < gate:
            return finish(REVIEW, CONFIDENCE_REASON)
        if answer.choice == "none":
            if depth == 0:
                return finish("absent", "no_target_in_whole_image")
            return finish("review", "selected_branch_has_no_target")
        allowed = {f"tile_{index}": view for index, view in enumerate(views)}
        if answer.choice not in allowed:
            return finish("review", "unknown_tile")
        current = allowed[answer.choice]
    if max_depth < MAX_DEPTH:
        return finish("review", "depth_limit")
    if len(trace) >= max_calls:
        return finish("review", "request_budget")
    state, questions, assets = box_request(current)
    answer = backend.decide(state, questions, assets=assets)["location"]
    trace.append({"stage": "box", "answer": answer, "view": current})
    if answer.confidence is None:
        return finish(REVIEW, "box confidence unavailable")
    if answer.confidence < gate:
        return finish(REVIEW, CONFIDENCE_REASON)
    try:
        box = normalized_box(answer)
        mapped = tile_to_image(box, current.bounds, *root.image.size)
        left, top, right, bottom = normalized_to_pixels(mapped, *root.image.size)
    except (ValueError, TypeError):
        return finish("review", "invalid_box")
    # A normalized but essentially full-tile rectangle is not a small-marker localization.
    if right - left > 96 or bottom - top > 96:
        return finish("review", "marker_size")
    return finish("localized", "simulated_rectangle_only", mapped)


def direct(backend, root, *, gate=0.7, max_calls=2):
    """Full-image baseline: a presence Choice guards a separate full-image Box."""
    _validate_limits(gate, MAX_DEPTH, max_calls)
    trace = []

    def finish(status, reason, box=None):
        return Outcome(status, reason, box, len(trace), tuple(trace))

    if max_calls == 0:
        return finish("review", "request_budget")
    state, questions, assets = presence_request(root)
    answer = backend.decide(state, questions, assets=assets)["presence"]
    trace.append({"stage": "presence", "answer": answer, "view": root})
    if answer.choice == "uncertain":
        return finish("review", "uncertain_identity")
    if answer.confidence < gate:
        return finish(REVIEW, CONFIDENCE_REASON)
    if answer.choice == "none":
        return finish("absent", "no_target_in_whole_image")
    if answer.choice != "present":
        return finish("review", "unknown_presence")
    if len(trace) >= max_calls:
        return finish("review", "request_budget")
    state, questions, assets = box_request(root)
    answer = backend.decide(state, questions, assets=assets)["location"]
    trace.append({"stage": "box", "answer": answer, "view": root})
    if answer.confidence is None:
        return finish(REVIEW, "box confidence unavailable")
    if answer.confidence < gate:
        return finish(REVIEW, CONFIDENCE_REASON)
    try:
        box = normalized_box(answer)
        left, top, right, bottom = normalized_to_pixels(box, *root.image.size)
    except (ValueError, TypeError):
        return finish("review", "invalid_box")
    if right - left > 96 or bottom - top > 96:
        return finish("review", "marker_size")
    return finish("localized", "simulated_rectangle_only", box)


def record_outcome(ident, outcome, actions=None, reviews=None):
    actions = ActionLog() if actions is None else actions
    reviews = ReviewQueue() if reviews is None else reviews
    if outcome.status == "localized":
        actions.record(
            "draw_rectangle",
            {"id": ident, "box": outcome.box},
            rule="accepted choices and box; geometry and request limits passed",
        )
    elif outcome.status == "review":
        reviews.submit({"id": ident}, outcome.reason)
    return actions, reviews


def hit(outcome, label):
    if label["status"] == "review":
        return outcome.status == "review"
    if label["status"] == "absent":
        return outcome.status == "absent"
    return outcome.status == "localized" and box_iou(outcome.box, label["box"]) >= 0.5


def summarize(outcomes, labels):
    correct = [hit(outcome, label) for outcome, label in zip(outcomes, labels, strict=True)]
    accepted = [outcome.status != "review" for outcome in outcomes]
    selective = evaluate_outcomes(accepted, correct)
    present = [
        (outcome, label)
        for outcome, label in zip(outcomes, labels, strict=True)
        if label["status"] == "present"
    ]
    ious = [
        box_iou(outcome.box, label["box"]) if outcome.box is not None else 0.0
        for outcome, label in present
    ]
    return {
        "n": len(outcomes),
        "hits": sum(correct),
        "end_to_end_hit": sum(correct) / len(outcomes),
        "mean_iou_all_present": sum(ious) / len(ious) if ious else None,
        "coverage": selective.coverage,
        "risk": selective.risk,
        "review": sum(not value for value in accepted),
        "absent": sum(outcome.status == "absent" for outcome in outcomes),
        "wrong_accepted": sum(a and not c for a, c in zip(accepted, correct, strict=True)),
        "calls": sum(outcome.calls for outcome in outcomes),
    }


def select_policy(backend, examples, labels, recipe_dir=None, *, objective):
    if objective != OBJECTIVE:
        raise ValueError("unknown selection objective")
    if any(example.split != "validation" for example in examples):
        raise ValueError("policy selection accepts only validation examples")
    rows = []
    for policy in POLICIES:
        for gate in GATES:
            outcomes = [
                search(backend, load_view(example.fields, recipe_dir), policy=policy, gate=gate)
                for example in examples
            ]
            metrics = summarize(outcomes, [labels[example.id] for example in examples])
            rows.append({"policy": policy, "gate": gate, **metrics})
    selected = max(
        rows,
        key=lambda row: (
            row["hits"] - 2 * row["wrong_accepted"],
            -row["calls"],
            row["gate"],
            row["policy"] == "compact",
        ),
    )
    return (selected["policy"], selected["gate"]), rows


def select_direct_gate(backend, examples, labels, recipe_dir=None):
    if any(example.split != "validation" for example in examples):
        raise ValueError("gate selection accepts only validation examples")
    rows = []
    for gate in GATES:
        outcomes = [
            direct(backend, load_view(example.fields, recipe_dir), gate=gate)
            for example in examples
        ]
        metrics = summarize(outcomes, [labels[example.id] for example in examples])
        rows.append({"gate": gate, **metrics})
    selected = max(
        rows,
        key=lambda row: (row["hits"] - 2 * row["wrong_accepted"], -row["calls"], row["gate"]),
    )
    return selected["gate"], rows
