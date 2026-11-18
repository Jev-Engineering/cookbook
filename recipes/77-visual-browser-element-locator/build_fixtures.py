"""Render authored UI screenshots and deliberately imperfect synthetic responses."""

import argparse
import json
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import (
    BoxAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    dump_responses,
    load_helpers,
    replay_key,
)
from jev_cookbook import (
    synthetic_images as si,
)
from jev_cookbook.fixtures import Example, FixtureFileError, load_responses

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
SIZE = (512, 384)
TARGETS = {"button": "Save changes", "input": "Search projects", "menu": "Export CSV"}
# Fictional application content, authored independently of split and response correctness.
WORKSPACES = {
    "v01": "Cedar",
    "v02": "Lumen",
    "v03": "Harbor",
    "v04": "Quartz",
    "v05": "Finch",
    "v06": "Nimbus",
    "v07": "Maple",
    "v08": "Pebble",
    "v09": "Willow",
    "v10": "Atlas",
    "t01": "Clover",
    "t02": "Saffron",
    "t03": "Linden",
    "t04": "Marble",
    "t05": "River",
    "t06": "Hazel",
    "t07": "Meadow",
    "t08": "Amber",
    "t09": "Aspen",
    "t10": "Fern",
    "t11": "Laurel",
    "t12": "Solstice",
    "d01": "Orchard",
    "d02": "Breeze",
}

# id, split, kind, layout, situation, presence probability, box confidence, box error
ROWS = [
    ("v01", "validation", "button", "standard", "normal", 0.98, 0.98, "small"),
    ("v02", "validation", "input", "reflow", "normal", 0.90, 0.98, "small"),
    ("v03", "validation", "menu", "reflow", "normal", 0.98, 0.90, "small"),
    ("v04", "validation", "button", "reflow", "normal", 0.98, 0.85, "wrong"),
    ("v05", "validation", "input", "standard", "absent", 0.85, 0.98, "wrong"),
    ("v06", "validation", "menu", "standard", "absent", 0.02, 0.99, "wrong"),
    ("v07", "validation", "button", "standard", "disabled", 0.98, 0.99, "exact"),
    ("v08", "validation", "input", "reflow", "duplicate", 0.98, 0.98, "exact"),
    ("v09", "validation", "menu", "standard", "normal", 0.98, None, "exact"),
    ("v10", "validation", "button", "reflow", "normal", 0.58, 0.96, "exact"),
    ("t01", "test", "button", "standard", "normal", 0.98, 0.98, "small"),
    ("t02", "test", "input", "reflow", "normal", 0.97, 0.97, "small"),
    ("t03", "test", "menu", "clipped", "normal", 0.98, 0.96, "small"),
    ("t04", "test", "button", "reflow", "normal", 0.98, 0.98, "wrong"),
    ("t05", "test", "input", "standard", "absent", 0.02, 0.99, "wrong"),
    ("t06", "test", "menu", "reflow", "absent", 0.05, 0.99, "wrong"),
    ("t07", "test", "button", "standard", "normal", 0.04, 0.99, "exact"),
    ("t08", "test", "input", "standard", "duplicate", 0.98, 0.99, "exact"),
    ("t09", "test", "menu", "standard", "disabled", 0.98, 0.99, "exact"),
    ("t10", "test", "input", "reflow", "normal", 0.98, None, "exact"),
    ("t11", "test", "menu", "standard", "normal", 0.98, 0.78, "small"),
    ("t12", "test", "button", "reflow", "absent", 0.04, 0.99, "wrong"),
    ("d01", "demo", "button", "reflow", "normal", 0.98, 0.97, "small"),
    ("d02", "demo", "menu", "standard", "absent", None, None, None),
]


def rectangle(kind, layout):
    if layout == "standard":
        return helpers.BASELINE_PIXELS[kind]
    if layout == "clipped":
        return (386, 236, 556, 276)
    return {
        "button": (66, 236, 226, 280),
        "input": (70, 224, 454, 268),
        "menu": (72, 236, 242, 276),
    }[kind]


