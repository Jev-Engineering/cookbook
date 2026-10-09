#!/usr/bin/env python3
"""Repository hygiene check: secrets, local-environment leaks, and notebook outputs.

Standard library only, so CI runs it without installing anything.

    python tools/check_hygiene.py            # every tracked file (git ls-files)
    python tools/check_hygiene.py a.py b.ipynb   # only the named files (pre-commit)

Exit status is 0 when clean, 1 when there are findings, 2 on a usage error (a directory or
missing path among the arguments is one: it is rejected, never counted as scanned).

What it covers (see docs/development.md for the prose version):

* Secret shapes, in every text file and in every notebook string: source cells, markdown,
  code-cell outputs (stream text, text/plain, text/html, any other text mime type,
  error values and tracebacks) and metadata. Rules: private-key blocks, well-known vendor
  key prefixes, JWTs, ``Authorization`` header values, ``Bearer`` tokens, ``name = value``
  assignments for key/token/secret/password names (including ``TYPESAFE_API_KEY=...``),
  tracked ``.env`` files, and long high-entropy tokens.
* Local-environment leaks, in notebook outputs and metadata only: Windows, Linux and macOS
  home-directory paths, absolute drive paths (either slash), username-bearing and
  machine-local temp or install paths, ``os.environ`` dumps, and the running account's name
  (whole word; generic or short names are not checked).

What it does not cover: the TypeSafe documentation shows no fixed key prefix, so a TypeSafe
key is caught only by the generic rules (header, bearer, assignment, entropy), not by a
prefix. Short or low-entropy secrets, secrets split across lines or encoded, image and PDF
output payloads (base64 data is deliberately not scanned), and git history are out of scope.
A bare ``name=VALUE`` assignment (letters of one case or digits joined by ``_``, the value
also by ``.``, no quotes) is code and is not scored by the entropy rule, so a long all-lowercase
or all-uppercase secret assigned, unquoted, to a name that contains none of api key, secret,
token, password, access key or credential is not caught by it.
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
import functools
import getpass
import gzip
import io
import json
import math
import os
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
# A name assigned a bare name, such as a ruff-style keyword argument
# ``startup_timeout=KERNEL_START_TIMEOUT``, is code, not a secret. Both sides are runs of
# letters or of digits joined by "_" (the right side also by "."), where no run mixes letters
# with digits and no run mixes cases (SCREAMING_SNAKE or lower_snake, no quotes); the left side
# starts with a letter run. A left side that names a secret (api key, secret, token, password,
# access key, credential) is never exempt, because a one-case value such as ``token=`` plus
# 36 lowercase letters is a real secret shape. A mixed-case or letter-and-digit run on either
# side is still scored, so ``token=a1B2c3...``, a key followed by ``=1`` and a quoted
# string are all still scored.
_RUN = r"(?:[A-Z]+|[a-z]+|[0-9]+)"
_IDENT_ASSIGNMENT = re.compile(rf"_*(?:[A-Z]+|[a-z]+)(?:_+{_RUN})*_*=_*{_RUN}(?:[_.]+{_RUN})*_*")
_SECRET_NAME = re.compile(
    r"api[_-]?key|secret|token|passw(?:or)?d|access[_-]?key|credential", re.IGNORECASE
)


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
        if _IDENT_ASSIGNMENT.fullmatch(word) and not _SECRET_NAME.search(word.partition("=")[0]):
            continue
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
    # The same drive path written with a forward slash (D:/work/x); "://" in a URL is excluded.
    ("windows-drive-path", re.compile(r"\b[A-Za-z]:/(?!/)[A-Za-z0-9_$.]")),
    # pytest names its temp root after the account: /tmp/pytest-of-alice/pytest-0/...
    ("username-temp-path", re.compile(r"pytest-of-[^/\\\s<>{}$'\"`)]+")),
    # Machine-local roots: macOS per-user temp, conda and Homebrew prefixes, mounted volumes.
    # They name the local setup rather than a person.
    ("local-temp-path", re.compile(r"(?<![\w.])(?:/private)?/var/folders/")),
    (
        "local-install-path",
        re.compile(
            r"(?<![\w.])/(?:opt/(?:ana|mini|micro|mamba)?(?:conda|forge|mamba)\d*(?![\w-])"
            r"|opt/homebrew(?![\w-])|usr/local/Caskroom(?![\w-])|Volumes/)"
        ),
    ),
)

# Common non-personal account names (CI runners, containers, notebook hosts). A local account
# with one of these names, or one shorter than _MIN_USERNAME_LENGTH, is not checked for by
# name: it is an ordinary word and would only produce false findings.
_GENERIC_USERNAMES = frozenset(
    "root runner user users admin administrator ubuntu debian vscode jovyan codespace colab "
    "docker default guest system work build github node pi ec2-user sagemaker "
    # Ordinary words that are also account names: flagging them would reject plain prose.
    # "agent" is this container's own account name (the word that motivated this list in the
    # first place: an agent's own printed output, e.g. "the agent will retry", tripped the
    # local-username rule on ordinary prose). "task", "worker", "sandbox" and "service" are
    # the same shape of word in the same family of containers (CI runners, agent sandboxes,
    # cloud notebook hosts) and are added alongside it for the same reason.
    "hello will mark page grant data test demo dev main home public temp owner info mail "
    "agent task worker sandbox service".split()
)
_MIN_USERNAME_LENGTH = 4

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


def _local_usernames() -> frozenset[str]:
    """Names of the account running the check, lower-cased, minus generic or short ones."""
    names = {os.environ.get(v, "") for v in ("USER", "USERNAME", "LOGNAME")}
    try:
        names.add(getpass.getuser())
    except (OSError, KeyError, ImportError):
        pass  # no account name is available: the name check then does nothing
    lowered = {n.strip().lower() for n in names}
    return frozenset(
        n for n in lowered if len(n) >= _MIN_USERNAME_LENGTH and n not in _GENERIC_USERNAMES
    )


@functools.lru_cache(maxsize=1)
def _username_pattern() -> re.Pattern[str] | None:
    names = sorted(_local_usernames(), key=len, reverse=True)
    if not names:
        return None
    alternation = "|".join(re.escape(n) for n in names)
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alternation})(?![A-Za-z0-9])", re.IGNORECASE)


def _scan_environment_text(text: str) -> Iterator[tuple[str, str]]:
    for line in text.splitlines():
        for rule, pattern in _PATH_PATTERNS:
            m = pattern.search(line)
            if m:
                yield rule, m.group(0)[:4] + "..."
    username = _username_pattern()
    if username is not None:
        for line in text.splitlines():
            m = username.search(line)
            if m:
                # Never echo the name: it is exactly what this rule keeps out of the repository.
                yield "local-username", f"the current account name (len {len(m.group(0))})"
                break
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


_SAFE_KEY = re.compile(r"[A-Za-z0-9_./+-]{1,48}")
_LONG_RUN = re.compile(r"[A-Za-z0-9]{16}")


def _shown(key: object) -> str:
    """A dict key as it may appear in a finding location.

    Keys come from the file under test, so one can be (or contain) a secret, a local path or
    the account name. Only a short, ordinary-looking key such as ``text/plain`` that trips no
    rule in force at a notebook output or metadata location is printed; any other is hidden.
    """
    if (
        isinstance(key, str)
        and _SAFE_KEY.fullmatch(key)
        and not _LONG_RUN.search(key)
        and not scan_text(key, environment=True)
    ):
        return key
    return "<key>"


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
            if isinstance(key, str):
                yield f"{label} <key name>", key  # a secret used as a key is still a secret
            yield from _walk_strings(v, f"{label}.{_shown(key)}")


_CELL_TYPES = frozenset({"code", "markdown", "raw", "heading"})
_CELL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def scan_notebook_data(nb: dict) -> list[tuple[str, str, str]]:
    """Return (location, rule, snippet) for a parsed notebook."""
    results: list[tuple[str, str, str]] = []

    def add(label: str, text: str, *, environment: bool) -> None:
        for line_no, rule, snip in scan_text(text, environment=environment):
            where = f"{label} line {line_no}" if line_no else label
            results.append((where, rule, snip))

    def malformed(label: str, value: object, why: str) -> None:
        """A node the notebook format does not allow: report it, and still read its strings."""
        results.append((label, "malformed-notebook-node", f"{why} (is {type(value).__name__})"))
        for where, text in _walk_strings(value, label):
            add(where, text, environment=True)

    for key, value in nb.items():
        if key in ("cells", "worksheets"):
            continue
        add(f"{_shown(key)} <key name>", key if isinstance(key, str) else "", environment=True)
        for label, text in _walk_strings(value, _shown(key)):
            add(label, text, environment=True)
    # nbformat 4 keeps cells at the top level; nbformat 3 keeps them in worksheets and
    # calls the source "input". Both are read when both are present.
    cells: list[tuple[str, object]] = []
    if isinstance(nb.get("cells"), list):
        cells.extend((f"cell {i}", c) for i, c in enumerate(nb["cells"]))
    if isinstance(nb.get("worksheets"), list):
        for number, sheet in enumerate(nb["worksheets"]):
            if not isinstance(sheet, dict):
                malformed(f"worksheet {number}", sheet, "worksheet is not an object")
                continue
            for key, value in sheet.items():
                if key == "cells":
                    continue
                shown = f"worksheet {number} {_shown(key)}"
                add(f"{shown} <key name>", key if isinstance(key, str) else "", environment=True)
                for label, text in _walk_strings(value, shown):
                    add(label, text, environment=True)
            sheet_cells = sheet.get("cells")
            if isinstance(sheet_cells, list):
                cells.extend((f"worksheet {number} cell {i}", c) for i, c in enumerate(sheet_cells))
            else:
                malformed(f"worksheet {number}", sheet_cells, "worksheet cells is not a list")
    if not any(isinstance(nb.get(k), list) for k in ("cells", "worksheets")):
        results.append(("notebook", "unrecognized-notebook-layout", "no cells or worksheets"))
    for key in ("cells", "worksheets"):  # present but not a list: still read its strings
        if key in nb and not isinstance(nb[key], list):
            malformed(key, nb[key], f"{key} is not a list")
    for name, cell in cells:
        if not isinstance(cell, dict):
            malformed(name, cell, "cell is not an object")
            continue
        # Only a known cell type is ever printed: the value is untrusted and may hold a secret.
        cell_type = cell.get("cell_type", "?")
        if not isinstance(cell_type, str) or cell_type not in _CELL_TYPES:
            if "cell_type" in cell:
                malformed(f"{name} cell_type", cell_type, "cell_type is not a known cell type")
            cell_type = "?"
        base = f"{name} ({cell_type})"
        # nbformat 4 calls the code "source", nbformat 3 "input". A cell that has both is
        # odd, so both are read: neither can hide text from the scan.
        for field in ("source", "input"):
            if field not in cell and field == "input":
                continue
            source = cell.get(field, "")
            if not isinstance(source, str | list):
                malformed(f"{base} {field}", source, f"{field} is not a string or list")
            add(f"{base} {field}", _as_text(source), environment=False)
        if "id" in cell:
            cell_id = cell["id"]
            if isinstance(cell_id, str) and _CELL_ID.fullmatch(cell_id):
                add(f"{base} id", cell_id, environment=False)
            else:
                malformed(f"{base} id", cell_id, "id is not 1-64 letters, digits, - or _")
        for key in ("execution_count", "prompt_number"):
            count = cell.get(key)
            if count is not None and (isinstance(count, bool) or not isinstance(count, int)):
                malformed(f"{base} {key}", count, f"{key} is not an integer or null")
        for key, value in cell.items():
            if key in ("source", "input", "cell_type", "id", "execution_count", "prompt_number"):
                continue
            where = _shown(key)
            add(f"{base} {where} <key name>", key, environment=True)
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


def non_files(paths: Iterable[Path]) -> list[Path]:
    """Named paths that are not regular files: a directory is rejected, never half-scanned."""
    return [path for path in paths if not path.is_file()]


def run(paths: Iterable[Path], root: Path, *, named: bool = False) -> list[Finding]:
    """Scan paths. With named=True (explicit arguments) a non-file is a finding, not a skip;
    otherwise (git ls-files) a deleted file or a submodule directory is skipped."""
    findings: list[Finding] = []
    for path in paths:
        if not path.is_file():
            if named:
                kind = "directory" if path.is_dir() else "missing or not a regular file"
                findings.append(Finding(path.as_posix(), "file", "not-a-file", kind))
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
    bad = non_files(paths) if args else []
    if bad:
        for path in bad:
            what = "a directory" if path.is_dir() else "missing or not a regular file"
            print(f"check_hygiene: {path.as_posix()} is {what}", file=sys.stderr)
        print(
            "check_hygiene: name files, or give no arguments to scan every tracked file "
            "(directories are never scanned implicitly)",
            file=sys.stderr,
        )
        return 2
    findings = run(paths, root, named=bool(args))
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
