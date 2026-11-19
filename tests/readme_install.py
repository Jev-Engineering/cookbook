"""The rule about ``.[dev,ml]`` in a recipe README, shared by ``tests/test_recipe_guard.py`` (every
published README and the template) and ``tests/test_new_recipe.py`` (the scaffold's output).

What the rule is for (#127, #137, #162, docs/recipe-template.md step 6). The ``Notebook (<recipe>)``
job installs ``.[ml]`` under ``.github/constraints-notebooks.txt`` and runs neither ``ruff`` nor
``pytest``, so the install that *reproduces the committed notebook outputs* is ``.[ml]`` alone.
The pre-#162 README paragraph said ``.[dev,ml]`` ... ``-c .github/constraints-notebooks.txt``
there, which is the wording that is wrong. It used to be checked as "the literal ``.[dev,ml]``
appears nowhere in the README", which also forbade the one place it is right: the install for
running a recipe's *tests*. Since #238 both ``Tests`` jobs install ``ml`` and a recipe whose
``helpers.py`` uses scikit-learn needs ``pip install -e ".[dev,ml]"`` to run ``pytest`` at all.

So the rule is now about the paragraph, not the whole file: a paragraph that is about reproducing
committed outputs must not contain ``.[dev,ml]``. Anywhere else the string is allowed. A paragraph
is a blank-line separated block, fenced code included: prose and a fence that touch with no blank
line between them are one paragraph, and a blank line splits a paragraph even inside a fence.

A paragraph is about reproducing committed outputs when its text, fenced code included, names the
constraints file or says "reproduc...", "byte for byte", "byte-for-byte" or "byte-identical"; or
when its prose (fenced code excluded) says it regenerates the committed or notebook outputs or the
notebook: "regenerate the committed outputs", "regenerate the recipe's committed outputs", "The
committed outputs are regenerated with ...", "the notebook is regenerated". "regenerat..." is
that narrow because READMEs say the catalog and the fixtures are regenerated, and a
``# regenerate`` comment in a fence is not prose. What is fenced is decided as
``tools/check_recipe_scope.py``'s ``without_code_fences`` decides it (its ``FENCE``, its open and
close rules, an unclosed fence running to the end of the README), over the whole README, so a
fence a blank line splits stays fenced in the paragraphs after the blank line (#358 item 3b).

A back-reference to the tests' install is not refused (#358 item 3a): an inline code span holding
exactly ``.[dev,ml]`` followed, after optional whitespace, by "above is for" (the template's
"``.[dev]`` above is for ``ruff`` and ``pytest``", once a scikit-learn recipe updates it) names
that install and does not perform it. Code spans are read left to right, so the backtick that
opens the span must open it: the closing backtick of an earlier span does not. ``.[dev,ml]``
inside a longer span such as ``pip install -e ".[dev,ml]"`` is an install whatever follows it, and
every other occurrence in a reproduction paragraph is refused.

This is a plain module (not a test file), loaded by path like the other helpers in tests/.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

COMBINED = ".[dev,ml]"
REPRODUCTION = re.compile(
    r"constraints-notebooks|reproduc|byte[ -]for[ -]byte|byte-identical", re.IGNORECASE
)
# "regenerat..." about the committed or notebook outputs or the notebook, matched in prose only.
# Active: "regenerate [the] [<owner>'s] [committed] [notebook] output(s)" or "... notebook".
# Passive: the same thing as subject, then "is/are/can [only|also|<adverb>ly] [be] regenerated".
# The passive subject must start at "the", an owner's "'s", "committed" or "notebook outputs", so
# "the fixture outputs are regenerated" (a noun in front of "outputs") does not count, and
# "the notebook's fixtures" is not the notebook.
_THING = r"(?:(?:committed\s+)?(?:notebook\s+)?outputs?|notebook)\b(?!')"
_SUBJECT = r"(?:the\s+(?:[\w-]+'s\s+)?|[\w-]+'s\s+|(?=committed\s|notebook\s+outputs?\b))"
_AUXILIARY = r"(?:is|are|was|were|be|been|being|gets?|got|can|could|must|should|will|would|may)"
REGENERATION = re.compile(
    rf"\bregenerat\w*\s+(?:the\s+)?(?:[\w-]+'s\s+)?{_THING}"
    rf"|\b{_SUBJECT}{_THING}\s+{_AUXILIARY}\s+"
    rf"(?:(?:{_AUXILIARY}|only|also|\w+ly)\s+){{0,3}}regenerat",
    re.IGNORECASE,
)
# An inline code span, read left to right: a run of backticks, its content, and the next run of
# exactly as many backticks.
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
ABOVE_IS_FOR = re.compile(r"\s*above\s+is\s+for\b", re.IGNORECASE)

# The scope check's fence pattern, so the two tools agree on what is fenced code (as
# tests/test_docs_links.py does by reusing its without_code_fences).
_spec = importlib.util.spec_from_file_location(
    "check_recipe_scope_readme_install",
    Path(__file__).resolve().parents[1] / "tools" / "check_recipe_scope.py",
)
_scope = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _scope  # its dataclasses resolve their module through sys.modules
_spec.loader.exec_module(_scope)
FENCE = _scope.FENCE

# The install the Notebook job runs, and the line a README documents for reproducing outputs.
REPRODUCTION_INSTALL = 'pip install -e ".[ml]" -c .github/constraints-notebooks.txt'
# What a README says for running the recipe's own tests (the "Run it offline" paragraph).
TEST_INSTALL = 'pip install -e ".[dev]"'


def paragraphs(readme: str) -> list[str]:
    """The README's blank-line separated blocks, each with its whitespace collapsed (a wrapped
    install line is still one line of text to the rule)."""
    return [" ".join(block.split()) for block in re.split(r"\n\s*\n", readme) if block.strip()]


def paragraph_prose(readme: str) -> list[str]:
    """For each of ``paragraphs(readme)``, in the same order, its lines outside fenced code,
    whitespace collapsed. Fence state is carried across paragraphs with the open and close rules
    of ``without_code_fences`` in tools/check_recipe_scope.py (fence lines themselves excluded)."""
    prose = []
    fence = None  # (character, length) while inside a fenced block
    for block in re.split(r"\n\s*\n", readme):
        if not block.strip():
            continue
        kept = []
        for line in block.split("\n"):
            match = FENCE.fullmatch(line)
            if fence is None:
                if match and not (match.group("mark")[0] == "`" and "`" in match.group("info")):
                    fence = (match.group("mark")[0], len(match.group("mark")))
                    continue
                kept.append(line)
            elif match and match.group("mark")[0] == fence[0]:
                if len(match.group("mark")) >= fence[1] and not match.group("info").strip():
                    fence = None
        prose.append(" ".join(" ".join(kept).split()))
    return prose


def _back_references(text: str) -> int:
    """How many times ``text`` says `` `.[dev,ml]` above is for``: a code span holding exactly
    ``.[dev,ml]``, opened by its own backtick, then "above is for"."""
    return sum(
        1
        for span in CODE_SPAN.finditer(text)
        if span.group(2) == COMBINED and ABOVE_IS_FOR.match(text, span.end())
    )


def combined_reproduction_installs(readme: str) -> list[str]:
    """Every paragraph that is about reproducing committed outputs and also says ``.[dev,ml]``
    other than as a back-reference (`` `.[dev,ml]` above is for``). An empty list is a pass."""
    return [
        text
        for text, prose in zip(paragraphs(readme), paragraph_prose(readme), strict=True)
        if (REPRODUCTION.search(text) or REGENERATION.search(prose))
        and text.count(COMBINED) > _back_references(text)
    ]


def with_documented_test_install(readme: str) -> str:
    """``readme`` with the tests' install line changed to the one docs/recipe-template.md step 3
    documents for a recipe whose helpers use scikit-learn. Raises if the README has no such line,
    so a test built on it cannot pass by changing nothing."""
    assert TEST_INSTALL in readme, "no test-install line to replace"
    return readme.replace(TEST_INSTALL, f'pip install -e "{COMBINED}"', 1)


def with_pre_162_reproduction_install(readme: str) -> str:
    """``readme`` with the reproduction install changed to the pre-#162 wording: the thing the
    rule must keep refusing. Raises if the README has no reproduction line to replace."""
    assert REPRODUCTION_INSTALL in readme, "no reproduction install line to replace"
    return readme.replace(
        REPRODUCTION_INSTALL, 'pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt', 1
    )
