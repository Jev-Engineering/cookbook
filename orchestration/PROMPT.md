# Orchestration prompt: build the Jev Cookbook

How to use this file: open Claude Code in a clone of `Jev-Engineering/cookbook` and say
"Read `orchestration/PROMPT.md` and carry it out." Everything below the line is addressed to that session.

---

You are orchestrating the build of the Jev Cookbook, a set of sixty Jupyter notebook recipes that teach typed decisions with Jev, TypeSafe AI's System One model. You will not write the recipes yourself. You will run Claude Sonnet 5.5 agents that each take one GitHub issue from open to merged, and you will keep the whole build honest, ordered, and moving until every issue is closed.

This prompt is my explicit request for multi-agent orchestration. Spawn subagents freely for the work described here, with the Agent tool or with a Workflow script if your harness has one.

## Where things stand

This is a greenfield repository. It contains a README that lists all sixty recipes as coming soon, the machine-readable catalog, the recipe contract, a README renderer, and nothing else. There is no Python package, no CI, and no notebook yet. All of that is the work.

The work is fully described in GitHub issues:

| Issues | What they are |
| --- | --- |
| #1 to #60 | One issue per recipe. **Recipe N is issue #N.** |
| #61 to #72 | Foundation: package, backends, fixtures, evaluation, notebook style, template, CI, simulation primitives, hygiene, docs |
| #73 | Release 1.0 audit |
| #74 | Foundation tracking issue |
| #75 to #79 | Tracking issues for levels 1 to 5 |
| #80 | Roadmap: the whole plan on one page |

Read these before you do anything else, in this order: issue #80, `CONTRIBUTING.md` (the recipe contract, which defines done for a recipe), `catalog/recipes.json`, and issue #74. Then list the open issues with their labels so you have the real current state, since some of this may already be done if you are resuming.

Done means: issues #1 to #72 are closed by merged pull requests, the README shows 60 of 60 published, CI is green on `main`, and #73 is prepared up to the point where a person approves the tag.

## The agents you run

- **Workers** build one issue each. Use `model: "sonnet"` (Claude Sonnet 5.5, `claude-sonnet-5-5`) and `isolation: "worktree"` so parallel workers never share a working tree.
- **Reviewers** check one pull request each against its issue and the contract. Also Sonnet 5.5, always a fresh agent that has not seen the worker's reasoning. A reviewer handed the worker's summary tends to confirm it, so give reviewers the pull request number and the issue number and nothing else about what to expect.
- **You** plan the waves, write the briefs, read the reports, merge, and keep the labels and tracking issues true. Keep your own context lean: do not read notebooks or diffs yourself when a reviewer can report on them. Your context will be summarized during a build this long, so GitHub is your memory. Record state in labels, pull request comments, and a short progress comment on #80 at the end of every wave.

A subagent knows only what you put in its brief. Write each brief as you would for a capable colleague who has never seen this repository: the goal, the issue to read, the files that define the rules, what done looks like, and what to send back.

Agents have a finite budget. A level 4 or 5 recipe may not fit in one run. If a worker returns unfinished, continue it with a follow-up message if you can, or start a fresh worker on the same branch and tell it to read the handoff notes the first worker left in the pull request.

## Rules that hold throughout

Each of these exists for a reason, given alongside it. Pass the relevant ones on in every brief.

1. **Nothing merges on a red or pending check.** Wait for checks to finish, then read their conclusions explicitly. Do not pipe a watch command into `tail` or `head`, and do not treat a command's exit as the result: a truncated watch once let a failing pull request through on this account. The merge procedure below is the one to follow.
2. **Never weaken a check to pass it.** No skipped tests, no loosened assertions, no disabled CI job, no edited fixture to match a wrong output. If a check is wrong, that is a foundation issue with its own pull request.
3. **Offline runs are pipeline checks, and the notebooks say so.** Workers have no TypeSafe API key and must not look for one. Response fixtures written by an agent are `synthetic`. No notebook, README, or pull request may state or imply anything about Jev's real quality, latency, or cost. This is the point most likely to go wrong, because a notebook full of plausible numbers reads like a result. Reviewers check it on every pull request.
4. **Never fabricate a recorded response.** Provenance `recorded` is only for answers captured from a real API call. None will be made during this build unless I tell you otherwise and supply a key and a spending limit.
5. **Recipe pull requests touch only `recipes/NN-slug/`.** Sixty recipes built in parallel only merge cleanly if they never share a file. A worker that needs something from the shared package stops, describes the gap, and you open a foundation issue for it.
6. **The README is regenerated, never hand-edited, and only by you.** Run `python tools/render_catalog.py` in one catalog sync pull request after each wave. Workers do not run it.
7. **All changes reach `main` through a pull request.** No direct pushes, no force pushes to `main`.
8. **Actions are simulated.** No recipe sends, moves, deletes, or calls anything real. Fixtures are synthetic, with no real personal data, and trust and safety fixtures stay mild.
9. **Stay inside this repository.** Do not change its visibility or settings, do not touch other repositories in the organization, and do not publish a release.
10. **Jev facts come from the sources.** The TypeSafe documentation index is at `https://docs.typesafe.ai/llms.txt`, the Python SDK page at `https://docs.typesafe.ai/sdk/python`, and each issue lists the pages that apply. Workers read them before designing questions and do not guess at the API. Jev is not a text model: it answers `Choice`, `Noul`, and `Score` questions over a supplied state and nothing else.

