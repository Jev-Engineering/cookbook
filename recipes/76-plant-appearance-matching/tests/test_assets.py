"""Independent image lineage and complete asset reproducibility."""

import hashlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from jev_cookbook.fixtures import load_inputs
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent


def test_query_pixels_and_scene_seeds_do_not_leak_across_splits():
    spec = importlib.util.spec_from_file_location("plant_generator", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeds = [row[3] for row in module.ROWS]
    assert len(seeds) == len(set(seeds)) == 26
    seen = set()
    for path in sorted((RECIPE / "assets").glob("*.png")):
        with Image.open(path) as image:
            assert image.size == (384, 320)
            digest = hashlib.sha256(image.tobytes()).hexdigest()
        assert digest not in seen
        seen.add(digest)
        image_asset(path)
    assert len(seen) == 30
    assert len(load_inputs(RECIPE)) == 26


def test_generator_reproduces_every_image_byte(tmp_path):
    for name in ("helpers.py", "build_fixtures.py"):
        shutil.copyfile(RECIPE / name, tmp_path / name)
    done = subprocess.run(
        [sys.executable, str(tmp_path / "build_fixtures.py")], capture_output=True
    )
    assert done.returncode == 0, done.stderr
    for path in (RECIPE / "assets").glob("*.png"):
        assert path.read_bytes() == (tmp_path / "assets" / path.name).read_bytes()
