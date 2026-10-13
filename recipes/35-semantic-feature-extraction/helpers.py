"""Python's half of recipe 35: the state, the six semantic-feature questions, the deterministic
composition that turns their answers into a feature vector, and the two classifiers (a Bernoulli
Naive Bayes classifier and a fixed majority-class baseline) that vector feeds.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions, the state and the rules cannot disagree.
"""

import math
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------- The feature list
#
# A fixed, predefined list of six semantic features (CONTRIBUTING.md section 3: "Noul
# propositions are written as statements that can be true or false. One independent question
# per label for multi-label tasks."). Each statement is written so it can be judged true or
# false on its own, independent of the other five: the use case ("compare a classifier trained
# on those features with a fixed baseline") needs a feature *vector*, which only means something
# if each entry is its own independent judgment rather than a restatement of another entry. No
# two of the six co-vary in the fixtures below for a mechanical reason -- each is authored
# separately, and tests/test_helpers.py checks that none is the complement or duplicate of
# another on the committed fixtures.
#
# A dict, not a set, so the order Python builds the six questions in is stable (insertion
# order), and so build_fixtures.py and the classifier agree on which position in a feature
# vector belongs to which feature.
FEATURES: dict[str, str] = {
    "mentions_price": (
        "The feedback mentions a specific price, fee, charge, subscription cost, or billing amount."
    ),
    "expresses_frustration": (
        "The feedback expresses frustration, anger, or strong disappointment with the product "
        "or service."
    ),
    "requests_refund_or_cancellation": (
        "The feedback explicitly asks for a refund, a credit, or to cancel the subscription."
    ),
    "mentions_competitor": (
        "The feedback names, or clearly and specifically identifies, a competing product or "
        "service."
    ),
    "reports_technical_issue": (
        "The feedback reports a bug, a crash, an error message, or something not working as "
        "expected."
    ),
    "expresses_satisfaction": (
        "The feedback expresses satisfaction, praise, or a positive experience with the product."
    ),
}

# The classifier's own target: a second, independently-authored gold label per example (never
# computed from the six features above; see fixtures/labels.jsonl and build_fixtures.py ROWS,
# where every row states both explicitly). Whether this piece of feedback should be escalated to
# a human customer-success specialist for individual follow-up, rather than handled routinely.
TARGET = "escalate"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one piece of feedback: the text, and nothing else.

    ``fields`` also carries a ``message_id`` bookkeeping identifier. Python keeps it and
    attaches it to the outcome, so it never needs to pass through the model.
    """
    return {"text": fields["text"]}


def build_questions() -> dict[str, Noul]:
    """One independent ``Noul`` per feature in ``FEATURES``, built by Python from that fixed
    list. All six describe the same state, so ``backend.decide`` sends them together in a
    single request (TypeSafe's primitives page, S02: independent questions over the same state
    belong in one request) -- six independent judgments, one request, one feature vector per
    text. They are six separate questions, not one six-way Choice, because the six outcomes are
    not exclusive: a piece of feedback can mention a price, report a bug and ask for a refund
    all at once, or none of the six at all.
    """
    return {
        name: Noul(
            instructions=statement,
            criteria={
                "true": statement,
                "false": "The feedback does not do this at all.",
            },
        )
        for name, statement in FEATURES.items()
    }


# --------------------------------------------------------------------------- The deterministic composition


@dataclass(frozen=True)
class FeatureDecision:
    """What Python decided for one (example, feature) pair: the raw Noul probability and the
    business tag it crosses to, a plain ``noul >= threshold`` comparison with no further gate.
    Noul has no confidence field (CONTRIBUTING.md section 3), so unlike a three-path Noul recipe
    this rule has nothing to send to review: every feature decision is a direct, deterministic
    composition of the model's probability and a threshold chosen from examples."""

    name: str
    noul: float
    present: bool


def compose_features(answers: Any, thresholds: dict[str, float]) -> dict[str, FeatureDecision]:
    """Apply each feature's own frozen business threshold to one request's six Noul answers.

    ``answers`` is a mapping from feature name to a Noul answer (or anything with a ``.noul``,
    or a plain probability). For every feature in ``FEATURES``: ``present`` is
    ``noul >= thresholds[name]``, the one condition this function ever applies -- the composition
    is deterministic and total, not a three-path rule, because a semantic feature has nothing to
    defer to a person: there is no third outcome here, only "present" or "absent", chosen from
    examples the same way CONTRIBUTING.md's confidence page describes any business threshold.

    Args:
        answers: ``{feature name: NoulAnswer-like or probability}``, one per name in
            ``FEATURES``.
        thresholds: The frozen per-feature thresholds (chosen on ``validation`` with
            ``jev_cookbook.evaluation.select_threshold``); must name exactly the features in
            ``FEATURES``, no more and no fewer.

    Returns:
        ``{feature name: FeatureDecision}``, one entry per name in ``FEATURES``.

    Raises:
        ValueError: ``thresholds`` does not name exactly ``FEATURES``, a threshold or a noul
            value lies outside ``[0, 1]``, or ``answers`` is missing a feature.
    """
    if set(thresholds) != set(FEATURES):
        raise ValueError(
            f"thresholds must name exactly FEATURES {sorted(FEATURES)}, got {sorted(thresholds)}"
        )
    decisions: dict[str, FeatureDecision] = {}
    for name in FEATURES:
        try:
            raw = answers[name]
        except KeyError:
            raise ValueError(f"answers is missing feature {name!r}") from None
        noul = float(raw.noul) if hasattr(raw, "noul") else float(raw)
        if not 0.0 <= noul <= 1.0:
            raise ValueError(f"noul for {name!r} must lie in [0, 1], got {noul!r}")
        threshold = float(thresholds[name])
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold for {name!r} must lie in [0, 1], got {threshold!r}")
        decisions[name] = FeatureDecision(name, noul, noul >= threshold)
    return decisions


