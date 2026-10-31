"""tools/check_recipe_assets.py (#307): every rule of the image-file contract can fail.

Images are built in memory with Pillow, and metadata is spliced in by hand so each test adds
exactly one defect to an otherwise valid file. The contract is in docs/fixtures.md.
"""

from __future__ import annotations

import importlib.util
import io
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tracemalloc
import zlib
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "check_recipe_assets.py"

spec = importlib.util.spec_from_file_location("check_recipe_assets_for_test", TOOL)
assets = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = assets  # a dataclass looks its module up here
spec.loader.exec_module(assets)

A = "recipes/01-demo/assets"


# -- building files -------------------------------------------------------------------------


def png(width=320, height=320, color=(180, 60, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "PNG")
    return buffer.getvalue()


def chunk(kind: bytes, body: bytes = b"") -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png_with(*extra: bytes, width=320, height=320) -> bytes:
    """A valid PNG with extra raw chunks spliced in just before IEND."""
    data = png(width, height)
    iend = data.rindex(b"\x00\x00\x00\x00IEND")
    return data[:iend] + b"".join(extra) + data[iend:]


def jpeg(width=320, height=320, **options) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 200)).save(buffer, "JPEG", **options)
    return buffer.getvalue()


def jpeg_with(segment_marker: int, body: bytes, width=320, height=320) -> bytes:
    """A valid baseline JPEG with one extra segment spliced in right after SOI."""
    data = jpeg(width, height)
    segment = b"\xff" + bytes([segment_marker]) + struct.pack(">H", len(body) + 2) + body
    return data[:2] + segment + data[2:]


def noise_png(seed: int, side=560) -> bytes:
    """An incompressible PNG of about 0.9 MB (under the 1 MiB cap)."""
    raw = random.Random(seed).randbytes(side * side * 3)
    buffer = io.BytesIO()
    Image.frombytes("RGB", (side, side), raw).save(buffer, "PNG", compress_level=0)
    return buffer.getvalue()


def entry(path: str, data: bytes | None, mode: str = "100644"):
    return assets.Entry(path, mode, data)


def findings(*entries):
    return assets.check_entries(entries)


def rules(*entries) -> list[str]:
    return [f.rule for f in findings(*entries)]


def only(path: str, data: bytes) -> list[str]:
    return rules(entry(path, data))


# -- the contract holds for valid files -------------------------------------------------------


def test_valid_png_jpg_and_jpeg_in_assets_pass():
    assert only(f"{A}/a.png", png()) == []
    assert only(f"{A}/b.jpg", jpeg()) == []
    assert only(f"{A}/c.jpeg", jpeg()) == []


def test_subfolders_of_assets_are_allowed():
    assert only(f"{A}/frames/door/open.png", png()) == []


def test_the_pixel_limits_are_inclusive_at_both_ends():
    assert only(f"{A}/min.png", png(280, 280)) == []
    assert only(f"{A}/max.png", png(1568, 1568)) == []
    assert only(f"{A}/tall.png", png(280, 1568)) == []
    assert only(f"{A}/wide.jpg", jpeg(1568, 280)) == []


def test_the_allowed_png_chunks_pass():
    extra = [chunk(b"gAMA", struct.pack(">I", 45455)), chunk(b"pHYs", struct.pack(">IIB", 1, 1, 1))]
    assert only(f"{A}/a.png", png_with(*extra)) == []


def test_a_jfif_header_alone_passes():
    data = jpeg()
    assert data[2:4] == b"\xff\xe0" and data[6:11] == b"JFIF\x00"
    assert only(f"{A}/a.jpg", data) == []


def test_the_repository_as_committed_passes():
    entries = assets.tracked_entries(REPO)
    assert assets.check_entries(entries) == []


# -- location --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "recipes/01-demo/helpers/photo.png",
        "recipes/01-demo/fixtures/photo.png",
        "recipes/01-demo/photo.jpg",
        "recipes/01-demo/tests/photo.jpeg",
        "recipes/01-demo/helpers/assets/photo.png",
        "recipes/01-demo/assetz/photo.png",
        "recipes/photo.png",
        "recipes/_template/photo.png",
        "recipes/01-demo/photo.PNG",
        "recipes/01-demo/photo.gif",
        "recipes/01-demo/diagram.svg",
    ],
)
def test_an_image_outside_assets_is_rejected(path):
    data = png() if "png" in path.lower() else jpeg()
    found = findings(entry(path, data))
    assert [f.rule for f in found] == ["image-outside-assets"]
    assert found[0].path == path
    assert "assets/" in str(found[0]) and path in str(found[0])


def test_an_image_hidden_under_another_name_outside_assets_is_rejected():
    for name, data in {
        "data.bin": png(),
        "notes.txt": jpeg(),
        "x.dat": b"GIF89a" + b"\x00" * 20,
        "y.dat": b"RIFF\x00\x00\x00\x00WEBPVP8 ",
    }.items():
        assert rules(entry(f"recipes/01-demo/helpers/{name}", data)) == ["image-outside-assets"]


def test_non_image_files_outside_assets_are_not_flagged():
    for path in ("README.md", "notebook.ipynb", "helpers.py", "fixtures/inputs.jsonl"):
        assert rules(entry(f"recipes/01-demo/{path}", b"plain text\n")) == []


def test_files_outside_recipes_are_not_this_checkers_business():
    # The repository banner and the docs figures are not recipe assets.
    assert rules(entry("assets/banner.png", png()), entry("docs/assets/x/a.png", png())) == []
    assert rules(entry("assets/anything.gif", b"GIF89a")) == []


def test_assets_holds_image_files_only():
    assert only(f"{A}/notes.txt", b"hello\n") == ["non-image-in-assets"]
    assert only(f"{A}/data.json", b"{}") == ["non-image-in-assets"]
    assert only(f"{A}/.gitkeep", b"") == ["non-image-in-assets"]


# -- format ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a.gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"),
        ("a.webp", b"RIFF\x04\x00\x00\x00WEBP"),
        ("a.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
        ("a.bmp", b"BM" + b"\x00" * 30),
        ("a.tiff", b"II*\x00" + b"\x00" * 30),
        ("a.avif", b"\x00" * 30),
    ],
)
def test_a_disallowed_format_is_rejected(name, data):
    found = findings(entry(f"{A}/{name}", data))
    assert [f.rule for f in found] == ["format-not-allowed"]
    assert name in str(found[0])


def test_a_gif_renamed_png_is_rejected():
    gif = io.BytesIO()
    Image.new("P", (320, 320)).save(gif, "GIF")
    found = findings(entry(f"{A}/photo.png", gif.getvalue()))
    assert [f.rule for f in found] == ["format-mismatch"]
    assert "GIF" in found[0].message and "photo.png" in str(found[0])


def test_a_webp_renamed_jpg_is_rejected():
    webp = io.BytesIO()
    Image.new("RGB", (320, 320)).save(webp, "WEBP")
    assert only(f"{A}/photo.jpg", webp.getvalue()) == ["format-mismatch"]


