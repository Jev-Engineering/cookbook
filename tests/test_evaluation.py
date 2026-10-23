"""Metric tests. Every expected value is computed by hand in the comment above it."""

from __future__ import annotations

import itertools
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


def test_recall_at_budget_eligible_none_is_the_default_behaviour():
    rel, sc = [1, 0, 1, 0, 1], [0.9, 0.8, 0.7, 0.6, 0.5]
    assert ev.recall_at_budget(rel, sc, 3, eligible=None) == ev.recall_at_budget(rel, sc, 3)
    assert ev.recall_at_budget(rel, sc, 3, eligible=[1] * 5) == ev.recall_at_budget(rel, sc, 3)


def test_recall_at_budget_ineligible_items_never_occupy_a_slot():
    # #231: one eligible item and a budget of 2. Items: relevance 1,1,0 ; scores 0.9,0.8,0.7 ;
    # only the LAST is eligible (and irrelevant). Without eligibility the budget of 2 takes the
    # two relevant items (recall 1.0); with it only item 3 can be reviewed -> 0 of 2 found.
    rel, sc = [1, 1, 0], [0.9, 0.8, 0.7]
    assert ev.recall_at_budget(rel, sc, 2) == pytest.approx(1.0)
    assert ev.recall_at_budget(rel, sc, 2, eligible=[0, 0, 1]) == 0.0
    # the slot-credit bug itself: relevant A (0.9, eligible), relevant B (0.8, ineligible),
    # irrelevant C (0.1, eligible), budget 2. Eligible are A and C only, so the budget fills with
    # both, finds A, and B is never found: 1 of 2 = 0.5 -- and B's higher stand-in score must not
    # buy it the second slot.
    assert ev.recall_at_budget([1, 1, 0], [0.9, 0.8, 0.1], 2, eligible=[1, 0, 1]) == 0.5
    # a single eligible slot goes to the best eligible item, not the best item
    assert ev.recall_at_budget([1, 0, 1], [0.1, 0.9, 0.5], 1, eligible=[1, 0, 1]) == 0.5


def test_recall_at_budget_denominator_keeps_ineligible_relevant_items():
    # relevant ineligible items are missed, they are not removed from the question
    assert ev.recall_at_budget([1, 1], [0.9, 0.8], 5, eligible=[1, 0]) == 0.5


def test_recall_at_budget_with_no_eligible_item_is_zero_not_nan():
    assert ev.recall_at_budget([1, 0], [0.9, 0.1], 1, eligible=[0, 0]) == 0.0
    # but no relevant item at all is still undefined, eligible or not
    assert nan(ev.recall_at_budget([0, 0], [0.9, 0.1], 1, eligible=[0, 0]))
    assert nan(ev.recall_at_budget([0, 0], [0.9, 0.1], 1, eligible=[1, 1]))


def test_recall_at_budget_ties_among_eligible_items_are_credited_in_expectation():
    # two eligible items tied at 0.5, one of them relevant, budget 1: a half chance of the one
    # slot finding it, over 2 relevant items in all (the ineligible 0.99 one is never found)
    assert ev.recall_at_budget([1, 0, 1], [0.5, 0.5, 0.99], 1, eligible=[1, 1, 0]) == 0.25


def test_recall_at_budget_eligible_validation():
    with pytest.raises(ValueError):
        ev.recall_at_budget([1, 0], [0.9, 0.1], 1, eligible=[1])
    with pytest.raises(ValueError):
        ev.recall_at_budget([1, 0], [0.9, 0.1], 1, eligible=[1, 2])
    with pytest.raises(ValueError):
        ev.recall_at_budget([1, 0], [0.9, 0.1], 1, eligible=[])


def test_mean_recall_at_budget_accepts_an_eligible_mask_per_query():
    q_plain = ([1, 0], [0.9, 0.1])  # recall 1.0
    q_gated = ([1, 1, 0], [0.9, 0.8, 0.1], [1, 0, 1])  # recall 0.5
    assert ev.mean_recall_at_budget([q_plain, q_gated], 2) == pytest.approx(0.75)
    with pytest.raises(ValueError):
        ev.mean_recall_at_budget([([1], [0.5], [1], [1])], 1)


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


def test_top_k_query_accuracy_a_tie_wholly_inside_the_cut_off_costs_nothing():
    # Scores 0.9, 0.9, 0.1 with only item 0 relevant. k=2 holds both tied items: hit, 1.0.
    # k=1 holds one of the two: P(it is the relevant one) = 1 / 2.
    q = ([1, 0, 0], [0.9, 0.9, 0.1])
    assert ev.top_k_query_accuracy([q], k=2) == 1.0
    assert ev.top_k_query_accuracy([q], k=1) == 0.5
    # the relevant item below the tie is out of reach until the cut-off passes the tie:
    # k=2 -> 0.0, k=3 -> 1.0.
    below = ([0, 0, 1], [0.9, 0.9, 0.1])
    assert ev.top_k_query_accuracy([below], k=2) == 0.0
    assert ev.top_k_query_accuracy([below], k=3) == 1.0


def test_top_k_query_accuracy_a_tie_that_straddles_the_cut_off_is_a_hypergeometric_hit():
    # Scores 0.9, 0.5, 0.5, 0.5; only item 1 (inside the three-way tie) is relevant.
    # k=1: the 0.9 item (not relevant) fills the slot -> 0.
    # k=2: one open slot among 3 tied, 1 relevant -> 1 - C(2,1)/C(3,1) = 1/3.
    # k=3: two open slots -> 1 - C(2,2)/C(3,2) = 1 - 1/3 = 2/3.
    # k=4: the whole tie fits -> 1.
    q = ([0, 1, 0, 0], [0.9, 0.5, 0.5, 0.5])
    got = [ev.top_k_query_accuracy([q], k=k) for k in (1, 2, 3, 4)]
    assert got == [0.0, 1 / 3, 2 / 3, 1.0]


def test_top_k_query_accuracy_a_tie_with_two_relevant_items_by_hand():
    # Four items tied, two relevant. 4 choose s orderings of the open slots:
    # k=1: 1 - C(2,1)/C(4,1) = 1/2.   k=2: 1 - C(2,2)/C(4,2) = 1 - 1/6 = 5/6.
    # k=3: the two non-relevant items cannot fill three slots -> 1.
    q = ([1, 1, 0, 0], [0.5, 0.5, 0.5, 0.5])
    got = [ev.top_k_query_accuracy([q], k=k) for k in (1, 2, 3)]
    assert got == [0.5, 5 / 6, 1.0]


def test_top_k_query_accuracy_k_larger_than_the_list_is_the_whole_list():
    # Three items, k=99: every item is in the cut-off, so any query with a relevant item is
    # a hit, including when the relevant item has the lowest score.
    assert ev.top_k_query_accuracy([([0, 0, 1], [0.9, 0.8, 0.1])], k=99) == 1.0
    assert ev.top_k_query_accuracy([([0, 0, 1], [0.9, 0.8, 0.1])], k=3) == 1.0
    assert ev.top_k_query_accuracy([([0, 0, 1], [0.9, 0.8, 0.1])], k=2) == 0.0
    # a one-item query, k=1 and k larger
    assert ev.top_k_query_accuracy([([1], [0.3])], k=1) == 1.0
    assert ev.top_k_query_accuracy([([1], [0.3])], k=5) == 1.0


def test_top_k_query_accuracy_multi_gold_is_any_hit_not_a_share():
    # Relevant: items 1 and 2 (scores 0.5 and 0.4); the top item 0 (0.9) is not.
    # k=1 -> top item irrelevant -> 0.   k=2 -> item 1 is in -> 1.0 (one of two found).
    # recall_at_budget at budget 2 is 1/2: this is the second place the two questions differ.
    rel, sc = [0, 1, 1], [0.9, 0.5, 0.4]
    assert ev.top_k_query_accuracy([(rel, sc)], k=1) == 0.0
    assert ev.top_k_query_accuracy([(rel, sc)], k=2) == 1.0
    assert ev.recall_at_budget(rel, sc, 2) == 0.5
    # Several relevant items in the top k still score 1.0 (not 2 and not 1/2).
    assert ev.top_k_query_accuracy([([1, 1, 1], [0.3, 0.2, 0.1])], k=3) == 1.0


