"""The generator reproduces the authored PNGs, as well as the guarded JSON files."""

import importlib.util
from pathlib import Path

from PIL import Image

RECIPE = Path(__file__).resolve().parent.parent


def test_assets_rebuild_pixel_identically(tmp_path):
    spec = importlib.util.spec_from_file_location("recipe91_assets", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = tmp_path
    module.build_assets(module.ROWS)
    expected = sorted((RECIPE / "assets").rglob("*.png"))
    assert len(expected) == 182
    for original in expected:
        rebuilt = tmp_path / original.relative_to(RECIPE)
        assert original.read_bytes() == rebuilt.read_bytes()
        with Image.open(original) as image:
            assert image.size == (400, 320)
            assert not image.getexif()


def test_protection_handles_malformed_and_provenance_only_records(tmp_path):
    import json

    from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance

    spec = importlib.util.spec_from_file_location(
        "recipe91_protection", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "responses.json"
    malformed = [
        [],
        {"k": None},
        {"k": {"model": "synthetic"}},
        {"k": {"model": "synthetic", "answers": None}},
        {"k": {"model": "synthetic", "answers": {"phase": None}}},
    ]
    for data in malformed:
        path.write_text(json.dumps(data))
        assert module.protected_responses(path)
    a = ChoiceAnswer.from_probabilities(
        {"yes": 0.9, "no": 0.1}, Provenance.recorded("jev-1.14.0", "2026-10-15")
    )
    recorded = DecisionResult({"phase": a}, "jev-1.14.0").to_dict()
    path.write_text(json.dumps({"k": recorded}))
    assert module.protected_responses(path)
    recorded["model"] = "synthetic"
    path.write_text(json.dumps({"k": recorded}))
    assert module.protected_responses(path)
