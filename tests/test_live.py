"""LiveBackend and the recorder, with the HTTP layer mocked: no network, no key, no SDK."""

from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

from jev_cookbook import (
    Backend,
    BudgetExceeded,
    Choice,
    ChoiceAnswer,
    DecisionResult,
    LiveBackend,
    LiveBackendUnavailable,
    LiveCallError,
    LiveConfigError,
    LiveResponseError,
    Noul,
    NoulAnswer,
    Provenance,
    RecordConflict,
    ReplayBackend,
    Score,
    ScoreAnswer,
    Usage,
    get_backend,
    merge_responses,
    record,
    replay_key,
)
from jev_cookbook.live import _dump

# A stand-in secret assembled at run time so no literal in this file looks like a credential.
SECRET = "-".join(["not", "a", "real", "key", "x" * 12])

STATE = {"document": "I was charged twice. Please fix this ASAP."}
QUESTIONS = {
    "billing": Noul(instructions="This ticket is about billing."),
    "tone": Choice(criteria={"calm": None, "angry": None}, instructions="Tone?"),
    "urgency": Score(criteria=["can wait", "today"], instructions="How urgent?"),
}
MODEL = "jev-1.13.0"
DAY = "2026-10-06"
SYN = Provenance.synthetic()


def api_body(model=MODEL, usage=None, *, noul=0.97, tone=None, urgency=None):
    """What the API sends: answers without provenance, level keys as JSON strings."""
    tone = tone or ChoiceAnswer.from_probabilities({"calm": 0.1, "angry": 0.9}, SYN)
    urgency = urgency or ScoreAnswer.from_probabilities([0.2, 0.8], ["can wait", "today"], SYN)
    answers = {
        "billing": NoulAnswer(noul, SYN).to_dict(),
        "tone": tone.to_dict(),
        "urgency": urgency.to_dict(),
    }
    for a in answers.values():
        del a["provenance"]
    return {
        "model": model,
        "usage": {"input_tokens": 120, "output_tokens": 0} if usage is None else usage,
        "answers": answers,
    }


class Resp:
    """SDK-shaped response: ``model_dump_json`` and a ``request_id`` property."""

    def __init__(self, body, request_id="req-1"):
        self._body = body
        self._rid = request_id

    def model_dump_json(self):
        return json.dumps(self._body)

    @property
    def request_id(self):
        if self._rid is None:
            raise RuntimeError("The response did not include a request ID.")
        return self._rid


class ApiError(Exception):
    def __init__(self, status, msg="boom", retry_after_ms=None):
        super().__init__(msg)
        self.status = status
        self.request_id = f"req-err-{status}"
        if retry_after_ms is not None:
            self.retry_after_ms = retry_after_ms


