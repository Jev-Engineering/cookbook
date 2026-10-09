"""Metric tests. Every expected value is computed by hand in the comment above it."""

from __future__ import annotations

import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from jev_cookbook import answers as ans
from jev_cookbook import evaluation as ev
from jev_cookbook import get_backend, load_helpers
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

REPO = Path(__file__).resolve().parent.parent


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


def test_noul_confidence_is_mirror_symmetric_and_bit_exact_with_choice():
    # 2 * max(p, 1 - p) - 1 must be exactly mirror-symmetric (f(p) == f(1 - p), where
    # "1 - p" is computed, not a separately-rounded decimal literal that only looks like
    # the mirror) and bit-for-bit equal to choice_confidence([p, 1 - p]) at n = 2, over
    # every two-decimal probability 0.00..1.00. abs(2p - 1) fails both: it differs from
    # its computed mirror by up to 1 ULP (e.g. p = 0.2 vs computed 1 - 0.2), which this
    # test is designed to catch.
    grid = [round(i * 0.01, 2) for i in range(101)]
    mirror_grid = [1.0 - p for p in grid]  # computed complement, not a grid literal
    values = ev.noul_confidence(grid)
    mirror_values = ev.noul_confidence(mirror_grid)
    assert values == mirror_values, "not exactly mirror-symmetric about p = 0.5"
    for p, v in zip(grid, values, strict=True):
        assert v == ans.choice_confidence([p, 1.0 - p]), f"not bit-exact at p={p}"


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


# ---------------------------------------------------------------- Multi-label pooling
#
# The reference functions below are copied verbatim (behaviourally) from a multi-label Noul
# recipe's hand-rolled notebook helpers, so this file imports nothing from a recipe folder.
# ``pooled_correct_and_confidence`` pools (example, label) decisions into flat correct and
# confidence arrays; ``tally_outcomes`` tallies the rule's own three-path outcomes. These tests
# check jev_cookbook.evaluation's shared replacements give identical numbers on the same data.

_POOL_LABELS = ("pricing", "reliability")


def _pooled_correct_and_confidence(gold_by_label, noul_by_label, thresholds):
    correct, confidence = [], []
    for label in _POOL_LABELS:
        gold = gold_by_label[label]
        noul = noul_by_label[label]
        threshold = thresholds[label]
        correct.extend((v >= threshold) == g for v, g in zip(noul, gold, strict=True))
        confidence.extend(ev.noul_confidence(noul))
    return correct, confidence


@dataclass
class _LabelDecision:
    tag: bool
    outcome: str  # "yes", "no", or "uncertain"


def _tally_outcomes(example_ids, results, gold_by_id):
    total = answered = right = 0
    for e in example_ids:
        decisions = results[e]
        gold = gold_by_id[e]
        for label in _POOL_LABELS:
            total += 1
            decision = decisions[label]
            if decision.outcome == "uncertain":
                continue
            answered += 1
            right += decision.tag == (label in gold)
    coverage = answered / total
    accuracy = right / answered if answered else float("nan")
    return total, answered, coverage, accuracy, 1.0 - accuracy


_POOL_IDS = ["e1", "e2", "e3", "e4"]
_POOL_GOLD_BY_LABEL = {"pricing": [1, 0, 1, 0], "reliability": [0, 1, 1, 0]}
_POOL_NOUL_BY_LABEL = {
    "pricing": [0.9, 0.3, 0.6, 0.2],
    "reliability": [0.4, 0.8, 0.95, 0.1],
}
_POOL_THRESHOLDS = {"pricing": 0.5, "reliability": 0.5}


def test_pool_label_decisions_matches_the_hand_rolled_pooling_reference():
    ref_correct, ref_confidence = _pooled_correct_and_confidence(
        _POOL_GOLD_BY_LABEL, _POOL_NOUL_BY_LABEL, _POOL_THRESHOLDS
    )
    correct, confidence, keys = ev.pool_label_decisions(
        _POOL_IDS, _POOL_LABELS, _POOL_GOLD_BY_LABEL, _POOL_NOUL_BY_LABEL, _POOL_THRESHOLDS
    )
    assert correct == ref_correct
    assert confidence == pytest.approx(ref_confidence)
    assert len(keys) == len(correct) == len(_POOL_IDS) * len(_POOL_LABELS)
    # pooled label-major, example-minor: the first len(ids) keys are all the first label
    assert keys[: len(_POOL_IDS)] == [(i, "pricing") for i in _POOL_IDS]
    assert keys[len(_POOL_IDS) :] == [(i, "reliability") for i in _POOL_IDS]


def test_pool_label_decisions_single_threshold_for_every_label():
    correct, confidence, _ = ev.pool_label_decisions(
        _POOL_IDS, _POOL_LABELS, _POOL_GOLD_BY_LABEL, _POOL_NOUL_BY_LABEL, 0.5
    )
    ref_correct, ref_confidence = _pooled_correct_and_confidence(
        _POOL_GOLD_BY_LABEL, _POOL_NOUL_BY_LABEL, _POOL_THRESHOLDS
    )
    assert correct == ref_correct
    assert confidence == pytest.approx(ref_confidence)


