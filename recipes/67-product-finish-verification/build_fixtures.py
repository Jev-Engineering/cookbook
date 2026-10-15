"""Author reproducible synthetic PNG illustrations and deliberately imperfect replay answers.

The drawing parameters and gold labels never enter inference state. They describe imagined
surface appearances, not real product photographs or measured color/material properties.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

from jev_cookbook import (
    DecisionResult,
    NoulAnswer,
    Provenance,
    ScoreAnswer,
    load_helpers,
    replay_key,
)

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
PALETTE = {
    "blue": (55, 108, 163),
    "teal": (48, 143, 130),
    "red": (177, 65, 60),
    "green": (75, 141, 85),
    "gray": (133, 141, 151),
    "brown": (151, 103, 65),
    "black": (58, 63, 68),
    "purple": (132, 84, 158),
}
# Tuple specs are color, apparent material, finish, illumination, visibility.
# Each case is a separately rendered enclosure lineage; no pixels cross scored splits.
ROWS = [
    ("v01", "validation", 101, ("blue", "plastic", "matte", "even", "clear"),
     ("blue", "plastic", "matte", "even", "clear"), (True, True, True, 0),
     (.98, .97, .97, .96), 0, "Same matte blue appearance."),
    ("v02", "validation", 102, ("teal", "plastic", "matte", "even", "clear"),
     ("teal", "plastic", "matte", "glare", "clear"), (True, True, True, 0),
     (.97, .94, .93, .91), 0, "Local illumination glare is not a glossy coating."),
    ("v03", "validation", 103, ("gray", "metal", "brushed", "even", "clear"),
     ("gray", "metal", "brushed", "shadow", "clear"), (True, True, True, 0),
     (.97, .93, .92, .88), 0, "Same brushed appearance under directional shadow."),
    ("v04", "validation", 104, ("red", "plastic", "matte", "even", "clear"),
     ("green", "plastic", "matte", "even", "clear"), (False, True, True, 3),
     (.98, .03, .97, .96), 3, "Persistent red-to-green body color change."),
    ("v05", "validation", 105, ("blue", "plastic", "matte", "even", "clear"),
     ("blue", "plastic", "gloss", "even", "clear"), (True, True, False, 3),
     (.98, .95, .96, .05), 3, "Broad sharp reflections from an illustrated glossy finish."),
    ("v06", "validation", 106, ("brown", "wood", "matte", "even", "clear"),
     ("brown", "plastic", "matte", "even", "clear"), (True, False, True, 3),
     (.98, .96, .04, .92), 3, "Wood grain is absent on the molded-looking candidate."),
    ("v07", "validation", 107, ("teal", "plastic", "matte", "even", "clear"),
     ("teal", "plastic", "textured", "even", "clear"), (True, True, False, 3),
     (.96, .96, .90, .78), 0, "Deliberate moderate-certainty miss of stippled finish."),
    ("v08", "validation", 108, ("black", "plastic", "gloss", "even", "clear"),
     ("black", "plastic", "gloss", "even", "covered"), (None, None, None, None),
     (.44, .53, .51, .50), None, "Occlusion leaves insufficient visible surface evidence."),
    ("v09", "validation", 109, ("purple", "plastic", "matte", "even", "clear"),
     ("purple", "unknown", "hazy", "even", "hazy"), (None, None, None, None),
     (.52, .62, .50, .48), None, "Unfamiliar and obscured appearance is unresolved."),
    ("v10", "validation", 110, None,
     ("red", "plastic", "matte", "even", "clear"), (None, None, None, None),
     None, None, "No visual reference supplied; Python requests no answer."),
    ("v11", "validation", 111, ("green", "plastic", "matte", "even", "clear"),
     ("green", "plastic", "matte", "even", "absent"), (None, None, None, None),
     (.02, .49, .49, .49), None, "Empty capture surface: candidate enclosure absent."),
    ("v12", "validation", 112, ("brown", "wood", "matte", "even", "clear"),
     ("brown", "wood", "matte", "even", "clear"), (True, True, True, 0),
     (.97, .96, .95, .94), 0, "Independent wood-grain drawings with matching appearance."),
    ("t01", "test", 201, ("red", "plastic", "matte", "even", "clear"),
     ("red", "plastic", "matte", "even", "clear"), (True, True, True, 0),
     (.98, .97, .96, .95), 0, "Same matte red appearance."),
    ("t02", "test", 202, ("green", "plastic", "matte", "even", "clear"),
     ("green", "plastic", "matte", "glare", "clear"), (True, True, True, 0),
     (.96, .92, .91, .90), 0, "Localized illumination glare on matching matte surfaces."),
    ("t03", "test", 203, ("gray", "metal", "brushed", "even", "clear"),
     ("gray", "metal", "brushed", "shadow", "clear"), (True, True, True, 0),
     (.96, .89, .94, .86), 0, "Matching brushed surface; authored uncertainty sends review."),
    ("t04", "test", 204, ("blue", "plastic", "matte", "even", "clear"),
     ("purple", "plastic", "matte", "even", "clear"), (False, True, True, 3),
     (.97, .05, .96, .94), 3, "Stable blue-to-purple hue difference."),
    ("t05", "test", 205, ("black", "plastic", "matte", "even", "clear"),
     ("black", "plastic", "gloss", "even", "clear"), (True, True, False, 3),
     (.98, .96, .95, .94), 0, "Confidently wrong glossy-as-matte answer passes frozen gate."),
    ("t06", "test", 206, ("brown", "wood", "matte", "even", "clear"),
     ("brown", "plastic", "matte", "even", "clear"), (True, False, True, 3),
     (.98, .95, .06, .91), 3, "Grain cues differ despite a similar brown color."),
    ("t07", "test", 207, ("red", "plastic", "matte", "even", "clear"),
     ("red", "plastic", "textured", "even", "clear"), (True, True, False, 3),
     (.97, .97, .94, .07), 3, "Raised stipple differs from a smooth surface."),
    ("t08", "test", 208, ("teal", "plastic", "gloss", "even", "clear"),
     ("teal", "plastic", "gloss", "even", "covered"), (None, None, None, None),
     (.31, .55, .53, .52), None, "Heavy occlusion is not evidence of a match."),
    ("t09", "test", 209, ("purple", "plastic", "matte", "even", "clear"),
     ("purple", "unknown", "hazy", "even", "hazy"), (None, None, None, None),
     (.49, .58, .48, .51), None, "Indeterminate material appearance stays unresolved."),
    ("t10", "test", 210, None,
     ("blue", "plastic", "matte", "even", "clear"), (None, None, None, None),
     None, None, "Reference missing, so Python bypasses inference."),
    ("t11", "test", 211, ("red", "plastic", "matte", "even", "clear"),
     ("red", "plastic", "matte", "even", "absent"), (None, None, None, None),
     (.04, .50, .49, .50), None, "Candidate absent, even though the reference is clear."),
    ("t12", "test", 212, ("brown", "wood", "matte", "even", "clear"),
     ("brown", "wood", "matte", "even", "clear"), (True, True, True, 0),
     (.97, .95, .96, .94), 3, "Matching pixels but conflicting authored severity triggers review."),
    ("d01", "demo", 301, ("blue", "plastic", "matte", "even", "clear"),
     ("blue", "plastic", "matte", "glare", "clear"), None,
     (.98, .96, .95, .93), 0, "Unscored glare demonstration."),
    ("d02", "demo", 302, ("teal", "plastic", "matte", "even", "clear"),
     ("teal", "plastic", "gloss", "even", "clear"), None,
     (.98, .95, .96, .08), 3, "Unscored finish mismatch demonstration."),
]  # fmt: skip


def render(spec, seed):
    """Draw an enclosure with visible, illustrative cues; no physical renderer is implied."""
    color, material, finish, light, visibility = spec
    image = Image.new("RGB", (384, 320), (244, 244, 240))
    draw = ImageDraw.Draw(image)
    left, top = 78 + seed % 13, 38 + seed % 11
    right, bottom = 300 - seed % 9, 280 - seed % 7
    if visibility == "absent":
        draw.line((40, 285 - seed % 9, 345, 285 - seed % 9), fill=(228, 228, 224), width=2)
        return image
    mask = Image.new("L", image.size)
    ImageDraw.Draw(mask).rounded_rectangle((left, top, right, bottom), radius=24, fill=255)
    body = Image.new("RGB", image.size)
    pixels = body.load()
    base = PALETTE[color]
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            u, v = (x - left) / (right - left), (y - top) / (bottom - top)
            noise = ((x * 17 + y * 29 + seed * 7) % 13 - 6) * 0.28
            shade = 0.92 + 0.08 * (1 - u) + (seed % 5 - 2) * 0.007
            extra = noise
            if material == "wood":
                extra += 13 * math.sin(y * 0.23 + 2.2 * math.sin(x * 0.035 + seed))
            if material == "metal":
                extra += ((y * 7 + seed) % 9 - 4) * 2.0
            if finish == "textured":
                extra += 24 if (x * 3 + y * 5 + seed) % 11 < 3 else -8
            if finish == "gloss":
                extra += 115 if 0.18 < u + 0.22 * v < 0.34 else 0
                extra += 45 if 0.73 < u < 0.79 else 0
            if light == "glare":
                extra += 92 * math.exp(-((u - 0.38) ** 2 + (v - 0.32) ** 2) / 0.055)
            if light == "shadow":
                shade *= 0.46 + 0.54 * u
            pixels[x, y] = tuple(max(0, min(255, int(c * shade + extra))) for c in base)
    image.paste(body, (0, 0), mask)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((left, top, right, bottom), radius=24, outline=(55, 62, 65), width=3)
    for x in (left + 17, right - 17):
        for y in (top + 17, bottom - 17):
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(167, 174, 177))
            draw.line((x - 2, y, x + 2, y), fill=(72, 76, 78))
    if visibility == "covered":
        draw.polygon(
            (
                (left - 8, top + 23),
                (right + 15, top + 6),
                (right + 8, bottom - 27),
                (left - 9, bottom - 5),
            ),
            fill=(215, 212, 202),
        )
    if visibility == "hazy":
        veil = Image.new("RGB", image.size, (210, 207, 199))
        image = Image.blend(image, veil, 0.74)
    return image


def write_image(spec, seed):
    import io

    stream = io.BytesIO()
    render(spec, seed).save(stream, format="PNG", optimize=False)
    raw = stream.getvalue()
    name = f"assets/{hashlib.sha256(raw).hexdigest()}.png"
    path = HERE / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(raw)
    return name


def fields_for(row):
    _, _, seed, reference, candidate, *_ = row
    return {
        "reference": None if reference is None else write_image(reference, seed * 2),
        "candidate": write_image(candidate, seed * 2 + 1),
    }


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for row in rows:
        ident, split, _, _, _, gold, _, _, note = row
        fields = fields_for(row)
        keys = []
        if fields["reference"] is not None:
            state, questions, assets = helpers.build_request(fields, HERE)
            keys.append(replay_key(state, questions, assets=assets))
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if gold is not None:
            label = dict(zip(helpers.ATTRIBUTES, gold[:3], strict=True))
            label.update(
                severity=gold[3],
                comparable=gold[0] is not None,
                acceptable=all(value is True for value in gold[:3]),
                note=note,
            )
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for row in rows:
        fields = fields_for(row)
        if fields["reference"] is None:
            continue
        state, questions, assets = helpers.build_request(fields, HERE)
        probabilities, peak = row[6:8]
        answers = {
            name: NoulAnswer(p, Provenance.synthetic())
            for name, p in zip(helpers.PROPOSITIONS, probabilities, strict=True)
        }
        distribution = [0.2] * 5 if peak is None else [0.02] * 5
        if peak is not None:
            distribution[peak] = 0.92
        answers["severity"] = ScoreAnswer.from_probabilities(
            distribution, helpers.RUBRIC, Provenance.synthetic()
        )
        key = replay_key(state, questions, assets=assets)
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
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
        raise SystemExit("TODO: add examples to ROWS in build_fixtures.py")
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
