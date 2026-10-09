"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 21.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response here is synthetic: written by hand as probabilities, not produced by a model.
Some are deliberately wrong, so the evaluation in the notebook has something to find, including
at least one answer that is confidently wrong (``v12-reef-misspell`` on ``validation`` and
``t04-capital-wrong-confident`` on ``test``, the latter stored as a confident ``match`` where the
gold label is ``no_match``). Rows whose ``spec`` is ``None`` are settled by ``helpers.settle``
before any request is built: they get no replay key and no stored response at all, so the number
of entries in ``responses.json`` is exactly the number of responses this recipe's notebook ever
asks Jev for, in any mode. ``main()`` checks every row against ``helpers.settle`` so a row's
``spec`` can never silently disagree with what the normaliser would do with it.

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

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# (id, split, fields, gold label or None for a demo example, spec or None)
#
# `spec` is a mapping {option: probability} over ("match", "partial_match", "no_match",
# "needs_review") for a row the normaliser cannot settle, or `None` for a row it can: a text
# response whose normalised form exactly equals one of QUESTION_BANK's accepted phrasings, or
# any response to a NUMBER-kind question (S07: "Jev is not a calculator", so a number question
# is never sent to Jev, whatever the response says). `main()` asserts this split matches
# `helpers.settle` exactly, so ROWS and the normaliser cannot silently drift apart.
ROWS = [
    # --- validation: text questions (5 settled by the normaliser, 8 sent to Jev) ---
    ("v01-tower-canon", "validation", {"quiz_id": "tower", "response": "Petra Lindqvist."},
     "match", None),
    ("v02-tower-partial", "validation", {"quiz_id": "tower", "response": "one of Lindqvist's apprentices"},
     "partial_match", {"match": 0.12, "partial_match": 0.68, "no_match": 0.15, "needs_review": 0.05}),
    ("v03-capital-article", "validation", {"quiz_id": "capital", "response": "The mirrowgate"},
     "match", None),
    ("v04-capital-hedge", "validation", {"quiz_id": "capital", "response": "Either Mirrowgate or Veyla"},
     "needs_review", {"match": 0.30, "partial_match": 0.05, "no_match": 0.10, "needs_review": 0.55}),
    ("v05-guild-canon", "validation", {"quiz_id": "guild", "response": "Doran Hale"},
     "match", None),
    ("v06-guild-overspecific", "validation",
     {"quiz_id": "guild", "response": "Doran Hale, the glassblower who founded it"},
     "match", {"match": 0.74, "partial_match": 0.14, "no_match": 0.07, "needs_review": 0.05}),
    ("v07-guild-hedge", "validation", {"quiz_id": "guild", "response": "Hale, or maybe his daughter"},
     "needs_review", {"match": 0.28, "partial_match": 0.17, "no_match": 0.05, "needs_review": 0.50}),
    ("v08-sonata-alt", "validation", {"quiz_id": "sonata", "response": "Costas"},
     "match", None),
    ("v09-sonata-wrong", "validation", {"quiz_id": "sonata", "response": "Petra Lindqvist"},
     "no_match", {"match": 0.06, "partial_match": 0.08, "no_match": 0.82, "needs_review": 0.04}),
    ("v10-reef-canon", "validation", {"quiz_id": "reef", "response": "Nia Brack"},
     "match", None),
    ("v11-reef-overspecific", "validation",
     {"quiz_id": "reef", "response": "Nia Brack, the marine surveyor"},
     "match", {"match": 0.76, "partial_match": 0.12, "no_match": 0.07, "needs_review": 0.05}),
    # Deliberately wrong and confident: the gold label is the misspelling's obvious reading
    # (match), but the stored answer leans "no_match" at a confidence the threshold below
    # will have to be set above to keep validation's accepted subset perfectly accurate. This
    # is the fixture that makes the threshold selection in the notebook non-vacuous.
    ("v12-reef-misspell", "validation", {"quiz_id": "reef", "response": "Nia Brak"},
     "match", {"match": 0.30, "partial_match": 0.07, "no_match": 0.60, "needs_review": 0.03}),
    ("v13-tower-misspell", "validation", {"quiz_id": "tower", "response": "Petra Lindqvest"},
     "match", {"match": 0.72, "partial_match": 0.10, "no_match": 0.10, "needs_review": 0.08}),
    # --- validation: number questions (always settled, never sent to Jev) ---
    ("v14-moons-digit", "validation", {"quiz_id": "moons", "response": "3"}, "match", None),
    ("v15-moons-wrong", "validation", {"quiz_id": "moons", "response": "4"}, "no_match", None),
    ("v16-siege-word", "validation", {"quiz_id": "siege", "response": "seven years"}, "match", None),
    ("v17-siege-gibberish", "validation", {"quiz_id": "siege", "response": "a long time"},
     "no_match", None),
    ("v18-council-digit", "validation", {"quiz_id": "council", "response": "5 members"},
     "match", None),
    ("v19-council-wrong", "validation", {"quiz_id": "council", "response": "6"}, "no_match", None),

    # --- test: text questions (5 settled by the normaliser, 8 sent to Jev) ---
    ("t01-tower-alt", "test", {"quiz_id": "tower", "response": "lindqvist"}, "match", None),
    ("t02-tower-wrong", "test", {"quiz_id": "tower", "response": "Doran Hale"},
     "no_match", {"match": 0.05, "partial_match": 0.10, "no_match": 0.80, "needs_review": 0.05}),
    ("t03-capital-canon", "test", {"quiz_id": "capital", "response": "Mirrowgate"}, "match", None),
    # The required confidently-wrong fixture: gold says no_match, the stored answer says match
    # at a confidence the frozen validation threshold does not catch, so test's risk is non-zero.
    ("t04-capital-wrong-confident", "test", {"quiz_id": "capital", "response": "Caldenhall"},
     "no_match", {"match": 0.81, "partial_match": 0.07, "no_match": 0.09, "needs_review": 0.03}),
    ("t05-capital-wrong2", "test", {"quiz_id": "capital", "response": "Ashcombe"},
     "no_match", {"match": 0.08, "partial_match": 0.10, "no_match": 0.77, "needs_review": 0.05}),
    ("t06-guild-alt", "test", {"quiz_id": "guild", "response": "Hale"}, "match", None),
    ("t07-guild-partial", "test", {"quiz_id": "guild", "response": "the Hale family"},
     "partial_match", {"match": 0.15, "partial_match": 0.70, "no_match": 0.10, "needs_review": 0.05}),
    ("t08-sonata-canon", "test", {"quiz_id": "sonata", "response": "Imra Costas"}, "match", None),
    ("t09-sonata-misspell", "test", {"quiz_id": "sonata", "response": "Imra Costass"},
     "match", {"match": 0.70, "partial_match": 0.12, "no_match": 0.12, "needs_review": 0.06}),
    ("t10-sonata-partial", "test", {"quiz_id": "sonata", "response": "Costas's apprentice"},
     "partial_match", {"match": 0.18, "partial_match": 0.66, "no_match": 0.11, "needs_review": 0.05}),
    ("t11-reef-alt", "test", {"quiz_id": "reef", "response": "brack"}, "match", None),
    # Jev's own choice is confidently needs_review here (0.80, well above the frozen gate),
    # which is exactly the fixture that makes `evaluate_outcomes` and `evaluate_selective`
    # disagree in the notebook's evaluation: a confidence-only view would count this one as
    # answered (and, by raw choice, right); `helpers.adjudicate`'s unconditional needs_review
    # branch never lets it become a final grade at all.
    ("t12-reef-hedge", "test", {"quiz_id": "reef", "response": "Brack, or maybe Hale"},
     "needs_review", {"match": 0.08, "partial_match": 0.03, "no_match": 0.04, "needs_review": 0.85}),
    ("t13-tower-overspecific", "test",
     {"quiz_id": "tower", "response": "Petra Lindqvist, who lit it during the founding festival"},
     "match", {"match": 0.73, "partial_match": 0.12, "no_match": 0.10, "needs_review": 0.05}),
    # --- test: number questions (always settled, never sent to Jev) ---
    ("t14-moons-word", "test", {"quiz_id": "moons", "response": "three"}, "match", None),
    ("t15-moons-gibberish", "test", {"quiz_id": "moons", "response": "several"}, "no_match", None),
    ("t16-siege-digit", "test", {"quiz_id": "siege", "response": "7"}, "match", None),
    ("t17-siege-wrong", "test", {"quiz_id": "siege", "response": "10 years"}, "no_match", None),
    ("t18-council-word", "test", {"quiz_id": "council", "response": "five"}, "match", None),
    ("t19-council-wrong", "test", {"quiz_id": "council", "response": "a handful"}, "no_match", None),

    # --- demo: shown in the notebook, never scored ---
    ("d01-settled", "demo", {"quiz_id": "capital", "response": "Mirrowgate!"}, None, None),
    ("d02-review", "demo",
     {"quiz_id": "tower", "response": "Maybe Lindqvist, or possibly someone else entirely"},
     None, {"match": 0.22, "partial_match": 0.08, "no_match": 0.12, "needs_review": 0.58}),
]  # fmt: skip


