"""Source-derived documentation facts; editable prose is not a golden string."""

import ast
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent.parent
HELPERS = {"stable_permutation", "stable_shuffle"}
FIXTURE_MODULES = {"jev_cookbook.fixtures", "jev_cookbook.fixtures.permutation"}
FIGURE_HOME = "notebook-style.md#figure-title-disclosure"
CATALOG_CHECK = "`Catalog (README is current)`"


def _section(text, heading, level=2):
    tokens = MarkdownIt("commonmark").parse(text)
    lines = text.splitlines(keepends=True)
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == f"h{level}":
            if tokens[index + 1].content != heading:
                continue
            start = token.map[1]
            end = next(
                (
                    following.map[0]
                    for following in tokens[index + 3 :]
                    if following.type == "heading_open" and int(following.tag[1:]) <= level
                ),
                len(lines),
            )
            return "".join(lines[start:end])
    raise AssertionError(f"missing section: {heading}")


def _visible_inline_blocks(text):
    """Factual documentation must be reader-visible Markdown, not hidden source.

    Unlike the dash convention, fact inventories exclude HTML comment bodies.
    Code spans remain visible names; fenced/indented code is example content.
    This bounded check does not interpret arbitrary HTML or CSS visibility.
    """
    return [token for token in MarkdownIt("commonmark").parse(text) if token.type == "inline"]


def _visible_words(block):
    return "".join(
        token.content
        if token.type in {"text", "code_inline"}
        else " "
        if token.type in {"softbreak", "hardbreak"}
        else ""
        for token in block.children or []
    )


def _visible_table_lines(text):
    for block in _visible_inline_blocks(text):
        # Raw block.content still contains inline HTML comments, including hidden
        # rows after ordinary paragraph text. Read the visible children instead.
        visible = "".join(
            f"`{token.content}`"
            if token.type == "code_inline"
            else token.content
            if token.type == "text"
            else "\n"
            if token.type in {"softbreak", "hardbreak"}
            else ""
            for token in block.children or []
        )
        for line in visible.splitlines():
            if line.lstrip().startswith("|"):
                yield line


