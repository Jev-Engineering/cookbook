"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 28.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic: written by hand as probabilities over the four suitability
levels, not produced by a model. Thirteen tasks (5 `validation`, 5 `test`, 3 `demo`), each
retrieved against the same fixed skill catalog ``helpers.SKILL_CATALOG`` with
``helpers.retrieve_candidates`` -- the same real retrieval step the notebook calls -- so this
script can never hand-pick a task's candidates behind the rule's back. Three tasks per scored
split are clear-cut (one retrieved skill's description plainly states it performs the task, the
other two plainly do not); one per split has every retrieved skill's description only in the
same general area as the task, never stating the specific action, so no candidate reaches the
business cutoff (`v03`, `t03`); one per split retrieves two skills whose descriptions are
*both* genuinely plausible for the task, scored close together on purpose -- the "two skills
equally plausible" hard case the use case names (`v04`, `t04`); and one per split is a
deliberately wrong pair of stored answers: the skill that actually fits is scored low and the
skill that only sounds related is scored confidently high, so the composed rule picks the wrong
one with a wide margin (`v05`, `t05`) -- on `validation` this is one of the examples the margin
threshold is chosen from, and on `test` it is the one the frozen threshold still lets through,
giving the evaluation a real, non-zero risk to report. Three more tasks are `demo`: one of each
shape (a confident correct pick, the ambiguous pair, and a cutoff failure), shown up close before
any aggregate and never scored. Every row names the level its own stored answer is written to
land on (``intended_level``), separately from the task's gold level (``gold_level``), so the two
can disagree on purpose where a row is deliberately wrong, and ``tests/test_build_fixtures.py``
checks every committed stored answer's modal level against its row's own ``intended_level``.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from TASKS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, Provenance, ScoreAnswer, load_helpers, replay_key
from jev_cookbook.evaluation import score_level

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
LEVELS = list(helpers.SUITABILITY_LEVELS)

# Probability vectors over the four levels (not_suitable, related, suitable, ideal), each
# summing to 1. Reused across tasks on purpose, the same way recipes/17-passage-reranking reuses
# one vector per rubric level for every passage at that level: the *level* a row is written to
# land on is what the row names (below), not the particular vector, so reusing a vector is not
# the same mistake a confidence-only shorthand would make (CONTRIBUTING's rule 11 risk: a spec
# that *infers* its label). Every vector here is given directly as a full distribution; nothing
# about the stored level is defaulted or inferred.
IDEAL_CONFIDENT = (0.02, 0.03, 0.10, 0.85)  # modal level 3
SUITABLE_CONFIDENT = (0.03, 0.09, 0.73, 0.15)  # modal level 2
RELATED_A = (0.09, 0.71, 0.14, 0.06)  # modal level 1
RELATED_B = (0.14, 0.58, 0.20, 0.08)  # modal level 1, a different vector for the same level
RELATED_C = (0.12, 0.60, 0.21, 0.07)  # modal level 1, a third vector for the same level
NOT_SUITABLE_CONFIDENT = (0.72, 0.16, 0.08, 0.04)  # modal level 0
IDEAL_MEDIUM = (0.04, 0.08, 0.18, 0.70)  # modal level 3, less peaked -- the wrong, over-eager pick
# Close-scoring pairs for the "two skills equally plausible" tasks: both land on modal level 3,
# with a small enough gap between their expected scores that the margin check should not let
# either one through automatically. Four distinct vectors (not one pair reused twice) so the
# two ambiguous tasks do not mirror each other digit for digit.
TIE_HIGH_1 = (0.03, 0.10, 0.35, 0.52)
TIE_LOW_1 = (0.03, 0.12, 0.38, 0.47)
TIE_HIGH_2 = (0.02, 0.08, 0.33, 0.57)
TIE_LOW_2 = (0.02, 0.11, 0.40, 0.47)
TIE_HIGH_3 = (0.04, 0.09, 0.32, 0.55)
TIE_LOW_3 = (0.03, 0.13, 0.39, 0.45)