def feature_vector(decisions: dict[str, FeatureDecision]) -> tuple[bool, ...]:
    """The composed feature vector for one example: a fixed-order tuple of booleans, one per
    name in ``FEATURES`` (insertion order), so every caller of the classifier below agrees on
    which position means which feature."""
    return tuple(decisions[name].present for name in FEATURES)


# --------------------------------------------------------------------------- A confidence gate, as a
# --------------------------------------------------------------------------- diagnostic alongside the vector

# The outcome a feature decision is routed to when its own confidence is too low to trust
# automatically. By convention (see docs/glossary.md#review) the value itself is the string
# "review", whatever a recipe's own sub-reasons are named.
REVIEW = "review"
CONFIDENT = "confident"


def confidence_outcome(noul: float, confidence_gate: float) -> tuple[str, str]:
    """Whether one feature decision is confident enough to trust automatically, using the
    pooled confidence gate "Python's part" chooses on ``validation`` -- a second, independent
    cut beside the business threshold :func:`compose_features` already applies (Noul has no
    confidence field of its own; :func:`jev_cookbook.evaluation.noul_confidence` derives one,
    ``|2p - 1|``, from the probability, per S03).

    This is a diagnostic only: :func:`feature_vector` always uses the business tag
    (``present``/absent), whatever this function reports, because the classifier below can
    weigh a noisy boolean feature itself and does not need one withheld the way an answer shown
    directly to a person would be. The notebook reports how many (text, feature) decisions this
    gate would send to review, without ever changing what the classifier is trained or run on.

    Args:
        noul: A feature's Noul probability, in [0, 1].
        confidence_gate: The frozen, pooled confidence gate (chosen on ``validation`` with
            ``jev_cookbook.evaluation.select_confidence_threshold``), in [0, 1].

    Returns:
        ``(REVIEW, "confidence below the threshold")`` when ``noul_confidence(noul) <
        confidence_gate``, else ``(CONFIDENT, "confidence at or above the threshold")``.

    Raises:
        ValueError: ``noul`` or ``confidence_gate`` lies outside ``[0, 1]``.
    """
    if not 0.0 <= noul <= 1.0:
        raise ValueError(f"noul must lie in [0, 1], got {noul!r}")
    if not 0.0 <= confidence_gate <= 1.0:
        raise ValueError(f"confidence_gate must lie in [0, 1], got {confidence_gate!r}")
    confidence = noul_confidence([noul])[0]
    if confidence < confidence_gate:
        return REVIEW, "confidence below the threshold"
    return CONFIDENT, "confidence at or above the threshold"


# --------------------------------------------------------------------------- The fixed baseline


@dataclass(frozen=True)
class MajorityBaseline:
    """The fixed baseline: predicts the majority ``TARGET`` class observed on ``train``, chosen
    once from that split and reused for every example afterwards, whatever its feature vector
    is. A tie goes to ``True`` (escalate): naming the tie rule explicitly, rather than letting it
    fall out of argument order or dict iteration, is what makes this baseline a value fixed in
    code rather than an accident of how it was computed."""

    majority: bool


def fit_majority_baseline(targets: Any) -> MajorityBaseline:
    """The majority-class baseline, fit on ``train``'s own ``TARGET`` gold labels only.

    This is the one setting the baseline ever learns: a single constant, frozen here before any
    ``validation`` or ``test`` example is looked at. It never reads a feature vector, by design
    -- that is what makes it a baseline a feature-based classifier has something to beat, and
    not a weaker copy of the same rule.

    Args:
        targets: The ``TARGET`` gold label (bool or 0/1) of every ``train`` example.

    Returns:
        A :class:`MajorityBaseline`.

    Raises:
        ValueError: ``targets`` is empty.
    """
    values = [bool(t) for t in targets]
    if not values:
        raise ValueError("fit_majority_baseline needs at least one example")
    n_true = sum(values)
    n_false = len(values) - n_true
    return MajorityBaseline(majority=n_true >= n_false)


def predict_majority_baseline(baseline: MajorityBaseline, n: int) -> list[bool]:
    """The baseline's prediction for ``n`` examples: its one frozen constant, repeated."""
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n!r}")
    return [baseline.majority] * n


# --------------------------------------------------------------------------- The simple classifier

