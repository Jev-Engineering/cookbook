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
second of two facts a claim needs is a passage the stored filter answer drops.

The evaluation is an ablation over a small labelled corpus of invented examples (3 `demo`, 8
`validation` and 10 `test`) with decoys that share words with the claim, a claim that only two
passages show together, contradicting passages, a mirrored pair of passages and claims no passage
settles. Four verifier-enabled configurations vary whether filtering and reranking run. A fifth
configuration shares the full pipeline's selected evidence and stops before verification. It sends
every claim to [review](../../docs/glossary.md#review), so its answer-support rate is zero. The comparison measures what enabling
automated verdicts adds when the evidence is held fixed. Answer-support rate counts answered
verdicts that match gold even if the selected evidence missed a gold passage. Evidence [recall](../../docs/glossary.md#recall)
checks the selected evidence against the gold passages. The request counts use the audited
backend, with the full pipeline's stage-one requests counted for both configurations that use
that shared execution.

The duplicate check compares the sets of words in two passages. A word is a run of Unicode
letters, numbers and combining marks (categories Mn, Mc and Me, as Python's `unicodedata`
classifies them), compared after NFC normalization and case folding. Variation selectors are
removed first. Every other character separates words: punctuation, symbols, underscores, and
zero-width joiners and non-joiners. Which separators stand between words, word order and repeated
words do not affect the score. Text written without spaces, such as Chinese or Thai, stays in
whole runs rather than receiving language-specific word segmentation, so one changed character
changes the whole run. Requests use the separate `stage_one_state(claim, passage)` and
`verify_state(claim, evidence)` constructors because a retrieved example produces several states.
The fixture builder drives `run_pipeline` with a backend that answers from the synthetic spec. The
`t04` decoys include an embedded instruction and a claim of decisive relevance. Their stored
answers exercise request construction and pipeline behavior, not a model's resistance to those
texts.

The full pipeline's `validation` verdicts set a confidence threshold with
`select_confidence_threshold`. The target applies to accepted validation verdicts. The policy
sends proposals below the frozen threshold to review. When no threshold meets the target, it
sends every proposal to review, even at confidence 1.0. An empty evidence set goes to review
without a verdict request.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev,ml]"` (the `ml` extra adds
scikit-learn, which the `Tests` jobs install and a recipe's `helpers.py` may use):

```bash
python -m jev_cookbook.fixtures validate recipes/52-retrieval-pipeline-evaluation
python tools/execute_notebook.py recipes/52-retrieval-pipeline-evaluation
pytest recipes/52-retrieval-pipeline-evaluation
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — the `dev` extra above adds `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline.

<!-- request-budget:begin -->
In live mode this notebook makes exactly **215** requests, of which 202 are distinct (the other 13 repeat a request on purpose) when every live answer matches the committed one, and up to **218** when a live answer sends it down a longer path. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=218` or higher before running it live (the default cap is 25): the cap is inclusive and every attempt counts against it, retries included, so a lower cap stops the run partway through with `BudgetExceeded` and a run that retries needs more.
<!-- request-budget:end -->

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 8 `validation` and 10 `test` examples are scored (the 3 `demo` examples are shown in the
  notebook but never scored).

Not measured live. The committed run replays invented claims and passages with hand-written
(synthetic) answers, including verdicts written from how much of the gold evidence reached the
verifier, several wrong on purpose and, in the full pipeline, one wrong *and* confident on `test` (`t08`) so the gate's
numbers show a real, non-zero [risk](../../docs/glossary.md#risk). Its answer-support rates, evidence recall, [coverage](../../docs/glossary.md#coverage) and request
counts check that the pipeline works (the candidate list, the cut, the composition, the gate and
the counting); they say nothing about how well Jev filters, reranks or verifies, how fast it is,
or what it costs. The request counts are counts of requests, not tokens, time or cost. This recipe
has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/52-retrieval-pipeline-evaluation/`. The root
`README.md` is generated; per the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by a
separate pull request, and this recipe's own builder never runs the renderer. While this recipe
remains unpublished and that integration step has not yet run, `Catalog (README is current)` is
expected to be red on its pull request, which is not a defect to fix here; once the catalog is
regenerated for it, the check turns green and stays that way. No sentence anywhere in this folder
states or implies Jev's real quality, latency, or cost: every number above is a synthetic pipeline
check. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