def test_a_jpeg_renamed_png_and_a_png_renamed_jpg_are_rejected():
    assert only(f"{A}/photo.png", jpeg()) == ["format-mismatch"]
    assert only(f"{A}/photo.jpg", png()) == ["format-mismatch"]
    assert only(f"{A}/photo.jpeg", png()) == ["format-mismatch"]


def test_arbitrary_bytes_with_an_image_suffix_are_rejected():
    assert only(f"{A}/photo.png", b"not an image at all") == ["format-mismatch"]
    assert only(f"{A}/photo.jpg", b"") == ["format-mismatch"]


@pytest.mark.parametrize("suffix", [".PNG", ".Png", ".JPG", ".JPEG", ".Jpeg"])
def test_a_suffix_must_be_lowercase(suffix):
    data = png() if suffix.lower() == ".png" else jpeg()
    found = findings(entry(f"{A}/photo{suffix}", data))
    assert [f.rule for f in found] == ["suffix-case"]


def test_a_file_with_no_suffix_in_assets_is_rejected():
    assert only(f"{A}/photo", png()) == ["format-not-allowed"]  # PNG bytes, but no suffix
    assert only(f"{A}/photo", b"text") == ["non-image-in-assets"]


def test_a_progressive_jpeg_is_rejected():
    assert only(f"{A}/a.jpg", jpeg(progressive=True)) == ["jpeg-not-baseline"]


def test_an_animated_png_is_rejected():
    actl = chunk(b"acTL", struct.pack(">II", 2, 0))
    data = png()
    idat = data.index(b"IDAT") - 4  # the length field precedes the chunk type
    animated = data[:idat] + actl + data[idat:]
    assert only(f"{A}/a.png", animated) == ["png-animated"]


def test_bytes_after_the_end_of_the_image_are_rejected():
    assert only(f"{A}/a.png", png() + b"secret=hidden") == ["trailing-data"]
    assert only(f"{A}/a.jpg", jpeg() + b"secret=hidden") == ["trailing-data"]


