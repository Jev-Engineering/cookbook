"""Offline contracts for bound measurements and disclosed comparison rows."""

import datetime
import json
import math
from dataclasses import asdict
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, live, vision

MODEL = "jev-test-model"
DAY = "2026-10-31"
NUMERIC_MEASUREMENTS = ("input_tokens", "output_tokens", "latency_seconds", "cost_usd")


def recorded():
    return DecisionResult({"q": NoulAnswer(0.5, Provenance.recorded(MODEL, DAY))}, MODEL)


def disclosed(**changes):
    return {"mode": "recorded", "model": MODEL, "capture_date": DAY, "n": 1, **changes}


@pytest.mark.parametrize("mode", ["recorded", "live"])
@pytest.mark.parametrize("latency", [None, 0.0, 0.25])
def test_bound_carrier_matches_split_form_and_preserves_inputs(mode, latency):
    result = recorded()
    measured = live.LedgerLatency(latency, DAY, MODEL)
    before = result.to_dict(), asdict(measured)
    bound = vision.run_record(result, mode=mode, measured=measured, measured_cost_usd=0)
    split = vision.run_record(
        result, mode=mode, measured_latency_seconds=latency, capture_date=DAY, measured_cost_usd=0
    )
    assert bound == split
    assert bound["capture_date"] == DAY
    assert bound["model"] == MODEL
    assert bound["latency_seconds"] == latency
    assert bound["cost_usd"] == 0.0
    assert "n" not in bound
    assert (result.to_dict(), asdict(measured)) == before


@pytest.mark.parametrize("split", ["capture_date", "measured_latency_seconds"])
@pytest.mark.parametrize("explicit_none", [False, True])
def test_bound_carrier_rejects_explicit_split_keywords(split, explicit_none):
    value = None if explicit_none else (DAY if split == "capture_date" else 0.25)
    with pytest.raises(ValueError, match="measured conflicts"):
        vision.run_record(
            recorded(),
            mode="recorded",
            measured=live.LedgerLatency(None, DAY, MODEL),
            **{split: value},
        )


def test_none_carrier_and_explicit_split_none_preserve_legacy_six_keys():
    result = recorded()
    base = vision.run_record(result, mode="recorded")
    assert set(base) == {
        "mode",
        "model",
        "input_tokens",
        "output_tokens",
        "latency_seconds",
        "cost_usd",
    }
    assert vision.run_record(result, mode="recorded", measured=None) == base
    assert (
        vision.run_record(
            result, mode="recorded", measured=None, measured_latency_seconds=None, capture_date=None
        )
        == base
    )


@pytest.mark.parametrize("latency", [None, 0.25])
@pytest.mark.parametrize(
    "changes,match",
    [
        ({"model": "another-model"}, "measured.model contradicts"),
        ({"model": None}, "measured.model"),
        ({"model": ""}, "measured.model"),
        ({"model": " "}, "measured.model"),
        ({"model": "synthetic"}, "measured.model"),
        ({"model": 5}, "measured.model"),
        ({"date": "2026-11-01"}, "contradicts the result's recorded answers"),
        ({"date": None}, "capture_date"),
        ({"date": "2026-02-30"}, "capture_date"),
        ({"date": "20261031"}, "capture_date"),
    ],
)
def test_carrier_metadata_is_checked_even_without_timing(latency, changes, match):
    carrier = live.LedgerLatency(
        **{"latency_seconds": latency, "date": DAY, "model": MODEL, **changes}
    )
    with pytest.raises(ValueError, match=match):
        vision.run_record(recorded(), mode="recorded", measured=carrier)


@pytest.mark.parametrize("value", [True, -1, math.nan, math.inf, 10**1000, "0.5"])
def test_direct_carrier_cannot_bypass_latency_validation(value):
    with pytest.raises(ValueError, match="measured_latency_seconds"):
        vision.run_record(
            recorded(), mode="recorded", measured=live.LedgerLatency(value, DAY, MODEL)
        )


