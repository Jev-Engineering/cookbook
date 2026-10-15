"""Author synthetic pixels and deliberately imperfect replay answers. Never calls an API."""

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

from jev_cookbook import (
    BoxAnswer,
    ChoiceAnswer,
    DecisionResult,
    Provenance,
    load_helpers,
    replay_key,
)

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
SIZE = (1024, 768)

# Gold and answer specifications live only in this generator and labels.jsonl.
# Neutral filenames ensure neither test status nor target location enters a request.
ROWS = [
    ("v01", "validation", (216, 126, 240, 150), "clear"),
    ("v02", "validation", (503, 375, 527, 399), "seam"),
    ("v03", "validation", (997, 740, 1021, 764), "edge"),
    ("v04", "validation", None, "absent"),
    ("v05", "validation", (310, 260, 334, 284), "ambiguous"),
    ("v06", "validation", (716, 510, 740, 534), "bad_box"),
    ("v07", "validation", (820, 200, 844, 224), "wrong_tile"),
    ("v08", "validation", (420, 624, 444, 648), "low_right"),
    ("v09", "validation", (108, 504, 132, 528), "low_wrong"),
    ("v10", "validation", (690, 100, 714, 124), "missing_confidence"),
    ("t01", "test", (280, 150, 304, 174), "clear"),
    ("t02", "test", (500, 379, 524, 403), "seam"),
    ("t03", "test", (1, 739, 25, 763), "edge"),
    ("t04", "test", None, "absent"),
    ("t05", "test", (650, 300, 674, 324), "ambiguous"),
    ("t06", "test", (780, 610, 804, 634), "bad_box"),
    ("t07", "test", (850, 80, 874, 104), "wrong_tile"),
    ("t08", "test", (300, 540, 324, 564), "low_right"),
    ("t09", "test", (112, 92, 136, 116), "low_wrong"),
    ("t10", "test", (750, 430, 774, 454), "missing_confidence"),
    ("d01", "demo", (507, 377, 531, 401), "seam"),
    ("d02", "demo", None, "absent"),
]


def marker(draw, bounds, kind="target"):
    x, y, right, bottom = bounds
    color = "#F386A1" if kind != "blue" else "#1F78A8"
    rectangle = (x, y, right - 1, bottom - 1)
    if kind == "circle":
        draw.ellipse(rectangle, fill=color, outline="#1E1E1E", width=2)
    else:
        draw.rectangle(rectangle, fill=color, outline="#1E1E1E", width=2)
    if kind in ("target", "blue"):
        cx, cy = (x + right) // 2, (y + bottom) // 2
        draw.line((cx, y + 5, cx, bottom - 6), fill="white", width=3)
        draw.line((x + 5, cy, right - 6, cy), fill="white", width=3)
    elif kind == "diagonal":
        draw.line((x + 4, y + 4, right - 5, bottom - 5), fill="#1E1E1E", width=3)


def scene(index, bounds, kind):
    rng = random.Random(83000 + index)
    image = Image.new("RGB", SIZE, "#FEFEFE")
    draw = ImageDraw.Draw(image)
    for x in range(0, SIZE[0], 64):
        draw.line((x, 0, x, SIZE[1] - 1), fill="#DEDEDE")
    for y in range(0, SIZE[1], 64):
        draw.line((0, y, SIZE[0] - 1, y), fill="#DEDEDE")
    for _ in range(180):
        x, y = rng.randrange(10, 982), rng.randrange(10, 726)
        width, height = rng.randrange(8, 24), rng.randrange(8, 24)
        draw.rectangle((x, y, x + width, y + height), fill=rng.choice(("#A0A0A0", "#D5D5D5")))
    for _ in range(26):
        x, y = rng.randrange(10, 982), rng.randrange(10, 726)
        marker(draw, (x, y, x + 24, y + 24), rng.choice(("blue", "circle", "diagonal")))
    if bounds is not None:
        marker(draw, bounds)
    if kind == "ambiguous":
        marker(draw, (110, 650, 134, 674))
    return image


def normalized(bounds, enclosing=(0, 0, 1024, 768)):
    x, y, right, bottom = bounds
    left, top, end_x, end_y = enclosing
    return {
        "top": (y - top) / (end_y - top),
        "bottom": (bottom - top) / (end_y - top),
        "left": (x - left) / (end_x - left),
        "right": (right - left) / (end_x - left),
    }


def contains(outer, inner):
    return (
        outer[0] <= inner[0] < inner[2] <= outer[2] and outer[1] <= inner[1] < inner[3] <= outer[3]
    )


def choice(question, selected, probability=0.96):
    options = tuple(question.criteria)
    remainder = (1 - probability) / (len(options) - 1)
    return ChoiceAnswer.from_probabilities(
        {option: probability if option == selected else remainder for option in options},
        Provenance.synthetic(),
    )


