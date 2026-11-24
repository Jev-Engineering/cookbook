"""Python's half of recipe 62: the change catalogue, the request Jev sees, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the gold labels, the questions and the rules come from one place.

The pattern this file shows (independent ``Noul`` propositions plus a ``Score`` per category):

* Python owns the change categories. ``CATEGORIES`` is a fixed tuple, and every gold label is
  read from the change the generator drew (``CHANGES``), never typed beside the example.
* ``build_request`` puts the two screenshots in the state once each, as image references, so a
  request carries two image copies (two copies of one image when the screenshots are identical).
* ``build_questions`` asks one ``Noul`` per category and one ``Score`` per category. Every one of
  them can be built before any answer exists, so all eight go in one request; Python reads a
  category's severity only when its ``Noul`` says the change is there.
* ``choose_noul_thresholds``, ``choose_severity_cutoff`` and ``choose_gate`` freeze the three
  settings on ``validation``; ``decide`` composes the answers into a verdict and
  ``queue_reviews`` is the one simulated side effect. These rules hold whatever the model answers.

No ``from __future__ import annotations`` here: ``load_helpers`` removes this module from
``sys.modules``, so ``typing.get_type_hints`` cannot resolve postponed annotations on a dataclass.
"""

import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from jev_cookbook import Noul, Score
from jev_cookbook import synthetic_images as si
from jev_cookbook.evaluation import score_level, select_confidence_threshold, select_threshold
from jev_cookbook.simulation import ReviewQueue, Routed, fill_review_queue
from jev_cookbook.vision import image_asset, image_reference, resolve_asset_path

# The recipe folder. The image paths in fixtures/inputs.jsonl are relative to it.
ROOT = Path(__file__).resolve().parent

# The predefined change categories, in a fixed order. Each is one Noul proposition and one Score.
MISSING, MISALIGNED, CLIPPED, OVERLAP = "missing_element", "misalignment", "clipping", "overlap"
CATEGORIES = (MISSING, MISALIGNED, CLIPPED, OVERLAP)

# The three verdicts; ``review`` is the review outcome.
PASS, FAIL, REVIEW = "pass", "fail", "review"

# The severity rubric, lowest level first. TypeSafe judges every level on its own, without its
# number or its neighbours (https://docs.typesafe.ai/primitives/score), so each description stands
# alone and names the effect on a person using the page, never "worse than the level below".
LEVEL_NAMES = ("cosmetic", "minor", "major", "blocking")
LEVELS = (
    "Visible only on close comparison: every piece of text is still present and readable, and "
    "every control looks and works as it did.",
    "Plainly visible and looks wrong, but nothing a person needs is lost: all text can still be "
    "read and every control can still be found and used.",
    "Some text a person reads is gone, cut off, covered or placed beside the wrong field, so part "
    "of the page can no longer be read correctly, while the page's main action can still be "
    "found and used.",
    "The page's main action is gone, covered or cannot be used, so a person cannot complete what "
    "the page is for.",
)
# A change at this level or above is a regression that fails the comparison (the gold verdict).
MAJOR = LEVEL_NAMES.index("major")

# What each named change does to the page, by category and gold severity level. The generator in
# build_fixtures.py draws these by name, and the gold label is read from this table. A change
# whose category is None is a benign look-alike: it alters pixels, but it is none of the
# predefined categories, so every proposition is false for it.
CHANGES: dict[str, tuple[str | None, int | None]] = {
    "avatar_missing": (MISSING, 1),  # the decorative profile badge is not drawn
    "help_missing": (MISSING, 2),  # the help line under the form is not drawn
    "save_missing": (MISSING, 3),  # the SAVE CHANGES button is not drawn
    "field_nudged": (MISALIGNED, 0),  # the first field sits 4 pixels to the right
    "field_shifted": (MISALIGNED, 1),  # the first field sits 28 pixels to the right
    "labels_shifted": (MISALIGNED, 2),  # every label sits one row down, beside the wrong field
    "help_clipped_edge": (CLIPPED, 1),  # the bottom 2 of the help line's 14 pixel rows are cut
    "help_clipped_boundary": (CLIPPED, 1),  # 6 of 14 rows cut: under half, still readable
    "help_clipped_half": (CLIPPED, 2),  # 10 of 14 rows cut: over half, no longer readable
    "badge_overlap": (OVERLAP, 1),  # a small badge covers a corner of CANCEL, its label clear
    "toast_over_help": (OVERLAP, 2),  # a notice covers the help line
    "toast_over_save": (OVERLAP, 3),  # a notice covers the SAVE CHANGES button
    "accent_colour": (None, None),  # benign: SAVE CHANGES is green instead of blue
    "timestamp_updated": (None, None),  # benign: the "last saved" time is a later time
}


