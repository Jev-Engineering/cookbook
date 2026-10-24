"""Author synthetic factory drawings and deliberately imperfect visual responses.

Scene parameters and expected event descriptions stay here and in labels, never in
inference state. No camera, model, or machine is contacted by this generator.
"""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from jev_cookbook import (
    DecisionResult,
    NoulAnswer,
    Provenance,
    ScoreAnswer,
    load_helpers,
    replay_key,
)

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# id, split, scene, geometry seed, command, metadata age, event, authored response profile
ROWS = [
    ("v01", "validation", "moving", 1, "running", 0.1, "movement_observed", "moving"),
    ("v02", "validation", "pile", 2, "running", 0.2, "jam_indication", "jam"),
    ("v03", "validation", "stationary", 3, "stopped", 0.3, "stopped_as_commanded", "still"),
    ("v04", "validation", "stationary", 4, "running", 0.1, "halted_cause_unobserved", "still"),
    ("v05", "validation", "empty", 5, "running", 0.2, "empty_lane", "empty"),
    ("v06", "validation", "frozen", 6, "running", 0.1, "review", "jam"),
    ("v07", "validation", "moving", 7, "running", 4.0, "review", "moving"),
    ("v08", "validation", "occluded", 8, "running", 0.2, "review", "occluded"),
    ("v09", "validation", "slow", 9, "running", 0.3, "movement_observed", "moving_soft"),
    ("v10", "validation", "pile", 10, "stopped", 0.1, "review", "jam"),
    ("v11", "validation", "guard", 11, "running", 0.2, "halted_cause_unobserved", "wrong_soft"),
    ("v12", "validation", "intrusion", 12, "running", 0.2, "review", "partial"),
    ("t01", "test", "moving", 21, "running", 0.1, "movement_observed", "moving"),
    ("t02", "test", "pile", 22, "running", 0.2, "jam_indication", "jam"),
    ("t03", "test", "stationary", 23, "stopped", 0.3, "stopped_as_commanded", "still"),
    ("t04", "test", "stationary", 24, "running", 0.1, "halted_cause_unobserved", "still"),
    ("t05", "test", "empty", 25, "running", 0.2, "empty_lane", "empty"),
    ("t06", "test", "frozen", 26, "running", 0.1, "review", "jam"),
    ("t07", "test", "stationary", 27, "unknown", 0.1, "review", "still"),
    ("t08", "test", "occluded", 28, "running", 0.2, "review", "occluded"),
    ("t09", "test", "guard", 29, "running", 0.1, "halted_cause_unobserved", "wrong_strong"),
    ("t10", "test", "dark", 30, "running", 0.2, "movement_observed", "moving"),
    ("t11", "test", "slow", 31, "running", 0.2, "movement_observed", "uncertain"),
    ("t12", "test", "intrusion", 32, "running", 0.2, "review", "partial"),
    ("d01", "demo", "pile", 41, "running", 0.2, None, "jam"),
    ("d02", "demo", "stationary", 42, "stopped", 0.1, None, "still"),
]  # fmt: skip

NOTES = {
    "moving": "Parcels change position; exit is clear.",
    "pile": "Three contacting parcels remain pressed against the red exit barrier.",
    "stationary": "Parcels remain still; the changing independent indicator excludes an exact frozen image. No visible obstruction establishes a cause.",
    "empty": "No parcels appear anywhere in the lane.",
    "frozen": "All sampled image bytes repeat. A frozen camera and a completely static scene cannot be distinguished.",
    "occluded": "A cover hides the parcel lane in the middle frame; the event is unobservable.",
    "slow": "Parcels move four pixels per sample, visible at full resolution.",
    "guard": "The red guard is above the lane with a visible gap; stationary parcels do not contact it.",
    "intrusion": "An object intrudes into the exit but does not contact the stationary parcel; active blockage is unresolved.",
    "dark": "Dark blue parcels visibly move; the orange-only pixel baseline misses them.",
}


