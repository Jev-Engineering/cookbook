"""Pure accounting validation contracts; no live client or image/plot imports."""

import datetime
import math
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest

from jev_cookbook._canonical import (
    check_question_depth,
    finite_number,
    is_iso_date,
    recorded_answer_dates,
)
from jev_cookbook.answers import DecisionResult, NoulAnswer, Provenance


@pytest.mark.parametrize("value", [0, 1, 0.25, Fraction(1, 2)])
def test_finite_number_accepts_real_numbers_as_floats(value):
    result = finite_number(value, "latency")
    assert type(result) is float
    assert result == value


@pytest.mark.parametrize(
    "value",
    [True, False, "1", None, 1j, Decimal("1"), float("nan"), float("inf"), -float("inf"), 10**1000],
)
def test_finite_number_rejects_nonreal_nonfinite_and_overflow(value):
    with pytest.raises(ValueError, match="^latency must be a finite number$"):
        finite_number(value, "latency")


@pytest.mark.parametrize("unit", [False, True])
def test_finite_number_preserves_negative_zero_unless_positive(unit):
    assert math.copysign(1, finite_number(-0.0, "x", unit=unit)) == -1
    for zero in (0, 0.0, -0.0):
        with pytest.raises(ValueError):
            finite_number(zero, "x", unit=unit, positive=True)


def test_finite_number_bounds_have_the_existing_field_diagnostics():
    assert finite_number(0, "x", unit=True) == 0.0
    assert finite_number(1, "x", unit=True, positive=True) == 1.0
    assert finite_number(2, "x", positive=True) == 2.0
    for value, options, message in (
        (-1, {}, "x must be non-negative"),
        (2, {"unit": True}, "x must be in [0, 1]"),
        (-1, {"unit": True}, "x must be in [0, 1]"),
        (0, {"positive": True}, "x must be positive"),
        (2, {"positive": True, "unit": True}, "x must be in (0, 1]"),
    ):
        with pytest.raises(ValueError) as error:
            finite_number(value, "x", **options)
        assert str(error.value) == message


@pytest.mark.parametrize("value", ["0001-01-01", "2000-02-29", "9999-12-31"])
def test_iso_date_accepts_real_calendar_boundaries(value):
    assert is_iso_date(value)
    assert Provenance.recorded("m", value).date == value


@pytest.mark.parametrize(
    "value",
    [
        "1900-02-29",
        "2026-02-30",
        "20261031",
        "2026-W44-6",
        "2026-1-05",
        " 2026-10-31",
        "2026-10-31\n",
        "٢٠٢٦-١٠-٣١",
        "",
        None,
        20261031,
        datetime.date(2026, 10, 31),
    ],
)
def test_iso_date_rejects_noncanonical_forms_and_non_dates(value):
    assert not is_iso_date(value)
    with pytest.raises(ValueError, match="date"):
        Provenance.recorded("m", value)


def test_provenance_keeps_its_stricter_exact_string_boundary():
    class Text(str):
        pass

    value = Text("2026-10-31")
    assert is_iso_date(value)
    with pytest.raises(ValueError, match="^recorded provenance requires a date as YYYY-MM-DD$"):
        Provenance.recorded("m", value)
    with pytest.raises(ValueError, match="^date must be YYYY-MM-DD, got '2026-02-30'$"):
        Provenance.recorded("m", "2026-02-30")


@pytest.mark.parametrize(
    "provenance, model, expected_date",
    [
        (Provenance.synthetic(), "synthetic", None),
        (Provenance.recorded("m", "2026-10-31"), "m", "2026-10-31"),
    ],
)
def test_recorded_date_accessor_keeps_result_serialization(provenance, model, expected_date):
    result = DecisionResult(
        {"a": NoulAnswer(0.25, provenance), "b": NoulAnswer(0.75, provenance)}, model
    )
    expected = {
        "model": model,
        "usage": {"input_tokens": None, "output_tokens": None},
        "answers": {
            "a": {"type": "noul", "noul": 0.25, "provenance": provenance.to_dict()},
            "b": {"type": "noul", "noul": 0.75, "provenance": provenance.to_dict()},
        },
    }
    assert result.recorded_date == expected_date
    assert result.to_dict() == expected
    assert DecisionResult.from_dict(expected) == result
    assert DecisionResult.from_dict(expected).recorded_date == expected_date


