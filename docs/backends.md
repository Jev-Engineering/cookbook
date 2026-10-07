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
conversion). Answers are immutable: mappings are read-only views. A legend value follows the same rule as a `Score` question level: non-empty text, a non-empty JSON
object or a non-empty JSON array (a tuple is held as a list). A legend value that is a JSON
object or array stays an ordinary `dict`/`list` inside the result, so replay builds a fresh result
from a private copy on every call: whatever you change in a returned result never reaches a later
replay. `to_dict()` also returns a fresh copy you may edit.

Construction is validated: probabilities sum to 1 (the error message says what they summed
to); `choice` is the highest-probability option (a gap under 1e-3 counts as a tie, see Tolerances); `confidence`
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

Every consistency check allows the gap that rounding can cause. The premise: each reported
number (each probability, `score`, `confidence`) is within 0.005 of its true value, which is what
rounding to two decimals does. Each bound below is the largest gap the formula can show under that
premise, plus a float margin of 1e-9 so no case is decided by float noise. `n` is the number of
options or levels.

| Check | Bound | Derivation |
| - | - | - |
| probabilities sum to 1 | `0.005 * n` | each of n probabilities is off by up to 0.005 |
| Score `score` equals `sum(i * p_i)` | `0.005 * n(n-1)/2 + 0.005` | each `p_i` moves the sum by up to `0.005 * i`; `score` itself is off by 0.005 |
| Choice `confidence` equals `(p_max - 1/n) / (1 - 1/n)` | `0.005 / (1 - 1/n) + 0.005` | the largest probability is off by up to 0.005 (rounding keeps order), the formula scales that by `1 / (1 - 1/n)`, and `confidence` is off by 0.005; one option gives 1 whatever `p` is, so the bound is 0.005 |
| Score `confidence` equals `1 - spread / even` | `0.005 * sum(abs(i - peak)) / even + 0.005` | see below |

Score confidence. On `https://docs.typesafe.ai/confidence.md` the formula is
`1 - spread / even` with `spread = sum(p_i * abs(i - peak))` and `even = mean(abs(i - (n-1)/2))`,
the same quantity for a uniform distribution, clamped to 0 to 1. For a fixed peak, each `p_i`
off by 0.005 moves the spread by up to `0.005 * sum(abs(i - peak))`, so the quotient moves by up to
that divided by `even`; `confidence` itself is off by 0.005; the clamp never widens a gap. The
peak is not continuous in the probabilities, so a stored answer is accepted when its confidence is
within the bound of the formula at any level whose reported probability is within `2 * 0.005` of
the largest (the true peak cannot be further below it). For two levels the bound is 0.015 and for
ten levels it is at most 0.095. When levels tie exactly, `score_confidence` and
`from_probabilities` take the first maximum as the peak (`[0.4, 0.4, 0.2]` gives 0.0, the last
maximum would give 0.1).

The sum bound grows with `n` (1.275 for 255 options), so for a very long Choice it only rejects
sums far from 1; that is what the premise allows.

The argmax rule is separate: `choice` must be the highest-probability option, with a slack of
`TOL = 1e-3`. Rounding is monotone, so it cannot put the stated option below another one; it can
only tie them (a true 0.5049 against 0.4951 both print 0.50). A stated choice within 1e-3 of the
top loads, one clearly below it (0.0011 or more) is rejected.

Examples printed to two decimals still load: every documented example on the Choice, Score and
confidence pages loads (their `confidence` is off by up to 0.0067; the Score `formality` example
prints 0.89 where the formula gives 0.883), and so does a true p = 0.5849 reported as
`{a: .58, b: .42}` with confidence `.17`. A seeded simulation test builds exact answers for
Choice with 2, 3, 5, 20 and 255 options and Score with 2, 5 and 10 levels, rounds every number to
two decimals, and requires every one to load. Hand-typed inconsistencies of 0.1 (wrong top option,
sum, score, or confidence beyond its bound) are rejected, and the tests pin each bound on both
sides. Issue #64 confirms on the first real recording whether the API rounds at all and, if it
does not, tightens these bounds in its own reviewed pull request. A bound changes no replay key
and no stored format.

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
selects the live backend and never falls back to replay: it requires `JEV_COOKBOOK_LIVE_MODEL`,
accepts an optional `JEV_COOKBOOK_LIVE_MAX_REQUESTS`, reads `TYPESAFE_API_KEY` from the
environment, and raises `LiveConfigError` when a setting is missing (see [live.md](live.md)).
Values other than unset, empty, `0`, `1` are an error. The environment is read when
`get_backend` is called, not at import.

## Backend attributes

Every backend has `mode` (`"synthetic"`, `"recorded"`, `"scripted"` or `"live"`) and `model`
(the model string its results carry; `"synthetic"` offline). `ReplayBackend` derives `mode`,
`model` and `recorded_dates` (a sorted tuple of unique dates, empty when synthetic) from the
fixture provenance when it loads, and rejects an empty fixture set, a set mixing synthetic and
recorded answers, or one with more than one model. `ScriptedBackend` is `mode="scripted"`,
`model="synthetic"`. The live backend, when it exists, must expose the same attributes
with `mode="live"`.