def normalized(rect):
    left, top, right, bottom = rect
    right, bottom = min(right, SIZE[0]), min(bottom, SIZE[1])
    return {
        "top": top / SIZE[1],
        "bottom": bottom / SIZE[1],
        "left": left / SIZE[0],
        "right": right / SIZE[0],
    }


def render(kind, layout, situation, workspace):
    """Return PNG-ready pixels and separately authored gold geometry."""
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
        "Changes are saved locally.",
        font=small,
        fill="#666666",
    )
    draw.text((18, 360), f"Workspace: {workspace}", font=small, fill="#666666")
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
    target = {"present": True, "box": normalized(boxes[0])} if boxes else {"present": False}
    gold = {
        "target": target,
        "unique": situation not in ("duplicate", "absent"),
        "enabled": situation not in ("disabled", "absent"),
        "boxes": [normalized(box) for box in boxes],
    }
    return image, gold


def image_path(workspace):
    return f"assets/{workspace.lower()}.png"


def fixture_parts(row, root, *, overwrite=False):
    ident, _split, kind, layout, situation, probability, confidence, error = row
    workspace = WORKSPACES[ident]
    image, gold = render(kind, layout, situation, workspace)
    path = image_path(workspace)
    si.write_asset(image, root, path, overwrite=overwrite)
    fields = {"image": path, "target": TARGETS[kind], "kind": kind}
    if probability is None:
        return fields, gold, None
    provenance = Provenance.synthetic()
    # The held-out contradiction claims both uniqueness and enabled state despite a no.
    claims_absence = probability <= 0.5 and ident != "t12"
    judgments = {
        "present": NoulAnswer(probability, provenance),
        "unique": NoulAnswer(
            0.06 if claims_absence or situation == "duplicate" else 0.98, provenance
        ),
        "enabled": NoulAnswer(
            0.03 if claims_absence or situation == "disabled" else 0.98, provenance
        ),
    }
    predicted = rectangle(kind, layout)
    if error == "wrong":
        predicted = (54, 92, 282, 124)
    elif error == "small":
        left, top, right, bottom = predicted
        predicted = (left + 3, top + 2, right - 2, bottom - 2)
    location = BoxAnswer(box=normalized(predicted), confidence=confidence, provenance=provenance)
    return fields, gold, helpers.Observation(judgments, location)


def prepare(rows, root, *, overwrite=False):
    # Compare existing images first, before writing any newly added picture.
    ordered = sorted(rows, key=lambda row: not (root / image_path(WORKSPACES[row[0]])).exists())
    return {row[0]: fixture_parts(row, root, overwrite=overwrite) for row in ordered}


def frozen_policy(rows, parts):
    validation = [
        Example(id=row[0], split=row[1], fields=parts[row[0]][0], replay_keys=())
        for row in rows
        if row[1] == "validation"
    ]
    return helpers.select_policy(
        validation,
        {key: value[2] for key, value in parts.items()},
        {key: value[1] for key, value in parts.items()},
    )


def requests(rows, parts, root):
    policy = frozen_policy(rows, parts)
    for row in rows:
        ident, split = row[:2]
        fields, gold, observation = parts[ident]
        if observation is None:
            yield ident, split, fields, gold, []
            continue
        state, assets = helpers.request_data(fields, root)
        first = helpers.build_questions()
        items = [(replay_key(state, first, assets=assets), observation.judgments)]
        threshold = helpers.COLLECTION_THRESHOLD if split == "validation" else policy.presence
        if helpers.first_gate(observation.judgments, threshold) is None:
            box_state, second = helpers.box_request(state)
            items.append(
                (replay_key(box_state, second, assets=assets), {"target_box": observation.location})
            )
        yield ident, split, fields, gold, items


def build_inputs_and_labels(rows, root=HERE, *, parts=None):
    parts = prepare(rows, root) if parts is None else parts
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


def build_responses(rows, root=HERE, *, parts=None):
    parts = prepare(rows, root) if parts is None else parts
    return {
        key: DecisionResult(answers, "synthetic").to_dict()
        for *_ignored, items in requests(rows, parts, root)
        for key, answers in items
    }


