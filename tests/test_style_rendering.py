"""Rendering assertions for the chart helpers in jev_cookbook.style (issue #288).

A figure committed to a notebook is content a reader trusts, yet the rest of the suite only
checks that it exists and has bytes. These tests draw each helper's figure on the Agg canvas
and assert three properties of the *rendered artists*, with no image comparison, no golden
files and no pixel reads, so they do not move when matplotlib or its fonts are upgraded:

1. No two text artists' (or a text artist's and a legend's) bounding boxes intersect.
2. Each tick label's rendered text is its source string, or an ellipsis abbreviation of it
   that is still unique: two different sources never render as the same tick.
3. Each axis title names the quantity plotted on that axis, and not the other axis's.

The assertion functions are module-level and are themselves proved able to fail (see the
"planted defect" tests): a check that cannot redden is a check that proves nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest
from matplotlib.axis import Axis
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.legend import Legend
from matplotlib.text import Text

from jev_cookbook import style

# --- the assertions ------------------------------------------------------------------------


def _draw(fig: Figure) -> None:
    """Lay the figure out and draw it on the Agg canvas (what a saved PNG would see)."""
    FigureCanvasAgg(fig)
    fig.canvas.draw()


def _in_view_ticks(axis: Axis) -> list:
    """The ticks the axis actually draws: matplotlib keeps stale ticks beyond the view limits."""
    lo, hi = sorted(axis.get_view_interval())
    eps = 1e-9 * max(1.0, abs(hi - lo))
    return [t for t in axis.get_major_ticks() if lo - eps <= t.get_loc() <= hi + eps]


def tick_texts(axis: Axis) -> list[str]:
    """The text each drawn tick label of ``axis`` renders (call after the figure is drawn)."""
    return [t.label1.get_text() for t in _in_view_ticks(axis) if t.label1.get_visible()]


def rendered_blocks(fig: Figure) -> list[tuple[str, object]]:
    """Every visible, non-empty text artist and every legend, as ``(description, bbox)``.

    A legend counts once, as its whole box (frame included); the texts inside it are not
    listed separately. Tick labels beyond the view limits are not drawn and are left out.
    """
    _draw(fig)
    legends = [lg for lg in fig.findobj(Legend) if lg.get_visible()]
    inside_legend = {id(t) for lg in legends for t in lg.get_texts()}
    undrawn = set()
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            in_view = {id(t) for t in _in_view_ticks(axis)}
            for tick in axis.get_major_ticks():
                if id(tick) not in in_view:
                    undrawn |= {id(tick.label1), id(tick.label2)}
    blocks: list[tuple[str, object]] = []
    for text in fig.findobj(Text):
        if not text.get_visible() or not text.get_text().strip():
            continue
        if id(text) in inside_legend or id(text) in undrawn:
            continue
        blocks.append((f"text {text.get_text()!r}", text.get_window_extent()))
    for lg in legends:
        names = ", ".join(repr(t.get_text()) for t in lg.get_texts())
        blocks.append((f"legend [{names}]", lg.get_window_extent()))
    return blocks


def _intersect(a, b) -> bool:
    """Strict overlap of two display-space boxes: touching edges do not count."""
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1


def assert_no_overlapping_text(fig: Figure) -> None:
    """Property 1: no two text artists or legends intersect, and none is cut off the figure."""
    blocks = rendered_blocks(fig)
    assert blocks, "nothing rendered; the assertion would pass vacuously"
    page = fig.bbox
    for name, box in blocks:
        inside = box.x0 >= page.x0 and box.y0 >= page.y0 and box.x1 <= page.x1 and box.y1 <= page.y1
        assert inside, f"{name} is cut off by the figure edge: {box.extents} not in {page.extents}"
    for i, (name_a, box_a) in enumerate(blocks):
        for name_b, box_b in blocks[i + 1 :]:
            assert not _intersect(box_a, box_b), (
                f"{name_a} {np.round(box_a.extents, 1).tolist()} overlaps "
                f"{name_b} {np.round(box_b.extents, 1).tolist()}"
            )


def assert_ticks_faithful(rendered: list[str], sources: list[str], *, exact: bool = False) -> None:
    """Property 2: every tick renders its source string, or an ellipsis abbreviation of it.

    Whatever the abbreviation, the number of *distinct* rendered ticks must equal the number
    of distinct source strings, so no two classes can share a tick. ``exact=True`` demands
    the source string itself, with no abbreviation. Keyed on the rendered text, not on its
    length, so a prefix collision cannot slip past it at any label length.
    """
    assert len(rendered) == len(sources), f"{len(rendered)} ticks drawn for {len(sources)} labels"
    for shown, source in zip(rendered, sources, strict=True):
        if shown == source:
            continue
        abbreviation = (
            not exact
            and shown.endswith("...")
            and len(shown) < len(source)
            and source.startswith(shown[:-3])
        )
        assert abbreviation, f"tick renders {shown!r}, its source label is {source!r}"
    assert len(set(rendered)) == len(set(sources)), (
        f"{len(set(sources))} distinct labels render as {len(set(rendered))} distinct ticks: "
        f"{rendered}"
    )


# The words that name each quantity an axis can carry in these charts. An axis title must
# contain a word of the quantity on that axis and no word of the quantity on another axis.
VOCABULARY: dict[str, tuple[str, ...]] = {
    "coverage": ("coverage",),
    "risk": ("risk", "error rate"),
    "threshold": ("threshold",),
    "metric": ("metric",),
    "probability": ("probability",),
    "gold": ("gold",),
    "predicted": ("predicted",),
}


def assert_axis_title(axis: Axis, quantity: str | None, *, others: tuple[str, ...] = ()) -> None:
    """Property 3: the axis title names ``quantity`` and none of the ``others``.

    ``quantity=None`` means the axis carries only category names and must have no title.
    """
    title = axis.get_label().get_text().lower()
    if quantity is None:
        assert title == "", f"axis carries categories but is titled {title!r}"
        return
    assert any(word in title for word in VOCABULARY[quantity]), (
        f"axis title {title!r} does not name its data ({quantity})"
    )
    for other in others:
        assert not any(word in title for word in VOCABULARY[other]), (
            f"axis title {title!r} names {other}, but the axis carries {quantity}"
        )


# --- stand-ins for the typed answers -------------------------------------------------------


@dataclass
class FakeScore:
    score: float
    probabilities: dict
    confidence: float
    legend: dict = field(default_factory=dict)
    provenance: str = "synthetic"


@dataclass
class FakeChoice:
    choice: str
    probabilities: dict
    confidence: float
    provenance: str = "synthetic"


@dataclass
class FakeNoul:
    noul: float
    provenance: str = "synthetic"


LEVELS = {"0": "Cosmetic", "1": "Workaround exists", "2": "Blocking"}
LEVEL_NAMES = [f"{k} {v}" for k, v in LEVELS.items()]
# The ordinary confident case (#286): the highest level is the most probable answer, and the
# y axis is inverted, so its bar is the bottom row, under a legend fixed to the lower right.
CONFIDENT_HIGH = FakeScore(1.96, {"0": 0.0, "1": 0.02, "2": 0.98}, 0.9, LEVELS)
CONFIDENT_LOW = FakeScore(0.04, {"0": 0.97, "1": 0.02, "2": 0.01}, 0.9, LEVELS)
SPLIT = FakeScore(1.0, {"0": 0.5, "1": 0.0, "2": 0.5}, 0.2, LEVELS)
MIDDLE = FakeScore(1.43, {"0": 0.0, "1": 0.57, "2": 0.43}, 0.35, LEVELS)
# Not normalised (a plain test double can say anything): both ends are high, so no corner of
# the axes is free and the legend has to leave them.
BOTH_ENDS_HIGH = FakeScore(1.0, {"0": 0.95, "1": 0.0, "2": 0.95}, 0.5, LEVELS)
LONG_LEGEND = FakeScore(
    3.9,
    {"0": 0.0, "1": 0.0, "2": 0.01, "3": 0.01, "4": 0.98},
    0.9,
    {
        "0": "The reader cannot tell what happened to their request or what to do next",
        "1": "The reader can find the outcome and the next step, but only with effort",
        "2": "The reader finds the outcome, and the next step is easy to miss",
        "3": "The reader finds both, and the wording is merely awkward",
        "4": "Everything the reader needs is plain on first reading",
    },
)

CHOICE = FakeChoice("calm", {"calm": 0.7, "angry": 0.2, "excited": 0.1}, 0.9)
CONFIDENT_CHOICE = FakeChoice("refund", {"refund": 0.99, "replace": 0.01}, 0.99)

# --- the confusion-matrix label sets -------------------------------------------------------

SHORT = ["no", "yes"]
# Longer than 14 characters but still unique once abbreviated (recipe 47's case, #265).
UNIQUE_AFTER_SHORTENING = [
    "factual_disagreement",
    "not_conflicting",
    "partial_overlap",
    "same_claim",
    "unrelated",
]
# Three labels share their first eleven characters ("customer_re"), the #278 / #265 case.
PREFIX_COLLISION = [
    "customer_refund_requested",
    "customer_refund_denied",
    "customer_replacement",
    "other",
]


def _matrix(n: int) -> np.ndarray:
    return np.arange(n * n).reshape(n, n) % 7 + np.eye(n, dtype=int) * 5


# --- every helper, rendered ----------------------------------------------------------------


@dataclass
class Case:
    """One rendered figure and what its artists must say."""

    fig: Figure
    x_ticks: list[str] | None = None
    y_ticks: list[str] | None = None
    x_title: str | None = None
    y_title: str | None = None
    exact_ticks: bool = False


def _confusion(labels, *, normalize=False, exact=False) -> Case:
    fig = style.plot_confusion_matrix(_matrix(len(labels)), labels, normalize=normalize)
    return Case(fig, labels, labels, "predicted", "gold", exact_ticks=exact)


def _answer(answer, names, *, exact=False) -> Case:
    fig = style.plot_answer_probabilities(answer)
    return Case(fig, None, names, "probability", None, exact_ticks=exact)


def _sweep(**kwargs) -> Case:
    thresholds = [0.1, 0.3, 0.5, 0.7, 0.9]
    metrics = {"precision": [0.5, 0.6, 0.7, 0.8, 0.9], "recall": [0.9, 0.8, 0.7, 0.4, 0.2]}
    fig = style.plot_threshold_sweep(thresholds, metrics, **kwargs)
    return Case(fig, None, None, "threshold", "metric")


def _risk(**kwargs) -> Case:
    coverage, risk = [0.2, 0.5, 0.8, 1.0], [0.0, 0.05, 0.1, 0.2]
    fig = style.plot_risk_coverage(coverage, risk, **kwargs)
    return Case(fig, None, None, "coverage", "risk")


CASES = {
    "confusion short": lambda: _confusion(SHORT, exact=True),
    "confusion short normalised": lambda: _confusion(SHORT, normalize=True, exact=True),
    "confusion unique after shortening": lambda: _confusion(UNIQUE_AFTER_SHORTENING),
    "confusion prefix collision": lambda: _confusion(PREFIX_COLLISION, exact=True),
    "answer choice": lambda: _answer(CHOICE, ["calm", "angry", "excited"], exact=True),
    "answer confident choice": lambda: _answer(CONFIDENT_CHOICE, ["refund", "replace"], exact=True),
    "answer noul": lambda: _answer(FakeNoul(0.93), ["no", "yes"], exact=True),
    "answer mapping": lambda: _answer({"a": 0.6, "b": 0.4}, ["a", "b"], exact=True),
    "answer score confident high": lambda: _answer(CONFIDENT_HIGH, LEVEL_NAMES, exact=True),
    "answer score confident low": lambda: _answer(CONFIDENT_LOW, LEVEL_NAMES, exact=True),
    "answer score split": lambda: _answer(SPLIT, LEVEL_NAMES, exact=True),
    "answer score middle": lambda: _answer(MIDDLE, LEVEL_NAMES, exact=True),
    "answer score both ends high": lambda: _answer(BOTH_ENDS_HIGH, LEVEL_NAMES, exact=True),
    "answer score long legend": lambda: _answer(
        LONG_LEGEND, [f"{k} {v}" for k, v in LONG_LEGEND.legend.items()]
    ),
    "sweep": lambda: _sweep(),
    "sweep chosen": lambda: _sweep(chosen=0.5),
    "risk coverage": lambda: _risk(),
    "risk coverage label and reference": lambda: _risk(label="model", reference_risk=0.2),
}


@pytest.fixture(params=sorted(CASES))
def case(request) -> Case:
    return CASES[request.param]()


def test_no_two_text_artists_overlap_in_any_helper_figure(case):
    assert_no_overlapping_text(case.fig)


def test_every_tick_renders_its_source_label(case):
    ax = case.fig.axes[0]
    _draw(case.fig)
    for axis, sources in ((ax.xaxis, case.x_ticks), (ax.yaxis, case.y_ticks)):
        if sources is not None:
            assert_ticks_faithful(tick_texts(axis), sources, exact=case.exact_ticks)


def test_every_axis_title_names_what_is_plotted_on_it(case):
    ax = case.fig.axes[0]
    _draw(case.fig)
    quantities = {q for q in (case.x_title, case.y_title) if q}
    assert_axis_title(ax.xaxis, case.x_title, others=tuple(quantities - {case.x_title}))
    assert_axis_title(ax.yaxis, case.y_title, others=tuple(quantities - {case.y_title}))


def test_the_titled_quantities_are_the_data_actually_plotted():
    coverage, risk = [0.2, 0.5, 0.8, 1.0], [0.0, 0.05, 0.1, 0.2]
    ax = style.plot_risk_coverage(coverage, risk).axes[0]
    (line,) = ax.lines
    assert list(line.get_xdata()) == coverage and ax.get_xlabel().startswith("Coverage")
    assert list(line.get_ydata()) == risk and ax.get_ylabel().startswith("Risk")

    thresholds = [0.1, 0.5, 0.9]
    ax = style.plot_threshold_sweep(thresholds, {"f1": [0.2, 0.9, 0.4]}).axes[0]
    assert list(ax.lines[0].get_xdata()) == thresholds and ax.get_xlabel() == "Threshold"

    ax = style.plot_answer_probabilities({"a": 0.6, "b": 0.4}).axes[0]
    assert [p.get_width() for p in ax.patches] == [0.6, 0.4] and ax.get_xlabel() == "Probability"


# --- the known defects ---------------------------------------------------------------------


def _legend_and_labels(fig: Figure):
    _draw(fig)
    ax = fig.axes[0]
    (legend,) = [lg for lg in fig.findobj(Legend) if lg.get_visible()]
    return ax, legend.get_window_extent(), [t.get_window_extent() for t in ax.texts]


def test_a_confident_score_legend_does_not_cover_a_value_label():
    """#286. The highest level is the bottom bar; the lower-right legend used to sit on 0.98."""
    ax, legend, labels = _legend_and_labels(style.plot_answer_probabilities(CONFIDENT_HIGH))
    assert len(labels) == 3
    assert not any(_intersect(legend, label) for label in labels)
    # The legend moved to the opposite corner rather than disappearing or shrinking.
    middle = ax.get_window_extent()
    assert legend.y0 > (middle.y0 + middle.y1) / 2 and legend.x0 > (middle.x0 + middle.x1) / 2


