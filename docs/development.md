# Development

Python 3.10 or newer (the floor of `typesafe-sdk`).

## The three commands

```bash
# 1. Install (from a fresh virtual environment)
python -m venv .venv
# Activate it, depending on your shell:
#   Linux / macOS:        . .venv/bin/activate
#   Windows, Git Bash:    source .venv/Scripts/activate
#   Windows, PowerShell:  .venv\Scripts\Activate.ps1
#   Windows, cmd:         .venv\Scripts\activate.bat
pip install -e ".[dev]"

# 2. Lint and format check
ruff check .
ruff format --check .

# 3. Test
pytest
```

`ruff format .` fixes formatting. Ruff also covers notebooks. On Debian or Ubuntu you may
need `python3` instead of `python`, and the `python3-venv` package for `python3 -m venv`.

`pytest` runs `tests/` and `recipes/` with `--import-mode=importlib`, so a recipe folder can
carry its own `tests/`, and test files with the same name in different folders do not clash.
How a recipe's tests import its `helpers.py` is defined in #68 (every recipe has a top-level
`helpers` module, so that convention must avoid name collisions).

The README tables are generated: after a catalog change run
`python tools/render_catalog.py`, and `python tools/render_catalog.py --check` to verify.

Never edit the generated regions by hand. A recipe pull request that adds
`recipes/NN-slug/notebook.ipynb` changes what the renderer produces, so the README must be
regenerated in that same pull request. The recipe builder does not do this: a designated
integration worker does, serially, after updating the branch against current `main` and
before the final review and CI run (see "The generated-README exception" in
[CONTRIBUTING.md](../CONTRIBUTING.md)). `--check` stays strict and fails on any stale
content. The planned scope check in #69 does not exist yet; when it does it must accept only
exact renderer output in the generated regions, never an arbitrary root edit.

## Continuous integration

`.github/workflows/ci.yml` (workflow `CI`) runs on every pull request and every push to
`main`. It uses no secrets and makes no live API calls. These job names are stable so they
can be made required checks; change one only deliberately, and add new jobs (for example
notebook execution) under new names.

| Check name | What it runs |
| --- | --- |
| `Lint (ruff)` | `ruff check .` and `ruff format --check .` |
| `Catalog (README is current)` | `python tools/render_catalog.py --check` |
| `Tests (py3.10)` | `pytest` on the package floor |
| `Tests (py3.14)` | `pytest` on the newest interpreter contributors use |
| `Hygiene (secrets and notebook outputs)` | `python tools/check_hygiene.py` (workflow `Hygiene`, `.github/workflows/hygiene.yml`) |

Run the lint, test and catalog commands from this document locally before opening a pull
request. Third-party actions are pinned to full commit SHAs with the version in a
comment; bump them deliberately, and keep the permissions at `contents: read`.

## Repository hygiene

`python tools/check_hygiene.py` scans every tracked file (or only the files you name) in a
few seconds, with the standard library only. Run it before pushing a notebook.

It covers, in every text file and in every notebook string (source, markdown, all text
outputs such as stream, `text/plain`, `text/html`, error values and tracebacks, and
metadata):

- private-key blocks, well-known vendor key prefixes (`sk-`, GitHub, AWS, Slack, Google),
  JWTs, `Authorization` header values, `Bearer` tokens, `name = value` assignments for
  key, token, secret and password names (including `TYPESAFE_API_KEY=...`), tracked `.env`
  files (`.env.example` is allowed), and long high-entropy tokens;
- in notebook outputs and metadata only: Windows, Linux and macOS home-directory paths,
  other absolute drive paths, WSL `/mnt/x/` paths, and `os.environ` dumps.

Placeholders such as `<API_KEY>`, `{key}`, `$KEY` and `your-key-here` are accepted, as are
the bare words `TYPESAFE_API_KEY` and `JEV_COOKBOOK_LIVE`. Findings print the file, the
cell and output location, the rule, and a masked snippet, never the whole value.

It does not cover: a TypeSafe key by prefix (the documentation shows no fixed prefix, so
only the generic rules apply), short or low-entropy secrets, encoded or line-split secrets,
image and PDF output payloads, or git history. No hex token of any length is caught by
the entropy rule (hex cannot reach its threshold), so a hex-format key is caught only by the
header, bearer and assignment rules. Notebooks of any size are parsed, ANSI colour codes in
tracebacks are stripped, UTF-16 files are decoded, and a file that cannot be scanned (an
unknown notebook layout, an undecodable or oversized non-image file) is reported as an
`unscanned-file` or `unrecognized-notebook-layout` finding, never skipped silently. Git SHAs, content hashes, URL and
file-path segments, and `data:` URIs are not treated as entropy findings. If a real credential
is ever committed, revoke it; removing it from the branch is not enough.

The fixture validator (#65) checks fixtures separately; this scan also reads fixture files
as plain text, so a key-like string in a fixture fails here too.

### Optional pre-commit

`.pre-commit-config.yaml` mirrors the CI checks (`ruff check`, `ruff format --check`, the
hygiene script, the catalog check). `pytest` runs only at push time, so commits stay fast.
It is optional:

```bash
pip install pre-commit      # in the same virtual environment as pip install -e ".[dev]"
pre-commit install --hook-type pre-commit --hook-type pre-push
pre-commit run --all-files  # run the commit checks once, now
pre-commit run --all-files --hook-stage pre-push   # include pytest
```

The hooks are local (`language: system`) and use the tools from your virtual environment,
so the pinned ruff version is the one CI uses.

Dependabot (`.github/dependabot.yml`) checks Python dependencies and GitHub Actions weekly,
with at most three of its update pull requests open at once for each.

## Dependency policy

- **Core** (`dependencies`): only what every offline notebook run needs. Currently
  `numpy`, `matplotlib`, and `nbclient`, `nbformat`, `ipykernel` for executing notebooks.
  A new core dependency needs a reason in its pull request.
- **Extras** (`optional-dependencies`): anything only some recipes or contributors need.
  - `live`: `typesafe-sdk`, for opt-in live inference (`JEV_COOKBOOK_LIVE=1`).
  - `ml`: `scikit-learn`, for recipes that train baselines.
  - `dev`: `ruff` (pinned exactly, so new rules or formatter changes cannot break `main`
    without a code change; bump it deliberately in its own pull request) and `pytest`.
- **No import-time side effects.** Importing `jev_cookbook` never touches the network,
  never reads an API key, and never imports `typesafe-sdk`. Code that needs the SDK
  imports it lazily, inside the live backend, and fails with a clear message when the
  `live` extra is not installed. A test enforces this for the package import.
- Recipes run offline with core dependencies only, unless the recipe README names an extra.
