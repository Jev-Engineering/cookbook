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
import re
import shutil
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


# --------------------------------------------------------------------------------------------
# check: the notebook actually executes its simulated side effect (#212)
# --------------------------------------------------------------------------------------------
#
# Check id ``simulated_side_effect_invoked``. The gap it closes: a recipe's helper can be
# well tested while the committed notebook no longer calls it (delete the ``submit_reviews``
# call from recipe 24's ``eval-test`` cell, re-execute, commit: every other check stays green,
# on a notebook whose prose claims a queue its output no longer shows).
#
# Identification rule (written down, because the issue asks for it): the guard parses the
# notebook's code cells with ``ast`` and walks only code that can execute -- it does not see
# comments or strings, skips the body of a function nobody calls, a lambda, an ``if False:`` /
# ``while False:`` branch, a loop over an empty literal, and statements after a top-level
# ``raise``. In that live code it counts CALL SITES (distinct source positions, not runtime
# calls) of three kinds, each under a stable key:
#
# * ``helpers.<fn>``: a call to a function of the recipe's ``helpers.py`` that is a side-effect
#   function -- one whose body, directly or through other ``helpers.py`` functions, calls a
#   mutating method (``submit``, ``resolve``, ``record``, ``put``, ``delete``, ``rollback``,
#   ``run``, ``step``) or one of the shared ``jev_cookbook.simulation`` fill helpers.
# * ``<Sink>.<method>``: a mutating method called on a name the notebook bound to a
#   ``jev_cookbook.simulation`` sink (``ReviewQueue.submit``, ``ActionLog.record``,
#   ``Store.put``, ...), the inline form.
# * ``fill_review_queue`` / ``record_actions`` / ``route_outcomes`` called directly.
#
# A function the notebook defines itself counts for what its body calls, but only if live code
# calls it. SIDE_EFFECT_INVENTORY below then states, per published recipe, either the minimum
# number of sites it must keep under each key, or that it has no simulated side effect (with the
# reason). The count is a floor: deleting any one of two calls fails. A recipe the inventory
# does not list yet (a recipe added after this check) is held to the general rule instead: if it
# imports or builds a sink, or its ``helpers.py`` defines a side-effect function, the notebook
# must execute at least one site, and every sink it builds must be mutated or handed to a
# side-effect function. Anything the analysis cannot read (a code cell that does not parse) fails
# rather than being skipped. Known limits: a site reached only through an attribute chain
# (``self.queue.submit``) or a function stored in a container is not seen, and a condition the
# analysis cannot evaluate statically is assumed to be taken.

SIDE_EFFECT_SINKS = {
    "ReviewQueue": frozenset({"submit", "resolve"}),
    "ActionLog": frozenset({"record"}),
    "Store": frozenset({"put", "delete", "rollback"}),
    "Transactor": frozenset({"run"}),
}
SIDE_EFFECT_FILL_HELPERS = frozenset({"fill_review_queue", "record_actions", "route_outcomes"})
HELPER_MUTATING_METHODS = frozenset(
    {"submit", "resolve", "record", "put", "delete", "rollback", "run", "step"}
)
SIMULATION_MODULE = "jev_cookbook.simulation"


