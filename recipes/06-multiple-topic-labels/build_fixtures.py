"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 06.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as five probabilities, one per label in
``helpers.LABELS``, not produced by a model) and deliberately imperfect. The gold label for
each example is the *set* of topics it actually raises: some examples raise none, most raise
one or two, and a few raise three or four at once (the hard cases this use case calls for: items
with no label and items with three or more).

Several examples use a word associated with a label ("price", "feature") without the feedback
actually raising that topic: a benign look-alike (CONTRIBUTING.md section 5), not S07's
"literal reading" (item 1), which is about the model reading a question's *instructions*
literally, not a surface word in the state. ``v16-lookalike-wrong`` (validation) and
``t16-lookalike-wrong`` (test) both store a confident ``feature_request`` probability (0.80 and
0.82) for feedback that only mentions a *past* feature, never a request; ``t16``'s is wrong
*and* confident on purpose, so the evaluation has a real, non-zero risk to find rather than a
threshold that happens to catch everything.

The replay keys come from the same ``build_state`` and ``build_questions`` the notebook uses,
via ``helpers.py``. Generating inputs and labels is kept separate from generating responses, on
purpose: once ``responses.json`` holds even one recorded answer (provenance ``"recorded"``,
captured from a real Jev call), running this script again must not silently replace it with a
synthetic probability. ``inputs.jsonl`` and ``labels.jsonl`` are always rewritten from ``ROWS``,
because neither ever holds a model's answer; ``responses.json`` is rewritten only when it does
not yet exist, holds only synthetic answers, or ``--force`` is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
LABELS = list(helpers.LABELS)  # pricing, reliability, usability, support, feature_request

