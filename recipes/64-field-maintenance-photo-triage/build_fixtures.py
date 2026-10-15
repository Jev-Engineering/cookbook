"""Create illustrative equipment drawings and explicitly synthetic response distributions.

No photographs or model calls are used. ROWS separates drawing specifications, authored gold,
and imagined responses. None of those annotations enters build_request.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from jev_cookbook import (
    ChoiceAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    load_helpers,
    replay_key,
)

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, scene, gold summary, gold visible, gold flags, imagined summary,
# imagined top probability, imagined probabilities: visible/corrosion/leak/disconnected.
ROWS = [
    ("v01", "validation", "clean", "normal", True, (), "normal", .95, (.96, .03, .03, .03)),
    ("v02", "validation", "rust", "corrosion", True, ("corrosion",), "corrosion", .94, (.96, .94, .04, .04)),
    ("v03", "validation", "fluid", "leak", True, ("leak",), "leak", .92, (.95, .03, .92, .04)),
    ("v04", "validation", "unplugged", "disconnected_cabling", True, ("disconnected_cabling",), "disconnected_cabling", .91, (.96, .03, .04, .91)),
    ("v05", "validation", "paint", "normal", True, (), "normal", .90, (.96, .10, .03, .04)),
    ("v06", "validation", "wetmark", "normal", True, (), "normal", .89, (.95, .04, .11, .04)),
    ("v07", "validation", "shadow", "normal", True, (), "normal", .88, (.95, .04, .12, .04)),
    ("v08", "validation", "rust+fluid", "unclear", True, ("corrosion", "leak"), "unclear", .94, (.95, .94, .94, .04)),
    ("v09", "validation", "covered", "unclear", False, (), "unclear", .96, (.08, .49, .50, .52)),
    ("v10", "validation", "faint_rust", "corrosion", True, ("corrosion",), "normal", .62, (.94, .35, .05, .05)),
    ("v11", "validation", "short_gap", "disconnected_cabling", True, ("disconnected_cabling",), "disconnected_cabling", .80, (.94, .03, .04, .77)),
    ("v12", "validation", "shadow+wetmark", "normal", True, (), "leak", .70, (.93, .05, .69, .05)),
    ("t01", "test", "rust", "corrosion", True, ("corrosion",), "corrosion", .94, (.96, .94, .03, .04)),
    ("t02", "test", "fluid", "leak", True, ("leak",), "leak", .91, (.96, .03, .92, .04)),
    ("t03", "test", "unplugged", "disconnected_cabling", True, ("disconnected_cabling",), "disconnected_cabling", .93, (.96, .04, .04, .93)),
    ("t04", "test", "clean", "normal", True, (), "normal", .91, (.96, .04, .04, .04)),
    ("t05", "test", "paint", "normal", True, (), "corrosion", .93, (.95, .94, .04, .04)),
    ("t06", "test", "wetmark", "normal", True, (), "normal", .87, (.93, .05, .12, .05)),
    ("t07", "test", "shadow+wetmark", "normal", True, (), "leak", .64, (.92, .05, .63, .05)),
    ("t08", "test", "rust+fluid", "unclear", True, ("corrosion", "leak"), "unclear", .93, (.94, .92, .93, .04)),
    ("t09", "test", "covered", "unclear", False, (), "normal", .92, (.14, .20, .20, .20)),
    ("t10", "test", "rust+unplugged", "unclear", True, ("corrosion", "disconnected_cabling"), "corrosion", .92, (.93, .92, .05, .92)),
    ("t11", "test", "faint_fluid", "leak", True, ("leak",), "leak", .68, (.92, .05, .72, .05)),
    ("t12", "test", "short_gap", "disconnected_cabling", True, ("disconnected_cabling",), "disconnected_cabling", .86, (.93, .04, .04, .86)),
    ("d01", "demo", "rust+fluid", None, True, ("corrosion", "leak"), "unclear", .94, (.97, .96, .95, .03)),
    ("d02", "demo", "unplugged", None, True, ("disconnected_cabling",), "disconnected_cabling", .94, (.97, .03, .04, .96)),
]  # fmt: skip


def draw_scene(scene, variant, path):
    """480 x 360 synthetic diagram; variants change geometry, not just embedded metadata."""
    image = Image.new("RGB", (480, 360), (244 - variant % 6, 246, 248))
    d = ImageDraw.Draw(image)
    dx = variant % 7 - 3
    dy = (variant * 3) % 9 - 4

    def rect(box, **kwargs):
        d.rectangle(tuple(v + (dx if i % 2 == 0 else dy) for i, v in enumerate(box)), **kwargs)

    def line(points, **kwargs):
        d.line([(x + dx, y + dy) for x, y in points], **kwargs)

    parts = set(scene.split("+"))
    d.rectangle((0, 275, 480, 360), fill=(222, 226, 228))
    d.text((15, 15), "SYNTHETIC EQUIPMENT DRAWING - NOT A PHOTO", fill=(45, 50, 55))
    rect((64, 240, 423, 257), fill=(95, 107, 116), outline=(45, 55, 65), width=2)
    rect((92, 90, 212, 233), fill=(178, 196, 203), outline=(55, 72, 83), width=3)
    for x in range(105, 205, 17):
        line([(x, 101), (x, 146)], fill=(139, 157, 166), width=3)
    rect((210, 137, 304, 170), fill=(177, 193, 200), outline=(55, 72, 83), width=3)
    rect((232, 124, 252, 185), fill=(145, 165, 176), outline=(55, 72, 83), width=3)
    for y in (129, 173):
        rect((236, y, 242, y + 6), fill=(70, 82, 88))
    rect((355, 85, 420, 169), fill=(190, 199, 206), outline=(55, 72, 83), width=3)
    rect((347, 108, 362, 129), fill=(56, 63, 69))
    cable_end = 319 if "unplugged" in parts else 334 if "short_gap" in parts else 355
    line([(175, 230), (285, 230), (310, 118), (cable_end, 118)], fill=(225, 151, 47), width=8)
    rect((cable_end - 9, 111, cable_end, 125), fill=(230, 160, 50), outline=(70, 65, 55))
    if "paint" in parts:
        rect((111, 161, 170, 212), fill=(164, 79, 37), outline=(118, 60, 35), width=2)
        line([(114, 165), (167, 165)], fill=(225, 172, 125), width=2)
    if "rust" in parts or "faint_rust" in parts:
        n = 22 if "rust" in parts else 5
        for i in range(n):
            x = 111 + (i * 19 + variant * 3) % 65
            y = 161 + (i * 11 + variant) % 54
            r = 4 + i % 4
            d.polygon(
                [
                    (x + dx, y + dy - r),
                    (x + dx + r, y + dy),
                    (x + dx + r - 2, y + dy + r),
                    (x + dx - r, y + dy + 2),
                ],
                fill=(158 + i % 4 * 8, 73, 34),
            )
            d.ellipse((x + dx, y + dy, x + dx + 2, y + dy + 2), fill=(68, 55, 42))
    if "fluid" in parts or "faint_fluid" in parts:
        width = 6 if "fluid" in parts else 2
        line(
            [(243, 181), (246, 204), (240, 226), (245, 260), (251, 278)],
            fill=(37, 138, 195),
            width=width,
        )
        d.ellipse((223 + dx, 270, 288 + dx, 289), fill=(51, 150, 201))
        for y in (211, 241, 263):
            d.ellipse((251 + dx, y, 255 + dx, y + 7), fill=(51, 150, 201))
    if "wetmark" in parts:
        d.ellipse((285 + dx, 283, 389 + dx, 302), fill=(51, 150, 201))
    if "shadow" in parts:
        d.polygon([(120, 276), (365 + dx, 275), (438, 310), (222, 307)], fill=(154, 163, 171))
    if "covered" in parts:
        d.polygon([(57, 67), (330, 73), (434, 266), (70, 274)], fill=(83, 86, 89))
        d.line([(70, 74), (320, 80), (420, 257)], fill=(120, 124, 127), width=5)
    d.text(
        (15, 326), "Illustrative visual evidence only; no operating clearance", fill=(45, 50, 55)
    )
    path.parent.mkdir(exist_ok=True, parents=True)
    image.save(path, format="PNG", optimize=False)


def _fields(row):
    return {"image": f"assets/{row[0]}.png"}


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for variant, row in enumerate(rows):
        ident, split, scene, gold, visible, flags, *_ = row
        fields = _fields(row)
        draw_scene(scene, variant, HERE / fields["image"])
        state, questions, assets = helpers.build_request(fields)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if gold is not None:
            labels.append(
                {
                    "id": ident,
                    "label": {
                        "condition": gold,
                        "visible": visible,
                        "conditions": {name: name in flags for name in helpers.CONDITIONS},
                        "rationale": {
                            "paint": "Smooth bounded brown panel; no pitting or flaking.",
                            "wetmark": "Isolated floor mark; no visible path from joint.",
                            "covered": "Cover hides components; absent flags are unscored, not negatives.",
                            "shadow+wetmark": "Shadow and isolated floor mark do not show a joint leak.",
                        }.get(
                            scene,
                            f"Illustrated scene: {scene}; visible conditions are listed separately.",
                        ),
                    },
                }
            )
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        *_, selected, top, nouls = row
        state, questions, assets = helpers.build_request(_fields(row))
        probabilities = {
            name: top if name == selected else (1 - top) / 4 for name in helpers.OPTIONS
        }
        answers = {
            "condition": ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())
        }
        answers.update(
            {
                name: NoulAnswer(p, Provenance.synthetic())
                for name, p in zip(("visible", *helpers.CONDITIONS), nouls, strict=True)
            }
        )
        key = replay_key(state, questions, assets=assets)
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="replace recorded answers deliberately"
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text("".join(json.dumps(row) + "\n" for row in rows), "utf-8")
    path = folder / "responses.json"
    if path.exists():
        current = json.loads(path.read_text("utf-8"))
        if any(value.get("model") != "synthetic" for value in current.values()) and not args.force:
            raise SystemExit("refusing to overwrite recorded responses; use --force explicitly")
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    print(
        f"wrote {len(inputs)} images and examples, {len(labels)} labels, {len(responses)} responses"
    )


if __name__ == "__main__":
    main()
