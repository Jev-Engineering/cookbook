# Long-context versus focused-context evaluation

**Recipe 98 · Level 5 (Expert) · `Choice`, `Noul`, `Score`, `Box`**

Compare full document context, deterministic word-overlap retrieval, and a bounded document-selection
step on identical labeled multimodal tasks. The final questions, images, model, task IDs, splits,
and gold stay fixed. Python chooses retrieval depth and a common confidence gate on validation,
freezes them, and evaluates held-out test once.

The corpus contains 17 authored inspection tasks: 8 validation, 8 test, and 1 unscored demo.
Seventeen Pillow-generated PNGs are 384 × 320 pixels. Stale notes, paraphrased evidence, conflicting
active notes, missing evidence, a cyan decoy, and deliberately wrong synthetic answers make the
comparison inspectable. The four final judgments concern note/image agreement, visible presence,
obstruction level, and crate location. Presence gates boxes; unknown Box confidence causes review.

**Not measured live.** The committed notebook replays synthetic answers. Its accuracy, review,
IoU, and error figures are pipeline checks. API token counts, inference latency, cost, model,
and capture dates are unmeasured. This small corpus does **not** reach or measure 262K tokens.

## Run offline

From the repository root, with the cookbook development dependencies installed:

```bash
python -m jev_cookbook.fixtures validate recipes/98-long-context-versus-focused-context-evaluation
python tools/execute_notebook.py recipes/98-long-context-versus-focused-context-evaluation
pytest recipes/98-long-context-versus-focused-context-evaluation
```

The executor always runs offline. See [development](../../docs/development.md) and
[notebook setup](../../docs/recipe-template.md) for the pinned environment. Run
`python build_fixtures.py` from this folder to reproduce the authored data and images.
The builder regenerates inputs, labels, and authored assets from `ROWS` on every run. It refuses
to overwrite recorded responses without `--force`; a refused run preserves that response file.
Changing the authored rows can therefore leave regenerated inputs awaiting matching responses.
Assets live beside `fixtures/`; only the three fixture JSON files live inside it.

## Switch to live

No live calls were made to build this recipe. A reader who chooses to record installs `.[live]`,
provides `TYPESAFE_API_KEY` through their environment, and sets `JEV_COOKBOOK_LIVE=1`.
The notebook pins `jev-1.14.0` and enables the experimental images and long-context headers.
Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS` deliberately: the complete small run makes exactly **73**
requests without retries (1 demo + 40 validation + 32 test), above the backend default of 25.
The response fixture contains **70 unique replay keys**. Three requests recur across comparison
arms and remain independent calls; unique-key count is not the live request budget.
`JEV_RECIPE98_MAX_RETRIES` defaults to 0 and is configurable; retries consume the same backend's
attempt cap. A capped or failed run stops and preserves its paid-call evidence.

Set `JEV_RECIPE98_CAPTURE_DIR` to a new local directory, outside `fixtures/`. The notebook uses the
shared recorder and writes `responses.json`, `request-ledger.json`, and `run-record.json`.
The last file preserves every call's actual typed response, elapsed inference time, returned model,
capture date, and successful-response usage, including distinct answers to identical requests in
different arms. Failed attempts may consume tokens without returning usage. Resource summaries
therefore separate successful-response tokens from complete arm totals: total tokens and cost stay
null if any call retried or its attempt count is unknown. Missing usage also keeps that token total
null. Cost additionally requires actual billing evidence for every single-attempt call; this capture
format does not establish billing across retries. Attempt counts and elapsed inference time still
include retries. Replay time is never treated as inference latency; character length and external
token preflight counts are never API usage.

The request cap is local to one backend and **does not enforce a cumulative dollar budget**.
A campaign using an existing cumulative authorization must reserve this run through its budget
orchestrator before opting in. This notebook neither resets that authorization nor substitutes
an unverified local receipt for it.

To replay your captured comparison, unset `JEV_COOKBOOK_LIVE` and set:

```bash
export JEV_RECIPE98_RESPONSES=/path/to/capture/responses.json
export JEV_RECIPE98_RUN_RECORD=/path/to/capture/run-record.json
```

Open the notebook directly in Jupyter from this folder. Its sidecar is required for recorded
comparisons: a map containing only one answer per replay key cannot preserve different live
answers to identical requests across arms. These environment overrides are intentionally removed
by the cookbook's offline executor.

## Prepare a larger workload

The documented opt-in ceiling is 262K tokens per request and question
([S11](https://docs.typesafe.ai/models)). `prepare_workload.py` appends deterministic archive notes
while preserving the underlying labeled tasks. Supply a whole-request counter that accepts
`(state, questions, assets)` and identifies its tokenizer/version and image assumptions:

```bash
python prepare_workload.py --counter my_counter:count_request \
  --counter-id 'my-tokenizer-version; documented image assumptions' \
  --target-tokens 250000 --out captures/large-workload.json
```

This local generator makes no inference calls. Its bounded search assumes counts increase
monotonically as notes are appended, retains a configurable reserve below the ceiling, and
records both workload identity and external-count provenance. Set `JEV_RECIPE98_WORKLOAD` to the
manifest explicitly for a larger live run or its recorded replay. All three arms receive the
same generated corpus. Missing replay responses fail clearly.

External counts are preflight information. The notebook prints each full-context successful
response's **server** input-token count only when recorded; those counts, including the actual
distance from the intended scale, are necessary before describing a near-262K comparison.
This recipe supplies no unofficial token estimator and makes no token claim from character length.

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S10: [Box](https://docs.typesafe.ai/primitives/box)
- S11: [Models and long context](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)

Continue with [semantic context paging](../46-semantic-context-paging/) and
[multi-agent task assignment](../49-multi-agent-task-assignment/). The
[contribution contract](../../CONTRIBUTING.md) governs publication; a designated integration
worker regenerates the root README. Genuine required review and merge checks remain separate
from this local recipe build.
