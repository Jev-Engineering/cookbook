"""Write assets/, assets-manifest.json and fixtures/ for recipe 61.

    python build_fixtures.py                     # from anywhere; it writes next to this file
    python build_fixtures.py --force             # also overwrite a responses.json holding a recorded answer
    python build_fixtures.py --overwrite-assets  # accept a picture that changed (replay keys change too)

The images are invented application windows drawn here with jev_cookbook.synthetic_images
(docs/synthetic-images.md): no real application, brand, person or captured screen. Four kinds
are the shared ``login_screen`` scene; the rest are drawn by ``app_screen`` below. The gold label
of an image is read from the ``kind`` that was drawn (``helpers.gold_label``), never typed in
beside the example. The responses are synthetic and deliberately imperfect. The replay keys come
from the same ``build_request`` and ``build_questions`` the notebook uses, and cover the images'
bytes. See docs/fixtures.md and docs/vision.md.

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
QUESTIONS = helpers.build_questions()

WIDTH, HEIGHT = 640, 400  # every image, like the shared login_screen scene

# (id, split, capture, kind drawn, drawing seed, the stored answer)
# The stored answer is (option with the most weight, its weight, the runner-up, its weight).
# Every other option has weight 1, and a probability is a weight over the total, so the
# probabilities of a row are fixed by four integers. Several rows are deliberately wrong.
ROWS = [
    ("v01", "validation", "S-1001", "sign_in", 1, ("normal", 50, "crash", 10)),
    ("v02", "validation", "S-1002", "sign_in_rejected", 2, ("auth_failure", 60, "normal", 8)),
    ("v03", "validation", "S-1003", "sign_in_waiting", 3, ("loading", 55, "crash", 10)),
    ("v04", "validation", "S-1004", "sign_in_crashed", 4, ("crash", 70, "loading", 6)),
    ("v05", "validation", "S-1005", "dashboard", 5, ("normal", 40, "loading", 10)),
    ("v06", "validation", "S-1006", "waiting_with_warning", 6, ("auth_failure", 30, "loading", 24)),
    ("v07", "validation", "S-1007", "rejected_inline", 7, ("normal", 24, "auth_failure", 20)),
    ("v08", "validation", "S-1008", "page_not_found", 41, ("unknown", 50, "normal", 8)),
    ("v09", "validation", "S-1009", "payment_declined", 42, ("auth_failure", 32, "unknown", 20)),
    ("v10", "validation", "S-1010", "dashboard_crashed", 46, ("crash", 36, "unknown", 12)),
    ("v11", "validation", "S-1011", "sign_in_with_hint", 11, ("normal", 28, "auth_failure", 18)),
    ("v12", "validation", "S-1012", "partial_render", 12, ("normal", 26, "unknown", 24)),
    ("t01", "test", "S-2001", "sign_in", 21, ("normal", 55, "crash", 8)),
    ("t02", "test", "S-2002", "sign_in_rejected", 22, ("auth_failure", 60, "normal", 10)),
    ("t03", "test", "S-2003", "sign_in_waiting", 48, ("loading", 50, "crash", 8)),
    ("t04", "test", "S-2004", "sign_in_crashed", 47, ("crash", 65, "loading", 8)),
    ("t05", "test", "S-2005", "dashboard", 25, ("normal", 45, "loading", 10)),
    ("t06", "test", "S-2006", "dashboard_crashed", 26, ("crash", 30, "unknown", 15)),
    ("t07", "test", "S-2007", "waiting_with_warning", 27, ("loading", 28, "auth_failure", 22)),
    ("t08", "test", "S-2008", "waiting_with_warning", 28, ("auth_failure", 52, "loading", 14)),
    ("t09", "test", "S-2009", "rejected_inline", 29, ("auth_failure", 48, "normal", 12)),
    ("t10", "test", "S-2010", "rejected_inline", 60, ("normal", 30, "auth_failure", 25)),
    ("t11", "test", "S-2011", "sign_in_with_hint", 31, ("normal", 50, "auth_failure", 12)),
    ("t12", "test", "S-2012", "sign_in_with_hint", 32, ("auth_failure", 26, "normal", 22)),
    ("t13", "test", "S-2013", "page_not_found", 33, ("unknown", 45, "crash", 12)),
    ("t14", "test", "S-2014", "payment_declined", 34, ("auth_failure", 56, "unknown", 12)),
    ("t15", "test", "S-2015", "partial_render", 35, ("unknown", 30, "loading", 20)),
    ("t16", "test", "S-2016", "maintenance", 36, ("crash", 26, "unknown", 22)),
    ("d01", "demo", "S-3001", "waiting_with_warning", 40, ("loading", 45, "auth_failure", 12)),
]

# The shared scene draws four of the kinds; its ``state`` argument names each.
LOGIN_STATES = {
    "sign_in": "normal",
    "sign_in_rejected": "error",
    "sign_in_waiting": "loading",
    "sign_in_crashed": "crash",
}

# What each kind's drawing must contain, by object name. A test redraws every row and checks it,
# so a kind cannot drift away from the evidence its gold label rests on.
EVIDENCE = {
    "sign_in": ("submit",),
    "sign_in_rejected": ("error_banner",),
    "sign_in_waiting": ("spinner",),
    "sign_in_crashed": ("dialog",),
    "waiting_with_warning": ("spinner", "warning_banner"),
    "rejected_inline": ("inline_message",),
    "sign_in_with_hint": ("hint",),
    "dashboard": ("orders_bar",),
    "dashboard_crashed": ("dialog", "orders_bar"),
    "page_not_found": ("code",),
    "payment_declined": ("error_banner", "card"),
    "maintenance": ("notice",),
    "partial_render": ("placeholder_a",),
}


def _form(c, brand, seed, *, invalid=False, waiting=False, hint=False, message=None):
    """The sign-in window shared by the look-alike kinds, drawn on canvas ``c``."""
    c.window(60, 30, 520, 340, f"{brand} SIGN IN", name="window")
    c.wordmark(400, 112, 160, 48, style_seed=seed, text=brand, name="logo")
    c.text_input(80, 132, 300, 34, "DEMO.USER", label="USERNAME", name="username")
    c.text_input(
        80, 200, 300, 34, "SECRET1", label="PASSWORD", masked=True, invalid=invalid, name="password"
    )
    if message:
        c.text(80, 240, message, "red", 1, name="inline_message")
    if hint:
        c.text(80, 240, "FORGOT PASSWORD?", "red", 1, name="hint")
    if waiting:
        c.button(80, 262, 140, 40, "SIGNING IN", style="disabled", name="submit")
        c.spinner(250, 282, 16, name="spinner")
    else:
        c.button(80, 262, 140, 40, "SIGN IN", name="submit")


def _dashboard(c, brand):
    """The working dashboard: two bars and three lines of figures, drawn on canvas ``c``."""
    c.window(60, 30, 520, 340, f"{brand} DASHBOARD", name="window")
    c.text(84, 76, "ORDERS TODAY", "dark", 2)
    c.bar(84, 100, 300, 22, 0.5, fill="blue", back="grey", name="orders_bar")
    c.text(84, 140, "SUPPORT QUEUE", "dark", 2)
    c.bar(84, 164, 300, 22, 0.25, fill="green", back="grey", name="queue_bar")
    c.text_block(84, 212, ["USERS ONLINE 54", "UPTIME 99 PERCENT", "VERSION 4.2"], "ink", 2)
    c.button(420, 300, 140, 40, "REFRESH", style="secondary", name="refresh")


def app_screen(*, kind, seed=0):
    """One 640x400 invented application window of a kind ``login_screen`` does not draw.

    ``kind`` is one of the keys of ``helpers.KINDS`` that ``LOGIN_STATES`` does not name;
    ``seed`` picks the invented product name and logo. Every length is an integer, so the pixels
    are the same on every Python.
    """
    c = si.Canvas(WIDTH, HEIGHT, "light", seed=seed)
    brand = si.fictional_name(seed)
    if kind == "waiting_with_warning":
        _form(c, brand, seed, waiting=True)
        c.error_banner(
            80,
            66,
            480,
            32,
            "SLOW CONNECTION. STILL TRYING.",
            level="warning",
            name="warning_banner",
        )
    elif kind == "rejected_inline":
        _form(c, brand, seed, invalid=True, message="PASSWORD NOT RECOGNISED")
    elif kind == "sign_in_with_hint":
        _form(c, brand, seed, hint=True)
    elif kind == "dashboard":
        _dashboard(c, brand)
    elif kind == "dashboard_crashed":
        _dashboard(c, brand)
        c.dialog(
            150,
            110,
            340,
            170,
            "APPLICATION ERROR",
            ["THE APPLICATION STOPPED.", "CODE E-500"],
            buttons=("RESTART", "CLOSE"),
            dim_backdrop=55,
            name="dialog",
        )
    elif kind == "page_not_found":
        c.window(60, 30, 520, 340, f"{brand} HELP", name="window")
        c.text(230, 110, "404", "dark", 8, name="code")
        c.centered_text((60, 190, 580, 230), "PAGE NOT FOUND", "ink", 3)
        c.button(250, 270, 140, 40, "GO BACK", style="secondary", name="back")
    elif kind == "payment_declined":
        c.window(60, 30, 520, 340, f"{brand} CHECKOUT", name="window")
        c.error_banner(80, 66, 480, 32, "PAYMENT DECLINED.", name="error_banner")
        c.text_input(80, 132, 300, 34, "XXXX 0000", label="CARD", name="card")
        c.text_input(80, 200, 140, 34, "12/30", label="EXPIRY", name="expiry")
        c.button(80, 262, 140, 40, "PAY NOW", name="pay")
    elif kind == "maintenance":
        c.window(60, 30, 520, 340, f"{brand} STATUS", name="window")
        c.error_banner(80, 66, 480, 32, "DOWN FOR PLANNED WORK.", level="info", name="notice")
        c.text_block(84, 130, ["PLEASE COME BACK LATER."], "ink", 2)
    elif kind == "partial_render":
        c.window(60, 30, 520, 340, brand, name="window")
        c.rect(84, 76, 300, 22, "grey", name="placeholder_a")
        c.rect(84, 112, 200, 22, "grey", name="placeholder_b")
    else:
        raise ValueError(f"app_screen does not draw {kind!r}")
    return c.provenance("build_fixtures.py:app_screen", {"kind": kind, "seed": seed})


def draw(row):
    """The canvas of one row: the shared scene for four kinds, ``app_screen`` for the rest."""
    _ident, _split, _capture, kind, seed, _answer = row
    helpers.gold_label(kind)  # a kind nobody has labelled raises here, before any file is written
    if kind in LOGIN_STATES:
        return si.login_screen(state=LOGIN_STATES[kind], seed=seed)
    return app_screen(kind=kind, seed=seed)


def image_path(ident):
    """Where the image of example ``ident`` is saved, relative to the recipe."""
    return f"assets/screen-{ident}.png"


def describe(row):
    """What the manifest says the image of ``row`` shows."""
    return f"An invented application window drawn as {row[3]!r} (seed {row[4]})."


def write_images(rows, overwrite, *, canvases=None):
    """Validate every image and its provenance before saving; return manifest entries by path.

    A validation error or ``si.RegenerationMismatch`` leaves all destination PNGs unchanged.
    Installation is atomic per file, not a rollback transaction for later I/O failures."""
    images = [(draw(row), image_path(row[0]), describe(row)) for row in rows]
    written = si.write_assets(images, HERE, overwrite=overwrite)
    for (canvas, path, _description), (status, _entry) in zip(images, written, strict=True):
        print(f"{status}: {path}")
        if canvases is not None:
            canvases.append(canvas)
    return sorted((entry for _status, entry in written), key=lambda entry: entry["path"])


def _fields(row):
    return {"capture": row[2], "image": image_path(row[0])}


def build_inputs_and_labels(rows, *, canvases=None, keys=None):
    """``(inputs, labels)`` from ``rows``, with the images already saved. Neither ever holds a
    model's answer, so both are always safe to regenerate, even after ``responses.json`` has
    been recorded. The gold label is read from the kind that was drawn; the demo example has
    none."""
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
            labels.append({"id": ident, "label": helpers.gold_label(row[3])})
    return inputs, labels


def answers_for(row, provenance: Provenance):
    """{question name: answer} for one row, from the integer weights ``row`` names."""
    top, top_weight, second, second_weight = row[-1]
    for option in (top, second):
        if option not in helpers.OPTIONS:
            raise ValueError(f"row {row[0]!r}: {option!r} is not one of {helpers.OPTIONS}")
    if top == second:
        raise ValueError(f"row {row[0]!r}: the top and runner-up options are both {top!r}")
    if type(top_weight) is not int or type(second_weight) is not int or second_weight < 1:
        raise ValueError(f"row {row[0]!r}: answer weights must be positive integers")
    if top_weight <= second_weight:
        raise ValueError(
            f"row {row[0]!r}: the top weight {top_weight} must exceed the runner-up's {second_weight}"
        )
    weights = dict.fromkeys(helpers.OPTIONS, 1)
    weights[top], weights[second] = top_weight, second_weight
    total = 0  # integers, so any order gives the same total
    for weight in weights.values():
        total += weight
    probabilities = {option: weight / total for option, weight in weights.items()}
    return {"app_state": ChoiceAnswer.from_probabilities(probabilities, provenance)}


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
