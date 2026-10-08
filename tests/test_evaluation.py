"""Metric tests. Every expected value is computed by hand in the comment above it."""

from __future__ import annotations

import math
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest

from jev_cookbook import answers as ans
from jev_cookbook import evaluation as ev


@dataclass
class ChoiceStub:
    choice: str
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class ScoreStub:
    score: float
    probabilities: dict[Any, float] = field(default_factory=dict)
    confidence: float = 0.0
    legend: dict[int, str] = field(default_factory=dict)


@dataclass
class NoulStub:
    noul: float


nan = math.isnan

# ---------------------------------------------------------------- Choice
# gold a a a b b c ; pred a a b b c c
G = ["a", "a", "a", "b", "b", "c"]
P = ["a", "a", "b", "b", "c", "c"]


def test_accuracy():
    # matches at positions 0, 1, 3, 5 -> 4 / 6
    assert ev.accuracy(G, P) == pytest.approx(4 / 6)


def test_accuracy_accepts_choice_answers():
    answers = [ChoiceStub(x) for x in P]
    assert ev.accuracy(G, answers) == pytest.approx(4 / 6)


def test_confusion_matrix():
    # gold a: pred a, a, b -> [2, 1, 0]; gold b: pred b, c -> [0, 1, 1]; gold c: pred c -> [0, 0, 1]
    cm = ev.confusion_matrix(G, P)
    assert cm.labels == ["a", "b", "c"]
    assert cm.matrix.tolist() == [[2, 1, 0], [0, 1, 1], [0, 0, 1]]


def test_confusion_matrix_label_order_and_unknown_label():
    cm = ev.confusion_matrix(G, P, labels=["c", "b", "a"])
    assert cm.matrix.tolist() == [[1, 0, 0], [1, 1, 0], [0, 1, 2]]
    with pytest.raises(ValueError):
        ev.confusion_matrix(G, P, labels=["a", "b"])


def test_per_class():
    r = ev.per_class_metrics(G, P)
    # a: TP 2, FP 0, FN 1 -> P 2/2, R 2/3, F1 = 2*2 / (2*2 + 0 + 1) = 4/5
    assert (r["a"].precision, r["a"].recall, r["a"].f1) == pytest.approx((1.0, 2 / 3, 4 / 5))
    # b: TP 1, FP 1 (pos 2), FN 1 (pos 4) -> P 1/2, R 1/2, F1 = 2 / (2 + 1 + 1) = 1/2
    assert (r["b"].precision, r["b"].recall, r["b"].f1) == pytest.approx((0.5, 0.5, 0.5))
    # c: TP 1, FP 1 (pos 4), FN 0 -> P 1/2, R 1, F1 = 2 / (2 + 1 + 0) = 2/3
    assert (r["c"].precision, r["c"].recall, r["c"].f1) == pytest.approx((0.5, 1.0, 2 / 3))
    assert r["a"].support == 3


def test_macro_and_micro():
    # macro P = (1 + 1/2 + 1/2) / 3 = 2/3 ; R = (2/3 + 1/2 + 1) / 3 = (13/6) / 3 = 13/18
    # macro F1 = (4/5 + 1/2 + 2/3) / 3 = (24/30 + 15/30 + 20/30) / 3 = 59/90
    m = ev.macro_average(G, P)
    assert m == pytest.approx({"precision": 2 / 3, "recall": 13 / 18, "f1": 59 / 90})
    # micro: TP 4, FP 2, FN 2 -> P 4/6, R 4/6, F1 = 8 / (8 + 2 + 2) = 2/3 (= accuracy)
    mi = ev.micro_average(G, P)
    assert mi == pytest.approx({"precision": 2 / 3, "recall": 2 / 3, "f1": 2 / 3})


def test_class_with_no_support_and_never_predicted_is_nan_and_skipped_in_macro():
    # label d occurs nowhere: TP = FP = FN = 0, everything undefined
    r = ev.per_class_metrics(G, P, labels=["a", "b", "c", "d"])
    assert nan(r["d"].precision) and nan(r["d"].recall) and nan(r["d"].f1)
    assert not r["d"].present
    # macro skips d, so it equals the three-class value 59/90
    assert ev.macro_average(G, P, labels=["a", "b", "c", "d"])["f1"] == pytest.approx(59 / 90)


def test_class_predicted_but_no_gold_support():
    # gold a a ; pred a b. a: TP 1, FN 1 -> P 1, R 1/2, F1 = 2 / (2 + 0 + 1) = 2/3.
    # b: TP 0, FP 1, FN 0 -> P 0/1 = 0, R undefined (no support), F1 = 0 / (0 + 1 + 0) = 0
    r = ev.per_class_metrics(["a", "a"], ["a", "b"])
    assert r["b"].precision == 0.0 and nan(r["b"].recall) and r["b"].f1 == 0.0
    # macro over a and b, undefined recall counted 0: P (1 + 0)/2, R (1/2 + 0)/2, F1 (2/3 + 0)/2
    assert ev.macro_average(["a", "a"], ["a", "b"]) == pytest.approx(
        {"precision": 0.5, "recall": 0.25, "f1": 1 / 3}
    )


