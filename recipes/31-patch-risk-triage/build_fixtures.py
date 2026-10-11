"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 31.

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

RAW_ROWS below holds forty fabricated patches: eight combinations of the three gold
propositions (authentication concern, input-validation concern, data-loss concern), two
patches per combination, split across validation and test, plus three further patches per
split -- one per concern -- whose diff genuinely has that one concern (gold True) but whose
description carries a reassuring, specific-sounding comment (a ticket number, a claim that a
gateway or platform already handles it) that does not actually show the safeguard in the diff
itself; these are stored with a noul low enough to read, confidently, as the concern being
absent. That is the opposite of a false alarm: it is the realistic way a reviewer (or a model)
misses a real problem, by trusting a comment instead of the code. Two plain demo patches close
the set. Every combination of the three gold values appears at least once, so every pair of
concerns is exercised in all four of its own combinations (each alone, both together, neither)
without needing a fixture group dedicated to the pair; every stored answer's basis -- the
diff lines that justify it, including the reassuring comment on the three lookalikes -- is
visible in the excerpt Jev is actually asked about, never only in a label or a comment outside
it.

All diff text below is schematic, not runnable: every file, function, package and ticket name
is fabricated (CONTRIBUTING.md section 5), and no hunk is complete or specific enough to apply
or execute as a real patch. The patches are written to teach the triage decision, never to
demonstrate a working technique.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()


# --------------------------------------------------------------------------------------------
# schematic diff hunks: one function per concern, parameterised by fabricated names so the
# same template produces forty distinct, readable excerpts rather than forty near-duplicates
# of hand-copied text.
# --------------------------------------------------------------------------------------------


def _auth_hunk(service: str, weak: bool, lookalike: bool = False) -> str:
    """A hunk touching ``{service}/auth.py``: ``weak`` removes the permission check Jev is
    asked about; ``lookalike`` (only meaningful when ``weak`` is True) adds a reassuring
    comment citing a ticket, without the check it claims, so the removal is still there for
    Jev to see."""
    if not weak:
        return (
            f"--- a/{service}/auth.py\n"
            f"+++ b/{service}/auth.py\n"
            "@@\n"
            "     if not verify_session_token(request.token):\n"
            "         raise AuthError('session token invalid')\n"
            f"+    if not has_permission(request.actor_id, '{service}:write'):\n"
            "+        raise AuthError('insufficient permission')\n"
            "     actor = load_actor(request.actor_id)\n"
        )
    note = (
        f"+    # permission check re-added upstream by the gateway, see ticket SEC-{len(service)}21\n"
        if lookalike
        else f"+    # permission check removed while {service} migrates to the new gateway\n"
    )
    return (
        f"--- a/{service}/auth.py\n"
        f"+++ b/{service}/auth.py\n"
        "@@\n"
        f"-    if not has_permission(request.actor_id, '{service}:write'):\n"
        "-        raise AuthError('insufficient permission')\n"
        "     actor = load_actor(request.actor_id)\n"
        f"{note}"
    )


def _input_hunk(service: str, field: str, weak: bool, lookalike: bool = False) -> str:
    """A hunk touching ``{service}/handlers.py``: ``weak`` drops the sanitisation of ``field``
    before it reaches a lookup; ``lookalike`` adds a comment claiming the input is sanitised
    elsewhere, without the sanitisation it claims."""
    if not weak:
        return (
            f"--- a/{service}/handlers.py\n"
            f"+++ b/{service}/handlers.py\n"
            "@@\n"
            f"     {field} = sanitize_identifier(request.params['{field}'])\n"
            f"+    if not {field}.isalnum():\n"
            f"+        raise ValidationError('{field} must be alphanumeric')\n"
            f"     record = lookup_record({field})\n"
        )
    note = (
        f"+    # {field} is sanitised upstream by the shared edge middleware, ticket DATA-{len(field)}7\n"
        if lookalike
        else f"+    # sanitisation dropped: {field} now reaches lookup_record unchanged\n"
    )
    return (
        f"--- a/{service}/handlers.py\n"
        f"+++ b/{service}/handlers.py\n"
        "@@\n"
        f"-    {field} = sanitize_identifier(request.params['{field}'])\n"
        f"+    {field} = request.params['{field}']\n"
        f"{note}"
        f"     record = lookup_record({field})\n"
    )


