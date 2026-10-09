# Evaluation toolkit

`jev_cookbook.evaluation` holds every metric a recipe reports. It is plain `numpy`, imports
nothing from the answer classes or the SDK, and is one module (`src/jev_cookbook/evaluation.py`).

```python
from jev_cookbook.evaluation import accuracy, select_threshold, evaluate_threshold
```

## Rules that hold everywhere

**Inputs.** `gold` is plain values. `predicted` (and the other system outputs) may be plain
values or typed answers, recognised by attribute: Choice has `choice`, `probabilities`,
`confidence`; Score has `score`, `probabilities`, `confidence`, `legend`; Noul has `noul`.

**Empty input raises `ValueError`**, for every public function, and so do unequal lengths,
out-of-range probabilities and invalid settings. No metric returns a number for no data.

**Undefined is NaN, never 0.0.** A ratio with a zero denominator returns `float("nan")`
(test with `math.isnan`). Each docstring says exactly when. The cases:

| Quantity | NaN when |
| --- | --- |
| class precision | the class was never predicted (`TP + FP == 0`) |
| class recall | the class has no gold examples (`TP + FN == 0`) |
| class F1 | the class is in neither gold nor predictions |
| micro precision / recall / F1 | its pooled denominator is zero |
| Cohen's kappa | chance agreement is 1 (a single option throughout) |
| nDCG | no item has positive gain |
| recall at a budget | no item is relevant |
| selective accuracy | nothing was answered |
| `SelectiveResult.threshold` from `evaluate_outcomes` | always (no single confidence cut-off produced the split) |
| reliability bin means | the bin is empty |

**Macro averages** average over *present* classes (at least one gold or predicted example),
so an unused label does not lower the mean. Within a present class, an undefined precision or
recall counts as 0.0.

**Ties in rankings** are resolved in expectation: tied items share the average gain (nDCG,
recall at a budget) or the fraction of the tied group that fits (top-k). Results never depend
on input order.

**Randomness** takes a required `seed` and uses `numpy.random.default_rng(seed)`.

**Choose on validation, report on test.** Selectors (`select_threshold`,
`select_confidence_threshold`) return a plain float. Evaluators (`evaluate_threshold`,
`evaluate_selective`) take that float. Never call a selector on the data you report.

```python
t = select_threshold(val_gold, val_noul, "f1")  # validation split
result = evaluate_threshold(test_gold, test_noul, t)  # test split, t frozen
```

## What the answer values hold

(From the TypeSafe documentation.) A Noul's `noul` is the probability, 0 to 1, that the
statement is true, and a Noul has **no `confidence`**. A Choice's `probabilities` map each
option to its probability and sum to 1. A Score's `score` is the expected level (it can fall
between levels) and `legend` maps levels to descriptions. The SDK types Score `probabilities`
(and `legend`) with `int` keys; the JSON on the wire has string keys. The toolkit accepts both.

`confidence` is **not** the top probability. For Choice it is the top probability rescaled,
`(p_max - 1/n) / (1 - 1/n)`: 0 at a uniform spread, 1 at a single peak. For Score it is
`max(0, 1 - sum_i p_i |i - m| / MAD_unif)`, a distance-based spread measure that depends on the
distance between levels (`m` is the most probable level), so `{0: .5, 2: .5}` and
`{0: .5, 1: .5}` have the same top probability and different confidence. For calibration use
`top_probabilities`, not `.confidence`.

## Functions

### Choice

| Function | Measures |
| --- | --- |
| `accuracy(gold, predicted)` | fraction of exact matches |
| `confusion_matrix(gold, predicted, labels=None)` | counts by (gold, predicted); returns `ConfusionMatrix(labels, matrix)` |
| `per_class_metrics(gold, predicted, labels=None)` | one-versus-rest precision, recall, F1, with `tp`, `fp`, `fn`, `support` |
| `macro_average(...)`, `micro_average(...)` | unweighted mean over present classes; pooled counts |
| `cohens_kappa(gold, predicted)` | agreement beyond chance, `(p_o - p_e) / (1 - p_e)` |