def test_class_never_predicted():
    # gold a b ; pred a a. b: TP 0, FP 0, FN 1 -> P undefined, R 0, F1 0
    r = ev.per_class_metrics(["a", "b"], ["a", "a"])
    assert nan(r["b"].precision) and r["b"].recall == 0.0 and r["b"].f1 == 0.0


def test_micro_with_catch_all_excluded():
    # gold a none none ; pred a a none. Only label a: TP 1, FP 1, FN 0 -> P 1/2, R 1, F1 = 2/3
    mi = ev.micro_average(["a", "none", "none"], ["a", "a", "none"], labels=["a"])
    assert mi == pytest.approx({"precision": 0.5, "recall": 1.0, "f1": 2 / 3})


def test_micro_undefined_is_nan():
    # label a only; gold none none, pred none none: no gold a, no predicted a -> all NaN
    mi = ev.micro_average(["none", "none"], ["none", "none"], labels=["a"])
    assert all(nan(v) for v in mi.values())


def test_macro_with_no_present_label_raises():
    with pytest.raises(ValueError):
        ev.macro_average(["a"], ["a"], labels=["z"])


def test_kappa():
    # p_o = 4/6. gold shares a 3/6 b 2/6 c 1/6 ; pred shares a 2/6 b 2/6 c 2/6
    # p_e = (3*2 + 2*2 + 1*2) / 36 = 12/36 = 1/3 ; kappa = (2/3 - 1/3) / (1 - 1/3) = 1/2
    assert ev.cohens_kappa(G, P) == pytest.approx(0.5)


def test_kappa_perfect_and_below_chance():
    # perfect with two options: p_o = 1, p_e = 1/2 -> (1 - 1/2) / (1/2) = 1
    assert ev.cohens_kappa(["a", "b"], ["a", "b"]) == pytest.approx(1.0)
    # complete disagreement: p_o = 0, p_e = 1/2 -> (0 - 1/2) / (1/2) = -1
    assert ev.cohens_kappa(["a", "b"], ["b", "a"]) == pytest.approx(-1.0)


def test_all_one_label():
    # accuracy 1, kappa has p_e = 1 so is undefined
    assert ev.accuracy(["a", "a"], ["a", "a"]) == 1.0
    assert nan(ev.cohens_kappa(["a", "a"], ["a", "a"]))


# ---------------------------------------------------------------- Noul
NG = [1, 1, 0, 0, 1, 0]
NS = [0.9, 0.6, 0.55, 0.2, 0.4, 0.1]


def test_threshold_point():
    # t = 0.5 -> yes at 0.9, 0.6, 0.55 (gold 1, 1, 0): TP 2, FP 1, FN 1 (0.4), TN 2
    p = ev.evaluate_threshold(NG, NS, 0.5)
    assert (p.tp, p.fp, p.fn, p.tn) == (2, 1, 1, 2)
    assert (p.precision, p.recall, p.f1) == pytest.approx((2 / 3, 2 / 3, 2 / 3))
    # t = 0.6 (equal counts as yes) -> yes at 0.9, 0.6: TP 2, FP 0, FN 1 -> P 1, R 2/3, F1 4/5
    p = ev.evaluate_threshold(NG, NS, 0.6)
    assert (p.precision, p.recall, p.f1) == pytest.approx((1.0, 2 / 3, 4 / 5))


def test_threshold_nothing_predicted_and_no_positives():
    # t = 0.95: no yes. TP 0, FP 0, FN 3 -> P undefined, R 0, F1 = 0 / 3 = 0
    p = ev.evaluate_threshold(NG, NS, 0.95)
    assert nan(p.precision) and p.recall == 0.0 and p.f1 == 0.0
    # no gold yes at all: recall undefined
    q = ev.evaluate_threshold([0, 0], [0.9, 0.1], 0.5)
    assert nan(q.recall) and q.precision == 0.0


def test_threshold_accepts_noul_answers_and_validates():
    p = ev.evaluate_threshold(NG, [NoulStub(v) for v in NS], 0.5)
    assert p.tp == 2
    with pytest.raises(ValueError):
        ev.evaluate_threshold(NG, NS, 1.5)
    with pytest.raises(ValueError):
        ev.evaluate_threshold(NG, [0.9, 0.6, 0.55, 0.2, 0.4, 1.2], 0.5)
    with pytest.raises(ValueError):
        ev.evaluate_threshold([2, 0], [0.5, 0.5], 0.5)


def test_sweep_default_thresholds():
    pts = ev.threshold_sweep(NG, NS)
    assert [p.threshold for p in pts] == [0.1, 0.2, 0.4, 0.55, 0.6, 0.9]
    # F1 = 2 TP / (2 TP + FP + FN):
    # 0.1: TP 3 FP 3 FN 0 -> 6/9 ; 0.2: TP 3 FP 2 -> 6/8 ; 0.4: TP 3 FP 1 -> 6/7
    # 0.55: TP 2 FP 1 FN 1 -> 4/6 ; 0.6: TP 2 FP 0 FN 1 -> 4/5 ; 0.9: TP 1 FP 0 FN 2 -> 2/4
    assert [p.f1 for p in pts] == pytest.approx([6 / 9, 6 / 8, 6 / 7, 4 / 6, 4 / 5, 2 / 4])
    assert [p.recall for p in pts] == pytest.approx([1, 1, 1, 2 / 3, 2 / 3, 1 / 3])


