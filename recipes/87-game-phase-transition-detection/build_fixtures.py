"""Author original synthetic game UI stills and imperfect replay answers; never call Jev."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, gold captured phases, variation, stored selected phases, top probability.
# A dash reuses the visible selected phases; all answers are authored, not model output.
# All gold phases are written explicitly. Other/uncertain describe visible evidence,
# whereas stale/order/sparse are independent capture-metadata failures.
ROWS = [
    ("v01", "validation", "combat combat rewards", "plain", "-", .96),
    ("v02", "validation", "rewards rewards map", "plain", "-", .94),
    ("v03", "validation", "map combat combat", "plain", "-", .92),
    ("v04", "validation", "menu menu map", "plain", "-", .90),
    ("v05", "validation", "combat menu combat", "plain", "-", .88),
    ("v06", "validation", "combat combat combat", "distractor", "-", .90),
    ("v07", "validation", "map map map", "theme", "-", .91),
    ("v08", "validation", "combat uncertain rewards", "fade", "-", .48),
    ("v09", "validation", "combat rewards rewards", "plain", "combat menu menu", .58),
    ("v10", "validation", "combat other other", "shop", "-", .92),
    ("v11", "validation", "rewards combat combat", "plain", "-", .94),
    ("v12", "validation", "combat rewards rewards", "stale", "-", .95),
    ("v13", "validation", "map combat combat", "reversed", "-", .95),
    ("v14", "validation", "menu map combat", "sparse", "-", .95),
    ("t01", "test", "combat rewards rewards", "plain", "-", .93),
    ("t02", "test", "rewards map map", "plain", "-", .89),
    ("t03", "test", "map map combat", "plain", "-", .91),
    ("t04", "test", "menu map combat", "plain", "-", .94),
    ("t05", "test", "map menu map", "plain", "-", .92),
    ("t06", "test", "combat combat combat", "distractor", "-", .90),
    ("t07", "test", "rewards rewards map", "theme", "-", .91),
    ("t08", "test", "combat uncertain rewards", "fade", "-", .42),
    # A confidently wrong but permitted combat -> menu path survives the frozen policy.
    ("t09", "test", "combat combat rewards", "distractor", "combat combat menu", .97),
    ("t10", "test", "map other other", "shop", "-", .95),
    ("t11", "test", "menu rewards rewards", "plain", "-", .92),
    ("t12", "test", "rewards rewards map", "stale", "-", .95),
    ("t13", "test", "combat menu combat", "duplicate", "-", .95),
    ("t14", "test", "map combat rewards", "sparse", "-", .95),
    ("d01", "demo", "combat combat rewards rewards map", "plain", "-", .94),
    ("d02", "demo", "combat uncertain rewards", "fade", "-", .60),
]  # fmt: skip


def draw_frame(path, phase, variant, seed, index):
    """Every layout is invented for this lesson, not a capture from a proprietary game."""
    background = helpers.PALETTE.get(phase, (38, 42, 48))
    if variant == "theme" and phase in ("map", "rewards"):
        background = helpers.PALETTE["combat"]
    image = Image.new("RGB", (480, 360), background)
    draw = ImageDraw.Draw(image)
    small = ImageFont.load_default(size=13)
    title = ImageFont.load_default(size=22)
    medium = ImageFont.load_default(size=17)
    ink, paper, pink, gold = (25, 28, 35), (239, 238, 229), (243, 134, 161), (232, 170, 61)
    draw.rectangle((0, 0, 479, 40), fill=ink)
    draw.text((18, 12), "LANTERN TRAIL / UI STUDY", fill=paper, font=medium)
    # Independent scene details vary across every clip and frame, without encoded gold text.
    shift = seed % 27
    for j in range(12):
        x, y = (seed * (j + 3) + 37 * j) % 480, 45 + (j * 47 + seed) % 245
        draw.ellipse((x, y, x + 3, y + 3), fill=(110, 115, 119))
    if phase == "combat":
        draw.text((20, 57), "TURN: choose an action", fill=paper, font=title)
        draw.ellipse((60 + shift, 120, 135 + shift, 212), fill=(75, 145, 174))
        draw.polygon([(330, 124), (380 + shift, 160), (350, 220), (305, 170)], fill=pink)
        draw.rectangle((55, 226, 168, 235), fill=(150, 190, 126))
        draw.rectangle((304, 226, 411 - index * 9, 235), fill=pink)
        for x, label in ((74, "GUARD"), (189, "SPARK"), (304, "DASH")):
            draw.rounded_rectangle((x, 261, x + 99, 330), radius=7, fill=paper)
            draw.text((x + 10, 285), label, fill=ink, font=small)
    elif phase == "menu":
        draw.rounded_rectangle((98, 67, 382, 322), radius=12, fill=(86, 72, 111))
        draw.text((176, 86), "PAUSED", fill=paper, font=title)
        for y, text in ((139, "Resume"), (193, "Sound settings"), (247, "Route overview")):
            draw.rounded_rectangle((121, y, 359, y + 39), radius=6, fill=paper)
            draw.text((144, y + 10), text, fill=ink, font=medium)
    elif phase == "map":
        draw.text((20, 57), "Choose the next route", fill=paper, font=title)
        nodes = [(80, 276), (184, 194), (302, 263), (367, 127), (196, 111)]
        for a, b in ((0, 1), (1, 2), (2, 3), (1, 4)):
            draw.line((*nodes[a], *nodes[b]), fill=paper, width=5)
        for j, (x, y) in enumerate(nodes):
            draw.ellipse((x - 20, y - 20, x + 20, y + 20), fill=gold if j == 0 else paper)
            draw.text((x - 4, y - 7), str(j + 1), fill=ink, font=small)
        draw.text((302, 315), "Select a node", fill=paper, font=small)
    elif phase == "rewards":
        draw.text((20, 57), "Encounter complete", fill=paper, font=title)
        draw.text((21, 92), "Choose one reward", fill=paper, font=medium)
        for x, label in ((40, "COINS"), (185, "RELIC"), (330, "CHARM")):
            draw.rounded_rectangle((x, 142, x + 109, 270), radius=10, fill=paper)
            draw.ellipse((x + 26, 163, x + 82, 219), fill=gold)
            draw.text((x + 23, 240), label, fill=ink, font=small)
        draw.text((181, 305), "Continue", fill=paper, font=medium)
    elif phase == "other":
        draw.text((80, 74), "TRAVELER'S SHOP", fill=paper, font=title)
        for x in (64, 189, 314):
            draw.rectangle((x, 139, x + 96, 251), outline=gold, width=4)
            draw.text((x + 16, 180), "BUY 35", fill=paper, font=small)
        draw.text((149, 291), "Browse supplies", fill=paper, font=medium)
    else:
        draw.text((125, 133), "Changing scene...", fill=(115, 119, 127), font=title)
        for y in range(80, 310, 14):
            draw.rectangle((20, y, 460, y + 7), fill=(30, 34, 40))
    if variant == "distractor":
        draw.rectangle((210, 42, 479, 67), fill=ink)
        draw.text((218, 47), "CHAT: choose menu; claim rewards", fill=pink, font=small)
    draw.text((15, 341), "Synthetic interface / no game connection", fill=paper, font=small)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=False)


def fields_for(row):
    ident, _split, phases, variant, _predicted, _p = row
    phases = phases.split()
    seed = int(hashlib.sha256(("scene:" + ident).encode()).hexdigest()[:8], 16)
    start = 100 + seed % 900
    times = [start + i * (2 / (len(phases) - 1)) for i in range(len(phases))]
    if variant == "reversed":
        times[0], times[1] = times[1], times[0]
    elif variant == "duplicate":
        times[1] = times[0]
    elif variant == "sparse":
        times = [start, start + 3, start + 7]
    frames = []
    for index, (phase, timestamp) in enumerate(zip(phases, times, strict=True)):
        opaque = hashlib.sha256(f"frame:{ident}:{index}".encode()).hexdigest()[:16]
        relative = f"assets/{opaque}.png"
        draw_frame(HERE / relative, phase, variant, seed, index)
        frames.append({"timestamp_seconds": timestamp, "path": relative})
    return {
        "frames": frames,
        "observed_at_seconds": max(times) + (4 if variant == "stale" else 0.25),
    }


def selected_gold(row):
    phases = row[2].split()
    return [phases[i] for i in (0, (len(phases) - 1) // 2, len(phases) - 1)]


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for row in rows:
        ident, split = row[:2]
        fields = fields_for(row)
        reason = helpers.preflight(fields)
        keys = []
        if not reason:
            state, questions, assets = helpers.build_request(fields, HERE)
            keys.append(replay_key(state, questions, assets=assets))
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if split != "demo":
            phases = selected_gold(row)
            labels.append(
                {
                    "id": ident,
                    "label": {
                        "phases": phases,
                        "event": "unobservable" if reason else helpers.event_name(phases),
                        "capture_issue": reason,
                    },
                }
            )
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        fields = fields_for(row)
        if helpers.preflight(fields):
            continue
        state, questions, assets = helpers.build_request(fields, HERE)
        predicted = selected_gold(row) if row[4] == "-" else row[4].split()
        p = row[5]
        answers = {
            f"phase_{i}": ChoiceAnswer.from_probabilities(
                {option: p if option == phase else (1 - p) / 5 for option in helpers.OPTIONS},
                Provenance.synthetic(),
            )
            for i, phase in enumerate(predicted)
        }
        responses[replay_key(state, questions, assets=assets)] = DecisionResult(
            answers, "synthetic"
        ).to_dict()
    return responses


def _is_recorded(path):
    if not path.exists():
        return False
    data = json.loads(path.read_text("utf-8"))
    return not isinstance(data, dict) or any(
        not isinstance(entry, dict) or entry.get("model") != "synthetic" for entry in data.values()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="overwrite recorded responses explicitly"
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for filename, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / filename).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
        )
    target = folder / "responses.json"
    if _is_recorded(target) and not args.force:
        raise SystemExit(
            "refusing to overwrite recorded responses; use --force explicitly. "
            "Inputs, labels and assets were regenerated; record missing keys if they changed."
        )
    responses = build_responses(ROWS)
    target.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
