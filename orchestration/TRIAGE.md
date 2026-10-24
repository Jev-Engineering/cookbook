# Triage prompt: audit the Jev Cookbook

How to use this file: open Claude Code in a clone of `Jev-Engineering/cookbook` and say
"Read `orchestration/TRIAGE.md` and carry it out." Everything below the line is addressed to that
session. Narrow it if you want less than the whole repository: "…and carry it out, recipes 20 to 37
only" or "…shared code and CI only". A scoped run still follows every rule here; it just sweeps
fewer surfaces, and says at the top of its report which ones it skipped.

This is the companion to [`PROMPT.md`](PROMPT.md). That file builds the repository; this one reads
what was built and tells you what is wrong with it. They never run as the same session.

---

You are triaging the Jev Cookbook: a curriculum of sixty Jupyter notebook recipes that teach typed
decisions with Jev, TypeSafe AI's System One model, plus the shared package, tools, and CI they
stand on. Thirty-six recipes and the foundation are on `main`; the rest are not built yet.

Your output is **one ranked, evidence-backed findings report**. You fix nothing. The value of this
run is entirely in whether a maintainer can act on each finding without re-doing your work, and in
whether the things you call clean are actually clean. A plausible-sounding report that misses a
false measurement claim is worse than no report, because it will be believed.

Triage here is not a code review. A reviewer asks "is this change good?"; you ask "what is wrong
with this repository as it now stands, how bad is it, and where does the fix belong?" Nothing is out
of scope because it was reviewed and merged already. Several of the rules below exist precisely
because something that passed review turned out to be wrong.

## What the repository is judged against

Three documents define correctness. Read all three before you look at a single recipe, and cite them
by section when you report.

| Document | What it governs |
| --- | --- |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | The recipe contract, sections 1 to 7, and the scope allowlist. This is the one that decides whether a recipe is right. |
| [`docs/development.md`](../docs/development.md) | Setup, the three commands, every CI check name, what each one runs |
| [`docs/`](../docs/) (the rest) | Backends, fixtures, evaluation, notebook style, notebook CI, offline and live, merge readiness, simulation, the template, the glossary |

Where a doc and the code disagree, that disagreement is itself a finding: say which one you believe
is correct and why, and do not quietly take the code's side. Docs in this repository are load
bearing — sixty recipes are written from them.

## Step 1: ground truth before opinion

Run the checks before you form a view, and record the exact output of each. Everything you say later
is anchored to this.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

