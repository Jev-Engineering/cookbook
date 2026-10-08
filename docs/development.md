# Development

Python 3.10 or newer (the floor of `typesafe-sdk`). Committable notebook outputs are the one
exception: they are produced on Python 3.14 with `.github/constraints-notebooks.txt`, because that
file cannot be installed on the floor (`numpy==2.5.3` needs Python 3.12 or newer) — see "Running CI
on one recipe".

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
integration worker does, serially, after the branch is handed over to it (one worker at a time, each
handover recorded on the pull request), updating the branch against current `main`, running the
renderer, committing only the generated README regions and confirming `--check`, before the final
review and CI run (see "The generated-README exception" in
[CONTRIBUTING.md](../CONTRIBUTING.md)). `--check` stays strict and fails on any stale
content, so on a recipe pull request that adds a notebook the `Catalog` check is expected to be
red until the integration stage has run; the builder does not fix it. The scope check
(`tools/check_recipe_scope.py`, CI check `Scope (recipe pull requests)`) enforces the allowlist
mechanically on every pull request; reviewers can run the same command locally, and the rule is
in [CONTRIBUTING.md](../CONTRIBUTING.md) and [notebook-ci.md](notebook-ci.md).

## Continuous integration

`.github/workflows/ci.yml` (workflow `CI`) runs on every pull request and every push to
`main`. It uses no secrets and makes no live API calls. These job names are stable so they
can be made required checks; change one only deliberately, and add new jobs under new names.
Notebook execution and fixture validation are in a second workflow, `Notebooks`
(`.github/workflows/notebooks.yml`), and the scope check is in a third, `Scope`
(`.github/workflows/scope.yml`, which also re-runs when a pull request description is edited).
Both are described below and in [notebook-ci.md](notebook-ci.md).

| Check name | What it runs |
| --- | --- |
| `Lint (ruff)` | `ruff check .` and `ruff format --check .` |
| `Catalog (README is current)` | `python tools/render_catalog.py --check` |
| `Tests (py3.10)` | `pytest` on the package floor |
| `Tests (py3.14)` | `pytest` on the newest interpreter contributors use |
| `Hygiene (secrets and notebook outputs)` | `python tools/check_hygiene.py` (workflow `Hygiene`, `.github/workflows/hygiene.yml`) |

The two test jobs differ on purpose: `Tests (py3.14)` installs `.[dev,live]` so the SDK-backed
tests in `tests/test_live_sdk.py` run, while `Tests (py3.10)` installs `.[dev]` only and proves
the package and every offline test work with the SDK absent (that one module is skipped).

Run the lint, test and hygiene commands from this document locally before opening a pull
request. Third-party actions are pinned to full commit SHAs with the version in a
comment; bump them deliberately, and keep the permissions at `contents: read`.

### Notebook checks (workflow `Notebooks`)

