"""Typed answers, provenance, usage and the result of one decision call.

Value types follow the TypeSafe response schema: ``noul`` is the probability of yes
(float, 0 to 1); ``probabilities`` maps option name (Choice, ``str``) or level index
(Score, ``int`` 0, 1, ...; JSON string keys in ``to_dict``) to a float; ``confidence`` is a float from 0 to 1; Score's
``score`` is the probability-weighted average level (a float, may fall between levels)
and ``legend`` maps the same level strings to the criteria descriptions.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ._canonical import plain_json

__all__ = [
    "Answer",
    "ChoiceAnswer",
    "DecisionResult",
    "NoulAnswer",
    "Provenance",
    "ScoreAnswer",
    "Usage",
    "answer_from_dict",
]

SYNTHETIC_SOURCE = "synthetic"
RECORDED_SOURCE = "recorded"


def _unit(value: Any, what: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{what} must be a number from 0 to 1, got {value!r}")
    return float(value)


def _prob_map(value: Any, what: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{what} must be a non-empty mapping")
    out: dict[str, float] = {}
    for k, v in value.items():
        if type(k) is not str:
            raise ValueError(f"{what} keys must be str, got {k!r}")
        out[k] = _unit(v, f"{what}[{k!r}]")
    return out


def _prob_map_any(value: Any, what: str) -> Mapping[Any, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{what} must be a non-empty mapping")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], what: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise ValueError(f"unknown {what} keys: {sorted(extra)}")


@dataclass(frozen=True)
class Provenance:
    """Where an answer came from.

    ``source`` is ``"synthetic"`` (written by hand or by a script; ``model`` and ``date``
    must be ``None``) or ``"recorded"`` (a real API response; ``model`` is the model
    string the API returned and ``date`` is ``YYYY-MM-DD``, both required).
    """

    source: str
    model: str | None = None
    date: str | None = None

    def __post_init__(self) -> None:
        if self.source == SYNTHETIC_SOURCE:
            if self.model is not None or self.date is not None:
                raise ValueError("synthetic provenance must not carry a model or date")
        elif self.source == RECORDED_SOURCE:
            if type(self.model) is not str or not self.model:
                raise ValueError("recorded provenance requires the model string")
            if type(self.date) is not str:
                raise ValueError("recorded provenance requires a date as YYYY-MM-DD")
            try:
                parsed = datetime.date.fromisoformat(self.date)
            except ValueError:
                raise ValueError(f"date must be YYYY-MM-DD, got {self.date!r}") from None
            if parsed.isoformat() != self.date:
                raise ValueError(f"date must be YYYY-MM-DD, got {self.date!r}")
        else:
            raise ValueError(
                f"provenance source must be 'synthetic' or 'recorded': {self.source!r}"
            )

    @classmethod
    def synthetic(cls) -> Provenance:
        return cls(SYNTHETIC_SOURCE)

    @classmethod
    def recorded(cls, model: str, date: str) -> Provenance:
        return cls(RECORDED_SOURCE, model, date)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "model": self.model, "date": self.date}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Provenance:
        _reject_unknown(data, {"source", "model", "date"}, "provenance")
        return cls(data.get("source"), data.get("model"), data.get("date"))


def _check_provenance(value: Any) -> None:
    if not isinstance(value, Provenance):
        raise TypeError("every answer needs a Provenance (Provenance.synthetic() or .recorded())")


@dataclass(frozen=True)
class NoulAnswer:
    """Yes/no answer: ``noul`` is the probability of yes, 0 to 1."""

    noul: float
    provenance: Provenance
    type: ClassVar[str] = "noul"

    def __post_init__(self) -> None:
        object.__setattr__(self, "noul", _unit(self.noul, "noul"))
        _check_provenance(self.provenance)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "noul", "noul": self.noul, "provenance": self.provenance.to_dict()}


@dataclass(frozen=True)
class ChoiceAnswer:
    """Selected option, its probability per option, and confidence (all 0 to 1)."""

    choice: str
    probabilities: Mapping[str, float]
    confidence: float
    provenance: Provenance
    type: ClassVar[str] = "choice"

    def __post_init__(self) -> None:
        probs = _prob_map(self.probabilities, "probabilities")
        if self.choice not in probs:
            raise ValueError(f"choice {self.choice!r} is not one of {sorted(probs)}")
        object.__setattr__(self, "probabilities", probs)
        object.__setattr__(self, "confidence", _unit(self.confidence, "confidence"))
        _check_provenance(self.provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "choice",
            "choice": self.choice,
            "probabilities": dict(self.probabilities),
            "confidence": self.confidence,
            "provenance": self.provenance.to_dict(),
        }


def _level_keys(value: Mapping[Any, Any], what: str) -> dict[int, Any]:
    """Accept int keys or their JSON string form ("0", "1", ...); return int keys 0..n-1."""
    out: dict[int, Any] = {}
    for k, v in value.items():
        if type(k) is str and k.isascii() and k.isdigit():
            k = int(k)
        if type(k) is not int:
            raise ValueError(f"{what} keys must be level indexes 0, 1, 2, ..., got {k!r}")
        out[k] = v
    if sorted(out) != list(range(len(out))) or not out:
        raise ValueError(f"{what} keys must be exactly 0..n-1, got {sorted(out)}")
    return dict(sorted(out.items()))


@dataclass(frozen=True)
class ScoreAnswer:
    """Expected score, probability per level, confidence, and the level legend.

    ``probabilities`` and ``legend`` are keyed by level index as ``int`` (``0``, ``1``,
    ...), as in ``typesafe_sdk``. ``to_dict()`` writes the keys as JSON strings.
    """

    score: float
    probabilities: Mapping[int, float]
    confidence: float
    legend: Mapping[int, Any]
    provenance: Provenance
    type: ClassVar[str] = "score"

    def __post_init__(self) -> None:
        probs = _level_keys(_prob_map_any(self.probabilities, "probabilities"), "probabilities")
        legend = _level_keys(dict(self.legend), "legend")
        if sorted(legend) != sorted(probs):
            raise ValueError("score legend and probabilities must cover the same levels")
        object.__setattr__(self, "legend", {k: plain_json(v, "legend") for k, v in legend.items()})
        score = self.score
        if type(score) not in (int, float) or not 0 <= score <= len(probs) - 1:
            raise ValueError(f"score must be a number from 0 to {len(probs) - 1}, got {score!r}")
        object.__setattr__(self, "score", float(score))
        object.__setattr__(
            self, "probabilities", {k: _unit(v, "probabilities") for k, v in probs.items()}
        )
        object.__setattr__(self, "confidence", _unit(self.confidence, "confidence"))
        _check_provenance(self.provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "score",
            "score": self.score,
            "probabilities": {str(k): v for k, v in self.probabilities.items()},
            "confidence": self.confidence,
            "legend": {str(k): v for k, v in self.legend.items()},
            "provenance": self.provenance.to_dict(),
        }


Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer


def answer_from_dict(data: Mapping[str, Any]) -> Answer:
    """Inverse of ``to_dict``. Unknown keys and missing provenance are rejected."""
    data = dict(data)
    kind = data.pop("type", None)
    if "provenance" not in data:
        raise ValueError("answer is missing provenance")
    prov = Provenance.from_dict(data.pop("provenance"))
    if kind == "noul":
        _reject_unknown(data, {"noul"}, "noul answer")
        return NoulAnswer(data.get("noul"), prov)
    if kind == "choice":
        _reject_unknown(data, {"choice", "probabilities", "confidence"}, "choice answer")
        return ChoiceAnswer(
            data.get("choice"), data.get("probabilities"), data.get("confidence"), prov
        )
    if kind == "score":
        _reject_unknown(data, {"score", "probabilities", "confidence", "legend"}, "score answer")
        return ScoreAnswer(
            data.get("score"),
            data.get("probabilities"),
            data.get("confidence"),
            data.get("legend"),
            prov,
        )
    raise ValueError(f"unknown answer type: {kind!r}")


@dataclass(frozen=True)
class Usage:
    """Token counts as reported by the API; either may be ``None`` (not reported)."""

    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens"):
            v = getattr(self, name)
            if v is not None and (type(v) is not int or v < 0):
                raise ValueError(f"{name} must be a non-negative int or None, got {v!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Usage:
        _reject_unknown(data, {"input_tokens", "output_tokens"}, "usage")
        return cls(data.get("input_tokens"), data.get("output_tokens"))


@dataclass(frozen=True)
class DecisionResult:
    """Named answers plus the ``model`` string and ``usage`` of the call.

    ``to_dict()`` is exactly the stored-response format replay reads.
    """

    answers: Mapping[str, Answer]
    model: str
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        if type(self.model) is not str or not self.model:
            raise ValueError("model must be a non-empty string")
        object.__setattr__(self, "answers", dict(self.answers))

    def __getitem__(self, name: str) -> Answer:
        return self.answers[name]

    @property
    def nouls(self) -> dict[str, NoulAnswer]:
        return {k: v for k, v in self.answers.items() if isinstance(v, NoulAnswer)}

    @property
    def choices(self) -> dict[str, ChoiceAnswer]:
        return {k: v for k, v in self.answers.items() if isinstance(v, ChoiceAnswer)}

    @property
    def scores(self) -> dict[str, ScoreAnswer]:
        return {k: v for k, v in self.answers.items() if isinstance(v, ScoreAnswer)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "usage": self.usage.to_dict(),
            "answers": {k: v.to_dict() for k, v in self.answers.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DecisionResult:
        _reject_unknown(data, {"model", "usage", "answers"}, "result")
        answers = data.get("answers")
        if not isinstance(answers, Mapping):
            raise ValueError("result 'answers' must be a mapping")
        return cls(
            {k: answer_from_dict(v) for k, v in answers.items()},
            data.get("model"),
            Usage.from_dict(data.get("usage") or {}),
        )
