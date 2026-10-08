"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 02.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as a probability, not produced by a model) and
deliberately imperfect. The hard cases the issue names are included and tagged in their id: a
complaint with no request (``-complaint``), a question about refund policy (``-policy``), a
request for a replacement instead of a refund (``-replacement``), and a refund mentioned only in
passing (``-mention``). Two more near misses are included because they come up constantly in real
refund workflows even though the issue does not name them: asking for store credit instead of a
refund (``-credit``) and a vague future possibility (``-conditional``). Both validation and test
also carry one message that is wrong *and* confident (``-hard-wrong``): declining a refund in the
same breath as raising it, stored at a noul high enough to clear the threshold this recipe's
notebook freezes (0.80) even though the gold label is false -- so the frozen threshold's numbers
show a real, non-zero risk of a wrongly queued message on both splits, not a guarantee that
happens to hold. The replay keys come from the same ``build_state`` and ``build_questions`` the
notebook uses, via ``helpers.py``.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# (id, split, ticket_id, text, gold label (bool) or None for demo, stored noul probability)
ROWS = [
    # --- validation: 19 examples --------------------------------------------------------------
    ("v01-explicit", "validation", "RF1001",
     "I'd like a refund for this order, it arrived broken.",
     True, 0.93),
    ("v02-explicit", "validation", "RF1002",
     "Please refund my purchase, the size is completely wrong.",
     True, 0.91),
    ("v03-moneyback", "validation", "RF1003",
     "This isn't what I ordered, I want my money back.",
     True, 0.85),
    ("v04-angry", "validation", "RF1004",
     "This is unacceptable. Give me my money back right now.",
     True, 0.92),
    ("v05-question", "validation", "RF1005",
     "Can I get a refund for this item?",
     True, 0.88),
    ("v06-buried", "validation", "RF1006",
     "Thanks for the fast shipping, by the way, can I get a refund since the color is wrong?",
     True, 0.80),
    ("v07-duplicate", "validation", "RF1007",
     "I was charged twice for the same order, please refund the extra charge.",
     True, 0.91),
    ("v08-short", "validation", "RF1008",
     "Refund please.",
     True, 0.86),
    ("v09-complaint", "validation", "RF1009",
     "This product is terrible and stopped working after two days.",
     False, 0.05),
    ("v10-complaint", "validation", "RF1010",
     "I'm very disappointed with the quality of this blanket.",
     False, 0.07),
    ("v11-policy", "validation", "RF1011",
     "What is your refund policy if I don't like the product?",
     False, 0.20),
    ("v12-replacement", "validation", "RF1012",
     "Can you send me a replacement? Mine arrived with a crack in it.",
     False, 0.10),
    ("v13-mention", "validation", "RF1013",
     "I got a refund last month for a different order, but this time I just have a sizing "
     "question.",
     False, 0.18),
    ("v14-cancel", "validation", "RF1014",
     "I want to cancel my subscription before the next billing cycle.",
     False, 0.09),
    ("v15-credit", "validation", "RF1015",
     "Instead of a refund, can I just get store credit for the difference?",
     False, 0.30),
    ("v16-return", "validation", "RF1016",
     "Is it possible to return this item I bought last week?",
     False, 0.35),
    ("v17-thanks", "validation", "RF1017",
     "Thank you so much for resolving my issue so quickly!",
     False, 0.03),
    ("v18-conditional", "validation", "RF1018",
     "I might ask for a refund if this isn't fixed soon, but let's try that first.",
     False, 0.33),
    ("v19-hard-wrong", "validation", "RF1019",
     "I thought about asking for a refund, but honestly I'd rather just keep it and have it "
     "repaired.",
     False, 0.95),
    # --- test: 19 examples -----------------------------------------------------------------
    ("t01-explicit", "test", "RF2001",
     "I need a refund for this order, it showed up damaged.",
     True, 0.92),
    ("t02-explicit", "test", "RF2002",
     "Please refund my payment, the item doesn't match the description.",
     True, 0.90),
    ("t03-moneyback", "test", "RF2003",
     "This is not the product I ordered, I want my money back.",
     True, 0.84),
    ("t04-angry", "test", "RF2004",
     "Completely unacceptable. I want my money back immediately.",
     True, 0.90),
    ("t05-question", "test", "RF2005",
     "Could I get a refund on this purchase?",
     True, 0.87),
    ("t06-buried", "test", "RF2006",
     "Loved the packaging, by the way, can I get a refund because the item is the wrong size?",
     True, 0.78),
    ("t07-duplicate", "test", "RF2007",
     "I noticed I was billed twice for one order, please refund the duplicate charge.",
     True, 0.89),
    ("t08-short", "test", "RF2008",
     "Refund now.",
     True, 0.84),
    ("t09-complaint", "test", "RF2009",
     "This product broke after only two uses and I'm really frustrated.",
     False, 0.06),
    ("t10-complaint", "test", "RF2010",
     "I'm unhappy with how thin this towel turned out to be.",
     False, 0.07),
    ("t11-policy", "test", "RF2011",
     "What's the refund policy if the product doesn't fit?",
     False, 0.22),
    ("t12-replacement", "test", "RF2012",
     "Could you send a replacement part? The one I received was cracked.",
     False, 0.10),
    ("t13-mention", "test", "RF2013",
     "I received a refund on a previous order, but right now I just want to know about sizing.",
     False, 0.17),
    ("t14-cancel", "test", "RF2014",
     "Please cancel my subscription before it renews next month.",
     False, 0.11),
    ("t15-credit", "test", "RF2015",
     "Rather than a refund, could I get store credit instead?",
     False, 0.28),
    ("t16-return", "test", "RF2016",
     "Can I return the jacket I bought two weeks ago?",
     False, 0.33),
    ("t17-thanks", "test", "RF2017",
     "Thanks for fixing my issue so fast, I really appreciate it!",
     False, 0.04),
    ("t18-conditional", "test", "RF2018",
     "If this keeps happening I might ask for a refund, but let's see if it gets fixed.",
     False, 0.31),
    ("t19-hard-wrong", "test", "RF2019",
     "I considered asking for a refund, but I've decided to keep it and just get it repaired "
     "instead.",
     False, 0.85),
    # --- demo: 2 examples, shown but never scored ----------------------------------------------
    ("d01-explicit", "demo", "RF3001",
     "The shoes I ordered arrived two sizes too small. I'd like a refund, please.",
     None, 0.94),
    ("d02-policy", "demo", "RF3002",
     "What's your refund policy if this doesn't work out for me?",
     None, 0.25),
]  # fmt: skip


def answers_for(spec: float, provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Noul answer, ``spec`` the probability."""
    return {"refund_requested": NoulAnswer(spec, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, ticket_id, text, label, _noul in rows:
        fields = {"ticket_id": ticket_id, "text": text}
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, ticket_id, text, _label, noul in rows:
        fields = {"ticket_id": ticket_id, "text": text}
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(noul, Provenance.synthetic())
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
    # sorted; each response keeps the field order DecisionResult.to_dict() emits.
    text = json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n"
    responses_file.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
