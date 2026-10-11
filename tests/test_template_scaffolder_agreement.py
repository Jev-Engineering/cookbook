"""Issue #215 acceptance criterion 2: ``recipes/_template/notebook.ipynb`` and what
``tools/new_recipe.py`` generates provably agree, on the two cells ``CONTRIBUTING.md`` section 2
depends on (``setup`` and ``measured``) -- not merely "the two files happen to say similar
things today", which is what #215 itself was: the scaffolder's ``measured`` cell went weeks
without printing the offline ``N`` the template prints, undetected, because nothing compared the
two sources to each other.

Why this is normalised STRUCTURAL EQUALITY and not a checklist of named properties (per issue
#215 comment 6107125765, and the two Opus reviews of PR #219, comments 6106985827 and
6107101685, which independently reached the same conclusion): #215's own property -- "the offline
branch prints N" -- was not an unwritten rule nobody thought of. It *was* written, as
``tests/test_new_recipe.py``'s old ``"N:" in measured`` assertion. The defect was that the
assertion could not fail: the live branch's own ``N:`` line satisfied it regardless of what the
offline branch did. A hand-maintained list of properties repeats exactly that mistake by
construction -- it is only as strong as what someone remembers to add to it, and would not have
been any stronger here, since "prints N" was already on the list. So this module names no
property of either source. It parses each cell with ``ast``, normalises away what the two
sources are allowed to differ on for reasons that have nothing to do with #215's defect --
import lines (the template's later cells are fully written and need imports the scaffold's TODO
stubs do not yet use), the recipe-identifying literals (``run_header``'s number and title, and
the ``backend = ...`` construction, which is a different call shape in replay vs. scripted mode,
not a different literal), the counted-noun phrase in the "N: ..." line (``scored`` vs.
``val_examples``/``test_examples``; recipe 23 counts "test comparisons" and 24 "test tickets", so
the noun varies legitimately across the published set, and the template and the scaffold already
disagree on it between themselves) -- and then asserts what is left is the same, on both cells,
by EQUALITY.

The ``setup`` cell's template side carries exactly one statement the scaffold's still-TODO
evaluation cells have no use for yet: ``selection``, used only by the template's own
fully-written evaluation cells. That one statement, and no other, is named in
``TEMPLATE_ONLY_SETUP_STATEMENTS`` and filtered out of the template's side before the equality
check runs. Naming it rather than reaching for a weaker check (a subsequence, "every statement
the scaffold emits appears, in order, in the template's") matters because a subsequence check
is satisfied by *any* omission on the scaffold side -- a shorter list is still a subsequence of a
longer one. That is exactly #215's own defect direction: the scaffolder silently dropping
something the template has. Equality modulo the one named allowance closes that direction too:
the scaffolder dropping, adding, or rewriting any statement on either side -- including
``selection`` growing a second template-only statement nobody added to the allowance -- fails
the comparison. See ``test_the_setup_comparison_catches_a_dropped_statement`` for the proof in
that direction and ``test_the_setup_comparison_catches_a_changed_offline_definition`` for a
reword.

This is one assertion per cell, not a list of remembered rules, and it is blind to the specific
property #215 found: deleting the offline ``N`` print (or any other statement, from either side)
changes that side's statement sequence, which the comparison catches without this module's code
ever testing for the word "N". See
``test_the_measured_comparison_is_blind_to_n_and_still_catches_215`` for the proof, and the pull
request description for the on-disk mutation against the real generator that backs the same
claim.

PLAINLY, so a reader is not misled about the strength of either guarantee: both ``measured`` and
``setup`` are checked for EQUALITY of the two sides' normalised statement lists, in the same
order. ``setup``'s equality is taken after filtering the one named, template-only statement in
``TEMPLATE_ONLY_SETUP_STATEMENTS`` out of the template's side; every other statement either side
carries must match the other's exactly, including by not being dropped. Nothing is checked only
as a subsequence. The one thing neither comparison can see is a drift applied identically to
both sides at once (that is inherent to any agreement check, not a gap specific to this one), and
neither covers the cells outside ``setup`` and ``measured`` -- see CONTRIBUTING.md section 2 for
why those two are the ones that matter here.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TEMPLATE_NOTEBOOK = json.loads(
    (REPO / "recipes" / "_template" / "notebook.ipynb").read_text("utf-8")
)
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{name}_for_agreement_test", REPO / "tools" / name
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


new_recipe = load_tool("new_recipe.py")

# Any catalog recipe works: the comparison below normalises away everything recipe-specific
# (the number, the title, the noun). Recipe 1 is simply the first one in the catalog.
RECIPE = next(r for r in CATALOG["recipes"] if r["rank"] == 1)


def _cell(cells: list[dict], cell_id: str) -> dict:
    return next(c for c in cells if c.get("id") == cell_id)


def _source(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


class _MaskRecipeIdentifyingLiterals(ast.NodeTransformer):
    """The two things a correct, unbroken cell is still allowed to differ on: a
    ``run_header(...)`` call's first two positional arguments (the recipe number and title --
    they identify the recipe, not its structure) and a ``backend = ...`` assignment's value
    (``fixtures=responses_path()`` for a replay recipe, ``script=helpers.script,
    seed=helpers.SEED`` for a scripted one -- a different call shape, not a different literal,
    so the text-level noun masking below cannot normalise it)."""

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "run_header" and len(node.args) >= 2:
            node.args[0] = ast.Constant(value="<RECIPE-NUMBER>")
            node.args[1] = ast.Constant(value="<RECIPE-TITLE>")
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        self.generic_visit(node)
        target = node.targets[0] if len(node.targets) == 1 else None
        if isinstance(target, ast.Name) and target.id == "backend":
            node.value = ast.Constant(value="<BACKEND>")
        return node


# The "N: ..." print's counted-noun phrase: masks "20 scored examples" and "12 validation and 8
# test examples" (or recipe 23's "19 test comparisons", 24's "19 test tickets") to the same
# thing. ``ast.unparse`` always renders an f-string with single quotes regardless of the source's
# own quoting, so the pattern matches the quote it actually emits.
_N_LINE = re.compile(r"(f'N: ).*?(\{check\})?(')")


def _mask_n_line(text: str) -> str:
    return _N_LINE.sub(lambda m: m.group(1) + "<N>" + (m.group(2) or "") + m.group(3), text)


def mode_neutral_statements(source: str) -> list[str]:
    """Every top-level statement of a code cell, normalised for comparison: import lines
    dropped (the scaffold's TODO cells need fewer imports than the template's filled-in ones --
    not a structural disagreement), the two recipe-identifying literals above masked, then
    re-emitted by ``ast.unparse`` -- which, as a side effect, drops every comment and
    canonicalises whitespace, so the scaffold's trailing "# TODO: and N for each reported
    metric" comment vanishes on its own rather than needing a rule of its own -- and finally the
    "N: ..." line's counted-noun phrase masked."""
    tree = ast.parse(source)
    tree = _MaskRecipeIdentifyingLiterals().visit(tree)
    ast.fix_missing_locations(tree)
    return [
        _mask_n_line(ast.unparse(node))
        for node in tree.body
        if not isinstance(node, (ast.Import, ast.ImportFrom))
    ]