def _simulation_imports(tree: ast.AST) -> tuple[dict[str, str], set[str]]:
    """``({local name: jev_cookbook.simulation name}, {local names of the module itself})``."""
    names: dict[str, str] = {}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == SIMULATION_MODULE:
            for alias in node.names:
                names[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module == "jev_cookbook":
            for alias in node.names:
                if alias.name == "simulation":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == SIMULATION_MODULE:
                    modules.add(alias.asname or SIMULATION_MODULE)
    return names, modules


def _simulation_symbol(func: ast.expr, names: dict[str, str], modules: set[str]) -> str | None:
    """The ``jev_cookbook.simulation`` name ``func`` refers to, or ``None``."""
    if isinstance(func, ast.Name):
        return names.get(func.id)
    if isinstance(func, ast.Attribute):
        owner = ast.unparse(func.value)
        if owner in modules or owner == SIMULATION_MODULE:
            return func.attr
    return None


def _constant_truth(test: ast.expr) -> bool | None:
    """``True``/``False`` for a test that is a literal constant (or ``not`` of one), else None."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _constant_truth(test.operand)
        return None if inner is None else not inner
    return None


def _is_empty_literal(node: ast.expr) -> bool:
    return (isinstance(node, ast.List | ast.Tuple | ast.Set) and not node.elts) or (
        isinstance(node, ast.Dict) and not node.keys
    )


def _expression_nodes(node: ast.AST):
    """Every node under ``node`` that can run, in source order, not entering a lambda."""
    yield node
    if isinstance(node, ast.Lambda):
        return
    for child in ast.iter_child_nodes(node):
        yield from _expression_nodes(child)


_TRY_STATEMENTS = (ast.Try, getattr(ast, "TryStar", ast.Try))  # TryStar only exists on 3.11+


def _live_nodes(stmts: list[ast.stmt]):
    """Statements and expression nodes of ``stmts`` that can execute, in source order.

    A ``def`` or ``class`` is yielded as itself and not entered (its body is live only if the
    function is called, which the caller decides). Branches are chosen only for literal
    constant conditions; anything else is assumed possible.
    """
    for stmt in stmts:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield stmt
            continue
        if isinstance(stmt, ast.If):
            yield stmt
            yield from _expression_nodes(stmt.test)
            truth = _constant_truth(stmt.test)
            if truth is not False:
                yield from _live_nodes(stmt.body)
            if truth is not True:
                yield from _live_nodes(stmt.orelse)
        elif isinstance(stmt, ast.While):
            yield stmt
            yield from _expression_nodes(stmt.test)
            if _constant_truth(stmt.test) is not False:
                yield from _live_nodes(stmt.body)
            yield from _live_nodes(stmt.orelse)
        elif isinstance(stmt, ast.For | ast.AsyncFor):
            yield stmt
            yield from _expression_nodes(stmt.iter)
            if not _is_empty_literal(stmt.iter):
                yield from _live_nodes(stmt.body)
            yield from _live_nodes(stmt.orelse)
        elif isinstance(stmt, ast.Match):
            yield stmt
            yield from _expression_nodes(stmt.subject)
            for case in stmt.cases:
                if case.guard is not None:
                    yield from _expression_nodes(case.guard)
                yield from _live_nodes(case.body)
        elif isinstance(stmt, _TRY_STATEMENTS):
            yield stmt
            for block in (stmt.body, *(h.body for h in stmt.handlers), stmt.orelse, stmt.finalbody):
                yield from _live_nodes(block)
        elif isinstance(stmt, ast.With | ast.AsyncWith):
            yield stmt
            for item in stmt.items:
                yield from _expression_nodes(item.context_expr)
            yield from _live_nodes(stmt.body)
        else:
            yield stmt
            for child in ast.iter_child_nodes(stmt):
                yield from _expression_nodes(child)
        if isinstance(stmt, ast.Raise | ast.Return | ast.Break | ast.Continue):
            return


def _helpers_side_effect_functions(helpers_path: Path) -> set[str] | None:
    """Names of the module-level ``helpers.py`` functions that perform a simulated side effect,
    or ``None`` if the file does not parse. A function is one when its body calls a mutating
    method or a shared fill helper, or calls another such function of the same module."""
    if not helpers_path.is_file():
        return set()
    try:
        tree = ast.parse(helpers_path.read_text("utf-8"))
    except SyntaxError:
        return None
    names, modules = _simulation_imports(tree)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    direct: set[str] = set()
    calls: dict[str, set[str]] = {}
    for name, node in functions.items():
        calls[name] = set()
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            if isinstance(func, ast.Attribute) and func.attr in HELPER_MUTATING_METHODS:
                direct.add(name)
            elif _simulation_symbol(func, names, modules) in SIDE_EFFECT_FILL_HELPERS:
                direct.add(name)
            elif isinstance(func, ast.Name) and func.id in functions:
                calls[name].add(func.id)
    effects = set(direct)
    changed = True
    while changed:
        changed = False
        for name, callees in calls.items():
            if name not in effects and callees & effects:
                effects.add(name)
                changed = True
    return effects


class SideEffectReport:
    """What the notebook's live code does with the simulated side effects of its recipe."""

    def __init__(self) -> None:
        self.sites: dict[str, set[tuple[int, int, int]]] = {}
        self.sink_vars: dict[str, str] = {}  # notebook name -> sink class it was built as
        self.touched_vars: set[str] = set()
        self.effect_functions: set[str] = set()  # helpers.py side-effect functions
        self.problems: list[str] = []  # things the analysis could not read

    def counts(self) -> dict[str, int]:
        return {key: len(places) for key, places in sorted(self.sites.items())}

    def untouched_sink_vars(self) -> list[str]:
        return sorted(v for v in self.sink_vars if v not in self.touched_vars)

    def uncalled_effect_functions(self) -> list[str]:
        called = {k.split(".", 1)[1] for k in self.sites if k.startswith("helpers.")}
        return sorted(self.effect_functions - called)


def _bind_sink_variables(node: ast.AST, report: SideEffectReport, resolve) -> None:
    """Record ``name = ReviewQueue()`` style bindings, including tuple unpacking."""
    if isinstance(node, ast.Assign):
        pairs = []
        for target in node.targets:
            if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                pairs.extend(zip(target.elts, node.value.elts, strict=False))
            else:
                pairs.append((target, node.value))
        for target, value in pairs:
            if isinstance(target, ast.Name) and isinstance(value, ast.Call):
                symbol = resolve(value.func)
                if symbol in SIDE_EFFECT_SINKS:
                    report.sink_vars[target.id] = symbol


def side_effect_report(recipe_dir_: Path) -> SideEffectReport:
    """Analyse ``recipe_dir_``'s committed notebook as described in the section header."""
    report = SideEffectReport()
    effects = _helpers_side_effect_functions(recipe_dir_ / "helpers.py")
    if effects is None:
        report.problems.append("helpers.py does not parse as plain Python")
        effects = set()
    report.effect_functions = set(effects)
    blocks: list[tuple[int, ast.Module]] = []
    for index, cell in enumerate(notebook_cells(recipe_dir_)):
        if cell.get("cell_type") != "code":
            continue
        try:
            blocks.append((index, ast.parse(cell_source(cell))))
        except SyntaxError:
            report.problems.append(
                f"notebook cell {index} does not parse as plain Python (an IPython magic?), "
                "so its side effects cannot be checked"
            )
    names: dict[str, str] = {}
    modules: set[str] = set()
    helper_names = {"helpers"}
    for _, tree in blocks:
        n, m = _simulation_imports(tree)
        names.update(n)
        modules |= m
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and _call_func_name(node.value) == "load_helpers"
            ):
                helper_names |= {t.id for t in node.targets if isinstance(t, ast.Name)}

    def resolve(func: ast.expr) -> str | None:
        return _simulation_symbol(func, names, modules)

    defs: dict[str, ast.FunctionDef] = {}
    entered: set[str] = set()
    current_cell = [0]

    def site(key: str, call: ast.Call) -> None:
        place = (current_cell[0], call.lineno, call.col_offset)
        report.sites.setdefault(key, set()).add(place)

    def touch_arguments(call: ast.Call) -> None:
        for arg in [*call.args, *(k.value for k in call.keywords)]:
            if isinstance(arg, ast.Name) and arg.id in report.sink_vars:
                report.touched_vars.add(arg.id)

    def run(stmts: list[ast.stmt]) -> None:
        for node in _live_nodes(stmts):
            if isinstance(node, ast.FunctionDef):
                defs[node.name] = node
            elif isinstance(node, ast.Assign):
                _bind_sink_variables(node, report, resolve)
            elif isinstance(node, ast.Call):
                handle(node)

    def handle(call: ast.Call) -> None:
        func = call.func
        symbol = resolve(func)
        if symbol in SIDE_EFFECT_FILL_HELPERS:
            site(symbol, call)
            touch_arguments(call)
        elif isinstance(func, ast.Name) and func.id in defs and func.id not in entered:
            entered.add(func.id)
            run(defs[func.id].body)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            owner = func.value.id
            if owner in helper_names and func.attr in effects:
                site(f"helpers.{func.attr}", call)
                touch_arguments(call)
            elif (
                owner in report.sink_vars
                and func.attr in SIDE_EFFECT_SINKS[report.sink_vars[owner]]
            ):
                site(f"{report.sink_vars[owner]}.{func.attr}", call)
                report.touched_vars.add(owner)

    for index, tree in blocks:
        current_cell[0] = index
        run(tree.body)
    return report


