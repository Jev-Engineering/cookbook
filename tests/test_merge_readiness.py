"""The merge-readiness check, driven by a fake ``gh`` that serves canned API responses.

Nothing here calls GitHub, needs credentials, or can mutate anything: the fake only answers GET
paths from an in-memory model, and a path it does not know is a test failure.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_merge_readiness", ROOT / "tools" / "check_merge_readiness.py"
)
mr = importlib.util.module_from_spec(_spec)
sys.modules["check_merge_readiness"] = mr
_spec.loader.exec_module(mr)

REPO = "Jev-Engineering/cookbook"
MAIN = "a" * 40
HEAD = "b" * 40
OLD_MAIN = "c" * 40
NEW_MAIN = "d" * 40
NEW_HEAD = "e" * 40
DONE = {"success", "failure", "cancelled", "timed_out", "neutral", "skipped"}


def run(
    name: str, state: str = "success", sha: str = HEAD, id_: int = 1, app: str = "github-actions"
) -> dict:
    return {
        "id": id_,
        "name": name,
        "head_sha": sha,
        "app": {"slug": app},
        "status": "completed" if state in DONE else state,
        "conclusion": state if state in DONE else None,
    }


def green(sha: str) -> list[dict]:
    return [run(n, sha=sha, id_=i) for i, n in enumerate(mr.BASELINE_CHECKS, 1)]


class FakeGitHub:
    """A mutable model of the few endpoints the tool reads. ``hooks`` fire on every request."""

    def __init__(self):
        self.calls: list[str] = []
        self.hooks: list = []
        self.default_branch = "main"
        self.main = MAIN
        self.pr = {
            "state": "open",
            "draft": False,
            "merged": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "head": {"sha": HEAD},
            "base": {"ref": "main"},
        }
        self.runs = {MAIN: green(MAIN), HEAD: green(HEAD)}
        self.statuses: dict[str, list[dict]] = {}
        self.compare = {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "merge_base_commit": {"sha": MAIN},
        }
        self.fail_on: str | None = None
        self.inflate_total = 0
        self.status_sha: str | None = None

    def __call__(self, path: str):
        self.calls.append(path)
        for hook in self.hooks:
            hook(self, path)
        if self.fail_on and self.fail_on in path:
            raise mr.ApiFailure("GitHub API request failed: simulated")
        base, _, query = path.partition("?")
        params = dict(p.split("=") for p in query.split("&")) if query else {}
        if base == f"repos/{REPO}":
            return {"default_branch": self.default_branch}
        if base == f"repos/{REPO}/branches/{self.default_branch}":
            return {"commit": {"sha": self.main}}
        if base == f"repos/{REPO}/pulls/95":
            return copy.deepcopy(self.pr)
        if base.startswith(f"repos/{REPO}/compare/"):
            return copy.deepcopy(self.compare)
        if base.endswith("/check-runs"):
            sha = base.split("/")[-2]
            body = self._page(self.runs.get(sha, []), "check_runs", params)
            body["total_count"] += self.inflate_total
            return body
        if base.endswith("/status"):
            sha = base.split("/")[-2]
            body = self._page(self.statuses.get(sha, []), "statuses", params)
            body["sha"] = self.status_sha or sha
            return body
        raise AssertionError(f"unexpected API path: {path}")

    @staticmethod
    def _page(items: list, key: str, params: dict) -> dict:
        size, page = int(params["per_page"]), int(params["page"])
        return {
            "total_count": len(items),
            key: copy.deepcopy(items[(page - 1) * size : page * size]),
        }


@pytest.fixture
def gh() -> FakeGitHub:
    return FakeGitHub()


def assess(gh: FakeGitHub, extra=()):
    return mr.assess(gh, REPO, 95, HEAD, list(extra))


def test_all_green_is_ready_with_receipt(gh):
    receipt = assess(gh)
    assert receipt["ready"] and receipt["failures"] == []
    assert receipt["main_sha"] == MAIN and receipt["head_sha"] == HEAD
    assert [c["name"] for c in receipt["checks"]["head"]] == list(mr.BASELINE_CHECKS)
    assert receipt["ancestry"]["merge_base"] == MAIN
    json.dumps(receipt)


def test_only_api_get_paths_are_requested(gh):
    assess(gh)
    assert gh.calls and all(c.startswith("repos/") for c in gh.calls)


# --- the two observed regressions -------------------------------------------------------------


def test_regression_pr83_cancelled_main_job_is_not_ready(gh):
    """PR83: main CI was cancelled when the next merge advanced main. A rerun later passed."""
    gh.runs[MAIN][2] = run("Tests (py3.10)", "cancelled", sha=MAIN, id_=3)
    receipt = assess(gh)
    assert not receipt["ready"]
    assert any("main: check Tests (py3.10) is cancelled" in f for f in receipt["failures"])
    # Once the rerun replaces the cancelled run (the API lists only the latest), it is ready.
    gh.runs[MAIN][2] = run("Tests (py3.10)", "success", sha=MAIN, id_=30)
    assert assess(gh)["ready"]


def test_regression_pr92_head_behind_main_is_not_ready(gh):
    """PR92: premerge CI tested an older main, even though evaluation/style had landed."""
    gh.main = NEW_MAIN
    gh.runs[NEW_MAIN] = green(NEW_MAIN)
    gh.compare = {
        "status": "diverged",
        "ahead_by": 1,
        "behind_by": 2,
        "merge_base_commit": {"sha": OLD_MAIN},
    }
    receipt = assess(gh)
    assert not receipt["ready"]
    text = " ".join(receipt["failures"])
    assert "not an ancestor" in text and "signed integration" in text and "fresh" in text
    assert receipt["ancestry"]["behind_by"] == 2


def test_merge_base_must_equal_main_even_if_status_looks_ahead(gh):
    gh.compare["merge_base_commit"] = {"sha": OLD_MAIN}
    assert not assess(gh)["ready"]


# --- PR state ---------------------------------------------------------------------------------


def test_unexpected_head_fails(gh):
    gh.pr["head"] = {"sha": NEW_HEAD}
    gh.runs[NEW_HEAD] = green(NEW_HEAD)
    assert any("not the expected" in f for f in assess(gh)["failures"])


@pytest.mark.parametrize(
    "change",
    [
        {"state": "closed"},
        {"merged": True},
        {"draft": True},
        {"base": {"ref": "release"}},
        {"mergeable": None},
        {"mergeable": False, "mergeable_state": "dirty"},
        {"mergeable_state": "behind"},
    ],
)
def test_pr_state_problems_fail(gh, change):
    gh.pr.update(change)
    assert not assess(gh)["ready"]


# --- checks -----------------------------------------------------------------------------------


@pytest.mark.parametrize("where", [MAIN, HEAD])
def test_missing_required_check_fails_on_either_commit(gh, where):
    gh.runs[where] = [r for r in gh.runs[where] if r["name"] != "Lint (ruff)"]
    receipt = assess(gh)
    assert not receipt["ready"]
    assert any("required check missing: Lint (ruff)" in f for f in receipt["failures"])


@pytest.mark.parametrize("state", ["failure", "cancelled", "timed_out", "neutral", "skipped"])
def test_non_success_conclusions_fail(gh, state):
    gh.runs[HEAD][0] = run("Lint (ruff)", state, id_=1)
    assert not assess(gh)["ready"]


def test_pending_check_run_fails(gh):
    gh.runs[HEAD][0] = run("Lint (ruff)", "in_progress", id_=1)
    assert any("is pending" in f for f in assess(gh)["failures"])


def test_one_green_workflow_is_not_the_full_gate(gh):
    gh.runs[HEAD] = [r for r in gh.runs[HEAD] if r["name"].startswith("Tests")]
    receipt = assess(gh)
    assert not receipt["ready"] and len(receipt["failures"]) == 3


def test_completed_run_without_conclusion_fails_closed(gh):
    gh.runs[HEAD][0]["conclusion"] = None
    with pytest.raises(mr.ApiFailure):
        assess(gh)


EXTERNAL = "external/deploy-preview"


def test_status_context_satisfies_an_additional_required_check(gh):
    for sha in (MAIN, HEAD):
        gh.statuses[sha] = [{"id": 900, "context": EXTERNAL, "state": "success"}]
    receipt = assess(gh, [EXTERNAL])
    assert receipt["ready"]
    assert receipt["checks"]["head"][-1]["kind"] == "status_context"


@pytest.mark.parametrize("state", ["pending", "failure", "error"])
def test_status_context_not_success_fails(gh, state):
    gh.statuses[MAIN] = [{"id": 900, "context": EXTERNAL, "state": "success"}]
    gh.statuses[HEAD] = [{"id": 900, "context": EXTERNAL, "state": state}]
    assert any(f"is {state}" in f for f in assess(gh, [EXTERNAL])["failures"])


def test_additional_check_may_be_a_check_run_from_another_app(gh):
    for sha in (MAIN, HEAD):
        gh.runs[sha].append(run("Deploy preview", sha=sha, id_=99, app="some-ci-app"))
    receipt = assess(gh, ["Deploy preview"])
    assert receipt["ready"] and receipt["checks"]["head"][-1]["app"] == "some-ci-app"


def test_status_context_cannot_stand_in_for_a_missing_baseline_job(gh):
    gh.runs[HEAD] = [r for r in gh.runs[HEAD] if r["name"] != "Lint (ruff)"]
    gh.statuses[HEAD] = [{"id": 900, "context": "Lint (ruff)", "state": "success"}]
    failures = assess(gh)["failures"]
    assert any(
        "baseline check Lint (ruff) is not a CheckRun from github-actions" in f for f in failures
    )


def test_baseline_check_run_from_another_app_is_rejected(gh):
    gh.runs[HEAD][0] = run("Lint (ruff)", id_=1, app="impostor")
    assert not assess(gh)["ready"]
    gh.runs[HEAD][0]["app"] = None
    assert not assess(gh)["ready"]


def test_check_runs_request_latest_explicitly(gh):
    assess(gh)
    runs = [c for c in gh.calls if "/check-runs" in c]
    assert runs and all("filter=latest" in c for c in runs)


def test_duplicate_and_conflicting_results_fail(gh):
    gh.runs[HEAD].append(run("Lint (ruff)", "success", id_=77))
    assert any("duplicate results (2)" in f for f in assess(gh)["failures"])

    gh.runs[HEAD][-1] = run("Lint (ruff)", "failure", id_=77)
    assert any("conflicting results" in f for f in assess(gh)["failures"])


def test_check_run_and_status_context_with_same_name_conflict(gh):
    gh.statuses[HEAD] = [{"id": 900, "context": "Lint (ruff)", "state": "failure"}]
    assert any("conflicting" in f for f in assess(gh)["failures"])


def test_extra_required_check_must_be_present_and_green(gh):
    assert not assess(gh, ["Notebooks (execute)"])["ready"]
    for sha in (MAIN, HEAD):
        gh.runs[sha].append(run("Notebooks (execute)", sha=sha, id_=99))
    receipt = assess(gh, ["Notebooks (execute)", "Lint (ruff)"])
    assert receipt["ready"]
    assert receipt["required_checks"].count("Lint (ruff)") == 1
    assert len(receipt["required_checks"]) == 6


def test_extra_check_missing_on_main_fails(gh):
    gh.runs[HEAD].append(run("Notebooks (execute)", sha=HEAD, id_=99))
    failures = assess(gh, ["Notebooks (execute)"])["failures"]
    assert any("main: required check missing" in f for f in failures)


def test_pagination_reads_every_page(gh):
    gh.runs[HEAD] = [run(f"filler {i}", sha=HEAD, id_=1000 + i) for i in range(150)] + green(HEAD)
    assert assess(gh)["ready"]
    assert any("page=2" in c for c in gh.calls)


def test_total_count_larger_than_visible_fails_closed(gh):
    gh.inflate_total = 3
    with pytest.raises(mr.ApiFailure, match="incomplete"):
        assess(gh)


# --- races ------------------------------------------------------------------------------------


def test_main_moving_during_collection_fails(gh):
    def advance(g, path):
        if path.startswith(f"repos/{REPO}/commits/{HEAD}/check-runs"):
            g.main = NEW_MAIN

    gh.hooks.append(advance)
    receipt = assess(gh)
    assert not receipt["ready"]
    assert any(f"main moved from {MAIN} to {NEW_MAIN}" in f for f in receipt["failures"])


def test_pr_head_moving_during_collection_fails(gh):
    def push(g, path):
        if path.startswith(f"repos/{REPO}/commits/{HEAD}/status"):
            g.pr["head"] = {"sha": NEW_HEAD}

    gh.hooks.append(push)
    failures = assess(gh)["failures"]
    assert any(f"PR head moved from {HEAD} to {NEW_HEAD}" in f for f in failures)


def test_default_branch_renamed_during_collection_fails(gh):
    def rename(g, path):
        if path.startswith(f"repos/{REPO}/commits/{HEAD}/status"):
            g.default_branch = "trunk"

    gh.hooks.append(rename)
    failures = assess(gh)["failures"]
    assert any("default branch changed from main to trunk" in f for f in failures)


def test_pr_closed_during_collection_fails_once(gh):
    def close(g, path):
        if path.startswith(f"repos/{REPO}/commits/{HEAD}/status"):
            g.pr["state"] = "closed"

    gh.hooks.append(close)
    assert any("race: PR is no longer open" in f for f in assess(gh)["failures"])


def test_pr_already_closed_is_not_also_reported_as_a_race(gh):
    gh.pr["state"] = "closed"
    failures = assess(gh)["failures"]
    assert any("PR is not open" in f for f in failures)
    assert not any(f.startswith("race:") for f in failures)


def test_combined_status_for_another_commit_fails_closed(gh):
    gh.status_sha = NEW_HEAD
    with pytest.raises(mr.ApiFailure, match="different commit"):
        assess(gh)


def test_main_and_pr_are_refetched_after_evidence(gh):
    assess(gh)
    assert gh.calls.count(f"repos/{REPO}/branches/main") == 2
    assert gh.calls.count(f"repos/{REPO}/pulls/95") == 2
    assert gh.calls.index(f"repos/{REPO}/pulls/95") < gh.calls.index(
        next(c for c in gh.calls if "check-runs" in c)
    )


# --- malformed data and API failure fail closed -----------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda g: g.pr.update(draft="no"),
        lambda g: g.pr.update(mergeable="yes"),
        lambda g: g.pr.update(head={"sha": "xyz"}),
        lambda g: g.compare.update(ahead_by=True),
        lambda g: g.compare.pop("merge_base_commit"),
        lambda g: g.runs[HEAD][0].update(head_sha=NEW_HEAD),
        lambda g: g.runs[HEAD][0].pop("name"),
        lambda g: g.runs[HEAD][0].update(id=True),
    ],
)
def test_malformed_data_fails_closed(gh, mutate):
    mutate(gh)
    with pytest.raises(mr.ApiFailure):
        assess(gh)


@pytest.mark.parametrize("fragment", ["pulls/95", "compare", "check-runs", "/status", "branches"])
def test_api_failure_anywhere_is_exit_3(gh, fragment, capsys):
    gh.fail_on = fragment
    code = mr.main(["--pr", "95", "--expected-head", HEAD], gh=gh)
    out = json.loads(capsys.readouterr().out)
    assert code == mr.EXIT_API and out["ready"] is False


# --- CLI, output ------------------------------------------------------------------------------


def test_main_ready_exit_0_and_json(gh, capsys):
    code = mr.main(["--pr", "95", "--expected-head", HEAD], gh=gh)
    captured = capsys.readouterr()
    assert code == mr.EXIT_READY and json.loads(captured.out)["ready"] is True
    assert "not a merge authorization" in captured.err


def test_main_not_ready_exit_1(gh, capsys):
    gh.runs[HEAD][0] = run("Lint (ruff)", "failure")
    assert mr.main(["--pr", "95", "--expected-head", HEAD], gh=gh) == mr.EXIT_NOT_READY
    assert json.loads(capsys.readouterr().out)["ready"] is False


@pytest.mark.parametrize(
    "argv",
    [
        ["--pr", "95"],
        ["--pr", "0", "--expected-head", HEAD],
        ["--pr", "95", "--expected-head", "abc"],
        ["--pr", "95", "--expected-head", HEAD.upper()],
        ["--pr", "95", "--expected-head", HEAD, "--repo", "no-slash"],
        ["--pr", "95", "--expected-head", HEAD, "--require-check", " "],
    ],
)
def test_usage_errors_exit_2(argv):
    with pytest.raises(SystemExit) as exc:
        mr.parse_args(argv)
    assert exc.value.code == 2


def test_receipt_is_bounded(gh, capsys):
    gh.runs[HEAD] = []
    argv = ["--pr", "95", "--expected-head", HEAD]
    for i in range(60):
        argv += ["--require-check", f"missing check {i} " + "x" * 150]
    mr.main(argv, gh=gh)
    out = json.loads(capsys.readouterr().out)
    assert len(out["failures"]) == mr.MAX_FAILURES + 1
    assert out["failures"][-1].startswith("... and ")
    assert all(len(f) <= 400 for f in out["failures"])


def test_output_carries_no_credentials(gh, monkeypatch, capsys):
    monkeypatch.setenv("GH_TOKEN", "ghp_" + "Z" * 36)
    mr.main(["--pr", "95", "--expected-head", HEAD], gh=gh)
    captured = capsys.readouterr()
    assert "ghp_" not in captured.out + captured.err


# --- the real runner, with subprocess mocked --------------------------------------------------


def _proc(returncode=0, stdout="{}", stderr=""):
    return subprocess.CompletedProcess(["gh"], returncode, stdout.encode(), stderr.encode())


def test_run_gh_uses_plain_get_and_parses(monkeypatch):
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        return _proc(stdout='{"a": 1}')

    monkeypatch.setattr(mr.subprocess, "run", fake)
    assert mr.run_gh("repos/x/y") == {"a": 1}
    assert seen["cmd"][:2] == ["gh", "api"]
    assert not {"-X", "--method", "--input", "-f", "-F", "--field"} & set(seen["cmd"])


@pytest.mark.parametrize(
    ("stderr", "label"),
    [
        ("HTTP 403: API rate limit exceeded", "rate limited"),
        ("HTTP 401: Bad credentials token=ghp_secret", "not authenticated"),
        ("To get started with GitHub CLI, please run: gh auth login", "not authenticated"),
        ("HTTP 404: Not Found", "not found"),
        ("gh: Not Found (HTTP 404)", "not found (HTTP 404)"),
        ("gh: Resource not accessible (HTTP 403)", "forbidden (HTTP 403)"),
        ("HTTP 429: slow down", "rate limited"),
        ("request 4031 and 4044 failed", "gh failed"),
        ("HTTP 502: Bad Gateway", "gh failed (HTTP 502)"),
    ],
)
def test_run_gh_failures_are_categorised_without_echoing_stderr(monkeypatch, stderr, label):
    monkeypatch.setattr(mr.subprocess, "run", lambda *a, **k: _proc(1, "", stderr))
    with pytest.raises(mr.ApiFailure) as exc:
        mr.run_gh("repos/x/y")
    assert label in str(exc.value) and "ghp_" not in str(exc.value)


def test_run_gh_missing_cli_timeout_and_bad_json(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError

    def slow(*a, **k):
        raise subprocess.TimeoutExpired("gh", 1)

    monkeypatch.setattr(mr.subprocess, "run", missing)
    with pytest.raises(mr.ApiFailure):
        mr.run_gh("p")
    monkeypatch.setattr(mr.subprocess, "run", slow)
    with pytest.raises(mr.ApiFailure):
        mr.run_gh("p")
    monkeypatch.setattr(mr.subprocess, "run", lambda *a, **k: _proc(stdout="<html>"))
    with pytest.raises(mr.ApiFailure):
        mr.run_gh("p")


# --- the real runner against a real child process ---------------------------------------------
#
# The child stands in for ``gh`` and writes raw bytes, so the actual subprocess decoding in
# ``run_gh`` runs. Windows decoded gh's UTF-8 with the locale code page (cp1252) and crashed on
# bytes such as 0x81, which is what these cases lock down.

SECRET = "ghp_" + "Q" * 36
CHILD = (
    "import sys\n"
    "sys.stdout.buffer.write({out!r})\n"
    "sys.stderr.buffer.write({err!r})\n"
    "sys.exit({code})\n"
)


@pytest.fixture
def child_gh(monkeypatch):
    """Route run_gh's subprocess call to a real Python child that emits the given bytes."""
    real_run = subprocess.run

    def configure(out: bytes = b"{}", err: bytes = b"", code: int = 0):
        script = CHILD.format(out=out, err=err, code=code)

        def run_child(cmd, **kwargs):
            assert cmd[:2] == ["gh", "api"]
            return real_run([sys.executable, "-c", script], **kwargs)

        monkeypatch.setattr(mr.subprocess, "run", run_child)

    return configure


