# Engineering diagram component locator

**Recipe 79 · Level 3 (Intermediate) · `Noul` + `Box`**

Locate a requested valve, flanged connector, or pump symbol in an authored process drawing.
Python fixes the allowed tags, batches presence and unique-binding propositions, requests a
Box only for an eligible target, then converts normalized coordinates into a simulated
annotation. Repeated tags, crossed leaders, missing confidence, and boundary clipping have
explicit review outcomes. These simplified symbols are teaching illustrations with legends,
not engineering standards or operating instructions; no equipment is operated.

The notebook shows drawings, typed answers, a crop, a validation sweep, and a confidently
wrong held-out annotation. A deterministic baseline searches the same pixels for canonical
glyph and text templates, then binds labels using a fixed region above the glyph. It has no
access to labels, fixture IDs, or drawing metadata. Its font, scale, orientation, and label
placement assumptions limit it to this authored drawing family.

## Run it offline

From the repository root, after installing `pip install -e ".[dev]"`:

```bash
python recipes/79-engineering-diagram-component-locator/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/79-engineering-diagram-component-locator
python tools/execute_notebook.py recipes/79-engineering-diagram-component-locator
pytest recipes/79-engineering-diagram-component-locator -q
```

Reproducing committed outputs uses Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`.
The generator writes 26 PNGs, 26 inputs, 24 readable gold labels, and synthetic responses.
It regenerates inputs and labels but refuses to overwrite recorded responses without
`--force`. The fixture folder contains only JSON/JSONL; PNGs live in `assets/`.

## Switch to live

The committed synthetic path makes exactly **44 requests**: 26 batched Noul requests and
18 dependent Box requests. Live answers can change eligibility, so the maximum is 52
successful requests; retries consume additional attempts. Install the optional `.[live]`
extra, set `JEV_COOKBOOK_LIVE=1`, `TYPESAFE_API_KEY`, and
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=60` for a bounded exploratory run. The notebook pins
`jev-1.14.0` and enables `images=True`. Its executor always runs offline.

For a measured capture, use `helpers.record_examples(live_backend, examples, destination,
recipe_dir, threshold)` with the shared recorder. It supplies `(state, questions, assets)`
triples and constructs dependent requests from actual captured first-stage answers. Choose
a fresh destination outside the existing synthetic responses, record validation first,
freeze the gate, and record the held-out split once with that gate. The stored responses
preserve the actual returned model, capture date, and reported usage. Missing token counts,
latency, and billed cost remain unknown. See [recording](../../docs/live.md).

## What was and was not measured

**Mode: synthetic. Not measured live.** N = 12 validation + 12 test diagrams, with two
unscored demonstrations and 26 distinct images. Fixtures include reflow, rotation, repeated
valves, duplicate tags, absent named components, misleading nearby labels, connector versus
junction, clipped symbols, and missing Box confidence.

Validation chooses the lowest observed composite confidence meeting accepted accuracy at
least 0.9, then freezes it before test. Full-policy metrics use actual accepted outcomes;
review does not count as coverage. Localization reports IoU on resolved unique/absent cases,
missed present symbols, false positives on absent targets, required-review violations, and
present symbols left unlocalized including review. The fixture set includes an accepted
wrong-valve box, a connector false positive, and a missed pump after the frozen gate.
All numbers are synthetic pipeline checks, not claims about Jev quality. No inference
latency, token usage, cost, model version, or capture date was measured for this build.

The baseline's assumptions and synthetic fixture distributions cannot establish performance
on real process diagrams. A real comparison needs independently sourced images and gold
annotations, a baseline capable of text and leader recognition, and recorded held-out calls.

[Hierarchical classification](../40-hierarchical-classification/) and
[abstention and review queues](../38-abstention-and-review-queues/) extend the policy pattern.

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S10: [Box](https://docs.typesafe.ai/primitives/box)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
