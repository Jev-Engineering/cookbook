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


# -- fix round 1: the key, the budget and rejected 200s, over the real SDK --------------------

import traceback  # noqa: E402

from jev_cookbook import BudgetExceeded, LiveCallError, LiveResponseError  # noqa: E402

PADDED_KEYS = [KEY + "\r", "  " + KEY + " \r\n", KEY]


def chain_text(exc, *extra):
    """str, repr, args and the formatted traceback of the whole __cause__/__context__ chain."""
    seen, texts, stack = set(), list(extra), [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        texts += [str(e), repr(e), repr(e.args)]
        stack += [e.__cause__, e.__context__]
    texts.append("".join(traceback.format_exception(exc)))
    return "\n".join(texts), len(seen)


@pytest.fixture
def env_backend(monkeypatch):
    """A backend that builds its own SDK client from the environment, over a mock transport."""

    def build(raw_key, handler, **kw):
        monkeypatch.setenv("JEV_COOKBOOK_LIVE", "1")
        monkeypatch.setenv("TYPESAFE_API_KEY", raw_key)
        monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
        real = sdk.TypeSafeClient
        monkeypatch.setattr(
            sdk,
            "TypeSafeClient",
            lambda **ckw: real(transport=httpx2.MockTransport(handler), **ckw),
        )
        backend = LiveBackend("m", sleep=lambda s: None, **kw)
        built.append(backend)
        return backend

    built = []
    yield build
    for backend in built:
        backend.close()


def echo(request):
    return request.headers["authorization"]  # the key exactly as the SDK sent it


FAILURES = {
    "401": lambda request: httpx2.Response(401, json={"error": f"invalid key {echo(request)}"}),
    "429": lambda request: httpx2.Response(429, json={"error": f"slow down {echo(request)}"}),
    "500": lambda request: httpx2.Response(500, text=f"oops {echo(request)}"),
    "transport": lambda request: (_ for _ in ()).throw(
        httpx2.ConnectError(f"cannot connect with {echo(request)}", request=request)
    ),
}


@pytest.mark.parametrize("raw_key", PADDED_KEYS)
@pytest.mark.parametrize("kind", list(FAILURES))
def test_the_key_in_any_variant_never_appears_after_a_failure(env_backend, raw_key, kind):
    backend = env_backend(raw_key, FAILURES[kind], max_retries=0)
    with pytest.raises(LiveCallError) as err:
        backend.decide("x", QUESTIONS)
    text, chain_len = chain_text(
        err.value, repr(backend), str(backend), repr(backend.ledger()), repr(backend.records)
    )
    for variant in {raw_key, raw_key.strip(), KEY}:
        assert variant not in text
    assert chain_len == 1  # neither __cause__ nor __context__ carries the SDK exception
    assert err.value.__cause__ is None and err.value.__context__ is None


def test_the_echoing_server_really_sees_the_key_the_sdk_sent(env_backend):
    sent = []

    def handler(request):
        sent.append(echo(request))
        return FAILURES["401"](request)

    with pytest.raises(LiveCallError, match="redacted"):
        env_backend(KEY + "\r", handler).decide("x", QUESTIONS)
    assert sent == ["Bearer " + KEY]  # trimmed on the wire, so the raw value alone would not match


@pytest.mark.parametrize(
    "make_handler",
    [
        lambda seen: lambda request: (seen.append(1), httpx2.Response(500, json={"e": "x"}))[1],
        lambda seen: (
            lambda request: (
                seen.append(1),
                (_ for _ in ()).throw(httpx2.ReadTimeout("slow", request=request)),
            )[1]
        ),
        lambda seen: (
            lambda request: (
                seen.append(1),
                (_ for _ in ()).throw(httpx2.ConnectError("down", request=request)),
            )[1]
        ),
    ],
    ids=["500", "timeout", "transport"],
)
@pytest.mark.parametrize("budget", [1, 3])
def test_exactly_max_requests_http_requests_are_ever_sent(make_handler, budget):
    seen = []
    # A client whose own policy retries four times: the backend must override it per call.
    client = sdk.TypeSafeClient(
        api_key=KEY,
        transport=httpx2.MockTransport(make_handler(seen)),
        retry=sdk.RetryPolicy(max_retries=4, backoff_initial=0, backoff_max=0),
    )
    backend = LiveBackend(
        "m", client=client, max_requests=budget, max_retries=9, sleep=lambda s: None
    )
    with pytest.raises(BudgetExceeded):
        backend.decide("x", QUESTIONS)
    assert len(seen) == budget == backend.requests_made


def test_an_env_built_backend_sends_exactly_max_requests(env_backend):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(500, json={"e": "x"})

    backend = env_backend(KEY, handler, max_requests=2, max_retries=9)
    with pytest.raises(BudgetExceeded):
        backend.decide("x", QUESTIONS)
    assert len(seen) == 2


@pytest.mark.parametrize("name", ["retry", "extra_body"])
def test_retry_and_extra_body_cannot_be_passed_through(name):
    value = {"model": "other"} if name == "extra_body" else sdk.RetryPolicy(max_retries=4)
    with pytest.raises(ValueError, match=name):
        LiveBackend(
            "m", client=client_with(lambda r: httpx2.Response(500)), request_kwargs={name: value}
        )


def test_a_200_the_sdk_rejects_keeps_the_scrubbed_body(env_backend):
    def handler(request):
        return httpx2.Response(200, json={"model": "jev-1.13.0", "echo": echo(request)})

    backend = env_backend(KEY + "\r", handler)
    with pytest.raises(LiveResponseError) as err:
        backend.decide("x", QUESTIONS)
    assert not isinstance(err.value, LiveCallError)
    assert err.value.response == {"model": "jev-1.13.0", "echo": "Bearer [redacted]"}
    assert "invalid or missing field 'usage'" in str(err.value)
    assert KEY not in chain_text(err.value)[0]
    assert backend.requests_made == 1 and backend.ledger()["failed_attempts"] == 1


def test_a_200_that_is_not_json_is_a_response_error(env_backend):
    backend = env_backend(KEY, lambda request: httpx2.Response(200, text=f"hi {echo(request)}"))
    with pytest.raises(LiveResponseError) as err:
        backend.decide("x", QUESTIONS)
    assert err.value.response is None and "hi Bearer [redacted]" in str(err.value)
    assert KEY not in chain_text(err.value)[0]


# -- fix round 2: the SDK's DEBUG log, a 200 that echoes the key, the failed-call ledger ------

import logging  # noqa: E402

from jev_cookbook import record  # noqa: E402


@pytest.fixture
def sdk_log():
    """Everything the SDK logs at DEBUG, formatted the way a handler would show it."""
    logger = logging.getLogger("typesafe_sdk")
    lines = []

    class Capture(logging.Handler):
        def emit(self, rec):
            lines.append(self.format(rec))
            lines.append(repr(rec.args))  # a handler that reads args directly

    handler = Capture()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    previous = logger.level
    logger.setLevel(logging.DEBUG)  # setLevel, not an attribute: it clears the enabled-for cache
    logger.addHandler(handler)
    yield lines
    logger.removeHandler(handler)
    logger.setLevel(previous)


@pytest.mark.parametrize("raw_key", PADDED_KEYS + ["\t" + KEY])
@pytest.mark.parametrize("kind", ["401", "429", "500"])
@pytest.mark.parametrize("retries", [0, 2])
def test_debug_log_never_contains_the_key_for_error_bodies(
    env_backend, sdk_log, raw_key, kind, retries
):
    backend = env_backend(raw_key, FAILURES[kind], max_retries=retries)
    with pytest.raises(LiveCallError):
        backend.decide("x", QUESTIONS)
    text = "\n".join(sdk_log)
    assert "<-" in text and "[redacted]" in text  # the log is still readable
    for variant in {raw_key, raw_key.strip(), KEY}:
        assert variant not in text
    assert "authorization" not in text.lower() or "'authorization': '***'" in text.lower()


def test_debug_log_keeps_its_non_secret_parts(env_backend, sdk_log):
    backend = env_backend(KEY, FAILURES["500"], max_retries=0)
    with pytest.raises(LiveCallError):
        backend.decide("x", QUESTIONS)
    text = "\n".join(sdk_log)
    assert "POST" in text and "oops Bearer [redacted]" in text


def test_the_log_filter_follows_the_backend_that_built_the_client(env_backend):
    from jev_cookbook import live

    logger = logging.getLogger("typesafe_sdk")
    baseline = dict(live._LOG_FILTER._counts)  # other tests may have left backends open
    first = env_backend(KEY, FAILURES["500"])
    second = LiveBackend("m")  # same environment, same patched SDK
    assert logger.filters.count(live._LOG_FILTER) == 1  # idempotent: one filter, however many
    first.close()
    assert live._LOG_FILTER in logger.filters  # the second backend is still protected
    assert KEY in live._LOG_FILTER._counts
    second.close()
    second.close()  # closing twice releases nothing twice
    assert live._LOG_FILTER._counts == baseline
    assert (live._LOG_FILTER in logger.filters) == bool(baseline)


def test_an_injected_client_gets_no_log_filter():
    logger = logging.getLogger("typesafe_sdk")
    from jev_cookbook import live

    before = (list(logger.filters), dict(live._LOG_FILTER._counts))
    LiveBackend("m", client=client_with(lambda r: httpx2.Response(500)))
    assert (list(logger.filters), dict(live._LOG_FILTER._counts)) == before  # caller's job


def test_a_200_body_echoing_the_key_is_refused_before_any_write(env_backend, tmp_path):
    def handler(request):
        return httpx2.Response(200, json={**BODY, "model": echo(request)})

    backend = env_backend(KEY + "\r", handler)
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    with pytest.raises(LiveResponseError) as err:
        record(backend, [("x", QUESTIONS)], path, ledger_path=ledger)
    assert KEY not in chain_text(err.value, repr(backend), repr(backend.ledger()))[0]
    assert not path.exists() and KEY not in ledger.read_text("utf-8")
    assert backend.model == "m"


def test_a_failed_validation_over_the_real_sdk_is_in_the_sidecar_with_its_request_id(
    env_backend, tmp_path
):
    bad = json.loads(json.dumps(BODY))
    bad["answers"]["tone"]["confidence"] = 0.99

    def handler(request):
        return httpx2.Response(200, json=bad, headers={"x-typesafe-request-id": "req-paid"})

    backend = env_backend(KEY, handler)
    ledger = tmp_path / "ledger.json"
    with pytest.raises(LiveResponseError) as err:
        record(backend, [("x", QUESTIONS)], tmp_path / "r.json", ledger_path=ledger)
    assert err.value.request_id == "req-paid"
    (line,) = json.loads(ledger.read_text("utf-8")).values()
    assert line["status"] == "invalid_response" and line["request_id"] == "req-paid"


def test_an_http_error_over_the_real_sdk_is_in_the_sidecar(env_backend, tmp_path):
    def handler(request):
        return httpx2.Response(
            429, json={"error": "slow"}, headers={"x-typesafe-request-id": "req-429"}
        )

    backend = env_backend(KEY, handler, max_retries=1)
    ledger = tmp_path / "ledger.json"
    with pytest.raises(LiveCallError):
        record(backend, [("x", QUESTIONS)], tmp_path / "r.json", ledger_path=ledger)
    (line,) = json.loads(ledger.read_text("utf-8")).values()
    assert (line["status"], line["http_status"], line["attempts"]) == ("error", 429, 2)
    assert line["request_id"] == "req-429"