def test_pool_label_decisions_errors():
    with pytest.raises(ValueError):
        ev.pool_label_decisions([], _POOL_LABELS, _POOL_GOLD_BY_LABEL, _POOL_NOUL_BY_LABEL, 0.5)
    with pytest.raises(ValueError):  # missing label
        ev.pool_label_decisions(
            _POOL_IDS, ("pricing", "missing"), _POOL_GOLD_BY_LABEL, _POOL_NOUL_BY_LABEL, 0.5
        )
    with pytest.raises(ValueError):  # missing threshold
        ev.pool_label_decisions(
            _POOL_IDS, _POOL_LABELS, _POOL_GOLD_BY_LABEL, _POOL_NOUL_BY_LABEL, {"pricing": 0.5}
        )
    with pytest.raises(ValueError):  # threshold out of range
        ev.pool_label_decisions(
            _POOL_IDS, _POOL_LABELS, _POOL_GOLD_BY_LABEL, _POOL_NOUL_BY_LABEL, 1.5
        )
    with pytest.raises(ValueError):  # length mismatch
        ev.pool_label_decisions(
            _POOL_IDS[:-1], _POOL_LABELS, _POOL_GOLD_BY_LABEL, _POOL_NOUL_BY_LABEL, 0.5
        )


def _confidence_cutoff_decisions(confidence_cutoff):
    """The decide_tags-style three-path decisions a confidence-only multi-label rule makes,
    for every example and label, at a given confidence cutoff."""
    results = {}
    for i, e in enumerate(_POOL_IDS):
        decisions = {}
        for label in _POOL_LABELS:
            noul = _POOL_NOUL_BY_LABEL[label][i]
            tag = noul >= _POOL_THRESHOLDS[label]
            confidence = ev.noul_confidence([noul])[0]
            outcome = "uncertain" if confidence < confidence_cutoff else ("yes" if tag else "no")
            decisions[label] = _LabelDecision(tag, outcome)
        results[e] = decisions
    return results


_POOL_GOLD_BY_ID = {
    e: {label for label in _POOL_LABELS if _POOL_GOLD_BY_LABEL[label][i]}
    for i, e in enumerate(_POOL_IDS)
}


def test_pool_label_outcomes_matches_the_hand_rolled_tally_reference():
    results = _confidence_cutoff_decisions(confidence_cutoff=0.5)
    ref = _tally_outcomes(_POOL_IDS, results, _POOL_GOLD_BY_ID)

    accepted_by_label = {
        label: [results[e][label].outcome != "uncertain" for e in _POOL_IDS]
        for label in _POOL_LABELS
    }
    tag_by_label = {label: [results[e][label].tag for e in _POOL_IDS] for label in _POOL_LABELS}
    accepted, correct, keys = ev.pool_label_outcomes(
        _POOL_IDS, _POOL_LABELS, _POOL_GOLD_BY_LABEL, accepted_by_label, tag_by_label
    )
    result = ev.evaluate_outcomes(accepted, correct)
    assert (result.n_total, result.n_answered) == (ref[0], ref[1])
    assert result.coverage == pytest.approx(ref[2])
    assert result.accuracy == pytest.approx(ref[3])
    assert result.risk == pytest.approx(ref[4])
    assert len(keys) == len(accepted) == len(_POOL_IDS) * len(_POOL_LABELS)


def test_pool_label_outcomes_matches_at_a_second_cutoff_with_some_uncertain():
    # A stricter cutoff sends more (example, label) pairs to "uncertain": re-run the identity
    # check so the agreement is not a coincidence of one confidence_cutoff.
    results = _confidence_cutoff_decisions(confidence_cutoff=0.8)
    ref = _tally_outcomes(_POOL_IDS, results, _POOL_GOLD_BY_ID)
    assert ref[1] < len(_POOL_IDS) * len(_POOL_LABELS)  # at least one pair is uncertain

    accepted_by_label = {
        label: [results[e][label].outcome != "uncertain" for e in _POOL_IDS]
        for label in _POOL_LABELS
    }
    tag_by_label = {label: [results[e][label].tag for e in _POOL_IDS] for label in _POOL_LABELS}
    accepted, correct, _ = ev.pool_label_outcomes(
        _POOL_IDS, _POOL_LABELS, _POOL_GOLD_BY_LABEL, accepted_by_label, tag_by_label
    )
    result = ev.evaluate_outcomes(accepted, correct)
    assert (result.n_total, result.n_answered) == (ref[0], ref[1])
    assert result.coverage == pytest.approx(ref[2])
    assert result.accuracy == pytest.approx(ref[3])


def test_pool_label_outcomes_errors():
    by_label = {label: [True, False] for label in _POOL_LABELS}
    with pytest.raises(ValueError):
        ev.pool_label_outcomes([], _POOL_LABELS, by_label, by_label, by_label)
    with pytest.raises(ValueError):  # missing from one of the three mappings
        ev.pool_label_outcomes(
            ["a", "b"], _POOL_LABELS, by_label, {"pricing": [True, False]}, by_label
        )
    with pytest.raises(ValueError):  # length mismatch
        ev.pool_label_outcomes(["a", "b", "c"], _POOL_LABELS, by_label, by_label, by_label)


