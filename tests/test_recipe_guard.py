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
sweep against the entry's own named issue removes one -- #163 for most entries here, a
different issue's own number for a later check's own newly-revealed drift) and
``docs/notebook-ci.md`` ("The recipe guard allowlist") for the condensed version aimed at a
builder reading CI output.

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
                                       re-derives the frozen threshold (preferring the
                                       confidence gate over a plain business threshold when
                                       a recipe has both) and binds an ``assert`` to a
                                       wrong-answer-at-or-above-it comparison, not merely
                                       "some wrong answer somewhere".
``validation_lines_carry_selection_and_check``
                                       G1(d) clause 1, CONTRIBUTING.md section 2: a printed
                                       validation metric line carries both ``{selection}``
                                       and ``{check}``.
``metric_lines_carry_check``          G1(d) clause 2: every printed metric line (a
                                       coverage/accuracy/risk/precision/recall/F1/nDCG
                                       keyword with a rounded-float format) carries at
                                       least ``{check}``, traced through simple bindings.
``figure_titles_check_only``          docs/notebook-style.md "Title convention": a
                                       ``plot_confusion_matrix``/``plot_threshold_sweep``/
                                       ``plot_risk_coverage`` title carries ``{check}`` and
                                       not ``{selection}``.
``print_what_you_plot``               G1(e), docs/notebook-style.md "Print what you plot":
                                       every ``plot_confusion_matrix``/``plot_threshold_sweep``/
                                       ``plot_risk_coverage`` call has, in the same code
                                       cell, a ``print`` of the plotted object itself or of
                                       something a loop over it prints.
``next_steps_links_exist``            G1(f) clause 1, docs/recipe-template.md: every
                                       ``../NN-slug/`` link in the notebook resolves to a
                                       published recipe.
``next_steps_inbound_links``          G1(f) clause 2: every published recipe is the target
                                       of at least one other published recipe's Next steps.
