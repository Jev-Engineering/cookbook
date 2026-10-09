"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 14.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response here is synthetic: written by hand as probabilities, not produced by a model.
Some are deliberately wrong, spread across different span positions (never only the first
candidate), so the evaluation in the notebook has something to find. The replay keys come
from the same ``build_state`` and ``build_questions`` the notebook uses; the candidate spans
themselves come from ``helpers.extract_spans`` run on each document's real text below, never
from a hand-written list of spans.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from ROWS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.

A document with no candidate spans at all gets no replay key and no response: Python decides
``not_stated`` for it (``helpers.no_candidates``) without ever building a question, so there is
nothing to replay (docs/fixtures.md: "replay_keys may be empty for an example").
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
NOT_STATED = helpers.NOT_STATED

# --------------------------------------------------------------------------------------------
# Clause sentences. Each one is a single sentence that either names an organisation (a
# candidate span, once helpers.extract_spans runs on the finished document) or does not. The
# supplier-naming clauses vary in whether they use an explicit disclosure word ("Supplier:",
# "Vendor on file:", "supplied by", "remit payment to") or state the supplier bare, with no
# such word at all -- that split is what breaks a lexical-cue baseline below.
# --------------------------------------------------------------------------------------------

BUYER = "Keystone Retail Group"


def buyer(addr="400 Commerce Ave"):
    return f"Bill To: {BUYER}, {addr}."


def ship_via(name, hub="overnight"):
    return f"Shipped via {name} {hub}."


def ship_from(name, place):
    return f"Goods ship from the {name} warehouse near {place}."


def bank_proc(name):
    return f"Payment processing handled by {name} on behalf of the account."


def remit_shipping(name):
    """A decoy that also contains the word "remit" -- same cue word a real supplier
    disclosure uses, so a naive cue-regex baseline can be fooled by it."""
    return f"Remit any shipping inquiries to {name}, our courier partner."


def prior_vendor(name):
    """A near-miss: an organisation named in the same breath as the real supplier, but
    explicitly describing a superseded arrangement, not this document's supplier."""
    return f"{name} handled this account before the contract was reassigned."


def labeled_supplier(name, addr, label="Supplier"):
    return f"{label}: {name}, {addr}."


def vendor_on_file(name, addr):
    return f"Vendor on file: {name}, {addr}."


def remit_supplier(name, addr):
    return f"Please remit payment to {name}, Accounts Receivable, {addr}."


def bare_supplier(name, addr):
    """Names the supplier with no disclosure word at all: a cue-regex baseline has nothing
    to match here."""
    return f"{name} shipped this order from {addr}."


def prepared_by(name, service):
    return f"This delivery was prepared by {name}, our supplier of {service}."


def supplied_by(name, addr):
    return f"This shipment was supplied by {name}, {addr}."


def items(desc):
    return f"Items: {desc}."


CLOSING = "Thank you for your order."


def _doc(header, clauses, items_desc, closing=True):
    """Join a header, the candidate-bearing clauses (in reading order) and a closing items
    line into one document string."""
    parts = [header, *clauses, items(items_desc)]
    if closing:
        parts.append(CLOSING)
    return " ".join(parts)


# --------------------------------------------------------------------------------------------
# ROWS: (id, split, doc_id, document, gold, probs). ``probs`` is a plain list of
# probabilities in the SAME order ``helpers.extract_spans`` will find the candidates in that
# document, with the final entry for ``not_stated``; build_responses zips it against the real
# extracted span ids, so there is no hand-written span list anywhere here -- only the document
# text and which position(s), if any, the chosen probabilities favour. A document with no
# candidate spans at all carries ``probs=None`` (nothing to answer).
# --------------------------------------------------------------------------------------------