def test_recorded_date_constructor_still_rejects_multiple_capture_dates():
    answers = {
        "a": NoulAnswer(0.5, Provenance.recorded("m", "2026-10-31")),
        "b": NoulAnswer(0.5, Provenance.recorded("m", "2026-11-01")),
    }
    with pytest.raises(ValueError, match="^recorded answers of one result must share one date$"):
        DecisionResult(answers, "m")


class _AdvertisedDateResult(DecisionResult):
    @property
    def recorded_date(self):
        return "2026-11-01"


class _AdvertisedSyntheticResult(DecisionResult):
    @property
    def source(self):
        return "synthetic"


@pytest.mark.parametrize("result_type", [_AdvertisedDateResult, _AdvertisedSyntheticResult])
def test_result_subclasses_cannot_override_the_constructor_date_invariant(result_type):
    answers = {
        "a": NoulAnswer(0.5, Provenance.recorded("m", "2026-10-31")),
        "b": NoulAnswer(0.5, Provenance.recorded("m", "2026-11-01")),
    }
    with pytest.raises(ValueError, match="^recorded answers of one result must share one date$"):
        result_type(answers, "m")


@pytest.mark.parametrize("latency", [None, 0.25])
def test_result_subclasses_cannot_advertise_a_date_instead_of_answer_provenance(tmp_path, latency):
    import json

    from jev_cookbook import live, vision

    result = _AdvertisedDateResult(
        {"q": NoulAnswer(0.5, Provenance.recorded("m", "2026-10-31"))}, "m"
    )
    ledger = tmp_path / "ledger.json"
    for day, matches in [("2026-11-01", False), ("2026-10-31", True)]:
        ledger.write_text(
            json.dumps(
                {
                    "k": {
                        "status": "recorded",
                        "model": "m",
                        "date": day,
                        "latency_seconds": latency,
                    }
                }
            ),
            encoding="utf-8",
        )
        if matches:
            assert live.load_ledger_latency(ledger, "k", result=result) == live.LedgerLatency(
                latency, day, "m"
            )
            row = vision.run_record(
                result, mode="recorded", measured_latency_seconds=latency, capture_date=day
            )
            assert row["capture_date"] == day
            assert row["latency_seconds"] == latency
        else:
            with pytest.raises(ValueError, match="ledger line.*dated"):
                live.load_ledger_latency(ledger, "k", result=result)
            with pytest.raises(ValueError, match="contradicts the result's recorded answers"):
                vision.run_record(
                    result, mode="recorded", measured_latency_seconds=latency, capture_date=day
                )


def _answer(source="recorded", date="2026-10-31"):
    return SimpleNamespace(provenance=SimpleNamespace(source=source, date=date))


def test_duck_dates_keep_all_recorded_dates_and_ignore_other_sources():
    result = SimpleNamespace(
        answers={
            "a": _answer(),
            "b": _answer(date="2026-11-01"),
            "c": _answer(source="synthetic", date=None),
        }
    )
    assert recorded_answer_dates(result) == {"2026-10-31", "2026-11-01"}


@pytest.mark.parametrize(
    "result, exception, message",
    [
        (SimpleNamespace(), ValueError, "at least one recorded answer"),
        (SimpleNamespace(answers={}), ValueError, "at least one recorded answer"),
        (SimpleNamespace(answers={"q": _answer(source="synthetic")}), ValueError, "at least one"),
        (SimpleNamespace(answers=[]), TypeError, "result.answers must be a mapping"),
        (SimpleNamespace(answers={"q": SimpleNamespace()}), TypeError, "each answer must provide"),
        (
            SimpleNamespace(answers={"q": SimpleNamespace(provenance=SimpleNamespace())}),
            TypeError,
            "each answer must provide",
        ),
        (
            SimpleNamespace(answers={"q": _answer(date="20261031")}),
            ValueError,
            "recorded answer provenance requires a YYYY-MM-DD date",
        ),
        (
            SimpleNamespace(answers={"q": _answer(date=None)}),
            ValueError,
            "recorded answer provenance requires a YYYY-MM-DD date",
        ),
    ],
)
def test_duck_dates_keep_missing_and_malformed_provenance_errors(result, exception, message):
    with pytest.raises(exception, match=message):
        recorded_answer_dates(result)