def test_top_k_query_accuracy_matches_the_documented_recipe_17_case_at_every_k():
    # The case that hid the original defect: one query with two relevant items, the top
    # one among them. recall_at_budget(.., 1) is 0.5; the ranking accuracy is 1.0 at every k.
    rel, sc = [1, 1, 0], [0.9, 0.1, 0.2]
    for k in (1, 2, 3, 4):
        assert ev.top_k_query_accuracy([(rel, sc)], k=k) == 1.0
    assert ev.recall_at_budget(rel, sc, 1) == 0.5


def test_top_k_query_accuracy_does_not_depend_on_the_order_items_are_listed():
    rel = [1, 0, 1, 0, 0]
    sc = [0.5, 0.5, 0.2, 0.5, 0.9]
    base = [ev.top_k_query_accuracy([(rel, sc)], k=k) for k in (1, 2, 3, 4, 5)]
    # by hand: top 0.9 (not relevant); then a three-way tie at 0.5 holding one relevant;
    # then 0.2 (relevant). k=1 -> 0. k=2: 1 slot of 3, 1 relevant -> 1/3. k=3: 2 of 3 -> 2/3.
    # k=4: the whole tie -> 1.  k=5 -> 1.
    assert base == [0.0, 1 / 3, 2 / 3, 1.0, 1.0]
    for order in ([4, 3, 2, 1, 0], [2, 0, 4, 1, 3], [1, 3, 0, 4, 2]):
        rel_p = [rel[i] for i in order]
        sc_p = [sc[i] for i in order]
        got = [ev.top_k_query_accuracy([(rel_p, sc_p)], k=k) for k in (1, 2, 3, 4, 5)]
        assert got == base


def test_top_k_query_accuracy_equals_brute_force_enumeration_of_tie_orders():
    # The definition, taken literally: average, over every ordering of the items that is
    # consistent with the scores (ties in any order), of "a relevant item is in the first k".
    # Every tie order is equally frequent among the consistent orderings, so the plain mean
    # over them is the expectation over tie orders. Small integer scores force many ties.
    rng = np.random.default_rng(20240607)
    checked = 0
    for _ in range(60):
        n = int(rng.integers(1, 7))
        scores = [int(v) for v in rng.integers(0, 3, size=n)]
        relevant = [int(v) for v in rng.integers(0, 2, size=n)]
        if not any(relevant):
            continue
        consistent = [
            perm
            for perm in itertools.permutations(range(n))
            if all(scores[perm[i]] >= scores[perm[i + 1]] for i in range(n - 1))
        ]
        for k in range(1, n + 2):
            hits = sum(any(relevant[i] for i in perm[:k]) for perm in consistent)
            expected = hits / len(consistent)
            got = ev.top_k_query_accuracy([(relevant, scores)], k=k)
            assert got == pytest.approx(expected, abs=1e-12), (scores, relevant, k)
            checked += 1
    assert checked > 100  # the loop really compared something


def test_top_k_query_accuracy_mean_is_over_queries_with_a_relevant_item_only():
    # q_tie: tied pair, one relevant -> 1/2.  q_hit: clear winner relevant -> 1.
    # q_none: no relevant item -> undefined, left out. Mean of the two defined = 3/4.
    q_tie = ([1, 0], [0.5, 0.5])
    q_hit = ([0, 1], [0.1, 0.9])
    q_none = ([0, 0, 0], [0.9, 0.5, 0.1])
    assert ev.top_k_query_accuracy([q_tie, q_hit, q_none]) == 0.75
    assert ev.top_k_query_accuracy([q_tie, q_hit]) == 0.75
    # a query that is a clear miss is NOT left out: (0 + 1) / 2
    assert ev.top_k_query_accuracy([([1, 0], [0.1, 0.9]), q_hit]) == 0.5


def test_top_k_query_accuracy_duplicate_gold_is_two_relevant_items():
    # Two items identical but for position, both marked relevant, are two relevant items:
    # relevance is a mask, so there is no gold id to repeat. Tied at 0.5 with a third,
    # irrelevant, item: k=1 -> 2/3; k=2 -> 1 - C(1,2)/C(3,2) = 1.
    q = ([1, 1, 0], [0.5, 0.5, 0.5])
    assert ev.top_k_query_accuracy([q], k=1) == 2 / 3
    assert ev.top_k_query_accuracy([q], k=2) == 1.0


def test_top_k_query_accuracy_cannot_score_a_gated_rule_and_prefiltering_changes_the_denominator():
    # The #231 trap in binary form. Query 1: the relevant item (index 0, score 0.9) is
    # excluded by a gate, so the rule's own pick is index 1 (score 0.5), which is not
    # relevant: the rule scores 0.0. Query 2 is an ordinary hit: 1.0.
    gated = ([1, 0, 0], [0.9, 0.5, 0.1], [0, 1, 1])  # eligible mask: item 0 excluded
    plain = ([0, 1], [0.1, 0.9], [1, 1])
    rule_own = (0.0 + 1.0) / 2  # hand-computed from the rule's own picks = 0.5
    # a) the helper on the full lists sees the excluded relevant item as the top hit:
    #    (1.0 + 1.0) / 2 = 1.0, a number the rule's pick never produces.
    full = [(g[0], g[1]) for g in (gated, plain)]
    assert ev.top_k_query_accuracy(full, k=1) == 1.0
    # b) dropping the excluded item beforehand leaves query 1 with no relevant item: it is
    #    undefined and leaves the denominator, so the mean is over ONE query and is also 1.0.
    pre_filtered = [([0, 0], [0.5, 0.1]), ([0, 1], [0.1, 0.9])]
    assert ev.top_k_query_accuracy(pre_filtered, k=1) == 1.0
    # the gated query alone is undefined (NaN), which is how it silently left the mean:
    assert nan(ev.top_k_query_accuracy(pre_filtered[:1], k=1))
    # c) with one relevant item per query, recall_at_budget's eligible mask is the metric:
    assert ev.mean_recall_at_budget([gated, plain], 1) == rule_own == 0.5
    assert ev.recall_at_budget(gated[0], gated[1], 1, eligible=gated[2]) == 0.0


def test_top_k_query_accuracy_accepts_booleans_and_rejects_non_binary_relevance():
    assert ev.top_k_query_accuracy([([False, True], [0.1, 0.9])]) == 1.0
    with pytest.raises(ValueError):
        ev.top_k_query_accuracy([([2, 0], [0.9, 0.1])])  # graded relevance is not binary
    with pytest.raises(ValueError):
        ev.top_k_query_accuracy([([1, 0], [float("nan"), 0.1])])  # non-finite score


def test_top_k_query_accuracy_an_empty_query_raises_even_among_valid_ones():
    with pytest.raises(ValueError):
        ev.top_k_query_accuracy([([1, 0], [0.9, 0.1]), ([], [])])
    with pytest.raises(ValueError):
        ev.top_k_query_accuracy([([], [])])
    with pytest.raises(ValueError):
        ev.top_k_query_accuracy([([1, 0], [])])  # items without scores


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


