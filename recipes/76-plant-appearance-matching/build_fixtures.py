"""Author illustrative foliage and synthetic answers; these are not real plant photographs.

Drawing parameters and handwritten labels live here only. Inference and the deterministic
baseline see pixels, not these parameters. Every query has an independent scene seed.
"""

import argparse
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, drawing, seed, rotation, palette, view, gold, invented winner, probability
ROWS = [
    ("v01", "validation", "broadleaf", 101, 0, "green", "full", "broadleaf", "broadleaf", .92),
    ("v02", "validation", "needlelike", 102, 0, "green", "full", "needlelike", "needlelike", .91),
    ("v03", "validation", "rosette", 103, 12, "green", "full", "rosette", "rosette", .90),
    ("v04", "validation", "fernlike", 104, -8, "green", "full", "fernlike", "fernlike", .88),
    ("v05", "validation", "broadleaf", 105, 32, "green", "full", "broadleaf", "broadleaf", .84),
    ("v06", "validation", "needlelike", 106, -18, "blue", "full", "needlelike", "needlelike", .86),
    ("v07", "validation", "rosette", 107, 0, "green", "occluded", "rosette", "rosette", .78),
    ("v08", "validation", "fernlike", 108, 18, "gold", "full", "fernlike", "fernlike", .76),
    ("v09", "validation", "single", 109, 15, "green", "full", "unknown", "broadleaf", .66),
    ("v10", "validation", "mixed", 110, 0, "green", "full", "unknown", "unknown", .90),
    ("v11", "validation", "grass", 111, 0, "green", "full", "unknown", "unknown", .92),
    ("v12", "validation", "empty", 112, 0, "green", "full", "unknown", "rosette", .60),
    ("t01", "test", "broadleaf", 201, -17, "green", "full", "broadleaf", "broadleaf", .90),
    ("t02", "test", "needlelike", 202, 23, "green", "full", "needlelike", "needlelike", .89),
    ("t03", "test", "rosette", 203, -25, "blue", "full", "rosette", "rosette", .88),
    ("t04", "test", "fernlike", 204, 12, "green", "full", "fernlike", "fernlike", .91),
    ("t05", "test", "broadleaf", 205, 29, "gold", "full", "broadleaf", "broadleaf", .82),
    ("t06", "test", "broadleaf", 206, 0, "green", "occluded", "broadleaf", "broadleaf", .70),
    ("t07", "test", "single", 207, -32, "blue", "full", "unknown", "broadleaf", .64),
    ("t08", "test", "fernlike", 208, -28, "blue", "full", "fernlike", "fernlike", .82),
    ("t09", "test", "mixed", 209, 0, "green", "full", "unknown", "unknown", .96),
    ("t10", "test", "fan", 210, -10, "green", "full", "unknown", "needlelike", .94),
    ("t11", "test", "grass", 211, 9, "gold", "full", "unknown", "unknown", .88),
    ("t12", "test", "empty", 212, 0, "green", "full", "unknown", "unknown", .93),
    ("d01", "demo", "fernlike", 301, -10, "green", "full", None, "fernlike", .89),
    ("d02", "demo", "mixed", 302, 0, "blue", "full", None, "unknown", .94),
]  # fmt: skip

PALETTES = {"green": (54, 125, 64), "blue": (55, 107, 147), "gold": (155, 118, 38)}


def leaf(draw, start, end, width, color):
    """A pointed blade with a visible midrib, drawn independently for each scene."""
    x, y = start
    dx, dy = end[0] - x, end[1] - y
    length = math.hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    points = [start]
    for sign in (1, -1):
        values = range(1, 13) if sign == 1 else range(11, 0, -1)
        for step in values:
            t = step / 12
            side = sign * width * math.sin(math.pi * t)
            points.append((x + t * dx + side * nx, y + t * dy + side * ny))
    draw.polygon(points, fill=color)
    draw.line([start, end], fill=tuple(max(0, c - 22) for c in color), width=2)


