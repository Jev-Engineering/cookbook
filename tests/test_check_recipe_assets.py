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
    corrupt = bytearray(data)
    corrupt[33] ^= 0xFF  # inside the IHDR body: the CRC no longer matches
    assert only(f"{A}/b.png", bytes(corrupt)) == ["png-structure"]
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
