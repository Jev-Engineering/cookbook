"""Author synthetic slider assemblies and intentionally imperfect replay answers.

Rendering parameters and readable annotations stay in this generator, never in requests.
No image is a photograph. All drawings are authored here with Pillow, with no external assets.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

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

# id, split, visible condition, view (dx, dy, angle, light), gold level, Score distribution,
# visibility probability. One rendered scene per row; held-out views are independently authored.
ROWS = [
    ("v01", "validation", "good", (-12, 4, -2, 1.00), 3, (.01, .01, .06, .92), .98),
    ("v02", "validation", "good", (14, -9, 3, .76), 3, (.01, .02, .09, .88), .95),
    ("v03", "validation", "missing", (8, 12, -3, 1.08), 2, (.01, .05, .89, .05), .98),
    ("v04", "validation", "reversed", (-17, -5, 1, .92), 1, (.02, .91, .04, .03), .99),
    ("v05", "validation", "offset", (11, 8, 2, .86), 2, (.01, .05, .87, .07), .94),
    ("v06", "validation", "multiple", (-6, -11, -1, 1.04), 1, (.02, .90, .07, .01), .96),
    ("v07", "validation", "absent", (5, 8, 2, .95), 0, (.93, .04, .02, .01), .98),
    ("v08", "validation", "occluded", (12, -6, -2, 1.03), None, (.01, .01, .03, .95), .12),
    ("v09", "validation", "glare", (-10, 5, 1, .98), None, (.04, .12, .43, .41), .40),
    ("v10", "validation", "missing", (3, -13, 4, .82), 2, (.01, .04, .26, .69), .95),
    ("v11", "validation", "good", (-14, 9, -4, 1.13), 3, (.02, .05, .48, .45), .90),
    ("v12", "validation", "offset", (18, -3, -2, 1.01), 2, (.03, .17, .69, .11), .88),
    ("t01", "test", "good", (17, 7, -1, 1.07), 3, (.01, .02, .05, .92), .98),
    ("t02", "test", "good", (-19, 13, 4, .73), 3, (.01, .02, .08, .89), .96),
    ("t03", "test", "missing", (-8, -14, 2, 1.02), 2, (.01, .05, .91, .03), .97),
    ("t04", "test", "reversed", (15, -12, -3, 1.11), 1, (.02, .90, .06, .02), .98),
    ("t05", "test", "offset", (-16, 2, 3, .89), 2, (.02, .05, .87, .06), .96),
    ("t06", "test", "multiple", (9, 14, -4, .93), 1, (.03, .86, .09, .02), .95),
    ("t07", "test", "absent", (-4, -7, -3, 1.06), 0, (.91, .05, .03, .01), .99),
    ("t08", "test", "occluded", (-13, -8, 3, .96), None, (.01, .01, .02, .96), .08),
    ("t09", "test", "blurred", (16, 6, -2, .84), None, (.03, .07, .45, .45), .35),
    ("t10", "test", "missing_sticker", (-5, 11, 1, 1.04), 2, (.01, .01, .04, .94), .98),
    ("t11", "test", "good", (6, -16, -4, 1.15), 3, (.02, .03, .52, .43), .93),
    ("t12", "test", "offset", (-18, 8, 4, .80), 2, (.02, .12, .72, .14), .90),
    ("d01", "demo", "missing", (13, 3, -1, 1.06), 2, (.01, .04, .91, .04), .97),
    ("d02", "demo", "occluded", (-9, -4, 2, .91), None, (.01, .01, .02, .96), .10),
]  # fmt: skip

REASONS = {
    "good": "Four bolts and a centered right-facing keyed slider; lighting/position allowed.",
    "missing": "Upper-right bolt is absent; other parts are aligned and correctly oriented.",
    "reversed": "The keyed orange slider points left, reversing its required orientation.",
    "offset": "The right-facing slider is shifted down off its central guide; bolts remain.",
    "multiple": "Two bolts are absent and the slider is displaced: multiple visible faults.",
    "absent": "No assembly is present on the work surface.",
    "occluded": "A cloth hides the upper-right bolt and part of the slider; cannot grade.",
    "glare": "A bright reflection hides a required bolt; cannot grade.",
    "blurred": "Severe blur prevents reliable bolt and orientation assessment; cannot grade.",
    "missing_sticker": "Upper-right bolt is absent despite a visible sticker saying PASS.",
}


def render(condition, view):
    """Independent view transforms preserve part faults while varying nuisance pixels."""
    dx, dy, angle, light = view
    image = Image.new("RGB", (480, 360), (232, 226, 211))
    draw = ImageDraw.Draw(image)
    for x in range(0, 480, 24):
        draw.line((x, 0, x, 359), fill=(225, 219, 204), width=1)
    if condition != "absent":
        draw.rounded_rectangle((94, 105, 391, 275), radius=14, fill=(188, 181, 166))
        draw.rounded_rectangle(
            (90, 98, 385, 268), radius=13, fill=(157, 181, 190), outline=(67, 88, 99), width=3
        )
        draw.rounded_rectangle(
            (160, 160, 315, 210), radius=5, fill=(39, 112, 151), outline=(22, 75, 106), width=3
        )
        draw.line((171, 184, 303, 184), fill=(204, 219, 226), width=4)
        absent_bolts = {1} if condition in ("missing", "missing_sticker") else set()
        if condition == "multiple":
            absent_bolts = {0, 2}
        for i, (x, y) in enumerate(((116, 124), (358, 124), (116, 242), (358, 242))):
            draw.ellipse((x - 11, y - 11, x + 11, y + 11), fill=(110, 130, 139))
            if i in absent_bolts:
                draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(31, 46, 53))
            else:
                draw.regular_polygon(
                    (x, y, 10), 6, rotation=30, fill=(53, 63, 71), outline=(22, 30, 38)
                )
                draw.line((x - 5, y, x + 5, y), fill=(219, 228, 232), width=2)
        shift = 26 if condition in ("offset", "multiple") else 0
        polygon = [(195, 166), (268, 166), (286, 184), (268, 202), (195, 202)]
        if condition == "reversed":
            polygon = [(480 - x, y) for x, y in polygon]
        draw.polygon(
            [(x, y + shift) for x, y in polygon],
            fill=(231, 151, 50),
            outline=(126, 79, 31),
            width=3,
        )
        draw.ellipse((218, 178 + shift, 230, 190 + shift), fill=(126, 79, 31))
        if condition == "occluded":
            draw.polygon(
                [(264, 94), (402, 113), (363, 208), (250, 180)],
                fill=(157, 95, 145),
                outline=(101, 66, 94),
                width=3,
            )
            for y in range(120, 170, 10):
                draw.line((280, y, 370, y + 15), fill=(188, 132, 174), width=2)
        if condition == "glare":
            draw.ellipse((319, 91, 385, 151), fill=(255, 255, 255))
        if condition == "missing_sticker":
            draw.rectangle((162, 219, 234, 248), fill=(248, 249, 220), outline=(80, 100, 80))
            draw.text((174, 228), "PASS", fill=(30, 85, 40))
    image = image.rotate(angle, Image.Resampling.BICUBIC, fillcolor=(232, 226, 211))
    image = image.transform(
        image.size,
        Image.Transform.AFFINE,
        (1, 0, -dx, 0, 1, -dy),
        Image.Resampling.BICUBIC,
        fillcolor=(232, 226, 211),
    )
    if condition == "blurred":
        image = image.filter(ImageFilter.GaussianBlur(9))
    return ImageEnhance.Brightness(image).enhance(light)


def build_assets(rows):
    folder = HERE / "assets"
    folder.mkdir(exist_ok=True)
    references = (
        ("r00.png", "absent", (0, 0, 0, 1)),
        ("r10.png", "reversed", (0, 0, 0, 1)),
        ("r11.png", "multiple", (-4, 2, 0, 0.95)),
        ("r20.png", "missing", (0, 0, 0, 1)),
        ("r21.png", "offset", (3, -2, 0, 1.02)),
        ("r30.png", "good", (0, 0, 0, 1)),
        ("r31.png", "good", (8, -4, 1, 0.85)),
    )
    for name, condition, view in references:
        render(condition, view).save(folder / name)
    for ident, _split, condition, view, _level, _probs, _visible in rows:
        render(condition, view).save(folder / f"{ident}.png")


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for ident, split, condition, _view, level, _probs, _visible in rows:
        fields = {"image": f"assets/{ident}.png"}
        state, questions, assets = helpers.build_request(fields, HERE)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if split != "demo":
            labels.append(
                {
                    "id": ident,
                    "label": {
                        "level": level,
                        "inspectable": level is not None,
                        "reason": REASONS[condition],
                    },
                }
            )
    return inputs, labels


def build_responses(rows):
    responses = {}
    for ident, _split, _condition, _view, _level, probs, visible in rows:
        state, questions, assets = helpers.build_request({"image": f"assets/{ident}.png"}, HERE)
        key = replay_key(state, questions, assets=assets)
        answers = {
            "conformity": ScoreAnswer.from_probabilities(
                probs, questions["conformity"].criteria, Provenance.synthetic()
            ),
            "inspectable": NoulAnswer(visible, Provenance.synthetic()),
        }
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def _is_recorded(path):
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
    except (ValueError, OSError):
        return True
    return not isinstance(data, dict) or any(
        not isinstance(entry, dict) or entry.get("model") != "synthetic" for entry in data.values()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    build_assets(ROWS)
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text("".join(json.dumps(row) + "\n" for row in rows), "utf-8")
    path = folder / "responses.json"
    if _is_recorded(path) and not args.force:
        raise SystemExit("refusing to overwrite recorded responses; pass --force explicitly")
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
