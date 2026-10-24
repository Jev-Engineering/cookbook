"""Verify original drawings reproduce and full manifests stay readable."""

import importlib.util
import io
from pathlib import Path

from PIL import Image

from jev_cookbook.fixtures import load_inputs
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent


def test_all_source_frames_reproduce_and_meet_image_contract():
    spec = importlib.util.spec_from_file_location("recipe92_drawings", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    examples = load_inputs(RECIPE)
    assert len(examples) == 26
    for index, example in enumerate(examples):
        assert len(example.fields["frames"]) == 5
        for frame, row in enumerate(example.fields["frames"]):
            path = RECIPE / row["path"]
            assert image_asset(path)["format"] == "png"
            with Image.open(path) as image:
                assert image.size == (480, 360)
            generated = io.BytesIO()
            module.draw_frame(module.ROWS[index][2], frame, index).save(generated, format="PNG")
            assert generated.getvalue() == path.read_bytes()


def test_validation_and_test_share_no_decoded_source_frame():
    import hashlib

    split_hashes = {"validation": set(), "test": set()}
    for example in load_inputs(RECIPE):
        if example.split not in split_hashes:
            continue
        for row in example.fields["frames"]:
            with Image.open(RECIPE / row["path"]) as image:
                digest = hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()
            split_hashes[example.split].add(digest)
    assert split_hashes["validation"].isdisjoint(split_hashes["test"])


def test_response_guard_fails_closed_on_malformed_content(tmp_path):
    import json

    spec = importlib.util.spec_from_file_location("recipe92_guard", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "responses.json"
    for raw in (b"not json", b"\xff", b"[]", b"{}", b'{"existing-key":{"model":"synthetic"}}'):
        path.write_bytes(raw)
        assert module.protected_responses(path)
        assert path.read_bytes() == raw
    valid = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    path.write_text(json.dumps(valid), encoding="utf-8")
    assert not module.protected_responses(path)
    answer = next(iter(next(iter(valid.values()))["answers"].values()))
    answer["provenance"] = {"source": "recorded", "model": "jev-1.14.0", "date": "2026-10-15"}
    path.write_text(json.dumps(valid), encoding="utf-8")
    assert module.protected_responses(path)
