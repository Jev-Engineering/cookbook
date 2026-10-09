"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 19.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic and deliberately imperfect: some are wrong, including some wrong
*and* confident, so the evaluation in the notebook has something real to find. The replay keys
come from the same ``build_state`` and ``build_questions`` the notebook uses, by way of
``helpers.trim_log``: each row carries the untrimmed ``full_log`` Python never sends to Jev, so
the trimming the notebook shows is the trimming the replay key is actually built from, not a
separate illustration of it.

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
OUTCOMES = (
    helpers.OUTCOMES
)  # (test_regression, dependency_problem, infrastructure_failure, unknown)


# --------------------------------------------------------------------------------------
# Log bodies. Nothing here is a real CI run: every log is written for this recipe, and the
# untrimmed text is kept in fixtures/inputs.jsonl so a reader can see what helpers.trim_log
# actually cuts away.
# --------------------------------------------------------------------------------------


def _regression_log(test_path, old, new, collected=128):
    """A genuine behaviour change: an assertion about the code's own output, nothing else."""
    return "\n".join(
        [
            "$ pytest -q",
            "============================= test session starts ==============================",
            f"collected {collected} items",
            "tests/ ....................F.......................",
            "",
            "=================================== FAILURES ====================================",
            f"____________________________ {test_path} ____________________________",
            f"    assert total == {old}",
            f"E   AssertionError: assert {new} == {old}",
            f"FAILED {test_path} - AssertionError: assert {new} == {old}",
            f"1 failed, {collected - 1} passed in 21.38s",
        ]
    )


def _dependency_install_log(package, detail):
    """A dependency problem caught before any test runs: pip never finishes installing."""
    return "\n".join(
        [
            "$ pip install -r requirements.txt",
            f"Collecting {package}",
            f"ERROR: {detail}",
            "##[error]Process completed with exit code 1.",
        ]
    )


def _dependency_collection_log(package, detail, collected_items=0):
    """A dependency problem caught at collection: pytest never gets to run anything."""
    return "\n".join(
        [
            "$ pytest -q",
            "============================= test session starts ==============================",
            f"collected {collected_items} items / 1 error",
            "=================================== ERRORS ====================================",
            f"____________________ ERROR collecting tests for {package} ____________________",
            f"{detail}",
            "!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!!!",
        ]
    )


def _dependency_surfaces_log(package, detail, test_path, collected=128):
    """The hard case: the root cause is a dependency problem, but it surfaces as a failing
    test, not as an install error. A reader (or a model) that only reads "FAILED tests/..."
    without the line beneath it can mistake this for a behaviour change."""
    return "\n".join(
        [
            "$ pytest -q",
            "============================= test session starts ==============================",
            f"collected {collected} items",
            "tests/ ..............F.........",
            "",
            "=================================== FAILURES ====================================",
            f"____________________________ {test_path} ____________________________",
            f"    import {package}",
            f"E   ModuleNotFoundError: {detail}",
            f"FAILED {test_path} - ModuleNotFoundError: {detail}",
            f"1 failed, {collected - 1} passed in 19.02s",
        ]
    )


def _dependency_fartrim_log(
    decoy_test, decoy_old, decoy_new, package, detail, test_path, filler=22
):
    """The trimming hard case: an unrelated test fails first, near the top of the log, and the
    real, decisive dependency error sits far below it, after many lines of unrelated passing
    tests. A window kept only around the first failure would miss it."""
    lines = [
        "$ pytest -q",
        "============================= test session starts ==============================",
        "collected 212 items",
        "tests/ .......F......................................",
        "",
        "=================================== FAILURES ====================================",
        f"____________________________ {decoy_test} ____________________________",
        f"    assert total == {decoy_old}",
        f"E   AssertionError: assert {decoy_new} == {decoy_old}",
        f"FAILED {decoy_test} - AssertionError: assert {decoy_new} == {decoy_old}",
    ]
    for i in range(filler):
        lines.append(f"tests/test_module_{i:02d}.py ........................... [{40 + i:3d}%]")
    lines += [
        "",
        "=================================== FAILURES ====================================",
        f"____________________________ {test_path} ____________________________",
        f"    import {package}",
        f"E   ModuleNotFoundError: {detail}",
        f"FAILED {test_path} - ModuleNotFoundError: {detail}",
        "2 failed, 210 passed in 58.21s",
    ]
    return "\n".join(lines)


