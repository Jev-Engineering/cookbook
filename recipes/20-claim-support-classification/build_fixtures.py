"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 20.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect. The hard cases the issue names are included and tagged in their id:

- ``-ontopic-unsettled``: a passage on the same topic that does not settle the claim either way
  (``unresolved``), because the thing being measured is still in progress or has not been
  reported yet.
- ``-weaker``: a passage that only supports a narrower or weaker version of the claim, which does
  not settle the broader claim as stated (``unresolved``).
- ``-stronger``: a passage that proves a strictly stronger claim, which does settle (supports) the
  weaker claim it logically contains (``supports``).
- ``-numeric`` / ``-date``: a passage that contradicts the claim by giving an inconsistent number
  or date rather than an outright denial (``contradicts``).
- ``-lookalike``: a passage that shares the claim's keywords but is about a different population or
  subject, so it does not address what the claim actually asserts (``unresolved``).
- ``t16-confident-wrong``: the one case this recipe's evaluation relies on: the stored answer is
  confidently wrong (``supports`` at a top probability of 0.80, a Choice confidence of
  ``(0.80 - 1/3) / (1 - 1/3) = 0.70``, well above the 0.4000 threshold this recipe's notebook
  freezes on ``validation``), stored on a ``test`` example whose gold label is ``contradicts``, so
  the frozen confidence threshold does not catch it and selective risk on `test` is non-zero.
- ``v16-numeric-missed``: a second wrong answer, this time on ``validation``, so the threshold
  chosen there has to actually exclude something (a non-vacuous selection) rather than accepting
  every validation example as given. The claim/passage pair is an unambiguous numeric
  ``contradicts`` by the criteria above (the passage's headcount is well under the claim's), but
  the stored answer misreads it as ``unresolved`` at a top probability of 0.58 (confidence 0.37),
  low enough that the frozen threshold sends it to review rather than reporting it wrong.

The replay keys come from the same ``build_state`` and ``build_questions`` the notebook uses, via
``helpers.py``. Generating inputs and labels is kept separate from generating responses, on
purpose (the pattern ``recipes/_template/build_fixtures.py`` sets): once ``responses.json`` holds
even one recorded answer (provenance "recorded", captured from a real Jev call), running this
script again must not silently replace it with a synthetic probability. ``inputs.jsonl`` and
``labels.jsonl`` are always rewritten from ``ROWS``, because neither ever holds a model's answer;
``responses.json`` is rewritten only when it does not yet exist, holds only synthetic answers, or
``--force`` is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
OPTIONS = list(QUESTIONS["relation"].criteria)  # supports, contradicts, unresolved

