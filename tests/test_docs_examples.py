"""Extracts, lints and executes the fenced Python examples in ``docs/evaluation.md`` (#152,
from the Opus reviews of #146, comments 6071614909 and 6071956764).

Before this file, a documented example could drift from the real ``jev_cookbook`` API with
nothing noticing: ``ruff check`` does not scan Markdown (``ruff format`` does, but only for
fence formatting, not correctness), and nothing executed a documented snippet end to end except
one block in ``docs/backends.md`` (``tests/test_backends.py::test_fixture_recipe_in_the_docs_runs``,
the precedent this file follows). That gap is exactly how the "Noul three-path pattern" example
shipped with a selection-on-test error and a ruff B905 finding (bare ``zip(...)`` with no
``strict=``) that had to be caught by hand.

**Convention.** Every fenced ```python block in the doc is extracted, in document order (index
0, 1, 2, ...). Each is both linted and executed against a small preamble from ``PREAMBLE`` below
that binds whatever names the example assumes are already in scope (an import shown in an
earlier block, a variable named for what a caller would supply, such as ``val_gold``) -- so a
genuine mistake (a typo, a removed ``strict=True``, a renamed function, a dropped or reordered
argument) still fails, while an intentional, documented placeholder does not. This is the
"explicit allowlist" the issue offers as one option for the marker convention: ``PREAMBLE``
names, for every block, exactly what it is assumed to already have in scope. Every block costs
at most a few hundred milliseconds to run (measured below each test, in a `SIGALRM` timeout well
above the worst observed case), so none is skipped for being "not self-contained" -- only block 5
is a genuine fragment (a formula shown mid-explanation, not a program with an observable result),
and it is linted and executed the same as the rest; there is simply nothing further to assert
about it.

**Linting never masks a new finding.** A block that fails `ruff check` with findings outside
``ALLOWED_FINDINGS`` below fails the test, including a *new* finding of the same code the block
already has a pre-existing one for, because matching is by exact ``(block, code, line)``, not by
block or by code alone. Two of the eight blocks have pre-existing findings (next section); every
other block must lint perfectly clean.

**Not included.** ``docs/backends.md``, ``docs/fixtures.md`` and ``docs/live.md`` (the issue's
"if cheap" extension) are left out: ``backends.md``'s one fully self-contained block is already
executed by the precedent above, so repeating it here would check nothing new; ``fixtures.md``'s
five blocks each reference their own example-specific placeholders (``recipe``, ``example_id``,
``candidates``, a real ``backend``) needing a bespoke preamble per block, which is not cheap; and
``live.md``'s three blocks construct a ``LiveBackend`` or a third-party adapter client, which
this suite must never do (CONTRIBUTING.md section 1: no key, no network, and
``jev_cookbook.LiveBackend`` must never be instantiated by a test that runs in CI).

**Known gaps, left for the orchestrator rather than fixed here.** Two of the eight blocks fail
``ruff check`` verbatim, against the repository's real configuration, for reasons this test did
not create and cannot fix within #152's allowed docs edit ("only for the marker convention", not
a content change). Each is named in ``ALLOWED_FINDINGS`` by its exact ``(block, code, line)``, so
a *different* finding in the same block -- including a new finding of the very same code, at a
different line -- is not covered by the allowlist and still fails:

- **Block 0** (the module's opening ``from jev_cookbook.evaluation import accuracy,
  select_threshold, evaluate_threshold``) fails ``I001`` (the three names are not alphabetised)
  and ``F401`` three times over (none of the three is used in that one-line block, since it
  exists only to show the import itself). ``I001`` is a real, fixable finding -- alphabetising
  the import is a one-line docs fix, outside this issue's allowed path. ``F401`` is not fixable
  by any docs edit: the block's entire purpose is to show the import statement in isolation, so
  nothing in it will ever use the names it imports without changing what the block demonstrates.
  It is allowed permanently (``PERMANENT_FINDINGS``), not as a gap awaiting a fix.
- **Block 4** (the ``evaluate_outcomes``/``evaluate_selective`` equivalence snippet, "Note the
  argument order") ends with a bare tuple comparison used to show a reader what is true, and
  fails ``B015`` ("pointless comparison"). A docs fix (wrapping it in ``assert``) would also let
  this file verify the claim it only executes today (see ``test_block_four_equivalence_holds``
  below, which checks the same claim test-side instead, without editing the doc).

If either ``I001`` or ``B015`` is ever fixed, the matching entry in ``ALLOWED_FINDINGS`` stops
matching anything, and ``test_known_findings_still_present`` fails -- the signal to remove it.
"""

