"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 33.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response here is synthetic: written by hand as probabilities, never produced by a
model. ``ROWS`` groups source fields by ``task_id`` -- a fabricated legacy export batch, two or
three source fields wide -- because the one-to-one constraint ``helpers.apply_one_to_one``
enforces only makes sense within one batch's own set of fields: two different batches describe
two different target-schema instances, so a field from one can never collide with a field from
another. `validation` holds eight batches (16 fields); `test` holds eight more, from a second
regional export of the same legacy system with different column names (16 fields); `demo` holds
one more (3 fields, shown but never scored).

Each split carries this recipe's hard cases, spread across more than one batch so no single
batch has to carry all of them:

- A misleading-name field in most batches: a column whose name suggests one target but whose
  description resolves to another (``customer_id`` -> ``loyalty_tier``, ``total_due`` ->
  ``shipping_country``, ``is_active`` -> ``is_gift_order``, and their `test`-split siblings).
- A genuinely ``unmapped`` field in most batches: a column with no counterpart in the target
  schema at all.
- One batch per split (``batch_v03``/``batch_t03``) where a field's own description is torn
  between two targets, with gold label ``ambiguous``.
- One batch per split (``batch_v04``/``batch_t04``) where the model's choice is semantically
  *right* but the declared type does not match the chosen target's type -- a mistake only
  Python's type check catches, not a confidence gate.
- One batch per split (``batch_v06``/``batch_t06``) with two source fields the model both maps
  to ``shipping_country``: a one-to-one conflict Python's validation is the only thing
  positioned to catch, since each field is judged from its own state alone and never sees its
  sibling column.
- One low-confidence, wrong validation field (``promo_code_applied`` in ``batch_v03``): wrong,
  and unconfident enough that the frozen gate, chosen on `validation`, excludes it -- the
  gate's one genuine validation-side catch, so the threshold selection has to exclude a real
  mistake rather than finding every answer trustworthy by default.
- One confidently wrong `test` field (``sku_note`` in ``batch_t08``): wrong, at a confidence
  this fixture set's correctly-answered fields also reach, with nothing else in its own batch
  under review, so nothing stops that batch from being accepted outright, wrong field and all.
  This is where this recipe's non-zero `test` risk comes from, at both the field level and the
  task level.

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
OPTIONS = list(QUESTIONS["target"].criteria)


def _fields(task_id, field_name, declared_type, description):
    return {
        "task_id": task_id,
        "field_name": field_name,
        "declared_type": declared_type,
        "description": description,
    }