class FakeClient:
    """Plays a script of outcomes (responses or exceptions) and records every call."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def system_one(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0) if self.outcomes else Resp(api_body())
        if isinstance(out, BaseException):
            raise out
        return out


def make(*outcomes, **kw):
    kw.setdefault("today", lambda: DAY)
    kw.setdefault("sleep", lambda s: None)
    client = FakeClient(*outcomes)
    return LiveBackend(kw.pop("model", "jev-latest"), client=client, **kw), client


# -- protocol, provenance, shapes ------------------------------------------------------------


def test_satisfies_backend_protocol_and_mode():
    backend, _ = make()
    assert isinstance(backend, Backend)
    assert backend.mode == "live"


def test_model_is_requested_then_returned():
    backend, client = make(model="jev-latest")
    assert backend.model == "jev-latest"
    result = backend.decide(STATE, QUESTIONS)
    assert client.calls[0]["model"] == "jev-latest"  # the alias is what is sent
    assert backend.model == MODEL == result.model  # the returned ID afterwards
    assert backend.requested_model == "jev-latest"


def test_result_is_recorded_with_returned_model_and_date():
    backend, _ = make()
    result = backend.decide(STATE, QUESTIONS)
    assert result.source == "recorded"
    for a in result.answers.values():
        assert a.provenance == Provenance.recorded(MODEL, DAY)
    assert result.usage == Usage(120, 0)
    assert set(result.to_dict()) == {"model", "usage", "answers"}  # shape unchanged


def test_request_is_built_from_the_question_objects():
    backend, client = make(request_kwargs={"provider": "x"})
    backend.decide(STATE, QUESTIONS)
    call = client.calls[0]
    assert call["state"] == STATE
    assert call["provider"] == "x"
    assert call["questions"] == {
        "billing": {"type": "noul", "instructions": "This ticket is about billing."},
        "tone": {
            "type": "choice",
            "instructions": "Tone?",
            "criteria": {"calm": None, "angry": None},
        },
        "urgency": {
            "type": "score",
            "instructions": "How urgent?",
            "criteria": ["can wait", "today"],
        },
    }
    assert list(call["questions"]["tone"]["criteria"]) == ["calm", "angry"]


def test_mapping_response_with_int_level_keys_goes_through_json():
    body = api_body()
    for field in ("probabilities", "legend"):
        body["answers"]["urgency"][field] = {
            int(k): v for k, v in body["answers"]["urgency"][field].items()
        }
    backend, _ = make(body)
    assert backend.decide(STATE, QUESTIONS)["urgency"].legend[1] == "today"


def test_request_id_is_kept_beside_the_result_not_in_it():
    backend, _ = make(Resp(api_body(), "req-42"), Resp(api_body(), None))
    first = backend.decide(STATE, QUESTIONS)
    assert backend.last_request_id == "req-42"
    assert "req-42" not in json.dumps(first.to_dict())
    backend.decide(STATE, QUESTIONS)
    assert backend.request_ids == ("req-42", None)


def test_rounded_two_decimal_response_loads():
    tone = {"type": "choice", "choice": "calm", "probabilities": {"calm": 0.58, "angry": 0.42}}
    tone["confidence"] = 0.17  # true p = 0.5849 gives 0.1698
    body = api_body()
    body["answers"]["tone"] = tone
    backend, _ = make(body)
    assert backend.decide(STATE, QUESTIONS)["tone"].confidence == 0.17


@pytest.mark.parametrize(
    "mutate, field",
    [
        (lambda b: b["answers"]["tone"].update(confidence=0.99), "confidence"),
        (lambda b: b["answers"]["urgency"].update(score=0.1), "score"),
        (lambda b: b["answers"]["billing"].update(noul=1.5), "noul"),
        (
            lambda b: b["answers"]["tone"].update(probabilities={"calm": 0.5, "angry": 0.1}),
            "probabilities",
        ),
    ],
)
def test_invalid_answer_is_surfaced_naming_question_and_field(mutate, field):
    body = api_body()
    mutate(body)
    backend, _ = make(body)
    with pytest.raises(LiveResponseError) as err:
        backend.decide(STATE, QUESTIONS)
    assert field in str(err.value)
    assert "Nothing was loosened" in str(err.value)
    assert err.value.response["model"] == MODEL
    assert backend.requests_made == 1  # the call was made and counted
    assert backend.records == ()  # but nothing counts as a recorded result


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["answers"].pop("urgency"),
        lambda b: b["answers"].update(extra=b["answers"]["billing"]),
        lambda b: b["answers"].update(billing=b["answers"]["tone"]),
        lambda b: b.update(model=""),
        lambda b: b.pop("answers"),
        lambda b: b["answers"]["tone"].update(type="mystery"),
    ],
)
def test_response_that_does_not_fit_the_questions_is_an_error(mutate):
    body = api_body()
    mutate(body)
    backend, _ = make(body)
    with pytest.raises(LiveResponseError):
        backend.decide(STATE, QUESTIONS)


# -- usage -----------------------------------------------------------------------------------


def test_usage_none_and_ints_are_mapped_and_summed():
    backend, _ = make(
        Resp(api_body(usage={"input_tokens": None, "output_tokens": None})),
        Resp(api_body(usage={"input_tokens": 10, "output_tokens": None})),
        Resp(api_body(usage={"input_tokens": 5, "output_tokens": 0})),
    )
    assert backend.usage_total == Usage(None, None)
    r1 = backend.decide(STATE, QUESTIONS)
    assert r1.usage == Usage(None, None) and backend.usage_total == Usage(None, None)
    backend.decide(STATE, QUESTIONS)
    assert backend.usage_total == Usage(10, None)
    backend.decide(STATE, QUESTIONS)
    assert backend.usage_total == Usage(15, 0)
    ledger = backend.ledger()
    assert ledger["input_tokens"] == 15 and ledger["output_tokens"] == 0
    assert ledger["calls_without_usage"] == 2  # the first two did not report both counts
    assert ledger["successful_calls"] == 3


def test_usage_block_may_be_missing():
    body = api_body()
    del body["usage"]
    backend, _ = make(body)
    assert backend.decide(STATE, QUESTIONS).usage == Usage()


@pytest.mark.parametrize(
    "bad", [{"input_tokens": 1.5}, {"output_tokens": -1}, {"input_tokens": True}]
)
def test_bad_usage_is_an_error_not_a_guess(bad):
    backend, _ = make(api_body(usage=bad))
    with pytest.raises(LiveResponseError, match="usage"):
        backend.decide(STATE, QUESTIONS)


# -- budget and retries ----------------------------------------------------------------------


def test_budget_guard_stops_a_run_before_sending():
    backend, client = make(max_requests=2)
    backend.decide(STATE, QUESTIONS)
    backend.decide(STATE, QUESTIONS)
    assert (backend.requests_made, backend.requests_remaining) == (2, 0)
    with pytest.raises(BudgetExceeded, match="2 of 2"):
        backend.decide(STATE, QUESTIONS)
    assert len(client.calls) == 2  # the third was never sent
    assert backend.requests_made == 2


def test_retries_count_toward_the_budget():
    backend, client = make(ApiError(503), ApiError(503), max_requests=2, max_retries=5)
    with pytest.raises(BudgetExceeded):
        backend.decide(STATE, QUESTIONS)
    assert len(client.calls) == 2 and backend.requests_made == 2


def test_retry_then_success_with_backoff():
    sleeps = []
    backend, client = make(
        ApiError(429, retry_after_ms=2000),
        ConnectionError("down"),
        ApiError(503),
        sleep=sleeps.append,
        max_retries=3,
    )
    backend.decide(STATE, QUESTIONS)
    assert len(client.calls) == 4 and backend.requests_made == 4
    assert sleeps == [2.0, 1.0, 2.0]  # Retry-After, then 0.5 * 2 ** (attempt - 1)
    assert backend.ledger()["failed_attempts"] == 3


def test_timeout_counts_as_spent_and_exhausted_retries_raise():
    backend, client = make(TimeoutError("slow"), TimeoutError("slow"), max_retries=1)
    with pytest.raises(LiveCallError) as err:
        backend.decide(STATE, QUESTIONS)
    assert "counts as spent" in str(err.value)
    assert backend.requests_made == 2 and len(client.calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_non_retryable_status_is_not_retried(status):
    backend, client = make(ApiError(status))
    with pytest.raises(LiveCallError) as err:
        backend.decide(STATE, QUESTIONS)
    assert err.value.status == status and err.value.request_id == f"req-err-{status}"
    assert len(client.calls) == 1 and backend.requests_made == 1


def test_unknown_exception_is_wrapped_not_retried():
    backend, client = make(RuntimeError("odd"))
    with pytest.raises(LiveCallError, match="odd"):
        backend.decide(STATE, QUESTIONS)
    assert len(client.calls) == 1


def test_constructor_validation():
    for kw in ({"max_requests": 0}, {"max_requests": True}, {"max_retries": -1}):
        with pytest.raises(ValueError):
            LiveBackend("m", client=FakeClient(), **kw)
    for model in ("", " ", None):
        with pytest.raises(ValueError):
            LiveBackend(model, client=FakeClient())


# -- configuration and the key ---------------------------------------------------------------


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        "JEV_COOKBOOK_LIVE",
        "TYPESAFE_API_KEY",
        "JEV_COOKBOOK_LIVE_MODEL",
        "JEV_COOKBOOK_LIVE_MAX_REQUESTS",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class FakeSdkClient:
    def __init__(self, *, api_key=None, retry=None, **kw):
        self.api_key = api_key
        self.retry = retry
        self.closed = False
        if api_key.startswith("reject"):
            raise ValueError(f"bad key {api_key}")

    def system_one(self, **kwargs):
        raise ApiError(500, f"server echoed {self.api_key}")

    def close(self):
        self.closed = True


def install_fake_sdk(monkeypatch):
    sdk = types.ModuleType("typesafe_sdk")
    sdk.TypeSafeClient = FakeSdkClient
    sdk.RetryPolicy = lambda **kw: types.SimpleNamespace(**kw)
    monkeypatch.setitem(sys.modules, "typesafe_sdk", sdk)


def test_missing_opt_in_is_actionable(clean_env):
    clean_env.setenv("TYPESAFE_API_KEY", SECRET)
    with pytest.raises(LiveConfigError) as err:
        LiveBackend("jev-latest")
    text = str(err.value)
    assert "JEV_COOKBOOK_LIVE=1" in text and SECRET not in text
    assert isinstance(err.value, LiveBackendUnavailable)


def test_missing_key_is_actionable(clean_env):
    clean_env.setenv("JEV_COOKBOOK_LIVE", "1")
    with pytest.raises(LiveConfigError) as err:
        LiveBackend("jev-latest")
    assert "TYPESAFE_API_KEY" in str(err.value) and "JEV_COOKBOOK_LIVE=1" in str(err.value)
    clean_env.setenv("TYPESAFE_API_KEY", "   ")
    with pytest.raises(LiveConfigError, match="TYPESAFE_API_KEY"):
        LiveBackend("jev-latest")


def test_missing_sdk_names_the_extra(clean_env):
    clean_env.setenv("JEV_COOKBOOK_LIVE", "1")
    clean_env.setenv("TYPESAFE_API_KEY", SECRET)
    clean_env.setitem(sys.modules, "typesafe_sdk", None)  # makes `import typesafe_sdk` fail
    with pytest.raises(LiveConfigError) as err:
        LiveBackend("jev-latest")
    assert "jev_cookbook[live]" in str(err.value) and SECRET not in str(err.value)


def test_builds_the_sdk_client_with_retries_off_and_never_leaks_the_key(clean_env):
    clean_env.setenv("JEV_COOKBOOK_LIVE", "1")
    clean_env.setenv("TYPESAFE_API_KEY", SECRET)
    install_fake_sdk(clean_env)
    backend = LiveBackend("jev-latest", sleep=lambda s: None)
    assert backend._client.api_key == SECRET
    assert backend._client.retry.max_retries == 0  # this class owns retries
    for text in (repr(backend), str(backend), repr(backend.ledger()), repr(backend.usage_total)):
        assert SECRET not in text
    # An error from the client that echoes the key reaches the caller scrubbed.
    with pytest.raises(LiveCallError) as err:
        backend.decide(STATE, QUESTIONS)
    assert SECRET not in str(err.value) and "[redacted]" in str(err.value)
    assert err.value.__cause__ is None
    backend.close()
    assert backend._client.closed


def test_sdk_rejecting_the_key_is_scrubbed(clean_env):
    clean_env.setenv("JEV_COOKBOOK_LIVE", "1")
    clean_env.setenv("TYPESAFE_API_KEY", "reject-" + SECRET)
    install_fake_sdk(clean_env)
    with pytest.raises(LiveConfigError) as err:
        LiveBackend("jev-latest")
    assert SECRET not in str(err.value) and "TYPESAFE_API_KEY" in str(err.value)
    assert err.value.__cause__ is None


def test_injected_client_reads_no_environment(clean_env):
    backend = LiveBackend("jev-latest", client=FakeClient())  # no opt-in, no key
    assert backend.mode == "live"
    backend.close()  # an injected client is not closed


def test_get_backend_live_needs_an_explicit_model(clean_env):
    clean_env.setenv("JEV_COOKBOOK_LIVE", "1")
    clean_env.setenv("TYPESAFE_API_KEY", SECRET)
    install_fake_sdk(clean_env)
    with pytest.raises(LiveConfigError, match="JEV_COOKBOOK_LIVE_MODEL"):
        get_backend(fixtures={})
    clean_env.setenv("JEV_COOKBOOK_LIVE_MODEL", MODEL)
    clean_env.setenv("JEV_COOKBOOK_LIVE_MAX_REQUESTS", "3")
    backend = get_backend(fixtures="ignored-in-live-mode.json")
    assert isinstance(backend, LiveBackend) and backend.mode == "live"
    assert (backend.requested_model, backend.max_requests) == (MODEL, 3)
    clean_env.setenv("JEV_COOKBOOK_LIVE_MAX_REQUESTS", "zero")
    with pytest.raises(LiveConfigError, match="MAX_REQUESTS"):
        get_backend(fixtures={})


def test_importing_and_injecting_works_with_the_sdk_blocked():
    probe = r"""