def test_truncated_and_corrupt_files_are_rejected():
    data = png()
    assert only(f"{A}/a.png", data[: len(data) // 2]) == ["png-structure"]
    assert only(f"{A}/c.png", data[:8]) == ["png-structure"]
    j = jpeg()
    assert only(f"{A}/a.jpg", j[: len(j) // 2]) == ["jpeg-structure"]
    assert only(f"{A}/b.jpg", b"\xff\xd8\xff") == ["jpeg-structure"]


def test_a_png_without_a_leading_ihdr_is_rejected():
    data = png()
    swapped = data[:8] + chunk(b"gAMA", b"\x00\x00\xb1\x8f") + data[8:]
    assert only(f"{A}/a.png", swapped) == ["png-structure"]


# -- size -----------------------------------------------------------------------------------


def test_a_file_over_the_per_file_cap_is_rejected():
    big = Image.frombytes("RGB", (600, 600), random.Random(1).randbytes(600 * 600 * 3))
    buffer = io.BytesIO()
    big.save(buffer, "PNG", compress_level=0)
    data = buffer.getvalue()
    assert assets.MAX_FILE_BYTES < len(data)
    found = findings(entry(f"{A}/big.png", data))
    assert [f.rule for f in found] == ["file-too-large"]
    assert "big.png" in str(found[0]) and "1 MiB" in found[0].message


def test_a_file_just_under_the_per_file_cap_passes():
    data = noise_png(2)
    assert 0.8 * assets.MAX_FILE_BYTES < len(data) <= assets.MAX_FILE_BYTES
    assert only(f"{A}/ok.png", data) == []


def test_the_per_file_cap_is_inclusive(monkeypatch):
    data = noise_png(3)
    monkeypatch.setattr(assets, "MAX_FILE_BYTES", len(data))
    assert only(f"{A}/ok.png", data) == []
    monkeypatch.setattr(assets, "MAX_FILE_BYTES", len(data) - 1)
    assert only(f"{A}/ok.png", data) == ["file-too-large"]


def test_a_recipe_over_the_total_cap_is_rejected():
    files = [entry(f"{A}/n{i}.png", noise_png(10 + i)) for i in range(9)]
    total = sum(len(f.data) for f in files)
    assert total > assets.MAX_TOTAL_BYTES
    found = findings(*files)
    assert [f.rule for f in found] == ["assets-total-too-large"]
    assert found[0].path == f"{A}/" and "8 MiB" in found[0].message


def test_the_total_cap_counts_each_recipe_separately():
    files = [entry(f"{A}/n{i}.png", noise_png(10 + i)) for i in range(8)]
    other = [entry(f"recipes/02-other/assets/n{i}.png", f.data) for i, f in enumerate(files)]
    assert sum(len(f.data) for f in files) <= assets.MAX_TOTAL_BYTES
    assert findings(*files, *other) == []


@pytest.mark.parametrize(
    ("width", "height"),
    [(279, 320), (320, 279), (100, 100), (1569, 320), (320, 1569), (1, 1)],
)
def test_pixel_dimensions_outside_the_api_limits_are_rejected(width, height):
    found = findings(entry(f"{A}/a.png", png(width, height)))
    assert [f.rule for f in found] == ["dimensions"]
    assert f"{width} x {height}" in found[0].message
    found = findings(entry(f"{A}/a.jpg", jpeg(width, height)))
    assert [f.rule for f in found] == ["dimensions"]


def test_the_limits_are_the_documented_ones():
    # https://docs.typesafe.ai/images: 280 to 1568 per side, 78,400 to 2,458,624 pixels.
    assert (assets.MIN_SIDE, assets.MAX_SIDE) == (280, 1568)
    assert assets.MIN_PIXELS == 280 * 280 and assets.MAX_PIXELS == 1568 * 1568
    assert (assets.MAX_FILE_BYTES, assets.MAX_TOTAL_BYTES) == (2**20, 8 * 2**20)


# -- metadata ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        (b"tEXt", b"Author\x00Jane Doe"),
        (b"iTXt", b"Comment\x00\x00\x00\x00\x00C:\\Users\\jane\\pic.png"),
        (b"zTXt", b"Software\x00\x00" + zlib.compress(b"token=abc")),
        (b"eXIf", b"MM\x00*\x00\x00\x00\x08\x00\x00"),
        (b"tIME", struct.pack(">HBBBBB", 2026, 10, 20, 12, 0, 0)),
        (b"iCCP", b"profile\x00\x00" + zlib.compress(b"x" * 20)),
        (b"prVt", b"private data"),
        (b"dSIG", b"signature"),
    ],
)
def test_a_png_metadata_chunk_is_rejected_and_named(kind, body):
    found = findings(entry(f"{A}/a.png", png_with(chunk(kind, body))))
    assert [f.rule for f in found] == ["png-metadata"]
    assert kind.decode() in found[0].message and "a.png" in str(found[0])


def test_pillow_written_text_and_exif_are_caught_end_to_end():
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Jane Doe")
    buffer = io.BytesIO()
    Image.new("RGB", (320, 320)).save(buffer, "PNG", pnginfo=info)
    assert only(f"{A}/a.png", buffer.getvalue()) == ["png-metadata"]
    exif = Image.Exif()
    exif[0x013B] = "Jane Doe"  # Artist
    buffer = io.BytesIO()
    Image.new("RGB", (320, 320)).save(buffer, "JPEG", exif=exif)
    assert only(f"{A}/a.jpg", buffer.getvalue()) == ["jpeg-metadata"]
    buffer = io.BytesIO()
    Image.new("RGB", (320, 320)).save(buffer, "PNG", exif=exif)
    assert only(f"{A}/b.png", buffer.getvalue()) == ["png-metadata"]


@pytest.mark.parametrize(
    ("marker", "body", "label"),
    [
        (0xE1, b"Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00", "APP1"),
        (0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta/>", "APP1"),
        (0xE2, b"ICC_PROFILE\x00\x01\x01" + b"\x00" * 20, "APP2"),
        (0xED, b"Photoshop 3.0\x008BIM", "APP13"),
        (0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x00", "APP14"),
        (0xFE, b"made by jane on C:\\Users\\jane", "COM"),
    ],
)
def test_a_jpeg_metadata_segment_is_rejected_and_named(marker, body, label):
    found = findings(entry(f"{A}/a.jpg", jpeg_with(marker, body)))
    assert [f.rule for f in found] == ["jpeg-metadata"]
    assert label in found[0].message and "a.jpg" in str(found[0])


def test_a_non_jfif_app0_segment_is_rejected():
    data = jpeg()
    # Replace the JFIF identifier of the existing APP0 with another one.
    assert data[6:11] == b"JFIF\x00"
    other = data[:6] + b"AVI1\x00" + data[11:]
    assert only(f"{A}/a.jpg", other) == ["jpeg-metadata"]


# -- links -------------------------------------------------------------------------------------


def test_a_symlink_is_rejected_anywhere_under_recipes():
    for path in (f"{A}/link.png", "recipes/01-demo/helpers/link", "recipes/01-demo/link.txt"):
        found = findings(entry(path, None, mode="120000"))
        assert [f.rule for f in found] == ["symlink"]
        assert path in str(found[0])


def test_a_submodule_is_rejected():
    assert rules(entry("recipes/01-demo/assets/vendored", None, mode="160000")) == ["symlink"]


def test_a_symlink_outside_recipes_is_not_checked_here():
    assert rules(entry("docs/link", None, mode="120000")) == []


# -- the command line, against a real repository ---------------------------------------------------


def git(path: Path, *args: str, data: bytes | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args], input=data, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout.decode().strip()


def make_repo(path: Path, files: dict[str, bytes], links: dict[str, str] | None = None) -> Path:
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    for name, data in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        git(path, "add", name)
    for name, target_text in (links or {}).items():
        # A symlink cannot always be created on disk (Windows), so it goes straight to the index.
        sha = git(path, "hash-object", "-w", "--stdin", data=target_text.encode())
        git(path, "update-index", "--add", "--cacheinfo", f"120000,{sha},{name}")
    return path


def run_cli(root: Path):
    # git must not climb out of a temporary directory into some enclosing repository.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(root.parent)}
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root)], capture_output=True, text=True, env=env
    )


def test_cli_passes_a_clean_repository(tmp_path):
    root = make_repo(tmp_path / "r", {f"{A}/a.png": png(), "recipes/01-demo/README.md": b"hi\n"})
    result = run_cli(root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout


def test_cli_names_the_file_and_the_rule_for_each_problem(tmp_path):
    root = make_repo(
        tmp_path / "r",
        {
            f"{A}/ok.png": png(),
            f"{A}/tagged.png": png_with(chunk(b"tEXt", b"Author\x00Jane")),
            f"{A}/small.jpg": jpeg(100, 100),
            "recipes/01-demo/helpers/stray.png": png(),
        },
    )
    result = run_cli(root)
    assert result.returncode == 1
    assert f"{A}/tagged.png: [png-metadata]" in result.stdout
    assert f"{A}/small.jpg: [dimensions]" in result.stdout
    assert "recipes/01-demo/helpers/stray.png: [image-outside-assets]" in result.stdout
    assert "ok.png" not in result.stdout


def test_cli_rejects_a_symlink_in_the_index(tmp_path):
    root = make_repo(tmp_path / "r", {f"{A}/ok.png": png()}, links={f"{A}/link.png": "ok.png"})
    result = run_cli(root)
    assert result.returncode == 1
    assert f"{A}/link.png: [symlink]" in result.stdout


def test_cli_judges_a_link_by_its_mode_and_never_reads_what_it_points_to(tmp_path):
    # The index says "symbolic link" while the working tree holds a perfectly valid image at the
    # path (as it would after a checkout that followed the link): the mode alone is the finding.
    root = make_repo(tmp_path / "r", {f"{A}/link.png": png()})
    sha = git(root, "hash-object", "-w", "--stdin", data=b"../elsewhere.png")
    git(root, "update-index", "--cacheinfo", f"120000,{sha},{A}/link.png")
    result = run_cli(root)
    assert result.returncode == 1
    assert result.stdout.strip().splitlines() == [
        f"{A}/link.png: [symlink] a symbolic link is not allowed under recipes/"
    ]


def test_cli_reports_a_non_repository_as_an_error(tmp_path):
    result = run_cli(tmp_path)
    assert result.returncode == 2


def test_cli_passes_the_repository_itself():
    result = run_cli(REPO)
    assert result.returncode == 0, result.stdout


# -- the places the contract is wired in ----------------------------------------------------------


def test_gitattributes_marks_every_image_suffix_binary():
    lines = (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for suffix in ("png", "jpg", "jpeg"):
        assert f"*.{suffix} binary" in lines
    if shutil.which("git"):
        out = git(REPO, "check-attr", "binary", "--", "recipes/x/assets/a.jpeg")
        assert out.endswith("binary: set"), out


def test_hygiene_workflow_runs_the_asset_checker():
    text = (REPO / ".github" / "workflows" / "hygiene.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s+run: python tools/check_recipe_assets\.py$", text, re.MULTILINE)
    # The existing hygiene step and the job name (part of the required-check contract) remain.
    assert "run: python tools/check_hygiene.py" in text
    assert "name: Hygiene (secrets and notebook outputs)" in text


def test_the_documented_numbers_match_the_constants():
    text = (REPO / "docs" / "fixtures.md").read_text(encoding="utf-8")
    section = text[text.index("### Image fixtures") :]
    assert "1 MiB (1,048,576 bytes)" in section and assets.MAX_FILE_BYTES == 1_048_576
    assert "8 MiB" in section and assets.MAX_TOTAL_BYTES == 8 * 1024 * 1024
    assert "280 to 1568" in section and "78,400 to 2,458,624" in section
    for chunk_name in sorted(assets.PNG_ALLOWED_CHUNKS):
        assert f"`{chunk_name}`" in section, chunk_name
    template = (REPO / "docs" / "recipe-template.md").read_text(encoding="utf-8")
    row = next(line for line in template.splitlines() if line.startswith("| `assets/`"))
    assert "vision.md" in row and "fixtures.md#image-fixtures" in row


def test_the_documented_clean_copy_recipe_produces_compliant_files(tmp_path, monkeypatch):
    """The snippet in docs/fixtures.md drops the text and ICC profile that a plain re-save keeps."""
    from PIL import PngImagePlugin

    text = (REPO / "docs" / "fixtures.md").read_text(encoding="utf-8")
    block = re.search(r"```python\n(from PIL import Image\n.*?)```", text, re.DOTALL).group(1)
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Jane Doe")
    dirty = io.BytesIO()
    Image.new("RGB", (320, 320), (9, 9, 9)).save(dirty, "PNG", pnginfo=info, icc_profile=b"x" * 80)
    assert only(f"{A}/source.png", dirty.getvalue()) == ["png-metadata"]
    # A plain re-save keeps the profile: this is why the documented recipe copies the pixels.
    resaved = io.BytesIO()
    Image.open(io.BytesIO(dirty.getvalue())).save(resaved, "PNG")
    assert only(f"{A}/source.png", resaved.getvalue()) == ["png-metadata"]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "source.png").write_bytes(dirty.getvalue())
    (tmp_path / "recipes" / "NN-slug" / "assets").mkdir(parents=True)
    for suffix in ("png", "jpg"):
        exec(compile(block.replace("example.png", f"example.{suffix}"), "fixtures.md", "exec"), {})
        out = tmp_path / "recipes" / "NN-slug" / "assets" / f"example.{suffix}"
        assert only(f"{A}/example.{suffix}", out.read_bytes()) == [], suffix


# -- smuggling inside parts the checker allows (#307 fix round 1) --------------------------------

TEXT = b"Author: Jane Doe; C:\\Users\\jane\\patient_scan.jpg; GPS 51.5,-0.12; sk-ant-XXXX"


def png_chunks_of(data: bytes) -> list[tuple[bytes, bytes]]:
    out, pos = [], 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        out.append((data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return out


def png_rebuilt(chunks: list[tuple[bytes, bytes]]) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunk(kind, body) for kind, body in chunks)


def png_edit(data: bytes, fn) -> bytes:
    """Rebuild a PNG after ``fn`` changed its (type, body) chunk list."""
    chunks = png_chunks_of(data)
    fn(chunks)
    return png_rebuilt(chunks)


def ihdr(width, height, depth, colour) -> bytes:
    return struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0)


def raw_png(colour: int, depth: int, extra=(), width=320, height=320, palette=b"") -> bytes:
    """A hand-built PNG of any colour type: IHDR, extra chunks, optional PLTE, IDAT, IEND."""
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    row = 1 + (width * channels * depth + 7) // 8
    chunks = [(b"IHDR", ihdr(width, height, depth, colour))]
    if palette:
        chunks.append((b"PLTE", palette))
    chunks.extend(extra)
    chunks.append((b"IDAT", zlib.compress(bytes(row * height))))
    chunks.append((b"IEND", b""))
    return png_rebuilt(chunks)


def jpeg_segments(data: bytes) -> list[tuple[int, bytes]]:
    """(marker, body) for every segment up to and including SOS; the rest is returned as marker -1."""
    out, pos = [], 2
    while True:
        marker = data[pos + 1]
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        out.append((marker, data[pos + 4 : pos + 2 + length]))
        pos += 2 + length
        if marker == 0xDA:
            out.append((-1, data[pos:]))
            return out


def jpeg_rebuilt(segments: list[tuple[int, bytes]]) -> bytes:
    out = b"\xff\xd8"
    for marker, body in segments:
        if marker == -1:
            out += body
        else:
            out += b"\xff" + bytes([marker]) + struct.pack(">H", len(body) + 2) + body
    return out


def jpeg_edit(fn, **options) -> bytes:
    segments = jpeg_segments(jpeg(**options))
    fn(segments)
    return jpeg_rebuilt(segments)


def test_the_helpers_rebuild_valid_files():
    assert only(f"{A}/a.png", png_rebuilt(png_chunks_of(png()))) == []
    assert only(f"{A}/a.jpg", jpeg_rebuilt(jpeg_segments(jpeg()))) == []
    assert only(f"{A}/b.png", raw_png(2, 8)) == []


@pytest.mark.parametrize(
    ("name", "edit", "rule"),
    [
        (
            "text after the JFIF fields",
            lambda s: s.__setitem__(0, (0xE0, s[0][1] + TEXT)),
            "jpeg-metadata",
        ),
        ("a second JFIF APP0", lambda s: s.insert(1, (0xE0, b"JFIF\x00" + TEXT)), "jpeg-metadata"),
        (
            "a JFIF thumbnail",
            lambda s: s.__setitem__(0, (0xE0, s[0][1][:12] + b"\x02\x02" + bytes(12))),
            "jpeg-metadata",
        ),
        ("a DNL segment", lambda s: s.insert(1, (0xDC, TEXT)), "jpeg-structure"),
        ("a JPG0 segment", lambda s: s.insert(1, (0xF0, TEXT)), "jpeg-structure"),
        ("a reserved 0xFF02 segment", lambda s: s.insert(1, (0x02, TEXT)), "jpeg-structure"),
        ("an oversized DRI", lambda s: s.insert(1, (0xDD, b"\x00\x10" + TEXT)), "jpeg-structure"),
        ("a DHP segment", lambda s: s.insert(1, (0xDE, TEXT)), "jpeg-structure"),
        ("an EXP segment", lambda s: s.insert(1, (0xDF, TEXT)), "jpeg-structure"),
        (
            "an extra DQT byte run",
            lambda s: s.insert(1, (0xDB, b"\x00" + bytes(64) + TEXT)),
            "jpeg-structure",
        ),
        (
            "an extra DHT byte run",
            lambda s: s.insert(1, (0xC4, b"\x00" + bytes(16) + TEXT)),
            "jpeg-structure",
        ),
        ("an empty DQT", lambda s: s.insert(1, (0xDB, b"")), "jpeg-structure"),
        (
            "a second frame header",
            lambda s: s.insert(1, (0xC0, next(b for m, b in s if m == 0xC0))),
            "jpeg-structure",
        ),
    ],
)
def test_jpeg_smuggling_carriers_are_rejected(name, edit, rule):
    data = jpeg_edit(edit)
    found = findings(entry(f"{A}/a.jpg", data))
    assert [f.rule for f in found] == [rule], name
    assert "a.jpg" in str(found[0])


def test_jpeg_frame_header_must_be_8_bit_with_one_or_three_components():
    def set_precision(segments):
        i = next(i for i, (m, _) in enumerate(segments) if m == 0xC0)
        segments[i] = (0xC0, b"\x0c" + segments[i][1][1:])

    assert only(f"{A}/a.jpg", jpeg_edit(set_precision)) == ["jpeg-structure"]

    def four_components(segments):
        i = next(i for i, (m, _) in enumerate(segments) if m == 0xC0)
        body = segments[i][1]
        segments[i] = (0xC0, body[:5] + b"\x04" + body[6:] + bytes(3))

    assert only(f"{A}/b.jpg", jpeg_edit(four_components)) == ["jpeg-structure"]


def test_jpeg_scan_header_length_must_match_its_component_count():
    def pad_scan(segments):
        i = next(i for i, (m, _) in enumerate(segments) if m == 0xDA)
        segments[i] = (0xDA, segments[i][1] + TEXT)

    assert only(f"{A}/a.jpg", jpeg_edit(pad_scan)) == ["jpeg-structure"]


def test_a_grayscale_jpeg_and_restart_markers_are_accepted():
    buffer = io.BytesIO()
    Image.new("L", (320, 320), 90).save(buffer, "JPEG")
    assert only(f"{A}/gray.jpg", buffer.getvalue()) == []
    buffer = io.BytesIO()
    Image.effect_noise((320, 320), 40).save(buffer, "JPEG", restart_marker_blocks=2)
    assert b"\xff\xdd" in buffer.getvalue()
    assert only(f"{A}/restart.jpg", buffer.getvalue()) == []


PHYS = struct.pack(">IIB", 1, 1, 1)


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        (b"gAMA", struct.pack(">I", 45455) + TEXT),
        (b"cHRM", bytes(32) + TEXT),
        (b"cHRM", bytes(8)),
        (b"sRGB", b"\x00" + TEXT),
        (b"sRGB", b"\x09"),
        (b"pHYs", PHYS + TEXT),
        (b"pHYs", PHYS[:8] + b"\x05"),
        (b"sBIT", b"\x08\x08\x08" + TEXT),
        (b"sBIT", b"\x09\x08\x08"),
        (b"bKGD", b"\x00" * 6 + TEXT),
        (b"bKGD", b"\x00" * 2),
        (b"tRNS", b"\x00" * 6 + TEXT),
        (b"tRNS", b"\x00" * 2),
    ],
)
def test_allowed_png_chunks_must_have_their_exact_length(kind, body):
    data = raw_png(2, 8, extra=[(kind, body)])
    found = findings(entry(f"{A}/a.png", data))
    assert [f.rule for f in found] == ["png-metadata"], (kind, body)
    assert kind.decode() in found[0].message


