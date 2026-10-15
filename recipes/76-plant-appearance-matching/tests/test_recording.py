"""Exercise the recording wrapper without API calls or credentials."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance

RECIPE = Path(__file__).resolve().parent.parent


def test_capture_requires_explicit_opt_in_before_creating_anything(tmp_path):
    env = dict(os.environ)
    env.pop("JEV_COOKBOOK_LIVE", None)
    output = tmp_path / "capture"
    done = subprocess.run(
        [sys.executable, str(RECIPE / "record_live.py"), "--output-dir", str(output)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0 and "explicitly" in done.stderr
    assert not output.exists()


def test_accounting_uses_actual_returned_model_date_and_null_unreported_usage(
    tmp_path, monkeypatch
):
    spec = importlib.util.spec_from_file_location("plant_recorder", RECIPE / "record_live.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    provenance = Provenance.recorded("jev-1.14.0", "2026-10-15")
    typed = ChoiceAnswer.from_probabilities({"broadleaf": 0.9, "unknown": 0.1}, provenance)
    result = DecisionResult({"group": typed}, "jev-1.14.0")
    monkeypatch.setattr(module.LiveBackend, "decide", lambda *args, **kwargs: result)
    times = iter([12.0, 12.25])
    monkeypatch.setattr(module.time, "perf_counter", lambda: next(times))
    backend = object.__new__(module.TimedBackend)
    backend.accounting_path, backend.accounting = tmp_path / "accounting.json", {}
    state, questions, assets = module.helpers.build_request({"image": "assets/query-d01.png"})
    assert backend.decide(state, questions, assets=assets) == result
    row = next(iter(json.loads(backend.accounting_path.read_text()).values()))
    assert row == {
        "model": "jev-1.14.0",
        "input_tokens": None,
        "output_tokens": None,
        "latency_seconds": 0.25,
        "cost_usd": None,
        "mode": "recorded",
        "date": "2026-10-15",
    }
