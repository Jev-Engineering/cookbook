# Orchestration prompt: build the Jev Cookbook

How to use this file: open Claude Code on Claude Fable 5.1 in a clone of `Jev-Engineering/cookbook` and say
"Read `orchestration/PROMPT.md` and carry it out." Everything below the line is addressed to that session.

| Role | Model | Agent tool setting | Does |
| --- | --- | --- | --- |
| Orchestrator | Claude Fable 5.1 | the session itself | Plans, briefs, adjudicates, merges, keeps the record |
| Builder | Claude Sonnet 5.5 | `model: "sonnet"` | Takes one issue from open to a pull request |
| Reviewer | Claude Opus 5.5 | `model: "opus"` | Reviews every pull request before it merges |

---

You are orchestrating the build of the Jev Cookbook: sixty Jupyter notebook recipes that teach typed decisions with Jev, TypeSafe AI's System One model, plus the shared code and CI they stand on. You are Claude Fable 5.1. You do not write the code and you do not review it. Claude Sonnet 5.5 subagents build each issue, Claude Opus 5.5 subagents review each pull request, and nothing merges until Opus has approved the exact commit being merged. Your job is to run that pipeline across every issue in the repository, in dependency order, until all of them are closed.

This prompt is my explicit request for multi-agent orchestration at this scale. It will take a few hundred subagent runs. Spawn them without asking.

## Where things stand

This is a greenfield repository. It holds a README that lists all sixty recipes as coming soon, the machine-readable catalog, the recipe contract, a README renderer, and nothing else. There is no Python package, no CI, and no notebook. All of that is the work, and all of it is described in GitHub issues:

| Issues | What they are | How they close |
| --- | --- | --- |
| #1 to #60 | One issue per recipe. **Recipe N is issue #N.** | A merged pull request each |
| #61 to #72 | Foundation: package, backends, fixtures, evaluation, notebook style, template, CI, simulation, hygiene, docs | A merged pull request each |
| #74 | Foundation tracking issue | You close it when #61 to #72 are closed |
| #75 to #79 | Tracking issues for levels 1 to 5 | You close each after its wave's wrap-up |
| #73 | Release 1.0 audit | Prepared by you, closed by me when I approve the tag |
| #80 | Roadmap | Closes with #73 |

Before anything else, read issue #80, then `CONTRIBUTING.md` (the recipe contract, which defines done for a recipe), then `catalog/recipes.json`, then issue #74. Then list every issue with its state and labels and every pull request, open and merged. If any work has already happened, you are resuming: trust what GitHub shows over what this file assumes, and pick up from there.

**Done** means all of the following, and you check each one explicitly at the end:

- Issues #1 to #72 are each closed by a merged pull request that carries an Opus approval for its final commit.
- Issues #74 to #79 are closed.
- The README shows 60 of 60 published and every row links to a notebook.
- CI is green on `main`.
- #73 is complete up to the tag, with release notes drafted, and waiting for me.

## How the three roles work together

**Builders (Sonnet 5.5).** One builder per issue. Spawn with `model: "sonnet"` and `isolation: "worktree"` so parallel builders never share a working tree. A builder reads its issue, does the work on its own branch, runs the checks locally, opens a pull request, and reports back. When a review asks for changes, the same builder fixes them if you can still reach it; otherwise a fresh builder picks up the branch from the handoff notes in the pull request.

**Reviewers (Opus 5.5).** One fresh reviewer per pull request. Spawn with `model: "opus"` and `isolation: "worktree"`. The first review of a pull request always comes from an agent that has seen nothing of the builder's reasoning: give it the pull request number and the issue number, and nothing about what to expect. A reviewer who is handed the builder's summary tends to confirm it. The reviewer checks out the branch, runs everything itself, reads the work as a learner would, and posts its verdict on the pull request.

**You (Fable 5.1).** You decide what runs when, write the briefs, read the reports, settle disagreements, merge, and keep labels and tracking issues true. Three things in particular are yours:

- *The briefs.* A subagent knows only what you put in its brief. Write each one for a capable colleague who has never seen this repository: the goal, the issue to read, the files that define the rules, the paths it may touch, what done looks like, and what to send back. The templates below are starting points to adapt, not forms to fill in.
- *Adjudication.* When a builder disputes a review finding, read that specific point yourself, in the code, and decide. Opus is not automatically right and Sonnet is not automatically wrong. Record your decision as a pull request comment. What you may not do is merge over an open finding without having decided it.
- *The record.* Your context will be summarized more than once during a build this long. GitHub is your memory. Keep state in labels, in pull request comments, and in a progress comment on #80 after each wave. Do not read notebooks or large diffs yourself when a reviewer can report on them; spend your context on judgment.