# (id, split, feedback_id, text, gold labels (tuple, () for none; None for a demo example that
# is never scored), stored probabilities in LABELS order)
ROWS = [
    # --- validation: 19 examples ------------------------------------------------------------
    ("v01", "validation", "FB-101",
     "The onboarding tour was confusing and I couldn't find the settings page.",
     ("usability",), (0.50, 0.54, 0.82, 0.10, 0.06)),
    ("v02", "validation", "FB-102",
     "You charged me twice for my annual subscription.",
     ("pricing",), (0.90, 0.04, 0.05, 0.46, 0.03)),
    ("v03", "validation", "FB-103",
     "The app crashes every time I open the export screen.",
     ("reliability",), (0.04, 0.88, 0.58, 0.05, 0.04)),
    ("v04", "validation", "FB-104",
     "Support took five days to answer a simple question.",
     ("support",), (0.05, 0.06, 0.04, 0.40, 0.05)),
    ("v05", "validation", "FB-105",
     "Could you add a dark mode? I'd love that option.",
     ("feature_request",), (0.03, 0.04, 0.08, 0.03, 0.50)),
    ("v06", "validation", "FB-106",
     "The checkout flow is clunky and the renewal price went up without warning.",
     ("pricing", "usability"), (0.78, 0.07, 0.70, 0.08, 0.56)),
    ("v07", "validation", "FB-107",
     "Everything has been great, thanks for a solid product!",
     (), (0.06, 0.05, 0.07, 0.08, 0.04)),
    ("v08", "validation", "FB-108",
     "Nice weather today, just wanted to say hi.",
     (), (0.02, 0.02, 0.03, 0.02, 0.02)),
    ("v09-lookalike", "validation", "FB-109",
     "I would pay any price for support this good — the rep fixed my issue in minutes.",
     ("support",), (0.42, 0.08, 0.06, 0.83, 0.05)),
    ("v10", "validation", "FB-110",
     "The dashboard redesign is beautiful but I can't figure out where the reports moved to.",
     ("usability",), (0.05, 0.09, 0.66, 0.07, 0.05)),
    ("v11", "validation", "FB-111",
     "Can you add an API so we can integrate with our own tools?",
     ("feature_request",), (0.04, 0.05, 0.06, 0.04, 0.88)),
    ("v12-mixed3", "validation", "FB-112",
     "My invoice was wrong, the app keeps freezing when I try to fix it myself, and the menus "
     "are impossible to navigate.",
     ("pricing", "reliability", "usability"), (0.75, 0.80, 0.68, 0.12, 0.05)),
    ("v13", "validation", "FB-113",
     "The refund I was promised never showed up on my statement.",
     ("pricing",), (0.86, 0.05, 0.04, 0.10, 0.03)),
    ("v14", "validation", "FB-114",
     "Login works fine now after the last update, nice fix.",
     ("reliability",), (0.04, 0.47, 0.08, 0.05, 0.04)),
    ("v15", "validation", "FB-115",
     "Your support rep was rude and unhelpful when I called about my renewal charge.",
     ("support", "pricing"), (0.44, 0.06, 0.05, 0.84, 0.04)),
    ("v16-lookalike-wrong", "validation", "FB-116",
     "The new filters feature is exactly what we asked for, thank you!",
     (), (0.05, 0.05, 0.10, 0.06, 0.80)),
    ("v17", "validation", "FB-117",
     "I can't tell if I'm being charged monthly or yearly — the billing page is confusing.",
     ("pricing", "usability"), (0.74, 0.08, 0.52, 0.15, 0.05)),
    ("v18", "validation", "FB-118",
     "Please add two-factor authentication; also the app froze twice during setup.",
     ("feature_request", "reliability"), (0.05, 0.70, 0.12, 0.06, 0.82)),
    ("v19-many", "validation", "FB-119",
     "This costs too much for what it does, keeps crashing on Android, the UI is a maze, and "
     "nobody from support ever replies.",
     ("pricing", "reliability", "usability", "support"), (0.88, 0.85, 0.80, 0.78, 0.05)),
    # --- test: 19 examples -------------------------------------------------------------------
    ("t01", "test", "FB-201",
     "I was billed for a plan I cancelled months ago.",
     ("pricing",), (0.89, 0.05, 0.04, 0.07, 0.03)),
    ("t02", "test", "FB-202",
     "The app freezes whenever I try to upload a photo.",
     ("reliability",), (0.04, 0.86, 0.08, 0.05, 0.04)),
    ("t03", "test", "FB-203",
     "I love how intuitive the new layout is.",
     ("usability",), (0.05, 0.06, 0.64, 0.05, 0.04)),
    ("t04", "test", "FB-204",
     "Support never resolved my ticket after three follow-ups.",
     ("support",), (0.05, 0.06, 0.04, 0.82, 0.04)),
    ("t05", "test", "FB-205",
     "Would you consider adding calendar sync?",
     ("feature_request",), (0.03, 0.04, 0.06, 0.03, 0.86)),
    ("t06", "test", "FB-206",
     "Signing up was a breeze and the price is fair for what you get.",
     ("usability", "pricing"), (0.68, 0.07, 0.72, 0.06, 0.04)),
    ("t07", "test", "FB-207",
     "Just wanted to say the team is doing a great job overall.",
     (), (0.06, 0.05, 0.06, 0.09, 0.04)),
    ("t08", "test", "FB-208",
     "Hope you're having a nice day over there!",
     (), (0.02, 0.02, 0.02, 0.02, 0.02)),
    ("t09-lookalike", "test", "FB-209",
     "The report export finally works, no more missing features from last month.",
     ("reliability",), (0.04, 0.72, 0.10, 0.05, 0.38)),
    ("t10", "test", "FB-210",
     "The settings menu is buried three levels deep and impossible to find.",
     ("usability",), (0.04, 0.06, 0.80, 0.05, 0.04)),
    ("t11", "test", "FB-211",
     "Can you support dark mode and larger font sizes for accessibility?",
     ("feature_request",), (0.03, 0.04, 0.10, 0.04, 0.84)),
    ("t12-mixed3", "test", "FB-212",
     "The checkout crashed twice, the fee breakdown makes no sense, and I had to explain my "
     "issue to three different agents.",
     ("pricing", "reliability", "support"), (0.74, 0.80, 0.15, 0.70, 0.05)),
    ("t13", "test", "FB-213",
     "My refund request has been pending for two weeks with no update.",
     ("pricing",), (0.84, 0.05, 0.04, 0.12, 0.03)),
    ("t14-lookalike", "test", "FB-214",
     "The new homepage loads fast and looks clean.",
     (), (0.03, 0.40, 0.12, 0.03, 0.03)),
    ("t15", "test", "FB-215",
     "The support agent was condescending when I asked about my upgrade cost.",
     ("support", "pricing"), (0.70, 0.06, 0.08, 0.85, 0.04)),
    ("t16-lookalike-wrong", "test", "FB-216",
     "Finally! The new bulk-export feature request we filed last year shipped.",
     (), (0.04, 0.05, 0.06, 0.05, 0.82)),
    ("t17-mixed3", "test", "FB-217",
     "I'm not sure if I'm on the right plan — the pricing page is confusing and support "
     "couldn't explain it either.",
     ("pricing", "usability", "support"), (0.76, 0.07, 0.60, 0.66, 0.05)),
    ("t18", "test", "FB-218",
     "Add an undo button, please — I just lost an hour of work when the app crashed.",
     ("feature_request", "reliability"), (0.04, 0.78, 0.10, 0.05, 0.80)),
    ("t19-many", "test", "FB-219",
     "The subscription keeps auto-renewing at a higher rate, the app crashes on startup, the "
     "UI changes every update without explanation, and support closed my ticket without "
     "responding.",
     ("pricing", "reliability", "usability", "support"), (0.90, 0.82, 0.76, 0.80, 0.04)),
    # --- demo: 2 examples, shown but never scored --------------------------------------------
    ("d01-mixed3", "demo", "FB-301",
     "The checkout flow is clunky and the renewal price went up without warning, and now I "
     "can't reach anyone on support.",
     None, (0.80, 0.08, 0.74, 0.72, 0.05)),
    ("d02-none", "demo", "FB-302",
     "Just a quick note to say thanks for a great product overall!",
     None, (0.03, 0.03, 0.04, 0.05, 0.03)),
]  # fmt: skip


def _fields(feedback_id, text):
    return {"feedback_id": feedback_id, "text": text}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded. A gold label is
    the sorted list of topics the example raises (``[]`` for none); ``docs/fixtures.md``
    requires every scored example to have exactly one label value, and a list is one value."""
    inputs, labels = [], []
    for ident, split, feedback_id, text, gold, _probs in rows:
        fields = _fields(feedback_id, text)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if gold is not None:
            labels.append({"id": ident, "label": sorted(gold)})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, feedback_id, text, _gold, probs in rows:
        fields = _fields(feedback_id, text)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = {
            label: NoulAnswer(p, Provenance.synthetic())
            for label, p in zip(LABELS, probs, strict=True)
        }
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