# Per published recipe: the minimum live call sites the notebook must keep under each key (see the
# section header), or a sentence saying why the recipe has no simulated side effect. Built from
# the audit in the pull request that added this check; a recipe not listed here is held to the
# general rule in ``test_the_notebook_executes_its_simulated_side_effect``.
_NO_SINKS = (
    "returns typed outcomes only: the notebook builds no ReviewQueue, ActionLog, Store or "
    "Transactor and helpers.py calls no mutating method"
)
SIDE_EFFECT_INVENTORY: dict[str, dict[str, int] | str] = {
    "01-sentiment-classification": _NO_SINKS,
    "02-refund-intent-detection": {"ReviewQueue.submit": 2},
    "03-response-clarity-scoring": _NO_SINKS,
    "04-support-ticket-routing": (
        "route_ticket returns a Routing value; its 'simulated queue' is a field of that value, "
        "not a ReviewQueue or ActionLog, and nothing is written anywhere"
    ),
    "05-document-classification": _NO_SINKS,
    "06-multiple-topic-labels": {"ReviewQueue.submit": 1},
    "07-word-sense-selection": _NO_SINKS,
    "08-faq-selection": _NO_SINKS,
    "09-file-organization": (
        "prints a proposed folder plan; nothing moves, and no ReviewQueue, ActionLog or Store is "
        "built"
    ),
    "10-answer-relevance-check": {"ReviewQueue.submit": 3},
    "11-clarification-selection": (
        "select_followup returns the question to ask as a value; no ReviewQueue, ActionLog or "
        "Store is built"
    ),
    "12-thesaurus-word-selection": _NO_SINKS,
    "13-candidate-rewrite-selection": _NO_SINKS,
    "14-source-span-selection": _NO_SINKS,
    "15-sensitive-text-triage": {"ReviewQueue.submit": 1},
    "16-discord-moderation-triage": {"ActionLog.record": 1, "ReviewQueue.submit": 1},
    "17-passage-reranking": _NO_SINKS,
    "18-duplicate-incident-matching": {"helpers.record_resolution": 1},
    "19-ci-failure-classification": {"helpers.classify": 3},
    "20-claim-support-classification": _NO_SINKS,
    "21-quiz-answer-adjudication": {"ReviewQueue.submit": 2},
    "22-cmdb-asset-matching": {"helpers.record_resolution": 1},
    "23-pairwise-answer-evaluation": (
        "the preference is a returned value and the notebook says it has no side effect; no "
        "ReviewQueue, ActionLog or Store is built"
    ),
    "24-incident-priority-composition": {"helpers.submit_reviews": 2},
    "25-change-evidence-review": {"ReviewQueue.submit": 1},
    "26-prompt-injection-screening": {"ReviewQueue.submit": 1},
    "27-function-selection": {"helpers.resolve": 2},
    "28-skill-selection": _NO_SINKS,
    "29-tool-outcome-verification": {"helpers.classify": 2},
    "30-citation-verification": {"helpers.classify": 2},
    "31-patch-risk-triage": {"ReviewQueue.submit": 1},
    "32-regression-test-selection": _NO_SINKS,
    "33-schema-field-mapping": {"helpers.submit_reviews": 2},
    "34-evidence-relationship-labels": {"helpers.submit_reviews": 2},
    "35-semantic-feature-extraction": _NO_SINKS,
    "36-card-game-action-selection": {"helpers.play_game": 1},
    "37-research-domain-tagging": {"ReviewQueue.submit": 1},
    "38-abstention-and-review-queues": {"ActionLog.record": 1, "ReviewQueue.submit": 1},
    "39-document-extraction-cascade": _NO_SINKS,
    "40-hierarchical-classification": {"ActionLog.record": 1, "ReviewQueue.submit": 1},
    "41-approval-scope-review": {"ReviewQueue.submit": 1},
    "42-outbound-disclosure-screening": {"ActionLog.record": 1, "ReviewQueue.submit": 1},
    "43-failure-recovery-selection": {"helpers.enforce_recovery": 3, "helpers.run_episode": 3},
    "44-plan-constraint-assessment": {"ReviewQueue.submit": 1},
    "45-memory-reconciliation": {
        "Store.put": 3,
        "helpers.rebuild_store_from_writes": 1,
        "helpers.reconcile": 3,
    },
    "46-semantic-context-paging": {"helpers.rebuild_store": 2, "helpers.run_session": 1},
    "47-evidence-conflict-diagnosis": _NO_SINKS,
    "48-document-revision-consistency": {
        "Store.put": 1,
        "Store.rollback": 1,
        "helpers.decide": 3,
    },
    "49-multi-agent-task-assignment": {"helpers.assign": 6},
    "50-model-comparison-and-calibration": _NO_SINKS,
}


