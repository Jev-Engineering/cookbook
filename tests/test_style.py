"""Tests for jev_cookbook.style: header text per mode, answer display, charts, colours."""

import io
import itertools
import subprocess
import sys
from dataclasses import dataclass, field

import matplotlib
import matplotlib.figure
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import pytest

from jev_cookbook import style


@pytest.fixture(autouse=True)
def headless_backend():
    """Run every test on the non-interactive Agg backend, as CI does."""
    previous = matplotlib.get_backend()
    plt.switch_backend("agg")
    yield
    plt.switch_backend(previous)


# --- stand-ins for the typed answers (the real classes come from issue #63) ----------------


@dataclass
class FakeChoice:
    choice: str
    probabilities: dict
    confidence: float
    provenance: str = "synthetic"


@dataclass
class FakeScore:
    score: float
    probabilities: dict
    confidence: float
    legend: dict = field(default_factory=dict)
    provenance: str = "synthetic"


@dataclass
class FakeNoul:
    noul: float
    provenance: str = "synthetic"


CHOICE = FakeChoice("calm", {"calm": 0.7, "angry": 0.2, "excited": 0.1}, 0.9)
SCORE = FakeScore(
    1.43,
    {"0": 0.0, "1": 0.57, "2": 0.43},
    0.35,
    {"0": "Cosmetic", "1": "Workaround exists", "2": "Blocking"},
)
NOUL = FakeNoul(0.93)

# --- run header: the exact text of each mode -----------------------------------------------

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
RECORDED_TEXT = (
    "Recipe 07: Triage tickets\n"
    "Mode: offline replay of recorded fixtures\n"
    "The answers were captured from a real Jev call to model system-one-test-model "
    "on 2026-01-02. Any numbers below describe only that recorded sample."
)
LIVE_TEXT = (
    "Recipe 07: Triage tickets\n"
    "Mode: live\n"
    "Calls are being made now to model system-one-test-model. "
    "Any numbers below describe only the examples in this run."
)
RECORDED_N_TEXT = RECORDED_TEXT.replace(
    "only that recorded sample.", "only that recorded sample of 12 examples."
)
LIVE_N_TEXT = LIVE_TEXT.replace("only the examples", "only the 12 examples")


def test_sample_size_is_appended_to_recorded_and_live_only():
    recorded = style.run_header_text(
        7,
        "Triage tickets",
        "recorded",
        model="system-one-test-model",
        recorded_on="2026-01-02",
        n_examples=12,
    )
    live = style.run_header_text(
        7, "Triage tickets", "live", model="system-one-test-model", n_examples=12
    )
    assert recorded == RECORDED_N_TEXT
    assert live == LIVE_N_TEXT
    via_info = style.RunInfo("live", "system-one-test-model", n_examples=12)
    assert style.run_header_text(7, "Triage tickets", via_info) == LIVE_N_TEXT


def test_synthetic_and_scripted_text_is_unchanged_and_refuses_a_sample_size():
    for mode in ("synthetic", "scripted"):
        with pytest.raises(ValueError):
            style.run_header_text(1, "T", mode, n_examples=5)


@pytest.mark.parametrize("bad", [0, -3, 2.5, True, "7"])
def test_sample_size_must_be_a_positive_integer(bad):
    with pytest.raises(ValueError):
        style.RunInfo("live", "m", n_examples=bad)


def test_live_header_carries_the_numbers_caveat():
    text = style.run_header_text(1, "T", "live", model="m")
    assert "Any numbers below describe only the examples in this run." in text


# --- Score level order (levels sort by integer value, as in the evaluation toolkit) ----------

OUT_OF_ORDER = FakeScore(
    1.43,
    {"2": 0.43, "0": 0.0, "1": 0.57},
    0.35,
    {"2": "c", "0": "a", "1": "b"},
)


def test_score_text_lists_levels_in_level_order_whatever_the_key_order():
    lines = style.format_answer(OUT_OF_ORDER).splitlines()
    assert [ln.split()[0] for ln in lines[1:4]] == ["0", "1", "2"]


