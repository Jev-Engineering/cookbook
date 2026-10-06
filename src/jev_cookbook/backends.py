"""Decision backends: one call, ``decide(state, questions)``, offline or (later) live.

``ReplayBackend`` answers from stored responses keyed by ``replay_key``; ``ScriptedBackend``
answers from a seeded function; ``get_backend`` picks one. The live backend arrives in a
separate change and plugs into ``get_backend`` through ``_make_live_backend``.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ._canonical import canonical_json, plain_json
from .answers import (
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
SCRIPTED_MODEL = "synthetic-scripted"


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
    if state is None:
        raise ValueError("state cannot be None (use a string, object or array)")
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
    question.to_dict()}}``: sorted object keys, no whitespace, ASCII escapes, newlines
    normalized to LF, shortest-repr floats. Score criteria keep their order; Choice
    options and question names are unordered.
    """
    plain_state, checked = _check_request(state, questions)
    payload = {
        "v": KEY_VERSION,
        "state": plain_state,
        "questions": {name: q.to_dict() for name, q in checked.items()},
    }
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


@runtime_checkable
class Backend(Protocol):
    """The one interface notebooks call."""

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
    names its key.
    """

    def __init__(self, responses: Mapping[str, Mapping[str, Any]]) -> None:
        self._results: dict[str, DecisionResult] = {}
        for key, stored in responses.items():
            try:
                self._results[key] = DecisionResult.from_dict(stored)
            except (ValueError, TypeError) as exc:
                raise FixtureError(f"stored response {key}: {exc}") from exc

    @classmethod
    def from_json(cls, path: str | os.PathLike[str]) -> ReplayBackend:
        """Load a JSON file holding one object: ``{replay_key: stored_response, ...}``."""
        with open(path, encoding="utf-8", newline="") as fh:
            data = json.load(fh)
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
        return result


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
    total = sum(weights)
    if total <= 0:
        raise ValueError(f"{what}: weights must not all be zero")
    return [w / total for w in weights]


def _choice_confidence(probs: Sequence[float]) -> float:
    n = len(probs)
    if n == 1:
        return 1.0
    return min(1.0, max(0.0, (n * max(probs) - 1) / (n - 1)))


def _score_confidence(probs: Sequence[float]) -> float:
    n = len(probs)
    if n == 1:
        return 1.0
    peak = probs.index(max(probs))
    spread = sum(p * abs(i - peak) for i, p in enumerate(probs))
    even = sum(abs(i - (n - 1) / 2) for i in range(n)) / n
    return min(1.0, max(0.0, 1 - spread / even))


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
        top = probs.index(max(probs))
        return ChoiceAnswer(
            options[top], dict(zip(options, probs, strict=True)), _choice_confidence(probs), prov
        )
    if isinstance(spec, (str, Mapping)) or len(spec) != len(q.criteria):
        raise ValueError(f"{name!r}: score spec needs {len(q.criteria)} weights, one per level")
    probs = _normalize(list(spec), name)
    keys = list(range(len(probs)))
    return ScoreAnswer(
        sum(i * p for i, p in enumerate(probs)),
        dict(zip(keys, probs, strict=True)),
        _score_confidence(probs),
        dict(zip(keys, q.criteria, strict=True)),
        prov,
    )


class ScriptedBackend:
    """Deterministic, seeded stand-in driven by ``script(state, questions, rng)``.

    ``script`` returns ``{question_name: spec}`` (see ``Spec`` above). ``rng`` is a
    ``random.Random`` seeded from ``(seed, replay_key)``, so the same request gives the
    same answers with the same seed on every platform, regardless of call order. Use only
    ``rng.random()`` in scripts: its stream is stable across Python versions. Answers are
    always ``synthetic``, the result model is ``"synthetic-scripted"``, and usage is empty.
    """

    def __init__(self, script: ScriptFn, seed: int = 0) -> None:
        if type(seed) is not int:
            raise TypeError("seed must be an int")
        self._script = script
        self.seed = seed

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
        return DecisionResult(answers, SCRIPTED_MODEL, Usage())


def _make_live_backend(**kwargs: Any) -> Backend:
    """Hook for the live backend (issue #64 replaces this body)."""
    raise LiveBackendUnavailable(
        f"{LIVE_ENV}=1 is set, but the live backend is not part of this version of "
        f"jev_cookbook. Unset {LIVE_ENV} to run offline from fixtures or a script."
    )


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
