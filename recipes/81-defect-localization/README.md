# Defect localization

**Recipe 81 · Level 3 (Intermediate) · `Box` + `Noul`**

Locate one requested scratch, dent, or broken component on a synthetic service panel. Three batched propositions establish presence, uniqueness, and a clear view before a separate Box request. Python selects the final policy on validation, draws accepted rectangles and crops, and sends ambiguous inspections to a simulated review queue. A Box always supplies coordinates; that is why presence comes first.

The 30 original Pillow drawings include scratches, shaded dents, fractured terminals, clean panels, printed registration marks, reflections, multiple defects and occluding tool covers. They are synthetic illustrations, not photographs. Inference receives pixels and the requested defect kind; expected outcomes and geometry stay in readable gold labels. The deterministic baseline finds the largest connected dark region using pixels alone.

## Run offline

From the repository root, install the package as described in [development](../../docs/development.md). To reproduce committed notebook outputs, use Python 3.14 and the pinned notebook stack:

```bash
python -m pip install -e '.[ml]' -c .github/constraints-notebooks.txt
python recipes/81-defect-localization/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/81-defect-localization
python tools/execute_notebook.py recipes/81-defect-localization
python -m pytest recipes/81-defect-localization -q
```

The generator reproducibly authors the assets and synthetic fixtures. It rewrites inputs and labels, but refuses to replace recorded responses without `--force`. The notebook executor always strips live settings. No key or network is needed.

## Switch to live

Install the optional `.[live]` dependency and use the opt-in described in [live inference](../../docs/live.md). The same questions request pinned `jev-1.14.0` with `images=True`. Set `JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MAX_REQUESTS=60`, with the key supplied only through the environment.

The committed synthetic execution makes exactly **48** calls: 30 batched screening requests and 18 dependent localization requests. It caches each request once, including validation trials and demonstrations. Real answers can change the second-stage count: 30–60 successful calls for this corpus. The recipe cap is 60 calls and the live backend independently counts attempts, including retries; retries may exhaust its budget sooner. No call sends an annotation or changes equipment state.

For reportable results, capture a copy of this recipe with `helpers.record_corpus(backend, examples, destination, root=recipe_copy)`, where `destination` is a new `fixtures/responses.json`. The helper uses `record` with `(state, questions, assets)` triples and branches on the actual recorded first-stage answers. It writes manifests with those actual request keys; keep the copied assets beside them. Responses retain the returned model, capture date and reported usage. Replay the capture to report held-out numbers. An unrecorded live notebook run suppresses the aggregate test report. Latency and cost stay unknown unless separately measured during real inference; replay timing is never inference latency.

## What was and was not measured

**Not measured live.** The committed answers are synthetic and intentionally imperfect. Every number is a pipeline check, not a Jev result. The 14 validation examples choose among nine policies; the 14 test examples are evaluated after freezing the policy; two demos are unscored. No live quality, latency, token or cost measurement is claimed.

The reported coverage uses actual accepted outcomes, excluding every review. Accepted localization is correct at IoU ≥ 0.50. The primary IoU covers every uniquely visible target, assigning zero to both accepted misses and deferred targets. Misses, false positives on absent scenes, poor-overlap boxes and boxes on multiple/occluded scenes have explicit denominators. Resolved-target IoU is supplemental. A confidently wrong reflection box, a misplaced dent box and a confident absence on a broken terminal remain accepted in the held-out fixtures. The baseline uses the same test images with fixed constants, and has its own misses and false positives.

The images are deliberately simple, the acquisition screen is fixed at 0.80 before selection, and this lesson does not establish generalization to real factory imagery. Crops are displayed locally, not sent through a third inference stage. The local builder changes only this recipe; catalog integration and genuine Opus review remain separate gates.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S10: [TypeSafe AI: Box](https://docs.typesafe.ai/primitives/box)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
