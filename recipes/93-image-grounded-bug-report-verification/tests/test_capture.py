"""Exercise real recorder integration with an injected in-memory client, no network."""

import importlib.util
import json
from pathlib import Path

from jev_cookbook import LiveBackend, ReplayBackend, load_helpers, record, replay_key
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def test_recorded_triples_replay_and_capture_actual_returned_fields(tmp_path):
    spec = importlib.util.spec_from_file_location("bug93_capture_test", RECIPE / "capture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    example = load_inputs(RECIPE)[0]
    request = helpers.build_request(example.fields, RECIPE)

    class Client:
        calls = 0

        def system_one(self, **kwargs):
            self.calls += 1
            assert len(kwargs["questions"]) == 4
            return {
                "model": "jev-1.14.0",
                "usage": {"input_tokens": 123, "output_tokens": 7},
                "answers": {name: {"type": "noul", "noul": 0.97} for name in helpers.CLAIMS},
            }

    client = Client()
    live = LiveBackend("jev-1.14.0", client=client, images=True, max_requests=1, max_retries=0)
    measurements = tmp_path / "measurements.json"
    timed = module.TimedBackend(live, measurements)
    responses = tmp_path / "fixtures" / "responses.json"
    report = record(timed, [request], responses, ledger_path=tmp_path / "ledger.json")
    assert len(report.written) == client.calls == 1
    state, questions, assets = request
    key = replay_key(state, questions, assets=assets)
    replayed = ReplayBackend.from_json(responses).decide(state, questions, assets=assets)
    assert replayed.model == "jev-1.14.0"
    assert all(a.provenance.source == "recorded" for a in replayed.answers.values())
    row = json.loads(measurements.read_text())[key]
    assert row["input_tokens"] == 123 and row["output_tokens"] == 7
    assert row["latency_seconds"] >= 0
    assert row["date"] == next(iter(replayed.answers.values())).provenance.date
    assert row["cost_usd"] is None
    again = record(timed, [request], responses, ledger_path=tmp_path / "ledger.json")
    assert len(again.skipped) == 1 and client.calls == 1
