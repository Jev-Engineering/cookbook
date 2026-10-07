"""Opt-in live backend and response recorder (see ``docs/live.md``).

``LiveBackend`` sends the same question definitions a notebook uses offline to the TypeSafe
System One API through ``typesafe_sdk`` and returns ordinary ``DecisionResult`` objects whose
answers carry ``Provenance.recorded(model_returned, utc_date)``. ``record`` runs requests
through a live backend and writes the responses into a ``ReplayBackend.from_json`` file.

Importing this module never imports ``typesafe_sdk``, reads an environment variable, or
touches the network. The SDK is imported (and ``TYPESAFE_API_KEY`` read) only when a
``LiveBackend`` has to build its own client.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._canonical import plain_json
from .answers import DecisionResult, Provenance, Usage, answer_from_dict
from .backends import (
    LIVE_ENV,
    FixtureError,
    LiveBackendUnavailable,
    ReplayBackend,
    _check_request,
    _check_result,
    replay_key,
)
from .questions import Question

__all__ = [
    "API_KEY_ENV",
    "BudgetExceeded",
    "CallRecord",
    "LiveBackend",
    "LiveCallError",
    "LiveConfigError",
    "LiveResponseError",
    "RecordConflict",
    "RecordReport",
    "live_backend_from_env",
    "merge_responses",
    "record",
]

API_KEY_ENV = "TYPESAFE_API_KEY"
MODEL_ENV = "JEV_COOKBOOK_LIVE_MODEL"
MAX_REQUESTS_ENV = "JEV_COOKBOOK_LIVE_MAX_REQUESTS"
DEFAULT_MAX_REQUESTS = 25
DEFAULT_MAX_RETRIES = 2
# Same statuses the SDK's default RetryPolicy retries (typesafe-sdk 0.7: 408, 429, 5xx).
RETRY_STATUSES = frozenset({408, 429} | set(range(500, 600)))
BACKOFF_INITIAL = 0.5
BACKOFF_MAX = 8.0
RETRY_AFTER_MAX = 30.0
_MESSAGE_LIMIT = 300


class LiveConfigError(LiveBackendUnavailable):
    """The opt-in, the key, or the SDK is missing. The message says what to do."""


class BudgetExceeded(RuntimeError):
    """The per-backend request budget is spent; no request was sent."""


class LiveCallError(RuntimeError):
    """A request failed. ``status`` and ``request_id`` are set when the API answered."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        request_id: str | None = None,
        error_type: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.request_id = request_id
        self.error_type = error_type


