# Live backend and recorder

`LiveBackend` sends the questions a notebook already uses offline to the TypeSafe System One API
and returns the same `DecisionResult` objects as replay. `record` runs requests through it and
writes the responses into a recipe's fixtures. Nothing here runs in CI: **CI never makes a live
call and needs no key.** Every test mocks the HTTP layer (a fake client, and
`httpx2.MockTransport` under the real SDK types when the SDK is installed).

## Opt in

Three things are needed, and each missing one gives an error that says what to do:

1. The optional SDK: `pip install 'jev_cookbook[live]'` (this pins `typesafe-sdk>=0.7.2,<0.8`).
   Importing `jev_cookbook` never imports it; only building a live client does.
2. `JEV_COOKBOOK_LIVE=1` in the environment. Any other value than unset, empty, `0` or `1` is an
   error; `1` never falls back to replay.
3. `TYPESAFE_API_KEY` in the environment, read when the backend is built (trimmed of
   surrounding whitespace once, as the SDK does). Never put a key in a notebook, fixture or
   committed file.

The SDK also reads `TYPESAFE_BASE_URL`, which would send the key to whatever host it names. When
the backend builds its own client it refuses to start (`LiveConfigError`) if that variable is set
to anything but `https://api.typesafe.ai`, and it passes the official host to the client
explicitly. To use another endpoint on purpose, build the client yourself and inject it with
`client=`. There is no environment opt-in for this.

```python
from jev_cookbook import LiveBackend

backend = LiveBackend("jev-1.13.0", max_requests=20)  # explicit model, explicit budget
result = backend.decide(state, questions)
```

Through `get_backend` (so a recipe switches mode without changing its code):

```bash
export JEV_COOKBOOK_LIVE=1
export JEV_COOKBOOK_LIVE_MODEL=jev-1.13.0        # required: there is no default model
export JEV_COOKBOOK_LIVE_MAX_REQUESTS=20         # optional, default 25
```

`get_backend(fixtures=...)` then returns a `LiveBackend` and ignores `fixtures`/`script`, because
in live mode the backend is the only thing that changes.

### Model

**Recordings must pin a versioned model: use `jev-1.13.0`, not an alias.** The model is passed
explicitly for every run, never defaulted. The documentation lists the pinned
ID `jev-1.13.0` and the aliases `jev-latest` and `jev-preview`. An alias moves when a release
ships, so a recording made through an alias may not be reproducible later; the response's `model`
field reports the versioned ID that answered. `backend.model` is the requested string until the
first response and the returned string afterwards (`backend.requested_model` keeps what was
sent). The returned string is what goes on `DecisionResult.model` and into every answer's
`Provenance.recorded(model, date)`, with the UTC date of the call.

## What a call does

- Requests are built from the question objects: `state` as given, each question as the raw
  dictionary the SDK accepts (`type`, plus `instructions` and `criteria` only when set), Choice
  options in the order written, and `model=`.
- The response is turned into JSON text first (`model_dump_json()` for an SDK model, `json.dumps`
  for a mapping) and parsed from that. The SDK's models are strict and use `int` level keys in
  Python; the JSON text is the one form both sides accept. Each answer is then built with the
  ordinary answer classes, so it gets the same consistency checks as any stored fixture.
- Usage: the API's `input_tokens`/`output_tokens` become `Usage`; each may be `null`. A count that
  is not a non-negative integer or null is a `LiveResponseError`, not a guess.
- The `request_id` (the `x-typesafe-request-id` header, when present) is not part of the stored
  response format, and `DecisionResult` rejects unknown fields, so it is kept beside the result:
  `backend.last_request_id`, `backend.request_ids`, `backend.records` (one `CallRecord` per
  successful call: replay key, model, request id, usage, date) and the recorder's optional sidecar.

## Budget guard

`LiveBackend(model, *, client=None, max_requests=25, max_retries=2, request_kwargs=None)`.

