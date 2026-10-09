"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 12.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect. Four target words (`happy`, `big`, `quick`, `angry`) each get five
`validation` and five `test` sentences. Every sentence contains its target word literally, and
none of its own three candidates appears anywhere in the sentence text, so the task is genuinely
"judge which supplied word fits here", never "copy the word already in the sentence" or "spot the
candidate that is already written out".

Gold labels are a list of every option the sentence accepts (one of the word's own candidates,
`keep_original`, or several at once), because the use case allows more than one synonym to fit.
Each word gets two `*-nomatch` sentences (an idiom or a fixed name, where none of the candidates
preserve the meaning: `keep_original` is the only acceptable answer) and two `*-low` sentences (a
correct choice, named at low confidence, with a genuine second acceptable candidate in its gold
set, so the gold set is never narrower than the sentence actually supports).

`SEED` and `shuffled_candidates` decouple a sentence's authored candidate order (gold first, for
readability below) from the order Jev is actually asked in: each sentence's three candidates are
permuted by a deterministic, seeded shuffle, independent across sentences. Without this, every
sentence in an earlier draft of these fixtures happened to list its best-fitting candidate first,
which let "always answer option 1" score as well as the frozen rule -- exactly the option-order
lean S07 item 8 documents in Jev 1.13. `notebook.ipynb` prints the resulting distribution of gold
positions (`gold_positions`, below) so the reader can see candidate 1 is not privileged.

Two sentences test the fallback's other failure direction: a stored answer that confidently (or
unconfidently) says `keep_original` even though a real candidate fits -- `v05-happy-fp` (low
confidence, caught by the gate) and `t05-big-fp` (confident, not caught, counted in `risk`).
`v05-angry-wrong` is the sole deliberately wrong validation answer (`livid`, at a moderate
confidence the threshold search must exclude): the sentence itself says "a little angry ...
shrugged it off", which contradicts `livid`'s own gloss ("extremely angry") directly, so the
designated-wrong answer is wrong by the glosses, not by a judgment call. `t05-quick-wrong`
(`hasty` for a sentence about a fast ferry crossing) is the sole wrong-and-confident test answer,
clear of the frozen threshold, so the risk the notebook reports on `test` is real.

