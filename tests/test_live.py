"""LiveBackend and the recorder, with the HTTP layer mocked: no network, no key, no SDK."""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
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
        "TYPESAFE_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class FakeSdkClient:
    def __init__(self, *, api_key=None, retry=None, **kw):
        self.api_key = api_key
        self.kw = kw
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
            "status": "recorded",
            "request_id": "req-9",
            "model": MODEL,
            "date": DAY,
            "input_tokens": 7,
            "output_tokens": None,
            "attempts": 1,
            "retried": [],
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


# -- fix round 1: key scrubbing, request kwargs, ledger after a partial run -----------------

PADDED = ["  " + SECRET + " \r\n", SECRET + "\r", SECRET]


def everything_said_about(exc, *extra):
    """Every string a caller could print: str, repr, args and the formatted chain."""
    seen, texts, e = set(), list(extra), exc
    stack = [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        texts += [str(e), repr(e), repr(e.args)]
        stack += [e.__cause__, e.__context__]
    texts.append("".join(traceback.format_exception(exc)))
    return "\n".join(texts), seen


@pytest.mark.parametrize("raw", PADDED)
def test_key_variants_never_reach_messages_tracebacks_or_the_ledger(clean_env, raw):
    clean_env.setenv("JEV_COOKBOOK_LIVE", "1")
    clean_env.setenv("TYPESAFE_API_KEY", raw)
    install_fake_sdk(clean_env)
    backend = LiveBackend("jev-latest", sleep=lambda s: None, max_retries=0)
    with pytest.raises(LiveCallError) as err:
        backend.decide(STATE, QUESTIONS)  # the fake SDK echoes the trimmed key it was given
    text, chain = everything_said_about(
        err.value, repr(backend), repr(backend.ledger()), repr(backend.records)
    )
    assert SECRET not in text and raw not in text and "[redacted]" in text
    assert err.value.__cause__ is None and err.value.__context__ is None
    assert len(chain) == 1  # the SDK exception is nowhere on the chain


def test_base_url_other_than_the_official_host_is_refused(clean_env):
    clean_env.setenv("JEV_COOKBOOK_LIVE", "1")
    clean_env.setenv("TYPESAFE_API_KEY", SECRET)
    install_fake_sdk(clean_env)
    clean_env.setenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai.evil.example")
    with pytest.raises(LiveConfigError, match="TYPESAFE_BASE_URL") as err:
        LiveBackend("jev-latest")
    assert SECRET not in str(err.value)
    for ok in ("https://api.typesafe.ai", "https://API.typesafe.ai/", "  "):
        clean_env.setenv("TYPESAFE_BASE_URL", ok)
        backend = LiveBackend("jev-latest")
        # the host is also passed explicitly, so the SDK never consults the variable
        assert backend._client.kw["base_url"] == "https://api.typesafe.ai"


@pytest.mark.parametrize(
    "name",
    ["retry", "extra_body", "extra_headers", "state", "questions", "model", "response_model"],
)
def test_request_kwargs_that_change_what_is_sent_are_rejected(name):
    with pytest.raises(ValueError, match=name):
        LiveBackend("m", client=FakeClient(), request_kwargs={name: object()})


def test_allowed_request_kwargs_are_forwarded():
    backend, client = make(request_kwargs={"provider": "openai", "timeout": 5})
    backend.decide(STATE, QUESTIONS)
    assert client.calls[0]["provider"] == "openai" and client.calls[0]["timeout"] == 5
    assert "retry" not in client.calls[0]  # a client without a retry parameter gets none


class ValidationError(Exception):
    """Shaped like typesafe_sdk's TypeSafeAPIResponseValidationError (duck typing)."""

    def __init__(self, body, field_path="answers"):
        super().__init__(200, body, field_path)
        self.status, self.body, self.field_path = 200, body, field_path


def test_a_200_the_sdk_rejects_is_a_response_error_with_the_scrubbed_body(clean_env):
    clean_env.setenv("TYPESAFE_API_KEY", " " + SECRET + "\r")
    body = {"model": MODEL, "echo": f"saw {SECRET}", SECRET: 1, "rows": [SECRET]}
    backend, _ = make(ValidationError(body))
    with pytest.raises(LiveResponseError, match="answers") as err:
        backend.decide(STATE, QUESTIONS)
    assert err.value.response == {
        "model": MODEL,
        "echo": "saw [redacted]",
        "[redacted]": 1,
        "rows": ["[redacted]"],
    }
    assert not isinstance(err.value, LiveCallError)
    assert SECRET not in everything_said_about(err.value)[0]
    assert backend.requests_made == 1 and backend.ledger()["failed_attempts"] == 1


def test_a_200_with_a_text_body_has_no_parsed_response():
    backend, _ = make(ValidationError("<html>nope</html>", "$"))
    with pytest.raises(LiveResponseError, match="nope") as err:
        backend.decide(STATE, QUESTIONS)
    assert err.value.response is None


def test_failure_on_the_second_call_leaves_a_ledger_with_the_first_request_id(tmp_path):
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    backend, _ = make(Resp(api_body(), "req-paid"), ApiError(400, "bad"))
    with pytest.raises(LiveCallError):
        record(backend, two_requests(), path, ledger_path=ledger)
    first = replay_key(*two_requests()[0])
    assert set(json.loads(path.read_text("utf-8"))) == {first}
    side = json.loads(ledger.read_text("utf-8"))
    second = replay_key(*two_requests()[1])
    assert set(side) == {first, second + "!failed-1"}
    assert side[first]["request_id"] == "req-paid" and side[first]["status"] == "recorded"
    assert side[second + "!failed-1"] == {
        "status": "error",
        "error_type": "ApiError",
        "http_status": 400,
        "request_id": "req-err-400",
        "model": "jev-latest",
        "date": DAY,
        "attempts": 1,
        "retried": [],
    }
    assert backend.ledger()["request_ids"] == ["req-paid"]
    assert not list(tmp_path.glob(".responses-*"))


def test_budget_exhaustion_leaves_the_ledger_consistent(tmp_path):
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    backend, _ = make(Resp(api_body(), "req-1"), max_requests=1)
    with pytest.raises(BudgetExceeded):
        record(backend, two_requests(), path, ledger_path=ledger)
    side = json.loads(ledger.read_text("utf-8"))
    second = replay_key(*two_requests()[1])
    assert set(side) == set(json.loads(path.read_text("utf-8"))) | {second + "!failed-1"}
    stopped = side[second + "!failed-1"]
    assert stopped["status"] == "budget_stopped" and stopped["attempts"] == 0
    assert stopped["request_id"] is None


def test_ledger_entry_is_kept_even_when_the_merge_fails(tmp_path):
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    backend, _ = make(Resp(api_body("jev-1.13.0"), "r1"), Resp(api_body("jev-1.14.0"), "r2"))
    with pytest.raises(RecordConflict):
        record(backend, two_requests(), path, ledger_path=ledger)
    assert {v["request_id"] for v in json.loads(ledger.read_text("utf-8")).values()} == {"r1", "r2"}


def test_a_paid_response_from_a_moved_alias_is_kept_in_a_side_file(tmp_path):
    path = tmp_path / "responses.json"
    backend, _ = make(Resp(api_body("jev-1.13.0"), "r1"), Resp(api_body("jev-1.14.0"), "r2"))
    with pytest.raises(RecordConflict, match="more than one model|kept in") as err:
        record(backend, two_requests(), path)
    second = replay_key(*two_requests()[1])
    side = tmp_path / "responses.drift-jev-1.14.0.json"
    assert err.value.saved_to == side and err.value.result.model == "jev-1.14.0"
    assert set(json.loads(side.read_text("utf-8"))) == {second}
    assert ReplayBackend.from_json(side).model == "jev-1.14.0"
    assert ReplayBackend.from_json(path).model == "jev-1.13.0"  # the main file is untouched
    assert set(json.loads(path.read_text("utf-8"))) == {replay_key(*two_requests()[0])}
    assert not (tmp_path / "responses-jev-1.14.0.json").exists()  # not a fixture-shaped name
    assert "drift" in str(err.value)


# -- fix round 2: every paid call has a ledger line; the key never reaches a fixture ----------


def sidecar_after(tmp_path, backend, requests=None):
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    with pytest.raises(Exception) as err:
        record(backend, requests or [(STATE, QUESTIONS)], path, ledger_path=ledger)
    return err.value, json.loads(ledger.read_text("utf-8")), path


def test_validation_failure_puts_the_request_id_on_the_error_and_in_the_sidecar(tmp_path):
    bad = api_body()
    bad["answers"]["tone"]["confidence"] = 0.99
    backend, _ = make(Resp(bad, "req-bad"))
    exc, side, path = sidecar_after(tmp_path, backend)
    assert isinstance(exc, LiveResponseError) and exc.request_id == "req-bad"
    line = side[replay_key(STATE, QUESTIONS) + "!failed-1"]
    assert line["status"] == "invalid_response" and line["request_id"] == "req-bad"
    assert line["error_type"] == "LiveResponseError" and line["attempts"] == 1
    assert not path.exists()


def test_validation_failure_after_a_success_keeps_both_ledger_lines(tmp_path):
    bad = api_body()
    bad["answers"]["tone"]["confidence"] = 0.99
    backend, _ = make(Resp(api_body(), "req-1"), Resp(bad, "req-2"))
    exc, side, path = sidecar_after(tmp_path, backend, two_requests())
    assert exc.request_id == "req-2"
    assert {v["request_id"] for v in side.values()} == {"req-1", "req-2"}
    assert len(side) == 2 and len(json.loads(path.read_text("utf-8"))) == 1


def test_sdk_style_validation_error_carries_its_request_id(tmp_path):
    err = ValidationError({"model": MODEL}, "usage")
    err.request_id = "req-v"
    backend, _ = make(err)
    exc, side, _ = sidecar_after(tmp_path, backend)
    assert exc.request_id == "req-v"
    assert list(side.values())[0]["request_id"] == "req-v"


def test_http_error_is_in_the_sidecar_with_its_status_and_request_id(tmp_path):
    backend, _ = make(ApiError(429, "slow"), max_retries=0)
    exc, side, _ = sidecar_after(tmp_path, backend)
    assert isinstance(exc, LiveCallError) and exc.request_id == "req-err-429"
    line = side[replay_key(STATE, QUESTIONS) + "!failed-1"]
    assert (line["status"], line["http_status"]) == ("error", 429)
    assert line["request_id"] == "req-err-429"


def test_a_retried_call_is_one_ledger_line_counting_its_attempts(tmp_path):
    backend, _ = make(ApiError(500), ApiError(500), ApiError(500), max_retries=2)
    _, side, _ = sidecar_after(tmp_path, backend)
    assert list(side.values())[0]["attempts"] == 3 == backend.requests_made


def test_timeout_is_in_the_sidecar_without_a_request_id(tmp_path):
    backend, _ = make(TimeoutError("slow"), max_retries=0)
    exc, side, _ = sidecar_after(tmp_path, backend)
    assert isinstance(exc, LiveCallError) and exc.request_id is None
    line = side[replay_key(STATE, QUESTIONS) + "!failed-1"]
    assert line["status"] == "timeout" and line["request_id"] is None
    assert line["http_status"] is None and line["attempts"] == 1


def test_budget_stop_is_in_the_sidecar(tmp_path):
    backend, _ = make(max_requests=1)
    backend.decide(*two_requests()[0])
    exc, side, _ = sidecar_after(tmp_path, backend, two_requests()[1:])
    assert isinstance(exc, BudgetExceeded)
    assert list(side.values())[0]["status"] == "budget_stopped"


def test_two_failures_for_one_key_do_not_overwrite_each_other(tmp_path):
    ledger = tmp_path / "ledger.json"
    for _ in range(2):
        backend, _ = make(ApiError(400), max_retries=0)
        with pytest.raises(LiveCallError):
            record(backend, [(STATE, QUESTIONS)], tmp_path / "r.json", ledger_path=ledger)
    key = replay_key(STATE, QUESTIONS)
    assert set(json.loads(ledger.read_text("utf-8"))) == {key + "!failed-1", key + "!failed-2"}


def test_a_failed_call_needs_no_ledger_path_and_the_error_still_propagates(tmp_path):
    backend, _ = make(ApiError(400), max_retries=0)
    with pytest.raises(LiveCallError):
        record(backend, [(STATE, QUESTIONS)], tmp_path / "r.json")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("where", ["fixtures", "recipes/01/fixtures", "fixtures/sub", "Fixtures"])
def test_a_ledger_inside_a_fixtures_directory_is_refused_before_any_call(tmp_path, where):
    backend, client = make()
    with pytest.raises(ValueError, match="fixtures/"):
        record(
            backend,
            [(STATE, QUESTIONS)],
            tmp_path / "r.json",
            ledger_path=tmp_path / where / "ledger.json",
        )
    assert client.calls == [] and backend.requests_made == 0
    assert not (tmp_path / where).exists()


def test_a_ledger_beside_but_not_inside_fixtures_is_accepted(tmp_path):
    backend, _ = make()
    report = record(
        backend,
        [(STATE, QUESTIONS)],
        tmp_path / "fixtures" / "responses.json",
        ledger_path=tmp_path / "ledger.json",
    )
    assert report.ledger_path == tmp_path / "ledger.json"


def test_a_200_that_echoes_the_key_is_refused_and_nothing_is_written(tmp_path, clean_env):
    clean_env.setenv("TYPESAFE_API_KEY", " " + SECRET + "\r")
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    backend, _ = make(Resp(api_body(model=f"jev-{SECRET}"), "req-echo"))
    with pytest.raises(LiveResponseError) as err:
        record(backend, [(STATE, QUESTIONS)], path, ledger_path=ledger)
    assert SECRET not in everything_said_about(err.value, repr(backend), repr(backend.ledger()))[0]
    assert err.value.request_id == "req-echo"
    assert not path.exists() and backend.records == ()
    assert backend.model == "jev-latest"  # the echoed string never became the model
    assert SECRET not in ledger.read_text("utf-8")
    assert list(json.loads(ledger.read_text("utf-8")).values())[0]["status"] == "invalid_response"


def test_a_response_with_the_key_is_counted_as_a_failed_attempt(clean_env):
    clean_env.setenv("TYPESAFE_API_KEY", SECRET)
    backend, _ = make(Resp(api_body(model=SECRET), "r"))
    with pytest.raises(LiveResponseError, match="API key"):
        backend.decide(STATE, QUESTIONS)
    assert backend.ledger()["failed_attempts"] == 1


def test_a_clean_response_is_unaffected_by_the_key_scan(clean_env):
    clean_env.setenv("TYPESAFE_API_KEY", SECRET)
    backend, _ = make(Resp(api_body(), "r"))
    assert backend.decide(STATE, QUESTIONS).model == MODEL


# -- fix round 3: retried attempts are on disk; history survives; the sidecar is its own file ---


def doc(n):
    return [({"document": f"ticket {n}"}, QUESTIONS)]


def test_sidecar_attempts_add_up_to_requests_made_and_keep_retried_request_ids(tmp_path):
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    backend, _ = make(
        Resp(api_body(), "req-a"),  # A: one attempt
        TimeoutError("slow"),  # B: timeout, 500, then a 200
        ApiError(500),
        Resp(api_body(), "req-b"),
        ApiError(400),  # C: fails at once
        ApiError(503),  # D: retried until the budget stops it
        ApiError(503),
        max_requests=7,
        max_retries=2,
    )
    record(backend, doc(1), path, ledger_path=ledger)
    record(backend, doc(2), path, ledger_path=ledger)
    with pytest.raises(LiveCallError):
        record(backend, doc(3), path, ledger_path=ledger)
    with pytest.raises(BudgetExceeded):
        record(backend, doc(4), path, ledger_path=ledger)
    side = json.loads(ledger.read_text("utf-8"))
    keys = [replay_key(*doc(n)[0]) for n in (1, 2, 3, 4)]
    assert sorted(side) == sorted([keys[0], keys[1], keys[2] + "!failed-1", keys[3] + "!failed-1"])
    assert sum(v["attempts"] for v in side.values()) == backend.ledger()["requests_made"] == 7
    assert [side[k]["attempts"] for k in (keys[0], keys[1])] == [1, 3]
    assert side[keys[1]]["request_id"] == "req-b"
    assert side[keys[1]]["retried"] == [
        {"error_type": "TimeoutError", "http_status": None, "request_id": None},
        {"error_type": "ApiError", "http_status": 500, "request_id": "req-err-500"},
    ]
    assert side[keys[0]]["retried"] == [] and side[keys[2] + "!failed-1"]["retried"] == []
    stopped = side[keys[3] + "!failed-1"]
    assert stopped["status"] == "budget_stopped" and stopped["attempts"] == 2
    assert [r["request_id"] for r in stopped["retried"]] == ["req-err-503", "req-err-503"]
    assert "req-err-500" in ledger.read_text("utf-8")


def test_a_failed_call_after_retries_lists_them_on_the_failed_line(tmp_path):
    backend, _ = make(ApiError(502), ApiError(400), max_retries=2)
    _, side, _ = sidecar_after(tmp_path, backend)
    line = list(side.values())[0]
    assert line["attempts"] == 2 and line["http_status"] == 400
    assert line["retried"] == [
        {"error_type": "ApiError", "http_status": 502, "request_id": "req-err-502"}
    ]


def test_retried_entries_are_scrubbed(tmp_path, clean_env):
    clean_env.setenv("TYPESAFE_API_KEY", SECRET)
    err = ApiError(500)
    err.request_id = f"id-{SECRET}"
    backend, _ = make(err, Resp(api_body(), "r"), max_retries=1)
    record(backend, doc(1), tmp_path / "r.json", ledger_path=tmp_path / "l.json")
    text = (tmp_path / "l.json").read_text("utf-8")
    assert SECRET not in text and "[redacted]" in text


def test_overwrite_keeps_the_earlier_sidecar_entry_as_history(tmp_path):
    path, ledger = tmp_path / "r.json", tmp_path / "ledger.json"
    backend, _ = make(
        Resp(api_body(), "req-old"), Resp(api_body(), "req-mid"), Resp(api_body(), "req-new")
    )
    for _ in range(3):
        record(backend, doc(1), path, ledger_path=ledger, overwrite=True)
    line = json.loads(ledger.read_text("utf-8"))[replay_key(*doc(1)[0])]
    assert line["request_id"] == "req-new"
    assert [h["request_id"] for h in line["superseded"]] == ["req-old", "req-mid"]
    assert all("superseded" not in h for h in line["superseded"])
    assert (
        "superseded"
        not in json.loads(ledger.read_text("utf-8"))[replay_key(*doc(1)[0])]["superseded"][0]
    )


def test_a_first_recording_has_no_history_field(tmp_path):
    backend, _ = make()
    record(backend, doc(1), tmp_path / "r.json", ledger_path=tmp_path / "l.json")
    line = list(json.loads((tmp_path / "l.json").read_text("utf-8")).values())[0]
    assert "superseded" not in line


def test_the_ledger_may_not_be_the_responses_file(tmp_path):
    backend, client = make()
    same = tmp_path / "r.json"
    with pytest.raises(ValueError, match="same file"):
        record(backend, doc(1), same, ledger_path=same)
    with pytest.raises(ValueError, match="same file"):
        record(backend, doc(1), same, ledger_path=tmp_path / "sub" / ".." / "r.json")
    assert client.calls == [] and not same.exists()


def test_a_hard_link_to_the_responses_file_is_refused(tmp_path):
    import os

    backend, client = make()
    same, link = tmp_path / "r.json", tmp_path / "link.json"
    same.write_text("{}" + chr(10), encoding="utf-8")
    try:
        os.link(same, link)
    except OSError:
        pytest.skip("hard links are not available here")
    with pytest.raises(ValueError, match="same file"):
        record(backend, doc(1), same, ledger_path=link)
    assert client.calls == []