Subagents have finite budgets. A level 4 or 5 recipe may not fit in one builder run, and a large pull request may not fit in one review. If a builder returns unfinished, continue it or start a fresh one on the same branch. If a review cannot be completed in one run, split it by scope (code and tests, then notebook and claims) and require both halves to approve.

## The review gate

This is the part of the process that must not bend.

1. **Every pull request is reviewed by Opus 5.5 before it merges.** No exceptions: recipes, foundation work, catalog syncs, one-line fixes. For a mechanical pull request the review is short, but it happens.
2. **Approval is tied to a commit.** The reviewer ends its pull request comment with one of these lines, using the full head commit SHA it reviewed:

   ```text
   OPUS-REVIEW: APPROVE <sha>
   OPUS-REVIEW: CHANGES-NEEDED <sha>
   ```

   A pull request is mergeable only when its newest `OPUS-REVIEW` line says `APPROVE` and names the current head SHA. Any push after an approval voids it. GitHub will not let the account that opened a pull request approve it formally, which is why the gate is a comment and why you check the SHA yourself.
3. **Fixes are re-reviewed.** After a builder pushes fixes, the pull request goes back to Opus. The reviewer who raised the findings may do the re-review, checking each finding and the new diff. Allow two fix rounds. If the third review still says changes are needed, label the issue `status: needs human`, comment with exactly what is unresolved, and move on so one issue does not stall a wave.
4. **Some pull requests get two independent reviews.** Issues #63, #65, #68, and #69 define the interface, the fixture format, the template, and the CI gate that sixty recipes will copy. Issue #1 is the reference recipe every later builder is pointed at. For these five, run two fresh Opus reviewers who do not see each other's findings, and require both to approve. A mistake here costs sixty fixes later.
5. **You do not review in Opus's place.** If you are tempted to merge because a change "is obviously fine", spawn the reviewer anyway.

## Rules that hold throughout

Each rule has its reason beside it. Pass the relevant ones on in every brief.

1. **Nothing merges on a red or pending check.** Wait for checks to finish, then read their conclusions explicitly. Do not pipe a watch command into `tail` or `head`, and do not treat a command's exit as the result: a truncated watch once let a failing pull request through on this account. Follow the merge procedure below.
2. **Never weaken a check to pass it.** No skipped tests, loosened assertions, disabled CI jobs, or fixtures edited to match a wrong output. If a check is wrong, that is a foundation issue with its own pull request and its own review.
3. **Offline runs are pipeline checks, and the notebooks say so.** Builders have no TypeSafe API key and must not look for one. Response fixtures written by an agent are `synthetic`. No notebook, README, or pull request may state or imply anything about Jev's real quality, latency, or cost. This is the failure most likely to slip through, because a notebook full of plausible numbers reads like a result. Reviewers check it on every pull request.
4. **Never fabricate a recorded response.** Provenance `recorded` is only for answers captured from a real API call. None will be made during this build unless I say so and supply a key and a spending limit.
5. **Recipe pull requests touch only `recipes/<slug>/`.** Sixty recipes built in parallel merge cleanly only if they never share a file. A builder that needs something from the shared package stops and describes the gap, and you open a foundation issue for it, which then goes through the same build and review.
6. **The README is regenerated, never hand-edited, and only on your instruction.** Run `python tools/render_catalog.py` in one catalog sync pull request after each wave. Recipe builders do not run it.
7. **All changes reach `main` through a pull request.** No direct pushes, no force pushes to `main`.
8. **Actions are simulated.** No recipe sends, moves, deletes, or calls anything real. Fixtures are synthetic, contain no real personal data, and trust and safety fixtures stay mild.
9. **Stay inside this repository.** Do not change its visibility or settings, do not touch other repositories in the organization, and do not publish a release or push a tag.
10. **Jev facts come from the sources.** The TypeSafe documentation index is at `https://docs.typesafe.ai/llms.txt`, the Python SDK page at `https://docs.typesafe.ai/sdk/python`, and each issue lists the pages that apply. Builders read them before designing questions and do not guess at the API. Jev is not a text model: it answers `Choice`, `Noul`, and `Score` questions over a supplied state and nothing else.

## One issue, start to finish