def test_selective_curve_collapses_ulp_different_mirror_confidence_into_one_threshold():
    # 0.42/0.58 and 0.07/0.93 are the hand-written mirror pairs docs/evaluation.md names
    # (nominal confidence 0.16 and 0.86): fed through noul_confidence, their raw |2p - 1|
    # values really do differ by a few ULPs, even though both halves of each pair mean the
    # same confidence -- noul_confidence does not round this away (reverted: a rounded
    # confidence could disagree, by rounding noise, with the raw value a recipe's own code
    # compares a frozen threshold against). Instead _candidate_thresholds (used by
    # selective_curve, outcome_curve and threshold_sweep) groups the sorted unique values
    # by round(v, 12) and keeps only the smaller raw member of each group, so each pair
    # collapses to one candidate -- 2 thresholds here, not 4 -- and that candidate is
    # always one of the actual observed confidences.
    noul = [0.42, 0.58, 0.07, 0.93]
    confidence = ev.noul_confidence(noul)
    assert confidence[0] != confidence[1], "0.42 vs 0.58 must still differ, unrounded"
    assert confidence[2] != confidence[3], "0.07 vs 0.93 must still differ, unrounded"
    correct = [True, False, True, False]
    c = ev.selective_curve(correct, confidence)
    assert len(c.thresholds) == 2  # not 4: each mirror pair collapsed to one candidate
    lo_16, hi_16 = sorted((confidence[0], confidence[1]))
    lo_86, hi_86 = sorted((confidence[2], confidence[3]))
    assert sorted(c.thresholds.tolist()) == [lo_16, lo_86]
    # the surviving threshold is the smaller twin, and the larger twin still clears
    # "confidence >= threshold" against it -- both members of each pair are accepted
    # together at that one candidate, exactly as if neither had moved.
    assert hi_16 >= lo_16 and hi_86 >= lo_86
    # at 0.86's survivor the two high-confidence examples answer (one right -> 0.5); at
    # 0.16's survivor every example answers (two of four right -> 0.5).
    assert c.coverage.tolist() == pytest.approx([0.5, 1.0])
    assert c.accuracy.tolist() == pytest.approx([0.5, 0.5])


def test_candidate_thresholds_leaves_ordinary_values_unchanged():
    # Confidences at ordinary fixture precision (2-4 decimals) are nowhere near a few-ULP
    # nominal twin, so the candidate-threshold grid must not merge any of them.
    correct = [True, False, True, False, True]
    confidence = [0.1234, 0.5, 0.0, 1.0, 0.9999]
    c = ev.selective_curve(correct, confidence)
    assert c.thresholds.tolist() == sorted(confidence, reverse=True)  # all 5 kept distinct
    r = ev.evaluate_selective(correct, confidence, 0.5)
    assert r.coverage == pytest.approx(3 / 5)  # answers 0.5, 1.0, 0.9999


def test_candidate_thresholds_never_returns_a_value_absent_from_the_input():
    # The headline invariant the whole redesign exists to preserve: every threshold this
    # module ever returns is a bit-exact member of the array it was given, never a rounded
    # stand-in. Checked directly against _candidate_thresholds, and through every public
    # function built on it, over a handful of vectors (an ordinary set, a ULP-twin set, a
    # plain tie, and the endpoints).
    vectors = [
        [0.9, 0.8, 0.7, 0.6, 0.5],
        # 0.42/0.58 and 0.07/0.93 are noul inputs, not twins themselves (four ordinary,
        # distinct floats); noul_confidence's |2p - 1| is what produces the two ULP-twin
        # pairs (0.1600.../0.1599... and 0.8599.../0.8600...) this test needs.
        list(ev.noul_confidence([0.42, 0.58, 0.07, 0.93])),
        [0.5, 0.5, 0.5],  # an ordinary (bit-identical) tie
        [0.0, 1.0],
        [0.3],
    ]
    for values in vectors:
        arr = np.asarray(values, dtype=float)
        observed = set(arr.tolist())
        assert set(ev._candidate_thresholds(arr).tolist()) <= observed

        correct = [True] * len(values)
        assert set(ev.selective_curve(correct, values).thresholds.tolist()) <= observed
        assert set(ev.outcome_curve(values, correct).thresholds.tolist()) <= observed

        gold = [v >= values[0] for v in values]  # arbitrary but valid boolean gold
        points = ev.threshold_sweep(gold, values)
        assert {p.threshold for p in points} <= observed


def _frozen_confidence_gate(recipe_dir: Path) -> float:
    """Reproduces one recipe's own two-stage threshold selection from its committed
    fixtures, offline, no network: the business threshold via select_threshold, then the
    certainty/confidence gate via select_confidence_threshold with min_coverage=0.80,
    exactly as recipes 10 and 15's own "Python's part" cell does."""
    helpers = load_helpers(recipe_dir)
    examples = load_inputs(recipe_dir)
    labels = load_labels(recipe_dir)
    backend = get_backend(fixtures=responses_path(recipe_dir))
    questions = helpers.build_questions()
    key = next(iter(questions))

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)[key]

    val_examples = select_split(examples, "validation")
    val_answers = [decide(e) for e in val_examples]
    val_gold = [labels[e.id] for e in val_examples]
    val_noul = [a.noul for a in val_answers]
    threshold = ev.select_threshold(val_gold, val_noul, objective="f1")
    would_be = [n >= threshold for n in val_noul]
    raw_correct = [r == g for r, g in zip(would_be, val_gold, strict=True)]
    val_confidence = ev.noul_confidence(val_noul)
    return ev.select_confidence_threshold(raw_correct, val_confidence, min_coverage=0.80)


def test_select_confidence_threshold_on_recipes_10_and_15_returns_the_same_gate_as_before():
    # Recipes 10 and 15's validation fixtures carry the same 0.07/0.93 mirror pair (nominal
    # certainty 0.86) that printed as a duplicate "gate >= 0.86" sweep row before this fix --
    # but neither recipe's own *frozen* gate is that pair itself (the duplicate is a few
    # rows further down the sweep than the frozen gate). The candidate-grid dedup must
    # therefore not move the value these two notebooks freeze and print as "0.30": it has to
    # come out bit-for-bit identical to the raw value select_confidence_threshold always
    # returned, on real fixtures.
    for recipe_dir in (RECIPE_10, RECIPE_15):
        gate = _frozen_confidence_gate(recipe_dir)
        assert gate == 0.30000000000000004, recipe_dir.name
        assert f"{gate:.2f}" == "0.30"


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


# A bimodal pool: four low confidences (0.04-0.20), then a gap, then six high ones (0.79-0.96).
# Accuracy of the answered subset at each threshold, high to low: 1.0 through 0.80, 5/6 at 0.79,
# 5/7 at 0.20, 6/8 at 0.15, 6/9 at 0.11, 6/10 at 0.04. Coverage rises 0.1 per step.
_BIMODAL_CONF = [0.04, 0.11, 0.15, 0.20, 0.79, 0.80, 0.84, 0.88, 0.92, 0.96]
_BIMODAL_CORRECT = [0, 0, 1, 0, 0, 1, 1, 1, 1, 1]


def _sweep_min_coverage(correct, conf, values):
    return [ev.select_confidence_threshold(correct, conf, min_coverage=v) for v in values]


def test_raising_min_coverage_can_only_select_a_lower_or_equal_threshold():
    # min_coverage is a FLOOR ON COVERAGE and a lower threshold keeps more answers, so the
    # direction is: higher min_coverage -> same or LOWER threshold (never higher).
    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    got = _sweep_min_coverage(_BIMODAL_CORRECT, _BIMODAL_CONF, values)
    assert got == [0.8, 0.8, 0.8, 0.8, 0.8, 0.79, 0.15, 0.15, 0.11, 0.04]
    assert all(b <= a for a, b in zip(got, got[1:], strict=False))
    assert got[0] > got[-1]  # and it does move overall, so the check is not vacuous


def test_raising_target_accuracy_can_only_select_a_higher_or_equal_threshold():
    # the reverse of min_coverage: a stricter accuracy target moves the gate UP
    got = [
        ev.select_confidence_threshold(_BIMODAL_CORRECT, _BIMODAL_CONF, target_accuracy=v)
        for v in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
    ]
    assert got == [0.04, 0.04, 0.15, 0.79, 0.8, 0.8]
    assert all(b >= a for a, b in zip(got, got[1:], strict=False))


