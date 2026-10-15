"""Render authored UI screenshots and deliberately imperfect synthetic responses."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import BoxAnswer, DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.fixtures import Example
from jev_cookbook.live import _dump

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
SIZE = (512, 384)
TARGETS = {"button": "Save changes", "input": "Search projects", "menu": "Export CSV"}

# id, split, kind, layout, situation, presence probability, box confidence, box error
ROWS = [
    ("v01", "validation", "button", "standard", "normal", 0.98, 0.98, "small"),
    ("v02", "validation", "input", "reflow", "normal", 0.92, 0.98, "small"),
    ("v03", "validation", "menu", "reflow", "normal", 0.98, 0.92, "small"),
    ("v04", "validation", "button", "reflow", "normal", 0.98, 0.85, "wrong"),
    ("v05", "validation", "input", "standard", "absent", 0.85, 0.98, "wrong"),
    ("v06", "validation", "menu", "standard", "absent", 0.02, 0.99, "wrong"),
    ("v07", "validation", "button", "standard", "disabled", 0.98, 0.99, "exact"),
    ("v08", "validation", "input", "reflow", "duplicate", 0.98, 0.98, "exact"),
    ("v09", "validation", "menu", "standard", "normal", 0.98, None, "exact"),
    ("v10", "validation", "button", "reflow", "normal", 0.58, 0.96, "exact"),
    ("t01", "test", "button", "standard", "normal", 0.98, 0.98, "small"),
    ("t02", "test", "input", "reflow", "normal", 0.97, 0.97, "small"),
    ("t03", "test", "menu", "reflow", "normal", 0.98, 0.96, "small"),
    ("t04", "test", "button", "reflow", "normal", 0.98, 0.98, "wrong"),
    ("t05", "test", "input", "standard", "absent", 0.02, 0.99, "wrong"),
    ("t06", "test", "menu", "reflow", "absent", 0.05, 0.99, "wrong"),
    ("t07", "test", "button", "standard", "normal", 0.04, 0.99, "exact"),
    ("t08", "test", "input", "standard", "duplicate", 0.98, 0.99, "exact"),
    ("t09", "test", "menu", "standard", "disabled", 0.98, 0.99, "exact"),
    ("t10", "test", "input", "reflow", "normal", 0.98, None, "exact"),
    ("t11", "test", "menu", "standard", "normal", 0.98, 0.78, "small"),
    ("t12", "test", "button", "reflow", "absent", 0.56, 0.99, "wrong"),
    ("d01", "demo", "button", "reflow", "normal", 0.98, 0.97, "small"),
    ("d02", "demo", "menu", "standard", "absent", 0.01, 0.99, "wrong"),
]


def rectangle(kind, layout):
    if layout == "standard":
        return helpers.BASELINE_PIXELS[kind]
    return {
        "button": (66, 236, 226, 280),
        "input": (70, 224, 454, 268),
        "menu": (72, 236, 242, 276),
    }[kind]


def normalized(rect):
    left, top, right, bottom = rect
    return {
        "top": top / SIZE[1],
        "bottom": bottom / SIZE[1],
        "left": left / SIZE[0],
        "right": right / SIZE[0],
    }


def render(row):
    """Return PNG-ready pixels and separately authored gold geometry."""
    ident, _split, kind, layout, situation, *_ = row
    image = Image.new("RGB", SIZE, "#FEFEFE")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=16)
    small = ImageFont.load_default(size=13)
    bold = ImageFont.load_default(size=20)
    draw.rectangle((0, 0, 511, 43), fill="#1E1E1E")
    draw.text((18, 12), "STUDIO / Project workspace", font=font, fill="white")
    draw.text((18, 57), "Overview     Projects     Settings", font=small, fill="#666666")
    draw.rounded_rectangle((40, 88, 488, 346), radius=14, fill="#F4F4F4")
    draw.text((62, 101), "Workspace preferences", font=bold, fill="#1E1E1E")
    draw.text((62, 194), "Keep your project details up to date.", font=small, fill="#666666")
    draw.text(
        (62, 214 if layout == "standard" else 156),
        "Changes stay in this demo.",
        font=small,
        fill="#666666",
    )
    draw.text(
        (18, 360), f"Sample screen {ident}  |  local demonstration", font=small, fill="#666666"
    )
    rect = rectangle(kind, layout)
    if kind == "menu":
        left, top, right, bottom = rect
        draw.text((left, top - 29), "Actions", font=small, fill="#1E1E1E")
        draw.rounded_rectangle(
            (left - 8, top - 8, right + 8, bottom + 52),
            radius=8,
            fill="#FEFEFE",
            outline="#AAAAAA",
        )
        draw.text((left + 12, bottom + 18), "Copy link", font=font, fill="#1E1E1E")
    boxes = []
    if situation != "absent":
        boxes.append(rect)
        if situation == "duplicate":
            # Distinct full-width controls with the same name, separated vertically.
            boxes = [(64, 130, 448, 174), (64, 258, 448, 302)]
        for left, top, right, bottom in boxes:
            disabled = situation == "disabled"
            fill = "#DEDEDE" if disabled else "#F386A1" if kind == "button" else "#FEFEFE"
            ink = "#999999" if disabled else "#1E1E1E"
            draw.rounded_rectangle(
                (left, top, right - 1, bottom - 1), radius=6, fill=fill, outline=ink, width=2
            )
            text = TARGETS[kind]
            draw.text((left + 12, top + 12), text, font=font, fill=ink)
            if disabled:
                draw.text((left, bottom + 5), "Disabled while syncing", font=small, fill="#777777")
    else:
        left, top, right, bottom = rect
        draw.rounded_rectangle(
            (left, top, right - 1, bottom - 1), radius=6, fill="#DEDEDE", outline="#AAAAAA"
        )
        distractor = {"button": "Discard draft", "input": "Filter members", "menu": "Import CSV"}
        draw.text((left + 10, top + 12), distractor[kind], font=font, fill="#1E1E1E")
    gold = {
        "present": situation != "absent",
        "unique": situation not in ("duplicate", "absent"),
        "enabled": situation not in ("disabled", "absent"),
        "boxes": [normalized(box) for box in boxes],
    }
    return image, gold


def fixture_parts(row, root):
    ident, _split, kind, layout, situation, probability, confidence, error = row
    image, gold = render(row)
    # Filenames and request references reveal no layout or gold coordinates.
    import io

    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    blob = encoded.getvalue()
    filename = hashlib.sha256(blob).hexdigest() + ".png"
    assets = Path(root) / "assets"
    assets.mkdir(exist_ok=True, parents=True)
    (assets / filename).write_bytes(blob)
    fields = {"image": f"assets/{filename}", "target": TARGETS[kind], "kind": kind}
    if ident == "d02":
        fields["counterfactual"] = True
    provenance = Provenance.synthetic()
    judgments = {
        "present": NoulAnswer(probability, provenance),
        "unique": NoulAnswer(0.06 if situation == "duplicate" else 0.98, provenance),
        "enabled": NoulAnswer(0.03 if situation == "disabled" else 0.98, provenance),
    }
    predicted = rectangle(kind, layout)
    if error == "wrong":
        predicted = (54, 92, 282, 124)
    elif error == "small":
        left, top, right, bottom = predicted
        predicted = (left + 3, top + 2, right - 2, bottom - 2)
    location = BoxAnswer(box=normalized(predicted), confidence=confidence, provenance=provenance)
    return fields, gold, helpers.Observation(judgments, location)


def prepare(rows, root):
    return {row[0]: fixture_parts(row, root) for row in rows}


def frozen_policy(rows, parts, root):
    validation = [
        Example(id=row[0], split=row[1], fields=parts[row[0]][0], replay_keys=())
        for row in rows
        if row[1] == "validation"
    ]
    return helpers.select_policy(
        validation,
        {key: value[2] for key, value in parts.items()},
        {key: value[1] for key, value in parts.items()},
        root,
        objective=helpers.OBJECTIVE,
    )[0]


def requests(rows, parts, root):
    policy = frozen_policy(rows, parts, root)
    for row in rows:
        ident, split = row[:2]
        fields, gold, observation = parts[ident]
        state, assets = helpers.request_data(fields, root)
        first = helpers.build_questions()
        items = [(replay_key(state, first, assets=assets), observation.judgments)]
        threshold = min(helpers.PRESENCE_CANDIDATES) if split == "validation" else policy.presence
        if helpers.first_gate(observation.judgments, threshold) is None or fields.get(
            "counterfactual"
        ):
            second = helpers.box_questions()
            items.append(
                (replay_key(state, second, assets=assets), {"target_box": observation.location})
            )
        yield ident, split, fields, gold, items


def build_inputs_and_labels(rows, root=HERE):
    parts = prepare(rows, root)
    inputs, labels = [], []
    for ident, split, fields, gold, items in requests(rows, parts, root):
        inputs.append(
            {
                "id": ident,
                "split": split,
                "fields": fields,
                "replay_keys": [key for key, _ in items],
            }
        )
        if split != "demo":
            labels.append({"id": ident, "label": gold})
    return inputs, labels


def build_responses(rows, root=HERE):
    parts = prepare(rows, root)
    return {
        key: DecisionResult(answers, "synthetic").to_dict()
        for *_ignored, items in requests(rows, parts, root)
        for key, answers in items
    }


def protected(path):
    """Fail closed for malformed files and recorded responses, including provenance."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            return True
        return any(DecisionResult.from_dict(value).source != "synthetic" for value in data.values())
    except (ValueError, TypeError, OSError, AttributeError, KeyError):
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="replace protected responses explicitly"
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(parents=True, exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    response_path = folder / "responses.json"
    if protected(response_path) and not args.force:
        raise SystemExit(
            "refusing to overwrite recorded or malformed responses; use --force explicitly. "
            "Inputs, labels and authored assets were regenerated."
        )
    responses = build_responses(ROWS)
    response_path.write_text(_dump(responses), encoding="utf-8")
    referenced_assets = {Path(row["fields"]["image"]).name for row in inputs}
    for path in (HERE / "assets").glob("*.png"):
        if (
            path.stem == hashlib.sha256(path.read_bytes()).hexdigest()
            and path.name not in referenced_assets
        ):
            path.unlink()
    print(f"wrote {len(inputs)} screenshots, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
