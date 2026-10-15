# Game HUD perception

**Recipe 80 · Level 4 (Advanced) · `Box` + `Choice` + image**

Locate an energy meter, a card, an action button, or an enemy indicator, then record a simulated
intent only when Python's phase, presence, enabled-state, confidence, geometry, and request-budget
checks pass. A second bounded `Choice` reads an explicitly displayed energy value from `0`–`3`
or returns `unreadable`; Python handles conversion and coordinates.

This is a **Slay the Spire 2-inspired mock HUD**, built from original minimal shapes and invented
card art. None of the images is an actual game screenshot or extracted game asset. The recipe
does not establish support for Slay the Spire 2. It never connects to, clicks, or controls a game.

The notebook first shows typed answers and a drawn rectangle. It then selects a policy on eight
validation captures, freezes it, and evaluates twelve held-out captures once. One additional demo
is unscored. Cases include reflowed HUDs, a hidden meter, occlusion, overlapping distractors,
disabled controls, ambiguous phases, and post-combat rewards. The stored answers deliberately
include confident errors that pass the gates.

## Run offline

From the repository root in the documented development environment:

```bash
python recipes/80-game-hud-perception/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/80-game-hud-perception
python tools/execute_notebook.py recipes/80-game-hud-perception
pytest recipes/80-game-hud-perception
```

Use Python 3.14 and the repository's notebook constraints to reproduce committed outputs. See
[development](../../docs/development.md) and [the template](../../docs/recipe-template.md).
The generator reproduces the 21 original 640 × 400 PNGs under `assets/` and the three JSON fixture
files. It protects recorded or malformed responses unless `--force` is explicitly supplied;
inputs, labels, and assets regenerate independently. Gold presence, phase, enabled state, energy,
and rectangles stay in `labels.jsonl`. Model state contains only the requested target and an
opaque content-addressed image reference.

The fixed-layout Python baseline reads the same pixels with frozen header colors, crop locations,
and energy-slot positions. It receives no labels or layout tags and makes zero model requests.
It is a deliberately narrow baseline for this authored UI, not a general screenshot reader.

## What was and was not measured

**Mode: synthetic replay. Not measured live.** N = 8 validation captures, 12 test captures, and
1 unscored demo. No actual model, capture date, inference latency, input/output token count, or
cost was measured; those accounting values remain `None`. Every score is a synthetic pipeline
check, not evidence about Jev or a real game.

The notebook reports phase/presence accuracy, end-to-end event accuracy, abstention, raw-box IoU,
IoU across required targets including zero for missed targets, and decision-call counts.
An event is correct only when its disposition agrees and, for a simulated intent, its rectangle
has IoU ≥ 0.5 and its energy value agrees where applicable. The evaluation retains a confident
wrong rectangle and a confidently misclassified reward screen: confidence gates enforce supplied
judgments and cannot certify the real screen's phase.

## Switch to live

The backend pins `jev-1.14.0` with `images=True`. Install the optional live dependencies and use
the explicit opt-in described in [live.md](../../docs/live.md); never put a key in a notebook or
fixture. `tools/execute_notebook.py` always runs offline. Image and Box support are experimental.

Each capture uses at most two **decision calls**, including a conditional localization call.
Validation policies share a cache, so identical requests are sent only once. The committed
synthetic path makes exactly **33** calls including the demo; any path through these 21 captures uses at most
42 distinct calls. The live backend's separate global request budget counts transport attempts,
including retries. Its default 25 is smaller than this notebook's synthetic path; a budget of
126 accommodates the maximum 42 calls with up to two retries each. A smaller explicit budget
stops before excess attempts rather than silently finishing. These counts are not latency or cost.

To adapt the recipe, supply screenshots you have permission to use, remove private overlays,
prepare upright PNG/JPEG images within the [image limits](../../docs/vision.md), and author fresh
gold annotations independently. Replace the mock HUD's target descriptions, discrete energy
vocabulary, and fixed-layout baseline on validation data; separate sessions/layouts for test.
Recompute image references and replay keys whenever image bytes or questions change. Freeze the
policy before test and record actual held-out calls before reporting model results. Keep the
`ActionLog` simulation boundary; screenshot perception alone supplies no game-action permission.

## Continue

- [Card-game action selection](../36-card-game-action-selection/) builds legal choices from
  structured game state.
- [Abstention and review queues](../38-abstention-and-review-queues/) explores decisions deferred
  for a person.
- [Vision helpers](../../docs/vision.md) documents image assets, geometry, and honest accounting.

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S10: [Box](https://docs.typesafe.ai/primitives/box)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
