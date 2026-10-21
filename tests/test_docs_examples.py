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
at most a few hundred milliseconds to run (measured below each test, under a 10 s limit well
above the worst observed case: ``SIGALRM`` on POSIX; on Windows a timer thread raises
``SIGBREAK``, which cannot interrupt a blocking call such as ``time.sleep``, only pure-Python
code), so none is skipped for being "not self-contained" -- only block 5
is a genuine fragment (a formula shown mid-explanation, not a program with an observable result),
and it is linted and executed the same as the rest; there is simply nothing further to assert
about it.

**Linting never masks a new finding.** A block that fails `ruff check` with findings outside
``ALLOWED_FINDINGS`` below fails the test, including a *new* finding of the same code the block
already has a pre-existing one for, because matching is by exact ``(block, code, line)``, not by
block or by code alone. Two of the nine blocks have pre-existing findings (next section); every
other block must lint perfectly clean.

**Not included.** ``docs/backends.md``, ``docs/fixtures.md`` and ``docs/live.md`` (the issue's
"if cheap" extension) are left out: ``backends.md``'s one fully self-contained block is already
executed by the precedent above, so repeating it here would check nothing new; ``fixtures.md``'s
five blocks each reference their own example-specific placeholders (``recipe``, ``example_id``,
``candidates``, a real ``backend``) needing a bespoke preamble per block, which is not cheap; and
``live.md``'s three blocks construct a ``LiveBackend`` or a third-party adapter client, which
this suite must never do (CONTRIBUTING.md section 1: no key, no network, and
``jev_cookbook.LiveBackend`` must never be instantiated by a test that runs in CI).

**Known gaps, left for the orchestrator rather than fixed here.** Two of the nine blocks fail
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

import _thread
import contextlib
import json
import re
import signal
import subprocess
import sys
import threading
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
    8: "",
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

