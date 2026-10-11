"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 29.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic and deliberately imperfect: some are wrong, including some wrong
*and* confident, so the evaluation in the notebook has something real to find. The replay keys
come from the same ``build_state`` and ``build_questions`` the notebook uses, so they cannot
drift from the question.

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
OUTCOMES = helpers.OUTCOMES  # (unverifiable, failed, partial, complete)
UNVERIFIABLE, FAILED, PARTIAL, COMPLETE = OUTCOMES


def _fields(call_id, request, tool, reported_status, exit_code, stdout, stderr, artifacts):
    return {
        "call_id": call_id,
        "request": request,
        "tool": tool,
        "reported_status": reported_status,
        "exit_code": exit_code,
        "stdout_excerpt": stdout,
        "stderr_excerpt": stderr,
        "artifacts": list(artifacts),
    }


def _dist(top, p_max):
    """Probabilities over OUTCOMES: ``p_max`` on ``top``, the rest split evenly."""
    rest = (1.0 - p_max) / 3.0
    return tuple(p_max if name == top else rest for name in OUTCOMES)


# --------------------------------------------------------------------------------------
# Tool-run records. Nothing here is a real tool, a real customer, or a real outage: every
# request, tool name and excerpt is written for this recipe. No fixture names a real package
# at a real version (CONTRIBUTING.md section 5): failures are written as operational errors
# (permissions, quotas, timeouts, missing files), never import or dependency errors.
# --------------------------------------------------------------------------------------

