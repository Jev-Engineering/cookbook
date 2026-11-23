"""Source-only generator references shared by manifest producers and validation.

A word mention is deliberately weaker than a callable check: comments, constants and invalid
Python can mention a name. Recipe tests and review establish that a generator draws its image.
Only regular UTF-8 source files in this installed package are supported, not namespace packages
or zip installs. Nothing here imports a generator or its parents.
"""

from __future__ import annotations

import re
from pathlib import Path

# Kept equal to the manifest schema's pattern. Groups 1 and 3 are source and function.
GENERATOR = re.compile(
    r"^([A-Za-z0-9_][A-Za-z0-9_.-]*[.]py|jev_cookbook([.][a-z_][a-z0-9_]*)+):([A-Za-z_][A-Za-z0-9_]*)$"
)
PACKAGE_DIR = Path(__file__).resolve().parent
SourceCache = dict[tuple[Path, str], bool | None]


def source_mentions(
    source: Path, function: str, *, cache: SourceCache | None = None
) -> bool | None:
    """Whether a readable UTF-8 file mentions the name as a word; ``None`` if unreadable.

    The caller owns an optional cache for one validation call. No file contents or results
    survive the call, even when a later edit preserves both file size and modification time.
    """
    key = (source, function)
    if cache is not None and key in cache:
        return cache[key]
    try:
        text = source.read_text(encoding="utf-8") if source.is_file() else None
        answer = None if text is None else bool(re.search(rf"\b{re.escape(function)}\b", text))
    except (OSError, UnicodeDecodeError):
        answer = None
    if cache is not None:
        cache[key] = answer
    return answer


def package_generator_problem(
    module: str,
    function: str,
    *,
    package_dir: Path | None = None,
    cache: SourceCache | None = None,
) -> str | None:
    """Explain an unsupported or unreadable package source, or a missing word mention.

    Packages take precedence over same-named modules. Every intermediate package must have
    an ``__init__.py``; namespace packages and sources in archives are unsupported by policy.
    """
    missing = f"{module} is not a module of the jev_cookbook package"
    if not GENERATOR.fullmatch(f"{module}:{function}") or not module.startswith("jev_cookbook."):
        return missing
    root = PACKAGE_DIR if package_dir is None else package_dir
    parts = module.split(".")[1:]
    try:
        if any(
            not root.joinpath(*parts[:i], "__init__.py").is_file() for i in range(1, len(parts))
        ):
            return missing
        base = root.joinpath(*parts)
        source = next(
            (p for p in (base / "__init__.py", base.with_suffix(".py")) if p.is_file()), None
        )
    except OSError:
        return f"{module} is not a readable Python module"
    if source is None:
        return missing
    answer = source_mentions(source, function, cache=cache)
    if answer is None:
        return f"{module} is not a readable Python module"
    if not answer:
        return f"{module} does not mention {function!r}"
    return None
