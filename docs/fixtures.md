# Fixtures

What goes in a recipe's `fixtures/` folder, and the tool that checks it:

```bash
python -m jev_cookbook.fixtures validate recipes/NN-slug   # exit 0 if valid, 1 with one line per problem
python -m jev_cookbook.fixtures validate --all             # every recipes/*/fixtures that exists
```

```text
recipes/NN-slug/fixtures/
├── inputs.jsonl            the examples: id, split, state (or fields), replay_keys
├── labels.jsonl            gold labels, one per scored example, same id
├── responses.json          model responses: {replay_key: stored response}
└── responses-<tag>.json    optional: the same requests answered by another model (comparison recipes)
```

Those are the only files allowed in `fixtures/`. Any other file or folder is an error, so
nothing in that folder escapes validation and scanning. Keep other things (a recorder's request-id
ledger, a generator script, notes) outside it.

All of them are UTF-8 and contain no comments. A leading byte order mark is accepted on
`inputs.jsonl` and `labels.jsonl` but **rejected on every responses file**, because
`ReplayBackend.from_json` opens them as plain UTF-8 and cannot parse a file that starts with one;
the validator may not accept a file the backend cannot load. Inputs and labels are **JSON Lines**,
one object per line, because a person reads and diffs one example per line, an error can name the
line, and examples are added by appending. Responses are one JSON object because that is the
format `ReplayBackend.from_json` already reads ([backends.md](backends.md)); this page does not
change it. Blank lines are ignored. The row schemas are in
[`schema.json`](../src/jev_cookbook/fixtures/schema.json) (JSON Schema, draft 2020-12); a
pattern must match the whole value, so an id with a trailing newline is refused.

## Inputs

```json
{"id": "t07", "split": "test", "state": {"text": "I was charged twice."}, "replay_keys": ["<64 hex>"]}
```

| Field | Rule |
| - | - |
| `id` | Stable, unique in the recipe: letters, digits, `_`, `.`, `-`, 1 to 64 characters, starting with a letter or digit. Never reused for a different example. Two ids that differ only by case are an error (ids tend to become file names). |
| `split` | `validation`, `test`, `train` or `demo` (below). |
| `state` | Exactly one of `state` and `fields`. `state` is the value passed to `backend.decide`: text, a JSON object, or a list of strings. |
| `fields` | The values the recipe's Python builds the state from (a JSON object), when the notebook assembles the state itself. |
| `replay_keys` | `replay_key(state, questions)` of every request the notebook replays for this example: 64 lowercase hex characters. May be empty (see "Replay and scripted recipes"). More than one when a later request depends on an earlier answer, in the order the notebook makes the requests. |

The validator cannot rebuild a request, because the questions live in the notebook. So the link
from an example to its responses is written down: `replay_keys`. Compute the keys in the script
that writes the fixtures, never by hand. Change a question and the keys change; the validator
then reports the old responses as unreferenced and the new keys as missing. A replay key is a
hash of the request, so two examples whose `state` (or `fields`) differ can never share one: a
key listed by such examples is an error. That catches a key copied from another example.

## Splits

- `validation`: choose thresholds, prompts and options here, as often as you like.
- `test`: report on it once, after the choices are frozen. Never tune on it.
- `train`: optional, for a baseline that learns from examples.
- `demo`: shown to the reader to illustrate a typed answer, never scored. It needs no label,
  and a label for a demo example is an error (it would only be ignored, and invites scoring it).

Both `validation` and `test` must have at least one example. **Leak rule:** the same content in
two different splits among `train`, `validation` and `test` is an error, because it would leak the
test set into the choices made on validation (or into training). Content means `state` for an
example that has `state`, and `fields` for an example that has `fields`; they are compared as JSON,
whatever the key order. `demo` examples are exempt. The same content twice inside one split is
allowed, but double counts that example.

## Labels

```json
{"id": "t07", "label": "billing"}
```

`label` is any JSON value except `null`: a string, number, boolean, list, or object (for several
labels). Every `train`, `validation` and `test` example needs exactly one label; a label whose
`id` is not in the inputs is an error.

## Replay and scripted recipes

Most recipes replay: the notebook answers each request from stored responses. Some do not. A
recipe built on `ScriptedBackend` or a simulator (the scripted and simulated catalog entries)
has nothing to replay, and the contract says code never invents an answer, so the format does not
make such recipes write responses just to pass.

- `replay_keys` may be empty for an example, including for every example.
- `responses.json` may be **absent** when no example lists a key. It is required when any example
  does, and then every listed key needs a response.
- The validator reports the recipe's **mode**: `replay` when some example lists a key, `scripted`
  when none does. The CLI prints it (`fixtures valid (mode scripted)`), and
  `validate_recipe(...)` returns a list of `Problem` with a `.mode` attribute (`None` when
  `inputs.jsonl` could not be read). CI and the recipe template can act on it.
- In scripted mode a responses file that exists is still checked, so every response in it is
  reported as one that no input lists. Delete it.

## Responses and provenance

`responses.json` is exactly `{replay_key: DecisionResult.to_dict()}`: see "Stored response" in
[backends.md](backends.md). Every answer carries its provenance (`synthetic`, or `recorded` with
the model string and the `YYYY-MM-DD` date), which `DecisionResult` already enforces. On top of that
the validator requires, for each responses file on its own, that:

- all responses in the file agree: it is all `synthetic` or all `recorded`, so a recorded file
  containing a synthetic answer is an error, and mixed files are an error;
- all responses name one model (dates may differ between responses);
- every response is listed in some input's `replay_keys`, and every listed key has a response.

