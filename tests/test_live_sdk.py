"""LiveBackend against the real ``typesafe_sdk`` types, with a mock HTTP transport.

These tests need the optional SDK (``pip install -e ".[live]"``); without it the module is
not collected. The offline contract (no SDK needed) is covered in ``test_live.py``. No
request leaves the process: the SDK's transport is replaced by ``httpx2.MockTransport``.
"""

from __future__ import annotations

import json

import pytest

sdk = pytest.importorskip("typesafe_sdk")
httpx2 = pytest.importorskip("httpx2")

from jev_cookbook import Choice, LiveBackend, Noul, Score  # noqa: E402

KEY = "-".join(["placeholder", "credential", "y" * 10])
BODY = {
    "model": "jev-1.13.0",
    "usage": {"input_tokens": 5, "output_tokens": None},
    "answers": {
        "billing": {"type": "noul", "noul": 0.9},
        "tone": {
            "type": "choice",
            "choice": "angry",
            "probabilities": {"calm": 0.1, "angry": 0.9},
            "confidence": 0.8,
        },
        "urgency": {
            "type": "score",
            "score": 0.8,
            "confidence": 0.6,
            "probabilities": {"0": 0.2, "1": 0.8},
            "legend": {"0": "can wait", "1": {"label": "today"}},
        },
    },
}
QUESTIONS = {
    "billing": Noul(instructions="This ticket is about billing."),
    "tone": Choice(criteria={"calm": None, "angry": "shouting"}),
    "urgency": Score(criteria=["can wait", "today"]),
}


def client_with(handler):
    return sdk.TypeSafeClient(
        api_key=KEY,
        transport=httpx2.MockTransport(handler),
        retry=sdk.RetryPolicy(max_retries=0),
    )


def test_real_client_over_mock_transport():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(200, json=BODY, headers={"x-typesafe-request-id": "req-77"})

    backend = LiveBackend("jev-latest", client=client_with(handler))
    result = backend.decide("I was charged twice.", QUESTIONS)
    assert len(seen) == 1
    sent = json.loads(seen[0].content)
    assert sent["model"] == "jev-latest" and sent["state"] == "I was charged twice."
    assert list(sent["questions"]["tone"]["criteria"]) == ["calm", "angry"]
    assert sent["questions"]["billing"] == {
        "type": "noul",
        "instructions": "This ticket is about billing.",
    }
    assert result.model == "jev-1.13.0" and result.usage.input_tokens == 5
    assert result["urgency"].legend[1] == {"label": "today"}
    assert result["tone"].provenance.source == "recorded"
    assert backend.last_request_id == "req-77"
    assert backend.model == "jev-1.13.0"


def test_sdk_response_without_request_id_header():
    backend = LiveBackend(
        "jev-latest", client=client_with(lambda request: httpx2.Response(200, json=BODY))
    )
    backend.decide("x", QUESTIONS)
    assert backend.last_request_id is None


def test_sdk_http_errors_are_classified_and_each_attempt_counted():
    calls = []

    def handler(request):
        calls.append(request)
        status = 503 if len(calls) < 3 else 200
        return httpx2.Response(status, json=BODY if status == 200 else {"error": "busy"})

    backend = LiveBackend("m", client=client_with(handler), sleep=lambda s: None, max_retries=2)
    backend.decide("x", QUESTIONS)
    assert backend.requests_made == 3 and len(calls) == 3


def test_sdk_timeout_is_retryable_and_counted():
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx2.ReadTimeout("slow", request=request)
        return httpx2.Response(200, json=BODY)

    backend = LiveBackend("m", client=client_with(handler), sleep=lambda s: None)
    backend.decide("x", QUESTIONS)
    assert backend.requests_made == 2


def test_authentication_error_does_not_echo_the_key():
    def handler(request):
        return httpx2.Response(401, json={"error": "unauthorized"})

    backend = LiveBackend("m", client=client_with(handler))
    with pytest.raises(Exception) as err:
        backend.decide("x", QUESTIONS)
    assert err.value.status == 401 and "TYPESAFE_API_KEY" in str(err.value)
    assert KEY not in str(err.value) and KEY not in repr(backend)
