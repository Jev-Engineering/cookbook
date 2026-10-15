# Signature and stamp localization

**Recipe 78 · Level 3 (Intermediate) · `Noul` + `Box`**

Locate one requested handwritten signature mark or APPROVED stamp in an authored
synthetic document. Two batched Noul propositions check presence and uniqueness.
Python gates a dependent Box request, converts normalized edges to exclusive pixel
bounds, and simulates a crop. A missing confidence value, uncertain presence or
multiple plausible marks goes to review. No approvals are issued; this example
neither identifies signers nor authenticates documents.

The notebook includes rotated marks on upright pages, a blank signature line, a
printed name, decorative seals, duplicate approval stamps, an occluded signature,
a partial scan and black ink. Names are fictional; signatures are meaningless
mathematical scribbles. All 26 images are deterministic 600 × 760 PNG drawings;
[`assets/README.md`](assets/README.md) records their provenance.

## Run offline

From the repository root with the cookbook development environment:

```bash
python recipes/78-signature-and-stamp-localization/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/78-signature-and-stamp-localization
python tools/execute_notebook.py recipes/78-signature-and-stamp-localization
pytest recipes/78-signature-and-stamp-localization
```

To reproduce committed notebook output, use Python 3.14 and install `.[ml]` with
`.github/constraints-notebooks.txt`, as explained in
[development](../../docs/development.md). No network or key is needed for replay.
The generator regenerates images, inputs and labels, but refuses to overwrite
recorded responses without `--force`.

## Policy and evaluation

Twelve validation documents select from nine combinations of presence probability
and Box confidence thresholds. The objective is correct resolved answers minus
twice the number of wrong crops; ties prefer more correct answers and then higher
thresholds. Validation selects presence 0.90 and Box confidence 0.85 in this
synthetic run. Twelve held-out test documents use that frozen policy once. Two
unscored documents demonstrate the typed answers and ambiguity handling.

The baseline uses the same files, searches only the lower half of each page, and
selects the largest blue or red connected ink component. It reads no labels.
Evaluation reports actual resolution coverage, accuracy among resolved answers,
review counts, IoU including zero-valued misses, absent false positives and
ambiguous crops. The held-out fixture intentionally retains a confidently wrong
box and a decorative-seal false positive after gating. These are synthetic
pipeline checks, not Jev performance estimates.

## Switch to live

**Not measured live.** The committed replay makes exactly 43 calls:
20 validation requests, 20 test requests and three demo requests. There are 26
first-stage requests and 17 dependent Box requests. The notebook's Python budget
is 52 logical requests; a different live answer pattern can use up to 52.
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=52` caps actual live attempts separately, including
retries, so failures can exhaust it before every logical request succeeds.

Images require `images=True`; Box recordings pin `jev-1.14.0`. Installing the live
extra and setting `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0` changes the backend while keeping the question
definitions. Direct live notebook use allows the demos, then stops before
aggregate evaluation: an unrecorded run is exploration, not a reportable result.
The notebook executor always runs offline.

For a reportable experiment, use a new recording file outside the committed
synthetic `fixtures/`. `helpers.record_stage(live_backend, examples, recipe_dir,
responses_file, presence_threshold)` calls the shared
[`record`](../../docs/live.md#recorder) with image-bearing triples. It replays each
actual first-stage answer to decide whether to record Box; it never invents
dependent answers. Use a single pinned
`LiveBackend("jev-1.14.0", images=True, max_requests=52)` instance:

1. Record only validation with presence threshold 0.80, the loosest candidate.
   Replay these records through `observe` and run `select_policy` using validation
   gold labels.
2. Freeze that returned policy. Record the untouched test examples with its
   presence threshold, then record the unscored demos. `record_stage` always uses
   the notebook's fixed demonstration threshold of 0.90 for demo examples,
   independently of the selected policy. Report the test only after capture is complete.
3. Regenerate the input `replay_keys` to list the branches actually captured and
   validate the recorded fixture set. Preserve every paid response. Do not run the
   synthetic generator with `--force` over recordings.

The recorder preserves the model returned by the service, capture date and
reported token usage. Optional capture ledgers belong outside `fixtures/`.
Unreported usage, inference latency and cost remain `None`; replay timing is
never inference timing. See [offline and live](../../docs/offline-and-live.md).

## Limits and next steps

The small, mostly colored-ink drawing set cannot establish performance on real
scans, diverse handwriting or authenticity questions. The crop is an image
location proposal only. Explore [document extraction
cascades](../39-document-extraction-cascade/) and [confidence
gates](../01-sentiment-classification/) next.

This is a local Codex implementation. Genuine Opus review and integration checks
remain pending; the catalog issue is unassigned. The root catalog README is
intentionally left for the designated integration stage.

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S10: [Box](https://docs.typesafe.ai/primitives/box)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
