"""Deterministic helpers for ordered, pre-extracted still frames.

Python owns frame order, sampling, timestamps and every piece of arithmetic here; nothing
calls a model and nothing decodes video. A *state frame* is the mapping that
:func:`jev_cookbook.vision.load_frames` returns: ``timestamp_seconds`` (elapsed seconds,
finite, nonnegative) and ``image`` (a reference), in strictly increasing time order. Every
function validates that and raises ``ValueError`` on empty input, a non-finite or negative
time, or a duplicate or out-of-order time, instead of repairing it.

Timestamps are compared with an absolute slack of :data:`TIME_EPSILON` (1e-9 seconds) so
float drift such as ``0.1 + 0.2`` against ``0.3`` cannot move a frame across a boundary.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping, Sequence
from numbers import Integral, Real
from typing import Any

__all__ = [
    "TIME_EPSILON",
    "earliest_transition",
    "frame_at",
    "frame_intervals",
    "frame_timestamps",
    "frame_windows",
    "relative_frames",
    "sample_frames",
    "select_frames",
    "transition_time",
    "window_timestamps",
]

TIME_EPSILON = 1e-9


def _seconds(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number of seconds")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number of seconds") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number of seconds")
    if number < 0 or (positive and number == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'non-negative'}")
    return number


def _ordered(times: Iterable[Any]) -> list[float]:
    result: list[float] = []
    for position, value in enumerate(times):
        seconds = _seconds(value, f"timestamp at position {position}")
        if result and seconds <= result[-1]:
            raise ValueError("frame timestamps must be strictly increasing")
        result.append(seconds)
    if not result:
        raise ValueError("frames must not be empty")
    return result


def frame_timestamps(state_frames: Iterable[Mapping[str, Any]]) -> list[float]:
    """The ``timestamp_seconds`` of each state frame, validated, in the given order."""
    times = []
    for position, frame in enumerate(state_frames):
        if not isinstance(frame, Mapping) or "timestamp_seconds" not in frame:
            raise ValueError(f"frame {position} must be a mapping with 'timestamp_seconds'")
        times.append(frame["timestamp_seconds"])
    return _ordered(times)


def _index(value: Any, name: str, size: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer index")
    if not 0 <= value < size:
        raise ValueError(f"{name} {value} is outside 0..{size - 1}")
    return int(value)


def sample_frames(
    timestamps: Iterable[float],
    *,
    every_seconds: float | None = None,
    count: int | None = None,
    start: float | None = None,
    end: float | None = None,
) -> list[int]:
    """Indices of the frames to keep, ascending and without repeats.

    ``timestamps`` are the strictly increasing frame times (use
    :func:`frame_timestamps` for state frames). ``start`` and ``end`` bound the *window*
    (inclusive, both default to the first and last timestamp); only frames inside it are
    eligible. At most one of ``every_seconds`` and ``count`` may be given; with neither,
    every frame in the window is selected. The window must contain a frame, otherwise
    ``ValueError`` is raised rather than returning nothing.

    ``every_seconds``: targets are ``window_start + k * every_seconds`` for ``k = 0, 1, ...``
    while the target is at most ``end`` (computed by multiplication, so error does not
    accumulate). Each target selects the eligible frame **nearest in time**; **a tie goes
    to the earlier frame**. A frame chosen by two targets is kept once, so a sparse
    sequence yields fewer indices than targets.

    ``count``: exactly ``count`` indices spread evenly by *position* across the eligible
    frames, always including the first and last eligible frame (``count == 1`` keeps only
    the first). Position ``i`` takes eligible frame ``round(i * (n - 1) / (count - 1))``
    where an exact half **rounds down to the earlier frame**, computed in integers. If
    ``count`` is at least the number of eligible frames, all of them are returned.

    Window edges and ties use a slack of :data:`TIME_EPSILON` seconds. Nothing is
    randomised and the result depends only on the arguments.
    """
    times = _ordered(timestamps)
    if every_seconds is not None and count is not None:
        raise ValueError("give at most one of every_seconds and count")
    low = _seconds(start, "start") if start is not None else times[0]
    high = _seconds(end, "end") if end is not None else times[-1]
    if low > high + TIME_EPSILON:
        raise ValueError("start must not be after end")
    eligible = [i for i, t in enumerate(times) if low - TIME_EPSILON <= t <= high + TIME_EPSILON]
    if not eligible:
        raise ValueError(f"no frame timestamp lies in [{low}, {high}]")

    if every_seconds is not None:
        step = _seconds(every_seconds, "every_seconds", positive=True)
        n_targets = math.floor((high - low) / step + TIME_EPSILON / step) + 1
        if n_targets > 10_000_000:
            raise ValueError("every_seconds yields more than 10,000,000 sampling targets")
        chosen: list[int] = []
        cursor = 0  # targets ascend, so the nearest frame never moves backwards
        for k in range(n_targets):
            target = low + k * step
            while (
                cursor + 1 < len(eligible) and times[eligible[cursor + 1]] <= target + TIME_EPSILON
            ):
                cursor += 1
            near = range(max(0, cursor - 1), min(len(eligible), cursor + 2))
            distances = {j: abs(times[eligible[j]] - target) for j in near}
            closest = min(distances.values())
            # the earliest frame within the slack of the closest one: the tie rule holds even
            # when frames lie closer together than TIME_EPSILON
            best = next(j for j in near if distances[j] <= closest + TIME_EPSILON)
            if not chosen or chosen[-1] != eligible[best]:
                chosen.append(eligible[best])
        return chosen

    if count is not None:
        if isinstance(count, bool) or not isinstance(count, Integral) or count <= 0:
            raise ValueError("count must be a positive integer")
        n = len(eligible)
        if count >= n:
            return eligible
        if count == 1:
            return [eligible[0]]
        span = int(count) - 1
        return [eligible[(2 * i * (n - 1) + span - 1) // (2 * span)] for i in range(count)]

    return eligible


def select_frames(
    state_frames: Sequence[Mapping[str, Any]], indices: Iterable[int]
) -> list[dict[str, Any]]:
    """Copies of the state frames at ``indices``, in the order given.

    Indices must be valid and strictly increasing, so the selection keeps the original
    chronological order. Typical use: ``select_frames(frames, sample_frames(...))``.
    Each copy gains ``frame_index``, its position in the list it was selected from, so the
    index space is never ambiguous afterwards; a row that already has ``frame_index`` keeps
    it, so selecting from a selection preserves the position in the original sequence.
    Indices you pass to :func:`window_timestamps` or :func:`earliest_transition` still refer
    to the list you pass with them.
    """
    rows = list(state_frames)
    frame_timestamps(rows)
    picked: list[int] = []
    for value in indices:
        index = _index(value, "index", len(rows))
        if picked and index <= picked[-1]:
            raise ValueError("indices must be strictly increasing")
        picked.append(index)
    result = []
    for i in picked:
        original = rows[i].get("frame_index", i)
        if isinstance(original, bool) or not isinstance(original, Integral) or original < 0:
            raise ValueError(f"frame_index of frame {i} must be a non-negative integer")
        result.append({**dict(rows[i]), "frame_index": int(original)})
    return result


def frame_intervals(state_frames: Iterable[Mapping[str, Any]]) -> list[float]:
    """Seconds between each frame and the next: ``n - 1`` positive floats.

    A single frame has no interval and returns ``[]``; no frames raise ``ValueError``.
    """
    times = frame_timestamps(state_frames)
    return [later - earlier for earlier, later in zip(times, times[1:], strict=False)]


def relative_frames(
    state_frames: Iterable[Mapping[str, Any]], now: float | None = None
) -> list[dict[str, Any]]:
    """Copies of the state frames with ``seconds_ago = now - timestamp_seconds`` added.

    Order and every other key are unchanged (``timestamp_seconds`` is kept; drop it from
    the state if the model should see only relative times). ``now`` defaults to the last
    frame's time, whose ``seconds_ago`` is then ``0.0``; it may not be earlier than the
    last frame. The input rows are not modified.
    """
    rows = list(state_frames)
    times = frame_timestamps(rows)
    reference = times[-1] if now is None else _seconds(now, "now")
    if reference < times[-1] - TIME_EPSILON:
        raise ValueError("now must not be earlier than the last frame")
    return [
        {**dict(row), "seconds_ago": max(0.0, reference - t)}
        for row, t in zip(rows, times, strict=True)
    ]


def window_timestamps(
    state_frames: Iterable[Mapping[str, Any]], first_index: int, last_index: int
) -> dict[str, float]:
    """Map the inclusive frame window ``first_index..last_index`` to seconds.

    Returns ``start_seconds``, ``end_seconds`` and ``duration_seconds`` (end minus start;
    ``0.0`` for a single-frame window). Indices are 0-based, non-negative and
    ``first_index <= last_index``; negative or out-of-range indices raise.
    """
    times = frame_timestamps(state_frames)
    first = _index(first_index, "first_index", len(times))
    last = _index(last_index, "last_index", len(times))
    if first > last:
        raise ValueError("first_index must not be after last_index")
    return {
        "start_seconds": times[first],
        "end_seconds": times[last],
        "duration_seconds": times[last] - times[first],
    }


def frame_at(timestamps: Iterable[float], seconds: float, *, side: str = "before") -> int:
    """Index of the frame at ``seconds`` (a log line, an agent-state record, a clicked time).

    ``side="before"`` is the last frame at or before ``seconds``; ``"after"`` the first frame
    at or after it; ``"nearest"`` the closer one, **a tie going to the earlier frame**. A frame
    within :data:`TIME_EPSILON` of ``seconds`` counts as at it. Raises ``ValueError`` when no
    frame qualifies (for example ``"before"`` a time earlier than the first frame) instead of
    guessing, because attaching an event to the wrong frame is a silent error.
    """
    times = _ordered(timestamps)
    when = _seconds(seconds, "seconds")
    if side not in ("before", "after", "nearest"):
        raise ValueError("side must be 'before', 'after' or 'nearest'")
    before = bisect.bisect_right(times, when + TIME_EPSILON) - 1  # -1 when none
    after = bisect.bisect_left(times, when - TIME_EPSILON)  # len(times) when none
    if side == "before":
        if before < 0:
            raise ValueError(f"no frame at or before {when} seconds")
        return before
    if side == "after":
        if after >= len(times):
            raise ValueError(f"no frame at or after {when} seconds")
        return after
    candidates = [i for i in (before, after) if 0 <= i < len(times)]
    gap = {i: abs(times[i] - when) for i in candidates}
    closest = min(gap.values())
    return min(i for i in candidates if gap[i] <= closest + TIME_EPSILON)


def frame_windows(
    timestamps: Iterable[float],
    *,
    width_seconds: float,
    stride_seconds: float,
    start: float | None = None,
    end: float | None = None,
) -> list[dict[str, Any]]:
    """Sliding windows over the sequence, each with the indices of the frames inside.

    Window ``k`` spans ``[w, w + width_seconds]`` (both edges inclusive, so a frame on the
    shared edge of neighbouring windows belongs to both) with ``w = start + k * stride_seconds``
    (multiplied, not accumulated). ``start`` / ``end`` default to the first and last
    timestamp. Only windows that fit entirely before ``end`` are produced; a window wider than
    the range raises ``ValueError``. When the last stride-spaced window stops short of ``end``,
    one **final window aligned to ``end``** (``[end - width, end]``, overlapping the previous
    window by more than the stride implies) is appended, so every frame lies in some window. A window that falls in a gap between frames is **kept**
    with ``indices == []`` so the caller decides explicitly what an empty window means. Each
    entry is ``{"window_start_seconds", "window_end_seconds", "indices"}``; pass its indices to
    :func:`select_frames` or :func:`window_timestamps` as needed.
    """
    times = _ordered(timestamps)
    width = _seconds(width_seconds, "width_seconds", positive=True)
    stride = _seconds(stride_seconds, "stride_seconds", positive=True)
    low = _seconds(start, "start") if start is not None else times[0]
    high = _seconds(end, "end") if end is not None else times[-1]
    if low > high + TIME_EPSILON:
        raise ValueError("start must not be after end")
    if width > high - low + TIME_EPSILON:
        raise ValueError("width_seconds is wider than the range being windowed")
    n_windows = math.floor((high - low - width) / stride + TIME_EPSILON / stride) + 1
    if n_windows > 10_000_000:
        raise ValueError("stride_seconds yields more than 10,000,000 windows")
    starts = [low + k * stride for k in range(n_windows)]
    if high - (starts[-1] + width) > TIME_EPSILON:
        starts.append(high - width)  # final window aligned to the end: no frame is left out
    result = []
    for first in starts:
        last = first + width
        lo = bisect.bisect_left(times, first - TIME_EPSILON)
        hi = bisect.bisect_right(times, last + TIME_EPSILON)
        result.append(
            {
                "window_start_seconds": first,
                "window_end_seconds": last,
                "indices": list(range(lo, hi)),
            }
        )
    return result


def transition_time(state_frames: Iterable[Mapping[str, Any]], first_new_index: int) -> float:
    """The cookbook's one convention for *when a transition happened*, in elapsed seconds.

    A transition's time is the ``timestamp_seconds`` of the **first frame in which the new
    state is visible**. ``first_new_index`` must be at least 1: a transition needs an earlier
    frame that still showed the old state. Gold labels follow the same rule (a labeller marks
    the first frame of the full-rate sequence that shows the new state); a prediction is
    measured on the frames Python sampled. A *correct* detection on sampled frames can
    therefore only be late, by less than the gap to the previous sampled frame; see
    :func:`earliest_transition` and ``evaluation.transition_metrics``.
    """
    times = frame_timestamps(state_frames)
    index = _index(first_new_index, "first_new_index", len(times))
    if index == 0:
        raise ValueError(
            "first_new_index must be at least 1: a transition needs an earlier frame showing "
            "the old state"
        )
    return times[index]


def earliest_transition(
    state_frames: Iterable[Mapping[str, Any]], changed: Iterable[bool | None]
) -> dict[str, Any] | None:
    """Earliest adjacent pair flagged as a change, an explicit review, or ``None``.

    ``changed[i]`` answers "did the state change between frame ``i`` and frame ``i + 1``?"
    (one Python-controlled question per adjacent pair; ``len(changed) == n - 1``). Values are
    ``True``, ``False`` (NumPy booleans are accepted) or ``None`` for a pair left
    **undetermined** (a Noul that was uncertain, or a low-confidence answer sent to review).
    Never coerce an undetermined pair to ``False``: that would report a later transition as the
    earliest one.

    - If the first non-``False`` pair is ``True``, the result applies :func:`transition_time`'s
      convention: ``{"review": False, "first_new_index": i + 1, "transition_seconds": ...,
      "window_start_seconds": ..., "window_end_seconds": ...}``.
    - If an undetermined pair comes first (before any ``True``, or with no ``True`` at all),
      the earliest transition is not established and the result is
      ``{"review": True, "first_undetermined_index": i, "window_start_seconds": ...,
      "window_end_seconds": ...}`` with no time. Score it by predicting one of
      ``transition_metrics``'s ``uncertain_labels`` for that example.
    - If every pair is ``False`` the result is ``None``, a recipe outcome (usually
      "unchanged"), not an error.

    The indices refer to the list passed here (so pass the *sampled* frames, and use their
    ``frame_index`` to get back to the original positions).
    """
    times = frame_timestamps(state_frames)
    flags = list(changed)
    if len(flags) != len(times) - 1:
        raise ValueError(f"changed needs one flag per adjacent pair ({len(times) - 1})")
    values: list[bool | None] = []
    for flag in flags:
        if flag is None:
            values.append(None)
        elif isinstance(flag, bool) or getattr(getattr(flag, "dtype", None), "kind", "") == "b":
            values.append(bool(flag))
        else:
            raise ValueError("changed must contain only True, False or None")
    for i, flag in enumerate(values):
        if flag is None:
            return {
                "review": True,
                "first_undetermined_index": i,
                "window_start_seconds": times[i],
                "window_end_seconds": times[i + 1],
            }
        if flag:
            return {
                "review": False,
                "first_new_index": i + 1,
                "transition_seconds": times[i + 1],
                "window_start_seconds": times[i],
                "window_end_seconds": times[i + 1],
            }
    return None
