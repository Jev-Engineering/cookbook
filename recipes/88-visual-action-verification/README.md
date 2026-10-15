# Visual action verification

**Recipe 88 · Level 3 (Intermediate) · Multiframe `Noul`**

Compare ordered before/after screenshots against one explicit visible postcondition. Independent
`Noul` questions check the final state and whether it was absent initially. Python validates
timestamps and image files, selects a certainty gate on validation, and sends uncertain or invalid
evidence to review. Only an accepted transition records a simulated handoff; no browser is connected.

The notebook shows the images and typed answers before evaluation. An independent pixel-change
baseline demonstrates why an unrelated banner cannot establish the intended action. Cases include
opening a dialog, toggling and saving a setting, no change, unrelated change, delayed completion,
loading, obscured evidence, missing frames, reversed order, and an already-open dialog.

## Run offline

From the repository root, after installing the development dependencies:

```bash
python -m jev_cookbook.fixtures validate recipes/88-visual-action-verification
python tools/execute_notebook.py recipes/88-visual-action-verification
pytest recipes/88-visual-action-verification
```

For byte-stable committed outputs use Python 3.14 and the repository's
[notebook constraints](../../.github/constraints-notebooks.txt). The executor always runs offline.

The Pillow generator writes invented 512×384 UI screenshots into `assets/` and strict JSON fixtures
into `fixtures/`. Reproduce both with:

```bash
python recipes/88-visual-action-verification/build_fixtures.py
```

Recorded responses are protected from replacement unless `--force` is explicitly supplied.
Inputs, labels, and assets regenerate independently, so changing a question or picture may require
recording new request keys. Tests check image/fixture byte reproduction and the overwrite guard.

## Switch to live

Install the live SDK extra and set `TYPESAFE_API_KEY` and `JEV_COOKBOOK_LIVE=1`, then open the notebook
from this folder. It requests `jev-1.14.0` and enables the experimental image capability explicitly
with `images=True`. The input is timestamped PNG still frames, not native video. See
[live setup](../../docs/live.md) and the [image utilities](../../docs/vision.md).

The notebook makes exactly 20 requests: two demonstrations, nine validation sequences, and nine test
sequences. Four invalid sequences are rejected before any request. Two independent questions share
each request. The default budget of 25 counts retries too; adjust
`JEV_COOKBOOK_LIVE_MAX_REQUESTS` deliberately if needed. A live run must be recorded before its
quality results are reportable.

## What was and was not measured

**Mode: synthetic; not measured live.** There are 11 validation and 11 test examples, plus two
unscored demonstrations. Every reported number is an authored pipeline check. No model inference
latency, input tokens, or cost was measured; missing values stay unknown.

The frozen test evaluation reports event/workflow accuracy, actual answered coverage and accuracy,
abstention, success precision/recall, false accepted handoffs, and pixel-baseline accuracy. The
fixtures deliberately include a confident wrong answer that passes the gate. These numbers say
nothing about Jev's quality. The test layout differs from validation, but both come from one small
drawing program; they do not represent independent real applications. Visible change cannot prove
that an action caused it or that a server persisted a setting.

## Further reading

- [29 — Tool outcome verification](../29-tool-outcome-verification/)
- [25 — Change evidence review](../25-change-evidence-review/)

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
