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
| recall at a budget, mean recall at a budget | no item is relevant (mean: skipped if some query has one; NaN if every query does) |
| `top_k_query_accuracy` | no query has a relevant item |
| selective accuracy | nothing was answered |
| `SelectiveResult.threshold` from `evaluate_outcomes` | always (no single confidence cut-off produced the split) |
| reliability bin means | the bin is empty |
| `fallback_metrics` precision / recall | the fallback was never chosen / no example's gold set was exactly the fallback |

**Macro averages** average over *present* classes (at least one gold or predicted example),
so an unused label does not lower the mean. Within a present class, an undefined precision or
recall counts as 0.0.

**Ties in rankings** are resolved in expectation: tied items share the average gain (nDCG,
recall at a budget) or the fraction of the tied group that fits (top-k, `top_k_query_accuracy`'s
hit probability). Results never depend on input order.

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

**Hand-written mirror probabilities can differ from `noul_confidence` by a few ULPs.** The
formula uses `max(p, 1 - p)`, computed, so it is exactly mirror-symmetric: `noul_confidence([p])`
equals `noul_confidence([1 - p])` when `1 - p` is *computed* from `p`. It is not guaranteed equal
when a fixture instead writes out both halves of a mirror pair as separate decimal literals,
because `1 - p` computed from `p` is not always bit-identical to the literal someone typed for
"the mirror of `p`": the two *inputs* `0.42` and `0.58` look like exact mirrors, but
`1 - 0.42 == 0.5800000000000001` in floating point, one ULP above the literal `0.58`. Feed both
literals to `noul_confidence` and the two *results* differ too — `0.16000000000000014` for `0.42`,
`0.15999999999999992` for `0.58`, eight ULPs apart (`math.ulp(0.16) == 2.7755575615628914e-17`;
the gap between them is `2.220446049250313e-16`) — even though both are meant to express the same
nominal confidence, `0.16`. The gap is not a fixed multiple: feeding `0.07`/`0.93` (nominal `0.86`)
differs by only two ULPs. One input ULP does not land as one result ULP; it is "a few", and which
few depends on the pair. The practical consequence is in `selective_curve` (and anything built on
it, including `outcome_curve` below): its candidate thresholds are `numpy.unique` of the observed
confidences, so two fixture rows hand-written as separate mirror-pair literals can land as two
*adjacent* threshold candidates ("`gate >= 0.86`" printed twice, at a few-ULPs-apart value) instead
of coalescing into one. This is a property of floating-point decimal literals, not a bug in
`noul_confidence` to fix by changing it here, and not one #172's fix, not yet landed, will fix by
rounding confidence itself: an earlier design that rounded every confidence to 12 decimal places
turned out to flip boundary-exact `conf >= threshold` comparisons in ten recipes whose own
helpers compare raw confidences directly (found by CI on that design's own pull request), so
confidence values are never rounded, there or anywhere else. Instead, #172's fix will deduplicate
only the *candidate-threshold grids*. There are two sites that build one from `numpy.unique(conf)`
today: `selective_curve` (which `select_confidence_threshold` calls directly, so it inherits
whatever `selective_curve` does) and `outcome_curve`'s own, separate `np.unique(conf)[::-1]` —
`outcome_curve` never calls `selective_curve`. Both will route through one shared
`_candidate_thresholds` helper, so the fix reaches both rather than leaving `outcome_curve`'s own
grid undeduplicated. Candidates will be grouped by `round(v, 12)`, and the **minimum raw member of
each group** will be kept as the surviving threshold, so every returned threshold stays a
bit-exact observed confidence and every `conf >= threshold` comparison — including a recipe's
own, outside this module — stays exact. Recipes 02, 10 and 15 each already carry exactly this
pair on their `validation` fixtures: a nominal-twin pair such as `0.93`/`0.07` (raw confidences
`0.8600000000000001` and `0.8599999999999999`), both of which round to `0.86` and will group
together; the surviving threshold will be the smaller of the two, `0.8599999999999999`, so both
twins satisfy `conf >= threshold` and will be counted as accepted at that one row — the duplicate
row collapses.

**What collapsing a group changes, and what it does not.** When every member of a group agrees
on `correct` — as 02's, 10's and 15's `0.86` pairs do — collapsing them to the union is collapsing
a genuine duplicate: the group's coverage becomes the higher of the two it replaces, accuracy does
not move, and nothing a recipe's own frozen threshold depends on can shift, because there was only
ever one operating point there. When a group's members *disagree* on `correct`, collapsing them
changes which operating point is on the grid at all, and that can move a selector's answer.
Recipe 06's pooled `validation` array (95 (example, label) pairs) has a nominal-`0.16` group whose
two raw members sit at different accuracies: `0.15999999999999992` gives coverage `0.915789` at
accuracy `0.988506`, `0.16000000000000014` gives coverage `0.905263` at accuracy `1.000000`.
Keeping only the minimum keeps the first row and drops the second, so
`select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)` on that array
would move, from `0.1600` (coverage `0.905263`) today to `0.2000` (coverage `0.894737`) after the
dedup. Recipe 06 itself is unaffected, because it does not ask for `target_accuracy=1.0`: its own
call uses `target_accuracy=0.97`, which both members already satisfy, so the frozen cutoff stays
`0.1200000000000001` (prints `0.1200`) before and after. `evaluate_selective` never builds a grid
of its own, so the dedup never touches it directly — but the frozen threshold it is handed can
still move, exactly when the group that threshold came from disagrees on `correct` this way;
"the same value either way" is true for 02, 10, 15 and recipe 06's own `0.97` call, and is not a
property of the dedup in general. `_conf_inputs` on `main` today does no rounding and no
deduplication of any kind, which is exactly why the duplicate row above is still printed.

Landing the fix will require regenerating three recipes' committed notebook output, not two, all
in the same pull request as the code change. Recipes **10** and **15** carry the colliding `0.86`
pair on `validation` examples their sweep cell prints as text, so the dedup will collapse their
duplicate `gate >= 0.86` row into one (the surviving row keeps the higher-coverage half,
`coverage 0.240`; every other row and the `0.30` frozen-gate threshold are unchanged), and their
committed output will need refreshing to match. Recipe **06**'s pooled `validation` curve also
loses a row (`30` → `29`, dropping the `coverage 0.905263` / accuracy `1.000000` point described
above) even though its own frozen cutoff (`0.1200`) does not move, so it regenerates too, for
honesty about what changed — its committed figure would otherwise still compare equal under CI's
own figure comparison, which is loose by design (`docs/recipe-template.md`: a moved line or marker
still passes; the printed numbers are what actually pins the plotted data), so a green
`Notebook (06-…)` check on the unrounded figure would not be proof that nothing moved. Recipes
**02** and **03** also carry colliding groups in their `validation` fixtures (02's the same `0.86`
pair; 03's a `0.4` pair) but are verified unchanged and need no regeneration: each group there
agrees on `correct`, so 02's three printed derived numbers and 03's frozen threshold (`0.6500`,
used only to gate answers, never itself swept or plotted) are identical before and after. Because
CI's notebook matrix re-executes every recipe notebook once a change touches anything outside
`recipes/` and `README.md`, #172's own pull request will regenerate whichever notebooks its own
grouping actually changes (10, 15 and 06) and ship them alongside the code — a #163-style
regeneration run on `main` ahead of the fix would only reproduce today's output byte for byte.
(CONTRIBUTING.md's scope allowlist binds recipe pull requests only, so a foundation pull request
may carry this `recipes/` output refresh.)

### Multi-label

`multilabel_from_noul(noul_by_label, thresholds)` builds predicted label sets from one Noul per
label per example. `multilabel_metrics(gold, predicted, labels=None)` returns per-label, micro
and macro precision, recall, F1. `exact_set_match(gold, predicted)` is the share of examples
whose set is exactly right (two empty sets match).

**Pooling (example, label) decisions for the three-path pattern.** A multi-label Noul recipe
asks one independent question per label per example (CONTRIBUTING.md section 3), so its three-
path pattern (below) needs every (example, label) decision's correctness and confidence pooled
into one flat pair of arrays before `selective_curve`, `select_confidence_threshold` or
`evaluate_selective` can see them. `pool_label_decisions(example_ids, labels, gold_by_label,
noul_by_label, thresholds)` does that pooling — `thresholds` is one float or `{label: float}`,
exactly as `multilabel_from_noul` takes it — and returns `(correct, confidence, keys)`, where
`keys[j]` is the `(example_id, label)` pair that `correct[j]`/`confidence[j]` describe (pooled
label-then-example, so attribution survives the flattening):

```python
correct, confidence, keys = pool_label_decisions(
    ids, LABELS, gold_by_label, noul_by_label, thresholds
)
curve = selective_curve(correct, confidence)  # one curve over every (example, label) pair
```

`pool_label_outcomes(example_ids, labels, gold_by_label, accepted_by_label, tag_by_label)` is
its companion for the rule's *own* decisions rather than a reapplied confidence gate — see
"Outcomes versus the confidence-only view" below — and returns `(accepted, correct, keys)` ready
to pass straight to `evaluate_outcomes`:

```python
accepted, correct, keys = pool_label_outcomes(
    ids, LABELS, gold_by_label, accepted_by_label, tag_by_label
)
result = evaluate_outcomes(accepted, correct)  # pooled coverage, accuracy, risk
```

### Choice with an acceptable set

Some Choice recipes accept more than one option as correct for an example (gold is a set, not a
single value), or add an explicit fallback option for an example none of the real candidates
fit (CONTRIBUTING.md section 4). `set_agreement(gold_sets, choices)` is the share of choices
inside their example's acceptable set (`mean(choices[i] in gold_sets[i])`); a single-answer gold
is a one-element set, `[gold_id]` or `{gold_id}`, not the bare value, exactly as `exact_set_match`
and `multilabel_metrics` require of their own gold collections.

`fallback_metrics(gold_sets, choices, fallback)` reports the fallback option's own precision,
recall, F1 and support, via the two-class relabelling every recipe that needed this built by
hand: "is this example's gold set exactly `{fallback}`" against "did the raw choice name
`fallback`", read off `per_class_metrics`'s True-class counts. An example whose gold set contains
`fallback` *alongside* a real candidate is not a gold fallback case for this function (it would
still count as an acceptable choice for `set_agreement`): the fallback class here means
"`fallback` was the *only* acceptable answer", not merely "`fallback` was acceptable".

### Score and ranking

| Function | Measures |
| --- | --- |
| `score_level(answer)` | most probable level; ties go to the lowest |
| `exact_agreement(gold, predicted, tolerance=0)` | share within `tolerance` levels, using the modal level |
| `mean_absolute_error(gold, predicted)` | mean `abs(score - gold)`, using the expected score |
| `ndcg(gold_relevance, scores, k=None, gain="linear")`, `mean_ndcg(queries, ...)` | ranking quality, `DCG / IDCG`, discount `1 / log2(i + 1)`; linear or `2^r - 1` gain |
| `top_k_accuracy(gold, probabilities, k)` | gold among the k most probable options (tie-aware) |
| `recall_at_budget(gold_relevant, scores, budget)`, `mean_recall_at_budget(queries, budget)` | relevant found in the top `budget` by score over all relevant; the mean over several queries |
| `top_k_query_accuracy(queries, k=1)` | is any relevant item among the top `k` scored items of a query (a *different* question from `recall_at_budget`, below) |

**`top_k_query_accuracy` is not `recall_at_budget` under another name.** The two differ whenever
a query has more than one relevant item: with two relevant items among three and the top-scored
item one of them, `top_k_query_accuracy(..., k=1)` is `1.0` (the top item *is* relevant) while
`recall_at_budget(..., budget=1)` is `0.5` (a review budget of one item still misses the other
relevant one). They agree exactly when every query has at most one relevant item — then "is the
relevant item in the top k" and "what share of the (one) relevant item was found" are the same
event — which is why a recipe-local `top1_accuracy` helper that computed the mean of
`recall_at_budget(..., budget=1)` passed its own tests on fixtures shaped that way, then gave the
wrong number the day a query got a second relevant item. `top_k_query_accuracy` is `top_k_accuracy`'s
query-ranking sibling, not an overload of it: `top_k_accuracy(gold, probabilities, k)` asks
whether *one* example's gold option is among the `k` most probable options of *its own*
probability distribution; `top_k_query_accuracy(queries, k)` asks, for each of several ranked
lists, whether any gold-relevant item is among the `k` top-scored items of that list. The two
names stay separate because the existing `top_k_accuracy` signature is frozen (its callers
already rely on it); do not confuse the two from the name alone.

### Selective prediction

`selective_curve(correct, confidence)` gives accuracy, risk (`1 - accuracy`) and coverage at
each distinct confidence threshold. `select_confidence_threshold(correct, confidence,
target_accuracy=... | min_coverage=...)` picks the value to freeze. `evaluate_selective(correct,
confidence, threshold)` reports coverage, accuracy, risk. Abstentions are not errors. Every
`confidence` here must lie in `[0, 1]`; all three functions raise `ValueError` otherwise, so a
sentinel (`-1.0`, `2.0`, ...) cannot leak through `select_confidence_threshold` into a threshold
and reach a rule's own `min_confidence` check.

**`select_confidence_threshold` freezes the max-coverage cut that still meets the target, not the
candidate nearest the target.** With `target_accuracy=...`, the value returned is the *lowest*
threshold (so the *highest* coverage) among the distinct observed validation confidences whose
answered subset has accuracy `>= target_accuracy`. On a small validation set the candidates can be
too sparse for loosening the target to buy anything smoothly: recipe 17's validation data reaches
`target_accuracy=1.0` at threshold `0.5600`, but *every* target from `0.95` down to the function's
own floor returns the same `0.0600` — the one wrong validation answer sits at confidence `0.10`,
and the next distinct confidence below the perfect cut is `0.06`, so there is nothing between them
for a looser target to land on. The code runs without error either way; only looking at the
candidate confidences themselves (or at `selective_curve` on the same data) shows why loosening
the target did not move the frozen value until it crossed that gap.

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

**Coverage counts delivered answers, not every decision the rule reaches.** `coverage =
n_answered / n_total` counts only examples where the rule delivered its own answer as the result
for that example. A deferral — an `unknown` or `needs_review` tag, a "manual triage" result,
anything else that asks a person to answer rather than answering itself — fails CONTRIBUTING.md
section 4 part (a) outright ("a complete answer to the question, not a deferral"): a deferral is
always a review outcome, in the `ReviewQueue`, however confidently it was reached, and
`accepted[i]` must be `False` for it. This is not about where the decision ends up recorded: a
complete-answer fallback that is *also* noted in a backlog still counts toward coverage, because
it passes part (a) regardless (recipe 22's `no_match` is logged to a `ReviewQueue` reused as an
unmatched-asset backlog and is still `accepted=True`, see
[docs/glossary.md](glossary.md#coverage)).
What decides `accepted` is whether the rule answered the question it was asked, not which
container received the result. (Orchestrator ruling 4, tracked from #164.)

**Recipe 19 is the case this ruling changes, not one that already complies.** As merged, it
reports `test` coverage with `evaluate_selective(test_correct, test_confidence, threshold)`,
which counts every build whose raw choice clears the confidence gate toward the answered set —
`unknown` included: five of the nineteen `test` builds name `unknown`; three of those five clear
the `0.4400` gate and are queued in the `ReviewQueue` for a person to find the real cause
(`reason: "no option fits"`), and the printed figure, `coverage 0.7895` (15 of 19), counts those
three as answered. `unknown` is a deferral under part (a) — it says "ask a person", not "here is
the cause" — so those three examples' `accepted` must be `False` whatever their confidence;
recomputing with `evaluate_outcomes` and that correction gives `coverage 0.6316` (12 of 19)
instead. Recipe 19's own correction is tracked by the recipe-side sweep (#163, which names this
exact figure — 0.7895 → 0.6316 — among its routed findings), not made here; this paragraph names
the gap between the shipped number and the rule rather than presenting `0.7895` as the compliant
figure.

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

**`outcome_curve(confidences, correct, *, exempt=None)` is the risk–coverage curve for a rule
with an unconditionally-accepted branch.** This is narrower than `evaluate_outcomes`: it models
only the CONTRIBUTING.md section 4 shape, an explicit fallback option (`no_match`, `unclear`,
`no_suitable_rewrite`, ...) the rule accepts *regardless of its confidence*, with every other
example still gated on `confidence >= t` as usual. `exempt` is a boolean mask marking those
fallback examples; at each distinct observed confidence `t` (descending, as in
`selective_curve`), the selected subset is:

```python
exempt | (~exempt & (confidence >= t))
```

An `exempt` example counts at *every* threshold, however low its confidence; every other example
counts only once its confidence clears `t`, exactly as `selective_curve` already computes for it.
Rows have the same shape `selective_curve` returns (`thresholds`, `coverage`, `accuracy`, `risk`),
so `plot_risk_coverage` plots either one unchanged:

```python
curve = outcome_curve(test_confidence, test_correct, exempt=test_exempt)
plot_risk_coverage(curve, label="test")  # same call as for a selective_curve result
```

`exempt=None` (the default) means no exemptions at all: the mask reduces to `confidence >= t` for
every `t`, and `outcome_curve` returns exactly what `selective_curve` would on the same
`confidences`/`correct` — checked directly in `tests/test_evaluation.py`,
`test_outcome_curve_equals_selective_curve_when_exempt_is_none`. **This is the only condition
under which the two curves coincide.** Do not pass a rule's own `accepted` array (what
`evaluate_outcomes` takes) as `exempt`: `accepted` means "was accepted at the gate actually used";
`exempt` means "accepted no matter what gate is swept". Confusing the two — treating "the rule
happened to accept this one" as "this one is exempt from the sweep" — reproduces a capped-coverage
curve that stops rising once `t` falls below whatever gate `accepted` was built from, which is
exactly the bug this function's signature now rules out (see "The curves coincide under a
narrower condition" below for a worked example). Because an `exempt` example is always selected, `accuracy` (and so `risk`) is
never NaN here: every threshold answers at least one example, unlike some other curves in this
module where a threshold can select nothing.

**Which shipped rules can use this, and which cannot.** `exempt` models only an unconditionally
*accepted* branch (CONTRIBUTING.md section 4's exemption). Checked against each recipe's own
committed fixtures:

| recipe | exempt-accept branch | reject-regardless branch | `exempt` suffices? |
| --- | --- | --- | --- |
| 11 | `no_clarification_needed` | membership check, fires on 0 examples | yes |
| 13 | `no_suitable_rewrite` | membership check, fires on 0 examples | yes |
| 14 | `not_stated` (×7) | membership check, fires on 0 examples | yes — but see the next paragraph for its 2 `no_candidates` short-circuits |
| 16 | none (every category gated) | none | yes, `exempt=None` |
| 18 | `no_match` (×12) | membership check, fires on 0 examples | yes |
| 19 | — | the model choosing `unknown` outright (×3 on `test`, ×2 on `validation`) | **no** |
| 21 | — | the model choosing `needs_review` outright (×3); 22 of 38 scored examples are also settled with no model call at all | **no** |
| 22 | `no_match` (×5) | membership check, fires on 0 examples | yes — but see the next paragraph for its 4 `no_candidate_resolution` short-circuits |
| 23 | agreed `insufficient_evidence` (×8) | `judge_pair`'s "orders disagree" branch (×9) | **no** |

For 11, 13, 14, 18 and 22, the single mask is exact *because* each rule's defensive membership
check never actually fires on its committed fixtures — not because `exempt` can express a
membership check in general; a future fixture that does trip one would need its own accounting.
Recipes **19**, **21** and **23** unconditionally *reject* some examples regardless of confidence
(the model naming `unknown` outright in 19 — a deferral under CONTRIBUTING.md section 4 part (a),
"Coverage counts delivered answers" above — `needs_review` outright in 21; `judge_pair`'s
disagreement check in 23, which runs before any confidence is read) — there is no single
`exempt`-shaped argument for "always sent to review no matter how confident", so none of the
three recipes' curves is expressible here yet. Recipe 21 is one of the three recipes whose review
asked for this function in the first place; it still cannot use it.

**Examples with no confidence to report.** `confidences` is required for every example passed in,
`exempt` included, and every value is validated to `[0, 1]` — but some examples never go through a
question at all. Recipe 14 short-circuits 2 of its 41 scored documents through `no_candidates`
(accepted as `not_stated`, no question built, so no `Noul`/`Choice` answer exists to read a
confidence from); recipe 22 short-circuits 4 of its 40 through `no_candidate_resolution` the same
way. Do not invent a placeholder confidence (`0.0` or otherwise) for such an example to keep its
row in the arrays: leave it out of `confidences`/`correct`/`exempt` entirely —
`outcome_curve` sweeps the *answered* examples only — and report it separately with its own
`evaluate_outcomes`-style accounting (it is still accepted, unconditionally, for that purpose). A
placeholder is not inert even though the example would stay exempt either way: `thresholds` is
`numpy.unique` of every confidence passed in, so one placeholder value adds a row to that grid and
moves the curve's x-axis, despite never changing which examples the mask selects. This is not a
blanket ban on ever showing a stand-in number. `docs/recipe-template.md`'s "a sentinel is not the
same thing as a disclosed stand-in" rule (and #164 ruling 9) allows a disclosed, in-range,
quantified one, but only where it cannot reach a function that derives threshold candidates from
the array — `select_confidence_threshold`, `selective_curve` and `outcome_curve`, the
answered-examples-only rule just above. `evaluate_selective` is not one of those three: it
reapplies an already-frozen threshold rather than deriving one, so a disclosed stand-in for an
example that never had a confidence to report may be handed to it. Recipe 14 is the shipped case:
`t17` never reaches a question (no candidate span), so `confidence_only = [1.0 if a is None else
a.confidence for a in test_answers]` stands in `1.0`, the top of the scale, specifically so that
it reads as a sure thing and matches what `select_span` itself did with `t17` (accepted): the
stand-in is never the reason anything is excluded from `evaluate_selective`'s gate. The opposite
choice, `0.0`, would instead make the counterfactual abstain on an example the rule actually
answered — deciding the outcome rather than standing in for a missing input, the sentinel
behaviour this rule forbids. Disclosure alone is
not enough: the notebook also quantifies what the stand-in costs, printing the gated view's
coverage over all 21 test documents (9 of them, `0.4286`) beside the narrower, 20-document
denominator a confidence gate could actually have applied to — the documents really asked a
question (8 of them, `0.4000`) — the same "disclose and quantify against the narrower
denominator" requirement `docs/recipe-template.md` states.

**Print both Ns when a recipe short-circuits examples.** `outcome_curve`'s own denominator at
every threshold is `len(confidences)` — the answered subset actually passed in — never the
recipe's whole scored split, because a short-circuited example was never in `confidences` to
begin with: no question was built for it, so there is no `Noul`/`Choice` answer to read a
confidence from, whatever its `accepted` value turns out to be. `evaluate_outcomes`'s
denominator, by contrast, is `len(accepted)`: the whole split, short-circuited examples included.
A short-circuited example's own `accepted` entry follows CONTRIBUTING.md section 4 like any other:
`not_stated` is a complete answer, not a deferral (section 4 part (a) names it explicitly), so
recipe 14's `no_candidates` short-circuit is `accepted=True` — present in `evaluate_outcomes`'s
count of answered examples, absent from `confidences` only because it never produced a confidence
to report, not because it is treated as unanswered. A recipe that short-circuits some examples
and reports both views must print both Ns next to their coverage figures, not just one of them:
on recipe 14's `test` split (21 documents, one of which `no_candidates` answers before any
question is built) an `outcome_curve` over the 20 documents that reach `select_span` reports
coverage as a fraction of 20, while `evaluate_outcomes(test_accepted, test_correct)` over the
same split — the short-circuited document counted as accepted — reports coverage as a fraction of
21. Both denominators are correct for what each function computes; a reader shown one coverage
number from each without both Ns printed beside them would be comparing two fractions over two
different totals without any way to tell.

### Outcomes versus the confidence-only view

This toolkit reports a rule two ways, and a recipe whose review branch is more than a confidence
gate needs to know which one it is reading:

* **The confidence-only view** (`selective_curve`, `select_confidence_threshold`,
  `evaluate_selective`) answers "what would a pure confidence gate do here", by reapplying
  `confidence >= threshold` itself. It never calls the rule.
* **The outcomes view** (`evaluate_outcomes`, `outcome_curve`) answers "what did the rule itself
  do": `evaluate_outcomes` from `accepted`/`correct` as the rule actually returned them;
  `outcome_curve` from `correct` and an `exempt` mask naming the rule's own unconditionally-
  accepted examples (CONTRIBUTING.md section 4), with every other example still gated on
  confidence.

**When the single numbers coincide.** If the rule's only review branch *is* the confidence gate —
nothing else can send an example to review, and nothing lets one through regardless of confidence
— `evaluate_outcomes` and `evaluate_selective` agree on every field but `threshold`
(`evaluate_outcomes`'s `SelectiveResult.threshold` is NaN; the confidence-only function reports
the frozen float). This is the case
`test_evaluate_outcomes_matches_evaluate_selective_for_a_confidence_only_rule` checks directly,
and it is also why a recipe built exactly that way can report either number: for a multi-label
Noul rule, `pool_label_decisions` fed to `evaluate_selective` and `pool_label_outcomes` fed to
`evaluate_outcomes` give the same pooled coverage, accuracy and risk.

**The curves coincide under a narrower condition: `exempt` empty or `None`, not merely "no second
branch".** `outcome_curve(confidences, correct, exempt=None)` equals `selective_curve(correct,
confidences)` exactly, by construction — `exempt=None` is unconditionally no exemptions, so this
holds for *any* rule, confidence-only or not, as long as `exempt` is actually left empty. The
trap is passing something else there by mistake. Recipe 06 (`pool_label_decisions`/
`pool_label_outcomes`) is a genuinely confidence-only rule: one global `uncertain` gate (`0.1200`)
is its only review branch, no fallback label. Its own `accepted` array (what `pool_label_outcomes`
builds, and what `evaluate_outcomes` correctly takes) is `confidence >= 0.1200` — a *fixed*
snapshot of that one gate. Reusing that array as `outcome_curve`'s `exempt` argument (instead of
leaving `exempt=None`, which is what a confidence-only rule actually calls for) does not produce
recipe 06's curve: on its validation split, sweeping `t` down from `1.0` with `exempt` fixed to
`confidence >= 0.12` caps coverage at `0.9368` — the share already fixed-gated in — where
`selective_curve` on the same data rises to `1.0000` as `t` falls below every observed confidence.
The fixed array was never "accepted no matter what `t` is swept"; it was "accepted at the one gate
already applied", and feeding it in as `exempt` silently reintroduces exactly the fixed-mask bug
this function's signature exists to rule out. The correct call for recipe 06 is simply
`outcome_curve(confidence, correct)`, no `exempt` at all — which, being confidence-only, then
agrees with `selective_curve` exactly.

**When they differ.** As soon as the rule has a second, unconditional branch — an explicit
fallback option such as `no_match` or `unclear` that is never confidence-checked (CONTRIBUTING.md
section 4), a membership check, or any other branch that does not depend on `min_confidence` —
the two views can disagree about which examples were "answered", and only the outcomes view
describes what actually happened. The confidence-only view, applied to such a rule, is not merely
less informative: it can be the more flattering number, because it has no way to notice a mistake
the rule's design lets through unchecked (an example below the confidence gate that the rule
nonetheless answered through its other branch, or vice versa).

**Showing the counterfactual for an exempted option.** CONTRIBUTING.md section 4's exemption is a
three-part test, not a side-effect check alone — see section 4 for the full wording, summarised
here: (a) the option is a complete answer to the question, not a deferral; (b) choosing it
records no action in the `ActionLog` (a printed, explicitly-labelled "noted, no action" backlog
entry is allowed; an actual action, however named, is not); (c) being wrong leaves nothing
standing beyond the missed item itself, measured against having sent it to review instead. All
three must pass before an option may be delivered at any confidence with no further gate. A
permissive option that is a real, confident category — recipe 16's `allowed`, say, as opposed to
a `no_match`/`unclear`-shaped one — does not pass this test even though choosing it has no side
effect of its own in the sense of touching anything outside the simulation: `allowed` resolves to
`ignore`, itself logged to the `ActionLog`, which fails (b); and a message that is really
violating, wrongly let through as `allowed`, stays live with nobody warned at all — something
standing beyond the missed item itself, which fails (c) — exactly the "exposure left open" part
(c) itself names, and exactly the failure mode an explicit review outcome exists to catch. Recipe
16 gates `allowed` like every other category for this reason. A recipe that does legitimately
exempt an option passing all three parts should still show the reader what gating it too would
have cost or bought, as a reported counterfactual, not a silent
choice: build a second `accepted` that routes the exempted option through the same confidence
check as everything else, and report both `evaluate_outcomes` results side by side (or, for the
curve, two `outcome_curve` calls on the same `confidences`/`correct`: the real one with `exempt`
set, the counterfactual with `exempt=None`), so "we chose to exempt this option" and "here is
what gating it would have looked like" are both on the page. (A recipe that decided *not* to
exempt a qualifying option at all, gating it like everything else, needs none of this: its own
`evaluate_outcomes` and `evaluate_selective` already agree, exactly as in "when the single numbers
coincide" above.)

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

Two caveats before freezing `c` on a real recipe. **First, and the one to hold onto hardest:
`|2p - 1|` is distance from 0.5, not margin at `t`.** It measures certainty about yes-versus-no,
not distance from the business threshold, so when `t != 0.5` an item sitting just either side of
`t` can still read as high-confidence, and the item the gate is least sure about need not be the
one closest to `t`. This matters most exactly where it is easiest to miss: a **per-label
threshold** set near 1.0 (a label the business rule only wants to apply when the model is very
sure). A noul of `0.88` against a threshold of `0.90` is a business-rule near-miss — the tag
flips to "no" for a reason as small as `0.02` — but its confidence is `|2(0.88) - 1| = 0.76`,
read as *fairly* confident, because `0.88` is still far from `0.5`. The gate is **structurally
blind** to this shape of error: it was never given `t`, only the raw probability, so no choice of
`c` can make it specifically distrust "just below a high threshold" rather than "close to 0.5".
A multi-label Noul recipe with several per-label thresholds (`pool_label_decisions`'s
`thresholds` argument, above) should expect this blind spot once per label with a high threshold,
not once for the whole rule. Second, look at `selective_curve(val_correct,
noul_confidence(val_noul))` before freezing `c`: if accuracy does not fall as coverage rises,
confidence is not separating right from wrong on this data and the gate buys nothing — on some
fixtures every wrong answer happens to be a confident one, in which case no `c` routes anything
useful to review, even though the code runs without error. (The same curve on the test split,
`selective_curve(test_correct, test_conf)`, is fine to look at *after* `c` is frozen, as a
reported result rather than as an input to the choice of `c`.) (The confidence page's own "three
paths for using confidence in your code" are three confidence *bands*; this pattern's three paths
are a cookbook convention, not that one.)

For a multi-label recipe whose only review branch *is* this confidence gate (no fallback label,
no membership check), the pooled confidence-only view and the pooled outcomes view give the same
numbers, for the reason "Outcomes versus the confidence-only view" gives generally: `correct` and
`confidence` from `pool_label_decisions` fed to `evaluate_selective` agree with `accepted` and
`correct` from `pool_label_outcomes` fed to `evaluate_outcomes`, on every field but `threshold`.

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
| `ClassificationCounts` | `tp`, `fp`, `fn`, `precision`, `recall`, `f1`, plus `support` and `present` (what `per_class_metrics` returns for each class, and what `fallback_metrics` returns for the fallback class) |
| `ThresholdPoint` | `threshold`, `tp`, `fp`, `fn`, `tn`, `precision`, `recall`, `f1`; `threshold_sweep` returns `list[ThresholdPoint]` |
| `SelectiveCurve` | `thresholds`, `coverage`, `accuracy`, `risk` (equal-length numpy arrays, one entry per threshold); returned by both `selective_curve` and `outcome_curve` |
| `SelectiveResult` | `threshold`, `n_total`, `n_answered`, `coverage`, `accuracy`, `risk`; returned by both `evaluate_selective` and `evaluate_outcomes` (`threshold` is NaN from the latter) |
| `ReliabilityBin` | `lower`, `upper`, `count`, `mean_probability`, `observed_rate` (the last two are NaN for an empty bin); `reliability_table` returns `list[ReliabilityBin]` |
| `BootstrapResult` | `difference`, `lower`, `upper`, `confidence_level`, `n`, `n_resamples`, `seed` |
| `UsageTotals` | `requests`, `input_tokens`, `output_tokens`, `total_tokens`, `requests_missing_input`, `requests_missing_output` |

Every metric computed on synthetic fixtures is a check that the pipeline works, not a measure
of Jev; `CONTRIBUTING.md` requires the notebook to say so next to the number.

The toolkit is tested against the real `jev_cookbook.answers` classes (read-only
`MappingProxyType` mappings, `int` Score keys, `Usage` and `DecisionResult.usage`) in
`tests/test_evaluation_answers.py`.