def test_min_coverage_response_is_flat_across_a_wide_range():
    # Five parameter values (0.1 to 0.5, a fivefold change) select the same threshold, because
    # every confidence between 0.20 and 0.80 is absent from the pool: the answer cannot land in
    # the gap. A reader told to "lower min_coverage and watch the threshold move" would see
    # nothing here; the stated direction is about movement, not a promise of it.
    flat = _sweep_min_coverage(_BIMODAL_CORRECT, _BIMODAL_CONF, [0.1, 0.2, 0.3, 0.4, 0.5])
    assert len(set(flat)) == 1
    # the threshold then moves a long way between neighbouring parameter values
    assert ev.select_confidence_threshold(_BIMODAL_CORRECT, _BIMODAL_CONF, min_coverage=0.7) == 0.15


def test_min_coverage_is_not_a_choice_when_errors_sit_at_the_top_of_the_confidence_order():
    # accuracy rises as the threshold falls (the one error is the most confident answer), so the
    # lowest observed confidence is always feasible and always the most accurate: every
    # min_coverage returns it, and a frozen number is not a choice.
    conf, correct = [0.9, 0.8, 0.7, 0.6, 0.5], [0, 1, 1, 1, 1]
    sweep = _sweep_min_coverage(correct, conf, [0.2, 0.4, 0.6, 0.8, 1.0])
    assert set(sweep) == {0.5}


def test_noul_confidence_gate_is_a_two_sided_band_and_its_effect_depends_on_the_wiring():
    # confidence = |2n - 1| is symmetric about 0.5, so a gate g passes exactly when
    # n >= (1 + g)/2 (confidently true) or n <= (1 - g)/2 (confidently false); the open interval
    # between them is the review band. This is the universal fact. Whether a gate is INERT, or
    # equivalent to a stricter threshold, is a fact about one composition, not about (t, g):
    # the same t and g below change 0 outcomes in one wiring and 199 in another.
    g, t = 0.5, 0.8
    # 0.0025 steps; the edges 0.25 and 0.75 are grid points, and |2n - 1| = 0.5 is exact there in
    # binary, so the exact comparison below is safe (arbitrary edges are not: see the next tests)
    grid = [i / 400 for i in range(401)]
    for n in grid:
        in_band = (1 - g) / 2 < n < (1 + g) / 2
        assert (ev.noul_confidence([n])[0] >= g) == (not in_band), n

    def threshold_only(n):
        return "accept" if n >= t else "deny"

    def gate_both_branches(n):
        if ev.noul_confidence([n])[0] < g:
            return "review"
        return threshold_only(n)

    def gate_accept_branch_only(n):
        if n >= t and ev.noul_confidence([n])[0] < g:
            return "review"
        return threshold_only(n)

    both = [n for n in grid if gate_both_branches(n) != threshold_only(n)]
    accept_only = [n for n in grid if gate_accept_branch_only(n) != threshold_only(n)]
    # t = 0.8 >= (1 + g)/2 = 0.75: on the accept side the gate is inert in both wirings ...
    assert not [n for n in both if n >= t]
    # ... but on the reject side the band is real in the wiring that gates it (every n strictly
    # between 0.25 and 0.75 becomes a review, 199 grid points) and absent in the one that does not
    assert len(both) == 199 and all((1 - g) / 2 < n < (1 + g) / 2 for n in both)
    assert accept_only == []


def test_accept_side_gate_inertness_needs_t_above_one_half():
    # for t > 0.5, p >= t gives |2p - 1| >= 2t - 1, so a gate g <= 2t - 1 withholds no admitted p
    t, g = 0.8, 0.6
    for p in (i / 400 for i in range(401)):
        if p >= t:
            assert ev.noul_confidence([p])[0] >= g
    # for t < 0.5 it is false even at g == |2t - 1|: t = 0.3, g = 0.4, p = 0.5 is admitted by the
    # threshold (0.5 >= 0.3) and has confidence 0.0 < 0.4, so the gate withholds it
    t, g = 0.3, 0.4
    assert g == pytest.approx(abs(2 * t - 1))
    assert 0.5 >= t and ev.noul_confidence([0.5])[0] == 0.0 < g
    # and the withheld admitted values are an interval around 0.5, not a lower tail
    grid = [i / 400 for i in range(401)]
    withheld = [p for p in grid if p >= t and ev.noul_confidence([p])[0] < g]
    assert min(withheld) < 0.5 < max(withheld)
    assert all(t <= p <= (1 + g) / 2 for p in withheld)


def _ulps_below(value, target):
    """How many representable doubles lie between ``value`` and ``target`` (``value < target``)."""
    steps = 0
    while value < target:
        value = math.nextafter(value, math.inf)
        steps += 1
    return steps


# Two-decimal thresholds t in 0.51 ... 0.99 whose confidence sits below the typed gate
# round(2t - 1, 2), with the gap in ULPs. Hand-checked, e.g. t = 0.6: noul_confidence is
# 0.19999999999999996, and two steps of math.nextafter reach 0.2 (0.19999999999999996 ->
# 0.19999999999999998 -> 0.2); the double 0.6 is slightly below 0.6, and 2 * 0.6 - 1 is exact
# for p >= 0.5 (Sterbenz), so the shortfall is the decimal's, not the arithmetic's.
_TYPED_GATE_MISSES = {
    0.57: 4,
    0.58: 3,
    0.59: 2,
    0.60: 2,
    0.61: 1,
    0.69: 2,
    0.70: 2,
    0.71: 1,
    0.72: 1,
    0.73: 1,
    0.82: 1,
    0.83: 1,
    0.84: 1,
    0.94: 1,
    0.95: 1,
    0.96: 1,
}


def test_accept_side_floor_at_exactly_two_t_minus_one_holds_only_in_real_arithmetic():
    # The floor g <= 2t - 1 is exact in real arithmetic. A gate typed as the decimal 2t - 1 sits ON
    # the edge, where binary floating point can put the admitted value p = t a few ULPs below it.
    c = ev.noul_confidence([0.6])[0]
    assert c == 0.19999999999999996
    assert c < 0.2
    assert math.nextafter(math.nextafter(c, 1.0), 1.0) == 0.2  # two ULPs, not one
    assert _ulps_below(c, 0.2) == 2
    # Recipe 39's frozen pair (t = 0.85, g = 0.70): the confidence is exactly the gate.
    assert ev.noul_confidence([0.85])[0] == 0.7
    # Exhaustive over the two-decimal thresholds 0.51 ... 0.99 with g = round(2t - 1, 2).
    ts = [i / 100 for i in range(51, 100)]
    misses = {
        t: _ulps_below(ev.noul_confidence([t])[0], round(2 * t - 1, 2))
        for t in ts
        if ev.noul_confidence([t])[0] < round(2 * t - 1, 2)
    }
    assert misses == _TYPED_GATE_MISSES
    assert len(misses) == 16
    assert 0.6 in misses
    assert 0.85 not in misses
    # Clear of the edge the floor holds with no exception.
    grid = [i / 400 for i in range(401)]
    for t in ts:
        g = 2 * t - 1 - 1e-9
        assert all(ev.noul_confidence([p])[0] >= g for p in grid if p >= t), t
        # ... and so does the gate the contract mandates, frozen at an observed confidence of an
        # item at or below t (here the item at t itself): noul_confidence is monotone on [0.5, 1].
        g = ev.noul_confidence([t])[0]
        assert all(ev.noul_confidence([p])[0] >= g for p in grid if p >= t), t


