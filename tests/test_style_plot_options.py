"""Options of the chart helpers in jev_cookbook.style that a recipe's own data can need.

* ``plot_confusion_matrix`` with a different vocabulary on each axis, and axis titles of the
  caller's choosing (#261), and the abbreviation-collision rule applied to each axis on its own
  (#265).
* ``plot_risk_coverage(connect=False)`` for separate policies that must not be joined by a line
  that implies a frontier (#267).

The tests read what was *rendered* (tick text and axis titles after the figure is drawn; the
pixels of the saved figure for the line), not the arguments of the call, because the defects
these options answer lived in committed PNGs that every source-level check let through.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from matplotlib.axis import Axis
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.text import Text

from jev_cookbook import style

# --- helpers -------------------------------------------------------------------------------


def _draw(fig: Figure) -> None:
    FigureCanvasAgg(fig)
    fig.canvas.draw()


def _ticks(axis: Axis) -> list[str]:
    """The text of each tick the axis draws (call after the figure is drawn)."""
    lo, hi = sorted(axis.get_view_interval())
    return [
        t.label1.get_text() for t in axis.get_major_ticks() if lo - 1e-9 <= t.get_loc() <= hi + 1e-9
    ]


def _rotation(axis: Axis) -> float:
    return axis.get_majorticklabels()[0].get_rotation()


def _no_text_overlaps(fig: Figure) -> None:
    _draw(fig)
    boxes = [
        (t.get_text(), t.get_window_extent())
        for t in fig.findobj(Text)
        if t.get_visible() and t.get_text().strip()
    ]
    assert boxes
    for i, (a, box_a) in enumerate(boxes):
        for b, box_b in boxes[i + 1 :]:
            overlap = (
                box_a.x0 < box_b.x1
                and box_b.x0 < box_a.x1
                and box_a.y0 < box_b.y1
                and box_b.y0 < box_a.y1
            )
            assert not overlap, f"{a!r} overlaps {b!r}"


# --- #261: distinct row and column vocabularies --------------------------------------------

GOLD_CONTENT = ["clear", "borderline", "violates"]
FINAL_ACTION = ["allowed", "held"]
CONTENT_BY_ACTION = np.array([[9, 0], [3, 4], [0, 8]])


def test_a_matrix_whose_axes_are_different_vocabularies_is_labelled_per_axis():
    """The occasion for #261: a matrix of gold content against final action read "Predicted:
    clear / violates" on its x axis, where the columns were ``allowed`` / ``held``."""
    fig = style.plot_confusion_matrix(
        CONTENT_BY_ACTION,
        row_labels=GOLD_CONTENT,
        col_labels=FINAL_ACTION,
        row_axis_title="Gold content",
        col_axis_title="Final action",
    )
    ax = fig.axes[0]
    _draw(fig)
    assert _ticks(ax.xaxis) == FINAL_ACTION
    assert _ticks(ax.yaxis) == GOLD_CONTENT
    assert ax.get_xlabel() == "Final action"
    assert ax.get_ylabel() == "Gold content"
    # Every cell is annotated with its own count, row by row.
    cells = {(t.get_position()[1], t.get_position()[0]): t.get_text() for t in ax.texts}
    assert cells == {(i, j): str(CONTENT_BY_ACTION[i, j]) for i in range(3) for j in range(2)}
    _no_text_overlaps(fig)


def test_the_axis_titles_default_to_gold_and_predicted():
    fig = style.plot_confusion_matrix([[8, 2], [1, 9]], ["no", "yes"])
    ax = fig.axes[0]
    assert (ax.get_ylabel(), ax.get_xlabel()) == ("Gold", "Predicted")
    # Naming only the labels of one axis leaves the titles as they were.
    fig = style.plot_confusion_matrix(
        [[8, 2], [1, 9]], row_labels=["a", "b"], col_labels=["c", "d"]
    )
    assert (fig.axes[0].get_ylabel(), fig.axes[0].get_xlabel()) == ("Gold", "Predicted")


