# Notebook style

`jev_cookbook.style` makes every notebook look the same and makes every notebook say which
mode it ran in. It is one module, `src/jev_cookbook/style.py`, with no data files: the
theme is a dict of matplotlib settings in code, so there is nothing extra to package.

```python
from jev_cookbook.style import apply_style, run_header, show_answer

apply_style()  # once, near the top
run_header(7, "Triage support tickets", "synthetic")
show_answer(answer)  # the typed answer, before any aggregate
```

Both calls print and return `None`, so a cell that ends with one shows no second, echoed
output. `run_header_text(...)` and `format_answer(...)` return the same text as a string.
No `%matplotlib inline` line is needed: see [Charts](#charts).

Importing the module changes nothing global (no rcParams, no colormap registration, no
pyplot import). `apply_style()` does that on purpose. The chart helpers apply the theme
themselves, so they look right even if `apply_style()` was not called.

## Run header

`run_header(recipe, title, mode, *, model=None, recorded_on=None, n_examples=None)` prints
three lines and returns `None` (`run_header_text` with the same arguments returns the text). `mode` is `"synthetic"`, `"scripted"`, `"recorded"`, `"live"`, or a
`RunInfo(mode, model, recorded_on, n_examples)`. Recorded needs `model` and `recorded_on`, live needs
`model`; a synthetic or scripted run refuses a model, because nothing a model produced is
in it. Wrong combinations raise `ValueError` rather than printing a vague header.

### From a backend

`run_header(recipe, title, backend=backend, n_examples=None)` reads `backend.mode`,
`backend.model` and, for a recorded run, `backend.recorded_dates` (a `ReplayBackend`, a
`ScriptedBackend`, or anything with those attributes, such as a live backend) and prints
exactly the text of that mode below. A synthetic or scripted backend's model name is not
shown. A recorded backend with one date says `on DATE`; with several it says `between FIRST
and LAST` (one date when they are equal), for example `...to model MODEL between 2026-01-02 and 2026-01-09. Any numbers...`.
`backend=` cannot be combined with `mode`, `model` or `recorded_on`. The explicit form above
keeps working unchanged. A sample size of one reads `1 example`, not `1 examples`.

`n_examples` is an optional sample size, accepted in every mode. Recorded then ends
`...describe only that recorded sample of 12 examples.` and live ends `...describe only the
12 examples in this run.` In a synthetic or scripted run it is the size of the fixture
sample the pipeline check ran on, added to the second line (`Mode: offline replay of
synthetic fixtures, pipeline check on a fixture sample of 12 examples`, and `Mode: offline,
scripted backend, pipeline check on a fixture sample of 12 examples`); the third line, the
sentence that the numbers are pipeline checks and not Jev results, is unchanged. Without
`n_examples` every header is exactly as shown below.

Synthetic (offline replay of `synthetic` fixtures):

```text
Recipe 07: Triage tickets
Mode: offline replay of synthetic fixtures
Metrics in this run are checks that the pipeline works. They are not Jev results.
```

Synthetic with `n_examples=12`:

```text
Recipe 07: Triage tickets
Mode: offline replay of synthetic fixtures, pipeline check on a fixture sample of 12 examples
Metrics in this run are checks that the pipeline works. They are not Jev results.
```

Scripted backend (offline): same third line, second line `Mode: offline, scripted backend`
(with `n_examples=12`: `Mode: offline, scripted backend, pipeline check on a fixture sample of 12 examples`).

Recorded (offline replay of `recorded` fixtures; the model string and date are the ones you pass):

```text
Recipe 07: Triage tickets
Mode: offline replay of recorded fixtures
The answers were captured from real Jev calls to model MODEL on DATE. Any numbers below describe only that recorded sample.
```

Live:

```text
Recipe 07: Triage tickets
Mode: live
Calls are being made now to model MODEL. Any numbers below describe only the examples in this run.
```

The header never states or implies quality, latency, or cost, in any mode. Tests pin the
exact text of every mode and check that the synthetic sentence appears in synthetic and
scripted runs and in no other.

## One typed answer

`show_answer(answer)` prints (and returns `None`), and `format_answer(answer)` returns, a readable view. Answers
are read by duck typing: a Choice has `choice`, `probabilities`, `confidence`; a Score has
`score`, `probabilities`, `confidence`, `legend` (levels are sorted by integer value, so
`2` comes before `10`, and the score line is placed by level value); a Noul has `noul` only
(the probability of yes, with no separate confidence); every answer has a `provenance`.

The real classes of `jev_cookbook.answers` work directly. Probabilities, `score`, `confidence`
and `noul` are shown to two decimals (the stored values are not changed). The read-only
mappings print as plain values, never as `mappingproxy(...)`. A legend value that is text is
shown as is; an object or array is shown as compact JSON on the level's line, for example
`0 {"label": "low", "n": 1}  0.10`. A recorded provenance shows its model and date
(`Provenance: recorded (MODEL, 2026-01-02)`); a synthetic one shows `synthetic`.

```text
Choice: calm (confidence 0.90)
  calm     0.70  ##############
  angry    0.20  ####
  excited  0.10  ##
Provenance: synthetic
```

## Charts

All helpers take plain arrays or mappings, return a matplotlib `Figure` (the one that owns
`ax` when you pass `ax=`), never call `plt.show()`, and work on the `Agg` backend. The
figures are not registered with pyplot, so a notebook does not show them twice: end the
cell with the returned figure, or call `fig.savefig(...)`.

**Print what you plot.** CI's figure comparison is loose by design (it compares what a figure
shows, not its exact pixels, so a moved line or marker still passes); the number that is actually
pinned byte for byte is whatever the cell prints. Pair every `plot_*` call with a `print` of the
same data, rounded, in the same cell — the confusion matrix's counts, a sweep's rows — so a
reader (and a diff) can see the numbers a figure draws without reading pixels. See
[recipe-template.md](recipe-template.md), "Choices the template makes for you", for the worked
example.

