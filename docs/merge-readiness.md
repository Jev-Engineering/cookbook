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

A `NOT READY` receipt stays `NOT READY`, and the helper never reports an exception as a pass.
The one manual ruling that can merge past its ancestry result is the foundation-only one in the
[manual decision for an immaterial `main` advance](#manual-decision-for-an-immaterial-main-advance).
The helper's CI evidence is never set aside.

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
| `--require-check NAME` | An additional required check, exact name, repeatable. Required on current `main` AND the PR head. |
| `--require-head-check NAME` | An additional required check, exact name, repeatable. Required on the PR head ONLY; never judged on current `main`. For a check that runs on `pull_request_target` (for example `Scope (recipe pull requests)`), which therefore never appears on a commit of `main`. |

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
3. Every check named with `--require-check` (the five baseline names plus any added with that
   option) is present and `success` on **current `main`** and then on the **PR head**; every
   check named with `--require-head-check` is present and `success` on the **PR head only** and
   is never looked for on `main`. Both read CheckRuns and StatusContexts, with every page fetched
   and the reported total matching what was seen. Missing, pending, failure, cancelled, timed
   out, neutral, skipped, or error results all fail, for either option, as does a result from the
   wrong app for a baseline name. One green workflow is not the gate: each named check is judged on
   its own. A name that is a baseline check, or that is also given with `--require-check`, keeps
   its `main` requirement even if it is also given with `--require-head-check`: the head-and-main
   requirement always wins, and spelling a baseline as head-only never weakens it. Repeating a name
   only deduplicates the requirement; it does not deduplicate actual results. More than one result
   for one name is ambiguous and fails closed, **except** that several CheckRuns from the one same
   app, with that app's slug readable, all `success`, for a non-baseline name, collapse into a
   single `success` result (see "Required checks" below for the exact rule, the `results`/`runs`
   receipt shape, and why); a baseline name, any mix that is not all-`success`, or results from
   more than one source (a
   StatusContext mixed with a CheckRun, two StatusContexts, or CheckRuns from different apps) stay
   ambiguous and fail closed exactly as before.
4. After collecting evidence it re-reads the default branch and the PR. If `main` or the head
   moved, or the PR is no longer open, it fails.

Authentication failure, rate limiting, missing visibility, malformed or untyped API data, and
incomplete listings all fail closed (exit `3`). The receipt contains SHAs, check names, ids and
states, a failure list capped at 25 entries, and bounded text. `required_checks` lists the names
required on current `main` AND the head (the five baseline names plus every `--require-check`
name); `required_head_checks` lists the names required on the head only (every
`--require-head-check` name, minus any that are also baseline or `--require-check` names, since
those already carry the stronger requirement). `checks.main` is judged against `required_checks`
only, never against `required_head_checks`, so it never reports a head-only name as having been
checked on `main`; `checks.head` is judged against both sets together, since every required name
is checked on the head. The receipt carries no tokens, headers, or raw API output or error
bodies: `gh` output is decoded as strict UTF-8 (never the Windows code page), and bytes that are
not valid UTF-8, non-JSON output, or an unexpected exception produce exit `3` with a one-line,
type-only reason.

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
and is reported as a failure, whether the name reached the helper as a baseline, a
`--require-check` or a `--require-head-check` name. Checks you add with `--require-check` or
`--require-head-check` may be a CheckRun from any app or a StatusContext, since that is how
external checks report; the receipt shows each one's `kind` and, for CheckRuns, the `app`.

**A name that appears more than once is ambiguous and fails closed, with one narrow exception
(#138).** The exception: a `--require-check` or `--require-head-check` name (never one of the
five baseline checks) whose every completed result is a **CheckRun from the same app, with that
app's slug actually readable,** and concluded `success` collapses into a single `success` result,
and the receipt's evidence for that check carries `"state": "success"`, `"results"` (the true
count), and `"runs"` — a list of every merged run's `id` and `state` (and `app`), capped at 10
entries with a `"runs_omitted"` count added when there were more, so the receipt stays bounded and
auditable. This exists because `scope.yml` runs `Scope (recipe pull requests)` on
`pull_request_target` for `opened`, `synchronize`, `reopened` and `edited`, so a description edit
after the last push leaves two successful `Scope` CheckRuns, both from `github-actions`, on the
same head; without the collapse the helper would fail closed forever on an otherwise fully green
head. "Readable" means GitHub returned a CheckRun whose `app` is an object with a string `slug`;
an absent `app`, a non-object `app`, or a non-string `slug` is unreadable and is never treated as
"the same app" as anything, including another equally unreadable row, so two CheckRuns that both
happen to have an unreadable slug do **not** collapse (#150) — that would need untyped or
malformed API data to reach, which the helper fails closed on everywhere else. A readable app
slug still renders in the evidence (clipped to 60 characters, as before); an unreadable one
renders as JSON `null`, never the string `"None"`, in both the single-result and the merged-`runs`
evidence (#150).

Every other multi-result case for such a name still fails closed exactly as before: a failure,
neutral, cancelled, timed out, skipped, pending/in-progress row, or differing conclusions (the
pre-#138 state-ambiguity case), **and, deliberately unchanged by #138, a result from more than one
source under the same name** — a StatusContext mixed with a CheckRun, two StatusContexts (which
carry no `app` to compare at all), or two CheckRuns from different apps (including a pair where
one or both apps are unreadable, per the paragraph above). That source-ambiguity guarantee
predates #138 (the docs above already use a CheckRun/StatusContext pair as the textbook example of
an ambiguous name) and stays exactly as strict even when every one of those differently sourced
results happens to be `success`: a spurious same-named result from a different actor must never be
absorbed into a genuine check's evidence. A baseline name is *never* eligible for the collapse,
regardless of its results, because nothing that reruns on `edited` publishes a baseline check, and
the stricter app rule two paragraphs up already governs it. CheckRuns are read with
`filter=latest`, so a rerun replaces an earlier cancelled run of the same job (this is also why the
#138 scenario needs the collapse at all: `synchronize` and `edited` start two different check
suites, so the second run adds a row rather than replacing one).

Every ambiguous result — a genuine conflict or the not-yet-collapsed duplicate case — also carries
`"states"` in its evidence: the sorted list of distinct results across the duplicate rows (for
example `["pending", "success"]` or `["failure", "success"]`), alongside the existing `"results"`
count. This lets the receipt distinguish a transient wait from a substantive conflict without a
second API call (#150); see the next paragraph and the wait-list bullet below for the case this
exists for.

A transient `success` + `pending`/`in_progress` pair for the same name — the instant between an
`edited` rerun starting and finishing, with the first run's `success` still visible — reports as
ambiguous (`NOT READY`) exactly like any other not-yet-all-success mix, with `"states": ["pending",
"success"]` (an `in_progress` CheckRun collapses to `pending`, like any other not-yet-completed
result), and clears itself as soon as the second run completes. It belongs on the transient-wait
list in ["Where it fits in the serial merge"](#where-it-fits-in-the-serial-merge) below, not among
the substantive failures: wait and rerun, the same as a still-computing `mergeable` state.

**Known limit, recorded for the record (#138 option 2, left deliberately out of scope by #144 and
#150): a cancelled or once-failed `Scope` row cannot be cleared by editing the description
again.** `scope.yml`'s concurrency group is `scope-<pr number>` with `cancel-in-progress: true`
(one group per pull request, not per head SHA), so a description `edited` event that fires while
an earlier `Scope` run for the same pull request is still in progress cancels that earlier run
outright. The cancelled run keeps its own check suite, so it stays a visible `cancelled` CheckRun
on the commit rather than being replaced (`filter=latest` only picks the latest run *within* a
check suite, and `edited` starts a new suite — the same reason #138's collapse exists at all, see
above). Two such rows (for example one `cancelled` and one `success`, or two `cancelled`) are an
ordinary ambiguous result — `"duplicate"` if the states match, `"conflicting"` if they do not —
never the all-`success` collapse, and no further edit can fix that: either row is still not
`success`, so the name can never become all-`success` by editing the same head again. The same is
true of a `Scope` run that completed with `conclusion: failure` once, for a cause since fixed: a
later edit's successful rerun adds a `success` row alongside the earlier `failure` row rather than
replacing it, which is `"conflicting"`, not a collapse. Both cases need a new head — a
`synchronize` event, which runs its own `Scope` check suite from scratch — not another edit of the
same head's description. Re-running the *original* `Scope` workflow run instead does not help,
even though "[Where it fits in the serial merge](#where-it-fits-in-the-serial-merge)" below might
suggest otherwise for a push-triggered check ("filter=latest shows what currently counts" and its
post-merge remedy "rerun the workflow on that exact commit"). The real reason is narrower:
`scope.yml` runs on `pull_request_target`, so re-running an *existing* run replays that run's
*original* event payload, not a fresh one. `github.event.pull_request.body` in that stale payload
is the pre-edit body — exactly the staleness a *new* `edited` event (unlike a rerun of an old one)
exists to catch — so a rerun's verdict is untrustworthy, not merely unhelpful. This is why the
rule in `CONTRIBUTING.md` — never edit a
pull request's description after the final push of a head that goes to the merge gate — stays in
force: an edit is the only way `Scope` reruns at all, and every rerun after the first either
leaves a `cancelled` row behind (if it overlaps a run still in progress) or, if the head already
failed `Scope` for a real reason, cannot un-fail it short of a new head. #150's four changes above
make the helper's reasoning on these rows legible (the actual cause is now visible in `"states"`)
but do not and cannot change the rows themselves: that is `scope.yml`'s concurrency behaviour and
GitHub's check-suite model, outside this read-only helper's reach.

The helper does not read workflow files. Checks added by later workflows (for example notebook
execution or fixture validation) are **the caller's responsibility**: read the current workflows
before each merge and pass every new check explicitly, with `--require-check` when the check also
runs on a push to `main`, or `--require-head-check` when it does not (see below).

```bash
python tools/check_merge_readiness.py --pr 123 --expected-head <sha> \
  --require-check "Notebooks (execute)" --require-check "Fixtures (validate)" \
  --require-head-check "Scope (recipe pull requests)"
```

**A check that only runs on a pull request is a different case, and is never required with
`--require-check`.** `Scope (recipe pull requests)` runs on `pull_request_target` and therefore
never appears on a commit of `main` (see [notebook-ci.md](notebook-ci.md)); the same is true of a
per-recipe notebook job such as `Notebook (01-sentiment-classification)` before that recipe has
landed on `main`. Pass names like these with `--require-head-check`, which judges them on the PR
head only and never looks for them on `main`; `--require-check` still requires every name it is
given to be present on current `main` as well as on the head, so passing a pull-request-only check
there would make the helper return `NOT READY` forever. **A head-only check is never verified on
`main`**, by design — a check required with `--require-head-check` says nothing about whether that
name exists, or is green, on any commit of `main`, past or future.

Checks on a pull request run on the merge result as of the last push, not on a `main` that moves
afterwards, and a green run on an older `main` says nothing about a later one. That is why the
helper reads the checks of current `main` and of the head separately, and why the exact
post-merge run below stays necessary.

Checks outside the required set are not judged. Using only the baseline when a workflow has
added a job silently under-checks, which is why the list is explicit and the receipt echoes
`required_checks` and `required_head_checks`.

## Where it fits in the serial merge

1. **Before the merge**, with the merge lock held, after the Opus approval for the current head
   is verified: run the helper with `--expected-head` set to that approved head. Anything but
   exit `0` stops the merge. Two not-ready results are transient waits, not failures, and the
   right response is to wait and run the helper again:

   - GitHub has not computed mergeability yet (`mergeable` is null, state `unknown`), which
     happens lazily, for example right after `main` advances.
   - A required check is still pending (queued or in progress), for example on a freshly merged
     `main`.
   - A `--require-check`/`--require-head-check` name reports `success` + `pending`/`in_progress`:
     the instant between an `edited` rerun of a check such as `Scope (recipe pull requests)`
     starting and finishing, with the first run's `success` still on the commit (#138). This
     prints the identical `conflicting results (N)` failure string, and the identical
     `"state": "ambiguous"` evidence, as a genuine conflict on the same name — **the message
     alone does not tell the two apart.** Read the evidence's `"states"` field instead (#150):
     `["pending", "success"]` (an `in_progress` CheckRun also collapses to `pending`) is the
     transient wait; any other pair — `["failure", "success"]`, two non-success states, and so on
     — is a substantive conflict. It clears on its own as soon as the second run completes,
     collapsing to `success` if that run also succeeds; if it does not, `"states"` changes to
     reflect the real conflict and the result stays a substantive failure, not a wait.

   Wait until the state settles and rerun; never merge while any of these hold. Every other
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
   the merge is not verified. `Scope (recipe pull requests)` is permanently PR-only (it runs on
   `pull_request_target`, never on a push), so it is never part of this post-merge list and is
   never expected on the merge commit: it was verified on the merged pull request's head, before
   the merge, and nothing checks it again here. **A per-recipe `Notebook (<recipe>)` job used with
   `--require-head-check` before that recipe landed is different**: once the merge lands, the push
   to `main` selects and runs exactly that recipe's job (see [notebook-ci.md](notebook-ci.md),
   "Which notebooks run"), so it **is** expected on the merge commit, and the flag used before the
   merge does not decide the post-merge list. Re-derive the full set of checks expected on this
   exact `main` commit (the five baseline names, every `--require-check` name, and, for a recipe
   merge, that recipe's own `Notebook (<recipe>)` name) and require all of them here, not only the
   names that were `--require-check` before the merge. Push CI on `main` cancels an older run when
   a newer merge lands, so a cancelled push run on a superseded commit is a real gap, as with
   PR #83: record it, rerun the workflow on that exact commit, and read the rows again. Do not
   treat a later commit's green run as proof for this one. If the merge commit is red, stop
   merging.

   Do the next merge only after this verification is complete for the previous merge commit,
   with every required check `completed` and `success`. A pending row is a wait, not a pass.
   Merging again while it is pending is how the PR #83 run was cancelled.

The helper narrows, but does not close, the window between the check and the merge:
`--match-head-commit` pins the head, and `main` can still advance in that gap, which is why the
post-merge verification of the exact commit remains necessary.

## Manual decision for an immaterial `main` advance

This section records a manual ruling, not a helper feature.

**The helper is unchanged and is still run before every merge.** Its receipt is recorded as it
is. When current `main` is not an ancestor of the head, the receipt says `NOT READY` (exit `1`)
with the signed-integration guidance, and nothing here turns it into success or presents it as a
passed automatic gate. The helper's CI evidence, every required check on current `main` and on
the head, is always binding. The helper may not be skipped.

### The standing ruling

The orchestrator (session `37d430e7`), sole serial merge owner, recorded a standing rule in
issue #80, ledger update 6 (comment 6031026593), "for the adopted helper and future merges": an
advance of `main` that touches none of a pull request's files does not require a branch update
before merge. The gate is Opus approval of the exact head, plus green checks on its merge ref as
of the last push, with `main`'s own CI verified after each merge before the next. The adoption
comment on PR #105 (6031278433) restates it, and adjudication 6031723897 applies it to "merges
performed by this run". None of these three states a foundation-only limit.

This document limits the use of the ruling to **foundation pull requests**. That limit comes
from #104 criterion 3 and from the recipe rules in `CONTRIBUTING.md` and `orchestration/PROMPT.md`
(see below), which stay unchanged; it is not a limit the ruling states for itself, and this
document does not widen it.

Under that rule the helper's ancestry result is advisory when the advance is immaterial, and
binding otherwise. A material advance still requires a signed integration of current `main`, green
checks on the new head, and a fresh review of it, because an update changes the head and voids
the earlier approval. An advance is material if it touches any of:

- the files the pull request changes;
- shared code the pull request uses;
- workflows under `.github/workflows/` (the ruling's own wording is "workflow changes"), or,
  as this document's addition, anything that changes the set of required checks.

If the evidence below cannot be shown, treat the advance as material.

### Requirements this document attaches to the ruling

Issue #104 asks for the ruling to be documented with explicit evidence, so a merge that relies on
it needs all of the following, each recorded on the pull request before the merge:

1. **Explicit evidence of the current delta and its effect, pinned to a `main` SHA.** Record the
   exact `main` SHA evaluated and the helper receipt that showed the ancestry failure. Name the
   commits that advanced `main` since the branch last integrated it, show the delta (for example
   `git diff <main at last integration>..<current main>`), and show that none of it is material
   as defined above. Then show the effect on **every** required check at the merge result: run
   each one on an uncommitted trial merge (`git merge-tree --write-tree <head> <current main>`),
   or reason about each one separately. The head's own check runs came from an older merge
   result, so the trial merge or that per-check reasoning is the only coverage of the combination.
2. **Genuine same-head reviewer acceptance of the delta.** The Opus approval of the exact head
   being merged is given with the advance in view and states that it accepts the adjudication for
   that head, as the review in comment 6031023696 did for the #91 delta. Where the contract requires two
   approvals, each reviewer does this. An approval that was given without the advance in view, or
   that asked for integration, is not that acceptance, and neither the supervisor's ruling nor a
   builder's or supervisor's own statement stands in for it. Without it, integrate and review
   again.
3. **Complete actual checks.** Every required check (the five baseline names plus any added by
   later workflows) is present and `success` on the head, and on current `main`. A missing or
   pending check is never waived, and a run on an older `main` is not counted as coverage of a
   later one.
4. **Exact post-merge CI before the next merge.** After the squash, read every required check on
   the exact merge commit as in the post-merge step above, and wait for it to finish green before
   merging anything else. If it is red, stop merging.

If `main` advances again before the merge, the ruling and the reviewer's acceptance no longer
apply. Both must be renewed for the new delta, or the branch is updated and reviewed again.

The decision covers only the ancestry failure. Any other failure in the receipt (head pin, draft
or closed pull request, a failed, cancelled, missing or pending check) still stands.

### Recipe pull requests are not covered

The ruling is foundation-only. It does not extend to recipe pull requests and does not weaken
#69's recipe gate or the ownership of the generated README. `CONTRIBUTING.md` and the recipe
rules in `orchestration/PROMPT.md` stay as written and have no exception: a recipe branch is
updated against current `main` with a signed merge commit, the generated README regions are
computed from the **base** README, strict scope and catalog CI must pass, and the new head is
reviewed again after any update.

### `orchestration/PROMPT.md` has not been amended

`orchestration/PROMPT.md` has not been changed to match the ruling, and this document does not
claim it has. Its "Merging" checklist still requires that "the branch is current against `main`"
(line 128), a foundation pull request left behind by a merge is still to be updated and reviewed
again (line 142), and the Wave 0 rule still says foundation pull requests are each updated
against the last and re-reviewed if the head changed (line 309). Line 136 also merges with
`--delete-branch`, while the serial-merge steps above do not add it. Reconciling these is a
separate reviewed change, tracked in issue #106. Until it lands the texts differ, and a merge
that relies on the ruling should say so on the pull request.

### Recorded history

Both cases below were merged by the orchestrator after an Opus review of the exact head that the
orchestrator launched. For each, the review comment and the merge note were posted from the same
orchestrator session. Whether the review accepted the ruling differs by case, as set out below.
No history is rewritten here, and what a source claims is recorded as a claim.

**PR #96** did not meet requirements 1 and 2. The review of head `f843a7c` (comment 6031008513,
header: orchestrator session `37d430e7`, model recorded in that header as `claude-opus-5-5`; the
reviewer model is `claude-opus-5` per the owner decision on #80 (comment 6070170893)) came before
the ruling and did not accept it. It approved that exact head. It
also stated that after #91 advanced `main` the helper returned `NOT READY` with `behind_by` 1,
and that a signed integration and a fresh review were needed before merging. The orchestrator
then ruled the advance immaterial in its merge note (comment 6031022258) and merged without that
refresh. No explicit acceptance of the adjudication by the reviewing Opus and no per-check effect
evidence was recorded on #96, and none is supplied after the fact. The audit receipt (issue #80,
comment 6031048875) records this as an adjudicated process exception, not proof that the
review's precondition or the helper's ancestry gate passed. The merge note's wording that the
checks were green "on the merge ref with current `main`" was inaccurate: the five checks on
`f843a7c` completed between 03:52:39Z and 03:53:33Z, and #91 merged at 04:32:27Z.

**PR #98** went further for one delta only. Its review of head `b20c2cc` (comment 6031023696)
recorded the adjudication of #91's advance, `7d14692..7e8ac92`, which had been made before the
review. It gave per-check reasoning and a trial merge against `7e8ac92`, found #91 immaterial, and
approved that head under the ruling with `main` at `7e8ac92`. That is an Opus acceptance of the
ruling for that delta, recorded before the merge note. It also
corrected the assertion that the pull request's checks ran with current `main`: they ran on the
merge result of the last push, which did not contain the advance.

That review does not mention #96. `main` then moved again to `96a1c7b` (#96, merged at
04:36:46Z, five seconds before the review was posted at 04:36:51Z). The only record of the effect
of that second delta is the orchestrator's merge note (comment 6031035340), which claims that the
reviewer ran the #98 scanner on #96's files and verified a clean merge tree, and which accepts
the merge-ref correction. No reviewer receipt records that claim or a renewed acceptance for
that delta, so by the pinning and renewal rules above the reviewer's acceptance was not recorded
as renewed for it. Requirement 4 was met: the five post-merge checks on `96a1c7b` were green by
04:37:45Z, before #98 merged at 04:38:05Z.

In both cases the post-merge CI on `main` is the backstop.