def test_each_allowed_png_chunk_passes_at_its_exact_length():
    extra = [
        (b"gAMA", struct.pack(">I", 45455)),
        (b"cHRM", bytes(32)),
        (b"sRGB", b"\x00"),
        (b"pHYs", PHYS),
        (b"sBIT", b"\x08\x08\x08"),
        (b"bKGD", bytes(6)),
        (b"tRNS", bytes(6)),
    ]
    assert only(f"{A}/a.png", raw_png(2, 8, extra=extra)) == []
    assert only(f"{A}/b.png", raw_png(0, 8, extra=[(b"bKGD", bytes(2)), (b"tRNS", bytes(2))])) == []
    palette = bytes([10, 20, 30, 200, 100, 50])
    assert (
        only(
            f"{A}/c.png",
            raw_png(3, 8, extra=[(b"bKGD", b"\x01"), (b"tRNS", b"\xff\x80")], palette=palette),
        )
        == []
    )


def test_a_transparency_chunk_is_not_allowed_on_an_image_with_an_alpha_channel():
    assert only(f"{A}/a.png", raw_png(6, 8, extra=[(b"tRNS", bytes(6))])) == ["png-metadata"]
    assert only(f"{A}/b.png", raw_png(6, 8)) == []


def test_a_palette_chunk_in_a_truecolour_png_is_rejected():
    assert only(f"{A}/a.png", raw_png(2, 8, palette=TEXT + b"\x00" * (-len(TEXT) % 3))) == [
        "png-metadata"
    ]
    assert only(f"{A}/b.png", raw_png(6, 8, palette=bytes(30))) == ["png-metadata"]


