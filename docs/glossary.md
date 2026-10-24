# Glossary

The words this cookbook uses, in the order a reader meets them. Statements about Jev link to a page
in the README [sources table](../README.md#sources) (S01 to S12); the root of those pages is the
TypeSafe documentation index, <https://docs.typesafe.ai/llms.txt>. Words that belong to this
cookbook and not to Jev link to the page in this repository that defines them. Nothing here says
how well Jev performs, how fast it is, or what it costs.

| Term | Where it comes from |
| --- | --- |
| [state](#state), [image asset](#image-asset), [question](#question), [Choice](#choice), [Noul](#noul), [Score](#score), [Box](#box), [criteria](#criteria), [probabilities](#probabilities), [confidence](#confidence) | Jev, as documented by TypeSafe, with local asset and answer handling in this cookbook |
| [gold label](#gold-label) | This cookbook's fixtures |
| [business threshold](#business-threshold), [confidence gate](#confidence-gate) | TypeSafe's guidance, and this cookbook's rule for choosing them |
| [review](#review) | This cookbook |
| [accuracy](#accuracy), [precision](#precision), [recall](#recall), [F1](#f1), [support](#support) | This cookbook, `jev_cookbook.evaluation` |
| [intersection-over-union](#intersection-over-union) | This cookbook, `jev_cookbook.vision` |
| [coverage](#coverage), [risk](#risk), [selective prediction](#selective-prediction) | This cookbook, `jev_cookbook.evaluation` |
| [replay key](#replay-key), [fixture](#fixture), [provenance](#provenance), [run mode](#run-mode) | This cookbook |

Each term is defined the first time a recipe's own prose uses it, and that first use links here. The template demonstrates this for the one lexicon term it uses in prose ([gold label](#gold-label), in its "Evaluation" section); a recipe that uses more of the lexicon links each on its own first use.

## state

What Jev is asked about: the text, JSON object or array of strings you supply with a request,
such as a customer review or a record with several parts. String values can contain image
references; a JSON object can hold an ordered sequence of frame records
([S09](https://docs.typesafe.ai/images)). Jev judges a state; it does not write text
([S01](https://docs.typesafe.ai/introduction)). In a recipe, Python builds the state, and
identifiers the judgment does not need stay out of it
([template README](../recipes/_template/README.md#what-it-teaches)).

## image asset

A PNG or JPEG supplied separately from the text of a request. The `assets` mapping associates
each reference string with a descriptor containing its type, format and base64-encoded data.
That reference must appear inside a string value in the state, instructions or criteria. Object
keys, question identifiers and option names stay text and do not count as uses of an asset
([S09](https://docs.typesafe.ai/images), [backends.md](backends.md#images-and-box)).

The local [vision helpers](vision.md#image-assets-and-reproducible-references) validate image
bytes, build descriptors in memory and derive stable references from the image bytes. Recipes
keep image files in `assets/` beside their JSON fixtures. Ordered frames are extracted still
images with explicit timestamps; the helpers do not decode a video
([vision.md](vision.md#explicitly-timestamped-still-frames)).

## question

One typed, narrow thing to ask about a state, defined by its type (`Choice`, `Noul`, `Score` or
`Box`), its `instructions` and any criteria that type accepts. `Box` has no criteria. Several
independent questions go in one request and are evaluated independently; a question that depends
on an earlier answer goes in a later request ([S02](https://docs.typesafe.ai/primitives)). The
cookbook's rule is one specific thing per question, with the answers combined in Python
([S01](https://docs.typesafe.ai/introduction),
[CONTRIBUTING.md](../CONTRIBUTING.md), section 3). The classes are in
[backends.md](backends.md#questions).

## Choice

The question type that selects one option from a list you supply. The answer holds `choice`, the
selected option, `probabilities` for every option, and a `confidence`
([S02](https://docs.typesafe.ai/primitives)). The cookbook adds explicit `none`, `other`,
`no_match` or `uncertain` options wherever the task needs them
([CONTRIBUTING.md](../CONTRIBUTING.md), section 3). A `Choice` needs at least two options: with
one, Jev has nothing to weigh, so building the question raises `ValueError`. When a recipe's own
candidate-gathering step leaves only one option (or none), the decision belongs to Python, not to
a request — a forced answer is resolved directly in code, before any question is built and before
any call is spent ([backends.md](backends.md#single-option-choice)).

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

## Box

The question type that locates one target rectangle in an image. A `Box` answer has exactly four
edges: `top`, `bottom`, `left` and `right`, expressed as finite values in `[0, 1]` with the origin
at the image's top left. The rectangle must have positive area: `left < right` and
`top < bottom`. It is one rectangle, not a mask or a collection of objects
([S10](https://docs.typesafe.ai/primitives/box),
[vision.md](vision.md#rectangle-coordinates)).

The answer's `confidence` is the supplied number in `[0, 1]`, or `None` when missing. There is no
probability distribution from which to recompute it
([backends.md](backends.md#images-and-box)). A rectangle alone does not establish that the target
exists. A recipe asks a separate presence question and combines the answers in Python. Unknown
presence or missing required confidence goes to [review](#review); review is not an absence
prediction. [Intersection-over-union](#intersection-over-union) measures the geometry separately
from that presence decision.

## criteria

What you tell Jev about the answer space. For a `Choice`, the options, each with an optional
description. For a `Score`, the levels of the rubric, in order
([S02](https://docs.typesafe.ai/primitives)). A `Noul` may carry an optional description of its
outcomes ([backends.md](backends.md#questions)). Python
builds option lists and rubrics, and carries them through to the output unchanged
([CONTRIBUTING.md](../CONTRIBUTING.md), section 3). In this repository the shapes are in
[backends.md](backends.md#questions).

Image references can appear in instruction or criterion string values, for example to supply
visual examples for fixed `Choice` options. Option names remain Python's labels. `Box` accepts
instructions but no criteria ([backends.md](backends.md#images-and-box)).

## probabilities

The distribution an answer carries across your options (`Choice`) or levels (`Score`). Its shape
is what the answer says about certainty: concentrated on one outcome, or spread out
([S03](https://docs.typesafe.ai/confidence)). A `Noul` carries a single probability instead of a
distribution. A `Box` carries rectangle edges and optional confidence, not a distribution.

## confidence

A single number from 0 to 1 that summarizes the shape of a `Choice` or `Score` distribution: 1 when
all the probability is on one outcome, 0 when it is spread evenly. A `Noul` has none (see the
Noul bullet below). Because the answer's `probabilities` are included, you can recompute it, and
the cookbook checks stored answers against these formulas.

- **Choice**, with `n` options and `p_max` the probability of the selected option:
  `(p_max - 1/n) / (1 - 1/n)`. Only the top probability counts. It is not the raw top
  probability.
- **Score**, with levels numbered 0 to n-1: one minus the probability-weighted average distance (in
  levels) from the most likely level, divided by the same average for an even spread (measured from
  the middle level), and floored at 0. Probability on a neighbouring level lowers it less than the
  same probability on a distant level. The exact formula, with a worked example, is on the
  [confidence page](https://docs.typesafe.ai/confidence) (S03).
- **Noul** has no `confidence` field, but the [confidence page](https://docs.typesafe.ai/confidence)
  (S03) defines one for it anyway, as the Choice formula above applied to a yes-or-no Choice
  (`n = 2`, `p_max = max(p, 1 - p)`), which reduces to `|2p - 1|` for a Noul's probability `p`:
  0 at `p = 0.5`, 1 at `p = 0` or `p = 1`. It is on the *same* 0-1 scale as Choice confidence, not
  a separate convention. [evaluation.md](evaluation.md) provides this as `noul_confidence(noul)`.
- **Box** carries the supplied confidence or `None` when it is missing. There is no distribution
  to recompute and geometry is not a substitute for confidence. Missing confidence cannot pass
  a required numeric gate, even one set to zero
  ([backends.md](backends.md#images-and-box), [vision.md](vision.md#rectangle-coordinates)).

## gold label

The correct answer for an example, written by whoever built the fixtures, never by Jev, and used
only to score an answer after the fact: it is never part of the state Jev sees. Stored in a
recipe's `fixtures/labels.jsonl`, one per scored example; the `demo` examples carry none
([fixtures.md](fixtures.md#labels)). [accuracy](#accuracy) and every other metric in
`jev_cookbook.evaluation` compare an answer against its gold label.

## business threshold

A cut-off in your own code that turns a model's judgment into a business decision, for example
"the ticket is urgent when `score >= 1.5`" or "the statement holds when `noul >= 0.6`". TypeSafe's
guidance is that a threshold is not one number and scales with the cost of being wrong
([S03](https://docs.typesafe.ai/confidence)). In this cookbook a business threshold belongs to
the task, so a recipe chooses it from labelled `validation` examples with
`jev_cookbook.evaluation.select_threshold`, freezes it, and reports with `evaluate_threshold` on
`test` ([evaluation.md](evaluation.md), [recipe-template.md](recipe-template.md)). It answers
"what does the model's judgment mean for the business", which is a separate question from "how
much do we trust this particular answer" — that second question is the
[confidence gate](#confidence-gate).

## confidence gate

A second, independent cut-off, applied to an answer's own [confidence](#confidence) (or
`noul_confidence` for a `Noul`), that decides whether to trust an answer enough to act on it
automatically or send it to [review](#review) instead. Chosen from `validation` with
`jev_cookbook.evaluation.select_confidence_threshold`, and reported on `test` with
`evaluate_selective` (when the rule's only review branch is this gate) or `evaluate_outcomes`
(every other rule) ([evaluation.md](evaluation.md), [recipe-template.md](recipe-template.md)). A
rule that also needs a [business threshold](#business-threshold) — for example, a `Noul`'s three
outcomes, yes, no, or review — chooses the two independently, both on `validation`
([evaluation.md](evaluation.md), "Noul three-path pattern"). `jev_cookbook.evaluation`'s
selective-prediction functions reject a confidence outside `[0, 1]`, so a sentinel value cannot be
chosen as a gate ([CONTRIBUTING.md](../CONTRIBUTING.md), section 4).

For `Box`, check for missing confidence before applying a numeric gate. A missing value takes
the review path and is not a numeric sample for threshold selection.

## review

The outcome a recipe gives an answer it does not act on automatically: an unconfident or
inconsistent result below a [confidence gate](#confidence-gate), or a deferral — an outcome that
asks a person to decide the same question again (`unknown` routed for someone to pick the real
answer, `needs_review`) — whatever its confidence. By convention the outcome value itself is the
string `"review"` (not, say, `"human_review"`; a recipe may still name its own domain-specific
sub-reasons), and the reason string for a confidence-gated review is exactly `"confidence below
the threshold"`, so two recipes' readers see the same words for the same cause. Simulated with
`jev_cookbook.simulation.ReviewQueue`; a recipe that simulates no queue still names the outcome in
its own rule's result type. A fallback option that is itself a complete answer — not a deferral —
may be delivered as a final result with no gate instead, but only when it passes every part of
the test [CONTRIBUTING.md](../CONTRIBUTING.md) section 4 states (worked through in
[recipe-template.md](recipe-template.md)); a deferral never qualifies, whatever its confidence,
and always counts toward review, not toward [coverage](#coverage).

## accuracy

The fraction of scored examples whose answer exactly matches its [gold label](#gold-label): for a
`Choice`, `choice == gold`; for a rule's own outcome, whatever the rule treats as a match.
Computed by `accuracy(gold, predicted)` in `jev_cookbook.evaluation`
([evaluation.md](evaluation.md)). Accuracy on `validation` is a selection step, not a reported
result: it is exactly how `select_threshold` chooses a [business threshold](#business-threshold)
and `select_confidence_threshold` chooses a [confidence gate](#confidence-gate) (`target_accuracy`
and `min_coverage` are both accuracy-based), so a `validation` accuracy prints under the selection
label alongside any other `validation` number. Accuracy on `test`, with every setting already
frozen, is the reported result, and is never itself used to choose anything.

## intersection-over-union

The area shared by two rectangles divided by the area covered by either rectangle, usually
abbreviated **IoU**. It is 0 for disjoint rectangles and 1 for identical ones. The local vision
helpers compute it in continuous normalized coordinates, before rounding to pixels
([vision.md](vision.md#presence-confidence-and-evaluation)).

In the cookbook's localization metrics, a missed present target contributes 0 IoU. Absent gold
targets are excluded from mean IoU and predicted boxes on those targets are counted separately
as false positives. Mean IoU is undefined (`NaN`) when no gold target is present. Report review
outcomes separately so abstentions and absent targets cannot disappear into a geometry score.

## precision

Of the examples a rule predicted belong to a class, the fraction that actually do:
`TP / (TP + FP)`. Undefined (`NaN`, never `0.0`) when the class was never predicted. Computed per
class by `per_class_metrics`, and swept across thresholds for a `Noul` by `evaluate_threshold` /
`threshold_sweep`, in `jev_cookbook.evaluation` ([evaluation.md](evaluation.md)).

## recall

Of the examples whose [gold label](#gold-label) is a class, the fraction a rule actually predicted
as that class: `TP / (TP + FN)`. Undefined (`NaN`, never `0.0`) when the class has no gold
examples. Computed by the same functions as [precision](#precision).

## F1

The harmonic mean of [precision](#precision) and [recall](#recall), `2 TP / (2 TP + FP + FN)`: one
number that falls when either does. Undefined (`NaN`, never `0.0`) when the class appears in
neither the gold labels nor the predictions. Computed by the same functions as precision and
recall.

## support

The number of scored examples whose [gold label](#gold-label) is a given class — the denominator
[recall](#recall) is computed against. Reported alongside precision, recall and F1 by
`per_class_metrics` in `jev_cookbook.evaluation` ([evaluation.md](evaluation.md)).

## coverage

The fraction of scored examples a rule actually answered itself, rather than sending to
[review](#review): `n_answered / n_total`. A deferral — an outcome that asks a person to decide
the same question again — counts toward review, not coverage, whatever its confidence. A
complete-answer fallback that passes the test in [CONTRIBUTING.md](../CONTRIBUTING.md) section 4
counts toward coverage like any other answered example, even when it is also noted in a backlog
for an unrelated follow-up: the rule already answered the question that was asked, and a note
about something else is not a review of that answer. Computed by `evaluate_selective` (a
confidence-only rule) or `evaluate_outcomes` (any rule with an unconditional review branch) in
`jev_cookbook.evaluation` ([evaluation.md](evaluation.md), "Selective prediction").

## risk

The error rate among the examples a rule answered itself: `1 - accuracy` restricted to the
answered subset, never computed over examples sent to [review](#review). Reported alongside
[coverage](#coverage) by the same functions, and swept across confidence gates by
`selective_curve` ([evaluation.md](evaluation.md)).

## selective prediction

The pattern of answering automatically only when an answer clears a
[confidence gate](#confidence-gate) and sending everything else to [review](#review), trading
[coverage](#coverage) for lower [risk](#risk). `jev_cookbook.evaluation`'s `selective_curve`,
`select_confidence_threshold`, `evaluate_selective` and `evaluate_outcomes` implement it
([evaluation.md](evaluation.md)); abstaining (sending to review) is never scored as an error.

## replay key

The lowercase hex SHA-256 of a request's state, questions and optional image-asset identity
(`replay_key(state, questions, assets=assets)`).
An offline run looks a request up by its key in the stored responses. A request with no stored
answer is an error (`ReplayMiss`), never an invented answer. Changing the state, a question name,
type, instructions or criteria changes the key. For images, the identity includes each
reference, its type and format, and a digest of its encoded data. Changing an image or its
reference changes the key; reordering the asset mapping does not. Omitting assets or passing an
empty mapping preserves the text-only key. Defined in [backends.md](backends.md#replay-key) and
[Images and Box](backends.md#images-and-box).

## fixture

The data a recipe ships in its `fixtures/` folder: `inputs.jsonl` (the examples and their splits),
`labels.jsonl` (gold labels) and `responses.json` (stored answers keyed by replay key). A recipe
with a scripted backend has no stored answers. Written for the recipe, small, and validated by
`python -m jev_cookbook.fixtures validate`. Defined in [fixtures.md](fixtures.md).

Visual recipes keep image files in the sibling `assets/` folder, with relative paths and frame
timestamps in the input records' `fields`. Gold labels remain separate from model inputs.
Base64 descriptors are built in memory, not committed inside response fixtures
([vision.md](vision.md#image-assets-and-reproducible-references)).

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