def test_a_score_legend_keeps_the_lower_right_corner_when_nothing_is_there():
    ax, legend, labels = _legend_and_labels(style.plot_answer_probabilities(CONFIDENT_LOW))
    assert not any(_intersect(legend, label) for label in labels)
    middle = ax.get_window_extent()
    assert legend.y1 < (middle.y0 + middle.y1) / 2 and legend.x0 > (middle.x0 + middle.x1) / 2


def test_a_score_legend_leaves_the_axes_when_no_corner_is_free():
    fig = style.plot_answer_probabilities(BOTH_ENDS_HIGH)
    ax, legend, labels = _legend_and_labels(fig)
    assert not any(_intersect(legend, label) for label in labels)
    assert legend.x0 >= ax.get_window_extent().x1


def test_a_label_set_sharing_eleven_characters_renders_distinct_full_ticks():
    """#278 / #265. Three labels share "customer_re"; each must keep its own, whole, tick."""
    fig = style.plot_confusion_matrix(_matrix(4), PREFIX_COLLISION)
    ax = fig.axes[0]
    _draw(fig)
    assert tick_texts(ax.xaxis) == PREFIX_COLLISION
    assert tick_texts(ax.yaxis) == PREFIX_COLLISION


def test_labels_that_stay_unique_are_still_abbreviated_as_before():
    fig = style.plot_confusion_matrix(_matrix(5), UNIQUE_AFTER_SHORTENING)
    ax = fig.axes[0]
    _draw(fig)
    expected = ["factual_dis...", "not_conflic...", "partial_ove...", "same_claim", "unrelated"]
    assert expected == [_old_truncation(s) for s in UNIQUE_AFTER_SHORTENING]
    assert tick_texts(ax.xaxis) == expected == tick_texts(ax.yaxis)


