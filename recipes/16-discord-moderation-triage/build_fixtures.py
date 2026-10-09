"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 16.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect. The hard cases rotate through both scored splits with different
wording each time: sarcasm (``v06``/``t06``/``t15``), a message that quotes or reports someone
else's abusive words rather than being abusive itself (``v07``/``t07``), borderline banter
between members (``v08``/``t08``/``v12``/``t12``/``v15``/``v18``/``v19``/``t19``), and a benign
message that merely contains a word the rule's examples mention (``v03``/``v16``/``t03``/``t16``).

Three stored answers are wrong on purpose, each illustrating a different failure shape:

* ``v07-quoted-abuse`` is wrong *and* confident, 0.6700, just below the threshold this recipe's
  notebook freezes on validation (0.7600, chosen on the other eleven gated validation examples),
  so it is the one example this recipe's threshold is chosen to exclude: a sarcastic report of
  someone else's abusive words read, confidently, as violating in its own right (S07 item 6,
  "adversarial content": Jev does not treat the state as hostile by default, so a message that
  only *quotes* hostile words can read as hostile itself).
* ``t07-quoted-abuse`` is the same shape of mistake on `test`, but at low confidence, 0.1300, so
  the frozen threshold catches it and sends it to review instead of reporting a wrong result.
* ``t15-false-allow`` is a sarcastic jab read, confidently (0.7000), as a genuine compliment:
  ``allowed`` never passes through the confidence gate at all (no side effect to protect), so
  this is a mistake the gate cannot catch structurally, not one it failed to catch.
* ``t17-false-flag`` is ordinary competitive trash talk read, confidently (0.7750), as a threat:
  a benign message wrongly hidden, the cost on the other side of a false allow.

The replay keys come from the same ``build_state`` and ``build_questions`` the notebook uses, via
``helpers.py``.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
OPTIONS = list(QUESTIONS["triage"].criteria)  # allowed, review_needed, potentially_violating

