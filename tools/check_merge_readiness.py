#!/usr/bin/env python3
"""Read-only merge-readiness check: current-main ancestry and complete CI.

Standard library plus the ``gh`` CLI (read-only ``gh api`` GET requests only).

    python tools/check_merge_readiness.py --pr 95 --expected-head <40-hex sha>
    python tools/check_merge_readiness.py --pr 95 --expected-head <sha> \
        --require-check "Notebooks (execute)"
    python tools/check_merge_readiness.py --pr 95 --expected-head <sha> \
        --require-head-check "Scope (recipe pull requests)"

Exit status: 0 ready, 1 not ready, 2 usage error, 3 GitHub API failure, incomplete data, or any
unexpected internal failure (all fail closed). With valid arguments a bounded ASCII JSON receipt
is always printed to stdout; an argument error exits 2 with argparse's usage message instead.

This answers ONE question: is the pull request head, as pinned, based on the current default
branch with every expected CI check successful on both current main and that head? It does not
review, approve, merge, or change anything, and a ready result is not merge authorization. See
docs/merge-readiness.md for the gates it deliberately does not cover.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from typing import Any

DEFAULT_REPO = "Jev-Engineering/cookbook"

# The baseline gate: the job names in .github/workflows/ci.yml and hygiene.yml. Checks added
# by later workflows are the caller's responsibility, passed with --require-check (required on
# current main and on the head) or --require-head-check (required on the head only, for a check
# such as "Scope (recipe pull requests)" that runs on pull_request_target and therefore never
# appears on a commit of main).
# The app that publishes the baseline jobs. A baseline name is only satisfied by a CheckRun from
# it, so a commit status posted under the same name cannot stand in for a missing Actions job.
# Checks named with --require-check or --require-head-check may be a CheckRun from any app or a
# StatusContext.
BASELINE_APP = "github-actions"
BASELINE_CHECKS = (
    "Lint (ruff)",
    "Catalog (README is current)",
    "Tests (py3.10)",
    "Tests (py3.14)",
    "Hygiene (secrets and notebook outputs)",
)

PAGE_SIZE = 100
MAX_PAGES = 10
MAX_FAILURES = 25
MAX_TEXT = 200
GH_TIMEOUT_SECONDS = 60

_SHA = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

EXIT_READY, EXIT_NOT_READY, EXIT_USAGE, EXIT_API = 0, 1, 2, 3


class ApiFailure(Exception):
    """GitHub could not be read, or answered with data this tool cannot trust."""


GhRunner = Callable[[str], Any]


def run_gh(path: str) -> Any:
    """GET one API path with ``gh api`` and return parsed JSON. Never sends a body or a method."""
    try:
        # Raw bytes, decoded below as strict UTF-8 (what gh writes). Text mode would use the
        # locale code page (cp1252 on Windows), which cannot decode valid gh output.
        proc = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
            capture_output=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        raise ApiFailure("gh CLI not found") from None
    except subprocess.TimeoutExpired:
        raise ApiFailure("gh timed out") from None
    if proc.returncode != 0:
        # stderr is only classified, never repeated, and a bad byte there cannot crash it.
        stderr = (
            proc.stderr.decode("utf-8", errors="replace") if isinstance(proc.stderr, bytes) else ""
        )
        raise ApiFailure(f"GitHub API request failed: {_classify(stderr)}: {_clip(path)}")
    if not isinstance(proc.stdout, bytes):
        raise ApiFailure(f"gh produced no readable output for {_clip(path)}")
    try:
        return json.loads(proc.stdout.decode("utf-8"))
    except UnicodeDecodeError:
        raise ApiFailure(f"gh output is not valid UTF-8 for {_clip(path)}") from None
    except ValueError:
        raise ApiFailure(f"GitHub returned non-JSON for {_clip(path)}") from None


def _classify(stderr: object) -> str:
    """Name the failure without repeating stderr, which can echo request details."""
    err = stderr.lower() if isinstance(stderr, str) else ""
    match = re.search(r"\bhttp[ /:]*(\d{3})\b", err)
    code = match.group(1) if match else ""
    if "rate limit" in err or code == "429":
        return "rate limited"
    if code == "401" or "bad credentials" in err or "gh auth login" in err:
        return "not authenticated"
    if code == "403":
        return "forbidden (HTTP 403)"
    if code == "404":
        return "not found (HTTP 404)"
    return f"gh failed (HTTP {code})" if code else "gh failed"


def _clip(value: object, limit: int = MAX_TEXT) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


# --- strict typed access: anything unexpected is an ApiFailure, never a default -----------------


def _obj(data: Any, what: str) -> dict:
    if not isinstance(data, dict):
        raise ApiFailure(f"{what}: expected an object")
    return data


def _get(data: dict, key: str, kind: type, what: str) -> Any:
    value = data.get(key)
    # bool is a subclass of int; never let one stand in for the other.
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ApiFailure(f"{what}: field '{key}' missing or not {kind.__name__}")
    return value


def _sha(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ApiFailure(f"{what}: not a full lowercase commit SHA")
    return value


def _nested(data: dict, keys: tuple[str, ...], what: str) -> dict:
    for key in keys:
        data = _obj(data.get(key), f"{what}.{key}")
    return data


# --- evidence collection --------------------------------------------------------------------------


def fetch_main(gh: GhRunner, repo: str) -> tuple[str, str]:
    """Return (default branch name, its current head SHA)."""
    info = _obj(gh(f"repos/{repo}"), "repository")
    branch = _get(info, "default_branch", str, "repository")
    commit = _nested(_obj(gh(f"repos/{repo}/branches/{branch}"), "branch"), ("commit",), "branch")
    return branch, _sha(commit.get("sha"), "default branch commit")


def fetch_pr(gh: GhRunner, repo: str, number: int) -> dict:
    pr = _obj(gh(f"repos/{repo}/pulls/{number}"), "pull request")
    head = _nested(pr, ("head",), "pull request")
    base = _nested(pr, ("base",), "pull request")
    mergeable = pr.get("mergeable")
    if mergeable is not None and not isinstance(mergeable, bool):
        raise ApiFailure("pull request: 'mergeable' is not a boolean or null")
    return {
        "state": _get(pr, "state", str, "pull request"),
        "draft": _get(pr, "draft", bool, "pull request"),
        "merged": _get(pr, "merged", bool, "pull request"),
        "mergeable": mergeable,
        "mergeable_state": _get(pr, "mergeable_state", str, "pull request"),
        "head_sha": _sha(head.get("sha"), "pull request head"),
        "base_ref": _get(base, "ref", str, "pull request base"),
    }


def _paged(gh: GhRunner, path: str, list_key: str, what: str) -> tuple[dict, list]:
    """Read every page of a list endpoint and require the count GitHub reports to match."""
    sep = "&" if "?" in path else "?"
    items: list = []
    first: dict | None = None
    total = 0
    for page in range(1, MAX_PAGES + 1):
        body = _obj(gh(f"{path}{sep}per_page={PAGE_SIZE}&page={page}"), what)
        total = _get(body, "total_count", int, what)
        chunk = body.get(list_key)
        if not isinstance(chunk, list):
            raise ApiFailure(f"{what}: '{list_key}' is not a list")
        first = first if first is not None else body
        items.extend(chunk)
        if len(items) >= total or not chunk:
            break
    if len(items) != total:
        raise ApiFailure(f"{what}: incomplete ({len(items)} of {total} entries visible)")
    return first or {}, items


def collect_checks(gh: GhRunner, repo: str, sha: str) -> list[dict]:
    """Every CheckRun and StatusContext on ``sha``, normalised to name/kind/state."""
    # filter=latest is the API default, stated so a rerun replaces an earlier cancelled run.
    runs_path = f"repos/{repo}/commits/{sha}/check-runs?filter=latest"
    _, runs = _paged(gh, runs_path, "check_runs", "check runs")
    combined, statuses = _paged(gh, f"repos/{repo}/commits/{sha}/status", "statuses", "statuses")
    if _sha(combined.get("sha"), "combined status") != sha:
        raise ApiFailure("combined status describes a different commit")

    found: list[dict] = []
    for run in runs:
        run = _obj(run, "check run")
        if _sha(run.get("head_sha"), "check run") != sha:
            raise ApiFailure("check run belongs to a different commit")
        status = _get(run, "status", str, "check run")
        conclusion = run.get("conclusion")
        if conclusion is not None and not isinstance(conclusion, str):
            raise ApiFailure("check run: 'conclusion' is not a string or null")
        found.append(
            {
                "name": _get(run, "name", str, "check run"),
                "kind": "check_run",
                "id": _get(run, "id", int, "check run"),
                "app": _app_slug(run),
                "state": _run_state(status, conclusion),
            }
        )
    for item in statuses:
        item = _obj(item, "status context")
        found.append(
            {
                "name": _get(item, "context", str, "status context"),
                "kind": "status_context",
                "id": _get(item, "id", int, "status context"),
                "state": _get(item, "state", str, "status context"),
            }
        )
    return found


def _app_slug(run: dict) -> str | None:
    app = run.get("app")
    slug = app.get("slug") if isinstance(app, dict) else None
    return slug if isinstance(slug, str) else None


def _run_state(status: str, conclusion: str | None) -> str:
    """Collapse a CheckRun to one word: 'success', 'pending', or its failing conclusion."""
    if status != "completed":
        return "pending"
    if not conclusion:
        raise ApiFailure("completed check run has no conclusion")
    return conclusion


# --- judgement ------------------------------------------------------------------------------------


def judge_checks(
    found: list[dict], required: list[str], label: str
) -> tuple[list[dict], list[str]]:
    """Return (evidence for the required checks, failures). Only exact 'success' passes."""
    by_name: dict[str, list[dict]] = {}
    for entry in found:
        by_name.setdefault(entry["name"], []).append(entry)

    evidence: list[dict] = []
    failures: list[str] = []
    for name in required:
        entries = by_name.get(name, [])
        if not entries:
            failures.append(f"{label}: required check missing: {_clip(name)}")
            evidence.append({"name": name, "state": "missing"})
        elif len(entries) > 1:
            states = sorted({e["state"] for e in entries})
            kind = "conflicting" if len(states) > 1 else "duplicate"
            failures.append(f"{label}: {kind} results ({len(entries)}) for check: {_clip(name)}")
            evidence.append({"name": name, "state": "ambiguous", "results": len(entries)})
        else:
            entry = entries[0]
            evidence.append(
                {"name": name, "kind": entry["kind"], "id": entry["id"], "state": entry["state"]}
            )
            if entry["kind"] == "check_run":
                evidence[-1]["app"] = _clip(entry["app"], 60)
            if name in BASELINE_CHECKS and (
                entry["kind"] != "check_run" or entry["app"] != BASELINE_APP
            ):
                failures.append(
                    f"{label}: baseline check {_clip(name)} is not a CheckRun from {BASELINE_APP}"
                )
            elif entry["state"] != "success":
                failures.append(f"{label}: check {_clip(name)} is {_clip(entry['state'])}")
    return evidence, failures


def judge_pr(pr: dict, default_branch: str, expected_head: str) -> list[str]:
    failures = []
    if pr["head_sha"] != expected_head:
        failures.append(
            f"PR head is {pr['head_sha']}, not the expected {expected_head}; "
            "anything reviewed against another head must be reviewed again"
        )
    if pr["state"] != "open" or pr["merged"]:
        failures.append(f"PR is not open (state={_clip(pr['state'])}, merged={pr['merged']})")
    if pr["draft"]:
        failures.append("PR is a draft")
    if pr["base_ref"] != default_branch:
        failures.append(f"PR targets {_clip(pr['base_ref'])}, not default branch {default_branch}")
    if pr["mergeable"] is not True or pr["mergeable_state"] in {"dirty", "behind", "unknown"}:
        failures.append(
            f"PR is not mergeable (mergeable={pr['mergeable']}, state={_clip(pr['mergeable_state'])})"
        )
    return failures


def check_ancestry(gh: GhRunner, repo: str, main_sha: str, head_sha: str) -> tuple[dict, list[str]]:
    """Prove main is an ancestor of the head: the API merge base must be main itself."""
    cmp = _obj(gh(f"repos/{repo}/compare/{main_sha}...{head_sha}?per_page=1"), "compare")
    status = _get(cmp, "status", str, "compare")
    ahead = _get(cmp, "ahead_by", int, "compare")
    behind = _get(cmp, "behind_by", int, "compare")
    merge_base = _sha(_nested(cmp, ("merge_base_commit",), "compare").get("sha"), "merge base")
    receipt = {
        "status": status,
        "ahead_by": ahead,
        "behind_by": behind,
        "merge_base": merge_base,
    }
    if merge_base == main_sha and behind == 0 and status in {"ahead", "identical"}:
        return receipt, []
    return receipt, [
        f"current main {main_sha} is not an ancestor of PR head {head_sha} "
        f"(compare status={_clip(status)}, behind_by={behind}, merge base {merge_base}). "
        "Update the branch with a signed integration of current main, then obtain a fresh "
        "review and CI of the new head; the old approval does not carry over."
    ]


def assess(
    gh: GhRunner,
    repo: str,
    number: int,
    expected_head: str,
    extra: list[str],
    extra_head: list[str] = (),
) -> dict:
    """``extra`` names are required on current main AND the head; ``extra_head`` names (for
    example "Scope (recipe pull requests)", which runs on ``pull_request_target`` and so never
    appears on a commit of main) are required on the head only and are never judged on main. A
    name that is a baseline check, or that also appears in ``extra``, keeps its main requirement
    regardless of being repeated here: the head-and-main requirement always wins.
    """
    required = list(dict.fromkeys([*BASELINE_CHECKS, *extra]))
    required_head_only = [name for name in dict.fromkeys(extra_head) if name not in required]
    required_on_head = [*required, *required_head_only]
    failures: list[str] = []

    branch, main_sha = fetch_main(gh, repo)
    pr = fetch_pr(gh, repo, number)
    failures += judge_pr(pr, branch, expected_head)

    ancestry, problems = check_ancestry(gh, repo, main_sha, pr["head_sha"])
    failures += problems

    main_checks, problems = judge_checks(collect_checks(gh, repo, main_sha), required, "main")
    failures += problems
    head_checks, problems = judge_checks(
        collect_checks(gh, repo, pr["head_sha"]), required_on_head, "head"
    )
    failures += problems

    # Evidence took time; confirm nothing moved while it was collected.
    branch_after, main_after = fetch_main(gh, repo)
    pr_after = fetch_pr(gh, repo, number)
    if branch_after != branch:
        failures.append(f"race: default branch changed from {branch} to {branch_after}")
    if main_after != main_sha:
        failures.append(f"race: main moved from {main_sha} to {main_after} during the check")
    if pr_after["head_sha"] != pr["head_sha"]:
        failures.append(
            f"race: PR head moved from {pr['head_sha']} to {pr_after['head_sha']} during the check"
        )
    was_open = pr["state"] == "open" and not pr["merged"]
    if was_open and (pr_after["state"] != "open" or pr_after["merged"]):
        failures.append("race: PR is no longer open")

    return {
        "ready": not failures,
        "repository": repo,
        "pull_request": number,
        "default_branch": branch,
        "main_sha": main_sha,
        "head_sha": pr["head_sha"],
        "expected_head_sha": expected_head,
        "mergeable_state": pr["mergeable_state"],
        "ancestry": ancestry,
        "required_checks": required,
        "required_head_checks": required_head_only,
        "checks": {"main": main_checks, "head": head_checks},
        "failures": failures,
    }


def bounded(receipt: dict) -> dict:
    """Cap the failure list and every string so the receipt stays small."""
    failures = receipt["failures"]
    if len(failures) > MAX_FAILURES:
        omitted = len(failures) - MAX_FAILURES
        failures = [*failures[:MAX_FAILURES], f"... and {omitted} more"]
    receipt["failures"] = [_clip(f, 400) for f in failures]
    return receipt


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read-only check that a PR head is based on current main with complete CI. "
        "Not a merge authorization: reviews, acceptance, scope and signatures are separate gates."
    )
    p.add_argument("--repo", default=DEFAULT_REPO, help=f"owner/name (default {DEFAULT_REPO})")
    p.add_argument("--pr", type=int, required=True, help="pull request number")
    p.add_argument("--expected-head", required=True, help="the full 40-character head SHA to pin")
    p.add_argument(
        "--require-check",
        action="append",
        default=[],
        metavar="NAME",
        help="an additional required check name, exactly as it appears (repeatable), required on "
        "current main AND the PR head. The five baseline checks are always required; checks "
        "added by later workflows must be named here",
    )
    p.add_argument(
        "--require-head-check",
        action="append",
        default=[],
        metavar="NAME",
        help="an additional required check name (repeatable), required on the PR head ONLY and "
        "never judged on main; for a check such as 'Scope (recipe pull requests)' that runs on "
        "pull_request_target and so never appears on a commit of main. A name that is also a "
        "baseline check or a --require-check name keeps its main requirement",
    )
    args = p.parse_args(argv)
    if args.pr < 1:
        p.error("--pr must be positive")
    if not _REPO.fullmatch(args.repo):
        p.error("--repo must look like owner/name")
    if not _SHA.fullmatch(args.expected_head):
        p.error("--expected-head must be a full lowercase 40-character SHA")
    if any(not name.strip() or len(name) > MAX_TEXT for name in args.require_check):
        p.error("--require-check names must be non-empty and at most 200 characters")
    if any(not name.strip() or len(name) > MAX_TEXT for name in args.require_head_check):
        p.error("--require-head-check names must be non-empty and at most 200 characters")
    return args


def _fail_closed(args: argparse.Namespace, message: str) -> int:
    receipt = {
        "ready": False,
        "repository": args.repo,
        "pull_request": args.pr,
        "expected_head_sha": args.expected_head,
        "failures": [_clip(message, 400)],
    }
    print(json.dumps(receipt, indent=2))
    print("NOT READY: GitHub evidence unavailable or untrusted", file=sys.stderr)
    return EXIT_API


def main(argv: list[str] | None = None, gh: GhRunner = run_gh) -> int:
    args = parse_args(argv)
    try:
        receipt = bounded(
            assess(
                gh,
                args.repo,
                args.pr,
                args.expected_head,
                args.require_check,
                args.require_head_check,
            )
        )
    except ApiFailure as exc:
        return _fail_closed(args, f"cannot verify (failing closed): {exc}")
    except Exception as exc:  # any surprise must still fail closed with a receipt
        # Only the exception type is reported: its text could carry raw output.
        return _fail_closed(
            args, f"cannot verify (failing closed): unexpected {type(exc).__name__}"
        )
    print(json.dumps(receipt, indent=2))
    if receipt["ready"]:
        print(
            "READY (CI and current-main ancestry only; not a merge authorization)", file=sys.stderr
        )
        return EXIT_READY
    print(f"NOT READY: {len(receipt['failures'])} failure(s)", file=sys.stderr)
    return EXIT_NOT_READY


if __name__ == "__main__":
    sys.exit(main())
