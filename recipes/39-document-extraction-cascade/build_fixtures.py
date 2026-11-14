"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 39.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic and deliberately imperfect: most documents extract and verify
cleanly, but several show the hard cases the use case names -- a decoy (a purchase order, a
tracking number, a reference to a superseded invoice, a subtotal or a previous balance) that
stage 1 wrongly prefers and stage 2 correctly catches; a decoy stage 2 wrongly clears anyway
(the one ``test`` error the frozen gate does not catch); a correct pick stage 2 wrongly doubts;
a low-confidence verification that is sent to review although it was probably right; a document
with no candidate for a field at all (both fields, one field, or neither); and a document where
real candidates exist but the right answer is still ``not_found`` (a decoy present, nothing
genuinely stating the field).

Each row names its document's gold value per field (``"not_found"`` when nothing states it), the
stage-1 Choice probabilities for every field this document has a real candidate for (aligned to
``helpers.extract_candidates``'s own candidate order, with the shared ``not_found`` fallback
last), and the stage-2 Noul "is this really it" probability for every field whose stage-1 top
choice named a real candidate. ``_resolve_row`` is the one place that turns a row into the
fields that actually get a stage-1 question, the fields that actually get a stage-2 question,
and the two requests' replay keys -- used by both ``build_inputs_and_labels`` and
``build_responses``, so the two can never disagree about which requests a row makes.

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

from jev_cookbook import (
    ChoiceAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    load_helpers,
    replay_key,
)

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

BUYER = "Bill To: Keystone Retail Group, 400 Commerce Ave."


def invoice_line(number):
    return f"Invoice #{number} for your records."


def po_decoy(number):
    return f"Purchase order number PO-{number} authorized this order."


def prior_invoice_decoy(number):
    return f"Previous invoice reference {number} was paid in full last month."


def tracking_decoy(number):
    return f"Tracking number TRK-{number} was assigned to this shipment."


def total_line(amount):
    return f"Total due: ${amount}."


def subtotal_line(amount):
    return f"Subtotal: ${amount}."


def tax_line(amount):
    return f"Sales tax: ${amount}."


def shipping_line(amount):
    return f"Shipping and handling: ${amount}."


def prior_balance_decoy(amount):
    return f"Previous balance carried forward: ${amount}."


def margin_note_decoy(amount):
    return f"A handwritten margin note says to disregard the total above and use ${amount} instead."


def items_line(desc):
    return f"Items: {desc}."


CLOSING = "Thank you for your business."


def _doc(header, clauses, items_desc):
    """Join a header, the field-bearing clauses (in reading order) and a closing items line
    and thank-you into one document string -- the same shape every row below uses."""
    return " ".join([header, *clauses, items_line(items_desc), CLOSING])


# --------------------------------------------------------------------------------------------
# ROWS: one dict per document. ``gold`` is ``None`` for a demo document (never scored) and
# otherwise ``{field: token-or-"not_found"}``. ``stage1`` gives, for every field this document
# has at least one real candidate for, the Choice probabilities in candidate order with
# ``not_found`` last; a field with no real candidate is simply absent from ``stage1`` (Python
# resolves it directly -- ``_resolve_row`` checks this against the document's own extracted
# candidates, so a mismatch here is caught at generation time, not silently). ``stage2`` gives
# the verification Noul probability for every field whose stage-1 top choice (computed from
# ``stage1``, never hand-duplicated) names a real candidate; a field stage 1 resolved to
# ``not_found`` is simply absent from ``stage2`` too.
# --------------------------------------------------------------------------------------------

