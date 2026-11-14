"""Write assets/, assets-manifest.json and fixtures/ for recipe 69.

    python build_fixtures.py                     # from anywhere; it writes next to this file
    python build_fixtures.py --force             # also overwrite a responses.json holding a recorded answer
    python build_fixtures.py --overwrite-assets  # accept a picture that changed (replay keys change too)

The images are invented tea tins drawn here with jev_cookbook.synthetic_images primitives
(docs/synthetic-images.md): no photograph, brand, person or third-party picture. Six of them are
the catalogue's reference images (helpers.CATALOG says which design each shows), and the rest are
the queries. The gold label of a query is derived from the design that was drawn and from what
the picture shows of it (helpers.gold_label), never typed in. The responses are synthetic and
deliberately imperfect. The replay keys come from the same ``build_request`` and
``build_questions`` the notebook uses, and cover the bytes of every image a request carries, the
references in the criteria included. See docs/fixtures.md and docs/vision.md.

Images are saved under the byte policy of docs/synthetic-images.md. Their bytes are part of the
replay key of each request that carries them, so if a regenerated picture differs from the file
that is already there this script stops and writes nothing more, unless ``--overwrite-assets``
accepts the change.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from ROWS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import (
    ChoiceAnswer,
    DecisionResult,
    Provenance,
    dump_responses,
    load_helpers,
    replay_key,
)
from jev_cookbook import synthetic_images as si

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

WIDTH, HEIGHT = 320, 360  # every image: at least 280 pixels on each side

# What was drawn for each example.
#   design    a catalogue product's name, or a dict of body/lid/emblem for a tin the catalogue
#             does not hold, or None for a frame with no tin in it
#   hidden    None, "emblem" or "lid": a pink SALE tag covers that feature of the tin
#   condition how the picture was taken: "studio" (the reference's own conditions, the tin only
#             shifted in the frame), "dim", "noisy", "far" (the tin drawn at 70 percent of its
#             size) or "shelf" (another background, the tin standing on a board)
# and what the stored answer is: (option with the most weight, its weight, the runner-up, its
# weight). Every other option has weight 1, and a probability is a weight over the total, so the
# stored answers are plain integers over an integer total.
ROWS = [
    ("v01", "validation", "Q-1001", "DEGUM", None, "studio", 11, ("DEGUM", 88, "BIVEN", 6)),
    ("v02", "validation", "Q-1002", "BIVEN", None, "dim", 12, ("BIVEN", 70, "DEGUM", 20)),
    ("v03", "validation", "Q-1003", "NOKER", None, "shelf", 13, ("NOKER", 85, "MAFEX", 6)),
    ("v04", "validation", "Q-1004", "PEBIX", None, "far", 14, ("PEBIX", 80, "no_match", 8)),
    ("v05", "validation", "Q-1005", "VODAR", None, "noisy", 15, ("VODAR", 62, "no_match", 18)),
    ("v06", "validation", "Q-1006", "MAFEX", None, "dim", 16, ("MAFEX", 74, "NOKER", 14)),
    ("v07", "validation", "Q-1007", "DEGUM", None, "shelf", 17, ("BIVEN", 34, "DEGUM", 30)),
    ("v08", "validation", "Q-1008", "BIVEN", None, "far", 18, ("BIVEN", 41, "DEGUM", 38)),
    ("v09", "validation", "Q-1009", "PEBIX", None, "studio", 19, ("PEBIX", 90, "VODAR", 4)),
    (
        "v10",
        "validation",
        "Q-1010",
        {"body": "pink", "lid": "ink", "emblem": "disc"},
        None,
        "studio",
        20,
        ("no_match", 66, "VODAR", 14),
    ),
    (
        "v11",
        "validation",
        "Q-1011",
        {"body": "blue", "lid": "white", "emblem": "ring"},
        None,
        "shelf",
        21,
        ("DEGUM", 58, "no_match", 24),
    ),
    (
        "v12",
        "validation",
        "Q-1012",
        "DEGUM",
        "emblem",
        "studio",
        22,
        ("uncertain", 55, "DEGUM", 22),
    ),
    ("v13", "validation", "Q-1013", "BIVEN", "emblem", "shelf", 23, ("BIVEN", 48, "uncertain", 36)),
    ("v14", "validation", "Q-1014", "NOKER", "lid", "dim", 24, ("NOKER", 66, "uncertain", 22)),
    ("t01", "test", "Q-2001", "DEGUM", None, "far", 31, ("DEGUM", 78, "BIVEN", 10)),
    ("t02", "test", "Q-2002", "BIVEN", None, "studio", 32, ("BIVEN", 84, "DEGUM", 8)),
    ("t03", "test", "Q-2003", "NOKER", None, "noisy", 33, ("NOKER", 70, "MAFEX", 16)),
    ("t04", "test", "Q-2004", "PEBIX", None, "dim", 34, ("PEBIX", 76, "no_match", 10)),
    ("t05", "test", "Q-2005", "VODAR", None, "shelf", 35, ("VODAR", 88, "NOKER", 4)),
    ("t06", "test", "Q-2006", "MAFEX", None, "far", 36, ("MAFEX", 54, "NOKER", 26)),
    ("t07", "test", "Q-2007", "DEGUM", None, "dim", 37, ("DEGUM", 46, "BIVEN", 40)),
    ("t08", "test", "Q-2008", "BIVEN", None, "noisy", 38, ("DEGUM", 72, "BIVEN", 12)),
    ("t09", "test", "Q-2009", "VODAR", None, "studio", 39, ("VODAR", 90, "NOKER", 4)),
    (
        "t10",
        "test",
        "Q-2010",
        {"body": "blue", "lid": "ink", "emblem": "square"},
        None,
        "studio",
        40,
        ("no_match", 60, "DEGUM", 20),
    ),
    ("t11", "test", "Q-2011", None, None, "shelf", 41, ("no_match", 92, "uncertain", 2)),
    (
        "t12",
        "test",
        "Q-2012",
        {"body": "amber", "lid": "ink", "emblem": "stack"},
        None,
        "dim",
        42,
        ("VODAR", 52, "no_match", 32),
    ),
    ("t13", "test", "Q-2013", "DEGUM", "emblem", "dim", 43, ("uncertain", 64, "DEGUM", 14)),
    ("t14", "test", "Q-2014", "BIVEN", "emblem", "far", 44, ("DEGUM", 36, "uncertain", 32)),
    ("t15", "test", "Q-2015", "PEBIX", "emblem", "studio", 45, ("PEBIX", 70, "uncertain", 16)),
    ("t16", "test", "Q-2016", "MAFEX", None, "shelf", 46, ("MAFEX", 82, "NOKER", 6)),
    ("d01", "demo", "Q-3001", "PEBIX", None, "dim", 50, ("PEBIX", 72, "no_match", 12)),
]

REFERENCE_SEED = 0


def jitter(seed):
    """The tin's shift in the frame, in pixels, from the picture's seed: the same seed always
    shifts it the same way, and a query is never the reference's own picture."""
    rng = si.Rng(seed)
    return rng.between(-24, 24), rng.between(-16, 16)