def _side_effect_violations(slug: str, recipe_dir_: Path) -> list[str] | None:
    """Reasons ``recipe_dir_``'s notebook fails the check, or ``None`` when the recipe is not in
    the inventory and nothing applies to it."""
    report = side_effect_report(recipe_dir_)
    violations = list(report.problems)
    counts = report.counts()
    expected = SIDE_EFFECT_INVENTORY.get(slug)
    if isinstance(expected, str):
        if counts or report.sink_vars:
            violations.append(
                f"the inventory says this recipe has no simulated side effect ({expected}) but "
                f"its notebook builds {sorted(set(report.sink_vars.values()))} and executes "
                f"{sorted(counts)}"
            )
        if report.effect_functions:
            violations.append(
                "the inventory says this recipe has no simulated side effect but helpers.py "
                f"defines {sorted(report.effect_functions)}"
            )
        return violations
    if expected is not None:
        for key, minimum in expected.items():
            found = counts.get(key, 0)
            if found < minimum:
                violations.append(
                    f"the notebook executes {key} at {found} call site(s), the inventory "
                    f"requires at least {minimum}"
                )
    elif counts == {} and not report.sink_vars and not report.effect_functions:
        return violations or None
    elif not counts:
        violations.append(
            "the recipe has a simulated side effect "
            f"({sorted(set(report.sink_vars.values())) or sorted(report.effect_functions)}) "
            "that its notebook never executes"
        )
    untouched = report.untouched_sink_vars()
    if untouched:
        violations.append(
            f"the notebook builds {untouched} but never calls a mutating method on it or "
            "passes it to a side-effect function"
        )
    return violations


