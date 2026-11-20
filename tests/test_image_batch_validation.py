"""Batch rejection must cover retained bytes and the original generator boundary."""

import hashlib
import io
import runpy
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from jev_cookbook import synthetic_images as si


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def recipe_at(root):
    recipe = root / "recipe"
    (recipe / "assets").mkdir(parents=True)
    (recipe / "assets-manifest.json").write_text("[]\n")
    (recipe / "assets" / "untouched.png").write_bytes(si.login_screen().png())
    return recipe


MALFORMED_PNGS = [
    "trailing-idat",
    "duplicate-ihdr",
    "nonempty-iend",
    "duplicate-iend",
    "chunk-after-iend",
    "extra-pixels",
]


def malformed_png(original, violation):
    """Rebuild synthetic PNG chunks with valid CRCs for isolated structure violations."""
    chunks = []
    pos = 8
    while pos < len(original):
        size = struct.unpack_from(">I", original, pos)[0]
        chunks.append((original[pos + 4 : pos + 8], original[pos + 8 : pos + 8 + size]))
        pos += size + 12
    header = chunks[0]
    compressed = b"".join(body for kind, body in chunks if kind == b"IDAT")
    if violation == "trailing-idat":
        compressed += b"SYNTHETIC TRAILING PAYLOAD"
    elif violation == "extra-pixels":
        compressed = zlib.compress(zlib.decompress(compressed) + b"\x00")
    chunks = [header, (b"IDAT", compressed), (b"IEND", b"")]
    if violation == "duplicate-ihdr":
        chunks.insert(1, header)
    elif violation == "nonempty-iend":
        chunks[-1] = (b"IEND", b"x")
    elif violation == "duplicate-iend":
        chunks.append((b"IEND", b""))
    elif violation == "chunk-after-iend":
        chunks.append((b"IDAT", b""))
    return original[:8] + b"".join(
        struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        for kind, body in chunks
    )


@pytest.mark.parametrize("invalid", ["metadata", "oversized"])
@pytest.mark.parametrize("writer", ["batch", "asset", "png"])
def test_retained_png_is_validated_before_any_install(tmp_path, monkeypatch, invalid, writer):
    recipe = recipe_at(tmp_path)
    (recipe / "build_fixtures.py").write_text(
        "from jev_cookbook import synthetic_images as si\ndef draw(): return si.Canvas(700, 600)\n"
    )
    canvas = si.Canvas(700, 600).provenance("build_fixtures.py:draw", {})
    original = canvas.png()
    options = {"compress_level": 0}
    if invalid == "metadata":
        info = PngImagePlugin.PngInfo()
        info.add_text("note", "synthetic metadata")
        options = {"pnginfo": info}
    with Image.open(io.BytesIO(original)) as image:
        image.save(recipe / "assets" / "late.png", **options)
    existing = (recipe / "assets" / "late.png").read_bytes()
    assert si.png_pixels_equal(existing, original)
    if invalid == "oversized":
        assert len(existing) > 1024 * 1024
        with Image.open(io.BytesIO(existing)) as image:
            assert image.info == {}
    monkeypatch.setattr(si, "bytes_are_canonical", lambda: False)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        if writer == "batch":
            si.write_assets(
                [
                    (si.login_screen(), "assets/early.png", "New"),
                    (canvas, "assets/late.png", "Late"),
                ],
                recipe,
            )
        elif writer == "asset":
            si.write_asset(canvas, recipe, "assets/late.png")
        else:
            si.write_png(canvas, recipe / "assets" / "late.png")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("invalid", MALFORMED_PNGS)