def test_a_palette_png_needs_a_valid_palette():
    assert only(f"{A}/a.png", raw_png(3, 8, palette=bytes(30))) == []
    assert only(f"{A}/b.png", raw_png(3, 8)) == ["png-structure"]
    assert only(f"{A}/c.png", raw_png(3, 2, palette=bytes(15))) == ["png-structure"]  # 5 > 4
    assert only(f"{A}/d.png", raw_png(3, 8, palette=bytes(31))) == ["png-structure"]  # not x3


def test_idat_must_be_one_clean_zlib_stream():
    base = png()

    def append(data):
        def fn(chunks):
            i = next(i for i, (k, _) in enumerate(chunks) if k == b"IDAT")
            chunks[i] = (b"IDAT", chunks[i][1] + data)

        return png_edit(base, fn)

    found = findings(entry(f"{A}/a.png", append(TEXT)))
    assert [f.rule for f in found] == ["trailing-data"] and "zlib" in found[0].message

    def truncate(chunks):
        i = next(i for i, (k, _) in enumerate(chunks) if k == b"IDAT")
        chunks[i] = (b"IDAT", chunks[i][1][:-6])

    assert only(f"{A}/b.png", png_edit(base, truncate)) == ["png-structure"]

    def garbage(chunks):
        i = next(i for i, (k, _) in enumerate(chunks) if k == b"IDAT")
        chunks[i] = (b"IDAT", TEXT)

    assert only(f"{A}/c.png", png_edit(base, garbage)) == ["png-structure"]


def png_with_idat(data: bytes, body: bytes) -> bytes:
    def replace(chunks):
        i = next(i for i, (k, _) in enumerate(chunks) if k == b"IDAT")
        chunks[i] = (b"IDAT", body)

    return png_edit(data, replace)


def idat_rows(width=320, height=320) -> bytes:
    return bytes(assets.png_raw_length(width, height, 2, 8, 0))


def test_a_complete_deflate_stream_must_still_end_with_its_final_block_and_checksum():
    # Both streams inflate to exactly the rows the header implies with no byte left over, so the
    # only thing wrong with them is that the zlib stream does not end: the length check cannot
    # catch them. Only the "ends cleanly" check does.
    rows = idat_rows()
    no_checksum = zlib.compress(rows)[:-4]  # the Adler-32 trailer is missing
    sync = zlib.compressobj()
    # A sync flush ends the data without a final block or a trailer.
    no_final_block = sync.compress(rows) + sync.flush(zlib.Z_SYNC_FLUSH)
    assert zlib.decompressobj().decompress(no_checksum) == rows
    assert zlib.decompressobj().decompress(no_final_block) == rows
    for name, stream in (("a", no_checksum), ("b", no_final_block)):
        found = findings(entry(f"{A}/{name}.png", png_with_idat(png(), stream)))
        assert [(f.rule, f.message) for f in found] == [
            ("png-structure", "IDAT zlib stream does not end cleanly")
        ], name
    # The same rows in a properly ended stream are accepted.
    assert only(f"{A}/c.png", png_with_idat(png(), zlib.compress(rows))) == []


