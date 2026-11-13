"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 51.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic: written by hand as probabilities, not produced by a model. Some are
deliberately wrong, one of them confidently, so the evaluation in the notebook has something to
find. The transcripts are invented for this recipe; the replay keys come from the same
``build_state`` and ``build_questions`` the notebook uses.

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
    Provenance,
    dump_responses,
    load_helpers,
    replay_key,
)

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# Each transcript is one recorded agent run: a goal and its turns, oldest first. Every turn
# after the first is a checkpoint, one request each: Jev sees the goal and the turns up to and
# including that checkpoint. A checkpoint's entry is
#     (gold label or None for a demo transcript, (top option, top %, second option, second %))
# The stored answer gives the top option and the second option those whole-number percentages;
# the rest is shared out evenly over the other three options (any leftover percent goes to the
# earliest of them in OPTIONS order), so every probability is an exact multiple of 1/100.
A, R, G, C, U = "advancing", "repeating", "regressing", "complete", "unclear"


def _turn(action, result, note):
    return {"action": action, "result": result, "note": note}


TRANSCRIPTS = [
    # --- validation -------------------------------------------------------------------------
    ("v-date-tests", "validation", "R-101", "Make the failing date-parsing tests pass.", [
        _turn("run_tests tests/test_dates.py",
              "3 failed, 9 passed: test_parse_date, test_parse_time, test_round_trip",
              "Three tests fail; starting with parse_date."),
        _turn("open src/dates.py lines 10-40",
              "parse_date uses the format '%d/%m/%Y'; the failing test passes '2026-10-04'",
              "Found a format mismatch."),
        _turn("edit src/dates.py: parse_date format '%d/%m/%Y' -> '%Y-%m-%d'",
              "saved src/dates.py (1 line changed)", "Fixed the reader's format."),
        _turn("run_tests tests/test_dates.py", "1 failed, 11 passed: test_round_trip",
              "Down to one failure."),
        _turn("open src/dates.py lines 41-60",
              "format_date still writes '%d/%m/%Y', so the round trip reads back a different date",
              "The writer has the same mismatch."),
        _turn("edit src/dates.py: format_date format '%d/%m/%Y' -> '%Y-%m-%d'",
              "saved src/dates.py (1 line changed)", "Fixed the writer too."),
        _turn("run_tests tests/test_dates.py", "12 passed", "All date tests pass."),
    ], [
        (A, (A, 84, U, 6)), (A, (A, 76, C, 10)), (A, (A, 84, C, 8)), (A, (A, 68, R, 14)),
        (A, (A, 60, R, 24)), (C, (C, 84, A, 8)),
    ]),
    ("v-install-loop", "validation", "R-102",
     "Install the project's dependencies into the build environment.", [
        _turn("pip install -r requirements.txt",
              "ERROR: No matching distribution found for numpyy==2.1",
              "Install failed on one package."),
        _turn("pip install -r requirements.txt",
              "ERROR: No matching distribution found for numpyy==2.1", "Retrying the install."),
        _turn("pip install -r requirements.txt --no-cache-dir",
              "ERROR: No matching distribution found for numpyy==2.1",
              "Trying without the cache."),
        _turn("pip install -r requirements.txt",
              "ERROR: No matching distribution found for numpyy==2.1", "One more attempt."),
    ], [
        (R, (R, 84, A, 6)), (R, (R, 68, A, 16)), (R, (R, 92, A, 5)),
    ]),
    ("v-timeout-search", "validation", "R-103", "Find where the session timeout is configured.", [
        _turn("search 'session_timeout' in config/", "no matches",
              "Not in config/ under that name."),
        _turn("search 'sessionTimeout' in src/",
              "src/settings.ts:14  sessionTimeout: env('SESSION_TTL')",
              "It reads an environment variable."),
        _turn("search 'SESSION_TTL' in config/", "no matches",
              "The variable is not set in config/."),
        _turn("grep -rn SESSION_TTL config/", "no matches", "Double-checking with grep."),
        _turn("find config -type f | xargs grep -n SESSION_TTL", "no matches",
              "Checking every file under config/ this time."),
        _turn("search 'SESSION_TTL' in deploy/", "deploy/staging.env:3  SESSION_TTL=1800",
              "Found it in the deploy environment file."),
    ], [
        (A, (A, 84, R, 6)), (A, (A, 60, R, 20)), (R, (A, 52, R, 36)), (R, (R, 76, A, 12)),
        (C, (C, 76, A, 16)),
    ]),
    ("v-lint-regress", "validation", "R-104",
     "Make the lint step pass without changing the program's behaviour.", [
        _turn("run lint", "12 problems in 4 files", "Starting the lint cleanup."),
        _turn("run lint --fix", "3 problems in 1 file: src/legacy_shim.py",
              "Auto-fix handled most of them."),
        _turn("run_tests", "31 passed", "Behaviour unchanged so far."),
        _turn("delete src/legacy_shim.py", "deleted 1 file; lint: 0 problems",
              "Lint is clean, task done!"),
        _turn("run_tests", "6 failed, 25 passed: ImportError: No module named 'legacy_shim'",
              "A few tests look flaky."),
    ], [
        (A, (A, 84, C, 6)), (A, (A, 76, C, 12)), (G, (C, 52, G, 30)), (G, (G, 84, R, 6)),
    ]),
    ("v-usage-report", "validation", "R-105",
     "Write the October usage report to reports/usage-2026-10.csv.", [
        _turn("query usage_by_account month=2026-10", "timed out after 30 s",
              "The query is slow."),
        _turn("query usage_by_account month=2026-10", "timed out after 30 s",
              "Great progress, the query is almost done."),
        _turn("query usage_by_account month=2026-10 limit=1000 offset=0",
              "1000 rows returned in 4 s", "Paging the query instead."),
        _turn("query usage_by_account month=2026-10 limit=1000 offset=1000",
              "843 rows returned in 3 s; no more rows", "Second and last page."),
        _turn("write reports/usage-2026-10.csv",
              "wrote 1843 rows; matches the query's total of 1843", "Report written."),
    ], [
        (R, (R, 76, A, 14)), (A, (A, 84, R, 6)), (A, (A, 60, R, 28)), (C, (C, 84, A, 6)),
    ]),
    ("v-table-migration", "validation", "R-106",
     "Migrate the eight customer tables to the new schema.", [
        _turn("migrate table accounts", "accounts: 1200 rows migrated, checks passed",
              "1 of 8 done."),
        _turn("migrate table contacts", "contacts: 3400 rows migrated, checks passed",
              "2 of 8 done."),
        _turn("migrate table orders", "orders: 9100 rows migrated, checks passed",
              "3 of 8 done."),
        _turn("migrate table orders_archive",
              "orders_archive: 22000 rows migrated, checks passed", "4 of 8 done."),
        _turn("migrate table invoices", "(output truncated)", "5 of 8 done."),
        _turn("migrate table payments", "payments: 5100 rows migrated, checks passed",
              "6 of 8 done."),
        _turn("migrate table refunds", "refunds: 300 rows migrated, checks passed",
              "7 of 8 done."),
        _turn("migrate table notes", "notes: 700 rows migrated, checks passed",
              "All 8 done."),
    ], [
        (A, (A, 84, R, 6)), (A, (A, 84, R, 6)), (A, (R, 44, A, 40)), (U, (U, 60, A, 24)),
        (A, (A, 76, R, 12)), (A, (A, 84, C, 6)), (A, (C, 44, A, 36)),
    ]),
    # --- test -------------------------------------------------------------------------------
    ("t-cli-flag", "test", "R-201",
     "Rename the CLI flag --dry to --dry-run, keeping --dry working as an alias.", [
        _turn("search '--dry' in src/", "src/cli.py:22 and src/cli.py:57",
              "Two places to change."),
        _turn("edit src/cli.py: add '--dry-run' with '--dry' as an alias",
              "saved src/cli.py (3 lines changed)", "Added the new flag."),
        _turn("edit src/cli.py: update the help text to list '--dry-run'",
              "saved src/cli.py (1 line changed)", "Updated the help text."),
        _turn("run_tests tests/test_cli.py", "15 passed, including test_dry_alias",
              "Done."),
    ], [
        (A, (A, 84, C, 6)), (A, (A, 76, R, 12)), (C, (C, 76, A, 12)),
    ]),
    ("t-log-forbidden", "test", "R-202", "Download the build log for job 4417.", [
        _turn("fetch_log job=4417", "403 Forbidden: the token lacks the 'logs:read' scope",
              "Permission problem."),
        _turn("fetch_log job=4417", "403 Forbidden: the token lacks the 'logs:read' scope",
              "Trying again."),
        _turn("fetch_log job=4417 retries=3",
              "403 Forbidden: the token lacks the 'logs:read' scope", "Added retries."),
        _turn("fetch_log job=4417", "403 Forbidden: the token lacks the 'logs:read' scope",
              "Once more."),
    ], [
        (R, (R, 84, A, 6)), (R, (R, 76, A, 12)), (R, (R, 92, A, 5)),
    ]),
    ("t-retry-search", "test", "R-203", "Find where the HTTP client's retry limit is set.", [
        _turn("search 'max_retries' in src/",
              "src/http/client.py:31  max_retries = config.get('retries')",
              "It comes from config."),
        _turn("search 'retries' in config/", "config/base.yaml:8  retries: ${RETRY_LIMIT}",
              "Config reads an environment variable."),
        _turn("search 'RETRY_LIMIT' in config/", "no matches",
              "The variable is not set in config/."),
        _turn("grep -rn RETRY_LIMIT config/", "no matches", "Looking more carefully."),
        _turn("grep -rni retry_limit config/", "no matches", "Case-insensitive this time."),
        _turn("search 'RETRY_LIMIT' in deploy/", "deploy/prod.env:5  RETRY_LIMIT=4",
              "Found it in the production environment file."),
    ], [
        (A, (A, 84, R, 6)), (A, (A, 68, R, 16)), (R, (A, 76, R, 12)), (R, (R, 68, A, 20)),
        (C, (C, 84, A, 6)),
    ]),
    ("t-resize-memory", "test", "R-204",
     "Speed up the image resize job without losing any output.", [
        _turn("profile resize_job", "200 images in 41 s on one thread", "Single-threaded."),
        _turn("set resize_job threads=8; run resize_job", "200 images in 9 s; 200 written",
              "Much faster."),
        _turn("set resize_job threads=64; run resize_job",
              "out of memory after 12 images; 12 written", "Even faster per image!"),
    ], [
        (A, (A, 84, C, 6)), (G, (G, 76, A, 14)),
    ]),
    ("t-backup-space", "test", "R-205", "Make the nightly backup job succeed.", [
        _turn("run backup_job", "failed: no space left on /backup", "The disk is full."),
        _turn("delete backups older than 30 days on /backup", "freed 120 GB; 40 GB free",
              "Made room."),
        _turn("run backup_job", "failed: no space left on /backup (needs 180 GB, 40 GB free)",
              "Backup complete."),
        _turn("move archives older than 7 days to cold storage", "moved 160 GB; 200 GB free",
              "Made more room."),
        _turn("run backup_job", "succeeded: 1 archive written, checksum verified",
              "Backup succeeded."),
    ], [
        (A, (A, 84, C, 6)), (A, (C, 44, A, 36)), (A, (A, 76, R, 12)), (C, (C, 84, A, 6)),
    ]),
    ("t-deploy-poll", "test", "R-206", "Confirm that the staging deploy finished and is healthy.", [
        _turn("deploy_status staging", "deploying, step 3 of 5", "Still running."),
        _turn("deploy_status staging", "(no output: connection reset)",
              "Status check hiccup."),
        _turn("deploy_status staging", "deploying, step 4 of 5", "Moving along."),
        _turn("deploy_status staging", "deploying, step 4 of 5", "Waiting."),
        _turn("deploy_status staging", "deployed, step 5 of 5; health check passed",
              "Deploy finished."),
    ], [
        (U, (U, 68, R, 14)), (A, (R, 52, A, 32)), (R, (R, 52, A, 32)), (C, (C, 84, A, 6)),
    ]),
    # --- demo: shown up close, never scored -------------------------------------------------
    ("d-integration", "demo", "R-301", "Get the integration suite green on the release branch.", [
        _turn("run_tests tests/integration",
              "2 failed: test_checkout_flow, test_refund_flow (timeout contacting payments-stub)",
              "Two failures, both timeouts."),
        _turn("run_tests tests/integration",
              "2 failed: test_checkout_flow, test_refund_flow (timeout contacting payments-stub)",
              "Re-running to be sure."),
        _turn("run_tests tests/integration --verbose",
              "2 failed: test_checkout_flow, test_refund_flow (timeout contacting payments-stub)",
              "Verbose output shows the suite is nearly passing."),
    ], [
        (None, (R, 68, A, 20)), (None, (R, 84, A, 8)),
    ]),
]  # fmt: skip


