"""Python's half of recipe 61: the category list, the request Jev sees, the question and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the options, the question and the rules come from one place.

The pattern this file shows (one ``Choice`` over one image, with a fallback option):

* Python owns the option list. ``OPTIONS`` is a fixed tuple, ``unknown`` is the last member, and
  nothing Jev answers can add to it.
* ``build_request`` puts the screenshot in the state once, as an image reference, and returns the
  image it refers to. Every place an image appears adds a copy to the request (docs/vision.md);
  here the criteria are words only, so each request carries exactly one copy.
* ``gold_label``, ``choose_threshold``, ``decide_state`` and ``queue_reviews`` are rules that hold
  whatever the model answers.

No ``from __future__ import annotations`` here: ``load_helpers`` removes this module from
``sys.modules``, so ``typing.get_type_hints`` cannot resolve postponed annotations on a dataclass.
"""

import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from jev_cookbook import Choice, ChoiceAnswer
from jev_cookbook import synthetic_images as si
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.simulation import ReviewQueue, Routed, fill_review_queue
from jev_cookbook.vision import image_asset, image_reference, resolve_asset_path

# The recipe folder. The image paths in fixtures/inputs.jsonl are relative to it.
ROOT = Path(__file__).resolve().parent

CRASH, LOADING, AUTH_FAILURE, NORMAL, UNKNOWN = (
    "crash",
    "loading",
    "auth_failure",
    "normal",
    "unknown",
)
ANSWERED, REVIEW = "answered", "review"  # what decide_state returns

# Python builds the option list: the four visual categories, then the fallback this use case
# names. The order is fixed and carries no meaning, so no position statistic is reported.
OPTIONS = (CRASH, LOADING, AUTH_FAILURE, NORMAL, UNKNOWN)

# What each drawing is. The generator in build_fixtures.py draws one of these ``kind`` values, and
# the gold label of the image is read from this table, never typed beside the example. The kinds
# that are look-alikes of another category, or that fit no category, are the hard cases.
KINDS = {
    "sign_in": NORMAL,  # a plain sign-in form
    "sign_in_rejected": AUTH_FAILURE,  # a banner and a red field
    "sign_in_waiting": LOADING,  # a disabled button and a spinner
    "sign_in_crashed": CRASH,  # a dimmed dialog reporting an application error
    "waiting_with_warning": LOADING,  # still waiting, with an error-like warning banner
    "rejected_inline": AUTH_FAILURE,  # no banner: one small line under the password field
    "sign_in_with_hint": NORMAL,  # a sign-in form with red "forgot password" text
    "dashboard": NORMAL,  # a working screen of figures and bars
    "dashboard_crashed": CRASH,  # the dashboard under a dimmed fatal-error dialog
    "page_not_found": UNKNOWN,  # a different error: no category names it
    "payment_declined": UNKNOWN,  # a different error on a checkout form
    "maintenance": UNKNOWN,  # a notice that the service is down for planned work
    "partial_render": UNKNOWN,  # a frame with a title bar and almost nothing drawn
}


def gold_label(kind: str) -> str:
    """The right option for a screenshot drawn as ``kind``, read from ``KINDS``.

    An unlisted kind raises: a drawing nobody has labelled must not receive a default label.
    """
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is not one of {sorted(KINDS)}")
    return KINDS[kind]


