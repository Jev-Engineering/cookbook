"""Shared code for the Jev Cookbook.

Importing this package must stay free of side effects: no network access, no
API key lookup, and no import of the optional ``typesafe-sdk``.

Typical notebook use (see ``docs/backends.md``)::

    from jev_cookbook import Choice, Noul, Score, get_backend

    backend = get_backend(fixtures="fixtures.json")
    result = backend.decide(state, {"billing": Noul(instructions="Is this billing?")})
    result["billing"].noul
"""

from .answers import (
    Answer,
    ChoiceAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    ScoreAnswer,
    Usage,
    answer_from_dict,
)
from .backends import (
    Backend,
    FixtureError,
    LiveBackendUnavailable,
    ReplayBackend,
    ReplayMiss,
    ScriptedBackend,
    get_backend,
    replay_key,
)
from .questions import Choice, Noul, Question, Score, question_from_dict

__version__ = "0.1.0"

__all__ = [
    "Answer",
    "Backend",
    "Choice",
    "ChoiceAnswer",
    "DecisionResult",
    "FixtureError",
    "LiveBackendUnavailable",
    "Noul",
    "NoulAnswer",
    "Provenance",
    "Question",
    "ReplayBackend",
    "ReplayMiss",
    "Score",
    "ScoreAnswer",
    "ScriptedBackend",
    "Usage",
    "__version__",
    "answer_from_dict",
    "get_backend",
    "question_from_dict",
    "replay_key",
]