`F1 = 2 TP / (2 TP + FP + FN)`. Leaving a catch-all class (`none`) out of `labels` gives
micro and macro averages over the remaining classes.

### Noul

| Function | Measures |
| --- | --- |
| `evaluate_threshold(gold, noul, threshold)` | precision, recall, F1 and counts of "yes when `noul >= threshold`" |
| `threshold_sweep(gold, noul, thresholds=None)` | the above at each distinct observed value, ascending |
| `select_threshold(gold, noul, objective="f1", target=None)` | the threshold to freeze: `f1`, `recall_at_precision`, `precision_at_recall`; ties go to the higher threshold |
| `brier_score(gold, noul)` | mean squared error of the yes probability |
| `noul_confidence(noul)` | `\|2p - 1\|`, usable as the `confidence` argument of selective prediction (not an API value) |

`noul_confidence` is the Choice confidence formula above, `(p_max - 1/n) / (1 - 1/n)`, applied to
a yes-or-no Choice (`n = 2`, `p_max = max(p, 1 - p)`); that reduces to `|2p - 1|`. It is therefore
on the *same* 0-1 scale as Choice (and Score) confidence, not a separate convention — the
[confidence page](https://docs.typesafe.ai/confidence) (S03) states this explicitly. A recipe
that gates both Noul and Choice answers with one confidence threshold can use `noul_confidence`
and `.confidence` interchangeably.

### Multi-label

`multilabel_from_noul(noul_by_label, thresholds)` builds predicted label sets from one Noul per
label per example. `multilabel_metrics(gold, predicted, labels=None)` returns per-label, micro
and macro precision, recall, F1. `exact_set_match(gold, predicted)` is the share of examples
whose set is exactly right (two empty sets match).

### Score and ranking

| Function | Measures |
| --- | --- |
| `score_level(answer)` | most probable level; ties go to the lowest |
| `exact_agreement(gold, predicted, tolerance=0)` | share within `tolerance` levels, using the modal level |
| `mean_absolute_error(gold, predicted)` | mean `abs(score - gold)`, using the expected score |
| `ndcg(gold_relevance, scores, k=None, gain="linear")`, `mean_ndcg(queries, ...)` | ranking quality, `DCG / IDCG`, discount `1 / log2(i + 1)`; linear or `2^r - 1` gain |
| `top_k_accuracy(gold, probabilities, k)` | gold among the k most probable options (tie-aware) |
| `recall_at_budget(gold_relevant, scores, budget)` | relevant found in the top `budget` by score over all relevant |

### Selective prediction

`selective_curve(correct, confidence)` gives accuracy, risk (`1 - accuracy`) and coverage at
each distinct confidence threshold. `select_confidence_threshold(correct, confidence,
target_accuracy=... | min_coverage=...)` picks the value to freeze. `evaluate_selective(correct,
confidence, threshold)` reports coverage, accuracy, risk. Abstentions are not errors. Every
`confidence` here must lie in `[0, 1]`; all three functions raise `ValueError` otherwise, so a
sentinel (`-1.0`, `2.0`, ...) cannot leak through `select_confidence_threshold` into a threshold
and reach a rule's own `min_confidence` check.

**A rule whose review branch is more than a confidence gate needs `evaluate_outcomes`, not a
sentinel.** `evaluate_selective` reapplies `confidence >= threshold` itself; it never calls the
rule. That is exactly right when the rule's only review branch *is* that gate — nothing else can
send an example to review — and wrong otherwise. A rule with an unconditional second branch (an
explicit fallback option such as `no_match` or `unclear` that is never confidence-checked, a
check that the chosen option is really a member of some set, or any other branch that does not
depend on `min_confidence`) can disagree with `evaluate_selective` about which examples were
answered. Recipes have reached for a sentinel confidence to paper over this: hand the rejected
examples a confidence of `0.0` (or, worse, `-1.0`) so `evaluate_selective` reproduces the rule's
split by construction. This is fragile two ways. First, it is one-directional: a change to the
rule's own confidence comparison does not change what the sentinel-fed call reports, so the two
accounts can silently drift apart (seen in review on #148). Second, an out-of-range sentinel
(`-1.0`) can be selected as "the threshold" by `select_confidence_threshold` itself whenever the
target accuracy admits every answer, and that candidate then fails the rule's own `[0, 1]`
validation when frozen and reused (#155) — which is exactly why confidence is now validated here.

`evaluate_outcomes(accepted, correct)` reports coverage, accuracy and risk from the rule's own
decisions instead: `accepted[i]` is whether the rule answered example `i` (not a confidence, not
a reconstruction — what the rule actually returned), `correct[i]` is whether an answered
example's answer was right (pass anything you like, conventionally `False`, for an example where
`accepted[i]` is `False`: it is required but never read). It returns the same `SelectiveResult`
as `evaluate_selective`, with `threshold` NaN (no single confidence cut-off decided `accepted`,
so a threshold is undefined here, not merely unreported — the module's general NaN convention,
above).

**Note the argument order.** Every other function in this family leads with `correct`
(`selective_curve(correct, confidence)`, `select_confidence_threshold(correct, confidence, ...)`,
`evaluate_selective(correct, confidence, threshold)`); `evaluate_outcomes(accepted, correct)`
puts `accepted` first. This is deliberate, not an inconsistency to fix: it mirrors this
function's own definition of `accepted` as the thing decided first (whether the rule answered at
all) and `correct` as conditional on it (whether the answer was right, which only matters once
something was answered) — the same order the dataclass's own fields read in
(`n_answered`/`coverage` before `accuracy`/`risk`). Both arguments are same-length boolean lists,
so swapping them raises nothing and silently returns a different, still-plausible number; read
the parameter names at the call site rather than relying on position alone.

For a rule whose only review branch *is* a confidence gate, the two agree, which is checked
directly (not merely argued) in `tests/test_evaluation.py`,
`test_evaluate_outcomes_matches_evaluate_selective_for_a_confidence_only_rule`:

```python
accepted = [c >= threshold for c in confidence]
a, b = evaluate_outcomes(accepted, correct), evaluate_selective(correct, confidence, threshold)
(a.n_total, a.n_answered, a.coverage, a.accuracy, a.risk) == (
    b.n_total,
    b.n_answered,
    b.coverage,
    b.accuracy,
    b.risk,
)
# True; only `threshold` differs: NaN from evaluate_outcomes, the frozen float from
# evaluate_selective. (`a == b` on the two SelectiveResult objects directly is False: `==` on a
# frozen dataclass compares every field, including threshold, and NaN != NaN.)
```

Use `evaluate_outcomes` as soon as the rule has a second, unconditional branch (a fallback
option, a membership check): build `accepted` from what the rule returned on each split, and
never invent a confidence for the examples it rejects outright.

### Noul three-path pattern

A Noul-gated decision often needs three outcomes, not two: answer yes, answer no, or send the
item to a person because the model is not confident enough to trust either answer. No helper
selects the business threshold and the confidence gate together; compose them from
`threshold_sweep` (via `select_threshold`), `evaluate_threshold` and the selective-prediction
pair (`select_confidence_threshold`, `evaluate_selective`). Both cut-offs are chosen on
validation and only then applied to test, exactly as in "Choose on validation, report on test"
above: recompute the confidence and correctness arrays on the test split rather than reusing the
validation arrays the gate was chosen from (`val_noul`, `test_noul`: plain probabilities, not
Noul answer objects — extract `.noul` first if you have answers, e.g.
`val_noul = [a.noul for a in val_answers]`):

```python
t = select_threshold(val_gold, val_noul, "f1")  # validation: business cut-off
val_correct = [(v >= t) == bool(g) for v, g in zip(val_noul, val_gold, strict=True)]
c = select_confidence_threshold(val_correct, noul_confidence(val_noul), target_accuracy=0.95)

test_conf = noul_confidence(test_noul)  # test: both cut-offs frozen
test_correct = [(v >= t) == bool(g) for v, g in zip(test_noul, test_gold, strict=True)]
result = evaluate_selective(test_correct, test_conf, c)  # result.coverage: share auto-answered
```

On test data: auto-answer `noul >= t` whenever `noul_confidence(noul) >= c` (`result.accuracy` is
the accuracy of those auto-answers; `result.coverage` is the share of examples auto-answered, not
an action); route everything else to review. `evaluate_threshold(gold, noul, t)` separately
reports precision and recall of the business rule alone, with no confidence gate, and
`threshold_sweep` is what `select_threshold` sweeps to choose `t`.

Two caveats before freezing `c` on a real recipe. First, `|2p - 1|` is distance from 0.5, not
margin at `t`: it measures certainty about yes-versus-no, not distance from the business
threshold, so when `t != 0.5` an item sitting just either side of `t` can still read as
high-confidence, and the item the gate is least sure about need not be the one closest to `t`.
Second, look at `selective_curve(val_correct, noul_confidence(val_noul))` before freezing `c`: if
accuracy does not fall as coverage rises, confidence is not separating right from wrong on this
data and the gate buys nothing — on some fixtures every wrong answer happens to be a confident
one, in which case no `c` routes anything useful to review, even though the code runs without
error. (The same curve on the test split, `selective_curve(test_correct, test_conf)`, is fine to
look at *after* `c` is frozen, as a reported result rather than as an input to the choice of `c`.)
(The confidence page's own "three paths for using confidence in your code" are three confidence
*bands*; this pattern's three paths are a cookbook convention, not that one.)

### Calibration

`reliability_table(probability, outcome, n_bins=10)` bins stated probability in equal widths
`(lower, upper]` (0 in the first bin) and reports count, mean probability, observed rate.
`expected_calibration_error(...)` is the count-weighted mean absolute gap; it depends on
`n_bins`. For Noul pass `noul` and the gold truth; for Choice or Score pass
`top_probabilities(answers)` and whether the pick was right.

### Comparison

`paired_bootstrap_difference(a, b, *, seed, n_resamples=10_000, confidence_level=0.95)`
resamples the per-example differences `a - b` and returns the mean difference with a
percentile interval as `BootstrapResult`. Examples must be aligned.

### Accounting

`sum_usage(usages)` sums per-request `usage` values, `Usage` objects or mappings (`input_tokens`, `output_tokens`, each
possibly `None` or absent) into `UsageTotals`. Requests that did not report a count are tallied
in `requests_missing_input` / `requests_missing_output`, so a partial total is visible.

## Result types

Every result type is a frozen dataclass whose fields are plain attributes, so other modules
(for example the notebook helpers) can accept them by duck typing.

| Type | Fields |
| --- | --- |
| `ConfusionMatrix` | `labels` (list), `matrix` (numpy integer array, `matrix[i, j]` = gold `labels[i]`, predicted `labels[j]`) |
| `ClassificationCounts` | `tp`, `fp`, `fn`, `precision`, `recall`, `f1`, plus `support` and `present` (what `per_class_metrics` returns for each class) |
| `ThresholdPoint` | `threshold`, `tp`, `fp`, `fn`, `tn`, `precision`, `recall`, `f1`; `threshold_sweep` returns `list[ThresholdPoint]` |
| `SelectiveCurve` | `thresholds`, `coverage`, `accuracy`, `risk` (equal-length numpy arrays, one entry per threshold) |
| `SelectiveResult` | `threshold`, `n_total`, `n_answered`, `coverage`, `accuracy`, `risk`; returned by both `evaluate_selective` and `evaluate_outcomes` (`threshold` is NaN from the latter) |
| `ReliabilityBin` | `lower`, `upper`, `count`, `mean_probability`, `observed_rate` (the last two are NaN for an empty bin); `reliability_table` returns `list[ReliabilityBin]` |
| `BootstrapResult` | `difference`, `lower`, `upper`, `confidence_level`, `n`, `n_resamples`, `seed` |
| `UsageTotals` | `requests`, `input_tokens`, `output_tokens`, `total_tokens`, `requests_missing_input`, `requests_missing_output` |

Every metric computed on synthetic fixtures is a check that the pipeline works, not a measure
of Jev; `CONTRIBUTING.md` requires the notebook to say so next to the number.

The toolkit is tested against the real `jev_cookbook.answers` classes (read-only
`MappingProxyType` mappings, `int` Score keys, `Usage` and `DecisionResult.usage`) in
`tests/test_evaluation_answers.py`.
