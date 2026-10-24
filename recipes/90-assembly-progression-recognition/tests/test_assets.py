"""Regeneration also covers binary assets; the standard scaffold covers JSON fixtures."""

import subprocess
import sys
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def test_rebuilt_images_are_byte_identical(tmp_path):
    for name in ("helpers.py", "build_fixtures.py"):
        (tmp_path / name).write_bytes((RECIPE / name).read_bytes())
    result = subprocess.run(
        [sys.executable, str(tmp_path / "build_fixtures.py")], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    expected = sorted((RECIPE / "assets").glob("*.png"))
    actual = sorted((tmp_path / "assets").glob("*.png"))
    assert len(expected) == len(actual) == 78
    assert all(
        a.name == b.name and a.read_bytes() == b.read_bytes()
        for a, b in zip(expected, actual, strict=True)
    )


def test_recording_requires_opt_in_before_any_directory_or_call(tmp_path):
    import os

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("JEV_COOKBOOK_", "TYPESAFE_"))
    }
    destination = tmp_path / "capture"
    result = subprocess.run(
        [sys.executable, str(RECIPE / "record_live.py"), "--output", str(destination)],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "explicit JEV_COOKBOOK_LIVE=1" in result.stderr
    assert not destination.exists()


def test_recording_refuses_existing_destination_before_backend_creation(tmp_path):
    import os

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("JEV_COOKBOOK_", "TYPESAFE_"))
    }
    environment["JEV_COOKBOOK_LIVE"] = "1"
    marker = tmp_path / "preserve.txt"
    marker.write_text("preserve")
    result = subprocess.run(
        [sys.executable, str(RECIPE / "record_live.py"), "--output", str(tmp_path)],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "FileExistsError" in result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["preserve.txt"]
    assert marker.read_text() == "preserve"


def test_measurement_failure_cannot_interrupt_successful_decision_before_recorder(
    tmp_path, monkeypatch
):
    import importlib.util
    import json

    from jev_cookbook import Choice, ChoiceAnswer, DecisionResult, LiveBackend, Provenance

    spec = importlib.util.spec_from_file_location(
        "recipe90_record_probe", RECIPE / "record_live.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = DecisionResult(
        {
            "stage": ChoiceAnswer.from_probabilities(
                {"base": 0.9, "posts": 0.1}, Provenance.recorded("jev-1.14.0", "2026-10-15")
            )
        },
        "jev-1.14.0",
    )
    monkeypatch.setattr(LiveBackend, "__init__", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(LiveBackend, "decide", lambda self, *args, **kwargs: result)
    ticks = iter((10.0, 10.25))
    monkeypatch.setattr(module, "perf_counter", lambda: next(ticks))
    # The missing parent means disk writing would fail if decide tried it before returning.
    backend = module.TimedBackend(tmp_path / "missing" / "measurements.json")
    assert (
        backend.decide("fixture", {"stage": Choice(criteria={"base": "bare", "posts": "posts"})})
        is result
    )
    row = next(iter(backend.measurements.values()))
    assert row["latency_seconds"] == 0.25 and row["cost_usd"] is None
    assert row["model"] == "jev-1.14.0"
    backend.measurement_path.parent.mkdir()
    backend.save_measurements()
    assert json.loads(backend.measurement_path.read_text()) == backend.measurements
