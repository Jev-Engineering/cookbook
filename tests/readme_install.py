"""Check the install used to reproduce committed notebook outputs in recipe READMEs.

The Notebook job installs ``.[ml]`` under its constraints. Tests may install both ``dev``
and ``ml``. Recognize reproduction instructions in prose/headings and associate subsequent
code blocks with that instruction, using the shared CommonMark context reader. A local
instruction to run tests overrides a reproduction heading for its following block.

Intent is deliberately bounded: explicit reproduce wording, regenerate followed by
committed notebook outputs, purpose phrases about byte/bit equality of outputs, and the
notebook constraints path. Bare equality assertions about tests, fixture regeneration and
catalog output regeneration do not establish notebook-reproduction intent. Arbitrary shell
aliases, variables, dynamic extras and indirect natural-language references remain review
obligations. Only direct ``pip install [-e|--editable] .[extras]`` commands are recognized.
No semantic intent is inferred from comments in a code block or raw HTML. Shell wrappers,
aliases and later commands on a compound shell line remain review obligations.

The compatibility helpers below are shared with recipe guard and scaffolder tests.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
import sys
from pathlib import Path

COMBINED = ".[dev,ml]"
# Public spelling retained for callers; intent is evaluated by _intent below.
REPRODUCTION = re.compile(r"constraints-notebooks|reproduc", re.IGNORECASE)
REPRODUCTION_INSTALL = 'pip install -e ".[ml]" -c .github/constraints-notebooks.txt'
TEST_INSTALL = 'pip install -e ".[dev]"'

_scope_spec = importlib.util.spec_from_file_location(
    "scope_context_for_readme_install",
    Path(__file__).resolve().parents[1] / "tools" / "check_recipe_scope.py",
)
_scope = importlib.util.module_from_spec(_scope_spec)
sys.modules[_scope_spec.name] = _scope
_scope_spec.loader.exec_module(_scope)

# Collapse line wrapping before command matching. Requiring an actual install command
# avoids treating a quoted back-reference to an extra as an instruction to install it.
_INSTALL = re.compile(
    r"\b(?:python(?:3(?:\.\d+)?)?\s+-m\s+)?pip(?:3)?\s+install\s+"
    r"(?:(?:-e|--editable)\s+)?(?P<quote>['\"]?)\.\[(?P<extras>[^\]\n]+)\](?P=quote)",
    re.IGNORECASE,
)
_INSTALL_START = re.compile(
    r"^\s*(?:python(?:3(?:\.\d+)?)?\s+-m\s+)?pip(?:3)?\s+install\b",
    re.IGNORECASE,
)
_TRAILING_CONSTRAINT = re.compile(
    r"\s+(?:-c|--constraint)(?:\s+|=)(?:\"[^\"]*\"|'[^']*'|[^\s;`]+)",
    re.IGNORECASE,
)
_EQUAL = r"(?:byte|bit)[\s\-\u2010-\u2015]+(?:for[\s\-\u2010-\u2015]+(?:byte|bit)|identical)"
_REPRODUCE = re.compile(r"\breproduc\w*\b", re.IGNORECASE)
_REGENERATE = re.compile(
    r"\bregenerat\w*\s+(?:the\s+)?(?:committed\s+(?:notebook\s+)?outputs?\b|"
    r"notebook(?:['’]s)?\s+outputs?\b)",
    re.IGNORECASE,
)
_EQUAL_PURPOSE = re.compile(
    rf"\b(?:for|to\s+(?:get|produce|obtain))\s+{_EQUAL}\s+(?:notebook\s+)?outputs?\b",
    re.IGNORECASE,
)
_TESTS = re.compile(
    r"\b(?:(?:to|for)\s+(?:run(?:ning)?\s+)?(?:the\s+)?tests?|run\s+(?:the\s+)?tests?)\b",
    re.IGNORECASE,
)
_FIXTURE_OR_CATALOG = re.compile(r"\bfixtures?\b|tools/render_catalog\b", re.IGNORECASE)


def paragraphs(readme: str) -> list[str]:
    """Legacy blank-line blocks for callers that need display text, not Markdown context."""
    return [" ".join(block.split()) for block in re.split(r"\n\s*\n", readme) if block.strip()]


def _intent(prose: str, previous: str | None) -> str | None:
    """The latest explicit instruction wins, without splitting abbreviations/sentences.

    Code spans and HTML comments cannot supply prose intent. Command detection uses the
    original content separately. Equality wording alone can describe what tests assert.
    """
    # Keep this exact program target as a non-intent exclusion even when it is code.
    prose = re.sub(r"`+tools/render_catalog\.py`+", "tools/render_catalog.py", prose)
    prose = re.sub(
        r"`+((?:\.github/)?constraints-notebooks\.txt)`+",
        r"\1",
        prose,
        flags=re.IGNORECASE,
    )
    prose = _scope.without_inline_code(_prose_source(prose))
    prose = " ".join(prose.replace("*", "").replace("__", "").split())
    candidates = [(m.start(), "tests") for m in _TESTS.finditer(prose)]
    candidates.extend(
        (m.start(), "reproduction")
        for m in re.finditer(r"\bconstraints-notebooks\.txt\b", prose, re.IGNORECASE)
    )
    for match in _REPRODUCE.finditer(prose):
        before = prose[: match.start()].rstrip()
        if (
            not before
            or before[-1] in ".!?:;"
            or re.search(r"\b(?:to|for|when)\s*$", before, re.IGNORECASE)
        ):
            candidates.append((match.start(), "reproduction"))
    for pattern in (_REGENERATE, _EQUAL_PURPOSE):
        for match in pattern.finditer(prose):
            # The narrow generation wording must describe notebook results, not fixtures
            # or another program's output. Stop the inspected clause at sentence punctuation.
            tail = re.split(r"[.;]", prose[match.start() :], maxsplit=1)[0]
            if not _FIXTURE_OR_CATALOG.search(tail):
                candidates.append((match.start(), "reproduction"))
    return max(candidates)[1] if candidates else previous


def _direct_combined_install(command: str) -> bool | None:
    """Whether one direct shell command installs both extras; None means no such install.

    Keep shlex tokens intact: an echo/printf argument containing a command is never a
    command. Shell wrappers, aliases and later commands on a compound line are explicit
    review obligations. Backslash continuations are joined by the caller.
    """
    # Inline Markdown code is not necessarily shell source (e.g. O'Reilly). Parse
    # only a direct install candidate; malformed quoting on that candidate still raises.
    if not _INSTALL_START.match(command):
        return None
    tokens = shlex.split(command, comments=True)
    if not tokens:
        return None
    if re.fullmatch(r"pip3?", tokens[0], re.IGNORECASE):
        start = 1
    elif (
        len(tokens) >= 3
        and re.fullmatch(r"python(?:3(?:\.\d+)?)?", tokens[0], re.IGNORECASE)
        and tokens[1] == "-m"
        and re.fullmatch(r"pip3?", tokens[2], re.IGNORECASE)
    ):
        start = 3
    else:
        return None
    if len(tokens) <= start or tokens[start].casefold() != "install":
        return None
    start += 1
    if len(tokens) > start and tokens[start] in {"-e", "--editable"}:
        start += 1
    if len(tokens) <= start:
        return None
    target = re.fullmatch(r"\.\[([^\]]+)\]", tokens[start])
    if target is None or not {"dev", "ml"} <= {
        part.strip().casefold() for part in target[1].split(",")
    }:
        return None
    return any("constraints-notebooks" in token.casefold() for token in tokens[start + 1 :])


def _prose_source(content: str) -> str:
    """Mask comments and HTML tags, including quoted attributes, preserving source offsets."""
    content = re.sub(r"<!--.*?(?:-->|\Z)", lambda m: " " * len(m[0]), content, flags=re.DOTALL)
    return re.sub(
        r"<(?:\"[^\"]*\"|'[^']*'|[^'\">])*>",
        lambda m: " " * len(m[0]),
        content,
    )


def _bad_installs(content: str, mode: str | None, *, prose: bool) -> bool:
    """A block is bad if a direct command installs both extras for notebook reproduction."""
    if not prose:
        # HTML delimiters have no Markdown meaning inside code. Only shell comments
        # apply, so '# <!--' cannot hide a real install on the next line.
        logical = re.sub(r"\\(?:\r\n|\r|\n)", " ", content)
        for line in re.split(r"\r\n|\r|\n", logical):
            if not _INSTALL_START.match(line):
                continue
            constraints = _direct_combined_install(line)
            if constraints is not None and (mode == "reproduction" or constraints):
                return True
        return False

    content = _prose_source(content)
    candidates = []
    outside_code = list(content)
    for span in _scope.INLINE_CODE.finditer(content):
        ticks = len(span["ticks"])
        candidates.append((span.start(), span.end(), span[0][ticks:-ticks]))
        outside_code[span.start() : span.end()] = " " * (span.end() - span.start())
    # Preserve the historical direct, unformatted pip form too; formatted spans were
    # removed first so a quoted echo argument inside a code span cannot reappear here.
    bare = "".join(outside_code)
    for command in _INSTALL.finditer(bare):
        end = command.end()
        # Preserve the notebook-stack constraint argument after the target. A period
        # inside its path is not the start of another prose sentence. Keep this bounded
        # to explicit -c/--constraint arguments rather than shell-parsing trailing prose.
        while trailing := _TRAILING_CONSTRAINT.match(bare, end):
            end = trailing.end()
        candidates.append((command.start(), end, bare[command.start() : end]))
    for start, end, command in candidates:
        constraints = _direct_combined_install(" ".join(command.split()))
        if constraints is None:
            continue
        intent = _intent(content[:start], mode)
        following = content[end:]
        purpose = re.split(r"[.!?;]", following, maxsplit=1)[0]
        intent = _intent(purpose, intent)
        # Inline command constraints after the project target, as well as the
        # surrounding prose's constraints path, both retain their parent behavior.
        if intent == "reproduction" or constraints:
            return True
    return False


def combined_reproduction_installs(readme: str) -> list[str]:
    """Diagnostic blocks installing dev+ml to reproduce committed notebook outputs.

    CommonMark supplies heading/paragraph/list/quote/code-block boundaries, including
    unclosed fences. Raw HTML is ignored. Local instruction state is saved/restored at
    list-item and quote boundaries; an unrelated heading resets it. Code-block comments
    never change the state. The shared reader retains CommonMark's nesting bound; content
    beyond that bound is a documented manual-review limit for this README heuristic.
    """
    refused = []
    mode = None
    stack = []
    block = None
    for token in _scope.commonmark_blocks(readme):
        if token.type in {"list_item_open", "blockquote_open"}:
            stack.append(mode)
        elif token.type in {"list_item_close", "blockquote_close"}:
            mode = stack.pop()
        elif token.type == "heading_open":
            block = "heading"
        elif token.type == "paragraph_open":
            block = "paragraph"
        elif token.type in {"heading_close", "paragraph_close"}:
            block = None
        elif token.type == "inline":
            if _bad_installs(token.content, mode, prose=True):
                refused.append(" ".join(token.content.split()))
            mode = _intent(token.content, None if block == "heading" else mode)
        elif token.type in {"fence", "code_block"}:
            if _bad_installs(token.content, mode, prose=False):
                refused.append(" ".join(token.content.split()))
    return refused


def with_documented_test_install(readme: str) -> str:
    """Replace the bare-dev tests install with the documented scikit-learn tests install.

    The scaffold after #466 already has that install. Accept it without weakening the
    assertion that a real tests-install command exists; do not rewrite reproduction.
    """
    if TEST_INSTALL in readme:
        return readme.replace(TEST_INSTALL, f'pip install -e "{COMBINED}"', 1)
    assert f'pip install -e "{COMBINED}"' in readme, "no test-install line to replace"
    return readme


def with_pre_162_reproduction_install(readme: str) -> str:
    """Replace the documented notebook install with the historically wrong combined one."""
    assert REPRODUCTION_INSTALL in readme, "no reproduction install line to replace"
    return readme.replace(
        REPRODUCTION_INSTALL, 'pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt', 1
    )
