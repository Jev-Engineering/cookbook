# Fixtures

What goes in a recipe's `fixtures/` folder, and the tool that checks it:

```bash
python -m jev_cookbook.fixtures validate recipes/NN-slug   # exit 0 if valid, 1 with one line per problem
python -m jev_cookbook.fixtures validate --all             # every recipes/*/fixtures that exists
```

`--all` looks for `recipes/` in the current directory, so run it from the repository root; use
`--recipes-dir <path>` to point it elsewhere. A `--recipes-dir` (or default `recipes/`) that is not
a directory is a usage error (exit 2), so a typo cannot pass as "nothing to validate"; an existing
one with no fixture folders exits 0.

```text
recipes/NN-slug/fixtures/
├── inputs.jsonl            the examples: id, split, state (or fields), replay_keys
├── labels.jsonl            gold labels, one per scored example, same id
├── responses.json          model responses: {replay_key: stored response}
└── responses-<tag>.json    optional: the same requests answered by another model (comparison recipes)
```

A multimodal recipe also has `assets/` and `assets-manifest.json` beside `fixtures/`, checked by
the same command ([Image provenance manifest](#image-provenance-manifest)).

Those are the only files allowed in `fixtures/`. Any other file or folder is an error, so
nothing in that folder escapes validation and scanning. Keep other things (a recorder's request-id
ledger, a generator script, notes) outside it. That includes the live recorder's
`<stem>.drift-<model>.json` comparison files: any name containing `.drift-` is a stray.

All of them are UTF-8 and contain no comments. A leading byte order mark is accepted on
`inputs.jsonl` and `labels.jsonl` but **rejected on every responses file**, because
`ReplayBackend.from_json` opens them as plain UTF-8 and cannot parse a file that starts with one;
the validator may not accept a file the backend cannot load. Inputs and labels are **JSON Lines**,
one object per line, because a person reads and diffs one example per line, an error can name the
line, and examples are added by appending. Responses are one JSON object because that is the
format `ReplayBackend.from_json` already reads ([backends.md](backends.md)); this page does not
change it. Blank lines are ignored. The row schemas are in
[`schema.json`](../src/jev_cookbook/fixtures/schema.json) (JSON Schema, draft 2020-12); a
pattern must match the whole value, so an id with a trailing newline is refused.

## Inputs

```json
{"id": "t07", "split": "test", "state": {"text": "I was charged twice."}, "replay_keys": ["<64 hex>"]}
```

| Field | Rule |
| - | - |
| `id` | Stable, unique in the recipe: letters, digits, `_`, `.`, `-`, 1 to 64 characters, starting with a letter or digit. Never reused for a different example. Two ids that differ only by case are an error (ids tend to become file names). |
| `split` | `validation`, `test`, `train` or `demo` (below). |
| `state` | Exactly one of `state` and `fields`. `state` is the value passed to `backend.decide`: text, a JSON object, or a list of strings. |
| `fields` | The values the recipe's Python builds the state from (a JSON object), when the notebook assembles the state itself. |
| `replay_keys` | `replay_key(state, questions)` of every request the notebook replays for this example: 64 lowercase hex characters. May be empty (see "Replay and scripted recipes"). More than one when a later request depends on an earlier answer, in the order the notebook makes the requests, or when an example simply makes more than one independent request of its own (recipe 23 asks the same comparison twice, with the two candidates in each order, and lists both keys in the order it makes the requests). A `demo` example may list keys (list them if the notebook replays it); if it does, the responses must exist like any other. |

The validator cannot rebuild a request, because the questions live in the notebook. So the link
from an example to its responses is written down: `replay_keys`. Compute the keys in the script
that writes the fixtures, never by hand. Change a question and the keys change; the validator
then reports the old responses as unreferenced and the new keys as missing. The key is the
hash of what Jev sees, so examples that differ only in values Python owns (a field `build_state`
leaves out, such as a role, an amount or a budget) legitimately share a key, and so do examples
whose later request is the same. The validator therefore checks one thing: two `state` examples
that each list exactly one key may not share it unless their `state` is the same. That catches a
key copied from another example. For `fields` examples and for examples listing several keys the
validator cannot see the request, so only a replay run shows a wrong key.

## Splits

- `validation`: choose thresholds, prompts and options here, as often as you like.
- `test`: report on it once, after the choices are frozen. Never tune on it.
- `train`: optional, for a baseline that learns from examples.
- `demo`: shown to the reader to illustrate a typed answer, never scored. It needs no label,
  and a label for a demo example is an error (it would only be ignored, and invites scoring it).

Both `validation` and `test` must have at least one example. **Leak rule:** the same content in
two different splits among `train`, `validation` and `test` is an error, because it would leak the
test set into the choices made on validation (or into training). Content means `state` for an
example that has `state`, and `fields` for an example that has `fields`; they are compared as JSON,
whatever the key order. `demo` examples are exempt. The same content twice inside one split is
allowed, but double counts that example.

**Replay-key leak rule:** a `fields` example's `state` is built by the recipe's `build_state`,
which the validator never runs, so two examples with different `fields` can still ask Jev the
identical request without the content check above noticing (recipe 14's `v17` and `t15` did
exactly this: different `fields`, but the same `replay_keys` entry, caught only once replay
itself was inspected). `replay_keys` is the hash of what Jev actually sees, so the validator
compares it directly: the same *complete* list of keys (order ignored, so listing them out of
order does not escape comparison) listed by an example of a different split among `train`,
`validation` and `test` is an error, naming both ids. Comparing the whole list, not one key in
isolation, is what keeps a legitimately shared *later* key legitimate (the same quoted sentence
above, "so do examples whose later request is the same"): such an example keeps a distinguishing
earlier key of its own, so its complete list still differs from every other example's, and
nothing is flagged; only two examples whose entire set of requests matches, key for key, are a
leak. That covers a one-key example's sole key (recipe 14's case) and a multi-key example's
whole set alike (recipe 23's two independent, mirrored requests per example). `demo` is exempt
here too.

## Labels

```json
{"id": "t07", "label": "billing"}
```

`label` is any JSON value except `null`: a string, number, boolean, list, or object (for several
labels). Every `train`, `validation` and `test` example needs exactly one label; a label whose
`id` is not in the inputs is an error.

### Box labels

A recipe whose question asks for a `Box` labels each example with a gold Box label, so ten
recipes do not invent ten formats. An object with a boolean `present`:

```json
{"id": "t07", "label": {"present": true, "box": {"top": 0.25, "bottom": 0.75, "left": 0.125, "right": 0.625}}}
{"id": "t08", "label": {"present": false}}
```

- `present: true` has exactly `present` and `box`. `box` has exactly `top`, `bottom`, `left`
  and `right`: finite numbers in [0, 1] (normalized to the image, as in
  [`docs/vision.md`](vision.md)), with `left < right` and `top < bottom`, and an area that
  does not underflow to zero.
- `present: false` has exactly `present`. It means the target is not in the image. It carries
  no `box`, not even a `null` one; `null` is never a label.
- `present` is a JSON boolean. `"yes"`, `1` and `null` are errors.

`vision.gold_box(label)` decodes one (the rectangle, or `None` for absent) and raises
`ValueError` on anything else; `vision.localization_report` takes these labels directly.

The validator treats a label that is an object with a `present` key as a Box label: that is
how a recipe declares the format, so `present` is reserved at the top level of a label object.
Every such label must pass `gold_box`, and once any label in the file is a Box label, a label
that is not (a bare box, a string) is an error. A recipe whose label holds a Box label among
other values nests it under its own key and calls `gold_box(label["target"])` in its own test;
the validator does not look inside other labels, so that test must cover every split the
recipe ships (`train` included), not only the one it reports:

```json
{"id": "t12", "label": {"target": {"present": true, "box": {"top": 0.25, "bottom": 0.75, "left": 0.125, "right": 0.625}}, "rubric": 3}}
```

Store the gold box once, for the whole image, as a full-image Box label. A recipe that tiles
the image does not store a tile choice beside it: a stored tile name can disagree with the box
(for an absent target there is no right tile at all, only "no match"), and with overlapping
tiles a target near a seam lies in more than one tile, so one string cannot hold the gold.
Python derives which tiles count as correct from the box and the tile bounds, and the
headline report stays per image ([vision](vision.md#tiled-and-hierarchical-recipes)).

## Nesting limit

No JSON value in a fixture file nests deeper than **64 levels**, counting the line (or, in a
responses file, the whole object) as level 1. This holds for `inputs.jsonl`, `labels.jsonl`,
`responses.json` and every `responses-<tag>.json`. Parsers and stacks disagree about very deep
JSON (a state that one Python version reads is a `RecursionError` on another, and even where it
parses, `replay_key` and the backends cannot hash it), so the validator counts brackets outside
strings before it parses and reports a line past the limit as a problem naming the file and line
(a responses file: the line where the limit is crossed). The same holds on every interpreter. No
real state, label or stored response comes near 64. Like any malformed line, an over-deep one is a
problem and not a crash, and `--all` goes on to the next recipe.

In `inputs.jsonl` the line itself counts as level 1, so the `state` object inside it starts at level 2 and a state can be at most 63 levels of its own, while `replay_key` accepts 64 ([backends.md](backends.md), "Replay key").

## Replay and scripted recipes

Most recipes replay: the notebook answers each request from stored responses. Some do not. A
recipe built on `ScriptedBackend` or a simulator (the scripted and simulated catalog entries)
has nothing to replay, and the contract says code never invents an answer, so the format does not
make such recipes write responses just to pass.

- `replay_keys` may be empty for an example, including for every example.
- `responses.json` may be **absent** when no example lists a key. It is required when any example
  does, and then every listed key needs a response.
- The validator reports the recipe's **mode**: `replay` when some example lists a key, `scripted`
  when none does. The CLI prints it (`fixtures valid (mode scripted)`), and
  `validate_recipe(...)` returns a list of `Problem` with a `.mode` attribute (`None` when
  `inputs.jsonl` could not be read). CI and the recipe template can act on it. Slicing,
  `.copy()` and `report + problems` keep the mode, `repr()` shows it, and other list operations
  (`sorted`, `*`) return a plain list.
- In scripted mode a responses file that exists is still checked, so every response in it is
  reported as one that no input lists. Delete it.

## Responses and provenance

`responses.json` is exactly `{replay_key: DecisionResult.to_dict()}`: see "Stored response" in
[backends.md](backends.md). Every answer carries its provenance (`synthetic`, or `recorded` with
the model string and the `YYYY-MM-DD` date), which `DecisionResult` already enforces. On top of that
the validator requires, for each responses file on its own, that:

- all responses in the file agree: it is all `synthetic` or all `recorded`, so a recorded file
  containing a synthetic answer is an error, and mixed files are an error;
- all responses name one model (dates may differ between responses);
- every response is listed in some input's `replay_keys`, and every listed key has a response.

A synthetic response says nothing about how Jev performs; never label anything `recorded` that
did not come from a real API call ([CONTRIBUTING.md](../CONTRIBUTING.md), section 2). Avoid
synthetic responses so tidy that every model-free baseline scores perfectly on `test`: put the
hard cases in the labels and let the stored answers be wrong on some of them.

### Comparison recipes: `responses-<tag>.json`

A recipe that compares models or backends (model comparison, adaptive routing) answers the same
requests with each one. `responses.json` stays the default and is the only file a notebook reads
unless it asks for another. Each extra set is `responses-<tag>.json`, where `<tag>` follows the id
rule (letters, digits, `_`, `.`, `-`, up to 64 characters). Each file is a normal `ReplayBackend`
file validated by the rules above, so one provenance and one model per file; different files may
name different models. Because a comparison answers the same requests, **every replay key listed
in `inputs.jsonl` must be present in every responses file**, and none may hold a key nobody lists.
Never mix two models in one file; that is what the extra files are for.

```python
from jev_cookbook import get_backend
from jev_cookbook.fixtures import responses_path

baseline = get_backend(fixtures=responses_path())  # responses.json
other = get_backend(fixtures=responses_path(tag="b"))  # responses-b.json
```

`responses_path(recipe_dir=None, tag=None)` and `load_responses(recipe_dir=None, tag=None)` take
the tag; a tag that breaks the id rule is a `ValueError`.

## Secrets

Each file, and each JSON string inside it, is scanned for key- and token-shaped strings with the
rules of `tools/check_hygiene.py` (same rule names, secret rules only). The scanner is copied
into the package because `tools/` is not installed, and a test compares the copy's rule
definitions and function source with `tools/check_hygiene.py`, so editing one copy fails the
tests. The message gives the file, line and rule, never the whole value.

Hard cases often need a fake password or key (a prompt-injection line, a phishing message, a
leaked-credential report). What the scanner flags and exempts:

- **Key-name and header style values.** `authorization: <value>` (8 or more characters),
  `Bearer <value>` (16 or more) and `<name> = <value>` or `<name>: <value>` (16 or more letters,
  digits and `_ - . / + =`, with at least one letter and one digit), where `<name>` contains
  `api_key`, `api-key`, `apikey`, `secret`, `token`, `password`, `passwd`, `access_key`,
  `access-key` or `credential`. These three rules **exempt a value that contains a marker**:
  `your`, `example`, `xxx`, `redacted`, `placeholder`, `changeme`, `dummy`, `<`, `>`, `{`, `}`,
  `$`, `...`, `…` or `***` (in any case). `password: EXAMPLE-Summer2024Holiday` passes.
- **Vendor-shaped strings are always flagged, marker or not:** `sk-` followed by 20 or more
  characters, `ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_`, `github_pat_`, `AKIA`/`ASIA` ids, `AIza` keys,
  `xox?-` tokens, JWTs and private-key blocks. `sk-EXAMPLE` followed by 20 more characters, a
  `ghp_` value with `EXAMPLE` in it, and AWS's own documentation access key id are flagged.
- **Long random-looking tokens are flagged:** a run of 32 or more of `A-Z a-z 0-9 _ + = -`
  (also `/` outside path- and URL-shaped words) that mixes letters with digits (or `+`, `/`,
  `=`) and has an entropy of 4.2 bits per character or more. An `api_key=` value that starts with
  `EXAMPLE_` but goes on as a long mixed run of this kind is flagged by this rule, marker or not.
  The one exception: a bare `name=VALUE` assignment (both sides runs of letters of one case or
  of digits joined by `_`, the value also by `.`, no quotes, and a name that does not contain
  api key, secret, token, password, access key or credential), such as the keyword argument
  `startup_timeout=KERNEL_START_TIMEOUT`, is not scored by this rule.

So write a fake credential that is short (under the lengths above), low-entropy (a repeated chunk
or plain words), or clearly not vendor-prefixed; truncate prefixes (`sk-...` is under the length
rule) or describe the credential in words. This example passes, and the test suite checks it:

<!-- accepted-fake-credential -->
```text
Your mailbox is full. Reply with your password (for example: hunter2) and the key sk-... to keep it.
```

Never commit a real credential, and never a realistic fake.

## Where the notebook runs

A notebook runs with its recipe directory as the working directory. That is a convention the
recipe relies on, not something these helpers enforce; the recipe CI (#69) runs the executor on a copy of the recipe folder, which sets the working
directory to that folder. Helpers take an explicit `recipe_dir` and default to the
current directory. Tests pass `Path(__file__).parent.parent`.

```python
from jev_cookbook import get_backend
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

examples = load_inputs()  # list[Example]: id, split, state, fields, replay_keys
labels = load_labels()  # {id: label}
backend = get_backend(fixtures=responses_path())
for example in select_split(examples, "validation"):
    result = backend.decide(example.state, questions)
```

`load_responses()` returns the raw `{replay_key: stored response}`; `validate_recipe(recipe_dir)`
returns the problems (empty when valid) and the mode. Loaders raise `FixtureFileError`, whose
message names the file and the line or id, for example
`recipes/03-x/fixtures/inputs.jsonl:5 (id 't02'): duplicate id (first used on line 2)`.

## Per-item option order

Whenever a recipe needs a per-example order it does not want to come from the data itself —
which candidate a `Choice` lists first, which of two answers is shown first in a pairwise
comparison — derive it from
`jev_cookbook.fixtures.stable_permutation(f"{recipe}:{example_id}", n)` (or
`stable_shuffle(seed_key, items)` to get the items themselves back in that order), never from
`random.shuffle` and never from the position an item already has in the authored list or in
`ROWS`. `{recipe}` here is the recipe's own slug (`"12-thesaurus-word-selection"`, never the bare
issue number `"12"` or `12`): a seed key is a string a person reads while debugging a replay
miss, and the slug is what the rest of the fixture tooling, and a recipe's own `helpers.py`,
already use to name the recipe.

Two different things go wrong otherwise:

- **`random.shuffle` is not a documented-stable algorithm across CPython versions.** The
  `random` module's docs promise only that `random.Random.random()` keeps producing the same
  sequence for the same seed; they make no such promise about `shuffle()`. A replay key is a
  hash of exactly what Jev is asked, options included, so the moment a generator's shuffled
  option order depends on a Python version's `shuffle()` output, the committed fixtures and the
  notebook that replays them become byte-reproducible only by accident, on whichever
  interpreters happen to agree. `stable_permutation` instead builds the permutation itself
  (Durstenfeld's Fisher-Yates) calling nothing but `random()`, so it is pinned forever (see
  `src/jev_cookbook/fixtures/permutation.py` for the full construction, and issue #181).
- **List position proxies grouped gold.** Fixtures are usually authored gold-candidate-first,
  for readability, and often written a whole target word or topic at a time — so the authored
  order is correlated with the label, and a frozen rule that always picks "option 1" can look
  right for the wrong reason (recipe 12 hit exactly this: an earlier draft that asked Jev in
  authored order let "always answer option 1" score as well as the real rule). Deriving the
  order from a hash of the example's own id, independent of every other example and of the
  authored order, breaks that correlation without touching which candidates are offered or what
  the gold label is.

```python
from jev_cookbook.fixtures import stable_permutation, stable_shuffle

order = stable_permutation(f"{recipe}:{example_id}", len(candidates))  # a permutation of indices
shown = stable_shuffle(f"{recipe}:{example_id}", candidates)  # the candidates, in that order
```

For a binary choice such as which of two candidates is shown first, use `n = 2`:
`stable_permutation(seed_key, 2)[0] == 0` says the first candidate keeps its place.
`stable_permutation`/`stable_shuffle` live in the shared package precisely so every recipe's
per-item order is derived the same documented-stable way; recipe 12's `shuffled_candidates`
(candidate order via `stable_shuffle`) and recipe 23's `assign_first_shown` (a pairwise side via
`stable_permutation(..., 2)`) are the two shapes this takes in practice.

## Writing fixtures

### Image fixtures

Keep small synthetic PNG/JPEG files in the recipe's `assets/` directory, beside `fixtures/`.
The fixture directory continues to contain only its documented JSON/JSONL files; image bytes
and base64 do not belong in those files.

#### The image-file contract

`python tools/check_recipe_assets.py` enforces these rules on every tracked file under
`recipes/`, in the `Hygiene (secrets and notebook outputs)` job. Each finding names the file and
the rule (`path: [rule] message`).

| Rule | Contract | Finding |
| - | - | - |
| Location | An image lives only in `recipes/<slug>/assets/`, optionally in subfolders. Anywhere else under `recipes/` (`helpers/`, `fixtures/`, the recipe root), a file with an image suffix (`.png`, `.jpg`, `.gif`, `.webp`, `.svg`, `.bmp`, `.ico`, `.tif`, `.heic`, `.avif`, `.jp2` and the like, in any case), or whose content begins like a PNG, JPEG, GIF, WebP, TIFF, BMP, ICO, HEIF/AVIF, JPEG 2000 or SVG file under any name, is rejected. An image written as base64 or a `data:` URI inside a text file (a README, `helpers.py`) is not detected. `assets/` holds image files only. | `image-outside-assets`, `non-image-in-assets` |
| Format | PNG or baseline JPEG, with a lowercase `.png`, `.jpg` or `.jpeg` suffix, whose bytes really are that format (a GIF renamed `.png` fails). GIF, WebP, SVG, TIFF and the other formats, animated PNG, progressive or arithmetic-coded JPEG and bytes after the end of the image are rejected. Any PNG colour type and bit depth (8 or 16 bit, interlaced or not) and an 8-bit JPEG with one or three components are accepted. | `format-not-allowed`, `suffix-case`, `format-mismatch`, `png-animated`, `jpeg-not-baseline`, `trailing-data`, `png-structure`, `jpeg-structure` |
| Pixels | Each side 280 to 1568 pixels and the area 78,400 to 2,458,624 pixels: the limits of the [Images page](https://docs.typesafe.ai/images) (an image outside them is rejected by the API, never resized). | `dimensions` |
| Size | At most 1 MiB (1,048,576 bytes) per file, and at most 8 MiB in all in one recipe's `assets/` folder. These caps are this repository's, far below the API's 16 MiB per file; a fixture is meant to be small enough to read about. | `file-too-large`, `assets-total-too-large` |
| Metadata | A PNG holds only the chunks `IHDR`, `PLTE`, `IDAT`, `IEND`, `tRNS`, `gAMA`, `cHRM`, `sRGB`, `sBIT`, `pHYs` and `bKGD`: no `tEXt`, `iTXt`, `zTXt`, `eXIf`, `tIME`, `iCCP` or private chunk. Each of those has exactly the length the PNG format fixes for the image (so no text hides after the fixed fields), `PLTE` appears only in a palette image, and the `IDAT` data is one zlib stream with nothing after it. A JPEG is checked against an allowlist of markers: SOI, one `APP0` that is exactly a 16-byte JFIF header with no thumbnail, `DQT`, `DHT` (both whole tables only), `DRI` of length 4, one `SOF0`, `SOS`, `RSTn` and EOI. Every other marker is rejected, so no EXIF, XMP, ICC, IPTC, Adobe or other `APPn`, no comment, and no second `APP0`, `DNL` or reserved segment. Text and EXIF can carry an author name, a local path, a GPS position or a token. These rules remove the places where ordinary tools write metadata into an image; they are not a detector for deliberately hidden bytes, which pixel values can always carry. | `png-metadata`, `jpeg-metadata` |
| Links | No symbolic link or submodule anywhere under `recipes/`. | `symlink` |

The `Scope (recipe pull requests)` check also rejects, by suffix, an image added, changed or
renamed anywhere in a recipe pull request outside `recipes/<slug>/assets/` (deleting a
misplaced one is allowed). The pixel limits are constants at the top of
`tools/check_recipe_assets.py`, copied from the Images page because the checker runs with no
install and so cannot import `jev_cookbook.vision`; change them there if the API's limits change.

To make a file comply, copy the pixels into a new image and save that. `Image.save` writes no
text, EXIF or comment you did not pass, but saving to PNG does carry a source's ICC profile
across (the `iCCP` chunk fails the check), so do not re-save the opened file itself:

```python
from PIL import Image

with Image.open("source.png") as source:
    rgb = source.convert("RGB")
clean = Image.frombytes("RGB", rgb.size, rgb.tobytes())
clean.save("recipes/NN-slug/assets/example.png")  # or .jpg: Pillow writes a baseline JPEG
```

Apply `ImageOps.exif_transpose` before the copy if the source has an orientation tag, as
[vision.md](vision.md) says, because the copy drops the tag. A CMYK source fails with an `APP14`
(Adobe) finding until `convert("RGB")` has run, which the snippet does.

A matplotlib figure saved with `fig.savefig(path)` carries a `tEXt` `Software` chunk, which fails
the check; save it with `fig.savefig(path, metadata={"Software": None})`.

A PNG over the 1 MiB cap is almost always photographic or noisy content: save that as a baseline
JPEG, which is usually a tenth of the size. Flat synthetic content (screenshots, diagrams) is a few
KB as a PNG even at 1568 x 1568.

A notebook that displays fixtures is held to an output cap (2 MiB for all its outputs), its
displayed images are compared by what they show, not by their bytes, and every image embedded in
it is held to the same metadata rules; a Markdown cell may not embed an image at all (link the
file under `assets/` by its relative path). See rules 2 to 5 of
[the staleness check](notebook-ci.md#the-staleness-check). **Display a fixture with
`IPython.display.Image(filename=path)`**, which embeds the file's own bytes once: displaying a
`PIL.Image` instead re-encodes the pixels as a PNG and a JPEG, which weighs 8 to 22 times the file
for photographic content (a 120 KB frame becomes 1.98 MB). If you do display a `PIL.Image`, call
`thumbnail((640, 640))` on a copy first.

An image example uses `fields` containing relative image paths and any other request inputs.
The recipe loads those files with `jev_cookbook.vision.image_asset(path, root=RECIPE_DIR)`
(or `image_assets` / `load_frames` with the same `root=`, or `resolve_asset_path` directly),
where `RECIPE_DIR` is the recipe folder. A path read from a fixture is data, not code: with
`root=` an absolute path, a URL, a `..` that leaves the folder, or a symlink pointing outside it
raises `AssetPathError` (a `ValueError`) instead of being opened. Never pass a fixture-supplied
path to `image_asset` without `root=`. The recipe then constructs stable
references with `image_reference`, and calls
`replay_key(state, questions, assets=assets)` when writing `replay_keys`.
The notebook builds the same state and assets and calls
`backend.decide(state, questions, assets=assets)`.
Store image paths in `fields` even when the textual state is otherwise identical: the
validator compares fields for split leakage, while the replay key covers the actual image
content. The validator compares image bytes across splits through the manifest's hashes (see
[Image provenance manifest](#image-provenance-manifest)); it does not decode pixels, so recipe
tests must still check lineage where the same picture could be saved with different bytes.

The input row schema is unchanged; do not add a top-level `assets` field. Labels can contain
the gold Box label above (a normalized box, or the explicit `{"present": false}`). A response's `BoxAnswer.to_dict()`
stores `type`, the four-edge `box`, nullable `confidence`, and the ordinary provenance.
`DecisionResult` and the fixture validator reject malformed geometry and confidence.
Missing confidence means unknown, never certainty. A Box is still returned for an absent
target, so labels and tests should exercise a separate presence/review rule.

#### Image provenance manifest

Every recipe with an `assets/` folder has one more file, `assets-manifest.json`, **beside**
`assets/` (not inside it: `assets/` holds image files only, and the file is part of the recipe
folder, so a recipe pull request edits it like any other recipe file). It records, for every image,
where it came from, under what licence, and what its author attests about it. A recipe with no
`assets/` needs no manifest. `python -m jev_cookbook.fixtures validate recipes/NN-slug` (and
`--all`, and the fixtures step of CI) enforces it; the format is also described by
[`assets-manifest.schema.json`](../src/jev_cookbook/fixtures/assets-manifest.schema.json).

```text
recipes/NN-slug/
├── assets/                  the images (and nothing else)
├── assets-manifest.json     one entry per image: provenance, licence, attestations
├── build_fixtures.py        the generator the entries point to
└── fixtures/
```

A worked example, for one image that `build_fixtures.py:draw_scene` drew (this block is parsed
and checked against the schema by `tests/test_fixtures_assets.py`):

```json
{
  "schema": 1,
  "assets": [
    {
      "path": "assets/scene-0.png",
      "sha256": "07c5f86f91ad18fef9ba8cad26e24e30ab100e69199c6e4d4b9ccf59a88fa680",
      "format": "PNG",
      "width": 320,
      "height": 300,
      "origin": "generated",
      "generator": "build_fixtures.py:draw_scene",
      "parameters": {"seed": 0, "shapes": 1, "background": [250, 250, 245]},
      "licence": "CC0-1.0",
      "description": "A blue rectangle on an off-white background; no target present.",
      "attestations": {
        "synthetic": true,
        "real_photo": false,
        "real_brand": false,
        "real_person": false,
        "third_party_content": false
      }
    }
  ]
}
```

| Field | Meaning |
| - | - |
| `schema` | Always `1`. |
| `assets` | One object per file under `assets/`, in any order, at least one. |
| `path` | Relative to the recipe folder, forward slashes, starting `assets/`, lowercase `.png`/`.jpg`/`.jpeg`. Letters, digits, `_`, `.`, `-` only, and no segment starts with `.`, so it can contain no `..`. It is exactly the string an `inputs.jsonl` `fields` value uses. |
| `sha256`, `format`, `width`, `height` | Digest of the file's bytes (the digest behind `image_reference`), `PNG` or `JPEG`, and pixel size. Checked against the file. |
| `origin` | `generated`: drawn by the recipe's own code. Nothing else is allowed. |
| `generator` | `build_fixtures.py:draw_scene`: a `.py` file in the recipe folder (it must exist and mention the function name), or `jev_cookbook.<module>:<function>` for shared code. |
| `parameters` | The arguments, seed included, that reproduce the file from the generator. `{}` if there are none. |
| `licence` | `MIT` (this repository's licence) or `CC0-1.0`. Third-party material is not allowed, so no other licence is. |
| `description` | What the image shows, for a reader who cannot see it. |
| `attestations` | All five keys, as booleans: `synthetic` true; `real_photo`, `real_brand`, `real_person`, `third_party_content` false. They state that the image is drawn by code and contains no real photograph, brand or logo, person, or third-party artwork or screenshot. |
| `shared_across_splits` | Optional boolean, default `false`; see the last rule below. |

Each failure is one line, `path: [rule] message`, naming the image (or the manifest, or
`fixtures/inputs.jsonl` and the example id for a `fields` problem):

| Rule | Fails when |
| - | - |
| `manifest-missing` | The recipe has files under `assets/` and no `assets-manifest.json`. |
| `manifest-invalid` | The manifest is not UTF-8 JSON (duplicate keys and `NaN` are refused) or not an object. |
| `manifest-field` | A field is missing, unknown, or of the wrong type or value (including `origin` other than `generated`, a bad `sha256`, `format`, `width`, `height`, `generator`, `parameters`, an empty `description`). |
| `asset-path` | A listed `path` is not a clean `assets/...` path (absolute, `..`, a backslash, a URL, a hidden or doubled segment, wrong suffix or case), or its file resolves outside `assets/` (a symbolic link); or a `fields` image path is not written `assets/<name>.png` with forward slashes (a drive letter, a backslash, `./`, `..`, a URL), or escapes the recipe through `resolve_asset_path(path, root=recipe)`. |
| `licence` | `licence` is missing or not `MIT` or `CC0-1.0`. |
| `attestation` | An attestation is missing, unknown, not a boolean, `synthetic` is not true, or any other is not false. |
| `duplicate-entry` | One path is listed twice. |
| `unlisted-asset` | A file under `assets/` has no entry, or a `fields` image path names no entry. |
| `missing-file` | An entry's file is not in `assets/`. |
| `hash-mismatch`, `format-mismatch`, `size-mismatch` | The file's SHA-256, format (read from the bytes) or pixel size is not what the entry says. |
| `generator` | The generator script is not a file in the recipe, or does not contain the function name. Whether the function really draws the image is for the reviewer. |
| `split-leak` | Examples in different scored splits (`train`, `validation`, `test`) name images with the same bytes, under one path or two. |

A **`fields` image path** is any string value in `fields`, at any depth and under any key, that
has no whitespace and starts with `assets/`. In a recipe that has images (an `assets/` folder or a
manifest) a string that ends in `.png`, `.jpg` or `.jpeg` (any case) and contains a `/` or a
backslash is one too, so a typo such as `../x.png`, `fixtures/x.png`, `./assets/x.png`,
`assets\x.png` or `C:/x.png` is reported rather than ignored. Every such string must be written
`assets/<name>.png` (or `.jpg`, `.jpeg`) with forward slashes and equal a manifest `path` exactly,
whichever operating system runs the validator; anything else is an `asset-path` failure. A bare
file name (`IMG_2041.JPG`), a URL in a recipe without images, and a prose sentence that mentions
`chart.png` are not paths. So a text-only recipe is unaffected by the image-suffix rule, but not by
the `assets/` prefix rule: a text-only recipe still fails if a `fields` value has no whitespace and
starts with `assets/` (`assets/equity`). In a recipe that has images, a value that
ends in an image suffix and contains a `/` or a backslash (an upload path, an attachment URL)
cannot be kept in `fields` as written; keep only the bare file name, put whitespace in the value,
or leave it out. `state` examples are not scanned,
so an image recipe puts its image paths in `fields`, or the reference and leak checks never see
them. `demo` examples are exempt from the leak rule, as they are from the label rule. An
image used only in a question's criteria is named by no `fields` value, so the leak rule cannot
see it; it still needs an entry, like every file under `assets/`. For a reference image that several splits deliberately share through `fields`, set
`"shared_across_splits": true` on every entry that carries those bytes.

What the validator does not do: decode pixels (two encodings of the same picture have different
hashes), run or read the generator beyond finding the function name, or judge whether a description
or an attestation is true. The reviewer does the last two, and the image-file contract above
(`tools/check_recipe_assets.py`) still decides what a valid file is.

To write the entries rather than type them, hash the bytes you just saved:

```python
import hashlib
from pathlib import Path

from PIL import Image


def manifest_entry(recipe_dir, path, generator, parameters, description, licence="CC0-1.0"):
    """`path` is "assets/x.png" under `recipe_dir`; the current directory does not matter."""
    file = Path(recipe_dir) / path
    data = file.read_bytes()
    with Image.open(file) as image:
        fmt, (width, height) = image.format, image.size
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": fmt,
        "width": width,
        "height": height,
        "origin": "generated",
        "generator": generator,
        "parameters": parameters,
        "licence": licence,
        "description": description,
        "attestations": {
            "synthetic": True,
            "real_photo": False,
            "real_brand": False,
            "real_person": False,
            "third_party_content": False,
        },
    }
```

At the end of `build_fixtures.py`, write `{"schema": 1, "assets": [...]}` with
`json.dumps(..., indent=2)`, entries sorted by `path` so a regenerated manifest diffs cleanly. The
manifest is then regenerated with the images and the hashes cannot drift.

### Generators

The fixtures are data written by a script, so the keys cannot drift from the questions. Keep
the questions and the function that builds a state in one module that both the generator and the
notebook import, so they cannot disagree (a mismatch only shows up as a replay miss at run
time). Put the generator in the recipe folder, next to the notebook and outside `fixtures/`
(for example `recipes/NN-slug/build_fixtures.py`), and commit it: the fixtures are then
reproducible and a reviewer can see how each response was made.

A synthetic result's model must be the string `"synthetic"` (`DecisionResult` refuses anything
else), because a synthetic answer comes from no model; so two synthetic responses files always
share that model string. Use `ChoiceAnswer.from_probabilities` and `ScoreAnswer.from_probabilities`
for the other answer types, as `NoulAnswer` is used below; the answer fields are computed from the
probabilities by the published formulas:

```python
from jev_cookbook import ChoiceAnswer, ScoreAnswer, Provenance

tone = ChoiceAnswer.from_probabilities({"calm": 0.7, "angry": 0.3}, Provenance.synthetic())
urgency = ScoreAnswer.from_probabilities(
    [0.1, 0.6, 0.3], ["low", "medium", "high"], Provenance.synthetic()
)  # probabilities by level, then the legend
```

```python
import json
from pathlib import Path

from jev_cookbook import DecisionResult, Noul, NoulAnswer, Provenance, dump_responses, replay_key

QUESTIONS = {"billing": Noul(instructions="Is this ticket about billing?")}


def build_state(fields):  # the notebook imports this same function
    return {"text": fields["text"]}


rows = [  # (id, split, fields, label, synthetic probability); t01 and v02 are answered wrongly
    ("v01", "validation", {"text": "I was charged twice."}, "billing", 0.92),
    ("v02", "validation", {"text": "How do I reset my password?"}, "other", 0.64),
    ("t01", "test", {"text": "My invoice shows the wrong amount."}, "billing", 0.45),
    ("t02", "test", {"text": "Your app crashes on start."}, "other", 0.09),
]
folder = Path("fixtures")
folder.mkdir(exist_ok=True)
inputs, labels, responses = [], [], {}
for ident, split, fields, label, p in rows:
    # a `fields` example gets its key from build_state
    key = replay_key(build_state(fields), QUESTIONS)
    inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
    labels.append({"id": ident, "label": label})
    answer = NoulAnswer(p, Provenance.synthetic())
    responses[key] = DecisionResult({"billing": answer}, "synthetic").to_dict()
(folder / "inputs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in inputs), "utf-8")
(folder / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in labels), "utf-8")
(folder / "responses.json").write_text(dump_responses(responses), encoding="utf-8", newline="\n")
```

These four answers are deliberately not all right: a fixture set where every stored answer matches
its label models nothing, so copy the pattern of imperfect answers, not a perfect set.

An example with `state` computes its key from that state directly. An example with `fields`
stores the fields and the key of `build_state(fields)`; the notebook calls the same `build_state`
before `backend.decide`. Recorded fixtures come from the live recorder, which writes the same
format; its request-id ledger lives outside `fixtures/`. A hard case is a normal example: name it
in the `id` (`v07-sarcasm`) or keep your own notes in the generator, since rows take no other
fields.

Keep fixtures small enough to read: tens of examples at levels 1 and 2 ([CONTRIBUTING.md](../CONTRIBUTING.md), section 5).

A generator that writes `responses.json` should not be able to silently replace a `recorded`
answer with a synthetic one: once a response's provenance is `recorded`, regenerating fixtures
should refuse to overwrite it without an explicit override. The scaffold's `build_fixtures.py`
(and the template's) does this by checking the existing file before writing and requiring
`--force` to overwrite a recorded one; generating `inputs.jsonl`/`labels.jsonl` stays separate
from generating `responses.json` so the first two can always be regenerated safely. See
[docs/recipe-template.md](recipe-template.md).
