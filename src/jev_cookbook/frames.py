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

import math
from collections.abc import Iterable, Mapping, Sequence
from numbers import Integral, Real
from typing import Any

__all__ = [
    "TIME_EPSILON",
    "frame_intervals",
    "frame_timestamps",
    "relative_frames",
    "sample_frames",
    "select_frames",
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
            best = cursor
            if cursor + 1 < len(eligible):
                before = abs(target - times[eligible[cursor]])
                after = abs(times[eligible[cursor + 1]] - target)
                if after < before - TIME_EPSILON:
                    best = cursor + 1
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
    """
    rows = list(state_frames)
    frame_timestamps(rows)
    picked: list[int] = []
    for value in indices:
        index = _index(value, "index", len(rows))
        if picked and index <= picked[-1]:
            raise ValueError("indices must be strictly increasing")
        picked.append(index)
    return [dict(rows[i]) for i in picked]


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