The replay keys come from the same `build_state` and `build_questions` the notebook uses, via
`helpers.py`; because the option order is shuffled per sentence, editing or reordering one
sentence's candidates changes only that sentence's key.
"""

import argparse
import hashlib
import json
import random
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

SEED = 12  # this recipe's number; see shuffled_candidates


def shuffled_candidates(item_id: str, candidates: list[str]) -> list[str]:
    """``candidates``, permuted by a deterministic shuffle seeded from ``(SEED, item_id)`` --
    the same seeding convention `ScriptedBackend.rng_for` uses (`src/jev_cookbook/backends.py`,
    `docs/backends.md` "Scripted backend"): hash ``f"{SEED}:{item_id}"`` and seed
    ``random.Random`` from the digest, rather than passing the tuple directly (`random.Random`
    only accepts ``None``, ``int``, ``float``, ``str``, ``bytes`` or ``bytearray``, and a bare
    string seed would depend on Python's randomized string hash across processes). The same item
    id always gives the same order, on every platform, independent of every other sentence's
    shuffle. This is what decouples the position a candidate is offered in from whether it
    belongs in the sentence's gold set (see the module docstring)."""
    digest = hashlib.sha256(f"{SEED}:{item_id}".encode()).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    order = list(range(len(candidates)))
    rng.shuffle(order)
    return [candidates[i] for i in order]


# (id, split, word, sentence, candidates (authored order: gold first, for readability -- the
# order Jev is actually asked in is shuffled_candidates(id, candidates)), gold list or None for
# demo, {candidate name (or "keep_original"): probability}). Each probability dict sums to 1.
ROWS = [
    # --- happy ---------------------------------------------------------------------------------
    ("v01-happy-high", "validation", "happy",
     "Maria looked incredibly happy as she opened the acceptance letter, tears of joy in her eyes.",
     ["joyful", "cheerful", "pleased"], ["joyful"],
     {"joyful": 0.88, "cheerful": 0.06, "pleased": 0.04, "keep_original": 0.02}),
    ("v02-happy-multi", "validation", "happy",
     "After the long negotiation finally ended in a fair deal, both sides were happy with the outcome.",
     ["pleased", "glad", "content"], ["pleased", "glad"],
     {"pleased": 0.80, "glad": 0.12, "content": 0.05, "keep_original": 0.03}),
    ("v03-happy-nomatch", "validation", "happy",
     "After weeks of back-and-forth, the two departments settled on a happy medium for the shared budget.",
     ["content", "pleased", "glad"], ["keep_original"],
     {"content": 0.08, "pleased": 0.06, "glad": 0.04, "keep_original": 0.82}),
    ("v04-happy-low", "validation", "happy",
     "He mentioned he felt happy with how the garden had turned out, though he barely glanced up "
     "from his phone the whole time he said it.",
     ["content", "pleased", "cheerful"], ["content", "pleased"],
     {"content": 0.40, "pleased": 0.32, "cheerful": 0.18, "keep_original": 0.10}),
    ("v05-happy-fp", "validation", "happy",
     "The two old friends seemed happy just sitting together on the porch, not saying much at all.",
     ["content", "glad", "pleased"], ["content", "glad"],
     {"content": 0.30, "glad": 0.10, "pleased": 0.22, "keep_original": 0.38}),
    ("t01-happy-high", "test", "happy",
     "The whole team looked happy when the client finally approved the final design after months "
     "of revisions.",
     ["joyful", "glad", "cheerful"], ["joyful", "glad"],
     {"joyful": 0.80, "glad": 0.12, "cheerful": 0.05, "keep_original": 0.03}),
    ("t02-happy-multi", "test", "happy",
     "She was happy to finally relax on the porch after a long week, with nothing on her mind and "
     "nowhere to be.",
     ["pleased", "content", "cheerful"], ["pleased", "content"],
     {"pleased": 0.80, "content": 0.12, "cheerful": 0.05, "keep_original": 0.03}),
    ("t03-happy-nomatch", "test", "happy",
     "The committee eventually agreed on a happy medium between the two competing proposals.",
     ["pleased", "glad", "cheerful"], ["keep_original"],
     {"pleased": 0.07, "glad": 0.05, "cheerful": 0.04, "keep_original": 0.84}),
    ("t04-happy-low", "test", "happy",
     "He said he was happy with the new schedule, though he said it so flatly it was hard to tell "
     "if he meant it.",
     ["content", "pleased", "glad"], ["content", "pleased"],
     {"content": 0.42, "pleased": 0.33, "glad": 0.15, "keep_original": 0.10}),
    ("t05-happy-high", "test", "happy",
     "Everyone at the reunion was happy to see faces they hadn't seen in years.",
     ["glad", "joyful", "cheerful"], ["glad", "joyful"],
     {"glad": 0.85, "joyful": 0.09, "cheerful": 0.04, "keep_original": 0.02}),
    # --- big -----------------------------------------------------------------------------------
    ("v01-big-multi", "validation", "big",
     "The city approved a big expansion of the downtown transit line this year.",
     ["large", "sizable", "massive"], ["large", "sizable"],
     {"large": 0.82, "sizable": 0.11, "massive": 0.04, "keep_original": 0.03}),
    ("v02-big-triple", "validation", "big",
     "The whale drifting past the boat was so big that everyone on deck fell silent.",
     ["huge", "enormous", "massive"], ["huge", "enormous", "massive"],
     {"huge": 0.85, "enormous": 0.08, "massive": 0.05, "keep_original": 0.02}),
    ("v03-big-nomatch", "validation", "big",
     "Getting the promotion was a big deal for her, even though nothing about her daily tasks "
     "changed yet.",
     ["large", "sizable", "massive"], ["keep_original"],
     {"large": 0.09, "sizable": 0.07, "massive": 0.04, "keep_original": 0.80}),
    ("v04-big-low", "validation", "big",
     "The warehouse felt big and strangely empty in the dim evening light, with only a few crates "
     "stacked near the door.",
     ["large", "huge", "sizable"], ["large", "huge"],
     {"large": 0.42, "huge": 0.31, "sizable": 0.17, "keep_original": 0.10}),
    ("v05-big-multi", "validation", "big",
     "The festival drew a big crowd from every town in the county this year.",
     ["sizable", "large", "massive"], ["sizable", "large"],
     {"sizable": 0.86, "large": 0.08, "massive": 0.04, "keep_original": 0.02}),
    ("t01-big-multi", "test", "big",
     "The new stadium has a big seating capacity, more than any other arena in the state.",
     ["large", "sizable", "massive"], ["large", "sizable"],
     {"large": 0.84, "sizable": 0.09, "massive": 0.04, "keep_original": 0.03}),
    ("t02-big-multi", "test", "big",
     "The iceberg drifting near the ship was big enough that the captain ordered a wide detour.",
     ["huge", "enormous", "massive"], ["huge", "enormous"],
     {"huge": 0.80, "enormous": 0.13, "massive": 0.04, "keep_original": 0.03}),
    ("t03-big-nomatch", "test", "big",
     "It was a big decision, one she had been putting off making for almost a year.",
     ["large", "sizable", "massive"], ["keep_original"],
     {"large": 0.08, "sizable": 0.06, "massive": 0.03, "keep_original": 0.83}),
    ("t04-big-low", "test", "big",
     "The garage looked big compared to the cramped one next door, though it still only fit one "
     "car comfortably.",
     ["large", "sizable", "huge"], ["large", "sizable"],
     {"large": 0.40, "sizable": 0.33, "huge": 0.17, "keep_original": 0.10}),
    ("t05-big-fp", "test", "big",
     "The orchard produced a big harvest of apples this autumn, far more than the bins could hold.",
     ["sizable", "large", "massive"], ["sizable", "large"],
     {"sizable": 0.07, "large": 0.05, "massive": 0.03, "keep_original": 0.85}),
    # --- quick ---------------------------------------------------------------------------------
    ("v01-quick-high", "validation", "quick",
     "The mechanic's diagnosis was quick, barely two minutes before he knew exactly what was wrong.",
     ["fast", "swift", "speedy"], ["fast"],
     {"fast": 0.85, "swift": 0.08, "speedy": 0.05, "keep_original": 0.02}),
    ("v02-quick-multi", "validation", "quick",
     "She gave a quick, decisive answer the moment the interviewer asked the hardest question.",
     ["swift", "speedy", "brisk"], ["swift", "speedy"],
     {"swift": 0.80, "speedy": 0.12, "brisk": 0.05, "keep_original": 0.03}),
    ("v03-quick-nomatch", "validation", "quick",
     "Her quick wit kept the whole dinner table laughing until dessert arrived.",
     ["fast", "swift", "speedy"], ["keep_original"],
     {"fast": 0.09, "swift": 0.06, "speedy": 0.04, "keep_original": 0.81}),
    ("v04-quick-low", "validation", "quick",
     "The repair was quick, done before the delivery truck even finished unloading next door.",
     ["fast", "speedy", "brisk"], ["fast", "speedy"],
     {"fast": 0.41, "speedy": 0.32, "brisk": 0.17, "keep_original": 0.10}),
    ("v05-quick-high", "validation", "quick",
     "They took a quick walk around the block before dinner, back in under ten minutes.",
     ["brisk", "fast", "swift"], ["brisk"],
     {"brisk": 0.86, "fast": 0.08, "swift": 0.04, "keep_original": 0.02}),
    ("t01-quick-multi", "test", "quick",
     "The reply came back quick, much sooner than she had expected given the time difference.",
     ["fast", "swift", "speedy"], ["fast", "swift"],
     {"fast": 0.83, "swift": 0.10, "speedy": 0.04, "keep_original": 0.03}),
    ("t02-quick-high", "test", "quick",
     "He made a quick circuit of the factory floor before the inspection began, pausing only a "
     "few seconds at each station.",
     ["brisk", "fast", "swift"], ["brisk"],
     {"brisk": 0.84, "fast": 0.09, "swift": 0.04, "keep_original": 0.03}),
    ("t03-quick-nomatch", "test", "quick",
     "Her quick thinking under pressure impressed everyone on the response team.",
     ["fast", "swift", "speedy"], ["keep_original"],
     {"fast": 0.08, "swift": 0.06, "speedy": 0.04, "keep_original": 0.82}),
    ("t04-quick-low", "test", "quick",
     "The fix was quick, though nobody on the crew was fully confident it would hold through the "
     "winter.",
     ["fast", "speedy", "hasty"], ["fast", "speedy"],
     {"fast": 0.44, "speedy": 0.31, "hasty": 0.15, "keep_original": 0.10}),
    ("t05-quick-wrong", "test", "quick",
     "The ferry crossing was quick, barely twenty minutes across the strait.",
     ["fast", "swift", "hasty"], ["fast", "swift"],
     {"fast": 0.09, "swift": 0.04, "hasty": 0.85, "keep_original": 0.02}),
    # --- angry ---------------------------------------------------------------------------------
    ("v01-angry-multi", "validation", "angry",
     "She was angry when she discovered the airline had cancelled her flight without any warning.",
     ["furious", "livid", "irritated"], ["furious", "livid"],
     {"furious": 0.87, "livid": 0.07, "irritated": 0.04, "keep_original": 0.02}),
    ("v02-angry-multi", "validation", "angry",
     "He grew angry as the meeting dragged an extra hour past its scheduled end with no end in "
     "sight.",
     ["annoyed", "irritated", "cross"], ["annoyed", "irritated"],
     {"annoyed": 0.81, "irritated": 0.11, "cross": 0.05, "keep_original": 0.03}),
    ("v03-angry-nomatch", "validation", "angry",
     "She always orders the Angry Bird smoothie before her morning workout at the new juice bar.",
     ["furious", "irritated", "annoyed"], ["keep_original"],
     {"furious": 0.09, "irritated": 0.07, "annoyed": 0.04, "keep_original": 0.80}),
    ("v04-angry-low", "validation", "angry",
     "She seemed a little angry about the last-minute change in plans, but she didn't say much "
     "about it.",
     ["annoyed", "cross", "irritated"], ["annoyed", "cross"],
     {"annoyed": 0.43, "cross": 0.30, "irritated": 0.17, "keep_original": 0.10}),
    ("v05-angry-wrong", "validation", "angry",
     "He was a little angry that the bus was two minutes late, but he just shrugged and went back "
     "to reading his book.",
     ["cross", "irritated", "livid"], ["cross", "irritated"],
     {"cross": 0.30, "irritated": 0.10, "livid": 0.55, "keep_original": 0.05}),
    ("t01-angry-multi", "test", "angry",
     "The customer was angry about being charged twice for the same order and demanded a refund "
     "on the spot.",
     ["furious", "livid", "irritated"], ["furious", "livid"],
     {"furious": 0.86, "livid": 0.08, "irritated": 0.04, "keep_original": 0.02}),
    ("t02-angry-high", "test", "angry",
     "He was a bit angry with himself, mostly just amused at his own forgetfulness, for leaving "
     "the tickets on the kitchen counter at home.",
     ["cross", "irritated", "annoyed"], ["cross"],
     {"cross": 0.82, "irritated": 0.10, "annoyed": 0.05, "keep_original": 0.03}),
    ("t03-angry-nomatch", "test", "angry",
     "The diner's lunch special today is the Angry Trucker burger, their spiciest one yet.",
     ["livid", "irritated", "annoyed"], ["keep_original"],
     {"livid": 0.08, "irritated": 0.06, "annoyed": 0.03, "keep_original": 0.83}),
    ("t04-angry-low", "test", "angry",
     "He was mildly angry about the delay at the gate, but he let it go after a minute or two.",
     ["annoyed", "irritated", "cross"], ["annoyed", "irritated"],
     {"annoyed": 0.42, "irritated": 0.31, "cross": 0.17, "keep_original": 0.10}),
    ("t05-angry-multi", "test", "angry",
     "She was angry about the mistake on the invoice and asked to speak with a manager right away.",
     ["livid", "furious", "irritated"], ["livid", "furious"],
     {"livid": 0.88, "furious": 0.07, "irritated": 0.03, "keep_original": 0.02}),
    # --- demo: shown in the notebook, never scored ----------------------------------------------
    ("d01-happy-clear", "demo", "happy",
     "She felt happy and kept smiling through the whole afternoon after hearing the good news.",
     ["joyful", "cheerful", "glad"], None,
     {"joyful": 0.90, "cheerful": 0.06, "glad": 0.03, "keep_original": 0.01}),
    ("d02-big-nomatch", "demo", "big",
     "It's a big ask, but I think the team can pull it off before the deadline.",
     ["large", "sizable", "massive"], None,
     {"large": 0.08, "sizable": 0.06, "massive": 0.03, "keep_original": 0.83}),
    ("d03-angry-wrong", "demo", "angry",
     "The negotiations turned angry fast once the topic of layoffs came up, and voices started "
     "rising around the table.",
     ["furious", "irritated", "annoyed"], None,
     {"furious": 0.05, "irritated": 0.90, "annoyed": 0.03, "keep_original": 0.02}),
]  # fmt: skip


def answers_for(
    item_id: str, candidates: list[str], probabilities: dict, provenance: Provenance
) -> dict:
    """{question name: answer} for one row: a single Choice answer over this sentence's own
    candidates (in the shuffled order Jev is actually asked) plus ``keep_original``."""
    options = [*shuffled_candidates(item_id, candidates), helpers.KEEP_ORIGINAL]
    ordered = {name: probabilities[name] for name in options}
    return {"synonym": ChoiceAnswer.from_probabilities(ordered, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, word, sentence, candidates, gold, _probs in rows:
        shuffled = shuffled_candidates(ident, candidates)
        fields = {"item_id": ident, "word": word, "sentence": sentence, "candidates": shuffled}
        questions = helpers.build_questions(word, shuffled)
        key = replay_key(helpers.build_state(fields), questions)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if gold is not None:
            labels.append({"id": ident, "label": gold})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for ident, _split, word, sentence, candidates, _gold, probs in rows:
        shuffled = shuffled_candidates(ident, candidates)
        fields = {"item_id": ident, "word": word, "sentence": sentence, "candidates": shuffled}
        questions = helpers.build_questions(word, shuffled)
        key = replay_key(helpers.build_state(fields), questions)
        answers = answers_for(ident, candidates, probs, Provenance.synthetic())
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