def _rows(transcripts):
    """One row per checkpoint: (id, split, fields, gold label or None, stored-answer spec)."""
    rows = []
    for slug, split, ref, goal, turns, checkpoints in transcripts:
        if len(checkpoints) != len(turns) - 1:
            raise ValueError(f"{slug}: every turn after the first needs one checkpoint entry")
        for turn, (label, spec) in enumerate(checkpoints, start=2):
            fields = {"transcript": ref, "turn": turn, "goal": goal, "turns": turns[:turn]}
            rows.append((f"{slug}-t{turn}", split, fields, label, spec))
    return rows


ROWS = _rows(TRANSCRIPTS)


def _percentages(spec):
    """Whole-number percentages per option, in OPTIONS order, from a stored-answer spec."""
    top, p_top, second, p_second = spec
    if top == second or p_top <= p_second:
        raise ValueError(f"bad spec {spec!r}: the top option must lead the second")
    rest = [name for name in helpers.OPTIONS if name not in (top, second)]
    remainder = 100 - p_top - p_second
    share, extra = divmod(remainder, len(rest))
    if share >= p_second:
        raise ValueError(f"bad spec {spec!r}: the second option must lead the rest")
    percent = {top: p_top, second: p_second}
    for index, name in enumerate(rest):
        percent[name] = share + (1 if index < extra else 0)
    return {name: percent[name] for name in helpers.OPTIONS}


def answers_for(spec, provenance: Provenance):
    """{question name: answer} for one row: the ``progress`` Choice built from ``spec``."""
    probabilities = {name: value / 100 for name, value in _percentages(spec).items()}
    return {"progress": ChoiceAnswer.from_probabilities(probabilities, provenance)}


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
        raise SystemExit("no checkpoints: add transcripts to TRANSCRIPTS in build_fixtures.py")
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
    # dump_responses is the serialization the recorder writes with (top-level keys sorted, each
    # response keeping the field order DecisionResult.to_dict() emits), so a recording's diff
    # stays limited to the values that actually changed.
    responses_file.write_text(dump_responses(responses), encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