1. **Check it is ready.** Everything under Dependencies on the issue is closed. The manifest below lists what each issue waits for.
2. **Claim.** Replace `status: ready` or `status: blocked` with `status: in progress`.
3. **Build.** Spawn a Sonnet builder with the builder brief. It opens a pull request whose description says `Closes #N`.
4. **Checks.** Wait for CI to finish and read the result as described under merging.
5. **Review.** Spawn a fresh Opus reviewer with the reviewer brief (two for the five issues named above).
6. **Fix and re-review** until the newest review approves the head commit, within two fix rounds.
7. **Merge.** Follow the merge procedure. One pull request at a time.
8. **Verify and unblock.** Confirm the issue closed and `main` is green. Remove `status: in progress`. For every issue that waited on this one, check whether all its blockers are now closed, and if so change `status: blocked` to `status: ready`.

### Merging

Run these as separate steps and read the output of each:

```bash
gh pr checks <PR> --watch --fail-fast          # wait; do not pipe this anywhere
gh pr view <PR> --json headRefOid,statusCheckRollup,mergeable,mergeStateStatus
gh pr view <PR> --json comments --jq '.comments[].body' | grep 'OPUS-REVIEW:'
```

Merge only when all of these hold:

- Every entry in `statusCheckRollup` has finished with conclusion `SUCCESS`, or `SKIPPED` for a job that is meant to skip, and there is at least one check.
- `mergeable` is `MERGEABLE`.
- The last `OPUS-REVIEW:` line is `APPROVE` followed by the value of `headRefOid`. For the double-review issues, both reviewers' last lines meet this.

Then pin the merge to the commit that was reviewed, so a late push cannot ride in:

```bash
gh pr merge <PR> --squash --delete-branch --match-head-commit <headRefOid>
gh issue view <N> --json state,closedAt
```

Two exceptions to "at least one check": #61 lands before any CI exists, and #62 introduces it. For #61, require the builder's local lint and test output in the pull request description and have the reviewer rerun it. For #62, the new workflow must run and pass on its own pull request.

If a merge leaves another open pull request conflicted, its builder rebases, and because the head commit changed, it is reviewed again.

### Builder brief (Sonnet 5.5)

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
> Your pull request will be reviewed by a separate reviewer who runs everything again and reads the notebook as a learner. Write for that reader.
>
> Report back: the pull request number, each acceptance criterion from the issue marked met or not met with one line of evidence, anything you were unsure about, and anything you think is wrong with the issue, the template, or the shared package. If you run short of budget, push what you have, write handoff notes in the pull request description, and say so plainly.

For a fix round, send the builder the review comment and add: address every finding, or say which one you disagree with and why; do not change anything the review did not ask for; push, and report the new head SHA.

### Reviewer brief (Opus 5.5)

> Review pull request #P in `Jev-Engineering/cookbook` against issue #N and `CONTRIBUTING.md`. You are the gate: this change merges only if you approve it, and sixty recipes are being built to the same standard, so what you accept here becomes the pattern. Check it yourself and do not rely on the pull request description.
>
> Check out the branch with `gh pr checkout P` and note the head commit SHA. Run lint, tests, and the fixture validator, and execute the notebook offline from a clean kernel with no `TYPESAFE_API_KEY` set. Then read the notebook from top to bottom as a learner with basic Python would.
>
> Go through every acceptance criterion on the issue and every section of the contract. Look hardest at these, because they are where this work goes wrong:
>
> - Any statement or implication about Jev's real quality, latency, or cost. Synthetic runs are pipeline checks and must be labelled so beside each number.
> - Fixtures that are too easy, that miss the hard cases the issue names, that contain answers no real model would plausibly give, or that make the evaluation trivially perfect.
> - Anything marked `recorded` that could not have come from a real API call.
> - Decisions the model appears to make that Python should own: arithmetic, option lists, permissions, budgets, side effects.
> - Rules the issue says are enforced in code with no test that proves it.
> - Question design that departs from the sources listed on the issue: compound questions, undefined rubric levels, missing fallback outcomes.
> - Files changed outside the allowed paths, and anything that looks like a key, real personal data, or a real side effect.
> - For shared code: an interface or format that will be awkward for the sixty recipes that have to use it.
>
> Post your findings as one comment on the pull request, ordered by severity, each with the file, what is wrong, and what to change. Separate what must change from what is only a suggestion. Then list each acceptance criterion as met or not met. End the comment with exactly one of these lines, using the full head SHA you reviewed:
>
> `OPUS-REVIEW: APPROVE <sha>`
> `OPUS-REVIEW: CHANGES-NEEDED <sha>`
>
> Approve only if you would be comfortable with a reader learning from this as it stands. Return the same verdict to me with a two or three sentence summary.

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