import json
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "evaluation.md"
PYPROJECT = REPO / "pyproject.toml"
TEXT = DOC.read_text("utf-8")
BLOCKS = re.findall(r"```python\n(.*?)```", TEXT, re.S)

# The venv's own pinned ruff (pyproject.toml pins an exact version under [dev]), never whatever
# happens to be first on PATH: a stray older/newer ruff on PATH must not silently change what
# this test can catch.
RUFF = [sys.executable, "-m", "ruff"]

# What each block assumes is already in scope: an import shown earlier, or a variable named for
# what a caller would supply (`val_gold`, `ids`, `LABELS`, ...). Both lint and execution use this
# same preamble, so a block's synthetic data is type-correct, not just lint-plausible.
PREAMBLE = {
    0: "",
    1: (
        "from jev_cookbook.evaluation import evaluate_threshold, select_threshold\n\n"
        "val_gold = [True, False, True, False, True]\n"
        "val_noul = [0.9, 0.2, 0.8, 0.3, 0.7]\n"
        "test_gold = [True, False, True, False, True]\n"
        "test_noul = [0.85, 0.15, 0.75, 0.25, 0.65]\n"
    ),
    2: (
        "from jev_cookbook.evaluation import pool_label_decisions, selective_curve\n\n"
        "ids = [1, 2, 3]\n"
        'LABELS = ["a", "b"]\n'
        'gold_by_label = {"a": [True, False, True], "b": [False, False, True]}\n'
        'noul_by_label = {"a": [0.9, 0.2, 0.8], "b": [0.3, 0.1, 0.7]}\n'
        'thresholds = {"a": 0.5, "b": 0.5}\n'
    ),
    3: (
        "from jev_cookbook.evaluation import evaluate_outcomes, pool_label_outcomes\n\n"
        "ids = [1, 2, 3]\n"
        'LABELS = ["a", "b"]\n'
        'gold_by_label = {"a": [True, False, True], "b": [False, False, True]}\n'
        'accepted_by_label = {"a": [True, True, False], "b": [True, True, True]}\n'
        'tag_by_label = {"a": [True, False, False], "b": [False, False, True]}\n'
    ),
    4: (
        "from jev_cookbook.evaluation import evaluate_outcomes, evaluate_selective\n\n"
        "confidence = [0.9, 0.2, 0.8]\n"
        "correct = [True, False, True]\n"
        "threshold = 0.5\n"
    ),
    5: (
        "import numpy as np\n\n"
        "exempt = np.array([True, False, False])\n"
        "confidence = np.array([0.9, 0.2, 0.8])\n"
        "t = 0.5\n"
    ),
    6: (
        "from jev_cookbook.evaluation import outcome_curve\n"
        "from jev_cookbook.style import plot_risk_coverage\n\n"
        "test_confidence = [0.9, 0.2, 0.8, 0.4]\n"
        "test_correct = [True, False, True, False]\n"
        "test_exempt = [False, False, True, False]\n"
    ),
    7: (
        "from jev_cookbook.evaluation import (\n"
        "    evaluate_selective,\n"
        "    noul_confidence,\n"
        "    select_confidence_threshold,\n"
        "    select_threshold,\n"
        ")\n\n"
        "val_gold = [True, False, True, False, True]\n"
        "val_noul = [0.9, 0.2, 0.8, 0.3, 0.7]\n"
        "test_gold = [True, False, True, False, True]\n"
        "test_noul = [0.85, 0.15, 0.75, 0.25, 0.65]\n"
    ),
}

# Permanently allowed findings: not a gap awaiting a docs fix, but a consequence of what the
# block exists to show. {block_index: {code, ...}} -- matched by code alone, any line or count.
PERMANENT_FINDINGS = {0: {"F401"}}

# Pre-existing, fixable findings: {(block_index, code, line): reason}. Matched exactly, so a new
# finding of the same code at a different line is NOT covered and still fails the test.
ALLOWED_FINDINGS = {
    (0, "I001", 1): "the import is not alphabetised; a one-line docs fix, outside #152's scope",
    (4, "B015", 8): "the bare tuple comparison is a pointless-expression finding; see the module"
    " docstring's 'Known gaps'",
}

