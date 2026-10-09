"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 09.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect: most are right, several are right but at low confidence, and one
(``v18-invoice-wrong``) is wrong on ``validation`` at a confidence below the threshold this
recipe's notebook later freezes, while one (``t17-hybrid-wrong-confident``) is wrong *and*
confident on ``test`` at 0.7500, comfortably above that frozen threshold (0.5000) -- so the
notebook's selective-prediction numbers show a real, non-zero risk on test rather than a
guarantee that happens to hold. The hard cases this use case calls for (a fixed folder catalog,
low-confidence proposals left unsorted) and the ones CONTRIBUTING.md asks every recipe to cover
are included and tagged in their id: a file with no good match at all
(``-no-match``), a file whose name and content point to two different folders at once
(``-ambiguous``), a file whose name suggests one folder while its excerpt says another
(``-lookalike``), and a file whose excerpt is too short to carry any signal (``-short``). The
replay keys come from the same ``build_state`` and ``build_questions`` the notebook uses, via
``helpers.py``.

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
OPTIONS = list(
    QUESTIONS["destination"].criteria
)  # invoices, contracts, reports, correspondence, unsorted

# (id, split, file_id, filename, excerpt, gold label or None for demo, stored probabilities)
# Probabilities are in OPTIONS order (invoices, contracts, reports, correspondence, unsorted)
# and sum to 1.
ROWS = [
    # --- validation: 19 examples -------------------------------------------------------------
    ("v01-invoice", "validation", "F1001", "INV-10234_Acme_Supplies.pdf",
     "Invoice #10234. Amount due: $482.00. Payment terms: net 30. Remit to Acme Supplies "
     "accounts receivable by the due date.",
     "invoices", (0.86, 0.04, 0.04, 0.03, 0.03)),
    ("v02-invoice", "validation", "F1002", "January_Utility_Statement.pdf",
     "Statement period January 1 to January 31. Total amount due $212.50. Autopay is "
     "scheduled for the 5th of next month.",
     "invoices", (0.90, 0.03, 0.03, 0.02, 0.02)),
    ("v03-contract", "validation", "F1003", "Vendor_Services_Agreement_v3.docx",
     "This Master Services Agreement is entered into by the Client and the Vendor, effective "
     "as of the date of the last signature below.",
     "contracts", (0.05, 0.84, 0.04, 0.04, 0.03)),
    ("v04-contract", "validation", "F1004", "NDA_Contractor_Reyes.pdf",
     "Both parties agree to keep confidential information disclosed under this agreement "
     "strictly confidential for a period of five years.",
     "contracts", (0.04, 0.88, 0.03, 0.03, 0.02)),
    ("v05-report", "validation", "F1005", "Q3_Sales_Summary.xlsx",
     "Quarterly revenue grew eight percent over Q2, driven mainly by the east region. "
     "Customer churn held steady at 2.1 percent.",
     "reports", (0.04, 0.04, 0.85, 0.04, 0.03)),
    ("v06-report", "validation", "F1006", "Weekly_Status_Update_Oct06.docx",
     "This week the team closed four open tickets and began the migration to the new "
     "warehouse schema.",
     "reports", (0.03, 0.03, 0.89, 0.03, 0.02)),
    ("v07-correspondence", "validation", "F1007", "Letter_to_Client_Reply.docx",
     "Thank you for your patience while we looked into the shipping delay. We expect the "
     "replacement to arrive by Friday.",
     "correspondence", (0.04, 0.04, 0.04, 0.85, 0.03)),
    ("v08-correspondence", "validation", "F1008", "Meeting_Notes_Oct03.txt",
     "Discussed the renewal timeline with the client. They asked for a call next week to "
     "review pricing options.",
     "correspondence", (0.03, 0.03, 0.03, 0.89, 0.02)),
    ("v09-no-match", "validation", "F1009", "banana_bread_recipe.txt",
     "Preheat the oven to 350F. Mash three ripe bananas and mix with sugar, eggs and melted "
     "butter.",
     "unsorted", (0.03, 0.03, 0.03, 0.03, 0.88)),
    ("v10-ambiguous", "validation", "F1010", "Renewal_Invoice_and_Agreement.pdf",
     "This renewal invoice reflects the updated contract pricing. The signature below "
     "confirms acceptance of the revised terms for the next twelve months.",
     "contracts", (0.30, 0.46, 0.08, 0.08, 0.08)),
    ("v11-lookalike", "validation", "F1011", "Status_Report_Vendor.pdf",
     "Hi Alex, sorry for the delay in replying. I wanted to let you know we approved the "
     "budget increase for next quarter and will send the paperwork separately.",
     "correspondence", (0.08, 0.06, 0.18, 0.60, 0.08)),
    ("v12-short", "validation", "F1012", "scan0013.pdf",
     "Please advise.",
     "unsorted", (0.20, 0.19, 0.18, 0.20, 0.23)),
    ("v13-invoice-lowconf", "validation", "F1013", "Supply_Order_Confirmation.pdf",
     "Order confirmed. Three items shipped today; the remaining two are backordered. An "
     "updated invoice will follow once they ship.",
     "invoices", (0.42, 0.20, 0.14, 0.12, 0.12)),
    ("v14-contract-lowconf", "validation", "F1014", "Office_Space_Addendum.pdf",
     "This addendum modifies section 4 of the existing lease. The new monthly amount takes "
     "effect the first of next month pending signature.",
     "contracts", (0.18, 0.40, 0.16, 0.14, 0.12)),
    ("v15-report-lowconf", "validation", "F1015", "Support_Metrics_Oct.pdf",
     "Ticket volume was flat month over month. Average response time improved slightly after "
     "the new routing rules went live.",
     "reports", (0.16, 0.14, 0.42, 0.16, 0.12)),
    ("v16-correspondence-lowconf", "validation", "F1016", "Note_to_Self_Followup.txt",
     "Remember to follow up with the client about the pricing question raised on the call.",
     "correspondence", (0.14, 0.12, 0.16, 0.42, 0.16)),
    ("v17-unsorted-lowconf", "validation", "F1017", "misc_file_2.pdf",
     "See attached for details.",
     "unsorted", (0.14, 0.16, 0.14, 0.16, 0.40)),
    ("v18-invoice-wrong", "validation", "F1018", "Printer_Lease_Partial_Invoice.pdf",
     "Invoice for the printer lease agreement, covering months one through three. Amount "
     "due $305.00. The remaining months bill separately under the same agreement.",
     "invoices", (0.20, 0.46, 0.12, 0.11, 0.11)),
    ("v19-report", "validation", "F1019", "Annual_Performance_Review_Dept.pdf",
     "Department headcount grew from twelve to fifteen. Average time to resolution improved "
     "by eighteen percent year over year.",
     "reports", (0.05, 0.05, 0.82, 0.05, 0.03)),
    # --- test: 19 examples ---------------------------------------------------------------------
    ("t01-invoice", "test", "F2001", "INV-20144_Acme_Supplies.pdf",
     "Invoice #20144. Amount due: $398.00. Payment terms: net 15. Remit to Acme Supplies "
     "accounts receivable.",
     "invoices", (0.87, 0.04, 0.04, 0.03, 0.02)),
    ("t02-invoice", "test", "F2002", "February_Utility_Statement.pdf",
     "Statement period February 1 to February 28. Total amount due $198.75. Autopay is "
     "scheduled for the 5th.",
     "invoices", (0.91, 0.03, 0.03, 0.02, 0.01)),
    ("t03-contract", "test", "F2003", "Vendor_Services_Agreement_v4.docx",
     "This amendment to the Master Services Agreement is entered into by the Client and the "
     "Vendor, effective upon signature.",
     "contracts", (0.04, 0.85, 0.04, 0.04, 0.03)),
    ("t04-contract", "test", "F2004", "NDA_Contractor_Price.pdf",
     "Both parties agree to keep confidential information disclosed under this agreement "
     "strictly confidential for a period of three years.",
     "contracts", (0.03, 0.89, 0.03, 0.03, 0.02)),
    ("t05-report", "test", "F2005", "Q4_Sales_Summary.xlsx",
     "Quarterly revenue grew five percent over Q3, driven mainly by renewals. Customer churn "
     "ticked up slightly to 2.4 percent.",
     "reports", (0.04, 0.04, 0.86, 0.04, 0.02)),
    ("t06-report", "test", "F2006", "Weekly_Status_Update_Nov03.docx",
     "This week the team closed six open tickets and finished the warehouse schema "
     "migration.",
     "reports", (0.03, 0.03, 0.90, 0.02, 0.02)),
    ("t07-correspondence", "test", "F2007", "Letter_to_Client_Followup.docx",
     "Following up on our call yesterday, the replacement part shipped this morning and "
     "should arrive Thursday.",
     "correspondence", (0.04, 0.04, 0.04, 0.86, 0.02)),
    ("t08-correspondence", "test", "F2008", "Meeting_Notes_Nov05.txt",
     "Discussed the onboarding checklist with the new client contact. They will send the "
     "signed paperwork separately.",
     "correspondence", (0.03, 0.03, 0.03, 0.90, 0.01)),
    ("t09-no-match", "test", "F2009", "office_potluck_signup.docx",
     "Please sign up for a dish to bring to Friday's potluck. We already have mac and cheese "
     "and a salad covered.",
     "unsorted", (0.03, 0.03, 0.03, 0.03, 0.88)),
    ("t10-ambiguous", "test", "F2010", "Renewal_Invoice_and_Agreement_2.pdf",
     "This renewal invoice reflects the updated contract pricing effective next quarter. The "
     "signature below confirms acceptance of the revised terms.",
     "contracts", (0.28, 0.48, 0.08, 0.08, 0.08)),
    ("t11-lookalike", "test", "F2011", "Status_Report_Vendor_2.pdf",
     "Hi Jordan, thanks for your patience. I'm writing to confirm we've approved the "
     "extended timeline and will send the revised schedule next week.",
     "correspondence", (0.07, 0.06, 0.17, 0.62, 0.08)),
    ("t12-short", "test", "F2012", "scan0027.pdf",
     "Thanks.",
     "unsorted", (0.21, 0.19, 0.18, 0.20, 0.22)),
    ("t13-invoice-lowconf", "test", "F2013", "Supply_Order_Confirmation_2.pdf",
     "Order confirmed. Two items shipped today; the rest are backordered. An updated invoice "
     "will follow once they ship.",
     "invoices", (0.40, 0.21, 0.14, 0.13, 0.12)),
    ("t14-contract-lowconf", "test", "F2014", "Office_Space_Addendum_2.pdf",
     "This addendum modifies section 6 of the existing lease. The new monthly amount takes "
     "effect next month pending signature.",
     "contracts", (0.17, 0.41, 0.16, 0.14, 0.12)),
    ("t15-report-lowconf", "test", "F2015", "Support_Metrics_Nov.pdf",
     "Ticket volume rose slightly this month. Average response time held steady despite the "
     "increase.",
     "reports", (0.15, 0.14, 0.43, 0.16, 0.12)),
    ("t16-correspondence-lowconf", "test", "F2016", "Note_to_Self_Followup_2.txt",
     "Remember to send the client the updated timeline before the end of the week.",
     "correspondence", (0.14, 0.13, 0.15, 0.43, 0.15)),
    ("t17-hybrid-wrong-confident", "test", "F2017", "Lease_Renewal_Final_Terms.pdf",
     "This finalizes the printer lease renewal: twelve months at the adjusted rate, "
     "countersigned by both parties. Outstanding balance from the prior term, $610.00, is "
     "included here for reference only.",
     "contracts", (0.80, 0.07, 0.05, 0.04, 0.04)),
    ("t18-report-lowconf", "test", "F2018", "Support_Metrics_Nov_Draft.pdf",
     "Draft figures for the November metrics review; numbers are provisional pending final "
     "reconciliation.",
     "reports", (0.16, 0.13, 0.44, 0.15, 0.12)),
    ("t19-invoice", "test", "F2019", "INV-20199_Acme_Supplies.pdf",
     "Invoice #20199. Amount due: $512.00. Payment terms: net 30. Remit to Acme Supplies "
     "accounts receivable.",
     "invoices", (0.83, 0.06, 0.05, 0.03, 0.03)),
    # --- demo: 2 examples, shown but never scored -----------------------------------------------
    ("d01-mixed", "demo", "F3001", "Renewal_Quote_and_Terms.pdf",
     "This quote reflects the renewed service terms. Please sign and return to confirm "
     "acceptance of the twelve-month extension at the adjusted rate.",
     None, (0.28, 0.47, 0.09, 0.08, 0.08)),
    ("d02-short", "demo", "F3002", "scan0047.pdf",
     "Noted, thanks.",
     None, (0.21, 0.20, 0.19, 0.20, 0.20)),
]  # fmt: skip


def _fields(file_id, filename, excerpt):
    return {"file_id": file_id, "filename": filename, "excerpt": excerpt}


def answers_for(probabilities: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over the five options."""
    return {
        "destination": ChoiceAnswer.from_probabilities(
            dict(zip(OPTIONS, probabilities, strict=True)), provenance
        )
    }


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, file_id, filename, excerpt, label, _probs in rows:
        fields = _fields(file_id, filename, excerpt)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, file_id, filename, excerpt, _label, probs in rows:
        fields = _fields(file_id, filename, excerpt)
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
