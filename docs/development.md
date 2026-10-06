# Development

Python 3.10 or newer (the floor of `typesafe-sdk`).

## The three commands

```bash
# 1. Install (from a fresh virtual environment)
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2. Lint and format check
ruff check .
ruff format --check .

# 3. Test
pytest
```

`ruff format .` fixes formatting. Ruff also covers notebooks. `pytest` runs with
`--import-mode=importlib`, so a recipe folder can carry its own `tests/` without
module-name clashes. The README tables are generated: after a catalog change run
`python tools/render_catalog.py`, and `python tools/render_catalog.py --check` to verify.

## Dependency policy

- **Core** (`dependencies`): only what every offline notebook run needs. Currently
  `numpy`, `matplotlib`, and `nbclient`, `nbformat`, `ipykernel` for executing notebooks.
  A new core dependency needs a reason in its pull request.
- **Extras** (`optional-dependencies`): anything only some recipes or contributors need.
  - `live`: `typesafe-sdk`, for opt-in live inference (`JEV_COOKBOOK_LIVE=1`).
  - `ml`: `scikit-learn`, for recipes that train baselines.
  - `dev`: `ruff` and `pytest`.
- **No import-time side effects.** Importing `jev_cookbook` never touches the network,
  never reads an API key, and never imports `typesafe-sdk`. Code that needs the SDK
  imports it lazily, inside the live backend, and fails with a clear message when the
  `live` extra is not installed. A test enforces this for the package import.
- Recipes run offline with core dependencies only, unless the recipe README names an extra.
