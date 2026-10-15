"""Visual claim judgments; exact freshness and simulated recommendations belong to Python."""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from jev_cookbook import Noul
from jev_cookbook.evaluation import accuracy, evaluate_outcomes, noul_confidence, per_class_metrics
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import image_asset, image_reference

CLAIMS = ("phase", "action", "status")
REVIEW = "review"
KNOWN = {
    "phase": {"combat", "map", "rewards", "menu", "loading"},
    "action": {"attack", "block", "choose_route", "collect", "none"},
    "status": {"ready", "executing", "complete", "paused", "loading"},
}
MAX_FRAME_AGE_MS = 2000
MAX_OVERLAY_LAG_MS = 3000
GATES = (0.0, 0.5, 0.75, 0.9)


def build_request(fields, recipe_dir):
    """Only input evidence crosses the boundary; filenames and labels do not."""
    frames, assets = [], {}
    for frame in fields["frames"]:
        asset = image_asset(Path(recipe_dir) / frame["path"])
        reference = image_reference(asset)
        assets[reference] = asset
        frames.append({"captured_ms": frame["captured_ms"], "image": reference})
    state = {
        "frames_in_supplied_order": frames,
        "agent_claims": dict(fields["agent_claims"]),
        "game_telemetry": dict(fields["game_telemetry"]),
        "claim_vocabulary": {name: sorted(values) for name, values in KNOWN.items()},
        "overlay_updated_ms": fields["overlay_updated_ms"],
        "observed_ms": fields["observed_ms"],
        "legend": (
            "Each authored frame: gameplay above y=272; agent overlay below y=272. "
            "The bottom overlay repeats agent_claims; it is a claim, not corroboration. "
            "Telemetry is a fallible game-state cache available to the exact baseline. "
            "Judge visual propositions only from the gameplay area of the final supplied "
            "frame. The prior frame provides context, never proof of a later completed action."
        ),
    }
    return state, assets


def build_questions():
    """Six independent true/false propositions in one request."""
    questions = {}
    for claim in CLAIMS:
        target = f"`agent_claims.{claim}`"
        evidence = (
            f"the final frame's gameplay area, excluding the agent overlay and telemetry. "
            f"The target is the displayed {claim} claim {target}. "
        )
        questions[f"{claim}_resolvable"] = Noul(
            instructions=(
                f"The gameplay evidence is sufficient to confirm or refute {target}. "
                f"Use {evidence}Judge this proposition independently of the support proposition."
            ),
            criteria={
                "true": "Readable game indicators establish this field's value.",
                "false": (
                    "The relevant HUD is occluded, unreadable, absent, or outside the defined "
                    "vocabulary. A loading screen alone cannot establish an action or readiness."
                ),
            },
        )
        questions[f"{claim}_supported"] = Noul(
            instructions=(
                f"The gameplay visibly supports {target}. Use {evidence}"
                "Judge the current displayed game field, not whether the strategy is wise "
                "or whether an intended action will happen."
            ),
            criteria={
                "true": "The readable gameplay field agrees with the agent's stated value.",
                "false": (
                    "The gameplay contradicts the claim, or does not establish it. Python "
                    "uses the separate resolvability answer to distinguish those two cases."
                ),
            },
        )
    return questions


def freshness(fields):
    """Time arithmetic only; stale video never proves a semantic disagreement."""
    timestamps = [frame["captured_ms"] for frame in fields["frames"]]
    values = [*timestamps, fields["overlay_updated_ms"], fields["observed_ms"]]
    if (
        len(timestamps) != 2
        or any(
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or value < 0
            for value in values
        )
        or not timestamps[0] < timestamps[1] <= fields["observed_ms"]
        or fields["overlay_updated_ms"] > timestamps[1]
    ):
        return ("invalid_timestamps",)
    flags = []
    if fields["observed_ms"] - timestamps[1] > MAX_FRAME_AGE_MS:
        flags.append("stream_stale")
    if timestamps[1] - fields["overlay_updated_ms"] > MAX_OVERLAY_LAG_MS:
        flags.append("overlay_delayed")
    return tuple(flags)


