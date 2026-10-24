"""Bounded visual inspection, deterministic review rules and pixel-only comparison."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from jev_cookbook import Box, Noul, replay_key
from jev_cookbook.evaluation import evaluate_outcomes
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import (
    box_confidence,
    box_iou,
    image_asset,
    image_reference,
    localization_metrics,
    normalized_box,
    run_record,
)

REVIEW = "review"
SCREEN = 0.8
KINDS = ("scratch", "dent", "broken component")
CANDIDATES = tuple((p, b) for p in (0.8, 0.9, 0.95) for b in (0.6, 0.8, 0.9))


def request(fields, root=Path("."), *, locate=False):
    """Only image bytes and the requested defect reach inference; paths stay local."""
    if fields["target"] not in KINDS:
        raise ValueError("unsupported target")
    asset = image_asset(Path(root) / fields["image"])
    ref = image_reference(asset)
    state = {
        "image": ref,
        "requested_defect": fields["target"],
        "inspection_window": "the brushed metal panel inside its four corner screws",
    }
    return state, build_questions(locate=locate), {ref: asset}


def build_questions(*, locate=False):
    """One independent proposition per Noul; the dependent Box is a later request."""
    if locate:
        return {
            "defect": Box(
                instructions=(
                    "Enclose the one requested visible defect in the inspection window. "
                    "Use a tight rectangle around the full scratch, the entire dent rim, "
                    "or the broken component including its separated pieces. Exclude "
                    "unrelated fasteners, printed lines, reflection and intact components."
                )
            )
        }
    return {
        "present": Noul(
            instructions=(
                "At least one visible instance of the requested defect is present in the "
                "inspection window. Scratches have irregular gouged edges; dents have "
                "a depressed shaded bowl and rim; a broken component has a visible fracture "
                "or separated parts. A straight printed line or bright reflection is not damage."
            )
        ),
        "unique": Noul(
            instructions=(
                "Exactly one candidate of the requested defect kind is visible in the "
                "inspection window. Separate scratches or dents count separately."
            )
        ),
        "clear": Noul(
            instructions=(
                "The inspection window is sufficiently unobstructed to determine the "
                "presence and full extent of the requested defect. A cover or tool "
                "hiding any candidate makes this statement false."
            )
        ),
    }


@dataclass(frozen=True)
class Policy:
    presence: float
    box: float

    def __post_init__(self):
        if not SCREEN <= self.presence <= 1 or not 0 <= self.box <= 1:
            raise ValueError("policy thresholds outside supported range")


@dataclass(frozen=True)
class Outcome:
    outcome: str
    reason: str
    box: dict | None = None

    @property
    def accepted(self):
        return self.outcome != REVIEW


def eligible(answers, threshold=SCREEN):
    return all(answers[name].noul >= threshold for name in ("present", "unique", "clear"))


def route(answers, box, policy):
    """Fail closed on occlusion, ambiguity and missing confidence, regardless of a box."""
    p, unique, clear = (answers[name].noul for name in ("present", "unique", "clear"))
    if clear < policy.presence:
        return Outcome(REVIEW, "inspection window is occluded or uncertain")
    if p <= 1 - policy.presence and unique <= 1 - policy.presence:
        return Outcome("absent", "confident absence; no rectangle")
    if not eligible(answers, policy.presence):
        return Outcome(REVIEW, "presence or unique-target evidence is insufficient")
    if box is None or box_confidence(box) is None:
        return Outcome(REVIEW, "box confidence is missing")
    if box_confidence(box) < policy.box:
        return Outcome(REVIEW, "confidence below the threshold")
    return Outcome("located", "visible unique target and box passed", normalized_box(box))


class Inspector:
    """At most two requests per image; cached results serve validation policy trials."""

    def __init__(self, backend, root=Path("."), *, max_requests=60):
        if type(max_requests) is not int or max_requests < 0:
            raise ValueError("max_requests must be a nonnegative integer")
        self.backend, self.root, self.max_requests = backend, Path(root), max_requests
        self.cache = {}
        self.calls = 0
        self.accounting = []
        self.actions, self.reviews = ActionLog(), ReviewQueue()

    def decide(self, triple):
        state, questions, assets = triple
        key = replay_key(state, questions, assets=assets)
        if key not in self.cache:
            if self.calls >= self.max_requests:
                raise RuntimeError("inspection request budget exhausted")
            self.calls += 1
            result = self.backend.decide(state, questions, assets=assets)
            self.cache[key] = result
            self.accounting.append(run_record(result, mode=self.backend.mode))
        return self.cache[key]

    def acquire(self, fields):
        first = self.decide(request(fields, self.root))
        box = None
        if eligible(first.answers):
            box = self.decide(request(fields, self.root, locate=True)).answers["defect"]
        return first, box

    def inspect(self, ident, fields, policy):
        first, box = self.acquire(fields)
        result = route(first.answers, box, policy)
        if result.outcome == REVIEW:
            self.reviews.submit({"id": ident}, result.reason, answer=first.answers["present"])
        elif result.outcome == "located":
            self.actions.record(
                "propose_annotation",
                {"id": ident, "box": result.box},
                answer=box,
                rule="presence, uniqueness, visibility and box gates passed",
            )
        return result


def correct(outcome, label):
    if label["outcome"] == REVIEW:
        return outcome.outcome == REVIEW
    if label["outcome"] == "absent":
        return outcome.outcome == "absent"
    return outcome.outcome == "located" and box_iou(outcome.box, label["box"]) >= 0.5


def select_policy(observations, labels, *, target_accuracy):
    """Maximize answered count subject to accuracy, using validation observations only."""
    if not 0 < target_accuracy <= 1 or len(observations) != len(labels) or not labels:
        raise ValueError("invalid selection inputs")
    trials = []
    for presence, confidence in CANDIDATES:
        policy = Policy(presence, confidence)
        outcomes = [route(first.answers, box, policy) for first, box in observations]
        scores = evaluate_outcomes(
            [outcome.accepted for outcome in outcomes],
            [correct(outcome, label) for outcome, label in zip(outcomes, labels, strict=True)],
        )
        trials.append((policy, scores))
    feasible = [(p, s) for p, s in trials if s.n_answered and s.accuracy >= target_accuracy]
    if not feasible:
        raise ValueError("no candidate policy meets the validation objective")
    chosen, _ = max(
        feasible, key=lambda ps: (ps[1].n_answered, ps[1].accuracy, ps[0].presence, ps[0].box)
    )
    return chosen, trials


def summarize(outcomes, labels):
    """Review is excluded from accuracy but is a missing delivery in all-target geometry."""
    accepted = [o.accepted for o in outcomes]
    selective = evaluate_outcomes(
        accepted, [correct(o, label) for o, label in zip(outcomes, labels, strict=True)]
    )
    geometrically_labeled = [
        (o, label) for o, label in zip(outcomes, labels, strict=True) if label["outcome"] != REVIEW
    ]
    geometry = (
        localization_metrics(
            [label["box"] for _, label in geometrically_labeled],
            [o.box if o.accepted else None for o, _ in geometrically_labeled],
        )
        if geometrically_labeled
        else None
    )
    resolved = [(o, label) for o, label in geometrically_labeled if o.accepted]
    resolved_geometry = (
        localization_metrics([label["box"] for _, label in resolved], [o.box for o, _ in resolved])
        if resolved
        else None
    )
    return {
        "n": len(outcomes),
        "answered": selective.n_answered,
        "review": len(outcomes) - selective.n_answered,
        "coverage": selective.coverage,
        "accuracy": selective.accuracy,
        "risk": selective.risk,
        "geometry_n": len(geometrically_labeled),
        "present": 0 if geometry is None else geometry.present,
        "absent": 0 if geometry is None else geometry.absent,
        "mean_iou": None if geometry is None else geometry.mean_iou,
        "missed": 0 if geometry is None else geometry.missed,
        "false_positives": 0 if geometry is None else geometry.false_positives,
        "resolved_mean_iou": None if resolved_geometry is None else resolved_geometry.mean_iou,
        "resolved_present": 0 if resolved_geometry is None else resolved_geometry.present,
        "accepted_misses": 0 if resolved_geometry is None else resolved_geometry.missed,
        "poor_overlap": sum(
            label["box"] is not None and o.box is not None and box_iou(o.box, label["box"]) < 0.5
            for o, label in resolved
        ),
        "reviewed_present": sum(
            not o.accepted and label["outcome"] == "located"
            for o, label in zip(outcomes, labels, strict=True)
        ),
        "invalid_scene_boxes": sum(
            o.box is not None and label["outcome"] == REVIEW
            for o, label in zip(outcomes, labels, strict=True)
        ),
    }


def pixel_baseline(image):
    """Largest 8-connected dark region within a fixed inspection window; no labels or IDs."""
    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    mask = gray < 105
    roi = np.zeros_like(mask)
    roi[int(height * 0.25) : int(height * 0.76), int(width * 0.2) : int(width * 0.8)] = True
    mask &= roi
    seen = np.zeros_like(mask)
    components = []
    for y, x in zip(*np.nonzero(mask), strict=True):
        if seen[y, x]:
            continue
        stack, pixels = [(int(x), int(y))], []
        seen[y, x] = True
        while stack:
            cx, cy = stack.pop()
            pixels.append((cx, cy))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((nx, ny))
        if len(pixels) >= 18:
            components.append(pixels)
    if not components:
        return Outcome("absent", "no dark component above the fixed area floor")
    pixels = max(components, key=len)
    xs, ys = zip(*pixels, strict=True)
    box = {
        "left": min(xs) / width,
        "top": min(ys) / height,
        "right": (max(xs) + 1) / width,
        "bottom": (max(ys) + 1) / height,
    }
    return Outcome("located", "largest dark component", box)


def baseline_for(fields, root=Path(".")):
    with Image.open(Path(root) / fields["image"]) as image:
        return pixel_baseline(image)


def record_corpus(backend, examples, destination, *, root=Path(".")):
    """Opt-in capture using the same dependent request construction and recorder triples.

    Record to a new folder. Resume uses already recorded stage-one answers to decide
    whether stage two is eligible; no synthetic answer determines live requests.
    """
    import json

    from jev_cookbook import ReplayBackend, record
    from jev_cookbook.fixtures import load_labels

    destination = Path(destination)
    manifest = []
    label_rows = []
    gold_labels = load_labels(root)
    for example in examples:
        first = request(example.fields, root)
        record(backend, [first], destination)
        replay = ReplayBackend.from_json(destination)
        result = replay.decide(first[0], first[1], assets=first[2])
        keys = [replay_key(first[0], first[1], assets=first[2])]
        if eligible(result.answers):
            second = request(example.fields, root, locate=True)
            record(backend, [second], destination)
            keys.append(replay_key(second[0], second[1], assets=second[2]))
        manifest.append(
            {
                "id": example.id,
                "split": example.split,
                "fields": dict(example.fields),
                "replay_keys": keys,
            }
        )
        if example.id in gold_labels:
            label_rows.append({"id": example.id, "label": gold_labels[example.id]})
    for name, rows in (("inputs.jsonl", manifest), ("labels.jsonl", label_rows)):
        (destination.parent / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
        )
    return manifest
