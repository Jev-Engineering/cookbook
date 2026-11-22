"""Offline public-contract regressions for the evaluation follow-ups."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from jev_cookbook import evaluation as ev


@dataclass
class Result:
    key: Any
    label: Any
    flag: Any = True


def accounting(function, results, gold, **kwargs):
    """Exercise either public accounting function with the same result shape."""
    predicate = "accepted_when" if function is ev.accepted_and_correct else "acts_when"
    return function(
        results, gold, **{predicate: lambda r: r.flag}, label_of=lambda r: r.label, **kwargs
    )


ACCOUNTING = [ev.accepted_and_correct, ev.action_error_rate]
RANKING = [
    pytest.param(ev.mean_ndcg, {}, id="mean_ndcg"),
    pytest.param(ev.mean_recall_at_budget, {"budget": 1}, id="mean_recall_at_budget"),
    pytest.param(ev.top_k_query_accuracy, {}, id="top_k_query_accuracy"),
]


@pytest.mark.parametrize("nan", [float("nan"), np.float64("nan"), np.float32("nan")])
@pytest.mark.parametrize("in_order", [False, True])
def test_breakdown_rejects_nan_labels_even_for_an_unused_order_entry(nan, in_order):
    kwargs = {"order": ["answered", nan]} if in_order else {}
    outcomes = ["answered"] if in_order else [nan]
    with pytest.raises(ValueError, match="(?i)nan"):
        ev.outcome_breakdown(outcomes, [True], **kwargs)


def test_breakdown_rejects_distinct_nan_objects_instead_of_unretrievable_rows():
    with pytest.raises(ValueError, match="(?i)nan"):
        ev.outcome_breakdown([float("nan"), float("nan")], [True, False])


@pytest.mark.parametrize("container", [tuple, frozenset])
def test_breakdown_keeps_composite_label_python_equality(container):
    # The kind rule is scalar: equal composite labels retain ordinary dictionary equality.
    integer = container([1])
    boolean = container([True])
    result = ev.outcome_breakdown([integer, boolean], [True, False])
    assert result == {integer: ev.OutcomeTally(1, 1)}
    assert result[boolean].total == 2


@pytest.mark.parametrize("left,right", [(True, 1), (1, 1.0), (np.bool_(True), 1)])
def test_breakdown_still_rejects_scalar_kind_collisions(left, right):
    with pytest.raises(ValueError, match="different kinds"):
        ev.outcome_breakdown([left, right], [True, False])


def test_breakdown_keeps_null_and_numpy_scalar_labels_and_zero_count_rows():
    result = ev.outcome_breakdown([None, 7, np.int64(7)], [True, True, False], order=[7, None, 9])
    assert list(result) == [7, None, 9]
    assert result[7] == ev.OutcomeTally(1, 1)
    assert result[None] == ev.OutcomeTally(1, 0)
    assert result[9] == ev.OutcomeTally(0, 0)
    assert np.isnan(result[9].accuracy)


@pytest.mark.parametrize("in_order", [False, True])
def test_breakdown_unhashable_label_still_has_clear_value_error(in_order):
    kwargs = {"order": [["unhashable"]]} if in_order else {}
    outcomes = ["answered"] if in_order else [["unhashable"]]
    with pytest.raises(ValueError, match="not hashable"):
        ev.outcome_breakdown(outcomes, [True], **kwargs)


def test_breakdown_duplicate_order_and_missing_outcome_still_raise():
    with pytest.raises(ValueError, match="listed twice"):
        ev.outcome_breakdown(["answered"], [True], order=["answered", "answered"])
    with pytest.raises(ValueError, match="not among the order"):
        ev.outcome_breakdown(["review"], [False], order=["answered"])


def test_action_error_rate_allows_mapping_gold_only_for_acting_examples():
    rows = [
        Result("review", None, False),
        Result("right", "A"),
        Result("no_match", None, False),
        Result("wrong", "C"),
    ]
    keyed = []
    labelled = []

    def key_of(row):
        assert row.flag, "non-acting results do not need a gold key"
        keyed.append(row.key)
        return row.key

    def label_of(row):
        assert row.flag, "non-acting results do not need a predicted label"
        labelled.append(row.key)
        return row.label

    assert (
        ev.action_error_rate(
            iter(rows),
            {"right": "A", "wrong": "D"},
            acts_when=lambda r: r.flag,
            label_of=label_of,
            key_of=key_of,
        )
        == 0.5
    )
    assert keyed == ["right", "wrong"]
    assert labelled == ["right", "wrong"]


def test_action_error_rate_no_acting_results_needs_neither_keys_nor_labels():
    def unexpected(_):
        pytest.fail("no acting result should need a key or label")

    rate = ev.action_error_rate(
        [None, None], {}, acts_when=lambda _: False, key_of=unexpected, label_of=unexpected
    )
    assert np.isnan(rate)


def test_action_error_rate_sequence_gold_stays_aligned_across_nonacting_rows():
    rows = [Result("skip", None, False), Result("a", "A"), Result("b", "B")]
    assert accounting(ev.action_error_rate, iter(rows), ["unused", "A", "wrong"]) == 0.5


@pytest.mark.parametrize("gold", [["A"], ["A", "B", "C"]])
@pytest.mark.parametrize("acting", [False, True])
def test_action_error_rate_requires_a_parallel_gold_sequence_even_when_none_act(gold, acting):
    with pytest.raises(ValueError, match="same length"):
        accounting(ev.action_error_rate, [Result("a", "A", acting), Result("b", "B", False)], gold)


@pytest.mark.parametrize("function", ACCOUNTING)
def test_accounting_missing_acting_gold_is_still_an_error(function):
    with pytest.raises(ValueError, match="no gold label"):
        accounting(function, [Result("missing", "A")], {}, key_of=lambda r: r.key)


def test_accepted_and_correct_requires_gold_and_label_for_review_results():
    rows = [Result("review", "held-back", False)]
    assert accounting(ev.accepted_and_correct, rows, ["held-back"]) == ([False], [True])
    with pytest.raises(ValueError, match="no gold label"):
        accounting(ev.accepted_and_correct, rows, {}, key_of=lambda r: r.key)


@pytest.mark.parametrize("function", ACCOUNTING)
def test_accounting_keeps_empty_and_gold_key_configuration_errors(function):
    with pytest.raises(ValueError, match="empty"):
        accounting(function, [], [])
    with pytest.raises(ValueError, match="needs key_of"):
        accounting(function, [Result("a", "A")], {"a": "A"})
    with pytest.raises(ValueError, match="key_of only applies"):
        accounting(function, [Result("a", "A")], ["A"], key_of=lambda r: r.key)
    with pytest.raises(ValueError, match="unhashable key"):
        accounting(function, [Result(["a"], "A")], {"a": "A"}, key_of=lambda r: r.key)


class ObservedGold(Mapping):
    """A mapping that makes the number and order of actual label reads observable."""

    def __init__(self, labels):
        self.labels = labels
        self.reads = []

    def __getitem__(self, key):
        self.reads.append(key)
        return self.labels[key]

    def __iter__(self):
        return iter(self.labels)

    def __len__(self):
        return len(self.labels)


@pytest.mark.parametrize("function", ACCOUNTING)
def test_accounting_resolves_each_mapping_gold_label_once(function):
    gold = ObservedGold({"a": "A", "b": "X"})
    answer = accounting(
        function, [Result("a", "A"), Result("b", "B")], gold, key_of=lambda r: r.key
    )
    assert answer == (([True, True], [True, False]) if function is ev.accepted_and_correct else 0.5)
    assert gold.reads == ["a", "b"]


@pytest.mark.parametrize("function", ACCOUNTING)
@pytest.mark.parametrize("side", ["gold", "prediction"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_accounting_array_labels_raise_clear_value_error_on_both_paths(function, side, wrapped):
    array = np.array([True, False])
    bad = SimpleNamespace(choice=array) if wrapped else array
    gold = [bad] if side == "gold" else ["A"]
    prediction = bad if side == "prediction" else "A"
    with pytest.raises(ValueError, match="(?i)(array|scalar|label)") as error:
        accounting(function, [Result("a", prediction)], gold)
    assert "truth value of an array" not in str(error.value)


@pytest.mark.parametrize("function", ACCOUNTING)
def test_accounting_choice_unwrapping_preserves_null_labels_and_wrong_predictions(function):
    rows = [Result("a", SimpleNamespace(choice=None)), Result("b", "B")]
    answer = accounting(function, rows, [None, SimpleNamespace(choice="X")])
    assert answer == (([True, True], [True, False]) if function is ev.accepted_and_correct else 0.5)


@pytest.mark.parametrize("function", ACCOUNTING)
@pytest.mark.parametrize("side", ["gold", "prediction"])
@pytest.mark.parametrize("answer", [SimpleNamespace(noul=0.7), SimpleNamespace(score=1.0)])
def test_accounting_keeps_rejecting_nonchoice_answers(function, side, answer):
    gold = [answer] if side == "gold" else ["A"]
    prediction = answer if side == "prediction" else "A"
    with pytest.raises(ValueError, match="compares Choice options"):
        accounting(function, [Result("a", prediction)], gold)


@pytest.mark.parametrize("function", ACCOUNTING)
@pytest.mark.parametrize("number", [float, np.float32, np.float64])
def test_accounting_accepts_integral_float_predicates(function, number):
    rows = [Result("a", "A", number(1)), Result("b", "B", number(0)), Result("c", "C", number(1))]
    answer = accounting(function, rows, ["A", "B", "wrong"])
    assert answer == (
        ([True, False, True], [True, True, False]) if function is ev.accepted_and_correct else 0.5
    )


@pytest.mark.parametrize("function", ACCOUNTING)
@pytest.mark.parametrize("flag", [0.5, -1.0, 2.0, np.nan, np.inf, "1", None])
def test_accounting_rejects_nonbinary_or_truthy_predicates(function, flag):
    with pytest.raises(ValueError, match="must return a bool"):
        accounting(function, [Result("a", "A", flag)], ["A"])


@pytest.mark.parametrize("function,kwargs", RANKING)
@pytest.mark.parametrize("exception_type", [TypeError, RuntimeError])
def test_ranking_propagates_actual_exceptions_from_query_generators(
    function, kwargs, exception_type
):
    error = exception_type("synthetic failure after yielding a query component")

    def query():
        yield [1, 0]
        raise error

    with pytest.raises(exception_type) as caught:
        function([query()], **kwargs)
    assert caught.value is error


@pytest.mark.parametrize("function,kwargs", RANKING)
def test_ranking_still_reads_a_valid_generator_query_once(function, kwargs):
    components = ([1, 0], [0.9, 0.1])
    assert function([(component for component in components)], **kwargs) == 1.0


class LargeNonIterable:
    def __repr__(self):
        return "LargeNonIterable(" + "x" * 20_000 + ")"


@pytest.mark.parametrize("function,kwargs", RANKING)
def test_ranking_noniterable_query_error_is_clear_and_bounds_its_repr(function, kwargs):
    with pytest.raises(ValueError, match="each query must be") as caught:
        function([LargeNonIterable()], **kwargs)
    message = str(caught.value)
    assert function.__name__ in message
    assert "LargeNonIterable" in message
    assert len(message) < 1_000


@pytest.mark.parametrize("function,kwargs", RANKING)
def test_ranking_bounds_the_preview_when_repr_fails_and_the_type_name_is_long(function, kwargs):
    def broken_repr(self):
        raise RuntimeError("synthetic repr failure")

    query = type("Q" * 5_000, (), {"__repr__": broken_repr})()
    with pytest.raises(ValueError, match="each query must be") as caught:
        function([query], **kwargs)
    message = str(caught.value)
    assert function.__name__ in message
    assert len(message) < 1_000


class DefaultGold(dict):
    def __missing__(self, key):
        return "A"


@pytest.mark.parametrize("function", ACCOUNTING)
@pytest.mark.parametrize(
    "gold_factory,label",
    [
        pytest.param(lambda: defaultdict(lambda: "A"), "A", id="defaultdict"),
        pytest.param(Counter, 0, id="counter"),
        pytest.param(DefaultGold, "A", id="missing-hook"),
    ],
)
def test_accounting_never_synthesizes_missing_gold_or_mutates_a_default_mapping(
    function, gold_factory, label
):
    gold = gold_factory()
    with pytest.raises(ValueError, match="no gold label"):
        accounting(function, [Result("missing", label)], gold, key_of=lambda r: r.key)
    assert dict(gold) == {}


@pytest.mark.parametrize("function", ACCOUNTING)
def test_accounting_preserves_a_dict_subclass_transformation_for_a_present_label(function):
    class TransformGold(dict):
        def __getitem__(self, key):
            return super().__getitem__(key).upper()

    gold = TransformGold({"present": "a"})
    result = accounting(function, [Result("present", "A")], gold, key_of=lambda r: r.key)
    expected = ([True], [True]) if function is ev.accepted_and_correct else 0.0
    assert result == expected
    assert dict(gold) == {"present": "a"}


@pytest.mark.parametrize("function,kwargs", RANKING)
def test_ranking_null_and_wrong_length_queries_remain_value_errors(function, kwargs):
    for query in (None, ([1],), ([1], [0.5], [1], [1])):
        with pytest.raises(ValueError, match="each query must be"):
            function([query], **kwargs)


def test_outcome_curve_preserves_exempt_confidence_rows_and_duplicate_coverage():
    curve = ev.outcome_curve([0.9, 0.6, 0.2], [True, False, True], exempt=[True, False, False])
    np.testing.assert_array_equal(curve.thresholds, [0.9, 0.6, 0.2])
    np.testing.assert_allclose(curve.coverage, [1 / 3, 2 / 3, 1])
    np.testing.assert_allclose(curve.accuracy, [1, 0.5, 2 / 3])
    # A low-confidence exempt example still contributes a threshold after coverage saturates.
    low = ev.outcome_curve([0.9, 0.2], [True, False], exempt=[False, True])
    np.testing.assert_array_equal(low.thresholds, [0.9, 0.2])
    np.testing.assert_array_equal(low.coverage, [1, 1])
    np.testing.assert_array_equal(low.accuracy, [0.5, 0.5])


def test_outcome_curve_all_rejected_preserves_thresholds_zero_coverage_and_nan_rates():
    curve = ev.outcome_curve([0.9, 0.2], [True, False], rejected=[True, True])
    np.testing.assert_array_equal(curve.thresholds, [0.9, 0.2])
    np.testing.assert_array_equal(curve.coverage, [0, 0])
    assert np.isnan(curve.accuracy).all()
    assert np.isnan(curve.risk).all()
