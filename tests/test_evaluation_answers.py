"""The evaluation toolkit against the real typed answer classes (not stand-ins)."""

from __future__ import annotations

import math
from types import MappingProxyType

import pytest

from jev_cookbook import evaluation as ev
from jev_cookbook.answers import (
    ChoiceAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    ScoreAnswer,
    Usage,
)

SYN = Provenance.synthetic()
LEGEND = ["low", "mid", "high"]


def choice(a: float, b: float, c: float) -> ChoiceAnswer:
    return ChoiceAnswer.from_probabilities({"a": a, "b": b, "c": c}, SYN)


def score(p0: float, p1: float, p2: float) -> ScoreAnswer:
    return ScoreAnswer.from_probabilities([p0, p1, p2], LEGEND, SYN)


CHOICES = [
    choice(0.7, 0.2, 0.1),  # a
    choice(0.6, 0.3, 0.1),  # a
    choice(0.2, 0.5, 0.3),  # b
    choice(0.1, 0.6, 0.3),  # b
    choice(0.2, 0.3, 0.5),  # c
    choice(0.1, 0.1, 0.8),  # c
]
CHOICE_GOLD = ["a", "a", "a", "b", "b", "c"]  # correct at 0, 1, 3, 5


def test_real_answers_use_read_only_mappings_and_int_score_keys():
    assert isinstance(CHOICES[0].probabilities, MappingProxyType)
    s = score(0.1, 0.2, 0.7)
    assert isinstance(s.probabilities, MappingProxyType)
    assert list(s.probabilities) == [0, 1, 2]


def test_choice_metrics():
    assert ev.accuracy(CHOICE_GOLD, CHOICES) == pytest.approx(4 / 6)
    cm = ev.confusion_matrix(CHOICE_GOLD, CHOICES)
    assert cm.labels == ["a", "b", "c"]
    assert cm.matrix.tolist() == [[2, 1, 0], [0, 1, 1], [0, 0, 1]]
    per = ev.per_class_metrics(CHOICE_GOLD, CHOICES)
    assert (per["a"].tp, per["a"].fp, per["a"].fn) == (2, 0, 1)
    assert per["a"].precision == pytest.approx(1.0)
    assert per["a"].recall == pytest.approx(2 / 3)


def test_noul_thresholds_on_noul_answers():
    # yes when noul >= 0.5; gold 1 at 0.9 and 0.6, gold 0 at 0.4 and 0.55
    answers = [NoulAnswer(v, SYN) for v in (0.9, 0.6, 0.4, 0.55)]
    gold = [1, 1, 0, 0]
    p = ev.evaluate_threshold(gold, answers, 0.5)
    assert (p.tp, p.fp, p.fn, p.tn) == (2, 1, 0, 1)
    assert p.precision == pytest.approx(2 / 3)
    assert p.recall == pytest.approx(1.0)
    sweep = ev.threshold_sweep(gold, answers)
    assert [pt.threshold for pt in sweep] == [0.4, 0.55, 0.6, 0.9]
    t = ev.select_threshold(gold, answers, objective="f1")
    assert t == pytest.approx(0.6)  # 0.6: tp 2, fp 0, fn 0 -> f1 1.0
    assert ev.brier_score(gold, answers) == pytest.approx((0.1**2 + 0.4**2 + 0.4**2 + 0.55**2) / 4)
    # |2p - 1|: 0.8, 0.2, 0.2, 0.1
    assert ev.noul_confidence(answers) == pytest.approx([0.8, 0.2, 0.2, 0.1])


def test_score_functions_on_score_answers():
    answers = [score(0.1, 0.2, 0.7), score(0.6, 0.3, 0.1), score(0.2, 0.6, 0.2)]
    assert [ev.score_level(a) for a in answers] == [2, 0, 1]
    assert all(type(ev.score_level(a)) is int for a in answers)
    assert ev.exact_agreement([2, 1, 1], answers) == pytest.approx(2 / 3)
    assert ev.exact_agreement([1, 1, 1], answers, tolerance=1) == pytest.approx(1.0)
    # expected scores: 0.2 + 1.4 = 1.6, 0.3 + 0.2 = 0.5, 1.0
    assert ev.mean_absolute_error([2, 0, 1], answers) == pytest.approx((0.4 + 0.5 + 0.0) / 3)
    assert ev.top_probabilities(answers) == pytest.approx([0.7, 0.6, 0.6])
    # gold level ranks: 2 is top for the first, 1 is second for the second, 1 is top for third
    assert ev.top_k_accuracy([2, 1, 1], answers, k=1) == pytest.approx(2 / 3)
    assert ev.top_k_accuracy([2, 1, 1], answers, k=2) == pytest.approx(1.0)


