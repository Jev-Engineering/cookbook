# Retrieval pipeline evaluation

**Recipe 52** · Level 4 (Advanced) · Decision type: `Choice` + `Score`

Combine passage filtering, reranking, and claim verification in a retrieval pipeline and measure each stage's effect on answer support using a fixed labeled corpus.

## What it teaches

A retrieval pipeline with three stages whose effects are measured one at a time. Python owns the
candidate list (it removes a passage that repeats an earlier one), every cut (the filter's drops and
the top-k cut) and the composition of requests. Jev answers narrow typed questions about one
claim: a `Choice` that filters out passages that do not bear on the claim, a `Score` rubric that
reranks the survivors, and a `Choice` verdict (`supported`, `contradicted` or the fallback
`not_enough_evidence`) over the evidence that is left. The filter and the rerank question are
independent, so they share one request per passage; the verdict reads the evidence those answers
chose, so it is a later request, and the notebook shows that boundary on a hard case where the
second of two facts a claim needs is a passage the filter leans towards dropping.

The evaluation is an ablation over a small labelled corpus of invented examples (3 `demo`, 8
`validation` and 10 `test`) with decoys that share words with the claim, a claim that only two
passages show together, contradicting passages, a mirrored pair of passages and claims no passage
settles. Four configurations (no stages, filter, rerank, filter and rerank) are each scored by
answer-support rate and evidence recall, with the number of requests each makes counted by the
audited backend. A confidence gate on the verdict, frozen on `validation` with
`select_confidence_threshold`, sends low-confidence verdicts to review with the reason
`confidence below the threshold`; a configuration whose filter leaves no evidence makes no verdict
request and reports a review instead.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/52-retrieval-pipeline-evaluation
python tools/execute_notebook.py recipes/52-retrieval-pipeline-evaluation
pytest recipes/52-retrieval-pipeline-evaluation
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
and always runs offline.

<!-- request-budget:begin -->
In live mode this notebook makes exactly **215** requests, of which 202 are distinct (the other 13 repeat a request on purpose). Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=215` or higher before running it live (the default cap is 25): the cap is inclusive and every attempt counts against it, retries included, so a lower cap stops the run partway through with `BudgetExceeded` and a run that retries needs more.
<!-- request-budget:end -->

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 8 `validation` and 10 `test` examples are scored (the 3 `demo` examples are shown in the
  notebook but never scored).

Not measured live. The committed run replays invented claims and passages with hand-written
(synthetic) answers, including verdicts written from how much of the gold evidence reached the
verifier, several wrong on purpose and one wrong *and* confident on `test` (`t08`) so the gate's
numbers show a real, non-zero risk. Its answer-support rates, evidence recall, coverage and request
counts check that the pipeline works (the candidate list, the cut, the composition, the gate and
the counting); they say nothing about how well Jev filters, reranks or verifies, how fast it is,
or what it costs. The request counts are counts of requests, not tokens, time or cost. This recipe
has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/52-retrieval-pipeline-evaluation/`. The root `README.md` is generated; per
the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by
a separate pull request, and this recipe's own builder never runs the renderer. While this recipe
remains unpublished and that integration step has not yet run, `Catalog (README is current)` is
expected to be red on its pull request, which is not a defect to fix here; once the catalog is
regenerated for it, the check turns green and stays that way. No sentence anywhere in this
folder states or implies Jev's real quality, latency, or cost: every number above is a synthetic
pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
