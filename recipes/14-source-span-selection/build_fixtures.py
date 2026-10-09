"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 14.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response here is synthetic: written by hand as probabilities, not produced by a model.
Some are deliberately wrong, including one in ``validation`` and two in ``test`` (one confident,
one not), so the evaluation in the notebook has something to find. The replay keys come from the
same ``build_state`` and ``build_questions`` the notebook uses, and the span offsets come from
locating each candidate sentence inside its document, so a typo in ``ROWS`` cannot silently
produce the wrong slice.

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
NOT_STATED = helpers.NOT_STATED

# Each row is one fabricated document: an id, its split, a bookkeeping doc_id, the full document
# text, the candidate sentences Python "extracts" from it (in the order they appear -- the first
# becomes option s1, the second s2, and so on), the gold label (the exact supplier name as it
# appears in the document, or NOT_STATED for a document that does not name one; None for a demo
# row, which carries no label at all), and the stored probabilities over every option Python
# built for this document (its span ids plus "not_stated"), written by hand.
#
# Hard cases this recipe's build notes and issue name: a document with two plausible
# organisations (v06-v08, t05-t07, t17, v19 -- a shipping carrier, a bank, or a decoy the stored
# answer sometimes picks over the real vendor); a near-miss span naming an organisation in a
# clearly superseded role (v09-v11, t08-t09, t18, d02 -- "the previous supplier", same topic,
# does not support the current claim); a document where the supplier's name appears in two
# different spans (v12-v13, t10-t11); and a document with no supporting span at all, with or
# without an organisation mentioned for some other reason (v14-v17, t12-t15).
ROWS = [
    # -- straightforward: one clear "Supplier:" span, one harmless "Bill To:" decoy --
    dict(
        id="v01", split="validation", doc_id="D01",
        document=(
            "Purchase Confirmation #4410. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Supplier: Meridian Office Supplies Inc., 18 Birch Lane. Items: 12 cartons of copy "
            "paper, 6 boxes of binder clips. Thank you for your order."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Supplier: Meridian Office Supplies Inc., 18 Birch Lane.",
        ],
        gold="Meridian Office Supplies Inc.",
        probs={"s1": 0.05, "s2": 0.85, "not_stated": 0.10},
    ),
    dict(
        id="v02", split="validation", doc_id="D02",
        document=(
            "Purchase Confirmation #4411. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Supplier: Northwind Trading LLC, 92 Elm Street. Items: 4 reams of cardstock. "
            "Thank you for your order."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Supplier: Northwind Trading LLC, 92 Elm Street.",
        ],
        gold="Northwind Trading LLC",
        probs={"s1": 0.04, "s2": 0.88, "not_stated": 0.08},
    ),
    dict(
        id="v03", split="validation", doc_id="D03",
        document=(
            "Purchase Confirmation #4412. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Supplier: Acme Industrial Partners, 7 Foundry Road. Items: 2 pallets of steel "
            "brackets. Thank you for your order."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Supplier: Acme Industrial Partners, 7 Foundry Road.",
        ],
        gold="Acme Industrial Partners",
        probs={"s1": 0.06, "s2": 0.80, "not_stated": 0.14},
    ),
    dict(
        id="v04", split="validation", doc_id="D04",
        document=(
            "Order Summary #5120. Bill To: Keystone Retail Group, Finance Department. "
            "Supplier: Oakridge Software Solutions, Suite 220, Riverside Plaza. Items: Annual "
            "license renewal for inventory software. Thank you for your business."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, Finance Department.",
            "Supplier: Oakridge Software Solutions, Suite 220, Riverside Plaza.",
        ],
        gold="Oakridge Software Solutions",
        probs={"s1": 0.03, "s2": 0.91, "not_stated": 0.06},
    ),
    dict(
        id="v05", split="validation", doc_id="D05",
        document=(
            "Order Summary #5121. Bill To: Keystone Retail Group, Finance Department. "
            "Supplier: Cobalt Analytics LLC, 14 Meridian Court. Items: Quarterly reporting "
            "dashboard subscription. Thank you for your business."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, Finance Department.",
            "Supplier: Cobalt Analytics LLC, 14 Meridian Court.",
        ],
        gold="Cobalt Analytics LLC",
        probs={"s1": 0.05, "s2": 0.83, "not_stated": 0.12},
    ),
    # -- hard case: two plausible organisations (a shipper or a bank, against the real vendor) --
    dict(
        id="v06", split="validation", doc_id="D12",
        document=(
            "Order Summary #5125. Remit any billing questions to Harbor Point Bank, our "
            "processing partner. Vendor on file: Copperfield Supplies LLC, 9 Lantern Street. "
            "Items: 100 reams of letterhead."
        ),
        span_texts=[
            "Remit any billing questions to Harbor Point Bank, our processing partner.",
            "Vendor on file: Copperfield Supplies LLC, 9 Lantern Street.",
        ],
        gold="Copperfield Supplies LLC",
        probs={"s1": 0.14, "s2": 0.76, "not_stated": 0.10},
    ),
    dict(
        id="v07", split="validation", doc_id="D13",
        document=(
            "Delivery Note #2201. Delivered by Starling Courier Services from the regional "
            "hub. Vendor on file: Bluepeak Packaging Co., 44 Kiln Street. Items: 200 "
            "corrugated boxes."
        ),
        span_texts=[
            "Delivered by Starling Courier Services from the regional hub.",
            "Vendor on file: Bluepeak Packaging Co., 44 Kiln Street.",
        ],
        gold="Bluepeak Packaging Co.",
        probs={"s1": 0.20, "s2": 0.70, "not_stated": 0.10},
    ),
    dict(
        id="v08", split="validation", doc_id="D14",
        document=(
            "Order Summary #5126. Payment processing handled by Union Crest Bank on behalf "
            "of the account. Vendor on file: Falcon Ridge Chemicals Inc., 3 Foundry Court. "
            "Items: 40 liters of degreaser solution."
        ),
        span_texts=[
            "Payment processing handled by Union Crest Bank on behalf of the account.",
            "Vendor on file: Falcon Ridge Chemicals Inc., 3 Foundry Court.",
        ],
        gold="Falcon Ridge Chemicals Inc.",
        probs={"s1": 0.22, "s2": 0.68, "not_stated": 0.10},
    ),
    # -- hard case: near-miss, a superseded vendor named in the same breath as the real one --
    dict(
        id="v09", split="validation", doc_id="D18",
        document=(
            "Order Summary #5129. We previously ordered packaging from Driftlane Supplies "
            "Co., but switched vendors last quarter. This shipment was supplied by Vellum & "
            "Co. Printing, Unit 4, Brookfield Business Park. Items: 500 printed brochures."
        ),
        span_texts=[
            "We previously ordered packaging from Driftlane Supplies Co., but switched "
            "vendors last quarter.",
            "This shipment was supplied by Vellum & Co. Printing, Unit 4, Brookfield "
            "Business Park.",
        ],
        gold="Vellum & Co. Printing",
        probs={"s1": 0.10, "s2": 0.81, "not_stated": 0.09},
    ),
    dict(
        id="v10", split="validation", doc_id="D19",
        document=(
            "Order Summary #5130. Oldfield Industrial Partners handled this account until "
            "last year, when the contract moved elsewhere. Clearwater Analytics now supplies "
            "the reporting platform under the new agreement, based at 9 Meridian Row. Items: "
            "Annual platform subscription."
        ),
        span_texts=[
            "Oldfield Industrial Partners handled this account until last year, when the "
            "contract moved elsewhere.",
            "Clearwater Analytics now supplies the reporting platform under the new "
            "agreement, based at 9 Meridian Row.",
        ],
        gold="Clearwater Analytics",
        probs={"s1": 0.13, "s2": 0.77, "not_stated": 0.10},
    ),
    dict(
        id="v11", split="validation", doc_id="D20",
        document=(
            "Order Summary #5131. Riverside Packaging Co. was our packaging vendor through "
            "the end of last year. Timberline Office Goods has supplied all packaging "
            "materials since the switch, from 15 Crestwood Lane. Items: 300 shipping cartons."
        ),
        span_texts=[
            "Riverside Packaging Co. was our packaging vendor through the end of last year.",
            "Timberline Office Goods has supplied all packaging materials since the switch, "
            "from 15 Crestwood Lane.",
        ],
        gold="Timberline Office Goods",
        probs={"s1": 0.18, "s2": 0.72, "not_stated": 0.10},
    ),
    # -- hard case: the supplier's name appears in two different spans --
    dict(
        id="v12", split="validation", doc_id="D23",
        document=(
            "This delivery was prepared by Brightwell Hardware Inc., our supplier of "
            "fasteners and tools. Please remit payment to Brightwell Hardware Inc., Accounts "
            "Receivable, 55 Industrial Way. Items: 12 boxes of wood screws."
        ),
        span_texts=[
            "This delivery was prepared by Brightwell Hardware Inc., our supplier of "
            "fasteners and tools.",
            "Please remit payment to Brightwell Hardware Inc., Accounts Receivable, 55 "
            "Industrial Way.",
        ],
        gold="Brightwell Hardware Inc.",
        probs={"s1": 0.20, "s2": 0.70, "not_stated": 0.10},
    ),
    dict(
        id="v13", split="validation", doc_id="D24",
        document=(
            "This project was produced by Driftwood Media Group, our supplier of video "
            "content. Please remit payment to Driftwood Media Group, Billing Department, 70 "
            "Studio Way. Items: Quarterly promotional video package."
        ),
        span_texts=[
            "This project was produced by Driftwood Media Group, our supplier of video "
            "content.",
            "Please remit payment to Driftwood Media Group, Billing Department, 70 Studio "
            "Way.",
        ],
        gold="Driftwood Media Group",
        probs={"s1": 0.68, "s2": 0.22, "not_stated": 0.10},
    ),
    # -- hard case: no supporting span, with an organisation mentioned for some other reason --
    dict(
        id="v14", split="validation", doc_id="D27",
        document=(
            "Delivery Note #2204. Bill To: Keystone Retail Group, 400 Commerce Ave. Shipped "
            "via Silverline Freight Services overnight. Contents: 10 boxes of printer paper."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Shipped via Silverline Freight Services overnight.",
        ],
        gold=NOT_STATED,
        probs={"s1": 0.14, "s2": 0.14, "not_stated": 0.72},
    ),
    dict(
        id="v15", split="validation", doc_id="D28",
        document=(
            "Delivery Note #2205. Bill To: Keystone Retail Group, Finance Department. "
            "Payment processing handled by Harbor Point Bank. Contents: 6 replacement toner "
            "cartridges."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, Finance Department.",
            "Payment processing handled by Harbor Point Bank.",
        ],
        gold=NOT_STATED,
        probs={"s1": 0.15, "s2": 0.20, "not_stated": 0.65},
    ),
    dict(
        id="v16", split="validation", doc_id="D29",
        document=(
            "Delivery Note #2206. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Delivered by Starling Courier Services from the regional hub. Contents: 3 "
            "replacement keyboards."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Delivered by Starling Courier Services from the regional hub.",
        ],
        gold=NOT_STATED,
        probs={"s1": 0.12, "s2": 0.18, "not_stated": 0.70},
    ),
    # -- hard case: no organisation mentioned at all, so there is nothing to extract --
    dict(
        id="v17", split="validation", doc_id="D33",
        document=(
            "Delivery Note #2209. Contents: 4 reams of copy paper and a box of binder clips. "
            "No further details were provided with this shipment."
        ),
        span_texts=[],
        gold=NOT_STATED,
        probs={"not_stated": 1.0},
    ),
    dict(
        id="v18", split="validation", doc_id="D10",
        document=(
            "Order Summary #5123. Bill To: Keystone Retail Group, Operations. Supplier: "
            "Larkspur Consulting LLC, 5 Crown Court. Items: Process audit engagement. Thank "
            "you for your business."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, Operations.",
            "Supplier: Larkspur Consulting LLC, 5 Crown Court.",
        ],
        gold="Larkspur Consulting LLC",
        probs={"s1": 0.04, "s2": 0.87, "not_stated": 0.09},
    ),
    # -- the one wrong, confident answer validation's threshold is chosen to exclude --
    dict(
        id="v19", split="validation", doc_id="D11",
        document=(
            "Order Summary #5124. Goods ship from the Silverline Freight Services depot in "
            "Reno. Vendor on file: Ember & Co. Stationery, Unit 12, Fairview Industrial Park. "
            "Items: 20 boxes of printer paper."
        ),
        span_texts=[
            "Goods ship from the Silverline Freight Services depot in Reno.",
            "Vendor on file: Ember & Co. Stationery, Unit 12, Fairview Industrial Park.",
        ],
        gold="Ember & Co. Stationery",
        probs={"s1": 0.74, "s2": 0.18, "not_stated": 0.08},
    ),
    # ================================ test ================================
    dict(
        id="t01", split="test", doc_id="D06",
        document=(
            "Purchase Confirmation #4413. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Supplier: Meadowbrook Textiles Ltd., 61 Mill Road. Items: 30 yards of canvas "
            "fabric. Thank you for your order."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Supplier: Meadowbrook Textiles Ltd., 61 Mill Road.",
        ],
        gold="Meadowbrook Textiles Ltd.",
        probs={"s1": 0.05, "s2": 0.84, "not_stated": 0.11},
    ),
    dict(
        id="t02", split="test", doc_id="D07",
        document=(
            "Purchase Confirmation #4414. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Supplier: Pinecrest Electronics Inc., 200 Circuit Drive. Items: 15 surge "
            "protectors. Thank you for your order."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Supplier: Pinecrest Electronics Inc., 200 Circuit Drive.",
        ],
        gold="Pinecrest Electronics Inc.",
        probs={"s1": 0.03, "s2": 0.90, "not_stated": 0.07},
    ),
    dict(
        id="t03", split="test", doc_id="D08",
        document=(
            "Order Summary #5122. Bill To: Keystone Retail Group, Risk Management. Supplier: "
            "Thornfield Insurance Group, 8 Harbor Square. Items: Annual liability policy "
            "renewal. Thank you for your business."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, Risk Management.",
            "Supplier: Thornfield Insurance Group, 8 Harbor Square.",
        ],
        gold="Thornfield Insurance Group",
        probs={"s1": 0.06, "s2": 0.78, "not_stated": 0.16},
    ),
    dict(
        id="t04", split="test", doc_id="D09",
        document=(
            "Purchase Confirmation #4415. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Supplier: Westgate Manufacturing Co., 19 Foundry Lane. Items: 8 steel shelving "
            "units. Thank you for your order."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Supplier: Westgate Manufacturing Co., 19 Foundry Lane.",
        ],
        gold="Westgate Manufacturing Co.",
        probs={"s1": 0.10, "s2": 0.62, "not_stated": 0.28},
    ),
    dict(
        id="t05", split="test", doc_id="D15",
        document=(
            "Delivery Note #2202. Shipped overnight via Crestline Overnight Shipping from "
            "the Denver hub. Vendor on file: Ironwood Fasteners Inc., 12 Anvil Lane. Items: "
            "500 steel bolts."
        ),
        span_texts=[
            "Shipped overnight via Crestline Overnight Shipping from the Denver hub.",
            "Vendor on file: Ironwood Fasteners Inc., 12 Anvil Lane.",
        ],
        gold="Ironwood Fasteners Inc.",
        probs={"s1": 0.18, "s2": 0.72, "not_stated": 0.10},
    ),
    dict(
        id="t06", split="test", doc_id="D16",
        document=(
            "Order Summary #5127. Goods ship from the Bluewave Logistics regional "
            "warehouse. Vendor on file: Maplewood Office Interiors, 6 Cedar Row. Items: 3 "
            "reception desks."
        ),
        span_texts=[
            "Goods ship from the Bluewave Logistics regional warehouse.",
            "Vendor on file: Maplewood Office Interiors, 6 Cedar Row.",
        ],
        gold="Maplewood Office Interiors",
        probs={"s1": 0.21, "s2": 0.69, "not_stated": 0.10},
    ),
    # -- wrong, but not confident enough to clear the frozen threshold: the gate catches it --
    dict(
        id="t07", split="test", doc_id="D17",
        document=(
            "Order Summary #5128. Payment processing handled by Harbor Point Bank on behalf "
            "of the account. Vendor on file: Redstone Analytics Inc., 2 Meridian Court. "
            "Items: Data pipeline consulting retainer."
        ),
        span_texts=[
            "Payment processing handled by Harbor Point Bank on behalf of the account.",
            "Vendor on file: Redstone Analytics Inc., 2 Meridian Court.",
        ],
        gold="Redstone Analytics Inc.",
        probs={"s1": 0.42, "s2": 0.38, "not_stated": 0.20},
    ),
    dict(
        id="t08", split="test", doc_id="D21",
        document=(
            "Delivery Note #2203. Elmwood Paper Co. filled this kind of order before the "
            "account was reassigned. Cinderwood Paper Mills has been the supplier of record "
            "since the reassignment, located at 21 Millrace Road. Items: 40 reams of "
            "cardstock."
        ),
        span_texts=[
            "Elmwood Paper Co. filled this kind of order before the account was reassigned.",
            "Cinderwood Paper Mills has been the supplier of record since the reassignment, "
            "located at 21 Millrace Road.",
        ],
        gold="Cinderwood Paper Mills",
        probs={"s1": 0.17, "s2": 0.73, "not_stated": 0.10},
    ),
    # -- wrong, and confident enough to clear the frozen threshold anyway --
    dict(
        id="t09", split="test", doc_id="D22",
        document=(
            "Order Summary #5132. Brookstone Textiles supplied this fabric line until the "
            "switch earlier this year. Amberline Textiles Co. has been the vendor of record "
            "since then, based at 18 Spindle Street. Items: 60 yards of upholstery fabric."
        ),
        span_texts=[
            "Brookstone Textiles supplied this fabric line until the switch earlier this "
            "year.",
            "Amberline Textiles Co. has been the vendor of record since then, based at 18 "
            "Spindle Street.",
        ],
        gold="Amberline Textiles Co.",
        probs={"s1": 0.80, "s2": 0.14, "not_stated": 0.06},
    ),
    dict(
        id="t10", split="test", doc_id="D25",
        document=(
            "This shipment was prepared by Fernwood Paper Mills, our supplier of printing "
            "stock. Please remit payment to Fernwood Paper Mills, Accounts Receivable, 88 "
            "Pulp Street. Items: 25 reams of glossy paper."
        ),
        span_texts=[
            "This shipment was prepared by Fernwood Paper Mills, our supplier of printing "
            "stock.",
            "Please remit payment to Fernwood Paper Mills, Accounts Receivable, 88 Pulp "
            "Street.",
        ],
        gold="Fernwood Paper Mills",
        probs={"s1": 0.15, "s2": 0.75, "not_stated": 0.10},
    ),
    dict(
        id="t11", split="test", doc_id="D26",
        document=(
            "This engagement was staffed by BrightPath Consulting Group, our supplier of "
            "advisory services. Please remit payment to BrightPath Consulting Group, Finance "
            "Office, 5 Summit Plaza. Items: Strategic planning workshop."
        ),
        span_texts=[
            "This engagement was staffed by BrightPath Consulting Group, our supplier of "
            "advisory services.",
            "Please remit payment to BrightPath Consulting Group, Finance Office, 5 Summit "
            "Plaza.",
        ],
        gold="BrightPath Consulting Group",
        probs={"s1": 0.66, "s2": 0.24, "not_stated": 0.10},
    ),
    dict(
        id="t12", split="test", doc_id="D30",
        document=(
            "Delivery Note #2207. Bill To: Keystone Retail Group, Operations. Shipped via "
            "Crestline Overnight Shipping. Contents: 2 external monitors."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, Operations.",
            "Shipped via Crestline Overnight Shipping.",
        ],
        gold=NOT_STATED,
        probs={"s1": 0.16, "s2": 0.16, "not_stated": 0.68},
    ),
    dict(
        id="t13", split="test", doc_id="D31",
        document=(
            "Delivery Note #2208. Bill To: Keystone Retail Group, 400 Commerce Ave. Goods "
            "ship from the Bluewave Logistics regional warehouse. Contents: 15 reams of copy "
            "paper."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Goods ship from the Bluewave Logistics regional warehouse.",
        ],
        gold=NOT_STATED,
        probs={"s1": 0.17, "s2": 0.17, "not_stated": 0.66},
    ),
    # -- wrong the other way: a real supplier is named, but the stored answer says not_stated
    # anyway; not_stated is never gated on confidence, so nothing catches this one --
    dict(
        id="t14", split="test", doc_id="D32",
        document=(
            "Order Summary #5133. Bill To: Keystone Retail Group, Facilities. This order was "
            "fulfilled by Ashgrove Fixtures Co. of 9 Lattice Row. Items: 4 display shelving "
            "units."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, Facilities.",
            "This order was fulfilled by Ashgrove Fixtures Co. of 9 Lattice Row.",
        ],
        gold="Ashgrove Fixtures Co.",
        probs={"s1": 0.12, "s2": 0.20, "not_stated": 0.68},
    ),
    dict(
        id="t15", split="test", doc_id="D34",
        document=(
            "Delivery Note #2210. Contents: 2 staplers and a box of highlighters. The "
            "packing slip included no vendor information."
        ),
        span_texts=[],
        gold=NOT_STATED,
        probs={"not_stated": 1.0},
    ),
    dict(
        id="t16", split="test", doc_id="D35",
        document=(
            "Purchase Confirmation #4421. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Supplier: Pinehollow Office Supply, 31 Birch Lane. Items: 6 boxes of sticky "
            "notes. Thank you for your order."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Supplier: Pinehollow Office Supply, 31 Birch Lane.",
        ],
        gold="Pinehollow Office Supply",
        probs={"s1": 0.05, "s2": 0.85, "not_stated": 0.10},
    ),
    dict(
        id="t17", split="test", doc_id="D36",
        document=(
            "Order Summary #5134. Goods ship from the Silverline Freight Services depot in "
            "Tulsa. Vendor on file: Marrow Creek Chemicals Inc., 14 Foundry Row. Items: 30 "
            "liters of solvent."
        ),
        span_texts=[
            "Goods ship from the Silverline Freight Services depot in Tulsa.",
            "Vendor on file: Marrow Creek Chemicals Inc., 14 Foundry Row.",
        ],
        gold="Marrow Creek Chemicals Inc.",
        probs={"s1": 0.19, "s2": 0.71, "not_stated": 0.10},
    ),
    dict(
        id="t18", split="test", doc_id="D37",
        document=(
            "Delivery Note #2211. Spruceview Supplies Co. handled this account before the "
            "contract was reassigned. Hazelwood Fixtures Inc. has supplied these fixtures "
            "since the reassignment, located at 7 Birchwood Lane. Items: 10 cabinet handle "
            "sets."
        ),
        span_texts=[
            "Spruceview Supplies Co. handled this account before the contract was "
            "reassigned.",
            "Hazelwood Fixtures Inc. has supplied these fixtures since the reassignment, "
            "located at 7 Birchwood Lane.",
        ],
        gold="Hazelwood Fixtures Inc.",
        probs={"s1": 0.15, "s2": 0.75, "not_stated": 0.10},
    ),
    dict(
        id="t19", split="test", doc_id="D38",
        document=(
            "Purchase Confirmation #4422. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Supplier: Stonebridge Electronics, 77 Circuit Row. Items: 10 network switches. "
            "Thank you for your order."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Supplier: Stonebridge Electronics, 77 Circuit Row.",
        ],
        gold="Stonebridge Electronics",
        probs={"s1": 0.04, "s2": 0.89, "not_stated": 0.07},
    ),
    # ================================ demo (never scored) ================================
    dict(
        id="d01-clear", split="demo", doc_id="D-DEMO1",
        document=(
            "Purchase Confirmation #9001. Bill To: Keystone Retail Group, 400 Commerce Ave. "
            "Supplier: Granite Hardware Supply, 3 Anvil Row. Items: 50 boxes of wood screws. "
            "Thank you for your order."
        ),
        span_texts=[
            "Bill To: Keystone Retail Group, 400 Commerce Ave.",
            "Supplier: Granite Hardware Supply, 3 Anvil Row.",
        ],
        gold=None,
        probs={"s1": 0.05, "s2": 0.86, "not_stated": 0.09},
    ),
    dict(
        id="d02-near-miss-wrong", split="demo", doc_id="D-DEMO2",
        document=(
            "Delivery Note #9002. Pinehurst Trading Co. handled this kind of delivery under "
            "the previous contract. Hollow Creek Builders Supply has been the supplier since "
            "the new agreement took effect, located at 10 Timber Lane. Items: 25 sheets of "
            "plywood."
        ),
        span_texts=[
            "Pinehurst Trading Co. handled this kind of delivery under the previous "
            "contract.",
            "Hollow Creek Builders Supply has been the supplier since the new agreement "
            "took effect, located at 10 Timber Lane.",
        ],
        gold=None,
        probs={"s1": 0.72, "s2": 0.20, "not_stated": 0.08},
    ),
]  # fmt: skip