import importlib.abc, os, sys

class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"typesafe", "typesafe_sdk"}:
            raise ImportError("blocked: " + name)

sys.meta_path.insert(0, Block())
import jev_cookbook
from jev_cookbook import LiveBackend, LiveConfigError

assert not any(m.startswith("typesafe") for m in sys.modules)
LiveBackend("m", client=object())  # injected: needs no SDK
os.environ["JEV_COOKBOOK_LIVE"] = "1"
os.environ["TYPESAFE_API_KEY"] = "-".join(["placeholder", "value"])
try:
    LiveBackend("m")
except LiveConfigError as exc:
    assert "jev_cookbook[live]" in str(exc)
else:
    raise SystemExit("expected LiveConfigError")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


# -- recorder --------------------------------------------------------------------------------


def two_requests():
    other = {"document": "Where is my refund?"}
    return [(STATE, QUESTIONS), (other, QUESTIONS)]


def test_recorded_fixture_replays_byte_for_byte(tmp_path):
    path = tmp_path / "fixtures" / "responses.json"
    backend, _ = make(Resp(api_body(), "r1"), Resp(api_body(noul=0.12), "r2"))
    report = record(backend, two_requests(), path)
    assert len(report.written) == 2 and report.requests == 2 and report.model == MODEL
    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text and text.endswith("}\n")
    stored = json.loads(text)
    assert list(stored) == sorted(stored)
    replay = ReplayBackend.from_json(path)
    assert (replay.mode, replay.model, replay.recorded_dates) == ("recorded", MODEL, (DAY,))
    for state, questions in two_requests():
        key = replay_key(state, questions)
        replayed = replay.decide(state, questions)
        assert json.dumps(replayed.to_dict()) == json.dumps(stored[key])  # byte for byte
    assert _dump(stored).encode("utf-8") == path.read_bytes()
    assert replay.decide(*two_requests()[1])["billing"].noul == 0.12