# --- the assertions can fail: planted defects ----------------------------------------------


def _planted_overlap() -> Figure:
    fig = Figure()
    ax = fig.subplots()
    ax.text(0.5, 0.5, "first label")
    ax.text(0.52, 0.5, "second label")
    return fig


def test_planted_overlapping_labels_redden_the_overlap_assertion():
    with pytest.raises(AssertionError, match="overlaps"):
        assert_no_overlapping_text(_planted_overlap())


def test_planted_legend_over_a_value_label_reddens_the_overlap_assertion():
    """The #286 defect, put back on the real figure: the old fixed lower-right legend."""
    fig = style.plot_answer_probabilities(CONFIDENT_HIGH)
    ax = fig.axes[0]
    ax.get_legend().remove()
    ax.legend(loc="lower right")
    with pytest.raises(AssertionError, match="legend"):
        assert_no_overlapping_text(fig)


def test_planted_text_off_the_figure_reddens_the_overlap_assertion():
    fig = Figure()
    fig.text(0.97, 0.5, "runs past the right-hand edge of the figure")
    with pytest.raises(AssertionError, match="cut off"):
        assert_no_overlapping_text(fig)


def test_overlap_assertion_refuses_to_pass_on_an_empty_figure():
    with pytest.raises(AssertionError, match="nothing rendered"):
        assert_no_overlapping_text(Figure())


