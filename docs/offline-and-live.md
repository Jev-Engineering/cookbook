# Offline and live

Every recipe can run in two ways, and the notebook always says which one it ran in. This page
explains the two, what each one can and cannot show, and where the limits are. Terms are defined in
the [glossary](glossary.md). To run something, start with [getting-started.md](getting-started.md).
Statements about Jev link to the README [sources table](../README.md#sources) (S01 to S08), whose
root is the TypeSafe documentation index, <https://docs.typesafe.ai/llms.txt>.

## The two modes

**Offline** is the default. The notebook needs no network and no API key. It sends each question
to a backend from `jev_cookbook` that answers from stored data instead of calling Jev:

- a **replay** backend looks the request up by its [replay key](glossary.md#replay-key) in the
  recipe's `fixtures/responses.json`. A request with no stored answer raises an error; nothing is
  invented to keep a notebook running ([backends.md](backends.md#replay-key));
- a **scripted** backend computes an answer from a small function the recipe supplies, with a
  seeded random generator, for recipes built on a simulator ([backends.md](backends.md#scripted-backend)).

**Live** is a choice you make. The same notebook sends the same questions to the TypeSafe System
One API ([S01](https://docs.typesafe.ai/introduction)) and gets the same typed answers back, so
switching modes changes the backend and nothing else. It needs the optional SDK, three
environment settings and your own key ([live.md](live.md#opt-in)). Continuous integration never
makes a live call and needs no key.

| | Offline | Live |
| --- | --- | --- |
| Where answers come from | Stored fixtures (replay) or a script (scripted) | The API, at the time you run it |
| Network and key | None | Needed |
| What the numbers can show | That the pipeline works, unless the fixtures are recorded | Only the examples and model of that run |

## Provenance: where a stored answer came from

Every answer carries its [provenance](glossary.md#provenance):

- **`synthetic`**: written for the recipe, by a person or a script. No model produced it. Some are
  wrong on purpose, so that the evaluation has something to find.
- **`recorded`**: captured from a real API call by the recorder (below), with the model string the
  API returned and the date of the call.

A responses file is all one or the other, and one model, so the two never mix inside a file
([fixtures.md](fixtures.md#responses-and-provenance)). Nothing is labelled `recorded` unless it came
from a real call. Recorded fixtures are a step in the build process: no recipe in the repository
carries one yet, so a recipe runs today as `synthetic` or `scripted`, and its README says so.

## The run-mode header

The first output of a notebook is a three-line header from `jev_cookbook.style.run_header`. It names
the [run mode](glossary.md#run-mode), the model for the two modes that involve one, and N, the number of examples
the run covers. In a recipe the header is written from the backend itself, so it cannot disagree
with what ran. The four forms, with a recipe number, title and N filled in as an example:

```text
Recipe 01: Sentiment classification
Mode: offline replay of synthetic fixtures, pipeline check on a fixture sample of 20 examples
Metrics in this run are checks that the pipeline works. They are not Jev results.
```

```text
Recipe 01: Sentiment classification
Mode: offline, scripted backend, pipeline check on a fixture sample of 20 examples
Metrics in this run are checks that the pipeline works. They are not Jev results.
```

```text
Recipe 01: Sentiment classification
Mode: offline replay of recorded fixtures
The answers were captured from real Jev calls to model <model string the API returned> on <YYYY-MM-DD>. Any numbers below describe only that recorded sample of 20 examples.
```

```text
Recipe 01: Sentiment classification
Mode: live
Calls are being made now to model <model string>. Any numbers below describe only the 20 examples in this run.
```

If you see the first or second form, the next section applies to every number below it.

## Why synthetic metrics are pipeline checks

In a `synthetic` or `scripted` run, the answers were not produced by a model. An accuracy, a
routing count or a confusion matrix then measures the recipe's own plumbing: that the state is built,
the questions are asked, the answers are read, the rule in Python holds, and the evaluation code adds
up. That is worth knowing, and it is why a recipe can run in CI. It says nothing about how Jev
behaves, because Jev took no part: the numbers come from answers someone wrote, some deliberately
wrong. The notebook prints a short `check` note next to such a number, and the header says so in its
last line ([CONTRIBUTING.md](../CONTRIBUTING.md), section 2).

Where the cookbook describes what Jev does, it describes it from the documentation, with a link:
for example that a question returns typed answers and probabilities
([S02](https://docs.typesafe.ai/primitives)), or how confidence follows from the probabilities
([S03](https://docs.typesafe.ai/confidence)). It makes no statement about Jev's quality, latency or
cost. A statement like that is allowed only when it comes from recorded inference on a held-out set,
with the model version stated.

## What "not measured live" means

A recipe's README says **not measured live** when no real Jev call was made for it. It is a plain
statement of fact, not a warning that something is missing. It means:

- every number in the notebook is a pipeline check;
- the recipe teaches the pattern (the typed question, the rule Python enforces, the way to evaluate
  it), and it does not tell you how Jev scores on this task;
- if you want that, run the recipe live yourself on your own data.

A recipe that does carry recorded fixtures states, for every number it reports, the model string the
API returned, the capture date and N. Those numbers describe that sample and nothing wider: not
Jev's quality in general, and not latency or cost unless those were measured and recorded.

## The live path

Three things are needed: the SDK (`pip install -e ".[live]"` from a checkout), `JEV_COOKBOOK_LIVE=1`
and `JEV_COOKBOOK_LIVE_MODEL`, and the key in the environment variable `TYPESAFE_API_KEY`. The key
is read from the environment when the backend is built, and nowhere else. Never put it in a
notebook, a fixture or any committed file. The setup, the model rule and every error message are in
[live.md](live.md#opt-in); what follows is the part that protects you from running up calls by
accident.

### The budget guard

A live backend counts every attempt it sends and refuses to send more than a limit you set
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, default 25; or `max_requests=` when you build the backend
yourself). The next attempt past the limit raises `BudgetExceeded` before anything is sent.
Retries count against the limit, so a limit of N can give fewer than N responses. The guard belongs
to one backend object: starting a new one starts a new count, so keeping a running total across runs
is up to you. The backend's `ledger()` gives a plain record of what was sent, with no key and no
state in it ([live.md](live.md#budget-guard)).

### The recorder

`record` runs requests through a live backend and writes the answers into a recipe's
`fixtures/responses.json`, so that later runs can replay them offline:

- the file is the same one the replay backend reads, with provenance `recorded`, the model string
  the API returned, and the date;
- it merges: a request already in the file is skipped without a call, and a different answer for
  the same request is a conflict, not an overwrite;
- every answer is written as soon as it arrives, so an error later in a run keeps what was
  already received;
- a recording pins a versioned model, not an alias, so that it can be reproduced
  ([live.md](live.md#model)).

A recorded fixture contains the answers and their provenance, never the state
([live.md](live.md#what-is-and-is-not-logged)). A recording is a deliberate act by a
maintainer with a key. The notebook executor (`tools/execute_notebook.py`) never runs live and removes
`JEV_COOKBOOK_*` and `TYPESAFE_*` from the kernel it starts, so a committed notebook cannot hold a
live result by accident ([recipe-template.md](recipe-template.md#executing-a-notebook)).