def test_typed_gate_at_two_t_minus_one_withholds_the_admitted_value_at_t_in_a_composition():
    # Compose the real helpers: an accept-only gate, applied with evaluate_selective to every
    # admitted p (p >= t) on a 0.00025-step grid. The typed gate round(2t - 1, 2) withholds
    # exactly the one value p = t for each of the 16 thresholds that miss by an ULP or more; the
    # gate frozen by select_confidence_threshold on a validation pool containing that item (the
    # contract's construction) withholds nothing.
    grid = [i / 4000 for i in range(4001)]
    for t in _TYPED_GATE_MISSES:
        admitted = [p for p in grid if p >= t]
        assert t in admitted  # i / 4000 and t = j / 100 are the same correctly rounded double
        conf = ev.noul_confidence(admitted)
        everything_right = [1] * len(admitted)
        typed = ev.evaluate_selective(everything_right, conf, round(2 * t - 1, 2))
        assert typed.n_answered == len(admitted) - 1, t
        withheld = [p for p, c in zip(admitted, conf, strict=True) if c < round(2 * t - 1, 2)]
        assert withheld == [t], t
        clear = ev.evaluate_selective(everything_right, conf, 2 * t - 1 - 1e-9)
        assert clear.n_answered == len(admitted), t
    # The frozen construction at t = 0.6: a validation pool whose lowest-confidence item is 0.6.
    val = [0.6, 0.62, 0.7, 0.95, 0.05]
    frozen = ev.select_confidence_threshold([1] * 5, ev.noul_confidence(val), min_coverage=0.5)
    assert frozen == ev.noul_confidence([0.6])[0] == 0.19999999999999996
    admitted = [p for p in grid if p >= 0.6]
    conf = ev.noul_confidence(admitted)
    assert ev.evaluate_selective([1] * len(admitted), conf, frozen).n_answered == len(admitted)
    assert ev.evaluate_selective([1] * len(admitted), conf, 0.2).n_answered == len(admitted) - 1


def test_reject_side_band_edge_disagrees_with_the_real_comparison_for_a_frozen_gate():
    # A gate frozen by select_confidence_threshold is an observed confidence g = |2p_i - 1|, so
    # p_i sits exactly on its own band edge in real arithmetic. Below 0.5 the computed edge
    # (1 - g)/2 can land above p_i. Hand-computed: p = 0.1, g = 2 * (1 - 0.1) - 1 = 0.8, and
    # (1 - 0.8)/2 = 0.09999999999999998 (< 0.1), so the band statement puts p = 0.1 in review.
    g = ev.noul_confidence([0.1])[0]
    assert g == 0.8
    assert (1 - g) / 2 == 0.09999999999999998 < 0.1
    # The real comparison passes it, and so does evaluate_selective on a pool frozen at it.
    val = [0.1, 0.02, 0.97]
    frozen = ev.select_confidence_threshold([1] * 3, ev.noul_confidence(val), min_coverage=1.0)
    assert frozen == g
    assert ev.evaluate_selective([1], ev.noul_confidence([0.1]), frozen).n_answered == 1
    assert (1 - frozen) / 2 < 0.1 < (1 + frozen) / 2  # band statement: review
    # Exhaustive over the 50 two-decimal p in 0.00 ... 0.49: the band disagrees for exactly 16.
    below = [i / 100 for i in range(0, 50)]
    disagree = [
        p
        for p in below
        if (1 - ev.noul_confidence([p])[0]) / 2 < p < (1 + ev.noul_confidence([p])[0]) / 2
    ]
    assert disagree == [
        0.08, 0.09, 0.10, 0.11,
        0.18, 0.19, 0.20, 0.21, 0.22, 0.23,
        0.41, 0.42, 0.43, 0.44, 0.45, 0.46,
    ]  # fmt: skip
    assert len(disagree) == 16
    # ... and for none of the two-decimal p above 0.5 (0.5 itself has g = 0 and an empty band).
    above = [i / 100 for i in range(51, 101)]
    assert [
        p
        for p in above
        if (1 - ev.noul_confidence([p])[0]) / 2 < p < (1 + ev.noul_confidence([p])[0]) / 2
    ] == []
    # The accept side stays clean on a fine grid too: p >= (1 + g)/2 whenever g = |2p - 1|.
    fine = [0.5 + i / 200000 for i in range(1, 100001)]
    assert all(p >= (1 + ev.noul_confidence([p])[0]) / 2 for p in fine)


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


RECIPE_10 = REPO / "recipes" / "10-answer-relevance-check"
RECIPE_11 = REPO / "recipes" / "11-clarification-selection"
RECIPE_13 = REPO / "recipes" / "13-candidate-rewrite-selection"
RECIPE_15 = REPO / "recipes" / "15-sensitive-text-triage"


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
    "accepted_and_correct": lambda: ev.accepted_and_correct(
        [], [], accepted_when=bool, label_of=str
    ),
    "action_error_rate": lambda: ev.action_error_rate([], [], acts_when=bool, label_of=str),
    "outcome_breakdown": lambda: ev.outcome_breakdown([], []),
    "outcome_curve": lambda: ev.outcome_curve([], []),
    "reliability_table": lambda: ev.reliability_table([], []),
    "expected_calibration_error": lambda: ev.expected_calibration_error([], []),
    "paired_bootstrap_difference": lambda: ev.paired_bootstrap_difference([], [], seed=0),
    "sum_usage": lambda: ev.sum_usage([]),
    "transition_metrics": lambda: ev.transition_metrics([], [], tolerance_seconds=0.5),
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


# ----------------------------------------------------------------------- transition_metrics


def test_transition_metrics_hand_computed():
    gold = [
        ("opened", 2.0),
        ("closed", 5.0),
        ("unchanged", None),
        ("opened", 1.0),
        ("closed", 4.0),
    ]
    pred = [
        ("opened", 2.0),  # exact
        ("closed", 5.4),  # right label, 0.4 s late: within 0.5 but not exact
        ("unchanged", None),  # exact (no time on either side)
        ("uncertain", None),  # review
        ("opened", 4.0),  # wrong label at the right second: wrong, and not a timing success
    ]
    m = ev.transition_metrics(gold, pred, tolerance_seconds=0.5)
    # 5 examples, 1 uncertain, 4 resolved; exact = ex0 + ex2 = 2; within = 3
    assert (m.n_examples, m.n_uncertain, m.n_resolved) == (5, 1, 4)
    assert (m.exact_correct, m.tolerance_correct) == (2, 3)
    assert m.exact_accuracy == 0.5
    assert m.tolerance_accuracy == 0.75
    assert m.exact_accuracy_all == 0.4
    assert m.tolerance_accuracy_all == 0.6
    assert m.uncertain_rate == 0.2
    assert m.tolerance_seconds == 0.5
    # headline timing: label-matched examples with times on both sides = ex0, ex1
    # errors 0.0 and +0.4: mean absolute 0.2, mean signed 0.2
    assert m.n_timed == 2
    assert m.mean_absolute_error_seconds == pytest.approx(0.2)
    assert m.mean_signed_error_seconds == pytest.approx(0.2)
    # any-label view adds ex4 (error 0.0): 3 examples, mean 0.4 / 3
    assert m.n_timed_any_label == 3
    assert m.mean_absolute_error_any_label_seconds == pytest.approx(0.4 / 3)
    assert m.mean_signed_error_any_label_seconds == pytest.approx(0.4 / 3)
    assert (m.n_missed_time, m.n_spurious_time) == (0, 0)
    assert m.outcomes == ("exact", "within", "exact", "review", "wrong")
    assert m.timing_errors_seconds[0] == 0.0
    assert m.timing_errors_seconds[1] == pytest.approx(0.4)
    assert m.timing_errors_seconds[2:] == (None, None, None)
    assert math.isnan(m.max_sampling_interval_seconds)
    assert m.tolerance_below_sampling_interval is False


def test_transition_metrics_wrong_label_at_the_right_second_is_not_good_timing():
    m = ev.transition_metrics([("opened", 2.0)], [("closed", 2.0)], tolerance_seconds=0.5)
    assert (m.exact_correct, m.tolerance_correct) == (0, 0)
    assert m.n_timed == 0
    assert math.isnan(m.mean_absolute_error_seconds)
    assert m.n_timed_any_label == 1
    assert m.mean_absolute_error_any_label_seconds == 0.0
    assert m.outcomes == ("wrong",)


def test_transition_metrics_signed_error_shows_early_and_late():
    gold = [("opened", 5.0), ("opened", 5.0)]
    pred = [("opened", 4.0), ("opened", 5.5)]
    m = ev.transition_metrics(gold, pred, tolerance_seconds=1.0)
    # errors -1.0 and +0.5: mean absolute 0.75, mean signed -0.25
    assert m.mean_absolute_error_seconds == 0.75
    assert m.mean_signed_error_seconds == -0.25
    assert (m.exact_correct, m.tolerance_correct) == (0, 2)
    assert m.outcomes == ("within", "within")