def test_recorded_responses_equal_the_live_results(tmp_path):
    path = tmp_path / "r.json"
    backend, _ = make()
    live = backend.decide(STATE, QUESTIONS)
    backend2, _ = make()
    record(backend2, [(STATE, QUESTIONS)], path)
    assert ReplayBackend.from_json(path).decide(STATE, QUESTIONS) == live


def test_record_merges_and_skips_existing_keys_without_calling(tmp_path):
    path = tmp_path / "r.json"
    first, _ = make()
    record(first, [two_requests()[0]], path)
    before = path.read_bytes()
    again, c2 = make()
    report = record(again, two_requests(), path)
    assert len(c2.calls) == 1  # only the new key was requested
    assert report.skipped == (replay_key(*two_requests()[0]),)
    assert len(report.written) == 1
    assert set(json.loads(path.read_text("utf-8"))) == {replay_key(*r) for r in two_requests()}
    assert path.read_bytes() != before
    none, c3 = make()
    report = record(none, two_requests(), path)
    assert c3.calls == [] and report.requests == 0 and report.written == ()


def test_overwrite_replaces_only_when_told(tmp_path):
    path = tmp_path / "r.json"
    record(make()[0], [(STATE, QUESTIONS)], path)
    key = replay_key(STATE, QUESTIONS)
    changed, client = make(Resp(api_body(noul=0.5)))
    report = record(changed, [(STATE, QUESTIONS)], path, overwrite=True)
    assert report.written == (key,) and len(client.calls) == 1
    assert json.loads(path.read_text("utf-8"))[key]["answers"]["billing"]["noul"] == 0.5
    same, _ = make(Resp(api_body(noul=0.5)))
    assert record(same, [(STATE, QUESTIONS)], path, overwrite=True).unchanged == (key,)