def gold_label(changes: Iterable[str]) -> dict[str, Any]:
    """The gold label of a pair whose after screenshot shows ``changes``, read from ``CHANGES``.

    One boolean per category, and ``severity``: the level of each category that is present. A
    pair holds at most one change per category, so a category's severity is that change's
    level. An unlisted change, or two changes of one category, raises: a drawing nobody has
    labelled must not receive a default label.
    """
    label: dict[str, Any] = dict.fromkeys(CATEGORIES, False)
    severity: dict[str, int] = {}
    for name in changes:
        if name not in CHANGES:
            raise ValueError(f"{name!r} is not one of {sorted(CHANGES)}")
        category, level = CHANGES[name]
        if category is None:
            continue
        if label[category]:
            raise ValueError(f"two {category} changes in one pair")
        label[category] = True
        severity[category] = level
    label["severity"] = severity
    return label


def gold_verdict(label: Mapping[str, Any]) -> str:
    """``fail`` when any change in a gold label is at ``MAJOR`` or above, else ``pass``."""
    return FAIL if any(level >= MAJOR for level in label["severity"].values()) else PASS


def truth_combination(label: Mapping[str, Any]) -> tuple[bool, ...]:
    """The gold truth value of every proposition, in ``CATEGORIES`` order."""
    return tuple(bool(label[category]) for category in CATEGORIES)


def decisive_categories(label: Mapping[str, Any]) -> list[str]:
    """The categories whose gold tag alone changes the gold verdict of this label.

    A true tag is decisive when setting it false (and dropping its severity) turns ``fail``
    into ``pass``: no other change in the pair would fail it.
    """
    decisive = []
    for category in CATEGORIES:
        if not label[category]:
            continue
        rest = {c: v for c, v in label["severity"].items() if c != category}
        if gold_verdict({"severity": rest}) != gold_verdict(label):
            decisive.append(category)
    return decisive


