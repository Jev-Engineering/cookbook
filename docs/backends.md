# Decision backends

One interface, `backend.decide(state, questions, assets=None)` (with `assets` keyword-only),
that a notebook calls the same way offline (replay or scripted) and live.

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

## Actual calls and distinct requests

A replay fixture map stores one response per distinct request key. Calling `decide` twice
with the same state, questions and assets makes two logical calls but uses one fixture key.
In a live comparison those calls may produce different answers; the audit never deduplicates
them or changes their state, questions, assets, answers, or replay keys. A live backend
caches nothing, so each of those calls is one paid request.

Wrap each backend whose live requests a notebook needs counted:

```python
from jev_cookbook import AuditedBackend, get_backend

backend = AuditedBackend(get_backend(fixtures="fixtures/responses.json"))
```

Pass this wrapper through every helper that makes decisions. Settings such as `max_retries`,
mode, returned model, recorded dates, and the live recorder's attributes remain attached to the
wrapped backend. At the end of the notebook, add a standalone final code cell:

```python
print(backend.audit_json())
```

A notebook with more than one audited backend gives each its own `label="..."` (a lowercase
name; `"main"` when there is one) and prints them together, in the order they were created:

```python
from jev_cookbook import AuditedBackend, audit_json, get_backend

arm_a = AuditedBackend(get_backend(fixtures="fixtures/a.json"), label="arm-a")
arm_b = AuditedBackend(get_backend(fixtures="fixtures/b.json"), label="arm-b")
```

```python
print(audit_json(arm_a, arm_b))
```

The live budget belongs to one backend object (`JEV_COOKBOOK_LIVE_MAX_REQUESTS` is the cap of
each, not of the run), so a second backend is a second budget and is named, counted and declared
as such rather than merged into one number.

The `JEV_REQUEST_AUDIT ` line is `{"schema": 2, "backends": [...]}`. Each backend entry holds its
`label`, `decide_calls`, `distinct_requests` and an ordered `calls` list with each `replay_key`
and whether the delegate `returned`. Counts derive from the list; repeated keys remain repeated.
A delegated exception propagates unchanged and leaves `returned: false`. A request rejected by the
wrapper's replay-key validation never reaches the delegate and is not counted.
`backend.audit()` returns a fresh dictionary snapshot of that backend's entry.

**Adding a counted quantity later** (the images a request carries, for example) does not change
these fields. A quantity is registered once with `jev_cookbook.accounting.register_profile(name,
counter)`; a call then carries `"profile": {name: n}` and the entry carries `"profile_totals":
{name: sum}`. Zeros and empty mappings are omitted, so a notebook that never uses the quantity
prints byte for byte the line it printed before, and its committed output stays valid. The guard
accepts exactly the registered names, recomputes every total, and compares it with the recipe's
declared `profile`. Only a change to a core field bumps `schema`.

