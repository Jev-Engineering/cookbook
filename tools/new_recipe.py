"""Create ``recipes/NN-slug/`` for recipe NN from ``catalog/recipes.json``.

    python tools/new_recipe.py 7                       # a replay recipe (the default)
    python tools/new_recipe.py 36 --mode scripted      # a scripted or simulator recipe
    python tools/new_recipe.py 77 --mode replay-images # a replay recipe whose requests carry images

The folder gets a skeleton that follows ``recipes/_template/``: the notebook sections in
order, a README, ``helpers.py``, ``build_fixtures.py``, ``side_effects.json`` (the recipe's
statement of its simulated side effects: a ``none`` placeholder to replace),
``request_budget.json`` (the declared live request count, one audited backend),
``tests/test_helpers.py`` and, for a replay recipe, ``tests/test_build_fixtures.py`` (the
refusal, inputs/labels-separation and writer-byte-identical guard tests; a scripted recipe has
no responses.json for them to guard).
The title, level, difficulty, decision types, use case and sources come from the catalog.
Everything the builder must write is marked ``TODO``, so ``grep -rn TODO recipes/NN-slug`` lists
what is left.
The command never overwrites: if the folder exists it stops with a message and exit status 1.

``--mode replay-images`` is the multimodal variant of replay (docs/vision.md). It writes the files
above and then runs the new folder's own ``build_fixtures.py`` once, which draws the example
images with ``jev_cookbook.synthetic_images`` and writes ``assets/``, ``assets-manifest.json`` and
``fixtures/``. This tool itself stays standard library only; that one step needs the installed
package and Pillow, which the scaffolded ``build_fixtures.py`` imports. If it fails, the folder is
removed and the command exits with status 1.

The scaffold is born on the audited request-count route (#213, #368): the notebook's one
``get_backend(...)`` is wrapped in ``AuditedBackend(..., label="main")``, a final standalone cell
prints ``backend.audit_json()``, and ``request_budget.json`` declares the one ``decide()`` call the
skeleton's own ``answer`` cell makes (``replay-images``: the ``decide()`` calls of its example
notebook, with the two image quantities of docs/backends.md) -- matching, out of the box, with no
hand-edit. The README's
``## Switch to live`` paragraph is rendered from that declaration, never hand-typed; as the builder
adds more ``decide()`` calls while writing Evaluation, ``request_budget.json`` and the rendered
paragraph are updated together (the README TODO there says how).

Standard library only. See docs/recipe-template.md for the walkthrough.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIRST, LAST = 1, 100  # ranks identify recipes; issue assignments are separate catalog fields
SLUG = re.compile(r"(?:[0-9]{2}|100)-[a-z0-9]+(?:-[a-z0-9]+)*")

# The notebook sections, in order. A test keeps this equal to the headings of the template.
SECTIONS = [
    "What you will build",
    "Setup and run mode",
    "The state",
    "The questions",
    "One answer up close",
    "Python's part",
    "Evaluation",
    "What was and was not measured",
    "Next steps",
]

TODO_MARK = "TODO"
# The run-mode paragraph every notebook's setup-md carries (#233). It is pinned byte for byte in
# the template and every published notebook by tests/test_run_mode_sentence.py, which also
# requires the scaffolded setup-md to carry it, so a new recipe starts with the true wording.
RUN_MODE_PARAGRAPH = (
    "Two labels may follow a number below. `(a pipeline check, not a Jev result)` marks a "
    "synthetic or scripted run; a recorded or live run does not print it, and its header says "
    "which mode ran. `(a selection step, not a reported result)` marks a line that is not a "
    "result to report, such as a number from `validation`, the split settings are chosen on, or "
    "a count of the items the frozen rule queues or would queue. A line with neither label, "
    "such as an individual answer or a per-example line, still comes from the mode the header "
    "names."
)
MODES = ("replay", "scripted")  # --mode; replay is the default and the one most recipes use
# --mode replay-images (docs/vision.md): replay, with images. It is a value of --mode rather than a
# separate flag so that no combination of options can ask for an image recipe that is not a replay
# recipe. MODES stays the two text modes: code that walks the text scaffolds (the tests, the recipe
# guard) keeps walking exactly those.
IMAGE_MODE = "replay-images"
ALL_MODES = (*MODES, IMAGE_MODE)

# The example the image scaffold ships, so that it runs end to end the moment it is written: an
# invented sign-in window (jev_cookbook.synthetic_images.login_screen) and two questions about it,
# "is an error banner shown?" (a Noul) and "where is it?" (a Box). TODO markers in the files that
# carry it say what to replace. One row per example:
#   (id, split, capture, screen state, drawing seed, probability of yes, the object Jev's
#    rectangle is drawn around, that rectangle's pixel offsets from the object (left, top, right,
#    bottom), the box confidence or None)
# The stored answers are deliberately imperfect: v05's rectangle overlaps the gold box by less than
# half (IoU 0.374), v06 and t05 answer yes about screens with no banner, t07 answers no about one
# with a banner, and t03's rectangle reports no confidence.
IMAGE_ROWS = (
    ("v01", "validation", "C-1001", "error", 11, 0.93, "error_banner", (0, 0, 0, 0), 0.90),
    ("v02", "validation", "C-1002", "error", 12, 0.88, "error_banner", (4, -2, -6, 2), 0.86),
    ("v03", "validation", "C-1003", "normal", 13, 0.06, "submit", (0, 0, 0, 0), 0.40),
    ("v04", "validation", "C-1004", "loading", 14, 0.12, "spinner", (0, 0, 0, 0), 0.35),
    ("v05", "validation", "C-1005", "error", 15, 0.64, "error_banner", (30, 10, -40, -8), 0.55),
    ("v06", "validation", "C-1006", "crash", 16, 0.58, "dialog", (0, 0, 0, 0), 0.30),
    ("t01", "test", "C-2001", "error", 21, 0.91, "error_banner", (0, 0, 0, 0), 0.92),
    ("t02", "test", "C-2002", "error", 22, 0.84, "error_banner", (10, 3, -12, -2), 0.90),
    ("t03", "test", "C-2003", "error", 23, 0.72, "error_banner", (4, -2, -6, 2), None),
    ("t04", "test", "C-2004", "normal", 24, 0.09, "submit", (0, 0, 0, 0), 0.45),
    ("t05", "test", "C-2005", "loading", 25, 0.81, "spinner", (0, 0, 0, 0), 0.93),
    ("t06", "test", "C-2006", "crash", 26, 0.45, "dialog", (0, 0, 0, 0), 0.38),
    ("t07", "test", "C-2007", "error", 27, 0.18, "error_banner", (0, 0, 0, 0), 0.50),
    ("d01", "demo", "C-3001", "error", 31, 0.90, "error_banner", (0, 0, 0, 0), 0.91),
)

# The audited request-count route (#213, #368): a recipe declares its live request count once, in
# request_budget.json, and the README's budget paragraph is rendered from it by
# jev_cookbook.accounting.render_budget_note -- never hand-typed. This tool stays standard-library
# only (see the module docstring), so request_budget_note below reproduces that renderer's exact
# output for the one shape a fresh scaffold ever declares (a single backend, no declared repeats,
# no at_most beyond requests) rather than importing jev_cookbook;
# tests/test_new_recipe.py::test_the_local_budget_renderer_and_default_cap_agree_byte_for_byte_with_the_shared_package
# calls the real jev_cookbook.accounting.render_budget_note directly and proves the two agree,
# byte for byte, so this cannot silently drift from the shared renderer.
BUDGET_FILE = "request_budget.json"
NOTE_BEGIN = "<!-- request-budget:begin -->"
NOTE_END = "<!-- request-budget:end -->"
# jev_cookbook.live.DEFAULT_MAX_REQUESTS; the same test named above pins this against the
# installed package so a change there cannot silently leave this copy stale.
DEFAULT_MAX_REQUESTS = 25


def request_budget_text(mode: str = "replay") -> str:
    """The scaffold's own ``request_budget.json``: the live request count declared once, matching
    exactly the one ``decide()`` call the skeleton notebook's ``answer`` cell makes (see
    ``notebook_cells``) -- so a fresh scaffold's declaration, audited notebook and rendered README
    paragraph already agree, with no hand-edit. ``fixtures`` is ``null`` for a scripted recipe
    (nothing to replay) and the recipe-relative replay file otherwise. ``replay-images`` is the
    exception to "one call": its example notebook decides each of ``IMAGE_ROWS`` once, so it
    declares that many requests and the two image quantities that go with them
    (docs/backends.md, "Actual calls and distinct requests"). As the builder adds
    ``decide()`` calls while writing Evaluation, this file's declared count (and ``distinct`` or
    ``at_most`` where they apply) must grow to match, and the README paragraph is regenerated from
    it -- the ``## Switch to live`` TODO in ``readme_text`` says how."""
    if mode == IMAGE_MODE:
        # The example notebook decides every example once, and each request carries one image
        # copy of one distinct image (the reference sits once in the state and in no
        # question), so the two image quantities of docs/backends.md equal the request count.
        count = len(IMAGE_ROWS)
        body = {
            "requests": count,
            "fixtures": "fixtures/responses.json",
            "profile": {"images": count, "distinct_images": count},
        }
        return json.dumps({"schema": 1, "backends": {"main": body}}, indent=2) + "\n"
    fixtures = None if mode == "scripted" else "fixtures/responses.json"
    body = {"requests": 1, "fixtures": fixtures}
    return json.dumps({"schema": 1, "backends": {"main": body}}, indent=2) + "\n"


