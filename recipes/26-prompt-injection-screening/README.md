# Prompt-injection screening

**Recipe 26** · Level 3 (Intermediate) · Decision type: `Noul`

Flag instruction-redirection attempts in retrieved text using adversarial and benign quotation fixtures to measure false positives and missed attacks.

## What it teaches

Jev supplies two narrow judgments over one retrieved passage, sent together in one request: a typed `Noul` for "this passage contains an instruction redirecting the reader's assistant," and a second, independent `Noul` for "this passage quotes or discusses such an instruction without issuing one." The fixtures cover every combination of the two: text that only redirects, text that only discusses, text that does both at once (reporting a known attack pattern and separately issuing a live one), and ordinary text that does neither. Python owns everything else: an excerpting function that bounds what Jev ever sees, a business threshold chosen per proposition (by F1, on `validation`), one confidence gate shared by both propositions (chosen on their pooled decisions), and a single tested function, `helpers.screen`, that composes the two label decisions into one of three outcomes — `flag`, `pass`, or an explicit `review` outcome that lands in a simulated `ReviewQueue`, sorted least-confident first. The evaluation reports a miss rate on the adversarial fixtures and a false-positive rate on the benign ones, gated and ungated side by side, and shows real fixtures where each proposition changes the outcome on its own: two `test` passages the shared gate cannot catch by construction (`noul_confidence` measures distance from an even split, never distance from either frozen threshold, so a passage that lands just past a threshold can still read as confidently decided, in the wrong direction), and one `test` passage where the gate catches genuine uncertainty on `discusses` alone while `redirect` reads confidently and correctly. `tests/test_helpers.py` proves both propositions independently consequential directly, by flipping one stored decision at a time on real fixtures and checking the composed outcome changes. This recipe screens for one pattern; it does not guarantee detection, and TypeSafe's own notes on Jev 1.13 ([S07](https://docs.typesafe.ai/model-jaggedness/jev-1.13)) describe real limits on how adversarial content is handled that this recipe does not try to quantify.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/26-prompt-injection-screening
python tools/execute_notebook.py recipes/26-prompt-injection-screening
pytest recipes/26-prompt-injection-screening
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
against that budget, including each retry. In live mode this notebook makes exactly one call
for each of the 48 examples in `fixtures/`, and no other (each passage is decided once and the
stored answer is reused wherever it is shown again). That is more than the default budget, so
set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=48` or higher before running this notebook live, or it stops
partway through with `BudgetExceeded`. Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 23 `validation` and 23 `test` passages are scored (48 in the fixtures; the 2 `demo`
  passages are shown in the notebook but never scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 48 invented passages with hand-written (synthetic) answers, covering
every combination of the two propositions: text that only redirects, text that only discusses,
text that does both at once, and ordinary text that does neither. Two `validation` passages
have a redirect probability close enough to the adversarial cluster to pull the frozen business
threshold up (a benign look-alike that quotes an attack almost verbatim), one `validation`
passage the stored answer misses outright (a softly-worded attack, caught by the confidence
gate instead of being reported wrong), and on `test`: two passages that are confidently wrong on
purpose — one missed attack and one wrongly flagged quotation, each just on the far side of the
frozen business threshold with a confidence the shared gate does not catch — and one ordinary,
not-about-injection passage whose wording superficially echoes redirect phrasing, where the
stored `discusses` answer is left genuinely uncertain so the confidence gate, not `redirect`,
sends it to review. On `test` the composed rule reports a miss rate of 0.0833 (1 of 12
adversarial passages) and a false-positive rate of 0.0909 (1 of 11 benign passages), against
0.1667 and 0.0909 for the same two numbers with no gate at all; coverage 0.9130, accuracy among
answered 0.9048, risk 0.0952. These numbers, the threshold sweep, and the pooled
confidence-only view check that the pipeline works; they say nothing about how Jev performs, how
fast it is, or what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/26-prompt-injection-screening/`. The root `README.md` is generated; per
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