def test_sweep_explicit_thresholds_sorted():
    pts = ev.threshold_sweep(NG, NS, thresholds=[0.6, 0.5])
    assert [p.threshold for p in pts] == [0.5, 0.6]
    with pytest.raises(ValueError):
        ev.threshold_sweep(NG, NS, thresholds=[])


def test_select_threshold_f1():
    # best F1 in the sweep above is 6/7 at threshold 0.4
    assert ev.select_threshold(NG, NS) == 0.4


def test_select_threshold_constrained():
    # precision >= 1.0 holds at 0.9 (recall 1/3) and 0.6 (recall 2/3) -> best recall at 0.6
    assert ev.select_threshold(NG, NS, "recall_at_precision", 1.0) == 0.6
    # recall >= 1.0 holds at 0.1 (P 1/2), 0.2 (P 3/5), 0.4 (P 3/4) -> best precision at 0.4
    assert ev.select_threshold(NG, NS, "precision_at_recall", 1.0) == 0.4


def test_select_threshold_ties_go_to_higher_threshold():
    # gold 1 0 0 1 0 ; noul 0.9 0.7 0.5 0.3 0.1. F1 = 2 TP / (2 TP + FP + FN):
    # 0.1: TP 2 FP 3 -> 4/7 ; 0.3: TP 2 FP 2 FN 0 -> 4/6 ; 0.5: TP 1 FP 2 FN 1 -> 2/5 ;
    # 0.7: TP 1 FP 1 FN 1 -> 2/4 ; 0.9: TP 1 FP 0 FN 1 -> 2/3.
    # 0.3 and 0.9 tie at 2/3, so the higher threshold, 0.9, is chosen.
    gold, noul = [1, 0, 0, 1, 0], [0.9, 0.7, 0.5, 0.3, 0.1]
    pts = {p.threshold: p.f1 for p in ev.threshold_sweep(gold, noul)}
    assert pts[0.3] == pts[0.9]  # the tie really exists
    assert ev.select_threshold(gold, noul) == 0.9


def test_select_threshold_single_candidate():
    # duplicate values leave a single candidate, 0.5
    assert ev.select_threshold([1, 1], [0.5, 0.5]) == 0.5


def test_select_threshold_errors():
    with pytest.raises(ValueError):
        ev.select_threshold(NG, NS, "nonsense")
    with pytest.raises(ValueError):
        ev.select_threshold(NG, NS, "recall_at_precision")  # missing target
    with pytest.raises(ValueError):
        # all gold no: precision is 0 at every threshold, so 0.5 is infeasible
        ev.select_threshold([0, 0], [0.9, 0.1], "recall_at_precision", 0.5)


def test_brier():
    # squared errors: 0.01, 0.16, 0.3025, 0.04, 0.36, 0.01 ; sum 0.8825 ; mean 0.8825 / 6
    assert ev.brier_score(NG, NS) == pytest.approx(0.8825 / 6)
    # always 0.5 gives 0.25 whatever the gold
    assert ev.brier_score([1, 0], [0.5, 0.5]) == pytest.approx(0.25)


def test_noul_confidence():
    # |2p - 1|, pinned at p in {0, 0.25, 0.5, 0.75, 1}
    assert ev.noul_confidence([0.0, 0.25, 0.5, 0.75, 1.0]) == pytest.approx(
        [1.0, 0.5, 0.0, 0.5, 1.0]
    )
    # |2p - 1|: 0.8, 0.6, 0.0
    assert ev.noul_confidence([0.9, 0.2, NoulStub(0.5)]) == pytest.approx([0.8, 0.6, 0.0])


def test_noul_confidence_is_the_choice_formula_at_n_equals_2():
    # https://docs.typesafe.ai/confidence (S03): a Noul's confidence is the Choice formula
    # (p_max - 1/n) / (1 - 1/n) applied to a yes-or-no Choice (n = 2), so noul_confidence(p)
    # must equal jev_cookbook.answers.choice_confidence([p, 1 - p]) for every p.
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert ev.noul_confidence([p])[0] == pytest.approx(ans.choice_confidence([p, 1.0 - p]))


# ---------------------------------------------------------------- Multi-label
MG = [{"x", "y"}, {"x"}, set()]
MP = [{"x"}, {"x", "z"}, set()]


def test_multilabel_metrics():
    r = ev.multilabel_metrics(MG, MP)
    # x: TP 2 FP 0 FN 0 ; y: TP 0 FP 0 FN 1 ; z: TP 0 FP 1 FN 0
    assert (r["per_label"]["x"].precision, r["per_label"]["x"].recall) == (1.0, 1.0)
    assert nan(r["per_label"]["y"].precision) and r["per_label"]["y"].recall == 0.0
    assert r["per_label"]["z"].precision == 0.0 and nan(r["per_label"]["z"].recall)
    # micro: TP 2, FP 1, FN 1 -> P 2/3, R 2/3, F1 = 4 / (4 + 1 + 1) = 2/3
    assert r["micro"] == pytest.approx({"precision": 2 / 3, "recall": 2 / 3, "f1": 2 / 3})
    # macro (undefined counted 0): P (1 + 0 + 0)/3, R (1 + 0 + 0)/3, F1 (1 + 0 + 0)/3
    assert r["macro"] == pytest.approx({"precision": 1 / 3, "recall": 1 / 3, "f1": 1 / 3})


