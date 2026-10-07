"""Tests of jev_cookbook.style against the real backends and answer classes, and against
duck-typed stand-ins for the evaluation toolkit's result objects."""

from dataclasses import dataclass

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pytest

from jev_cookbook import (
    ChoiceAnswer,
    DecisionResult,
    Noul,
    NoulAnswer,
    Provenance,
    ReplayBackend,
    ScoreAnswer,
    ScriptedBackend,
    replay_key,
    style,
)


@pytest.fixture(autouse=True)
def headless_backend():
    previous = matplotlib.get_backend()
    plt.switch_backend("agg")
    yield
    plt.switch_backend(previous)


SYNTHETIC_TEXT = (
    "Recipe 07: Triage tickets\n"
    "Mode: offline replay of synthetic fixtures\n"
    "Metrics in this run are checks that the pipeline works. They are not Jev results."
)
SCRIPTED_TEXT = (
    "Recipe 07: Triage tickets\n"
    "Mode: offline, scripted backend\n"
    "Metrics in this run are checks that the pipeline works. They are not Jev results."
)
MODEL = "system-one-test-model"


def _recorded_text(when: str, sample: str = "") -> str:
    return (
        "Recipe 07: Triage tickets\n"
        "Mode: offline replay of recorded fixtures\n"
        f"The answers were captured from real Jev calls to model {MODEL} {when}. "
        f"Any numbers below describe only that recorded sample{sample}."
    )


LIVE_TEXT = (
    "Recipe 07: Triage tickets\n"
    "Mode: live\n"
    f"Calls are being made now to model {MODEL}. "
    "Any numbers below describe only the examples in this run."
)

QUESTIONS = {"billing": Noul(instructions="Is this ticket about billing?")}


def _replay(*provenances: Provenance, model: str = "synthetic") -> ReplayBackend:
    """A ReplayBackend with one fixture per provenance (one state each)."""
    responses = {}
    for i, prov in enumerate(provenances):
        state = {"document": f"ticket {i}"}
        result = DecisionResult({"billing": NoulAnswer(0.9, prov)}, model)
        responses[replay_key(state, QUESTIONS)] = result.to_dict()
    return ReplayBackend(responses)


def _recorded(*dates: str) -> ReplayBackend:
    return _replay(*(Provenance.recorded(MODEL, d) for d in dates), model=MODEL)


class StandInLive:
    mode = "live"
    model = MODEL


# --- run header from a backend -------------------------------------------------------------


def test_header_from_a_synthetic_replay_backend():
    backend = _replay(Provenance.synthetic())
    assert backend.mode == "synthetic"
    assert style.run_header_text(7, "Triage tickets", backend=backend) == SYNTHETIC_TEXT


def test_header_from_a_scripted_backend():
    backend = ScriptedBackend(lambda state, questions, rng: {"billing": 0.5})
    assert style.run_header_text(7, "Triage tickets", backend=backend) == SCRIPTED_TEXT


def test_header_from_a_recorded_backend_with_one_date():
    backend = _recorded("2026-01-02", "2026-01-02")
    assert backend.recorded_dates == ("2026-01-02",)
    text = style.run_header_text(7, "Triage tickets", backend=backend)
    assert text == _recorded_text("on 2026-01-02")
    assert text == style.run_header_text(
        7, "Triage tickets", "recorded", model=MODEL, recorded_on="2026-01-02"
    )


def test_header_from_a_recorded_backend_with_several_dates_states_the_range():
    backend = _recorded("2026-01-09", "2026-01-02", "2026-01-05")
    assert backend.recorded_dates == ("2026-01-02", "2026-01-05", "2026-01-09")
    text = style.run_header_text(7, "Triage tickets", backend=backend)
    assert text == _recorded_text("between 2026-01-02 and 2026-01-09")


def test_header_from_a_live_stand_in():
    assert style.run_header_text(7, "Triage tickets", backend=StandInLive()) == LIVE_TEXT


