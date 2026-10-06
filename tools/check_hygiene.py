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
output payloads (base64 data is deliberately not scanned), and git history are out of scope.
No hex token of any length is caught by the entropy rule (hex cannot reach the threshold); a
hex-format key is caught only by the header, bearer and assignment rules. ANSI colour codes
are stripped before scanning. UTF-8 and UTF-16/32 text is decoded; a notebook of any size is
parsed, nbformat 3 and 4 are understood, and anything else that cannot be scanned (unknown
notebook layout, undecodable or oversized non-image file) is reported as a finding rather than
skipped. Zip, npz, gz and npy files are opened and their contents scanned (nesting up to 3 deep). Known image, font and PDF suffixes are skipped quietly. Findings never print the
matched value in full.
"""

from __future__ import annotations

import codecs
import gzip
import io
import json
import math
import re
import subprocess
import sys
import zipfile
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

# Non-notebook text files above this size are reported, not skipped. Notebooks have no limit:
# their binary payloads are skipped by key, so what is left is small.
MAX_FILE_BYTES = 20_000_000

# Binary formats that are expected in a repository and are skipped quietly. Any other file
# that cannot be decoded as text is reported as unscanned-file.
_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".woff", ".woff2", ".ttf",
    ".otf", ".pyc",
}  # fmt: skip

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
# A "word" is a whitespace/quote-delimited run. A word shaped like a path or URL is scored
# per "/"-separated segment, so a commit permalink or fixtures/replay/<hash>.json is not one
# long "random" token. Any other word is scored whole, "/" included, because base64 keys
# contain "/". Path-shaped: contains "://", starts with a real-looking absolute directory
# (/home, /usr, ...), "./", "../" or a drive letter, or ends in a file-like suffix.
# Hexadecimal strings never reach the entropy threshold (16 symbols give at most 4.0 bits per
# character), which is why they are not flagged; it also means a hex-format key is NOT caught
# by this rule, only by the header, bearer and assignment rules.
_WORD = re.compile(r"""[^\s"'<>()\[\]{},;`]+""")
_TOKEN = re.compile(r"[A-Za-z0-9_+=-]{32,}")
_TOKEN_SLASH = re.compile(r"[A-Za-z0-9_+=/-]{32,}")
_PATH_SHAPED = re.compile(r"://|^/[a-z_.-]+/|^\.{1,2}/|^[A-Za-z]:[\/]|\.[A-Za-z0-9]{1,5}$")
_DATA_URI = re.compile(r"data:[\w./+-]+;base64,[A-Za-z0-9+/=]+")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
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
    for word in _WORD.findall(line):
        pattern = _TOKEN if _PATH_SHAPED.search(word) else _TOKEN_SLASH
        for t in pattern.findall(word):
            # Random base64 sometimes has no digit; "+", "/" or "=" then marks it as non-prose.
            mixed = any(c.isalpha() for c in t) and any(c.isdigit() or c in "+/=" for c in t)
            if mixed and _entropy(t) >= _ENTROPY_THRESHOLD:
                yield "high-entropy-token", _mask(t)


# --- local-environment rules (outputs and metadata only) -------------------------------

_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "windows-user-path",
        re.compile(r"\b[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+[^\\/\s]+", re.I),
    ),
    ("windows-absolute-path", re.compile(r"\b[A-Za-z]:\\+[A-Za-z0-9_$.]")),
    # A home directory with or without a trailing slash: PosixPath('/home/tim') too.
    ("linux-home-path", re.compile(r"(?<![\w.])/home/[^/\s<>'\"`)\\]+")),
    ("macos-home-path", re.compile(r"(?<![\w.])/Users/[^/\s<>'\"`)\\]+")),
    ("wsl-unc-path", re.compile(r"[\\/]{2}wsl(?:\.localhost|\$)[\\/]", re.I)),
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
    text = _ANSI.sub("", text)  # IPython colours traceback paths; escapes defeat \b and lookbehinds
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
            if key in ("attachments", "png", "jpeg", "pdf"):  # attachments; nbformat 3 images
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
    # nbformat 4 keeps cells at the top level; nbformat 3 keeps them in worksheets and
    # calls the source "input".
    cells: list = []
    if isinstance(nb.get("cells"), list):
        cells = nb["cells"]
    elif isinstance(nb.get("worksheets"), list):
        for sheet in nb["worksheets"]:
            if isinstance(sheet, dict) and isinstance(sheet.get("cells"), list):
                cells.extend(sheet["cells"])
    else:
        results.append(("notebook", "unrecognized-notebook-layout", "no cells or worksheets"))
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            continue
        base = f"cell {index} ({cell.get('cell_type', '?')})"
        source = cell.get("source", cell.get("input", ""))
        add(f"{base} source", _as_text(source), environment=False)
        for key, value in cell.items():
            if key in ("source", "input", "cell_type", "id", "execution_count", "prompt_number"):
                continue
            where = "outputs" if key == "outputs" else key
            for label, text in _walk_strings(value, f"{base} {where}"):
                add(label, text, environment=True)
    return results


