"""The parametrised recipe guard (#165): one check function per rule, one test case per
published recipe per rule, so a contract rule that used to live only in a reviewer's head is
enforced by CI on every recipe at once, not re-derived by hand on every pull request.

Source of the rules: the Wave 2 consistency review (issue #76 comment 6079429778, "Route #165")
and the PR #186 review's additions (issue #165 comments 6079443958 and 6082395702). Both are
read-only reviews; nothing here loosens, skips, or re-derives a rule differently from what they
specify. ``CONTRIBUTING.md``, ``docs/recipe-template.md``, ``docs/notebook-style.md`` and
``docs/glossary.md`` as they stand on current ``main`` (post PR #186) are the contract text this
module checks against.

Running this module the day it lands finds real, pre-existing drift in recipes merged before the
guard existed -- that is exactly the #163 sweep's work list, not something to fix by weakening a
check here. ``tests/recipe_guard_known_failures.py`` is the one place that drift is recorded, as
a ``(slug, check_id)`` allowlist that marks the pair ``xfail(strict=True)``: CI stays green today,
and a sweep pull request that actually fixes a recipe turns its xfail into an unexpected pass,
which ``strict=True`` turns back into a hard failure until the entry is removed. See that file's
own docstring for the allowlist protocol (a recipe pull request may never add an entry; only a
#163 sweep removes one) and ``docs/notebook-ci.md`` ("The recipe guard allowlist") for the
condensed version aimed at a builder reading CI output.

Check ids, the rule each enforces, and how it is detected (also the per-check docstring below):

====================================  =====================================================
check id                              rule -> detection
====================================  =====================================================
``build_fixtures_scaffold``           G1(a): ``tests/test_build_fixtures.py`` matches
                                       ``tools/new_recipe.py::build_fixtures_test_text`` for
                                       this recipe, byte for byte.
``no_issue_citations``                G1(b), CONTRIBUTING.md section 6: no ``#NNN`` or
                                       "the issue" in a recipe file's prose (docstrings and
                                       comments in ``.py`` files, full text of ``README.md``
                                       and notebook markdown cells).
``stored_answers_strong_form``        G1(c): ``test_stored_answers_are_not_all_right``
                                       re-derives the frozen threshold and asserts a wrong
                                       answer at or above it, not merely "some wrong answer".
``validation_lines_carry_selection_and_check``
                                       G1(d), CONTRIBUTING.md section 2: a printed
                                       validation metric line carries both ``{selection}``
                                       and ``{check}``.
``figure_titles_check_only``          docs/notebook-style.md "Title convention": a
                                       ``plot_confusion_matrix``/``plot_threshold_sweep``/
                                       ``plot_risk_coverage`` title carries ``{check}`` and
                                       not ``{selection}``.
``print_what_you_plot``               G1(e), docs/notebook-style.md "Print what you plot":
                                       every ``plot_confusion_matrix``/``plot_risk_coverage``
                                       call has a matching ``print`` in the same or the
                                       preceding code cell.
``next_steps_links_exist``            G1(f), docs/recipe-template.md: every ``../NN-slug/``
                                       link in the notebook resolves to a published recipe.
``review_value_is_review``            docs/glossary.md#review: ``helpers.REVIEW == "review"``
                                       where a ``REVIEW`` constant exists.
``review_reason_string``              docs/glossary.md#review: the exact reason string
                                       ``"confidence below the threshold"`` appears in
                                       ``helpers.py``.
``readme_sources_match_catalog``      tests/test_recipe_sources.py's own rule, reused here
                                       so the guard reports it as one of the nine checks too.
``readme_budget_note_matches_stored_answers``
                                       CONTRIBUTING.md section 2 / docs/live.md: the stated
                                       live-mode call count equals ``len(responses.json)``.
``readme_no_dev_ml_install``          docs/recipe-template.md step 6: reproducing committed
                                       outputs installs ``.[ml]``, never ``.[dev,ml]``.
====================================  =====================================================

Scope decisions (see the pull request body for the full reasoning):

* The parametrised list is every ``recipes/NN-slug/`` with a committed ``notebook.ipynb``
  (``PUBLISHED``, the same set ``tests/test_recipe_sources.py`` already uses). Checks that need
  a catalog row or a stored-answer count (sources, the live budget note) use ``guarded()`` and
  run over ``PUBLISHED`` alone; every other check uses ``guarded_with_template()`` and also runs
  against ``recipes/_template``, never xfailed there: the template already has its own dedicated
  pins in ``tests/test_template.py``, and including it here gives this module's own detection
  logic a sanity check -- the template is the thing every one of these rules is written to match.
* ``next_steps_links_exist`` checks only that a forward link resolves (R20). It does not also
  check that every published recipe is the *target* of some other recipe's Next steps (R21):
  that is a property of the whole set, not of one recipe against one rule, and belongs to a
  different kind of test; #165's brief scopes this module to per-recipe, per-check cases.
* A recipe with no ``fixtures/responses.json`` (a scripted recipe; none are published yet) is
  skipped, not failed, by every check that reads stored responses
  (``build_fixtures_scaffold``, ``stored_answers_strong_form``,
  ``readme_budget_note_matches_stored_answers``): there is nothing for them to guard.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import tokenize
from pathlib import Path
from types import ModuleType

import pytest

from jev_cookbook import load_helpers

REPO = Path(__file__).resolve().parent.parent


def _load_known_failures() -> dict[tuple[str, str], str]:
    """``tests/recipe_guard_known_failures.py``'s ``KNOWN_FAILURES``, loaded by file path: this
    directory has no ``__init__.py`` (pytest's ``--import-mode=importlib`` needs none for
    collection), so ``from tests.recipe_guard_known_failures import ...`` is not a reliable cross-
    module import here. ``tools/new_recipe.py``'s own loader elsewhere in this module uses the
    same mechanism."""
    spec = importlib.util.spec_from_file_location(
        "recipe_guard_known_failures",
        Path(__file__).resolve().parent / "recipe_guard_known_failures.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.KNOWN_FAILURES


KNOWN_FAILURES = _load_known_failures()
RECIPES_DIR = REPO / "recipes"
TEMPLATE = RECIPES_DIR / "_template"
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))


def _is_published(recipe: dict) -> bool:
    return (RECIPES_DIR / recipe["slug"] / "notebook.ipynb").is_file()


# Every catalog recipe with a committed notebook -- the same set tests/test_recipe_sources.py
# already selects. _template is not a catalog slug (tests/test_template_render.py) and is added
# separately, only to the checks it makes sense for (see the module docstring).
PUBLISHED: list[dict] = [r for r in CATALOG["recipes"] if _is_published(r)]


def test_at_least_one_recipe_is_published():
    # Otherwise every parametrized check below would silently check nothing.
    assert PUBLISHED


def _slug(recipe_or_path) -> str:
    return recipe_or_path["slug"] if isinstance(recipe_or_path, dict) else recipe_or_path.name


def guarded(check_id):
    """``[pytest.param(recipe, id=slug, marks=...)]`` for every recipe in PUBLISHED, xfail(strict)
    marked for exactly the (slug, check_id) pairs tests/recipe_guard_known_failures.py lists."""

    def params(recipes=PUBLISHED):
        out = []
        for recipe in recipes:
            slug = _slug(recipe)
            reason = KNOWN_FAILURES.get((slug, check_id))
            marks = [pytest.mark.xfail(reason=f"#163: {reason}", strict=True)] if reason else []
            out.append(pytest.param(recipe, id=slug, marks=marks))
        return out

    return params


def guarded_with_template(check_id):
    """Like ``guarded``, but also runs the check against ``recipes/_template`` (never xfailed:
    the template is the reference every one of these checks is written to match)."""

    def params():
        return guarded(check_id)() + [pytest.param({"slug": "_template"}, id="_template")]

    return params


def recipe_dir(recipe: dict) -> Path:
    return RECIPES_DIR / recipe["slug"]


def load_tool(name: str) -> ModuleType:
    """A tool module, loaded by file path (tools/ has no __init__.py)."""
    spec = importlib.util.spec_from_file_location(f"{name}_for_recipe_guard", REPO / "tools" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def notebook_cells(recipe_dir_: Path) -> list[dict]:
    return json.loads((recipe_dir_ / "notebook.ipynb").read_text("utf-8"))["cells"]


def cell_source(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def extract_calls(source: str, name: str) -> list[str]:
    """Every balanced ``name(...)`` call in ``source``, as its full text including the parens.

    A plain depth counter over every ``(``/``)`` in the source, not a tokenizer: good enough for
    the call shapes these notebooks actually use (no unbalanced parens inside a string literal
    argument), and it has to handle a call whose own arguments contain further calls (an f-string
    computing ``{len(x)}``), which a non-recursive regex cannot.
    """
    calls = []
    start = 0
    needle = name + "("
    while True:
        idx = source.find(needle, start)
        if idx == -1:
            return calls
        depth = 0
        end = None
        for j in range(idx + len(name), len(source)):
            if source[j] == "(":
                depth += 1
            elif source[j] == ")":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end is None:
            return calls
        calls.append(source[idx : end + 1])
        start = end + 1


# --------------------------------------------------------------------------------------------
# check 1: tests/test_build_fixtures.py matches the current scaffold
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe", guarded("build_fixtures_scaffold")())
def test_build_fixtures_guard_matches_the_current_scaffold(recipe):
    """G1(a): byte-identical to ``tools/new_recipe.py::build_fixtures_test_text(recipe)``, the
    exact text ``python tools/new_recipe.py`` would emit for this recipe today. Byte identity
    (rather than, say, checking for the regeneration assertion alone) is the precise signature:
    it also catches a stray issue number in the docstring (R9) and any other drift in the same
    motion, and it is exactly what ``tests/test_template.py`` already proves for the template
    itself (reversing the substitution the other way)."""
    path = recipe_dir(recipe) / "fixtures" / "responses.json"
    if not path.is_file():
        pytest.skip("scripted recipe: no responses.json, no test_build_fixtures.py to guard")
    new_recipe = load_tool("new_recipe.py")
    expected = new_recipe.build_fixtures_test_text(recipe)
    actual_path = recipe_dir(recipe) / "tests" / "test_build_fixtures.py"
    assert actual_path.is_file(), f"{recipe['slug']}: no tests/test_build_fixtures.py"
    assert actual_path.read_text("utf-8") == expected


# --------------------------------------------------------------------------------------------
# check 2: no "#NNN" issue numbers or "the issue" in a recipe file
# --------------------------------------------------------------------------------------------

ISSUE_NUMBER = re.compile(r"#\d+\b")
THE_ISSUE = re.compile(r"\bthe issue\b", re.IGNORECASE)
QUOTED = re.compile(r'"[^"\n]*"')


def _strip_quoted(text: str) -> str:
    """Remove double-quoted spans before scanning prose for an issue citation: a recipe's own
    markdown routinely quotes a fixture's raw input text back at the reader (an invented invoice
    or ticket number, "invoice #312"), and that fabricated, in-fiction "#NNN" is not a citation
    of this repository's issue tracker. A real citation ("Issue #2 asks for...") is never itself
    inside quotes, so this does not hide one."""
    return QUOTED.sub(" ", text)


def _prose_of_python(source: str) -> str:
    """Docstrings and comments only -- the prose a reader of the file sees -- not string-literal
    fixture data (a ``ROWS`` entry can legitimately contain a fabricated "#NNN", an invoice or
    ticket number that is part of the example, not a citation)."""
    parts = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    parts.append(doc)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                parts.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return "\n".join(parts)


def _citation_hits(text: str, location: str) -> list[str]:
    text = _strip_quoted(text)
    hits = [f"{location}: {m.group(0)!r} (issue number)" for m in ISSUE_NUMBER.finditer(text)]
    hits += [f'{location}: {m.group(0)!r} ("the issue")' for m in THE_ISSUE.finditer(text)]
    return hits


def _recipe_citation_hits(recipe_dir_: Path) -> list[str]:
    hits = []
    for name in ("helpers.py", "build_fixtures.py"):
        path = recipe_dir_ / name
        if path.is_file():
            hits += _citation_hits(_prose_of_python(path.read_text("utf-8")), name)
    readme = recipe_dir_ / "README.md"
    if readme.is_file():
        hits += _citation_hits(readme.read_text("utf-8"), "README.md")
    tests_dir = recipe_dir_ / "tests"
    if tests_dir.is_dir():
        for path in sorted(tests_dir.glob("*.py")):
            hits += _citation_hits(_prose_of_python(path.read_text("utf-8")), f"tests/{path.name}")
    notebook = recipe_dir_ / "notebook.ipynb"
    if notebook.is_file():
        for cell in notebook_cells(recipe_dir_):
            source = cell_source(cell)
            location = f"notebook.ipynb cell {cell.get('id', '?')}"
            if cell["cell_type"] == "code":
                hits += _citation_hits(_prose_of_python(source), location)
            else:
                hits += _citation_hits(source, location)
    return hits


@pytest.mark.parametrize("recipe", guarded_with_template("no_issue_citations")())
def test_no_issue_numbers_or_the_issue_in_recipe_files(recipe):
    """G1(b), CONTRIBUTING.md section 6: "A recipe file never cites a private issue number or
    'the issue' -- a reader cannot see either." Scans the prose of helpers.py, build_fixtures.py,
    every tests/*.py file, README.md and every notebook cell (code cells: docstrings and comments
    only; markdown cells and README.md: full text, minus quoted fixture text -- see
    ``_strip_quoted``'s docstring for why)."""
    hits = _recipe_citation_hits(recipe_dir(recipe))
    assert not hits, "; ".join(hits)


# --------------------------------------------------------------------------------------------
# check 3: test_stored_answers_are_not_all_right is the strong form
# --------------------------------------------------------------------------------------------

STRONG_FORM_DEF = "def test_stored_answers_are_not_all_right"
# Captures the name the recomputed cutoff is assigned to: every recipe names it differently
# (threshold, gate, ...), so the "wrong answer at or above it" comparison below must use
# whatever name this capture finds, not a hardcoded "threshold".
RERIVES_THRESHOLD = re.compile(r"(\w+)\s*=\s*select_(?:confidence_)?threshold\(")


def _find_function_body(source: str, def_line: str) -> str | None:
    """``source`` from ``def_line`` to the next top-level ``def``/``class``, or EOF. ``None`` if
    ``def_line`` is not in ``source``. A plain substring slice, not an AST visit: the strong-form
    signature below is itself textual (two literal markers), so this keeps the whole check at one
    level of mechanism."""
    idx = source.find(def_line)
    if idx == -1:
        return None
    rest = source[idx:]
    body = rest[len(def_line) :]
    next_def = re.search(r"\n(?:def |class )", body)
    return def_line + (body[: next_def.start()] if next_def else body)


@pytest.mark.parametrize("recipe", guarded_with_template("stored_answers_strong_form")())
def test_stored_answers_are_not_all_right_is_the_strong_form(recipe):
    """G1(c): the strong form re-derives the frozen confidence threshold from ``validation``
    (an assignment from ``select_confidence_threshold(`` or ``select_threshold(``) and requires a
    wrong ``test`` answer *at or above* that same name (a ``>= <name>`` comparison in the same
    function body, whatever the recipe calls it -- ``threshold``, ``gate``, and both are used by
    real merged recipes). The weak form, ``assert wrong, "the fixtures should contain some wrong
    answers"``, passes even when the confidence gate catches every mistake (R7) and has no such
    assignment to find; a recipe that keeps the old weak assertion *alongside* a working strong
    one (18, 22) still passes here, because the strong assertion is what actually binds."""
    path = recipe_dir(recipe) / "fixtures" / "responses.json"
    if recipe["slug"] != "_template" and not path.is_file():
        pytest.skip(
            "scripted recipe: no stored answers for this guard to re-derive a threshold over"
        )
    tests_dir = recipe_dir(recipe) / "tests"
    bodies = [
        body
        for test_file in sorted(tests_dir.glob("*.py"))
        if (body := _find_function_body(test_file.read_text("utf-8"), STRONG_FORM_DEF)) is not None
    ]
    assert bodies, f"{recipe['slug']}: no {STRONG_FORM_DEF} in tests/"
    body = bodies[0]
    match = RERIVES_THRESHOLD.search(body)
    assert match, (
        f"{recipe['slug']}: does not re-derive the threshold (no 'x = select_confidence_threshold(...)')"
    )
    name = match.group(1)
    assert re.search(rf">=\s*{re.escape(name)}\b", body), (
        f"{recipe['slug']}: no '>= {name}' comparison selecting a wrong answer at or above it"
    )


# --------------------------------------------------------------------------------------------
# check 4a: a validation metric line carries both {selection} and {check}
# --------------------------------------------------------------------------------------------

FLOAT_FORMAT = re.compile(r"\{[^{}]*:\.\d+f\}")


@pytest.mark.parametrize(
    "recipe", guarded_with_template("validation_lines_carry_selection_and_check")()
)
def test_validation_metric_lines_carry_selection_and_check(recipe):
    """G1(d), CONTRIBUTING.md section 2: "a number from the validation split is a selection
    step" and, in an offline run, "any metric is a check that the pipeline works" -- together,
    in a synthetic or scripted run, a validation number needs both labels.

    Narrow, mechanical definition: a *validation metric line* is a ``print(`` call in a notebook
    code cell whose text contains both a rounded-float format spec (``{x:.4f}``, the shape every
    metric in this cookbook is printed with) and the word "validation". Such a line must contain
    the literal tokens ``{selection}`` and ``{check}``. This does not catch a validation line with
    no float formatting (a plain status line with no number carries no selection/check
    obligation either), which is deliberate: see the module docstring."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    violations = []
    for cell in notebook_cells(recipe_dir(recipe)) if nb.is_file() else []:
        if cell["cell_type"] != "code":
            continue
        source = cell_source(cell)
        for call in extract_calls(source, "print"):
            if FLOAT_FORMAT.search(call) and "validation" in call.lower():
                missing = [t for t in ("{selection}", "{check}") if t not in call]
                if missing:
                    violations.append(
                        f"cell {cell.get('id', '?')} missing {missing}: {call[:80]!r}"
                    )
    assert not violations, "; ".join(violations)


# --------------------------------------------------------------------------------------------
# check 4b: a plot_*'s title carries {check} and not {selection}
# --------------------------------------------------------------------------------------------

METRIC_PLOTS = ("plot_confusion_matrix", "plot_threshold_sweep", "plot_risk_coverage")
TITLE_ARG = re.compile(r'title\s*=\s*(f?"(?:[^"\\]|\\.)*"|f?\'(?:[^\'\\]|\\.)*\')')


@pytest.mark.parametrize("recipe", guarded_with_template("figure_titles_check_only")())
def test_metric_figure_titles_carry_check_and_not_selection(recipe):
    """docs/notebook-style.md "Title convention": a figure's title carries the pipeline-check
    disclosure ``{check}`` and no other disclosure label, even when it is drawn from
    ``validation`` -- a figure is never additionally re-labelled as a selection step the way a
    printed number is.

    Scoped to the three evaluation chart helpers (``plot_confusion_matrix``,
    ``plot_threshold_sweep``, ``plot_risk_coverage``): ``plot_answer_probabilities`` draws one
    answer for the "One answer up close" section, not a split's metrics, and the template's own
    plain, descriptive titles there ("A review with conflicting signal") correctly carry neither
    label."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    violations = []
    for cell in notebook_cells(recipe_dir(recipe)) if nb.is_file() else []:
        if cell["cell_type"] != "code":
            continue
        source = cell_source(cell)
        for fn in METRIC_PLOTS:
            for call in extract_calls(source, fn):
                match = TITLE_ARG.search(call)
                if match is None:
                    violations.append(f"cell {cell.get('id', '?')} {fn}(...) has no title=")
                    continue
                title = match.group(1)
                if "{check}" not in title:
                    violations.append(
                        f"cell {cell.get('id', '?')} {fn} title missing {{check}}: {title}"
                    )
                if "{selection}" in title:
                    violations.append(
                        f"cell {cell.get('id', '?')} {fn} title has {{selection}}: {title}"
                    )
    assert not violations, "; ".join(violations)


# --------------------------------------------------------------------------------------------
# check 5: print what you plot
# --------------------------------------------------------------------------------------------

PRINTED_TABLE_PLOTS = ("plot_confusion_matrix", "plot_risk_coverage")
FIRST_ARG = re.compile(r"\(\s*([A-Za-z_][A-Za-z0-9_.]*)")


def _mentions_in_a_print(source: str, name: str) -> bool:
    return bool(re.search(rf"print\(.*?\b{re.escape(name)}\b", source, re.DOTALL))


@pytest.mark.parametrize("recipe", guarded_with_template("print_what_you_plot")())
def test_every_plot_call_has_a_printed_table(recipe):
    """G1(e), docs/notebook-style.md "Print what you plot": CI's figure comparison is loose, so
    the printed numbers are what actually pins the plotted data byte for byte.

    Narrow, mechanical definition: for every ``plot_confusion_matrix(`` or ``plot_risk_coverage(``
    call, take its first positional argument's base name (``matrix`` in
    ``plot_confusion_matrix(matrix, title=...)``, ``curve`` in ``plot_risk_coverage(curve)``, the
    part before any ``.`` attribute access). A ``print(`` call that mentions that same name,
    anywhere in the same code cell or the immediately preceding code cell, counts as printing the
    plotted table. This is deliberately about the *plotted object*, not "any print nearby": an
    unrelated print in the preceding cell (a baseline accuracy line, say) does not satisfy it,
    which is exactly the gap this check exists to catch (recipe 23's confusion matrix has such a
    preceding cell and still fails this check)."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    if not nb.is_file():
        pytest.skip("no notebook")
    code_cells = [c for c in notebook_cells(recipe_dir(recipe)) if c["cell_type"] == "code"]
    violations = []
    for i, cell in enumerate(code_cells):
        source = cell_source(cell)
        for fn in PRINTED_TABLE_PLOTS:
            for call in extract_calls(source, fn):
                match = FIRST_ARG.search(call)
                if match is None:
                    violations.append(
                        f"cell {cell.get('id', '?')} {fn}(...) has no plain first argument"
                    )
                    continue
                name = match.group(1).split(".")[0]
                previous = cell_source(code_cells[i - 1]) if i > 0 else ""
                if not (_mentions_in_a_print(source, name) or _mentions_in_a_print(previous, name)):
                    violations.append(
                        f"cell {cell.get('id', '?')} {fn}({name}, ...) prints nothing"
                    )
    assert not violations, "; ".join(violations)


# --------------------------------------------------------------------------------------------
# check 6: every Next-steps link target exists on disk
# --------------------------------------------------------------------------------------------

NEIGHBOUR_LINK = re.compile(r"\]\(\.\./([0-9]{2}-[a-z0-9-]+)/\)")


@pytest.mark.parametrize("recipe", guarded_with_template("next_steps_links_exist")())
def test_next_steps_links_resolve_to_a_published_recipe(recipe):
    """G1(f), docs/recipe-template.md: "Link only a recipe whose notebook.ipynb is already
    committed on main: a folder link to one that is not yet published would 404 on GitHub, and
    that forward link is not allowed." Scans every markdown cell (not only the one named
    ``next-md``: the suffix is cosmetic, see docs/recipe-template.md "Cell ids"), for a
    ``](../NN-slug/)`` folder link, and requires ``recipes/NN-slug/notebook.ipynb`` to exist."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    if not nb.is_file():
        pytest.skip("no notebook")
    missing = []
    for cell in notebook_cells(recipe_dir(recipe)):
        if cell["cell_type"] != "markdown":
            continue
        for slug in NEIGHBOUR_LINK.findall(cell_source(cell)):
            if not (RECIPES_DIR / slug / "notebook.ipynb").is_file():
                missing.append(f"cell {cell.get('id', '?')} links ../{slug}/, not published")
    assert not missing, "; ".join(missing)


# --------------------------------------------------------------------------------------------
# check 7a/7b: helpers.REVIEW == "review"; the exact reason string in helpers.py
# --------------------------------------------------------------------------------------------

REASON_STRING = "confidence below the threshold"


@pytest.mark.parametrize("recipe", guarded_with_template("review_value_is_review")())
def test_review_outcome_value_is_review_where_it_exists(recipe):
    """docs/glossary.md#review: "the outcome value itself is the string 'review' (not, say,
    'human_review'; a recipe may still name its own domain-specific sub-reasons)." Only checked
    where ``helpers.py`` actually defines a module-level ``REVIEW`` constant: a recipe whose rule
    names its review outcome some other way (``REVIEW_NEEDED`` in recipe 16, say) has nothing for
    this particular check to compare, and is not asserted to be wrong by its absence."""
    helpers = load_helpers(recipe_dir(recipe))
    if not hasattr(helpers, "REVIEW"):
        pytest.skip("helpers.py defines no module-level REVIEW constant")
    assert helpers.REVIEW == "review"


@pytest.mark.parametrize("recipe", guarded_with_template("review_reason_string")())
def test_the_confidence_gate_reason_string_is_exact(recipe):
    """docs/glossary.md#review: "the reason string for a confidence-gated review is exactly
    'confidence below the threshold', so two recipes' readers see the same words for the same
    cause." A plain substring search of helpers.py's full text (this is a literal string argument
    in the rule's own code, not prose, so it is not restricted to docstrings and comments the way
    the issue-citation check is)."""
    text = (recipe_dir(recipe) / "helpers.py").read_text("utf-8")
    assert REASON_STRING in text


# --------------------------------------------------------------------------------------------
# check 8a: README "## Sources" equals the catalog row
# --------------------------------------------------------------------------------------------

SOURCE_ID = re.compile(r"^- (S\d+):", re.MULTILINE)


def _readme_source_ids(readme_text: str) -> list[str]:
    """Same rule as tests/test_recipe_sources.py::_readme_source_ids, reused here (not imported:
    that module is collected by pytest under ``--import-mode=importlib`` with no package
    __init__, so importing it by dotted path from another test module is fragile; the rule is
    four lines, so it is restated instead, with this note tying the two together)."""
    marker = "\n## Sources\n"
    if marker not in readme_text:
        return []
    return SOURCE_ID.findall(readme_text.split(marker, 1)[1])


@pytest.mark.parametrize("recipe", guarded("readme_sources_match_catalog")())
def test_readme_sources_match_the_catalog(recipe):
    """tests/test_recipe_sources.py's own rule, folded into this module as one of the nine
    checks too (CONTRIBUTING.md: a recipe's README is one page of the contract same as any
    other file). Not run against the template, which has no catalog row to compare against."""
    readme = (recipe_dir(recipe) / "README.md").read_text("utf-8")
    documented = _readme_source_ids(readme)
    cataloged = recipe.get("sources", [])
    assert documented, f"{recipe['slug']}/README.md has no '## Sources' bullet list"
    assert set(documented) == set(cataloged)


# --------------------------------------------------------------------------------------------
# check 8b: the live budget note equals the stored-answer count
# --------------------------------------------------------------------------------------------

LIVE_CALL_COUNT = re.compile(
    r"makes\s+exactly\s+(?:\*\*)?(\d+)(?:\*\*)?\s+(?:calls?|requests?)\b"
    r"|makes\s+exactly\s+one\s+(?:call|request)\s+for\s+each\s+of\s+(?:the\s+)?(\d+)\b"
)


@pytest.mark.parametrize("recipe", guarded("readme_budget_note_matches_stored_answers")())
def test_the_live_budget_note_matches_the_stored_answer_count(recipe):
    """CONTRIBUTING.md section 2 / docs/live.md: every attempt against the live request budget
    counts once per example actually decided, and the README's "Switch to live" section states
    that count so a reader can size ``JEV_COOKBOOK_LIVE_MAX_REQUESTS`` correctly. The count is
    derivable wherever ``fixtures/responses.json`` exists (one stored response per decided
    example, by construction of ``build_fixtures.py``), so this checks the number the README
    states there against ``len(responses.json)``.

    The stated number is read from either of the two prose shapes every current recipe's README
    uses ("makes exactly one call for each of the 40 examples", "makes exactly **17** calls"),
    tolerant of a line wrap (``\\s+`` for every space) and of "call" or "request" (recipe 06 says
    the latter). A recipe whose README states the count some other way is not something this
    regex can see and is a gap in the check, not necessarily in the recipe; see the pull request
    body."""
    path = recipe_dir(recipe) / "fixtures" / "responses.json"
    if not path.is_file():
        pytest.skip("scripted recipe: no responses.json to derive a stored-answer count from")
    stored = len(json.loads(path.read_text("utf-8")))
    readme = (recipe_dir(recipe) / "README.md").read_text("utf-8")
    assert "## Switch to live" in readme
    section = readme.split("## Switch to live", 1)[1].split("## What was", 1)[0]
    match = LIVE_CALL_COUNT.search(section)
    assert match, f"{recipe['slug']}: no recognisable live-call-count sentence in README.md"
    stated = int(next(g for g in match.groups() if g))
    assert stated == stored, (
        f"{recipe['slug']}: README states {stated}, responses.json has {stored}"
    )


# --------------------------------------------------------------------------------------------
# check 9: no ".[dev,ml]" install line in the README
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe", guarded_with_template("readme_no_dev_ml_install")())
def test_the_readme_never_installs_dev_and_ml_combined(recipe):
    """docs/recipe-template.md step 6: reproducing committed outputs installs ``.[ml]`` alone
    (``nbclient``/``ipykernel`` are core dependencies, so ``.[ml]`` is already enough to execute
    the notebook; ``.[dev]`` is for ``ruff``/``pytest``, which that job does not run). The
    pre-#162 README paragraph combined them into one ``.[dev,ml]`` install line (R15); this
    checks the literal substring is gone."""
    readme = (recipe_dir(recipe) / "README.md").read_text("utf-8")
    assert ".[dev,ml]" not in readme