@pytest.mark.parametrize("writer", ["batch", "asset", "png"])
def test_retained_malformed_png_is_refused_without_writes(tmp_path, monkeypatch, invalid, writer):
    recipe = recipe_at(tmp_path)
    canvas = si.login_screen()
    original = canvas.png()
    existing = malformed_png(original, invalid)
    checker = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "tools/check_recipe_assets.py")
    )
    assert checker["inspect_png"](original) == (640, 400)
    with pytest.raises(checker["ImageError"]):
        checker["inspect_png"](existing)
    assert si.png_pixels_equal(existing, original)
    late = recipe / "assets" / "late.png"
    late.write_bytes(existing)
    monkeypatch.setattr(si, "bytes_are_canonical", lambda: False)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        if writer == "batch":
            si.write_assets(
                [
                    (si.login_screen(), "assets/early.png", "New"),
                    (canvas, "assets/late.png", "Late"),
                ],
                recipe,
            )
        elif writer == "asset":
            si.write_asset(canvas, recipe, "assets/late.png")
        else:
            si.write_png(canvas, late)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("writer", ["batch", "asset", "png"])
def test_valid_noncanonical_png_keeps_existing_bytes(tmp_path, monkeypatch, writer):
    recipe = recipe_at(tmp_path)
    canvas = si.login_screen()
    late = recipe / "assets" / "late.png"
    with Image.open(io.BytesIO(canvas.png())) as image:
        image.save(late, compress_level=0)
    existing = late.read_bytes()
    assert existing != canvas.png()
    assert si.png_pixels_equal(existing, canvas.png())
    before = snapshot(tmp_path)
    monkeypatch.setattr(si, "bytes_are_canonical", lambda: False)
    if writer == "batch":
        [(status, entry)] = si.write_assets([(canvas, "assets/late.png", "Retained")], recipe)
        assert entry["sha256"] == hashlib.sha256(existing).hexdigest()
    elif writer == "asset":
        status = si.write_asset(canvas, recipe, "assets/late.png")
    else:
        status = si.write_png(canvas, late)
    assert status == "kept-committed-bytes"
    assert snapshot(tmp_path) == before


def uniform_white_png(variant):
    """Three legal encodings of the same 281x280 white pixels, built without Pillow."""
    width, height = 281, 280
    depth, colour, interlace = 8, 2, 0
    if variant == "grayscale1":
        depth, colour = 1, 0
        raw = (b"\x00" + b"\xff" * 35 + b"\x80") * height
    elif variant == "adam7":
        interlace = 1
        raw = b""
        for x, y, dx, dy in [
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        ]:
            columns = (width - x + dx - 1) // dx
            rows = (height - y + dy - 1) // dy
            raw += (b"\x00" + b"\xff" * (3 * columns)) * rows
    else:
        assert variant == "split-idat"
        raw = (b"\x00" + b"\xff" * (3 * width)) * height
    header = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)
    compressed = zlib.compress(raw)
    chunks = [(b"IHDR", header)]
    if variant == "split-idat":
        chunks += [(b"IDAT", compressed[:1]), (b"IDAT", compressed[1:])]
    else:
        chunks.append((b"IDAT", compressed))
    chunks.append((b"IEND", b""))
    return b"\x89PNG\r\n\x1a\n" + b"".join(
        struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        for kind, body in chunks
    )


@pytest.mark.parametrize("variant", ["split-idat", "adam7", "grayscale1"])
@pytest.mark.parametrize("writer", ["batch", "asset", "png"])
def test_legal_png_encodings_keep_exact_existing_bytes(tmp_path, monkeypatch, variant, writer):
    recipe = recipe_at(tmp_path)
    (recipe / "build_fixtures.py").write_text(
        "from jev_cookbook import synthetic_images as si\n"
        "def draw(): return si.Canvas(281, 280, 'white')\n"
    )
    canvas = si.Canvas(281, 280, "white").provenance("build_fixtures.py:draw", {})
    existing = uniform_white_png(variant)
    checker = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "tools/check_recipe_assets.py")
    )
    assert checker["inspect_png"](existing) == (281, 280)
    assert existing != canvas.png()
    assert si.png_pixels_equal(existing, canvas.png())
    late = recipe / "assets" / "late.png"
    late.write_bytes(existing)
    before = snapshot(tmp_path)
    monkeypatch.setattr(si, "bytes_are_canonical", lambda: False)
    if writer == "batch":
        [(status, entry)] = si.write_assets([(canvas, "assets/late.png", "Retained")], recipe)
        assert entry["sha256"] == hashlib.sha256(existing).hexdigest()
    elif writer == "asset":
        status = si.write_asset(canvas, recipe, "assets/late.png")
    else:
        status = si.write_png(canvas, late)
    assert status == "kept-committed-bytes"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("escape", ["relative", "absolute", "symlink"])
