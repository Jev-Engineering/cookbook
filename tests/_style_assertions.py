"""Shared rendered-figure assertions for the cookbook style tests.

The caller loads this module by path because tests is not a Python package.
"""

from __future__ import annotations

import io

import matplotlib as mpl
import numpy as np
from matplotlib.axis import Axis
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.legend import Legend
from matplotlib.text import Text


def _draw(fig: Figure) -> None:
    """Lay the figure out and draw it on the Agg canvas (what a saved PNG would see)."""
    FigureCanvasAgg(fig)
    fig.canvas.draw()


def full_canvas_png(fig: Figure) -> bytes:
    """Save the entire canvas at the normal save DPI, preserving padding and RGBA pixels.

    The notebook exporter uses a tight crop. Equality of those exports can hide a difference
    in canvas size or padding, so these regression assertions require a separate full export.
    """
    buffer = io.BytesIO()
    FigureCanvasAgg(fig)
    with mpl.rc_context({"savefig.bbox": None}):
        fig.savefig(buffer, format="png")
    return buffer.getvalue()


def assert_same_full_canvas(a: Figure, b: Figure) -> None:
    """The saved figures agree byte for byte, including the complete canvas and alpha."""
    assert full_canvas_png(a) == full_canvas_png(b), "full-canvas PNGs differ"


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
