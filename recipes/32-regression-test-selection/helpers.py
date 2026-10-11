"""Python's half of recipe 32: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from typing import Any

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.


def build_state(fields: dict[str, Any]):
    """The state Jev sees for one example. Keep identifiers and other Python-owned values out."""
    raise NotImplementedError("TODO: build the state from the example's fields")


def build_questions():
    """The questions asked about every example. Python builds option lists and criteria."""
    raise NotImplementedError("TODO: return {name: Choice | Noul | Score}")


# TODO: the rule or rules Python enforces whatever the model answers, with tests.