def test_header_from_a_backend_states_the_sample_size_with_correct_plural():
    backend = _recorded("2026-01-02")
    assert style.run_header_text(7, "Triage tickets", backend=backend, n_examples=12) == (
        _recorded_text("on 2026-01-02", " of 12 examples")
    )
    one = style.run_header_text(7, "Triage tickets", backend=backend, n_examples=1)
    assert one.endswith("that recorded sample of 1 example.")
    live = style.run_header_text(7, "T", backend=StandInLive(), n_examples=1)
    assert live.endswith("describe only the 1 example in this run.")
    live = style.run_header_text(7, "T", backend=StandInLive(), n_examples=2)
    assert live.endswith("describe only the 2 examples in this run.")


def test_run_header_prints_the_backend_text_and_returns_none(capsys):
    backend = _recorded("2026-01-02")
    assert style.run_header(7, "Triage tickets", backend=backend) is None
    text = style.run_header_text(7, "Triage tickets", backend=backend)
    assert capsys.readouterr().out == text + "\n"


def test_header_from_a_synthetic_backend_states_the_fixture_sample_size():
    text = style.run_header_text(7, "T", backend=_replay(Provenance.synthetic()), n_examples=3)
    assert text.splitlines()[1] == (
        "Mode: offline replay of synthetic fixtures, pipeline check on a fixture sample "
        "of 3 examples"
    )
    assert text.endswith(style.SYNTHETIC_NOTICE)


def test_header_backend_and_explicit_arguments_cannot_be_mixed():
    backend = _replay(Provenance.synthetic())
    for kwargs in ({"mode": "synthetic"}, {"model": "m"}, {"recorded_on": "2026-01-02"}):
        with pytest.raises(ValueError):
            style.run_header_text(7, "T", backend=backend, **kwargs)


def test_header_needs_a_mode_or_a_backend_and_rejects_non_backends():
    with pytest.raises(ValueError):
        style.run_header_text(7, "T")
    with pytest.raises(TypeError):
        style.run_header_text(7, "T", backend=object())


def test_header_rejects_a_recorded_stand_in_without_dates():
    @dataclass
    class NoDates:
        mode: str = "recorded"
        model: str = MODEL
        recorded_dates: tuple = ()

    with pytest.raises(ValueError):
        style.run_header_text(7, "T", backend=NoDates())


def test_run_info_range_is_validated():
    with pytest.raises(ValueError):
        style.RunInfo("recorded", "m", "2026-01-09", recorded_until="2026-01-02")
    with pytest.raises(ValueError):
        style.RunInfo("live", "m", recorded_until="2026-01-02")


def test_explicit_form_still_pluralises_correctly():
    text = style.run_header_text(
        7, "T", "recorded", model="m", recorded_on="2026-01-02", n_examples=1
    )
    assert text.endswith("that recorded sample of 1 example.")
    assert style.run_header_text(7, "T", "live", model="m", n_examples=1).endswith(
        "only the 1 example in this run."
    )


# --- real answer classes -------------------------------------------------------------------

SYN = Provenance.synthetic()
REC = Provenance.recorded(MODEL, "2026-01-02")


def _choice(prov=SYN):
    return ChoiceAnswer.from_probabilities({"calm": 0.7, "angry": 0.2, "excited": 0.1}, prov)


def _score_text():
    return ScoreAnswer.from_probabilities(
        [0.0, 0.57, 0.43], ["Cosmetic", "Workaround exists", "Blocking"], SYN
    )


def _score_objects():
    legend = [{"label": "low", "n": 1}, ["mid", "tier 2"], "high"]
    return ScoreAnswer.from_probabilities([0.1, 0.3, 0.6], legend, SYN)


def test_format_real_choice_answer_shows_plain_values():
    answer = _choice()
    assert "mappingproxy" in repr(answer.probabilities)  # the input the display must tame
    text = style.format_answer(answer)
    lines = text.splitlines()
    assert lines[0] == f"Choice: calm (confidence {answer.confidence:.2f})"
    assert lines[1].split()[:2] == ["calm", "0.70"]
    assert "mappingproxy" not in text
    assert lines[-1] == "Provenance: synthetic"


