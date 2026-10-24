# Assembly progression recognition

Recipe 90 · Level 3 (Intermediate) · `Choice` · Multiframe & temporal understanding.

Classify the visible stage of a desktop arch across timestamped stills. Three independent stage questions share one request; Python accepts only unchanged or one-step progress and sends uncertainty, unknown parts, regression and skipped observations to review. All stage notes are simulated. Visible cap placement says nothing about hidden work or mechanical completion.

The original synthetic drawings show a blue plinth, teal posts, orange bridge and pink cap. The 26 sequences contain 78 distinct 384 × 320 PNGs: 12 validation, 12 test, two unscored demonstrations. Cases include loose parts, partial and occluded views, unknown attached components, removal, missing observations and misleading scene text. Only pixels, ordered timestamps and fixed assembly context enter requests.

## Run offline

From the repository root, with Python 3.14 and the repository environment:

```bash
pip install -e ".[ml]" -c .github/constraints-notebooks.txt
python recipes/90-assembly-progression-recognition/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/90-assembly-progression-recognition
python tools/execute_notebook.py recipes/90-assembly-progression-recognition
python -m pytest recipes/90-assembly-progression-recognition -q
```

Install `.[dev]` separately for pytest and ruff. Open [notebook.ipynb](notebook.ipynb) for the images, typed answers and executed results. Regeneration is deterministic and refuses to replace recorded responses without `--force`; inputs, labels and authored drawings are rebuilt even on refusal. Keep recordings in a separate capture directory until explicitly integrating them.

## Evaluation

Validation maximizes coverage subject to zero accepted trajectory errors among structurally eligible examples, using the minimum frame confidence and `target_accuracy=1.0`. Freeze the cutoff before test. `evaluate_outcomes` measures actual acceptance flags, including all progression interlocks. Report frame-stage, final-stage and event accuracy, accepted accuracy, risk and abstentions with N. A high-confidence wrong test answer remains accepted deliberately.

The pixel baseline counts fixed component-color areas in a broad assembly window, followed by the same progression checks. It reads image pixels alone and cannot distinguish a seated cap from a loose cap beside the arch. Both systems are tested on identical sequences. The baseline's confidence of one is a deterministic accept flag, not an uncertainty estimate.

## Switch to live

The full notebook makes exactly **26 requests** with three questions each, including demonstrations. `SequenceRunner` caches requests and stops after 26 distinct attempts. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` for the backend's independent transport cap; retries consume that budget. `get_backend(..., images=True, model="jev-1.14.0")` preserves the same questions. Direct live exploration stops before aggregates because unrecorded live runs are not reportable held-out results.

To deliberately record all requests, install `.[live]`, supply your own `TYPESAFE_API_KEY` in the environment, set `JEV_COOKBOOK_LIVE=1`, and run:

```bash
python recipes/90-assembly-progression-recognition/record_live.py --output /tmp/arch-capture
```

The destination must be new and outside this recipe. [record_live.py](record_live.py) calls `record` with the unchanged `(state, questions, assets)` triples, pinned `jev-1.14.0`, image opt-in, 26 attempts and no retries. It preserves actual returned model, date and usage in responses, request details in a ledger, and actual inference-call latency in a separate measurements file; cost stays null. It never overwrites committed synthetic fixtures. A failed capture leaves already recorded responses for inspection. Do not run `build_fixtures.py --force` over integrated recordings. See [live documentation](../../docs/live.md) for replaying recorded responses and preserving sidecars outside `fixtures/`.

## What was and was not measured

**not measured live**. Every committed answer is synthetic; numbers are pipeline checks, not Jev results. Latency, tokens and cost are unknown (`None`) in synthetic mode. Recorded held-out reports must name the returned model, dates and N; live unrecorded exploration is not such a report. These stylized drawings do not measure performance on factory photographs, hidden component installation, structural integrity or real equipment.

## Next steps

See [abstention and review queues](../38-abstention-and-review-queues/) and [image helpers](../../docs/vision.md). Genuine review and integration remain separate from local execution.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
