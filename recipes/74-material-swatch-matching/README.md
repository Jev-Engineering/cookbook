# Material swatch matching

**Recipe 74** · Level 2 (Easy) · Decision type: `Choice`

Match a query swatch against four image-defined, fictional material IDs. The criterion for
each ID is an actual reference PNG. This lesson shows why both color and texture matter:
two references share a color, two share a weave pattern, and query images vary in scale,
orientation, and illumination. Clear out-of-catalog appearances return `no_match`; glare or
covered texture returns `uncertain` and enters a simulated review queue.

The authored PNGs are synthetic textures, not photographs. Matching visible appearance does
not establish fiber, chemistry, durability, fire rating, or purchasing suitability. Python
can log a simulated visual candidate; it cannot place an order or approve a substitution.

## Run offline

From the repository root in the cookbook environment:

```bash
python recipes/74-material-swatch-matching/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/74-material-swatch-matching
python tools/execute_notebook.py recipes/74-material-swatch-matching
pytest recipes/74-material-swatch-matching
```

There are 30 deterministic 384 × 320 PNGs: four controlled references and 26 independently
rendered query images. Twelve validation and twelve held-out test examples have readable
gold labels; two unscored examples demonstrate the typed answer. Query paths, labels, split
names, and drawing parameters are absent from inference state. Content-based references bind
the actual query and reference bytes into replay identity. No external image source is used.

## Policy and comparison

Validation chooses the lowest eligible confidence that reaches 90% accepted accuracy among
non-uncertain answers, then freezes it. `uncertain` always defers; `no_match` passes the same
confidence gate as any candidate. The notebook measures actual accepted decisions with
`evaluate_outcomes`, counting review as abstention. A deliberately confident wrong texture
match survives the frozen gate in the synthetic held-out test.

The deterministic baseline reads the identical five images per query. It compares mean RGB,
mean edge magnitude, and luminance contrast with fixed feature weights. Fixed highlight and
low-contrast checks defer visibly obscured queries. Validation alone chooses a nearest-reference
rejection radius from five declared candidates, maximizing correct accepts minus three times
wrong accepts, with smaller-radius tie breaking. It is a modest appearance baseline, sensitive
to lighting and pattern scale; no label or drawing metadata reaches it.

## Switch to live

Not measured live. The committed metrics are synthetic pipeline checks, not Jev quality results.
Inference latency, tokens, and cost are unknown (`None`). Image functionality is experimental.
The same questions can run with `images=True` and pinned `jev-1.14.0`; see
[the live workflow](../../docs/live.md). The notebook makes exactly 26 calls, one per example,
caches answers, and submits five images in each call. Set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` or higher for a live notebook run; retry attempts also
consume the budget. The executor always runs offline. Unrecorded live exploration suppresses
held-out aggregate reporting.

For a deliberate capture, use the recorder with the same request triples. This snippet is
opt-in and is not executed by the notebook:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
requests = [helpers.build_request(e.fields) for e in load_inputs()]
backend = LiveBackend("jev-1.14.0", images=True, max_requests=26, max_retries=0)
record(backend, requests, Path("capture/responses.json"), ledger_path="capture/ledger.json")
```

The recorder stores the returned model, capture date, and reported usage, and the ledger keeps
request identifiers. Record actual inference latency separately if measured. Do not infer latency from replay or
invent a bill. Inspect the capture before replacing synthetic fixtures; the generator refuses
to overwrite recorded answers without `--force`. Freeze a policy on recorded validation before
opening recorded test results. This synthetic exercise does not calibrate a policy for real photos.

## Next steps

Try independently photographed swatches under controlled white balance, including unknown
materials and occluded samples. Use [abstention and review queues](../38-abstention-and-review-queues/)
to explore the deferral policy and [sentiment classification](../01-sentiment-classification/)
for the basic typed-choice evaluation pattern.

## Sources

- S02: [TypeSafe primitives](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe images](https://docs.typesafe.ai/images)
- S11: [TypeSafe models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