# One entry per task: (task_id, split, task text, {skill_id: (gold_level_or_None, intended_level,
# probabilities)}). `gold_level` is this skill's true suitability level for this task, written
# by the fixture author from the rubric; it is `None` for a `demo` task, which carries no label.
# `intended_level` is the modal level the row's own `probabilities` are written to land on --
# equal to `gold_level` everywhere the stored answer is right, and deliberately different on the
# two rows that are not (both skills of v05, and both skills of t05).
TASKS = [
    (
        "v01",
        "validation",
        "Book a flight and hotel for next week's trip to the Denver sales conference.",
        {
            "travel_booking": (3, 3, IDEAL_CONFIDENT),
            "code_review_summary": (0, 0, NOT_SUITABLE_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v02",
        "validation",
        "Summarize the changes in this pull request before our team reviews it.",
        {
            "code_review_summary": (3, 3, IDEAL_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v03",
        "validation",
        "Set up a recurring reminder to log my travel expenses every Friday afternoon.",
        {
            # No retrieved skill's description states the specific action this task asks for
            # (a recurring reminder); all three are only in the same general area. The business
            # cutoff sends this to review on its own, whatever the margin among them turns out
            # to be.
            "travel_booking": (1, 1, RELATED_A),
            "calendar_scheduling": (1, 1, RELATED_B),
            "expense_report": (1, 1, RELATED_C),
        },
    ),
    (
        "v04",
        "validation",
        "Arrange the calendar slot and travel plans for next week's trip to the Chicago "
        "conference.",
        {
            # The hard case: both calendar_scheduling and travel_booking plausibly fit ("the
            # calendar slot" is scheduling; "travel plans" is booking), so both carry the
            # highest gold level and the stored scores are written close together.
            "calendar_scheduling": (3, 3, TIE_HIGH_1),
            "travel_booking": (3, 3, TIE_LOW_1),
            "code_review_summary": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v05",
        "validation",
        "Pull up the internal doc on how travel booking approvals work for the finance team.",
        {
            # Deliberately wrong: the task only asks to find a document, which is exactly
            # doc_search's job (gold level 3), but the stored answer confidently scores
            # travel_booking instead (gold level 1: the same general area, mentioned by name,
            # but the task never asks to book anything) -- and under-scores doc_search to match.
            # This is one of the examples the margin threshold below is chosen from.
            "travel_booking": (1, 3, IDEAL_MEDIUM),
            "doc_search": (3, 1, RELATED_A),
            "code_review_summary": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t01",
        "test",
        "Set up a 30 minute meeting with the design team for Thursday afternoon.",
        {
            "calendar_scheduling": (3, 3, IDEAL_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t02",
        "test",
        "Find the article that explains how two-factor authentication works for our account.",
        {
            "doc_search": (3, 3, IDEAL_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t03",
        "test",
        "I want to understand how expense categories map to our department budgets this quarter.",
        {
            "expense_report": (1, 1, RELATED_A),
            "calendar_scheduling": (1, 1, RELATED_B),
            "travel_booking": (1, 1, RELATED_C),
        },
    ),
    (
        "t04",
        "test",
        "Put this on the calendar and sort out travel arrangements for next month's trip to "
        "the Austin summit.",
        {
            "travel_booking": (3, 3, TIE_HIGH_2),
            "calendar_scheduling": (3, 3, TIE_LOW_2),
            "code_review_summary": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t05",
        "test",
        "Find the internal article explaining how to categorize client dinner expenses for "
        "reimbursement.",
        {
            # Deliberately wrong, the case the frozen margin threshold does not catch: the task
            # asks to find an article (doc_search, gold level 3), but the stored answer scores
            # expense_report confidently instead (gold level 1) and scores doc_search as if it
            # were not suitable at all.
            "expense_report": (1, 3, IDEAL_CONFIDENT),
            "doc_search": (3, 0, NOT_SUITABLE_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "d01",
        "demo",
        "Submit my taxi and hotel receipts from last week's client visit for reimbursement.",
        {
            "expense_report": (None, 3, IDEAL_CONFIDENT),
            "travel_booking": (None, 0, NOT_SUITABLE_CONFIDENT),
            "code_review_summary": (None, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "d02",
        "demo",
        "Handle the calendar schedule and travel logistics for next week's trip to the "
        "Seattle offsite.",
        {
            "travel_booking": (None, 3, TIE_HIGH_3),
            "calendar_scheduling": (None, 3, TIE_LOW_3),
            "code_review_summary": (None, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "d03",
        "demo",
        "Set up a recurring reminder to track my conference travel expenses.",
        {
            "travel_booking": (None, 1, RELATED_A),
            "calendar_scheduling": (None, 1, RELATED_B),
            "expense_report": (None, 1, RELATED_C),
        },
    ),
]


def _fields(task_id: str, task: str, skill_id: str) -> dict:
    return {
        "task_id": task_id,
        "task": task,
        "skill_id": skill_id,
        "skill": helpers.SKILL_CATALOG[skill_id],
    }


def _rows(tasks):
    """Flatten ``TASKS`` into one row per (task, retrieved skill) pair, in retrieval order,
    calling the same ``retrieve_candidates`` the notebook calls -- so this script can never
    hand-pick a task's candidates behind the rule's back. Each row is
    ``(id, split, fields, gold_level, intended_level, probabilities)``.
    """
    rows = []
    for task_id, split, task, specs in tasks:
        candidates = helpers.retrieve_candidates(task)
        if set(candidates) != set(specs):
            raise SystemExit(
                f"{task_id}: retrieve_candidates returned {candidates}, "
                f"but TASKS names {sorted(specs)}"
            )
        for skill_id in candidates:
            gold_level, intended_level, probabilities = specs[skill_id]
            ident = f"{task_id}-{skill_id}"
            rows.append(
                (ident, split, _fields(task_id, task, skill_id), gold_level, intended_level,
                 probabilities)
            )  # fmt: skip
    return rows


def answers_for(probabilities: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Score answer over the four levels."""
    return {"relevance": ScoreAnswer.from_probabilities(list(probabilities), LEVELS, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, gold_level, _intended_level, _probabilities in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if gold_level is not None:
            labels.append({"id": ident, "label": gold_level})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, fields, _gold_level, _intended_level, probabilities in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(probabilities, Provenance.synthetic())
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def check_intended_levels(rows) -> None:
    """Every row's stored answer must land on the level the row itself names
    (``intended_level``), never a level inferred from the probabilities after the fact
    (CONTRIBUTING's rule 11 risk). Raises if any row disagrees with its own ``probabilities``."""
    for ident, _split, _fields, _gold_level, intended_level, probabilities in rows:
        answers = answers_for(probabilities, Provenance.synthetic())
        level = score_level(answers["relevance"])
        if level != intended_level:
            raise SystemExit(
                f"{ident}: probabilities land on level {level}, but TASKS names "
                f"intended_level {intended_level}"
            )


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
    used only to warn when a TASKS edit has desynchronised the two."""
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
    if not TASKS:
        raise SystemExit("add tasks to TASKS in build_fixtures.py")
    rows = _rows(TASKS)
    check_intended_levels(rows)
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(rows)
    for name, items in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\n" for row in items)
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    responses_file = folder / "responses.json"
    if _is_recorded(responses_file) and not args.force:
        message = (
            f"refusing to overwrite {responses_file}: it holds a recorded response "
            "(pass --force to overwrite it anyway)"
        )
        if _unresolved_keys(inputs, responses_file):
            message += (
                "\ninputs.jsonl and labels.jsonl above were rewritten from TASKS; "
                "responses.json was not, and at least one of the keys the rewritten inputs "
                "ask for is missing from it. The three files are desynchronised until you "
                "--force a rewrite or record the missing answers."
            )
        raise SystemExit(message)
    responses = build_responses(rows)
    # The same serialization jev_cookbook.live._dump writes: only the top-level keys are
    # sorted; each response keeps the field order DecisionResult.to_dict() emits. Matching the
    # recorder exactly, rather than json.dumps(..., sort_keys=True) (which also sorts every
    # nested dict alphabetically), keeps a recording's diff to the values that actually changed.
    text = json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n"
    responses_file.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