def test_titles_can_be_set_without_changing_the_labels():
    fig = style.plot_confusion_matrix(
        [[8, 2], [1, 9]], ["no", "yes"], row_axis_title="Reviewer", col_axis_title="Jev"
    )
    ax = fig.axes[0]
    _draw(fig)
    assert (ax.get_ylabel(), ax.get_xlabel()) == ("Reviewer", "Jev")
    assert _ticks(ax.xaxis) == _ticks(ax.yaxis) == ["no", "yes"]


def test_one_label_list_still_names_both_axes_and_each_axis_can_override_it():
    counts = [[8, 2], [1, 9]]
    both = style.plot_confusion_matrix(counts, ["no", "yes"])
    rows_only = style.plot_confusion_matrix(counts, ["no", "yes"], row_labels=["x", "z"])
    cols_only = style.plot_confusion_matrix(counts, ["no", "yes"], col_labels=["p", "q"])
    for fig in (both, rows_only, cols_only):
        _draw(fig)
    assert _ticks(both.axes[0].xaxis) == _ticks(both.axes[0].yaxis) == ["no", "yes"]
    assert _ticks(rows_only.axes[0].yaxis) == ["x", "z"]
    assert _ticks(rows_only.axes[0].xaxis) == ["no", "yes"]
    assert _ticks(cols_only.axes[0].xaxis) == ["p", "q"]
    assert _ticks(cols_only.axes[0].yaxis) == ["no", "yes"]


@dataclass
class _Matrix:
    labels: list[str]
    matrix: np.ndarray


def test_an_object_with_labels_and_matrix_is_still_one_vocabulary():
    """``ConfusionMatrix`` is not changed: its two axes share ``.labels``. A table with two
    vocabularies is a plain array plus ``row_labels`` and ``col_labels``."""
    cm = _Matrix(["no", "yes"], np.array([[8, 2], [1, 9]]))
    fig = style.plot_confusion_matrix(cm)
    _draw(fig)
    ax = fig.axes[0]
    assert _ticks(ax.xaxis) == _ticks(ax.yaxis) == ["no", "yes"]
    assert (ax.get_ylabel(), ax.get_xlabel()) == ("Gold", "Predicted")


def test_explicit_row_and_column_labels_need_no_shared_list():
    fig = style.plot_confusion_matrix(
        CONTENT_BY_ACTION, row_labels=GOLD_CONTENT, col_labels=FINAL_ACTION
    )
    _draw(fig)
    assert _ticks(fig.axes[0].yaxis) == GOLD_CONTENT


def test_a_figure_for_one_vocabulary_is_unchanged_by_naming_it_for_both_axes():
    """Same pixels whether the vocabulary arrives as ``labels`` or as the two new options."""
    counts = np.array([[8, 2, 0], [1, 9, 3], [0, 4, 7]])
    names = ["one", "two", "a_rather_long_label_x"]
    a = style.plot_confusion_matrix(counts, names, title="t")
    b = style.plot_confusion_matrix(counts, row_labels=names, col_labels=names, title="t")
    assert _png(a) == _png(b)
    assert a.get_size_inches().tolist() == b.get_size_inches().tolist()


def test_the_figure_grows_with_each_axis():
    wide = style.plot_confusion_matrix(
        np.ones((2, 7)), row_labels=list("ab"), col_labels=list("cdefghi")
    )
    tall = style.plot_confusion_matrix(
        np.ones((7, 2)), row_labels=list("cdefghi"), col_labels=list("ab")
    )
    w_wide, h_wide = wide.get_size_inches()
    w_tall, h_tall = tall.get_size_inches()
    assert w_wide > h_wide and h_tall > w_tall


