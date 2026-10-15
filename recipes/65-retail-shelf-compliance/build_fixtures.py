"""Author reproducible synthetic shelf drawings, readable gold, and imperfect replay answers.

Only this offline generator knows rendering descriptions and gold labels. Inference gets
opaque image references, pixels, and fixed task context. All drawings are original recipe
assets; none is a photograph or an API result. --force is required over recorded answers.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
C, N, R = "compliant", "noncompliant", "review"
COLORS = {
    "oats": (216, 139, 43),
    "tea": (41, 144, 122),
    "soup": (191, 73, 89),
    "unknown": (128, 85, 182),
}

# id, split, visible groups by zone, counts, variation, per-group gold, synthetic p(yes).
# Different shelf geometry/count/packing is authored independently in each split.
ROWS = [
    ("v01-full", "validation", ("oats", "tea", "soup"), (3, 3, 3), 1, (C,C,C), (.96,.95,.94)),
    ("v02-spaced", "validation", ("oats", "tea", "soup"), (1, 2, 1), 2, (C,C,C), (.91,.90,.93)),
    ("v03-swap", "validation", ("tea", "oats", "soup"), (2, 3, 2), 3, (N,N,C), (.06,.08,.96)),
    ("v04-gap", "validation", ("oats", "empty", "soup"), (3, 0, 2), 4, (C,N,C), (.94,.07,.93)),
    ("v05-restocked", "validation", ("oats", "tea", "soup"), (4, 1, 4), 5, (C,C,C), (.89,.88,.91)),
    ("v06-occluded", "validation", ("oats", "blocked", "soup"), (2, 2, 3), 6, (C,R,C), (.92,.52,.94)),
    ("v07-new-pack", "validation", ("oats-alt", "tea", "soup"), (2, 2, 1), 7, (C,C,C), (.78,.93,.94)),
    ("v08-unknown", "validation", ("oats", "tea", "unknown"), (2, 3, 2), 8, (C,C,N), (.95,.92,.11)),
    ("v09-partial", "validation", ("blocked", "tea", "soup"), (2, 1, 3), 9, (R,C,C), (.61,.91,.92)),
    ("v10-mixed", "validation", ("oats", "tea-mixed", "soup"), (2, 3, 2), 10, (C,N,C), (.94,.72,.95)),
    ("v11-all-empty", "validation", ("empty", "empty", "empty"), (0, 0, 0), 11, (N,N,N), (.05,.08,.04)),
    ("v12-sparse", "validation", ("oats", "tea", "soup"), (1, 1, 2), 12, (C,C,C), (.66,.91,.92)),
    ("t01-full", "test", ("oats", "tea", "soup"), (2, 4, 3), 13, (C,C,C), (.94,.95,.96)),
    ("t02-spaced", "test", ("oats", "tea", "soup"), (1, 3, 1), 14, (C,C,C), (.90,.92,.93)),
    ("t03-swap", "test", ("oats", "soup", "tea"), (3, 2, 4), 15, (C,N,N), (.95,.07,.08)),
    ("t04-gap", "test", ("empty", "tea", "soup"), (0, 3, 1), 16, (N,C,C), (.06,.92,.91)),
    ("t05-restocked", "test", ("oats", "tea", "soup"), (4, 2, 4), 17, (C,C,C), (.92,.93,.90)),
    ("t06-occluded", "test", ("oats", "tea", "blocked"), (2, 1, 2), 18, (C,C,R), (.93,.92,.48)),
    ("t07-new-pack", "test", ("oats", "tea-alt", "soup"), (1, 2, 3), 19, (C,C,C), (.93,.85,.94)),
    ("t08-lookalike", "test", ("unknown-look", "tea", "soup"), (3, 2, 2), 20, (N,C,C), (.96,.94,.92)),
    ("t09-partial", "test", ("oats", "blocked", "soup"), (3, 2, 1), 21, (C,R,C), (.92,.59,.93)),
    ("t10-mixed", "test", ("oats", "tea", "soup-mixed"), (1, 2, 3), 22, (C,C,N), (.92,.94,.18)),
    ("t11-empty-blocked", "test", ("empty", "tea", "blocked"), (0, 3, 2), 23, (N,C,R), (.07,.94,.54)),
    ("t12-sparse", "test", ("oats", "tea", "soup"), (2, 1, 1), 24, (C,C,C), (.91,.67,.92)),
    ("d01-swapped", "demo", ("tea", "oats", "soup"), (3, 2, 1), 25, None, (.04,.09,.96)),
    ("d02-blocked", "demo", ("oats", "blocked", "soup"), (1, 3, 3), 26, None, (.94,.51,.93)),
]  # fmt: skip


def _font(size):
    return ImageFont.load_default(size=size)


def drawing(groups, counts, variation, *, reference=False):
    """A 600 x 400 diagram; title explicitly distinguishes drawings from photographs."""
    image = Image.new("RGB", (600, 400), "#f7f4ee")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 600, 72), fill="#223343")
    title = "APPROVED PLANOGRAM DRAWING" if reference else "SYNTHETIC SHELF DRAWING"
    draw.text((24, 16), title, font=_font(22), fill="white")
    draw.text(
        (24, 46), "Group placement only | package counts may vary", font=_font(14), fill="#d9e5e9"
    )
    for index, (group, count) in enumerate(zip(groups, counts, strict=True)):
        x0, y0, x1, y1 = list(helpers.SLOTS.values())[index]
        draw.text((x0, 84), ("LEFT", "CENTER", "RIGHT")[index], font=_font(14), fill="#394753")
        draw.rectangle((x0, y0, x1, y1), fill="#eeebe4", outline="#b6b6b0", width=1)
        if group != "empty":
            base = group.split("-")[0]
            if group == "blocked":
                base = helpers.GROUPS[index]
            width = min(48, (x1 - x0 - 20) // max(count, 1) - 7)
            for k in range(count):
                x = x0 + 10 + k * ((x1 - x0 - 20) // max(count, 1)) + variation % 4
                height = 111 + ((variation + k * 5) % 28)
                y = y1 - height - 3
                identity = "unknown" if group.endswith("mixed") and k == count - 1 else base
                color = COLORS[identity]
                if group.endswith("alt"):
                    color = (118, 92, 179) if base == "tea" else (43, 124, 181)
                if group == "unknown-look":
                    color = COLORS["oats"]
                draw.rounded_rectangle(
                    (x, y, x + width, y1 - 3), radius=4, fill=color, outline="#4b4b4b", width=1
                )
                draw.rectangle((x + 2, y + 10, x + width - 2, y + 40), fill="#fffdf2")
                label = "???" if identity == "unknown" else identity.upper()
                draw.text((x + 3, y + 20), label, font=_font(10), fill="#24303a")
                if identity == "oats":
                    draw.polygon(
                        ((x + width // 2, y + 56), (x + 7, y + 79), (x + width - 7, y + 79)),
                        fill="#fff0cb",
                    )
                elif identity == "tea":
                    draw.ellipse((x + 8, y + 58, x + width - 8, y + 84), outline="#e4fff3", width=3)
                elif identity == "soup":
                    draw.arc(
                        (x + 7, y + 58, x + width - 7, y + 85), 0, 180, fill="#fff0e5", width=3
                    )
            if group == "blocked":
                draw.rectangle(
                    (x0 + 3, y0 + 20, x1 - 3, y1 - 2), fill="#91989c", outline="#47515a", width=2
                )
                draw.text((x0 + 16, y0 + 77), "CART IN FRONT", font=_font(15), fill="white")
                draw.line((x0 + 10, y0 + 110, x1 - 10, y1 - 10), fill="#b6bec2", width=4)
        draw.rectangle((x0 - 2, y1 + 1, x1 + 2, y1 + 16), fill="#626c73")
    draw.text(
        (24, 343), "Illustrative product groups: OATS / TEA / SOUP", font=_font(17), fill="#24313e"
    )
    draw.text(
        (24, 372),
        "Original synthetic fixture | no inventory action",
        font=_font(13),
        fill="#59646b",
    )
    return image


def store_image(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    relative = "assets/" + hashlib.sha256(data).hexdigest() + ".png"
    target = HERE / relative
    target.parent.mkdir(exist_ok=True)
    if not target.exists() or target.read_bytes() != data:
        target.write_bytes(data)
    return relative


def fields_for(row):
    _, _, groups, counts, variation, _, _ = row
    return {
        "shelf": store_image(drawing(groups, counts, variation)),
        "planogram": store_image(drawing(helpers.GROUPS, (3, 3, 3), 0, reference=True)),
    }


def answers_for(spec, provenance):
    return {g: NoulAnswer(p, provenance) for g, p in zip(helpers.GROUPS, spec, strict=True)}


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for row in rows:
        ident, split, _, _, _, gold, _ = row
        fields = fields_for(row)
        state, questions, assets = helpers.request(fields, HERE)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if gold is not None:
            groups = dict(zip(helpers.GROUPS, gold, strict=True))
            labels.append(
                {"id": ident, "label": {"groups": groups, "outcome": helpers.compose(groups)}}
            )
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        state, questions, assets = helpers.request(fields_for(row), HERE)
        key = replay_key(state, questions, assets=assets)
        responses[key] = DecisionResult(
            answers_for(row[-1], Provenance.synthetic()), "synthetic"
        ).to_dict()
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
    if not ROWS:
        raise SystemExit("add examples to ROWS in build_fixtures.py")
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
