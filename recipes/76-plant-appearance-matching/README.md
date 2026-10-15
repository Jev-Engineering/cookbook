# Plant appearance matching

**Recipe 76** · Level 2 (Easy) · Decision type: `Choice` with image criteria

Suggest an appearance group from a query image and four labeled visual examples:
`broadleaf`, `needlelike`, `rosette`, or `fernlike`. `unknown` always asks for review.
The lesson demonstrates a workflow for plant photographs using **authored Pillow foliage
illustrations**, not real photographs. The groups describe visible arrangements, not species.
Nothing here identifies species or assesses health or edibility.

## What it teaches

Reference images appear inside each `Choice` criterion. The query state contains one opaque image
reference; IDs, filenames, labels and drawing parameters stay outside inference. Python fixes the
candidate vocabulary, limits the session to 26 decisions, caches reused requests, and routes an
accepted candidate to a simulated `ActionLog` or a deferral to `ReviewQueue`.

The 30 images comprise four references and 26 independently drawn queries: 12 validation,
12 test, and two unscored demos. They vary rotation, color and occlusion, and include an isolated
leaf, multiple plants, empty scenes, grasslike tufts and an unfamiliar fan. Gold labels and
invented response probabilities are readable in `build_fixtures.py`.

Validation chooses the lowest observed confidence giving perfect accepted accuracy among answers
that name a supported group. Unknown is excluded from fitting because it always defers. Failure to
find a valid gate stops the run before test evaluation or suggestions. Test uses the frozen gate
once. A second, deterministic baseline extracts saturated foreground color, bounding-box aspect,
fill, boundary density and a 6 × 6 silhouette grid. It finds the nearest reference by Euclidean
distance and chooses a radius from a declared family on validation, maximizing accepted accuracy
with at least 50% coverage. All comparisons use the same images and gold labels.

## Run it offline

From the repository root, with development dependencies installed:

```bash
python recipes/76-plant-appearance-matching/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/76-plant-appearance-matching
python tools/execute_notebook.py recipes/76-plant-appearance-matching
python -m pytest recipes/76-plant-appearance-matching -q
```

No network or key is needed. Reproduce committed outputs on Python 3.14 with
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`; install `.[dev]` separately for
pytest and Ruff. The generator refuses to replace recorded responses unless `--force` is explicit.
The scaffold tests check this guard and byte reproducibility; further tests check image lineage,
request identity, routing under arbitrary answers, request limits, policy objectives and the
accepted wrong held-out answer.

## Switch to live

This notebook makes exactly **26 calls** in live mode without retries: one per example, five image
assets per call, with answers reused for display and evaluation. Install `.[live]`, set
`TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1`, and `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` or higher to allow
retries. The notebook explicitly requests `jev-1.14.0` with images enabled. The recipe limits
logical attempts to 26; the live backend separately bounds HTTP attempts including retries.
An exception stops the notebook. `tools/execute_notebook.py` always runs offline.

For reportable measurements, capture the same request triples using
`record_live.py --output-dir /your/local/capture-directory` with explicit live opt-in. It writes
inputs, labels, recorded responses and an accounting file outside the committed fixtures. The
recorder retains actual returned model, capture date and available token usage. The wrapper times
actual inference requests; measured cost remains null. Read the [live contract](../../docs/live.md).
An unrecorded live notebook run is exploration, never a reportable held-out result.

## What was and was not measured

**Synthetic pipeline checks; not measured live.** On N=12 test illustrations, the frozen synthetic
answer policy accepts 7, correctly suggests 6, and defers 5: accepted accuracy 6/7, abstention 5/12.
The frozen pixel baseline accepts 6 correctly and defers 6. Raw synthetic Choice accuracy is 10/12,
including correct unknown predictions; those unknowns still count as review, never coverage.
One confidently wrong fan-shaped example remains accepted. A confidence threshold cannot establish
that an image belongs to the reference collection.

These tiny authored images and authored answers test wiring and evaluation, not Jev quality or
real photograph performance. Shared drawing conventions make the pixel baseline unusually favorable;
its saturation mask assumes neutral backgrounds. It cannot handle ordinary clutter, lighting,
multiple depth planes or naturally overlapping forms reliably. Latency, token usage and cost are
unknown in the committed run. No external action occurs.

## Next steps

Try a second independently labeled reference per group and a new held-out photograph collection,
with permission to use it, before changing the candidate vocabulary. Freeze any revised policy on
fresh validation examples. [Sentiment classification](../01-sentiment-classification/) teaches
confidence gates, and [Support ticket routing](../04-support-ticket-routing/) explores review routing.
The generated root catalog and genuine Opus review remain integration responsibilities.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
