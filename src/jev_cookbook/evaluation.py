"""Evaluation toolkit: metrics every recipe reports through, in plain numpy.

Conventions that hold for every public function (see also ``docs/evaluation.md``):

* **Empty input raises.** Any function given an empty sequence raises ``ValueError``.
  Sequences that must be the same length (gold and predictions, for example) raise
  ``ValueError`` when they are not.
* **Undefined quantities are NaN, and each docstring says when.** A ratio whose
  denominator is zero (the precision of a class that was never predicted, the recall of
  a class with no gold examples, a kappa with no disagreement to correct for) is returned
  as ``float("nan")``, never as 0.0. Check with ``math.isnan``.
* **Ties in rankings are broken in expectation.** When items share a score, the metric is
  the average over every order of the tied items, so the result does not depend on input
  order and no tie is silently resolved in the system's favour.
* **Typed answers or plain values.** Every ``predicted`` argument accepts typed answer
  objects (anything with the attributes of :class:`ChoiceLike`, :class:`ScoreLike` or
  :class:`NoulLike`) or plain values, and ``gold`` accepts plain values. Answers are
  recognised by attribute, so this module imports nothing from the answer classes.
* **Choose on validation, report on test.** Every threshold selector returns a plain
  ``float``; the matching evaluator takes that float as an argument. Select on the
  validation split, then pass the returned value, unchanged, to the evaluator on the
  test split.
* **Randomness takes an explicit seed** and uses ``numpy.random.default_rng(seed)``.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np

__all__ = [
    "BootstrapResult",
    "ChoiceLike",
    "ClassificationCounts",
    "ConfusionMatrix",
    "NoulLike",
    "ReliabilityBin",
    "ScoreLike",
    "SelectiveCurve",
    "SelectiveResult",
    "ThresholdPoint",
    "UsageTotals",
    "accuracy",
    "brier_score",
    "cohens_kappa",
    "confusion_matrix",
    "exact_agreement",
    "exact_set_match",
    "expected_calibration_error",
    "evaluate_outcomes",
    "evaluate_selective",
    "evaluate_threshold",
    "macro_average",
    "mean_absolute_error",
    "mean_ndcg",
    "micro_average",
    "multilabel_from_noul",
    "multilabel_metrics",
    "ndcg",
    "noul_confidence",
    "paired_bootstrap_difference",
    "per_class_metrics",
    "recall_at_budget",
    "reliability_table",
    "score_level",
    "select_confidence_threshold",
    "select_threshold",
    "selective_curve",
    "sum_usage",
    "threshold_sweep",
    "top_k_accuracy",
    "top_probabilities",
]


# --------------------------------------------------------------------------- answer shapes


@runtime_checkable
class ChoiceLike(Protocol):
    """A Choice answer: the chosen option, a probability per option, and a confidence."""

    choice: Any
    probabilities: Mapping[Any, float]
    confidence: float


@runtime_checkable
class ScoreLike(Protocol):
    """A Score answer: expected score, a probability per level, confidence, and legend."""

    score: float
    probabilities: Mapping[Any, float]
    confidence: float
    legend: Mapping[Any, Any]


@runtime_checkable
class NoulLike(Protocol):
    """A Noul answer: the probability, from 0 to 1, that the statement is true."""

    noul: float


# --------------------------------------------------------------------------- validation


def _require_nonempty(values: Sequence[Any] | np.ndarray, name: str) -> None:
    if len(values) == 0:
        raise ValueError(f"{name} is empty; a metric over no examples is undefined")


def _same_length(a: Sequence[Any], b: Sequence[Any], names: str) -> None:
    if len(a) != len(b):
        raise ValueError(f"{names} must have the same length, got {len(a)} and {len(b)}")


def _as_list(values: Iterable[Any], name: str) -> list[Any]:
    out = list(values)
    _require_nonempty(out, name)
    return out


def _choice_value(x: Any, function: str) -> Any:
    if hasattr(x, "choice"):
        return x.choice
    if hasattr(x, "noul"):
        raise ValueError(
            f"{function} compares Choice options; a Noul answer is a probability, "
            "so use evaluate_threshold or threshold_sweep with the gold booleans"
        )
    if hasattr(x, "score"):
        raise ValueError(
            f"{function} compares Choice options; a Score answer is a level, "
            "so use score_level with exact_agreement, or mean_absolute_error"
        )
    return x


def _noul_value(x: Any) -> Any:
    return x.noul if hasattr(x, "noul") else x


def _floats(values: Iterable[Any], name: str, unit_interval: bool = False) -> np.ndarray:
    arr = np.asarray([float(v) for v in values], dtype=float)
    _require_nonempty(arr, name)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains NaN or infinite values")
    if unit_interval and (arr.min() < 0.0 or arr.max() > 1.0):
        raise ValueError(f"{name} must lie in [0, 1]")
    return arr


def _noul_array(values: Iterable[Any], name: str) -> np.ndarray:
    return _floats((_noul_value(v) for v in values), name, unit_interval=True)


def _binary(values: Iterable[Any], name: str) -> np.ndarray:
    arr = _floats(values, name)
    if not np.all((arr == 0.0) | (arr == 1.0)):
        raise ValueError(f"{name} must be booleans or 0/1")
    return arr.astype(bool)


def _default_labels(*seqs: Sequence[Any]) -> list[Any]:
    seen: list[Any] = []
    for seq in seqs:
        for v in seq:
            if v not in seen:
                seen.append(v)
    try:
        return sorted(seen)
    except TypeError:
        return seen


def _safe_div(num: float, den: float) -> float:
    return num / den if den > 0 else float("nan")


def _choice_pair(
    gold: Iterable[Any], predicted: Iterable[Any], function: str
) -> tuple[list[Any], list[Any]]:
    g = [_choice_value(x, function) for x in _as_list(gold, "gold")]
    p = [_choice_value(x, function) for x in _as_list(predicted, "predicted")]
    _same_length(g, p, "gold and predicted")
    return g, p


# --------------------------------------------------------------------------- Choice


def accuracy(gold: Iterable[Any], predicted: Iterable[Any]) -> float:
    """Fraction of examples whose predicted option equals the gold option.

    ``accuracy = (number of i with predicted[i] == gold[i]) / n``.

    Args:
        gold: Gold options (plain values).
        predicted: Predicted options, as plain values or Choice answers (``.choice`` is used).

    Returns:
        A float in [0, 1]. Raises ``ValueError`` on empty input or unequal lengths.
    """
    g, p = _choice_pair(gold, predicted, "accuracy")
    return sum(a == b for a, b in zip(g, p, strict=True)) / len(g)


@dataclass(frozen=True)
class ConfusionMatrix:
    """Counts of examples by (gold, predicted). ``matrix[i, j]`` is the number of examples
    whose gold option is ``labels[i]`` and whose predicted option is ``labels[j]``."""

    labels: list[Any]
    matrix: np.ndarray


def confusion_matrix(
    gold: Iterable[Any], predicted: Iterable[Any], labels: Sequence[Hashable] | None = None
) -> ConfusionMatrix:
    """Count how often each gold option was predicted as each option.

    Rows are gold, columns are predicted, in the order of ``labels``.

    Args:
        gold: Gold options.
        predicted: Predicted options (plain values or Choice answers).
        labels: Row and column order. Default: every option seen in gold or predicted,
            sorted when sortable, otherwise in first-seen order. When given, every gold
            and predicted value must be in it, otherwise ``ValueError``.

    Returns:
        A :class:`ConfusionMatrix` with an integer ``(len(labels), len(labels))`` matrix.
        Empty input or unequal lengths raise ``ValueError``.
    """
    g, p = _choice_pair(gold, predicted, "confusion_matrix")
    labs = list(labels) if labels is not None else _default_labels(g, p)
    index = {lab: i for i, lab in enumerate(labs)}
    if len(index) != len(labs):
        raise ValueError("labels contains duplicates")
    mat = np.zeros((len(labs), len(labs)), dtype=int)
    for a, b in zip(g, p, strict=True):
        if a not in index or b not in index:
            raise ValueError(f"value {a!r} or {b!r} is not in labels {labs!r}")
        mat[index[a], index[b]] += 1
    return ConfusionMatrix(labs, mat)


@dataclass(frozen=True)
class ClassificationCounts:
    """Precision, recall, F1 and counts for one class (or one label).

    ``precision`` is NaN when ``tp + fp == 0`` (never predicted); ``recall`` is NaN when
    ``tp + fn == 0`` (no gold support); ``f1`` is NaN only when ``tp + fp + fn == 0``
    (the class occurs in neither gold nor predictions).
    """

    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float

    @property
    def support(self) -> int:
        """Number of gold examples of the class (``tp + fn``)."""
        return self.tp + self.fn

    @property
    def present(self) -> bool:
        """True when the class occurs in gold or predictions."""
        return self.tp + self.fp + self.fn > 0


def _counts(tp: int, fp: int, fn: int) -> ClassificationCounts:
    return ClassificationCounts(
        tp,
        fp,
        fn,
        precision=_safe_div(tp, tp + fp),
        recall=_safe_div(tp, tp + fn),
        f1=_safe_div(2 * tp, 2 * tp + fp + fn),
    )


def per_class_metrics(
    gold: Iterable[Any], predicted: Iterable[Any], labels: Sequence[Hashable] | None = None
) -> dict[Any, ClassificationCounts]:
    """Precision, recall and F1 of each class, treating it as one-versus-rest.

    For class c: ``precision = TP / (TP + FP)``, ``recall = TP / (TP + FN)`` and
    ``F1 = 2 TP / (2 TP + FP + FN)`` (the harmonic mean of the two), where TP counts
    examples with gold c and predicted c, FP gold other and predicted c, FN gold c and
    predicted other.

    Args:
        gold: Gold options.
        predicted: Predicted options (plain values or Choice answers).
        labels: Classes to report, in order. Default: every option seen in gold or
            predicted. Gold or predicted values outside ``labels`` are allowed here (they
            count as "other"), so a catch-all such as ``"none"`` can be left out.

    Returns:
        ``{label: ClassificationCounts}`` in the order of ``labels``. See
        :class:`ClassificationCounts` for exactly when each ratio is NaN. Empty input or
        unequal lengths raise ``ValueError``.
    """
    return _per_class(gold, predicted, labels, "per_class_metrics")


def _per_class(
    gold: Iterable[Any],
    predicted: Iterable[Any],
    labels: Sequence[Hashable] | None,
    function: str,
) -> dict[Any, ClassificationCounts]:
    g, p = _choice_pair(gold, predicted, function)
    labs = list(labels) if labels is not None else _default_labels(g, p)
    out: dict[Any, ClassificationCounts] = {}
    for lab in labs:
        tp = sum(a == lab and b == lab for a, b in zip(g, p, strict=True))
        fp = sum(a != lab and b == lab for a, b in zip(g, p, strict=True))
        fn = sum(a == lab and b != lab for a, b in zip(g, p, strict=True))
        out[lab] = _counts(tp, fp, fn)
    return out


def macro_average(
    gold: Iterable[Any], predicted: Iterable[Any], labels: Sequence[Hashable] | None = None
) -> dict[str, float]:
    """Unweighted mean of per-class precision, recall and F1, so every class counts equally.

    Averages over the *present* classes only: those with at least one gold or predicted
    example among ``labels``. Classes that occur in neither are skipped, so an unused
    label does not drag the mean down. Within a present class, an undefined precision
    (never predicted) or undefined recall (no gold support) counts as 0.0; F1 is always
    defined for a present class.

    Args:
        gold, predicted, labels: As in :func:`per_class_metrics`.

    Returns:
        ``{"precision": ..., "recall": ..., "f1": ...}``, each in [0, 1]. Raises
        ``ValueError`` on empty input, unequal lengths, or when no class in ``labels``
        is present.
    """
    stats = [c for c in _per_class(gold, predicted, labels, "macro_average").values() if c.present]
    if not stats:
        raise ValueError("no class in labels occurs in gold or predicted")

    def mean(vals: Iterable[float]) -> float:
        v = [0.0 if math.isnan(x) else x for x in vals]
        return sum(v) / len(v)

    return {
        "precision": mean(c.precision for c in stats),
        "recall": mean(c.recall for c in stats),
        "f1": mean(c.f1 for c in stats),
    }


def micro_average(
    gold: Iterable[Any], predicted: Iterable[Any], labels: Sequence[Hashable] | None = None
) -> dict[str, float]:
    """Precision, recall and F1 computed from counts pooled over classes.

    ``precision = sum TP / sum (TP + FP)``, ``recall = sum TP / sum (TP + FN)``,
    ``F1 = 2 sum TP / (2 sum TP + sum FP + sum FN)``. With every option in ``labels``
    and exactly one prediction per example, all three equal :func:`accuracy`. Leaving a
    catch-all class out of ``labels`` gives the micro average over the remaining classes.

    Args:
        gold, predicted, labels: As in :func:`per_class_metrics`.

    Returns:
        ``{"precision", "recall", "f1"}``. A value is NaN when its denominator is zero
        (nothing predicted among ``labels`` for precision; no gold among ``labels`` for
        recall; neither for F1). Empty input or unequal lengths raise ``ValueError``.
    """
    stats = _per_class(gold, predicted, labels, "micro_average").values()
    tp = sum(c.tp for c in stats)
    fp = sum(c.fp for c in stats)
    fn = sum(c.fn for c in stats)
    pooled = _counts(tp, fp, fn)
    return {"precision": pooled.precision, "recall": pooled.recall, "f1": pooled.f1}


def cohens_kappa(gold: Iterable[Any], predicted: Iterable[Any]) -> float:
    """Agreement between gold and predicted options beyond what chance agreement would give.

    ``kappa = (p_o - p_e) / (1 - p_e)``, where ``p_o`` is the observed agreement
    (:func:`accuracy`) and ``p_e = sum over options of (share of gold) * (share of
    predicted)`` is the agreement expected if the two were independent with the same
    marginal frequencies. It is 1 for perfect agreement, 0 at chance level, and negative
    below chance.

    Args:
        gold: Gold options.
        predicted: Predicted options (plain values or Choice answers).

    Returns:
        A float. NaN when ``p_e == 1`` (gold and predicted both use a single, identical
        option throughout), because there is no disagreement to correct for. Empty input
        or unequal lengths raise ``ValueError``.
    """
    g, p = _choice_pair(gold, predicted, "cohens_kappa")
    n = len(g)
    po = sum(a == b for a, b in zip(g, p, strict=True)) / n
    pe = sum((g.count(lab) / n) * (p.count(lab) / n) for lab in set(g) | set(p))
    if math.isclose(pe, 1.0):
        return float("nan")
    return (po - pe) / (1.0 - pe)


# --------------------------------------------------------------------------- Noul


@dataclass(frozen=True)
class ThresholdPoint:
    """Outcome of predicting yes when ``noul >= threshold``.

    ``precision`` is NaN when nothing is predicted yes; ``recall`` is NaN when there are
    no gold yes examples; ``f1`` is NaN only when there is no predicted and no gold yes.
    """

    threshold: float
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float
    recall: float
    f1: float


def _noul_inputs(gold: Iterable[Any], noul: Iterable[Any]) -> tuple[np.ndarray, np.ndarray]:
    y = _binary(_as_list(gold, "gold"), "gold")
    s = _noul_array(_as_list(noul, "noul"), "noul")
    _same_length(y, s, "gold and noul")
    return y, s


def _point(y: np.ndarray, s: np.ndarray, threshold: float) -> ThresholdPoint:
    pred = s >= threshold
    tp = int(np.sum(pred & y))
    fp = int(np.sum(pred & ~y))
    fn = int(np.sum(~pred & y))
    tn = int(np.sum(~pred & ~y))
    c = _counts(tp, fp, fn)
    return ThresholdPoint(float(threshold), tp, fp, fn, tn, c.precision, c.recall, c.f1)


def evaluate_threshold(
    gold: Iterable[Any], noul: Iterable[Any], threshold: float
) -> ThresholdPoint:
    """Precision, recall and F1 of the rule "answer yes when ``noul >= threshold``".

    ``precision = TP / (TP + FP)``, ``recall = TP / (TP + FN)``, ``F1 = 2 TP / (2 TP +
    FP + FN)``, with yes as the positive class. ``threshold`` is an argument, not
    something this function chooses: pick it with :func:`select_threshold` on a
    validation split and pass that value here for the test split.

    Args:
        gold: Gold truth values (bool or 0/1).
        noul: Noul answers or plain probabilities in [0, 1].
        threshold: Cut-off in [0, 1]; a noul exactly equal to it counts as yes.

    Returns:
        A :class:`ThresholdPoint` (NaN rules in its docstring). Empty input, unequal
        lengths, values outside [0, 1] or a non-boolean gold raise ``ValueError``.
    """
    if not 0.0 <= float(threshold) <= 1.0:
        raise ValueError("threshold must lie in [0, 1]")
    y, s = _noul_inputs(gold, noul)
    return _point(y, s, float(threshold))


def threshold_sweep(
    gold: Iterable[Any], noul: Iterable[Any], thresholds: Sequence[float] | None = None
) -> list[ThresholdPoint]:
    """Precision and recall at each of a set of thresholds, in ascending threshold order.

    Each entry is :func:`evaluate_threshold` at one threshold, so recall never rises and
    the number predicted yes never rises as the threshold rises.

    Args:
        gold: Gold truth values (bool or 0/1).
        noul: Noul answers or plain probabilities in [0, 1].
        thresholds: Cut-offs to evaluate. Default: every distinct observed noul value,
            ascending (these are the only thresholds at which the predictions change).

    Returns:
        A list of :class:`ThresholdPoint`. Same errors as :func:`evaluate_threshold`;
        an explicitly passed empty ``thresholds`` also raises ``ValueError``.
    """
    y, s = _noul_inputs(gold, noul)
    if thresholds is None:
        ts = [float(t) for t in np.unique(s)]
    else:
        ts = sorted(float(t) for t in thresholds)
        _require_nonempty(ts, "thresholds")
        if ts[0] < 0.0 or ts[-1] > 1.0:
            raise ValueError("thresholds must lie in [0, 1]")
    return [_point(y, s, t) for t in ts]


def select_threshold(
    gold: Iterable[Any],
    noul: Iterable[Any],
    objective: str = "f1",
    target: float | None = None,
) -> float:
    """Choose a noul threshold on a validation split; returns the value to freeze.

    Candidates are the distinct observed noul values. Objectives:

    * ``"f1"``: the threshold with the highest F1.
    * ``"recall_at_precision"``: the highest recall among thresholds with precision
      ``>= target``.
    * ``"precision_at_recall"``: the highest precision among thresholds with recall
      ``>= target``.

    Ties are broken toward the *higher* threshold (the more conservative yes). Candidates
    whose metric is undefined (NaN) are never chosen.

    Call this on validation data only; report with :func:`evaluate_threshold` on test
    data, passing the returned value unchanged.

    Args:
        gold: Gold truth values (bool or 0/1).
        noul: Noul answers or plain probabilities in [0, 1].
        objective: One of the names above.
        target: Required for the two constrained objectives, in [0, 1].

    Returns:
        The chosen threshold as a float. Raises ``ValueError`` on empty input, an
        unknown objective, a missing or invalid target, or when no threshold satisfies
        the constraint.
    """
    if objective not in ("f1", "recall_at_precision", "precision_at_recall"):
        raise ValueError(f"unknown objective {objective!r}")
    if objective != "f1" and (target is None or not 0.0 <= target <= 1.0):
        raise ValueError(f"objective {objective!r} needs a target in [0, 1]")
    best: tuple[float, float] | None = None  # (metric value, threshold)
    for pt in threshold_sweep(gold, noul):
        if objective == "f1":
            value, ok = pt.f1, True
        elif objective == "recall_at_precision":
            value, ok = pt.recall, pt.precision >= target  # type: ignore[operator]
        else:
            value, ok = pt.precision, pt.recall >= target  # type: ignore[operator]
        # NaN comparisons are False, so undefined candidates drop out via ``ok``/``value``.
        if ok and not math.isnan(value) and (best is None or value >= best[0]):
            best = (value, pt.threshold)
    if best is None:
        raise ValueError("no threshold satisfies the objective on this data")
    return best[1]


def brier_score(gold: Iterable[Any], noul: Iterable[Any]) -> float:
    """Mean squared difference between the predicted yes-probability and the 0/1 outcome.

    ``brier = mean((noul[i] - y[i])^2)`` with ``y[i]`` 1 for gold yes and 0 for gold no.
    Lower is better; 0 is perfect and 0.25 is what always answering 0.5 gives.

    Args:
        gold: Gold truth values (bool or 0/1).
        noul: Noul answers or plain probabilities in [0, 1].

    Returns:
        A float in [0, 1]. Empty input, unequal lengths or out-of-range values raise
        ``ValueError``.
    """
    y, s = _noul_inputs(gold, noul)
    return float(np.mean((s - y.astype(float)) ** 2))


def noul_confidence(noul: Iterable[Any]) -> list[float]:
    """Confidence of each Noul answer: ``2 * max(p, 1 - p) - 1`` (equal to ``|2p - 1|``).

    A Noul answer has no ``confidence`` field. Per the TypeSafe confidence page
    (https://docs.typesafe.ai/confidence, S03), a Noul's confidence is the Choice
    confidence formula, ``(p_max - 1/n) / (1 - 1/n)``, applied to a yes-or-no Choice:
    with ``n = 2`` and ``p_max = max(p, 1 - p)`` that formula is ``2 * p_max - 1``,
    mathematically ``|2p - 1|``. The ``max`` form is used rather than ``abs(2p - 1)``
    because it is exactly mirror-symmetric in floating point (``f(p) == f(1 - p)``) and
    bit-for-bit equal to :func:`jev_cookbook.answers.choice_confidence` ``([p, 1 - p])``,
    which ``abs(2p - 1)`` is not (it differs from its mirror by up to 1 ULP). It therefore
    sits on the *same* 0-1 scale as Choice (and Score) confidence: 0 at ``p = 0.5``
    (uniform), 1 at ``p = 0`` or ``p = 1``. Use the result as the ``confidence`` argument
    of the selective-prediction functions, together with correctness of the thresholded
    answer.

    Args:
        noul: Noul answers or plain probabilities in [0, 1].

    Returns:
        A list of floats in [0, 1]. Empty, out-of-range, NaN or infinite input raises
        ``ValueError``.
    """
    return [float(2.0 * max(v, 1.0 - v) - 1.0) for v in _noul_array(_as_list(noul, "noul"), "noul")]


# --------------------------------------------------------------------------- Multi-label


def _label_sets(items: Iterable[Any], name: str) -> list[frozenset[Any]]:
    out = []
    for it in _as_list(items, name):
        if isinstance(it, (str, bytes)) or not isinstance(it, Iterable):
            raise ValueError(f"{name} items must be collections of labels, got {it!r}")
        out.append(frozenset(it))
    return out


def multilabel_from_noul(
    noul_by_label: Mapping[Hashable, Sequence[Any]], thresholds: Mapping[Hashable, float] | float
) -> list[frozenset[Any]]:
    """Turn one Noul answer per label per example into a predicted label set per example.

    Example ``i`` gets label ``l`` when ``noul_by_label[l][i] >= thresholds[l]``.

    Args:
        noul_by_label: ``{label: noul answers or probabilities}``, equal lengths.
        thresholds: One float for all labels, or ``{label: float}`` (frozen values chosen
            on validation, e.g. with :func:`select_threshold`).

    Returns:
        A list of ``frozenset`` of labels, one per example. Empty input, unequal lengths,
        out-of-range values or a missing threshold raise ``ValueError``.
    """
    _require_nonempty(list(noul_by_label), "noul_by_label")
    arrays = {lab: _noul_array(vals, f"noul for {lab!r}") for lab, vals in noul_by_label.items()}
    lengths = {len(a) for a in arrays.values()}
    if len(lengths) != 1:
        raise ValueError("every label needs the same number of examples")
    n = lengths.pop()
    sets: list[set[Any]] = [set() for _ in range(n)]
    for lab, arr in arrays.items():
        if isinstance(thresholds, Mapping):
            if lab not in thresholds:
                raise ValueError(f"no threshold for label {lab!r}")
            t = float(thresholds[lab])
        else:
            t = float(thresholds)
        for i in np.nonzero(arr >= t)[0]:
            sets[int(i)].add(lab)
    return [frozenset(s) for s in sets]


def multilabel_metrics(
    gold: Iterable[Any], predicted: Iterable[Any], labels: Sequence[Hashable] | None = None
) -> dict[str, Any]:
    """Per-label, micro and macro precision, recall and F1 for label-set predictions.

    Each label is its own one-versus-rest problem with the definitions of
    :func:`per_class_metrics`; ``micro`` pools the counts over labels and ``macro``
    averages over the *present* labels exactly as :func:`macro_average` does.

    Args:
        gold: Per example, a collection of gold labels (empty collections are allowed).
        predicted: Per example, a collection of predicted labels.
        labels: Labels to score. Default: every label seen in gold or predicted. Labels
            outside it are ignored.

    Returns:
        ``{"per_label": {label: ClassificationCounts}, "micro": {...}, "macro": {...}}``
        where micro and macro are ``{"precision", "recall", "f1"}`` dicts. Micro values
        are NaN when their denominators are zero. Raises ``ValueError`` on empty input,
        unequal lengths, or when no label is present.
    """
    g = _label_sets(gold, "gold")
    p = _label_sets(predicted, "predicted")
    _same_length(g, p, "gold and predicted")
    if labels is None:
        labs = _default_labels(*[sorted(s, key=repr) for s in g + p])
    else:
        labs = list(labels)
    per: dict[Any, ClassificationCounts] = {}
    for lab in labs:
        tp = sum(lab in a and lab in b for a, b in zip(g, p, strict=True))
        fp = sum(lab not in a and lab in b for a, b in zip(g, p, strict=True))
        fn = sum(lab in a and lab not in b for a, b in zip(g, p, strict=True))
        per[lab] = _counts(tp, fp, fn)
    present = [c for c in per.values() if c.present]
    if not present:
        raise ValueError("no label occurs in gold or predicted")
    pooled = _counts(
        sum(c.tp for c in per.values()),
        sum(c.fp for c in per.values()),
        sum(c.fn for c in per.values()),
    )

    def zmean(vals: Iterable[float]) -> float:
        v = [0.0 if math.isnan(x) else x for x in vals]
        return sum(v) / len(v)

    return {
        "per_label": per,
        "micro": {"precision": pooled.precision, "recall": pooled.recall, "f1": pooled.f1},
        "macro": {
            "precision": zmean(c.precision for c in present),
            "recall": zmean(c.recall for c in present),
            "f1": zmean(c.f1 for c in present),
        },
    }


def exact_set_match(gold: Iterable[Any], predicted: Iterable[Any]) -> float:
    """Fraction of examples whose predicted label set equals the gold label set exactly.

    ``mean(set(predicted[i]) == set(gold[i]))``. Two empty sets match, so "no labels"
    predicted for an example with no gold labels counts as correct.

    Args:
        gold: Per example, a collection of gold labels.
        predicted: Per example, a collection of predicted labels.

    Returns:
        A float in [0, 1]. Empty input or unequal lengths raise ``ValueError``.
    """
    g = _label_sets(gold, "gold")
    p = _label_sets(predicted, "predicted")
    _same_length(g, p, "gold and predicted")
    return sum(a == b for a, b in zip(g, p, strict=True)) / len(g)


# --------------------------------------------------------------------------- Score and ranking


def score_level(answer: Any) -> Any:
    """The most probable level of a Score answer; plain numbers are returned unchanged.

    For an answer with ``probabilities``, the level (key) with the highest probability;
    ties go to the lowest level. The SDK types Score ``probabilities`` keys as ``int``;
    the JSON on the wire uses string keys. Both are accepted, and numeric string keys are
    converted to ``int``.

    Args:
        answer: A Score answer, or a plain number.

    Returns:
        The level. Raises ``ValueError`` if ``probabilities`` is empty.
    """
    if not hasattr(answer, "probabilities"):
        return answer
    probs = answer.probabilities
    if len(probs) == 0:
        raise ValueError("answer has empty probabilities")
    levels = [_level_key(k) for k in probs]
    values = list(probs.values())
    top = max(values)
    return min(lv for lv, v in zip(levels, values, strict=True) if v == top)


def _level_key(k: Any) -> Any:
    if isinstance(k, str):
        try:
            return int(k)
        except ValueError:
            return k
    return k


def exact_agreement(gold: Iterable[Any], predicted: Iterable[Any], tolerance: float = 0.0) -> float:
    """Fraction of examples where the predicted level is within ``tolerance`` of gold.

    ``mean(|level(predicted[i]) - gold[i]| <= tolerance)``. With the default tolerance of
    0 this is exact agreement; 1 gives agreement within one level. A Score answer is
    reduced to its most probable level (:func:`score_level`); plain numbers are used as
    given, so round an expected score yourself if you want to compare it to a level.

    Args:
        gold: Gold levels (numbers).
        predicted: Score answers or plain numbers.
        tolerance: Non-negative allowed distance.

    Returns:
        A float in [0, 1]. Empty input, unequal lengths or a negative tolerance raise
        ``ValueError``.
    """
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    g = _floats(_as_list(gold, "gold"), "gold")
    p = _floats((score_level(x) for x in _as_list(predicted, "predicted")), "predicted")
    _same_length(g, p, "gold and predicted")
    return float(np.mean(np.abs(g - p) <= tolerance))


def mean_absolute_error(gold: Iterable[Any], predicted: Iterable[Any]) -> float:
    """Mean absolute distance, in score levels, between predicted and gold scores.

    ``mean(|predicted[i] - gold[i]|)``. For a Score answer, ``predicted[i]`` is its
    expected score (``.score``, which may fall between levels), not its modal level.

    Args:
        gold: Gold scores (numbers).
        predicted: Score answers or plain numbers.

    Returns:
        A non-negative float. Empty input or unequal lengths raise ``ValueError``.
    """
    g = _floats(_as_list(gold, "gold"), "gold")
    p = _floats(
        (x.score if hasattr(x, "score") else x for x in _as_list(predicted, "predicted")),
        "predicted",
    )
    _same_length(g, p, "gold and predicted")
    return float(np.mean(np.abs(g - p)))


def _tie_averaged(scores: np.ndarray, values: np.ndarray) -> np.ndarray:
    """``values`` arranged in descending ``scores`` order; each group of tied scores is
    replaced by its mean, which is the expectation over all orderings of the tie."""
    order = np.argsort(-scores, kind="stable")
    s = scores[order]
    v = values[order].astype(float)
    out = np.empty_like(v)
    start = 0
    while start < len(s):
        end = start
        while end + 1 < len(s) and s[end + 1] == s[start]:
            end += 1
        out[start : end + 1] = v[start : end + 1].mean()
        start = end + 1
    return out


def ndcg(
    gold_relevance: Iterable[Any],
    scores: Iterable[Any],
    k: int | None = None,
    gain: str = "linear",
) -> float:
    """Quality of a ranking of one list of items, discounted so top positions matter most.

    ``DCG@k = sum_{i=1..k} g(rel_i) / log2(i + 1)`` with items ordered by ``scores``
    descending, ``g(r) = r`` (``gain="linear"``) or ``2^r - 1`` (``"exponential"``).
    ``nDCG@k = DCG@k / IDCG@k``, where IDCG is the DCG of the best possible order.
    Tied scores get the average gain of the positions they occupy (the expectation over
    tie orders).

    Args:
        gold_relevance: Non-negative gold relevance per item.
        scores: Score per item; higher ranks first. Score answers (``.score``) or numbers.
        k: Cut-off; default is the whole list. Must be at least 1; larger than the list
            is the same as the whole list.
        gain: ``"linear"`` or ``"exponential"``.

    Returns:
        A float in [0, 1], or NaN when IDCG is 0 (no item has positive gain). Empty input,
        unequal lengths, negative relevance or bad ``k``/``gain`` raise ``ValueError``.
    """
    if gain not in ("linear", "exponential"):
        raise ValueError(f"unknown gain {gain!r}")
    rel = _floats(_as_list(gold_relevance, "gold_relevance"), "gold_relevance")
    sc = _floats(
        (x.score if hasattr(x, "score") else x for x in _as_list(scores, "scores")), "scores"
    )
    _same_length(rel, sc, "gold_relevance and scores")
    if rel.min() < 0:
        raise ValueError("relevance must be non-negative")
    if k is not None and k < 1:
        raise ValueError("k must be at least 1")
    g = rel if gain == "linear" else 2.0**rel - 1.0
    cut = len(g) if k is None else min(k, len(g))
    discount = 1.0 / np.log2(np.arange(2, cut + 2))
    dcg = float(np.sum(_tie_averaged(sc, g)[:cut] * discount))
    idcg = float(np.sum(np.sort(g)[::-1][:cut] * discount))
    return dcg / idcg if idcg > 0 else float("nan")


def mean_ndcg(
    queries: Iterable[tuple[Any, Any]], k: int | None = None, gain: str = "linear"
) -> float:
    """Mean :func:`ndcg` over several ranked lists.

    Args:
        queries: Pairs ``(gold_relevance, scores)``, one per list.
        k, gain: As in :func:`ndcg`.

    Returns:
        The mean over lists whose nDCG is defined. Lists with IDCG 0 are skipped; if
        every list is skipped the result is NaN. No lists, or any invalid list, raise
        ``ValueError``.
    """
    vals = [ndcg(r, s, k=k, gain=gain) for r, s in _as_list(queries, "queries")]
    defined = [v for v in vals if not math.isnan(v)]
    return float(np.mean(defined)) if defined else float("nan")


def top_probabilities(answers: Iterable[Any]) -> list[float]:
    """Highest probability in each answer's ``probabilities``.

    Note this is not always ``.confidence``. For Choice, ``.confidence`` is the top probability
    rescaled, ``(p_max - 1/n) / (1 - 1/n)`` (0 at a uniform spread, 1 at a single peak), so
    it is not the model's stated chance that its pick is right. For Score, ``.confidence`` is
    ``max(0, 1 - sum_i p_i |i - m| / MAD_unif)``, a distance-based spread measure that depends
    on the distance between levels (``m`` is the most probable level), not on the top
    probability alone. The top probability is the usual input to calibration functions (it is
    the model's stated chance that its own pick is right).

    Args:
        answers: Choice or Score answers (anything with ``probabilities``).

    Returns:
        A list of floats. Empty input, or an answer without probabilities, raises
        ``ValueError``.
    """
    out = []
    for a in _as_list(answers, "answers"):
        if not hasattr(a, "probabilities") or len(a.probabilities) == 0:
            raise ValueError("answer has no probabilities")
        out.append(float(max(a.probabilities.values())))
    return out


def top_k_accuracy(gold: Iterable[Any], probabilities: Iterable[Any], k: int) -> float:
    """Fraction of examples whose gold option is among the ``k`` most probable options.

    Options are ranked by probability, descending. If the gold option is tied with others
    across the cut-off, it gets fractional credit equal to the share of the tied options
    that fit in the top ``k`` (the expectation over tie orders), so uniform
    probabilities over ``m`` options score ``min(1, k / m)``.

    Args:
        gold: Gold options (or levels).
        probabilities: Per example, a mapping option to probability, or an answer with
            ``.probabilities``. Keys match gold by equality, and also by string form, so
            integer gold levels match both ``int`` keys (the SDK's Score type) and string
            keys (the wire JSON).
        k: At least 1.

    Returns:
        A float in [0, 1]. Empty input, unequal lengths, ``k < 1`` or a gold option that
        is not among an example's options raise ``ValueError``.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    g = _as_list(gold, "gold")
    ps = _as_list(probabilities, "probabilities")
    _same_length(g, ps, "gold and probabilities")
    total = 0.0
    for gold_opt, p in zip(g, ps, strict=True):
        mapping = p.probabilities if hasattr(p, "probabilities") else p
        match = [key for key in mapping if key == gold_opt or str(key) == str(gold_opt)]
        if not match:
            raise ValueError(f"gold option {gold_opt!r} is not among options {list(mapping)!r}")
        mine = float(mapping[match[0]])
        above = sum(float(v) > mine for v in mapping.values())
        tied = sum(float(v) == mine for v in mapping.values())
        total += min(1.0, max(0.0, (k - above) / tied))
    return total / len(g)


def recall_at_budget(gold_relevant: Iterable[Any], scores: Iterable[Any], budget: int) -> float:
    """Share of all relevant items found when reviewing only the ``budget`` top-scored items.

    ``recall = (relevant items among the top budget by score) / (all relevant items)``.
    Tied scores across the cut-off are credited in expectation (the average over tie
    orders). A ``budget`` larger than the list is treated as the whole list.

    Args:
        gold_relevant: Gold relevance per item (bool or 0/1).
        scores: Score per item; higher is reviewed first. Numbers, or Noul/Score answers
            (``.noul`` or ``.score``).
        budget: Number of items that can be reviewed, at least 1.

    Returns:
        A float in [0, 1], or NaN when no item is relevant. Empty input, unequal lengths
        or ``budget < 1`` raise ``ValueError``.
    """
    if budget < 1:
        raise ValueError("budget must be at least 1")
    rel = _binary(_as_list(gold_relevant, "gold_relevant"), "gold_relevant").astype(float)
    sc = _floats(
        (
            x.noul if hasattr(x, "noul") else x.score if hasattr(x, "score") else x
            for x in _as_list(scores, "scores")
        ),
        "scores",
    )
    _same_length(rel, sc, "gold_relevant and scores")
    total = float(rel.sum())
    if total == 0:
        return float("nan")
    return float(_tie_averaged(sc, rel)[: min(budget, len(rel))].sum() / total)


# --------------------------------------------------------------------------- Selective prediction


def _conf_inputs(
    correct: Iterable[Any], confidence: Iterable[Any]
) -> tuple[np.ndarray, np.ndarray]:
    ok = _binary(_as_list(correct, "correct"), "correct")
    items = _as_list(confidence, "confidence")
    if any(hasattr(x, "noul") and not hasattr(x, "confidence") for x in items):
        raise ValueError(
            "a Noul answer has no confidence; pass noul_confidence(noul) as the confidence"
        )
    conf = _floats(
        (x.confidence if hasattr(x, "confidence") else x for x in items),
        "confidence",
        unit_interval=True,
    )
    _same_length(ok, conf, "correct and confidence")
    return ok, conf


@dataclass(frozen=True)
class SelectiveCurve:
    """Accuracy against coverage as the confidence threshold falls.

    Entry ``i`` is the rule "answer when confidence >= ``thresholds[i]``", with
    ``thresholds`` descending, so ``coverage`` is non-decreasing. ``risk = 1 - accuracy``
    (the risk and coverage curve is ``risk`` against ``coverage``).
    """

    thresholds: np.ndarray
    coverage: np.ndarray
    accuracy: np.ndarray
    risk: np.ndarray


def selective_curve(correct: Iterable[Any], confidence: Iterable[Any]) -> SelectiveCurve:
    """Accuracy and risk of the answered subset at every confidence threshold.

    For each distinct confidence value t, ``coverage = (# with confidence >= t) / n`` and
    ``accuracy = (# correct among them) / (# with confidence >= t)``. Examples with equal
    confidence enter together, so the curve does not depend on input order.

    Args:
        correct: Whether each prediction was right (bool or 0/1).
        confidence: Per-example confidence, in [0, 1]: numbers, or Choice/Score answers
            (``.confidence``). For Noul see :func:`noul_confidence`.

    Returns:
        A :class:`SelectiveCurve`. Every entry answers at least one example, so accuracy
        is always defined. Empty input, unequal lengths, or a confidence outside [0, 1]
        (a sentinel such as -1.0 included) raise ``ValueError``.
    """
    ok, conf = _conf_inputs(correct, confidence)
    thresholds = np.unique(conf)[::-1]
    n = len(ok)
    cov, acc = [], []
    for t in thresholds:
        sel = conf >= t
        cov.append(sel.sum() / n)
        acc.append(ok[sel].mean())
    acc_a = np.asarray(acc)
    return SelectiveCurve(thresholds, np.asarray(cov), acc_a, 1.0 - acc_a)


def select_confidence_threshold(
    correct: Iterable[Any],
    confidence: Iterable[Any],
    target_accuracy: float | None = None,
    min_coverage: float | None = None,
) -> float:
    """Choose a confidence threshold on a validation split; returns the value to freeze.

    Give exactly one of:

    * ``target_accuracy``: the lowest threshold (so the highest coverage) whose answered
      subset has accuracy ``>= target_accuracy``.
    * ``min_coverage``: among thresholds with coverage ``>= min_coverage``, the one with
      the highest accuracy (ties go to the lower threshold, i.e. more coverage).

    Candidates are the distinct observed confidence values, so the result is always in
    [0, 1] itself. Call this on validation data only, then report with
    :func:`evaluate_selective` on test data using the returned value unchanged.

    A rule whose review branch is more than a confidence gate (an explicit fallback
    option, a foreign-option check, any other unconditional branch) has no real
    confidence for the answers it rejects outright. Do not invent one by feeding a
    sentinel such as ``-1.0`` or ``2.0`` into ``confidence`` to make this function (or
    :func:`evaluate_selective`) reproduce the rule's split: an out-of-range sentinel now
    raises here before it can be selected as a threshold and handed back to the rule's
    own ``min_confidence`` check. Compute the rule's own coverage/accuracy/risk with
    :func:`evaluate_outcomes` instead; see "Selective prediction" in
    ``docs/evaluation.md``.

    Args:
        correct: Whether each validation prediction was right.
        confidence: Per-example confidence, in [0, 1] (numbers or answers with
            ``.confidence``).
        target_accuracy: Accuracy to guarantee on the answered subset, in [0, 1].
        min_coverage: Minimum answered fraction, in (0, 1].

    Returns:
        The threshold as a float, itself in [0, 1]. Raises ``ValueError`` on empty input,
        a confidence outside [0, 1], when not exactly one criterion is given, or when no
        threshold satisfies it.
    """
    if (target_accuracy is None) == (min_coverage is None):
        raise ValueError("give exactly one of target_accuracy and min_coverage")
    curve = selective_curve(correct, confidence)
    if target_accuracy is not None:
        feasible = np.nonzero(curve.accuracy >= target_accuracy)[0]
        if len(feasible) == 0:
            raise ValueError(f"no threshold reaches accuracy {target_accuracy}")
        return float(curve.thresholds[feasible[-1]])  # thresholds descend: last is lowest
    feasible = np.nonzero(curve.coverage >= min_coverage)[0]  # type: ignore[operator]
    if len(feasible) == 0:
        raise ValueError(f"no threshold reaches coverage {min_coverage}")
    best = max(float(curve.accuracy[i]) for i in feasible)
    return float(curve.thresholds[[i for i in feasible if curve.accuracy[i] == best][-1]])


@dataclass(frozen=True)
class SelectiveResult:
    """Outcome of answering only some examples, out of a total of ``n_total``.

    ``accuracy`` and ``risk`` are NaN when nothing was answered (``n_answered == 0``).
    ``threshold`` is the frozen confidence cut-off that produced ``n_answered`` when this
    came from :func:`evaluate_selective`; it is NaN when this came from
    :func:`evaluate_outcomes` instead, because no single confidence cut-off decided which
    examples were answered there, so a threshold is not merely unknown but undefined
    (the module's general NaN convention: see ``docs/evaluation.md``).
    """

    threshold: float
    n_total: int
    n_answered: int
    coverage: float
    accuracy: float
    risk: float


def evaluate_selective(
    correct: Iterable[Any], confidence: Iterable[Any], threshold: float
) -> SelectiveResult:
    """Coverage and accuracy of the rule "answer when confidence >= ``threshold``".

    ``coverage = n_answered / n``; ``accuracy = correct answered / n_answered``;
    ``risk = 1 - accuracy``. Abstentions are not counted as errors. The threshold is an
    argument: choose it with :func:`select_confidence_threshold` on validation data.

    This reapplies ``confidence >= threshold`` itself; it does not call the rule. That is
    exactly right when the rule's only review branch *is* that confidence gate (nothing
    else can send an example to review), and wrong otherwise: a rule with an additional
    unconditional branch (an explicit fallback option such as ``no_match``, a check that
    the chosen option is a real member of some set, or any other branch that does not
    depend on ``min_confidence``) can reject an example this function would still count as
    answered, or vice versa. For such a rule, build ``accepted``/``correct`` from what the
    rule itself returned and use :func:`evaluate_outcomes` instead of reaching for this
    function with a made-up confidence for the examples the rule rejects unconditionally.
    See "Selective prediction" in ``docs/evaluation.md`` for the full convention.

    Args:
        correct: Whether each prediction was right.
        confidence: Per-example confidence, in [0, 1] (numbers or answers with
            ``.confidence``).
        threshold: The frozen cut-off.

    Returns:
        A :class:`SelectiveResult`. Empty input, unequal lengths, or a confidence outside
        [0, 1] (a sentinel such as -1.0 included) raise ``ValueError``.
    """
    ok, conf = _conf_inputs(correct, confidence)
    sel = conf >= threshold
    n_ans = int(sel.sum())
    acc = float(ok[sel].mean()) if n_ans else float("nan")
    return SelectiveResult(float(threshold), len(ok), n_ans, n_ans / len(ok), acc, 1.0 - acc)


def evaluate_outcomes(accepted: Iterable[Any], correct: Iterable[Any]) -> SelectiveResult:
    """Coverage and accuracy of a rule's own accept/review decisions.

    Use this, not :func:`evaluate_selective`, for a rule whose review branch is more than
    a single confidence gate: an explicit fallback option the rule never gates on
    confidence (``no_match``, ``unclear``, ...), a check that the chosen option is really
    a member of some set, or any other branch that can send an example to review (or let
    it through) independently of ``confidence >= threshold``. Pass what the rule actually
    did, not a reconstruction of it: ``accepted[i]`` is whether the rule answered example
    ``i`` (True) or sent it to review (False), and ``correct[i]`` is whether an answered
    example's answer was right (ignored, but still required, where ``accepted[i]`` is
    False). Do not feed a sentinel confidence (``-1.0``, ``2.0``, ...) for the
    unconditionally-rejected examples into :func:`select_confidence_threshold` or
    :func:`evaluate_selective` to reproduce this split instead: that is exactly the
    mistake this function exists to replace, and an out-of-range sentinel now raises in
    both of those functions rather than silently leaking into a threshold.

    ``coverage = n_answered / n``; ``accuracy = correct among answered / n_answered``;
    ``risk = 1 - accuracy``, the same definitions as :func:`evaluate_selective`. For a
    rule whose *only* review branch is a confidence gate, the two functions agree on
    every field but ``threshold``: ``evaluate_outcomes(confidence >= t, correct)`` equals
    ``evaluate_selective(correct, confidence, t)`` in ``n_total``, ``n_answered``,
    ``coverage``, ``accuracy`` and ``risk`` (``threshold`` is NaN here, a real float
    there), because ``accepted`` and ``conf >= threshold`` select exactly the same
    examples. The two diverge as soon as the rule has a second, unconditional branch,
    which is the case this function is for.

    Args:
        accepted: Whether the rule answered (as opposed to sent to review) each example,
            as the rule itself decided it (bool or 0/1).
        correct: Whether each answered example's answer was right (bool or 0/1).

    Returns:
        A :class:`SelectiveResult` with ``threshold`` NaN (see its docstring: no single
        confidence cut-off produced ``accepted`` here, so a threshold is undefined, not
        merely unreported). Empty input or unequal lengths raise ``ValueError``.
    """
    acc = _binary(_as_list(accepted, "accepted"), "accepted")
    ok = _binary(_as_list(correct, "correct"), "correct")
    _same_length(acc, ok, "accepted and correct")
    n_ans = int(acc.sum())
    accuracy_ = float(ok[acc].mean()) if n_ans else float("nan")
    return SelectiveResult(
        float("nan"), len(acc), n_ans, n_ans / len(acc), accuracy_, 1.0 - accuracy_
    )


# --------------------------------------------------------------------------- Calibration


@dataclass(frozen=True)
class ReliabilityBin:
    """One bin of a reliability table. ``mean_probability`` and ``observed_rate`` are NaN
    for an empty bin (``count == 0``)."""

    lower: float
    upper: float
    count: int
    mean_probability: float
    observed_rate: float


def reliability_table(
    probability: Iterable[Any], outcome: Iterable[Any], n_bins: int = 10
) -> list[ReliabilityBin]:
    """Stated probability against observed frequency, in equal-width probability bins.

    Bins split [0, 1] into ``n_bins`` equal parts; a value belongs to ``(lower, upper]``,
    except that 0 falls in the first bin. Each bin reports its count, the mean stated
    probability and the observed rate of the outcome. For Noul, ``probability`` is the
    noul and ``outcome`` the gold truth value. For Choice or Score, ``probability`` is the
    top probability (:func:`top_probabilities`) and ``outcome`` is whether the pick was
    right.

    Args:
        probability: Numbers in [0, 1] (Noul answers are read through ``.noul``).
        outcome: Whether the event happened (bool or 0/1).
        n_bins: At least 1.

    Returns:
        ``n_bins`` :class:`ReliabilityBin` entries, including empty ones. Empty input,
        unequal lengths, out-of-range values or ``n_bins < 1`` raise ``ValueError``.
    """
    if n_bins < 1:
        raise ValueError("n_bins must be at least 1")
    p = _noul_array(_as_list(probability, "probability"), "probability")
    y = _binary(_as_list(outcome, "outcome"), "outcome").astype(float)
    _same_length(p, y, "probability and outcome")
    # Round away float noise (0.7 * 10 == 7.000000000000001) so edges land in the lower bin.
    idx = np.clip(np.ceil(np.round(p * n_bins, 9)).astype(int) - 1, 0, n_bins - 1)
    bins = []
    for b in range(n_bins):
        m = idx == b
        cnt = int(m.sum())
        bins.append(
            ReliabilityBin(
                b / n_bins,
                (b + 1) / n_bins,
                cnt,
                float(p[m].mean()) if cnt else float("nan"),
                float(y[m].mean()) if cnt else float("nan"),
            )
        )
    return bins


def expected_calibration_error(
    probability: Iterable[Any], outcome: Iterable[Any], n_bins: int = 10
) -> float:
    """Average gap between stated probability and observed frequency, weighted by bin size.

    ``ECE = sum over non-empty bins of (count / n) * |observed_rate - mean_probability|``
    using the bins of :func:`reliability_table`. 0 means stated probabilities match
    observed frequencies in every bin. It depends on ``n_bins``.

    Args:
        probability, outcome, n_bins: As in :func:`reliability_table`.

    Returns:
        A float in [0, 1]. Same errors as :func:`reliability_table`.
    """
    table = reliability_table(probability, outcome, n_bins)
    n = sum(b.count for b in table)
    return sum(b.count / n * abs(b.observed_rate - b.mean_probability) for b in table if b.count)


# --------------------------------------------------------------------------- Comparison


@dataclass(frozen=True)
class BootstrapResult:
    """Paired bootstrap result: ``difference`` is mean(a) - mean(b) on the data; ``lower``
    and ``upper`` bound it at ``confidence_level`` (percentile method)."""

    difference: float
    lower: float
    upper: float
    confidence_level: float
    n: int
    n_resamples: int
    seed: int


def paired_bootstrap_difference(
    a: Iterable[Any],
    b: Iterable[Any],
    *,
    seed: int,
    n_resamples: int = 10_000,
    confidence_level: float = 0.95,
) -> BootstrapResult:
    """Confidence interval for how much system A's mean per-example score exceeds B's.

    Per-example scores of A and B must be aligned (same example at the same index). The
    differences ``d[i] = a[i] - b[i]`` are resampled with replacement, ``n_resamples``
    times; the interval is the ``(1 - level) / 2`` and ``(1 + level) / 2`` percentiles
    (numpy's default linear interpolation) of the resampled means of ``d``. If the
    interval excludes 0, the difference is unlikely to be resampling noise on this data.

    The result is deterministic for a given ``seed`` (``numpy.random.default_rng``).
    Pass per-example correctness (0/1), per-example error, or any per-example number.

    Args:
        a, b: Per-example scores, equal length.
        seed: Required integer seed.
        n_resamples: At least 1.
        confidence_level: In (0, 1).

    Returns:
        A :class:`BootstrapResult`. Empty input, unequal lengths or invalid settings raise
        ``ValueError``.
    """
    av = _floats(_as_list(a, "a"), "a")
    bv = _floats(_as_list(b, "b"), "b")
    _same_length(av, bv, "a and b")
    if n_resamples < 1 or not 0.0 < confidence_level < 1.0:
        raise ValueError("need n_resamples >= 1 and confidence_level in (0, 1)")
    d = av - bv
    n = len(d)
    rng = np.random.default_rng(seed)
    means = np.empty(n_resamples)
    chunk = max(1, 2_000_000 // n)  # bounded memory; fixed rule, so still deterministic
    for start in range(0, n_resamples, chunk):
        size = min(chunk, n_resamples - start)
        means[start : start + size] = d[rng.integers(0, n, size=(size, n))].mean(axis=1)
    lo, hi = np.quantile(means, [(1 - confidence_level) / 2, (1 + confidence_level) / 2])
    return BootstrapResult(
        float(d.mean()), float(lo), float(hi), confidence_level, n, n_resamples, seed
    )


# --------------------------------------------------------------------------- Accounting


@dataclass(frozen=True)
class UsageTotals:
    """Summed usage. ``input_tokens`` and ``output_tokens`` add only the requests that
    reported them; ``requests_missing_input`` / ``requests_missing_output`` count the
    requests that did not, so a partial total is never mistaken for a full one."""

    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    requests_missing_input: int
    requests_missing_output: int


def sum_usage(usages: Iterable[Mapping[str, Any] | None]) -> UsageTotals:
    """Request count and token totals from the per-request ``usage`` blocks.

    Each usage block is a mapping with optional ``input_tokens`` and ``output_tokens``
    integers, each possibly absent or ``None`` when the API did not report it. A ``None``
    block is a request with nothing reported. Objects with those attributes (such as
    ``Usage`` and ``DecisionResult.usage``) are accepted too. ``requests`` is the number of blocks; ``total_tokens`` is input plus output of
    the reported values.

    Args:
        usages: One usage mapping or ``Usage`` object per request.

    Returns:
        A :class:`UsageTotals`. No requests, or a negative or non-integer count, raise
        ``ValueError``.
    """
    items = _as_list(usages, "usages")
    totals = {"input_tokens": 0, "output_tokens": 0}
    missing = {"input_tokens": 0, "output_tokens": 0}
    for u in items:
        for key in totals:
            if u is None:
                val = None
            elif isinstance(u, Mapping):
                val = u.get(key)
            else:
                val = getattr(u, key, None)
            if val is None:
                missing[key] += 1
                continue
            if isinstance(val, bool) or int(val) != val or val < 0:
                raise ValueError(f"{key} must be a non-negative integer, got {val!r}")
            totals[key] += int(val)
    return UsageTotals(
        len(items),
        totals["input_tokens"],
        totals["output_tokens"],
        totals["input_tokens"] + totals["output_tokens"],
        missing["input_tokens"],
        missing["output_tokens"],
    )