| Check name | What it runs |
| --- | --- |
| `Notebooks (execute)` | The one stable name to require: green when every selected notebook passed. |
| `Notebook (<recipe>)` | One job per recipe folder: installs `.[ml]` under the CI constraints, executes `notebook.ipynb` offline in a scratch copy with no key and no network (a network namespace with `no_new_privs`), `check_notebook_fresh.py` against the committed file, `check_hygiene.py` on the fresh copy. |
| `Notebooks (discover)` | Chooses the recipes to run (a push to `main` runs the folders changed since the previous tip and a pull request runs the folders it changes, either of them all when anything but `recipes/<folder>/` and `README.md` changed). |
| `Fixtures (validate)` | `python tools/notebook_ci.py fixtures`: every folder under `recipes/` has `fixtures/` and validates. |
| `Scope (recipe pull requests)` | `tools/check_recipe_scope.py` (workflow `Scope`, `pull_request_target`, so the base branch's copy judges), on pull requests only, and again when the description or base is edited. |

### Running CI on one recipe

To run what the notebook job runs on one recipe, from the repository root (Git Bash on Windows,
or Linux). CI copies to a folder that keeps the recipe's name, so do the same:

```bash
pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt   # CI's install (Python 3.14)
mkdir -p /tmp/run && cp -R recipes/NN-slug /tmp/run/NN-slug
PYTHONPATH="$PWD/tools/netguard" python tools/execute_notebook.py /tmp/run/NN-slug
test -z "$(git status --porcelain)" || { echo "the run wrote into the checkout"; git status --porcelain; exit 1; }
python tools/check_notebook_fresh.py recipes/NN-slug/notebook.ipynb /tmp/run/NN-slug/notebook.ipynb
python tools/check_hygiene.py /tmp/run/NN-slug/notebook.ipynb
python tools/notebook_ci.py fixtures
```

The constraints pin the plotting stack and the kernel stack to the versions CI uses (see
[notebook-ci.md](notebook-ci.md#pinned-plotting-stack)). **Committable outputs require Python 3.14
with the constraints file**, not just the same `pip install`: text output is compared byte for byte
against CI's pinned stack, and the floor, Python 3.10, cannot even install the file (`numpy==2.5.3`
needs Python 3.12 or newer). This is not permission to skip the pins on a newer interpreter either;
only figures tolerate a different version (they are compared by what they show, not by bytes).
Install with the same file before you execute a notebook whose outputs you will commit.

**This is the weaker, no-`sudo` variant, and it is honest about why.** The kernel above runs as
your own user, who already owns the checkout that `tools/check_notebook_fresh.py`,
`tools/check_hygiene.py` and the committed notebook are read from — there is no boundary here
stopping a cell from writing any of them, only the `test -z "$(git status --porcelain)"` line
catching it afterwards (a real backstop: it does fail if a cell wrote into the checkout, the same
way CI's own backstop would). CI does not rely on a backstop alone; it runs the kernel as a
separate, unprivileged user who cannot write the checkout, the interpreter's site-packages or the
runner's `$HOME` at all — see "Protecting the checks from the notebook under test" in
[notebook-ci.md](notebook-ci.md). To reproduce that boundary locally rather than only its
backstop, on Linux, with `sudo` and a spare system user:

```bash
sudo useradd -M -s /usr/sbin/nologin nbrunner_local   # once; pick a name that cannot collide
sudo mkdir -p /tmp/nbrunner-home
sudo chown nbrunner_local:nbrunner_local /tmp/nbrunner-home

mkdir -p /tmp/run && cp -R recipes/NN-slug /tmp/run/NN-slug
sudo chown -R nbrunner_local:nbrunner_local /tmp/run/NN-slug
sudo chmod -R u+rwX,go-rwx /tmp/run/NN-slug   # nbrunner_local's only writable location

sudo env "PATH=$PATH" "HOME=/tmp/nbrunner-home" "PYTHONPATH=$PWD/tools/netguard" \
  "PYTHONNOUSERSITE=1" setpriv --no-new-privs --reuid=nbrunner_local --regid=nbrunner_local \
  --clear-groups -- python -s tools/execute_notebook.py /tmp/run/NN-slug

# A cell could have started a process that outlives the kernel (setsid, a double fork, & disown);
# end every nbrunner_local process before trusting anything it could still touch.
sudo pkill -9 -u nbrunner_local || true
sleep 1
sudo pgrep -u nbrunner_local && { echo "a detached process survived pkill"; exit 1; }

sudo install -m 0644 -o "$(id -u)" -g "$(id -g)" /tmp/run/NN-slug/notebook.ipynb /tmp/fresh.ipynb

test -z "$(git status --porcelain)" || { echo "the run wrote into the checkout"; exit 1; }
git show HEAD:recipes/NN-slug/notebook.ipynb > /tmp/committed.ipynb
python tools/check_notebook_fresh.py /tmp/committed.ipynb /tmp/fresh.ipynb
python tools/check_hygiene.py /tmp/fresh.ipynb
python tools/notebook_ci.py fixtures

sudo userdel nbrunner_local   # tidy up afterwards; the home and scratch directories are in /tmp
```

This reproduces the uid boundary around the checkout, site-packages and `$HOME`, and the
leftover-process kill; it does not also reproduce CI's network namespace (`unshare --net`), which
needs root for the whole duration rather than one dropped-privilege command and is demonstrated
separately below.

`PYTHONPATH="$PWD/tools/netguard"` loads the Python-level network guard, as in CI. The path must be
absolute: the executor starts the kernel with the recipe folder as its working directory, so a
relative `PYTHONPATH` resolves against `/tmp/run/NN-slug`, finds nothing, and the notebook runs
unguarded without a word. To see that the guard reached the kernel, run a probe cell (a cell that
prints `socket.socket.connect.__module__` must print `sitecustomize`, and one that calls
`socket.create_connection(("example.com", 80))` must raise `NetworkBlocked`). The guard is a
readable error for an honest mistake, not a sandbox. On Linux the enforcing layer can be tried the
way CI does it. The values that must belong to you (`id -u`, `id -g`, `PATH`) are expanded by your
shell, outside the quotes, and passed in as arguments; inside the single-quoted script they would
expand as root:

```bash
sudo env "PATH=$PATH" unshare --net -- sh -c \
  'ip link set lo up && exec setpriv --no-new-privs --reuid="$1" --regid="$2" --clear-groups -- \
   python -c "import socket; socket.create_connection((\"1.1.1.1\", 53), timeout=5)"' \
  sh "$(id -u)" "$(id -g)"
```

which must fail with an `OSError` (`Network is unreachable`), as your user and with your `python`
(add `import os; print(os.getuid())` to the payload to check). `sudo -n true` run from inside it
must fail too. To check a pull
request description and diff against the allowlist, put the description in a file:

```bash
printf 'Closes #NN\n' > /tmp/pr-body.txt
python tools/check_recipe_scope.py --base origin/main --head HEAD \
    --branch recipe/NN-slug --body-file /tmp/pr-body.txt
```

A fresh scaffold has no `fixtures/` folder until you run `python recipes/NN-slug/build_fixtures.py`,
and `Fixtures (validate)` fails a recipe folder without one.

To refresh a stale notebook, run `python tools/execute_notebook.py recipes/NN-slug` and commit
the result. Everything about these checks, including how the figure comparison works and what
it cannot see, is in [notebook-ci.md](notebook-ci.md).

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
- in notebook outputs and metadata only (source cells, Markdown and plain text files may
  mention paths): Windows, Linux and macOS home-directory paths, absolute drive paths with
  either slash (`C:\x`, `D:/work/x`), WSL `/mnt/x/` paths, username-bearing temp paths
  (`/tmp/pytest-of-<user>/`), machine-local roots (`/opt/conda*`, `/opt/mambaforge`, `/opt/homebrew`,
  `/private/var/folders/`, `/Volumes/`), `os.environ` dumps, and the name of the account
  running the check (see below).

Placeholders such as `<API_KEY>`, `{key}`, `$KEY` and `your-key-here` are accepted, as are
the bare words `TYPESAFE_API_KEY` and `JEV_COOKBOOK_LIVE`. Findings print the file, the
cell and output location, the rule, and a masked snippet, never the whole value.

Usernames: a bare username cannot be told from an ordinary word, so names are not treated as
secrets in general. A name is caught when it sits in one of the path rules above and, as a
best effort, when it is the account that runs the check (`USER`, `USERNAME`, `LOGNAME` or the
OS account) as a whole word in an output or metadata. That is reported as `local-username`
without echoing the name. It helps local and pre-commit runs and leaves CI (account
`runner`) unaffected. Account names shorter than 4 characters, generic ones (`root`,
`runner`, `admin`, `ubuntu`, `vscode`, ...) and a short list of ordinary words that are also
account names (`hello`, `will`, `mark`, `page`, `grant`, `data`, `test`, ...) are not checked
by name, because that would reject plain prose. The list is not exhaustive: if your account
name is another common word, expect a local `local-username` finding on any output that
contains it. Reword that output (the finding gives its cell and line); CI never runs this
rule, and the path rules still catch the name inside a path. Other people's bare
names, system library paths (`/usr/lib/python3...`), UNC paths other than WSL, and a lone
one-letter `x:/` that is not a drive are not told apart from prose and are out of scope.

Notebook structure: a cell, worksheet or `cells` value that nbformat does not allow (for
example a bare string where a cell object belongs, or a `source` that is not text) is a
`malformed-notebook-node` finding with its location and the Python type. Its strings are
still scanned for secrets, so the output stays masked and short. This covers a cell's `id`
(1-64 letters, digits, `-`, `_`), `cell_type` (code, markdown, raw, heading),
`execution_count` and `prompt_number` (integer or null). Only a known cell type is ever
printed in a location. Both `cells` and nbformat 3 `worksheets` are read when both are
present, including each worksheet's other keys such as `metadata`.

Dictionary keys are scanned like values (`<key name>` in the location), so a secret used as a
JSON key is a finding. A key is printed in a finding location only when it is short and
ordinary (such as `text/plain`) and trips no rule that applies there (secret, local path,
account name); any other key is shown as `<key>`, so a finding never echoes a secret, path or
account name that sits in a key. A cell that has both `source` and `input` has both scanned.

Arguments: name files, or give none to scan every tracked file. A directory, or a path that
does not exist, is rejected with exit status 2 and a message. It is never counted as scanned
and never scanned implicitly; expand a directory yourself (`git ls-files dir`) if you need it.

It does not cover: a TypeSafe key by prefix (the documentation shows no fixed prefix, so
only the generic rules apply), short or low-entropy secrets, encoded or line-split secrets,
image and PDF output payloads, or git history. No hex token of any length is caught by
the entropy rule (hex cannot reach its threshold), so a hex-format key is caught only by the
header, bearer and assignment rules. Notebooks of any size are parsed, ANSI colour codes in
tracebacks are stripped, UTF-16 files are decoded, and a file that cannot be scanned (an
unknown notebook layout, an undecodable or oversized non-image file) is reported as an
`unscanned-file` or `unrecognized-notebook-layout` finding, never skipped silently. Git SHAs, content hashes, URL and
file-path segments, `data:` URIs, and a bare `name=VALUE` assignment (both sides runs of letters of one case or of digits joined by `_`, the value also by `.`, no quotes, and a name that does not contain api key, secret, token, password, access key or credential), such as the keyword argument `startup_timeout=KERNEL_START_TIMEOUT`, are not treated as entropy findings. If a real credential
is ever committed, revoke it; removing it from the branch is not enough.

The fixture validator (#65) checks fixtures separately; this scan also reads fixture files
as plain text, so a key-like string in a fixture fails here too. The validator carries a copy
of the secret rules only (`src/jev_cookbook/fixtures/_scan.py`), not the notebook-output path,
account-name and notebook-layout rules, which have no meaning in fixture text. A test in
`tests/test_fixtures.py` compares the copied rule definitions and functions with
`tools/check_hygiene.py`, so changing a secret rule there without the copy fails the tests.

### Optional pre-commit

`.pre-commit-config.yaml` mirrors the CI checks (`ruff check`, `ruff format --check`, the
hygiene script, the catalog check). `pytest` runs only at push time, so commits stay fast.
`ruff format --check` also covers Python code blocks in `*.md` files, as in CI. `ruff check`
does not lint Markdown, so that hook is unchanged, and `.markdown` and `.mdx` files are left
out because `ruff format .` ignores them. It is optional:

```bash
pip install pre-commit      # in the same virtual environment as pip install -e ".[dev]"
pre-commit install --hook-type pre-commit --hook-type pre-push
pre-commit run --all-files  # run the commit checks once, now
pre-commit run --all-files --hook-stage pre-push   # include pytest
```

The hooks are local (`language: system`) and use the tools from your virtual environment,
so the pinned ruff version is the one CI uses. Run `pre-commit` with the project virtual
environment activated so the pinned `ruff==0.16.10` is first on `PATH`: a stale global ruff (0.14.0 was
seen) reports `Failed to parse <file>.md` on Markdown files and, when run on `.`, silently skips
Markdown altogether, which gives a false pass. CI is unaffected because it installs the pinned ruff.

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
- Recipes run offline with the core dependencies and the `ml` extra. CI installs `.[ml]` in the
  notebook job (before the network is cut), with the plotting stack pinned by
  `.github/constraints-notebooks.txt`; the `live` extra is never installed there. A recipe that
  needs any other extra needs the workflow's install line changed first (a foundation change; a
  recipe pull request cannot touch `.github/`). Bumping the constraints is a foundation change
  that re-executes every notebook ([notebook-ci.md](notebook-ci.md#pinned-plotting-stack)).