def request_records(index, row, recipe_dir=None):
    """Yield the same runtime request triples with authored answers, never inferred answers."""
    root_dir = HERE if recipe_dir is None else Path(recipe_dir)
    _, _, bounds, kind = row
    root = helpers.load_view({"image": f"assets/scene-{index:02d}.png"}, root_dir)
    provenance = Provenance.synthetic()

    def entry(request, answer):
        state, questions, assets = request
        name = next(iter(questions))
        return request, DecisionResult({name: answer}, "synthetic")

    for policy in helpers.POLICIES:
        current = root
        wrong_branch = kind in ("wrong_tile", "low_wrong") or (
            kind == "seam" and policy == "compact"
        )
        for depth in range(helpers.MAX_DEPTH):
            views = helpers.split_view(current, policy)
            request = helpers.tile_request(views)
            question = request[1]["tile"]
            if kind in ("absent", "ambiguous"):
                selected = "none" if kind == "absent" else "uncertain"
                yield entry(request, choice(question, selected))
                break
            correct = next((i for i, view in enumerate(views) if contains(view.bounds, bounds)), 0)
            wrong_depth = 1 if kind == "seam" else 0
            chosen = (
                next(i for i, view in enumerate(views) if not contains(view.bounds, bounds))
                if wrong_branch and depth == wrong_depth
                else correct
            )
            probability = 0.72 if kind == "low_right" else 0.68 if kind == "low_wrong" else 0.96
            yield entry(request, choice(question, f"tile_{chosen}", probability))
            current = views[chosen]
        else:
            box = (
                {"top": 0.12, "bottom": 0.18, "left": 0.12, "right": 0.18}
                if wrong_branch or kind == "bad_box"
                else normalized(bounds, current.bounds)
            )
            confidence = None if kind == "missing_confidence" else 0.86 if kind == "edge" else 0.95
            yield entry(
                helpers.box_request(current),
                BoxAnswer(box=box, confidence=confidence, provenance=provenance),
            )

    request = helpers.presence_request(root)
    selected = "none" if kind == "absent" else "uncertain" if kind == "ambiguous" else "present"
    probability = 0.73 if kind == "low_right" else 0.70 if kind == "low_wrong" else 0.97
    yield entry(request, choice(request[1]["presence"], selected, probability))
    if selected == "present":
        incorrect = kind in ("seam", "bad_box", "wrong_tile", "low_wrong")
        predicted = (bounds[0] - 16, bounds[1], bounds[2] - 16, bounds[3]) if incorrect else bounds
        confidence = None if kind == "missing_confidence" else 0.86 if kind == "edge" else 0.95
        yield entry(
            helpers.box_request(root),
            BoxAnswer(box=normalized(predicted), confidence=confidence, provenance=provenance),
        )


def build_inputs_and_labels(rows, recipe_dir=None):
    inputs, labels = [], []
    for index, row in enumerate(rows, start=1):
        ident, split, bounds, kind = row
        keys = [
            replay_key(request[0], request[1], assets=request[2])
            for request, _ in request_records(index, row, recipe_dir)
        ]
        inputs.append(
            {
                "id": ident,
                "split": split,
                "fields": {"image": f"assets/scene-{index:02d}.png"},
                "replay_keys": list(dict.fromkeys(keys)),
            }
        )
        if split != "demo":
            status = (
                "absent" if kind == "absent" else "review" if kind == "ambiguous" else "present"
            )
            labels.append(
                {
                    "id": ident,
                    "label": {
                        "status": status,
                        "box": normalized(bounds) if status == "present" else None,
                    },
                }
            )
    return inputs, labels


def build_responses(rows, recipe_dir=None):
    responses = {}
    for index, row in enumerate(rows, start=1):
        for request, result in request_records(index, row, recipe_dir):
            key = replay_key(request[0], request[1], assets=request[2])
            payload = result.to_dict()
            if key in responses and responses[key] != payload:
                raise ValueError("identical image request has conflicting authored answers")
            responses[key] = payload
    return responses


def is_recorded(path):
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
    parser.add_argument("--force", action="store_true", help="replace recorded response fixtures")
    args = parser.parse_args()
    (HERE / "assets").mkdir(exist_ok=True)
    for index, (_, _, bounds, kind) in enumerate(ROWS, start=1):
        scene(index, bounds, kind).save(HERE / "assets" / f"scene-{index:02d}.png")
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, records in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text(
            "".join(json.dumps(row) + "\n" for row in records), encoding="utf-8", newline="\n"
        )
    path = folder / "responses.json"
    if is_recorded(path) and not args.force:
        raise SystemExit("refusing to overwrite recorded responses; use --force deliberately")
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"Wrote {len(inputs)} scenes, {len(labels)} labels, {len(responses)} synthetic responses."
    )


if __name__ == "__main__":
    main()
