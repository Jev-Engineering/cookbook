"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 04.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect. Two hard-case pairs run through the fixture set twice, once in
``validation`` and once in ``test``, with different wording each time: a ticket that could be
``billing`` or ``account_access`` (paying is blocked by being locked out), and a ticket that
could be ``technical_issue`` or ``feature_request`` (an existing export is broken and a new
export format is requested in the same sentence). The second pair's ``test`` member
(``t08-ambiguous-bug-feature``) is wrong *and* confident, 0.7750, comfortably above the
threshold this recipe's notebook freezes on validation (0.3750), so the selective-prediction
numbers in "Evaluation" show a real, non-zero risk rather than a guarantee that happens to
hold. ``t13-mixed-topics`` is wrong too, but at low confidence, so the threshold catches it
and sends it to review instead. Three ``unclear_request`` tickets per split (vague, off-topic,
and mixing several unrelated requests) are the use case's fallback outcome. The replay
keys come from the same ``build_state`` and ``build_questions`` the notebook uses, via
``helpers.py``.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
OPTIONS = list(QUESTIONS["category"].criteria)  # billing, technical_issue, account_access,
# feature_request, unclear_request

# (id, split, fields, gold label or None for demo, stored probabilities in OPTIONS order)
ROWS = [
    # --- validation: 19 examples --------------------------------------------------------------
    ("v01-billing", "validation", {
        "ticket_id": "TKT-1001", "subject": "Charged twice for renewal",
        "description": "My subscription renewed and I was billed $42 two times on the same "
        "day. Please refund the duplicate charge.",
    }, "billing", (0.90, 0.03, 0.03, 0.02, 0.02)),
    ("v02-billing", "validation", {
        "ticket_id": "TKT-1002", "subject": "Wrong amount on invoice",
        "description": "My latest invoice shows $89 but my plan is $59 a month. Can you "
        "correct the charge?",
    }, "billing", (0.86, 0.04, 0.05, 0.02, 0.03)),
    ("v03-ambiguous-billing-account", "validation", {
        "ticket_id": "TKT-1003", "subject": "Can't update my card because I'm locked out",
        "description": "I need to change my expired credit card, but I can't sign in to "
        "reach the billing page at all.",
    }, "billing", (0.42, 0.05, 0.38, 0.03, 0.12)),
    ("v04-account", "validation", {
        "ticket_id": "TKT-1004", "subject": "Password reset email never arrives",
        "description": "I've requested a password reset three times, but no email shows up "
        "in my inbox or spam folder.",
    }, "account_access", (0.03, 0.08, 0.85, 0.02, 0.02)),
    ("v05-account", "validation", {
        "ticket_id": "TKT-1005", "subject": "Add a teammate to our account",
        "description": "We'd like to give a new team member access to the dashboard under "
        "our existing plan.",
    }, "account_access", (0.04, 0.05, 0.82, 0.06, 0.03)),
    ("v06-technical", "validation", {
        "ticket_id": "TKT-1006", "subject": "App crashes when exporting a report",
        "description": "Every time I click export, the page freezes and then shows a blank "
        "white screen.",
    }, "technical_issue", (0.03, 0.88, 0.03, 0.04, 0.02)),
    ("v07-technical", "validation", {
        "ticket_id": "TKT-1007", "subject": "Dashboard shows last month's data",
        "description": "The usage numbers on my dashboard have not updated since the 3rd, "
        "even though I've used the product every day since.",
    }, "technical_issue", (0.02, 0.84, 0.05, 0.05, 0.04)),
    ("v08-ambiguous-bug-feature", "validation", {
        "ticket_id": "TKT-1008", "subject": "Dark mode looks broken",
        "description": "I turned on dark mode and the text is unreadable; it would be great "
        "if this were fixed, or if you added a proper dark theme option.",
    }, "technical_issue", (0.03, 0.34, 0.05, 0.46, 0.12)),
    ("v09-feature", "validation", {
        "ticket_id": "TKT-1009", "subject": "Request: export to CSV",
        "description": "It would really help our workflow if reports could be exported as "
        "CSV, not just PDF.",
    }, "feature_request", (0.03, 0.06, 0.03, 0.85, 0.03)),
    ("v10-feature", "validation", {
        "ticket_id": "TKT-1010", "subject": "Please add dark mode",
        "description": "Could you add a dark color theme for the app? We use it at night and "
        "the bright screen is hard on the eyes.",
    }, "feature_request", (0.02, 0.07, 0.03, 0.85, 0.03)),
    ("v11-vague", "validation", {
        "ticket_id": "TKT-1011", "subject": "help",
        "description": "it's not working, please fix",
    }, "unclear_request", (0.12, 0.30, 0.10, 0.05, 0.43)),
    ("v12-offtopic", "validation", {
        "ticket_id": "TKT-1012", "subject": "random message",
        "description": "Hey, just wanted to say I love pizza. Do you guys sell any merch?",
    }, "unclear_request", (0.05, 0.05, 0.03, 0.15, 0.72)),
    ("v13-mixed-topics", "validation", {
        "ticket_id": "TKT-1013", "subject": "A few things",
        "description": "My invoice looks off, the app also crashed yesterday, and I also "
        "wish you had a mobile app.",
    }, "unclear_request", (0.20, 0.15, 0.07, 0.08, 0.50)),
    ("v14-billing", "validation", {
        "ticket_id": "TKT-1014", "subject": "Need a receipt for reimbursement",
        "description": "Can you send me a PDF receipt for last month's payment? My employer "
        "needs it for reimbursement.",
    }, "billing", (0.83, 0.04, 0.05, 0.05, 0.03)),
    ("v15-account", "validation", {
        "ticket_id": "TKT-1015", "subject": "Two-factor code never arrives",
        "description": "I set up two-factor authentication and now the text codes never "
        "arrive, so I can't get into my account at all.",
    }, "account_access", (0.04, 0.09, 0.78, 0.04, 0.05)),
    ("v16-technical", "validation", {
        "ticket_id": "TKT-1016", "subject": "Search returns no results",
        "description": "The search bar returns zero results for terms I know exist in my "
        "documents.",
    }, "technical_issue", (0.02, 0.81, 0.06, 0.07, 0.04)),
    ("v17-feature", "validation", {
        "ticket_id": "TKT-1017", "subject": "Bulk delete option",
        "description": "Could you add a way to select multiple items and delete them all at "
        "once, instead of one at a time?",
    }, "feature_request", (0.03, 0.10, 0.03, 0.80, 0.04)),
    ("v18-short", "validation", {
        "ticket_id": "TKT-1018", "subject": "Refund?",
        "description": "Can I get my money back.",
    }, "billing", (0.55, 0.05, 0.05, 0.03, 0.32)),
    ("v19-short", "validation", {
        "ticket_id": "TKT-1019", "subject": "cant login",
        "description": "login broken",
    }, "account_access", (0.04, 0.18, 0.60, 0.03, 0.15)),
    # --- test: 19 examples -----------------------------------------------------------------
    ("t01-billing", "test", {
        "ticket_id": "TKT-2001", "subject": "Double charge on my card",
        "description": "I noticed two identical charges for my monthly plan on the 1st.",
    }, "billing", (0.88, 0.03, 0.04, 0.02, 0.03)),
    ("t02-billing", "test", {
        "ticket_id": "TKT-2002", "subject": "Need an invoice correction",
        "description": "The invoice lists an annual plan but I'm on the monthly plan; please "
        "fix the amount.",
    }, "billing", (0.84, 0.04, 0.05, 0.04, 0.03)),
    ("t03-ambiguous-billing-account", "test", {
        "ticket_id": "TKT-2003", "subject": "Payment method update blocked by login",
        "description": "I can't change my card on file because the account page won't let me "
        "sign in.",
    }, "billing", (0.40, 0.06, 0.37, 0.04, 0.13)),
    ("t04-account", "test", {
        "ticket_id": "TKT-2004", "subject": "Password reset link expired",
        "description": "The reset link in the email expires before I can click it.",
    }, "account_access", (0.03, 0.07, 0.84, 0.03, 0.03)),
    ("t05-account", "test", {
        "ticket_id": "TKT-2005", "subject": "Add a second admin",
        "description": "We need another person added as an admin on our team account.",
    }, "account_access", (0.03, 0.05, 0.85, 0.04, 0.03)),
    ("t06-technical", "test", {
        "ticket_id": "TKT-2006", "subject": "Export button does nothing",
        "description": "Clicking export just spins forever and nothing downloads.",
    }, "technical_issue", (0.03, 0.86, 0.04, 0.04, 0.03)),
    ("t07-technical", "test", {
        "ticket_id": "TKT-2007", "subject": "Numbers don't match between pages",
        "description": "The total on the summary page doesn't match the total on the detail "
        "page for the same report.",
    }, "technical_issue", (0.02, 0.83, 0.06, 0.05, 0.04)),
    ("t08-ambiguous-bug-feature", "test", {
        "ticket_id": "TKT-2008", "subject": "Export only works for PDF",
        "description": "Right now reports can only be exported as PDF; it would help to also "
        "have a CSV option, and sometimes the PDF export button doesn't respond at all.",
    }, "technical_issue", (0.03, 0.08, 0.03, 0.82, 0.04)),
    ("t09-feature", "test", {
        "ticket_id": "TKT-2009", "subject": "Would like scheduled reports",
        "description": "Could reports be emailed automatically every Monday morning instead "
        "of me downloading them each week?",
    }, "feature_request", (0.03, 0.07, 0.03, 0.84, 0.03)),
    ("t10-feature", "test", {
        "ticket_id": "TKT-2010", "subject": "API access",
        "description": "Is there a way to get an API key so we can pull our data "
        "programmatically?",
    }, "feature_request", (0.02, 0.08, 0.04, 0.83, 0.03)),
    ("t11-vague", "test", {
        "ticket_id": "TKT-2011", "subject": "problem",
        "description": "something is wrong, please help",
    }, "unclear_request", (0.14, 0.28, 0.12, 0.06, 0.40)),
    ("t12-offtopic", "test", {
        "ticket_id": "TKT-2012", "subject": "quick question",
        "description": "Do you have a referral program? Also, I really like your logo.",
    }, "unclear_request", (0.05, 0.04, 0.03, 0.18, 0.70)),
    ("t13-mixed-topics", "test", {
        "ticket_id": "TKT-2013", "subject": "A few things",
        "description": "My invoice looks off, the search is also broken, and could you add a "
        "way to sort by date?",
    }, "unclear_request", (0.30, 0.27, 0.05, 0.18, 0.20)),
    ("t14-billing", "test", {
        "ticket_id": "TKT-2014", "subject": "Charged after cancellation",
        "description": "I cancelled last week but was still charged this month.",
    }, "billing", (0.85, 0.04, 0.05, 0.03, 0.03)),
    ("t15-account", "test", {
        "ticket_id": "TKT-2015", "subject": "Locked out after password change",
        "description": "I changed my password and now neither the old nor the new one works.",
    }, "account_access", (0.04, 0.08, 0.80, 0.04, 0.04)),
    ("t16-technical", "test", {
        "ticket_id": "TKT-2016", "subject": "Notifications stopped",
        "description": "I used to get email alerts for new comments and they just stopped "
        "coming entirely.",
    }, "technical_issue", (0.02, 0.80, 0.07, 0.07, 0.04)),
    ("t17-feature", "test", {
        "ticket_id": "TKT-2017", "subject": "Multi-language support",
        "description": "Any plans to support languages other than English in the interface?",
    }, "feature_request", (0.03, 0.09, 0.03, 0.82, 0.03)),
    ("t18-short", "test", {
        "ticket_id": "TKT-2018", "subject": "Billing?",
        "description": "money taken twice",
    }, "billing", (0.50, 0.05, 0.05, 0.03, 0.37)),
    ("t19-short", "test", {
        "ticket_id": "TKT-2019", "subject": "cant login",
        "description": "nothing works",
    }, "account_access", (0.05, 0.20, 0.45, 0.05, 0.25)),
    # --- demo: 2 examples, shown but never scored ----------------------------------------------
    ("d01-ambiguous", "demo", {
        "ticket_id": "TKT-3001", "subject": "Can't update payment because locked out",
        "description": "I need to switch my card on file, but the account portal won't let "
        "me sign in at all.",
    }, None, (0.42, 0.05, 0.38, 0.03, 0.12)),
    ("d02-vague", "demo", {
        "ticket_id": "TKT-3002", "subject": "please help",
        "description": "it doesn't work",
    }, None, (0.15, 0.30, 0.12, 0.06, 0.37)),
]  # fmt: skip


def answers_for(probabilities: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the five options."""
    return {
        "category": ChoiceAnswer.from_probabilities(
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