The cookbook registers two such quantities itself, when `jev_cookbook` is imported, for requests
that carry `assets`: `images`, the image copies a request expands to (every place a reference is
replaced by its image; an image in the instructions counts once per question that has it), and
`distinct_images`, the distinct assets whose reference is replaced at least once (an asset whose
reference is never replaced counts none, although it is still supplied). Both are counts: no
bytes, content or references reach
the line. A text-only call has neither, so its line is byte for byte unchanged and a text-only
notebook never loads the image code. Each total is a sum over calls, so `distinct_images` is the
per-call distinct assets summed across the run, not the number of different files in it. A recipe
declares them like any profile, `"profile": {"images": 12, "distinct_images": 4}`, and the guard
also refuses a call that states images without distinct images or fewer copies than distinct
images, whatever the totals say. See
[copies and the 32 MiB caps](vision.md#image-copies-and-the-32-mib-caps).

### The declared count: `request_budget.json`

A recipe states its live request count once, in `request_budget.json` beside the notebook:

```text
{
  "schema": 1,
  "backends": {
    "main": { "requests": 40, "fixtures": "fixtures/responses.json" }
  }
}
```

Per backend: `requests` (the `decide` calls the notebook makes), `fixtures` (the recipe-relative
replay file whose keys the backend must exercise exactly, or `null` for a scripted backend), and
optionally `distinct` (when the notebook repeats a request on purpose, such as a simulation that
reaches the same state again: `requests` calls, `distinct` different ones; the default is
`requests`), `at_most` (when the count depends on the answers, such as a second stage that runs
only for some first-stage answers: the audit replays the committed answers and measures `requests`;
`at_most` is the author's stated bound for every other path, and the cap is sized by it) and
`profile`.

The README's budget paragraph is rendered from this file, not typed:
`python -c "from jev_cookbook.accounting import render_recipe_note as r; print(r('recipes/NN-slug'), end='')"`
prints it between `<!-- request-budget:begin -->` and `<!-- request-budget:end -->`, and the
guard re-renders it and requires the README to hold it unchanged. It also rejects any other
sentence in `## Switch to live` that pairs a number with request, call, budget, cap, "raise",
"set it to", "at least" or "up to" wording (the library default may be named in a sentence that
says "default"). That is a reach, not a proof: a number spelled out in words, or prose in another
section, is not read, so a migrating recipe's reviewer still reads the section. The cap it names is the largest single backend's bound, because the cap is inclusive and per
backend (a run of N requests is allowed by a cap of N, and stopped at request N+1); the total is
what the run is billed.

The recipe guard (`readme_budget_note_matches_request_audit`) ties the final output to the shared
wrapper's direct construction and print, recomputes every count, rejects failed calls, and checks
the execution against the declaration: calls, distinct requests, the exact fixture inventory
(extra unused and missing fixtures both fail), and any profile. **A request decided twice fails on
its own and names its replay key**, unless the declaration says how many repeats are intended.
The declaration, an audited notebook and the rendered paragraph come together or not at all:
a README holding the paragraph with neither of the others, a declaration with no audit line, and
an audited notebook with no declaration each fail.
The separate fresh-kernel notebook check verifies that committed output is current; the unit
guard does not execute the notebook or prove arbitrary helper behavior. Use the direct imports and
constructions above, one top-level binding per audited backend, and the final standalone print.
Rejected, because each is a backend the ledger cannot see: protected-name rebinding; detached
summary strings; importing `get_backend`, `ReplayBackend`, `ScriptedBackend`, `LiveBackend` or
`AuditedBackend` under another name; any other use of those names or of `.get_backend` and the like
as an attribute (so `ReplayBackend.from_json(...)` is rejected as well as `ReplayBackend(...)`);
a string equal to one of them; a `getattr` whose attribute is not written out as a string literal
(`getattr(backend, "recorded_dates", ())`, the measured cell's own line, is allowed; `getattr(m, name)`
and `getattr(m, "get_" + "backend")` are not); and `globals`, `eval`, `exec`, `__import__`,
`importlib`, `vars`, `__builtins__`, `operator.attrgetter`/`methodcaller`, `.getattr`,
`__getattr__`, `__getattribute__` and `__dict__`, which can reach one without naming it. That list
is not exhaustive: a lookup primitive outside it, fed a name assembled at run time, is not seen,
and nothing here proves otherwise. This is deliberate: a backend of any kind
that is not wrapped is not counted, so an audited notebook has no unaudited lane yet, including a
never-live `ReplayBackend` comparison lane (how such a lane is declared is open and belongs to the
first recipe that needs it). `one_backend_per_budget` separately fails a recipe with more
`get_backend` call sites than audited backends, counting aliases, attributes, bare references and
`getattr` strings; a call reached many times through one site is only visible to the ledger.

A recipe with no declaration, no `AuditedBackend` and no rendered paragraph keeps the strict
`len(responses.json)` check against its hand-written README sentence. That is a proxy: it
measures distinct fixture keys, so it cannot see a repeated request, a second backend, or an unused
fixture. An attempted but malformed audit fails instead of falling back to it.

This audit describes logical calls on the executed path. It contains no response contents or
HTTP-attempt evidence, and is not a measurement of live usage, latency, cost, or model quality.
See [live request accounting](live.md#budget-guard) for retry budgets.

## Questions

They mirror `typesafe_sdk`, and every constructor takes keyword arguments only. `instructions` is
text, a JSON object or array, or `None`. `Choice(criteria={name: description-or-None})` takes a
mapping of 2 to 255 options (see "Single-option Choice" below for the lower bound).
`Score(criteria=[...])` takes an ordered list of 2 to 10
levels (each non-empty text, a non-empty JSON object or a non-empty JSON array; the legend holds the level value as given, so a legend value may be text, an object or an array). `Noul(criteria={"true": ..., "false": ...})` optionally
describes the outcomes. All values must be plain JSON (`str`, `int`, `float`, `bool`, `None`,
`list`, `dict` with `str` keys); numpy values and NaN are rejected. `to_dict()` /
`question_from_dict()` convert them.

The `state` passed to `decide` and `replay_key` is a string, a JSON object (`dict`), or an array
(`list`/`tuple`) of strings. Bare numbers, booleans and `None` are rejected with `TypeError`.

### Single-option Choice

`Choice` needs at least two options: with one, Jev has nothing to weigh, so building the
question raises `ValueError` ("a Choice needs at least two options; a forced answer belongs
to Python, not a request"). `jev_cookbook.answers.choice_confidence` raises the same error for
`n < 2` instead of returning a value for it (the published formula, `(p_max - 1/n) / (1 - 1/n)`,
is 0/0 at one option), and a stored `ChoiceAnswer` whose offered option list has one entry fails
the same way wherever it is loaded, including by `ReplayBackend`. When a recipe's own
candidate-gathering step leaves a document with only one option (or none), the decision belongs
to Python, not to a request: resolve it to a result directly in code and never build the
question or spend a call. Recipes 14 and 22 are the pattern: a document with no candidate span,
or an observed asset with no shortlisted canonical record, is resolved in Python (`no_candidates`,
`no_candidate_resolution`) before any `Choice` is ever built, so the single-option case never
reaches `get_backend` at all.

## Answers

| Class | Fields (value types) |
| - | - |
| `NoulAnswer` | `noul: float` (probability of yes, 0 to 1) |
| `ChoiceAnswer` | `choice: str`, `probabilities: {option: float}`, `confidence: float` |
| `ScoreAnswer` | `score: float`, `probabilities: {int: float}`, `confidence: float`, `legend: {int: str \| object \| array}` |
| `BoxAnswer` | `box: {top: float, bottom: float, left: float, right: float}`, `confidence: float \| None` |

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
`(p_max - 1/n) / (1 - 1/n)`; Score `1 - spread / even_spread`, where `spread`
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
| Choice `confidence` equals `(p_max - 1/n) / (1 - 1/n)` | `0.005 / (1 - 1/n) + 0.005` | the largest probability is off by up to 0.005 (rounding keeps order), the formula scales that by `1 / (1 - 1/n)`, and `confidence` is off by 0.005. A one-option Choice is rejected at construction (see "Single-option Choice"), so `n` is always at least 2 wherever this bound applies |
| Score `confidence` equals `1 - spread / even` | `0.005 * sum(abs(i - peak)) / even + 0.005` | see below |

Score confidence. On `https://docs.typesafe.ai/confidence` the formula is
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
`model`, `usage`, `source` (`"synthetic"` or `"recorded"`), `result[name]`, `name in result` and
`for name in result` (both by question name; any other value is simply not in the result),
`result.keys()` (the question names, in answer order), and the groupings `nouls`, `choices`,
`scores` and `boxes` (each a `dict` of the answers of that class, in answer order).
`dict(result)` and `{**result}` give `{name: answer}`, the same as `dict(result.answers)`;
`items()`, `values()`, `get()` and `len()` are not provided, so use `result.answers` for them.
A result never mixes synthetic and recorded answers; a synthetic
result's model is always `"synthetic"`; for a recorded result every answer's provenance model
equals the result's model. Each class has `to_dict()` / `from_dict()` (`answer_from_dict` for
answers).

Provenance: `Provenance.synthetic()` (no model, no date) or `Provenance.recorded(model, "YYYY-MM-DD")`
(the model string the API returned, and the date; both required; the model cannot be
`"synthetic"`). Nothing may be labelled `recorded` unless it came from a real API call.

## Stored response (what replay reads)

A stored response is exactly `DecisionResult.to_dict()`; a fixture file is a JSON object
`{replay_key: stored_response}` (the file layout and the validator are in [fixtures.md](fixtures.md)). Keys are 64 lowercase hex
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

Unknown keys are errors, and provenance is required on every answer. `provenance` and `usage`
must each be an object: `"usage": null` (or any other non-object `usage`) is rejected with a
`ValueError` naming the field, where it used to be read as empty. A missing `usage` key still
means "not reported" (`Usage()`). On replay the answers must
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

This example writes a scratch `fixtures.json` in the current directory so that it is self-contained. In a recipe the same mapping lives at `fixtures/responses.json`, written by a generator script next to the notebook; the layout and the validator are in [fixtures.md](fixtures.md).

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
bumped if this rule changes after a fixture has been recorded under it. The image `assets`
member (below) was redefined once, before any image fixture existed (its digest moved from the
base64 text to the decoded file bytes), so `v` stayed 1 and no recorded key moved. Any later
change that would alter an existing key, text-only or image, bumps `v`.

The state, a question's `instructions`, and each `criteria` value (each Score level, Choice
option description, Noul outcome) each nest at most **64 levels** of list/object, counting the
outermost container as level 1; the `{"v", "state", "questions"}` envelope is not counted. Deeper
raises `ValueError` ("nested deeper than 64 levels"), not `RecursionError`; anything at exactly
64 levels hashes as it always did. Only `replay_key` applies this limit: the shared JSON helpers
(`plain_json`, `canonical_json`, the simulation classes) have no depth limit by default. The
count matches the fixture validator (`docs/fixtures.md`), but in `inputs.jsonl` the state sits
inside the line object, which the validator counts as level 1, so the deepest state a fixture
can hold is 63 levels of its own while `replay_key` accepts 64.

## Scripted backend

`ScriptedBackend(script, seed=0)` calls `script(state, questions, rng)` and expects
`{name: spec}`: a float for `Noul`; an option name or `{option: weight}` for `Choice`; a list of
per-level weights for `Score`. Weights are normalized; `confidence` is computed with the formulas
on the TypeSafe confidence page. `rng` is a `random.Random` seeded from `(seed, replay_key)`, so
the same request gives the same answers on every platform, whatever the call order; use only
`rng.random()`. Sums use `math.fsum`, so results are identical across Python versions. Answers are always
`synthetic`, model `"synthetic"`, empty usage. These
numbers say nothing about how Jev performs.

Use only `rng.random()`, never `rng.shuffle()` or anything else that draws from
`_randbelow()`/`getrandbits()` (`choice()`, `sample()`, `randint()`, ...): the `random` module's
own docs commit only `random.Random.random()` to producing the same sequence for the same seed
across Python versions, and name no such guarantee for the rest of the API, `shuffle()`
included. A script that calls `rng.random()` is reproducible on every supported Python for
exactly that reason; a script that called `rng.shuffle()` would not be.

A script that needs a per-item order -- which candidate to list first, say -- should reach for
`jev_cookbook.fixtures.stable_permutation`/`stable_shuffle` (`docs/fixtures.md`, "Per-item
option order") instead of `rng.shuffle()`: build the index or value order from a seed key of
your own (not from `rng`, which is already committed to `(seed, replay_key)` for the answers
themselves), the same way a fixture generator does for a replay-mode recipe. Issue #181
reviewed every caller of `rng_for`/`script` in this repository for exactly this risk: none
currently calls `rng.shuffle()` or any other non-`random()` method on `rng` (the existing
`test_scripted_is_deterministic_and_seeded` in `tests/test_backends.py` already pins
`random.Random(12345).random() == 0.41661987254534116` as the byte-reproduction check for the
one method this relies on), so nothing here needed to change.

## `get_backend`

`get_backend(*, fixtures=None, script=None, seed=0, model=None, images=False, long_context=False)`
returns a `ScriptedBackend` (script) or a
`ReplayBackend` (fixtures: a mapping or a JSON path); pass exactly one. `JEV_COOKBOOK_LIVE=1`
selects the live backend and never falls back to replay: it requires `JEV_COOKBOOK_LIVE_MODEL`,
accepts an optional `JEV_COOKBOOK_LIVE_MAX_REQUESTS`, reads `TYPESAFE_API_KEY` from the
environment, and raises `LiveConfigError` when a setting is missing (see [live.md](live.md)).
An explicit `model` overrides `JEV_COOKBOOK_LIVE_MODEL`; the two boolean flags enable the
experimental request headers in live mode. Offline backends ignore these live options and
derive their model and provenance from the fixtures or script.
Values other than unset, empty, `0`, `1` are an error. The environment is read when
`get_backend` is called, not at import.

### Which lane goes through `get_backend`

Under `JEV_COOKBOOK_LIVE=1`, `get_backend` ignores `fixtures` and `script` and returns a live
backend for the model in `model` or `JEV_COOKBOOK_LIVE_MODEL`, not the model named in a fixture
file. Use it for the one lane that is meant to switch with live mode. A lane that must stay
offline whatever the environment says (the fabricated adapters in a recipe that compares backends,
for instance) is constructed directly: `ReplayBackend(mapping)`, `ReplayBackend.from_json(path)`
or `ScriptedBackend(script, seed)`. Built through `get_backend`, that lane would become a live
backend under live mode and could send a real request for a model that does not exist. Nothing
offline shows it, because the two branches differ only when `JEV_COOKBOOK_LIVE=1`, which no
automated check sets. Recipe 50 is the pattern: `get_backend` for `jev` only, `ReplayBackend`
for the other lanes, and one responses file per lane (see
[fixtures.md](fixtures.md#comparison-recipes-responses-tagjson)).

Decision (#290): nothing enforces this. A check could count `get_backend` calls in a recipe, but
a count cannot tell whether a second backend was meant to go live, so it would stand in for
intent the source does not carry; a recipe may also legitimately call it once or twice. The rule
is guidance, read here, in the `get_backend` docstring and in [live.md](live.md), and held by
review. An explicit keyword on `get_backend` that separates "may go live" from "never live" would
be a public API change and a separately reviewed design.

## Backend attributes

Every backend has `mode` (`"synthetic"`, `"recorded"`, `"scripted"` or `"live"`) and `model`
(the model string its results carry; `"synthetic"` offline). `ReplayBackend` derives `mode`,
`model` and `recorded_dates` (a sorted tuple of unique dates, empty when synthetic) from the
fixture provenance when it loads, and rejects an empty fixture set, a set mixing synthetic and
recorded answers, or one with more than one model. `ScriptedBackend` is `mode="scripted"`,
`model="synthetic"`. The live backend, when it exists, must expose the same attributes
with `mode="live"`.

## Images and Box

**Experimental.** Upstream labels images and Box "Dreamer-ready": "Images and Box questions aren’t
yet up to our standards to call ready for production" and "The request format, the answers, and
the limits on this page can change between releases, and accuracy will change as we update the
models" (the [images](https://docs.typesafe.ai/images) and [Box](https://docs.typesafe.ai/primitives/box)
pages, read on 2026-10-31). This section describes what this repository does today. The local helpers are in [vision.md](vision.md).

`assets` maps a stable reference string to the official raw image dictionary:
`{"type": "image", "format": "png", "data_base64": ...}` (`jpg` and any letter case also work;
the format is canonicalized to `png`/`jpeg` before the replay key is computed, so the same bytes
key identically however the format is spelled).
The same keyword is accepted by `replay_key`, replay, scripted and live `decide`.
The shared `jev_cookbook.vision.image_asset(path)` helper reads and validates an image (pass
`root=` for a path that comes from fixture data, see [fixtures.md](fixtures.md#image-fixtures));
`image_reference(asset)` derives a stable reference from its bytes. The live adapter converts
the dictionary into the SDK's `Image` and sends it using the SDK's multipart support.

```python
from jev_cookbook import Box, Noul, get_backend
from jev_cookbook.vision import image_asset, image_reference

photo = image_asset("assets/screenshot.png")
ref = image_reference(photo)
assets = {ref: photo}
state = {"screenshot": ref}
questions = {
    "present": Noul(instructions="The Save button is visible in `screenshot`."),
    "button": Box(instructions="The Save button in `screenshot`."),
}
backend = get_backend(fixtures="fixtures/responses.json", model="jev-1.14.0", images=True)
result = backend.decide(state, questions, assets=assets)
result.boxes["button"].box
```

References remain strings in cookbook state and questions; the API substitutes images.
They can occur inside longer strings and nested values in state, instructions or criteria.
Object keys, including question IDs and Choice option names, remain text. Every supplied
asset must appear in a value; key-only and unused references fail validation. Use distinctive
references to avoid accidental substring matches. See the official [image contract](https://docs.typesafe.ai/images).

A reference repeated in state, criteria or several questions' instructions adds a copy of the
image each time, and the live backend refuses a request whose distinct images or expanded copies
exceed 32 MiB before spending anything (`ImageRequestTooLarge`, `requests_made` unchanged). That check
is necessary, not sufficient: it does not model the request-body cap, and a request that passes
can still be refused. Put a shared image in the state once.
[Copies and the 32 MiB caps](vision.md#image-copies-and-the-32-mib-caps)
has the counting rules; image tokens are observable only in a recorded response's
`usage.input_tokens`, beside which `live.record` writes the `images` and `distinct_images` counts.

Asset dictionaries, base64, image format and image bounds are checked before replay or live
inference. A Box request needs at least one image. An arbitrary string without an asset entry
is ordinary text; replay detects a missing or changed image through its different request key.
Keep image files under `assets/` beside `fixtures/`, and put their relative paths in input
`fields` ([fixtures.md](fixtures.md#image-fixtures)).

The text-only replay envelope is unchanged: omitted, `None` and empty assets produce exactly
the existing keys. A request with images adds an `assets` object sorted by reference, holding
each asset's `type`, canonical `format` (`png` or `jpeg`) and `sha256`, the lowercase hex
SHA-256 of the **decoded file bytes** (the same digest `image_reference` embeds), not of the
base64 text. Base64 that decodes to the same bytes but is spelled differently (for example
non-canonical trailing bits, `QQ==` and `QR==`) therefore keys once. This is the envelope
every image fixture binds to; text-only keys are untouched and pinned by a test. Changed image
bytes or references change the key, while reordering the assets map does not. No image data
is stored in a response fixture. The scripted random seed includes this key; scripts retain
their existing `(state, questions, rng)` interface.

`Box(instructions=...)` has no `criteria`; its `to_dict()` contains only type and instructions.
`BoxAnswer(box, confidence, provenance)` requires exactly four finite edges in `[0, 1]`,
with `left < right` and `top < bottom`, and copies them into an immutable mapping.
Confidence is in `[0, 1]` or `None`; omitted confidence in a stored/raw response becomes `None`.
No confidence is invented. The [SDK response contract](https://docs.typesafe.ai/sdk/python/api/types/responses)
documents `None` when the model supplies no confidence; an SDK response that omits a required
field entirely may still be rejected by the SDK before cookbook parsing.

A Box can return coordinates for an absent object. Pair it with a presence question and route
absent or uncertain results to review in Python. This is one rectangle, not a presence flag
or segmentation mask. See the [Box contract](https://docs.typesafe.ai/primitives/box).
Scripts return a ready-made synthetic `BoxAnswer`; replay and live responses enforce the same
geometry and question/answer type checks. `format_answer`/`show_answer` display the edges and
show missing confidence as `unknown`; probability plotting does not apply to a Box.
