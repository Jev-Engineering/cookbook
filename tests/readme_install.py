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
committed outputs (it names the constraints file, or says "reproduc...", "byte for byte",
"byte-for-byte" or "byte-identical", or its prose says "regenerat..." the committed or notebook
outputs or the notebook) must not contain ``.[dev,ml]``. Anywhere else the string is allowed.
"regenerat..." is that narrow because READMEs say the catalog and the fixtures are regenerated, and
a ``# regenerate`` comment in a fence is not prose about the paragraph. Refinements (#358):

- Paragraphs are split by blank lines as before, so prose and a fence that touch with no blank
  line between them, above or below it, are one paragraph. A fence that opens after a blank line
  is also read with the reproduction prose that introduces it, so an install line in a fence below
  "To reproduce the committed outputs:" counts as part of that paragraph. The introduction is the
  nearest prose block above the fence that ends with a colon, and the fence is joined to it only
  when that block's last sentence (the one ending with the colon) is itself about reproducing.
  "Reproducing ... needs ``.[ml]`` .... To run the tests:" introduces the tests, so its fence
  stays a paragraph of its own. The reach back is bounded: at most ``INTRODUCTION_REACH`` prose
  blocks (numbered steps, say) may stand between the introduction and the fence, and a heading
  (``#`` or underlined with ``=``/``-``) or another fence in between ends the search. A fence that
  is not joined is checked with the prose it touches. Blank lines inside a fence do not split it.
- Fences follow CommonMark: an opening fence is three or more backticks or tildes indented at
  most three spaces (relative to the list item it sits in, if any), and a backtick fence's info
  string has no backtick, so inline ```code``` at the start of a line and backticks inside an
  indented code block open nothing. The closing fence uses the opening character, at least as
  many of it, and nothing else on the line. An unclosed fence runs to the end of the file.
- A back-reference to the tests' install written earlier in the README, the inline code span
  `` `.[dev,ml]` `` followed by "above is for" (the template's "``.[dev]`` above is for ``ruff``
  and ``pytest``", once a scikit-learn recipe updates it), names that install and does not
  perform it, so it is not refused. ``.[dev,ml]`` inside a longer span such as
  ``pip install -e ".[dev,ml]"`` is an install whatever follows it, and every other occurrence in
  a reproduction paragraph is refused too.

This is a plain module (not a test file), loaded by path like the other helpers in tests/.
"""

from __future__ import annotations

import re

COMBINED = ".[dev,ml]"
REPRODUCTION = re.compile(
    r"constraints-notebooks|reproduc|byte[ -]for[ -]byte|byte-identical", re.IGNORECASE
)
# "regenerat..." counts only in prose and only about the committed outputs or the notebook, so the
# catalog's or the fixtures' regeneration, or a ``# regenerate`` comment in a fence, does not.
REGENERATION = re.compile(
    r"regenerat\w*\s+(?:the\s+)?(?:committed\s+)?(?:notebook\s+)?outputs?\b"
    r"|regenerat\w*\s+(?:the\s+)?notebook\b",
    re.IGNORECASE,
)
# ``.[dev,ml]`` anywhere except the back-reference: the inline code span `` `.[dev,ml]` `` and
# nothing else, followed by the template's "above is for". ``.[dev,ml]`` inside a longer span
# (``pip install -e ".[dev,ml]"``) is an install, whatever follows it.
COMBINED_NOT_BACK_REFERENCE = re.compile(
    rf"(?<!`){re.escape(COMBINED)}|{re.escape(COMBINED)}(?!`+\s+above\s+is\s+for\b)",
    re.IGNORECASE,
)
# An opening fence, after its indentation: 3+ backticks with no backtick after them, or 3+ tildes.
FENCE_OPEN = re.compile(r"(`{3,}(?!.*`)|~{3,})")
LIST_ITEM = re.compile(r"^ *(?:[-*+]|\d{1,9}[.)]) +")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
# The underline of a setext heading (the line under its text): only ``=`` or only ``-``.
SETEXT_UNDERLINE = re.compile(r"^ {0,3}(?:=+|-+)\s*$")
# How many prose blocks may stand between reproduction prose and the fence it introduces.
INTRODUCTION_REACH = 3

# The install the Notebook job runs, and the line a README documents for reproducing outputs.
REPRODUCTION_INSTALL = 'pip install -e ".[ml]" -c .github/constraints-notebooks.txt'
# What a README says for running the recipe's own tests (the "Run it offline" paragraph).
TEST_INSTALL = 'pip install -e ".[dev]"'

Block = list[tuple[bool, str]]  # (the line is in a fence, the line)


def _blocks(readme: str) -> list[Block]:
    """The README's blank-line separated blocks, as before #358, except that a fenced code block
    never splits however many blank lines it holds (see the module docstring for what opens and
    closes one). Prose touching a fence with no blank line is in the fence's block."""
    blocks: list[Block] = []
    current: Block = []
    fence: tuple[str, int, int] | None = None  # character, length, deepest closing indent
    list_indent: int | None = None  # content column of the list item the text is in, if any
    for raw in readme.splitlines():
        line = raw.expandtabs(4)
        text = line.lstrip(" ")
        indent = len(line) - len(text)
        if fence is not None:
            current.append((True, line))
            char, length, deepest = fence
            marker = text.rstrip()
            if indent <= deepest and len(marker) >= length and marker == char * len(marker):
                fence = None
            continue
        if not text.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        container = list_indent if list_indent is not None and indent >= list_indent else 0
        opening = FENCE_OPEN.match(text)
        if opening and indent - container <= 3:
            current.append((True, line))
            fence = (opening.group(1)[0], len(opening.group(1)), container + 3)
            continue
        item = LIST_ITEM.match(line)
        if item:
            list_indent = item.end()
        elif not current and indent == 0:
            list_indent = None
        current.append((False, line))
    if current:  # an unclosed fence runs to the end of the file
        blocks.append(current)
    return blocks


def _collapse(lines: list[str]) -> str:
    return " ".join(" ".join(lines).split())


def _is_heading(block: Block) -> bool:
    lines = [line for _, line in block]
    return any(HEADING.match(line) for line in lines) or any(
        SETEXT_UNDERLINE.match(line) for line in lines[1:]
    )


def _introduction(blocks: list[Block], fence: int) -> int | None:
    """The index of the reproduction prose that introduces the block at ``fence`` (one that opens
    with a fence, a blank line above it), or None."""
    for i in range(fence - 1, max(fence - 2 - INTRODUCTION_REACH, -1), -1):
        if any(in_fence for in_fence, _ in blocks[i]):
            return None
        text = _collapse([line for _, line in blocks[i]])
        if text.endswith(":"):
            last_sentence = re.split(r"(?<=[.!?])\s+", text)[-1]
            return i if REPRODUCTION.search(last_sentence) else None
        if _is_heading(blocks[i]):
            return None
    return None


def _paragraphs(readme: str) -> list[Block]:
    blocks = _blocks(readme)
    joined: list[Block] = [list(block) for block in blocks]
    for i, block in enumerate(blocks):
        introduction = _introduction(blocks, i) if block[0][0] else None
        if introduction is not None:
            joined[introduction].extend(block)
            joined[i] = []
    return [block for block in joined if block]


def paragraphs(readme: str) -> list[str]:
    """The README's blank-line separated blocks, each with its whitespace collapsed (a wrapped
    install line is still one line of text to the rule). A fenced code block is one block however
    many blank lines it holds. A block that opens with a fence is joined to the reproduction prose
    that introduces it across blank lines, if any; otherwise it is a paragraph of its own."""
    return [_collapse([line for _, line in block]) for block in _paragraphs(readme)]


def combined_reproduction_installs(readme: str) -> list[str]:
    """Every paragraph that is about reproducing committed outputs and also says ``.[dev,ml]``
    other than as a back-reference ("`` `.[dev,ml]` above is for``"). An empty list is a pass."""
    found = []
    for block in _paragraphs(readme):
        text = _collapse([line for _, line in block])
        prose = _collapse([line for in_fence, line in block if not in_fence])
        about_reproducing = REPRODUCTION.search(text) or REGENERATION.search(prose)
        if about_reproducing and COMBINED_NOT_BACK_REFERENCE.search(text):
            found.append(text)
    return found


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