# ---------------------------------------------------------------- Choice with an acceptable set
_FB_GOLD_SETS = [{"keep"}, {"x"}, {"keep"}, {"x", "keep"}, {"y"}]
_FB_CHOICES = ["keep", "x", "x", "keep", "y"]


def test_set_agreement():
    # position 0: keep in {keep} yes; 1: x in {x} yes; 2: x in {keep} no; 3: keep in {x,keep}
    # yes; 4: y in {y} yes -> 4/5
    assert ev.set_agreement(_FB_GOLD_SETS, _FB_CHOICES) == pytest.approx(4 / 5)
    assert ev.set_agreement([{"a"}], [ChoiceStub("a")]) == 1.0
    with pytest.raises(ValueError):
        ev.set_agreement(["ab"], ["a"])  # a bare string is not a label collection
    with pytest.raises(ValueError):
        ev.set_agreement([{"a"}], [])


def test_fallback_metrics():
    # gold-is-fallback (gold set exactly {"keep"}): positions 0, 2 -> support 2
    # predicted-is-fallback (choice == "keep"): positions 0, 3
    # tp: position 0 (both) -> 1 ; fp: position 3 (predicted, not gold-exact) -> 1
    # fn: position 2 (gold-exact, not predicted) -> 1
    r = ev.fallback_metrics(_FB_GOLD_SETS, _FB_CHOICES, "keep")
    assert (r.tp, r.fp, r.fn, r.support) == (1, 1, 1, 2)
    assert (r.precision, r.recall, r.f1) == pytest.approx((0.5, 0.5, 0.5))


def test_fallback_metrics_accepts_choice_answers():
    r = ev.fallback_metrics([{"keep"}], [ChoiceStub("keep")], "keep")
    assert (r.tp, r.fp, r.fn) == (1, 0, 0)


def test_fallback_metrics_degenerate_cases():
    # the fallback is never the gold-exact answer: recall is undefined (no support)
    r = ev.fallback_metrics([{"x"}, {"y"}], ["x", "y"], "keep")
    assert r.support == 0 and nan(r.recall)
    assert r.fp == 0 and r.tp == 0  # never chosen either, so precision is also undefined
    assert nan(r.precision)
    # the fallback is never chosen, but is sometimes the gold-exact answer: precision undefined
    r = ev.fallback_metrics([{"keep"}, {"x"}], ["x", "x"], "keep")
    assert nan(r.precision)
    assert r.recall == 0.0 and r.support == 1
    # a gold set containing the fallback alongside a real option is not a gold-exact fallback
    # case: contrast with set_agreement, where that same example counts "keep" as acceptable
    r = ev.fallback_metrics([{"x", "keep"}], ["keep"], "keep")
    assert r.support == 0  # {"x", "keep"} != {"keep"}
    assert r.fp == 1  # predicted "keep" but gold-exact says no


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


def test_mean_recall_at_budget_is_the_thin_mean():
    queries = [([1, 0, 1], [0.9, 0.8, 0.7]), ([0, 1], [0.1, 0.9])]
    expected = (ev.recall_at_budget(*queries[0], 2) + ev.recall_at_budget(*queries[1], 2)) / 2
    assert ev.mean_recall_at_budget(queries, 2) == pytest.approx(expected)


def test_mean_recall_at_budget_skips_undefined_queries():
    q_zero = ([0, 0], [0.1, 0.2])  # no relevant item: undefined, skipped
    q_one = ([1, 0], [0.9, 0.1])  # recall@1 = 1.0
    assert ev.mean_recall_at_budget([q_zero, q_one], 1) == pytest.approx(1.0)
    assert nan(ev.mean_recall_at_budget([q_zero], 1))


def test_top_k_query_accuracy_credits_a_clear_winner():
    assert ev.top_k_query_accuracy([([0, 1, 0], [0.1, 0.9, 0.2])]) == 1.0
    assert ev.top_k_query_accuracy([([0, 1, 0], [0.9, 0.1, 0.2])]) == 0.0


def test_top_k_query_accuracy_averages_over_queries():
    queries = [([0, 1], [0.1, 0.9]), ([1, 0], [0.1, 0.9])]
    assert ev.top_k_query_accuracy(queries) == pytest.approx(0.5)


def test_top_k_query_accuracy_gives_fractional_credit_on_a_tie_at_the_top():
    # the same expectation-over-tie-orders rule recall_at_budget uses: one of two tied for
    # the top score is relevant -> half credit.
    assert ev.top_k_query_accuracy([([1, 0], [0.5, 0.5])]) == pytest.approx(0.5)


def test_top_k_query_accuracy_diverges_from_mean_recall_at_budget_with_two_relevant_items():
    # Two of three items are gold-relevant and the top-scored item is one of them: the top
    # item IS relevant, so top-k query accuracy at k=1 is 1.0. But a review budget of 1 only
    # finds one of the two relevant items, so mean recall at a budget of 1 is 0.5. This is
    # exactly the gap a recipe-local "top1_accuracy" helper was written to fix: an earlier,
    # mistaken version computed it as the mean of recall_at_budget(..., budget=1), which
    # silently agrees with true top-1 accuracy only when every query has one relevant item
    # (see test_top_k_query_accuracy_agrees_with_mean_recall_at_budget_for_single_relevant_item).
    relevant, scores = [1, 1, 0], [0.9, 0.1, 0.2]
    assert ev.top_k_query_accuracy([(relevant, scores)], k=1) == pytest.approx(1.0)
    assert ev.mean_recall_at_budget([(relevant, scores)], budget=1) == pytest.approx(0.5)