def test_multilabel_labels_restrict_and_absent_label():
    r = ev.multilabel_metrics(MG, MP, labels=["x", "unused"])
    assert not r["per_label"]["unused"].present
    # macro covers only x: all 1
    assert r["macro"]["f1"] == 1.0
    with pytest.raises(ValueError):
        ev.multilabel_metrics([set()], [set()])  # no label present anywhere


def test_exact_set_match():
    # position 0: {x,y} vs {x} no; 1: {x} vs {x,z} no; 2: {} vs {} yes -> 1/3
    assert ev.exact_set_match(MG, MP) == pytest.approx(1 / 3)
    with pytest.raises(ValueError):
        ev.exact_set_match(["ab"], [{"a"}])  # a bare string is not a label collection


def test_multilabel_from_noul():
    noul = {"x": [0.9, NoulStub(0.2)], "y": [0.4, 0.8]}
    # thresholds x 0.5, y 0.5: example 0 -> x (0.9), not y (0.4); example 1 -> y only
    assert ev.multilabel_from_noul(noul, {"x": 0.5, "y": 0.5}) == [{"x"}, {"y"}]
    # single threshold 0.3: example 0 -> x, y ; example 1 -> y (x 0.2 < 0.3)
    assert ev.multilabel_from_noul(noul, 0.3) == [{"x", "y"}, {"y"}]
    with pytest.raises(ValueError):
        ev.multilabel_from_noul(noul, {"x": 0.5})


# ---------------------------------------------------------------- Score and ranking
SGOLD = [1, 2, 3, 4]
SPRED = [
    ScoreStub(1.4, {"1": 0.6, "2": 0.4}),
    ScoreStub(2.5, {"2": 0.5, "3": 0.5}),  # tie -> lowest level 2
    ScoreStub(3.0, {"3": 1.0}),
    ScoreStub(3.3, {"3": 0.7, "4": 0.3}),
]


def test_score_level():
    assert [ev.score_level(a) for a in SPRED] == [1, 2, 3, 3]
    assert ev.score_level(2.5) == 2.5


def test_exact_agreement():
    # modal levels 1 2 3 3 vs gold 1 2 3 4 -> 3 / 4 ; within one level 4 / 4
    assert ev.exact_agreement(SGOLD, SPRED) == pytest.approx(0.75)
    assert ev.exact_agreement(SGOLD, SPRED, tolerance=1) == 1.0
    assert ev.exact_agreement([1, 2], [1, 3]) == 0.5  # plain numbers
    with pytest.raises(ValueError):
        ev.exact_agreement([1], [1], tolerance=-1)


def test_mean_absolute_error():
    # expected scores 1.4 2.5 3.0 3.3 vs 1 2 3 4: 0.4 + 0.5 + 0 + 0.7 = 1.6 ; / 4 = 0.4
    assert ev.mean_absolute_error(SGOLD, SPRED) == pytest.approx(0.4)
    assert ev.mean_absolute_error([1, 2], [2, 4]) == pytest.approx(1.5)  # (1 + 2) / 2


def test_ndcg_hand_values():
    rel = [3, 2, 0, 1]
    # rel sorted descending (3, 2, 1, 0) ranked in that order is the ideal order -> 1
    assert ev.ndcg([3, 2, 1, 0], [0.9, 0.8, 0.7, 0.6]) == pytest.approx(1.0)
    # reversed scores order items rel 1, 0, 2, 3 :
    #   DCG = 1/log2(2) + 0/log2(3) + 2/log2(4) + 3/log2(5) = 1 + 0 + 1 + 3/log2(5)
    # ideal order 3, 2, 1, 0 : IDCG = 3/log2(2) + 2/log2(3) + 1/log2(4) + 0 = 3 + 2/log2(3) + 1/2
    dcg = 1 + 0 + 1 + 3 / math.log2(5)
    idcg = 3 + 2 / math.log2(3) + 0.5
    assert ev.ndcg(rel, [0.6, 0.7, 0.8, 0.9]) == pytest.approx(dcg / idcg)
    # at k = 2: DCG = 1 + 0 = 1 ; IDCG = 3 + 2/log2(3)
    assert ev.ndcg(rel, [0.6, 0.7, 0.8, 0.9], k=2) == pytest.approx(1 / (3 + 2 / math.log2(3)))


def test_ndcg_exponential_gain():
    # gains 2^r - 1 : rel [1, 0] ranked worst-first: DCG = 0/log2(2) + 1/log2(3) ; IDCG = 1
    assert ev.ndcg([1, 0], [0.1, 0.9], gain="exponential") == pytest.approx(1 / math.log2(3))
    # rel [3, 0]: gains 7 and 0, ranked best-first -> 1 exactly
    assert ev.ndcg([3, 0], [0.9, 0.1], gain="exponential") == pytest.approx(1.0)


def test_ndcg_ties_use_average_gain_and_ignore_input_order():
    # rel [1, 0], equal scores: positions 1, 2 each get 0.5.
    # DCG = 0.5 / log2(2) + 0.5 / log2(3) ; IDCG = 1
    expected = 0.5 + 0.5 / math.log2(3)
    assert ev.ndcg([1, 0], [0.5, 0.5]) == pytest.approx(expected)
    assert ev.ndcg([0, 1], [0.5, 0.5]) == pytest.approx(expected)