def design_of(design):
    """``{body, lid, emblem}`` of a row's ``design`` (a catalogue name or a dict), or None."""
    if design is None:
        return None
    if isinstance(design, str):
        return next(sku for sku in helpers.CATALOG if sku.name == design).design()
    return dict(design)


def visible_of(design, hidden):
    """What a picture shows of its tin: each feature, or None for the one a tag covers."""
    drawn = design_of(design)
    if drawn is None:
        return None
    return {a: None if a == hidden else drawn[a] for a in helpers.ATTRIBUTES}


def draw_tin(
    *, body, lid, emblem, hidden=None, condition="reference", dx=0, dy=0, seed=0, tin=True
):
    """One tea tin on a plain background, as an invented stand-in for a product photograph.

    ``body`` and ``lid`` are palette colours and ``emblem`` is one of disc, ring, triangle, bars,
    stack or square. ``hidden`` ("emblem" or "lid") covers that feature with a pink SALE tag.
    ``condition`` is "reference" or "studio" (plain background, even light), "dim" (a shadow),
    "noisy" (sensor noise and a soft blur), "far" (70 percent of the size) or "shelf" (a tinted
    wall and a board under the tin). ``dx`` and ``dy`` shift the tin in the frame; ``tin=False``
    leaves it out. Every length is an integer, so the pixels are the same on every Python."""
    if condition not in ("reference", "studio", "dim", "noisy", "far", "shelf"):
        raise ValueError(f"unknown condition {condition!r}")
    percent = 70 if condition == "far" else 100
    wall = si.mix("grey", "teal", 30) if condition == "shelf" else "paper"
    canvas = si.Canvas(WIDTH, HEIGHT, wall, seed=seed)
    if tin:
        centre = WIDTH // 2 + dx
        base = (270 if condition == "far" else 300) + dy
        body_w, body_h = 110 * percent // 100, 160 * percent // 100
        lid_w, lid_h = 124 * percent // 100, 32 * percent // 100
        if condition == "shelf":
            canvas.rect(0, base, WIDTH, 28, "dark")
        else:
            canvas.ellipse(centre - body_w // 2 - 6, base - 8, body_w + 12, 16, "grey")
        body_x, body_y = centre - body_w // 2, base - body_h
        canvas.rect(body_x, body_y, body_w, body_h, body, outline="ink", outline_width=2)
        lid_x, lid_y = centre - lid_w // 2, body_y - lid_h
        canvas.rect(lid_x, lid_y, lid_w, lid_h, lid, outline="ink", outline_width=2)
        pad, label_h = 9 * percent // 100, 70 * percent // 100
        label_y = body_y + 45 * percent // 100
        canvas.rect(
            body_x + pad,
            label_y,
            body_w - 2 * pad,
            label_h,
            "paper",
            outline="ink",
            outline_width=1,
        )
        size = 36 * percent // 100
        left, top = centre - size // 2, label_y + (label_h - size) // 2
        unit = size // 5
        if emblem == "disc":
            canvas.ellipse(left, top, size, size, body)
        elif emblem == "ring":
            canvas.ellipse(left, top, size, size, body)
            inset = size // 4
            canvas.ellipse(left + inset, top + inset, size - 2 * inset, size - 2 * inset, "paper")
        elif emblem == "triangle":
            canvas.triangle(left, top, size, size, body)
        elif emblem == "bars":
            for index in range(3):
                canvas.rect(left + index * 2 * unit, top, unit, size, body)
        elif emblem == "stack":
            for index in range(3):
                canvas.rect(left, top + index * 2 * unit, size, unit, body)
        elif emblem == "square":
            canvas.rect(left, top, size, size, body)
        else:
            raise ValueError(f"unknown emblem {emblem!r}")
        margin = 8 * percent // 100
        if hidden == "emblem":
            tag = canvas.rect(
                left - margin,
                top - margin,
                size + 2 * margin,
                size + 2 * margin,
                "pink",
                outline="ink",
                outline_width=2,
            )
        elif hidden == "lid":
            tag = canvas.rect(
                lid_x - margin,
                lid_y - 2,
                lid_w + 2 * margin,
                lid_h + 4,
                "pink",
                outline="ink",
                outline_width=2,
            )
        elif hidden is None:
            tag = None
        else:
            raise ValueError(f"unknown hidden feature {hidden!r}")
        if tag is not None:
            canvas.centered_text(tag, "SALE", "white", 2 if percent == 100 else 1)
    if condition == "dim":
        canvas.lighting(55, gradient_percent=30)
    elif condition == "noisy":
        canvas.noise(12)
        canvas.blur(1)
    return canvas.provenance(
        "build_fixtures.py:draw_tin",
        {
            "body": body,
            "lid": lid,
            "emblem": emblem,
            "hidden": hidden,
            "condition": condition,
            "dx": dx,
            "dy": dy,
            "seed": seed,
            "tin": tin,
        },
    )


def reference_path(sku):
    return sku.reference_path


def query_path(ident):
    """Where the query image of example ``ident`` is saved, relative to the recipe."""
    return f"assets/query-{ident}.png"


def draw_reference(sku):
    """The catalogue reference image of ``sku``: the tin centred, in even light."""
    return draw_tin(**sku.design(), condition="reference", seed=REFERENCE_SEED)


def draw(row):
    """The canvas of one query row."""
    ident, _split, _capture, design, hidden, condition, seed, _answer = row
    dx, dy = jitter(seed)
    drawn = design_of(design)
    if drawn is None:
        # A frame with no tin: the same wall, nothing on it. The design arguments are placeholders
        # that are never drawn.
        return draw_tin(
            body="blue", lid="ink", emblem="disc", condition=condition, seed=seed, tin=False
        )
    return draw_tin(**drawn, hidden=hidden, condition=condition, dx=dx, dy=dy, seed=seed)


def describe(row):
    """What a query picture shows, for the manifest."""
    _ident, _split, _capture, design, hidden, condition, seed, _answer = row
    drawn = design_of(design)
    if drawn is None:
        return f"An invented shelf frame under {condition!r} conditions with no tin in it (seed {seed})."
    tag = f", a pink SALE tag covering the {hidden}" if hidden else ""
    return (
        f"An invented tea tin with a {drawn['body']} body, {drawn['lid']} lid and "
        f"{drawn['emblem']} emblem{tag}, drawn under {condition!r} conditions (seed {seed})."
    )


def write_images(rows, overwrite):
    """Draw and save every image under the byte policy; return the manifest entries by path.

    The six reference images come first, then the queries. Raises ``si.RegenerationMismatch``
    (and saves nothing more) for a picture that differs from the committed file, unless
    ``overwrite`` is true."""
    entries = []
    for sku in helpers.CATALOG:
        path = reference_path(sku)
        canvas = draw_reference(sku)
        status = canvas.write(HERE, path, overwrite=overwrite)
        print(f"{status}: {path}")
        description = (
            f"The reference image of the invented product {sku.name}: a tea tin with a "
            f"{sku.body} body, {sku.lid} lid and {sku.emblem} emblem, centred, in even light."
        )
        entries.append(canvas.manifest_entry(HERE, path, description))
    for row in rows:
        path = query_path(row[0])
        canvas = draw(row)
        status = canvas.write(HERE, path, overwrite=overwrite)
        print(f"{status}: {path}")
        entries.append(canvas.manifest_entry(HERE, path, describe(row)))
    return sorted(entries, key=lambda entry: entry["path"])


def _fields(row):
    return {"capture": row[2], "image": query_path(row[0]), "condition": row[5]}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``, with the images already saved. Neither ever holds a
    model's answer, so both are always safe to regenerate, even after ``responses.json`` has
    been recorded. A gold label is derived from what was drawn."""
    questions = helpers.build_questions()
    inputs, labels = [], []
    for row in rows:
        ident, split = row[0], row[1]
        fields = _fields(row)
        state, assets = helpers.build_request(fields)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if split != "demo":
            labels.append({"id": ident, "label": helpers.gold_label(visible_of(row[3], row[4]))})
    return inputs, labels


def answers_for(row, provenance: Provenance):
    """{question name: answer} for one row, from the integer weights ``row`` names."""
    top, top_weight, second, second_weight = row[-1]
    weights = dict.fromkeys(helpers.OPTIONS, 1)
    weights[top], weights[second] = top_weight, second_weight
    total = 0
    for weight in weights.values():  # integers, so any order gives the same total
        total += weight
    probabilities = {option: weight / total for option, weight in weights.items()}
    return {"sku": ChoiceAnswer.from_probabilities(probabilities, provenance)}


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``, with the images already saved. Always
    synthetic: this script never calls Jev, so it can never produce a recorded response."""
    questions = helpers.build_questions()
    responses = {}
    for row in rows:
        state, assets = helpers.build_request(_fields(row))
        key = replay_key(state, questions, assets=assets)
        answers = answers_for(row, Provenance.synthetic())
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
    parser = argparse.ArgumentParser(description="Write this recipe's assets/ and fixtures/.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite responses.json even if it holds a recorded (non-synthetic) answer",
    )
    parser.add_argument(
        "--overwrite-assets",
        action="store_true",
        help="accept an image that differs from the committed file (its replay keys change)",
    )
    args = parser.parse_args()
    if not ROWS:
        raise SystemExit("ROWS is empty: add examples to build_fixtures.py")
    responses_file = HERE / "fixtures" / "responses.json"
    if args.overwrite_assets and _is_recorded(responses_file) and not args.force:
        # A redrawn picture changes the replay key of every request that carries it, which would
        # orphan the recorded answers kept in responses.json; refuse before any file is touched.
        raise SystemExit(
            f"refusing --overwrite-assets: {responses_file} holds a recorded response, and a "
            "changed picture changes its replay keys (pass --force too to rewrite both); "
            "nothing was written"
        )
    try:
        entries = write_images(ROWS, args.overwrite_assets)
    except si.RegenerationMismatch as error:
        raise SystemExit(
            f"refused: {error}\nnothing else was written; to accept the redrawn picture, run "
            "python build_fixtures.py --overwrite-assets"
        ) from None
    manifest = {"schema": 1, "assets": entries}
    (HERE / "assets-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
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
    # dump_responses is the serialization the recorder writes with (top-level keys sorted, each
    # response keeping the field order DecisionResult.to_dict() emits), so a recording's diff
    # stays limited to the values that actually changed.
    responses_file.write_text(dump_responses(responses), encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