**Title convention.** A figure's `title=` carries the pipeline-check disclosure, `{check}`, when
it is plotted in a synthetic or scripted run, and nothing else: a figure is read once, as a
pipeline check or as a result, never additionally re-labelled as a selection step the way a
printed number is. A figure plotted from `validation` still carries only `{check}` in its title,
even though a *printed* `validation` line carries both `{selection}{check}`
([recipe-template.md](recipe-template.md)).

### Showing a figure in a notebook

A cell that ends with a returned `Figure` renders as an image in a plain `ipykernel`
session, without `%matplotlib inline`. The mechanism is that `apply_style()`, when it runs
under IPython (`get_ipython()` is not `None`), registers a PNG formatter for
`matplotlib.figure.Figure` on the shell's display formatter. The formatter draws with the
Agg canvas, so it needs no pyplot and no GUI backend. It was chosen over importing
`matplotlib.pyplot` or switching the backend because importing the module (and the helpers)
must keep changing no global state and leaking no pyplot figures; the registration happens
only when a notebook calls `apply_style()`, which is already documented as global. Outside
IPython `apply_style()` registers nothing. `%matplotlib inline` still works and is not
needed. If a cell does not call `apply_style()` first, a returned figure prints as
`<Figure ...>` text, so call it once near the top. A test executes a two-cell notebook in
a real kernel and asserts an `image/png` output, and its negative control (no
`apply_style()`) shows none.

| Helper | Draws |
| --- | --- |
| `plot_confusion_matrix(counts, labels=None, *, normalize=False, title=None, ax=None)` | gold by predicted, every cell annotated; `counts` may be an object with `.labels` and `.matrix` |
| `plot_answer_probabilities(answer, *, highlight=None, title=None, ax=None)` | probability bars for a Choice, Score, Noul, or a plain mapping |
| `plot_threshold_sweep(thresholds, metrics=None, *, chosen=None, title=None, ax=None)` | one line per metric, chosen threshold marked; `thresholds` may be a list of objects with `.threshold` and `.precision`, `.recall`, `.f1` |
| `plot_risk_coverage(coverage, risk=None, *, label=None, reference_risk=None, title=None, ax=None)` | error rate on answered cases against fraction answered; `coverage` may be an object with `.coverage` and `.risk` |

The evaluation toolkit's results are accepted by duck typing, without importing it:
`confusion_matrix(...)` results (`.labels`, `.matrix`), the list from `threshold_sweep(...)`
(each point has `.threshold`, `.precision`, `.recall`, `.f1`; an undefined NaN value leaves a
gap in the line), and `selective_curve(...)` results (`.coverage`, `.risk`).

