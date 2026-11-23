"""#539: a refused duplicate name must leave pixels and the object ledger intact.

The literal calls below exercise the documented public API, including the methods that
delegate painting to another drawer. They do not inspect the implementation or pin PNGs.
Only duplicate-name refusals are required to be atomic here; arbitrary invalid arguments
are not a whole-method transaction contract.
"""

from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest

from jev_cookbook.synthetic_images import Canvas


@dataclass(frozen=True)
class Call:
    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any] = field(default_factory=dict)

    def draw(self, canvas: Canvas, name: Any):
        return getattr(canvas, self.method)(*self.args, **self.kwargs, name=name)


# One independently specified, visible, valid call for every public name-bearing drawer.
# Perturbations use a small region containing a contrast edge; defects use a real surface.
DRAWERS = (
    Call("rect", (30, 40, 60, 50, "teal"), {"outline": "ink"}),
    Call("ellipse", (30, 40, 60, 50, "teal"), {"outline": "ink"}),
    Call("triangle", (30, 40, 60, 50, "teal"), {"direction": "right"}),
    Call("line", (30, 40, 90, 85, "blue", 3)),
    Call("text", (30, 40, "HELLO", "ink", 2)),
    Call("centered_text", ((30, 40, 150, 90), "HELLO", "ink", 2)),
    Call("text_block", (30, 40, ["ONE", " ", "TWO"], "ink", 2)),
    Call("labelled_object", (30, 40, 90, 60, "teal"), {"label": "A"}),
    Call("stamp", (30, 40, 90, 60, "OK")),
    Call("signature", (30, 40, 90, 40)),
    Call("schematic_symbol", (30, 40, 100, 60, "valve")),
    Call("window", (30, 40, 240, 140, "TEST")),
    Call("button", (30, 40, 100, 40, "GO")),
    Call("text_input", (30, 70, 160, 36, "VALUE"), {"label": "FIELD", "focused": True}),
    Call(
        "dialog",
        (30, 30, 300, 160, "NOTICE", ["READY"]),
        {"buttons": ["OK", "BACK"], "dim_backdrop": 55},
    ),
    Call("error_banner", (30, 40, 240, 40, "HI")),
    Call("spinner", (80, 80, 24), {"phase": 3}),
    Call("bar", (30, 40, 120, 20, 0.5)),
    Call("wordmark", (30, 40, 220, 40), {"text": "ZORA", "emblem": "bars", "colour": "purple"}),
    Call("scratch", ("surface",), {"start": (30, 220), "end": (95, 260), "width": 2}),
    Call("dent", ("surface",), {"depth_percent": 60, "size_percent": 50}),
    Call("missing_part", ("surface",)),
    Call("blur", (2,), {"region": (220, 180, 300, 260)}),
    Call("noise", (15,), {"region": (220, 180, 300, 260), "grey": False}),
    Call("lighting", (60,), {"region": (220, 180, 300, 260), "gradient_percent": 20}),
    Call("occlude", ("surface",), {"fraction": 0.5, "side": "left", "fill": "red"}),
)


def canvas() -> Canvas:
    """Synthetic, disposable pixels; no asset generation or filesystem writes."""
    result = Canvas(400, 300, seed=17)
    result.rect(20, 200, 90, 80, "teal", name="surface")
    result.rect(240, 190, 30, 50, "red", name="contrast")
    return result


def snapshot(canvas: Canvas):
    # Deep-copy values so in-place changes to a Drawn's attrs cannot hide behind equality.
    return canvas.image.tobytes(), deepcopy(canvas.objects)


def assert_duplicate_is_atomic(canvas: Canvas, call: Call, name: Any = "taken"):
    before_pixels, before_objects = snapshot(canvas)
    with pytest.raises(ValueError, match="already used on this canvas"):
        call.draw(canvas, name)
    assert canvas.image.tobytes() == before_pixels, f"{call.method} painted before refusing"
    assert canvas.objects == before_objects, f"{call.method} changed the ledger before refusing"


def test_the_literal_table_covers_every_public_name_bearing_drawer():
    methods = {
        name
        for name, method in inspect.getmembers(Canvas, inspect.isfunction)
        if not name.startswith("_") and "name" in inspect.signature(method).parameters
    }
    assert {call.method for call in DRAWERS} == methods
    assert len(DRAWERS) == len(methods) == 26


@pytest.mark.parametrize("call", DRAWERS, ids=lambda call: call.method)
def test_each_drawer_refuses_a_global_duplicate_before_pixels_or_objects_change(call):
    c = canvas()
    # A different drawer owns the name: uniqueness applies to the entire canvas.
    if call.method == "text":
        c.rect(355, 10, 20, 20, "red", name="taken")
    else:
        c.text(355, 10, "X", "red", 1, name="taken")
    assert_duplicate_is_atomic(c, call)


@pytest.mark.parametrize("call", DRAWERS, ids=lambda call: call.method)
@pytest.mark.parametrize("name", ["available", ""], ids=["named", "empty-string-name"])
def test_each_literal_call_really_paints_and_records_when_the_name_is_available(call, name):
    c = canvas()
    before_pixels, before_objects = snapshot(c)
    result = call.draw(c, name)
    assert c.image.tobytes() != before_pixels
    assert c.objects != before_objects
    assert c.objects[name] is result
    assert result.name == name


@pytest.mark.parametrize("call", DRAWERS, ids=lambda call: call.method)
def test_each_drawer_accepts_an_explicit_unnamed_call_without_recording_none(call):
    c = canvas()
    before_pixels, before_objects = snapshot(c)
    result = call.draw(c, None)
    assert c.image.tobytes() != before_pixels
    assert result.name is None
    assert None not in c.objects
    if call.method == "missing_part":
        del before_objects["surface"]
    assert c.objects == before_objects


