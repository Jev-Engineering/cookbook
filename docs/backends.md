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

They mirror `typesafe_sdk`, and every constructor takes keyword arguments only. `instructions` is
text, a JSON object or array, or `None`. `Choice(criteria={name: description-or-None})` takes a
non-empty mapping of at most 255 options. `Score(criteria=[...])` takes an ordered list of 2 to 10
levels (each non-empty text, a non-empty JSON object or a non-empty JSON array; the legend holds the level value as given, so a legend value may be text, an object or an array). `Noul(criteria={"true": ..., "false": ...})` optionally
describes the outcomes. All values must be plain JSON (`str`, `int`, `float`, `bool`, `None`,
`list`, `dict` with `str` keys); numpy values and NaN are rejected. `to_dict()` /
`question_from_dict()` convert them.

The `state` passed to `decide` and `replay_key` is a string, a JSON object (`dict`), or an array
(`list`/`tuple`) of strings. Bare numbers, booleans and `None` are rejected with `TypeError`.

## Answers

| Class | Fields (value types) |
| - | - |
| `NoulAnswer` | `noul: float` (probability of yes, 0 to 1) |
| `ChoiceAnswer` | `choice: str`, `probabilities: {option: float}`, `confidence: float` |
| `ScoreAnswer` | `score: float`, `probabilities: {int: float}`, `confidence: float`, `legend: {int: str \| object \| array}` |

Every answer also has `provenance: Provenance` (`source`, `model`, `date`). Score level keys are
`int` in memory (as in `typesafe_sdk`) and JSON strings (`"0"`, `"1"`, ...) in `to_dict()`; level
keys must be canonical decimal integers (`"00"` is rejected, and so is a duplicate level after
conversion). Answers are immutable: mappings are read-only views. A legend value that is a JSON
object or array stays an ordinary `dict`/`list` inside the result, so replay builds a fresh result
from a private copy on every call: whatever you change in a returned result never reaches a later
replay. `to_dict()` also returns a fresh copy you may edit.

Construction is validated: probabilities sum to 1 (the error message says what they summed
to); `choice` is the highest-probability option (a gap under 1e-3 counts as a tie); `confidence`
equals the published formulas (Choice
`(p_max - 1/n) / (1 - 1/n)`, one option gives 1; Score `1 - spread / even_spread`, where `spread`
is the probability-weighted distance from the most likely level and `even_spread` is the same
quantity for a uniform distribution, see the TypeSafe confidence page); Score `score` equals the
probability-weighted level. Tolerances are in the next subsection. To avoid computing these by hand use

```python
ChoiceAnswer.from_probabilities({"calm": 0.05, "angry": 0.95}, provenance)
ScoreAnswer.from_probabilities([0.0, 0.2, 0.8], ["can wait", "this week", "today"], provenance)
```

### Tolerances

| Check | Tolerance |
| - | - |
| probabilities sum to 1 | `SUM_TOL = 1e-9` |
| Score `score` equals the probability-weighted level | `LEVEL_TOL = 1e-9` |
| `confidence` equals the published formula (Choice and Score) | `CONFIDENCE_TOL = 7e-3` |

These are the smallest values that accept every example response in the TypeSafe docs
(`primitives/choice`, `primitives/score`, `sdk/python/usage`, `confidence`), which print values
rounded to two decimals. Measured against the formulas on this page, those examples have
probabilities that sum to 1 exactly, a Score `score` within 3e-16 of the weighted level, and a
`confidence` off by up to 0.0067 (the Score `formality` example prints 0.89 where the formula gives
0.883, which suggests the printed probabilities are rounded). The `sdk/python/usage` page shows no
Choice or Score response, and the `confidence` page only works the `bug_severity` example (0.35
against 0.355). A tolerance of 1e-3 on `confidence` would have rejected three of the examples. The
tests pin both sides of each value and check the documented examples. Issue #64 verifies these
values against the first real recording and may widen them; a tolerance changes no replay key and no
stored format.

`DecisionResult(answers, model, usage)` has `answers` (a read-only mapping of answer objects),
`model`, `usage`, `source` (`"synthetic"` or `"recorded"`), `result[name]`, and the groupings
`nouls`, `choices`, `scores`. A result never mixes synthetic and recorded answers; a synthetic
result's model is always `"synthetic"`; for a recorded result every answer's provenance model
equals the result's model. Each class has `to_dict()` / `from_dict()` (`answer_from_dict` for
answers).

Provenance: `Provenance.synthetic()` (no model, no date) or `Provenance.recorded(model, "YYYY-MM-DD")`
(the model string the API returned, and the date; both required; the model cannot be
`"synthetic"`). Nothing may be labelled `recorded` unless it came from a real API call.

## Stored response (what replay reads)

A stored response is exactly `DecisionResult.to_dict()`; a fixture file is a JSON object
`{replay_key: stored_response}` (the on-disk format is finalized by the fixture validator). Keys are 64 lowercase hex
characters, and a duplicate key in the file is an error.