def test_merge_refuses_a_different_answer_for_an_existing_key(tmp_path):
    path = tmp_path / "r.json"
    backend, _ = make()
    record(backend, [(STATE, QUESTIONS)], path)
    key = replay_key(STATE, QUESTIONS)
    stored = json.loads(path.read_text("utf-8"))
    different = json.loads(json.dumps(stored[key]))
    different["answers"]["billing"]["noul"] = 0.01
    before = path.read_bytes()
    with pytest.raises(RecordConflict, match=key):
        merge_responses(path, {key: different})
    assert path.read_bytes() == before
    assert merge_responses(path, {key: stored[key]}) == ([], [key])  # identical: a no-op
    assert merge_responses(path, {key: different}, overwrite=True) == ([key], [])


def test_mixed_model_or_synthetic_file_is_refused_unchanged(tmp_path):
    path = tmp_path / "r.json"
    record(make()[0], [(STATE, QUESTIONS)], path)
    before = path.read_bytes()
    other_model, _ = make(Resp(api_body(model="jev-9.9.9")))
    with pytest.raises(RecordConflict, match="more than one model"):
        record(other_model, [two_requests()[1]], path)
    assert path.read_bytes() == before
    syn = DecisionResult({"billing": NoulAnswer(0.5, SYN)}, "synthetic").to_dict()
    with pytest.raises(RecordConflict, match="mix"):
        merge_responses(path, {"a" * 64: syn})
    assert path.read_bytes() == before