@pytest.mark.parametrize(
    "call",
    [
        # no labels at all
        lambda: style.plot_confusion_matrix([[1, 2], [3, 4]]),
        # only one axis named, and nothing for the other
        lambda: style.plot_confusion_matrix([[1, 2], [3, 4]], row_labels=["a", "b"]),
        lambda: style.plot_confusion_matrix([[1, 2], [3, 4]], col_labels=["a", "b"]),
        # a rectangular table needs both vocabularies
        lambda: style.plot_confusion_matrix(CONTENT_BY_ACTION, GOLD_CONTENT),
        # counts that do not match the two lists
        lambda: style.plot_confusion_matrix(
            CONTENT_BY_ACTION, row_labels=FINAL_ACTION, col_labels=GOLD_CONTENT
        ),
        lambda: style.plot_confusion_matrix([[1, 2, 3]], ["a"]),
    ],
    ids=["none", "rows-only", "cols-only", "rectangular-one-list", "swapped", "ragged"],
)
def test_labels_that_do_not_fit_the_counts_are_refused(call):
    with pytest.raises(ValueError):
        call()


def test_a_rectangular_refusal_names_both_dimensions():
    with pytest.raises(ValueError, match=r"3x2.*shape \(2, 3\)"):
        style.plot_confusion_matrix(
            np.ones((2, 3)), row_labels=GOLD_CONTENT, col_labels=FINAL_ACTION
        )


# --- #265: the abbreviation-collision rule holds on each axis ------------------------------

SHARED_PREFIX = ["customer_refund", "customer_return", "customer_replace"]


def test_a_colliding_axis_keeps_whole_labels_and_the_other_axis_is_abbreviated_as_before():
    """Rows collide at 14 characters; the columns are long but distinct, so they abbreviate."""
    long_distinct = ["alternative_method", "thread_previously_held", "ok"]
    fig = style.plot_confusion_matrix(
        np.ones((3, 3)), row_labels=SHARED_PREFIX, col_labels=long_distinct
    )
    ax = fig.axes[0]
    _draw(fig)
    assert _ticks(ax.yaxis) == SHARED_PREFIX
    assert _ticks(ax.xaxis) == ["alternative...", "thread_prev...", "ok"]
    assert _rotation(ax.xaxis) == 0


def test_a_colliding_column_axis_keeps_whole_labels_stood_on_end():
    long_distinct = ["alternative_method", "thread_previously_held", "ok"]
    fig = style.plot_confusion_matrix(
        np.ones((3, 3)), row_labels=long_distinct, col_labels=SHARED_PREFIX
    )
    ax = fig.axes[0]
    _draw(fig)
    assert _ticks(ax.xaxis) == SHARED_PREFIX
    assert _rotation(ax.xaxis) == 90
    assert _ticks(ax.yaxis) == ["alternative...", "thread_prev...", "ok"]
    assert len(set(_ticks(ax.xaxis))) == 3


def test_labels_sharing_eleven_characters_are_distinct_ticks_on_both_axes():
    fig = style.plot_confusion_matrix(np.ones((3, 3)), SHARED_PREFIX)
    ax = fig.axes[0]
    _draw(fig)
    assert _ticks(ax.xaxis) == _ticks(ax.yaxis) == SHARED_PREFIX


# --- #267: connect=False ------------------------------------------------------------------

# Three separate policies at the coverage and risk a Level 4 recipe reports them: not on one
# curve, and not in ascending coverage (reject-all and approve-all both cover everything).
POLICY_COVERAGE = [1.0, 0.8667, 1.0]
POLICY_RISK = [0.1, 0.05, 0.3]


def _png(fig: Figure) -> bytes:
    import io

    buffer = io.BytesIO()
    FigureCanvasAgg(fig)
    fig.savefig(buffer, format="png")
    return buffer.getvalue()


def _pixels(fig: Figure) -> np.ndarray:
    _draw(fig)
    return np.asarray(fig.canvas.buffer_rgba())[..., :3].astype(float)


