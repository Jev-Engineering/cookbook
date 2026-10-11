"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 27.

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

# (id, split, fields, gold label or None for a demo example, (answer_choice, confidence))
#
# fields["request"] carries the prose a user sent plus, where the request supplies them, an
# "Arguments: k=v; k=v" trailer that helpers.extract_arguments parses -- never a hand-written
# dict here. The hard cases this recipe's use case names:
#   - "match a function, carry invalid arguments": v09-v11, t09-t11, demo-02 (one of each
#     violation kind -- missing required, wrong type, value outside the enumeration -- on each
#     split);
#   - "match nothing": v07, v08, t07, t08 (no_function);
#   - "ambiguous between two functions": v12, v13, t12, t13 (correct, but stored at low
#     confidence);
#   - "one wrong answer visible to the selector on validation": v14 (wrong, confidence 0.55 --
#     the pivot the frozen gate, 0.60, sits just above);
#   - "one confidently wrong selection above the gate on test": t14 (Jev names a real function
#     other than the gold one, confidently, and that wrong function's own schema happens to
#     accept the arguments this request supplies, so it is wrongly, confidently executed).
ROWS = [
    (
        "v01",
        "validation",
        {
            "request": (
                "Please send an email to the finance team about the delayed invoice.\n"
                "Arguments: to=finance@example.com; subject=Delayed invoice; "
                "body=The October invoice is running two days late.; priority=normal"
            )
        },
        "send_email",
        ("send_email", 0.85),
    ),
    (
        "v02",
        "validation",
        {
            "request": (
                "Please set up a meeting called 'Design Sync' with ana@example.com and "
                "ben@example.com for 30 minutes on 2026-11-02.\n"
                "Arguments: title=Design Sync; attendees=ana@example.com|ben@example.com; "
                "duration_minutes=30; date=2026-11-02"
            )
        },
        "schedule_meeting",
        ("schedule_meeting", 0.80),
    ),
    (
        "v03",
        "validation",
        {
            "request": (
                "File a ticket: the checkout page throws a 500 error for guest users.\n"
                "Arguments: title=Checkout 500 error for guests; priority=high; "
                "assignee=platform-team"
            )
        },
        "create_ticket",
        ("create_ticket", 0.75),
    ),
    (
        "v04",
        "validation",
        {
            "request": (
                "Remind me to call the landlord about the lease renewal on 2026-11-04.\n"
                "Arguments: message=Call the landlord about the lease renewal; "
                "remind_at=2026-11-04; channel=sms"
            )
        },
        "set_reminder",
        ("set_reminder", 0.90),
    ),
    (
        "v05",
        "validation",
        {
            "request": (
                "Update record REC-4471: set the owner field to mteo.\n"
                "Arguments: record_id=REC-4471; field=owner; value=mteo"
            )
        },
        "update_record",
        ("update_record", 0.65),
    ),
    (
        "v06",
        "validation",
        {
            "request": (
                "Look up contacts matching 'harbor logistics' in the directory, at most 3 "
                "results.\nArguments: query=harbor logistics; max_results=3"
            )
        },
        "lookup_contact",
        ("lookup_contact", 0.70),
    ),
    (
        "v07",
        "validation",
        {"request": "What's the weather like in Lisbon today?"},
        "no_function",
        ("no_function", 0.85),
    ),
    (
        "v08",
        "validation",
        {"request": "Tell me a short joke about a pigeon who delivers packages."},
        "no_function",
        ("no_function", 0.60),
    ),
    (
        "v09",
        "validation",
        {
            "request": (
                "Please email the vendor about the late shipment.\n"
                "Arguments: to=vendor@example.com; subject=Late shipment"
            )
        },
        "send_email",
        ("send_email", 0.80),
    ),
    (
        "v10",
        "validation",
        {
            "request": (
                "Schedule a meeting called 'Retro' with carla@example.com for sometime soon "
                "on 2026-11-06.\n"
                "Arguments: title=Retro; attendees=carla@example.com; "
                "duration_minutes=soon; date=2026-11-06"
            )
        },
        "schedule_meeting",
        ("schedule_meeting", 0.75),
    ),
    (
        "v11",
        "validation",
        {
            "request": (
                "File a ticket about the printer on the third floor; mark it urgent.\n"
                "Arguments: title=Third floor printer down; priority=urgent"
            )
        },
        "create_ticket",
        ("create_ticket", 0.70),
    ),
    (
        "v12",
        "validation",
        {
            "request": (
                "Make sure someone pings the on-call engineer at 9am tomorrow about the "
                "certificate renewal; it does not need to go on anyone's calendar, just a "
                "heads-up beforehand.\n"
                "Arguments: message=Certificate renewal heads-up; remind_at=2026-11-06; "
                "channel=email"
            )
        },
        "set_reminder",
        ("set_reminder", 0.30),
    ),
    (
        "v13",
        "validation",
        {
            "request": (
                "Mark the status as resolved for our billing incident and make sure it is "
                "tracked somewhere formally, since there is no existing record for it yet.\n"
                "Arguments: title=Billing incident resolved; priority=low"
            )
        },
        "create_ticket",
        ("create_ticket", 0.40),
    ),
    (
        "v14",
        "validation",
        {
            "request": (
                "Find me contact details for anyone named Priya in the directory.\n"
                "Arguments: query=Priya; max_results=5"
            )
        },
        "lookup_contact",
        ("send_email", 0.55),  # deliberately wrong: pivots the frozen gate at 0.60
    ),
    (
        "v15",
        "validation",
        {
            "request": (
                "Send an email to legal@example.com with subject 'NDA question' and body "
                "'Can we get the counterparty's signature by Friday?'\n"
                "Arguments: to=legal@example.com; subject=NDA question; "
                "body=Can we get the counterparty's signature by Friday?; priority=high"
            )
        },
        "send_email",
        ("send_email", 0.95),
    ),
    (
        "v16",
        "validation",
        {
            "request": (
                "Set up a 45 minute meeting titled 'Vendor review' with priya@example.com "
                "and tom@example.com on 2026-11-09.\n"
                "Arguments: title=Vendor review; attendees=priya@example.com|tom@example.com; "
                "duration_minutes=45; date=2026-11-09"
            )
        },
        "schedule_meeting",
        ("schedule_meeting", 0.65),
    ),
    (
        "v17",
        "validation",
        {
            "request": (
                "Remind me to submit the expense report on 2026-11-07.\n"
                "Arguments: message=Submit the expense report; remind_at=2026-11-07; "
                "channel=push"
            )
        },
        "set_reminder",
        ("set_reminder", 0.72),
    ),
    (
        "v18",
        "validation",
        {
            "request": (
                "File a ticket: the nightly backup job failed again overnight.\n"
                "Arguments: title=Nightly backup job failed; priority=critical"
            )
        },
        "create_ticket",
        ("create_ticket", 0.68),
    ),
    (
        "v19",
        "validation",
        {
            "request": (
                "Update record REC-9120: change the notes field to 'follow up next quarter'.\n"
                "Arguments: record_id=REC-9120; field=notes; value=follow up next quarter"
            )
        },
        "update_record",
        ("update_record", 0.62),
    ),
    (
        "t01",
        "test",
        {
            "request": (
                "Send an email to support@example.com, subject 'Refund status', body 'Could "
                "you confirm when the refund will post?'\n"
                "Arguments: to=support@example.com; subject=Refund status; "
                "body=Could you confirm when the refund will post?"
            )
        },
        "send_email",
        ("send_email", 0.80),
    ),
    (
        "t02",
        "test",
        {
            "request": (
                "Schedule a meeting called 'Launch readiness' with dao@example.com and "
                "fen@example.com for 90 minutes on 2026-11-12.\n"
                "Arguments: title=Launch readiness; "
                "attendees=dao@example.com|fen@example.com; duration_minutes=90; "
                "date=2026-11-12"
            )
        },
        "schedule_meeting",
        ("schedule_meeting", 0.85),
    ),
    (
        "t03",
        "test",
        {
            "request": (
                "File a ticket about the mobile app crashing on startup for some users.\n"
                "Arguments: title=Mobile app crash on startup; priority=critical; "
                "assignee=mobile-team"
            )
        },
        "create_ticket",
        ("create_ticket", 0.90),
    ),
    (
        "t04",
        "test",
        {
            "request": (
                "Remind me to renew the office parking permits on 2026-11-14.\n"
                "Arguments: message=Renew office parking permits; remind_at=2026-11-14; "
                "channel=email"
            )
        },
        "set_reminder",
        ("set_reminder", 0.75),
    ),
    (
        "t05",
        "test",
        {
            "request": (
                "Update record REC-3302: set the status field to inactive.\n"
                "Arguments: record_id=REC-3302; field=status; value=inactive"
            )
        },
        "update_record",
        ("update_record", 0.65),
    ),
    (
        "t06",
        "test",
        {
            "request": (
                "Search the contact directory for 'northwind logistics', up to 5 results.\n"
                "Arguments: query=northwind logistics; max_results=5"
            )
        },
        "lookup_contact",
        ("lookup_contact", 0.70),
    ),
    (
        "t07",
        "test",
        {"request": "What's a good name for a houseplant that keeps surviving neglect?"},
        "no_function",
        ("no_function", 0.80),
    ),
    (
        "t08",
        "test",
        {"request": "How many time zones does Russia span?"},
        "no_function",
        ("no_function", 0.65),
    ),
    (
        "t09",
        "test",
        {
            "request": (
                "Remind the team the contract renewal is due soon.\n"
                "Arguments: message=Contract renewal due soon"
            )
        },
        "set_reminder",
        ("set_reminder", 0.78),
    ),
    (
        "t10",
        "test",
        {
            "request": (
                "Update record REQ-882: set the owner field to jlee.\n"
                "Arguments: record_id=REQ-882; field=owner; value=jlee"
            )
        },
        "update_record",
        ("update_record", 0.72),
    ),
    (
        "t11",
        "test",
        {
            "request": (
                "Send an email to ops@example.com, subject 'Deploy window', body 'The window "
                "opens at 2am UTC.', and flag it urgent.\n"
                "Arguments: to=ops@example.com; subject=Deploy window; "
                "body=The window opens at 2am UTC.; priority=urgent"
            )
        },
        "send_email",
        ("send_email", 0.82),
    ),
    (
        "t12",
        "test",
        {
            "request": (
                "Flag for the support lead that the contract renewal is due Friday; a quick "
                "nudge beforehand is enough, nothing needs to be booked on their schedule.\n"
                "Arguments: message=Contract renewal due Friday; remind_at=2026-11-13; "
                "channel=push"
            )
        },
        "set_reminder",
        ("set_reminder", 0.35),
    ),
    (
        "t13",
        "test",
        {
            "request": (
                "Note that the inventory sync job keeps failing and get this properly logged "
                "so engineering can pick it up, since nothing is tracking it yet.\n"
                "Arguments: title=Inventory sync job failing; priority=high"
            )
        },
        "create_ticket",
        ("create_ticket", 0.42),
    ),
    (
        "t14",
        "test",
        {
            "request": (
                "I need Dana's contact details from the directory, and if you find them, "
                "forward a note to the support team so they have it on file.\n"
                "Arguments: query=Dana; to=support-team@example.com; "
                "subject=Dana contact details; "
                "body=Please add Dana's contact details once found."
            )
        },
        "lookup_contact",
        ("send_email", 0.85),  # confidently wrong: send_email's own schema accepts these
    ),
    (
        "t15",
        "test",
        {
            "request": (
                "Send an email to billing@example.com, subject 'Overdue balance', body "
                "'Please settle the balance by month end.'\n"
                "Arguments: to=billing@example.com; subject=Overdue balance; "
                "body=Please settle the balance by month end.; priority=high"
            )
        },
        "send_email",
        ("send_email", 0.92),
    ),
    (
        "t16",
        "test",
        {
            "request": (
                "Set up a 20 minute meeting called 'Stand-up' with ravi@example.com on "
                "2026-11-16.\n"
                "Arguments: title=Stand-up; attendees=ravi@example.com; "
                "duration_minutes=20; date=2026-11-16"
            )
        },
        "schedule_meeting",
        ("schedule_meeting", 0.68),
    ),
    (
        "t17",
        "test",
        {
            "request": (
                "Remind me to water the office plants on 2026-11-17.\n"
                "Arguments: message=Water the office plants; remind_at=2026-11-17; "
                "channel=sms"
            )
        },
        "set_reminder",
        ("set_reminder", 0.73),
    ),
    (
        "t18",
        "test",
        {
            "request": (
                "File a ticket about the shared printer jamming on the fifth floor.\n"
                "Arguments: title=Fifth floor printer jam; priority=low"
            )
        },
        "create_ticket",
        ("create_ticket", 0.66),
    ),
    (
        "t19",
        "test",
        {
            "request": (
                "Update record REC-5588: set the notes field to 'renewed through 2027'.\n"
                "Arguments: record_id=REC-5588; field=notes; value=renewed through 2027"
            )
        },
        "update_record",
        ("update_record", 0.63),
    ),
    (
        "demo-01",
        "demo",
        {
            "request": (
                "Please set up a meeting called 'Quarterly Planning' with ana@example.com "
                "and ben@example.com for 60 minutes on 2026-11-10.\n"
                "Arguments: title=Quarterly Planning; "
                "attendees=ana@example.com|ben@example.com; duration_minutes=60; "
                "date=2026-11-10"
            )
        },
        None,
        ("schedule_meeting", 0.85),
    ),
    (
        "demo-02",
        "demo",
        {
            "request": (
                "File a ticket about the broken login page.\nArguments: title=Broken login page"
            )
        },
        None,
        ("create_ticket", 0.80),
    ),
]


def probabilities_for(answer_choice: str, confidence: float, option_names: tuple) -> dict:
    """A probability distribution over ``option_names`` whose top option is ``answer_choice``
    at (as close as floating point allows) the published Choice confidence formula's
    ``confidence``, with the rest of the mass spread evenly over every other option."""
    n = len(option_names)
    p_max = confidence * (1 - 1 / n) + 1 / n
    remaining = (1 - p_max) / (n - 1)
    return {name: (p_max if name == answer_choice else remaining) for name in option_names}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, label, _spec in rows:
        order = helpers.option_order_for(ident)
        questions = helpers.build_questions(order)
        key = replay_key(helpers.build_state(fields), questions)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for ident, _split, fields, _label, spec in rows:
        order = helpers.option_order_for(ident)
        questions = helpers.build_questions(order)
        key = replay_key(helpers.build_state(fields), questions)
        answer_choice, confidence = spec
        probabilities = probabilities_for(answer_choice, confidence, helpers.OPTION_NAMES)
        answer = ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())
        responses[key] = DecisionResult({"function": answer}, "synthetic").to_dict()
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