def build_request(fields: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """``(state, assets)`` for one example: what Jev sees and the image that goes with it.

    ``fields`` names the screenshot by a path relative to the recipe and also carries the capture
    identifier. Python keeps the identifier; the state holds only the image's reference, once, so
    the request carries one copy of one image. The kind of drawing, which decides the gold label,
    is in no field: it stays in the fixture generator.
    """
    asset = image_asset(fields["image"], root=ROOT)
    reference = image_reference(asset)
    return {"screenshot": reference}, {reference: asset}


def build_questions() -> dict[str, Any]:
    """The one question asked about every example: which state does the screenshot show?

    The criteria are words only. Each of the four categories says what to look for and, for the
    two that have a look-alike, what does not change the answer; ``unknown`` names the cases that
    fit none of them. The same ``Choice`` is asked of every example.
    """
    criteria = {
        CRASH: (
            "The application itself has failed: the screenshot shows a dialog or screen that "
            "reports an unexpected application failure, with a restart or close choice."
        ),
        LOADING: (
            "The application is waiting for something to finish: the screenshot shows a spinner "
            "or a disabled action. A warning about a slow connection does not change that the "
            "application is still waiting."
        ),
        AUTH_FAILURE: (
            "A sign-in was rejected: the screenshot shows a sign-in form that reports wrong "
            "credentials, by a banner or by a small message and a field marked invalid, even "
            "when the rest of the form looks ordinary."
        ),
        NORMAL: (
            "The application is working and nothing is wrong: the screenshot shows an ordinary "
            "screen with no failure message, no waiting and no rejected sign-in. A link such as "
            "a password reminder is ordinary."
        ),
        UNKNOWN: (
            "None of the other four options fits: the screenshot shows a different kind of "
            "error or notice, or so little that it cannot be told which state it is."
        ),
    }
    return {
        "app_state": Choice(
            instructions=(
                "Which option describes the application state shown in the `screenshot` image? "
                "Judge what the screen reports, not how the window is laid out: the same state "
                "can appear on a sign-in form or on a dashboard."
            ),
            criteria=criteria,
        )
    }


def open_image(path: str) -> Image.Image:
    """The image at ``path`` (relative to the recipe) as an RGB Pillow image."""
    with Image.open(resolve_asset_path(path, root=ROOT)) as picture:
        return picture.convert("RGB")


def png_bytes(image: Image.Image) -> bytes:
    """``image`` as PNG bytes, for ``IPython.display.Image(data=..., format="png")``."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def contact_sheet(items: Iterable[tuple[str, str]], *, cell: tuple[int, int] = (240, 160)) -> bytes:
    """PNG bytes of a row of small pictures, each with its label above it.

    ``items`` are ``(label, path)`` pairs, the path relative to the recipe. The sheet is only for
    looking at in the notebook; nothing sent to Jev comes from it.
    """
    pairs = list(items)
    if not pairs:
        raise ValueError("a contact sheet needs at least one picture")
    width = max(280, cell[0] * len(pairs))
    height = max(280, cell[1] + 24)
    sheet = si.Canvas(width, height, "paper")
    for index, (label, path) in enumerate(pairs):
        left = index * cell[0]
        thumbnail = open_image(path)
        thumbnail.thumbnail((cell[0] - 8, cell[1]))
        sheet.image.paste(thumbnail, (left + 4, 22))
        sheet.text(left + 6, 6, label, "ink", 1)
    return sheet.png()


@dataclass(frozen=True)
class Outcome:
    """What Python decided for one example: an answer or a review, with the reason.

    ``choice`` is what Jev chose and is kept even when the example goes to review, so a review
    shows what triggered it. ``label`` is the delivered answer, or ``None`` for a review.
    """

    capture: str
    kind: str
    choice: str
    label: str | None
    reason: str
    answer: Any = field(default=None, repr=False, compare=False)


def choose_threshold(
    answers: Iterable[ChoiceAnswer], gold: Iterable[str], *, target_accuracy: float
) -> tuple[float | None, int]:
    """Freeze a validation cutoff and count its candidates. None means withhold all deliveries.

    Only an answer that can be delivered sets the bar, so every ``unknown`` answer is left out:
    ``decide_state`` always sends it to review, whatever its confidence.
    """
    eligible = [
        (a.choice == g, a.confidence)
        for a, g in zip(answers, gold, strict=True)
        if a.choice != UNKNOWN
    ]
    if not eligible:
        return None, 0
    try:
        threshold = select_confidence_threshold(
            [right for right, _ in eligible],
            [confidence for _, confidence in eligible],
            target_accuracy=target_accuracy,
        )
    except ValueError as error:
        if str(error) != f"no threshold reaches accuracy {target_accuracy}":
            raise
        return None, len(eligible)
    return threshold, len(eligible)


def decide_state(capture: str, answer: Any, threshold: float | None) -> Outcome:
    """Deliver a category only when Jev is confident; otherwise queue a review.

    ``unknown`` is a deferral ("ask a person"), so it is always a review, whatever its
    confidence. Each of the four categories is delivered when the answer's confidence is at least
    ``threshold`` and is a review below it. With no validated threshold, every eligible answer
    goes to review. The rule is code, so it holds whatever the model answers: an option outside
    ``OPTIONS`` raises instead of being delivered.
    """
    if threshold is not None and not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold!r}")
    if answer.choice not in OPTIONS:
        raise ValueError(f"{answer.choice!r} is not one of {OPTIONS}")
    if answer.choice == UNKNOWN:
        return Outcome(capture, REVIEW, answer.choice, None, "the answer is unknown", answer)
    if threshold is None:
        return Outcome(capture, REVIEW, answer.choice, None, "no validated threshold", answer)
    # Written so that a NaN confidence (every comparison with it is False) is a review, not a delivery.
    if not answer.confidence >= threshold:
        return Outcome(
            capture, REVIEW, answer.choice, None, "confidence below the threshold", answer
        )
    return Outcome(capture, ANSWERED, answer.choice, answer.choice, "confident answer", answer)


def queue_reviews(queue: ReviewQueue, outcomes: Iterable[Outcome]) -> Routed:
    """Submit every outcome that is a review to ``queue`` with its reason; nothing else happens.

    A delivered answer writes nothing: no log entry, no message and no change to any system. The
    item keeps the capture identifier and what Jev chose.
    """
    return fill_review_queue(
        queue,
        outcomes,
        needs_review=lambda o: o.kind == REVIEW,
        item=lambda o: {"capture": o.capture, "model_choice": o.choice},
        reason=lambda o: o.reason,
        answer=lambda o: o.answer,
        key=lambda o: o.capture,
    )
