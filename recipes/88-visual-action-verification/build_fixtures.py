"""Generate tiny synthetic UI screenshots and explicitly authored replay answers."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, intent, rendered states, gold outcome, postcondition p, initially_absent p.
# These render instructions and labels never enter inference state.
ROWS = [
    ("d01", "demo", "open_export", ("base", "dialog"), None, 0.98, 0.97),
    ("d02", "demo", "open_export", ("base", "banner"), None, 0.04, 0.98),
    ("v01", "validation", "open_export", ("base", "dialog"), "success", 0.97, 0.98),
    ("v02", "validation", "save_notifications", ("off", "saved"), "success", 0.95, 0.97),
    ("v03", "validation", "open_export", ("base", "base"), "not_observed", 0.03, 0.98),
    ("v04", "validation", "open_export", ("base", "banner"), "not_observed", 0.07, 0.97),
    ("v05", "validation", "save_notifications", ("off", "loading", "saved"), "success", 0.94, 0.96),
    ("v06", "validation", "save_notifications", ("off", "loading"), "not_observed", 0.52, 0.97),
    ("v07", "validation", "open_export", ("base", "covered"), "review", 0.49, 0.95),
    ("v08", "validation", "open_export", ("base",), "review", None, None),
    ("v09", "validation", "open_export", ("base", "dialog"), "review", None, None),
    ("v10", "validation", "open_export", ("dialog", "dialog"), "review", 0.98, 0.02),
    ("v11", "validation", "save_notifications", ("off", "saved"), "success", 0.42, 0.95),
    ("t01", "test", "open_export", ("base", "dialog"), "success", 0.96, 0.96),
    ("t02", "test", "save_notifications", ("off", "saved"), "success", 0.94, 0.97),
    ("t03", "test", "open_export", ("base", "base"), "not_observed", 0.04, 0.98),
    ("t04", "test", "open_export", ("base", "banner"), "not_observed", 0.03, 0.97),
    ("t05", "test", "save_notifications", ("off", "loading", "saved"), "success", 0.92, 0.95),
    ("t06", "test", "save_notifications", ("off", "loading"), "not_observed", 0.55, 0.96),
    ("t07", "test", "open_export", ("base", "covered"), "review", 0.48, 0.96),
    ("t08", "test", "save_notifications", ("off",), "review", None, None),
    ("t09", "test", "open_export", ("base", "dialog"), "review", None, None),
    ("t10", "test", "open_export", ("dialog", "dialog"), "review", 0.97, 0.04),
    ("t11", "test", "save_notifications", ("off", "unsaved"), "not_observed", 0.93, 0.96),
]  # fmt: skip


def screenshot(kind, board, variant):
    """A complete invented 512x384 app surface; no image generator or real account data."""
    image = Image.new("RGB", (512, 384), "#FEFEFE")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=15)
    large = ImageFont.load_default(size=23)
    ink = "#1E1E1E"
    draw.rectangle((0, 0, 511, 49), fill=ink)
    draw.text((22, 13), "PAPER DESK", fill="#FEFEFE", font=large)
    draw.text((340, 18), f"Workspace {board}", fill="#FEFEFE", font=small)
    draw.text(
        (24, 66),
        "Reports" if kind in {"base", "dialog", "banner", "covered"} else "Settings",
        fill=ink,
        font=large,
    )
    # Test screens move the content and use distinct visible report text.
    y = 112 + variant * 8
    if kind in {"base", "dialog", "banner", "covered"}:
        draw.rounded_rectangle((24, y, 487, y + 132), radius=8, fill="#F2F2F2")
        draw.text(
            (40, y + 18),
            "Quarterly summary" if variant else "Monthly overview",
            fill=ink,
            font=font,
        )
        draw.text((40, y + 51), "Your report is ready to preview.", fill=ink, font=small)
        draw.rounded_rectangle((38, y + 82, 239, y + 116), radius=6, fill="#F386A1")
        draw.text((52, y + 89), "Export report", fill=ink, font=font)
        if kind == "banner":
            draw.rectangle((24, 286, 487, 348), fill="#DEDEDE")
            draw.text((40, 306), "New help article available", fill=ink, font=font)
        if kind == "dialog":
            draw.rectangle((64, 88, 447, 314), fill="#FEFEFE", outline=ink, width=3)
            draw.text((88, 113), "Export report", fill=ink, font=large)
            draw.text((88, 164), "Choose a format", fill=ink, font=font)
            draw.rounded_rectangle((88, 198, 420, 237), radius=5, outline="#777777", width=2)
            draw.text((102, 206), "PDF document", fill=ink, font=font)
            draw.rounded_rectangle((280, 261, 421, 298), radius=5, fill="#F386A1")
            draw.text((302, 270), "Continue", fill=ink, font=font)
        if kind == "covered":
            draw.rectangle((42, 93, 469, 325), fill="#DEDEDE", outline="#777777", width=2)
            draw.text((87, 194), "Preview unavailable", fill=ink, font=large)
    else:
        draw.rounded_rectangle((24, y, 487, y + 192), radius=8, fill="#F2F2F2")
        draw.text((40, y + 19), "Notifications", fill=ink, font=large)
        on = kind != "off"
        draw.rounded_rectangle(
            (357, y + 16, 456, y + 53), radius=18, fill="#F386A1" if on else "#DEDEDE"
        )
        draw.ellipse(
            (416 if on else 361, y + 20, 450 if on else 395, y + 49), fill="#FEFEFE", outline=ink
        )
        draw.text((41, y + 70), "Enabled" if on else "Disabled", fill=ink, font=font)
        text = {
            "off": "Saved: disabled",
            "saved": "Saved: enabled",
            "loading": "Saving...",
            "unsaved": "Unsaved changes",
        }[kind]
        draw.text((41, y + 105), text, fill=ink, font=font)
        draw.rounded_rectangle((350, y + 143, 460, y + 178), radius=5, fill="#F386A1")
        draw.text((382, y + 151), "Save", fill=ink, font=font)
    draw.text((24, 359), "Synthetic interface - no browser is connected", fill=ink, font=small)
    return image


def fields_for(row, index):
    ident, split, intent, scenes, _gold, _post, _initial = row
    frames = [
        {
            "asset": f"assets/frame-{index:02d}-{position:02d}.png",
            "timestamp_ms": 900 if position == 0 else 1200 + position * 300,
            "phase": "before" if position == 0 else "after",
        }
        for position in range(len(scenes))
    ]
    if ident in {"v09", "t09"}:
        frames.reverse()
    return {"intent": intent, "action_timestamp_ms": 1000, "frames": frames}


def build_assets(rows, directory=HERE):
    folder = Path(directory) / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows):
        for position, scene in enumerate(row[3]):
            image = screenshot(scene, index + 1, int(row[1] == "test"))
            image.save(folder / f"frame-{index:02d}-{position:02d}.png", optimize=False)


def build_inputs_and_labels(rows, directory=HERE):
    inputs, labels = [], []
    for index, row in enumerate(rows):
        ident, split, _intent, _scenes, gold, _post, _initial = row
        fields = fields_for(row, index)
        keys = []
        if helpers.frame_problem(fields, directory) is None:
            state, questions, assets = helpers.build_request(fields, directory)
            keys = [replay_key(state, questions, assets=assets)]
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if gold is not None:
            labels.append({"id": ident, "label": gold})
    return inputs, labels


def build_responses(rows, directory=HERE):
    responses = {}
    for index, row in enumerate(rows):
        fields = fields_for(row, index)
        if helpers.frame_problem(fields, directory):
            continue
        state, questions, assets = helpers.build_request(fields, directory)
        key = replay_key(state, questions, assets=assets)
        answers = {
            "postcondition": NoulAnswer(row[5], Provenance.synthetic()),
            "initially_absent": NoulAnswer(row[6], Provenance.synthetic()),
        }
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def is_recorded(path):
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
    parser.add_argument("--force", action="store_true", help="replace recorded answers explicitly")
    args = parser.parse_args()
    build_assets(ROWS)
    inputs, labels = build_inputs_and_labels(ROWS)
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text("".join(json.dumps(row) + "\n" for row in rows), "utf-8")
    path = folder / "responses.json"
    if is_recorded(path) and not args.force:
        raise SystemExit(
            "refusing to overwrite recorded responses.json; use --force explicitly. "
            "Inputs, labels and assets were regenerated; record any newly missing keys."
        )
    responses = build_responses(ROWS)
    path.write_text(json.dumps(dict(sorted(responses.items())), indent=2) + "\n", "utf-8")
    print(f"Wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses.")


if __name__ == "__main__":
    main()
