"""Bounded frame judgments and local checks; no camera or delivery service is controlled."""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from jev_cookbook import Choice, replay_key
from jev_cookbook.simulation import ActionLog, BudgetExceeded, ReviewQueue
from jev_cookbook.vision import load_frames

OPTIONS = ("arrival", "departure", "unchanged", "uncertain")
REVIEW = "review"
TARGET = "Tan cardboard parcel with a blue vertical tape stripe on the dark delivery mat."
MAX_GAP = 2.0
MAX_SPAN = 4.0


def build_questions():
    """One event judgment over the entire ordered sequence, not independent endpoints."""
    return {
        "event": Choice(
            instructions=(
                "Classify the visible history of the specified target across ALL timestamped "
                "stills. Arrival and departure name visibility changes in these sampled images, "
                "not proof of a physical delivery, removal, or theft. Ignore other objects. "
                "If the target is hidden, identity is ambiguous, or changes reverse in the "
                "middle, choose uncertain. Never infer absence behind an occluder."
            ),
            criteria={
                "arrival": "Clearly absent, then visible, with no later reversal.",
                "departure": "Clearly visible, then absent, with no later reversal.",
                "unchanged": "Clearly present throughout or clearly absent throughout.",
                "uncertain": "Occlusion, ambiguity, poor evidence, or more than one transition.",
            },
        )
    }


@dataclass(frozen=True)
class Prepared:
    state: dict
    assets: dict
    issues: tuple
    images: tuple


def prepare(fields, root):
    """Validate times; measure quality from pixels, never drawing metadata or gold labels."""
    rows = fields["frames"]
    if not 3 <= len(rows) <= 4:
        raise ValueError("supply three or four ordered stills")
    frames, assets = load_frames([(r["timestamp_seconds"], Path(root) / r["path"]) for r in rows])
    images = []
    for row in rows:
        with Image.open(Path(root) / row["path"]) as image:
            images.append(np.asarray(image.convert("RGB"), dtype=np.float64))
    issues = []
    times = [f["timestamp_seconds"] for f in frames]
    if max(b - a for a, b in zip(times, times[1:], strict=False)) > MAX_GAP:
        issues.append("sampling gap exceeds two seconds")
    if times[-1] - times[0] > MAX_SPAN:
        issues.append("sample span exceeds four seconds")
    if len({im.shape for im in images}) != 1:
        issues.append("frame dimensions changed")
    else:
        # A fixed, empty wall strip is the local camera-alignment reference.
        anchors = [im[:100].mean(axis=2) for im in images]
        if any(float(np.abs(a - anchors[0]).mean()) > 6.0 for a in anchors[1:]):
            issues.append("camera or background changed")
    if any(float(im.mean()) < 35.0 or float(im.std()) < 8.0 for im in images):
        issues.append("lighting or contrast inadequate")
    return Prepared({"target": TARGET, "frames": frames}, assets, tuple(issues), tuple(images))


@dataclass(frozen=True)
class Observation:
    prepared: Prepared
    result: object = None

    @property
    def answer(self):
        return None if self.result is None else self.result["event"]


class ClipRunner:
    """One request per eligible clip, cached; bad quality and exhausted budgets stop sends."""

    def __init__(self, backend, max_requests=20):
        if type(max_requests) is not int or max_requests < 0:
            raise ValueError("max_requests must be a nonnegative integer")
        self.backend = backend
        self.max_requests = max_requests
        self.requests = 0
        self.cache = {}

    def observe(self, fields, root):
        prepared = prepare(fields, root)
        if prepared.issues:
            return Observation(prepared)
        questions = build_questions()
        key = replay_key(prepared.state, questions, assets=prepared.assets)
        if key not in self.cache:
            if self.requests >= self.max_requests:
                raise BudgetExceeded("clip request budget exhausted")
            self.requests += 1
            self.cache[key] = self.backend.decide(prepared.state, questions, assets=prepared.assets)
        return Observation(prepared, self.cache[key])


@dataclass(frozen=True)
class Outcome:
    label: str
    accepted: bool
    reason: str


def route(observation, min_confidence):
    """Quality, known label and confidence are all mandatory; uncertainty always defers."""
    if isinstance(min_confidence, bool) or not isinstance(min_confidence, (int, float)):
        raise ValueError("threshold must be between zero and one")
    if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ValueError("threshold must be between zero and one")
    if observation.prepared.issues:
        return Outcome(REVIEW, False, "; ".join(observation.prepared.issues))
    answer = observation.answer
    if answer is None or answer.choice not in OPTIONS or answer.choice == "uncertain":
        return Outcome(REVIEW, False, "event is unresolved")
    confidence = answer.confidence
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
        or confidence < min_confidence
    ):
        return Outcome(REVIEW, False, "confidence below the threshold")
    return Outcome(answer.choice, True, "quality checks and confidence gate passed")


def log_outcome(clip_id, observation, threshold, actions: ActionLog, reviews: ReviewQueue):
    """Simulate an observation note only; no delivery, theft or inventory claim is made."""
    outcome = route(observation, threshold)
    if outcome.accepted:
        actions.record(
            "visible_event_note",
            {"clip": clip_id, "event": outcome.label, "physical_event": "not established"},
            answer=observation.answer,
            rule=outcome.reason,
        )
    else:
        reviews.submit({"clip": clip_id}, outcome.reason, answer=observation.answer)
    return outcome


def pixel_baseline(prepared):
    """Fixed tan-pixel occupancy baseline over every frame; no labels or row IDs are read.

    It treats enough brown pixels in the lower central mat as a parcel. It cannot identify
    blue tape, distinguish a brown crate, or decide whether an object is hidden.
    """
    if prepared.issues:
        return "uncertain"
    occupied = []
    for image in prepared.images:
        height, width = image.shape[:2]
        roi = image[int(height * 0.42) : int(height * 0.91), int(width * 0.18) : int(width * 0.82)]
        red, green, blue = roi.transpose(2, 0, 1)
        tan = (red > 125) & (red > green * 1.15) & (green > blue * 1.25)
        occupied.append(int(tan.sum()) >= 1000)
    changes = [(a, b) for a, b in zip(occupied, occupied[1:], strict=False) if a != b]
    if not changes:
        return "unchanged"
    if len(changes) > 1:
        return "uncertain"
    return "arrival" if changes[0][1] else "departure"


def contact_sheet(fields, root):
    """Display all sampled pixels and their actual timestamps for a reader to inspect."""
    rows = fields["frames"]
    sheet = Image.new("RGB", (480 * len(rows), 390), "#FEFEFE")
    draw = ImageDraw.Draw(sheet)
    for i, row in enumerate(rows):
        with Image.open(Path(root) / row["path"]) as image:
            sheet.paste(image.resize((480, 360)), (480 * i, 30))
        draw.text((480 * i + 12, 8), f"t = {row['timestamp_seconds']:.2f} s", fill="#1E1E1E")
    return sheet