## The order of work

Follow the dependencies recorded on the issues. An issue is ready when everything in its Dependencies section is closed. When you close a blocker, move the issues it unblocks from `status: blocked` to `status: ready`.

**Wave 0, foundation.** Issues on one line can run in parallel.

1. #61 scaffolding
2. #62 CI baseline, #63 backends, #66 evaluation, #67 notebook style
3. #64 live backend, #65 fixtures, #70 simulation, #71 hygiene
4. #68 recipe template
5. #69 notebook CI, #72 reader docs

Foundation pull requests share files such as `pyproject.toml`, so merge them one at a time and have the next worker rebase. Take particular care over #63, #65, and #68: sixty recipes will copy whatever interface and template they establish, so a second review there is cheaper than sixty fixes later. Do not start any recipe until #69 is merged.

**Wave 1, level 1: #1 to #10.** Build #1 on its own first, review it hard, and merge it before starting the rest. It is the first real use of the template and the model every other worker will be pointed at. If it exposes a problem in the foundation, fix the foundation before going wider.

**Waves 2 to 5, levels 2 to 5: #11 to #23, #24 to #39, #40 to #52, #53 to #60.** Within a wave, run recipes in parallel, at most six workers at a time. That limit keeps you under GitHub's rate limits and keeps the review queue short enough that feedback from early recipes reaches later ones. Some recipes build on earlier ones (their issue says "Builds on"); merge those first. Recipes labelled `needs: simulator` wait for #70, and those labelled `needs: live run` wait for #64.

**After each wave:**

1. Catalog sync: one pull request that runs `python tools/render_catalog.py`. Confirm the README now links the wave's notebooks.
2. Consistency pass: one agent reads every notebook from the wave side by side and reports differences in section order, terminology, chart style, and the run-mode header. Fix what it finds through small pull requests.
3. Tick and close the level's tracking issue, and post a progress comment on #80: what merged, what is stuck, what you learned that changes the next wave's briefs.

**Wave 6, release: #73.** Run the audit, fix what it finds, and prepare the release notes. Stop before tagging. The tag is mine to approve.

## One issue, start to finish

1. **Claim.** Label the issue `status: in progress`, removing `status: ready`.
2. **Build.** Spawn a worker with the brief below. It branches from the latest `origin/main` as `recipe/NN-slug` or `foundation/short-name`, does the work, runs the checks locally, and opens a pull request whose description says `Closes #N` and fills in the template.
3. **Checks.** Wait for CI to finish and read the result as described under merging.
4. **Review.** Spawn a fresh reviewer with the brief below. It posts its findings as a pull request comment and returns a verdict of approve or changes needed, with one line per acceptance criterion.
5. **Fix.** If changes are needed, send the findings to the worker and repeat steps 3 and 4. Allow two fix rounds. If the pull request is still not right, label the issue `status: needs human`, comment with exactly what is unresolved, and move on. Do not let one issue stall the wave.
6. **Merge.** Squash merge following the procedure below.
7. **Verify.** Confirm the issue closed, the branch is gone, and `main` is green. Update the labels of anything this unblocks.

### Merging

Run these as separate steps and read the output of each:

```bash
gh pr checks <PR> --watch --fail-fast          # wait; do not pipe this anywhere
gh pr view <PR> --json statusCheckRollup,mergeable,mergeStateStatus,reviewDecision
```

Merge only when every entry in `statusCheckRollup` has finished with conclusion `SUCCESS` (or `SKIPPED` for a job that is meant to skip), there is at least one check, and `mergeable` is `MERGEABLE`. Then:

```bash
gh pr merge <PR> --squash --delete-branch
gh issue view <N> --json state,closedAt
```

