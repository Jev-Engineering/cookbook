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
                                       live-mode call count equals backend-derived audit evidence,
                                       with strict ``len(responses.json)`` legacy fallback.
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
                                       What an assertion pins is its derived CLAIM (#276): the
                                       truth sense is carried through ``not``, ``and``/``or``,
                                       ``is False``, ``if``-expressions, count thresholds and
                                       ``all``/``any``/``len`` over comprehensions, and only a
                                       claim that the spelling is PRESENT counts; an assert that
                                       does not always run (under ``if``, a loop,
                                       ``pytest.raises``) counts for nothing. A value is tainted
                                       by any read of the committed file (``read_text``,
                                       ``read_bytes``, ``open(...).read()``, ``with open``).
``noul_proposition_gold_coverage``    #283: for every ``Noul`` proposition this check can
                                       reach in the recipe's own code (two or more -- a
                                       battery; fewer reached and the check does not apply),
                                       ``labels.jsonl`` carries at least one gold-true AND one
                                       gold-false row for that proposition in EVERY scored
                                       split. Propositions are reached by calling the recipe's
                                       own zero-argument functions and keeping the
                                       ``Noul``-valued entries of whatever dict each returns
                                       -- never by name or spelling. A builder that requires
                                       an argument is NOT reached (recipe 39; see below), and
                                       the skip says so rather than claiming the recipe builds
                                       fewer than two.
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
* A scripted recipe (``fixtures/responses.json`` does not exist; answers are computed by a
  seeded script in ``helpers.py`` rather than replayed from a stored file -- recipe 36 is the
  first and, as of this writing, only published one) is skipped by three of the checks above,
  for three DIFFERENT reasons (#249). Two early revisions of this module keyed all three skips
  on the same proxy -- "does ``responses.json`` exist" -- which is a correlate of "are this
  recipe's answers stored" and not of what each check actually means; PR #246's review verified
  each skip by hand and found that proxy wrong for one of the three. So each skip below is now
  keyed on the property its own check is about, and the three no longer share one skip
  condition:

  - ``build_fixtures_scaffold`` (G1(a)) is about ``tools/new_recipe.py``'s *replay-mode*
    scaffold for ``tests/test_build_fixtures.py``, and a scripted recipe has no such file by
    construction (``tools/new_recipe.py::build_scripted_fixtures_text`` writes a different
    docstring and never writes ``responses.json`` at all) -- there is nothing for a scripted
    recipe to hold byte-identical, so the skip here is genuinely vacuous and stays keyed on
    ``responses.json``'s absence, which **is** the property for this one check alone.
  - ``stored_answers_strong_form`` (G1(c)) is about whether a recipe re-derives a frozen
    confidence or business threshold independently -- a property of whether the recipe
    *freezes a threshold*, which has nothing to do with whether its answers are stored or
    computed. Keying this skip on ``responses.json`` was the defect #249 found: recipe 36 has
    no stored responses and freezes a confidence gate, so the check was applicable, silently
    skipped, and (before a same-PR fix round renamed the test function the check anchors on)
    would have failed. The skip is now keyed on
    ``_threshold_pin_obligations(recipe_dir(recipe))`` -- the same real-call detector
    ``threshold_objective_pin`` uses to find every genuine ``select_confidence_threshold(``/
    ``select_threshold(`` call in the recipe's committed notebook or ``helpers.py`` -- so a
    scripted recipe with a gate is checked and one without a gate (scripted or not) is skipped
    on the actual absence of anything to re-derive.
  - ``readme_budget_note_matches_stored_answers`` compares the README's count with a
    backend-derived ledger when the notebook adopts ``AuditedBackend``. It verifies the
    ledger's full ordered keys, derived counts, exact replay inventory, anchored source and
    committed output. Fresh offline execution remains the separate notebook CI job's duty.
    Without an audit, the existing strict ``len(responses.json)`` proxy remains; unaudited
    scripted recipes still lack a committed artifact this check can read and retain the
    existing skip. Audited scripted recipes are checked using their actual call ledger.
* ``noul_proposition_gold_coverage`` (#283) discovers a recipe's ``Noul`` propositions by
  CALLING every zero-required-argument function ``helpers.py`` defines (not imports) and
  keeping the ``Noul``-valued entries of any dict each one returns -- the recipe's own code
  builds the questions it sends, so every proposition this finds is one a live run asks about,
  under whatever name the recipe's own code gave it, never a name or spelling this check
  supplies. The converse does not hold: it finds what zero-argument calls reach, not
  everything the recipe builds (recipe 39, below). Measured against the published set, 51
  such function calls across 49 published recipes plus the template (43 of the 50
  ``helpers.py`` modules define at least one) opened no file, printed nothing and raised
  nothing; the calls themselves took about 0.015s, and the whole discovery sweep, including
  ``load_helpers`` for all 50 modules, about 0.2s -- a measurement of today's set, not a
  contract: see
  ``_noul_propositions`` for what those calls include besides question builders. Ten published
  recipes expose two or more ``Noul`` propositions to this route (06, 25, 26, 31, 35, 37, 41,
  42, 44, 48) and every one already carries a gold-true and a gold-false row for every
  proposition in both scored splits, so this check needs no
  ``tests/recipe_guard_known_failures.py`` entry to land.

  KNOWN UNREACHED CASE: recipe 39 builds two ``Noul`` propositions (one per field in
  ``FIELDS``) in one stage-2 request, but through ``build_stage2_questions(which)``, which
  requires an argument, so zero-argument discovery finds none of them. That is a limit of
  the discovery route, not a fact about the recipe, and the skip reason says so. It is also the
  right outcome rather than a gap to close by calling the builder with ``list(FIELDS)``: 39's
  ``labels.jsonl`` records each field's extracted STRING (``{"invoice_number": "4420", ...}``),
  not a per-proposition boolean, so if the builder were reached every row would read gold-true
  and the check would fail the recipe on gold it simply cannot read. Widening discovery to
  argument-taking builders is a design decision this check does not make; a recipe whose
  question builder requires an argument (a feature list, a field list) is not covered by it.

  A recipe with zero or one ``Noul`` proposition reached is skipped, not passed vacuously:
  gold-coverage-per-proposition is the #283 battery property, and a single proposition's
  ``labels.jsonl`` entry in this cookbook is often a bare boolean with no proposition key at
  all (recipes 02, 10, 15), which this check does not attempt to read.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import io
import json
import operator
import re
import shutil
import textwrap
import tokenize
from pathlib import Path
from types import ModuleType

import pytest

from jev_cookbook import Noul, load_helpers
from jev_cookbook import fixtures as jc_fixtures

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
    itself (reversing the substitution the other way).

    The property this check is about is replay-mode fixture scaffolding, which only exists for
    a replay-mode recipe: a scripted recipe's ``tools/new_recipe.py --mode scripted`` scaffold
    (``build_scripted_fixtures_text``) never writes ``responses.json`` and never writes a
    ``tests/test_build_fixtures.py`` for this check to hold byte-identical to anything, so the
    skip below is genuinely vacuous for one, not a proxy standing in for a different property
    (#249)."""
    path = recipe_dir(recipe) / "fixtures" / "responses.json"
    if not path.is_file():
        pytest.skip(
            "scripted recipe: replay-mode scaffold does not apply, no test_build_fixtures.py "
            "to guard (see #249)"
        )
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
    the weak one (proven on recipe 14 in scratch) correctly fails this check.

    The property this check is *about* is whether the recipe freezes a confidence or business
    threshold at all -- not whether its answers happen to be stored in ``responses.json``
    (#249). A scripted recipe (no ``fixtures/responses.json``, answers computed instead of
    replayed) that freezes a gate has exactly the same obligation to re-derive it as a recipe
    whose answers are stored; whether the answers came from a file or a function says nothing
    about whether a threshold exists to re-derive. So the skip below is keyed on
    ``_threshold_pin_obligations`` -- the same real-call detector ``threshold_objective_pin``
    already uses to find every genuine ``select_confidence_threshold(``/``select_threshold(``
    call in this recipe's committed notebook or ``helpers.py`` -- rather than on
    ``responses.json``'s existence, which is a correlate of "has stored answers", not of "has a
    threshold"."""
    if recipe["slug"] != "_template" and not _threshold_pin_obligations(recipe_dir(recipe)):
        pytest.skip(
            "no real select_confidence_threshold(/select_threshold( call in this recipe's "
            "notebook or helpers.py: this recipe freezes no threshold for G1(c) to re-derive"
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


def test_stored_answers_strong_form_skip_fires_only_when_no_threshold_is_frozen(tmp_path):
    """#249: the skip above is keyed on ``_threshold_pin_obligations`` finding no real
    ``select_confidence_threshold(``/``select_threshold(`` call in the recipe's notebook or
    ``helpers.py`` -- the property G1(c) is about -- rather than on whether
    ``fixtures/responses.json`` exists. Proving a skip condition needs both directions (a skip
    that never skips is as wrong as one that always does):

    1. **Fires when no threshold is frozen.** On a throwaway copy of recipe 36 (the one
       published scripted recipe, chosen because it has no ``responses.json`` and would have
       been silently skipped by the OLD condition regardless of this property), deleting its
       one real ``select_confidence_threshold(`` call and import leaves
       ``_threshold_pin_obligations`` empty -- the input the skip's ``not ...`` branches on.
    2. **Does not fire when a threshold is frozen.** The unmodified recipe 36 is used elsewhere
       in this module's own parametrized run
       (``test_stored_answers_are_not_all_right_is_the_strong_form[36-card-game-action-
       selection]``) and is observed there to PASS, not skip -- it has a confidence gate and
       the strong-form test re-derives it, so the property is true and the check runs for real.
       That parametrized case is the live, continuously-run proof for this direction; this test
       supplies the complementary one a synthetic mutation is needed for."""
    recipe_dir_copy = tmp_path / "36-card-game-action-selection"
    shutil.copytree(REPO / "recipes" / "36-card-game-action-selection", recipe_dir_copy)

    assert _threshold_pin_obligations(recipe_dir_copy), (
        "sanity check failed: the unmodified copy already has no threshold obligations"
    )

    nb_path = recipe_dir_copy / "notebook.ipynb"
    notebook = json.loads(nb_path.read_text("utf-8"))
    setup_cell = next(c for c in notebook["cells"] if c.get("id") == "setup")
    rule_cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")

    import_source = cell_source(setup_cell)
    stripped_import = import_source.replace("    select_confidence_threshold,\n", "")
    assert stripped_import != import_source, "mutation did not take -- the replace found nothing"
    setup_cell["source"] = [stripped_import]

    rule_source = cell_source(rule_cell)
    stripped_call = rule_source.replace(
        "threshold = select_confidence_threshold(val_correct, val_confidence, "
        "min_coverage=MIN_COVERAGE)",
        "threshold = 0.5  # no real threshold-selection call left",
    )
    assert stripped_call != rule_source, "mutation did not take -- the replace found nothing"
    rule_cell["source"] = [stripped_call]

    nb_path.write_text(json.dumps(notebook), encoding="utf-8")

    obligations = _threshold_pin_obligations(recipe_dir_copy)
    assert obligations == [], (
        f"expected no threshold obligations once the real call is gone, got {obligations}"
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

NEIGHBOUR_LINK = re.compile(r"\]\(\.\./((?:[0-9]{2}|100)-[a-z0-9-]+)/\)")


def test_recipe_100_next_steps_link_must_resolve_to_a_published_notebook(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "RECIPES_DIR", tmp_path)
    source = tmp_path / "01-source"
    source.mkdir()
    target = "100-multimodal-agent-handoff-verification"
    (source / "notebook.ipynb").write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "markdown",
                        "id": "next-md",
                        "source": f"[Handoff](../{target}/)",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="100-multimodal-agent-handoff-verification"):
        test_next_steps_links_resolve_to_a_published_recipe({"slug": source.name})
    (tmp_path / target).mkdir()
    (tmp_path / target / "notebook.ipynb").write_text("{}", encoding="utf-8")
    test_next_steps_links_resolve_to_a_published_recipe({"slug": source.name})


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
# check 8b: the live budget note matches backend evidence or the strict legacy proxy
# --------------------------------------------------------------------------------------------

LIVE_CALL_COUNT = re.compile(
    r"makes\s+exactly\s+(?:\*\*)?(\d+)(?:\*\*)?\s+(?:calls?|requests?)\b"
    r"|makes\s+exactly\s+one\s+(?:call|request)\s+for\s+each\s+of\s+(?:the\s+)?(\d+)\b"
)


def _load_request_audit() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "request_audit_for_recipe_guard", Path(__file__).resolve().parent / "request_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_request_audit = _load_request_audit()


@pytest.mark.parametrize("recipe", guarded("readme_budget_note_matches_stored_answers")())
def test_the_live_budget_note_matches_the_stored_answer_count(recipe):
    """Actual decide calls and distinct fixture keys are different quantities.

    An audited notebook prints the shared backend's complete ordered call ledger in its
    final cell. The source/output verifier checks that binding, recomputes both counts,
    and demands exact coverage of responses.json's keys. Repeated identical requests
    count independently. Freshness is enforced by the separate offline notebook job.

    Recipes without audit evidence keep the existing strict fixture-count proxy (and
    the existing unaudited-scripted skip); malformed audits never use that fallback.
    """
    path = recipe_dir(recipe) / "fixtures" / "responses.json"
    keys = set(json.loads(path.read_text("utf-8"))) if path.is_file() else None
    actual = _request_audit.audited_call_count(notebook_cells(recipe_dir(recipe)), keys)
    if actual is None:
        if keys is None:
            pytest.skip(
                "scripted recipe: no responses.json or committed backend request audit; "
                "actual decide() count requires execution evidence (see #249)"
            )
        actual = len(keys)
    readme = (recipe_dir(recipe) / "README.md").read_text("utf-8")
    assert "## Switch to live" in readme
    section = readme.split("## Switch to live", 1)[1].split("## What was", 1)[0]
    match = LIVE_CALL_COUNT.search(section)
    assert match, f"{recipe['slug']}: no recognisable live-call-count sentence in README.md"
    stated = int(next(g for g in match.groups() if g))
    assert stated == actual, (
        f"{recipe['slug']}: README states {stated}, backend audit or legacy fixture count is {actual}"
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
    if _module_is_marked_not_to_run(tree):
        return []
    candidates: list[ast.FunctionDef] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.FunctionDef):
            candidates.append(node)
        elif isinstance(node, ast.ClassDef):
            candidates.extend(n for n in node.body if isinstance(n, ast.FunctionDef))
    return [
        node
        for node in candidates
        if node.name.startswith("test_") and not _is_marked_not_to_run(node.decorator_list)
    ]


_NOT_RUN_MARKS = frozenset({"skip", "skipif", "xfail"})


def _is_marked_not_to_run(decorators: list[ast.expr]) -> bool:
    """True if a decorator list carries ``pytest.mark.skip`` / ``skipif`` / ``xfail`` (bare or
    called): the asserts of such a test do not (reliably) run, so they pin nothing."""
    for decorator in decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in _NOT_RUN_MARKS:
            return True
    return False


def _module_is_marked_not_to_run(tree: ast.AST) -> bool:
    """A module-level ``pytestmark = pytest.mark.skip(...)`` (or a list holding one)."""
    for node in getattr(tree, "body", []):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
            and _is_marked_not_to_run(
                list(node.value.elts)
                if isinstance(node.value, ast.List | ast.Tuple)
                else [node.value]
            )
        ):
            return True
    return False


_ARTEFACT_FILE_NAMES = ("notebook.ipynb", "helpers.py")

# Names pytest gives a test its scratch directory under. A path rooted there is a COPY a test made
# (usually to mutate it), not the committed artefact, so a read of it does not taint.
_SCRATCH_DIR_NAMES = frozenset({"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory"})

# Callables that read a file's contents. This is the set of ways Python spells "read this file",
# not a set of spellings of an objective: it only decides whether a statement that names the
# committed artefact also READS it (as opposed to merely mentioning its name in a string), so a
# read via ``open(...).read()``, ``read_bytes()`` or ``with open(...) as f: f.read()`` seeds taint
# exactly as ``read_text()`` does.
_FILE_READ_ATTRS = frozenset({"read_text", "read_bytes", "read", "readlines", "open"})


def _mentions_artefact_file(node: ast.AST) -> bool:
    """True if ``node`` contains a string that IS one of the committed file names (or a path
    ending in ``/<name>``) -- not a longer name that merely contains it (``expected_helpers.py``)."""
    return any(
        isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and any(n.value == name or n.value.endswith("/" + name) for name in _ARTEFACT_FILE_NAMES)
        for n in ast.walk(node)
    )


def _mentions_scratch_dir(node: ast.AST) -> bool:
    return any(
        (isinstance(n, ast.Name) and n.id in _SCRATCH_DIR_NAMES)
        or (isinstance(n, ast.arg) and n.arg in _SCRATCH_DIR_NAMES)
        for n in ast.walk(node)
    )


def _performs_a_file_read(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Name) and n.func.id == "open":
            return True
        if isinstance(n.func, ast.Attribute) and n.func.attr in _FILE_READ_ATTRS:
            return True
    return False


def _reads_helpers_source_via_inspect(node: ast.AST) -> bool:
    for n in ast.walk(node):
        is_getsource = isinstance(n, ast.Call) and (
            (isinstance(n.func, ast.Attribute) and n.func.attr == "getsource")
            or (isinstance(n.func, ast.Name) and n.func.id == "getsource")
        )
        if not is_getsource:
            continue
        for inner in ast.walk(n):
            if isinstance(inner, ast.Name) and "helpers" in inner.id:
                return True
            if isinstance(inner, ast.Attribute) and "helpers" in inner.attr:
                return True
    return False


def _reads_real_committed_source(node: ast.AST) -> bool:
    """True if one piece of syntax (a single statement's value expression, a ``with`` item's
    context expression, or a whole function definition -- see ``_tainted_names_in_function`` and
    ``_locally_source_reading_function_names`` below) is the actual FILE READ of the *actual
    committed* notebook or ``helpers.py`` -- not a hand-typed duplicate of either, and not a
    later step of the same chain (extracting one cell, then joining its ``"source"``) that never
    itself mentions the file at all. That later step is carried by the generic name-reference
    propagation in ``_tainted_names_in_function``, which is why this function only needs to see
    the read itself (this used to also require ``"source"`` in the same statement as
    ``"notebook.ipynb"``, false for the template's own three-line chain).

    The property is "this syntax names the committed artefact AND performs a read": derived
    from the AST (a ``Call`` to ``open``, or to a ``read``-family method), not from the literal
    text ``read_text``. The earlier text test required that one spelling, so ``open(...).read()``
    and ``read_bytes()`` -- plainly real reads of the committed source -- produced no taint at
    all and a legitimate pin written that way was refused for how its read was spelled (#276).
    The second route is ``inspect.getsource(...)`` on something named ``helpers``, for a test
    that checks a helpers function's own source rather than a file."""
    return (
        _mentions_artefact_file(node)
        and _performs_a_file_read(node)
        and not _mentions_scratch_dir(node)
    ) or _reads_helpers_source_via_inspect(node)


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
            if _reads_real_committed_source(node):
                names.add(node.name)
    return names


def _tainted_names_in_function(
    func: ast.FunctionDef, text: str, taint_producing_names: set[str]
) -> set[str]:
    """Fixed-point taint set, local to one test function: a name is tainted if the statement
    assigning it (a) itself reads the real committed source (``_reads_real_committed_source`` on
    that one assignment's value -- the inline case: recipes 38, 39, 41, 43, 45, the template),
    (b) calls a function named in ``taint_producing_names`` (a source-reading helper defined
    anywhere in this file, or a ``helpers.py`` wrapper that itself makes the real selection call
    -- recipes 28, 42, 44), or (c) its value expression references an already-tainted name
    anywhere, including as a call argument (plain data-flow propagation -- recipe 42's
    ``_call_keyword_value(source, ...)``, whose own definition never mentions
    ``notebook.ipynb`` at all, but whose result still structurally depends on it because its
    argument, ``source``, does). The binding of ``with open(<committed file>) as f`` is the same
    read in statement form, so ``f`` is tainted by the same rules and ``f.read()`` then carries
    the taint on by (c). Scoped to one function at a time (never a whole-file flat
    namespace): a name is only ever compared against taint computed within the SAME function,
    so an unrelated function's own local variable sharing a common name (``source``, ``cell``)
    can never borrow another function's taint."""
    tainted: set[str] = set()

    bindings: dict[str, list[ast.AST]] = {}
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            bindings.setdefault(node.targets[0].id, []).append(node.value)
        elif isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.optional_vars, ast.Name):
                    bindings.setdefault(item.optional_vars.id, []).append(item.context_expr)

    # names that hold a COPY under pytest's scratch directory (the fixture parameter itself, and
    # anything assigned from it): a read of those is a read of a test-made copy, not of the
    # committed artefact
    scratch = set(_SCRATCH_DIR_NAMES)  # the fixture parameter (or any use of its name)
    grew = True
    while grew:
        grew = False
        for name, values in bindings.items():
            if name not in scratch and any(scratch & _ast_names(v) for v in values):
                scratch.add(name)
                grew = True

    def _taints(value: ast.AST) -> bool:
        if scratch & _ast_names(value):
            return False
        calls_taint_producing = any(
            isinstance(n, ast.Call) and _call_func_name(n) in taint_producing_names
            for n in ast.walk(value)
        )
        return (
            _reads_real_committed_source(value)
            or calls_taint_producing
            or bool(tainted & _ast_names(value))
        )

    # A name is tainted only if EVERY binding of it in the function is: ``source = <read>`` followed
    # by ``source = "<hand typed>"`` leaves a name whose value at the assert is the hand-typed one.
    changed = True
    while changed:
        changed = False
        for name, values in bindings.items():
            if name not in tainted and all(_taints(v) for v in values):
                tainted.add(name)
                changed = True
    return tainted


def _is_plain_open_with(node: ast.With) -> bool:
    """A ``with open(...) as f:`` (or ``path.open()``) block: it runs its body exactly once,
    unconditionally, so asserts inside it are as unconditional as the statement itself. Any other
    context manager is not assumed to behave that way -- ``pytest.raises(AssertionError)`` inverts
    the sense of every assert inside it, and ``contextlib.suppress`` can swallow them."""
    return all(
        isinstance(item.context_expr, ast.Call)
        and (
            (isinstance(item.context_expr.func, ast.Name) and item.context_expr.func.id == "open")
            or (
                isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "open"
            )
        )
        for item in node.items
    )


def _unconditional_asserts(body: list[ast.stmt]) -> list[ast.Assert]:
    """The ``assert`` statements in ``body`` that always run when the test does: direct
    statements of the function, those inside a plain ``with open(...)`` block, and those in the
    body of a ``for`` loop over a visibly non-empty literal tuple/list/set (no ``break``,
    ``continue`` or ``return`` in it), which runs for every element. Collection STOPS at the first
    statement that can end the test early (a ``return``, a ``raise`` or a ``pytest.skip`` /
    ``xfail`` / ``exit`` / ``fail`` call, including one under an ``if``): an assert after it may
    never run. An assert under an ``if``, any other loop, a ``try``, a nested function, or ``with
    pytest.raises(...)`` is NOT included, because its effective truth sense depends on a context
    this check cannot see: ``if cond: assert "x" in source`` pins nothing when ``cond`` is false,
    and ``with pytest.raises(AssertionError): assert "x" in source`` claims the spelling is
    ABSENT. Not crediting those is the fail-closed direction (a loud refusal, never a silent
    pass). A test marked ``skip``/``skipif``/``xfail`` is not considered at all
    (``_test_function_defs``)."""
    return _collect_unconditional_asserts(body)[0]


_LEAVING_CALL_NAMES = frozenset({"skip", "xfail", "exit", "fail", "importorskip", "_exit"})


def _walk_same_scope(node: ast.AST):
    """``ast.walk`` that does not descend into nested functions, lambdas or classes (a ``return``
    in a nested helper does not end the test)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for child in ast.iter_child_nodes(current):
            if not isinstance(
                child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef
            ):
                stack.append(child)


def _may_leave_the_test(stmt: ast.stmt, *, loop_exits: bool = False) -> bool:
    """True if running ``stmt`` can end the test (or, with ``loop_exits``, skip the rest of the
    enclosing loop body) before the statements after it run: a ``return``, a ``raise``, or a
    call to ``pytest.skip`` / ``xfail`` / ``exit`` / ``fail`` (anywhere inside it, including under
    an ``if``). An assert placed after such a statement may never run."""
    for node in _walk_same_scope(stmt):
        if isinstance(node, ast.Return | ast.Raise):
            return True
        if loop_exits and isinstance(node, ast.Break | ast.Continue):
            return True
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in _LEAVING_CALL_NAMES:
                return True
    return False


def _collect_unconditional_asserts(body: list[ast.stmt]) -> tuple[list[ast.Assert], bool]:
    """``(asserts, completed)``: the asserts that always run, and whether control provably reaches
    the end of ``body`` (``False`` once a statement that can leave the test was met, after which
    nothing further is credited). Direct statements count; a plain ``with open(...)`` block counts
    through its body; a ``for`` loop over a visibly non-empty literal display counts through its
    body when the body cannot ``break``/``continue``/``return`` (it then runs once per element)."""
    found: list[ast.Assert] = []
    for stmt in body:
        if isinstance(stmt, ast.Assert):
            found.append(stmt)
        elif isinstance(stmt, ast.With) and _is_plain_open_with(stmt):
            inner, completed = _collect_unconditional_asserts(stmt.body)
            found.extend(inner)
            if not completed:
                return found, False
        elif (
            isinstance(stmt, ast.For)
            and _provably_nonempty(stmt.iter, frozenset())
            and not any(_may_leave_the_test(s, loop_exits=True) for s in stmt.body)
            and not stmt.orelse
        ):
            found.extend(_collect_unconditional_asserts(stmt.body)[0])
        elif _may_leave_the_test(stmt):
            return found, False
    return found, True


# --------------------------------------------------------------------------------------------
# effective truth sense (#276): what does an assert CLAIM about a spelling?
#
# The earlier walk yielded every ``ast.Compare`` under an assert and tracked only an enclosing
# ``not`` and the comparison's own ``not in``/``!=``/``is not``, so negation expressed as a VALUE
# (``("x" in source) is False``), by a COUNT (``source.count("x") == 0``), by CONTEXT (an
# ``IfExp`` branch) or inside a comprehension (``len([m for m in ... if "x" in m]) == 0``) was
# invisible, and a spelling asserted ABSENT was credited as PRESENT. A blacklist of those
# spellings is the wrong shape (CONTRIBUTING.md section 6's list was evaded five times), so
# this derives the property instead: ``_entailed_spellings(expr, truth, ...)`` answers "if
# ``expr`` evaluates to ``truth``, which spellings must be present in the committed source?",
# recursing structurally so every layer (``not``, ``and``/``or``, ``if``-expressions, ``is False``,
# numeric thresholds on counts, ``all``/``any``/``len`` over comprehensions) contributes its own
# sign. Anything the recursion does not understand entails NOTHING, so an unrecognised idiom is
# refused loudly rather than credited silently.
# --------------------------------------------------------------------------------------------

_NUMERIC_COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_MIRRORED = {
    ast.Eq: ast.Eq,
    ast.NotEq: ast.NotEq,
    ast.Lt: ast.Gt,
    ast.LtE: ast.GtE,
    ast.Gt: ast.Lt,
    ast.GtE: ast.LtE,
}
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp)


def _literal_text(node: ast.AST) -> set[str] | None:
    """The literal text a hand-written needle expression stands for: a ``str``/``bytes``
    constant, the constant parts of an f-string, or the literal parts of a ``+`` / ``%`` join of
    those. ``None`` when ``node`` contributes no literal text at all (a name, a call...)."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return {node.value}
        if isinstance(node.value, bytes):
            return {node.value.decode("utf-8", "replace")}
        return None
    if isinstance(node, ast.JoinedStr):
        parts = {
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        }
        return parts or None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Mod):
        pieces = [p for p in (_literal_text(node.left), _literal_text(node.right)) if p]
        return set().union(*pieces) if pieces else None
    return None


def _truth_literal(literal: ast.AST, value: ast.AST) -> bool | None:
    """If ``literal`` is a ``True``/``False`` constant (or ``1``/``0`` standing opposite a
    boolean-valued expression), the truth value it names; else ``None``."""
    if not isinstance(literal, ast.Constant):
        return None
    if type(literal.value) is bool:
        return literal.value
    if (
        type(literal.value) is int
        and literal.value in (0, 1)
        and isinstance(value, ast.Compare | ast.BoolOp | ast.UnaryOp)
    ):
        return bool(literal.value)
    return None


def _taint_through_comprehension(comp: ast.expr, tainted: frozenset[str]) -> frozenset[str]:
    """``tainted`` as seen INSIDE the comprehension: each generator's target names are tainted when
    the iterable it ranges over is wholly tainted (``for s in sources`` with ``sources`` tainted
    is what lets ``all("min_coverage" in s for s in sources)`` be traced to the real committed
    source) and are SHADOWED -- removed from the set -- when it is not, so ``any("x" in source for
    source in ["x"])`` does not borrow the outer ``source``'s taint, and neither does an iterable
    that mixes the real read with a hand-typed copy of the needle."""
    out = set(tainted)
    for gen in comp.generators:
        targets = _ast_names(gen.target)
        if _wholly_tainted(gen.iter, frozenset(out)):
            out |= targets
        else:
            out -= targets
    return frozenset(out)


def _wholly_tainted(node: ast.AST, tainted: frozenset[str]) -> bool:
    """True if EVERY value ``node`` can produce comes from tainted data, not merely if it
    mentions a tainted name somewhere: a display is wholly tainted only if each element is, a
    ``+`` or ``or`` only if each operand is, a hand-typed literal never is. Calls, subscripts and
    attributes are wholly tainted when they reference a tainted name (``notebook["cells"]``,
    ``"".join(cell["source"])``): data flowing out of the read stays tainted."""
    if isinstance(node, ast.Constant | ast.JoinedStr):
        return False
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return bool(node.elts) and all(
            _wholly_tainted(e.value if isinstance(e, ast.Starred) else e, tainted)
            for e in node.elts
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _wholly_tainted(node.left, tainted) and _wholly_tainted(node.right, tainted)
    if isinstance(node, ast.BoolOp):
        return all(_wholly_tainted(v, tainted) for v in node.values)
    if isinstance(node, ast.IfExp):
        return _wholly_tainted(node.body, tainted) and _wholly_tainted(node.orelse, tainted)
    return bool(tainted & _ast_names(node))


def _embeds_text(node: ast.AST, texts: set[str]) -> bool:
    """True if a hand-typed string inside ``node`` contains one of ``texts`` -- the needle was
    smuggled into the value it is compared with (``kws.get("objective", "min_coverage") ==
    "min_coverage"``, ``source.replace("a", "min_coverage")``), so the comparison holds whatever
    the committed source says."""
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str | bytes):
            value = n.value if isinstance(n.value, str) else n.value.decode("utf-8", "replace")
            if any(t in value for t in texts):
                return True
    return False


def _credible_source_operand(node: ast.AST, texts: set[str], tainted: frozenset[str]) -> bool:
    """The operand a needle is compared against really is the committed source (wholly tainted)
    and does not itself contain the needle as a hand-typed string."""
    return _wholly_tainted(node, tainted) and not _embeds_text(node, texts)


def _provably_nonempty(iterable: ast.expr, nonempty: frozenset[str]) -> bool:
    if isinstance(iterable, ast.List | ast.Tuple | ast.Set):
        return bool(iterable.elts) and not any(isinstance(e, ast.Starred) for e in iterable.elts)
    return isinstance(iterable, ast.Name) and iterable.id in nonempty


_CONTAINER_VALUES = (
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
)


def _name_bindings(func: ast.FunctionDef, name: str) -> list[ast.AST | None]:
    """Every binding of ``name`` in ``func``: the assigned value for a plain ``name = value``, and
    ``None`` for any other way of (re)binding or deleting it (augmented assignment, ``for``
    target, tuple unpacking, ``with ... as``, walrus, ``del``, comprehension target)."""
    values: list[ast.AST | None] = []
    plain_targets: set[int] = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            values.append(node.value)
            plain_targets.add(id(node.targets[0]))
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Name)
            and node.id == name
            and isinstance(node.ctx, ast.Store | ast.Del)
            and id(node) not in plain_targets
        ):
            values.append(None)
    return values


def _mutated_in_place(func: ast.FunctionDef, name: str) -> bool:
    """``name.<anything>(...)`` (``clear``, ``pop``, ``remove``...) or a subscript store/delete on
    ``name``: the container may not hold what it was bound to."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
        ):
            return True
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store | ast.Del)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
        ):
            return True
    return False


def _asserted_nonempty_names(func: ast.FunctionDef) -> frozenset[str]:
    """Names this function establishes as non-empty before an ``all(...)`` over them can mean
    anything (``all`` over an empty iterable is vacuously true and pins nothing). A name counts
    only if it is bound ONCE in the function and never mutated in place (so a later
    ``sources = []`` or ``sources.clear()`` cannot empty it behind the evidence), and then by:

    * being bound to a non-empty literal list/tuple/set; or
    * an unconditional ``assert len(name) > 0`` / ``>= 1`` / ``!= 0`` / ``== n`` (``n > 0``); or
    * an unconditional bare ``assert name`` when the single binding is a container display or
      list/set/dict comprehension -- NOT a generator, which is always truthy."""
    candidates: dict[str, str] = {}  # name -> how it was shown non-empty
    asserted_len: set[str] = set()
    asserted_bare: set[str] = set()
    for assert_ in _unconditional_asserts(func.body):
        conjuncts = (
            assert_.test.values
            if isinstance(assert_.test, ast.BoolOp) and isinstance(assert_.test.op, ast.And)
            else [assert_.test]
        )
        for conjunct in conjuncts:
            if isinstance(conjunct, ast.Name):
                asserted_bare.add(conjunct.id)
            elif (
                isinstance(conjunct, ast.Compare)
                and len(conjunct.ops) == 1
                and isinstance(conjunct.left, ast.Call)
                and isinstance(conjunct.left.func, ast.Name)
                and conjunct.left.func.id == "len"
                and len(conjunct.left.args) == 1
                and isinstance(conjunct.left.args[0], ast.Name)
                and isinstance(conjunct.comparators[0], ast.Constant)
                and type(conjunct.comparators[0].value) in (int, float)
                and type(conjunct.ops[0]) in _NUMERIC_COMPARE
                and not _NUMERIC_COMPARE[type(conjunct.ops[0])](0, conjunct.comparators[0].value)
            ):
                asserted_len.add(conjunct.left.args[0].id)
    assigned = {
        n.targets[0].id
        for n in ast.walk(func)
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
    }
    for name in assigned | asserted_len:
        if _mutated_in_place(func, name):
            continue
        bindings = _name_bindings(func, name)
        if len(bindings) > 1:
            continue
        value = bindings[0] if bindings else None
        if value is not None and _provably_nonempty(value, frozenset()):
            candidates[name] = "literal"
        elif name in asserted_len:
            candidates[name] = "len"
        elif name in asserted_bare and isinstance(value, _CONTAINER_VALUES):
            candidates[name] = "truthy container"
    return frozenset(candidates)


def _exists_entailed(
    comp: ast.expr,
    elt_truth: bool | None,
    tainted: frozenset[str],
    nonempty: frozenset[str],
) -> set[str]:
    """Spellings entailed by "some element of ``comp`` survives its filters (and, when
    ``elt_truth`` is not ``None``, its element expression evaluates to ``elt_truth``)": the
    conjunction of every filter being true for that one element, with the comprehension variable
    tainted when it ranges over tainted data."""
    inner = _taint_through_comprehension(comp, tainted)
    out: set[str] = set()
    for gen in comp.generators:
        for condition in gen.ifs:
            out |= _entailed_spellings(condition, True, inner, nonempty)
    if elt_truth is not None:
        out |= _entailed_spellings(comp.elt, elt_truth, inner, nonempty)
    return out


def _forall_entailed(
    comp: ast.expr, elt_truth: bool, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str]:
    """Spellings entailed by "EVERY element of ``comp`` evaluates to ``elt_truth``". Only
    meaningful when there is at least one element and no filter narrows which ones count, so a
    filtered comprehension, or an iterable not provably non-empty, entails nothing."""
    if any(gen.ifs for gen in comp.generators):
        return set()
    if not all(_provably_nonempty(gen.iter, nonempty) for gen in comp.generators):
        return set()
    inner = _taint_through_comprehension(comp, tainted)
    return _entailed_spellings(comp.elt, elt_truth, inner, nonempty)


def _quantity_spellings(
    node: ast.AST, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str] | None:
    """``None`` unless ``node`` is a COUNT of something in the committed source:
    ``<tainted>.count(<needle>)``, ``len(<comprehension>)``, ``len(<tainted>)`` or
    ``sum(1 for ...)``. When it is, the spellings whose presence a count greater than zero
    entails (the needle of a ``.count``, the filters of a comprehension)."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "count" and node.args:
        if tainted & _ast_names(func.value):
            needle = _literal_text(node.args[0]) or set()
            if not _credible_source_operand(func.value, needle, tainted):
                return set()  # still a count, but of something that is not the committed source
            return needle
        return None
    if isinstance(func, ast.Name) and len(node.args) == 1:
        arg = node.args[0]
        if func.id == "len":
            if isinstance(arg, _COMPREHENSIONS):
                return _exists_entailed(arg, None, tainted, nonempty)
            return set() if tainted & _ast_names(arg) else None
        if func.id == "sum" and isinstance(arg, _COMPREHENSIONS):
            # ``sum(1 for ...)`` counts the elements that survive the filters; ``sum(<bool or
            # count> for ...)`` is positive only if some element's term is true / positive
            counts_elements = isinstance(arg.elt, ast.Constant) and arg.elt.value == 1
            return _exists_entailed(arg, None if counts_elements else True, tainted, nonempty)
    return None


def _combine(parts: list[set[str]], all_must_hold: bool) -> set[str]:
    """What a conjunction (``all_must_hold``: every part is known true, so every part's
    entailments apply) or a disjunction (some part is true, we do not know which, so only what
    EVERY part entails applies) entails."""
    if not parts:
        return set()
    if all_must_hold:
        return set().union(*parts)
    return set.intersection(*parts)


def _entailed_spellings(
    expr: ast.expr, truth: bool, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str]:
    """If ``expr`` evaluates to ``truth``, the spellings that must therefore be PRESENT in the
    committed source. The effective truth sense is carried down the tree: ``not`` flips it,
    ``and``/``or`` apply it to each operand but combine differently (a true ``and`` and a false
    ``or`` know every operand; a false ``and`` and a true ``or`` only know what all operands
    share), an ``if``-expression only entails what BOTH branches do, a comparison against a
    ``True``/``False`` literal re-targets the other operand with the sign that literal implies,
    and a count compared with a number entails presence only when the comparison excludes
    zero. Anything not recognised entails nothing."""
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        return _entailed_spellings(expr.operand, not truth, tainted, nonempty)
    if isinstance(expr, ast.BoolOp):
        parts = [_entailed_spellings(v, truth, tainted, nonempty) for v in expr.values]
        return _combine(parts, isinstance(expr.op, ast.And) == truth)
    if isinstance(expr, ast.IfExp):
        branches = [
            _entailed_spellings(expr.body, truth, tainted, nonempty),
            _entailed_spellings(expr.orelse, truth, tainted, nonempty),
        ]
        return _combine(branches, all_must_hold=False)
    if isinstance(expr, ast.Compare):
        return _compare_entailed(expr, truth, tainted, nonempty)
    if isinstance(expr, ast.Call):
        return _call_entailed(expr, truth, tainted, nonempty)
    return set()


def _call_entailed(
    call: ast.Call, truth: bool, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str]:
    quantity = _quantity_spellings(call, tainted, nonempty)
    if quantity is not None:
        # a bare count used as a condition means "count != 0"
        return quantity if truth else set()
    if not (isinstance(call.func, ast.Name) and len(call.args) == 1):
        return set()
    name, arg = call.func.id, call.args[0]
    if name == "bool":
        return _entailed_spellings(arg, truth, tainted, nonempty)
    if name not in ("all", "any"):
        return set()
    if isinstance(arg, _COMPREHENSIONS):
        if (name == "any") == truth:  # some element satisfies it
            return _exists_entailed(arg, name == "any", tainted, nonempty)
        return _forall_entailed(arg, name == "all", tainted, nonempty)
    if (
        isinstance(arg, ast.List | ast.Tuple | ast.Set)
        and arg.elts
        and not any(isinstance(e, ast.Starred) for e in arg.elts)
    ):
        parts = [_entailed_spellings(e, truth, tainted, nonempty) for e in arg.elts]
        return _combine(parts, (name == "all") == truth)
    return set()


def _compare_entailed(
    compare: ast.Compare, truth: bool, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str]:
    if len(compare.ops) > 1:  # a < b < c is (a < b) and (b < c)
        operands = [compare.left, *compare.comparators]
        parts = [
            _compare_entailed(
                ast.Compare(left=operands[i], ops=[op], comparators=[operands[i + 1]]),
                truth,
                tainted,
                nonempty,
            )
            for i, op in enumerate(compare.ops)
        ]
        return _combine(parts, all_must_hold=truth)
    left, op, right = compare.left, compare.ops[0], compare.comparators[0]
    op_type = type(op)

    # (a) a boolean-valued operand compared with a True/False literal: ``(x in s) is False``
    if isinstance(op, ast.Eq | ast.NotEq | ast.Is | ast.IsNot):
        for value, literal in ((left, right), (right, left)):
            wanted = _truth_literal(literal, value)
            if wanted is not None:
                positive = isinstance(op, ast.Eq | ast.Is)
                inner = wanted if positive == truth else (not wanted)
                return _entailed_spellings(value, inner, tainted, nonempty)

    # (b) a count compared with a number: presence is entailed only if the claim excludes zero
    for quantity_side, number_side, mirrored in ((left, right, False), (right, left, True)):
        quantity = _quantity_spellings(quantity_side, tainted, nonempty)
        if quantity is None:
            continue
        cmp_type = _MIRRORED.get(op_type) if mirrored else op_type
        if (
            cmp_type not in _NUMERIC_COMPARE
            or not isinstance(number_side, ast.Constant)
            or type(number_side.value) not in (int, float)
        ):
            return set()
        zero_is_consistent = _NUMERIC_COMPARE[cmp_type](0, number_side.value) == truth
        return set() if zero_is_consistent else quantity

    # (c) membership / equality: credited only when the comparison effectively says "equal" or
    # "contained", and one side is a hand-written needle while the other is derived from the
    # committed source
    if not isinstance(op, ast.In | ast.NotIn | ast.Eq | ast.NotEq | ast.Is | ast.IsNot):
        return set()
    if isinstance(op, ast.In | ast.Eq | ast.Is) != truth:
        return set()
    if isinstance(op, ast.In | ast.NotIn):
        needle = _literal_text(left)
        if needle and _credible_source_operand(right, needle, tainted):
            return needle
        return set()
    found: set[str] = set()
    for value, literal in ((left, right), (right, left)):
        text = _literal_text(literal)
        if text and _literal_text(value) is None and _credible_source_operand(value, text, tainted):
            found |= text
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
    this route accepts. Only an assert that always runs counts (``_unconditional_asserts``)."""
    for node in _unconditional_asserts(func.body):
        if not isinstance(node.test, ast.Compare):
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

    * **Direct.** An unconditional ``assert`` whose EFFECTIVE CLAIM, derived by
      ``_entailed_spellings`` (the truth sense carried through ``not``, ``and``/``or``,
      ``is False``, ``if``-expressions, count thresholds and ``all``/``any``/``len`` over
      comprehensions), is that a spelling is present in a value traced to the real committed
      source. Each comparison is gated on its OWN operands -- the spelling must be a
      hand-written needle compared against a tainted operand -- so an unrelated tainted
      reference elsewhere in the same ``assert`` cannot license a hand-typed literal comparison
      that never touches it. This is what a reviewer's ``.count('objective="f1"') == 2`` (41,
      44), ``objective == "f1"`` (42), and ``f"min_coverage={MIN_COVERAGE}"`` f-string (46) all
      need, and what the mutation findings in #244 and #276 exist to close: crediting the wrong
      side of a negative claim, and crediting a spelling that merely co-occurs with taint.
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
    frozen_taint = frozenset(tainted)
    nonempty = _asserted_nonempty_names(func)

    for node in _unconditional_asserts(func.body):
        pinned |= _entailed_spellings(node.test, True, frozen_taint, nonempty)

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

    unconditional = _unconditional_asserts(func.body)
    distinguished: set[str] = set()
    for node in unconditional:
        if not (
            isinstance(node.test, ast.Compare)
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
    for node in unconditional:
        if not (
            isinstance(node.test, ast.Compare)
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


# --------------------------------------------------------------------------------------------
# mutation tests for the EFFECTIVE TRUTH SENSE of an objective pin (#276). Each one runs the
# same ``_objective_pin_violations`` CI runs, on a throwaway copy of a published recipe that
# passes today (49, whose only pin is a ``"min_coverage" in source`` assertion), with that
# recipe's pin rewritten into the shape under test. A shape that says the spelling is ABSENT
# must make the check go red; a shape that says it is PRESENT must keep it green; and flipping
# the copy's objective (so the committed call no longer uses the pinned spelling) must turn every
# green shape red again, proving the pin is really tied to the committed call.
# --------------------------------------------------------------------------------------------

_POLARITY_BASE_RECIPE = "49-multi-agent-task-assignment"

_POLARITY_PREAMBLE = """\
import json
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parent.parent
"""

_NOTEBOOK_READ = """\
notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
cell = next(c for c in notebook["cells"] if c.get("id") == "threshold-code")
source = "".join(cell["source"])
cells = ["".join(c["source"]) for c in notebook["cells"]]
"""


def _polarity_violations(
    tmp_path: Path,
    assertions: str,
    *,
    read: str = _NOTEBOOK_READ,
    flip_objective: bool = False,
    decorators: str = "",
    nested: bool = False,
) -> list[str] | None:
    """Copy recipe 49 into ``tmp_path``, replace its ``tests/`` with a single test whose body is
    ``read`` followed by ``assertions`` (optionally decorated, or nested inside a helper function
    pytest would not collect), optionally flip the committed notebook's objective from
    ``min_coverage`` to ``target_accuracy``, and return the check's verdict for the copy."""
    target = tmp_path / _POLARITY_BASE_RECIPE
    shutil.copytree(REPO / "recipes" / _POLARITY_BASE_RECIPE, target)
    for old in (target / "tests").glob("*.py"):
        old.unlink()
    body = textwrap.indent(read + assertions, "    ")
    test_text = f"{decorators}def test_pin():\n{body}"
    if nested:
        test_text = "def _helper():\n" + textwrap.indent(test_text, "    ")
    (target / "tests" / "test_threshold_pin.py").write_text(
        f"{_POLARITY_PREAMBLE}\n\n{test_text}", encoding="utf-8"
    )
    if flip_objective:
        nb_path = target / "notebook.ipynb"
        notebook = json.loads(nb_path.read_text("utf-8"))
        flipped = 0
        for cell in notebook["cells"]:
            if cell.get("id") in ("threshold-code", "sweep-code"):
                text = cell_source(cell)
                swapped = text.replace("min_coverage=", "target_accuracy=")
                assert swapped != text, "mutation did not take -- the replace found nothing"
                cell["source"] = [swapped]
                flipped += 1
        assert flipped == 2
        nb_path.write_text(json.dumps(notebook), encoding="utf-8")
    return _objective_pin_violations(target)


def test_the_unmutated_polarity_baseline_passes_and_a_hand_typed_pin_does_not(tmp_path):
    """The baseline every mutation below departs from: recipe 49's own pin shape passes on the
    copy, and the SAME assertion against a hand-typed duplicate of the source (not a read of the
    committed notebook) does not."""
    assert _polarity_violations(tmp_path / "a", 'assert "min_coverage" in source\n') == []
    typed = "source = 'select_confidence_threshold(min_coverage=0.5)'\nassert \"min_coverage\" in source\n"
    violations = _polarity_violations(tmp_path / "b", typed, read="")
    assert violations and "min_coverage" in violations[0]


# Each spelling says the objective is NOT in the committed source (or says nothing that proves
# it is), so a recipe whose only pin is this shape is unpinned.
_ABSENT_OR_UNPROVEN_SHAPES = {
    # the four spellings #276 names
    "is False": 'assert ("min_coverage" in source) is False\n',
    "count == 0": 'assert source.count("min_coverage") == 0\n',
    "len of filtered comprehension == 0": (
        'assert len([s for s in cells if "min_coverage" in s]) == 0\n'
    ),
    "if-expression with a vacuous branch": (
        'assert ("min_coverage" in source) if len(source) > 0 else True\n'
    ),
    # the same property in other clothes
    "== False": 'assert ("min_coverage" in source) == False  # noqa: E712\n',
    "is not True": 'assert ("min_coverage" in source) is not True\n',
    "not in is True": 'assert ("min_coverage" not in source) is True\n',
    "not in": 'assert "min_coverage" not in source\n',
    "not (x in y)": 'assert not ("min_coverage" in source)\n',
    "count < 1": 'assert source.count("min_coverage") < 1\n',
    "count <= 0": 'assert source.count("min_coverage") <= 0\n',
    "0 == count": 'assert 0 == source.count("min_coverage")\n',
    "not bare count": 'assert not source.count("min_coverage")\n',
    "not (count > 0)": 'assert not (source.count("min_coverage") > 0)\n',
    "len of comprehension is 0": ('assert len([s for s in cells if "min_coverage" in s]) < 1\n'),
    "sum of matches == 0": ('assert sum(1 for s in cells if "min_coverage" in s) == 0\n'),
    "not any": 'assert not any("min_coverage" in s for s in cells)\n',
    "all(not in)": 'assert all("min_coverage" not in s for s in cells)\n',
    "any(not in)": 'assert any("min_coverage" not in s for s in cells)\n',
    "not all(in)": 'assert not all("min_coverage" in s for s in cells)\n',
    "or with a vacuous operand": 'assert ("min_coverage" in source) or len(source) > 0\n',
    "or True": 'assert ("min_coverage" in source) or True\n',
    "chained comparison to zero": 'assert 0 == source.count("min_coverage") == 0\n',
    "count compared with a non-number": ('assert source.count("min_coverage") == len(cells)\n'),
    "all over a possibly-empty iterable (vacuous)": (
        'assert all("min_coverage" in s for s in cells)\n'
    ),
    "assert under pytest.raises (claims absence)": (
        'with pytest.raises(AssertionError):\n    assert "min_coverage" in source\n'
    ),
    "assert under an if": 'if len(source) > 0:\n    assert "min_coverage" in source\n',
    "assert in a loop": 'for s in cells:\n    assert "min_coverage" in s\n',
    # review of the first head: comprehension scoping and vacuous non-emptiness
    "any rebinding the tainted name": (
        'assert any("min_coverage" in source for source in ["min_coverage"])\n'
    ),
    "all rebinding the tainted name": (
        'assert all("min_coverage" in source for source in ["min_coverage"])\n'
    ),
    "any over a display mixing the read with a typed needle": (
        'assert any("min_coverage" in s for s in [source, "min_coverage"])\n'
    ),
    "all over a name emptied after a non-empty assignment": (
        'sources = [source]\nsources = []\nassert all("min_coverage" in s for s in sources)\n'
    ),
    "all over a name emptied in place": (
        'sources = [source]\nsources.clear()\nassert all("min_coverage" in s for s in sources)\n'
    ),
    "all over a name asserted non-empty then rebound": (
        "sources = [source]\nassert sources\nsources = []\n"
        'assert all("min_coverage" in s for s in sources)\n'
    ),
    "all over a generator asserted truthy": (
        'sources = (s for s in cells if "zzz" in s)\nassert sources\n'
        'assert all("min_coverage" in s for s in sources)\n'
    ),
    # an assert that may never run
    "assert after an early return": ('if source:\n    return\nassert "min_coverage" in source\n'),
    "assert after pytest.skip": 'pytest.skip("later")\nassert "min_coverage" in source\n',
    "assert after a conditional skip": (
        'if not source:\n    pytest.skip("later")\nassert "min_coverage" in source\n'
    ),
    "assert after a raise": 'raise RuntimeError("x")\nassert "min_coverage" in source\n',
    "assert in a loop with a continue before it": (
        'for cid in ("threshold-code", "sweep-code"):\n    if cid:\n        continue\n'
        '    assert "min_coverage" in source\n'
    ),
    "assert in a loop with a break": (
        'for cid in ("threshold-code", "sweep-code"):\n    assert "min_coverage" in source\n'
        "    break\n"
    ),
    # the needle is compared against a value that carries a hand-typed copy of it
    "needle smuggled into a default": (
        'kws = {"a": source}\nassert kws.get("objective", "min_coverage") == "min_coverage"\n'
    ),
    "needle smuggled through or": 'assert (source or "min_coverage") == "min_coverage"\n',
    "needle appended to the source": 'assert "min_coverage" in source + " min_coverage"\n',
    "needle substituted into the source": (
        'assert "min_coverage" in source.replace("target_accuracy", "min_coverage")\n'
    ),
    "needle in a display with the source": 'assert "min_coverage" in [source, "min_coverage"]\n',
    "count of the needle in a padded source": (
        'assert (source + "min_coverage").count("min_coverage") >= 1\n'
    ),
    # taint ignoring reassignment
    "source rebound to a typed string": (
        "source = 'select_confidence_threshold(s, min_coverage=0.75)'\n"
        'assert "min_coverage" in source\n'
    ),
}

# Shapes that need the whole test function around them rather than a body: a decorator or a
# nesting that stops pytest from running the asserts.
_NOT_RUN_WRAPPERS = {
    "skip marker": {"decorators": '@pytest.mark.skip(reason="x")\n'},
    "skipif marker": {"decorators": '@pytest.mark.skipif(True, reason="x")\n'},
    "xfail marker": {"decorators": "@pytest.mark.xfail\n"},
    "test nested in a helper (never collected)": {"nested": True},
}

# Each shape says the objective IS in the committed source.
_PRESENT_SHAPES = {
    "in": 'assert "min_coverage" in source\n',
    "is True": 'assert ("min_coverage" in source) is True\n',
    "== True": 'assert ("min_coverage" in source) == True  # noqa: E712\n',
    "not in is False": 'assert ("min_coverage" not in source) is False\n',
    "not (not in)": 'assert not ("min_coverage" not in source)\n',
    "not (in is False)": 'assert not (("min_coverage" in source) is False)\n',
    "count >= 1": 'assert source.count("min_coverage") >= 1\n',
    "count > 0": 'assert source.count("min_coverage") > 0\n',
    "count != 0": 'assert source.count("min_coverage") != 0\n',
    "count == n": 'assert source.count("min_coverage") == 2\n',
    "1 <= count": 'assert 1 <= source.count("min_coverage")\n',
    "0 < count": 'assert 0 < source.count("min_coverage")\n',
    "bare count": 'assert source.count("min_coverage")\n',
    "not (count == 0)": 'assert not (source.count("min_coverage") == 0)\n',
    "count is positive and bounded": 'assert 1 <= source.count("min_coverage") <= 9\n',
    "len of filtered comprehension > 0": (
        'assert len([s for s in cells if "min_coverage" in s]) > 0\n'
    ),
    "sum of matches >= 1": 'assert sum(1 for s in cells if "min_coverage" in s) >= 1\n',
    "if-expression with the pin in both branches": (
        'assert ("min_coverage" in source) if len(source) > 0 else ("min_coverage" in source)\n'
    ),
    "and with an unrelated absence claim": (
        'assert "min_coverage" in source and "target_accuracy" not in source\n'
    ),
    "or with the pin in both operands": (
        'assert "min_coverage" in source or source.count("min_coverage") > 0\n'
    ),
    "bool()": 'assert bool("min_coverage" in source)\n',
    "any over a tainted source": 'assert any("min_coverage" in s for s in cells)\n',
    "not all(not in)": 'assert not all("min_coverage" not in s for s in cells)\n',
    "all over a literal non-empty display": (
        'assert all("min_coverage" in s for s in (source, source))\n'
    ),
    "all over a name asserted non-empty": (
        "sources = [s for s in cells]\nassert len(sources) > 0\n"
        'assert all("min_coverage" in s for s in sources)\n'
    ),
    "not any(not in) over a literal non-empty display": (
        'assert not any("min_coverage" not in s for s in [source, source])\n'
    ),
    "all([...]) of memberships": (
        'assert all(["min_coverage" in source, source.count("min_coverage") > 0])\n'
    ),
    "any([...]) of identical claims": (
        'assert any(["min_coverage" in source, source.count("min_coverage") > 0])\n'
    ),
    "f-string needle": 'assert f"min_coverage={0.75}" in source\n',
    "assert inside a plain open block": 'with open(RECIPE / "notebook.ipynb") as h:\n    assert "min_coverage" in source\n',
    # review of the first head: idioms the first derivation wrongly refused
    "sum of booleans": 'assert sum(("min_coverage" in s) for s in cells) > 0\n',
    "sum of counts": 'assert sum(s.count("min_coverage") for s in cells) >= 1\n',
    "loop over a literal tuple of cell ids": (
        'for cid in ("threshold-code", "sweep-code"):\n'
        '    src = "".join(next(c for c in notebook["cells"] if c.get("id") == cid)["source"])\n'
        '    assert "min_coverage" in src\n'
    ),
    "assert before an early return": (
        'assert "min_coverage" in source\nif not source:\n    return\n'
    ),
    "all over a name asserted non-empty (list)": (
        "sources = [s for s in cells]\nassert sources\n"
        'assert all("min_coverage" in s for s in sources)\n'
    ),
}


@pytest.mark.parametrize("shape", sorted(_ABSENT_OR_UNPROVEN_SHAPES))
def test_a_spelling_asserted_absent_or_unproven_is_not_credited_as_pinned(tmp_path, shape):
    """#276: every shape here says the objective is absent from the committed source (or proves
    nothing about it), so a recipe pinned only that way must FAIL the check. Each is planted in a
    copy of a recipe that passes today. Reverting the polarity derivation (back to crediting any
    comparison whose operands name the spelling) turns every case here green."""
    violations = _polarity_violations(tmp_path, _ABSENT_OR_UNPROVEN_SHAPES[shape])
    assert violations, f"{shape!r}: a spelling that is not asserted present was credited"
    assert "min_coverage" in violations[0]


@pytest.mark.parametrize("shape", sorted(_PRESENT_SHAPES))
def test_a_spelling_asserted_present_is_still_credited_and_tied_to_the_committed_call(
    tmp_path, shape
):
    """The positive half, proved by mutation both ways: the shape passes on the unmodified
    objective, and goes red the moment the committed notebook's objective is flipped to a
    spelling the shape does not mention (so the pin is bound to the committed call, not merely
    accepted). Covers ``all(...)``/``any(...)`` over a tainted source (previously refused because
    taint never reached a comprehension variable)."""
    assertions = _PRESENT_SHAPES[shape]
    assert _polarity_violations(tmp_path / "keep", assertions) == [], (
        f"{shape!r}: a legitimate pin was refused"
    )
    flipped = _polarity_violations(tmp_path / "flip", assertions, flip_objective=True)
    assert flipped and "target_accuracy" in flipped[0], (
        f"{shape!r}: passed although the committed objective no longer matches the pin"
    )


# (read statements, assertion) pairs: a read of the committed notebook spelled without
# ``read_text``. They taint the value they produce, so the pin passes, and flipping the objective
# turns it red. Before #276 each of these produced NO taint and was refused.
_READ_SPELLINGS = {
    "open(...).read()": (
        'source = open(RECIPE / "notebook.ipynb", encoding="utf-8").read()\n',
        'assert "min_coverage" in source\n',
    ),
    "read_bytes()": (
        'raw = (RECIPE / "notebook.ipynb").read_bytes()\n',
        'assert b"min_coverage" in raw\n',
    ),
    "with open() as f: f.read()": (
        'with open(RECIPE / "notebook.ipynb", encoding="utf-8") as handle:\n'
        "    source = handle.read()\n",
        'assert "min_coverage" in source\n',
    ),
    "json.load(open())": (
        'notebook = json.load(open(RECIPE / "notebook.ipynb", encoding="utf-8"))\n'
        'source = "".join(c["source"][0] for c in notebook["cells"] if c.get("id") == "threshold-code")\n',
        'assert "min_coverage" in source\n',
    ),
    "read_text() (unchanged)": (
        'source = (RECIPE / "notebook.ipynb").read_text("utf-8")\n',
        'assert "min_coverage" in source\n',
    ),
    "Path.open().read()": (
        'source = (RECIPE / "notebook.ipynb").open(encoding="utf-8").read()\n',
        'assert "min_coverage" in source\n',
    ),
}


@pytest.mark.parametrize("spelling", sorted(_READ_SPELLINGS))
def test_a_read_of_the_committed_notebook_taints_whatever_call_performs_it(tmp_path, spelling):
    read, assertion = _READ_SPELLINGS[spelling]
    assert _polarity_violations(tmp_path / "keep", assertion, read=read) == [], (
        f"{spelling}: a real read of the committed notebook did not taint its result"
    )
    flipped = _polarity_violations(tmp_path / "flip", assertion, read=read, flip_objective=True)
    assert flipped and "target_accuracy" in flipped[0], (
        f"{spelling}: the pin was not tied to the committed call"
    )


def test_a_read_of_something_else_does_not_taint(tmp_path):
    """The converse of the read-spelling widening: mentioning the committed file's name is not a
    read of it, and reading some OTHER file is not a read of the committed artefact."""
    mentions = 'source = str(RECIPE / "notebook.ipynb")\n'
    elsewhere = 'source = open(RECIPE / "README.md", encoding="utf-8").read()\n'
    for index, read in enumerate((mentions, elsewhere)):
        violations = _polarity_violations(
            tmp_path / str(index), 'assert "min_coverage" in source\n', read=read
        )
        assert violations, (
            f"credited a pin against a value that is not the committed source: {read}"
        )


@pytest.mark.parametrize("wrapper", sorted(_NOT_RUN_WRAPPERS))
def test_asserts_of_a_test_pytest_does_not_run_are_not_credited(tmp_path, wrapper):
    """A pin in a test that is marked skip/skipif/xfail, or defined inside another function (so
    never collected), is not a pin: the same assertion that passes in a normal test is refused."""
    assertion = 'assert "min_coverage" in source\n'
    assert _polarity_violations(tmp_path / "plain", assertion) == []
    violations = _polarity_violations(tmp_path / "wrapped", assertion, **_NOT_RUN_WRAPPERS[wrapper])
    assert violations, f"{wrapper}: credited an assert that does not run"


def test_a_read_of_a_scratch_copy_or_a_longer_file_name_does_not_taint(tmp_path):
    """``open(tmp_path / "notebook.ipynb").read()`` reads a copy the test made, and
    ``expected_helpers.py`` is not ``helpers.py``: neither is the committed artefact."""
    assertion = 'assert "min_coverage" in source\n'
    reads = {
        "tmp_path copy": 'source = open(tmp_path / "notebook.ipynb", encoding="utf-8").read()\n',
        "tmp_path copy via a local": (
            'copy = tmp_path / "sub"\n'
            'source = (copy / "notebook.ipynb").read_text(encoding="utf-8")\n'
        ),
        "longer file name": 'source = open(RECIPE / "expected_helpers.py").read()\n',
    }
    for label, read in reads.items():
        violations = _polarity_violations(tmp_path / label.replace(" ", "_"), assertion, read=read)
        assert violations, f"{label}: credited a read that is not the committed artefact"


def test_the_effective_truth_sense_unit_cases():
    """Direct unit cases for ``_entailed_spellings``, the derivation the mutation tests above
    exercise end to end: each is (expression, truth the assert needs, spellings it entails)."""
    cases = [
        ('"x" in source', True, {"x"}),
        ('"x" in source', False, set()),
        ('"x" not in source', True, set()),
        ('"x" not in source', False, {"x"}),
        ('("x" in source) is False', True, set()),
        ('("x" in source) is False', False, {"x"}),
        ('not (("x" in source) is False)', True, {"x"}),
        ('source.count("x") == 0', True, set()),
        ('source.count("x") == 0', False, {"x"}),
        ('source.count("x") >= 1', True, {"x"}),
        ('source.count("x") >= 1', False, set()),
        ('"x" in source and "y" in source', True, {"x", "y"}),
        ('"x" in source and "y" in source', False, set()),
        ('"x" in source or "y" in source', True, set()),
        ('"x" in source or "x" in source', True, {"x"}),
        ('"x" not in source or "y" not in source', False, {"x", "y"}),
        ('("x" in source) if flag else True', True, set()),
        ('("x" in source) if flag else ("x" in source)', True, {"x"}),
        ('"x" in "hand typed"', True, set()),
        ('"x" in other', True, set()),
    ]
    for source_text, truth, expected in cases:
        expr = ast.parse(source_text, mode="eval").body
        got = _entailed_spellings(expr, truth, frozenset({"source"}), frozenset())
        assert got == expected, f"{source_text!r} (needs {truth}): {got} != {expected}"


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
    violations = _objective_pin_violations(recipe_dir(recipe))
    if violations is None:
        pytest.skip(
            f"{recipe['slug']}: no select_confidence_threshold/select_threshold call in the "
            "committed notebook or helpers.py"
        )
    assert not violations, f"{recipe['slug']}: " + "; ".join(violations)


def _objective_pin_violations(recipe_dir_: Path) -> list[str] | None:
    """The whole ``threshold_objective_pin`` verdict for one recipe directory: ``None`` when it
    makes no threshold-selection call (the check does not apply), else the list of violations
    (empty means the recipe passes). Factored out of the parametrised test so the mutation tests
    below can run the SAME code path CI runs on a throwaway copy of a recipe."""
    obligations = _threshold_pin_obligations(recipe_dir_)
    if not obligations:
        return None
    pinned = _pinned_objective_spellings(recipe_dir_)
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
                "bare `assert name` or any other truthiness check is not credited. Only asserts "
                "that always run count: top-level statements of a collected test function (not "
                "skipped/xfail-marked, not nested in another function), those inside "
                "`with open(...)`, and those in a `for` over a non-empty literal tuple/list "
                "with no break/continue/return -- and only up to the first return/raise/"
                "pytest.skip. An assert under `if`, `try`, any other loop or context manager "
                "(e.g. pytest.raises) is not credited, and the assertion must CLAIM the "
                "spelling is present (not absent) in a value read from the committed file "
                "itself (not a tmp_path copy), by name, so `is False`, `.count(...) == 0` and "
                "a hand-typed copy of the needle in the compared value do not count"
            )
    return violations


# --------------------------------------------------------------------------------------------
# check: every Noul proposition a recipe's own code builds has a gold-true and gold-false row
# in every scored split (#283)
# --------------------------------------------------------------------------------------------


def _noul_propositions(recipe_dir_: Path) -> dict[str, list[str]]:
    """Every ``Noul`` proposition this route can reach in the recipe's own code, as ``{name: [the
    function(s) that produced it]}``. Not "every proposition the recipe builds": a builder that
    requires an argument is never called (recipe 39's ``build_stage2_questions(which)`` is the
    known case -- see the module docstring). Discovery calls every function ``helpers.py`` defines (not
    one it merely imports) that can be called with no arguments, and keeps the ``Noul``-valued
    entries of any dict it returns. The name is the dict key the recipe's own code assigns --
    the same key ``labels.jsonl`` must carry that proposition's gold value under -- never a
    spelling this check searches for or guesses.

    Calling an arbitrary zero-argument function is safe here only because it was MEASURED to be
    on today's published set, not because any contract says so (CONTRIBUTING.md makes no such
    promise): 51 function calls across 49 published recipes plus the template opened no file,
    wrote no output and raised nothing; the calls took about 0.015s, the whole sweep including
    ``load_helpers`` for all 50 modules about 0.2s. They are not all question
    builders: 36's ``enumerate_game_space`` (a brute-force search over card permutations, the
    one call that does real work -- 13ms at today's ``N_CARDS``, but its cost is bounded by
    nothing this check controls), 43's private ``_new_budget`` and ``worst_case_step_bound``,
    44's ``approve_all_outcome``/``reject_all_outcome``/``always_review_outcome``, 48's
    ``always_consistent_baseline``, and 40's ``build_department_question``/
    ``build_flat_question`` (two builders returning a bare ``Choice``, not a dict) are all
    called, and a function that does not return a ``{name: Noul(...)}`` mapping simply
    contributes nothing. A function that requires an argument is not called. A function that
    raises is skipped, not a failure of this check -- which makes a raising builder
    indistinguishable from a recipe that genuinely builds fewer than two propositions, the same
    root cause as the argument-taking case."""
    helpers = load_helpers(recipe_dir_, reload=True)
    props: dict[str, list[str]] = {}
    for name, obj in vars(helpers).items():
        if not inspect.isfunction(obj) or obj.__module__ != helpers.__name__:
            continue  # imported into helpers.py, not defined there
        try:
            sig = inspect.signature(obj)
        except (TypeError, ValueError):
            continue
        if any(
            param.default is inspect.Parameter.empty
            and param.kind
            in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
            for param in sig.parameters.values()
        ):
            continue  # needs an argument this check does not have -- not a question builder
        try:
            result = obj()
        except Exception:
            continue
        if not isinstance(result, dict):
            continue
        for key, value in result.items():
            if isinstance(value, Noul):
                props.setdefault(key, []).append(name)
    return props


def _noul_gold_value(label: object, prop: str) -> tuple[bool, bool | None]:
    """``(found, value)`` for proposition ``prop``'s gold value under one ``labels.jsonl`` row's
    ``label``. Handles every shape the published multi-proposition ``Noul`` recipes actually
    use: a flat ``{prop: bool, ...}`` mapping (26, 41, 42, 44, 48); one level of nesting,
    ``{"features": {prop: bool, ...}, ...}`` (35); and set-valued gold, a list naming the
    propositions that are true, where membership stands for the value and an absent name is a
    recorded ``False`` (06, 37). Finding none of these shapes reports ``found=False`` rather
    than guessing; such a row contributes nothing to either truth value, which is exactly what
    this check is required to notice (a proposition it cannot read gold for is not evidence that
    a gold-true or gold-false row exists)."""
    if isinstance(label, dict):
        if prop in label:
            return True, bool(label[prop])
        for value in label.values():
            if isinstance(value, dict) and prop in value:
                return True, bool(value[prop])
        return False, None
    if isinstance(label, list):
        return True, prop in label
    return False, None


def _noul_gold_gaps(recipe_dir_: Path) -> tuple[dict[str, list[str]], list[str]]:
    """``(propositions, gaps)`` for one recipe. ``gaps`` names every ``split/proposition`` pair
    among ``jev_cookbook.fixtures.REQUIRED_SPLITS`` (``validation``, ``test`` -- the module's
    own rule that ``demo`` is never scored, not a spelling repeated here) for which
    ``labels.jsonl`` carries no gold-true row, no gold-false row, or neither. Returns
    ``(propositions, [])`` immediately, with no fixture read at all, when fewer than two
    propositions are reached: #283 is about the multi-proposition battery, and a single
    proposition's gold is often recorded with no proposition key for ``_noul_gold_value`` to
    read (see the module docstring)."""
    props = _noul_propositions(recipe_dir_)
    if len(props) < 2:
        return props, []
    inputs = jc_fixtures.load_inputs(recipe_dir_)
    labels = jc_fixtures.load_labels(recipe_dir_)
    split_of = {example.id: example.split for example in inputs}
    seen: dict[tuple[str, str], set[bool]] = {}
    for example_id, label in labels.items():
        split = split_of.get(example_id)
        if split not in jc_fixtures.REQUIRED_SPLITS:
            continue
        for prop in props:
            found, value = _noul_gold_value(label, prop)
            if found:
                seen.setdefault((split, prop), set()).add(value)
    gaps = []
    for split in jc_fixtures.REQUIRED_SPLITS:
        for prop in props:
            values = seen.get((split, prop), set())
            missing = [v for v in (True, False) if v not in values]
            if missing:
                missing_words = "/".join("true" if m else "false" for m in missing)
                gaps.append(
                    f"{split}/{prop}: no gold-{missing_words} row (saw only {sorted(values)})"
                )
    return props, gaps


@pytest.mark.parametrize("recipe", guarded_with_template("noul_proposition_gold_coverage")())
def test_every_noul_proposition_has_gold_true_and_false_in_each_scored_split(recipe):
    """#283: recipe 48's review measured, on its merged fixtures, that ``breaks_reference`` had
    zero gold positives in validation -- no row where its tag could change a composed outcome,
    no row from which ``select_threshold`` could choose that proposition's threshold, so the
    recipe's own declared "the F1 sweep is degenerate" limitation was a symptom of the fixture
    gap rather than an independent fact about the task. #283's issue is silent on this: an issue
    that names propositions but not the combinations and polarities their gold must cover left
    it to chance, and it reached a builder only through an orchestration brief rather than
    through the issue itself. This check makes the mechanical half of that requirement --
    "every proposition gets a gold-true and a gold-false row in every scored split" -- a CI
    property instead of a brief.

    A recipe in which fewer than two ``Noul`` propositions are reached is skipped (not passed):
    either it builds fewer than two, so the battery property #283 is about does not reach it, or
    it builds them where zero-argument discovery cannot call (recipe 39), and this check does
    not substitute for whatever the recipe's own evidence requires. See ``_noul_propositions`` for how
    propositions are discovered (by calling the recipe's own code, never by name) and
    ``_noul_gold_value`` for the gold-reading shapes this recognises."""
    props, gaps = _noul_gold_gaps(recipe_dir(recipe))
    if len(props) < 2:
        pytest.skip(
            f"{recipe['slug']}: no two Noul propositions reachable by zero-argument discovery "
            f"(found {sorted(props)}); a recipe whose question builder requires an argument "
            "is not reached, and a builder that raises is not told apart from one that is absent"
        )
    assert not gaps, f"{recipe['slug']}: " + "; ".join(gaps)
