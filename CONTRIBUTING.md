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

A recipe's `helpers.py` is never imported by name: every recipe has a `helpers` module and pytest runs them all in one process, so `import helpers` would give the second recipe the first one's code. Load it by path with `jev_cookbook.load_helpers`: `helpers = load_helpers()` in the notebook (its working directory is the recipe folder) and `helpers = load_helpers(Path(__file__).resolve().parent.parent)` in `tests/`. `python tools/new_recipe.py NN` creates a recipe folder from the template in `recipes/_template/`; see [docs/recipe-template.md](docs/recipe-template.md).

A recipe pull request touches only `recipes/NN-slug/`, with one bounded exception. It does not edit the catalog, shared code, workflows, or any hand-written part of `README.md`. The README tables are regenerated from the catalog by `tools/render_catalog.py`, which lists a recipe as published as soon as its `notebook.ipynb` exists, so adding a notebook makes the generated regions of the root `README.md` stale and the `Catalog (README is current)` check fails until they are regenerated.

### The generated-README exception

- **Builders never run the renderer.** The recipe builder stays inside `recipes/NN-slug/`.
- **A designated integration worker regenerates the README in the same recipe pull request.** A branch is handed over one worker at a time, never shared, and each handover is recorded on the pull request. The recipe builder finishes and hands the branch over; the integration worker (never the recipe builder) takes it, updates it against current `main` with a merge commit signed like any other commit (a `README.md` conflict is resolved by taking `origin/main`'s `README.md` and re-running the renderer, since every recipe merge changes the shared progress badge line), runs `python tools/render_catalog.py`, commits only the generated README regions, confirms `python tools/render_catalog.py --check` passes, and hands the branch on. The stage is serialized, one integration worker at a time, because every recipe pull request changes the same generated lines. This happens before the final review and before the final CI run, so the reviewed head is the head that is checked and merged. If `main` moves afterwards, the branch is updated and the README regenerated again, and the new head is reviewed again.
- **The only permitted change outside `recipes/NN-slug/` is the exact output of the renderer** for the five generated regions of the root `README.md` (the content between the `<!-- catalog:NAME:start -->` and `<!-- catalog:NAME:end -->` markers). Nothing else in `README.md`, no other root file, no catalog data, and no shared code or workflow may change in a recipe pull request.
- **Strict catalog CI is unchanged.** `python tools/render_catalog.py --check` still fails on a stale README. Until the integration stage has run, `Catalog (README is current)` is expected to be red on a recipe pull request that adds a notebook; that is not a defect to fix by hand or by running the renderer in the builder's branch. A recipe is never merged with a red check and a promise to fix the README later, and the README is never edited by hand.
- **Scope check, enforced by `Scope (recipe pull requests)` (`tools/check_recipe_scope.py`, #69) and applied mechanically by the reviewer.** The automated check implements exactly the same rule. It is an allowlist, evaluated on `git diff --raw -M base...head` (with `base` the current tip of `main` that the branch was updated against):
  0. The allowlist applies to a recipe pull request: one whose branch is `recipe/<slug>` and whose description says `Closes #N` with N in 1 to 60 (recipe N is issue N). A foundation pull request is any other; it is not subject to this allowlist. The check fails closed: a pull request that matches only one of the two tests, or whose `<slug>` cannot be resolved from the catalog entry for issue N, fails. A recipe pull request must close exactly one issue of this repository: a description that also closes another issue of this repository (recipe or not) is rejected, and so is one that closes two recipe issues. A closing reference written inside a fenced code block or an inline code span does not count, because GitHub links nothing written in either.
  1. Every changed path, whether added, modified, deleted or renamed (both the old and the new path of a rename), must be under `recipes/<slug>/`, where `<slug>` is the slug of the issue this pull request closes, or must be exactly `README.md`. Any other path is rejected: another recipe's folder, files directly under `recipes/`, the catalog, `src/`, `tools/`, `tests/`, `docs/`, `orchestration/`, `.github/`, `pyproject.toml`, and every other root file, including new files outside the allowed paths.
  2. Inside `recipes/<slug>/` and for `README.md`, symlinks, submodule entries, mode changes (for example making a file executable), and type changes are rejected: `README.md` must stay a regular, non-executable file (mode `100644`), every new or resulting mode must be `100644` (a new executable file, shown as `000000 100755 A`, is rejected), and nothing may be deleted or renamed out of the folder.
  3. `README.md` is accepted only if it equals the renderer's output computed from the **base** README, not from the head README. Run, in a checkout of the head with the head's `recipes/` tree (which decides publication status), `expected = render(<base README.md>, <head catalog/recipes.json>)` using `render` from `tools/render_catalog.py` (the base README comes from `git show base:README.md`), and require `head README.md == expected` byte for byte. Rendering the head README against itself is not enough: that is what `python tools/render_catalog.py --check` already does, and it passes for any prose or marker-line edit made outside the generated regions. The comparison against the base README rejects such edits by construction. The catalog is also required to be unchanged from the base (rule 1 already rejects `catalog/`), and `--check` must still pass on the head.
  4. #69 tests the rejection of at least one example of each excluded class: another recipe's folder, a root file, `docs/`, `tests/`, `src/`, `tools/`, `catalog/`, `.github/`, README prose, a README marker line, a rename or deletion out of scope, a symlink or mode change inside the recipe folder, a mode-only or type change to `README.md` with otherwise correct content, and a new file outside the allowed paths.
  For example: `git diff --raw -M origin/main...HEAD` must list only `recipes/<slug>/...` paths plus, once integrated, `README.md`. Reviewers reject symlink (`120000`) and submodule (`160000`) modes, any mode change (for example `100644 100755`), and any type change; every new or resulting mode must be `100644`; `--name-status` cannot show these, which is why the command is `--raw`.

## The contract

### 1. Offline by default, live by choice

- The notebook runs top to bottom with no network access and no API key, using the replay or scripted backend from `jev_cookbook` and the responses in `fixtures/`.
- Live calls are opt-in: `JEV_COOKBOOK_LIVE=1` with `TYPESAFE_API_KEY` set. The live path uses the same question definitions as the offline path, so switching modes changes the backend and nothing else.
- A fixture miss raises a clear error. Code never invents an answer to keep a notebook running.
- Never commit a key, a token, or an `Authorization` header, including inside notebook outputs.

### 2. Honest about what was measured

- Every response fixture records its provenance: `synthetic` (written for the recipe) or `recorded` (captured from a live call, with the model version the API returned and the date).
- The notebook states near the top which mode it ran in. In a synthetic run, any metric is a check that the pipeline works, and the notebook says so next to the number.
- The disclosure is the same in every recipe, and the template implements it with `run_header` and its "What was and was not measured" cell (see [docs/offline-and-live.md](docs/offline-and-live.md)): the run mode (`synthetic`, `scripted`, `recorded` or `live`), and for `recorded` and `live` the model string, for `recorded` the capture date, and N, the number of examples a reported number covers. In a live run the header, printed before the first call, names the model requested, and the measured cell names the model the API returned; a recorded run names the model the API returned. A synthetic or scripted run states N as the size of the fixture sample it checked the pipeline on.
- A live run over a recipe's fixture inputs measures those N small, written-for-the-recipe inputs with that model and nothing else. A recipe reports such a number only from recorded fixtures (provenance `recorded`), on the held-out `test` split, as exactly that: the model string the API returned, the capture date and N. It is not generalized: it says nothing about Jev's quality on other data, and nothing about latency or cost unless those were themselves measured and recorded. A live run that was not recorded yields nothing reportable, and a number from the `validation` split is a selection step, not a result.
- No sentence about Jev's quality, latency, or cost appears unless it comes from recorded live inference on a held-out set, with the model version stated. This holds even when the figure is attributed to someone else: quoting a third-party or TypeSafe number about Jev's quality, latency, or cost (a published benchmark, a cookbook, a case study) is still a statement about Jev, and it needs the same recorded, held-out evidence this recipe would need to state the number itself, or it does not appear. If no live run was made, the recipe README says "not measured live".
- Recipes that compare backends or optimize anything keep a test split that is used once, after choices are frozen.

### 3. Questions are narrow and typed

- Each question asks one specific thing. Decompose anything that weighs several factors and combine the answers in Python.
- `Choice` options are a fixed, supplied set. Include `none`, `other`, `no_match`, or `uncertain` outcomes when the use case calls for them.
- A `Choice` needs at least two options: with one, Jev has nothing to weigh. When a recipe's own candidate-gathering step leaves a document with only one option (or none), the decision belongs to Python, not to a request — resolve it directly in code and never build the question or spend a call. `jev_cookbook` enforces this at construction (see [docs/backends.md](docs/backends.md), "Single-option Choice").
- `Noul` propositions are written as statements that can be true or false. One independent question per label for multi-label tasks. Noul has no confidence field in the API; `jev_cookbook.evaluation.noul_confidence` derives a certainty `|2p - 1|` from its probability, and thresholds are chosen from examples and evaluated.
- `Score` rubrics define every level in words. Exact measurement and arithmetic stay in code.
- Independent questions go in one request. A question that depends on an earlier answer goes in a later request.
- Option lists, candidates, spans, and identifiers are built by Python and carried through to the output unchanged, so every result traces back to its source.

### 4. Python owns every side effect

- Actions are simulated. Nothing sends a message, moves a file, changes a ticket, or calls an external system.
- Permissions, budgets, retry limits, interlocks, and stop conditions are enforced in code and hold whatever the model answers. Where it makes sense, prove it with a test rather than a sentence.
- Uncertain or inconsistent results go to an explicit review outcome. A fallback option may be delivered as a final result at any confidence, with no further gate, only when it passes all three parts of this test:
  - **(a) It is a complete answer to the question, not a deferral.** `no_match`, `not_stated`, `no_suitable_rewrite` and `keep_original` are complete answers: each says what to do (link nothing, extract nothing, rewrite nothing, keep what was there). `unknown`, `needs_review` and an outcome such as "manual triage" are deferrals — each says "ask a person" rather than answering — and a deferral is always a review outcome, in the `ReviewQueue`, whatever its confidence; it never qualifies for this exemption.
  - **(b) Choosing it records no action in the `ActionLog`.** Submitting it to a backlog for someone to look at later is allowed, but only when the notebook prints the backlog entry and says plainly that it is a note and not an action taken (the pattern: the backlogged item is printed with the information it carries, and the prose says explicitly that nothing was changed). Recording the fallback as an action taken — a message sent, a status changed — fails this part, whatever the option is named.
  - **(c) Being wrong leaves nothing standing beyond the missed item itself, measured against having sent it to review instead.** A wrong complete-answer fallback that merely leaves one item unhandled in a visible backlog or as an unmatched item fails nothing here, because review would also have left that same item pending. A wrong fallback that leaves something else standing too — a violating message published, an exposure left open — fails this part, whatever (a) and (b) say about it.

  A deferral (failing (a)) counts toward review, not coverage, whatever its confidence; a complete-answer fallback that passes all three parts counts toward coverage like any other answered example. Every option that fails any part is gated on confidence like any other result. A recipe that claims the exemption shows it: it prints the gated counterfactual (the coverage, accuracy and risk the rule would report, on the split it is reporting, if the fallback were gated too) beside the numbers it actually reports, so a reader can see what the exemption costs or buys. Gating a qualifying fallback anyway, with no exemption claimed, is also compliant. [docs/recipe-template.md](docs/recipe-template.md) works through the contrast between a fallback that passes this test and one that does not.

### 5. Fixtures are synthetic and small

- Write the data for the recipe. No real personal data, no scraped content, no customer text. Fabricated names and numbers only.
- Trust and safety recipes stay mild: enough to exercise the decision, nothing graphic or abusive.
- Include the hard cases the use case names (no match, ambiguous, mixed, adversarial, benign look-alikes) and gold labels for everything evaluated.
- Keep a recipe's fixtures small enough to read. Aim for tens of examples at levels 1 and 2, and state the size wherever a number is reported.
- The file layout, splits, and the validator (`python -m jev_cookbook.fixtures validate recipes/NN-slug`) are specified in [docs/fixtures.md](docs/fixtures.md).

### 6. It teaches

- Open with what the reader will build, the decision type, and the level. Close with what to try next and links to neighbouring recipes. A "Next steps" link names a neighbour that already exists on `main`: link only a recipe whose `notebook.ipynb` is already committed, never one not yet published (a forward link), and never the recipe's own issue.
- Show the typed answer itself before any aggregate: the choice with its probabilities, the noul value, the score with its distribution.
- Evaluate against the gold labels with the helpers in `jev_cookbook`, and compare with the baseline the issue names when there is one.
- Explain each design choice in a sentence where it happens. Prose in markdown cells, not in code comments. Define a cookbook term the first time a recipe uses it, in prose, and link the matching [glossary](docs/glossary.md) entry there.
- Cite only reader-visible sources: the catalog's `S`-numbered references, this repository's own docs and files, or a neighbouring recipe by slug. A recipe file never cites a private issue number or "the issue" — a reader cannot see either, so name the use case or the rule instead of the ticket that asked for it.
- Charts use the cookbook plotting style. The palette is TypeSafe's: pink `#F386A1`, ink `#1E1E1E`, magenta `#E551BA`, panel grey `#DEDEDE`, paper `#FEFEFE`.

### 7. It passes

- The notebook executes cleanly offline in CI, start to finish, from a fresh environment.
- Fixtures validate against the fixture schema.
- Setup, the three commands, and CI are described in [docs/development.md](docs/development.md).
- Lint and tests pass. Nothing is skipped, disabled, or loosened to get there.

## Branches, commits, pull requests

- Branch names: `recipe/NN-slug` for recipes, `foundation/short-name` for shared work.
- One issue per pull request. The description says `Closes #N` and fills in the checklist from the pull request template.
- Squash merge once every current check has succeeded on the exact head and an Opus review of that head has approved it. A red, missing, cancelled or pending check is not mergeable, and any new commit voids earlier approval.
- A recipe pull request that adds a notebook includes the regenerated README regions (see the exception above) and says so in its description.
- A pull-request description is written once, at open (or with the first push), and never edited after the final push of a head that goes to the merge gate. `scope.yml`'s `Scope (recipe pull requests)` check runs on `pull_request_target` for `opened`, `synchronize`, `reopened` and `edited`, so an `edited` event reruns it, and the rerun replays the pre-edit body rather than reflecting the new one; the extra row it leaves behind is either a `cancelled` duplicate (if it overlaps a run still in progress) or, once the head has failed `Scope` for a real reason, a `success` next to an earlier `failure` that nothing can turn into a single passing result short of a new head (see [docs/merge-readiness.md](docs/merge-readiness.md)). Record fix-round notes and integration receipts in pull-request comments instead.
- A fix made in response to review is written for a first-time reader of the shipped notebook or doc, not for the reviewer: never compare the shipped text with an earlier revision the reader never saw. Words such as "previously", "used to be", "no longer" and "was once" are the usual way that comparison shows up, not a list of words to avoid regardless of what they are doing: the template's own "the stored keys no longer match the question" is a forward-looking comparison between two states a reader can see now (before and after an edit they make), not a reference to an earlier revision, and stays. Re-read the whole file after a fix, not only the changed cells or lines.

## Sources

Read the references listed on the recipe issue before writing questions. The full list is in the [README](README.md#sources). The TypeSafe documentation index for tools is at <https://docs.typesafe.ai/llms.txt>.
