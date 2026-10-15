# Golden-sample assembly checks

**Recipe 71 · Level 2 (Easy) · Score with a visibility Noul**

Compare a synthetic slider assembly with good and defective samples embedded directly in the
ordered `Score.criteria`. Python applies a frozen confidence gate and an independent visibility
interlock, then records simulated inspection candidates or review items. Nothing authorizes release.
The notebook shows every visual rubric level and typed answers before evaluation.

## Run it offline

From the repository root, with the cookbook's development environment (`pip install -e ".[dev]"`):

```bash
python -m jev_cookbook.fixtures validate recipes/71-golden-sample-assembly-checks
pytest recipes/71-golden-sample-assembly-checks
python tools/execute_notebook.py recipes/71-golden-sample-assembly-checks
```

For committed notebook outputs use Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`, as described in
[notebook execution](../../docs/recipe-template.md). No network or key is needed.

## What it teaches

- Four ordered conformity levels, each defined by text and actual reference images. A separate
  visibility proposition handles occlusion without pretending uncertainty is a severity level.
- Independent query views; pixels and fixed context reach inference, while labels and drawing
  parameters stay local. Opaque content references bind all eight request images to replay keys.
- Validation selects the smallest confidence cutoff with perfect accepted ordinal agreement;
  test reports after both the Score and registered-pixel baseline cutoffs are frozen.
- Exact agreement and expected-score MAE use the ten readable test queries; coverage, abstention,
  accepted accuracy and wrong acceptance use all twelve. Review is excluded from coverage.
- A confidently wrong synthetic sticker case survives the gate. A “PASS” sticker does not prove
  conformance, and a model confidence threshold does not certify an assembly.

The deterministic baseline registers the colored plate, normalizes brightness and compares resized
RGB crops to the same references. It reads no labels or authored geometry. Its limitations include
small rotation sensitivity and failure to distinguish occlusion from part changes.

## Switch to live

Install the optional SDK (`pip install -e ".[live]"`), supply `TYPESAFE_API_KEY` through the environment,
and explicitly set `JEV_COOKBOOK_LIVE=1`. The recipe pins `jev-1.14.0` and enables experimental images.
The notebook makes exactly **26** calls without retries, with two independent questions per request.
Raise `JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at least 26 (for example, 32); the default is 25 and every
retry consumes an attempt. The recipe's own cache caps distinct requests at 26. An interactive live
run is unrecorded exploration; the notebook executor always runs offline.

To record the identical request triples, from this recipe folder run:

```bash
python record_live.py --output capture/responses.json
```

This opt-in script uses `record`, protects the committed synthetic response file and writes a
request ledger beside the separate capture. Keep capture files private until reviewed; they are not
part of the authored fixture set. The recorder retains the returned model, UTC capture date and
reported usage; missing counts remain null. It does not measure latency or billing. See the
[live contract](../../docs/live.md) before substituting an independently reviewed recording.

## What was and was not measured

**Synthetic replay; not measured live.** There are 12 validation queries, 12 test queries and
2 unscored demos; 26 query drawings and 7 rubric references (33 PNG files). All are authored with
Pillow at 480 × 360. They are drawings, not photographs. Fixtures cover missing bolts, reversed
orientation, displaced parts, multiple faults, absence, benign lighting and translation, occlusion,
glare, blur, and an irrelevant “PASS” sticker. Test pictures share the rendering grammar with
validation, so the split is a plumbing check rather than real-world generalization evidence.

Every response is intentionally synthetic, including errors. Model quality, inference latency,
token usage and cost were not measured. The notebook's numeric results describe only these fixtures.
Live use requires independent photographs, fresh annotations and held-out evaluation; this recipe
provides no autonomous production inspection system.

`helpers.py` owns requests, the request cap, routing, baseline and metrics; `build_fixtures.py`
authors assets and readable labels and refuses recorded-response overwrite without `--force`.
Tests cover routing under arbitrary typed answers, image identity, data separation, reproducibility,
recording overwrite guards and a wrong accepted test answer after validation threshold selection.

## Next steps

Continue with [03: Response scoring](../03-response-clarity-scoring/) and
[38: Abstention and review queues](../38-abstention-and-review-queues/).

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