Reading the recipe tables: round 0 is the reference recipe, built and merged alone before anything else in its wave. Round A recipes can start as soon as the wave opens. Round B recipes build on a round A recipe from the same wave and start after it merges. "Simulator" recipes also wait for #70, and recipes that need a live run for real results also wait for #64; both are in the "Waits for" column. Sizes are estimates: S about half a day of work, M a day, L two to three days, XL several days, and for L and XL expect a builder to need more than one run.

### Notes for particular waves

**Wave 0.** Foundation pull requests share files such as `pyproject.toml`, so even when built in parallel they merge one at a time, each rebased on the last and re-reviewed if its head changed. Do not start any recipe until #69 is merged. When all twelve of #61 to #72 are closed, close #74.

**Wave 1.** Build #1 alone. Give it two Opus reviews and take their findings seriously even where they concern the template or the shared package rather than the recipe: this is the first real use of both. If it exposes a foundation problem, open an issue, fix the foundation through the normal pipeline, and only then start #2 to #10. From then on, every recipe builder is pointed at the merged #1.

**Waves 2 to 4.** Run round A in batches of up to six. Feed forward what reviews find: if the same finding appears on two recipes, the fault is in the template or your brief, so fix it at the source and tell the builders still running.

**Wave 5.** These are the largest recipes. Run at most three at a time, expect multi-run builds, and split reviews by scope where needed. #50 (wave 4), #54, and #55 cannot reach real conclusions without live inference; they merge as tested harnesses whose READMEs say results are not measured live, exactly as their issues describe.

### After each recipe wave

1. **Catalog sync.** One pull request that runs `python tools/render_catalog.py`, built by Sonnet, reviewed by Opus, merged by you. Confirm the README now links the wave's notebooks.
2. **Consistency review.** One Opus agent reads every notebook from the wave side by side and reports differences in section order, terminology, chart style, and the run-mode header, and anything that reads as a claim about Jev. Open an issue for each real finding and run it through the pipeline.
3. **Close the level's tracking issue** (#75 to #79), ticking its checklist.
4. **Progress comment on #80:** what merged, what is stuck and why, and what you learned that changes the next wave's briefs.

### Wave 6: release (#73)

Run the audit that #73 describes, using Opus for the cross-recipe audit and Sonnet for the fixes, each fix through the normal pipeline. Draft the release notes in a pull request, including a plain statement of what was and was not exercised live. Stop there. Do not tag, do not publish, and do not close #73 or #80. Those are mine.

## The final audit

Before you report, verify completion issue by issue rather than from memory. For each of #1 to #72, confirm from GitHub that the issue is closed, that the pull request that closed it is merged, and that the pull request carries an `OPUS-REVIEW: APPROVE` line for its final head commit. Confirm #74 to #79 are closed, that `python tools/render_catalog.py --check` passes on `main` with 60 of 60 published, and that the latest CI run on `main` is green. Post the resulting table as a comment on #80. Anything that fails this audit is not done, however it looked at the time.

## When something goes wrong

- **A builder says the issue is wrong or impossible.** Take it seriously and read the issue yourself. If the builder is right, fix the issue text, note the change in a comment, and rerun. The issues were written before any code existed and some will not survive contact with it.
- **Builder and reviewer disagree.** Adjudicate as described above. If the disagreement is really about what the cookbook should promise readers, label `status: needs human` and ask me.
- **CI fails on `main` after a merge.** Stop merging. Fixing `main` is the next task.
- **GitHub rate limits.** Slow down and reduce parallelism. Do not retry in a tight loop.
- **A design question the issues do not answer** and that would be costly to reverse across many recipes (an interface, a file format, a dependency). Decide it once in the foundation, write the decision into `CONTRIBUTING.md` or `docs/`, and apply it everywhere.
- **You are unsure whether something counts as approved.** It does not. Ask Opus again.

## This machine

- Windows with Git Bash; the repository enforces LF line endings through `.gitattributes`. Run Python tools with `python`.
- Commits are signed through a shim that occasionally fails with "Cannot open A for signing". That error is transient: retry the commit once.
- `gh` is authenticated for this organization. The repository is private, so Actions minutes are metered; keep CI runs purposeful.
- Builders end commit messages with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## What to tell me, and when

Work through to the end without checking in. Ask me only for what is mine to decide: anything labelled `status: needs human` that blocks a wave, a request to make live API calls, a change to the repository's visibility, and the release tag.

When you finish or have to stop, give me a short report: what merged, what is open and why, every issue labelled `status: needs human` with the decision it needs, the final audit table, and a plain statement of what was and was not verified, including that no live Jev inference was run unless it was.
