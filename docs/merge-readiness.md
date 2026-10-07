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
returned data that cannot be trusted. A JSON receipt is always printed to stdout; a one-line
summary goes to stderr.

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
or raw API error bodies.

### Required checks

The five baseline checks are always required. They are the job names in
`.github/workflows/ci.yml` and `.github/workflows/hygiene.yml`:

- `Lint (ruff)`
- `Catalog (README is current)`
- `Tests (py3.10)`
- `Tests (py3.14)`
- `Hygiene (secrets and notebook outputs)`

The helper does not read workflow files. Checks added by later workflows (for example notebook
execution, fixture validation, or the recipe scope check) are **the caller's responsibility**:
read the current workflows before each merge and pass every new check explicitly.

```bash
python tools/check_merge_readiness.py --pr 123 --expected-head <sha> \
  --require-check "Notebooks (execute)" --require-check "Scope (recipe paths)"
```

Checks outside the required set are not judged. Using only the baseline when a workflow has
added a job silently under-checks, which is why the list is explicit and the receipt echoes
`required_checks`.

## Where it fits in the serial merge

1. **Before the merge**, with the merge lock held, after the Opus approval for the current head
   is verified: run the helper with `--expected-head` set to that approved head. Anything but
   exit `0` stops the merge; fix the cause rather than rerunning until green.
2. **Merge pinned to the head**: `gh pr merge <PR> --squash --delete-branch --match-head-commit <sha>`
   (the merge itself is the supervisor's, not the helper's). Never use admin bypass.
3. **After the merge**, verify the exact merge commit on `main`: wait for CI on that commit and
   confirm every required check succeeded there, for example by running the same check on the
   next pull request, whose `main` is that commit. If it is red, stop merging.

The helper narrows, but does not close, the window between the check and the merge:
`--match-head-commit` pins the head, and `main` can still advance in that gap, which is why the
post-merge verification of the exact commit remains necessary.