# (id, split, fields, gold label or None for demo, stored probabilities in OPTIONS order)
ROWS = [
    # --- validation: 19 examples ------------------------------------------------------------
    ("v01-allowed-friendly", "validation", {
        "message_id": "MSG-5001", "author": "pixel_otter",
        "message": "gg everyone, that was such a fun match tonight!",
    }, "allowed", (0.90, 0.06, 0.04)),
    ("v02-allowed-compliment", "validation", {
        "message_id": "MSG-5002", "author": "nova_badger",
        "message": "@quiet_lynx your stream setup looks awesome, nice work!",
    }, "allowed", (0.88, 0.07, 0.05)),
    ("v03-trigger-word", "validation", {
        "message_id": "MSG-5003", "author": "glitchy_wren",
        "message": "this boss fight is insane, I want to kill something lol, final phase is rough",
    }, "allowed", (0.84, 0.11, 0.05)),
    ("v04-violating-insult", "validation", {
        "message_id": "MSG-5004", "author": "driftwood92",
        "message": "@star_finch you're pathetic and nobody here actually likes you, just leave "
        "the server already",
    }, "potentially_violating", (0.03, 0.07, 0.90)),
    ("v05-violating-exclude", "validation", {
        "message_id": "MSG-5005", "author": "echo_marmot",
        "message": "we don't want you in our group anymore, stop queuing with us, nobody "
        "invited you",
    }, "potentially_violating", (0.04, 0.08, 0.88)),
    ("v06-sarcasm", "validation", {
        "message_id": "MSG-5006", "author": "cobalt_heron",
        "message": "oh sure, because YOU are definitely the best player in this server, "
        "congratulations on that",
    }, "review_needed", (0.08, 0.87, 0.05)),
    ("v07-quoted-abuse", "validation", {
        "message_id": "MSG-5007", "author": "misty_falcon",
        "message": "can a mod look at this? dax told me 'nobody wants you here, just quit "
        "already' in general chat yesterday",
    }, "review_needed", (0.05, 0.17, 0.78)),
    ("v08-banter", "validation", {
        "message_id": "MSG-5008", "author": "amber_vole",
        "message": "lol you're actually the worst at this game, I can't even, how do you keep "
        "dying there",
    }, "review_needed", (0.20, 0.65, 0.15)),
    ("v09-allowed-disagreement", "validation", {
        "message_id": "MSG-5009", "author": "quiet_lynx",
        "message": "I really disagree with your strategy call there, I think we should have "
        "rotated earlier",
    }, "allowed", (0.80, 0.15, 0.05)),
    ("v10-violating-doxx-hint", "validation", {
        "message_id": "MSG-5010", "author": "star_finch",
        "message": "I found @glitchy_wren's real address from an old post, should I post it "
        "here so everyone knows where they live",
    }, "potentially_violating", (0.05, 0.10, 0.85)),
    ("v11-allowed-joke", "validation", {
        "message_id": "MSG-5011", "author": "driftwood92",
        "message": "I'm so bad at this game it's actually impressive, send help",
    }, "allowed", (0.89, 0.07, 0.04)),
    ("v12-review-vague-target", "validation", {
        "message_id": "MSG-5012", "author": "echo_marmot",
        "message": "some people in this server really need to grow up, you know who you are",
    }, "review_needed", (0.25, 0.60, 0.15)),
    ("v13-violating-harass", "validation", {
        "message_id": "MSG-5013", "author": "cobalt_heron",
        "message": "@amber_vole I'm going to keep messaging you every day until you respond, "
        "you can't ignore me forever",
    }, "potentially_violating", (0.04, 0.12, 0.84)),
    ("v14-allowed-vent", "validation", {
        "message_id": "MSG-5014", "author": "misty_falcon",
        "message": "ugh I just lost rank again, this game is going to be the death of me",
    }, "allowed", (0.86, 0.09, 0.05)),
    ("v15-review-sarcasm2", "validation", {
        "message_id": "MSG-5015", "author": "amber_vole",
        "message": "wow, incredible call there captain, truly a masterclass in how to lose a "
        "match",
    }, "review_needed", (0.18, 0.68, 0.14)),
    ("v16-allowed-trigger2", "validation", {
        "message_id": "MSG-5016", "author": "quiet_lynx",
        "message": "I could honestly die laughing, that clip of the fail was amazing",
    }, "allowed", (0.82, 0.13, 0.05)),
    ("v17-violating-threat-mild", "validation", {
        "message_id": "MSG-5017", "author": "star_finch",
        "message": "say that again and see what happens to you next time we're in a match "
        "together",
    }, "potentially_violating", (0.06, 0.09, 0.85)),
    ("v18-review-banter2", "validation", {
        "message_id": "MSG-5018", "author": "driftwood92",
        "message": "you again? honestly at this point I think you just enjoy losing to me",
    }, "review_needed", (0.22, 0.63, 0.15)),
    ("v19-review-shortvague", "validation", {
        "message_id": "MSG-5019", "author": "glitchy_wren",
        "message": "some of you need to rethink how you talk to people in voice chat",
    }, "review_needed", (0.30, 0.55, 0.15)),
    # --- test: 19 examples --------------------------------------------------------------------
    ("t01-allowed-friendly", "test", {
        "message_id": "MSG-6001", "author": "nova_badger",
        "message": "that was a great run everyone, thanks for carrying us through the raid",
    }, "allowed", (0.91, 0.05, 0.04)),
    ("t02-allowed-compliment", "test", {
        "message_id": "MSG-6002", "author": "pixel_otter",
        "message": "@cobalt_heron your edit on that highlight video turned out really clean",
    }, "allowed", (0.87, 0.08, 0.05)),
    ("t03-trigger-word", "test", {
        "message_id": "MSG-6003", "author": "echo_marmot",
        "message": "this match is an absolute bloodbath, everyone is getting wrecked, what a "
        "game",
    }, "allowed", (0.83, 0.12, 0.05)),
    ("t04-violating-insult", "test", {
        "message_id": "MSG-6004", "author": "misty_falcon",
        "message": "@driftwood92 you're worthless and everyone in this server thinks you're a "
        "joke, just quit the game forever",
    }, "potentially_violating", (0.03, 0.06, 0.91)),
    ("t05-violating-exclude", "test", {
        "message_id": "MSG-6005", "author": "star_finch",
        "message": "nobody wants you in this clan, stop showing up to our sessions, you're not "
        "welcome here",
    }, "potentially_violating", (0.04, 0.09, 0.87)),
    ("t06-sarcasm", "test", {
        "message_id": "MSG-6006", "author": "quiet_lynx",
        "message": "oh fantastic, another brilliant play from our resident pro, truly inspiring "
        "stuff",
    }, "review_needed", (0.16, 0.69, 0.15)),
    ("t07-quoted-abuse", "test", {
        "message_id": "MSG-6007", "author": "amber_vole",
        "message": "heads up, @glitchy_wren said 'you're a joke and everyone here hates you' to "
        "someone in voice chat earlier",
    }, "review_needed", (0.25, 0.33, 0.42)),
    ("t08-banter", "test", {
        "message_id": "MSG-6008", "author": "cobalt_heron",
        "message": "you're hilarious, truly the worst teammate I've ever had, how do you even "
        "see the screen",
    }, "review_needed", (0.08, 0.87, 0.05)),
    ("t09-allowed-disagreement", "test", {
        "message_id": "MSG-6009", "author": "driftwood92",
        "message": "I don't think that rotation was right, I'd have pushed the other lane "
        "instead",
    }, "allowed", (0.81, 0.14, 0.05)),
    ("t10-violating-doxx-hint", "test", {
        "message_id": "MSG-6010", "author": "glitchy_wren",
        "message": "someone find @echo_marmot's old forum posts with their school name, let's "
        "post it here",
    }, "potentially_violating", (0.05, 0.09, 0.86)),
    ("t11-allowed-joke", "test", {
        "message_id": "MSG-6011", "author": "nova_badger",
        "message": "I die every single round in the same spot, it's basically a tradition now",
    }, "allowed", (0.90, 0.06, 0.04)),
    ("t12-review-vague-target", "test", {
        "message_id": "MSG-6012", "author": "misty_falcon",
        "message": "a few people in this community seriously need to check their attitude, you "
        "know who",
    }, "review_needed", (0.26, 0.59, 0.15)),
    ("t13-violating-harass", "test", {
        "message_id": "MSG-6013", "author": "star_finch",
        "message": "@amber_vole I'll keep tagging you in every channel until you actually "
        "answer me",
    }, "potentially_violating", (0.04, 0.11, 0.85)),
    ("t14-allowed-vent", "test", {
        "message_id": "MSG-6014", "author": "quiet_lynx",
        "message": "I can't believe I threw that match, I'm genuinely so mad at myself right "
        "now",
    }, "allowed", (0.85, 0.10, 0.05)),
    ("t15-false-allow", "test", {
        "message_id": "MSG-6015", "author": "pixel_otter",
        "message": "wow, what an incredible strategy from our captain, really carried the whole "
        "team there",
    }, "review_needed", (0.80, 0.15, 0.05)),
    ("t16-allowed-trigger2", "test", {
        "message_id": "MSG-6016", "author": "cobalt_heron",
        "message": "that jumpscare nearly killed me, I actually screamed, this game is too much",
    }, "allowed", (0.84, 0.11, 0.05)),
    ("t17-false-flag", "test", {
        "message_id": "MSG-6017", "author": "driftwood92",
        "message": "I'm going to destroy you in the next match, get ready to lose",
    }, "allowed", (0.10, 0.05, 0.85)),
    ("t18-violating-threat-mild", "test", {
        "message_id": "MSG-6018", "author": "glitchy_wren",
        "message": "watch yourself, you really don't want to find out what happens if you keep "
        "talking to me like that",
    }, "potentially_violating", (0.05, 0.10, 0.85)),
    ("t19-review-banter2", "test", {
        "message_id": "MSG-6019", "author": "echo_marmot",
        "message": "you're back again? I guess you really do enjoy losing to the same person "
        "every night",
    }, "review_needed", (0.21, 0.64, 0.15)),
    # --- demo: 2 examples, shown but never scored ----------------------------------------------
    ("d01-trigger-word", "demo", {
        "message_id": "MSG-7001", "author": "nova_badger",
        "message": "I'm going to kill this raid boss tonight if it's the last thing I do, "
        "let's go",
    }, None, (0.85, 0.10, 0.05)),
    ("d02-quoted-report", "demo", {
        "message_id": "MSG-7002", "author": "pixel_otter",
        "message": "can someone check this? misty_falcon told me 'you're an idiot and should "
        "just leave' in dms",
    }, None, (0.10, 0.75, 0.15)),
]  # fmt: skip


def answers_for(probabilities: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the three options."""
    return {
        "triage": ChoiceAnswer.from_probabilities(
            dict(zip(OPTIONS, probabilities, strict=True)), provenance
        )
    }


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, label, _probs in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, fields, _label, probs in rows:
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
