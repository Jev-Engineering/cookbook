"""Seeded Pillow illustrations and explicitly authored synthetic Score answers.

No generative image model or Jev call produces these fixtures. The author assigns rubric
levels and imperfect answer distributions independently; seeds and drawing variants never
enter inference. Running without --force protects any recorded response file.
"""

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from jev_cookbook import DecisionResult, Provenance, ScoreAnswer, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
MOODBOARD = [f"assets/mood-{i:02d}.png" for i in range(1, 4)]
CREAM = (239, 231, 211)
MUTED = [(180, 108, 78), (134, 153, 126), (57, 64, 60), (204, 174, 129)]
VIVID = [(244, 25, 132), (20, 108, 246), (249, 215, 22), (133, 36, 237)]

# id, split, seed, drawing, author gold levels (palette/surface/composition),
# authored modal answers, peak probability, label rationale. Neither labels nor drawing
# recipes are copied to request state. Gold is subjective under this explicit author rubric.
ROWS = [
    ("v01", "validation", 101, "quiet", [3, 3, 3], [3, 3, 3], .96, "Muted flat balanced geometric group."),
    ("v02", "validation", 108, "quiet", [3, 3, 3], [3, 3, 3], .94, "Different arrangement still follows the family."),
    ("v03", "validation", 116, "vivid", [0, 3, 3], [0, 3, 3], .96, "Saturated shapes depart from the muted family."),
    ("v04", "validation", 125, "accent", [2, 3, 3], [2, 3, 3], .92, "One small vivid accent in a muted group."),
    ("v05", "validation", 134, "outline", [3, 0, 3], [3, 0, 3], .94, "Matching colors cannot excuse heavy outlines."),
    ("v06", "validation", 143, "texture", [3, 1, 3], [3, 1, 3], .92, "Broad mottled patches disturb flat surfaces."),
    ("v07", "validation", 152, "sparse", [3, 3, 1], [3, 3, 1], .94, "Single tiny motif leaves an empty field."),
    ("v08", "validation", 161, "crowded", [3, 3, 1], [3, 3, 1], .92, "Twelve major shapes overcrowd the group."),
    ("v09", "validation", 170, "subtle", [3, 2, 3], [3, 3, 3], .64, "One light contour is a small surface departure."),
    ("v10", "validation", 179, "pair", [3, 3, 2], [3, 3, 2], .78, "Two major forms make a readable but sparse group."),
    ("v11", "validation", 188, "blank", None, [1, 1, 1], .25, "No discernible illustration: author requests review, no numeric gold."),
    ("v12", "validation", 197, "foreign", [0, 0, 0], [0, 0, 0], .94, "Vivid outlined fragments have no quiet focal grouping."),
    ("t01", "test", 302, "quiet", [3, 3, 3], [3, 3, 3], .96, "New geometry in the same muted flat family."),
    ("t02", "test", 313, "quiet", [3, 3, 3], [3, 3, 3], .92, "An alternate compatible layout is not a pixel-copy requirement."),
    ("t03", "test", 324, "vivid", [0, 3, 3], [0, 3, 3], .94, "Vivid colors with otherwise compatible treatment."),
    ("t04", "test", 335, "accent", [2, 3, 3], [2, 3, 3], .92, "Minor saturated accent, otherwise muted."),
    ("t05", "test", 346, "outline", [3, 0, 3], [3, 3, 3], .96, "Confident synthetic surface error despite plainly heavy outlines."),
    ("t06", "test", 357, "texture", [3, 1, 3], [3, 1, 3], .92, "Texture remains a surface mismatch even in matching colors."),
    ("t07", "test", 368, "sparse", [3, 3, 1], [3, 3, 1], .94, "A tiny isolated motif is under-composed for this brief."),
    ("t08", "test", 379, "crowded", [3, 3, 1], [3, 3, 1], .90, "Too many major forms despite the correct palette."),
    ("t09", "test", 390, "corner", [3, 3, 1], [3, 3, 2], .66, "A corner-compressed group undermines balanced placement."),
    ("t10", "test", 401, "pair", [3, 3, 2], [3, 3, 2], .78, "Two readable major forms, moderately sparse."),
    ("t11", "test", 412, "veiled", None, [1, 1, 1], .25, "Extreme washout leaves the style indeterminate; review required."),
    ("t12", "test", 423, "foreign", [0, 0, 0], [0, 0, 0], .94, "Unrelated vivid outlined all-over fragments."),
    ("d01", "demo", 501, "outline", None, [3, 0, 3], .94, "Demonstrate a palette match with the wrong surface treatment."),
    ("d02", "demo", 512, "veiled", None, [1, 1, 1], .25, "Demonstrate an explicit uncertain review."),
]  # fmt: skip