def _old_truncation(label: str) -> str:
    """What plot_confusion_matrix drew before #265: 11 characters and an ellipsis past 14."""
    return label if len(label) <= 14 else label[:11].rstrip() + "..."


def test_planted_prefix_collision_reddens_the_tick_assertion():
    """The old behaviour, put back: three different labels drawn as one tick."""
    fig = style.plot_confusion_matrix(_matrix(4), PREFIX_COLLISION)
    ax = fig.axes[0]
    ax.set_xticks(range(4), labels=[_old_truncation(x) for x in PREFIX_COLLISION])
    _draw(fig)
    shown = tick_texts(ax.xaxis)
    assert shown.count("customer_re...") == 3
    with pytest.raises(AssertionError, match="distinct"):
        assert_ticks_faithful(shown, PREFIX_COLLISION)


@pytest.mark.parametrize(
    ("rendered", "sources", "message"),
    [
        (["yes", "no"], ["yes", "no", "maybe"], "ticks drawn"),
        (["yez", "no"], ["yes", "no"], "its source label"),
        (["a different..."], ["a long label here"], "its source label"),
        (["x..."], ["x"], "its source label"),
    ],
)
def test_tick_assertion_rejects_misspelt_and_unrelated_ticks(rendered, sources, message):
    with pytest.raises(AssertionError, match=message):
        assert_ticks_faithful(rendered, sources)