# The complete list of statements the template's ``setup`` cell is allowed to carry that the
# scaffold's still-TODO cells have no use for yet. ``selection`` is used only by the template's
# own fully-written evaluation cells. Any statement the template carries that is not in this
# tuple, and any statement the scaffold drops, adds, or rewrites relative to what remains, fails
# the equality check below -- see the module docstring's "PLAINLY" paragraph.
TEMPLATE_ONLY_SETUP_STATEMENTS = ("selection = ' (a selection step, not a reported result)'",)


def _setup_template_stmts(source: str) -> list[str]:
    """The template's ``setup`` cell, normalised, with the one named template-only statement in
    ``TEMPLATE_ONLY_SETUP_STATEMENTS`` filtered out -- what the scaffold's ``setup`` cell must
    equal."""
    return [s for s in mode_neutral_statements(source) if s not in TEMPLATE_ONLY_SETUP_STATEMENTS]


@pytest.mark.parametrize("mode", ["replay", "scripted"])
def test_the_scaffolded_setup_cell_matches_the_template_modulo_the_named_allowance(mode):
    """Every mode-neutral statement the scaffold's ``setup`` cell emits -- ``scored``,
    ``offline``, ``check``, and the ``run_header(...)`` call with its ``n_examples=len(scored)``
    -- must equal, in the same order, the template's ``setup`` cell once the one named,
    template-only statement in ``TEMPLATE_ONLY_SETUP_STATEMENTS`` (``selection``, used by the
    template's own fully-written evaluation cells) is filtered out of the template's side. A
    statement either side adds, drops, or rewrites relative to the other fails this -- including
    the scaffold dropping a statement the template has, which is issue #215's own defect
    direction (see ``test_the_setup_comparison_catches_a_dropped_statement`` below).

    This is EQUALITY, exactly like ``test_the_scaffolded_measured_cell_matches_the_template``
    below, not a weaker subsequence check: see the module docstring's "PLAINLY" paragraph."""
    generated = _cell(new_recipe.notebook_cells(CATALOG, RECIPE, mode=mode), "setup")
    template = _cell(TEMPLATE_NOTEBOOK["cells"], "setup")
    generated_stmts = mode_neutral_statements(_source(generated))
    template_stmts = _setup_template_stmts(_source(template))
    assert generated_stmts == template_stmts, (
        f"scaffolded setup cell ({mode}) does not match the template's after normalisation "
        f"(modulo {TEMPLATE_ONLY_SETUP_STATEMENTS}):\ngenerated: {generated_stmts}\n"
        f"template: {template_stmts}"
    )