@pytest.mark.parametrize("recipe", guarded("simulated_side_effect_invoked")())
def test_the_notebook_executes_its_simulated_side_effect(recipe):
    """#212: nothing else verifies that a recipe's notebook actually INVOKES the simulated side
    effect its prose and its helper tests describe. A helper can be thoroughly tested while the
    committed notebook stops calling it, and a notebook re-executed after that edit is fresh and
    faithfully wrong, so the notebook-freshness job, the helper's tests and every other check
    here stay green. The rule, the inventory and the known limits are in the section header
    above; ``SIDE_EFFECT_INVENTORY`` states for every published recipe either the call sites it
    must keep or that it has no simulated side effect, and a recipe it does not list is held to
    the general rule. A code cell the analysis cannot parse fails rather than being skipped."""
    violations = _side_effect_violations(recipe["slug"], recipe_dir(recipe))
    if violations is None:
        pytest.skip(
            f"{recipe['slug']}: not in SIDE_EFFECT_INVENTORY and no simulated side effect "
            "detected; add it to the inventory with the reason it has none"
        )
    assert not violations, f"{recipe['slug']}: " + "; ".join(violations)


def side_effect_inventory_gaps() -> list[str]:
    """Published recipes with no ``SIDE_EFFECT_INVENTORY`` entry yet. Deliberately not a test: a
    recipe pull request may not edit ``tests/``, so a new recipe cannot add its own entry, and
    failing it for that would block every recipe. Such a recipe is held to the general rule (see
    the section header) and the parametrised test says so when it skips; a foundation pull request
    adds the entries at close-out. List them with ``python -c`` or from a debugger."""
    return sorted({r["slug"] for r in PUBLISHED} - SIDE_EFFECT_INVENTORY.keys())