- At most `max_requests` attempts per backend instance, enforced before each send. The next one
  raises `BudgetExceeded` and nothing is sent. The budget belongs to the instance: a new
  `LiveBackend` (or a second `get_backend()` call under `JEV_COOKBOOK_LIVE=1`) starts a fresh one.
  Cumulative accounting across instances, runs and sessions is the orchestrator's job, not this
  module's; persist `backend.ledger()` and the recorder sidecar (below) for it.
- `request_kwargs` accepts only `provider` and `timeout`. Anything else (`retry`, `extra_body`,
  `extra_headers`, `state`, `questions`, `model`, `response_model`, ...) raises `ValueError`,
  because it could change what is sent or how many requests one call makes. The backend also
  passes its own no-retry policy on every call whenever the client's `system_one` takes `retry=`
  (the SDK's does), so a client built with its own retries cannot exceed the budget either: at
  most `max_requests` HTTP requests are ever sent.
- Retries count. A request whose outcome is unknown (timeout after send) counts as spent. So does
  a request the API answered with an error, and one whose response failed validation.
- Retries: HTTP 408, 429 and 5xx, connection errors and timeouts, up to `max_retries` times with
  exponential backoff from 0.5 s capped at 8 s. Only the SDK's 429 retry hint is honoured (capped
  at 30 s); a `Retry-After` header on any other status, such as a 503, is not read.
  Other errors (400, 401, 403, 404, 422, anything unknown) are not retried. When it builds its own
  client the backend turns the SDK's retries off (`RetryPolicy(max_retries=0)`), so this loop is
  the only one and every attempt is counted.
- For a ledger: `requests_made`, `requests_remaining`, `max_requests`, `usage_total` (a `Usage`
  summing the counts the API reported; `None` until a call reports one), `records`, and
  `ledger()`, a plain dictionary (requested and returned model, budget, requests made, successes,
  failed attempts, token sums, calls that did not report both counts, request ids). It holds no
  key, state or answers.

An injected `client` is yours: any object with `system_one(state=..., questions=..., model=...)`
returning an SDK-style response. The backend requires no opt-in or key for it (it reads
`TYPESAFE_API_KEY` only to scrub that text from error messages). If the client's `system_one` takes
`retry=` the backend passes a no-retry policy per call, so the SDK's own retries cannot add
requests; a client without that parameter that retries inside itself is invisible to the budget,
so build it with retries off.

## Recorder

```python
from jev_cookbook import LiveBackend, record

report = record(
    LiveBackend("jev-1.13.0", max_requests=40),
    [(state, questions) for state in states],  # the same question definitions
    "recipes/NN-slug/fixtures/responses.json",  # explicit path; the template decides it
    overwrite=False,
    ledger_path=None,  # optional request-id sidecar
)
```

`record(backend, requests, responses_path, *, overwrite=False, ledger_path=None) -> RecordReport`.

- `requests` is an iterable of `(state, questions)` pairs. `responses_path` is passed explicitly
  so the fixture layout of issue #65 can be applied by the recipe template; this module imposes no
  folder or file name.
- The file is exactly the `ReplayBackend.from_json` format: one JSON object
  `{replay_key: stored_response}`, each value `DecisionResult.to_dict()`, provenance `recorded`
  with the returned model string and the date. It is written with sorted keys, two-space indent,
  UTF-8, LF and a final newline, atomically (temp file then replace). A recorded fixture replays
  byte for byte: `json.dumps(replay.decide(...).to_dict())` equals the stored value.
- Merging: an existing file is read and extended. A key already in the file is skipped without a
  call (no budget spent) unless `overwrite=True`. `merge_responses(path, additions, *,
  overwrite=False)` is the underlying merge: a key present with a different response raises
  `RecordConflict`; an identical one is a no-op; a merge that would leave the file unloadable by
  `ReplayBackend` (a second model, or synthetic and recorded mixed) raises `RecordConflict` and
  writes nothing.
