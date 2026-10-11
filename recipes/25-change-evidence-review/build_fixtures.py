"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 25.

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

RAW_ROWS below holds forty fabricated change records: eight combinations of the three gold
propositions (sufficient implementation evidence, sufficient validation evidence, sufficient
rollback evidence), two records per combination, split across validation and test, plus three
further records per split -- one per proposition -- where the record names a specific-sounding
but ultimately empty mention of that one evidence type (a ticket, an approver, a runbook, a
sign-off) without actually describing it (an insufficient reading this use case names directly:
a record that mentions a rollback plan without describing one), stored with a noul high enough
to read as a false positive against that proposition's own business threshold. These six
lookalikes do not move any threshold -- the thresholds are set elsewhere, by the three
deliberately borderline true readings (the lowest true positive for each proposition); what the
lookalikes do is give the shared confidence gate false positives to catch on validation, and
leave the single confidently-wrong record the gate does not catch on test. Two plain demo
records close the set. Every combination of the three gold values therefore appears at least
once, so every pair of propositions is exercised in all four of its own combinations (each
alone, both together, neither) without needing a fixture group dedicated to the pair.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# Each entry: (id, split, record text, gold (implementation, validation, rollback) or None for
# a demo record, stored (noul, noul, noul)). The eight combinations are visited in a fixed
# order (TTT, TTF, TFT, TFF, FTT, FTF, FFT, FFF), two records each; a true value's text comes
# from a phrase bank keyed by topic, so every proposition that reads true on one record
# describes the *same* underlying change as every other true proposition on that record. A
# false value's text is a generic, topic-free phrase (vague, or -- for the three lookalike
# records -- a specific, named mention with nothing behind it), which is why it never needs to
# match the record's topic.
RAW_ROWS = (
    # --- validation ------------------------------------------------------------
    (
        "v01",
        "validation",
        "Add loyalty discount to checkout\n\nImplementation: Updated the checkout service's `discount_rules.py` to add a 10% loyalty discount for accounts over two years old, and redeployed checkout-api pods 1 through 6 via the standard pipeline.\n\nValidation: Ran the full regression suite (212 cases) against staging; all cases passed, and a manual spot-check of 25 sampled invoices matched finance's reconciliation spreadsheet exactly.\n\nRollback: If an issue is found, revert commit 8f2c91a and redeploy the previous build (checkout-api:4.18.2) via the standard pipeline; the discount logic change touches no stored data, so no data migration reversal is needed.",
        (True, True, True),
        (0.97, 0.98, 0.96),
    ),
    (
        "v02",
        "validation",
        "Rotate edge TLS certificate\n\nImplementation: Rotated the TLS certificate for api.internal.example.com on the edge load balancers (lb-01, lb-02) and updated the corresponding entries in the certificate inventory.\n\nValidation: Verified in staging that the rotated certificate presents correctly on every edge load balancer and that the TLS handshake succeeds from three external test clients.\n\nRollback: Restore the previous certificate from the inventory's prior entry and reload the load balancers' TLS configuration; the prior certificate remains valid for 11 more days, so there is no gap.",
        (True, True, True),
        (0.96, 0.97, 0.95),
    ),
    (
        "v03",
        "validation",
        "Add customer order index\n\nImplementation: Added a new index on `orders(customer_id, created_at)` in the orders database and updated the ORM model `Order` to use it for the dashboard query.\n\nValidation: Verified in staging that the new index cut the dashboard query's P95 latency from 820ms to 95ms, confirmed against the APM trace.\n\nRollback: We can roll this back if needed.",
        (True, True, False),
        (0.95, 0.96, 0.02),
    ),
    (
        "v04",
        "validation",
        "Migrate billing worker to new topic\n\nImplementation: Migrated the `billing-worker` service from the legacy queue (billing-legacy) to the new `billing-events` topic, updating the consumer group configuration accordingly.\n\nValidation: Replayed the last 30 days of production billing events against the new consumer in a shadow environment and confirmed the computed totals matched the legacy consumer's output exactly.\n\nRollback: Standard rollback process applies.",
        (True, True, False),
        (0.94, 0.95, 0.02),
    ),
    (
        "v05",
        "validation",
        "Externalize shipping rate table\n\nImplementation: Replaced the hardcoded shipping-rate table in `rates.py` with a call to the new rates microservice, behind the `use_rates_service` feature flag.\n\nValidation: Testing was completed successfully.\n\nRollback: Set `use_rates_service` to false in the feature-flag service, which reverts to the hardcoded table with no deploy required; no code rollback is needed.",
        (True, False, True),
        (0.93, 0.01, 0.94),
    ),
    (
        "v06",
        "validation",
        "Backfill invoice tax region\n\nImplementation: Patched the `invoice_totals` backfill migration to recompute `tax_region` for every invoice created before 2024-01-01, run via the nightly `migrate:backfill` batch job.\n\nValidation: Looks good in staging.\n\nRollback: Restore the `invoice_totals` table from the pre-backfill snapshot taken at 01:00 UTC before the migration ran, using the standard snapshot-restore runbook.",
        (True, False, True),
        (0.92, 0.01, 0.93),
    ),
    (
        "v07",
        "validation",
        "Add rate limiting to search API\n\nImplementation: Added rate limiting (100 requests per minute per API key) to the `/v2/search` endpoint in `search_api/middleware.py`.\n\nValidation: No issues found during review.\n\nRollback: A rollback plan is in place.",
        (True, False, False),
        (0.91, 0.02, 0.03),
    ),
    (
        "v08",
        "validation",
        "Switch password-reset email provider\n\nImplementation: Updated the `notification-service` to send password-reset emails through the new transactional email provider instead of the deprecated SMTP relay.\n\nValidation: Passed testing.\n\nRollback: Rollback plan: see runbook.",
        (True, False, False),
        (0.83, 0.03, 0.03),
    ),
    (
        "v09",
        "validation",
        "Increase payments-gateway retries\n\nImplementation: The change has been made as discussed.\n\nValidation: Simulated gateway timeouts in staging and confirmed the retry policy made exactly 5 attempts with the expected backoff intervals, logged in the test run.\n\nRollback: Revert `gateway.yaml` to the previous retry policy (3 attempts, fixed 500ms delay) and redeploy payments-gateway; no in-flight payments are affected since retries are idempotent.",
        (False, True, True),
        (0.01, 0.94, 0.92),
    ),
    (
        "v10",
        "validation",
        "Add archived_at column to tickets\n\nImplementation: Implementation details attached.\n\nValidation: Ran the archive job against a staging snapshot and confirmed `archived_at` was populated for all 512 tickets older than 90 days, with none set for newer tickets.\n\nRollback: Run the reverse migration to drop the `archived_at` column and redeploy the archive job at the previous tag; no tickets are deleted by the rollback.",
        (False, True, True),
        (0.02, 0.93, 0.91),
    ),
    (
        "v11",
        "validation",
        "Add loyalty discount to checkout\n\nImplementation: Standard update applied to the service.\n\nValidation: Ran the full regression suite (212 cases) against staging; all cases passed, and a manual spot-check of 25 sampled invoices matched finance's reconciliation spreadsheet exactly.\n\nRollback: No rollback needed.",
        (False, True, False),
        (0.02, 0.92, 0.04),
    ),
    (
        "v12",
        "validation",
        "Rotate edge TLS certificate\n\nImplementation: Made the requested fix.\n\nValidation: Verified in staging that the rotated certificate presents correctly on every edge load balancer and that the TLS handshake succeeds from three external test clients.\n\nRollback: Rollback plan: TBD.",
        (False, True, False),
        (0.03, 0.85, 0.05),
    ),
    (
        "v13",
        "validation",
        "Add customer order index\n\nImplementation: Done, see the dev branch.\n\nValidation: Validated per standard process.\n\nRollback: Drop the new index with `DROP INDEX orders_customer_created_idx` and redeploy the dashboard service at the previous tag; query results are unaffected either way.",
        (False, False, True),
        (0.03, 0.03, 0.9),
    ),
    (
        "v14",
        "validation",
        "Migrate billing worker to new topic\n\nImplementation: Everything needed was changed.\n\nValidation: QA signed off.\n\nRollback: Repoint the `billing-worker` consumer group back to the `billing-legacy` queue and redeploy the prior consumer image; the new topic's events remain available for replay later if needed.",
        (False, False, True),
        (0.04, 0.04, 0.84),
    ),
    (
        "v15",
        "validation",
        "Externalize shipping rate table\n\nImplementation: The change has been made as discussed.\n\nValidation: Testing was completed successfully.\n\nRollback: We can roll this back if needed.",
        (False, False, False),
        (0.05, 0.05, 0.05),
    ),
    (
        "v16",
        "validation",
        "Backfill invoice tax region\n\nImplementation: Implementation details attached.\n\nValidation: Looks good in staging.\n\nRollback: Standard rollback process applies.",
        (False, False, False),
        (0.06, 0.06, 0.07),
    ),
    (
        "v17",
        "validation",
        "Externalize shipping rate table\n\nImplementation: Delivered in the Q3 release train (sprint 14); approved by the platform lead and tracked under JIRA-5192.\n\nValidation: Tested the feature flag in both positions in staging: with it off, rates matched the old table exactly for all 40 sample routes; with it on, rates matched the new service's published rate card.\n\nRollback: Set `use_rates_service` to false in the feature-flag service, which reverts to the hardcoded table with no deploy required; no code rollback is needed.",
        (False, True, True),
        (0.87, 0.98, 0.96),
    ),
    (
        "v18",
        "validation",
        "Add rate limiting to search API\n\nImplementation: Added rate limiting (100 requests per minute per API key) to the `/v2/search` endpoint in `search_api/middleware.py`.\n\nValidation: Reviewed and signed off by QA under ticket QA-3310, per the release checklist.\n\nRollback: Remove the rate-limiting middleware from `search_api/middleware.py` and redeploy search-api at the previous tag (search-api:7.2.0).",
        (True, False, True),
        (0.97, 0.86, 0.95),
    ),
    (
        "v19",
        "validation",
        "Increase payments-gateway retries\n\nImplementation: Reconfigured the `payments-gateway` retry policy in `gateway.yaml` from 3 attempts to 5, with exponential backoff starting at 200ms.\n\nValidation: Simulated gateway timeouts in staging and confirmed the retry policy made exactly 5 attempts with the expected backoff intervals, logged in the test run.\n\nRollback: Rollback plan documented in RUNBOOK-204, owned by the payments on-call rotation and reviewed before this deploy.",
        (True, True, False),
        (0.96, 0.97, 0.89),
    ),
    # --- test ------------------------------------------------------------------
    (
        "t01",
        "test",
        "Add customer order index\n\nImplementation: Added a new index on `orders(customer_id, created_at)` in the orders database and updated the ORM model `Order` to use it for the dashboard query.\n\nValidation: Verified in staging that the new index cut the dashboard query's P95 latency from 820ms to 95ms, confirmed against the APM trace.\n\nRollback: Drop the new index with `DROP INDEX orders_customer_created_idx` and redeploy the dashboard service at the previous tag; query results are unaffected either way.",
        (True, True, True),
        (0.96, 0.97, 0.95),
    ),
    (
        "t02",
        "test",
        "Migrate billing worker to new topic\n\nImplementation: Migrated the `billing-worker` service from the legacy queue (billing-legacy) to the new `billing-events` topic, updating the consumer group configuration accordingly.\n\nValidation: Replayed the last 30 days of production billing events against the new consumer in a shadow environment and confirmed the computed totals matched the legacy consumer's output exactly.\n\nRollback: Repoint the `billing-worker` consumer group back to the `billing-legacy` queue and redeploy the prior consumer image; the new topic's events remain available for replay later if needed.",
        (True, True, True),
        (0.95, 0.96, 0.94),
    ),
    (
        "t03",
        "test",
        "Externalize shipping rate table\n\nImplementation: Replaced the hardcoded shipping-rate table in `rates.py` with a call to the new rates microservice, behind the `use_rates_service` feature flag.\n\nValidation: Tested the feature flag in both positions in staging: with it off, rates matched the old table exactly for all 40 sample routes; with it on, rates matched the new service's published rate card.\n\nRollback: Rollback plan: see runbook.",
        (True, True, False),
        (0.94, 0.95, 0.01),
    ),
    (
        "t04",
        "test",
        "Backfill invoice tax region\n\nImplementation: Patched the `invoice_totals` backfill migration to recompute `tax_region` for every invoice created before 2024-01-01, run via the nightly `migrate:backfill` batch job.\n\nValidation: Ran the backfill against a staging copy of the production database and confirmed all 18,204 affected invoices now report the correct tax region, spot-checked against the tax team's reference list.\n\nRollback: No rollback needed.",
        (True, True, False),
        (0.93, 0.94, 0.02),
    ),
    (
        "t05",
        "test",
        "Add rate limiting to search API\n\nImplementation: Added rate limiting (100 requests per minute per API key) to the `/v2/search` endpoint in `search_api/middleware.py`.\n\nValidation: Passed testing.\n\nRollback: Remove the rate-limiting middleware from `search_api/middleware.py` and redeploy search-api at the previous tag (search-api:7.2.0).",
        (True, False, True),
        (0.92, 0.02, 0.93),
    ),
    (
        "t06",
        "test",
        "Switch password-reset email provider\n\nImplementation: Updated the `notification-service` to send password-reset emails through the new transactional email provider instead of the deprecated SMTP relay.\n\nValidation: Validated per standard process.\n\nRollback: Revert the `notification-service` config to point back at the legacy SMTP relay, which remains active and unchanged during this rollout.",
        (True, False, True),
        (0.91, 0.02, 0.92),
    ),
    (
        "t07",
        "test",
        "Increase payments-gateway retries\n\nImplementation: Reconfigured the `payments-gateway` retry policy in `gateway.yaml` from 3 attempts to 5, with exponential backoff starting at 200ms.\n\nValidation: QA signed off.\n\nRollback: Rollback plan: TBD.",
        (True, False, False),
        (0.9, 0.03, 0.03),
    ),
    (
        "t08",
        "test",
        "Add archived_at column to tickets\n\nImplementation: Added a new column `archived_at` to the `tickets` table and updated the `Ticket` model and the archive job to populate it.\n\nValidation: Testing was completed successfully.\n\nRollback: We can roll this back if needed.",
        (True, False, False),
        (0.8, 0.03, 0.04),
    ),
    (
        "t09",
        "test",
        "Add loyalty discount to checkout\n\nImplementation: Made the requested fix.\n\nValidation: Ran the full regression suite (212 cases) against staging; all cases passed, and a manual spot-check of 25 sampled invoices matched finance's reconciliation spreadsheet exactly.\n\nRollback: If an issue is found, revert commit 8f2c91a and redeploy the previous build (checkout-api:4.18.2) via the standard pipeline; the discount logic change touches no stored data, so no data migration reversal is needed.",
        (False, True, True),
        (0.01, 0.93, 0.91),
    ),
    (
        "t10",
        "test",
        "Rotate edge TLS certificate\n\nImplementation: Done, see the dev branch.\n\nValidation: Verified in staging that the rotated certificate presents correctly on every edge load balancer and that the TLS handshake succeeds from three external test clients.\n\nRollback: Restore the previous certificate from the inventory's prior entry and reload the load balancers' TLS configuration; the prior certificate remains valid for 11 more days, so there is no gap.",
        (False, True, True),
        (0.02, 0.92, 0.9),
    ),
    (
        "t11",
        "test",
        "Add customer order index\n\nImplementation: Everything needed was changed.\n\nValidation: Verified in staging that the new index cut the dashboard query's P95 latency from 820ms to 95ms, confirmed against the APM trace.\n\nRollback: Standard rollback process applies.",
        (False, True, False),
        (0.03, 0.91, 0.04),
    ),
    (
        "t12",
        "test",
        "Migrate billing worker to new topic\n\nImplementation: The change has been made as discussed.\n\nValidation: Replayed a sample of the last 30 days of production billing events against the new consumer in a shadow environment; totals matched the legacy consumer's output for the sampled window, though the full 30-day replay had not finished before this record was filed.\n\nRollback: A rollback plan is in place.",
        (False, True, False),
        (0.03, 0.82, 0.05),
    ),
    (
        "t13",
        "test",
        "Externalize shipping rate table\n\nImplementation: Implementation details attached.\n\nValidation: Looks good in staging.\n\nRollback: Set `use_rates_service` to false in the feature-flag service, which reverts to the hardcoded table with no deploy required; no code rollback is needed.",
        (False, False, True),
        (0.04, 0.04, 0.89),
    ),
    (
        "t14",
        "test",
        "Backfill invoice tax region\n\nImplementation: Standard update applied to the service.\n\nValidation: No issues found during review.\n\nRollback: Restore the `invoice_totals` table from the pre-backfill snapshot taken at 01:00 UTC before the migration ran, using the standard snapshot-restore runbook.",
        (False, False, True),
        (0.04, 0.05, 0.81),
    ),
    (
        "t15",
        "test",
        "Add rate limiting to search API\n\nImplementation: Made the requested fix.\n\nValidation: Passed testing.\n\nRollback: Rollback plan: see runbook.",
        (False, False, False),
        (0.05, 0.05, 0.06),
    ),
    (
        "t16",
        "test",
        "Switch password-reset email provider\n\nImplementation: Done, see the dev branch.\n\nValidation: Validated per standard process.\n\nRollback: No rollback needed.",
        (False, False, False),
        (0.06, 0.07, 0.07),
    ),
    (
        "t17",
        "test",
        "Rotate edge TLS certificate\n\nImplementation: Delivered in the Q3 release train (sprint 14); approved by the platform lead and tracked under JIRA-5188.\n\nValidation: Verified in staging that the rotated certificate presents correctly on every edge load balancer and that the TLS handshake succeeds from three external test clients.\n\nRollback: Restore the previous certificate from the inventory's prior entry and reload the load balancers' TLS configuration; the prior certificate remains valid for 11 more days, so there is no gap.",
        (False, True, True),
        (0.85, 0.97, 0.95),
    ),
    (
        "t18",
        "test",
        "Migrate billing worker to new topic\n\nImplementation: Migrated the `billing-worker` service from the legacy queue (billing-legacy) to the new `billing-events` topic, updating the consumer group configuration accordingly.\n\nValidation: Reviewed and signed off by QA under ticket QA-3318, per the release checklist.\n\nRollback: Repoint the `billing-worker` consumer group back to the `billing-legacy` queue and redeploy the prior consumer image; the new topic's events remain available for replay later if needed.",
        (True, False, True),
        (0.96, 0.84, 0.94),
    ),
    (
        "t19",
        "test",
        "Backfill invoice tax region\n\nImplementation: Patched the `invoice_totals` backfill migration to recompute `tax_region` for every invoice created before 2024-01-01, run via the nightly `migrate:backfill` batch job.\n\nValidation: Ran the backfill against a staging copy of the production database and confirmed all 18,204 affected invoices now report the correct tax region, spot-checked against the tax team's reference list.\n\nRollback: Rollback plan documented in RUNBOOK-211, owned by the data-platform on-call rotation and reviewed before this deploy.",
        (True, True, False),
        (0.95, 0.96, 0.9),
    ),
    # --- demo ------------------------------------------------------------------
    (
        "d01",
        "demo",
        "Add dynamic discount rule to checkout\n\nImplementation: Added a `loyalty_discount` rule to `checkout/pricing.py` that applies a 10% discount for accounts active over two years, deployed to checkout-api pods 1-6.\n\nValidation: Ran the pricing regression suite (88 cases) in staging; all passed, and manually verified the discount applied correctly for 10 sample accounts of varying age.\n\nRollback: Revert commit 4a7e21c and redeploy checkout-api at the previous tag (checkout-api:6.3.0); the change touches no stored data, so no further reversal is needed.",
        None,
        (0.95, 0.96, 0.94),
    ),
    (
        "d02",
        "demo",
        "Add regional failover for checkout\n\nImplementation: Added a secondary-region failover path to `checkout/router.py`, switching traffic to the eu-west pool when the primary region's health check fails twice in a row.\n\nValidation: Forced a primary-region health-check failure in staging and confirmed traffic switched to eu-west within 8 seconds with no dropped checkouts.\n\nRollback: A rollback plan is in place.",
        None,
        (0.93, 0.92, 0.09),
    ),
)


