# Board-game piece recognition

**Recipe 72 · Level 2 (Easy) · `Choice` with image criteria**

Identify one fictional token, tile, figurine or card from five fixed reference drawings.
Each category includes its actual reference image in `Choice.criteria`; `unknown` covers
unfamiliar, empty, covered or multiply occupied crops. Python owns the catalog, confidence
policy and simulated `ReviewQueue`. Recognition never changes a board, moves a piece or scores a game.

The notebook shows the reference catalog, a query and its typed answer before evaluation.
It selects two thresholds on validation, freezes them, and compares the authored Choice
responses against a deterministic rotation-bank, color and shape nearest-reference baseline
on the same held-out crops. Actual routing outcomes determine acceptance and abstention.
A deliberately confident ring-token/sun-token error survives the frozen gate.

## Run offline

From the repository root in the development environment:

```bash
python recipes/72-board-game-piece-recognition/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/72-board-game-piece-recognition
python tools/execute_notebook.py recipes/72-board-game-piece-recognition
pytest recipes/72-board-game-piece-recognition
```

The notebook runs from its folder. Pillow creates all artwork locally; no network or key is
needed. There are **31 original 384 × 320 PNGs**: five shared reference designs and 26 distinct
query crops. Queries include rotation, scale, perspective, lighting, similar amber tokens,
partial clipping, covered symbols, stacked pieces, an unfamiliar star, empty crops and printed
instruction-like text. This is synthetic illustration, not real photography or licensed art.
`ROWS` in `build_fixtures.py` is the readable authoring record; parameters and gold labels
are never inference inputs. The generator reproduces assets and fixtures and refuses to
replace recorded responses without `--force`.

## Switch to live

**Not measured live.** The committed run contains only authored synthetic answers. Every
metric checks the pipeline; it is not evidence about Jev quality. N = **12 validation +
12 test**, with **2 additional unscored demos**. Model, date, inference latency, usage and
cost are unknown for synthetic inference and reported as `None` where applicable. Tiny,
related synthetic designs cannot establish accuracy on real components, glare, wear or boards.

Follow [live setup](../../docs/live.md), install the optional live SDK and keep the API key
only in the environment. For interactive exploration set `JEV_COOKBOOK_LIVE=1`,
`JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0` and `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` or higher.
The notebook explicitly pins `jev-1.14.0` and enables `images=True`; the question builder
is identical in both modes. It makes exactly **26** requests, one per query, with six images
each and no dependent stages. The default request budget of 25 is insufficient; retries also
consume the configured budget, so 26 permits a complete run only without retries. Results
are cached by the replay key of freshly rebuilt state, questions and image assets. Unchanged
evidence reuses a result; changed pixels or context require a new request even under the same
example identifier. An unrecorded live run is exploration, not a reported result.

To capture the same requests, run this deliberately from the recipe folder after configuring
your key. Use a fresh output file so synthetic and recorded responses never mix:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
triples = [helpers.build_request(e.fields) for e in load_inputs()]
report = record(
    LiveBackend("jev-1.14.0", images=True, max_requests=26),
    triples,
    Path("recordings/responses.json"),
    ledger_path=Path("recordings/ledger.json"),
)
```

The recorder retains actual returned model, date and reported usage. Its ledger retains
request and retry records outside `fixtures/`. To replay a completed capture, review it and
replace `fixtures/responses.json` as a deliberate dataset update; keep an untouched test set
when tuning policy. The recorder does not supply inference latency or billing: measure and
retain those separately, otherwise leave them `None`. See [offline and live](../../docs/offline-and-live.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)

Local Codex implementation; genuine Opus review and the repository merge gate remain pending.
Only this recipe folder is authored here; catalog integration belongs to the designated integrator.