@pytest.mark.parametrize("value", [{}, SimpleNamespace(latency_seconds=0.5, date=DAY, model=MODEL)])
def test_carrier_requires_the_public_type(value):
    with pytest.raises(TypeError, match="measured must be a LedgerLatency"):
        vision.run_record(recorded(), mode="recorded", measured=value)


@pytest.mark.parametrize("mode", ["synthetic", "scripted"])
@pytest.mark.parametrize("latency", [None, 0.25])
def test_fixture_mode_refuses_every_non_none_carrier(mode, latency):
    with pytest.raises(ValueError, match="synthetic/scripted"):
        vision.run_record(
            SimpleNamespace(source="synthetic"),
            mode=mode,
            measured=live.LedgerLatency(latency, DAY, MODEL),
        )


@pytest.mark.parametrize("latency", [None, 0.25])
@pytest.mark.parametrize(
    "answers,error,match",
    [
        ({}, ValueError, "at least one recorded answer"),
        ({"q": SimpleNamespace()}, TypeError, "answer must provide provenance"),
        (
            {"q": NoulAnswer(0.5, Provenance.synthetic())},
            ValueError,
            "at least one recorded answer",
        ),
    ],
)
def test_carrier_does_not_repair_missing_result_provenance(latency, answers, error, match):
    result = SimpleNamespace(source="recorded", model=MODEL, answers=answers, usage=None)
    with pytest.raises(error, match=match):
        vision.run_record(result, mode="recorded", measured=live.LedgerLatency(latency, DAY, MODEL))


@pytest.mark.parametrize("latency", [None, 0.25])
def test_ledger_loaded_carrier_flows_into_accounting_without_split_metadata(tmp_path, latency):
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps(
            {
                "k": {
                    "status": "recorded",
                    "model": MODEL,
                    "date": DAY,
                    "latency_seconds": latency,
                }
            }
        ),
        encoding="utf-8",
    )
    result = recorded()
    measured = live.load_ledger_latency(path, "k", result=result)
    row = vision.run_record(result, mode="recorded", measured=measured, n=1)
    assert row == {
        "mode": "recorded",
        "model": MODEL,
        "input_tokens": None,
        "output_tokens": None,
        "latency_seconds": latency,
        "cost_usd": None,
        "capture_date": DAY,
        "n": 1,
    }


@pytest.mark.parametrize("latency", [None, 0.25])
def test_bound_carrier_uses_subclass_answer_dates_not_an_overridden_accessor(latency):
    class AdvertisedDateResult(DecisionResult):
        @property
        def recorded_date(self):
            return "2026-11-01"

    result = AdvertisedDateResult({"q": NoulAnswer(0.5, Provenance.recorded(MODEL, DAY))}, MODEL)
    with pytest.raises(ValueError, match="contradicts the result's recorded answers"):
        vision.run_record(
            result, mode="recorded", measured=live.LedgerLatency(latency, "2026-11-01", MODEL)
        )
    row = vision.run_record(
        result, mode="recorded", measured=live.LedgerLatency(latency, DAY, MODEL)
    )
    assert row["capture_date"] == DAY
    assert row["latency_seconds"] == latency


@pytest.mark.parametrize(
    "field", ["characters", "utf8_bytes", "input_tokens", "output_tokens", "n"]
)
@pytest.mark.parametrize("value", [True, -1, 1.5, "1", math.nan, math.inf, -math.inf])
def test_comparison_rejects_bad_counts_with_other_disclosures_present(field, value):
    with pytest.raises(ValueError, match=field):
        vision.comparison_table([disclosed(**{field: value})])


def test_comparison_n_must_be_positive():
    with pytest.raises(ValueError, match="n must be a positive integer"):
        vision.comparison_table([disclosed(n=0)])


