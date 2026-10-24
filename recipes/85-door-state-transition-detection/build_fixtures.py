"""Authored synthetic door frames and intentionally imperfect replay answers; no inference."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, panel openness per frame, visual nuisance, gold, synthetic winner, top probability.
# These drawing parameters never enter inference state or baseline inputs.
ROWS = [
    ("v01", "validation", (0, .5, 1), "clear", "opened", "opened", .94),
    ("v02", "validation", (1, .5, 0), "clear", "closed", "closed", .92),
    ("v03", "validation", (0, 0, 0), "light", "unchanged", "unchanged", .88),
    ("v04", "validation", (1, 1, 1), "shift", "unchanged", "unchanged", .86),
    ("v05", "validation", (0, 0, 0), "clear", "unchanged", "unchanged", .90),
    ("v06", "validation", (0, .5, 1), "dim", "opened", "opened", .81),
    ("v07", "validation", (0, .5, 1), "occluded", "uncertain", "uncertain", .95),
    ("v08", "validation", (0, 0, 0), "absent", "uncertain", "uncertain", .91),
    ("v09", "validation", (0, .5, 1), "partial", "uncertain", "uncertain", .84),
    ("v10", "validation", (0, 0, 0), "outside", "unchanged", "opened", .60),
    ("v11", "validation", (1, .5, 0), "covered_last", "uncertain", "closed", .63),
    ("v12", "validation", (1, .5, 0), "shift", "closed", "closed", .80),
    ("t01", "test", (0, .5, 1), "clear", "opened", "opened", .94),
    ("t02", "test", (1, .5, 0), "clear", "closed", "closed", .92),
    ("t03", "test", (0, 0, 0), "dim", "unchanged", "unchanged", .91),
    ("t04", "test", (1, 1, 1), "shift", "unchanged", "unchanged", .89),
    ("t05", "test", (0, 0, 0), "large_shift", "unchanged", "unchanged", .88),
    ("t06", "test", (0, .5, 1), "occluded", "uncertain", "uncertain", .96),
    ("t07", "test", (0, 0, 0), "absent", "uncertain", "uncertain", .92),
    ("t08", "test", (0, .5, 1), "partial", "uncertain", "opened", .58),
    ("t09", "test", (0, 1, 0), "clear", "uncertain", "uncertain", .91),
    ("t10", "test", (0, 0, 0), "shadow", "unchanged", "opened", .97),
    ("t11", "test", (0, .3, .7), "clear", "opened", "opened", .84),
    ("t12", "test", (0, 0, 0), "outside", "unchanged", "unchanged", .68),
    ("d01", "demo", (0, 1, 0, 1, 0), "clear", None, "unchanged", .93),
    ("d02", "demo", (0, .5, 1), "reversed", None, "opened", .99),
]  # fmt: skip


def draw_frame(openness, nuisance, frame_index, variant):
    """Draw a hinged panel and dark doorway; every sequence has its own scene geometry."""
    wall = (215 + variant % 12, 219 - variant % 13, 224 - variant % 17)
    image = Image.new("RGB", (400, 320), wall)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 290, 399, 319), fill=(155, 155, 160))
    draw.line((0, 289, 399, 289), fill=(80, 80, 85), width=3)
    draw.rectangle((25, 45, 85, 110), fill=(248, 246, 230), outline=(85, 88, 94), width=3)
    draw.line((36, 66 + variant % 7, 74, 66 + variant % 7), fill=(80, 90, 100), width=3)
    draw.rectangle((306, 218, 351, 287), fill=(97, 116, 133))
    shift = 0
    if nuisance in ("shift", "large_shift"):
        shift = frame_index * (5 if nuisance == "shift" else 18)
    if nuisance == "partial":
        shift = 200
    left, top, right, bottom = 132 + shift, 48, 278 + shift, 290
    if nuisance != "absent":
        draw.rectangle((left - 8, top - 8, right + 8, bottom), fill=(75, 76, 81))
        draw.rectangle((left, top, right, bottom), fill=(27, 32, 39))
        width = int((right - left) * (1 - 0.76 * openness))
        brown = (152 + variant % 16, 104 + variant % 9, 69 + variant % 8)
        draw.polygon(
            [
                (left, top),
                (left + width, top + int(openness * 24)),
                (left + width, bottom - int(openness * 14)),
                (left, bottom),
            ],
            fill=brown,
            outline=(60, 43, 33),
            width=3,
        )
        if width > 35:
            draw.rectangle(
                (left + 12, top + 25, left + width - 12, bottom - 30),
                outline=(114, 75, 48),
                width=3,
            )
        x = left + width - 14
        draw.ellipse((x - 4, 164, x + 4, 172), fill=(236, 209, 121))
    if nuisance == "outside":
        draw.rectangle((25 + frame_index * 20, 170, 42 + frame_index * 20, 280), fill=(44, 86, 116))
    if nuisance == "occluded" or (nuisance == "covered_last" and frame_index == 2):
        draw.rectangle((113, 30, 295, 294), fill=(108, 130, 148))
        draw.line((119, 40, 289, 280), fill=(157, 176, 189), width=8)
    if nuisance == "shadow" and frame_index > 0:
        shadow_bounds = (194, 48, 278, 290)
        shaded = ImageEnhance.Brightness(image.crop(shadow_bounds)).enhance(0.43)
        image.paste(shaded, shadow_bounds)
    if nuisance in ("light", "dim"):
        factor = (
            (1.0, 1.15, 1.3)[frame_index] if nuisance == "light" else (1.0, 0.62, 0.40)[frame_index]
        )
        image = ImageEnhance.Brightness(image).enhance(factor)
    return image


def fields_for(row):
    ident, _split, positions, nuisance, *_ = row
    times = [8.0 + i * 0.7 for i in range(len(positions))]
    if nuisance == "reversed":
        times = list(reversed(times))
    return {
        "frames": [
            {"timestamp_seconds": t, "path": f"assets/{ident}-{i}.png"} for i, t in enumerate(times)
        ]
    }


def build_assets(rows):
    folder = HERE / "assets"
    folder.mkdir(exist_ok=True)
    for variant, row in enumerate(rows):
        ident, _split, positions, nuisance, *_ = row
        for i, openness in enumerate(positions):
            draw_frame(openness, nuisance, i, variant).save(folder / f"{ident}-{i}.png")


def build_inputs_and_labels(rows):
    build_assets(rows)
    inputs, labels = [], []
    for row in rows:
        ident, split, _positions, _nuisance, gold, *_ = row
        fields = fields_for(row)
        keys = []
        if helpers.preflight_reason(fields) is None:
            state, questions, assets = helpers.build_request(fields, HERE)
            keys.append(replay_key(state, questions, assets=assets))
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if gold is not None:
            labels.append({"id": ident, "label": gold})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        fields = fields_for(row)
        if helpers.preflight_reason(fields) is not None:
            continue
        state, questions, assets = helpers.build_request(fields, HERE)
        winner, top = row[-2:]
        probabilities = {
            option: top if option == winner else (1 - top) / 3 for option in helpers.OPTIONS
        }
        answer = ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())
        key = replay_key(state, questions, assets=assets)
        responses[key] = DecisionResult({"transition": answer}, "synthetic").to_dict()
    return responses


def _is_recorded(path: Path) -> bool:
    """True if ``path`` exists and holds at least one response whose model is not
    ``"synthetic"`` (a recorded, or otherwise real, answer). A file that fails to parse, or
    whose top level is not a JSON object, cannot hold a valid synthetic response either, so it
    is treated as not recorded rather than raising; inside an object, an entry that is itself
    not an object is treated as if it were recorded, so it blocks an overwrite instead of being
    silently skipped."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return any(
        not isinstance(entry, dict) or entry.get("model") != "synthetic" for entry in data.values()
    )


