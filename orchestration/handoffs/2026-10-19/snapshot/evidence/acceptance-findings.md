# Cookbook acceptance reconciliation — read-only governance evidence

Observed 2026-10-19 against current main `2dd687f858549ee8eeb9c98f83344814dfc7d0b6`.

## Scope and limits

This is an acceptance/status reconciliation, not repository code review and not an Opus review. No repository file, branch, pull request, issue body, issue state, label, ownership, or live budget was changed. No notebook or test suite was run by this task. Static source measurements, GitHub issue/PR retrieval, exact merge check/status retrieval, and merge ancestry/signature retrieval are the evidence below.

Read all bodies and all comments of #262, #283, #213, #249, #244, #245, #247, #276, #161, #163, #113, #74–#79, plus relevant #80 ledger decisions and current #53/#56 bodies. Complete normalized sources are in `acceptance-issues.json`, `acceptance-comments.json`, `acceptance-pr-evidence.json`, `acceptance-merge-checks.json`, and `acceptance-amendment-targets.json`. Historical PR receipts were read for their recorded scope, exact SHAs, acceptance tables, and explicit limitations; their asserted native model provenance was not recreated or independently authenticated in this task.

The repository assigns status, dispatch and serial merges to the existing primary. The last substantive [#80 handoff](https://github.com/Jev-Engineering/cookbook/issues/80#issuecomment-6187157003) says the five-branch run finished but dispatch and serial-merge ownership remain with that same primary. No explicit current broad ownership handoff or model substitution was found. Proposed changes below are for that owner; the current coordinator should preserve states and report the reconciliation until ownership is resolved.

## Priority recommendations

1. Preserve the pre-recording hold and reconcile **#213** against the newer partial delivery **#298**. Its closed state still does not satisfy the original six acceptance criteria.
2. Have the primary apply the exact **#53/#56** amendments below, verify both current bodies, and complete the remaining administrative criterion of **#283**.
3. Have the primary close **#262** using its existing acceptance receipt plus the fresh exact-main measurement below. Do not duplicate the cleanup.
4. Reconcile **#249** for administrative closure: its final review marks all four written criteria met, including the explicitly allowed recorded deferral. Retain #213 as the separate full counting/audit task. Recover the missing native reviewer identity/model evidence before certifying the historical review gate.
5. Prioritize **#276** guard soundness ahead of the **#244** 31-recipe objective-pin sweep. Keep the **#245/#247/#161** shared evaluation work serialized where paths overlap.
6. Keep **#163**, **#78**, **#79**, **#80**, and release **#73** incomplete. The broader catalog now has 100 ranks, but ranks 61–100 have no assigned recipe issue.

## #262 — recorded acceptance fulfilled; primary closure pending

[Issue](https://github.com/Jev-Engineering/cookbook/issues/262) is OPEN with `status: ready`.

The complete acceptance table is already in [6188243147](https://github.com/Jev-Engineering/cookbook/issues/262#issuecomment-6188243147). [PR #293](https://github.com/Jev-Engineering/cookbook/pull/293) removed the plural references and [PR #294](https://github.com/Jev-Engineering/cookbook/pull/294) removed remaining singular references. Both are merged. #294's recorded final review [6188147823](https://github.com/Jev-Engineering/cookbook/pull/294#issuecomment-6188147823) names agent `agent-ab31b21610741e7bb`, model `claude-opus-5[1m]`, full head `45d70cb0fdfdece489a80f0e14af9df1f870186d`, and ends in the matching APPROVE verdict. #293's recorded final review [6187736390](https://github.com/Jev-Engineering/cookbook/pull/293#issuecomment-6187736390) similarly approves `4a72ea69331f80ef54d86c3101c68ae27d199fdc`.

Fresh measurement used `git ls-tree` and `git show` on each exact commit, case-insensitive literal `build note`, any singular/plural form, tracked `.py`/`.md` content and notebook cell source under `recipes/`, excluding outputs:

| Commit | Source files scanned | Occurrences | Files with hits | Recipes with hits |
|---|---:|---:|---:|---:|
| Current main `2dd687f858549ee8eeb9c98f83344814dfc7d0b6` | 307 | 0 | 0 | 0 |
| Parent positive control `b4aa3ec7f4cf93c326aa9d72f57c7c07ea1999bd` | 307 | 9 | 6 | 5 |
| Earlier baseline `6fe0008b4aed05ac2350d9ce819803de568edf99` | 307 | 21 | 17 | 12 |

Criterion 2's reason-based reader-visible-source rule is still in [CONTRIBUTING §6](https://github.com/Jev-Engineering/cookbook/blob/2dd687f858549ee8eeb9c98f83344814dfc7d0b6/CONTRIBUTING.md#L95), delivered earlier in #186. Criterion 4 is conditional on a guard landing; neither cleanup PR changed a guard, and #225 owns that separate class-wide work. Zero matches of this spelling must not be presented as proof that all private pointers are absent.

**Next:** primary verifies ownership/current issue once more, closes with #293/#294 plus 6188243147 and the fresh scan. Preserve #225/#163.

## #283 — two criteria delivered; issue amendments still absent

[Issue](https://github.com/Jev-Engineering/cookbook/issues/283) is OPEN/reopened with `status: in progress`. Its [reopening comment](https://github.com/Jev-Engineering/cookbook/issues/283#issuecomment-6186068579) explains accidental keyword closure. Later [acceptance reconciliation 6186113105](https://github.com/Jev-Engineering/cookbook/issues/283#issuecomment-6186113105) corrects the scope: the guard decision criterion permits a reasoned partial implementation; it does not require every potential guard.

[PR #292](https://github.com/Jev-Engineering/cookbook/pull/292) merged as `bad1bf2997a7e8f0811d5b9719dd9fb6643efbdb`. Its final recorded [review 6186059618](https://github.com/Jev-Engineering/cookbook/pull/292#issuecomment-6186059618) explicitly marks:

- Criterion 1, #53/#56 amendments: **not met**.
- Criterion 2, issue-author guidance: **met**, in `.github/ISSUE_TEMPLATE/recipe.yml`; builder guidance also in `docs/recipe-template.md`.
- Criterion 3, enforcement decision: **met**; per-proposition coverage implemented, truth-combination and outcome-determining guards deferred with reasons.

Fresh live [#53](https://github.com/Jev-Engineering/cookbook/issues/53) and [#56](https://github.com/Jev-Engineering/cookbook/issues/56) still have their original Noul bullet and no such addition, and each has zero comments at this observation. Neither recipe notebook exists on current main. Preserve all existing bodies, dependencies, source references, and scope.

### Exact proposed addition for the primary to append to each issue

#### Multi-proposition Noul fixture coverage

If this recipe asks more than one Noul proposition together, its fixtures must satisfy all three requirements:

- Every proposition has at least one gold-true row and one gold-false row in each scored split, `validation` and `test`. Threshold selection uses only the validation split; the held-out test split remains untouched until choices are frozen.
- State explicitly which truth combinations the use case admits, and include at least one row for each admissible combination. For two propositions, consider both true, both false, and each true alone; document any combination excluded by the use case.
- For every proposition, include at least one row where that proposition's tag changes the composed Python outcome. Identify the row and demonstrate the effect with the other proposition tags and frozen policy settings held fixed.

These are separate obligations: positive/negative coverage alone does not establish truth-combination coverage or that each proposition can affect the composed outcome.

Add to the acceptance checklist:

- [ ] The fixture set demonstrates the three multi-proposition Noul requirements above, with per-proposition scored-split coverage, admissible truth combinations, and an outcome-determining row for every proposition.

### Application receipt needed

Re-read the latest body immediately before each update; append the addition without overwriting concurrent edits; read back both resulting bodies and record their URLs/update timestamps on #283. Only then consider criterion 1 fulfilled. This task did not apply the addition or dispatch a builder.

## #213 — closed state remains premature despite partial #298 support

[Issue](https://github.com/Jev-Engineering/cookbook/issues/213) is CLOSED. [6189254002](https://github.com/Jev-Engineering/cookbook/issues/213#issuecomment-6189254002) and [#80 6189282972](https://github.com/Jev-Engineering/cookbook/issues/80#issuecomment-6189282972) record its wrong closure via #280. The REST timeline independently shows closure at `2026-10-14T19:04:00Z`; the original reconciliation identifies #280 as closer. #280 merged two seconds before that.

The important new evidence is [PR #298](https://github.com/Jev-Engineering/cookbook/pull/298), merged after those comments as `68f7de69af42d4f561a338c8050fd65033c36d24`. It adds `AuditedBackend`, a ledger of logical `decide()` calls separate from distinct request keys, and an opt-in notebook audit path. It must be credited; repeating the old assertion that current source only contains the legacy comparison would be inaccurate.

It does **not** complete #213:

| Original criterion | Current acceptance disposition |
|---|---|
| Actual offline notebook decisions checked against declaration | Partial infrastructure only. All 50 published notebooks and the template contain **zero `AuditedBackend` uses** in their current cell source. Unaudited recipes still use the legacy fixture-count proxy. |
| Duplicate logical decision fails separately and names key | Not delivered by #298: repeated identical calls are intentionally counted independently and accepted when stated count matches. An accidental duplicate requires separate discrimination from intentional repeated states. |
| One declared source derives README count and budget instruction | Not delivered: current guard still extracts a handwritten README count with `LIVE_CALL_COUNT`; no recipe declaration migration or generation was shipped. |
| Documented inclusive cap cannot abort run | Not established for the current corpus. Logical calls and live HTTP attempts/retries remain different; budgets remain per backend. |
| Every published recipe audited; counts recorded | Missing. #298 says no recipe opts in; the historical review reports 49 PASS/1 scripted SKIP on both old/new guard. A structural call-site inventory is not the required runtime audit. |
| Budget arithmetic corrected on #80 before recording | Still unresolved. No reconciled usage/reservations or usable balance is established by this task or #298. |

Recorded #298 review [6204038240](https://github.com/Jev-Engineering/cookbook/pull/298#issuecomment-6204038240) itself documents an audited-scripted helper-backend undercount escape, and bounds the source reader as not proving arbitrary helper behavior. That is relevant future negative-control input, not a new blocking review of the already merged PR.

**Next:** primary reopens/reconciles #213, credits #298's additive support, and schedules remaining original audit/duplicate/declaration work. Preserve the pre-recording gate and cumulative $25 accounting. No live call, reservation, credential lookup, or fresh balance was authorized or attempted here.

## #249 — all four written criteria have a recorded final assessment

[Issue](https://github.com/Jev-Engineering/cookbook/issues/249) remains OPEN. [PR #280](https://github.com/Jev-Engineering/cookbook/pull/280) is merged and touches only `tests/test_recipe_guard.py`. Its [final review 6176064287](https://github.com/Jev-Engineering/cookbook/pull/280#issuecomment-6176064287), section 11, explicitly marks **all four criteria MET**.

Criterion 2 explicitly allows “a recorded decision explains why it cannot.” The review says that branch is discharged in the committed docstring, with the lossy proxy and deferred #213 work acknowledged. The later helper-based proposal changes the preferred design for #213; it does not erase this allowed deferral. The issue comment [6175619794](https://github.com/Jev-Engineering/cookbook/issues/249#issuecomment-6175619794) says item 2's fix remains but also records the corrected scripted-skip measurements. The primary should reconcile the difference between “possible fuller fix” and the listed acceptance condition.

**Caveat:** review 6176064287 ends in the exact-head OPUS-REVIEW marker but contains no explicit reviewer agent ID or resolved-model declaration. Its model provenance cannot be authenticated from this comment alone. Do not manufacture it. The former primary may retain the actual runtime receipt.

**Next:** primary recovers/authenticates historical review provenance and records acceptance reconciliation before closing #249; keep #213 open for the real call-count work. No new code PR is needed merely to repeat already delivered scripted-skip changes.

## Remaining implementation and sweep work

### #244 — objective-pin guard delivered; 31 recipe repairs remain

[Issue](https://github.com/Jev-Engineering/cookbook/issues/244) remains OPEN correctly. [6173678129](https://github.com/Jev-Engineering/cookbook/issues/244#issuecomment-6173678129) records #273's guard/template delivery and an explicit decision that the static source-spelling guard subsumes the keyword audit; the remaining work is clearing the genuinely unpinned recipes.

Current `tests/recipe_guard_known_failures.py` has exactly 31 `threshold_objective_pin` entries, all attributed to #244: **01–27, 29, 30, 33, 35**. These are not #163 debt. Each fix needs the recipe-specific real-source pin and proof, then removal of its own strict-xfail entry. Preserve #276's separate guard-polarity defects. **Next:** genuine builder/reviewer pipeline for bounded sweeps; no blanket removal of entries and no implication that CI xfails mean completion.

### #276 — guard soundness/recognition repairs remain

[Issue](https://github.com/Jev-Engineering/cookbook/issues/276) and [6173684525](https://github.com/Jev-Engineering/cookbook/issues/276#issuecomment-6173684525) require rejecting false-presence evidence in nested comparisons/count-zero/IfExp forms, accepting genuine `all`/`any` pins, recognizing `open(...).read()` and `read_bytes()` as source reads, and committed regression/mutation coverage. No later delivery was found in main history. **Next:** fix/verify the guard before using it as broad #244 cleanup certification; preserve currently supported shapes.

### #245 — missing min_coverage documentation and regression evidence

[Issue](https://github.com/Jev-Engineering/cookbook/issues/245) remains OPEN. Current `docs/evaluation.md` still describes `target_accuracy` extensively without the requested `min_coverage` direction/flat-region treatment. The docstring's parameter note still says only “Minimum answered fraction, in (0, 1].” Comments [6158276279](https://github.com/Jev-Engineering/cookbook/issues/245#issuecomment-6158276279) and [6162281876](https://github.com/Jev-Engineering/cookbook/issues/245#issuecomment-6162281876) require the parameter-local explanation, a wide flat-region test, and verification that a proposed reader exercise actually changes the thing it promises. **Next:** focused shared-doc/docstring/test PR with the recipe-40 test as reference; no need to redo already merged recipe fixes.

### #247 — latest ruling supersedes the simple inequality guard

[Issue](https://github.com/Jev-Engineering/cookbook/issues/247) remains OPEN. Read all three corrections. The final [6163789822](https://github.com/Jev-Engineering/cookbook/issues/247#issuecomment-6163789822) says inertness is not derivable from `t` and `g` alone: the Python composition determines the effect. It asks for the universal two-sided confidence band and each recipe's own with/without-gate measurement, split by side. A blanket `gate <= |2t−1|` failure would contradict this latest ruling. **Next:** primary records this current interpretation in the implementation brief/body, then genuine builder documents the band and demonstrates each actual composition; preserve the explicitly requested counterfactual decision/audit work.

### #161 — partial helper delivery; remaining API consolidation remains open

[Issue](https://github.com/Jev-Engineering/cookbook/issues/161) was explicitly reopened after #185 in [6082744814](https://github.com/Jev-Engineering/cookbook/issues/161#issuecomment-6082744814). Delivered: pooling/tally, ranking helpers, exempt-accept outcome curve, set/fallback metrics, hygiene `agent`, ULP and three-path docs. Later #187 delivered answered-denominator and deferral/coverage documentation; current docs contain these, so do not reschedule them.

Remaining: common accepted/correct representation, common action error-rate helper, per-outcome breakdown, curve support for unconditional rejection, and consistent `_score_value` use by `ndcg`/`mean_ndcg`. Current source still has `.score`-only extraction inside `ndcg` and `outcome_curve(..., exempt=None)` with explicit no-encoding text for unconditional rejection. The backlog container was assigned outside this issue's paths and should not be folded in silently. **Next:** update precise remaining scope under primary ownership; reuse delivered work and keep shared paths serialized.

### #163 — broad sweep remains partial

[Issue](https://github.com/Jev-Engineering/cookbook/issues/163) is OPEN correctly. All comments were read. Earlier A–F sweeps and #293/#294/#295 delivered much of it; current allowlist has no #163 entries, but that does not close every routed prose/consistency item.

Fresh source confirms two specific residues in [6104460938](https://github.com/Jev-Engineering/cookbook/issues/163#issuecomment-6104460938): recipes **06–11** still lead with the `.[ml]` install shape while their neighbors lead with `.[dev]`, and recipe **02** still lacks a “Pull request rules” heading. The first needs one shared install decision before a consistency sweep, not six ad hoc choices.

[6187052434](https://github.com/Jev-Engineering/cookbook/issues/163#issuecomment-6187052434) expressly excludes reverted recipe-45 margin/baseline work from #293; #295 only adds two glossary links. The remaining recipe-45 follow-up was an **unfiled local draft**, not a created issue. **Next:** primary reconciles remaining routed findings and retrieves/files the retained draft if still needed. Never claim the reverted work was shipped or reintroduce it to match a stale checklist.

### #113 — small genuine docs fix is ready technically

[Issue](https://github.com/Jev-Engineering/cookbook/issues/113) is OPEN with no comments. Its prerequisite #106/#112 is delivered: #112 merge `4e64560ade10f809058b941347081a8e270355ca`, signature valid, all five exact-merge checks successful, ancestor of current main. Current `docs/merge-readiness.md` still has “orchestration/PROMPT.md has not been amended” and “Until it lands the texts differ,” so the requested stale subsection remains.

**Next:** existing primary assigns the bounded `docs/merge-readiness.md` subsection-only fix to the prescribed builder, preserves every operative evidence gate/history caveat, then obtains genuine exact-head review. Ownership and model availability, not an undelivered #106, are the current blockers.

## Tracking issues and catalog

Fresh all-issue pagination confirms original foundation issues **#61–#72 closed**, recipe issues **#1–#50 closed**, **#51–#60 open**. Current catalog has **100 rows**, 50 published notebooks; rank 01–60 retains assigned issues 1–60, while rank 61–100 has **issue: null**. Those multimodal ranks are not repository issues #61–#100 and cannot authorize recipe PRs until actual assigned issues exist in the trusted base catalog.

| Tracker | Current state | Reconciliation / next step |
|---|---|---|
| [#74](https://github.com/Jev-Engineering/cookbook/issues/74) | Closed | Preserve historical completion. Original children closed and later closure comment verifies scope CI. Historical #81/#82/#86 reviewer model provenance gaps are explicitly disclosed in 6028948068; do not fill them in retrospectively. |
| [#75](https://github.com/Jev-Engineering/cookbook/issues/75) | Closed | Preserve delivered Wave 1 and routed #163 residue; checkbox staleness alone is not grounds to reopen. |
| [#76](https://github.com/Jev-Engineering/cookbook/issues/76) | Closed | Full consistency review 6079429778 and close-out 6079452279 exist; its routed debts remain separately tracked. |
| [#77](https://github.com/Jev-Engineering/cookbook/issues/77) | Closed | All 16 children closed. Closure 6157428580 openly deferred inbound-link residue to #214; preserve that explicit history. Correction 6163246146 changes 18 to 28 foundation issues and warns about default pagination. Do not reuse old counts. |
| [#78](https://github.com/Jev-Engineering/cookbook/issues/78) | Open | 11/13 delivered (#40–#50); #51/#52 and real wave audit remain. 6188146180 removed old missing-specification blocker and preserved native #147 dependencies. |
| [#79](https://github.com/Jev-Engineering/cookbook/issues/79) | Open | All 8 expert recipes still open. #53/#56 amendments precede their dispatch; #60 also waits on unfinished #59. |
| [#80](https://github.com/Jev-Engineering/cookbook/issues/80) | Open | Keep open with #73. Original 60-recipe campaign and newer catalog track must be reported separately; live evidence, accounting, final platform checks, release preparation and separate tag approval remain. |

This task did not independently re-review every historic recipe or authenticate every old approval. Preserve delivered status where existing audited routing explicitly leaves follow-ups open, and report concrete remaining defects through their owning issues.

## Fresh exact-merge metadata checks

Each row below was fetched from GitHub now: PR merged=true; merge commit GitHub signature verified with reason valid; exact merge latest CheckRuns all completed/success with matching total/row count and unique names; zero StatusContexts; merge ancestor of current main. Scope is PR-only and is not claimed as an exact-main check.

| PR | Merge SHA | Successful exact-merge check rows |
|---|---|---:|
| #112 | `4e64560ade10f809058b941347081a8e270355ca` | 5 |
| #280 | `5af4ab56e1411606c459a7fb1be956c871979d65` | 56 |
| #292 | `bad1bf2997a7e8f0811d5b9719dd9fb6643efbdb` | 58 |
| #293 | `b4aa3ec7f4cf93c326aa9d72f57c7c07ea1999bd` | 24 |
| #294 | `a25f6038c9935006b004222f998b8583968c4c38` | 13 |
| #298 | `68f7de69af42d4f561a338c8050fd65033c36d24` | 59 |

Full per-check names, IDs, app slugs and URLs are in `acceptance-merge-checks.json`. These checks establish delivered CI evidence, not missing reviewer provenance, future authorization, or full issue acceptance by themselves.
