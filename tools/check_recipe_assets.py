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


_BMP_HEADERS = {
    int(n).to_bytes(4, "little") for n in (12, 40, 52, 56, 64, 108, 124)
}  # the DIB header sizes that follow the 14-byte file header
_FTYP_IMAGE_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"avis"}
_SVG_START = re.compile(
    r"\s*(?:<\?xml[^>]*\?>\s*)?(?:<!--.*?-->\s*|<!DOCTYPE[^>]*>\s*)*<svg[\s>/]",
    re.DOTALL | re.IGNORECASE,
)


def sniff(data: bytes) -> str | None:
    """The image format the first bytes announce, or None.

    Recognised: PNG, JPEG, GIF, WebP, TIFF, BMP, ICO, HEIF/AVIF, JPEG 2000 and SVG (a text file
    that starts, after an optional XML prolog, comments and doctype, with ``<svg``). Nothing else
    is sniffed: an image written as base64 or a ``data:`` URI inside a text file is not found.
    """
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
    if data[:2] == b"BM" and data[6:10] == b"\x00\x00\x00\x00" and data[14:18] in _BMP_HEADERS:
        return "BMP"
    if data[:4] == b"\x00\x00\x01\x00" and 1 <= int.from_bytes(data[4:6], "little") <= 255:
        return "ICO"
    if data[4:8] == b"ftyp" and data[8:12] in _FTYP_IMAGE_BRANDS:
        return "HEIF/AVIF"
    if data.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n"):
        return "JPEG 2000"
    if _SVG_START.match(data[:4096].decode("utf-8", "ignore").lstrip("\ufeff")):
        return "SVG"
    return None


# --- PNG --------------------------------------------------------------------------------

# Colour type -> (channels, valid bit depths). Used for exact chunk lengths.
_PNG_COLOUR = {
    0: (1, {1, 2, 4, 8, 16}),
    2: (3, {8, 16}),
    3: (1, {1, 2, 4, 8}),
    4: (2, {8, 16}),
    6: (4, {8, 16}),
}
# The one text chunk an embedded notebook output may hold: matplotlib's own signature.
_EMBEDDED_SOFTWARE = re.compile(
    rb"Software\x00Matplotlib version[0-9][0-9A-Za-z.+_-]*, https://matplotlib\.org/"
)
# Ancillary chunks the PNG specification allows at most once per file.
_PNG_ONCE = frozenset({"gAMA", "cHRM", "sRGB", "sBIT", "pHYs", "bKGD", "tRNS"})
_ADAM7 = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)

# Backstop for a header that claims absurd dimensions: IDAT is never inflated past the length the
# header implies, and a header implying more than this is refused without inflating anything.
_MAX_INFLATED = 256 * 1024 * 1024


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


