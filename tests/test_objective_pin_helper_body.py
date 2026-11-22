"""Extraction pins must account for objective spellings in the called helper (#540).

These tests use the guard's recipe-wide pool and final verdict, rather than prescribing a
new internal helper API. Fixtures are source text the guard analyses; only the small, local
AST extractor in the recipe-42 regression is executed to prove the fallback's behaviour.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
from pathlib import Path
from textwrap import dedent

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location(
        "recipe_guard_for_helper_body_tests", Path(__file__).with_name("test_recipe_guard.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PARAMETER_HELPER = '''\
def _extract(source, keyword):
    """Extract precisely the requested keyword, with no fallback."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            for item in node.keywords:
                if item.arg == keyword:
                    return ast.literal_eval(item.value)
    return None
'''

_FALLBACK_HELPER = """\
def _fallback_keyword(source, keyword):
    for candidate in (keyword, "target_accuracy"):
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "select_confidence_threshold"
            ):
                for item in node.keywords:
                    if item.arg == candidate:
                        return ast.literal_eval(item.value)
    return None
"""


def _pool_fixture(tmp_path: Path, helpers: str, body: str) -> Path:
    """A minimal recipe tests directory for the real pool collector; no fixture is imported."""
    folder = tmp_path / "recipe"
    tests = folder / "tests"
    tests.mkdir(parents=True)
    source = (
        "import ast\nfrom pathlib import Path\nRECIPE = Path(__file__).parent.parent\n\n"
        + dedent(helpers)
        + "\n\ndef test_pin():\n"
        + '    source = (RECIPE / "notebook.ipynb").read_text("utf-8")\n'
        + "\n".join("    " + line for line in dedent(body).strip().splitlines())
        + "\n"
    )
    ast.parse(source)
    (tests / "test_helpers.py").write_text(source, encoding="utf-8")
    return folder


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("min_coverage", {"min_coverage"}),
        ("target_accuracy", {"target_accuracy"}),
        ("f1", {"f1"}),
        ("recall_at_precision", {"recall_at_precision"}),
        ("precision_at_recall", {"precision_at_recall"}),
    ],
)
@pytest.mark.parametrize("assertion", ["assert value is not None", "assert None is not value"])
def test_parameterized_helper_keeps_one_spelling_credit(
    tmp_path, guard, spelling, expected, assertion
):
    folder = _pool_fixture(
        tmp_path,
        _PARAMETER_HELPER,
        f'value = _extract(source, "{spelling}")\n{assertion}',
    )
    assert guard._pinned_objective_spellings(folder) == expected


@pytest.mark.parametrize(
    "helper",
    [
        _FALLBACK_HELPER,
        # A helper that hard-codes the same spelling still supplies its own answer.
        _PARAMETER_HELPER.replace(
            "if item.arg == keyword:", 'if item.arg == keyword or item.arg == "min_coverage":'
        ).replace("def _extract(", "def _fallback_keyword("),
        # Refusing body spellings conservatively is explicitly within #540's scope: a
        # static extractor need not prove that a branch is reachable before refusing it.
        _PARAMETER_HELPER.replace(
            "    return None\n",
            '    if False:\n        return "target_accuracy"\n    return None\n',
        ).replace("def _extract(", "def _fallback_keyword("),
    ],
    ids=["fallback", "same-spelling-in-body", "dead-objective-string"],
)
def test_helper_body_objective_text_cannot_donate_extraction_credit(tmp_path, guard, helper):
    folder = _pool_fixture(
        tmp_path,
        helper,
        'value = _fallback_keyword(source, "min_coverage")\nassert value is not None',
    )
    assert guard._pinned_objective_spellings(folder) == set()


def test_default_argument_objective_spelling_refuses_credit(tmp_path, guard):
    """A fallback spelling in a parameter default is a literal the helper owns (#540)."""
    helper = _PARAMETER_HELPER.replace(
        "def _extract(source, keyword):",
        'def _extract(source, keyword, fallback="target_accuracy"):',
    ).replace("if item.arg == keyword:", "if item.arg in (keyword, fallback):")
    folder = _pool_fixture(
        tmp_path, helper, 'value = _extract(source, "min_coverage")\nassert value is not None'
    )
    assert guard._pinned_objective_spellings(folder) == set()


def test_any_same_named_definition_with_an_objective_literal_refuses_credit(tmp_path, guard):
    """Every definition of a name is refused if any one holds an objective literal (#540).

    The guard resolves a call by name only, so a same-named method elsewhere in the module
    could be the one that runs; the conservative rule refuses the name.
    """
    shadow = (
        "class _Shadow:"
        + "\n"
        + "    def _extract(self, source, keyword):"
        + "\n"
        + '        return "target_accuracy"'
        + "\n"
    )
    folder = _pool_fixture(
        tmp_path,
        _PARAMETER_HELPER + "\n" + "\n" + shadow,
        'value = _extract(source, "min_coverage")\nassert value is not None',
    )
    assert guard._pinned_objective_spellings(folder) == set()


def test_body_spelling_from_the_other_threshold_function_also_refuses_credit(tmp_path, guard):
    helper = _PARAMETER_HELPER.replace("    return None\n", '    return "f1"\n')
    folder = _pool_fixture(
        tmp_path, helper, 'value = _extract(source, "min_coverage")\nassert value is not None'
    )
    assert guard._pinned_objective_spellings(folder) == set()


def test_longer_identifier_string_is_not_an_objective_token_in_the_body(tmp_path, guard):
    helper = _PARAMETER_HELPER.replace(
        "    return None\n", '    note = "target_accuracy_note"\n    return None\n'
    )
    folder = _pool_fixture(
        tmp_path, helper, 'value = _extract(source, "min_coverage")\nassert value is not None'
    )
    assert guard._pinned_objective_spellings(folder) == {"min_coverage"}


def test_unused_fallback_helper_does_not_poison_a_different_helper(tmp_path, guard):
    folder = _pool_fixture(
        tmp_path,
        _PARAMETER_HELPER + "\n\n" + _FALLBACK_HELPER,
        'value = _extract(source, "min_coverage")\nassert value is not None',
    )
    assert guard._pinned_objective_spellings(folder) == {"min_coverage"}


def test_refused_helper_does_not_remove_credit_from_another_extraction(tmp_path, guard):
    folder = _pool_fixture(
        tmp_path,
        _PARAMETER_HELPER + "\n\n" + _FALLBACK_HELPER,
        """\
        unsafe = _fallback_keyword(source, "min_coverage")
        assert unsafe is not None
        safe = _extract(source, "f1")
        assert safe is not None
        """,
    )
    assert guard._pinned_objective_spellings(folder) == {"f1"}


def test_simple_alias_is_outside_locally_defined_function_extraction_contract(tmp_path, guard):
    folder = _pool_fixture(
        tmp_path,
        _PARAMETER_HELPER + "\n_pull = _extract\n",
        'value = _pull(source, "min_coverage")\nassert value is not None',
    )
    assert guard._pinned_objective_spellings(folder) == set()


def test_an_independent_direct_pin_survives_refused_extraction_credit(tmp_path, guard):
    folder = _pool_fixture(
        tmp_path,
        _FALLBACK_HELPER,
        """\
        value = _fallback_keyword(source, "min_coverage")
        assert value is not None
        assert "target_accuracy" in source
        """,
    )
    assert guard._pinned_objective_spellings(folder) == {"target_accuracy"}


def test_recipe42_fallback_body_cannot_pin_either_objective_after_a_flip(tmp_path, guard):
    """Reproduce #540 on recipe 42, including proof that both fallback assertions hold."""
    folder = tmp_path / "42-outbound-disclosure-screening"
    shutil.copytree(
        REPO / "recipes" / folder.name,
        folder,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    assert guard._pinned_objective_spellings(folder) == {"f1", "min_coverage"}
    assert guard._objective_pin_violations(folder) == []

    tests_path = folder / "tests" / "test_helpers.py"
    original = tests_path.read_text("utf-8")
    tree = ast.parse(original)
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_notebook_pins_the_confidence_gate_keyword_and_value"
    )
    replacement = """\
def test_notebook_pins_the_confidence_gate_keyword_and_value():
    source = _notebook_cell_source("python-rule")
    by_coverage = _fallback_keyword(source, "min_coverage")
    assert by_coverage is not None
    by_accuracy = _fallback_keyword(source, "target_accuracy")
    assert by_accuracy is not None
"""
    lines = original.splitlines(keepends=True)
    mutated = (
        "".join(lines[: target.lineno - 1])
        + replacement
        + "".join(lines[target.end_lineno :])
        + "\n\n"
        + _FALLBACK_HELPER
    )
    ast.parse(mutated)
    tests_path.write_text(mutated, encoding="utf-8")

    notebook_path = folder / "notebook.ipynb"
    notebook = json.loads(notebook_path.read_text("utf-8"))
    hits = 0
    rule_source = None
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        source = cell["source"]
        source = "".join(source) if isinstance(source, list) else source
        hits += source.count("min_coverage=0.75")
        source = source.replace("min_coverage=0.75", "target_accuracy=1.0")
        cell["source"] = source.splitlines(keepends=True)
        if cell.get("id") == "python-rule":
            rule_source = source
    assert hits == 1, "the objective flip must change exactly one real selection call"
    assert rule_source is not None
    notebook_path.write_text(json.dumps(notebook), encoding="utf-8")

    # Execute only our synthetic helper. The cookbook backend and the recipe's test module
    # are never imported, and no notebook code is executed by this semantic precondition.
    namespace = {"ast": ast}
    exec(compile(_FALLBACK_HELPER, "<synthetic fallback helper>", "exec"), namespace)
    assert namespace["_fallback_keyword"](rule_source, "min_coverage") == 1.0
    assert namespace["_fallback_keyword"](rule_source, "target_accuracy") == 1.0

    assert (
        "cell python-rule",
        "select_confidence_threshold",
        "target_accuracy",
    ) in guard._threshold_pin_obligations(folder)
    assert guard._pinned_objective_spellings(folder) == {"f1"}
    violations = guard._objective_pin_violations(folder)
    assert violations is not None and len(violations) == 1
    assert violations[0].startswith(
        "cell python-rule select_confidence_threshold(...): objective 'target_accuracy' "
    )