def _infra_log(detail, collected=96):
    """An infrastructure failure before or outside any test result: the runner itself failed."""
    return "\n".join(
        [
            "$ pytest -q",
            "============================= test session starts ==============================",
            f"collected {collected} items",
            "tests/ ................",
            f"##[error]{detail}",
            "##[error]Process completed with exit code 1.",
        ]
    )


def _infra_looks_like_test_log(test_path, detail, collected=96):
    """The hard case: the runner was lost mid-test, and the only summary line left behind
    reads like an ordinary test failure."""
    return "\n".join(
        [
            "$ pytest -q",
            "============================= test session starts ==============================",
            f"collected {collected} items",
            "tests/ .......... (running)",
            f"____________________________ {test_path} ____________________________",
            f"##[error]{detail}",
            f"FAILED {test_path} - runner connection lost",
            "##[error]Process completed with exit code 1.",
        ]
    )


def _flaky_log(test_path, old, new, rerun=1):
    """A test fails once and passes on an automatic rerun, with no other signal. The flaky
    resolution is folded into the FAILED line itself so helpers.trim_log's one-line context
    keeps it next to the failure, not past the edge of the window."""
    return "\n".join(
        [
            "$ pytest -q",
            "============================= test session starts ==============================",
            "collected 140 items",
            "tests/ ................................",
            "",
            "=================================== FAILURES ====================================",
            f"____________________________ {test_path} ____________________________",
            f"E   AssertionError: assert {new} {'==' if new != old else '>='} {old}",
            f"FAILED {test_path} - AssertionError (flaky: passed on rerun {rerun}/{rerun})",
            "139 passed, 1 flaky test rerun and passed in 33.04s",
        ]
    )


def _conflicting_log(warning, test_path, old, new, rerun=1):
    """Two weak, non-matching signals in one log: a non-fatal dependency-resolver warning that
    never blocks the install, and a flaky test that passes on rerun. Neither is decisive."""
    return "\n".join(
        [
            "$ pip install -r requirements.txt",
            f"WARNING: {warning}",
            "$ pytest -q",
            "collected 140 items",
            "tests/ ................................",
            "=================================== FAILURES ====================================",
            f"____________________________ {test_path} ____________________________",
            f"E   AssertionError: assert {new} {'==' if new != old else '>='} {old}",
            f"FAILED {test_path} - AssertionError (flaky: passed on rerun {rerun}/{rerun})",
            "139 passed, 1 flaky test rerun and passed in 29.91s",
        ]
    )


def _inconclusive_log(note):
    """No failure, no error, no clear signal at all: nothing here matches a decisive pattern,
    so helpers.trim_log falls back to the first lines of the log."""
    return "\n".join(
        [
            "$ pytest -q",
            "============================= test session starts ==============================",
            "collected 140 items",
            f"{note}",
            "##[warning]No test results were produced for this run.",
        ]
    )


def _fields(build_id, full_log):
    return {"build_id": build_id, "full_log": full_log}


def _dist(top, p_max):
    """Probabilities over OUTCOMES: ``p_max`` on ``top``, the rest split evenly."""
    rest = (1.0 - p_max) / 3.0
    return tuple(p_max if name == top else rest for name in OUTCOMES)


TEST_REGRESSION, DEPENDENCY_PROBLEM, INFRASTRUCTURE_FAILURE, UNKNOWN = OUTCOMES

