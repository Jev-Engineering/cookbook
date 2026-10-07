# Getting started

From a clone to a notebook running offline, in a few minutes, with no API key. You need Python 3.10
or newer and git. This page covers install, opening a notebook, running it offline, running a
recipe's tests, and switching to live. What an offline run does and does not show is in
[offline-and-live.md](offline-and-live.md), and the words are in the [glossary](glossary.md).

## 1. Install

```bash
git clone https://github.com/Jev-Engineering/cookbook.git
cd cookbook
python -m venv .venv
# Activate it, depending on your shell:
#   Linux / macOS:        . .venv/bin/activate
#   Windows, Git Bash:    source .venv/Scripts/activate
#   Windows, PowerShell:  .venv\Scripts\Activate.ps1
#   Windows, cmd:         .venv\Scripts\activate.bat
pip install -e ".[dev]"
```

The repository is private for now, so the clone needs a GitHub account with access. On Debian or
Ubuntu you may need `python3` instead of `python`. `.[dev]` installs the package `jev_cookbook`
with the tools to run and test notebooks. It needs no network at run time and installs no TypeSafe
SDK; that is the optional `.[live]` extra in step 6. Everything below is run from the repository
root, with the environment active.

## 2. Pick a notebook

Each recipe is a folder, `recipes/NN-slug/`, with `notebook.ipynb`, a one-page `README.md`, and
`fixtures/`. The recipe numbers and their status are in the table in the
[README](../README.md#the-recipes): a row links to its notebook once the recipe is published, and
to its issue until then.

- **Recipe 01**, `recipes/01-sentiment-classification/`, is where the curriculum starts, once its
  row in the README table links to a notebook.
- **The template**, `recipes/_template/`, is a small, complete recipe that routes a support message.
  It is always there, it works the same way every recipe does, and the commands below use it. To
  use another recipe, replace `recipes/_template` with its folder.

Whichever you pick, start with the folder's `README.md`: it says what the recipe teaches, how to
run it, and what was and was not measured.

## 3. Run it offline

```bash
python -m jev_cookbook.fixtures validate recipes/_template   # the fixtures are valid
python tools/execute_notebook.py recipes/_template           # run notebook.ipynb, outputs written back
```

The first command prints `recipes/_template: fixtures valid (mode replay)` and exits 0. The second
runs the notebook top to bottom in a fresh kernel with the recipe folder as its working directory,
and writes the outputs into `notebook.ipynb`. It prints `_template: executed notebook.ipynb
offline` and exits 0. On Windows it may also print warnings of its own on stderr; judge success by
the exit status. For a committed recipe the rewritten file is identical, so
`git status` shows nothing new. The executor removes every `JEV_COOKBOOK_*` and `TYPESAFE_*`
variable from the kernel's environment, so it never runs live, even from a shell set up for live
calls ([recipe-template.md](recipe-template.md#executing-a-notebook)).

To read and step through the notebook yourself, install Jupyter, which is not a dependency of this
repository, and open the notebook from its own folder:

```bash
pip install jupyterlab
cd recipes/_template
jupyter lab notebook.ipynb
```

With no `JEV_COOKBOOK_LIVE` set, the notebook runs offline. The first output of the notebook is its
run-mode header. For a synthetic run it reads:

```text
Recipe template: Route a support message
Mode: offline replay of synthetic fixtures, pipeline check on a fixture sample of 20 examples
Metrics in this run are checks that the pipeline works. They are not Jev results.
```

That last line matters: in this mode the numbers below it check the pipeline and are not Jev
results. Read [offline-and-live.md](offline-and-live.md) for what that means and for the other three
modes.

## 4. Run a recipe's tests

```bash
pytest recipes/_template
```

This runs the recipe's own tests (11 for the template): that the rule Python enforces in
`helpers.py` holds whatever the model answers, and that the stored answers still match the current
question. `pytest` with no argument runs every test in the repository, which is what CI runs; the
other checks are in [development.md](development.md).

## 5. Make your own recipe

```bash
python tools/new_recipe.py NN                  # recipes/NN-slug/ from the catalog; NN is 1 to 60
python tools/new_recipe.py NN --mode scripted  # the same, for a scripted or simulator recipe
```

The command never overwrites a folder that exists. Every place left for you to write is marked
`TODO`. The walkthrough from scaffold to a finished recipe is in
[recipe-template.md](recipe-template.md#from-scaffold-to-a-running-notebook), and the contract it
has to meet is [CONTRIBUTING.md](../CONTRIBUTING.md).

## 6. Switch to live

Live calls send the same questions to the TypeSafe API and change nothing else. They need your own
key and are opt-in. The install line for the optional SDK is:

```bash
pip install -e ".[live]"
```

Then set three environment variables in the shell you open Jupyter from (the model has no default,
and the key goes in the environment and nowhere else):

| Variable | Value |
| --- | --- |
| `TYPESAFE_API_KEY` | your API key |
| `JEV_COOKBOOK_LIVE` | `1` |
| `JEV_COOKBOOK_LIVE_MODEL` | the model to ask, for example `jev-1.13.0` |

`JEV_COOKBOOK_LIVE_MAX_REQUESTS` (optional, default 25) caps how many requests one backend may send.
Open the notebook from its own folder, as in step 3. The header now says `Mode: live` and the model,
and any number it prints describes only the examples in that run. Never put a key in a notebook,
fixture or committed file. The budget guard, the recorder that turns live answers into fixtures, and
every error message are in [live.md](live.md) and [offline-and-live.md](offline-and-live.md#the-live-path).
Model names are listed in the TypeSafe documentation, reachable from
<https://docs.typesafe.ai/llms.txt>.