def request_budget_note(requests: int) -> str:
    """The rendered ``## Switch to live`` paragraph, markers included, for a declaration of
    exactly ``requests`` on a single backend with no declared repeats and no ``at_most`` beyond
    ``requests`` -- the one shape ``request_budget_text`` ever declares at scaffold time. Byte for
    byte what ``jev_cookbook.accounting.render_budget_note`` returns for that shape (pinned, by a
    direct call to the real renderer, in
    ``tests/test_new_recipe.py::test_the_local_budget_renderer_and_default_cap_agree_byte_for_byte_with_the_shared_package``);
    kept here rather than imported, so this standard-library-only tool does not need the
    installed package to generate a recipe skeleton."""
    return (
        f"{NOTE_BEGIN}\n"
        f"In live mode this notebook makes exactly **{requests}** requests, each decided once. "
        f"Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS={requests}` or higher before running it live (the "
        f"default cap is {DEFAULT_MAX_REQUESTS}): the cap is inclusive and every attempt counts "
        "against it, retries included, so a lower cap stops the run partway through with "
        "`BudgetExceeded` and a run that retries needs more.\n"
        f"{NOTE_END}\n"
    )


class ScaffoldError(Exception):
    """A problem the user can fix; ``main`` prints it and exits with status 1."""


def _load_catalog(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ScaffoldError(f"catalog not found: {path}") from None
    except json.JSONDecodeError as error:
        raise ScaffoldError(f"catalog is not valid JSON ({path.name}): {error}") from None


def find_recipe(catalog: dict, number: int) -> dict:
    """The catalog entry whose ``rank`` is ``number``."""
    for recipe in catalog.get("recipes", []):
        if recipe.get("rank") == number:
            return recipe
    raise ScaffoldError(f"recipe {number} is not in the catalog")


# --------------------------------------------------------------------------- notebook


def _cell(kind: str, cell_id: str, source: str) -> dict:
    cell = {"cell_type": kind, "id": cell_id, "metadata": {}, "source": source.strip("\n")}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    return cell


def _source_lines(catalog: dict, recipe: dict) -> str:
    by_id = {s["id"]: s for s in catalog.get("sources", [])}
    lines = []
    for sid in recipe.get("sources", []):
        s = by_id.get(sid)
        lines.append(f"- {sid}: [{s['reference']}]({s['url']})" if s else f"- {sid}")
    return "\n".join(lines)


def notebook_cells(catalog: dict, recipe: dict, mode: str = "replay") -> list[dict]:
    """The skeleton notebook's cells, with the catalog fields filled in. ``mode`` is ``replay``
    (the backend replays ``fixtures/responses.json``), ``scripted`` (a seeded script in
    ``helpers.py`` answers, and there are no stored responses) or ``replay-images`` (replay, with
    images; see ``image_notebook_cells``)."""
    if mode == IMAGE_MODE:
        return image_notebook_cells(catalog, recipe)
    scripted = mode == "scripted"
    number = recipe["rank"]
    title = recipe["title"]
    types = " + ".join(f"`{t}`" for t in recipe["decision_types"])
    head = (
        f"# {title}\n\n"
        f"**Recipe {number:02d}** · Level {recipe['level']} ({recipe['difficulty']}) "
        f"· Decision type: {types}\n\n"
        f"{recipe['use_case']}\n\n"
        f"Sources:\n\n{_source_lines(catalog, recipe)}\n\n"
        f"## {SECTIONS[0]}\n\n"
        f"{TODO_MARK}: say in two or three sentences what the reader will have built by the end: "
        "the decision, what Jev is asked, what Python does with the answer."
    )

    def md(cell_id: str, text: str) -> dict:
        return _cell("markdown", cell_id, text)

    def code(cell_id: str, text: str) -> dict:
        return _cell("code", cell_id, text)

    if scripted:
        fixture_import = "from jev_cookbook.fixtures import load_inputs, load_labels"
        # Wrapped to fit pyproject.toml's line-length = 100: unwrapped, this line is 128
        # characters and `ruff format --check` (which also lints notebooks, extend-include =
        # ["*.ipynb"]) would reformat it on a freshly scaffolded recipe, failing both the
        # documented local check and the required Lint (ruff) CI job with no hand-edit.
        backend_line = (
            "backend = AuditedBackend(\n"
            '    get_backend(script=helpers.script, seed=helpers.SEED), label="main"\n'
            ")  # the seeded script in helpers.py"
        )
    else:
        fixture_import = (
            "from jev_cookbook.fixtures import load_inputs, load_labels, responses_path"
        )
        backend_line = (
            'backend = AuditedBackend(get_backend(fixtures=responses_path()), label="main")'
        )
    answers_how = (
        "computes its answers with a seeded script" if scripted else "replays synthetic answers"
    )
    setup_prose = (
        f"{TODO_MARK}: add the imports your later sections use (evaluation and plotting "
        "helpers), one sentence on the fixture set and its size."
    )
    if scripted:
        setup_prose += (
            f"\n\n{TODO_MARK}: say that a seeded script in `helpers.py` stands in for the model "
            "(there are no stored responses), so the run is a pipeline check."
        )

    return [
        md("intro", head),
        md(
            "setup-md",
            f"## {SECTIONS[1]}\n\n"
            "The notebook runs from its own folder with the standard library and `jev_cookbook` "
            "only. The header states which mode ran. "
            + RUN_MODE_PARAGRAPH
            + f" {TODO_MARK}: keep this paragraph as it is; define `selection` in the setup cell "
            "as `recipes/_template/` does, and print `{selection}{check}` on every `validation` "
            "number.\n\n" + setup_prose,
        ),
        code(
            "setup",
            f"""
from jev_cookbook import AuditedBackend, get_backend, load_helpers
{fixture_import}
from jev_cookbook.style import apply_style, run_header, show_answer

apply_style()
helpers = load_helpers()  # this recipe's helpers.py, loaded by path
examples = load_inputs()
labels = load_labels()
{backend_line}
# N for the header is the number of examples the metrics are about: the ones with a gold
# label, which excludes the demo examples.
scored = [e for e in examples if e.split not in ("train", "demo")]

offline = backend.mode in ("synthetic", "scripted")
check = " (a pipeline check, not a Jev result)" if offline else ""
run_header(
    {number},
    {json.dumps(title)},
    backend=backend,
    n_examples=len(scored),
)
""",
        ),
        md(
            "state-md",
            f"## {SECTIONS[2]}\n\n"
            f"{TODO_MARK}: say how Python builds the state from one input and what Jev sees. "
            "Name what Python keeps for itself (identifiers, amounts, permissions).",
        ),
        code(
            "state",
            """
demo = [e for e in examples if e.split == "demo"]
if not demo:
    raise ValueError("add at least one demo example to ROWS in build_fixtures.py")
example = demo[0]
state = helpers.build_state(example.fields)
print(state)
""",
        ),
        md(
            "questions-md",
            f"## {SECTIONS[3]}\n\n"
            f"{TODO_MARK}: one sentence per design choice: why this question type, who builds the "
            "options, why each outcome (`none`, `uncertain`) is there, how a multi-part judgment "
            "was split.",
        ),
        code(
            "questions",
            """
questions = helpers.build_questions()
for name, question in questions.items():
    print(name, question.to_dict())
""",
        ),
        md(
            "answer-md",
            f"## {SECTIONS[4]}\n\n"
            f"{TODO_MARK}: show one typed answer before any aggregate and say what its fields mean "
            "(choice and probabilities, noul value, score and distribution).",
        ),
        code(
            "answer",
            """
result = backend.decide(state, questions)
for answer in result.answers.values():
    show_answer(answer)
""",
        ),
        md(
            "python-md",
            f"## {SECTIONS[5]}\n\n"
            f"{TODO_MARK}: describe the rule in `helpers.py` that holds whatever the model "
            "answers, and the explicit review outcome for uncertain or inconsistent results. "
            "Then call it here.",
        ),
        code("python-rule", "# TODO: apply the rule from helpers.py to the example above"),
        md(
            "evaluation-md",
            f"## {SECTIONS[6]}\n\n"
            f"{TODO_MARK}: choose every setting on `validation`, freeze it, and report once on "
            "`test` with `jev_cookbook.evaluation`. In a synthetic or scripted run print each metric "
            "with `check` beside it; an individual example listed below a metric is not a "
            "metric and needs no label. Say which `validation` numbers your selection forces (see the "
            "template's evaluation section), or that none is. Compare with the baseline the "
            "issue names, if there is one.",
        ),
        code("evaluation", "# TODO: evaluate on validation, then report on test"),
        md(
            "measured-md",
            f"## {SECTIONS[7]}\n\n"
            f'{TODO_MARK}: while every answer is synthetic, keep this sentence: "Not measured '
            f"live: the offline run {answers_how}, so its numbers check the pipeline "
            'and say nothing about how Jev performs." For a recorded recipe, replace it with '
            "the model the API returned, the capture dates and N.\n\n"
            f"{TODO_MARK}: state the size of the fixture set and anything else this notebook "
            "does not show. Say nothing about Jev's quality, speed or cost.",
        ),
        code(
            "measured",
            """
if offline:
    print(f"Provenance: {backend.mode}. Not measured live: a pipeline check, not a Jev result.")
    print(f"N: {len(scored)} scored examples{check}")
else:
    dates = ", ".join(getattr(backend, "recorded_dates", ()) or ()) or "this run"
    print(f"Provenance: {backend.mode}, model {backend.model}")
    print(f"Captured: {dates}")
    print(f"N: {len(scored)} scored examples")  # TODO: and N for each reported metric
""",
        ),
        md(
            "audit-md",
            "### Live request audit\n\n"
            "The cell below is this notebook's final code cell, on purpose: "
            "`backend.audit_json()` prints an ordered ledger of every `decide()` call the "
            "backend above made. [`request_budget.json`](request_budget.json) declares this "
            "notebook's live request count once, and the recipe guard checks the ledger, the "
            "declaration and the README's rendered paragraph against each other "
            "([docs/backends.md](../../docs/backends.md#actual-calls-and-distinct-requests)). "
            "It holds no response content and says nothing about Jev's quality, speed or cost.",
        ),
        code("audit", "print(backend.audit_json())"),
        md(
            "next-md",
            f"## {SECTIONS[8]}\n\n"
            f"{TODO_MARK}: what to try next, and links to neighbouring recipes that already "
            "exist on `main`, by slug, for example [`NN-slug`](../NN-slug/). Link only a "
            "recipe whose notebook.ipynb is already committed: a folder link to one that is "
            "not yet published would 404 on GitHub, and a forward link like that is not "
            "allowed (docs/recipe-template.md).",
        ),
    ]


def image_notebook_cells(catalog: dict, recipe: dict) -> list[dict]:
    """The ``--mode replay-images`` notebook: the replay notebook's cells (so the intro, the
    run-mode paragraph, the ``questions``, ``measured`` and audit cells are the ones a replay
    recipe has), with the cells that touch images or a Box answer replaced, and one added.

    * ``setup`` turns the images header on (``get_backend(..., images=True)``), imports what the
      cells below use and defines ``selection``, because the cells below print ``validation``
      numbers;
    * ``state`` builds the request (state and assets) for the demo example and shows its image;
    * ``answer`` decides it with ``assets=`` and ``answer-boxes`` (added) draws the Box answer on
      the image with ``draw_boxes``;
    * ``python-rule`` freezes the presence and box-confidence thresholds on ``validation``;
    * ``evaluation`` reports the ``test`` split through ``localization_report``, and
      ``evaluation-review`` lists what Python did not locate and why.

    The example is marked ``TODO`` wherever it is the builder's to replace."""
    cells = notebook_cells(catalog, recipe, "replay")
    number, title = recipe["rank"], recipe["title"]

    def md(cell_id: str, text: str) -> dict:
        return _cell("markdown", cell_id, text)

    def code(cell_id: str, text: str) -> dict:
        return _cell("code", cell_id, text)

    replacements = {
        "setup-md": md(
            "setup-md",
            f"## {SECTIONS[1]}\n\n"
            "The notebook runs from its own folder with `jev_cookbook` and the packages it "
            "installs; Pillow reads and draws the images. The header states which mode ran. "
            + RUN_MODE_PARAGRAPH
            + f" {TODO_MARK}: keep this paragraph as it is; the setup cell defines `selection` "
            "and `check`, so print `{selection}{check}` on every `validation` number.\n\n"
            "The images are in `assets/`, drawn by `build_fixtures.py`; `assets-manifest.json` "
            "records where each came from ([docs/vision.md](../../docs/vision.md), "
            "[docs/fixtures.md](../../docs/fixtures.md#image-provenance-manifest)). "
            "`get_backend(..., images=True)` is the option that enables the experimental images "
            "request header in a live run; offline backends ignore it "
            "([docs/backends.md](../../docs/backends.md#get_backend)).\n\n"
            f"{TODO_MARK}: add the imports your later sections use, one sentence on the fixture "
            "set and its size, and what the images show.",
        ),
        "setup": code(
            "setup",
            f"""
from IPython.display import Image, display

from jev_cookbook import AuditedBackend, get_backend, load_helpers
from jev_cookbook.evaluation import noul_confidence, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split
from jev_cookbook.style import apply_style, run_header, show_answer
from jev_cookbook.vision import box_confidence, box_iou, draw_boxes, gold_box, localization_report

apply_style()
helpers = load_helpers()  # this recipe's helpers.py, loaded by path
examples = load_inputs()
labels = load_labels()
backend = AuditedBackend(get_backend(fixtures=responses_path(), images=True), label="main")
# scored excludes the demo example: it carries no gold label, so no metric below is about it.
scored = [e for e in examples if e.split not in ("train", "demo")]

offline = backend.mode in ("synthetic", "scripted")
check = " (a pipeline check, not a Jev result)" if offline else ""
# A number from the validation split is a selection step, not a result, in every run mode.
selection = " (a selection step, not a reported result)"

run_header(
    {number},
    {json.dumps(title)},
    backend=backend,
    n_examples=len(scored),
)
""",
        ),
        "state-md": md(
            "state-md",
            f"## {SECTIONS[2]}\n\n"
            f"{TODO_MARK}: say how Python builds the request from one example and what Jev sees: "
            "the fixture names the image by a path in `fields`, Python loads it with "
            "`image_asset(path, root=...)` and gives Jev a reference to its bytes, once, in the "
            "state. Name what Python keeps for itself (the capture identifier, the path, the gold "
            "label).",
        ),
        "state": code(
            "state",
            """
import json

demo = [e for e in examples if e.split == "demo"]
if not demo:
    raise ValueError("add at least one demo example to ROWS in build_fixtures.py")
example = demo[0]
print("Python has:")
print(json.dumps(example.fields, indent=2))
state, assets = helpers.build_request(example.fields)
print("Jev sees:")
print(json.dumps(state, indent=2))
display(Image(filename=helpers.ROOT / example.fields["image"]))
""",
        ),
        "answer-md": md(
            "answer-md",
            f"## {SECTIONS[4]}\n\n"
            f"{TODO_MARK}: show one image answer before any aggregate and say what its fields "
            "mean: the probability of yes for presence, and the rectangle's four edges "
            "(normalized to the image) with its confidence, which can be missing. A Box returns a "
            "rectangle even when the target is absent, so a returned rectangle cannot establish "
            "that the target exists.",
        ),
        "answer": code(
            "answer",
            """
result = backend.decide(state, questions, assets=assets)
for answer in result.answers.values():
    show_answer(answer)
""",
        ),
        "python-md": md(
            "python-md",
            f"## {SECTIONS[5]}\n\n"
            f"{TODO_MARK}: describe the rule in `helpers.py` that holds whatever the model "
            "answers (`locate`): a rectangle counts only after the presence question says the "
            "target is there, an uncertain presence answer or a rectangle without enough "
            "confidence goes to an explicit review outcome, and a review is never an absence. "
            "Say how each threshold is chosen on `validation` and frozen. Then apply it here.",
        ),
        "python-rule": code(
            "python-rule",
            """
val_examples = select_split(examples, "validation")
val_results = [
    backend.decide(state, questions, assets=assets)
    for state, assets in (helpers.build_request(e.fields) for e in val_examples)
]
val_gold = [labels[e.id] for e in val_examples]
# A yes is a probability above one half; only a call at or above the frozen threshold is acted on,
# so the threshold is the lowest confidence at which every call is right.
presence_right = [
    (r["present"].noul > 0.5) == (gold_box(g) is not None)
    for r, g in zip(val_results, val_gold, strict=True)
]
presence_threshold = select_confidence_threshold(
    presence_right, noul_confidence([r["present"].noul for r in val_results]), target_accuracy=1.0
)
# The same rule for the rectangle: among present targets whose rectangle has a confidence, a
# rectangle is right when its IoU with the gold box is at least one half.
sized = [
    (box_iou(gold_box(g), r["location"]) >= 0.5, box_confidence(r["location"]))
    for r, g in zip(val_results, val_gold, strict=True)
    if gold_box(g) is not None and box_confidence(r["location"]) is not None
]
box_threshold = select_confidence_threshold(
    [ok for ok, _ in sized], [c for _, c in sized], target_accuracy=1.0
)
print(f"presence threshold, frozen from here on: {presence_threshold:.2f}{selection}{check}")
print(f"box threshold, frozen from here on: {box_threshold:.2f}{selection}{check}")

shown = helpers.locate(
    example.fields["capture"],
    result["present"],
    result["location"],
    presence_threshold,
    box_threshold,
)
print(f"{shown.capture}: {shown.kind} ({shown.reason})")
""",
        ),
        "evaluation-md": md(
            "evaluation-md",
            f"## {SECTIONS[6]}\n\n"
            f"{TODO_MARK}: choose every setting on `validation` (above: the presence and box "
            "thresholds), freeze it, and report once on `test` through `localization_report`, "
            "which counts every example once and names each denominator. In a synthetic or "
            "scripted run print each metric with `check` beside it; an individual example listed "
            "below a metric is not a metric and needs no label. Say which `validation` numbers "
            "your selection forces, or that none is. Compare with the baseline the issue names, "
            "if there is one.",
        ),
        "evaluation": code(
            "evaluation",
            """
test_examples = select_split(examples, "test")
test_results = [
    backend.decide(state, questions, assets=assets)
    for state, assets in (helpers.build_request(e.fields) for e in test_examples)
]
test_gold = [labels[e.id] for e in test_examples]
test_outcomes = [
    helpers.locate(
        e.fields["capture"], r["present"], r["location"], presence_threshold, box_threshold
    )
    for e, r in zip(test_examples, test_results, strict=True)
]
report = localization_report(test_gold, [o.outcome for o in test_outcomes])
print(f"test, {len(test_examples)} examples, thresholds frozen{check}")
for line in str(report).splitlines():
    print(f"{line}{check}")
""",
        ),
    }
    out: list[dict] = []
    for cell in cells:
        out.append(replacements.get(cell["id"], cell))
        if cell["id"] == "answer":
            out.append(
                code(
                    "answer-boxes",
                    """
picture = helpers.open_image(example.fields["image"])
marked = draw_boxes(picture, {"Jev": result["location"]})
display(Image(data=helpers.png_bytes(marked), format="png"))
""",
                )
            )
        if cell["id"] == "evaluation":
            out.append(
                code(
                    "evaluation-review",
                    """
print("Test examples Python did not locate, and why:")
for item, decided in zip(test_examples, test_outcomes, strict=True):
    if decided.kind != "located":
        print(f"  {item.id}: {decided.kind} ({decided.reason})")
""",
                )
            )
    return out


def notebook_json(catalog: dict, recipe: dict, mode: str = "replay") -> str:
    notebook = {
        "cells": notebook_cells(catalog, recipe, mode),
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"


# ----------------------------------------------------------------------------- other files


def readme_text(catalog: dict, recipe: dict, mode: str = "replay") -> str:
    slug = recipe["slug"]
    scripted = mode == "scripted"
    run_note = (
        "The notebook runs from this folder with no network and no API key. A seeded script in "
        "`helpers.py` answers (there are no stored responses): see "
        "[docs/simulation.md](../../docs/simulation.md)."
        if scripted
        else "The notebook runs from this folder with no network and no API key, replaying "
        "`fixtures/`."
    )
    mode_line = (
        "scripted (offline, answers computed by a seeded script). Not measured live."
        if scripted
        else "synthetic (offline replay of hand-written answers). Not measured live."
    )
    closing = (
        "the offline run computes its answers with a seeded script written for this recipe, so "
        "its numbers check that the pipeline works."
        if scripted
        else "the offline run replays synthetic answers written for this recipe, so its numbers "
        "check that the pipeline works."
    )
    if mode == IMAGE_MODE:
        run_note = (
            "The notebook runs from this folder with no network and no API key, replaying "
            "`fixtures/` and reading the images in `assets/`. `build_fixtures.py` draws those "
            "images and writes `assets-manifest.json`, which records where each came from, its "
            "licence and what it is attested not to be "
            "([docs/fixtures.md](../../docs/fixtures.md#image-provenance-manifest)); "
            "[docs/vision.md](../../docs/vision.md) covers loading images and Box answers.\n\n"
            f"{TODO_MARK}: before you commit, recreate the images under the notebook constraints "
            "pin (the install in the paragraph below) with `python build_fixtures.py`: the PNG "
            "bytes are part of the replay key of each request that carries a picture, and the "
            "committed bytes are meant to be the ones "
            "that pin writes "
            "([docs/synthetic-images.md](../../docs/synthetic-images.md#byte-stability-and-regeneration))."
        )
        mode_line = (
            "synthetic (offline replay of hand-written answers about drawn images). "
            "Not measured live."
        )
        closing = (
            "the offline run replays synthetic answers written for this recipe, about images "
            "drawn for it, so its numbers check that the pipeline works."
        )
    types = " + ".join(f"`{t}`" for t in recipe["decision_types"])
    return f"""# {recipe["title"]}

**Recipe {recipe["rank"]:02d}** · Level {recipe["level"]} ({recipe["difficulty"]}) · Decision type: {types}

{recipe["use_case"]}

## What it teaches

{TODO_MARK}: two or three sentences: the decision, what Jev is asked, what Python owns.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/{slug}
python tools/execute_notebook.py recipes/{slug}
pytest recipes/{slug}
```

{run_note}

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — `.[dev]` above is for `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline.

{request_budget_note(json.loads(request_budget_text(mode))["backends"]["main"]["requests"]).rstrip()}

{TODO_MARK}: this paragraph is generated from `request_budget.json`, next to this notebook, by
`jev_cookbook.accounting.render_recipe_note`; never edit it by hand. As you add `decide()` calls
while you write Evaluation, update `request_budget.json`'s declared count to match (and its
`distinct` or `at_most` if some requests repeat on purpose or the count depends on an answer).
Then regenerate this block with the one-line command below, copied exactly:
`python -c "from jev_cookbook.accounting import render_recipe_note as r; print(r('recipes/{slug}'), end='')"`
Its output already carries both marker comments, so replace the whole block, those two lines
included, with it before you finish. The recipe guard compares the declaration, the notebook's
audited execution and this paragraph against each other. Never put a key in a notebook or a
fixture.

## What was and was not measured

- **Mode:** {mode_line}
- **Model, capture date:** not applicable while every answer is synthetic.
  {TODO_MARK}: if this recipe records real inference, replace the mode, model and date lines
  with the mode (`recorded` or `live`), the model the API returned, and the capture date or
  dates; state N for every reported metric. Leave them as they are for a synthetic recipe.
- **N:** {TODO_MARK}: the number of scored examples per split (the `demo` examples are not scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

{TODO_MARK}: while every answer is synthetic, keep this: {closing} For a recorded recipe,
replace it with the model, the capture dates and N. Then state what the evaluation covers.

## Pull request rules

This recipe's pull request changes only `recipes/{slug}/`. The root `README.md` is generated; per
the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by
a separate pull request, and this recipe's own builder never runs the renderer. While this recipe
remains unpublished and that integration step has not yet run, `Catalog (README is current)` is
expected to be red on its pull request, which is not a defect to fix here; once the catalog is
regenerated for it, the check turns green and stays that way. No sentence anywhere in this
folder states or implies Jev's real quality, latency, or cost: every number above is a synthetic
pipeline check (see the {TODO_MARK} markers above). The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

{_source_lines(catalog, recipe)}
"""


def helpers_text(recipe: dict, mode: str = "replay") -> str:
    if mode == IMAGE_MODE:
        return image_helpers_text(recipe)
    script_block = ""
    if mode == "scripted":
        script_block = f'''

SEED = 0  # {TODO_MARK}: the backend seed, committed so the run is reproducible


def script(state, questions, rng):
    """Stand in for the model: return {{question name: spec}} for one request.

    A spec is an option name or {{option: weight}} for a Choice, a probability of yes for a
    Noul, and a list of weights for a Score. Use only ``rng.random()`` for chance, never the
    global ``random`` or the clock: the same request must always give the same answer.
    """
    raise NotImplementedError("{TODO_MARK}: answer from the state, deliberately imperfect")
'''
    return f'''"""Python's half of recipe {recipe["rank"]:02d}: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from typing import Any

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.


def build_state(fields: dict[str, Any]):
    """The state Jev sees for one example. Keep identifiers and other Python-owned values out."""
    raise NotImplementedError("{TODO_MARK}: build the state from the example's fields")


def build_questions():
    """The questions asked about every example. Python builds option lists and criteria."""
    raise NotImplementedError("{TODO_MARK}: return {{name: Choice | Noul | Score}}")
{script_block}

# {TODO_MARK}: the rule or rules Python enforces whatever the model answers, with tests.
'''


def rows_hint(level: int) -> str:
    """How many examples to write, from the contract: tens at levels 1 and 2, and at every level
    the size is stated wherever a number is reported."""
    if level <= 2:
        return f"tens of examples (about twenty) at level {level}"
    return (
        f"as many examples as level {level} needs to show its hard cases, small enough to read; "
        "state the size wherever a number is reported"
    )


def build_fixtures_text(recipe: dict, mode: str = "replay") -> str:
    if mode == IMAGE_MODE:
        return image_build_fixtures_text(recipe)
    if mode == "scripted":
        return build_scripted_fixtures_text(recipe)
    return f'''"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe {recipe["rank"]:02d}.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic and deliberately imperfect: include some wrong answers and the
hard cases the use case names. See docs/fixtures.md and recipes/_template/build_fixtures.py.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from ROWS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, Provenance, dump_responses, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# (id, split, fields, gold label or None for a demo example, how the stored answer is written)
ROWS = []  # {TODO_MARK}: {rows_hint(recipe["level"])}, across validation and test


def answers_for(spec, provenance: Provenance):
    """{{question name: answer}} for one row, for example ChoiceAnswer.from_probabilities(...)."""
    raise NotImplementedError("{TODO_MARK}: build the typed answers from the row's spec")


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, label, _spec in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({{"id": ident, "split": split, "fields": fields, "replay_keys": [key]}})
        if label is not None:
            labels.append({{"id": ident, "label": label}})
    return inputs, labels


def build_responses(rows):
    """``{{replay_key: stored response}}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {{}}
    for _ident, _split, fields, _label, spec in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(spec, Provenance.synthetic())
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def _is_recorded(path: Path) -> bool:
    """True if ``path`` exists and holds at least one response whose model is not
    ``"synthetic"`` (a recorded, or otherwise real, answer). A file that fails to parse, or
    whose top level is not a JSON object, cannot hold a valid synthetic response either, so it
    is treated as not recorded rather than raising; inside an object, an entry that is itself
    not an object is treated as if it were recorded, so it blocks an overwrite instead of being
    silently skipped."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return any(
        not isinstance(entry, dict) or entry.get("model") != "synthetic" for entry in data.values()
    )


def _unresolved_keys(inputs, responses_file: Path) -> list[str]:
    """Replay keys the just-rewritten ``inputs`` ask for that ``responses_file`` does not have,
    used only to warn when a ROWS edit has desynchronised the two."""
    if not responses_file.exists():
        return []
    try:
        data = json.loads(responses_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    return [key for row in inputs for key in row["replay_keys"] if key not in data]


def main() -> None:
    parser = argparse.ArgumentParser(description="Write this recipe's fixtures/.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite responses.json even if it holds a recorded (non-synthetic) answer",
    )
    args = parser.parse_args()
    if not ROWS:
        raise SystemExit("{TODO_MARK}: add examples to ROWS in build_fixtures.py")
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\\n" for row in rows)
        (folder / name).write_text(text, encoding="utf-8", newline="\\n")
    responses_file = folder / "responses.json"
    if _is_recorded(responses_file) and not args.force:
        message = (
            f"refusing to overwrite {{responses_file}}: it holds a recorded response "
            "(pass --force to overwrite it anyway)"
        )
        if _unresolved_keys(inputs, responses_file):
            message += (
                "\\ninputs.jsonl and labels.jsonl above were rewritten from ROWS; "
                "responses.json was not, and at least one of the keys the rewritten inputs "
                "ask for is missing from it. The three files are desynchronised until you "
                "--force a rewrite or record the missing answers."
            )
        raise SystemExit(message)
    responses = build_responses(ROWS)
    # dump_responses is the serialization the recorder writes with (top-level keys sorted, each
    # response keeping the field order DecisionResult.to_dict() emits), so a recording's diff
    # stays limited to the values that actually changed.
    responses_file.write_text(dump_responses(responses), encoding="utf-8", newline="\\n")
    print(f"wrote {{len(inputs)}} examples, {{len(labels)}} labels, {{len(responses)}} responses")


if __name__ == "__main__":
    main()
'''


def side_effects_text() -> str:
    """The ``side_effects.json`` every scaffold starts with: a ``none`` declaration whose reason is
    a ``TODO`` placeholder. The recipe guard (``simulated_side_effect_invoked`` in
    ``tests/test_recipe_guard.py``) rejects a reason that still carries the marker, so the file
    cannot be forgotten, and rejects ``none`` outright for a recipe that has a simulated side
    effect or needs a simulator, so the placeholder cannot stand in for a real declaration
    either. Schema and keys: docs/simulation.md."""
    reason = (
        f"{TODO_MARK}: say why this recipe has no simulated side effect (nothing is queued, "
        "logged or stored), or replace the whole file with a sites declaration: the exact "
        "number of places the notebook calls each side-effect function (docs/simulation.md, "
        "Declaring the side effect)"
    )
    return json.dumps({"schema": 1, "none": reason}, indent=2) + "\n"


def build_scripted_fixtures_text(recipe: dict) -> str:
    """A scripted recipe has nothing to replay: ``replay_keys`` are empty and there is no
    ``responses.json`` (docs/fixtures.md, "Replay and scripted recipes")."""
    return f'''"""Write fixtures/inputs.jsonl and labels.jsonl for recipe {recipe["rank"]:02d} (scripted).

    python build_fixtures.py        # from anywhere; it writes next to this file

A scripted recipe has nothing to replay: every example has empty ``replay_keys`` and there is no
responses.json, because ``helpers.script`` answers (see docs/simulation.md and
docs/fixtures.md, "Replay and scripted recipes").
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (id, split, fields, gold label or None for a demo example)
ROWS = []  # {TODO_MARK}: {rows_hint(recipe["level"])}, across validation and test


def main() -> None:
    if not ROWS:
        raise SystemExit("{TODO_MARK}: add examples to ROWS in build_fixtures.py")
    inputs, labels = [], []
    for ident, split, fields, label in ROWS:
        inputs.append({{"id": ident, "split": split, "fields": fields, "replay_keys": []}})
        if label is not None:
            labels.append({{"id": ident, "label": label}})
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\\n" for row in rows)
        (folder / name).write_text(text, encoding="utf-8", newline="\\n")
    (folder / "responses.json").unlink(missing_ok=True)  # a scripted recipe has none
    print(f"wrote {{len(inputs)}} examples and {{len(labels)}} labels")


if __name__ == "__main__":
    main()
'''


def tests_text(recipe: dict, mode: str = "replay") -> str:
    # The scaffolder knows the mode when it writes this file, so each mode gets only the
    # replay-key test that applies to it: a replay recipe never defines helpers.script or
    # helpers.SEED, so a scripted branch in its test file would be dead code, copied sixty times.
    if mode == IMAGE_MODE:
        return _fill(IMAGE_TESTS, recipe)
    if mode == "scripted":
        return f'''"""Tests for recipe {recipe["rank"]:02d}'s helpers. They load the helpers by file path."""

from pathlib import Path

from jev_cookbook import ScriptedBackend, load_helpers
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def test_questions_are_built_by_python():
    # {TODO_MARK}: assert the option lists and criteria against literal expected values (not
    # helpers' own data, which would make the assertion self-referential), then test every rule
    # in helpers.py
    assert helpers.build_questions()


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # A scripted recipe replays nothing: no example lists a key, and helpers.script must give
    # the same answer to the same request every time (a fresh backend each time, same seed).
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == ()
        state = helpers.build_state(example.fields)
        first = ScriptedBackend(helpers.script, helpers.SEED).decide(state, questions)
        second = ScriptedBackend(helpers.script, helpers.SEED).decide(state, questions)
        assert first.to_dict() == second.to_dict()
'''
    return f'''"""Tests for recipe {recipe["rank"]:02d}'s helpers. They load the helpers by file path."""

from pathlib import Path

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import score_level, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def test_questions_are_built_by_python():
    # {TODO_MARK}: assert the option lists and criteria against literal expected values (not
    # helpers' own data, which would make the assertion self-referential), then test every rule
    # in helpers.py
    assert helpers.build_questions()


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example;
    # adapt this when an example needs a dependent second request (CONTRIBUTING: a question that
    # depends on an earlier answer goes in a later request), where the example lists a key for
    # each request in order.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if a confidence gate
    # caught every mistake. Mirror your notebook's own threshold selection here, including any
    # filter on which answers can set the bar (the lowest confidence at which every validation
    # answer *that counts* is right -- an unfiltered selection over every validation answer can
    # choose a different, usually lower, threshold than your notebook's own one does), and
    # require a wrong `test` answer at or above it: a mistake the gate would still let through,
    # which is what evaluating on `test` exists to catch. Adapt `predicted`/`confidence` below
    # for a question with no native confidence (a Noul: use
    # jev_cookbook.evaluation.noul_confidence(answer.noul) in place of answer.confidence), or
    # repeat this per question when more than one needs the check.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    name = next(iter(questions))
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)[name]

    def predicted(answer):
        # A Score's own gold label is a level, so compare against score_level(answer) (the
        # most probable level), never answer.score (the probability-weighted expected value,
        # which is a float that almost never equals an integer gold level).
        return answer.choice if hasattr(answer, "choice") else score_level(answer)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {{e.id: decide(e) for e in validation}}
    correct = [predicted(val_answers[e.id]) == labels[e.id] for e in validation]
    confidence = [val_answers[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id
        for e in test
        if predicted(decide(e)) != labels[e.id] and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
'''


def build_fixtures_test_text(recipe: dict, mode: str = "replay") -> str:
    """Guard tests for ``build_fixtures.py`` (replay modes only; a scripted recipe has no
    ``responses.json`` and nothing for these tests to guard, see ``build_scripted_fixtures_text``):
    refusal without ``--force``, ``inputs.jsonl``/``labels.jsonl`` regenerated from ``ROWS`` even
    on a refused run, and the committed ``responses.json`` byte-identical to what
    ``jev_cookbook.live``'s recorder would write. See
    ``recipes/_template/tests/test_build_fixtures.py``, which this follows.

    ``mode="replay-images"`` returns the variant for a recipe with ``assets/``: the temporary
    copy it rebuilds in also holds the committed images (their bytes are part of the replay
    key of each request that carries them), and it adds the checks that the images and ``assets-manifest.json`` are reproduced and
    that a changed picture is refused. A recipe that has ``assets/`` commits this variant; called
    with one argument, the function returns the text variant."""
    if mode == IMAGE_MODE:
        return _fill(IMAGE_BUILD_FIXTURES_TEST, recipe)
    slug = recipe["slug"]
    module_name = f"recipe{recipe['rank']:02d}_build_fixtures_for_test"
    return f'''"""build_fixtures.py follows the recipes/_template/build_fixtures.py pattern: inputs and
labels generation is separate from responses generation, a recorded responses.json is never
silently overwritten, and the committed file matches jev_cookbook.live's writer exactly."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from jev_cookbook import dump_responses

RECIPE = Path(__file__).resolve().parent.parent
SCRIPT = RECIPE / "build_fixtures.py"


def load_module_at(path, name):
    """Import build_fixtures.py by file path so its functions and module-level values (ROWS,
    build_responses) are plain Python objects, not subprocess output or a re-dump of the file
    it wrote."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jsonl(rows):
    return "".join(json.dumps(row) + "\\n" for row in rows)


def test_the_committed_responses_are_byte_identical_to_the_recorders_writer():
    """jev_cookbook.dump_responses sorts only the top-level keys; json.dumps(..., sort_keys=True)
    sorts every nested dict too and so disagrees with it on every response's field order. The
    committed file must match dump_responses exactly, not just agree with it on top-level order.

    Comparing against dump_responses(json.loads(raw)) (re-dumping the file's own parsed content)
    cannot catch a sort_keys=True regression: json.loads preserves whatever nested order the file
    already has, and dump_responses only re-sorts the top level, so that round trip would pass no
    matter which writer produced the file. Instead, import build_fixtures.py and compare against
    dump_responses of what build_responses computes directly from ROWS, independent of what
    main() actually wrote to disk."""
    raw = (RECIPE / "fixtures" / "responses.json").read_text("utf-8")
    module = load_module_at(SCRIPT, "{module_name}")
    assert len(module.ROWS) > 1
    assert raw == dump_responses(module.build_responses(module.ROWS))


def test_build_fixtures_separates_inputs_labels_from_responses(tmp_path):
    """Mutation check: regenerating must never silently overwrite a recorded responses.json,
    and --force must restore the exact synthetic bytes. inputs.jsonl and labels.jsonl are
    rewritten from ROWS on every run, refused or not: only responses.json is guarded, and this
    also proves it by corrupting both files before the refused run and checking that they come
    back exactly as build_inputs_and_labels(ROWS) computes them, not merely "changed"."""
    copy = tmp_path / "{slug}"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    script = copy / "build_fixtures.py"
    first = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr

    responses = copy / "fixtures" / "responses.json"
    data = json.loads(responses.read_text("utf-8"))
    for value in data.values():
        value["model"] = "jev-1.13.0"
    responses.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\\n", encoding="utf-8", newline="\\n"
    )
    before = responses.read_bytes()

    inputs_path = copy / "fixtures" / "inputs.jsonl"
    labels_path = copy / "fixtures" / "labels.jsonl"
    inputs_path.write_bytes(b"corrupted")
    labels_path.write_bytes(b"corrupted")

    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert responses.read_bytes() == before
    module = load_module_at(script, "{module_name}_refused")
    expected_inputs, expected_labels = module.build_inputs_and_labels(module.ROWS)
    assert inputs_path.read_text("utf-8") == _jsonl(expected_inputs)
    assert labels_path.read_text("utf-8") == _jsonl(expected_labels)

    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True
    )
    assert forced.returncode == 0, forced.stderr
    after = json.loads(responses.read_text("utf-8"))
    assert all(v["model"] == "synthetic" for v in after.values())


def test_the_generator_reproduces_the_committed_fixtures(tmp_path):
    copy = tmp_path / "{slug}"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    done = subprocess.run(
        [sys.executable, str(copy / "build_fixtures.py")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    for name in ("inputs.jsonl", "labels.jsonl", "responses.json"):
        assert (copy / "fixtures" / name).read_bytes() == (RECIPE / "fixtures" / name).read_bytes()
'''


# ------------------------------------------------------------------------ the image variant
#
# The three files below (and the image tests after them) are written from plain templates with
# @TOKEN@ placeholders rather than f-strings: they are full of braces and backslashes, and a
# generated file must read exactly as written here.

IMAGE_HELPERS = r'''"""Python's half of recipe @RANK@: the request Jev sees, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the images, the questions and the rules come from one place.

@TODO@: the example below asks whether an invented sign-in window shows an error banner, and where.
Replace the questions, the request and the rule with your recipe's, and keep the pattern. A path
read from a fixture is data, so an image is loaded with ``image_asset(path, root=ROOT)``; its
reference comes from its bytes; the reference goes into the state once, because every place it
appears adds another copy of the image to the request (docs/vision.md); and a rectangle counts
only after a presence question says the target is there.
"""

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from jev_cookbook import Box, Noul
from jev_cookbook.evaluation import noul_confidence
from jev_cookbook.vision import (
    box_confidence,
    image_asset,
    image_reference,
    normalized_box,
    resolve_asset_path,
)

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The recipe folder. The image paths in fixtures/inputs.jsonl are relative to it.
ROOT = Path(__file__).resolve().parent

LOCATED, ABSENT, REVIEW = "located", "absent", "review"  # what localization_report counts


def build_request(fields: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """``(state, assets)`` for one example: what Jev sees and the images that go with it.

    ``fields`` names the image by a path relative to the recipe and also carries the capture
    identifier. Python keeps the identifier and attaches it to the outcome, so it never needs to
    pass through the model. The state holds only the image's reference.
    """
    asset = image_asset(fields["image"], root=ROOT)
    reference = image_reference(asset)
    return {"screenshot": reference}, {reference: asset}


def build_questions() -> dict[str, Any]:
    """The questions asked about every example: is the target there, and where is it?"""
    return {
        "present": Noul(instructions="The sign-in window in `screenshot` shows an error banner."),
        "location": Box(instructions="The error banner in the sign-in window in `screenshot`."),
    }


def open_image(path: str) -> Image.Image:
    """The image at ``path`` (relative to the recipe) as an RGB Pillow image to draw on."""
    with Image.open(resolve_asset_path(path, root=ROOT)) as picture:
        return picture.convert("RGB")


def png_bytes(image: Image.Image) -> bytes:
    """``image`` as PNG bytes, for ``IPython.display.Image(data=..., format="png")``."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass(frozen=True)
class Localized:
    """What Python decided: a rectangle, an absence, or a review, with the reason."""

    capture: str
    kind: str
    box: dict[str, float] | None
    reason: str

    @property
    def outcome(self) -> tuple[str, dict[str, float] | None]:
        """The pair ``jev_cookbook.vision.localization_report`` takes for this example."""
        return (self.kind, self.box)


def locate(
    capture: str,
    presence: Any,
    location: Any,
    presence_threshold: float,
    box_threshold: float,
) -> Localized:
    """Accept a rectangle only when the presence answer is confident and says the target is there.

    ``presence`` is the Noul answer and ``location`` the Box answer. A presence answer whose
    confidence is below ``presence_threshold`` goes to review, not to absent. Otherwise a
    probability of yes above one half means the target is there, and anything else means it is
    not (the Box's rectangle is then ignored). A present target is located only when its
    rectangle carries a confidence of at least ``box_threshold``; a rectangle with no confidence
    or a lower one goes to review. The rule is code, so it holds whatever the model answers.
    """
    for name, value in (
        ("presence_threshold", presence_threshold),
        ("box_threshold", box_threshold),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1, got {value!r}")
    if noul_confidence([presence.noul])[0] < presence_threshold:
        return Localized(capture, REVIEW, None, "presence confidence below the threshold")
    if presence.noul <= 0.5:
        return Localized(capture, ABSENT, None, "no error banner")
    confidence = box_confidence(location)
    if confidence is None:
        return Localized(capture, REVIEW, None, "the rectangle has no confidence")
    if confidence < box_threshold:
        return Localized(capture, REVIEW, None, "rectangle confidence below the threshold")
    return Localized(capture, LOCATED, normalized_box(location), "confident rectangle")


# @TODO@: the other rules Python enforces whatever the model answers, with tests.
'''

IMAGE_BUILD_FIXTURES = r'''"""Write assets/, assets-manifest.json and fixtures/ for recipe @RANK@.

    python build_fixtures.py                     # from anywhere; it writes next to this file
    python build_fixtures.py --force             # also overwrite a responses.json holding a recorded answer
    python build_fixtures.py --overwrite-assets  # accept a picture that changed (replay keys change too)

The images are drawn here with jev_cookbook.synthetic_images (docs/synthetic-images.md): no
photograph, brand, person or third-party picture, and the gold Box label of each is derived from
what was drawn, not typed in. The responses are synthetic and deliberately imperfect. The replay
keys come from the same ``build_request`` and ``build_questions`` the notebook uses, and cover the
images' bytes. See docs/fixtures.md and docs/vision.md.

@TODO@: the sign-in windows, the two questions and the answers below are an example. Replace them
with your recipe's images (draw them with ``jev_cookbook.synthetic_images`` primitives, or give
``canvas.provenance("build_fixtures.py:your_function", {...})`` to a scene of your own so the
manifest names a generator that exists here), and keep ROWS' split names and demo example.

Images are saved under the byte policy of docs/synthetic-images.md. Their bytes are part of the
replay key of each request that carries them, so if a regenerated picture differs from the file that is already there this script
stops and writes nothing more, unless ``--overwrite-assets`` accepts the change.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from ROWS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import (
    BoxAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    dump_responses,
    load_helpers,
    replay_key,
)
from jev_cookbook import synthetic_images as si

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

TARGET = "error_banner"  # the drawn object whose rectangle is the gold box, when the screen has it

# (id, split, capture, screen state, drawing seed, probability of yes, the drawn object Jev's
# rectangle is around, that rectangle's pixel offsets from the object (left, top, right, bottom),
# the rectangle's confidence or None for a Box answer that reports none)
ROWS = [
@ROWS@
]  # @TODO@: your examples, across validation and test, and at least one demo


def image_path(ident):
    """Where the image of example ``ident`` is saved, relative to the recipe."""
    return f"assets/screen-{ident}.png"


def draw(row):
    """The canvas of one row. ``login_screen`` is a shared scene, so the manifest entry names it
    as the generator and ``si.check_reproducible`` can redraw it from the entry."""
    _ident, _split, _capture, state, seed, *_answer = row
    return si.login_screen(state=state, seed=seed)


def write_images(rows, overwrite):
    """Draw and save every image under the byte policy; return the manifest entries by path.

    Raises ``si.RegenerationMismatch`` (and saves nothing more) for a picture that differs from
    the committed file, unless ``overwrite`` is true."""
    entries = []
    for row in rows:
        path = image_path(row[0])
        canvas = draw(row)
        status = canvas.write(HERE, path, overwrite=overwrite)
        print(f"{status}: {path}")
        description = f"An invented sign-in window in the {row[3]!r} state (seed {row[4]})."
        entries.append(canvas.manifest_entry(HERE, path, description))
    return sorted(entries, key=lambda entry: entry["path"])


def _fields(row):
    return {"capture": row[2], "image": image_path(row[0])}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``, with the images already saved. Neither ever holds a
    model's answer, so both are always safe to regenerate, even after ``responses.json`` has
    been recorded. A gold Box label is derived from what was drawn."""
    inputs, labels = [], []
    for row in rows:
        ident, split = row[0], row[1]
        fields = _fields(row)
        state, assets = helpers.build_request(fields)
        key = replay_key(state, QUESTIONS, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if split != "demo":
            drawn = draw(row).objects.get(TARGET)
            labels.append({"id": ident, "label": drawn.label() if drawn else si.absent_label()})
    return inputs, labels


def answers_for(row, provenance: Provenance):
    """{question name: answer} for one row: the presence probability and a rectangle around the
    object ``row`` names, moved by its offsets (the rectangle a model returns even when the
    target is absent)."""
    _ident, _split, _capture, _state, _seed, p_yes, shown, offsets, confidence = row
    canvas = draw(row)
    width, height = canvas.size
    left, top, right, bottom = (
        edge + offset for edge, offset in zip(canvas.objects[shown].pixels, offsets, strict=True)
    )
    box = {
        "top": top / height,
        "bottom": bottom / height,
        "left": left / width,
        "right": right / width,
    }
    return {
        "present": NoulAnswer(p_yes, provenance),
        "location": BoxAnswer(box, confidence, provenance),
    }


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``, with the images already saved. Always
    synthetic: this script never calls Jev, so it can never produce a recorded response."""
    responses = {}
    for row in rows:
        state, assets = helpers.build_request(_fields(row))
        key = replay_key(state, QUESTIONS, assets=assets)
        answers = answers_for(row, Provenance.synthetic())
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def _is_recorded(path: Path) -> bool:
    """True if ``path`` exists and holds at least one response whose model is not
    ``"synthetic"`` (a recorded, or otherwise real, answer). A file that fails to parse, or
    whose top level is not a JSON object, cannot hold a valid synthetic response either, so it
    is treated as not recorded rather than raising; inside an object, an entry that is itself
    not an object is treated as if it were recorded, so it blocks an overwrite instead of being
    silently skipped."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return any(
        not isinstance(entry, dict) or entry.get("model") != "synthetic" for entry in data.values()
    )


def _unresolved_keys(inputs, responses_file: Path) -> list[str]:
    """Replay keys the just-rewritten ``inputs`` ask for that ``responses_file`` does not have,
    used only to warn when a ROWS edit has desynchronised the two."""
    if not responses_file.exists():
        return []
    try:
        data = json.loads(responses_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    return [key for row in inputs for key in row["replay_keys"] if key not in data]


def main() -> None:
    parser = argparse.ArgumentParser(description="Write this recipe's assets/ and fixtures/.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite responses.json even if it holds a recorded (non-synthetic) answer",
    )
    parser.add_argument(
        "--overwrite-assets",
        action="store_true",
        help="accept an image that differs from the committed file (its replay keys change)",
    )
    args = parser.parse_args()
    if not ROWS:
        raise SystemExit("@TODO@: add examples to ROWS in build_fixtures.py")
    try:
        entries = write_images(ROWS, args.overwrite_assets)
    except si.RegenerationMismatch as error:
        raise SystemExit(f"refused: {error}\nnothing else was written") from None
    manifest = {"schema": 1, "assets": entries}
    (HERE / "assets-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\n" for row in rows)
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    responses_file = folder / "responses.json"
    if _is_recorded(responses_file) and not args.force:
        message = (
            f"refusing to overwrite {responses_file}: it holds a recorded response "
            "(pass --force to overwrite it anyway)"
        )
        if _unresolved_keys(inputs, responses_file):
            message += (
                "\ninputs.jsonl and labels.jsonl above were rewritten from ROWS; "
                "responses.json was not, and at least one of the keys the rewritten inputs "
                "ask for is missing from it. The three files are desynchronised until you "
                "--force a rewrite or record the missing answers."
            )
        raise SystemExit(message)
    responses = build_responses(ROWS)
    # dump_responses is the serialization the recorder writes with (top-level keys sorted, each
    # response keeping the field order DecisionResult.to_dict() emits), so a recording's diff
    # stays limited to the values that actually changed.
    responses_file.write_text(dump_responses(responses), encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
'''


IMAGE_TESTS = r'''"""Tests for recipe @RANK@'s helpers. They load the helpers by file path."""

import json
from pathlib import Path

import pytest

from jev_cookbook import BoxAnswer, NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook import synthetic_images as si
from jev_cookbook.evaluation import noul_confidence, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.vision import gold_box

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

BOX = {"top": 0.25, "bottom": 0.5, "left": 0.125, "right": 0.5}


def noul(probability):
    return NoulAnswer(probability, Provenance.synthetic())


def box(confidence):
    return BoxAnswer(BOX, confidence, Provenance.synthetic())


def test_questions_are_built_by_python():
    # @TODO@: assert your questions' instructions and criteria against literal expected values
    # (not helpers' own data, which would make the assertion self-referential), then test every
    # rule in helpers.py
    questions = helpers.build_questions()
    assert list(questions) == ["present", "location"]
    assert [question.to_dict()["type"] for question in questions.values()] == ["noul", "box"]


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example;
    # adapt this when an example needs a dependent second request (CONTRIBUTING: a question that
    # depends on an earlier answer goes in a later request), where the example lists a key for
    # each request in order. The key covers the image's bytes, so a changed picture fails here.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        state, assets = helpers.build_request(example.fields)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)


def test_every_scene_can_be_redrawn_from_its_manifest_entry():
    # A shared scene is rebuilt from the generator and parameters its entry records and compared
    # with the committed file; a recipe's own generator is covered by test_build_fixtures.py.
    manifest = json.loads((RECIPE / "assets-manifest.json").read_text("utf-8"))
    shared = [
        entry
        for entry in manifest["assets"]
        if entry["generator"].startswith("jev_cookbook.synthetic_images:")
    ]
    if not shared:
        pytest.skip("no entry names a shared scene; test_build_fixtures.py covers the rest")
    for entry in shared:
        assert si.check_reproducible(RECIPE, entry) in ("unchanged", "kept-committed-bytes")


def test_a_confident_yes_with_a_confident_rectangle_is_located():
    found = helpers.locate("C-1", noul(0.9), box(0.9), 0.3, 0.8)
    assert (found.kind, found.reason) == ("located", "confident rectangle")
    assert found.box == BOX and found.outcome == ("located", BOX)


def test_a_confident_no_is_absent_and_ignores_the_rectangle():
    found = helpers.locate("C-1", noul(0.1), box(0.99), 0.3, 0.8)
    assert found.outcome == ("absent", None)


def test_an_unconfident_presence_answer_is_a_review_never_an_absence():
    # confidence 2 * max(p, 1 - p) - 1: 0.6 for p = 0.8, 0.2 for p = 0.4
    assert helpers.locate("C-1", noul(0.4), box(0.99), 0.3, 0.8).outcome == ("review", None)
    assert helpers.locate("C-1", noul(0.8), box(0.99), 0.7, 0.8).outcome == ("review", None)
    assert helpers.locate("C-1", noul(0.8), box(0.99), 0.6, 0.8).kind == "located"


def test_a_probability_of_exactly_one_half_is_not_a_yes():
    assert helpers.locate("C-1", noul(0.5), box(0.99), 0.0, 0.8).outcome == ("absent", None)


def test_a_review_is_never_an_absence_over_a_grid_of_probabilities_and_thresholds():
    # 101 probabilities (0.00 to 1.00) by 5 thresholds: below the threshold the outcome is a
    # review; at or above it, an absence is the answer "no" and nothing else.
    for step in range(101):
        probability = step / 100
        confidence = noul_confidence([probability])[0]
        for threshold in (0.0, 0.25, 0.5, 0.75, 1.0):
            found = helpers.locate("C-1", noul(probability), box(0.99), threshold, 0.0)
            if confidence < threshold:
                assert found.kind == "review", (probability, threshold)
            elif probability <= 0.5:
                assert found.kind == "absent", (probability, threshold)
            else:
                assert found.kind == "located", (probability, threshold)


def test_a_rectangle_without_enough_confidence_is_a_review():
    missing = helpers.locate("C-1", noul(0.9), box(None), 0.3, 0.0)
    assert (missing.kind, missing.reason) == ("review", "the rectangle has no confidence")
    low = helpers.locate("C-1", noul(0.9), box(0.5), 0.3, 0.8)
    assert (low.kind, low.reason) == ("review", "rectangle confidence below the threshold")
    assert helpers.locate("C-1", noul(0.9), box(0.8), 0.3, 0.8).kind == "located"


def test_a_threshold_outside_zero_to_one_is_an_error():
    with pytest.raises(ValueError, match="presence_threshold"):
        helpers.locate("C-1", noul(0.9), box(0.9), 1.1, 0.8)
    with pytest.raises(ValueError, match="box_threshold"):
        helpers.locate("C-1", noul(0.9), box(0.9), 0.3, -0.1)


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if a confidence gate
    # caught every mistake. Mirror your notebook's own threshold selection here (the lowest
    # confidence at which every validation answer that counts is right) and require a wrong
    # `test` answer at or above it: a mistake the gate would still let through, which is what
    # evaluating on `test` exists to catch. This checks the presence question; repeat it for the
    # rectangle's confidence if that gate matters to your recipe.
    backend = get_backend(fixtures=responses_path(RECIPE), images=True)
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def answer_of(example):
        state, assets = helpers.build_request(example.fields)
        return backend.decide(state, questions, assets=assets)["present"]

    def right(example, answer):
        return (answer.noul > 0.5) == (gold_box(labels[example.id]) is not None)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = [answer_of(e) for e in validation]
    threshold = select_confidence_threshold(
        [right(e, a) for e, a in zip(validation, val_answers, strict=True)],
        noul_confidence([a.noul for a in val_answers]),
        target_accuracy=1.0,
    )

    test = [e for e in examples if e.split == "test" and e.id in labels]
    test_answers = [answer_of(e) for e in test]
    wrong_and_confident = [
        e.id
        for e, a in zip(test, test_answers, strict=True)
        if not right(e, a) and noul_confidence([a.noul])[0] >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
'''

IMAGE_BUILD_FIXTURES_TEST = r'''"""build_fixtures.py follows the recipes/_template/build_fixtures.py pattern, with images: inputs
and labels generation is separate from responses generation, a recorded responses.json is never
silently overwritten, a picture that differs from the committed file is refused rather than
rewritten, and the committed files match what the script writes: the images and
assets-manifest.json unchanged, and responses.json byte for byte what jev_cookbook.live's writer
produces."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from jev_cookbook import dump_responses
from jev_cookbook import synthetic_images as si

RECIPE = Path(__file__).resolve().parent.parent
SCRIPT = RECIPE / "build_fixtures.py"


def load_module_at(path, name):
    """Import build_fixtures.py by file path so its functions and module-level values (ROWS,
    build_responses) are plain Python objects, not subprocess output or a re-dump of the file
    it wrote."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jsonl(rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


def _copy_of_the_recipe(folder):
    """A folder holding what a rerun needs: the two scripts and the committed images. The images
    are copied because their bytes are part of the replay key of each request that carries
    them: with the committed files beside it the script compares each picture it draws with the
    committed one, and without them it would create the pictures afresh with whatever PNG
    encoder this environment has."""
    folder.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (folder / name).write_bytes((RECIPE / name).read_bytes())
    shutil.copytree(RECIPE / "assets", folder / "assets")
    return folder / "build_fixtures.py"


def test_the_committed_responses_are_byte_identical_to_the_recorders_writer():
    """jev_cookbook.dump_responses sorts only the top-level keys; json.dumps(..., sort_keys=True)
    sorts every nested dict too and so disagrees with it on every response's field order. The
    committed file must match dump_responses exactly, not just agree with it on top-level order.

    Comparing against dump_responses(json.loads(raw)) (re-dumping the file's own parsed content)
    cannot catch a sort_keys=True regression: json.loads preserves whatever nested order the file
    already has, and dump_responses only re-sorts the top level, so that round trip would pass no
    matter which writer produced the file. Instead, import build_fixtures.py and compare against
    dump_responses of what build_responses computes directly from ROWS, independent of what
    main() actually wrote to disk."""
    raw = (RECIPE / "fixtures" / "responses.json").read_text("utf-8")
    module = load_module_at(SCRIPT, "recipe@RANK@_build_fixtures_for_test")
    assert len(module.ROWS) > 1
    assert raw == dump_responses(module.build_responses(module.ROWS))


def test_build_fixtures_separates_inputs_labels_from_responses(tmp_path):
    """Mutation check: regenerating must never silently overwrite a recorded responses.json,
    and --force must restore the exact synthetic bytes. inputs.jsonl and labels.jsonl are
    rewritten from ROWS on every run, refused or not: only responses.json is guarded, and this
    also proves it by corrupting both files before the refused run and checking that they come
    back exactly as build_inputs_and_labels(ROWS) computes them, not merely "changed"."""
    script = _copy_of_the_recipe(tmp_path / "@SLUG@")
    copy = script.parent
    first = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr

    responses = copy / "fixtures" / "responses.json"
    data = json.loads(responses.read_text("utf-8"))
    for value in data.values():
        value["model"] = "jev-1.13.0"
    responses.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    before = responses.read_bytes()

    inputs_path = copy / "fixtures" / "inputs.jsonl"
    labels_path = copy / "fixtures" / "labels.jsonl"
    inputs_path.write_bytes(b"corrupted")
    labels_path.write_bytes(b"corrupted")

    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert responses.read_bytes() == before
    module = load_module_at(script, "recipe@RANK@_build_fixtures_for_test_refused")
    expected_inputs, expected_labels = module.build_inputs_and_labels(module.ROWS)
    assert inputs_path.read_text("utf-8") == _jsonl(expected_inputs)
    assert labels_path.read_text("utf-8") == _jsonl(expected_labels)

    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True
    )
    assert forced.returncode == 0, forced.stderr
    after = json.loads(responses.read_text("utf-8"))
    assert all(v["model"] == "synthetic" for v in after.values())


def test_the_generator_reproduces_the_committed_fixtures_and_images(tmp_path):
    script = _copy_of_the_recipe(tmp_path / "@SLUG@")
    copy = script.parent
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    for name in ("inputs.jsonl", "labels.jsonl", "responses.json"):
        assert (copy / "fixtures" / name).read_bytes() == (RECIPE / "fixtures" / name).read_bytes()
    assert (copy / "assets-manifest.json").read_bytes() == (
        RECIPE / "assets-manifest.json"
    ).read_bytes()
    committed = sorted(p.relative_to(RECIPE) for p in (RECIPE / "assets").rglob("*") if p.is_file())
    assert committed
    assert sorted(p.relative_to(copy) for p in (copy / "assets").rglob("*") if p.is_file()) == (
        committed
    )
    for path in committed:
        assert (copy / path).read_bytes() == (RECIPE / path).read_bytes(), path


def test_a_picture_that_differs_from_the_committed_file_is_refused_not_rewritten(tmp_path):
    """The byte policy of docs/synthetic-images.md: a changed picture is a new hash and so new
    replay keys, which is a decision. The script stops, names the problem and writes nothing more;
    --overwrite-assets accepts the redrawn picture and restores the committed one."""
    script = _copy_of_the_recipe(tmp_path / "@SLUG@")
    copy = script.parent
    picture = sorted((copy / "assets").glob("*.png"))[0]
    committed = picture.read_bytes()
    with Image.open(picture) as original:
        size = original.size
    Image.new("RGB", size, "white").save(picture)
    changed = picture.read_bytes()
    assert changed != committed
    manifest = copy / "assets-manifest.json"
    assert not manifest.exists()

    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    assert "refused" in refused.stderr and "nothing else was written" in refused.stderr
    assert picture.read_bytes() == changed
    assert not manifest.exists() and not (copy / "fixtures").exists()

    accepted = subprocess.run(
        [sys.executable, str(script), "--overwrite-assets"], capture_output=True, text=True
    )
    assert accepted.returncode == 0, accepted.stderr
    # The same pixels as the committed picture. Whether the bytes are the committed ones too
    # depends on the PNG encoder of the environment running this test (docs/synthetic-images.md).
    assert picture.read_bytes() != changed
    assert si.png_pixels_equal(picture.read_bytes(), committed)
'''


def image_rows_text() -> str:
    """``IMAGE_ROWS`` as the lines of ``ROWS`` in the image ``build_fixtures.py``."""

    def literal(value: object) -> str:
        if isinstance(value, tuple):
            return "(" + ", ".join(literal(item) for item in value) + ")"
        return json.dumps(value) if isinstance(value, str) else repr(value)

    return "\n".join(f"    {literal(row)}," for row in IMAGE_ROWS)


def _fill(template: str, recipe: dict) -> str:
    """``template`` with its ``@TOKEN@`` placeholders replaced."""
    filled = template.replace("@RANK@", f"{recipe['rank']:02d}").replace("@TODO@", TODO_MARK)
    return filled.replace("@SLUG@", recipe["slug"]).replace("@ROWS@", image_rows_text())


def image_helpers_text(recipe: dict) -> str:
    return _fill(IMAGE_HELPERS, recipe)


def image_build_fixtures_text(recipe: dict) -> str:
    return _fill(IMAGE_BUILD_FIXTURES, recipe)


def files_for(catalog: dict, recipe: dict, mode: str = "replay") -> dict[str, str]:
    """``{relative path: text}`` of everything the scaffold creates."""
    files = {
        "notebook.ipynb": notebook_json(catalog, recipe, mode),
        "README.md": readme_text(catalog, recipe, mode),
        "helpers.py": helpers_text(recipe, mode),
        "build_fixtures.py": build_fixtures_text(recipe, mode),
        "side_effects.json": side_effects_text(),
        BUDGET_FILE: request_budget_text(mode),
        "tests/test_helpers.py": tests_text(recipe, mode),
    }
    if mode == "replay":
        # A scripted recipe's build_fixtures.py has no responses.json and no --force/refusal
        # logic for these tests to guard (build_scripted_fixtures_text), so the file is emitted
        # for replay recipes only.
        files["tests/test_build_fixtures.py"] = build_fixtures_test_text(recipe)
    if mode == IMAGE_MODE:
        files["tests/test_build_fixtures.py"] = build_fixtures_test_text(recipe, mode)
    return files


BUILD_TIMEOUT = 300  # seconds the image scaffold waits for the new folder's build_fixtures.py


def _draw_images(target: Path) -> None:
    """Run ``target``'s own ``build_fixtures.py`` once, which draws ``assets/`` and writes
    ``assets-manifest.json`` and ``fixtures/`` (``--mode replay-images``). If it cannot run or
    exits with an error, ``target`` is removed and ``ScaffoldError`` carries what it printed, so
    the command leaves no half-written recipe."""
    try:
        done = subprocess.run(
            [sys.executable, "build_fixtures.py"],
            cwd=target,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT,
        )
        problem = "" if done.returncode == 0 else "\n".join(done.stderr.strip().splitlines()[-8:])
        if done.returncode != 0 and not problem:
            problem = f"exit status {done.returncode}"
    except (OSError, subprocess.SubprocessError) as error:
        problem = f"{type(error).__name__}: {error}"
    if problem:
        shutil.rmtree(target, ignore_errors=True)
        raise ScaffoldError(
            "--mode replay-images draws the example images by running the new folder's "
            "build_fixtures.py, which needs the installed package and Pillow "
            f'(pip install -e ".[dev]"); it failed, so nothing was created:\n{problem}'
        )


def scaffold(number: int, catalog_path: Path, recipes_dir: Path, mode: str = "replay") -> Path:
    """Create ``recipes_dir/NN-slug/`` and return it. Raises ``ScaffoldError`` and writes
    nothing when the number is out of range, is not in the catalog, or the folder exists. For
    ``--mode replay-images`` it then runs the folder's ``build_fixtures.py`` once (see
    ``_draw_images``); if that fails the folder is removed again."""
    if not FIRST <= number <= LAST:
        raise ScaffoldError(f"recipe number must be {FIRST} to {LAST}, got {number}")
    if mode not in ALL_MODES:
        raise ScaffoldError(f"mode must be one of {', '.join(ALL_MODES)}, got {mode!r}")
    catalog = _load_catalog(catalog_path)
    recipe = find_recipe(catalog, number)
    slug = recipe.get("slug")
    if (
        not isinstance(slug, str)
        or not SLUG.fullmatch(slug)
        or not slug.startswith(f"{number:02d}-")
    ):
        raise ScaffoldError(f"recipe {number} has an invalid catalog slug")
    target = recipes_dir / recipe["slug"]
    if target.exists():
        raise ScaffoldError(f"{target.as_posix()} already exists; refusing to overwrite it")
    files = files_for(catalog, recipe, mode)
    target.mkdir(parents=True)
    for name, text in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    if mode == IMAGE_MODE:
        _draw_images(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create recipes/NN-slug/ for recipe NN from catalog/recipes.json."
    )
    parser.add_argument("number", help=f"recipe number, {FIRST} to {LAST}")
    parser.add_argument(
        "--catalog", type=Path, default=ROOT / "catalog" / "recipes.json", help="catalog file"
    )
    parser.add_argument(
        "--recipes-dir", type=Path, default=ROOT / "recipes", help="where recipe folders live"
    )
    parser.add_argument(
        "--mode",
        choices=ALL_MODES,
        default="replay",
        help="replay (default): fixtures/responses.json is replayed; scripted: a seeded script "
        "in helpers.py answers, for simulator and ScriptedBackend recipes; replay-images: replay "
        "with images, which also draws assets/ and a working example by running the new "
        "folder's build_fixtures.py (needs the installed package and Pillow)",
    )
    args = parser.parse_args(argv)
    if not args.number.isascii() or not args.number.isdigit():
        parser.error(f"recipe number must be a whole number, got {args.number!r}")
    number = int(args.number)
    if not FIRST <= number <= LAST:
        parser.error(f"recipe number must be {FIRST} to {LAST}, got {number}")
    try:
        target = scaffold(number, args.catalog, args.recipes_dir, args.mode)
    except ScaffoldError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"created {target.parent.name}/{target.name}/")
    recipe = find_recipe(_load_catalog(args.catalog), number)
    if recipe.get("issue") is None:
        print(
            "No assigned recipe issue: local scaffolding is allowed, but a recipe pull request "
            "requires a real issue assignment in the base catalog. Do not use the rank as "
            "an issue number."
        )
    print(f"next: grep -rn {TODO_MARK} {target.parent.name}/{target.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
