"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 08.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect in four different ways, on purpose. One wrong answer is in
``validation`` itself (``v06-ambiguous-wrong``, confidence 0.3350): without it, all 14 real-FAQ
``validation`` answers would be correct and ``select_confidence_threshold`` could only return
the lowest observed confidence, whatever the target accuracy -- the gate would never actually be
chosen by anything. With it, the lowest threshold whose answered ``validation`` subset is still
perfectly accurate is 0.3467 (``v17-ambiguous``'s confidence, the next value up), which is what
this recipe's notebook freezes; under that frozen threshold, ``v06-ambiguous-wrong`` itself ends
up reviewed, not reported. The other three are in ``test``, each wrong in a different way: one
question is answered by a real, wrong FAQ at a confidence (0.5333) above the frozen threshold,
so the confidence gate lets a wrong answer through (``t07-ambiguous``); another is answered
``no_match`` -- wrongly -- at a confidence (0.4167) the rule never checks at all, because
``no_match`` bypasses the gate entirely (``t12-no-match-wrong``); a third (``t19-no-match-wrong``)
is wrong but not confident (0.2183), so it is sent to review instead of being reported. The hard
cases the issue names are included and tagged in their id: a question no FAQ addresses
(``-no-match``) and a question two FAQs nearly address (``-ambiguous``). The replay keys come
from the same ``build_state`` and ``build_questions`` the notebook uses, via ``helpers.py``.

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
OPTIONS = list(QUESTIONS["faq"].criteria)  # the 7 options, in the order build_questions builds them


def dist(**given: float) -> dict[str, float]:
    """A full probability mapping over ``OPTIONS``: ``given`` names the option(s) that carry
    real mass; every other option shares the remainder evenly. Keeps each row below readable
    as "the two or three options that matter", rather than seven hand-typed numbers."""
    missing = [o for o in OPTIONS if o not in given]
    remainder = 1.0 - sum(given.values())
    share = remainder / len(missing)
    result = {o: share for o in missing}
    result.update(given)
    return result


def _fields(question_id: str, text: str) -> dict[str, str]:
    return {"question_id": question_id, "text": text}


# (id, split, fields, gold label or None for demo, stored probabilities)
ROWS = [
    # --- validation: 19 examples, all answered correctly ------------------------------------
    ("v01-password-reset", "validation", _fields("Q1001", "I forgot my password and the app won't let me back in."),
     "password_reset", dist(password_reset=0.88)),
    ("v02-password-reset", "validation", _fields("Q1002", "Locked out after three failed attempts, how do I reset my password?"),
     "password_reset", dist(password_reset=0.85)),
    ("v03-change-email", "validation", _fields("Q1003", "I switched jobs and need to put my new email address on file."),
     "change_email", dist(change_email=0.84)),
    ("v04-change-email", "validation", _fields("Q1004", "Can you tell me how to change the email tied to my account?"),
     "change_email", dist(change_email=0.80)),
    ("v05-cancel-subscription", "validation", _fields("Q1005", "Please cancel my plan, I don't want to be charged again."),
     "cancel_subscription", dist(cancel_subscription=0.83)),
    # cancel_subscription vs. billing_cycle; gold is cancel_subscription (an explicit "I want
    # this to end"), but the stored answer confidently (0.3350) names billing_cycle instead --
    # a plausible, wrong answer, deliberately placed in validation itself (see the module
    # docstring: this is the error that gives select_confidence_threshold something real to cut
    # on, instead of returning the lowest observed confidence for any target accuracy).
    ("v06-ambiguous-wrong", "validation", _fields("Q1006", "I want this to end before my card gets charged again."),
     "cancel_subscription", dist(billing_cycle=0.43, cancel_subscription=0.30)),
    ("v07-billing-cycle", "validation", _fields("Q1007", "When is my card going to be charged next?"),
     "billing_cycle", dist(billing_cycle=0.82)),
    ("v08-export-data", "validation", _fields("Q1008", "Is there a way to download everything I've stored in my account?"),
     "export_data", dist(export_data=0.81)),
    ("v09-export-data", "validation", _fields("Q1009", "I need a full copy of my data before I switch tools."),
     "export_data", dist(export_data=0.78)),
    ("v10-delete-account", "validation", _fields("Q1010", "I want my account and everything in it permanently removed."),
     "delete_account", dist(delete_account=0.85)),
    ("v11-delete-account", "validation", _fields("Q1011", "Please delete my account completely, not just cancel the plan."),
     "delete_account", dist(delete_account=0.87)),
    ("v12-no-match", "validation", _fields("Q1012", "Do you have a dark mode in the mobile app?"),
     "no_match", dist(no_match=0.80)),
    ("v13-no-match", "validation", _fields("Q1013", "Can two people share one login?"),
     "no_match", dist(no_match=0.75)),
    ("v14-no-match", "validation", _fields("Q1014", "Does the API have a rate limit I should know about?"),
     "no_match", dist(no_match=0.78)),
    ("v15-no-match", "validation", _fields("Q1015", "What file formats can I upload to my project?"),
     "no_match", dist(no_match=0.72)),
    ("v16-no-match", "validation", _fields("Q1016", "Will you add a feature to schedule posts in advance?"),
     "no_match", dist(no_match=0.76)),
    # Two FAQs nearly address this one (password_reset vs. change_email); the real ask is
    # regaining access, so the gold label is password_reset. Correct, at confidence 0.3467 --
    # once v06-ambiguous-wrong above is excluded, this is the lowest-confidence correct answer
    # left in validation, which is exactly what fixes the threshold the notebook freezes.
    ("v17-ambiguous", "validation", _fields("Q1017", "I can't log in -- is it because my old email bounced? How do I get back into my account?"),
     "password_reset", dist(password_reset=0.44, change_email=0.33)),
    # billing_cycle vs. cancel_subscription; correct, but at confidence 0.3000 -- below the
    # frozen threshold (0.3467), so the rule sends this one to review too, despite it being
    # right: the gate trades some correct, low-confidence coverage for excluding
    # v06-ambiguous-wrong above.
    ("v18-ambiguous", "validation", _fields("Q1018", "Just checking -- how many more times will I be billed before this is over?"),
     "billing_cycle", dist(billing_cycle=0.40, cancel_subscription=0.34)),
    # cancel_subscription vs. delete_account; the question only asks to stop paying, not to
    # remove the account, so the gold label is cancel_subscription.
    ("v19-ambiguous", "validation", _fields("Q1019", "I don't care about deleting anything, I just want the charges to stop."),
     "cancel_subscription", dist(cancel_subscription=0.46, delete_account=0.30)),
    # --- test: 19 examples, three of them wrong on purpose -----------------------------------
    ("t01-password-reset", "test", _fields("Q2001", "I can't remember my password and need to set a new one."),
     "password_reset", dist(password_reset=0.86)),
    ("t02-password-reset", "test", _fields("Q2002", "My password stopped working after the last update, how do I reset it?"),
     "password_reset", dist(password_reset=0.89)),
    ("t03-password-reset", "test", _fields("Q2003", "Three wrong password attempts and now I'm locked out. What now?"),
     "password_reset", dist(password_reset=0.83)),
    ("t04-change-email", "test", _fields("Q2004", "My old email address is no longer active, how do I swap it for a new one?"),
     "change_email", dist(change_email=0.82)),
    # password_reset vs. change_email; the explicit ask is to update the email on file, so the
    # gold label is change_email.
    ("t05-ambiguous", "test", _fields("Q2005", "I keep getting logged out on my phone -- can you update the email on file so password alerts go to the right inbox?"),
     "change_email", dist(change_email=0.44, password_reset=0.34)),
    ("t06-cancel-subscription", "test", _fields("Q2006", "I'd like to cancel my plan before the next renewal."),
     "cancel_subscription", dist(cancel_subscription=0.84)),
    # cancel_subscription vs. billing_cycle; gold is cancel_subscription (an explicit request to
    # stop being charged), but the stored answer confidently (0.5333, above the 0.3467
    # threshold) names billing_cycle instead -- a real, wrong FAQ the confidence gate lets
    # through.
    ("t07-ambiguous", "test", _fields("Q2007", "I want to know how to stop being charged every single month."),
     "cancel_subscription", dist(billing_cycle=0.60, cancel_subscription=0.25)),
    ("t08-billing-cycle", "test", _fields("Q2008", "How often do you bill me for this plan?"),
     "billing_cycle", dist(billing_cycle=0.80)),
    ("t09-billing-cycle", "test", _fields("Q2009", "What date does my subscription renew each month?"),
     "billing_cycle", dist(billing_cycle=0.77)),
    ("t10-billing-cycle", "test", _fields("Q2010", "Can you tell me the schedule you charge my card on?"),
     "billing_cycle", dist(billing_cycle=0.83)),
    ("t11-export-data", "test", _fields("Q2011", "How can I export all of my saved information?"),
     "export_data", dist(export_data=0.79)),
    # Gold is export_data, but the stored answer names no_match at 0.4167 -- no_match is never
    # run past the confidence gate (it has none), so this wrong answer is delivered as a final
    # "no FAQ fits" result, not caught by any threshold.
    ("t12-no-match-wrong", "test", _fields("Q2012", "Can I get a full archive of everything tied to my profile before I leave?"),
     "export_data", dist(no_match=0.50, export_data=0.30)),
    ("t13-delete-account", "test", _fields("Q2013", "Can you permanently erase my account and all its data?"),
     "delete_account", dist(delete_account=0.88)),
    # delete_account vs. cancel_subscription; correct, but at 0.2533 confidence, below the
    # threshold, so the rule sends it to review instead of reporting it.
    ("t14-ambiguous", "test", _fields("Q2014", "Please close everything down -- I don't want the account or the charges anymore."),
     "delete_account", dist(delete_account=0.36, cancel_subscription=0.32)),
    ("t15-no-match", "test", _fields("Q2015", "Is there a keyboard shortcut to duplicate a project?"),
     "no_match", dist(no_match=0.79)),
    ("t16-no-match", "test", _fields("Q2016", "Do you offer a student discount on the paid plan?"),
     "no_match", dist(no_match=0.74)),
    ("t17-no-match", "test", _fields("Q2017", "Can I integrate this with a calendar app?"),
     "no_match", dist(no_match=0.81)),
    ("t18-no-match", "test", _fields("Q2018", "Is the mobile app available in French?"),
     "no_match", dist(no_match=0.70)),
    # Gold is no_match, but the stored answer names billing_cycle at 0.2183 confidence, below
    # the threshold, so it is sent to review -- wrong, but caught, unlike t07 above.
    ("t19-no-match-wrong", "test", _fields("Q2019", "Will my free trial convert to a paid plan automatically?"),
     "no_match", dist(billing_cycle=0.33, no_match=0.28)),
    # --- demo: 2 examples, shown but never scored ---------------------------------------------
    ("d01-ambiguous", "demo", _fields("Q3001", "I need to update my account because I don't recognize the email address listed anymore."),
     None, dist(change_email=0.42, password_reset=0.35)),
    ("d02-no-match", "demo", _fields("Q3002", "Can I pay with cryptocurrency instead of a credit card?"),
     None, dist(no_match=0.58, billing_cycle=0.15)),
]  # fmt: skip


def answers_for(spec: dict[str, float], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the seven options."""
    return {"faq": ChoiceAnswer.from_probabilities(spec, provenance)}


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