class _HTMLProse(HTMLParser):
    """Keep HTML data text; do not claim to model browser layout or CSS visibility."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_comment(self, data):
        # Comments remain checked documentation; only their delimiters are markup.
        self.parts.extend(("\n", data, "\n"))

    def handle_starttag(self, tag, attrs):
        self.parts.append("\n")

    def handle_endtag(self, tag):
        self.parts.append("\n")


def _html_prose(text):
    parser = _HTMLProse()
    parser.feed(text)
    parser.close()
    return "".join(parser.parts)


def _inline_prose(children):
    parts = []
    for child in children:
        if child.type == "text":
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif child.type == "code_inline":
            parts.append("\n")
        elif child.type == "html_inline":
            parts.append(_html_prose(child.content))
        elif child.children:
            parts.append(_inline_prose(child.children))
    return "".join(parts)


def _prose_blocks(text):
    """Yield prose and its source block's starting line, using CommonMark syntax.

    The parser owns indentation, container/lazy-continuation and code-span rules.
    Fenced/indented code and inline code are exempt. HTML text and comment bodies
    are checked; tag attributes and comment delimiters are markup. Boundaries
    separate code, tags and comments so fragments cannot join into invented words
    or dashes, and a standalone dash in any prose segment remains observable.
    Typography transformations are never enabled:
    replacing '--' with a typographic dash would conceal the defect being checked.
    """
    for block in MarkdownIt("commonmark", {"typographer": False}).parse(text):
        if block.type == "inline":
            yield block.map[0] + 1, _inline_prose(block.children or [])
        elif block.type == "html_block":
            yield block.map[0] + 1, _html_prose(block.content)


def _prose(text):
    return "\n".join(prose for _, prose in _prose_blocks(text))


def _dash_lines(text):
    # Inline tokens have no source map: report the enclosing block's starting line
    # rather than inventing exact offsets after entities, escapes or code spans.
    return [
        line for line, prose in _prose_blocks(text) for _ in re.finditer(r"(?<!\S)--(?!\S)", prose)
    ]


def test_markdown_prose_uses_em_dashes():
    paths = subprocess.run(
        ["git", "ls-files", "--", "*.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert paths, "the Markdown inventory must not be empty"
    problems = [
        f"{path}:{line}"
        for path in paths
        for line in _dash_lines((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert not problems, "use an em dash in prose (block start lines): " + ", ".join(problems)


@pytest.mark.parametrize(
    "text",
    [
        "text -- text",
        "text --\ncontinued",
        "text\n-- continued",
        "--",
        "`code` -- prose",
        "<!-- a comment -- still prose -->",
        "<!-- -- -->",
        "<span>--</span>",
        "<!-- comment -->--<!-- comment -->",
        "`code`--`code`",
        "`unmatched -- prose",
        "`unmatched\n\nProse -- must fail.\n\n`also unmatched",
        "`unmatched\n# Heading -- must fail\n`also unmatched",
        "- `unmatched\n- Prose -- must fail. `",
        "> `unmatched\n\nProse -- must fail. `",
        "> `unmatched\n# Heading -- must fail. `",
        "- `unmatched\n\nProse -- must fail. `",
        "- `unmatched\n# Heading -- must fail. `",
        "    ```\n\nordinary -- prose\n",
        ">     ```\n\nordinary -- prose\n",
        "- item\n\n      ```\n\nordinary -- prose\n",
        "<div>ordinary -- prose</div>",
        "before <span>ordinary -- prose</span> after",
        "<!-- ignored -->\nordinary -- prose",
        "<div><!-- ignored -->ordinary -- prose</div>",
        "> ```\n> code -- code\nProse -- must fail.",
        "- ```\n  code -- code\nProse -- must fail.",
        "- item\n  ```\n  code -- code\nProse -- must fail.",
        r"\`escaped -- prose",
        r"`code\` -- prose",
        "```python\ncode -- code\n```\nprose -- fails",
        "````\n```\n````\nprose -- fails",
        "~~~\n```\n~~~\nprose -- fails",
    ],
)
def test_dash_guard_rejects_prose_mutations(text):
    assert _dash_lines(text)


@pytest.mark.parametrize(
    "text",
    [
        "prose — prose",
        "` -- ` is the convention quoting itself",
        "<!-- accepted-fake-credential -->",
        "prose -`code`- prose",
        "<span>-</span><span>-</span>",
        "prose -<!-- comment -->- prose",
        "<div>prose -<!-- comment -->- prose</div>",
        "    indented -- code",
        "    ```\n    indented -- code\n",
        "   ```\ncode -- code\n   ```",
        ">     indented -- code",
        "- item\n\n      indented -- code",
        # CommonMark permits lazy paragraph continuation: these ticks match.
        "> `unmatched\nProse -- must fail. `",
        "- `multiline\n-- code`",
        "<!-- catalog:recipes:start -->",
        "```bash\npython tool.py -- arg\n```",
        "  ```python\nvalue -- other\n  ```",
        "~~~bash\nvalue -- other\n~~~",
        "````md\n```\nvalue -- other\n```\n````",
        "`code -- code`",
        "``code ` -- ` code``",
        "`multiline\n-- code`",
        "> `multiline\n> -- code`",
        "- `multiline\n  -- code`",
        "> ```\n> code -- code\n> ```",
        "- ```\n  code -- code\n  ```",
        "- item\n  ```\n  code -- code\n  ```",
        "```md\n> quoted -- code\n- list -- code\n```",
        "> ```md\n> > nested -- code\n> ```",
        r"`code -- \`",
        "| --- | --- |",
        "---\n--flag\nword--word",
    ],
)
def test_dash_guard_keeps_real_exceptions(text):
    assert not _dash_lines(text)


def test_indented_literal_fence_does_not_hide_following_prose():
    assert _dash_lines("    ```\n\nordinary -- prose\n") == [3]
    assert re.search(r"\bpredates\b", _prose("    ```\n\nRecipe 12 predates this helper.\n"))


@pytest.mark.parametrize("indent", range(4))
def test_fence_openers_allow_zero_to_three_spaces(indent):
    spaces = " " * indent
    assert not _dash_lines(f"{spaces}```\ncode -- code\n{spaces}```\n")
    assert _dash_lines(f"{spaces}```\ncode -- code\n{spaces}```\nprose -- fails")


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


class _HelperUsage(ast.NodeVisitor):
    """Resolve explicit imports in source order, without importing recipe code.

    Notebook cells share one module scope. Function scopes copy outer bindings,
    with parameters and local stores shadowing them. Dynamic imports, alias
    assignments and execution-dependent branch resolution are outside this scan.
    """

    def __init__(self, bindings=None):
        self.bindings = dict(bindings or {})
        self.imported = set()
        self.calls = set()
        self.functions = {}

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if node.module in FIXTURE_MODULES and alias.name == "*":
                raise AssertionError("enumerate permutation imports instead of using import *")
            self.bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            if node.module in FIXTURE_MODULES and alias.name in HELPERS:
                self.imported.add(alias.name)

    def visit_Import(self, node):
        for alias in node.names:
            self.bindings[alias.asname or alias.name.split(".")[0]] = (
                alias.name if alias.asname else alias.name.split(".")[0]
            )

    def visit_Call(self, node):
        parts = _name(node.func).split(".")
        canonical = ".".join([self.bindings.get(parts[0], ""), *parts[1:]])
        module, _, function = canonical.rpartition(".")
        if module in FIXTURE_MODULES and function in HELPERS:
            self.calls.add(function)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bindings.pop(node.id, None)

    def visit_Assign(self, node):
        self.visit(node.value)
        for target in node.targets:
            self.visit(target)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
            self.visit(node.target)

    def visit_NamedExpr(self, node):
        self.visit(node.value)
        self.visit(node.target)

    def visit_FunctionDef(self, node):
        local = _HelperUsage(self.bindings)
        # Parameters and assignments make a name local throughout the function.
        for child in ast.walk(node):
            if isinstance(child, ast.arg):
                local.bindings.pop(child.arg, None)
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                local.bindings.pop(child.id, None)
        for statement in node.body:
            local.visit(statement)
        self.imported.update(local.imported)
        self.calls.update(local.calls)
        self.functions[node.name] = local.calls
        self.bindings.pop(node.name, None)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        local = _HelperUsage(self.bindings)
        for statement in node.body:
            local.visit(statement)
        self.imported.update(local.imported)
        self.calls.update(local.calls)
        self.bindings.pop(node.name, None)


def _recipe_trees(sources):
    for path, text in sources.items():
        if path.endswith(".ipynb"):
            body = []
            for index, cell in enumerate(json.loads(text)["cells"]):
                if cell["cell_type"] == "code":
                    source = cell["source"]
                    body.extend(ast.parse("".join(source), filename=f"{path}:cell-{index}").body)
            yield path, ast.Module(body=body, type_ignores=[])
        else:
            yield path, ast.parse(text, filename=path)


def _permutation_facts(section, sources):
    rows = []
    # Parse every data row before validating its helper. Filtering by a known
    # helper prefix would silently erase an incorrect attribution.
    for line in _visible_table_lines(section):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells == ["Recipe source", "Function", "Shared helper"]:
            continue
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        assert len(cells) == 3, f"malformed permutation inventory row: {line}"
        values = [re.fullmatch(r"`([^`]+)`", cell) for cell in cells]
        assert all(values), f"malformed permutation inventory row: {line}"
        path, function, helper = (value[1] for value in values)
        assert re.fullmatch(r"recipes/[^/]+/.+\.(?:py|ipynb)", path), (
            f"invalid permutation inventory source: {path}"
        )
        assert function.isidentifier(), f"invalid permutation inventory function: {function}"
        assert helper in HELPERS, f"unknown attributed helper: {helper}"
        rows.append((path, function, helper))
    assert rows, "missing recipe/function/helper inventory"
    assert len(rows) == len(set(rows)), "duplicate permutation inventory row"
    assert not re.search(r"\bpredat\w*\b", _prose(section), re.I), "stale predates-helper claim"
    imported_recipes = set()
    functions = {}
    for path, tree in _recipe_trees(sources):
        usage = _HelperUsage()
        usage.visit(tree)
        # Module imports count when they call a helper through that module.
        if usage.imported or usage.calls:
            imported_recipes.add(path.split("/")[1])
        for function, calls in usage.functions.items():
            functions[(path, function)] = calls
    documented_recipes = {path.split("/")[1] for path, _, _ in rows}
    assert documented_recipes == imported_recipes, (
        f"permutation recipe inventory: docs={sorted(documented_recipes)}, "
        f"imports={sorted(imported_recipes)}"
    )
    for path, function, helper in rows:
        assert (path, function) in functions, f"missing named function {path}:{function}"
        assert helper in functions[(path, function)], (
            f"{path}:{function} does not call attributed helper {helper}"
        )


def _recipe_sources():
    return {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "recipes").rglob("*"))
        if path.suffix in {".py", ".ipynb"}
    }


def test_per_item_order_claims_match_recipe_source():
    section = _section(
        (ROOT / "docs/fixtures.md").read_text(encoding="utf-8"), "Per-item option order"
    )
    _permutation_facts(section, _recipe_sources())


@pytest.mark.parametrize(
    "mutation",
    [
        "predates",
        "predates_between_blocks",
        "unlisted",
        "unlisted_notebook",
        "missing_function",
        "wrong_helper",
        "unsupported_helper",
        "malformed_row",
    ],
)
def test_permutation_fact_mutations_are_observed(mutation):
    section = _section(
        (ROOT / "docs/fixtures.md").read_text(encoding="utf-8"), "Per-item option order"
    )
    sources = _recipe_sources()
    if mutation == "predates":
        section += "\nRecipe 12 predates this helper and migrates separately.\n"
    elif mutation == "predates_between_blocks":
        section += "\n`unmatched\n\nRecipe 12 predates this helper.\n\n`unmatched\n"
    elif mutation == "unlisted_notebook":
        sources["recipes/99-undocumented/notebook.ipynb"] = _notebook_source(
            "import jev_cookbook.fixtures as f",
            "shown = f.stable_shuffle('99:item', [1, 2])",
        )
    elif mutation == "unlisted":
        sources["recipes/99-undocumented/helpers.py"] = (
            "from jev_cookbook.fixtures import stable_shuffle\n"
            "def order():\n    return stable_shuffle('99:item', [1, 2])\n"
        )
    elif mutation == "missing_function":
        section = section.replace("`shuffled_candidates`", "`missing_function`")
    elif mutation == "unsupported_helper":
        section = section.replace(
            "`_demo_rows` | `stable_permutation`", "`_demo_rows` | `random.shuffle`"
        )
    elif mutation == "malformed_row":
        section = section.replace("`_demo_rows` |", "_demo_rows |")
    else:
        section = section.replace(
            "`shuffled_candidates` | `stable_shuffle`",
            "`shuffled_candidates` | `stable_permutation`",
        )
    with pytest.raises(AssertionError):
        _permutation_facts(section, sources)


@pytest.mark.parametrize(
    "source",
    [
        "from jev_cookbook.fixtures import stable_shuffle as mix\n"
        "def order():\n return mix('k', [])",
        "import jev_cookbook.fixtures as f\ndef order():\n return f.stable_shuffle('k', [])",
        "from jev_cookbook import fixtures as f\ndef order():\n return f.stable_shuffle('k', [])",
        "import jev_cookbook.fixtures\ndef order():\n"
        " return jev_cookbook.fixtures.stable_shuffle('k', [])",
    ],
)
def test_permutation_inventory_resolves_import_aliases(source):
    section = "| `recipes/99-example/helpers.py` | `order` | `stable_shuffle` |"
    _permutation_facts(section, {"recipes/99-example/helpers.py": source})
    with pytest.raises(AssertionError, match="inventory"):
        _permutation_facts(section, {"recipes/98-other/helpers.py": source})


def _notebook_source(*cells):
    return json.dumps({"cells": [{"cell_type": "code", "source": cell} for cell in cells]})


@pytest.mark.parametrize("rebound", [False, True])
def test_notebook_inventory_keeps_aliases_across_cells_and_honors_rebinding(rebound):
    path = "recipes/99-example/notebook.ipynb"
    section = f"| `{path}` | `order` | `stable_shuffle` |"
    cells = ["import jev_cookbook.fixtures as f"]
    if rebound:
        cells.append("f = object()")
    cells.append("def order():\n return f.stable_shuffle('99:item', [1, 2])")
    sources = {path: _notebook_source(*cells)}
    if rebound:
        with pytest.raises(AssertionError, match="inventory"):
            _permutation_facts(section, sources)
    else:
        _permutation_facts(section, sources)


@pytest.mark.parametrize(
    "rebind",
    ["f = object()", "import unrelated as f", "from unrelated import fixture as f", "del f"],
)
def test_notebook_alias_rebinding_does_not_invent_an_unlisted_helper_user(rebind):
    section = "| `recipes/98-listed/helpers.py` | `order` | `stable_shuffle` |"
    sources = {
        "recipes/98-listed/helpers.py": (
            "from jev_cookbook.fixtures import stable_shuffle\n"
            "def order():\n return stable_shuffle('98:item', [])"
        ),
        "recipes/99-example/notebook.ipynb": _notebook_source(
            "import jev_cookbook.fixtures as f",
            rebind,
            "shown = f.stable_shuffle('99:item', [1, 2])",
        ),
    }
    _permutation_facts(section, sources)


def test_helper_call_before_rebinding_is_still_observed():
    path = "recipes/99-example/notebook.ipynb"
    usage = _HelperUsage()
    sources = {
        path: _notebook_source(
            "import jev_cookbook.fixtures as f",
            "shown = f.stable_shuffle('99:item', [1, 2])",
            "f = object()",
        )
    }
    _, tree = next(_recipe_trees(sources))
    usage.visit(tree)
    assert usage.calls == {"stable_shuffle"}


def _scaffold_readme_source():
    tree = ast.parse((ROOT / "tools/new_recipe.py").read_text(encoding="utf-8"))
    function = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "readme_text"
    )
    returned = next(n.value for n in function.body if isinstance(n, ast.Return))
    assert isinstance(returned, ast.JoinedStr), "readme_text must expose its README template"
    return "".join(n.value if isinstance(n, ast.Constant) else "{value}" for n in returned.values)


def _red_catalog_claims(text):
    visible = "\n".join(_visible_words(block) for block in _visible_inline_blocks(text))
    # Normalize the visible check name; emphasis, a link or a code span must not
    # determine whether a factual red-check claim is observed.
    visible = re.sub(re.escape(CATALOG_CHECK.strip("`")), lambda _: CATALOG_CHECK, visible)
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(visible.split()))
    return [
        sentence
        for sentence in sentences
        if CATALOG_CHECK in sentence and re.search(r"\bred\b", sentence)
    ]


def _red_conditions(sentence):
    """Recognize a bounded conjunction of publication/integration conditions.

    Supported conditions start with while/if/when/before/until/awaiting, before
    or after the check name. Commas and "and" join positive prerequisites;
    unsupported clauses (including "or" and negated prerequisites) fail closed.
    This checks these documented forms, not arbitrary natural-language equivalence.
    """
    absent = {"unpublished": False, "pending_integration": False}
    before, _, after = sentence.lower().partition(CATALOG_CHECK.lower())
    start = r"\b(?:while|if|when|before|until|awaiting)\b"
    match = re.search(start, before)
    if match:
        condition = re.sub(r",?\s+the\s*$", "", before[match.start() :]).strip(" ,")
    else:
        match = re.search(start, after)
        if not match:
            return absent
        condition = re.split(r"[.;]|,\s*which\b", after[match.start() :])[0].strip(" ,")
    facts = set()
    for clause in re.split(r"\s+and\s+|,\s*", condition):
        clause = re.sub(r"^(?:while|if|when)\s+", "", clause.strip())
        if re.fullmatch(
            r"(?:(?:(?:this|the|a) )?recipe |it )?"
            r"(?:remains |is (?:still )?|still )?(?:unpublished|not yet published)",
            clause,
        ):
            facts.add("unpublished")
        elif re.fullmatch(
            r"(?:before|until|awaiting) (?:(?:that|the) )?"
            r"(?:integration|handover)(?: step| stage)?"
            r"|(?:(?:(?:(?:that|the|this) )?(?:integration|handover)(?: step| stage)?"
            r"|that) (?:has |is )?)?not (?:yet )?"
            r"(?:run|happened|completed|complete|done|handed over)",
            clause,
        ):
            facts.add("pending_integration")
        else:
            return absent
    return {name: name in facts for name in absent}


def _check_catalog_conditions(readme, expected):
    for sentence in _red_catalog_claims(readme):
        assert _red_conditions(sentence) == expected, f"unconditional catalog-red claim: {sentence}"


def test_recipe_readme_catalog_red_claims_keep_the_scaffolder_conditions():
    claims = _red_catalog_claims(_scaffold_readme_source())
    assert len(claims) == 1, "scaffolder must state one catalog-red condition"
    expected = _red_conditions(claims[0])
    assert all(expected.values()), "scaffolder lost its publication/integration conditions"
    readmes = sorted((ROOT / "recipes").glob("*/README.md"))
    assert readmes
    for path in readmes:
        try:
            _check_catalog_conditions(path.read_text(encoding="utf-8"), expected)
        except AssertionError as error:
            raise AssertionError(f"{path.relative_to(ROOT)}: {error}") from error


def test_catalog_fact_accepts_rewording_and_rejects_unconditional_mutation():
    expected = {"unpublished": True, "pending_integration": True}
    _check_catalog_conditions(
        "Before integration, while unpublished and not yet handed over, "
        f"{CATALOG_CHECK} can be red.",
        expected,
    )
    with pytest.raises(AssertionError, match="unconditional"):
        _check_catalog_conditions(
            f"{CATALOG_CHECK} is expected to be red on its pull request.", expected
        )
    source = _red_catalog_claims(_scaffold_readme_source())[0]
    mutated = source[source.index(CATALOG_CHECK) :]
    with pytest.raises(AssertionError, match="unconditional"):
        _check_catalog_conditions(mutated, expected)


@pytest.mark.parametrize(
    "condition",
    [
        "while this recipe remains unpublished and that integration step has not yet run",
        "while this recipe remains unpublished and before integration",
        "before integration, while unpublished and not yet handed over",
        "while not yet published and before integration",
        "before integration and while this recipe remains unpublished",
        "while a recipe remains unpublished and that integration step has not yet run",
        "while this recipe remains unpublished and that handover has not yet happened",
        "while this recipe remains unpublished and that has not yet happened",
    ],
)
@pytest.mark.parametrize("postposed", [False, True])
def test_catalog_conditions_accept_equivalent_order_and_wording(condition, postposed):
    claim = f"the {CATALOG_CHECK} check is expected to be red"
    sentence = f"{claim} {condition}." if postposed else f"{condition}, {claim}."
    _check_catalog_conditions(sentence, {"unpublished": True, "pending_integration": True})


@pytest.mark.parametrize(
    "condition",
    [
        "while this recipe remains unpublished or that integration step has not yet run",
        "while this recipe is not unpublished and before integration",
        "while this recipe remains unpublished and that integration step has run",
        "while this recipe remains published and before integration",
        "while this recipe remains unpublished",
        "before integration",
        "while this recipe remains unpublished and not before integration",
    ],
)
@pytest.mark.parametrize("postposed", [False, True])
def test_catalog_conditions_reject_weakened_or_missing_prerequisites(condition, postposed):
    claim = f"{CATALOG_CHECK} is expected to be red"
    sentence = f"{claim} {condition}." if postposed else f"{condition}, {claim}."
    with pytest.raises(AssertionError, match="unconditional"):
        _check_catalog_conditions(sentence, {"unpublished": True, "pending_integration": True})


def test_catalog_scaffold_conjunction_mutation_is_observed():
    claim = _red_catalog_claims(_scaffold_readme_source())[0]
    mutated = claim.replace("unpublished and", "unpublished or")
    assert mutated != claim
    with pytest.raises(AssertionError, match="unconditional"):
        _check_catalog_conditions(mutated, {"unpublished": True, "pending_integration": True})


def _figure_rule_home(style_doc, template_doc):
    home = _section(style_doc, "Figure title disclosure", level=3)
    template_blocks = _visible_inline_blocks(template_doc)
    links = [
        token.attrGet("href")
        for block in template_blocks
        for token in block.children or []
        if token.type == "link_open"
    ]
    assert FIGURE_HOME in links, "template must reference the figure rule home"
    # This function identifies the one-answer carve-out. It belongs to the style API
    # reference only; restoring its old inline carve-out recreates the duplication.
    assert "plot_answer_probabilities" in "\n".join(
        _visible_words(block) for block in _visible_inline_blocks(home)
    ), "missing one-answer carve-out"
    assert "plot_answer_probabilities" not in "\n".join(
        _visible_words(block) for block in template_blocks
    ), "duplicated one-answer carve-out"


def test_figure_disclosure_rule_has_one_home():
    _figure_rule_home(
        (ROOT / "docs/notebook-style.md").read_text(encoding="utf-8"),
        (ROOT / "docs/recipe-template.md").read_text(encoding="utf-8"),
    )


def test_mutating_one_figure_rule_copy_is_observed():
    style_doc = (ROOT / "docs/notebook-style.md").read_text(encoding="utf-8")
    template_doc = (ROOT / "docs/recipe-template.md").read_text(encoding="utf-8")
    with pytest.raises(AssertionError, match="duplicated"):
        _figure_rule_home(
            style_doc,
            template_doc + "\n`plot_answer_probabilities` carries no disclosure label at all.\n",
        )
    with pytest.raises(AssertionError, match="reference"):
        _figure_rule_home(style_doc, template_doc.replace(FIGURE_HOME, "notebook-style.md"))
    # Editing canonical prose keeps the structural fact true.
    _figure_rule_home(
        style_doc.replace("need not carry one", "does not require that label"), template_doc
    )


def _chart_functions(source):
    tree = ast.parse(source)
    return {
        n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("plot_")
    }


def _documented_chart_functions(text):
    return {
        match[1]
        for line in _visible_table_lines(text)
        if (match := re.match(r"^\| `(plot_\w+)\(", line))
    }


@pytest.mark.parametrize(
    "name",
    [
        "Catalog (README is current)",
        "**Catalog (README is current)**",
        "*Catalog (README is current)*",
        "[Catalog (README is current)](https://example.invalid/check)",
        "`Catalog (README is current)`",
        "Catalog (**README** is current)",
    ],
)
def test_catalog_check_formatting_cannot_hide_unconditional_claim(name):
    expected = {"unpublished": True, "pending_integration": True}
    with pytest.raises(AssertionError, match="unconditional"):
        _check_catalog_conditions(f"{name} is expected to be red on its pull request.", expected)
    _check_catalog_conditions(
        f"While unpublished and before integration, {name} can be red.", expected
    )


@pytest.mark.parametrize("wrapper", ["<!--\n{}\n-->", "```markdown\n{}\n```", "    {}"])
def test_hidden_or_example_inventories_do_not_supply_reader_facts(wrapper):
    section = "| `recipes/99-example/helpers.py` | `order` | `stable_shuffle` |"
    sources = {
        "recipes/99-example/helpers.py": "from jev_cookbook.fixtures import stable_shuffle\ndef order():\n return stable_shuffle('k', [])"
    }
    with pytest.raises(AssertionError, match="inventory"):
        _permutation_facts(wrapper.format(section), sources)
    assert not _documented_chart_functions(wrapper.format("| `plot_example()` | chart |"))


@pytest.mark.parametrize("wrapper", ["<!--\n{}\n-->", "```markdown\n{}\n```", "    {}"])
def test_hidden_or_example_figure_link_does_not_supply_cross_reference(wrapper):
    style_doc = (
        "### Figure title disclosure\n\n`plot_answer_probabilities` is the one-answer case.\n"
    )
    link = f"See [the rule]({FIGURE_HOME})."
    with pytest.raises(AssertionError, match="reference"):
        _figure_rule_home(style_doc, wrapper.format(link))
    _figure_rule_home(style_doc, link)


@pytest.mark.parametrize("wrapper", ["<!--\n{}\n-->", "```markdown\n{}\n```"])
def test_hidden_section_heading_does_not_establish_a_rule_home(wrapper):
    style_doc = (
        "### Figure title disclosure\n\n`plot_answer_probabilities` is the one-answer case.\n"
    )
    with pytest.raises(AssertionError, match="missing section"):
        _figure_rule_home(wrapper.format(style_doc), f"[the rule]({FIGURE_HOME})")


def test_inline_html_comment_does_not_supply_visible_inventory():
    row = "| `recipes/99-example/helpers.py` | `order` | `stable_shuffle` |"
    sources = {
        "recipes/99-example/helpers.py": "from jev_cookbook.fixtures import stable_shuffle\n"
        "def order():\n return stable_shuffle('k', [])"
    }
    with pytest.raises(AssertionError, match="inventory"):
        _permutation_facts(f"Inventory <!--\n{row}\n-->", sources)
    assert not _documented_chart_functions("Inventory <!--\n| `plot_example()` | chart |\n-->")


def test_inline_html_comment_does_not_supply_figure_cross_reference():
    style = "### Figure title disclosure\n\n`plot_answer_probabilities` is the one-answer case.\n"
    with pytest.raises(AssertionError, match="reference"):
        _figure_rule_home(style, f"Documentation <!--\n[the rule]({FIGURE_HOME})\n-->")


def test_style_chart_function_inventory_matches_source():
    source = (ROOT / "src/jev_cookbook/style.py").read_text(encoding="utf-8")
    doc = (ROOT / "docs/notebook-style.md").read_text(encoding="utf-8")
    assert _documented_chart_functions(doc) == _chart_functions(source)


def test_chart_inventory_mutation_is_observed():
    source = (ROOT / "src/jev_cookbook/style.py").read_text(encoding="utf-8")
    doc = (ROOT / "docs/notebook-style.md").read_text(encoding="utf-8")
    mutated = source + "\ndef plot_undocumented():\n    pass\n"
    assert _documented_chart_functions(doc) != _chart_functions(mutated)
