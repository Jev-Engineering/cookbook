# Orchestration prompt: complete every open issue

How to use this file: open Claude Code in a clone of `Jev-Engineering/cookbook` and say
"Read `orchestration/COMPLETE.md` and carry it out." Everything below the line is addressed to that session.

This is the successor to [`PROMPT.md`](PROMPT.md), which built the repository from empty. That file's
rules (roles, the Opus review gate, the merge procedure, the scope allowlist, the live-recording budget,
"Rules that hold throughout") are still in force and are not repeated here; this file says what to do
now, what is authorized, and the lessons that cost real rounds last time. Where the two differ, this file
wins for this run. [`TRIAGE.md`](TRIAGE.md) is the audit prompt; it never runs in the same session as
this one.

**Authorizations for this run. The operator edits this block before starting; anything not marked yes is
not authorized.**

| Action | Authorized |
| --- | --- |
| Open branches, pull requests and comments; squash-merge a pull request that has a genuine Opus approval of its exact head and green checks | yes |
| Open the missing recipe issues for catalog ranks 61 to 100 and record their numbers in `catalog/recipes.json` through a reviewed pull request | **no, ask first** |
| Live Jev recording within the cumulative $25 limit on #80 | **no, offline only** |
| Push the release tag, publish a release, change repository settings or protection rules | never; #73 stays for the operator |

---

You are orchestrating completion of the Jev Cookbook: close every open issue in
`Jev-Engineering/cookbook` that can be closed by a merged, Opus-approved pull request, and report precisely
why each of the rest cannot be. You orchestrate; Sonnet subagents build and integrate; fresh Opus subagents
review. You do not write the code and you do not review it.

## Step 0: establish the facts, then plan

GitHub is the source of truth, not this file and not any ledger. Before dispatching anything:

1. `git fetch origin`. Use `origin/main` for every comparison. A local `main` ref in a shared checkout can
   be dozens of commits stale; never branch from it or report counts against it.
2. Read `CONTRIBUTING.md`, `docs/development.md`, `docs/merge-readiness.md`, the workflows, issue #80 with
   every owner-decision comment, and the latest `orchestration/handoffs/*/README.md` (a historical
   snapshot: read current GitHub state before acting on its proposals).
3. Enumerate open issues (with labels and dependencies), open pull requests (head SHA, checks, comments),
   remote branches, and the local worktrees other sessions may own. Check who already owns the run
   (existing supervisor sessions, open pull requests, unmerged branches, receipts) and resume or
   coordinate with them; never write to a branch or worktree another agent owns.
4. Verify what `model: "sonnet"` and `model: "opus"` resolve to in this harness and record it. Default
   service tier only. A review is only called Opus's if the reviewer reported an Opus model.
5. Write the plan: every open issue classified as one of: *ready*, *blocked on another issue*, *blocked on
   a human decision*, *epic or tracking*, *not completable by a pull request*. Waves, in order:
   1. the p1 foundation issues, then the foundation issues that later recipes depend on (the shared-code
      and CI gates), then the remaining foundation and docs issues by priority;
   2. recipes 51 to 60 (their dependencies are recipes 17, 20, 29, 30, 35 and the foundation above);
   3. the multimodal recipes 61 to 100, only once their issues exist and the Codex-built branches
      (`recipe/NN-*`, `foundation/multimodal-integration`) have been re-integrated with current `main`;
   4. epics #78 and #79 and the release audit #73, which you prepare but never close or tag.

