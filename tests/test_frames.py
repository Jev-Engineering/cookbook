"""Ordered-frame helpers: every expectation below is worked out by hand in a comment."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import numpy as np
import pytest

from jev_cookbook import frames
from jev_cookbook.evaluation import transition_metrics
from jev_cookbook.fixtures import validate_recipe
from jev_cookbook.frames import (
    earliest_transition,
    frame_at,
    frame_intervals,
    frame_timestamps,
    frame_windows,
    relative_frames,
    sample_frames,
    select_frames,
    transition_time,
    window_timestamps,
)


def rows(*times):
    return [{"timestamp_seconds": t, "image": f"image:sha256:{i}"} for i, t in enumerate(times)]


SIX = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


def test_public_names():
    assert set(frames.__all__) == {
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
    }


# ------------------------------------------------------------------------------ sample_frames


def test_no_rule_keeps_every_frame_in_the_window():
    assert sample_frames(SIX) == [0, 1, 2, 3, 4, 5]
    assert sample_frames(SIX, start=1.0, end=3.0) == [1, 2, 3]


def test_every_seconds_on_the_grid():
    # targets 0, 2, 4 land exactly on frames 0, 2, 4
    assert sample_frames(SIX, every_seconds=2) == [0, 2, 4]


def test_every_seconds_tie_goes_to_the_earlier_frame():
    # targets 0, 2.5, 5; 2.5 is 0.5 from both frame 2 and frame 3 -> frame 2
    assert sample_frames(SIX, every_seconds=2.5) == [0, 2, 5]


def test_every_seconds_nearest_not_floor():
    # targets 0, .5, 1; .5 is .1 from 0.4 and .5 from 1.0 -> index 1
    assert sample_frames([0.0, 0.4, 1.0], every_seconds=0.5) == [0, 1, 2]


def test_every_seconds_deduplicates_sparse_frames():
    # frames 0 and 4; targets 0,1,2,3,4: 1 -> 0, 2 is a tie -> 0, 3 -> 4, 4 -> 4
    assert sample_frames([0.0, 4.0], every_seconds=1) == [0, 1]


def test_every_seconds_with_start_and_end():
    # window [1.5, 5]: eligible frames 2..5; targets 1.5, 2.5, 3.5, 4.5 -> 2, (tie) 2, 3, 4
    assert sample_frames(SIX, every_seconds=1, start=1.5) == [2, 3, 4]
    # window [0, 3]: targets 0,1,2,3
    assert sample_frames(SIX, every_seconds=1, end=3) == [0, 1, 2, 3]


def test_every_seconds_float_drift_does_not_lose_the_last_target():
    tenths = [i / 10 for i in range(11)]  # 0.0 .. 1.0
    # 0.3 * 3 == 0.8999999999999999 and 0.1 * 3 == 0.30000000000000004; both stay on frames
    assert sample_frames(tenths, every_seconds=0.3) == [0, 3, 6, 9]
    assert sample_frames([0.0, 0.1, 0.2, 0.3], every_seconds=0.1) == [0, 1, 2, 3]
    # 1/3 is not representable: targets 0, 1/3, 2/3, 1 over frames 0, .5, 1 -> 0, 1, (1), 2
    assert sample_frames([0.0, 0.5, 1.0], every_seconds=1 / 3) == [0, 1, 2]


def test_boundaries_are_inclusive_within_float_slack():
    assert sample_frames(SIX, end=3.0 - 1e-10) == [0, 1, 2, 3]
    assert sample_frames(SIX, start=2.0 + 1e-10, end=4.0) == [2, 3, 4]
    assert sample_frames(SIX, start=2.0 + 1e-6, end=4.0) == [3, 4]
    assert sample_frames(SIX, start=3.0, end=3.0) == [3]


def test_a_drifted_timestamp_samples_like_its_exact_value():
    # 0.1 + 0.2 = 0.30000000000000004; targets 0, 0.3, 0.6 pick frames 0, 1, 2
    times = [0.0, 0.1 + 0.2, 0.6]
    assert sample_frames(times, every_seconds=0.3) == [0, 1, 2]


def test_count_spreads_by_position_including_both_ends():
    # n = 6: count 3 -> positions 0, 2.5 (half rounds down to 2), 5
    assert sample_frames(SIX, count=3) == [0, 2, 5]
    # count 4 -> 0, 5/3 -> 2, 10/3 -> 3, 5
    assert sample_frames(SIX, count=4) == [0, 2, 3, 5]
    assert sample_frames(SIX, count=2) == [0, 5]
    assert sample_frames(SIX, count=1) == [0]


def test_count_at_least_the_frames_returns_all_without_repeats():
    assert sample_frames(SIX, count=6) == [0, 1, 2, 3, 4, 5]
    assert sample_frames(SIX, count=99) == [0, 1, 2, 3, 4, 5]


@pytest.mark.parametrize("n", range(1, 30))
def test_count_returns_exactly_count_distinct_ascending_indices(n):
    times = [float(i) ** 1.5 for i in range(n)]
    for count in range(1, n + 1):
        picked = sample_frames(times, count=count)
        assert len(picked) == count
        assert picked == sorted(set(picked))
        assert picked[0] == 0
        assert count == 1 or picked[-1] == n - 1


def test_count_within_a_window_indexes_the_eligible_frames():
    # window 1..4 holds frames 1,2,3,4; count 3 -> positions 0, 1.5 (down -> 1), 3
    assert sample_frames(SIX, count=3, start=1, end=4) == [1, 2, 4]


def test_single_frame():
    assert sample_frames([2.5]) == [0]
    assert sample_frames([2.5], every_seconds=1) == [0]
    assert sample_frames([2.5], count=4) == [0]
    assert sample_frames([2.5], start=2.5, end=2.5, count=1) == [0]


def test_numpy_numbers_and_generators_are_accepted():
    assert sample_frames((t for t in np.array(SIX)), every_seconds=np.float64(2)) == [0, 2, 4]
    assert sample_frames(SIX, count=np.int64(2)) == [0, 5]


@pytest.mark.parametrize(
    "times",
    [[], [1.0, 1.0], [2.0, 1.0], [0.0, 2.0, 1.0], [-1.0, 0.0], [0.0, math.nan], [0.0, math.inf]],
)
def test_bad_timestamps_raise(times):
    with pytest.raises(ValueError):
        sample_frames(times)


def test_duplicate_and_unsorted_timestamps_say_so():
    with pytest.raises(ValueError, match="strictly increasing"):
        sample_frames([0.0, 1.0, 1.0])
    with pytest.raises(ValueError, match="strictly increasing"):
        sample_frames([3.0, 1.0, 2.0])
    with pytest.raises(ValueError, match="empty"):
        sample_frames([])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"every_seconds": 0},
        {"every_seconds": -1},
        {"every_seconds": math.nan},
        {"every_seconds": math.inf},
        {"every_seconds": True},
        {"every_seconds": "1"},
        {"count": 0},
        {"count": -2},
        {"count": 2.5},
        {"count": 2.0},
        {"count": True},
        {"every_seconds": 1, "count": 2},
        {"start": -1},
        {"start": math.nan},
        {"end": math.inf},
        {"start": 4, "end": 3},
        {"start": 10},
        {"end": -0.5},
        {"every_seconds": 1e-12},
    ],
)
def test_bad_arguments_raise(kwargs):
    with pytest.raises(ValueError):
        sample_frames(SIX, **kwargs)


def test_window_without_a_frame_raises_instead_of_returning_nothing():
    with pytest.raises(ValueError, match="no frame"):
        sample_frames(SIX, start=1.2, end=1.8)


def test_sampling_is_deterministic_and_independent_of_the_input_container():
    first = sample_frames(SIX, every_seconds=1.5)
    assert first == sample_frames(tuple(SIX), every_seconds=1.5)
    assert first == sample_frames(iter(SIX), every_seconds=1.5)
    # targets 0, 1.5 (tie 1,2 -> 1), 3, 4.5 (tie 4,5 -> 4)
    assert first == [0, 1, 3, 4]


# ------------------------------------------------------------------------------ the rest


def test_frame_timestamps_and_validation():
    assert frame_timestamps(rows(0, 0.5, 2)) == [0.0, 0.5, 2.0]
    for bad in ([], rows(1, 1), rows(2, 1), [{"image": "x"}], [1.0], rows(-1, 2)):
        with pytest.raises(ValueError):
            frame_timestamps(bad)


def test_frame_intervals():
    assert frame_intervals(rows(0, 0.75, 1.5, 4.0)) == [0.75, 0.75, 2.5]
    assert frame_intervals(rows(3.0)) == []
    with pytest.raises(ValueError):
        frame_intervals([])
    with pytest.raises(ValueError, match="strictly increasing"):
        frame_intervals(rows(0, 1, 1))


def test_relative_frames_default_now_is_the_last_frame():
    original = rows(0, 2, 5)
    out = relative_frames(original)
    assert [r["seconds_ago"] for r in out] == [5.0, 3.0, 0.0]
    assert [r["image"] for r in out] == ["image:sha256:0", "image:sha256:1", "image:sha256:2"]
    assert [r["timestamp_seconds"] for r in out] == [0.0, 2.0, 5.0]
    assert all("seconds_ago" not in r for r in original)  # input untouched
    assert out[0] is not original[0]


def test_relative_frames_explicit_now():
    out = relative_frames(rows(1.0, 2.5), now=4.0)
    assert [r["seconds_ago"] for r in out] == [3.0, 1.5]
    assert relative_frames(rows(1.0, 2.5), now=2.5)[-1]["seconds_ago"] == 0.0
    assert relative_frames(rows(1.0, 2.5), now=2.5 - 1e-10)[-1]["seconds_ago"] == 0.0


def test_relative_frames_single_and_errors():
    assert relative_frames(rows(7.0))[0]["seconds_ago"] == 0.0
    for kwargs in ({"now": 2.0}, {"now": math.nan}, {"now": -1}, {"now": True}):
        with pytest.raises(ValueError):
            relative_frames(rows(1.0, 3.0), **kwargs)
    with pytest.raises(ValueError):
        relative_frames([])
    with pytest.raises(ValueError):
        relative_frames(rows(2, 1))


def test_window_timestamps():
    state = rows(0, 0.75, 1.5, 4.0)
    assert window_timestamps(state, 1, 3) == {
        "start_seconds": 0.75,
        "end_seconds": 4.0,
        "duration_seconds": 3.25,
    }
    assert window_timestamps(state, 2, 2) == {
        "start_seconds": 1.5,
        "end_seconds": 1.5,
        "duration_seconds": 0.0,
    }
    assert window_timestamps(state, np.int64(0), 3)["duration_seconds"] == 4.0


@pytest.mark.parametrize("first,last", [(-1, 2), (0, 4), (2, 1), (0.0, 1), (True, 1), (0, "1")])
def test_window_timestamps_rejects_bad_indices(first, last):
    with pytest.raises(ValueError):
        window_timestamps(rows(0, 1, 2, 3), first, last)


def test_window_timestamps_empty_and_unordered():
    with pytest.raises(ValueError):
        window_timestamps([], 0, 0)
    with pytest.raises(ValueError):
        window_timestamps(rows(1, 0), 0, 1)


def test_select_frames_pairs_with_sample_frames():
    state = rows(*SIX)
    chosen = select_frames(state, sample_frames(frame_timestamps(state), every_seconds=2))
    assert [r["timestamp_seconds"] for r in chosen] == [0.0, 2.0, 4.0]
    assert chosen[0] == {**state[0], "frame_index": 0}
    assert chosen[0] is not state[0]
    assert select_frames(state, []) == []
    for bad in ([6], [-1], [2, 1], [1, 1], [True], [1.0]):
        with pytest.raises(ValueError):
            select_frames(state, bad)
    with pytest.raises(ValueError):
        select_frames([], [])


# ------------------------------------------------------------------------------ round 2


def test_tie_rule_holds_when_frames_are_closer_than_the_slack():
    # frame 1 is exactly on the target, frame 2 is 5e-10 s later: still the earlier frame
    assert sample_frames([0.0, 1.0, 1.0 + 5e-10, 2.0], every_seconds=1) == [0, 1, 3]
    # the earlier frame sits just before the target and the later one just after
    assert sample_frames([0.0, 1.0 - 5e-10, 1.0 + 5e-10, 2.0], every_seconds=1) == [0, 1, 3]


@pytest.mark.parametrize(
    ("times", "expected"),
    [
        # three frames: index 1 is exactly on the target (1.0), indices 2 and 3 are just after it
        ([0.0, 1.0, 1.0 + 3e-10, 1.0 + 6e-10, 2.0], [0, 1, 4]),
        # three frames around the target: the earliest of the tied frames wins
        ([0.0, 1.0 - 4e-10, 1.0, 1.0 + 4e-10, 2.0], [0, 1, 4]),
        # three frames, all after the target; the first of them is the closest
        ([0.0, 1.0 + 1e-10, 1.0 + 2e-10, 1.0 + 3e-10, 2.0], [0, 1, 4]),
        # four frames after the target
        ([0.0, 1.0, 1.0 + 2e-10, 1.0 + 4e-10, 1.0 + 6e-10, 2.0], [0, 1, 5]),
        # three frames up to the target: index 3 is exactly on it, indices 1 and 2 are just before
        # it, so the earliest tied frame is two frames before the closest one
        ([0.0, 1.0 - 6e-10, 1.0 - 3e-10, 1.0, 2.0], [0, 1, 4]),
        # the closest frame is index 2 (1e-10 after the target); index 1 is 5e-10 before it, so
        # its distance is within 1e-9 of the smallest one and the two are tied
        ([0.0, 1.0 - 5e-10, 1.0 + 1e-10, 1.0 + 2e-10, 2.0], [0, 1, 4]),
        # index 1 is 3e-9 before the target, outside the slack of the closest frame (index 2,
        # exactly on the target), so it is not tied
        ([0.0, 1.0 - 3e-9, 1.0, 1.0 + 3e-10, 2.0], [0, 2, 4]),
    ],
)
def test_every_seconds_picks_the_earliest_frame_within_the_slack_of_the_closest(times, expected):
    assert sample_frames(times, every_seconds=1) == expected


def test_a_cluster_inside_the_window_edge_slack_is_tied_too():
    # index 1 is 3e-10 before start=1.0, inside the window's own slack, so it is eligible and
    # tied with index 2 (exactly on the target) and index 3: the earliest of the three wins
    times = [0.0, 1.0 - 3e-10, 1.0, 1.0 + 3e-10, 2.0]
    assert sample_frames(times, every_seconds=1, start=1.0) == [1, 4]


def _nearest_by_the_rule(times, every_seconds):
    """The documented rule written out literally, with no cursor and no shortcut.

    For each target, the earliest frame whose distance is within TIME_EPSILON of the smallest
    distance; a frame chosen by two targets is kept once.
    """
    n_targets = math.floor(
        (times[-1] - times[0]) / every_seconds + frames.TIME_EPSILON / every_seconds
    )
    chosen = []
    for k in range(n_targets + 1):
        target = times[0] + k * every_seconds
        distance = [abs(t - target) for t in times]
        smallest = min(distance)
        best = next(i for i, d in enumerate(distance) if d <= smallest + frames.TIME_EPSILON)
        if not chosen or chosen[-1] != best:
            chosen.append(best)
    return chosen


def test_every_seconds_matches_the_rule_written_out_literally_including_clusters():
    rng = random.Random(340)
    gaps = [1e-10, 2e-10, 3e-10, 5e-10, 9e-10, 0.1, 0.25, 0.5, 1.0]
    for _ in range(2000):
        times, now = [], 0.0
        for _ in range(rng.randint(1, 12)):
            now += rng.choice(gaps)
            times.append(now)
        every = rng.choice([0.1, 0.25, 0.3, 0.5, 1.0])
        got = sample_frames(times, every_seconds=every)
        assert got == _nearest_by_the_rule(times, every), (times, every)


def test_count_spreading_is_by_position_not_by_time():
    # the 9.7 s gap is not sampled evenly: positions 0, 2, 4 keep 0.0, 0.2 and 10.0
    assert sample_frames([0.0, 0.1, 0.2, 0.3, 10.0], count=3) == [0, 2, 4]


def test_select_frames_records_the_original_index():
    state = rows(*SIX)
    first = select_frames(state, [1, 3, 5])
    assert [r["frame_index"] for r in first] == [1, 3, 5]
    assert "frame_index" not in state[1]
    second = select_frames(first, [0, 2])
    assert [r["frame_index"] for r in second] == [1, 5]  # still the original positions
    assert [r["timestamp_seconds"] for r in second] == [1.0, 5.0]


def test_frame_at():
    times = [0.0, 1.0, 2.0, 4.0]
    assert frame_at(times, 2.0) == 2
    assert frame_at(times, 3.0) == 2
    assert frame_at(times, 3.0, side="after") == 3
    assert frame_at(times, 2.0, side="after") == 2
    assert frame_at(times, 1.5, side="nearest") == 1  # tie goes to the earlier frame
    assert frame_at(times, 3.1, side="nearest") == 3
    assert frame_at(times, 100.0, side="nearest") == 3
    assert frame_at(times, 100.0) == 3
    assert frame_at(times, 2.0 - 1e-10, side="after") == 2
    assert frame_at(times, 2.0 + 1e-10) == 2
    assert frame_at([5.0], 0.0, side="nearest") == 0
    with pytest.raises(ValueError, match="at or before"):
        frame_at([1.0, 2.0], 0.5)
    with pytest.raises(ValueError, match="at or after"):
        frame_at([1.0, 2.0], 2.5, side="after")
    for bad in ({"side": "left"}, {"side": None}):
        with pytest.raises(ValueError):
            frame_at(times, 1.0, **bad)
    for bad_time in (-1.0, math.nan, True):
        with pytest.raises(ValueError):
            frame_at(times, bad_time)
    with pytest.raises(ValueError):
        frame_at([], 1.0)


def test_frame_windows_keeps_empty_windows_visible():
    times = [0.0, 0.5, 1.0, 1.5, 2.0, 6.0, 6.5, 7.0, 7.5, 8.0]
    windows = frame_windows(times, width_seconds=2.0, stride_seconds=2.0)
    # windows start at 0, 2, 4, 6 and span [0,2], [2,4], [4,6], [6,8]
    assert [(w["window_start_seconds"], w["window_end_seconds"]) for w in windows] == [
        (0.0, 2.0),
        (2.0, 4.0),
        (4.0, 6.0),
        (6.0, 8.0),
    ]
    assert [w["indices"] for w in windows] == [
        [0, 1, 2, 3, 4],
        [4],  # shared edge frame at 2.0
        [5],  # shared edge frame at 6.0
        [5, 6, 7, 8, 9],
    ]
    gap = frame_windows(times, width_seconds=1.0, stride_seconds=1.0, start=3.0, end=5.0)
    assert [w["indices"] for w in gap] == [[], []]
    assert frame_windows([0.0, 1.0], width_seconds=1.0, stride_seconds=5.0)[0]["indices"] == [0, 1]


def test_frame_windows_float_drift_and_errors():
    times = [i / 10 for i in range(11)]
    # width 0.3, stride 0.1: windows at 0.0 .. 0.7 -> 8 windows despite 0.1 * 7 drifting
    windows = frame_windows(times, width_seconds=0.3, stride_seconds=0.1)
    assert len(windows) == 8
    assert windows[7]["indices"] == [7, 8, 9, 10]
    assert frame_windows([2.5], width_seconds=1e-12, stride_seconds=1.0)[0]["indices"] == [0]
    for kwargs in (
        {"width_seconds": 2.0, "stride_seconds": 1.0},  # wider than the 1.0 s range
        {"width_seconds": 0, "stride_seconds": 1.0},
        {"width_seconds": 1.0, "stride_seconds": 0},
        {"width_seconds": 1.0, "stride_seconds": math.nan},
        {"width_seconds": 1.0, "stride_seconds": True},
        {"width_seconds": 0.5, "stride_seconds": 1e-9},
        {"width_seconds": 0.5, "stride_seconds": 1.0, "start": 2.0, "end": 1.0},
    ):
        with pytest.raises(ValueError):
            frame_windows([0.0, 1.0], **kwargs)
    with pytest.raises(ValueError):
        frame_windows([], width_seconds=1.0, stride_seconds=1.0)


def test_transition_time_is_the_first_frame_showing_the_new_state():
    state = rows(0.0, 0.5, 1.0, 1.5)
    assert transition_time(state, 2) == 1.0
    assert transition_time(state, 3) == 1.5
    for bad in (0, -1, 4, True, 1.0):
        with pytest.raises(ValueError):
            transition_time(state, bad)
    with pytest.raises(ValueError):
        transition_time([], 1)


def test_earliest_transition_from_per_pair_flags():
    state = rows(0.0, 1.0, 2.5, 4.0)
    found = earliest_transition(state, [False, True, True])
    # pair (1, 2) is the first flagged: the new state is first visible in frame 2, at 2.5 s
    assert found == {
        "review": False,
        "first_new_index": 2,
        "transition_seconds": 2.5,
        "window_start_seconds": 1.0,
        "window_end_seconds": 2.5,
    }
    assert found["transition_seconds"] == transition_time(state, found["first_new_index"])
    assert earliest_transition(state, [False, False, False]) is None
    assert earliest_transition(rows(3.0), []) is None
    for bad in ([True], [True, False, False, False], [1, 0, 0], [0.0, False, False], "ab"):
        with pytest.raises(ValueError):
            earliest_transition(state, bad)
    with pytest.raises(ValueError):
        earliest_transition([], [])


def test_earliest_transition_undetermined_pair_is_review_not_a_later_transition():
    state = rows(0.0, 1.0, 2.5, 4.0)
    # pair (1, 2) is undetermined and pair (2, 3) says changed: the earliest is not established
    review = earliest_transition(state, [False, None, True])
    assert review == {
        "review": True,
        "first_undetermined_index": 1,
        "window_start_seconds": 1.0,
        "window_end_seconds": 2.5,
    }
    assert "transition_seconds" not in review
    # a confident True before the undetermined pair still wins
    assert earliest_transition(state, [True, None, None])["transition_seconds"] == 1.0
    # no True at all but an undetermined pair: review, not "unchanged"
    assert earliest_transition(state, [False, False, None])["first_undetermined_index"] == 2
    assert earliest_transition(state, [None, True, True])["first_undetermined_index"] == 0
    assert earliest_transition(state, [False, False, False]) is None


def test_earliest_transition_accepts_numpy_booleans():
    state = rows(0.0, 1.0, 2.0)
    flags = np.array([0.2, 0.9]) >= 0.5
    found = earliest_transition(state, flags)
    assert found["first_new_index"] == 2 and found["transition_seconds"] == 2.0
    assert earliest_transition(state, [np.bool_(False), np.bool_(False)]) is None


def test_frame_windows_cover_the_end_of_the_sequence():
    times = [i / 2 for i in range(17)]  # 0.0 .. 8.0 every 0.5 s
    windows = frame_windows(times, width_seconds=3.0, stride_seconds=2.0)
    # stride-spaced windows start at 0, 2, 4 and end at 3, 5, 7; a final one is [5, 8]
    assert [(w["window_start_seconds"], w["window_end_seconds"]) for w in windows] == [
        (0.0, 3.0),
        (2.0, 5.0),
        (4.0, 7.0),
        (5.0, 8.0),
    ]
    assert windows[-1]["indices"] == list(range(10, 17))
    covered = {i for w in windows for i in w["indices"]}
    assert covered == set(range(17))
    # frames 0..4, width 2, stride 1.5: windows [0,2], [1.5,3.5] and the final [2,4]
    small = frame_windows([0.0, 1.0, 2.0, 3.0, 4.0], width_seconds=2.0, stride_seconds=1.5)
    assert [(w["window_start_seconds"], w["window_end_seconds"]) for w in small] == [
        (0.0, 2.0),
        (1.5, 3.5),
        (2.0, 4.0),
    ]
    assert {i for w in small for i in w["indices"]} == {0, 1, 2, 3, 4}
    # an exactly dividing stride adds nothing
    assert len(frame_windows(times, width_seconds=4.0, stride_seconds=2.0)) == 3


def _covered(windows):
    return {i for w in windows for i in w["indices"]}


def test_frame_windows_cover_every_frame_when_stride_is_at_most_width():
    # stride == width is the boundary: neighbouring windows share an edge, nothing falls between
    times = [i / 2 for i in range(19)]  # 0.0 .. 9.0 every 0.5 s
    exact = frame_windows(times, width_seconds=2.0, stride_seconds=2.0)
    # windows [0,2] [2,4] [4,6] [6,8], then the end-aligned [7,9]
    assert [(w["window_start_seconds"], w["window_end_seconds"]) for w in exact] == [
        (0.0, 2.0),
        (2.0, 4.0),
        (4.0, 6.0),
        (6.0, 8.0),
        (7.0, 9.0),
    ]
    assert _covered(exact) == set(range(19))
    # every width/stride pair on a grid with stride <= width, with and without start/end
    for width in (0.5, 1.0, 1.5, 2.0, 3.0):
        for stride in (0.5, 0.7, 1.0, 1.5, 2.0, 3.0):
            if stride > width:
                continue
            windows = frame_windows(times, width_seconds=width, stride_seconds=stride)
            assert _covered(windows) == set(range(19)), (width, stride)
            inner = frame_windows(
                times, width_seconds=width, stride_seconds=stride, start=1.0, end=8.5
            )
            assert _covered(inner) == set(range(2, 18)), (width, stride, "start/end")


def test_frame_windows_with_a_stride_wider_than_the_width_leave_frames_out():
    times = [float(i) for i in range(11)]  # 0 .. 10 s, one frame per second
    windows = frame_windows(times, width_seconds=1.0, stride_seconds=5.0)
    # sparse by construction: [0,1] and [5,6], plus the end-aligned [9,10]
    assert [(w["window_start_seconds"], w["window_end_seconds"]) for w in windows] == [
        (0.0, 1.0),
        (5.0, 6.0),
        (9.0, 10.0),
    ]
    assert [w["indices"] for w in windows] == [[0, 1], [5, 6], [9, 10]]
    assert set(range(11)) - _covered(windows) == {2, 3, 4, 7, 8}
    # the smallest overshoot: width 0.5, stride 1.5 over a half-second grid drops two of every three
    half = [i / 2 for i in range(21)]  # 0.0 .. 10.0
    narrow = frame_windows(half, width_seconds=0.5, stride_seconds=1.5)
    assert sorted(set(range(21)) - _covered(narrow)) == [2, 5, 8, 11, 14, 17]


def test_frame_windows_stride_wider_than_the_width_is_accepted_and_may_leave_no_frame_out():
    times = [float(i) for i in range(11)]  # 0 .. 10 s, one frame per second
    # width 1, stride 1.5: the windows [0, 1] [1.5, 2.5] [3, 4] [4.5, 5.5] [6, 7] [7.5, 8.5]
    # [9, 10] hold every frame although the stride is wider than the width: no error, no gap
    aligned = frame_windows(times, width_seconds=1.0, stride_seconds=1.5)
    assert [w["window_start_seconds"] for w in aligned] == [0.0, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0]
    assert set(range(11)) - _covered(aligned) == set()
    # width 1, stride 5: the frames in no window are what the documented expression gives
    sparse = frame_windows(times, width_seconds=1.0, stride_seconds=5.0)
    n = len(times)
    uncovered = set(range(n)) - {i for w in sparse for i in w["indices"]}
    assert uncovered == {2, 3, 4, 7, 8}


def test_select_frames_validates_an_existing_frame_index():
    state = rows(0.0, 1.0)
    state[1]["frame_index"] = 7
    assert select_frames(state, [1])[0]["frame_index"] == 7
    for bad in ("x", -1, 1.5, True, None):
        broken = rows(0.0, 1.0)
        broken[1]["frame_index"] = bad
        with pytest.raises(ValueError, match="frame_index"):
            select_frames(broken, [1])


DOCS = Path(__file__).resolve().parent.parent / "docs"


def _transition_label_section():
    """The "Transition labels" section of docs/fixtures.md and its JSON example rows."""
    text = (DOCS / "fixtures.md").read_text("utf-8")
    start = text.index("### Transition labels\n")
    section = text[start : text.index("\n## ", start)]
    lines = [
        line
        for block in section.split("```json\n")[1:]
        for line in block[: block.index("```")].splitlines()
        if line.strip()
    ]
    return section, [json.loads(line) for line in lines]


def _validator_problems(root, labels):
    """What the fixture validator reports for a recipe whose test split carries ``labels``."""
    folder = root / "01-demo" / "fixtures"
    folder.mkdir(parents=True)
    ids = ["v00"] + [f"s{i:02d}" for i in range(len(labels))]
    splits = ["validation"] + ["test"] * len(labels)
    inputs = [
        {"id": ident, "split": split, "fields": {"n": n}, "replay_keys": []}
        for n, (ident, split) in enumerate(zip(ids, splits, strict=True))
    ]
    gold = [{"transition": "opened", "seconds": 1.0}, *labels]
    gold_rows = [{"id": ident, "label": label} for ident, label in zip(ids, gold, strict=True)]
    for name, content in (("inputs", inputs), ("labels", gold_rows)):
        text = "".join(json.dumps(row) + "\n" for row in content)
        (folder / f"{name}.jsonl").write_text(text, encoding="utf-8", newline="\n")
    return [str(problem) for problem in validate_recipe(folder.parent)]


def test_transition_label_examples_follow_the_stated_format_and_decode_for_the_metric():
    _, examples = _transition_label_section()
    assert len(examples) >= 2
    pairs = []
    for row in examples:
        label = row["label"]
        assert "transition" in label and set(label) <= {"transition", "seconds"}, label
        assert isinstance(label["transition"], str) and label["transition"], label
        if "seconds" in label:
            seconds = label["seconds"]
            assert isinstance(seconds, int | float) and not isinstance(seconds, bool), label
            assert math.isfinite(seconds) and seconds >= 0, label
        pairs.append((label["transition"], label.get("seconds")))
    assert any(s is None for _, s in pairs) and any(s is not None for _, s in pairs), (
        "the section must show a label with a time and one without"
    )
    scored = transition_metrics(pairs, pairs, tolerance_seconds=0.5)
    assert scored.exact_correct == len(pairs)


def test_the_validator_checks_nothing_specific_to_transition_labels(tmp_path):
    _, examples = _transition_label_section()
    shown = [row["label"] for row in examples]
    assert _validator_problems(tmp_path / "ok", shown) == []
    malformed = [
        {"transition": "opened", "seconds": -1.0},
        {"transition": "opened", "seconds": "2.5"},
        {"transition": "opened", "seconds": True},
        {"transition": "opened", "seconds": None},
        {"seconds": 2.5},
        {"transition": "", "seconds": 1.0},
        {"transition": "opened", "seconds": 2.5, "note": "x"},
        {"transition": "uncertain"},
    ]
    for n, label in enumerate(malformed):
        assert _validator_problems(tmp_path / f"bad{n}", [label]) == [], label
    # `present` is the Box format's marker: the validator reads the object as a Box label
    marked = {"transition": "opened", "seconds": 2.5, "present": True}
    problems = _validator_problems(tmp_path / "present", [marked])
    assert any("Box label" in problem for problem in problems), problems
    # and a file that mixes Box labels with transition labels fails
    mixed = _validator_problems(tmp_path / "mixed", [{"present": False}])
    assert any("Box label" in problem for problem in mixed), mixed


def test_the_metric_rejects_a_malformed_gold_time_and_a_review_label():
    for pair in [("opened", -1.0), ("opened", "2.5"), ("opened", True), ("uncertain", None)]:
        with pytest.raises(ValueError):
            transition_metrics([pair], [pair], tolerance_seconds=0.5)


def test_vision_links_to_the_transition_label_format():
    vision = (DOCS / "vision.md").read_text("utf-8")
    assert "(fixtures.md#transition-labels)" in vision
    assert "### Transition labels\n" in (DOCS / "fixtures.md").read_text("utf-8")
