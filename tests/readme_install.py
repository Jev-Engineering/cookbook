"""Check the install used to reproduce committed notebook outputs in recipe READMEs.

The Notebook job installs ``.[ml]`` under its constraints. Tests may install both ``dev``
and ``ml``. Recognize reproduction instructions in prose/headings and associate subsequent
code blocks with that instruction, using the shared CommonMark context reader. A local
instruction to run tests overrides a reproduction heading for its following block.

Intent is deliberately bounded: explicit reproduce wording, regenerate followed by
committed notebook outputs, purpose phrases about byte/bit equality of outputs, and the
notebook constraints path. Bare equality assertions about tests, fixture regeneration and
catalog output regeneration do not establish notebook-reproduction intent. Comments in a
code block and raw HTML supply no intent.

Recognized install forms (``_direct_combined_install``): ``pip``/``pip3`` install with any pip
options before the target (an option's argument, such as ``-c FILE``, is skipped), ``-e`` or
``--editable``, extras in any order or spacing; a leading ``$``, ``%``, ``>`` or ``PS>`` prompt;
``sudo`` (with option flags such as ``-H``), ``env``, ``uv`` and ``VAR=value`` prefixes;
``py -m``, ``py -3.14 -m`` and ``python[3.x] -m`` launchers; backslash continuations. A line that
holds a dev+ml target and ``constraints-notebooks`` is refused whatever its syntax (main's rule).

Decided limits, not detected and left to review: shell aliases and variables; dynamic extras
(``.[$EXTRAS]``); an ``echo``/``printf`` argument that does not also name the constraints file;
raw HTML blocks such as ``<pre>``; two separate targets (``".[dev]" ".[ml]"``); ``sudo`` options
that take an argument (``sudo -u USER``); ``python -m uv pip``; earlier or later commands on a
compound line (``cd dir && pip install ...``) unless the line names the constraints file; and
content beyond CommonMark's nesting bound. The one deliberate reader difference is a trust
boundary: the privileged scope CLI keeps its stdlib physical-line fence reader
(``without_code_fences``) and never calls the CommonMark reader used here.

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
# The bare-dev tests install: the legacy spelling that published READMEs may still carry. The
# scaffold and the template README say ``.[dev,ml]`` (COMBINED); both are accepted below.
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
_PROMPT = r"(?:(?:\$|%|>|PS>|PS\s[^>\n]*>)\s+)?"
_WRAP = r"(?:[A-Za-z_]\w*=\S*\s+|sudo(?:\s+-[A-Za-z-]+)*\s+|env\s+|uv\s+)*"
_PY = r"(?:(?:py|python[\d.]*)(?:\s+-[\d.]+)?\s+-m\s+)?"
_INSTALL = re.compile(
    r"\bpip[\d.]*\s+install\s+"
    r"(?:-{1,2}[\w-]+(?:=\S+)?\s+(?:(?:\.github/)?[\w./-]*constraints-notebooks\.txt\s+)?)*"
    r"(?:(?:-e|--editable)\s+)?(?P<quote>['\"]?)\.\[(?P<extras>[^\]\n]+)\](?P=quote)",
    re.IGNORECASE,
)
# A command line that is, or wraps, a pip install: an optional prompt, env assignments, sudo/uv,
# and an optional python -m / py -m in front of pip.
_INSTALL_START = re.compile(
    rf"^\s*{_PROMPT}{_WRAP}{_PY}pip[\d.]*(?:\.exe)?\s+install\b",
    re.IGNORECASE,
)
_PIP_PROGRAM = re.compile(r"pip[\d.]*(?:\.exe)?", re.IGNORECASE)
_PROMPT_PREFIX = re.compile(rf"^\s*{_PROMPT}")
# pip options whose next token is their argument, so it is never mistaken for the target.
_OPTIONS_WITH_ARGUMENT = {
    "-c", "--constraint", "-r", "--requirement", "-i", "--index-url", "--extra-index-url",
    "-f", "--find-links", "-t", "--target", "--prefix", "--root", "--python", "--proxy",
    "--cache-dir", "--trusted-host", "--src", "--platform", "--abi", "--implementation",
    "--python-version", "--upgrade-strategy", "--config-settings", "-C",
}  # fmt: skip
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


def _conservative_combined_install(command: str) -> bool:
    """Main's coverage, kept whatever the shell syntax: a dev+ml target and the notebook
    constraints file on one command line. Shell comments are dropped when the line parses."""
    try:
        text = " ".join(shlex.split(command, comments=True))
    except ValueError:
        text = command
    return "constraints-notebooks" in text.casefold() and any(
        {part.strip().casefold() for part in extras.split(",")} >= {"dev", "ml"}
        for extras in re.findall(r"\.\[([^\]]+)\]", text)
    )


def _direct_combined_install(command: str) -> bool | None:
    """Whether one direct shell command installs both extras; None means no such install.

    The target may follow any pip options (an option's argument is skipped, so ``-c FILE`` can
    come first); a leading prompt, env assignments, sudo, uv and python/py -m are stripped.
    Keep shlex tokens intact: an echo/printf argument containing a command is never a
    command, except that a line naming both a dev+ml target and the notebook constraints
    file is refused whatever its syntax (main's rule). Other shell wrappers, aliases and
    later commands on a compound line are explicit review obligations.
    """
    if _conservative_combined_install(command):
        return True
    # Inline Markdown code is not necessarily shell source (e.g. O'Reilly). Parse
    # only a direct install candidate; malformed quoting on that candidate still raises.
    if not _INSTALL_START.match(command):
        return None
    tokens = shlex.split(command[_PROMPT_PREFIX.match(command).end() :], comments=True)
    program = next(
        (
            index
            for index, token in enumerate(tokens[:-1])
            if _PIP_PROGRAM.fullmatch(token) and tokens[index + 1].casefold() == "install"
        ),
        None,
    )
    if program is None:
        return None
    constraints = False
    combined = False
    skip = False
    for token in tokens[program + 2 :]:
        constraints = constraints or "constraints-notebooks" in token.casefold()
        if skip:
            skip = False
            continue
        if token in _OPTIONS_WITH_ARGUMENT:
            skip = True
            continue
        target = re.fullmatch(r"\.\[([^\]]+)\]", token)
        if target is not None and {"dev", "ml"} <= {
            part.strip().casefold() for part in target[1].split(",")
        }:
            combined = True
    return constraints if combined else None


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
    """Replace a legacy bare-dev tests install with the documented scikit-learn tests install.

    The scaffold after #466 and the template README already say that install; a published
    README may still carry the legacy spelling. Accept either without weakening the
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
