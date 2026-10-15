"""Pixel requests, a local similarity baseline, and simulated swatch decisions."""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from jev_cookbook import Choice
from jev_cookbook.evaluation import evaluate_outcomes
from jev_cookbook.vision import image_asset, image_reference

REFERENCES = {
    "M-17": "assets/reference-17.png",
    "M-28": "assets/reference-28.png",
    "M-39": "assets/reference-39.png",
    "M-46": "assets/reference-46.png",
}
NO_MATCH = "no_match"
UNCERTAIN = "uncertain"
OPTIONS = (*REFERENCES, NO_MATCH, UNCERTAIN)
REVIEW = "review"
RADII = (0.04, 0.08, 0.12, 0.18, 0.26)


def build_state(fields, root=None):
    """Only query pixels and acquisition context are visible to inference."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    asset = image_asset(root / fields["image"])
    return {
        "query": image_reference(asset),
        "task": "Visual appearance match for the supplied reference collection.",
    }


def build_questions(root=None):
    """The four category criteria ARE reference images, not texture-name proxies."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    criteria = {
        name: image_reference(image_asset(root / path)) for name, path in REFERENCES.items()
    }
    criteria[NO_MATCH] = "The visible color and texture do not match any supplied reference."
    criteria[UNCERTAIN] = (
        "Glare, cover, blur, or conflicting appearance prevents a defensible visual match."
    )
    return {
        "swatch": Choice(
            instructions=(
                "Which reference has the same visible color and texture as `query`? "
                "Allow rotation, moderate scale change, and mild illumination changes. "
                "A similar color alone or pattern alone is insufficient. Choose no_match "
                "for a clearly different visible swatch, uncertain for obscured evidence. "
                "These fictional IDs express appearance only, never composition or suitability."
            ),
            criteria=criteria,
        )
    }


def build_request(fields, root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    assets = {}
    for path in [fields["image"], *REFERENCES.values()]:
        asset = image_asset(root / path)
        assets[image_reference(asset)] = asset
    return build_state(fields, root), build_questions(root), assets


@dataclass(frozen=True)
class Match:
    label: str
    outcome: str
    reason: str


def route(answer, threshold):
    """A no-match is gated too; uncertainty is always a deferral."""
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    label = getattr(answer, "choice", None)
    if label not in OPTIONS or label == UNCERTAIN:
        return Match(UNCERTAIN, REVIEW, "unrecognized or uncertain appearance")
    confidence = getattr(answer, "confidence", None)
    if (
        not isinstance(confidence, (float, int))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
        or confidence < threshold
    ):
        return Match(label, REVIEW, "confidence below the threshold")
    return Match(
        label, "accepted", "visual candidate" if label in REFERENCES else "no visual match"
    )


def apply_decision(ident, answer, threshold, review_queue, action_log):
    """Only an appearance suggestion can enter this simulated log."""
    decision = route(answer, threshold)
    if decision.outcome == REVIEW:
        review_queue.submit({"sample": ident}, decision.reason, answer=answer)
    elif decision.label in REFERENCES:
        action_log.record(
            "suggest_visual_candidate",
            {"sample": ident, "candidate": decision.label},
            answer=answer,
            rule="frozen confidence gate; appearance suggestion only",
        )
    return decision


def pixel_features(path):
    """Mean RGB plus rotation-tolerant mean edge magnitude and luminance contrast."""
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=float) / 255
    gray = rgb.mean(axis=2)
    edge = (np.abs(np.diff(gray, axis=0)).mean() + np.abs(np.diff(gray, axis=1)).mean()) / 2
    vector = np.r_[rgb.mean(axis=(0, 1)), 4 * edge, 2 * gray.std()]
    return vector, float((rgb.min(axis=2) > 0.94).mean()), float(gray.std())


def baseline(fields, radius, root=None):
    """Read the same query/reference bytes as the Choice; no label or row ID access."""
    if radius not in RADII:
        raise ValueError("radius must be in the frozen candidate family")
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    query, highlights, contrast = pixel_features(root / fields["image"])
    if highlights > 0.25 or contrast < 0.012:
        return Match(UNCERTAIN, REVIEW, "fixed visible-evidence gate")
    distances = {
        name: float(np.linalg.norm(query - pixel_features(root / path)[0]))
        for name, path in REFERENCES.items()
    }
    nearest = min(distances, key=distances.get)
    label = nearest if distances[nearest] <= radius else NO_MATCH
    return Match(label, "accepted", "nearest pixel signature or radius rejection")


def choose_radius(validation, labels, root=None):
    """Validation only: maximize correct accepts minus three wrong accepts.

    Reviews score zero. Ties choose the smallest rejection radius. Color/texture
    weights and visible-evidence gates are fixed before this selection.
    """
    if not validation or any(e.split != "validation" for e in validation):
        raise ValueError("radius selection requires validation examples only")
    rows = []
    for radius in RADII:
        decisions = [baseline(e.fields, radius, root) for e in validation]
        accepted = [d.outcome != REVIEW for d in decisions]
        correct = [d.label == labels[e.id] for e, d in zip(validation, decisions, strict=True)]
        score = sum(
            (1 if ok else -3) for accept, ok in zip(accepted, correct, strict=True) if accept
        )
        rows.append((radius, score, evaluate_outcomes(accepted, correct)))
    return max(rows, key=lambda row: (row[1], -row[0]))[0], rows