def test_ndcg_undefined_and_errors():
    assert nan(ev.ndcg([0, 0], [0.1, 0.2]))  # IDCG = 0
    with pytest.raises(ValueError):
        ev.ndcg([-1, 0], [1, 2])
    with pytest.raises(ValueError):
        ev.ndcg([1, 0], [1, 2], k=0)
    with pytest.raises(ValueError):
        ev.ndcg([1, 0], [1, 2], gain="bad")


def test_ndcg_accepts_score_answers():
    assert ev.ndcg([1, 0], [ScoreStub(2.0), ScoreStub(1.0)]) == pytest.approx(1.0)


def test_mean_ndcg_skips_undefined_lists():
    rel = [3, 2, 0, 1]
    q_perfect = ([3, 2, 1, 0], [0.9, 0.8, 0.7, 0.6])  # nDCG 1
    q_reverse = (rel, [0.6, 0.7, 0.8, 0.9])  # nDCG = dcg / idcg from the test above
    q_zero = ([0, 0], [1, 2])  # undefined, skipped
    value = ev.mean_ndcg([q_perfect, q_reverse, q_zero])
    dcg = 1 + 0 + 1 + 3 / math.log2(5)
    idcg = 3 + 2 / math.log2(3) + 0.5
    assert value == pytest.approx((1.0 + dcg / idcg) / 2)
    assert nan(ev.mean_ndcg([q_zero]))


def test_top_k_accuracy():
    probs = [{"1": 0.6, "2": 0.4}, {"2": 0.5, "3": 0.5}, {"3": 1.0}, {"3": 0.7, "4": 0.3}]
    # k = 1: gold 1 is top -> 1 ; gold 2 tied with 3 for one slot -> 1/2 ; gold 3 -> 1 ;
    # gold 4 is below 3 -> 0 ; total 2.5 / 4
    assert ev.top_k_accuracy(SGOLD, probs, k=1) == pytest.approx(2.5 / 4)
    # k = 2: every gold is within the top two -> 1
    assert ev.top_k_accuracy(SGOLD, probs, k=2) == pytest.approx(1.0)
    # answers work too, and uniform over 4 options with k = 2 gives 2/4
    uniform = ChoiceStub("a", {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25})
    assert ev.top_k_accuracy(["c"], [uniform], k=2) == pytest.approx(0.5)


def test_top_k_errors():
    with pytest.raises(ValueError):
        ev.top_k_accuracy(["z"], [{"a": 1.0}], k=1)
    with pytest.raises(ValueError):
        ev.top_k_accuracy(["a"], [{"a": 1.0}], k=0)


def test_top_probabilities():
    assert ev.top_probabilities(SPRED) == pytest.approx([0.6, 0.5, 1.0, 0.7])
    with pytest.raises(ValueError):
        ev.top_probabilities([NoulStub(0.5)])


def test_recall_at_budget():
    rel = [1, 0, 1, 0, 1]
    # top 3 by score are positions 0, 1, 2 -> relevant found 2 of 3
    assert ev.recall_at_budget(rel, [0.9, 0.8, 0.7, 0.6, 0.5], 3) == pytest.approx(2 / 3)
    # all five tied, budget 2: expected relevant found = 2 * 3/5 = 1.2 ; / 3 = 0.4
    assert ev.recall_at_budget(rel, [0.5] * 5, 2) == pytest.approx(0.4)
    # budget beyond the list is the whole list
    assert ev.recall_at_budget(rel, [0.9, 0.8, 0.7, 0.6, 0.5], 99) == pytest.approx(1.0)
    # no relevant item: undefined
    assert nan(ev.recall_at_budget([0, 0], [0.1, 0.2], 1))
    # Noul answers as scores
    assert ev.recall_at_budget([1, 0], [NoulStub(0.9), NoulStub(0.1)], 1) == 1.0
    with pytest.raises(ValueError):
        ev.recall_at_budget(rel, [0.5] * 5, 0)


# ---------------------------------------------------------------- Selective prediction
SC = [1, 1, 0, 1, 0]
SF = [0.9, 0.8, 0.7, 0.6, 0.5]


def test_selective_curve():
    c = ev.selective_curve(SC, SF)
    assert c.thresholds.tolist() == [0.9, 0.8, 0.7, 0.6, 0.5]
    # answered 1..5 items; correct among them 1, 2, 2, 3, 3
    assert c.coverage == pytest.approx([1 / 5, 2 / 5, 3 / 5, 4 / 5, 1.0])
    assert c.accuracy == pytest.approx([1, 1, 2 / 3, 3 / 4, 3 / 5])
    assert c.risk == pytest.approx([0, 0, 1 / 3, 1 / 4, 2 / 5])


def test_selective_curve_ties_enter_together():
    # confidence 0.9 0.9 0.5 correct 1 0 1 : at 0.9 two answered, one right -> 0.5 ; at 0.5 all -> 2/3
    c = ev.selective_curve([1, 0, 1], [0.9, 0.9, 0.5])
    assert c.coverage == pytest.approx([2 / 3, 1.0])
    assert c.accuracy == pytest.approx([0.5, 2 / 3])