def test_transition_metrics_missing_and_spurious_times():
    gold = [("opened", 1.0), ("unchanged", None)]
    pred = [("opened", None), ("opened", 3.0)]
    m = ev.transition_metrics(gold, pred, tolerance_seconds=10.0)
    # ex0 right label but no time; ex1 wrong label with an invented time
    assert (m.n_missed_time, m.n_spurious_time) == (1, 1)
    assert (m.exact_correct, m.tolerance_correct) == (0, 0)
    assert m.n_timed == 0 and m.n_timed_any_label == 0
    assert math.isnan(m.mean_absolute_error_seconds)
    assert math.isnan(m.mean_signed_error_seconds)
    assert math.isnan(m.mean_absolute_error_any_label_seconds)
    assert m.outcomes == ("wrong", "wrong")


def test_transition_metrics_all_uncertain_has_nan_resolved_accuracy():
    m = ev.transition_metrics(
        [("opened", 1.0), ("closed", 2.0)],
        [("uncertain", None), ("uncertain", 2.0)],
        tolerance_seconds=0.0,
    )
    assert (m.n_uncertain, m.n_resolved) == (2, 0)
    assert math.isnan(m.exact_accuracy) and math.isnan(m.tolerance_accuracy)
    assert m.exact_accuracy_all == 0.0 and m.uncertain_rate == 1.0
    assert m.n_timed == 0
    assert m.outcomes == ("review", "review")


def test_transition_metrics_single_example():
    m = ev.transition_metrics([("opened", 0.0)], [("opened", 0.0)], tolerance_seconds=0)
    assert (m.n_examples, m.exact_accuracy, m.tolerance_accuracy) == (1, 1.0, 1.0)
    assert m.mean_absolute_error_seconds == 0.0


def test_transition_metrics_tolerance_is_inclusive_and_float_safe():
    gold = [("opened", 1.0), ("opened", 0.3), ("opened", 1.0)]
    pred = [("opened", 1.5), ("opened", 0.1 + 0.2), ("opened", 1.5000001)]
    m = ev.transition_metrics(gold, pred, tolerance_seconds=0.5)
    # gap 0.5 is inside; 0.3 vs 0.30000000000000004 is exact; 0.5000001 is outside
    assert m.tolerance_correct == 2
    assert m.exact_correct == 1
    assert m.outcomes == ("within", "exact", "wrong")
    zero = ev.transition_metrics(gold[:1], gold[:1], tolerance_seconds=0)
    assert zero.tolerance_correct == 1


def test_transition_metrics_accepts_json_lists_and_numpy_numbers():
    m = ev.transition_metrics(
        [["a", np.float64(1.0)], ["b", None]],
        [["a", np.float64(1.0)], ["b", None]],
        tolerance_seconds=np.float64(0.1),
    )
    assert (m.exact_correct, m.n_examples) == (2, 2)


def test_transition_metrics_several_review_labels():
    m = ev.transition_metrics(
        [("s1", 1.0), ("s2", 2.0), ("s3", 3.0), ("s1", 1.0)],
        [("unknown", None), ("inconsistent", 2.0), ("s3", 3.0), ("uncertain", None)],
        tolerance_seconds=0.5,
        uncertain_labels=("unknown", "inconsistent"),
    )
    # "uncertain" is an ordinary label here, so ex3 is simply wrong
    assert (m.n_uncertain, m.n_resolved, m.exact_correct) == (2, 2, 1)
    assert m.outcomes == ("review", "review", "exact", "wrong")
    # a bare string is one label, not a set of characters
    single = ev.transition_metrics(
        [("a", None)], [("review", None)], tolerance_seconds=0, uncertain_labels="review"
    )
    assert single.n_uncertain == 1
    none = ev.transition_metrics(
        [("a", None)], [("uncertain", None)], tolerance_seconds=0, uncertain_labels=()
    )
    assert none.n_uncertain == 0 and none.outcomes == ("wrong",)


def test_transition_metrics_rejects_missing_or_bad_review_labels():
    for bad in (None, 3, 2.5):
        with pytest.raises(ValueError, match="uncertain_labels"):
            ev.transition_metrics(
                [("a", None)], [("a", None)], tolerance_seconds=0, uncertain_labels=bad
            )


def test_transition_metrics_sampling_interval_warning():
    gold = [("opened", 2.5)]
    pred = [("opened", 3.0)]
    narrow = ev.transition_metrics(
        gold, pred, tolerance_seconds=0.5, max_sampling_interval_seconds=1.0
    )
    assert narrow.max_sampling_interval_seconds == 1.0
    assert narrow.tolerance_below_sampling_interval is True
    wide = ev.transition_metrics(
        gold, pred, tolerance_seconds=1.0, max_sampling_interval_seconds=1.0
    )
    assert wide.tolerance_below_sampling_interval is False


def test_transition_convention_end_to_end():
    from jev_cookbook import frames as fr

    # full-rate frames every 0.5 s; the door is first visibly open in the frame at 2.5 s
    full = [{"timestamp_seconds": t / 2, "image": f"i{t}"} for t in range(7)]
    gold_time = fr.transition_time(full, 5)
    assert gold_time == 2.5
    # Python samples every 1.0 s -> frames at 0, 1, 2, 3; the per-pair question fires for 2 -> 3
    sampled = fr.select_frames(full, fr.sample_frames(fr.frame_timestamps(full), every_seconds=1))
    assert [r["timestamp_seconds"] for r in sampled] == [0.0, 1.0, 2.0, 3.0]
    found = fr.earliest_transition(sampled, [False, False, True])
    assert found["transition_seconds"] == 3.0  # first sampled frame showing the new state
    interval = max(fr.frame_intervals(sampled))
    assert interval == 1.0
    # detection on sampled frames is late by 0.5 s (less than the 1.0 s gap), never early
    m = ev.transition_metrics(
        [("opened", gold_time)],
        [("opened", found["transition_seconds"])],
        tolerance_seconds=interval,
        max_sampling_interval_seconds=interval,
    )
    assert m.outcomes == ("within",)
    assert m.mean_signed_error_seconds == 0.5
    assert m.tolerance_below_sampling_interval is False


@pytest.mark.parametrize(
    "gold,pred,tolerance",
    [
        ([("a", 1.0)], [("a", 1.0), ("a", 2.0)], 0.5),
        ([], [("a", 1.0)], 0.5),
        ([("a", 1.0)], [], 0.5),
        (["a"], [("a", 1.0)], 0.5),
        ([("a", 1.0)], [("a",)], 0.5),
        ([("a", 1.0)], [("a", 1.0, 2.0)], 0.5),
        ([("a", -1.0)], [("a", 1.0)], 0.5),
        ([("a", 1.0)], [("a", math.nan)], 0.5),
        ([("a", 1.0)], [("a", math.inf)], 0.5),
        ([("a", 1.0)], [("a", 10**400)], 0.5),
        ([("a", True)], [("a", 1.0)], 0.5),
        ([("a", "1")], [("a", 1.0)], 0.5),
        ([("uncertain", None)], [("a", 1.0)], 0.5),
        ([("a", 1.0)], [("a", 1.0)], -0.1),
        ([("a", 1.0)], [("a", 1.0)], math.nan),
        ([("a", 1.0)], [("a", 1.0)], 10**400),
        ([("a", 1.0)], [("a", 1.0)], True),
        ([("a", 1.0)], [("a", 1.0)], None),
    ],
)
def test_transition_metrics_rejects_bad_input(gold, pred, tolerance):
    with pytest.raises(ValueError):
        ev.transition_metrics(gold, pred, tolerance_seconds=tolerance)


