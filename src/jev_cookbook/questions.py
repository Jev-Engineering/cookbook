"""Question definitions mirroring the TypeSafe ``Noul``, ``Choice`` and ``Score`` requests.

Shapes follow ``typesafe_sdk``: ``instructions`` is text, a JSON object or an array (or
``None``); ``Choice.criteria`` is a mapping of option name to an optional description;
``Score.criteria`` is a non-empty ordered list, one description per level starting at 0;
``Noul.criteria`` optionally describes the ``true`` and ``false`` outcomes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from ._canonical import plain_json

__all__ = ["Choice", "Noul", "Question", "Score", "question_from_dict"]


def _instructions(value: Any) -> Any:
    return plain_json(value, "instructions")


@dataclass(frozen=True)
class Noul:
    """A yes/no question; the answer is the probability of yes."""

    instructions: Any = None
    criteria: Mapping[str, Any] | None = None
    type: ClassVar[str] = "noul"

    def __post_init__(self) -> None:
        object.__setattr__(self, "instructions", _instructions(self.instructions))
        crit = self.criteria
        if crit is not None:
            crit = plain_json(dict(crit), "criteria")
            extra = set(crit) - {"true", "false"}
            if extra:
                raise ValueError(f"Noul criteria keys must be 'true'/'false', got {sorted(extra)}")
            crit = {k: v for k, v in crit.items() if v is not None} or None
        object.__setattr__(self, "criteria", crit)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "noul", "instructions": self.instructions, "criteria": self.criteria}


@dataclass(frozen=True)
class Choice:
    """Pick one named option. ``criteria`` maps option name to a description or ``None``.

    The options are an unordered set for replay-key purposes.
    """

    criteria: Mapping[str, Any]
    instructions: Any = None
    type: ClassVar[str] = "choice"

    def __post_init__(self) -> None:
        if not isinstance(self.criteria, Mapping) or not self.criteria:
            raise ValueError("Choice criteria must be a non-empty mapping of option -> description")
        crit = plain_json(dict(self.criteria), "criteria")
        if any(k == "" for k in crit):
            raise ValueError("Choice option names must be non-empty")
        object.__setattr__(self, "criteria", crit)
        object.__setattr__(self, "instructions", _instructions(self.instructions))

    def to_dict(self) -> dict[str, Any]:
        return {"type": "choice", "instructions": self.instructions, "criteria": self.criteria}


@dataclass(frozen=True)
class Score:
    """Rate against ordered levels. ``criteria[i]`` describes level ``i`` (from zero)."""

    criteria: Sequence[Any]
    instructions: Any = None
    type: ClassVar[str] = "score"

    def __post_init__(self) -> None:
        if isinstance(self.criteria, (str, Mapping)) or not isinstance(self.criteria, Sequence):
            raise ValueError("Score criteria must be a non-empty ordered list of descriptions")
        if not self.criteria:
            raise ValueError("Score criteria must be a non-empty ordered list of descriptions")
        object.__setattr__(self, "criteria", plain_json(list(self.criteria), "criteria"))
        object.__setattr__(self, "instructions", _instructions(self.instructions))

    def to_dict(self) -> dict[str, Any]:
        return {"type": "score", "instructions": self.instructions, "criteria": self.criteria}


Question = Noul | Choice | Score


def question_from_dict(data: Mapping[str, Any]) -> Question:
    """Inverse of ``to_dict``. Unknown keys are rejected."""
    data = dict(data)
    kind = data.pop("type", None)
    allowed = {"instructions", "criteria"}
    if set(data) - allowed:
        raise ValueError(f"unknown question keys: {sorted(set(data) - allowed)}")
    if kind == "noul":
        return Noul(data.get("instructions"), data.get("criteria"))
    if kind == "choice":
        return Choice(data.get("criteria"), data.get("instructions"))
    if kind == "score":
        return Score(data.get("criteria"), data.get("instructions"))
    raise ValueError(f"unknown question type: {kind!r}")
