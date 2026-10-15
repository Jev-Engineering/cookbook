"""The generator reproduces its authored images and protects recorded model answers."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from jev_cookbook import Provenance
from jev_cookbook.live import _dump

RECIPE = Path(__file__).resolve().parent.parent


def copied_recipe(tmp_path):
    recipe = tmp_path / "95-ai-livestream-overlay-verification"
    recipe.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        shutil.copyfile(RECIPE / name, recipe / name)
    return recipe


def load_builder(recipe):
    spec = importlib.util.spec_from_file_location(
        "recipe95_fixture_builder_for_test", recipe / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_builder(recipe, *arguments):
    return subprocess.run(
        [sys.executable, str(recipe / "build_fixtures.py"), *arguments],
        capture_output=True,
        text=True,
        timeout=120,
    )


def jsonl(rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


def artifact_bytes(recipe):
    return {
        str(path.relative_to(recipe)): path.read_bytes()
        for directory in ("fixtures", "assets")
        for path in sorted((recipe / directory).glob("*"))
        if path.is_file()
    }


def test_generator_reproduces_committed_json_and_png_bytes_and_is_repeatable(tmp_path):
    recipe = copied_recipe(tmp_path)
    first = run_builder(recipe)
    assert first.returncode == 0, first.stderr
    before = artifact_bytes(recipe)
    committed = artifact_bytes(RECIPE)
    assert before == committed
    images = [path for path in before if path.endswith(".png")]
    assert len(images) == 52
    for name in images:
        with Image.open(recipe / name) as image:
            assert image.format == "PNG"
            assert image.size == (512, 384)
            assert image.mode == "RGB"
    second = run_builder(recipe)
    assert second.returncode == 0, second.stderr
    assert artifact_bytes(recipe) == before


def test_response_bytes_match_the_recorder_dump_of_independently_built_answers(tmp_path):
    recipe = copied_recipe(tmp_path)
    builder = load_builder(recipe)
    inputs, _ = builder.build_inputs_and_labels(builder.ROWS)
    responses = builder.build_responses(builder.ROWS, inputs)
    assert len(responses) == len(builder.ROWS) > 1
    committed = (RECIPE / "fixtures" / "responses.json").read_text("utf-8")
    assert committed == _dump(responses)


def test_recorded_responses_survive_refusal_while_inputs_labels_and_pngs_regenerate(tmp_path):
    recipe = copied_recipe(tmp_path)
    first = run_builder(recipe)
    assert first.returncode == 0, first.stderr
    response_path = recipe / "fixtures" / "responses.json"
    response_data = json.loads(response_path.read_text("utf-8"))
    recorded = Provenance.recorded("jev-fixture-guard-test", "2026-10-15").to_dict()
    for response in response_data.values():
        response["model"] = recorded["model"]
        for answer in response["answers"].values():
            answer["provenance"] = dict(recorded)
    response_path.write_text(_dump(response_data), encoding="utf-8", newline="\n")
    recorded_bytes = response_path.read_bytes()
    original_pngs = {path.name: path.read_bytes() for path in (recipe / "assets").glob("*.png")}
    input_path = recipe / "fixtures" / "inputs.jsonl"
    label_path = recipe / "fixtures" / "labels.jsonl"
    input_path.write_bytes(b"corrupted inputs")
    label_path.write_bytes(b"corrupted labels")
    for name in original_pngs:
        (recipe / "assets" / name).write_bytes(b"corrupted image")

    refused = run_builder(recipe)
    assert refused.returncode != 0
    assert "recorded" in refused.stderr
    assert "--force" in refused.stderr
    assert response_path.read_bytes() == recorded_bytes
    regenerated_input_bytes = input_path.read_text("utf-8")
    regenerated_label_bytes = label_path.read_text("utf-8")
    assert {
        path.name: path.read_bytes() for path in (recipe / "assets").glob("*.png")
    } == original_pngs
    builder = load_builder(recipe)
    expected_inputs, expected_labels = builder.build_inputs_and_labels(builder.ROWS)
    assert regenerated_input_bytes == jsonl(expected_inputs)
    assert regenerated_label_bytes == jsonl(expected_labels)

    forced = run_builder(recipe, "--force")
    assert forced.returncode == 0, forced.stderr
    assert response_path.read_text("utf-8") == _dump(
        builder.build_responses(builder.ROWS, expected_inputs)
    )
    restored = json.loads(response_path.read_text("utf-8"))
    assert all(response["model"] == "synthetic" for response in restored.values())
    assert all(
        answer["provenance"]["source"] == "synthetic"
        for response in restored.values()
        for answer in response["answers"].values()
    )
