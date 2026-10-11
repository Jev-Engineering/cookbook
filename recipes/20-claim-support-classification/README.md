# Claim support classification

**Recipe 20** · Level 2 (Easy) · Decision type: `Choice`

Classify whether a provided passage supports, contradicts, or leaves unresolved a specific claim while preserving the passage identifier.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over three fixed options Python builds:
`supports`, `contradicts`, `unresolved`. The question follows TypeSafe's citation-checking
cookbook pattern (S06): one `Choice` named `relation` that asks how a passage relates to a claim,
adapted here so the third option, `unresolved`, is a real outcome of its own rather than a last
resort. Python keeps the passage identifier out of the state entirely and reattaches it to every
result, accepted or sent to review, so a result can always be traced back to the passage it came
from. The one setting Python tunes, a confidence threshold, is chosen on `validation` and frozen
before `test` is touched. The notebook shows typed answers across the hard cases this use case
names (a passage that is on topic but does not settle the claim, a passage that only supports a
narrower version of the claim, a passage that shares the claim's keywords but is about something
else), then an evaluation that checks the stored answers against a majority-label baseline chosen
on `validation`, reports per-class precision, recall and F1 with `unresolved` discussed on its
own, and the coverage, accuracy and risk the frozen threshold buys on `test`, including one
answer that is confidently wrong on purpose.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/20-claim-support-classification
python tools/execute_notebook.py recipes/20-claim-support-classification
pytest recipes/20-claim-support-classification
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — `.[dev]` above is for `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend; the question definition is the same in
both modes. Install the SDK (`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`,
`JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in
Jupyter (not a dependency of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` always removes `JEV_COOKBOOK_*` and
`TYPESAFE_*` from the kernel's environment, so it never runs live and never writes a live outcome
into a committed notebook. In live mode this notebook makes exactly one call for each of the 40
examples in `fixtures/` (each example is decided once and the stored answer is reused wherever it
is shown again), which is above the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)); set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running this notebook live, or it stops
partway through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other
committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored).

The committed run replays 40 invented claim/passage pairs with hand-written (synthetic) answers,
several wrong on purpose, including one wrong *and* confident on `test` (`t16-confident-wrong`) so
the frozen confidence threshold's selective-prediction numbers show a real, non-zero risk rather
than a guarantee that happens to hold. Its accuracy, per-class precision/recall/F1 and the
coverage of the frozen threshold check that the pipeline works; they say nothing about how Jev
performs, how fast it is, or what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe is published: the root `README.md` already carries its generated catalog regions,
from the integration step that ran when this recipe was first merged, per the generated-README
exception in [CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception). A later
pull request that changes only `recipes/20-claim-support-classification/` leaves the root
`README.md` untouched and does not need the renderer run; `Catalog (README is current)` stays
green on such a pull request. No sentence anywhere in this folder states or implies Jev's real
quality, latency, or cost: every number above is a synthetic pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks) — the citation-checking pattern
  (`https://docs.typesafe.ai/cookbooks/citation_check.md`) is the closest worked example: a single
  `Choice` question that decides whether a passage supports, contradicts, or says nothing about a
  claim. This recipe's question is designed from it directly (same question shape, closely related
  option wording), widening the third option from "says nothing" to the use case's own
  `unresolved`, which also covers a passage that only settles a narrower or different claim.
