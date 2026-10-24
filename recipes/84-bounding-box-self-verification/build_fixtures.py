"""Author synthetic drawings, labels and deliberately imperfect dependent response traces.

Only this authoring script knows scene geometry. Inference receives image bytes, a fixed target
statement and its own candidate coordinates. No live calls are made by this generator.
"""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import BoxAnswer, DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, position, visual variant, initial box shape, answer behavior, box confidence.
# Every held-out composition has independently authored position, clutter and geometry.
ROWS = [
    ("v01", "validation", (92, 62), "pink", "bottom", "honest", .91),
    ("v02", "validation", (170, 70), "pink", "left", "honest", .88),
    ("v03", "validation", (66, 82), "steel", "top", "honest", .86),
    ("v04", "validation", (204, 54), "pink", "right", "honest", .83),
    ("v05", "validation", (120, 103), "pink", "both", "honest", .90),
    ("v06", "validation", (52, 66), "absent", "wrong", "absent", .90),
    ("v07", "validation", (178, 86), "case", "wrong", "absent", .90),
    ("v08", "validation", (101, 75), "pink", "wrong", "false_agreement", .65),
    ("v09", "validation", (60, 95), "double", "full", "ambiguous", .90),
    ("v10", "validation", (159, 61), "pink", "full", "missing", None),
    ("v11", "validation", (86, 91), "pink", "bottom", "uncertain_edge", .90),
    ("v12", "validation", (191, 102), "pink", "full", "reject_crop", .92),
    ("t01", "test", (98, 71), "pink", "bottom", "honest", .91),
    ("t02", "test", (177, 83), "pink", "left", "honest", .89),
    ("t03", "test", (61, 72), "steel", "top", "honest", .86),
    ("t04", "test", (210, 63), "pink", "right", "honest", .90),
    ("t05", "test", (112, 108), "pink", "both", "honest", .90),
    ("t06", "test", (70, 75), "absent", "wrong", "absent", .91),
    ("t07", "test", (166, 91), "case", "wrong", "false_agreement", .97),
    ("t08", "test", (106, 69), "pink", "bottom", "false_agreement", .96),
    ("t09", "test", (67, 103), "double", "full", "ambiguous", .90),
    ("t10", "test", (150, 76), "pink", "full", "missing", None),
    ("t11", "test", (90, 82), "pink", "full", "always_clip", .95),
    ("t12", "test", (183, 95), "pink", "full", "missed_presence", .90),
    ("d01", "demo", (125, 78), "pink", "bottom", "honest", .94),
    ("d02", "demo", (160, 88), "case", "wrong", "absent", .90),
]  # fmt: skip


def normalize(bounds):
    left, top, right, bottom = bounds
    return dict(left=left / 480, top=top / 360, right=right / 480, bottom=bottom / 360)


def gold_box(row):
    _, _, (x, y), variant, *_ = row
    if variant in ("absent", "case", "double"):
        return None
    return normalize((x + 20, y + 20, x + 141, y + 181))


def initial_box(row):
    _, _, (x, y), _, kind, *_ = row
    if kind == "wrong":
        return normalize((350, 85, 415, 247))
    left, top, right, bottom = 18, 18, 143, 183
    if kind == "bottom":
        bottom = 168
    if kind == "left":
        left = 34
    if kind == "top":
        top = 34
    if kind == "right":
        right = 128
    if kind == "both":
        top, bottom = 34, 168
    return normalize((x + left, y + top, x + right, y + bottom))


def _font(size):
    return ImageFont.load_default(size=size)


def draw_scene(row):
    ident, _, (x, y), variant, *_ = row
    image = Image.new("RGB", (480, 360), "#F5F2EA")
    draw = ImageDraw.Draw(image)
    draw.rectangle((14, 14, 465, 345), outline="#6F777B", width=2)
    draw.text((28, 24), "ASSEMBLY BENCH", fill="#1E1E1E", font=_font(20))
    draw.line((28, 55, 450, 55), fill="#AAB2B5", width=2)
    draw.rounded_rectangle((330, 72, 439, 283), radius=10, fill="#DFE6E8")
    draw.text((342, 258), "TOOLS", fill="#3A484C", font=_font(14))
    draw.line((385, 120, 385, 231), fill="#667B86", width=15)
    draw.arc((362, 87, 408, 135), 0, 180, fill="#667B86", width=12)
    draw.line((365, 111, 369, 88), fill="#667B86", width=10)
    draw.line((404, 111, 400, 88), fill="#667B86", width=10)
    # This is a physical bench ruler, not a target label or an answer annotation.
    draw.rectangle((30, 316, 309, 330), fill="#D9C49A")
    for tick in range(35, 307, 14):
        draw.line((tick, 317, tick, 326), fill="#5F584B")
    # Different benign bolts guarantee different source compositions, without printed IDs.
    digest = hashlib.sha256(ident.encode()).digest()
    for j in range(5):
        bx, by = 30 + digest[j] % 270, 285 + digest[j + 5] % 24
        draw.ellipse((bx, by, bx + 7, by + 7), fill="#899296", outline="#394448")

    def clamp(cx, cy, steel=False):
        color = "#6E8B98" if steel else "#E551BA"
        points = [
            (20, 20),
            (130, 20),
            (130, 47),
            (53, 47),
            (53, 125),
            (130, 125),
            (130, 148),
            (20, 148),
        ]
        draw.polygon(
            [(cx + px, cy + py) for px, py in points], fill=color, outline="#28383E", width=3
        )
        draw.rectangle(
            (cx + 102, cy + 99, cx + 114, cy + 180), fill="#71838C", outline="#28383E", width=2
        )
        for ty in range(106, 160, 7):
            draw.line((cx + 102, cy + ty, cx + 114, cy + ty - 3), fill="#28383E", width=2)
        draw.rounded_rectangle(
            (cx + 89, cy + 90, cx + 128, cy + 101),
            radius=3,
            fill="#A6B8C0",
            outline="#28383E",
            width=2,
        )
        draw.rounded_rectangle((cx + 75, cy + 164, cx + 140, cy + 173), radius=4, fill="#28383E")

    if variant == "case":
        draw.rounded_rectangle(
            (120, 129, 285, 239), radius=12, fill="#E551BA", outline="#28383E", width=3
        )
        draw.rectangle((171, 113, 233, 131), outline="#28383E", width=7)
        draw.text((160, 174), "SPARES", font=_font(20), fill="#1E1E1E")
    elif variant == "double":
        clamp(35, 80)
        clamp(180, 86, steel=True)
    elif variant != "absent":
        clamp(x, y, steel=variant == "steel")
    return image


