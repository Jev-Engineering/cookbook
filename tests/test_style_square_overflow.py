"""Square confusion matrices retain whole labels inside their owned figure (#495).

These are Agg-rendered synthetic cases, not notebook freshness or model-quality evidence.
The no-growth control proves that the same boundary assertion detects the original defect.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from jev_cookbook import style

from .test_style_rendering import (
    assert_no_overlapping_text,
    assert_ticks_faithful,
    full_canvas_png,
    tick_texts,
)

LONG_LABELS = [f"pre_{'x' * 60}_{i}" for i in range(2)]
SHORT_LABELS = ["a", "b"]
COUNTS = np.array([[7, 2], [1, 8]])
INITIAL_SIDE = 4.3


def _square(rows, cols, *, normalize=False):
    return style.plot_confusion_matrix(
        COUNTS,
        row_labels=rows,
        col_labels=cols,
        row_axis_title="Gold content",
        col_axis_title="Final action",
        normalize=normalize,
        title="Synthetic square matrix",
    )


def _assert_readable(fig, rows, cols):
    FigureCanvasAgg(fig)
    assert_no_overlapping_text(fig)
    ax = fig.axes[0]
    assert_ticks_faithful(tick_texts(ax.yaxis), rows, exact=True)
    assert_ticks_faithful(tick_texts(ax.xaxis), cols, exact=True)
    assert (ax.get_ylabel(), ax.get_xlabel()) == ("Gold content", "Final action")
    dimensions = np.asarray(fig.get_size_inches())
    assert np.all(np.isfinite(dimensions))
    # A finite fixture needs enough space for its labels, not an unbounded page.
    assert np.all((dimensions >= INITIAL_SIDE) & (dimensions < 32))


@pytest.mark.parametrize("normalize", [False, True], ids=["counts", "fractions"])
@pytest.mark.parametrize(
    ("rows", "cols", "growing_axis"),
    [(LONG_LABELS, SHORT_LABELS, 0), (SHORT_LABELS, LONG_LABELS, 1)],
    ids=["whole-row-labels", "whole-column-labels"],
)
def test_square_whole_labels_fit_without_layout_warnings(rows, cols, growing_axis, normalize):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fig = _square(rows, cols, normalize=normalize)
        _assert_readable(fig, rows, cols)
    assert fig.get_size_inches()[growing_axis] > INITIAL_SIDE


def test_square_shared_vocabulary_fits_with_whole_labels_on_both_axes():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fig = style.plot_confusion_matrix(COUNTS, LONG_LABELS)
        FigureCanvasAgg(fig)
        assert_no_overlapping_text(fig)
    ax = fig.axes[0]
    assert_ticks_faithful(tick_texts(ax.xaxis), LONG_LABELS, exact=True)
    assert_ticks_faithful(tick_texts(ax.yaxis), LONG_LABELS, exact=True)
    assert np.all(np.isfinite(fig.get_size_inches()))
    assert np.all(fig.get_size_inches() > INITIAL_SIDE)
    assert np.all(fig.get_size_inches() < 32)


@pytest.mark.parametrize(
    ("rows", "cols"),
    [(LONG_LABELS, SHORT_LABELS), (SHORT_LABELS, LONG_LABELS)],
    ids=["whole-row-labels", "whole-column-labels"],
)
def test_disabling_growth_reddens_the_square_boundary_assertion(monkeypatch, rows, cols):
    monkeypatch.setattr(style, "_grow_to_fit_text", lambda *args: None)
    fig = _square(rows, cols)
    assert fig.get_size_inches() == pytest.approx([INITIAL_SIDE, INITIAL_SIDE])
    # Only this deliberately defective control may draw a collapsed intermediate layout.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="constrained_layout not applied", category=UserWarning
        )
        with pytest.raises(AssertionError, match="cut off by the figure edge"):
            assert_no_overlapping_text(fig)


def test_supplied_axes_retain_their_figure_size_and_owner(monkeypatch):
    fig = Figure(figsize=(18, 18), layout="constrained")
    ax = fig.subplots()
    original_size = fig.get_size_inches().copy()

    def unexpected_growth(*_args):
        pytest.fail("a caller-owned figure must not enter automatic growth")

    monkeypatch.setattr(style, "_grow_to_fit_text", unexpected_growth)
    returned = style.plot_confusion_matrix(
        COUNTS, row_labels=LONG_LABELS, col_labels=SHORT_LABELS, ax=ax
    )
    assert returned is fig
    assert returned.axes == [ax]
    assert fig.get_size_inches() == pytest.approx(original_size)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert_no_overlapping_text(fig)
    assert_ticks_faithful(tick_texts(ax.yaxis), LONG_LABELS, exact=True)
    assert_ticks_faithful(tick_texts(ax.xaxis), SHORT_LABELS, exact=True)


@pytest.mark.parametrize("normalize", [False, True], ids=["counts", "fractions"])
def test_short_square_keeps_its_size_and_png_when_growth_is_unneeded(monkeypatch, normalize):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        actual = _square(SHORT_LABELS, SHORT_LABELS, normalize=normalize)
        actual_png = full_canvas_png(actual)
        with monkeypatch.context() as control:
            control.setattr(style, "_grow_to_fit_text", lambda *args: None)
            unchanged = _square(SHORT_LABELS, SHORT_LABELS, normalize=normalize)
            unchanged_png = full_canvas_png(unchanged)
    assert actual.get_size_inches() == pytest.approx([INITIAL_SIDE, INITIAL_SIDE])
    assert actual.get_size_inches() == pytest.approx(unchanged.get_size_inches())
    assert actual_png == unchanged_png
    _assert_readable(actual, SHORT_LABELS, SHORT_LABELS)