def test_select_confidence_threshold():
    # accuracy >= 0.75 at 0.9, 0.8 and 0.6 (3/4) -> lowest such threshold 0.6
    assert ev.select_confidence_threshold(SC, SF, target_accuracy=0.75) == 0.6
    # coverage >= 0.6: thresholds 0.7, 0.6, 0.5 with accuracy 2/3, 3/4, 3/5 -> 0.6
    assert ev.select_confidence_threshold(SC, SF, min_coverage=0.6) == 0.6


def test_select_confidence_threshold_coverage_tie_goes_to_lower_threshold():
    # correct 1 0 0 1 ; confidence 0.9 0.8 0.7 0.6 ; accuracy of the answered subset:
    # 0.9: 1/1 ; 0.8: 1/2 ; 0.7: 1/3 ; 0.6: 2/4. With min_coverage 0.5 the candidates are
    # 0.8 (coverage 2/4), 0.7, 0.6. Best accuracy 1/2 ties at 0.8 and 0.6 -> lower, 0.6.
    c = ev.selective_curve([1, 0, 0, 1], [0.9, 0.8, 0.7, 0.6])
    assert c.accuracy[1] == c.accuracy[3] == 0.5  # the tie really exists
    assert (
        ev.select_confidence_threshold([1, 0, 0, 1], [0.9, 0.8, 0.7, 0.6], min_coverage=0.5) == 0.6
    )


def test_select_confidence_threshold_errors():
    with pytest.raises(ValueError):
        ev.select_confidence_threshold(SC, SF)
    with pytest.raises(ValueError):
        ev.select_confidence_threshold(SC, SF, target_accuracy=0.5, min_coverage=0.5)
    with pytest.raises(ValueError):
        ev.select_confidence_threshold([0, 0], [0.9, 0.1], target_accuracy=0.5)


def test_evaluate_selective():
    # threshold 0.75 answers 0.9 and 0.8, both right: coverage 2/5, accuracy 1, risk 0
    r = ev.evaluate_selective(SC, SF, 0.75)
    assert (r.n_answered, r.n_total) == (2, 5)
    assert (r.coverage, r.accuracy, r.risk) == pytest.approx((0.4, 1.0, 0.0))
    # nothing answered: accuracy and risk undefined
    r = ev.evaluate_selective(SC, SF, 0.95)
    assert r.n_answered == 0 and r.coverage == 0.0 and nan(r.accuracy) and nan(r.risk)


def test_selective_rejects_noul_answers_with_a_pointer_to_noul_confidence():
    with pytest.raises(ValueError, match="noul_confidence"):
        ev.selective_curve([1, 0], [NoulStub(0.9), NoulStub(0.4)])
    with pytest.raises(ValueError, match="noul_confidence"):
        ev.evaluate_selective([1, 0], [NoulStub(0.9), NoulStub(0.4)], 0.5)
    # the documented path works: confidence |2p - 1| = 0.8, 0.2
    assert ev.selective_curve(
        [1, 0], ev.noul_confidence([NoulStub(0.9), NoulStub(0.4)])
    ).coverage.tolist() == [0.5, 1.0]


def test_selective_reads_confidence_from_answers():
    answers = [ChoiceStub("a", confidence=c) for c in SF]
    assert ev.evaluate_selective(SC, answers, 0.75).n_answered == 2


# ---------------------------------------------------------------- Calibration
CP = [0.1, 0.3, 0.35, 0.8, 0.95, 1.0]
CO = [0, 0, 1, 1, 1, 0]


def test_reliability_table():
    t = ev.reliability_table(CP, CO, n_bins=2)
    # bin (0, 0.5]: 0.1 0.3 0.35 -> mean 0.75 / 3 = 0.25, outcomes 0 0 1 -> rate 1/3
    assert (t[0].count, t[0].mean_probability, t[0].observed_rate) == pytest.approx(
        (3, 0.25, 1 / 3)
    )
    # bin (0.5, 1]: 0.8 0.95 1.0 -> mean 2.75 / 3, outcomes 1 1 0 -> rate 2/3
    assert (t[1].count, t[1].mean_probability, t[1].observed_rate) == pytest.approx(
        (3, 2.75 / 3, 2 / 3)
    )


def test_ece():
    # 0.5 * |1/3 - 0.25| + 0.5 * |2/3 - 2.75/3| = 0.5 * 1/12 + 0.5 * 0.25 = 1/24 + 1/8 = 1/6
    assert ev.expected_calibration_error(CP, CO, n_bins=2) == pytest.approx(1 / 6)


def test_ece_weights_bins_by_count():
    # probability 0.1 0.2 0.9 ; outcome 0 1 1 ; 2 bins.
    # bin (0, 0.5]: 0.1, 0.2 -> mean 0.15, rate 1/2, gap 0.35, weight 2/3
    # bin (0.5, 1]: 0.9 -> mean 0.9, rate 1, gap 0.1, weight 1/3
    # ECE = 2/3 * 0.35 + 1/3 * 0.1 = 0.8 / 3 ; an unweighted bin mean would be 0.225
    assert ev.expected_calibration_error([0.1, 0.2, 0.9], [0, 1, 1], n_bins=2) == pytest.approx(
        0.8 / 3
    )


