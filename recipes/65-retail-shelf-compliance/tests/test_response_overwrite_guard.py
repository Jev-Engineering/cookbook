"""Damaged captures must survive regeneration until --force explicitly replaces them."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import ReplayBackend
from jev_cookbook.live import _dump

RECIPE = Path(__file__).resolve().parent.parent
KEY = "0" * 64
VALID_ENTRY = json.dumps(
    next(iter(json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8")).values()))
)


@pytest.fixture
def generator(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "recipe65_overwrite_guard_generator", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", tmp_path)
    # One authored row exercises the real main path without regenerating every drawing
    # for each damaged-file variant. The scaffold separately verifies the full fixture set.
    monkeypatch.setattr(module, "ROWS", module.ROWS[:1])
    monkeypatch.setattr("sys.argv", ["build_fixtures.py"])
    (tmp_path / "fixtures").mkdir()
    return module


def payload(entry):
    return json.dumps({KEY: entry}).encode()


@pytest.mark.parametrize(
    "damaged",
    [
        b'{"request":{"model":"jev-1.14.0","answers":',
        b"\xff\xfe damaged capture",
        b"",
        b"null",
        b"[]",
        b'"synthetic"',
        b"{}",
        payload(None),
        payload([]),
        payload({"model": "synthetic"}),
        payload({"model": "synthetic", "answers": None}),
        payload({"model": "synthetic", "answers": {}}),
        payload(
            {
                "model": "synthetic",
                "answers": {
                    "oats": {
                        "type": "noul",
                        "noul": 1.5,
                        "provenance": {"source": "synthetic"},
                    }
                },
            }
        ),
        ('{"request":' + VALID_ENTRY + "}").encode(),
        ('{"' + KEY + '":' + VALID_ENTRY + ',"' + KEY + '":' + VALID_ENTRY + "}").encode(),
    ],
    ids=[
        "truncated-recording",
        "invalid-utf8",
        "empty-file",
        "null-top-level",
        "array-top-level",
        "string-top-level",
        "empty-object",
        "null-entry",
        "array-entry",
        "missing-answers",
        "null-answers",
        "empty-answers",
        "invalid-probability",
        "invalid-replay-key",
        "duplicate-key",
    ],
)
def test_malformed_capture_is_preserved_until_force(generator, damaged, monkeypatch):
    responses = generator.HERE / "fixtures" / "responses.json"
    responses.write_bytes(damaged)

    with pytest.raises(SystemExit, match="--force"):
        generator.main()

    assert responses.read_bytes() == damaged
    inputs, labels = generator.build_inputs_and_labels(generator.ROWS)
    for name, expected in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        actual = (responses.parent / name).read_text("utf-8")
        assert [json.loads(line) for line in actual.splitlines()] == expected

    monkeypatch.setattr("sys.argv", ["build_fixtures.py", "--force"])
    generator.main()
    assert responses.read_text("utf-8") == _dump(generator.build_responses(generator.ROWS))
    assert ReplayBackend.from_json(responses).mode == "synthetic"


def test_unreadable_capture_is_preserved_and_force_bypasses_read(generator, monkeypatch):
    responses = generator.HERE / "fixtures" / "responses.json"
    original = (RECIPE / "fixtures" / "responses.json").read_bytes()
    responses.write_bytes(original)

    def denied(path):
        assert path == responses
        raise PermissionError("capture cannot be read")

    monkeypatch.setattr(generator, "ReplayBackend", SimpleNamespace(from_json=denied))
    with pytest.raises(SystemExit, match="--force"):
        generator.main()
    assert responses.read_bytes() == original

    monkeypatch.setattr("sys.argv", ["build_fixtures.py", "--force"])
    generator.main()
    assert responses.read_text("utf-8") == _dump(generator.build_responses(generator.ROWS))


def test_unreadable_metadata_is_protected(generator, monkeypatch):
    responses = generator.HERE / "fixtures" / "responses.json"
    original = b"unreadable capture"
    responses.write_bytes(original)
    original_lstat = Path.lstat

    def denied(path, *args, **kwargs):
        if path == responses:
            raise PermissionError("capture metadata cannot be read")
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", denied)
    with pytest.raises(SystemExit, match="--force"):
        generator.main()
    assert responses.read_bytes() == original


def test_only_absent_or_valid_synthetic_file_is_safe(generator):
    path = generator.HERE / "fixtures" / "responses.json"
    assert not generator._is_recorded(path)
    path.write_bytes((RECIPE / "fixtures" / "responses.json").read_bytes())
    assert not generator._is_recorded(path)
