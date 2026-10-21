"""Image provenance: the checks of a recipe's ``assets-manifest.json`` (``docs/fixtures.md``).

A recipe with an ``assets/`` folder lists every image in it in ``assets-manifest.json``, beside
that folder, with where the file came from, its licence and attestations. This module reads
that file and reports what is wrong as ``(file, message, ident)`` tuples, ``message`` starting
with the ``[rule]`` that failed; ``validate_recipe`` turns them into ``Problem`` lines of the form
``path: [rule] message``. The rules:

``manifest-missing``      the recipe has image files and no manifest
``manifest-invalid``      the manifest is not readable UTF-8 JSON, or not an object
``manifest-field``        a field is missing, unknown or of the wrong type or value
``asset-path``            a listed path is not a clean ``assets/...`` path, or resolves outside it
``licence``               the licence is missing or not an allowed SPDX identifier
``attestation``           an attestation is missing, or ``synthetic`` is not true, or another is not false
``duplicate-entry``       one path listed twice
``unlisted-asset``        a file under ``assets/`` (or a ``fields`` image path) has no entry
``missing-file``          an entry names a file that is not there
``hash-mismatch``         ``sha256`` is not the digest of the file
``format-mismatch``       ``format`` is not what the bytes are (or they are neither PNG nor JPEG)
``size-mismatch``         ``width``/``height`` are not the image's
``generator``             the generator script does not exist in the recipe, or does not mention the function
``split-leak``            the same image bytes are named by examples of different splits

Only the standard library is used, so reading an image is a header parse, not a decode. What this
does not do: decode pixels, so the same picture saved twice with different bytes is two hashes;
or judge that a description is true.
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ._schema import check, load_schema

ASSETS_DIR = "assets"
ASSETS_MANIFEST_FILE = "assets-manifest.json"
ASSETS_SCHEMA_FILE = "assets-manifest.schema.json"

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")
_MAX_READ = 16 * 1024 * 1024
_ASSET_PATH = re.compile(
    r"assets/([A-Za-z0-9][A-Za-z0-9_.-]*/)*[A-Za-z0-9][A-Za-z0-9_.-]*[.](png|jpg|jpeg)"
)
# Same text as the "generator" pattern of the schema; group 1 is the file or module, group 3 the function.
_GENERATOR = re.compile(
    r"([A-Za-z0-9_][A-Za-z0-9_.-]*[.]py|jev_cookbook([.][a-z_][a-z0-9_]*)+):([A-Za-z_][A-Za-z0-9_]*)"
)
_MISSING = re.compile(r"missing required field '([^']+)'")
_INDEX = re.compile(r"assets\[(\d+)\]")

Finding = tuple[str, str, "str | None"]  # file shown, "[rule] message", example id or None


def inspect_image(data: bytes) -> tuple[str, int, int] | None:
    """``(format, width, height)`` read from the header of a PNG or JPEG, else ``None``."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) >= 24 and data[12:16] == b"IHDR":
            width, height = struct.unpack(">II", data[16:24])
            return "PNG", width, height
        return None
    if not data.startswith(b"\xff\xd8"):
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            return None
        marker = data[pos]
        pos += 1
        if 0xD0 <= marker <= 0xD8 or marker in (0x01, 0x00):
            continue
        if marker in (0xD9, 0xDA):
            return None
        if pos + 2 > len(data):
            return None
        (length,) = struct.unpack(">H", data[pos : pos + 2])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if length < 8 or pos + 7 > len(data):
                return None
            height, width = struct.unpack(">HH", data[pos + 3 : pos + 7])
            return "JPEG", width, height
        pos += length
    return None


def looks_like_image_path(value: str) -> bool:
    """Is a ``fields`` string meant as an image path?

    The convention: a string with no whitespace that starts with ``assets/`` or ends in
    ``.png``, ``.jpg`` or ``.jpeg`` (any case). Keys do not matter, nesting does not matter.
    Prose that merely mentions a file ("see chart.png") has whitespace and is not a path.
    """
    if not value or any(c.isspace() for c in value):
        return False
    return value.startswith(f"{ASSETS_DIR}/") or value.lower().endswith(IMAGE_SUFFIXES)


