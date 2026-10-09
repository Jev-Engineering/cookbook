"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 10.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as a probability, not produced by a model) and
deliberately imperfect. The hard cases the issue names are included and tagged in their id: a
response that is clearly relevant (``-relevant``), one that is clearly off-topic (``-offtopic``,
including a generic boilerplate reply, a reply that only repeats the question, one that deflects
without answering, and one about an unrelated subject), and three harder shapes.

``-hard-wrong`` is a fluent, well-formed response that confidently answers a *different* question
from the one asked. Both splits carry one, stored at a noul (0.78 on `validation`, 0.83 on
`test`) and a certainty (0.56, 0.66) well clear of the gate the notebook freezes (0.30): the
certainty gate measures how far a probability leans, not whether it leans the right way, and a
response engineered to read as fluent and on-topic leans hard. Both are deliberately stored above
the gate on purpose -- the lesson is that certainty cannot catch this shape of error, on either
split, not that it happens to catch it on one and miss it on the other.

``-partial`` (three per split, stored within 0.08 of an even split, 0.46-0.58, gold labels not
all one way -- two true, one false, in no fixed order relative to noul) is the opposite shape: a
response whose probability alone does not reliably say which way it should go, which is exactly
what the certainty gate is for and exactly what it catches here, alongside ``-error`` below.

One pair per split (``-error``, 0.60 on `validation`, 0.61 on `test`, gold false) is a genuine
raw-decision mistake sitting just past the business threshold (0.55): close enough to an even
split that the certainty gate catches it too, but on the wrong side of 0.55, unlike the
``-partial`` pairs. Excluding it from the decisions `check_relevance` acts on alone is what lets
the frozen gate raise accuracy on the answered subset above the ungated rule's own accuracy on
both splits -- the gate is shown earning its coverage/accuracy trade-off, not asserted to.

