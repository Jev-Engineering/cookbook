"""Shared ``ast``-based detection for the "What was and was not measured" disclosure cell's
offline/live branches (issue #215), used by both ``tests/test_template.py`` (the template's own
pin) and ``tests/test_recipe_guard.py`` (the per-recipe guard), so the one piece of logic that
decides "which branch is the one that discloses the run mode, and does it really print N" is
written -- and proved against PR #219 reviewer B's evasions -- once, not twice.

Anchors on the branch that actually *contains* the disclosure sentence, rather than splitting
the cell's source on the first ``"else:"`` (which assumes that branch always comes first -- an
assumption an inserted ``elif`` or an inverted ``if not offline: ... else:`` breaks while the
rule stays broken), and requires an actual ``print(...)`` call whose string argument starts with
``"N:"`` (not merely text that *reads* ``N:`` somewhere, such as a comment)."""

from __future__ import annotations

import ast


def if_elif_else_branches(node: ast.If) -> list[list[ast.stmt]]:
    """``[if-body, elif-body, ..., else-body]`` for one ``if``/``elif``.../``else`` chain (the
    final list is empty when there is no ``else:``). An ``elif`` is represented in the AST as a
    single-statement ``orelse`` holding another ``If``, so this walks that chain instead of
    stopping at the first ``orelse`` -- which is exactly what lets it anchor on the right branch
    when an ``elif`` has been inserted between ``if`` and ``else``."""
    branches = [node.body]
    orelse = node.orelse
    while len(orelse) == 1 and isinstance(orelse[0], ast.If):
        branches.append(orelse[0].body)
        orelse = orelse[0].orelse
    branches.append(orelse)
    return branches


def branch_text(branch: list[ast.stmt]) -> str:
    return "\n".join(ast.unparse(stmt) for stmt in branch)


def branch_prints_n(branch: list[ast.stmt]) -> bool:
    """True if ``branch`` contains a ``print(...)`` call whose first argument is a string (an
    f-string or a plain literal) that *starts with* ``"N:"`` -- an actually printed line, not
    merely text that reads ``N:`` somewhere, such as a comment (``# N: deliberately not printed
    offline``) that a plain substring search over the branch's text cannot tell apart from a
    real print."""
    for stmt in branch:
        for node in ast.walk(stmt):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
                and node.args
            ):
                continue
            first = node.args[0]
            if isinstance(first, ast.JoinedStr) and first.values:
                head = first.values[0]
                text = head.value if isinstance(head, ast.Constant) else None
            elif isinstance(first, ast.Constant):
                text = first.value
            else:
                text = None
            if isinstance(text, str) and text.startswith("N:"):
                return True
    return False


def disclosure_branches(source: str, signature: str) -> list[list[ast.stmt]]:
    """Every ``if``/``elif``/``else`` branch, anywhere in ``source`` -- not only at the top level
    -- whose own statements carry ``signature`` (the disclosure sentence) -- found by parsing
    with ``ast`` and anchoring on the branch that actually holds it, rather than by a string
    split on the first ``else:``. The split assumed the disclosure's branch always comes first;
    it does not survive an inserted ``elif`` (the disclosure stays in the ``if`` while ``N``
    moves to the ``elif``) or an inverted ``if not offline: ... else:`` (the disclosure moves to
    the ``else``) -- both pass a split-based check while the rule is broken. Anchoring on content
    rather than position catches both: the branch returned here is whichever one the disclosure
    is actually in, wherever that is.

    Walking with ``ast.walk`` rather than scanning only ``tree.body`` also matters for nesting:
    an ``if``/``else`` one level deeper (the whole disclosure cell wrapped in, say,
    ``if backend is not None:``) would otherwise be invisible to a top-level-only scan, which
    finds only the *outer* ``if`` and treats its entire body -- offline branch, live branch, and
    the live branch's own ``N:`` print, all three -- as one undifferentiated "branch" containing
    the disclosure. That collapses the branch distinction the whole check exists to make: the
    live branch's ``N:`` print then satisfies ``branch_prints_n`` even when the offline branch,
    considered on its own, prints no ``N`` at all. Walking the whole tree finds the *inner*
    ``if``/``else`` too, so its own offline and live branches are checked independently, at any
    nesting depth."""
    tree = ast.parse(source)
    return [
        branch
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        for branch in if_elif_else_branches(node)
        if signature in branch_text(branch)
    ]
