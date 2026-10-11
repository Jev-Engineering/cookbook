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
disagree on it between themselves) -- and then asserts what is left is the same. For ``measured``
that is plain equality (the two sides are the same length once the noun is masked). For ``setup``
it is "every statement the scaffold emits appears, in order, in the template", because the
template is a filled-in worked example and legitimately carries extra statements (``selection``)
the scaffold's still-TODO evaluation cells have no use for yet; this degenerates to equality
whenever the two sides are in fact the same length, so one helper serves both cells.

Either way this is one assertion per cell, not a list of remembered rules, and it is blind to
the specific property #215 found: deleting the offline ``N`` print (or any other statement, from
either side) changes that side's statement sequence, which the comparison catches without this
module's code ever testing for the word "N". See
``test_the_measured_comparison_is_blind_to_n_and_still_catches_215`` for the proof, and the pull
request description for the on-disk mutation against the real generator that backs the same
claim.

PLAINLY, so a reader is not misled about the strength of either guarantee: ``measured`` is
checked for EQUALITY -- the scaffold's and the template's normalised statement lists must be the
same list, in the same order, nothing more on either side. ``setup`` is checked as an ordered
SUBSEQUENCE -- every normalised statement the scaffold emits must appear, in order, in the
template's, but the template is allowed extra statements (``selection``) the scaffold does not
emit. A subsequence check is weaker than equality: it cannot notice the template losing a
statement the scaffold never had in the first place. It is the right check here only because the
template is a genuinely larger, filled-in worked example and the scaffold a smaller skeleton --
not a device to make a mismatch pass. Every statement the two sides *do* share is still compared
exactly, so a change to any of ``scored``, ``offline``, ``check``, or the ``run_header(...)``
call -- on either side -- still fails the check (see
``test_the_setup_comparison_catches_a_changed_offline_definition``).
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


def _is_subsequence(small: list[str], big: list[str]) -> bool:
    """True if every item of ``small`` appears in ``big``, in the same relative order (``big``
    may hold extra items between matches). Equivalent to equality when the two lists are the
    same length, which is exactly what lets one helper serve both cells below: ``measured`` is
    the same length on both sides once the noun is masked, so this degenerates to plain
    equality there; ``setup``'s template side carries the extra, legitimately template-only
    ``selection`` statement, so this is a genuine subsequence check there."""
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


@pytest.mark.parametrize("mode", ["replay", "scripted"])
def test_the_scaffolded_setup_cell_is_a_subsequence_of_the_templates(mode):
    """Every mode-neutral statement the scaffold's ``setup`` cell emits -- ``scored``,
    ``offline``, ``check``, and the ``run_header(...)`` call with its ``n_examples=len(scored)``
    -- must appear, in the same order, in the template's ``setup`` cell. A statement the scaffold
    adds, drops, or rewrites relative to the template fails this; a statement only the template
    has (``selection``, used by its own fully-written evaluation cells) does not.

    This is a SUBSEQUENCE check, not equality (contrast
    ``test_the_scaffolded_measured_cell_matches_the_template`` below, which is equality) --
    deliberately weaker, because the template legitimately carries more than the scaffold here.
    See the module docstring's "PLAINLY" paragraph for what that costs and why it is still the
    right check."""
    generated = _cell(new_recipe.notebook_cells(CATALOG, RECIPE, mode=mode), "setup")
    template = _cell(TEMPLATE_NOTEBOOK["cells"], "setup")
    generated_stmts = mode_neutral_statements(_source(generated))
    template_stmts = mode_neutral_statements(_source(template))
    assert _is_subsequence(generated_stmts, template_stmts), (
        f"scaffolded setup cell ({mode}) is not a subsequence of the template's after "
        f"normalisation:\ngenerated: {generated_stmts}\ntemplate: {template_stmts}"
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
    module, ``mode_neutral_statements`` or ``_is_subsequence`` ever naming "N": the two sides
    simply no longer have the same number of statements in the offline branch. This is the
    "blind to any rule about N" standard both #219 reviewers asked for criterion 2 to meet."""
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
    template_stmts = mode_neutral_statements(_source(_cell(TEMPLATE_NOTEBOOK["cells"], "setup")))
    source = _source(generated)
    broken = source.replace(
        'offline = backend.mode in ("synthetic", "scripted")',
        'offline = backend.mode == "synthetic"',
    )
    assert broken != source
    assert not _is_subsequence(mode_neutral_statements(broken), template_stmts)