``review_value_is_review``            docs/glossary.md#review: ``helpers.REVIEW == "review"``
                                       where it exists; traced through the confidence-gated
                                       reason string where it does not, less one named
                                       domain exemption (recipe 16's ``ESCALATE``).
``review_reason_string``              docs/glossary.md#review: the exact reason string
                                       ``"confidence below the threshold"`` appears in
                                       ``helpers.py``.
``readme_sources_match_catalog``      tests/test_recipe_sources.py's own rule, reused here
                                       so the guard reports it as one of these checks too.
``readme_budget_note_matches_stored_answers``
                                       CONTRIBUTING.md section 2 / docs/live.md: the stated
                                       live-mode call count equals ``len(responses.json)``.
``readme_no_dev_ml_install``          docs/recipe-template.md step 6: reproducing committed
                                       outputs installs ``.[ml]``, never ``.[dev,ml]``.
``measured_cell_prints_n_offline``    CONTRIBUTING.md section 2 (#215): the "measured" cell's
                                       offline branch prints N, not only its live/recorded
                                       branch.
``threshold_objective_pin``           for every real ``select_confidence_threshold(``/
                                       ``select_threshold(`` call in the committed notebook or
                                       ``helpers.py``, the objective it actually selects is
                                       PINNED by some assertion in that recipe's tests, traced
                                       by data flow back to the real committed call or a real
                                       production call (not merely co-located with a string
                                       naming the spelling) -- not a hand-written literal beside
                                       the call, and not the resulting threshold value alone.
====================================  =====================================================

Scope decisions (see the pull request body for the full reasoning):

* The parametrised list is every ``recipes/NN-slug/`` with a committed ``notebook.ipynb``
  (``PUBLISHED``, the same set ``tests/test_recipe_sources.py`` already uses). Checks that need
  a catalog row or a stored-answer count (sources, the live budget note) use ``guarded()`` and
  run over ``PUBLISHED`` alone; every other check uses ``guarded_with_template()`` and also runs
  against ``recipes/_template``, never xfailed there: the template already has its own dedicated
  pins in ``tests/test_template.py``, and including it here gives this module's own detection
  logic a sanity check -- the template is the thing every one of these rules is written to match.
* ``next_steps_inbound_links`` is still a per-recipe, per-check case (the fix round that added it
  found the distinction drawn in an earlier revision of this docstring -- that inbound coverage is
  "a property of the whole set, not of one recipe" -- did not actually hold: the check below reads
  every *other* recipe's notebook the same way ``next_steps_links_exist`` reads every neighbour's
  folder, and ``readme_sources_match_catalog`` already reads the catalog, so there was no real
  distinction between what a per-recipe check can and cannot look at).
* ``next_steps_inbound_links`` is nonetheless the one check in this module marked
  ``@pytest.mark.catalog_audit`` and deselected from the default run (#203, issue #76 comment
  6079429778's "Route #165"). The distinction that matters here is not what the check can read
  but when it can possibly pass: a recipe pull request may change only its own folder (``Scope``),
  and no recipe on ``main`` may link forward to a recipe that is not yet published
  (``next_steps_links_exist`` forbids it), so a new recipe's own PR can never add the backlink
  this check needs and can never satisfy it -- not a drift to record in
  ``tests/recipe_guard_known_failures.py``, but a check that is structurally unpassable within
  the scope of the PR that would trip it. It runs instead as a wave close-out audit, by hand,
  after the close-out sweep has added the missing backlinks: ``pytest -m catalog_audit
  tests/test_recipe_guard.py`` (see ``docs/development.md``, "Continuous integration"). Per-PR
  CI (bare ``pytest``, which reads ``pyproject.toml``'s ``addopts``) never selects it. A
  consequence for ``tests/recipe_guard_known_failures.py``: an allowlist entry keyed on
  ``next_steps_inbound_links`` is now exercised only at close-out, not in per-PR CI, so that one
  check's entries (there are none today) can only go stale between close-outs, not between
  pull requests -- see that file's own docstring for the allowlist protocol, which this
  narrows by exactly one check.
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
import shutil
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
            # The reason string itself carries its own citation (see that file's docstring):
            # historically always "... see #163", but #244's own guard adds entries for drift
            # that check newly reveals, which is #244's own work list, not #163's -- so this no
            # longer hardcodes a "#163:" prefix onto every entry regardless of which issue it
            # actually tracks (see the pull request body for #244's reasoning).
            marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
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
# The confidence gate is preferred over a plain business threshold when a recipe's test
# re-derives both (recipe 15: a Noul business threshold by F1, then a separate confidence gate):
# G1(c) is about the *confidence* gate specifically, and re.search returns the leftmost match, so
# naming the gate pattern first keeps a recipe's earlier, unrelated "threshold = select_threshold(
# ...)" business-threshold line from being picked up as if it were the gate.
CONFIDENCE_GATE_ASSIGN = re.compile(r"(\w+)\s*=\s*select_confidence_threshold\(")
PLAIN_THRESHOLD_ASSIGN = re.compile(r"(\w+)\s*=\s*select_threshold\(")


def _find_function_body(source: str, def_line: str) -> str | None:
    """``source`` from ``def_line`` to the next top-level ``def``/``class``, or EOF. ``None`` if
    ``def_line`` is not in ``source``."""
    idx = source.find(def_line)
    if idx == -1:
        return None
    rest = source[idx:]
    body = rest[len(def_line) :]
    next_def = re.search(r"\n(?:def |class )", body)
    return def_line + (body[: next_def.start()] if next_def else body)


def _derives_threshold_name(body: str) -> str | None:
    match = CONFIDENCE_GATE_ASSIGN.search(body) or PLAIN_THRESHOLD_ASSIGN.search(body)
    return match.group(1) if match else None


def _ast_names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _has_gte_against(node: ast.AST, target: str) -> bool:
    """True if ``node``'s subtree contains a ``>=`` comparison with ``target`` on either side."""
    for compare in ast.walk(node):
        if isinstance(compare, ast.Compare):
            for op, comparator in zip(compare.ops, compare.comparators, strict=True):
                if isinstance(op, ast.GtE) and (
                    target in _ast_names(compare.left) or target in _ast_names(comparator)
                ):
                    return True
    return False


def _calls_in(stmts: list[ast.stmt]) -> list[ast.Call]:
    """``ast.Call`` nodes under ``stmts`` only -- an ``ast.If``'s ``body``, never its ``orelse``,
    so an ``.append`` in an unrelated ``else`` branch is never credited to the ``if``'s own test."""
    return [n for s in stmts for n in ast.walk(s) if isinstance(n, ast.Call)]


def _vars_bound_to_the_gte_comparison(tree: ast.AST, target: str) -> set[str]:
    """Names whose value structurally depends on a ``>= target`` comparison: an assignment whose
    right-hand side contains one (a list comprehension's filter or its element expression, a
    ``for``-loop accumulator initialised to a boolean/number), or a ``name.append(...)`` call
    inside the body of an ``if`` whose test contains one (the loop-and-flag shape 14, 18 and 22
    use: ``if a.confidence >= gate: wrong_above_gate.append(e.id)``)."""
    confirmed: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and _has_gte_against(node.value, target)
        ):
            confirmed.add(node.targets[0].id)
        if isinstance(node, ast.If) and _has_gte_against(node.test, target):
            for call in _calls_in(node.body):
                if isinstance(call.func, ast.Attribute) and call.func.attr == "append":
                    if isinstance(call.func.value, ast.Name):
                        confirmed.add(call.func.value.id)
    return confirmed


def _an_assert_depends_on(tree: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(node, ast.Assert) and _ast_names(node.test) & names for node in ast.walk(tree)
    )


@pytest.mark.parametrize("recipe", guarded_with_template("stored_answers_strong_form")())
def test_stored_answers_are_not_all_right_is_the_strong_form(recipe):
    """G1(c): the strong form re-derives the frozen confidence threshold from ``validation``
    (an assignment from ``select_confidence_threshold(`` or, lacking that, ``select_threshold(``)
    and binds an ``assert`` to a wrong-answer-at-or-above-it comparison -- not merely performs
    the comparison somewhere dead, and not merely asserts "some wrong answer exists" (the weak
    form, R7, which has no such assignment to find at all).

    "Binds" is checked with ``ast``, not text: find every name whose value structurally depends
    on a ``>= <derived name>`` comparison (a list/generator comprehension's filter or element
    expression, or a ``name.append(...)`` call inside an ``if`` gated on that comparison -- the
    two shapes the eight currently-passing recipes and the template use between them), then
    require at least one ``assert`` whose own test expression names one of those. A recipe that
    keeps an old weak assertion *alongside* a working strong one (18, 22) still passes, because
    the strong assertion is what actually binds; deleting only the strong assertion and leaving
    the weak one (proven on recipe 14 in scratch) correctly fails this check."""
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
    target = _derives_threshold_name(body)
    assert target, (
        f"{recipe['slug']}: does not re-derive the threshold "
        "(no 'x = select_confidence_threshold(...)' or 'x = select_threshold(...)')"
    )
    tree = ast.parse(body)
    confirmed = _vars_bound_to_the_gte_comparison(tree, target)
    assert confirmed, f"{recipe['slug']}: nothing is derived from a '>= {target}' comparison"
    assert _an_assert_depends_on(tree, confirmed), (
        f"{recipe['slug']}: no assert's own test expression names {sorted(confirmed)}"
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
# check 4b (of G1(d)): every printed metric line carries at least {check}
# --------------------------------------------------------------------------------------------

METRIC_KEYWORD = re.compile(r"\b(coverage|accuracy|risk|precision|recall|f1|ndcg)\b", re.IGNORECASE)


def _assigned_names(tree: ast.AST) -> dict[str, ast.AST]:
    return {
        node.targets[0].id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }


def _labelled_names(tree: ast.AST, label: str) -> set[str]:
    """Names anywhere in ``tree`` transitively carrying the disclosure label ``"check"`` (or
    ``"selection"``): the bare name itself; a simple assignment whose value references one; a
    ``for``-loop's unpacked target at the position where every element of a literal tuple/list
    ``iter`` references one (recipe 17's ``for ..., label in (("validation", ..., selection +
    check), ("test", ..., check)):``); or a function parameter whose argument references one at
    every call site of that function (recipe 21's ``def f(..., suffix): ... f(..., f"{selection}
    {check}")``). Fixed-point over the three, so a label can pass through more than one hop."""
    derived = {label}
    assigns = list(ast.walk(tree))
    functions = {n.name: n for n in assigns if isinstance(n, ast.FunctionDef)}
    calls_by_func = {
        name: [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == name
        ]
        for name in functions
    }
    changed = True
    while changed:
        changed = False
        for node in assigns:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                target_name = node.targets[0].id
                if target_name not in derived and derived & _ast_names(node.value):
                    derived.add(target_name)
                    changed = True
            if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
                elements = node.iter.elts if isinstance(node.iter, ast.Tuple | ast.List) else None
                if not elements:
                    continue
                arity = len(node.target.elts)
                for position, slot in enumerate(node.target.elts):
                    if not isinstance(slot, ast.Name) or slot.id in derived:
                        continue
                    if all(
                        isinstance(elt, ast.Tuple | ast.List)
                        and len(elt.elts) == arity
                        and derived & _ast_names(elt.elts[position])
                        for elt in elements
                    ):
                        derived.add(slot.id)
                        changed = True
        for name, fdef in functions.items():
            calls = calls_by_func[name]
            if not calls:
                continue
            for position, arg in enumerate(fdef.args.args):
                if arg.arg in derived:
                    continue
                supplied_per_call = [
                    call.args[position]
                    if position < len(call.args)
                    else next((kw.value for kw in call.keywords if kw.arg == arg.arg), None)
                    for call in calls
                ]
                if all(s is not None and derived & _ast_names(s) for s in supplied_per_call):
                    derived.add(arg.arg)
                    changed = True
    return derived


def _metric_lines_missing_check(source: str) -> list[str]:
    """``print(`` calls in ``source`` whose text has a metric keyword and a rounded-float
    format spec but whose formatted values name no ``{check}``-derived name. Shared by the
    parametrized check below and by the regression test that proves the tracer's "every call
    site" requirement actually holds."""
    candidates = [
        c
        for c in extract_calls(source, "print")
        if METRIC_KEYWORD.search(c) and FLOAT_FORMAT.search(c)
    ]
    if not candidates:
        return []
    tree = ast.parse(source)
    check_derived = _labelled_names(tree, "check")
    missing = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print"):
            continue
        text = ast.get_source_segment(source, node) or ""
        if not (METRIC_KEYWORD.search(text) and FLOAT_FORMAT.search(text)):
            continue
        used = {
            name
            for arg in (*node.args, *(kw.value for kw in node.keywords))
            for name in _ast_names(arg)
        }
        if not used & check_derived:
            missing.append(text)
    return missing


@pytest.mark.parametrize("recipe", guarded_with_template("metric_lines_carry_check")())
def test_every_printed_metric_line_carries_at_least_check(recipe):
    """G1(d) clause 2 (issue #76 comment 6079429778): "every printed metric line carries at
    least {check}" -- the direct generalisation of
    tests/test_template.py::test_every_metric_line_of_the_evaluation_carries_the_pipeline_check_label,
    over every recipe instead of only the template. Catches R3 (recipe 17's six unlabelled sweep
    rows) and more besides, since Wave 2 only read recipes 11-23.

    Narrow, mechanical definition: a *metric line* is a ``print(`` call whose text contains both
    a coverage/accuracy/risk/precision/recall/F1/nDCG keyword and a rounded-float format spec
    (``{x:.4f}``) -- a plain "any print with a rounded float" proxy is not usable, since it also
    flags the template's own per-example confidence lines, which carry no metric keyword and
    correctly need no label. Such a line's formatted values must include a name transitively
    carrying ``{check}`` (``_labelled_names``): checking only for the literal substring
    ``"{check}"`` wrongly flags recipes 17, 21 and 22, which disclose through a bound ``suffix``/
    ``label``/``split_label`` variable instead of the literal token."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    violations = []
    for cell in notebook_cells(recipe_dir(recipe)) if nb.is_file() else []:
        if cell["cell_type"] != "code":
            continue
        for text in _metric_lines_missing_check(cell_source(cell)):
            violations.append(f"cell {cell.get('id', '?')}: {text[:90]!r} carries no {{check}}")
    assert not violations, "; ".join(violations)


def test_the_label_tracer_requires_every_call_site_not_just_one():
    """Fix round 2, Opus re-review MC-A: ``_labelled_names`` must require a check-derived
    argument at *every* call site of a function (and at every element of a literal tuple/list
    ``for``-loop iterable), not just one -- otherwise one labelled split licenses another,
    undisclosed one. Proved directly against recipe 21's own ``eval-selective`` cell, which
    calls ``selective_report`` twice: once with ``f"{selection}{check}"``, once with plain
    ``check``. The unmutated cell has no violation; unlabelling only the second call site (the
    exact repro the review used) must turn up one."""
    source = cell_source(
        next(
            cell
            for cell in notebook_cells(recipe_dir({"slug": "21-quiz-answer-adjudication"}))
            if cell.get("id") == "eval-selective"
        )
    )
    assert not _metric_lines_missing_check(source)

    marker = '"test, called subset", check)'
    assert marker in source
    mutated = source.replace(marker, '"test, called subset", "")')
    assert _metric_lines_missing_check(mutated), (
        "unlabelling only the second selective_report call site must be caught"
    )


# --------------------------------------------------------------------------------------------
# check 4c (of G1(d)): a plot_*'s title carries {check} and not {selection}
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

PRINTED_TABLE_PLOTS = ("plot_confusion_matrix", "plot_risk_coverage", "plot_threshold_sweep")
FIRST_ARG = re.compile(r"\(\s*([A-Za-z_][A-Za-z0-9_.]*)")


def _derived_from(tree: ast.AST, seed: str) -> set[str]:
    """Names whose value is assigned, directly or transitively, from an expression mentioning
    ``seed`` -- the fixed-point simple-assignment half of ``_labelled_names``, reused here for
    one name instead of a disclosure label (recipe 18's ``zipped = zip(curve.thresholds, ...)``,
    read from ``curve``)."""
    derived = {seed}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id not in derived
                and derived & _ast_names(node.value)
            ):
                derived.add(node.targets[0].id)
                changed = True
    return derived


def _body_calls_print(stmts: list[ast.stmt]) -> bool:
    return any(
        isinstance(call.func, ast.Name) and call.func.id == "print" for call in _calls_in(stmts)
    )


def _cell_prints_the_plotted_object(source: str, name: str) -> bool:
    """True if ``source`` prints ``name`` (or a plain-assignment descendant of it) either
    directly -- a ``print(...)`` call whose argument subtree references such a name -- or
    indirectly, via a ``for`` loop whose iterable references one and whose body calls ``print``
    (the template's ``for gold_label, row in zip(matrix.labels, matrix.matrix.tolist(), ...):
    ... print(...)``, recipe 21's identical shape, and recipe 18's one-hop ``zipped = zip(curve.
    ...)`` then ``for ... in zipped: print(...)``, covered by ``_derived_from`` first)."""
    tree = ast.parse(source)
    derived = _derived_from(tree, name)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            if derived & {
                nm
                for arg in (*node.args, *(kw.value for kw in node.keywords))
                for nm in _ast_names(arg)
            }:
                return True
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.For)
            and derived & _ast_names(node.iter)
            and _body_calls_print(node.body)
        ):
            return True
    return False


@pytest.mark.parametrize("recipe", guarded_with_template("print_what_you_plot")())
def test_every_plot_call_has_a_printed_table(recipe):
    """G1(e), docs/recipe-template.md and docs/notebook-style.md "Print what you plot" ("Pair
    every plot_* call with a print of the same data, rounded, in the same cell"; sweep helpers
    are named explicitly alongside the confusion matrix in recipe-template.md). CI's figure
    comparison is loose, so the printed numbers are what actually pins the plotted data byte for
    byte.

    For every ``plot_confusion_matrix(``, ``plot_risk_coverage(`` or ``plot_threshold_sweep(``
    call, in the *same* cell only (the contract names the same cell, and a preceding-cell
    allowance was checked and found to add nothing real: it only ever let an unrelated print
    satisfy this), take its first positional argument's base name (``matrix``, ``curve``, the
    part before any ``.`` attribute access) and require
    ``_cell_prints_the_plotted_object``: a ``print`` whose argument subtree names that object
    (directly, or via a ``for`` loop over it). What this actually requires is narrower than "the
    same data the figure draws" reads as, on purpose and honestly stated: it is satisfied by any
    print derived from the plotted object, including a count merely derived from it and not its
    full table, which this check does not tell apart from one -- a cell that prints a number
    computed independently of the plotted object (an overall accuracy from `test_gold`/
    `test_answers` directly, say) is the one shape this reliably catches."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    if not nb.is_file():
        pytest.skip("no notebook")
    violations = []
    for cell in notebook_cells(recipe_dir(recipe)):
        if cell["cell_type"] != "code":
            continue
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
                if not _cell_prints_the_plotted_object(source, name):
                    violations.append(
                        f"cell {cell.get('id', '?')} {fn}({name}, ...) prints nothing of {name}"
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


def _inbound_next_steps_links() -> dict[str, set[str]]:
    """``{slug: {slugs of published recipes whose own notebook links ../slug/}}``, over every
    published recipe (never ``_template``, which is not a catalog slug and is not a valid link
    target either)."""
    inbound: dict[str, set[str]] = {r["slug"]: set() for r in PUBLISHED}
    for recipe in PUBLISHED:
        for cell in notebook_cells(recipe_dir(recipe)):
            if cell["cell_type"] != "markdown":
                continue
            for slug in NEIGHBOUR_LINK.findall(cell_source(cell)):
                if slug in inbound and slug != recipe["slug"]:
                    inbound[slug].add(recipe["slug"])
    return inbound


INBOUND_NEXT_STEPS_LINKS = _inbound_next_steps_links()


@pytest.mark.catalog_audit
@pytest.mark.parametrize("recipe", guarded("next_steps_inbound_links")())
def test_every_recipe_is_linked_from_some_other_recipes_next_steps(recipe):
    """G1(f) clause 2 (issue #76 comment 6079429778): "every published recipe is the target of
    at least one other recipe's Next steps" (R21) -- a per-recipe, per-check case exactly like
    ``next_steps_links_exist`` (see the module docstring's scope decisions), computed once over
    the whole published set (``_inbound_next_steps_links``, built from the same
    ``](../NN-slug/)`` pattern that check reads) and looked up per recipe here.

    Marked ``catalog_audit`` (#203) and deselected by default (see ``pyproject.toml``'s
    ``addopts``): a new recipe's own pull request can never satisfy this check. The recipe
    being added has no inbound link yet, and nothing in its own PR can create one -- no recipe
    on ``main`` may link forward to a recipe that is not yet published (``next_steps_links_exist``
    forbids exactly that), and a recipe pull request may change only its own folder (the
    ``Scope`` check), so it cannot add a backlink to itself from an older recipe either. The
    check is therefore run by hand at each wave close-out, after the sweep that adds the
    missing backlinks: ``pytest -m catalog_audit tests/test_recipe_guard.py``."""
    assert INBOUND_NEXT_STEPS_LINKS[recipe["slug"]], (
        f"{recipe['slug']}: no other published recipe's Next steps links ../{recipe['slug']}/"
    )


# --------------------------------------------------------------------------------------------
# check 7a/7b: helpers.REVIEW == "review"; the exact reason string in helpers.py
# --------------------------------------------------------------------------------------------

REASON_STRING = "confidence below the threshold"
# The identifier immediately preceding a confidence-gated review's reason string, e.g.
# "Routing(ticket, REVIEW, \"confidence below the threshold\")" or the tuple-unpacking
# "outcome, reason = UNCERTAIN, \"confidence below the review cutoff\"" (recipe 06's own,
# non-conforming text -- "confidence below" rather than the exact REASON_STRING, so this
# traces even the recipes review_reason_string already flags for a different reason).
CONFIDENCE_REASON_PREFIX = re.compile(r'(\w+)\s*,\s*"confidence below')
# Recipe 16's REVIEW_NEEDED names one of the rule's own question options, not the outcome a
# low-confidence answer is routed to; its real outcome, ESCALATE, is a legitimate
# domain-specific name (an escalation queue), not REVIEW renamed -- see the test's docstring.
NAMED_DOMAIN_OUTCOME_EXEMPTIONS = {
    "16-discord-moderation-triage": 'ESCALATE is a genuine domain-specific outcome, not "review" renamed',
}


@pytest.mark.parametrize("recipe", guarded_with_template("review_value_is_review")())
def test_review_outcome_value_is_review_where_it_exists(recipe):
    """docs/glossary.md#review: "the outcome value itself is the string 'review' (not, say,
    'human_review'; a recipe may still name its own domain-specific sub-reasons)." Checked
    directly where ``helpers.py`` defines a module-level ``REVIEW`` constant; traced where it
    does not, via the identifier immediately preceding a confidence-gated review's reason string
    (``'\\w+, "confidence below'``, loose enough to also find 06's non-conforming ``"confidence
    below the review cutoff"`` -- see ``review_reason_string`` for that drift -- not only the
    exact pinned text, since a recipe that fails one check should not be invisible to the other).

    Three recipes have no ``REVIEW`` constant today (06, 16, 21), and they are not the same kind
    of case. 16's constant is ``REVIEW_NEEDED``, naming one of the rule's own *question* options
    (something the model can answer), not the outcome a wrong or unconfident answer is routed to
    -- 16's actual review outcome, traced the same way, is ``ESCALATE``, a legitimate
    domain-specific name for "an escalation queue" (the glossary's "a recipe may still name its
    own domain-specific sub-reasons" clause, read for the outcome value rather than only the
    reason string, which is the only reading under which ``ESCALATE`` is not simply ``"review"``
    wearing a disguise). It is named here, once, as the one exemption the trace does not itself
    decide. 06 (``UNCERTAIN``) and 21 (``NEEDS_REVIEW``, value literally ``"needs_review"``) have
    no such claim: both read as a plain rename of the same review-queue outcome the glossary
    names, so the trace reports them as real failures -- recorded in the allowlist (their own
    reason naming #163, the sweep issue that owns this drift) rather than hidden behind a skip
    whose stated reason would not be the truth about them. (Not every check's allowlist entries
    name #163: see ``tests/recipe_guard_known_failures.py``'s own docstring.)"""
    helpers = load_helpers(recipe_dir(recipe))
    if hasattr(helpers, "REVIEW"):
        assert helpers.REVIEW == "review"
        return
    if recipe["slug"] in NAMED_DOMAIN_OUTCOME_EXEMPTIONS:
        pytest.skip(
            f"{recipe['slug']}: {NAMED_DOMAIN_OUTCOME_EXEMPTIONS[recipe['slug']]} "
            "(named exemption, not traced)"
        )
    text = (recipe_dir(recipe) / "helpers.py").read_text("utf-8")
    match = CONFIDENCE_REASON_PREFIX.search(text)
    assert match, (
        f"{recipe['slug']}: no REVIEW constant and no identifiable confidence-gated "
        "outcome for this check to trace"
    )
    value = getattr(helpers, match.group(1), None)
    assert value == "review", (
        f"{recipe['slug']}: the confidence-gated outcome ({match.group(1)}) is {value!r}, "
        'not "review"'
    )


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
    """tests/test_recipe_sources.py's own rule, folded into this module as one of these checks
    too (CONTRIBUTING.md: a recipe's README is one page of the contract same as any
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


# --------------------------------------------------------------------------------------------
# check 10: the "measured" cell's offline branch prints N (#215)
# --------------------------------------------------------------------------------------------

MEASURED_SIGNATURE = "Not measured live: a pipeline check, not a Jev result."


def _load_measured_cell_branches() -> ModuleType:
    """``tests/measured_cell_branches.py``, loaded by file path like
    ``_load_known_failures`` above: the branch-anchoring and "really prints N" logic is shared
    with ``tests/test_template.py``'s own pin on the template, so the one piece of logic that
    decides "which branch discloses the run mode, and does it really print N" is written, and
    proved against PR #219 reviewer B's evasions, once rather than twice."""
    spec = importlib.util.spec_from_file_location(
        "measured_cell_branches_for_recipe_guard",
        Path(__file__).resolve().parent / "measured_cell_branches.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_measured_cell = _load_measured_cell_branches()


def _disclosure_branches(source: str) -> list[list[ast.stmt]]:
    return _measured_cell.disclosure_branches(source, MEASURED_SIGNATURE)


_branch_prints_n = _measured_cell.branch_prints_n


@pytest.mark.parametrize("recipe", guarded_with_template("measured_cell_prints_n_offline")())
def test_the_measured_cell_prints_n_in_the_offline_branch(recipe):
    """CONTRIBUTING.md section 2: the disclosure names, "in every mode", the run mode and N --
    the number of examples a reported number covers. docs/recipe-template.md states the
    consequence explicitly: the "What was and was not measured" code cell's branches must each
    actually print N, so an offline run's branch prints it too, not only the recorded/live
    branch -- a markdown promise one branch of its own code does not keep is a defect in the
    cell, not something to soften in the prose.

    #215: the scaffolder's own version of this cell printed no N in the offline branch for weeks,
    and the only test naming this property, ``tests/test_new_recipe.py``, could not fail: it
    checked ``"N:" in measured`` against the whole cell rather than the offline branch alone, and
    the live (``else``) branch's own ``"N:"`` line satisfied that regardless of what the offline
    branch did. This check applies the same fix at the recipe level, over every published recipe
    (and the template), so a recipe scaffolded with the defect, or a hand-edit that drops N from
    one branch later, is caught here even when nothing else does.

    The cell is found by its disclosure sentence (``MEASURED_SIGNATURE``) rather than by cell id:
    most recipes call it ``measured``, but a few predate that convention (recipe 01 calls it
    ``measured-code``; recipe 05's id is an auto-generated hex string) -- the sentence itself is
    the one thing every recipe's version of this cell shares, by CONTRIBUTING.md's own "the
    disclosure is the same in every recipe" rule.

    The branch that must print N is found with ``ast``, anchored on whichever branch actually
    carries the disclosure (``_disclosure_branches``) -- not, as the first version of this check
    did, by splitting the source on the first ``else:`` and treating whatever comes before it as
    "the offline branch". That assumption is what let three shapes pass while the rule stayed
    broken (PR #219 reviewer B): an ``elif`` that moves N into a third branch while the
    disclosure stays in the ``if``; an inverted ``if not offline: ... else:`` that moves the
    disclosure into the ``else``; and ``# N: ...`` written as a comment, which a substring search
    over the branch's raw text cannot tell apart from an actual ``print``. ``_branch_prints_n``
    requires a real ``print`` call whose string argument starts with ``"N:"``, which closes all
    three. The ``else:`` requirement below is unchanged from the original check (a cell with no
    recorded/live branch at all still fails here, as it always did); what changed is how the
    branch to check is chosen and what counts as "prints N" within it."""
    cells = [
        c
        for c in notebook_cells(recipe_dir(recipe))
        if c["cell_type"] == "code" and MEASURED_SIGNATURE in cell_source(c)
    ]
    assert cells, f"{recipe['slug']}: no code cell carries the disclosure sentence"
    for cell in cells:
        source = cell_source(cell)
        assert "else:" in source, f"{recipe['slug']}: cell {cell.get('id', '?')} has no else branch"
        branches = _disclosure_branches(source)
        assert branches, (
            f"{recipe['slug']}: cell {cell.get('id', '?')} carries the disclosure sentence but "
            "not inside any if/elif/else branch this check can parse"
        )
        for branch in branches:
            assert _branch_prints_n(branch), (
                f"{recipe['slug']}: cell {cell.get('id', '?')}'s branch carrying the disclosure "
                "prints no N"
            )
        # The committed, stored output must carry a line starting "N:" too (the same pin
        # tests/test_template.py makes on the template, tests/test_template.py:398): a cell
        # whose source prints N but whose committed output was captured from a stale run that did
        # not would otherwise pass the check above and still mislead a reader of the rendered
        # notebook, who sees only the stored output, never the source.
        lines = "".join(
            "".join(o.get("text", ""))
            for o in cell.get("outputs", [])
            if o.get("output_type") == "stream"
        ).splitlines()
        assert any(line.startswith("N:") for line in lines), (
            f"{recipe['slug']}: cell {cell.get('id', '?')}'s committed stdout has no line "
            "starting with N:"
        )


# --------------------------------------------------------------------------------------------
# check 11: the threshold-selection OBJECTIVE is pinned by source spelling (#244)
# --------------------------------------------------------------------------------------------

# For each function, the complete set of spellings its objective can take: the keyword
# argument name for select_confidence_threshold (mutually exclusive, no default -- exactly one
# is given), or the string value of select_threshold's `objective` argument (positional or
# keyword; defaults to "f1" when omitted entirely).
THRESHOLD_OBJECTIVE_SPELLINGS = {
    "select_confidence_threshold": ("target_accuracy", "min_coverage"),
    "select_threshold": ("f1", "recall_at_precision", "precision_at_recall"),
}


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """``{alias: real_name}`` for ``from jev_cookbook.evaluation import select_threshold as X``
    style renames of either threshold function, so a call made *through* the alias is not
    silently invisible to the rest of this check (a reviewer measured this on a throwaway
    mutation of recipe 38: ``import ... as _sct`` then ``_sct(...)`` made the unmodified check
    below report "no threshold call here" -- fail OPEN, the wrong default for a check whose
    whole purpose is to fail closed). No published recipe does this today; this exists so the
    guard does not silently stop seeing a recipe that starts to."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in THRESHOLD_OBJECTIVE_SPELLINGS and alias.asname:
                    aliases[alias.asname] = alias.name
    return aliases


def _resolved_call_name(call: ast.Call, aliases: dict[str, str]) -> str | None:
    """The real function name ``call`` resolves to -- ``select_confidence_threshold`` or
    ``select_threshold``, by direct name or via ``aliases`` -- or ``None`` for anything else
    (including a call through an attribute such as ``jev_cookbook.evaluation.select_threshold
    (...)``, which no published recipe uses and which this does not attempt to resolve; that
    residual gap is disclosed rather than silently assumed away)."""
    if not isinstance(call.func, ast.Name):
        return None
    name = call.func.id
    if name in THRESHOLD_OBJECTIVE_SPELLINGS:
        return name
    return aliases.get(name)


def _call_func_name(call: ast.Call) -> str | None:
    """The bare name one call is made through -- ``f(...)`` or ``x.f(...)`` -- or ``None`` for
    a callee shape with no simple name (``(lambda: ...)()``). Used only to check membership in
    a *name-based* set (a recipe's own taint-producing helper functions, or a ``helpers.py``
    production wrapper); it is not the same resolution ``_resolved_call_name`` does for the two
    specific threshold functions themselves."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _threshold_call_objective(call: ast.Call, resolved_name: str) -> str | None:
    """The objective actually selected by one real call already known (via
    ``_resolved_call_name``) to resolve to ``resolved_name``: the keyword-argument NAME present
    for ``select_confidence_threshold`` (``target_accuracy`` or ``min_coverage`` -- whichever
    the call actually binds), or the string VALUE of ``select_threshold``'s ``objective``
    argument, given positionally (3rd argument) or as the keyword ``objective=``. Parsed from
    the already-parsed ``ast.Call`` node, not by regex on text: a value that merely contains a
    keyword's spelling as a substring elsewhere in the call (inside an unrelated string
    argument, say) cannot be mistaken for the argument binding itself. Returns ``None`` for a
    call shape this cannot identify an objective for (not observed in the published set; such a
    call is still flagged, as an unidentifiable objective, by the check below rather than
    silently skipped)."""
    if resolved_name == "select_confidence_threshold":
        for kw in call.keywords:
            if kw.arg in ("target_accuracy", "min_coverage"):
                return kw.arg
        return None
    for kw in call.keywords:
        if (
            kw.arg == "objective"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value
    if (
        len(call.args) >= 3
        and isinstance(call.args[2], ast.Constant)
        and isinstance(call.args[2].value, str)
    ):
        return call.args[2].value
    return None


def _real_threshold_calls(tree: ast.AST, aliases: dict[str, str]) -> list[tuple[ast.Call, str]]:
    """``(call, resolved_function_name)`` for every genuine ``ast.Call`` node resolving to
    ``select_confidence_threshold``/``select_threshold`` -- real code, never text that merely
    looks like a call inside a string literal (an f-string's hand-written decoration quoting
    the call shape beside it, exactly the pattern #244 found inert). A plain substring/paren-
    balance scan over the cell's raw text, as this module's own ``extract_calls`` does for
    other checks, cannot tell the two apart; walking the already-parsed AST can, because a
    string constant is never an ``ast.Call`` node regardless of what text it contains."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            resolved = _resolved_call_name(node, aliases)
            if resolved is not None:
                found.append((node, resolved))
    return found


def _threshold_pin_obligations(recipe_dir_: Path) -> list[tuple[str, str, str | None]]:
    """``(location, function_name, objective)`` for every real threshold-selection call in this
    recipe's committed ``notebook.ipynb`` code cells or its ``helpers.py`` -- both are scanned
    (not the notebook alone) because three published recipes (28, 31, 35) route the call
    through a ``helpers.py`` wrapper the notebook merely calls by name, and checking only the
    notebook would silently *skip* them rather than reveal that they, too, lack the pin -- the
    same blind spot #222's ``G1(c)`` already has for exactly this shape, which this check must
    not repeat (see the pull request body).

    A code cell or ``helpers.py`` that does not parse as plain Python (an IPython magic, or any
    other syntax error) is reported as its own obligation, with function name
    ``"<unparseable>"`` and objective ``None`` -- a hard failure naming what is wrong, never a
    silent skip and never a raw ``SyntaxError`` traceback blamed on the recipe.

    Import aliases are resolved across the WHOLE notebook, not cell by cell: a notebook's
    ``from jev_cookbook.evaluation import select_threshold as X`` import and the cell that
    calls ``X(...)`` are essentially never the same cell (the import lives in an early setup
    cell; the call lives in the evaluation cell), and ``ast.parse`` on one cell's own source
    can never see an import statement written in a different cell. Parsing each cell on its
    own and resolving aliases against that one cell's tree alone -- an earlier version of this
    function did exactly that -- means the alias fix below cannot actually fire for any
    notebook: 0 of 46 published recipes have the import and the call in the same cell, so a
    reviewer's recipe-38 alias mutation still returned ``SKIP (no obligations)`` under it,
    silently, which is worse than not attempting the fix at all. Building one merged
    ``{alias: real_name}`` map from every code cell first, then resolving every cell's own
    calls against that merged map, is what makes the alias route actually reachable."""
    obligations: list[tuple[str, str, str | None]] = []
    notebook = recipe_dir_ / "notebook.ipynb"
    if notebook.is_file():
        code_cells = [c for c in notebook_cells(recipe_dir_) if c["cell_type"] == "code"]
        parsed: list[tuple[dict, ast.Module | None]] = []
        merged_aliases: dict[str, str] = {}
        for cell in code_cells:
            try:
                tree = ast.parse(cell_source(cell))
            except SyntaxError:
                parsed.append((cell, None))
                continue
            parsed.append((cell, tree))
            merged_aliases.update(_import_aliases(tree))
        for cell, tree in parsed:
            location = f"cell {cell.get('id', '?')}"
            if tree is None:
                obligations.append((location, "<unparseable>", None))
                continue
            for call, resolved in _real_threshold_calls(tree, merged_aliases):
                obligations.append((location, resolved, _threshold_call_objective(call, resolved)))
    helpers_path = recipe_dir_ / "helpers.py"
    if helpers_path.is_file():
        try:
            tree = ast.parse(helpers_path.read_text("utf-8"))
        except SyntaxError:
            obligations.append(("helpers.py", "<unparseable>", None))
        else:
            aliases = _import_aliases(tree)
            for call, resolved in _real_threshold_calls(tree, aliases):
                obligations.append(
                    ("helpers.py", resolved, _threshold_call_objective(call, resolved))
                )
    return obligations


def _test_function_defs(tree: ast.AST) -> list[ast.FunctionDef]:
    """Every ``def test_...`` in an already-parsed test file, found by walking the module's own
    AST -- deliberately not a text scan that locates one function by name and then regexes
    forward to the next ``\\n(?:def |class )`` to find where it ends (``_find_function_body``,
    above, does that for a single named function). That scan-forward shape is unsound in
    general: a decorator line is neither ``def`` nor ``class``, so a decorated neighbour
    (``@pytest.mark.parametrize`` on the very next function, common in this codebase) folds into
    the "body" it returns, and parsing that text then raises a ``SyntaxError`` that is really a
    bug in the extraction, not in the recipe (#272). Finding every function with ``ast.walk`` and
    bounding each one with ``ast.get_source_segment`` (used below) sidesteps the whole class:
    the parser's own ``end_lineno`` is exact regardless of what decorator, comment, or blank line
    follows, so this check can never misreport a recipe's test file as broken when the guard's
    own extraction is what is wrong."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def _reads_real_committed_source(segment: str) -> bool:
    """True if one piece of source text (a single statement's own segment -- see
    ``_tainted_names_in_function`` below, which calls this once per assignment, not once per
    whole function) is the actual FILE READ of the *actual committed* notebook or
    ``helpers.py`` -- not a hand-typed duplicate of either, and not a later step of the same
    chain (extracting one cell, then joining its ``"source"``) that never itself mentions the
    file at all. Two routes, matching the two places a real threshold-selection call can live
    (see ``_threshold_pin_obligations``): the notebook route (``notebook.ipynb`` with
    ``read_text`` -- the parse step, which the generic name-reference propagation in
    ``_tainted_names_in_function`` then carries forward through every later ``cell = ...``/
    ``source = ...`` step without this function needing to see the word ``"source"`` at all)
    and the helpers route (``inspect.getsource(`` on something named ``helpers``, or a direct
    read of ``helpers.py``'s own text). Deliberately a text heuristic for the one, single,
    file-opening statement rather than a full data-flow trace of its own (the data-flow tracing
    is ``_tainted_names_in_function``'s job): this used to also require ``"source"`` to appear
    in the SAME statement as ``"notebook.ipynb"``, which is false for the template's own three-
    line chain (``notebook = json.loads(...)``; ``cell = next(... notebook["cells"] ...)``;
    ``source = "".join(cell["source"])``) -- no single line of that chain contains both, so the
    whole chain went untainted. Seeding only on the read itself and letting propagation do the
    rest fixes that without weakening anything: the three-line chain, and each of 41's, 42's,
    and 44's one-line or module-level-helper variants, all seed correctly either way."""
    notebook_route = "notebook.ipynb" in segment and "read_text" in segment
    helpers_route = ("inspect.getsource(" in segment and "helpers" in segment) or (
        "helpers.py" in segment and "read_text" in segment
    )
    return notebook_route or helpers_route


def _production_wrapper_names(helpers_path: Path) -> set[str]:
    """Top-level function names defined in ``helpers.py`` whose own body makes a real
    threshold-selection call -- calling one of these from a test exercises the real objective,
    whatever it is, even though the test itself never reads ``helpers.py``'s text at all
    (recipe 28's ``helpers.select_margin_threshold``, used only through
    ``_spellings_pinned_by_production_discrimination`` below, since a bare call with no
    accompanying non-degeneracy check proves nothing by itself)."""
    if not helpers_path.is_file():
        return set()
    try:
        tree = ast.parse(helpers_path.read_text("utf-8"))
    except SyntaxError:
        return set()
    aliases = _import_aliases(tree)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _real_threshold_calls(node, aliases)
    }


def _locally_source_reading_function_names(tree: ast.Module, text: str) -> set[str]:
    """Names of functions DEFINED IN THIS TEST FILE whose own body reads the real committed
    notebook or ``helpers.py`` (``_reads_real_committed_source`` on the function's own source
    segment) -- a module-level helper like recipes 42's ``_notebook_cell_source`` or 44's
    ``_notebook_code_source``, which several recipes factor the read into so more than one test
    can reuse it. Calling such a function taints the result wherever it is called from, not only
    from inside its own definition -- the fix for recipes 42 and 44, whose pin a reviewer found
    this check previously missed entirely because the read lived outside the one test
    function's own segment."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            segment = ast.get_source_segment(text, node) or ""
            if _reads_real_committed_source(segment):
                names.add(node.name)
    return names


def _tainted_names_in_function(
    func: ast.FunctionDef, text: str, taint_producing_names: set[str]
) -> set[str]:
    """Fixed-point taint set, local to one test function: a name is tainted if the statement
    assigning it (a) itself reads the real committed source (``_reads_real_committed_source`` on
    that one assignment's own text -- the inline case: recipes 38, 39, 41, 43, 45, the template),
    (b) calls a function named in ``taint_producing_names`` (a source-reading helper defined
    anywhere in this file, or a ``helpers.py`` wrapper that itself makes the real selection call
    -- recipes 28, 42, 44), or (c) its value expression references an already-tainted name
    anywhere, including as a call argument (plain data-flow propagation -- recipe 42's
    ``_call_keyword_value(source, ...)``, whose own definition never mentions
    ``notebook.ipynb`` at all, but whose result still structurally depends on it because its
    argument, ``source``, does). Scoped to one function at a time (never a whole-file flat
    namespace): a name is only ever compared against taint computed within the SAME function,
    so an unrelated function's own local variable sharing a common name (``source``, ``cell``)
    can never borrow another function's taint."""
    tainted: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(func):
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                continue
            target = node.targets[0].id
            if target in tainted:
                continue
            value_text = ast.get_source_segment(text, node.value) or ""
            calls_taint_producing = any(
                isinstance(n, ast.Call) and _call_func_name(n) in taint_producing_names
                for n in ast.walk(node.value)
            )
            if (
                _reads_real_committed_source(value_text)
                or calls_taint_producing
                or (tainted & _ast_names(node.value))
            ):
                tainted.add(target)
                changed = True
    return tainted


NEGATIVE_COMPARISONS = (ast.NotIn, ast.NotEq, ast.IsNot)


def _effective_comparisons(expr: ast.expr, negated: bool = False):
    """Yield ``(compare, effective_positive)`` for every ``ast.Compare`` reachable from
    ``expr``, tracking sign through any enclosing ``not`` (``ast.UnaryOp``/``ast.Not``, which
    flips the running sign) and through ``and``/``or`` (``ast.BoolOp``, which does NOT flip
    anything -- it only distributes the current sign unchanged to each of its own operands).
    ``effective_positive`` folds the enclosing-``not`` count together with the compare's own
    operator: a ``NotIn``/``NotEq``/``IsNot`` compare is itself negative, so an even total
    number of negations (a positive op under zero enclosing nots, or a negative op under one)
    reads positive overall -- ``not ("x" in source)`` and ``not ("x" not in source)`` land on
    opposite sides of this, correctly: the first says "x" must be absent, the second says it
    must be present. A reviewer's own synthetic probe established the missing case directly:
    this module previously had no handling for ``UnaryOp``/``Not`` at all, so ``assert not
    ("target_accuracy" in source)`` -- which asserts the spelling is ABSENT -- credited it as
    PINNED, the same backwards mistake the earlier ``NotIn``/``NotEq`` fix closed one level up
    the tree from."""
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        yield from _effective_comparisons(expr.operand, not negated)
        return
    if isinstance(expr, ast.BoolOp):
        for value in expr.values:
            yield from _effective_comparisons(value, negated)
        return
    if isinstance(expr, ast.Compare):
        own_negative = any(isinstance(op, NEGATIVE_COMPARISONS) for op in expr.ops)
        yield (expr, negated == own_negative)
        return
    for child in ast.iter_child_nodes(expr):
        if isinstance(child, ast.expr):
            yield from _effective_comparisons(child, negated)


def _tainted_operand_constants(compare: ast.Compare, tainted: set[str]) -> set[str]:
    """String constants found in ``compare``'s own operands (``compare.left`` and every
    ``compare.comparators``), gated on at least ONE of those SAME operands referencing a
    tainted name -- not merely on some unrelated tainted name appearing anywhere else in the
    enclosing statement, which is the gap a reviewer isolated synthetically: ``assert
    len(source) > 0 and "min_coverage" in "<hand-typed literal>"`` has a tainted name
    (``source``) in its first half and the spelling in its second, but the two never touch
    each other -- the ``"min_coverage" in "<hand-typed literal>"`` comparison's own two
    operands are a bare string constant and a different, hand-typed string constant, neither
    of which is ``source`` or anything derived from it. Gating per-comparison on its own
    operands, not per-statement on the statement's full name set, is what closes this: this
    specific ``Compare`` node's operands reference no tainted name, so it contributes nothing,
    regardless of what the sibling half of the ``and`` does."""
    operands = (compare.left, *compare.comparators)
    if not any(tainted & _ast_names(operand) for operand in operands):
        return set()
    found: set[str] = set()
    for operand in operands:
        for const in ast.walk(operand):
            if isinstance(const, ast.Constant) and isinstance(const.value, str):
                found.add(const.value)
    return found


def _locally_defined_function_names(tree: ast.AST) -> set[str]:
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _extraction_checked(name: str, func: ast.FunctionDef) -> bool:
    """True if ``name`` is checked, anywhere in ``func``, by the ONE narrow idiom the
    extraction route (below) trusts: ``assert <name> is not None`` (either operand order) --
    not merely referenced in some assert, which a reviewer showed is satisfied by an unrelated
    ``not in`` comparison or a wholly disconnected ``assert len(x) > 0``. ``is not None``
    specifically claims "the extraction for this keyword actually matched something in the
    real call"; that is the one fact this idiom can honestly stand for, so it is the only one
    this route accepts."""
    for node in ast.walk(func):
        if not (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)):
            continue
        test = node.test
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.IsNot):
            continue
        sides = (test.left, test.comparators[0])
        if name not in {n for side in sides for n in _ast_names(side)}:
            continue
        if any(isinstance(side, ast.Constant) and side.value is None for side in sides):
            return True
    return False


def _spellings_pinned_by_assertions(
    func: ast.FunctionDef, tainted: set[str], locally_defined: set[str]
) -> set[str]:
    """Objective spellings this one function's assertions pin, by two routes:

    * **Direct.** An ``assert`` whose test expression contains an EFFECTIVELY POSITIVE
      comparison (``_effective_comparisons``, which tracks sign through any enclosing ``not``)
      whose OWN operands include both a reference to a tainted name and a string constant
      naming the spelling (``_tainted_operand_constants`` -- gated per comparison, not per
      statement, so an unrelated tainted reference elsewhere in the same ``assert`` cannot
      license a hand-typed literal comparison that never touches it). This is what a
      reviewer's ``.count('objective="f1"') == 2`` (41, 44), ``objective == "f1"`` (42), and
      ``f"min_coverage={MIN_COVERAGE}"`` f-string (46) all need, and what the two mutation
      findings above this function exist to close: crediting the wrong side of a negative
      comparison, and crediting a spelling that merely co-occurs with taint rather than being
      compared against it.
    * **Extraction.** An assignment ``name = <tainted call>`` to a LOCALLY DEFINED function
      (``locally_defined`` -- never a built-in string/list method such as ``.replace(...)`` or
      ``.count(...)``, which would otherwise let an unrelated tainted expression, such as a
      mutation-proof's own ``source.replace(pinned, "target_accuracy=1.0")``, donate its
      literal argument as if it were a real pin) whose call's own arguments already name the
      spelling being extracted (recipe 42's ``min_coverage = _call_keyword_value(source,
      "select_confidence_threshold", "min_coverage")``) -- the keyword being pinned is a Python
      identifier, never re-stated as a literal in the later assert (``assert min_coverage is
      not None``), so the direct route alone misses it. Credited only when the extracted name
      is checked by the one idiom ``_extraction_checked`` trusts."""
    pinned: set[str] = set()

    for node in ast.walk(func):
        if not isinstance(node, ast.Assert):
            continue
        for compare, positive in _effective_comparisons(node.test):
            if positive:
                pinned |= _tainted_operand_constants(compare, tainted)

    for node in ast.walk(func):
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in tainted
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in locally_defined
        ):
            continue
        target = node.targets[0].id
        if not _extraction_checked(target, func):
            continue
        for const in ast.walk(node.value):
            if isinstance(const, ast.Constant) and isinstance(const.value, str):
                pinned.add(const.value)

    return pinned


def _spellings_pinned_by_production_discrimination(
    func: ast.FunctionDef, production_wrapper_names: set[str], aliases: dict[str, str]
) -> set[str]:
    """Recipe 28's shape, which fits neither route in ``_spellings_pinned_by_assertions``: no
    source text is read at all, and the real call is made inline
    (``helpers.select_margin_threshold(safe, margin)``), never bound to a name the taint tracer
    above can see at all. Pins an objective by tying the REAL production call's own result, via
    ``==``, to a LOCAL re-derivation computed with an explicit keyword -- valid only once a
    separate ``!=`` assert proves that re-derivation differs from a sibling computed with a
    DIFFERENT objective, so the equality could not hold under a keyword swap to that sibling's
    objective (recipe 28's own ``assert by_min_coverage != by_target_accuracy``, immediately
    followed by ``assert helpers.select_margin_threshold(safe, margin) == by_min_coverage``, is
    exactly this non-degeneracy-then-tie shape)."""
    re_derivations: dict[str, str] = {}
    for node in ast.walk(func):
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
        ):
            continue
        resolved = _resolved_call_name(node.value, aliases)
        if resolved is None:
            continue
        objective = _threshold_call_objective(node.value, resolved)
        if objective:
            re_derivations[node.targets[0].id] = objective

    distinguished: set[str] = set()
    for node in ast.walk(func):
        if not (
            isinstance(node, ast.Assert)
            and isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.NotEq)
        ):
            continue
        left_objs = {re_derivations[n] for n in _ast_names(node.test.left) if n in re_derivations}
        right_objs = {
            re_derivations[n] for n in _ast_names(node.test.comparators[0]) if n in re_derivations
        }
        if left_objs and right_objs and left_objs != right_objs:
            distinguished |= left_objs | right_objs

    pinned: set[str] = set()
    for node in ast.walk(func):
        if not (
            isinstance(node, ast.Assert)
            and isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
        ):
            continue
        sides = (node.test.left, node.test.comparators[0])
        has_production_call = any(
            isinstance(n, ast.Call) and _call_func_name(n) in production_wrapper_names
            for side in sides
            for n in ast.walk(side)
        )
        if not has_production_call:
            continue
        for side in sides:
            for name in _ast_names(side):
                if name in re_derivations and re_derivations[name] in distinguished:
                    pinned.add(re_derivations[name])
    return pinned


def _pinned_objective_spellings(recipe_dir_: Path) -> set[str]:
    """Every objective spelling this recipe's ``tests/*.py`` pin, by any of the shapes this
    check recognises, pooled across every test function in every test file. Pooling recipe-wide
    rather than per-obligation is a deliberate scope simplification: every published recipe's
    own threshold calls use one objective per function consistently (no recipe mixes, say,
    ``min_coverage`` in one ``select_confidence_threshold`` call with ``target_accuracy`` in
    another), so there is no live case where pooling lets one call's pin stand in for a
    different call's missing one -- see the pull request body for how this was checked."""
    pinned: set[str] = set()
    tests_dir = recipe_dir_ / "tests"
    if not tests_dir.is_dir():
        return pinned
    production_wrapper_names = _production_wrapper_names(recipe_dir_ / "helpers.py")
    for path in sorted(tests_dir.glob("*.py")):
        text = path.read_text("utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        aliases = _import_aliases(tree)
        taint_producing_names = (
            _locally_source_reading_function_names(tree, text) | production_wrapper_names
        )
        locally_defined = _locally_defined_function_names(tree)
        for func in _test_function_defs(tree):
            tainted = _tainted_names_in_function(func, text, taint_producing_names)
            pinned |= _spellings_pinned_by_assertions(func, tainted, locally_defined)
            pinned |= _spellings_pinned_by_production_discrimination(
                func, production_wrapper_names, aliases
            )
    return pinned


def _objective_token_present(objective: str, needle: str) -> bool:
    """True if ``objective`` appears in ``needle`` as a whole token -- bounded by the start/end
    of the string or a non-identifier character on either side -- not merely as a substring.
    Bare ``objective in needle`` would credit ``"min_coverage"`` from a needle that happens to
    contain it inside a longer, unrelated identifier; no published recipe does this today, but
    the obligation match should not rely on that remaining true by accident, especially for a
    short spelling like ``"f1"``."""
    return re.search(rf"(?<!\w){re.escape(objective)}(?!\w)", needle) is not None


# --------------------------------------------------------------------------------------------
# regression tests for the threshold_objective_pin detection itself, each proving a property
# a recipe's own test suite cannot see: the pin detector's own correctness. All four were
# found by a reviewer's synthetic probes, each isolating one way an earlier draft of the
# detector could be fooled; each is reproduced here as a committed test, not only a hand-run
# probe, per the standing house rule that a fixed defect needs its own regression test.
# --------------------------------------------------------------------------------------------


def _single_test_function(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))


def test_a_credited_spelling_must_be_compared_against_a_tainted_operand():
    """A reviewer isolated the gap synthetically: an earlier version of this detector credited
    a spelling the moment ANY tainted name appeared ANYWHERE in the same ``assert`` statement,
    not specifically compared against it. ``assert len(source) > 0 and "min_coverage" in
    "<hand-typed literal>"`` has a tainted name (``source``) in its first half and the spelling
    in its second, but the two never touch: the ``in`` comparison's own two operands are a bare
    string constant and an unrelated hand-typed string, neither derived from ``source`` at all.
    That must NOT be credited. The positive control alongside it -- ``"min_coverage" in
    source`` -- must still be, so this also proves the fix does not merely refuse everything."""
    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    assert len(source) > 0 and "min_coverage" in "<hand-typed literal>"
"""
    )
    tainted = {"source"}
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "min_coverage" not in pinned, "credited a spelling never compared against taint"

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    assert len(source) > 0 and "min_coverage" in source
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "min_coverage" in pinned, "the positive control (genuinely compared) was not credited"


def test_polarity_through_not_is_tracked():
    """``assert not ("target_accuracy" in source)`` asserts the spelling is ABSENT -- a
    reviewer's synthetic probe found an earlier version of this detector had no handling for
    ``not`` at all, so it credited the spelling as PINNED regardless, exactly backwards and
    exactly the mistake the ``NotIn``/``NotEq`` exclusion exists to prevent one level up the
    tree. Double negation must flip back to positive: ``not ("target_accuracy" not in
    source)`` asserts the spelling IS present, so it must be credited the same as a bare ``in``
    would be."""
    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    assert not ("target_accuracy" in source)
"""
    )
    tainted = {"source"}
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "target_accuracy" not in pinned, "credited a spelling asserted ABSENT via not(x in y)"

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    assert not ("target_accuracy" not in source)
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "target_accuracy" in pinned, "double negation should read positive and be credited"


def test_the_extraction_route_requires_a_locally_defined_function_and_a_real_check():
    """Two findings, both from the same reviewer, about ``_spellings_pinned_by_assertions``'s
    extraction route:

    1. **Not any referencing assert.** An earlier version credited an extracted, tainted name
       the moment it was referenced in ANY assert -- satisfied by an unrelated ``not in`` check
       or a wholly disconnected ``assert len(x) > 0``, neither of which actually verifies the
       extraction succeeded. Only ``assert <name> is not None`` is trusted.
    2. **Not any tainted call.** A recipe's own mutation-proof code can legitimately build a
       tainted string via a built-in method (``source.replace(pinned, "target_accuracy=1.0")``)
       for the specific purpose of testing what a keyword swap *would* look like -- that literal
       must never be credited as a real pin. Restricting the route to calls through a LOCALLY
       DEFINED function (never a bare attribute/method call like ``.replace(``) closes this."""
    tainted = {"source", "extracted", "swapped"}

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    extracted = _call_keyword_value(source, "select_confidence_threshold", "min_coverage")
    assert "nope" not in extracted
    assert len(extracted) > 0
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined={"_call_keyword_value"})
    assert "min_coverage" not in pinned, "credited an extraction checked only by unrelated asserts"

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    swapped = source.replace("min_coverage=min_coverage", "target_accuracy=1.0")
    assert swapped != source
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "target_accuracy" not in pinned, "credited a literal built via a built-in method call"

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    extracted = _call_keyword_value(source, "select_confidence_threshold", "min_coverage")
    assert extracted is not None
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined={"_call_keyword_value"})
    assert "min_coverage" in pinned, "the genuine extraction idiom was not credited"


def test_import_alias_is_resolved_across_notebook_cells_not_per_cell(tmp_path):
    """A notebook's ``from jev_cookbook.evaluation import select_confidence_threshold as X``
    import and the cell that calls ``X(...)`` are essentially never the same cell in practice
    (the import lives in an early setup cell; the call lives in the evaluation cell). A
    reviewer measured that resolving aliases against one cell's own parse tree alone -- what an
    earlier version of ``_threshold_pin_obligations`` did -- means the alias route can never
    actually fire for any notebook: 0 of 46 published recipes have the import and the call in
    the same cell.

    This goes through ``_threshold_pin_obligations`` itself, on a throwaway copy of a real
    recipe's notebook, rather than composing ``_import_aliases``/``_real_threshold_calls`` by
    hand -- an earlier version of this test did exactly that, which meant it kept passing when
    a reviewer reverted the merged-alias loop in ``_threshold_pin_obligations`` (the function
    the bug actually lived in) and replaced it with the old per-cell resolution: the hand-
    composed functions still worked correctly in isolation, so the test proved nothing about
    whether the fix was actually wired into the code path CI runs. Mutating recipe 38's own
    ``setup`` cell (the import) and ``python-rule`` cell (the call) into exactly this alias
    shape, on a throwaway copy, exercises the real function end to end."""
    recipe_dir = tmp_path / "38-abstention-and-review-queues"
    shutil.copytree(REPO / "recipes" / "38-abstention-and-review-queues", recipe_dir)
    nb_path = recipe_dir / "notebook.ipynb"
    notebook = json.loads(nb_path.read_text("utf-8"))
    setup_cell = next(c for c in notebook["cells"] if c.get("id") == "setup")
    rule_cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")

    import_source = cell_source(setup_cell)
    aliased_import = import_source.replace(
        "select_confidence_threshold,", "select_confidence_threshold as _sct,"
    )
    assert aliased_import != import_source, "mutation did not take -- the replace found nothing"
    setup_cell["source"] = [aliased_import]

    call_source = cell_source(rule_cell)
    aliased_call = call_source.replace(
        "threshold = select_confidence_threshold(", "threshold = _sct("
    )
    assert aliased_call != call_source, "mutation did not take -- the replace found nothing"
    rule_cell["source"] = [aliased_call]

    nb_path.write_text(json.dumps(notebook), encoding="utf-8")

    obligations = _threshold_pin_obligations(recipe_dir)
    assert ("cell python-rule", "select_confidence_threshold", "min_coverage") in obligations, (
        f"the aliased call was not resolved by _threshold_pin_obligations itself: {obligations}"
    )


@pytest.mark.parametrize("recipe", guarded_with_template("threshold_objective_pin")())
def test_the_threshold_objective_is_pinned_by_source_spelling(recipe):
    """#244: nothing pins a notebook's threshold-selection OBJECTIVE. A printed f-string literal
    beside the call (``print(f"objective: select_confidence_threshold(..., min_coverage=0.75)")``)
    is hand-written and nothing compares it to the call; a test asserting the resulting
    threshold *value* only pins the objective if no other objective can produce that value,
    which recipe 38's own pool demonstrated is not reliable (``min_coverage=0.75`` and
    ``target_accuracy=1.0`` select the identical threshold there, so swapping the call's keyword
    and leaving the value-pinning test in place left the full suite, the recipe guard, and the
    notebook-freshness check all green with the committed, printed objective line now false).

    What this check requires: for every real ``select_confidence_threshold(``/
    ``select_threshold(`` call this recipe's committed notebook or ``helpers.py`` actually makes
    (``_threshold_pin_obligations``, AST-found so a call-shaped string inside an unrelated
    f-string decoration is never mistaken for the real call, and resolved through a straight
    import alias so an aliased call is never silently invisible either), the objective it
    actually selects -- the keyword name, or the objective string -- must be PINNED somewhere in
    this recipe's tests: an assertion whose truth depends on a value that is, by data-flow
    tracing, really tied to the committed call (``_pinned_objective_spellings`` and the
    functions above it), not merely co-located with a string that happens to name the spelling.
    This recognises every shape the published set currently uses (a direct ``in``/``not in``
    against a read of the real source; an AST-extracted keyword value compared with ``==``; a
    ``.count(...) == n``; an f-string literal; a real production call tied, with a
    non-degeneracy check, to a local re-derivation) because it traces the PROPERTY -- "this
    assertion's truth depends on the real committed call" -- rather than enumerating spellings
    of it, which is exactly the defence CONTRIBUTING.md section 6 shows failing five times over
    for the same reason. A call this check cannot identify an objective for (not observed in the
    published set), or a cell/``helpers.py`` that does not parse as plain Python at all, fails
    here too, rather than being silently skipped."""
    obligations = _threshold_pin_obligations(recipe_dir(recipe))
    if not obligations:
        pytest.skip(
            f"{recipe['slug']}: no select_confidence_threshold/select_threshold call in the "
            "committed notebook or helpers.py"
        )
    pinned = _pinned_objective_spellings(recipe_dir(recipe))
    violations = []
    for location, func_name, objective in obligations:
        if func_name == "<unparseable>":
            violations.append(
                f"{location}: does not parse as plain Python -- this check cannot verify any "
                "threshold call here (an IPython magic, or a real syntax error?)"
            )
            continue
        if objective is None:
            violations.append(
                f"{location} {func_name}(...): objective not identifiable by this check"
            )
            continue
        if not any(_objective_token_present(objective, needle) for needle in pinned):
            violations.append(
                f"{location} {func_name}(...): objective {objective!r} is not pinned by any "
                "assertion in tests/ that this check can tie to the real committed call -- "
                "either compare a string naming it against a real read of the committed "
                "source (notebook.ipynb's cell source, or inspect.getsource(helpers.<fn>)), "
                "or, if you extracted it via a local helper (name = _your_helper(source, ...)), "
                "check the extracted value with `assert name is not None` specifically -- a "
                "bare `assert name` or any other truthiness check is not credited"
            )
    assert not violations, f"{recipe['slug']}: " + "; ".join(violations)
