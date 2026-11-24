"""Write assets/, assets-manifest.json and fixtures/ for recipe 62.

    python build_fixtures.py                     # from anywhere; it writes next to this file
    python build_fixtures.py --force             # also overwrite a responses.json holding a recorded answer
    python build_fixtures.py --overwrite-assets  # accept a picture that changed (replay keys change too)

The images are an invented settings page drawn here with jev_cookbook.synthetic_images
(docs/synthetic-images.md): no real application, brand, person or captured screen, and no product
name at all. ``settings_page`` draws the page from one of five bases (the values in its fields)
and applies the named changes of ``helpers.CHANGES`` to it; a pair is the base drawn with no
change (the before screenshot) and the same base drawn with the row's changes (the after
screenshot). The gold label of a pair is read from the changes that were drawn
(``helpers.gold_label``), never typed in beside the example. The responses are synthetic and
deliberately imperfect. The replay keys come from the same ``build_request`` and
``build_questions`` the notebook uses, and cover the images' bytes. See docs/fixtures.md and
docs/vision.md.

Each split has its own bases (validation a and b, test c and d, the demo e), so no picture's bytes
are shared between the scored splits.

Images are saved under the byte policy of docs/synthetic-images.md. Their bytes are part of the
replay key of each request that carries them, so if a regenerated picture differs from the file that is already there this script
stops and writes nothing more, unless ``--overwrite-assets`` accepts the change.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from ROWS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given. Duplicate JSON keys or missing, contradictory,
or unsupported answer provenance require --force too.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import (
    DecisionResult,
    NoulAnswer,
    Provenance,
    ScoreAnswer,
    dump_responses,
    load_helpers,
    replay_key,
)
from jev_cookbook import synthetic_images as si

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

WIDTH, HEIGHT = 640, 480  # every screenshot

# The values each base page shows: (display name, time zone, language, last saved, saved later).
# The names are invented initials and surnames for a demo account, not people.
BASES = {
    "a": ("JO PARK", "UTC+01:00", "ENGLISH", "09:41", "10:05"),
    "b": ("RI TANAKA", "UTC-05:00", "SPANISH", "14:12", "14:37"),
    "c": ("MO EVANS", "UTC+09:00", "FRENCH", "08:03", "08:26"),
    "d": ("LU SANTOS", "UTC+00:00", "GERMAN", "17:55", "18:20"),
    "e": ("KAI DIAZ", "UTC+02:00", "DUTCH", "11:30", "11:52"),
}

# (id, split, pair identifier, base, the changes drawn in the after screenshot, answer overrides)
# The overrides replace the default stored answer of a question: a category name maps to a
# probability of yes; "<category>_severity" maps to the four integer weights of the Score's
# levels. Every other answer comes from the defaults in ``answers_for``. Several are wrong on
# purpose, so the evaluation has errors to find.
ROWS = [
    ("v01", "validation", "P-1001", "a", (), {}),
    ("v02", "validation", "P-1002", "b", ("accent_colour",), {"overlap": 0.64}),
    ("v03", "validation", "P-1003", "a", ("avatar_missing",), {}),
    ("v04", "validation", "P-1004", "b", ("help_missing",), {}),
    (
        "v05",
        "validation",
        "P-1005",
        "a",
        ("field_shifted",),
        {"misalignment": 0.58, "clipping": 0.5},
    ),
    ("v06", "validation", "P-1006", "b", ("labels_shifted",), {"misalignment": 0.12}),
    ("v07", "validation", "P-1007", "a", ("help_clipped_edge",), {"misalignment": 0.45}),
    ("v08", "validation", "P-1008", "b", ("help_clipped_half",), {}),
    (
        "v09",
        "validation",
        "P-1009",
        "a",
        ("help_clipped_boundary",),
        {"clipping_severity": (4, 40, 44, 4)},
    ),
    ("v10", "validation", "P-1010", "b", ("badge_overlap",), {"missing_element": 0.7}),
    ("v11", "validation", "P-1011", "a", ("toast_over_save",), {}),
    (
        "v12",
        "validation",
        "P-1012",
        "b",
        ("avatar_missing", "field_nudged"),
        {"misalignment_severity": (40, 36, 6, 4)},
    ),
    ("v13", "validation", "P-1013", "a", ("save_missing", "help_clipped_edge"), {}),
    (
        "v14",
        "validation",
        "P-1014",
        "b",
        ("avatar_missing", "toast_over_help"),
        {"overlap": 0.55},
    ),
    ("v15", "validation", "P-1015", "a", ("field_nudged", "help_clipped_half"), {}),
    (
        "v16",
        "validation",
        "P-1016",
        "b",
        ("labels_shifted", "badge_overlap"),
        {"misalignment_severity": (4, 46, 40, 4)},
    ),
    ("v17", "validation", "P-1017", "a", ("help_clipped_edge", "toast_over_save"), {}),
    (
        "v18",
        "validation",
        "P-1018",
        "b",
        ("avatar_missing", "field_shifted", "help_clipped_boundary"),
        {"missing_element": 0.66},
    ),
    (
        "v19",
        "validation",
        "P-1019",
        "a",
        ("help_missing", "labels_shifted", "badge_overlap"),
        {"overlap": 0.61},
    ),
    (
        "v20",
        "validation",
        "P-1020",
        "b",
        ("save_missing", "help_clipped_edge", "badge_overlap"),
        {"clipping": 0.47},
    ),
    (
        "v21",
        "validation",
        "P-1021",
        "a",
        ("field_nudged", "help_clipped_half", "badge_overlap"),
        {"misalignment": 0.39},
    ),
    (
        "v22",
        "validation",
        "P-1022",
        "b",
        ("avatar_missing", "field_shifted", "help_clipped_edge", "badge_overlap"),
        {},
    ),
    ("t01", "test", "P-2001", "c", (), {}),
    ("t02", "test", "P-2002", "d", ("timestamp_updated",), {"misalignment": 0.62}),
    ("t03", "test", "P-2003", "c", ("accent_colour",), {"overlap": 0.72}),
    ("t04", "test", "P-2004", "d", ("save_missing",), {}),
    ("t05", "test", "P-2005", "c", ("avatar_missing",), {}),
    ("t06", "test", "P-2006", "d", ("field_nudged",), {"misalignment": 0.33}),
    ("t07", "test", "P-2007", "c", ("labels_shifted",), {}),
    (
        "t08",
        "test",
        "P-2008",
        "d",
        ("help_clipped_boundary",),
        {"clipping_severity": (4, 10, 60, 6)},
    ),
    ("t09", "test", "P-2009", "c", ("help_clipped_half",), {}),
    ("t10", "test", "P-2010", "d", ("toast_over_help",), {"overlap": 0.30}),
    ("t11", "test", "P-2011", "c", ("badge_overlap",), {"overlap": 0.35}),
    ("t12", "test", "P-2012", "d", ("help_missing", "field_shifted"), {}),
    (
        "t13",
        "test",
        "P-2013",
        "c",
        ("avatar_missing", "help_clipped_half"),
        {"clipping_severity": (4, 36, 40, 4)},
    ),
    ("t14", "test", "P-2014", "d", ("save_missing", "badge_overlap"), {}),
    ("t15", "test", "P-2015", "c", ("field_nudged", "help_clipped_half"), {}),
    ("t16", "test", "P-2016", "d", ("field_shifted", "toast_over_save"), {}),
    (
        "t17",
        "test",
        "P-2017",
        "c",
        ("help_clipped_edge", "badge_overlap"),
        {"missing_element": 0.68},
    ),
    ("t18", "test", "P-2018", "d", ("save_missing", "field_nudged", "help_clipped_boundary"), {}),
    (
        "t19",
        "test",
        "P-2019",
        "c",
        ("avatar_missing", "labels_shifted", "toast_over_save"),
        {"misalignment_severity": (4, 40, 36, 4)},
    ),
    (
        "t20",
        "test",
        "P-2020",
        "d",
        ("avatar_missing", "help_clipped_edge", "badge_overlap"),
        {"clipping": 0.4},
    ),
    ("t21", "test", "P-2021", "c", ("labels_shifted", "help_clipped_edge", "badge_overlap"), {}),
    (
        "t22",
        "test",
        "P-2022",
        "d",
        ("avatar_missing", "field_nudged", "help_clipped_boundary", "badge_overlap"),
        {"clipping_severity": (4, 40, 36, 4)},
    ),
    ("d01", "demo", "P-3001", "e", ("field_nudged", "help_clipped_half"), {}),
]

# Default stored answers. A category that is there gets a probability of yes from PRESENT, one
# that is not from ABSENT, each picked by the row's position so the values vary; its Score
# weights put PEAKS on the gold level (on the first level when the category is absent) and 6
# on each neighbour, over a floor of 4.
PRESENT = (0.93, 0.86, 0.9, 0.81, 0.88)
ABSENT = (0.06, 0.12, 0.09, 0.15, 0.04, 0.1)
PEAKS = (60, 48, 70, 54, 64)

# Where the parts of the page are drawn, in pixels.
LABEL_X, FIELD_X, ROW_Y, ROW_STEP = 44, 230, 120, 50  # labels, fields and the first row
HELP_Y, SAVED_Y, BUTTON_Y = 300, 326, 380


def settings_page(*, base, changes=()):
    """One 640x480 invented settings page, drawn from ``base`` with ``changes`` applied.

    ``base`` is a key of ``BASES``; ``changes`` names entries of ``helpers.CHANGES``. Every length
    is an integer, so the pixels are the same on every Python. A change the page does not know
    how to draw raises before anything is saved.
    """
    unknown = sorted(set(changes) - set(helpers.CHANGES))
    if unknown:
        raise ValueError(f"settings_page does not draw {unknown}")
    name, zone, language, saved, saved_later = BASES[base]
    c = si.Canvas(WIDTH, HEIGHT, "light")
    c.window(20, 20, 600, 440, "ACCOUNT SETTINGS", name="window")
    c.text(LABEL_X, 64, "PROFILE", "ink", 3, name="heading")
    if "avatar_missing" not in changes:
        c.ellipse(548, 58, 44, 44, "teal", name="avatar")
    labels = ("DISPLAY NAME", "TIME ZONE", "LANGUAGE")
    values = (name, zone, language)
    label_drop = ROW_STEP if "labels_shifted" in changes else 0
    for row, (label, value) in enumerate(zip(labels, values, strict=True)):
        y = ROW_Y + row * ROW_STEP
        c.text(LABEL_X, y + label_drop, label, "dark", 2, name=f"label{row}")
        x = FIELD_X
        if row == 0 and "field_nudged" in changes:
            x += 4
        if row == 0 and "field_shifted" in changes:
            x += 28
        c.rect(x, y - 9, 300, 32, "white", outline="mid", name=f"field{row}")
        c.text(x + 10, y, value, "ink", 2)
    if "help_missing" not in changes:
        c.text(LABEL_X, HELP_Y, "CHANGES APPLY ON EVERY DEVICE", "dark", 2, name="help")
        cut = {"help_clipped_edge": 2, "help_clipped_boundary": 6, "help_clipped_half": 10}
        for change, rows_cut in cut.items():
            if change in changes:
                help_line = c.objects["help"]
                c.rect(
                    help_line.left - 2,
                    help_line.bottom - rows_cut,
                    help_line.width + 4,
                    rows_cut,
                    "white",
                    name="help_cut",
                )
    later = "timestamp_updated" in changes
    c.text(LABEL_X, SAVED_Y, f"LAST SAVED {saved_later if later else saved}", "mid", 2)
    if "save_missing" not in changes:
        fill = "green" if "accent_colour" in changes else "blue"
        save = c.rect(LABEL_X, BUTTON_Y, 200, 44, fill, outline="dark", name="save")
        c.centered_text(save, "SAVE CHANGES", "white", 2)
    cancel = c.rect(264, BUTTON_Y, 130, 44, "white", outline="mid", name="cancel")
    c.centered_text(cancel, "CANCEL", "ink", 2)
    if "badge_overlap" in changes:
        badge = c.rect(376, BUTTON_Y - 10, 34, 20, "red", name="badge")
        c.centered_text(badge, "NEW", "white", 1)
    for change, (x, y) in (("toast_over_help", (34, 288)), ("toast_over_save", (34, 372))):
        if change in changes:
            toast = c.rect(x, y, 330, 40, "ink", name=change)
            c.centered_text(toast, "SYNC PAUSED", "white", 2)
    return c.provenance("build_fixtures.py:settings_page", {"base": base, "changes": list(changes)})


def before_path(base):
    """Where the unchanged page of ``base`` is saved, relative to the recipe."""
    return f"assets/before-{base}.png"


def after_path(ident):
    """Where the after screenshot of example ``ident`` is saved, relative to the recipe."""
    return f"assets/after-{ident}.png"


def describe(base, changes):
    """What the manifest says a screenshot shows."""
    shown = ", ".join(changes) if changes else "no change"
    return f"An invented account settings page, base {base!r}, drawn with: {shown}."


def write_images(rows, overwrite, *, canvases=None):
    """Validate every image and its provenance before saving; return manifest entries by path.

    The unchanged page of each base the rows use is saved once, then each row's after
    screenshot. ``canvases`` receives one after-screenshot canvas per row, in row order.
    A validation error or ``si.RegenerationMismatch`` leaves all destination PNGs unchanged.
    Installation is atomic per file, not a rollback transaction for later I/O failures."""
    bases = sorted({row[3] for row in rows})
    images = [(settings_page(base=base), before_path(base), describe(base, ())) for base in bases]
    afters = []
    for row in rows:
        ident, _split, _pair, base, changes, _answers = row
        helpers.gold_label(changes)  # an unlabelled change raises here, before any file is written
        afters.append((settings_page(base=base, changes=changes), after_path(ident)))
        images.append((afters[-1][0], after_path(ident), describe(base, changes)))
    written = si.write_assets(images, HERE, overwrite=overwrite)
    for (_canvas, path, _description), (status, _entry) in zip(images, written, strict=True):
        print(f"{status}: {path}")
    if canvases is not None:
        canvases.extend(canvas for canvas, _path in afters)
    return sorted((entry for _status, entry in written), key=lambda entry: entry["path"])


def _fields(row):
    return {"pair": row[2], "before": before_path(row[3]), "after": after_path(row[0])}


def build_inputs_and_labels(rows, *, canvases=None, keys=None):
    """``(inputs, labels)`` from ``rows``, with the images already saved. Neither ever holds a
    model's answer, so both are always safe to regenerate, even after ``responses.json`` has
    been recorded. The gold label is read from the changes that were drawn; the demo example
    has none."""
    inputs, labels = [], []
    for row in rows:
        ident, split = row[0], row[1]
        fields = _fields(row)
        state, assets = helpers.build_request(fields)
        key = replay_key(state, QUESTIONS, assets=assets)
        if keys is not None:
            keys.append(key)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if split != "demo":
            labels.append({"id": ident, "label": helpers.gold_label(row[4])})
    return inputs, labels


def _weights(level, peak):
    """Integer weights for the four Score levels: 4 each, plus ``peak`` on ``level`` and 6 beside it."""
    weights = [4] * len(helpers.LEVELS)
    weights[level] += peak
    for neighbour in (level - 1, level + 1):
        if 0 <= neighbour < len(weights):
            weights[neighbour] += 6
    return tuple(weights)


def answers_for(row, provenance: Provenance):
    """{question name: answer} for one row: a probability of yes per category and a Score per
    category, from the defaults above with the row's overrides applied."""
    index = ROWS.index(row) if row in ROWS else 0
    _ident, _split, _pair, _base, changes, overrides = row
    unknown = sorted(set(overrides) - set(QUESTIONS))
    if unknown:
        raise ValueError(f"row {row[0]!r}: {unknown} are not question names")
    label = helpers.gold_label(changes)
    answers = {}
    for position, category in enumerate(helpers.CATEGORIES):
        present = label[category]
        default = (
            PRESENT[index % len(PRESENT)] if present else ABSENT[(index + position) % len(ABSENT)]
        )
        answers[category] = NoulAnswer(overrides.get(category, default), provenance)
    for position, category in enumerate(helpers.CATEGORIES):
        key = helpers.severity_key(category)
        level = label["severity"].get(category, 0)
        weights = overrides.get(key) or _weights(level, PEAKS[(index + position) % len(PEAKS)])
        if len(weights) != len(helpers.LEVELS) or any(type(w) is not int or w < 1 for w in weights):
            raise ValueError(f"row {row[0]!r}: {key} needs four positive integer weights")
        total = 0  # integers, so any order gives the same total
        for weight in weights:
            total += weight
        answers[key] = ScoreAnswer.from_probabilities(
            [weight / total for weight in weights], list(helpers.LEVELS), provenance
        )
    return answers