def answers_for(spec, provenance: Provenance):
    """``{question name: answer}`` for one row that was sent to Jev."""
    return {"adjudication": ChoiceAnswer.from_probabilities(dict(spec), provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded. A row whose
    ``spec`` is ``None`` gets empty ``replay_keys``: the normaliser settles it, so the notebook
    never builds a request for it."""
    inputs, labels = [], []
    for ident, split, fields, label, spec in rows:
        keys = [replay_key(helpers.build_state(fields), QUESTIONS)] if spec is not None else []
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``, one entry for every row whose ``spec``
    is not ``None``. Always synthetic: this script never calls Jev, so it can never produce a
    recorded response."""
    responses = {}
    for _ident, _split, fields, _label, spec in rows:
        if spec is None:
            continue
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(spec, Provenance.synthetic())
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def _check_rows_agree_with_the_normaliser(rows):
    """Every row's ``spec`` must agree with what ``helpers.settle`` would do with its fields:
    ``None`` exactly when the normaliser can decide it alone. A row that disagrees would mean
    ROWS and the normaliser have drifted apart, so this raises rather than writing a fixture
    set the notebook's own rule would not reproduce."""
    problems = []
    for ident, _split, fields, _label, spec in rows:
        settled = helpers.settle(fields)
        if (settled is not None) != (spec is None):
            problems.append(
                f"{ident}: settle() returned {settled!r} but spec is "
                f"{'None' if spec is None else 'not None'}"
            )
    if problems:
        raise SystemExit("ROWS disagrees with helpers.settle:\n" + "\n".join(problems))


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
    _check_rows_agree_with_the_normaliser(ROWS)
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
