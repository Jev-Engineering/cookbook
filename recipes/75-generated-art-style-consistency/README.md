# Generated-art style consistency

**Recipe 75** · Level 2 (Easy) · Decision type: `Score`

Compare a candidate illustration with three compatible examples of **Quiet Orbits**, a fictional
muted geometric art direction. Three independent Scores retain palette, surface treatment and
composition judgments. Python combines them with explicit equal weights and sends uncertain
reports to a simulated review queue. A correct palette does not conceal the wrong linework.

The 29 PNGs are original **seeded Pillow procedural illustrations**, not outputs of an image
model. The 26 candidate images are independent of the three moodboard examples. Fixtures include
vivid palettes, a small discordant accent, bold outlines, grain, sparse and crowded arrangements,
corner compression, an unrelated style, an absent illustration and a washed-out image. Subjective
gold levels are authored under the complete 0–3 rubrics in `helpers.py`; each label has a rationale.

## Run it offline

From the repository root, install development tools with `pip install -e ".[dev]"`, then run:

```bash
python recipes/75-generated-art-style-consistency/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/75-generated-art-style-consistency
python tools/execute_notebook.py recipes/75-generated-art-style-consistency
pytest recipes/75-generated-art-style-consistency
```

The notebook runs from its own folder without a key or network access. Reproduce committed
outputs with Python 3.14 and `pip install -e ".[ml]" -c .github/constraints-notebooks.txt`.
The fixture generator requires `--force` before replacing recorded answers; it always regenerates
image assets, inputs and labels, so preserve an existing recording together with its original images.

## Evaluation

The 12 validation examples select a minimum-confidence cutoff for exact three-dimension modal
agreement (`target_accuracy=1.0`). The cutoff is frozen before evaluating the 12 test examples.
Two demos are shown but never scored. An indeterminate image has no numeric gold; it stays in the
routing denominator and accepting it is wrong. Per-dimension MAE and modal-level agreement use
11 numerically labeled images per split. Coverage and abstention come from actual report/review
outcomes; the equal-weight combined score never replaces the dimension reports.

The same-image baseline compares RGB histograms, edge density and foreground coverage with the
three references. Its thresholds are fixed in code and never read gold labels. It cannot reliably
separate layout, outlines and texture, and it always reports even an indeterminate image. A
confidently wrong synthetic held-out surface answer passes the frozen Score policy on purpose.

## Switch to live

This notebook makes exactly **26** calls in live mode: one batched request per example, three independent
Scores per request. Each request supplies four distinct images; repeating the three moodboard
references in the Score criteria makes ten expanded image occurrences. Set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=32` to allow a few retries beyond the 26 required attempts (every
retry consumes budget). The recipe also enforces a 26-request cap and caches already seen examples.
Install `pip install -e ".[live]"`, configure `TYPESAFE_API_KEY` in your environment and opt in with
`JEV_COOKBOOK_LIVE=1`. Requests pin `jev-1.14.0` and use `images=True` for the experimental image
header. The standard executor always runs offline.

An unrecorded live notebook run is exploration, not a reportable held-out result. To capture real
answers, run this explicit opt-in snippet from the recipe folder after setting the environment.
It writes to a separate capture directory so synthetic fixtures are preserved:

```python
from pathlib import Path
from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs, responses_path

helpers = load_helpers()
backend = get_backend(fixtures=responses_path(), images=True, model="jev-1.14.0")
if backend.mode != "live":
    raise RuntimeError("Explicit live opt-in is required for a capture")
triples = [helpers.build_request(e.fields) for e in load_inputs()]
Path("capture").mkdir(exist_ok=True)
report = record(backend, triples, "capture/responses.json", ledger_path="capture/ledger.json")
```

The recorder retains actual returned model, capture date and reported usage. Record measured
inference timing separately if needed; replay timing is not inference latency. Unmeasured cost
and latency remain `None`. Review a recording and preserve its images before installing its
responses for replay. See [live recording](../../docs/live.md) and
[image references](../../docs/vision.md).

## What was and was not measured

**Mode: synthetic; not measured live.** N=12 validation, N=12 test and two unscored demos, 26
requests and 78 typed judgments. All answer distributions were authored; they are not observations
of Jev. The notebook measures pipeline behavior, author-rubric MAE/agreement and abstention. It
makes no claim about artistic quality, real-model accuracy, inference latency, tokens or billing.
Human agreement, real image-model outputs and robustness to real capture conditions remain untested.

Local Codex implementation is subject to the repository's independent Opus review and integration
gates; it is not a merged or approved recipe. The builder changes only this recipe folder. A
designated integrator owns generated root README updates under [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
