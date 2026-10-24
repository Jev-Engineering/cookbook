# Resolution prompt: take one issue to a merged pull request

How to use this file: open Claude Code in a clone of `Jev-Engineering/cookbook` and say "Read
`orchestration/RESOLVE.md` and carry it out." Name an issue to pin the choice ("…and carry it out
for #327"); with none named, the session picks one by the selection rule in step 1. Add "and keep
going" to run issues back to back, one at a time, until told to stop. Everything below the line is
addressed to that session.

This is the per-issue loop. [`PROMPT.md`](PROMPT.md) and [`COMPLETE.md`](COMPLETE.md) stay in force
and are not repeated here: the roles, the scope allowlist, "Rules that hold throughout", the builder
and reviewer briefs, the merge procedure, the traps, and the resource rules. This file changes one
thing and adds the discipline around it: **a pull request now passes two review gates on the same
head before it merges** — a fresh Opus reviewer and a high-effort `/code-review` pass — and nothing
merges while either gate, or any check, has an open item. [`TRIAGE.md`](TRIAGE.md) is the audit
prompt and never runs in the same session as this one.

**Authorizations for this run. The operator edits this block before starting; anything not marked
yes is not authorized.**

| Action | Authorized |
| --- | --- |
| Branch, push, open a pull request, comment, and squash-merge a pull request that passes both gates with a complete green check set | yes |
| Open follow-up issues for anything found but out of scope | yes |
| Open the missing recipe issues for catalog ranks 61 to 100 | **no, ask first** |
| Live Jev recording (`TYPESAFE_API_KEY`, any spend) | **no, offline only** |
| Push a tag, publish a release, change repository settings or protection rules, admin-merge, force-push | never |

---

You take **one open issue** from `Jev-Engineering/cookbook` to a merged pull request, or you report
the precise reason it cannot get there. You orchestrate: Sonnet subagents build and integrate, a
fresh Opus subagent reviews, and you run the second gate, adjudicate, and merge. You do not write
the code, and your own opinion never replaces a gate.

## Step 0: ground truth

1. `git fetch origin` and compare everything against `origin/main`. A local `main` in a shared
   checkout is routinely dozens of commits stale; never branch from it or count against it.
2. Read `CONTRIBUTING.md` (the contract), `docs/development.md` (the checks), and
   `docs/merge-readiness.md` (the merge gate). Read issue #80 with its owner-decision comments and
   the newest `orchestration/handoffs/*/README.md` — a historical snapshot, so confirm current
   GitHub state before acting on anything it proposes.
3. Enumerate, with pagination: open issues (labels, dependencies), open pull requests (head SHA,
   checks, comments, review threads), remote branches, and the worktrees under `.claude/worktrees/`.
   GitHub is the source of truth, not this file, not `.claude/issues.json`, not any ledger.
4. Check ownership before you touch anything: another session may already own the issue, its branch,
   or its worktree. Resume or coordinate; never write to a branch or worktree you do not own, and
   never stop or resume another session's agents.
5. Verify what `model: "sonnet"` and `model: "opus"` resolve to in this harness and record it.
   Default service tier. A review is only Opus's if the reviewer reported an Opus model.
6. Receipts live in the untracked `.claude/` directory (`.claude/review-<PR>-opus.md`,
   `.claude/review-<PR>-codereview.md`, `.claude/readiness-<PR>.txt`, `.claude/pr<PR>-body.md`) and
   never enter a commit.

## Step 1: choose the issue

If the operator named one, verify it is actually ready and say so; if it is not, report that instead
of substituting a different issue. Otherwise pick the first issue that satisfies all of:

- `status: ready`, and every issue under Dependencies is **delivered and verified on
  `origin/main`**, not merely closed or present on a branch;
- not `status: needs human`, not an epic or tracking issue (#73 to #80), not `needs: live run` or
  `needs: simulator` while this run is offline;
- nothing else open already touches the same files (two writers on one file is how a day is lost).

Order by: `priority: p1` before p2 before p3; a foundation issue that later recipes depend on before
one that nothing waits on; smaller before larger when otherwise tied. Say in one line why this issue
and not the others.

Re-measure before trusting this, but as of the 2026-10-21 snapshot the ready p1 foundation issues
were #328 (Windows kernel-test flake), #327 (side-effect guard follow-ups, gates recipes 57 to 60),
#247 (Noul confidence-gate floor), #244 (threshold-objective pin) and #218 (a mechanical check for
the honesty rule); #314, #311, #310 and #308 were already in progress under other sessions; recipes
#51 and #52 were the only ready recipe issues. Issue numbers above #361 were filed after that
snapshot — enumerate them yourself.

## Step 2: claim

Swap `status: ready` for `status: in progress` and leave one comment on the issue naming this
session and the branch it will use. If you abandon the issue, revert the label and say why in the
same place.

## Step 3: build

Spawn one Sonnet builder with `isolation: "worktree"` and the builder brief from `PROMPT.md`, plus:

- the issue number and the instruction to read it in full first, with its comments;
- the files that define the rules (`CONTRIBUTING.md`, the relevant `docs/` pages, the issue's
  Sources);
- the exact paths it may touch, and that a gap in shared code is reported, never patched in place;
- the three local checks and the rule that **no check is ever weakened to pass it** — no skipped
  test, loosened assertion, disabled job, or fixture edited to match a wrong output;
- offline only: no key, no network inference, fixtures `synthetic`;
- a notebook is verified by executing a *scratch copy* and running `tools/check_notebook_fresh.py`,
  never by executing the tree under review, and the working tree it hands back is clean;
- it opens the pull request with `Closes #N` (`Refs #N` for partial work — the keyword closes an
  issue from anywhere in the body, including inside a quotation), and the body states only what the
  final diff contains.