def test_selective_prediction_on_choice_top_probabilities():
    conf = ev.top_probabilities(CHOICES)
    assert conf == pytest.approx([0.7, 0.6, 0.5, 0.6, 0.5, 0.8])
    correct = [g == a.choice for g, a in zip(CHOICE_GOLD, CHOICES, strict=True)]
    curve = ev.selective_curve(correct, conf)
    # thresholds run from the strictest (highest) down to the most permissive
    assert curve.thresholds.tolist() == pytest.approx([0.8, 0.7, 0.6, 0.5])
    assert curve.coverage.tolist() == pytest.approx([1 / 6, 2 / 6, 4 / 6, 1.0])
    # at 0.8 only the last example is answered and it is right; at 0.5 all six, 4 right
    assert curve.accuracy[0] == pytest.approx(1.0)
    assert curve.accuracy[-1] == pytest.approx(4 / 6)
    assert curve.risk.tolist() == pytest.approx((1 - curve.accuracy).tolist())
    t = ev.select_confidence_threshold(correct, conf, target_accuracy=1.0)
    res = ev.evaluate_selective(correct, conf, t)
    assert res.accuracy == pytest.approx(1.0)
    assert res.n_total == 6


def test_calibration_on_real_answers():
    conf = ev.top_probabilities(CHOICES)
    correct = [g == a.choice for g, a in zip(CHOICE_GOLD, CHOICES, strict=True)]
    # top probabilities [0.7, 0.6, 0.5, 0.6, 0.5, 0.8]; correct [1, 1, 0, 1, 0, 1].
    # Five equal bins, (lo, hi]: (0.4, 0.6] holds 0.5, 0.5, 0.6, 0.6 (the 0.6 values sit on
    # the upper edge) with mean 0.55 and observed rate 2/4; (0.6, 0.8] holds 0.7, 0.8 with
    # mean 0.75 and observed rate 2/2. The other three bins are empty.
    table = ev.reliability_table(conf, correct, n_bins=5)
    assert [b.count for b in table] == [0, 0, 4, 2, 0]
    assert table[2].mean_probability == pytest.approx(0.55)
    assert table[2].observed_rate == pytest.approx(0.5)
    assert table[3].mean_probability == pytest.approx(0.75)
    assert table[3].observed_rate == pytest.approx(1.0)
    # ECE = 4/6 * |0.5 - 0.55| + 2/6 * |1.0 - 0.75| = 0.2/6 + 0.5/6 = 0.7/6 = 0.116667
    # (an unweighted mean of the two bins would be 0.15)
    ece = ev.expected_calibration_error(conf, correct, n_bins=5)
    assert ece == pytest.approx(0.7 / 6)
    # Noul answers feed the same functions through their noul value
    nouls = [NoulAnswer(v, SYN) for v in (0.9, 0.8, 0.2, 0.1)]
    assert ev.expected_calibration_error(nouls, [1, 1, 0, 0], n_bins=10) == pytest.approx(
        (0.1 + 0.2 + 0.2 + 0.1) / 4
    )


def test_sum_usage_on_usage_objects_and_decision_result():
    usages = [Usage(10, 5), Usage(None, 7), Usage()]
    totals = ev.sum_usage(usages)
    assert (totals.requests, totals.input_tokens, totals.output_tokens) == (3, 10, 12)
    assert totals.total_tokens == 22
    assert (totals.requests_missing_input, totals.requests_missing_output) == (2, 1)

    results = [
        DecisionResult({"x": NoulAnswer(0.5, SYN)}, "synthetic", Usage(3, 4)),
        DecisionResult({"x": NoulAnswer(0.5, SYN)}, "synthetic"),
    ]
    totals = ev.sum_usage(r.usage for r in results)
    assert (totals.requests, totals.input_tokens, totals.output_tokens) == (2, 3, 4)
    assert (totals.requests_missing_input, totals.requests_missing_output) == (1, 1)


