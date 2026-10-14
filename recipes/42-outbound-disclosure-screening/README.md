# Outbound disclosure screening

**Recipe 42** · Level 4 (Advanced) · Decision type: `Noul`

Screen proposed outbound messages for disclosure concerns against supplied sharing rules while deterministic controls hold flagged or uncertain samples for review.

## What it teaches

Jev answers two independent `Noul` propositions per proposed outbound message, sent together in one request -- the sharing rules supplied for this recipe, each a statement that can be true or false, never a question. Python owns everything else: a business threshold and a confidence gate chosen per rule, then pooled across both rules into one shared gate (`jev_cookbook.evaluation.pool_label_decisions`), a deterministic policy that holds every later message in a thread once an earlier one in it was held, and the final `held`/`allowed` decision. The evaluation reports a missed-disclosure rate, a false-hold rate, and an overall hold rate, for the full pipeline against a baseline that uses the identical business thresholds and the identical number of requests but neither the confidence gate nor thread escalation -- so what each deterministic control buys (and what it does not) is visible rather than assumed. Nothing is ever sent: `allowed` means a message cleared every check in a simulation that executes no action.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/42-outbound-disclosure-screening
python tools/execute_notebook.py recipes/42-outbound-disclosure-screening
pytest recipes/42-outbound-disclosure-screening
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — `.[dev]` above is for `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline. The live backend's default request budget is 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)); every attempt counts
against that budget, including each retry. In live mode this notebook makes exactly one call for
each of the 35 messages in `fixtures/`, and no other (every message is decided once and the
stored answer is reused wherever it is shown again). That is more than the default budget, so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=35` or higher before running this notebook live, or it stops
partway through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other
committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 16 `validation` and 16 `test` messages are scored (35 in the fixtures; the 3 `demo`
  messages are shown in the notebook but never scored). Scored rows, requests, questions and
  task-level units are four different quantities for this recipe (one battery of 2 questions per
  message, in one request): 32 scored rows, 32 requests overall (16 per split), 64 scored
  questions (32 per split), 32 task-level held/allowed decisions (16 per split). The notebook's
  evaluation section states which quantity each number it prints is over.

The committed run replays 35 invented messages with hand-written (synthetic) answers, some wrong
on purpose: a message that embeds an instruction trying to steer the screen into clearing it
despite stating an unpublished price (one per split, stored confidently wrong, well clear of the
confidence gate -- the gate cannot catch a confident mistake, only genuine ambiguity), a genuine
business-rule miss on each rule (one per split per rule), two messages that merely resemble a
violation without being one (one per split per rule, close enough to the gate's band that it
reviews them), two messages held only because their confidence sits inside the gate's band (one
per split), and a two-message thread per split where the second message is clean on its own
content and held only because the first message in its thread already was. Its missed-disclosure
rate, false-hold rate, hold rate, and the pooled confidence-gate curve check that the pipeline
works; they say nothing about how Jev performs, how fast it is, or what it costs. This recipe has
no recorded fixtures. `allowed` means this pipeline found nothing to hold a message for; nothing
in this recipe ever actually sends anything, in any outcome.

## Pull request rules

This recipe's pull request changes only `recipes/42-outbound-disclosure-screening/`. The root `README.md` is generated; per
the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by
a separate pull request, and this recipe's own builder never runs the renderer. While this recipe
remains unpublished and that integration step has not yet run, `Catalog (README is current)` is
expected to be red on its pull request, which is not a defect to fix here; once the catalog is
regenerated for it, the check turns green and stays that way. No sentence anywhere in this
folder states or implies Jev's real quality, latency, or cost: every number above is a synthetic
pipeline check. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
