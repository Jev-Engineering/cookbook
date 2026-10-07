"""A narrow key- and token-shaped string scan for fixture files.

``tools/check_hygiene.py`` is the repository's secret scanner, but ``tools/`` is not part of
the installed package, so this module carries a copy of its secret rules (not its local-path
or ``os.environ`` rules, which only apply to notebook outputs). The rule names are the same:
private-key-block, sk-prefixed-key, github-token, github-fine-grained-token,
aws-access-key-id, slack-token, google-api-key, jwt, authorization-header-value,
bearer-token, secret-assignment and high-entropy-token. A test compares the copy's rule
definitions and function source with ``tools/check_hygiene.py``, so the copy cannot drift
unnoticed. Scanning fixtures is narrower than the full hygiene run, which also reads every
tracked file: this scan only sees the files of a recipe's ``fixtures/`` folder (inputs, labels
and every responses file) and reports a line number, never the whole value.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator

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


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """Return ``(line number, rule, masked snippet)`` for each key-shaped string."""
    hits: list[tuple[int, str, str]] = []
    text = _ANSI.sub("", text)
    for number, line in enumerate(text.splitlines(), start=1):
        hits.extend((number, rule, snip) for rule, snip in _scan_secrets_line(line))
    return hits
