"""Author synthetic porch drawings, readable labels and deliberately imperfect responses.

Drawing specifications live only here. Inference sees image bytes, timestamps and the target
sentence. The generator has no live path and preserves recorded responses unless --force.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, visible frames, special scene, gold, synthetic winner, top probability.
# P = blue-taped parcel; E = empty mat; C = brown crate; O = parcel hidden by screen.
# Return and transient sequences have two changes and cannot be one arrival/departure.
ROWS = [
    ("v01", "validation", "EPP", "plain", "arrival", "arrival", .94),
    ("v02", "validation", "PPE", "plain", "departure", "departure", .93),
    ("v03", "validation", "PPP", "move", "unchanged", "unchanged", .91),
    ("v04", "validation", "EEE", "plant", "unchanged", "unchanged", .90),
    ("v05", "validation", "ECC", "plain", "unchanged", "unchanged", .87),
    ("v06", "validation", "PEP", "plain", "uncertain", "uncertain", .95),
    ("v07", "validation", "POO", "plain", "uncertain", "uncertain", .94),
    ("v08", "validation", "PPE", "shift", "uncertain", "departure", .98),
    ("v09", "validation", "EPP", "gap", "uncertain", "arrival", .98),
    ("v10", "validation", "PPE", "dark", "uncertain", "departure", .98),
    ("v11", "validation", "EEP", "small", "arrival", "arrival", .72),
    ("v12", "validation", "PEE", "plant", "departure", "unchanged", .60),
    ("t01", "test", "EEP", "plain", "arrival", "arrival", .92),
    ("t02", "test", "PEE", "plain", "departure", "departure", .91),
    ("t03", "test", "PPP", "plant", "unchanged", "unchanged", .90),
    ("t04", "test", "EEE", "blue", "unchanged", "unchanged", .89),
    ("t05", "test", "EPE", "plain", "uncertain", "uncertain", .94),
    ("t06", "test", "PEP", "move", "uncertain", "uncertain", .92),
    ("t07", "test", "POO", "plant", "uncertain", "uncertain", .96),
    ("t08", "test", "PPE", "shift", "uncertain", "departure", .98),
    ("t09", "test", "EEP", "gap", "uncertain", "arrival", .98),
    ("t10", "test", "PEE", "dark", "uncertain", "departure", .98),
    # Accepted confident error: a brown crate leaves, but the specified parcel is absent.
    ("t11", "test", "CCE", "plain", "unchanged", "departure", .94),
    ("t12", "test", "EPP", "small", "arrival", "arrival", .55),
    ("d01", "demo", "EPP", "plant", None, "arrival", .93),
    ("d02", "demo", "PEP", "plain", None, "uncertain", .95),
]  # fmt: skip


def draw_frame(kind, special, scene, index):
    """Draw a 480x360 synthetic scene; no text reveals labels or split membership."""
    image = Image.new("RGB", (480, 360), (218, 224, 224))
    d = ImageDraw.Draw(image)
    # Stable wall details make camera displacement measurable from actual pixels.
    d.rectangle((45 + scene % 7, 16, 86 + scene % 7, 86), fill=(55, 78, 88))
    d.rectangle((345, 10, 416, 96), fill=(120, 135, 146))
    for y in (24, 48, 72, 96):
        d.line((0, y, 480, y), fill=(175, 185, 187), width=2)
    d.rectangle((0, 145, 480, 360), fill=(170, 179, 184))
    d.polygon([(90, 172), (387, 172), (416, 330), (65, 330)], fill=(66, 76, 85))
    for y in range(185, 325, 15):
        d.line((95, y, 382, y), fill=(85, 94, 101), width=2)
    if special == "plant":
        x = 35 + index * 6
        d.rectangle((x, 231, x + 38, 278), fill=(113, 122, 129))
        d.ellipse((x - 10, 179, x + 48, 240), fill=(47, 119, 79))
    if special == "blue":
        x = 108 + index * 70
        d.ellipse((x, 220, x + 55, 275), fill=(40, 105, 212))
    if kind in "PCO":
        x = 180 + (scene % 5) * 9
        if special == "move":
            x += index * 18
        size = 42 if special == "small" else 88
        y = 232 - size // 3
        fill = (193, 143, 85) if kind != "C" else (168, 112, 57)
        d.rectangle((x, y, x + size, y + size * 0.72), fill=fill, outline=(72, 62, 51), width=3)
        d.polygon(
            [(x, y), (x + 14, y - 16), (x + size + 14, y - 16), (x + size, y)], fill=(218, 171, 109)
        )
        d.polygon(
            [
                (x + size, y),
                (x + size + 14, y - 16),
                (x + size + 14, y + size * 0.72 - 16),
                (x + size, y + size * 0.72),
            ],
            fill=(143, 98, 54),
        )
        if kind != "C":
            d.rectangle((x + size * 0.43, y, x + size * 0.57, y + size * 0.72), fill=(44, 106, 209))
            d.polygon(
                [
                    (x + size * 0.43, y),
                    (x + size * 0.43 + 14, y - 16),
                    (x + size * 0.57 + 14, y - 16),
                    (x + size * 0.57, y),
                ],
                fill=(65, 124, 219),
            )
        else:
            for dx in (15, 38, 61):
                d.line((x + dx, y + 4, x + dx, y + size * 0.67), fill=(95, 70, 44), width=3)
        if kind == "O":
            d.rectangle((125, 158, 350, 307), fill=(110, 123, 139), outline=(49, 58, 72), width=4)
            d.line((145, 166, 145, 300), fill=(155, 166, 179), width=5)
    if special == "shift" and index > 0:
        shifted = Image.new("RGB", image.size, (218, 224, 224))
        shifted.paste(image, (38, 0))
        image = shifted
    if special == "dark":
        image = ImageEnhance.Brightness(image).enhance(0.10)
    return image


def fields_for(row):
    ident, _split, kinds, special, _gold, _winner, _p = row
    times = (0.0, 1.0, 8.0) if special == "gap" else (0.0, 1.0, 2.0)
    return {
        "frames": [
            {"timestamp_seconds": time, "path": f"assets/{ident}-{index}.png"}
            for index, time in enumerate(times[: len(kinds)])
        ]
    }


def build_assets(rows):
    (HERE / "assets").mkdir(exist_ok=True)
    for scene, row in enumerate(rows):
        for index, kind in enumerate(row[2]):
            image = draw_frame(kind, row[3], scene, index)
            image.save(HERE / "assets" / f"{row[0]}-{index}.png", optimize=False)


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for row in rows:
        fields = fields_for(row)
        prepared = helpers.prepare(fields, HERE)
        keys = (
            []
            if prepared.issues
            else [replay_key(prepared.state, helpers.build_questions(), assets=prepared.assets)]
        )
        inputs.append({"id": row[0], "split": row[1], "fields": fields, "replay_keys": keys})
        if row[4] is not None:
            labels.append({"id": row[0], "label": row[4]})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        prepared = helpers.prepare(fields_for(row), HERE)
        if prepared.issues:
            continue
        winner, p = row[-2:]
        probabilities = {
            option: p if option == winner else (1 - p) / 3 for option in helpers.OPTIONS
        }
        answer = ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())
        key = replay_key(prepared.state, helpers.build_questions(), assets=prepared.assets)
        responses[key] = DecisionResult({"event": answer}, "synthetic").to_dict()
    return responses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace recorded answers")
    args = parser.parse_args()
    build_assets(ROWS)
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    path = folder / "responses.json"
    if path.exists() and not args.force:
        existing = json.loads(path.read_text("utf-8"))
        if any(not isinstance(r, dict) or r.get("model") != "synthetic" for r in existing.values()):
            raise SystemExit("refusing to overwrite recorded responses; pass --force to replace")
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(inputs)} clips, {len(labels)} labels, 78 images, {len(responses)} responses")


if __name__ == "__main__":
    main()