def image_path_strings(fields: Any) -> list[str]:
    """Every string value in ``fields`` (at any depth) that ``looks_like_image_path``, in order."""
    found: list[str] = []
    pending = [fields]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if looks_like_image_path(item):
                found.append(item)
        elif isinstance(item, dict):
            pending.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            pending.extend(reversed(item))
    return found


def _listed_files(assets: Path) -> set[str]:
    """Posix paths (``assets/...``) of every file or link under ``assets/``; links not followed."""
    found: set[str] = set()
    for folder, dirs, files in os.walk(assets, followlinks=False):
        here = Path(folder)
        for name in files:
            found.add(f"{ASSETS_DIR}/{(here / name).relative_to(assets).as_posix()}")
        for name in dirs:
            if (here / name).is_symlink():
                found.add(f"{ASSETS_DIR}/{(here / name).relative_to(assets).as_posix()}")
    return found


def _rule(path: str, message: str) -> str:
    missing = _MISSING.match(message)
    field = missing.group(1) if missing else path.rsplit(".", 1)[-1]
    if ".attestations" in path or path.endswith("attestations"):
        return "attestation"
    if field == "licence":
        return "licence"
    if field == "path" and not missing:
        return "asset-path"
    return "manifest-field"


def check_assets(
    recipe: Path,
    examples: Iterable[Any],
    *,
    read_json: Any,
    leak_splits: tuple[str, ...],
) -> list[Finding]:
    """Every problem with the recipe's images and ``assets-manifest.json``.

    ``examples`` are the recipe's ``Example`` rows (``id``, ``split``, ``fields``); ``read_json``
    is ``(path) -> (value, problem message | None)``, the package's strict reader.
    """
    from ..vision import AssetPathError, resolve_asset_path  # PIL: import only when needed

    out: list[Finding] = []
    shown = lambda rel: (recipe / rel).as_posix()  # noqa: E731
    assets_dir = recipe / ASSETS_DIR
    manifest_path = recipe / ASSETS_MANIFEST_FILE
    manifest_name = shown(ASSETS_MANIFEST_FILE)
    actual = _listed_files(assets_dir) if assets_dir.is_dir() else set()

    manifest: Any = None
    if manifest_path.is_file():
        manifest, problem = read_json(manifest_path)
        if problem:
            out.append((manifest_name, f"[manifest-invalid] {problem}", None))
            manifest = None
        elif not isinstance(manifest, dict):
            out.append((manifest_name, "[manifest-invalid] must be a JSON object", None))
            manifest = None
    elif actual:
        out.append(
            (
                manifest_name,
                f"[manifest-missing] the recipe has {len(actual)} file(s) under {ASSETS_DIR}/ "
                f"and no {ASSETS_MANIFEST_FILE}; list every image with its provenance "
                "(docs/fixtures.md, 'Image provenance manifest')",
                None,
            )
        )

    entries: dict[str, dict[str, Any]] = {}  # path -> entry that passed the schema
    named: set[str] = set()  # every path a manifest entry names, valid entry or not
    if manifest is not None:
        schema = load_schema(ASSETS_SCHEMA_FILE)
        raw_entries = manifest.get("assets")
        bad_index: set[int] = set()
        for path, message in check(manifest, schema, schema):
            index = _INDEX.match(path)
            entry = None
            if index and isinstance(raw_entries, list):
                bad_index.add(int(index.group(1)))
                entry = raw_entries[int(index.group(1))]
            entry_path = entry.get("path") if isinstance(entry, dict) else None
            file = (
                shown(entry_path)
                if isinstance(entry_path, str) and _ASSET_PATH.fullmatch(entry_path)
                else manifest_name
            )
            out.append((file, f"[{_rule(path, message)}] {path}: {message}", None))
        for index, entry in enumerate(raw_entries if isinstance(raw_entries, list) else []):
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                continue
            path = entry["path"]
            if _ASSET_PATH.fullmatch(path):
                if path in named:
                    out.append((shown(path), "[duplicate-entry] listed more than once", None))
                    continue
                named.add(path)
                if index not in bad_index:
                    entries[path] = entry

    # Listed and present, and the other way round.
    for path in sorted(named - actual):
        out.append((shown(path), "[missing-file] listed in the manifest but not in assets/", None))
    if manifest is not None:
        for path in sorted(actual - named):
            msg = (
                f"[unlisted-asset] not listed in {ASSETS_MANIFEST_FILE}; "
                f"every file under {ASSETS_DIR}/ needs an entry"
            )
            out.append((shown(path), msg, None))

    # Each entry against its file.
    hashes: dict[str, str] = {}
    for path, entry in sorted(entries.items()):
        if path not in actual:
            continue
        file = shown(path)
        try:
            real = resolve_asset_path(path, root=recipe)
            if not real.is_relative_to((recipe / ASSETS_DIR).resolve()) or not real.is_file():
                raise AssetPathError(f"{path!r} is not a file inside {ASSETS_DIR}/")
            with real.open("rb") as handle:
                data = handle.read(_MAX_READ + 1)
        except (AssetPathError, OSError) as exc:
            out.append((file, f"[asset-path] {exc}", None))
            continue
        if len(data) > _MAX_READ:
            out.append((file, "[size-mismatch] larger than 16 MiB; cannot be a fixture", None))
            continue
        digest = hashlib.sha256(data).hexdigest()
        hashes[path] = digest
        if digest != entry["sha256"]:
            msg = f"[hash-mismatch] sha256 is {digest}, the manifest says {entry['sha256']}"
            out.append((file, msg, None))
        seen = inspect_image(data)
        if seen is None:
            msg = "[format-mismatch] the bytes are neither a PNG nor a JPEG"
            out.append((file, msg, None))
        else:
            fmt, width, height = seen
            if fmt != entry["format"]:
                msg = f"[format-mismatch] the bytes are {fmt}, the manifest says {entry['format']}"
                out.append((file, msg, None))
            if (width, height) != (entry["width"], entry["height"]):
                msg = (
                    f"[size-mismatch] the image is {width} x {height}, the manifest says "
                    f"{entry['width']} x {entry['height']}"
                )
                out.append((file, msg, None))
        generator = _GENERATOR.fullmatch(entry["generator"])
        if generator and generator.group(1).endswith(".py"):
            script = recipe / generator.group(1)
            try:
                text = script.read_text(encoding="utf-8") if script.is_file() else None
            except (OSError, UnicodeDecodeError):
                text = None
            func = generator.group(3)
            if text is None:
                msg = f"[generator] {generator.group(1)} is not a readable file in the recipe"
                out.append((file, msg, None))
            elif not re.search(rf"\b{re.escape(func)}\b", text):
                msg = f"[generator] {generator.group(1)} does not mention {func!r}"
                out.append((file, msg, None))

    # fields: every image path names a manifest entry; no image crosses splits.
    users: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for example in examples:
        if example.fields is None:
            continue
        for value in image_path_strings(example.fields):
            try:
                resolve_asset_path(value, root=recipe)
            except AssetPathError as exc:
                msg = f"[asset-path] fields image path {value!r}: {exc}"
                out.append((shown("fixtures/inputs.jsonl"), msg, example.id))
                continue
            if value not in named:
                msg = (
                    f"[unlisted-asset] fields image path {value!r} has no entry in "
                    f"{ASSETS_MANIFEST_FILE}; write the path exactly as listed"
                )
                out.append((shown("fixtures/inputs.jsonl"), msg, example.id))
            elif value in hashes and example.split in leak_splits:
                users[hashes[value]][example.split].append((example.id, value))
    for digest, by_split in sorted(users.items()):
        if len(by_split) < 2:
            continue
        paths = {path for uses in by_split.values() for _, path in uses}
        if all(entries[p].get("shared_across_splits") is True for p in paths):
            continue
        where = "; ".join(
            f"{split}: {', '.join(f'{i} ({p})' for i, p in uses)}"
            for split, uses in sorted(by_split.items())
        )
        msg = (
            f"[split-leak] the same image (sha256 {digest[:12]}) is named by examples of "
            f"different splits ({where}); set shared_across_splits to true on every entry "
            "of it only if a reference image is meant to be shared"
        )
        out.append((shown(sorted(paths)[0]), msg, None))
    return out


__all__ = [
    "ASSETS_DIR",
    "ASSETS_MANIFEST_FILE",
    "check_assets",
    "image_path_strings",
    "inspect_image",
    "looks_like_image_path",
]
