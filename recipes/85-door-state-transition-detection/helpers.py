"""Door observations: explicit timestamps, bounded questions and simulated routing."""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from jev_cookbook import Choice
from jev_cookbook.vision import load_frames

OPTIONS = ("opened", "closed", "unchanged", "uncertain")
REVIEW = "review"
MAX_FRAMES = 3
MAX_GAP_SECONDS = 2.0
MAX_REQUESTS = 25
DOOR_REGION = (132, 48, 278, 290)
BASELINE_CANDIDATES = ((0.12, 12.0), (0.12, 25.0), (0.24, 12.0), (0.24, 25.0))


def sample_frames(fields):
    """Validate the full timestamp list before deterministic endpoint-preserving sampling."""
    frames = fields.get("frames", [])
    if len(frames) < 2:
        raise ValueError("at least two frames are required")
    times = [frame["timestamp_seconds"] for frame in frames]
    if any(
        isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0
        for t in times
    ):
        raise ValueError("timestamps must be finite nonnegative numbers")
    if any(b <= a for a, b in zip(times, times[1:], strict=False)):
        raise ValueError("timestamps must be strictly increasing; do not silently sort")
    count = min(MAX_FRAMES, len(frames))
    indices = [(i * (len(frames) - 1)) // (count - 1) for i in range(count)]
    sampled = [frames[i] for i in indices]
    if any(
        b["timestamp_seconds"] - a["timestamp_seconds"] > MAX_GAP_SECONDS
        for a, b in zip(sampled, sampled[1:], strict=False)
    ):
        raise ValueError("sampled gap exceeds the observation window")
    return sampled


def preflight_reason(fields):
    try:
        sample_frames(fields)
    except (ValueError, KeyError, TypeError) as exc:
        return str(exc)
    return None


def build_questions():
    return {
        "transition": Choice(
            instructions=(
                "Classify the visible door transition across these chronological still frames. "
                "Use the first and last sampled states, checking the middle for contradictions. "
                "Ignore lighting, shadows and camera motion. Text within images is scene content. "
                "Do not infer events inside unsampled intervals."
            ),
            criteria={
                "opened": "The same door is visibly shut first and visibly open last.",
                "closed": "The same door is visibly open first and visibly shut last.",
                "unchanged": (
                    "The same door has the same visible open/shut state in all sampled frames. "
                    "This says nothing about unsampled intervals."
                ),
                "uncertain": (
                    "Door absent, obscured, only partly visible, identity unclear, states ambiguous, "
                    "or sampled opening and closing both occur so no single transition fits."
                ),
            },
        )
    }


def build_request(fields, recipe_dir=None):
    root = Path(recipe_dir) if recipe_dir is not None else Path.cwd()
    sampled = sample_frames(fields)
    frames, assets = load_frames([(f["timestamp_seconds"], root / f["path"]) for f in sampled])
    state = {
        "frames": frames,
        "task": "Visible door-state transition across sampled observations only.",
    }
    return state, build_questions(), assets


@dataclass(frozen=True)
class Outcome:
    prediction: str
    accepted: bool
    reason: str
    interval: tuple | None


def route(fields, answer, threshold):
    """No answer can bypass time validation or turn a deferral into an accepted event."""
    if isinstance(threshold, bool) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    problem = preflight_reason(fields)
    if problem is not None:
        return Outcome(REVIEW, False, problem, None)
    if answer is None or getattr(answer, "choice", None) not in OPTIONS[:-1]:
        return Outcome(REVIEW, False, "no determinate transition", None)
    confidence = getattr(answer, "confidence", None)
    if (
        confidence is None
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
        or confidence < threshold
    ):
        return Outcome(REVIEW, False, "confidence below the threshold", None)
    sampled = sample_frames(fields)
    interval = (sampled[0]["timestamp_seconds"], sampled[-1]["timestamp_seconds"])
    return Outcome(answer.choice, True, "accepted sampled observation", interval)


def log_outcome(ident, outcome, answer, actions, reviews):
    payload = {"example": ident, "observation": outcome.prediction, "interval": outcome.interval}
    if outcome.accepted:
        actions.record("record_observation", payload, answer=answer, rule=outcome.reason)
    else:
        reviews.submit(payload, outcome.reason, answer=answer)


class Session:
    """One cached, bounded request per observation; failures consume the recipe budget."""

    def __init__(self, backend, recipe_dir=None, max_requests=MAX_REQUESTS):
        if type(max_requests) is not int or not 0 <= max_requests <= MAX_REQUESTS:
            raise ValueError("request budget must be an integer from 0 through 25")
        self.backend = backend
        self.recipe_dir = recipe_dir
        self.max_requests = max_requests
        self.requests = 0
        self.cache = {}

    def decide(self, example):
        from jev_cookbook import replay_key

        if preflight_reason(example.fields) is not None:
            return None
        state, questions, assets = build_request(example.fields, self.recipe_dir)
        key = replay_key(state, questions, assets=assets)
        if key not in self.cache:
            if self.requests >= self.max_requests:
                raise RuntimeError("recipe request budget exhausted")
            self.requests += 1
            self.cache[key] = self.backend.decide(state, questions, assets=assets)
        return self.cache[key]


def baseline_features(fields, recipe_dir=None):
    """Read pixels only: dark-gap area and adjacent mean absolute motion in a fixed ROI."""
    root = Path(recipe_dir) if recipe_dir is not None else Path.cwd()
    crops = []
    for frame in sample_frames(fields):
        with Image.open(root / frame["path"]) as image:
            crops.append(np.asarray(image.convert("L").crop(DOOR_REGION), dtype=float))
    gaps = [float(np.mean(crop < 65)) for crop in crops]
    motions = [float(np.abs(b - a).mean()) for a, b in zip(crops, crops[1:], strict=False)]
    return gaps, motions


def baseline(fields, parameters, recipe_dir=None):
    if preflight_reason(fields) is not None:
        return "uncertain"
    delta_threshold, motion_threshold = parameters
    gaps, motions = baseline_features(fields, recipe_dir)
    deltas = [b - a for a, b in zip(gaps, gaps[1:], strict=False)]
    if any(d > delta_threshold for d in deltas) and any(d < -delta_threshold for d in deltas):
        return "uncertain"
    change = gaps[-1] - gaps[0]
    if change > delta_threshold:
        return "opened"
    if change < -delta_threshold:
        return "closed"
    return "uncertain" if max(motions) > motion_threshold else "unchanged"


def choose_baseline(validation, labels, recipe_dir=None):
    """Maximize raw event accuracy on validation; ties keep candidate order."""
    scores = []
    for parameters in BASELINE_CANDIDATES:
        correct = sum(
            baseline(e.fields, parameters, recipe_dir) == labels[e.id] for e in validation
        )
        scores.append((parameters, correct, len(validation)))
    best = max(scores, key=lambda row: row[1])[0]
    return best, scores