def _label_for(gold):
    """The gold label record for one scored row, or ``None`` for a ``demo`` row. ``gaps`` is
    every proposition in ``helpers.LABELS`` whose gold value is ``False``; ``outcome`` is
    ``helpers.READY`` when there are none and ``helpers.GAPS`` otherwise -- the gold composed
    outcome a stored answer is compared against, built from these three independently authored
    booleans, never from one of them standing in for another."""
    if gold is None:
        return None
    gold_impl, gold_valid, gold_rollback = gold
    outcome = helpers.READY if gold_impl and gold_valid and gold_rollback else helpers.GAPS
    return {
        helpers.IMPLEMENTATION_EVIDENCE: gold_impl,
        helpers.VALIDATION_EVIDENCE: gold_valid,
        helpers.ROLLBACK_EVIDENCE: gold_rollback,
        "outcome": outcome,
    }


ROWS = tuple(
    (ident, split, {"record": record}, _label_for(gold), spec)
    for ident, split, record, gold, spec in RAW_ROWS
)


def answers_for(spec, provenance: Provenance):
    """{question name: answer} for one row: a Noul answer for each of the three propositions,
    from the row's ``(implementation_prob, validation_prob, rollback_prob)`` spec."""
    implementation_prob, validation_prob, rollback_prob = spec
    return {
        helpers.IMPLEMENTATION_EVIDENCE: NoulAnswer(implementation_prob, provenance),
        helpers.VALIDATION_EVIDENCE: NoulAnswer(validation_prob, provenance),
        helpers.ROLLBACK_EVIDENCE: NoulAnswer(rollback_prob, provenance),
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
