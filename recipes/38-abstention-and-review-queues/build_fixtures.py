"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 38.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic and deliberately imperfect: include some wrong answers and the
hard cases the use case names. See docs/fixtures.md and recipes/_template/build_fixtures.py.

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
OPTIONS = list(QUESTIONS["queue"].criteria)  # self_serve, tier1_support, tier2_engineering,
# insufficient_information

# (id, split, fields, gold label or None for demo, stored probabilities in OPTIONS order)
#
# Two hard-case pairs run through the fixture set twice, with different wording each time, the
# way recipe 4's did: an ambiguous self_serve/tier1_support ticket (v03/t03, and again as
# v19/t19 from the account-access side) and an ambiguous tier1_support/tier2_engineering ticket
# (v08/t08). t08's stored answer is wrong *and* confident, comfortably above the threshold this
# recipe freezes on validation, so test risk is non-zero rather than a guarantee that happens to
# hold by construction. t16 is wrong too, but at low confidence, so the threshold catches it and
# sends it to review instead. v18/t18 are right but deliberately low-confidence, so the gate
# sends a correct answer to review anyway -- the coverage this rule gives up even when it would
# have been right. Three insufficient_information tickets per split (vague, off-topic, mixing
# several unrelated requests) are the use case's named fallback; v12/t12 are stored at high
# confidence on purpose, to show that this option is never auto-routed no matter how sure Jev
# is. The replay keys come from the same build_state and build_questions the notebook uses, via
# helpers.py.
ROWS = [
    # --- validation: 20 examples ----------------------------------------------------------
    ("v01-ss-reset-password", "validation", {
        "ticket_id": "TKT-3001", "subject": "How do I reset my password?",
        "description": "I'm signed in on my laptop but forgot the password for my phone. Is "
        "there a help article for resetting it myself?",
    }, "self_serve", (0.88, 0.04, 0.04, 0.04)),
    ("v02-ss-billing-cycle", "validation", {
        "ticket_id": "TKT-3002", "subject": "When does my plan renew?",
        "description": "Does my monthly plan renew on the 1st of the month, or on the day I "
        "originally signed up?",
    }, "self_serve", (0.84, 0.05, 0.06, 0.05)),
    ("v03-ambiguous-ss-tier1", "validation", {
        "ticket_id": "TKT-3003", "subject": "Locked out, recovery email also gone",
        "description": "I lost access to the email address on file, so the password reset "
        "link has nowhere to send a code. I can't get back in on my own.",
    }, "tier1_support", (0.38, 0.42, 0.12, 0.08)),
    ("v04-tier1-add-teammate", "validation", {
        "ticket_id": "TKT-3004", "subject": "Add a teammate to our workspace",
        "description": "We'd like to give a new hire access to our team workspace under our "
        "current plan.",
    }, "tier1_support", (0.05, 0.84, 0.06, 0.05)),
    ("v05-tier1-refund-seats", "validation", {
        "ticket_id": "TKT-3005", "subject": "Refund for unused seats",
        "description": "We were charged for 10 seats this month but only use 8. Can you "
        "refund the difference?",
    }, "tier1_support", (0.05, 0.80, 0.08, 0.07)),
    ("v06-tier2-export-spins", "validation", {
        "ticket_id": "TKT-3006", "subject": "Export button does nothing",
        "description": "Every time I click export, the page just spins and nothing ever "
        "downloads.",
    }, "tier2_engineering", (0.04, 0.05, 0.86, 0.05)),
    ("v07-tier2-totals-mismatch", "validation", {
        "ticket_id": "TKT-3007", "subject": "Totals don't match between pages",
        "description": "The weekly total on the summary page doesn't match the same week's "
        "total on the detail page.",
    }, "tier2_engineering", (0.05, 0.06, 0.83, 0.06)),
    ("v08-ambiguous-tier1-tier2", "validation", {
        "ticket_id": "TKT-3008", "subject": "Dashboard stopped updating",
        "description": "I set a custom date filter last week and the dashboard hasn't "
        "refreshed since, even though I haven't touched the filter again.",
    }, "tier2_engineering", (0.05, 0.76, 0.13, 0.06)),
    ("v09-ss-permissions-explained", "validation", {
        "ticket_id": "TKT-3009", "subject": "What can viewers do versus editors?",
        "description": "Could you explain the difference between the viewer and editor roles "
        "on our workspace?",
    }, "self_serve", (0.82, 0.06, 0.07, 0.05)),
    ("v10-ss-invoice-pdf", "validation", {
        "ticket_id": "TKT-3010", "subject": "Where do I download my invoice?",
        "description": "Is there a page where I can download a PDF of last month's invoice "
        "myself?",
    }, "self_serve", (0.85, 0.05, 0.05, 0.05)),
    ("v11-insufficient-vague", "validation", {
        "ticket_id": "TKT-3011", "subject": "help",
        "description": "it's not working, please fix",
    }, "insufficient_information", (0.12, 0.15, 0.25, 0.48)),
    ("v12-insufficient-offtopic", "validation", {
        "ticket_id": "TKT-3012", "subject": "random message",
        "description": "Hey, just wanted to say I love the logo. Do you sell any merch?",
    }, "insufficient_information", (0.05, 0.05, 0.04, 0.86)),
    ("v13-insufficient-mixed", "validation", {
        "ticket_id": "TKT-3013", "subject": "A few things",
        "description": "My invoice looks off, the dashboard also crashed yesterday, and "
        "could someone add my coworker to the workspace too.",
    }, "insufficient_information", (0.20, 0.26, 0.24, 0.30)),
    ("v14-tier1-resend-receipt", "validation", {
        "ticket_id": "TKT-3014", "subject": "Need my April receipt resent",
        "description": "The invoice email bounced and I need someone to resend my April "
        "receipt directly to a different address.",
    }, "tier1_support", (0.08, 0.78, 0.07, 0.07)),
    ("v15-tier2-search-empty", "validation", {
        "ticket_id": "TKT-3015", "subject": "Search returns nothing",
        "description": "Searching for terms I know exist in my documents returns zero "
        "results every time.",
    }, "tier2_engineering", (0.05, 0.06, 0.84, 0.05)),
    ("v16-ss-trial-length", "validation", {
        "ticket_id": "TKT-3016", "subject": "How long is the free trial?",
        "description": "How many days does the free trial last, and is there a page that "
        "shows how many I have left?",
    }, "self_serve", (0.83, 0.06, 0.06, 0.05)),
    ("v17-tier1-add-billing-contact", "validation", {
        "ticket_id": "TKT-3017", "subject": "Add a second billing contact",
        "description": "We'd like another person on our team to also receive our invoices "
        "by email.",
    }, "tier1_support", (0.06, 0.81, 0.07, 0.06)),
    ("v18-tier1-vague-refund-lowconf", "validation", {
        "ticket_id": "TKT-3018", "subject": "Refund?",
        "description": "want my money back",
    }, "tier1_support", (0.18, 0.34, 0.20, 0.28)),
    ("v19-ambiguous-ss-tier1-device", "validation", {
        "ticket_id": "TKT-3019", "subject": "New phone never gets the code",
        "description": "I'm trying to sign in on a new phone and the code never arrives, "
        "though I still have access on my laptop right now.",
    }, "self_serve", (0.46, 0.34, 0.10, 0.10)),
    ("v20-tier2-crash-on-open", "validation", {
        "ticket_id": "TKT-3020", "subject": "Settings page crashes",
        "description": "The app crashes immediately every time I try to open the settings "
        "page.",
    }, "tier2_engineering", (0.04, 0.05, 0.87, 0.04)),
    # --- test: 20 examples -------------------------------------------------------------------
    ("t01-ss-reset-password", "test", {
        "ticket_id": "TKT-4001", "subject": "Reset password, have email access",
        "description": "I still have access to my email and would like to reset my password "
        "myself if there's a self-serve way.",
    }, "self_serve", (0.86, 0.05, 0.05, 0.04)),
    ("t02-ss-plan-limits", "test", {
        "ticket_id": "TKT-4002", "subject": "What happens past my usage limit?",
        "description": "What happens to my data if I go over my plan's monthly usage limit?",
    }, "self_serve", (0.83, 0.06, 0.06, 0.05)),
    ("t03-ambiguous-ss-tier1", "test", {
        "ticket_id": "TKT-4003", "subject": "Locked out, recovery email also gone",
        "description": "I'm locked out and the recovery email on file is also an address I "
        "can no longer reach, so the reset link has nowhere to go.",
    }, "tier1_support", (0.37, 0.43, 0.11, 0.09)),
    ("t04-tier1-add-admin", "test", {
        "ticket_id": "TKT-4004", "subject": "Add a second admin",
        "description": "We need a second person added as an admin on our team account.",
    }, "tier1_support", (0.05, 0.85, 0.05, 0.05)),
    ("t05-tier1-refund-duplicate-seat", "test", {
        "ticket_id": "TKT-4005", "subject": "Charged for a seat twice",
        "description": "It looks like we were billed for the same extra seat twice this "
        "month. Can that be refunded?",
    }, "tier1_support", (0.06, 0.81, 0.07, 0.06)),
    ("t06-tier2-export-blank-pdf", "test", {
        "ticket_id": "TKT-4006", "subject": "Export downloads but PDF is blank",
        "description": "The export finishes now, but the PDF it produces is completely "
        "blank every time.",
    }, "tier2_engineering", (0.04, 0.05, 0.87, 0.04)),
    ("t07-tier2-totals-mismatch", "test", {
        "ticket_id": "TKT-4007", "subject": "Numbers don't match between pages",
        "description": "The total on the summary page doesn't match the total on the detail "
        "page for the same report.",
    }, "tier2_engineering", (0.05, 0.06, 0.84, 0.05)),
    ("t08-ambiguous-tier1-tier2", "test", {
        "ticket_id": "TKT-4008", "subject": "Dashboard stopped updating",
        "description": "I changed a date filter a few days ago and the dashboard hasn't "
        "refreshed since, even though I haven't touched anything else.",
    }, "tier2_engineering", (0.05, 0.82, 0.07, 0.06)),
    ("t09-ss-saved-views", "test", {
        "ticket_id": "TKT-4009", "subject": "How do saved views work?",
        "description": "Is there a help article explaining how saved views work and how to "
        "share one with a teammate?",
    }, "self_serve", (0.82, 0.07, 0.06, 0.05)),
    ("t10-ss-export-csv-howto", "test", {
        "ticket_id": "TKT-4010", "subject": "Where to export data as CSV?",
        "description": "Is there a self-serve way to export my data as CSV instead of PDF?",
    }, "self_serve", (0.84, 0.05, 0.06, 0.05)),
    ("t11-insufficient-vague", "test", {
        "ticket_id": "TKT-4011", "subject": "problem",
        "description": "something is wrong, please help",
    }, "insufficient_information", (0.13, 0.16, 0.26, 0.45)),
    ("t12-insufficient-offtopic", "test", {
        "ticket_id": "TKT-4012", "subject": "quick question",
        "description": "Are you hiring? I really like your newsletter too.",
    }, "insufficient_information", (0.04, 0.05, 0.05, 0.86)),
    ("t13-insufficient-mixed", "test", {
        "ticket_id": "TKT-4013", "subject": "A few things",
        "description": "My invoice looks wrong, the search is also broken, and could you add "
        "a way to sort by date too.",
    }, "insufficient_information", (0.22, 0.24, 0.26, 0.28)),
    ("t14-tier1-resend-receipt", "test", {
        "ticket_id": "TKT-4014", "subject": "Need an old receipt resent",
        "description": "My receipt email bounced and I need last quarter's receipt resent "
        "to a different address.",
    }, "tier1_support", (0.07, 0.79, 0.07, 0.07)),
    ("t15-tier2-search-wrong-workspace", "test", {
        "ticket_id": "TKT-4015", "subject": "Search returns the wrong workspace's results",
        "description": "Search results are coming from a workspace I don't even belong to, "
        "not the one I'm signed into.",
    }, "tier2_engineering", (0.05, 0.06, 0.85, 0.04)),
    ("t16-ss-trial-length-lowconf-wrong", "test", {
        "ticket_id": "TKT-4016", "subject": "How long is the free trial?",
        "description": "How many trial days do I have left, and where would I see that "
        "myself?",
    }, "self_serve", (0.24, 0.27, 0.26, 0.23)),
    ("t17-tier1-change-billing-contact", "test", {
        "ticket_id": "TKT-4017", "subject": "Change who receives our invoices",
        "description": "We'd like to change which person on our team receives our monthly "
        "invoices.",
    }, "tier1_support", (0.06, 0.82, 0.06, 0.06)),
    ("t18-tier1-vague-refund-lowconf", "test", {
        "ticket_id": "TKT-4018", "subject": "Money back?",
        "description": "give me my money back",
    }, "tier1_support", (0.17, 0.33, 0.21, 0.29)),
    ("t19-ambiguous-ss-tier1-device", "test", {
        "ticket_id": "TKT-4019", "subject": "New laptop never gets the code",
        "description": "Signing in on a new laptop, the code never arrives, though I'm still "
        "signed in on my phone right now.",
    }, "self_serve", (0.45, 0.35, 0.10, 0.10)),
    ("t20-tier2-crash-on-open", "test", {
        "ticket_id": "TKT-4020", "subject": "Settings page crashes",
        "description": "The settings page crashes every single time I try to open it.",
    }, "tier2_engineering", (0.04, 0.05, 0.88, 0.03)),
    # --- demo: 2 examples, shown but never scored -------------------------------------------
    ("d01-ambiguous-ss-tier1", "demo", {
        "ticket_id": "TKT-5001", "subject": "Can't sign back in after changing email",
        "description": "I changed my email provider and now the password reset link goes to "
        "an inbox I can no longer open.",
    }, None, (0.40, 0.44, 0.09, 0.07)),
    ("d02-insufficient-vague", "demo", {
        "ticket_id": "TKT-5002", "subject": "please help",
        "description": "it doesn't work",
    }, None, (0.14, 0.18, 0.26, 0.42)),
]  # fmt: skip


def answers_for(probabilities: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the four options."""
    return {
        "queue": ChoiceAnswer.from_probabilities(
            dict(zip(OPTIONS, probabilities, strict=True)), provenance
        )
    }


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
        raise SystemExit("TODO: add examples to ROWS in build_fixtures.py")
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
