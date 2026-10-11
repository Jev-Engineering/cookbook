# Schema field mapping

**Recipe 33** · Level 3 (Intermediate) · Decision type: `Choice`

Map source field descriptions to a bounded target schema with ambiguous and unmapped outcomes before Python validates the proposed mappings.

## What it teaches

Jev reads one source field at a time -- its name, its declared type, and a full description of what it actually holds -- from a fabricated legacy export, and answers one `Choice` over the eight fields of a fixed target schema, plus `ambiguous` and `unmapped`. Jev never sees more than one field at a time and never decides whether a proposed mapping is actually usable: Python does that afterward, in two steps (`helpers.gate_field`, then `helpers.apply_one_to_one`), checking that the declared type is compatible with the chosen target and that no two source fields were mapped to the same one. The notebook shows a field whose name is actively misleading and whose description resolves it anyway, two source fields that collide on the same target even though neither request could have known about the other, and an evaluation that reports mapping accuracy and the conflicts Python's validation catches, at the level of one field and at the level of a whole source batch.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/33-schema-field-mapping
python tools/execute_notebook.py recipes/33-schema-field-mapping
pytest recipes/33-schema-field-mapping
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
against that budget, including each retry.

This notebook makes exactly one request per source field it decides, each field decided once and
reused everywhere it is shown again: 35 fields in `fixtures/`, so **35 requests in live mode**, no
more. That is above the live backend's default budget of 25, so **raise
`JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at least 35** before running this notebook live, or it stops
partway through with `BudgetExceeded`; raise it further still to leave room for retries, since
every attempt (including a retry) counts against the budget. Never put a key in a notebook or a
fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 16 `validation` and 16 `test` fields are scored (35 in the fixtures, across 16 source
  batches on those two splits; the 3 `demo` fields, one more batch, are shown but never scored). A
  recorded recipe states N beside every reported metric.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 35 invented source fields with hand-written (synthetic) answers, some
wrong on purpose: a deliberately unconfident mistake (caught by the confidence gate, on
`validation`) and a one-to-one collision (caught by the one-to-one check, one on each split) are
both caught by Python's validation; a confident mistake on `test` that neither mechanism catches is
not, which is where this recipe's non-zero risk on `test` comes from. Its mapping accuracy, the
field- and task-level coverage/accuracy/risk, and the number of conflicts caught check that the
pipeline works; they say nothing about how Jev performs, how fast it is, or what it costs.

## Pull request rules

This recipe's pull request changes only `recipes/33-schema-field-mapping/`. The root `README.md` is generated; per
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
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
