# Card-game action selection

**Recipe 36** · Level 3 (Intermediate) · Decision type: `Choice`

Select a legal action in a turn-based card-game simulator using structured state and fixed action descriptions while Python enforces game rules.

## What it teaches

A seeded two-player card game, "Card Duel": each turn, Python enumerates exactly the cards left in the player's hand and offers them to Jev as a fixed-description `Choice`, and `CardDuel` (a `jev_cookbook.simulation.Simulator`) rejects any answer that is not one of them. Python also holds the one rule that decides what to do with an unconfident answer -- substitute a rule-based action and send the turn to review, never leave a turn unplayed -- and composes many such turns into a whole game, evaluated both per turn (does the choice match a rule-based reference action) and per game (does the resulting policy win, against a random-legal and a rule-based baseline, over seeded games).

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/36-card-game-action-selection
python tools/execute_notebook.py recipes/36-card-game-action-selection
pytest recipes/36-card-game-action-selection
```

The notebook runs from this folder with no network and no API key. A seeded script in `helpers.py` answers (there are no stored responses): see [docs/simulation.md](../../docs/simulation.md).

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
This notebook makes exactly **290** calls in live mode: a per-turn `Choice` is a live request every time `helpers.decide_turn` runs, and this recipe's task-level section plays whole games under two different model-driven policies (confidence-gated and, for comparison, ungated), each of which decides its own turns as the game unfolds rather than replaying a fixed trajectory, so most of those decisions are genuinely new states rather than the same question asked twice (98 calls score the per-question evaluation on `validation` and `test` plus the two demo turns; 192 more come from playing 10 validation and 14 test games under both model-driven policies, 4 decided turns each). 290 is far above the default budget of 25, so raise `JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at least 290 before running this notebook live, or shrink `VALIDATION_SEEDS`/`TEST_SEEDS` in the notebook first; either way it stops partway through with `BudgetExceeded` rather than silently truncate. Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** scripted (offline, answers computed by a seeded script, `helpers.script`). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 40 validation turns across 10 seeded games; 56 test turns across 14 seeded games (the two `demo` turns are not scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

Every number in this notebook, at both the per-turn and the task level, comes from `helpers.script`, a seeded stand-in for the model written for this recipe, never from a real call to Jev: it checks that the simulator, the confidence gate, and the task-level composition all work together, and says nothing about how Jev performs, how fast it is, or what it costs. The one exception the evaluation names explicitly is the rule-based baseline's own win rate, which is constant across every seeded game tried against this recipe's fixed opponent and is disclosed as a structural property of the two fixed strategies rather than a measured result.

## Pull request rules

This recipe's pull request changes only `recipes/36-card-game-action-selection/`. The root `README.md` is generated; per
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
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
