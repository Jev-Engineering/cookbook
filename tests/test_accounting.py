"""Request accounting measures actual delegate invocations, not fixture inventory."""

import base64
import io
import json

import pytest
from PIL import Image

from jev_cookbook import (
    AuditedBackend,
    Backend,
    BudgetExceeded,
    DecisionResult,
    LiveBackend,
    Noul,
    NoulAnswer,
    Provenance,
    ReplayBackend,
    ReplayMiss,
    ScriptedBackend,
    record,
    replay_key,
)
from jev_cookbook.accounting import AUDIT_PREFIX
from jev_cookbook.style import run_header_text

QUESTIONS = {"present": Noul(instructions="The package is present.")}


def test_duplicate_calls_delegate_independently_and_keep_original_keys():
    observations = []

    def script(state, questions, rng):
        observations.append(state)
        return {"present": len(observations) / 10}

    backend = AuditedBackend(ScriptedBackend(script))
    answers = [backend.decide("package", QUESTIONS)["present"].noul for _ in range(3)]
    assert answers == [0.1, 0.2, 0.3]
    assert observations == ["package"] * 3
    assert isinstance(backend, Backend)
    key = replay_key("package", QUESTIONS)
    audit = backend.audit()
    assert audit == {
        "schema": 1,
        "decide_calls": 3,
        "distinct_requests": 1,
        "calls": [{"replay_key": key, "returned": True}] * 3,
    }
    audit["calls"].clear()
    assert len(backend.audit()["calls"]) == 3
    assert json.loads(backend.audit_json().removeprefix(AUDIT_PREFIX)) == backend.audit()


def test_failed_delegate_is_counted_and_local_validation_failure_is_not():
    result = DecisionResult({"present": NoulAnswer(0.9, Provenance.synthetic())}, "synthetic")
    backend = AuditedBackend(ReplayBackend({replay_key("known", QUESTIONS): result.to_dict()}))
    backend.decide("known", QUESTIONS)
    with pytest.raises(ReplayMiss):
        backend.decide("missing", QUESTIONS)
    with pytest.raises(TypeError, match="state"):
        backend.decide(None, QUESTIONS)
    assert backend.audit()["decide_calls"] == 2
    assert backend.audit()["distinct_requests"] == 2
    assert [call["returned"] for call in backend.audit()["calls"]] == [True, False]


def test_recorded_provenance_and_dates_remain_visible():
    result = DecisionResult(
        {"present": NoulAnswer(0.9, Provenance.recorded("jev-test", "2026-10-01"))},
        "jev-test",
    )
    backend = AuditedBackend(ReplayBackend({replay_key("known", QUESTIONS): result.to_dict()}))
    assert backend.mode == "recorded"
    assert backend.model == "jev-test"
    assert backend.recorded_dates == ("2026-10-01",)
    assert backend.decide("known", QUESTIONS).to_dict() == result.to_dict()
    assert "2026-10-01" in run_header_text(1, "Accounting", backend=backend, n_examples=1)


def test_image_content_is_bound_to_the_same_key_and_passed_unchanged():
    png = io.BytesIO()
    Image.new("RGB", (280, 280), "pink").save(png, format="PNG")
    assets = {
        "image-main": {
            "type": "image",
            "format": "png",
            "data_base64": base64.b64encode(png.getvalue()).decode("ascii"),
        }
    }
    received = []

    class Delegate:
        mode = "synthetic"
        model = "synthetic"

        def decide(self, state, questions, *, assets):
            received.append((state, questions, assets))
            return DecisionResult({"present": NoulAnswer(0.9, Provenance.synthetic())}, "synthetic")

    backend = AuditedBackend(Delegate())
    state = {"photo": "image-main"}
    backend.decide(state, QUESTIONS, assets=assets)
    assert received[0][0] is state and received[0][1] is QUESTIONS and received[0][2] is assets
    key = backend.audit()["calls"][0]["replay_key"]
    assert key == replay_key(state, QUESTIONS, assets=assets)
    assert key != replay_key(state, QUESTIONS)


def test_live_recorder_dynamic_attributes_and_failed_calls_without_network(tmp_path):
    class Client:
        def __init__(self):
            self.calls = []

        def system_one(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "model": "jev-1.14.0",
                "answers": {"present": {"type": "noul", "noul": 0.9}},
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }

    client = Client()
    live = LiveBackend("jev-preview", client=client, max_requests=2, today=lambda: "2026-10-01")
    backend = AuditedBackend(live)
    backend.max_retries = 0
    assert live.max_retries == 0
    assert backend.model == "jev-preview"
    path = tmp_path / "responses.json"
    ledger = tmp_path / "ledger.json"
    with backend as entered:
        assert entered is backend
        for _ in range(2):
            record(backend, [("package", QUESTIONS)], path, overwrite=True, ledger_path=ledger)
        with pytest.raises(BudgetExceeded):
            record(backend, [("package", QUESTIONS)], path, overwrite=True, ledger_path=ledger)
    assert backend.model == "jev-1.14.0"
    assert backend.requests_made == 2
    assert len(client.calls) == len(backend.records) == 2
    assert backend.audit()["decide_calls"] == 3
    assert backend.audit()["distinct_requests"] == 1
    assert [call["returned"] for call in backend.audit()["calls"]] == [True, True, False]
    assert len(json.loads(path.read_text())) == 1
    stored_ledger = json.loads(ledger.read_text())
    assert any(line["status"] == "budget_stopped" for line in stored_ledger.values())
