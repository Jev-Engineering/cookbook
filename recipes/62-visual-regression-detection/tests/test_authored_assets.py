"""Authored image reproducibility and protection of recorded answers."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from jev_cookbook.live import _dump

RECIPE = Path(__file__).resolve().parent.parent
SCRIPT = RECIPE / "build_fixtures.py"


def load_generator(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_generator(tmp_path):
    copy = tmp_path / "visual-regression"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    return copy


def run_generator(recipe, *args):
    return subprocess.run(
        [sys.executable, str(recipe / "build_fixtures.py"), *args],
        capture_output=True,
        text=True,
    )


def jsonl(rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


def generated_bytes(recipe):
    return {
        path.relative_to(recipe).as_posix(): path.read_bytes()
        for folder in ("assets", "fixtures")
        for path in sorted((recipe / folder).iterdir())
        if path.is_file()
    }


def test_committed_responses_match_the_recorder_writer_from_freshly_built_data(tmp_path):
    module = load_generator(SCRIPT, "visual_regression_generator_serialization_test")
    _, _, responses = module.build_data(tmp_path)
    assert len(responses) > 1
    assert (RECIPE / "fixtures" / "responses.json").read_text("utf-8") == _dump(responses)


def test_generator_reproduces_committed_image_and_fixture_bytes_twice(tmp_path):
    copy = copy_generator(tmp_path)
    first = run_generator(copy)
    assert first.returncode == 0, first.stderr
    expected = generated_bytes(RECIPE)
    assert generated_bytes(copy) == expected
    second = run_generator(copy)
    assert second.returncode == 0, second.stderr
    assert generated_bytes(copy) == expected


def test_recorded_guard_preserves_responses_but_refreshes_inputs_and_labels(tmp_path):
    copy = copy_generator(tmp_path)
    first = run_generator(copy)
    assert first.returncode == 0, first.stderr
    path = copy / "fixtures" / "responses.json"
    synthetic = path.read_bytes()
    recorded = json.loads(synthetic)
    for result in recorded.values():
        result["model"] = "jev-recorded-test"
    path.write_text(_dump(recorded), encoding="utf-8", newline="\n")
    protected = path.read_bytes()
    inputs_path = copy / "fixtures" / "inputs.jsonl"
    labels_path = copy / "fixtures" / "labels.jsonl"
    inputs_path.write_bytes(b"corrupted")
    labels_path.write_bytes(b"corrupted")

    refused = run_generator(copy)
    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert path.read_bytes() == protected
    module = load_generator(
        copy / "build_fixtures.py", "visual_regression_generator_recorded_guard_test"
    )
    inputs, labels, _ = module.build_data(copy)
    assert inputs_path.read_text("utf-8") == jsonl(inputs)
    assert labels_path.read_text("utf-8") == jsonl(labels)

    forced = run_generator(copy, "--force")
    assert forced.returncode == 0, forced.stderr
    assert path.read_bytes() == synthetic


def test_authored_assets_meet_the_image_dimension_limits():
    assets = list((RECIPE / "assets").glob("*.png"))
    assert assets
    for path in assets:
        with Image.open(path) as image:
            width, height = image.size
            assert image.format == "PNG"
            assert 256 <= width <= 1568
            assert 256 <= height <= 1568
            assert width * height >= 78400


def test_allowed_theme_keeps_the_header_text_readable():
    module = load_generator(SCRIPT, "visual_regression_theme_header_test")
    before = np.asarray(module.render_page(701))
    themed = np.asarray(module.render_page(701, "theme"))
    np.testing.assert_array_equal(before[:46], themed[:46])
    assert themed[0, 0].max() < 64
    assert (themed[16:35, 20:180].min(axis=2) > 240).any()