Finally, one ``-moderate`` pair of each gold value per split (0.65 true, 0.35 false) is confident
enough to clear the gate (certainty 0.30, exactly the frozen cut-off) while sitting close enough
to the business threshold that moving it changes their outcome: without these two pairs, every
pair that clears the gate would sit at or past 0.78, so the business threshold, frozen separately
at 0.55, would never actually decide anything a looser or tighter gate could not already decide on
its own. The replay keys come from the same ``build_state`` and ``build_questions`` the notebook
uses, via ``helpers.py``.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# (id, split, pair_id, question, response, gold label (bool) or None for demo, stored noul
# probability that the response addresses the question)
ROWS = [
    # --- validation: 25 pairs ---------------------------------------------------------------
    ("v01-relevant", "validation", "AR1001",
     "How long does standard shipping take?",
     "Standard shipping takes 5 to 7 business days from the date your order ships.",
     True, 0.93),
    ("v02-relevant", "validation", "AR1002",
     "How do I reset my account password?",
     "Go to the sign-in page, select 'Forgot password', and we'll email you a link to set a "
     "new one.",
     True, 0.90),
    ("v03-relevant", "validation", "AR1003",
     "What is your return policy for opened items?",
     "Opened items can be returned within 30 days of delivery as long as they are undamaged; "
     "we refund the purchase price minus the original shipping cost.",
     True, 0.88),
    ("v04-relevant", "validation", "AR1004",
     "Can I cancel my subscription before the renewal date?",
     "Yes, you can cancel any time before your renewal date from the Billing tab, and you'll "
     "keep access until the current period ends.",
     True, 0.91),
    ("v05-relevant", "validation", "AR1005",
     "Does the premium plan include phone support?",
     "Yes, the premium plan includes phone support on business days from 9am to 6pm.",
     True, 0.85),
    ("v06-relevant", "validation", "AR1006",
     "Why was my card declined at checkout?",
     "A card is usually declined at checkout because the billing address does not match the "
     "bank's records, the card has expired, or the bank's fraud check blocked the charge.",
     True, 0.94),
    ("v07-relevant", "validation", "AR1007",
     "How do I update the email address on my account?",
     "Open Account Settings, select 'Email', enter the new address, and confirm it from the "
     "link we send to that address.",
     True, 0.89),
    ("v08-relevant", "validation", "AR1008",
     "Is the product warranty transferable to a new owner?",
     "No, the warranty is registered to the original purchaser only and does not transfer if "
     "you sell or give away the product.",
     True, 0.82),
    ("v09-relevant", "validation", "AR1009",
     "What file formats can I upload to the dashboard?",
     "The dashboard accepts CSV, JSON, and XLSX files up to 50MB each.",
     True, 0.87),
    ("v10-offtopic-boilerplate", "validation", "AR1010",
     "How long does standard shipping take?",
     "Thanks for reaching out! Our team appreciates your business and we're always here to "
     "help with anything you need.",
     False, 0.05),
    ("v11-offtopic-wrongtopic", "validation", "AR1011",
     "How do I reset my account password?",
     "You can change your notification preferences from the Settings menu under "
     "'Notifications'.",
     False, 0.03),
    ("v12-offtopic-adjacent", "validation", "AR1012",
     "What is your return policy for opened items?",
     "Unopened items in their original packaging can be returned for a full refund within 60 "
     "days.",
     False, 0.08),
    ("v13-offtopic-repeats", "validation", "AR1013",
     "Can I cancel my subscription before the renewal date?",
     "I understand you're asking whether you can cancel your subscription before it renews.",
     False, 0.10),
    ("v14-offtopic-deflect", "validation", "AR1014",
     "Does the premium plan include phone support?",
     "Support options can vary, and it really depends on a few factors. I'd recommend "
     "checking back later for more details.",
     False, 0.12),
    ("v15-offtopic-generic", "validation", "AR1015",
     "Why was my card declined at checkout?",
     "We accept Visa, Mastercard, and American Express for all orders.",
     False, 0.06),
    ("v16-offtopic-wrongfield", "validation", "AR1016",
     "How do I update the email address on my account?",
     "To update your mailing address for shipments, open Account Settings and select "
     "'Addresses'.",
     False, 0.09),
    ("v17-offtopic-unrelated", "validation", "AR1017",
     "What file formats can I upload to the dashboard?",
     "Our mobile app is available for both iOS and Android devices.",
     False, 0.07),
    ("v18-partial", "validation", "AR1018",
     "Is the product warranty transferable to a new owner?",
     "The warranty lasts two years from the original purchase date and covers manufacturing "
     "defects.",
     False, 0.47),
    ("v19-partial", "validation", "AR1019",
     "What file formats can I upload to the dashboard?",
     "You can upload CSV and JSON files to the dashboard; larger exports are best split into "
     "multiple files.",
     True, 0.55),
    ("v20-error", "validation", "AR1020",
     "Can I downgrade from the premium plan to the free plan?",
     "If you're looking to change your plan, you can do that any time from the Billing tab "
     "under 'Plan'.",
     False, 0.60),
    ("v21-partial", "validation", "AR1021",
     "What happens to my saved files if I close my account?",
     "Closing your account removes access to the dashboard immediately; you can export your "
     "files any time before that from the Files tab.",
     True, 0.58),
    ("v22-hard-wrong", "validation", "AR1022",
     "How do I reset my account password?",
     "To change the email address linked to your account, open Account Settings, select "
     "'Email', and confirm the new address from the link we send you.",
     False, 0.78),
    ("v23-relevant", "validation", "AR1023",
     "Can I cancel my subscription before the renewal date?",
     "Yes -- cancel any time from the Billing tab; you'll still have access through the end "
     "of the period you already paid for.",
     True, 0.84),
    ("v24-moderate", "validation", "AR1024",
     "Does the mobile app support offline access to my files?",
     "Yes, you can mark files for offline access from the file list, and they will sync again "
     "the next time you have a connection.",
     True, 0.65),
    ("v25-moderate", "validation", "AR1025",
     "Can I get a discount for paying annually instead of monthly?",
     "Annual and monthly plans include the same features and support options.",
     False, 0.35),
    # --- test: 25 pairs ----------------------------------------------------------------------
    ("t01-relevant", "test", "AR2001",
     "How long does express shipping take?",
     "Express shipping arrives within 1 to 2 business days after your order ships.",
     True, 0.92),
    ("t02-relevant", "test", "AR2002",
     "How do I enable two-factor authentication?",
     "Open Account Settings, select 'Security', turn on 'Two-factor authentication', and scan "
     "the QR code with your authenticator app.",
     True, 0.90),
    ("t03-relevant", "test", "AR2003",
     "What is your return policy for items damaged in shipping?",
     "If an item arrives damaged, contact us within 14 days with a photo and we'll send a "
     "replacement or a full refund at no extra cost.",
     True, 0.89),
    ("t04-relevant", "test", "AR2004",
     "Can I pause my subscription instead of cancelling?",
     "Yes, you can pause your subscription for up to 3 months from the Billing tab; billing "
     "resumes automatically afterward.",
     True, 0.90),
    ("t05-relevant", "test", "AR2005",
     "Does the basic plan include email support?",
     "Yes, the basic plan includes email support with a typical response time of one business "
     "day.",
     True, 0.86),
    ("t06-relevant", "test", "AR2006",
     "Why did my payment fail during checkout?",
     "A payment usually fails during checkout because the card's expiration date is wrong, "
     "the available balance is too low, or the issuing bank flagged the transaction.",
     True, 0.93),
    ("t07-relevant", "test", "AR2007",
     "How do I change the phone number on my account?",
     "Open Account Settings, select 'Phone', enter the new number, and verify it with the "
     "code we text to it.",
     True, 0.88),
    ("t08-relevant", "test", "AR2008",
     "Is the extended warranty refundable if I return the product?",
     "Yes, if you return the product within the return window, the extended warranty you "
     "purchased with it is refunded in full.",
     True, 0.84),
    ("t09-relevant", "test", "AR2009",
     "What image formats can I upload to the gallery?",
     "The gallery accepts JPEG, PNG, and WEBP images up to 10MB each.",
     True, 0.87),
    ("t10-offtopic-boilerplate", "test", "AR2010",
     "How long does express shipping take?",
     "We really appreciate you being a customer and we're always working to improve your "
     "experience.",
     False, 0.04),
    ("t11-offtopic-wrongtopic", "test", "AR2011",
     "How do I enable two-factor authentication?",
     "You can switch your display theme to dark mode from the Settings menu.",
     False, 0.03),
    ("t12-offtopic-adjacent", "test", "AR2012",
     "What is your return policy for items damaged in shipping?",
     "Items that no longer fit can be exchanged for a different size within 30 days of "
     "delivery.",
     False, 0.09),
    ("t13-offtopic-repeats", "test", "AR2013",
     "Can I pause my subscription instead of cancelling?",
     "You're asking whether pausing is an option instead of cancelling outright.",
     False, 0.11),
    ("t14-offtopic-deflect", "test", "AR2014",
     "Does the basic plan include email support?",
     "Our support options are always evolving, so it's best to keep an eye on updates.",
     False, 0.13),
    ("t15-offtopic-generic", "test", "AR2015",
     "Why did my payment fail during checkout?",
     "We accept all major credit cards as well as PayPal for checkout.",
     False, 0.07),
    ("t16-offtopic-wrongfield", "test", "AR2016",
     "How do I change the phone number on my account?",
     "To change the shipping address on an order that hasn't shipped yet, go to Orders and "
     "select 'Edit address'.",
     False, 0.10),
    ("t17-offtopic-unrelated", "test", "AR2017",
     "What image formats can I upload to the gallery?",
     "Our desktop app now supports keyboard shortcuts for faster navigation.",
     False, 0.06),
    ("t18-partial", "test", "AR2018",
     "Is the extended warranty refundable if I return the product?",
     "The extended warranty covers accidental damage for up to two years from purchase.",
     False, 0.46),
    ("t19-partial", "test", "AR2019",
     "What image formats can I upload to the gallery?",
     "You can upload JPEG and PNG images to the gallery; very large files may take longer to "
     "process.",
     True, 0.56),
    ("t20-error", "test", "AR2020",
     "Can I switch from the free plan to the premium plan mid-month?",
     "Plan changes are billed on a prorated basis, so you only pay for the days remaining in "
     "the cycle.",
     False, 0.61),
    ("t21-partial", "test", "AR2021",
     "What happens to my draft documents if my trial expires?",
     "When your trial expires, editing is disabled, but your drafts stay saved and become "
     "editable again if you subscribe.",
     True, 0.57),
    ("t22-hard-wrong", "test", "AR2022",
     "How do I enable two-factor authentication?",
     "To change your account password, open Account Settings, select 'Security', then "
     "'Change password', and enter your new password twice to confirm.",
     False, 0.83),
    ("t23-relevant", "test", "AR2023",
     "Does the basic plan include email support?",
     "Yes -- basic plan customers can reach email support any time, and most replies arrive "
     "within one business day.",
     True, 0.86),
    ("t24-moderate", "test", "AR2024",
     "Does the desktop app support offline access to my files?",
     "Yes, mark files for offline access from the file list and they will sync again the next "
     "time you have a connection.",
     True, 0.65),
    ("t25-moderate", "test", "AR2025",
     "Is there a discount for paying for the year upfront instead of monthly?",
     "The annual and monthly plans offer the same set of features and the same support "
     "options.",
     False, 0.35),
    # --- demo: 2 pairs, shown but never scored ------------------------------------------------
    ("d01-relevant", "demo", "AR3001",
     "What is your return policy for opened items?",
     "Opened items can be returned within 30 days of delivery, as long as they still work and "
     "are not damaged; we refund the full purchase price minus the original shipping fee.",
     None, 0.90),
    ("d02-offtopic", "demo", "AR3002",
     "How do I reset my account password?",
     "You can download your invoice history as a PDF from the Billing tab.",
     None, 0.04),
]  # fmt: skip


def _fields(pair_id, question, response):
    return {"pair_id": pair_id, "question": question, "response": response}


def answers_for(probability: float, provenance: Provenance) -> dict:
    """{question name: answer} for one row: the stored probability that the response addresses
    the question the user asked."""
    return {"relevant": NoulAnswer(probability, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, pair_id, question, response, label, _probability in rows:
        fields = _fields(pair_id, question, response)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, pair_id, question, response, _label, probability in rows:
        fields = _fields(pair_id, question, response)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(probability, Provenance.synthetic())
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