# These calls retain visible paint when clipped. All their required components remain
# valid, so a passing duplicate refusal cannot be explained by an off-canvas/fit error.
CLIPPED = (
    Call("rect", (390, 40, 40, 40, "blue")),
    Call("ellipse", (390, 40, 40, 40, "blue")),
    Call("triangle", (390, 40, 40, 40, "blue"), {"direction": "left"}),
    Call("line", (390, 40, 430, 70, "blue", 3)),
    Call("text", (395, 40, "H", "ink", 2)),
    Call("labelled_object", (390, 40, 40, 40, "teal")),
    Call("schematic_symbol", (-5, 40, 100, 60, "resistor")),
    Call("error_banner", (-5, 40, 240, 40, "HI")),
    Call("bar", (390, 40, 80, 20, 0.5)),
    Call("wordmark", (-5, 40, 220, 40), {"text": "ZORA", "emblem": "disc"}),
)


@pytest.mark.parametrize("call", CLIPPED, ids=lambda call: call.method)
def test_clipped_drawers_still_refuse_duplicates_before_painting(call):
    positive = canvas()
    pixels = positive.image.tobytes()
    drawn = call.draw(positive, "free")
    assert positive.image.tobytes() != pixels
    assert positive.objects["free"] is drawn

    c = canvas()
    c.text(355, 10, "X", "red", 1, name="taken")
    assert_duplicate_is_atomic(c, call)


# Collision with a component the composite WILL create is a duplicate refusal too.
# Include late components to catch methods that paint/record earlier components first.
COMPONENT_COLLISIONS = (
    (Call("text_block", (30, 40, ["ONE", " ", "TWO"])), "group.line2"),
    (Call("window", (30, 40, 240, 140, "TEST")), "group.title_bar"),
    (Call("window", (30, 40, 240, 140, "TEST")), "group.minimize"),
    (Call("text_input", (30, 70, 160, 36, "VALUE"), {"label": "FIELD"}), "group.label"),
    (
        Call(
            "dialog",
            (30, 30, 300, 160, "NOTICE", ["READY"]),
            {"buttons": ["OK", "BACK"], "dim_backdrop": 55},
        ),
        "group.button1",
    ),
)


@pytest.mark.parametrize(
    "call,component",
    COMPONENT_COLLISIONS,
    ids=["block-line2", "window-title", "window-minimize", "input-label", "dialog-button1"],
)
def test_existing_component_names_are_checked_before_any_composite_pixels_change(call, component):
    positive = canvas()
    pixels = positive.image.tobytes()
    call.draw(positive, "group")
    assert positive.image.tobytes() != pixels
    assert component in positive.objects

    c = canvas()
    c.rect(355, 10, 20, 20, "red", name=component)
    assert_duplicate_is_atomic(c, call, "group")


@pytest.mark.parametrize(
    "call,unused_suffix",
    [
        (Call("text_block", (30, 40, ["ONE", " ", "TWO"])), "group.line1"),
        (Call("text_input", (30, 70, 160, 36)), "group.label"),
        (Call("dialog", (30, 30, 300, 160, "NOTICE", ["READY"])), "group.button1"),
    ],
    ids=["blank-line", "absent-label", "absent-second-button"],
)
def test_unused_component_suffixes_do_not_reserve_names(call, unused_suffix):
    c = canvas()
    existing = c.rect(355, 10, 20, 20, "red", name=unused_suffix)
    pixels = c.image.tobytes()
    result = call.draw(c, "group")
    assert c.image.tobytes() != pixels
    assert c.objects["group"] is result
    assert c.objects[unused_suffix] is existing


def test_missing_part_cannot_remove_its_target_to_make_a_duplicate_name_available():
    c = canvas()
    assert_duplicate_is_atomic(c, Call("missing_part", ("surface",)), "surface")


@pytest.mark.parametrize("name", [0, 7, ("tag", 1)])
def test_existing_acceptance_of_hashable_non_string_names_is_preserved(name):
    c = canvas()
    drawn = c.rect(30, 40, 20, 20, "blue", name=name)
    assert c.objects[name] is drawn
    assert_duplicate_is_atomic(c, Call("rect", (70, 40, 20, 20, "red")), name)


@pytest.mark.parametrize("name", [[], {}], ids=["list", "dict"])
def test_unhashable_names_still_raise_typeerror(name):
    # No assertion about pixels: the parent never promised invalid-name transactions.
    with pytest.raises(TypeError, match="unhashable"):
        canvas().rect(30, 40, 20, 20, "blue", name=name)


@pytest.mark.parametrize(
    "call,message",
    [
        (Call("text", (30, 40, "   ")), "no visible character"),
        (Call("text_block", (30, 40, [" ", "   "])), "no visible character"),
        (Call("text_block", (30, 40, [])), "non-empty sequence"),
        (Call("rect", (30, 40, 20, 20)), "needs a fill"),
        (Call("missing_part", ((320, 220, 340, 240),)), "changed nothing"),
    ],
    ids=["space-text", "space-block", "empty-block", "empty-rect", "unchanged-removal"],
)
def test_existing_no_data_refusals_keep_their_messages_and_do_not_record_names(call, message):
    c = canvas()
    before_pixels, before_objects = snapshot(c)
    with pytest.raises(ValueError, match=message):
        call.draw(c, "free")
    assert c.image.tobytes() == before_pixels
    assert c.objects == before_objects
