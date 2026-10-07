"""Decision backends: one call, ``decide(state, questions)``, offline or (later) live.

``ReplayBackend`` answers from stored responses keyed by ``replay_key``; ``ScriptedBackend``
answers from a seeded function; ``get_backend`` picks one. The live backend arrives in a
separate change and plugs into ``get_backend`` through ``_make_live_backend``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ._canonical import canonical_json, plain_json
from .answers import (
    RECORDED_SOURCE,
    SYNTHETIC_MODEL,
    SYNTHETIC_SOURCE,
    Answer,
    ChoiceAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    ScoreAnswer,
    Usage,
)
from .questions import Choice, Noul, Question, Score

__all__ = [
    "Backend",
    "FixtureError",
    "LiveBackendUnavailable",
    "ReplayBackend",
    "ReplayMiss",
    "ScriptedBackend",
    "get_backend",
    "replay_key",
]

KEY_VERSION = 1
LIVE_ENV = "JEV_COOKBOOK_LIVE"
KEY_PATTERN = re.compile(r"[0-9a-f]{64}")


class ReplayMiss(LookupError):
    """No stored response exists for the request. ``.key`` is the missing replay key."""

    def __init__(self, key: str, names: Sequence[str], known: int) -> None:
        self.key = key
        super().__init__(
            f"no stored response for replay key {key} (questions: {', '.join(names)}; "
            f"{known} stored response(s) loaded). Replay never invents an answer. Either the "
            "state or a question definition changed since the fixture was written (re-run "
            "the recipe's fixture builder), or this request has no fixture yet (add a "
            "synthetic response under this key, or record one with the live backend)."
        )


class FixtureError(ValueError):
    """A stored response is malformed or does not fit the questions asked."""


class LiveBackendUnavailable(RuntimeError):
    """``JEV_COOKBOOK_LIVE=1`` was set but no live backend is available."""


def _check_request(
    state: Any, questions: Mapping[str, Question]
) -> tuple[Any, dict[str, Question]]:
    if not (
        type(state) is str
        or type(state) is dict
        or (type(state) in (list, tuple) and all(type(x) is str for x in state))
    ):
        raise TypeError("state must be a string, a JSON object, or an array of strings")
    if not isinstance(questions, Mapping) or not questions:
        raise ValueError("questions must be a non-empty mapping of name -> question")
    checked: dict[str, Question] = {}
    for name, q in questions.items():
        if type(name) is not str or not name:
            raise ValueError(f"question names must be non-empty str, got {name!r}")
        if not isinstance(q, (Noul, Choice, Score)):
            raise TypeError(f"question {name!r} must be Noul, Choice or Score, got {type(q)}")
        checked[name] = q
    return plain_json(state, "state"), checked


def replay_key(state: Any, questions: Mapping[str, Question]) -> str:
    """Stable 64-hex-character key for a request (see docs/backends.md for the exact rule).

    SHA-256 of the canonical JSON of ``{"v": 1, "state": ..., "questions": {name:
    question.to_dict()}}``: question names sorted; every other object key (state keys,
    Choice options) and every array in the order written; no whitespace, ASCII escapes,
    shortest-repr floats. Nothing else is normalized.
    """
    plain_state, checked = _check_request(state, questions)
    payload = {
        "v": KEY_VERSION,
        "state": plain_state,
        "questions": {name: checked[name].to_dict() for name in sorted(checked)},
    }
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


@runtime_checkable
class Backend(Protocol):
    """The one interface notebooks call.

    ``mode`` is ``"synthetic"``, ``"recorded"``, ``"scripted"`` or ``"live"``; ``model`` is
    the model string results carry (``"synthetic"`` for the offline synthetic modes).
    """

    mode: str
    model: str

    def decide(self, state: Any, questions: Mapping[str, Question]) -> DecisionResult:
        """Answer every named question about ``state``."""
        ...


def _check_fits(name: str, question: Question, answer: Answer) -> None:
    ok = {Noul: NoulAnswer, Choice: ChoiceAnswer, Score: ScoreAnswer}[type(question)]
    if not isinstance(answer, ok):
        raise FixtureError(
            f"question {name!r} is {question.type} but the stored answer is {answer.type}"
        )
    if isinstance(answer, ChoiceAnswer) and set(answer.probabilities) != set(question.criteria):
        raise FixtureError(f"{name!r}: probabilities keys differ from the question's options")
    if isinstance(answer, ScoreAnswer) and len(answer.probabilities) != len(question.criteria):
        raise FixtureError(f"{name!r}: score has a different number of levels than the question")


def _check_result(questions: Mapping[str, Question], result: DecisionResult) -> None:
    if set(result.answers) != set(questions):
        raise FixtureError(
            f"stored answers {sorted(result.answers)} differ from questions {sorted(questions)}"
        )
    for name, q in questions.items():
        _check_fits(name, q, result.answers[name])


class ReplayBackend:
    """Replay stored responses.

    ``responses`` maps a replay key to a stored response: exactly ``DecisionResult.to_dict()``
    (``synthetic`` and ``recorded`` answers both replay; provenance is kept per answer).
    Every response is parsed when the backend is built, so a bad fixture fails early and
    names its key. ``mode`` (``synthetic`` or ``recorded``), ``model`` and ``recorded_dates``
    (sorted unique dates) come from the fixture provenance; a fixture set that mixes
    synthetic and recorded answers, or more than one model, is rejected. Every hit returns a
    fresh ``DecisionResult`` built from a private copy of the stored response, so nothing a
    caller changes (including a legend value that is a JSON object or array) reaches a
    later replay.
    """

    def __init__(self, responses: Mapping[str, Mapping[str, Any]]) -> None:
        self._results: dict[str, DecisionResult] = {}
        self._stored: dict[str, dict[str, Any]] = {}
        for key, stored in responses.items():
            if type(key) is not str or not KEY_PATTERN.fullmatch(key):
                raise FixtureError(f"replay key must be 64 lowercase hex characters, got {key!r}")
            try:
                self._results[key] = DecisionResult.from_dict(stored)
                self._stored[key] = copy.deepcopy(self._results[key].to_dict())
            except (ValueError, TypeError) as exc:
                raise FixtureError(f"stored response {key}: {exc}") from exc
        if not self._results:
            raise FixtureError("a replay backend needs at least one stored response")
        sources = {r.source for r in self._results.values()}
        models = {r.model for r in self._results.values()}
        if len(sources) > 1:
            raise FixtureError("fixtures mix synthetic and recorded answers")
        if len(models) > 1:
            raise FixtureError(f"fixtures come from more than one model: {sorted(models)}")
        self.mode: str = sources.pop()
        self.model: str = models.pop()
        self.recorded_dates: tuple[str, ...] = tuple(
            sorted(
                {
                    a.provenance.date
                    for r in self._results.values()
                    for a in r.answers.values()
                    if a.provenance.source == RECORDED_SOURCE and a.provenance.date
                }
            )
        )

    @classmethod
    def from_json(cls, path: str | os.PathLike[str]) -> ReplayBackend:
        """Load a JSON file holding one object: ``{replay_key: stored_response, ...}``."""

        def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for k, v in pairs:
                if k in out:
                    raise FixtureError(f"{path}: duplicate key {k!r}")
                out[k] = v
            return out

        with open(path, encoding="utf-8", newline="") as fh:
            data = json.load(fh, object_pairs_hook=no_duplicates)
        if not isinstance(data, dict):
            raise FixtureError(f"{path}: expected a JSON object of replay_key -> response")
        return cls(data)

    def keys(self) -> list[str]:
        return sorted(self._results)

    def decide(self, state: Any, questions: Mapping[str, Question]) -> DecisionResult:
        key = replay_key(state, questions)
        result = self._results.get(key)
        if result is None:
            raise ReplayMiss(key, sorted(questions), len(self._results))
        try:
            _check_result(questions, result)
        except FixtureError as exc:
            raise FixtureError(f"stored response {key}: {exc}") from exc
        return DecisionResult.from_dict(self._stored[key])


# A scripted spec is the minimal description of an answer:
#   Noul   -> float probability of yes
#   Choice -> option name (all weight on it) or {option: non-negative weight}
#   Score  -> list of non-negative weights, one per level
# Weights are normalized to probabilities. A ready-made synthetic Answer is also accepted.
Spec = Any
ScriptFn = Callable[[Any, Mapping[str, Question], random.Random], Mapping[str, Spec]]


def _normalize(weights: Sequence[float], what: str) -> list[float]:
    for w in weights:
        if type(w) not in (int, float) or not w >= 0 or w == float("inf"):
            raise ValueError(f"{what}: weights must be finite numbers >= 0, got {w!r}")
    total = math.fsum(weights)
    if total <= 0:
        raise ValueError(f"{what}: weights must not all be zero")
    return [w / total for w in weights]


def _build(name: str, q: Question, spec: Spec) -> Answer:
    prov = Provenance.synthetic()
    if isinstance(spec, (NoulAnswer, ChoiceAnswer, ScoreAnswer)):
        if spec.provenance.source != SYNTHETIC_SOURCE:
            raise ValueError(f"{name!r}: scripted answers must be synthetic")
        return spec
    if isinstance(q, Noul):
        return NoulAnswer(spec, prov)
    if isinstance(q, Choice):
        options = list(q.criteria)
        if isinstance(spec, str):
            spec = {spec: 1.0}
        if not isinstance(spec, Mapping) or not set(spec) <= set(options):
            raise ValueError(f"{name!r}: choice spec must name options from {options}")
        probs = _normalize([spec.get(o, 0.0) for o in options], name)
        return ChoiceAnswer.from_probabilities(dict(zip(options, probs, strict=True)), prov)
    if isinstance(spec, (str, Mapping)) or len(spec) != len(q.criteria):
        raise ValueError(f"{name!r}: score spec needs {len(q.criteria)} weights, one per level")
    probs = _normalize(list(spec), name)
    return ScoreAnswer.from_probabilities(probs, q.criteria, prov)


class ScriptedBackend:
    """Deterministic, seeded stand-in driven by ``script(state, questions, rng)``.

    ``script`` returns ``{question_name: spec}`` (see ``Spec`` above). ``rng`` is a
    ``random.Random`` seeded from ``(seed, replay_key)``, so the same request gives the
    same answers with the same seed on every platform, regardless of call order. Use only
    ``rng.random()`` in scripts: its stream is stable across Python versions. Answers are
    always ``synthetic``, the result model is ``"synthetic"``, and usage is empty.
    """

    def __init__(self, script: ScriptFn, seed: int = 0) -> None:
        if type(seed) is not int:
            raise TypeError("seed must be an int")
        self._script = script
        self.seed = seed
        self.mode: str = "scripted"
        self.model: str = SYNTHETIC_MODEL

    def rng_for(self, state: Any, questions: Mapping[str, Question]) -> random.Random:
        digest = hashlib.sha256(f"{self.seed}:{replay_key(state, questions)}".encode()).hexdigest()
        return random.Random(int(digest[:16], 16))

    def decide(self, state: Any, questions: Mapping[str, Question]) -> DecisionResult:
        plain_state, checked = _check_request(state, questions)
        specs = self._script(plain_state, checked, self.rng_for(state, questions))
        if set(specs) != set(checked):
            raise ValueError(f"script returned {sorted(specs)} but questions are {sorted(checked)}")
        answers = {name: _build(name, checked[name], specs[name]) for name in checked}
        for name, answer in answers.items():
            try:
                _check_fits(name, checked[name], answer)
            except FixtureError as exc:
                raise ValueError(f"script answer for {exc}") from exc
        return DecisionResult(answers, SYNTHETIC_MODEL, Usage())


def _make_live_backend(**kwargs: Any) -> Backend:
    """Hook ``get_backend`` calls under ``JEV_COOKBOOK_LIVE=1``: builds the live backend."""
    from .live import live_backend_from_env  # lazy: live.py imports this module

    return live_backend_from_env(**kwargs)


def get_backend(
    *,
    fixtures: Mapping[str, Mapping[str, Any]] | str | os.PathLike[str] | None = None,
    script: ScriptFn | None = None,
    seed: int = 0,
) -> Backend:
    """Return the backend a notebook should use.

    Offline (default): ``script`` gives a ``ScriptedBackend`` (with ``seed``); otherwise
    ``fixtures`` (a mapping, or a path to a JSON file) gives a ``ReplayBackend``. Passing
    both, or neither, is an error. ``JEV_COOKBOOK_LIVE=1`` selects the live backend and
    raises ``LiveBackendUnavailable`` until it exists; it never falls back to replay. Any
    other value than unset, empty, ``0`` or ``1`` is an error. The variable is read when
    this function is called, never at import.
    """
    live = os.environ.get(LIVE_ENV, "")
    if live not in ("", "0", "1"):
        raise ValueError(f"{LIVE_ENV} must be 1 (live) or unset/0 (offline), got {live!r}")
    if live == "1":
        return _make_live_backend(fixtures=fixtures, script=script, seed=seed)
    if (fixtures is None) == (script is None):
        raise ValueError("pass exactly one of fixtures=... (replay) or script=... (scripted)")
    if script is not None:
        return ScriptedBackend(script, seed)
    if isinstance(fixtures, Mapping):
        return ReplayBackend(fixtures)
    return ReplayBackend.from_json(Path(fixtures))
