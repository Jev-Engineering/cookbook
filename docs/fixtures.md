# Fixtures

What goes in a recipe's `fixtures/` folder, and the tool that checks it:

```bash
python -m jev_cookbook.fixtures validate recipes/NN-slug   # exit 0 if valid, 1 with one line per problem
python -m jev_cookbook.fixtures validate --all             # every recipes/*/fixtures that exists
```

```text
recipes/NN-slug/fixtures/
├── inputs.jsonl      the examples: id, split, state (or fields), replay_keys
├── labels.jsonl      gold labels, one per example, same id
└── responses.json    model responses: {replay_key: stored response}
```

All three are UTF-8 (a leading byte order mark is accepted) and contain no comments. Inputs and
labels are **JSON Lines**, one object per line, because a person reads and diffs one example per
line, an error can name the line, and examples are added by appending. Responses are one JSON
object because that is the format `ReplayBackend.from_json` already reads
([backends.md](backends.md)); this page does not change it. Blank lines are ignored. The row schemas are in
[`schema.json`](../src/jev_cookbook/fixtures/schema.json) (JSON Schema, draft 2020-12).

## Inputs

```json
{"id": "t07", "split": "test", "state": {"text": "I was charged twice."}, "replay_keys": ["<64 hex>"]}
```

| Field | Rule |
| - | - |
| `id` | Stable, unique in the recipe: letters, digits, `_`, `.`, `-`, 1 to 64 characters, starting with a letter or digit. Never reused for a different example. |
| `split` | `validation`, `test`, `train` or `demo` (below). |
| `state` | Exactly one of `state` and `fields`. `state` is the value passed to `backend.decide`: text, a JSON object, or a list of strings. |
| `fields` | The values the recipe's Python builds the state from (a JSON object), when the notebook assembles the state itself. |
| `replay_keys` | `replay_key(state, questions)` of every request made for this example: 64 lowercase hex characters, one or more (more than one when a later request depends on an earlier answer). |

The validator cannot rebuild a request, because the questions live in the notebook. So the link
from an example to its responses is written down: `replay_keys`. Compute the keys in the script
or notebook cell that writes the fixtures, never by hand. Change a question and the keys change;
the validator then reports the old responses as unreferenced and the new keys as missing.

## Splits

- `validation`: choose thresholds, prompts and options here, as often as you like.
- `test`: report on it once, after the choices are frozen. Never tune on it.
- `train`: optional, for a baseline that learns from examples.
- `demo`: shown to the reader to illustrate a typed answer, never scored; no label needed.

Both `validation` and `test` must have at least one example. The same `state` in two scored
splits is an error (it would leak the test set into the choices made on validation).

## Labels

```json
{"id": "t07", "label": "billing"}
```

`label` is any JSON value except `null`: a string, number, boolean, list, or object (for several
labels). Every `train`, `validation` and `test` example needs exactly one label; a label whose
`id` is not in the inputs is an error.

## Responses and provenance

`responses.json` is exactly `{replay_key: DecisionResult.to_dict()}`: see "Stored response" in
[backends.md](backends.md). Every answer carries its provenance (`synthetic`, or `recorded` with
the model string and the `YYYY-MM-DD` date), which `DecisionResult` already enforces. On top of that
the validator requires that:

- all responses in a recipe agree: a file is all `synthetic` or all `recorded`, so a recorded
  file containing a synthetic answer is an error, and mixed sets are an error;
- all responses name one model (dates may differ between responses);
- every response is listed in some input's `replay_keys`, and every listed key has a response.

A synthetic response says nothing about how Jev performs; never label anything `recorded` that
did not come from a real API call ([CONTRIBUTING.md](../CONTRIBUTING.md), section 2).

## Secrets

Each file, and each JSON string inside it, is scanned for key- and token-shaped strings with the
rules of `tools/check_hygiene.py` (same rule names, secret rules only; the scanner is copied
into the package because `tools/` is not installed, and a test keeps the copy equal). The
message gives the file, line and rule, never the whole value. Do not use a field named `token`.

## Where the notebook runs

A notebook executes with its recipe directory as the working directory (nbclient's default; CI
sets it explicitly). Helpers take an explicit `recipe_dir` and default to the current directory.
Tests pass `Path(__file__).parent.parent`.

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
returns a list of `Problem` (empty when valid). Loaders raise `FixtureFileError`, whose message
names the file and the line or id, for example
`recipes/03-x/fixtures/inputs.jsonl:5 (id 't02'): duplicate id (first used on line 2)`.

Keep fixtures small enough to read: tens of examples at levels 1 and 2 ([CONTRIBUTING.md](../CONTRIBUTING.md), section 5).
