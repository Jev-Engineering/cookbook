"""The docs may not name a ruff version other than the one `pyproject.toml` pins (issue #303).

`pyproject.toml`'s `dev` extra is the single source of the ruff pin. A doc that restates the
version goes stale at the next bump (`docs/development.md` said `ruff==0.16.10` after the pin had
moved to 0.17.x), so this test fails on any version the pin does not match, and
`docs/development.md` must say where the pin lives. It is not the general documentation-facts
check; it covers this one fact.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"

# Every file that explains the toolchain. Recipe folders are left out: they never state it.
SOURCES = sorted(
    [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / ".pre-commit-config.yaml",
        *(ROOT / "docs").rglob("*.md"),
    ]
)

# `ruff==0.17.1`, `ruff 0.17.1`, `ruff v0.17.1`, `ruff version 0.17.1`, `ruff>=0.17`.
VERSION_AFTER_RUFF = re.compile(
    r"\bruff\b[`'\"]?\s*(?:version\s*)?(?:[=<>~!]=?\s*)?v?(\d+\.\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


def pinned_ruff() -> str:
    match = re.search(r'"ruff==(\d+\.\d+\.\d+)"', PYPROJECT.read_text(encoding="utf-8"))
    assert match, 'pyproject.toml no longer pins "ruff==X.Y.Z" in the dev extra'
    return match.group(1)


def named_versions(text: str) -> list[str]:
    return [m.group(1) for m in VERSION_AFTER_RUFF.finditer(text)]


def test_the_pin_is_found():
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned_ruff())


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_doc_names_a_ruff_version_that_differs_from_the_pin(path):
    pin = pinned_ruff()
    stale = [v for v in named_versions(path.read_text(encoding="utf-8")) if v != pin]
    # A version named only to describe a historical stale global (`ruff (0.14.0 was seen)`) is
    # separated from the word "ruff" by a parenthesis and is not matched; anything directly
    # after the word is a claim about the current version.
    assert not stale, (
        f"{path.relative_to(ROOT)} names ruff {stale} but pyproject.toml pins {pin}; "
        "point at pyproject.toml instead of restating the version"
    )


def test_development_md_points_at_pyproject_for_the_pin():
    text = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    at = text.find("stale global ruff")
    assert at != -1, "the stale-global-ruff sentence in docs/development.md moved"
    before = text[max(0, at - 400) : at]
    assert "pyproject.toml" in before, "the sentence must say where the ruff pin lives"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("the pinned `ruff==0.16.10` is first", ["0.16.10"]),
        ("ruff 0.17.1 formats", ["0.17.1"]),
        ("ruff version 0.9.2", ["0.9.2"]),
        ("`ruff` v0.17.1", ["0.17.1"]),
        ("ruff>=0.17", ["0.17"]),
        ("a stale global ruff (0.14.0 was seen)", []),  # history, not a claim
        ("ruff check . and ruff format", []),
        ("pinned in `pyproject.toml`", []),
    ],
)
def test_the_matcher_finds_what_it_must(text, expected):
    assert named_versions(text) == expected
