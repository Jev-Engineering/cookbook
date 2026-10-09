"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 12.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect. Four target words (`happy`, `big`, `quick`, `angry`) each get five
`validation` and five `test` sentences. Every sentence carries its own candidate synonym list,
assembled by Python per sentence rather than shared across every sentence that happens to use the
same word (see `helpers.candidate_options`); changing one sentence's candidates in `ROWS` changes
only that sentence's replay key, because the option list -- and so the key -- follows the
sentence, never the word.

Gold labels are a list of every option the sentence accepts (one of the word's own candidates,
`keep_original`, or several at once), because the use case allows more than one synonym to fit.
One sentence per word (`*-nomatch`) is a hard case the issue names: none of the supplied
candidates preserve the word's meaning here (an idiom, or personification), so `keep_original` is
the only acceptable answer. One sentence per word (`*-low`) names the right option at a low
confidence, so it is right but still sent to review once the confidence gate is frozen. On
`validation`, `v05-happy-wrong` is wrong at a moderate confidence (0.55, between the low and high
tiers below); excluding it from the accepted set is what the frozen threshold actually has to do,
rather than landing on a threshold nothing on `validation` would have crossed anyway. On `test`,
two sentences are wrong: `t05-quick-wrong` is wrong at a high confidence (0.85, the same tier as
every confident, correct answer), so it clears the frozen threshold anyway, and the
selective-prediction numbers the notebook reports on `test` show a real, non-zero risk rather than
a guarantee that happens to hold; `t03-angry-nomatch` is also wrong (the stored answer misses a
personified, no-match sentence and names a literal candidate instead of `keep_original`), but only
at a low confidence (0.42), so the confidence gate does catch this one -- it lowers the raw
choice's recall of `keep_original` without adding to the accepted-and-wrong risk count. Three
`demo` examples are shown in the notebook but never scored: a confident,
correct pick, a confident, correct `keep_original`, and a confident answer that is wrong (the same
shape as `t05-quick-wrong`, shown before any aggregate so a wrong-but-confident answer is on the
page before the evaluation gets to it). The replay keys come from the same `build_state` and
`build_questions` the notebook uses, via `helpers.py`.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# (id, split, word, sentence, candidates, gold list or None for demo, probabilities)
# Probabilities are in the order (candidate_1, candidate_2, candidate_3, keep_original) and sum
# to 1; "candidates" is this sentence's own list, in that same order.
ROWS = [
    # --- happy ---------------------------------------------------------------------------------
    ("v01-happy-high", "validation", "happy",
     "She was joyful and couldn't stop smiling after hearing the good news.",
     ["joyful", "cheerful", "pleased"], ["joyful"], (0.88, 0.06, 0.04, 0.02)),
    ("v02-happy-multi", "validation", "happy",
     "He was pleased, and quietly glad, that the meeting had gone so well.",
     ["pleased", "glad", "content"], ["pleased", "glad"], (0.80, 0.12, 0.05, 0.03)),
    ("v03-happy-nomatch", "validation", "happy",
     "After months of negotiation, they finally reached a happy medium on the budget.",
     ["content", "pleased", "glad"], ["keep_original"], (0.08, 0.06, 0.04, 0.82)),
    ("v04-happy-low", "validation", "happy",
     "He said he was happy with how the garden had turned out, though he barely looked up.",
     ["content", "pleased", "cheerful"], ["content"], (0.40, 0.32, 0.18, 0.10)),
    ("v05-happy-wrong", "validation", "happy",
     "The whole office seemed happy about the new coffee machine.",
     ["cheerful", "pleased", "glad"], ["cheerful", "pleased"], (0.30, 0.10, 0.55, 0.05)),
    ("t01-happy-high", "test", "happy",
     "The puppy bounded over, joyful to see its owner again.",
     ["joyful", "cheerful", "glad"], ["joyful"], (0.90, 0.05, 0.03, 0.02)),
    ("t02-happy-multi", "test", "happy",
     "She was content, and pleased besides, with the quiet evening at home.",
     ["content", "pleased", "glad"], ["content", "pleased"], (0.80, 0.12, 0.05, 0.03)),
    ("t03-happy-nomatch", "test", "happy",
     "Choosing a happy medium between the two designs took most of the afternoon.",
     ["content", "pleased", "cheerful"], ["keep_original"], (0.07, 0.05, 0.04, 0.84)),
    ("t04-happy-low", "test", "happy",
     "He mentioned he was happy with the new schedule, almost in passing.",
     ["content", "pleased", "glad"], ["content"], (0.42, 0.33, 0.15, 0.10)),
    ("t05-happy-high", "test", "happy",
     "Everyone at the party was glad to see the band back together.",
     ["glad", "joyful", "cheerful"], ["glad", "joyful"], (0.85, 0.09, 0.04, 0.02)),
    # --- big -----------------------------------------------------------------------------------
    ("v01-big-multi", "validation", "big",
     "The company announced a big expansion into three new countries.",
     ["large", "sizable", "massive"], ["large", "sizable"], (0.82, 0.11, 0.04, 0.03)),
    ("v02-big-multi", "validation", "big",
     "The whale was so big that the boat looked tiny beside it.",
     ["huge", "enormous", "massive"], ["huge", "enormous", "massive"], (0.85, 0.08, 0.05, 0.02)),
    ("v03-big-nomatch", "validation", "big",
     "Today is a big day for her: the final round of interviews.",
     ["large", "sizable", "massive"], ["keep_original"], (0.09, 0.07, 0.04, 0.80)),
    ("v04-big-low", "validation", "big",
     "The warehouse felt big and oddly empty in the evening light.",
     ["large", "sizable", "huge"], ["large"], (0.42, 0.31, 0.17, 0.10)),
    ("v05-big-multi", "validation", "big",
     "The festival drew a big crowd from across the region.",
     ["sizable", "large", "massive"], ["sizable", "large"], (0.86, 0.08, 0.04, 0.02)),
    ("t01-big-multi", "test", "big",
     "The new stadium has a big seating capacity for a city this size.",
     ["large", "sizable", "massive"], ["large", "sizable"], (0.84, 0.09, 0.04, 0.03)),
    ("t02-big-multi", "test", "big",
     "The iceberg was big enough to be seen from the passing ship.",
     ["huge", "enormous", "massive"], ["huge", "enormous"], (0.80, 0.13, 0.04, 0.03)),
    ("t03-big-nomatch", "test", "big",
     "It was a big decision, one she had been putting off for a year.",
     ["large", "sizable", "massive"], ["keep_original"], (0.08, 0.06, 0.03, 0.83)),
    ("t04-big-low", "test", "big",
     "The garage looked big compared to the cramped one next door.",
     ["large", "sizable", "huge"], ["large"], (0.40, 0.33, 0.17, 0.10)),
    ("t05-big-multi", "test", "big",
     "The orchard produced a big harvest of apples this autumn.",
     ["sizable", "large", "massive"], ["sizable", "large"], (0.87, 0.07, 0.04, 0.02)),
    # --- quick ---------------------------------------------------------------------------------
    ("v01-quick-multi", "validation", "quick",
     "The courier was quick, delivering the package within the hour.",
     ["fast", "swift", "speedy"], ["fast", "swift", "speedy"], (0.85, 0.08, 0.05, 0.02)),
    ("v02-quick-multi", "validation", "quick",
     "She gave a quick, decisive answer the moment the question was asked.",
     ["swift", "speedy", "brisk"], ["swift", "speedy"], (0.80, 0.12, 0.05, 0.03)),
    ("v03-quick-nomatch", "validation", "quick",
     "He has a quick wit that keeps the whole table laughing.",
     ["fast", "swift", "speedy"], ["keep_original"], (0.09, 0.06, 0.04, 0.81)),
    ("v04-quick-low", "validation", "quick",
     "The repair was quick, finished before the delivery truck even left.",
     ["fast", "speedy", "brisk"], ["fast"], (0.41, 0.32, 0.17, 0.10)),
    ("v05-quick-high", "validation", "quick",
     "They took a quick walk around the block before dinner.",
     ["brisk", "fast", "swift"], ["brisk"], (0.86, 0.08, 0.04, 0.02)),
    ("t01-quick-multi", "test", "quick",
     "The reply came back quick, faster than she expected.",
     ["fast", "swift", "speedy"], ["fast", "swift"], (0.83, 0.10, 0.04, 0.03)),
    ("t02-quick-high", "test", "quick",
     "He made a quick, brisk circuit of the factory floor before the inspection.",
     ["brisk", "fast", "swift"], ["brisk"], (0.84, 0.09, 0.04, 0.03)),
    ("t03-quick-nomatch", "test", "quick",
     "She's always had a quick mind for numbers, even as a child.",
     ["fast", "swift", "speedy"], ["keep_original"], (0.08, 0.06, 0.04, 0.82)),
    ("t04-quick-low", "test", "quick",
     "The fix was quick, though nobody was sure it would hold.",
     ["fast", "speedy", "hasty"], ["fast"], (0.44, 0.31, 0.15, 0.10)),
    ("t05-quick-wrong", "test", "quick",
     "The ferry crossing was quick, barely twenty minutes across the strait.",
     ["fast", "swift", "hasty"], ["fast", "swift"], (0.09, 0.04, 0.85, 0.02)),
    # --- angry ---------------------------------------------------------------------------------
    ("v01-angry-multi", "validation", "angry",
     "She was furious when she found out the flight had been cancelled without notice.",
     ["furious", "livid", "irritated"], ["furious", "livid"], (0.87, 0.07, 0.04, 0.02)),
    ("v02-angry-multi", "validation", "angry",
     "He grew increasingly annoyed as the meeting ran an hour past schedule.",
     ["annoyed", "irritated", "cross"], ["annoyed", "irritated"], (0.81, 0.11, 0.05, 0.03)),
    ("v03-angry-nomatch", "validation", "angry",
     "The old door hinge let out an angry creak every time it swung open.",
     ["furious", "irritated", "annoyed"], ["keep_original"], (0.09, 0.07, 0.04, 0.80)),
    ("v04-angry-low", "validation", "angry",
     "She seemed a little angry about the change in plans, but didn't say much.",
     ["annoyed", "irritated", "cross"], ["annoyed"], (0.43, 0.30, 0.17, 0.10)),
    ("v05-angry-high", "validation", "angry",
     "He was cross with himself for forgetting the tickets at home.",
     ["cross", "irritated", "annoyed"], ["cross"], (0.85, 0.08, 0.05, 0.02)),
    ("t01-angry-multi", "test", "angry",
     "The customer was furious about the duplicate charge on the invoice.",
     ["furious", "livid", "irritated"], ["furious", "livid"], (0.86, 0.08, 0.04, 0.02)),
    ("t02-angry-multi", "test", "angry",
     "The staff grew annoyed with the constant interruptions during the training.",
     ["annoyed", "irritated", "cross"], ["annoyed", "irritated"], (0.82, 0.10, 0.05, 0.03)),
    ("t03-angry-nomatch", "test", "angry",
     "The sky looked angry just before the storm broke over the hills.",
     ["furious", "irritated", "annoyed"], ["keep_original"], (0.42, 0.33, 0.15, 0.10)),
    ("t04-angry-low", "test", "angry",
     "He was mildly angry about the delay but let it go quickly.",
     ["annoyed", "irritated", "cross"], ["annoyed"], (0.42, 0.31, 0.17, 0.10)),
    ("t05-angry-multi", "test", "angry",
     "She was livid about the mistake and demanded an explanation on the spot.",
     ["livid", "furious", "irritated"], ["livid", "furious"], (0.88, 0.07, 0.03, 0.02)),
    # --- demo: shown in the notebook, never scored ----------------------------------------------
    ("d01-happy-clear", "demo", "happy",
     "She was happy and couldn't stop smiling all evening after the reunion.",
     ["joyful", "cheerful", "glad"], None, (0.90, 0.06, 0.03, 0.01)),
    ("d02-big-nomatch", "demo", "big",
     "It's a big ask, but I think the team can pull it off.",
     ["large", "sizable", "massive"], None, (0.08, 0.06, 0.03, 0.83)),
    ("d03-angry-wrong", "demo", "angry",
     "The wind grew angry as the storm rolled in off the coast.",
     ["furious", "irritated", "annoyed"], None, (0.80, 0.12, 0.05, 0.03)),
]  # fmt: skip


def answers_for(
    candidates: list[str], probabilities: tuple[float, ...], provenance: Provenance
) -> dict:
    """{question name: answer} for one row: a single Choice answer over this sentence's own
    candidates plus ``keep_original``, in that order."""
    options = [*candidates, helpers.KEEP_ORIGINAL]
    return {
        "synonym": ChoiceAnswer.from_probabilities(
            dict(zip(options, probabilities, strict=True)), provenance
        )
    }


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, word, sentence, candidates, gold, _probs in rows:
        fields = {"item_id": ident, "word": word, "sentence": sentence, "candidates": candidates}
        questions = helpers.build_questions(word, candidates)
        key = replay_key(helpers.build_state(fields), questions)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if gold is not None:
            labels.append({"id": ident, "label": gold})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, word, sentence, candidates, _gold, probs in rows:
        fields = {"item_id": _ident, "word": word, "sentence": sentence, "candidates": candidates}
        questions = helpers.build_questions(word, candidates)
        key = replay_key(helpers.build_state(fields), questions)
        answers = answers_for(candidates, probs, Provenance.synthetic())
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