Open work at the time of writing, to be re-measured: about 74 open issues, 11 of them recipe issues
(51 to 60 and #326), about 53 foundation issues, four epics or tracking issues, and the release audit.
Catalog ranks 61 to 100 exist on `main` but have `issue: null`, so a recipe pull request for them cannot
pass the scope check until issues are opened and recorded.

## The pipeline for one issue

Same as `PROMPT.md` "One issue, start to finish", with these additions earned the hard way:

- **Brief like a colleague.** A subagent knows only its brief: the issue, the files that define the rules,
  the paths it may touch, what done looks like, what to send back, and the resource rules below. A
  reviewer gets the pull request number and the issue and nothing about what to expect. When a prior
  review exists, the reviewer reads it only after forming its own view.
- **Integration is a separate, mechanical step.** When `main` has moved, a Sonnet integration worker makes
  a signed merge of `origin/main` into the branch (never a rebase, never a force-push), takes `main`'s
  `README.md` on conflict and re-runs `python tools/render_catalog.py`, and never edits recipe files. If a
  conflict cannot be resolved without weakening a check, it stops and reports. Any new head voids prior
  approvals and is reviewed again.
- **Fix rounds are bounded.** Send the reviewer's findings to a builder, and tell it to change only what
  the review asked for. A sweep or fix round that fixes things nobody named cannot be reviewed; anything
  new it finds is reported or filed, not smuggled in.
- **Reviews.** One fresh Opus reviewer per pull request; two independent reviewers (split by focus, for
  example tooling and tests versus catalog, docs and compatibility) for anything that changes shared
  tooling, the recipe guard, the scope check, the replay-key format, or an interface sixty recipes copy.
  Both must approve the same final head. Reviewers write their verdict to a file; you post it verbatim as
  a pull request comment after confirming the final line is exactly
  `OPUS-REVIEW: APPROVE <full-head-sha>` (or `CHANGES-NEEDED`) and the SHA is the current head.
- **Merge.** `python tools/check_merge_readiness.py --pr N --expected-head SHA` must say READY, all checks
  must be read per check (not inferred from `mergeStateStatus`), then
  `gh pr merge N --squash --match-head-commit SHA`. Then wait for CI on that exact `main` commit and read
  every check before the next merge. If `main` goes red, stop merging and fix it first.
- **Verify the issue.** Confirm the issue closed (or deliberately did not) and its acceptance criteria are
  actually met, not merely that the pull request merged.

## Traps that cost rounds last time

- **Closing keywords in prose.** GitHub closes an issue from the phrase "Closes #N" anywhere in a pull
  request body, even inside "this is not `Closes #N`". Write `Refs #N` for partial work and never quote
  the keyword. If an issue closes wrongly, reopen it with an explanation.
- **Claims in the pull request body are claims.** Reviewers found overclaims there repeatedly (items that
  had been reverted, a fixed-defect statement that was untrue, counts that were off by one). Tell builders
  to state only what the final diff contains, and have reviewers check the body against the diff. Edit a
  body before the final push to the merge gate, not after; a correction can be a comment.
- **A passing check is not a result.** Read the actual outputs. A cached `git grep` with a dead pathspec
  and a clean tree both return "no hits"; always run the instrument against a ref where it must find
  something. Notebooks are verified by executing a scratch copy and running
  `tools/check_notebook_fresh.py`; never execute in the tree under review.
- **Unaddressed disclosure is a defect.** When the data cannot support what the prose implies (a
  calibration that does nothing because every validation answer is right), the notebook must say so; do
  not reshape fixtures to make a number look good.
- **Tooling quirks.** `gh pr edit` can fail on the retired Projects (classic) GraphQL field; use
  `gh api -X PATCH repos/Jev-Engineering/cookbook/pulls/N -F body=@file`. A clone whose `origin` is a local
  path must push with the explicit `git@github.com:Jev-Engineering/cookbook.git` URL (no config change).
  Agent worktrees created with `isolation: "worktree"` land under `.claude/worktrees/` in the checkout;
  remove them after use.
- **Unsigned commits.** The repository requires signed commits. A branch with unsigned commits is not
  pushed; report it and let the operator decide how to re-sign.
- **Foundation work is not smuggled into recipe pull requests.** A recipe pull request touches only
  `recipes/<slug>/` plus the regenerated README regions. A gap in shared code becomes a foundation issue
  with its own pull request and review.
- **Other sessions share this machine and this checkout.** Do all mutations in worktrees you own; do not
  switch branches in a shared checkout under another reader; never stop or resume another session's
  agents.

## Resources

One heavy job at a time (pytest, notebook execution, dependency installs), under `nice -n 10`, with a
memory and process check first; back off if memory is low or there are 3000 or more processes. Long
background polling loops get killed under memory pressure: prefer short foreground checks of CI state.
Use fresh virtual environments per task and remove them afterwards; do not prune the shared `~/.cache/uv`.
Never run `wsl --shutdown`, `--terminate` or `-t`.

## Recipes 61 to 100 (multimodal track)

These were built by a Codex session in `/workspace/cookbook-multimodal` (ledger: `campaign.json`) and pushed
as branches, unreviewed and cut from an old `main`. The foundation they needed (catalog and tooling to 100,
image and `Box` support, request accounting) has been reviewed and merged; `main` has since gained more
image rules (a 280 px minimum, image-byte hashing in replay keys, an image-file contract and checker, a
notebook image policy, tile bounds). Treat every one of those branches as unintegrated: merge `origin/main`
in, resolve against the new image rules, re-run everything, then review. Recipe 77 has unsigned commits.
Uncommitted work in those worktrees stays with its owner. Do not open issues for these recipes unless the
authorizations table says yes; when it does, create one issue per rank with the catalog entry's title and
description, record the numbers in `catalog/recipes.json` through a reviewed foundation pull request, and
only then dispatch recipe pull requests, one recipe per branch `recipe/<slug>`.

## Offline only unless authorized

No live call, no `TYPESAFE_API_KEY`, no search for a credential, by you or any subagent, unless the
authorizations table grants live recording. If it does, follow `PROMPT.md` rule 4 exactly: one serialized
recorder, a durable budget ledger on #80, conservative caps, and `recorded` only for answers captured from
a real call. Never claim anything about Jev's real quality, latency or cost without that evidence.

## What "done" means

Keep a concise ledger as comments on #80 (issue or pull request, owner agent, resolved model, branch, head
SHA, receipts, CI run, next action, blocker); GitHub is your memory because your context will be summarized.
You are finished when every open issue is either closed by a merged, Opus-approved pull request whose exact
`main` commit has green CI, or carries a precise blocker (`status: needs human` plus the missing decision or
authority). Your final report lists: issues closed with their merge commits, issues left open with the exact
reason, anything you found but did not fix (filed as issues, not smuggled in), the resolved models used, and
that no live call or spend occurred (or the exact accounting if one was authorized). #73 is prepared up to
the tag, with release notes drafted, and left for the operator.