def test_score_chart_orders_bars_and_places_the_score_line_by_level():
    fig = style.plot_answer_probabilities(OUT_OF_ORDER)
    ax = fig.axes[0]
    assert [t.get_text() for t in ax.get_yticklabels()] == ["0 a", "1 b", "2 c"]
    line = [ln for ln in ax.lines if ln.get_label() == "score"][0]
    assert line.get_ydata()[0] == pytest.approx(1.43)


def test_score_levels_sort_numerically_past_ten_and_accept_int_keys():
    probs = {str(i): 0.0 for i in range(12)}
    probs["11"] = 1.0
    shuffled = dict(sorted(probs.items()))  # "0", "1", "10", "11", "2", ...
    ans = FakeScore(11.0, shuffled, 0.9, {k: f"L{k}" for k in shuffled})
    fig = style.plot_answer_probabilities(ans)
    ax = fig.axes[0]
    assert [t.get_text() for t in ax.get_yticklabels()] == [f"{i} L{i}" for i in range(12)]
    assert [ln for ln in ax.lines if ln.get_label() == "score"][0].get_ydata()[0] == 11.0
    as_ints = FakeScore(1.0, {2: 0.1, 0: 0.2, 1: 0.7}, 0.7, {})
    assert [ln.split()[0] for ln in style.format_answer(as_ints).splitlines()[1:4]] == [
        "0",
        "1",
        "2",
    ]


# --- confusion-matrix text contrast ----------------------------------------------------------


def _contrast_ratio(bg_hex_or_rgb, fg_hex):
    lb = style._luminance(matplotlib.colors.to_rgb(bg_hex_or_rgb))
    lf = style._luminance(matplotlib.colors.to_rgb(fg_hex))
    hi, lo = max(lb, lf), min(lb, lf)
    return (hi + 0.05) / (lo + 0.05)


def test_cell_text_has_at_least_4_to_1_contrast_across_the_whole_ramp():
    for v in np.linspace(0, 1, 201):
        bg = style.SEQUENTIAL_CMAP(v)[:3]
        colour = style._text_colour(bg)
        assert _contrast_ratio(bg, colour) >= 4.0, f"low contrast at ramp value {v:.3f}"


def test_confusion_matrix_cells_use_the_higher_contrast_text_colour():
    fig = style.plot_confusion_matrix([[100, 37], [0, 63]], ["a", "b"])
    ax = fig.axes[0]
    for text in ax.texts:
        i, j = int(text.get_position()[1]), int(text.get_position()[0])
        value = [[100, 37], [0, 63]][i][j]
        bg = style.SEQUENTIAL_CMAP(value / 100)[:3]
        got = matplotlib.colors.to_hex(text.get_color()).upper()
        other = style.PAPER if got == style.INK else style.INK
        assert _contrast_ratio(bg, got) >= _contrast_ratio(bg, other)


def test_header_synthetic_text_is_pinned():
    assert style.run_header_text(7, "Triage tickets", "synthetic") == SYNTHETIC_TEXT


def test_header_scripted_text_is_pinned():
    assert style.run_header_text(7, "Triage tickets", "scripted") == SCRIPTED_TEXT


def test_header_recorded_text_is_pinned():
    text = style.run_header_text(
        7, "Triage tickets", "recorded", model="system-one-test-model", recorded_on="2026-01-02"
    )
    assert text == RECORDED_TEXT


def test_header_live_text_is_pinned():
    text = style.run_header_text(7, "Triage tickets", "live", model="system-one-test-model")
    assert text == LIVE_TEXT


def test_synthetic_sentence_only_in_synthetic_and_scripted():
    runs = {
        "synthetic": style.RunInfo("synthetic"),
        "scripted": style.RunInfo("scripted"),
        "recorded": style.RunInfo("recorded", "m-1", "2026-01-02"),
        "live": style.RunInfo("live", "m-1"),
    }
    for mode, info in runs.items():
        text = style.run_header_text(1, "T", info)
        assert (style.SYNTHETIC_NOTICE in text) == (mode in ("synthetic", "scripted")), mode
    assert "not Jev results" in style.run_header_text(1, "T", "synthetic")
    assert "not Jev results" not in style.run_header_text(
        1, "T", "recorded", model="m", recorded_on="d"
    )
    assert "not Jev results" not in style.run_header_text(1, "T", "live", model="m")