def test_top_k_query_accuracy_agrees_with_mean_recall_at_budget_for_single_relevant_item():
    # When every query has exactly one relevant item, "is the relevant item in the top k" and
    # "what share of the (one) relevant item was found in the top k" are the same event, so
    # the two helpers must agree, ties included.
    queries = [
        ([0, 1, 0], [0.1, 0.9, 0.2]),  # clear winner, relevant
        ([1, 0, 0], [0.9, 0.1, 0.2]),  # clear winner, not relevant
        ([1, 0], [0.5, 0.5]),  # tie at the top, half the tie is relevant
    ]
    for k in (1, 2):
        assert ev.top_k_query_accuracy(queries, k=k) == pytest.approx(
            ev.mean_recall_at_budget(queries, k)
        )


def test_top_k_query_accuracy_extracts_noul_and_score_exactly_as_recall_at_budget_does():
    # Both ranking helpers must take `scores` identically (the docstrings each promise it): a
    # mixed list of Noul and Score answers run through recall_at_budget/mean_recall_at_budget
    # and through top_k_query_accuracy must each extract .noul/.score, not raise and not
    # silently read a wrong number from the bare object.
    relevant = [0, 1, 0]
    scores = [NoulStub(0.2), NoulStub(0.9), ScoreStub(0.4, confidence=0.5)]
    plain = [0.2, 0.9, 0.4]
    assert ev.recall_at_budget(relevant, scores, 1) == pytest.approx(
        ev.recall_at_budget(relevant, plain, 1)
    )
    assert ev.mean_recall_at_budget([(relevant, scores)], 1) == pytest.approx(
        ev.mean_recall_at_budget([(relevant, plain)], 1)
    )
    assert ev.top_k_query_accuracy([(relevant, scores)], k=1) == pytest.approx(
        ev.top_k_query_accuracy([(relevant, plain)], k=1)
    )
    # concretely: the Noul answer at index 1 (0.9) is the top score and is relevant.
    assert ev.top_k_query_accuracy([(relevant, scores)], k=1) == pytest.approx(1.0)


def test_top_k_query_accuracy_is_one_when_every_item_is_relevant():
    assert ev.top_k_query_accuracy([([1, 1, 1], [0.9, 0.1, 0.2])]) == 1.0


def test_top_k_query_accuracy_undefined_when_no_query_has_a_relevant_item():
    # NaN, not a raise: the same undefined-is-NaN convention as mean_ndcg and
    # mean_recall_at_budget, unlike the recipe-local helper this generalizes, which raised.
    assert nan(ev.top_k_query_accuracy([([0, 0], [0.1, 0.9])]))


def test_top_k_query_accuracy_errors():
    with pytest.raises(ValueError):
        ev.top_k_query_accuracy([])
    with pytest.raises(ValueError):
        ev.top_k_query_accuracy([([1], [0.1, 0.2])])  # length mismatch within one query
    with pytest.raises(ValueError):
        ev.top_k_query_accuracy([([1, 0], [0.1, 0.9])], k=0)


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


def test_selective_curve_rejects_out_of_range_confidence():
    # a sentinel confidence (a rule's "never gated" marker) must not reach the curve.
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        ev.selective_curve([1, 0, 1], [0.9, -1.0, 0.5])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        ev.selective_curve([1, 0, 1], [0.9, 2.0, 0.5])


def test_select_confidence_threshold_rejects_out_of_range_confidence():
    # Before the fix, a -1.0 sentinel among otherwise-high accuracy made this function
    # happily return -1.0 as "the threshold" whenever target_accuracy admitted every
    # answer (issue #155): every answer, sentinel included, clears accuracy >= 0.5, so
    # the lowest (most-covering) threshold was the sentinel itself. That candidate must
    # never reach the caller.
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        ev.select_confidence_threshold([1, 1, 1], [0.9, 0.8, -1.0], target_accuracy=0.5)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        ev.select_confidence_threshold([1, 1, 1], [0.9, 0.8, -1.0], min_coverage=0.5)


def test_evaluate_selective_rejects_out_of_range_confidence():
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        ev.evaluate_selective(SC, [0.9, 0.8, 0.7, 0.6, -1.0], 0.5)


# ---------------------------------------------------------------- Selective prediction from outcomes


def test_evaluate_outcomes():
    # answered positions 0, 1, 3 (True); correct among them: 0 and 3 right, 1 wrong
    # -> coverage 3/4, accuracy 2/3, risk 1/3
    r = ev.evaluate_outcomes([True, True, False, True], [True, False, False, True])
    assert (r.n_total, r.n_answered) == (4, 3)
    assert (r.coverage, r.accuracy, r.risk) == pytest.approx((0.75, 2 / 3, 1 / 3))
    assert nan(r.threshold)  # no single confidence cut-off produced this split