# (id, split, task_id, field_name, declared_type, description, gold label or None for demo, spec)
#
# `spec` is {"choice": <option Jev is stored as answering>, "peak": <top probability>,
# "shares": {<option>: <probability>, ...}}; "choice" and "peak" are always given explicitly --
# never defaulted -- because a bare-float shorthand that filled in "choice" by default would
# silently mislabel every row whose intended choice is not the positive case. "shares" is only
# given for the three `ambiguous` rows, where the remaining probability mass must land on the
# two specific candidates the field's own description is torn between, not spread evenly over
# every option.
ROWS = [
    # ------------------------------- validation: batch_v01 (2 fields) ----------------------------
    (
        "v01", "validation", "batch_v01", "cust_mail", "varchar",
        "The customer's email address, used to send order receipts and account notices.",
        "customer_email", {"choice": "customer_email", "peak": 0.84},
    ),
    (
        "v02", "validation", "batch_v01", "customer_id", "varchar",
        "A short alphanumeric loyalty tier code such as GOLD-1, SILVER-2 or BRONZE-3, assigned "
        "when the customer enrolls in the rewards program. Despite the column's name, this "
        "field has never stored the account's own numeric identifier.",
        "loyalty_tier", {"choice": "loyalty_tier", "peak": 0.82},
    ),
    # ------------------------------- validation: batch_v02 (2 fields) ----------------------------
    (
        "v03", "validation", "batch_v02", "internal_sync_flag", "bool",
        "An internal flag used only by the nightly batch job that reconciles this table "
        "against a separate internal system; it is not an attribute of the customer or the "
        "order, and carries no meaning once the export leaves that job.",
        "unmapped", {"choice": "unmapped", "peak": 0.86},
    ),
    (
        "v04", "validation", "batch_v02", "acct_ref", "int",
        "The internal numeric identifier assigned to the customer account when it was first "
        "created.",
        "customer_id", {"choice": "customer_id", "peak": 0.90},
    ),
    # --------------------------- validation: batch_v03 (2 fields, hard) ---------------------------
    (
        "v05-ambiguous", "validation", "batch_v03", "region_note", "varchar",
        "This column has been used inconsistently by different store locations: in about half "
        "of exports it holds the shipping country for the order, and in the other half it "
        "holds the customer's loyalty-program tier name instead; the export itself does not "
        "say which convention a given row follows.",
        "ambiguous",
        {
            "choice": "ambiguous",
            "peak": 0.40,
            "shares": {"shipping_country": 0.30, "loyalty_tier": 0.30},
        },
    ),
    (
        "v06-wrong", "validation", "batch_v03", "promo_code_applied", "varchar",
        "The stock-keeping unit code identifying the exact product variant most recently "
        "viewed by the customer on the storefront, logged for abandoned-cart follow-up.",
        "product_sku", {"choice": "shipping_country", "peak": 0.50},
    ),
    # --------------------------- validation: batch_v04 (2 fields, hard) ---------------------------
    (
        "v07-type", "validation", "batch_v04", "order_total_code", "varchar",
        "The total monetary amount charged for the order, formatted as a decimal string with "
        "two places after the point.",
        "order_total", {"choice": "order_total", "peak": 0.88},
    ),
    (
        "v08", "validation", "batch_v04", "placed_on", "date",
        "The calendar date the order was placed by the customer.",
        "order_date", {"choice": "order_date", "peak": 0.84},
    ),
    # ------------------------------- validation: batch_v05 (2 fields) ----------------------------
    (
        "v09", "validation", "batch_v05", "wrap_flag", "bool",
        "Whether the customer asked for the order to be wrapped and marked as a gift at "
        "checkout.",
        "is_gift_order", {"choice": "is_gift_order", "peak": 0.80},
    ),
    (
        "v10", "validation", "batch_v05", "sku_code", "varchar",
        "The stock-keeping unit code identifying the exact product variant ordered.",
        "product_sku", {"choice": "product_sku", "peak": 0.86},
    ),
    # --------------------------- validation: batch_v06 (2 fields, conflict) -----------------------
    (
        "v11-conflict", "validation", "batch_v06", "ship_to_cc", "varchar",
        "The two-letter country code the parcel will be shipped to.",
        "shipping_country", {"choice": "shipping_country", "peak": 0.85},
    ),
    (
        "v12-conflict", "validation", "batch_v06", "alt_country_note", "varchar",
        "A duplicate column some orders carry from an old checkout form that also recorded "
        "the shipping country in free text; this export keeps both columns side by side for "
        "orders created before the main field was added.",
        "unmapped", {"choice": "shipping_country", "peak": 0.85},
    ),
    # ------------------------------- validation: batch_v07 (2 fields) ----------------------------
    (
        "v13", "validation", "batch_v07", "member_level", "varchar",
        "The customer's named loyalty-program tier, such as Gold, Silver or Bronze.",
        "loyalty_tier", {"choice": "loyalty_tier", "peak": 0.88},
    ),
    (
        "v14", "validation", "batch_v07", "total_due", "varchar",
        "The three-letter ISO country code the parcel will be shipped to, stored as free "
        "text; the legacy ledger named this column after an older, unrelated billing feature "
        "that was removed years ago.",
        "shipping_country", {"choice": "shipping_country", "peak": 0.82},
    ),
    # ------------------------------- validation: batch_v08 (2 fields) ----------------------------
    (
        "v15", "validation", "batch_v08", "is_active", "bool",
        "Whether the customer asked for the order to be wrapped and marked as a gift at "
        "checkout, a column repurposed from an older membership-status flag of the same name.",
        "is_gift_order", {"choice": "is_gift_order", "peak": 0.90},
    ),
    (
        "v16", "validation", "batch_v08", "ext_ref_code", "varchar",
        "A free-text reference code some regional offices write for their own internal "
        "paperwork; its meaning and format vary by region, and it is not read by any part of "
        "the customer or order record kept in the target schema.",
        "unmapped", {"choice": "unmapped", "peak": 0.84},
    ),
    # ---------------------------------- test: batch_t01 (2 fields) -------------------------------
    (
        "t01", "test", "batch_t01", "mail_addr", "varchar",
        "The customer's email address, used for account contact and order receipts.",
        "customer_email", {"choice": "customer_email", "peak": 0.86},
    ),
    (
        "t02", "test", "batch_t01", "acct_num", "int",
        "The internal numeric identifier assigned to the customer account.",
        "customer_id", {"choice": "customer_id", "peak": 0.82},
    ),
    # ---------------------------------- test: batch_t02 (2 fields) -------------------------------
    (
        "t03", "test", "batch_t02", "status_code", "varchar",
        "A short alphanumeric loyalty tier code such as GOLD-1, SILVER-2 or BRONZE-3, assigned "
        "when the customer enrolls in the rewards program; despite its name, this column has "
        "never stored an account status flag.",
        "loyalty_tier", {"choice": "loyalty_tier", "peak": 0.84},
    ),
    (
        "t04", "test", "batch_t02", "batch_marker", "bool",
        "An internal flag used only by the nightly reconciliation job against a separate "
        "internal system; it is not an attribute of the customer or the order, and carries no "
        "meaning once the export leaves that job.",
        "unmapped", {"choice": "unmapped", "peak": 0.88},
    ),
    # ----------------------------- test: batch_t03 (2 fields, hard) ------------------------------
    (
        "t05-ambiguous", "test", "batch_t03", "pref_region", "varchar",
        "This column has been used inconsistently by different store locations: in some "
        "exports it holds the shipping country for the order, and in others it holds the "
        "customer's loyalty-program tier name instead; the export itself does not say which "
        "convention a given row follows.",
        "ambiguous",
        {
            "choice": "ambiguous",
            "peak": 0.42,
            "shares": {"shipping_country": 0.29, "loyalty_tier": 0.29},
        },
    ),
    (
        "t07", "test", "batch_t03", "order_dt", "date",
        "The calendar date the order was placed by the customer.",
        "order_date", {"choice": "order_date", "peak": 0.80},
    ),
    # ----------------------------- test: batch_t04 (2 fields, hard) ------------------------------
    (
        "t06-type", "test", "batch_t04", "amount_due_txt", "varchar",
        "The total monetary amount charged for the order, formatted as a decimal string with "
        "two places after the point.",
        "order_total", {"choice": "order_total", "peak": 0.90},
    ),
    (
        "t09", "test", "batch_t04", "item_code", "varchar",
        "The stock-keeping unit code identifying the exact product variant ordered.",
        "product_sku", {"choice": "product_sku", "peak": 0.84},
    ),
    # ---------------------------------- test: batch_t05 (2 fields) -------------------------------
    (
        "t08", "test", "batch_t05", "gift_mark", "bool",
        "Whether the customer asked for the order to be wrapped and marked as a gift at "
        "checkout.",
        "is_gift_order", {"choice": "is_gift_order", "peak": 0.86},
    ),
    (
        "t12", "test", "batch_t05", "tier_name", "varchar",
        "The customer's named loyalty-program tier, such as Gold, Silver or Bronze.",
        "loyalty_tier", {"choice": "loyalty_tier", "peak": 0.88},
    ),
    # ----------------------------- test: batch_t06 (2 fields, conflict) --------------------------
    (
        "t10-conflict", "test", "batch_t06", "dest_country", "varchar",
        "The two-letter country code the parcel will be shipped to.",
        "shipping_country", {"choice": "shipping_country", "peak": 0.85},
    ),
    (
        "t11-conflict", "test", "batch_t06", "legacy_country_note", "varchar",
        "A duplicate column some orders carry from an old checkout form that also recorded "
        "the shipping country in free text; kept side by side with the main field for orders "
        "created before it was added.",
        "unmapped", {"choice": "shipping_country", "peak": 0.85},
    ),
    # ---------------------------------- test: batch_t07 (2 fields) -------------------------------
    (
        "t13", "test", "batch_t07", "balance_owed", "varchar",
        "The three-letter ISO country code the parcel will be shipped to, stored as free "
        "text; the legacy ledger named this column after an older, unrelated billing feature "
        "that was removed years ago.",
        "shipping_country", {"choice": "shipping_country", "peak": 0.82},
    ),
    (
        "t14", "test", "batch_t07", "enrolled_flag", "bool",
        "Whether the customer asked for the order to be wrapped and marked as a gift at "
        "checkout, a column repurposed from an older enrollment-status flag of the same name.",
        "is_gift_order", {"choice": "is_gift_order", "peak": 0.90},
    ),
    # ------------------------------ test: batch_t08 (2 fields, wrong) -----------------------------
    (
        "t15", "test", "batch_t08", "campaign_tag", "varchar",
        "A free-text label naming which marketing channel or campaign referred the customer to "
        "sign up; it has no counterpart in the target order or customer schema.",
        "unmapped", {"choice": "unmapped", "peak": 0.84},
    ),
    (
        "t16-wrong", "test", "batch_t08", "sku_note", "varchar",
        "The stock-keeping unit code identifying the exact product variant ordered, recorded "
        "as a secondary copy by an older point-of-sale terminal still in use at two stores.",
        "product_sku", {"choice": "customer_email", "peak": 0.92},
    ),
    # --------------------------------- demo: batch_d01 (3 fields) --------------------------------
    (
        "d01", "demo", "batch_d01", "acct_label", "varchar",
        "A short alphanumeric loyalty tier code such as GOLD-1, SILVER-2 or BRONZE-3, assigned "
        "when the customer enrolls in the rewards program. Despite the column's name, this "
        "field has never stored the account's own numeric identifier.",
        None, {"choice": "loyalty_tier", "peak": 0.85},
    ),
    (
        "d02", "demo", "batch_d01", "support_region", "varchar",
        "This column has been used inconsistently by different store locations: in about half "
        "of exports it holds the shipping country for the order, and in the other half it "
        "holds the customer's loyalty-program tier name instead; the export itself does not "
        "say which convention a given row follows.",
        None,
        {
            "choice": "ambiguous",
            "peak": 0.40,
            "shares": {"shipping_country": 0.30, "loyalty_tier": 0.30},
        },
    ),
    (
        "d03", "demo", "batch_d01", "ticket_notes", "varchar",
        "A short free-text note support agents attach to a customer record for their own "
        "follow-up; it is not read by any other system and has no corresponding column in "
        "the target schema.",
        None, {"choice": "unmapped", "peak": 0.82},
    ),
]  # fmt: skip


