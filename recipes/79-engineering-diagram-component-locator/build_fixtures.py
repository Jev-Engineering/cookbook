"""Author process drawings, readable gold, and deliberately imperfect synthetic answers."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from jev_cookbook import BoxAnswer, DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
SIZE = (640, 420)

# id, split, drawing case, requested tag, layout offset, presence, uniqueness, box confidence,
# box variant. The drawings and labels are authored evidence, never inference inputs.
ROWS = [
    ("v01-valve", "validation", "plain", "V-101", -9, .98, .97, .94, "correct"),
    ("v02-connector", "validation", "plain", "C-201", -5, .97, .96, .92, "correct"),
    ("v03-reflow", "validation", "reflow", "V-102", 4, .95, .94, .88, "correct"),
    ("v04-rotated", "validation", "rotated", "V-101", 2, .94, .93, .83, "correct"),
    ("v05-pump", "validation", "plain", "P-301", 6, .96, .95, .91, "correct"),
    ("v06-absent", "validation", "absent", "C-201", -3, .03, .02, None, "correct"),
    ("v07-duplicate", "validation", "duplicate", "V-101", 3, .98, .05, None, "correct"),
    ("v08-near-label", "validation", "leaders", "V-101", -4, .93, .89, .78, "correct"),
    ("v09-junction", "validation", "junction", "C-201", 7, .04, .03, None, "correct"),
    ("v10-clipped", "validation", "clipped", "P-301", 1, .94, .93, .91, "correct"),
    ("v11-wrong-box", "validation", "plain", "V-102", 9, .95, .94, .65, "other"),
    ("v12-missing-confidence", "validation", "reflow", "C-201", -8, .94, .93, None, "correct"),
    ("t01-valve", "test", "plain", "V-101", 12, .97, .96, .93, "correct"),
    ("t02-connector", "test", "plain", "C-201", 15, .96, .95, .91, "correct"),
    ("t03-reflow", "test", "reflow", "V-102", -15, .95, .94, .87, "correct"),
    ("t04-rotated", "test", "rotated", "V-101", -12, .92, .91, .82, "correct"),
    ("t05-missed-pump", "test", "plain", "P-301", -16, .03, .02, None, "correct"),
    ("t06-absent", "test", "absent", "C-201", 11, .03, .02, None, "correct"),
    ("t07-duplicate", "test", "duplicate", "V-101", -13, .97, .04, None, "correct"),
    ("t08-wrong-binding", "test", "leaders", "V-101", 14, .98, .97, .96, "other"),
    ("t09-junction-false-positive", "test", "junction", "C-201", -11, .96, .95, .93, "junction"),
    ("t10-clipped", "test", "clipped", "P-301", 13, .94, .92, .89, "correct"),
    ("t11-uncertain-binding", "test", "leaders", "V-102", -17, .91, .64, .84, "correct"),
    ("t12-missing-confidence", "test", "reflow", "C-201", 17, .95, .94, None, "correct"),
    ("d01-label-leaders", "demo", "leaders", "V-101", 0, .98, .97, .95, "correct"),
    ("d02-duplicate", "demo", "duplicate", "V-101", 20, .97, .03, None, "correct"),
]  # fmt: skip


def bounds(kind, center, rotated=False):
    x, y = center
    offsets = {
        "valve": (-16, -17, 17, 12),
        "connector": (-6, -13, 7, 14),
        "pump": (-16, -16, 17, 17),
        "junction": (-6, -6, 7, 7),
    }
    left, top, right, bottom = offsets[kind]
    if rotated:
        left, top, right, bottom = top, -right + 1, bottom, -left + 1
    return {
        "left": max(0, x + left) / SIZE[0],
        "top": max(0, y + top) / SIZE[1],
        "right": min(SIZE[0], x + right) / SIZE[0],
        "bottom": min(SIZE[1], y + bottom) / SIZE[1],
    }


def drawing(row):
    _, _, case, target, shift, *_ = row
    image = Image.new("RGB", SIZE, helpers.PAPER)
    d = ImageDraw.Draw(image)
    d.rectangle((0, 0, 639, 43), fill=(222, 222, 222))
    d.text(
        (18, 12), "PROCESS LOOP / synthetic teaching drawing", font=helpers.FONT, fill=helpers.INK
    )
    y = 130 + (35 if case == "reflow" else 0) + shift // 2
    locations = {
        "V-101": (155 + shift, y),
        "V-102": (325 - shift, y),
        "C-201": (480 + shift, y),
        "P-301": (230 - shift, 265 + shift // 3),
    }
    if case == "reflow":
        locations["V-101"], locations["V-102"] = locations["V-102"], locations["V-101"]
    if case == "rotated":
        locations[target] = (155 + shift, 232)
    if case == "clipped":
        locations[target] = (3, 265 + shift // 3)
    bottom = locations["P-301"][1]
    d.line([(48, y), (592, y), (592, bottom), (48, bottom), (48, y)], fill=helpers.INK, width=2)
    if case == "clipped":
        d.line((0, bottom, 230, bottom), fill=helpers.INK, width=2)
    d.polygon([(590, y + 25), (585, y + 35), (595, y + 35)], fill=helpers.INK)
    d.text((505, bottom + 18), "return loop", font=helpers.FONT, fill=helpers.INK)
    junction = (410 - shift, bottom)
    d.line((junction[0], bottom - 48, junction[0], bottom), fill=helpers.INK, width=2)
    d.ellipse((junction[0] - 5, bottom - 5, junction[0] + 5, bottom + 5), fill=helpers.INK)
    kinds = {"V-101": "valve", "V-102": "valve", "C-201": "connector", "P-301": "pump"}
    for label, (x, sy) in locations.items():
        if case in {"absent", "junction"} and label == target:
            if case == "junction":
                d.line((x, sy - 34, x, sy + 34), fill=helpers.INK, width=2)
                d.ellipse((x - 5, sy - 5, x + 5, sy + 5), fill=helpers.INK)
                d.text((x - 24, sy - 44), label, font=helpers.FONT, fill=helpers.INK)
            continue
        rotated = case == "rotated" and label == target
        if rotated:
            d.line((x, y, x, bottom), fill=helpers.INK, width=2)
        image.paste(helpers.symbol(kinds[label], rotated), (x - 20, sy - 20))
        tag = "V-101" if case == "duplicate" and label == "V-102" else label
        lx, ly = x - 24, sy - 44
        if case == "leaders" and label.startswith("V"):
            other = "V-102" if label == "V-101" else "V-101"
            lx = locations[other][0] - 24
            ly -= 23 if label == "V-101" else 44
            d.line(
                [(lx + 24, ly + 20), (lx + 24, ly + 24), (x, sy - 22)],
                fill=(100, 100, 100),
                width=1,
            )
            d.ellipse((x - 2, sy - 24, x + 2, sy - 20), fill=helpers.INK)
        d.text((lx, ly), tag, font=helpers.FONT, fill=helpers.INK)
    d.line((15, 331, 624, 331), fill=(160, 160, 160), width=1)
    d.text(
        (18, 341),
        "LEGEND / teaching symbols, not an operating document",
        font=helpers.FONT,
        fill=helpers.INK,
    )
    for x, kind, text in [
        (40, "valve", "valve"),
        (180, "connector", "connector"),
        (352, "pump", "pump"),
        (495, "junction", "junction"),
    ]:
        image.paste(helpers.symbol(kind), (x - 20, 371))
        d.text((x + 26, 383), text, font=helpers.FONT, fill=helpers.INK)
    # Coordinates and the annotation explanation stay in labels/generator, never fields/state.
    box = bounds(kinds[target], locations[target], case == "rotated")
    status = "located"
    note = "One symbol has the requested tag; box covers symbol body, excluding pipes and tag."
    if case in {"absent", "junction"}:
        status, box = "absent", None
        note = (
            "Requested connector removed."
            if case == "absent"
            else "C-201 text is beside a junction dot; no flanged connector carries this tag."
        )
    elif case in {"duplicate", "clipped"}:
        status, box = "review", None
        note = (
            "Two valve bodies carry V-101; there is no unique requested symbol."
            if case == "duplicate"
            else "Pump body extends outside the image; a complete body cannot be enclosed."
        )
    if case == "leaders":
        note = "Follow crossed leader endpoints: the nearest label is attached to the other valve."
    gold = {"status": status, "box": box, "rationale": note}
    proposed = bounds(kinds[target], locations[target], case == "rotated")
    if row[-1] == "other":
        other = "V-102" if target == "V-101" else "V-101"
        proposed = bounds("valve", locations[other])
    elif row[-1] == "junction":
        proposed = bounds("junction", locations[target])
    return image, gold, proposed


def materialize(row):
    image, gold, proposed = drawing(row)
    # Pixel bytes determine the opaque file identity. The saved PNG has no drawing metadata.
    name = hashlib.sha256(image.tobytes()).hexdigest() + ".png"
    path = HERE / "assets" / name
    path.parent.mkdir(exist_ok=True)
    image.save(path)
    return {"image": "assets/" + name, "target": row[3]}, gold, proposed


def requests_for(row):
    fields, gold, box = materialize(row)
    state, assets = helpers.build_state(fields, HERE)
    provenance = Provenance.synthetic()
    first = DecisionResult(
        {"present": NoulAnswer(row[5], provenance), "unique": NoulAnswer(row[6], provenance)},
        "synthetic",
    )
    requests = [(state, helpers.build_questions(), assets, first)]
    if helpers.first_stage(first, helpers.ACQUISITION_FLOOR) == "eligible":
        second = DecisionResult({"component": BoxAnswer(box, row[7], provenance)}, "synthetic")
        requests.append((state, helpers.build_box_question(), assets, second))
    return fields, gold, requests


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for row in rows:
        fields, gold, requests = requests_for(row)
        keys = [replay_key(s, q, assets=a) for s, q, a, _ in requests]
        inputs.append({"id": row[0], "split": row[1], "fields": fields, "replay_keys": keys})
        if row[1] != "demo":
            labels.append({"id": row[0], "label": gold})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        _, _, requests = requests_for(row)
        for state, questions, assets, result in requests:
            responses[replay_key(state, questions, assets=assets)] = result.to_dict()
    return responses


def _is_recorded(path):
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
    except (ValueError, OSError):
        return True
    return not isinstance(data, dict) or any(
        not isinstance(entry, dict)
        or entry.get("model") != "synthetic"
        or any(
            a.get("provenance", {}).get("kind") == "recorded"
            for a in entry.get("answers", {}).values()
        )
        for entry in data.values()
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, data in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text(
            "".join(json.dumps(r) + "\n" for r in data), encoding="utf-8", newline="\n"
        )
    path = folder / "responses.json"
    if _is_recorded(path) and not args.force:
        raise SystemExit("refusing to overwrite recorded responses; use --force explicitly")
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
