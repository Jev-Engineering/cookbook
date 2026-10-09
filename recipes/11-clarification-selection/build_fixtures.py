"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 11.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect in four different ways, on purpose. One wrong answer is in ``validation``
itself (``v08-scope-wrong``, confidence 0.3000): without it, every real-catalog ``validation``
answer would be correct and ``select_confidence_threshold`` could only return the lowest observed
confidence, whatever the target accuracy -- the gate would never actually be chosen by anything.
With it, the lowest threshold whose answered ``validation`` subset is still perfectly accurate is
0.3350 (``v16-access-ambiguous``'s confidence, the next value up), which is what this recipe's
notebook freezes; under that frozen threshold, ``v08-scope-wrong`` itself ends up reviewed, not
reported. The other three are in ``test``, each wrong in a different way: one task is answered by
a real, wrong catalog option at a confidence (0.4750) above the frozen threshold, so the
confidence gate lets a wrong answer through (``t09-format-wrong``); another is answered
``no_clarification_needed`` -- wrongly -- at a confidence (0.4750) the rule never checks at all,
because ``no_clarification_needed`` bypasses the gate entirely (``t12-budget-wrong``); a third
(``t15-access-wrong-caught``) is wrong but not confident (0.0900), so it is sent to review instead
of being reported. The hard cases the issue names are included: tasks that omit one specific
piece of information (every ``ask_*``-labelled row) and tasks that omit nothing
(``no_clarification_needed``). The replay keys come from the same ``build_state`` and
``build_questions`` the notebook uses, via ``helpers.py``.

Generating inputs and labels is kept separate from generating responses, on purpose (the pattern
``recipes/_template/build_fixtures.py`` sets): once responses.json holds even one recorded answer
(provenance "recorded", captured from a real Jev call), running this script again must not
silently replace it with a synthetic probability. inputs.jsonl and labels.jsonl are always
rewritten from ROWS, because neither ever holds a model's answer; responses.json is rewritten only
when it does not yet exist, holds only synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
OPTIONS = list(QUESTIONS["clarification"].criteria)  # the 7 options, in build_questions's order


def dist(**given: float) -> dict[str, float]:
    """A full probability mapping over ``OPTIONS``: ``given`` names the option(s) that carry
    real mass; every other option shares the remainder evenly. Keeps each row below readable
    as "the one or two options that matter", rather than seven hand-typed numbers."""
    missing = [o for o in OPTIONS if o not in given]
    remainder = 1.0 - sum(given.values())
    share = remainder / len(missing)
    result = {o: share for o in missing}
    result.update(given)
    return result


def _fields(task_id: str, text: str) -> dict[str, str]:
    return {"task_id": task_id, "text": text}


# (id, split, fields, gold label or None for demo, stored probabilities)
ROWS = [
    # --- validation: 19 examples, one wrong on purpose ---------------------------------------
    ("v01-deadline-slidedeck", "validation",
     _fields("TK101", "Put together the slide deck for the partner review."),
     "ask_deadline", dist(ask_deadline=0.85)),
    ("v02-deadline-letter", "validation",
     _fields("TK102", "Draft the vendor renewal letter for Acme Corp."),
     "ask_deadline", dist(ask_deadline=0.82)),
    ("v03-deadline-checklist", "validation",
     _fields("TK103", "Pull together the onboarding checklist for the new hires."),
     "ask_deadline", dist(ask_deadline=0.80)),
    ("v04-recipient-slidedeck", "validation",
     _fields("TK104", "Put together a slide deck summarizing last quarter's results by Friday."),
     "ask_recipient", dist(ask_recipient=0.84)),
    ("v05-recipient-email", "validation",
     _fields("TK105", "Draft an email about the new expense policy, ready to go out today."),
     "ask_recipient", dist(ask_recipient=0.81)),
    ("v06-recipient-export", "validation",
     _fields(
         "TK106", "Export the support ticket data from this month as a spreadsheet by end of day."
     ),
     "ask_recipient", dist(ask_recipient=0.78)),
    ("v07-scope-sales", "validation",
     _fields("TK107", "Pull the sales numbers into a spreadsheet for the regional manager by Friday."),
     "ask_scope", dist(ask_scope=0.83)),
    # ask_scope vs. ask_format; gold is ask_scope (the report's shape is already named, its
    # period and dataset are not), but the stored answer confidently (0.40) names ask_format
    # instead -- a plausible, wrong answer, deliberately placed in validation itself (see the
    # module docstring: this is the error that gives select_confidence_threshold something real
    # to cut on, instead of returning the lowest observed confidence for any target accuracy).
    ("v08-scope-wrong", "validation",
     _fields("TK108", "Put together a report on support tickets for the ops lead, due next week."),
     "ask_scope", dist(ask_format=0.40, ask_scope=0.30)),
    ("v09-scope-customerlist", "validation",
     _fields("TK109", "Export the customer list as a spreadsheet for the marketing team today."),
     "ask_scope", dist(ask_scope=0.79)),
    ("v10-format-salesnumbers", "validation",
     _fields("TK110", "Put together the Q3 sales numbers for the leadership team by Monday."),
     "ask_format", dist(ask_format=0.80)),
    ("v11-format-ticketvolumes", "validation",
     _fields(
         "TK111", "Pull together this month's support ticket volumes for the ops lead, due Friday."
     ),
     "ask_format", dist(ask_format=0.76)),
    ("v12-budget-travel", "validation",
     _fields("TK112", "Book a flight and hotel for the Chicago conference next month."),
     "ask_budget", dist(ask_budget=0.84)),
    ("v13-budget-room", "validation",
     _fields("TK113", "Reserve a conference room and catering for the all-hands on the 20th."),
     "ask_budget", dist(ask_budget=0.79)),
    ("v14-access-folder", "validation",
     _fields("TK114", "Set up a shared folder for the onboarding materials by Friday."),
     "ask_access_level", dist(ask_access_level=0.82)),
    ("v15-access-tracker", "validation",
     _fields("TK115", "Create a shared tracker for the open vendor contracts, ready today."),
     "ask_access_level", dist(ask_access_level=0.80)),
    # ask_access_level vs. ask_recipient; correct, but at confidence 0.3350 -- once
    # v08-scope-wrong above is excluded, this is the lowest-confidence correct answer left in
    # validation, which is exactly what fixes the threshold the notebook freezes.
    ("v16-access-ambiguous", "validation",
     _fields(
         "TK116", "Put together a shared dashboard of support metrics for the week, live by Monday."
     ),
     "ask_access_level", dist(ask_access_level=0.43, ask_recipient=0.30)),
    ("v17-none-billing", "validation",
     _fields("TK117", "Export this month's billing errors as a CSV for the finance team by Friday."),
     "no_clarification_needed", dist(no_clarification_needed=0.80)),
    ("v18-none-summary", "validation",
     _fields(
         "TK118",
         "Draft a one-page summary of the Q3 support ticket backlog for the ops lead, ready by "
         "Wednesday.",
     ),
     "no_clarification_needed", dist(no_clarification_needed=0.77)),
    ("v19-none-hotel", "validation",
     _fields("TK119", "Book a $400-budget hotel room for the Denver site visit on the 14th."),
     "no_clarification_needed", dist(no_clarification_needed=0.75)),
    # --- test: 19 examples, three of them wrong on purpose -----------------------------------
    ("t01-deadline-postmortem", "test",
     _fields("TK201", "Write up the incident postmortem for the infra team."),
     "ask_deadline", dist(ask_deadline=0.86)),
    ("t02-deadline-packet", "test",
     _fields("TK202", "Prepare the welcome packet for new clients."),
     "ask_deadline", dist(ask_deadline=0.83)),
    ("t03-deadline-press", "test",
     _fields("TK203", "Draft the press release about the product launch for the press."),
     "ask_deadline", dist(ask_deadline=0.89)),
    ("t04-recipient-summary", "test",
     _fields("TK204", "Draft a quarterly financial summary covering Q3, due Monday."),
     "ask_recipient", dist(ask_recipient=0.85)),
    ("t05-recipient-factsheet", "test",
     _fields(
         "TK205", "Put together a one-page fact sheet about the new pricing plan, ready by Thursday."
     ),
     "ask_recipient", dist(ask_recipient=0.82)),
    ("t06-recipient-csv", "test",
     _fields("TK206", "Export this week's sign-up numbers as a CSV file by tomorrow morning."),
     "ask_recipient", dist(ask_recipient=0.80)),
    ("t07-scope-usage", "test",
     _fields("TK207", "Put together a spreadsheet of usage data for the product team by end of month."),
     "ask_scope", dist(ask_scope=0.81)),
    ("t08-scope-complaints", "test",
     _fields("TK208", "Draft a summary of customer complaints for the support lead, ready Wednesday."),
     "ask_scope", dist(ask_scope=0.78)),
    # ask_format vs. ask_scope; gold is ask_format (the spend breakdown's period is already
    # named, its shape is not), but the stored answer confidently (0.4750, above the 0.3350
    # threshold) names ask_scope instead -- a real, wrong catalog option the confidence gate
    # lets through.
    ("t09-format-wrong", "test",
     _fields("TK209", "Prepare the Q2 marketing spend breakdown for finance by next Tuesday."),
     "ask_format", dist(ask_scope=0.55, ask_format=0.25)),
    ("t10-format-signups", "test",
     _fields("TK210", "Put together this week's sign-up numbers for the growth team today."),
     "ask_format", dist(ask_format=0.77)),
    ("t11-format-churn", "test",
     _fields("TK211", "Pull last year's churn figures together for the board, ready by the 15th."),
     "ask_format", dist(ask_format=0.79)),
    # Gold is ask_budget, but the stored answer names no_clarification_needed at 0.4750 --
    # no_clarification_needed is never run past the confidence gate (it has none), so this
    # wrong answer is delivered as a final "nothing to ask" result, not caught by any threshold.
    ("t12-budget-wrong", "test",
     _fields("TK212", "Book travel for the three engineers attending the vendor summit in March."),
     "ask_budget", dist(no_clarification_needed=0.55, ask_budget=0.25)),
    ("t13-budget-swag", "test",
     _fields("TK213", "Order the branded swag for the new-hire welcome kits, needed by the 1st."),
     "ask_budget", dist(ask_budget=0.78)),
    ("t14-access-planner", "test",
     _fields("TK214", "Build a shared budget planner for next year's offsite, due by the 10th."),
     "ask_access_level", dist(ask_access_level=0.81)),
    # Gold is ask_access_level, but the stored answer names ask_recipient instead, at only 0.09
    # confidence, below the threshold, so it is sent to review -- wrong, but caught, unlike
    # t09 above.
    ("t15-access-wrong-caught", "test",
     _fields(
         "TK215", "Set up a shared doc for collecting interview feedback, ready before Thursday's "
         "debrief."
     ),
     "ask_access_level", dist(ask_recipient=0.22, ask_access_level=0.18)),
    ("t16-none-slidedeck", "test",
     _fields(
         "TK216",
         "Put together a slide deck of last week's growth metrics for the exec team, due Monday "
         "morning.",
     ),
     "no_clarification_needed", dist(no_clarification_needed=0.83)),
    ("t17-none-folder", "test",
     _fields(
         "TK217",
         "Set up a shared folder for the design assets, viewable by the whole product team, ready "
         "today.",
     ),
     "no_clarification_needed", dist(no_clarification_needed=0.79)),
    ("t18-none-room", "test",
     _fields("TK218", "Reserve a conference room for up to $150 for Thursday's offsite planning session."),
     "no_clarification_needed", dist(no_clarification_needed=0.76)),
    ("t19-none-newsletter", "test",
     _fields(
         "TK219",
         "Export the newsletter sign-ups from March as a spreadsheet for the marketing team by end "
         "of day.",
     ),
     "no_clarification_needed", dist(no_clarification_needed=0.82)),
    # --- demo: 2 examples, shown but never scored ---------------------------------------------
    ("d01-ambiguous", "demo",
     _fields("TK301", "Set up a shared project tracker for the ops team."),
     None, dist(ask_access_level=0.40, ask_deadline=0.33)),
    ("d02-confident-none", "demo",
     _fields(
         "TK302", "Export last week's refund requests as a spreadsheet for the finance team by "
         "noon tomorrow."
     ),
     None, dist(no_clarification_needed=0.80)),
]  # fmt: skip


def answers_for(spec: dict[str, float], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the seven options."""
    return {"clarification": ChoiceAnswer.from_probabilities(spec, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, label, _spec in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, fields, _label, spec in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(spec, Provenance.synthetic())
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