@pytest.mark.parametrize("mode", ["replay", "scripted"])
def test_the_scaffolded_measured_cell_matches_the_template(mode):
    """The scaffold's ``measured`` cell, normalised, must equal the template's ``measured`` cell,
    normalised -- both branches, not only the offline one: this is the structural check that
    closes issue #215's acceptance criterion 2, and it is also what restores the live-branch
    coverage the #219 round narrowed (see issue #215 comment 6107125765, "Restore the
    live-branch coverage"): deleting either branch's ``N:`` print from the scaffolder, in either
    mode, makes this fail (proved on the real generator by mutation; see the pull request
    description)."""
    generated = _cell(new_recipe.notebook_cells(CATALOG, RECIPE, mode=mode), "measured")
    template = _cell(TEMPLATE_NOTEBOOK["cells"], "measured")
    generated_stmts = mode_neutral_statements(_source(generated))
    template_stmts = mode_neutral_statements(_source(template))
    assert generated_stmts == template_stmts, (
        f"scaffolded measured cell ({mode}) does not match the template's after "
        f"normalisation:\ngenerated: {generated_stmts}\ntemplate: {template_stmts}"
    )


def test_the_measured_comparison_is_blind_to_n_and_still_catches_215():
    """Reproduces the historical #215 defect directly against the real generated cell -- delete
    the offline branch's own ``N:`` print -- and shows the comparison disagrees, without this
    module or ``mode_neutral_statements`` ever naming "N": the two sides simply no longer have
    the same number of statements in the offline branch. This is the "blind to any rule about N"
    standard both #219 reviewers asked for criterion 2 to meet."""
    generated = _cell(new_recipe.notebook_cells(CATALOG, RECIPE, mode="replay"), "measured")
    template_stmts = mode_neutral_statements(_source(_cell(TEMPLATE_NOTEBOOK["cells"], "measured")))
    source = _source(generated)
    broken = re.sub(
        r'\n *print\(f"N: \{len\(scored\)\} scored examples\{check\}"\)', "", source, count=1
    )
    assert broken != source, "the mutation did not change anything -- the regex did not match"
    assert mode_neutral_statements(broken) != template_stmts


def test_the_measured_comparison_catches_a_dropped_live_branch_print_too():
    """The same mutation on the *live* (``else``) branch's ``N:`` print, which #219 left
    uncovered by any assertion on the scaffolder side (issue #215 comment 6107125765, "Restore
    the live-branch coverage"): this comparison fails on it too, by construction, with no
    branch-specific code anywhere in this module."""
    generated = _cell(new_recipe.notebook_cells(CATALOG, RECIPE, mode="replay"), "measured")
    template_stmts = mode_neutral_statements(_source(_cell(TEMPLATE_NOTEBOOK["cells"], "measured")))
    source = _source(generated)
    broken = source.replace(
        '\n    print(f"N: {len(scored)} scored examples")  # TODO: and N for each reported metric',
        "",
    )
    assert broken != source, "the mutation did not change anything"
    assert mode_neutral_statements(broken) != template_stmts


def test_the_setup_comparison_catches_a_changed_offline_definition():
    """A ``setup``-cell regression unrelated to ``N`` -- rewording ``offline``'s definition --
    is also caught, proving the structural comparison is not special-cased to the measured
    cell's own property."""
    generated = _cell(new_recipe.notebook_cells(CATALOG, RECIPE, mode="replay"), "setup")
    template_stmts = _setup_template_stmts(_source(_cell(TEMPLATE_NOTEBOOK["cells"], "setup")))
    source = _source(generated)
    broken = source.replace(
        'offline = backend.mode in ("synthetic", "scripted")',
        'offline = backend.mode == "synthetic"',
    )
    assert broken != source
    assert mode_neutral_statements(broken) != template_stmts


@pytest.mark.parametrize(
    "removed_line",
    [
        pytest.param(
            '\ncheck = " (a pipeline check, not a Jev result)" if offline else ""',
            id="check",
        ),
        pytest.param("\napply_style()", id="apply_style"),
        pytest.param(
            '\nscored = [e for e in examples if e.split not in ("train", "demo")]',
            id="scored",
        ),
    ],
)
def test_the_setup_comparison_catches_a_dropped_statement(removed_line):
    """Issue #215 was the scaffolder silently *dropping* a statement the template has -- not
    adding or rewording one. This reproduces that direction directly against the real generated
    ``setup`` cell: delete one of its own statements and show the comparison disagrees. A
    subsequence check (a shorter generated list is still a subsequence of a longer template list)
    would not catch any of these three; equality modulo ``TEMPLATE_ONLY_SETUP_STATEMENTS`` catches
    all three, because dropping a statement changes the length, and the two normalised lists are
    no longer the same list."""
    generated = _cell(new_recipe.notebook_cells(CATALOG, RECIPE, mode="replay"), "setup")
    template_stmts = _setup_template_stmts(_source(_cell(TEMPLATE_NOTEBOOK["cells"], "setup")))
    source = _source(generated)
    broken = source.replace(removed_line, "", 1)
    assert broken != source, "the mutation did not change anything -- the line was not found"
    assert mode_neutral_statements(broken) != template_stmts