Recipe work also takes the serialized integration stage (`PROMPT.md` rule 6): a Sonnet integration
worker updates the branch against current `main` with a **signed merge commit** — never a rebase,
never a force-push — regenerates the README regions with `python tools/render_catalog.py`, and edits
no recipe file. Record every handover on the pull request.

## Step 4: checks

Wait for the complete current check set and read each conclusion explicitly:

```bash
gh pr view <PR> --json headRefOid,baseRefName,mergeable,mergeStateStatus,statusCheckRollup,reviewDecision
gh pr checks <PR> --watch --fail-fast     # wait for it; do not pipe it anywhere
```

Read `.github/workflows/` rather than trusting any list in a prompt. A missing, pending, cancelled,
timed-out or failed check blocks everything downstream. A green check is not a result on its own:
run each instrument against a ref where it must find something before you believe a clean report.

## Step 5: the two gates, on one head

Both gates judge the **same final head**. Any new commit — a fix, an integration, a regenerated
README — voids both, and both run again.

**Gate A — fresh Opus review.** One fresh Opus subagent per pull request, `isolation: "worktree"`,
given the pull request number and the issue number and nothing about what to expect. Two independent
reviewers, split by focus, for anything that touches shared tooling, the recipe guard, the scope
check, the replay-key format, the fixture format, or any interface sixty recipes copy; both must
approve the same head. The reviewer runs everything itself, writes its verdict to a file, and you
post it verbatim as a pull request comment after confirming the last line of its own text is exactly

```text
OPUS-REVIEW: APPROVE <full-head-sha>
```

and that the SHA is the current head. Verify the receipt itself with `gh api` on the comment ID: a
marker found by grepping comment text, a quotation, a builder-authored comment, or a verdict for an
older head is not an approval.

**Gate B — `/code-review high` on the same head.** Invoke the `code-review` skill at level `high`
targeting the pull request, in this session, and save its findings to
`.claude/review-<PR>-codereview.md`. Then triage every finding, one by one, and record the
disposition on the pull request:

- a defect, or anything that teaches a reader something false → a bounded builder fix round;
- correct as written → a written answer on the pull request saying why, which the Gate A reviewer
  explicitly accepts on that same head;
- real but out of this issue's scope → a follow-up issue, filed and linked, never smuggled into this
  diff.

No finding is dropped silently, and "the reviewer approved it" is not a disposition for a Gate B
finding (nor the reverse). If the two gates disagree, you adjudicate in writing, on the pull
request, with the reason — and when the disagreement is about whether something is a defect, the fix
wins.

**Fix rounds are bounded and reviewable.** Send the findings to a builder and tell it to change only
what was asked. A round that also fixes things nobody named cannot be reviewed; what it noticed gets
reported or filed. There is no round count after which a problem is dropped: when a failure repeats,
diagnose the cause, narrow the work, or assign a fresh builder and reviewer pair.

## Step 6: "no issues on CI or review" — the merge condition

Merge only when every one of these holds, each checked explicitly and recorded:

1. The acceptance criteria on the issue are met, in the diff, not in the pull request body's claims.
2. Nothing outside the allowed scope changed: `git diff --raw -M origin/main...HEAD`, every
   resulting mode `100644`, no symlink, submodule, mode or type change.
3. The branch carries a signed integration of current `main` on this head (the foundation-only
   immaterial-advance ruling in `docs/merge-readiness.md` is the single exception, and it needs
   every requirement that document attaches to it; it never applies to a recipe pull request).
4. The complete current check set exists and finished `SUCCESS` — `Lint (ruff)`, `Catalog (README is
   current)`, `Tests (py3.10)`, `Tests (py3.14)`, `Hygiene (secrets and notebook outputs)`, and
   every check the workflows add, with `Scope (recipe pull requests)` required on the head only.
   `SKIPPED` counts only where the workflow's documented condition really applies.
5. Gate A approves this exact head (both reviewers, for a double-review pull request), with every
   blocking finding resolved and the applicable review threads resolved.
6. Gate B has no open finding: each is fixed, answered in writing and accepted, or filed as a
   follow-up issue — and the answered ones were accepted by the Gate A reviewer on this head.
7. `python tools/check_merge_readiness.py --pr <PR> --expected-head <headRefOid>` was run and its
   receipt recorded as printed. It is read-only and never authorization, and a `NOT READY` stays
   `NOT READY`.

Then, holding a single merge lock:

```bash
gh pr merge <PR> --squash --match-head-commit <headRefOid>
gh issue view <N> --json state,closedAt
```

No admin bypass, no `--delete-branch`, and honor a merge queue. Record the merge commit, then wait
for CI on that exact `main` commit and read it per check. If `main` goes red, stop and prioritize a
fix through the same pipeline; never hide it.

## Step 7: verify, unblock, report

Confirm the issue closed and its criteria are genuinely met; remove `status: in progress`; for every
issue that waited on this one, re-check its blockers and move `status: blocked` to `status: ready`
where they are all delivered. Leave the working tree clean (`git status --porcelain` empty), remove
the worktrees and virtual environments this run created, and delete nothing you do not own — a past
run's reviewer deleted another agent's files during cleanup.

Then report, in this order and nothing longer than it needs to be:

- the issue, the pull request, the merge commit, and the `main` CI result on that commit;
- the resolved models for builder, integration worker and reviewer, and the review comment IDs;
- Gate A rounds and Gate B findings with their dispositions, including every answered-not-fixed one;
- follow-up issues filed, with numbers;
- that no live call and no spend occurred;
- anything left unverified, said plainly as unverified. Never infer a check's result from its
  source.

If the issue cannot reach a merge, say exactly what is missing — a decision only the operator can
make, a credential, an authority this table withholds — label it `status: needs human`, and stop
there rather than working around it.