def test_idat_is_inflated_no_further_than_the_length_the_header_implies():
    # A 100 MiB run of zeros is a ~100 KiB deflate stream. The checker must refuse it after
    # inflating one byte past the 320 x 320 RGB rows, not allocate the lot.
    bomb = zlib.compress(bytes(100 * 2**20), 9)
    assert len(bomb) < 2**20
    data = png_with_idat(png(), bomb)
    expected = assets.png_raw_length(320, 320, 2, 8, 0)
    tracemalloc.start()
    try:
        found = findings(entry(f"{A}/bomb.png", data))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert [(f.rule, f.message) for f in found] == [
        ("png-structure", f"IDAT inflates past the {expected:,} bytes the image header implies")
    ]
    assert peak < 2 * 2**20, f"peak {peak:,} bytes while checking a 100 MiB bomb"


def test_the_inflate_limit_is_exactly_one_byte_past_the_expected_length():
    # The exact length is accepted and anything longer is refused as "inflates past". (This test
    # alone cannot tell the margin of one byte from a larger one, or from none: the next test
    # pins the limit given to zlib.)
    expected = assets.png_raw_length(320, 320, 2, 8, 0)
    for extra, outcome in ((0, []), (1, ["png-structure"]), (2, ["png-structure"])):
        data = png_with_idat(png(), zlib.compress(bytes(expected + extra)))
        assert only(f"{A}/e{extra}.png", data) == outcome, extra


class InflateSpy:
    """Stands in for ``zlib`` inside the checker: all real, but every inflate call is recorded
    as (max_length it was given, number of bytes it returned)."""

    def __init__(self):
        self.calls: list[tuple[int, int]] = []
        self.crc32 = zlib.crc32
        self.error = zlib.error

    def decompressobj(self):
        real, calls = zlib.decompressobj(), self.calls

        class Recording:
            def decompress(self, data, max_length=0):
                out = real.decompress(data, max_length)
                calls.append((max_length, len(out)))
                return out

            def __getattr__(self, name):  # eof, unused_data, ...
                return getattr(real, name)

        return Recording()


def spy_on_inflate(monkeypatch) -> InflateSpy:
    spy = InflateSpy()
    monkeypatch.setattr(assets, "zlib", spy)
    return spy


def test_the_inflate_call_is_given_exactly_one_byte_past_the_expected_length(monkeypatch):
    # The spare byte is what tells "too long" from "does not end cleanly" and keeps a valid file
    # off the output limit altogether. A margin of two bytes (or none) returns a different
    # number of bytes here, so the margin cannot drift unnoticed.
    spy = spy_on_inflate(monkeypatch)
    expected = assets.png_raw_length(320, 320, 2, 8, 0)
    data = png_with_idat(png(), zlib.compress(bytes(expected + 50)))
    found = findings(entry(f"{A}/long.png", data))
    assert [f.rule for f in found] == ["png-structure"]
    assert spy.calls == [(expected + 1, expected + 1)]


def png_with_header(width, height, colour, depth, interlace, idat: bytes) -> bytes:
    """A PNG whose header says anything, with the given IDAT body (not necessarily matching)."""
    header = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)
    return png_rebuilt([(b"IHDR", header), (b"IDAT", idat), (b"IEND", b"")])


