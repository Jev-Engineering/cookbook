"""Python's half of recipe 69: the catalogue, the request Jev sees, the question and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the catalogue, the images' references, the question and the
rules come from one place.

The pattern this file shows (reference images inside fixed ``Choice`` criteria):

* Python owns the catalogue. Each product is one ``Sku`` and its reference image is a file under
  ``assets/``.
* ``build_questions`` puts each product's reference into that option's criteria with
  ``image_reference``, so the reference is part of the question, not of the example.
* ``build_request`` puts the query image in the state once and returns every asset the request
  needs: the query and all the references. Every place a reference appears adds a copy of that
  image to the request (docs/vision.md), so the criteria's references repeat on every call.
* ``gold_label`` and ``decide_sku`` are rules that hold whatever the model answers.

No ``from __future__ import annotations`` here: ``load_helpers`` removes this module from
``sys.modules``, so ``typing.get_type_hints`` cannot resolve postponed annotations on a dataclass.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from jev_cookbook import Choice
from jev_cookbook import synthetic_images as si
from jev_cookbook.simulation import ReviewQueue, Routed, fill_review_queue
from jev_cookbook.vision import image_asset, image_reference, resolve_asset_path

# The recipe folder. The image paths in fixtures/inputs.jsonl are relative to it.
ROOT = Path(__file__).resolve().parent

NO_MATCH, UNCERTAIN = "no_match", "uncertain"
ANSWERED, REVIEW = "answered", "review"  # what decide_sku returns

# The visual features that make up a tin's design, in the order the question names them.
ATTRIBUTES = ("body", "lid", "emblem")


@dataclass(frozen=True)
class Sku:
    """One product of the invented catalogue: a name and the design of its tin."""

    name: str
    body: str  # the body colour
    lid: str  # the lid colour
    emblem: str  # the shape printed on the label

    @property
    def reference_path(self) -> str:
        """Where this product's reference image is saved, relative to the recipe."""
        return f"assets/reference-{self.name.lower()}.png"

    def design(self) -> dict[str, str]:
        return {"body": self.body, "lid": self.lid, "emblem": self.emblem}


# The names are invented (jev_cookbook.synthetic_images.fictional_name seeds 2, 4, 5, 6, 22 and
# 23). DEGUM and BIVEN differ in exactly one feature, the emblem: that is the pair a hidden
# emblem cannot separate.
CATALOG = (
    Sku("DEGUM", "blue", "ink", "ring"),
    Sku("BIVEN", "blue", "ink", "bars"),
    Sku("NOKER", "teal", "white", "disc"),
    Sku("PEBIX", "green", "ink", "triangle"),
    Sku("VODAR", "amber", "white", "stack"),
    Sku("MAFEX", "purple", "white", "ring"),
)

# Python builds the option list: every product, then the two outcomes this use case names.
OPTIONS = tuple(sku.name for sku in CATALOG) + (NO_MATCH, UNCERTAIN)


def candidates(visible: Mapping[str, str | None]) -> list[str]:
    """The catalogue products whose design agrees with every feature that can be seen.

    ``visible`` maps each of ``ATTRIBUTES`` to the feature seen in a query, or to ``None`` for a
    feature the picture does not show (a tag covers it). A product is a candidate when each seen
    feature equals its own and each hidden feature is allowed to be anything.
    """
    if set(visible) != set(ATTRIBUTES):
        raise ValueError(f"visible must name exactly {ATTRIBUTES}, got {sorted(visible)}")
    return [
        sku.name
        for sku in CATALOG
        if all(visible[a] is None or visible[a] == getattr(sku, a) for a in ATTRIBUTES)
    ]


def gold_label(visible: Mapping[str, str | None] | None) -> str:
    """The right option for a query, derived from what it shows.

    ``None`` means no tin is in the image. Otherwise the candidates decide: none means the design
    is not in the catalogue (``no_match``), exactly one is that product's name, and two or more
    mean the picture cannot say which (``uncertain``).
    """
    if visible is None:
        return NO_MATCH
    found = candidates(visible)
    if not found:
        return NO_MATCH
    return found[0] if len(found) == 1 else UNCERTAIN