def probabilities_for(spec: dict) -> dict[str, float]:
    """The probability distribution over every option in ``OPTIONS`` named by ``spec``:
    ``spec["peak"]`` on ``spec["choice"]``, ``spec["shares"]`` (if given) on exactly the named
    options, and the remainder split evenly over whatever is left. ``choice`` and ``peak`` are
    read with ``[...]``, never ``.get(..., default)``: a spec missing either is a KeyError, not
    a silently defaulted row (see ROWS's own comment on this).
    """
    choice = spec["choice"]
    peak = spec["peak"]
    shares = spec.get("shares", {})
    if choice in shares:
        raise ValueError(f"{choice!r} is both the choice and a named share")
    probs = dict.fromkeys(OPTIONS, 0.0)
    probs[choice] = peak
    for option, share in shares.items():
        probs[option] = share
    remainder = round(1.0 - peak - sum(shares.values()), 10)
    rest = [o for o in OPTIONS if o != choice and o not in shares]
    if rest:
        each = remainder / len(rest)
        for option in rest[:-1]:
            probs[option] = round(each, 10)
        # the last option absorbs the rounding remainder, so the values still sum to exactly 1
        probs[rest[-1]] = round(remainder - sum(probs[o] for o in rest[:-1]), 10)
    elif abs(remainder) > 1e-9:
        raise ValueError("remainder left over with no option to place it on")
    return probs


def answers_for(spec: dict, provenance: Provenance) -> dict:
    """{question name: answer} for one row: the one Choice this recipe asks, built from
    ``spec`` via :func:`probabilities_for`."""
    probabilities = probabilities_for(spec)
    return {"target": ChoiceAnswer.from_probabilities(probabilities, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, task_id, field_name, declared_type, description, label, _spec in rows:
        fields = _fields(task_id, field_name, declared_type, description)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, task_id, field_name, declared_type, description, _label, spec in rows:
        fields = _fields(task_id, field_name, declared_type, description)
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