def test_recorded_and_live_state_the_model_and_date_they_are_given():
    rec = style.run_header_text(1, "T", "recorded", model="abc-9", recorded_on="2025-12-31")
    assert "abc-9" in rec and "2025-12-31" in rec
    assert "only that recorded sample" in rec
    live = style.run_header_text(1, "T", "live", model="abc-9")
    assert "abc-9" in live


@pytest.mark.parametrize("mode", ["synthetic", "scripted", "recorded", "live"])
def test_header_never_claims_quality_latency_or_cost(mode):
    kwargs = {"model": "m-1", "recorded_on": "2026-01-02"} if mode == "recorded" else {}
    if mode == "live":
        kwargs = {"model": "m-1"}
    text = style.run_header_text(1, "T", mode, **kwargs).lower()
    for word in ("accura", "fast", "slow", "latency", "cost", "cheap", "quality", "better"):
        assert word not in text


def test_synthetic_header_never_words_itself_as_measuring_jev():
    text = style.run_header_text(1, "T", "synthetic").lower()
    assert "captured" not in text and "real jev" not in text and "live" not in text


def test_header_recipe_number_formats():
    assert style.run_header_text(7, "T", "synthetic").startswith("Recipe 07: T")
    assert style.run_header_text(42, "T", "synthetic").startswith("Recipe 42: T")
    assert style.run_header_text("07", "T", "synthetic").startswith("Recipe 07: T")


def test_run_header_prints_and_returns_the_text(capsys):
    returned = style.run_header(7, "Triage tickets", "synthetic")
    assert capsys.readouterr().out == SYNTHETIC_TEXT + "\n"
    assert returned == SYNTHETIC_TEXT


def test_run_header_accepts_run_info():
    info = style.RunInfo("live", model="m-1")
    assert style.run_header_text(1, "T", info) == style.run_header_text(1, "T", "live", model="m-1")


@pytest.mark.parametrize(
    "args, kwargs",
    [
        (("nonsense",), {}),
        (("recorded",), {"model": "m"}),
        (("recorded",), {"recorded_on": "2026-01-02"}),
        (("live",), {}),
        (("live",), {"model": "m", "recorded_on": "2026-01-02"}),
        (("synthetic",), {"model": "m"}),
        (("scripted",), {"recorded_on": "2026-01-02"}),
    ],
)
def test_header_rejects_incomplete_or_contradictory_modes(args, kwargs):
    with pytest.raises(ValueError):
        style.run_header_text(1, "T", *args, **kwargs)


def test_header_rejects_details_beside_a_run_info():
    with pytest.raises(ValueError):
        style.run_header_text(1, "T", style.RunInfo("live", model="m"), model="other")


# --- one typed answer ----------------------------------------------------------------------


def test_format_choice_orders_by_probability_and_states_provenance():
    lines = style.format_answer(CHOICE).splitlines()
    assert lines[0] == "Choice: calm (confidence 0.90)"
    assert lines[1].split()[:2] == ["calm", "0.70"]
    assert lines[2].split()[:2] == ["angry", "0.20"]
    assert lines[-1] == "Provenance: synthetic"


def test_format_score_shows_legend_and_distribution():
    text = style.format_answer(SCORE)
    assert text.splitlines()[0] == "Score: 1.43 (confidence 0.35)"
    assert "1 Workaround exists  0.57" in text
    assert "Provenance: synthetic" in text


def test_format_noul_has_no_confidence():
    text = style.format_answer(NOUL)
    assert text.splitlines()[0] == "Noul: 0.93 probability of yes (0 is no, 1 is yes)"
    assert "confidence" not in text


def test_format_answer_handles_missing_provenance_and_rejects_non_answers():
    @dataclass
    class Bare:
        noul: float

    assert style.format_answer(Bare(0.5)).splitlines()[-1] == "Provenance: not stated"
    with pytest.raises(TypeError):
        style.format_answer(object())


def test_show_answer_prints_the_formatted_text(capsys):
    returned = style.show_answer(CHOICE)
    assert capsys.readouterr().out == returned + "\n"


# --- charts --------------------------------------------------------------------------------


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    buf.seek(0)
    return mpimg.imread(buf)


