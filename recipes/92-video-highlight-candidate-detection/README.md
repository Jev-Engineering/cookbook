# Video highlight candidate detection

Recipe 92 · Level 3 (Intermediate) · Multiframe `Score`.

Score three independent visible signals in ordered frame windows: newly raised arms, persistent setting replacement, and a new game victory overlay. Python samples actual timestamps, combines scores, freezes a validation-selected confidence gate, compares a pixel-difference baseline, and ranks a capped simulated editorial shortlist. The posture score describes visible arms; it does not infer emotions or intent.

The original illustrations contain readable people, a desk room, an outdoor stage, and a fictional game. They include ordinary footage, camera-angle cuts, flashes, occlusion, transient signals, pre-existing signals and misleading trophy advertisements. There are **26 windows, 130 PNG frames (480 × 360), 24 readable event annotations, and 26 response records**: 12 validation, 12 test, and 2 unscored demonstrations. Each request samples three of five source frames and batches three Score questions. No real video or personal imagery is included.

## Run offline

From the repository root, use the notebook constraints when preparing an environment:

```bash
python -m pip install -e '.[ml]' -c .github/constraints-notebooks.txt
python recipes/92-video-highlight-candidate-detection/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/92-video-highlight-candidate-detection
python tools/execute_notebook.py recipes/92-video-highlight-candidate-detection
python -m pytest recipes/92-video-highlight-candidate-detection -q
```

The notebook runs from its recipe directory, needs no key or network, and shows the source frames and typed answers before aggregate metrics. `build_fixtures.py` reproduces the drawings, manifests, annotations and synthetic probabilities. As in the cookbook scaffold, inputs and labels are always regenerated; drawings are regenerated too. The script refuses to replace recorded `responses.json` without `--force`. After changing source drawings or questions, a refused rebuild can leave new keys beside old responses: preserve a separate recorded corpus and re-record deliberately, rather than treating that refusal as rollback of the whole folder.

## Policy and evaluation

The fixed 2.4/3 score boundary encodes a persistent highlight signal. Python takes the maximum score and the minimum confidence across the three questions. Validation selects the lowest observed confidence yielding perfect raw event accuracy; a separate [0,1] pixel-difference threshold maximizes validation F1 over observed differences. Both thresholds freeze before test. Scores in [1.5, 2.4) remain explicit review even with high confidence. Low scores become `none_suitable` only after the same confidence gate.

All metrics are **synthetic pipeline checks**, not evidence of Jev quality. Test reporting uses the same windows for both methods and prints N, event accuracy, resolved accuracy, abstention, missed events and false candidates. Actual acceptance flags feed `evaluate_outcomes`. The independent event annotations include visible event intervals; the proposed clip includes the opening lead-in frame rather than claiming an exact detected onset. Two accepted held-out mistakes deliberately survive the frozen gate. A three-item shortlist affects editorial suggestions, not classification denominators. Actions stay in `ActionLog` with `executed=False`; deferred judgments stay in `ReviewQueue`.

## Switch to live

**Not measured live.** Image support is experimental. Install the live extra, opt in with `JEV_COOKBOOK_LIVE=1`, provide `TYPESAFE_API_KEY` outside the notebook, and set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` or higher to allow for retries. The requested model is pinned to `jev-1.14.0` and `images=True` enables the image header. The notebook makes exactly **26** calls in a complete successful run; cached redisplays add none. Its local cap limits unique semantic attempts to 26. The backend's HTTP-attempt budget also counts retries; fewer successes are possible if attempts fail.

Live notebook execution is exploration: held-out aggregate reporting is suppressed until answers are captured and replayed. `tools/execute_notebook.py` always strips live environment variables. To record separately, run this explicit snippet from the recipe folder with credentials already configured:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
requests = [helpers.request(e.fields) for e in load_inputs()]
backend = LiveBackend("jev-1.14.0", images=True, max_requests=30)
report = record(
    backend,
    requests,
    Path("capture/responses.json"),
    ledger_path=Path("capture/ledger.json"),
)
```

The request triples bind every image byte. The recorder keeps actual returned model, capture date and reported token usage; inspect and validate that captured corpus before replacing the replay file. Retain an untouched test set when revising any policy. Unknown latency, tokens and billed cost remain `None`; replay runtime is not inference latency. No live calls were made for this recipe, and no recording is committed.

## Limits and next steps

This lesson begins with timestamped extracted stills. A real decoder must preserve presentation timestamps and upright PNG/JPEG pixels. Sparse sampling can miss short events; these drawings do not represent real camera motion, footage diversity, emotion, or editorial quality. Add independent footage annotations and a separate untouched test set before changing the sampler or choosing a real editing policy. Continue with [response clarity scoring](../03-response-clarity-scoring/) and [incident priority composition](../24-incident-priority-composition/).

Only this recipe folder is authored here. Root catalog rendering belongs to integration. Local Codex implementation and checks do not replace the required Opus review and final main CI gate.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