assert len(BLOCKS) == 9, (
    f"docs/evaluation.md now has {len(BLOCKS)} fenced python block(s), not 9: update PREAMBLE, "
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


@contextlib.contextmanager
def _time_limit(seconds):
    """Raise ``_Timeout`` if the body runs longer than ``seconds``.

    POSIX uses ``SIGALRM`` (``seconds`` must be an int there). Windows has no ``SIGALRM``, so a
    timer thread raises Ctrl-Break (``signal.SIGBREAK``) in the main thread through a handler
    only this helper installs: a real Ctrl-C (``SIGINT``) is never touched or reinterpreted. An
    ``armed`` flag is cleared in ``finally`` before the timer is cancelled and joined and the old
    handler restored, so a trip that lands late is a no-op. Limit on Windows: the handler runs
    between Python bytecodes, so a blocking call in the body (``time.sleep(3)``, I/O) is not
    interrupted; ``_Timeout`` arrives only once it returns. Fine for these pure-Python blocks."""
    if _HAS_SIGALRM:
        previous = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
        return
    armed = True

    def on_timer(_signum, _frame):
        if armed:
            raise _Timeout("docs/evaluation.md example exceeded its timeout")

    previous = signal.signal(signal.SIGBREAK, on_timer)
    timer = threading.Timer(seconds, _thread.interrupt_main, args=(signal.SIGBREAK,))
    timer.start()
    try:
        try:
            yield
        finally:
            armed = False
            timer.cancel()
            timer.join()
    finally:
        signal.signal(signal.SIGBREAK, previous)


@pytest.mark.skipif(
    _HAS_SIGALRM, reason="exercises the Windows-only SIGBREAK timer path; POSIX uses SIGALRM"
)
def test_windows_time_limit_always_raises_timeout_for_a_busy_loop():
    """The shape of the race fixed in #325 review round 1: a short limit on a pure-Python busy
    loop used to escape as a bare ``KeyboardInterrupt`` in ~1-2% of runs, which aborts pytest."""
    for _ in range(100):
        try:
            with pytest.raises(_Timeout):
                with _time_limit(0.01):
                    while True:
                        pass
        except KeyboardInterrupt:
            pytest.fail("a timeout escaped _time_limit as a bare KeyboardInterrupt")


@pytest.mark.skipif(_HAS_SIGALRM, reason="exercises the Windows-only SIGBREAK timer path")
def test_windows_time_limit_leaves_a_real_ctrl_c_alone():
    with pytest.raises(KeyboardInterrupt):
        with _time_limit(10):
            _thread.interrupt_main()  # SIGINT, as a real Ctrl-C delivers it
            for _ in range(10**6):
                pass


@pytest.mark.skipif(_HAS_SIGALRM, reason="exercises the Windows-only SIGBREAK timer path")
def test_windows_time_limit_ignores_a_trip_after_the_block():
    with _time_limit(10):
        pass
    _thread.interrupt_main(signal.SIGBREAK)  # a timer that fired just as the block ended
    for _ in range(10**6):
        pass  # must not raise


@pytest.mark.parametrize("index", sorted(EXECUTED))
def test_block_executes(index):
    try:
        with _time_limit(10):
            namespace: dict = {}
            exec(compile(_source(index), f"docs/evaluation.md:block{index}", "exec"), namespace)
    finally:
        import matplotlib.pyplot as plt

        plt.close("all")  # block 6 calls plot_risk_coverage, which opens a Figure


def test_block_four_equivalence_holds():
    """Block 4 ("Note the argument order") claims, in a comment the bare tuple comparison backs
    with no `assert`, that `evaluate_outcomes` and `evaluate_selective` agree on every field but
    `threshold` for a confidence-only rule. #152's allowed docs edit cannot add the `assert`
    itself (that is a content change), so this test checks the same claim here instead, against
    the real objects the block computed. Catches exactly what a bare comparison cannot: swapping
    `evaluate_selective`'s argument order silently computes something else, with no exception."""
    with _time_limit(10):
        namespace: dict = {}
        exec(compile(_source(4), "docs/evaluation.md:block4", "exec"), namespace)
    a, b = namespace["a"], namespace["b"]
    assert (a.n_total, a.n_answered, a.coverage, a.accuracy, a.risk) == (
        b.n_total,
        b.n_answered,
        b.coverage,
        b.accuracy,
        b.risk,
    ), "evaluate_outcomes and evaluate_selective no longer agree on block 4's synthetic data"


def test_docstring_block_count_matches_the_assertion():
    """The module docstring says how many blocks there are ("Two of the nine blocks ..."); it
    must follow ``len(BLOCKS)`` so the prose cannot go stale when a block is added."""
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    words += ["ten", "eleven", "twelve"]
    mentioned = set(re.findall(r"Two of the (\w+) blocks", __doc__))
    assert mentioned == {words[len(BLOCKS)]}


VISION_TEXT = (REPO / "docs" / "vision.md").read_text("utf-8")


def _vision_block(marker: str) -> str:
    """The one fenced python block in ``docs/vision.md`` that contains ``marker``."""
    found = [b for b in re.findall(r"```python\n(.*?)```", VISION_TEXT, re.S) if marker in b]
    assert len(found) == 1, f"expected exactly one docs/vision.md block containing {marker!r}"
    return found[0]


def test_vision_frame_walkthrough_runs_on_the_pages_own_frames(tmp_path, monkeypatch):
    """The ordered-frame walkthrough in ``docs/vision.md`` continues from the ``load_frames``
    example above it. Execute those blocks in one namespace, in page order, against three
    generated stills at the paths the page names, and check the values the comments state."""
    from PIL import Image

    (tmp_path / "assets").mkdir()
    for shade, name in enumerate(("door-closed", "door-moving", "door-open")):
        Image.new("RGB", (280, 280), (shade * 90, 40, 40)).save(tmp_path / "assets" / f"{name}.png")
    monkeypatch.chdir(tmp_path)

    namespace: dict = {}
    for marker in ("load_frames(", "frame_timestamps(frames)", '"sampling"'):
        source = _vision_block(marker)
        exec(compile(source, "docs/vision.md", "exec"), namespace)

    assert namespace["times"] == [0.0, 0.75, 1.5]
    assert namespace["chosen"] == [0, 1, 2]
    assert [row["frame_index"] for row in namespace["sampled"]] == [0, 1, 2]
    assert namespace["gaps"] == [0.75, 0.75]
    assert [row["seconds_ago"] for row in namespace["labelled"]] == [1.5, 0.75, 0.0]
    assert namespace["window"] == {
        "start_seconds": 0.75,
        "end_seconds": 1.5,
        "duration_seconds": 0.75,
    }
    assert namespace["fields"]["sampling"]["indices"] == [0, 1, 2]
    assert namespace["fields"]["sampling"]["every_seconds"] == 0.5
