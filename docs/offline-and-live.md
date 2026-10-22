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

## What the recipe guard checks about section 2

[CONTRIBUTING.md](../CONTRIBUTING.md), section 2, is a rule about meaning: no notebook, README or
pull request may state or imply anything about Jev's quality, latency or cost except as measured on
N examples with the returned model version and capture date. No test can judge meaning, so a green
guard is **not** a guarantee that a recipe is honest. `tests/test_recipe_guard.py` enforces a
floor, built only from what is decidable from the files. Each check below runs over every
published recipe and the template, and its failure message points here.

| Check | A recipe fails it when |
| --- | --- |
| `reported_provenance_matches_fixtures` | The mode the committed output reports (the `Mode:` header, a `Provenance:` line, the measured cell's offline disclosure, a `Captured:` line) is not the provenance the stored answers carry. All-synthetic fixtures must report `synthetic` and the disclosure. Recorded fixtures must report `recorded` and state exactly the model and the capture dates the fixtures carry, in both directions: the header says `on D` or `between FIRST and LAST`, every `Provenance: recorded` line names that model (and, per answer, one of those dates), the `Captured:` lines list exactly those dates, no other `jev-N.N.N` model string appears in the output, and no pipeline-check label does. A date or a model the output states beyond the fixtures', or a line of those forms the check cannot read, is a failure, as is a missing one. A header, a provenance line or a fixture the check cannot read is a failure, not a pass. |
| `readme_states_fixture_provenance` | The README's `**Mode:**` line names another mode than the fixtures carry, a recipe with no live run never says "not measured live", or a recorded recipe's README omits its model or capture dates, or states a date or a `jev-N.N.N` model string the fixtures do not carry. The mode must be the first word after `**Mode:**` (`synthetic`, `scripted` or `recorded`); only the first `**Mode:**` is read. |
| `metric_output_lines_carry_pipeline_check` | In a synthetic or scripted run, a committed output line names a metric (coverage, accuracy, risk, precision, recall, F1, nDCG, agreement, AUC, MRR, Brier, error rate, hit rate) and prints a decimal or a percentage without `(a pipeline check, not a Jev result)` on the same line. It reads the printed line, so `{x:.2f}` versus `{x:.4f}`, an aligned spec, or a format hoisted into a variable does not change the result, as long as a metric word is on the same line as the number: an aligned table whose header names the metrics and whose rows carry only numbers, a word on one line and its number on the next, and a metric named by none of the words above are not seen. |
| `prose_quantities_are_printed` | The README or a notebook markdown cell quotes a percentage or decimal next to a metric word, a price, a latency or a throughput, and no committed output prints that number (or, for a metric, the recipe's own tests type it). A quote of `0.92` is backed by a printed `0.9167`; `97.4%` by `0.974`; `1,250` by `1250`. Risk and accuracy back each other, but only through a printed rate: a quoted risk or accuracy is also backed by one minus a decimal (two or more places, between 0 and 1) or by 100 minus a percentage that was printed on a line naming accuracy, risk or error rate, so a printed `accuracy 0.9474` backs a quoted risk of `0.0526`, and a printed confidence or a count does not. A printed percentage also backs its fraction. A price or a latency is backed only by a printed price or latency, so a printed sample size does not back "180 ms". A duration is read as a claim about Jev only when its sentence says latency or response time, or says slow, fast, speed or takes together with Jev, the model, the API, inference or a live run; "the notebook takes about 2 minutes" is not. A quote is read when it sits next to the metric word through only a connective ("is", "of", "at", "reaches", "about" and a few more). |
| `no_unhedged_quality_claim_about_jev` | In a synthetic or scripted recipe, a README or markdown sentence has Jev or the model as the subject of an evaluative adverb or adjective (correctly, reliably, well, accurate, fast, cheap, right) or says it outperforms something, and the sentence has no negation, hypothetical or attribution ("not measured live", "would", "according to", "TypeSafe's notes say"). A sentence here is a heading, a table row, a list item (with its wrapped lines) or one sentence of a paragraph: a hedge word in a neighbouring bullet, or in the heading above, does not excuse it. The failure message prints the sentence. |

A fabricated "97.4% accuracy, 180 ms median latency, $0.0004 a call" fails
`prose_quantities_are_printed` in the README and in a notebook cell alike.

### What none of this covers: the reviewer's alone

These parts of section 2 have no mechanical check. The reviewer is the only enforcement, and reads
the README and every markdown cell for them:

- A claim about what Jev does that has no number and no evaluative word ("Jev judges from the
  evidence as a whole"). The claim check above flags `Jev judges these correctly`, and passes a
  synonym ("flawless"), a plain assertion, and a claim whose subject is a model string such as
  `jev-1.13.0` rather than Jev or the model.
- An attributed quality claim ("TypeSafe says Jev is accurate"). The claim check reads an
  attribution as a hedge, but section 2 holds even when a figure is attributed to someone else.
- A true number given a false interpretation. The prose check confirms a quoted number was
  printed somewhere, not that it is the right number in the right place: a quoted `1.0000` is
  backed by any printed `1.0000`. Backing is by existence, so it is strong for a four-decimal
  quote and weak for a round one: in a recipe that prints many numbers, a fabricated two-decimal
  value is often already printed by coincidence (measured across the published set, roughly a
  third to four fifths of all two-decimal values per recipe, against a few percent at four
  decimals). The check also reads no latency written `0.18 s` or in words, no price with neither a
  cost word nor a unit of work ("Jev at $0.0004 is affordable"), and no number spelled in words.
  A quoted parameter or target ("coverage stays at 0.70 by construction") is read as a quote, so
  it must be printed.
- A stale or inflated N ("20 examples" printed where the fixtures hold 22), and a header line that
  claims real measurement while the mode word is unchanged: the mode and the disclosure are
  checked, N is only required to be printed.
- A fixture-derived statistic offered as evidence about the model, such as the share of
  comparisons whose first-listed option was chosen, which offline measures only the person who wrote
  the fixtures.
- A metric that is perfect by construction, printed with its pipeline-check label and without
  saying that the fixtures or the selection force it.
- A sentence that misdescribes the notebook's own committed output ("each misses one record",
  "every answer is on the correct side of its threshold") without quoting a number the output did
  not print.
- A count with no decimal, such as `15 of 15`, which is not a metric line to the label check.
- Any statement in a pull request description or comment: the guard reads files, not pull requests.
- A quality, latency or cost figure attributed to TypeSafe or a third party that the check above does not
  see (it quotes no number beside a metric word, a price or a latency). Section 2 forbids
  it without the same recorded, held-out evidence.

### The older metric-line checks

`validation_lines_carry_selection_and_check` and `metric_lines_carry_check` look for a `print(`
whose call spells a rounded-float format (`{x:.4f}`) beside a metric word. They cover that one
formatting convention. A metric printed through an aligned spec, a hoisted format string or a helper
is outside them, as is any prose. Their existence is not evidence that section 2 is enforced;
`metric_output_lines_carry_pipeline_check` is the check that reads what was printed.

### Ideas considered and rejected

- A notebook that says `recorded` must have a non-synthetic response: every recipe, the template
  included, says `recorded` in its prose, to state what a recorded recipe would add. The structural
  form above compares what the output reports with what the fixtures carry.
- Any evaluative word in a sentence that mentions Jev: most of those sentences are disclosures that
  name accuracy, cost or latency in order to deny them, comparisons between a recipe's own baselines
  on its own fixtures, or quotations of TypeSafe's documentation. Only the narrow form above is
  checked.
- A warning the author answers in the pull request: a recipe pull request can change only its own
  folder, so it has no place to answer one.

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
- pin a versioned model such as `jev-1.13.0` when you record, not an alias. The recorder accepts an alias
  and does not stop you, so the person recording must not use one: an alias moves when a release
  ships, and a recording made through it may not be reproducible ([live.md](live.md#model)).

A recorded fixture contains the answers and their provenance, never the state
([live.md](live.md#what-is-and-is-not-logged)). A recording is a deliberate act by a
maintainer with a key. The notebook executor (`tools/execute_notebook.py`) never runs live and removes
`JEV_COOKBOOK_*` and `TYPESAFE_*` from the kernel it starts, so a committed notebook cannot hold a
live result by accident ([recipe-template.md](recipe-template.md#executing-a-notebook)).