class LiveResponseError(ValueError):
    """The API answered, but the response is not a valid decision result.

    The call was made and counted. ``response`` holds the parsed JSON body when there was
    one, so the orchestrator can inspect it; nothing is loosened to make it pass.
    """

    def __init__(self, message: str, *, response: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.response = response


class RecordConflict(ValueError):
    """A responses file already holds a different response under this replay key."""


@dataclass(frozen=True)
class CallRecord:
    """Ledger line for one successful call (no key, no state, no answers)."""

    replay_key: str
    model: str
    request_id: str | None
    usage: Usage
    date: str


def _scrub(text: str, secret: str | None) -> str:
    if secret:
        text = text.replace(secret, "[redacted]")
    return text if len(text) <= _MESSAGE_LIMIT else text[:_MESSAGE_LIMIT] + "..."


def _today_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _import_sdk() -> Any:
    try:
        import typesafe_sdk
    except ImportError:
        raise LiveConfigError(
            "the live backend needs the optional typesafe-sdk package. Install it with "
            "pip install 'jev_cookbook[live]' (or pip install typesafe-sdk), then set "
            f"{LIVE_ENV}=1 and {API_KEY_ENV}. Offline runs do not need it."
        ) from None
    return typesafe_sdk


def _read_key() -> str:
    flag = os.environ.get(LIVE_ENV, "")
    if flag != "1":
        raise LiveConfigError(
            f"live calls are opt-in: set {LIVE_ENV}=1 in the environment to allow them "
            f"(it is {'unset' if flag == '' else repr(flag)} now). Offline runs use fixtures "
            "and make no call."
        )
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise LiveConfigError(
            f"{API_KEY_ENV} is not set. Create a key at the TypeSafe console, export it as "
            f"{API_KEY_ENV} in the environment (never in a notebook, fixture or file you commit), "
            f"and keep {LIVE_ENV}=1."
        )
    return key


def _question_payload(question: Question) -> dict[str, Any]:
    """The raw-dictionary form the SDK accepts: only the fields that are set."""
    data = question.to_dict()
    return {k: v for k, v in data.items() if k == "type" or v is not None}


def _usage_from(raw: Any) -> Usage:
    """Map the API's usage block to ``Usage``; counts must be non-negative ints or null."""
    if raw is None:
        return Usage()
    if not isinstance(raw, Mapping):
        raise LiveResponseError(f"usage must be an object, got {type(raw).__name__}")
    values: dict[str, int | None] = {}
    for name in ("input_tokens", "output_tokens"):
        v = raw.get(name)
        if v is not None and (type(v) is not int or v < 0):
            raise LiveResponseError(f"usage.{name} must be a non-negative integer or null: {v!r}")
        values[name] = v
    return Usage(values["input_tokens"], values["output_tokens"])


def _response_json(response: Any) -> dict[str, Any]:
    """Parse a response object (SDK model or mapping) through JSON into plain data.

    The SDK's strict models reject Python dicts with string level keys, and their Python
    dumps hold ``int`` level keys, so the JSON text is the one lossless common form.
    """
    if hasattr(response, "model_dump_json"):
        text = response.model_dump_json()
    elif isinstance(response, Mapping):
        try:
            text = json.dumps(response, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise LiveResponseError(f"response is not JSON-serializable: {exc}") from None
    else:
        raise LiveResponseError(
            f"response must be an SDK response model or a mapping, got {type(response).__name__}"
        )
    data = json.loads(text)
    if not isinstance(data, dict):
        raise LiveResponseError("response body is not a JSON object", response=None)
    return data


def _request_id(response: Any) -> str | None:
    try:
        rid = response.request_id
    except Exception:  # SDK raises when the header is absent; a mapping has no attribute
        return None
    return rid if isinstance(rid, str) and rid else None


def _parse_response(
    response: Any, questions: Mapping[str, Question], date: str
) -> tuple[DecisionResult, str | None]:
    """Turn an API response into a recorded ``DecisionResult`` (validated, not loosened)."""
    data = _response_json(response)
    model = data.get("model")
    if type(model) is not str or not model:
        raise LiveResponseError("response has no model string", response=data)
    answers_raw = data.get("answers")
    if not isinstance(answers_raw, dict):
        raise LiveResponseError("response has no answers object", response=data)
    try:
        usage = _usage_from(data.get("usage"))
    except LiveResponseError as exc:
        raise LiveResponseError(str(exc), response=data) from None
    provenance = Provenance.recorded(model, date).to_dict()
    answers = {}
    for name, raw in answers_raw.items():
        if not isinstance(raw, dict):
            raise LiveResponseError(f"answer {name!r} is not an object", response=data)
        fields = {
            "noul": ("noul",),
            "choice": ("choice", "probabilities", "confidence"),
            "score": ("score", "probabilities", "confidence", "legend"),
        }.get(raw.get("type"))
        if fields is None:
            raise LiveResponseError(
                f"answer {name!r} has an unknown type {raw.get('type')!r}", response=data
            )
        stored = {"type": raw["type"], **{f: raw[f] for f in fields if f in raw}}
        stored["provenance"] = dict(provenance)
        try:
            answers[name] = answer_from_dict(stored)
        except (ValueError, TypeError) as exc:
            shown = {k: v for k, v in stored.items() if k not in ("provenance", "legend")}
            raise LiveResponseError(
                f"the API returned an answer for question {name!r} ({raw['type']}) that fails "
                f"validation: {exc}. Reported values: {shown!r}. Nothing was loosened; see "
                "docs/live.md (Tolerances).",
                response=data,
            ) from None
    try:
        result = DecisionResult(answers, model, usage)
        _check_result(questions, result)
    except (ValueError, TypeError, FixtureError) as exc:
        raise LiveResponseError(
            f"the API response does not fit the questions asked: {exc}", response=data
        ) from None
    return result, _request_id(response)


def _is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status", None)
    if type(status) is int:
        return status in RETRY_STATUSES
    # typesafe_sdk's connection and timeout errors subclass the builtins.
    return isinstance(exc, (ConnectionError, TimeoutError))


def _describe_failure(exc: BaseException, key: str | None) -> LiveCallError:
    status = getattr(exc, "status", None)
    status = status if type(status) is int else None
    rid = getattr(exc, "request_id", None)
    rid = rid if isinstance(rid, str) else None
    kind = type(exc).__name__
    if isinstance(exc, TimeoutError):
        what = "the request timed out (it may have reached the server, so it counts as spent)"
    elif isinstance(exc, ConnectionError):
        what = "the request could not reach the API"
    elif status is not None:
        what = f"the API returned HTTP {status}"
    else:
        what = "the request failed"
    detail = _scrub(str(exc), key)
    hint = ""
    if status == 401:
        hint = f" Check {API_KEY_ENV}."
    msg = f"{what} ({kind}{f', request id {rid}' if rid else ''}).{hint}"
    if detail:
        msg += f" Detail: {detail}"
    return LiveCallError(msg, status=status, request_id=rid, error_type=kind)


class LiveBackend:
    """Backend that answers by calling the TypeSafe System One API.

    ``model`` is required and passed explicitly (an alias such as ``"jev-latest"`` or a
    pinned ID such as ``"jev-1.13.0"``); ``self.model`` is that requested string until the
    first response, then the model string the API returned. ``mode`` is ``"live"``.

    ``client`` is injectable: any object with ``system_one(state=..., questions=..., model=...)``
    returning an SDK-style response (or a mapping of that JSON shape). With no ``client`` the
    backend reads ``TYPESAFE_API_KEY`` (requires ``JEV_COOKBOOK_LIVE=1``), imports
    ``typesafe_sdk`` and builds ``TypeSafeClient(api_key=..., retry=RetryPolicy(max_retries=0))``
    so that this class owns retries and every attempt is counted. An injected client reads
    nothing from the environment; if it retries internally those retries are not visible to the
    budget, so build it with retries off. ``request_kwargs`` are passed to every
    ``system_one`` call (the seam for the System One Adapter's ``provider=``).

    The budget: at most ``max_requests`` attempts (each retry counts; a timeout counts as
    spent). A request over the budget raises ``BudgetExceeded`` before anything is sent.
    ``max_retries`` retries (default 2) apply to HTTP 408/429/5xx, connection errors and
    timeouts, with exponential backoff (``sleep`` is injectable).
    """

    mode = "live"

    def __init__(
        self,
        model: str,
        *,
        client: Any = None,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        request_kwargs: Mapping[str, Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        today: Callable[[], str] = _today_utc,
    ) -> None:
        if type(model) is not str or not model.strip():
            raise ValueError("model must be a non-empty string such as 'jev-latest'")
        for name, value, low in (
            ("max_requests", max_requests, 1),
            ("max_retries", max_retries, 0),
        ):
            if type(value) is not int or value < low:
                raise ValueError(f"{name} must be an int >= {low}, got {value!r}")
        self.requested_model: str = model
        self.model: str = model
        self.max_requests: int = max_requests
        self.max_retries: int = max_retries
        self._request_kwargs = dict(request_kwargs or {})
        self._sleep = sleep
        self._today = today
        self._lock = threading.Lock()
        self._made = 0
        self._failed = 0
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._calls_without_usage = 0
        self._records: list[CallRecord] = []
        self._owns_client = client is None
        if client is None:
            client = self._build_client()
        self._client = client

    def _build_client(self) -> Any:
        key = _read_key()
        sdk = _import_sdk()
        try:
            return sdk.TypeSafeClient(api_key=key, retry=sdk.RetryPolicy(max_retries=0))
        except Exception as exc:
            raise LiveConfigError(
                f"the TypeSafe SDK rejected {API_KEY_ENV} ({type(exc).__name__}): "
                + _scrub(str(exc), key)
            ) from None

    def __repr__(self) -> str:
        return (
            f"LiveBackend(model={self.model!r}, requests={self._made}/{self.max_requests}, "
            f"client={type(self._client).__name__})"
        )

    __str__ = __repr__

    # -- budget and ledger -------------------------------------------------------------

    @property
    def requests_made(self) -> int:
        """Attempts sent so far, including retries and requests whose outcome is unknown."""
        return self._made

    @property
    def requests_remaining(self) -> int:
        return self.max_requests - self._made

    @property
    def usage_total(self) -> Usage:
        """Sum of the token counts the API reported (``None`` until one call reports it)."""
        return Usage(self._input_tokens, self._output_tokens)

    @property
    def records(self) -> tuple[CallRecord, ...]:
        """One ``CallRecord`` per successful call, in order."""
        return tuple(self._records)

    @property
    def request_ids(self) -> tuple[str | None, ...]:
        return tuple(r.request_id for r in self._records)

    @property
    def last_request_id(self) -> str | None:
        return self._records[-1].request_id if self._records else None

    def ledger(self) -> dict[str, Any]:
        """Plain-data summary for an orchestrator's ledger (no key, state or answers)."""
        return {
            "requested_model": self.requested_model,
            "model": self.model,
            "max_requests": self.max_requests,
            "requests_made": self._made,
            "successful_calls": len(self._records),
            "failed_attempts": self._failed,
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "calls_without_usage": self._calls_without_usage,
            "request_ids": [r.request_id for r in self._records],
        }

    def _spend(self) -> None:
        with self._lock:
            if self._made >= self.max_requests:
                raise BudgetExceeded(
                    f"request budget spent: {self._made} of {self.max_requests} requests made "
                    f"(retries and timed-out requests count). Nothing was sent. Raise "
                    "max_requests for this backend only if you mean to spend more."
                )
            self._made += 1

    def _note_success(self, rec: CallRecord) -> None:
        with self._lock:
            self._records.append(rec)
            self.model = rec.model
            for attr, v in (
                ("_input_tokens", rec.usage.input_tokens),
                ("_output_tokens", rec.usage.output_tokens),
            ):
                if v is not None:
                    setattr(self, attr, (getattr(self, attr) or 0) + v)
            if rec.usage.input_tokens is None or rec.usage.output_tokens is None:
                self._calls_without_usage += 1

    # -- decide --------------------------------------------------------------------------

    def decide(self, state: Any, questions: Mapping[str, Question]) -> DecisionResult:
        plain_state, checked = _check_request(state, questions)
        key = replay_key(state, questions)
        payload = {name: _question_payload(q) for name, q in checked.items()}
        attempt = 0
        while True:
            self._spend()
            try:
                response = self._client.system_one(
                    state=plain_json(plain_state, "state"),
                    questions=payload,
                    model=self.requested_model,
                    **self._request_kwargs,
                )
            except Exception as exc:
                with self._lock:
                    self._failed += 1
                if _is_retryable(exc) and attempt < self.max_retries:
                    attempt += 1
                    self._sleep(self._delay(exc, attempt))
                    continue
                raise _describe_failure(exc, os.environ.get(API_KEY_ENV)) from None
            break
        date = self._today()
        try:
            result, rid = _parse_response(response, checked, date)
        except LiveResponseError:
            with self._lock:
                self._failed += 1
            raise
        self._note_success(CallRecord(key, result.model, rid, result.usage, date))
        return result

    @staticmethod
    def _delay(exc: BaseException, attempt: int) -> float:
        hinted = getattr(exc, "retry_after_ms", None)
        if type(hinted) in (int, float) and hinted >= 0:
            return min(hinted / 1000.0, RETRY_AFTER_MAX)
        return min(BACKOFF_INITIAL * 2 ** (attempt - 1), BACKOFF_MAX)

    def close(self) -> None:
        """Close the client when this backend built it (an injected client stays yours)."""
        if self._owns_client and hasattr(self._client, "close"):
            self._client.close()

    def __enter__(self) -> LiveBackend:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# -- recorder ----------------------------------------------------------------------------


def _no_duplicates(path: Path) -> Callable[[list[tuple[str, Any]]], dict[str, Any]]:
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise FixtureError(f"{path}: duplicate key {k!r}")
            out[k] = v
        return out

    return hook


def _load_responses(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        data = json.load(fh, object_pairs_hook=_no_duplicates(path))
    if not isinstance(data, dict):
        raise FixtureError(f"{path}: expected a JSON object of replay_key -> response")
    return data


def _dump(data: Mapping[str, Any]) -> str:
    """Deterministic fixture text: keys sorted, 2-space indent, UTF-8, LF, final newline."""
    return json.dumps(dict(sorted(data.items())), indent=2, ensure_ascii=False) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".responses-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def merge_responses(
    path: str | os.PathLike[str],
    additions: Mapping[str, Mapping[str, Any]],
    *,
    overwrite: bool = False,
) -> tuple[list[str], list[str]]:
    """Merge stored responses into a ``{replay_key: stored_response}`` file.

    Returns ``(written, unchanged)`` key lists. A key already present with a different
    response raises ``RecordConflict`` unless ``overwrite`` is true; an identical one is left
    as is. The merged set must still load as a ``ReplayBackend`` (one source, one model),
    otherwise ``RecordConflict`` explains why and nothing is written. The write is atomic.
    """
    target = Path(path)
    merged = _load_responses(target)
    written: list[str] = []
    unchanged: list[str] = []
    for key, stored in additions.items():
        stored = json.loads(json.dumps(stored))
        if key in merged and merged[key] != stored:
            if not overwrite:
                raise RecordConflict(
                    f"{target} already holds a different response for replay key {key}. "
                    "Pass overwrite=True to replace it, or record to a new file."
                )
        if key in merged and merged[key] == stored:
            unchanged.append(key)
            continue
        merged[key] = stored
        written.append(key)
    try:
        ReplayBackend(merged)
    except FixtureError as exc:
        raise RecordConflict(f"the merged responses would not load for replay: {exc}") from None
    if written:
        _write_atomic(target, _dump(merged))
    return written, unchanged


@dataclass(frozen=True)
class RecordReport:
    """What ``record`` did. ``requests`` is the number of live attempts the backend made."""

    path: Path
    written: tuple[str, ...]
    skipped: tuple[str, ...]
    unchanged: tuple[str, ...]
    requests: int
    model: str | None
    ledger_path: Path | None = None


def record(
    backend: LiveBackend,
    requests: Iterable[tuple[Any, Mapping[str, Question]]],
    responses_path: str | os.PathLike[str],
    *,
    overwrite: bool = False,
    ledger_path: str | os.PathLike[str] | None = None,
) -> RecordReport:
    """Run ``(state, questions)`` requests live and write ``recorded`` responses to a file.

    ``responses_path`` is the recipe's responses file in the ``ReplayBackend.from_json``
    format ``{replay_key: stored_response}`` (the caller decides the name and folder). Each
    response is merged and written as soon as it arrives, so a failure later in the run keeps
    what was already paid for. A key already in the file is skipped without a call unless
    ``overwrite=True``, in which case the new response replaces it. A response that fails
    answer validation raises ``LiveResponseError`` naming the question and field; nothing
    is loosened. ``ledger_path`` optionally writes ``{replay_key: {request_id, model, date,
    input_tokens, output_tokens}}`` for the calls made here (``request_id`` is not part of
    the stored-response format, so it lives in this sidecar).
    """
    target = Path(responses_path)
    before = backend.requests_made
    existing = set(_load_responses(target))
    written: list[str] = []
    skipped: list[str] = []
    unchanged: list[str] = []
    sidecar: dict[str, Any] = {}
    seen: set[str] = set()
    for state, questions in requests:
        key = replay_key(state, questions)
        if key in seen:
            continue
        seen.add(key)
        if key in existing and not overwrite:
            skipped.append(key)
            continue
        result = backend.decide(state, questions)
        rec = backend.records[-1]
        w, u = merge_responses(target, {key: result.to_dict()}, overwrite=overwrite)
        written += w
        unchanged += u
        existing.add(key)
        sidecar[key] = {
            "request_id": rec.request_id,
            "model": rec.model,
            "date": rec.date,
            "input_tokens": rec.usage.input_tokens,
            "output_tokens": rec.usage.output_tokens,
        }
    out_ledger = None
    if ledger_path is not None and sidecar:
        out_ledger = Path(ledger_path)
        old = _load_responses(out_ledger)
        old.update(sidecar)
        _write_atomic(out_ledger, _dump(old))
    return RecordReport(
        target,
        tuple(written),
        tuple(skipped),
        tuple(unchanged),
        backend.requests_made - before,
        backend.model if backend.records else None,
        out_ledger,
    )


def live_backend_from_env(**_ignored: Any) -> LiveBackend:
    """Build the backend ``get_backend`` returns under ``JEV_COOKBOOK_LIVE=1``.

    ``get_backend`` has no model argument, and the model is never defaulted, so it comes from
    ``JEV_COOKBOOK_LIVE_MODEL`` (for example ``jev-1.13.0``); ``JEV_COOKBOOK_LIVE_MAX_REQUESTS``
    optionally sets the budget (default 25). ``fixtures``/``script`` arguments are ignored in
    live mode: the same notebook code runs, and the backend is the only thing that changes.
    """
    model = os.environ.get(MODEL_ENV, "").strip()
    if not model:
        raise LiveConfigError(
            f"{MODEL_ENV} is not set. The model is chosen explicitly for every live run: set it "
            "to a versioned ID such as jev-1.13.0 (pinned) or an alias such as jev-latest "
            "(moves when a new release ships), or construct LiveBackend(model=...) yourself."
        )
    raw = os.environ.get(MAX_REQUESTS_ENV, "").strip()
    try:
        budget = int(raw) if raw else DEFAULT_MAX_REQUESTS
    except ValueError:
        raise LiveConfigError(f"{MAX_REQUESTS_ENV} must be a whole number, got {raw!r}") from None
    if budget < 1:
        raise LiveConfigError(f"{MAX_REQUESTS_ENV} must be at least 1, got {budget}")
    return LiveBackend(model, max_requests=budget)