ROWS = [
    # === gold at position 1 of 2 (breaks "always take the last span") ===
    dict(
        id="v01", split="validation", doc_id="D01",
        document=_doc(
            "Purchase Confirmation #4410.",
            [labeled_supplier("Meridian Office Supplies Inc.", "18 Birch Lane"), buyer()],
            "12 cartons of copy paper",
        ),
        gold="Meridian Office Supplies Inc.", probs=[0.85, 0.05, 0.10],
    ),
    dict(
        id="v02", split="validation", doc_id="D02",
        document=_doc(
            "Purchase Confirmation #4411.",
            [labeled_supplier("Northwind Trading LLC", "92 Elm Street"), buyer()],
            "4 reams of cardstock",
        ),
        gold="Northwind Trading LLC", probs=[0.88, 0.04, 0.08],
    ),
    dict(
        id="v03", split="validation", doc_id="D03",
        document=_doc(
            "Purchase Confirmation #4412.",
            [bare_supplier("Ashgrove Fixtures Co.", "9 Lattice Row"), buyer()],
            "4 display shelving units",
        ),
        gold="Ashgrove Fixtures Co.", probs=[0.80, 0.06, 0.14],
    ),
    dict(
        id="t01", split="test", doc_id="D04",
        document=_doc(
            "Purchase Confirmation #4413.",
            [labeled_supplier("Meadowbrook Textiles Group", "61 Mill Road"), buyer()],
            "30 yards of canvas fabric",
        ),
        gold="Meadowbrook Textiles Group", probs=[0.84, 0.05, 0.11],
    ),
    dict(
        id="t02", split="test", doc_id="D05",
        document=_doc(
            "Purchase Confirmation #4414.",
            [bare_supplier("Stonebridge Electronics", "200 Circuit Drive"), buyer()],
            "15 surge protectors",
        ),
        gold="Stonebridge Electronics", probs=[0.78, 0.07, 0.15],
    ),
    # gold at s1, a cue-bearing decoy follows -- fools last-span AND cue-regex baselines
    dict(
        id="v04", split="validation", doc_id="D06",
        document=_doc(
            "Order Summary #5120.",
            [
                labeled_supplier("Cobalt Analytics LLC", "14 Meridian Court"),
                remit_shipping("Starling Courier Services"),
            ],
            "Quarterly reporting dashboard subscription",
        ),
        gold="Cobalt Analytics LLC", probs=[0.82, 0.08, 0.10],
    ),
    dict(
        id="t03", split="test", doc_id="D07",
        document=_doc(
            "Order Summary #5121.",
            [
                prepared_by("Oakridge Software Solutions", "inventory software"),
                remit_shipping("Silverline Freight Services"),
            ],
            "Annual license renewal for inventory software",
        ),
        gold="Oakridge Software Solutions", probs=[0.80, 0.09, 0.11],
    ),
    # === gold at position 2 of 2 (the "easy" layout, kept but no longer the only one) ===
    dict(
        id="v05", split="validation", doc_id="D08",
        document=_doc(
            "Purchase Confirmation #4415.",
            [buyer(), labeled_supplier("Granite Hardware Supply", "3 Anvil Row")],
            "50 boxes of wood screws",
        ),
        gold="Granite Hardware Supply", probs=[0.04, 0.87, 0.09],
    ),
    dict(
        id="v06", split="validation", doc_id="D09",
        document=_doc(
            "Purchase Confirmation #4416.",
            [buyer(), bare_supplier("Pinehollow Office Supply", "31 Birch Lane")],
            "6 boxes of sticky notes",
        ),
        gold="Pinehollow Office Supply", probs=[0.06, 0.80, 0.14],
    ),
    dict(
        id="t04", split="test", doc_id="D10",
        document=_doc(
            "Purchase Confirmation #4417.",
            [buyer(), labeled_supplier("Pinecrest Electronics Inc.", "200 Circuit Drive")],
            "10 network switches",
        ),
        gold="Pinecrest Electronics Inc.", probs=[0.04, 0.89, 0.07],
    ),
    # === gold at position 1 of 3 ===
    dict(
        id="v07", split="validation", doc_id="D11",
        document=_doc(
            "Order Summary #5122.",
            [
                labeled_supplier("Larkspur Consulting LLC", "5 Crown Court"),
                buyer("Operations"),
                bank_proc("Union Crest Bank"),
            ],
            "Process audit engagement",
        ),
        gold="Larkspur Consulting LLC", probs=[0.80, 0.08, 0.05, 0.07],
    ),
    dict(
        id="v08", split="validation", doc_id="D12",
        document=_doc(
            "Order Summary #5123.",
            [
                bare_supplier("Clearwater Analytics", "9 Meridian Row"),
                buyer("Finance Department"),
                prior_vendor("Oldfield Industrial Partners"),
            ],
            "Annual platform subscription",
        ),
        gold="Clearwater Analytics", probs=[0.78, 0.07, 0.06, 0.09],
    ),
    dict(
        id="t05", split="test", doc_id="D13",
        document=_doc(
            "Order Summary #5124.",
            [
                supplied_by("BrightPath Consulting Group", "5 Summit Plaza"),
                buyer("Finance Office"),
                remit_shipping("Crestline Overnight Shipping"),
            ],
            "Strategic planning workshop",
        ),
        gold="BrightPath Consulting Group", probs=[0.76, 0.08, 0.06, 0.10],
    ),
    dict(
        id="t06", split="test", doc_id="D14",
        document=_doc(
            "Order Summary #5125.",
            [
                remit_supplier("Fernwood Paper Mills", "88 Pulp Street"),
                buyer("Accounts Payable"),
                remit_shipping("Bluewave Logistics"),
            ],
            "25 reams of glossy paper",
        ),
        gold="Fernwood Paper Mills", probs=[0.74, 0.09, 0.06, 0.11],
    ),
    # === gold in the middle: position 2 of 3 (both "first" and "last" baselines wrong) ===
    dict(
        id="v09", split="validation", doc_id="D15",
        document=_doc(
            "Order Summary #5126.",
            [
                bank_proc("Harbor Point Bank"),
                vendor_on_file("Copperfield Supplies LLC", "9 Lantern Street"),
                ship_via("Starling Courier Services"),
            ],
            "100 reams of letterhead",
        ),
        gold="Copperfield Supplies LLC", probs=[0.08, 0.76, 0.06, 0.10],
    ),
    dict(
        id="v10", split="validation", doc_id="D16",
        document=_doc(
            "Delivery Note #2201.",
            [
                ship_via("Starling Courier Services"),
                vendor_on_file("Bluepeak Packaging Co.", "44 Kiln Street"),
                buyer(),
            ],
            "200 corrugated boxes",
        ),
        gold="Bluepeak Packaging Co.", probs=[0.10, 0.74, 0.06, 0.10],
    ),
    dict(
        id="t07", split="test", doc_id="D17",
        document=_doc(
            "Order Summary #5127.",
            [
                ship_from("Bluewave Logistics", "Reno"),
                bare_supplier("Marrow Creek Chemicals Inc.", "14 Foundry Row"),
                bank_proc("Union Crest Bank"),
            ],
            "30 liters of solvent",
        ),
        gold="Marrow Creek Chemicals Inc.", probs=[0.08, 0.72, 0.09, 0.11],
    ),
    dict(
        id="t08", split="test", doc_id="D18",
        document=_doc(
            "Order Summary #5128.",
            [
                prior_vendor("Driftlane Supplies Co."),
                prepared_by("Vellum Printing Co.", "stationery"),
                remit_shipping("Crestline Overnight Shipping"),
            ],
            "500 printed brochures",
        ),
        gold="Vellum Printing Co.", probs=[0.09, 0.73, 0.08, 0.10],
    ),
    # === gold at the last of 3 (position 3) ===
    dict(
        id="v11", split="validation", doc_id="D19",
        document=_doc(
            "Order Summary #5129.",
            [
                buyer("Risk Management"),
                bank_proc("Harbor Point Bank"),
                labeled_supplier("Thornfield Insurance Group", "8 Harbor Square"),
            ],
            "Annual liability policy renewal",
        ),
        gold="Thornfield Insurance Group", probs=[0.06, 0.08, 0.76, 0.10],
    ),
    dict(
        id="t09", split="test", doc_id="D20",
        document=_doc(
            "Order Summary #5130.",
            [
                buyer(),
                prior_vendor("Elmwood Paper Mills"),
                bare_supplier("Cinderwood Paper Mills", "21 Millrace Road"),
            ],
            "40 reams of cardstock",
        ),
        gold="Cinderwood Paper Mills", probs=[0.05, 0.14, 0.71, 0.10],
    ),
    # === gold at position 1 of 4 ===
    dict(
        id="v12", split="validation", doc_id="D21",
        document=_doc(
            "Order Summary #5131.",
            [
                remit_supplier("Falcon Ridge Chemicals Inc.", "3 Foundry Court"),
                buyer(),
                bank_proc("Union Crest Bank"),
                remit_shipping("Silverline Freight Services"),
            ],
            "40 liters of degreaser solution",
        ),
        gold="Falcon Ridge Chemicals Inc.", probs=[0.74, 0.05, 0.05, 0.07, 0.09],
    ),
    dict(
        id="t10", split="test", doc_id="D22",
        document=_doc(
            "Order Summary #5132.",
            [
                labeled_supplier("Ironwood Fasteners Inc.", "12 Anvil Lane"),
                buyer(),
                ship_via("Crestline Overnight Shipping"),
                prior_vendor("Spruceview Supplies Group"),
            ],
            "500 steel bolts",
        ),
        gold="Ironwood Fasteners Inc.", probs=[0.72, 0.06, 0.07, 0.06, 0.09],
    ),
    # === gold at the last of 4-5 ===
    dict(
        id="v13", split="validation", doc_id="D23",
        document=_doc(
            "Order Summary #5133.",
            [
                buyer("Facilities"),
                ship_from("Bluewave Logistics", "Tulsa"),
                bank_proc("Harbor Point Bank"),
                vendor_on_file("Maplewood Office Interiors", "6 Cedar Row"),
            ],
            "3 reception desks",
        ),
        gold="Maplewood Office Interiors", probs=[0.04, 0.06, 0.07, 0.73, 0.10],
    ),
    dict(
        id="t11", split="test", doc_id="D24",
        document=_doc(
            "Order Summary #5134.",
            [
                buyer("Operations"),
                prior_vendor("Brookstone Textiles"),
                ship_from("Silverline Freight Services", "Tulsa"),
                remit_supplier("Hazelwood Fixtures Inc.", "7 Birchwood Lane"),
            ],
            "10 cabinet handle sets",
        ),
        gold="Hazelwood Fixtures Inc.", probs=[0.03, 0.06, 0.08, 0.73, 0.10],
    ),
    # === the supplier's name appears in two different spans ===
    dict(
        id="v14", split="validation", doc_id="D25",
        document=_doc(
            "Delivery Note #2202.",
            [
                prepared_by("Brightwell Hardware Inc.", "fasteners and tools"),
                remit_supplier("Brightwell Hardware Inc.", "55 Industrial Way"),
            ],
            "12 boxes of wood screws",
        ),
        gold="Brightwell Hardware Inc.", probs=[0.22, 0.68, 0.10],
    ),
    dict(
        id="v15", split="validation", doc_id="D26",
        document=_doc(
            "Delivery Note #2203.",
            [
                prepared_by("Driftwood Media Group", "video content"),
                remit_supplier("Driftwood Media Group", "70 Studio Way"),
            ],
            "Quarterly promotional video package",
        ),
        gold="Driftwood Media Group", probs=[0.68, 0.22, 0.10],
    ),
    dict(
        id="t12", split="test", doc_id="D27",
        document=_doc(
            "Delivery Note #2204.",
            [
                buyer(),
                prepared_by("Dawnridge Hardware Supply", "shelving hardware"),
                remit_supplier("Dawnridge Hardware Supply", "19 Rivet Row"),
            ],
            "8 steel shelving units",
        ),
        gold="Dawnridge Hardware Supply", probs=[0.05, 0.20, 0.65, 0.10],
    ),
    dict(
        id="t13", split="test", doc_id="D28",
        document=_doc(
            "Delivery Note #2205.",
            [
                remit_supplier("Amberline Textiles Co.", "18 Spindle Street"),
                buyer(),
                prepared_by("Amberline Textiles Co.", "upholstery fabric"),
            ],
            "60 yards of upholstery fabric",
        ),
        gold="Amberline Textiles Co.", probs=[0.64, 0.05, 0.21, 0.10],
    ),
    # === no supporting span, with an organisation mentioned for some other reason ===
    dict(
        id="v16", split="validation", doc_id="D29",
        document=_doc(
            "Delivery Note #2206.",
            [buyer(), ship_via("Silverline Freight Services")],
            "10 boxes of printer paper",
        ),
        gold=NOT_STATED, probs=[0.14, 0.14, 0.72],
    ),
    dict(
        id="v17", split="validation", doc_id="D30",
        document=_doc(
            "Delivery Note #2207.",
            [buyer("Finance Department"), bank_proc("Harbor Point Bank")],
            "6 replacement toner cartridges",
        ),
        gold=NOT_STATED, probs=[0.15, 0.20, 0.65],
    ),
    dict(
        id="v18", split="validation", doc_id="D31",
        document=_doc(
            "Delivery Note #2208.",
            [
                buyer(),
                ship_from("Bluewave Logistics", "the regional hub"),
                prior_vendor("Oldfield Industrial Partners"),
            ],
            "15 reams of copy paper",
        ),
        gold=NOT_STATED, probs=[0.12, 0.13, 0.11, 0.64],
    ),
    dict(
        id="t14", split="test", doc_id="D32",
        document=_doc(
            "Delivery Note #2209.",
            [buyer("Operations"), ship_via("Crestline Overnight Shipping")],
            "2 external monitors",
        ),
        gold=NOT_STATED, probs=[0.16, 0.16, 0.68],
    ),
    dict(
        id="t15", split="test", doc_id="D33",
        document=_doc(
            "Delivery Note #2210.",
            [buyer(), bank_proc("Union Crest Bank")],
            "2 staplers and a box of highlighters",
        ),
        gold=NOT_STATED, probs=[0.17, 0.17, 0.66],
    ),
    dict(
        id="t16", split="test", doc_id="D34",
        document=_doc(
            "Delivery Note #2211.",
            [
                buyer(),
                ship_via("Starling Courier Services"),
                prior_vendor("Spruceview Supplies Group"),
            ],
            "4 reams of copy paper and a box of binder clips",
        ),
        gold=NOT_STATED, probs=[0.13, 0.12, 0.11, 0.64],
    ),
    # === no organisation mentioned at all: Python short-circuits, no request at all ===
    dict(
        id="v19", split="validation", doc_id="D35",
        document="Delivery Note #2212. Contents: 4 reams of copy paper and a box of binder "
        "clips. No further details were provided with this shipment.",
        gold=NOT_STATED, probs=None,
    ),
    dict(
        id="t17", split="test", doc_id="D36",
        document="Delivery Note #2213. Contents: 2 staplers and a box of highlighters. The "
        "packing slip included no vendor information.",
        gold=NOT_STATED, probs=None,
    ),
    # === the wrong, confident answers: spread across different positions, not only s1 ===
    # v20: two plausible organisations, gold at s2 (vendor on file), the stored answer wrongly
    # and confidently names the s1 decoy -- this is validation's one wrong, named, confident
    # answer, which the frozen threshold is chosen to exclude.
    dict(
        id="v20", split="validation", doc_id="D37",
        document=_doc(
            "Order Summary #5135.",
            [
                ship_from("Silverline Freight Services", "Reno"),
                vendor_on_file("Ember Stationery Co.", "Unit 12, Fairview Industrial Park"),
            ],
            "20 boxes of printer paper",
        ),
        gold="Ember Stationery Co.", probs=[0.74, 0.18, 0.08],
    ),
    # t18: a near-miss superseded vendor at s1, the real supplier at s2 -- the stored answer
    # wrongly and confidently names the superseded vendor (s1), comfortably above the frozen
    # threshold, so this is the one the gate does not catch.
    dict(
        id="t18", split="test", doc_id="D38",
        document=_doc(
            "Order Summary #5136.",
            [
                prior_vendor("Brookstone Textiles"),
                bare_supplier("Amberline Textiles Co.", "18 Spindle Street"),
            ],
            "60 yards of upholstery fabric",
        ),
        gold="Amberline Textiles Co.", probs=[0.80, 0.14, 0.06],
    ),
    # t19: three candidates, gold at s3 (last); the stored answer wrongly, confidently names
    # the s2 decoy instead -- a wrong answer that does NOT pick the first span.
    dict(
        id="t19", split="test", doc_id="D39",
        document=_doc(
            "Order Summary #5137.",
            [
                buyer(),
                bank_proc("Union Crest Bank"),
                bare_supplier("Redstone Analytics Inc.", "2 Meridian Court"),
            ],
            "Data pipeline consulting retainer",
        ),
        gold="Redstone Analytics Inc.", probs=[0.06, 0.70, 0.14, 0.10],
    ),
    # t20: wrong and low-confidence (the gate catches this one): gold at s2 of 2, the stored
    # answer barely prefers the s1 decoy.
    dict(
        id="t20", split="test", doc_id="D40",
        document=_doc(
            "Order Summary #5138.",
            [
                bank_proc("Harbor Point Bank"),
                vendor_on_file("Westgate Manufacturing Co.", "19 Foundry Lane"),
            ],
            "8 steel shelving units",
        ),
        gold="Westgate Manufacturing Co.", probs=[0.42, 0.38, 0.20],
    ),
    # t21: a real supplier is named (bare, no cue), but the stored answer wrongly, confidently
    # says not_stated anyway -- not_stated is never gated on confidence, so nothing catches it.
    dict(
        id="t21", split="test", doc_id="D41",
        document=_doc(
            "Order Summary #5139.",
            [buyer("Facilities"), bare_supplier("Pinehollow Office Supply", "31 Birch Lane")],
            "6 boxes of sticky notes",
        ),
        gold="Pinehollow Office Supply", probs=[0.12, 0.20, 0.68],
    ),
    # === demo (never scored) ===
    dict(
        id="d01-clear", split="demo", doc_id="D-DEMO1",
        document=_doc(
            "Purchase Confirmation #9001.",
            [buyer(), labeled_supplier("Hollow Creek Builders Supply", "10 Timber Lane")],
            "25 sheets of plywood",
        ),
        gold=None, probs=[0.05, 0.86, 0.09],
    ),
    dict(
        id="d02-no-candidates", split="demo", doc_id="D-DEMO2",
        document="Delivery Note #9002. Contents: 2 staplers and a box of highlighters. The "
        "packing slip included no vendor information.",
        gold=None, probs=None,
    ),
]  # fmt: skip


