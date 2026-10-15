"""Author synthetic forms, gold ink envelopes, and deliberately imperfect replay answers.

No actual identity, signature or approval is represented. The handwritten marks are
mathematical scribbles and every printed name is fictional. Gold masks are used only
by this authoring script; runtime inference sees the final image and requested mark.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import BoxAnswer, DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.fixtures import Example

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
SIZE = (600, 760)

# id, split, target, drawing case, position, mark rotation, p_present, p_unique,
# Box confidence, synthetic localization behavior. None is deliberately missing confidence.
ROWS = [
    ("v01", "validation", "signature", "normal", (90, 520), -4, .98, .97, .92, "tight"),
    ("v02", "validation", "stamp", "normal", (340, 505), 7, .98, .98, .91, "tight"),
    ("v03", "validation", "signature", "normal", (280, 265), 8, .92, .94, .90, "loose"),
    ("v04", "validation", "stamp", "normal", (70, 310), -11, .93, .93, .89, "tight"),
    ("v05", "validation", "signature", "blank", (95, 535), 0, .03, .04, .98, "false"),
    ("v06", "validation", "signature", "printed", (310, 520), 0, .04, .04, .98, "false"),
    ("v07", "validation", "stamp", "seal", (350, 540), 0, .84, .87, .94, "false"),
    ("v08", "validation", "stamp", "duplicate", (80, 475), 5, .98, .10, .96, "tight"),
    ("v09", "validation", "signature", "occluded", (80, 540), -7, .65, .69, .90, "tight"),
    ("v10", "validation", "signature", "black", (320, 420), 5, .98, .97, .76, "wrong"),
    ("v11", "validation", "stamp", "normal", (330, 270), 13, .97, .96, None, "tight"),
    ("v12", "validation", "signature", "normal", (95, 430), 12, .99, .97, .88, "tight"),
    ("t01", "test", "signature", "normal", (100, 510), 6, .97, .96, .92, "tight"),
    ("t02", "test", "stamp", "normal", (350, 495), -8, .97, .98, .93, "loose"),
    ("t03", "test", "signature", "normal", (300, 260), -12, .94, .93, .91, "tight"),
    ("t04", "test", "stamp", "normal", (80, 330), 10, .98, .98, .97, "wrong"),
    ("t05", "test", "signature", "blank", (90, 530), 0, .03, .04, .97, "false"),
    ("t06", "test", "signature", "printed", (310, 530), 0, .03, .03, .96, "false"),
    ("t07", "test", "stamp", "seal", (340, 535), 0, .96, .96, .96, "false"),
    ("t08", "test", "stamp", "duplicate", (85, 480), -6, .98, .12, .97, "tight"),
    ("t09", "test", "signature", "occluded", (310, 545), 9, .67, .72, .90, "tight"),
    ("t10", "test", "signature", "partial", (360, 430), -5, .92, .92, .86, "tight"),
    ("t11", "test", "stamp", "normal", (340, 290), -14, .97, .97, None, "tight"),
    ("t12", "test", "signature", "black", (85, 425), -3, .97, .97, .79, "tight"),
    ("d01", "demo", "signature", "normal", (100, 520), -9, .99, .98, .94, "tight"),
    ("d02", "demo", "stamp", "duplicate", (90, 450), 9, .98, .11, .96, "tight"),
]  # fmt: skip


def _font(size):
    return ImageFont.load_default(size=size)


def _mark(kind, angle, black=False, seal=False):
    tile = Image.new("RGBA", (210, 110))
    draw = ImageDraw.Draw(tile)
    color = (30, 30, 30, 255) if black else (35, 65, 145, 255)
    if kind == "signature":
        points = []
        for x in range(15, 194):
            y = 53 + int(19 * math.sin(x / 10) + 12 * math.sin(x / 5.1))
            points.append((x, y))
        draw.line(points, fill=color, width=3)
        draw.line([(28, 84), (180, 68)], fill=color, width=2)
    else:
        color = (165, 55, 65, 255)
        if seal:
            draw.ellipse((24, 5, 187, 104), outline=color, width=4)
            draw.ellipse((34, 14, 178, 96), outline=color, width=2)
            draw.text((61, 36), "ARCHIVE", font=_font(19), fill=color)
            draw.text((62, 61), "EMBLEM", font=_font(16), fill=color)
        else:
            draw.rounded_rectangle((8, 16, 201, 96), radius=5, outline=color, width=4)
            draw.rectangle((15, 23, 194, 89), outline=color, width=1)
            draw.text((27, 42), "APPROVED", font=_font(27), fill=color)
    return tile.rotate(angle, Image.Resampling.BICUBIC, expand=True)


def _normalized(bounds):
    left, top, right, bottom = bounds
    return {
        "left": left / SIZE[0],
        "top": top / SIZE[1],
        "right": right / SIZE[0],
        "bottom": bottom / SIZE[1],
    }


def draw_document(row):
    ident, _, kind, case, position, angle, *_ = row
    image = Image.new("RGB", SIZE, (248, 247, 242))
    draw = ImageDraw.Draw(image)
    draw.rectangle((22, 20, 577, 738), outline=(178, 178, 173), width=2)
    draw.text((46, 44), "PAPERFIELD DEMO WORKSHOP", font=_font(24), fill=(35, 35, 35))
    draw.text((46, 82), "Fictional supply receipt", font=_font(20), fill=(60, 60, 60))
    form_number = 100000 + int(hashlib.sha256(ident.encode()).hexdigest()[:6], 16) % 900000
    draw.text((46, 119), f"Form {form_number} / SAMPLE ONLY", font=_font(15), fill=(85, 85, 85))
    draw.line((45, 152, 555, 152), fill=(105, 105, 105), width=2)
    draw.text((46, 176), "Prepared for: Neri Vale (fictional)", font=_font(17), fill=(50, 50, 50))
    draw.text((46, 207), "Contents: blank paper, sample folders", font=_font(17), fill=(50, 50, 50))
    draw.text((46, 238), "Archive routing: training collection", font=_font(17), fill=(50, 50, 50))
    for y in (362, 394):
        draw.line((46, y, 552, y), fill=(200, 200, 195), width=1)
    draw.text((46, 665), "Prepared name: Tavi Fen (fictional)", font=_font(16), fill=(65, 65, 65))
    draw.text(
        (46, 696),
        "Synthetic drawing / no authority or legal effect",
        font=_font(14),
        fill=(100, 100, 100),
    )
    x, y = position
    if kind == "signature":
        draw.line(
            (x, min(y + 110, 645), min(x + 212, 560), min(y + 110, 645)), fill=(85, 85, 85), width=1
        )
        draw.text((x, min(y + 117, 650)), "Signature", font=_font(14), fill=(80, 80, 80))
    masks = []
    candidate_bounds = []
    if case == "printed":
        draw.text((x + 6, y + 48), "Neri Vale", font=_font(25), fill=(40, 40, 40))
    elif case != "blank":
        locations = [position]
        if case == "duplicate":
            locations.append((335, 510))
        for px, py in locations:
            mark = _mark(kind, angle, black=case == "black", seal=case == "seal")
            image.paste(mark, (px, py), mark)
            mask = Image.new("L", SIZE)
            mask.paste(mark.getchannel("A"), (px, py))
            masks.append(mask)
        if case in ("partial", "occluded"):
            cover = (470, 400, 599, 650) if case == "partial" else (x + 70, y, x + 160, y + 130)
            ImageDraw.Draw(image).rectangle(cover, fill=(230, 229, 224))
            for mask in masks:
                ImageDraw.Draw(mask).rectangle(cover, fill=0)
        for mask in masks:
            candidate_bounds.append(_normalized(mask.getbbox()))
    present = case not in ("blank", "printed", "seal")
    label = {
        "present": present,
        "unique": present and case != "duplicate",
        "boxes": candidate_bounds if present else [],
        "case": case,
        "annotation": "tight envelope of visible target ink; duplicate targets are ambiguous",
    }
    image_folder = HERE / "assets"
    image_folder.mkdir(exist_ok=True)
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    path = image_folder / (digest + ".png")
    image.save(path, optimize=False)
    fields = {"image": "assets/" + path.name, "kind": kind}
    candidate = (
        candidate_bounds[0] if candidate_bounds else _normalized((x, y + 35, x + 190, y + 90))
    )
    return fields, label, candidate


def _cases(rows):
    cases = []
    for row in rows:
        ident, split, _, _, _, _, present, unique, confidence, behavior = row
        fields, label, candidate = draw_document(row)
        provenance = Provenance.synthetic()
        judgments = {
            "present": NoulAnswer(present, provenance),
            "unique": NoulAnswer(unique, provenance),
        }
        box = candidate
        if behavior == "loose":
            box = {
                "left": max(0, box["left"] - 0.02),
                "right": min(1, box["right"] + 0.02),
                "top": max(0, box["top"] - 0.012),
                "bottom": min(1, box["bottom"] + 0.012),
            }
        elif behavior == "wrong":
            box = _normalized((65, 168, 400, 203))
        location = BoxAnswer(box, confidence, provenance)
        example = Example(ident, split, (), fields=fields)
        cases.append((example, label, helpers.Observation(judgments, location)))
    return cases


def _requests(rows):
    cases = _cases(rows)
    validation = [example for example, _, _ in cases if example.split == "validation"]
    labels = {example.id: label for example, label, _ in cases}
    observations = {example.id: obs for example, _, obs in cases}
    policy, _ = helpers.select_policy(
        validation, observations, labels, HERE, objective=helpers.OBJECTIVE
    )
    for example, label, obs in cases:
        state, assets = helpers.request_data(example.fields, HERE)
        first = replay_key(state, helpers.build_questions(), assets=assets)
        requests = [(first, DecisionResult(obs.judgments, "synthetic"))]
        threshold = {
            "validation": min(helpers.PRESENCE_CANDIDATES),
            "test": policy.presence,
            "demo": helpers.DEMO_PRESENCE,
        }[example.split]
        if helpers.first_gate(obs.judgments, threshold) is None:
            key = replay_key(state, helpers.box_questions(), assets=assets)
            requests.append((key, DecisionResult({"mark_box": obs.location}, "synthetic")))
        yield example, label, requests


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for example, label, requests in _requests(rows):
        inputs.append(
            {
                "id": example.id,
                "split": example.split,
                "fields": dict(example.fields),
                "replay_keys": [key for key, _ in requests],
            }
        )
        if example.split != "demo":
            labels.append({"id": example.id, "label": label})
    return inputs, labels


def build_responses(rows):
    return {key: result.to_dict() for _, _, requests in _requests(rows) for key, result in requests}


def _is_recorded(path):
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    return not isinstance(data, dict) or any(
        not isinstance(value, dict) or value.get("model") != "synthetic" for value in data.values()
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
    path = folder / "responses.json"
    if _is_recorded(path) and not args.force:
        raise SystemExit(
            "recorded responses preserved; inputs/labels regenerated; use --force to replace"
        )
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(inputs)} documents, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