def zeros_stream(total: int) -> bytes:
    """A zlib stream of ``total`` zero bytes, built without ever holding them all in memory."""
    packer = zlib.compressobj(9)
    parts = [packer.compress(bytes(2**20)) for _ in range(total // 2**20)]
    parts += [packer.compress(bytes(total % 2**20)), packer.flush()]
    return b"".join(parts)


def asset_findings(data: bytes) -> list[tuple[str, str]]:
    return [(f.rule, f.message) for f in findings(entry(f"{A}/big.png", data))]


def embedded_findings(data: bytes) -> list[tuple[str, str]]:
    return [(f.rule, f.message) for f in assets.inspect_embedded("image/png", data)]


# (backstop constant, how a file reaches it, the rule a refusal carries, its value in MiB): a file
# under assets/ has the dimension limits, so a refusal is a "dimensions" finding; an image
# embedded in a notebook has none, so the cap is much higher.
BACKSTOPS = [
    pytest.param("_MAX_INFLATED_ASSET", asset_findings, "dimensions", 32, id="asset"),
    pytest.param("_MAX_INFLATED", embedded_findings, "png-structure", 256, id="embedded"),
]


@pytest.mark.parametrize("interlace", [0, 1])
def test_the_largest_legal_asset_is_not_refused_by_the_backstop(interlace):
    # 1568 x 1568 RGBA 16-bit implies 19,670,560 bytes (19,671,932 interlaced) and is a file of
    # about 19 KB. A backstop under that would reject a legal image (a 16 MiB one does).
    expected = assets.png_raw_length(1568, 1568, 6, 16, interlace)
    assert expected > 16 * 2**20
    data = png_with_header(1568, 1568, 6, 16, interlace, zeros_stream(expected))
    assert len(data) < assets.MAX_FILE_BYTES
    assert only(f"{A}/largest.png", data) == []


def test_a_large_embedded_figure_is_not_refused_by_the_backstop():
    # A notebook figure has no dimension limit: 3000 x 2400 RGBA implies 28,802,400 bytes.
    expected = assets.png_raw_length(3000, 2400, 6, 8, 0)
    assert expected > 16 * 2**20
    data = png_with_header(3000, 2400, 6, 8, 0, zeros_stream(expected))
    assert embedded_findings(data) == []


@pytest.mark.parametrize(("constant", "check", "rule", "mib"), BACKSTOPS)
def test_a_header_one_past_the_backstop_is_refused_and_one_at_it_is_not(
    monkeypatch, constant, check, rule, mib
):
    spy = spy_on_inflate(monkeypatch)
    expected = assets.png_raw_length(320, 320, 2, 8, 0)  # 307,520 bytes for a 320 x 320 RGB PNG
    data = png()
    monkeypatch.setattr(assets, constant, expected)  # exactly at the backstop: allowed
    assert check(data) == []
    assert spy.calls
    spy.calls.clear()
    monkeypatch.setattr(assets, constant, expected - 1)  # one byte over it: refused, not inflated
    found = check(data)
    assert [r for r, _ in found] == [rule]
    assert found[0][1].startswith(
        f"the image header implies {expected:,} bytes of pixel data; "
        f"the most inflated is {expected - 1:,}"
    )
    assert spy.calls == []


@pytest.mark.parametrize(("constant", "check", "rule", "mib"), BACKSTOPS)
def test_the_backstops_are_the_documented_sizes(constant, check, rule, mib):
    # A header implying 2 bytes more than the stated size is refused (a backstop of 4 GiB would
    # let it through to the length check, which words it differently), whatever the constant
    # says: gray 8-bit, 1 pixel wide, implies two bytes per row.
    height = mib * 2**20 // 2 + 1
    data = png_with_header(1, height, 0, 8, 0, zlib.compress(bytes(64)))
    assert assets.png_raw_length(1, height, 0, 8, 0) == mib * 2**20 + 2
    found = check(data)
    assert [r for r, _ in found] == [rule]
    assert found[0][1].startswith(
        f"the image header implies {mib * 2**20 + 2:,} bytes of pixel data; "
        f"the most inflated is {mib * 2**20:,}"
    )


def test_a_small_file_with_a_huge_header_cannot_make_the_asset_check_allocate_much():
    # A 299 KB file with a 9000 x 9000 header (243,009,000 bytes implied, under the old 256 MiB
    # backstop) made the checker peak at about 487 MB. Nothing is inflated for it now.
    expected = assets.png_raw_length(9000, 9000, 2, 8, 0)
    data = png_with_header(9000, 9000, 2, 8, 0, zeros_stream(300 * 2**20))
    assert len(data) < assets.MAX_FILE_BYTES
    if tracemalloc.is_tracing():
        pytest.skip("tracemalloc is already running, so its peak is not this test's")
    tracemalloc.start()
    try:
        found = asset_findings(data)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 2**20, f"peak {peak:,} bytes while checking a 9000 x 9000 header"
    assert [r for r, _ in found] == ["dimensions"]
    assert f"implies {expected:,} bytes" in found[0][1]


def test_idat_chunks_must_be_consecutive():
    def split(chunks):
        i = next(i for i, (k, _) in enumerate(chunks) if k == b"IDAT")
        body = chunks[i][1]
        chunks[i : i + 1] = [(b"IDAT", body[:5]), (b"gAMA", bytes(4)), (b"IDAT", body[5:])]

    assert only(f"{A}/a.png", png_edit(png(), split)) == ["png-structure"]

    def split_clean(chunks):
        i = next(i for i, (k, _) in enumerate(chunks) if k == b"IDAT")
        body = chunks[i][1]
        chunks[i : i + 1] = [(b"IDAT", body[:5]), (b"IDAT", body[5:])]

    assert only(f"{A}/b.png", png_edit(png(), split_clean)) == []


def test_png_ihdr_fields_are_validated():
    def with_ihdr(colour, depth):
        return png_edit(
            png(),
            lambda c: c.__setitem__(0, (b"IHDR", ihdr(320, 320, depth, colour))),
        )

    assert only(f"{A}/a.png", with_ihdr(5, 8)) == ["png-structure"]
    assert only(f"{A}/b.png", with_ihdr(2, 4)) == ["png-structure"]


def test_a_png_crc_error_is_reported_as_a_crc_error():
    data = bytearray(png())
    data[20] ^= 0xFF  # inside the IHDR body (bytes 16-28); its CRC is bytes 29-32
    found = findings(entry(f"{A}/a.png", bytes(data)))
    assert [f.rule for f in found] == ["png-structure"]
    assert "bad CRC in chunk IHDR" in found[0].message
    # A bad CRC in a later chunk too.
    data = bytearray(png())
    data[-1] ^= 0xFF  # the last byte of the IEND CRC
    assert "bad CRC in chunk IEND" in findings(entry(f"{A}/b.png", bytes(data)))[0].message


def adam7_length_by_counting(width, height, bits_per_pixel) -> int:
    """Independent of the tool: count the pixels of every Adam7 pass one by one."""
    starts = [
        (0, 0, 8, 8),
        (4, 0, 8, 8),
        (0, 4, 4, 8),
        (2, 0, 4, 4),
        (0, 2, 2, 4),
        (1, 0, 2, 2),
        (0, 1, 1, 2),
    ]
    total = 0
    for x0, y0, dx, dy in starts:
        columns = len(range(x0, width, dx))
        rows = len(range(y0, height, dy))
        if columns and rows:
            total += rows * (1 + (columns * bits_per_pixel + 7) // 8)
    return total


def interlaced_png(width=320, height=320, bits=24, extra=0) -> bytes:
    header = ihdr(width, height, 8, 2)[:-1] + b"\x01"
    raw = bytes(adam7_length_by_counting(width, height, bits) + extra)
    return png_rebuilt([(b"IHDR", header), (b"IDAT", zlib.compress(raw)), (b"IEND", b"")])


def test_sixteen_bit_and_interlaced_pngs_are_accepted():
    assert only(f"{A}/deep.png", raw_png(2, 16)) == []
    assert only(f"{A}/inter.png", interlaced_png()) == []
    assert only(f"{A}/inter2.png", interlaced_png(333, 301)) == []


def test_the_inflated_idat_length_must_match_the_image_header():
    assert only(f"{A}/a.png", interlaced_png(extra=1)) == ["png-structure"]
    assert only(f"{A}/b.png", interlaced_png(extra=-1)) == ["png-structure"]

    # Text appended to the pixel rows inside the zlib stream, in a plain PNG.
    def pad(chunks):
        i = next(i for i, (k, _) in enumerate(chunks) if k == b"IDAT")
        raw = zlib.decompress(chunks[i][1]) + TEXT
        chunks[i] = (b"IDAT", zlib.compress(raw))

    found = findings(entry(f"{A}/c.png", png_edit(png(), pad)))
    assert [f.rule for f in found] == ["png-structure"]
    assert "the image header implies" in found[0].message

    def short(chunks):
        i = next(i for i, (k, _) in enumerate(chunks) if k == b"IDAT")
        chunks[i] = (b"IDAT", zlib.compress(zlib.decompress(chunks[i][1])[:-3]))

    assert only(f"{A}/d.png", png_edit(png(), short)) == ["png-structure"]


@pytest.mark.parametrize(
    ("colour", "depth"), [(0, 1), (0, 8), (2, 8), (2, 16), (3, 4), (4, 8), (6, 16)]
)
def test_expected_length_covers_every_colour_type_and_depth(colour, depth):
    palette = bytes(3 * 2**depth) if colour == 3 else b""
    assert only(f"{A}/a.png", raw_png(colour, depth, width=333, height=301, palette=palette)) == []
    width = 333
    assert assets.png_raw_length(width, 5, colour, depth, 0) == 5 * (
        1 + (width * {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour] * depth + 7) // 8
    )


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        (b"gAMA", bytes(4)),
        (b"cHRM", bytes(32)),
        (b"sRGB", b"\x00"),
        (b"pHYs", PHYS),
        (b"sBIT", b"\x08\x08\x08"),
        (b"bKGD", bytes(6)),
        (b"tRNS", bytes(6)),
    ],
)
def test_a_png_chunk_that_may_appear_only_once_is_rejected_when_repeated(kind, body):
    assert only(f"{A}/a.png", raw_png(2, 8, extra=[(kind, body)])) == []
    found = findings(entry(f"{A}/b.png", raw_png(2, 8, extra=[(kind, body), (kind, body)])))
    assert [f.rule for f in found] == ["png-metadata"]
    assert "more than once" in found[0].message


def test_a_second_exact_jfif_header_is_rejected():
    def duplicate(segments):
        segments.insert(1, (0xE0, segments[0][1]))  # byte-for-byte the same valid 16-byte header

    found = findings(entry(f"{A}/a.jpg", jpeg_edit(duplicate)))
    assert [f.rule for f in found] == ["jpeg-metadata"]
    assert "second or late APP0" in found[0].message


def test_a_late_jfif_header_after_the_frame_is_rejected():
    def late(segments):
        i = next(i for i, (m, _) in enumerate(segments) if m == 0xDA)
        segments.insert(i, (0xE0, segments[0][1]))

    found = findings(entry(f"{A}/a.jpg", jpeg_edit(late)))
    assert [f.rule for f in found] == ["jpeg-metadata"]


def test_the_jpeg_marker_allowlist_refuses_unknown_markers_even_with_a_valid_table_body():
    # A body that would parse as an empty Huffman table (17 zero bytes) must not rescue a marker
    # that is not on the allowlist: only the allowlist stops it.
    for marker in (0xDC, 0xDE, 0xDF, 0xF0, 0xF8, 0x02, 0x4F):
        found = findings(
            entry(f"{A}/a.jpg", jpeg_edit(lambda s, m=marker: s.insert(1, (m, bytes(17)))))
        )
        assert [f.rule for f in found] == ["jpeg-structure"], hex(marker)
        assert "is not one a baseline JPEG fixture may contain" in found[0].message, hex(marker)
    # The same table body under the real DHT marker is a well-formed (if useless) table.
    assert only(f"{A}/b.jpg", jpeg_edit(lambda s: s.insert(1, (0xC4, bytes(17))))) == []


def test_only_one_matplotlib_software_line_is_allowed_in_an_embedded_png():
    def with_text(*texts):
        def add(chunks):
            for text in texts:
                chunks.insert(1, (b"tEXt", text))

        return png_edit(png(), add)

    good = b"Software\x00Matplotlib version3.10.9, https://matplotlib.org/"
    assert assets.inspect_embedded("image/png", with_text(good)) == []
    for bad in (
        (good, good),
        (b"Software\x00Jane Doe wrote this at C:\\Users\\jane",),
        (b"Software\x00Matplotlib version3.10.9, https://matplotlib.org/ and more text",),
        (b"Author\x00Matplotlib version3.10.9, https://matplotlib.org/",),
        (good, b"Comment\x00hello"),
    ):
        found = assets.inspect_embedded("image/png", with_text(*bad))
        assert [f.rule for f in found] == ["png-metadata"], bad


# -- content sniffing outside assets/ -----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("chart.dat", b"BM" + bytes(4) + bytes(4) + struct.pack("<II", 54, 40) + bytes(40)),
        ("x.bin", b"\x00\x00\x01\x00\x01\x00" + bytes(30)),
        ("diagram.xml", b"<svg xmlns='http://www.w3.org/2000/svg' width='10'/>"),
        (
            "diagram2.txt",
            b'<?xml version="1.0"?>\n<!-- c -->\n<!DOCTYPE svg>\n<svg viewBox="0 0 1 1">',
        ),
        ("bom.xml", "\ufeff  <svg/>".encode()),
        ("photo.bin", b"\x00\x00\x00\x18ftypheic" + bytes(20)),
        ("photo2.bin", b"\x00\x00\x00\x1cftypavif" + bytes(20)),
        ("scan.bin", b"\x00\x00\x00\x0cjP  \r\n\x87\n" + bytes(20)),
    ],
)
def test_more_image_types_are_found_by_content_outside_assets(name, data):
    found = findings(entry(f"recipes/01-demo/helpers/{name}", data))
    assert [f.rule for f in found] == ["image-outside-assets"], name