@pytest.mark.parametrize("field", ["latency_seconds", "cost_usd"])
@pytest.mark.parametrize("value", [True, -0.1, math.nan, math.inf, -math.inf, "1", 10**1000])
def test_comparison_rejects_bad_measurements_with_disclosures_present(field, value):
    with pytest.raises(ValueError, match=field):
        vision.comparison_table([disclosed(**{field: value})])


@pytest.mark.parametrize("field", ["latency_seconds", "cost_usd"])
def test_comparison_rejects_negative_reals_that_underflow_to_signed_zero(field):
    value = Fraction(-1, 10**1000)
    assert float(value) == 0.0
    assert value < 0
    with pytest.raises(ValueError, match=f"^{field} must be non-negative$"):
        vision.comparison_table([disclosed(**{field: value})])


@pytest.mark.parametrize("field", NUMERIC_MEASUREMENTS)
@pytest.mark.parametrize("mode", ["recorded", "live"])
@pytest.mark.parametrize("value", [0, 1])
def test_every_numeric_measurement_requires_model_and_n(field, mode, value):
    row = disclosed(mode=mode, **{field: value})
    for missing in ("model", "n"):
        incomplete = {key: part for key, part in row.items() if key != missing}
        with pytest.raises(ValueError, match=missing):
            vision.comparison_table([incomplete])
    with pytest.raises(ValueError, match="model"):
        vision.comparison_table([{**row, "model": None}])
    without_date = {key: part for key, part in row.items() if key != "capture_date"}
    if mode == "recorded":
        for incomplete in (without_date, {**row, "capture_date": None}):
            with pytest.raises(ValueError, match="capture_date"):
                vision.comparison_table([incomplete])
    else:
        vision.comparison_table([without_date])
        vision.comparison_table([{**row, "capture_date": None}])


@pytest.mark.parametrize("model", ["", " \t", "synthetic", 5, True])
def test_model_only_rows_still_validate_the_model(model):
    with pytest.raises(ValueError, match="model"):
        vision.comparison_table([{"mode": "recorded", "model": model}])


@pytest.mark.parametrize("mode", ["recorded", "live"])
@pytest.mark.parametrize(
    "date",
    ["2026-02-30", "20261031", "2026-W44-6", " 2026-10-31", datetime.date(2026, 10, 31)],
)
def test_dates_are_validated_even_without_measurements(mode, date):
    with pytest.raises(ValueError, match="capture_date"):
        vision.comparison_table([{"mode": mode, "model": MODEL, "capture_date": date}])


def test_labels_are_text_but_empty_labels_are_allowed():
    with pytest.raises(ValueError, match="label"):
        vision.comparison_table([{"mode": "live", "label": 5}])
    vision.comparison_table([{"mode": "live", "label": ""}])


@pytest.mark.parametrize("mode", ["recorded", "live"])
def test_absent_model_only_computed_only_and_null_measurements_need_no_disclosures(mode):
    for fields in ({}, {"model": MODEL}, {"characters": 0}, dict.fromkeys(NUMERIC_MEASUREMENTS)):
        row = {"mode": mode, **fields}
        before = dict(row)
        vision.comparison_table(iter([row]))
        assert row == before


@pytest.mark.parametrize(
    "field", ["characters", "utf8_bytes", "input_tokens", "output_tokens", "n"]
)
@pytest.mark.parametrize("value", [2**53 + 1, 10**1000, np.int64(7)])
def test_integer_counts_render_exactly_and_are_not_coerced(field, value):
    row = disclosed(**{field: value})
    before = dict(row)
    assert str(value) in vision.comparison_table([row]).splitlines()[-1].split()
    assert row == before
    assert row[field] is value


@pytest.mark.parametrize("value", [Fraction(1, 3), -0.0, np.float64(0.125)])
def test_valid_real_measurements_retain_their_original_rendering(value):
    row = disclosed(latency_seconds=value)
    assert str(value) in vision.comparison_table([row]).splitlines()[-1].split()
    assert row["latency_seconds"] is value
