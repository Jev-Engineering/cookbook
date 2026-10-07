# Merge readiness

`tools/check_merge_readiness.py` is a read-only helper that answers one question before a
serial merge: **is this pull request head, as pinned, based on current `main`, with every
expected CI check successful on both current `main` and that head?**

It exists because of two observed delivery gaps. The `main` CI run for PR #83 was cancelled when
the next merge advanced `main` before verification completed (a rerun later passed). The
pre-merge CI for PR #92 ran against an older `main` even though evaluation and style work had
landed. Both are kept here as historical receipts; the tests reproduce each one.

## What it is not

A successful run is **not merge authorization**. It covers CI and current-`main` readiness and
nothing else. Every other gate still applies and is checked by the people and agents who own it:

- a genuine Opus review of the exact head being merged (and two where the contract requires it),
  verified from the reviewer's own receipt; the helper never reads, creates, or approximates one;
- every acceptance criterion on the issue;
- dependencies on other issues and pull requests;
- scope: the changed paths are the ones the issue and `CONTRIBUTING.md` allow;
- signed commits;
- the original supervisor as the sole serial merge controller.

A `NOT READY` receipt stays `NOT READY`. The only manual exception to it that this document
describes is the foundation-only one in the [manual exception for an immaterial `main` advance](#manual-exception-for-an-immaterial-main-advance),
and the helper never reports it as a pass.

The helper never merges, reviews, approves, comments, edits settings, or bypasses a control. It
only issues `gh api` GET requests, with no body and no method override.

## Usage

Needs the `gh` CLI, already authenticated, and Python 3.10 or newer. No other dependency.

```bash
python tools/check_merge_readiness.py --pr 95 --expected-head <full 40-character head SHA>
```

| Option | Meaning |
| --- | --- |
| `--pr N` | Pull request number (required). |
| `--expected-head SHA` | The full lowercase head SHA that was reviewed and that you intend to merge (required). |
| `--repo OWNER/NAME` | Defaults to `Jev-Engineering/cookbook`. |
| `--require-check NAME` | An additional required check, exact name, repeatable. |

Exit status: `0` ready, `1` not ready, `2` usage error, `3` GitHub could not be read or
returned data that cannot be trusted, including any unexpected internal failure. Once the
arguments are valid, a bounded JSON receipt (ASCII only) is always printed to stdout and a
one-line summary goes to stderr. A usage error (`2`) prints argparse's usage message instead and
no receipt.

### What it verifies

1. The PR head equals `--expected-head`, the PR is open, not a draft, not merged, targets the
   repository's current default branch, and GitHub reports it mergeable (`mergeable` is true and
   the state is not `dirty`, `behind` or `unknown`).
2. Current default-branch `main` is an ancestor of the PR head. The API compare must report the
   merge base to be `main` itself, with the head ahead of or identical to it and zero commits
   behind. A branch behind `main` fails with guidance: update it with a signed integration of
   current `main`, then get a fresh review and CI of the new head.
3. Every required check is present and `success` on **current `main`** and then on the **PR
   head**, reading both CheckRuns and StatusContexts, with every page fetched and the reported
   total matching what was seen. Missing, pending, failure, cancelled, timed out, neutral,
   skipped, error, duplicate, conflicting, or ambiguous results all fail. One green workflow is
   not the gate: each named check is judged on its own.
4. After collecting evidence it re-reads the default branch and the PR. If `main` or the head
   moved, or the PR is no longer open, it fails.

Authentication failure, rate limiting, missing visibility, malformed or untyped API data, and
incomplete listings all fail closed (exit `3`). The receipt contains SHAs, check names, ids and
states, a failure list capped at 25 entries, and bounded text. It carries no tokens, headers,
or raw API output or error bodies: `gh` output is decoded as strict UTF-8 (never the Windows
code page), and bytes that are not valid UTF-8, non-JSON output, or an unexpected exception
produce exit `3` with a one-line, type-only reason.

### Required checks

The five baseline checks are always required. They are the job names in
`.github/workflows/ci.yml` and `.github/workflows/hygiene.yml`:

- `Lint (ruff)`
- `Catalog (README is current)`
- `Tests (py3.10)`
- `Tests (py3.14)`
- `Hygiene (secrets and notebook outputs)`

Each baseline name must be a **CheckRun published by `github-actions`**: a commit status or a
CheckRun from another app posted under the same name cannot stand in for a missing Actions job
and is reported as a failure. Checks you add with `--require-check` may be a CheckRun from any
app or a StatusContext, since that is how external checks report; the receipt shows each one's
`kind` and, for CheckRuns, the `app`. A name that appears more than once (for example as both a
CheckRun and a StatusContext) is ambiguous and fails. CheckRuns are read with `filter=latest`, so
a rerun replaces an earlier cancelled run of the same job.

The helper does not read workflow files. Checks added by later workflows (for example notebook
execution, fixture validation, or the recipe scope check) are **the caller's responsibility**:
read the current workflows before each merge and pass every new check explicitly.

