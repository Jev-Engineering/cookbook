"""Tests for the live-extra report in ``tests/conftest.py`` (issue #264).

Part 1 calls the pure helpers with fake ``find_spec`` results and fake pytest reports. Part 2 runs
a few tiny pytest subprocesses with ``typesafe_sdk`` and ``httpx2`` stubbed in or blocked, then
checks the printed line and its counts. Every expected count is derived from the run it checks:
the sample files hold a few tests each, and the real SDK-gated cases are counted by collecting
them. The real netguard test uses stub modules and a stand-in executor that runs no notebook.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

TESTS_DIR = Path(__file__).parent
REPO_DIR = TESTS_DIR.parent
SRC_DIR = REPO_DIR / "src"

# conftest.py is loaded by path under its own name; it is never imported as ``conftest``.
_spec = importlib.util.spec_from_file_location(
    "_live_reporting_conftest", Path(__file__).parent / "conftest.py"
)
assert _spec is not None and _spec.loader is not None
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)

BOTH = ("typesafe_sdk", "httpx2")
ZERO = {"ran": 0, "skipped": 0, "deselected": 0}
COUNTS = {"ran": 3, "skipped": 2, "deselected": 1}  # fake counts, only for the formatters
MISSING_RE = re.compile(r"\(missing: ([^)]*)\)")
RESULT_RE = re.compile(r"^live extra .*ran=(\d+) skipped=(\d+) deselected=(\d+)", re.MULTILINE)
SDK_SKIP = (
    "f.py",
    3,
    "Skipped: could not import 'typesafe_sdk': No module named 'typesafe_sdk'",
)
UNRELATED_SKIP = ("f.py", 3, "Skipped: needs a GPU")


# -- Part 1: pure unit tests ----------------------------------------------------------------------


def finder(installed):
    """A find_spec stand-in: a truthy spec for each name in ``installed``, None for the rest."""

    def find_spec(name):
        return object() if name in installed else None

    return find_spec


def raising_finder(error, name):
    """A find_spec stand-in that raises ``error`` for ``name`` and finds every other module."""

    def find_spec(found):
        if found == name:
            raise error
        return object()

    return find_spec


def fake_report(nodeid, *, marked=False, skipped=False, longrepr=None):
    keywords = {"live_sdk": True} if marked else {}
    return SimpleNamespace(nodeid=nodeid, keywords=keywords, skipped=skipped, longrepr=longrepr)


def test_nothing_missing_when_both_modules_are_found():
    assert live.missing_live_modules(finder(BOTH)) == []


def test_only_httpx2_missing():
    assert live.missing_live_modules(finder(("typesafe_sdk",))) == ["httpx2"]


def test_only_typesafe_sdk_missing():
    assert live.missing_live_modules(finder(("httpx2",))) == ["typesafe_sdk"]


def test_both_missing_are_named_in_order():
    assert live.missing_live_modules(finder(())) == ["typesafe_sdk", "httpx2"]


@pytest.mark.parametrize("error", [ValueError("bad __spec__"), ImportError("broken")])
@pytest.mark.parametrize("name", BOTH)
def test_a_find_spec_error_counts_as_missing(error, name):
    assert live.missing_live_modules(raising_finder(error, name)) == [name]


MISSING_CASES = [
    ([], None),
    (["httpx2"], "httpx2"),
    (["typesafe_sdk"], "typesafe_sdk"),
    (["typesafe_sdk", "httpx2"], "typesafe_sdk, httpx2"),
]


def named_missing(line):
    found = MISSING_RE.search(line)
    return found.group(1) if found else None


@pytest.mark.parametrize(("missing", "named"), MISSING_CASES)
def test_header_and_summary_name_exactly_the_missing_modules(missing, named):
    assert named_missing(live.header_line(missing)) == named
    assert named_missing(live.summary_line(missing, COUNTS)) == named


def test_installed_lines_say_installed_and_never_not():
    for line in (live.header_line([]), live.summary_line([], COUNTS)):
        assert "INSTALLED" in line
        assert "NOT" not in line


def test_installed_missing_one_and_missing_both_lines_are_pairwise_different():
    states = [[], ["httpx2"], ["typesafe_sdk", "httpx2"]]
    assert len({live.header_line(state) for state in states}) == 3
    assert len({live.summary_line(state, COUNTS) for state in states}) == 3


def test_summary_line_carries_the_three_counts():
    for missing in ([], ["httpx2"]):
        assert "ran=3 skipped=2 deselected=1" in live.summary_line(missing, COUNTS)


def test_no_sdk_tests_gives_zero_counts():
    assert live.sdk_gated_counts({}) == ZERO
    assert live.sdk_gated_counts({"passed": [fake_report("t::plain")]}) == ZERO
    stats = {"warnings": [SimpleNamespace(message="old API")], "": [fake_report("t::plain")]}
    assert live.sdk_gated_counts(stats) == ZERO


def test_passed_call_and_error_teardown_count_as_one_test():
    stats = {
        "passed": [fake_report("t::a", marked=True)],
        "error": [fake_report("t::a", marked=True)],
    }
    assert live.sdk_gated_counts(stats) == {"ran": 1, "skipped": 0, "deselected": 0}


def test_passed_call_and_failed_teardown_count_as_one_test():
    stats = {
        "passed": [fake_report("t::a", marked=True)],
        "failed": [fake_report("t::a", marked=True)],
    }
    assert live.sdk_gated_counts(stats) == {"ran": 1, "skipped": 0, "deselected": 0}


def test_gated_test_skipped_at_setup_counts_as_skipped_not_ran():
    stats = {
        "skipped": [fake_report("t::a", marked=True, skipped=True, longrepr=SDK_SKIP)],
    }
    assert live.sdk_gated_counts(stats) == {"ran": 0, "skipped": 1, "deselected": 0}


def test_nodeid_in_passed_and_skipped_counts_only_as_skipped():
    stats = {
        "passed": [fake_report("t::a", marked=True)],
        "skipped": [fake_report("t::a", marked=True, skipped=True, longrepr=SDK_SKIP)],
    }
    assert live.sdk_gated_counts(stats) == {"ran": 0, "skipped": 1, "deselected": 0}


@pytest.mark.parametrize("module", BOTH)
def test_unmarked_skip_naming_a_live_module_counts_as_skipped(module):
    reason = f"Skipped: could not import '{module}': No module named '{module}'"
    stats = {"skipped": [fake_report("t::a", skipped=True, longrepr=("f.py", 3, reason))]}
    assert live.sdk_gated_counts(stats) == {"ran": 0, "skipped": 1, "deselected": 0}


def test_unmarked_skip_with_an_unrelated_reason_is_ignored():
    stats = {"skipped": [fake_report("t::a", skipped=True, longrepr=UNRELATED_SKIP)]}
    assert live.sdk_gated_counts(stats) == ZERO


def test_a_report_without_a_nodeid_is_ignored():
    no_id = SimpleNamespace(keywords={"live_sdk": True}, skipped=False, longrepr=None)
    stats = {"passed": [no_id], "error": [fake_report(None, marked=True)]}
    assert live.sdk_gated_counts(stats) == ZERO


def test_deselected_items_count_distinct_gated_nodeids_only():
    stats = {
        "deselected": [
            fake_report("t::a", marked=True),
            fake_report("t::a", marked=True),
            fake_report("t::b", marked=True),
            fake_report("t::plain"),
        ],
    }
    assert live.sdk_gated_counts(stats) == {"ran": 0, "skipped": 0, "deselected": 2}


def test_keywords_that_is_not_a_mapping_does_not_crash():
    odd = SimpleNamespace(nodeid="t::odd", keywords=None, skipped=False, longrepr=None)
    assert live.sdk_gated_counts({"passed": [odd], "deselected": [odd]}) == ZERO
    odd_skip = SimpleNamespace(nodeid="t::odd", keywords=None, skipped=True, longrepr=SDK_SKIP)
    assert live.sdk_gated_counts({"skipped": [odd_skip]}) == {
        "ran": 0,
        "skipped": 1,
        "deselected": 0,
    }


# -- Part 2: tiny pytest subprocesses -------------------------------------------------------------

# Blocking a module name in sys.modules makes ``import name`` raise ImportError and makes
# importlib.util.find_spec(name) return None, which is how a missing extra looks to conftest.py.
BOOT = (
    "import os, sys\n"
    "for name in filter(None, os.environ.get('JEV_TEST_BLOCK', '').split(',')):\n"
    "    sys.modules[name] = None\n"
    "import pytest\n"
    "raise SystemExit(pytest.main(sys.argv[1:]))\n"
)
NETGUARD_FILE = "test_notebook_ci_netguard.py"
NETGUARD_TARGET = f"tests/{NETGUARD_FILE}::test_live_backend_call_is_blocked_with_the_sdk_installed"
SDK_FILE = "test_live_sdk.py"
SDK_TARGET = f"tests/{SDK_FILE}"
REAL_SDK_FILES = {
    name: (TESTS_DIR / name).read_text(encoding="utf-8") for name in (SDK_FILE, NETGUARD_FILE)
}
REAL_SDK_TARGETS = (SDK_TARGET, NETGUARD_TARGET)
EXECUTOR_STUB = """
START_WAIT = 0
START_ATTEMPTS = {"Kernel didn't respond": 0, "Kernel died before replying": 0}