def test_ece_perfectly_calibrated_is_zero():
    # four items at 0.5, two right: bin mean 0.5, rate 0.5 -> 0
    assert ev.expected_calibration_error([0.5] * 4, [1, 1, 0, 0]) == pytest.approx(0.0)


def test_bin_edges_and_empty_bins():
    # 0.7 * 10 is 7.000000000000001 in floating point but belongs to bin (0.6, 0.7], index 6
    t = ev.reliability_table([0.7, 0.0, 1.0], [1, 0, 1], n_bins=10)
    assert [b.count for b in t] == [1, 0, 0, 0, 0, 0, 1, 0, 0, 1]  # 0.0 -> first bin, 1.0 -> last
    assert nan(t[1].mean_probability) and nan(t[1].observed_rate)
    with pytest.raises(ValueError):
        ev.reliability_table(CP, CO, n_bins=0)


def test_calibration_accepts_noul_answers():
    t = ev.reliability_table([NoulStub(0.5)] * 2, [1, 0], n_bins=2)
    assert t[0].count == 2


# ---------------------------------------------------------------- Bootstrap
def test_bootstrap_constant_difference_has_degenerate_interval():
    # every difference is 1, so every resampled mean is 1
    r = ev.paired_bootstrap_difference([1, 1, 1, 1], [0, 0, 0, 0], seed=0, n_resamples=200)
    assert (r.difference, r.lower, r.upper) == (1.0, 1.0, 1.0)


def test_bootstrap_single_example():
    r = ev.paired_bootstrap_difference([3], [1], seed=5, n_resamples=10)
    assert (r.difference, r.lower, r.upper) == (2.0, 2.0, 2.0)


def test_bootstrap_difference_and_interval_bounds():
    # d = [1, 0, 0, 1] -> mean 2/4 = 0.5; every resampled mean is a multiple of 1/4 in [0, 1]
    r = ev.paired_bootstrap_difference([1, 0, 1, 1], [0, 0, 1, 0], seed=1, n_resamples=500)
    assert r.difference == pytest.approx(0.5)
    assert 0.0 <= r.lower <= 0.5 <= r.upper <= 1.0
    assert (r.n, r.n_resamples, r.seed, r.confidence_level) == (4, 500, 1, 0.95)


def test_bootstrap_interval_follows_confidence_level():
    # d = [1, 0, 0, 1]; a resampled mean is Binomial(4, 1/2) / 4, so with
    # P(0) = 1/16 = 6.25% > 2.5% and P(1) = 6.25% > 2.5% the 95% interval is (0, 1).
    # CDF: P(<= 0) = 1/16, P(<= 1/4) = 5/16 = 31.25%, P(<= 1/2) = 11/16, P(<= 3/4) = 15/16 = 93.75%.
    # So the 25th percentile is 1/4 (5/16 >= 25% > 1/16) and the 75th is 3/4 (11/16 < 75% <= 15/16),
    # giving the 50% interval (0.25, 0.75).
    a, b = [1, 0, 1, 1], [0, 0, 1, 0]
    r95 = ev.paired_bootstrap_difference(a, b, seed=0, n_resamples=20000)
    assert (r95.lower, r95.upper) == (0.0, 1.0)
    r50 = ev.paired_bootstrap_difference(a, b, seed=0, n_resamples=20000, confidence_level=0.5)
    assert (r50.lower, r50.upper) == (0.25, 0.75)


def test_bootstrap_is_deterministic_and_seed_dependent():
    a, b = list(np.arange(30) % 3), list(np.arange(30) % 2)
    r1 = ev.paired_bootstrap_difference(a, b, seed=7, n_resamples=300)
    r2 = ev.paired_bootstrap_difference(a, b, seed=7, n_resamples=300)
    r3 = ev.paired_bootstrap_difference(a, b, seed=8, n_resamples=300)
    assert r1 == r2
    assert (r1.lower, r1.upper) != (r3.lower, r3.upper)


def test_bootstrap_validates_settings():
    with pytest.raises(ValueError):
        ev.paired_bootstrap_difference([1], [0], seed=0, confidence_level=1.0)
    with pytest.raises(ValueError):
        ev.paired_bootstrap_difference([1], [0], seed=0, n_resamples=0)
    with pytest.raises(TypeError):
        ev.paired_bootstrap_difference([1], [0])  # type: ignore[call-arg]


# ---------------------------------------------------------------- Accounting
def test_sum_usage():
    usages = [
        {"input_tokens": 10, "output_tokens": 3},
        {"input_tokens": 5, "output_tokens": None},
        None,
        {"input_tokens": 1},
    ]
    u = ev.sum_usage(usages)
    # input 10 + 5 + 1 = 16 ; output 3 ; total 19 ; output missing in blocks 2, 3, 4 ; input in 3
    assert (u.requests, u.input_tokens, u.output_tokens, u.total_tokens) == (4, 16, 3, 19)
    assert (u.requests_missing_input, u.requests_missing_output) == (1, 3)