def png_raw_length(width: int, height: int, colour: int, depth: int, interlace: int) -> int:
    """The number of bytes a PNG's IDAT must inflate to: one filter byte plus the packed pixels
    of every row, of every Adam7 pass when interlaced."""
    bits = _PNG_COLOUR[colour][0] * depth
    passes = _ADAM7 if interlace else ((0, 0, 1, 1),)
    total = 0
    for x0, y0, dx, dy in passes:
        pass_w, pass_h = -(-(width - x0) // dx), -(-(height - y0) // dy)
        if pass_w > 0 and pass_h > 0:
            total += pass_h * (1 + (pass_w * bits + 7) // 8)
    return total


def _png_chunk_length_ok(name: str, body: bytes, colour: int, depth: int, palette: int) -> bool:
    """Is ``body`` exactly as long as the PNG specification fixes it for this image?"""
    channels = _PNG_COLOUR[colour][0]
    if name == "gAMA":
        return len(body) == 4
    if name == "cHRM":
        return len(body) == 32
    if name == "sRGB":
        return len(body) == 1 and body[0] <= 3
    if name == "pHYs":
        return len(body) == 9 and body[8] <= 1
    if name == "sBIT":
        return len(body) == (3 if colour == 3 else channels) and all(
            1 <= b <= (8 if colour == 3 else depth) for b in body
        )
    if name == "bKGD":
        return len(body) == {0: 2, 4: 2, 2: 6, 6: 6, 3: 1}[colour] and (
            colour != 3 or body[0] < palette
        )
    if name == "tRNS":
        if colour == 0:
            return len(body) == 2
        if colour == 2:
            return len(body) == 6
        return colour == 3 and 1 <= len(body) <= palette
    return True


def inspect_png(data: bytes, *, embedded: bool = False) -> tuple[int, int]:
    """(width, height) of a PNG that obeys the contract; raises ImageError otherwise.

    ``embedded`` is for an image inside a notebook output: matplotlib's ``Software`` text chunk
    is also allowed there.
    """
    first = True
    size = (0, 0)
    colour = depth = 0
    palette = 0
    idat = bytearray()
    idat_done = False
    interlace = 0
    seen: set[str] = set()
    software = 0
    for name, body in _png_chunks(data):
        if first:
            if name != "IHDR" or len(body) != 13:
                raise ImageError("png-structure", "first chunk is not a 13-byte IHDR")
            width, height, depth, colour, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if colour not in _PNG_COLOUR or depth not in _PNG_COLOUR[colour][1]:
                raise ImageError("png-structure", f"invalid colour type {colour}/depth {depth}")
            if compression or filtering or interlace > 1 or not width or not height:
                raise ImageError("png-structure", "invalid IHDR fields")
            size = (width, height)
            first = False
            continue
        if name == "IHDR":
            raise ImageError("png-structure", "second IHDR chunk")
        if name == "acTL":
            raise ImageError("png-animated", "animated PNG (acTL chunk); stills only")
        if embedded and name == "tEXt":
            software += 1
            if software > 1 or not _EMBEDDED_SOFTWARE.fullmatch(body):
                raise ImageError(
                    "png-metadata",
                    "a tEXt chunk other than one matplotlib 'Software' line is not allowed",
                )
            continue
        if name not in PNG_ALLOWED_CHUNKS:
            raise ImageError(
                "png-metadata",
                f"chunk {name} is not allowed (text, EXIF, time, profile and private chunks "
                "can carry names, paths or tokens; strip it)",
            )
        if name in _PNG_ONCE:
            if name in seen:
                raise ImageError("png-metadata", f"chunk {name} appears more than once")
            seen.add(name)
        if name == "IDAT":
            if idat_done:
                raise ImageError("png-structure", "IDAT chunks are not consecutive")
            idat += body
            continue
        if idat:
            idat_done = True
        if name == "PLTE":
            if colour != 3:
                raise ImageError(
                    "png-metadata", "PLTE chunk in a PNG that is not palette-based (colour type 3)"
                )
            if palette or idat or not body or len(body) % 3 or len(body) > 3 * 2**depth:
                raise ImageError("png-structure", "invalid or misplaced PLTE chunk")
            palette = len(body) // 3
        elif not _png_chunk_length_ok(name, body, colour, depth, palette):
            raise ImageError("png-metadata", f"chunk {name} has a length the PNG format forbids")
    if not idat:
        raise ImageError("png-structure", "no IDAT chunk")
    if colour == 3 and not palette:
        raise ImageError("png-structure", "palette PNG without a PLTE chunk")
    expected = png_raw_length(size[0], size[1], colour, depth, interlace)
    if expected > _MAX_INFLATED:
        raise ImageError(
            "png-structure",
            f"the image header implies {expected:,} bytes of pixel data; the most inflated is "
            f"{_MAX_INFLATED:,}",
        )
    inflater = zlib.decompressobj()
    try:
        # Stop one byte past the length the header implies: a compressed bomb in a small file
        # cannot make this job allocate more than that, and one extra byte is enough to see
        # that the stream is too long.
        inflated = inflater.decompress(bytes(idat), expected + 1)
    except zlib.error as error:
        raise ImageError("png-structure", f"IDAT is not a valid zlib stream ({error})") from error
    if len(inflated) > expected:
        raise ImageError(
            "png-structure",
            f"IDAT inflates past the {expected:,} bytes the image header implies",
        )
    if not inflater.eof:
        raise ImageError("png-structure", "IDAT zlib stream does not end cleanly")
    if inflater.unused_data:
        raise ImageError(
            "trailing-data", f"{len(inflater.unused_data)} byte(s) after the zlib stream in IDAT"
        )
    if len(inflated) != expected:
        raise ImageError(
            "png-structure",
            f"IDAT inflates to {len(inflated):,} bytes; the image header implies {expected:,}",
        )
    return size


# --- JPEG -------------------------------------------------------------------------------

_JPEG_SOF0 = 0xC0
_JPEG_DHT = 0xC4
_JPEG_DQT = 0xDB
_JPEG_DRI = 0xDD
_JPEG_SOS = 0xDA
_JPEG_APP0 = 0xE0
_SOF_OTHER = set(range(0xC1, 0xD0)) - {0xC4, 0xC8, 0xCC}  # DHT, JPG, DAC are not frame headers


def _jpeg_check_tables(marker: int, body: bytes) -> None:
    """DQT and DHT must be exactly a sequence of whole tables, so no byte is spare."""
    pos = 0
    if marker == _JPEG_DQT:
        while pos < len(body):
            precision = body[pos] >> 4
            if precision > 1 or body[pos] & 0x0F > 3:
                raise ImageError("jpeg-structure", "invalid DQT table header")
            pos += 1 + 64 * (precision + 1)
    else:
        while pos < len(body):
            if pos + 17 > len(body) or body[pos] & 0x0F > 3 or body[pos] >> 4 > 1:
                raise ImageError("jpeg-structure", "invalid DHT table header")
            pos += 17 + sum(body[pos + 1 : pos + 17])
    if pos != len(body) or not body:
        raise ImageError("jpeg-structure", "quantisation/Huffman table has the wrong length")


def inspect_jpeg(data: bytes) -> tuple[int, int]:
    """(width, height) of a baseline JPEG that obeys the contract; raises ImageError.

    An allowlist: SOI, at most one APP0 that is exactly a JFIF header with no thumbnail, DQT,
    DHT, DRI of length 4, one SOF0, SOS, RSTn and EOI. Any other marker is refused.
    """
    if not data.startswith(b"\xff\xd8"):
        raise ImageError("jpeg-structure", "missing SOI marker")
    pos = 2
    size: tuple[int, int] | None = None
    saw_app0 = saw_scan = False
    while True:
        if pos >= len(data) or data[pos] != 0xFF:
            raise ImageError("jpeg-structure", "expected a marker; truncated or corrupt")
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            raise ImageError("jpeg-structure", "truncated before EOI")
        marker = data[pos]
        pos += 1
        if marker == 0xD9:  # EOI
            if size is None or not saw_scan:
                raise ImageError("jpeg-structure", "no frame header and scan before EOI")
            if pos != len(data):
                raise ImageError("trailing-data", f"{len(data) - pos} byte(s) after EOI")
            return size
        if 0xD0 <= marker <= 0xD7:
            continue  # RSTn: no length
        if 0xE1 <= marker <= 0xEF:
            raise ImageError(
                "jpeg-metadata",
                f"APP{marker - 0xE0} segment (EXIF, XMP, ICC, IPTC, Adobe or vendor data) is not "
                "allowed; strip it",
            )
        if marker == 0xFE:
            raise ImageError("jpeg-metadata", "COM (comment) segment is not allowed; strip it")
        if marker in _SOF_OTHER:
            raise ImageError(
                "jpeg-not-baseline",
                f"SOF marker 0xFF{marker:02X} (progressive, lossless, extended or arithmetic "
                "coding); save a baseline JPEG",
            )
        if marker not in (_JPEG_APP0, _JPEG_SOF0, _JPEG_DHT, _JPEG_DQT, _JPEG_DRI, _JPEG_SOS):
            raise ImageError(
                "jpeg-structure",
                f"marker 0xFF{marker:02X} is not one a baseline JPEG fixture may contain",
            )
        if pos + 2 > len(data):
            raise ImageError("jpeg-structure", "truncated segment header")
        (length,) = struct.unpack(">H", data[pos : pos + 2])
        if length < 2 or pos + length > len(data):
            raise ImageError("jpeg-structure", f"segment 0xFF{marker:02X} runs past the file")
        body = data[pos + 2 : pos + length]
        if marker == _JPEG_APP0:
            if saw_app0 or size is not None:
                raise ImageError("jpeg-metadata", "second or late APP0 segment is not allowed")
            saw_app0 = True
            if len(body) != 14 or not body.startswith(b"JFIF\x00") or body[12] or body[13]:
                raise ImageError(
                    "jpeg-metadata",
                    "APP0 must be a plain 16-byte JFIF header with no thumbnail and no extra data",
                )
        elif marker == _JPEG_SOF0:
            if size is not None:
                raise ImageError("jpeg-structure", "more than one frame header")
            if len(body) < 6 or body[0] != 8 or body[5] not in (1, 3):
                raise ImageError(
                    "jpeg-structure", "frame header must be 8-bit with 1 or 3 components"
                )
            if len(body) != 6 + 3 * body[5]:
                raise ImageError("jpeg-structure", "frame header has the wrong length")
            height, width = struct.unpack(">HH", body[1:5])
            size = (width, height)
        elif marker == _JPEG_DRI:
            if length != 4:
                raise ImageError("jpeg-structure", "DRI segment must be exactly 4 bytes long")
        elif marker == _JPEG_SOS:
            if size is None or not body or length != 6 + 2 * body[0]:
                raise ImageError("jpeg-structure", "invalid scan header")
            saw_scan = True
        else:
            _jpeg_check_tables(marker, body)
        pos += length
        if marker == _JPEG_SOS:  # entropy-coded data runs to the next real marker
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


def inspect_embedded(mime: str, data: bytes) -> list[Finding]:
    """The metadata rules for an image embedded in a notebook (an output), as findings.

    Size and pixel limits do not apply (a figure may be any size; the notebook has its own
    output cap), only structure and metadata.
    """
    try:
        if mime == "image/png":
            inspect_png(data, embedded=True)
        elif mime == "image/jpeg":
            inspect_jpeg(data)
        else:
            return [Finding("", "format-not-allowed", f"{mime} is not a PNG or JPEG")]
    except ImageError as error:
        return [Finding("", error.rule, error.message)]
    return []


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
                f"{len(data):,} bytes; the per-file cap is {MAX_FILE_BYTES:,} (1 MiB). "
                "Photographic or noisy content is far smaller as a baseline JPEG; "
                "flat synthetic content is small as a PNG",
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
