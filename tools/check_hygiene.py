#!/usr/bin/env python3
"""Repository hygiene check: secrets, local-environment leaks, and notebook outputs.

Standard library only, so CI runs it without installing anything.

    python tools/check_hygiene.py            # every tracked file (git ls-files)
    python tools/check_hygiene.py a.py b.ipynb   # only the named files (pre-commit)

Exit status is 0 when clean, 1 when there are findings, 2 on a usage error.

What it covers (see docs/development.md for the prose version):

* Secret shapes, in every text file and in every notebook string: source cells, markdown,
  code-cell outputs (stream text, text/plain, text/html, any other text mime type,
  error values and tracebacks) and metadata. Rules: private-key blocks, well-known vendor
  key prefixes, JWTs, ``Authorization`` header values, ``Bearer`` tokens, ``name = value``
  assignments for key/token/secret/password names (including ``TYPESAFE_API_KEY=...``),
  tracked ``.env`` files, and long high-entropy tokens.
* Local-environment leaks, in notebook outputs and metadata only: Windows, Linux and macOS
  home-directory paths, other absolute drive paths, and ``os.environ`` dumps.

What it does not cover: the TypeSafe documentation shows no fixed key prefix, so a TypeSafe
key is caught only by the generic rules (header, bearer, assignment, entropy), not by a
prefix. Short or low-entropy secrets, secrets split across lines or encoded, image and PDF
output payloads (base64 data is deliberately not scanned), binary files, and git history are
out of scope. Findings never print the matched value in full.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 2_000_000

# Output mime types whose payload is binary or base64; never scanned.
_BINARY_MIME_PREFIXES = ("image/", "audio/", "video/")
_BINARY_MIMES = {"application/pdf", "application/octet-stream"}

_PLACEHOLDER_MARKERS = (
    "your",
    "example",
    "xxx",
    "redacted",
    "placeholder",
    "changeme",
    "dummy",
    "<",
    ">",
    "{",
    "}",
    "$",
    "...",
    "…",
    "***",
)


@dataclass(frozen=True)
class Finding:
    path: str
    location: str
    rule: str
    snippet: str

    def __str__(self) -> str:
        return f"{self.path}: {self.location}: [{self.rule}] {self.snippet}"


def _mask(value: str) -> str:
    """Show enough to locate a match without reproducing a secret in CI logs."""
    value = value.strip()
    return f"{value[:4]}{'*' * 6} (len {len(value)})"


def _is_placeholder(value: str) -> bool:
    low = value.lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def _entropy(token: str) -> float:
    counts = {c: token.count(c) for c in set(token)}
    n = len(token)
    return -sum(k / n * math.log2(k / n) for k in counts.values())


def _letters_and_digits(value: str) -> bool:
    return any(c.isalpha() for c in value) and any(c.isdigit() for c in value)


# --- secret rules ---------------------------------------------------------------------

_VENDOR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ("sk-prefixed-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ),
)

_AUTH_HEADER = re.compile(
    r"""authorization["']?\s*[:=]\s*["']?(?:(?:bearer|basic|token)\s+)?(?P<v>[^\s"',;)}\]<]+)""",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bbearer\s+(?P<v>[A-Za-z0-9._~+/=-]{16,})", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"""(?:api[_-]?key|apikey|secret|token|passw(?:or)?d|access[_-]?key|credential)s?
        ["']?\]?\s*[:=]\s*["']?(?P<v>[A-Za-z0-9_\-./+=]{16,})""",
    re.IGNORECASE | re.VERBOSE,
)
_TOKEN = re.compile(r"[A-Za-z0-9_+/=-]{32,}")
_HEX_ONLY = re.compile(r"[0-9a-fA-F]+")
_DATA_URI = re.compile(r"data:[\w./+-]+;base64,[A-Za-z0-9+/=]+")
_ENTROPY_THRESHOLD = 4.2


def _scan_secrets_line(line: str) -> Iterator[tuple[str, str]]:
    line = _DATA_URI.sub("data:...", line)
    for rule, pattern in _VENDOR_PATTERNS:
        m = pattern.search(line)
        if m:
            yield rule, _mask(m.group(0))
    m = _AUTH_HEADER.search(line)
    if m and len(m.group("v")) >= 8 and not _is_placeholder(m.group("v")):
        yield "authorization-header-value", _mask(m.group("v"))
    m = _BEARER.search(line)
    if m and not _is_placeholder(m.group("v")):
        yield "bearer-token", _mask(m.group("v"))
    m = _ASSIGNMENT.search(line)
    if m:
        v = m.group("v")
        if _letters_and_digits(v) and not _is_placeholder(v):
            yield "secret-assignment", _mask(v)
    for m in _TOKEN.finditer(line):
        t = m.group(0)
        if (
            _letters_and_digits(t)
            and not _HEX_ONLY.fullmatch(t)  # git SHAs and content hashes
            and _entropy(t) >= _ENTROPY_THRESHOLD
        ):
            yield "high-entropy-token", _mask(t)


# --- local-environment rules (outputs and metadata only) -------------------------------

_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "windows-user-path",
        re.compile(r"\b[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+[^\\/\s]+", re.I),
    ),
    ("windows-absolute-path", re.compile(r"\b[A-Za-z]:\\+[A-Za-z0-9_$.]")),
    ("linux-home-path", re.compile(r"(?<![\w.])/home/[^/\s<>]+/")),
    ("macos-home-path", re.compile(r"(?<![\w.])/Users/[^/\s<>]+/")),
    ("wsl-windows-path", re.compile(r"(?<![\w.])/mnt/[a-z]/")),
    ("root-home-path", re.compile(r"(?<![\w.])/root/")),
)