```bash
python tools/check_merge_readiness.py --pr 123 --expected-head <sha> \
  --require-check "Notebooks (execute)" --require-check "Scope (recipe paths)"
```

Checks on a pull request run on the merge result as of the last push, not on a `main` that moves
afterwards, and a green run on an older `main` says nothing about a later one. That is why the
helper reads the checks of current `main` and of the head separately, and why the exact
post-merge run below stays necessary.

Checks outside the required set are not judged. Using only the baseline when a workflow has
added a job silently under-checks, which is why the list is explicit and the receipt echoes
`required_checks`.

## Where it fits in the serial merge

1. **Before the merge**, with the merge lock held, after the Opus approval for the current head
   is verified: run the helper with `--expected-head` set to that approved head. Anything but
   exit `0` stops the merge. Two not-ready results are transient waits, not failures, and the
   right response is to wait and run the helper again:

   - GitHub has not computed mergeability yet (`mergeable` is null, state `unknown`), which
     happens lazily, for example right after `main` advances.
   - A required check is still pending (queued or in progress), for example on a freshly merged
     `main`.

   Wait until the state settles and rerun; never merge while either one holds. Every other
   failure is substantive (a stale base, a failed, cancelled or missing check, a moved head, a
   draft or closed pull request): fix the cause rather than rerunning until green. A check that
   stays missing is not a wait and is never waived.
2. **Merge pinned to the head**, by the original supervisor only, with exactly the authorized
   command `gh pr merge <PR> --squash --match-head-commit <sha>`. Do not add `--delete-branch`
   or `--admin`, and never bypass a rule. The helper does not run this and cannot authorize it.
3. **After the merge**, verify the exact merge commit, not whatever `main` is later. Use the
   squash commit's SHA and read its CheckRuns and StatusContexts directly (read-only GETs):

   ```bash
   REPO=Jev-Engineering/cookbook
   SHA=$(gh pr view <PR> --repo $REPO --json mergeCommit --jq .mergeCommit.oid)

   # CheckRuns on that commit: the count, then name, app, status, conclusion per run
   gh api "repos/$REPO/commits/$SHA/check-runs?filter=latest&per_page=100" \
     --jq '.total_count, (.check_runs[] | [.name, .app.slug, .status, .conclusion] | @tsv)'

   # The same, with filter=all, to audit earlier attempts such as a cancelled one
   gh api "repos/$REPO/commits/$SHA/check-runs?filter=all&per_page=100" \
     --jq '.total_count, (.check_runs[] | [.id, .name, .app.slug, .status, .conclusion] | @tsv)'

   # StatusContexts on that commit (empty today; read it for any added external check)
   gh api "repos/$REPO/commits/$SHA/status?per_page=100" \
     --jq '.sha, .total_count, (.statuses[] | [.context, .state] | @tsv)'

   # The commit is on main: expect "ahead 0" or "identical 0" (main at or after $SHA)
   gh api "repos/$REPO/compare/$SHA...main" --jq '[.status, .behind_by] | join(" ")'
   ```

   `filter=latest` shows what currently counts: a rerun replaces an earlier cancelled run of the
   same job. `filter=all` also lists the superseded attempts, so a cancelled one is visible and
   can be recorded rather than lost. Judge the gate on the `filter=latest` rows and keep the
   `filter=all` rows as the audit trail.

   Every required check (the five baseline names plus each `--require-check` used) must appear
   exactly once, `completed` with conclusion `success` (or state `success` for a status), and the
   printed counts must match the rows listed. Missing, pending, cancelled or duplicate rows mean
   the merge is not verified. Push CI on `main` cancels an older run when a newer merge lands, so
   a cancelled push run on a superseded commit is a real gap, as with PR #83: record it, rerun the
   workflow on that exact commit, and read the rows again. Do not treat a later commit's green
   run as proof for this one. If the merge commit is red, stop merging.

   Do the next merge only after this verification is complete for the previous merge commit,
   with every required check `completed` and `success`. A pending row is a wait, not a pass.
   Merging again while it is pending is how the PR #83 run was cancelled.

The helper narrows, but does not close, the window between the check and the merge:
`--match-head-commit` pins the head, and `main` can still advance in that gap, which is why the
post-merge verification of the exact commit remains necessary.

## Manual exception for an immaterial `main` advance

This section describes a manual ruling, not a helper feature. The helper's ancestry check is
strict and stays strict: if current `main` is not an ancestor of the head, it reports `NOT READY`
(exit `1`) with the signed-integration guidance, and that receipt is kept as it is. Nothing here
changes an ancestry failure into success, and an exception is never presented as a passed
automatic gate.

The default is unchanged: when `main` moves after a head was reviewed, update the branch with a
signed integration of current `main`, get green checks on the new head, and have it reviewed
again, because an update changes the head and voids the earlier approval.

