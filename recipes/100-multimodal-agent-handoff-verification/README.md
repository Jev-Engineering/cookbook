# Multimodal agent handoff verification

**Recipe 100** · Level 4 (Advanced) · `Choice` + `Noul` + images

Check an export-producing agent's report against a screenshot and tool record before a simulated export-analyzing agent can receive the artifact. One `Choice` classifies the report; three independent `Noul` claims check visible completion, tool-output completion and artifact identity. All four independent judgments share one request. Python owns the recipient/operation allowlist, evidence freshness, capture provenance, task/attempt identity, current revision, exact tool preconditions, budgets and duplicate suppression.

Every declined handoff enters `ReviewQueue`. Every permitted handoff enters `ActionLog` with `executed=False`; no real action or second agent runs. Report, tool-output and on-screen instructions remain data. Collector identifiers stand in for trusted harness metadata and are not cryptographic authentication.

## Run offline

From the repository root in the documented development environment:

```bash
python ./recipes/100-multimodal-agent-handoff-verification/build_fixtures.py
python -m jev_cookbook.fixtures validate ./recipes/100-multimodal-agent-handoff-verification
python tools/execute_notebook.py ./recipes/100-multimodal-agent-handoff-verification
python -m pytest ./recipes/100-multimodal-agent-handoff-verification
```

The notebook uses its recipe folder as working directory. Reproducing committed outputs requires Python 3.14 and `pip install -e ".[ml]" -c .github/constraints-notebooks.txt`; tests and lint use the development extras. See [development](../../docs/development.md) and [recipe template](../../docs/recipe-template.md). `build_fixtures.py` redraws the synthetic images and rebuilds inputs and labels. It refuses to replace recorded responses unless explicitly passed `--force`.

## What was measured

**Synthetic fixtures; not measured live.** There are 12 validation examples, 12 held-out test examples, and two unscored demonstrations: 26 distinct screenshots at 480 × 360, 26 requests and 104 bounded question answers. Screenshots are authored UI drawings; no real browser or customer data is included.

Validation chooses from confidence thresholds 0.40, 0.65 and 0.85 by maximizing actual handoff coverage subject to zero false handoffs on that sample; the frozen threshold is 0.65. The 120-second evidence age limit is a fixed application precondition. On the 12 synthetic test examples the gate hands off five, with four correct and one deliberately confident wrong artifact match; seven go to review. The pixel-and-structured-record baseline hands off six, with three correct. These are pipeline checks, not Jev quality results. Review never counts as coverage. The notebook reports actual accepted flags through `evaluate_outcomes` and next-step agreement over the full sample.

Hard cases include partial completion under a green banner, mismatched artifact identity, stale successful records, conflicting screen/tool outcomes, untrusted capture origin, changed current revision, ambiguous pixels, visible text injection, malicious report/tool instructions and a benign quoted warning. The baseline reads actual banner pixels plus exact structured records, never gold labels or drawing metadata. Its fixed color rule misses a muted theme and cannot read an artifact name. Unknown model, tokens, latency and cost remain `None` in synthetic accounting. Small drawings and synthetic probabilities establish no real-world robustness or safety guarantee.

## Switch to live

The same request definitions work with pinned `jev-1.14.0` and `images=True`; long context is unnecessary. Install the optional live SDK and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1`, `JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0` and `JEV_COOKBOOK_LIVE_MAX_REQUESTS=32` in your environment. The notebook makes exactly 26 calls, one per example, so the default live budget of 25 is insufficient. The local application budget is 26 logical requests; the backend counts all HTTP attempts, including retries, against its separate limit. Nothing is recorded automatically by opening the notebook live, and the notebook suppresses held-out metrics for unrecorded live exploration.

To deliberately capture all the same request triples, run from this recipe folder with live opt-in enabled:

```python
from pathlib import Path

from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs, responses_path

helpers = load_helpers()
backend = get_backend(fixtures=responses_path(), images=True, model="jev-1.14.0")
assert backend.mode == "live"
requests = [helpers.build_request(example.fields) for example in load_inputs()]
Path("recordings").mkdir(exist_ok=True)
report = record(
    backend,
    requests,
    Path("recordings/responses.json"),
    ledger_path=Path("recordings/ledger.json"),
)
print(report)
```

The recorder stores the actual returned model, UTC capture date and available input/output token counts. The optional ledger retains request identifiers and attempt counts outside strict `fixtures/`. This recipe does not time inference or measure billing; latency and cost remain `None` unless independently captured at inference time. Never substitute replay timing. Recording to a separate directory avoids mixing synthetic and recorded responses. A maintainer can validate and deliberately promote the complete recording to `fixtures/responses.json`, then replay the notebook offline; update the README with returned model, capture dates and N before reporting any held-out recorded result. See [live recording](../../docs/live.md) and [offline/live disclosure](../../docs/offline-and-live.md).

## Continue

The earlier [tool outcome verification](../29-tool-outcome-verification/) develops text-only outcome interpretation; [sentiment classification](../01-sentiment-classification/) introduces validation and uncertainty-aware evaluation. A dependent follow-up inspection must be a separate request after its prerequisite answer, with its own budget and replay key.

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
