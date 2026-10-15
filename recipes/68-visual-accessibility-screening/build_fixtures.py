"""Author synthetic UI drawings and deliberately imperfect replay answers; never infer live."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, drawing variant, theme, font size, flags, assessable, rationale,
# probabilities in clipping / low_contrast / crowding / overlap / readable order.
ROWS = [
    ("v01", "validation", "roomy", "light", 20, [], True,
     "Clear text and separated controls.", (.06, .08, .07, .04, .98)),
    ("v02", "validation", "clipped", "dark", 23, ["clipping"], True,
     "Main sentence is cut at the right boundary.", (.94, .04, .04, .05, .98)),
    ("v03", "validation", "faint", "light", 22, ["low_contrast"], True,
     "Pale main text blends into the paper.", (.04, .93, .03, .04, .98)),
    ("v04", "validation", "cramped", "dark", 18, ["crowding"], True,
     "Only two pixels separate the controls.", (.04, .04, .94, .04, .98)),
    ("v05", "validation", "overlap", "light", 21, ["crowding", "overlap"], True,
     "Blue control covers the pink control and its label.", (.04, .06, .94, .96, .98)),
    ("v06", "validation", "both_text", "dark", 24, ["clipping", "low_contrast"], True,
     "Faint long text is also visibly cut off.", (.93, .94, .04, .04, .98)),
    ("v07", "validation", "ellipsis", "light", 19, [], True,
     "Intentional ellipsis is complete; no cut letter strokes.", (.61, .03, .03, .04, .98)),
    ("v08", "validation", "roomy", "dark", 18, [], True,
     "Dark theme still has clear bright text.", (.03, .60, .04, .04, .98)),
    ("v09", "validation", "compact", "light", 20, [], True,
     "Nine-pixel gap is compact but labels and edges remain clear.", (.04, .04, .65, .05, .98)),
    ("v10", "validation", "stacked", "dark", 22, [], True,
     "Vertically stacked controls have a clear nine-pixel gap.", (.04, .03, .05, .66, .98)),
    ("v11", "validation", "blur", "light", 22, [], False,
     "Blur prevents reliable character and boundary judgments.", (.04, .04, .04, .04, .25)),
    ("v12", "validation", "icons", "dark", 21, [], True,
     "Unfamiliar icons are visible; their accessible names cannot be inferred.",
     (.04, .04, .04, .04, .96)),
    ("t01", "test", "roomy", "dark", 24, [], True,
     "Large bright text and separated controls.", (.03, .04, .04, .03, .98)),
    ("t02", "test", "clipped", "light", 21, ["clipping"], True,
     "Right edge truncates the longer explanatory text.", (.96, .04, .04, .04, .98)),
    ("t03", "test", "faint", "dark", 20, ["low_contrast"], True,
     "Grey main text has weak separation from the dark background.", (.04, .95, .04, .04, .98)),
    ("t04", "test", "cramped", "light", 23, ["crowding"], True,
     "Near-touching controls have cramped labels.", (.04, .04, .96, .04, .98)),
    ("t05", "test", "overlap", "dark", 19, ["crowding", "overlap"], True,
     "One control obscures the other's label.", (.04, .04, .96, .96, .98)),
    ("t06", "test", "both_text", "light", 22, ["clipping", "low_contrast"], True,
     "Both text defects are visible, but the synthetic clipping answer is unsure.",
     (.56, .96, .04, .04, .98)),
    ("t07", "test", "ellipsis", "dark", 23, [], True,
     "The ellipsis is intentional; the synthetic answer is uncertain.",
     (.54, .04, .04, .04, .98)),
    ("t08", "test", "compact", "dark", 19, [], True,
     "Benign compact spacing; the stored answer confidently overflags crowding.",
     (.04, .04, .97, .04, .98)),
    ("t09", "test", "faint", "light", 18, ["low_contrast"], True,
     "Faint text; the stored answer confidently misses it.", (.04, .03, .04, .04, .98)),
    ("t10", "test", "occluded", "light", 20, [], False,
     "Opaque help panel hides the controls; no complete screen can be assessed.",
     (.04, .04, .04, .04, .12)),
    ("t11", "test", "blur", "dark", 24, [], False,
     "Blur obscures evidence, despite confident negative flag answers.",
     (.03, .03, .03, .03, .18)),
    ("t12", "test", "icons", "light", 24, [], True,
     "Ambiguous icon meaning is not one of the four visible defect labels.",
     (.04, .04, .04, .04, .98)),
    ("d01", "demo", "both_text", "light", 24, None, True,
     "Demonstrate two independent positive flags.", (.95, .94, .04, .03, .98)),
    ("d02", "demo", "compact", "light", 18, None, True,
     "Demonstrate a review decision for uncertain crowding.", (.04, .04, .56, .04, .98)),
]  # fmt: skip


def draw_ui(row):
    ident, _, variant, theme, size, *_ = row
    dark = theme == "dark"
    background = (32, 38, 48) if dark else (254, 254, 254)
    foreground = (244, 246, 250) if dark else (30, 30, 30)
    if variant in {"faint", "both_text"}:
        foreground = (112, 118, 128) if dark else (188, 188, 188)
    image = Image.new("RGB", (480, 360), background)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=size)
    heading = ImageFont.load_default(size=25)
    bright = (244, 246, 250) if dark else (30, 30, 30)
    draw.text((24, 22), "Notification settings", font=heading, fill=bright)
    # Labels vary naturally across examples; IDs and defect names are never drawn.
    subtitle = "Choose your notification mode"
    if variant in {"clipped", "both_text"}:
        subtitle = "Choose your notification preferences for every workspace"
    elif variant == "ellipsis":
        subtitle = "Notification preferences..."
    text = Image.new("RGB", (432, 58), background)
    ImageDraw.Draw(text).text((8, 10), subtitle, font=font, fill=foreground)
    image.paste(text, (24, 74))
    y = 166 + (int(ident[-2:]) % 3) * 4
    gap = 2 if variant == "cramped" else 9 if variant == "compact" else 32
    a = (36, y, 218, y + 56)
    b = (218 + gap, y, 400 + gap, y + 56)
    if variant == "overlap":
        b = (126, y + 18, 308, y + 74)
    elif variant == "stacked":
        a, b = (36, 150, 312, 198), (36, 207, 312, 255)
    labels = ("Daily digest", "Live updates")
    if variant == "icons":
        labels = ("*", "?")
    for box, color, label in zip((a, b), helpers.CONTROL_COLORS, labels, strict=True):
        draw.rectangle(box, fill=color)
        draw.text(
            (box[0] + 10, box[1] + 16),
            label,
            font=ImageFont.load_default(size=17),
            fill=(24, 24, 24),
        )
    footer = "Changes are saved in this workspace"
    if variant == "icons":
        footer = "Tooltip and keyboard behavior are not shown"
    draw.text((24, 313), footer, font=ImageFont.load_default(size=16), fill=bright)
    if variant == "occluded":
        draw.rectangle((25, 145, 455, 290), fill=(222, 222, 222))
        draw.text((55, 190), "Help panel covers controls", font=font, fill=(30, 30, 30))
    if variant == "blur":
        image = image.filter(ImageFilter.GaussianBlur(5))
    return image


def image_fields(row):
    folder = HERE / "assets"
    folder.mkdir(exist_ok=True)
    image = draw_ui(row)
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    content = buffer.getvalue()
    name = hashlib.sha256(content).hexdigest() + ".png"
    (folder / name).write_bytes(content)
    return {"image": "assets/" + name}


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for row in rows:
        ident, split, _, _, _, flags, assessable, rationale, _ = row
        fields = image_fields(row)
        state, questions, assets = helpers.build_request(fields, HERE)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if flags is not None:
            labels.append(
                {
                    "id": ident,
                    "label": {"flags": flags, "assessable": assessable, "rationale": rationale},
                }
            )
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        state, questions, assets = helpers.build_request(image_fields(row), HERE)
        answers = {
            name: NoulAnswer(p, Provenance.synthetic())
            for name, p in zip(questions, row[-1], strict=True)
        }
        responses[replay_key(state, questions, assets=assets)] = DecisionResult(
            answers, "synthetic"
        ).to_dict()
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
            a.get("provenance", {}).get("source") == "recorded"
            for a in entry.get("answers", {}).values()
        )
        for entry in data.values()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text("".join(json.dumps(row) + "\n" for row in rows), "utf-8")
    path = folder / "responses.json"
    if _is_recorded(path) and not args.force:
        raise SystemExit("refusing to overwrite recorded responses; pass --force to replace")
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    print(f"wrote {len(inputs)} images, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