def test_the_side_effect_inventory_names_only_published_recipes_with_well_formed_entries():
    stale = sorted(SIDE_EFFECT_INVENTORY.keys() - {r["slug"] for r in PUBLISHED})
    assert not stale, f"SIDE_EFFECT_INVENTORY names recipes that are not published: {stale}"
    for slug, entry in SIDE_EFFECT_INVENTORY.items():
        if isinstance(entry, str):
            assert entry.strip(), f"{slug}: a no-side-effect entry must say why"
        else:
            assert entry and all(
                isinstance(k, str) and type(n) is int and n >= 1 for k, n in entry.items()
            ), f"{slug}: expected {{key: minimum call sites >= 1}}, got {entry!r}"


# The guard is proved by mutation: each case below takes a real published recipe, edits ONLY its
# committed notebook source, and requires the guard to report it. M15 is the originally reported
# case (recipe 24, delete the ``eval-test`` cell's ``submit_reviews`` call); the others show the
# guard is not satisfied by a mention in a comment, a string, a function nobody calls, a lambda,
# or an ``if False:`` branch.

RECIPE_24 = "24-incident-priority-composition"
RECIPE_24_TEST_CALL = "helpers.submit_reviews(queue, test_examples, test_decisions, test_results)"


def _mutated_recipe(tmp_path: Path, slug: str, edit) -> Path:
    """A copy of the published recipe ``slug`` whose notebook code cells went through
    ``edit(source) -> source``. Only the notebook is touched."""
    target = tmp_path / slug
    shutil.copytree(RECIPES_DIR / slug, target, ignore=shutil.ignore_patterns("__pycache__"))
    path = target / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            cell["source"] = edit(cell_source(cell)).splitlines(keepends=True)
    path.write_text(json.dumps(notebook), "utf-8")
    return target


def _replace_line(old: str, make):
    """An ``edit`` replacing the line that contains ``old`` with ``make(line)``; it must hit once."""
    hits = []

    def edit(source: str) -> str:
        lines = source.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if old in line:
                hits.append(line)
                lines[i] = make(line)
        return "".join(lines)

    edit.hits = hits
    return edit


def test_the_unmutated_recipe_24_passes_the_guard(tmp_path):
    assert _side_effect_violations(RECIPE_24, RECIPES_DIR / RECIPE_24) == []
    copy = _mutated_recipe(tmp_path, RECIPE_24, lambda source: source)
    assert _side_effect_violations(RECIPE_24, copy) == []


def test_m15_deleting_the_test_split_submit_reviews_call_is_caught(tmp_path):
    edit = _replace_line(RECIPE_24_TEST_CALL, lambda line: "")
    copy = _mutated_recipe(tmp_path, RECIPE_24, edit)
    assert len(edit.hits) == 1, "the mutation must remove exactly the test split's call"
    violations = _side_effect_violations(RECIPE_24, copy)
    assert violations == [
        "the notebook executes helpers.submit_reviews at 1 call site(s), the inventory requires at least 2"
    ]


def test_deleting_every_submit_reviews_call_is_caught(tmp_path):
    edit = _replace_line("helpers.submit_reviews(", lambda line: "")
    copy = _mutated_recipe(tmp_path, RECIPE_24, edit)
    assert len(edit.hits) == 2
    assert _side_effect_violations(RECIPE_24, copy)
    # An unlisted recipe with the same gap is caught by the general rule, not only by the floor.
    assert any("never executes" in v for v in _side_effect_violations("99-not-in-inventory", copy))


@pytest.mark.parametrize(
    ("name", "make"),
    [
        ("a comment", lambda line: "# " + line.lstrip()),
        ("a string", lambda line: f'"""{line.strip()}"""\n'),
        ("an if False branch", lambda line: f"if False:\n    {line.strip()}\n"),
        ("a while False loop", lambda line: f"while False:\n    {line.strip()}\n"),
        ("a loop over an empty list", lambda line: f"for _ in []:\n    {line.strip()}\n"),
        ("a function never called", lambda line: f"def _never():\n    {line.strip()}\n"),
        ("a lambda never called", lambda line: f"_never = lambda: {line.strip()}\n"),
        ("after a raise", lambda line: f"raise SystemExit\n{line}"),
    ],
)
def test_a_dead_or_inert_mention_of_the_call_does_not_satisfy_the_guard(tmp_path, name, make):
    edit = _replace_line(RECIPE_24_TEST_CALL, make)
    copy = _mutated_recipe(tmp_path, RECIPE_24, edit)
    assert len(edit.hits) == 1
    violations = _side_effect_violations(RECIPE_24, copy)
    assert violations, f"{name} must not count as invoking the side effect"
    assert "at least 2" in violations[0]