def _unresolved_keys(inputs, responses_file: Path) -> list[str]:
    """Replay keys the just-rewritten ``inputs`` ask for that ``responses_file`` does not have,
    used only to warn when a ROWS edit has desynchronised the two."""
    if not responses_file.exists():
        return []
    try:
        data = json.loads(responses_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    return [key for row in inputs for key in row["replay_keys"] if key not in data]


def main() -> None:
    parser = argparse.ArgumentParser(description="Write this recipe's fixtures/.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite responses.json even if it holds a recorded (non-synthetic) answer",
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\n" for row in rows)
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    responses_file = folder / "responses.json"
    if _is_recorded(responses_file) and not args.force:
        message = (
            f"refusing to overwrite {responses_file}: it holds a recorded response "
            "(pass --force to overwrite it anyway)"
        )
        if _unresolved_keys(inputs, responses_file):
            message += (
                "\ninputs.jsonl and labels.jsonl above were rewritten from ROWS; "
                "responses.json was not, and at least one of the keys the rewritten inputs "
                "ask for is missing from it. The three files are desynchronised until you "
                "--force a rewrite or record the missing answers."
            )
        raise SystemExit(message)
    responses = build_responses(ROWS)
    # The same serialization jev_cookbook.live._dump writes: only the top-level keys are
    # sorted; each response keeps the field order DecisionResult.to_dict() emits. Matching the
    # recorder exactly, rather than json.dumps(..., sort_keys=True) (which also sorts every
    # nested dict alphabetically), keeps a recording's diff to the values that actually changed.
    text = json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n"
    responses_file.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
