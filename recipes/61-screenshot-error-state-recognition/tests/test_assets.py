"""Images are reproducible authored evidence; refusing recorded replacement preserves pixels."""

import importlib.util
import json
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parent.parent


def load_generator():
    spec = importlib.util.spec_from_file_location("images61", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_image_pixels_reproduce():
    generator = load_generator()
    for ident, _split, scenario, variant, *_rest in generator.ROWS:
        from PIL import Image

        with Image.open(RECIPE / "assets" / f"{ident}.png") as committed:
            assert committed.tobytes() == generator.draw_screen(scenario, variant).tobytes()


def test_recorded_refusal_keeps_asset_bytes(tmp_path, monkeypatch):
    generator = load_generator()
    monkeypatch.setattr(generator, "HERE", tmp_path)
    monkeypatch.setattr("sys.argv", ["build_fixtures.py"])
    generator.main()
    response_path = tmp_path / "fixtures" / "responses.json"
    responses = json.loads(response_path.read_text())
    for value in responses.values():
        value["model"] = "jev-1.14.0"
    response_path.write_text(json.dumps(responses))
    before = {p.name: p.read_bytes() for p in (tmp_path / "assets").glob("*.png")}

    def forbidden_write(_rows):
        raise AssertionError("refused run must not regenerate recorded image evidence")

    monkeypatch.setattr(generator, "write_assets", forbidden_write)
    with pytest.raises(SystemExit, match="refusing"):
        generator.main()
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "assets").glob("*.png")}