def build_request(fields: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """``(state, assets)`` for one pair: what Jev sees and the images that go with it.

    ``fields`` names the two screenshots by paths relative to the recipe and also carries the
    pair identifier. Python keeps the identifier; the state holds only the two image references,
    each once. Two screenshots with the same bytes have the same reference, so ``assets`` then
    holds one image. Which changes were drawn, the gold label, is in no field: it stays in the
    fixture generator.
    """
    before = image_asset(fields["before"], root=ROOT)
    after = image_asset(fields["after"], root=ROOT)
    state = {"before": image_reference(before), "after": image_reference(after)}
    return state, {state["before"]: before, state["after"]: after}


# What each category means, in the words both questions about it use.
DESCRIPTIONS = {
    MISSING: "an element that is visible in `before` is not visible anywhere in `after`",
    MISALIGNED: (
        "an element in `after` sits in a different position from the same element in `before`, "
        "so it no longer lines up with the elements around it or with the field it labels"
    ),
    CLIPPED: (
        "text or a control in `after` is cut off at an edge, so part of it that `before` shows "
        "is no longer drawn"
    ),
    OVERLAP: (
        "an element in `after` is drawn on top of another element and covers part of it, which "
        "does not happen in `before`"
    ),
}
# Shared by every question: what the two images are, and what is not one of these changes.
CONTEXT = (
    "The `before` and `after` images are screenshots of the same settings page at the same "
    "size, taken before and after a code change. A different colour on its own, or a new value "
    "in text that is expected to change, such as a time, is not one of these changes."
)


def severity_key(category: str) -> str:
    """The name of the Score question about ``category``."""
    return f"{category}_severity"


def build_questions() -> dict[str, Any]:
    """The eight questions asked about every pair: one Noul and one Score per category.

    Each Noul is a statement that is true when its kind of change is there, so a high ``noul``
    means the change the code acts on is present. Each Score rates the most severe change of its
    kind on the rubric in ``LEVELS``. None of the eight needs another's answer to be built, so
    they share one request; Python ignores the Score of a category whose Noul is below its
    threshold.
    """
    questions: dict[str, Any] = {}
    for category in CATEGORIES:
        questions[category] = Noul(
            instructions=f"{CONTEXT} Comparing the two, {DESCRIPTIONS[category]}."
        )
    for category in CATEGORIES:
        questions[severity_key(category)] = Score(
            instructions=(
                f"{CONTEXT} Consider changes of this kind: {DESCRIPTIONS[category]}. How severe "
                "is the most severe change of this kind, judged by its effect on a person using "
                "the page?"
            ),
            criteria=list(LEVELS),
        )
    return questions


def severity_position(answer: Any) -> float:
    """A Score's ``score`` as a position from 0 (the first level) to 1 (the last).

    This is where the answer sits along the rubric, not a measured size: the cutoff that maps it
    to a verdict is chosen on ``validation`` and compared with it, nothing more.
    """
    return answer.score / (len(LEVELS) - 1)


def choose_noul_thresholds(
    results: Iterable[Mapping[str, Any]], golds: Iterable[Mapping[str, Any]]
) -> dict[str, float]:
    """One business threshold per category, chosen on validation by F1 and then frozen.

    The categories differ in how easy they are to see, so each gets its own threshold rather
    than one shared cut-off.
    """
    results, golds = list(results), list(golds)
    return {
        category: select_threshold(
            [g[category] for g in golds],
            [r[category].noul for r in results],
            objective="f1",
        )
        for category in CATEGORIES
    }


def choose_severity_cutoff(
    results: Iterable[Mapping[str, Any]], golds: Iterable[Mapping[str, Any]]
) -> float:
    """The severity position at or above which a change fails the comparison, chosen by F1.

    The pool is every change that is really there (gold true) in the split: its Score answer's
    position, and whether its gold level is ``MAJOR`` or above.
    """
    gold_fails, positions = [], []
    for result, gold in zip(results, golds, strict=True):
        for category in CATEGORIES:
            if gold[category]:
                gold_fails.append(gold["severity"][category] >= MAJOR)
                positions.append(severity_position(result[severity_key(category)]))
    return select_threshold(gold_fails, positions, objective="f1")


def detected_change_is_right(
    result: Mapping[str, Any], gold: Mapping[str, Any], category: str, cutoff: float
) -> bool:
    """Whether a detected change lands on the right side of the severity cutoff.

    Right means: the answer reaches the cutoff exactly when the change is really there and its
    gold level is ``MAJOR`` or above. A detected change that is not there is right only when its
    severity stays below the cutoff, where it cannot fail the pair.
    """
    fails = severity_position(result[severity_key(category)]) >= cutoff
    really = bool(gold[category]) and gold["severity"][category] >= MAJOR
    return fails == really


def choose_gate(
    results: Iterable[Mapping[str, Any]],
    golds: Iterable[Mapping[str, Any]],
    thresholds: Mapping[str, float],
    cutoff: float,
    *,
    target_accuracy: float,
) -> tuple[float | None, int]:
    """Freeze the severity confidence gate on validation, and count its candidates.

    The candidates are the detected changes (a Noul at or above its frozen threshold), because
    only their severity is ever read. ``None`` means no cutoff reaches ``target_accuracy``, and
    every detected change then goes to review.
    """
    right, confidence = [], []
    for result, gold in zip(results, golds, strict=True):
        for category in CATEGORIES:
            if result[category].noul >= thresholds[category]:
                right.append(detected_change_is_right(result, gold, category, cutoff))
                confidence.append(result[severity_key(category)].confidence)
    if not right:
        return None, 0
    try:
        gate = select_confidence_threshold(right, confidence, target_accuracy=target_accuracy)
    except ValueError as error:
        if str(error) != f"no threshold reaches accuracy {target_accuracy}":
            raise
        return None, len(right)
    return gate, len(right)


@dataclass(frozen=True)
class Policy:
    """The settings frozen on validation: a threshold per category, a cutoff and a gate."""

    thresholds: Mapping[str, float]
    cutoff: float
    gate: float | None


@dataclass(frozen=True)
class Detected:
    """One change Python reads as present, with what its Score said and what that is worth."""

    category: str
    noul: float
    level: int
    score: float
    confidence: float
    at_or_above_cutoff: bool
    confident: bool


@dataclass(frozen=True)
class Verdict:
    """What Python decided for one pair: ``pass``, ``fail`` or ``review``, with the reason.

    ``changes`` lists every detected change and is kept for a review too, so a person sees what
    triggered it.
    """

    pair: str
    kind: str
    reason: str
    changes: tuple[Detected, ...]
    result: Any = field(default=None, repr=False, compare=False)


def decide(pair: str, result: Mapping[str, Any], policy: Policy) -> Verdict:
    """Compose the eight answers about one pair into a verdict.

    A category counts as detected when its ``noul`` is at least its frozen threshold. No
    detected change is a pass. A detected change whose severity confidence is at least the gate
    is trusted, and a trusted change at or above the severity cutoff fails the pair whatever the
    others say. Otherwise any detected change that is not trusted sends the pair to review, and
    a pair whose detected changes are all trusted and all below the cutoff passes. A NaN
    confidence fails every comparison, so it is never trusted.
    """
    if policy.gate is not None and not 0.0 <= policy.gate <= 1.0:
        raise ValueError(f"the gate must be between 0 and 1, got {policy.gate!r}")
    if not 0.0 <= policy.cutoff <= 1.0:
        raise ValueError(f"the cutoff must be between 0 and 1, got {policy.cutoff!r}")
    changes = []
    for category in CATEGORIES:
        noul = result[category].noul
        if not noul >= policy.thresholds[category]:
            continue
        severity = result[severity_key(category)]
        confident = policy.gate is not None and severity.confidence >= policy.gate
        changes.append(
            Detected(
                category,
                noul,
                int(score_level(severity)),
                severity.score,
                severity.confidence,
                severity_position(severity) >= policy.cutoff,
                confident,
            )
        )
    changes = tuple(changes)
    if not changes:
        return Verdict(pair, PASS, "no predefined change detected", changes, result)
    if any(c.confident and c.at_or_above_cutoff for c in changes):
        reason = "a confident change at or above the severity cutoff"
        return Verdict(pair, FAIL, reason, changes, result)
    if policy.gate is None:
        return Verdict(pair, REVIEW, "no validated threshold", changes, result)
    if any(not c.confident for c in changes):
        return Verdict(pair, REVIEW, "confidence below the threshold", changes, result)
    reason = "every detected change is below the severity cutoff"
    return Verdict(pair, PASS, reason, changes, result)


def queue_reviews(queue: ReviewQueue, verdicts: Iterable[Verdict]) -> Routed:
    """Submit every verdict that is a review to ``queue`` with its reason; nothing else happens.

    A pass or a fail writes nothing: no log entry, no message and no change to any system. The
    queued item keeps the pair identifier and the detected categories with their severity levels.
    """
    return fill_review_queue(
        queue,
        verdicts,
        needs_review=lambda v: v.kind == REVIEW,
        item=lambda v: {
            "pair": v.pair,
            "changes": {c.category: LEVEL_NAMES[c.level] for c in v.changes},
        },
        reason=lambda v: v.reason,
        answer=lambda v: v.result,
        key=lambda v: v.pair,
    )


def open_image(path: str) -> Image.Image:
    """The image at ``path`` (relative to the recipe) as an RGB Pillow image."""
    with Image.open(resolve_asset_path(path, root=ROOT)) as picture:
        return picture.convert("RGB")


def pair_sheet(rows: Iterable[tuple[str, str, str]], *, width: int = 300) -> bytes:
    """PNG bytes of before-and-after pairs, one pair per row, each with its caption above.

    ``rows`` are ``(caption, before path, after path)``. The sheet is only for looking at in the
    notebook; nothing sent to Jev comes from it.
    """
    rows = list(rows)
    if not rows:
        raise ValueError("a pair sheet needs at least one pair")
    height = width * 3 // 4
    sheet = si.Canvas(2 * width + 24, max(280, len(rows) * (height + 24) + 8), "paper")
    for index, (caption, before, after) in enumerate(rows):
        top = index * (height + 24) + 4
        sheet.text(6, top, caption, "ink", 1)
        for column, path in enumerate((before, after)):
            picture = open_image(path)
            picture.thumbnail((width - 4, height))
            sheet.image.paste(picture, (column * (width + 12) + 6, top + 14))
    buffer = io.BytesIO()
    sheet.image.save(buffer, format="PNG")
    return buffer.getvalue()