# (id, split, passage_id, claim, passage, gold label or None for demo, stored probabilities)
# Probabilities are in OPTIONS order (supports, contradicts, unresolved) and sum to 1.
ROWS = [
    # --- validation: 19 examples --------------------------------------------------------------
    ("v01-supports", "validation", "PSG1001",
     "Rivermoor Bridge reopened to vehicle traffic in June 2023.",
     "After an 18-month closure for cable inspection, Rivermoor Bridge reopened to vehicle "
     "traffic in June 2023.",
     "supports", (0.88, 0.05, 0.07)),
    ("v02-supports", "validation", "PSG1002",
     "The Calmerol trial enrolled more than 500 adult participants.",
     "The Calmerol trial enrolled 612 adult participants across four clinics.",
     "supports", (0.85, 0.05, 0.10)),
    ("v03-contradicts", "validation", "PSG1003",
     "Northwind Robotics' warehouse in Dalton employs over 300 workers.",
     "Northwind Robotics' Dalton warehouse employs 140 workers as of last quarter.",
     "contradicts", (0.08, 0.82, 0.10)),
    ("v04-contradicts", "validation", "PSG1004",
     "The ferry service runs seven days a week.",
     "The ferry service only runs Monday through Friday; it is closed on weekends.",
     "contradicts", (0.05, 0.88, 0.07)),
    ("v05-offtopic", "validation", "PSG1005",
     "The museum's east wing underwent asbestos remediation in 2021.",
     "The museum's gift shop added a new line of postcards and tote bags this spring.",
     "unresolved", (0.08, 0.07, 0.85)),
    ("v06-offtopic", "validation", "PSG1006",
     "Harlow Transit increased its bus fleet by twelve vehicles.",
     "Harlow Transit's customer satisfaction survey had a response rate of 22 percent.",
     "unresolved", (0.10, 0.08, 0.82)),
    ("v07-ontopic-unsettled", "validation", "PSG1007",
     "The new filtration system removes at least 99 percent of sediment from the reservoir.",
     "Engineers installed the new filtration system at the reservoir in March and are "
     "monitoring sediment levels over the coming months.",
     "unresolved", (0.30, 0.10, 0.60)),
    ("v08-weaker", "validation", "PSG1008",
     "Calmerol relieves all common types of joint pain.",
     "In the trial, Calmerol relieved knee and shoulder pain in most participants.",
     "unresolved", (0.45, 0.05, 0.50)),
    ("v09-stronger", "validation", "PSG1009",
     "Calmerol relieves some common types of joint pain.",
     "Calmerol relieved every kind of joint pain reported by trial participants, including "
     "knee, shoulder, hip, and wrist pain.",
     "supports", (0.80, 0.05, 0.15)),
    ("v10-date", "validation", "PSG1010",
     "Harrow Dam's spillway was completed in 2015.",
     "Construction records show Harrow Dam's spillway was completed in 2018, three years "
     "later than originally scheduled.",
     "contradicts", (0.10, 0.80, 0.10)),
    ("v11-lookalike", "validation", "PSG1011",
     "Vitacrest multivitamins reduced fatigue in office workers aged 40 to 65.",
     "A separate study found Vitacrest multivitamins reduced fatigue in college athletes aged "
     "18 to 22, with no data collected on older adults.",
     "unresolved", (0.25, 0.15, 0.60)),
    ("v12-supports", "validation", "PSG1012",
     "The library extended its weekend hours by two hours.",
     "Starting this month, the library will stay open two additional hours on both Saturday "
     "and Sunday.",
     "supports", (0.83, 0.06, 0.11)),
    ("v13-contradicts", "validation", "PSG1013",
     "Oakhaven Elementary's enrollment grew for the third straight year.",
     "Oakhaven Elementary's enrollment fell for the second year in a row, according to the "
     "district's fall count.",
     "contradicts", (0.07, 0.85, 0.08)),
    ("v14-offtopic", "validation", "PSG1014",
     "The city council approved funding for a new bike lane on Birch Street.",
     "The city council's next meeting will include a presentation on recycling collection "
     "schedules.",
     "unresolved", (0.09, 0.06, 0.85)),
    ("v15-supports", "validation", "PSG1015",
     "Northwind Robotics' new assembly line reduced defect rates.",
     "Since the new assembly line went live, Northwind Robotics' defect rate dropped from 3.1 "
     "percent to 1.4 percent.",
     "supports", (0.86, 0.05, 0.09)),
    ("v16-numeric-missed", "validation", "PSG1016",
     "The marathon drew more than 2,000 runners this year.",
     "Registration numbers show 1,840 runners crossed the start line this year, down from "
     "1,970 the previous year.",
     "contradicts", (0.10, 0.32, 0.58)),
    ("v17-contradicts", "validation", "PSG1017",
     "Yearly rainfall in the valley exceeded the ten-year average.",
     "This year's rainfall came in 15 percent below the ten-year average for the valley.",
     "contradicts", (0.08, 0.84, 0.08)),
    ("v18-ontopic-unsettled", "validation", "PSG1018",
     "The bridge's new coating will last at least twenty years.",
     "Crews finished applying the new protective coating to the bridge last week; its "
     "performance will be assessed in future inspections.",
     "unresolved", (0.25, 0.08, 0.67)),
    ("v19-supports", "validation", "PSG1019",
     "Daily ridership on the Blue Line rose after the schedule change.",
     "Blue Line ridership climbed by 9 percent in the month following the schedule change.",
     "supports", (0.84, 0.06, 0.10)),
    # --- test: 19 examples ----------------------------------------------------------------------
    ("t01-supports", "test", "PSG2001",
     "Fernbrook Clinic opened a second location downtown.",
     "Fernbrook Clinic's downtown location held its ribbon-cutting ceremony this morning, its "
     "second site in the city.",
     "supports", (0.87, 0.05, 0.08)),
    ("t02-supports", "test", "PSG2002",
     "The firmware update fixed the battery drain issue.",
     "After installing the firmware update, average battery life on the test devices "
     "increased from six to nine hours.",
     "supports", (0.82, 0.06, 0.12)),
    ("t03-contradicts", "test", "PSG2003",
     "Lakeside High School's football team finished the season undefeated.",
     "Lakeside High School's football team lost three games this season, finishing eighth in "
     "the conference.",
     "contradicts", (0.06, 0.86, 0.08)),
    ("t04-contradicts", "test", "PSG2004",
     "The ferry terminal renovation stayed within its original budget.",
     "The ferry terminal renovation ran $2.3 million over its original budget, according to "
     "the port authority's report.",
     "contradicts", (0.05, 0.89, 0.06)),
    ("t05-offtopic", "test", "PSG2005",
     "The orchard switched to a new irrigation system last spring.",
     "The orchard's farmers market stall sold out of peaches within two hours on Saturday.",
     "unresolved", (0.07, 0.08, 0.85)),
    ("t06-offtopic", "test", "PSG2006",
     "Maple Ridge installed solar panels on the community center roof.",
     "Maple Ridge's town newsletter featured a recipe contest ahead of the harvest festival.",
     "unresolved", (0.09, 0.07, 0.84)),
    ("t07-ontopic-unsettled", "test", "PSG2007",
     "The new checkout software cut average wait times in half.",
     "The store rolled out the new checkout software last week and is collecting wait-time "
     "data over the next month.",
     "unresolved", (0.32, 0.09, 0.59)),
    ("t08-weaker", "test", "PSG2008",
     "The tutoring program improved test scores in every subject.",
     "Students in the tutoring program improved their math test scores by an average of eight "
     "points.",
     "unresolved", (0.42, 0.06, 0.52)),
    ("t09-stronger", "test", "PSG2009",
     "The tutoring program improved test scores in at least one subject.",
     "Students in the tutoring program improved test scores in math, reading, and science "
     "alike.",
     "supports", (0.78, 0.06, 0.16)),
    ("t10-date", "test", "PSG2010",
     "The community center's roof replacement finished in April.",
     "Invoices show the community center's roof replacement was completed in September, five "
     "months behind schedule.",
     "contradicts", (0.08, 0.83, 0.09)),
    ("t11-lookalike", "test", "PSG2011",
     "NeuroFlex headphones reduced reported ear fatigue among call-center workers after six "
     "hours of continuous use.",
     "A separate review found NeuroFlex headphones reduced reported ear fatigue among marathon "
     "runners during two-hour training sessions, with no call-center data collected.",
     "unresolved", (0.30, 0.10, 0.60)),
    ("t12-supports", "test", "PSG2012",
     "The co-op added curbside pickup for online orders.",
     "Starting this week, members can select curbside pickup when they place an online order "
     "with the co-op.",
     "supports", (0.85, 0.05, 0.10)),
    ("t13-contradicts", "test", "PSG2013",
     "Statewide applications to the apprenticeship program doubled this year.",
     "Statewide applications to the apprenticeship program fell by 12 percent this year "
     "compared with last year.",
     "contradicts", (0.07, 0.84, 0.09)),
    ("t14-offtopic", "test", "PSG2014",
     "The transit agency added real-time arrival screens at every station.",
     "The transit agency's annual report highlighted a new employee wellness initiative "
     "launched in the spring.",
     "unresolved", (0.08, 0.07, 0.85)),
    ("t15-supports", "test", "PSG2015",
     "Riverside Press shortened its average book production timeline.",
     "Riverside Press cut its average time from manuscript to finished book from eleven months "
     "to seven.",
     "supports", (0.84, 0.05, 0.11)),
    ("t16-confident-wrong", "test", "PSG2016",
     "Thornwell Dairy's milk recall covered three states.",
     "Thornwell Dairy's recall notice named only a single state, citing a packaging defect at "
     "one plant.",
     "contradicts", (0.80, 0.09, 0.11)),
    ("t17-contradicts", "test", "PSG2017",
     "Average response times for the emergency line improved this quarter.",
     "Average response times for the emergency line grew longer this quarter, rising from four "
     "minutes to six.",
     "contradicts", (0.06, 0.87, 0.07)),
    ("t18-ontopic-unsettled", "test", "PSG2018",
     "The new packaging will cut shipping damage claims by half.",
     "The company switched to the new packaging last month and is tracking shipping damage "
     "claims over the coming quarter.",
     "unresolved", (0.28, 0.09, 0.63)),
    ("t19-supports", "test", "PSG2019",
     "Weekend attendance at the botanical garden rose after the new exhibit opened.",
     "Weekend attendance at the botanical garden climbed 17 percent in the month after the new "
     "butterfly exhibit opened.",
     "supports", (0.86, 0.05, 0.09)),
    # --- demo: 2 examples, shown but never scored -----------------------------------------------
    ("d01-supports", "demo", "PSG3001",
     "The park district replaced the playground's old equipment.",
     "The park district installed brand-new slides, swings and climbing structures at Elm "
     "Street Park this fall, replacing equipment that was over twenty years old.",
     None, (0.84, 0.06, 0.10)),
    ("d02-weaker", "demo", "PSG3002",
     "The clinic's new scheduling system eliminated double-booking entirely.",
     "The clinic adopted a new scheduling system in January; staff say double-bookings have "
     "become rare, though a few still occur during peak hours.",
     None, (0.35, 0.08, 0.57)),
]  # fmt: skip


def answers_for(probabilities: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the three outcomes."""
    return {
        "relation": ChoiceAnswer.from_probabilities(
            dict(zip(OPTIONS, probabilities, strict=True)), provenance
        )
    }


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, passage_id, claim, passage, label, _probs in rows:
        fields = {"passage_id": passage_id, "claim": claim, "passage": passage}
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, passage_id, claim, passage, _label, probs in rows:
        fields = {"passage_id": passage_id, "claim": claim, "passage": passage}
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