def _fields(row: dict) -> dict:
    return {"doc_id": row["doc_id"], "document": row["document"]}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded. A document
    with no candidate spans (``probs is None``) gets empty ``replay_keys``: Python decides
    ``not_stated`` for it without ever asking a question."""
    inputs, labels = [], []
    for row in rows:
        fields = _fields(row)
        spans = helpers.extract_spans(row["document"])
        if spans:
            questions = helpers.build_questions(fields)
            key = replay_key(helpers.build_state(fields), questions)
            replay_keys = [key]
        else:
            replay_keys = []
        inputs.append(
            {"id": row["id"], "split": row["split"], "fields": fields, "replay_keys": replay_keys}
        )
        if row["gold"] is not None:
            labels.append({"id": row["id"], "label": row["gold"]})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response. A document with no candidate
    spans contributes nothing here -- there is no question to answer."""
    responses = {}
    for row in rows:
        if row["probs"] is None:
            continue
        fields = _fields(row)
        questions = helpers.build_questions(fields)
        key = replay_key(helpers.build_state(fields), questions)
        options = list(questions["supplier_span"].criteria)
        probs = dict(zip(options, row["probs"], strict=True))
        answer = ChoiceAnswer.from_probabilities(probs, Provenance.synthetic())
        responses[key] = DecisionResult({"supplier_span": answer}, "synthetic").to_dict()
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
