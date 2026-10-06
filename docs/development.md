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

## Continuous integration

`.github/workflows/ci.yml` (workflow `CI`) runs on every pull request and every push to
`main`. It is offline and keyless: it uses no secrets. These job names are stable so they
can be made required checks; change one only deliberately, and add new jobs (for example
notebook execution) under new names.

| Check name | What it runs |
| --- | --- |
| `Lint (ruff)` | `ruff check .` and `ruff format --check .` |
| `Catalog (README is current)` | `python tools/render_catalog.py --check` |
| `Tests (py3.10)` | `pytest` on the package floor |
| `Tests (py3.14)` | `pytest` on the newest interpreter contributors use |

Run the same four commands locally (the three above plus the catalog check) before opening a
pull request. Third-party actions are pinned to full commit SHAs with the version in a
comment; bump them deliberately, and keep the permissions at `contents: read`.

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