```json
{
  "model": "synthetic",
  "usage": {"input_tokens": null, "output_tokens": null},
  "answers": {
    "billing": {"type": "noul", "noul": 0.97,
                "provenance": {"source": "synthetic", "model": null, "date": null}},
    "tone": {"type": "choice", "choice": "angry",
             "probabilities": {"calm": 0.05, "frustrated": 0.15, "angry": 0.8}, "confidence": 0.7,
             "provenance": {"source": "synthetic", "model": null, "date": null}},
    "urgency": {"type": "score", "score": 1.8,
                "probabilities": {"0": 0.0, "1": 0.2, "2": 0.8}, "confidence": 0.7,
                "legend": {"0": "can wait", "1": "this week", "2": "today"},
                "provenance": {"source": "synthetic", "model": null, "date": null}}
  }
}
```

Unknown keys are errors, and provenance is required on every answer. On replay the answers must
match the questions asked (same names, same types, same options or number of levels), or
`FixtureError` is raised. Choice option order is part of the replay key, so reordering the options
of a question is a `ReplayMiss`, not a fit error (a stored answer only has to name the same options,
in any order).

### Building a fixture by hand

```python
# recipe: fixture
import json

from jev_cookbook import (
    Choice,
    ChoiceAnswer,
    DecisionResult,
    Noul,
    NoulAnswer,
    Provenance,
    Score,
    ScoreAnswer,
    get_backend,
    replay_key,
)

state = {"document": "I was charged twice. Please fix this ASAP."}
questions = {
    "billing": Noul(instructions="Is this ticket about billing?"),
    "tone": Choice(criteria={"calm": None, "angry": None}, instructions="Tone?"),
    "urgency": Score(criteria=["can wait", "today"], instructions="How urgent?"),
}
syn = Provenance.synthetic()
result = DecisionResult(
    {
        "billing": NoulAnswer(0.97, syn),
        "tone": ChoiceAnswer.from_probabilities({"calm": 0.1, "angry": 0.9}, syn),
        "urgency": ScoreAnswer.from_probabilities([0.2, 0.8], ["can wait", "today"], syn),
    },
    "synthetic",
)
fixtures = {replay_key(state, questions): result.to_dict()}
with open("fixtures.json", "w", encoding="utf-8", newline="\n") as fh:
    json.dump(fixtures, fh, indent=2)
    fh.write("\n")

backend = get_backend(fixtures="fixtures.json")
assert backend.decide(state, questions) == result
```

Change the state or any question and the key changes, so replay misses (`ReplayMiss`) instead of
guessing. A recorded fixture uses `Provenance.recorded(model, date)` on every answer and the same
model string as `DecisionResult(..., model)`.

## Replay key

`replay_key(state, questions)` is the lowercase hex SHA-256 of the ASCII bytes of the canonical
JSON of `{"v": 1, "state": <state>, "questions": {<name>: <question.to_dict()>, ...}}`.

Canonical JSON: separators `,` and `:` with no spaces, `ensure_ascii=True` (non-ASCII becomes
`\uXXXX`), `allow_nan=False`, floats and ints as Python writes them (shortest round-trip `repr`,
identical on all platforms and Python 3.10 to 3.14). Question names are sorted. Every other object
key (state keys, Choice options) and every array is hashed in the order written, which is the order
the SDK sends. Nothing else is normalized: `1` and `1.0` differ, `-0.0` stays `-0.0`, newline
styles (`\r\n`, `\r`, `\n`) differ, and Unicode is not re-normalized. It never uses `hash()`.

What changes the key: the state (including key order), question names, each question's type,
`instructions`, and `criteria` (Score level order and Choice option order matter; Noul criteria
with all-`None` values equal no criteria). What does not: question order. The key version `v` is
bumped if this rule ever changes.

A miss raises `ReplayMiss` (a `LookupError`) whose message and `.key` give the missing key; the
fix is to rebuild or add the fixture for that key. Replay never fabricates an answer.

## Scripted backend

`ScriptedBackend(script, seed=0)` calls `script(state, questions, rng)` and expects
`{name: spec}`: a float for `Noul`; an option name or `{option: weight}` for `Choice`; a list of
per-level weights for `Score`. Weights are normalized; `confidence` is computed with the formulas
on the TypeSafe confidence page. `rng` is a `random.Random` seeded from `(seed, replay_key)`, so
the same request gives the same answers on every platform, whatever the call order; use only
`rng.random()`. Sums use `math.fsum`, so results are identical across Python versions. Answers are always
`synthetic`, model `"synthetic"`, empty usage. These
numbers say nothing about how Jev performs.

## `get_backend`

`get_backend(*, fixtures=None, script=None, seed=0)` returns a `ScriptedBackend` (script) or a
`ReplayBackend` (fixtures: a mapping or a JSON path); pass exactly one. `JEV_COOKBOOK_LIVE=1`
selects the live backend and currently raises `LiveBackendUnavailable`; it never falls back to
replay. Values other than unset, empty, `0`, `1` are an error. The environment is read when
`get_backend` is called, not at import.

## Backend attributes

Every backend has `mode` (`"synthetic"`, `"recorded"`, `"scripted"` or `"live"`) and `model`
(the model string its results carry; `"synthetic"` offline). `ReplayBackend` derives `mode`,
`model` and `recorded_dates` (a sorted tuple of unique dates, empty when synthetic) from the
fixture provenance when it loads, and rejects an empty fixture set, a set mixing synthetic and
recorded answers, or one with more than one model. `ScriptedBackend` is `mode="scripted"`,
`model="synthetic"`. The live backend, when it exists, must expose the same attributes
with `mode="live"`.
