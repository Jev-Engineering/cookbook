"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 13.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect in several different ways, on purpose. One wrong answer is in
``validation`` itself (``v06-sympathetic-wrong``): without it, every real-candidate
``validation`` answer would be correct and ``select_confidence_threshold`` could only return the
lowest observed confidence, whatever the target accuracy -- the gate would never actually be
chosen by anything. The other three deliberate errors are in ``test``, each wrong in a different
way: one candidate is answered confidently (above the frozen threshold), so the confidence gate
lets a wrong rewrite through (``t07-sympathetic-wrong``); one is answered
``no_suitable_rewrite`` -- wrongly -- at a confidence (0.2267) *below* the frozen gate, which
the rule never checks at all because ``no_suitable_rewrite`` bypasses the gate entirely
(``t12-courtesy-credit-wrong``): this is also the one row where ``evaluate_outcomes`` and
``evaluate_selective`` genuinely disagree, since ``evaluate_selective`` would exclude a
confidence this low as unanswered while the rule itself still returns it as a final
``kept_original`` result (see the notebook's "Evaluation" section); a third is wrong but not
confident, so it is sent to review instead of being reported (``t19-setup-fee-wrong``). The hard
cases this use case calls for are included: candidates that change
the original sentence's meaning, candidates that miss the requested tone, candidates that do
both, and several items where no candidate is good enough and the gold label is
``no_suitable_rewrite``. The replay keys come from the same ``build_state`` and
``build_questions`` the notebook uses, via ``helpers.py``.

The three candidate identifiers (``candidate_1``, ``candidate_2``, ``candidate_3``) are fixed
positions Python assigns; which position holds the correct rewrite (when one exists) is varied
across the rows below on purpose, so that the fixture set does not quietly reward whichever
position a biased reader (or a model with S07's documented lean toward the first option) always
picks.

Generating inputs and labels is kept separate from generating responses, on purpose (the pattern
``recipes/_template/build_fixtures.py`` sets): once responses.json holds even one recorded
answer (provenance "recorded", captured from a real Jev call), running this script again must
not silently replace it with a synthetic probability. inputs.jsonl and labels.jsonl are always
rewritten from ROWS, because neither ever holds a model's answer; responses.json is rewritten
only when it does not yet exist, holds only synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
OPTIONS = list(
    QUESTIONS["rewrite"].criteria
)  # candidate_1, candidate_2, candidate_3, no_suitable_rewrite


def dist(**given: float) -> dict[str, float]:
    """A full probability mapping over ``OPTIONS``: ``given`` names the option(s) that carry
    real mass; every other option shares the remainder evenly. Keeps each row below readable as
    "the one or two options that matter", rather than four hand-typed numbers."""
    missing = [o for o in OPTIONS if o not in given]
    remainder = 1.0 - sum(given.values())
    share = remainder / len(missing)
    result = {o: share for o in missing}
    result.update(given)
    return result


def _fields(item_id: str, original: str, tone: str, candidates: tuple[str, str, str]) -> dict:
    return {
        "item_id": item_id,
        "original": original,
        "requested_tone": tone,
        "candidates": candidates,
    }


C1, C2, C3, NSR = "candidate_1", "candidate_2", "candidate_3", "no_suitable_rewrite"

# (id, split, item_id, original, tone, (candidate_1, candidate_2, candidate_3), gold label or
#  None for demo, stored probabilities)
ROWS = [
    # --- validation: 19 examples, one of them wrong on purpose ------------------------------
    ("v01-shipping-delay", "validation", "R1001",
     "We can't ship your order before Friday.", "apologetic",
     ("I'm sorry, but we won't be able to ship your order until Friday.",
      "We can't ship your order before Friday, so we've cancelled it.",
      "Your order won't ship before Friday. Deal with it."),
     C1, dist(candidate_1=0.85)),
    ("v02-contract-request", "validation", "R1002",
     "Please send the updated contract by end of day.", "friendly",
     ("You are required to submit the updated contract by end of day.",
      "Could you send over the updated contract by end of day? Thanks so much!",
      "Please send the updated invoice by end of day."),
     C2, dist(candidate_2=0.84)),
    ("v03-server-maintenance", "validation", "R1003",
     "The server will be down for maintenance tonight.", "reassuring",
     ("The server will be down for maintenance all week.",
      "Warning: the server is going down tonight and may not come back up.",
      "Just a heads-up: the server will be briefly down for routine maintenance tonight, and "
      "everything will be back to normal after."),
     C3, dist(candidate_3=0.83)),
    ("v04-price-increase", "validation", "R1004",
     "We increased the subscription price by 10%.", "diplomatic",
     ("We've made a 10% adjustment to the subscription price to keep investing in the service "
      "you rely on.",
      "We raised the price 10%. That's final.",
      "We increased the subscription price by 25%."),
     C1, dist(candidate_1=0.80)),
    ("v05-report-urgent", "validation", "R1005",
     "I need the report before the meeting starts.", "urgent",
     ("Whenever you get a chance, maybe send the report over before the meeting?",
      "I need the report in hand before the meeting starts -- please send it right away.",
      "I need the report sometime after the meeting ends."),
     C2, dist(candidate_2=0.82)),
    # Gold is candidate_3 (the only one that is both correctly stated and actually warm), but
    # the stored answer names candidate_1 instead -- correct meaning, flatter tone -- at
    # confidence 0.2667 (top probability 0.45). That is the highest confidence among
    # validation's wrong real-candidate answers (it is the only one), which is exactly why it
    # sets the bar: a plausible wrong answer deliberately placed in validation itself (see the
    # module docstring: this is the error that gives select_confidence_threshold something real
    # to cut on, instead of returning the lowest observed confidence for any target accuracy).
    ("v06-sympathetic-wrong", "validation", "R1006",
     "We can't approve the refund as requested.", "sympathetic",
     ("We're unable to approve the refund as requested.",
      "We've approved a partial refund instead of the full amount requested.",
      "I know this isn't the answer you were hoping for, and I'm sorry -- we're not able to "
      "approve the refund as requested."),
     C3, dist(candidate_1=0.45, candidate_3=0.30)),
    ("v07-office-closed", "validation", "R1007",
     "Our office will be closed next Monday for the holiday.", "friendly",
     ("Just a friendly reminder that our office will be closed next Monday for the holiday -- "
      "enjoy the day off!",
      "Our office will be closed next Monday and Tuesday for the holiday.",
      "Be advised that the office shall remain closed on the holiday observed next Monday."),
     C1, dist(candidate_1=0.82)),
    ("v08-roadmap", "validation", "R1008",
     "The feature you requested isn't on our roadmap right now.", "encouraging",
     ("The feature you requested is already on our roadmap for next quarter.",
      "That feature isn't on our roadmap. It probably never will be.",
      "We've decided not to support that kind of request going forward."),
     NSR, dist(no_suitable_rewrite=0.81)),
    ("v09-recurring-charge", "validation", "R1009",
     "Your account will be charged again next month.", "reassuring",
     ("Your account will be charged again next month. No further details are available.",
      "Your account will not be charged again next month.",
      "You will keep being charged every month indefinitely unless you cancel now."),
     NSR, dist(no_suitable_rewrite=0.78)),
    ("v10-export-bug", "validation", "R1010",
     "We found a bug in the export feature.", "direct",
     ("It looks like there might possibly be a small issue with exporting, we think.",
      "We found a bug in the import feature.",
      "We found a bug in the export feature."),
     C3, dist(candidate_3=0.85)),
    ("v11-proposal-review", "validation", "R1011",
     "Can you review the proposal before Thursday?", "formal",
     ("Hey, can you take a look at the proposal before Thursday?",
      "Would you be able to review the proposal prior to Thursday?",
      "Can you review the proposal after Thursday?"),
     C2, dist(candidate_2=0.87)),
    ("v12-trial-extension", "validation", "R1012",
     "We can extend your trial by one week.", "enthusiastic",
     ("We can extend your trial by one month.",
      "Your trial may be extended by one week upon request.",
      "We're ending trial extensions altogether starting this week."),
     NSR, dist(no_suitable_rewrite=0.80)),
    ("v13-weather-delay", "validation", "R1013",
     "The shipment was delayed due to weather.", "apologetic",
     ("The shipment was delayed due to weather conditions beyond our control.",
      "The shipment was delayed due to a warehouse error.",
      "Shipments are often delayed and there's nothing we can do about it."),
     NSR, dist(no_suitable_rewrite=0.75)),
    ("v14-discount-match", "validation", "R1014",
     "We can't match the discount you saw elsewhere.", "diplomatic",
     ("We can match the discount you saw elsewhere.",
      "We don't match competitor discounts. Ever.",
      "That discount doesn't exist and you must be mistaken."),
     NSR, dist(no_suitable_rewrite=0.78)),
    ("v15-meeting-moved", "validation", "R1015",
     "The meeting has been moved to 3pm.", "friendly",
     ("The meeting has been moved to 4pm.",
      "Meeting relocated. New time: 1500 hours.",
      "The meeting that was scheduled is cancelled."),
     NSR, dist(no_suitable_rewrite=0.72)),
    ("v16-testing-day", "validation", "R1016",
     "We need one more day to finish testing.", "confident",
     ("We need one more week to finish testing.",
      "We might need one more day, we're not totally sure yet, sorry.",
      "Testing is basically done, just a formality left."),
     NSR, dist(no_suitable_rewrite=0.76)),
    # Two candidates both keep the meaning (missing the conference); the gold label is
    # candidate_2 because it is the one that actually reads as warm, not merely neutral.
    # Correct, but at a lower confidence than the clear cases above.
    ("v17-conference-miss", "validation", "R1017",
     "We won't be able to attend the conference this year.", "warm",
     ("We will not be attending the conference this year.",
      "We're so sorry to miss the conference this year -- we'll really miss catching up with "
      "everyone!",
      "We will be attending the conference this year after all."),
     C2, dist(candidate_2=0.44, candidate_1=0.33)),
    # candidate_1 keeps the meaning but reads firm rather than calm; candidate_3 is the
    # genuinely calm one. Correct, but at a lower confidence.
    ("v18-policy-effective", "validation", "R1018",
     "The new policy takes effect immediately.", "calm",
     ("The new policy takes effect immediately, so please comply without delay.",
      "The new policy takes effect next month.",
      "Just to let you know, the new policy is now in effect -- nothing urgent to do right "
      "away, just keep it in mind going forward."),
     C3, dist(candidate_3=0.40, candidate_1=0.34)),
    # candidate_1 and candidate_2 both keep the meaning and are both reasonably polite; the
    # gold label is candidate_1 for being the warmer, more clearly "firm but polite" phrasing.
    # Correct, but at a lower confidence.
    ("v19-admin-access", "validation", "R1019",
     "We can't give you admin access to that system.", "firm but polite",
     ("I'm afraid we're not able to grant admin access to that system.",
      "We can't give you admin access. That's the policy.",
      "We can give you limited access to that system, just not admin."),
     C1, dist(candidate_1=0.46, candidate_2=0.30)),
    # --- test: 19 examples, three of them wrong on purpose -----------------------------------
    ("t01-shipping-refund", "test", "R2001",
     "We're not able to refund the shipping cost.", "polite",
     ("I'm sorry, but we're not able to refund the shipping cost.",
      "We're able to refund the shipping cost in full.",
      "No refunds on shipping. Next question."),
     C1, dist(candidate_1=0.86)),
    ("t02-payment-failed", "test", "R2002",
     "Your payment failed to process.", "reassuring",
     ("Your payment failed to process. Try again or contact support.",
      "It looks like your payment didn't go through -- no worries, this happens sometimes. "
      "Just try again whenever you're ready.",
      "Your payment processed successfully."),
     C2, dist(candidate_2=0.89)),
    ("t03-free-tier-ends", "test", "R2003",
     "We're discontinuing the free tier next quarter.", "diplomatic",
     ("We're discontinuing the paid tier next quarter.",
      "The free tier is going away next quarter. Upgrade or lose access.",
      "Starting next quarter, we'll be retiring the free tier so we can focus on making the "
      "paid plans even better for everyone."),
     C3, dist(candidate_3=0.83)),
    ("t04-return-window", "test", "R2004",
     "We can't process returns after 30 days.", "firm",
     ("Returns are not accepted after 30 days -- this policy applies without exception.",
      "Aw shucks, we usually can't take returns after 30 days, sorry about that!",
      "We can't process returns after 60 days."),
     C1, dist(candidate_1=0.82)),
    # candidate_1 keeps the meaning but reads flatter than friendly; candidate_2 is the
    # genuinely friendly one. Correct, but at a lower confidence.
    ("t05-resend-form", "test", "R2005",
     "We need you to resend the signed form.", "friendly",
     ("Please resend the signed form at your convenience.",
      "Would you mind resending the signed form whenever you get a chance? Thanks a bunch!",
      "We need you to sign and return a new form, not resend the old one."),
     C2, dist(candidate_2=0.44, candidate_1=0.34)),
    ("t06-event-postponed", "test", "R2006",
     "The event has been postponed to next week.", "enthusiastic",
     ("The event has been cancelled.",
      "Event postponed. New date: next week.",
      "Exciting update -- the event is now happening next week instead, so mark your "
      "calendars, we can't wait to see you there!"),
     C3, dist(candidate_3=0.84)),
    # Gold is candidate_3 (the genuinely sympathetic rewrite), but the stored answer names
    # candidate_1 instead -- correct meaning, flatter tone -- at confidence 0.4667 (top
    # probability 0.60), comfortably above the frozen 0.28 gate: a real, wrong candidate the
    # confidence gate lets straight through.
    ("t07-sympathetic-wrong", "test", "R2007",
     "We can't waive the late fee this time.", "sympathetic",
     ("We're not able to waive the late fee this time.",
      "We've decided to waive the late fee this time.",
      "I really wish I had better news -- we're not able to waive the late fee this time, but "
      "I understand that's frustrating."),
     C3, dist(candidate_1=0.60, candidate_3=0.25)),
    ("t08-lost-submission", "test", "R2008",
     "We lost your original submission.", "apologetic",
     ("Your original submission was lost. Please resubmit.",
      "I'm so sorry -- we lost your original submission. Could you please resend it when you "
      "have a moment?",
      "We found your original submission after all."),
     C2, dist(candidate_2=0.80)),
    ("t09-warranty-damage", "test", "R2009",
     "The warranty does not cover accidental damage.", "direct",
     ("The warranty does not cover accidental damage.",
      "Unfortunately, as much as we wish it were otherwise, the warranty sadly does not extend "
      "to cover accidental damage of any kind.",
      "The warranty covers accidental damage up to a limit."),
     C1, dist(candidate_1=0.77)),
    ("t10-approval-urgent", "test", "R2010",
     "We need your approval before we can proceed.", "urgent",
     ("We need your approval before we can close the project.",
      "Whenever is convenient, we'd love your approval to proceed, no rush at all.",
      "We can't move forward without your approval -- please send it as soon as you can."),
     C3, dist(candidate_3=0.83)),
    ("t11-pricing-disclosure", "test", "R2011",
     "We can't disclose other customers' pricing.", "diplomatic",
     ("We can disclose other customers' pricing on request.",
      "We never share pricing. Don't ask again.",
      "No one is allowed to know anyone's pricing, including yours."),
     NSR, dist(no_suitable_rewrite=0.79)),
    # Gold is candidate_2 (a genuinely warm, correct rewrite existed), but the stored answer
    # names no_suitable_rewrite instead, at confidence 0.2267 -- *below* the frozen 0.28 gate.
    # no_suitable_rewrite is never run past the confidence gate (it has none), so this wrong
    # answer is still delivered as a final "keep the original" result, not caught by any
    # threshold, even though its own confidence is low: this is the row that makes
    # evaluate_outcomes and evaluate_selective genuinely disagree (see "Python's part" and
    # "Evaluation" below), because evaluate_selective would have excluded it as unanswered.
    ("t12-courtesy-credit-wrong", "test", "R2012",
     "We can give you a one-time courtesy credit.", "warm",
     ("A one-time courtesy credit can be issued.",
      "We'd love to give you a one-time courtesy credit as a thank-you for your patience!",
      "We can give you a recurring monthly credit."),
     C2, dist(no_suitable_rewrite=0.42, candidate_2=0.30)),
    ("t13-deleted-file", "test", "R2013",
     "We can't restore the deleted file.", "sympathetic",
     ("I'm really sorry, but we're not able to restore the deleted file.",
      "We can restore the deleted file from a backup.",
      "Deleted files can't be restored. That's final."),
     C1, dist(candidate_1=0.88)),
    # candidate_3 keeps the meaning but reads firmer than calm; candidate_1 is the genuinely
    # calm one. Correct, but at confidence 0.1467 (top probability 0.36), below the 0.28 gate,
    # so the rule sends this one to review instead of reporting it.
    ("t14-account-paused", "test", "R2014",
     "We need to pause your account during the investigation.", "calm",
     ("Just so you know, we'll need to pause your account for a short time while we look into "
      "this -- nothing to worry about on your end.",
      "We need to close your account permanently during the investigation.",
      "Your account will be paused during the investigation, effective immediately."),
     C1, dist(candidate_1=0.36, candidate_3=0.32)),
    ("t15-no-more-extensions", "test", "R2015",
     "We can't extend the deadline again.", "firm but polite",
     ("We can extend the deadline one more time.",
      "No more extensions. End of discussion.",
      "Deadlines don't really matter that much anyway."),
     NSR, dist(no_suitable_rewrite=0.79)),
    ("t16-weekday-support", "test", "R2016",
     "Support is only available on weekdays.", "friendly",
     ("Support is available every day including weekends.",
      "Support: weekdays only. No exceptions.",
      "We don't really do support most days, sorry."),
     NSR, dist(no_suitable_rewrite=0.74)),
    ("t17-price-all-customers", "test", "R2017",
     "The price increase applies to all existing customers.", "diplomatic",
     ("The price increase applies only to new customers.",
      "Everyone's price is going up. No exceptions, no complaints.",
      "Existing customers are being phased out entirely."),
     NSR, dist(no_suitable_rewrite=0.81)),
    ("t18-delivery-guarantee", "test", "R2018",
     "We can't guarantee same-day delivery anymore.", "reassuring",
     ("We can now guarantee same-day delivery for everyone.",
      "Same-day delivery is no longer guaranteed. Plan accordingly.",
      "Delivery times are basically unpredictable now and we can't promise anything."),
     NSR, dist(no_suitable_rewrite=0.70)),
    # Gold is no_suitable_rewrite: all three candidates are flawed (candidate_3 quietly adds an
    # unstated "first month only" restriction, a meaning change dressed up in an enthusiastic,
    # tempting tone). The stored answer names candidate_3 instead, but only at confidence 0.1067
    # (top probability 0.33), below the 0.28 gate, so this one is caught and sent to review
    # rather than reported.
    ("t19-setup-fee-wrong", "test", "R2019",
     "We can waive the setup fee for annual plans.", "enthusiastic",
     ("We can waive the setup fee for monthly plans.",
      "Setup fee waived for annual plans. Noted.",
      "Great news -- we're waiving the setup fee, but only for the first month of annual "
      "plans."),
     NSR, dist(candidate_3=0.33, no_suitable_rewrite=0.28)),
    # --- demo: 2 examples, shown but never scored ---------------------------------------------
    ("d01-renewal-date", "demo", "R3001",
     "We're moving your renewal date up by two weeks.", "friendly",
     ("Your renewal date has been moved up by two weeks.",
      "Quick heads-up -- we've shifted your renewal date up by two weeks, just wanted you to "
      "know!",
      "We're moving your renewal date back by two weeks."),
     None, dist(candidate_2=0.42, candidate_1=0.35)),
    ("d02-custom-integrations", "demo", "R3002",
     "We don't support custom integrations at this time.", "encouraging",
     ("We fully support custom integrations starting today.",
      "No custom integrations. Not now, not planned.",
      "Honestly, custom integrations are unlikely to ever happen."),
     None, dist(no_suitable_rewrite=0.58, candidate_1=0.15)),
]  # fmt: skip


def answers_for(spec: dict[str, float], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the four options."""
    return {"rewrite": ChoiceAnswer.from_probabilities(spec, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, item_id, original, tone, candidates, label, _spec in rows:
        fields = _fields(item_id, original, tone, candidates)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, item_id, original, tone, candidates, _label, spec in rows:
        fields = _fields(item_id, original, tone, candidates)
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
