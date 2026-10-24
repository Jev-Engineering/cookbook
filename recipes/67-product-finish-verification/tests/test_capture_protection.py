"""Damaged captures remain intact until replacement is explicitly forced."""

import builtins
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, ReplayBackend
from jev_cookbook.live import _dump

RECIPE = Path(__file__).resolve().parent.parent
KEY = "a" * 64
SYNTHETIC = DecisionResult(
    {"match": NoulAnswer(0.9, Provenance.synthetic())}, "synthetic"
).to_dict()
RECORDED = DecisionResult(
    {"match": NoulAnswer(0.9, Provenance.recorded("jev-1.14.0", "2026-10-15"))},
    "jev-1.14.0",
).to_dict()


def encoded(value):
    return json.dumps(value).encode("utf-8")


@pytest.fixture
def generator(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "recipe67_capture_guard", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", tmp_path)
    # One original case exercises the complete generator without rebuilding all 50 images.
    monkeypatch.setattr(module, "ROWS", module.ROWS[:1])
    monkeypatch.setattr(sys, "argv", ["build_fixtures.py"])
    (tmp_path / "fixtures").mkdir()
    return module, tmp_path / "fixtures" / "responses.json"


def force_and_check(module, path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["build_fixtures.py", "--force"])
    module.main()
    assert ReplayBackend.from_json(path).mode == "synthetic"
    assert path.read_text("utf-8") == _dump(module.build_responses(module.ROWS))


@pytest.mark.parametrize(
    "original",
    [
        b'{"request":{"model":"jev-1.14.0","answers":',
        b"",
        b"\xff\xfe\x00",
        b"null",
        b"[]",
        b"{}",
        encoded({KEY: RECORDED}),
        encoded({"invalid-replay-key": SYNTHETIC}),
        encoded({KEY: None}),
        encoded({KEY: []}),
        encoded({KEY: 12}),
        encoded({KEY: {"model": "synthetic"}}),
        encoded({KEY: {**SYNTHETIC, "answers": {}}}),
        encoded({KEY: {**SYNTHETIC, "answers": {"match": []}}}),
        encoded({KEY: {**SYNTHETIC, "usage": []}}),
        encoded({KEY: {**SYNTHETIC, "unexpected": "field"}}),
        encoded({KEY: {**RECORDED, "model": "synthetic"}}),
        b'{"'
        + KEY.encode()
        + b'":'
        + encoded(RECORDED)
        + b',"'
        + KEY.encode()
        + b'":'
        + encoded(SYNTHETIC)
        + b"}",
    ],
    ids=[
        "truncated-recording",
        "empty-bytes",
        "invalid-utf8",
        "null-root",
        "array-root",
        "empty-root",
        "valid-recorded",
        "invalid-key",
        "null-entry",
        "array-entry",
        "number-entry",
        "missing-answers",
        "empty-answers",
        "invalid-answer",
        "invalid-usage",
        "unknown-field",
        "inconsistent-provenance",
        "duplicate-key-hides-recording",
    ],
)
def test_protected_capture_bytes_require_force(generator, monkeypatch, original):
    module, path = generator
    path.write_bytes(original)
    with pytest.raises(SystemExit, match="refusing to overwrite.*--force"):
        module.main()
    assert path.read_bytes() == original
    assert (path.parent / "inputs.jsonl").is_file()
    assert (path.parent / "labels.jsonl").is_file()
    force_and_check(module, path, monkeypatch)


def test_unreadable_capture_requires_force_and_force_does_not_read_it(generator, monkeypatch):
    module, path = generator
    original = encoded({KEY: RECORDED})
    path.write_bytes(original)
    real_open = builtins.open
    attempts = []

    def deny_capture_read(file, *args, **kwargs):
        if Path(file) == path:
            attempts.append(file)
            raise PermissionError("capture is unreadable")
        return real_open(file, *args, **kwargs)

    with monkeypatch.context() as blocked:
        blocked.setattr(builtins, "open", deny_capture_read)
        with pytest.raises(SystemExit, match="refusing to overwrite.*--force"):
            module.main()
        assert path.read_bytes() == original
        assert len(attempts) == 1
        blocked.setattr(sys, "argv", ["build_fixtures.py", "--force"])
        module.main()
        assert len(attempts) == 1
    assert ReplayBackend.from_json(path).mode == "synthetic"


def test_metadata_failure_preserves_capture_bytes(generator, monkeypatch):
    module, path = generator
    original = encoded({KEY: RECORDED})
    path.write_bytes(original)
    real_stat = Path.stat

    def deny_capture_stat(target, *args, **kwargs):
        if target == path:
            raise PermissionError("capture metadata is unreadable")
        return real_stat(target, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", deny_capture_stat)
    with pytest.raises(SystemExit, match="refusing to overwrite.*--force"):
        module.main()
    assert path.read_bytes() == original
    force_and_check(module, path, monkeypatch)


def test_absent_and_valid_synthetic_files_rebuild_without_force(generator):
    module, path = generator
    assert not path.exists()
    module.main()
    original = path.read_bytes()
    assert ReplayBackend.from_json(path).mode == "synthetic"
    module.main()
    assert path.read_bytes() == original