@pytest.mark.parametrize("entrypoint", ["batch", "manifest"])
def test_generator_outside_recipe_is_refused_without_writes(tmp_path, escape, entrypoint):
    recipe = recipe_at(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def draw(): return None\n")
    generator = f"{outside}:draw" if escape == "absolute" else "../outside.py:draw"
    if escape == "symlink":
        try:
            (recipe / "linked.py").symlink_to(outside)
        except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
            pytest.skip("this platform cannot create symbolic links")
        generator = "linked.py:draw"
    canvas = si.login_screen().provenance(generator, {})
    (recipe / "assets" / "late.png").write_bytes(canvas.png())
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        if entrypoint == "batch":
            si.write_assets(
                [
                    (si.login_screen(), "assets/early.png", "New"),
                    (canvas, "assets/late.png", "Late"),
                ],
                recipe,
            )
        else:
            si.manifest_entry(recipe, "assets/late.png", generator, {}, "Late")
    assert snapshot(tmp_path) == before


def test_relative_generator_inside_recipe_still_writes(tmp_path):
    recipe = recipe_at(tmp_path)
    script = recipe / "build_fixtures.py"
    script.write_text("from jev_cookbook.synthetic_images import login_screen as draw\n")
    canvas = si.login_screen().provenance("build_fixtures.py:draw", {})
    [(status, entry)] = si.write_assets([(canvas, "assets/custom.png", "Custom")], recipe)
    assert status == "created"
    assert entry["generator"] == "build_fixtures.py:draw"
    assert si.manifest_entry(recipe, "assets/custom.png", entry["generator"], {}, "Custom") == entry
    assert (
        entry["sha256"] == hashlib.sha256((recipe / "assets/custom.png").read_bytes()).hexdigest()
    )
    assert (recipe / "assets/custom.png").read_bytes() == canvas.png()


def _png_with_idat(original, mutate_idat, fix_crc):
    chunks, position = [], 8
    while position < len(original):
        (length,) = struct.unpack(">I", original[position : position + 4])
        kind = original[position + 4 : position + 8]
        body = original[position + 8 : position + 8 + length]
        if kind == b"IDAT":
            body = mutate_idat(body)
        crc = zlib.crc32(kind + body) if fix_crc or kind != b"IDAT" else 0
        chunks.append(struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc))
        position += 12 + length
    return original[:8] + b"".join(chunks)


def test_check_png_refuses_a_bad_crc_and_a_corrupt_zlib_stream():
    original = si.login_screen().png()
    si._check_png(original)
    bad_crc = _png_with_idat(original, lambda body: body, fix_crc=False)
    with pytest.raises(ValueError, match="CRC"):
        si._check_png(bad_crc)
    corrupt = _png_with_idat(original, lambda body: b"\xff\xff" + body[2:], fix_crc=True)
    with pytest.raises(ValueError, match="zlib"):
        si._check_png(corrupt)


def test_write_assets_refuses_two_images_for_one_destination(tmp_path):
    recipe = recipe_at(tmp_path)
    (recipe / "build_fixtures.py").write_text(
        "from jev_cookbook import synthetic_images as si\ndef draw(): return si.login_screen()\n"
    )
    canvas = si.login_screen().provenance("build_fixtures.py:draw", {})
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match="duplicate image destination"):
        si.write_assets(
            [(canvas, "assets/same.png", "One"), (canvas, "assets/same.png", "Two")], recipe
        )
    assert snapshot(tmp_path) == before