def _gate(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("gate must be a finite number in [0, 1]")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("gate must be a finite number in [0, 1]")


def claim_labels(fields, answers, gate):
    """Unresolvable evidence and internally inconsistent answers are always unresolved."""
    _gate(gate)
    labels, reasons = {}, {}
    for claim in CLAIMS:
        resolvable = answers[f"{claim}_resolvable"]
        supported = answers[f"{claim}_supported"]
        if "invalid_timestamps" in freshness(fields):
            label, reason = "unresolved", "frame order is invalid"
        elif fields["agent_claims"][claim] not in KNOWN[claim]:
            label, reason = "unresolved", "unknown claim vocabulary"
        elif min(noul_confidence([resolvable, supported])) < gate:
            label, reason = "unresolved", "confidence below the threshold"
        elif resolvable.noul < 0.5:
            label = "unresolved"
            reason = (
                "support contradicts unresolvable evidence"
                if supported.noul >= 0.5
                else "evidence does not settle this claim"
            )
        elif resolvable.noul == 0.5 or supported.noul == 0.5:
            label, reason = "unresolved", "probability tie"
        else:
            label = "supported" if supported.noul > 0.5 else "unsupported"
            reason = "readable gameplay agrees" if label == "supported" else "visible disagreement"
        labels[claim], reasons[claim] = label, reason
    return labels, reasons


@dataclass(frozen=True)
class Outcome:
    claims: dict
    time_flags: tuple
    semantic_mismatch: bool
    review: bool
    recommendation: str

    @property
    def outcome(self):
        return REVIEW if self.review else "retain"


def route(ident, fields, answers, gate, *, actions, queue):
    labels, reasons = claim_labels(fields, answers, gate)
    flags = freshness(fields)
    mismatch = "unsupported" in labels.values()
    review = bool(flags) or any(label != "supported" for label in labels.values())
    evidence = {name: answer.to_dict() for name, answer in answers.items()}
    if review:
        queue.submit(
            {"example": ident, "claims": labels, "time_flags": list(flags)},
            "; ".join([*flags, *(f"{name}: {reason}" for name, reason in reasons.items())]),
            answer=evidence,
        )
        recommendation = "review evidence before any overlay update"
    else:
        recommendation = "retain the verified overlay"
        actions.record(
            "overlay recommendation",
            {"example": ident, "recommendation": recommendation},
            answer=evidence,
            rule="all claims supported; valid, fresh timestamps",
        )
    return Outcome(labels, flags, mismatch, review, recommendation)


def exact_baseline(fields):
    """Same raw claims, telemetry and timestamps; no gold or model answer access."""
    invalid = "invalid_timestamps" in freshness(fields)
    result = {}
    for claim in CLAIMS:
        stated, telemetry = fields["agent_claims"][claim], fields["game_telemetry"][claim]
        if invalid or stated not in KNOWN[claim] or telemetry not in KNOWN[claim]:
            result[claim] = "unresolved"
        else:
            result[claim] = "supported" if stated == telemetry else "unsupported"
    return result


def select_gate(examples, answers, gold):
    """Maximum answered claims at 100% validation accuracy; ties choose the lower gate."""
    sweep = []
    for gate in GATES:
        predicted, expected = [], []
        for example in examples:
            labels, _ = claim_labels(example["fields"], answers[example["id"]], gate)
            predicted.extend(labels[name] for name in CLAIMS)
            expected.extend(gold[example["id"]]["claims"][name] for name in CLAIMS)
        metric = evaluate_outcomes(
            [label != "unresolved" for label in predicted],
            [left == right for left, right in zip(predicted, expected, strict=True)],
        )
        sweep.append((gate, metric))
    eligible = [
        (gate, metric) for gate, metric in sweep if metric.n_answered and metric.accuracy >= 1.0
    ]
    if not eligible:
        raise ValueError("no validation gate meets the predeclared selection objective")
    gate, _ = max(eligible, key=lambda item: (item[1].n_answered, -item[0]))
    return gate, sweep


def evaluate(examples, answers, gold, gate):
    """Actual three-way outcomes, including abstention, and event precision with counts."""
    actions, queue = ActionLog(), ReviewQueue()
    outcomes = {
        example["id"]: route(
            example["id"],
            example["fields"],
            answers[example["id"]],
            gate,
            actions=actions,
            queue=queue,
        )
        for example in examples
    }
    reports = {}
    for method in ("visual", "exact_baseline"):
        predictions = [
            outcomes[example["id"]].claims
            if method == "visual"
            else exact_baseline(example["fields"])
            for example in examples
        ]
        claim_report = {}
        for claim in CLAIMS:
            predicted = [labels[claim] for labels in predictions]
            expected = [gold[example["id"]]["claims"][claim] for example in examples]
            selective = evaluate_outcomes(
                [label != "unresolved" for label in predicted],
                [a == b for a, b in zip(predicted, expected, strict=True)],
            )
            claim_report[claim] = {
                "N": len(examples),
                "three_way_accuracy": accuracy(expected, predicted),
                "answered": selective.n_answered,
                "answered_accuracy": selective.accuracy,
                "abstention": 1 - selective.coverage,
            }
        predicted_events = [
            "mismatch" if "unsupported" in p.values() else "no_established_mismatch"
            for p in predictions
        ]
        expected_events = [
            "mismatch" if gold[example["id"]]["semantic_mismatch"] else "no_established_mismatch"
            for example in examples
        ]
        counts = per_class_metrics(
            expected_events, predicted_events, labels=("no_established_mismatch", "mismatch")
        )
        event = counts["mismatch"]
        reports[method] = {
            "claims": claim_report,
            "event": {
                "N": len(examples),
                "tp": event.tp,
                "fp": event.fp,
                "fn": event.fn,
                "precision": event.precision,
                "recall": event.recall,
            },
        }
    return reports, outcomes, actions, queue


def pixel_difference(fields, recipe_dir):
    """A display diagnostic, not evidence that any particular claim is false."""
    images = [
        np.asarray(Image.open(Path(recipe_dir) / frame["path"]).convert("RGB"), dtype=np.int16)
        for frame in fields["frames"]
    ]
    return np.any(images[0] != images[1], axis=2)