def _all_figures():
    cm = np.array([[8, 2], [1, 9]])
    return [
        style.plot_confusion_matrix(cm, ["no", "yes"], title="cm"),
        style.plot_confusion_matrix(cm, ["no", "yes"], normalize=True),
        style.plot_answer_probabilities(CHOICE),
        style.plot_answer_probabilities(SCORE),
        style.plot_answer_probabilities(NOUL),
        style.plot_answer_probabilities({"a": 0.6, "b": 0.4}, highlight="a"),
        style.plot_threshold_sweep(
            [0.1, 0.5, 0.9], {"precision": [0.5, 0.7, 0.9], "recall": [0.9, 0.7, 0.3]}, chosen=0.5
        ),
        style.plot_risk_coverage(
            [0.2, 0.6, 1.0], [0.0, 0.1, 0.2], label="model", reference_risk=0.2
        ),
    ]


def test_every_chart_returns_a_figure_without_touching_pyplot():
    before = plt.get_fignums()
    figs = _all_figures()
    assert all(isinstance(f, matplotlib.figure.Figure) for f in figs)
    assert plt.get_fignums() == before


def test_every_chart_has_opaque_paper_backgrounds_in_the_saved_png():
    paper = np.array(matplotlib.colors.to_rgb(style.PAPER))
    for fig in _all_figures():
        assert fig.get_facecolor()[3] == 1.0
        for ax in fig.axes:
            assert matplotlib.colors.to_rgba(ax.get_facecolor())[3] == 1.0
            assert matplotlib.colors.to_hex(ax.get_facecolor()).upper() == style.PAPER
        image = _png(fig)
        assert np.all(image[..., 3] == 1.0), "PNG has transparent pixels"
        assert np.allclose(image[0, 0, :3], paper, atol=1 / 255)


def test_charts_do_not_depend_on_apply_style_having_been_called():
    # The default rcParams face colour is white, not paper; the helpers must still use paper.
    with matplotlib.rc_context({"figure.facecolor": "white", "axes.facecolor": "white"}):
        fig = style.plot_answer_probabilities(CHOICE)
    assert matplotlib.colors.to_hex(fig.get_facecolor()).upper() == style.PAPER


def test_charts_draw_into_a_given_axes():
    fig = matplotlib.figure.Figure()
    ax = fig.subplots()
    out = style.plot_risk_coverage([0.5, 1.0], [0.0, 0.1], ax=ax)
    assert out is fig and len(fig.axes) == 1


def test_confusion_matrix_annotates_every_cell_and_normalises_rows():
    fig = style.plot_confusion_matrix([[8, 2], [0, 0]], ["a", "b"], normalize=True)
    texts = sorted(t.get_text() for t in fig.axes[0].texts)
    assert texts == ["0.00", "0.00", "0.20", "0.80"]
    raw = style.plot_confusion_matrix([[8, 2], [1, 9]], ["a", "b"])
    assert sorted(t.get_text() for t in raw.axes[0].texts) == ["1", "2", "8", "9"]


def test_probability_bars_highlight_the_chosen_option():
    fig = style.plot_answer_probabilities(CHOICE)
    ax = fig.axes[0]
    labels = [t.get_text() for t in ax.get_yticklabels()]
    colours = [matplotlib.colors.to_hex(p.get_facecolor()).upper() for p in ax.patches]
    assert colours[labels.index("calm")] == style.PINK
    assert {c for i, c in enumerate(colours) if labels[i] != "calm"} == {style.PANEL}
    assert "calm (confidence 0.90)" == ax.get_title(loc="left")


def test_noul_bars_are_no_and_yes():
    fig = style.plot_answer_probabilities(NOUL)
    ax = fig.axes[0]
    assert [t.get_text() for t in ax.get_yticklabels()] == ["no", "yes"]
    assert [round(p.get_width(), 2) for p in ax.patches] == [0.07, 0.93]


@pytest.mark.parametrize(
    "call",
    [
        lambda: style.plot_confusion_matrix([[1, 2, 3]], ["a"]),
        lambda: style.plot_answer_probabilities({}),
        lambda: style.plot_threshold_sweep([0.1, 0.2], {"m": [1.0]}),
        lambda: style.plot_threshold_sweep([0.1, 0.2], {}),
        lambda: style.plot_threshold_sweep([], {"m": []}),
        lambda: style.plot_risk_coverage([0.1, 0.2], [0.1]),
    ],
)
def test_charts_reject_bad_shapes(call):
    with pytest.raises(ValueError):
        call()


