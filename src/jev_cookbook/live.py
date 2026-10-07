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
import inspect
import json
import logging
import os
import re
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
OFFICIAL_BASE_URL = "https://api.typesafe.ai"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
SDK_LOGGER = "typesafe_sdk"
# The only per-call options a recorder may pass through. Everything else (retry, extra_body,
# extra_headers, state, questions, model, response_model, ...) can change what is sent or how
# many times, so it is rejected rather than forwarded.
ALLOWED_REQUEST_KWARGS = frozenset({"provider", "timeout"})


class LiveConfigError(LiveBackendUnavailable):
    """The opt-in, the key, or the SDK is missing. The message says what to do."""


class BudgetExceeded(RuntimeError):
    """The per-backend request budget is spent; no request was sent."""


class LiveCallError(RuntimeError):
    """A request failed. ``status`` and ``request_id`` are set when the API answered.

    A timeout or a connection error has neither, because no response came back.
    """

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
    ``request_id`` is the response's ``x-typesafe-request-id`` when it had one: the paid call
    can be found by it even though nothing was recorded.
    """

    def __init__(
        self,
        message: str,
        *,
        response: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.response = response
        self.request_id = request_id


class RecordConflict(ValueError):
    """A responses file already holds a different response under this replay key.

    When the conflict happens after a paid call, ``result`` holds that ``DecisionResult`` and
    ``saved_to`` the drift file it was kept in (``None`` if even that write failed).
    """

    result: DecisionResult | None = None
    saved_to: Path | None = None


@dataclass(frozen=True)
class CallRecord:
    """Ledger line for one successful call (no key, no state, no answers)."""

    replay_key: str
    model: str
    request_id: str | None
    usage: Usage
    date: str


def _secret_variants(*raw: str | None) -> tuple[str, ...]:
    """Every form of the key that may be echoed: as given, and trimmed (what the SDK sends)."""
    forms = set()
    for value in raw:
        if value and value.strip():
            forms.update((value, value.strip()))
    return tuple(sorted(forms, key=len, reverse=True))


def _redact(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
    return text


def _scrub(text: str, secrets: Iterable[str]) -> str:
    text = _redact(text, secrets)
    return text if len(text) <= _MESSAGE_LIMIT else text[:_MESSAGE_LIMIT] + "..."


def _redact_data(data: Any, secrets: tuple[str, ...]) -> Any:
    """Copy parsed JSON with the key removed from every string and key."""
    if isinstance(data, str):
        return _redact(data, secrets)
    if isinstance(data, Mapping):
        return {
            (_redact(k, secrets) if isinstance(k, str) else k): _redact_data(v, secrets)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact_data(v, secrets) for v in data]
    return data


def _wire_variants(*raw: str | None) -> tuple[str, ...]:
    """``_secret_variants`` plus the escaped spellings a repr or JSON dump of the text shows."""
    forms = set()
    for value in _secret_variants(*raw):
        forms.update(
            (value, repr(value)[1:-1], repr(value.encode())[2:-1], json.dumps(value)[1:-1])
        )
    return tuple(sorted((f for f in forms if f), key=len, reverse=True))


class _RedactingFilter(logging.Filter):
    """Replace every registered key variant in a record before any handler sees it.

    One instance serves the ``typesafe_sdk`` logger for all backends that built their own
    client; variants are reference counted, so ``close()`` of one backend does not unprotect
    another. It runs after the SDK's own header filter, which was added at import.
    """

    def __init__(self) -> None:
        super().__init__()
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def add(self, variants: Iterable[str]) -> None:
        with self._lock:
            for v in variants:
                self._counts[v] = self._counts.get(v, 0) + 1

    def discard(self, variants: Iterable[str]) -> bool:
        """Drop one reference to each variant; True when no variant is registered any more."""
        with self._lock:
            for v in variants:
                if v in self._counts:
                    self._counts[v] -= 1
                    if self._counts[v] <= 0:
                        del self._counts[v]
            return not self._counts

    def filter(self, record: logging.LogRecord) -> bool:
        with self._lock:
            secrets = tuple(sorted(self._counts, key=len, reverse=True))
        if not secrets:
            return True
        try:
            message = record.getMessage()
        except Exception:  # a malformed record: show it without its arguments, never raw
            message = str(record.msg)
        if any(s in message for s in secrets):
            record.msg = _redact(message, secrets)
            record.args = None
        return True


_LOG_FILTER = _RedactingFilter()


def _protect_sdk_logger(variants: Iterable[str]) -> None:
    logger = logging.getLogger(SDK_LOGGER)
    if _LOG_FILTER not in logger.filters:
        logger.addFilter(_LOG_FILTER)
    _LOG_FILTER.add(variants)


def _release_sdk_logger(variants: Iterable[str]) -> None:
    if _LOG_FILTER.discard(variants):
        logging.getLogger(SDK_LOGGER).removeFilter(_LOG_FILTER)


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


def _check_base_url() -> None:
    """Refuse to send the key anywhere but the official host (the SDK reads this variable)."""
    raw = os.environ.get(BASE_URL_ENV, "").strip()
    if raw and raw.rstrip("/").lower() != OFFICIAL_BASE_URL:
        raise LiveConfigError(
            f"{BASE_URL_ENV} is set to a host other than {OFFICIAL_BASE_URL}, and the SDK would "
            f"send {API_KEY_ENV} there. Unset it for a live run. To use another endpoint on "
            "purpose, build the client yourself and pass LiveBackend(model, client=...)."
        )


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
    rid = _request_id(response)
    try:
        data = _response_json(response)
    except LiveResponseError as exc:
        raise LiveResponseError(str(exc), response=exc.response, request_id=rid) from None
    model = data.get("model")
    if type(model) is not str or not model:
        raise LiveResponseError("response has no model string", response=data, request_id=rid)
    answers_raw = data.get("answers")
    if not isinstance(answers_raw, dict):
        raise LiveResponseError("response has no answers object", response=data, request_id=rid)
    try:
        usage = _usage_from(data.get("usage"))
    except LiveResponseError as exc:
        raise LiveResponseError(str(exc), response=data, request_id=rid) from None
    provenance = Provenance.recorded(model, date).to_dict()
    answers = {}
    for name, raw in answers_raw.items():
        if not isinstance(raw, dict):
            raise LiveResponseError(
                f"answer {name!r} is not an object", response=data, request_id=rid
            )
        fields = {
            "noul": ("noul",),
            "choice": ("choice", "probabilities", "confidence"),
            "score": ("score", "probabilities", "confidence", "legend"),
        }.get(raw.get("type"))
        if fields is None:
            raise LiveResponseError(
                f"answer {name!r} has an unknown type {raw.get('type')!r}",
                response=data,
                request_id=rid,
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
                request_id=rid,
            ) from None
    try:
        result = DecisionResult(answers, model, usage)
        _check_result(questions, result)
    except (ValueError, TypeError, FixtureError) as exc:
        raise LiveResponseError(
            f"the API response does not fit the questions asked: {exc}",
            response=data,
            request_id=rid,
        ) from None
    return result, rid


def _is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status", None)
    if type(status) is int:
        return status in RETRY_STATUSES
    # typesafe_sdk's connection and timeout errors subclass the builtins.
    return isinstance(exc, (ConnectionError, TimeoutError))


def _is_validation_error(exc: BaseException) -> bool:
    return (
        type(getattr(exc, "field_path", None)) is str and type(getattr(exc, "status", None)) is int
    )


def _response_validation_error(exc: BaseException, secrets: tuple[str, ...]) -> LiveResponseError:
    """A 200 the SDK rejected: keep the (scrubbed) body, as docs/live.md promises."""
    path = _redact(str(getattr(exc, "field_path", "")), secrets)
    body = getattr(exc, "body", None)
    msg = f"the API answered HTTP {getattr(exc, 'status', 200)} but the body is not a valid result"
    if path:
        msg += f" (invalid or missing field {path!r})"
    parsed = None
    if isinstance(body, Mapping):
        parsed = _redact_data(body, secrets)
    elif isinstance(body, str) and body:
        msg += f". The body was not a JSON object. It begins: {_scrub(body, secrets)!r}"
    rid = getattr(exc, "request_id", None)
    rid = _redact(rid, secrets) if isinstance(rid, str) and rid else None
    return LiveResponseError(msg, response=parsed, request_id=rid)


def _takes_retry(client: Any) -> bool:
    """True when ``client.system_one`` has a per-call ``retry`` parameter (the SDK's does)."""
    try:
        return "retry" in inspect.signature(client.system_one).parameters
    except (TypeError, ValueError, AttributeError):
        return False


def _describe_failure(exc: BaseException, secrets: tuple[str, ...]) -> LiveCallError:
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
    detail = _scrub(str(exc), secrets)
    hint = ""
    if status == 401:
        hint = f" Check {API_KEY_ENV}."
    rid = _redact(rid, secrets) if rid else rid
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
    ``system_one`` call (the seam for the System One Adapter's ``provider=``); only
    ``provider`` and ``timeout`` are accepted, because anything else (``retry``, ``extra_body``,
    ...) could change what is sent or how many times. The backend always passes its own no-retry
    policy per call when the client's ``system_one`` takes ``retry=``.

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
        bad = sorted(set(request_kwargs or {}) - ALLOWED_REQUEST_KWARGS)
        if bad:
            raise ValueError(
                f"request_kwargs {bad} are not allowed: they could change what is sent or how "
                "many requests are made, which the budget cannot see. Allowed: "
                f"{sorted(ALLOWED_REQUEST_KWARGS)}."
            )
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
        self._retried: list[dict[str, Any]] = []
        self._owns_client = client is None
        # Only used to scrub messages; an injected client's key came from somewhere we cannot
        # see, and the usual place is this variable.
        self._secrets = _secret_variants(os.environ.get(API_KEY_ENV))
        self._call_extra: dict[str, Any] = {}
        self._log_variants: tuple[str, ...] = ()
        if client is None:
            client = self._build_client()
            self._call_extra["retry"] = _import_sdk().RetryPolicy(max_retries=0)
        elif _takes_retry(client):
            self._call_extra["retry"] = _import_sdk().RetryPolicy(max_retries=0)
        self._client = client

    def _build_client(self) -> Any:
        key = _read_key()
        _check_base_url()
        self._secrets = _secret_variants(os.environ.get(API_KEY_ENV), key)
        sdk = _import_sdk()
        # The SDK logs response bodies unredacted at DEBUG. Redact the key from that logger for
        # as long as this backend's own client lives (an injected client is the caller's job).
        self._log_variants = _wire_variants(os.environ.get(API_KEY_ENV), key)
        _protect_sdk_logger(self._log_variants)
        failure = None
        try:
            return sdk.TypeSafeClient(
                api_key=key, base_url=OFFICIAL_BASE_URL, retry=sdk.RetryPolicy(max_retries=0)
            )
        except Exception as exc:
            failure = (type(exc).__name__, _scrub(str(exc), self._secrets))
        _release_sdk_logger(self._log_variants)
        self._log_variants = ()
        raise LiveConfigError(
            f"the TypeSafe SDK rejected {API_KEY_ENV} ({failure[0]}): {failure[1]}"
        )

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
    def last_retried(self) -> tuple[dict[str, Any], ...]:
        """The failed attempts the latest ``decide`` call retried past, oldest first.

        Each is ``{error_type, http_status, request_id}`` (scrubbed). Reset at the start of every
        call, so it describes that call whether it then succeeded or raised.
        """
        return tuple(dict(r) for r in self._retried)

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
        with self._lock:
            self._retried = []
        # Errors are raised after their `except` block has ended, so neither `__cause__` nor
        # `__context__` carries the SDK exception (its message may echo the key).
        while True:
            self._spend()
            failure: Exception | None = None
            delay = 0.0
            try:
                response = self._client.system_one(
                    state=plain_json(plain_state, "state"),
                    questions=payload,
                    model=self.requested_model,
                    **self._request_kwargs,
                    **self._call_extra,
                )
            except Exception as exc:
                with self._lock:
                    self._failed += 1
                if _is_retryable(exc) and attempt < self.max_retries:
                    attempt += 1
                    delay = self._delay(exc, attempt)
                    note = _describe_failure(exc, self._secrets)
                    with self._lock:
                        self._retried.append(
                            {
                                "error_type": note.error_type,
                                "http_status": note.status,
                                "request_id": note.request_id,
                            }
                        )
                elif _is_validation_error(exc):
                    failure = _response_validation_error(exc, self._secrets)
                else:
                    failure = _describe_failure(exc, self._secrets)
            else:
                break
            if failure is not None:
                raise failure
            self._sleep(delay)
        date = self._today()
        problem: tuple[str, Any, str | None] | None = None
        try:
            result, rid = _parse_response(response, checked, date)
            if self._secrets and any(
                s in json.dumps([result.to_dict(), rid]) for s in _wire_variants(*self._secrets)
            ):
                # Never keep a response that carries the key (it would be written to a fixture).
                raise LiveResponseError(
                    "the response contains the API key, so it was refused and not recorded",
                    request_id=rid,
                )
        except LiveResponseError as exc:
            with self._lock:
                self._failed += 1
            problem = (str(exc), exc.response, exc.request_id)
        if problem is not None:
            rid = problem[2]
            raise LiveResponseError(
                _redact(problem[0], self._secrets),
                response=_redact_data(problem[1], self._secrets),
                request_id=_redact(rid, self._secrets) if rid else None,
            )
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
        variants, self._log_variants = self._log_variants, ()
        if variants:
            _release_sdk_logger(variants)

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


def _keep_paid_response(
    exc: RecordConflict, target: Path, key: str, result: DecisionResult
) -> RecordConflict:
    """Save a response that could not be merged (alias moved, answer differs) beside the file.

    The name ``<stem>.drift-<returned model><suffix>`` is deliberately not a fixture name: the
    fixture validator flags it as a stray file, which is the signal for the author to deal with it.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", result.model)
    side = target.with_name(f"{target.stem}.drift-{safe}{target.suffix}")
    saved: Path | None = None
    try:
        merge_responses(side, {key: result.to_dict()}, overwrite=False)
        saved = side
        note = f" The response was paid for, so it was kept in {side} (nothing else changed)."
    except Exception as inner:
        note = f" Keeping it in {side} also failed ({type(inner).__name__}); it is on .result."
    err = RecordConflict(f"{exc}{note}")
    err.result = result
    err.saved_to = saved
    return err


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
    is loosened.

    ``ledger_path`` optionally writes a sidecar with one line per paid call made here
    (``request_id`` is not part of the stored-response format, so it lives there): a success is
    ``{replay_key: {status: "recorded", request_id, model, date, input_tokens, output_tokens}}``
    and a call that produced nothing to record (``invalid_response``, ``error``, ``timeout``,
    ``budget_stopped``) is ``{replay_key + "!failed-N": {status, error_type, http_status,
    request_id, model, date, attempts, retried}}``, written before the error is re-raised.
    ``attempts`` is the HTTP attempts that call spent (a budget stop with nothing sent is 0) and
    ``retried`` lists ``{error_type, http_status, request_id}`` for each failed attempt it retried
    past, on both kinds of line. Re-recording a key with ``overwrite=True`` keeps the earlier
    ``recorded`` entry under ``superseded``. A ``ledger_path`` inside a ``fixtures/`` directory,
    or the same file as ``responses_path``, is refused with ``ValueError`` before any call.
    """
    target = Path(responses_path)
    out_ledger = Path(ledger_path) if ledger_path is not None else None
    if out_ledger is not None:
        _refuse_fixtures_dir(out_ledger)
        _refuse_same_file(out_ledger, target)
    before = backend.requests_made
    existing = set(_load_responses(target))
    written: list[str] = []
    skipped: list[str] = []
    unchanged: list[str] = []
    wrote_ledger = False
    seen: set[str] = set()
    for state, questions in requests:
        key = replay_key(state, questions)
        if key in seen:
            continue
        seen.add(key)
        if key in existing and not overwrite:
            skipped.append(key)
            continue
        attempts_before = backend.requests_made
        try:
            result = backend.decide(state, questions)
        except Exception as exc:
            # Every paid attempt gets a ledger line, even when it produced nothing to record.
            if out_ledger is not None:
                _ledger_failure(
                    out_ledger, key, exc, backend, backend.requests_made - attempts_before
                )
                wrote_ledger = True
            raise
        rec = backend.records[-1]
        # The call is paid for: record its request id first, then the response.
        if out_ledger is not None:
            old = _load_responses(out_ledger)
            line: dict[str, Any] = {
                "status": "recorded",
                "request_id": rec.request_id,
                "model": rec.model,
                "date": rec.date,
                "input_tokens": rec.usage.input_tokens,
                "output_tokens": rec.usage.output_tokens,
                "attempts": backend.requests_made - attempts_before,
                "retried": list(backend.last_retried),
            }
            previous = old.get(key)
            if isinstance(previous, dict):
                # A paid call is never forgotten: an earlier entry for this key moves to history.
                history = list(previous.get("superseded") or [])
                history.append({k: v for k, v in previous.items() if k != "superseded"})
                line["superseded"] = history
            old[key] = line
            _write_atomic(out_ledger, _dump(old))
            wrote_ledger = True
        try:
            w, u = merge_responses(target, {key: result.to_dict()}, overwrite=overwrite)
        except RecordConflict as exc:
            raise _keep_paid_response(exc, target, key, result) from None
        written += w
        unchanged += u
        existing.add(key)
    return RecordReport(
        target,
        tuple(written),
        tuple(skipped),
        tuple(unchanged),
        backend.requests_made - before,
        backend.model if backend.records else None,
        out_ledger if wrote_ledger else None,
    )


def _refuse_fixtures_dir(path: Path) -> None:
    """The sidecar is not a fixture: the fixture validator rejects stray files in ``fixtures/``."""
    if any(part.lower() == "fixtures" for part in path.resolve().parent.parts):
        raise ValueError(
            f"ledger_path {str(path)!r} is inside a fixtures/ directory. The sidecar holds request "
            "ids and failed attempts, not fixtures, and the fixture validator rejects stray files "
            "there. Put it elsewhere (for example next to the recipe, outside fixtures/)."
        )


def _refuse_same_file(ledger: Path, responses: Path) -> None:
    """The sidecar must not be the responses file (it would write lines into the fixture)."""
    same = ledger.resolve() == responses.resolve()
    if not same and ledger.exists() and responses.exists():
        same = os.path.samefile(ledger, responses)
    if same:
        raise ValueError(
            f"ledger_path {str(ledger)!r} is the same file as responses_path. The sidecar holds "
            "request ids and failed attempts, not responses; use a separate file."
        )


def _ledger_failure(
    ledger: Path, key: str, exc: Exception, backend: LiveBackend, attempts: int
) -> None:
    """Add a sidecar line for a ``decide`` call that produced no response to record.

    The line is stored under ``<replay key>!failed-<n>`` so it never replaces the entry of an
    earlier successful call for the same key.
    """
    if isinstance(exc, BudgetExceeded):
        kind = "budget_stopped"
    elif isinstance(exc, LiveResponseError):
        kind = "invalid_response"
    elif isinstance(exc, LiveCallError):
        kind = "timeout" if exc.error_type.endswith("TimeoutError") else "error"
    else:
        kind = "error"
    old = _load_responses(ledger)
    n = 1
    while f"{key}!failed-{n}" in old:
        n += 1
    old[f"{key}!failed-{n}"] = {
        "status": kind,
        "error_type": getattr(exc, "error_type", "") or type(exc).__name__,
        "http_status": getattr(exc, "status", None),
        "request_id": getattr(exc, "request_id", None),
        "model": backend.requested_model,
        "date": backend._today(),
        "attempts": attempts,
        "retried": list(backend.last_retried),
    }
    _write_atomic(ledger, _dump(old))


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