def asset_manifest(rows, root):
    entries = []
    for ident, _split, kind, layout, situation, *_answer in rows:
        workspace = WORKSPACES[ident]
        parameters = {
            "kind": kind,
            "layout": layout,
            "situation": situation,
            "workspace": workspace,
        }
        entries.append(
            si.manifest_entry(
                root,
                image_path(workspace),
                "build_fixtures.py:render",
                parameters,
                f"A fictional project workspace with a {kind} control, "
                f"{layout} layout and {situation} target.",
            )
        )
    return {"schema": 1, "assets": sorted(entries, key=lambda entry: entry["path"])}


def protected(recipe_dir):
    """Allow automatic replacement only for strictly validated synthetic responses."""
    try:
        data = load_responses(recipe_dir)
    except FixtureFileError:
        return True
    return any(value["model"] != "synthetic" for value in data.values())


def existing_output_mode(path, expected_type):
    """Validate an output itself rather than following a link to another file."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SystemExit(f"refusing to write: cannot inspect {path.name}") from exc
    if not expected_type(mode):
        raise SystemExit(f"refusing to write: unexpected output type at {path.name}")
    return mode


def write_text(path, text, *, should_replace=None):
    """Replace the output without modifying other links to its previous file."""
    with TemporaryDirectory(dir=path.parent) as staging_dir:
        staged = Path(staging_dir) / path.name
        staged.write_text(text, encoding="utf-8", newline="\n")
        current_mode = existing_output_mode(path, stat.S_ISREG)
        if current_mode is not None:
            staged.chmod(stat.S_IMODE(current_mode))
        if should_replace is not None and not should_replace():
            return False
        staged.replace(path)
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="replace protected responses explicitly"
    )
    parser.add_argument(
        "--overwrite-assets", action="store_true", help="accept changed authored images"
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    response_path = folder / "responses.json"
    manifest_path = HERE / "assets-manifest.json"
    existing_output_mode(folder, stat.S_ISDIR)
    for path in (folder / "inputs.jsonl", folder / "labels.jsonl", manifest_path):
        existing_output_mode(path, stat.S_ISREG)
    response_exists = existing_output_mode(response_path, stat.S_ISREG) is not None
    response_is_protected = response_exists and not args.force and protected(HERE)
    if response_is_protected and args.overwrite_assets:
        raise SystemExit(
            "refusing --overwrite-assets with recorded or malformed responses; use --force"
        )
    try:
        parts = prepare(ROWS, HERE, overwrite=args.overwrite_assets)
    except si.RegenerationMismatch as exc:
        raise SystemExit(
            f"refused: {exc}\nnothing else was written; use --overwrite-assets to accept the changes"
        ) from exc

    write_text(manifest_path, json.dumps(asset_manifest(ROWS, HERE), indent=2) + "\n")
    folder.mkdir(parents=True, exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS, parts=parts)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        write_text(folder / name, "".join(json.dumps(row) + "\n" for row in rows))
    protected_message = (
        "refusing to overwrite recorded or malformed responses; use --force explicitly. "
        "Inputs, labels and the asset manifest were regenerated."
    )
    if response_is_protected:
        raise SystemExit(protected_message)

    responses = build_responses(ROWS, parts=parts)
    response_text = dump_responses(responses)
    response_bytes = response_text.encode("utf-8")

    def should_replace_response():
        if existing_output_mode(response_path, stat.S_ISREG) is None:
            return True
        try:
            if response_path.read_bytes() == response_bytes:
                return False
        except OSError:
            pass  # Let the provenance check handle unreadable files.
        if not args.force and protected(HERE):
            raise SystemExit(protected_message)
        return True

    replaced = write_text(response_path, response_text, should_replace=should_replace_response)
    response_status = (
        f"{len(responses)} responses" if replaced else f"kept {len(responses)} responses"
    )
    print(f"wrote {len(inputs)} screenshots, {len(labels)} labels, {response_status}")


if __name__ == "__main__":
    main()