def test_probabilities_and_confidence_are_shown_to_two_decimals():
    answer = ChoiceAnswer.from_probabilities({"a": 0.123456, "b": 0.876544}, SYN)
    text = style.format_answer(answer)
    assert "a  0.12" in text and "b  0.88" in text
    assert f"(confidence {answer.confidence:.2f})" in text
    assert "0.123" not in text and "0.8765" not in text


def test_format_real_recorded_provenance_names_model_and_date():
    assert style.format_answer(_choice(REC)).splitlines()[-1] == (
        f"Provenance: recorded ({MODEL}, 2026-01-02)"
    )


def test_format_real_score_with_text_legend():
    answer = _score_text()
    text = style.format_answer(answer)
    assert text.splitlines()[0] == f"Score: {answer.score:.2f} (confidence {answer.confidence:.2f})"
    assert "1 Workaround exists  0.57" in text
    assert "mappingproxy" not in text


def test_format_real_score_with_object_and_array_legends_is_readable():
    text = style.format_answer(_score_objects())
    assert '0 {"label": "low", "n": 1}  0.10' in text
    assert '1 ["mid", "tier 2"]  0.30' in text
    assert "2 high  0.60" in text
    assert "mappingproxy" not in text and "{'" not in text


def test_score_levels_keyed_by_int_sort_numerically():
    n = 10
    probs = [0.0] * n
    probs[2], probs[9] = 0.4, 0.6
    answer = ScoreAnswer.from_probabilities(probs, [f"L{i}" for i in range(n)], SYN)
    assert all(isinstance(k, int) for k in answer.probabilities)
    rows = [ln.split()[0] for ln in style.format_answer(answer).splitlines()[1:-1]]
    assert rows == [str(i) for i in range(n)]


def test_format_real_noul_answer():
    text = style.format_answer(NoulAnswer(0.93, SYN))
    assert text.splitlines()[0] == "Noul: 0.93 probability of yes (0 is no, 1 is yes)"
    assert "confidence" not in text


def test_plot_real_choice_answer_highlights_the_choice():
    fig = style.plot_answer_probabilities(_choice())
    ax = fig.axes[0]
    labels = [t.get_text() for t in ax.get_yticklabels()]
    assert sorted(labels) == ["angry", "calm", "excited"]
    colours = [matplotlib.colors.to_hex(p.get_facecolor()).upper() for p in ax.patches]
    assert colours[labels.index("calm")] == style.PINK


def test_plot_real_score_answers_use_level_order_and_readable_labels():
    fig = style.plot_answer_probabilities(_score_text())
    ax = fig.axes[0]
    assert [t.get_text() for t in ax.get_yticklabels()] == [
        "0 Cosmetic",
        "1 Workaround exists",
        "2 Blocking",
    ]
    score_line = [ln for ln in ax.lines if ln.get_label() == "score"][0]
    assert score_line.get_ydata()[0] == pytest.approx(1.0 + 0.43)

    fig = style.plot_answer_probabilities(_score_objects())
    labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
    assert labels[2] == "2 high"
    assert labels[0].startswith('0 {"label"')
    assert all("mappingproxy" not in t and "{'" not in t for t in labels)


def test_plot_real_noul_answer():
    fig = style.plot_answer_probabilities(NoulAnswer(0.75, SYN))
    assert [t.get_text() for t in fig.axes[0].get_yticklabels()] == ["no", "yes"]


def test_plot_a_read_only_mapping_of_probabilities():
    fig = style.plot_answer_probabilities(_choice().probabilities, highlight="calm")
    assert len(fig.axes[0].patches) == 3


# --- duck-typed evaluation results ---------------------------------------------------------


@dataclass
class FakeConfusion:
    labels: list
    matrix: np.ndarray


@dataclass
class FakePoint:
    threshold: float
    precision: float
    recall: float
    f1: float


@dataclass
class FakeCurve:
    coverage: np.ndarray
    risk: np.ndarray


