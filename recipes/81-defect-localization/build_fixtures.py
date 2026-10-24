"""Author small inspection drawings and deliberately imperfect synthetic responses."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from jev_cookbook import BoxAnswer, DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
SIZE = (480, 360)


def row(ident, split, target, scene, bounds, probs, confidence, *, predicted=None, note=""):
    return {
        "id": ident,
        "split": split,
        "target": target,
        "scene": scene,
        "bounds": bounds,
        "probabilities": probs,
        "confidence": confidence,
        "predicted": predicted,
        "note": note,
    }


ROWS = [
    row("v01", "validation", "scratch", "scratch", (135, 133, 229, 161), (.98, .98, .99), .96),
    row("v02", "validation", "dent", "dent", (259, 173, 327, 223), (.96, .98, .99), .91),
    row("v03", "validation", "broken component", "broken", (183, 143, 251, 203), (.97, .98, .99), .92),
    row("v04", "validation", "scratch", "scratch", (272, 119, 359, 146), (.94, .96, .98), .88),
    row("v05", "validation", "dent", "dent", (143, 204, 212, 250), (.97, .97, .99), .84),
    row("v06", "validation", "scratch", "clean", None, (.03, .02, .98), None,
        note="Clean brushed surface; screw slots are outside the window."),
    row("v07", "validation", "scratch", "seam", None, (.04, .03, .98), None,
        note="Straight dashed registration mark is printed, not a scratch."),
    row("v08", "validation", "dent", "scratch", (217, 181, 305, 211), (.06, .03, .99), None,
        note="A scratch exists, but the requested dent is absent."),
    row("v09", "validation", "scratch", "multiple", (124, 123, 211, 149), (.99, .05, .99), None,
        note="Two independent scratches; no unique rectangle is defined."),
    row("v10", "validation", "dent", "occluded", (200, 152, 270, 202), (.97, .96, .20), None,
        note="A blue tool cover hides the lower extent of the dent."),
    row("v11", "validation", "scratch", "faint", (254, 218, 343, 243), (.69, .80, .99), None,
        note="Faint but authored visible scratch; weak presence evidence causes review."),
    row("v12", "validation", "dent", "dent", (187, 102, 254, 150), (.98, .98, .99), None,
        note="Box has no confidence and must not be accepted."),
    row("v13", "validation", "scratch", "scratch", (133, 185, 232, 215), (.98, .98, .99), .70,
        predicted=(301, 110, 362, 147), note="A misplaced low-confidence rectangle."),
    row("v14", "validation", "scratch", "ink", None, (.86, .92, .99), .95,
        predicted=(163, 142, 260, 173), note="Dark printed trace mistaken for a scratch."),
    row("t01", "test", "scratch", "scratch", (167, 113, 267, 144), (.98, .98, .99), .94),
    row("t02", "test", "dent", "dent", (132, 166, 210, 221), (.96, .97, .99), .93),
    row("t03", "test", "broken component", "broken", (277, 187, 347, 247), (.97, .97, .99), .92),
    row("t04", "test", "scratch", "scratch", (224, 155, 359, 193), (.93, .95, .98), .86),
    row("t05", "test", "dent", "dent", (272, 102, 342, 150), (.98, .98, .99), .65,
        note="Correct rectangle rejected by frozen box confidence."),
    row("t06", "test", "scratch", "clean", None, (.02, .02, .99), None),
    row("t07", "test", "scratch", "seam", None, (.03, .02, .99), None),
    row("t08", "test", "scratch", "reflection", None, (.98, .98, .99), .96,
        predicted=(151, 159, 301, 187), note="Bright foil reflection confidently mistaken for a gouge."),
    row("t09", "test", "scratch", "multiple", (139, 148, 225, 177), (.99, .10, .99), None,
        note="Two separate scratches require a human to choose a target."),
    row("t10", "test", "dent", "occluded", (242, 154, 314, 207), (.98, .95, .10), None,
        note="Tool cover hides part of the requested dent."),
    row("t11", "test", "scratch", "scratch", (128, 223, 221, 249), (.86, .97, .99), .97,
        note="Acquisition screen passes, frozen presence gate defers."),
    row("t12", "test", "dent", "dent", (225, 202, 298, 251), (.98, .98, .99), .95,
        predicted=(122, 111, 186, 150), note="Confident misplaced rectangle survives every gate."),
    row("t13", "test", "broken component", "broken", (158, 144, 228, 204), (.03, .02, .99), None,
        note="Confident absence misses a visible fractured terminal."),
    row("t14", "test", "scratch", "scratch", (257, 127, 345, 155), (.98, .98, .99), None,
        note="Missing box confidence always defers."),
    row("d01", "demo", "scratch", "scratch", (175, 161, 293, 195), (.98, .97, .99), .94),
    row("d02", "demo", "scratch", "multiple", (135, 124, 221, 151), (.99, .08, .99), None),
]  # fmt: skip


def normalized(bounds):
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    return {
        "top": top / SIZE[1],
        "bottom": bottom / SIZE[1],
        "left": left / SIZE[0],
        "right": right / SIZE[0],
    }


def scratch(draw, bounds, *, faint=False):
    x, y, r, b = bounds
    points = [(x + 3, b - 6), (x + 21, y + 10), (x + 43, y + 15), (r - 24, y + 3), (r - 5, y + 7)]
    draw.line([(a + 2, c + 2) for a, c in points], fill=(247, 248, 249), width=5)
    draw.line(points, fill=(149, 157, 162) if faint else (55, 64, 69), width=4)
    for a, c in points[1:-1]:
        draw.line((a, c, a + 5, max(y + 1, c - 7)), fill=(121, 133, 140), width=2)


def dent(draw, bounds):
    x, y, r, b = bounds
    draw.ellipse((x, y, r - 1, b - 1), fill=(244, 246, 248), outline=(152, 164, 173), width=2)
    draw.ellipse((x + 4, y + 3, r - 4, b - 5), fill=(144, 156, 166))
    draw.ellipse((x + 8, y + 7, r - 9, b - 8), fill=(162, 175, 185))
    draw.arc((x + 2, y + 1, r - 2, b - 2), 180, 340, fill=(109, 125, 138), width=3)
    draw.arc((x + 5, y + 5, r - 5, b - 4), 10, 160, fill=(232, 238, 243), width=4)


def broken(draw, bounds):
    x, y, r, b = bounds
    mid = (x + r) // 2
    draw.polygon(
        [
            (x, y + 8),
            (mid - 4, y + 8),
            (mid - 10, y + 23),
            (mid - 3, y + 32),
            (mid - 12, b - 4),
            (x, b - 4),
        ],
        fill=(201, 142, 59),
        outline=(63, 66, 66),
        width=3,
    )
    draw.polygon(
        [
            (mid + 8, y),
            (r - 1, y + 4),
            (r - 1, b - 8),
            (mid + 10, b - 12),
            (mid + 16, y + 28),
            (mid + 7, y + 19),
        ],
        fill=(226, 166, 66),
        outline=(62, 65, 66),
        width=3,
    )
    for px in (x + 10, r - 13):
        draw.line((px, y + 17, px, b - 16), fill=(243, 213, 137), width=4)


def draw_scene(item, index):
    """Original procedural drawings, not photographs; geometry lives outside inference."""
    image = Image.new("RGB", SIZE, (29, 38, 45))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle(
        (26, 44, 454, 316), radius=20, fill=(83, 98, 110), outline=(127, 148, 160), width=3
    )
    d.rounded_rectangle(
        (60, 72, 420, 290), radius=12, fill=(199, 208, 215), outline=(150, 164, 174), width=3
    )
    for y in range(85, 280, 4):
        tone = 192 + (y + 3 * index) % 15
        d.line((77, y, 403, y), fill=(tone, tone + 8, tone + 13))
    for x, y in ((77, 89), (403, 89), (77, 272), (403, 272)):
        d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(129, 144, 157), outline=(67, 78, 87), width=2)
        d.line((x - 5, y + 4, x + 5, y - 4), fill=(57, 67, 76), width=3)
    d.text((31, 19), "SERVICE PANEL  /  SURFACE INSPECTION", fill=(231, 238, 242))
    d.text((47, 332), "SYNTHETIC DRAWING     |     FIXED CAMERA VIEW", fill=(170, 190, 201))
    # Each scene has a different texture phase and status LED without revealing a label.
    d.ellipse((428, 67 + index % 4, 437, 76 + index % 4), fill=(109, 200, 172))
    scene, bounds = item["scene"], item["bounds"]
    if scene in ("scratch", "faint", "multiple"):
        scratch(d, bounds, faint=scene == "faint")
        if scene == "multiple":
            scratch(d, (270, 211, 358, 240))
    elif scene in ("dent", "occluded"):
        dent(d, bounds)
        if scene == "occluded":
            x, y, r, b = bounds
            d.rounded_rectangle(
                (x - 25, y + 20, r + 29, b + 47),
                radius=9,
                fill=(54, 104, 145),
                outline=(28, 67, 98),
                width=3,
            )
            d.line((x - 18, y + 29, r + 22, y + 29), fill=(101, 149, 186), width=3)
    elif scene == "broken":
        broken(d, bounds)
    elif scene == "seam":
        for x in range(145, 336, 19):
            d.line((x, 175, x + 10, 175), fill=(65, 74, 81), width=3)
        d.text((149, 189), "ALIGN", fill=(84, 94, 101))
    elif scene == "ink":
        d.line((164, 170, 193, 143, 223, 170, 259, 144), fill=(38, 53, 64), width=4)
        d.text((171, 185), "TRACE", fill=(75, 89, 101))
    elif scene == "reflection":
        d.polygon([(151, 182), (290, 159), (301, 165), (164, 187)], fill=(249, 250, 251))
        d.line((154, 186, 300, 165), fill=(164, 175, 182), width=2)
    return image


def fields_for(item):
    return {"image": f"assets/{item['id']}.png", "target": item["target"]}


def gold_for(item):
    actual = {
        "scratch": "scratch",
        "faint": "scratch",
        "dent": "dent",
        "broken": "broken component",
    }.get(item["scene"])
    if item["scene"] in ("multiple", "occluded"):
        outcome = "review"
    else:
        outcome = "located" if actual == item["target"] else "absent"
    return {
        "outcome": outcome,
        "box": normalized(item["bounds"]) if outcome == "located" else None,
        "note": item["note"]
        or (
            f"Visible {item['target']} with full extent inside the window."
            if outcome == "located"
            else f"No visible {item['target']} in the window."
        ),
    }


def first_result(item):
    return DecisionResult(
        {
            name: NoulAnswer(p, Provenance.synthetic())
            for name, p in zip(("present", "unique", "clear"), item["probabilities"], strict=True)
        },
        "synthetic",
    )


def request_triples(item):
    fields = fields_for(item)
    triples = [helpers.request(fields, HERE)]
    if helpers.eligible(first_result(item).answers):
        triples.append(helpers.request(fields, HERE, locate=True))
    return triples


def build_inputs_and_labels(rows):
    (HERE / "assets").mkdir(exist_ok=True)
    inputs, labels = [], []
    for index, item in enumerate(rows):
        draw_scene(item, index).save(HERE / fields_for(item)["image"], format="PNG")
        keys = [replay_key(s, q, assets=a) for s, q, a in request_triples(item)]
        inputs.append(
            {
                "id": item["id"],
                "split": item["split"],
                "fields": fields_for(item),
                "replay_keys": keys,
            }
        )
        if item["split"] != "demo":
            labels.append({"id": item["id"], "label": gold_for(item)})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for item in rows:
        triples = request_triples(item)
        state, questions, assets = triples[0]
        responses[replay_key(state, questions, assets=assets)] = first_result(item).to_dict()
        if len(triples) == 2:
            state, questions, assets = triples[1]
            # A wrong response rectangle is authored independently of the gold label.
            bounds = item["predicted"] or item["bounds"]
            answer = BoxAnswer(normalized(bounds), item["confidence"], Provenance.synthetic())
            responses[replay_key(state, questions, assets=assets)] = DecisionResult(
                {"defect": answer}, "synthetic"
            ).to_dict()
    return responses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="replace recorded responses explicitly"
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for filename, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / filename).write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n"
        )
    destination = folder / "responses.json"
    if destination.exists() and not args.force:
        existing = json.loads(destination.read_text("utf-8"))
        if not isinstance(existing, dict) or any(
            not isinstance(r, dict) or r.get("model") != "synthetic" for r in existing.values()
        ):
            raise SystemExit(
                "refusing to overwrite recorded responses; use --force; inputs and labels were regenerated"
            )
    responses = build_responses(ROWS)
    destination.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(inputs)} drawings, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