@pytest.mark.parametrize(
    "data",
    [
        b"BM is the abbreviation of a bureau\n",
        b"<svg-like text is not a file that starts with the tag\n",
        b"# README\n<svg ...> mentioned later\n",
        b"\x00\x00\x01\x00\x00\x00",  # an ICO header with zero images
        b"\x00\x00\x00\x18ftypmp42" + bytes(20),  # an MP4, not an image brand
        b"plain text",
    ],
)
def test_ordinary_files_are_not_mistaken_for_images(data):
    assert rules(entry("recipes/01-demo/helpers/notes.txt", data)) == []


def test_the_documented_sniff_list_matches_the_code():
    section = (REPO / "docs" / "fixtures.md").read_text(encoding="utf-8")
    for fmt in (
        "PNG",
        "JPEG",
        "GIF",
        "WebP",
        "TIFF",
        "BMP",
        "ICO",
        "HEIF/AVIF",
        "JPEG 2000",
        "SVG",
    ):
        assert fmt in assets.sniff.__doc__, fmt
    assert "not detected" in section and "data:" in section


# -- the 280-1568 contract, and the wiring -------------------------------------------------------


def test_the_checker_limits_match_the_documented_280_to_1568_contract():
    text = (REPO / "docs" / "fixtures.md").read_text(encoding="utf-8")
    assert f"{assets.MIN_SIDE} to {assets.MAX_SIDE} pixels" in text
    assert f"{assets.MIN_PIXELS:,} to {assets.MAX_PIXELS:,}" in text
    assert (assets.MIN_SIDE, assets.MAX_SIDE) == (280, 1568)


def test_the_checker_limits_match_the_shared_image_limits():
    # Plain attribute access: if `IMAGE_LIMITS` is renamed or removed this test must error, not
    # quietly pass with nothing compared.
    import jev_cookbook.vision as vision

    assert (assets.MIN_SIDE, assets.MAX_SIDE, assets.MIN_PIXELS, assets.MAX_PIXELS) == tuple(
        vision.IMAGE_LIMITS[k] for k in ("min_side", "max_side", "min_area", "max_area")
    )


def test_the_pre_commit_config_runs_the_asset_checker():
    text = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "entry: python tools/check_recipe_assets.py" in text


def test_the_contributor_documents_mention_the_asset_check():
    contributing = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "├── assets/" in contributing and "docs/fixtures.md" in contributing
    development = (REPO / "docs" / "development.md").read_text(encoding="utf-8")
    row = next(ln for ln in development.splitlines() if ln.startswith("| `Hygiene ("))
    assert "tools/check_recipe_assets.py" in row
    assert "check_recipe_assets.py" in development[development.index("## Repository hygiene") :]


def test_the_file_too_large_message_points_photographic_content_to_jpeg():
    message = assets.check_image(f"{A}/big.png", b"\x89PNG\r\n\x1a\n" + bytes(2**20))[0].message
    assert "JPEG" in message
