"""Ordered screenshots, bounded visual questions, and a simulated handoff policy."""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence, select_confidence_threshold
from jev_cookbook.vision import image_asset, image_reference

SUCCESS = "success"
NOT_OBSERVED = "not_observed"
REVIEW = "review"
PIXEL_THRESHOLD = 0.01
INTENTS = {
    "open_export": {
        "action": "Click Export report.",
        "postcondition": "The Export report dialog is open.",
    },
    "save_notifications": {
        "action": "Enable notifications, then click Save.",
        "postcondition": (
            "The notifications panel displays the saved-state confirmation 'Saved: enabled'."
        ),
    },
}


def frame_problem(fields, recipe_dir):
    """Return a deterministic review reason, or None. Never silently reorder evidence."""
    if fields.get("intent") not in INTENTS:
        return "unsupported action intent"
    frames = fields.get("frames", [])
    if len(frames) < 2:
        return "missing before or after frame"
    timestamps = [frame.get("timestamp_ms") for frame in frames]
    action_time = fields.get("action_timestamp_ms")
    if any(type(t) is not int or t < 0 for t in [action_time, *timestamps]):
        return "timestamps must be nonnegative integer milliseconds"
    if any(a >= b for a, b in zip(timestamps, timestamps[1:], strict=False)):
        return "frames are not in strict chronological order"
    if frames[0].get("phase") != "before" or any(
        frame.get("phase") != "after" for frame in frames[1:]
    ):
        return "expected one before frame followed by after frames"
    if not timestamps[0] < action_time < timestamps[1]:
        return "frames do not bracket the action timestamp"
    dimensions = []
    for frame in frames:
        path = Path(recipe_dir) / frame["asset"]
        if not path.is_file():
            return "frame file is missing"
        try:
            with Image.open(path) as image:
                image.load()
                dimensions.append(image.size)
        except (OSError, ValueError):
            return "frame file cannot be decoded"
    if len(set(dimensions)) != 1:
        return "frame dimensions differ"
    return None


def build_request(fields, recipe_dir):
    """Build inference state from pixels and neutral timing, never gold or render metadata."""
    problem = frame_problem(fields, recipe_dir)
    if problem:
        raise ValueError(problem)
    assets, frames = {}, []
    for frame in fields["frames"]:
        asset = image_asset(Path(recipe_dir) / frame["asset"])
        ref = image_reference(asset)
        assets[ref] = asset
        frames.append(
            {
                "phase": frame["phase"],
                "timestamp_ms": frame["timestamp_ms"],
                "image": ref,
            }
        )
    intent = INTENTS[fields["intent"]]
    state = {
        "simulated_action": intent["action"],
        "action_timestamp_ms": fields["action_timestamp_ms"],
        "desired_postcondition": intent["postcondition"],
        "frames_in_capture_order": frames,
    }
    return state, build_questions(fields["intent"]), assets


def build_questions(intent):
    """Two independent propositions: the final state and the initial state."""
    postcondition = INTENTS[intent]["postcondition"]
    return {
        "postcondition": Noul(
            instructions=(
                "In the final after screenshot, this statement is true: " + postcondition
            ),
            criteria={
                "true": "The final screenshot visibly establishes exactly this postcondition.",
                "false": (
                    "The final screenshot shows a different state. A loading indicator, an "
                    "unrelated banner, or a report of clicking is not the requested final state."
                ),
            },
        ),
        "initially_absent": Noul(
            instructions=(
                "In the first before screenshot, the following postcondition is absent: "
                + postcondition
            ),
            criteria={
                "true": "The initial screenshot visibly lacks the requested postcondition.",
                "false": "The initial screenshot already displays the requested postcondition.",
            },
        ),
    }


def collect(examples, backend, recipe_dir):
    """Decide each valid example once; missing evidence does not spend a request."""
    results = {}
    for example in examples:
        if frame_problem(example.fields, recipe_dir):
            results[example.id] = None
        else:
            state, questions, assets = build_request(example.fields, recipe_dir)
            results[example.id] = backend.decide(state, questions, assets=assets)
    return results


def certainty(result):
    """A derived certainty, not a Noul API confidence field."""
    return min(noul_confidence([answer.noul for answer in result.answers.values()]))


def proposed_outcome(result):
    return SUCCESS if result["postcondition"].noul >= 0.5 else NOT_OBSERVED


def freeze_gate(examples, results, labels):
    """Choose only from eligible validation cases; hard review branches stay separate."""
    if not examples or any(example.split != "validation" for example in examples):
        raise ValueError("gate selection requires validation examples only")
    eligible = [
        example
        for example in examples
        if results[example.id] is not None and results[example.id]["initially_absent"].noul >= 0.5
    ]
    return select_confidence_threshold(
        [proposed_outcome(results[e.id]) == labels[e.id] for e in eligible],
        [certainty(results[e.id]) for e in eligible],
        target_accuracy=1.0,
    )


@dataclass(frozen=True)
class Outcome:
    example_id: str
    outcome: str
    reason: str


def classify(example, result, gate, recipe_dir, *, actions, queue):
    """Python alone chooses review, a final negative, or a simulated accepted handoff."""
    if not isinstance(gate, (int, float)) or not math.isfinite(gate) or not 0 <= gate <= 1:
        raise ValueError("gate must be finite and between 0 and 1")
    reason = frame_problem(example.fields, recipe_dir)
    if reason is None and result is None:
        reason = "no visual answer available"
    if reason is None and result["initially_absent"].noul < 0.5:
        reason = "initial absence of the postcondition not established"
    if reason is None and certainty(result) < gate:
        reason = "confidence below the threshold"
    if reason is not None:
        queue.submit({"example_id": example.id}, reason, answer=result)
        return Outcome(example.id, REVIEW, reason)
    outcome = proposed_outcome(result)
    if outcome == SUCCESS:
        actions.record(
            "simulated handoff accepted",
            {"example_id": example.id, "intent": example.fields["intent"]},
            answer=result,
            rule="valid ordered frames, initially absent, postcondition true, certainty gate",
        )
        return Outcome(example.id, SUCCESS, "requested visible transition verified")
    return Outcome(example.id, NOT_OBSERVED, "requested postcondition not observed")


def changed_fraction(fields, recipe_dir):
    """Independent baseline: fraction of pixels differing in any RGB channel."""
    if frame_problem(fields, recipe_dir):
        return None
    images = []
    for frame in (fields["frames"][0], fields["frames"][-1]):
        with Image.open(Path(recipe_dir) / frame["asset"]) as image:
            images.append(np.asarray(image.convert("RGB")))
    return float(np.any(images[0] != images[1], axis=2).mean())


def pixel_baseline(fields, recipe_dir):
    fraction = changed_fraction(fields, recipe_dir)
    if fraction is None:
        return REVIEW
    return SUCCESS if fraction >= PIXEL_THRESHOLD else NOT_OBSERVED