def test_duck_dates_check_every_answer_and_do_not_trust_an_advertised_accessor():
    result = SimpleNamespace(
        recorded_date="2026-10-31", answers={"valid": _answer(), "missing": SimpleNamespace()}
    )
    with pytest.raises(TypeError, match="each answer must provide provenance"):
        recorded_answer_dates(result)


def _nested(levels):
    value = "leaf"
    for _ in range(levels):
        value = [value]
    return value


@pytest.mark.parametrize("part", ["instructions", "mapping", "sequence"])
def test_question_depth_counts_each_part_without_wrapper_overhead(part):
    def content(levels):
        deep = _nested(levels)
        if part == "instructions":
            return {"type": "noul", "instructions": deep}
        if part == "mapping":
            return {"type": "choice", "criteria": {"a": deep, "b": _nested(64)}}
        return {"type": "score", "criteria": [deep, _nested(64)]}

    check_question_depth(content(64), "q")
    path = {
        "instructions": "question 'q' instructions",
        "mapping": "question 'q' criteria['a']",
        "sequence": "question 'q' criteria[0]",
    }[part]
    with pytest.raises(ValueError) as error:
        check_question_depth(content(65), "q")
    assert str(error.value) == f"{path}: nested deeper than 64 levels (see docs/fixtures.md)"


def test_question_depth_preserves_part_order_and_accepts_scalar_content():
    check_question_depth({"instructions": "scalar", "criteria": None}, "q")
    with pytest.raises(ValueError, match="question 'q' instructions"):
        check_question_depth({"instructions": _nested(65), "criteria": [_nested(65)]}, "q")
    with pytest.raises(ValueError) as error:
        check_question_depth({"criteria": {"z": _nested(65), "a": _nested(65)}}, "q")
    assert "criteria['z']" in str(error.value)


_LIGHTWEIGHT_LEDGER_PROBE = """
import sys
from types import SimpleNamespace
from jev_cookbook.answers import DecisionResult, NoulAnswer, Provenance
from jev_cookbook.live import load_ledger_latencies, load_ledger_latency

path = sys.argv[1]
typed = DecisionResult({"q": NoulAnswer(0.5, Provenance.recorded("m", "2026-11-18"))}, "m")
duck = SimpleNamespace(model="m", answers={"q": SimpleNamespace(
    provenance=SimpleNamespace(source="recorded", date="2026-11-18"))})
for result in (typed, duck):
    measured = load_ledger_latencies(path, ["k"], results={"k": result})["k"]
    assert (measured.latency_seconds, measured.date, measured.model) == (0.25, "2026-11-18", "m")
try:
    load_ledger_latency(path, "invalid")
except ValueError as error:
    assert "needs a YYYY-MM-DD date" in str(error)
else:
    raise AssertionError("invalid date was accepted")
heavy = [name for name in ("PIL", "matplotlib", "numpy", "typesafe_sdk") if name in sys.modules]
assert not heavy, f"ledger-only reads imported {heavy}"
print("ledger-only imports stayed lightweight")
"""


def test_ledger_validation_stays_lightweight_in_a_fresh_process(tmp_path):
    import json
    import subprocess
    import sys

    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "k": {
                    "status": "recorded",
                    "date": "2026-11-18",
                    "model": "m",
                    "latency_seconds": 0.25,
                },
                "invalid": {"status": "recorded", "date": "20261118", "model": "m"},
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-c", _LIGHTWEIGHT_LEDGER_PROBE, str(ledger)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "ledger-only imports stayed lightweight"
