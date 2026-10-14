"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 44.

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

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()


def _fields(
    *,
    budget_limit,
    cost,
    deadline,
    completion,
    approved_vendors,
    used_vendor,
    data_scope,
    data_note,
    steps,
):
    """One plan's ``fields``: the user's four constraint statements (the concrete limit,
    deadline, vendor list and data scope baked into each), the plan's own description built
    from ``steps`` plus its stated cost, completion date, vendor and data-handling note, and
    ``cost`` on its own -- the only numeric fact Python reads back out, for the stateful
    walkthrough's running-budget bookkeeping (never read a second time by the model)."""
    return {
        "user_constraints": {
            helpers.BUDGET: f"Budget constraint: total plan cost must not exceed ${budget_limit}.",
            helpers.TIMELINE: f"Timeline constraint: every step must be completed by {deadline}.",
            helpers.VENDOR: (
                "Vendor constraint: only these vendors are pre-approved for this task: "
                f"{', '.join(approved_vendors)}."
            ),
            helpers.DATA_HANDLING: (
                "Data handling constraint: the user's personal data may be shared only with "
                f"{data_scope}."
            ),
        },
        "plan": (
            f"{steps} Estimated total cost: ${cost}. Target completion: {completion}. "
            f"Vendor used: {used_vendor}. {data_note}"
        ),
        "cost": cost,
    }