def test_failure_mid_run_keeps_what_was_already_recorded(tmp_path):
    path = tmp_path / "r.json"
    backend, _ = make(Resp(api_body()), ApiError(400, "bad"))
    with pytest.raises(LiveCallError):
        record(backend, two_requests(), path)
    assert set(json.loads(path.read_text("utf-8"))) == {replay_key(*two_requests()[0])}
    assert ReplayBackend.from_json(path).model == MODEL


def test_budget_stops_the_recorder_and_keeps_earlier_responses(tmp_path):
    path = tmp_path / "r.json"
    backend, client = make(max_requests=1)
    with pytest.raises(BudgetExceeded):
        record(backend, two_requests(), path)
    assert len(client.calls) == 1 and len(json.loads(path.read_text("utf-8"))) == 1


def test_record_surfaces_an_invalid_answer_and_writes_nothing_for_it(tmp_path):
    path = tmp_path / "r.json"
    bad = api_body()
    bad["answers"]["tone"]["confidence"] = 0.99
    backend, _ = make(bad)
    with pytest.raises(LiveResponseError, match="'tone'.*confidence"):
        record(backend, [(STATE, QUESTIONS)], path)
    assert not path.exists()


def test_record_writes_an_optional_request_id_sidecar(tmp_path):
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    backend, _ = make(Resp(api_body(usage={"input_tokens": 7, "output_tokens": None}), "req-9"))
    report = record(backend, [(STATE, QUESTIONS)], path, ledger_path=ledger)
    key = replay_key(STATE, QUESTIONS)
    assert report.ledger_path == ledger
    assert json.loads(ledger.read_text("utf-8")) == {
        key: {
            "request_id": "req-9",
            "model": MODEL,
            "date": DAY,
            "input_tokens": 7,
            "output_tokens": None,
        }
    }
    assert "req-9" not in path.read_text("utf-8")  # the stored-response shape is untouched
    plain, _ = make()
    assert record(plain, [(STATE, QUESTIONS)], tmp_path / "other.json").ledger_path is None


def test_recorder_output_never_contains_the_key(tmp_path, clean_env):
    clean_env.setenv("JEV_COOKBOOK_LIVE", "1")
    clean_env.setenv("TYPESAFE_API_KEY", SECRET)
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    backend, _ = make()
    record(backend, [(STATE, QUESTIONS)], path, ledger_path=ledger)
    for p in (path, ledger):
        assert SECRET not in p.read_text("utf-8")
    assert not list(tmp_path.glob(".responses-*"))  # no temp files left behind


def test_duplicate_requests_in_one_run_are_sent_once(tmp_path):
    backend, client = make()
    report = record(backend, [(STATE, QUESTIONS), (STATE, QUESTIONS)], tmp_path / "r.json")
    assert len(client.calls) == 1 and len(report.written) == 1
