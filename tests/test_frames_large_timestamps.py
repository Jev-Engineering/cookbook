"""Independent nearest-frame checks at representable elapsed times of 1e3 to 1e6 s."""

import math
import random

import pytest

from jev_cookbook.frames import TIME_EPSILON, frame_at, sample_frames


def _all_frame_reference(times, target):
    """Scan every distance, then choose the first frame in the documented tied set."""
    distances = [abs(timestamp - target) for timestamp in times]
    threshold = min(distances) + TIME_EPSILON
    return next(index for index, distance in enumerate(distances) if distance <= threshold)


def _two_candidate_reference(times, target):
    """The before/after rule, using independent linear scans rather than bisection."""
    before = [index for index, time in enumerate(times) if time <= target + TIME_EPSILON]
    after = [index for index, time in enumerate(times) if time >= target - TIME_EPSILON]
    candidates = ([before[-1]] if before else []) + ([after[0]] if after else [])
    closest = min(abs(times[index] - target) for index in candidates)
    return min(
        index for index in candidates if abs(times[index] - target) <= closest + TIME_EPSILON
    )


@pytest.mark.parametrize("base", [1e3, 1e4, 1e5, 1e6])
def test_seeded_large_elapsed_times_match_independent_nearest_references(base):
    rng = random.Random(492)
    ties = 0
    later_is_strictly_closer_but_tied = 0
    selected = set()
    for _ in range(150):
        times = [base + rng.uniform(0.0, 1.0)]
        for _ in range(rng.randint(2, 14)):
            times.append(times[-1] + rng.choice([1e-7, 1e-6, 0.001, 0.04, 0.25, 1.0]))

        # This conservative guard deliberately avoids the documented float-rounding
        # exception near 3 * TIME_EPSILON, including at the largest generated time.
        margin = 3 * TIME_EPSILON + 16 * math.ulp(times[-1])
        assert all(b - a > margin for a, b in zip(times[:-1], times[1:], strict=True))
        targets = [times[0] - 0.5, times[-1] + 0.5, *times]
        for earlier, later in zip(times[:-1], times[1:], strict=True):
            midpoint = earlier + (later - earlier) / 2
            targets.extend(
                [
                    midpoint,
                    math.nextafter(midpoint, math.inf),
                    midpoint - 4 * TIME_EPSILON,
                    midpoint + 4 * TIME_EPSILON,
                    earlier - TIME_EPSILON,
                    earlier + TIME_EPSILON,
                ]
            )
        targets.extend(rng.uniform(times[0] - 0.5, times[-1] + 0.5) for _ in range(8))

        for target in targets:
            expected = _all_frame_reference(times, target)
            assert expected == _two_candidate_reference(times, target), (times, target)
            assert frame_at(times, target, side="nearest") == expected, (times, target)
            selected.add(expected)
            distances = [abs(timestamp - target) for timestamp in times]
            closest = min(distances)
            ties += sum(distance <= closest + TIME_EPSILON for distance in distances) > 1
            later_is_strictly_closer_but_tied += distances[expected] > closest

    assert ties > 0, "the seeded queries must exercise slack ties at every base"
    assert later_is_strictly_closer_but_tied > 0, "ties must exercise more than exact midpoints"
    assert len(selected) > 2, "the oracle must select interior frames as well as endpoints"


@pytest.mark.parametrize("base", [1e3, 1e4, 1e5, 1e6])
def test_large_elapsed_time_endpoints_midpoints_and_slack_have_literal_answers(base):
    # Dyadic offsets make these frame times and the exact midpoint representable.
    times = [base, base + 0.25, base + 0.75, base + 1.0]
    midpoint = base + 0.5
    just_after = math.nextafter(midpoint, math.inf)
    assert just_after > midpoint
    assert abs(times[1] - just_after) > abs(times[2] - just_after)
    assert 2 * (just_after - midpoint) < TIME_EPSILON
    cases = [
        (base - 0.5, 0),
        (times[0], 0),
        (times[1], 1),
        (midpoint, 1),
        (just_after, 1),  # a strictly closer later frame remains tied by the slack
        (midpoint - 4 * TIME_EPSILON, 1),
        (midpoint + 4 * TIME_EPSILON, 2),
        (times[2], 2),
        (times[-1], 3),
        (base + 1.5, 3),
    ]
    for target, expected in cases:
        assert _all_frame_reference(times, target) == expected
        assert frame_at(times, target, side="nearest") == expected


@pytest.mark.parametrize(
    ("times", "target"),
    [
        pytest.param([0.0, 1.0, 1.0 + 3e-10, 2.0], 1.0 + 2e-9, id="first-cluster"),
        pytest.param(
            [0.0, 1.0 - 4e-10, 1.0, 1.0 + 4e-10, 2.0],
            1.0 + 1.5e-9,
            id="second-cluster",
        ),
    ],
)
@pytest.mark.parametrize("operation", ["frame_at", "sample_frames"])
def test_each_original_cluster_input_is_rejected_independently(times, target, operation):
    # Both historical tie examples violate the public minimum-spacing requirement.
    assert any(b - a <= TIME_EPSILON for a, b in zip(times[:-1], times[1:], strict=True))
    with pytest.raises(ValueError, match="gaps greater than TIME_EPSILON"):
        if operation == "frame_at":
            frame_at(times, target, side="nearest")
        else:
            sample_frames(times, every_seconds=target)