# Laplace smoothing constant: a fixed hyperparameter, never tuned on any split, so the model has
# no setting left to select once ``train`` is fit. 1.0 is "add one" smoothing, the standard
# choice when nothing about the data favours another value.
LAPLACE_ALPHA = 1.0


@dataclass(frozen=True)
class NaiveBayesModel:
    """A Bernoulli Naive Bayes classifier over a boolean feature vector: the two class priors
    and, per class, the log-probability of each feature reading True and of it reading False.
    Plain Python and ``math.log``, not a library, specifically so this file imports under
    ``.[dev]`` alone (the ``Tests`` CI jobs never install ``[ml]``; see the recipe README)."""

    feature_names: tuple[str, ...]
    log_prior: dict[bool, float]
    log_true: dict[bool, tuple[float, ...]]
    log_false: dict[bool, tuple[float, ...]]


def fit_naive_bayes(
    vectors: list[tuple[bool, ...]],
    targets: list[bool],
    feature_names: tuple[str, ...] = tuple(FEATURES),
    alpha: float = LAPLACE_ALPHA,
) -> NaiveBayesModel:
    """Fit a Bernoulli Naive Bayes classifier on ``train``'s own composed feature vectors.

    For each class ``c`` in ``(False, True)``: the prior is the share of ``train`` examples with
    that target, and for each feature ``j`` the Laplace-smoothed probability of reading True
    given class ``c`` is ``(count_true_j_in_c + alpha) / (n_c + 2 * alpha)``, stored as a log
    (and its complement, the log probability of reading False). ``predict_naive_bayes`` sums the
    stored log value for each feature's observed reading, so fitting and predicting never
    multiply probabilities directly and never need to worry about floating-point underflow on a
    mix of extreme values.

    Args:
        vectors: One ``feature_vector``-shaped tuple per ``train`` example.
        targets: ``TARGET`` gold label per ``train`` example, aligned with ``vectors``.
        feature_names: The fixed feature order (default: ``FEATURES``' own order).
        alpha: The Laplace smoothing constant (default: ``LAPLACE_ALPHA``, never tuned).

    Returns:
        A :class:`NaiveBayesModel`.

    Raises:
        ValueError: ``vectors``/``targets`` are empty, unequal length, a vector's length does
            not match ``feature_names``, ``alpha`` is not positive, or ``train`` does not
            contain both classes (a class with no examples has nothing to estimate a likelihood
            from).
    """
    if not vectors or not targets:
        raise ValueError("fit_naive_bayes needs at least one example")
    if len(vectors) != len(targets):
        raise ValueError(f"{len(vectors)} vectors but {len(targets)} targets")
    if alpha <= 0.0:
        raise ValueError(f"alpha must be positive, got {alpha!r}")
    n_features = len(feature_names)
    for v in vectors:
        if len(v) != n_features:
            raise ValueError(f"expected {n_features}-length vectors, got {len(v)!r}")
    targets = [bool(t) for t in targets]
    log_prior: dict[bool, float] = {}
    log_true: dict[bool, tuple[float, ...]] = {}
    log_false: dict[bool, tuple[float, ...]] = {}
    n_total = len(targets)
    for c in (False, True):
        rows = [v for v, t in zip(vectors, targets, strict=True) if t is c]
        n_c = len(rows)
        if n_c == 0:
            raise ValueError(f"train has no examples with target={c!r}; cannot fit a likelihood")
        log_prior[c] = math.log(n_c / n_total)
        true_j, false_j = [], []
        for j in range(n_features):
            count_true = sum(1 for v in rows if v[j])
            p_true = (count_true + alpha) / (n_c + 2.0 * alpha)
            true_j.append(math.log(p_true))
            false_j.append(math.log(1.0 - p_true))
        log_true[c] = tuple(true_j)
        log_false[c] = tuple(false_j)
    return NaiveBayesModel(tuple(feature_names), log_prior, log_true, log_false)


def predict_naive_bayes(model: NaiveBayesModel, vector: tuple[bool, ...]) -> bool:
    """The classifier's prediction for one feature vector: the class with the higher posterior
    log-probability (prior plus the sum of each feature's stored log-likelihood for its observed
    reading). A tie goes to ``True``, the same convention :func:`fit_majority_baseline` uses, so
    the two share one rule for what "no clear winner" means.

    Args:
        model: A fitted :class:`NaiveBayesModel`.
        vector: A ``feature_vector``-shaped tuple, same length and order as ``model.feature_names``.

    Returns:
        The predicted ``TARGET`` value.

    Raises:
        ValueError: ``vector``'s length does not match ``model.feature_names``.
    """
    if len(vector) != len(model.feature_names):
        raise ValueError(
            f"expected a {len(model.feature_names)}-length vector, got {len(vector)!r}"
        )
    scores: dict[bool, float] = {}
    for c in (False, True):
        score = model.log_prior[c]
        for j, present in enumerate(vector):
            score += model.log_true[c][j] if present else model.log_false[c][j]
        scores[c] = score
    return scores[True] >= scores[False]
