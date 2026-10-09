"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 07.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect. For each of the four target words, one `validation` example is wrong at
a moderate confidence (the stored answer leans toward the other sense). On `test`, only `crane`
carries a wrong stored answer, and it carries two: `t04-crane-thin` answers `unclear` at a low
confidence (so `resolve` sends it to review for choosing `unclear`, not for its confidence, and
it is caught regardless of where the threshold ends up), and `t05-crane-wrong` is wrong *and*
confident, well above the threshold this recipe's notebook freezes on validation -- so the
notebook's selective-prediction numbers show a real, non-zero risk on test rather than a
guarantee that happens to hold. `bank`, `spring` and `bat` each carry one `test` example that is
right but at a low confidence, so a correct answer can still be sent to review (for its
confidence, this time). The hard case this use case calls for, a sentence whose context is too
thin to tell two senses apart, appears twice, close to an even split across the word's two senses and
`unclear` with `unclear` on top: as a `demo` example (`d01-bank-thin`) and once scored
(`t04-crane-thin`). Two more `demo` examples exist only so the notebook's up-close section never
has to reach into a scored split: `d03-spring-low` names a real sense at a low confidence
(correct, like the three `test` examples above, demonstrating the "confidence below the
threshold" review reason on its own, without also choosing `unclear`), and `d04-bat-wrong` is
wrong and confident, the same shape as `t05-crane-wrong`. The replay keys come from the same
`build_state` and `build_questions` the notebook uses, via `helpers.py`; because the option list
depends on the target word, each row's key is computed from that word's own question.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# (id, split, sentence_id, word, sentence, gold sense or None for demo, probabilities)
# Probabilities are in the order of that word's own options (its two senses, then "unclear",
# see helpers.senses_for) and sum to 1.
ROWS = [
    # --- bank: financial_institution (FI), river_edge (RE) ---------------------------------
    ("v01-bank-fi", "validation", "S101", "bank",
     "I need to open a new checking account at the bank before it closes at five.",
     "financial_institution", (0.90, 0.05, 0.05)),
    ("v02-bank-fi", "validation", "S102", "bank",
     "The bank approved my small business loan after reviewing two years of statements.",
     "financial_institution", (0.88, 0.06, 0.06)),
    ("v03-bank-wrong", "validation", "S103", "bank",
     "The old bank was crumbling after years of neglect.",
     "financial_institution", (0.35, 0.55, 0.10)),
    ("v04-bank-re", "validation", "S104", "bank",
     "We sat on the grassy bank of the river and watched the current drift by.",
     "river_edge", (0.05, 0.90, 0.05)),
    ("v05-bank-re", "validation", "S105", "bank",
     "Heavy spring rain caused the river to overflow its bank and flood the lower field.",
     "river_edge", (0.08, 0.85, 0.07)),
    ("t01-bank-fi", "test", "S106", "bank",
     "She deposited her paycheck at the bank on her way home from work.",
     "financial_institution", (0.89, 0.05, 0.06)),
    ("t02-bank-fi", "test", "S107", "bank",
     "The bank raised its interest rate on savings accounts this quarter.",
     "financial_institution", (0.87, 0.06, 0.07)),
    ("t03-bank-low", "test", "S108", "bank",
     "The bank was quiet when I walked in this morning.",
     "financial_institution", (0.42, 0.38, 0.20)),
    ("t04-bank-re", "test", "S109", "bank",
     "The fisherman cast his line from the muddy bank near the old bridge.",
     "river_edge", (0.06, 0.88, 0.06)),
    ("t05-bank-re", "test", "S110", "bank",
     "Children skipped stones across the water from the bank.",
     "river_edge", (0.10, 0.83, 0.07)),
    # --- crane: machine, bird ---------------------------------------------------------------
    ("v01-crane-machine", "validation", "S111", "crane",
     "The construction crew used a tall crane to lift steel beams onto the new office tower.",
     "machine", (0.90, 0.05, 0.05)),
    ("v02-crane-machine", "validation", "S112", "crane",
     "A crane operator carefully lowered the shipping container onto the dock.",
     "machine", (0.88, 0.06, 0.06)),
    ("v03-crane-bird", "validation", "S113", "crane",
     "A white crane stood motionless in the shallow water, waiting for a fish to pass.",
     "bird", (0.06, 0.89, 0.05)),
    ("v04-crane-bird", "validation", "S114", "crane",
     "We watched a pair of cranes wade through the marsh at dawn.",
     "bird", (0.15, 0.75, 0.10)),
    ("v05-crane-wrong", "validation", "S115", "crane",
     "The crane moved across the yard without making a sound.",
     "machine", (0.30, 0.60, 0.10)),
    ("t01-crane-machine", "test", "S116", "crane",
     "The crane's long arm swung the concrete slab into place above the tenth floor.",
     "machine", (0.91, 0.04, 0.05)),
    ("t02-crane-machine", "test", "S117", "crane",
     "Workers guided the crane as it hoisted the air conditioning unit onto the roof.",
     "machine", (0.87, 0.06, 0.07)),
    ("t03-crane-bird", "test", "S118", "crane",
     "The crane stretched its long neck and took off from the riverbank.",
     "bird", (0.07, 0.88, 0.05)),
    ("t04-crane-thin", "test", "S119", "crane",
     "The crane stood near the water's edge for a long while.",
     "bird", (0.30, 0.32, 0.38)),
    ("t05-crane-wrong", "test", "S120", "crane",
     "A crane waded slowly through the shallow marsh at sunrise, dipping its beak into the "
     "water to catch a fish.",
     "bird", (0.80, 0.15, 0.05)),
    # --- spring: season, coil ----------------------------------------------------------------
    ("v01-spring-season", "validation", "S121", "spring",
     "The flowers bloom every spring once the frost melts away.",
     "season", (0.90, 0.05, 0.05)),
    ("v02-spring-season", "validation", "S122", "spring",
     "We planted the garden in spring, right after the last frost.",
     "season", (0.88, 0.06, 0.06)),
    ("v03-spring-coil", "validation", "S123", "spring",
     "The mechanic replaced the broken spring in the car's suspension.",
     "coil", (0.07, 0.88, 0.05)),
    ("v04-spring-coil", "validation", "S124", "spring",
     "A small spring inside the pen pushes the tip back when you click it.",
     "coil", (0.15, 0.75, 0.10)),
    ("v05-spring-wrong", "validation", "S125", "spring",
     "The spring finally gave way under the pressure.",
     "coil", (0.55, 0.35, 0.10)),
    ("t01-spring-season", "test", "S126", "spring",
     "Spring arrived late this year, so the trees budded in April instead of March.",
     "season", (0.89, 0.05, 0.06)),
    ("t02-spring-season", "test", "S127", "spring",
     "Every spring, the local farmers market reopens along Main Street.",
     "season", (0.86, 0.07, 0.07)),
    ("t03-spring-coil", "test", "S128", "spring",
     "The old mattress had a spring poking through the fabric.",
     "coil", (0.07, 0.87, 0.06)),
    ("t04-spring-low", "test", "S129", "spring",
     "There was a spring somewhere inside the mechanism that needed tightening.",
     "coil", (0.38, 0.44, 0.18)),
    ("t05-spring-season", "test", "S130", "spring",
     "The spring forecast promised warmer days ahead.",
     "season", (0.80, 0.10, 0.10)),
    # --- bat: animal, equipment ---------------------------------------------------------------
    ("v01-bat-animal", "validation", "S131", "bat",
     "A bat flew out of the cave just as the sun went down.",
     "animal", (0.90, 0.05, 0.05)),
    ("v02-bat-animal", "validation", "S132", "bat",
     "The colony of bats hung upside down from the ceiling of the tunnel.",
     "animal", (0.85, 0.08, 0.07)),
    ("v03-bat-equipment", "validation", "S133", "bat",
     "He gripped the bat tightly before swinging at the fastball.",
     "equipment", (0.06, 0.89, 0.05)),
    ("v04-bat-wrong", "validation", "S134", "bat",
     "The bat hung in the old shed for years, untouched.",
     "equipment", (0.60, 0.30, 0.10)),
    ("t01-bat-animal", "test", "S135", "bat",
     "Scientists tracked the bat's flight path using a small radio tag.",
     "animal", (0.88, 0.06, 0.06)),
    ("t02-bat-animal", "test", "S136", "bat",
     "A single bat darted between the trees at twilight, hunting insects.",
     "animal", (0.84, 0.08, 0.08)),
    ("t03-bat-equipment", "test", "S137", "bat",
     "The coach handed her a new bat before the championship game.",
     "equipment", (0.07, 0.87, 0.06)),
    ("t04-bat-low", "test", "S138", "bat",
     "There was a bat near the old barn at dusk.",
     "animal", (0.45, 0.40, 0.15)),
    # --- demo: 4 examples, shown but never scored ----------------------------------------------
    ("d01-bank-thin", "demo", "S139", "bank",
     "Everyone was talking about the bank this week.",
     None, (0.33, 0.30, 0.37)),
    ("d02-crane-machine", "demo", "S140", "crane",
     "The crane lifted the steel beam onto the fifth floor without a sound.",
     None, (0.92, 0.04, 0.04)),
    ("d03-spring-low", "demo", "S141", "spring",
     "Something about the spring felt different this time.",
     None, (0.40, 0.36, 0.24)),
    ("d04-bat-wrong", "demo", "S142", "bat",
     "The bat glided silently between the trees, swooping low to snatch an insect before "
     "vanishing into the dark.",
     None, (0.10, 0.85, 0.05)),
]  # fmt: skip


def options_for(word: str) -> list[str]:
    """The option order for ``word``, matching ``helpers.build_questions(word)``."""
    return list(helpers.senses_for(word))


def answers_for(word: str, probabilities: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over that word's options."""
    return {
        "sense": ChoiceAnswer.from_probabilities(
            dict(zip(options_for(word), probabilities, strict=True)), provenance
        )
    }


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, sentence_id, word, sentence, label, _probs in rows:
        fields = {"sentence_id": sentence_id, "word": word, "sentence": sentence}
        questions = helpers.build_questions(word)
        key = replay_key(helpers.build_state(fields), questions)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, sentence_id, word, sentence, _label, probs in rows:
        fields = {"sentence_id": sentence_id, "word": word, "sentence": sentence}
        questions = helpers.build_questions(word)
        key = replay_key(helpers.build_state(fields), questions)
        answers = answers_for(word, probs, Provenance.synthetic())
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