def test_evaluate_outcomes_nothing_answered_is_nan():
    r = ev.evaluate_outcomes([False, False], [True, False])
    assert r.n_answered == 0 and r.coverage == 0.0 and nan(r.accuracy) and nan(r.risk)


def test_evaluate_outcomes_accepts_0_1():
    r = ev.evaluate_outcomes([1, 0, 1], [1, 1, 0])
    assert (r.n_total, r.n_answered) == (3, 2)


def test_evaluate_outcomes_matches_evaluate_selective_for_a_confidence_only_rule():
    # When a rule's only review branch is "confidence < threshold", evaluate_outcomes
    # fed the rule's own accept/review split agrees with evaluate_selective fed the raw
    # confidence and the same threshold, on every field but threshold itself (docs/evaluation.md,
    # "Selective prediction"). Checked over several thresholds and a non-trivial correctness
    # pattern, not just one convenient case.
    rng = np.random.default_rng(155)
    confidence = rng.random(200).tolist()
    correct = (rng.random(200) < 0.7).tolist()
    for threshold in (0.0, 0.1, 0.37, 0.5, 0.63, 0.9, 1.0):
        accepted = [c >= threshold for c in confidence]
        by_outcomes = ev.evaluate_outcomes(accepted, correct)
        by_selective = ev.evaluate_selective(correct, confidence, threshold)
        assert by_outcomes.n_total == by_selective.n_total
        assert by_outcomes.n_answered == by_selective.n_answered
        assert by_outcomes.coverage == pytest.approx(by_selective.coverage)
        if nan(by_selective.accuracy):
            assert nan(by_outcomes.accuracy) and nan(by_outcomes.risk)
        else:
            assert by_outcomes.accuracy == pytest.approx(by_selective.accuracy)
            assert by_outcomes.risk == pytest.approx(by_selective.risk)
        assert nan(by_outcomes.threshold)
        assert by_selective.threshold == threshold


def test_evaluate_outcomes_diverges_from_evaluate_selective_with_a_second_review_branch():
    # The case evaluate_outcomes is for: a rule with an unconditional review branch beyond
    # the confidence gate (here, example 1 is rejected outright whatever its confidence).
    # evaluate_selective knows nothing about that branch and answers it anyway.
    accepted = [True, False, True]  # the rule's own decisions; index 1 rejected unconditionally
    correct = [True, True, False]
    confidence = [0.9, 0.9, 0.1]  # index 1 is confident, but the rule still rejects it
    threshold = 0.5
    by_outcomes = ev.evaluate_outcomes(accepted, correct)
    by_selective = ev.evaluate_selective(correct, confidence, threshold)
    assert by_outcomes.n_answered == 2  # indices 0, 2
    assert by_selective.n_answered == 2  # indices 0, 1: evaluate_selective disagrees on which
    assert by_outcomes.accuracy != pytest.approx(by_selective.accuracy)


def test_evaluate_outcomes_errors():
    with pytest.raises(ValueError):
        ev.evaluate_outcomes([], [])
    with pytest.raises(ValueError):
        ev.evaluate_outcomes([True], [True, False])
    with pytest.raises(ValueError):
        ev.evaluate_outcomes([True, 2], [True, False])  # not boolean/0/1


def test_outcome_curve_equals_selective_curve_when_exempt_is_none():
    # No exemptions at all (the default `exempt=None`, and an explicit all-False mask) means
    # the two curves are the same identity: outcome_curve exists for the *other* case.
    oc = ev.outcome_curve(SF, SC)
    sc = ev.selective_curve(SC, SF)
    assert oc.thresholds.tolist() == sc.thresholds.tolist()
    assert oc.coverage == pytest.approx(sc.coverage)
    assert oc.accuracy == pytest.approx(sc.accuracy)
    assert oc.risk == pytest.approx(sc.risk)
    oc_false = ev.outcome_curve(SF, SC, exempt=[False] * len(SC))
    assert oc_false.coverage == pytest.approx(oc.coverage)
    assert oc_false.accuracy == pytest.approx(oc.accuracy)


def test_outcome_curve_accepts_an_exempt_example_at_every_threshold():
    # index 2 is exempt: accepted whatever its confidence (CONTRIBUTING.md section 4's
    # fallback shape, e.g. recipe 11's no_clarification_needed or recipe 13's
    # no_suitable_rewrite). Every other index is gated on confidence >= t as usual.
    confidence = [0.9, 0.8, 0.7, 0.6, 0.5]
    correct = [True, False, True, True, True]
    exempt = [False, False, True, False, False]
    c = ev.outcome_curve(confidence, correct, exempt=exempt)
    assert c.thresholds.tolist() == [0.9, 0.8, 0.7, 0.6, 0.5]
    # t=0.9: nonexempt>=0.9 {0}, + exempt {2} -> sel {0,2}: cov 2/5, acc (T,T)=1.0
    # t=0.8: nonexempt>=0.8 {0,1}, + {2} -> sel {0,1,2}: cov 3/5, acc (T,F,T)=2/3
    # t=0.7: nonexempt>=0.7 {0,1} (3's 0.6 < 0.7), + {2} -> sel {0,1,2}: cov 3/5, acc 2/3
    # t=0.6: nonexempt>=0.6 {0,1,3}, + {2} -> sel {0,1,2,3}: cov 4/5, acc (T,F,T,T)=3/4
    # t=0.5: nonexempt>=0.5 {0,1,3,4}, + {2} -> sel all: cov 1.0, acc (T,F,T,T,T)=4/5
    assert c.coverage == pytest.approx([0.4, 0.6, 0.6, 0.8, 1.0])
    assert c.accuracy == pytest.approx([1.0, 2 / 3, 2 / 3, 0.75, 0.8])
    assert c.risk == pytest.approx((1 - c.accuracy).tolist())


