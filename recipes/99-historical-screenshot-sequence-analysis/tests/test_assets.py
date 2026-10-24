"""Rebuild the original artwork independently and keep labels outside image requests."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

RECIPE = Path(__file__).resolve().parent.parent


def test_assets_reproduce_and_meet_the_request_shape(tmp_path):
    copy = tmp_path / "recipe99"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        shutil.copyfile(RECIPE / name, copy / name)
    completed = subprocess.run(
        [sys.executable, str(copy / "build_fixtures.py")], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    names = sorted(path.name for path in (RECIPE / "assets").glob("*.png"))
    assert len(names) == 205
    assert names == sorted(path.name for path in (copy / "assets").glob("*.png"))
    for name in names:
        original, regenerated = RECIPE / "assets" / name, copy / "assets" / name
        assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(
            regenerated.read_bytes()
        ).digest()
        with Image.open(original) as image:
            assert image.size == (480, 360) and image.format == "PNG"
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text())
    setup = next(cell for cell in notebook["cells"] if cell["id"] == "setup")
    text = "".join(setup["source"])
    assert "long_context=True" in text and "images=True" in text and 'model="jev-1.14.0"' in text