def _dataloss_hunk(service: str, table: str, risky: bool, lookalike: bool = False) -> str:
    """A hunk touching ``{service}/cleanup.py``: ``risky`` drops the archive step before a
    delete of ``table``; ``lookalike`` adds a comment claiming a snapshot is taken elsewhere,
    without the snapshot it claims."""
    if not risky:
        return (
            f"--- a/{service}/cleanup.py\n"
            f"+++ b/{service}/cleanup.py\n"
            "@@\n"
            f"     archive_before_delete('{table}')\n"
            f"     delete_rows('{table}', older_than=retention_days)\n"
            f"+    confirm_archive_complete('{table}')\n"
        )
    note = (
        f"+    # a snapshot of '{table}' is captured automatically by the platform, see OPS-{len(table)}4\n"
        if lookalike
        else f"+    # archive step removed; '{table}' is deleted directly to shorten the job\n"
    )
    return (
        f"--- a/{service}/cleanup.py\n"
        f"+++ b/{service}/cleanup.py\n"
        "@@\n"
        f"-    archive_before_delete('{table}')\n"
        f"     delete_rows('{table}', older_than=retention_days)\n"
        f"{note}"
    )


def _diff(
    title: str,
    service: str,
    field: str,
    table: str,
    gold: tuple[bool, bool, bool],
    lookalike: str | None = None,
) -> str:
    """The full patch excerpt for one row: a one-line title, then the three hunks in a fixed
    order (authentication, input validation, data loss). ``gold`` is
    ``(authentication_concern, input_validation_concern, data_loss_concern)``; ``lookalike``,
    when given, is the one label (from ``helpers.LABELS``) whose hunk should carry the
    reassuring, unsubstantiated comment instead of the plain one."""
    auth_gold, input_gold, dataloss_gold = gold
    return (
        f"Patch: {title}\n\n"
        + _auth_hunk(service, auth_gold, lookalike=lookalike == helpers.AUTHENTICATION_CONCERN)
        + "\n"
        + _input_hunk(
            service, field, input_gold, lookalike=lookalike == helpers.INPUT_VALIDATION_CONCERN
        )
        + "\n"
        + _dataloss_hunk(
            service, table, dataloss_gold, lookalike=lookalike == helpers.DATA_LOSS_CONCERN
        )
    )


# --------------------------------------------------------------------------------------------
# forty fabricated services, one per row, so every patch names a different (invented) system.
# (service, field, table, title)
# --------------------------------------------------------------------------------------------

_VALIDATION_NAMES = (
    ("loyalty-svc", "promo_code", "loyalty_ledger", "Add a loyalty bonus to checkout"),
    ("ticketing-svc", "ticket_ref", "ticket_archive", "Let agents reassign support tickets"),
    ("billing-worker", "invoice_id", "invoice_totals", "Retry failed billing charges"),
    ("profile-export-svc", "export_token", "profile_exports", "Let users export their profile"),
    ("session-renewal-job", "session_id", "session_store", "Renew long-lived sessions nightly"),
    ("coupon-redeem-svc", "coupon_code", "coupon_redemptions", "Apply bulk coupon redemptions"),
    ("searchindex-job", "doc_id", "search_index", "Rebuild the product search index nightly"),
    ("auditlog-purge-job", "entry_id", "audit_log", "Purge old audit log entries nightly"),
    ("avatar-resize-worker", "image_id", "avatar_cache", "Resize uploaded avatar images"),
    ("password-reset-svc", "reset_token", "password_resets", "Let users request a password reset"),
    ("bulk-import-svc", "batch_id", "import_batches", "Import supplier catalog updates in bulk"),
    ("invoice-pdf-svc", "invoice_id", "invoice_pdfs", "Generate PDF invoices on demand"),
    ("order-cancel-svc", "order_id", "order_archive", "Let customers cancel a pending order"),
    ("user-merge-job", "user_id", "user_accounts", "Merge duplicate user accounts nightly"),
    ("report-export-svc", "report_id", "report_exports", "Export finance reports to CSV"),
    ("webhook-relay-svc", "event_id", "webhook_log", "Relay webhook events to partners"),
)

