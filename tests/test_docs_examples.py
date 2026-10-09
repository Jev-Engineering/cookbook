"""Extracts, lints and (for the ones marked executable) runs the fenced Python examples in
``docs/evaluation.md`` (#152, from the Opus reviews of #146, comments 6071614909 and
6071956764).

Before this file, a documented example could drift from the real ``jev_cookbook`` API with
nothing noticing: ``ruff check`` does not scan Markdown (``ruff format`` does, but only for
fence formatting, not correctness), and nothing executed a documented snippet end to end except
one block in ``docs/backends.md`` (``tests/test_backends.py::test_fixture_recipe_in_the_docs_runs``,
the precedent this file follows). That gap is exactly how the "Noul three-path pattern" example
shipped with a selection-on-test error and a ruff B905 finding (bare ``zip(...)`` with no
``strict=``) that had to be caught by hand.

**Convention.** Every fenced ```python block in the doc is extracted, in document order (index
0, 1, 2, ...). Each is linted with the repository's own ruff configuration, against a small
preamble from ``PREAMBLE`` below that binds whatever names the example assumes are already in
scope (an import shown in an earlier block, a variable named for what a caller would supply,
such as ``val_gold``) -- so a genuine mistake (a typo, a removed ``strict=True``, a renamed
function) still fails lint, while an intentional, documented placeholder does not. This is the
"explicit allowlist" the issue offers as one option for the marker convention: ``PREAMBLE``
names, for every block, exactly what it is assumed to already have in scope.

A block is additionally *executed*, under a short timeout, against synthetic data, only if its
index is in ``EXECUTED`` -- the issue's "self-contained" blocks: runnable end to end against
plausible, type-correct synthetic input, with no live call and no side effect. The rest are
lint-only, most because they are deliberately partial (a fragment such as
``exempt | (~exempt & (confidence >= t))``, written to show one line of a larger function, not a
complete program).

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
a content change):

- **Block 0** (the module's opening ``from jev_cookbook.evaluation import accuracy,
  select_threshold, evaluate_threshold``) fails ``I001`` (the three names are not alphabetised)
  and ``F401`` (none of them is used in that one-line block, since it exists only to show the
  import itself).
- **Block 4** (the ``evaluate_outcomes``/``evaluate_selective`` equivalence snippet, "Note the
  argument order") ends with a bare tuple comparison used to show a reader what is true, not to
  assert it in running code, and fails ``B015`` ("pointless comparison").

Each would need one line of ``docs/evaluation.md`` changed to pass (alphabetise the import;
wrap the comparison in ``assert`` or a variable) -- a content fix, not a marker. The ``xfail``
entries below record this precisely rather than silently excluding either block from "every
fenced block": if a block is ever corrected, this test starts failing (``strict``) as a signal
to remove its marker.
"""

import re
import shutil
import signal
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "evaluation.md"
PYPROJECT = REPO / "pyproject.toml"
TEXT = DOC.read_text("utf-8")
BLOCKS = re.findall(r"```python\n(.*?)```", TEXT, re.S)

RUFF = shutil.which("ruff") or "ruff"

# What each block assumes is already in scope. Lint never executes anything, so a value only
# has to exist with a plausible type; the EXECUTED blocks below need it to also be realistic.
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

# The issue's "self-contained" allowlist: blocks runnable end to end against the synthetic data
# in PREAMBLE, with no live call and no side effect beyond an in-memory matplotlib Figure.
EXECUTED = {0, 1, 6, 7}

KNOWN_LINT_GAP = {0, 4}  # see "Known gaps" in the module docstring

assert len(BLOCKS) == 8, (
    f"docs/evaluation.md now has {len(BLOCKS)} fenced python block(s), not 8: update PREAMBLE, "
    "EXECUTED and KNOWN_LINT_GAP above for the new or removed block before trusting this test"
)
assert set(PREAMBLE) == set(range(len(BLOCKS)))


def _source(index: int) -> str:
    return PREAMBLE[index] + BLOCKS[index]


def _lint(index: int, tmp_path: Path) -> subprocess.CompletedProcess:
    path = tmp_path / f"evaluation_block_{index}.py"
    path.write_text(_source(index), encoding="utf-8")
    return subprocess.run(
        [RUFF, "check", "--config", str(PYPROJECT), str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "index",
    [
        pytest.param(
            i,
            marks=pytest.mark.xfail(
                reason=(
                    f"docs/evaluation.md block {i} fails ruff check verbatim (I001/F401 for "
                    "block 0, B015 for block 4); fixing it is a content change, outside "
                    "#152's marker-convention-only docs edit -- see the module docstring's "
                    "'Known gaps'"
                ),
                strict=True,
            ),
        )
        if i in KNOWN_LINT_GAP
        else i
        for i in range(len(BLOCKS))
    ],
)
def test_block_lints_clean(index, tmp_path):
    proc = _lint(index, tmp_path)
    assert proc.returncode == 0, (
        f"docs/evaluation.md block {index} fails `ruff check`:\n{proc.stdout}{proc.stderr}"
    )


class _Timeout(Exception):
    pass


def _alarm(_signum, _frame):
    raise _Timeout("docs/evaluation.md example exceeded its timeout")


@pytest.mark.parametrize("index", sorted(EXECUTED))
def test_block_executes(index):
    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(5)
    try:
        exec(compile(_source(index), f"docs/evaluation.md:block{index}", "exec"), {})
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        import matplotlib.pyplot as plt

        plt.close("all")  # block 6 calls plot_risk_coverage, which opens a Figure