def test_nan_convention_with_real_answers():
    # a class never predicted has undefined precision
    answers = [choice(0.8, 0.1, 0.1), choice(0.7, 0.2, 0.1)]
    per = ev.per_class_metrics(["a", "b"], answers, labels=["a", "b", "c"])
    assert math.isnan(per["b"].precision)
    assert math.isnan(per["c"].recall)


def test_score_level_is_the_most_likely_level_not_the_rounded_expected_score():
    # expected score 0 * 0.5 + 1 * 0.1 + 2 * 0.4 = 0.9, which rounds to 1, but level 0
    # is the most likely one
    a = ScoreAnswer.from_probabilities([0.5, 0.1, 0.4], LEGEND, SYN)
    assert a.score == pytest.approx(0.9)
    assert ev.score_level(a) == 0
    assert ev.exact_agreement([0], [a]) == 1.0
    assert ev.exact_agreement([1], [a]) == 0.0
    assert ev.mean_absolute_error([0], [a]) == pytest.approx(0.9)


def test_choice_metrics_reject_noul_and_score_answers_naming_the_function():
    nouls = [NoulAnswer(0.9, SYN), NoulAnswer(0.2, SYN)]
    scores = [score(0.1, 0.2, 0.7), score(0.6, 0.3, 0.1)]
    with pytest.raises(ValueError, match=r"accuracy.*Noul"):
        ev.accuracy([1, 0], nouls)
    with pytest.raises(ValueError, match=r"accuracy.*Score"):
        ev.accuracy([2, 0], scores)
    with pytest.raises(ValueError, match=r"per_class_metrics.*Noul"):
        ev.per_class_metrics([1, 0], nouls)
    with pytest.raises(ValueError, match=r"per_class_metrics.*Score"):
        ev.per_class_metrics([2, 0], scores)
    with pytest.raises(ValueError, match=r"cohens_kappa.*Score"):
        ev.cohens_kappa([2, 0], scores)
    with pytest.raises(ValueError, match=r"confusion_matrix.*Noul"):
        ev.confusion_matrix([1, 0], nouls)
    with pytest.raises(ValueError, match=r"macro_average.*Noul"):
        ev.macro_average([1, 0], nouls)
    with pytest.raises(ValueError, match=r"micro_average.*Score"):
        ev.micro_average([2, 0], scores)


def test_average_errors_name_the_function_called():
    nouls = [NoulAnswer(0.9, SYN), NoulAnswer(0.2, SYN)]
    scores = [score(0.1, 0.2, 0.7), score(0.6, 0.3, 0.1)]
    for fn in ("macro_average", "micro_average"):
        with pytest.raises(ValueError) as exc:
            getattr(ev, fn)([1, 0], nouls)
        assert fn in str(exc.value) and "per_class_metrics" not in str(exc.value)
        with pytest.raises(ValueError) as exc:
            getattr(ev, fn)(nouls, [1, 0])
        assert fn in str(exc.value) and "per_class_metrics" not in str(exc.value)
        with pytest.raises(ValueError, match=rf"{fn}.*Score"):
            getattr(ev, fn)([2, 0], scores)


def test_choice_confidence_is_documented_as_the_rescaled_top_probability():
    """The wording in the code and the docs: Choice confidence is (p_max - 1/n)/(1 - 1/n)."""
    from pathlib import Path

    doc = (ev.top_probabilities.__doc__ or "").replace("\n", " ")
    docs = (Path(__file__).resolve().parent.parent / "docs" / "evaluation.md").read_text(
        encoding="utf-8"
    )
    for text in (" ".join(doc.split()), " ".join(docs.split())):
        assert "top probability rescaled" in text
        assert "derived from the whole" not in text
        assert "distance-based spread" in text  # Score stays the spread measure
