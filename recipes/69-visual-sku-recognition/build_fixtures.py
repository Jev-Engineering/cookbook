"""Author small controlled product drawings and deliberately imperfect synthetic answers.

No image is a real product photograph. The separate reference and query sets use the same
fictional design vocabulary; recognizing them says nothing about real retail imagery.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key
from jev_cookbook.live import _dump

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
OPTIONS = helpers.OPTIONS

# id, split, drawn variant, lighting, obstruction, gold, synthetic top option, top probability.
# Query ids are bookkeeping only. Neither these parameters nor labels enter the request.
ROWS = [
    ("v01", "validation", 1, "normal", "none", "sku_101", "sku_101", 0.94),
    ("v02", "validation", 2, "normal", "none", "sku_102", "sku_102", 0.91),
    ("v03", "validation", 3, "normal", "none", "sku_103", "sku_103", 0.93),
    ("v04", "validation", 4, "normal", "none", "sku_104", "sku_104", 0.92),
    ("v05", "validation", 1, "dim", "none", "sku_101", "sku_101", 0.81),
    ("v06", "validation", 2, "warm", "none", "sku_102", "sku_101", 0.61),
    ("v07", "validation", 3, "cool", "none", "sku_103", "sku_103", 0.84),
    ("v08", "validation", 4, "bright", "edge", "sku_104", "sku_104", 0.83),
    ("v09", "validation", 5, "normal", "none", "no_match", "no_match", 0.90),
    ("v10", "validation", 6, "normal", "none", "no_match", "sku_101", 0.58),
    ("v11", "validation", 2, "normal", "label", "unknown", "unknown", 0.89),
    ("v12", "validation", 3, "dim", "heavy", "unknown", "unknown", 0.91),
    ("v13", "validation", 1, "cool", "edge", "sku_101", "sku_102", 0.56),
    ("v14", "validation", 2, "bright", "none", "sku_102", "sku_102", 0.87),
    ("v15", "validation", 5, "dim", "none", "no_match", "no_match", 0.77),
    ("v16", "validation", 4, "warm", "none", "sku_104", "sku_104", 0.88),
    ("t01", "test", 1, "bright", "none", "sku_101", "sku_101", 0.92),
    ("t02", "test", 2, "cool", "none", "sku_102", "sku_102", 0.89),
    ("t03", "test", 3, "warm", "edge", "sku_103", "sku_103", 0.90),
    ("t04", "test", 4, "dim", "none", "sku_104", "sku_104", 0.85),
    ("t05", "test", 1, "warm", "none", "sku_101", "sku_101", 0.79),
    ("t06", "test", 2, "dim", "none", "sku_102", "sku_101", 0.93),
    ("t07", "test", 3, "bright", "none", "sku_103", "sku_103", 0.88),
    ("t08", "test", 4, "cool", "edge", "sku_104", "sku_104", 0.80),
    ("t09", "test", 5, "warm", "none", "no_match", "no_match", 0.87),
    ("t10", "test", 6, "bright", "none", "no_match", "sku_102", 0.63),
    ("t11", "test", 1, "dim", "label", "unknown", "unknown", 0.92),
    ("t12", "test", 4, "normal", "heavy", "unknown", "sku_104", 0.57),
    ("t13", "test", 2, "normal", "edge", "sku_102", "sku_102", 0.78),
    ("t14", "test", 1, "normal", "none", "sku_101", "sku_101", 0.91),
    ("t15", "test", 6, "cool", "none", "no_match", "no_match", 0.75),
    ("t16", "test", 3, "dim", "none", "sku_103", "sku_103", 0.82),
    ("d01", "demo", 2, "warm", "none", None, "sku_102", 0.86),
    ("d02", "demo", 1, "normal", "label", None, "unknown", 0.90),
]


def draw_product(variant, lighting="normal", obstruction="none", seed=0):
    """Draw a 384x320 RGB asset with deterministic position/size/background variation."""
    background = 239 - (seed % 7)
    image = Image.new("RGB", (384, 320), (background,) * 3)
    draw = ImageDraw.Draw(image)
    dx = (seed * 7) % 23 - 11 if seed else 0
    dy = (seed * 11) % 13 - 6 if seed else 0
    scale = 0.93 + (seed % 5) * 0.025 if seed else 1.0

    def box(coords):
        return tuple(
            round((v - (192 if i % 2 == 0 else 160)) * scale)
            + (192 + dx if i % 2 == 0 else 160 + dy)
            for i, v in enumerate(coords)
        )

    coral = (206, 83, 73)
    teal = (43, 141, 151)
    ink = (38, 38, 38)
    draw.ellipse(box((116, 267, 275, 285)), fill=(214,) * 3)
    if variant in (1, 2, 6):
        draw.rounded_rectangle(
            box((137, 83, 247, 271)), radius=20, fill=coral, outline=ink, width=3
        )
        draw.rectangle(box((158, 55, 226, 93)), fill=coral, outline=ink, width=3)
        draw.rounded_rectangle(box((154, 44, 230, 62)), radius=4, fill=ink)
    elif variant == 3:
        draw.rounded_rectangle(box((119, 99, 265, 270)), radius=15, fill=teal, outline=ink, width=3)
        draw.ellipse(box((119, 88, 265, 114)), fill=(75, 160, 166), outline=ink, width=3)
    elif variant == 4:
        draw.rectangle(box((134, 92, 250, 270)), fill=teal, outline=ink, width=3)
        draw.polygon(box((134, 92, 166, 52, 218, 52, 250, 92)), fill=teal, outline=ink)
        draw.line(box((166, 52, 218, 52)), fill=ink, width=5)
    else:
        draw.polygon(box((135, 64, 249, 64, 268, 268, 116, 268)), fill=(142, 79, 174), outline=ink)
    draw.rounded_rectangle(box((145, 134, 239, 224)), radius=4, fill=(250, 245, 228), outline=ink)
    font = ImageFont.load_default(size=16)
    x, y = box((165, 140))
    draw.text((x, y), "TERN", fill=ink, font=font)
    if variant in (1, 3):
        draw.ellipse(box((179, 173, 205, 199)), fill=ink)
    elif variant == 2:
        draw.rectangle(box((174, 172, 184, 202)), fill=ink)
        draw.rectangle(box((201, 172, 211, 202)), fill=ink)
    elif variant == 4:
        draw.polygon(box((192, 171, 211, 202, 173, 202)), fill=ink)
    elif variant == 6:
        draw.line(box((176, 173, 209, 202)), fill=ink, width=6)
        draw.line(box((209, 173, 176, 202)), fill=ink, width=6)
    else:
        draw.rectangle(box((178, 176, 208, 202)), fill=ink)
    if obstruction == "label":
        draw.rectangle(box((136, 132, 248, 227)), fill=(141, 141, 141))
    elif obstruction == "heavy":
        draw.rectangle(box((103, 85, 277, 283)), fill=(141, 141, 141))
    elif obstruction == "edge":
        draw.rectangle(box((229, 231, 272, 277)), fill=(141, 141, 141))
    factors = {"normal": 1.0, "dim": 0.63, "bright": 1.13, "warm": 0.94, "cool": 0.96}
    image = ImageEnhance.Brightness(image).enhance(factors[lighting])
    if lighting in ("warm", "cool"):
        channels = image.split()
        shifts = (14, 0, -10) if lighting == "warm" else (-12, 0, 13)
        image = Image.merge(
            "RGB",
            tuple(
                c.point(lambda p, d=d: max(0, min(255, p + d)))
                for c, d in zip(channels, shifts, strict=True)
            ),
        )
    return image


def fields_for(index):
    return {"image": f"assets/queries/q-{index + 1:03d}.png"}


def build_assets(rows):
    """References and queries have separate files; images contain no gold metadata."""
    for variant, relative in enumerate(helpers.CATALOG.values(), start=1):
        path = HERE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        draw_product(variant).save(path)
    for index, row in enumerate(rows):
        path = HERE / fields_for(index)["image"]
        path.parent.mkdir(parents=True, exist_ok=True)
        draw_product(row[2], row[3], row[4], seed=index + 1).save(path)


def build_inputs_and_labels(rows):
    """Generate public image paths and labels separately from response generation."""
    build_assets(rows)
    inputs, labels = [], []
    for index, row in enumerate(rows):
        ident, split, *_rest = row
        fields = fields_for(index)
        state, questions, assets = helpers.build_request(fields)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if row[5] is not None:
            labels.append({"id": ident, "label": row[5]})
    return inputs, labels


def answers_for(top, probability, provenance):
    probabilities = dict.fromkeys(OPTIONS, (1 - probability) / (len(OPTIONS) - 1))
    probabilities[top] = probability
    return {"sku": ChoiceAnswer.from_probabilities(probabilities, provenance)}


def build_responses(rows):
    """Hand-authored synthetic distributions, including confidently wrong responses."""
    responses = {}
    for index, row in enumerate(rows):
        state, questions, assets = helpers.build_request(fields_for(index))
        key = replay_key(state, questions, assets=assets)
        responses[key] = DecisionResult(
            answers_for(row[6], row[7], Provenance.synthetic()), "synthetic"
        ).to_dict()
    return responses


def _is_recorded(path):
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return not isinstance(data, dict) or any(
        not isinstance(value, dict)
        or value.get("model") != "synthetic"
        or any(
            answer.get("provenance", {}).get("source") != "synthetic"
            for answer in value.get("answers", {}).values()
        )
        for value in data.values()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="replace recorded responses explicitly"
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    target = folder / "responses.json"
    if _is_recorded(target) and not args.force:
        raise SystemExit("refusing to overwrite recorded responses; use --force explicitly")
    target.write_text(_dump(build_responses(ROWS)), "utf-8")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(inputs)} synthetic responses")


if __name__ == "__main__":
    main()
