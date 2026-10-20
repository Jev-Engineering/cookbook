#!/usr/bin/env python3
"""Image-file contract for recipes (#307): where an image may live, what it may be, how big.

    python tools/check_recipe_assets.py            # every tracked file under recipes/
    python tools/check_recipe_assets.py --root DIR # a checkout other than this repository

Standard library only (it runs in the Hygiene job, which installs nothing), so it reads PNG and
JPEG structure by hand instead of using Pillow. Exit 0 when clean, 1 with one
``path: [rule] message`` line per problem, 2 when the file list cannot be read.

The contract, in full (the prose version is docs/fixtures.md, section "Image fixtures"):

* Location: an image lives only in ``recipes/<recipe>/assets/`` (optionally in subfolders).
  Any file under ``recipes/`` with an image suffix, or whose first bytes are an image
  signature, anywhere else is ``image-outside-assets``. ``assets/`` holds image files only.
* Format: PNG or baseline JPEG, lowercase ``.png``/``.jpg``/``.jpeg``, and the bytes must be that
  format (a GIF renamed ``.png`` is ``format-mismatch``). Animated PNG, progressive or
  arithmetic-coded JPEG, and bytes after the end of the image are rejected.
* Size: each file at most ``MAX_FILE_BYTES`` (1 MiB); a recipe's ``assets/`` folder at most
  ``MAX_TOTAL_BYTES`` (8 MiB) in all; each side ``MIN_SIDE``..``MAX_SIDE`` pixels and the area
  ``MIN_PIXELS``..``MAX_PIXELS`` (the API's image limits, see below).
* Metadata: a PNG may hold only the chunks in ``PNG_ALLOWED_CHUNKS`` (so no tEXt, iTXt, zTXt,
  eXIf, tIME, iCCP or unknown ancillary chunk); a JPEG may hold only a JFIF ``APP0`` segment
  (so no EXIF, XMP, ICC, IPTC, Adobe or other APPn segment and no comment).
* No symbolic link or submodule under ``recipes/``.

The pixel limits are those of the TypeSafe Images page (https://docs.typesafe.ai/images):
280 to 1568 pixels per side, 78,400 to 2,458,624 pixels in all, 16 MiB per file. They are kept
here as plain constants because this tool must run with no install and so cannot import
``src/jev_cookbook/vision.py``, which enforces the same limits on load. The 16 MiB API limit is
far above the 1 MiB cap here, which is the stricter, repository-local rule.
"""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
import sys
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MIN_SIDE = 280
MAX_SIDE = 1568
MIN_PIXELS = 78_400
MAX_PIXELS = 2_458_624

ALLOWED_SUFFIXES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}
# Suffixes that mark a file as an image for the location rule (any case). A superset of the
# allowed ones; tools/check_recipe_scope.py keeps an identical copy (a test compares them).
IMAGE_SUFFIXES = (
    ".png", ".apng", ".jpg", ".jpeg", ".jpe", ".jfif", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".svg", ".ico", ".heic", ".heif", ".avif", ".jp2",
)  # fmt: skip

# Critical chunks plus the ancillary ones that carry only rendering information. Everything
# else (tEXt, iTXt, zTXt, eXIf, tIME, iCCP, dSIG, private chunks) can carry text or identity.
PNG_ALLOWED_CHUNKS = frozenset(
    {"IHDR", "PLTE", "IDAT", "IEND", "tRNS", "gAMA", "cHRM", "sRGB", "sBIT", "pHYs", "bKGD"}
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_SOF_BASELINE = 0xC0
_SOF_OTHER = set(range(0xC1, 0xD0)) - {0xC4, 0xC8, 0xCC}  # DHT, JPG, DAC are not frame headers


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.rule}] {self.message}"