# Every block executes: each costs well under a second (see the timeout below), so none is
# excluded for being "not self-contained". Block 5 is linted and executed like the rest, even
# though it has no further claim for a test to check.
EXECUTED = set(range(len(BLOCKS)))

assert len(BLOCKS) == 8, (
    f"docs/evaluation.md now has {len(BLOCKS)} fenced python block(s), not 8: update PREAMBLE, "
    "PERMANENT_FINDINGS and ALLOWED_FINDINGS above for the new or removed block before trusting "
    "this test"
)
assert set(PREAMBLE) == set(range(len(BLOCKS)))


def _source(index: int) -> str:
    return PREAMBLE[index] + BLOCKS[index]


def _lint(index: int, tmp_path: Path) -> list[dict]:
    path = tmp_path / f"evaluation_block_{index}.py"
    path.write_text(_source(index), encoding="utf-8")
    proc = subprocess.run(
        [*RUFF, "check", "--config", str(PYPROJECT), "--output-format=json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else []


@pytest.mark.parametrize("index", range(len(BLOCKS)))
def test_block_lints_clean(index, tmp_path):
    diagnostics = _lint(index, tmp_path)
    permanent = PERMANENT_FINDINGS.get(index, set())
    unexpected = [
        d
        for d in diagnostics
        if d["code"] not in permanent
        and (index, d["code"], d["location"]["row"]) not in ALLOWED_FINDINGS
    ]
    assert not unexpected, (
        f"docs/evaluation.md block {index} has unexpected ruff finding(s): "
        + ", ".join(f"{d['code']} at line {d['location']['row']}" for d in unexpected)
    )


def test_known_findings_still_present(tmp_path):
    """Each ``ALLOWED_FINDINGS`` entry names a real, currently-present defect. If a docs fix ever
    removes one, this fails as the signal to delete the now-stale allowlist entry."""
    by_block: dict[int, list[dict]] = {}
    for block_index, _code, _line in ALLOWED_FINDINGS:
        by_block.setdefault(block_index, _lint(block_index, tmp_path))
    missing = [
        f"{code} at line {line} (block {block_index})"
        for (block_index, code, line) in ALLOWED_FINDINGS
        if not any(
            d["code"] == code and d["location"]["row"] == line for d in by_block[block_index]
        )
    ]
    assert not missing, (
        "docs/evaluation.md no longer has these allowlisted findings -- remove them from "
        f"ALLOWED_FINDINGS: {missing}"
    )


_HAS_SIGALRM = hasattr(signal, "SIGALRM")


class _Timeout(Exception):
    pass


def _alarm(_signum, _frame):
    raise _Timeout("docs/evaluation.md example exceeded its timeout")


@pytest.mark.skipif(
    not _HAS_SIGALRM,
    reason="signal.SIGALRM is POSIX-only; docs/development.md also documents Windows local dev",
)
@pytest.mark.parametrize("index", sorted(EXECUTED))
def test_block_executes(index):
    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(10)
    try:
        namespace: dict = {}
        exec(compile(_source(index), f"docs/evaluation.md:block{index}", "exec"), namespace)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        import matplotlib.pyplot as plt

        plt.close("all")  # block 6 calls plot_risk_coverage, which opens a Figure


@pytest.mark.skipif(not _HAS_SIGALRM, reason="see test_block_executes")
def test_block_four_equivalence_holds():
    """Block 4 ("Note the argument order") claims, in a comment the bare tuple comparison backs
    with no `assert`, that `evaluate_outcomes` and `evaluate_selective` agree on every field but
    `threshold` for a confidence-only rule. #152's allowed docs edit cannot add the `assert`
    itself (that is a content change), so this test checks the same claim here instead, against
    the real objects the block computed. Catches exactly what a bare comparison cannot: swapping
    `evaluate_selective`'s argument order silently computes something else, with no exception."""
    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(10)
    try:
        namespace: dict = {}
        exec(compile(_source(4), "docs/evaluation.md:block4", "exec"), namespace)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    a, b = namespace["a"], namespace["b"]
    assert (a.n_total, a.n_answered, a.coverage, a.accuracy, a.risk) == (
        b.n_total,
        b.n_answered,
        b.coverage,
        b.accuracy,
        b.risk,
    ), "evaluate_outcomes and evaluate_selective no longer agree on block 4's synthetic data"