ROWS = [
    # === clean baselines: both fields present, correctly extracted and verified ===
    dict(
        id="v01", split="validation", doc_id="D01",
        document=_doc(
            "Purchase Confirmation #D01.",
            [invoice_line("4420"), BUYER, total_line("540.00")],
            "12 cartons of copy paper",
        ),
        gold={"invoice_number": "4420", "total_amount": "540.00"},
        stage1={"invoice_number": [0.90, 0.10], "total_amount": [0.92, 0.08]},
        stage2={"invoice_number": 0.90, "total_amount": 0.90},
    ),
    dict(
        id="v02", split="validation", doc_id="D02",
        document=_doc(
            "Purchase Confirmation #D02.",
            [invoice_line("4421"), BUYER, subtotal_line("500.00"), tax_line("40.00"), total_line("540.00")],
            "4 reams of cardstock",
        ),
        gold={"invoice_number": "4421", "total_amount": "540.00"},
        stage1={"invoice_number": [0.88, 0.12], "total_amount": [0.05, 0.07, 0.80, 0.08]},
        stage2={"invoice_number": 0.88, "total_amount": 0.85},
    ),
    # === a decoy candidate is present but correctly not chosen (ambiguous, resolved right) ===
    dict(
        id="v03", split="validation", doc_id="D03",
        document=_doc(
            "Order Summary #D03.",
            [invoice_line("5120"), po_decoy("7788"), BUYER, total_line("210.50")],
            "a shelving unit",
        ),
        gold={"invoice_number": "5120", "total_amount": "210.50"},
        stage1={"invoice_number": [0.78, 0.12, 0.10], "total_amount": [0.90, 0.10]},
        stage2={"invoice_number": 0.88, "total_amount": 0.90},
    ),
    # === stage 1 wrongly, confidently prefers a decoy; stage 2 correctly catches it ===
    dict(
        id="v04", split="validation", doc_id="D04",
        document=_doc(
            "Order Summary #D04.",
            [prior_invoice_decoy("3990"), invoice_line("5121"), BUYER, total_line("88.00")],
            "replacement toner",
        ),
        gold={"invoice_number": "5121", "total_amount": "88.00"},
        stage1={"invoice_number": [0.72, 0.18, 0.10], "total_amount": [0.85, 0.15]},
        stage2={"invoice_number": 0.12, "total_amount": 0.90},
    ),
    # === a decoy for one field, no candidate at all for the other (partial no-match) ===
    dict(
        id="v05", split="validation", doc_id="D05",
        document=_doc(
            "Delivery Note #D05.",
            [BUYER, tracking_decoy("99120"), invoice_line("5122")],
            "2 staplers",
        ),
        gold={"invoice_number": "5122", "total_amount": "not_found"},
        stage1={"invoice_number": [0.15, 0.75, 0.10]},
        stage2={"invoice_number": 0.90},
    ),
    # === stage 1 wrongly prefers a decoy amount; stage 2 correctly catches it ===
    dict(
        id="v06", split="validation", doc_id="D06",
        document=_doc(
            "Order Summary #D06.",
            [invoice_line("5123"), BUYER, subtotal_line("260.00"), prior_balance_decoy("50.00"), total_line("300.00")],
            "a desk lamp",
        ),
        gold={"invoice_number": "5123", "total_amount": "300.00"},
        stage1={"invoice_number": [0.85, 0.15], "total_amount": [0.10, 0.78, 0.06, 0.06]},
        stage2={"invoice_number": 0.88, "total_amount": 0.12},
    ),
    # === no invoice number stated at all (no candidate), amount present ===
    dict(
        id="v07", split="validation", doc_id="D07",
        document=_doc(
            "Delivery Note #D07.",
            [BUYER, total_line("64.00")],
            "a box of binder clips",
        ),
        gold={"invoice_number": "not_found", "total_amount": "64.00"},
        stage1={"total_amount": [0.88, 0.12]},
        stage2={"total_amount": 0.88},
    ),
    # === stage 2 is confident but not sure enough (uncertain -> review) ===
    dict(
        id="v08", split="validation", doc_id="D08",
        document=_doc(
            "Order Summary #D08.",
            [invoice_line("5124"), BUYER, subtotal_line("120.00"), shipping_line("15.00"), total_line("135.00")],
            "a cabinet handle set",
        ),
        gold={"invoice_number": "5124", "total_amount": "135.00"},
        stage1={"invoice_number": [0.82, 0.18], "total_amount": [0.06, 0.08, 0.78, 0.08]},
        stage2={"invoice_number": 0.90, "total_amount": 0.90},
    ),
    # === neither field has a candidate at all: zero requests for this document ===
    dict(
        id="v09", split="validation", doc_id="D09",
        document=_doc("Purchase Confirmation #D09.", [BUYER], "10 boxes of printer paper"),
        gold={"invoice_number": "not_found", "total_amount": "not_found"},
        stage1={},
        stage2={},
    ),
    # === a misdirecting aside is present but correctly not chosen ===
    dict(
        id="v10", split="validation", doc_id="D10",
        document=_doc(
            "Order Summary #D10.",
            [invoice_line("5125"), BUYER, margin_note_decoy("0.00"), total_line("412.75")],
            "a monitor arm",
        ),
        gold={"invoice_number": "5125", "total_amount": "412.75"},
        stage1={"invoice_number": [0.85, 0.15], "total_amount": [0.10, 0.80, 0.10]},
        stage2={"invoice_number": 0.88, "total_amount": 0.85},
    ),
    # === three decoys, one real value: the richest candidate set, resolved correctly ===
    dict(
        id="v11", split="validation", doc_id="D11",
        document=_doc(
            "Order Summary #D11.",
            [po_decoy("8810"), tracking_decoy("22011"), invoice_line("5126"), BUYER, subtotal_line("90.00"), tax_line("7.20"), total_line("97.20")],
            "a box of highlighters",
        ),
        gold={"invoice_number": "5126", "total_amount": "97.20"},
        stage1={"invoice_number": [0.08, 0.08, 0.74, 0.10], "total_amount": [0.05, 0.05, 0.82, 0.08]},
        stage2={"invoice_number": 0.85, "total_amount": 0.85},
    ),
    # === stage 1 picks the right amount, but stage 2 wrongly doubts a correct pick ===
    dict(
        id="v12", split="validation", doc_id="D12",
        document=_doc(
            "Delivery Note #D12.",
            [invoice_line("5127"), BUYER, prior_balance_decoy("60.00"), total_line("220.00")],
            "a reception desk",
        ),
        gold={"invoice_number": "5127", "total_amount": "220.00"},
        stage1={"invoice_number": [0.84, 0.16], "total_amount": [0.15, 0.75, 0.10]},
        stage2={"invoice_number": 0.86, "total_amount": 0.08},
    ),
    dict(
        id="v13", split="validation", doc_id="D13",
        document=_doc(
            "Order Summary #D13.",
            [invoice_line("5128"), BUYER, total_line("76.40")],
            "a box of wood screws",
        ),
        gold={"invoice_number": "5128", "total_amount": "76.40"},
        stage1={"invoice_number": [0.86, 0.14], "total_amount": [0.90, 0.10]},
        stage2={"invoice_number": 0.90, "total_amount": 0.90},
    ),
    # === test ===
    dict(
        id="t01", split="test", doc_id="E01",
        document=_doc(
            "Purchase Confirmation #E01.",
            [invoice_line("6001"), BUYER, total_line("612.00")],
            "30 yards of canvas fabric",
        ),
        gold={"invoice_number": "6001", "total_amount": "612.00"},
        stage1={"invoice_number": [0.88, 0.12], "total_amount": [0.90, 0.10]},
        stage2={"invoice_number": 0.90, "total_amount": 0.90},
    ),
    dict(
        id="t02", split="test", doc_id="E02",
        document=_doc(
            "Order Summary #E02.",
            [invoice_line("6002"), BUYER, subtotal_line("600.00"), tax_line("48.00"), total_line("648.00")],
            "15 surge protectors",
        ),
        gold={"invoice_number": "6002", "total_amount": "648.00"},
        stage1={"invoice_number": [0.86, 0.14], "total_amount": [0.06, 0.06, 0.80, 0.08]},
        stage2={"invoice_number": 0.88, "total_amount": 0.88},
    ),
    dict(
        id="t03", split="test", doc_id="E03",
        document=_doc(
            "Order Summary #E03.",
            [invoice_line("6003"), po_decoy("1190"), BUYER, total_line("340.00")],
            "a software license renewal",
        ),
        gold={"invoice_number": "6003", "total_amount": "340.00"},
        stage1={"invoice_number": [0.76, 0.14, 0.10], "total_amount": [0.88, 0.12]},
        stage2={"invoice_number": 0.88, "total_amount": 0.88},
    ),
    # === the one test error the frozen gate does not catch: stage 2 wrongly, confidently
    # clears a decoy stage 1 wrongly, confidently preferred ===
    dict(
        id="t04", split="test", doc_id="E04",
        document=_doc(
            "Order Summary #E04.",
            [prior_invoice_decoy("5998"), invoice_line("6004"), BUYER, total_line("150.00")],
            "a quarterly subscription",
        ),
        gold={"invoice_number": "6004", "total_amount": "150.00"},
        stage1={"invoice_number": [0.78, 0.12, 0.10], "total_amount": [0.85, 0.15]},
        stage2={"invoice_number": 0.85, "total_amount": 0.90},
    ),
    dict(
        id="t05", split="test", doc_id="E05",
        document=_doc(
            "Delivery Note #E05.",
            [BUYER, tracking_decoy("77011"), invoice_line("6005")],
            "a replacement cartridge",
        ),
        gold={"invoice_number": "6005", "total_amount": "not_found"},
        stage1={"invoice_number": [0.15, 0.75, 0.10]},
        stage2={"invoice_number": 0.88},
    ),
    dict(
        id="t06", split="test", doc_id="E06",
        document=_doc(
            "Order Summary #E06.",
            [invoice_line("6006"), BUYER, subtotal_line("260.00"), prior_balance_decoy("40.00"), total_line("300.00")],
            "a set of cabinet hinges",
        ),
        gold={"invoice_number": "6006", "total_amount": "300.00"},
        stage1={"invoice_number": [0.85, 0.15], "total_amount": [0.07, 0.07, 0.78, 0.08]},
        stage2={"invoice_number": 0.88, "total_amount": 0.86},
    ),
    # === a decoy is present, but Jev correctly answers not_found for the field itself ===
    dict(
        id="t07", split="test", doc_id="E07",
        document=_doc(
            "Delivery Note #E07.",
            [BUYER, tracking_decoy("31090"), total_line("52.00")],
            "a box of sticky notes",
        ),
        gold={"invoice_number": "not_found", "total_amount": "52.00"},
        stage1={"invoice_number": [0.15, 0.85], "total_amount": [0.88, 0.12]},
        stage2={"total_amount": 0.88},
    ),
    # === stage 2 is confident but not sure enough (uncertain -> review), on test ===
    dict(
        id="t08", split="test", doc_id="E08",
        document=_doc(
            "Order Summary #E08.",
            [invoice_line("6008"), BUYER, subtotal_line("180.00"), shipping_line("20.00"), total_line("200.00")],
            "a set of shelf brackets",
        ),
        gold={"invoice_number": "6008", "total_amount": "200.00"},
        stage1={"invoice_number": [0.84, 0.16], "total_amount": [0.06, 0.08, 0.78, 0.08]},
        stage2={"invoice_number": 0.90, "total_amount": 0.48},
    ),
    dict(
        id="t09", split="test", doc_id="E09",
        document=_doc("Purchase Confirmation #E09.", [BUYER], "a box of binder clips"),
        gold={"invoice_number": "not_found", "total_amount": "not_found"},
        stage1={},
        stage2={},
    ),
    dict(
        id="t10", split="test", doc_id="E10",
        document=_doc(
            "Order Summary #E10.",
            [invoice_line("6010"), BUYER, margin_note_decoy("0.00"), total_line("501.25")],
            "a network switch",
        ),
        gold={"invoice_number": "6010", "total_amount": "501.25"},
        stage1={"invoice_number": [0.85, 0.15], "total_amount": [0.10, 0.80, 0.10]},
        stage2={"invoice_number": 0.88, "total_amount": 0.85},
    ),
    dict(
        id="t11", split="test", doc_id="E11",
        document=_doc(
            "Order Summary #E11.",
            [po_decoy("4410"), tracking_decoy("55021"), invoice_line("6011"), BUYER, subtotal_line("95.00"), tax_line("7.60"), total_line("102.60")],
            "a box of paper clips",
        ),
        gold={"invoice_number": "6011", "total_amount": "102.60"},
        stage1={"invoice_number": [0.08, 0.08, 0.74, 0.10], "total_amount": [0.05, 0.05, 0.82, 0.08]},
        stage2={"invoice_number": 0.85, "total_amount": 0.85},
    ),
    # === stage 2 wrongly doubts a correct pick, on test ===
    dict(
        id="t12", split="test", doc_id="E12",
        document=_doc(
            "Delivery Note #E12.",
            [invoice_line("6012"), BUYER, prior_balance_decoy("70.00"), total_line("310.00")],
            "a set of cabinet handles",
        ),
        gold={"invoice_number": "6012", "total_amount": "310.00"},
        stage1={"invoice_number": [0.86, 0.14], "total_amount": [0.14, 0.76, 0.10]},
        stage2={"invoice_number": 0.86, "total_amount": 0.08},
    ),
    dict(
        id="t13", split="test", doc_id="E13",
        document=_doc(
            "Order Summary #E13.",
            [invoice_line("6013"), BUYER, total_line("84.90")],
            "a box of thumbtacks",
        ),
        gold={"invoice_number": "6013", "total_amount": "84.90"},
        stage1={"invoice_number": [0.87, 0.13], "total_amount": [0.90, 0.10]},
        stage2={"invoice_number": 0.90, "total_amount": 0.90},
    ),
    dict(
        id="t14", split="test", doc_id="E14",
        document=_doc(
            "Order Summary #E14.",
            [prior_invoice_decoy("5950"), po_decoy("9910"), invoice_line("6014"), BUYER, subtotal_line("210.00"), tax_line("16.80"), total_line("226.80")],
            "a strategic planning workshop",
        ),
        gold={"invoice_number": "6014", "total_amount": "226.80"},
        stage1={"invoice_number": [0.08, 0.08, 0.74, 0.10], "total_amount": [0.05, 0.05, 0.82, 0.08]},
        stage2={"invoice_number": 0.85, "total_amount": 0.85},
    ),
    # === demo (never scored) ===
    dict(
        id="d01-both-fields", split="demo", doc_id="F01",
        document=_doc(
            "Purchase Confirmation #F01.",
            [invoice_line("7001"), BUYER, total_line("128.00")],
            "a box of plywood sheets",
        ),
        gold=None,
        stage1={"invoice_number": [0.85, 0.15], "total_amount": [0.88, 0.12]},
        stage2={"invoice_number": 0.90, "total_amount": 0.90},
    ),
    dict(
        id="d02-no-candidates", split="demo", doc_id="F02",
        document=_doc("Delivery Note #F02.", [BUYER], "2 staplers"),
        gold=None,
        stage1={},
        stage2={},
    ),
]  # fmt: skip


