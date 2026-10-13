"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 35.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response here is synthetic: six probabilities per example, one per feature in
``helpers.FEATURES``, written by hand (via a small deterministic pool below, never
``random``) rather than produced by a model. Several are deliberately wrong, on purpose, so
the business threshold each feature's evaluation freezes has real mistakes to find -- a
fixture set with nothing wrong would make every number that follows true by construction.

Two gold labels are authored for every ``train``, ``validation`` and ``test`` row, and
neither is computed from the other: ``features``, one bool per name in ``helpers.FEATURES``
(what the six Noul questions are judging), and ``escalate`` (what the classifier and the
baseline are trained and scored against). ROWS states both explicitly, by hand, for every row.

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

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
FEATURE_NAMES = tuple(helpers.FEATURES)

# Two pools of plausible synthetic probabilities, one for a feature read as present, one for a
# feature read as absent. Cycling through eight close-together values each (rather than one
# fixed number per side) keeps the stored probabilities off a coarse grid without spreading
# either pool so wide that a threshold chosen from a handful of validation examples could reject
# a test example on the same side of 0.5 (a sparse feature's validation threshold is the lowest
# value its few `True` examples happen to draw; a wide pool risked a test `True` example drawing
# something lower still). The cycle position is the running count of (example, feature) pairs
# built so far, in ROWS order then FEATURES order, so it is deterministic and reproducible from
# this file alone, never from the clock or `random`.
_TRUE_POOL = (0.88, 0.91, 0.89, 0.92, 0.90, 0.88, 0.91, 0.89)
_FALSE_POOL = (0.09, 0.12, 0.10, 0.08, 0.11, 0.09, 0.12, 0.10)


def _noul_for(effective_present: bool, i: int) -> float:
    """The i-th pool value for a feature that should read ``effective_present``."""
    pool = _TRUE_POOL if effective_present else _FALSE_POOL
    return pool[i % len(pool)]