For **foundation pull requests only**, the original supervisor, as sole serial merge controller,
may instead rule that an advance of `main` is immaterial and merge the reviewed head without
updating it. The ruling is a manual adjudication of the narrow case where the update would void
an approval for no change in what is merged.

### A recorded departure from the PROMPT checklist, not a satisfied condition

The exception contradicts `orchestration/PROMPT.md` as it is written today, and it does not
reconcile the two. The PROMPT checklist is still the operative rule for every merge, and this
document does not amend it:

- the "Merging" checklist requires that "the branch is current against `main`" (line 128);
- a foundation pull request left behind by a merge is updated by its owner and reviewed again
  (line 142);
- Wave 0 foundation pull requests are each updated against the last and re-reviewed if the head
  changed (line 309).

A merge under this exception does not meet those conditions. It is a supervisor-adjudicated,
recorded departure from them, to be named as such on the pull request. Changing the PROMPT
wording is a separate foundation pull request with its own review; this document does not do it,
and until one lands the contradiction stands and is not resolved here. For the same follow-up,
`orchestration/PROMPT.md` line 136 merges with `--delete-branch`, while the serial-merge section
above says not to add it.

The earlier supervisor wording that treated the helper's ancestry result as advisory in the
immaterial case is not adopted. The result stays a binding `NOT READY`; the exception is a
separate manual ruling that sits next to it.

### Requirements

An exception needs all of the following, each recorded on the pull request before the merge:

1. **Explicit evidence of the current delta and its effect, pinned to a `main` SHA.** Record the
   exact `main` SHA evaluated and the helper receipt that showed the ancestry failure. Name the
   commits that advanced `main` since the branch last integrated it, show the delta (for example
   `git diff <main at last integration>..<current main>`), and show that none of it touches the
   pull request's files or the shared code they depend on. Then show the effect on **every**
   required check at the merge result: run each one on an uncommitted trial merge
   (`git merge-tree --write-tree <head> <current main>`), or reason about each one separately. The
   head's own check runs came from an older merge result, so the trial merge or that per-check
   reasoning is the only coverage of the combination.
2. **Explicit genuine reviewer agreement at the same head.** A genuine Opus review of the exact
   head being merged states that it accepts the adjudication for that head. A review that asked
   for integration is not satisfied by the supervisor's ruling alone; the same-head reviewer must
   agree, and where the contract requires two approvals, each reviewer must. Without that
   agreement, integrate and review again.
3. **Complete actual checks.** Every required check (the five baseline names plus any added by
   later workflows) is present and `success` on the head, and on current `main`. A missing or
   pending check is never waived, and a run on an older `main` is not counted as coverage of a
   later one.
4. **Exact post-merge CI before the next merge.** After the squash, read every required check on
   the exact merge commit as in the post-merge step above, and wait for it to finish green before
   merging anything else. If it is red, stop merging.

If `main` advances again before the merge, the ruling and the reviewer's agreement no longer
apply. Both must be renewed for the new delta, or the branch is updated and reviewed again.

The exception covers only the ancestry failure. Any other failure in the receipt (head pin,
draft or closed pull request, a failed, cancelled, missing or pending check) still stands.

It does not apply when the advance is material: if `main` touched the pull request's files or
the shared code they depend on, or the evidence in item 1 cannot be shown, the signed update and
the renewed head review are required.

### Recipe pull requests are not covered

The exception does not extend to recipe pull requests and does not weaken #69's recipe gate or
the ownership of the generated README. `CONTRIBUTING.md` and the recipe rules in
`orchestration/PROMPT.md` stay as written and have no exception: a recipe branch is updated against current `main` with a signed merge commit, the
generated README regions are computed from the **base** README, strict scope and catalog CI
must pass, and the new head is reviewed again after any update.

### Recorded history

PR #96 is the recorded case. It did not meet requirements 1 and 2 above. The Opus review of head
`f843a7c` (comment 6031008513) approved that content, and stated that after #91 advanced `main`
the helper returned `NOT READY` with `behind_by` 1 and that a signed integration and a fresh
review were needed before merging. The supervisor's merge note (comment 6031022258) ruled the
advance immaterial and merged without that refresh. No later #96 comment records the reviewer
accepting that ruling, and no per-check effect evidence was recorded there. The audit receipt
(issue #80, comment 6031048875) records this as an adjudicated process exception, not proof that
the review's precondition or the helper's ancestry gate passed. The requirements above are not a
description of what #96 did, they do not approve #96 retroactively, and no reviewer agreement is
supplied for it after the fact.

The merge note also said the five checks were green "on the merge ref with current `main`". They
were not run against the advance: the five checks on `f843a7c` completed between 03:52:39Z and
03:53:33Z, and #91 merged at 04:32:27Z. The PR #98 review (comment 6031023696) made the same
correction for its own checks: they ran on the merge result of the last push, which did not
contain the advance. In both cases the post-merge CI on `main` is the backstop.