def frame_image(scene, seed, frame):
    """A fixed synthetic camera view; drawings are not real factory photographs."""
    if scene == "frozen":
        frame = 0
    image = Image.new("RGB", (384, 320), (239, 242, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 25, 365, 110), fill=(221, 226, 232), outline=(95, 105, 115), width=2)
    draw.text((31, 40), "SYNTHETIC CONVEYOR / FIXED CAMERA", fill=(30, 30, 30))
    draw.line((32, 87, 290, 87), fill=(150, 158, 168), width=2)
    draw.rectangle((310 + frame * 13, 69, 319 + frame * 13, 81), fill=(50, 150, 110))
    draw.rectangle((30, 147, 354, 250), fill=(80, 87, 94), outline=(30, 30, 30), width=3)
    draw.rectangle((40, 157, 344, 240), fill=(47, 52, 58))
    for x in range(48, 345, 24):
        draw.line((x, 241, x, 247), fill=(180, 185, 190), width=2)
    draw.rectangle((55, 250, 69, 286), fill=(93, 100, 108))
    draw.rectangle((315, 250, 329, 286), fill=(93, 100, 108))
    draw.text((115, 278), "TRAVEL  ---------------->", fill=(30, 30, 30))
    # Geometry changes across sequences, independently of their expected event.
    y = 175 + seed % 7
    x = 77 + seed % 17
    delta = 4 if scene == "slow" else 24
    if scene in ("moving", "dark", "slow"):
        x += delta * frame
    parcels = [] if scene == "empty" else [(x, y, x + 37, y + 43)]
    if scene in ("pile", "frozen"):
        parcels = [(211, y + 8, 247, y + 47), (249, y + 8, 285, y + 47), (287, y + 8, 323, y + 47)]
        draw.rectangle((324, 156, 337, 239), fill=(208, 48, 59))
    if scene == "intrusion":
        draw.rectangle((324, 157, 337, 184), fill=(208, 48, 59))
    if scene == "guard":
        draw.rectangle((324, 117, 337, 142), fill=(208, 48, 59))
        draw.text((42, 123), "DISPLAY: REPORT JAM", fill=(130, 30, 45))
    color = (55, 100, 140) if scene == "dark" else (215 + seed % 20, 121, 47)
    for box in parcels:
        draw.rectangle(box, fill=color, outline=(32, 35, 38), width=2)
        draw.line((box[0] + 18, box[1] + 2, box[0] + 18, box[3] - 2), fill=(240, 205, 145), width=3)
    if scene == "occluded" and frame == 1:
        draw.rectangle((38, 154, 346, 241), fill=(160, 168, 176))
        draw.line((42, 158, 342, 237), fill=(110, 117, 126), width=4)
    # This housing fastener varies by camera setup; it is not a class marker.
    draw.ellipse((25 + seed, 298, 29 + seed, 302), fill=(90, 95, 100))
    return image


def fields_for(row):
    ident, _split, scene, seed, operation, age, _label, _profile = row
    frames = []
    for frame in range(3):
        opaque = hashlib.sha256(f"conveyor:{ident}:{frame}".encode()).hexdigest()[:16]
        relative = f"assets/{opaque}.png"
        path = HERE / relative
        path.parent.mkdir(exist_ok=True)
        image = frame_image(scene, seed, frame)
        image.save(path, format="PNG", optimize=False)
        frames.append({"timestamp_seconds": frame * 0.5, "path": relative})
    return {"frames": frames, "operation": operation, "telemetry_age_seconds": age}


def answers_for(profile):
    # visible, present, movement, score probabilities. Answers are authored, not inferred.
    profiles = {
        "moving": (0.98, 0.98, 0.97, (0.96, 0.02, 0.01, 0.01)),
        "moving_soft": (0.95, 0.95, 0.90, (0.94, 0.03, 0.02, 0.01)),
        "jam": (0.98, 0.98, 0.02, (0.01, 0.01, 0.02, 0.96)),
        "still": (0.97, 0.97, 0.03, (0.95, 0.03, 0.01, 0.01)),
        "empty": (0.98, 0.02, 0.02, (0.96, 0.02, 0.01, 0.01)),
        "occluded": (0.04, 0.80, 0.50, (0.40, 0.40, 0.15, 0.05)),
        "wrong_soft": (0.97, 0.97, 0.21, (0.01, 0.01, 0.02, 0.96)),
        "wrong_strong": (0.99, 0.99, 0.01, (0.005, 0.005, 0.01, 0.98)),
        "partial": (0.97, 0.97, 0.03, (0.02, 0.05, 0.90, 0.03)),
        "uncertain": (0.97, 0.97, 0.63, (0.95, 0.03, 0.01, 0.01)),
    }
    visible, present, moving, probabilities = profiles[profile]
    provenance = Provenance.synthetic()
    answers = {
        name: NoulAnswer(value, provenance)
        for name, value in zip(
            ("visible", "present", "movement"), (visible, present, moving), strict=True
        )
    }
    answers["obstruction"] = ScoreAnswer.from_probabilities(
        probabilities, helpers.RUBRIC, provenance
    )
    return DecisionResult(answers, "synthetic").to_dict()


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for row in rows:
        ident, split, scene, _seed, operation, age, label, _profile = row
        fields = fields_for(row)
        prepared = helpers.prepare(fields, HERE)
        keys = (
            []
            if prepared.interlock
            else [replay_key(prepared.state, QUESTIONS, assets=prepared.assets)]
        )
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if label is not None:
            reason = NOTES[scene]
            if operation == "unknown":
                reason += " Operating command is unavailable."
            if age > 2:
                reason += " Operating metadata is stale."
            if operation == "stopped":
                reason += " The command is stopped; do not infer an active jam from stillness."
            labels.append({"id": ident, "label": {"event": label, "reason": reason}})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        prepared = helpers.prepare(fields_for(row), HERE)
        if prepared.interlock is None:
            key = replay_key(prepared.state, QUESTIONS, assets=prepared.assets)
            responses[key] = answers_for(row[-1])
    return responses


def _is_recorded(path):
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
    except (ValueError, OSError):
        return True
    return not isinstance(data, dict) or any(
        not isinstance(row, dict) or row.get("model") != "synthetic" for row in data.values()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
        )
    responses_path = folder / "responses.json"
    if _is_recorded(responses_path) and not args.force:
        raise SystemExit(
            "refusing to overwrite recorded responses without --force; inputs and labels regenerated"
        )
    responses = build_responses(ROWS)
    responses_path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(inputs)} sequences, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