if __name__ == "__main__":
    raise SystemExit("network access is blocked (startup harness executor stand-in)")
"""

SAMPLE_MARKED = """
import pytest

pytestmark = pytest.mark.live_sdk


def test_a():
    assert True


def test_b():
    assert True
"""
SAMPLE_TEARDOWN = """
import pytest

pytestmark = pytest.mark.live_sdk


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown")


def test_a(broken_teardown):
    assert True
"""
SAMPLE_IMPORTORSKIP = """
import pytest


def test_needs_the_sdk():
    pytest.importorskip("typesafe_sdk")
"""


def run_pytest(tmp_path, files, *, block=(), stubs=(), args=(), stub_sources=None):
    """Run pytest in ``tmp_path`` with a copy of conftest.py.

    ``stubs`` names get empty stub modules on the path. ``stub_sources`` maps module names to
    source written as their stub; it is written after ``stubs``, so it overrides an empty stub of
    the same name. ``block`` names are blocked in sys.modules.

    Returns (returncode, stdout, counts), where counts is (ran, skipped, deselected) from the
    live line, or None when no such line was printed.
    """
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    shutil.copyfile(TESTS_DIR / "conftest.py", tests / "conftest.py")
    (tmp_path / "pytest.ini").write_text("", encoding="utf-8")
    for name, source in files.items():
        (tests / name).write_text(textwrap.dedent(source), encoding="utf-8")
    if NETGUARD_FILE in files:
        # Netguard loads these at collection to calculate its executor timeout.
        shutil.copyfile(TESTS_DIR / "executor_budget.py", tests / "executor_budget.py")
        tools = tmp_path / "tools"
        tools.mkdir(exist_ok=True)
        (tools / "execute_notebook.py").write_text(EXECUTOR_STUB, encoding="utf-8")
    stub_dir = tmp_path / "stubs"
    shutil.rmtree(stub_dir, ignore_errors=True)
    stub_dir.mkdir()
    for name in stubs:
        (stub_dir / f"{name}.py").write_text("", encoding="utf-8")
    for name, source in (stub_sources or {}).items():
        (stub_dir / f"{name}.py").write_text(source, encoding="utf-8")
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("JEV_COOKBOOK_", "TYPESAFE_"))
    }
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(stub_dir), str(SRC_DIR)])
    env["JEV_TEST_BLOCK"] = ",".join(block)
    proc = subprocess.run(
        [sys.executable, "-c", BOOT, "-p", "no:cacheprovider", "--import-mode=importlib", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    match = RESULT_RE.search(proc.stdout)
    counts = tuple(int(group) for group in match.groups()) if match else None
    return proc.returncode, proc.stdout, counts


def collect(tmp_path, files, *, args=(), **kwargs):
    """Return the exit code and output from a collect-only run."""
    return run_pytest(tmp_path, files, args=["--collect-only", "-q", *args], **kwargs)[:2]


def collected_count(out):
    return sum(line.startswith("tests/") and "::" in line for line in out.splitlines())


def live_summary(out):
    """The one terminal-summary line of a run (it starts with the state, not the header label)."""
    lines = [line for line in out.splitlines() if line.startswith("live extra ") and "ran=" in line]
    assert len(lines) == 1, out
    return lines[0]


@pytest.fixture(scope="module")
def absent(tmp_path_factory):
    """The real SDK-gated tests with both modules blocked: collect result and a normal run."""
    tmp = tmp_path_factory.mktemp("absent")
    collect_rc, collect_out = collect(tmp, REAL_SDK_FILES, block=BOTH, args=REAL_SDK_TARGETS)
    assert collect_rc == 0, collect_out
    assert NETGUARD_TARGET in collect_out
    rc, out, counts = run_pytest(tmp, REAL_SDK_FILES, block=BOTH, args=REAL_SDK_TARGETS)
    return SimpleNamespace(collected=collected_count(collect_out), rc=rc, out=out, counts=counts)


def test_absent_extra_skips_each_test_one_by_one(absent):
    assert absent.collected > 1  # one skip per test, not one skip for the whole module
    assert absent.counts is not None, absent.out
    ran, skipped, deselected = absent.counts
    assert absent.rc == 0
    assert (ran, skipped, deselected) == (0, absent.collected, 0)
    assert "live extra NOT INSTALLED (missing: typesafe_sdk, httpx2)" in absent.out
    assert "live extra (typesafe_sdk, httpx2): NOT INSTALLED" in absent.out
    assert "passed" not in absent.out.splitlines()[-1]


def test_quiet_run_still_prints_the_summary_line(tmp_path, absent):
    rc, out, counts = run_pytest(
        tmp_path, REAL_SDK_FILES, block=BOTH, args=["-q", *REAL_SDK_TARGETS]
    )
    assert rc == 0
    assert counts == absent.counts
    assert live_summary(out).startswith("live extra NOT INSTALLED")


@pytest.mark.parametrize("missing", BOTH)
def test_one_missing_live_module_skips_every_gated_test(tmp_path, absent, missing):
    stubs = tuple(name for name in BOTH if name != missing)
    # An installed SDK can itself import httpx2 at startup.
    stub_sources = {"typesafe_sdk": "import httpx2"} if missing == "httpx2" else None
    rc, out, counts = run_pytest(
        tmp_path,
        REAL_SDK_FILES,
        stubs=stubs,
        block=(missing,),
        stub_sources=stub_sources,
        args=REAL_SDK_TARGETS,
    )
    assert rc == 0, out
    assert counts == (0, absent.collected, 0), out
    assert named_missing(live_summary(out)) == missing


def test_real_sdk_cases_are_selected_by_the_live_sdk_marker(tmp_path, absent):
    rc, out = collect(
        tmp_path, REAL_SDK_FILES, stubs=BOTH, args=["-m", "live_sdk", *REAL_SDK_TARGETS]
    )
    assert rc == 0, out
    assert NETGUARD_TARGET in out
    assert collected_count(out) == absent.collected, out


def test_the_netguard_test_runs_when_both_modules_import(tmp_path):
    rc, out, counts = run_pytest(tmp_path, REAL_SDK_FILES, stubs=BOTH, args=[NETGUARD_TARGET])
    assert rc == 0, out
    assert counts == (1, 0, 0), out


def test_both_installed_says_so_and_runs_the_marked_tests(tmp_path, absent):
    rc, out, counts = run_pytest(tmp_path, {"test_sample.py": SAMPLE_MARKED}, stubs=BOTH)
    sample_count = SAMPLE_MARKED.count("\ndef test_")
    assert rc == 0
    assert counts == (sample_count, 0, 0)
    installed = live_summary(out)
    assert installed.startswith("live extra INSTALLED")
    not_installed = live_summary(absent.out)
    assert not_installed.startswith("live extra NOT INSTALLED")
    assert installed.split()[:3] != not_installed.split()[:3]


def test_zero_sdk_tests_still_prints_the_line(tmp_path):
    files = {"test_plain.py": "def test_plain():\n    assert True\n"}
    rc, out, counts = run_pytest(tmp_path, files, block=BOTH)
    assert rc == 0
    assert counts == (0, 0, 0)
    assert live_summary(out).startswith("live extra NOT INSTALLED")


def test_deselected_gated_tests_are_counted(tmp_path):
    rc, out, counts = run_pytest(
        tmp_path, {"test_sample.py": SAMPLE_MARKED}, stubs=BOTH, args=["-k", "not test_b"]
    )
    assert rc == 0
    assert counts == (1, 0, 1)  # test_a ran, test_b was deselected


def test_skip_raised_inside_a_test_is_counted_by_its_reason(tmp_path):
    rc, out, counts = run_pytest(tmp_path, {"test_inner_skip.py": SAMPLE_IMPORTORSKIP}, block=BOTH)
    assert rc == 0
    assert counts == (0, 1, 0)


def test_teardown_error_after_a_pass_is_one_test(tmp_path):
    rc, out, counts = run_pytest(tmp_path, {"test_teardown.py": SAMPLE_TEARDOWN}, stubs=BOTH)
    assert rc != 0
    assert "1 passed" in out and "1 error" in out
    assert counts == (1, 0, 0)


# -- A broken install is an error, not a skip -----------------------------------------------------


@pytest.mark.parametrize(
    ("broken", "source", "diagnostic", "block"),
    [
        pytest.param(
            "typesafe_sdk",
            'raise ImportError("cannot import name x from pydantic")',
            "ImportError: cannot import name x from pydantic",
            (),
            id="sdk-import-error",
        ),
        pytest.param(
            "typesafe_sdk",
            'raise ModuleNotFoundError("No module named pydantic", name="pydantic")',
            "ModuleNotFoundError: No module named pydantic",
            (),
            id="sdk-transitive-missing",
        ),
        pytest.param(
            "httpx2",
            'raise ImportError("broken httpx2")',
            "ImportError: broken httpx2",
            (),
            id="httpx2-import-error",
        ),
        pytest.param(
            "typesafe_sdk",
            'raise ModuleNotFoundError("No module named typesafe_sdk._core", name="typesafe_sdk._core")',
            "ModuleNotFoundError: No module named typesafe_sdk._core",
            (),
            id="sdk-own-submodule-missing",
        ),
        pytest.param(
            "typesafe_sdk",
            'raise ModuleNotFoundError("broken installed SDK", name="typesafe_sdk")',
            "ModuleNotFoundError: broken installed SDK",
            (),
            id="sdk-found-but-reports-own-name-missing",
        ),
        pytest.param(
            "typesafe_sdk",
            'raise ImportError("broken SDK with httpx2 absent")',
            "ImportError: broken SDK with httpx2 absent",
            ("httpx2",),
            id="sdk-broken-httpx2-absent",
        ),
        pytest.param(
            "httpx2",
            'raise ImportError("broken httpx2 with SDK absent")',
            "ImportError: broken httpx2 with SDK absent",
            ("typesafe_sdk",),
            id="httpx2-broken-sdk-absent",
        ),
    ],
)
def test_a_present_but_broken_module_fails_with_its_import_error(
    tmp_path, broken, source, diagnostic, block
):
    for target, expected_exit, expected_counts in (
        (SDK_TARGET, 2, (0, 0, 0)),
        (NETGUARD_TARGET, 1, (1, 0, 0)),
    ):
        rc, out, counts = run_pytest(
            tmp_path,
            REAL_SDK_FILES,
            stubs=BOTH,
            block=block,
            stub_sources={broken: source},
            args=[target],
        )
        assert rc == expected_exit, out
        assert diagnostic in out, out
        assert counts == expected_counts, out