def test_exact_mode_rejects_an_abbreviation_that_the_default_accepts():
    sources = ["a_rather_long_label"]
    assert_ticks_faithful(["a_rather_lo..."], sources)
    with pytest.raises(AssertionError, match="its source label"):
        assert_ticks_faithful(["a_rather_lo..."], sources, exact=True)


def test_planted_mismatched_axis_titles_redden_the_title_assertion():
    fig = style.plot_risk_coverage([0.2, 0.6, 1.0], [0.0, 0.1, 0.2])
    ax = fig.axes[0]
    assert_axis_title(ax.xaxis, "coverage", others=("risk",))
    assert_axis_title(ax.yaxis, "risk", others=("coverage",))
    # Titles swapped: the x axis carries coverage but is called risk.
    ax.set_xlabel("Risk (error rate on answered cases)")
    ax.set_ylabel("Coverage (fraction of cases answered)")
    with pytest.raises(AssertionError, match="does not name its data"):
        assert_axis_title(ax.xaxis, "coverage", others=("risk",))
    with pytest.raises(AssertionError, match="does not name its data"):
        assert_axis_title(ax.yaxis, "risk", others=("coverage",))


def test_planted_title_naming_both_quantities_reddens_the_title_assertion():
    fig = style.plot_risk_coverage([0.2, 0.6, 1.0], [0.0, 0.1, 0.2])
    ax = fig.axes[0]
    ax.set_xlabel("Coverage, or risk")
    with pytest.raises(AssertionError, match="names risk"):
        assert_axis_title(ax.xaxis, "coverage", others=("risk",))


def test_planted_title_on_a_category_axis_reddens_the_title_assertion():
    ax = style.plot_answer_probabilities(CHOICE).axes[0]
    assert_axis_title(ax.yaxis, None)
    ax.set_ylabel("Predicted")
    with pytest.raises(AssertionError, match="carries categories"):
        assert_axis_title(ax.yaxis, None)


def test_the_cases_cover_every_plotting_helper():
    """A new ``plot_*`` helper must be added to CASES (and to this table) to pass."""
    by_prefix = {
        "confusion": "plot_confusion_matrix",
        "answer": "plot_answer_probabilities",
        "sweep": "plot_threshold_sweep",
        "risk": "plot_risk_coverage",
    }
    exercised = {by_prefix[name.split()[0]] for name in CASES}
    assert exercised == {n for n in style.__all__ if n.startswith("plot_")}
