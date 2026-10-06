# Decision backends

One interface, `backend.decide(state, questions)`, that a notebook calls the same way offline
(replay or scripted) and, once it exists, live.

```python
from jev_cookbook import Choice, Noul, Score, get_backend

state = {"document": "I was charged twice. Please fix this ASAP."}
questions = {
    "billing": Noul(instructions="Is this ticket about billing?"),
    "tone": Choice(
        instructions="What is the customer's tone?",
        criteria={"calm": None, "frustrated": None, "angry": None},
    ),
    "urgency": Score(
        instructions="How urgent is this ticket?",
        criteria=["can wait", "this week", "today"],
    ),
}

backend = get_backend(fixtures="fixtures/responses.json")  # replay
# backend = get_backend(script=my_script, seed=0)           # scripted
result = backend.decide(state, questions)

result["billing"].noul  # float, probability of yes
result["tone"].choice  # "angry"
result["urgency"].score  # float, may fall between levels
result.model, result.usage  # model string and token counts
result["tone"].provenance.source  # "synthetic" or "recorded"
```

## Questions

They mirror `typesafe_sdk`. `instructions` is text, a JSON object or array, or `None`.
`Choice(criteria={name: description-or-None})` takes a non-empty mapping.
`Score(criteria=[...])` takes a non-empty ordered list, one description per level from 0.
`Noul(criteria={"true": ..., "false": ...})` optionally describes the outcomes.
All values must be plain JSON (`str`, `int`, `float`, `bool`, `None`, `list`, `dict` with `str`
keys); numpy values and NaN are rejected. `to_dict()` / `question_from_dict()` convert them.

## Answers

| Class | Fields (value types) |
| - | - |
| `NoulAnswer` | `noul: float` (probability of yes, 0 to 1) |
| `ChoiceAnswer` | `choice: str`, `probabilities: {option: float}`, `confidence: float` |
| `ScoreAnswer` | `score: float`, `probabilities: {int: float}`, `confidence: float`, `legend: {int: criteria}` |

Every answer also has `provenance: Provenance` (`source`, `model`, `date`). Score level keys are
`int` in memory (as in `typesafe_sdk`) and JSON strings (`"0"`, `"1"`, ...) in `to_dict()`.
`DecisionResult` has `answers`, `model`, `usage`, `result[name]`, and the groupings `nouls`,
`choices`, `scores`. Each class has `to_dict()` / `from_dict()` (`answer_from_dict` for answers).

Provenance: `Provenance.synthetic()` (no model, no date) or `Provenance.recorded(model, "YYYY-MM-DD")`
(the model string the API returned, and the date). Nothing may be labelled `recorded` unless it came
from a real API call.

## Stored response (what replay reads)

A stored response is exactly `DecisionResult.to_dict()`; a fixture file is a JSON object
`{replay_key: stored_response}` (the on-disk format is finalized by the fixture validator).

```json
{
  "model": "synthetic-fixture",
  "usage": {"input_tokens": null, "output_tokens": null},
  "answers": {
    "billing": {"type": "noul", "noul": 0.97,
                "provenance": {"source": "synthetic", "model": null, "date": null}},
    "tone": {"type": "choice", "choice": "angry",
             "probabilities": {"calm": 0.05, "frustrated": 0.15, "angry": 0.8}, "confidence": 0.7,
             "provenance": {"source": "synthetic", "model": null, "date": null}},
    "urgency": {"type": "score", "score": 1.8,
                "probabilities": {"0": 0.0, "1": 0.2, "2": 0.8}, "confidence": 0.6,
                "legend": {"0": "can wait", "1": "this week", "2": "today"},
                "provenance": {"source": "synthetic", "model": null, "date": null}}
  }
}
```

Unknown keys are errors, and provenance is required on every answer. On replay the answers must
match the questions asked (same names, same types, same options or number of levels), or
`FixtureError` is raised.

## Replay key

`replay_key(state, questions)` is the lowercase hex SHA-256 of the ASCII bytes of the canonical
JSON of `{"v": 1, "state": <state>, "questions": {<name>: <question.to_dict()>, ...}}`.

Canonical JSON: object keys sorted, separators `,` and `:` with no spaces, `ensure_ascii=True`
(non-ASCII becomes `\uXXXX`), `allow_nan=False`, floats and ints as Python writes them (shortest
round-trip `repr`, identical on all platforms and Python 3.10 to 3.14), `-0.0` written as `0.0`,
and every `\r\n` or lone `\r` in any string (keys included) replaced by `\n`. Nothing else is
normalized: `1` and `1.0` differ, and Unicode is not re-normalized. It never uses `hash()`.

What changes the key: the state, question names, each question's type, `instructions`, and
`criteria` (Score level order matters; Choice options are an unordered set; Noul criteria with
all-`None` values equal no criteria). What does not: dict insertion order, Choice option order,
question order, platform newlines. The key version `v` is bumped if this rule ever changes.

A miss raises `ReplayMiss` (a `LookupError`) whose message and `.key` give the missing key; the
fix is to rebuild or add the fixture for that key. Replay never fabricates an answer.

## Scripted backend

`ScriptedBackend(script, seed=0)` calls `script(state, questions, rng)` and expects
`{name: spec}`: a float for `Noul`; an option name or `{option: weight}` for `Choice`; a list of
per-level weights for `Score`. Weights are normalized; `confidence` is computed with the formulas
on the TypeSafe confidence page. `rng` is a `random.Random` seeded from `(seed, replay_key)`, so
the same request gives the same answers on every platform, whatever the call order; use only
`rng.random()`. Answers are always `synthetic`, model `"synthetic-scripted"`, empty usage. These
numbers say nothing about how Jev performs.

## `get_backend`

`get_backend(*, fixtures=None, script=None, seed=0)` returns a `ScriptedBackend` (script) or a
`ReplayBackend` (fixtures: a mapping or a JSON path); pass exactly one. `JEV_COOKBOOK_LIVE=1`
selects the live backend and currently raises `LiveBackendUnavailable`; it never falls back to
replay. Values other than unset, empty, `0`, `1` are an error. The environment is read when
`get_backend` is called, not at import.
