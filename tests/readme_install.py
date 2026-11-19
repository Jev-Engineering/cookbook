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

- A fenced code block is read with the reproduction prose that introduces it, so an install line
  in a fence below "To reproduce the committed outputs:" counts as part of that paragraph. The
  introduction is the nearest prose block above the fence that ends with a colon, and the fence
  is joined to it only when that block's last sentence (the one ending with the colon) is itself
  about reproducing. "Reproducing ... needs ``.[ml]`` .... To run the tests:" introduces the
  tests, so its fence stays a paragraph of its own. The reach back is bounded: at most
  ``INTRODUCTION_REACH`` prose blocks (numbered steps, say) may stand between the introduction and
  the fence, and a heading or another fence in between ends the search. A fence that is not
  joined is checked on its own text. Blank lines inside a fence do not split it.
- Fences follow CommonMark: an opening fence is three or more backticks or tildes indented at
  most three spaces (relative to the list item it sits in, if any), and a backtick fence's info
  string has no backtick, so inline ```code``` at the start of a line and backticks inside an
  indented code block open nothing. The closing fence uses the opening character, at least as
  many of it, and nothing else on the line. An unclosed fence runs to the end of the file.
- A back-reference to the tests' install written earlier in the README, ``.[dev,ml]`` followed by
  "above is for" (the template's "``.[dev]`` above is for ``ruff`` and ``pytest``", once a
  scikit-learn recipe updates it), names that install and does not perform it, so it is not
  refused. Every other occurrence in a reproduction paragraph still is.

This is a plain module (not a test file), loaded by path like the other helpers in tests/.
"""

from __future__ import annotations

import re

COMBINED = ".[dev,ml]"
REPRODUCTION = re.compile(
    r"constraints-notebooks|reproduc|regenerat|byte[ -]for[ -]byte|byte-identical", re.IGNORECASE
)
# ``.[dev,ml]`` anywhere except as a back-reference: the string, then optional closing quotes or
# backticks, then the template's "above is for".
COMBINED_NOT_BACK_REFERENCE = re.compile(
    re.escape(COMBINED) + r"(?![\"'`]*\s+above\s+is\s+for\b)", re.IGNORECASE
)
# An opening fence, after its indentation: 3+ backticks with no backtick after them, or 3+ tildes.
FENCE_OPEN = re.compile(r"(`{3,}(?!.*`)|~{3,})")
LIST_ITEM = re.compile(r"^ *(?:[-*+]|\d{1,9}[.)]) +")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
# How many prose blocks may stand between reproduction prose and the fence it introduces.
INTRODUCTION_REACH = 3

# The install the Notebook job runs, and the line a README documents for reproducing outputs.
REPRODUCTION_INSTALL = 'pip install -e ".[ml]" -c .github/constraints-notebooks.txt'
# What a README says for running the recipe's own tests (the "Run it offline" paragraph).
TEST_INSTALL = 'pip install -e ".[dev]"'


def _blocks(readme: str) -> list[tuple[bool, list[str]]]:
    """``(is_fence, lines)`` for each blank-line separated block, a fenced code block being one
    block however many blank lines it holds (see the module docstring for what opens and closes
    one)."""
    blocks: list[tuple[bool, list[str]]] = []
    current: list[str] = []
    fence: tuple[str, int, int] | None = None  # character, length, deepest closing indent
    list_indent: int | None = None  # content column of the list item the text is in, if any
    for raw in readme.splitlines():
        line = raw.expandtabs(4)
        text = line.lstrip(" ")
        indent = len(line) - len(text)
        if fence is not None:
            current.append(line)
            char, length, deepest = fence
            marker = text.rstrip()
            if indent <= deepest and len(marker) >= length and marker == char * len(marker):
                blocks.append((True, current))
                current, fence = [], None
            continue
        if not text.strip():
            if current:
                blocks.append((False, current))
                current = []
            continue
        container = list_indent if list_indent is not None and indent >= list_indent else 0
        opening = FENCE_OPEN.match(text)
        if opening and indent - container <= 3:
            if current:
                blocks.append((False, current))
            current = [line]
            fence = (opening.group(1)[0], len(opening.group(1)), container + 3)
            continue
        item = LIST_ITEM.match(line)
        if item:
            list_indent = item.end()
        elif not current and indent == 0:
            list_indent = None
        current.append(line)
    if current:  # an unclosed fence runs to the end of the file
        blocks.append((fence is not None, current))
    return blocks


def _collapse(lines: list[str]) -> str:
    return " ".join(" ".join(lines).split())


def _introduction(blocks: list[tuple[bool, list[str]]], fence: int) -> int | None:
    """The index of the reproduction prose that introduces the fence at ``fence``, or None."""
    for i in range(fence - 1, max(fence - 2 - INTRODUCTION_REACH, -1), -1):
        is_fence, lines = blocks[i]
        if is_fence:
            return None
        text = _collapse(lines)
        if text.endswith(":"):
            last_sentence = re.split(r"(?<=[.!?])\s+", text)[-1]
            return i if REPRODUCTION.search(last_sentence) else None
        if any(HEADING.match(line) for line in lines):
            return None
    return None


def paragraphs(readme: str) -> list[str]:
    """The README's blank-line separated blocks, each with its whitespace collapsed (a wrapped
    install line is still one line of text to the rule). A fenced code block is one block however
    many blank lines it holds, and is joined to the reproduction prose that introduces it, if
    any; otherwise it is a paragraph of its own."""
    blocks = _blocks(readme)
    texts: list[list[str]] = [list(lines) for _, lines in blocks]
    for i, (is_fence, lines) in enumerate(blocks):
        introduction = _introduction(blocks, i) if is_fence else None
        if introduction is not None:
            texts[introduction].extend(lines)
            texts[i] = []
    return [_collapse(lines) for lines in texts if "".join(lines).strip()]


def combined_reproduction_installs(readme: str) -> list[str]:
    """Every paragraph that is about reproducing committed outputs and also says ``.[dev,ml]``
    other than as a back-reference ("``.[dev,ml]`` above is for"). An empty list is a pass."""
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