def test_outcome_curve_accuracy_is_never_nan_even_when_an_old_fixed_accept_mask_would_empty_out():
    # Under the semantics this function replaced (a fixed `accepted & (confidence >= t)`
    # mask), a threshold whose gate selected nothing but the rule's rejects used to read NaN
    # (the case test_outcome_curve_is_nan_where_the_accepted_mask_selects_nothing covered
    # before this fix round). `exempt` cannot reproduce that failure mode: an exempt example
    # is selected at every threshold, and the top threshold is itself an observed confidence,
    # so even with no exemptions at least that one example clears it -- the same guarantee
    # selective_curve has. accuracy (and so risk) is therefore always defined here.
    confidence = [0.9, 0.1, 0.1]
    correct = [True, False, True]
    exempt = [False, False, True]
    c = ev.outcome_curve(confidence, correct, exempt=exempt)
    assert not any(nan(a) for a in c.accuracy)
    assert not any(nan(r) for r in c.risk)
    # and with no exemptions at all, same as selective_curve: never NaN either.
    c_none = ev.outcome_curve(confidence, correct)
    assert not any(nan(a) for a in c_none.accuracy)


def test_outcome_curve_accepts_choice_and_noul_answers():
    # The docstring promises the same input contract as selective_curve: numbers, or
    # Choice/Score answers (.confidence); Noul must go through noul_confidence first and a
    # bare Noul answer raises with a pointer to it, exactly as selective_curve does.
    answers = [ChoiceStub("a", confidence=c) for c in SF]
    c = ev.outcome_curve(answers, SC)
    assert c.coverage == pytest.approx(ev.selective_curve(SC, SF).coverage)
    with pytest.raises(ValueError, match="noul_confidence"):
        ev.outcome_curve([NoulStub(0.9), NoulStub(0.4)], [1, 0])
    noul_answers = [NoulStub(0.9), NoulStub(0.4)]
    ok_curve = ev.outcome_curve(ev.noul_confidence(noul_answers), [1, 0])
    assert ok_curve.coverage.tolist() == [0.5, 1.0]


def test_outcome_curve_placeholder_confidence_for_an_unanswered_example_moves_the_grid():
    # The docs warn against inventing a confidence for an example that was never answered at
    # all (a rule's own short-circuit before any question was asked, e.g. recipe 14's
    # no_candidates or recipe 22's no_candidate_resolution): outcome_curve sweeps answered
    # examples only. This pins why a placeholder is not inert even for an exempt example --
    # it adds a row to the threshold grid (thresholds = numpy.unique of every confidence
    # passed in) and so moves the curve's x-axis, even though an exempt example is selected
    # at every threshold either way.
    confidence = [0.9, 0.8, 0.7]
    correct = [True, False, True]
    exempt = [False, False, True]  # index 2 is a genuine, answered exempt example
    answered_only = ev.outcome_curve(confidence, correct, exempt=exempt)
    assert answered_only.thresholds.tolist() == [0.9, 0.8, 0.7]

    # Adding an unanswered example as if it had confidence 0.0 (still exempt, so it would
    # never change which examples are selected) nonetheless inserts a new threshold row.
    with_placeholder = ev.outcome_curve(
        confidence + [0.0], correct + [True], exempt=exempt + [True]
    )
    assert with_placeholder.thresholds.tolist() == [0.9, 0.8, 0.7, 0.0]
    assert len(with_placeholder.thresholds) != len(answered_only.thresholds)


def test_outcome_curve_rejects_out_of_range_confidence():
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        ev.outcome_curve([0.9, -1.0, 0.5], [True, True, True])


def test_outcome_curve_rejects_non_boolean_exempt():
    with pytest.raises(ValueError, match="exempt"):
        ev.outcome_curve([0.9, 0.5], [True, True], exempt=[0, 2])


def test_outcome_curve_errors():
    with pytest.raises(ValueError):
        ev.outcome_curve([], [])
    with pytest.raises(ValueError):
        ev.outcome_curve([0.9, 0.5], [True])  # confidences/correct length mismatch
    with pytest.raises(ValueError):
        ev.outcome_curve([0.9, 0.5], [True, True], exempt=[True])  # exempt length mismatch


# ---------------------------------------------------------------- outcome_curve against merged recipes


RECIPE_11 = REPO / "recipes" / "11-clarification-selection"
RECIPE_13 = REPO / "recipes" / "13-candidate-rewrite-selection"