def _ink_near(fig: Figure, point: tuple[float, float], radius: int = 3) -> bool:
    """Is there a dark pixel within ``radius`` pixels of data ``point`` in the drawn figure?

    The grid is the light panel grey and the background is paper, so a dark pixel is a mark
    the helper drew: the line or a marker.
    """
    image = _pixels(fig)
    ax = fig.axes[0]
    x, y = ax.transData.transform(point)
    row = int(round(image.shape[0] - y))
    col = int(round(x))
    window = image[row - radius : row + radius + 1, col - radius : col + radius + 1]
    return bool((window.mean(axis=-1) < 90).any())


def _midpoints(x, y) -> list[tuple[float, float]]:
    return [((x[i] + x[i + 1]) / 2, (y[i] + y[i + 1]) / 2) for i in range(len(x) - 1)]


def test_connect_false_draws_unordered_policies_without_a_line_between_them():
    """Decoded from the rendered figure, not read from the call: between two plotted policies
    the default draws a line and ``connect=False`` leaves the background."""
    joined = style.plot_risk_coverage(POLICY_COVERAGE, POLICY_RISK)
    points = style.plot_risk_coverage(POLICY_COVERAGE, POLICY_RISK, connect=False)
    for midpoint in _midpoints(POLICY_COVERAGE, POLICY_RISK):
        assert _ink_near(joined, midpoint), "the default no longer joins its points"
        assert not _ink_near(points, midpoint), f"a line still runs through {midpoint}"
    # The measured points themselves are drawn: a marker at each of them.
    for point in zip(POLICY_COVERAGE, POLICY_RISK, strict=True):
        assert _ink_near(points, point, radius=1)


def test_connect_false_keeps_the_coordinates_and_their_order():
    fig = style.plot_risk_coverage(POLICY_COVERAGE, POLICY_RISK, connect=False, label="policies")
    (line,) = fig.axes[0].lines
    assert line.get_xdata().tolist() == POLICY_COVERAGE
    assert line.get_ydata().tolist() == POLICY_RISK
    assert line.get_linestyle() == "None"
    assert line.get_marker() not in (None, "None", "")
    assert [t.get_text() for t in fig.axes[0].get_legend().get_texts()] == ["policies"]


def test_the_default_still_joins_in_input_order_and_does_not_sort():
    fig = style.plot_risk_coverage(POLICY_COVERAGE, POLICY_RISK)
    (line,) = fig.axes[0].lines
    assert line.get_xdata().tolist() == POLICY_COVERAGE
    assert line.get_ydata().tolist() == POLICY_RISK
    assert line.get_linestyle() == "-"


def test_the_default_and_connect_true_are_the_same_figure():
    coverage, risk = [0.2, 0.6, 1.0], [0.0, 0.1, 0.2]
    plain = style.plot_risk_coverage(coverage, risk, label="m", reference_risk=0.2, title="t")
    explicit = style.plot_risk_coverage(
        coverage, risk, label="m", reference_risk=0.2, title="t", connect=True
    )
    assert _png(plain) == _png(explicit)


@dataclass
class _Curve:
    coverage: np.ndarray
    risk: np.ndarray


def test_connect_false_takes_a_selective_curve_object_too():
    curve = _Curve(np.array([0.25, 0.5, 1.0]), np.array([0.0, 0.1, 0.2]))
    fig = style.plot_risk_coverage(curve, connect=False)
    (line,) = fig.axes[0].lines
    assert line.get_linestyle() == "None"
    assert line.get_xdata().tolist() == [0.25, 0.5, 1.0]


def test_connect_false_draws_into_a_given_axes_and_keeps_the_reference_line():
    fig = Figure()
    ax = fig.subplots()
    out = style.plot_risk_coverage(
        POLICY_COVERAGE, POLICY_RISK, connect=False, reference_risk=0.3, ax=ax
    )
    assert out is fig
    assert ax.lines[0].get_linestyle() == "None"
    assert ax.lines[1].get_linestyle() == "--"
