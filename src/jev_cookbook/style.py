"""Notebook style: TypeSafe palette, matplotlib theme, run-mode header, chart helpers.

Notebooks use it like this::

    from jev_cookbook.style import apply_style, run_header, show_answer

    apply_style()
    run_header(7, "Triage support tickets", "synthetic")

Everything here is plain Python plus numpy and matplotlib. Importing the module changes no
global state (no rcParams, no colormap registration); call :func:`apply_style` for that.
The chart helpers build non-pyplot ``Figure`` objects, never call ``plt.show()``, and work
on the headless ``Agg`` backend. They apply the theme themselves, so they look the same
whether or not :func:`apply_style` was called.

Answers are read by duck typing, with the attribute names of the typed answers in the
TypeSafe SDK: a Choice has ``choice``, ``probabilities`` and ``confidence``; a Score has
``score``, ``probabilities``, ``confidence`` and ``legend``; a Noul has ``noul`` only.
Every answer also has a ``provenance``. This module imports no SDK and no other part of
``jev_cookbook``.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import matplotlib as mpl
import numpy as np
from cycler import cycler
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure

__all__ = [
    "CATEGORICAL",
    "INK",
    "MAGENTA",
    "PANEL",
    "PAPER",
    "PINK",
    "SEQUENTIAL",
    "SEQUENTIAL_CMAP",
    "SYNTHETIC_NOTICE",
    "RunInfo",
    "apply_style",
    "format_answer",
    "plot_answer_probabilities",
    "plot_confusion_matrix",
    "plot_risk_coverage",
    "plot_threshold_sweep",
    "rc_params",
    "run_header",
    "run_header_text",
    "show_answer",
    "style_context",
]

# --- palette -------------------------------------------------------------------------------

PINK = "#F386A1"
INK = "#1E1E1E"
MAGENTA = "#E551BA"
PANEL = "#DEDEDE"
PAPER = "#FEFEFE"

# Categorical order. Pink and ink come from the TypeSafe palette; blue and amber are added
# because pink and magenta alone collapse into one hue for protanopia. Magenta is reserved
# as the highlight colour (score line, chosen threshold) and is not in the cycle.
BLUE = "#1F78A8"
AMBER = "#E8A33D"
CATEGORICAL: tuple[str, ...] = (INK, PINK, BLUE, AMBER)

# Sequential ramp, light to dark, with strictly decreasing lightness (checked in tests).
SEQUENTIAL: tuple[str, ...] = ("#FBE3EA", PINK, "#B0287A", INK)
SEQUENTIAL_CMAP = LinearSegmentedColormap.from_list("jev_sequential", SEQUENTIAL)

_MARKERS = ("o", "s", "^", "D")


def rc_params() -> dict[str, Any]:
    """The matplotlib rcParams of the cookbook style, as a fresh dict.

    Figure and axes backgrounds are the opaque paper colour, and saving never makes them
    transparent, so a figure stays readable inside GitHub's dark notebook view.
    """
    return {
        "figure.facecolor": PAPER,
        "figure.edgecolor": PAPER,
        "figure.dpi": 100,
        "figure.figsize": (6.4, 4.0),
        "axes.facecolor": PAPER,
        "axes.edgecolor": INK,
        "axes.labelcolor": INK,
        "axes.titlecolor": INK,
        "axes.titlelocation": "left",
        "axes.titleweight": "bold",
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "axes.grid": True,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.prop_cycle": cycler(color=list(CATEGORICAL), marker=list(_MARKERS)),
        "grid.color": PANEL,
        "grid.linewidth": 0.8,
        "lines.linewidth": 2.0,
        "lines.markersize": 6,
        "text.color": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "legend.frameon": True,
        "legend.facecolor": PAPER,
        "legend.edgecolor": PANEL,
        "font.size": 10,
        "image.cmap": "jev_sequential",
        "savefig.facecolor": PAPER,
        "savefig.edgecolor": PAPER,
        "savefig.transparent": False,
        "savefig.bbox": "tight",
        "savefig.dpi": 100,
    }


def _register_cmap() -> None:
    if "jev_sequential" not in mpl.colormaps:
        mpl.colormaps.register(SEQUENTIAL_CMAP, name="jev_sequential")


def apply_style() -> None:
    """Apply the cookbook style to matplotlib globally (call once, near the top)."""
    _register_cmap()
    mpl.rcParams.update(rc_params())


@contextmanager
def style_context() -> Iterator[None]:
    """Apply the cookbook style only inside a ``with`` block."""
    _register_cmap()
    with mpl.rc_context(rc_params()):
        yield


def _new_figure(ax: Axes | None, figsize: tuple[float, float]) -> tuple[Figure, Axes]:
    """A themed, opaque, non-pyplot figure (or the figure that owns ``ax``)."""
    if ax is not None:
        fig = ax.figure
    else:
        with style_context():
            fig = Figure(figsize=figsize, layout="constrained")
            ax = fig.subplots()
    fig.patch.set_facecolor(PAPER)
    fig.patch.set_alpha(1.0)
    ax.set_facecolor(PAPER)
    return fig, ax


# --- run-mode header -----------------------------------------------------------------------

SYNTHETIC_NOTICE = (
    "Metrics in this run are checks that the pipeline works. They are not Jev results."
)

_MODES = ("synthetic", "scripted", "recorded", "live")


@dataclass(frozen=True)
class RunInfo:
    """The situation a notebook ran in.

    ``mode`` is one of ``synthetic`` (offline replay of synthetic fixtures), ``scripted``
    (offline scripted backend), ``recorded`` (offline replay of recorded fixtures; needs
    ``model`` and ``recorded_on``) or ``live`` (calls made now; needs ``model``).
    """

    mode: str
    model: str | None = None
    recorded_on: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(f"unknown run mode {self.mode!r}; expected one of {list(_MODES)}")
        if self.mode in ("synthetic", "scripted"):
            if self.model or self.recorded_on:
                raise ValueError(
                    f"a {self.mode} run was not produced by a model: "
                    "do not pass model or recorded_on"
                )
        elif self.mode == "recorded":
            if not self.model or not self.recorded_on:
                raise ValueError("a recorded run needs both model and recorded_on")
        else:
            if not self.model:
                raise ValueError("a live run needs model")
            if self.recorded_on:
                raise ValueError("a live run has no recorded_on")


def run_header_text(
    recipe: int | str,
    title: str,
    mode: str | RunInfo,
    *,
    model: str | None = None,
    recorded_on: str | None = None,
) -> str:
    """The header text :func:`run_header` prints (three lines, plain text)."""
    if isinstance(mode, RunInfo):
        if model or recorded_on:
            raise ValueError("pass model and recorded_on inside the RunInfo, not beside it")
        info = mode
    else:
        info = RunInfo(mode, model, recorded_on)
    number = f"{recipe:02d}" if isinstance(recipe, int) else str(recipe)
    first = f"Recipe {number}: {title}"
    if info.mode == "synthetic":
        second = "Mode: offline replay of synthetic fixtures"
        third = SYNTHETIC_NOTICE
    elif info.mode == "scripted":
        second = "Mode: offline, scripted backend"
        third = SYNTHETIC_NOTICE
    elif info.mode == "recorded":
        second = "Mode: offline replay of recorded fixtures"
        third = (
            f"The answers were captured from a real Jev call to model {info.model} "
            f"on {info.recorded_on}. Any numbers below describe only that recorded sample."
        )
    else:
        second = "Mode: live"
        third = f"Calls are being made now to model {info.model}."
    return "\n".join((first, second, third))


def run_header(
    recipe: int | str,
    title: str,
    mode: str | RunInfo,
    *,
    model: str | None = None,
    recorded_on: str | None = None,
) -> str:
    """Print the recipe number, title, run mode and what that mode means. Returns the text.

    ``mode`` is ``"synthetic"``, ``"scripted"``, ``"recorded"`` or ``"live"``, or a
    :class:`RunInfo`. Recorded runs need ``model`` and ``recorded_on``; live runs need
    ``model``. The text never states or implies quality, latency or cost.
    """
    text = run_header_text(recipe, title, mode, model=model, recorded_on=recorded_on)
    print(text)
    return text


# --- one typed answer ----------------------------------------------------------------------

_BAR_WIDTH = 20


def _bar(p: float) -> str:
    return "#" * round(max(0.0, min(1.0, float(p))) * _BAR_WIDTH)


def _provenance(answer: Any) -> str:
    value = getattr(answer, "provenance", None)
    if value is None:
        return "not stated"
    if isinstance(value, enum.Enum):
        value = value.value
    return str(value)


def _kind(answer: Any) -> str:
    for name in ("choice", "score", "noul"):
        if hasattr(answer, name):
            return name
    raise TypeError(
        f"cannot display {type(answer).__name__}: expected an answer with a "
        "'choice', 'score' or 'noul' attribute"
    )


def _level_label(answer: Any, level: Any) -> str:
    legend = dict(getattr(answer, "legend", None) or {})
    name = legend.get(level, legend.get(str(level), ""))
    return f"{level} {name}".strip()


def format_answer(answer: Any) -> str:
    """One typed answer as readable text (the string :func:`show_answer` prints)."""
    kind = _kind(answer)
    lines: list[str] = []
    if kind == "choice":
        lines.append(f"Choice: {answer.choice} (confidence {float(answer.confidence):.2f})")
        probs = dict(answer.probabilities)
        width = max((len(str(k)) for k in probs), default=0)
        for option, p in sorted(probs.items(), key=lambda kv: -float(kv[1])):
            lines.append(f"  {str(option):<{width}}  {float(p):.2f}  {_bar(p)}")
    elif kind == "score":
        score, conf = float(answer.score), float(answer.confidence)
        lines.append(f"Score: {score:.2f} (confidence {conf:.2f})")
        for level, p in dict(answer.probabilities).items():
            lines.append(f"  {_level_label(answer, level)}  {float(p):.2f}  {_bar(p)}")
    else:
        lines.append(f"Noul: {float(answer.noul):.2f} probability of yes (0 is no, 1 is yes)")
    lines.append(f"Provenance: {_provenance(answer)}")
    return "\n".join(lines)


def show_answer(answer: Any) -> str:
    """Print one typed answer readably and return the text. Shown before any aggregate."""
    text = format_answer(answer)
    print(text)
    return text


# --- charts --------------------------------------------------------------------------------


def _as_1d(values: Any, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError(f"{name} must be a non-empty 1-D sequence")
    return arr


def _shorten(text: str, width: int = 28) -> str:
    return text if len(text) <= width else text[: width - 3].rstrip() + "..."


def _luminance(rgb: Sequence[float]) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(float(c)) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def plot_confusion_matrix(
    counts: Any,
    labels: Sequence[str],
    *,
    normalize: bool = False,
    title: str | None = None,
    ax: Axes | None = None,
) -> Figure:
    """Confusion matrix. ``counts[i][j]`` is gold label i predicted as label j.

    ``normalize=True`` shows each row as a fraction of its gold label's total. Cells are
    annotated with the numbers, so colour is never the only carrier of the value. Returns
    the ``Figure`` (the one that owns ``ax`` when ``ax`` is given).
    """
    arr = np.asarray(counts, dtype=float)
    n = len(labels)
    if arr.shape != (n, n):
        raise ValueError(f"counts must be {n}x{n} to match labels, got shape {arr.shape}")
    shown = arr
    if normalize:
        totals = arr.sum(axis=1, keepdims=True)
        shown = np.divide(arr, totals, out=np.zeros_like(arr), where=totals > 0)
    side = max(4.0, 0.9 * n + 2.5)
    fig, ax = _new_figure(ax, (side, side))
    with style_context():
        vmax = float(shown.max()) if shown.max() > 0 else 1.0
        ax.imshow(shown, cmap=SEQUENTIAL_CMAP, vmin=0.0, vmax=vmax)
        ax.grid(False)
        names = [_shorten(str(x), 14) for x in labels]
        ax.set_xticks(range(n), labels=names)
        ax.set_yticks(range(n), labels=names)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Gold")
        for i in range(n):
            for j in range(n):
                value = shown[i, j]
                light = _luminance(SEQUENTIAL_CMAP(value / vmax)[:3]) > 0.35
                text = f"{value:.2f}" if normalize else f"{round(value)}"
                ax.text(j, i, text, ha="center", va="center", color=INK if light else PAPER)
        for spine in ax.spines.values():
            spine.set_visible(True)
        if title:
            ax.set_title(title)
    return fig


def plot_answer_probabilities(
    answer: Any,
    *,
    highlight: str | None = None,
    title: str | None = None,
    ax: Axes | None = None,
) -> Figure:
    """Probability bars for one answer.

    ``answer`` is a Choice (bars per option, the chosen option highlighted), a Score
    (bars per level in level order, with a line at the score), a Noul (a no bar and a yes
    bar), or a plain mapping from option to probability (pass ``highlight`` to mark one).
    """
    score: float | None = None
    chosen = highlight
    default_title: str | None = None
    if isinstance(answer, Mapping):
        probs = {str(k): float(v) for k, v in answer.items()}
    else:
        kind = _kind(answer)
        if kind == "choice":
            probs = {str(k): float(v) for k, v in answer.probabilities.items()}
            chosen = str(answer.choice) if highlight is None else highlight
            default_title = f"{answer.choice} (confidence {float(answer.confidence):.2f})"
        elif kind == "score":
            probs = {
                _shorten(_level_label(answer, level)): float(p)
                for level, p in answer.probabilities.items()
            }
            score = float(answer.score)
            default_title = f"Score {score:.2f} (confidence {float(answer.confidence):.2f})"
        else:
            p_yes = float(answer.noul)
            probs = {"no": 1.0 - p_yes, "yes": p_yes}
            default_title = f"Noul {p_yes:.2f} probability of yes"
    if not probs:
        raise ValueError("answer has no probabilities to plot")
    names = list(probs)
    values = [probs[k] for k in names]
    fig, ax = _new_figure(ax, (6.4, 0.45 * len(names) + 1.6))
    with style_context():
        colors = [PINK if (chosen is not None and k == chosen) else PANEL for k in names]
        ypos = np.arange(len(names))
        ax.barh(ypos, values, color=colors, edgecolor=INK, linewidth=1.0, height=0.65)
        ax.set_yticks(ypos, labels=names)
        ax.invert_yaxis()
        ax.set_xlim(0, 1.12)
        ax.set_xlabel("Probability")
        ax.grid(axis="y", visible=False)
        for y, v in zip(ypos, values, strict=True):
            ax.text(min(v, 1.0) + 0.015, y, f"{v:.2f}", va="center", color=INK)
        if score is not None:
            # Score 0 is the first level, drawn at y=0; the y axis is inverted.
            ax.axhline(score, color=MAGENTA, linestyle="--", linewidth=2.0, label="score")
            ax.legend(loc="lower right")
        heading = title if title is not None else default_title
        if heading:
            ax.set_title(heading)
    return fig


def plot_threshold_sweep(
    thresholds: Any,
    metrics: Mapping[str, Any],
    *,
    chosen: float | None = None,
    title: str | None = None,
    ax: Axes | None = None,
) -> Figure:
    """One line per metric against a decision threshold, with the chosen threshold marked.

    ``metrics`` maps a metric name to values aligned with ``thresholds``. Lines differ by
    colour and marker, so they can be told apart without colour.
    """
    x = _as_1d(thresholds, "thresholds")
    if not metrics:
        raise ValueError("metrics must not be empty")
    fig, ax = _new_figure(ax, (6.4, 4.0))
    with style_context():
        for name, values in metrics.items():
            y = _as_1d(values, f"metrics[{name!r}]")
            if y.shape != x.shape:
                raise ValueError(f"metrics[{name!r}] has {y.size} values, expected {x.size}")
            ax.plot(x, y, label=str(name), markevery=max(1, x.size // 10))
        if chosen is not None:
            ax.axvline(chosen, color=MAGENTA, linestyle="--", linewidth=2.0)
            ax.annotate(
                f"chosen: {chosen:g}",
                (chosen, 1.0),
                xycoords=("data", "axes fraction"),
                xytext=(4, -4),
                textcoords="offset points",
                va="top",
                color=INK,
            )
        ax.set_xlabel("Threshold")
        ax.set_ylabel("Metric value")
        ax.legend(loc="best")
        if title:
            ax.set_title(title)
    return fig


def plot_risk_coverage(
    coverage: Any,
    risk: Any,
    *,
    label: str | None = None,
    reference_risk: float | None = None,
    title: str | None = None,
    ax: Axes | None = None,
) -> Figure:
    """Risk and coverage curve: error rate on the answered cases against the fraction answered.

    ``coverage`` and ``risk`` are aligned 1-D arrays. ``reference_risk`` draws a dashed line,
    for example the error rate when every case is answered.
    """
    x = _as_1d(coverage, "coverage")
    y = _as_1d(risk, "risk")
    if x.shape != y.shape:
        raise ValueError(f"coverage has {x.size} values but risk has {y.size}")
    fig, ax = _new_figure(ax, (6.4, 4.0))
    with style_context():
        ax.plot(x, y, label=label)
        if reference_risk is not None and not math.isnan(reference_risk):
            ax.axhline(
                reference_risk,
                color=MAGENTA,
                linestyle="--",
                linewidth=2.0,
                label="reference risk",
            )
        ax.set_xlim(0, 1.0)
        ax.set_ylim(bottom=0)
        ax.set_xlabel("Coverage (fraction of cases answered)")
        ax.set_ylabel("Risk (error rate on answered cases)")
        if label or reference_risk is not None:
            ax.legend(loc="best")
        if title:
            ax.set_title(title)
    return fig