def _spans(document: str, texts: list[str]) -> list[dict]:
    """``[{"id": "s1", "start": ..., "end": ...}, ...]`` -- one entry per candidate sentence
    in ``texts``, located inside ``document`` in order, so a typo in a span's text raises
    ``ValueError`` here (from ``str.index``) instead of silently drifting from the document."""
    spans = []
    cursor = 0
    for i, text in enumerate(texts, start=1):
        start = document.index(text, cursor)
        end = start + len(text)
        spans.append({"id": f"s{i}", "start": start, "end": end})
        cursor = end
    return spans


def _fields(row: dict) -> dict:
    return {
        "doc_id": row["doc_id"],
        "document": row["document"],
        "spans": _spans(row["document"], row["span_texts"]),
    }


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for row in rows:
        fields = _fields(row)
        questions = helpers.build_questions(fields)
        key = replay_key(helpers.build_state(fields), questions)
        inputs.append(
            {"id": row["id"], "split": row["split"], "fields": fields, "replay_keys": [key]}
        )
        if row["gold"] is not None:
            labels.append({"id": row["id"], "label": row["gold"]})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for row in rows:
        fields = _fields(row)
        questions = helpers.build_questions(fields)
        key = replay_key(helpers.build_state(fields), questions)
        options = list(questions["supplier_span"].criteria)
        probs = {option: row["probs"][option] for option in options}
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
