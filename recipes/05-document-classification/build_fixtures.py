"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 05.

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
OPTIONS = list(
    QUESTIONS["doc_type"].criteria
)  # invoice, meeting_note, policy, technical_guide, other

# (id, split, fields, gold label or None for demo, stored probabilities in OPTIONS order)
#
# Probabilities sum to 1. Most documents are clear and get a high probability on the right
# label. A few are deliberately borderline: a document plausibly fitting two of the five types
# (the build notes' hard case), written with a middling probability on the correct label and
# real mass on the type it is easiest to confuse with. Two are wrong on purpose and confident
# about it anyway: "t15-reset" (gold technical_guide, stored answer calls it policy at 0.62) and
# "v12-deploy" (gold policy, stored answer calls it technical_guide at 0.58), so the frozen
# threshold's selective risk is non-zero on both test and validation, not just a guarantee that
# happens to hold. "t19-attached" is a very short, genuinely unreadable document: its stored
# probabilities are nearly uniform, so it is correct but far too low-confidence to be reported.
ROWS = [
    # --- validation: 19 examples --------------------------------------------------------------
    ("v01-invoice", "validation", {"doc_id": "D101",
     "text": "Invoice #4417. Amount due: $1,250.00. For: 10 hours of consulting in September. "
     "Payment due within 30 days to account ending 2291."},
     "invoice", (0.88, 0.03, 0.03, 0.03, 0.03)),
    ("v02-invoice", "validation", {"doc_id": "D102",
     "text": "Invoice #882. Bill to: Harbor Supplies. 3 pallets of packing boxes at $85 each, "
     "subtotal $255.00, tax $20.40, total due $275.40 by November 15."},
     "invoice", (0.86, 0.04, 0.03, 0.03, 0.04)),
    ("v03-invoice", "validation", {"doc_id": "D103",
     "text": "Invoice #1190 for the June website maintenance retainer. Amount due $600.00. "
     "Please remit payment by the 10th; a $25 late fee applies after that date."},
     "invoice", (0.72, 0.05, 0.06, 0.05, 0.12)),
    ("v04-invoice-nowword", "validation", {"doc_id": "D104",
     "text": "Amount owed for May catering services: $940.00. Due upon receipt. "
     "Reference order CAT-558."},
     "invoice", (0.58, 0.04, 0.05, 0.04, 0.29)),
    ("v05-meeting", "validation", {"doc_id": "D105",
     "text": "Notes from the Oct 3 product sync: Maria will finalize the onboarding flow "
     "mockups by Friday. Dev agreed to cut the API freeze to Wednesday. Next sync is in two "
     "weeks."},
     "meeting_note", (0.05, 0.84, 0.06, 0.03, 0.02)),
    ("v06-meeting", "validation", {"doc_id": "D106",
     "text": "Minutes, weekly ops meeting, Sept 28. Attendees: Dana, Priya, Luis. Decided to "
     "move the Tuesday standup to 10am starting next week. Luis will update the calendar "
     "invite."},
     "meeting_note", (0.04, 0.82, 0.07, 0.03, 0.04)),
    ("v07-meeting-vs-policy", "validation", {"doc_id": "D107",
     "text": "At today's budget meeting, the team agreed that travel requests over $300 will "
     "go through Priya for sign-off starting this quarter. Minutes recorded by Dana."},
     "meeting_note", (0.03, 0.52, 0.38, 0.04, 0.03)),
    ("v08-meeting", "validation", {"doc_id": "D108",
     "text": "Standup notes, Aug 14: blocked on the staging database migration; Sam is pairing "
     "with ops this afternoon to unblock it. Carried over from yesterday."},
     "meeting_note", (0.03, 0.80, 0.05, 0.09, 0.03)),
    ("v09-policy", "validation", {"doc_id": "D109",
     "text": "Expense policy: all travel bookings must be made through the approved travel "
     "portal. Reimbursement requests submitted more than 60 days after travel will not be "
     "processed."},
     "policy", (0.03, 0.05, 0.86, 0.03, 0.03)),
    ("v10-policy", "validation", {"doc_id": "D110",
     "text": "Remote work policy: employees working remotely more than three days a week must "
     "have written manager approval on file with HR."},
     "policy", (0.03, 0.04, 0.84, 0.05, 0.04)),
    ("v11-policy-vs-meeting", "validation", {"doc_id": "D111",
     "text": "Effective immediately, as approved at the September leadership meeting, all "
     "expense reports over $500 require a second manager's signature before submission to "
     "Finance."},
     "policy", (0.03, 0.36, 0.56, 0.03, 0.02)),
    ("v12-deploy", "validation", {"doc_id": "D112",
     "text": "All production deployments must go through the automated release pipeline; "
     "manual deployment to production is not permitted under any circumstance."},
     "policy", (0.03, 0.03, 0.30, 0.58, 0.06)),
    ("v13-guide", "validation", {"doc_id": "D113",
     "text": "To reset the device: hold the power button for 10 seconds, release when the "
     "light blinks twice, then reconnect it to the app within 2 minutes."},
     "technical_guide", (0.03, 0.03, 0.04, 0.85, 0.05)),
    ("v14-guide", "validation", {"doc_id": "D114",
     "text": "Installing the CLI: download the archive, extract it to /usr/local/bin, run "
     "`cli --version` to confirm, then add the completion script to your shell profile."},
     "technical_guide", (0.03, 0.03, 0.04, 0.83, 0.07)),
    ("v15-guide", "validation", {"doc_id": "D115",
     "text": "Troubleshooting the printer jam: open the rear tray, pull the paper straight "
     "out (not at an angle), close the tray, then press the green button to resume."},
     "technical_guide", (0.03, 0.03, 0.05, 0.81, 0.08)),
    ("v16-guide-vs-policy", "validation", {"doc_id": "D116",
     "text": "Rotating the API key: generate a new key in the dashboard, update the key in "
     "every service's config, confirm each service logs a successful call with the new key, "
     "then revoke the old key."},
     "technical_guide", (0.03, 0.03, 0.33, 0.54, 0.07)),
    ("v17-other", "validation", {"doc_id": "D117",
     "text": "Thanks so much for the birthday card, it really made my week! Hope to see you "
     "at the reunion in June."},
     "other", (0.06, 0.05, 0.04, 0.05, 0.80)),
    ("v18-other", "validation", {"doc_id": "D118",
     "text": "Our new office chair line comes in six colors and ships free on orders over $75. "
     "Check out the catalog for the full range."},
     "other", (0.08, 0.06, 0.05, 0.05, 0.76)),
    ("v19-other-vs-invoice", "validation", {"doc_id": "D119",
     "text": "Thank you for your payment. We received $142.50 for order #58291 on October 2. "
     "Your account is now paid in full; no further action is needed."},
     "other", (0.34, 0.05, 0.04, 0.04, 0.53)),
    # --- test: 19 examples -----------------------------------------------------------------
    ("t01-invoice", "test", {"doc_id": "D201",
     "text": "Invoice #5502. Services: logo redesign package. Total due $480.00, net 15 from "
     "the invoice date."},
     "invoice", (0.87, 0.03, 0.03, 0.03, 0.04)),
    ("t02-invoice", "test", {"doc_id": "D202",
     "text": "Invoice #77. Bill to: Northside Dental. 2 boxes of gloves, 1 box of masks. Total "
     "due: $134.75, due by the end of the month."},
     "invoice", (0.85, 0.04, 0.03, 0.04, 0.04)),
    ("t03-invoice", "test", {"doc_id": "D203",
     "text": "Statement of amount due: $310.00 for July tutoring sessions. Please pay within "
     "10 business days of this notice."},
     "invoice", (0.68, 0.05, 0.06, 0.05, 0.16)),
    ("t04-invoice", "test", {"doc_id": "D204",
     "text": "Invoice #910. Web hosting renewal, 12 months. Total due $240.00. Due upon "
     "receipt."},
     "invoice", (0.86, 0.03, 0.04, 0.03, 0.04)),
    ("t05-meeting", "test", {"doc_id": "D205",
     "text": "Notes from the vendor call, Nov 2: the vendor confirmed the shipment will arrive "
     "a week late. Jordan will notify the warehouse team."},
     "meeting_note", (0.04, 0.83, 0.06, 0.03, 0.04)),
    ("t06-meeting", "test", {"doc_id": "D206",
     "text": "Minutes, design review, Oct 20. Attendees: Noor, Kai. The purple variant was "
     "rejected; Kai will prepare two new mockups for next week's review."},
     "meeting_note", (0.03, 0.81, 0.08, 0.04, 0.04)),
    ("t07-meeting-vs-guide", "test", {"doc_id": "D207",
     "text": "At the deployment retro, the team walked through the rollback steps that were "
     "used last night: stop the worker, restore the last snapshot, then restart the worker. "
     "Everyone agreed to document this properly later."},
     "meeting_note", (0.03, 0.50, 0.11, 0.33, 0.03)),
    ("t08-meeting", "test", {"doc_id": "D208",
     "text": "Notes, hiring committee, Sept 9. Panel agreed to move two candidates to the "
     "final round; Priya will schedule their onsite interviews this week."},
     "meeting_note", (0.04, 0.84, 0.06, 0.03, 0.03)),
    ("t09-policy", "test", {"doc_id": "D209",
     "text": "Data retention policy: customer support tickets are retained for three years "
     "and then deleted automatically. No exceptions may be granted without written approval "
     "from Legal."},
     "policy", (0.03, 0.04, 0.85, 0.04, 0.04)),
    ("t10-policy", "test", {"doc_id": "D210",
     "text": "Password policy: all employee accounts must use a passphrase of at least "
     "sixteen characters and must be rotated every 180 days."},
     "policy", (0.03, 0.04, 0.83, 0.06, 0.04)),
    ("t11-policy-vs-guide", "test", {"doc_id": "D211",
     "text": "Backups must be encrypted at rest and verified monthly by running the "
     "restore-test script against the previous month's backup; any failed verification must "
     "be reported to security within 24 hours."},
     "policy", (0.03, 0.04, 0.50, 0.40, 0.03)),
    ("t12-guide", "test", {"doc_id": "D212",
     "text": "Setting up the dev environment: clone the repo, run the setup script, copy "
     ".env.example to .env, then start the server with `make dev`."},
     "technical_guide", (0.03, 0.03, 0.04, 0.84, 0.06)),
    ("t13-guide", "test", {"doc_id": "D213",
     "text": "Migrating the database: take a backup first, run the migration script against "
     "staging, verify the row counts match, then run it against production during the "
     "maintenance window."},
     "technical_guide", (0.03, 0.03, 0.05, 0.82, 0.07)),
    ("t14-guide", "test", {"doc_id": "D214",
     "text": "Connecting the sensor: attach the cable to port 2, power on the hub, wait for "
     "the blue light, then pair it from the app's device list."},
     "technical_guide", (0.03, 0.03, 0.05, 0.80, 0.09)),
    ("t15-reset", "test", {"doc_id": "D215",
     "text": "Resetting a locked account: verify the requester's identity with two forms of "
     "ID, reset the password in the admin console, then require a new passphrase on next "
     "login."},
     "technical_guide", (0.03, 0.03, 0.62, 0.28, 0.04)),
    ("t16-other", "test", {"doc_id": "D216",
     "text": "Mix two cups of flour with a teaspoon of baking soda, fold in the blueberries, "
     "and bake at 375 degrees for twenty-five minutes."},
     "other", (0.07, 0.06, 0.05, 0.05, 0.77)),
    ("t17-other", "test", {"doc_id": "D217",
     "text": "Weather for Thursday: mostly cloudy, high near 61, light wind from the "
     "northwest in the afternoon."},
     "other", (0.07, 0.07, 0.06, 0.05, 0.75)),
    ("t18-other-vs-invoice", "test", {"doc_id": "D218",
     "text": "Estimated cost for the fence repair: $380, pending your approval. This is not a "
     "bill; we will invoice you only after the work is completed."},
     "other", (0.36, 0.04, 0.04, 0.04, 0.52)),
    ("t19-attached", "test", {"doc_id": "D219", "text": "See attached."},
     "other", (0.20, 0.20, 0.19, 0.19, 0.22)),
    # --- demo: 2 examples, shown but never scored ----------------------------------------------
    ("d01-meeting-vs-policy", "demo", {"doc_id": "D301",
     "text": "At Tuesday's staff meeting, Finance proposed that any expense report over $500 "
     "must have manager approval before submission. Starting next week, this applies to "
     "every department, and expense reports without the approval signature will be returned "
     "unprocessed."},
     None, (0.04, 0.40, 0.46, 0.06, 0.04)),
    ("d02-invoice-vs-other", "demo", {"doc_id": "D302",
     "text": "Thank you for your payment of $64.00 for invoice #312. This confirms the "
     "invoice is now paid in full."},
     None, (0.42, 0.03, 0.03, 0.04, 0.48)),
]  # fmt: skip


def answers_for(spec, provenance: Provenance):
    """{question name: answer} for one row: a single Choice answer over the five options."""
    return {
        "doc_type": ChoiceAnswer.from_probabilities(
            dict(zip(OPTIONS, spec, strict=True)), provenance
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