# (id, split, fields, gold label or None for a demo example, probabilities over OUTCOMES)
ROWS = [
    # -- test_regression: a real behaviour change, nothing else in the log. --------------
    (
        "v-tr-01",
        "validation",
        _fields("CI-10101", _regression_log("tests/test_pricing.py::test_total_with_discount", 42.50, 45.00)),
        TEST_REGRESSION,
        _dist(TEST_REGRESSION, 0.88),
    ),
    (
        "v-tr-02",
        "validation",
        _fields("CI-10102", _regression_log("tests/test_checkout.py::test_shipping_fee", 5.99, 7.99)),
        TEST_REGRESSION,
        _dist(TEST_REGRESSION, 0.75),
    ),
    (
        "v-tr-03",
        "validation",
        _fields("CI-10103", _regression_log("tests/test_inventory.py::test_stock_decrement", 10, 9)),
        TEST_REGRESSION,
        _dist(TEST_REGRESSION, 0.60),
    ),
    (
        "v-tr-04",
        "validation",
        _fields("CI-10104", _regression_log("tests/test_auth.py::test_session_expiry_minutes", 30, 15)),
        TEST_REGRESSION,
        _dist(TEST_REGRESSION, 0.70),
    ),
    (
        "v-tr-05",
        "validation",
        _fields("CI-10105", _regression_log("tests/test_reporting.py::test_monthly_total", 1200.00, 1150.00)),
        TEST_REGRESSION,
        _dist(TEST_REGRESSION, 0.45),
    ),
    # -- dependency_problem: install failures, a collection error, the hard cases. --------
    (
        "v-dep-01",
        "validation",
        _fields(
            "CI-10201",
            _dependency_install_log("acme-sdk", "No matching distribution found for acme-sdk==4.2.0"),
        ),
        DEPENDENCY_PROBLEM,
        _dist(DEPENDENCY_PROBLEM, 0.80),
    ),
    (
        "v-dep-02",
        "validation",
        _fields(
            "CI-10202",
            _dependency_collection_log(
                "widget_core",
                "ImportError: cannot import name 'WidgetCore' from 'widget_core' (unknown location)",
            ),
        ),
        DEPENDENCY_PROBLEM,
        _dist(DEPENDENCY_PROBLEM, 0.58),
    ),
    (
        "v-dep-03-surfaces",
        "validation",
        _fields(
            "CI-10203",
            _dependency_surfaces_log(
                "payments_sdk",
                "No module named 'payments_sdk.v2'",
                "tests/test_payment_flow.py::test_authorize_and_capture",
            ),
        ),
        DEPENDENCY_PROBLEM,
        _dist(TEST_REGRESSION, 0.82),  # wrong on purpose, and confidently so
    ),
    (
        "v-dep-04-fartrim",
        "validation",
        _fields(
            "CI-10204",
            _dependency_fartrim_log(
                "tests/test_timezone_utils.py::test_dst_rounding",
                3.14,
                3.15,
                "geo_sdk",
                "No module named 'geo_sdk.regions'",
                "tests/test_region_lookup.py::test_resolve_region_code",
            ),
        ),
        DEPENDENCY_PROBLEM,
        _dist(DEPENDENCY_PROBLEM, 0.62),
    ),
    (
        "v-dep-05",
        "validation",
        _fields(
            "CI-10205",
            _dependency_install_log(
                "cache_layer", "Could not find a version that satisfies the requirement cache_layer>=3.0,<4.0"
            ),
        ),
        DEPENDENCY_PROBLEM,
        _dist(DEPENDENCY_PROBLEM, 0.50),
    ),
    # -- infrastructure_failure: the runner itself, and the hard case that looks like a test. --
    (
        "v-infra-01",
        "validation",
        _fields("CI-10301", _infra_log("The job was terminated: exit code 137 (out of memory).")),
        INFRASTRUCTURE_FAILURE,
        _dist(INFRASTRUCTURE_FAILURE, 0.78),
    ),
    (
        "v-infra-02",
        "validation",
        _fields(
            "CI-10302",
            _infra_log("The runner has received a shutdown signal and will be terminated."),
        ),
        INFRASTRUCTURE_FAILURE,
        _dist(INFRASTRUCTURE_FAILURE, 0.66),
    ),
    (
        "v-infra-03",
        "validation",
        _fields("CI-10303", _infra_log("This step has timed out after 45 minutes.")),
        INFRASTRUCTURE_FAILURE,
        _dist(INFRASTRUCTURE_FAILURE, 0.55),
    ),
    (
        "v-infra-04-looks-like-test",
        "validation",
        _fields(
            "CI-10304",
            _infra_looks_like_test_log(
                "tests/test_batch_export.py::test_full_export_completes",
                "Lost communication with the runner. The job exceeded the maximum execution "
                "time and was automatically canceled.",
            ),
        ),
        INFRASTRUCTURE_FAILURE,
        _dist(INFRASTRUCTURE_FAILURE, 0.60),
    ),
    (
        "v-infra-05",
        "validation",
        _fields(
            "CI-10305",
            _infra_log("Connection reset by peer while uploading test artifacts."),
        ),
        INFRASTRUCTURE_FAILURE,
        _dist(TEST_REGRESSION, 0.35),  # wrong, but low confidence: the gate should catch it
    ),
    # -- unknown: flaky, inconclusive, or genuinely conflicting logs. ---------------------
    (
        "v-unknown-01",
        "validation",
        _fields("CI-10401", _flaky_log("tests/test_webhook_delivery.py::test_retry_on_timeout", True, False)),
        UNKNOWN,
        _dist(UNKNOWN, 0.70),
    ),
    (
        "v-unknown-02",
        "validation",
        _fields(
            "CI-10402",
            _inconclusive_log("This run was superseded by a newer commit before any tests finished."),
        ),
        UNKNOWN,
        _dist(UNKNOWN, 0.55),
    ),
    (
        "v-unknown-03",
        "validation",
        _fields(
            "CI-10403",
            _conflicting_log(
                "pip's dependency resolver does not currently account for all packages (non-fatal)",
                "tests/test_search_ranking.py::test_top_result_stable",
                True,
                False,
            ),
        ),
        UNKNOWN,
        _dist(UNKNOWN, 0.40),
    ),
    (
        "v-unknown-04",
        "validation",
        _fields(
            "CI-10404",
            _flaky_log("tests/test_session_cache.py::test_cache_hit_rate_within_bounds", 0.95, 0.91, rerun=2),
        ),
        UNKNOWN,
        _dist(UNKNOWN, 0.30),
    ),
    # ======================================================================================
    # test
    # ======================================================================================
    (
        "t-tr-01",
        "test",
        _fields("CI-20101", _regression_log("tests/test_billing.py::test_tax_rate", 0.08, 0.075)),
        TEST_REGRESSION,
        _dist(TEST_REGRESSION, 0.84),
    ),
    (
        "t-tr-02",
        "test",
        _fields("CI-20102", _regression_log("tests/test_cart.py::test_item_count_after_remove", 3, 2)),
        TEST_REGRESSION,
        _dist(TEST_REGRESSION, 0.68),
    ),
    (
        "t-tr-03",
        "test",
        _fields("CI-20103", _regression_log("tests/test_shipping.py::test_delivery_estimate_days", 5, 7)),
        TEST_REGRESSION,
        _dist(TEST_REGRESSION, 0.52),
    ),
    (
        "t-tr-04",
        "test",
        _fields("CI-20104", _regression_log("tests/test_notifications.py::test_digest_frequency", 7, 14)),
        TEST_REGRESSION,
        _dist(TEST_REGRESSION, 0.90),
    ),
    (
        "t-tr-05-wrong",
        "test",
        _fields("CI-20105", _regression_log("tests/test_loyalty_points.py::test_points_awarded_per_purchase", 100, 80)),
        TEST_REGRESSION,
        _dist(UNKNOWN, 0.85),  # wrong and confident: shows the cost of never gating `unknown`
    ),
    (
        "t-dep-01",
        "test",
        _fields(
            "CI-20201",
            _dependency_install_log("search_index", "No matching distribution found for search_index==1.8.3"),
        ),
        DEPENDENCY_PROBLEM,
        _dist(DEPENDENCY_PROBLEM, 0.72),
    ),
    (
        "t-dep-02-surfaces",
        "test",
        _fields(
            "CI-20202",
            _dependency_surfaces_log(
                "media_pipeline",
                "No module named 'media_pipeline.codecs'",
                "tests/test_video_ingest.py::test_transcode_job_completes",
            ),
        ),
        DEPENDENCY_PROBLEM,
        _dist(TEST_REGRESSION, 0.85),  # the hard case the issue names: wrong, and confident
    ),
    (
        "t-dep-03-fartrim",
        "test",
        _fields(
            "CI-20203",
            _dependency_fartrim_log(
                "tests/test_currency_utils.py::test_rounding_mode",
                19.99,
                20.00,
                "billing_sdk",
                "No module named 'billing_sdk.tax'",
                "tests/test_invoice_totals.py::test_apply_tax",
            ),
        ),
        DEPENDENCY_PROBLEM,
        _dist(DEPENDENCY_PROBLEM, 0.58),
    ),
    (
        "t-dep-04",
        "test",
        _fields(
            "CI-20204",
            _dependency_collection_log(
                "queue_client",
                "ImportError: cannot import name 'QueueClient' from 'queue_client' (unknown location)",
            ),
        ),
        DEPENDENCY_PROBLEM,
        _dist(DEPENDENCY_PROBLEM, 0.47),
    ),
    (
        "t-dep-05",
        "test",
        _fields(
            "CI-20205",
            _dependency_install_log("data_connector", "ERESOLVE could not resolve dependency tree for data_connector@2.4.0"),
        ),
        DEPENDENCY_PROBLEM,
        _dist(DEPENDENCY_PROBLEM, 0.63),
    ),
    (
        "t-infra-01",
        "test",
        _fields(
            "CI-20301",
            _infra_log("The self-hosted runner lost communication with the server; the job will be requeued."),
        ),
        INFRASTRUCTURE_FAILURE,
        _dist(INFRASTRUCTURE_FAILURE, 0.80),
    ),
    (
        "t-infra-02",
        "test",
        _fields("CI-20302", _infra_log("This step has timed out after 60 minutes.")),
        INFRASTRUCTURE_FAILURE,
        _dist(INFRASTRUCTURE_FAILURE, 0.68),
    ),
    (
        "t-infra-03",
        "test",
        _fields("CI-20303", _infra_log("Process completed with exit code 143 (terminated).")),
        INFRASTRUCTURE_FAILURE,
        _dist(INFRASTRUCTURE_FAILURE, 0.50),
    ),
    (
        "t-infra-04-looks-like-test",
        "test",
        _fields(
            "CI-20304",
            _infra_looks_like_test_log(
                "tests/test_report_generation.py::test_nightly_report_completes",
                "The operation was canceled. Lost communication with the runner mid-test.",
            ),
        ),
        INFRASTRUCTURE_FAILURE,
        _dist(INFRASTRUCTURE_FAILURE, 0.57),
    ),
    (
        "t-infra-05",
        "test",
        _fields("CI-20305", _infra_log("The runner has received a shutdown signal during cleanup.")),
        INFRASTRUCTURE_FAILURE,
        _dist(INFRASTRUCTURE_FAILURE, 0.73),
    ),
    (
        "t-unknown-01",
        "test",
        _fields("CI-20401", _flaky_log("tests/test_email_delivery.py::test_bounce_handling", True, False)),
        UNKNOWN,
        _dist(UNKNOWN, 0.65),
    ),
    (
        "t-unknown-02",
        "test",
        _fields(
            "CI-20402",
            _inconclusive_log("This workflow run was manually canceled before the test job finished."),
        ),
        UNKNOWN,
        _dist(UNKNOWN, 0.48),
    ),
    (
        "t-unknown-03",
        "test",
        _fields(
            "CI-20403",
            _conflicting_log(
                "pip's dependency resolver does not currently account for all packages (non-fatal)",
                "tests/test_recommendation_order.py::test_top_pick_consistent",
                True,
                False,
            ),
        ),
        UNKNOWN,
        _dist(UNKNOWN, 0.33),
    ),
    (
        "t-unknown-04",
        "test",
        _fields(
            "CI-20404",
            _flaky_log("tests/test_rate_limiter.py::test_requests_per_minute_within_bounds", 60, 58, rerun=2),
        ),
        UNKNOWN,
        _dist(UNKNOWN, 0.52),
    ),
    # -- demo: shown to the reader, never scored. ------------------------------------------
    (
        "demo-01-dep-surfaces",
        "demo",
        _fields(
            "CI-30001",
            _dependency_surfaces_log(
                "support_sdk",
                "No module named 'support_sdk.v3'",
                "tests/test_ticket_sync.py::test_sync_marks_resolved",
            ),
        ),
        None,
        _dist(TEST_REGRESSION, 0.78),  # the same confident mistake, shown up close
    ),
    (
        "demo-02-unknown-flaky",
        "demo",
        _fields(
            "CI-30002",
            _flaky_log("tests/test_notification_batch.py::test_batch_dedup", True, False),
        ),
        None,
        _dist(UNKNOWN, 0.60),
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
