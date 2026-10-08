# Glossary

The words this cookbook uses, in the order a reader meets them. Statements about Jev link to a page
in the README [sources table](../README.md#sources) (S01 to S08); the root of those pages is the
TypeSafe documentation index, <https://docs.typesafe.ai/llms.txt>. Words that belong to this
cookbook and not to Jev link to the page in this repository that defines them. Nothing here says
how well Jev performs, how fast it is, or what it costs.

| Term | Where it comes from |
| --- | --- |
| [state](#state), [question](#question), [Choice](#choice), [Noul](#noul), [Score](#score), [criteria](#criteria), [probabilities](#probabilities), [confidence](#confidence) | Jev, as documented by TypeSafe |
| [threshold](#threshold) | TypeSafe's guidance, and this cookbook's rule for choosing one |
| [replay key](#replay-key), [fixture](#fixture), [provenance](#provenance), [run mode](#run-mode) | This cookbook |

## state

What Jev is asked about: the text or JSON object you supply with a request, such as a customer
review or a record with several parts. Jev judges a state; it does not write text
([S01](https://docs.typesafe.ai/introduction)). In a recipe, Python builds the state, and
identifiers the judgment does not need stay out of it
([template README](../recipes/_template/README.md#what-it-teaches)).

## question

One typed, narrow thing to ask about a state, defined by its type (`Choice`, `Noul` or `Score`),
its `instructions` and, for `Choice` and `Score`, its criteria. Several independent questions go
in one request and are evaluated independently; a question that depends on an earlier answer goes in a
later request ([S02](https://docs.typesafe.ai/primitives)). The cookbook's rule is one specific
thing per question, with the answers combined in Python ([S01](https://docs.typesafe.ai/introduction),
[CONTRIBUTING.md](../CONTRIBUTING.md), section 3). The classes are in
[backends.md](backends.md#questions).

## Choice

The question type that selects one option from a list you supply. The answer holds `choice`, the
selected option, `probabilities` for every option, and a `confidence`
([S02](https://docs.typesafe.ai/primitives)). The cookbook adds explicit `none`, `other`,
`no_match` or `uncertain` options wherever the task needs them
([CONTRIBUTING.md](../CONTRIBUTING.md), section 3).

## Noul

The question type that judges a statement. The answer is `noul`: the probability, from 0 to 1,
that the statement holds. A `Noul` has no separate `confidence`: a value near 0.5 is the uncertain
case ([S02](https://docs.typesafe.ai/primitives), [S03](https://docs.typesafe.ai/confidence)). The
cookbook writes each proposition as a statement that can be true or false, and asks one
independent `Noul` per label when a task allows several labels.

## Score

The question type that places the state on a rubric whose ordered levels you define. The answer
holds `score`, a position along your levels that can fall between two of them, a `legend`,
`probabilities` over the levels, and a `confidence`
([S02](https://docs.typesafe.ai/primitives)).

## criteria

What you tell Jev about the answer space. For a `Choice`, the options, each with an optional
description. For a `Score`, the levels of the rubric, in order
([S02](https://docs.typesafe.ai/primitives)). A `Noul` may carry an optional description of its
outcomes ([backends.md](backends.md#questions)). Python
builds option lists and rubrics, and carries them through to the output unchanged
([CONTRIBUTING.md](../CONTRIBUTING.md), section 3). In this repository the shapes are in
[backends.md](backends.md#questions).

## probabilities

The distribution an answer carries across your options (`Choice`) or levels (`Score`). Its shape
is what the answer says about certainty: concentrated on one outcome, or spread out
([S03](https://docs.typesafe.ai/confidence)). A `Noul` carries a single probability instead of a
distribution.

## confidence

A single number from 0 to 1 that summarizes the shape of a `Choice` or `Score` distribution: 1 when
all the probability is on one outcome, 0 when it is spread evenly. A `Noul` has none
([S03](https://docs.typesafe.ai/confidence)). Because the answer's `probabilities` are included,
you can recompute it, and the cookbook checks stored answers against these formulas.

- **Choice**, with `n` options and `p_max` the probability of the selected option:
  `(p_max - 1/n) / (1 - 1/n)`. Only the top probability counts. It is not the raw top
  probability.
- **Score**, with levels numbered 0 to n-1: one minus the probability-weighted average distance (in
  levels) from the most likely level, divided by the same average for an even spread (measured from
  the middle level), and floored at 0. Probability on a neighbouring level lowers it less than the
  same probability on a distant level. The exact formula, with a worked example, is on the
  [confidence page](https://docs.typesafe.ai/confidence) (S03).
- **Noul** has no `confidence` field, but the page defines one for it anyway, as the Choice
  formula above applied to a yes-or-no Choice (`n = 2`, `p_max = max(p, 1 - p)`), which reduces to
  `|2p - 1|` for a Noul's probability `p`: 0 at `p = 0.5`, 1 at `p = 0` or `p = 1`. It is on the
  *same* 0-1 scale as Choice confidence, not a separate convention. [evaluation.md](evaluation.md)
  provides this as `noul_confidence(noul)`.

## threshold

A cut-off in your own code that turns a number into an action, for example "route to a person when
`confidence` is below the cut-off". TypeSafe's guidance is that a threshold is not one number and
scales with the cost of being wrong ([S03](https://docs.typesafe.ai/confidence)). In this
cookbook a threshold belongs to the task, so a recipe chooses it from labelled `validation`
examples, freezes it, and reports on `test` ([evaluation.md](evaluation.md),
[recipe-template.md](recipe-template.md)).

## replay key

The lowercase hex SHA-256 of a request's state and questions (`replay_key(state, questions)`).
An offline run looks a request up by its key in the stored responses. A request with no stored
answer is an error (`ReplayMiss`), never an invented answer. Changing the state, a question name,
type, instructions or criteria changes the key. Defined in [backends.md](backends.md#replay-key).

## fixture

The data a recipe ships in its `fixtures/` folder: `inputs.jsonl` (the examples and their splits),
`labels.jsonl` (gold labels) and `responses.json` (stored answers keyed by replay key). A recipe
with a scripted backend has no stored answers. Written for the recipe, small, and validated by
`python -m jev_cookbook.fixtures validate`. Defined in [fixtures.md](fixtures.md).

## provenance

Where a stored answer came from, written on every answer. **`synthetic`**: written for the
recipe, not produced by any model. **`recorded`**: captured from a real API call, together with the
model string the API returned and the date. Nothing is labelled `recorded` that did not come from a
real call. Defined in [fixtures.md](fixtures.md#responses-and-provenance) and
[CONTRIBUTING.md](../CONTRIBUTING.md), section 2.

## run mode

How a notebook run was produced, stated in the run header at the top of the notebook:
**`synthetic`** (offline replay of synthetic fixtures), **`scripted`** (offline, a scripted backend
or a simulator), **`recorded`** (offline replay of recorded fixtures) or **`live`** (calls made
now). Only the last two involve a model. See [offline-and-live.md](offline-and-live.md).