_TEST_NAMES = (
    ("giftcard-svc", "card_code", "giftcard_ledger", "Add gift card balance adjustments"),
    ("escalation-svc", "case_ref", "case_archive", "Allow escalation of support cases"),
    ("payout-worker", "payout_id", "payout_totals", "Retry failed partner payouts"),
    ("datarequest-svc", "request_token", "data_requests", "Let users export their account data"),
    ("token-refresh-job", "token_id", "token_store", "Refresh long-lived API tokens nightly"),
    ("voucher-redeem-svc", "voucher_code", "voucher_redemptions", "Apply bulk voucher redemptions"),
    ("catalogindex-job", "sku_id", "catalog_index", "Rebuild the catalog search index nightly"),
    ("eventlog-purge-job", "entry_id", "event_log", "Purge old event log entries nightly"),
    ("thumbnail-resize-worker", "image_id", "thumbnail_cache", "Resize uploaded thumbnails"),
    ("mfa-reset-svc", "reset_token", "mfa_resets", "Let users request an MFA reset"),
    ("bulk-sync-svc", "batch_id", "sync_batches", "Sync warehouse inventory updates in bulk"),
    ("receipt-pdf-svc", "order_id", "receipt_pdfs", "Generate PDF receipts on demand"),
    ("subscription-cancel-svc", "sub_id", "subscription_archive", "Let customers cancel a plan"),
    ("contact-merge-job", "contact_id", "contact_records", "Merge duplicate contact records"),
    ("ledger-export-svc", "ledger_id", "ledger_exports", "Export accounting ledgers to CSV"),
    (
        "notification-relay-svc",
        "event_id",
        "notification_log",
        "Relay notification events to partners",
    ),
)

# The eight combinations, visited in a fixed order (FFF, TFF, FTF, FFT, TTF, TFT, FTT, TTT),
# each paired with two rows. The second row of the single-concern combinations (TFF, FTF, FFT)
# is a deliberately borderline true reading, overridden below rather than drawn from the same
# high band as every other true reading, so F1 has a real choice of candidates near the line
# rather than only the clean high band to select a threshold from; which observed value F1
# actually freezes as a concern's threshold is reported by the notebook, not decided here.
_COMBOS = (
    (False, False, False),
    (True, False, False),
    (False, True, False),
    (False, False, True),
    (True, True, False),
    (True, False, True),
    (False, True, True),
    (True, True, True),
)

# Clean readings vary row to row rather than repeating one flat number (so the fixtures are not
# a two-value grid): a short, deliberately uneven cycle for the "true" and "false" bands.
_TRUE_CYCLE = (0.86, 0.93, 0.97, 0.90, 0.95, 0.84, 0.91, 0.96)
_FALSE_CYCLE = (0.04, 0.09, 0.02, 0.11, 0.06, 0.03, 0.08, 0.05)