def test_sum_usage_accepts_attribute_objects_and_rejects_bad_counts():
    @dataclass
    class U:
        input_tokens: int | None = None
        output_tokens: int | None = None

    u = ev.sum_usage([U(2, 4), U(1, None)])
    assert (u.input_tokens, u.output_tokens, u.requests_missing_output) == (3, 4, 1)
    with pytest.raises(ValueError):
        ev.sum_usage([{"input_tokens": -1, "output_tokens": 0}])
    with pytest.raises(ValueError):
        ev.sum_usage([{"input_tokens": 1.5}])


# ---------------------------------------------------------------- Empty input and length mismatch
EMPTY_CALLS = {
    "accuracy": lambda: ev.accuracy([], []),
    "confusion_matrix": lambda: ev.confusion_matrix([], []),
    "per_class_metrics": lambda: ev.per_class_metrics([], []),
    "macro_average": lambda: ev.macro_average([], []),
    "micro_average": lambda: ev.micro_average([], []),
    "cohens_kappa": lambda: ev.cohens_kappa([], []),
    "evaluate_threshold": lambda: ev.evaluate_threshold([], [], 0.5),
    "threshold_sweep": lambda: ev.threshold_sweep([], []),
    "select_threshold": lambda: ev.select_threshold([], []),
    "brier_score": lambda: ev.brier_score([], []),
    "noul_confidence": lambda: ev.noul_confidence([]),
    "multilabel_from_noul": lambda: ev.multilabel_from_noul({}, 0.5),
    "multilabel_from_noul_values": lambda: ev.multilabel_from_noul({"x": []}, 0.5),
    "multilabel_metrics": lambda: ev.multilabel_metrics([], []),
    "exact_set_match": lambda: ev.exact_set_match([], []),
    "score_level": lambda: ev.score_level(ScoreStub(1.0, {})),
    "exact_agreement": lambda: ev.exact_agreement([], []),
    "mean_absolute_error": lambda: ev.mean_absolute_error([], []),
    "ndcg": lambda: ev.ndcg([], []),
    "mean_ndcg": lambda: ev.mean_ndcg([]),
    "top_probabilities": lambda: ev.top_probabilities([]),
    "top_k_accuracy": lambda: ev.top_k_accuracy([], [], 1),
    "recall_at_budget": lambda: ev.recall_at_budget([], [], 1),
    "selective_curve": lambda: ev.selective_curve([], []),
    "select_confidence_threshold": lambda: ev.select_confidence_threshold(
        [], [], target_accuracy=0.5
    ),
    "evaluate_selective": lambda: ev.evaluate_selective([], [], 0.5),
    "reliability_table": lambda: ev.reliability_table([], []),
    "expected_calibration_error": lambda: ev.expected_calibration_error([], []),
    "paired_bootstrap_difference": lambda: ev.paired_bootstrap_difference([], [], seed=0),
    "sum_usage": lambda: ev.sum_usage([]),
}


@pytest.mark.parametrize("name", sorted(EMPTY_CALLS))
def test_empty_input_raises(name):
    with pytest.raises(ValueError):
        EMPTY_CALLS[name]()


def test_every_public_function_has_an_empty_input_test():
    # score_level is the only function whose "empty" input is an answer with no probabilities;
    # classes and protocols are not metrics.
    functions = {
        n
        for n in ev.__all__
        if callable(getattr(ev, n)) and n[0].islower() and not isinstance(getattr(ev, n), type)
    }
    covered = {n.removesuffix("_values") for n in EMPTY_CALLS}
    assert functions <= covered, sorted(functions - covered)


MISMATCH_CALLS = {
    "accuracy": lambda: ev.accuracy([1], [1, 2]),
    "confusion_matrix": lambda: ev.confusion_matrix([1], [1, 2]),
    "per_class_metrics": lambda: ev.per_class_metrics([1], [1, 2]),
    "cohens_kappa": lambda: ev.cohens_kappa([1], [1, 2]),
    "evaluate_threshold": lambda: ev.evaluate_threshold([1], [0.5, 0.5], 0.5),
    "brier_score": lambda: ev.brier_score([1], [0.5, 0.5]),
    "exact_set_match": lambda: ev.exact_set_match([{1}], [{1}, {2}]),
    "exact_agreement": lambda: ev.exact_agreement([1], [1, 2]),
    "mean_absolute_error": lambda: ev.mean_absolute_error([1], [1, 2]),
    "ndcg": lambda: ev.ndcg([1], [1, 2]),
    "top_k_accuracy": lambda: ev.top_k_accuracy([1], [{1: 1.0}, {1: 1.0}], 1),
    "recall_at_budget": lambda: ev.recall_at_budget([1], [1, 2], 1),
    "selective_curve": lambda: ev.selective_curve([1], [0.5, 0.5]),
    "reliability_table": lambda: ev.reliability_table([0.5], [1, 0]),
    "paired_bootstrap_difference": lambda: ev.paired_bootstrap_difference([1], [1, 2], seed=0),
}


@pytest.mark.parametrize("name", sorted(MISMATCH_CALLS))
def test_length_mismatch_raises(name):
    with pytest.raises(ValueError):
        MISMATCH_CALLS[name]()


def test_import_does_not_pull_in_sdk():
    # A fresh interpreter: other test modules may legitimately import the SDK
    # into this process, which says nothing about what evaluation itself imports.
    code = (
        "import sys, jev_cookbook.evaluation; "
        "assert 'typesafe_sdk' not in sys.modules "
        "and not any(m.startswith('typesafe') for m in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