def _fields(row: dict) -> dict:
    return {"doc_id": row["doc_id"], "document": row["document"]}


def _resolve_row(row: dict):
    """The one place a row's stage-1 and stage-2 requests (if any) are built, so
    ``build_inputs_and_labels`` and ``build_responses`` can never disagree about which requests
    a document makes. Returns ``(s1_fields, stage1_answers, key1, s2_fields, stage2_answers,
    key2)``; ``key1``/``key2`` are ``None`` when that stage makes no request for this document.
    """
    fields = _fields(row)
    s1_fields = helpers.stage1_fields(fields)
    given1 = row.get("stage1", {})
    if set(given1) != set(s1_fields):
        raise ValueError(
            f"{row['id']}: stage1 spec names {sorted(given1)}, but the document's own "
            f"candidates give fields {s1_fields}"
        )
    stage1_answers = {}
    for field in s1_fields:
        spans = helpers.spans_by_id(fields, field)
        options = [*spans, helpers.NOT_FOUND]
        probs = given1[field]
        if len(probs) != len(options):
            raise ValueError(
                f"{row['id']}/{field}: {len(probs)} stage1 probabilities for {len(options)} "
                f"options {options}"
            )
        stage1_answers[field] = ChoiceAnswer.from_probabilities(
            dict(zip(options, probs, strict=True)), Provenance.synthetic()
        )
    stage1_choices = {field: answer.choice for field, answer in stage1_answers.items()}
    s2_fields = helpers.stage2_fields(stage1_choices)
    given2 = row.get("stage2", {})
    if set(given2) != set(s2_fields):
        raise ValueError(
            f"{row['id']}: stage2 spec names {sorted(given2)}, but stage1's own top choices "
            f"give fields {s2_fields}"
        )
    stage2_answers = {
        field: NoulAnswer(given2[field], Provenance.synthetic()) for field in s2_fields
    }
    key1 = None
    if s1_fields:
        q1 = helpers.build_stage1_questions(fields, s1_fields)
        state1 = helpers.build_stage1_state(fields, s1_fields)
        key1 = replay_key(state1, q1)
    key2 = None
    if s2_fields:
        q2 = helpers.build_stage2_questions(s2_fields)
        state2 = helpers.build_stage2_state(fields, stage1_choices, s2_fields)
        key2 = replay_key(state2, q2)
    return s1_fields, stage1_answers, key1, s2_fields, stage2_answers, key2


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded. A document's
    ``replay_keys`` lists the stage-1 key (if a stage-1 request was made) and then the stage-2
    key (if a stage-2 request was made), in the order the notebook makes the requests -- never
    more than two, and empty when neither field has a candidate at all."""
    inputs, labels = [], []
    for row in rows:
        _s1, _a1, key1, _s2, _a2, key2 = _resolve_row(row)
        replay_keys = [key for key in (key1, key2) if key is not None]
        inputs.append(
            {
                "id": row["id"],
                "split": row["split"],
                "fields": _fields(row),
                "replay_keys": replay_keys,
            }
        )
        if row["gold"] is not None:
            labels.append({"id": row["id"], "label": row["gold"]})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response. A document contributes zero, one or
    two entries here, exactly matching the keys ``build_inputs_and_labels`` lists for it."""
    responses = {}
    for row in rows:
        _s1, stage1_answers, key1, _s2, stage2_answers, key2 = _resolve_row(row)
        if key1 is not None:
            responses[key1] = DecisionResult(stage1_answers, "synthetic").to_dict()
        if key2 is not None:
            responses[key2] = DecisionResult(stage2_answers, "synthetic").to_dict()
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
    # The same serialization jev_cookbook.dump_responses writes: only the top-level keys are
    # sorted; each response keeps the field order DecisionResult.to_dict() emits. Matching the
    # recorder exactly, rather than json.dumps(..., sort_keys=True) (which also sorts every
    # nested dict alphabetically), keeps a recording's diff to the values that actually changed.
    text = json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n"
    responses_file.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
