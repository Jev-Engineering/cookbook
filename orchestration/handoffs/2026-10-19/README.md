# Execution handoff: 2026-10-19

This directory preserves a repository-safe copy of the supplied
`cookbook-execution-handoff-2026-10-19.zip`. It is a historical execution snapshot,
recorded against commit `2dd687f858549ee8eeb9c98f83344814dfc7d0b6` with the last
GitHub refresh at 2026-10-19 05:38:16 UTC. Read current GitHub state before acting
on its proposed next steps.

The source archive contains audit evidence and proposed GitHub updates. Importing
it does not execute those proposals, resume the campaign, certify acceptance,
close its tracked issues, or authorize live inference or a release. The original
handoff reports 67 issue-ledger rows, 44 retained branches and 14 proposed GitHub
updates. Its recorded CI and validation results describe the historical base.

## Contents

- [Original handoff overview](snapshot/README.txt)
- [Execution ledger](snapshot/execution-ledger.json)
- [Branch ledger](snapshot/branch-ledger.json)
- [Historical main verification](snapshot/main-verification.json)
- [Unpublished GitHub update proposals](snapshot/prepared-github-updates.json)
- [Supporting evidence](snapshot/evidence/)

## Source integrity and normalization

All 31 entries in the source manifest were verified against their recorded byte
sizes and SHA-256 digests before import. The original ZIP remains unchanged at
its supplied location. [source-manifest.json](source-manifest.json) is the
unmodified manifest from that ZIP; it describes the source files, not the
normalized copies.

The repository hygiene scanner flagged 141 high-entropy spans in 9 source
files, including public signature text, identifiers and compressed prose.
Those spans are explicitly replaced with `[omitted; sha256: ...]` markers. An
omission records a scanner match, not a finding that the source contained a
credential. JSON keys, structure and non-string values are preserved. All other
source files are byte-for-byte copies, apart from removing one extra blank
line at the end of the acceptance-findings document. Repository validation rules
are unchanged.

[import-record.json](import-record.json) records the original ZIP digest, each
source and imported file digest, and every omission's source character offsets,
line number and digest. [snapshot/manifest.json](snapshot/manifest.json) gives
the byte sizes and SHA-256 digests of the imported snapshot. Use that manifest
to validate these copies; use the source manifest with the original ZIP for
exact source evidence, including any omitted text.
