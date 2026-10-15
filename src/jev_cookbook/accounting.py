"""Count actual backend decisions independently of distinct replay fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._canonical import canonical_json
from .answers import DecisionResult
from .backends import Assets, Backend, replay_key
from .questions import Question

AUDIT_PREFIX = "JEV_REQUEST_AUDIT "

__all__ = ["AuditedBackend"]


class AuditedBackend:
    """Delegate every decision, preserving an ordered, duplicate-inclusive request ledger.

    A ledger entry is added immediately before delegation. ``returned`` becomes true only
    after the delegate returns; exceptions propagate unchanged and leave a false entry.
    Requests rejected while computing their replay key never reach the delegate and are
    not counted. These are logical ``decide`` calls, not HTTP attempts or paid requests.

    Public backend settings and live recorder attributes are forwarded, including writes
    such as ``max_retries = 0``. Mode, model and recorded dates remain dynamic. No responses,
    request contents, assets, credentials, timestamps or latency appear in the audit.
    """

    __slots__ = ("_backend", "_calls")

    def __init__(self, backend: Backend) -> None:
        self._backend = backend
        self._calls: list[tuple[str, bool]] = []

    @property
    def mode(self) -> str:
        return self._backend.mode

    @property
    def model(self) -> str:
        return self._backend.model

    @property
    def recorded_dates(self) -> tuple[str, ...]:
        return getattr(self._backend, "recorded_dates", ())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._backend, name, value)

    def __enter__(self) -> AuditedBackend:
        self._backend.__enter__()
        return self

    def __exit__(self, *exc: object) -> Any:
        return self._backend.__exit__(*exc)

    def decide(
        self, state: Any, questions: Mapping[str, Question], *, assets: Assets | None = None
    ) -> DecisionResult:
        key = replay_key(state, questions, assets=assets)
        index = len(self._calls)
        self._calls.append((key, False))
        result = (
            self._backend.decide(state, questions)
            if assets is None
            else self._backend.decide(state, questions, assets=assets)
        )
        self._calls[index] = (key, True)
        return result

    def audit(self) -> dict[str, Any]:
        """A fresh snapshot; both counts are derived from the actual call sequence."""
        return {
            "schema": 1,
            "decide_calls": len(self._calls),
            "distinct_requests": len({key for key, _ in self._calls}),
            "calls": [{"replay_key": key, "returned": returned} for key, returned in self._calls],
        }

    def audit_json(self) -> str:
        """The deterministic, machine-readable line printed at the end of a notebook."""
        return AUDIT_PREFIX + canonical_json(self.audit())