def draw_illustration(seed, variant):
    """480x360 RGB procedural art; random() alone supplies reproducible seeded variation."""
    rng = random.Random(seed)
    image = Image.new("RGB", (480, 360), CREAM)
    draw = ImageDraw.Draw(image)
    colors = VIVID if variant in ("vivid", "foreign") else MUTED
    if variant == "blank":
        return image
    count = {"sparse": 1, "pair": 2, "crowded": 12, "foreign": 46}.get(variant, 4)
    for i in range(count):
        if variant == "sparse":
            x, y = 200 + int(rng.random() * 40), 140 + int(rng.random() * 40)
            w, h = 30, 28
        elif variant in ("crowded", "foreign"):
            columns = 4 if variant == "crowded" else 8
            rows = 3 if variant == "crowded" else 6
            x = 15 + (i % columns) * (450 // columns) + int(rng.random() * 13)
            y = 12 + (i // columns) * (330 // rows) + int(rng.random() * 8)
            w, h = (90, 95) if variant == "crowded" else (45, 42)
        elif variant == "corner":
            x, y = 8 + i % 2 * 90, 8 + i // 2 * 78
            w, h = 105, 92
        else:
            anchors = [(70, 48), (256, 66), (94, 199), (277, 212)]
            x, y = anchors[i]
            x += int(rng.random() * 25) - 12
            y += int(rng.random() * 17) - 8
            w, h = 84 + int(rng.random() * 45), 72 + int(rng.random() * 34)
            if variant == "pair":
                x, y = (90 + 190 * i, 100 + 60 * i)
                w, h = 118, 122
        color = colors[i % len(colors)]
        outline = (39, 40, 45) if variant in ("outline", "foreign") else None
        width = 9 if variant == "outline" else 5
        if variant == "subtle" and i == 1:
            outline, width = (100, 112, 94), 2
        shape = int(rng.random() * 3)
        if shape == 0:
            draw.ellipse((x, y, x + w, y + h), fill=color, outline=outline, width=width)
        elif shape == 1:
            draw.rectangle((x, y, x + w, y + h), fill=color, outline=outline, width=width)
        else:
            points = [(x, y + h), (x + w // 2, y), (x + w, y + h)]
            draw.polygon(points, fill=color)
            if outline:
                draw.line([*points, points[0]], fill=outline, width=width, joint="curve")
    if variant == "accent":
        draw.ellipse((213, 152, 243, 182), fill=VIVID[0])
    if variant == "texture":
        for _ in range(2400):
            x, y = int(rng.random() * 480), int(rng.random() * 360)
            old = image.getpixel((x, y))
            if old != CREAM:
                toned = tuple(max(0, c - 28) for c in old)
                draw.ellipse((x, y, x + 2, y + 2), fill=toned)
    if variant == "veiled":
        image = Image.blend(
            image.filter(ImageFilter.GaussianBlur(30)), Image.new("RGB", image.size, CREAM), 0.98
        )
    return image


def fields_for(index):
    return {"image": f"assets/illustration-{index + 1:03d}.png", "moodboard": MOODBOARD}


def write_assets():
    (HERE / "assets").mkdir(exist_ok=True)
    for i, path in enumerate(MOODBOARD):
        draw_illustration(41 + 7 * i, "quiet").save(HERE / path)
    for i, row in enumerate(ROWS):
        draw_illustration(row[2], row[3]).save(HERE / fields_for(i)["image"])


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for i, row in enumerate(rows):
        ident, split, _, _, gold, _, _, rationale = row
        fields = fields_for(i)
        state, questions, assets = helpers.build_request(fields, HERE)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if split != "demo":
            labels.append({"id": ident, "label": {"levels": gold, "rationale": rationale}})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for i, row in enumerate(rows):
        state, questions, assets = helpers.build_request(fields_for(i), HERE)
        peaks, concentration = row[5], row[6]
        answers = {}
        for dimension, peak in zip(helpers.DIMENSIONS, peaks, strict=True):
            probabilities = [(1 - concentration) / 3] * 4
            probabilities[peak] = concentration
            answers[dimension] = ScoreAnswer.from_probabilities(
                probabilities, questions[dimension].criteria, Provenance.synthetic()
            )
        key = replay_key(state, questions, assets=assets)
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def _is_recorded(path):
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return not isinstance(data, dict) or any(
        not isinstance(value, dict) or value.get("model") != "synthetic" for value in data.values()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    write_assets()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, values in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text("".join(json.dumps(row) + "\n" for row in values), "utf-8")
    target = folder / "responses.json"
    if _is_recorded(target) and not args.force:
        raise SystemExit("refusing to overwrite recorded responses; pass --force to replace them")
    responses = build_responses(ROWS)
    target.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    print(
        f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses; 29 images"
    )


if __name__ == "__main__":
    main()
