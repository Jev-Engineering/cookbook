"""Generated image bytes are reproducible, and recorded provenance cannot be replaced."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def test_all_generated_asset_bytes_are_reproducible(tmp_path):
    for name in ("helpers.py", "build_fixtures.py"):
        (tmp_path / name).write_bytes((RECIPE / name).read_bytes())
    result = subprocess.run(
        [sys.executable, str(tmp_path / "build_fixtures.py")], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    original = {p.name: p.read_bytes() for p in (RECIPE / "assets").glob("*.png")}
    generated = {p.name: p.read_bytes() for p in (tmp_path / "assets").glob("*.png")}
    assert len(original) == 31
    assert generated == original


def test_recorded_provenance_blocks_rebuild_even_if_model_field_is_corrupted(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "piece_builder_guard", RECIPE / "build_fixtures.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    path = tmp_path / "responses.json"
    path.write_text(
        json.dumps(
            {
                "fake": {
                    "model": "synthetic",
                    "answers": {"piece": {"provenance": {"source": "recorded"}}},
                }
            }
        )
    )
    assert builder._is_recorded(path)
    path.write_text("broken JSON")
    assert builder._is_recorded(path)