- Each response is written as soon as it arrives, so an error later in the run (budget, network, an
  invalid answer) keeps what was already paid for. Duplicate requests in one run are sent once.
- A paid response that cannot be merged (for example the alias moved and the file holds another
  model, or the same key holds a different answer) is not lost: it is written to a drift file
  `<responses stem>.drift-<returned model><suffix>` (for example
  `responses.drift-jev-1.14.0.json`) in the same directory as the main file, which is left
  untouched, and `RecordConflict` is raised with `.result` (the `DecisionResult`) and `.saved_to`
  (the drift file). The name is deliberately not a fixture name: the fixture validator flags it as
  a stray file, which is the signal for the author to deal with it (keep it out of the commit, or
  record again with a pinned model). Pin the model to avoid this.
- One recorder per responses file: the merge is read-modify-write, and two recorders on one file
  race.
- `RecordReport` lists `written`, `skipped` and `unchanged` keys, the number of attempts the
  backend made, and the returned model.
- `ledger_path`: a JSON sidecar with one line for every paid call made in this run. It is separate
  from the responses file because the stored-response format has no field for the request id. It
  is optional, and **it must live outside `fixtures/`**: `record` refuses (`ValueError`, before any
  call) a path inside a `fixtures/` directory, because the fixture validator rejects stray files
  there. Never commit it as a fixture. It is rewritten atomically after every call.
  - A call that produced a response is `{replay_key: {status: "recorded", request_id, model, date,
    input_tokens, output_tokens}}`, written before that response is merged, so a merge conflict
    still leaves its request id.
  - A call that produced nothing to record is written before the error is re-raised, as
    `{replay_key + "!failed-N": {status, error_type, http_status, request_id, model, date,
    attempts}}`. `status` is `invalid_response` (the API answered but the result failed
    validation, or contained the key), `error` (an HTTP or connection error), `timeout` or
    `budget_stopped`. `attempts` is the number of HTTP attempts that one call spent (0 for a budget
    stop). `request_id` is filled whenever a response came back, including a rejected 200; a
    timeout has none. The same id is on the exception (`LiveResponseError.request_id`,
    `LiveCallError.request_id`). A failed line never replaces the entry of an earlier call for the
    same key.
  - `overwrite=True` still replaces the earlier `recorded` entry for a re-recorded key.

Operational notes for a recording run:

- Every attempt counts against the budget, including each retry. `max_retries` defaults to 2, so a
  budget of N can yield fewer than N responses: a flaky run may spend three attempts on one
  request.
- Keep `TYPESAFE_LOG_LEVEL` unset (see the logging section below).
- Only `provider` and `timeout` are accepted per call (`request_kwargs`); anything else raises
  `ValueError`.
- The sidecar lives outside `fixtures/`, as above.
- A response whose serialized form contains the API key (in any spelling) is refused as an
  `invalid_response` and never written to a fixture, the sidecar or `backend.model`.

### Tolerances: what the first real recording settles

The answer classes check confidence, score and sum with bounds that allow for two-decimal
rounding (`docs/backends.md`, Tolerances). Those bounds are provisional. If a recorded response
ever fails them, `record` raises `LiveResponseError` naming the question and the field (for
example `confidence does not match the published Choice formula`) with the reported values, and
attaches the parsed body as `.response`. Nothing is loosened and nothing is written for that
response; the call is counted as spent. The orchestrator decides what to do next.

The first real recording confirms whether the API rounds its numbers at all. If it does not, the
bounds should be tightened in their own reviewed change; if it rounds differently from two
decimals, they should be widened or the premise restated there. Until then no claim is made
either way.

## What is and is not logged

