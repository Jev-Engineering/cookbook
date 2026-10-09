# Quiz answer adjudication

**Recipe 21** · Level 2 (Easy) · Decision type: `Choice`

Judge whether a typed quiz response matches an accepted answer by meaning, with partial-match and review outcomes for ambiguous responses.

## What it teaches

Python checks a normalised exact match first (case, whitespace, punctuation and a leading
article folded away) against a candidate set of accepted phrasings it assembled itself; only a
response the normaliser cannot settle is sent to Jev. A question whose accepted answer is a
number is never sent to Jev at all, settled or not, because TypeSafe's own notes on Jev 1.13
(S07) say arithmetic belongs in code. Jev supplies one narrow judgment, a typed `Choice` over
four options the use case names: `match`, `partial_match`, `no_match`, `needs_review`. Python
decides what a model-chosen answer is allowed to do: a `review` outcome -- whether Jev named
the `needs_review` option outright or a confidence gate put a response there -- is never
reported as a final grade, because awarding or withholding a point is a side effect
CONTRIBUTING.md section 4 keeps in Python's hands; every such response goes into a simulated
`ReviewQueue` for a human adjudicator instead. The notebook shows both the settled and the
model-assisted path on one pair of examples, then the rule, then an evaluation that reports how
many responses never needed a call, agreement with the gold label, a confusion matrix and
per-class metrics, the `review` outcome broken down by which of its two causes fired, and,
among only the responses actually sent to Jev, selective coverage, accuracy and risk for the
confidence gate.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/21-quiz-answer-adjudication
python tools/execute_notebook.py recipes/21-quiz-answer-adjudication
pytest recipes/21-quiz-answer-adjudication
```

The notebook needs no network and no API key. It runs with this folder as its working directory,
replays the stored answers in `fixtures/responses.json`, and imports only the standard library
and `jev_cookbook`. Its first output says which mode ran.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — `.[dev]` above is for `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls change the backend and nothing else; the question definition is the same in both
modes. Install the SDK (`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`,
`JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder
in Jupyter (not a dependency of this repository), or record answers with the recorder described
in [docs/live.md](../../docs/live.md). `tools/execute_notebook.py` always removes
`JEV_COOKBOOK_*` and `TYPESAFE_*` from the kernel's environment, so it never runs live and never
writes a live outcome into a committed notebook.

`fixtures/` holds 40 examples, but this notebook makes far fewer than 40 calls in live mode: a
response the normaliser can settle on its own (an exact match after normalising, or any response
to a number question) never reaches Jev, and each of the rest is decided once and the stored
answer reused wherever it is shown again. In live mode this notebook makes exactly **17** calls,
one for each of the 17 examples (8 `validation`, 8 `test`, 1 `demo`) that `helpers.settle` leaves
unsettled, and no other. That is well below the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)). Never put a key in a
notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored). Of the scored examples, 22 (11
  `validation`, 11 `test`) are settled by the normaliser without ever reaching Jev; the
  remaining 16 (8 and 8) are sent to Jev.

The committed run replays 40 invented quiz responses with hand-written (synthetic) answers for
the 17 that are ever sent to a model, some wrong on purpose, including one that is wrong with
confidence above the frozen threshold (`t04-capital-wrong-confident`, stored as a confident
`match` where the gold label is `no_match`). Its agreement with the gold labels, the confusion
matrix, per-class metrics and the coverage of the frozen confidence gate check that the pipeline
works; they say nothing about how Jev performs, how fast it is, or what it costs. This recipe has
no recorded fixtures.

## Pull request rules

This recipe is published: the root `README.md` already carries its generated catalog regions,
from the integration step that ran when this recipe was first merged, per the generated-README
exception in [CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception). A later
pull request that changes only `recipes/21-quiz-answer-adjudication/` leaves the root `README.md`
untouched and does not need the renderer run; `Catalog (README is current)` stays green on such a
pull request. No sentence anywhere in this folder states or implies Jev's real quality, latency,
or cost: every number above is a synthetic pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
