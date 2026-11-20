"""Banner refusals preserve pixels and the existing object ledger (#388, PR #475)."""

import pytest

from jev_cookbook import synthetic_images as si


@pytest.mark.parametrize(
    ("x", "y", "message", "error"),
    [
        (-200, 10, "HI", "ellipse None lies entirely outside the (640, 400) canvas"),
        (625, 10, "HI", "'!' at scale 2 does not fit in its box"),
        (10, -25, "HI", "'!' at scale 2 does not fit in its box"),
        (10, 390, "HI", "'!' at scale 2 does not fit in its box"),
        (600, 10, "HI", "text None lies entirely outside the (640, 400) canvas"),
        (10, 10, "   ", "the text has no visible character (only spaces)"),
    ],
)
def test_error_banner_late_refusals_leave_the_canvas_unchanged(x, y, message, error):
    canvas = si.Canvas(640, 400)
    canvas.rect(300, 300, 20, 20, "teal", name="existing")
    before, objects = canvas.image.tobytes(), dict(canvas.objects)

    with pytest.raises(ValueError) as raised:
        canvas.error_banner(x, y, 400, 40, message, name="probe")

    assert str(raised.value) == error
    assert canvas.image.tobytes() == before
    assert canvas.objects == objects


@pytest.mark.parametrize(("x", "y"), [(-12, 10), (590, 10), (10, -10), (10, 375)])
def test_error_banner_still_accepts_partly_clipped_components(x, y):
    canvas = si.Canvas(640, 400)
    before = canvas.image.tobytes()

    banner = canvas.error_banner(x, y, 400, 40, "HI", name="probe")

    assert canvas.image.tobytes() != before
    assert canvas.objects == {"probe": banner}
    assert banner.pixels == (max(x, 0), max(y, 0), min(x + 400, 640), min(y + 40, 400))
    assert len(banner.parts) == 4
    assert banner.attrs["message"] == "HI"