def fields_for(row):
    name = hashlib.sha256(("clamp-scene:" + row[0]).encode()).hexdigest()[:12]
    return {"image": f"assets/scene-{name}.png"}


def build_assets(rows):
    (HERE / "assets").mkdir(exist_ok=True)
    for row in rows:
        draw_scene(row).save(HERE / fields_for(row)["image"], format="PNG")


class AuthoredBackend:
    """Synthetic fixture author only: intentionally wrong answers remain wrong."""

    def __init__(self, row):
        self.row = row
        self.keys = []
        self.responses = {}

    def decide(self, state, questions, *, assets):
        behavior = self.row[5]
        provenance = Provenance.synthetic()
        if "present" in questions:
            p = 0.98
            if behavior in ("absent", "missed_presence"):
                p = 0.02
            unique = 0.02 if behavior == "ambiguous" else p
            answers = {
                "present": NoulAnswer(p, provenance),
                "unique": NoulAnswer(unique, provenance),
            }
        elif "target" in questions:
            answers = {"target": BoxAnswer(initial_box(self.row), self.row[6], provenance)}
        elif "left" in questions:
            candidate, gold = state["candidate"], gold_box(self.row)
            decisions = {edge: False for edge in helpers.EDGES}
            if gold is not None and behavior not in ("false_agreement", "always_clip"):
                decisions = {
                    edge: candidate[edge] > gold[edge]
                    if edge in ("left", "top")
                    else candidate[edge] < gold[edge]
                    for edge in helpers.EDGES
                }
            if behavior == "always_clip":
                decisions["bottom"] = True
            answers = {
                edge: NoulAnswer(0.98 if yes else 0.02, provenance)
                for edge, yes in decisions.items()
            }
            if behavior == "uncertain_edge":
                answers["bottom"] = NoulAnswer(0.67, provenance)
        else:
            answers = {
                "identity": NoulAnswer(0.98, provenance),
                "complete": NoulAnswer(0.02 if behavior == "reject_crop" else 0.98, provenance),
            }
        result = DecisionResult(answers, "synthetic")
        key = replay_key(state, questions, assets=assets)
        self.keys.append(key)
        self.responses[key] = result.to_dict()
        return result


def build_all(rows):
    """Validation alone chooses the threshold; write exactly the paths the notebook uses."""
    build_assets(rows)
    inputs, labels, responses = [], [], {}
    validation_results, eligible = [], []
    for row in rows:
        if row[1] != "validation":
            continue
        backend = AuthoredBackend(row)
        outcome = helpers.run(fields_for(row), backend, helpers.EXPLORATION_FLOOR, HERE)
        validation_results.append((row, backend))
        if outcome.outcome != helpers.REVIEW:
            eligible.append((row, outcome))
    from jev_cookbook.evaluation import select_confidence_threshold

    threshold = select_confidence_threshold(
        [helpers.correct(outcome, {"box": gold_box(row)}) for row, outcome in eligible],
        [outcome.confidence for _, outcome in eligible],
        target_accuracy=1.0,
    )
    val_backends = {row[0]: backend for row, backend in validation_results}
    for row in rows:
        ident, split = row[:2]
        backend = val_backends.get(ident)
        if backend is None:
            backend = AuthoredBackend(row)
            helpers.run(
                fields_for(row),
                backend,
                threshold if split == "test" else helpers.EXPLORATION_FLOOR,
                HERE,
            )
        inputs.append(
            {"id": ident, "split": split, "fields": fields_for(row), "replay_keys": backend.keys}
        )
        if split != "demo":
            labels.append(
                {
                    "id": ident,
                    "label": {
                        "box": gold_box(row),
                        "ambiguous": row[3] == "double",
                        "case": f"{row[3]} scene; initial {row[4]}; authored {row[5]} response",
                    },
                }
            )
        responses.update(backend.responses)
    return inputs, labels, responses


def build_inputs_and_labels(rows):
    inputs, labels, _ = build_all(rows)
    return inputs, labels


def build_responses(rows):
    return build_all(rows)[2]


def _is_recorded(path):
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
    except (ValueError, OSError):
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
    inputs, labels, responses = build_all(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
        )
    path = folder / "responses.json"
    if _is_recorded(path) and not args.force:
        raise SystemExit(
            "refusing to overwrite recorded responses; use --force; inputs and labels were regenerated"
        )
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
