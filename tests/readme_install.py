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
committed outputs (it names the constraints file, or says "reproduc...", "regenerat...", "byte for
byte", "byte-for-byte" or "byte-identical") must not contain ``.[dev,ml]``. Anywhere else the
string is allowed. Two refinements (#358):

- A fenced code block belongs to the prose paragraph just before it, so an install line in a
  fence below "To reproduce the committed outputs:" is read as part of that paragraph. Blank
  lines inside a fence do not split it.
- A back-reference to the tests' install written earlier in the README, ``.[dev,ml]`` followed by
  "above" (the template's "``.[dev]`` above is for ``ruff`` and ``pytest``", once a scikit-learn
  recipe updates it), names that install and does not perform it, so it is not refused. Every
  other occurrence in a reproduction paragraph still is.

This is a plain module (not a test file), loaded by path like the other helpers in tests/.
"""

from __future__ import annotations

import re

COMBINED = ".[dev,ml]"
REPRODUCTION = re.compile(
    r"constraints-notebooks|reproduc|regenerat|byte[ -]for[ -]byte|byte-identical", re.IGNORECASE
)
# ``.[dev,ml]`` anywhere except as a back-reference: the string, then optional closing quotes or
# backticks, then "above".
COMBINED_NOT_BACK_REFERENCE = re.compile(re.escape(COMBINED) + r"(?![\"'`]*\s+above\b)")
FENCE = re.compile(r"^\s*(```|~~~)")

# The install the Notebook job runs, and the line a README documents for reproducing outputs.
REPRODUCTION_INSTALL = 'pip install -e ".[ml]" -c .github/constraints-notebooks.txt'
# What a README says for running the recipe's own tests (the "Run it offline" paragraph).
TEST_INSTALL = 'pip install -e ".[dev]"'


def paragraphs(readme: str) -> list[str]:
    """The README's blank-line separated blocks, each with its whitespace collapsed (a wrapped
    install line is still one line of text to the rule). A fenced code block is one block however
    many blank lines it holds, and is joined to the prose block just before it."""
    blocks: list[list[str]] = []
    current: list[str] = []
    fence: str | None = None  # the opening marker while inside a fence
    joins_previous = False  # the current block is a fence that belongs to the block before
    for line in readme.splitlines():
        opening = FENCE.match(line)
        if fence is None and opening:
            if current:
                blocks.append(current)
                current = []
            joins_previous = bool(blocks)
            fence = opening.group(1)
            current.append(line)
            continue
        if fence is not None:
            current.append(line)
            if line.strip().startswith(fence) and len(current) > 1:
                (blocks[-1].extend if joins_previous else blocks.append)(current)
                current, fence, joins_previous = [], None, False
            continue
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:  # an unclosed fence runs to the end of the file
        (blocks[-1].extend if fence is not None and joins_previous else blocks.append)(current)
    return [" ".join(" ".join(block).split()) for block in blocks if "".join(block).strip()]


def combined_reproduction_installs(readme: str) -> list[str]:
    """Every paragraph that is about reproducing committed outputs and also says ``.[dev,ml]``
    other than as a back-reference ("``.[dev,ml]`` above"). An empty list is a pass."""
    return [
        p
        for p in paragraphs(readme)
        if REPRODUCTION.search(p) and COMBINED_NOT_BACK_REFERENCE.search(p)
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