# (id, split, fields, gold label ({"budget", "timeline", "vendor", "data_handling"}: bool, or
# None for a demo example), (stored budget, timeline, vendor, data_handling noul probabilities))
#
# 15 validation + 15 test candidate plans (one request, four Noul propositions, per plan) plus
# 5 demo plans: two shown "up close" and three -- d03, d04, d05 -- a stateful sequence that
# shares one department budget, Python's own running "remaining budget" figure threaded across
# them and baked into each later plan's own budget constraint text before build_state ever
# runs, so the third plan is ineligible purely because the earlier two already spent most of
# the budget, never because of anything new in its own text.
#
# v02-v05 and t02-t05 are this recipe's named hard case in its sharpest single-constraint form:
# each plan satisfies every constraint but one, and is still confidently ineligible for that
# one. v09, v10 and v12 are look-alikes whose plan text reads reassuringly (or urgently) but
# whose stored answer is NOT fooled by it, so the business threshold chosen on validation is
# not itself distorted by a wrong answer; t09, t10, t12 and t13 are the adversarial look-alikes
# proper, where the stored TEST answer IS wrong (a false negative that misses a real violation,
# or a false positive that flags a clean plan), so no constraint's own precision or recall on
# the reported split is saturated by construction -- each of the four constraints has at least
# one real miss on test. v11/t11 are the conflicting pair: the same underlying trade-off (an
# approved vendor costs more, an unapproved one costs less) resolved in opposite directions, so
# budget and vendor genuinely pull against each other rather than always moving together.
# v13/v14 and t14/t15 are the gated, low-confidence pairs -- one where the model's uncertainty
# is cautious (gold is actually clear), one where it is warranted (gold is actually a
# violation) -- that exercise the review path through the confidence gate rather than a
# confident business-rule tag.
ROWS = [
    # -- validation: 15 ------------------------------------------------------------------------
    ("v01", "validation", _fields(
        budget_limit=5000, cost=4200, deadline="March 14", completion="March 10",
        approved_vendors=["Acme Events", "Bright Catering"], used_vendor="Acme Events",
        data_scope="the user's own team",
        data_note="The plan shares the attendee list only with the user's own team for headcount planning.",
        steps="Book Acme Events for the quarterly team offsite, covering venue and catering for 20 people.",
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": False},
       (0.05, 0.04, 0.05, 0.04)),
    ("v02-budget", "validation", _fields(
        budget_limit=3000, cost=4100, deadline="April 20", completion="April 12",
        approved_vendors=["Northwind Travel"], used_vendor="Northwind Travel",
        data_scope="the user's travel coordinator",
        data_note="The plan shares passport numbers only with the user's travel coordinator for booking.",
        steps="Book a 3-day conference trip for two staff through Northwind Travel.",
    ), {"budget": True, "timeline": False, "vendor": False, "data_handling": False},
       (0.90, 0.05, 0.04, 0.05)),
    ("v03-timeline", "validation", _fields(
        budget_limit=8000, cost=6500, deadline="May 1", completion="May 9",
        approved_vendors=["Summit Logistics"], used_vendor="Summit Logistics",
        data_scope="internal facilities staff",
        data_note="The plan shares delivery addresses only with internal facilities staff.",
        steps="Move office furniture to the new floor via Summit Logistics.",
    ), {"budget": False, "timeline": True, "vendor": False, "data_handling": False},
       (0.05, 0.88, 0.05, 0.04)),
    ("v04-vendor", "validation", _fields(
        budget_limit=2500, cost=2100, deadline="June 3", completion="May 28",
        approved_vendors=["Clearview Print", "Keystone Print"], used_vendor="Rapid Print Co",
        data_scope="the print vendor only for the order itself",
        data_note="The plan shares only the brochure artwork file with the print vendor.",
        steps="Print 500 conference brochures through Rapid Print Co.",
    ), {"budget": False, "timeline": False, "vendor": True, "data_handling": False},
       (0.05, 0.04, 0.91, 0.04)),
    ("v05-data", "validation", _fields(
        budget_limit=1200, cost=950, deadline="February 20", completion="February 15",
        approved_vendors=["Harbor Analytics"], used_vendor="Harbor Analytics",
        data_scope="Harbor Analytics' own survey team",
        data_note=(
            "The plan shares the full customer contact list, including phone numbers, with "
            "Harbor Analytics' outside subcontractor for cold calling."
        ),
        steps="Run a customer satisfaction survey through Harbor Analytics.",
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": True},
       (0.04, 0.05, 0.05, 0.89)),
    ("v06-mixed", "validation", _fields(
        budget_limit=4000, cost=5200, deadline="January 10", completion="January 18",
        approved_vendors=["Delta Fit-Out"], used_vendor="Delta Fit-Out",
        data_scope="the facilities team",
        data_note="The plan shares floor plans only with the facilities team.",
        steps="Refit the third-floor meeting rooms via Delta Fit-Out.",
    ), {"budget": True, "timeline": True, "vendor": False, "data_handling": False},
       (0.92, 0.86, 0.05, 0.04)),
    ("v07-mixed", "validation", _fields(
        budget_limit=6000, cost=8800, deadline="September 30", completion="September 25",
        approved_vendors=["Granite Movers"], used_vendor="Swift Relocation",
        data_scope="Granite Movers",
        data_note="The plan shares employee home addresses with Swift Relocation's third-party scheduling app.",
        steps="Relocate the operations team to the new building via Swift Relocation.",
    ), {"budget": True, "timeline": False, "vendor": True, "data_handling": True},
       (0.89, 0.05, 0.93, 0.90)),
    ("v08-allfour", "validation", _fields(
        budget_limit=10000, cost=15500, deadline="November 1", completion="November 15",
        approved_vendors=["Pinnacle AV"], used_vendor="Star AV Rentals",
        data_scope="Pinnacle AV",
        data_note=(
            "The plan shares the full attendee list, including home addresses, with Star AV "
            "Rentals' marketing partner."
        ),
        steps="Outfit the annual conference with staging and AV through Star AV Rentals.",
    ), {"budget": True, "timeline": True, "vendor": True, "data_handling": True},
       (0.95, 0.90, 0.94, 0.93)),
    ("v09-lookalike-budget", "validation", _fields(
        budget_limit=2000, cost=2600, deadline="July 4", completion="June 28",
        approved_vendors=["Lakeside Supplies"], used_vendor="Lakeside Supplies",
        data_scope="Lakeside Supplies",
        data_note="The plan shares only the delivery address with Lakeside Supplies.",
        steps=(
            "Restock the break room supplies through Lakeside Supplies; this stays comfortably "
            "within the usual budget for this kind of order."
        ),
    ), {"budget": True, "timeline": False, "vendor": False, "data_handling": False},
       (0.90, 0.04, 0.05, 0.05)),
    ("v10-lookalike-vendor", "validation", _fields(
        budget_limit=3500, cost=3100, deadline="August 12", completion="August 5",
        approved_vendors=["Crestview Catering"], used_vendor="Crestview Caterers",
        data_scope="the caterer",
        data_note="The plan shares the guest count only with the caterer.",
        steps="Cater the department retreat through Crestview Caterers, our usual catering partner.",
    ), {"budget": False, "timeline": False, "vendor": True, "data_handling": False},
       (0.04, 0.05, 0.90, 0.05)),
    ("v11-conflict", "validation", _fields(
        budget_limit=1500, cost=1350, deadline="October 2", completion="September 29",
        approved_vendors=["Metro Sign Co"], used_vendor="Value Signs Direct",
        data_scope="the sign vendor",
        data_note="The plan shares only the artwork file with the sign vendor.",
        steps=(
            "Order lobby signage through Value Signs Direct instead of Metro Sign Co, to keep "
            "the order inside budget."
        ),
    ), {"budget": False, "timeline": False, "vendor": True, "data_handling": False},
       (0.05, 0.04, 0.90, 0.05)),
    ("v12-lookalike-timeline", "validation", _fields(
        budget_limit=5000, cost=4300, deadline="December 15", completion="December 10",
        approved_vendors=["Apex Repairs"], used_vendor="Apex Repairs",
        data_scope="Apex Repairs",
        data_note="The plan shares only the equipment serial numbers with Apex Repairs.",
        steps=(
            "This is extremely time-critical and must be rushed: repair the HVAC unit through "
            "Apex Repairs well ahead of the deadline."
        ),
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": False},
       (0.05, 0.05, 0.04, 0.05)),
    ("v13-gated-clear", "validation", _fields(
        budget_limit=2200, cost=2150, deadline="March 30", completion="March 22",
        approved_vendors=["Union Freight"], used_vendor="Union Freight",
        data_scope="Union Freight",
        data_note="The plan shares only the shipment manifest with Union Freight.",
        steps=(
            "Ship the trade-show materials through Union Freight; the estimate sits "
            "approximately at the budget limit, with some risk of a small overage depending on "
            "final invoicing."
        ),
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": False},
       (0.52, 0.04, 0.05, 0.05)),
    ("v14-gated-violation", "validation", _fields(
        budget_limit=1800, cost=2050, deadline="May 18", completion="May 14",
        approved_vendors=["Coastal Rentals"], used_vendor="Coastal Rentals",
        data_scope="Coastal Rentals",
        data_note="The plan shares only the delivery window with Coastal Rentals.",
        steps=(
            "Rent tables and chairs for the client event through Coastal Rentals; the final "
            "price depends on a few options still being confirmed."
        ),
    ), {"budget": True, "timeline": False, "vendor": False, "data_handling": False},
       (0.47, 0.04, 0.05, 0.05)),
    ("v15", "validation", _fields(
        budget_limit=9000, cost=7600, deadline="February 28", completion="February 20",
        approved_vendors=["Ridgeline Consulting"], used_vendor="Ridgeline Consulting",
        data_scope="Ridgeline Consulting",
        data_note="The plan shares only the project brief with Ridgeline Consulting.",
        steps="Engage Ridgeline Consulting for the process review.",
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": False},
       (0.05, 0.05, 0.04, 0.04)),
    # -- test: 15 -------------------------------------------------------------------------------
    ("t01", "test", _fields(
        budget_limit=4500, cost=3900, deadline="January 22", completion="January 18",
        approved_vendors=["Brightline Design"], used_vendor="Brightline Design",
        data_scope="Brightline Design",
        data_note="The plan shares only the brand guidelines with Brightline Design.",
        steps="Commission a new brand refresh through Brightline Design.",
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": False},
       (0.04, 0.05, 0.04, 0.05)),
    ("t02-budget", "test", _fields(
        budget_limit=2800, cost=3600, deadline="April 9", completion="April 2",
        approved_vendors=["Union Freight"], used_vendor="Union Freight",
        data_scope="Union Freight",
        data_note="The plan shares only the shipment manifest with Union Freight.",
        steps="Ship replacement equipment to the regional office through Union Freight.",
    ), {"budget": True, "timeline": False, "vendor": False, "data_handling": False},
       (0.92, 0.04, 0.05, 0.05)),
    ("t03-timeline", "test", _fields(
        budget_limit=7000, cost=6100, deadline="June 1", completion="June 11",
        approved_vendors=["Harborview Movers"], used_vendor="Harborview Movers",
        data_scope="Harborview Movers",
        data_note="The plan shares only the new office address with Harborview Movers.",
        steps="Move the regional team to the new office via Harborview Movers.",
    ), {"budget": False, "timeline": True, "vendor": False, "data_handling": False},
       (0.05, 0.89, 0.04, 0.05)),
    ("t04-vendor", "test", _fields(
        budget_limit=2600, cost=2300, deadline="July 15", completion="July 8",
        approved_vendors=["Clearwater Design", "Pixel Forge"], used_vendor="Bright Ideas Studio",
        data_scope="the design vendor",
        data_note="The plan shares only the campaign brief with the design vendor.",
        steps="Design the summer campaign assets through Bright Ideas Studio.",
    ), {"budget": False, "timeline": False, "vendor": True, "data_handling": False},
       (0.04, 0.05, 0.90, 0.05)),
    ("t05-data", "test", _fields(
        budget_limit=1600, cost=1300, deadline="March 5", completion="February 27",
        approved_vendors=["Meridian Research"], used_vendor="Meridian Research",
        data_scope="Meridian Research's internal analysts",
        data_note=(
            "The plan shares the full respondent list, including emails, with Meridian "
            "Research's offshore data-entry contractor."
        ),
        steps="Run a market research survey through Meridian Research.",
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": True},
       (0.05, 0.04, 0.05, 0.91)),
    ("t06-mixed", "test", _fields(
        budget_limit=3200, cost=2700, deadline="August 30", completion="August 20",
        approved_vendors=["Lakeside Supplies"], used_vendor="Rapid Supplies Co",
        data_scope="Lakeside Supplies",
        data_note="The plan shares the warehouse access codes with Rapid Supplies Co.'s subcontractor.",
        steps="Restock the warehouse through Rapid Supplies Co.",
    ), {"budget": False, "timeline": False, "vendor": True, "data_handling": True},
       (0.05, 0.04, 0.90, 0.88)),
    ("t07-mixed", "test", _fields(
        budget_limit=5000, cost=6700, deadline="October 10", completion="October 19",
        approved_vendors=["Northgate Facilities"], used_vendor="Summit Facilities",
        data_scope="Northgate Facilities",
        data_note="The plan shares only the maintenance schedule with Northgate Facilities.",
        steps="Service the HVAC system across two floors through Summit Facilities.",
    ), {"budget": True, "timeline": True, "vendor": True, "data_handling": False},
       (0.90, 0.87, 0.92, 0.05)),
    ("t08-allfour", "test", _fields(
        budget_limit=4000, cost=6200, deadline="December 1", completion="December 12",
        approved_vendors=["Evergreen Catering"], used_vendor="Festive Events Co",
        data_scope="Evergreen Catering",
        data_note=(
            "The plan shares the full guest list, including home addresses, with Festive "
            "Events Co.'s marketing affiliate."
        ),
        steps="Cater the holiday party through Festive Events Co.",
    ), {"budget": True, "timeline": True, "vendor": True, "data_handling": True},
       (0.94, 0.91, 0.93, 0.92)),
    ("t09-adversarial-data", "test", _fields(
        budget_limit=2000, cost=1700, deadline="May 5", completion="April 28",
        approved_vendors=["Sunrise Analytics"], used_vendor="Sunrise Analytics",
        data_scope="Sunrise Analytics' internal team",
        data_note=(
            "The plan states the respondent data stays internal, but the detailed step list "
            "shows the respondent database is exported to an outside call center for follow-up."
        ),
        steps="Run a customer follow-up survey through Sunrise Analytics.",
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": True},
       (0.04, 0.05, 0.05, 0.09)),
    ("t10-adversarial-timeline", "test", _fields(
        budget_limit=3000, cost=2500, deadline="September 1", completion="September 9",
        approved_vendors=["Northgate Facilities"], used_vendor="Delta Fit-Out",
        data_scope="Delta Fit-Out",
        data_note="The plan shares only the floor plan with Delta Fit-Out.",
        steps="Refit the second-floor break room via Delta Fit-Out; this is on track.",
    ), {"budget": False, "timeline": True, "vendor": True, "data_handling": False},
       (0.04, 0.11, 0.90, 0.05)),
    ("t11-conflict", "test", _fields(
        budget_limit=1600, cost=1750, deadline="November 20", completion="November 14",
        approved_vendors=["Metro Sign Co"], used_vendor="Metro Sign Co",
        data_scope="Metro Sign Co",
        data_note="The plan shares only the artwork file with Metro Sign Co.",
        steps=(
            "Order lobby signage through Metro Sign Co, our only pre-approved vendor for this "
            "kind of order, even though it costs more than the off-list alternative."
        ),
    ), {"budget": True, "timeline": False, "vendor": False, "data_handling": False},
       (0.88, 0.04, 0.05, 0.05)),
    ("t12-falsepositive-vendor", "test", _fields(
        budget_limit=2400, cost=2000, deadline="July 1", completion="June 25",
        approved_vendors=["Granite Movers"], used_vendor="Granite Movers",
        data_scope="Granite Movers",
        data_note="The plan shares only the inventory list with Granite Movers.",
        steps=(
            "Move inventory between warehouses through a specialty subcontractor arrangement "
            "with Granite Movers's own in-house team."
        ),
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": False},
       (0.04, 0.05, 0.93, 0.05)),
    ("t13-falsepositive-budget", "test", _fields(
        budget_limit=5000, cost=4200, deadline="February 10", completion="February 3",
        approved_vendors=["Pinnacle AV"], used_vendor="Pinnacle AV",
        data_scope="Pinnacle AV",
        data_note="The plan shares only the equipment list with Pinnacle AV.",
        steps=(
            "Outfit the quarterly town hall through Pinnacle AV; a worst-case contingency "
            "estimate of $5800 is noted in case of last-minute additions."
        ),
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": False},
       (0.78, 0.04, 0.05, 0.05)),
    ("t14-gated-clear", "test", _fields(
        budget_limit=2600, cost=2550, deadline="June 20", completion="June 15",
        approved_vendors=["Union Freight"], used_vendor="Union Freight",
        data_scope="Union Freight",
        data_note="The plan shares only the shipment manifest with Union Freight.",
        steps=(
            "Ship conference materials through Union Freight; the estimate sits approximately "
            "at the budget limit, with final invoicing still pending."
        ),
    ), {"budget": False, "timeline": False, "vendor": False, "data_handling": False},
       (0.50, 0.04, 0.05, 0.05)),
    ("t15-gated-violation", "test", _fields(
        budget_limit=1900, cost=2150, deadline="October 25", completion="October 19",
        approved_vendors=["Coastal Rentals"], used_vendor="Coastal Rentals",
        data_scope="Coastal Rentals",
        data_note="The plan shares only the delivery window with Coastal Rentals.",
        steps=(
            "Rent event furniture through Coastal Rentals; the final price depends on a few "
            "options still being confirmed."
        ),
    ), {"budget": True, "timeline": False, "vendor": False, "data_handling": False},
       (0.49, 0.04, 0.05, 0.05)),
    # -- demo: 5 (never scored) -------------------------------------------------------------
    ("d01-flag", "demo", _fields(
        budget_limit=3000, cost=5200, deadline="April 1", completion="March 25",
        approved_vendors=["Crestline Logistics"], used_vendor="Crestline Logistics",
        data_scope="Crestline Logistics",
        data_note="The plan shares only the delivery schedule with Crestline Logistics.",
        steps="Ship replacement workstations to the satellite office through Crestline Logistics.",
    ), None, (0.93, 0.04, 0.05, 0.04)),
    ("d02-clean", "demo", _fields(
        budget_limit=6000, cost=4800, deadline="May 10", completion="May 2",
        approved_vendors=["Clearview Print"], used_vendor="Clearview Print",
        data_scope="Clearview Print",
        data_note="The plan shares only the brochure artwork with Clearview Print.",
        steps="Print the investor-day handouts through Clearview Print.",
    ), None, (0.04, 0.05, 0.04, 0.05)),
    ("d03-seq1", "demo", _fields(
        budget_limit=5000, cost=3000, deadline="December 31", completion="November 1",
        approved_vendors=["Union Office Supply"], used_vendor="Union Office Supply",
        data_scope="Union Office Supply",
        data_note="The plan shares only the purchase order with Union Office Supply.",
        steps="Order new desks for the growing team through Union Office Supply; first order this quarter.",
    ), None, (0.04, 0.04, 0.04, 0.04)),
    ("d04-seq2", "demo", _fields(
        budget_limit=2000, cost=1500, deadline="December 31", completion="November 20",
        approved_vendors=["Union Office Supply"], used_vendor="Union Office Supply",
        data_scope="Union Office Supply",
        data_note="The plan shares only the purchase order with Union Office Supply.",
        steps="Order monitors for the new desks through Union Office Supply; second order this quarter.",
    ), None, (0.04, 0.04, 0.04, 0.04)),
    ("d05-seq3", "demo", _fields(
        budget_limit=500, cost=1200, deadline="December 31", completion="December 5",
        approved_vendors=["Union Office Supply"], used_vendor="Union Office Supply",
        data_scope="Union Office Supply",
        data_note="The plan shares only the purchase order with Union Office Supply.",
        steps="Order ergonomic chairs through Union Office Supply; third order this quarter.",
    ), None, (0.85, 0.04, 0.04, 0.04)),
]  # fmt: skip


def answers_for(spec, provenance: Provenance):
    """{question name: answer} for one row: four independent NoulAnswer values, one per
    constraint, from the row's ``(budget, timeline, vendor, data_handling)`` probabilities."""
    budget_p, timeline_p, vendor_p, data_p = spec
    return {
        helpers.BUDGET: NoulAnswer(budget_p, provenance),
        helpers.TIMELINE: NoulAnswer(timeline_p, provenance),
        helpers.VENDOR: NoulAnswer(vendor_p, provenance),
        helpers.DATA_HANDLING: NoulAnswer(data_p, provenance),
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