A synthetic response says nothing about how Jev performs; never label anything `recorded` that
did not come from a real API call ([CONTRIBUTING.md](../CONTRIBUTING.md), section 2). Avoid
synthetic responses so tidy that every model-free baseline scores perfectly on `test`: put the
hard cases in the labels and let the stored answers be wrong on some of them.

### Comparison recipes: `responses-<tag>.json`

A recipe that compares models or backends (model comparison, adaptive routing) answers the same
requests with each one. `responses.json` stays the default and is the only file a notebook reads
unless it asks for another. Each extra set is `responses-<tag>.json`, where `<tag>` follows the id
rule (letters, digits, `_`, `.`, `-`, up to 64 characters). Each file is a normal `ReplayBackend`
file validated by the rules above, so one provenance and one model per file; different files may
name different models. Because a comparison answers the same requests, **every replay key listed
in `inputs.jsonl` must be present in every responses file**, and none may hold a key nobody lists.
Never mix two models in one file; that is what the extra files are for.

```python
from jev_cookbook import get_backend
from jev_cookbook.fixtures import responses_path

baseline = get_backend(fixtures=responses_path())  # responses.json
other = get_backend(fixtures=responses_path(tag="b"))  # responses-b.json
```

`responses_path(recipe_dir=None, tag=None)` and `load_responses(recipe_dir=None, tag=None)` take
the tag; a tag that breaks the id rule is a `ValueError`.

## Secrets

Each file, and each JSON string inside it, is scanned for key- and token-shaped strings with the
rules of `tools/check_hygiene.py` (same rule names, secret rules only). The scanner is copied
into the package because `tools/` is not installed, and a test compares the copy's rule
definitions and function source with `tools/check_hygiene.py`, so editing one copy fails the
tests. The message gives the file, line and rule, never the whole value.

Hard cases often need a fake password or key (a prompt-injection line, a phishing message, a
leaked-credential report). Write them with a placeholder marker the scanner exempts, for example
`password: EXAMPLE-Summer2024Holiday` or `<redacted>`, not as a realistic value. A field whose
name contains `token`, `secret`, `password`, `credential` or `api_key` with a value of 16 or more
letters and digits is flagged unless the value has a marker (`example`, `your`, `redacted`,
`placeholder`, `dummy`, `xxx`, `changeme`, or one of `<`, `>`, `{`, `}`, `$`, `...`). Never commit
a real credential, and never a realistic fake.

## Where the notebook runs

A notebook runs with its recipe directory as the working directory. That is a convention the
recipe relies on, not something these helpers enforce; the recipe CI (#69) sets the working
directory explicitly when it executes notebooks. Helpers take an explicit `recipe_dir` and default to the
current directory. Tests pass `Path(__file__).parent.parent`.

```python
from jev_cookbook import get_backend
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

examples = load_inputs()  # list[Example]: id, split, state, fields, replay_keys
labels = load_labels()  # {id: label}
backend = get_backend(fixtures=responses_path())
for example in select_split(examples, "validation"):
    result = backend.decide(example.state, questions)
```

`load_responses()` returns the raw `{replay_key: stored response}`; `validate_recipe(recipe_dir)`
returns the problems (empty when valid) and the mode. Loaders raise `FixtureFileError`, whose
message names the file and the line or id, for example
`recipes/03-x/fixtures/inputs.jsonl:5 (id 't02'): duplicate id (first used on line 2)`.

## Writing fixtures

The fixtures are data written by a script, so the keys cannot drift from the questions. Keep
the questions and the function that builds a state in one module that both the generator and the
notebook import, so they cannot disagree (a mismatch only shows up as a replay miss at run
time). Put the generator in the recipe folder, next to the notebook and outside `fixtures/`
(for example `recipes/NN-slug/build_fixtures.py`), and commit it: the fixtures are then
reproducible and a reviewer can see how each response was made.

```python
import json
from pathlib import Path

from jev_cookbook import DecisionResult, Noul, NoulAnswer, Provenance, replay_key

QUESTIONS = {"billing": Noul(instructions="Is this ticket about billing?")}


def build_state(fields):  # the notebook imports this same function
    return {"text": fields["text"]}


rows = [  # (id, split, fields, label, synthetic probability)
    ("v01", "validation", {"text": "I was charged twice."}, "billing", 0.92),
    ("v02", "validation", {"text": "How do I reset my password?"}, "other", 0.11),
    ("t01", "test", {"text": "My invoice shows the wrong amount."}, "billing", 0.88),
    ("t02", "test", {"text": "Your app crashes on start."}, "other", 0.09),
]
folder = Path("fixtures")
folder.mkdir(exist_ok=True)
inputs, labels, responses = [], [], {}
for ident, split, fields, label, p in rows:
    key = replay_key(build_state(fields), QUESTIONS)  # a `fields` example gets its key from build_state
    inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
    labels.append({"id": ident, "label": label})
    answer = NoulAnswer(p, Provenance.synthetic())
    responses[key] = DecisionResult({"billing": answer}, "synthetic").to_dict()
(folder / "inputs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in inputs), "utf-8")
(folder / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in labels), "utf-8")
(folder / "responses.json").write_text(json.dumps(responses, indent=2) + "\n", "utf-8")
```

An example with `state` computes its key from that state directly. An example with `fields`
stores the fields and the key of `build_state(fields)`; the notebook calls the same `build_state`
before `backend.decide`. Recorded fixtures come from the live recorder, which writes the same
format; its request-id ledger lives outside `fixtures/`. A hard case is a normal example: name it
in the `id` (`v07-sarcasm`) or keep your own notes in the generator, since rows take no other
fields.

Keep fixtures small enough to read: tens of examples at levels 1 and 2 ([CONTRIBUTING.md](../CONTRIBUTING.md), section 5).
