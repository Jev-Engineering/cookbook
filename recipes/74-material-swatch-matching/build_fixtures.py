"""Author controlled synthetic texture PNGs and intentionally imperfect replay answers.

Drawing parameters and gold labels stay here; inference receives only asset bytes.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# Fictional visual references: same color/different pattern; same pattern/different color.
SWATCHES = {
    "M-17": ((181, 160, 124), "weave"),
    "M-28": ((181, 160, 124), "rib"),
    "M-39": ((83, 133, 171), "weave"),
    "M-46": ((171, 99, 72), "dots"),
    "outside": ((112, 158, 94), "diagonal"),
    "recolor": ((174, 103, 154), "weave"),
}

# id, split, appearance, phase, scale, angle, brightness, obstruction, gold, response, p(top)
ROWS = [
    ("v01", "validation", "M-17", 3, 1.0, 0, 1.0, "", "M-17", "M-17", .94),
    ("v02", "validation", "M-28", 7, 1.0, 0, 1.0, "", "M-28", "M-28", .92),
    ("v03", "validation", "M-39", 11, 1.0, 0, 1.0, "", "M-39", "M-39", .93),
    ("v04", "validation", "M-46", 5, 1.0, 0, 1.0, "", "M-46", "M-46", .91),
    ("v05-scale", "validation", "M-17", 9, 1.3, 0, 1.0, "", "M-17", "M-17", .85),
    ("v06-light", "validation", "M-39", 13, 1.0, 0, .86, "", "M-39", "M-39", .83),
    ("v07-turn", "validation", "M-28", 2, 1.0, 42, 1.0, "", "M-28", "M-17", .59),
    ("v08-unknown", "validation", "outside", 6, 1.0, 0, 1.0, "", "no_match", "no_match", .90),
    ("v09-recolor", "validation", "recolor", 9, 1.0, 0, 1.0, "", "no_match", "no_match", .88),
    ("v10-glare", "validation", "M-17", 8, 1.0, 0, 1.0, "glare", "uncertain", "uncertain", .91),
    ("v11-cover", "validation", "M-46", 4, 1.0, 0, 1.0, "cover", "uncertain", "uncertain", .84),
    ("v12-lookalike", "validation", "M-28", 6, 1.4, 0, .92, "", "M-28", "M-17", .65),
    ("t01", "test", "M-17", 17, 1.05, 8, 1.0, "", "M-17", "M-17", .93),
    ("t02", "test", "M-28", 19, 1.05, 4, 1.0, "", "M-28", "M-28", .90),
    ("t03", "test", "M-39", 21, 1.05, 6, 1.0, "", "M-39", "M-39", .91),
    ("t04", "test", "M-46", 14, 1.1, 9, 1.0, "", "M-46", "M-46", .92),
    ("t05-scale", "test", "M-17", 18, 1.45, 0, 1.0, "", "M-17", "M-17", .81),
    ("t06-light", "test", "M-39", 16, 1.0, 0, .80, "", "M-39", "M-39", .72),
    ("t07-lookalike", "test", "M-28", 23, 1.25, 35, 1.0, "", "M-28", "M-17", .95),
    ("t08-unknown", "test", "outside", 20, 1.1, 10, 1.0, "", "no_match", "no_match", .91),
    ("t09-recolor", "test", "recolor", 24, 1.2, 20, 1.0, "", "no_match", "no_match", .86),
    ("t10-glare", "test", "M-39", 22, 1.0, 12, 1.0, "glare", "uncertain", "uncertain", .94),
    ("t11-cover", "test", "M-28", 25, 1.0, 0, 1.0, "cover", "uncertain", "uncertain", .90),
    ("t12-turn", "test", "M-46", 28, 1.0, 60, .96, "", "M-46", "M-46", .88),
    ("d01", "demo", "M-28", 31, 1.2, 20, .97, "", None, "M-28", .89),
    ("d02", "demo", "M-17", 33, 1.0, 0, 1.0, "glare", None, "uncertain", .93),
]  # fmt: skip


def draw_swatch(kind, phase, scale=1.0, angle=0, brightness=1.0, obstruction=""):
    """Analytic synthetic surface, explicitly not a photograph or material simulation."""
    color, pattern = SWATCHES[kind]
    y, x = np.mgrid[0:320, 0:384]
    theta = np.deg2rad(angle)
    u = (x * np.cos(theta) + y * np.sin(theta) + phase) / scale
    v = (-x * np.sin(theta) + y * np.cos(theta) + phase * 0.7) / scale
    if pattern == "weave":
        texture = 15 * np.sin(u * np.pi / 5) + 15 * np.sin(v * np.pi / 5)
        texture += 7 * np.sign(np.sin(u * np.pi / 20) * np.sin(v * np.pi / 20))
    elif pattern == "rib":
        texture = 29 * np.sin(u * np.pi / 5) + 3 * np.sin(v * np.pi / 2)
    elif pattern == "dots":
        texture = np.where((u % 22 - 11) ** 2 + (v % 22 - 11) ** 2 < 28, -42, 7)
    else:
        texture = 24 * np.sin((u + v) * np.pi / 12)
    grain = 1.3 * np.sin(x * 0.73 + y * 1.19 + phase)
    rgb = (np.array(color)[None, None, :] + texture[..., None] + grain[..., None]) * brightness
    if obstruction == "glare":
        rgb = 255 * 0.91 + rgb * 0.09
        rgb[:, 38:347] = 255
    if obstruction == "cover":
        rgb = np.full_like(rgb, 190.0 + phase * 0.13) + (x / 384 * 6)[..., None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype("uint8"))


def write_assets():
    (HERE / "assets").mkdir(exist_ok=True)
    for name, path in helpers.REFERENCES.items():
        draw_swatch(name, 0).save(HERE / path)
    for row in ROWS:
        ident, _, kind, phase, scale, angle, brightness, obstruction, *_ = row
        draw_swatch(kind, phase, scale, angle, brightness, obstruction).save(
            HERE / "assets" / f"{ident}.png"
        )


def fields_for(row):
    return {"image": f"assets/{row[0]}.png"}


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for row in rows:
        ident, split, *_, label, _choice, _prob = row
        fields = fields_for(row)
        state, questions, assets = helpers.build_request(fields, HERE)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        state, questions, assets = helpers.build_request(fields_for(row), HERE)
        choice, probability = row[-2:]
        probs = {name: (1 - probability) / 5 for name in helpers.OPTIONS}
        probs[choice] = probability
        answer = ChoiceAnswer.from_probabilities(probs, Provenance.synthetic())
        key = replay_key(state, questions, assets=assets)
        responses[key] = DecisionResult({"swatch": answer}, "synthetic").to_dict()
    return responses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    write_assets()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text("".join(json.dumps(row) + "\n" for row in rows), "utf-8")
    path = folder / "responses.json"
    if path.exists() and not args.force:
        stored = json.loads(path.read_text("utf-8"))
        if any(value.get("model") != "synthetic" for value in stored.values()):
            raise SystemExit("refusing to overwrite recorded responses; use --force")
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