# Overrides, by (row index within the split, label): deliberately borderline or wrong readings
# written to land somewhere specific, not drawn from the clean bands below. Each is a true
# reading unless its own comment says otherwise. Which one of these ends up setting a given
# concern's frozen business threshold is decided by F1 over the whole split, not by this
# comment: on validation it happens to be (9, INPUT_VALIDATION_CONCERN) at 0.50 (the near-0.5
# reading written to be gated) rather than (5, INPUT_VALIDATION_CONCERN) at 0.56, because 0.50
# is the lower of the two and F1 ties toward the more conservative (higher) threshold only when
# two candidates score equally -- here they do not, so the frozen threshold is whichever of the
# observed values actually maximises F1, confirmed in the notebook's own printed output, not
# asserted here.
_VALIDATION_OVERRIDES = {
    (3, helpers.AUTHENTICATION_CONCERN): 0.58,  # TFF, second row: borderline true
    (5, helpers.INPUT_VALIDATION_CONCERN): 0.56,  # FTF, second row: borderline true
    (7, helpers.DATA_LOSS_CONCERN): 0.61,  # FFT, second row: borderline true
    (1, helpers.INPUT_VALIDATION_CONCERN): 0.63,  # FFF, second row: a wrong, low-confidence tag
    (9, helpers.INPUT_VALIDATION_CONCERN): 0.50,  # TTF, second row: a near-0.5 reading, gated
}
_TEST_OVERRIDES = {
    (3, helpers.AUTHENTICATION_CONCERN): 0.64,
    (5, helpers.INPUT_VALIDATION_CONCERN): 0.62,
    (7, helpers.DATA_LOSS_CONCERN): 0.67,
}

# A per-split shift into _TRUE_CYCLE/_FALSE_CYCLE so the two splits do not draw the same clean
# reading at the same row index: with no shift, row i's clean readings on validation and on
# test are the same two cycle entries (same combo at the same position), which is what made 11
# of the 19 test patches share a validation patch's exact stored-answer profile. Shifting test's
# index by half the cycle length (4 of 8) de-correlates every non-overridden row while leaving
# the actual *set* of values each split draws from unchanged -- every entry of both cycles
# still appears in both splits the same number of times, just attached to different rows -- so
# no per-concern tag, no threshold, and no gate decision moves; only which row carries which
# already-clean reading does.
_CYCLE_OFFSET = {"validation": 0, "test": 4}


def _combo_rows(split: str, names, overrides):
    rows = []
    row_index = 0
    offset = _CYCLE_OFFSET[split]
    for combo in _COMBOS:
        for _ in range(2):
            service, field, table, title = names[row_index]
            noul = []
            for label, gold_value in zip(helpers.LABELS, combo, strict=True):
                if (row_index, label) in overrides:
                    noul.append(overrides[(row_index, label)])
                elif gold_value:
                    noul.append(_TRUE_CYCLE[(row_index + offset) % len(_TRUE_CYCLE)])
                else:
                    noul.append(_FALSE_CYCLE[(row_index + offset) % len(_FALSE_CYCLE)])
            ident = f"{split[0]}{row_index + 1:02d}"
            diff = _diff(title, service, field, table, combo)
            rows.append((ident, split, diff, combo, tuple(noul)))
            row_index += 1
    return rows


_VALIDATION_LOOKALIKES = (
    (
        "v17",
        "gateway-authz-svc",
        "actor_id",
        "session_store",
        "Route write requests through the new gateway",
        helpers.AUTHENTICATION_CONCERN,
        (0.05, 0.04, 0.05),
    ),
    (
        "v18",
        "catalog-search-svc",
        "query_term",
        "search_index",
        "Let catalog search accept a free-text filter",
        helpers.INPUT_VALIDATION_CONCERN,
        (0.03, 0.06, 0.04),
    ),
    (
        "v19",
        "snapshot-cleanup-job",
        "actor_id",
        "snapshot_store",
        "Shorten the nightly snapshot-cleanup job",
        helpers.DATA_LOSS_CONCERN,
        (0.04, 0.03, 0.07),
    ),
)