def reference_assets() -> dict[str, tuple[str, dict[str, Any]]]:
    """``{product name: (reference, asset)}`` for every product, in catalogue order."""
    found = {}
    for sku in CATALOG:
        asset = image_asset(sku.reference_path, root=ROOT)
        found[sku.name] = (image_reference(asset), asset)
    if len({reference for reference, _ in found.values()}) != len(found):
        raise ValueError("two products share one reference image, which cannot tell them apart")
    return found


def build_request(fields: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """``(state, assets)`` for one example: what Jev sees and every image that goes with it.

    ``fields`` names the query image by a path relative to the recipe and also carries the
    capture identifier and the condition it was drawn under. Python keeps those two; the state
    holds only the query image's reference, once. The assets hold the query and every reference
    the question's criteria use, because a reference with no asset would be plain text.
    """
    asset = image_asset(fields["image"], root=ROOT)
    reference = image_reference(asset)
    assets = {ref: found for ref, found in reference_assets().values()}
    if reference in assets:
        raise ValueError("the query image has the bytes of a reference image")
    assets[reference] = asset
    return {"query": reference}, assets


def build_questions() -> dict[str, Any]:
    """The one question asked about every example: which product is in the query image?

    Each product's criteria hold its reference image and a sentence on how to use it; the two
    outcome options are words only. The same ``Choice`` is asked of every example, so the
    references sit in the criteria and not in the state.
    """
    criteria: dict[str, Any] = {}
    for name, (reference, _asset) in reference_assets().items():
        criteria[name] = (
            f"The catalogue product {name}. Its reference image is {reference}. The query shows "
            "this product when its tin has the same body colour, lid colour and label emblem as "
            "the tin in this reference image."
        )
    criteria[NO_MATCH] = (
        "The tin in the query is not any product above: its body colour, lid colour and label "
        "emblem together are not those of any reference image, or the query shows no tin at "
        "all. Choose this even when the tin looks close to one product but differs from it in a "
        "feature you can see."
    )
    criteria[UNCERTAIN] = (
        "What the query shows fits two or more of the products above equally well and the image "
        "does not settle which, usually because a pink SALE tag covers the feature that tells "
        "them apart. Choose a product, not this, when what is visible already rules out every "
        "other product."
    )
    return {
        "sku": Choice(
            instructions=(
                "Which option is the tin shown in the `query` image? Each product option's "
                "criteria hold that product's reference image: the tin seen straight on, in "
                "even light, on a plain background. Compare design, not photography: the query "
                "can be dimmer, noisier, smaller, shifted in the frame or standing on a shelf, "
                "and none of that changes which product it is. A tin's design is its body "
                "colour, its lid colour and the emblem on its label."
            ),
            criteria=criteria,
        )
    }


def open_image(path: str) -> Image.Image:
    """The image at ``path`` (relative to the recipe) as an RGB Pillow image."""
    with Image.open(resolve_asset_path(path, root=ROOT)) as picture:
        return picture.convert("RGB")


def contact_sheet(items: Iterable[tuple[str, str]], *, cell: tuple[int, int] = (160, 180)) -> bytes:
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


def decide_sku(capture: str, answer: Any, threshold: float) -> Outcome:
    """Deliver a product or ``no_match`` only when Jev is confident; otherwise queue a review.

    ``uncertain`` is a deferral ("ask a person"), so it is always a review, whatever its
    confidence. Every other option, ``no_match`` included, is delivered when the answer's
    confidence is at least ``threshold`` and is a review below it. ``no_match`` is not exempted
    from that gate. The rule is code, so it holds whatever the model answers: an option that is
    not in the catalogue's list raises instead of being delivered.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold!r}")
    if answer.choice not in OPTIONS:
        raise ValueError(f"{answer.choice!r} is not one of {OPTIONS}")
    if answer.choice == UNCERTAIN:
        return Outcome(capture, REVIEW, answer.choice, None, "the answer is uncertain", answer)
    if answer.confidence < threshold:
        return Outcome(
            capture, REVIEW, answer.choice, None, "confidence below the threshold", answer
        )
    return Outcome(capture, ANSWERED, answer.choice, answer.choice, "confident answer", answer)


def queue_reviews(queue: ReviewQueue, outcomes: Iterable[Outcome]) -> Routed:
    """Submit every outcome that is a review to ``queue`` with its reason; nothing else happens.

    A delivered answer, ``no_match`` included, writes nothing: no log entry, no message and no
    change to a listing. The item keeps the capture identifier and what Jev chose.
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
