# Orchestration prompt: finish the Jev Cookbook (recipes 51 to 100 and release)

How to use this file: open Claude Code in a clone of `Jev-Engineering/cookbook` and say
"Read `orchestration/FINISH.md` and carry it out." Everything below the line is addressed to that session.

This file extends `orchestration/PROMPT.md`; it does not replace it. PROMPT.md still defines the three
roles, the review gate, the rules that hold throughout, the merge procedure, and the builder, integration
worker and reviewer briefs. Where the two disagree, this file wins on **scope, counts and order**, and
PROMPT.md wins on **gates and safety**. Nothing here relaxes a gate.

## Owner decisions for this run (2026-10-20)

Confirm each with the owner before dispatching if it is not already recorded as a comment on #80. Once
confirmed, post them as one dated owner-decision comment on #80 and cite that comment in every brief.

1. **Models.** Builders and integration workers: Claude Sonnet 5.5 (`model: "sonnet"`). Reviewers:
   Claude Opus 5.5 (`model: "opus"`). The 2026-10-08 Sonnet 5 / Opus 5 substitution in PROMPT.md has
   lapsed. Verify what each alias actually resolves to before the first dispatch and record it. If either
   resolves to anything else, stop and ask; do not substitute. Commit trailer:
   `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Default service tier, no Fast mode.
2. **Scope is 100 recipes.** "Done" means 100 of 100 published, not 60. Issue #73 (release audit) and
   #80 (roadmap) are amended to say so through comments, not by rewriting history.
3. **You may open the recipe issues for ranks 61 to 100** and record their numbers in `catalog/recipes.json`
   through a reviewed foundation pull request (PR #296 assumed the owner would do this; this decision
   delegates it). Nothing else about the catalog's 40 multimodal entries changes without review.
4. **Live budget.** One cumulative $25 limit for the whole build, as decided on #80
   ([comment 6025510672](https://github.com/Jev-Engineering/cookbook/issues/80#issuecomment-6025510672)),
   covering everything already spent. Image and long-context requests are not authorized beyond it.
   Ask before exceeding it.
5. **Release.** One release, `v1.0.0`, after all 100 recipes. You stop at the tag; the owner tags.

## Where things stand

GitHub is the source of truth; verify every statement here before acting on it. As of `main` `57fca66`:

- **50 of 100 published** (recipes 01 to 50). Levels 1 to 3 closed; #78 (Level 4) and #79 (Level 5) open.
- **Recipes 51 to 60** are issues #51 to #60. #51 and #52 are `status: ready`; #53 to #60 are blocked on
  dependencies listed in the PROMPT.md manifest (most of which are now closed: re-check them).
- **Recipes 61 to 100** (the multimodal track) exist only as catalog entries with `issue: null`. Their plan,
  evidence rules and readiness checklist are in `docs/multimodal-track.md`. The scope guard rejects any
  recipe pull request for them until a real issue number is in the **base** catalog.
- **Multimodal foundation delivered:** #296 (catalog and tooling to 100), #297 (image inputs, `Box`,
  `src/jev_cookbook/vision.py`, image-aware replay keys and live headers), #298 (actual-backend-call
  audit). Not delivered, per #297: request accounting for repeated calls, plus everything on the
  `docs/multimodal-track.md` "Before a recipe is ready" list that #297 did not cover.
- **About 50 open foundation issues** (#113 to #290), mostly guard and documentation gaps found during
  waves 1 to 4. Several are p1.
- **#213 is closed but its scope was not delivered** (see its reconciliation comment 6189254002). It holds
  the pre-recording gate: no live recording until it is reopened, reconciled and genuinely closed.
- **No recorded live evidence exists.** All response fixtures are `synthetic`. Prior smoke usage against the
  $25 limit has not been reconciled.
- **Handoff archive** `orchestration/handoffs/2026-10-19/` holds a full ledger from a run that could not
  write to GitHub. Its 14 prepared updates were never published. Use it as a lead, not as evidence; its
  reconciliations for #213, #240, #244/#276/#282, #249, #262, #283 and #284 are worth reading.
- Open PR #301 (dependabot ruff bump) goes through the normal review gate like anything else.

## Done

Check each explicitly at the end, from GitHub, not memory:

- Every recipe issue for ranks 51 to 100, and every foundation issue opened or reopened during this run, is
  closed by a merged pull request with a genuine Opus receipt on its final head.
- Every pre-existing open foundation issue is closed by a merged, reviewed pull request, or carries a
  recorded triage decision ("deferred past 1.0" with the owner's agreement, or "won't fix" with reasons).
  None is silently left open.
- `python tools/render_catalog.py --check` passes on `main` showing **100 of 100 published**, every row
  linking to a notebook.
- Every current check is green on the final `main` commit.
- Live-recording coverage meets the owner requirement on #80 for every recipe, or the exact blocker is
  recorded per recipe.
- #73 is complete up to the tag, with release notes drafted in a pull request, waiting for the owner.

## Phase 0: take over and reconcile

1. Do everything in PROMPT.md "Run ownership" and "Where things stand": read `AGENTS.md` files, #80 with all
   owner decisions, `CONTRIBUTING.md`, `docs/development.md`, `docs/multimodal-track.md`, `docs/vision.md`,
   the workflows (`ci.yml`, `hygiene.yml`, `notebooks.yml`, `scope.yml`), the PR template, and the catalog.
   Enumerate every issue and pull request with pagination, including comments, reviews, threads and checks.
2. Confirm no other supervisor owns the run. The last #80 receipts name an existing primary that holds
   serial-merge control and #213. If it is live, coordinate; if it is not, record the takeover on #80 with
   evidence that it is idle. Never touch another owner's branch or worktree. The 44 retained branches stay.
3. Confirm you can write to GitHub (post a short takeover comment on #80). If writes fail, stop and say so.
4. Work through the handoff's reconciliations: reopen #213 if the evidence holds; apply the prepared #53 and
   #56 body amendments (append to freshly read bodies, verify the readback); decide #262 and #249 closure on
   genuine evidence only. Post a fresh ledger on #80.

## Phase 1: foundation triage

Sort every open foundation issue into one of three buckets and record the bucket on the issue:

- **Before more recipes.** Anything that changes what a new recipe must contain, or a guard that new
  recipes would otherwise pass wrongly: at least #218, #244 with #276 and then #282, #245, #247, #249, #283,
  #284, #209 (the scaffold importing a private API), and the flaky notebook #287, which reddens unrelated
  pull requests. Fixing these after 50 more recipes means 50 more fixes.
- **Before release.** Real defects that do not change the recipe contract (plotting, docs drift, helper gaps).
- **Defer or close.** Duplicates, superseded issues (the handoff found #240's helper already shipped), and
  anything the owner agrees can wait past 1.0.

Run the first bucket through the pipeline before opening Level 5 and the multimodal recipes, at most three
foundation pull requests building at once, merged serially. Foundation pull requests that change a guard,
the template or the fixture format get two independent Opus reviews on the same final head. The second
bucket can run alongside recipe work whenever it does not touch files recipe builders depend on.

## Phase 2: recipes 51 to 60

Follow the PROMPT.md manifest rows, waits-for columns and wave notes for Waves 4 and 5. #51 and #52 can start
as soon as Phase 1's first bucket is merged. Level 5 runs at most three builders at once, expects multi-run
builds, and splits reviews by scope. #54 and #55 (and #50, already merged) are harnesses whose READMEs say
"not measured live" until Phase 6 records them. Close #78 and #79 after each wave's catalog audit and
consistency review (PROMPT.md "After each recipe wave").

## Phase 3: multimodal foundation readiness

Before any recipe 61 to 100 is opened for building, have an Opus agent audit `main` against the
`docs/multimodal-track.md` "Before a recipe is ready" list and `docs/vision.md`, and report each item as
delivered (with a file and test as evidence) or missing. Expect gaps in at least:

- request accounting for repeated image calls (deferred by #297);
- how a recipe stores its images: a format and size limit, where they live under `recipes/<slug>/`, and how
  hygiene and the notebook output check treat binary assets;
- image provenance and licence fields in the fixture schema, enforced by the validator;
- deterministic helpers and tests for ordered frames (sampling, timestamps, durations) and for tiling and
  coordinate mapping back to the full image, if `vision.py` does not already cover them;
- `Box` evaluation: IoU on present targets, separate absent-target and review outcomes, and a stated
  denominator, as `docs/multimodal-track.md` "What an evaluation must show" requires;
- long-context runs: recording the real input-token count and refusing to describe a character count as a
  measured token count;
- synthetic image generation: a way for builders to produce readable test images programmatically, so no
  fixture contains a real photograph, a real brand, a real person or anyone else's copyrighted image.

Open one foundation issue per real gap, with acceptance criteria, and run each through the pipeline. Anything
that defines an interface or file format every multimodal recipe will copy gets two independent reviews.

## Phase 4: open the recipe issues for 61 to 100

1. Read three existing recipe issues of different levels (for example #4, #29 and #49) and match their
   structure: goal, what the recipe teaches, question design, hard cases the fixtures must include, Python's
   responsibilities, evaluation, Sources (from the catalog entry's source IDs, with S09 to S12 for every
   multimodal recipe), Dependencies, acceptance criteria, and labels (`type: recipe`, level, decision types,
   category, priority, size, status).
2. Derive each issue from its catalog entry and `docs/multimodal-track.md`; do not invent scope the catalog
   does not support. Every issue states the evidence rules for its decision types (the table in "What an
   evaluation must show"), the absent-target and ambiguous cases, and that images are synthetic.
3. Dependencies: every multimodal recipe waits for the Phase 3 issues it uses. Recipes that extend an
   earlier recipe's pattern also wait for that recipe (for example tiled search, rank 83, waits for the
   first `Box` recipe; multiframe recipes wait for the frame helpers). Write the dependency table as a
   manifest in the same format as PROMPT.md's, and post it on #80.
4. Open one tracking epic per group of eight (ranks 61–68, 69–76, 77–84, 85–92, 93–100).
5. Open a foundation pull request that records each issue number in `catalog/recipes.json` for its slug and
   nothing else. It gets two independent reviews: the scope guard trusts the base catalog, so a wrong number
   here lets the wrong pull request close the wrong issue.
6. Once all issues exist, post the issue-to-rank map on #80.

## Phase 5: build recipes 61 to 100

Same pipeline as every other recipe: one Sonnet builder per issue in its own worktree, branch
`recipe/<slug>`, the serialized integration worker, a fresh Opus reviewer on the integrated head, serial
merges with `--match-head-commit`.

- **Reference recipe first.** Build **69 (Visual SKU recognition, Easy)** alone, with two independent Opus
  reviews on the same final head, as #1 was for the text recipes. Then build **77 (Visual browser element
  locator)** alone as the `Box` reference and **85 (the first multiframe recipe)** alone as the frames
  reference, each with two reviews. Treat their findings about shared code as foundation issues and fix
  them before the rest of their group starts.
- Then follow the "Suggested first additions" order in `docs/multimodal-track.md` (62, 80, 83, 88, 95, 98),
  and the rest of each group by difficulty, at most six builders at once (three for Advanced and Expert).
- After each group of eight: catalog audit, an Opus consistency review across the group, then close its epic.

Add this to every multimodal builder brief, on top of PROMPT.md's builder brief:

> Read `docs/multimodal-track.md`, `docs/vision.md`, and the TypeSafe pages S09 (Images), S10 (Box) and
> S11 (Models) before designing a question. Every image in your fixtures is synthetic, generated by code
> in your recipe folder or by the shared helper, with its provenance recorded; never a real photograph,
> real brand, real person or anything copied from the web. A `Box` question asks for one rectangle, and
> your Python checks the target is present before it uses the coordinates; a returned rectangle never
> proves a target exists. Python owns decoding, frame order, sampling, timestamps, crops, tiles and all
> coordinate arithmetic. Include absent targets, ambiguous images and negatives. Synthetic IoU, accuracy and
> timing are pipeline checks and are labelled so beside each number; nothing you write may describe vision
> or long-context quality, latency, token use or cost unless it was recorded live.

And this to every multimodal reviewer brief:

> Open and look at the committed images yourself. Reject any that look like a real photograph, a real
> logo or brand, or a real person, or whose provenance is missing. Check that absent-target and review
> cases are in the reported denominator, and that no `Box` coordinates are used without a presence check.

## Phase 6: live recording

Not before #64 and the reconciled #213 are merged and approved, and only through the budget guard, exactly as
PROMPT.md rule 4 describes. Reconcile prior usage first, check TypeSafe's current published pricing for text,
image and long-context requests, and convert what is left of the $25 into request and token caps. Record in
this priority order, stopping when the remaining budget cannot safely cover the next recipe:

1. #50, #54 and #55, which cannot reach a real conclusion without it.
2. One reference recipe per kind: 01 (text), 69 (image), 77 (`Box`), 85 (frames).
3. 98 (long-context versus focused-context), on the smallest workload that still makes the comparison honest.
4. A held-out sample from the remaining recipes, spread across levels and decision types.

Every recorded result states N, the model version the API returned and the capture date. Recipes that are not
recorded say "not measured live". Post every reservation and spend on #80.

## Phase 7: release audit

Run #73 as PROMPT.md "Wave 6" describes, over all 100 recipes: fresh-clone offline execution on Linux and
Windows, the full contract, link and provenance audit, an Opus cross-recipe audit, Sonnet fixes through the
normal pipeline, and release notes in a pull request that say plainly what was and was not exercised live,
including how much of the vision, `Box` and long-context work was recorded. Before release, also land a
reviewed documentation pull request that brings `orchestration/PROMPT.md`, `README.md` prose and
`CONTRIBUTING.md` in line with 100 recipes. Stop at the human gate: no tag, no release, do not close #73 or #80.

## Then

Run PROMPT.md "The final audit" with 100 in place of 60, plus the triage record for every pre-existing
foundation issue, and give the owner the report PROMPT.md "What to tell me, and when" describes. Work through
to the end without checking in. Ask only for what is the owner's to decide: anything in the owner-decisions
block above that is not yet confirmed, a model alias that does not resolve as stated, spending past $25, a
`status: needs human` product question, deferring a foundation issue past 1.0, and the release tag.
