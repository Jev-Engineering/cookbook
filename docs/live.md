# Live backend and recorder

`LiveBackend` sends the questions a notebook already uses offline to the TypeSafe System One API
and returns the same `DecisionResult` objects as replay. `record` runs requests through it and
writes the responses into a recipe's fixtures. Nothing here runs in CI: **CI never makes a live
call and needs no key.** Every test mocks the HTTP layer (a fake client, and
`httpx2.MockTransport` under the real SDK types when the SDK is installed).

## Opt in

Three things are needed, and each missing one gives an error that says what to do:

1. The optional SDK: `pip install 'jev_cookbook[live]'` (this pins `typesafe-sdk>=0.7.5,<0.8`).
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

**Only the lane meant to go live is built through `get_backend`.** A recipe that compares
backends and has a lane that must stay offline (a fabricated adapter, a baseline replayed from its
own file) builds that lane directly with `ReplayBackend(...)`, `ReplayBackend.from_json(...)` or
`ScriptedBackend(...)`. Through `get_backend` it would become a live backend, on the model from
`JEV_COOKBOOK_LIVE_MODEL`, in live mode. Offline runs and CI cannot show the difference. Read
[backends.md](backends.md#which-lane-goes-through-get_backend) before writing a multi-backend
harness.

### Model

**Recordings must pin a versioned model: use `jev-1.13.0`, not an alias.** The model is passed
explicitly for every run, never defaulted. The documentation lists the pinned
IDs `jev-1.13.0`, `jev-1.14.0` and the aliases `jev-latest` and `jev-preview`. An alias moves when a release
ships, so a recording made through an alias may not be reproducible later; the response's `model`
field reports the versioned ID that answered. `backend.model` is the requested string until the
first response and the returned string afterwards (`backend.requested_model` keeps what was
sent). The returned string is what goes on `DecisionResult.model` and into every answer's
`Provenance.recorded(model, date)`, with the UTC date of the call.

### Experimental images and long context

Pass `images=True` and/or `long_context=True` to `LiveBackend` or `get_backend`.
These booleans add exactly `TypeSafe-Danger-Zone-Images: true` and
`TypeSafe-Danger-Zone-Long-Context: true`, respectively, to each request.
Their defaults are false and ordinary text calls add neither header.
The existing restriction on arbitrary `request_kwargs["extra_headers"]` still holds.

Pass raw image dictionaries using `decide(state, questions, assets=assets)` as described in
[backends.md](backends.md#images-and-box). Before spending a request, the backend checks the
assets, requires the images flag, and for a Box requires `jev-1.14.0` or `jev-preview`.
Use the pinned `jev-1.14.0` for recordings. An unknown future version is refused for Box until
support is verified; the text-only model behavior is unchanged. The API replaces references in
string values; cookbook passes those strings through and converts assets into SDK `Image`
objects for multipart upload. SDK 0.7.5 introduced this support
([changelog](https://docs.typesafe.ai/sdk/python/changelog)).

These features remain experimental. The model context and server-side request limits still
apply when a header is enabled; enabling a flag is not a measurement of accuracy, token usage,
latency or cost. See [images](https://docs.typesafe.ai/images),
[Box](https://docs.typesafe.ai/primitives/box), and [models](https://docs.typesafe.ai/models).

### Context limits

These are the limits the models page states, read on 2026-10-31 at
<https://docs.typesafe.ai/models>. Its table gives the context length of `jev-1.14.0` and
`jev-1.13.0` as "64k per-request / 32k per-question". The page defines the per-request context as
the state plus all questions combined and the per-question context as the state plus any one
question, and a request has to fit both. It sets no separate limit on the number of questions.
Sending the header `TypeSafe-Danger-Zone-Long-Context: true`, which `long_context=True` adds,
raises both limits to 262k tokens on either model. The page adds that long context costs the same
per token and is slower and less accurate than staying inside the default limits.

The page states the 262k figure in tokens and does not say what a "k" in its table counts, so this
cookbook converts none of the three limits to characters, and it does not check a request against
them. [`context_size`](vision.md#context-size-and-the-comparison-table) counts characters and
UTF-8 bytes, which are not tokens. The one token count the cookbook can show is the
`usage.input_tokens` of a recorded response, which may be `null`. The documentation index at
<https://docs.typesafe.ai/llms.txt> (read on 2026-10-31) lists no page or endpoint for counting or
estimating tokens, and the cookbook has no estimator.

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
  successful call: replay key, model, request id, usage, date, `images` and `distinct_images`
  (both 0 unless the call carried image assets) and `latency_seconds`, see [Latency](#latency))
  and the recorder's optional sidecar.

## Budget guard

`LiveBackend(model, *, client=None, max_requests=25, max_retries=2, request_kwargs=None,
images=False, long_context=False)`.

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
  failed attempts, token sums, calls that did not report both counts, request ids). When any
  successful call carried image assets it also holds `images` (image copies) and `distinct_images`,
  each summed over the successful calls; a text-only ledger has neither key. It holds no key,
  state or answers.

- The cap is inclusive and per backend. With `JEV_COOKBOOK_LIVE_MAX_REQUESTS=N` a backend sends
  N attempts and refuses the (N+1)th, so a recipe that makes N requests on one backend runs to the
  end at a cap of N, and at N-1 it stops at its last request. `get_backend` reads the variable for
  each backend it builds, so a notebook with two backends sends up to N through each: the cap is
  never a limit on the run. A recipe's README therefore names the largest single backend's count
  as the cap and its total as what the run spends, and a cap that is met exactly leaves no room for
  a retry.

`AuditedBackend` can wrap the same instance to count logical `decide()` invocations and emit
offline execution evidence for a recipe's README budget note; see
[actual calls and distinct requests](backends.md#actual-calls-and-distinct-requests).
Its count includes repeated identical requests and failed delegated calls. It is separate from
`requests_made`: one logical call can retry several HTTP attempts, or spend zero attempts when
the budget is already exhausted. Distinct fixture keys count neither of those quantities.
The wrapper forwards the live recorder's attributes and settings to this same backend instance.

**A recipe's request count is declared once** in `request_budget.json`; the README's budget
paragraph is rendered from it and the recipe guard compares both with the audited offline
execution, so the count the README promises, the `JEV_COOKBOOK_LIVE_MAX_REQUESTS` it tells you to
set and the requests the notebook makes cannot drift apart for a recipe that has adopted the
declaration (the others keep the older check, which cannot see a repeated request)
([the declaration](backends.md#the-declared-count-request_budgetjson)). The audit replays the
committed answers; a recipe whose later requests depend on earlier answers declares the longest
path it can take, and the README's cap follows that bound. Totals for budget arithmetic are the
sum over a recipe's backends (what is billed); the cap is the largest single backend.

An injected `client` is yours: any object with `system_one(state=..., questions=..., model=...)`
returning an SDK-style response. The backend requires no opt-in or key for it (it reads
`TYPESAFE_API_KEY` only to scrub that text from error messages). If the client's `system_one` takes
`retry=` the backend passes a no-retry policy per call, so the SDK's own retries cannot add
requests; a client without that parameter that retries inside itself is invisible to the budget,
so build it with retries off.

## Latency

Each HTTP attempt is timed with the backend's `clock` (default `time.perf_counter`, a monotonic
clock; pass `clock=` to inject one in a test). The clock is read once immediately before
`client.system_one(...)` is called and once immediately after that call returns or raises. The
difference, rounded to a nanosecond, is the attempt's `latency_seconds`.

| What | In the timed window? |
| --- | --- |
| Whatever the client does inside the one `system_one` call | Yes |
| The budget check that counts the attempt | No: it comes first, so `requests_made` already includes the attempt at the first reading |
| The cookbook's validation of the response | No: it comes after the second reading |
| The backoff sleep before a retry | No: it falls between one attempt's second reading and the next attempt's first |
| The recorder's ledger write | No: it happens after `decide` has returned |

The cookbook does not look inside the client, so `latency_seconds` is the wall-clock time of that
call as seen from the machine that made it. It is not a server-side or model-only time.

Where it is kept:

- `CallRecord.latency_seconds` and `backend.last_latency_seconds` hold the answering attempt's.
- Each entry of `backend.last_retried` holds the `latency_seconds` of the failed attempt it
  describes.
- The recorder's sidecar holds it on a `recorded` line (the answering attempt), on every entry of
  `retried`, and on a failed line (the attempt that ended the call; null when that call sent
  nothing, such as a budget stop or a refusal).
- It is not in the responses file and not in the replay key: recording one request under two
  different clocks writes byte-identical response files.
- `backend.ledger()`, the in-memory summary, has no latency field.

A latency is null when the clock gave no usable reading: a difference that is negative or not
finite, a clock that raises, or readings that cannot be subtracted. A call that took several
attempts has one latency for its answering attempt; the failed attempts' latencies are in
`retried`, and the backoff between attempts is in none of them, so their sum is not the call's
elapsed time.

### Reading a captured latency back

`load_ledger_latency(ledger_path, replay_key)` returns a `LedgerLatency(latency_seconds, date,
model)` for the `recorded` line stored under the key. It returns `None`, meaning "not measured",
when the ledger has no `recorded` line under that key or the line has no latency (a ledger
written before latency was captured has none). It reads only the line under the key itself: not a
`!failed-N` line, not a `superseded` history entry, and nothing from a replay. It raises
`FileNotFoundError` for a ledger file that does not exist and `ValueError` for a latency that is
not a finite, non-negative number, or a line without a text date or model.
[vision.md](vision.md#honest-accounting) shows the result feeding `run_record`.

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

- `requests` is an iterable of `(state, questions)` pairs or `(state, questions, assets)` triples.
  Image content participates in deduplication, replay keys and ledger keys. Assets themselves
  are sent to the API but are not written to the responses or ledger file.
  `responses_path` is passed explicitly
  so the fixture layout of issue #65 can be applied by the recipe template; this module imposes no
  folder or file name.
- The file is exactly the `ReplayBackend.from_json` format: one JSON object
  `{replay_key: stored_response}`, each value `DecisionResult.to_dict()`, provenance `recorded`
  with the returned model string and the date. It is written with sorted keys, two-space indent,
  UTF-8, LF and a final newline, atomically (temp file then replace). A recorded fixture replays
  byte for byte: `json.dumps(replay.decide(...).to_dict())` equals the stored value.
- `jev_cookbook.dump_responses(data)` returns exactly that text for a `{replay_key: response}`
  mapping and writes nothing. A scaffolded `build_fixtures.py` writes `responses.json` with it, and
  the scaffolded `tests/test_build_fixtures.py` asserts the committed file equals
  `dump_responses(build_responses(ROWS))`: what the synthetic generator would write, serialized
  exactly as the recorder serializes. (That test describes a synthetic fixture set; once a recipe
  merges a recorded answer it no longer holds.) `jev_cookbook.live._dump` is the same function
  under its old, private name, kept only as a transitional alias for code outside `recipes/`;
  no recipe may use it.
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
  record again with a pinned model). Pin the model to avoid this. The drift file lands next to the
  responses file, so the fixture validator will flag it as a stray file; that is intended, because
  it makes sure nobody commits it unnoticed.
- One recorder per responses file: the merge is read-modify-write, and two recorders on one file
  race.
- `RecordReport` lists `written`, `skipped` and `unchanged` keys, the number of attempts the
  backend made, and the returned model.
- `ledger_path`: a JSON sidecar with one line for each call `record` makes to `decide` in this
  run: a call that produced a response, and a call that raised, including one refused before
  anything was sent, which spends nothing. A request that fails validation (for example an asset
  that no state, instruction or criteria value names) never becomes a `decide` call: `record`
  raises before any call and writes no line for it. The sidecar is separate
  from the responses file because the stored-response format has no field for the request id. It
  is optional, and **it must live outside `fixtures/`**: `record` refuses (`ValueError`, before any
  call) a path inside a `fixtures/` directory, because the fixture validator rejects stray files
  there, and a path that is the same file as `responses_path` (including through a different
  spelling or a link). Never commit it as a fixture. It is rewritten atomically after every call.
  - A call that produced a response is `{replay_key: {status: "recorded", request_id, model, date,
    input_tokens, output_tokens, latency_seconds, attempts, retried}}`, written before that
    response is merged, so a merge conflict still leaves its request id. `request_id` is the id
    of the answering attempt, and `latency_seconds` is that attempt's [latency](#latency).
    `attempts` is every HTTP attempt that call spent, the answering one included (1 when
    nothing was retried). `retried` lists the failed attempts it retried past, oldest first, as
    `{error_type, http_status, request_id, latency_seconds}` (`http_status` and `request_id` are
    null when the attempt got no response, for example a timeout; `latency_seconds` is that
    attempt's own latency); it is `[]` when nothing was retried.
    `images` and `distinct_images` (the image copies and the distinct assets, counts only, never
    bytes or references) are added only when the call carried image assets; a text-only call's
    line has neither.
  - A call that produced nothing to record is written before the error is re-raised, as
    `{replay_key + "!failed-N": {status, error_type, http_status, request_id, model, date,
    latency_seconds, attempts, retried}}`. `status` is `invalid_response` (the API answered but
    the result failed validation, or contained the key), `error` (an HTTP or connection error, or any other
    exception that ended the call, including a request refused before anything was sent),
    `timeout` or `budget_stopped`. `error_type`, `http_status` and `request_id` describe the last
    attempt (the one that ended the call; a timeout has no request id; for `budget_stopped`
    `error_type` is `BudgetExceeded` and the other two are null). `latency_seconds` is the
    [latency](#latency) of that same attempt, and null when the call sent nothing (a budget stop
    or a refusal, including a budget stop after earlier attempts were retried). A `decide` call
    refused before anything was sent (`ImageRequestTooLarge` for an image request over a 32 MiB cap, or
    `LiveConfigError` for a request the backend is not set up for, such as image assets without
    `images=True`) is `status: "error"` with `error_type` the exception's class name,
    `http_status`, `request_id` and `latency_seconds` null, `attempts: 0` and `retried: []`; it is
    not a paid call.
    A request that fails validation is not one of these: it raises from `record` before `decide`
    is called and gets no line. `attempts` is the HTTP attempts this call spent: 0 when
    nothing was sent (a budget already spent, or a refusal as above), and otherwise includes any
    attempts made before the call failed or the budget stopped it. `retried` is as above. A failed
    line carries no `images` or `distinct_images`. The same last-attempt id is on the exception
    (`LiveResponseError.request_id`, `LiveCallError.request_id`). A failed line never replaces the
    entry of an earlier call for the same key.
  - Reconciling: within one fresh sidecar, the sum of `attempts` over its lines (including any
    `superseded` entries, below) equals `backend.ledger()["requests_made"]` for the backend that
    ran. Every request id the backend saw is on disk: as `request_id` or inside `retried`.
  - `overwrite=True` keeps the earlier entry: when a key already has a `recorded` line, the new
    line carries the earlier one (and any it already carried) under `superseded`, oldest first,
    each with its own request id, attempts and retried list.

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
  counted across backends). The filter covers the `typesafe_sdk` logger's own messages and
  arguments. It does not cover `exc_info` tracebacks (a handler formats those later) or records
  logged on child loggers such as `typesafe_sdk.x`; SDK 0.7.2 uses neither, and the `<0.8` pin keeps
  it so, but a later SDK that does needs this re-checked. **An injected client is the caller's
  responsibility:** the backend installs nothing for it, so redact its logging yourself. The request and response bodies still
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
SDK-shaped responses, and reads no environment variable for an injected client. The adapter's
extra `usage` block is parsed like any other, so it must have the System One shape
(`input_tokens` and `output_tokens` as non-negative integers or null; anything else raises
`LiveResponseError`), and its `debug` field is not read. This snippet is a design note, not a
tested path: no test builds an adapter client. Two cautions when it is used: the adapter's own provider
retries are invisible to the request budget (set them low), and one `system_one` call may make
several provider requests, so the budget counts calls to `system_one`, not provider requests. A
later issue should decide whether a named `AdapterBackend` (own opt-in variable, own key rules, a
fixture file per backend) belongs in `jev_cookbook` or in recipes 50 and 55 themselves.
