"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 16.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect. The hard cases rotate through both scored splits with different
wording each time: sarcasm (``v06``/``t06``/``t15``), a message that quotes or reports someone
else's abusive words rather than being abusive itself (``v07``/``t07``), borderline banter
between members (``v08``/``t08``/``v12``/``t12``/``v15``/``v18``/``v19``/``t19``), and a benign
message that merely contains a word the rule's examples mention (``v03``/``v16``/``t03``/``t16``).

Five stored answers are wrong on purpose (the notebook derives this count from the fixtures
rather than stating it; this docstring names them so a reader of the generator does not have to
re-derive it by hand), each illustrating a different failure shape under the confidence gate
this recipe applies to every category alike (``helpers.moderate``'s three-path pattern):

* ``v07-quoted-abuse`` is wrong *and* confident, 0.6700, just below the gate this recipe's
  notebook freezes on validation (0.7600, chosen over all nineteen validation examples), so it
  is the one example the gate is chosen to exclude: a sarcastic report of someone else's
  abusive words read, confidently, as violating in its own right (S07 item 6, "adversarial
  content": Jev does not treat the state as hostile by default, so a message that only *quotes*
  hostile words can read as hostile itself).
* ``t07-quoted-abuse`` is the same shape of mistake on `test`, but at low confidence, 0.1300, so
  the frozen gate catches it and escalates it instead of reporting a wrong result. Both scored
  quoted-abuse examples land on the wrong side, so no scored example shows the steering in the
  option descriptions actually working; that is a jaggedness lesson in itself, not a fixture bug.
* ``t15-false-allow`` is read, confidently (0.7000), as `allowed`, when its gold label is
  `review_needed` -- a labelling convention, the same one `v15` and `t06` use with a tell this
  message does not carry (hyperbolic, singled-out praise defaults to `review_needed`). At 0.7000
  its confidence falls *below* the frozen gate (0.7600), so once `allowed` is gated like every
  other category, this mistake is caught, not missed.
* ``t17-false-flag`` is ordinary competitive trash talk read, confidently (0.7750), as a threat:
  a benign message wrongly hidden, clearing the gate anyway.
* ``t20-missed-violation`` is a passive-aggressive exclusionary remark -- gold
  `potentially_violating` -- read, confidently (0.7750), as `allowed`: the cost the issue names
  for a false allow, a message that actually violates the rule left standing, surviving the gate
  exactly as `t17` does on the other side.

``v09-allowed-hesitant`` is not wrong -- its gold label and its stored category agree, `allowed`
-- but at 0.4000 confidence it sits below the gate too, so it is escalated despite being right:
the coverage cost of gating `allowed` like every other category, on `validation`, where the gate
is chosen.

The replay keys come from the same ``build_state`` and ``build_questions`` the notebook uses, via
``helpers.py``. Probabilities are written as ``{option: probability}`` mappings, independent of
``helpers.OPTIONS``' order, so reordering the options (as this recipe does, to point jev-1.13's
documented first-option lean away from `allowed`) never requires re-deriving every row by hand.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# (id, split, fields, gold label or None for demo, stored probabilities by option name)
ROWS = [
    # --- validation: 19 examples ------------------------------------------------------------
    ("v01-allowed-friendly", "validation", {
        "message_id": "MSG-5001", "author": "pixel_otter",
        "message": "gg everyone, that was such a fun match tonight!",
    }, "allowed", {"allowed": 0.90, "review_needed": 0.06, "potentially_violating": 0.04}),
    ("v02-allowed-compliment", "validation", {
        "message_id": "MSG-5002", "author": "nova_badger",
        "message": "@quiet_lynx your stream setup looks awesome, nice work!",
    }, "allowed", {"allowed": 0.88, "review_needed": 0.07, "potentially_violating": 0.05}),
    ("v03-trigger-word", "validation", {
        "message_id": "MSG-5003", "author": "glitchy_wren",
        "message": "this boss fight is insane, I want to kill something lol, final phase is rough",
    }, "allowed", {"allowed": 0.84, "review_needed": 0.11, "potentially_violating": 0.05}),
    ("v04-violating-insult", "validation", {
        "message_id": "MSG-5004", "author": "driftwood92",
        "message": "@star_finch you're pathetic and nobody here actually likes you, just leave "
        "the server already",
    }, "potentially_violating",
       {"allowed": 0.03, "review_needed": 0.07, "potentially_violating": 0.90}),
    ("v05-violating-exclude", "validation", {
        "message_id": "MSG-5005", "author": "echo_marmot",
        "message": "we don't want you in our group anymore, stop queuing with us, nobody "
        "invited you",
    }, "potentially_violating",
       {"allowed": 0.04, "review_needed": 0.08, "potentially_violating": 0.88}),
    ("v06-sarcasm", "validation", {
        "message_id": "MSG-5006", "author": "cobalt_heron",
        "message": "oh sure, because YOU are definitely the best player in this server, "
        "congratulations on that",
    }, "review_needed", {"allowed": 0.08, "review_needed": 0.87, "potentially_violating": 0.05}),
    ("v07-quoted-abuse", "validation", {
        "message_id": "MSG-5007", "author": "misty_falcon",
        "message": "can a mod look at this? dax told me 'nobody wants you here, just quit "
        "already' in general chat yesterday",
    }, "review_needed", {"allowed": 0.05, "review_needed": 0.17, "potentially_violating": 0.78}),
    ("v08-banter", "validation", {
        "message_id": "MSG-5008", "author": "amber_vole",
        "message": "lol you're actually the worst at this game, I can't even, how do you keep "
        "dying there",
    }, "review_needed", {"allowed": 0.20, "review_needed": 0.65, "potentially_violating": 0.15}),
    ("v09-allowed-hesitant", "validation", {
        "message_id": "MSG-5009", "author": "quiet_lynx",
        "message": "idk, maybe we should've rotated earlier instead of doing that, just a "
        "thought",
    }, "allowed", {"allowed": 0.60, "review_needed": 0.25, "potentially_violating": 0.15}),
    ("v10-violating-doxx-hint", "validation", {
        "message_id": "MSG-5010", "author": "star_finch",
        "message": "I found @glitchy_wren's real address from an old post, should I post it "
        "here so everyone knows where they live",
    }, "potentially_violating",
       {"allowed": 0.05, "review_needed": 0.10, "potentially_violating": 0.85}),
    ("v11-allowed-joke", "validation", {
        "message_id": "MSG-5011", "author": "driftwood92",
        "message": "I'm so bad at this game it's actually impressive, send help",
    }, "allowed", {"allowed": 0.89, "review_needed": 0.07, "potentially_violating": 0.04}),
    ("v12-review-vague-target", "validation", {
        "message_id": "MSG-5012", "author": "echo_marmot",
        "message": "some people in this server really need to grow up, you know who you are",
    }, "review_needed", {"allowed": 0.25, "review_needed": 0.60, "potentially_violating": 0.15}),
    ("v13-violating-harass", "validation", {
        "message_id": "MSG-5013", "author": "cobalt_heron",
        "message": "@amber_vole I'm going to keep messaging you every day until you respond, "
        "you can't ignore me forever",
    }, "potentially_violating",
       {"allowed": 0.04, "review_needed": 0.12, "potentially_violating": 0.84}),
    ("v14-allowed-vent", "validation", {
        "message_id": "MSG-5014", "author": "misty_falcon",
        "message": "ugh I just lost rank again, this game is going to be the death of me",
    }, "allowed", {"allowed": 0.86, "review_needed": 0.09, "potentially_violating": 0.05}),
    ("v15-review-sarcasm2", "validation", {
        "message_id": "MSG-5015", "author": "amber_vole",
        "message": "wow, incredible call there captain, truly a masterclass in how to lose a "
        "match",
    }, "review_needed", {"allowed": 0.18, "review_needed": 0.68, "potentially_violating": 0.14}),
    ("v16-allowed-trigger2", "validation", {
        "message_id": "MSG-5016", "author": "quiet_lynx",
        "message": "I could honestly die laughing, that clip of the fail was amazing",
    }, "allowed", {"allowed": 0.85, "review_needed": 0.10, "potentially_violating": 0.05}),
    ("v17-violating-threat-mild", "validation", {
        "message_id": "MSG-5017", "author": "star_finch",
        "message": "say that again and see what happens to you next time we're in a match "
        "together",
    }, "potentially_violating",
       {"allowed": 0.06, "review_needed": 0.09, "potentially_violating": 0.85}),
    ("v18-review-banter2", "validation", {
        "message_id": "MSG-5018", "author": "driftwood92",
        "message": "you again? honestly at this point I think you just enjoy losing to me",
    }, "review_needed", {"allowed": 0.22, "review_needed": 0.63, "potentially_violating": 0.15}),
    ("v19-review-shortvague", "validation", {
        "message_id": "MSG-5019", "author": "glitchy_wren",
        "message": "some of you need to rethink how you talk to people in voice chat",
    }, "review_needed", {"allowed": 0.30, "review_needed": 0.55, "potentially_violating": 0.15}),
    # --- test: 20 examples --------------------------------------------------------------------
    ("t01-allowed-friendly", "test", {
        "message_id": "MSG-6001", "author": "nova_badger",
        "message": "that was a great run everyone, thanks for carrying us through the raid",
    }, "allowed", {"allowed": 0.91, "review_needed": 0.05, "potentially_violating": 0.04}),
    ("t02-allowed-compliment", "test", {
        "message_id": "MSG-6002", "author": "pixel_otter",
        "message": "@cobalt_heron your edit on that highlight video turned out really clean",
    }, "allowed", {"allowed": 0.87, "review_needed": 0.08, "potentially_violating": 0.05}),
    ("t03-trigger-word", "test", {
        "message_id": "MSG-6003", "author": "echo_marmot",
        "message": "this match is an absolute bloodbath, everyone is getting wrecked, what a "
        "game",
    }, "allowed", {"allowed": 0.83, "review_needed": 0.12, "potentially_violating": 0.05}),
    ("t04-violating-insult", "test", {
        "message_id": "MSG-6004", "author": "misty_falcon",
        "message": "@driftwood92 you're worthless and everyone in this server thinks you're a "
        "joke, just quit the game forever",
    }, "potentially_violating",
       {"allowed": 0.03, "review_needed": 0.06, "potentially_violating": 0.91}),
    ("t05-violating-exclude", "test", {
        "message_id": "MSG-6005", "author": "star_finch",
        "message": "nobody wants you in this clan, stop showing up to our sessions, you're not "
        "welcome here",
    }, "potentially_violating",
       {"allowed": 0.04, "review_needed": 0.09, "potentially_violating": 0.87}),
    ("t06-sarcasm", "test", {
        "message_id": "MSG-6006", "author": "quiet_lynx",
        "message": "oh fantastic, another brilliant play from our resident pro, truly inspiring "
        "stuff",
    }, "review_needed", {"allowed": 0.16, "review_needed": 0.69, "potentially_violating": 0.15}),
    ("t07-quoted-abuse", "test", {
        "message_id": "MSG-6007", "author": "amber_vole",
        "message": "heads up, @glitchy_wren said 'you're a joke and everyone here hates you' to "
        "someone in voice chat earlier",
    }, "review_needed", {"allowed": 0.25, "review_needed": 0.33, "potentially_violating": 0.42}),
    ("t08-banter", "test", {
        "message_id": "MSG-6008", "author": "cobalt_heron",
        "message": "you're hilarious, truly the worst teammate I've ever had, how do you even "
        "see the screen",
    }, "review_needed", {"allowed": 0.08, "review_needed": 0.87, "potentially_violating": 0.05}),
    ("t09-allowed-disagreement", "test", {
        "message_id": "MSG-6009", "author": "driftwood92",
        "message": "I don't think that rotation was right, I'd have pushed the other lane "
        "instead",
    }, "allowed", {"allowed": 0.81, "review_needed": 0.14, "potentially_violating": 0.05}),
    ("t10-violating-doxx-hint", "test", {
        "message_id": "MSG-6010", "author": "glitchy_wren",
        "message": "someone find @echo_marmot's old forum posts with their school name, let's "
        "post it here",
    }, "potentially_violating",
       {"allowed": 0.05, "review_needed": 0.09, "potentially_violating": 0.86}),
    ("t11-allowed-joke", "test", {
        "message_id": "MSG-6011", "author": "nova_badger",
        "message": "I die every single round in the same spot, it's basically a tradition now",
    }, "allowed", {"allowed": 0.90, "review_needed": 0.06, "potentially_violating": 0.04}),
    ("t12-review-vague-target", "test", {
        "message_id": "MSG-6012", "author": "misty_falcon",
        "message": "a few people in this community seriously need to check their attitude, you "
        "know who",
    }, "review_needed", {"allowed": 0.26, "review_needed": 0.59, "potentially_violating": 0.15}),
    ("t13-violating-harass", "test", {
        "message_id": "MSG-6013", "author": "star_finch",
        "message": "@amber_vole I'll keep tagging you in every channel until you actually "
        "answer me",
    }, "potentially_violating",
       {"allowed": 0.04, "review_needed": 0.11, "potentially_violating": 0.85}),
    ("t14-allowed-vent", "test", {
        "message_id": "MSG-6014", "author": "quiet_lynx",
        "message": "I can't believe I threw that match, I'm genuinely so mad at myself right "
        "now",
    }, "allowed", {"allowed": 0.85, "review_needed": 0.10, "potentially_violating": 0.05}),
    ("t15-false-allow", "test", {
        "message_id": "MSG-6015", "author": "pixel_otter",
        "message": "wow, what an incredible strategy from our captain, really carried the whole "
        "team there",
    }, "review_needed", {"allowed": 0.80, "review_needed": 0.15, "potentially_violating": 0.05}),
    ("t16-allowed-trigger2", "test", {
        "message_id": "MSG-6016", "author": "cobalt_heron",
        "message": "that jumpscare nearly killed me, I actually screamed, this game is too much",
    }, "allowed", {"allowed": 0.84, "review_needed": 0.11, "potentially_violating": 0.05}),
    ("t17-false-flag", "test", {
        "message_id": "MSG-6017", "author": "driftwood92",
        "message": "I'm going to destroy you in the next match, get ready to lose",
    }, "allowed", {"allowed": 0.10, "review_needed": 0.05, "potentially_violating": 0.85}),
    ("t18-violating-threat-mild", "test", {
        "message_id": "MSG-6018", "author": "glitchy_wren",
        "message": "watch yourself, you really don't want to find out what happens if you keep "
        "talking to me like that",
    }, "potentially_violating",
       {"allowed": 0.05, "review_needed": 0.10, "potentially_violating": 0.85}),
    ("t19-review-banter2", "test", {
        "message_id": "MSG-6019", "author": "echo_marmot",
        "message": "you're back again? I guess you really do enjoy losing to the same person "
        "every night",
    }, "review_needed", {"allowed": 0.21, "review_needed": 0.64, "potentially_violating": 0.15}),
    ("t20-missed-violation", "test", {
        "message_id": "MSG-6020", "author": "star_finch",
        "message": "honestly, no one would even notice if you just stopped showing up here",
    }, "potentially_violating",
       {"allowed": 0.85, "review_needed": 0.10, "potentially_violating": 0.05}),
    # --- demo: 2 examples, shown but never scored ----------------------------------------------
    ("d01-trigger-word", "demo", {
        "message_id": "MSG-7001", "author": "nova_badger",
        "message": "I'm going to kill this raid boss tonight if it's the last thing I do, "
        "let's go",
    }, None, {"allowed": 0.85, "review_needed": 0.10, "potentially_violating": 0.05}),
    ("d02-quoted-report", "demo", {
        "message_id": "MSG-7002", "author": "pixel_otter",
        "message": "can someone check this? misty_falcon told me 'you're an idiot and should "
        "just leave' in dms",
    }, None, {"allowed": 0.10, "review_needed": 0.75, "potentially_violating": 0.15}),
]  # fmt: skip


def answers_for(probabilities: dict, provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the three options."""
    return {"triage": ChoiceAnswer.from_probabilities(probabilities, provenance)}


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