def foliage(group, rng, color):
    """Return a transparent botanical-style illustration; shapes are not species labels."""
    layer = Image.new("RGBA", (384, 320))
    draw = ImageDraw.Draw(layer)
    stem = (75, 100, 58)
    if group == "broadleaf":
        draw.line([(194, 281), (184, 69)], fill=stem, width=5)
        for i in range(6):
            y = 242 - i * 29 + rng.randrange(-6, 7)
            side = -1 if i % 2 else 1
            start = (190, y)
            end = (190 + side * rng.randrange(65, 91), y - rng.randrange(28, 51))
            leaf(draw, start, end, rng.randrange(17, 25), color)
        leaf(draw, (185, 102), (178, 39), 19, color)
    elif group == "needlelike":
        draw.line([(193, 285), (187, 45)], fill=stem, width=5)
        for side in (-1, 1):
            for y in (118, 173, 232):
                end = (190 + side * rng.randrange(67, 92), y - 56)
                draw.line([(190, y), end], fill=stem, width=3)
                for j in range(1, 8):
                    t = j / 8
                    x0, y0 = 190 + (end[0] - 190) * t, y - 56 * t
                    for bend in (-1, 1):
                        leaf(draw, (x0, y0), (x0 + side * 21, y0 + bend * 19), 2, color)
    elif group == "rosette":
        center = (192 + rng.randrange(-8, 9), 166 + rng.randrange(-6, 7))
        for ring, count in ((0, 11), (1, 8)):
            for i in range(count):
                theta = i * math.tau / count + ring * 0.2 + rng.random() * 0.07
                length = rng.randrange(96, 124) if ring == 0 else rng.randrange(52, 78)
                end = (center[0] + length * math.cos(theta), center[1] + length * math.sin(theta))
                shade = tuple(min(255, c + ring * 15) for c in color)
                leaf(draw, center, end, 14 if ring else 20, shade)
    elif group == "fernlike":
        draw.line([(196, 286), (182, 35)], fill=stem, width=3)
        for i in range(11):
            y = 251 - i * 18
            length = 68 * (1 - i / 14) + rng.randrange(-5, 6)
            for side in (-1, 1):
                start, end = (190, y), (190 + side * length, y - 22)
                draw.line([start, end], fill=stem, width=2)
                for j in range(1, 7):
                    x0, y0 = 190 + side * length * j / 7, y - 22 * j / 7
                    leaf(draw, (x0, y0), (x0 + side * 14, y0 - 13), 4, color)
                    leaf(draw, (x0, y0), (x0 + side * 9, y0 + 8), 3, color)
        leaf(draw, (184, 65), (180, 29), 5, color)
    elif group == "single":
        leaf(draw, (113, 236), (270 + rng.randrange(-8, 8), 92), 52, color)
    elif group in ("grass", "fan"):
        center = (192, 281 if group == "grass" else 232)
        for i in range(15):
            theta = -math.pi + 0.20 + i * (math.pi - 0.4) / 14
            length = rng.randrange(135, 208)
            end = (center[0] + math.cos(theta) * length, center[1] + math.sin(theta) * length)
            leaf(draw, center, end, 3 if group == "grass" else 8, color)
    elif group == "mixed":
        for group_name, offset in (("broadleaf", (-83, 18)), ("rosette", (86, 15))):
            small = foliage(group_name, rng, color).resize((269, 224), Image.Resampling.LANCZOS)
            layer.alpha_composite(small, (57 + offset[0], 48 + offset[1]))
    elif group != "empty":
        raise ValueError(group)
    return layer


def draw_scene(group, seed, angle=0, palette="green", view="full"):
    rng = random.Random(seed)
    image = Image.new("RGB", (384, 320), (241, 241, 237))
    draw = ImageDraw.Draw(image)
    # Neutral bench texture varies scene identity without encoding a category.
    for _ in range(35):
        x, y = rng.randrange(384), rng.randrange(320)
        shade = rng.randrange(215, 238)
        draw.line([(x, y), (x + rng.randrange(2, 9), y)], fill=(shade, shade, shade))
    layer = foliage(group, rng, PALETTES[palette]).rotate(angle, Image.Resampling.BICUBIC)
    image.paste(layer, (0, 0), layer)
    if view == "occluded":
        draw.rectangle((0, 0, 159, 320), fill=(218, 218, 218))
        draw.line([(159, 0), (159, 320)], fill=(179, 179, 179), width=3)
    return image


def fields_for(row):
    return {"image": f"assets/query-{row[0]}.png"}


def build_assets(rows):
    (HERE / "assets").mkdir(exist_ok=True)
    for index, (group, relative) in enumerate(helpers.REFERENCES.items()):
        draw_scene(group, 10 + index).save(HERE / relative)
    for row in rows:
        draw_scene(*row[2:7]).save(HERE / fields_for(row)["image"])


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for row in rows:
        fields = fields_for(row)
        state, questions, assets = helpers.build_request(fields)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": row[0], "split": row[1], "fields": fields, "replay_keys": [key]})
        if row[7] is not None:
            labels.append({"id": row[0], "label": row[7]})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        state, questions, assets = helpers.build_request(fields_for(row))
        probabilities = {option: (1 - row[9]) / 4 for option in helpers.OPTIONS}
        probabilities[row[8]] = row[9]
        answer = ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())
        responses[replay_key(state, questions, assets=assets)] = DecisionResult(
            {"group": answer}, "synthetic"
        ).to_dict()
    return responses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="allow replacing recorded responses")
    args = parser.parse_args()
    build_assets(ROWS)
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text("".join(json.dumps(row) + "\n" for row in rows), "utf-8")
    destination = folder / "responses.json"
    if destination.exists() and not args.force:
        old = json.loads(destination.read_text("utf-8"))
        if not isinstance(old, dict) or any(
            not isinstance(value, dict) or value.get("model") != "synthetic"
            for value in old.values()
        ):
            raise SystemExit("refusing to overwrite recorded responses; use --force explicitly")
    responses = build_responses(ROWS)
    destination.write_text(json.dumps(dict(sorted(responses.items())), indent=2) + "\n", "utf-8")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