def test_confusion_matrix_accepts_an_object_with_labels_and_matrix():
    result = FakeConfusion(["a", "b"], np.array([[3, 1], [0, 4]]))
    fig = style.plot_confusion_matrix(result)
    ax = fig.axes[0]
    assert [t.get_text() for t in ax.get_xticklabels()] == ["a", "b"]
    assert sorted(t.get_text() for t in ax.texts) == ["0", "1", "3", "4"]
    # Same drawing as the explicit form.
    explicit = style.plot_confusion_matrix([[3, 1], [0, 4]], ["a", "b"])
    assert [t.get_text() for t in explicit.axes[0].texts] == [t.get_text() for t in ax.texts]


def test_confusion_matrix_object_with_non_string_labels_and_normalize():
    fig = style.plot_confusion_matrix(
        FakeConfusion([0, 1], np.array([[1, 1], [0, 2]])), normalize=True
    )
    assert sorted(t.get_text() for t in fig.axes[0].texts) == ["0.00", "0.50", "0.50", "1.00"]


def test_confusion_matrix_needs_labels_or_an_object_that_has_them():
    with pytest.raises(ValueError):
        style.plot_confusion_matrix([[1, 0], [0, 1]])


def test_threshold_sweep_accepts_a_list_of_points():
    points = [
        FakePoint(0.2, 0.5, 0.9, 0.64),
        FakePoint(0.5, 0.7, 0.7, 0.7),
        FakePoint(0.8, float("nan"), 0.1, 0.18),
    ]
    fig = style.plot_threshold_sweep(points, chosen=0.5)
    ax = fig.axes[0]
    assert [ln.get_label() for ln in ax.lines if not ln.get_label().startswith("_")] == [
        "precision",
        "recall",
        "f1",
    ]
    line = ax.lines[0]
    assert list(line.get_xdata()) == [0.2, 0.5, 0.8]
    assert np.isnan(line.get_ydata()[2])


def test_threshold_sweep_points_use_only_the_metrics_they_carry():
    @dataclass
    class Partial:
        threshold: float
        recall: float

    fig = style.plot_threshold_sweep([Partial(0.1, 0.9), Partial(0.9, 0.2)])
    assert [ln.get_label() for ln in fig.axes[0].lines] == ["recall"]
    with pytest.raises(ValueError):
        style.plot_threshold_sweep([FakePoint(0.1, 1, 1, 1)], {"x": [1.0]})

    @dataclass
    class NoMetric:
        threshold: float

    with pytest.raises(ValueError):
        style.plot_threshold_sweep([NoMetric(0.1)])


def test_risk_coverage_accepts_an_object_with_coverage_and_risk():
    curve = FakeCurve(np.array([0.2, 0.6, 1.0]), np.array([0.0, 0.1, 0.2]))
    fig = style.plot_risk_coverage(curve, label="by confidence")
    line = fig.axes[0].lines[0]
    assert list(line.get_xdata()) == [0.2, 0.6, 1.0]
    assert list(line.get_ydata()) == [0.0, 0.1, 0.2]
    with pytest.raises(ValueError):
        style.plot_risk_coverage([0.1, 0.2])


def test_equal_first_and_last_dates_print_on_date_not_a_range():
    info = style.RunInfo("recorded", MODEL, "2026-01-02", recorded_until="2026-01-02")
    assert style.run_header_text(7, "Triage tickets", info) == _recorded_text("on 2026-01-02")


@pytest.mark.parametrize(
    "recorded_on, recorded_until",
    [
        ("2026-1-2", None),
        ("20260102", None),
        ("DATE", None),
        ("2026-02-30", None),
        (" 2026-01-02", None),
        ("2026-01-02", "yesterday"),
        ("2026-01-02", "2026-1-9"),
        ("2026-01-09", "2026-01-02"),
    ],
)
def test_run_info_rejects_malformed_or_unordered_dates(recorded_on, recorded_until):
    with pytest.raises(ValueError):
        style.RunInfo("recorded", MODEL, recorded_on, recorded_until=recorded_until)


@pytest.mark.parametrize("recorded_on", ["2026-1-2", "DATE", "2026-02-30"])
def test_explicit_recorded_header_rejects_malformed_dates(recorded_on):
    with pytest.raises(ValueError):
        style.run_header_text(7, "T", "recorded", model=MODEL, recorded_on=recorded_on)