- This module makes no `logging` calls and prints nothing. The key is read once and passed to the
  SDK client; the backend keeps only the private strings it scrubs with, so the key is not in
  `repr`/`str` of the backend, in
  `ledger()`, in `records`, in fixtures or in the sidecar. Error messages carry the exception
  class, HTTP status, the request id and the SDK's message with every form of the key (as
  exported and trimmed) replaced by `[redacted]`. They are raised after the SDK's exception has
  been handled, so neither `__cause__` nor `__context__` carries it. An HTTP 200 that the SDK
  rejects (a missing field, a body that is not JSON) is a `LiveResponseError` whose `.response`
  is the parsed body, scrubbed the same way, or `None` for a non-JSON body.
- The SDK has its own `typesafe_sdk` logger (`TYPESAFE_LOG_LEVEL`). It redacts secret headers,
  but at DEBUG it logs request and response **bodies unredacted**, so a server that echoes the key
  in an error body would put it in the log. When the backend builds its own client it installs a
  `logging.Filter` on that logger that replaces every spelling of the key (as exported, trimmed,
  and their repr and JSON escapes) with `[redacted]` in the message and its arguments, leaves the
  rest of the line as the SDK wrote it, and removes it again in `close()` (shared and reference
  counted across backends). **An injected client is the caller's responsibility:** the backend
  installs nothing for it, so redact its logging yourself. The request and response bodies still
  contain your state and the answers, so keep `TYPESAFE_LOG_LEVEL` unset in notebooks whose state
  is sensitive, and do not paste its output into a pull request.
- Recorded fixtures contain the answers and provenance only, never the state. Keep notebook
  output free of the key as always (`CONTRIBUTING.md` section 1).

## Alternative backends: the System One Adapter (S08)

Decision: **deferred; the interface seam exists now, and the adapter is not an optional extra in
this change.**

What the source says (`https://github.com/typesafe-ai/system-one-adapter-python`, catalog
source S08): `SystemOneAdapterClient` is a drop-in replacement for `typesafe_sdk`'s `system_one`
call, backed by provider SDKs (OpenAI-compatible, Anthropic, Gemini) installed as its own extras.
Its `system_one(state=, questions=, model=)` returns a `typesafe_sdk.SystemOneResponse` subclass
with extra `usage` and `debug` fields, and takes a `provider=` argument. Each provider needs its
own credentials (not `TYPESAFE_API_KEY`), and its probabilities come from a generative model
that the adapter normalizes or discretizes by option.

Why deferred: the recipes that need it (50, model comparison and calibration; 55, adaptive model
routing) have to compare backends on identical labeled tasks, which is a design question about
fixtures per backend, per-backend replay keys or files, and cost accounting, not about transport.
A premature extra would also add provider keys and a second kind of `recorded` provenance (a model
string that is not a System One model) before the fixture format of #65 and the comparison design
of those recipes exist. Recorded provenance stays honest in the meantime: an adapter call is a real
API call, and the model string is whatever the provider returns.

The seam (so nothing needs to change later):

```python
from system_one_adapter import SystemOneAdapterClient  # not a dependency of jev_cookbook

backend = LiveBackend(
    "gpt-4o-mini",  # the model string sent
    client=SystemOneAdapterClient(structured_outputs=True, llm_answer_mode="probabilities"),
    request_kwargs={"provider": "openai"},  # passed to every system_one call
    max_requests=100,
)
```

This already type-checks against the contract above: `LiveBackend` only needs `system_one` and
SDK-shaped responses, ignores the adapter's extra `usage` and `debug` fields, and reads no
environment variable for an injected client. This snippet is a design note, not a tested path:
no test builds an adapter client. Two cautions when it is used: the adapter's own provider
retries are invisible to the request budget (set them low), and one `system_one` call may make
several provider requests, so the budget counts calls to `system_one`, not provider requests. A
later issue should decide whether a named `AdapterBackend` (own opt-in variable, own key rules, a
fixture file per backend) belongs in `jev_cookbook` or in recipes 50 and 55 themselves.