def test_transition_metrics_rejects_bad_interval():
    for bad in (-1.0, math.nan, True, 10**400):
        with pytest.raises(ValueError):
            ev.transition_metrics(
                [("a", 1.0)], [("a", 1.0)], tolerance_seconds=0.5, max_sampling_interval_seconds=bad
            )


def test_transition_metrics_requires_a_keyword_tolerance():
    with pytest.raises(TypeError):
        ev.transition_metrics([("a", 1.0)], [("a", 1.0)])  # type: ignore[call-arg]


# ---------------------------------------------------------------- ranking family: one input contract (#356)


def test_ndcg_takes_noul_answers_exactly_as_the_other_ranking_helpers_do():
    # rel [1, 0], scores 0.9 > 0.1: best order -> 1.0 ; reversed scores: DCG = 0 + 1/log2(3),
    # IDCG = 1. Before #356 a Noul answer raised TypeError here (only .score was extracted).
    good = [NoulStub(0.9), NoulStub(0.1)]
    bad = [NoulStub(0.1), NoulStub(0.9)]
    assert ev.ndcg([1, 0], good) == pytest.approx(1.0)
    assert ev.ndcg([1, 0], bad) == pytest.approx(1 / math.log2(3))
    prov = ans.Provenance.synthetic()
    real = [ans.NoulAnswer(0.9, prov), ans.NoulAnswer(0.1, prov)]
    assert ev.ndcg([1, 0], real) == pytest.approx(1.0)
    # a mixed list of Noul and Score answers is the same call on the plain numbers
    mixed = [NoulStub(0.2), ScoreStub(0.9, confidence=0.5), NoulStub(0.4)]
    plain = [0.2, 0.9, 0.4]
    assert ev.ndcg([0, 1, 1], mixed) == ev.ndcg([0, 1, 1], plain)
    assert ev.mean_ndcg([([0, 1, 1], mixed), ([1, 0], good)]) == ev.mean_ndcg(
        [([0, 1, 1], plain), ([1, 0], [0.9, 0.1])]
    )
    # the ranking-family helpers take one Noul/Score list identically
    rel = [0, 1, 1]
    assert ev.recall_at_budget(rel, mixed, 1) == ev.recall_at_budget(rel, plain, 1)


def test_mean_recall_at_budget_is_the_fsum_mean_and_independent_of_query_order():
    # Three queries of 12 items with 10 relevant, budget 3, scores descending by position: the
    # top 3 hold 1, 2 and 3 relevant items, so the per-query recalls are 1/10, 2/10, 3/10, i.e.
    # 0.1, 0.2, 0.3. Summed left to right those give 0.6000000000000001 (np.mean: 0.2000...04);
    # math.fsum gives 0.6, so the mean is 0.6 / 3 = 0.19999999999999998, in every query order.
    sc = [1.0 - 0.01 * i for i in range(12)]
    qs = [
        ([1, 0, 0] + [1] * 9, sc),
        ([1, 1, 0] + [1] * 8 + [0], sc),
        ([1, 1, 1] + [1] * 7 + [0, 0], sc),
    ]
    assert [ev.recall_at_budget(r, s, 3) for r, s in qs] == [0.1, 0.2, 0.3]
    expected = math.fsum([0.1, 0.2, 0.3]) / 3
    assert expected == 0.19999999999999998
    for perm in itertools.permutations(qs):
        assert ev.mean_recall_at_budget(list(perm), 3) == expected


def test_mean_ndcg_is_the_fsum_mean_and_independent_of_query_order():
    # per-list nDCG 0.8599797111848092, 0.9158928585785953, 0.9224945116765986 (each from a
    # 4-item list below): the left-to-right np.mean is 0.8994556938133345, the exactly rounded
    # sum over 3 is 0.8994556938133343, which is also what every query order must give.
    qs = [
        (
            [1, 0, 1, 2],
            [0.9967268145367039, 0.16152946442461624, 0.04855216354845626, 0.9866991087842674],
        ),
        (
            [3, 0, 1, 2],
            [0.8262955117986266, 0.45566510149066475, 0.42175728191158934, 0.05570723100789343],
        ),
        (
            [0, 3, 2, 1],
            [0.13057182715312, 0.7316644233766765, 0.9497985626218988, 0.6303992934263946],
        ),
    ]
    each = [ev.ndcg(r, s) for r, s in qs]
    expected = math.fsum(each) / 3
    assert expected == 0.8994556938133343
    for perm in itertools.permutations(qs):
        assert ev.mean_ndcg(list(perm)) == expected


def test_mean_recall_at_budget_reads_each_query_once_so_a_one_shot_iterable_still_works():
    # Before #356 `len(q)` made a generator query raise TypeError where unpacking had worked,
    # and a four-item one raised TypeError rather than the documented ValueError.
    one_shot = iter([[1, 0], [0.9, 0.1]])
    assert ev.mean_recall_at_budget([one_shot], 1) == 1.0
    gated = iter([[1, 1, 0], [0.9, 0.8, 0.1], [1, 0, 1]])
    assert ev.mean_recall_at_budget([gated], 2) == 0.5
    with pytest.raises(ValueError, match="each query must be"):
        ev.mean_recall_at_budget([iter([[1], [0.5], [1], [1]])], 1)
    with pytest.raises(ValueError, match="each query must be"):
        ev.mean_recall_at_budget([([1],)], 1)


def test_top_k_query_accuracy_names_the_missing_eligible_argument_for_a_three_tuple():
    # The docstring says this helper has no `eligible`; the three-tuple mean_recall_at_budget
    # takes used to die with "too many values to unpack (expected 2)".
    with pytest.raises(ValueError, match="no eligible argument"):
        ev.top_k_query_accuracy([([1, 0], [0.9, 0.1], [1, 1])])
    with pytest.raises(ValueError, match="pair"):
        ev.top_k_query_accuracy([([1, 0],)])
    with pytest.raises(ValueError, match="pair"):
        ev.top_k_query_accuracy([([1], [0.5], [1], [1])])
    # a one-shot pair is still a pair
    assert ev.top_k_query_accuracy([iter([[1, 0], [0.9, 0.1]])]) == 1.0


# ---------------------------------------------------------------- (accepted, correct) pair, action error rate, breakdown (#161)


@dataclass
class Res:
    ticket_id: str
    outcome: str
    label: str


# t1 linked A (gold A: right) ; t2 review B (gold Z: wrong, not accepted) ;
# t3 no_match none (gold none: right) ; t4 linked C (gold D: wrong)
RES = [
    Res("t1", "linked", "A"),
    Res("t2", "review", "B"),
    Res("t3", "no_match", "none"),
    Res("t4", "linked", "C"),
]
GOLD_BY_ID = {"t1": "A", "t2": "Z", "t3": "none", "t4": "D"}


def _answered(r):
    return r.outcome != "review"


def test_accepted_and_correct_is_the_pair_evaluate_outcomes_takes():
    accepted, correct = ev.accepted_and_correct(
        RES,
        GOLD_BY_ID,
        accepted_when=_answered,
        label_of=lambda r: r.label,
        key_of=lambda r: r.ticket_id,
    )
    # accepted: t1 yes, t2 no (review), t3 yes, t4 yes ; correct is computed for EVERY result,
    # the review one included (B != Z): right, wrong, right, wrong
    assert accepted == [True, False, True, True]
    assert correct == [True, False, True, False]
    r = ev.evaluate_outcomes(accepted, correct)
    # 3 of 4 answered; of those t1 and t3 right -> accuracy 2/3
    assert (r.n_total, r.n_answered, r.coverage) == (4, 3, 0.75)
    assert r.accuracy == pytest.approx(2 / 3)
    # a parallel gold sequence is the same call, with no key_of
    seq = ev.accepted_and_correct(
        RES, ["A", "Z", "none", "D"], accepted_when=_answered, label_of=lambda r: r.label
    )
    assert seq == (accepted, correct)