def _decode(raw: bytes) -> str | None:
    """Decode UTF-8 or UTF-16/32 (BOM, or the NUL pattern of ASCII text); None if binary."""
    for bom, codec in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if raw.startswith(bom):
            try:
                return raw.decode(codec)
            except UnicodeDecodeError:
                return None
    if b"\0" not in raw:
        return raw.decode("utf-8-sig", errors="replace")
    sample = raw[:4096]
    for codec, nul_slice in (("utf-16-le", sample[1::2]), ("utf-16-be", sample[0::2])):
        if nul_slice and nul_slice.count(0) > 0.9 * len(nul_slice):
            try:
                return raw.decode(codec)
            except UnicodeDecodeError:
                return None
    return None


_ARCHIVE_SUFFIXES = {".zip", ".npz", ".gz"}
_MAX_ARCHIVE_DEPTH = 3


def _archive_members(raw: bytes, suffix: str, name: str) -> Iterator[tuple[str, bytes] | str]:
    """Yield (member name, bytes) for each member, or an error string if unreadable."""
    try:
        if suffix == ".gz":
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as fh:
                data = fh.read(MAX_FILE_BYTES + 1)
            yield (name[:-3] if name.endswith(".gz") else name + "!gunzip", data)
            return
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if info.file_size > MAX_FILE_BYTES:
                    yield f"member {info.filename} larger than the limit"
                    continue
                yield (f"{name}!{info.filename}", zf.read(info))
    except (
        OSError,
        EOFError,
        zipfile.BadZipFile,
        zlib.error,
        RuntimeError,
        NotImplementedError,
    ) as exc:
        yield f"unreadable archive: {exc}"


def scan_bytes(raw: bytes, name: str, depth: int = 0) -> list[Finding]:
    """Scan one file's bytes; archives (zip, npz, gz) are opened and their members scanned."""
    suffix = Path(name.split("!")[-1]).suffix.lower()
    if suffix in _ARCHIVE_SUFFIXES:
        if depth >= _MAX_ARCHIVE_DEPTH:
            return [Finding(name, "file", "unscanned-file", "archives nested too deeply")]
        findings: list[Finding] = []
        for member in _archive_members(raw, suffix, name):
            if isinstance(member, str):
                findings.append(Finding(name, "file", "unscanned-file", member))
            elif len(member[1]) > MAX_FILE_BYTES:
                findings.append(Finding(member[0], "file", "unscanned-file", "larger than limit"))
            else:
                findings.extend(scan_bytes(member[1], member[0], depth + 1))
        return findings
    if suffix == ".npy":
        # NumPy arrays are raw bytes with a small header; scan them as latin-1 text.
        text: str | None = raw.decode("latin-1")
    else:
        text = _decode(raw)
    if text is None:
        if suffix in _BINARY_SUFFIXES:
            return []
        return [Finding(name, "file", "unscanned-file", "binary or undecodable")]
    if suffix == ".ipynb":
        try:
            nb = json.loads(text)
        except json.JSONDecodeError as exc:
            return [Finding(name, "file", "invalid-notebook-json", str(exc))]
        if not isinstance(nb, dict):
            return [Finding(name, "file", "invalid-notebook-json", "not an object")]
        return [Finding(name, loc, rule, snip) for loc, rule, snip in scan_notebook_data(nb)]
    return [Finding(name, f"line {n}", rule, snip) for n, rule, snip in scan_text(text)]


def scan_file(path: Path, display: str | None = None) -> list[Finding]:
    name = display or path.as_posix()
    base = path.name
    findings: list[Finding] = []
    if base == ".env" or (base.startswith(".env.") and base != ".env.example"):
        findings.append(Finding(name, "file", "env-file", "tracked .env file"))
    try:
        if path.stat().st_size > MAX_FILE_BYTES and path.suffix not in (".ipynb", ".zip", ".npz"):
            return [*findings, Finding(name, "file", "unscanned-file", "larger than the limit")]
        raw = path.read_bytes()
    except OSError as exc:
        return [*findings, Finding(name, "file", "unreadable", str(exc))]
    return [*findings, *scan_bytes(raw, name)]


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