_ENV_NAMES = {
    "PATH",
    "HOME",
    "USER",
    "USERNAME",
    "USERPROFILE",
    "LOGNAME",
    "SHELL",
    "PWD",
    "COMPUTERNAME",
    "HOSTNAME",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "LANG",
    "TERM",
    "SYSTEMROOT",
    "PROGRAMFILES",
    "OS",
    "VIRTUAL_ENV",
}
_ENV_NAME_REF = re.compile(r"""["']?\b([A-Z][A-Z0-9_]*)["']?\s*(?:=|:)\s*\S""")
_ENV_LINE = re.compile(r"^[A-Z][A-Z0-9_]{2,}=\S")


def _scan_environment_text(text: str) -> Iterator[tuple[str, str]]:
    for line in text.splitlines():
        for rule, pattern in _PATH_PATTERNS:
            m = pattern.search(line)
            if m:
                yield rule, m.group(0)[:4] + "..."
    if "environ(" in text or "environ({" in text:
        yield "environment-dump", "os.environ repr"
        return
    named = {m.group(1) for m in _ENV_NAME_REF.finditer(text)} & _ENV_NAMES
    if len(named) >= 3:
        yield "environment-dump", f"{len(named)} well-known variable names"
        return
    if sum(1 for line in text.splitlines() if _ENV_LINE.match(line)) >= 6:
        yield "environment-dump", "6 or more NAME=value lines"


# --- scanning --------------------------------------------------------------------------


def scan_text(text: str, *, environment: bool = False) -> list[tuple[int, str, str]]:
    """Return (line number, rule, masked snippet) for secrets, plus leaks if asked."""
    hits: list[tuple[int, str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        hits.extend((number, rule, snip) for rule, snip in _scan_secrets_line(line))
    if environment:
        hits.extend((0, rule, snip) for rule, snip in _scan_environment_text(text))
    return hits


def _as_text(value: object) -> str:
    if isinstance(value, list):
        return "".join(str(v) for v in value)
    return value if isinstance(value, str) else ""


def _walk_strings(node: object, label: str) -> Iterator[tuple[str, str]]:
    """Yield (location, text) for every string below node, skipping binary payloads."""
    if isinstance(node, str):
        yield label, node
    elif isinstance(node, list):
        if node and all(isinstance(v, str) for v in node):
            yield label, "".join(node)  # nbformat stores multiline text as a list
        else:
            for i, v in enumerate(node):
                yield from _walk_strings(v, f"{label}[{i}]")
    elif isinstance(node, dict):
        for key, v in node.items():
            if isinstance(key, str) and (
                key.startswith(_BINARY_MIME_PREFIXES) or key in _BINARY_MIMES
            ):
                continue
            if key == "attachments":
                continue
            yield from _walk_strings(v, f"{label}.{key}")


def scan_notebook_data(nb: dict) -> list[tuple[str, str, str]]:
    """Return (location, rule, snippet) for a parsed notebook."""
    results: list[tuple[str, str, str]] = []

    def add(label: str, text: str, *, environment: bool) -> None:
        for line_no, rule, snip in scan_text(text, environment=environment):
            where = f"{label} line {line_no}" if line_no else label
            results.append((where, rule, snip))

    for key, value in nb.items():
        if key in ("cells", "worksheets"):
            continue
        for label, text in _walk_strings(value, key):
            add(label, text, environment=True)
    for index, cell in enumerate(nb.get("cells", [])):
        if not isinstance(cell, dict):
            continue
        base = f"cell {index} ({cell.get('cell_type', '?')})"
        add(f"{base} source", _as_text(cell.get("source", "")), environment=False)
        for key, value in cell.items():
            if key in ("source", "cell_type", "id", "execution_count"):
                continue
            where = "outputs" if key == "outputs" else key
            for label, text in _walk_strings(value, f"{base} {where}"):
                add(label, text, environment=True)
    return results


def scan_file(path: Path, display: str | None = None) -> list[Finding]:
    name = display or path.as_posix()
    base = path.name
    findings: list[Finding] = []
    if base == ".env" or (base.startswith(".env.") and base != ".env.example"):
        findings.append(Finding(name, "file", "env-file", "tracked .env file"))
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return findings
        raw = path.read_bytes()
    except OSError as exc:
        return [*findings, Finding(name, "file", "unreadable", str(exc))]
    if b"\0" in raw:
        return findings
    text = raw.decode("utf-8", errors="replace")
    if path.suffix == ".ipynb":
        try:
            nb = json.loads(text)
        except json.JSONDecodeError as exc:
            return [*findings, Finding(name, "file", "invalid-notebook-json", str(exc))]
        if not isinstance(nb, dict):
            return [*findings, Finding(name, "file", "invalid-notebook-json", "not an object")]
        findings.extend(
            Finding(name, loc, rule, snip) for loc, rule, snip in scan_notebook_data(nb)
        )
    else:
        findings.extend(Finding(name, f"line {n}", rule, snip) for n, rule, snip in scan_text(text))
    return findings


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    return [root / p for p in out.decode("utf-8").split("\0") if p]


def run(paths: Iterable[Path], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            display = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            display = path.as_posix()
        findings.extend(scan_file(path, display))
    return findings


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(__file__).resolve().parent.parent
    try:
        paths = [Path(a) for a in args] if args else tracked_files(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"check_hygiene: cannot list tracked files: {exc}", file=sys.stderr)
        return 2
    findings = run(paths, root)
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\nHygiene check failed: {len(findings)} finding(s). Remove the value or path "
            "from the file (for a notebook, clear the output, fix the cause, and re-run it). "
            "If a real credential was committed, revoke it: deleting it is not enough.",
            file=sys.stderr,
        )
        return 1
    print(f"Hygiene check passed: {len(paths)} file(s) scanned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