class ImageError(Exception):
    """A rule violation found while reading one image: (rule, message)."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


def sniff(data: bytes) -> str | None:
    """The image format the first bytes announce, or None."""
    if data.startswith(PNG_SIGNATURE):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WebP"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "TIFF"
    return None


# --- PNG --------------------------------------------------------------------------------


def _png_chunks(data: bytes) -> Iterator[tuple[str, bytes]]:
    pos = len(PNG_SIGNATURE)
    while True:
        if pos + 8 > len(data):
            raise ImageError("png-structure", "truncated before IEND")
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        raw_type = data[pos + 4 : pos + 8]
        if not re.fullmatch(rb"[A-Za-z]{4}", raw_type):
            raise ImageError("png-structure", f"invalid chunk type {raw_type!r}")
        end = pos + 8 + length + 4
        if end > len(data):
            raise ImageError("png-structure", f"chunk {raw_type.decode()} runs past the file")
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[end - 4 : end])
        if zlib.crc32(raw_type + body) != crc:
            raise ImageError("png-structure", f"bad CRC in chunk {raw_type.decode()}")
        yield raw_type.decode(), body
        pos = end
        if raw_type == b"IEND":
            if pos != len(data):
                raise ImageError("trailing-data", f"{len(data) - pos} byte(s) after IEND")
            return


def inspect_png(data: bytes) -> tuple[int, int]:
    """(width, height) of a PNG that obeys the contract; raises ImageError otherwise."""
    first = True
    size = (0, 0)
    saw_idat = False
    for name, body in _png_chunks(data):
        if first:
            if name != "IHDR" or len(body) != 13:
                raise ImageError("png-structure", "first chunk is not a 13-byte IHDR")
            size = struct.unpack(">II", body[:8])
            first = False
        elif name == "IHDR":
            raise ImageError("png-structure", "second IHDR chunk")
        if name == "acTL":
            raise ImageError("png-animated", "animated PNG (acTL chunk); stills only")
        if name not in PNG_ALLOWED_CHUNKS:
            raise ImageError(
                "png-metadata",
                f"chunk {name} is not allowed (text, EXIF, time, profile and private chunks "
                "can carry names, paths or tokens; strip it)",
            )
        saw_idat = saw_idat or name == "IDAT"
    if not saw_idat:
        raise ImageError("png-structure", "no IDAT chunk")
    return size


# --- JPEG -------------------------------------------------------------------------------


def inspect_jpeg(data: bytes) -> tuple[int, int]:
    """(width, height) of a baseline JPEG that obeys the contract; raises ImageError."""
    if not data.startswith(b"\xff\xd8"):
        raise ImageError("jpeg-structure", "missing SOI marker")
    pos = 2
    size: tuple[int, int] | None = None
    while True:
        # A marker is 0xFF, optional 0xFF fill bytes, then the marker code.
        if pos >= len(data) or data[pos] != 0xFF:
            raise ImageError("jpeg-structure", "expected a marker; truncated or corrupt")
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            raise ImageError("jpeg-structure", "truncated before EOI")
        marker = data[pos]
        pos += 1
        if marker == 0xD9:  # EOI
            if size is None:
                raise ImageError("jpeg-structure", "no frame header (SOF0) before EOI")
            if pos != len(data):
                raise ImageError("trailing-data", f"{len(data) - pos} byte(s) after EOI")
            return size
        if marker == 0x01 or 0xD0 <= marker <= 0xD8 or marker == 0x00:
            continue  # TEM, RSTn, SOI: no length (0x00 would be a stuffed byte, tolerated)
        if pos + 2 > len(data):
            raise ImageError("jpeg-structure", "truncated segment header")
        (length,) = struct.unpack(">H", data[pos : pos + 2])
        if length < 2 or pos + length > len(data):
            raise ImageError("jpeg-structure", f"segment 0xFF{marker:02X} runs past the file")
        body = data[pos + 2 : pos + length]
        if marker == _SOF_BASELINE:
            if size is not None:
                raise ImageError("jpeg-structure", "more than one frame header")
            if len(body) < 6:
                raise ImageError("jpeg-structure", "short SOF0 segment")
            height, width = struct.unpack(">HH", body[1:5])
            size = (width, height)
        elif marker in _SOF_OTHER:
            raise ImageError(
                "jpeg-not-baseline",
                f"SOF marker 0xFF{marker:02X} (progressive, lossless, extended or arithmetic "
                "coding); save a baseline JPEG",
            )
        elif marker == 0xE0:
            if not body.startswith(b"JFIF\x00"):
                raise ImageError("jpeg-metadata", "APP0 segment is not a JFIF header")
        elif 0xE1 <= marker <= 0xEF:
            raise ImageError(
                "jpeg-metadata",
                f"APP{marker - 0xE0} segment (EXIF, XMP, ICC, IPTC or vendor data) is not "
                "allowed; strip it",
            )
        elif marker == 0xFE:
            raise ImageError("jpeg-metadata", "COM (comment) segment is not allowed; strip it")
        pos += length
        if marker == 0xDA:  # SOS: entropy-coded data runs to the next real marker
            while True:
                nxt = data.find(b"\xff", pos)
                if nxt == -1 or nxt + 1 >= len(data):
                    raise ImageError("jpeg-structure", "truncated in image data")
                code = data[nxt + 1]
                if code == 0x00 or 0xD0 <= code <= 0xD7:
                    pos = nxt + 2
                    continue
                pos = nxt
                break


# --- one file ----------------------------------------------------------------------------


def check_image(path: str, data: bytes) -> list[Finding]:
    """The per-file rules for a file already known to be inside an assets folder."""
    suffix = Path(path).suffix
    lowered = suffix.lower()
    if lowered not in ALLOWED_SUFFIXES:
        if lowered in IMAGE_SUFFIXES or sniff(data):
            return [
                Finding(
                    path,
                    "format-not-allowed",
                    f"{lowered or 'this'} images are not allowed; use PNG or baseline JPEG",
                )
            ]
        return [Finding(path, "non-image-in-assets", "assets/ holds image files only")]
    if suffix != lowered:
        return [
            Finding(path, "suffix-case", f"suffix {suffix} must be lowercase ({lowered})"),
        ]
    expected = ALLOWED_SUFFIXES[lowered]
    found = sniff(data)
    if found != expected:
        return [
            Finding(
                path,
                "format-mismatch",
                f"suffix says {expected} but the bytes are {found or 'not a recognised image'}",
            )
        ]
    findings: list[Finding] = []
    if len(data) > MAX_FILE_BYTES:
        findings.append(
            Finding(
                path,
                "file-too-large",
                f"{len(data):,} bytes; the per-file cap is {MAX_FILE_BYTES:,} (1 MiB)",
            )
        )
    try:
        width, height = inspect_png(data) if expected == "PNG" else inspect_jpeg(data)
    except ImageError as error:
        return [*findings, Finding(path, error.rule, error.message)]
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        findings.append(
            Finding(
                path,
                "dimensions",
                f"{width} x {height}; each side must be {MIN_SIDE} to {MAX_SIDE} pixels",
            )
        )
    elif not MIN_PIXELS <= width * height <= MAX_PIXELS:
        findings.append(
            Finding(
                path,
                "dimensions",
                f"{width * height:,} pixels; the area must be {MIN_PIXELS:,} to {MAX_PIXELS:,}",
            )
        )
    return findings


# --- a tree ------------------------------------------------------------------------------

SYMLINK_MODE = "120000"
SUBMODULE_MODE = "160000"
_ASSET_PATH = re.compile(r"recipes/(?P<recipe>[^/]+)/assets/.+")


@dataclass(frozen=True)
class Entry:
    """A tracked file: its path, git mode, and bytes (None for a link or submodule)."""

    path: str
    mode: str
    data: bytes | None


def check_entries(entries: Iterable[Entry]) -> list[Finding]:
    findings: list[Finding] = []
    totals: dict[str, int] = {}
    for entry in entries:
        path = entry.path
        if not path.startswith("recipes/"):
            continue
        if entry.mode in (SYMLINK_MODE, SUBMODULE_MODE):
            kind = "symbolic link" if entry.mode == SYMLINK_MODE else "submodule"
            findings.append(Finding(path, "symlink", f"a {kind} is not allowed under recipes/"))
            continue
        data = entry.data or b""
        in_assets = _ASSET_PATH.fullmatch(path)
        if not in_assets:
            suffix = Path(path).suffix.lower()
            kind = sniff(data) or ("image" if suffix in IMAGE_SUFFIXES else None)
            if kind:
                findings.append(
                    Finding(
                        path,
                        "image-outside-assets",
                        f"{kind} image outside recipes/<recipe>/assets/",
                    )
                )
            continue
        recipe = in_assets.group("recipe")
        totals[recipe] = totals.get(recipe, 0) + len(data)
        findings.extend(check_image(path, data))
    for recipe, total in sorted(totals.items()):
        if total > MAX_TOTAL_BYTES:
            findings.append(
                Finding(
                    f"recipes/{recipe}/assets/",
                    "assets-total-too-large",
                    f"{total:,} bytes in all; the folder cap is {MAX_TOTAL_BYTES:,} (8 MiB)",
                )
            )
    return findings


def tracked_entries(root: Path) -> list[Entry]:
    """Every tracked file under ``recipes/`` with its git mode. Links are not followed."""
    out = subprocess.run(
        ["git", "ls-files", "-s", "-z", "--", "recipes"], cwd=root, capture_output=True, check=True
    ).stdout
    entries = []
    for record in out.decode("utf-8", "surrogateescape").split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        mode = meta.split()[0]
        data = None
        if mode not in (SYMLINK_MODE, SUBMODULE_MODE):
            try:
                data = (root / path).read_bytes()
            except OSError:
                continue  # deleted in the working tree: nothing to check
        entries.append(Entry(path, mode, data))
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        entries = tracked_entries(args.root)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"check_recipe_assets: cannot list tracked files: {error}", file=sys.stderr)
        return 2
    findings = check_entries(entries)
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\nImage-asset check failed: {len(findings)} finding(s). The contract is in "
            "docs/fixtures.md (Image fixtures).",
            file=sys.stderr,
        )
        return 1
    print(f"Image-asset check passed: {len(entries)} file(s) under recipes/ checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