ruff check .                                   # Lint (ruff)
ruff format --check .                          # Lint (ruff), notebooks and Markdown too
pytest                                         # Tests (py3.10) / Tests (py3.14)
pytest -m catalog_audit                        # deselected by default; a wave check over every recipe
python tools/check_hygiene.py                  # Hygiene (secrets and notebook outputs)
python tools/render_catalog.py --check         # Catalog (README is current)
python tools/notebook_ci.py fixtures           # Fixtures (validate), every recipe
python -m jev_cookbook.fixtures validate --all # the same validator, per recipe, with detail
```

Then execute the notebooks. **`python tools/execute_notebook.py recipes/NN-slug` rewrites the
notebook in place**, so copy the recipe folder to the scratch directory and execute the copy, or
execute in place and `git restore` afterwards. Either way, finish with a clean working tree and say
in the report that you verified it is clean (`git status --porcelain` empty). A triage run that
leaves edits behind has damaged the thing it was auditing.

```bash
python tools/execute_notebook.py <copy>/recipes/NN-slug
python tools/check_notebook_fresh.py recipes/NN-slug/notebook.ipynb <copy>/recipes/NN-slug/notebook.ipynb
```

A stale committed output — the notebook on `main` is not what a fresh offline run produces — is a
finding against that recipe, and the diff tells you what kind: a changed number is far more serious
than a changed figure hash.

Record which interpreter you ran on. The repository supports 3.10 as its floor and executes
committable outputs on 3.14 with `.github/constraints-notebooks.txt`; a failure that appears on one
and not the other is a finding, and so is one you cannot reproduce on either.

If a check fails for an environmental reason (no network to install, a missing interpreter), say so
in the report as an unverified surface. Never infer a check's result from reading its source.

## Step 2: severity, and why this repository ranks it this way

Rank every finding on this scale. It is not generic: it puts the two promises this cookbook makes to
its readers above everything else, including broken builds.

- **S1 — Teaches the wrong thing.** The repository tells a reader something false about Jev or about
  how to build with it. A number presented as a Jev result that did not come from recorded live
  inference on a held-out set with the model string and capture date (contract section 2); a
  third-party or TypeSafe quality, latency or cost figure quoted without that same evidence; a
  recipe that lets the model do arithmetic, choose its own options, grant a permission, or cause a
  side effect (sections 3 and 4); a safety gate, budget or interlock that the prose claims is
  enforced and the code does not enforce; real personal data or scraped text in fixtures
  (section 5). A single S1 is worth more than every other finding in your report combined.
- **S2 — Breaks or silently weakens the guarantees.** A red or non-reproducible check; a notebook
  that does not execute offline from a fresh environment; a fixture miss that is swallowed instead
  of raising; a test that passes without asserting what it names; a gate that is skipped, loosened
  or disabled; a committed notebook output that is stale in a way that changes a reported number; a
  secret, token or local path reachable in a tracked file or a notebook output.
- **S3 — Contract violation with no reader-visible falsehood yet.** A `Choice` with one option or
  with no escape outcome where the use case needs one; a question that weighs several factors at
  once; a dependent question batched into the same request as the one it depends on; missing or
  wrong provenance on a fixture; a test split used more than once; a deferral treated as a
  complete-answer fallback (section 4's three-part test); an exemption claimed without the gated
  counterfactual printed beside the reported numbers.
- **S4 — Decay.** Stale prose, a doc that describes code that changed, a forward "Next steps" link
  to an unpublished recipe, a citation to a private issue number a reader cannot see, a glossary
  term used before it is defined, drift from the template that no recipe needed, duplicated logic
  that belongs in `src/jev_cookbook/`, a comment carrying prose that the contract says belongs in a
  markdown cell.
- **S5 — Worth knowing.** Inconsistency, naming, a rough edge, a risk that has not bitten yet.

When a finding could be two severities, state the higher one and say what would move it down.

## Step 3: route every finding

In this repository the fix route is part of the triage, because the scope allowlist decides who may
touch what. Tag each finding with exactly one:

- **`recipe`** — fixable inside `recipes/<slug>/` alone, by a recipe pull request on branch
  `recipe/<slug>`.
- **`foundation`** — needs `src/`, `tools/`, `tests/`, `docs/`, `.github/`, `catalog/`,
  `pyproject.toml` or a root file. It needs its own issue and its own pull request, and it may not
  ride along in a recipe pull request.
- **`template`** — the defect is in `recipes/_template/`, so every recipe built after the fix
  inherits the correction and every recipe built before it needs the same fix applied by hand. Say
  how many existing recipes carry the copy.
- **`systemic`** — the same defect in three or more recipes. Report it once, with the full list of
  affected paths, not once per recipe. A systemic S3 usually outranks an isolated S2 in what a
  maintainer should do first; say so when you think it does.
- **`process`** — the rule itself is wrong, ambiguous, or unenforceable as written in
  `CONTRIBUTING.md` or `PROMPT.md`.

## Step 4: the sweep

Cover every surface. For each one, the question is not "does this look reasonable" but "what rule
applies here, and does this obey it?"

### A. Shared package (`src/jev_cookbook/`)

`backends.py`, `evaluation.py`, `fixtures/`, `live.py`, `questions.py`, `answers.py`, `recipe.py`,
`simulation.py`, `style.py`, `_canonical.py`. The sixty recipes inherit everything this package gets
wrong, so a defect here is rarely isolated.

- Does the enforcement actually enforce? Single-option `Choice` rejected at construction; a fixture
  miss raising rather than inventing an answer; replay keys that cannot silently match the wrong
  stored answer after a question is edited; `noul_confidence` computing `|2p - 1|` as documented.
- Offline and live paths share the same question definitions, and `typesafe-sdk` is never imported
  at module import time (`Tests (py3.10)` installs `.[dev]` only and must pass with the SDK absent).
- Does the public surface match `docs/backends.md`, `docs/evaluation.md`, `docs/fixtures.md`,
  `docs/simulation.md`, `docs/notebook-style.md`? Check the documented examples run.
- `simulation.py`: an action is simulated, and nothing in the package can reach a real system.

### B. Tools and CI (`tools/`, `.github/workflows/`)

- Every check name in `docs/development.md` exists in a workflow, and every workflow job that gates
  merging is named in the docs. A renamed job silently stops being a required check.
- `check_hygiene.py`: does it catch what it claims — a key in a notebook output, an `Authorization`
  header, a local path, a username — and does it look inside the archive and notebook structures its
  docstring says it does? Try to think of a shape it would miss, and say so plainly as a gap rather
  than asserting coverage.
- `check_recipe_scope.py`: does it implement the allowlist in `CONTRIBUTING.md` exactly, including
  failing closed, `README.md` compared against `render(base README, head catalog)` rather than
  against itself, and rejection of symlink, submodule, mode and type changes?
- `notebook_ci.py`: the selection logic for a pull request, a push, a forced push, a rewound `main`,
  a first push, a scheduled run. A selection bug means a notebook is never executed by CI and nobody
  notices.
- `render_catalog.py`, `check_notebook_fresh.py`, `execute_notebook.py`, `new_recipe.py`,
  `check_merge_readiness.py`: same treatment. `new_recipe.py` scaffolds from the template, so drift
  between the two is a `template` finding.
- Third-party actions pinned to full commit SHAs, permissions at `contents: read`, no secret used by
  any keyless workflow.

### C. Catalog, README, docs

- `catalog/recipes.json` against the README's generated regions, and against what exists on disk:
  every `slug` matches its folder, ranks and issue numbers are unique and consistent, levels and
  categories agree with the level and category tables.
- The hand-written README prose against the current repository: a described command that no longer
  exists, a path that moved, a claim about measurement that contract section 2 would not allow.
- Each `docs/*.md` against the code it documents. Run the documented commands.
- The glossary: every term the recipes use is there, and each entry still matches the code.

### D. Tests (`tests/`, and each recipe's `tests/`)

- A test that cannot fail is a finding at S2, not S5: assertions on the wrong object, a fixture that
  makes the assertion vacuous, a guard whose known-failures list has quietly absorbed a real
  regression (`tests/recipe_guard_known_failures.py` deserves a close read — a known-failures file
  is where a defect goes to be forgotten).
- Anything skipped, xfailed, or deselected: say why it is, and whether the reason still holds. The
  `catalog_audit` marker is deselected by default on purpose; confirm it passes when run.
- Wherever a recipe's `helpers.py` enforces a rule, contract section 4 requires a test for it. Find
  the enforcements with no test.

### E. Each recipe (`recipes/NN-slug/`), against the contract section by section

Work recipe by recipe, oldest first, and apply the same checklist to every one. The template counts
as a recipe for this purpose and is the highest-leverage single folder in the repository.

1. **Layout and loading.** Only the files the contract allows. `helpers.py` loaded with
   `jev_cookbook.load_helpers`, never `import helpers` — pytest runs every recipe in one process, so
   a by-name import gives one recipe another's code.
2. **Offline by default (§1).** Runs top to bottom with no network and no key. Live is opt-in via
   `JEV_COOKBOOK_LIVE=1` and `TYPESAFE_API_KEY`, and switching modes changes the backend and nothing
   else. No key, token or `Authorization` header anywhere, notebook outputs included.
3. **Honest about what was measured (§2).** The `run_header` and the "What was and was not measured"
   cell are present and true: the run mode, the model string for `recorded` and `live`, the capture
   date for `recorded`, and N. Every reported number states N beside it. A synthetic or scripted run
   says next to each metric that it is a pipeline check and not a Jev result. Any sentence about
   Jev's quality, latency or cost traces to recorded inference on the held-out `test` split — a
   `validation` number is a selection step, not a result. A quoted third-party figure needs the same
   evidence. Where there was no recorded run, the README says "not measured live". **Read every
   number in the notebook and every adjective next to it.** This is where S1 findings live.
4. **Questions are narrow and typed (§3).** One thing per question. `Choice` options supplied by
   Python, at least two, with `none` / `other` / `no_match` / `uncertain` where the use case calls
   for one, and a one-option case resolved in Python without spending a call. `Noul` propositions
   written as true-or-false statements, one per label, with thresholds chosen from examples and
   evaluated. `Score` rubrics defining every level in words, with arithmetic in code. Independent
   questions in one request; a dependent question in a later one. Options, candidates, spans and
   identifiers built in Python and carried through unchanged.
5. **Python owns every side effect (§4).** Actions simulated. Permissions, budgets, retry limits,
   interlocks and stop conditions enforced in code so they hold whatever the model answers — and
   proved by a test where the recipe says they are. Uncertain or inconsistent results go to an
   explicit review outcome. Apply the three-part fallback test in full: (a) is it a complete answer
   or a deferral, (b) does choosing it record an action in the `ActionLog`, (c) does being wrong
   leave anything standing beyond the missed item. If the exemption is claimed, the gated
   counterfactual must be printed beside the reported numbers.
6. **Fixtures (§5).** Synthetic, small, readable, fabricated names and numbers only; no real
   personal data, no scraped or customer text; trust and safety fixtures mild. The hard cases the
   use case names are present, with gold labels for everything evaluated. Provenance on every
   response fixture. Splits as `docs/fixtures.md` specifies, and the `test` split used once, after
   choices were frozen. The validator passes.
7. **It teaches (§6).** Opens with what the reader will build, the decision type and the level;
   closes with next steps. Every "Next steps" link names a recipe whose `notebook.ipynb` is already
   on `main` — a forward link to an unbuilt recipe is a finding, and so is a link to the recipe's own
   issue. The typed answer is shown before any aggregate. Evaluation against gold labels, and against
   the named baseline where there is one. Prose in markdown cells, not code comments. Each cookbook
   term defined in prose on first use with the glossary linked. Citations only to reader-visible
   sources — never a private issue number or "the issue". Charts in the cookbook style, palette pink
   `#F386A1`, ink `#1E1E1E`, magenta `#E551BA`, panel grey `#DEDEDE`, paper `#FEFEFE`.
8. **It passes (§7).** Executes cleanly offline from a fresh environment, committed outputs fresh,
   fixtures validate, lint and tests pass with nothing skipped, disabled or loosened.

Also read each recipe as a learner would, once, end to end. Some defects — a notebook that is
correct and teaches nothing, an explanation that is subtly backwards, a conclusion the numbers do
not support — are only visible that way, and no check will ever catch them.

### F. Across recipes

- Divergence from the template that no recipe needed, and the same fix made differently in several
  recipes. Both are `systemic`.
- A rule that every recipe reimplements in its own `helpers.py`: candidate for `src/jev_cookbook/`.
- Terminology drift: the same concept under three names across recipes.
- Link integrity across the whole repository: internal links resolve, recipe cross-references point
  at published recipes, anchors exist.
- Level ordering: does recipe N actually demand what its level claims, and is the curriculum's
  difficulty monotone enough to follow in rank order?

## Step 5: verify before you report

Every finding carries, without exception:

- the file and line (`recipes/14-source-span-selection/helpers.py:88`), or the notebook cell by
  index and its first line;
- a command a maintainer can run to see it, with the output you got — or, where no command shows it,
  the quoted text and the contract section it violates;
- the severity, the route, and one sentence on consequence: what a reader or a maintainer gets wrong
  because of this.

Confirm each one before writing it down. Grep hits are leads, not findings; read the surrounding
code and the cell's prose. A rule you half-remember is not a rule — reopen `CONTRIBUTING.md` and
quote it. When you are genuinely unsure, report it as **Unverified** with the specific question that
would settle it, in its own section. Unverified items are welcome. Confident wrong ones are not.

Say what you did not cover, and why. "I executed 12 of 36 notebooks; here is the list I did not run"
is a useful report. An implied claim of full coverage you did not achieve makes the whole report
unusable.

## Step 6: the report

Write it to `triage-report.md` in the scratch directory (not into the repository — a triage run
commits nothing), and summarise the top findings in your reply.

```markdown
# Triage: Jev Cookbook — <date>, <commit sha>

Surfaces covered: ...        Surfaces skipped: ...
Environment: Python <v>, <OS>.  Working tree clean at finish: yes/no.

## Gate results
| Check | Command | Result |

## Findings
| # | Sev | Route | Where | Finding |
| 1 | S1 | recipe | 24-incident-priority-composition/notebook.ipynb, cell 18 | ... |

## Detail
### 1. <one-line title>  — S1, route `recipe`
**Where** · **What** · **Why it matters** · **Evidence** (command and output, or quoted text plus
the contract section) · **Suggested fix** (one or two sentences; you do not implement it)

## Unverified
## Clean
What you checked and found correct, surface by surface. This is evidence too: it tells a maintainer
where not to look again.
```

Order the findings table by severity, and within a severity by blast radius: systemic before
isolated, template before single-recipe, shared code before one notebook. If the whole report is one
line long because the repository is clean, say that plainly and show the gate output that supports
it. Do not pad a report to look thorough — inventing a finding to fill a section is the single
worst thing you can do here, worse than missing one.

## Rules for this run

1. **You fix nothing.** No edits, no commits, no branches, no pull requests, no pushes. The one
   exception is executing notebooks into a scratch copy, and the working tree is clean when you
   finish. If a defect is so severe it should stop something, say so at the top of the report.
2. **No live calls, ever, in a triage run.** No `JEV_COOKBOOK_LIVE=1`, no `TYPESAFE_API_KEY`, no
   search for a credential in any file. The live budget belongs to the build, not to the audit.
3. **Never weaken a check to see what happens.** Do not edit a test, loosen an assertion, or disable
   a workflow, even temporarily, even in a copy you intend to discard.
4. **Never reproduce a secret.** If you find one, report its location and its shape, masked, and
   treat it as S1. Do not paste it into the report, a log, or your reply.
5. **Read before you conclude, and read the whole file.** Notebooks are large; sample nothing that
   you then describe as checked.
6. **Stay inside this repository.** Read-only `gh` calls are fine if you need pull request or issue
   context. Do not change settings, labels, issues or pull requests, do not touch other
   repositories, and never run the WSL shutdown or terminate commands (`wsl --shutdown`,
   `--terminate`, `-t`) — they take down every other session on the machine.
7. **Your context will run out before thirty-six notebooks do.** Work in waves, write each wave's
   findings into the report file as you finish it rather than holding them in context, and keep the
   report on disk as your memory. If the operator has authorized subagents, one read-only agent per
   recipe with the section E checklist and this file's evidence rules is the right shape — each
   returns findings in the report's row format and nothing else, and you adjudicate, deduplicate and
   rank. Without that authorization, sweep serially and say in the report how far you got.
