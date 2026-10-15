# Multimodal track: recipes 61–100

The multimodal track adds forty planned recipes to the original 01–60 curriculum. It preserves
the original recipes, slugs, issue assignments and contribution rules. The full forty use cases,
their ranks, slugs, decision types, difficulty and references live in
[`catalog/recipes.json`](../catalog/recipes.json). The generated [recipe catalog](../README.md)
shows which notebooks are available: a planned entry becomes published there only when its
`notebook.ipynb` exists. Catalog inclusion alone does not provide a working example or establish
that the shared package implements the required API support.

This plan preserves the user-provided proposal **“New Jev Cookbook Use Cases — Vision &
Multimodal Expansion”**, including its October 14, 2026 release context and eight suggested first
additions. The proposal motivates the curriculum; the official references S09–S12 below define
the API capabilities to verify during implementation. The contribution contract remains the
authority for fixtures, evaluation, review and publication.

## The forty planned recipes

| Ranks | Group | What the recipes teach |
| --- | --- | --- |
| 61–68 | Image understanding and visual judgments | Screenshot states and regressions, manufacturing defects, maintenance triage, shelf compliance, schematic symbols, product finishes and accessibility screening. |
| 69–76 | Visual criteria and reference matching | SKU recognition, brand verification, assembly samples, board-game pieces, UI states, material swatches, art direction and plant appearance groups. |
| 77–84 | Bounding boxes and spatial reasoning | Browser elements, signatures and stamps, diagram components, game HUDs, defects, reference-guided object search, tiled search and crop verification. |
| 85–92 | Multiframe and temporal understanding | Door transitions, arrivals and departures, game phases, visual action verification, conveyor jams, assembly stages, sports phases and highlight candidates. |
| 93–100 | Multimodal and long context | Bug-report evidence, report audits, livestream overlays, multilingual instructions, equipment troubleshooting, context comparisons, screenshot histories and agent handoffs. |

The catalog retains all forty proposals, including negative, unknown and review outcomes where
the task needs them. Multiframe recipes use chronologically ordered PNG or JPEG still frames;
Python owns decoding, sampling, timestamps and duration calculations. Localization recipes ask
for one target rectangle per `Box` question and check whether the target is present before using
the coordinates. The upstream image and Box contracts are in [S09: Images](https://docs.typesafe.ai/images)
and [S10: Box](https://docs.typesafe.ai/primitives/box).

## Suggested first additions

These are the eight starting points proposed in the supplied brief. They are curriculum
priorities, not claims that an implementation or dependency is ready.

| Rank | Recipe | First demonstration | Difficulty |
| --- | --- | --- | --- |
| 62 | Visual regression detection | Before-and-after screenshots with explicit change categories and severity rubrics. | Intermediate |
| 69 | Visual SKU recognition | Reference photographs inside fixed choice criteria. | Easy |
| 77 | Visual browser element locator | A presence check, one rectangle and a simulated browser action. | Intermediate |
| 80 | Game HUD perception | Visual perception composed with deterministic game-agent rules. | Advanced |
| 83 | Hierarchical visual search | Tile selection and coordinate mapping back to the full image. | Advanced |
| 88 | Visual action verification | Screenshot evidence for a simulated action's intended result. | Intermediate |
| 95 | AI livestream overlay verification | Frames checked against recorded agent state and displayed status. | Advanced |
| 98 | Long-context versus focused-context evaluation | A controlled comparison of full, retrieved and staged evidence. | Expert |

These numbers are recipe ranks. Repository issues 61–100 already serve foundation and tracking
work; they are not the tickets for these recipes.

## Before a recipe is ready

The [scaffolder](recipe-template.md) accepts ranks 1–100. A new multimodal entry starts with
`issue: null`; scaffolding it prints a notice and creates a local skeleton. Keep that work local
until a real repository issue is assigned to the slug in the trusted base catalog. A recipe pull
request must use that assigned issue as its sole closing reference. The
[scope guard](notebook-ci.md#the-scope-check) fails closed for an unknown or unassigned slug, and
an issue assignment made only in the pull request's head catalog cannot authorize it.

Shared implementation work must establish image-asset handling, image references in state and
question criteria, opt-in experimental headers, `Box` parsing, model-version pinning and faithful
recording/replay before a recipe can depend on those features. Coordinate conversion, annotation,
crop/tile transforms and ordered-frame handling need deterministic Python helpers and appropriate
tests. Shared code and workflow changes belong in foundation work under the
[contribution contract](../CONTRIBUTING.md).

The generic template supplies nine notebook sections and an offline workflow. Each visual recipe
still needs its own bounded questions, labeled visual inputs, Python policy, baseline and
evaluation. Keep fixtures synthetic and readable under the current
[fixture contract](fixtures.md); record image provenance and any applicable license. Include
ambiguous examples, negative examples and absent targets. A returned rectangle by itself cannot
establish that a target exists. Python controls all permissions, budgets, retries and simulated
effects.

Run offline by default with synthetic replay or a deterministic script and no key or network.
Live inference requires an explicit opt-in. Record the model version actually returned, the
capture date and the number of examples covered by each reported result. Model aliases can move;
use pinned versions for comparisons and consult [S11: Models and long context](https://docs.typesafe.ai/models).
These experimental recipes are demonstrations and evaluation studies. Publication still requires
the existing offline execution, fixture, hygiene, scope and exact-head review gates, including
the designated README integration stage and an Opus approval of the exact head.

## What an evaluation must show

Choose thresholds and other policies on `validation`, freeze them, and report on the held-out
`test` split. Compare methods on the same labeled tasks and keep the baseline visible.

| Decision or study | Required evidence |
| --- | --- |
| `Choice` and `Noul` | Classification accuracy and abstention/review rate, with coverage and risk computed from the Python rule's actual outcomes. |
| `Score` | Agreement with labeled rubric levels using a stated metric; show the answer distribution and explain each level. |
| `Box` | Intersection-over-union against labeled rectangles on present targets, plus separate absent-target and review outcomes. State the denominator so rejected or absent cases cannot disappear from the report. |
| Multiframe decisions | Event or transition accuracy against labeled sequences, with sampling, order and uncertain outcomes stated. |
| Resource comparisons | Latency, input tokens and cost for each compared inference mode only when those values were actually measured and recorded. State timing boundaries, model, capture date and N. |

Synthetic or scripted answers establish that the pipeline works. Their accuracy, IoU or event
scores must be labeled as pipeline checks, and their execution time cannot stand in for live
model latency. If live latency, token use or cost was not recorded, say it was not measured.
Report any cost calculation with its recorded token usage and pricing basis.

Long-context studies should generate configurable workloads, preserve the evidence given to each
method and report the actual recorded input-token count. The proposal's 262k-token mode is an
experimental capacity to investigate; a character count or an offline run does not demonstrate a
measured 262k-token inference. Follow the evidence and disclosure requirements in
[offline-and-live.md](offline-and-live.md) and [evaluation.md](evaluation.md).

## Official references

These source IDs match the catalog entries reviewed on October 15, 2026:

| Source | Reference | Implementation topic |
| --- | --- | --- |
| S09 | [TypeSafe AI: Images](https://docs.typesafe.ai/images) | PNG/JPEG assets, image references, comparisons and ordered still frames. |
| S10 | [TypeSafe AI: Box](https://docs.typesafe.ai/primitives/box) | One bounding rectangle, normalized coordinates, confidence and absent-target checks. |
| S11 | [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models) | Versioned models, moving aliases and the opt-in long-context limit. |
| S12 | [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14) | The October 14 release and the experimental image, Box and long-context capabilities. |