# (id, split, fields, gold label or None for a demo example, probabilities over OUTCOMES)
ROWS = [
    # ======================================================================================
    # validation -- 19 examples: 5 complete, 5 partial, 5 failed (one the "contradicts" hard
    # case, which also pins the confidence gate), 4 unverifiable (one the "no evidence" hard
    # case).
    # ======================================================================================
    (
        "v-complete-01",
        "validation",
        _fields(
            "CALL-10001",
            "Write the Q3 summary to reports/q3_summary.csv",
            "write_file",
            "success",
            0,
            "Wrote 482 rows to reports/q3_summary.csv",
            "",
            ["reports/q3_summary.csv"],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.90),
    ),
    (
        "v-complete-02",
        "validation",
        _fields(
            "CALL-10002",
            "Email the renewal reminder to all customers in the 'expiring_30d' segment",
            "send_email",
            "success",
            0,
            "Sent 214 of 214 messages in segment 'expiring_30d'",
            "",
            [],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.85),
    ),
    (
        "v-complete-03",
        "validation",
        _fields(
            "CALL-10003",
            "Deploy the checkout-service canary to the staging cluster",
            "deploy_service",
            "success",
            0,
            "Canary checkout-service:1.4.2 is healthy on staging (3/3 replicas ready)",
            "",
            ["deploy/checkout-service-canary.log"],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.75),
    ),
    (
        "v-complete-04",
        "validation",
        _fields(
            "CALL-10004",
            "Run the add_customer_region migration on the orders database",
            "run_migration",
            "success",
            0,
            "Applied migration add_customer_region (orders_db); 1 of 1 pending migrations",
            "",
            ["migrations/add_customer_region.sql"],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.62),
    ),
    (
        "v-complete-05",
        "validation",
        _fields(
            "CALL-10005",
            "Back up the billing database to the nightly archive bucket",
            "backup_database",
            "success",
            0,
            "Backup billing_db_2026-10-08.tar.gz uploaded to archive/nightly/",
            "",
            ["archive/nightly/billing_db_2026-10-08.tar.gz"],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.55),
    ),
    (
        "v-partial-01",
        "validation",
        _fields(
            "CALL-10101",
            "Resize all 12 product photos in the autumn catalogue to 800x800",
            "resize_image",
            "partial_success",
            0,
            "Resized 9 of 12 photos to 800x800; 3 skipped: unsupported format (.heic)",
            "",
            ["catalogue/autumn/resized/ (9 files)"],
        ),
        PARTIAL,
        _dist(PARTIAL, 0.80),
    ),
    (
        "v-partial-02",
        "validation",
        _fields(
            "CALL-10102",
            "Compress the 18 uploaded case files into case-4821.zip",
            "compress_archive",
            "partial_success",
            0,
            "Archived 15 of 18 files into case-4821.zip; 3 files were missing from the upload folder",
            "",
            ["case-4821.zip"],
        ),
        PARTIAL,
        _dist(PARTIAL, 0.70),
    ),
    (
        "v-partial-03",
        "validation",
        _fields(
            "CALL-10103",
            "Sync the on-call rotation calendar for next week (7 shifts)",
            "sync_calendar",
            "partial_success",
            0,
            "Synced 5 of 7 shifts; 2 shifts conflicted with an existing event and were left unsynced",
            "",
            [],
        ),
        PARTIAL,
        _dist(PARTIAL, 0.65),
    ),
    (
        "v-partial-04",
        "validation",
        _fields(
            "CALL-10104",
            "Publish the weekly ops report to the shared dashboard (3 sections)",
            "publish_report",
            "partial_success",
            0,
            "Published 2 of 3 sections; the 'incidents' section failed to render",
            "",
            ["dashboard/ops-weekly (2 sections)"],
        ),
        PARTIAL,
        _dist(PARTIAL, 0.58),
    ),
    (
        "v-partial-05-wrong",
        "validation",
        _fields(
            "CALL-10105",
            "Rotate and archive last month's application logs across 4 services",
            "rotate_log",
            "partial_success",
            0,
            "Rotated logs for 3 of 4 services; auth-service log rotation failed: destination full",
            "",
            ["archive/logs/ (3 services)"],
        ),
        PARTIAL,
        # wrong toward unverifiable, and comfortably below the pin below: caught either way.
        # Real, partial evidence hedged away instead of read.
        _dist(UNVERIFIABLE, 0.30),
    ),
    (
        "v-failed-01",
        "validation",
        _fields(
            "CALL-10201",
            "Provision a new build-agent VM in the eu-west pool",
            "provision_vm",
            "failure",
            1,
            "",
            "Error: quota exceeded for eu-west pool (0 of 0 instances available)",
            [],
        ),
        FAILED,
        _dist(FAILED, 0.82),
    ),
    (
        "v-failed-02",
        "validation",
        _fields(
            "CALL-10202",
            "Close ticket SUP-5521 and add a resolution note",
            "update_ticket",
            "failure",
            1,
            "",
            "Error: ticket SUP-5521 not found",
            [],
        ),
        FAILED,
        _dist(FAILED, 0.70),
    ),
    (
        "v-failed-03",
        "validation",
        _fields(
            "CALL-10203",
            "Deploy the invoicing-service canary to the staging cluster",
            "deploy_service",
            "failure",
            1,
            "",
            "Rollout aborted: readiness probe failed after 5 attempts",
            [],
        ),
        FAILED,
        _dist(FAILED, 0.50),
    ),
    (
        "v-failed-04",
        "validation",
        _fields(
            "CALL-10204",
            "Restore the staging database from last night's snapshot",
            "backup_database",
            "failure",
            1,
            "",
            "Error: snapshot 2026-10-07-staging is corrupted and cannot be restored",
            [],
        ),
        FAILED,
        _dist(FAILED, 0.90),
    ),
    (
        "v-failed-05-contradicts",
        "validation",
        _fields(
            "CALL-10205",
            "Write the renewal letters to outbox/renewals_batch7.pdf",
            "write_file",
            "success",
            0,
            "",
            "PermissionError: outbox/ is not writable",
            [],
        ),
        FAILED,
        # The hard case this use case names: reported success, but the evidence contradicts
        # it. The stored answer trusts the reported status instead of the stderr beneath it,
        # and is wrong *and* confident: select_confidence_threshold(target_accuracy=1.0) must
        # set the gate above this confidence to keep validation accuracy perfect, which is
        # exactly what pins the threshold below.
        _dist(COMPLETE, 0.58),
    ),
    (
        "v-unverifiable-01-no-evidence",
        "validation",
        _fields(
            "CALL-10301",
            "Email the churn-risk follow-up to the 'high_risk' segment",
            "send_email",
            "success",
            0,
            "",
            "",
            [],
        ),
        UNVERIFIABLE,
        # The other hard case: a reported success with nothing behind it at all -- no count
        # sent, no artefact, no output of any kind. The evidence cannot show the request was
        # fulfilled, and it cannot show it was not, either.
        _dist(UNVERIFIABLE, 0.72),
    ),
    (
        "v-unverifiable-02",
        "validation",
        _fields(
            "CALL-10302",
            "Back up the analytics database to the nightly archive bucket",
            "backup_database",
            "in_progress",
            None,
            "Backup job submitted (job id 88213)",
            "",
            [],
        ),
        UNVERIFIABLE,
        _dist(UNVERIFIABLE, 0.60),
    ),
    (
        "v-unverifiable-03",
        "validation",
        _fields(
            "CALL-10303",
            "Provision a new build-agent VM in the us-east pool",
            "provision_vm",
            "success",
            0,
            "Instance i-0a2c pending initialization; health check not yet available",
            "",
            [],
        ),
        UNVERIFIABLE,
        _dist(UNVERIFIABLE, 0.44),
    ),
    (
        "v-unverifiable-04",
        "validation",
        _fields(
            "CALL-10304",
            "Update the DNS record for status.example-saas.test to point at the new load balancer",
            "update_ticket",
            "unknown",
            None,
            "",
            "",
            [],
        ),
        UNVERIFIABLE,
        _dist(UNVERIFIABLE, 0.38),
    ),
    # ======================================================================================
    # test -- 19 examples: 5 complete, 4 partial, 5 failed (one the "contradicts" hard case,
    # stored confidently wrong -- the costly error), 5 unverifiable (one the "no evidence" hard
    # case).
    # ======================================================================================
    (
        "t-complete-01",
        "test",
        _fields(
            "CALL-20001",
            "Write the September payroll export to exports/payroll_sept.csv",
            "write_file",
            "success",
            0,
            "Wrote 96 rows to exports/payroll_sept.csv",
            "",
            ["exports/payroll_sept.csv"],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.88),
    ),
    (
        "t-complete-02",
        "test",
        _fields(
            "CALL-20002",
            "Email the onboarding checklist to every new hire added this week (6 people)",
            "send_email",
            "success",
            0,
            "Sent 6 of 6 messages to the 'new_hires_this_week' list",
            "",
            [],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.80),
    ),
    (
        "t-complete-03",
        "test",
        _fields(
            "CALL-20003",
            "Deploy the search-service canary to the staging cluster",
            "deploy_service",
            "success",
            0,
            "Canary search-service:2.1.0 is healthy on staging (4/4 replicas ready)",
            "",
            ["deploy/search-service-canary.log"],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.70),
    ),
    (
        "t-complete-04",
        "test",
        _fields(
            "CALL-20004",
            "Run the add_loyalty_tier migration on the orders database",
            "run_migration",
            "success",
            0,
            "Applied migration add_loyalty_tier (orders_db); 1 of 1 pending migrations",
            "",
            ["migrations/add_loyalty_tier.sql"],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.65),
    ),
    (
        "t-complete-05",
        "test",
        _fields(
            "CALL-20005",
            "Back up the catalogue database to the nightly archive bucket",
            "backup_database",
            "success",
            0,
            "Backup catalogue_db_2026-10-08.tar.gz uploaded to archive/nightly/",
            "",
            ["archive/nightly/catalogue_db_2026-10-08.tar.gz"],
        ),
        COMPLETE,
        _dist(COMPLETE, 0.52),
    ),
    (
        "t-partial-01",
        "test",
        _fields(
            "CALL-20101",
            "Resize all 20 product photos in the winter catalogue to 800x800",
            "resize_image",
            "partial_success",
            0,
            "Resized 17 of 20 photos to 800x800; 3 skipped: unsupported format (.heic)",
            "",
            ["catalogue/winter/resized/ (17 files)"],
        ),
        PARTIAL,
        _dist(PARTIAL, 0.78),
    ),
    (
        "t-partial-02",
        "test",
        _fields(
            "CALL-20102",
            "Compress the 10 uploaded case files into case-5190.zip",
            "compress_archive",
            "partial_success",
            0,
            "Archived 8 of 10 files into case-5190.zip; 2 files were missing from the upload folder",
            "",
            ["case-5190.zip"],
        ),
        PARTIAL,
        _dist(PARTIAL, 0.66),
    ),
    (
        "t-partial-03",
        "test",
        _fields(
            "CALL-20103",
            "Publish the weekly ops report to the shared dashboard (4 sections)",
            "publish_report",
            "partial_success",
            0,
            "Published 3 of 4 sections; the 'forecast' section failed to render",
            "",
            ["dashboard/ops-weekly (3 sections)"],
        ),
        PARTIAL,
        _dist(PARTIAL, 0.55),
    ),
    (
        "t-partial-04-wrong",
        "test",
        _fields(
            "CALL-20104",
            "Sync the on-call rotation calendar for next week (6 shifts)",
            "sync_calendar",
            "partial_success",
            0,
            "Synced 4 of 6 shifts; 2 shifts conflicted with an existing event and were left unsynced",
            "",
            [],
        ),
        PARTIAL,
        # wrong toward unverifiable, below the gate: caught either way. Real, partial evidence
        # hedged away instead of read -- the same mistake as the validation case above.
        _dist(UNVERIFIABLE, 0.35),
    ),
    (
        "t-failed-01",
        "test",
        _fields(
            "CALL-20201",
            "Provision a new build-agent VM in the ap-south pool",
            "provision_vm",
            "failure",
            1,
            "",
            "Error: quota exceeded for ap-south pool (0 of 0 instances available)",
            [],
        ),
        FAILED,
        _dist(FAILED, 0.84),
    ),
    (
        "t-failed-02",
        "test",
        _fields(
            "CALL-20202",
            "Close ticket SUP-6630 and add a resolution note",
            "update_ticket",
            "failure",
            1,
            "",
            "Error: ticket SUP-6630 not found",
            [],
        ),
        FAILED,
        _dist(FAILED, 0.72),
    ),
    (
        "t-failed-03",
        "test",
        _fields(
            "CALL-20203",
            "Deploy the billing-service canary to the staging cluster",
            "deploy_service",
            "failure",
            1,
            "",
            "Rollout aborted: readiness probe failed after 5 attempts",
            [],
        ),
        FAILED,
        _dist(FAILED, 0.48),
    ),
    (
        "t-failed-04",
        "test",
        _fields(
            "CALL-20204",
            "Restore the production database from last night's snapshot",
            "backup_database",
            "failure",
            1,
            "",
            "Error: snapshot 2026-10-07-production is corrupted and cannot be restored",
            [],
        ),
        FAILED,
        _dist(FAILED, 0.90),
    ),
    (
        "t-failed-05-contradicts",
        "test",
        _fields(
            "CALL-20205",
            "Write the renewal letters to outbox/renewals_batch12.pdf",
            "write_file",
            "success",
            0,
            "",
            "PermissionError: outbox/ is not writable",
            [],
        ),
        FAILED,
        # The costly error this recipe is built to show: the tool reports success, the
        # evidence (stderr) contradicts it, and the stored answer is wrong *and* confidently
        # above the gate -- a false `complete` left standing, exactly the mistake
        # CONTRIBUTING.md section 4 asks every option to be gated against.
        _dist(COMPLETE, 0.75),
    ),
    (
        "t-unverifiable-01-no-evidence",
        "test",
        _fields(
            "CALL-20301",
            "Email the win-back offer to the 'lapsed_90d' segment",
            "send_email",
            "success",
            0,
            "",
            "",
            [],
        ),
        UNVERIFIABLE,
        _dist(UNVERIFIABLE, 0.70),
    ),
    (
        "t-unverifiable-02",
        "test",
        _fields(
            "CALL-20302",
            "Back up the reporting database to the nightly archive bucket",
            "backup_database",
            "in_progress",
            None,
            "Backup job submitted (job id 91847)",
            "",
            [],
        ),
        UNVERIFIABLE,
        _dist(UNVERIFIABLE, 0.63),
    ),
    (
        "t-unverifiable-03",
        "test",
        _fields(
            "CALL-20303",
            "Provision a new build-agent VM in the sa-east pool",
            "provision_vm",
            "success",
            0,
            "Instance i-19fe pending initialization; health check not yet available",
            "",
            [],
        ),
        UNVERIFIABLE,
        _dist(UNVERIFIABLE, 0.47),
    ),
    (
        "t-unverifiable-04",
        "test",
        _fields(
            "CALL-20304",
            "Update the DNS record for api.example-saas.test to point at the new load balancer",
            "update_ticket",
            "unknown",
            None,
            "",
            "",
            [],
        ),
        UNVERIFIABLE,
        _dist(UNVERIFIABLE, 0.41),
    ),
    (
        "t-unverifiable-05",
        "test",
        _fields(
            "CALL-20305",
            "Rotate and archive last month's application logs across 3 services",
            "rotate_log",
            "unknown",
            None,
            "",
            "",
            [],
        ),
        UNVERIFIABLE,
        _dist(UNVERIFIABLE, 0.35),
    ),
    # -- demo: shown to the reader, never scored. ------------------------------------------
    (
        "demo-01-no-evidence",
        "demo",
        _fields(
            "CALL-30001",
            "Email the renewal reminder to the 'expiring_7d' segment",
            "send_email",
            "success",
            0,
            "",
            "",
            [],
        ),
        None,
        _dist(UNVERIFIABLE, 0.68),
    ),
    (
        "demo-02-contradicts",
        "demo",
        _fields(
            "CALL-30002",
            "Write the renewal letters to outbox/renewals_batch3.pdf",
            "write_file",
            "success",
            0,
            "",
            "PermissionError: outbox/ is not writable",
            [],
        ),
        None,
        _dist(COMPLETE, 0.70),  # the same confident mistake, shown up close
    ),
]  # fmt: skip


def answers_for(spec, provenance: Provenance):
    """``{"outcome": ChoiceAnswer}`` from a row's probability tuple, in ``OUTCOMES`` order."""
    probabilities = dict(zip(OUTCOMES, spec, strict=True))
    return {"outcome": ChoiceAnswer.from_probabilities(probabilities, provenance)}


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