def _row_at_or_above(curve: ev.SelectiveCurve, threshold: float) -> tuple[float, float, float]:
    """The row whose selected set under ``confidence >= t`` is identical to
    ``confidence >= threshold``: the smallest observed threshold still >= ``threshold`` selects
    exactly the same examples, because no observed confidence lies strictly between them."""
    candidates = [i for i, t in enumerate(curve.thresholds) if t >= threshold]
    idx = max(candidates)  # thresholds descend: the last one >= threshold is the smallest
    return float(curve.coverage[idx]), float(curve.accuracy[idx]), float(curve.risk[idx])


def test_outcome_curve_reproduces_recipe_11s_evaluate_outcomes_at_its_frozen_gate():
    """Recipe 11's `select_followup` (recipes/11-clarification-selection/helpers.py) accepts
    `no_clarification_needed` whatever its confidence -- CONTRIBUTING.md section 4's exemption
    -- and gates every other option on `confidence >= threshold`. Re-derived from the recipe's
    own committed fixtures (ReplayBackend, no notebook executed, no network): at the notebook's
    frozen gate, `outcome_curve`'s row must reproduce `evaluate_outcomes`'s coverage, accuracy
    and risk on the test split, which differ from `evaluate_selective`'s confidence-only
    numbers because of exactly one unconditionally-accepted wrong answer
    (`t12-budget-wrong`)."""
    helpers = load_helpers(RECIPE_11)
    examples = load_inputs(RECIPE_11)
    labels = load_labels(RECIPE_11)
    backend = get_backend(fixtures=responses_path(RECIPE_11))
    questions = helpers.build_questions()

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["clarification"]

    val_examples = select_split(examples, "validation")
    val_answers = [decide(e) for e in val_examples]
    val_gold = [labels[e.id] for e in val_examples]
    real_match = [
        (a.choice == g, a.confidence)
        for a, g in zip(val_answers, val_gold, strict=True)
        if a.choice != helpers.NO_CLARIFICATION_NEEDED
    ]
    threshold = ev.select_confidence_threshold(
        [c for c, _ in real_match], [f for _, f in real_match], target_accuracy=1.0
    )

    test_examples = select_split(examples, "test")
    test_answers = [decide(e) for e in test_examples]
    test_gold = [labels[e.id] for e in test_examples]
    test_results = [
        helpers.select_followup(e.fields["task_id"], a, threshold)
        for e, a in zip(test_examples, test_answers, strict=True)
    ]
    test_gold_by_id = {
        e.fields["task_id"]: g for e, g in zip(test_examples, test_gold, strict=True)
    }
    test_accepted, test_correct = helpers.outcome_accounting(test_results, test_gold_by_id)
    reference = ev.evaluate_outcomes(test_accepted, test_correct)

    confidences = [a.confidence for a in test_answers]
    correct = [a.choice == g for a, g in zip(test_answers, test_gold, strict=True)]
    exempt = [a.choice == helpers.NO_CLARIFICATION_NEEDED for a in test_answers]
    curve = ev.outcome_curve(confidences, correct, exempt=exempt)
    row_coverage, row_accuracy, row_risk = _row_at_or_above(curve, threshold)

    assert row_coverage == pytest.approx(reference.coverage)
    assert row_accuracy == pytest.approx(reference.accuracy)
    assert row_risk == pytest.approx(reference.risk)
    # the numbers this notebook prints, as of this merge (comment 6081624400's own re-derivation)
    assert (reference.coverage, reference.accuracy, reference.risk) == pytest.approx(
        (0.9474, 0.8889, 0.1111), abs=1e-4
    )
    # the confidence-only view disagrees: it excludes the exempt wrong answer, reading smaller
    # on both coverage and risk -- the more flattering number this function exists to avoid.
    naive = ev.evaluate_selective(correct, confidences, threshold)
    assert (naive.coverage, naive.accuracy, naive.risk) == pytest.approx(
        (0.8947, 0.9412, 0.0588), abs=1e-4
    )
    naive_row_coverage, _, naive_row_risk = _row_at_or_above(
        ev.selective_curve(correct, confidences), threshold
    )
    assert naive_row_coverage == pytest.approx(naive.coverage)
    assert naive_row_risk == pytest.approx(naive.risk)