# --- global style and import hygiene -------------------------------------------------------


def test_importing_style_changes_no_global_state():
    probe = """
import sys, matplotlib
keys = [k for k in matplotlib.rcParams if k != "backend"]
before = {k: matplotlib.rcParams[k] for k in keys}
import jev_cookbook.style
assert {k: matplotlib.rcParams[k] for k in keys} == before, "rcParams changed on import"
assert "jev_sequential" not in matplotlib.colormaps, "cmap registered on import"
assert "typesafe_sdk" not in sys.modules and "typesafe" not in sys.modules
assert "matplotlib.pyplot" not in sys.modules, "pyplot imported on import"
"""
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_apply_style_sets_opaque_paper_defaults():
    with matplotlib.rc_context():
        style.apply_style()
        rc = matplotlib.rcParams
        assert matplotlib.colors.to_hex(rc["figure.facecolor"]).upper() == style.PAPER
        assert matplotlib.colors.to_hex(rc["axes.facecolor"]).upper() == style.PAPER
        assert matplotlib.colors.to_hex(rc["savefig.facecolor"]).upper() == style.PAPER
        assert rc["savefig.transparent"] is False
        assert rc["image.cmap"] == "jev_sequential"


# --- colour-blind readability --------------------------------------------------------------

# Machado, Oliveira and Fernandes (2009), severity 1.0, applied to linear RGB.
_CVD = {
    "deuteranopia": np.array(
        [
            [0.367322, 0.860646, -0.227968],
            [0.280085, 0.672501, 0.047413],
            [-0.011820, 0.042940, 0.968881],
        ]
    ),
    "protanopia": np.array(
        [
            [0.152286, 1.052583, -0.204868],
            [0.114503, 0.786281, 0.099216],
            [-0.003882, -0.048116, 1.051998],
        ]
    ),
}


def _lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _enc(c):
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(np.maximum(c, 0), 1 / 2.4) - 0.055)


def _lab(rgb):
    xyz = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = xyz @ _lin(rgb) / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def _rgb(hex_colour):
    return np.array(matplotlib.colors.to_rgb(hex_colour))


def _delta_e(a, b, deficiency=None):
    ra, rb = _rgb(a), _rgb(b)
    if deficiency:
        ra = _enc(np.clip(_CVD[deficiency] @ _lin(ra), 0, 1))
        rb = _enc(np.clip(_CVD[deficiency] @ _lin(rb), 0, 1))
    return float(np.linalg.norm(_lab(ra) - _lab(rb)))


@pytest.mark.parametrize("deficiency", [None, "deuteranopia", "protanopia"])
def test_categorical_colours_stay_distinguishable_under_colour_blindness(deficiency):
    # CIELAB distance (dE76) of 20 or more is clearly distinct; the measured minimum is higher.
    pairs = itertools.combinations(style.CATEGORICAL, 2)
    assert min(_delta_e(a, b, deficiency) for a, b in pairs) >= 20


@pytest.mark.parametrize("deficiency", [None, "deuteranopia", "protanopia"])
def test_highlight_and_panel_are_distinguishable_from_the_bar_outline(deficiency):
    # Chosen bar (pink) against unchosen bars (panel grey), and the score line against paper.
    assert _delta_e(style.PINK, style.PANEL, deficiency) >= 15
    assert _delta_e(style.MAGENTA, style.PAPER, deficiency) >= 40


def test_sequential_ramp_lightness_strictly_decreases_with_clear_steps():
    stops = [_lab(_rgb(c))[0] for c in style.SEQUENTIAL]
    steps = -np.diff(stops)
    assert np.all(steps >= 10), f"lightness steps too small or not monotonic: {steps}"
    # The same holds in the sampled colormap, so it reads in greyscale and for any deficiency.
    sampled = [_lab(np.array(style.SEQUENTIAL_CMAP(v)[:3]))[0] for v in np.linspace(0, 1, 9)]
    assert np.all(np.diff(sampled) < 0)


def test_palette_constants_match_the_brand():
    assert (style.PINK, style.INK, style.MAGENTA, style.PANEL, style.PAPER) == (
        "#F386A1",
        "#1E1E1E",
        "#E551BA",
        "#DEDEDE",
        "#FEFEFE",
    )