def build_responses(rows, *, canvases=None, keys=None):
    """``{replay_key: stored response}`` from ``rows``, with the images already saved. Always
    synthetic: this script never calls Jev, so it can never produce a recorded response."""
    responses = {}
    for index, row in enumerate(rows):
        if keys is None:
            state, assets = helpers.build_request(_fields(row))
            key = replay_key(state, QUESTIONS, assets=assets)
        else:
            key = keys[index]
        answers = answers_for(row, Provenance.synthetic())
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def _has_synthetic_provenance(entry) -> bool:
    """Prove the result and every answer synthetic without validating answer mathematics."""
    if not isinstance(entry, dict) or entry.get("model") != "synthetic":
        return False
    if entry.keys() - {"model", "usage", "answers"}:
        return False
    answers = entry.get("answers")
    if not isinstance(answers, dict) or not answers:
        return False
    for answer in answers.values():
        if not isinstance(answer, dict):
            return False
        try:
            provenance = Provenance.from_dict(answer.get("provenance"))
        except ValueError:
            return False
        if provenance.source != "synthetic":
            return False
    return True


def _is_recorded(path: Path) -> bool:
    """True when an existing response cannot be proved synthetic; refuse ambiguous JSON.

    An empty response map contains nothing to preserve. Every entry in a nonempty map
    must have a synthetic model and consistent synthetic provenance on every answer.
    """
    if not path.exists():
        return False

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (ValueError, OSError, UnicodeError, RecursionError):
        raise SystemExit(
            f"refusing to overwrite {path}: cannot read responses.json to check for recorded "
            "responses (pass --force to overwrite it anyway)"
        ) from None
    if not isinstance(data, dict):
        raise SystemExit(
            f"refusing to overwrite {path}: responses.json is not a JSON object, so its "
            "provenance cannot be checked (pass --force to overwrite it anyway)"
        )
    return any(not _has_synthetic_provenance(entry) for entry in data.values())


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
        help="overwrite responses.json even if recorded or its provenance cannot be checked",
    )
    parser.add_argument(
        "--overwrite-assets",
        action="store_true",
        help="accept an image that differs from the committed file (its replay keys change)",
    )
    args = parser.parse_args()
    if not ROWS:
        raise SystemExit("ROWS is empty: add examples to ROWS in build_fixtures.py")
    responses_file = HERE / "fixtures" / "responses.json"
    if args.overwrite_assets and not args.force and _is_recorded(responses_file):
        # A redrawn picture changes the replay key of every request that carries it, which would
        # orphan the recorded answers kept in responses.json; refuse before any file is touched.
        raise SystemExit(
            f"refusing --overwrite-assets: {responses_file} holds a recorded response or ambiguous provenance, and a "
            "changed picture changes its replay keys (pass --force too to rewrite both); "
            "nothing was written"
        )
    # Retain only this run's canvases and keys; independent helper calls recompute them.
    canvases = []
    try:
        entries = write_images(ROWS, args.overwrite_assets, canvases=canvases)
    except si.RegenerationMismatch as error:
        raise SystemExit(
            f"refused: {error}\nnothing else was written; to accept the redrawn picture, run "
            "python build_fixtures.py --overwrite-assets (if fixtures/responses.json holds a "
            "recorded response, that is refused too unless you pass --force as well: "
            "python build_fixtures.py --overwrite-assets --force)"
        ) from None
    # Later steps index canvases[index] by row, so write_images must add one per row, in order.
    assert len(canvases) == len(ROWS), "write_images must add exactly one canvas per row, in order"
    manifest = {"schema": 1, "assets": entries}
    (HERE / "assets-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    keys = []
    inputs, labels = build_inputs_and_labels(ROWS, canvases=canvases, keys=keys)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\n" for row in rows)
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    responses_file = folder / "responses.json"
    if not args.force and _is_recorded(responses_file):
        message = (
            f"refusing to overwrite {responses_file}: it holds a recorded response or ambiguous provenance "
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
    responses = build_responses(ROWS, canvases=canvases, keys=keys)
    # dump_responses is the serialization the recorder writes with (top-level keys sorted, each
    # response keeping the field order DecisionResult.to_dict() emits), so a recording's diff
    # stays limited to the values that actually changed.
    responses_file.write_text(dump_responses(responses), encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