_TEST_LOOKALIKES = (
    (
        "t17",
        "partner-authz-svc",
        "actor_id",
        "token_store",
        "Route partner write requests through the new gateway",
        helpers.AUTHENTICATION_CONCERN,
        (0.06, 0.05, 0.04),
    ),
    (
        "t18",
        "legacy-search-svc",
        "query_term",
        "catalog_index",
        "Let legacy search accept a free-text filter",
        helpers.INPUT_VALIDATION_CONCERN,
        (0.04, 0.07, 0.05),
    ),
    (
        "t19",
        "archive-cleanup-job",
        "actor_id",
        "archive_store",
        "Shorten the nightly archive-cleanup job",
        helpers.DATA_LOSS_CONCERN,
        (0.05, 0.04, 0.08),
    ),
)


def _lookalike_rows(entries):
    rows = []
    for ident, service, field, table, title, lookalike_label, noul in entries:
        gold = tuple(label == lookalike_label for label in helpers.LABELS)
        diff = _diff(title, service, field, table, gold, lookalike=lookalike_label)
        rows.append((ident, "validation" if ident.startswith("v") else "test", diff, gold, noul))
    return rows


_DEMO_ROWS = (
    # d01: a clean patch, confidently routine on all three concerns.
    (
        "d01",
        "demo",
        _diff(
            "Add a seasonal banner to the storefront",
            "storefront-banner-svc",
            "banner_id",
            "banner_cache",
            (False, False, False),
        ),
        None,
        (0.04, 0.05, 0.03),
    ),
    # d02: authentication reads just above where "Python's part" freezes the business
    # threshold, but its confidence is low enough that the shared gate sends the whole patch
    # to review rather than act on a reading this close to the line.
    (
        "d02",
        "demo",
        _diff(
            "Let the inventory-sync job run outside business hours",
            "inventory-sync-svc",
            "actor_id",
            "inventory_ledger",
            (True, False, False),
        ),
        None,
        (0.62, 0.07, 0.05),
    ),
)

RAW_ROWS = (
    *_combo_rows("validation", _VALIDATION_NAMES, _VALIDATION_OVERRIDES),
    *_lookalike_rows(_VALIDATION_LOOKALIKES),
    *_combo_rows("test", _TEST_NAMES, _TEST_OVERRIDES),
    *_lookalike_rows(_TEST_LOOKALIKES),
    *_DEMO_ROWS,
)


def _label_for(gold):
    """The gold label record for one scored row, or ``None`` for a ``demo`` row. ``concerns``
    is every proposition in ``helpers.LABELS`` whose gold value is ``True``; ``priority`` is
    the review priority ``helpers.priority_from_concerns`` composes from that same set --
    the gold composed outcome a stored answer is compared against, built from these three
    independently authored booleans by the one function ``review_priority`` itself calls,
    never from a second, separate implementation of the same rule."""
    if gold is None:
        return None
    concerns = frozenset(name for name, value in zip(helpers.LABELS, gold, strict=True) if value)
    priority, _reason = helpers.priority_from_concerns(concerns)
    label = {name: value for name, value in zip(helpers.LABELS, gold, strict=True)}
    label["priority"] = priority
    return label


ROWS = tuple(
    (ident, split, {"diff": diff}, _label_for(gold), noul)
    for ident, split, diff, gold, noul in RAW_ROWS
)


def answers_for(spec, provenance: Provenance):
    """{question name: answer} for one row: a Noul answer for each of the three concerns, from
    the row's ``(auth_noul, input_noul, dataloss_noul)`` spec."""
    auth_noul, input_noul, dataloss_noul = spec
    return {
        helpers.AUTHENTICATION_CONCERN: NoulAnswer(auth_noul, provenance),
        helpers.INPUT_VALIDATION_CONCERN: NoulAnswer(input_noul, provenance),
        helpers.DATA_LOSS_CONCERN: NoulAnswer(dataloss_noul, provenance),
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
        raise SystemExit("ROWS is empty; add examples to it in build_fixtures.py")
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
