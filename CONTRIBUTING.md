# Contributing to the Jev Cookbook

This file is the **recipe contract**. Every recipe issue points here, and a recipe pull request is reviewed against it. It applies equally to people and to coding agents.

Organization-wide policies (conduct, security reporting, support) live in [Jev-Engineering/.github](https://github.com/Jev-Engineering/.github).

## The idea every recipe protects

Jev supplies a focused semantic judgment. Python does everything exact. A recipe that lets the model do arithmetic, pick its own options, grant a permission, or perform a side effect is teaching the wrong lesson, however well it runs.

## Where things go

```text
recipes/NN-slug/
├── notebook.ipynb     the recipe, executed, outputs committed
├── README.md          one page: what it teaches, how to run it, what was and was not measured
├── fixtures/          inputs, labels, and model responses used by the offline run
├── helpers.py         optional: logic too long to read comfortably in a cell (level 3 and up)
└── tests/             optional: tests for helpers.py, required wherever helpers.py enforces a rule
```

`NN-slug` is the `slug` of the recipe in [`catalog/recipes.json`](catalog/recipes.json). Do not rename it. Shared code belongs in `src/jev_cookbook/` and changes there go through their own issue and pull request, never inside a recipe pull request.

A recipe pull request touches only `recipes/NN-slug/`, with one bounded exception. It does not edit the catalog, shared code, workflows, or any hand-written part of `README.md`. The README tables are regenerated from the catalog by `tools/render_catalog.py`, which lists a recipe as published as soon as its `notebook.ipynb` exists, so adding a notebook makes the generated regions of the root `README.md` stale and the `Catalog (README is current)` check fails until they are regenerated.

### The generated-README exception

- **Builders never run the renderer.** The recipe builder stays inside `recipes/NN-slug/`.
- **A designated integration worker regenerates the README in the same recipe pull request.** One integration worker at a time (the stage is serialized, because every recipe pull request changes the same generated lines) first updates the branch against current `main`, then runs `python tools/render_catalog.py`, then commits the result. This happens before the final review and before the final CI run, so the reviewed head is the head that is checked and merged. If `main` moves afterwards, the branch is updated and the README regenerated again, and the new head is reviewed again.
- **The only permitted change outside `recipes/NN-slug/` is the exact output of the renderer** for the five generated regions of the root `README.md` (the content between the `<!-- catalog:NAME:start -->` and `<!-- catalog:NAME:end -->` markers). Nothing else in `README.md`, no other root file, no catalog data, and no shared code or workflow may change in a recipe pull request.
- **Strict catalog CI is unchanged.** `python tools/render_catalog.py --check` still fails on a stale README. Until the integration stage has run, `Catalog (README is current)` is expected to be red on a recipe pull request that adds a notebook; that is not a defect to fix by hand or by running the renderer in the builder's branch. A recipe is never merged with a red check and a promise to fix the README later, and the README is never edited by hand.
- **Reviewer scope check, applied today and by #69 later (#69 is not yet built).** Nothing automated enforces the scope yet, so the reviewer applies it mechanically, and the scope check #69 adds must implement exactly the same rule. It is an allowlist, evaluated on `git diff --name-status -M base...head` (with `base` the current tip of `main` that the branch was updated against):
  1. Every changed path, whether added, modified, deleted or renamed (both the old and the new path of a rename), must be under `recipes/<slug>/`, where `<slug>` is the slug of the issue this pull request closes, or must be exactly `README.md`. Any other path is rejected: another recipe's folder, files directly under `recipes/`, the catalog, `src/`, `tools/`, `tests/`, `docs/`, `orchestration/`, `.github/`, `pyproject.toml`, and every other root file, including new files outside the allowed paths.
  2. Inside `recipes/<slug>/`, symlinks, submodule entries, mode changes (for example making a file executable), and type changes are rejected, and nothing may be deleted or renamed out of the folder.
  3. `README.md` is accepted only if it equals the renderer's output computed from the **base** README, not from the head README. Run, in a checkout of the head with the head's `recipes/` tree (which decides publication status), `expected = render(<base README.md>, <head catalog/recipes.json>)` using `render` from `tools/render_catalog.py` (the base README comes from `git show base:README.md`), and require `head README.md == expected` byte for byte. Rendering the head README against itself is not enough: that is what `python tools/render_catalog.py --check` already does, and it passes for any prose or marker-line edit made outside the generated regions. The comparison against the base README rejects such edits by construction. The catalog is also required to be unchanged from the base (rule 1 already rejects `catalog/`), and `--check` must still pass on the head.
  4. #69 must test the rejection of at least one example of each excluded class: another recipe's folder, a root file, `docs/`, `tests/`, `src/`, `tools/`, `catalog/`, `.github/`, README prose, a README marker line, a rename or deletion out of scope, a symlink or mode change, and a new file outside the allowed paths.
  For example: `git diff --name-status -M origin/main...HEAD` must list only `recipes/<slug>/...` paths plus, once integrated, `README.md`.

## The contract

### 1. Offline by default, live by choice

- The notebook runs top to bottom with no network access and no API key, using the replay or scripted backend from `jev_cookbook` and the responses in `fixtures/`.
- Live calls are opt-in: `JEV_COOKBOOK_LIVE=1` with `TYPESAFE_API_KEY` set. The live path uses the same question definitions as the offline path, so switching modes changes the backend and nothing else.
- A fixture miss raises a clear error. Code never invents an answer to keep a notebook running.
- Never commit a key, a token, or an `Authorization` header, including inside notebook outputs.

### 2. Honest about what was measured

- Every response fixture records its provenance: `synthetic` (written for the recipe) or `recorded` (captured from a live call, with the model version the API returned and the date).
- The notebook states near the top which mode it ran in. In a synthetic run, any metric is a check that the pipeline works, and the notebook says so next to the number.
- No sentence about Jev's quality, latency, or cost appears unless it comes from recorded live inference on a held-out set, with the model version stated. If no live run was made, the recipe README says "not measured live".
- Recipes that compare backends or optimize anything keep a test split that is used once, after choices are frozen.

### 3. Questions are narrow and typed

- Each question asks one specific thing. Decompose anything that weighs several factors and combine the answers in Python.
- `Choice` options are a fixed, supplied set. Include `none`, `other`, `no_match`, or `uncertain` outcomes when the use case calls for them.
- `Noul` propositions are written as statements that can be true or false. One independent question per label for multi-label tasks. Noul has no confidence field; thresholds are chosen from examples and evaluated.
- `Score` rubrics define every level in words. Exact measurement and arithmetic stay in code.
- Independent questions go in one request. A question that depends on an earlier answer goes in a later request.
- Option lists, candidates, spans, and identifiers are built by Python and carried through to the output unchanged, so every result traces back to its source.

### 4. Python owns every side effect

- Actions are simulated. Nothing sends a message, moves a file, changes a ticket, or calls an external system.
- Permissions, budgets, retry limits, interlocks, and stop conditions are enforced in code and hold whatever the model answers. Where it makes sense, prove it with a test rather than a sentence.
- Uncertain or inconsistent results go to an explicit review outcome.

### 5. Fixtures are synthetic and small

- Write the data for the recipe. No real personal data, no scraped content, no customer text. Fabricated names and numbers only.
- Trust and safety recipes stay mild: enough to exercise the decision, nothing graphic or abusive.
- Include the hard cases the use case names (no match, ambiguous, mixed, adversarial, benign look-alikes) and gold labels for everything evaluated.
- Keep a recipe's fixtures small enough to read. Aim for tens of examples at levels 1 and 2, and state the size wherever a number is reported.

### 6. It teaches

- Open with what the reader will build, the decision type, and the level. Close with what to try next and links to neighbouring recipes.
- Show the typed answer itself before any aggregate: the choice with its probabilities, the noul value, the score with its distribution.
- Evaluate against the gold labels with the helpers in `jev_cookbook`, and compare with the baseline the issue names when there is one.
- Explain each design choice in a sentence where it happens. Prose in markdown cells, not in code comments.
- Charts use the cookbook plotting style. The palette is TypeSafe's: pink `#F386A1`, ink `#1E1E1E`, magenta `#E551BA`, panel grey `#DEDEDE`, paper `#FEFEFE`.

### 7. It passes

- The notebook executes cleanly offline in CI, start to finish, from a fresh environment.
- Fixtures validate against the fixture schema.
- Lint and tests pass. Nothing is skipped, disabled, or loosened to get there.

## Branches, commits, pull requests

- Branch names: `recipe/NN-slug` for recipes, `foundation/short-name` for shared work.
- One issue per pull request. The description says `Closes #N` and fills in the checklist from the pull request template.
- Squash merge once every current check has succeeded on the exact head and an Opus review of that head has approved it. A red, missing, cancelled or pending check is not mergeable, and any new commit voids earlier approval.
- A recipe pull request that adds a notebook includes the regenerated README regions (see the exception above) and says so in its description.

## Sources

Read the references listed on the recipe issue before writing questions. The full list is in the [README](README.md#sources). The TypeSafe documentation index for tools is at <https://docs.typesafe.ai/llms.txt>.