UNICODE_JSON = '{"title": "Zażółć \u201d \u2010 ā ✓ 🎉", "n": 1}'.encode()


def test_real_child_valid_non_cp1252_utf8_is_decoded(child_gh):
    # U+201D, U+2010 and 'ā' contain bytes (0x81, 0x90) that cp1252 cannot decode.
    child_gh(out=UNICODE_JSON)
    assert mr.run_gh("repos/x/y")["n"] == 1


@pytest.mark.parametrize(
    "out",
    [b"\xff\xfe{}", b'{"a": "\x81\x8d"}', b"\x80", b"<html>not json</html>", b"", b"[1, 2"],
)
def test_real_child_invalid_output_is_api_failure(child_gh, out):
    child_gh(out=out)
    with pytest.raises(mr.ApiFailure):
        mr.run_gh("repos/x/y")


def test_real_child_invalid_stderr_bytes_do_not_crash_or_leak(child_gh):
    child_gh(out=b"", err=b"HTTP 401 \xff\xfe " + SECRET.encode(), code=1)
    with pytest.raises(mr.ApiFailure) as exc:
        mr.run_gh("repos/x/y")
    assert SECRET not in str(exc.value)


@pytest.mark.parametrize(
    "out",
    [b"\xff\xfe\x81" + SECRET.encode(), b"<html>" + SECRET.encode(), b"[]", b'"text"'],
)
def test_real_child_main_exits_3_with_bounded_receipt(child_gh, out, capsys):
    child_gh(out=out)
    code = mr.main(["--pr", "95", "--expected-head", HEAD])
    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert code == mr.EXIT_API and receipt["ready"] is False
    assert SECRET not in captured.out + captured.err
    assert len(receipt["failures"]) == 1 and len(receipt["failures"][0]) <= 400


def test_real_child_unicode_responses_flow_through_main(child_gh, capsys):
    child_gh(out=UNICODE_JSON)  # decodes fine, but is not a repository object
    assert mr.main(["--pr", "95", "--expected-head", HEAD]) == mr.EXIT_API
    assert json.loads(capsys.readouterr().out)["ready"] is False


def test_unexpected_failure_exits_3_without_its_message(capsys):
    def boom(path):
        raise RuntimeError(f"surprise {SECRET} from {path}")

    code = mr.main(["--pr", "95", "--expected-head", HEAD], gh=boom)
    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert code == mr.EXIT_API and receipt["ready"] is False
    assert "unexpected RuntimeError" in receipt["failures"][0]
    assert SECRET not in captured.out + captured.err
    assert captured.out.isascii()


def test_unexpected_none_output_is_exit_3(monkeypatch, capsys):
    monkeypatch.setattr(
        mr.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(["gh"], 0, None, "")
    )
    assert mr.main(["--pr", "95", "--expected-head", HEAD]) == mr.EXIT_API
    assert json.loads(capsys.readouterr().out)["ready"] is False
