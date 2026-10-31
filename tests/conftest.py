"""Report whether the optional ``live`` extra is installed, and count this run's SDK-gated tests.

Refs #264. The ``live`` extra (modules ``typesafe_sdk`` and ``httpx2``) changes how many tests
run, so every pytest run says whether it was present, with counts derived from that run.

The counts are per test node id, over SDK-gated tests of THIS invocation only (tests marked
``live_sdk``, or skipped with a reason naming ``typesafe_sdk`` or ``httpx2``):

- ``ran`` = executed (pass, fail, error, xfail, xpass).
- ``skipped`` = skipped.
- ``deselected`` = gated tests removed by -k, -m or --deselect.

None of them is a whole-suite total.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping
from typing import Any

LIVE_SDK_MODULES = ("typesafe_sdk", "httpx2")
LIVE_SDK_MARKER = "live_sdk"
INSTALL_HINT = 'pip install -e ".[live]"'


def missing_live_modules(
    find_spec: Callable[[str], object] = importlib.util.find_spec,
) -> list[str]:
    """Names from LIVE_SDK_MODULES that cannot be found; a find_spec error counts as missing."""
    missing: list[str] = []
    for name in LIVE_SDK_MODULES:
        try:
            spec = find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            missing.append(name)
    return missing


def _skip_reason(obj: Any) -> str:
    """The skip message of a report: longrepr[2] for the (path, line, message) form."""
    longrepr = getattr(obj, "longrepr", None)
    if isinstance(longrepr, tuple | list) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr)


def is_sdk_gated(obj: Any) -> bool:
    """True for a live_sdk-marked test, or a skip whose reason names a live-extra module."""
    try:
        marked = LIVE_SDK_MARKER in getattr(obj, "keywords", {})
    except TypeError:
        marked = False
    if marked:
        return True
    if not getattr(obj, "skipped", False):
        return False
    reason = _skip_reason(obj)
    return any(name in reason for name in LIVE_SDK_MODULES)


def sdk_gated_counts(stats: Mapping[str, list[Any]]) -> dict[str, int]:
    """Count this run's SDK-gated tests by node id: ran, skipped and deselected."""
    skipped_ids: set[str] = set()
    other_ids: set[str] = set()
    for category in ("passed", "failed", "error", "skipped", "xfailed", "xpassed"):
        for report in stats.get(category, []):
            nodeid = getattr(report, "nodeid", None)
            if nodeid is None or not is_sdk_gated(report):
                continue
            if category == "skipped":
                skipped_ids.add(nodeid)
            else:
                other_ids.add(nodeid)
    deselected_ids = {
        getattr(item, "nodeid", None) for item in stats.get("deselected", []) if is_sdk_gated(item)
    }
    deselected_ids.discard(None)
    return {
        "ran": len(other_ids - skipped_ids),
        "skipped": len(skipped_ids),
        "deselected": len(deselected_ids),
    }


def header_line(missing: list[str]) -> str:
    """The report-header line: whether the live extra is installed."""
    if not missing:
        return "live extra (typesafe_sdk, httpx2): INSTALLED -- SDK-gated tests run"
    return (
        "live extra (typesafe_sdk, httpx2): NOT INSTALLED "
        f"(missing: {', '.join(missing)}) -- SDK-gated tests are skipped one by one; "
        "test totals are not comparable with a run that has it"
    )


def summary_line(missing: list[str], counts: Mapping[str, int]) -> str:
    """The terminal-summary line: the install state and this run's SDK-gated counts."""
    state = "INSTALLED" if not missing else f"NOT INSTALLED (missing: {', '.join(missing)})"
    line = (
        f"live extra {state}: SDK-gated tests in this run: ran={counts['ran']} "
        f"skipped={counts['skipped']} deselected={counts['deselected']}"
    )
    if missing:
        line += (
            f" -- install with {INSTALL_HINT} to run them; "
            "counts are not comparable with a run that has it"
        )
    return line


def pytest_configure(config: Any) -> None:
    """Register the live_sdk marker so that it is known under --strict-markers."""
    config.addinivalue_line(
        "markers",
        "live_sdk: needs the optional live extra (typesafe_sdk and httpx2); "
        "skipped one test at a time when it is absent (#264).",
    )


def pytest_report_header(config: Any) -> str:
    """Header line: whether the live extra is installed."""
    return header_line(missing_live_modules())


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: Any) -> None:
    """Always print the live-extra line, even when no SDK-gated test was collected."""
    terminalreporter.write_sep("-", "optional live extra")
    counts = sdk_gated_counts(terminalreporter.stats)
    terminalreporter.write_line(summary_line(missing_live_modules(), counts))