### Legibility on GitHub's light and dark views

Every figure has an explicit, opaque paper (`#FEFEFE`) figure and axes background, and
`savefig.transparent` is off, so a figure keeps its own light panel inside GitHub's dark
notebook view instead of drawing ink-coloured text on a dark page. A test saves every
chart to PNG and checks that no pixel is transparent and the corner pixel is paper.

### Colour-blind readability

- Categorical order: ink `#1E1E1E`, pink `#F386A1`, blue `#1F78A8`, amber `#E8A33D`.
  Blue and amber are additions to the brand palette: pink and magenta alone become nearly
  one hue for protanopia. Magenta `#E551BA` is kept for highlights (the score line, the
  chosen threshold) and is not in the cycle. Lines also differ by marker shape.
- Sequential ramp (confusion matrix): `#FBE3EA`, pink, `#B0287A`, ink, with lightness
  falling at every stop. Cell numbers use ink or paper, whichever has the higher contrast against that cell;
  a test sweeps the whole ramp and requires at least 4:1.
- Check actually run (`tests/test_style.py`): the four categorical colours were converted to
  deuteranopia and protanopia with the Machado, Oliveira and Fernandes (2009) matrices
  (severity 1.0, in linear RGB), and every pair was compared by CIELAB distance (dE76). The
  test requires at least 20 for every pair in normal vision and under both simulations; the
  measured minimums are 49.7 (normal), 49.8 (deuteranopia) and 28.9 (protanopia, pink
  against blue). For the ramp, the CIELAB lightness L* of the stops is 92.3, 68.5, 41.5 and
  11.3 (steps of at least 10, required by the test), and the sampled colormap is strictly
  monotonic, so it also reads in greyscale. This is a simulation and a distance check, not a
  study with colour-blind readers.

## Example figures

The images below are regenerated by the snippet that follows. The data is made up for
illustration; it is not model output and says nothing about how Jev performs.

![Confusion matrix](assets/notebook-style/confusion-matrix.png)
![Probability bars for one Choice answer](assets/notebook-style/answer-probabilities.png)
![Threshold sweep](assets/notebook-style/threshold-sweep.png)
![Risk and coverage](assets/notebook-style/risk-coverage.png)

```python
# Regenerates docs/assets/notebook-style/*.png. Run from the repository root.
# The numbers are illustrative placeholders, not results.
from dataclasses import dataclass
from pathlib import Path

from jev_cookbook.style import (
    plot_answer_probabilities,
    plot_confusion_matrix,
    plot_risk_coverage,
    plot_threshold_sweep,
)

OUT = Path("docs/assets/notebook-style")
OUT.mkdir(parents=True, exist_ok=True)


@dataclass
class IllustrativeChoice:  # stand-in with the attribute names of a Choice answer
    choice: str
    probabilities: dict
    confidence: float
    provenance: str = "synthetic"


def save(fig, name):
    # No "Software" metadata, so the PNG bytes do not change with the matplotlib version tag.
    fig.savefig(OUT / name, metadata={"Software": None})


save(
    plot_confusion_matrix(
        [[18, 3, 1], [4, 15, 2], [0, 5, 12]],
        ["billing", "bug", "feature"],
        title="Confusion matrix (illustrative counts)",
    ),
    "confusion-matrix.png",
)
save(
    plot_answer_probabilities(
        IllustrativeChoice("bug", {"billing": 0.12, "bug": 0.71, "feature": 0.17}, 0.71),
        title="One Choice answer (illustrative values)",
    ),
    "answer-probabilities.png",
)
thresholds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
save(
    plot_threshold_sweep(
        thresholds,
        {
            "precision": [0.55, 0.6, 0.66, 0.72, 0.78, 0.84, 0.89, 0.93, 0.97],
            "recall": [0.98, 0.95, 0.9, 0.84, 0.77, 0.66, 0.52, 0.38, 0.2],
        },
        chosen=0.5,
        title="Threshold sweep (illustrative values)",
    ),
    "threshold-sweep.png",
)
save(
    plot_risk_coverage(
        [0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0],
        [0.0, 0.02, 0.04, 0.07, 0.11, 0.16, 0.22],
        label="by confidence",
        reference_risk=0.22,
        title="Risk and coverage (illustrative values)",
    ),
    "risk-coverage.png",
)
```
