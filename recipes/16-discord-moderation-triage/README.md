# Discord moderation triage

**Recipe 16** · Level 2 (Easy) · Decision type: `Choice`

Classify sample Discord messages as allowed, review-needed, or potentially violating a supplied community rule to populate a simulated moderator queue.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over three fixed categories Python builds: `review_needed` (the explicit uncertain outcome, for a message whose tone or context a reader cannot be sure of), `potentially_violating`, and `allowed`. Python owns everything else: the community rule and message text Jev sees, the identifiers that never reach the model, and a rule (`helpers.moderate`) that applies one confidence gate to every category alike -- the standard three-path pattern -- before turning the category into one of four simulated moderation actions: `ignore`, `warn`, `hide`, or `escalate` to a person, through `jev_cookbook.simulation`'s `ActionLog` and `ReviewQueue`. `allowed` gets no exemption from the gate: a confidently wrong `allowed` answer leaves a message standing that a person never sees, which is a real consequence, not a free action. Nothing is ever posted, deleted, or sent to a real server. The notebook shows typed answers across this recipe's hard cases (sarcasm, a message that only quotes or reports someone else's abusive words, borderline banter, and a benign message with a trigger word), then the rule and the simulated queue it fills, then an evaluation that reports a confusion matrix, the separate cost of a false allow against a false flag, and the coverage, accuracy and risk the gate produces, chosen on `validation` over every category and frozen before `test`.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/16-discord-moderation-triage
python tools/execute_notebook.py recipes/16-discord-moderation-triage
pytest recipes/16-discord-moderation-triage
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
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline. In live mode this notebook makes exactly one call for each of the 41
examples in `fixtures/`, and no other (each message is decided once and the stored answer is reused
wherever it is shown again). That is more than the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)), so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=41` or higher before running this notebook live, or it stops partway
through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 20 `test` examples are scored (41 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored).

The committed run replays 41 invented Discord messages with hand-written (synthetic) answers, five
wrong on purpose (the notebook derives this count, and which ones, from the fixtures rather than
stating it, since this README's own text could drift from the fixtures where the notebook cannot):
one wrong and confident on `validation`, which the confidence gate -- chosen over every category
alike, `allowed` included -- is selected to exclude, and four more on `test`: two the gate catches
(one of them a false allow, caught now that `allowed` is gated like every other category instead
of being exempt from it), and two it does not -- a false flag that clears the gate (an allowed
message wrongly hidden) and a false allow that clears it too (a message that actually violates
the rule, read confidently as `allowed` and left standing: the cost of a false allow, which gating
`allowed` does not make impossible, only subject to the same gate every other category gets). Its
confusion matrix, per-category metrics and the coverage, accuracy and risk the frozen gate produces check
that the pipeline works; they say nothing about how Jev performs, how fast it is, or what it
costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/16-discord-moderation-triage/`. The root
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
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
