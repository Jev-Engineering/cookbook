"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 01.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect: a few are wrong, several more are right but at low confidence, and one
(``t16-mixed``) is wrong *and* confident, at 0.6000, comfortably above the threshold this recipe's
notebook freezes on validation (0.4933) -- so the notebook's selective-prediction numbers show a
real, non-zero risk on test rather than a guarantee that happens to hold. The use case's hard cases
are included and tagged in their id: sarcasm (``-sarcasm``), a review that praises one thing
and condemns another (``-mixed``), a neutral statement of fact (``-neutral-fact``), and a very
short review (``-short``). The replay keys come from the same ``build_state`` and
``build_questions`` the notebook uses, via ``helpers.py``.

Generating inputs and labels is kept separate from generating responses, on purpose (the pattern
``recipes/_template/build_fixtures.py`` sets): once responses.json holds even one recorded answer
(provenance "recorded", captured from a real Jev call), running this script again must not
silently replace it with a synthetic probability. inputs.jsonl and labels.jsonl are always
rewritten from ROWS, because neither ever holds a model's answer; responses.json is rewritten only
when it does not yet exist, holds only synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
OPTIONS = list(QUESTIONS["sentiment"].criteria)  # positive, neutral, negative, mixed

# (id, split, review_id, text, gold label or None for demo, stored probabilities)
# Probabilities are in OPTIONS order (positive, neutral, negative, mixed) and sum to 1.
ROWS = [
    # --- validation: 19 examples -------------------------------------------------------------
    ("v01-positive", "validation", "R1001",
     "This blender crushed ice perfectly on the first try. I'm thrilled with how powerful it is.",
     "positive", (0.90, 0.04, 0.03, 0.03)),
    ("v02-positive", "validation", "R1002",
     "Fits like a glove and the fabric feels great against my skin. Love it!",
     "positive", (0.88, 0.05, 0.03, 0.04)),
    ("v03-sarcasm", "validation", "R1003",
     "Great, it broke on the second use. Exactly what I was hoping for.",
     "negative", (0.58, 0.07, 0.28, 0.07)),
    ("v04-short", "validation", "R1004",
     "Perfect.",
     "positive", (0.68, 0.17, 0.08, 0.07)),
    ("v05-neutral-fact", "validation", "R1005",
     "The box arrived on Tuesday, two days after the confirmation email.",
     "neutral", (0.10, 0.78, 0.06, 0.06)),
    ("v06-negative", "validation", "R1006",
     "The charger only outputs five watts even though the listing says twenty.",
     "negative", (0.06, 0.10, 0.80, 0.04)),
    ("v07-negative", "validation", "R1007",
     "Customer service never answered my three emails about the missing part.",
     "negative", (0.04, 0.08, 0.85, 0.03)),
    ("v08-short", "validation", "R1008",
     "Broken.",
     "negative", (0.09, 0.19, 0.63, 0.09)),
    ("v09-mixed", "validation", "R1009",
     "The sound quality is excellent, but the battery dies in under an hour.",
     "mixed", (0.22, 0.05, 0.18, 0.55)),
    ("v10-mixed", "validation", "R1010",
     "I love the color, but the zipper jammed on day one and won't budge.",
     "mixed", (0.18, 0.04, 0.26, 0.52)),
    ("v11-short", "validation", "R1011",
     "It arrived.",
     "neutral", (0.12, 0.55, 0.12, 0.21)),
    ("v12-neutral-fact", "validation", "R1012",
     "Setup took five minutes and the manual matches the actual buttons on the device.",
     "neutral", (0.14, 0.71, 0.08, 0.07)),
    ("v13-positive", "validation", "R1013",
     "This jacket kept me warm on a freezing hike and the pockets are huge.",
     "positive", (0.84, 0.06, 0.05, 0.05)),
    ("v14-negative", "validation", "R1014",
     "The app crashes every time I try to export a file, which makes it unusable for my job.",
     "negative", (0.05, 0.07, 0.83, 0.05)),
    ("v15-sarcasm", "validation", "R1015",
     "Wonderful, the one feature I needed is the one they forgot to include.",
     "negative", (0.18, 0.08, 0.62, 0.12)),
    ("v16-mixed", "validation", "R1016",
     "The screen looks amazing in daylight, but under any indoor lighting it washes out completely.",
     "mixed", (0.30, 0.05, 0.15, 0.50)),
    ("v17-neutral-fact", "validation", "R1017",
     "Comes in a box, with a cable and a quick-start card inside.",
     "neutral", (0.08, 0.80, 0.06, 0.06)),
    ("v18-short", "validation", "R1018",
     "Meh.",
     "neutral", (0.22, 0.40, 0.23, 0.15)),
    ("v19-positive", "validation", "R1019",
     "The blades stay sharp and the motor runs quiet even at full speed.",
     "positive", (0.86, 0.06, 0.04, 0.04)),
    # --- test: 19 examples ---------------------------------------------------------------------
    ("t01-positive", "test", "R2001",
     "The espresso machine heats up in under a minute and the shots taste like the cafe down the street.",
     "positive", (0.89, 0.05, 0.03, 0.03)),
    ("t02-positive", "test", "R2002",
     "These sheets are impossibly soft and held up great after a dozen washes.",
     "positive", (0.85, 0.07, 0.04, 0.04)),
    ("t03-sarcasm", "test", "R2003",
     "Lovely, the strap snapped before I even left the store. Just lovely.",
     "negative", (0.60, 0.06, 0.27, 0.07)),
    ("t04-short", "test", "R2004",
     "Great.",
     "positive", (0.66, 0.18, 0.09, 0.07)),
    ("t05-neutral-fact", "test", "R2005",
     "The package included the cable, the stand, and a printed warranty card.",
     "neutral", (0.09, 0.79, 0.06, 0.06)),
    ("t06-negative", "test", "R2006",
     "The fan rattles so loudly on high speed that I can't use it at night.",
     "negative", (0.05, 0.09, 0.82, 0.04)),
    ("t07-negative", "test", "R2007",
     "Support closed my ticket twice without fixing the login issue.",
     "negative", (0.04, 0.07, 0.86, 0.03)),
    ("t08-short", "test", "R2008",
     "Useless.",
     "negative", (0.08, 0.17, 0.66, 0.09)),
    ("t09-mixed", "test", "R2009",
     "The camera takes beautiful photos in daylight, but every indoor shot comes out blurry.",
     "mixed", (0.24, 0.05, 0.19, 0.52)),
    ("t10-mixed", "test", "R2010",
     "I like the design, but the handle cracked after one trip through the dishwasher.",
     "mixed", (0.20, 0.04, 0.24, 0.52)),
    ("t11-short", "test", "R2011",
     "It works.",
     "neutral", (0.16, 0.52, 0.13, 0.19)),
    ("t12-neutral-fact", "test", "R2012",
     "Installed it myself in about ten minutes following the included diagram.",
     "neutral", (0.13, 0.72, 0.08, 0.07)),
    ("t13-positive", "test", "R2013",
     "This backpack held up through three flights and still looks new.",
     "positive", (0.83, 0.06, 0.06, 0.05)),
    ("t14-negative", "test", "R2014",
     "The battery drains to zero overnight even when the laptop is fully powered off.",
     "negative", (0.06, 0.08, 0.81, 0.05)),
    ("t15-sarcasm", "test", "R2015",
     "Fantastic, the replacement part doesn't fit either. Fantastic.",
     "negative", (0.20, 0.07, 0.58, 0.15)),
    ("t16-mixed", "test", "R2016",
     "The keyboard feels great to type on, but two keys stopped registering within a week.",
     "mixed", (0.70, 0.05, 0.10, 0.15)),
    ("t17-neutral-fact", "test", "R2017",
     "Ships in a plain box with the unit wrapped in foam.",
     "neutral", (0.07, 0.82, 0.05, 0.06)),
    ("t18-short", "test", "R2018",
     "Fine.",
     "neutral", (0.46, 0.30, 0.14, 0.10)),
    ("t19-positive", "test", "R2019",
     "The drill has plenty of torque and the battery lasts through a full afternoon of work.",
     "positive", (0.87, 0.05, 0.04, 0.04)),
    # --- demo: 2 examples, shown but never scored -----------------------------------------------
    ("d01-mixed", "demo", "R3001",
     "The toaster browns evenly, but the crumb tray is impossible to remove for cleaning.",
     None, (0.20, 0.05, 0.20, 0.55)),
    ("d02-short", "demo", "R3002",
     "Fine, I guess.",
     None, (0.30, 0.35, 0.20, 0.15)),
]  # fmt: skip


def answers_for(probabilities: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the four options."""
    return {
        "sentiment": ChoiceAnswer.from_probabilities(
            dict(zip(OPTIONS, probabilities, strict=True)), provenance
        )
    }


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, review_id, text, label, _probs in rows:
        fields = {"review_id": review_id, "text": text}
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, review_id, text, _label, probs in rows:
        fields = {"review_id": review_id, "text": text}
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(probs, Provenance.synthetic())
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
    if not ROWS:
        raise SystemExit("add examples to ROWS in build_fixtures.py")
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