def test_outcome_curve_reproduces_recipe_13s_evaluate_outcomes_at_its_frozen_gate():
    """Recipe 13's `select_rewrite` (recipes/13-candidate-rewrite-selection/helpers.py) accepts
    `no_suitable_rewrite` whatever its confidence, the same shape as recipe 11. Re-derived from
    its own committed fixtures: at the frozen gate, `outcome_curve`'s row must reproduce
    `evaluate_outcomes`'s test-split numbers, not `evaluate_selective`'s -- the two disagree
    here because `t12-courtesy-credit-wrong`'s confidence (0.2267) sits below the gate (0.28)
    but `select_rewrite` never checks a `no_suitable_rewrite` answer's confidence."""
    helpers = load_helpers(RECIPE_13)
    examples = load_inputs(RECIPE_13)
    labels = load_labels(RECIPE_13)
    backend = get_backend(fixtures=responses_path(RECIPE_13))
    questions = helpers.build_questions()

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["rewrite"]

    val_examples = select_split(examples, "validation")
    val_answers = [decide(e) for e in val_examples]
    val_gold = [labels[e.id] for e in val_examples]
    real_match = [
        (a.choice == g, a.confidence)
        for a, g in zip(val_answers, val_gold, strict=True)
        if a.choice != helpers.NO_SUITABLE_REWRITE
    ]
    threshold = ev.select_confidence_threshold(
        [c for c, _ in real_match], [f for _, f in real_match], target_accuracy=1.0
    )

    test_examples = select_split(examples, "test")
    test_answers = [decide(e) for e in test_examples]
    test_gold = [labels[e.id] for e in test_examples]

    def select(e, a):
        candidates = dict(zip(helpers.CANDIDATES, e.fields["candidates"], strict=True))
        return helpers.select_rewrite(
            e.fields["item_id"], a, e.fields["original"], candidates, threshold
        )

    test_results = [select(e, a) for e, a in zip(test_examples, test_answers, strict=True)]
    test_accepted = [r.outcome != helpers.REVIEW for r in test_results]
    test_correct = [a.choice == g for a, g in zip(test_answers, test_gold, strict=True)]
    reference = ev.evaluate_outcomes(test_accepted, test_correct)

    confidences = [a.confidence for a in test_answers]
    exempt = [a.choice == helpers.NO_SUITABLE_REWRITE for a in test_answers]
    curve = ev.outcome_curve(confidences, test_correct, exempt=exempt)
    row_coverage, row_accuracy, row_risk = _row_at_or_above(curve, threshold)

    assert row_coverage == pytest.approx(reference.coverage)
    assert row_accuracy == pytest.approx(reference.accuracy)
    assert row_risk == pytest.approx(reference.risk)
    assert (reference.coverage, reference.accuracy, reference.risk) == pytest.approx(
        (0.8421, 0.8750, 0.1250), abs=1e-4
    )
    # at this particular gate the confidence-only view happens to equal evaluate_selective's
    # smaller numbers -- exactly the trap of plotting selective_curve for this rule.
    naive = ev.evaluate_selective(test_correct, confidences, threshold)
    assert naive.coverage == pytest.approx(0.7895, abs=1e-4)
    assert naive.coverage != pytest.approx(reference.coverage)


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
    "pool_label_decisions": lambda: ev.pool_label_decisions([], ["l"], {"l": []}, {"l": []}, 0.5),
    "pool_label_outcomes": lambda: ev.pool_label_outcomes(
        [], ["l"], {"l": []}, {"l": []}, {"l": []}
    ),
    "set_agreement": lambda: ev.set_agreement([], []),
    "fallback_metrics": lambda: ev.fallback_metrics([], [], "fallback"),
    "score_level": lambda: ev.score_level(ScoreStub(1.0, {})),
    "exact_agreement": lambda: ev.exact_agreement([], []),
    "mean_absolute_error": lambda: ev.mean_absolute_error([], []),
    "ndcg": lambda: ev.ndcg([], []),
    "mean_ndcg": lambda: ev.mean_ndcg([]),
    "top_probabilities": lambda: ev.top_probabilities([]),
    "top_k_accuracy": lambda: ev.top_k_accuracy([], [], 1),
    "top_k_query_accuracy": lambda: ev.top_k_query_accuracy([]),
    "recall_at_budget": lambda: ev.recall_at_budget([], [], 1),
    "mean_recall_at_budget": lambda: ev.mean_recall_at_budget([], 1),
    "selective_curve": lambda: ev.selective_curve([], []),
    "select_confidence_threshold": lambda: ev.select_confidence_threshold(
        [], [], target_accuracy=0.5
    ),
    "evaluate_selective": lambda: ev.evaluate_selective([], [], 0.5),
    "evaluate_outcomes": lambda: ev.evaluate_outcomes([], []),
    "outcome_curve": lambda: ev.outcome_curve([], []),
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
    "set_agreement": lambda: ev.set_agreement([{1}], [1, 2]),
    "fallback_metrics": lambda: ev.fallback_metrics([{1}], [1, 2], 1),
    "exact_agreement": lambda: ev.exact_agreement([1], [1, 2]),
    "mean_absolute_error": lambda: ev.mean_absolute_error([1], [1, 2]),
    "ndcg": lambda: ev.ndcg([1], [1, 2]),
    "top_k_accuracy": lambda: ev.top_k_accuracy([1], [{1: 1.0}, {1: 1.0}], 1),
    "top_k_query_accuracy": lambda: ev.top_k_query_accuracy([([1], [0.1, 0.2])]),
    "recall_at_budget": lambda: ev.recall_at_budget([1], [1, 2], 1),
    "selective_curve": lambda: ev.selective_curve([1], [0.5, 0.5]),
    "evaluate_outcomes": lambda: ev.evaluate_outcomes([True], [True, False]),
    "outcome_curve": lambda: ev.outcome_curve([0.5], [True, True]),
    "reliability_table": lambda: ev.reliability_table([0.5], [1, 0]),
    "paired_bootstrap_difference": lambda: ev.paired_bootstrap_difference([1], [1, 2], seed=0),
    "pool_label_decisions": lambda: ev.pool_label_decisions(
        ["a"], ["l"], {"l": [True, False]}, {"l": [0.5]}, 0.5
    ),
    "pool_label_outcomes": lambda: ev.pool_label_outcomes(
        ["a"], ["l"], {"l": [True, False]}, {"l": [True]}, {"l": [True]}
    ),
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