def test_a_call_moved_into_a_function_that_is_called_still_counts(tmp_path):
    """The guard is not tied to the call sitting at cell level: a notebook-defined function that
    live code calls counts for what its body calls."""
    edit = _replace_line(
        RECIPE_24_TEST_CALL,
        lambda line: f"def _fill_test():\n    {line.strip()}\n\n\n_fill_test()\n",
    )
    copy = _mutated_recipe(tmp_path, RECIPE_24, edit)
    assert _side_effect_violations(RECIPE_24, copy) == []


def test_an_inline_recipe_is_caught_when_its_queue_submit_is_deleted(tmp_path):
    slug = "02-refund-intent-detection"
    assert _side_effect_violations(slug, RECIPES_DIR / slug) == []
    edit = _replace_line("queue.submit(", lambda line: line.replace("queue.submit(", "print("))
    copy = _mutated_recipe(tmp_path, slug, edit)
    assert len(edit.hits) == 2
    violations = _side_effect_violations(slug, copy)
    assert "ReviewQueue.submit at 0 call site(s)" in violations[0]
    assert any("never calls a mutating method" in v for v in violations)


def test_a_helper_with_a_side_effect_that_the_notebook_never_calls_is_reported(tmp_path):
    """The original gap in its general form: the helper exists and is tested, the notebook does
    not call it. A recipe the inventory does not list is reported, not passed or skipped."""
    edit = _replace_line("helpers.submit_reviews(", lambda line: "")
    copy = _mutated_recipe(tmp_path, RECIPE_24, edit)
    report = side_effect_report(copy)
    assert report.effect_functions == {"submit_reviews"}
    assert report.counts() == {}
    assert report.uncalled_effect_functions() == ["submit_reviews"]
    assert _side_effect_violations("99-not-in-inventory", copy)


def test_an_unlisted_recipe_with_a_working_side_effect_passes_the_general_rule():
    assert _side_effect_violations("99-not-in-inventory", RECIPES_DIR / RECIPE_24) == []
    assert (
        _side_effect_violations("99-not-in-inventory", RECIPES_DIR / "02-refund-intent-detection")
        == []
    )


def test_an_unlisted_recipe_with_no_side_effect_is_neither_failed_nor_silently_passed():
    """``None`` makes the parametrised test skip with a reason that names the missing entry."""
    assert (
        _side_effect_violations("99-not-in-inventory", RECIPES_DIR / "01-sentiment-classification")
        is None
    )


def test_a_recipe_listed_as_having_no_side_effect_fails_if_it_acquires_one(tmp_path):
    # Recipe 24's notebook under the inventory entry of a recipe that claims to have none.
    violations = _side_effect_violations("01-sentiment-classification", RECIPES_DIR / RECIPE_24)
    assert any("no simulated side effect" in v for v in violations)


def test_an_unparseable_notebook_cell_fails_rather_than_being_skipped(tmp_path):
    copy = _mutated_recipe(tmp_path, RECIPE_24, lambda source: source)
    path = copy / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    notebook["cells"].append(
        {"cell_type": "code", "metadata": {}, "outputs": [], "source": ["%matplotlib inline\n"]}
    )
    path.write_text(json.dumps(notebook), "utf-8")
    violations = _side_effect_violations(RECIPE_24, copy)
    assert any("does not parse" in v for v in violations)


def test_a_sink_the_notebook_builds_but_never_reaches_is_reported(tmp_path):
    slug = "10-answer-relevance-check"
    edit = _replace_line("queue = ReviewQueue()", lambda line: line + "orphan = ReviewQueue()\n")
    copy = _mutated_recipe(tmp_path, slug, edit)
    violations = _side_effect_violations(slug, copy)
    assert violations == [
        "the notebook builds ['orphan'] but never calls a mutating method on it or passes it "
        "to a side-effect function"
    ]