def test_accepted_and_correct_rejects_a_bad_gold_or_empty_results():
    kw = {"accepted_when": lambda r: True, "label_of": lambda r: r.label}
    with pytest.raises(ValueError, match="needs key_of"):
        ev.accepted_and_correct(RES, GOLD_BY_ID, **kw)
    with pytest.raises(ValueError, match="no gold label for key 't2'"):
        ev.accepted_and_correct(RES, {"t1": "A"}, key_of=lambda r: r.ticket_id, **kw)
    with pytest.raises(ValueError, match="key_of only applies"):
        ev.accepted_and_correct(RES, ["A"] * 4, key_of=lambda r: r.ticket_id, **kw)
    with pytest.raises(ValueError, match="same length"):
        ev.accepted_and_correct(RES, ["A"], **kw)
    with pytest.raises(ValueError, match="empty"):
        ev.accepted_and_correct([], ["A"], **kw)


def test_action_error_rate_counts_only_wrong_results_that_acted():
    kw = {
        "acts_when": lambda r: r.outcome == "linked",
        "label_of": lambda r: r.label,
        "key_of": lambda r: r.ticket_id,
    }
    # linked results are t1 (right) and t4 (wrong): 1 of 2
    assert ev.action_error_rate(RES, GOLD_BY_ID, **kw) == 0.5
    # a wrong no_match (accepted, wrong, but no side effect) lowers accuracy and not this rate
    extra = [*RES, Res("t5", "no_match", "none")]
    gold = {**GOLD_BY_ID, "t5": "X1"}
    assert ev.action_error_rate(extra, gold, **kw) == 0.5
    acc, ok = ev.accepted_and_correct(
        extra, gold, accepted_when=_answered, label_of=lambda r: r.label, key_of=kw["key_of"]
    )
    # answered: t1, t3, t4, t5; right: t1, t3 -> 2 of 4
    assert ev.evaluate_outcomes(acc, ok).accuracy == pytest.approx(2 / 4)
    # nothing acted: undefined is NaN, never 0.0
    assert nan(ev.action_error_rate(RES, GOLD_BY_ID, **{**kw, "acts_when": lambda r: False}))
    with pytest.raises(ValueError, match="empty"):
        ev.action_error_rate([], {}, **kw)
    with pytest.raises(ValueError, match="needs key_of"):
        ev.action_error_rate(RES, GOLD_BY_ID, **{k: v for k, v in kw.items() if k != "key_of"})


def test_outcome_breakdown_tallies_each_outcome_by_right_and_wrong():
    outcomes = ["ans", "rev", "ans", "none", "ans", "rev"]
    correct = [1, 0, 0, 1, 1, 1]
    tally = ev.outcome_breakdown(outcomes, correct)
    # first-occurrence order; ans: examples 0, 2, 4 -> right, wrong, right ; rev: 1, 5 ->
    # wrong, right ; none: 3 -> right
    assert list(tally) == ["ans", "rev", "none"]
    assert tally["ans"] == ev.OutcomeTally(right=2, wrong=1)
    assert tally["rev"] == ev.OutcomeTally(right=1, wrong=1)
    assert tally["none"] == ev.OutcomeTally(right=1, wrong=0)
    assert sum(t.total for t in tally.values()) == len(outcomes)
    assert tally["ans"].accuracy == pytest.approx(2 / 3)
    # a stable table shape: an outcome that never happened is listed with zero counts and NaN
    ordered = ev.outcome_breakdown(outcomes, correct, order=["none", "ans", "rev", "absent"])
    assert list(ordered) == ["none", "ans", "rev", "absent"]
    assert ordered["absent"] == ev.OutcomeTally(0, 0)
    assert nan(ordered["absent"].accuracy)
    with pytest.raises(ValueError, match="not among the order"):
        ev.outcome_breakdown(outcomes, correct, order=["ans", "rev"])
    with pytest.raises(ValueError):
        ev.outcome_breakdown([], [])
    with pytest.raises(ValueError):
        ev.outcome_breakdown(["a"], [1, 0])
    with pytest.raises(ValueError):
        ev.outcome_breakdown(["a"], [2])


# ---------------------------------------------------------------- outcome_curve with a REJECT branch (#161)


def test_outcome_curve_rejected_examples_are_never_selected_whatever_their_confidence():
    # confidences 0.9 0.8 0.7 0.6, correct 1 1 0 1, example 1 (0.8) is rejected outright.
    # t=0.9: {0}: coverage 1/4, accuracy 1 ; t=0.8: {0,1} minus the rejected 1 = {0}: 1/4, 1 ;
    # t=0.7: {0,2}: 2/4, accuracy 1/2 ; t=0.6: {0,2,3}: 3/4, accuracy 2/3
    conf = [0.9, 0.8, 0.7, 0.6]
    c = ev.outcome_curve(conf, [1, 1, 0, 1], rejected=[False, True, False, False])
    assert c.thresholds.tolist() == [0.9, 0.8, 0.7, 0.6]
    assert c.coverage.tolist() == [0.25, 0.25, 0.5, 0.75]
    assert c.accuracy.tolist() == pytest.approx([1.0, 1.0, 0.5, 2 / 3])
    assert c.risk.tolist() == pytest.approx([0.0, 0.0, 0.5, 1 / 3])
    # the frozen-gate row is what the rule's own accounting gives (the point of the curve)
    gate = 0.7
    accepted = [cf >= gate and not rj for cf, rj in zip(conf, [0, 1, 0, 0], strict=True)]
    own = ev.evaluate_outcomes(accepted, [1, 1, 0, 1])
    row = list(c.thresholds).index(gate)
    assert (c.coverage[row], c.accuracy[row]) == (own.coverage, own.accuracy)
    # without the rejected mask the same call reports the confidence-only numbers instead
    plain = ev.outcome_curve(conf, [1, 1, 0, 1])
    assert plain.coverage[1] == 0.5 and c.coverage[1] == 0.25


def test_outcome_curve_rejected_combines_with_exempt_and_matches_evaluate_outcomes_per_row():
    conf = [0.95, 0.90, 0.60, 0.50, 0.40, 0.30]
    correct = [1, 1, 0, 1, 0, 1]
    exempt = [False, False, False, False, False, True]
    rejected = [False, True, False, False, True, False]
    c = ev.outcome_curve(conf, correct, exempt=exempt, rejected=rejected)
    for t, cov, acc in zip(c.thresholds, c.coverage, c.accuracy, strict=True):
        accepted = [
            (not rj) and (ex or cf >= t) for cf, ex, rj in zip(conf, exempt, rejected, strict=True)
        ]
        own = ev.evaluate_outcomes(accepted, correct)
        assert cov == own.coverage
        assert acc == own.accuracy or (nan(acc) and nan(own.accuracy))
    # by hand at t=0.5: confident enough and not rejected are 0 (0.95), 2 (0.60), 3 (0.50) ;
    # the exempt 5 is always in -> {0, 2, 3, 5}: coverage 4/6, correct 1 0 1 1 -> accuracy 3/4
    row = list(c.thresholds).index(0.5)
    assert c.coverage[row] == pytest.approx(4 / 6)
    assert c.accuracy[row] == pytest.approx(3 / 4)


def test_outcome_curve_with_everything_rejected_selects_nothing_and_is_nan_not_zero():
    c = ev.outcome_curve([0.9, 0.5], [1, 0], rejected=[True, True])
    assert c.coverage.tolist() == [0.0, 0.0]
    assert all(nan(a) for a in c.accuracy) and all(nan(r) for r in c.risk)


def test_outcome_curve_rejected_validation():
    with pytest.raises(ValueError, match="both exempt and rejected"):
        ev.outcome_curve([0.9, 0.5], [1, 0], exempt=[True, False], rejected=[True, False])
    with pytest.raises(ValueError, match="same length"):
        ev.outcome_curve([0.9, 0.5], [1, 0], rejected=[True])
    with pytest.raises(ValueError):
        ev.outcome_curve([0.9, 0.5], [1, 0], rejected=[2, 0])
    with pytest.raises(TypeError):  # keyword-only
        ev.outcome_curve([0.9, 0.5], [1, 0], None, [True, False])  # type: ignore[misc]
