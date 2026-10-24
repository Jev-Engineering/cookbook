"""The generator reproduces all original raster assets, including preflight-rejected clips."""

import subprocess
import sys
from pathlib import Path

from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent


def test_every_committed_asset_is_valid_and_reproduced(tmp_path):
    for name in ("helpers.py", "build_fixtures.py"):
        (tmp_path / name).write_bytes((RECIPE / name).read_bytes())
    done = subprocess.run(
        [sys.executable, str(tmp_path / "build_fixtures.py")],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    committed = sorted(p.name for p in (RECIPE / "assets").glob("*.png"))
    rebuilt = sorted(p.name for p in (tmp_path / "assets").glob("*.png"))
    assert len(committed) == 92
    assert rebuilt == committed
    for name in committed:
        assert image_asset(RECIPE / "assets" / name)["format"] == "png"
        assert (RECIPE / "assets" / name).read_bytes() == (tmp_path / "assets" / name).read_bytes()
