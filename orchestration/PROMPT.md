# Orchestration prompt: build the Jev Cookbook

How to use this file: open Claude Code in a clone of `Jev-Engineering/cookbook` and say
"Read `orchestration/PROMPT.md` and carry it out." Everything below the line is addressed to that session.

| Role | Model | Agent tool setting | Does |
| --- | --- | --- | --- |
| Orchestrator | whatever the session runs; this file does not name or assume it | the session itself | Plans, briefs, adjudicates, merges, keeps the record |
| Builder, integration worker | Claude Sonnet 5.5 | `model: "sonnet"`, only if it resolves to Sonnet 5.5 | Takes one issue, or one bounded integration task, to a pull request |
| Reviewer | Claude Opus (the runtime's Opus assignment) | `model: "opus"`, only if verified | Reviews every pull request before it merges |

Model assignments are verified, not assumed. Before dispatching, check what the runtime actually resolves each
alias to, record the resolved models, and never substitute a model silently or describe a review as Opus's
without having verified the assignment.

**This run (2026-10-08).** Owner decision on issue #80 ([comment
6070170893](https://github.com/Jev-Engineering/cookbook/issues/80#issuecomment-6070170893)): for
this run, builders run on Claude Sonnet 5 (`claude-sonnet-5`) and reviewers on Claude Opus 5
(`claude-opus-5`), the models this harness's Agent tool actually resolves `model: "sonnet"` and
`model: "opus"` to. Default service tier only, no Fast mode. Prior accepted results stand
unchanged. This is a dated substitution for this run only, not permission for any other model.

---

You are orchestrating the build of the Jev Cookbook: sixty Jupyter notebook recipes that teach typed decisions with Jev, TypeSafe AI's System One model, plus the shared code and CI they stand on. You do not write the code and you do not review it. Claude Sonnet 5.5 subagents build each issue and carry out integration, Claude Opus subagents review each pull request (see "This run" above for the dated model substitution in effect now), and nothing merges until Opus has approved the exact commit being merged. Your job is to run that pipeline across every issue in the repository, in dependency order, until all of them are closed or genuinely blocked.

This is an execution request. Continue beyond planning, opening pull requests, or green CI, and carry each issue through its authorized completion gates. This prompt is my explicit request for multi-agent orchestration at this scale. It will take a few hundred subagent runs. Spawn them without asking.

**Run ownership.** Before starting, inspect who already owns the run: existing supervisor sessions, open pull requests and their branches, worktrees, pending agents, receipts, budgets, and unrelated local changes. Resume or coordinate with an existing supervisor instead of creating a competing controller. Never write to a branch or worktree another agent owns, never resume or stop another session's agents, and preserve branches, review history, decisions, ledgers and local changes. One issue or explicitly bounded integration task per worker, one branch, clearly owned paths, and never two writers on one branch or worktree at the same time: a branch is handed over one worker at a time, and each handover (builder to integration worker, integration worker back to a builder for a fix round, and so on) is recorded on the pull request.

## Where things stand

GitHub, not this file, is the source of truth for state. This file was first written for an empty repository and has been revised since; do not treat any count, branch or approval it mentions as current. Package scaffolding, a CI baseline (workflow `CI`) and a hygiene workflow (`Hygiene`) already exist on `main`, along with the recipe contract, the catalog, and a README renderer; recipes, most shared code, and notebook execution in CI do not exist until their issues land. Work is described in GitHub issues:

| Issues | What they are | How they close |
| --- | --- | --- |
| #1 to #60 | One issue per recipe. **Recipe N is issue #N.** | A merged pull request each |
| #61 to #72 | Foundation: package, backends, fixtures, evaluation, notebook style, template, CI, simulation, hygiene, docs | A merged pull request each |
| #74 | Foundation tracking issue | You close it when its children meet their criteria |
| #75 to #79 | Tracking issues for levels 1 to 5 | You close each after its wave's audit |
| #73 | Release 1.0 audit | Prepared by you, closed by me when I approve the tag |
| #80 | Roadmap and owner decisions | Closes with #73 |
| #87 and later foundation issues | Fixes discovered during the build (for example the catalog coordination rules) | A merged pull request each |

Before anything else, read applicable `AGENTS.md` files, issue #80 with every owner decision comment, `CONTRIBUTING.md` (the recipe contract, which defines done for a recipe), `docs/development.md`, the current workflows and the pull request template, `catalog/recipes.json`, and issue #74. Then enumerate every issue (with state and labels) and every pull request with pagination, including conversation comments, formal reviews, review threads, checks, changed files, branches, and head and base SHAs. Labels alone do not tell you the state, and formal reviews do not hold all findings. If work has already happened, you are resuming: trust what GitHub shows and pick up from there. Audit completed work without recreating it. If historical review evidence is missing for any work, say so plainly, fix defects through new reviewed pull requests, and never invent a past approval.

Keep a durable execution ledger (concise progress comments on #80 are the shared copy): issue or pull request, dependencies, owner and agent ID, resolved model, worktree, branch, head and base SHA, acceptance evidence, review findings and comment IDs, CI run URLs, live spending and reservations, next action, and blocker. Update it after meaningful transitions, not only after a wave. It never holds a secret.

**Done** means all of the following, and you check each one explicitly at the end:

- Each of #1 to #72, and each issue opened during the build, is closed by a merged pull request that carries a genuine Opus approval for its final commit.
- Issues #74 to #79 are closed.
- The README shows 60 of 60 published and every row links to a notebook.
- All current checks are green on `main`.
- Every recipe has the live-recording coverage the owner decision on #80 requires, or the exact blocker is recorded.
- #73 is complete up to the tag, with release notes drafted, and waiting for me.

## How the three roles work together

**Builders (Sonnet 5.5).** One builder per issue (see "This run" above for the dated model substitution in effect now). Spawn with `model: "sonnet"` (after verifying it resolves to Sonnet 5.5) and `isolation: "worktree"` so parallel builders never share a working tree. A builder reads its issue, does the work on its own branch, runs the checks locally, opens a pull request, and reports back. When a review asks for changes, the same builder fixes them if you can still reach it; otherwise a fresh builder picks up the branch from the handoff notes in the pull request.

**Reviewers (Opus).** One fresh reviewer per pull request. Spawn with `model: "opus"` (after verifying the assignment) and `isolation: "worktree"`. The first review of a pull request always comes from an agent that has seen nothing of the builder's reasoning: give it the pull request number and the issue number, and nothing about what to expect. A reviewer who is handed the builder's summary tends to confirm it. The reviewer checks out the branch, runs everything itself, reads the work as a learner would, and posts its verdict on the pull request.

**You (the orchestrator).** You decide what runs when, write the briefs, read the reports, settle disagreements, merge serially, and keep labels and tracking issues true. Workers and reviewers never merge. Three things in particular are yours:

- *The briefs.* A subagent knows only what you put in its brief. Write each one for a capable colleague who has never seen this repository: the goal, the issue to read, the files that define the rules, the paths it may touch, what done looks like, and what to send back. The templates below are starting points to adapt, not forms to fill in.
- *Adjudication.* When a builder disputes a review finding, read that specific point yourself, in the code, and decide. Opus is not automatically right and Sonnet is not automatically wrong. Record your decision as a pull request comment. What you may not do is merge over an open finding without having decided it.
- *The record.* Your context will be summarized more than once during a build this long. GitHub is your memory. Keep state in labels, in pull request comments, in the ledger above, and in progress comments on #80. Do not read notebooks or large diffs yourself when a reviewer can report on them; spend your context on judgment.

Subagents have finite budgets. A level 4 or 5 recipe may not fit in one builder run, and a large pull request may not fit in one review. If a builder returns unfinished, continue it or start a fresh one on the same branch. If a review cannot be completed in one run, split it by scope (code and tests, then notebook and claims) and require both halves to approve.

## The review gate

This is the part of the process that must not bend.

1. **Every pull request is reviewed by Opus before it merges.** No exceptions: recipes, foundation work, integration, catalog, documentation, release preparation, one-line fixes. For a mechanical pull request the review is short, but it happens.
2. **Approval is tied to a commit and authenticated.** The reviewer posts one pull request comment containing its agent ID, resolved model, the exact head and base SHAs reviewed, an acceptance-criteria assessment, the checks it ran, blocking findings (with locations) separated from suggestions, and exactly one final verdict line using the full head SHA:

   ```text
   OPUS-REVIEW: APPROVE <full-head-sha>
   OPUS-REVIEW: CHANGES-NEEDED <full-head-sha>
   ```

   You record the genuine reviewer output and its comment ID in the ledger. Do not authorize a merge from a marker found by grepping comment text: quoted text, a builder-authored comment, a quotation inside another comment, or a verdict for an older head is not an approval. Fetch the comment itself (`gh api` on the comment ID), confirm it is the receipt of the reviewer you dispatched (the comment was posted after that agent's run, by the expected account, and the verdict line is the last line of the comment's own text rather than quoted material), and confirm the SHA equals the current head. GitHub will not let the account that opened a pull request approve it formally, which is why the gate is a comment and why you verify the receipt and the SHA yourself.
3. **Any new commit voids approval.** That includes a conflict-resolving rebase, a merge of `main`, and a regenerated README. Return fixes to a Sonnet worker and send the new head to Opus, with the earlier findings, to confirm each is resolved and to review what changed. Opus is also given the full current diff.
4. **No arbitrary abandonment.** There is no fixed number of fix rounds after which a problem is dropped. When a failure repeats, diagnose the cause, narrow the work, or assign a fresh Sonnet and Opus pair. Label an issue `status: needs human` and ask me only for genuinely missing authority or input, or a product decision that is mine; say exactly what is unresolved.
5. **Some pull requests get two independent reviews.** Issues #63, #65, #68, and #69 define the interface, the fixture format, the template, and the CI gate that sixty recipes will copy. Issue #1 is the reference recipe every later builder is pointed at. For these five, run two fresh Opus reviewers who do not see each other's findings, and require both to approve **the same final head**. A mistake here costs sixty fixes later. Existing stronger review requirements on a particular issue or pull request are preserved.
6. **You do not review in Opus's place.** If you are tempted to merge because a change "is obviously fine", spawn the reviewer anyway. Your adjudication of a disagreement does not replace an Opus approval with all blocking findings resolved.

## Rules that hold throughout

Each rule has its reason beside it. Pass the relevant ones on in every brief.

1. **Nothing merges on a red, missing, cancelled or pending check.** Wait for checks to finish, then read their conclusions explicitly. Do not pipe a watch command into `tail` or `head`, and do not treat a command's exit, `mergeable`, a clean merge state, or one green job as the result: a truncated watch once let a failing pull request through on this account. The complete gate is every check listed in the merge procedure below, including Hygiene. Follow that procedure.
2. **Never weaken a check to pass it.** No skipped tests, loosened assertions, disabled CI jobs, or fixtures edited to match a wrong output. If a check is wrong, that is a foundation issue with its own pull request and its own review.
3. **Offline runs are pipeline checks, and the notebooks say so.** CI, builders, and default notebook execution are offline and keyless. Builders and reviewers have no TypeSafe API key and must not look for one. Response fixtures written by an agent are `synthetic`. No notebook, README, or pull request may state or imply anything about Jev's real quality, latency, or cost except as measured on N examples, with the model version the API returned and the capture date, per section 2 of `CONTRIBUTING.md`. A notebook full of plausible numbers reads like a result, so reviewers check this on every pull request.
4. **Live recording is authorized by the owner, within limits, and not before #64.** The decision on #80 (<https://github.com/Jev-Engineering/cookbook/issues/80#issuecomment-6025510672>) supersedes any earlier statement that no live call will be made. It authorizes live Jev calls to record real fixtures for each recipe, **$25 in total for the whole build**: one cumulative limit across all workers, retries, resumed sessions and recipes, never a per-agent allowance. It does not authorize spending on other providers.
   - **Gate.** No live call occurs before #64 is merged **and** Opus-approved. Until then everything is offline and `synthetic`.
   - **Accounting.** Only the orchestrator, or one serialized recorder it designates, makes live calls, unless an atomic shared reservation with durable accounting exists. Before recording, reconcile actual prior usage and outstanding reservations, verify TypeSafe's current published pricing, convert the limit to conservative request and token caps, and enforce them through the #64 budget guard. Record every reservation and spend in a central durable ledger (kept in progress comments on #80 and reconciled with the guard's own record). Account for retries and requests whose outcome is unknown before retrying. Stop new calls when the remaining budget cannot safely cover them and ask me before exceeding $25.
   - **Credential.** The key stays in the untracked, git-ignored file outside every agent worktree that the owner supplied for this run. Use only that source; do not search other files for keys. It never appears in a commit, notebook output, log, command output, pull request, or issue, and reviewers check this on every pull request.
   - **Evidence.** `recorded` is only for answers captured from a real API call, with the returned model string, capture date, and request identity where available. Never hand-write or hand-edit a response and call it recorded. Live mode uses the same question definitions as offline mode. Notebooks replay the recorded fixtures offline by default.
   - **Coverage.** Track the recording requirement per recipe. If the credential or budget is unavailable, continue independent offline work and record the exact live-evidence blocker; never silently downgrade the owner's requirement or claim completion.
5. **Recipe pull requests touch only `recipes/<slug>/`, plus the regenerated README regions.** Sixty recipes built in parallel merge cleanly only if they never share a file. A builder that needs something from the shared package stops and describes the gap, and you open a foundation issue for it, which then goes through the same build and review. The one permitted addition is described in the next rule.
6. **The README is regenerated by the integration worker, inside the recipe pull request, never by hand and never by the builder.** Adding `notebook.ipynb` makes the generated catalog regions stale, and `Catalog (README is current)` is a strict required check, so the pull request must carry the regenerated regions. After the builder reports done, a designated Sonnet integration worker, one pull request at a time (this stage is serialized, because every recipe changes the same generated lines): (a) takes over the branch (the handover is recorded on the pull request; the builder is not a writer from then on) and updates it against current `main` with a signed merge commit (if `README.md` conflicts, take `origin/main`'s `README.md` and re-run the renderer, since every recipe merge changes the shared progress badge line), (b) runs `python tools/render_catalog.py` and commits only the resulting generated-region changes of the root `README.md`, (c) confirms `python tools/render_catalog.py --check` passes, and only then does the pull request go to final Opus review and the final CI run. If `main` moves afterwards, repeat the update and regeneration, and review the new head. The exception covers exact renderer output for the generated regions and nothing else: no hand-written README prose, no other root file, no catalog, shared-code, workflow or `docs/` change. Reviewers reject anything else outside `recipes/<slug>/`. Do not disable or loosen the catalog check, tolerate a red one, or merge now and repair the README later. Today reviewers enforce this scope with `git diff --raw -M origin/main...HEAD` (not `--name-status`, which cannot show modes; reviewers reject symlink `120000` and submodule `160000` modes, any mode change such as `100644 100755`, and any type change; every new or resulting mode must be `100644`), and the scope check #69 adds must implement the same rule, defined in full in `CONTRIBUTING.md`: an allowlist in which every changed path (added, modified, deleted, or either side of a rename) is under this pull request's `recipes/<slug>/` or is exactly `README.md`, with symlinks, mode changes, type changes (for `README.md` too, which must stay a regular file of mode `100644`) and new files outside those paths rejected, applied to recipe pull requests only (branch `recipe/<slug>` and `Closes #N` with N in 1 to 60; the check fails closed if only one of the two holds or the slug cannot be resolved), and with `README.md` required to equal `render(<base README>, <head catalog>)` computed with the head's `recipes/` tree, byte for byte. The template is the **base** README: rendering the head README against itself is what `--check` does and would accept prose edits. Until the integration stage has run, `Catalog (README is current)` is expected to be red on a recipe pull request that adds a notebook; the builder must not fix it. Stale hand-written README prose is fixed through a separate, reviewed documentation pull request, not inside a recipe pull request.
7. **All changes reach `main` through a pull request.** No direct pushes, no force pushes to `main`.
8. **Actions are simulated.** No recipe sends, moves, deletes, or calls anything real. Fixtures are synthetic, contain no real personal data, and trust and safety fixtures stay mild.
9. **Stay inside this repository.** Do not change its visibility, settings, or protection rules (inspect rules when you can, apply the procedural gates here whether or not GitHub enforces them, and never bypass a rule or use admin merge to force a merge), do not touch other repositories, and do not publish a release or push a tag. Never run the WSL shutdown or terminate commands (`wsl` with `--shutdown`, `--terminate` or `-t`); they take down every other session on the machine. Recover individual agents or processes without disturbing other sessions.
10. **Jev facts come from the sources.** The TypeSafe documentation index is at `https://docs.typesafe.ai/llms.txt`, the Python SDK page at `https://docs.typesafe.ai/sdk/python`, and each issue lists the pages that apply. Builders read them before designing questions and do not guess at the API. Jev is not a text model: it answers `Choice`, `Noul`, and `Score` questions over a supplied state and nothing else.

## One issue, start to finish

1. **Check it is ready.** Everything under Dependencies on the issue is delivered and verified, not merely closed or present on a branch. The manifest below lists what each issue waits for; reconcile it against the live issues and GitHub relationships, and resolve any discrepancy before dispatching.
2. **Claim.** Replace `status: ready` or `status: blocked` with `status: in progress`.
3. **Build.** Spawn a Sonnet builder with the builder brief. It opens a pull request whose description says `Closes #N`.
4. **Integrate (recipes).** The serialized integration worker updates the branch against current `main` and regenerates the README regions (rule 6), then CI runs on that head.
5. **Checks.** Wait for CI to finish and read the result as described under merging.
6. **Review.** Spawn a fresh Opus reviewer with the reviewer brief (two for the five issues named above) on the final head.
7. **Fix and re-review** until the newest genuine review approves the current head. Any new head repeats steps 4 to 6.
8. **Merge.** Follow the merge procedure. One pull request at a time.
9. **Verify and unblock.** Confirm the issue closed, its acceptance criteria are actually met, and CI on that exact `main` commit is green. Remove `status: in progress`. For every issue that waited on this one, check whether all its blockers are now delivered, and if so change `status: blocked` to `status: ready`.

### Merging

Hold a single merge lock. Run these as separate steps and read the output of each:

```bash
gh pr view <PR> --json headRefOid,baseRefName,mergeable,mergeStateStatus,statusCheckRollup,reviewDecision
gh pr checks <PR> --watch --fail-fast          # wait; do not pipe this anywhere
gh api repos/Jev-Engineering/cookbook/issues/<PR>/comments --paginate   # fetch the receipts themselves
```

Also read formal reviews and review threads, and refresh current `main`. Merge only when all of these hold:

- Every dependency is delivered and verified, and the acceptance criteria are met.
- The branch is current against `main` (except under the foundation-only ruling in the next item) through a signed integration of current `main` (a merge commit, never a rebase or force-push), the integration stage (rule 6) was done on this head, and nothing outside the allowed scope changed. This is the default and is mandatory for every recipe pull request and for any foundation pull request whose `main` advance is material (it touches the pull request's files, shared code it uses, workflows under `.github/workflows/`, or the set of required checks). If the evidence for an immaterial advance cannot be shown, treat the advance as material. Every new head, including one produced by an integration, needs a renewed genuine Opus review and complete checks.
- `python tools/check_merge_readiness.py --pr <PR> --expected-head <headRefOid>` was run, and its receipt is recorded as it is. Name `Scope (recipe pull requests)` with `--require-head-check`, not `--require-check`, since it is required on the PR head only and never judged on `main`. It is read-only and never merge authorization. A `NOT READY` result stays `NOT READY`: it is never reported as a pass. The one way to merge past an ancestry-only `NOT READY` is the foundation-only manual ruling in the [manual decision for an immaterial `main` advance](../docs/merge-readiness.md#manual-decision-for-an-immaterial-main-advance), made as a standing rule in [#80 ledger update 6](https://github.com/Jev-Engineering/cookbook/issues/80#issuecomment-6031026593) (see [`docs/merge-readiness.md`](../docs/merge-readiness.md)), which needs all of: the exact current `main` SHA pinned, with the delta and its effect on every required check shown; each required genuine Opus reviewer's explicit acceptance of that delta on the same head; every required check present and `success` on both the head and current `main` (a check that by design runs on a pull request only, such as `Scope (recipe pull requests)`, is required on the head and is never expected on a commit of `main`, so its absence there is not a failure of this requirement), with no claim that an older `main`'s CI covers a later one; and an honest merge note that the checklist's currency requirement was departed from. If `main` advances again, the ruling and the acceptance lapse and must be renewed, or the branch is integrated and reviewed again. The ruling never applies to recipe pull requests, which always take a signed current-`main` update, README regions rendered from the base README, and a new-head review, with no exception.
- The complete current check set exists and has finished with conclusion `SUCCESS` (or `SKIPPED` only where a workflow's documented condition really applies): `Lint (ruff)`, `Catalog (README is current)`, `Tests (py3.10)`, `Tests (py3.14)`, and `Hygiene (secrets and notebook outputs)`. Read the workflows (`.github/workflows/`) rather than trusting this list, and require any check added since (for example the notebook execution, fixture validation and scope checks from #65 and #69). Handle both CheckRun and StatusContext entries in `statusCheckRollup`. A missing, pending, failed, cancelled or timed-out check blocks the merge.
- Every blocking finding is resolved, and applicable review threads are resolved.
- A genuine Opus receipt (the authenticated comment described under the review gate) approves the current `headRefOid`. For the double-review issues, both distinct reviewers approve that same head.

Then pin the merge to the commit that was reviewed, so a late push cannot ride in, and verify the result:

```bash
gh pr merge <PR> --squash --match-head-commit <headRefOid>
gh issue view <N> --json state,closedAt
```

Do not use admin bypass, and honor any merge queue. Do not add `--delete-branch`: merging never deletes the branch or its worktree. Remove an unused branch or worktree later and separately, only after the merge commit and its exact post-merge CI are verified and its owner confirms it is unused and nothing on it is needed (see Run ownership). Record the merge commit and wait for CI on that exact `main` commit, read per check as in the post-merge steps of [`docs/merge-readiness.md`](../docs/merge-readiness.md#where-it-fits-in-the-serial-merge), and let it finish green before the next merge or before treating the work as verified. If `main` fails, stop merging and prioritize a Sonnet fix with Opus review; do not hide the failure.

If a merge leaves another open pull request behind or conflicted, it is updated against `main`: for a recipe pull request the builder hands the branch to the integration worker, who updates it and regenerates the README (rule 6); for a foundation pull request its owner updates it with a signed integration of current `main`, unless the advance is immaterial and the foundation-only manual ruling in the [manual decision for an immaterial `main` advance](../docs/merge-readiness.md#manual-decision-for-an-immaterial-main-advance) is fully evidenced and accepted by each required reviewer on the same head. Each handover is recorded on the pull request. An integration changes the head, so the new head is reviewed again; on the immaterial path the head does not change, and each required reviewer's explicit same-head acceptance of the new delta is that renewed review.

### Builder brief (Sonnet 5.5)

> You are building one issue in the repository `Jev-Engineering/cookbook`, a cookbook of Jupyter notebooks that teach typed decisions with Jev (TypeSafe AI's System One model, which answers Choice, Noul, and Score questions over a supplied state and does not generate text).
>
> Your issue is #N. Read it in full with `gh issue view N`, then read `CONTRIBUTING.md`, which is the contract your work is reviewed against. For a recipe, also read the recipe template once #68 has merged and the merged reference recipe `recipes/01-sentiment-classification/` once #1 has merged, as the reference for structure and tone, and read the documentation pages listed under Sources on the issue before you design any question.
>
> Branch from the latest `origin/main` as `<branch>`. Work only inside `<allowed paths>`. For a recipe that is `recipes/<slug>/`; you do not run `tools/render_catalog.py` or edit the root `README.md`, because the integration worker regenerates the README regions in your pull request after you finish (until then `Catalog (README is current)` is expected to be red on your pull request; do not fix it). If you find you need a change outside your paths, stop and tell me what and why instead of making it.
>
> You have no TypeSafe API key and must not look for one, and you make no live call. The notebook runs offline from fixtures you write, and those fixtures are marked `synthetic`; recorded fixtures come later, from the orchestrator's budgeted recorder, never from you. Do not write anything, in the notebook, the README, or the pull request, that states or implies how well Jev actually performs. Metrics from a synthetic run are checks that the pipeline works, and the notebook says so beside each number.
>
> Before opening a pull request, run the checks from `docs/development.md` and the current workflows (`ruff check .`, `ruff format --check .`, `pytest`, `python tools/check_hygiene.py`, and the fixture validator and notebook execution once they exist), executing the notebook offline from a clean kernel. Use a fresh virtual environment, and sign your commits with the configured signing (never disable it). Fix what fails; do not skip or loosen a check. Then open a pull request with `Closes #N` and the template filled in, including the commands you ran and their results.
>
> Your pull request will be reviewed by a separate reviewer who runs everything again and reads the notebook as a learner. Write for that reader.
>
> Report back: the pull request URL and number, the branch and the full head SHA, each acceptance criterion from the issue marked met or not met with one line of evidence, anything you were unsure about, and anything you think is wrong with the issue, the template, or the shared package. If you run short of budget, push what you have, write handoff notes in the pull request description, and say so plainly.

For a fix round, send the builder the review comment and add: address every finding, or say which one you disagree with and why; do not change anything the review did not ask for; push, and report the new head SHA.

### Integration worker brief (Sonnet 5.5)

> You are the integration worker for recipe pull request #P in `Jev-Engineering/cookbook`. You are never the recipe builder. Take the branch only after the orchestrator has recorded the handover from the builder on the pull request, work in your own worktree, and stay the only writer until you record the handover back.
>
> Your allowed paths are the generated regions of the root `README.md` and nothing else. Fetch, then merge current `origin/main` into the branch (a merge commit, not a rebase; no force-push; the merge commit is signed like any other commit). If merging `origin/main` conflicts in `README.md`, resolve it by taking `origin/main`'s `README.md` and then re-running the renderer, since every recipe merge changes the shared progress badge line. In a fresh virtual environment run `python tools/render_catalog.py`, then confirm `python tools/render_catalog.py --check` passes, and run `git diff --raw -M origin/main...HEAD` (it shows modes; reject symlink `120000` and submodule `160000` modes, any mode change such as `100644 100755`, and any type change; every new or resulting mode must be `100644`): every path must be under `recipes/<slug>/` or be exactly `README.md`, a regular file of mode `100644` (check with `git ls-files -s README.md`). Commit only the generated README regions, signed, with the Sonnet co-author line; never hand-edit the README or touch any other file. Push new commits only.
>
> Report back: the pull request number, the new full head SHA, the commands you ran with their actual results, and the `git diff --raw -M origin/main...HEAD` output. If `main` moves again, or a fix round changes the branch, you are called again and repeat this.

### Reviewer brief (Opus)

> Review pull request #P in `Jev-Engineering/cookbook` against issue #N and `CONTRIBUTING.md`. You are the gate: this change merges only if you approve it, and sixty recipes are being built to the same standard, so what you accept here becomes the pattern. Check it yourself and do not rely on the pull request description.
>
> Check out the branch with `gh pr checkout P` and note the head and base commit SHAs. Do not take a verdict or summary from the builder. Run the checks from `docs/development.md` and the current workflows (lint, format, tests, catalog check, hygiene, and the fixture validator and notebook execution once they exist) in a fresh environment, and execute the notebook offline from a clean kernel with no `TYPESAFE_API_KEY` set. Then read the notebook from top to bottom as a learner with basic Python would.
>
> Go through every acceptance criterion on the issue and every section of the contract. Look hardest at these, because they are where this work goes wrong:
>
> - Any statement or implication about Jev's real quality, latency, or cost. Synthetic runs are pipeline checks and must be labelled so beside each number.
> - Fixtures that are too easy, that miss the hard cases the issue names, that contain answers no real model would plausibly give, or that make the evaluation trivially perfect.
> - Anything marked `recorded` that could not have come from a real API call.
> - Decisions the model appears to make that Python should own: arithmetic, option lists, permissions, budgets, side effects.
> - Rules the issue says are enforced in code with no test that proves it.
> - Question design that departs from the sources listed on the issue: compound questions, undefined rubric levels, missing fallback outcomes.
> - Files changed outside the allowed paths (for a recipe, run `git diff --raw -M origin/main...HEAD`, which shows modes: reject symlink `120000` and submodule `160000` modes, any mode change such as `100644 100755`, and any type change; every new or resulting mode must be `100644`; every path must be under `recipes/<slug>/` or be `README.md`; `README.md` must be a regular file of mode `100644` and equal `render(<base README>, <head catalog>)` as defined in `CONTRIBUTING.md`; anything else is a finding), and anything that looks like a key, real personal data, or a real side effect.
> - Anything marked `recorded` without the returned model string, capture date and authentic provenance, and any key or credential in a notebook output, log, or description.
> - For shared code: an interface or format that will be awkward for the sixty recipes that have to use it.
>
> Post your findings as one comment on the pull request. Begin it with your agent ID and resolved model and the exact head and base SHAs you reviewed. Order findings by severity, each with the file and location, what is wrong, and what to change. Separate what must change from what is only a suggestion, and say which checks you ran. Then list each acceptance criterion as met or not met. End the comment with exactly one of these lines as its own final line, using the full head SHA you reviewed:
>
> `OPUS-REVIEW: APPROVE <sha>`
> `OPUS-REVIEW: CHANGES-NEEDED <sha>`
>
> Do not quote either line elsewhere in the comment. Approve only if you would be comfortable with a reader learning from this as it stands. Return the same verdict to me with a two or three sentence summary.

For a re-review, add: these were your findings; for each, say whether it is resolved; then review everything that changed since the SHA you last reviewed, and post a new verdict line for the new head SHA.

## The manifest: every issue, in order

Work through the waves in order. Inside a wave, issues in the same step or round can run in parallel, at most six builders at a time. That limit keeps you under GitHub's rate limits and keeps the review queue short enough that lessons from early pull requests reach later ones. An issue never starts before everything in its "Waits for" column is closed, whatever its wave.

Branches are `foundation/<name>` as listed, and `recipe/<slug>` for recipes. A recipe's allowed path is `recipes/<slug>/`.

### Wave 0: foundation (#61 to #72)

| Issue | What | Step | Branch | Waits for | Size | Opus review |
| :---: | --- | :---: | --- | --- | :---: | --- |
| #61 | project scaffolding and Python package skeleton | 1 | `foundation/scaffolding` | nothing | S | one review |
| #62 | CI baseline for lint, tests, and the README catalog check | 2 | `foundation/ci-baseline` | #61 | S | one review |
| #63 | decision backends with typed answers, replay, and scripted modes | 2 | `foundation/backends` | #61 | M | two independent reviews |
| #64 | opt-in live Jev backend and response recorder | 3 | `foundation/live-backend` | #63 | M | one review |
| #65 | fixture specification and validator | 3 | `foundation/fixtures` | #63 | M | two independent reviews |
| #66 | evaluation toolkit | 2 | `foundation/evaluation` | #61 | L | one review |
| #67 | notebook style, plotting theme, and run-mode header | 2 | `foundation/notebook-style` | #61 | S | one review |
| #68 | recipe template and scaffolder | 4 | `foundation/recipe-template` | #63, #65, #66, #67 | M | two independent reviews |
| #69 | CI executes every notebook offline and validates fixtures | 5 | `foundation/notebook-ci` | #62, #68 | M | two independent reviews |
| #70 | simulation and state primitives | 3 | `foundation/simulation` | #63 | L | one review |
| #71 | repository hygiene for secrets, dependencies, and notebook outputs | 3 | `foundation/hygiene` | #62 | S | one review |
| #72 | reader documentation for getting started, offline and live modes, and the glossary | 5 | `foundation/reader-docs` | #64, #68 | M | one review |

### Wave 1: level 1, Beginner (#1 to #10), tracked in #75

| Issue | Recipe | Slug | Types | Size | Round | Waits for | Flags |
| :---: | --- | --- | --- | :---: | :---: | --- | --- |
| #1 | Sentiment classification | `01-sentiment-classification` | Choice | S | 0 | #69 | reference recipe: build alone, two reviews |
| #2 | Refund intent detection | `02-refund-intent-detection` | Noul | S | A | #69 |  |
| #3 | Response clarity scoring | `03-response-clarity-scoring` | Score | S | A | #69 |  |
| #4 | Support ticket routing | `04-support-ticket-routing` | Choice | S | A | #69 |  |
| #5 | Document classification | `05-document-classification` | Choice | S | A | #69 |  |
| #6 | Multiple topic labels | `06-multiple-topic-labels` | Noul | S | A | #69 |  |
| #7 | Word sense selection | `07-word-sense-selection` | Choice | S | A | #69 |  |
| #8 | FAQ selection | `08-faq-selection` | Choice | S | A | #69 |  |
| #9 | File organization | `09-file-organization` | Choice | S | A | #69 |  |
| #10 | Answer relevance check | `10-answer-relevance-check` | Noul | S | A | #69 |  |

### Wave 2: level 2, Easy (#11 to #23), tracked in #76

| Issue | Recipe | Slug | Types | Size | Round | Waits for | Flags |
| :---: | --- | --- | --- | :---: | :---: | --- | --- |
| #11 | Clarification selection | `11-clarification-selection` | Choice | M | A | #69 |  |
| #12 | Thesaurus word selection | `12-thesaurus-word-selection` | Choice | M | A | #69 |  |
| #13 | Candidate rewrite selection | `13-candidate-rewrite-selection` | Choice | M | A | #69 |  |
| #14 | Source span selection | `14-source-span-selection` | Choice | M | A | #69 |  |
| #15 | Sensitive text triage | `15-sensitive-text-triage` | Noul | M | A | #69 |  |
| #16 | Discord moderation triage | `16-discord-moderation-triage` | Choice | M | A | #69 |  |
| #17 | Passage reranking | `17-passage-reranking` | Score | M | A | #69 |  |
| #18 | Duplicate incident matching | `18-duplicate-incident-matching` | Choice | M | A | #69 |  |
| #19 | CI failure classification | `19-ci-failure-classification` | Choice | M | A | #69 |  |
| #20 | Claim support classification | `20-claim-support-classification` | Choice | M | A | #69 |  |
| #21 | Quiz answer adjudication | `21-quiz-answer-adjudication` | Choice | M | A | #69 |  |
| #22 | CMDB asset matching | `22-cmdb-asset-matching` | Choice | M | A | #69 |  |
| #23 | Pairwise answer evaluation | `23-pairwise-answer-evaluation` | Choice | M | A | #69 |  |

### Wave 3: level 3, Intermediate (#24 to #39), tracked in #77

| Issue | Recipe | Slug | Types | Size | Round | Waits for | Flags |
| :---: | --- | --- | --- | :---: | :---: | --- | --- |
| #24 | Incident priority composition | `24-incident-priority-composition` | Score | M | A | #69, #3 |  |
| #25 | Change evidence review | `25-change-evidence-review` | Noul | M | A | #69, #6 |  |
| #26 | Prompt-injection screening | `26-prompt-injection-screening` | Noul | M | A | #69 |  |
| #27 | Function selection | `27-function-selection` | Choice | M | A | #69 |  |
| #28 | Skill selection | `28-skill-selection` | Score | M | A | #69, #11, #17 |  |
| #29 | Tool outcome verification | `29-tool-outcome-verification` | Choice | M | A | #69 |  |
| #30 | Citation verification | `30-citation-verification` | Choice | M | A | #69, #20 |  |
| #31 | Patch risk triage | `31-patch-risk-triage` | Noul | M | B | #69, #25 |  |
| #32 | Regression test selection | `32-regression-test-selection` | Score | M | A | #69, #17 |  |
| #33 | Schema field mapping | `33-schema-field-mapping` | Choice | M | A | #69 |  |
| #34 | Evidence relationship labels | `34-evidence-relationship-labels` | Choice | M | A | #69 |  |
| #35 | Semantic feature extraction | `35-semantic-feature-extraction` | Noul | M | A | #69, #6 |  |
| #36 | Card-game action selection | `36-card-game-action-selection` | Choice | L | A | #69, #70 | simulator |
| #37 | Research domain tagging | `37-research-domain-tagging` | Noul | M | A | #69, #6 |  |
| #38 | Abstention and review queues | `38-abstention-and-review-queues` | Choice | M | A | #69, #4 |  |
| #39 | Document extraction cascade | `39-document-extraction-cascade` | Choice + Noul | M | A | #69, #14 |  |

### Wave 4: level 4, Advanced (#40 to #52), tracked in #78

| Issue | Recipe | Slug | Types | Size | Round | Waits for | Flags |
| :---: | --- | --- | --- | :---: | :---: | --- | --- |
| #40 | Hierarchical classification | `40-hierarchical-classification` | Choice | L | A | #69, #5, #38 |  |
| #41 | Approval scope review | `41-approval-scope-review` | Noul | L | A | #69, #27 |  |
| #42 | Outbound disclosure screening | `42-outbound-disclosure-screening` | Noul | L | A | #69, #15 |  |
| #43 | Failure recovery selection | `43-failure-recovery-selection` | Choice | L | A | #69, #70, #29 | simulator |
| #44 | Plan constraint assessment | `44-plan-constraint-assessment` | Noul | L | A | #69 |  |
| #45 | Memory reconciliation | `45-memory-reconciliation` | Choice | L | A | #69, #70 | simulator |
| #46 | Semantic context paging | `46-semantic-context-paging` | Score | L | A | #69, #70, #17 | simulator |
| #47 | Evidence conflict diagnosis | `47-evidence-conflict-diagnosis` | Choice | L | A | #69, #20 |  |
| #48 | Document revision consistency | `48-document-revision-consistency` | Choice + Noul | L | A | #69, #70, #13 | simulator |
| #49 | Multi-agent task assignment | `49-multi-agent-task-assignment` | Score | L | A | #69, #28 |  |
| #50 | Model comparison and calibration | `50-model-comparison-and-calibration` | Choice + Noul + Score | L | A | #69, #64, #23, #38 | live run needed for real results |
| #51 | Stalled-loop detection | `51-stalled-loop-detection` | Choice | L | A | #69, #29 |  |
| #52 | Retrieval pipeline evaluation | `52-retrieval-pipeline-evaluation` | Choice + Score | L | A | #69, #17, #20, #30 |  |

### Wave 5: level 5, Expert (#53 to #60), tracked in #79

| Issue | Recipe | Slug | Types | Size | Round | Waits for | Flags |
| :---: | --- | --- | --- | :---: | :---: | --- | --- |
| #53 | Semantic feature discovery | `53-semantic-feature-discovery` | Noul + Score | XL | A | #69, #35 |  |
| #54 | Question and policy optimization | `54-question-and-policy-optimization` | Choice + Noul + Score | XL | A | #69, #64, #38 | live run needed for real results |
| #55 | Adaptive model routing | `55-adaptive-model-routing` | Choice + Score | XL | A | #69, #64, #50 | live run needed for real results |
| #56 | Adversarial harness evaluation | `56-adversarial-harness-evaluation` | Noul | XL | A | #69, #26, #41, #42 |  |
| #57 | Evidence graph updates | `57-evidence-graph-updates` | Choice + Noul | XL | A | #69, #70, #34, #47 | simulator |
| #58 | Simulated process supervision | `58-simulated-process-supervision` | Choice + Noul | XL | A | #69, #70, #43 | simulator |
| #59 | Observation and action selection | `59-observation-and-action-selection` | Choice | XL | A | #69, #70, #36 | simulator |
| #60 | Factory production control | `60-factory-production-control` | Choice + Noul + Score | XL | B | #69, #70, #43, #59 | simulator |

The manifest is the repository's planning record and is kept; reconcile it with live issues and relationships before each dispatch. Reading the recipe tables: round 0 is the reference recipe, built and merged alone before anything else in its wave. Round A recipes can start as soon as the wave opens. Round B recipes build on a round A recipe from the same wave and start after it merges. "Simulator" recipes also wait for #70, and recipes that need a live run for real results also wait for #64; both are in the "Waits for" column. Sizes are estimates: S about half a day of work, M a day, L two to three days, XL several days, and for L and XL expect a builder to need more than one run.

### Notes for particular waves

**Wave 0.** Foundation pull requests share files such as `pyproject.toml`, workflows, `CONTRIBUTING.md` and shared package interfaces, so even when built in parallel they integrate and merge one at a time, each updated against the last with a signed integration of current `main` and re-reviewed if its head changed. The one departure is the foundation-only manual ruling for an immaterial `main` advance in the [manual decision for an immaterial `main` advance](../docs/merge-readiness.md#manual-decision-for-an-immaterial-main-advance), which does not apply to a material advance or to any recipe. Do not start any recipe until #69 and the catalog coordination fix (#87) have merged. Close #74 only when its children meet their criteria and are delivered and verified, not just closed.

**Wave 1.** Build #1 alone. Give it two Opus reviews on the same final head and take their findings seriously even where they concern the template or the shared package rather than the recipe: this is the first real use of both. If it exposes a foundation problem, open an issue, fix the foundation through the normal pipeline, and only then start #2 to #10. From then on, every recipe builder is pointed at the merged #1.

**Waves 2 to 4.** Run round A in batches of up to six builders, and fewer when the review queue grows or runtime limits are lower; keep reviewer capacity in reserve. Feed forward what reviews find: if the same finding appears on two recipes, the fault is in the template or your brief, so fix it at the source and tell the builders still running.

**Wave 5.** These are the largest recipes. Run at most three builders at a time, expect multi-run builds, and split reviews by scope where needed. #50 (wave 4), #54, and #55 cannot reach real conclusions without live inference; until recorded evidence exists they are tested harnesses whose READMEs say results are not measured live, as their issues describe. Once #64 is merged and approved, record them within the shared $25 budget (rule 4); claim only what the recorded sample, model version and date support.

### After each recipe wave

Each recipe's README row is already updated by its own pull request (rule 6), so there is no post-wave README sync.

1. **Catalog audit.** Verify the catalog counts, links and generated content against `main` (`python tools/render_catalog.py --check` and the wave's rows). This confirms the README; it is not the first README update, and it never replaces the per-recipe regeneration.
2. **Consistency review.** One Opus agent reads every notebook from the wave side by side and reports differences in terminology, section order, chart style, the run-mode header, evidence quality and learner experience, and anything that reads as a claim about Jev. Open an issue for each real finding and run it through the pipeline.
3. **Close the level's tracking issue** (#75 to #79) only after its actual criteria are met.
4. **Progress comment on #80:** what merged, what is blocked and why, evidence, live spending against the $25 limit, and what you learned that changes the next wave's briefs.

### Wave 6: release (#73)

Run the audit that #73 describes, using Opus for the cross-recipe audit and Sonnet for the fixes, each fix through the normal pipeline. Draft the release notes in a pull request, including a plain statement of what was and was not exercised live. Stop there. Stop at the human gate: do not create or push `v1.0.0`, do not publish a release, and do not close #73 or #80. Tag approval is mine. The audit also covers fresh-clone offline execution on Linux and Windows, the full contract, link and provenance audit, and honest release notes on live coverage and limitations.

## The final audit

Before you report, re-enumerate every issue and pull request with pagination and verify completion issue by issue rather than from memory. For each issue in scope, confirm from GitHub that it is closed, that the pull request that closed it is merged, and which genuine Opus receipt (comment ID, reviewer, final head SHA) approved it. Confirm #74 to #79 are closed only if their criteria are met, that `python tools/render_catalog.py --check` passes on `main` with 60 of 60 published, and that CI on the reported `main` commit is green for every current check. Post the evidence table on #80: issue, pull request, reviewed head, Opus reviewer and comment, merge commit, checks, and closure or the precise blocker. Also report recipes delivered and live-recording coverage, cumulative live spending and unresolved reservations, the final `main` SHA, Linux and Windows validation, remaining human decisions (especially the release tag), and local worktree ownership. Remove only your own completed, clean, unused worktrees. Anything that fails this audit is not done, however it looked at the time; say "implementation complete, release approval pending" only when that is the true state.

## When something goes wrong

- **A builder says the issue is wrong or impossible.** Take it seriously and read the issue yourself. If the builder is right, fix the issue text, note the change in a comment, and rerun. The issues were written before any code existed and some will not survive contact with it. Where this file and the live repository disagree, reconcile through a reviewed pull request.
- **Builder and reviewer disagree.** Adjudicate as described above. If the disagreement is really about what the cookbook should promise readers, label `status: needs human` and ask me.
- **An agent stops unexpectedly.** Inspect its branch, worktree, pull request and handoff, then resume the same task under the same run identity and accounting without duplicating ownership. An intentional stop, a completed run, or an expired authorized window is not permission to restart or extend. Use backoff for rate limits and bounded waits with progress updates, and keep working on whatever independent authorized work remains.
- **CI fails on `main` after a merge.** Stop merging. Fixing `main` is the next task.
- **GitHub rate limits.** Slow down and reduce parallelism. Do not retry in a tight loop.
- **A design question the issues do not answer** and that would be costly to reverse across many recipes (an interface, a file format, a dependency). Decide it once in the foundation, write the decision into `CONTRIBUTING.md` or `docs/`, and apply it everywhere.
- **You are unsure whether something counts as approved.** It does not. Ask Opus again.

## This machine

- Windows with Git Bash; the repository enforces LF line endings through `.gitattributes`. Run Python tools with `python`.
- Commits are signed through the configured signing, and signatures are verified. A shim has occasionally failed with "Cannot open A for signing"; retry once, then diagnose. Never disable signing to get a commit or push through.
- `gh` is authenticated for this organization. The repository is private, so Actions minutes are metered; keep CI runs purposeful. Foundation work covers the supported Python versions (currently 3.10 and 3.14).
- Builders end commit messages with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## What to tell me, and when

Work through to the end without checking in, and do not stop while independent authorized work remains. Ask me only for what is mine to decide: genuinely missing authority or input, anything labelled `status: needs human` that blocks a wave, spending beyond the $25 limit on #80, a change to the repository's visibility, and the release tag.

When you finish or have to stop, give me a short report: what merged, what is open and why, every `status: needs human` item with the decision it needs, the final audit table, cumulative live spending, and a plain statement of what was and was not verified, including how much recorded live evidence exists.