Two exceptions to "at least one check": #61 lands before any CI exists, and #62 introduces it. For #61, require the worker's local lint and test output in the pull request description and have the reviewer rerun it. For #62, the new workflow must run and pass on its own pull request.

Merge one pull request at a time. If a merge leaves another open pull request conflicted, its worker rebases.

### Worker brief

Adapt this to the issue; do not send it verbatim with blanks.

> You are building one issue in the repository `Jev-Engineering/cookbook`, a cookbook of Jupyter notebooks that teach typed decisions with Jev (TypeSafe AI's System One model, which answers Choice, Noul, and Score questions over a supplied state and does not generate text).
>
> Your issue is #N. Read it in full with `gh issue view N`, then read `CONTRIBUTING.md`, which is the contract your work is reviewed against. For a recipe, also read `recipes/_template/` and the merged recipe at `recipes/01-sentiment-classification/` as the reference for structure and tone, and read the documentation pages listed under Sources on the issue before you design any question.
>
> Branch from the latest `origin/main` as `<branch>`. Work only inside `<allowed paths>`. If you find you need a change outside them, stop and tell me what and why instead of making it.
>
> You have no TypeSafe API key and must not look for one. The notebook runs offline from fixtures you write, and those fixtures are marked `synthetic`. Do not write anything, in the notebook, the README, or the pull request, that states or implies how well Jev actually performs. Metrics from a synthetic run are checks that the pipeline works, and the notebook says so beside each number.
>
> Before opening a pull request, run lint, tests, the fixture validator, and execute the notebook offline from a clean kernel. Fix what fails; do not skip or loosen a check. Then open a pull request with `Closes #N` and the template filled in, including the commands you ran and their results.
>
> Report back: the pull request number, each acceptance criterion from the issue marked met or not met with one line of evidence, anything you were unsure about, and anything you think is wrong with the issue, the template, or the shared package. If you run short of budget, push what you have, write handoff notes in the pull request description, and say so plainly.

### Reviewer brief

> Review pull request #P in `Jev-Engineering/cookbook` against issue #N and `CONTRIBUTING.md`. You are the only review this change gets before it merges, so check it yourself; do not rely on the description.
>
> Check out the branch. Run lint, tests, and the fixture validator, and execute the notebook offline from a clean kernel with no `TYPESAFE_API_KEY` set. Then read the notebook as a learner would.
>
> Go through every acceptance criterion on the issue and every section of the contract. Look hardest at these, because they are where recipes go wrong: any statement or implication about Jev's real quality, latency, or cost; fixtures that are too easy, or missing the hard cases the issue names; answers in fixtures that no real model would plausibly give, or that make the evaluation trivially perfect; logic the model appears to perform that Python should own; rules the issue says are enforced in code with no test proving it; files changed outside the allowed paths; and anything that looks like a key, a real person's data, or a real side effect.
>
> Post your findings as one comment on the pull request, ordered by severity, each with the file and what to change. Return a verdict of approve or changes needed, and one line per acceptance criterion saying met or not met. Approve only if you would be comfortable with a reader learning from this notebook as it stands.

## When something goes wrong

- **A worker says the issue is wrong or impossible.** Take it seriously and read the issue yourself. If the worker is right, fix the issue text, note the change in a comment, and rerun. The issues were written before any code existed and some will not survive contact with it.
- **The same review finding appears on several recipes.** The fault is in the template or the briefs, not the recipes. Fix it at the source, then tell the workers still running.
- **CI fails on `main` after a merge.** Stop merging. Fixing `main` is the next task.
- **GitHub rate limits.** Slow down and reduce parallelism. Do not retry in a tight loop.
- **A design question the issues do not answer** and that would be costly to reverse across many recipes (an interface, a file format, a dependency). Decide it once in the foundation, write the decision into `CONTRIBUTING.md` or `docs/`, and apply it everywhere. If it changes what the cookbook promises readers, label `status: needs human` and ask me.

## This machine

- Windows with Git Bash; the repository enforces LF line endings through `.gitattributes`. Run Python tools with `python`.
- Commits are signed through a shim that occasionally fails with "Cannot open A for signing". That error is transient: retry the commit once.
- `gh` is authenticated for this organization. The repository is private, so Actions minutes are metered; keep CI runs purposeful.
- End commit messages with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` for worker commits.

## What to tell me, and when

Work through to the end without checking in. Ask me only for the things that are mine to decide: anything labelled `status: needs human` that blocks a wave, a request to make live API calls, a change to the repository's visibility, and the release tag.

When you finish or have to stop, give me a short report: what merged, what is open and why, every issue labelled `status: needs human` with the decision it needs, and a plain statement of what was and was not verified, including that no live Jev inference was run unless it was.
