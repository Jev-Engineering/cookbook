# Reference-guided object search

**Recipe 82 · Level 3 (Intermediate) · `Box` + `Noul`**

Locate a fictional bottle on a cluttered shelf using its reference image directly in the Box instructions. The reference portraits and shelf scenes are authored **synthetic drawings**, not photographs. They exercise the workflow intended for independent product photos and shelf photos.

## What it teaches

Two Noul propositions share one request: a matching product is present, and exactly one instance is visible. Python requires both probabilities to reach 0.8 before asking for a Box. Both at or below 0.2 resolve absence; other combinations defer. Box always returns coordinates, so absence and ambiguity must be handled separately. Missing Box confidence also defers. Python permits at most two logical requests per scene, performs exact geometry, and records only simulated highlights or pending reviews.

The notebook displays the reference, shelf and typed answers before evaluating anything. Validation selects the Box confidence gate from observed confidences with `target_accuracy=1.0` on eligible validation boxes. A real RGB template matcher supplies the baseline: it reads only the reference and scene pixels, searches three scales, suppresses overlapping peaks, and defers on multiple matches. Its error tolerance minimizes `3 × accepted errors + reviews` at at least 50% validation coverage. Both settings freeze before test evaluation.

There are 26 query scenes, three independently drawn reference portraits, 12 validation labels, 12 test labels and two unscored demos. Cases include rotation, scale change, partial occlusion, dim light, near-identical emblems, absent products, multiple matches and misleading instructions printed in the scene. Query images are distinct across splits; the known reference catalog is intentionally shared. Gold geometry and scene construction data never reach inference. Confident wrong test answers survive the frozen policy.

## Run it offline

From the repository root, with the development and notebook dependencies described in [development](../../docs/development.md):

```bash
python recipes/82-reference-guided-object-search/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/82-reference-guided-object-search
python tools/execute_notebook.py recipes/82-reference-guided-object-search
python -m pytest recipes/82-reference-guided-object-search -q
```

The generator uses Pillow and reproduces all images and fixture bytes. It refuses to overwrite a recorded responses file without `--force`, while regenerating the authored inputs and labels. The notebook uses NumPy, Pillow, Matplotlib and `jev_cookbook`; no API key or network is needed offline.

## Switch to live

Not measured live. The same question definitions work with `get_backend(images=True, model="jev-1.14.0")`. Follow [live setup](../../docs/live.md) to install the optional SDK and provide the environment opt-in and your own key. This recipe pins `jev-1.14.0` and enables the experimental images header. No key belongs in committed files. The notebook executor always runs offline.

The committed notebook performs **43 conditional logical requests**, reusing evidence for displays and evaluation. The inventory contains **52 distinct stage responses**, including counterfactual Box answers for scenes whose screening blocks localization. Other answers can change the notebook's request count; its ceiling is 52 logical requests. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=52` or a deliberate larger attempt budget if allowing retries. Each retry spends another attempt; direct live execution is unrecorded exploration and yields no reportable held-out claim.

For a deliberate exhaustive experiment, a fresh capture makes exactly **52** calls when all succeed with retries disabled. This captures the full inventory, including counterfactual boxes; it does not authorize accepting those boxes. Run the following only after explicit live opt-in, from this recipe folder. Keep the capture separate until reviewed; never merge synthetic and recorded responses in one file.

```python
from pathlib import Path
from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
backend = get_backend(fixtures=Path("fixtures/responses.json"), images=True, model="jev-1.14.0")
if backend.mode != "live":
    raise RuntimeError("Recording requires an explicitly opted-in live backend")
backend.max_retries = 0
triples = [
    helpers.request(e.fields, stage=stage) for e in load_inputs() for stage in ("screen", "box")
]
Path("capture").mkdir(exist_ok=True)
report = record(
    backend, triples, Path("capture/responses.json"), ledger_path=Path("capture/ledger.json")
)
```

The recorder saves the returned model, capture date and reported usage, and its sidecar accounts for attempts. Inference latency and measured charges remain unknown unless measured during capture. Replace the synthetic response file only with a reviewed complete recording; replay it under the frozen protocol to report that held-out sample. Revising prompts or policies after inspecting test failures requires a new holdout.

## What was and was not measured

**Mode: synthetic. N: 12 validation, 12 test, two demo. Not measured live.** All numbers are checks of the authored pipeline, not Jev quality claims. The notebook reports actual accepted flags, review counts, accepted accuracy, coverage, resolved-scene IoU, missed targets, absent-scene false positives, separate multiple-instance counts, and delivery IoU over all uniquely present targets (zero for any undelivered box, including review). Reviews are excluded from localization scoring and counted explicitly, never relabeled absent. The pixel baseline sees the same images and labels are used only for selection/evaluation.

Model, tokens, inference latency and cost remain `None` for replay. Synthetic images omit camera noise, depth, realistic lighting and the diversity of commercial packaging. The plain-background, upright pixel template is a deliberately limited comparator. A confident reference mismatch can pass every gate; the simulated highlight is not a safety guarantee or a physical picking instruction.

## Next steps

Read [abstention and review queues](../38-abstention-and-review-queues/) and [sentiment classification](../01-sentiment-classification/) for selection and deferral patterns. See [vision helpers](../../docs/vision.md) for coordinate and localization metric contracts. Replace the drawings with licensed independent photos and fresh annotations before making any real model measurement.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S10: [TypeSafe AI: Box](https://docs.typesafe.ai/primitives/box)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