def _synthetic_recipe(tmp_path: Path, cells: list[str], helpers_source: str = "") -> Path:
    """A throwaway recipe folder: a notebook of the given code cells and an optional helpers.py."""
    folder = tmp_path / "99-synthetic"
    folder.mkdir()
    notebook = {
        "cells": [
            {"cell_type": "code", "metadata": {}, "outputs": [], "source": src.splitlines(True)}
            for src in cells
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (folder / "notebook.ipynb").write_text(json.dumps(notebook), "utf-8")
    if helpers_source:
        (folder / "helpers.py").write_text(helpers_source, "utf-8")
    return folder


SYNTHETIC_HELPERS = """
from jev_cookbook.simulation import fill_review_queue


def leaf(queue, item):
    queue.submit(item, "because")


def via_leaf(queue, items):
    for item in items:
        leaf(queue, item)


def via_shared(queue, outcomes):
    return fill_review_queue(queue, outcomes, needs_review=bool, item=dict, reason="r")


def pure(x):
    return x + 1
"""


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        # a helper that reaches a mutating method only through another helper still counts
        (
            ["helpers = load_helpers()\nq = ReviewQueue()\nhelpers.via_leaf(q, [])"],
            {"helpers.via_leaf": 1},
        ),
        (
            ["helpers = load_helpers()\nq = ReviewQueue()\nhelpers.via_shared(q, [])"],
            {"helpers.via_shared": 1},
        ),
        # a pure helper is not a side effect, so calling it does not satisfy the guard
        (["helpers = load_helpers()\nq = ReviewQueue()\nhelpers.pure(1)"], {}),
        # try/with/match bodies and comprehensions are live code
        (
            [
                "helpers = load_helpers()\nq = ReviewQueue()\n"
                "try:\n    helpers.leaf(q, 1)\nexcept ValueError:\n    pass\n"
                "with open('x') as f:\n    helpers.leaf(q, 2)\n"
                "match 1:\n    case 1:\n        helpers.leaf(q, 3)\n"
                "[helpers.leaf(q, i) for i in range(2)]"
            ],
            {"helpers.leaf": 4},
        ),
        # aliases of the simulation module and of a sink class resolve
        (
            [
                "import jev_cookbook.simulation as sim\nfrom jev_cookbook.simulation "
                "import ActionLog as AL\nlog = AL()\nlog.record('k')\nsim.fill_review_queue("
                "sim.ReviewQueue(), [], needs_review=bool, item=dict, reason='r')"
            ],
            {"ActionLog.record": 1, "fill_review_queue": 1},
        ),
        # tuple binding, and a notebook-defined function counts only when live code calls it
        (
            [
                "a, q = ActionLog(), ReviewQueue()\n"
                "def go():\n    q.submit({}, 'r')\n    a.record('k')\ndef unused():\n    q.submit({}, 'r')\ngo()"
            ],
            {"ActionLog.record": 1, "ReviewQueue.submit": 1},
        ),
        # a name that merely looks like a sink method on an unrelated object is not counted
        (["d = {}\nd.put = 1\nclass X:\n    def submit(self): ...\nX().submit()"], {}),
    ],
)
def test_the_site_counter_on_synthetic_notebooks(tmp_path, cells, expected):
    header = "from jev_cookbook.simulation import ActionLog, ReviewQueue\n"
    cells = [header + cells[0], *cells[1:]]
    report = side_effect_report(_synthetic_recipe(tmp_path, cells, SYNTHETIC_HELPERS))
    assert report.effect_functions == {"leaf", "via_leaf", "via_shared"}
    assert report.counts() == expected


def test_the_inventory_matches_what_the_published_recipes_do_today():
    """Every inventoried recipe passes, with nothing allowlisted and nothing skipped."""
    for recipe in PUBLISHED:
        if recipe["slug"] in SIDE_EFFECT_INVENTORY:
            assert _side_effect_violations(recipe["slug"], recipe_dir(recipe)) == [], recipe["slug"]