# (id, split, message_id, text, features, escalate, wrong)
#
# `features`: {name: bool}, one entry per helpers.FEATURES, authored by hand for every row.
# `escalate`: the classifier's own gold label, also authored by hand -- never derived from
#   `features` -- for every `train`/`validation`/`test` row; `None` for a `demo` row (fixtures.md:
#   a label for a demo example is an error).
# `wrong`: the subset of `features` whose *stored synthetic answer* is deliberately on the
#   other side of 0.5 from `features[name]` -- a synthetic model mistake, not a mistake in the
#   gold label itself. Every feature has at least one `wrong` entry somewhere below.
#
# Fourteen scenarios (A-N) appear once per split (reworded each time, so no two splits share the
# same `state` -- the fixtures.md leak rule), plus two extra rows per split for variety and to
# reach the per-split count stated in the README. Read down any one column of `features` across
# every row below and both a True and a False case appear for every one of the six features,
# crossed with both `escalate` values -- see tests/test_helpers.py for the mechanical check.
ROWS = [
    # --- A: billing dispute, frustrated, wants a refund -> escalate
    ("tr01", "train", "M-1001",
     "I was charged $64 twice this month and it's incredibly frustrating "
     "-- I want a refund right away.",
     {"mentions_price": True, "expresses_frustration": True,
      "requests_refund_or_cancellation": True, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    ("v01", "validation", "M-2001",
     "Your system billed me $58 a second time and I am furious about it; "
     "please refund the extra charge.",
     {"mentions_price": True, "expresses_frustration": True,
      "requests_refund_or_cancellation": True, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    ("t01", "test", "M-3001",
     "I got charged $71 twice in one week, I'm really annoyed, and I need "
     "that refund processed now.",
     {"mentions_price": True, "expresses_frustration": True,
      "requests_refund_or_cancellation": True, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    # --- B: calm billing question -> not escalate
    ("tr02", "train", "M-1002",
     "Could you confirm whether the $12 monthly fee includes the extra "
     "storage add-on?",
     {"mentions_price": True, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    ("v02", "validation", "M-2002",
     "I'd like to understand what the $19 charge on my statement covers "
     "this month.",
     {"mentions_price": True, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset({"expresses_frustration"})),
    ("t02", "test", "M-3002",
     "Can you clarify if the $25 renewal fee includes next year's support "
     "plan?",
     {"mentions_price": True, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    # --- C: crash report, frustrated -> escalate
    ("tr03", "train", "M-1003",
     "The app keeps crashing every time I open the reports tab and it's "
     "driving me crazy.",
     {"mentions_price": False, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     True, frozenset()),
    ("v03", "validation", "M-2003",
     "I'm so frustrated -- the dashboard crashes constantly whenever I try "
     "to export a file.",
     {"mentions_price": False, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     True, frozenset({"reports_technical_issue"})),
    ("t03", "test", "M-3003",
     "This is maddening: the mobile app crashes the second I tap the "
     "calendar view.",
     {"mentions_price": False, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     True, frozenset()),
    # --- D: minor bug, calm -> not escalate
    ("tr04", "train", "M-1004",
     "The export button didn't respond on my first click, but a second "
     "click worked fine.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     False, frozenset()),
    ("v04", "validation", "M-2004",
     "The search bar was briefly unresponsive earlier today, though it's "
     "working normally now.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     False, frozenset()),
    ("t04", "test", "M-3004",
     "The calendar view loaded blank once this morning, but refreshing "
     "the page fixed it.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     False, frozenset({"expresses_frustration"})),
    # --- E: pure praise -> not escalate
    ("tr05", "train", "M-1005",
     "Your new dashboard layout is wonderful, everything is so much "
     "easier to find now.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset()),
    ("v05", "validation", "M-2005",
     "I really appreciate how smooth the onboarding experience has been, "
     "great work.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset()),
    ("t05", "test", "M-3005",
     "The latest update made everything feel faster and cleaner, thank "
     "you for that.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset()),
    # --- F: happy, favourably compares to a competitor -> not escalate
    ("tr06", "train", "M-1006",
     "Unlike BrightMetrics, your reports actually load instantly -- "
     "really happy with the switch.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": True,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset()),
    ("v06", "validation", "M-2006",
     "I compared you with RivalDash last year and your support has been "
     "far better since.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": True,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset()),
    ("t06", "test", "M-3006",
     "I tried NorthLedger before, but your interface is so much "
     "friendlier, I'm glad I stayed.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": True,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset({"expresses_satisfaction"})),
    # --- G: calm cancellation, no longer needed -> escalate
    ("tr07", "train", "M-1007",
     "I'd like to cancel my subscription -- I simply don't need the "
     "service anymore.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": True, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    ("v07", "validation", "M-2007",
     "Please cancel my plan at the end of the billing cycle, no issues, "
     "just downsizing.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": True, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    ("t07", "test", "M-3007",
     "I want to cancel next month's renewal since my project wrapped up "
     "early.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": True, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    # --- H: frustrated, names a competitor, technical issue -> escalate
    ("tr08", "train", "M-1008",
     "I'm extremely frustrated that the sync feature keeps failing -- "
     "CloudPeak never had this problem.",
     {"mentions_price": False, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": True,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     True, frozenset({"mentions_competitor"})),
    ("v08", "validation", "M-2008",
     "This constant syncing error is infuriating, and OrbitSuite handled "
     "the same task flawlessly.",
     {"mentions_price": False, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": True,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     True, frozenset()),
    ("t08", "test", "M-3008",
     "I'm furious the import tool keeps erroring out; VaultFlow never "
     "gave me this trouble.",
     {"mentions_price": False, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": True,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     True, frozenset()),
    # --- I: positive remark about the price itself -> not escalate
    ("tr09", "train", "M-1009",
     "The new $9 starter price is a fantastic deal, I'm thrilled with "
     "the value.",
     {"mentions_price": True, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset()),
    ("v09", "validation", "M-2009",
     "Thanks for keeping the $14 plan so affordable, it's genuinely "
     "great value for the features.",
     {"mentions_price": True, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset()),
    ("t09", "test", "M-3009",
     "I love that the $7 tier covers everything I need, what a "
     "wonderful price.",
     {"mentions_price": True, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset({"mentions_price"})),
    # --- J: frustration in the past tense, already resolved -> not escalate
    ("tr10", "train", "M-1010",
     "I was frustrated about the login issue last week, but support "
     "fixed it quickly, thanks.",
     {"mentions_price": False, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    ("v10", "validation", "M-2010",
     "I was annoyed about the delay earlier, but it's resolved now and "
     "I'm all set.",
     {"mentions_price": False, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    ("t10", "test", "M-3010",
     "I was upset about the missing invoice, but it arrived today, so "
     "we're good now.",
     {"mentions_price": False, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    # --- K: neutral product question, nothing active -> not escalate
    ("tr11", "train", "M-1011",
     "Does the mobile app support dark mode on tablets as well as "
     "phones?",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    ("v11", "validation", "M-2011",
     "Is there a way to export reports directly to a shared drive "
     "folder?",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    ("t11", "test", "M-3011",
     "Will the calendar integration work with a shared team calendar "
     "too?",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    # --- L: a long-time customer quietly leaving, no feature active -> escalate
    ("tr12", "train", "M-1012",
     "I've been with you for nine years, and this will be my last "
     "renewal.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    ("v12", "validation", "M-2012",
     "After a long time as a customer, I don't think I'll be renewing "
     "again.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    ("t12", "test", "M-3012",
     "This has been a good run over the years, but I won't be "
     "continuing with you.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    # --- M: a benign, administrative cancellation -> not escalate
    ("tr13", "train", "M-1013",
     "I'd like to cancel the extra seat on my plan, it's just not being "
     "used.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": True, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    ("v13", "validation", "M-2013",
     "Please remove the unused add-on from my account, nothing else "
     "needs changing.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": True, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    ("t13", "test", "M-3013",
     "Can you cancel the second license on my account, we only need "
     "the one.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": True, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset({"requests_refund_or_cancellation"})),
    # --- N: generally positive, but an unresolved technical issue -> escalate
    ("tr14", "train", "M-1014",
     "I really love the product, but the export keeps crashing and "
     "losing my data -- please call me.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": True},
     True, frozenset({"expresses_satisfaction"})),
    ("v14", "validation", "M-2014",
     "You've been great overall, but this repeated sync failure is "
     "costing me real work, I need a call.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": True},
     True, frozenset({"expresses_satisfaction"})),
    ("t14", "test", "M-3014",
     "I'm a big fan of the product, yet the report builder keeps "
     "freezing and I need someone to look into it.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": True},
     True, frozenset()),
    # --- extra rows: two per split, for variety and to reach the stated per-split count
    ("tr15", "train", "M-1015",
     "I was charged $82 again, I'm furious, I want a refund, the app "
     "crashes constantly, and I'm seriously considering RivalDash "
     "instead.",
     {"mentions_price": True, "expresses_frustration": True,
      "requests_refund_or_cancellation": True, "mentions_competitor": True,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     True, frozenset()),
    ("tr16", "train", "M-1016",
     "Do you offer an API key with read-only access for internal "
     "reporting?",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     False, frozenset()),
    ("v15", "validation", "M-2015",
     "The payment page keeps throwing an error when I try to update my "
     "$45 card on file, and it's honestly maddening.",
     {"mentions_price": True, "expresses_frustration": True,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     True, frozenset()),
    ("v16", "validation", "M-2016",
     "Thanks for the loyalty discount on my $30 renewal this year, "
     "much appreciated!",
     {"mentions_price": True, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     False, frozenset()),
    ("t15", "test", "M-3015",
     "I'm cancelling my plan and moving to NorthLedger, please process "
     "my refund as soon as possible.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": True, "mentions_competitor": True,
      "reports_technical_issue": False, "expresses_satisfaction": False},
     True, frozenset()),
    ("t16", "test", "M-3016",
     "Found a small glitch in the export yesterday, but it resolved "
     "itself after a refresh, no big deal.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     False, frozenset({"reports_technical_issue"})),
    # --- demo: shown to the reader, never scored (no label)
    ("d01", "demo", "M-9001",
     "My invoice doubled this month, and now the payment page keeps "
     "timing out when I try to fix it.",
     {"mentions_price": True, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": True, "expresses_satisfaction": False},
     None, frozenset()),
    ("d02", "demo", "M-9002",
     "Everything has been working great, though I did want to ask about "
     "upgrading my plan.",
     {"mentions_price": False, "expresses_frustration": False,
      "requests_refund_or_cancellation": False, "mentions_competitor": False,
      "reports_technical_issue": False, "expresses_satisfaction": True},
     None, frozenset()),
]  # fmt: skip


def _fields(message_id, text):
    return {"message_id": message_id, "text": text}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, message_id, text, features, escalate, _wrong in rows:
        fields = _fields(message_id, text)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if escalate is not None:
            labels.append(
                {"id": ident, "label": {"features": dict(features), "escalate": escalate}}
            )
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    i = 0  # running (example, feature) count, for _noul_for's pool position
    for _ident, _split, message_id, text, features, _escalate, wrong in rows:
        fields = _fields(message_id, text)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = {}
        for name in FEATURE_NAMES:
            gold = features[name]
            effective = (not gold) if name in wrong else gold
            p = _noul_for(effective, i)
            i += 1
            answers[name] = NoulAnswer(p, Provenance.synthetic())
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
