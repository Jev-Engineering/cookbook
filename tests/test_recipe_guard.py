"""The parametrised recipe guard (#165): one check function per rule, one test case per
published recipe per rule, so a contract rule that used to live only in a reviewer's head is
enforced by CI on every recipe at once, not re-derived by hand on every pull request.

Source of the rules: the Wave 2 consistency review (issue #76 comment 6079429778, "Route #165")
and the PR #186 review's additions (issue #165 comments 6079443958 and 6082395702). Both are
read-only reviews; nothing here loosens, skips, or re-derives a rule differently from what they
specify. ``CONTRIBUTING.md``, ``docs/recipe-template.md``, ``docs/notebook-style.md`` and
``docs/glossary.md`` as they stand on current ``main`` (post PR #186) are the contract text this
module checks against.

Running this module the day it lands finds real, pre-existing drift in recipes merged before the
guard existed -- that is exactly the #163 sweep's work list, not something to fix by weakening a
check here. ``tests/recipe_guard_known_failures.py`` is the one place that drift is recorded, as
a ``(slug, check_id)`` allowlist that marks the pair ``xfail(strict=True)``: CI stays green today,
and a sweep pull request that actually fixes a recipe turns its xfail into an unexpected pass,
which ``strict=True`` turns back into a hard failure until the entry is removed. See that file's
own docstring for the allowlist protocol (a recipe pull request may never add an entry; only a
sweep against the entry's own named issue removes one -- #163 for most entries here, a
different issue's own number for a later check's own newly-revealed drift) and
``docs/notebook-ci.md`` ("The recipe guard allowlist") for the condensed version aimed at a
builder reading CI output.

Check ids, the rule each enforces, and how it is detected (also the per-check docstring below):

====================================  =====================================================
check id                              rule -> detection
====================================  =====================================================
``fixture_arithmetic``               Every recipes/*/build_fixtures.py (including unpublished
                                       recipes and _template): AST sum calls need recognized
                                       integer syntax or direct round(expr, literal 0..10).
                                       Literal-arithmetic float evidence in **/builtin pow
                                       requires repeated multiplication. Strings are ignored.
                                       Not whole-program numeric inference: see the helper
                                       docstrings and docs/fixtures.md for exact limits.
``build_fixtures_scaffold``           G1(a): ``tests/test_build_fixtures.py`` matches
                                       ``tools/new_recipe.py::build_fixtures_test_text`` for
                                       this recipe, byte for byte: the ``replay-images``
                                       variant when ``assets/`` is a directory, otherwise
                                       the ``replay`` variant.
``no_issue_citations``                G1(b), CONTRIBUTING.md section 6: no ``#NNN`` or
                                       "the issue" in a recipe file's prose (docstrings and
                                       comments in ``.py`` files, full text of ``README.md``
                                       and notebook markdown cells), and none of the other
                                       spellings of a document a reader cannot open (#225):
                                       a pull request's description,
                                       body or text, a bare ``PR`` (not "PR curve", "PR AUC"
                                       or "recall (PR)", the metric), a wave or batch number,
                                       a house rule number ("rule 12", unless it is followed
                                       by of/in/from and a path from the repository root that
                                       is git-tracked and regular, outside orchestration/;
                                       rendered links resolve from the source file), "the
                                       orchestrator", "the brief", "the
                                       reviewer's finding", a review finding label ``(M3)``,
                                       "acceptance criteria" (not "acceptance test", ordinary
                                       vocabulary), a review or fix round, and a recipe
                                       number (each in a list) or a sibling/repository-relative
                                       recipe link that is not published. Small ordinary-English
                                       exceptions are paired with process-pointer regressions.
                                       Quoted fixture text is stripped as before. Not seen:
                                       any other way to cite a document outside the tree.
``no_cell_id_citations``              CONTRIBUTING.md section 6 (#250): no backticked span
                                       in a markdown cell or ``README.md`` that is exactly a
                                       hyphenated cell id of that recipe's notebook (a cell id
                                       is in the ``.ipynb`` JSON only). Not seen: a single-word
                                       id (``state``, ``setup``), which is English and cannot be
                                       told from prose; an id that is not backticked; a
                                       code cell's comments and a test's lookup of a cell by
                                       id, which are machinery, not prose to a reader.
``glossary_first_use_links``           #211, CONTRIBUTING.md section 6 and docs/recipe-template.md
                                       "The lexicon": the first use of each lexicon term in a
                                       recipe's prose (business threshold, confidence gate,
                                       review, gold label, coverage, risk, selective
                                       prediction, accuracy, precision, recall, F1, support) is
                                       the relative Markdown link ``../../docs/glossary.md#anchor``
                                       to an anchor ``docs/glossary.md`` defines. First use is the
                                       first markdown cell in notebook order that uses the term,
                                       per notebook, with ``README.md`` checked on its own; later
                                       uses may be bare. Fails on a bare first use (including a
                                       code span with a bare path beside it), a link to another
                                       target or anchor, and a link that only comes after the
                                       first use. Prose is paragraphs, list items and table
                                       cells: headings, code, HTML and double-quoted fixture text
                                       are skipped, a code span counts only when it is exactly
                                       the term, and a few everyday senses (a customer review,
                                       some risk of, test coverage, support outside a sentence
                                       naming precision, recall or F1) are skipped by name. Not
                                       seen: whether the sentence defines the term, any other
                                       everyday sense, an inflection other than the plural of
                                       gold label, business threshold and confidence gate, and a
                                       use in a code cell's prose. Drift is recorded in
                                       ``tests/recipe_guard_known_failures.py``.
``stored_answers_strong_form``        G1(c): ``test_stored_answers_are_not_all_right``
                                       re-derives the frozen threshold (preferring the
                                       confidence gate over a plain business threshold when
                                       a recipe has both), written out or through a function
                                       of the recipe's own ``helpers.py`` that reaches the
                                       shared selection function (#222), and binds an
                                       ``assert`` to a wrong-answer-at-or-above-it comparison,
                                       not merely "some wrong answer somewhere".
``validation_lines_carry_selection_and_check``
                                       G1(d) clause 1, CONTRIBUTING.md section 2: a printed
                                       validation metric line carries both ``{selection}``
                                       and ``{check}``. A validation metric line is a
                                       ``print(`` that prints a rounded float (``{x:.4f}``,
                                       or aligned, ``{x:>13.4f}``, #270) and says
                                       "validation"; the float may be formatted in a string
                                       the call interpolates (traced through simple
                                       bindings, #234) and the labels may sit in that
                                       string. Not seen: a float rounded by ``round()``/
                                       ``%``/the builtin ``format()``, a line that never says
                                       "validation" in its own text or in a string literal of
                                       the float string it prints (the word reaching it through
                                       a loop variable -- 26 committed lines in 12 cells of 8
                                       recipes, 25 labelled by their loop's own tuple and one
                                       not, recipe 39's ``evaluation-t86``, #363 -- or a name
                                       bound to ``"validation"``), a number
                                       that is a validation figure only by its variable name,
                                       a float hoisted by anything but a simple binding, a
                                       nested precision, and a printer that is not literally
                                       ``print(``. A suffix built by concatenation fails on
                                       purpose.
``metric_lines_carry_check``          G1(d) clause 2: every printed metric line (a
                                       coverage/accuracy/risk/precision/recall/F1/nDCG
                                       keyword with a rounded-float format) carries at
                                       least ``{check}``, traced through simple bindings.
                                       NOT the honesty rule: it covers one formatting
                                       convention (a ``print(`` that spells ``{x:.Nf}``,
                                       aligned or not (#270), beside one of those seven
                                       words) and nothing else. Outside it: a hoisted
                                       format string (#234; the validation check above
                                       follows one, this does not -- in a synthetic or
                                       scripted run the committed-output check below
                                       reads it), a helper, or
                                       ``round()``; a metric whose line names none of the
                                       seven words; every sentence of prose in a markdown
                                       cell or a README; and every claim about quality,
                                       latency or cost that is not a printed metric line.
                                       Its existence is not evidence that section 2 is
                                       enforced; the five checks at the end of this table
                                       (``reported_provenance_matches_fixtures`` ...) are
                                       what #218 added, and
                                       docs/offline-and-live.md lists what none of them reach.
``figure_titles_check_only``          docs/notebook-style.md "Title convention": a
                                       ``plot_confusion_matrix``/``plot_threshold_sweep``/
                                       ``plot_risk_coverage`` title carries ``{check}`` and
                                       not ``{selection}``.
``print_what_you_plot``               G1(e), docs/notebook-style.md "Print what you plot":
                                       every ``plot_confusion_matrix``/``plot_threshold_sweep``/
                                       ``plot_risk_coverage`` call has, in the same code
                                       cell, a ``print`` of the plotted object itself or of
                                       something a loop over it prints.
``plot_cells_have_images``            #232, docs/notebook-style.md "Print what you plot":
                                       every code cell that calls a ``plot_*`` function has at
                                       least one non-empty ``image/*`` output committed in that
                                       same cell, so a figure cannot vanish (a ``print`` after
                                       the plot call, a lost output) while every other check
                                       stays green. Per cell, not per notebook (the notebook-
                                       level ``test_recipe_figure_presence.py`` guard of #256
                                       would pass a cell that lost its figure while another
                                       holds one). No exemption list: a published recipe that
                                       fails is a real gap. Not seen (#655): a figure that is
                                       committed but no longer produced by a fresh run (the
                                       freshness tool's job: it fails on a drop in image
                                       outputs); a plot call in a markdown cell or a string;
                                       a figure that is not made by a ``plot_*`` call: a
                                       matplotlib ``Figure`` built directly (recipe 77's
                                       ``evaluation-chart``) or a helper image shown with
                                       ``display()`` (recipes 69 and 77), which only the
                                       notebook-level ``test_recipe_figure_presence.py``
                                       sees; a ``plot_*`` function reached through an import
                                       alias (``as prc``), an assigned alias, ``getattr`` or
                                       ``functools.partial``; and a wrapper defined in one
                                       cell and called from another (the defining cell is
                                       selected, the calling cell is not). None of the alias,
                                       ``getattr``, ``partial`` or cross-cell wrapper spellings
                                       occurs in a published recipe (the direct ``Figure`` and
                                       ``display()`` cases do). All are listed, not detected,
                                       because a static name rule that chased them would risk
                                       false positives.
``next_steps_links_exist``            G1(f) clause 1, docs/recipe-template.md: every
                                       ``../NN-slug/`` link in the notebook resolves to a
                                       published recipe.
``next_steps_inbound_links``          G1(f) clause 2: every published recipe is the target
                                       of at least one other published recipe's Next steps.
``review_value_is_review``            docs/glossary.md#review: ``helpers.REVIEW == "review"``
                                       where it exists; traced through the confidence-gated
                                       reason string where it does not, less one named
                                       domain exemption (recipe 16's ``ESCALATE``).
``review_reason_string``              docs/glossary.md#review: where ``helpers.py`` produces
                                       the confidence-gated review's reason in executable
                                       code, it is exactly ``"confidence below the
                                       threshold"`` on a branch a confidence comparison
                                       controls (#227), that branch is reachable from the
                                       notebook, and a committed output shows a review the
                                       rule produced. Not a comment, an unused constant or a
                                       ``print`` of the words (in the cell, or bound to a name
                                       in any cell). A recipe with no gate fails unless it is
                                       a named gate-free design (``GATE_FREE_DESIGNS``), which
                                       is not applicable; the eight published recipes that
                                       show no such review are skipped with a recorded reason
                                       (``REASON_NOT_IN_COMMITTED_OUTPUT``, #342).
``confidence_gate_from_shared_helper``
                                       #282: a recipe whose executable code gates on
                                       confidence freezes the gate through a used call to
                                       ``select_confidence_threshold`` imported from
                                       ``jev_cookbook.evaluation``, in the notebook or a
                                       ``helpers.py`` wrapper; a constant, a look-alike, a
                                       module-attribute call or an unread result fails. A
                                       recipe that gates on nothing passes (an argument
                                       range check is not a gate), and a named gate-free design
                                       is not applicable, as for the check above. This is what
                                       makes the "no resolvable call" skips of the checks
                                       above mean "no gate".
``readme_sources_match_catalog``      tests/test_recipe_sources.py's own rule, reused here
                                       so the guard reports it as one of these checks too.
``readme_budget_note_matches_request_audit``
                                       CONTRIBUTING.md section 2 / docs/live.md (#213): the live
                                       request count is declared once (``request_budget.json``),
                                       equals the audited execution of every backend, repeats no
                                       request undeclared, and the README holds the paragraph
                                       rendered from it; strict ``len(responses.json)`` legacy
                                       fallback for a recipe with none of the three.
``one_backend_per_budget``            #213: no more ``get_backend`` call sites in the notebook
                                       and ``helpers.py`` than audited backends (an unaudited
                                       recipe: one); the request budget belongs
                                       to one backend object, so a second site is a second
                                       budget no README cap or count audit sees.
``readme_no_dev_ml_install``          docs/recipe-template.md step 6: reproducing committed
                                       outputs installs ``.[ml]``, never ``.[dev,ml]`` (a paragraph
                                       about reproducing outputs; the tests' install line may say
                                       ``.[dev,ml]``, #238).
``measured_cell_prints_n_offline``    CONTRIBUTING.md section 2 (#215): the "measured" cell's
                                       offline branch prints N, not only its live/recorded
                                       branch.
``threshold_objective_pin``           for every real ``select_confidence_threshold(``/
                                       ``select_threshold(`` call in the committed notebook or
                                       ``helpers.py``, the objective it actually selects is
                                       PINNED by some assertion in that recipe's tests, traced
                                       by data flow back to the real committed call or a real
                                       production call (not merely co-located with a string
                                       naming the spelling) -- not a hand-written literal beside
                                       the call, and not the resulting threshold value alone.
                                       What an assertion pins is its derived CLAIM (#276): the
                                       truth sense is carried through ``not``, ``and``/``or``,
                                       ``is False``, ``if``-expressions, count thresholds and
                                       ``all``/``any``/``len`` over comprehensions, and only a
                                       claim that the spelling is PRESENT counts; an assert that
                                       does not always run (under ``if``, a loop,
                                       ``pytest.raises``, or in a test pytest would not collect
                                       or run) counts for nothing. A value is tainted by any
                                       read of the committed file (``read_text``,
                                       ``read_bytes``, ``open(...).read()``, ``with open``) or
                                       by ``inspect.getsource(helpers.<fn>)``; a write-mode
                                       ``open``, a ``tmp_path``/``tempfile``/``shutil`` copy,
                                       another recipe's folder and a case-rewritten value (#320)
                                       do not taint, and only ``test_*.py``/``*_test.py`` are
                                       collected. Accepted limits: docs/recipe-template.md.
``noul_proposition_gold_coverage``    #283: for every ``Noul`` proposition this check can
                                       reach in the recipe's own code (two or more -- a
                                       battery; fewer reached and the check does not apply),
                                       ``labels.jsonl`` carries at least one gold-true AND one
                                       gold-false row for that proposition in EVERY scored
                                       split. Propositions are reached by calling the recipe's
                                       own zero-argument functions and keeping the
                                       ``Noul``-valued entries of whatever dict each returns
                                       -- never by name or spelling. A builder that requires
                                       an argument is NOT reached (recipe 39; see below), and
                                       the skip says so rather than claiming the recipe builds
                                       fewer than two.
``reported_provenance_matches_fixtures``
                                       #218, CONTRIBUTING.md section 2: the mode the
                                       committed output reports (the ``Mode:`` header, every
                                       ``Provenance:`` line, the measured cell's offline
                                       disclosure, ``Captured:``) is the provenance the stored
                                       answers carry (``responses.json -> answers -> name ->
                                       provenance.source``), and fails closed on a header, a
                                       provenance line or a fixture it cannot read. Not a
                                       vocabulary check: see "Honesty checks" below.
``readme_states_fixture_provenance``  #218: the README's ``**Mode:**`` line names the mode the
                                       fixtures carry, a recipe with no live run says "not
                                       measured live", and a recorded recipe names its model and
                                       capture dates.
``metric_output_lines_carry_pipeline_check``
                                       #218: in a synthetic or scripted run (read from the
                                       fixtures), every committed output line that names a
                                       metric word and prints a decimal or a percentage
                                       carries ``(a pipeline check, not a Jev result)`` on the
                                       same line. Keyed on the printed line, so precision,
                                       alignment and hoisting do not matter.
``prose_quantities_are_printed``      #218: a percentage or decimal quoted next to a metric
                                       word, a price, a latency or a throughput in the README
                                       or a markdown cell is a number the committed output
                                       printed (or the recipe's own tests type), at the quote's
                                       precision, as a percentage or a fraction. A table
                                       row is read cell by cell under its row label (#691).
``no_unhedged_quality_claim_about_jev``
                                       #218 item 1, the narrow form: in a synthetic or
                                       scripted recipe, no README or markdown sentence says Jev
                                       or the model does something correctly/reliably/well ...
                                       or is accurate/fast/cheap ..., or outperforms something,
                                       unless the same sentence, heading, list item or
                                       table row negates, hedges or attributes it.
``synthetic_output_prints_no_token_count``
                                       #312: in a synthetic or scripted run (read from the
                                       fixtures), no committed output line prints a number
                                       as a token count, in any cell: nothing offline measures
                                       tokens, and characters or bytes are not tokens.
``simulated_side_effect_invoked``     #212: the notebook's live code (parsed with ``ast``: no
                                       comment, string, uncalled function, lambda or dead
                                       branch) calls the recipe's simulated side effect, as
                                       many call sites of each key as the recipe declares in
                                       ``side_effects.json`` (or ``SIDE_EFFECT_INVENTORY``
                                       for the first 50 recipes); fails closed when it
                                       detects a side effect with no declaration. See the
                                       section header of that check for the rule and limits.
``fixed_order_choice_position_statistic``
                                       #208: a recipe whose code never calls or imports
                                       ``stable_permutation`` / ``stable_shuffle`` (parsed with
                                       ``ast`` in its notebook code and ``*.py`` files; a
                                       comment, docstring or string does not count) prints no
                                       first-option-lean or gold-position statistic: no
                                       code-cell name, keyword or literal, and no stored text
                                       output, for one. One real use exempts the WHOLE recipe,
                                       even if it also lists another Choice in a fixed order.
                                       Not seen: markdown; other names, wording or constructs; a
                                       statistic computed inside a helper; a string dict key; an
                                       unparseable cell (``%magic``); text/html-only output.
                                       Read as "gold position": printed text with ``-``,
                                       ``_`` or repeated spaces between the words, with or
                                       without "match" ("gold-match position"), and the phrase
                                       "position of the gold" (not "gold standard", "goldfish"
                                       or "golden"); the names ``gold_pos...`` and
                                       ``gold_match_pos...``.
====================================  =====================================================

Scope decisions (see the pull request body for the full reasoning):

* ``guarded()`` parametrises every catalog recipe with a committed notebook, plus
  ``recipes/_template``. ``fixture_arithmetic`` is the exception: it checks every builder,
  including unpublished recipes and the template, without an allowlist or ``guarded()``.
  Each published case retains its registered strict expected failure
  where applicable. The template case always runs without an expected failure. A check whose
  scope is published recipes only declares its reason with ``skip_template`` at registration.
  The template's declaration, ledger and README paragraph are compared on the audited route
  (#381). The side-effect check reads the template's notebook and any declaration before deciding
  whether there is a simulated write to report (#512).
* ``next_steps_inbound_links`` is still a per-recipe, per-check case (the fix round that added it
  found the distinction drawn in an earlier revision of this docstring -- that inbound coverage is
  "a property of the whole set, not of one recipe" -- did not actually hold: the check below reads
  every *other* recipe's notebook the same way ``next_steps_links_exist`` reads every neighbour's
  folder, and ``readme_sources_match_catalog`` already reads the catalog, so there was no real
  distinction between what a per-recipe check can and cannot look at).
* ``next_steps_inbound_links`` is nonetheless the one check in this module marked
  ``@pytest.mark.catalog_audit`` and deselected from the default run (#203, issue #76 comment
  6079429778's "Route #165"). The distinction that matters here is not what the check can read
  but when it can possibly pass: a recipe pull request may change only its own folder (``Scope``),
  and no recipe on ``main`` may link forward to a recipe that is not yet published
  (``next_steps_links_exist`` forbids it), so a new recipe's own PR can never add the backlink
  this check needs and can never satisfy it -- not a drift to record in
  ``tests/recipe_guard_known_failures.py``, but a check that is structurally unpassable within
  the scope of the PR that would trip it. It runs instead as a wave close-out audit, by hand,
  after the close-out sweep has added the missing backlinks: ``pytest -m catalog_audit
  tests/test_recipe_guard.py`` (see ``docs/development.md``, "Continuous integration"). Per-PR
  CI (bare ``pytest``, which reads ``pyproject.toml``'s ``addopts``) never selects it. A
  consequence for ``tests/recipe_guard_known_failures.py``: an allowlist entry keyed on
  ``next_steps_inbound_links`` is now exercised only at close-out, not in per-PR CI, so that one
  check's entries (there are none today) can only go stale between close-outs, not between
  pull requests -- see that file's own docstring for the allowlist protocol, which this
  narrows by exactly one check.
* A scripted recipe (``fixtures/responses.json`` does not exist; answers are computed by a
  seeded script in ``helpers.py`` rather than replayed from a stored file -- recipe 36 is the
  first and, as of this writing, only published one) is skipped by three of the checks above,
  for three DIFFERENT reasons (#249). Two early revisions of this module keyed all three skips
  on the same proxy -- "does ``responses.json`` exist" -- which is a correlate of "are this
  recipe's answers stored" and not of what each check actually means; PR #246's review verified
  each skip by hand and found that proxy wrong for one of the three. So each skip below is now
  keyed on the property its own check is about, and the three no longer share one skip
  condition:

  - ``build_fixtures_scaffold`` (G1(a)) is about ``tools/new_recipe.py``'s ``replay`` and
    ``replay-images`` scaffolds for ``tests/test_build_fixtures.py``: ``assets/`` being a
    directory selects ``replay-images``, otherwise ``replay``. A scripted recipe has no such
    file by construction (``tools/new_recipe.py::build_scripted_fixtures_text`` writes a different
    docstring and never writes ``responses.json`` at all) -- there is nothing for a scripted
    recipe to hold byte-identical, so the skip here is genuinely vacuous and stays keyed on
    ``responses.json``'s absence, which **is** the property for this one check alone.
  - ``stored_answers_strong_form`` (G1(c)) is about whether a recipe re-derives a frozen
    confidence or business threshold independently -- a property of whether the recipe
    *freezes a threshold*, which has nothing to do with whether its answers are stored or
    computed. Keying this skip on ``responses.json`` was the defect #249 found: recipe 36 has
    no stored responses and freezes a confidence gate, so the check was applicable, silently
    skipped, and (before a same-PR fix round renamed the test function the check anchors on)
    would have failed. The skip is now keyed on
    ``_threshold_pin_obligations(recipe_dir(recipe))`` -- the same real-call detector
    ``threshold_objective_pin`` uses to find every genuine ``select_confidence_threshold(``/
    ``select_threshold(`` call in the recipe's committed notebook or ``helpers.py`` -- so a
    scripted recipe with a gate is checked and one without a gate (scripted or not) is skipped
    on the actual absence of anything to re-derive.
  - ``readme_budget_note_matches_request_audit`` (#213) compares the audited execution with the
    recipe's one declaration, ``request_budget.json``, and the README with the paragraph
    rendered from it, for a recipe that adopts the route (declaration, ``AuditedBackend``
    notebook and rendered paragraph come together or not at all). It verifies the ledger's full
    ordered keys, derived counts, exact replay inventory, anchored source and committed output,
    and fails on a request decided twice unless the declaration names the repeats. Fresh
    offline execution remains the separate notebook CI job's duty. A recipe with none of the
    three keeps the existing strict ``len(responses.json)`` proxy, and unaudited scripted
    recipes still lack a committed artifact this check can read and retain the existing skip.
* ``noul_proposition_gold_coverage`` (#283) discovers a recipe's ``Noul`` propositions by
  CALLING every zero-required-argument function ``helpers.py`` defines (not imports) and
  keeping the ``Noul``-valued entries of any dict each one returns -- the recipe's own code
  builds the questions it sends, so every proposition this finds is one a live run asks about,
  under whatever name the recipe's own code gave it, never a name or spelling this check
  supplies. The converse does not hold: it finds what zero-argument calls reach, not
  everything the recipe builds (recipe 39, below). Measured against the published set, 51
  such function calls across 49 published recipes plus the template (43 of the 50
  ``helpers.py`` modules define at least one) opened no file, printed nothing and raised
  nothing; the calls themselves took about 0.015s, and the whole discovery sweep, including
  ``load_helpers`` for all 50 modules, about 0.2s -- a measurement of today's set, not a
  contract: see
  ``_noul_propositions`` for what those calls include besides question builders. Ten published
  recipes expose two or more ``Noul`` propositions to this route (06, 25, 26, 31, 35, 37, 41,
  42, 44, 48) and every one already carries a gold-true and a gold-false row for every
  proposition in both scored splits, so this check needs no
  ``tests/recipe_guard_known_failures.py`` entry to land.

  KNOWN UNREACHED CASE: recipe 39 builds two ``Noul`` propositions (one per field in
  ``FIELDS``) in one stage-2 request, but through ``build_stage2_questions(which)``, which
  requires an argument, so zero-argument discovery finds none of them. That is a limit of
  the discovery route, not a fact about the recipe, and the skip reason says so. It is also the
  right outcome rather than a gap to close by calling the builder with ``list(FIELDS)``: 39's
  ``labels.jsonl`` records each field's extracted STRING (``{"invoice_number": "4420", ...}``),
  not a per-proposition boolean, so if the builder were reached every row would read gold-true
  and the check would fail the recipe on gold it simply cannot read. Widening discovery to
  argument-taking builders is a design decision this check does not make; a recipe whose
  question builder requires an argument (a feature list, a field list) is not covered by it.

  A recipe with zero or one ``Noul`` proposition reached is skipped, not passed vacuously:
  gold-coverage-per-proposition is the #283 battery property, and a single proposition's
  ``labels.jsonl`` entry in this cookbook is often a bare boolean with no proposition key at
  all (recipes 02, 10, 15), which this check does not attempt to read.
* ``review_reason_string`` (#227) and ``confidence_gate_from_shared_helper`` (#282) read the same
  analysis of ``helpers.py`` and the notebook's code cells, by AST: where a confidence is
  compared with a bound a recipe chooses (a gate; an argument range check is not one), where the
  confidence-gated review's reason is produced by executable code, and whether a comparison
  controls that branch. The two checks share ONE applicability predicate
  (``_live_gate_locations``). The glossary's rule is conditional (it words a confidence-gated
  review; it does not require one), so a recipe with no gate is not applicable and a recipe may
  not satisfy the check by a comment. Two closed, named lists record what the published set
  looked like when this landed: ``GATE_FREE_DESIGNS`` (recipe 28, by design; not applicable to
  either check, in the style of ``NAMED_DOMAIN_OUTCOME_EXEMPTIONS``) and
  ``REASON_NOT_IN_COMMITTED_OUTPUT`` (eight recipes whose live gate no committed output shows
  producing a review: recorded drift owned by #342, in the ``see #NNN`` convention of
  ``tests/recipe_guard_known_failures.py``, but reported as a SKIP after the static half has held
  in full, which a strict xfail would not do). Both are strict, so a stale entry fails. A recipe
  pull request cannot edit this file, so neither list grows from a recipe.
  The checks that skip on "no resolvable ``select_confidence_threshold(`` call"
  (``threshold_objective_pin`` and ``stored_answers_strong_form``) are unchanged:
  ``confidence_gate_from_shared_helper`` is what makes the skip mean "no gate" rather than "a gate the finder cannot see".
* Honesty checks (#218, CONTRIBUTING.md section 2). The rule "no notebook, README or pull request
  may state or imply anything about Jev's real quality, latency or cost except as measured" had
  no check, and a fabricated "97.4% accuracy, 180 ms median latency, $0.0004 a call" passed every
  test in the repository twice. A check cannot judge meaning, and none of these claims to. They
  are a floor, built on what is decidable, and ``docs/offline-and-live.md`` ("What the recipe
  guard checks about section 2") is where a reviewer reads what is NOT covered. The decisions:

  - IMPLEMENTED (items 2 and 3, and the quoted-value check from #218's third comment):
    ``reported_provenance_matches_fixtures``, ``readme_states_fixture_provenance``,
    ``metric_output_lines_carry_pipeline_check`` and ``prose_quantities_are_printed``. Measured
    over the 50 published recipes and the template when they landed: 0 violations, so none is in
    ``tests/recipe_guard_known_failures.py``. Each examined real input (6548 committed output
    lines, 1190 metric lines, 213 quoted quantities, none of them a price or a latency), and
    ``test_each_detector_sees_something_...`` pins floors so a parser that finds nothing cannot
    pass for a clean tree.
  - REJECTED, item 3 as worded ("a notebook that says ``recorded`` must have a non-synthetic
    response"): every one of the 51 recipe folders says ``recorded`` in its prose (214 times in
    READMEs and markdown cells), in the contract's own counterfactual and for a logged action,
    so it would reject the template. The replacement compares the mode the output REPORTS with
    the mode the fixtures CARRY.
  - IMPLEMENTED NARROWLY, item 1 (claim vocabulary): ``no_unhedged_quality_claim_about_jev``
    flags only a sentence in which Jev or the model (not a possessive: "the model's stored
    answers") is the subject of an evaluative adverb or adjective, with no negation, hypothetical
    or attribution in it. The unit a hedge covers is its own sentence, heading, list item (with
    its wrapped lines) or table row (``_markdown_units``): a hedge word in a neighbouring bullet or
    in the heading above excuses nothing. Measured over the 7093 sentences of the 3517 units of
    the published READMEs and markdown cells: 2 match, both hedged ("not", "not a finding about Jev"), so it
    lands with 0 violations. REJECTED, the wide form (any evaluative word near a mention of Jev): 644
    sentences match an ordinary lexicon, nearly all of them disclosures that name accuracy,
    cost or latency in order to deny them, comparisons between a recipe's own baselines on its
    own fixtures ("beats"), or TypeSafe's documentation quoted. A recipe pull request cannot edit
    this file, so an allowlist of reviewed sentences cannot be answered from the recipe that
    trips it.
  - REJECTED, a warning tier: pytest has no channel through which a recipe pull request can
    "answer" a warning inside its own scope, so a warning here would be noise nobody is required
    to read. A rule this important is a failure or it is the reviewer's.
  - NOT COVERED, written down rather than omitted: a claim about Jev with no evaluative word
    ("Jev judges from the evidence as a whole"), a true number given a false interpretation, a
    fixture-derived statistic offered as evidence about the model, a metric that is perfect by
    construction and reported without saying so, a statement that misdescribes the notebook's own
    output (#221's six findings; none quotes a number the output did not print), counts with no
    decimal ("15 of 15", #326), and pull request text. ``_REVIEWER_ONLY`` below pins that these
    pass, so a later check that starts catching one must move it deliberately.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import inspect
import io
import json
import operator
import posixpath
import re
import shutil
import subprocess
import sys
import textwrap
import tokenize
from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

import pytest
from markdown_it import MarkdownIt

from jev_cookbook import Noul, load_helpers
from jev_cookbook import fixtures as jc_fixtures

REPO = Path(__file__).resolve().parent.parent


def _load_known_failures() -> dict[tuple[str, str], str]:
    """``tests/recipe_guard_known_failures.py``'s ``KNOWN_FAILURES``, loaded by explicit file
    path relative to this module. ``tools/new_recipe.py``'s own loader elsewhere in this module
    uses the same mechanism."""
    spec = importlib.util.spec_from_file_location(
        "recipe_guard_known_failures",
        Path(__file__).resolve().parent / "recipe_guard_known_failures.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.KNOWN_FAILURES


KNOWN_FAILURES = _load_known_failures()
RECIPES_DIR = REPO / "recipes"
TEMPLATE = RECIPES_DIR / "_template"
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))


def _is_published(recipe: dict) -> bool:
    return (RECIPES_DIR / recipe["slug"] / "notebook.ipynb").is_file()


# _template is a reference recipe outside the catalog.
PUBLISHED: list[dict] = [r for r in CATALOG["recipes"] if _is_published(r)]
PUBLISHED_NUMBERS = frozenset(int(r["slug"].split("-", 1)[0]) for r in PUBLISHED)
PUBLISHED_SLUGS = frozenset(r["slug"] for r in PUBLISHED)
RECIPES_WITH_TEMPLATE = [*PUBLISHED, {"slug": "_template"}]


def test_at_least_one_recipe_is_published():
    # Otherwise every published-recipe case below would silently check nothing.
    assert PUBLISHED_SLUGS


def _slug(recipe_or_path) -> str:
    return recipe_or_path["slug"] if isinstance(recipe_or_path, dict) else recipe_or_path.name


def guarded(check_id: str, *, skip_template: str | None = None):
    """Register published recipe cases and include the template unless given a skip reason."""
    if skip_template is not None and (
        not isinstance(skip_template, str) or not skip_template.strip()
    ):
        raise ValueError(f"{check_id}: skip_template needs a non-empty reason")

    cases = []
    recipes = PUBLISHED if skip_template is not None else RECIPES_WITH_TEMPLATE
    for recipe in recipes:
        slug = _slug(recipe)
        reason = KNOWN_FAILURES.get((slug, check_id)) if slug != "_template" else None
        marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
        cases.append(pytest.param(recipe, id=slug, marks=marks))
    return cases


def recipe_dir(recipe: dict) -> Path:
    return RECIPES_DIR / recipe["slug"]


def load_tool(name: str) -> ModuleType:
    """A tool module, loaded by file path (tools/ has no __init__.py)."""
    spec = importlib.util.spec_from_file_location(f"{name}_for_recipe_guard", REPO / "tools" / name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotated fields through their module
    spec.loader.exec_module(module)
    return module


def notebook_cells(recipe_dir_: Path) -> list[dict]:
    return json.loads((recipe_dir_ / "notebook.ipynb").read_text("utf-8"))["cells"]


def cell_source(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def extract_calls(source: str, name: str) -> list[str]:
    """Every balanced ``name(...)`` call in ``source``, as its full text including the parens.

    A plain depth counter over every ``(``/``)`` in the source, not a tokenizer: good enough for
    the call shapes these notebooks actually use (no unbalanced parens inside a string literal
    argument), and it has to handle a call whose own arguments contain further calls (an f-string
    computing ``{len(x)}``), which a non-recursive regex cannot.
    """
    calls = []
    start = 0
    needle = name + "("
    while True:
        idx = source.find(needle, start)
        if idx == -1:
            return calls
        depth = 0
        end = None
        for j in range(idx + len(name), len(source)):
            if source[j] == "(":
                depth += 1
            elif source[j] == ")":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end is None:
            return calls
        calls.append(source[idx : end + 1])
        start = end + 1


# --------------------------------------------------------------------------------------------
# check 1: tests/test_build_fixtures.py matches the current scaffold
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recipe",
    guarded(
        "build_fixtures_scaffold",
        skip_template="The renderer needs a catalog row. The template tests pin the scaffold.",
    ),
)
def test_build_fixtures_guard_matches_the_current_scaffold(recipe):
    """G1(a): byte-identical to ``tools/new_recipe.py::build_fixtures_test_text(recipe, mode)``
    for the recipe's scaffold mode (below), the exact text ``python tools/new_recipe.py`` would
    emit for this recipe today. Byte identity
    (rather than, say, checking for the regeneration assertion alone) is the precise signature:
    it also catches a stray issue number in the docstring (R9) and any other drift in the same
    motion, and it is exactly what ``tests/test_template.py`` already proves for the template
    itself (reversing the substitution the other way).

    The property this check is about is replay-mode fixture scaffolding, which only exists for
    a replay-mode recipe: a scripted recipe's ``tools/new_recipe.py --mode scripted`` scaffold
    (``build_scripted_fixtures_text``) never writes ``responses.json`` and never writes a
    ``tests/test_build_fixtures.py`` for this check to hold byte-identical to anything, so the
    skip below is genuinely vacuous for one, not a proxy standing in for a different property
    (#249).

    A recipe with an ``assets/`` folder is an image recipe, and its scaffold is
    ``--mode replay-images``, whose ``tests/test_build_fixtures.py`` also copies ``assets/``
    (``build_fixtures_test_text(recipe, "replay-images")``); every other replay recipe is held to
    the text variant (#452)."""
    path = recipe_dir(recipe) / "fixtures" / "responses.json"
    if not path.is_file():
        pytest.skip(
            "scripted recipe: replay-mode scaffold does not apply, no test_build_fixtures.py "
            "to guard (see #249)"
        )
    folder = recipe_dir(recipe)
    new_recipe = load_tool("new_recipe.py")
    mode = new_recipe.IMAGE_MODE if (folder / "assets").is_dir() else "replay"
    expected = new_recipe.build_fixtures_test_text(recipe, mode)
    actual_path = folder / "tests" / "test_build_fixtures.py"
    assert actual_path.is_file(), f"{recipe['slug']}: no tests/test_build_fixtures.py"
    assert actual_path.read_text("utf-8") == expected


@pytest.mark.parametrize(
    "kind,committed,passes",
    [
        ("text", "text", True),
        ("image", "image", True),
        ("image", "text", False),
        ("text", "image", False),
    ],
)
def test_build_fixtures_guard_holds_an_image_recipe_to_the_image_variant(
    tmp_path, monkeypatch, kind, committed, passes
):
    """G1(a) itself, run on a recipe folder built here: an image recipe (``assets/`` present) that
    commits the text variant fails, and so does a text recipe that commits the image variant;
    each committing its own variant passes (#452)."""
    new_recipe = load_tool("new_recipe.py")
    recipes = [r for r in CATALOG["recipes"] if r["rank"] == 77]
    assert len(recipes) == 1, "catalog rank 77 is the image recipe this test scaffolds against"
    recipe = recipes[0]
    variants = {
        "text": new_recipe.build_fixtures_test_text(recipe),
        "image": new_recipe.build_fixtures_test_text(recipe, new_recipe.IMAGE_MODE),
    }
    assert variants["text"] != variants["image"]
    monkeypatch.setitem(globals(), "RECIPES_DIR", tmp_path)
    folder = recipe_dir(recipe)
    (folder / "fixtures").mkdir(parents=True)
    (folder / "fixtures" / "responses.json").write_text("{}\n", "utf-8")
    (folder / "tests").mkdir()
    (folder / "tests" / "test_build_fixtures.py").write_text(variants[committed], "utf-8")
    if kind == "image":
        (folder / "assets").mkdir()
        (folder / "assets" / "screen.png").write_bytes(b"not read by G1(a)")
    if passes:
        test_build_fixtures_guard_matches_the_current_scaffold(recipe)
    else:
        with pytest.raises(AssertionError):
            test_build_fixtures_guard_matches_the_current_scaffold(recipe)


# --------------------------------------------------------------------------------------------
# check 2: no "#NNN", "the issue" or any other pointer a reader cannot open in a recipe file
# --------------------------------------------------------------------------------------------

ISSUE_NUMBER = re.compile(r"#\d+\b")
THE_ISSUE = re.compile(r"\bthe issue\b", re.IGNORECASE)
QUOTED = re.compile(r'"[^"\n]*"')


def _strip_quoted(text: str) -> str:
    """Remove double-quoted spans before scanning prose for an issue citation: a recipe's own
    markdown routinely quotes a fixture's raw input text back at the reader (an invented invoice
    or ticket number, "invoice #312"), and that fabricated, in-fiction "#NNN" is not a citation
    of this repository's issue tracker. A real citation ("Issue #2 asks for...") is never itself
    inside quotes, so this does not hide one."""
    return QUOTED.sub(" ", text)


def _prose_of_python(source: str) -> str:
    """Docstrings and comments only -- the prose a reader of the file sees -- not string-literal
    fixture data (a ``ROWS`` entry can legitimately contain a fabricated "#NNN", an invoice or
    ticket number that is part of the example, not a citation)."""
    parts = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    parts.append(doc)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                parts.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return "\n".join(parts)


# CONTRIBUTING.md section 6 forbids pointers to documents a reader cannot open. Ordinary
# orchestration, hardware notation, batches of input and precision-recall metrics are not such
# pointers. The contextual exceptions below are intentionally small (#471): an ambiguous label
# or unexplained PR still fails, and every exception has a paired process-citation regression.
NUMBER_LIST = r"\d+(?:\s*(?:,\s*(?:(?:and|or)\s+)?|(?:and|or)\s+|&\s*)\d+)*"
# A list of rule numbers shares the following target. Bare paths are repository-root-relative;
# rendered Markdown links are relative to the actual source file. Neither spelling grants a
# private orchestration file, untracked file, directory, symlink or case-mismatched path a pass.
COMMITTED_RULE_TARGET = re.compile(
    r"\s*(?i:of|in|from)\s+(?:\[[^]\n]+\]\((?P<link>[^\s)]+)\)"
    r"|`(?P<code>[^`\n]+)`|(?P<bare>[^\s`<>()\[\]{}]+))"
)
RECIPE_NUMBER = re.compile(rf"\brecipes?\s+({NUMBER_LIST})\b", re.IGNORECASE)
RECIPE_SLUG_LINK = re.compile(
    # An underscore may open emphasis; real underscore suffixes stay inside the folder token.
    r"(?<![^\W_])(?<![.-])(?:(?:\.\./)+(?:recipes/)?|recipes/)"
    r"(\d{2,3}-[^\s/`)\]}>\"',;:!?#]+)"
)
# A destination starts after the link opener, independently of its optional title or closing
# whitespace. Even a malformed link keeps its destination literal; it cannot turn a real folder
# period into prose punctuation by breaking its closing delimiter. Angle destinations also name
# literal paths. This is conservative recognition, not a complete Markdown renderer.
RECIPE_LITERAL_PATH = re.compile(
    r"`+(?P<code>[^`\n]*)`+|\[[^]\n]*\]\(\s*"
    r"(?:<(?P<angle>[^>\n]*)>|(?P<link>[^\s)>]+))"
)
PR_METRIC_WORD = re.compile(
    r"\)?[\s-]*(?:curves?|AUC|AP|areas?|plots?|precision|recall|metrics?)\b", re.IGNORECASE
)
# "plots" and "metrics" are plural nouns ("the PR plots are in the figure") and also a verb or a
# verb's subject ("this PR plots the new curve", "the PR metrics changed in review"). The plural
# is a metric when the spelled-out form precedes it ("precision-recall (PR) plots", checked
# first), or when the next word is one of these closed classes: the end of the clause, punctuation
# (`, . ; : ( )`, an em or en dash, `--`, or a hyphen followed by whitespace), a preposition, a
# conjunction (`and or but nor`), a copula (`are is were was`) or `show(s)`. The prepositions
# are a closed list too. Everything else is a pointer, and that is the recorded trade-off
# (#639): a determiner or an ordinary verb after the plural ("this PR plots the curve", "the PR
# metrics improved") is flagged even when it was meant as the metric, and the fix for the
# author is to spell out "precision-recall (PR)".
PR_PLURAL_METRIC_WORD = re.compile(r"\)?[\s-]*(?:plots|metrics)\b", re.IGNORECASE)
_PR_PREPOSITIONS = (
    "for|on|over|of|at|by|from|across|per|with|in|into|to|under|below|above|against|as|than"
    "|within|between|through|during|after|before|among|along|beyond|without|about|around|near"
    "|onto|upon|via|versus|vs|like|unlike|beneath|beside|besides|despite|except|inside|outside"
    "|throughout|toward|towards|underneath|until"
)
PR_PLURAL_METRIC_END = re.compile(
    rf"\s*(?:$|[,.;:()\u2014\u2013]|--|-(?=\s)|(?:{_PR_PREPOSITIONS}"
    r"|and|or|but|nor|are|is|were|was|show|shows)\b)",
    re.IGNORECASE,
)


def _pr_is_metric(text: str, start: int, end: int) -> bool:
    """Recognise metric grammar, never a word merely starting with a metric word.

    Scores/points are ambiguous: allow a standalone metric noun or a metric's preposition,
    but not a pointer's verb ("points out", "scores the change"). Spell out precision-recall
    when another construction is needed rather than adding a blanket PR exemption.
    """
    before, after = text[:start], text[end:]
    plural = PR_PLURAL_METRIC_WORD.match(after)
    if plural:
        if re.search(r"\brecall\s+\($", before, re.I) and after.startswith(")"):
            return True
        return bool(PR_PLURAL_METRIC_END.match(after, plural.end()))
    if PR_METRIC_WORD.match(after):
        return True
    if re.match(r"\s+(?:scores?|points?)\b(?=\s*(?:$|[,.;:)]|(?:for|on|over)\b))", after, re.I):
        return True
    if re.match(r"\s+and\s+ROC\s+curves?\b", after, re.I):
        return True
    if re.match(
        r"\s+is\s+(?:0(?:\.[0-9]+)?|1(?:\.0+)?)"
        r"(?=\s*(?:$|[,;:!?)](?=\s|$)|\.(?=\s|$)))",
        after,
        re.I,
    ):
        return True
    if re.search(r"\brecall\s+\($", before, re.I):
        return after.startswith(")")
    return bool(
        re.search(r"\barea\s+under\s+(?:the\s+)?$", before, re.I)
        and re.match(r"\s*(?:$|[,.;:)]|(?:is|of)\b)", after, re.I)
    )


@cache
def _tracked_regular_files(repo: Path) -> frozenset[str]:
    """One case-exact index snapshot per repository in this guard invocation; git errors fail.

    Stage/mode checks also reject symlinks, submodules and unresolved index entries. Do not use
    exists(): an ignored local file must not make the same prose pass only on one machine.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--stage", "-z"],
        check=True,
        capture_output=True,
    )
    files = set()
    for record in result.stdout.split(b"\0"):
        if record:
            metadata, path = record.split(b"\t", 1)
            mode, _object_id, stage = metadata.split()
            if mode in (b"100644", b"100755") and stage == b"0":
                files.add(path.decode("utf-8", "surrogateescape"))
    return frozenset(files)


def _names_a_committed_file(text: str, end: int, source_path: Path | None = None) -> bool:
    """Whether the rule's target names a tracked regular file a recipe reader can open."""
    found = COMMITTED_RULE_TARGET.match(text, end)
    if not found:
        return False
    path = found.group("link") or found.group("code") or found.group("bare")
    if found.group("bare"):
        # Capture the whole token before trimming sentence punctuation; never validate a
        # tracked prefix of a query, percent escape, backslash path or another malformed token.
        path = path.rstrip(".,;:!?")
        if not any(c in path for c in (".", "/")):
            return False
    if found.group("link"):
        path = path.split("#", 1)[0]
    if any(c in path for c in (":", "%", "?", "\\", "#")):
        return False
    if found.group("link"):
        # No schemes, absolute paths, URL escapes, queries or platform-specific separators.
        # Resolve ../ lexically, then check containment and exact git membership. Never resolve
        # a symlink first: its textual path must not become another file's legitimate name.
        if source_path is None:
            return False
        try:
            parent = source_path.relative_to(REPO).parent.as_posix()
        except ValueError:
            return False
        if path.startswith("/"):
            return False
        path = posixpath.normpath(posixpath.join(parent, path))
    elif path.startswith("/") or ".." in path.split("/") or "." in path.split("/"):
        return False
    if path.startswith(("/", "../", "orchestration/")) or path == "orchestration":
        return False
    if path not in _tracked_regular_files(REPO):
        return False
    target = REPO / path
    return target.is_file() and not any(
        p.is_symlink() for p in (target, *target.parents) if p != REPO
    )


def _allow_pr_metric(text: str, match: re.Match[str], source_path: Path | None) -> bool:
    return match.group().startswith("PR") and _pr_is_metric(text, match.start(), match.end())


def _allow_recipe_actor(text: str, match: re.Match[str], source_path: Path | None) -> bool:
    # Singular "brief pause/delay" is adjective+noun; plural-looking "the brief delays"
    # can instead be a brief imposing requirements and must remain a pointer. Routing
    # tasks to skills describes the recipe's actor. Keep other bare roles conservative.
    after = text[match.end() :]
    return bool(
        (
            match.group().lower().endswith("brief")
            and re.match(r"\s+(?:pause|delay|interval|wait)\b", after, re.I)
        )
        or (
            match.group().lower().endswith("orchestrator")
            and re.match(
                r"\s+routes?\s+(?:each\s+task|tasks?)\s+to\s+(?:a|the)\s+skills?\b",
                after,
                re.I,
            )
        )
    )


def _allow_input_batch(text: str, match: re.Match[str], source_path: Path | None) -> bool:
    return bool(
        match.group().lower().startswith("batch")
        and re.search(r"\bprocess\s+$", text[: match.start()], re.I)
        and re.match(r"\s+of\s+\d+\b", text[match.end() :])
    )


def _allow_ordinary_notation(text: str, match: re.Match[str], source_path: Path | None) -> bool:
    before, after = text[: match.start()], text[match.end() :]
    # A colon/dash still introduces a finding even after an ordinary-looking noun.
    if re.match(r"\s*[:–—-]", after):
        return False
    # A sample or region label is ordinary only in "sample (N1) of the population"; "per sample
    # (M3)" has the shape of a finding label and stays a hit (#639).
    return bool(
        re.search(r"\bvitamin\s+$", before, re.I)
        or (
            re.search(r"\b(?:sample|region)\s+$", before, re.I)
            and re.match(r"\s+of\b", after, re.I)
        )
        or (
            re.fullmatch(r"\(\s*M[1-9]\s*\)", match.group())
            and re.match(r"\s+chips?\b", after, re.I)
        )
    )


def _allow_committed_rule(text: str, match: re.Match[str], source_path: Path | None) -> bool:
    return _names_a_committed_file(text, match.end(), source_path)


def _allow_no_citation(text: str, match: re.Match[str], source_path: Path | None) -> bool:
    return False


class CitationPattern(NamedTuple):
    pattern: re.Pattern[str]
    allow: Callable[[str, re.Match[str], Path | None], bool]
    explanation: str = "a reader cannot open it"


PROCESS_CITATIONS: dict[str, CitationPattern] = {
    "pull request pointer": CitationPattern(
        re.compile(
            r"\b(?-i:PRs?)\b|\bpull[- ]requests?(?:['’]s|['’])?\s+"
            r"(?:description|body|text|\d+)\b",
            re.IGNORECASE,
        ),
        _allow_pr_metric,
    ),
    "wave or batch number": CitationPattern(
        re.compile(r"\b(?:wave|batch)\s+\d+\b", re.IGNORECASE), _allow_input_batch
    ),
    "review round": CitationPattern(
        re.compile(r"\b(?:review|fix)\s+round\b", re.IGNORECASE), _allow_no_citation
    ),
    "house rule number": CitationPattern(
        re.compile(rf"\brules?\s+{NUMBER_LIST}\b", re.IGNORECASE),
        _allow_committed_rule,
        "a reader cannot open it; name a case-exact git-tracked regular file outside orchestration/ "
        "using a repository-root-relative path or a Markdown link relative to this file",
    ),
    "orchestration role": CitationPattern(
        re.compile(
            r"\bthe\s+(?:orchestrator|brief)\b"
            r"|\b(?:the|this)\s+(?:independent\s+)?reviewers?(?:['’]s|['’])?\s+"
            r"(?:found|finding|findings|noted|asked|comments?|said|required|flagged)\b"
            r"|\breviewers['’]\s+(?:findings?|comments?)\b",
            re.IGNORECASE,
        ),
        _allow_recipe_actor,
    ),
    "review finding label": CitationPattern(
        re.compile(r"\(\s*[MSBN][1-9]\s*\)"), _allow_ordinary_notation
    ),
    "acceptance criteria": CitationPattern(
        re.compile(r"\bacceptance\s+criteri(?:a|on)\b", re.IGNORECASE), _allow_no_citation
    ),
}


def _recipe_reference_slug(text: str, match: re.Match[str]) -> str:
    """Keep literal folder names exact; remove only paired prose emphasis and punctuation."""
    slug = match.group(1)
    if text[match.end() :].startswith("/"):
        return slug
    for literal in RECIPE_LITERAL_PATH.finditer(text):
        group = next(name for name in ("code", "angle", "link") if literal.group(name) is not None)
        start, end = literal.span(group)
        if start <= match.start() and match.end() <= end:
            # The prose regex deliberately stops at punctuation. Literal destinations
            # cannot accept that prefix as a real folder: recover the entire segment
            # through its slash/query/fragment boundary, including punctuation/spaces.
            return re.split(r"[/?#]", text[match.start(1) : end], maxsplit=1)[0]
    # A bare prose path can finish a sentence. An explicit code/link destination, or a folder
    # segment before a slash, cannot borrow this punctuation exception for its real name.
    slug = slug.rstrip(".…")
    opening = re.search(r"([*_]+)$", text[: match.start()])
    if opening:
        closing = opening.group(1)[::-1]
        if slug.endswith(closing):
            slug = slug[: -len(closing)].rstrip(".…")
    return slug


def _citation_hits(text: str, location: str, source_path: Path | None = None) -> list[str]:
    text = _strip_quoted(text)
    hits = [f"{location}: {m.group(0)!r} (issue number)" for m in ISSUE_NUMBER.finditer(text)]
    hits += [f'{location}: {m.group(0)!r} ("the issue")' for m in THE_ISSUE.finditer(text)]
    for kind, rule in PROCESS_CITATIONS.items():
        for m in rule.pattern.finditer(text):
            if not rule.allow(text, m, source_path):
                hits.append(f"{location}: {m.group(0)!r} ({kind}: {rule.explanation})")
    for m in RECIPE_NUMBER.finditer(text):
        for number in re.findall(r"\d+", m.group(1)):
            if int(number) not in PUBLISHED_NUMBERS:
                hits.append(f"{location}: recipe {number!s} (a recipe that is not published)")
    for m in RECIPE_SLUG_LINK.finditer(text):
        if _recipe_reference_slug(text, m) not in PUBLISHED_SLUGS:
            hits.append(f"{location}: {m.group(0)!r} (a recipe that is not published)")
    return hits


@pytest.mark.parametrize(
    "sentence",
    [
        "the PR is 1 commit ahead",
        "the PR is 1 of the required approvals",
        "the PR is 1.2 revisions old",
        "the PR is 0 commits ahead",
        "the PR is 0.81 commits behind",
        "the PR is 1.000 revisions old",
        "the PR is 1,000 commits ahead",
        "the PR is 1,234 commits behind",
        "the PR is 0,123 revisions old",
    ],
)
def test_numeric_pr_metrics_do_not_excuse_process_predicates(sentence):
    assert _citation_hits(sentence, "negative control")


@pytest.mark.parametrize("value", ["0", "0.81", "1", "1.000"])
@pytest.mark.parametrize("ending", ["", ".", ", with recall shown separately."])
def test_numeric_pr_metric_sentence_remains_allowed(value, ending):
    assert not _citation_hits(f"the PR is {value}{ending}", "metric control")


@pytest.mark.parametrize("punctuation", [",", ";", ":", "!", "'", '"', ")", "]", "}", " "])
@pytest.mark.parametrize("prefix", ["../", "../../recipes/", "recipes/"])
@pytest.mark.parametrize("wrapper", ["`{}`", "[next](<{}>)"])
def test_literal_recipe_folder_suffix_is_not_a_published_prefix(punctuation, prefix, wrapper):
    target = f"{prefix}30-citation-verification{punctuation}missing/README.md"
    assert _citation_hits(wrapper.format(target), "literal destination")


@pytest.mark.parametrize("punctuation", [",", ";", ":", "!", "'", '"', "]", "}"])
def test_unbracketed_recipe_folder_suffix_is_not_a_published_prefix(punctuation):
    target = f"../30-citation-verification{punctuation}missing/README.md"
    assert _citation_hits(f"[next]({target})", "literal destination")


def _recipe_citation_hits(recipe_dir_: Path) -> list[str]:
    hits = []
    for name in ("helpers.py", "build_fixtures.py"):
        path = recipe_dir_ / name
        if path.is_file():
            hits += _citation_hits(_prose_of_python(path.read_text("utf-8")), name, path)
    readme = recipe_dir_ / "README.md"
    if readme.is_file():
        hits += _citation_hits(readme.read_text("utf-8"), "README.md", readme)
    tests_dir = recipe_dir_ / "tests"
    if tests_dir.is_dir():
        for path in sorted(tests_dir.glob("*.py")):
            hits += _citation_hits(
                _prose_of_python(path.read_text("utf-8")), f"tests/{path.name}", path
            )
    notebook = recipe_dir_ / "notebook.ipynb"
    if notebook.is_file():
        for cell in notebook_cells(recipe_dir_):
            source = cell_source(cell)
            location = f"notebook.ipynb cell {cell.get('id', '?')}"
            if cell["cell_type"] == "code":
                hits += _citation_hits(_prose_of_python(source), location, notebook)
            else:
                hits += _citation_hits(source, location, notebook)
    return hits


@pytest.mark.parametrize("recipe", guarded("no_issue_citations"))
def test_no_issue_numbers_or_the_issue_in_recipe_files(recipe):
    """G1(b), CONTRIBUTING.md section 6: "A recipe file never cites a private issue number or
    'the issue' -- a reader cannot see either." Scans the prose of helpers.py, build_fixtures.py,
    every tests/*.py file, README.md and every notebook cell (code cells: docstrings and comments
    only; markdown cells and README.md: full text, minus quoted fixture text -- see
    ``_strip_quoted``'s docstring for why). The reason section 6 gives governs every spelling, so
    the check also reads ``PROCESS_CITATIONS`` and the unpublished-recipe pointers (#225)."""
    hits = _recipe_citation_hits(recipe_dir(recipe))
    assert not hits, "; ".join(hits)


# --------------------------------------------------------------------------------------------
# check 2b: no cell id cited in reader-facing prose (#250)
# --------------------------------------------------------------------------------------------

CODE_SPAN = re.compile(r"`([^`\n]+)`")
# This private module instance uses the dev-installed block parser. The scope CLI and docs
# loader use separate instances and retain their dependency-free physical-line mode.
_cell_id_scope = load_tool("check_recipe_scope.py")
_cell_id_scope.COMMONMARK_FENCE_CONTEXT = True
without_code_fences = _cell_id_scope.without_code_fences


def _hyphenated_cell_ids(recipe_dir_: Path, *, cells: list[dict] | None = None) -> set[str]:
    """The ids of the notebook's cells that contain a hyphen. A single-word id (``state``,
    ``setup``, ``answer``) is also an ordinary English word, so a backticked ``state`` is more
    often prose than a pointer, and counting those made every count taken before this one
    wrong (13 across 9 recipes, then 9 across 5 with ``state`` in it, then 13 in recipe 36 alone,
    every one of those 13 a coincidence); they cannot be told apart mechanically and are not checked."""
    if cells is None:
        cells = notebook_cells(recipe_dir_)
    return {c["id"] for c in cells if "-" in str(c.get("id", ""))}


def _cell_id_citations(text: str, ids: set[str], location: str) -> list[str]:
    """Every backticked span of ``text`` that is exactly one of ``ids``. Fenced blocks are
    code, not prose addressed to the reader. The shared helper's explicitly selected CommonMark
    mode removes fence-token line ranges, including fences inside containers, while preserving
    fence-looking lines in HTML blocks. An unclosed fence ends at its container or the document.
    Inline spans, HTML content and indented code otherwise keep this check's existing policy.
    The reader models CommonMark (markdown-it-py's preset), not GitHub's cmark-gfm, so GFM-only
    containers such as footnote definitions are not modelled."""
    text = without_code_fences(text)
    return [
        f"{location}: `{m.group(1)}` is a cell id, which only the .ipynb JSON shows"
        for m in CODE_SPAN.finditer(text)
        if m.group(1) in ids
    ]


def _recipe_cell_id_citations(recipe_dir_: Path) -> list[str]:
    """A cell id cited in this recipe's markdown cells or README.md. Out of scope by design: a
    code cell's comments, and the tests that find a cell by its id (``c.get("id") == "..."``),
    which are machinery reading the JSON, not prose a reader is pointed through."""
    cells = notebook_cells(recipe_dir_)
    ids = _hyphenated_cell_ids(recipe_dir_, cells=cells)
    hits = []
    readme = recipe_dir_ / "README.md"
    if readme.is_file():
        hits += _cell_id_citations(readme.read_text("utf-8"), ids, "README.md")
    for cell in cells:
        if cell["cell_type"] == "markdown":
            location = f"notebook.ipynb cell {cell.get('id', '?')}"
            hits += _cell_id_citations(cell_source(cell), ids, location)
    return hits


@pytest.mark.parametrize("recipe", guarded("no_cell_id_citations"))
def test_no_cell_id_is_cited_in_reader_facing_prose(recipe):
    """#250, CONTRIBUTING.md section 6: a cell id exists only in the ``.ipynb`` JSON, so a reader
    of the rendered notebook (Jupyter, nbviewer, GitHub) never sees it, and "the ``python-rule``
    cell below" points at nothing. Quote the section heading or say what the cell prints. Fails
    on a backticked span in a markdown cell or README.md that equals a hyphenated cell id of that
    notebook; see ``_hyphenated_cell_ids`` for why single-word ids are not checked."""
    hits = _recipe_cell_id_citations(recipe_dir(recipe))
    assert not hits, "; ".join(hits)


# --------------------------------------------------------------------------------------------
# check 2c: a glossary term's first use in prose links its glossary entry (#211)
# --------------------------------------------------------------------------------------------

GLOSSARY_FILE = REPO / "docs" / "glossary.md"
# The template lexicon (docs/recipe-template.md, "The lexicon"): the terms every evaluation
# borrows, each with its glossary anchor. State and Score are Jev's own words, not lexicon terms,
# so their everyday senses are out of scope rather than excepted.
GLOSSARY_LEXICON = {
    "business threshold": "business-threshold",
    "confidence gate": "confidence-gate",
    "review": "review",
    "gold label": "gold-label",
    "coverage": "coverage",
    "risk": "risk",
    "selective prediction": "selective-prediction",
    "accuracy": "accuracy",
    "precision": "precision",
    "recall": "recall",
    "F1": "f1",
    "support": "support",
}
# The plural of a compound term is the same use; for a one-word term the plural is another word
# ("reviews" of a product, "risks" as a verb), so only these three take an ``s``.
_PLURAL_TERMS = frozenset({"business threshold", "confidence gate", "gold label"})
# Everyday senses of the ambiguous lexicon words. A match that overlaps one of these is not the
# cookbook term. Each entry is pinned by a pair of tests: the everyday phrase passes and the term
# beside it still fails. What this cannot judge stays with the reviewer (docs/notebook-ci.md).
_EVERYDAY_SENSES = {
    "review": re.compile(
        r"\b(?:customer|product|movie|film|restaurant|hotel|book|app|user|code|peer|final|star)"
        r"\s+reviews?\b"
        r"|\b(?:to|will|would|must|should|can|we|you|they|then)\s+review\s+"
        r"(?:the|a|an|each|every|this|that|it|them|their|its|these|those|all|any|whether|what|how)\b",
        re.IGNORECASE,
    ),
    "risk": re.compile(
        r"\b(?:at|some|any|no|small|real|low|high)\s+risk\s+of\b|\b(?:to|would|will|could|may|might)\s+risk\b",
        re.IGNORECASE,
    ),
    "coverage": re.compile(r"\b(?:test|code|news|insurance|media)\s+coverage\b", re.IGNORECASE),
}
# ``support`` is also an everyday noun and verb ("support tickets", "does the passage support
# the claim"). It is the cookbook's metric only beside the metrics it is reported with, so it
# counts only in a paragraph, list item or table cell that also names precision, recall or F1.
_SUPPORT_COMPANIONS = re.compile(r"\b(?:precision|recall|F1)\b", re.IGNORECASE)
_QUOTED_TEXT = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_GLOSSARY_MARKDOWN = MarkdownIt("commonmark").enable("table")
_EMPHASIS_TOKENS = frozenset({"em_open", "em_close", "strong_open", "strong_close"})


class GlossaryUse(NamedTuple):
    term: str
    href: str | None  # the link the use sits in, or None when it is bare
    ordinal: int  # position among the first uses, in document order


@cache
def _glossary_anchors() -> frozenset[str]:
    """The anchors ``docs/glossary.md`` defines: GitHub's slug of each ``##`` heading."""
    anchors = set()
    for line in GLOSSARY_FILE.read_text("utf-8").splitlines():
        if line.startswith("## "):
            anchors.add(re.sub(r"[^\w\- ]", "", line[3:].strip().lower()).replace(" ", "-"))
    return frozenset(anchors)


def _term_pattern(term: str) -> re.Pattern[str]:
    plural = "(?:s|es)?" if term in _PLURAL_TERMS else ""
    body = re.escape(term).replace(r"\ ", r"[\s-]+")
    # A hyphen beside F1 keeps it the metric ("F1-score", "macro-F1"); beside the other terms it
    # makes another word ("review-needed", "non-zero risk"), so there it is not a boundary.
    before = r"(?<!\w)" if term == "F1" else r"(?<![\w-])"
    after = r"(?!\w)" if term == "F1" else r"(?![\w-])"
    flags = 0 if term == "F1" else re.IGNORECASE
    return re.compile(rf"{before}{body}{plural}{after}", flags)


_TERM_PATTERNS = {term: _term_pattern(term) for term in GLOSSARY_LEXICON}


def _uses_term(term: str, text: str, unit_text: str) -> bool:
    """Does the prose ``text`` use ``term`` in the cookbook sense (see ``_EVERYDAY_SENSES``)?"""
    everyday = (
        [m.span() for m in _EVERYDAY_SENSES[term].finditer(text)]
        if term in _EVERYDAY_SENSES
        else []
    )
    for match in _TERM_PATTERNS[term].finditer(text):
        if any(start < match.end() and match.start() < end for start, end in everyday):
            continue
        if term == "support" and not _SUPPORT_COMPANIONS.search(unit_text):
            continue
        return True
    return False


def _scan_inline(children, first: dict[str, GlossaryUse]) -> None:
    """Record the first use of each term in the children of one inline token."""
    unit_text = " ".join(c.content for c in children if c.type in {"text", "code_inline"})
    state: dict = {"href": None, "depth": 0, "run": []}

    def record(term: str) -> None:
        first[term] = GlossaryUse(term, state["href"], len(first) + 1)

    def flush() -> None:
        text = _QUOTED_TEXT.sub(" ", "".join(state["run"]))
        state["run"] = []
        for term in GLOSSARY_LEXICON:
            if term not in first and _uses_term(term, text, unit_text):
                record(term)

    for child in children:
        if child.type == "text":
            state["run"].append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            state["run"].append(" ")
        elif child.type in _EMPHASIS_TOKENS:
            continue
        else:
            flush()
            if child.type == "link_open":
                state["depth"] += 1
                if state["depth"] == 1:
                    state["href"] = child.attrGet("href")
            elif child.type == "link_close":
                state["depth"] -= 1
                if not state["depth"]:
                    state["href"] = None
            elif child.type == "code_inline":
                code = child.content.strip()
                for term in GLOSSARY_LEXICON:
                    exact = code == term if term == "F1" else code.lower() == term.lower()
                    if exact and term not in first:
                        record(term)
    flush()


def _glossary_first_uses(markdown: str) -> dict[str, GlossaryUse]:
    """The first use of each lexicon term in the prose of one Markdown source, in document
    order, with the link it sits in. Prose is paragraphs, list items, table cells and quotes.
    Headings are structure, fenced and indented code and HTML are not prose, double-quoted text
    is a fixture's own words, and an inline code span counts only when it is exactly a term,
    which is how the bare form `` `gold label` `` names a term without linking it. Text is
    matched in runs: a soft line break reads as a space and emphasis markers are transparent, so
    ``gold`` + newline + ``label`` and ``**gold** label`` are the term. A link, a code span, an
    image or inline HTML ends a run."""
    first: dict[str, GlossaryUse] = {}
    in_heading = False
    for token in _GLOSSARY_MARKDOWN.parse(markdown):
        if token.type in {"heading_open", "heading_close"}:
            in_heading = token.type == "heading_open"
        if token.type != "inline" or in_heading:
            continue
        _scan_inline(token.children or (), first)
    return first


def _glossary_link_problem(use: GlossaryUse) -> str | None:
    """Why this first use does not link its anchor in the required form: the relative Markdown
    link ``../../docs/glossary.md#anchor`` (README.md and the notebook sit two folders below the
    repository root) to an anchor that ``docs/glossary.md`` defines."""
    anchor = GLOSSARY_LEXICON[use.term]
    want = f"../../docs/glossary.md#{anchor}"
    if anchor not in _glossary_anchors():
        return f"docs/glossary.md defines no #{anchor} anchor"
    if use.href is None:
        return f"is not a link to {want}"
    if use.href != want:
        return f"links {use.href!r}, not {want}"
    return None


def _glossary_link_hits(markdown: str, location: str) -> list[str]:
    hits = []
    for use in sorted(_glossary_first_uses(markdown).values(), key=lambda u: u.ordinal):
        problem = _glossary_link_problem(use)
        if problem:
            hits.append(f"{location}: first use of {use.term!r} {problem}")
    return hits


def _recipe_glossary_link_hits(recipe_dir_: Path) -> list[str]:
    """The README is checked on its own. In the notebook a term's first use is in the first
    markdown cell, in notebook order, that uses it, so a term first used in one cell and again,
    unlinked, in a later cell is one link, not two."""
    hits = []
    readme = recipe_dir_ / "README.md"
    if readme.is_file():
        hits += _glossary_link_hits(readme.read_text("utf-8"), "README.md")
    seen: set[str] = set()
    for cell in notebook_cells(recipe_dir_):
        if cell["cell_type"] != "markdown":
            continue
        location = f"notebook.ipynb cell {cell.get('id', '?')}"
        for use in sorted(
            _glossary_first_uses(cell_source(cell)).values(), key=lambda u: u.ordinal
        ):
            if use.term in seen:
                continue
            seen.add(use.term)
            problem = _glossary_link_problem(use)
            if problem:
                hits.append(f"{location}: first use of {use.term!r} {problem}")
    return hits


@pytest.mark.parametrize("recipe", guarded("glossary_first_use_links"))
def test_the_first_use_of_a_glossary_term_links_its_entry(recipe):
    """#211, CONTRIBUTING.md section 6 and docs/recipe-template.md "The lexicon": a recipe
    defines a cookbook term the first time its prose uses it and links the glossary entry there.
    Fails on a first use that is bare, that links another target, or whose anchor is missing
    from docs/glossary.md. Per notebook, in notebook order, with the README checked separately.
    Whether the sentence defines the term, and the everyday senses the check does not list,
    stay with the reviewer."""
    hits = _recipe_glossary_link_hits(recipe_dir(recipe))
    assert not hits, "; ".join(hits)


GLOSSARY_LINK = "../../docs/glossary.md#"


def _link(text: str, anchor: str) -> str:
    return f"[{text}]({GLOSSARY_LINK}{anchor})"


def test_every_lexicon_term_has_a_glossary_anchor():
    """The lexicon names the anchors the check demands, so each must exist."""
    assert set(GLOSSARY_LEXICON.values()) <= _glossary_anchors()
    assert {"gold-label", "f1", "confidence-gate", "selective-prediction"} <= _glossary_anchors()


@pytest.mark.parametrize("term", list(GLOSSARY_LEXICON))
def test_a_linked_first_use_passes_and_the_same_use_bare_fails(term):
    anchor = GLOSSARY_LEXICON[term]
    assert _glossary_link_hits(f"We report {_link(term, anchor)} here.", "x") == []
    hits = _glossary_link_hits(f"We report {term} here, precision and recall too.", "x")
    assert any(f"first use of {term!r}" in hit for hit in hits)


def test_an_unlinked_first_use_fails_even_when_a_later_use_is_linked():
    text = f"The gold label comes first.\n\nLater, the {_link('gold label', 'gold-label')} again."
    (hit,) = _glossary_link_hits(text, "README.md")
    assert "first use of 'gold label' is not a link" in hit


def test_a_link_with_the_wrong_anchor_fails():
    (hit,) = _glossary_link_hits(f"The {_link('gold label', 'accuracy')} is the answer.", "x")
    assert "links '../../docs/glossary.md#accuracy', not ../../docs/glossary.md#gold-label" in hit


@pytest.mark.parametrize(
    "href",
    [
        "../docs/glossary.md#gold-label",
        "../../docs/glossary.md",
        "docs/glossary.md#gold-label",
        "../../docs/glossary.md#gold-labels",
        "https://example.com/docs/glossary.md#gold-label",
    ],
)
def test_a_link_to_another_target_fails(href):
    assert _glossary_link_hits(f"The [gold label]({href}) is the answer.", "x")


def test_the_bare_form_of_a_term_and_a_path_is_not_a_link():
    """The shape the first #211 sighting found: the term in a code span, the path beside it as
    plain text, so a reader sees a path and no link."""
    text = "Each is scored against its (`gold label`, ../../docs/glossary.md#gold-label)."
    (hit,) = _glossary_link_hits(text, "x")
    assert "first use of 'gold label' is not a link" in hit


def test_a_code_span_inside_the_link_is_a_linked_use():
    assert _glossary_link_hits(f"Its {_link('`gold label`', 'gold-label')}.", "x") == []


def test_a_later_unlinked_use_is_allowed():
    text = (
        f"The {_link('gold label', 'gold-label')} is the answer.\n\n"
        "A second paragraph names the gold label again, and so does this gold label."
    )
    assert _glossary_link_hits(text, "x") == []


def test_a_term_inside_a_link_to_something_else_is_not_the_glossary_link():
    assert _glossary_link_hits("See [the gold label rules](other.md) for it.", "x")


def test_the_plural_of_a_compound_term_is_the_term():
    assert _glossary_link_hits("The gold labels are fixed.", "x")
    assert _glossary_link_hits(f"The {_link('gold labels', 'gold-label')} are fixed.", "x") == []


@pytest.mark.parametrize(
    "text",
    [
        "## Coverage and risk\n\nNothing else.",
        "```python\ncoverage = 1\n```\n",
        "    accuracy = 1\n",
        'The input reads "a gold label of five stars".',
        "<!-- accuracy -->\n",
        "An unrelated sentence about states and scores.",
    ],
    ids=["heading", "fence", "indented-code", "quoted-fixture", "html", "everyday-state-score"],
)
def test_structure_and_non_prose_are_not_first_uses(text):
    assert _glossary_link_hits(text, "x") == []


@pytest.mark.parametrize(
    ("everyday", "term"),
    [
        ("Read the customer review first.", "review"),
        ("Then we review the answer.", "review"),
        ("There is some risk of a small overage.", "risk"),
        ("Not every sentence would risk a wrong answer.", "risk"),
        ("The test coverage is not the metric.", "coverage"),
        ("A support ticket arrived.", "support"),
        ("Does this passage support the claim?", "support"),
    ],
)
def test_an_everyday_sense_is_not_a_use_but_the_term_beside_it_is(everyday, term):
    assert _glossary_link_hits(everyday, "x") == []
    hits = _glossary_link_hits(f"{everyday} The {term} outcome follows, with precision.", "x")
    assert any(f"first use of {term!r}" in hit for hit in hits)


def test_support_counts_beside_the_metrics_it_is_reported_with():
    hits = _glossary_link_hits("Precision, recall, F1 and support are reported.", "x")
    assert any("'support'" in hit for hit in hits)


def test_f1_is_case_exact_so_a_formula_name_is_not_it():
    assert _glossary_link_hits("The f1 name in prose is not the F1 metric.", "x") != []
    assert _glossary_link_hits("The f1 name only.", "x") == []


@pytest.mark.parametrize(
    "spelling",
    [
        "gold\nlabel",
        "business\nthreshold",
        "confidence\ngate",
        "selective\nprediction",
        "**gold** label",
        "gold **label**",
        "*business threshold*",
        "gold-label",
        "F1-score",
        "macro-F1",
    ],
)
def test_a_term_wrapped_hyphenated_or_split_by_emphasis_is_still_the_term(spelling):
    """A soft line break is a space, emphasis markers are transparent and a hyphen joins the
    words of a compound term, so none of these hides a bare first use."""
    assert _glossary_link_hits(f"Compare each answer with its {spelling} here.", "x")
    anchor = next(
        a
        for t, a in GLOSSARY_LEXICON.items()
        if _TERM_PATTERNS[t].search(spelling.replace("*", ""))
    )
    linked = f"With its [{spelling}]({GLOSSARY_LINK}{anchor}) here."
    assert _glossary_link_hits(linked, "x") == []


def test_a_wrapped_bare_first_use_is_not_excused_by_a_later_link():
    text = f"Its gold\nlabel is first.\n\nLater, the {_link('gold label', 'gold-label')}."
    assert _glossary_link_hits(text, "x")


def test_an_everyday_phrase_split_by_emphasis_is_still_everyday():
    assert _glossary_link_hits("Read the customer **review** first.", "x") == []
    assert _glossary_link_hits('The input is "a **gold label** of five stars".', "x") == []


def test_a_link_ends_a_run_so_text_either_side_is_not_one_term():
    assert _glossary_link_hits("The gold [x](y.md) label here.", "x") == []


def test_support_companions_are_matched_without_regard_to_case():
    hits = _glossary_link_hits("PRECISION and support per class.", "x")
    assert any("'support'" in hit for hit in hits)


def test_an_undefined_anchor_is_reported(monkeypatch):
    monkeypatch.setitem(GLOSSARY_LEXICON, "risk", "no-such-anchor")
    (hit,) = _glossary_link_hits("The risk is low.", "x")
    assert "docs/glossary.md defines no #no-such-anchor anchor" in hit


def _write_notebook(directory: Path, cells: list[str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    body = [
        {"cell_type": "markdown", "id": f"c{i}", "metadata": {}, "source": [source]}
        for i, source in enumerate(cells)
    ]
    (directory / "notebook.ipynb").write_text(json.dumps({"cells": body}), encoding="utf-8")
    return directory


def test_the_notebook_first_use_is_the_first_markdown_cell_in_order(tmp_path):
    linked = f"The {_link('gold label', 'gold-label')} is fixed."
    later = "A later cell says gold label bare."
    assert _recipe_glossary_link_hits(_write_notebook(tmp_path / "a", [linked, later])) == []
    (hit,) = _recipe_glossary_link_hits(_write_notebook(tmp_path / "b", [later, linked]))
    assert "cell c0" in hit
    assert "first use of 'gold label' is not a link" in hit


def test_a_code_cell_is_not_prose(tmp_path):
    cells = [
        {"cell_type": "code", "id": "setup", "metadata": {}, "source": ["# gold label\n"]},
        {"cell_type": "markdown", "id": "md", "metadata": {}, "source": ["Nothing here."]},
    ]
    directory = tmp_path / "recipe"
    directory.mkdir()
    (directory / "notebook.ipynb").write_text(json.dumps({"cells": cells}), encoding="utf-8")
    assert _recipe_glossary_link_hits(directory) == []


def test_the_readme_is_checked_separately_from_the_notebook(tmp_path):
    directory = _write_notebook(tmp_path / "r", [f"The {_link('gold label', 'gold-label')}."])
    (directory / "README.md").write_text("The gold label is the answer.\n", encoding="utf-8")
    (hit,) = _recipe_glossary_link_hits(directory)
    assert hit.startswith("README.md: first use of 'gold label'")


# --- #225: the citation check reads every spelling of "something a reader cannot see" ----------


# Frozen pre-#365 patterns and quote handling, verified against the parent of 85f357b:
# 3553f319ba053ea68164c07896f449267108c66a:tests/test_recipe_guard.py. These are historical
# evidence, not aliases of the current patterns: future vocabulary edits must not rewrite it.
LEGACY_ISSUE_NUMBER = re.compile(r"#\d+\b")
LEGACY_THE_ISSUE = re.compile(r"\bthe issue\b", re.IGNORECASE)
LEGACY_QUOTED = re.compile(r'"[^"\n]*"')


def _legacy_citation_hits(text: str, location: str) -> list[str]:
    """The frozen pre-#365 check, kept as red-before evidence for #225's unreadable pointers."""
    text = LEGACY_QUOTED.sub(" ", text)
    return [
        f"{location}: {m.group(0)!r}"
        for pattern in (LEGACY_ISSUE_NUMBER, LEGACY_THE_ISSUE)
        for m in pattern.finditer(text)
    ]


# Prose that cites a document the reader cannot open, with the shape the message must name. The
# PR-description, wave/batch and rule-number lines are what PR #223 and PR #224 committed with
# every check green; the finding labels are what recipe 37's fix round committed (#225).
_UNREADABLE_CITATIONS = {
    "pr-description": ("the PR description proves against the unmasked run", "pull request"),
    "pr-description-proved": ("proved in the PR description by a mutation", "pull request"),
    "pull-request-description": ("see the pull request description", "pull request"),
    "pull-request-body": ("the pull request body has the numbers", "pull request"),
    "the-pr": ("as the PR says, this is a floor", "pull request"),
    "possessive-pr": ("the PR's description proves it", "pull request"),
    "possessive-pull-request-description": (
        "the pull request's description proves it",
        "pull request",
    ),
    "possessive-pull-request-body": ("the pull-request's body has the mutation", "pull request"),
    "pr-then-pr-curve": ("see the PR, then the PR curve", "pull request"),
    "this-pr": ("this PR changes the gate", "pull request"),
    "wave-and-batch": ("Fixture-generation consistency (Wave 3 batch 1)", "wave or batch"),
    "wave-alone": ("it fixes something a Wave 1 review noted", "wave or batch"),
    "batch-alone": ("the batch 2 sweep moved this", "wave or batch"),
    "rule-capitalised": ("Rule 12: nothing in this file pins the output", "house rule"),
    "rule-lowercase": ("which is what rule 19 is about", "house rule"),
    "rule-of-a-file-that-does-not-exist": ("rule 4 of docs/not-a-file.md", "house rule"),
    "rule-of-a-path-that-climbs-out": ("rule 4 of docs/../CONTRIBUTING.md", "house rule"),
    "rule-of-a-file-not-at-the-root": ("rule 4 of helpers.py", "house rule"),
    "rule-of-a-policy": ("rule 4 of the policy", "house rule"),
    "the-orchestrator": ("the orchestrator asked for this order", "orchestration role"),
    "the-brief": ("as the brief says, keep it short", "orchestration role"),
    "the-reviewers-finding": ("the reviewer's finding was that it is circular", "orchestration"),
    "the-reviewer-found": ("the reviewer found a wrong label here", "orchestration role"),
    "finding-label-m": ("the objective is pinned (M3): a swap that keeps", "review finding label"),
    "finding-label-s": ("a per-domain F1 actually moves (S1): the", "review finding label"),
    "acceptance-criteria": ("what the acceptance criteria call accuracy", "acceptance criteria"),
    "acceptance-criterion": ("the acceptance criterion also asks for it", "acceptance criteria"),
    "review-round": ("after its first review round", "review round"),
    "fix-round": ("in the recipe's first fix round", "review round"),
    "unpublished-recipe-number": ("Rule 11 (recipe 99 lineage)", "not published"),
    "unpublished-recipe-link": ("see ../99-not-a-recipe/ for the shape", "not published"),
    "unpublished-recipe-100": ("the recipe 100 pattern", "not published"),
    "unpublished-recipe-100-link": ("see ../100-not-a-recipe/ for the shape", "not published"),
    "published-number-wrong-slug": ("see ../30-not-a-real-slug/ for the shape", "not published"),
    "rule-of-an-absolute-path": ("rule 4 of /etc/hosts", "house rule"),
}

# Prose that must keep passing: a target that is committed, an identifier the repository itself
# defines, and ordinary words a recipe about review queues or retrieval uses freely.
_READABLE_CITATIONS = {
    "a-committed-section": "CONTRIBUTING.md section 6 forbids it",
    "a-committed-doc": "see docs/evaluation.md for the selection rule",
    "the-guards-own-anchor": "strong-form guard (G1(c)), defined in tests/test_recipe_guard.py",
    "a-defined-requirement-id": "R21 asks for a printed count",
    "a-catalog-source": "TypeSafe's notes on Jev 1.13 (S07) document it",
    "a-numbered-rule-that-names-its-file": "rule 4 of docs/glossary.md says so",
    "a-numbered-rule-in-contributing": "rule 4 in CONTRIBUTING.md says so",
    "a-numbered-rule-capitalised-of": "Rule 4 Of docs/glossary.md says so",
    "a-numbered-rule-of-a-neighbours-readme": (
        "rule 4 of recipes/38-abstention-and-review-queues/README.md says so"
    ),
    "a-numbered-rule-of-the-package": "rule 4 of src/jev_cookbook/evaluation.py says so",
    "a-pr-curve": "the PR curve and PR AUC are reported",
    "the-metric-abbreviated": "precision-recall (PR) curves and precision and recall (PR) at k",
    "pr-auc-hyphenated": "PR-AUC and PR AP, not PR scores",
    "an-acceptance-test": "an acceptance test the customer signs off, and the acceptance tests",
    "a-published-neighbour": "see recipe 30 and ../30-citation-verification/ for the shape",
    "a-human-reviewer": "a reviewer decides what the model could not",
    "reviewers-in-the-queue": "the reviewers who work the review queue see the reason",
    "the-review-queue": "the review queue is the second half of the recipe",
    "a-rule-without-a-number": "a rule of thumb, and the rule the code applies",
    "an-f1-and-r-squared-in-parentheses": "macro F1 (F1) and (R2) are reported",
    "a-batch-and-a-wave": "a batch of tickets and a wave of requests arrive together",
    "a-round-of-play": "round 2 of the game follows round 1",
    "words-that-contain-pr": "the PRIOR and a PROMPT are not pull requests",
    "a-quoted-fixture-line": 'the ticket reads "see PR 12 and rule 7 for the wave 3 batch"',
}


@pytest.mark.parametrize("case", sorted(_UNREADABLE_CITATIONS))
def test_a_citation_of_something_a_reader_cannot_open_is_a_hit(case):
    text, shape = _UNREADABLE_CITATIONS[case]
    hits = _citation_hits(text, "prose")
    assert any(shape in hit for hit in hits), f"{case}: {text!r} -> {hits}"
    # The red-before: none of these spellings is an issue number or "the issue".
    assert _legacy_citation_hits(text, "prose") == [], case


@pytest.mark.parametrize("case", sorted(_READABLE_CITATIONS))
def test_a_citation_a_reader_can_open_is_not_a_hit(case):
    hits = _citation_hits(_READABLE_CITATIONS[case], "prose")
    assert hits == [], f"{case}: {hits}"


def test_the_hit_message_names_the_place_the_shape_and_the_words():
    (hit,) = _citation_hits("see the pull request body", "README.md")
    assert hit == "README.md: 'pull request body' (pull request pointer: a reader cannot open it)"


def test_a_committed_target_is_looked_up_in_the_tree_not_trusted_by_its_spelling():
    # The carve-out is for a rule whose target a reader can open, a tracked regular file; a path-shaped
    # string that names nothing is the same dangling pointer as a bare "rule 4".
    assert _citation_hits("rule 4 of docs/glossary.md", "x") == []
    assert _citation_hits("rule 4 of docs/glossary-of-nothing.md", "x") != []


# #471: every narrowed vocabulary has a must-fail process pointer beside its ordinary use.
# Labels with no explicit ordinary context stay conservative; so do in-fiction rule numbers:
# state/quote the supplied rule itself rather than silently exempting "of the game/policy".
_CITATION_VOCABULARY_PAIRS = {
    "brief-adjective": ("as the brief says, retry", "the brief pause between retries"),
    "brief-delay": ("the brief requires retries", "allow the brief delay before retrying"),
    "routing-actor": (
        "the orchestrator asked for this order",
        "the orchestrator routes each task to a skill",
    ),
    "hardware-label": ("the objective is pinned (M2): a swap", "an (M2) chip"),
    "vitamin-label": ("the finding (B1) needs a fix", "vitamin (B1)"),
    "sample-label": ("the sample (N1): missing evidence", "the sample (N1) of the population"),
    "region-label": ("region (S1): a finding", "region (S1) of the map"),
    "input-batch": ("the batch 3 sweep moved this", "process batch 3 of 5"),
    "pr-roc": ("as the PR says, use the gate", "PR and ROC curves"),
    "pr-number": ("the PR scored the change", "the PR is 0.81"),
    "pr-area": ("the PR pointed to the change", "area under the PR"),
    "pr-points": ("as the PR points out, freeze it", "PR points"),
    "pr-scores": ("this PR scores the change", "PR scores"),
    "pr-metric-boundary": ("the PR plotted the change", "the PR plot"),
    "pr-metric-areas-boundary": ("the PR areaspecific note", "PR areas"),
    "pr-plots-verb": ("this PR plots the new calibration curve", "the PR plots are in the figure"),
    "pr-metrics-subject": ("the PR metrics changed in review", "the PR metrics are reported"),
    "pr-plots-then-object": ("the PR plots a new curve", "the PR plots, the curves and the areas"),
    "per-sample-label": ("per sample (M3)", "the sample (M3) of the batch"),
    "per-region-label": ("per region (S2) the rate", "the region (S2) of the map"),
    "typographic-pull-request": ("the pull request’s description", "the precision-recall curve"),
    "typographic-reviewer": ("the reviewer’s finding", "a reviewer decides uncertain cases"),
    "plural-possessive": ("reviewers' findings", "reviewers in the queue decide cases"),
    "plural-typographic-possessive": ("reviewers’ findings", "the reviewers who work the queue"),
    "pull-request-number": ("pull request 12", "the request contains 12 rows"),
    "repository-relative-recipe": (
        "see ../../recipes/99-not-a-recipe/",
        "see ../../recipes/30-citation-verification/",
    ),
    "repository-relative-wrong-slug": (
        "see ../../recipes/30-wrong-slug/",
        "see ../../recipes/30-citation-verification/README.md",
    ),
    "recipe-number-list": ("recipes 30 and 99", "recipes 28 and 30"),
    "recipe-comma-list": ("recipes 28, 30, and 99", "recipes 28, 30, and 36"),
    "multiple-rule-target": (
        "rules 4 and 5 of docs/missing.md",
        "rules 4 and 5 of docs/glossary.md",
    ),
    "comma-rule-target": (
        "rules 4, 5, and 6 of docs/missing.md",
        "rules 4, 5, and 6 of docs/glossary.md",
    ),
    "orchestration-target": (
        "rule 6 of orchestration/PROMPT.md",
        "rule 6 of CONTRIBUTING.md",
    ),
    "path-case": ("rule 4 of docs/GLOSSARY.md", "rule 4 of docs/glossary.md"),
    "directory-target": (
        "rule 4 of recipes/16-discord-moderation-triage",
        "rule 4 of recipes/16-discord-moderation-triage/README.md",
    ),
    "fictional-game-rule": ("rule 2 of the game", 'the game says "rule 2: take one card"'),
    "fictional-server-rule": (
        "rule 3 of the server's rules",
        'the server says "rule 3: keep messages civil"',
    ),
    "ambiguous-review-label": ("the outcome (N1) follows", "the sample (N1) of the population"),
}


@pytest.mark.parametrize("case", sorted(_CITATION_VOCABULARY_PAIRS))
def test_citation_vocabulary_pairs_keep_process_pointers_and_allow_ordinary_prose(case):
    must_fail, must_pass = _CITATION_VOCABULARY_PAIRS[case]
    assert _citation_hits(must_fail, "prose"), (case, must_fail)
    assert _citation_hits(must_pass, "prose") == [], (case, must_pass)


@pytest.mark.parametrize(
    "sentence",
    [
        "this PR plots the new calibration curve",
        "the PR metrics changed in review",
        "The PR plots a curve for each domain.",
        "the PR metrics moved after the last change",
        "recall (PR) plots show the gap but this PR plots the fix",
        "the PR plots the curve",
        "the PR metrics improved",
        "the PR metrics improved after calibration",
        "the PR metrics look similar",
        "the PR plots-based review",
        "the PR plots illustrate the trade-off",
        "this PR metrics the run",
    ],
)
def test_a_pr_metric_word_in_the_plural_is_a_pointer_when_a_predicate_follows(sentence):
    """#639 item 1: "plots" and "metrics" are also a verb and a verb's subject."""
    hits = _citation_hits(sentence, "prose")
    assert hits and all("pull request pointer" in hit for hit in hits), hits


@pytest.mark.parametrize(
    "sentence",
    [
        "the PR plots",
        "the PR metrics.",
        "the PR plots, the PR metrics and PR curves",
        "the PR metrics are reported",
        "the PR plots were drawn from the validation split",
        "the PR metrics for each domain",
        "PR metrics of the run",
        "the PR plots and the ROC curves",
        "recall (PR) plots show the gap",
        "the PR plots in Figure 2 show the gap",
        "the PR metrics in the table",
        "the PR metrics in table 2",
        "the PR plots under each threshold",
        "PR metrics to compare models",
        "the PR metrics to report",
        "the PR metrics below",
        "the PR plots above",
        "the PR metrics into a dashboard",
        "the PR plots against the baseline",
        "the PR plots as a pair",
        "the PR metrics than the ROC metrics",
        "the PR plots within each domain",
        "the PR metrics between runs",
        "the PR metrics but not ROC",
        "the PR metrics nor the ROC metrics",
        "PR metrics (precision and recall)",
        "the PR plots \u2014 see the appendix",
        "the PR plots\u2014see the appendix",
        "the PR plots \u2013 see the appendix",
        "the PR metrics -- see the table",
        "the PR metrics - see the table",
        "precision-recall (PR) plots in the appendix",
        "precision-recall (PR) plots illustrate the trade-off",
        "precision and recall (PR) metrics improved after calibration",
    ],
)
def test_a_pr_metric_word_in_the_plural_stays_a_metric_in_noun_position(sentence):
    # The decision recorded for #639 item 1: the plural is read as the metric after the spelled-out
    # "precision-recall (PR)", or when the next word is the end of the clause, punctuation, a
    # preposition, a conjunction, a copula or show(s). "the PR metrics are in the description"
    # therefore still passes. Determiners and ordinary verbs after the plural stay pointers.
    assert _citation_hits(sentence, "prose") == []


@pytest.mark.parametrize(
    "sentence",
    [
        "per sample (M3)",
        "each sample (S2) is scored",
        "per sample (B1), the rate",
        "region (N4) changed",
        "per region (S1)",
        "the sample (M3) was flagged",
    ],
)
def test_a_sample_or_region_label_needs_of_to_be_ordinary_notation(sentence):
    """#639 item 2: the exemption is for "sample (N1) of the population", not any label that
    follows the word sample or region."""
    hits = _citation_hits(sentence, "prose")
    assert hits and all("review finding label" in hit for hit in hits), hits


@pytest.mark.parametrize(
    "sentence",
    [
        "the sample (N1) of the population",
        "a sample (M3) Of the batch",
        "region (S1) of the map",
        "vitamin (B1)",
    ],
)
def test_a_sample_or_region_label_with_of_stays_ordinary_notation(sentence):
    assert _citation_hits(sentence, "prose") == []
    # a colon or dash after the label is still a finding, with or without "of"
    assert _citation_hits(sentence.replace(")", "):", 1), "prose")


def test_rule_n_of_license_is_pinned_bare_does_not_qualify_but_a_code_span_does():
    """#639 item 3. ``LICENSE`` is the one tracked regular file at the repository root with no
    dot in its name, so it is a committed file a reader can open. Decision: the bare token
    ``rule 4 of LICENSE`` does NOT qualify, because a bare dotless token cannot be told from an
    English noun ("rule 4 of the policy"), and the licence text has no numbered rules to cite.
    The same file named in a code span or a Markdown link still names a tracked regular file and
    does qualify. If the bare-path rule that a path contains ``.`` or ``/`` is removed, the first
    assertions below fail."""
    tracked = _tracked_regular_files(REPO)
    assert "LICENSE" in tracked
    assert [name for name in tracked if "/" not in name and "." not in name] == ["LICENSE"]
    assert _citation_hits("rule 4 of LICENSE", "prose") == [
        "prose: 'rule 4' (house rule number: a reader cannot open it; name a case-exact "
        "git-tracked regular file outside orchestration/ using a repository-root-relative "
        "path or a Markdown link relative to this file)"
    ]
    assert _citation_hits("rule 4 in LICENSE says so.", "prose")
    assert _citation_hits("rule 4 of `LICENSE`", "prose") == []
    source = REPO / "recipes" / "_template" / "README.md"
    assert _citation_hits("rule 4 of [the licence](../../LICENSE)", "prose", source) == []
    # a dotless name that is not tracked never qualifies in any spelling
    assert _citation_hits("rule 4 of `LICENCE`", "prose")


@pytest.mark.parametrize(
    "text,numbers",
    [
        ("recipes 30 and 99", [99]),
        ("recipes 99 and 30", [99]),
        ("recipes 30, 99, and 100", [99, 100]),
        ("recipes 99 or 100", [99, 100]),
        ("recipes 30 & 99", [99]),
    ],
)
def test_citation_recipe_lists_check_every_number(text, numbers):
    hits = _citation_hits(text, "prose")
    assert len(hits) == len(numbers), hits
    assert all(any(f"recipe {number} " in hit for hit in hits) for number in numbers), hits


@pytest.mark.parametrize(
    "target,passes",
    [
        ("[the glossary](../../docs/glossary.md)", True),
        ("[the glossary](../../docs/glossary.md#state)", True),
        ("[a neighbour](../30-citation-verification/README.md)", True),
        ("[the glossary](../../docs/GLOSSARY.md)", False),
        ("[missing](../../docs/missing.md)", False),
        ("[a directory](../../docs/)", False),
        ("[the brief](../../orchestration/PROMPT.md)", False),
        ("[the brief](../../docs/../orchestration/PROMPT.md)", False),
        ("[outside](../../../CONTRIBUTING.md)", False),
        ("[absolute](/docs/glossary.md)", False),
        ("[remote](https://example.invalid/docs/glossary.md)", False),
        ("[escaped](../../docs/%67lossary.md)", False),
        ("[query](../../docs/glossary.md?raw=1)", False),
    ],
)
def test_citation_rule_targets_accept_safe_rendered_links(target, passes):
    source = REPO / "recipes/_template/README.md"
    hits = _citation_hits(f"rules 4 and 5 of {target}", "README.md", source)
    assert (hits == []) is passes, hits


def test_citation_rule_links_resolve_from_the_actual_source_file():
    prose = "rule 4 of [the glossary](../../../docs/glossary.md)"
    assert (
        _citation_hits(prose, "tests/test_helpers.py", REPO / "recipes/_template/tests/t.py") == []
    )
    assert _citation_hits(prose, "README.md", REPO / "recipes/_template/README.md")
    assert _citation_hits(prose, "unknown source")


def test_citation_rule_target_message_explains_both_path_spellings():
    (hit,) = _citation_hits("rule 4 of helpers.py", "README.md")
    assert "git-tracked regular file" in hit
    assert "repository-root-relative path" in hit
    assert "Markdown link relative to this file" in hit


def test_citation_git_index_requires_exact_regular_stage_zero_paths(monkeypatch, tmp_path):
    def git_index(command, **kwargs):
        assert command == ["git", "-C", str(tmp_path), "ls-files", "--stage", "-z"]
        assert kwargs == {"check": True, "capture_output": True}
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                b"100644 aaaa 0\tdocs/glossary.md\0"
                b"100755 bbbb 0\ttools/run.sh\0"
                b"120000 cccc 0\tdocs/link.md\0"
                b"160000 dddd 0\tmodule\0"
                b"100644 eeee 2\tdocs/conflict.md\0"
            ),
        )

    monkeypatch.setattr(subprocess, "run", git_index)
    assert _tracked_regular_files(tmp_path) == frozenset({"docs/glossary.md", "tools/run.sh"})
    _tracked_regular_files.cache_clear()


@pytest.mark.parametrize("target", ["docs/untracked.md", "ignored.md", "docs/GLOSSARY.md", "docs"])
def test_citation_rule_targets_reject_local_untracked_ignored_or_case_wrong_paths(
    monkeypatch, tmp_path, target
):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/glossary.md").write_text("Tracked document", "utf-8")
    if target != "docs":
        (tmp_path / target).write_text("Local file", "utf-8")
    monkeypatch.setitem(globals(), "REPO", tmp_path)
    monkeypatch.setitem(
        globals(), "_tracked_regular_files", lambda repo: frozenset({"docs/glossary.md"})
    )
    assert _citation_hits("rule 4 of docs/glossary.md", "prose") == []
    assert _citation_hits(f"rule 4 of {target}", "prose")


@pytest.mark.parametrize("symlink", ["docs/glossary.md", "docs"])
def test_citation_rule_targets_reject_worktree_symlinks(monkeypatch, tmp_path, symlink):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/glossary.md").write_text("Tracked document", "utf-8")
    monkeypatch.setitem(globals(), "REPO", tmp_path)
    monkeypatch.setitem(
        globals(), "_tracked_regular_files", lambda repo: frozenset({"docs/glossary.md"})
    )
    assert _citation_hits("rule 4 of docs/glossary.md", "prose") == []
    # Model an index-tracked regular file replaced by a symlink in the working tree. This
    # avoids depending on host symlink permissions while testing both final and parent paths.
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == tmp_path / symlink)
    assert _citation_hits("rule 4 of docs/glossary.md", "prose")


def test_citation_git_lookup_failure_is_not_an_empty_allowlist(monkeypatch, tmp_path):
    def failed_git(command, **kwargs):
        raise subprocess.CalledProcessError(128, command)

    monkeypatch.setattr(subprocess, "run", failed_git)
    with pytest.raises(subprocess.CalledProcessError):
        _tracked_regular_files(tmp_path)


# #471 fix round: regressions against rejected tree 672f8e3212245d3d6e44abcb0481740923e112cf.
# Preserve the original Unicode-decimal coverage and punctuation spellings, and keep ordinary
# adjective nouns distinct from briefs that impose requirements through a verb.
_CITATION_NO_LOOSENING_PAIRS = {
    "fullwidth-wave": ("wave ３", 'the fixture says "wave ３"'),
    "arabic-wave": ("wave ٣", 'the fixture says "wave ٣"'),
    "fullwidth-rule": ("rule ６", "rule ６ of docs/glossary.md"),
    "arabic-rule": ("rule ٦", "rule ٦ of docs/glossary.md"),
    "fullwidth-recipe": ("recipe ９９", "recipe ３０"),
    "arabic-recipe": ("recipe ٩٩", "recipe ٣٠"),
    "mixed-fullwidth-list": ("recipes 30 and ９９", "recipes 30 and ２８"),
    "mixed-arabic-list": ("recipes 30 and ٩٩", "recipes 30 and ٢٨"),
    "unicode-batch-input": ("batch ３", "process batch ３ of ５"),
    "bare-slug-period": ("see ../99-not-a-recipe.", "see ../30-citation-verification."),
    "bare-slug-backticks": ("see `../99-not-a-recipe`", "see `../30-citation-verification`"),
    "repository-slug-period": (
        "see ../../recipes/99-not-a-recipe.",
        "see ../../recipes/30-citation-verification.",
    ),
    "slug-filename-prefix": (
        "see ../30-citation-verification.md.",
        "see ../30-citation-verification.",
    ),
    "slug-underscore-prefix": (
        "see `../30-citation-verification_missing`",
        "see `../30-citation-verification`",
    ),
    "slug-uppercase-prefix": (
        "see `../30-citation-verificationMissing`",
        "see `../30-citation-verification`",
    ),
    "slug-hyphen-prefix": (
        "see `../30-citation-verification-`",
        "see `../30-citation-verification`",
    ),
    "wrong-slug-period": ("see ../30-wrong-slug.", "see ../30-citation-verification."),
    "repository-slug-backticks": (
        "see `../../recipes/99-not-a-recipe`",
        "see `../../recipes/30-citation-verification`",
    ),
    "brief-delays-verb": (
        "the brief delays release until approval",
        "allow the brief delay before retrying",
    ),
    "brief-pauses-verb": (
        "the brief pauses execution until approval",
        "the brief pause between retries",
    ),
    "brief-waits-verb": ("the brief waits for approval", "the brief wait between retries"),
}


@pytest.mark.parametrize("case", sorted(_CITATION_NO_LOOSENING_PAIRS))
def test_citation_fix_round_preserves_prior_detections(case):
    must_fail, must_pass = _CITATION_NO_LOOSENING_PAIRS[case]
    assert _citation_hits(must_fail, "prose"), (case, must_fail)
    assert _citation_hits(must_pass, "prose") == [], (case, must_pass)


@pytest.mark.parametrize("suffix", ["?raw=1", "%2Fmissing", "\\missing", "/missing"])
@pytest.mark.parametrize("spelling", ["bare", "backticked", "rendered"])
def test_citation_rule_target_checks_the_complete_token(suffix, spelling):
    path = f"docs/glossary.md{suffix}"
    if spelling == "backticked":
        target = f"`{path}`"
        valid_target = "`docs/glossary.md`"
    elif spelling == "rendered":
        target = f"[the glossary](../../{path})"
        valid_target = "[the glossary](../../docs/glossary.md)"
    else:
        target = path
        valid_target = "docs/glossary.md"
    source = REPO / "recipes/_template/README.md"
    assert _citation_hits(f"rule 4 of {target}", "prose", source)
    assert _citation_hits(f"rule 4 of {valid_target}", "prose", source) == []


@pytest.mark.parametrize("punctuation", [".", ",", ";", ":", "!", "?", ")", "]"])
def test_citation_rule_target_preserves_sentence_punctuation(punctuation):
    assert _citation_hits(f"See rule 4 of docs/glossary.md{punctuation}", "prose") == []
    assert _citation_hits(f"See rule 4 of `docs/glossary.md`{punctuation}", "prose") == []


# #471 fix round 2: Markdown wrappers are prose formatting, while punctuation in literal
# destinations and actual folder segments is part of the path and must match exactly.
@pytest.mark.parametrize("marker", ["*", "**", "_", "__"])
@pytest.mark.parametrize("prefix", ["../", "../../recipes/"])
@pytest.mark.parametrize("slash", ["", "/"])
def test_citation_recipe_emphasis_preserves_published_and_unpublished_paths(marker, prefix, slash):
    published = f"see {marker}{prefix}30-citation-verification{slash}{marker}."
    unpublished = f"see {marker}{prefix}99-not-a-recipe{slash}{marker}."
    assert _citation_hits(published, "prose") == [], published
    assert _citation_hits(unpublished, "prose"), unpublished


@pytest.mark.parametrize("prefix", ["../", "../../recipes/"])
@pytest.mark.parametrize("punctuation", [".", "…"])
@pytest.mark.parametrize("form", ["rendered", "backticked", "directory", "file-in-directory"])
def test_citation_recipe_literal_folder_punctuation_is_not_sentence_punctuation(
    prefix, punctuation, form
):
    valid = f"{prefix}30-citation-verification"
    invalid = f"{valid}{punctuation}"
    if form == "rendered":
        valid, invalid = f"[next]({valid})", f"[next]({invalid})"
    elif form == "backticked":
        valid, invalid = f"`{valid}`", f"`{invalid}`"
    elif form == "directory":
        valid, invalid = f"{valid}/", f"{invalid}/"
    else:
        valid, invalid = f"[next]({valid}/README.md)", f"[next]({invalid}/README.md)"
    assert _citation_hits(f"see {valid}", "prose") == [], valid
    assert _citation_hits(f"see {invalid}", "prose"), invalid
    assert _citation_hits(f"see {prefix}30-citation-verification{punctuation}", "prose") == []


@pytest.mark.parametrize("suffix", ["_missing", ".md", "Missing", "-", "."])
@pytest.mark.parametrize("marker", ["*", "**", "_", "__"])
def test_citation_recipe_emphasis_does_not_hide_a_wrong_folder_suffix(suffix, marker):
    valid = f"{marker}../30-citation-verification{marker}."
    invalid = f"{marker}../30-citation-verification{suffix}/{marker}."
    assert _citation_hits(valid, "prose") == []
    assert _citation_hits(invalid, "prose"), invalid


# #472: keep the historical red-before control independent of the current vocabulary and
# quote policy. Expected hits below are literals from the frozen pre-#365 implementation.
@pytest.mark.parametrize(
    "text,expected",
    [
        ("#12 then #34", ["prose: '#12'", "prose: '#34'"]),
        ("The Issue and the issue", ["prose: 'The Issue'", "prose: 'the issue'"]),
        ('fixture "#12 the issue"', []),
        ("#12 and the issue", ["prose: '#12'", "prose: 'the issue'"]),
        ("the PR description and rule 4", []),
        ('"#12\nthe issue"', ["prose: '#12'", "prose: 'the issue'"]),
    ],
)
def test_legacy_citation_control_keeps_frozen_verdicts(text, expected):
    assert _legacy_citation_hits(text, "prose") == expected


@pytest.mark.parametrize("name", ["ISSUE_NUMBER", "THE_ISSUE", "QUOTED", "_strip_quoted"])
def test_legacy_citation_control_ignores_current_pattern_and_quote_mutations(monkeypatch, name):
    text = '#12 and the issue; fixture "#99 the issue"'
    expected = ["prose: '#12'", "prose: 'the issue'"]
    current_hits = _citation_hits(text, "prose")
    replacements = {
        "ISSUE_NUMBER": re.compile(r"(?!)"),
        "THE_ISSUE": re.compile(r"(?!)"),
        "QUOTED": re.compile(r".+", re.DOTALL),
        "_strip_quoted": lambda text: "",
    }
    monkeypatch.setitem(globals(), name, replacements[name])
    assert _legacy_citation_hits(text, "prose") == expected
    assert _citation_hits(text, "prose") != current_hits


def test_legacy_citation_patterns_are_frozen_literals_not_aliases_of_the_current_ones():
    # Rebinding a current name in a test cannot reach an alias taken at import time, so the
    # monkeypatch control above cannot see one: pin the frozen text and how it is defined.
    frozen = {
        LEGACY_ISSUE_NUMBER: (r"#\d+\b", 0),
        LEGACY_THE_ISSUE: (r"\bthe issue\b", re.IGNORECASE),
        LEGACY_QUOTED: (r'"[^"\n]*"', 0),
    }
    for pattern, (text, flags) in frozen.items():
        assert (pattern.pattern, pattern.flags & ~re.UNICODE) == (text, flags)
    # re.compile caches by literal, so identity cannot tell an alias from a copy: read the source.
    defined = {
        node.targets[0].id: node.value
        for node in ast.parse(Path(__file__).read_text("utf-8")).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    for name in ("LEGACY_ISSUE_NUMBER", "LEGACY_THE_ISSUE", "LEGACY_QUOTED"):
        value = defined[name]
        assert isinstance(value, ast.Call) and ast.unparse(value.func) == "re.compile", name


@pytest.mark.parametrize("allowed", [False, True])
def test_citation_patterns_dispatch_their_own_allow_function(monkeypatch, allowed):
    calls = []
    source = REPO / "recipes/_template/README.md"

    def allow(text, match, source_path):
        calls.append((text, match.group(), source_path))
        return allowed

    monkeypatch.setitem(
        globals(),
        "PROCESS_CITATIONS",
        {
            "synthetic pointer": CitationPattern(
                re.compile(r"\bmarker\b"), allow, "synthetic reason"
            )
        },
    )
    hits = _citation_hits("a marker", "prose", source)
    assert calls == [("a marker", "marker", source)]
    assert hits == ([] if allowed else ["prose: 'marker' (synthetic pointer: synthetic reason)"])


def test_citation_publication_inventory_is_a_frozen_module_snapshot(monkeypatch):
    assert isinstance(PUBLISHED_NUMBERS, frozenset)
    assert isinstance(PUBLISHED_SLUGS, frozenset)
    # Derived from the catalog directly, not from PUBLISHED: the scope-registration rule bars
    # a bare PUBLISHED reference outside the registered definitions.
    on_disk = [r["slug"] for r in CATALOG["recipes"] if _is_published(r)]
    assert PUBLISHED_NUMBERS == frozenset(int(slug.split("-", 1)[0]) for slug in on_disk)
    assert PUBLISHED_SLUGS == frozenset(on_disk)
    # Scanning a file/cell must use the snapshot instead of iterating the catalog again.
    monkeypatch.setitem(globals(), "PUBLISHED", None)
    assert _citation_hits("recipe 30 and ../30-citation-verification/", "prose") == []
    assert _citation_hits("recipe 99 and ../99-missing/", "prose")
    assert RECIPE_SLUG_LINK.groups == 1


# The same spelling in each place the check reads: a comment or docstring in a .py file, the
# README, a markdown cell and a code cell's comment all count.
_PLANT = "see the PR description"


def _append_code_cell(folder: Path, source: str, cell_id: str = "honesty-probe") -> None:
    path = folder / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    notebook["cells"].append(
        {
            "cell_type": "code",
            "id": cell_id,
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": source.splitlines(keepends=True),
        }
    )
    path.write_text(json.dumps(notebook), "utf-8")


def _plant_a_pull_request_pointer(folder: Path, where: str) -> None:
    if where in ("README.md", "helpers.py", "build_fixtures.py", "tests/test_helpers.py"):
        path = folder / where
        line = _PLANT if where == "README.md" else f"# {_PLANT}"
        path.write_text(path.read_text("utf-8") + f"\n{line}\n", "utf-8")
    elif where == "markdown cell":
        _append_cell(folder, "markdown", _PLANT)
    else:
        assert where == "code cell comment"
        _append_code_cell(folder, f"# {_PLANT}\nx = 1\n")


@pytest.mark.parametrize(
    "where",
    [
        "README.md",
        "helpers.py",
        "build_fixtures.py",
        "tests/test_helpers.py",
        "markdown cell",
        "code cell comment",
    ],
)
def test_a_pull_request_pointer_is_found_wherever_the_check_reads(tmp_path, where):
    folder = _copy_recipe(tmp_path, "_template")
    assert _recipe_citation_hits(folder) == []
    _plant_a_pull_request_pointer(folder, where)
    hits = _recipe_citation_hits(folder)
    assert len(hits) == 1 and "pull request pointer" in hits[0], hits
    named = where if where.endswith((".md", ".py")) else "honesty-probe"
    assert named in hits[0], hits


def test_prose_in_a_string_literal_is_fixture_data_not_a_citation(tmp_path):
    # Unchanged by #225: a fabricated "PR 12" or "Wave 3" inside a fixture row is in-fiction text.
    folder = _copy_recipe(tmp_path, "_template")
    _append_code_cell(folder, 'ROW = "see the PR description for the Wave 3 rule 11"\n')
    assert _recipe_citation_hits(folder) == []


def test_a_recipe_that_cites_an_unpublished_recipe_fails_where_a_published_one_passes(tmp_path):
    folder = _copy_recipe(tmp_path, "_template")
    published = "Same shape as [recipe 30](../30-citation-verification/)."
    _append_cell(folder, "markdown", published)
    assert _recipe_citation_hits(folder) == []
    _append_cell(folder, "markdown", "Rule 11 (recipe 99 lineage).", cell_id="lineage")
    hits = _recipe_citation_hits(folder)
    assert any("not published" in h and "lineage" in h for h in hits), hits


# --- #250: the cell-id check ---------------------------------------------------------------------

_CELL_ID_CASES_THAT_FAIL = {
    "the-cell-below": "The `python-rule` cell below freezes the gate.",
    "as-it-shows": "As `python-rule` shows, nothing moves.",
    "in-a-list-item": "- Rerun `evaluation-validation` and compare.",
    "in-bold": "**`python-rule`** is the cell to change.",
    "two-in-one-sentence": "Rerun `evaluation-test` and `evaluation-validation` afterward.",
}
_CELL_ID_CASES_THAT_PASS = {
    "a-single-word-id": "The `state` cell below builds the store.",
    "another-single-word-id": "Run the `setup` cell first.",
    "unbackticked": "The python-rule cell below freezes the gate.",
    "not-the-whole-span": "Set `python-rule-2` or `my.python-rule` and see.",
    "a-hyphenated-token-that-is-no-cell": "The label `needs-review` is the review value.",
    "a-heading-instead": 'Change it in the cell under "Python\'s part" that prints the gate.',
    # A backticked span INSIDE a fence: only the fence strip keeps these from being hits (the same
    # text outside a fence is "the-cell-below" in the cases that fail).
    "inside-a-backtick-fence": "```text\nthe `python-rule` cell\n```",
    "inside-a-tilde-fence": "~~~\nthe `python-rule` cell below\n~~~",
    "a-quoted-lookup-not-backticked": 'The tests find it with c.get("id") == "python-rule".',
}


@pytest.mark.parametrize("where", ["markdown cell", "README.md"])
@pytest.mark.parametrize("case", sorted(_CELL_ID_CASES_THAT_FAIL))
def test_a_cited_hyphenated_cell_id_fails(tmp_path, case, where):
    folder = _copy_recipe(tmp_path, "_template")
    assert {"python-rule", "evaluation-validation", "evaluation-test"} <= _hyphenated_cell_ids(
        folder
    )
    assert _recipe_cell_id_citations(folder) == []
    text = _CELL_ID_CASES_THAT_FAIL[case]
    if where == "README.md":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + text + "\n", "utf-8")
    else:
        _append_cell(folder, "markdown", text)
    hits = _recipe_cell_id_citations(folder)
    assert hits, f"{case}: nothing noticed"
    # Every cited id is reported, not only the first one in the sentence.
    cited = re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", text)
    assert len(hits) == len(cited) and all(any(i in h for h in hits) for i in cited), hits
    assert all(("README.md" if where == "README.md" else "honesty-probe") in h for h in hits)


@pytest.mark.parametrize("where", ["markdown cell", "README.md"])
@pytest.mark.parametrize("case", sorted(_CELL_ID_CASES_THAT_PASS))
def test_prose_that_is_not_a_hyphenated_cell_id_citation_passes(tmp_path, case, where):
    folder = _copy_recipe(tmp_path, "_template")
    text = _CELL_ID_CASES_THAT_PASS[case]
    if where == "README.md":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + text + "\n", "utf-8")
    else:
        _append_cell(folder, "markdown", text)
    assert _recipe_cell_id_citations(folder) == [], case


def test_single_word_ids_are_not_checked_because_they_are_english(tmp_path):
    # The negative #250 asks for, so that a future strengthening cannot bring the noise back: the
    # template has the ids `state`, `setup`, `answer` and `questions`, and prose backticks them.
    folder = _copy_recipe(tmp_path, "_template")
    all_ids = {c["id"] for c in notebook_cells(folder)}
    assert {"state", "setup", "answer", "questions"} <= all_ids
    assert not ({"state", "setup", "answer", "questions"} & _hyphenated_cell_ids(folder))
    _append_cell(
        folder, "markdown", "The `state` and `answer` cells use the `setup` and `questions` ones."
    )
    assert _recipe_cell_id_citations(folder) == []


def test_a_cell_id_in_code_and_in_a_test_lookup_is_machinery_not_a_citation(tmp_path):
    folder = _copy_recipe(tmp_path, "_template")
    _append_code_cell(folder, "# the `python-rule` cell sets this\nx = 1\n")
    lookup = '\n\ndef test_the_rule_cell_exists(cells):\n    assert any(c.get("id") == "python-rule" for c in cells)\n'
    path = folder / "tests" / "test_helpers.py"
    path.write_text(path.read_text("utf-8") + lookup, "utf-8")
    assert _recipe_cell_id_citations(folder) == []


def test_cell_id_citation_scan_reads_the_notebook_once(monkeypatch, tmp_path):
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", "Run `python-rule` below.")
    original = notebook_cells
    reads = []

    def counted(recipe_path):
        reads.append(recipe_path)
        return original(recipe_path)

    monkeypatch.setitem(globals(), "notebook_cells", counted)
    hits = _recipe_cell_id_citations(folder)
    assert reads == [folder]
    assert len(hits) == 1 and "`python-rule`" in hits[0], hits


def test_cell_id_helper_uses_even_an_empty_parsed_cell_list(monkeypatch, tmp_path):
    def forbidden_read(recipe_path):
        raise AssertionError("already parsed cells must not trigger another notebook read")

    monkeypatch.setitem(globals(), "notebook_cells", forbidden_read)
    assert _hyphenated_cell_ids(tmp_path, cells=[]) == set()


def test_a_cell_id_of_another_notebook_is_not_this_notebooks_citation(tmp_path):
    folder = _copy_recipe(tmp_path, "_template")
    assert "evaluation-curve" not in {c["id"] for c in notebook_cells(folder)}
    _append_cell(folder, "markdown", "Recipe 28's `evaluation-curve` cell prints the sweep.")
    assert _recipe_cell_id_citations(folder) == []


def test_the_citations_recipe_17_carried_are_found_where_they_were_written(tmp_path):
    """#250's first instance, put back by hand into a copy of recipe 17: the paragraph that said
    ``selective-discuss`` and the next-steps item that said the ``python-rule`` cell."""
    folder = _copy_recipe(tmp_path, "17-passage-reranking")
    assert _recipe_cell_id_citations(folder) == []
    _edit_markdown(
        folder,
        'The paragraph beginning "At this gate" in "Evaluation" already said',
        "`selective-discuss` already said",
    )
    _edit_markdown(
        folder,
        'in the cell under "Python\'s part" that prints `chosen confidence gate, frozen from here on` (',
        'in the `python-rule` cell, under "Python\'s part" (',
    )
    hits = _recipe_cell_id_citations(folder)
    assert len(hits) == 2, hits
    assert "ranking-discuss" in hits[0] and "`selective-discuss`" in hits[0]
    assert "next-md" in hits[1] and "`python-rule`" in hits[1]


@pytest.mark.parametrize(
    "text,expected_count",
    [
        (" ```text\n`python-rule`\n ```", 0),
        ("  ~~~text\n`python-rule`\n  ~~~", 0),
        ("   ```text\n`python-rule`\n   ```", 0),
        ("````text\n`python-rule`\n`````", 0),
        ("~~~~text\n`python-rule`\n~~~~~", 0),
        ("````\n```\n`python-rule`\n````", 0),
        ("~~~\n```\n`python-rule`\n~~~", 0),
        ("```\n```text\n`python-rule`\n```", 0),
        ("```text\n`python-rule`", 0),
        ("    ```text\n`python-rule`\n    ```", 1),
        ("before ```text\n`python-rule`", 1),
        ("```py`tag`\n`python-rule`", 1),
        ("`python-rule`\n~~~\n`python-rule`\n~~~\n`python-rule`", 2),
    ],
)
def test_cell_id_citations_follow_shared_commonmark_fence_edges(text, expected_count):
    hits = _cell_id_citations(text, {"python-rule"}, "prose")
    assert len(hits) == expected_count, hits
    assert all("`python-rule`" in hit for hit in hits)


def test_cell_id_citations_use_the_scope_tools_fence_parser(monkeypatch):
    module = sys.modules[without_code_fences.__module__]
    assert Path(module.__file__).resolve() == REPO / "tools/check_recipe_scope.py"
    assert without_code_fences is module.without_code_fences
    calls = []

    def fenced(text):
        calls.append(text)
        return ""

    monkeypatch.setitem(globals(), "without_code_fences", fenced)
    assert _cell_id_citations("`python-rule`", {"python-rule"}, "prose") == []
    assert calls == ["`python-rule`"]


# --------------------------------------------------------------------------------------------
# check 3: test_stored_answers_are_not_all_right is the strong form
# --------------------------------------------------------------------------------------------

STRONG_FORM_DEF = "def test_stored_answers_are_not_all_right"
# The confidence gate is preferred over a plain business threshold when a recipe's test
# re-derives both (recipe 15: a Noul business threshold by F1, then a separate confidence gate):
# G1(c) is about the *confidence* gate specifically, and re.search returns the leftmost match, so
# naming the gate pattern first keeps a recipe's earlier, unrelated "threshold = select_threshold(
# ...)" business-threshold line from being picked up as if it were the gate.
CONFIDENCE_GATE_ASSIGN = re.compile(r"(\w+)\s*=\s*select_confidence_threshold\(")
PLAIN_THRESHOLD_ASSIGN = re.compile(r"(\w+)\s*=\s*select_threshold\(")


def _find_function_body(source: str, def_line: str) -> str | None:
    """``source`` from ``def_line`` to the next top-level decorator, ``def`` or ``class``, or EOF.
    ``None`` if ``def_line`` is not in ``source``.

    The scan stops at a decorator as well as a definition (#272): a decorator line is neither
    ``def `` nor ``class ``, so a decorated neighbour (``@pytest.mark.parametrize`` on the very
    next test function, the common case here) used to be folded into the extracted body, and
    ``ast.parse`` of the result then raised a ``SyntaxError`` about a line the recipe's author
    never wrote, in a function this check does not audit. Only a decorator at column zero ends
    the scan: an indented ``@`` (a nested function's or a class body's own decorator, inside the
    audited body) is part of the body and must not cut it short. Like the ``def``/``class``
    stop, this is a text scan: a column-zero ``@``/``def ``/``class `` inside a multi-line
    string literal in the audited function would also end it."""
    idx = source.find(def_line)
    if idx == -1:
        return None
    rest = source[idx:]
    body = rest[len(def_line) :]
    next_def = re.search(r"\n(?:@|def |class )", body)
    return def_line + (body[: next_def.start()] if next_def else body)


def _shared_selector_imports(trees: list[ast.AST]) -> dict[str, str]:
    """``{local name: real name}`` for ``select_confidence_threshold``/``select_threshold``
    imported from ``jev_cookbook.evaluation`` (the shared helper), across ``trees``, less any
    local name those trees also define or rebind themselves: a recipe's own
    ``def select_confidence_threshold(...)`` that returns a constant is a look-alike, not the
    shared helper, and must not be credited as one (#282). ``from jev_cookbook.evaluation
    import select_confidence_threshold as pick`` is credited under ``pick``."""
    imported: dict[str, str] = {}
    rebound: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "jev_cookbook.evaluation"
                and node.level == 0
            ):
                for alias in node.names:
                    if alias.name in THRESHOLD_OBJECTIVE_SPELLINGS:
                        imported[alias.asname or alias.name] = alias.name
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                rebound.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    rebound |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
    return {local: real for local, real in imported.items() if local not in rebound}


def _threshold_selecting_helpers(helpers_path: Path) -> dict[str, frozenset[str]]:
    """``{function name: the shared threshold functions it reaches}`` for every function in a
    recipe's own ``helpers.py`` that selects a threshold, directly (a call to
    ``select_confidence_threshold``/``select_threshold`` imported from the shared helper) or
    through another function of the same module that does (a wrapper around a wrapper). Name-
    based and call-graph only: a function that merely returns a number, or that happens to share
    a name with one that selects, is not in the result unless it really reaches the shared call.
    An unreadable or unparseable ``helpers.py`` has none."""
    try:
        tree = ast.parse(helpers_path.read_text("utf-8"))
    except (OSError, SyntaxError):
        return {}
    selectors = _shared_selector_imports([tree])
    defs: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.setdefault(node.name, []).append(node)
    reached: dict[str, set[str]] = {name: set() for name in defs}
    calls: dict[str, set[str]] = {name: set() for name in defs}
    for name, nodes in defs.items():
        for func in nodes:
            for call in (n for n in ast.walk(func) if isinstance(n, ast.Call)):
                if isinstance(call.func, ast.Name) and call.func.id in selectors:
                    reached[name].add(selectors[call.func.id])
                callee = _call_func_name(call)
                if callee in defs and callee != name:
                    calls[name].add(callee)
    changed = True
    while changed:
        changed = False
        for name, callees in calls.items():
            for callee in callees:
                if not reached[callee] <= reached[name]:
                    reached[name] |= reached[callee]
                    changed = True
    return {name: frozenset(kinds) for name, kinds in reached.items() if kinds}


def _load_helpers_aliases(*trees: ast.AST) -> set[str]:
    """Names bound to ``load_helpers(...)`` anywhere in ``trees``: how a recipe's test module
    names its own ``helpers.py`` (``helpers = load_helpers(RECIPE)``)."""
    aliases: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and _call_func_name(node.value) == "load_helpers"
            ):
                aliases |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return aliases


def _assigned_from_helper_selector(
    tree: ast.AST,
    selectors: dict[str, frozenset[str]],
    aliases: set[str],
    real_name: str,
) -> str | None:
    """The name ``x`` in the first ``x = <alias>.<fn>(...)`` of ``tree`` (source order) where
    ``<alias>`` is bound to this recipe's own ``load_helpers(...)`` and ``<fn>`` is a function of
    that ``helpers.py`` that reaches ``real_name`` (``selectors``, from
    ``_threshold_selecting_helpers``). The callee must be BOTH reached through the recipe's own
    helpers module AND really select a threshold: an unrelated helper function, an attribute of
    some other object, or a helper that only returns a number is not a re-derivation."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id in aliases
            and real_name in selectors.get(node.value.func.attr, frozenset())
        ):
            found.append((node.lineno, node.targets[0].id))
    return min(found)[1] if found else None


def _derives_threshold_name(
    body: str,
    tree: ast.AST | None = None,
    selectors: dict[str, frozenset[str]] | None = None,
    aliases: set[str] | None = None,
) -> str | None:
    """The name the strong-form test binds its re-derived threshold to: ``x =
    select_confidence_threshold(...)``, else ``x = <helpers>.<fn>(...)`` where ``<fn>`` is a
    function of this recipe's own ``helpers.py`` that reaches ``select_confidence_threshold``
    (#222 gap 2: correct factoring behind a named wrapper is not punished, and a test that
    wants a fully independent re-derivation can still write the call out), else the same two
    shapes for ``select_threshold``. The confidence gate is preferred over a plain business
    threshold when both are present, whichever is written first."""
    match = CONFIDENCE_GATE_ASSIGN.search(body)
    if match:
        return match.group(1)
    if tree is not None and selectors:
        via_helper = _assigned_from_helper_selector(
            tree, selectors, aliases or set(), "select_confidence_threshold"
        )
        if via_helper:
            return via_helper
    match = PLAIN_THRESHOLD_ASSIGN.search(body)
    if match:
        return match.group(1)
    if tree is not None and selectors:
        return _assigned_from_helper_selector(tree, selectors, aliases or set(), "select_threshold")
    return None


def _ast_names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _has_gte_against(node: ast.AST, target: str) -> bool:
    """True if ``node``'s subtree contains a ``>=`` comparison with ``target`` on either side."""
    for compare in ast.walk(node):
        if isinstance(compare, ast.Compare):
            for op, comparator in zip(compare.ops, compare.comparators, strict=True):
                if isinstance(op, ast.GtE) and (
                    target in _ast_names(compare.left) or target in _ast_names(comparator)
                ):
                    return True
    return False


def _calls_in(stmts: list[ast.stmt]) -> list[ast.Call]:
    """``ast.Call`` nodes under ``stmts`` only -- an ``ast.If``'s ``body``, never its ``orelse``,
    so an ``.append`` in an unrelated ``else`` branch is never credited to the ``if``'s own test."""
    return [n for s in stmts for n in ast.walk(s) if isinstance(n, ast.Call)]


def _vars_bound_to_the_gte_comparison(tree: ast.AST, target: str) -> set[str]:
    """Names whose value structurally depends on a ``>= target`` comparison: an assignment whose
    right-hand side contains one (a list comprehension's filter or its element expression, a
    ``for``-loop accumulator initialised to a boolean/number), or a ``name.append(...)`` call
    inside the body of an ``if`` whose test contains one (the loop-and-flag shape 14, 18 and 22
    use: ``if a.confidence >= gate: wrong_above_gate.append(e.id)``)."""
    confirmed: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and _has_gte_against(node.value, target)
        ):
            confirmed.add(node.targets[0].id)
        if isinstance(node, ast.If) and _has_gte_against(node.test, target):
            for call in _calls_in(node.body):
                if isinstance(call.func, ast.Attribute) and call.func.attr == "append":
                    if isinstance(call.func.value, ast.Name):
                        confirmed.add(call.func.value.id)
    return confirmed


def _an_assert_depends_on(tree: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(node, ast.Assert) and _ast_names(node.test) & names for node in ast.walk(tree)
    )


@pytest.mark.parametrize("recipe", guarded("stored_answers_strong_form"))
def test_stored_answers_are_not_all_right_is_the_strong_form(recipe):
    """G1(c): the strong form re-derives the frozen confidence threshold from ``validation``
    (an assignment from ``select_confidence_threshold(`` or, lacking that, ``select_threshold(``;
    in either case the call may be written out in the test or made through a function of the
    recipe's own ``helpers.py`` that reaches it, ``gate = helpers.choose_gate(...)``, #222 gap 2)
    and binds an ``assert`` to a wrong-answer-at-or-above-it comparison -- not merely performs
    the comparison somewhere dead, and not merely asserts "some wrong answer exists" (the weak
    form, R7, which has no such assignment to find at all).

    Accepting a call through ``helpers`` stops the check punishing correct factoring (a recipe
    that names its objective once, in ``helpers.py``, no longer has to restate the call here
    only to satisfy a text pattern) and leaves independence available by choice: a strong-form
    test that must not agree with the production path by construction still writes the call out.
    What the callee has to be is checked, not assumed: ``helpers`` must be bound to
    ``load_helpers(...)`` in the test module, and the function must exist in that recipe's
    ``helpers.py`` and reach the shared selection function through its own call graph.
    The test module's name for this function is also load-bearing, and the failure says so.

    "Binds" is checked with ``ast``, not text: find every name whose value structurally depends
    on a ``>= <derived name>`` comparison (a list/generator comprehension's filter or element
    expression, or a ``name.append(...)`` call inside an ``if`` gated on that comparison -- the
    two shapes the eight currently-passing recipes and the template use between them), then
    require at least one ``assert`` whose own test expression names one of those. A recipe that
    keeps an old weak assertion *alongside* a working strong one (18, 22) still passes, because
    the strong assertion is what actually binds; deleting only the strong assertion and leaving
    the weak one (proven on recipe 14 in scratch) correctly fails this check.

    The property this check is *about* is whether the recipe freezes a confidence or business
    threshold at all -- not whether its answers happen to be stored in ``responses.json``
    (#249). A scripted recipe (no ``fixtures/responses.json``, answers computed instead of
    replayed) that freezes a gate has exactly the same obligation to re-derive it as a recipe
    whose answers are stored; whether the answers came from a file or a function says nothing
    about whether a threshold exists to re-derive. So the skip below is keyed on
    ``_threshold_pin_obligations`` -- the same real-call detector ``threshold_objective_pin``
    already uses to find every genuine ``select_confidence_threshold(``/``select_threshold(``
    call in this recipe's committed notebook or ``helpers.py`` -- rather than on
    ``responses.json``'s existence, which is a correlate of "has stored answers", not of "has a
    threshold"."""
    if recipe["slug"] != "_template" and not _threshold_pin_obligations(recipe_dir(recipe)):
        pytest.skip(
            "no real select_confidence_threshold(/select_threshold( call in this recipe's "
            "notebook or helpers.py: this recipe freezes no threshold for G1(c) to re-derive"
        )
    failure = _strong_form_failure(recipe_dir(recipe), recipe["slug"])
    assert failure is None, failure


def _strong_form_failure(recipe_dir_: Path, slug: str) -> str | None:
    """The whole G1(c) verdict for one recipe directory once the check applies: ``None`` when
    it passes, else the message. Factored out of the parametrised test so the table and mutation
    tests below run the SAME code path CI runs, on a throwaway recipe."""
    tests_dir = recipe_dir_ / "tests"
    found: list[tuple[str, str]] = []
    for test_file in sorted(tests_dir.glob("*.py")):
        text = test_file.read_text("utf-8")
        if (body := _find_function_body(text, STRONG_FORM_DEF)) is not None:
            found.append((text, body))
    if not found:
        return (
            f"{slug}: no {STRONG_FORM_DEF} in tests/ -- the guard locates the strong-form test "
            "by this name (a longer name that continues it, such as "
            f"{STRONG_FORM_DEF}_above_the_frozen_gate, is found too), so the name is part of "
            "the contract; a correctly shaped test under any other name is not seen"
        )
    text, body = found[0]
    try:
        tree = ast.parse(body)
    except SyntaxError as error:
        return (
            f"{slug}: the extracted {STRONG_FORM_DEF} body does not parse ({error.msg} at "
            f"line {error.lineno} of the extracted text). The guard cuts the function out of "
            "its test file at the next column-zero decorator, def or class; check that the "
            "function and the lines directly after it are plain Python"
        )
    try:
        module_tree = ast.parse(text)
    except SyntaxError:
        module_tree = ast.parse("")
    selectors = _threshold_selecting_helpers(recipe_dir_ / "helpers.py")
    aliases = _load_helpers_aliases(module_tree, tree)
    target = _derives_threshold_name(body, tree, selectors, aliases)
    if not target:
        return (
            f"{slug}: does not re-derive the threshold (no 'x = select_confidence_threshold(...)' "
            "or 'x = select_threshold(...)', and no 'x = helpers.<fn>(...)' where <fn> is a "
            "function of this recipe's own helpers.py that calls one of them)"
        )
    confirmed = _vars_bound_to_the_gte_comparison(tree, target)
    if not confirmed:
        return f"{slug}: nothing is derived from a '>= {target}' comparison"
    if not _an_assert_depends_on(tree, confirmed):
        return f"{slug}: no assert's own test expression names {sorted(confirmed)}"
    return None


def test_stored_answers_strong_form_skip_fires_only_when_no_threshold_is_frozen(tmp_path):
    """#249: the skip above is keyed on ``_threshold_pin_obligations`` finding no real
    ``select_confidence_threshold(``/``select_threshold(`` call in the recipe's notebook or
    ``helpers.py`` -- the property G1(c) is about -- rather than on whether
    ``fixtures/responses.json`` exists. Proving a skip condition needs both directions (a skip
    that never skips is as wrong as one that always does):

    1. **Fires when no threshold is frozen.** On a throwaway copy of recipe 36 (the one
       published scripted recipe, chosen because it has no ``responses.json`` and would have
       been silently skipped by the OLD condition regardless of this property), deleting its
       one real ``select_confidence_threshold(`` call and import leaves
       ``_threshold_pin_obligations`` empty -- the input the skip's ``not ...`` branches on.
    2. **Does not fire when a threshold is frozen.** The unmodified recipe 36 is used elsewhere
       in this module's own parametrized run
       (``test_stored_answers_are_not_all_right_is_the_strong_form[36-card-game-action-
       selection]``) and is observed there to PASS, not skip -- it has a confidence gate and
       the strong-form test re-derives it, so the property is true and the check runs for real.
       That parametrized case is the live, continuously-run proof for this direction; this test
       supplies the complementary one a synthetic mutation is needed for."""
    recipe_dir_copy = tmp_path / "36-card-game-action-selection"
    shutil.copytree(REPO / "recipes" / "36-card-game-action-selection", recipe_dir_copy)

    assert _threshold_pin_obligations(recipe_dir_copy), (
        "sanity check failed: the unmodified copy already has no threshold obligations"
    )

    nb_path = recipe_dir_copy / "notebook.ipynb"
    notebook = json.loads(nb_path.read_text("utf-8"))
    setup_cell = next(c for c in notebook["cells"] if c.get("id") == "setup")
    rule_cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")

    import_source = cell_source(setup_cell)
    stripped_import = import_source.replace("    select_confidence_threshold,\n", "")
    assert stripped_import != import_source, "mutation did not take -- the replace found nothing"
    setup_cell["source"] = [stripped_import]

    rule_source = cell_source(rule_cell)
    stripped_call = rule_source.replace(
        "threshold = select_confidence_threshold(val_correct, val_confidence, "
        "min_coverage=MIN_COVERAGE)",
        "threshold = 0.5  # no real threshold-selection call left",
    )
    assert stripped_call != rule_source, "mutation did not take -- the replace found nothing"
    rule_cell["source"] = [stripped_call]

    nb_path.write_text(json.dumps(notebook), encoding="utf-8")

    obligations = _threshold_pin_obligations(recipe_dir_copy)
    assert obligations == [], (
        f"expected no threshold obligations once the real call is gone, got {obligations}"
    )


# --- fixtures for the tests that run a check on a throwaway recipe ------------------------------


def _copy_recipe(tmp_path: Path, slug: str) -> Path:
    """A throwaway copy of the published recipe (or ``_template``) ``slug``."""
    target = tmp_path / slug
    shutil.copytree(RECIPES_DIR / slug, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


def _edit_text(path: Path, old: str, new: str) -> None:
    """Replace ``old`` with ``new`` in the file at ``path``; ``old`` must occur exactly once, so a
    mutation that silently missed its target cannot pass for a mutation that was caught."""
    text = path.read_text("utf-8")
    assert text.count(old) == 1, (
        f"{path.name}: expected exactly one {old!r}, found {text.count(old)}"
    )
    path.write_text(text.replace(old, new), "utf-8")


def _edit_notebook_code(folder: Path, old: str, new: str) -> None:
    """Like ``_edit_text`` for the notebook's code cells, as one text (``old`` occurs once)."""
    path = folder / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    hits = 0
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            source = cell_source(cell)
            hits += source.count(old)
            cell["source"] = source.replace(old, new).splitlines(keepends=True)
    assert hits == 1, f"notebook: expected exactly one {old!r}, found {hits}"
    path.write_text(json.dumps(notebook), "utf-8")


# --- #272: the function body stops at a column-zero decorator -----------------------------------

# The scan before #272, kept here as the red-before evidence: a decorator line is neither of these.
_LEGACY_NEXT_DEF = re.compile(r"\n(?:def |class )")

_AUDITED = """
def test_stored_answers_are_not_all_right():
    gate = select_confidence_threshold(a, b, target_accuracy=1.0)
    wrong = [e for e in test if e.confidence >= gate]
    assert wrong
"""


@pytest.mark.parametrize(
    "neighbour",
    [
        '@pytest.mark.parametrize("x", [1, 2])\ndef test_other(x):\n    assert x\n',
        "@pytest.fixture\n@pytest.mark.slow\ndef thing():\n    return 1\n",
        '@pytest.mark.parametrize(\n    "x",\n    [1, 2],\n)\ndef test_other(x):\n    assert x\n',
        "class TestThing:\n    def test_a(self):\n        assert 1\n",
        "def test_plain():\n    assert 1\n",
        "",
    ],
    ids=["decorated", "two-decorators", "multi-line-decorator", "class", "plain-def", "eof"],
)
def test_the_function_body_stops_at_whatever_follows_it(neighbour):
    """#272: the extracted body ends at the next column-zero decorator, def or class, so whatever
    follows the audited function is never folded into it and ``ast.parse`` of the body is the
    audited function alone."""
    source = "import pytest\n" + _AUDITED + "\n\n" + neighbour
    body = _find_function_body(source, STRONG_FORM_DEF)
    assert body is not None
    ast.parse(body)
    assert body.rstrip().endswith("assert wrong")
    if neighbour:
        assert neighbour.splitlines()[0] not in body


def test_the_legacy_scan_folded_a_decorated_neighbour_into_the_body():
    """The red-before for #272, in the repository rather than in a pull request body: the scan this
    module used before the fix, run on the same source, hands ``ast.parse`` a decorator with no
    function under it and raises the ``SyntaxError`` the issue reproduces."""
    source = (
        "import pytest\n"
        + _AUDITED
        + '\n\n@pytest.mark.parametrize("x", [1, 2])\ndef t(x):\n    pass\n'
    )
    rest = source[source.find(STRONG_FORM_DEF) :]
    legacy_body = rest[: _LEGACY_NEXT_DEF.search(rest).start()]
    assert legacy_body.rstrip().endswith('@pytest.mark.parametrize("x", [1, 2])')
    with pytest.raises(SyntaxError):
        ast.parse(legacy_body)
    ast.parse(_find_function_body(source, STRONG_FORM_DEF))


def test_an_indented_decorator_inside_the_body_does_not_end_the_scan_early():
    """#272's negative case: ``\\n@`` at column zero and an indented ``@`` are different things.
    A nested function (or a class body) inside the audited function is decorated at its own
    indentation, and the lines after it, including the assert the check is looking for, are
    still the audited function's."""
    source = (
        "def test_stored_answers_are_not_all_right():\n"
        "    gate = select_confidence_threshold(a, b, target_accuracy=1.0)\n"
        "\n"
        "    @staticmethod\n"
        "    def nested(e):\n"
        "        return e.confidence >= gate\n"
        "\n"
        "    wrong = [e for e in test if nested(e)]\n"
        "    assert wrong\n"
        "\n\n"
        '@pytest.mark.parametrize("x", [1])\n'
        "def test_other(x):\n"
        "    pass\n"
    )
    body = _find_function_body(source, STRONG_FORM_DEF)
    assert "@staticmethod" in body
    assert body.rstrip().endswith("assert wrong")
    assert "test_other" not in body
    ast.parse(body)


# --- #222 gap 2: the strong-form test may re-derive through a helpers function -------------------

_STRONG_FORM_HELPERS = """
from jev_cookbook.evaluation import select_confidence_threshold, select_threshold


def choose_gate(correct, confidence):
    return select_confidence_threshold(correct, confidence, min_coverage=0.5)


def choose_gate_twice_removed(correct, confidence):
    return choose_gate(correct, confidence)


def choose_business(gold, noul):
    return select_threshold(gold, noul, objective="f1")


def fixed_gate(correct, confidence):
    return 0.85
"""

_LOOK_ALIKE_HELPERS = """
def select_confidence_threshold(correct, confidence, **kwargs):
    return 0.85


def choose_gate(correct, confidence):
    return select_confidence_threshold(correct, confidence, min_coverage=0.5)
"""

_STRONG_FORM_TEST = """
from types import SimpleNamespace

import pytest
from jev_cookbook import load_helpers
from jev_cookbook.evaluation import select_confidence_threshold, select_threshold

{binding}
{extra}

def {name}():
{derive}
    wrong_and_confident = [e for e in test if e.confidence >= {var} and not e.ok]
    assert {assertion}
{tail}
"""

_DECORATED_TAIL = """

@pytest.mark.parametrize("x", [1, 2])
def test_something_else(x):
    assert x
"""


def _strong_form_recipe(
    tmp_path: Path,
    *,
    derive: str,
    var: str = "gate",
    assertion: str = "wrong_and_confident",
    helpers: str = _STRONG_FORM_HELPERS,
    extra: str = "",
    binding: str = "helpers = load_helpers(RECIPE)",
    name: str = "test_stored_answers_are_not_all_right",
    tail: str = "",
) -> Path:
    folder = tmp_path / "synthetic-recipe"
    (folder / "tests").mkdir(parents=True)
    (folder / "helpers.py").write_text(helpers, "utf-8")
    (folder / "tests" / "test_helpers.py").write_text(
        _STRONG_FORM_TEST.format(
            derive=textwrap.indent(derive, "    "),
            var=var,
            assertion=assertion,
            extra=extra,
            binding=binding,
            name=name,
            tail=tail,
        ),
        "utf-8",
    )
    return folder


_STRONG_FORM_CASES = {
    # shapes that pass: the written-out call (unchanged), then a call through the recipe's helpers
    "written-out": ("gate = select_confidence_threshold(c, f, target_accuracy=1.0)", {}, None),
    "helpers-wrapper": ("gate = helpers.choose_gate(c, f)", {}, None),
    "wrapper-of-a-wrapper": ("gate = helpers.choose_gate_twice_removed(c, f)", {}, None),
    "business-wrapper": (
        "threshold = helpers.choose_business(g, n)",
        {"var": "threshold"},
        None,
    ),
    "local-helpers-name": (
        "h = load_helpers(RECIPE)\ngate = h.choose_gate(c, f)",
        {},
        None,
    ),
    "gate-preferred-over-business": (
        "threshold = helpers.choose_business(g, n)\ngate = helpers.choose_gate(c, f)",
        {},
        None,
    ),
    "decorated-neighbour-after-it": (
        "gate = helpers.choose_gate(c, f)",
        {"tail": _DECORATED_TAIL},
        None,
    ),
    "longer-name-is-found": (
        "gate = helpers.choose_gate(c, f)",
        {"name": "test_stored_answers_are_not_all_right_above_the_gate"},
        None,
    ),
    # shapes that must still fail: the relaxation accepts a real selection, nothing else
    "constant-from-helpers": (
        "gate = helpers.fixed_gate(c, f)",
        {},
        "does not re-derive the threshold",
    ),
    "function-helpers-does-not-have": (
        "gate = helpers.no_such_function(c, f)",
        {},
        "does not re-derive the threshold",
    ),
    "object-that-is-not-load-helpers": (
        "gate = helpers.choose_gate(c, f)",
        {"binding": "helpers = SimpleNamespace(choose_gate=lambda c, f: 0.85)"},
        "does not re-derive the threshold",
    ),
    "same-function-on-another-object": (
        "gate = other.choose_gate(c, f)",
        {"extra": "other = SimpleNamespace(choose_gate=lambda c, f: 0.85)"},
        "does not re-derive the threshold",
    ),
    "look-alike-in-helpers": (
        "gate = helpers.choose_gate(c, f)",
        {"helpers": _LOOK_ALIKE_HELPERS},
        "does not re-derive the threshold",
    ),
    "business-compared-but-gate-derived": (
        "threshold = helpers.choose_business(g, n)\ngate = helpers.choose_gate(c, f)",
        {"var": "threshold"},
        "nothing is derived from a '>= gate' comparison",
    ),
    "derived-name-never-compared": (
        "gate = helpers.choose_gate(c, f)",
        {"var": "something_else"},
        "nothing is derived from a '>= gate' comparison",
    ),
    "compared-but-never-asserted": (
        "gate = helpers.choose_gate(c, f)",
        {"assertion": "True"},
        "no assert's own test expression names",
    ),
    "wrong-name": (
        "gate = helpers.choose_gate(c, f)",
        {"name": "test_every_wrong_answer_is_caught"},
        "the name is part of the contract",
    ),
}


@pytest.mark.parametrize("case", sorted(_STRONG_FORM_CASES))
def test_the_strong_form_accepts_a_call_into_helpers_only_when_it_really_selects(tmp_path, case):
    """#222 gap 2: the check used to require ``x = select_confidence_threshold(`` written out in the
    test, so a recipe that named its objective once in ``helpers.py`` (31, 35) had to restate the
    call. A call into the recipe's own helpers is now accepted when it is made through the module
    ``load_helpers`` returned AND the function exists there and reaches the shared selection
    function. Every row that must still fail names why."""
    derive, kwargs, expected = _STRONG_FORM_CASES[case]
    folder = _strong_form_recipe(tmp_path, derive=derive, **kwargs)
    failure = _strong_form_failure(folder, "synthetic")
    if expected is None:
        assert failure is None, failure
    else:
        assert failure is not None and expected in failure, failure


def test_the_old_patterns_find_nothing_in_a_helpers_derivation():
    """Red-before for #222 gap 2: the two regexes the check relied on match neither shape the
    relaxation accepts, so on the previous code every ``helpers-wrapper`` row above failed with
    "does not re-derive the threshold"."""
    for line in (
        "gate = helpers.choose_gate(c, f)",
        "gate = helpers.choose_gate_twice_removed(c, f)",
    ):
        assert CONFIDENCE_GATE_ASSIGN.search(line) is None
        assert PLAIN_THRESHOLD_ASSIGN.search(line) is None


def test_recipe_31s_strong_form_passes_with_its_gate_derived_through_helpers(tmp_path):
    """The published recipe the issue's second comment is about: 31's strong-form test restates
    ``select_confidence_threshold(...)`` inline only because the guard demanded the text. Replace
    that call with the ``helpers.choose_gate`` wrapper the notebook already uses and the check
    still passes -- and the previous patterns find no derivation in the result, so on the
    previous code this same mutation failed."""
    folder = _copy_recipe(tmp_path, "31-patch-risk-triage")
    test_file = folder / "tests" / "test_helpers.py"
    assert _strong_form_failure(folder, "31") is None
    _edit_text(
        test_file,
        "    gate = select_confidence_threshold(\n"
        "        val_correct, val_confidence, min_coverage=helpers.MIN_COVERAGE\n"
        "    )\n",
        "    gate = helpers.choose_gate(val_correct, val_confidence)\n",
    )
    assert _strong_form_failure(folder, "31") is None
    body = _find_function_body(test_file.read_text("utf-8"), STRONG_FORM_DEF)
    assert CONFIDENCE_GATE_ASSIGN.search(body) is None
    assert PLAIN_THRESHOLD_ASSIGN.search(body) is None
    # ... and a wrapper that selects nothing is still not a re-derivation.
    _edit_text(
        folder / "helpers.py",
        "    return select_confidence_threshold(correct, confidence, min_coverage=MIN_COVERAGE)",
        "    return 0.85",
    )
    failure = _strong_form_failure(folder, "31")
    assert failure is not None and "does not re-derive the threshold" in failure


def test_a_strong_form_body_that_does_not_parse_is_reported_as_such(tmp_path):
    """#272's other half: an extracted body that cannot be parsed is reported as what it is, with
    the cut the guard made, never as a bare ``SyntaxError`` traceback blamed on the recipe."""
    folder = _strong_form_recipe(tmp_path, derive="gate = helpers.choose_gate(c, f)")
    test_file = folder / "tests" / "test_helpers.py"
    test_file.write_text(
        test_file.read_text("utf-8").replace(
            "    assert wrong_and_confident\n", "    assert wrong_and_confident\n  )\n"
        ),
        "utf-8",
    )
    failure = _strong_form_failure(folder, "synthetic")
    assert failure is not None and "does not parse" in failure and "column-zero" in failure


# --------------------------------------------------------------------------------------------
# check 4a: a validation metric line carries both {selection} and {check}
# --------------------------------------------------------------------------------------------

# A rounded-float replacement field: ``{x:.4f}``, and the same with whatever Python's format-spec
# mini-language allows between the colon and the precision -- fill and alignment (``>``, ``<``,
# ``^``, ``=``, ``*^``), sign, ``z``, ``#``, a leading ``0``, a width (a number or a nested ``{w}``)
# and a grouping character: ``{x:>13.4f}``, ``{x:<8.2f}``, ``{x:^10.4f}``, ``{x:+08.3f}``,
# ``{x:,.2f}``. The precision stays required (``{x:10f}`` is not a *rounded* float) and the type
# stays ``f``, so ``{x:>8}``, ``{x:d}``, ``{x:.2%}`` and ``{x:.3g}`` are still not matched (#270).
_FORMAT_SPEC_BEFORE_PRECISION = r"(?:[^{}]?[<>=^])?[+\- ]?z?#?0?(?:\d+|\{[^{}]*\})?[,_]?"
FLOAT_FORMAT = re.compile(r"\{[^{}]*:" + _FORMAT_SPEC_BEFORE_PRECISION + r"\.\d+f\}")
SELECTION_AND_CHECK = ("{selection}", "{check}")


class _Binding(NamedTuple):
    """One value assigned to a name: its source ``text``, the ``names`` it references, the string
    ``literals`` it spells (the characters it can print, as opposed to identifiers and keyword
    names that merely appear in its source), and whether it ``builds_float`` (see
    ``_hoisted_float_strings``)."""

    text: str
    names: frozenset[str]
    literals: str
    builds_float: bool


def _hoisted_float_strings(code: list[tuple[str, str, ast.Module]]) -> dict[str, list[_Binding]]:
    """``{name: [every value assigned to it]}`` for each name with a simple binding
    (``name = <expr>``, ``name: T = <expr>``) in the notebook's code cells that *builds a
    rounded-float string*: a value of it spells a float format (``FLOAT_FORMAT``), or references a
    name that does (``line = f"({text})"`` after ``text = f"{x:.2f}"``), to a fixed point. This is
    what lets the guard below follow a ``print`` to the line that actually formats the number
    (#234).

    Only float-building names are followed, never any name, on purpose: ``other_split =
    "validation"`` or ``selection = " (selection: chosen on validation)"`` would otherwise put the
    word "validation" into every line that mentions the name, and recipe 32's test-split overlap
    figure (a fixture-composition statistic, not a validation metric) would become a validation
    metric line.

    A followed name keeps EVERY value it is assigned, with ``builds_float`` saying which build a
    float: the labels a name carries are those of all its values (``_tokens_through``), so a later
    ``row = "no float here"`` does not leave the label of an earlier ``row = f"{a:.2f}{check}"``
    credited to a line that prints the later one. What a line can say ("validation") and whether it
    prints a float are read from the float-building values only."""
    bindings: dict[str, list[_Binding]] = {}
    for _cell_id, source, tree in code:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                target, value = node.target, node.value
            else:
                continue
            if isinstance(target, ast.Name):
                text = ast.get_source_segment(source, value) or ""
                literals = " ".join(
                    n.value
                    for n in ast.walk(value)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                )
                bindings.setdefault(target.id, []).append(
                    _Binding(text, frozenset(_ast_names(value)), literals, False)
                )
    float_building: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, values in bindings.items():
            if name not in float_building and any(
                FLOAT_FORMAT.search(v.text) or v.names & float_building for v in values
            ):
                float_building.add(name)
                changed = True
    return {
        name: [
            v._replace(builds_float=bool(FLOAT_FORMAT.search(v.text) or v.names & float_building))
            for v in values
        ]
        for name, values in bindings.items()
        if name in float_building
    }


def _tokens_through(
    names: set[str],
    hoisted: dict[str, list[_Binding]],
    tokens: tuple[str, ...],
    _visiting: frozenset[str] = frozenset(),
) -> tuple[list[_Binding], set[str]]:
    """``(printed, carried)`` for the followed names among ``names``: the float-building values
    they are bound to, transitively, and the subset of ``tokens`` carried by *every* value (float
    building or not) of *some* name -- a label that sits in only one of two assignments of a name
    is not a label the line prints. Not flow-sensitive: every assignment of the name anywhere in
    the notebook counts, so a print that comes before a later unlabelled rebinding is reported
    too (the safe direction)."""
    printed: list[_Binding] = []
    carried: set[str] = set()
    for name in names & hoisted.keys() - _visiting:
        per_value = []
        for value in hoisted[name]:
            deeper_printed, deeper_carried = _tokens_through(
                set(value.names), hoisted, tokens, _visiting | {name}
            )
            if value.builds_float:
                printed.append(value)
                printed += deeper_printed
            per_value.append({t for t in tokens if t in value.text} | deeper_carried)
        carried |= set.intersection(*per_value)
    return printed, carried


def _validation_metric_lines_missing_labels(
    cells: list[tuple[str, str]],
) -> list[tuple[str, str, list[str]]]:
    """``(cell id, print text, missing labels)`` for each *validation metric line* of the notebook
    code cells ``cells`` (``[(cell id, source)]``) that lacks ``{selection}`` or ``{check}``.

    A validation metric line is a ``print(`` call that prints a rounded float and says
    "validation". Both are read off what the line prints, not off one spelling of it: the float
    may be formatted in the call or in a string the call interpolates (``text = f"{c:.2f}"`` /
    ``print(f"validation ...: {text}")``, traced through simple bindings, #234), and the format may
    carry alignment or a width (``FLOAT_FORMAT``, #270). The word "validation" must be in the
    call's own text (any part of it, as it always was) or in a string literal of a float-building
    value the call prints (``line = f"validation accuracy: {a:.2f}"``); an identifier or a keyword
    argument inside that value (``for n, v in input_validation_concerns``) is not something the
    line prints and does not count. A name bound to some other string is not followed (see
    ``_hoisted_float_strings``).

    The labels are the literal tokens ``{selection}`` and ``{check}``, in the call or in a
    float-building string it prints. A line that builds its suffix by concatenation or through a
    differently spelled name FAILS, though what it prints is right. That is deliberate and stays:
    it is the safe direction, and it keeps one spelling of the label across the published set. Do
    not read it as a defect of this check (#234, quirk 1).

    Quirk 3 of #234 (the bare word "validation" makes a line a validation line) is not removed, and
    the hoist makes its surface slightly wider, not narrower: the word may now also arrive from a
    string literal of the float string the call interpolates.

    Not seen, so a reader knows what a green result does not say: a float rounded by ``round()``
    or ``%`` or the builtin ``format()``; a "validation" that reaches the line only through a
    loop variable (when measured, 26 committed lines in 12 cells of 8 recipes: 25 carry both labels
    through their loop's own tuple, one does not -- recipe 39's ``evaluation-t86``, #363) or a name
    bound to ``"validation"``; a float hoisted by anything but a simple binding (a tuple unpack, ``+=``, a
    ``for`` target, a function's return); a nested precision (``{x:.{p}f}``); and a printer that is
    not literally ``print(`` (``pprint(``, ``obj.print(``), which the text scan this replaced did
    inspect and the published set has none of. A cell that does not parse is read the way it always
    was, by the text of each ``print(`` call, rather than skipped."""
    code = []
    unparsable = []
    for cell_id, source in cells:
        try:
            code.append((cell_id, source, ast.parse(source)))
        except SyntaxError:
            unparsable.append((cell_id, source))
    hoisted = _hoisted_float_strings(code)
    found = []
    for cell_id, source, tree in code:
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print"):
                continue
            call = ast.get_source_segment(source, node) or ""
            printed, carried = _tokens_through(
                {
                    n
                    for arg in (*node.args, *(kw.value for kw in node.keywords))
                    for n in _ast_names(arg)
                },
                hoisted,
                SELECTION_AND_CHECK,
            )
            if not any(FLOAT_FORMAT.search(t) for t in [call, *(v.text for v in printed)]):
                continue
            if not any("validation" in t.lower() for t in [call, *(v.literals for v in printed)]):
                continue
            missing = [t for t in SELECTION_AND_CHECK if t not in call and t not in carried]
            if missing:
                found.append((cell_id, call, missing))
    for cell_id, source in unparsable:
        for call in extract_calls(source, "print"):
            if FLOAT_FORMAT.search(call) and "validation" in call.lower():
                missing = [t for t in SELECTION_AND_CHECK if t not in call]
                if missing:
                    found.append((cell_id, call, missing))
    return found


@pytest.mark.parametrize("recipe", guarded("validation_lines_carry_selection_and_check"))
def test_validation_metric_lines_carry_selection_and_check(recipe):
    """G1(d), CONTRIBUTING.md section 2: "a number from the validation split is a selection
    step" and, in an offline run, "any metric is a check that the pipeline works" -- together,
    in a synthetic or scripted run, a validation number needs both labels.

    Narrow, mechanical definition: a *validation metric line* is a ``print(`` call in a notebook
    code cell that prints a rounded float (``{x:.4f}``, or with an alignment or width,
    ``{x:>13.4f}``) and says "validation". The float format may sit in a string the call
    interpolates rather than in the call itself, and is followed through simple bindings
    (``_validation_metric_lines_missing_labels``). Such a line must contain the literal tokens
    ``{selection}`` and ``{check}``. A line that builds those by concatenation fails although what
    it prints is right: deliberate, the safe direction, and not to be loosened. This does not catch
    a validation line with no rounded float (a plain status line with no number carries no
    selection/check obligation either), a float formatted by ``round()``, ``%`` or the builtin
    ``format()``, a line whose only mention of validation is in a string that is not itself a float
    format (a loop variable, a name bound to ``"validation"``), or a printed number that never says
    "validation" on the line. The word "validation" is still the trigger (quirk 3 of #234 is not
    removed), now also read from the string literals of the float string the call interpolates.
    The full list of what is not seen is in ``_validation_metric_lines_missing_labels``."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    cells = [
        (str(cell.get("id", "?")), cell_source(cell))
        for cell in (notebook_cells(recipe_dir(recipe)) if nb.is_file() else [])
        if cell["cell_type"] == "code"
    ]
    violations = [
        f"cell {cell_id} missing {missing}: {call[:80]!r}"
        for cell_id, call, missing in _validation_metric_lines_missing_labels(cells)
    ]
    assert not violations, "; ".join(violations)


# --------------------------------------------------------------------------------------------
# check 4b (of G1(d)): every printed metric line carries at least {check}
# --------------------------------------------------------------------------------------------

METRIC_KEYWORD = re.compile(r"\b(coverage|accuracy|risk|precision|recall|f1|ndcg)\b", re.IGNORECASE)


def _assigned_names(tree: ast.AST) -> dict[str, ast.AST]:
    return {
        node.targets[0].id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }


def _labelled_names(tree: ast.AST, label: str) -> set[str]:
    """Names anywhere in ``tree`` transitively carrying the disclosure label ``"check"`` (or
    ``"selection"``): the bare name itself; a simple assignment whose value references one; a
    ``for``-loop's unpacked target at the position where every element of a literal tuple/list
    ``iter`` references one (recipe 17's ``for ..., label in (("validation", ..., selection +
    check), ("test", ..., check)):``); or a function parameter whose argument references one at
    every call site of that function (recipe 21's ``def f(..., suffix): ... f(..., f"{selection}
    {check}")``). Fixed-point over the three, so a label can pass through more than one hop."""
    derived = {label}
    assigns = list(ast.walk(tree))
    functions = {n.name: n for n in assigns if isinstance(n, ast.FunctionDef)}
    calls_by_func = {
        name: [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == name
        ]
        for name in functions
    }
    changed = True
    while changed:
        changed = False
        for node in assigns:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                target_name = node.targets[0].id
                if target_name not in derived and derived & _ast_names(node.value):
                    derived.add(target_name)
                    changed = True
            if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
                elements = node.iter.elts if isinstance(node.iter, ast.Tuple | ast.List) else None
                if not elements:
                    continue
                arity = len(node.target.elts)
                for position, slot in enumerate(node.target.elts):
                    if not isinstance(slot, ast.Name) or slot.id in derived:
                        continue
                    if all(
                        isinstance(elt, ast.Tuple | ast.List)
                        and len(elt.elts) == arity
                        and derived & _ast_names(elt.elts[position])
                        for elt in elements
                    ):
                        derived.add(slot.id)
                        changed = True
        for name, fdef in functions.items():
            calls = calls_by_func[name]
            if not calls:
                continue
            for position, arg in enumerate(fdef.args.args):
                if arg.arg in derived:
                    continue
                supplied_per_call = [
                    call.args[position]
                    if position < len(call.args)
                    else next((kw.value for kw in call.keywords if kw.arg == arg.arg), None)
                    for call in calls
                ]
                if all(s is not None and derived & _ast_names(s) for s in supplied_per_call):
                    derived.add(arg.arg)
                    changed = True
    return derived


def _metric_lines_missing_check(source: str) -> list[str]:
    """``print(`` calls in ``source`` whose text has a metric keyword and a rounded-float
    format spec but whose formatted values name no ``{check}``-derived name. Shared by the
    parametrized check below and by the regression test that proves the tracer's "every call
    site" requirement actually holds."""
    candidates = [
        c
        for c in extract_calls(source, "print")
        if METRIC_KEYWORD.search(c) and FLOAT_FORMAT.search(c)
    ]
    if not candidates:
        return []
    tree = ast.parse(source)
    check_derived = _labelled_names(tree, "check")
    missing = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print"):
            continue
        text = ast.get_source_segment(source, node) or ""
        if not (METRIC_KEYWORD.search(text) and FLOAT_FORMAT.search(text)):
            continue
        used = {
            name
            for arg in (*node.args, *(kw.value for kw in node.keywords))
            for name in _ast_names(arg)
        }
        if not used & check_derived:
            missing.append(text)
    return missing


@pytest.mark.parametrize("recipe", guarded("metric_lines_carry_check"))
def test_every_printed_metric_line_carries_at_least_check(recipe):
    """G1(d) clause 2 (issue #76 comment 6079429778): "every printed metric line carries at
    least {check}" -- the direct generalisation of
    tests/test_template.py::test_every_metric_line_of_the_evaluation_carries_the_pipeline_check_label,
    over every recipe instead of only the template. Catches R3 (recipe 17's six unlabelled sweep
    rows) and more besides, since Wave 2 only read recipes 11-23.

    Narrow, mechanical definition: a *metric line* is a ``print(`` call whose text contains both
    a coverage/accuracy/risk/precision/recall/F1/nDCG keyword and a rounded-float format spec
    (``{x:.4f}``, or aligned, ``{x:>13.4f}``: #270) -- a plain "any print with a rounded float" proxy is not usable, since it also
    flags the template's own per-example confidence lines, which carry no metric keyword and
    correctly need no label. Such a line's formatted values must include a name transitively
    carrying ``{check}`` (``_labelled_names``): checking only for the literal substring
    ``"{check}"`` wrongly flags recipes 17, 21 and 22, which disclose through a bound ``suffix``/
    ``label``/``split_label`` variable instead of the literal token."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    violations = []
    for cell in notebook_cells(recipe_dir(recipe)) if nb.is_file() else []:
        if cell["cell_type"] != "code":
            continue
        for text in _metric_lines_missing_check(cell_source(cell)):
            violations.append(f"cell {cell.get('id', '?')}: {text[:90]!r} carries no {{check}}")
    assert not violations, "; ".join(violations)


def test_the_label_tracer_requires_every_call_site_not_just_one():
    """Fix round 2, Opus re-review MC-A: ``_labelled_names`` must require a check-derived
    argument at *every* call site of a function (and at every element of a literal tuple/list
    ``for``-loop iterable), not just one -- otherwise one labelled split licenses another,
    undisclosed one. Proved directly against recipe 21's own ``eval-selective`` cell, which
    calls ``selective_report`` twice: once with ``f"{selection}{check}"``, once with plain
    ``check``. The unmutated cell has no violation; unlabelling only the second call site (the
    exact repro the review used) must turn up one."""
    source = cell_source(
        next(
            cell
            for cell in notebook_cells(recipe_dir({"slug": "21-quiz-answer-adjudication"}))
            if cell.get("id") == "eval-selective"
        )
    )
    assert not _metric_lines_missing_check(source)

    marker = '"test, called subset", check)'
    assert marker in source
    mutated = source.replace(marker, '"test, called subset", "")')
    assert _metric_lines_missing_check(mutated), (
        "unlabelling only the second selective_report call site must be caught"
    )


# --------------------------------------------------------------------------------------------
# checks 4a and 4b: what counts as a printed rounded float, and which line is a validation line
# --------------------------------------------------------------------------------------------

# Each is a replacement field as it is written inside an f-string.
_SPECS_THAT_ARE_ROUNDED_FLOATS = [
    "{x:.4f}",
    "{x:.0f}",
    "{x:>13.4f}",
    "{x:<8.2f}",
    "{x:^10.4f}",
    "{x:*^10.4f}",
    "{x:=+9.3f}",
    "{x:+.3f}",
    "{x:08.3f}",
    "{x:,.2f}",
    "{x:_.2f}",
    "{x:#.3f}",
    "{x:>{width}.4f}",
    "{report.coverage:>10.4f}",
    "{rows[0]['v']:>10.4f}",
    "{a if b else c:>8.2f}",
    "{x!r:>8.2f}",
]
_SPECS_THAT_ARE_NOT = [
    "{x}",
    "{x:>13}",
    "{x:<8s}",
    "{x:d}",
    "{x:>5d}",
    "{x:10f}",  # no precision: not a *rounded* float
    "{x:.4}",
    "{x:.4g}",
    "{x:.4e}",
    "{x:.1%}",
    "{x!r:>8}",
    "{'f':>8}",
    "{x:abc.4f}",  # not a format spec at all
    "{x:.4f",  # not closed
    "x:>13.4f",  # not a replacement field
    "{x:.f}",
    "{x:.{prec}f}",  # a nested precision is real Python, and not read: documented, not accidental
]


@pytest.mark.parametrize("field", _SPECS_THAT_ARE_ROUNDED_FLOATS)
def test_a_rounded_float_is_recognised_whatever_its_alignment_or_width(field):
    """#270: ``FLOAT_FORMAT`` required the precision to follow the colon, so the aligned table of
    recipe 43 (``{x:>13.4f}``) was not a printed float to either metric-line guard."""
    assert FLOAT_FORMAT.search(f"print(f'a {field} b')"), field


@pytest.mark.parametrize("field", _SPECS_THAT_ARE_NOT)
def test_a_format_that_is_not_a_rounded_float_is_still_not_recognised(field):
    """The widened pattern must not become everything-matching: no precision, another type, a
    percentage, no replacement field and a spec that is not one all stay unmatched."""
    assert not FLOAT_FORMAT.search(f"print(f'a {field} b')"), field


BOTH = ["{selection}", "{check}"]
NEXT_CELL = "\n#--cell--\n"

# source -> the labels the validation-metric-line check reports missing, one list per violating
# print call, in order. ``[]`` means the check has nothing to say about the source. A source may
# hold several code cells, separated by ``NEXT_CELL``.
_VALIDATION_LINES = {
    # --- a validation line that carries both labels passes, however the float is formatted ------
    "inline": ('print(f"validation accuracy: {a:.4f}{selection}{check}")', []),
    "aligned": (
        """print(f"{'validation':<28} {n:>8} {a:>13.4f} {b:>20.4f}{selection}{check}")""",
        [],
    ),
    "hoisted-labels-on-the-print": (
        'text = f"{a:.2f}"\nprint(f"validation accuracy: {text}{selection}{check}")',
        [],
    ),
    "hoisted-labels-in-the-binding": (
        'line = f"validation accuracy: {a:.2f}{selection}{check}"\nprint(line)',
        [],
    ),
    "hoisted-through-a-join": (
        'rows = ", ".join(f"{t} {c:.2f}" for t, c in wrong)\n'
        'print(f"validation wrong selection\'s confidence: {rows}{selection}{check}")',
        [],
    ),
    "hoisted-two-hops": (
        'text = f"{a:.2f}"\nline = f"({text})"\n'
        'print(f"validation accuracy {line}{selection}{check}")',
        [],
    ),
    "hoisted-in-another-cell-labelled": (
        'text = f"{a:.2f}"' + NEXT_CELL + 'print(f"validation accuracy: {text}{selection}{check}")',
        [],
    ),
    # a label that sits in the binding the line prints counts, split or whole
    "label-split-between-print-and-binding": (
        'text = f"{a:.2f}{selection}"\nprint(f"validation accuracy: {text}{check}")',
        [],
    ),
    # --- not a validation metric line: nothing to say -------------------------------------------
    "no-float": ('print(f"validation split holds {n} examples")', []),
    "float-but-not-validation": ('print(f"test accuracy: {a:.4f}{check}")', []),
    "hoisted-but-not-validation": (
        'text = f"{a:.2f}"\nprint(f"test accuracy: {text}{check}")',
        [],
    ),
    # recipe 32's test-split overlap figure: "validation" reaches the line only through a name
    # bound to a string that builds no float, and the line is not a validation metric
    "the-word-only-through-an-unrelated-binding": (
        'other_split = "validation"\n'
        'print(f"test candidates also in the {other_split} split: {k / n:.4f}{check}")',
        [],
    ),
    # a label whose own definition says "validation" does not make every line that prints it one
    "a-selection-label-that-names-validation": (
        'selection = " (selection: chosen on validation)"\n'
        'print(f"test accuracy: {a:.4f}{selection}{check}")',
        [],
    ),
    # "validation" only in an identifier or keyword inside the float string is not printed: not a
    # validation line
    "the-word-only-in-an-identifier-of-the-float-string": (
        'rows = ", ".join(f"{n} {v:.2f}" for n, v in input_validation_concerns)\n'
        'print(f"concern scores: {rows}")',
        [],
    ),
    "the-word-only-in-a-keyword-of-the-float-string": (
        'rows = fmt(v, mode="x", validation=1) + f" {v:.2f}"\nprint(f"concern scores: {rows}")',
        [],
    ),
    # a float rounded by a call, not a format spec, is outside this check (documented)
    "rounding-by-round-is-not-a-format-spec": (
        'print(f"validation accuracy: {round(a, 4)}")',
        [],
    ),
    # --- a validation line that lacks a label fails ---------------------------------------------
    "inline-unlabelled": ('print(f"validation accuracy: {a:.4f}")', [BOTH]),
    "inline-no-selection": ('print(f"validation accuracy: {a:.4f}{check}")', [["{selection}"]]),
    "inline-no-check": ('print(f"validation accuracy: {a:.4f}{selection}")', [["{check}"]]),
    "aligned-unlabelled": (
        """print(f"{'validation':<28} {n:>8} {a:>13.4f} {b:>20.4f}")""",
        [BOTH],
    ),
    "aligned-no-selection": (
        """print(f"{'validation':<28} {a:>13.4f}{check}")""",
        [["{selection}"]],
    ),
    "hoisted-unlabelled": (
        'text = f"{a:.2f}"\nprint(f"  validation wrongly selected anyway: {text}")',
        [BOTH],
    ),
    "hoisted-no-selection": (
        'text = f"{a:.2f}"\nprint(f"validation accuracy: {text}{check}")',
        [["{selection}"]],
    ),
    "hoisted-no-check": (
        'text = f"{a:.2f}"\nprint(f"validation accuracy: {text}{selection}")',
        [["{check}"]],
    ),
    "hoisted-through-a-join-unlabelled": (
        'rows = ", ".join(f"{t} {c:.2f}" for t, c in wrong)\n'
        'print(f"validation wrong selection\'s confidence: {rows}")',
        [BOTH],
    ),
    "hoisted-two-hops-unlabelled": (
        'text = f"{a:.2f}"\nline = f"({text})"\nprint(f"validation accuracy {line}")',
        [BOTH],
    ),
    "hoisted-the-whole-line-unlabelled": (
        'line = f"validation accuracy: {a:.2f}"\nprint(line)',
        [BOTH],
    ),
    "hoisted-in-another-cell-unlabelled": (
        'text = f"{a:.2f}"' + NEXT_CELL + 'print(f"validation accuracy: {text}")',
        [BOTH],
    ),
    # a name assigned twice carries a label only if every assignment does, including an
    # assignment that builds no float
    "label-in-an-earlier-assignment-that-the-line-no-longer-prints": (
        'row = f"{a:.2f}{selection}{check}"\n'
        'print(f"validation accuracy: {row}")\n'
        'row = "no float here"\n'
        'print(f"validation risk: {row} {b:.4f}")',
        [BOTH, BOTH],  # flow-insensitive: the first print is reported too, the safe direction
    ),
    "label-in-only-one-of-two-assignments": (
        'text = f"{a:.2f}{selection}{check}"\ntext = f"{b:.2f}"\n'
        'print(f"validation accuracy {text}")',
        [BOTH],
    ),
    "a-cycle-of-bindings-terminates": (
        'a = f"{b}{x:.2f}"\nb = f"{a}"\nprint(f"validation accuracy {a}")',
        [BOTH],
    ),
    # --- quirk 1 of #234, kept on purpose: a suffix built by concatenation fails ----------------
    "concatenated-suffix": ('print(f"validation accuracy: {a:.4f}" + selection + check)', [BOTH]),
    "concatenated-suffix-hoisted": (
        'text = f"{a:.2f}"\nprint(f"validation accuracy: {text}" + selection + check)',
        [BOTH],
    ),
    # --- two prints, one bad ---------------------------------------------------------------------
    "one-of-two-prints-is-unlabelled": (
        'print(f"validation accuracy: {a:.4f}{selection}{check}")\n'
        'print(f"validation risk: {r:.4f}")',
        [BOTH],
    ),
}


def _validation_cells(source: str) -> list[tuple[str, str]]:
    return [(f"c{i}", part) for i, part in enumerate(source.split(NEXT_CELL))]


@pytest.mark.parametrize("case", sorted(_VALIDATION_LINES))
def test_the_validation_metric_line_check_on_each_shape(case):
    """The table every shape of #234 and #270 is held to: what passes, what fails with which
    label missing, and the shapes that are deliberately not a validation metric line."""
    source, expected = _VALIDATION_LINES[case]
    found = _validation_metric_lines_missing_labels(_validation_cells(source))
    assert [missing for _, _, missing in found] == expected, found


def test_a_cell_that_does_not_parse_is_still_read_by_the_text_of_its_prints():
    """Fails closed: a notebook cell with a magic is not skipped, it is read as it always was."""
    source = "%matplotlib inline\nprint(f'validation accuracy: {a:>8.4f}')"
    found = _validation_metric_lines_missing_labels([("magic", source)])
    assert [missing for _, _, missing in found] == [BOTH]
    labelled = "%matplotlib inline\nprint(f'validation accuracy: {a:>8.4f}{selection}{check}')"
    assert not _validation_metric_lines_missing_labels([("magic", labelled)])


def _real_cell_source(slug: str, cell_id: str) -> str:
    return cell_source(
        next(
            cell for cell in notebook_cells(recipe_dir({"slug": slug})) if cell.get("id") == cell_id
        )
    )


def test_recipe_28s_hoisted_validation_line_is_read_and_held_to_both_labels():
    """The real instance #234 describes: recipe 28's ``confidence-gate`` cell formats the wrong
    selection's confidence in ``val_wrong_text`` (a join over f-strings) before it prints it. The
    unmutated cell has nothing missing; taking ``{selection}`` or ``{check}`` off only that line
    is caught, and it names that line. The check used to see neither mutation."""
    source = _real_cell_source("28-skill-selection", "confidence-gate")
    line = 'print(f"validation wrong selection\'s confidence: {val_wrong_text}{selection}{check}")'
    assert line in source
    assert not _validation_metric_lines_missing_labels([("confidence-gate", source)])
    for removed in ("{selection}", "{check}"):
        mutated = source.replace(line, line.replace(removed, ""))
        found = _validation_metric_lines_missing_labels([("confidence-gate", mutated)])
        assert [(missing, "val_wrong_text" in call) for _, call, missing in found] == [
            ([removed], True)
        ], (removed, found)


def test_recipe_43s_aligned_baselines_table_is_read_by_the_metric_line_check():
    """The real instance #270 describes: recipe 43's ``evaluation-baselines`` rows are aligned
    (``{x:>20.4f}``), so ``FLOAT_FORMAT`` did not see them and ``{check}`` could be dropped from
    any row without a guard noticing. It is caught now, and only that row is named."""
    source = _real_cell_source("43-failure-recovery-selection", "evaluation-baselines")
    row = 'f"{always_task.accuracy:>20.4f}{check}"'
    assert source.count(row) == 1
    assert not _metric_lines_missing_check(source)
    missing = _metric_lines_missing_check(source.replace(row, 'f"{always_task.accuracy:>20.4f}"'))
    assert len(missing) == 1 and "'always retry'" in missing[0], missing


_ALIGNED_METRIC_LINES = {
    "labelled": (
        """print(f"{'a':<28} {raw:>13.4f} {cov.coverage:>10.4f}{check}")""",
        False,
    ),
    "unlabelled": ("""print(f"{'a':<28} {raw:>13.4f} {cov.coverage:>10.4f}")""", True),
    "unlabelled-centred": ('print(f"accuracy {a:^10.4f}")', True),
    "label-bound-to-a-suffix": ('suffix = check\nprint(f"accuracy {a:>10.4f}{suffix}")', False),
    "no-metric-word": ('print(f"{name:<28} {value:>13.4f}")', False),
    # METRIC_KEYWORD's \bcoverage\b does not see inside min_coverage: out of scope, on purpose
    # (#270's second comment, the other direction)
    "min_coverage-is-not-the-word-coverage": ('print(f"min_coverage {x:>8.4f}")', False),
    "not-a-float": ('print(f"accuracy {a:>10}")', False),
}


@pytest.mark.parametrize("case", sorted(_ALIGNED_METRIC_LINES))
def test_an_aligned_metric_line_is_held_to_the_check_label(case):
    source, fails = _ALIGNED_METRIC_LINES[case]
    assert bool(_metric_lines_missing_check(source)) is fails


# --------------------------------------------------------------------------------------------
# check 4c (of G1(d)): a plot_*'s title carries {check} and not {selection}
# --------------------------------------------------------------------------------------------

METRIC_PLOTS = ("plot_confusion_matrix", "plot_threshold_sweep", "plot_risk_coverage")
TITLE_ARG = re.compile(r'title\s*=\s*(f?"(?:[^"\\]|\\.)*"|f?\'(?:[^\'\\]|\\.)*\')')


@pytest.mark.parametrize("recipe", guarded("figure_titles_check_only"))
def test_metric_figure_titles_carry_check_and_not_selection(recipe):
    """docs/notebook-style.md "Title convention": a figure's title carries the pipeline-check
    disclosure ``{check}`` and no other disclosure label, even when it is drawn from
    ``validation`` -- a figure is never additionally re-labelled as a selection step the way a
    printed number is.

    Scoped to the three evaluation chart helpers (``plot_confusion_matrix``,
    ``plot_threshold_sweep``, ``plot_risk_coverage``): ``plot_answer_probabilities`` draws one
    answer for the "One answer up close" section, not a split's metrics, and the template's own
    plain, descriptive titles there ("A review with conflicting signal") correctly carry neither
    label."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    violations = []
    for cell in notebook_cells(recipe_dir(recipe)) if nb.is_file() else []:
        if cell["cell_type"] != "code":
            continue
        source = cell_source(cell)
        for fn in METRIC_PLOTS:
            for call in extract_calls(source, fn):
                match = TITLE_ARG.search(call)
                if match is None:
                    violations.append(f"cell {cell.get('id', '?')} {fn}(...) has no title=")
                    continue
                title = match.group(1)
                if "{check}" not in title:
                    violations.append(
                        f"cell {cell.get('id', '?')} {fn} title missing {{check}}: {title}"
                    )
                if "{selection}" in title:
                    violations.append(
                        f"cell {cell.get('id', '?')} {fn} title has {{selection}}: {title}"
                    )
    assert not violations, "; ".join(violations)


# --------------------------------------------------------------------------------------------
# check 5: print what you plot
# --------------------------------------------------------------------------------------------

PRINTED_TABLE_PLOTS = ("plot_confusion_matrix", "plot_risk_coverage", "plot_threshold_sweep")
FIRST_ARG = re.compile(r"\(\s*([A-Za-z_][A-Za-z0-9_.]*)")


def _derived_from(tree: ast.AST, seed: str) -> set[str]:
    """Names whose value is assigned, directly or transitively, from an expression mentioning
    ``seed`` -- the fixed-point simple-assignment half of ``_labelled_names``, reused here for
    one name instead of a disclosure label (recipe 18's ``zipped = zip(curve.thresholds, ...)``,
    read from ``curve``)."""
    derived = {seed}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id not in derived
                and derived & _ast_names(node.value)
            ):
                derived.add(node.targets[0].id)
                changed = True
    return derived


def _body_calls_print(stmts: list[ast.stmt]) -> bool:
    return any(
        isinstance(call.func, ast.Name) and call.func.id == "print" for call in _calls_in(stmts)
    )


def _cell_prints_the_plotted_object(source: str, name: str) -> bool:
    """True if ``source`` prints ``name`` (or a plain-assignment descendant of it) either
    directly -- a ``print(...)`` call whose argument subtree references such a name -- or
    indirectly, via a ``for`` loop whose iterable references one and whose body calls ``print``
    (the template's ``for gold_label, row in zip(matrix.labels, matrix.matrix.tolist(), ...):
    ... print(...)``, recipe 21's identical shape, and recipe 18's one-hop ``zipped = zip(curve.
    ...)`` then ``for ... in zipped: print(...)``, covered by ``_derived_from`` first)."""
    tree = ast.parse(source)
    derived = _derived_from(tree, name)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            if derived & {
                nm
                for arg in (*node.args, *(kw.value for kw in node.keywords))
                for nm in _ast_names(arg)
            }:
                return True
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.For)
            and derived & _ast_names(node.iter)
            and _body_calls_print(node.body)
        ):
            return True
    return False


@pytest.mark.parametrize("recipe", guarded("print_what_you_plot"))
def test_every_plot_call_has_a_printed_table(recipe):
    """G1(e), docs/recipe-template.md and docs/notebook-style.md "Print what you plot" ("Pair
    every plot_* call with a print of the same data, rounded, in the same cell"; sweep helpers
    are named explicitly alongside the confusion matrix in recipe-template.md). CI's figure
    comparison is loose, so the printed numbers are what actually pins the plotted data byte for
    byte.

    For every ``plot_confusion_matrix(``, ``plot_risk_coverage(`` or ``plot_threshold_sweep(``
    call, in the *same* cell only (the contract names the same cell, and a preceding-cell
    allowance was checked and found to add nothing real: it only ever let an unrelated print
    satisfy this), take its first positional argument's base name (``matrix``, ``curve``, the
    part before any ``.`` attribute access) and require
    ``_cell_prints_the_plotted_object``: a ``print`` whose argument subtree names that object
    (directly, or via a ``for`` loop over it). What this actually requires is narrower than "the
    same data the figure draws" reads as, on purpose and honestly stated: it is satisfied by any
    print derived from the plotted object, including a count merely derived from it and not its
    full table, which this check does not tell apart from one -- a cell that prints a number
    computed independently of the plotted object (an overall accuracy from `test_gold`/
    `test_answers` directly, say) is the one shape this reliably catches."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    if not nb.is_file():
        pytest.skip("no notebook")
    violations = []
    for cell in notebook_cells(recipe_dir(recipe)):
        if cell["cell_type"] != "code":
            continue
        source = cell_source(cell)
        for fn in PRINTED_TABLE_PLOTS:
            for call in extract_calls(source, fn):
                match = FIRST_ARG.search(call)
                if match is None:
                    violations.append(
                        f"cell {cell.get('id', '?')} {fn}(...) has no plain first argument"
                    )
                    continue
                name = match.group(1).split(".")[0]
                if not _cell_prints_the_plotted_object(source, name):
                    violations.append(
                        f"cell {cell.get('id', '?')} {fn}({name}, ...) prints nothing of {name}"
                    )
    assert not violations, "; ".join(violations)


# --------------------------------------------------------------------------------------------
# check 5b (#232): every plot_* cell has a committed image output
# --------------------------------------------------------------------------------------------

_PLOT_CALL_TEXT = re.compile(r"\bplot_[A-Za-z0-9_]*\s*\(")


def _cell_calls_a_plot_function(source: str) -> bool:
    """True if ``source`` calls any ``plot_*`` function (a name or an attribute). Parsed, so a
    comment or a string that merely mentions one does not count; a cell that does not parse
    (a magic) falls back to the text pattern, which can only over-select."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return bool(_PLOT_CALL_TEXT.search(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if isinstance(name, str) and name.startswith("plot_"):
                return True
    return False


def _cell_has_image_output(cell: dict) -> bool:
    return any(
        output.get("output_type") in {"display_data", "execute_result"}
        and any(
            mime.startswith("image/") and value
            for mime, value in (output.get("data") or {}).items()
        )
        for output in cell.get("outputs") or []
    )


def _plot_cells_without_images(cells: list[dict]) -> list[str]:
    return [
        f"cell {cell.get('id', index)}: calls a plot_* function but has no committed image/* output"
        for index, cell in enumerate(cells)
        if cell.get("cell_type") == "code"
        and _cell_calls_a_plot_function(cell_source(cell))
        and not _cell_has_image_output(cell)
    ]


@pytest.mark.parametrize("recipe", guarded("plot_cells_have_images"))
def test_every_plot_cell_has_a_committed_image(recipe):
    """#232: for every code cell calling a ``plot_*`` function, require a committed ``image/*``
    output in that cell. Static, no execution; keyed on the property (an image was committed),
    not on PNG. See the table at the top of this module for what it does not see."""
    if not (recipe_dir(recipe) / "notebook.ipynb").is_file():
        pytest.skip("no notebook")
    violations = _plot_cells_without_images(notebook_cells(recipe_dir(recipe)))
    assert not violations, "; ".join(violations)


def _plot_cell(outputs, source="plot_risk_coverage(curve)\nprint(curve)"):
    return {"cell_type": "code", "id": "plot-cell", "source": source, "outputs": outputs}


_IMAGE_OUTPUT = {"output_type": "display_data", "data": {"image/png": "stored"}, "metadata": {}}


def _real_plot_cells(cells):
    return [
        c for c in cells if c["cell_type"] == "code" and _cell_calls_a_plot_function(cell_source(c))
    ]


def test_plot_cell_guard_has_a_real_published_plot_cell_to_discriminate_on():
    cells = notebook_cells(RECIPES_DIR / "41-approval-scope-review")
    assert _real_plot_cells(cells), "recipe 41 should contain a plot cell"
    assert _plot_cells_without_images(cells) == []


def test_removing_a_real_plot_cells_image_fails_the_plot_cell_guard():
    cells = json.loads(json.dumps(notebook_cells(RECIPES_DIR / "41-approval-scope-review")))
    removed = 0
    for cell in _real_plot_cells(cells):
        for output in cell.get("outputs", []):
            for mime in [m for m in output.get("data", {}) if m.startswith("image/")]:
                del output["data"][mime]
                removed += 1
    assert removed, "the mutation must remove a real committed image"
    assert _plot_cells_without_images(cells)


def test_a_plot_cell_whose_image_moved_to_another_cell_fails():
    # Per cell, not per notebook: the figure exists in the notebook, in the wrong cell.
    cells = [_plot_cell([]), {"cell_type": "code", "source": "x = 1", "outputs": [_IMAGE_OUTPUT]}]
    assert len(_plot_cells_without_images(cells)) == 1


@pytest.mark.parametrize(
    "outputs",
    [
        [],
        [{"output_type": "stream", "name": "stdout", "text": "image/png"}],
        [{"output_type": "display_data", "data": {"text/plain": "<Figure size 1x1>"}}],
        [{"output_type": "display_data", "data": {"image/png": ""}}],
        [{"output_type": "stream", "data": {"image/png": "stored"}}],
    ],
    ids=["empty-outputs", "text-only-stream", "text-plain-repr", "empty-image", "image-in-stream"],
)
def test_a_plot_cell_without_an_image_output_fails(outputs):
    assert _plot_cells_without_images([_plot_cell(outputs)])


def test_a_plot_cell_with_no_outputs_key_fails():
    cell = _plot_cell([])
    del cell["outputs"]
    assert _plot_cells_without_images([cell])


@pytest.mark.parametrize(
    "mime", ["image/png", "image/svg+xml", "image/jpeg"], ids=["png", "svg", "jpeg"]
)
@pytest.mark.parametrize("output_type", ["display_data", "execute_result"])
def test_any_image_mime_in_the_plot_cell_passes(mime, output_type):
    output = {"output_type": output_type, "data": {mime: "stored"}}
    assert _plot_cells_without_images([_plot_cell([output])]) == []


def test_a_list_source_and_an_attribute_call_are_both_seen():
    cell = _plot_cell([], source=["style.plot_threshold_sweep(", "    curve)"])
    assert _plot_cells_without_images([cell])


@pytest.mark.parametrize(
    "source",
    [
        "# plot_risk_coverage(curve)",
        "label = 'plot_risk_coverage(curve)'",
        "x = 1",
        "plot_data = 2",
    ],
    ids=["comment", "string", "no-plot", "name-not-call"],
)
def test_a_cell_that_does_not_call_a_plot_function_needs_no_image(source):
    assert _plot_cells_without_images([_plot_cell([], source=source)]) == []


def test_a_markdown_cell_naming_a_plot_call_needs_no_image():
    cell = {"cell_type": "markdown", "source": "plot_risk_coverage(curve)"}
    assert _plot_cells_without_images([cell]) == []


@pytest.mark.parametrize(
    "source",
    ["plotted = 1\nplotting(rows)", "plot(rows)", "plotly(rows)", "x.plot(rows)"],
    ids=["plotting", "bare-plot", "plotly", "plot-method"],
)
def test_the_plot_underscore_prefix_is_pinned(source):
    """Widening the prefix from ``plot_`` to ``plot`` would select these cells (#655)."""
    assert not _cell_calls_a_plot_function(source)
    assert _plot_cells_without_images([_plot_cell([], source=source)]) == []


def test_a_bare_plot_underscore_call_is_the_shortest_selected_name():
    assert _cell_calls_a_plot_function("plot_x(1)")
    assert _cell_calls_a_plot_function("style.plot_x(1)")


def _guarded_check_ids() -> set[str]:
    """Every check id registered through a real ``guarded("...")`` call in this module, found
    with ``ast`` so a call that spans several lines counts and a string that merely contains
    ``guarded("example")`` (test scaffolding) does not."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "guarded"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _table_check_ids(doc: str) -> set[str]:
    """The check ids in the first column of the module docstring's check table."""
    table = doc.split("check id", 1)[1].split("Scope decisions", 1)[0]
    return set(re.findall(r"^``([a-z0-9_]+)``", table, re.MULTILINE))


def test_the_check_table_lists_exactly_the_guarded_check_ids():
    """docs/notebook-ci.md points readers at the table as the list of rules (#655), so every
    ``guarded()`` id needs a row (plus ``fixture_arithmetic``, which is not registered through
    ``guarded``) and no row may name an id that does not exist."""
    expected = _guarded_check_ids() | {"fixture_arithmetic"}
    assert "simulated_side_effect_invoked" in expected  # multi-line calls are counted
    assert "example" not in expected  # scaffolding inside a string is not a check
    table = _table_check_ids(__doc__)
    assert table == expected, (
        f"guarded ids with no table row: {sorted(expected - table)}; "
        f"table rows with no guarded id: {sorted(table - expected)}"
    )


def test_the_table_completeness_test_fails_when_a_row_is_missing():
    doc = __doc__.replace("``simulated_side_effect_invoked``", "``x``", 1)
    assert _table_check_ids(doc) != _guarded_check_ids() | {"fixture_arithmetic"}


# Figure sources the guard does not see (#655). Each is listed under "Not seen" in the check table
# at the top of this module (the second element is the words that line must contain), not detected:
# a static name rule that chased them would risk false positives on a published recipe.
UNSEEN_PLOT_SOURCES = {
    "import alias": (
        "from jev_cookbook.style import plot_risk_coverage as prc\nprc(curve)",
        "import alias",
    ),
    "assigned alias": ("f = style.plot_risk_coverage\nf(curve)", "assigned alias"),
    "getattr": ('getattr(style, "plot_risk_coverage")(curve)', "getattr"),
    "functools.partial": ("functools.partial(style.plot_risk_coverage, curve)()", "partial"),
    "direct Figure": ("fig = Figure()\nax = fig.subplots()\nfig", "Figure"),
    "display of a helper image": ("display(helpers.render_image(row))", "display"),
    "cross-cell wrapper": ("draw(curve)", "wrapper defined in one"),
}


@pytest.mark.parametrize("name", list(UNSEEN_PLOT_SOURCES))
def test_each_unseen_figure_source_is_listed_in_the_check_table_and_stays_unseen(name):
    """If one of these becomes detected, move it out of the table's "Not seen" line and into the
    covered rule, with a must-fail test; if the line loses a source, this fails."""
    source, words = UNSEEN_PLOT_SOURCES[name]
    assert _plot_cells_without_images([_plot_cell([], source=source)]) == []
    row = __doc__.split("``plot_cells_have_images``", 1)[1].split("``next_steps_links_exist``")[0]
    assert "Not seen (#655)" in row
    assert re.search(words, re.sub(r"\s+", " ", row))


def test_an_unparsable_plot_cell_is_still_checked():
    cell = _plot_cell([], source="%matplotlib inline\nplot_risk_coverage(curve)")
    assert _plot_cells_without_images([cell])


# --------------------------------------------------------------------------------------------
# check 6: every Next-steps link target exists on disk
# --------------------------------------------------------------------------------------------

NEIGHBOUR_FOLDER = r"\.\./((?:[0-9]{2}|100)-[a-z0-9-]+)/"
NEIGHBOUR_LINK = re.compile(rf"\]\({NEIGHBOUR_FOLDER}\)")
NEIGHBOUR_HREF = re.compile(NEIGHBOUR_FOLDER)


def test_recipe_100_next_steps_link_must_resolve_to_a_published_notebook(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "RECIPES_DIR", tmp_path)
    source = tmp_path / "01-source"
    source.mkdir()
    target = "100-multimodal-agent-handoff-verification"
    (source / "notebook.ipynb").write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "markdown",
                        "id": "next-md",
                        "source": f"[Handoff](../{target}/)",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="100-multimodal-agent-handoff-verification"):
        test_next_steps_links_resolve_to_a_published_recipe({"slug": source.name})
    (tmp_path / target).mkdir()
    (tmp_path / target / "notebook.ipynb").write_text("{}", encoding="utf-8")
    test_next_steps_links_resolve_to_a_published_recipe({"slug": source.name})


@pytest.mark.parametrize("recipe", guarded("next_steps_links_exist"))
def test_next_steps_links_resolve_to_a_published_recipe(recipe):
    """G1(f), docs/recipe-template.md: "Link only a recipe whose notebook.ipynb is already
    committed on main: a folder link to one that is not yet published would 404 on GitHub, and
    that forward link is not allowed." Scans every markdown cell (not only the one named
    ``next-md``: the suffix is cosmetic, see docs/recipe-template.md "Cell ids"), for a
    ``](../NN-slug/)`` folder link, and requires ``recipes/NN-slug/notebook.ipynb`` to exist."""
    nb = recipe_dir(recipe) / "notebook.ipynb"
    if not nb.is_file():
        pytest.skip("no notebook")
    missing = []
    for cell in notebook_cells(recipe_dir(recipe)):
        if cell["cell_type"] != "markdown":
            continue
        for slug in NEIGHBOUR_LINK.findall(cell_source(cell)):
            if not (RECIPES_DIR / slug / "notebook.ipynb").is_file():
                missing.append(f"cell {cell.get('id', '?')} links ../{slug}/, not published")
    assert not missing, "; ".join(missing)


_MARKDOWN = MarkdownIt("commonmark")


def _next_steps_targets(markdown: str) -> set[str]:
    """Find recipe-folder links in a top-level Next steps section of one Markdown cell."""
    targets = set()
    in_next_steps = False
    tokens = iter(_MARKDOWN.parse(markdown))
    for token in tokens:
        if token.type == "heading_open" and token.level == 0 and token.tag in {"h1", "h2"}:
            heading = next(tokens)
            title = "".join(
                " " if part.type in {"softbreak", "hardbreak"} else part.content
                for part in heading.children or ()
                if part.type != "html_inline"
            )
            in_next_steps = token.tag == "h2" and title.split() == ["Next", "steps"]
        elif in_next_steps and token.type == "inline":
            for part in token.children or ():
                if part.type == "link_open":
                    href = part.attrGet("href")
                    match = NEIGHBOUR_HREF.fullmatch(href) if isinstance(href, str) else None
                    if match:
                        targets.add(match[1])
    return targets


def _inbound_next_steps_links() -> dict[str, set[str]]:
    """Map each published slug to the recipes that link to it from their Next steps section."""
    inbound: dict[str, set[str]] = {r["slug"]: set() for r in PUBLISHED}
    for recipe in PUBLISHED:
        for cell in notebook_cells(recipe_dir(recipe)):
            if cell["cell_type"] != "markdown":
                continue
            for slug in _next_steps_targets(cell_source(cell)):
                if slug in inbound and slug != recipe["slug"]:
                    inbound[slug].add(recipe["slug"])
    return inbound


INBOUND_NEXT_STEPS_LINKS = _inbound_next_steps_links()


def test_inbound_next_steps_audit_rejects_a_mid_notebook_only_link(tmp_path, monkeypatch):
    source = {"slug": "01-source"}
    target = {"slug": "02-target"}
    monkeypatch.setitem(globals(), "PUBLISHED", [source, target])
    monkeypatch.setitem(globals(), "RECIPES_DIR", tmp_path)
    for recipe in (source, target):
        recipe_dir(recipe).mkdir()
    (recipe_dir(target) / "notebook.ipynb").write_text('{"cells": []}', encoding="utf-8")

    link = "[Try the target recipe](../02-target/)\n"
    explanation = {"cell_type": "markdown", "id": "next-md", "source": ["## Explanation\n"]}
    next_steps = {
        "cell_type": "markdown",
        "id": "closing-notes",
        "source": ["## Next steps\n", "\n", link],
    }
    notebook = recipe_dir(source) / "notebook.ipynb"
    cells = {"cells": [explanation, next_steps]}
    notebook.write_text(json.dumps(cells), encoding="utf-8")
    monkeypatch.setitem(globals(), "INBOUND_NEXT_STEPS_LINKS", _inbound_next_steps_links())
    test_every_recipe_is_linked_from_some_other_recipes_next_steps(target)

    explanation["source"].append(next_steps["source"].pop())
    next_steps["source"].extend(["## Appendix\n", "\n", link])
    notebook.write_text(json.dumps(cells), encoding="utf-8")
    monkeypatch.setitem(globals(), "INBOUND_NEXT_STEPS_LINKS", _inbound_next_steps_links())
    with pytest.raises(AssertionError, match="02-target: no other published recipe's Next steps"):
        test_every_recipe_is_linked_from_some_other_recipes_next_steps(target)


@pytest.mark.parametrize(
    "before_link, after_link, counts",
    [
        pytest.param(" \t\r\n\r\n## Next steps\r\n", "", True, id="blank-prefix"),
        pytest.param("Closing remarks.\n\n## Next steps\n", "", True, id="prose-prefix"),
        pytest.param("Closing remarks.\n", "\n## Next steps\n", False, id="before-heading"),
        pytest.param("```md\n## Next steps\n", "\n```\n", False, id="fenced-heading"),
        pytest.param("## Next steps\n\n~~~md\n", "\n~~~\n", False, id="fenced-link"),
        pytest.param("## Next steps\n\n~~~\n", "", False, id="unclosed-fence"),
        pytest.param(
            "## Next steps\n\n  ````md\n```\n## Appendix\n  ````\n\n### More reading\n",
            "",
            True,
            id="fenced-appendix",
        ),
        pytest.param("## Next steps\n\n## Appendix\n", "", False, id="real-appendix"),
        pytest.param("<!--\n## Next steps\n-->\n\n", "", False, id="commented-heading"),
        pytest.param("## Next steps\n\n<!--\n", "\n-->\n", False, id="commented-link"),
        pytest.param("## Next steps\n\n<!--\n", "", False, id="unclosed-comment"),
        pytest.param(
            "## Next steps\n\n<!--\n## Appendix\n```\n-->\n\n",
            "",
            True,
            id="commented-appendix-and-fence",
        ),
        pytest.param("## Next steps\n\n```md\n<!--\n```\n\n", "", True, id="fenced-comment-opener"),
        pytest.param("## Next steps\n\nExample: ``", "``\n", False, id="inline-literal-link"),
        pytest.param("## Next steps\n\nType `<!--` then ", "", True, id="inline-comment-opener"),
        pytest.param(
            "Remarks with a stray `.\n\n## Next steps\n", " `\n", True, id="stray-backtick"
        ),
        pytest.param("## Next steps\n\n- First\n  - Second\n    ", "", True, id="nested-list-link"),
        pytest.param("## Next steps\n\n> ```md\n> ", "\n> ```\n", False, id="quoted-fence"),
        pytest.param("## Next steps\n\n    ", "", False, id="indented-code"),
        pytest.param("## Next steps\n\nExample: `\n", "`", False, id="multiline-code-span"),
        pytest.param("## Next steps\n\nAppendix\n--------\n\n", "", False, id="setext-appendix"),
        pytest.param("## Next steps <!-- editorial note -->\n\n", "", True, id="heading-comment"),
        pytest.param(
            "## Next <!-- editorial note --> steps\n\n", "", True, id="comment-between-words"
        ),
        pytest.param("Next\nsteps\n----------\n\n", "", True, id="wrapped-setext-title"),
        pytest.param("## Next steps\n\n!", "", False, id="image-is-not-a-link"),
    ],
)
def test_inbound_next_steps_audit_respects_markdown_boundaries(
    tmp_path, monkeypatch, before_link, after_link, counts
):
    source = {"slug": "01-source"}
    target = {"slug": "02-target"}
    monkeypatch.setitem(globals(), "PUBLISHED", [source, target])
    monkeypatch.setitem(globals(), "RECIPES_DIR", tmp_path)
    link = "[Try the target recipe](../02-target/)"
    for recipe, cells in (
        (source, [{"cell_type": "markdown", "source": before_link + link + after_link}]),
        (target, []),
    ):
        folder = recipe_dir(recipe)
        folder.mkdir()
        (folder / "notebook.ipynb").write_text(json.dumps({"cells": cells}), encoding="utf-8")
    assert _inbound_next_steps_links()[target["slug"]] == ({source["slug"]} if counts else set())


def test_inbound_next_steps_audit_resolves_markdown_reference_links():
    markdown = """[recipe]: ../02-target/

## Next steps

See [the neighbouring recipe][recipe].
"""
    assert _next_steps_targets(markdown) == {"02-target"}


# Inbound targets must be published in the catalog.
@pytest.mark.catalog_audit
@pytest.mark.parametrize("recipe", guarded("next_steps_inbound_links", skip_template="Unpublished"))
def test_every_recipe_is_linked_from_some_other_recipes_next_steps(recipe):
    """G1(f) clause 2 (issue #76 comment 6079429778): "every published recipe is the target of
    at least one other recipe's Next steps" (R21) -- a per-recipe, per-check case exactly like
    ``next_steps_links_exist`` (see the module docstring's scope decisions), computed once over
    the whole published set (``_inbound_next_steps_links``) and looked up per recipe here.
    A top-level H2 titled Next steps identifies the section within a Markdown cell. CommonMark
    link tokens with a recipe-folder destination count until the next top-level H1 or H2 or
    the end of the cell. Code, comments and raw HTML do not produce Markdown link tokens.

    Marked ``catalog_audit`` (#203) and deselected by default (see ``pyproject.toml``'s
    ``addopts``): a new recipe's own pull request can never satisfy this check. The recipe
    being added has no inbound link yet, and nothing in its own PR can create one -- no recipe
    on ``main`` may link forward to a recipe that is not yet published (``next_steps_links_exist``
    forbids exactly that), and a recipe pull request may change only its own folder (the
    ``Scope`` check), so it cannot add a backlink to itself from an older recipe either. The
    check is therefore run by hand at each wave close-out, after the sweep that adds the
    missing backlinks: ``pytest -m catalog_audit tests/test_recipe_guard.py``."""
    assert INBOUND_NEXT_STEPS_LINKS[recipe["slug"]], (
        f"{recipe['slug']}: no other published recipe's Next steps links ../{recipe['slug']}/"
    )


# --------------------------------------------------------------------------------------------
# check 7a/7b: helpers.REVIEW == "review"; the exact reason string in helpers.py
# --------------------------------------------------------------------------------------------

REASON_STRING = "confidence below the threshold"
# The identifier immediately preceding a confidence-gated review's reason string, e.g.
# "Routing(ticket, REVIEW, \"confidence below the threshold\")" or the tuple-unpacking
# "outcome, reason = UNCERTAIN, \"confidence below the review cutoff\"" (recipe 06's own,
# non-conforming text -- "confidence below" rather than the exact REASON_STRING, so this
# traces even the recipes review_reason_string already flags for a different reason).
CONFIDENCE_REASON_PREFIX = re.compile(r'(\w+)\s*,\s*"confidence below')
# Recipe 16's REVIEW_NEEDED names one of the rule's own question options, not the outcome a
# low-confidence answer is routed to; its real outcome, ESCALATE, is a legitimate
# domain-specific name (an escalation queue), not REVIEW renamed -- see the test's docstring.
NAMED_DOMAIN_OUTCOME_EXEMPTIONS = {
    "16-discord-moderation-triage": 'ESCALATE is a genuine domain-specific outcome, not "review" renamed',
}


@pytest.mark.parametrize("recipe", guarded("review_value_is_review"))
def test_review_outcome_value_is_review_where_it_exists(recipe):
    """docs/glossary.md#review: "the outcome value itself is the string 'review' (not, say,
    'human_review'; a recipe may still name its own domain-specific sub-reasons)." Checked
    directly where ``helpers.py`` defines a module-level ``REVIEW`` constant; traced where it
    does not, via the identifier immediately preceding a confidence-gated review's reason string
    (``'\\w+, "confidence below'``, loose enough to also find 06's non-conforming ``"confidence
    below the review cutoff"`` -- see ``review_reason_string`` for that drift -- not only the
    exact pinned text, since a recipe that fails one check should not be invisible to the other).

    Three recipes have no ``REVIEW`` constant today (06, 16, 21), and they are not the same kind
    of case. 16's constant is ``REVIEW_NEEDED``, naming one of the rule's own *question* options
    (something the model can answer), not the outcome a wrong or unconfident answer is routed to
    -- 16's actual review outcome, traced the same way, is ``ESCALATE``, a legitimate
    domain-specific name for "an escalation queue" (the glossary's "a recipe may still name its
    own domain-specific sub-reasons" clause, read for the outcome value rather than only the
    reason string, which is the only reading under which ``ESCALATE`` is not simply ``"review"``
    wearing a disguise). It is named here, once, as the one exemption the trace does not itself
    decide. 06 (``UNCERTAIN``) and 21 (``NEEDS_REVIEW``, value literally ``"needs_review"``) have
    no such claim: both read as a plain rename of the same review-queue outcome the glossary
    names, so the trace reports them as real failures -- recorded in the allowlist (their own
    reason naming #163, the sweep issue that owns this drift) rather than hidden behind a skip
    whose stated reason would not be the truth about them. (Not every check's allowlist entries
    name #163: see ``tests/recipe_guard_known_failures.py``'s own docstring.)"""
    helpers = load_helpers(recipe_dir(recipe))
    if hasattr(helpers, "REVIEW"):
        assert helpers.REVIEW == "review"
        return
    if recipe["slug"] in NAMED_DOMAIN_OUTCOME_EXEMPTIONS:
        pytest.skip(
            f"{recipe['slug']}: {NAMED_DOMAIN_OUTCOME_EXEMPTIONS[recipe['slug']]} "
            "(named exemption, not traced)"
        )
    text = (recipe_dir(recipe) / "helpers.py").read_text("utf-8")
    match = CONFIDENCE_REASON_PREFIX.search(text)
    assert match, (
        f"{recipe['slug']}: no REVIEW constant and no identifiable confidence-gated "
        "outcome for this check to trace"
    )
    value = getattr(helpers, match.group(1), None)
    assert value == "review", (
        f"{recipe['slug']}: the confidence-gated outcome ({match.group(1)}) is {value!r}, "
        'not "review"'
    )


# --- the reason string must be produced by a live review branch (#227) --------------------------
#
# docs/glossary.md#review words the rule conditionally -- "the reason string for a
# confidence-gated review is exactly ..." -- so it governs how a confidence-gated review is
# worded, not whether a recipe has one. The check used to be an unconditional substring search of
# helpers.py's text, which enforced something both stronger (every recipe has a gated review) and
# weaker (a comment, an unused constant or a dead function satisfies it): recipe 28 passed it on a
# sentence about a branch that does not exist, and recipe 35's first build passed it on a function
# nothing called. What it checks now is the property the glossary names, in three states:
#
# 1. a gate exists (``_live_gate_locations``): the exact words must be produced by executable code
#    in helpers.py, on a branch a confidence comparison controls, in a function the notebook
#    reaches, and a committed notebook output must show a review whose reason came out of the rule
#    rather than being typed into the cell that shows it;
# 2. no gate, and the recipe is a named gate-free design (``GATE_FREE_DESIGNS``): not applicable,
#    said so in the skip. The exemption is checked too: it fails once the recipe grows a live gate;
# 3. no gate, and no named design: a failure that names the absence, not "string missing".
#
# ``confidence_gate_from_shared_helper`` (#282) applies under the SAME predicate, so the two
# checks cannot disagree about whether a recipe has a gate, and a named gate-free design is not
# applicable to both.

# Recipes whose rule has no confidence-gated review by design. A named, reviewed exception in the
# module's existing style (see NAMED_DOMAIN_OUTCOME_EXEMPTIONS); a recipe pull request cannot edit
# this file, so a new gate-free recipe is a foundation-reviewed decision, never a string parked in
# a comment. Adding an entry here does not add a gate, and a dead gate is not the way out.
GATE_FREE_DESIGNS = {
    "28-skill-selection": (
        "score-and-margin selection with no per-answer confidence check: a gate chosen by "
        "select_confidence_threshold on its own auto-selected pool is inert on the committed "
        "fixtures (helpers.py, 'Why this rule has two review branches, not three', and "
        "test_no_confidence_gate_could_have_caught_the_wrong_selections_without_also_losing_"
        "correct_ones); reviewed as the recipe's design, not padding to be restored"
    ),
}

# Published recipes whose rule has a live confidence-gated review branch but whose committed
# notebook output never shows a review produced by it: RECORDED DRIFT, not a justification, so
# the convention is tests/recipe_guard_known_failures.py's -- every reason ends ``see #NNN``, the
# issue whose work list owns clearing the entry (#342). It is a list here, and not xfail(strict)
# entries there, because a strict xfail is satisfied by ANY failure and would stop holding these
# recipes to the static half (a live branch, a controlling comparison, wording, reachability).
# Here the static half runs first, in full, and only the committed-output half is reported as a
# skip carrying the recorded reason. The list is closed (a recipe pull request cannot add to it)
# and strict both ways: a recipe on it whose output starts showing a rule-produced review fails
# until the entry is removed, and a recipe off it must show one.
_NO_REVIEW_IN_OUTPUT = (
    "the live confidence-gated review branch is reachable from the notebook, but no committed "
    "output shows a review whose reason it produced; see #342"
)
REASON_NOT_IN_COMMITTED_OUTPUT = {
    slug: _NO_REVIEW_IN_OUTPUT
    for slug in (
        "42-outbound-disclosure-screening",
        "43-failure-recovery-selection",
        "45-memory-reconciliation",
        "46-semantic-context-paging",
        "48-document-revision-consistency",
        "49-multi-agent-task-assignment",
        "50-model-comparison-and-calibration",
    )
} | {
    "36-card-game-action-selection": (
        "the live confidence-gated review branch is reachable from the notebook, and the "
        "evaluation cell prints how many turns the gate sends to review, but labels the count "
        "with helpers.REASON_LOW_CONFIDENCE and takes it from evaluate_selective, which re-applies "
        "the gate, rather than from a review the rule returned; see #342"
    ),
}

_ORDERING_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_LEAVES_THE_BLOCK = (ast.Return, ast.Raise, ast.Continue, ast.Break)
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _identifier(node: ast.AST) -> str | None:
    """The name an expression is written with: ``x`` for ``x``, ``attr`` for ``obj.attr``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _compares_confidence(node: ast.AST) -> bool:
    """True if ``node``'s subtree has an ordering comparison (``<``, ``<=``, ``>``, ``>=``) with a
    confidence on either side: some name or attribute in the comparison with ``confidence`` in
    it (``answer.confidence``, ``min_confidence``, ``noul_confidence(noul)``). The property a
    confidence gate has by definition, rather than any spelling of the gate itself."""
    for compare in ast.walk(node):
        if isinstance(compare, ast.Compare) and any(
            isinstance(op, _ORDERING_OPS) for op in compare.ops
        ):
            for part in ast.walk(compare):
                name = _identifier(part)
                if name and "confidence" in name.lower():
                    return True
    return False


def _is_unit_bound(node: ast.AST) -> bool:
    """A literal 0 or 1 (``0``, ``0.0``, ``1``, ``1.0``): the ends of a confidence's own range."""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
        and node.value in (0, 1)
    )


def _mentions_confidence(node: ast.AST) -> bool:
    return any("confidence" in (_identifier(part) or "").lower() for part in ast.walk(node))


def _is_validation_guard(compare: ast.Compare, parents: dict[ast.AST, ast.AST]) -> bool:
    """Whether a comparison only validates an argument: it is in an ``assert``, or in the test of
    an ``if`` whose body does nothing but ``raise``."""
    node: ast.AST = compare
    while node in parents:
        parent = parents[node]
        if isinstance(parent, ast.Assert):
            return True
        if isinstance(parent, ast.If) and node is parent.test:
            return all(isinstance(stmt, ast.Raise) for stmt in parent.body)
        if isinstance(parent, ast.stmt):
            return False
        node = parent
    return False


def _confidence_bound_comparisons(tree: ast.AST) -> list[ast.Compare]:
    """The comparisons in ``tree`` that bound a confidence by something a recipe CHOOSES: an
    ordering comparison with a confidence on one side (``_compares_confidence``) that is not a
    range check on an argument. ``if not 0.0 <= min_confidence <= 1.0: raise ValueError(...)``
    (chained between literal 0 and 1, or a literal 0 or 1 in an ``assert`` or an ``if`` that only
    raises) validates a parameter and gates nothing, and a recipe whose only such comparison is
    a range check has no gate to freeze. ``answer.confidence >= 0.85`` is a gate, and stays one
    whether the number is a literal or a name."""
    parents = _parents(tree)
    found: list[ast.Compare] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Compare) and _compares_confidence(node)):
            continue
        others = [
            operand
            for operand in (node.left, *node.comparators)
            if not _mentions_confidence(operand)
        ]
        only_unit_bounds = bool(others) and all(_is_unit_bound(operand) for operand in others)
        if only_unit_bounds and (len(node.ops) >= 2 or _is_validation_guard(node, parents)):
            continue
        found.append(node)
    return found


def _confidence_derived_names(tree: ast.AST) -> set[str]:
    """Identifiers whose value is computed from a confidence comparison, to a fixpoint: a
    variable assigned, or a keyword argument given, an expression holding one
    (``gated = confidence < confidence_gate``), and anything assigned from those. A record built
    with ``LabelDecision(..., gated)`` and read back as ``decision.gated`` in another function
    is the multi-label recipes' shape, and ``if decision.gated:`` is a confidence-controlled
    branch even though the comparison itself sits elsewhere. By name, not by value: a name reused
    for something unrelated is over-credited, which this check accepts and says so."""
    derived: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            pairs: list[tuple[ast.AST, ast.AST]] = []
            if isinstance(node, ast.Assign):
                pairs = [(target, node.value) for target in node.targets]
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                pairs = [(node.target, node.value)]
            elif isinstance(node, ast.NamedExpr):
                pairs = [(node.target, node.value)]
            elif isinstance(node, ast.keyword) and node.arg is not None:
                names = {node.arg}
                if (
                    _compares_confidence(node.value) or _mentions_any(node.value, derived)
                ) and not names <= derived:
                    derived |= names
                    changed = True
                continue
            for target, value in pairs:
                names = {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
                if (
                    _compares_confidence(value) or _mentions_any(value, derived)
                ) and not names <= derived:
                    derived |= names
                    changed = True
    return derived


def _mentions_any(node: ast.AST, names: set[str]) -> bool:
    return any(_identifier(part) in names for part in ast.walk(node))


def _is_confidence_test(test: ast.AST, derived: set[str]) -> bool:
    """Whether a condition is a confidence comparison, or reads something derived from one."""
    return _compares_confidence(test) or _mentions_any(test, derived)


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, *_FUNCTION_NODES)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _names_bound_to_reason(target: ast.AST, value: ast.AST) -> set[str]:
    """The names ``target = value`` binds to a string holding the reason: ``NAME = "..."``, and
    element by element for ``A, B = "...", "..."``. Anything else binds nothing here."""
    if isinstance(target, ast.Name):
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return {target.id} if REASON_STRING in value.value else set()
        return set()
    if (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
    ):
        names: set[str] = set()
        for one_target, one_value in zip(target.elts, value.elts, strict=True):
            names |= _names_bound_to_reason(one_target, one_value)
        return names
    return set()


def _reason_constant_names(tree: ast.Module) -> set[str]:
    """Module-level names bound to a string holding the reason (``REASON_REVIEW = "confidence
    below the threshold"``), so a use of the NAME inside a function counts as a use of the words.
    Only assignment statements bind: a bare string statement at module level, and above all the
    module docstring every ``helpers.py`` has, is an expression statement with a string value and
    binds nothing (it used to be read as an assignment and raised ``AttributeError``)."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names |= _names_bound_to_reason(target, node.value)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            names |= _names_bound_to_reason(node.target, node.value)
    return names


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _live_reason_uses(tree: ast.Module) -> list[ast.AST]:
    """Every use of the reason string in EXECUTABLE code: the literal itself, or a module-level
    constant holding it, inside a function body. Not a comment (not in the AST at all), not a
    docstring, and not an unused module-level constant: those are the words without a branch."""
    docstrings = _docstring_constant_ids(tree)
    constants = _reason_constant_names(tree)
    parents = _parents(tree)
    uses: list[ast.AST] = []
    for node in ast.walk(tree):
        is_literal = (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and REASON_STRING in node.value
            and id(node) not in docstrings
        )
        is_constant = isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        is_constant = is_constant and node.id in constants
        if not (is_literal or is_constant):
            continue
        scope = node
        while scope in parents and not isinstance(scope, _FUNCTION_NODES):
            scope = parents[scope]
        if isinstance(scope, _FUNCTION_NODES):
            uses.append(node)
    return uses


def _near_miss_reasons(tree: ast.Module) -> list[str]:
    """Executable string literals that word a confidence-gated review's reason differently from
    the glossary ("confidence below the review cutoff"): recipe 06 once did, and the exact-text
    rule exists to stop the next one."""
    docstrings = _docstring_constant_ids(tree)
    return sorted(
        {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and node.value.startswith("confidence below")
            and REASON_STRING not in node.value
        }
    )


def _controlled_by_confidence(
    node: ast.AST, parents: dict[ast.AST, ast.AST], derived: set[str]
) -> bool:
    """Whether ``node`` runs only because of a confidence comparison: it sits inside an ``if``
    (either arm) or a conditional expression whose condition is one, or it follows, in the same
    block, an ``if`` on one whose body leaves the block (the guard clause
    ``if confidence >= gate: return ok`` then ``return REVIEW, reason``). Polarity is not judged:
    this establishes that a confidence comparison decides whether the reason is produced, not
    that it is the right way round -- the recipe's own tests own that."""
    child = node
    while child in parents:
        parent = parents[child]
        if (
            isinstance(parent, (ast.If, ast.IfExp))
            and child is not parent.test
            and _is_confidence_test(parent.test, derived)
        ):
            return True
        for field in ("body", "orelse", "finalbody"):
            block = getattr(parent, field, None)
            if isinstance(block, list) and child in block:
                for earlier in block[: block.index(child)]:
                    if (
                        isinstance(earlier, ast.If)
                        and isinstance(earlier.body[-1], _LEAVES_THE_BLOCK)
                        and _is_confidence_test(earlier.test, derived)
                    ):
                        return True
        if isinstance(parent, _FUNCTION_NODES):
            return False
        child = parent
    return False


def _notebook_code_trees(recipe_dir_: Path) -> tuple[list[tuple[dict, ast.Module]], list[str]]:
    """``([(cell, tree)], [ids of code cells that do not parse])`` for the committed notebook."""
    trees: list[tuple[dict, ast.Module]] = []
    unparseable: list[str] = []
    if (recipe_dir_ / "notebook.ipynb").is_file():
        for cell in notebook_cells(recipe_dir_):
            if cell["cell_type"] != "code":
                continue
            try:
                trees.append((cell, ast.parse(cell_source(cell))))
            except SyntaxError:
                unparseable.append(str(cell.get("id", "?")))
    return trees, unparseable


def _identifiers_in(tree: ast.AST) -> set[str]:
    return {name for part in ast.walk(tree) if (name := _identifier(part))}


def _reachable_helper_functions(
    helpers_tree: ast.Module, notebook_trees: list[ast.Module]
) -> set[str]:
    """Names of ``helpers.py`` functions the notebook can run: those it names, and, to a fixpoint,
    those named inside any such function. Name-based, so a different object's method of the same
    name over-counts; what it catches is a branch in a function nothing in the notebook mentions
    (recipe 35's first build)."""
    defs: dict[str, list[ast.AST]] = {}
    for node in ast.walk(helpers_tree):
        if isinstance(node, _FUNCTION_NODES):
            defs.setdefault(node.name, []).append(node)
    reachable = {name for tree in notebook_trees for name in _identifiers_in(tree)} & set(defs)
    frontier = list(reachable)
    while frontier:
        for func in defs[frontier.pop()]:
            for name in _identifiers_in(func) & set(defs):
                if name not in reachable:
                    reachable.add(name)
                    frontier.append(name)
    return reachable


def _cell_types_the_reason(tree: ast.Module, constant_names: set[str]) -> bool:
    """Whether a cell's own code writes the reason: the words as a string literal, or a
    ``helpers`` constant holding them. Output from such a cell shows what the cell typed, not
    what the rule produced."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if REASON_STRING in node.value:
                return True
    return bool(_identifiers_in(tree) & constant_names)


def _output_text(cell: dict) -> str:
    parts: list[str] = []
    for output in cell.get("outputs", []):
        if output.get("output_type") == "stream":
            parts.append("".join(output.get("text", "")))
        else:
            parts.append("".join(output.get("data", {}).get("text/plain", "")))
            parts.append("".join(output.get("data", {}).get("text/html", "")))
    return "\n".join(parts)


def _names_carrying_the_reason(trees: list[ast.Module], constant_names: set[str]) -> set[str]:
    """Names, across the WHOLE notebook, that hold the words the cell author wrote: a
    ``helpers`` reason constant, and any name bound in any cell to the words themselves (a
    literal or an f-string holding them) or to another such name (``msg = "confidence below the
    threshold"`` in one cell, ``print(msg)`` in the next). Judging each cell alone let a literal
    cross a cell boundary and be printed as if the rule had produced it. Only a plain binding is
    followed: the words carried through a container, a function's return value or a file read
    are not, and an output that comes that way is still accepted -- the evidence here is the
    words in an output, not a traced ``.reason`` expression."""
    carrying = set(constant_names)
    changed = True
    while changed:
        changed = False
        for tree in trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                    targets = [node.target]
                else:
                    continue
                value = getattr(node, "value", None)
                if value is None:
                    continue
                holds_the_words = isinstance(value, (ast.Constant, ast.JoinedStr)) and any(
                    isinstance(part, ast.Constant)
                    and isinstance(part.value, str)
                    and REASON_STRING in part.value
                    for part in ast.walk(value)
                )
                is_a_carrier = isinstance(value, (ast.Name, ast.Attribute)) and (
                    _identifier(value) in carrying
                )
                if holds_the_words or is_a_carrier:
                    names = {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
                    if not names <= carrying:
                        carrying |= names
                        changed = True
    return carrying


def _cells_showing_the_reason(
    notebook_trees: list[tuple[dict, ast.Module]], constant_names: set[str]
) -> list[str]:
    """Ids of the code cells whose committed output holds the reason string and whose own code
    does not write it, in the cell or by a name any cell bound to the words
    (``_names_carrying_the_reason``): evidence that a review the rule produced reached the
    reader."""
    carrying = _names_carrying_the_reason([tree for _, tree in notebook_trees], constant_names)
    return [
        str(cell.get("id", "?"))
        for cell, tree in notebook_trees
        if REASON_STRING in _output_text(cell) and not _cell_types_the_reason(tree, carrying)
    ]


def _live_gate_locations(
    helpers_tree: ast.Module, notebook: list[tuple[dict, ast.Module]]
) -> list[str]:
    """Where this recipe's executable code gates on confidence: ``helpers.py`` when it compares a
    confidence with a bound a recipe chooses (an argument range check is not one,
    ``_confidence_bound_comparisons``) or produces the confidence-gated review's reason, and each
    notebook code cell that compares one. THE applicability predicate of both
    ``review_reason_string`` and ``confidence_gate_from_shared_helper``: a recipe with no location
    here has no gate, and a named gate-free design is not applicable to either; a recipe with one
    has a gate, and must show it is real (the reason, its branch, its output) and frozen through
    the shared helper. It is a property of what the code does, not a spelling of how the gate was
    frozen: it is exactly what the checks that skip on "no resolvable call" cannot see."""
    where = []
    if _live_reason_uses(helpers_tree) or _confidence_bound_comparisons(helpers_tree):
        where.append("helpers.py")
    where += [
        f"cell {cell.get('id', '?')}"
        for cell, tree in notebook
        if _confidence_bound_comparisons(tree)
    ]
    return where


def _gate_free_verdict(slug: str, gated_in: list[str], check: str) -> tuple[str, str] | None:
    """The verdict for a recipe named in ``GATE_FREE_DESIGNS``, or ``None`` for any other: not
    applicable (a skip carrying the entry's reason), unless the recipe now has a live gate, when the
    entry has outlived the absence it records and the recipe is held to the check."""
    if slug not in GATE_FREE_DESIGNS:
        return None
    if gated_in:
        return "fail", (
            f"{slug}: listed in GATE_FREE_DESIGNS but its code now gates on confidence "
            f"({', '.join(gated_in)}); remove the entry so the gate is held to {check}"
        )
    return "skip", f"{slug}: named gate-free design -- {GATE_FREE_DESIGNS[slug]}"


def _reason_string_verdict(recipe_dir_: Path, slug: str) -> tuple[str, str]:
    """``("ok" | "skip" | "fail", message)`` for one recipe directory: the whole
    ``review_reason_string`` verdict, factored out so the mutation and table tests below run the
    SAME code path CI runs on a throwaway recipe. ``skip`` is a named exception reported with its
    reason (``GATE_FREE_DESIGNS``, or ``REASON_NOT_IN_COMMITTED_OUTPUT`` after the static half
    held in full)."""
    try:
        helpers_tree = ast.parse((recipe_dir_ / "helpers.py").read_text("utf-8"))
    except (OSError, SyntaxError) as error:
        return "fail", f"{slug}: helpers.py cannot be read as Python ({error})"
    notebook, unparseable = _notebook_code_trees(recipe_dir_)
    if unparseable:
        return "fail", (
            f"{slug}: notebook code cell(s) {unparseable} do not parse as plain Python, so "
            "the committed output cannot be tied to the rule"
        )
    uses = _live_reason_uses(helpers_tree)
    near_misses = _near_miss_reasons(helpers_tree)
    if near_misses:
        return "fail", (
            f"{slug}: a review reason is worded {near_misses[0]!r}; docs/glossary.md#review "
            f"fixes the reason of a confidence-gated review to exactly {REASON_STRING!r}"
        )
    gated_in = _live_gate_locations(helpers_tree, notebook)
    named = _gate_free_verdict(slug, gated_in, "this check")
    if named is not None:
        return named
    if not gated_in:
        return "fail", (
            f"{slug}: no executable branch of helpers.py produces {REASON_STRING!r} -- the words "
            "are absent, or only in a comment, a docstring or a constant nothing uses. If this "
            "rule has a confidence-gated review, add the branch (docs/glossary.md#review). If it "
            "genuinely has none, that is a design decision a foundation pull request records in "
            "GATE_FREE_DESIGNS with the reason; do not park the words in a comment and do not "
            "add a gate nothing exercises"
        )
    if not uses:
        return "fail", (
            f"{slug}: this recipe gates on confidence ({', '.join(gated_in)}) but no executable "
            f"branch of helpers.py produces {REASON_STRING!r}: the words are absent, or only in a "
            "comment, a docstring or a constant nothing uses. Give the review the gate sends "
            "answers to that reason (docs/glossary.md#review)"
        )
    derived = _confidence_derived_names(helpers_tree)
    parents = _parents(helpers_tree)
    controlled = [use for use in uses if _controlled_by_confidence(use, parents, derived)]
    if not controlled:
        return "fail", (
            f"{slug}: helpers.py uses {REASON_STRING!r} in code, but no use is on a branch a "
            "confidence comparison controls (an `if`/conditional on a comparison with a "
            "confidence, a guard clause after one, or a flag derived from one). Put the reason "
            "on the branch the comparison decides; a shape this check cannot read is reported "
            "for adjudication, not satisfied by moving the words"
        )
    reachable = _reachable_helper_functions(helpers_tree, [tree for _, tree in notebook])
    functions = []
    for use in controlled:
        scope = use
        while not isinstance(scope, _FUNCTION_NODES):
            scope = parents[scope]
        functions.append(scope.name)
    if not set(functions) & reachable:
        return "fail", (
            f"{slug}: the confidence-gated review in helpers.py ({', '.join(sorted(set(functions)))}) "
            "is not reachable from the notebook: nothing in its code cells names those "
            "functions, directly or through another function of helpers.py. A gate the notebook "
            "never runs is the dead branch the reason string was meant to prove is absent"
        )
    shown = _cells_showing_the_reason(notebook, _reason_constant_names(helpers_tree))
    if slug in REASON_NOT_IN_COMMITTED_OUTPUT:
        if shown:
            return "fail", (
                f"{slug}: listed in REASON_NOT_IN_COMMITTED_OUTPUT but cell(s) {shown} now show a "
                "review produced by the rule; remove the entry so the output is held to this check"
            )
        return "skip", f"{slug}: {REASON_NOT_IN_COMMITTED_OUTPUT[slug]}"
    if not shown:
        return "fail", (
            f"{slug}: no committed notebook output shows a review whose reason the rule produced "
            f"({REASON_STRING!r} in an output of a cell that does not itself write those words). "
            "Print the outcome the rule returns for an example it sends to review (its `.reason`) "
            "and re-execute the notebook, or, if the gate is never exercised on the committed "
            "fixtures, that is the finding to bring to review, not something to type into a print"
        )
    return "ok", ""


@pytest.mark.parametrize("recipe", guarded("review_reason_string"))
def test_the_confidence_gate_reason_string_is_exact(recipe):
    """docs/glossary.md#review: "the reason string for a confidence-gated review is exactly
    'confidence below the threshold', so two recipes' readers see the same words for the same
    cause." The rule is conditional -- it words a confidence-gated review, it does not require a
    recipe to have one -- and the check used to be an unconditional substring search of
    ``helpers.py``'s text, satisfied by a comment (#227). It now requires, where the words are
    produced by executable code at all, that:

    * the words are the reason of a branch a confidence comparison controls
      (``_controlled_by_confidence``); not a comment, a docstring, an unused constant, or a use
      with no such comparison deciding it;
    * that branch's function is reachable from the notebook (``_reachable_helper_functions``);
    * a committed notebook output shows a review whose reason the rule produced: the words in the
      output of a cell whose own code does not write them (``_cells_showing_the_reason``), so a
      literal-only ``print`` is not evidence, in the cell or carried into it from another cell
      by a name (``_names_carrying_the_reason``). The eight published recipes whose output shows
      no such review are named in ``REASON_NOT_IN_COMMITTED_OUTPUT`` as recorded drift (#342),
      strictly, and are SKIPPED with that reason once the rest of the check has held (see its
      comment);
    * no executable string words a confidence review differently (a near miss is a failure).

    A recipe whose rule has no confidence-gated review at all is not applicable
    (``GATE_FREE_DESIGNS``, named and checked, a skip carrying the reason), and a recipe with no
    gate (``_live_gate_locations``, the predicate ``confidence_gate_from_shared_helper`` shares)
    and no named design fails with a message that names the absence. What the check cannot see is
    disclosed, not assumed away: the output evidence is the words in an output of a cell that does
    not write them, not a traced ``.reason`` expression, so words carried into a cell through a
    container, a function's return value or a file are still accepted; control is judged by name
    and shape; polarity is not judged; and
    a branch that exists, is reachable and is shown in an output may still not be the gate that
    the rule's frozen threshold feeds -- ``confidence_gate_from_shared_helper`` and the recipe's
    own tests own that."""
    status, message = _reason_string_verdict(recipe_dir(recipe), recipe["slug"])
    if status == "skip":
        pytest.skip(message)
    assert status == "ok", message


# --- #227: the reason string must be produced by a live review branch ----------------------------

_GATE_HELPERS = '''
from jev_cookbook.evaluation import select_confidence_threshold

REVIEW = "review"


def route(answer, min_confidence):
    """Send an answer to review below the gate."""
    if answer.confidence < min_confidence:
        return REVIEW, "confidence below the threshold"
    return answer.choice, "confident match"
'''

_GATE_CELLS = [
    (
        "from jev_cookbook.evaluation import select_confidence_threshold\n"
        "helpers = load_helpers()\n"
        "gate = select_confidence_threshold(ok, conf, target_accuracy=1.0)\n"
        "print(helpers.route(answer, gate))\n",
        "('review', 'confidence below the threshold')\n",
    ),
]


def _gate_recipe(tmp_path: Path, helpers: str = _GATE_HELPERS, cells=_GATE_CELLS) -> Path:
    """A minimal recipe folder: a ``helpers.py`` and a notebook of ``(source, stdout)`` code cells."""
    folder = tmp_path / "synthetic-gate"
    folder.mkdir(parents=True)
    (folder / "helpers.py").write_text(textwrap.dedent(helpers), "utf-8")
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "id": f"c{i}",
                "metadata": {},
                "execution_count": i,
                "source": source.splitlines(keepends=True),
                "outputs": (
                    [{"output_type": "stream", "name": "stdout", "text": output.splitlines(True)}]
                    if output
                    else []
                ),
            }
            for i, (source, output) in enumerate(cells)
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (folder / "notebook.ipynb").write_text(json.dumps(notebook), "utf-8")
    return folder


def _guard_clause_helpers() -> str:
    return """
        def route(answer, min_confidence):
            if answer.confidence >= min_confidence:
                return answer.choice, "confident match"
            return "review", "confidence below the threshold"
    """


_REASON_PASSES = {
    "the-branch-itself": (_GATE_HELPERS, _GATE_CELLS),
    "guard-clause-then-fall-through": (_guard_clause_helpers(), _GATE_CELLS),
    "conditional-expression": (
        """
        def route(answer, min_confidence):
            reason = "confidence below the threshold" if answer.confidence < min_confidence else "ok"
            return reason
        """,
        _GATE_CELLS,
    ),
    "reason-held-in-a-module-constant": (
        """
        REASON_REVIEW = "confidence below the threshold"

        def route(answer, min_confidence):
            if answer.confidence < min_confidence:
                return "review", REASON_REVIEW
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
    ),
    "flag-derived-from-the-comparison-and-read-elsewhere": (
        """
        from collections import namedtuple

        Decision = namedtuple("Decision", "label gated")

        def decide(answer, gate):
            gated = answer.confidence < gate
            return Decision(answer.choice, gated)

        def route(answer, gate):
            decision = decide(answer, gate)
            if decision.gated:
                return "review", "confidence below the threshold"
            return decision.label, "ok"
        """,
        [("print(helpers.route(answer, 0.5))\n", "('review', 'confidence below the threshold')\n")],
    ),
    # shapes every helpers.py has that must not be read as a binding of the reason (they used to
    # raise AttributeError: a module-level expression statement has a string value but no target)
    "module-docstring-holding-the-words": (
        '''
        """Rules for the gate. A review's reason is "confidence below the threshold"."""

        def route(answer, min_confidence):
            if answer.confidence < min_confidence:
                return "review", "confidence below the threshold"
            return answer.choice, "ok"
        ''',
        _GATE_CELLS,
    ),
    "bare-string-statement-holding-the-words": (
        """
        def route(answer, min_confidence):
            if answer.confidence < min_confidence:
                return "review", "confidence below the threshold"
            return answer.choice, "ok"

        "the reason is confidence below the threshold"
        """,
        _GATE_CELLS,
    ),
    "reason-constant-added-to-in-place": (
        """
        REASON = ""
        REASON += "confidence below the threshold"

        def route(answer, min_confidence):
            if answer.confidence < min_confidence:
                return "review", REASON
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
    ),
    "reason-constants-bound-by-tuple-assignment": (
        """
        REASON_GATE, REASON_OTHER = "confidence below the threshold", "something else"

        def route(answer, min_confidence):
            if answer.confidence < min_confidence:
                return "review", REASON_GATE
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
    ),
    "an-unrelated-name-bound-in-an-earlier-cell": (
        _GATE_HELPERS,
        [
            ("label = 'run 1'\n", ""),
            (
                "print(label, helpers.route(answer, 0.5))\n",
                "run 1 ('review', 'confidence below the threshold')\n",
            ),
        ],
    ),
    "reached-through-another-function": (
        """
        def route(answer, gate):
            if answer.confidence < gate:
                return "review", "confidence below the threshold"
            return answer.choice, "ok"

        def route_all(answers, gate):
            return [route(a, gate) for a in answers]
        """,
        [
            (
                "print(helpers.route_all(answers, 0.5))\n",
                "[('review', 'confidence below the threshold')]\n",
            )
        ],
    ),
}


@pytest.mark.parametrize("shape", sorted(_REASON_PASSES))
def test_a_live_confidence_gated_review_shown_in_an_output_passes(tmp_path, shape):
    helpers, cells = _REASON_PASSES[shape]
    folder = _gate_recipe(tmp_path, helpers, cells)
    status, message = _reason_string_verdict(folder, "synthetic")
    assert (status, message) == ("ok", "")


_UNTYPED_PRINT = [
    ("print('confidence below the threshold')\n", "confidence below the threshold\n"),
]

_REASON_FAILS = {
    # the words without a branch: what the substring search accepted
    "words-only-in-a-comment": (
        """
        def route(answer, gate):
            # the review reason would be "confidence below the threshold"
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
        "no executable branch of helpers.py produces",
    ),
    "words-only-in-a-docstring": (
        '''
        def route(answer, gate):
            """Review reason: "confidence below the threshold"."""
            return answer.choice, "ok"
        ''',
        _GATE_CELLS,
        "no executable branch of helpers.py produces",
    ),
    "unused-module-constant": (
        """
        REASON_REVIEW = "confidence below the threshold"

        def route(answer, gate):
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
        "no executable branch of helpers.py produces",
    ),
    "words-nowhere": (
        """
        def route(answer, gate):
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
        "GATE_FREE_DESIGNS",
    ),
    # a branch that exists but no confidence comparison decides it
    "returned-unconditionally": (
        """
        def route(answer, gate):
            return "review", "confidence below the threshold"
        """,
        _GATE_CELLS,
        "no use is on a branch a confidence comparison controls",
    ),
    "under-a-condition-that-is-not-about-confidence": (
        """
        def route(answer, gate):
            if answer.choice == "none":
                return "review", "confidence below the threshold"
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
        "no use is on a branch a confidence comparison controls",
    ),
    "set-in-a-function-no-comparison-reaches": (
        """
        def _review():
            return "review", "confidence below the threshold"

        def route(answer, gate):
            if answer.confidence < gate:
                return _review()
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
        "no use is on a branch a confidence comparison controls",
    ),
    # a branch the notebook never runs (recipe 35's first build)
    "gate-in-a-function-the-notebook-never-names": (
        """
        def route(answer, gate):
            return answer.choice, "ok"

        def confidence_outcome(answer, gate):
            if answer.confidence < gate:
                return "review", "confidence below the threshold"
            return "ok", "ok"
        """,
        [("print(helpers.route(answer, 0.5))\n", "('review', 'confidence below the threshold')\n")],
        "is not reachable from the notebook",
    ),
    # a reason that never reached a reader, or that the cell typed itself
    "no-output-at-all": (
        _GATE_HELPERS,
        [("print(helpers.route(answer, 0.5))\n", "")],
        "no committed notebook output shows a review",
    ),
    "a-literal-only-print": (
        _GATE_HELPERS,
        [("helpers.route(answer, 0.5)\n", ""), *_UNTYPED_PRINT],
        "no committed notebook output shows a review",
    ),
    "the-cell-prints-the-constant-itself": (
        """
        REASON_REVIEW = "confidence below the threshold"

        def route(answer, gate):
            if answer.confidence < gate:
                return "review", REASON_REVIEW
            return answer.choice, "ok"
        """,
        [
            (
                "helpers.route(answer, 0.5)\nprint(helpers.REASON_REVIEW)\n",
                "confidence below the threshold\n",
            ),
        ],
        "no committed notebook output shows a review",
    ),
    "a-print-that-types-the-words-beside-the-call": (
        _GATE_HELPERS,
        [
            (
                "print(helpers.route(answer, 0.5), 'confidence below the threshold')\n",
                "x confidence below the threshold\n",
            )
        ],
        "no committed notebook output shows a review",
    ),
    # wording
    # the words carried into the cell that prints them from another cell
    "words-bound-in-one-cell-printed-in-the-next": (
        _GATE_HELPERS,
        [
            ("msg = 'confidence below the threshold'\n", ""),
            ("helpers.route(answer, 0.5)\nprint(msg)\n", "confidence below the threshold\n"),
        ],
        "no committed notebook output shows a review",
    ),
    "constant-copied-to-a-name-in-one-cell-printed-in-the-next": (
        """
        REASON_REVIEW = "confidence below the threshold"

        def route(answer, gate):
            if answer.confidence < gate:
                return "review", REASON_REVIEW
            return answer.choice, "ok"
        """,
        [
            ("msg = helpers.REASON_REVIEW\nalias = msg\n", ""),
            ("helpers.route(answer, 0.5)\nprint(alias)\n", "confidence below the threshold\n"),
        ],
        "no committed notebook output shows a review",
    ),
    # a gate whose reason is produced but whose comparison is not an argument range check
    "gate-with-no-reason-produced": (
        """
        def route(answer, gate):
            if answer.confidence < gate:
                return "review", "low confidence"
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
        "gates on confidence (helpers.py) but no executable branch of helpers.py produces",
    ),
    "near-miss-wording": (
        """
        def route(answer, gate):
            if answer.confidence < gate:
                return "review", "confidence below the review cutoff"
            return answer.choice, "ok"
        """,
        _GATE_CELLS,
        "fixes the reason of a confidence-gated review to exactly",
    ),
    "unparseable-notebook-cell": (
        _GATE_HELPERS,
        [("%matplotlib inline\nhelpers.route(answer, 0.5)\n", "confidence below the threshold\n")],
        "do not parse as plain Python",
    ),
}


@pytest.mark.parametrize("shape", sorted(_REASON_FAILS))
def test_a_reason_string_without_a_live_reachable_shown_branch_fails(tmp_path, shape):
    """Every row names the shape it stands for. The first three are the shapes the substring
    search of ``helpers.py`` accepted (a comment, a docstring, an unused constant); the rest are
    the ways a branch can exist and still prove nothing. Each failure says what to do."""
    helpers, cells, expected = _REASON_FAILS[shape]
    folder = _gate_recipe(tmp_path, helpers, cells)
    status, message = _reason_string_verdict(folder, "synthetic")
    assert status == "fail" and expected in message, (status, message)
    if shape.startswith("words-only") or shape == "unused-module-constant":
        # the check this replaces was green on exactly these
        assert REASON_STRING in (folder / "helpers.py").read_text("utf-8")


def test_a_named_gate_free_design_is_not_applicable_and_a_stale_exemption_fails(tmp_path):
    comment_only = textwrap.dedent(
        """
        def route(answer, gate):
            # a review would say "confidence below the threshold" -- this rule has none
            return answer.choice, "ok"
        """
    )
    folder = _gate_recipe(tmp_path, comment_only, [("print(helpers.route(answer, 0.5))\n", "ok\n")])
    status, message = _reason_string_verdict(folder, "28-skill-selection")
    assert status == "skip" and "named gate-free design" in message
    # the same recipe under a slug nobody named is a failure that names the absence
    status, message = _reason_string_verdict(folder, "some-new-recipe")
    assert (
        status == "fail" and "GATE_FREE_DESIGNS" in message and "do not park the words" in message
    )
    # an exemption does not outlive the absence it records
    live = _gate_recipe(tmp_path / "live")
    status, message = _reason_string_verdict(live, "28-skill-selection")
    assert status == "fail" and "remove the entry" in message


def test_a_recipe_listed_as_not_showing_the_reason_is_held_to_it_both_ways(tmp_path):
    hidden = _gate_recipe(
        tmp_path / "hidden", _GATE_HELPERS, [("print(helpers.route(answer, 0.5))\n", "")]
    )
    status, message = _reason_string_verdict(hidden, "49-multi-agent-task-assignment")
    # recorded drift: the static half held in full, and the skip carries the recorded reason
    assert status == "skip" and "see #342" in message
    status, message = _reason_string_verdict(hidden, "some-new-recipe")
    assert status == "fail" and "no committed notebook output shows a review" in message
    shown = _gate_recipe(tmp_path / "shown")
    status, message = _reason_string_verdict(shown, "49-multi-agent-task-assignment")
    assert status == "fail" and "remove the entry" in message
    # the static half is not waived by being listed
    dead = _gate_recipe(tmp_path / "dead", "def route(a, g):\n    return a, g\n", [("1\n", "")])
    status, message = _reason_string_verdict(dead, "49-multi-agent-task-assignment")
    assert status == "fail" and "no executable branch" in message


def test_every_exemption_names_a_published_recipe_and_gate_free_ones_have_no_live_gate():
    published = PUBLISHED_SLUGS
    assert set(GATE_FREE_DESIGNS) <= published
    assert set(REASON_NOT_IN_COMMITTED_OUTPUT) <= published
    assert not set(GATE_FREE_DESIGNS) & set(REASON_NOT_IN_COMMITTED_OUTPUT)
    for slug in GATE_FREE_DESIGNS:
        folder = RECIPES_DIR / slug
        notebook, _ = _notebook_code_trees(folder)
        helpers_tree = ast.parse((folder / "helpers.py").read_text("utf-8"))
        assert _live_gate_locations(helpers_tree, notebook) == [], slug
    for reason in REASON_NOT_IN_COMMITTED_OUTPUT.values():
        assert reason.endswith("see #342")


def test_a_module_docstring_holding_the_words_is_neither_a_binding_nor_a_crash(tmp_path):
    """Every helpers.py has a module docstring, and a docstring is an expression statement whose
    value is a string. ``_reason_constant_names`` read any such statement as an assignment and
    raised ``AttributeError`` the moment the docstring held the reason's words, taking BOTH new
    checks down with a traceback about a line the recipe's author wrote innocently. Recipe 28
    already has the words in a comment; promote them to its module docstring and both checks
    still return their verdicts (and the words are not a use, so nothing is satisfied by them)."""
    folder = _copy_recipe(tmp_path, "28-skill-selection")
    path = folder / "helpers.py"
    text = path.read_text("utf-8")
    assert text.startswith('"""')
    path.write_text(
        '"""A review\'s reason is "confidence below the threshold" (docs/glossary.md#review).\n\n'
        + text[3:],
        "utf-8",
    )
    ast.parse(path.read_text("utf-8"))
    assert _reason_string_verdict(folder, "28-skill-selection")[0] == "skip"
    assert _gate_freeze_verdict(folder, "28-skill-selection")[0] == "skip"
    # not named, it is the absence it always was -- a verdict, not a traceback
    status, message = _reason_string_verdict(folder, "not-named")
    assert status == "fail" and "no executable branch of helpers.py produces" in message
    assert _gate_freeze_verdict(folder, "not-named")[0] == "not-applicable"


def test_the_template_and_a_simple_published_recipe_pass_with_their_own_outputs(tmp_path):
    for slug in ("_template", "01-sentiment-classification", "31-patch-risk-triage"):
        assert _reason_string_verdict(_copy_recipe(tmp_path, slug), slug) == ("ok", "")


def test_a_branch_replaced_by_a_comment_in_a_published_recipe_is_caught(tmp_path):
    """The mutation proof on a published recipe (01): replace the live gated return with a
    comment that carries the words. The substring check this replaces stays green, the new one
    goes red, naming the absence."""
    folder = _copy_recipe(tmp_path, "01-sentiment-classification")
    _edit_text(
        folder / "helpers.py",
        '        return Classification(review_id, answer.choice, REVIEW, "confidence below the threshold")\n',
        '        # the reason would be "confidence below the threshold"\n        pass\n',
    )
    assert REASON_STRING in (folder / "helpers.py").read_text("utf-8")  # the old check: green
    status, message = _reason_string_verdict(folder, "01-sentiment-classification")
    assert status == "fail" and "no executable branch of helpers.py produces" in message


def test_a_branch_the_notebook_stops_calling_is_caught(tmp_path):
    """Remove the call: 01's notebook stops routing through ``classify`` (its output is stale but
    still holds the words, as it would between an edit and a re-execution). The static half
    notices before the freshness job has to."""
    folder = _copy_recipe(tmp_path, "01-sentiment-classification")
    notebook = json.loads((folder / "notebook.ipynb").read_text("utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            cell["source"] = [line.replace("classify", "unrelated") for line in cell["source"]]
    (folder / "notebook.ipynb").write_text(json.dumps(notebook), "utf-8")
    status, message = _reason_string_verdict(folder, "01-sentiment-classification")
    assert status == "fail" and "is not reachable from the notebook" in message


def test_a_removed_branch_in_a_published_recipe_is_caught(tmp_path):
    folder = _copy_recipe(tmp_path, "01-sentiment-classification")
    _edit_text(
        folder / "helpers.py",
        "    if answer.confidence < min_confidence:\n"
        '        return Classification(review_id, answer.choice, REVIEW, "confidence below the threshold")\n',
        "",
    )
    status, message = _reason_string_verdict(folder, "01-sentiment-classification")
    assert status == "fail" and "no executable branch of helpers.py produces" in message


# --------------------------------------------------------------------------------------------
# check 8a: README "## Sources" equals the catalog row
# --------------------------------------------------------------------------------------------

SOURCE_ID = re.compile(r"^- (S\d+):", re.MULTILINE)


def _readme_source_ids(readme_text: str) -> list[str]:
    """Same rule as tests/test_recipe_sources.py::_readme_source_ids, restated locally rather
    than imported from that test module. The rule is four lines, with this note tying the two
    copies together."""
    marker = "\n## Sources\n"
    if marker not in readme_text:
        return []
    return SOURCE_ID.findall(readme_text.split(marker, 1)[1])


@pytest.mark.parametrize(
    "recipe",
    guarded(
        "readme_sources_match_catalog",
        skip_template="The comparison needs a catalog row with source IDs.",
    ),
)
def test_readme_sources_match_the_catalog(recipe):
    """tests/test_recipe_sources.py's own rule, folded into this module as one of these checks
    too (CONTRIBUTING.md: a recipe's README is one page of the contract same as any
    other file). Not run against the template, which has no catalog row to compare against."""
    readme = (recipe_dir(recipe) / "README.md").read_text("utf-8")
    documented = _readme_source_ids(readme)
    cataloged = recipe.get("sources", [])
    assert documented, f"{recipe['slug']}/README.md has no '## Sources' bullet list"
    assert set(documented) == set(cataloged)


# --------------------------------------------------------------------------------------------
# check 8b: the live budget note matches the request audit (#213) or the strict legacy proxy
# --------------------------------------------------------------------------------------------


def _load_request_audit() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "request_audit_for_recipe_guard", Path(__file__).resolve().parent / "request_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_request_audit = _load_request_audit()
LIVE_CALL_COUNT = _request_audit.LIVE_CALL_COUNT
AUDIT_PREFIX = _request_audit.AUDIT_PREFIX


@pytest.mark.parametrize("recipe", guarded("readme_budget_note_matches_request_audit"))
def test_the_live_budget_note_matches_the_request_audit(recipe):
    """A recipe states its live request count once, in ``request_budget.json``.

    The audited route (a recipe that declares a count, wraps its backends in
    ``AuditedBackend`` and prints the one final audit line) is checked three ways at once:
    the committed audit line equals the declaration (calls, distinct requests, exact fixture
    inventory), no request is decided twice unless the declaration says so (a repeat fails and
    names the replay key), and the README holds the paragraph rendered from the declaration
    and the section states no other request count or cap. The declaration, the audited notebook
    and the rendered paragraph come together or not at all (a paragraph alone fails too). Freshness of the committed line is the separate offline notebook
    job's duty.

    A recipe with none of the three keeps the old strict ``len(responses.json)`` proxy, which
    measures distinct fixture keys and so cannot see a repeated request or a second backend (see
    #213); unaudited scripted recipes still have no artifact to read and keep the existing skip.
    A malformed audit never falls back to the proxy.
    """
    directory = recipe_dir(recipe)
    if _request_audit.audit_recipe(directory, notebook_cells(directory)) is not None:
        return
    path = directory / "fixtures" / "responses.json"
    if not path.is_file():
        pytest.skip(
            "scripted recipe: no responses.json or committed backend request audit; "
            "actual decide() count requires execution evidence (see #249)"
        )
    actual = len(json.loads(path.read_text("utf-8")))
    readme = (directory / "README.md").read_text("utf-8")
    assert "## Switch to live" in readme
    section = readme.split("## Switch to live", 1)[1].split("## What was", 1)[0]
    match = LIVE_CALL_COUNT.search(section)
    assert match, f"{recipe['slug']}: no recognisable live-call-count sentence in README.md"
    stated = int(next(g for g in match.groups() if g))
    assert stated == actual, (
        f"{recipe['slug']}: README states {stated}, legacy fixture count is {actual}"
    )


def _drift_template_budget(folder: Path) -> int:
    path = folder / "request_budget.json"
    budget = json.loads(path.read_text("utf-8"))
    backend = next(iter(budget["backends"].values()))
    requests = backend["requests"]
    backend["requests"] = requests + 1
    if "at_most" in backend:
        backend["at_most"] = max(backend["at_most"], backend["requests"])
    path.write_text(json.dumps(budget), "utf-8")
    return requests


def _drift_template_readme(folder: Path) -> int:
    path = folder / "README.md"
    match = re.search(r"exactly \*\*(\d+)\*\* requests?\b", path.read_text("utf-8"))
    assert match, "the template README no longer holds the rendered request count"
    count = int(match.group(1))
    _edit_text(path, match.group(0), f"exactly **{count + 1}** requests")
    return count


def _drift_template_audit_line(folder: Path) -> int:
    path = folder / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    for cell in notebook["cells"]:
        for output in cell.get("outputs", []):
            text = output.get("text", [])
            # nbformat allows a stream's text as one string or as a list of lines.
            lines = text.splitlines(keepends=True) if isinstance(text, str) else list(text)
            for i, line in enumerate(lines):
                if line.startswith(AUDIT_PREFIX):
                    payload = json.loads(line[len(AUDIT_PREFIX) :])
                    # Keep the ledger self-consistent. The declaration's call-count comparison
                    # reports the extra call before any replay fixture inventory comparison.
                    entry = payload["backends"][0]
                    requests = entry["decide_calls"]
                    keys = {call["replay_key"] for call in entry["calls"]}
                    key = next(
                        f"{candidate:064x}"
                        for candidate in range(len(keys) + 1)
                        if f"{candidate:064x}" not in keys
                    )
                    entry["calls"].append({"replay_key": key, "returned": True})
                    entry["decide_calls"] += 1
                    entry["distinct_requests"] += 1
                    lines[i] = AUDIT_PREFIX + json.dumps(payload, separators=(",", ":")) + "\n"
                    output["text"] = lines
                    path.write_text(json.dumps(notebook), "utf-8")
                    return requests
    raise AssertionError("the template notebook no longer commits an audit line")


_TEMPLATE_DRIFTS = {
    "budget": (
        _drift_template_budget,
        r"made {original} decide\(\) calls, request_budget\.json declares {drifted}",
    ),
    "readme": (_drift_template_readme, r"README budget paragraph differs"),
    "audit-line": (
        _drift_template_audit_line,
        r"made {drifted} decide\(\) calls, request_budget\.json declares {original}",
    ),
}


def test_the_template_passes_the_request_audit_on_the_audited_route():
    """The template's audit returns the declared total, which distinguishes it from legacy replay."""
    assert (
        _request_audit.audit_recipe(TEMPLATE, notebook_cells(TEMPLATE))
        == _request_audit.load_budget(TEMPLATE).total
    )


@pytest.mark.parametrize("drift", sorted(_TEMPLATE_DRIFTS))
def test_each_template_drift_fails_the_request_audit_check_on_its_own_comparison(
    tmp_path, monkeypatch, drift
):
    """Check which comparison catches each change to the budget, README and committed ledger."""
    folder = _copy_recipe(tmp_path, "_template")
    mutate, message = _TEMPLATE_DRIFTS[drift]
    count = mutate(folder)
    monkeypatch.setitem(globals(), "RECIPES_DIR", tmp_path)
    with pytest.raises(AssertionError, match=message.format(original=count, drifted=count + 1)):
        test_the_live_budget_note_matches_the_request_audit({"slug": "_template"})


def _check_recipe_scope_registration(tree: ast.Module) -> None:
    """Fail on a recipe sweep that reads ``PUBLISHED`` outside the registered definitions.

    Decision for #639: ``PUBLISHED_SLUGS`` and ``PUBLISHED_NUMBERS`` are catalog-membership sets
    ("is this a published recipe"), and ``recipes/_template`` is deliberately not a member: it
    has no catalog row, so a link to it must stay "not published", and the side-effect
    inventory's stale-entry comparison would report it as stale. A loop over ``PUBLISHED_SLUGS``
    therefore skips the template, which is correct for catalog metadata. A per-recipe check
    never loops over the set: it is parametrised through ``guarded()`` or
    ``RECIPES_WITH_TEMPLATE``, which this function enforces, and the full-set test below pins
    that ``RECIPES_WITH_TEMPLATE`` is ``PUBLISHED_SLUGS`` plus the template. A plain
    ``for slug in PUBLISHED_SLUGS`` inside a test body is not detected; a check that must see
    the template iterates ``RECIPES_WITH_TEMPLATE``.
    """
    # Catalog metadata and explicitly registered exclusions can use the published set. Other
    # recipe cases start with the full set, including the template.
    catalog_helpers = {
        "guarded",
        "_inbound_next_steps_links",
        "side_effect_inventory_gaps",
    }
    # The module-level frozensets that replaced the _published_recipe_numbers/_slugs helpers
    # (#472): the same catalog metadata, registered under their new names.
    catalog_constants = {"PUBLISHED_NUMBERS", "PUBLISHED_SLUGS"}
    pytest_names = {"pytest", "pytest.mark", "pytest.mark.parametrize"}
    aliases = {}

    def qualified_name(node: ast.expr) -> str:
        name, separator, rest = ast.unparse(node).partition(".")
        return aliases.get(name, name) + separator + rest

    for statement in tree.body:
        if isinstance(statement, ast.Import):
            aliases.update(
                (name.asname or name.name, "pytest")
                for name in statement.names
                if name.name == "pytest"
            )
        if isinstance(statement, ast.ImportFrom) and statement.module == "pytest":
            aliases.update(
                (name.asname or name.name, "pytest.mark")
                for name in statement.names
                if name.name == "mark"
            )
        if isinstance(statement, ast.Assign) and isinstance(
            statement.value, (ast.Name, ast.Attribute)
        ):
            origin = qualified_name(statement.value)
            if origin in pytest_names:
                aliases.update(
                    (target.id, origin)
                    for target in statement.targets
                    if isinstance(target, ast.Name)
                )

        catalog_helper = (
            isinstance(statement, ast.FunctionDef) and statement.name in catalog_helpers
        ) or (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id in catalog_constants
        )
        full_set_definition = (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "RECIPES_WITH_TEMPLATE"
        )
        if not full_set_definition and not catalog_helper:
            assert not any(
                isinstance(node, ast.Name)
                and node.id == "PUBLISHED"
                and isinstance(node.ctx, ast.Load)
                for node in ast.walk(statement)
            ), f"line {statement.lineno}: use RECIPES_WITH_TEMPLATE for recipe sweeps"

    for marker in ast.walk(tree):
        if (
            not isinstance(marker, ast.Call)
            or qualified_name(marker.func) != "pytest.mark.parametrize"
        ):
            continue
        args = dict(zip(("argnames", "argvalues"), marker.args, strict=False))
        args.update((keyword.arg, keyword.value) for keyword in marker.keywords)
        assert isinstance(args.get("argnames"), (ast.Constant, ast.List, ast.Tuple)), (
            f"line {marker.lineno}: use literal parameter names to make recipe scope visible"
        )
        names = ast.literal_eval(args["argnames"])
        if isinstance(names, str):
            names = [name.strip() for name in names.split(",")]
        if "recipe" not in names:
            continue
        values = args["argvalues"]
        registered = isinstance(values, ast.Call) and ast.unparse(values.func) == "guarded"
        all_recipes = isinstance(values, ast.Name) and values.id == "RECIPES_WITH_TEMPLATE"
        assert registered or all_recipes, (
            f"line {marker.lineno}: use guarded() or RECIPES_WITH_TEMPLATE for recipe cases"
        )


def test_recipe_scope_registration_rejects_a_chained_assignment_of_a_catalog_constant():
    """#639 (from the #640 review): only a single-target assignment is exempt, so a second
    target cannot carry the published-only list under the catalog constant's name."""
    source = "PUBLISHED_SLUGS = CASES = [*PUBLISHED]\n"
    with pytest.raises(AssertionError, match="use RECIPES_WITH_TEMPLATE for recipe sweeps"):
        _check_recipe_scope_registration(ast.parse(source))
    for chained in (
        "CASES = PUBLISHED_NUMBERS = [*PUBLISHED]",
        "A = B = PUBLISHED_SLUGS = PUBLISHED",
    ):
        with pytest.raises(AssertionError, match="use RECIPES_WITH_TEMPLATE for recipe sweeps"):
            _check_recipe_scope_registration(ast.parse(chained + "\n"))
    # control: the same value under the single name is the registered definition
    _check_recipe_scope_registration(ast.parse("PUBLISHED_SLUGS = [*PUBLISHED]\n"))


@pytest.mark.parametrize(
    "source",
    [
        'CASES = [r for r in PUBLISHED if r["slug"] in PUBLISHED_SLUGS]\n',
        "CASES = [r for r in PUBLISHED if r['rank'] in PUBLISHED_NUMBERS]\n",
        "def test_each(): assert PUBLISHED_SLUGS and PUBLISHED\n",
        "for recipe in PUBLISHED: assert recipe['slug'] in PUBLISHED_SLUGS\n",
        "PUBLISHED_NUMBERS |= {r['rank'] for r in PUBLISHED}\n",
        "PUBLISHED_SLUGS: frozenset = frozenset(r['slug'] for r in PUBLISHED)\n",
        "PUBLISHED_SLUGS, OTHER = frozenset(r['slug'] for r in PUBLISHED), 1\n",
    ],
    ids=[
        "membership-slugs",
        "membership-numbers",
        "test-function",
        "loop",
        "augmented",
        "annotated",
        "tuple-target",
    ],
)
def test_recipe_scope_registration_does_not_exempt_a_statement_that_mentions_a_constant(source):
    """#639 (from the #640 review): a statement that merely mentions ``PUBLISHED_NUMBERS`` or
    ``PUBLISHED_SLUGS`` is not exempt; only the single-target module-level assignment is."""
    with pytest.raises(AssertionError, match="use RECIPES_WITH_TEMPLATE for recipe sweeps"):
        _check_recipe_scope_registration(ast.parse(source))


def test_recipe_checks_use_the_template_scope_registration():
    _check_recipe_scope_registration(ast.parse(Path(__file__).read_text("utf-8")))


def test_recipe_scope_registration_accepts_the_published_frozensets_only_by_name():
    source = """PUBLISHED_SLUGS = frozenset(r["slug"] for r in PUBLISHED)
PUBLISHED_NUMBERS = frozenset(int(r["slug"].split("-", 1)[0]) for r in PUBLISHED)
"""
    _check_recipe_scope_registration(ast.parse(source))
    with pytest.raises(AssertionError, match="use RECIPES_WITH_TEMPLATE for recipe sweeps"):
        _check_recipe_scope_registration(
            ast.parse(source.replace("PUBLISHED_SLUGS =", "OTHER_SLUGS ="))
        )


def test_recipe_scope_registration_rejects_a_published_only_module_alias():
    source = """\
RECIPE_CASES = [recipe for recipe in PUBLISHED]
def test_each_recipe():
    for recipe in RECIPE_CASES:
        assert recipe
"""
    with pytest.raises(AssertionError, match="use RECIPES_WITH_TEMPLATE for recipe sweeps"):
        _check_recipe_scope_registration(ast.parse(source))


@pytest.mark.parametrize(
    "source",
    [
        """\
from pytest import mark as pm
class TestRecipeCases:
    @pm.parametrize(argnames="recipe", argvalues=CASES)
    def test_each_recipe(self, recipe):
        assert recipe
""",
        """\
@pytest.mark.parametrize(argnames="recipe", argvalues=CASES)
class TestRecipeCases:
    def test_each_recipe(self, recipe):
        assert recipe
""",
        """\
from pytest import mark as pm
parametrize = pm.parametrize
@parametrize(argnames="recipe", argvalues=CASES)
def test_each_recipe(recipe):
    assert recipe
""",
        """\
from pytest import mark as pm
pytestmark = [pm.parametrize(argnames="recipe", argvalues=CASES)]
def test_each_recipe(recipe):
    assert recipe
""",
        """\
class TestRecipeCases:
    pytestmark = pytest.mark.parametrize(argnames="recipe", argvalues=CASES)
    def test_each_recipe(self, recipe):
        assert recipe
""",
    ],
    ids=["class-method", "test-class", "assignment-alias", "module-pytestmark", "class-pytestmark"],
)
def test_recipe_scope_registration_checks_ordinary_parametrization_forms(source):
    with pytest.raises(AssertionError, match=r"use guarded\(\) or RECIPES_WITH_TEMPLATE"):
        _check_recipe_scope_registration(ast.parse(source))
    registered = source.replace("argvalues=CASES", 'argvalues=guarded("example")')
    _check_recipe_scope_registration(ast.parse(registered))


def test_recipe_scope_registration_requires_the_template_in_the_full_set():
    expected = PUBLISHED_SLUGS | {"_template"}
    actual = [_slug(recipe) for recipe in RECIPES_WITH_TEMPLATE]
    assert set(actual) == expected and len(actual) == len(expected), (
        "RECIPES_WITH_TEMPLATE must contain the published recipes and the template exactly once"
    )


def _audited_mini_recipe(tmp_path: Path, n: int = 3) -> tuple[Path, str]:
    """A throwaway recipe genuinely on the audited route (#213): one real ``AuditedBackend``
    over ``n`` distinct synthetic requests, a ``request_budget.json`` that matches it, and a
    README whose rendered budget paragraph matches too -- everything ``audit_recipe``
    (``tests/request_audit.py``) checks, built from the real shared objects rather than typed
    out by hand. Returns the folder and the one genuine, committed audit line."""
    from jev_cookbook import AuditedBackend, Noul, ScriptedBackend
    from jev_cookbook.accounting import load_budget, render_budget_note

    def script(state, questions, rng):
        return {"q": 0.9}

    backend = AuditedBackend(ScriptedBackend(script, 0))
    for i in range(n):
        backend.decide({"i": i}, {"q": Noul()})
    line = backend.audit_json()

    folder = tmp_path / "mini-audited"
    folder.mkdir()
    setup = (
        "from jev_cookbook import AuditedBackend, Noul, get_backend\n\n\n"
        "def script(state, questions, rng):\n"
        "    return {'q': 0.9}\n\n\n"
        "backend = AuditedBackend(get_backend(script=script))\n"
        f"for i in range({n}):\n"
        "    backend.decide({'i': i}, {'q': Noul()})\n"
    )
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "id": "setup",
                "metadata": {},
                "execution_count": 1,
                "outputs": [],
                "source": setup.splitlines(True),
            },
            {
                "cell_type": "code",
                "id": "audit",
                "metadata": {},
                "execution_count": 2,
                "outputs": [{"name": "stdout", "output_type": "stream", "text": [line + "\n"]}],
                "source": ["print(backend.audit_json())\n"],
            },
        ]
    }
    (folder / "notebook.ipynb").write_text(json.dumps(notebook), "utf-8")
    (folder / "request_budget.json").write_text(
        json.dumps({"schema": 1, "backends": {"main": {"requests": n, "fixtures": None}}}),
        "utf-8",
    )
    note = render_budget_note(load_budget(folder))
    (folder / "README.md").write_text(
        f"# Mini audited recipe\n\n## Switch to live\n\n{note}", "utf-8"
    )
    return folder, line


def test_a_wrong_decide_count_in_the_audit_line_is_still_caught_after_the_exclusion(tmp_path):
    """#376: excluding the committed audit line from the honesty guard's quantity pool
    (``_printed_numbers``) must not also blind ``readme_budget_note_matches_request_audit``
    (#213) to a wrong ledger -- the two checks are independent, and this pins that they stay
    that way. Both directions, on the one real mini recipe, which is given a genuine printed
    metric and a markdown cell quoting it, so the pool-side assertion below has something it
    could plausibly lose: the pool side first (a committed, non-audit cell genuinely prints
    ``validation accuracy: 0.9500``, a markdown cell quotes "The accuracy is 95%.", and
    ``_unprinted_quantities`` is empty with the real audit line committed alongside it in a
    different cell -- the exclusion costs this recipe's own genuine figure nothing; an exclusion
    that blanked more than the matched line, e.g. the whole recipe's output once any cell
    carries the audit line, would lose this backing and fail here), then the ledger side (a real
    audited mini recipe's genuine line passes; a mutated line that lies about the call count --
    ``decide_calls`` left inconsistent with the still-genuine, still-64-hex ``calls`` list --
    still fails, exactly as before this fix, because the fix never touches
    ``tests/request_audit.py``)."""
    from jev_cookbook._canonical import canonical_json

    folder, line = _audited_mini_recipe(tmp_path, n=3)
    assert line.startswith(AUDIT_PREFIX)

    notebook = json.loads((folder / "notebook.ipynb").read_text("utf-8"))
    genuine_metric_cell = {
        "cell_type": "code",
        "id": "genuine-metric",
        "metadata": {},
        "execution_count": 2,
        "outputs": [
            {
                "name": "stdout",
                "output_type": "stream",
                "text": ["validation accuracy: 0.9500\n"],
            }
        ],
        "source": ["print('validation accuracy: 0.9500')\n"],
    }
    notebook["cells"][-1]["execution_count"] = 3  # the audit cell, now third rather than second
    notebook["cells"].insert(len(notebook["cells"]) - 1, genuine_metric_cell)
    (folder / "notebook.ipynb").write_text(json.dumps(notebook), "utf-8")
    _append_cell(folder, "markdown", "The accuracy is 95%.", cell_id="genuine-quote")

    assert _unprinted_quantities(folder) == []
    assert _request_audit.audit_recipe(folder, notebook_cells(folder)) == 3

    payload = json.loads(line[len(AUDIT_PREFIX) :])
    payload["backends"][0]["decide_calls"] = 4  # claims a 4th call that never happened
    wrong_line = AUDIT_PREFIX + canonical_json(payload)
    notebook = json.loads((folder / "notebook.ipynb").read_text("utf-8"))
    audit_cell = next(cell for cell in notebook["cells"] if cell.get("id") == "audit")
    audit_cell["outputs"][0]["text"] = [wrong_line + "\n"]
    (folder / "notebook.ipynb").write_text(json.dumps(notebook), "utf-8")

    with pytest.raises(AssertionError, match="stated call count differs"):
        _request_audit.audit_recipe(folder, notebook_cells(folder))


def _replace_audit_line(folder: Path, cell_id: str, edit) -> None:
    """Rewrite the committed audit line of ``folder``'s notebook through ``edit(payload)``, in
    canonical form, so only the edited values differ from a genuine line."""
    from jev_cookbook._canonical import canonical_json

    path = folder / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == cell_id)
    for output in cell["outputs"]:
        text = output.get("text", [])
        for i, line in enumerate(text):
            if line.startswith(AUDIT_PREFIX):
                payload = json.loads(line[len(AUDIT_PREFIX) :])
                edit(payload)
                text[i] = AUDIT_PREFIX + canonical_json(payload) + "\n"
                path.write_text(json.dumps(notebook), "utf-8")
                return
    raise AssertionError(f"cell {cell_id} commits no audit line")


def test_what_the_ledger_pins_about_its_replay_keys(tmp_path):
    """#379: what ``readme_budget_note_matches_request_audit`` pins about a ledger's
    ``replay_key`` values, in both configurations, as docs/backends.md states it.

    * With a fixture inventory declared (the template, ``fixtures/responses.json``), a key
      replaced by a well-formed but wrong value fails: the executed key set must equal the
      inventory.
    * With ``fixtures: null`` (a scripted lane, which has no stored answers to compare against),
      the guard checks a key's FORM and the counts the key list implies: a malformed key fails,
      and so does a duplicated key, whose ledger then holds fewer distinct requests than it
      states. A well-formed wrong key is the recorded limit and PASSES here. What catches it is
      the fresh-kernel notebook check (``tools/check_notebook_fresh.py``, CI's ``Notebook
      (<recipe>)`` job): the committed text output must equal a fresh run's, so the edited line
      differs from what the run prints, shown at the end on the same two notebooks."""
    template = tmp_path / "template"
    shutil.copytree(RECIPES_DIR / "_template", template)
    assert _request_audit.audit_recipe(template, notebook_cells(template)) == 22

    def wrong_key(payload):
        payload["backends"][0]["calls"][0]["replay_key"] = "a" * 64

    _replace_audit_line(template, "audit", wrong_key)
    with pytest.raises(AssertionError, match="differ from fixture inventory"):
        _request_audit.audit_recipe(template, notebook_cells(template))

    folder, _ = _audited_mini_recipe(tmp_path, n=3)
    genuine = folder.parent / "genuine.ipynb"
    shutil.copy(folder / "notebook.ipynb", genuine)
    assert _request_audit.audit_recipe(folder, notebook_cells(folder)) == 3

    def malformed_key(payload):
        payload["backends"][0]["calls"][0]["replay_key"] = "not-a-key"

    def duplicated_key(payload):
        calls = payload["backends"][0]["calls"]
        calls[1]["replay_key"] = calls[0]["replay_key"]

    for edit, message in (
        (malformed_key, "malformed replay key"),
        (duplicated_key, "stated distinct count differs"),
    ):
        shutil.copy(genuine, folder / "notebook.ipynb")
        _replace_audit_line(folder, "audit", edit)
        with pytest.raises(AssertionError, match=message):
            _request_audit.audit_recipe(folder, notebook_cells(folder))

    shutil.copy(genuine, folder / "notebook.ipynb")
    _replace_audit_line(folder, "audit", wrong_key)
    # The recorded limit: a well-formed wrong key on a backend with no inventory passes the guard.
    assert _request_audit.audit_recipe(folder, notebook_cells(folder)) == 3
    fresh = load_tool("check_notebook_fresh.py")
    assert fresh.main([str(genuine), str(genuine)]) == 0
    assert fresh.main([str(folder / "notebook.ipynb"), str(genuine)]) == 1


# --------------------------------------------------------------------------------------------
# check 8c: one budget per backend (#213): a recipe builds exactly the backends it audits
# --------------------------------------------------------------------------------------------


def _backend_sites(sources: list[str], name: str) -> int:
    """How many places ``sources`` (one recipe's code, in any number of files) can reach ``name``.

    Counted: every load of ``name`` or of a local alias made by ``from ... import name as alias``,
    every ``.name`` attribute, and every string equal to ``name`` (``getattr(module, "name")``).
    A call, a bare reference (``gb = get_backend``) and a dynamic lookup each count once, so a
    second backend cannot hide behind a rename. The import itself is not a site.
    """
    trees = [ast.parse(source) for source in sources]
    names = {name}
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names.update(a.asname for a in node.names if a.name == name and a.asname)
    count = 0
    for tree in trees:
        for node in ast.walk(tree):
            count += isinstance(node, ast.Name) and node.id in names
            count += isinstance(node, ast.Attribute) and node.attr == name
            count += isinstance(node, ast.Constant) and node.value == name
    return count


def _backend_budget_verdict(folder: Path) -> tuple[str, str]:
    """``("pass" | "fail", message)`` for one recipe folder.

    ``JEV_COOKBOOK_LIVE_MAX_REQUESTS`` caps one backend object, so a second ``get_backend`` is a
    second budget that a README cap, the count audit and a reader following either would not
    see (recipe 37's review found 73 live requests against a README promising 37). A recipe therefore
    has no more ``get_backend`` call sites, in its notebook and ``helpers.py``, than it has
    audited backends (an unaudited recipe: at most one), and an audited recipe builds its
    backends in the notebook, where the audit can see them. This counts call sites in source,
    so one site reached many times (a loop, a helper called twice) is invisible to it; an alias
    (``import get_backend as gb``), an attribute (``module.get_backend``), a bare reference or a
    ``getattr`` string each count as a site. A
    loop or comprehension is not rejected on sight: recipe 50 selects one of three lanes inside
    a dict comprehension and builds exactly one ``get_backend``. What counts a site reached more
    than once is the audited route's committed ledger.
    """
    notebook = [cell_source(cell) for cell in notebook_cells(folder) if cell["cell_type"] == "code"]
    helpers = (
        (folder / "helpers.py").read_text("utf-8") if (folder / "helpers.py").is_file() else ""
    )
    notebook_sites = _backend_sites(notebook, "get_backend")
    helpers_sites = _backend_sites([helpers], "get_backend")
    audited = _backend_sites(notebook, "AuditedBackend")
    allowed = audited or 1
    if notebook_sites + helpers_sites > allowed:
        return "fail", (
            f"{notebook_sites + helpers_sites} get_backend call sites "
            f"({notebook_sites} in the notebook, {helpers_sites} in helpers.py) for "
            f"{audited or 'no'} audited backend(s): each is its own request budget"
        )
    if audited and helpers_sites:
        return "fail", "an audited recipe builds its backends in the notebook, not in helpers.py"
    return "pass", ""


@pytest.mark.parametrize("recipe", guarded("one_backend_per_budget"))
def test_a_recipe_builds_exactly_the_backends_it_audits(recipe):
    """See ``_backend_budget_verdict``: one request budget per ``get_backend`` call."""
    status, message = _backend_budget_verdict(recipe_dir(recipe))
    assert status == "pass", f"{recipe['slug']}: {message}"


def _mini_recipe(tmp_path: Path, cells: list[str], helpers: str = "") -> Path:
    folder = tmp_path / "mini"
    folder.mkdir()
    notebook = {
        "cells": [{"cell_type": "code", "source": source, "outputs": []} for source in cells]
    }
    (folder / "notebook.ipynb").write_text(json.dumps(notebook), "utf-8")
    (folder / "helpers.py").write_text(helpers, "utf-8")
    return folder


_ONE = "from jev_cookbook import get_backend\nbackend = get_backend(script=f)"
_AUDITED_ONE = (
    "from jev_cookbook import AuditedBackend, get_backend\n"
    "backend = AuditedBackend(get_backend(script=f))"
)
_AUDITED_TWO = (
    "from jev_cookbook import AuditedBackend, get_backend\n"
    "a = AuditedBackend(get_backend(script=f), label='a')\n"
    "b = AuditedBackend(get_backend(script=g), label='b')"
)


@pytest.mark.parametrize(
    "cells,helpers",
    [
        ([_ONE], ""),
        ([_ONE], "def decide(backend):\n    return backend\n"),
        (
            [
                "from jev_cookbook import get_backend\nb = {n: get_backend(script=f) if n == 'a' else n for n in 'ab'}"
            ],
            "",
        ),
        (["from jev_cookbook import get_backend as gb\nb = gb(script=f)"], ""),
        ([_AUDITED_ONE], ""),
        ([_AUDITED_TWO], ""),
        (["x = 1"], ""),
    ],
    ids=[
        "one",
        "one-and-helpers",
        "one-in-a-comprehension",
        "one-through-an-alias",
        "audited",
        "two-audited",
        "none",
    ],
)
def test_one_budget_per_backend_accepts_the_supported_shapes(tmp_path, cells, helpers):
    assert _backend_budget_verdict(_mini_recipe(tmp_path, cells, helpers)) == ("pass", "")


@pytest.mark.parametrize(
    "cells,helpers,expected",
    [
        # recipe 37's defect: a second get_backend, hence a second, fresh budget
        ([_ONE, "backend2 = get_backend(script=g)"], "", "2 get_backend call sites"),
        ([_ONE], "def again():\n    return get_backend(script=g)\n", "1 in helpers.py"),
        (
            [_ONE, "from jev_cookbook import backends\nb = backends.get_backend(script=g)"],
            "",
            "2 get_backend call sites",
        ),
        ([_ONE + "\nbackends = [get_backend(script=g) for _ in range(2)]"], "", "2 get_backend"),
        ([_ONE + "\nfor _ in range(2):\n    get_backend(script=g)"], "", "2 get_backend"),
        # the same second budget behind a rename, an attribute, a bare reference or a lookup
        (
            [_ONE, "from jev_cookbook import get_backend as gb\nraw = gb(script=g)"],
            "",
            "get_backend call sites",
        ),
        (
            ["from jev_cookbook import get_backend as gb\na = gb(script=f)\nb = gb(script=g)"],
            "",
            "2 get_backend call sites",
        ),
        ([_ONE, "import jev_cookbook as jc\nraw = jc.get_backend(script=g)"], "", "2 get_backend"),
        ([_ONE, "gb = get_backend\nraw = gb(script=g)"], "", "get_backend call sites"),
        (
            [_ONE, "import jev_cookbook\nraw = getattr(jev_cookbook, 'get_backend')(script=g)"],
            "",
            "2 get_backend call sites",
        ),
        (
            [_ONE],
            "from jev_cookbook import get_backend as gb\ndef again():\n    return gb(script=g)\n",
            "1 in helpers.py",
        ),
        # an audited recipe: one site per audited backend, and none in helpers.py
        ([_AUDITED_ONE, "extra = get_backend(script=g)"], "", "2 get_backend call sites"),
        ([_AUDITED_TWO + "\nc = get_backend(script=h)"], "", "3 get_backend call sites"),
        (
            [_AUDITED_ONE],
            "def make():\n    return get_backend(script=g)\n",
            "get_backend call sites",
        ),
    ],
    ids=[
        "second-in-notebook",
        "second-in-helpers",
        "attribute-call",
        "second-in-comprehension",
        "second-in-loop",
        "alias-in-notebook",
        "alias-used-twice",
        "module-alias-attribute",
        "bare-reference",
        "getattr-string",
        "alias-in-helpers",
        "audited-plus-raw",
        "two-audited-plus-raw",
        "audited-helper",
    ],
)
def test_one_budget_per_backend_fails_a_second_budget(tmp_path, cells, helpers, expected):
    status, message = _backend_budget_verdict(_mini_recipe(tmp_path, cells, helpers))
    assert status == "fail" and expected in message


# --------------------------------------------------------------------------------------------
# check 9: no ".[dev,ml]" install line in the README
# --------------------------------------------------------------------------------------------


def _load_readme_install() -> ModuleType:
    """``tests/readme_install.py``, loaded by file path like ``_load_known_failures`` above: the
    rule about ``.[dev,ml]`` in a README is shared with ``tests/test_new_recipe.py``'s check on
    the scaffold's output, so what the rule forbids is written, and proved, once."""
    spec = importlib.util.spec_from_file_location(
        "readme_install_for_recipe_guard",
        Path(__file__).resolve().parent / "readme_install.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_readme_install = _load_readme_install()


@pytest.mark.parametrize("recipe", guarded("readme_no_dev_ml_install"))
def test_the_readme_never_installs_dev_and_ml_combined(recipe):
    """docs/recipe-template.md step 6: reproducing committed outputs installs ``.[ml]`` alone
    (``nbclient``/``ipykernel`` are core dependencies, so ``.[ml]`` is already enough to execute
    the notebook; ``.[dev]`` is for ``ruff``/``pytest``, which that job does not run). The
    pre-#162 README paragraph combined them into one ``.[dev,ml]`` install line (R15).

    Until #238 this was ``".[dev,ml]" not in readme``, which also forbade the string where it is
    right: the install for running the recipe's tests, which both ``Tests`` jobs now run with the
    ``ml`` extra. It now refuses ``.[dev,ml]`` in a paragraph that is about reproducing committed
    outputs (see ``tests/readme_install.py``) and nowhere else."""
    readme = (recipe_dir(recipe) / "README.md").read_text("utf-8")
    assert _readme_install.combined_reproduction_installs(readme) == []


def _readme_install_subjects() -> list:
    """The template and the first published README that has a test-install line (the scaffold's
    ``.[dev,ml]`` or the legacy bare ``.[dev]``) and the reproduction install: the two shapes the
    rule is proved against. A README need not carry both test-install spellings."""
    scaffold_install = f'pip install -e "{_readme_install.COMBINED}"'

    def has_both(text: str) -> bool:
        return _readme_install.REPRODUCTION_INSTALL in text and (
            scaffold_install in text or _readme_install.TEST_INSTALL in text
        )

    published = [
        p / "README.md"
        for p in sorted(RECIPES_DIR.iterdir())
        if p.name != "_template"
        and (p / "README.md").is_file()
        and has_both((p / "README.md").read_text("utf-8"))
    ]
    assert published, "no published README has a test install and the reproduction install"
    return [
        pytest.param(RECIPES_DIR / "_template" / "README.md", id="_template"),
        pytest.param(published[0], id=published[0].parent.name),
    ]


@pytest.mark.parametrize("path", _readme_install_subjects())
def test_a_readme_may_document_dev_and_ml_for_the_tests_install(path):
    """#238: the install that runs a scikit-learn recipe's tests is ``.[dev,ml]``; a README may say
    so (it fails the pre-#238 literal check and passes this one), as long as its reproduction
    paragraph still says ``.[ml]``."""
    readme = _readme_install.with_documented_test_install(path.read_text("utf-8"))
    assert ".[dev,ml]" in readme
    assert _readme_install.combined_reproduction_installs(readme) == []


@pytest.mark.parametrize("path", _readme_install_subjects())
def test_a_readme_may_not_reproduce_outputs_with_dev_and_ml(path):
    """The wording the check was written against stays refused: the pre-#162 reproduction line
    (``.[dev,ml]`` with the constraints file), however the line is wrapped, and ``.[dev,ml]`` in
    any paragraph that says it reproduces the outputs, with or without the constraints file."""
    readme = path.read_text("utf-8")
    assert _readme_install.combined_reproduction_installs(readme) == []
    old = _readme_install.with_pre_162_reproduction_install(readme)
    assert len(_readme_install.combined_reproduction_installs(old)) == 1
    wrapped = old.replace('".[dev,ml]" -c', '".[dev,ml]"\n-c')
    assert len(_readme_install.combined_reproduction_installs(wrapped)) == 1
    no_constraints = (
        readme.rstrip() + "\n\nTo reproduce the committed outputs byte for byte run"
        ' `pip install -e ".[dev,ml]"`.\n'
    )
    assert len(_readme_install.combined_reproduction_installs(no_constraints)) == 1


# --------------------------------------------------------------------------------------------
# check 10: the "measured" cell's offline branch prints N (#215)
# --------------------------------------------------------------------------------------------

MEASURED_SIGNATURE = "Not measured live: a pipeline check, not a Jev result."


def _load_measured_cell_branches() -> ModuleType:
    """``tests/measured_cell_branches.py``, loaded by file path like
    ``_load_known_failures`` above: the branch-anchoring and "really prints N" logic is shared
    with ``tests/test_template.py``'s own pin on the template, so the one piece of logic that
    decides "which branch discloses the run mode, and does it really print N" is written, and
    proved against PR #219 reviewer B's evasions, once rather than twice."""
    spec = importlib.util.spec_from_file_location(
        "measured_cell_branches_for_recipe_guard",
        Path(__file__).resolve().parent / "measured_cell_branches.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_measured_cell = _load_measured_cell_branches()


def _disclosure_branches(source: str) -> list[list[ast.stmt]]:
    return _measured_cell.disclosure_branches(source, MEASURED_SIGNATURE)


_branch_prints_n = _measured_cell.branch_prints_n


@pytest.mark.parametrize("recipe", guarded("measured_cell_prints_n_offline"))
def test_the_measured_cell_prints_n_in_the_offline_branch(recipe):
    """CONTRIBUTING.md section 2: the disclosure names, "in every mode", the run mode and N --
    the number of examples a reported number covers. docs/recipe-template.md states the
    consequence explicitly: the "What was and was not measured" code cell's branches must each
    actually print N, so an offline run's branch prints it too, not only the recorded/live
    branch -- a markdown promise one branch of its own code does not keep is a defect in the
    cell, not something to soften in the prose.

    #215: the scaffolder's own version of this cell printed no N in the offline branch for weeks,
    and the only test naming this property, ``tests/test_new_recipe.py``, could not fail: it
    checked ``"N:" in measured`` against the whole cell rather than the offline branch alone, and
    the live (``else``) branch's own ``"N:"`` line satisfied that regardless of what the offline
    branch did. This check applies the same fix at the recipe level, over every published recipe
    (and the template), so a recipe scaffolded with the defect, or a hand-edit that drops N from
    one branch later, is caught here even when nothing else does.

    The cell is found by its disclosure sentence (``MEASURED_SIGNATURE``) rather than by cell id:
    most recipes call it ``measured``, but a few predate that convention (recipe 01 calls it
    ``measured-code``; recipe 05's id is an auto-generated hex string) -- the sentence itself is
    the one thing every recipe's version of this cell shares, by CONTRIBUTING.md's own "the
    disclosure is the same in every recipe" rule.

    The branch that must print N is found with ``ast``, anchored on whichever branch actually
    carries the disclosure (``_disclosure_branches``) -- not, as the first version of this check
    did, by splitting the source on the first ``else:`` and treating whatever comes before it as
    "the offline branch". That assumption is what let three shapes pass while the rule stayed
    broken (PR #219 reviewer B): an ``elif`` that moves N into a third branch while the
    disclosure stays in the ``if``; an inverted ``if not offline: ... else:`` that moves the
    disclosure into the ``else``; and ``# N: ...`` written as a comment, which a substring search
    over the branch's raw text cannot tell apart from an actual ``print``. ``_branch_prints_n``
    requires a real ``print`` call whose string argument starts with ``"N:"``, which closes all
    three. The ``else:`` requirement below is unchanged from the original check (a cell with no
    recorded/live branch at all still fails here, as it always did); what changed is how the
    branch to check is chosen and what counts as "prints N" within it."""
    cells = [
        c
        for c in notebook_cells(recipe_dir(recipe))
        if c["cell_type"] == "code" and MEASURED_SIGNATURE in cell_source(c)
    ]
    assert cells, f"{recipe['slug']}: no code cell carries the disclosure sentence"
    for cell in cells:
        source = cell_source(cell)
        assert "else:" in source, f"{recipe['slug']}: cell {cell.get('id', '?')} has no else branch"
        branches = _disclosure_branches(source)
        assert branches, (
            f"{recipe['slug']}: cell {cell.get('id', '?')} carries the disclosure sentence but "
            "not inside any if/elif/else branch this check can parse"
        )
        for branch in branches:
            assert _branch_prints_n(branch), (
                f"{recipe['slug']}: cell {cell.get('id', '?')}'s branch carrying the disclosure "
                "prints no N"
            )
        # The committed, stored output must carry a line starting "N:" too (the same pin
        # tests/test_template.py makes on the template, tests/test_template.py:398): a cell
        # whose source prints N but whose committed output was captured from a stale run that did
        # not would otherwise pass the check above and still mislead a reader of the rendered
        # notebook, who sees only the stored output, never the source.
        lines = "".join(
            "".join(o.get("text", ""))
            for o in cell.get("outputs", [])
            if o.get("output_type") == "stream"
        ).splitlines()
        assert any(line.startswith("N:") for line in lines), (
            f"{recipe['slug']}: cell {cell.get('id', '?')}'s committed stdout has no line "
            "starting with N:"
        )


# --------------------------------------------------------------------------------------------
# check 11: the threshold-selection OBJECTIVE is pinned by source spelling (#244)
# --------------------------------------------------------------------------------------------

# For each function, the complete set of spellings its objective can take: the keyword
# argument name for select_confidence_threshold (mutually exclusive, no default -- exactly one
# is given), or the string value of select_threshold's `objective` argument (positional or
# keyword; defaults to "f1" when omitted entirely).
THRESHOLD_OBJECTIVE_SPELLINGS = {
    "select_confidence_threshold": ("target_accuracy", "min_coverage"),
    "select_threshold": ("f1", "recall_at_precision", "precision_at_recall"),
}
# Every spelling of either function, for the extraction route's one-spelling rule.
ALL_OBJECTIVE_SPELLINGS = frozenset(
    spelling for spellings in THRESHOLD_OBJECTIVE_SPELLINGS.values() for spelling in spellings
)


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """``{alias: real_name}`` for ``from jev_cookbook.evaluation import select_threshold as X``
    style renames of either threshold function, so a call made *through* the alias is not
    silently invisible to the rest of this check (a reviewer measured this on a throwaway
    mutation of recipe 38: ``import ... as _sct`` then ``_sct(...)`` made the unmodified check
    below report "no threshold call here" -- fail OPEN, the wrong default for a check whose
    whole purpose is to fail closed). No published recipe does this today; this exists so the
    guard does not silently stop seeing a recipe that starts to."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in THRESHOLD_OBJECTIVE_SPELLINGS and alias.asname:
                    aliases[alias.asname] = alias.name
    return aliases


def _resolved_call_name(call: ast.Call, aliases: dict[str, str]) -> str | None:
    """The real function name ``call`` resolves to -- ``select_confidence_threshold`` or
    ``select_threshold``, by direct name or via ``aliases`` -- or ``None`` for anything else
    (including a call through an attribute such as ``jev_cookbook.evaluation.select_threshold
    (...)``, which no published recipe uses and which this does not attempt to resolve; that
    residual gap is disclosed rather than silently assumed away)."""
    if not isinstance(call.func, ast.Name):
        return None
    name = call.func.id
    if name in THRESHOLD_OBJECTIVE_SPELLINGS:
        return name
    return aliases.get(name)


def _call_func_name(call: ast.Call) -> str | None:
    """The bare name one call is made through -- ``f(...)`` or ``x.f(...)`` -- or ``None`` for
    a callee shape with no simple name (``(lambda: ...)()``). Used only to check membership in
    a *name-based* set (a recipe's own taint-producing helper functions, or a ``helpers.py``
    production wrapper); it is not the same resolution ``_resolved_call_name`` does for the two
    specific threshold functions themselves."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _threshold_call_objective(call: ast.Call, resolved_name: str) -> str | None:
    """The objective actually selected by one real call already known (via
    ``_resolved_call_name``) to resolve to ``resolved_name``: the keyword-argument NAME present
    for ``select_confidence_threshold`` (``target_accuracy`` or ``min_coverage`` -- whichever
    the call actually binds), or the string VALUE of ``select_threshold``'s ``objective``
    argument, given positionally (3rd argument) or as the keyword ``objective=``. Parsed from
    the already-parsed ``ast.Call`` node, not by regex on text: a value that merely contains a
    keyword's spelling as a substring elsewhere in the call (inside an unrelated string
    argument, say) cannot be mistaken for the argument binding itself. Returns ``None`` for a
    call shape this cannot identify an objective for (not observed in the published set; such a
    call is still flagged, as an unidentifiable objective, by the check below rather than
    silently skipped)."""
    if resolved_name == "select_confidence_threshold":
        for kw in call.keywords:
            if kw.arg in ("target_accuracy", "min_coverage"):
                return kw.arg
        return None
    for kw in call.keywords:
        if (
            kw.arg == "objective"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value
    if (
        len(call.args) >= 3
        and isinstance(call.args[2], ast.Constant)
        and isinstance(call.args[2].value, str)
    ):
        return call.args[2].value
    return None


def _real_threshold_calls(tree: ast.AST, aliases: dict[str, str]) -> list[tuple[ast.Call, str]]:
    """``(call, resolved_function_name)`` for every genuine ``ast.Call`` node resolving to
    ``select_confidence_threshold``/``select_threshold`` -- real code, never text that merely
    looks like a call inside a string literal (an f-string's hand-written decoration quoting
    the call shape beside it, exactly the pattern #244 found inert). A plain substring/paren-
    balance scan over the cell's raw text, as this module's own ``extract_calls`` does for
    other checks, cannot tell the two apart; walking the already-parsed AST can, because a
    string constant is never an ``ast.Call`` node regardless of what text it contains."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            resolved = _resolved_call_name(node, aliases)
            if resolved is not None:
                found.append((node, resolved))
    return found


def _threshold_pin_obligations(recipe_dir_: Path) -> list[tuple[str, str, str | None]]:
    """``(location, function_name, objective)`` for every real threshold-selection call in this
    recipe's committed ``notebook.ipynb`` code cells or its ``helpers.py`` -- both are scanned
    (not the notebook alone) because three published recipes (28, 31, 35) route the call
    through a ``helpers.py`` wrapper the notebook merely calls by name, and checking only the
    notebook would silently *skip* them rather than reveal that they, too, lack the pin -- the
    same blind spot #222's ``G1(c)`` already has for exactly this shape, which this check must
    not repeat (see the pull request body).

    A code cell or ``helpers.py`` that does not parse as plain Python (an IPython magic, or any
    other syntax error) is reported as its own obligation, with function name
    ``"<unparseable>"`` and objective ``None`` -- a hard failure naming what is wrong, never a
    silent skip and never a raw ``SyntaxError`` traceback blamed on the recipe.

    Import aliases are resolved across the WHOLE notebook, not cell by cell: a notebook's
    ``from jev_cookbook.evaluation import select_threshold as X`` import and the cell that
    calls ``X(...)`` are essentially never the same cell (the import lives in an early setup
    cell; the call lives in the evaluation cell), and ``ast.parse`` on one cell's own source
    can never see an import statement written in a different cell. Parsing each cell on its
    own and resolving aliases against that one cell's tree alone -- an earlier version of this
    function did exactly that -- means the alias fix below cannot actually fire for any
    notebook: 0 of 46 published recipes have the import and the call in the same cell, so a
    reviewer's recipe-38 alias mutation still returned ``SKIP (no obligations)`` under it,
    silently, which is worse than not attempting the fix at all. Building one merged
    ``{alias: real_name}`` map from every code cell first, then resolving every cell's own
    calls against that merged map, is what makes the alias route actually reachable."""
    obligations: list[tuple[str, str, str | None]] = []
    notebook = recipe_dir_ / "notebook.ipynb"
    if notebook.is_file():
        code_cells = [c for c in notebook_cells(recipe_dir_) if c["cell_type"] == "code"]
        parsed: list[tuple[dict, ast.Module | None]] = []
        merged_aliases: dict[str, str] = {}
        for cell in code_cells:
            try:
                tree = ast.parse(cell_source(cell))
            except SyntaxError:
                parsed.append((cell, None))
                continue
            parsed.append((cell, tree))
            merged_aliases.update(_import_aliases(tree))
        for cell, tree in parsed:
            location = f"cell {cell.get('id', '?')}"
            if tree is None:
                obligations.append((location, "<unparseable>", None))
                continue
            for call, resolved in _real_threshold_calls(tree, merged_aliases):
                obligations.append((location, resolved, _threshold_call_objective(call, resolved)))
    helpers_path = recipe_dir_ / "helpers.py"
    if helpers_path.is_file():
        try:
            tree = ast.parse(helpers_path.read_text("utf-8"))
        except SyntaxError:
            obligations.append(("helpers.py", "<unparseable>", None))
        else:
            aliases = _import_aliases(tree)
            for call, resolved in _real_threshold_calls(tree, aliases):
                obligations.append(
                    ("helpers.py", resolved, _threshold_call_objective(call, resolved))
                )
    return obligations


def _test_function_defs(tree: ast.AST) -> list[ast.FunctionDef]:
    """Every ``test_...`` function in an already-parsed test file that pytest would actually RUN,
    found from the module's own AST -- deliberately not a text scan that locates one function by
    name and then regexes forward to the next ``\\n(?:def |class )`` to find where it ends
    (``_find_function_body``, above, does that for a single named function). That scan-forward
    shape is unsound in general: a decorator line is neither ``def`` nor ``class``, so a decorated
    neighbour (``@pytest.mark.parametrize`` on the very next function, common in this codebase)
    folds into the "body" it returns, and parsing that text then raises a ``SyntaxError`` that is
    really a bug in the extraction, not in the recipe (#272).

    What counts as "would run" mirrors pytest's collection rules, and fails closed where this
    cannot tell: a module-level ``test_`` function, or a ``test_`` method of a top-level class
    that pytest collects (named ``Test*``, defining no ``__init__``/``__new__``), unless the
    function, the class (decorator or class-body ``pytestmark``) or the module (``pytestmark``, or
    a top-level ``pytest.importorskip(...)`` / ``pytest.skip(..., allow_module_level=True)``)
    carries a ``skip``/``skipif``/``xfail`` mark or skips the file. A ``test_`` def nested in
    another function, a method of a helper class (``class Helper:``), and anything else pytest
    would not collect is not a test and pins nothing, nor is one in a module or class that sets
    ``__test__`` to anything but ``True``, or one a later ``def`` of the same name replaces. (A
    ``unittest.TestCase`` subclass not named ``Test*`` and a nested ``Test*`` class are not
    credited either: the safe, loud direction. A ``Test*`` class that inherits an ``__init__`` or
    ``__test__`` from a base defined in the SAME file is not credited; one inherited from an
    imported base is, and is recorded as accepted.) A module-level ``importorskip`` of a module that IS installed does not
    really skip the file, but a static check cannot tell, so it is not credited."""
    if (
        _module_is_marked_not_to_run(tree)
        or _module_skips_itself(tree)
        or _disables_collection(getattr(tree, "body", []))
    ):
        return []
    candidates: list[ast.FunctionDef] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.FunctionDef):
            candidates.append(node)
        elif isinstance(node, ast.ClassDef) and _pytest_collects_class(node, tree):
            candidates.extend(_unshadowed(node.body))
    gone = {id(d) for d in _shadowed(getattr(tree, "body", []))}
    candidates = [n for n in candidates if id(n) not in gone]
    return [
        node
        for node in candidates
        if node.name.startswith("test_") and not _is_marked_not_to_run(node.decorator_list)
    ]


def _shadowed(body: list[ast.stmt]) -> list[ast.FunctionDef]:
    """The functions in ``body`` that a LATER ``def`` of the same name replaces: Python keeps the
    last binding, so pytest runs only that one, and an assert in the earlier body never runs."""
    defs = [n for n in body if isinstance(n, ast.FunctionDef)]
    return [d for i, d in enumerate(defs) if any(later.name == d.name for later in defs[i + 1 :])]


def _unshadowed(body: list[ast.stmt]) -> list[ast.FunctionDef]:
    gone = {id(d) for d in _shadowed(body)}
    return [n for n in body if isinstance(n, ast.FunctionDef) and id(n) not in gone]


def _disables_collection(body: list[ast.stmt]) -> bool:
    """``__test__ = <anything but True>`` in a module or class body: pytest collects nothing from
    it. A value this cannot read counts as disabled (the fail-closed side)."""
    for stmt in body:
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "__test__" for t in targets):
            value = stmt.value
            if not (isinstance(value, ast.Constant) and value.value is True):
                return True
    return False


def _pytest_collects_class(node: ast.ClassDef, tree: ast.AST | None = None) -> bool:
    """True if pytest would collect ``node``'s ``test_`` methods: the name matches the default
    ``python_classes = Test*``, it defines no ``__init__`` / ``__new__`` (pytest warns and skips
    such a class), and it is not marked ``skip``/``skipif``/``xfail`` by a class decorator or a
    class-body ``pytestmark``."""
    local = {
        n.name: n for n in getattr(tree, "body", []) if isinstance(n, ast.ClassDef)
    }  # classes defined in the same module, to follow ``class TestX(Base)``

    def poisoned(cls: ast.ClassDef, seen: frozenset[str]) -> bool:
        if _disables_collection(cls.body) or any(
            isinstance(n, ast.FunctionDef) and n.name in ("__init__", "__new__") for n in cls.body
        ):
            return True
        return any(
            isinstance(b, ast.Name)
            and b.id in local
            and b.id not in seen
            and poisoned(local[b.id], seen | {b.id})
            for b in cls.bases
        )

    return (
        node.name.startswith("Test")
        and not poisoned(node, frozenset({node.name}))
        and not _is_marked_not_to_run(node.decorator_list)
        and not _module_is_marked_not_to_run(node)
    )


def _module_skips_itself(tree: ast.AST) -> bool:
    """A top-level ``pytest.importorskip(...)`` or ``pytest.skip(..., allow_module_level=True)``
    (also under a module-level ``if``/``try``, or as the value of an assignment): the whole file is
    skipped, so none of its asserts run. Function and class bodies are not searched."""
    for stmt in getattr(tree, "body", []):
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for node in _walk_same_scope(stmt):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "importorskip":
                return True
            if name == "skip" and any(k.arg == "allow_module_level" for k in node.keywords):
                return True
    return False


_NOT_RUN_MARKS = frozenset({"skip", "skipif", "xfail"})


def _is_marked_not_to_run(decorators: list[ast.expr]) -> bool:
    """True if a decorator list carries ``pytest.mark.skip`` / ``skipif`` / ``xfail`` (bare or
    called): the asserts of such a test do not (reliably) run, so they pin nothing."""
    for decorator in decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in _NOT_RUN_MARKS:
            return True
    return False


def _module_is_marked_not_to_run(tree: ast.AST) -> bool:
    """A module-level ``pytestmark = pytest.mark.skip(...)`` (or a list holding one)."""
    for node in getattr(tree, "body", []):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
            and _is_marked_not_to_run(
                list(node.value.elts)
                if isinstance(node.value, ast.List | ast.Tuple)
                else [node.value]
            )
        ):
            return True
    return False


_ARTEFACT_FILE_NAMES = ("notebook.ipynb", "helpers.py")

# Names pytest gives a test its scratch directory under. A path rooted there is a COPY a test made
# (usually to mutate it), not the committed artefact, so a read of it does not taint.
_SCRATCH_DIR_NAMES = frozenset({"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory"})

# Callables that read a file's contents. This is the set of ways Python spells "read this file",
# not a set of spellings of an objective: it only decides whether a statement that names the
# committed artefact also READS it (as opposed to merely mentioning its name in a string), so a
# read via ``open(...).read()``, ``read_bytes()`` or ``with open(...) as f: f.read()`` seeds taint
# exactly as ``read_text()`` does.
_FILE_READ_ATTRS = frozenset({"read_text", "read_bytes", "read", "readlines", "open"})


def _mentions_artefact_file(node: ast.AST) -> bool:
    """True if ``node`` contains a string that IS one of the committed file names (or a path
    ending in ``/<name>``) -- not a longer name that merely contains it (``expected_helpers.py``)."""
    return any(
        isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and any(n.value == name or n.value.endswith("/" + name) for name in _ARTEFACT_FILE_NAMES)
        for n in ast.walk(node)
    )


# Calls that MAKE a scratch location or a copy of a file somewhere else (#320): a path built from
# one of these is a test-made copy exactly as a path under ``tmp_path`` is, so a read of it does not
# taint either. ``tempfile.*`` and ``shutil.*``; a bare name is accepted for the ``from tempfile
# import mkdtemp`` spelling. A copy placed under any other root is still not seen (accepted).
_TEMPFILE_NAMES = frozenset(
    {
        "mkdtemp",
        "mkstemp",
        "gettempdir",
        "TemporaryDirectory",
        "NamedTemporaryFile",
        "SpooledTemporaryFile",
    }
)
_COPY_FUNCS = frozenset({"copy", "copy2", "copyfile", "copytree", "move"})


def _module_aliases(tree: ast.AST) -> dict[str, str]:
    """``{local name: dotted real name}`` for every import in ``tree``: ``import tempfile as tf``
    gives ``tf -> tempfile`` and ``from tempfile import TemporaryDirectory as TD`` gives ``TD ->
    tempfile.TemporaryDirectory`` (an unaliased import maps to itself)."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _scratch_call_kind(call: ast.Call, aliases: dict[str, str] | None) -> str | None:
    """``"tempfile"`` for a call that makes a scratch location, ``"copy"`` for the ``shutil`` copy
    family, else ``None``. Resolved through the module's imports (``import tempfile as tf``), and
    by bare name for ``from tempfile import mkdtemp``. Other ``shutil``/``tempfile`` calls
    (``shutil.which``) are not scratch makers."""
    aliases = aliases or {}
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        module = aliases.get(func.value.id, func.value.id)
        if module == "tempfile":
            return "tempfile"
        if module == "shutil" and func.attr in _COPY_FUNCS:
            return "copy"
    elif isinstance(func, ast.Name):
        module, _, name = aliases.get(func.id, func.id).rpartition(".")
        if module == "tempfile" or (not module and name in _TEMPFILE_NAMES):
            return "tempfile"
        if module == "shutil" and name in _COPY_FUNCS:
            return "copy"
        if not module and name in {"copy2", "copyfile", "copytree"}:
            return "copy"
    return None


def _makes_scratch(node: ast.AST, aliases: dict[str, str] | None = None) -> bool:
    """True if ``node`` contains a call that makes a scratch directory or a copy of a file."""
    return any(
        isinstance(n, ast.Call) and _scratch_call_kind(n, aliases) is not None
        for n in ast.walk(node)
    )


def _copy_destinations(func: ast.AST, aliases: dict[str, str] | None) -> set[str]:
    """The names in the destination of every ``shutil.copy*``/``move`` call in ``func``, however
    the call is used (a bare statement included): what is copied there is a test-made copy."""
    names: set[str] = set()
    for n in ast.walk(func):
        if isinstance(n, ast.Call) and _scratch_call_kind(n, aliases) == "copy":
            dst = n.args[1] if len(n.args) > 1 else None
            for keyword in n.keywords:
                if keyword.arg == "dst":
                    dst = keyword.value
            if dst is not None:
                names |= _ast_names(dst)
    return names


def _mentions_scratch_dir(node: ast.AST, aliases: dict[str, str] | None = None) -> bool:
    return _makes_scratch(node, aliases) or any(
        (isinstance(n, ast.Name) and n.id in _SCRATCH_DIR_NAMES)
        or (isinstance(n, ast.arg) and n.arg in _SCRATCH_DIR_NAMES)
        for n in ast.walk(node)
    )


# The committed recipe folders are named ``NN-slug``. A read that spells such a name is a read of
# ONE recipe's artefact chosen by hand (#320): a recipe's own tests locate their folder from
# ``__file__``, so a hard-coded slug is another recipe's notebook (or the recipe's own, which the
# guard cannot tell apart and refuses -- the fail-closed direction).
_RECIPE_SLUG = re.compile(r"\d{2,3}-[a-z0-9][a-z0-9-]*")


def _names_a_recipe_folder(node: ast.AST) -> bool:
    """A string constant shaped like a recipe folder name (``42-...``, ``100-...``) that is a path
    part or an argument. A slug-shaped cell id used as a subscript key or compared with ``==``
    (``c["id"] == "10-threshold"``) is data, not a path, and is not counted. A slug held in a
    variable, split or built by an f-string is not seen (accepted, recorded in the docs)."""
    data = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Compare):
            data.update(id(o) for o in [n.left, *n.comparators])
        elif isinstance(n, ast.Subscript):
            data.add(id(n.slice))
    return any(
        isinstance(n, ast.Constant)
        and id(n) not in data
        and isinstance(n.value, str)
        and any(_RECIPE_SLUG.fullmatch(part) for part in n.value.split("/"))
        for n in ast.walk(node)
    )


# Methods that rewrite the characters of the text they are called on. A value that went through
# one is no longer "the committed source": a pin compared against it is satisfied by text the
# source only matches after the rewrite (``"min_coverage" in source.lower()`` holds for a comment
# that says ``MIN_COVERAGE`` while the call uses ``target_accuracy``). Such a value is never
# credited (#320); compare against the untransformed source instead. ``replace`` is not listed:
# what it types is tracked per name (``_Taint.embedded``).
_TEXT_REWRITING_METHODS = frozenset(
    {"lower", "upper", "casefold", "swapcase", "title", "capitalize", "translate"}
)


def _rewrites_text(node: ast.AST, tainted: frozenset[str] = frozenset()) -> bool:
    """True if ``node`` rewrites the characters of the SOURCE value: a ``.lower()``-family call
    whose receiver is a read of the committed file, a tainted name or a comprehension variable;
    the same method named without being called (``map(str.lower, ...)``,
    ``functools.partial(str.lower)``); or named by string (``getattr(x, "lower")``,
    ``operator.methodcaller("lower")``). A ``.lower()`` on something that is not the source
    (``read_text(enc.lower())``) does not count; one on a cell field inside the read
    (``c["cell_type"].lower()``) does, the fail-closed side. A rewrite stored under a name in
    another statement (``f = str.lower`` then ``f(source)``) is not seen (accepted)."""
    call_funcs = {id(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)}
    targets: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.comprehension):
            targets |= _ast_names(n.target)
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            if isinstance(func, ast.Attribute) and func.attr in _TEXT_REWRITING_METHODS:
                # the receiver (``source.lower()``) or an argument (``str.lower(source)``)
                for operand in (func.value, *n.args):
                    if _reads_real_committed_source(operand) or (
                        _ast_names(operand) & (set(tainted) | targets)
                    ):
                        return True
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called in {"getattr", "methodcaller"} and any(
                isinstance(a, ast.Constant) and a.value in _TEXT_REWRITING_METHODS for a in n.args
            ):
                return True
        elif (
            isinstance(n, ast.Attribute)
            and n.attr in _TEXT_REWRITING_METHODS
            and id(n) not in call_funcs
        ):
            return True
    return False


def _opens_for_writing(call: ast.Call) -> bool:
    """True for an ``open`` call that is not provably a READ: a literal mode containing ``w``,
    ``a`` or ``x``, or a mode this cannot read (a name, an f-string). A missing mode is the
    default ``"r"``; ``"r+"`` and ``"rb"`` read. ``open(path, "w")`` makes a file, it does not
    read it (#320), so a ``with open(<committed file>, "w") as f`` binding must not taint ``f``.
    The mode is the SECOND argument of the builtin ``open`` (and ``io.open``/``codecs.open``) and
    the FIRST of ``Path.open``; ``mode=`` is accepted either way."""
    func = call.func
    builtin = isinstance(func, ast.Name) or (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in {"io", "codecs"}
    )
    if any(isinstance(a, ast.Starred) for a in call.args) or any(
        k.arg is None for k in call.keywords
    ):
        return True  # ``open(p, **kw)``: the mode cannot be read
    index = 1 if builtin else 0
    mode: ast.expr | None = call.args[index] if len(call.args) > index else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(flag in mode.value for flag in "wax")
    return True


def _is_open_call(call: ast.Call) -> bool:
    return (isinstance(call.func, ast.Name) and call.func.id == "open") or (
        isinstance(call.func, ast.Attribute) and call.func.attr == "open"
    )


def _performs_a_file_read(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        if _is_open_call(n):
            if not _opens_for_writing(n):
                return True
        elif isinstance(n.func, ast.Attribute) and n.func.attr in _FILE_READ_ATTRS:
            return True
    return False


def _reads_helpers_source_via_inspect(node: ast.AST) -> bool:
    for n in ast.walk(node):
        is_getsource = isinstance(n, ast.Call) and (
            (isinstance(n.func, ast.Attribute) and n.func.attr == "getsource")
            or (isinstance(n.func, ast.Name) and n.func.id == "getsource")
        )
        if not is_getsource:
            continue
        for inner in ast.walk(n):
            if isinstance(inner, ast.Name) and "helpers" in inner.id:
                return True
            if isinstance(inner, ast.Attribute) and "helpers" in inner.attr:
                return True
    return False


def _reads_real_committed_source(node: ast.AST, aliases: dict[str, str] | None = None) -> bool:
    """True if one piece of syntax (a single statement's value expression, a ``with`` item's
    context expression, or a whole function definition -- see ``_tainted_names_in_function`` and
    ``_locally_source_reading_function_names`` below) is the actual FILE READ of the *actual
    committed* notebook or ``helpers.py`` -- not a hand-typed duplicate of either, and not a
    later step of the same chain (extracting one cell, then joining its ``"source"``) that never
    itself mentions the file at all. That later step is carried by the generic name-reference
    propagation in ``_tainted_names_in_function``, which is why this function only needs to see
    the read itself (this used to also require ``"source"`` in the same statement as
    ``"notebook.ipynb"``, false for the template's own three-line chain).

    The property is "this syntax names the committed artefact AND performs a read": derived
    from the AST (a ``Call`` to ``open``, or to a ``read``-family method), not from the literal
    text ``read_text``. The earlier text test required that one spelling, so ``open(...).read()``
    and ``read_bytes()`` -- plainly real reads of the committed source -- produced no taint at
    all and a legitimate pin written that way was refused for how its read was spelled (#276).
    The second route is ``inspect.getsource(...)`` on something named ``helpers``, for a test
    that checks a helpers function's own source rather than a file."""
    return (
        _mentions_artefact_file(node)
        and _performs_a_file_read(node)
        and not _mentions_scratch_dir(node, aliases)
        and not _names_a_recipe_folder(node)
    ) or _reads_helpers_source_via_inspect(node)


def _production_wrapper_names(helpers_path: Path) -> set[str]:
    """Top-level function names defined in ``helpers.py`` whose own body makes a real
    threshold-selection call -- calling one of these from a test exercises the real objective,
    whatever it is, even though the test itself never reads ``helpers.py``'s text at all
    (recipe 28's ``helpers.select_margin_threshold``, used only through
    ``_spellings_pinned_by_production_discrimination`` below, since a bare call with no
    accompanying non-degeneracy check proves nothing by itself)."""
    if not helpers_path.is_file():
        return set()
    try:
        tree = ast.parse(helpers_path.read_text("utf-8"))
    except SyntaxError:
        return set()
    aliases = _import_aliases(tree)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _real_threshold_calls(node, aliases)
    }


def _locally_source_reading_function_names(
    tree: ast.Module, aliases: dict[str, str] | None = None
) -> set[str]:
    """Names of functions DEFINED IN THIS TEST FILE whose own body reads the real committed
    notebook or ``helpers.py`` (``_reads_real_committed_source`` on the function's own source
    segment) -- a module-level helper like recipes 42's ``_notebook_cell_source`` or 44's
    ``_notebook_code_source``, which several recipes factor the read into so more than one test
    can reuse it. Calling such a function taints the result wherever it is called from, not only
    from inside its own definition -- the fix for recipes 42 and 44, whose pin a reviewer found
    this check previously missed entirely because the read lived outside the one test
    function's own segment."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if _reads_real_committed_source(node, aliases):
                names.add(node.name)
    return names


def _tainted_names_in_function(
    func: ast.FunctionDef,
    taint_producing_names: set[str],
    aliases: dict[str, str] | None = None,
) -> set[str]:
    """Fixed-point taint set, local to one test function: a name is tainted if the statement
    assigning it (a) itself reads the real committed source (``_reads_real_committed_source`` on
    that one assignment's value -- the inline case: recipes 38, 39, 41, 43, 45, the template),
    (b) calls a function named in ``taint_producing_names`` (a source-reading helper defined
    anywhere in this file, or a ``helpers.py`` wrapper that itself makes the real selection call
    -- recipes 28, 42, 44), or (c) its value expression references an already-tainted name
    anywhere, including as a call argument (plain data-flow propagation -- recipe 42's
    ``_call_keyword_value(source, ...)``, whose own definition never mentions
    ``notebook.ipynb`` at all, but whose result still structurally depends on it because its
    argument, ``source``, does). The binding of ``with open(<committed file>) as f`` is the same
    read in statement form, so ``f`` is tainted by the same rules and ``f.read()`` then carries
    the taint on by (c). Scoped to one function at a time (never a whole-file flat
    namespace): a name is only ever compared against taint computed within the SAME function,
    so an unrelated function's own local variable sharing a common name (``source``, ``cell``)
    can never borrow another function's taint."""
    tainted: set[str] = set()

    bindings = _function_bindings(func)

    # names that hold a COPY under pytest's scratch directory (the fixture parameter itself, and
    # anything assigned from it): a read of those is a read of a test-made copy, not of the
    # committed artefact
    scratch = set(_SCRATCH_DIR_NAMES)  # the fixture parameter (or any use of its name)
    scratch |= _copy_destinations(func, aliases)  # ``shutil.copy(src, dst)`` as a statement
    grew = True
    while grew:
        grew = False
        for name, values in bindings.items():
            if name not in scratch and any(
                v is not None and (scratch & _ast_names(v) or _makes_scratch(v, aliases))
                for v in values
            ):
                scratch.add(name)
                grew = True

    # a test that WRITES the committed file (``(RECIPE / "notebook.ipynb").write_text(...)``, or an
    # ``open`` of it for writing) and then reads it back pins the text it typed: nothing it reads
    # is credited. A write through a name or in another function is not seen (accepted).
    for call in ast.walk(func):
        if not isinstance(call, ast.Call):
            continue
        callee = call.func
        if isinstance(callee, ast.Attribute) and callee.attr in {"write_text", "write_bytes"}:
            target: ast.AST = callee.value
        elif _is_open_call(call) and _opens_for_writing(call):
            target = call
        else:
            continue
        if (
            _mentions_artefact_file(target)
            and not scratch & _ast_names(target)
            and not _makes_scratch(target, aliases)
        ):
            return set()

    def _taints(value: ast.AST | None) -> bool:
        if value is None:  # bound by a form this cannot trace (``+=``, ``for``, unpacking, ``:=``)
            return False
        if (
            scratch & _ast_names(value)
            or _makes_scratch(value, aliases)
            or _rewrites_text(value, frozenset(tainted))
        ):
            return False
        calls_taint_producing = any(
            isinstance(n, ast.Call) and _call_func_name(n) in taint_producing_names
            for n in ast.walk(value)
        )
        return (
            _reads_real_committed_source(value, aliases)
            or calls_taint_producing
            or _wholly_tainted(value, frozenset(tainted))
        )

    # A name is tainted only if EVERY binding of it in the function is, and is traceable: ``source
    # = <read>`` followed by ``source = "<hand typed>"``, ``source += "<hand typed>"``, ``for source
    # in (...)``, ``source, _ = ...`` or ``(source := ...)`` leaves a name whose value at the
    # assert is not (only) the read. A value built from the read plus a hand-typed piece
    # (``source + "x"``, ``source or "x"``, a dict holding both) is not tainted either: the name
    # must be WHOLLY derived from the read.
    changed = True
    while changed:
        changed = False
        for name, values in bindings.items():
            if name not in tainted and all(_taints(v) for v in values):
                tainted.add(name)
                changed = True
    return tainted


def _function_bindings(func: ast.FunctionDef) -> dict[str, list[ast.AST | None]]:
    """Every way ``func`` binds a name: the assigned value for a plain ``name = value`` and the
    context expression for ``with <expr> as name`` (the two forms whose value can be traced), and
    ``None`` for every other binding of that name -- augmented or annotated assignment, a ``for``
    target, tuple unpacking, a walrus, ``del``, ``with ... as (a, b)``. A comprehension's own
    target is scoped to the comprehension and is handled by ``_taint_through_comprehension``."""
    bindings: dict[str, list[ast.AST | None]] = {}
    traced: set[int] = set()
    scoped: set[int] = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            bindings.setdefault(node.targets[0].id, []).append(node.value)
            traced.add(id(node.targets[0]))
        elif isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.optional_vars, ast.Name):
                    bindings.setdefault(item.optional_vars.id, []).append(item.context_expr)
                    traced.add(id(item.optional_vars))
        elif isinstance(node, ast.comprehension):
            scoped.update(id(n) for n in ast.walk(node.target))
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store | ast.Del)
            and id(node) not in traced
            and id(node) not in scoped
        ):
            bindings.setdefault(node.id, []).append(None)
    return bindings


class _Taint(frozenset):
    """The names traced to the committed source, plus -- per local name -- the hand-typed strings
    its bindings embed (``embedded``): ``padded = source.replace("a", "min_coverage")`` is still a
    name derived from the read, but it carries the needle ``min_coverage`` that no read put there,
    so ``"min_coverage" in padded`` holds whatever the notebook says (see ``_embeds_text``).

    A plain ``frozenset`` of names works everywhere a ``_Taint`` does and simply embeds nothing.
    The converse is the invariant to keep: every function that derives a new taint set from a
    ``_Taint`` must re-wrap it (``_taint_through_comprehension`` does), because a plain set
    silently loses ``embedded`` -- and losing it can only CREDIT more, never less."""

    embedded: dict[str, frozenset[str]]

    def __new__(cls, names=(), embedded=None):
        obj = super().__new__(cls, names)
        obj.embedded = {n: frozenset(t) for n, t in (embedded or {}).items()}
        return obj


def _embedded_of(tainted: frozenset[str]) -> dict[str, frozenset[str]]:
    return getattr(tainted, "embedded", {})


def _folded_text(node: ast.AST) -> str | None:
    """The text of a ``str``/``bytes`` constant, or of a ``+`` chain made only of such constants
    (``"min" + "_coverage"``); ``None`` for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str | bytes):
        return node.value if isinstance(node.value, str) else node.value.decode("utf-8", "replace")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _folded_text(node.left), _folded_text(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _typed_strings(node: ast.AST) -> set[str]:
    """Every hand-typed ``str``/``bytes`` constant inside ``node`` (f-string text included), and
    the text a ``+`` of adjacent literals spells (``"min" + "_coverage"`` types ``min_coverage``
    although no single constant contains it)."""
    found: set[str] = set()
    for n in ast.walk(node):
        text = _folded_text(n)
        if text is not None:
            found.add(text)
    return found


# Methods that put the values they are given INTO the container they are called on.
_CONTAINER_INSERT_METHODS = frozenset(
    {"append", "extend", "insert", "add", "update", "setdefault", "appendleft", "extendleft"}
)


def _in_place_contributions(func: ast.FunctionDef) -> dict[str, list[ast.AST]]:
    """name -> the expressions that are put INTO the container ``name`` after it was bound:
    arguments of ``name.append(...)`` / ``extend`` / ``insert`` / ``add`` / ``update`` /
    ``setdefault``, and the value (and key) of ``name[key] = value``. They are not bindings of
    ``name``, but what they hand-type is in ``name`` all the same."""
    contributions: dict[str, list[ast.AST]] = {}
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _CONTAINER_INSERT_METHODS
            and isinstance(node.func.value, ast.Name)
        ):
            contributions.setdefault(node.func.value.id, []).extend(
                [*node.args, *(k.value for k in node.keywords)]
            )
        elif isinstance(node, ast.Assign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    contributions.setdefault(target.value.id, []).extend([node.value, target.slice])
    return contributions


def _embedded_texts(func: ast.FunctionDef, tainted: set[str]) -> dict[str, frozenset[str]]:
    """For each local name (tainted or not), the hand-typed strings in any of its bindings or
    put into it in place (``_in_place_contributions``), followed transitively through the local
    names those expressions reference (so ``again = swapped`` carries what ``swapped =
    source.replace(..., "min_coverage")`` typed, and so does ``needle = "min_coverage"`` when it
    is then passed to ``.replace``). ``tainted`` is accepted for the callers' symmetry: every name
    is tracked, because hand-typed text flows through untainted names too."""
    bindings = _function_bindings(func)
    contributions = _in_place_contributions(func)
    names = set(bindings) | set(contributions) | set(tainted)
    embedded: dict[str, set[str]] = {name: set() for name in names}
    changed = True
    while changed:
        changed = False
        for name in names:
            for value in [*bindings.get(name, []), *contributions.get(name, [])]:
                if value is None:
                    continue
                found = _typed_strings(value)
                for ref in _ast_names(value):
                    found |= embedded.get(ref, set())
                if not found <= embedded[name]:
                    embedded[name] |= found
                    changed = True
    return {name: frozenset(texts) for name, texts in embedded.items()}


def _is_plain_open_with(node: ast.With) -> bool:
    """A ``with open(...) as f:`` (or ``path.open()``) block: it runs its body exactly once,
    unconditionally, so asserts inside it are as unconditional as the statement itself. Any other
    context manager is not assumed to behave that way -- ``pytest.raises(AssertionError)`` inverts
    the sense of every assert inside it, and ``contextlib.suppress`` can swallow them."""
    return all(
        isinstance(item.context_expr, ast.Call)
        and (
            (isinstance(item.context_expr.func, ast.Name) and item.context_expr.func.id == "open")
            or (
                isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "open"
            )
        )
        for item in node.items
    )


def _unconditional_asserts(body: list[ast.stmt]) -> list[ast.Assert]:
    """The ``assert`` statements in ``body`` that always run when the test does: direct
    statements of the function, those inside a plain ``with open(...)`` block, and those in the
    body of a ``for`` loop over a visibly non-empty literal tuple/list/set (no ``break``,
    ``continue`` or ``return`` in it), which runs for every element. Collection STOPS at the first
    statement that can end the test early (a ``return``, a ``raise`` or a ``pytest.skip`` /
    ``xfail`` / ``exit`` / ``fail`` call, including one under an ``if``): an assert after it may
    never run. An assert under an ``if``, any other loop, a ``try``, a nested function, or ``with
    pytest.raises(...)`` is NOT included, because its effective truth sense depends on a context
    this check cannot see: ``if cond: assert "x" in source`` pins nothing when ``cond`` is false,
    and ``with pytest.raises(AssertionError): assert "x" in source`` claims the spelling is
    ABSENT. Not crediting those is the fail-closed direction (a loud refusal, never a silent
    pass). A test marked ``skip``/``skipif``/``xfail`` is not considered at all
    (``_test_function_defs``)."""
    return _collect_unconditional_asserts(body)[0]


_LEAVING_CALL_NAMES = frozenset({"skip", "xfail", "exit", "fail", "importorskip", "_exit"})


def _walk_same_scope(node: ast.AST):
    """``ast.walk`` that does not descend into nested functions, lambdas or classes (a ``return``
    in a nested helper does not end the test)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for child in ast.iter_child_nodes(current):
            if not isinstance(
                child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef
            ):
                stack.append(child)


def _may_leave_the_test(stmt: ast.stmt, *, loop_exits: bool = False) -> bool:
    """True if running ``stmt`` can end the test (or, with ``loop_exits``, skip the rest of the
    enclosing loop body) before the statements after it run: a ``return``, a ``raise``, or a
    call to ``pytest.skip`` / ``xfail`` / ``exit`` / ``fail`` (anywhere inside it, including under
    an ``if``). An assert placed after such a statement may never run."""
    for node in _walk_same_scope(stmt):
        if isinstance(node, ast.Return | ast.Raise):
            return True
        if loop_exits and isinstance(node, ast.Break | ast.Continue):
            return True
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in _LEAVING_CALL_NAMES:
                return True
    return False


def _collect_unconditional_asserts(body: list[ast.stmt]) -> tuple[list[ast.Assert], bool]:
    """``(asserts, completed)``: the asserts that always run, and whether control provably reaches
    the end of ``body`` (``False`` once a statement that can leave the test was met, after which
    nothing further is credited). Direct statements count; a plain ``with open(...)`` block counts
    through its body; a ``for`` loop over a visibly non-empty literal display counts through its
    body when the body cannot ``break``/``continue``/``return`` (it then runs once per element)."""
    found: list[ast.Assert] = []
    for stmt in body:
        if isinstance(stmt, ast.Assert):
            found.append(stmt)
        elif isinstance(stmt, ast.With) and _is_plain_open_with(stmt):
            inner, completed = _collect_unconditional_asserts(stmt.body)
            found.extend(inner)
            if not completed:
                return found, False
        elif (
            isinstance(stmt, ast.For)
            and _provably_nonempty(stmt.iter, frozenset())
            and not any(_may_leave_the_test(s, loop_exits=True) for s in stmt.body)
            and not stmt.orelse
        ):
            found.extend(_collect_unconditional_asserts(stmt.body)[0])
        elif _may_leave_the_test(stmt):
            return found, False
    return found, True


# --------------------------------------------------------------------------------------------
# effective truth sense (#276): what does an assert CLAIM about a spelling?
#
# The earlier walk yielded every ``ast.Compare`` under an assert and tracked only an enclosing
# ``not`` and the comparison's own ``not in``/``!=``/``is not``, so negation expressed as a VALUE
# (``("x" in source) is False``), by a COUNT (``source.count("x") == 0``), by CONTEXT (an
# ``IfExp`` branch) or inside a comprehension (``len([m for m in ... if "x" in m]) == 0``) was
# invisible, and a spelling asserted ABSENT was credited as PRESENT. A blacklist of those
# spellings is the wrong shape (CONTRIBUTING.md section 6's list was evaded five times), so
# this derives the property instead: ``_entailed_spellings(expr, truth, ...)`` answers "if
# ``expr`` evaluates to ``truth``, which spellings must be present in the committed source?",
# recursing structurally so every layer (``not``, ``and``/``or``, ``if``-expressions, ``is False``,
# numeric thresholds on counts, ``all``/``any``/``len`` over comprehensions) contributes its own
# sign. Anything the recursion does not understand entails NOTHING, so an unrecognised idiom is
# refused loudly rather than credited silently.
# --------------------------------------------------------------------------------------------

_NUMERIC_COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_MIRRORED = {
    ast.Eq: ast.Eq,
    ast.NotEq: ast.NotEq,
    ast.Lt: ast.Gt,
    ast.LtE: ast.GtE,
    ast.Gt: ast.Lt,
    ast.GtE: ast.LtE,
}
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp)


def _literal_text(node: ast.AST) -> set[str] | None:
    """The literal text a hand-written needle expression stands for: a ``str``/``bytes``
    constant, the constant parts of an f-string, or the literal parts of a ``+`` / ``%`` join of
    those. ``None`` when ``node`` contributes no literal text at all (a name, a call...)."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return {node.value}
        if isinstance(node.value, bytes):
            return {node.value.decode("utf-8", "replace")}
        return None
    if isinstance(node, ast.JoinedStr):
        parts = {
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        }
        return parts or None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Mod):
        pieces = [p for p in (_literal_text(node.left), _literal_text(node.right)) if p]
        return set().union(*pieces) if pieces else None
    return None


def _truth_literal(literal: ast.AST, value: ast.AST) -> bool | None:
    """If ``literal`` is a ``True``/``False`` constant (or ``1``/``0`` standing opposite a
    boolean-valued expression), the truth value it names; else ``None``."""
    if not isinstance(literal, ast.Constant):
        return None
    if type(literal.value) is bool:
        return literal.value
    if (
        type(literal.value) is int
        and literal.value in (0, 1)
        and isinstance(value, ast.Compare | ast.BoolOp | ast.UnaryOp)
    ):
        return bool(literal.value)
    return None


def _taint_through_comprehension(comp: ast.expr, tainted: frozenset[str]) -> frozenset[str]:
    """``tainted`` as seen INSIDE the comprehension: each generator's target names are tainted when
    the iterable it ranges over is wholly tainted (``for s in sources`` with ``sources`` tainted
    is what lets ``all("min_coverage" in s for s in sources)`` be traced to the real committed
    source) and are SHADOWED -- removed from the set -- when it is not, so ``any("x" in source for
    source in ["x"])`` does not borrow the outer ``source``'s taint, and neither does an iterable
    that mixes the real read with a hand-typed copy of the needle."""
    out = set(tainted)
    embedded = dict(_embedded_of(tainted))
    for gen in comp.generators:
        targets = _ast_names(gen.target)
        # a target carries whatever hand-typed text the iterable it ranges over carries
        carried = _typed_strings(gen.iter)
        for ref in _ast_names(gen.iter):
            carried |= embedded.get(ref, frozenset())
        for name in targets:
            embedded[name] = frozenset(carried)
        if _wholly_tainted(gen.iter, frozenset(out)):
            out |= targets
        else:
            out -= targets
    return _Taint(out, embedded)


def _wholly_tainted(node: ast.AST, tainted: frozenset[str]) -> bool:
    """True if EVERY value ``node`` can produce comes from tainted data, not merely if it
    mentions a tainted name somewhere: a display is wholly tainted only if each element is, a
    ``+`` or ``or`` only if each operand is, a hand-typed literal never is. Calls, subscripts and
    attributes are wholly tainted when they reference a tainted name (``notebook["cells"]``,
    ``"".join(cell["source"])``): data flowing out of the read stays tainted."""
    if isinstance(node, ast.Constant | ast.JoinedStr) or _rewrites_text(node, tainted):
        return False
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return bool(node.elts) and all(
            _wholly_tainted(e.value if isinstance(e, ast.Starred) else e, tainted)
            for e in node.elts
        )
    if isinstance(node, ast.Dict):
        return bool(node.values) and all(_wholly_tainted(v, tainted) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _wholly_tainted(node.left, tainted) and _wholly_tainted(node.right, tainted)
    if isinstance(node, ast.BoolOp):
        return all(_wholly_tainted(v, tainted) for v in node.values)
    if isinstance(node, ast.IfExp):
        return _wholly_tainted(node.body, tainted) and _wholly_tainted(node.orelse, tainted)
    return bool(tainted & _ast_names(node))


def _embeds_text(node: ast.AST, texts: set[str], tainted: frozenset[str]) -> bool:
    """True if a hand-typed string inside ``node`` contains one of ``texts`` -- the needle was
    smuggled into the value it is compared with (``kws.get("objective", "min_coverage") ==
    "min_coverage"``, ``source.replace("a", "min_coverage")``), so the comparison holds whatever
    the committed source says; so does a needle spelled as a ``+`` of adjacent literals
    (``"min" + "_coverage"``). A NAME counts for the hand-typed strings its own bindings embed, and
    for what is put into it in place by ``.append(...)`` / ``name[k] = ...`` (``tainted.embedded``),
    so the same smuggling through an intermediate variable (``swapped = source.replace("a",
    "min_coverage")`` then ``"min_coverage" in swapped``) is seen too, not only when it is
    spelled inline in the compared expression.

    NOT seen (kept out of scope on purpose, listed in #320): a needle reaching the value through a
    module-level name, a function parameter, a call result (``"".join(["min", "_coverage"])``), an
    f-string split around a placeholder, or any other computation of the text -- this is a check
    on what is TYPED in the function, not a data-flow proof that the needle came from the read."""
    embedded = _embedded_of(tainted)
    if any(t in typed for typed in _typed_strings(node) for t in texts):
        return True
    return any(
        isinstance(n, ast.Name)
        and any(t in typed for typed in embedded.get(n.id, ()) for t in texts)
        for n in ast.walk(node)
    )


def _credible_source_operand(node: ast.AST, texts: set[str], tainted: frozenset[str]) -> bool:
    """The operand a needle is compared against really is the committed source (wholly tainted)
    and does not itself contain the needle as a hand-typed string, inline or through a name."""
    return _wholly_tainted(node, tainted) and not _embeds_text(node, texts, tainted)


def _provably_nonempty(iterable: ast.expr, nonempty: frozenset[str]) -> bool:
    if isinstance(iterable, ast.List | ast.Tuple | ast.Set):
        return bool(iterable.elts) and not any(isinstance(e, ast.Starred) for e in iterable.elts)
    return isinstance(iterable, ast.Name) and iterable.id in nonempty


_CONTAINER_VALUES = (
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
)


def _name_bindings(func: ast.FunctionDef, name: str) -> list[ast.AST | None]:
    """Every binding of ``name`` in ``func``: the assigned value for a plain ``name = value``, and
    ``None`` for any other way of (re)binding or deleting it (augmented assignment, ``for``
    target, tuple unpacking, ``with ... as``, walrus, ``del``, comprehension target)."""
    values: list[ast.AST | None] = []
    plain_targets: set[int] = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            values.append(node.value)
            plain_targets.add(id(node.targets[0]))
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Name)
            and node.id == name
            and isinstance(node.ctx, ast.Store | ast.Del)
            and id(node) not in plain_targets
        ):
            values.append(None)
    return values


def _mutated_in_place(func: ast.FunctionDef, name: str) -> bool:
    """``name.<anything>(...)`` (``clear``, ``pop``, ``remove``...) or a subscript store/delete on
    ``name``: the container may not hold what it was bound to."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
        ):
            return True
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store | ast.Del)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
        ):
            return True
    return False


def _asserted_nonempty_names(func: ast.FunctionDef) -> frozenset[str]:
    """Names this function establishes as non-empty before an ``all(...)`` over them can mean
    anything (``all`` over an empty iterable is vacuously true and pins nothing). A name counts
    only if it is bound ONCE in the function and never mutated in place (so a later
    ``sources = []`` or ``sources.clear()`` cannot empty it behind the evidence), and then by:

    * being bound to a non-empty literal list/tuple/set; or
    * an unconditional ``assert len(name) > 0`` / ``>= 1`` / ``!= 0`` / ``== n`` (``n > 0``); or
    * an unconditional bare ``assert name`` when the single binding is a container display or
      list/set/dict comprehension -- NOT a generator, which is always truthy."""
    candidates: dict[str, str] = {}  # name -> how it was shown non-empty
    asserted_len: set[str] = set()
    asserted_bare: set[str] = set()
    for assert_ in _unconditional_asserts(func.body):
        conjuncts = (
            assert_.test.values
            if isinstance(assert_.test, ast.BoolOp) and isinstance(assert_.test.op, ast.And)
            else [assert_.test]
        )
        for conjunct in conjuncts:
            if isinstance(conjunct, ast.Name):
                asserted_bare.add(conjunct.id)
            elif (
                isinstance(conjunct, ast.Compare)
                and len(conjunct.ops) == 1
                and isinstance(conjunct.left, ast.Call)
                and isinstance(conjunct.left.func, ast.Name)
                and conjunct.left.func.id == "len"
                and len(conjunct.left.args) == 1
                and isinstance(conjunct.left.args[0], ast.Name)
                and isinstance(conjunct.comparators[0], ast.Constant)
                and type(conjunct.comparators[0].value) in (int, float)
                and type(conjunct.ops[0]) in _NUMERIC_COMPARE
                and not _NUMERIC_COMPARE[type(conjunct.ops[0])](0, conjunct.comparators[0].value)
            ):
                asserted_len.add(conjunct.left.args[0].id)
    assigned = {
        n.targets[0].id
        for n in ast.walk(func)
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
    }
    for name in assigned | asserted_len:
        if _mutated_in_place(func, name):
            continue
        bindings = _name_bindings(func, name)
        if len(bindings) > 1:
            continue
        value = bindings[0] if bindings else None
        if value is not None and _provably_nonempty(value, frozenset()):
            candidates[name] = "literal"
        elif name in asserted_len:
            candidates[name] = "len"
        elif name in asserted_bare and isinstance(value, _CONTAINER_VALUES):
            candidates[name] = "truthy container"
    return frozenset(candidates)


def _exists_entailed(
    comp: ast.expr,
    elt_truth: bool | None,
    tainted: frozenset[str],
    nonempty: frozenset[str],
) -> set[str]:
    """Spellings entailed by "some element of ``comp`` survives its filters (and, when
    ``elt_truth`` is not ``None``, its element expression evaluates to ``elt_truth``)": the
    conjunction of every filter being true for that one element, with the comprehension variable
    tainted when it ranges over tainted data."""
    inner = _taint_through_comprehension(comp, tainted)
    out: set[str] = set()
    for gen in comp.generators:
        for condition in gen.ifs:
            out |= _entailed_spellings(condition, True, inner, nonempty)
    if elt_truth is not None:
        out |= _entailed_spellings(comp.elt, elt_truth, inner, nonempty)
    return out


def _forall_entailed(
    comp: ast.expr, elt_truth: bool, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str]:
    """Spellings entailed by "EVERY element of ``comp`` evaluates to ``elt_truth``". Only
    meaningful when there is at least one element and no filter narrows which ones count, so a
    filtered comprehension, or an iterable not provably non-empty, entails nothing."""
    if any(gen.ifs for gen in comp.generators):
        return set()
    if not all(_provably_nonempty(gen.iter, nonempty) for gen in comp.generators):
        return set()
    inner = _taint_through_comprehension(comp, tainted)
    return _entailed_spellings(comp.elt, elt_truth, inner, nonempty)


def _quantity_spellings(
    node: ast.AST, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str] | None:
    """``None`` unless ``node`` is a COUNT of something in the committed source:
    ``<tainted>.count(<needle>)``, ``len(<comprehension>)``, ``len(<tainted>)`` or
    ``sum(1 for ...)``. When it is, the spellings whose presence a count greater than zero
    entails (the needle of a ``.count``, the filters of a comprehension)."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "count" and node.args:
        if tainted & _ast_names(func.value):
            needle = _literal_text(node.args[0]) or set()
            if not _credible_source_operand(func.value, needle, tainted):
                return set()  # still a count, but of something that is not the committed source
            return needle
        return None
    if isinstance(func, ast.Name) and len(node.args) == 1:
        arg = node.args[0]
        if func.id == "len":
            if isinstance(arg, _COMPREHENSIONS):
                return _exists_entailed(arg, None, tainted, nonempty)
            return set() if tainted & _ast_names(arg) else None
        if func.id == "sum" and isinstance(arg, _COMPREHENSIONS):
            # ``sum(1 for ...)`` counts the elements that survive the filters; ``sum(<bool or
            # count> for ...)`` is positive only if some element's term is true / positive
            counts_elements = isinstance(arg.elt, ast.Constant) and arg.elt.value == 1
            return _exists_entailed(arg, None if counts_elements else True, tainted, nonempty)
    return None


def _combine(parts: list[set[str]], all_must_hold: bool) -> set[str]:
    """What a conjunction (``all_must_hold``: every part is known true, so every part's
    entailments apply) or a disjunction (some part is true, we do not know which, so only what
    EVERY part entails applies) entails."""
    if not parts:
        return set()
    if all_must_hold:
        return set().union(*parts)
    return set.intersection(*parts)


def _entailed_spellings(
    expr: ast.expr, truth: bool, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str]:
    """If ``expr`` evaluates to ``truth``, the spellings that must therefore be PRESENT in the
    committed source. The effective truth sense is carried down the tree: ``not`` flips it,
    ``and``/``or`` apply it to each operand but combine differently (a true ``and`` and a false
    ``or`` know every operand; a false ``and`` and a true ``or`` only know what all operands
    share), an ``if``-expression only entails what BOTH branches do, a comparison against a
    ``True``/``False`` literal re-targets the other operand with the sign that literal implies,
    and a count compared with a number entails presence only when the comparison excludes
    zero. Anything not recognised entails nothing."""
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        return _entailed_spellings(expr.operand, not truth, tainted, nonempty)
    if isinstance(expr, ast.BoolOp):
        parts = [_entailed_spellings(v, truth, tainted, nonempty) for v in expr.values]
        return _combine(parts, isinstance(expr.op, ast.And) == truth)
    if isinstance(expr, ast.IfExp):
        branches = [
            _entailed_spellings(expr.body, truth, tainted, nonempty),
            _entailed_spellings(expr.orelse, truth, tainted, nonempty),
        ]
        return _combine(branches, all_must_hold=False)
    if isinstance(expr, ast.Compare):
        return _compare_entailed(expr, truth, tainted, nonempty)
    if isinstance(expr, ast.Call):
        return _call_entailed(expr, truth, tainted, nonempty)
    return set()


def _call_entailed(
    call: ast.Call, truth: bool, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str]:
    quantity = _quantity_spellings(call, tainted, nonempty)
    if quantity is not None:
        # a bare count used as a condition means "count != 0"
        return quantity if truth else set()
    if not (isinstance(call.func, ast.Name) and len(call.args) == 1):
        return set()
    name, arg = call.func.id, call.args[0]
    if name == "bool":
        return _entailed_spellings(arg, truth, tainted, nonempty)
    if name not in ("all", "any"):
        return set()
    if isinstance(arg, _COMPREHENSIONS):
        if (name == "any") == truth:  # some element satisfies it
            return _exists_entailed(arg, name == "any", tainted, nonempty)
        return _forall_entailed(arg, name == "all", tainted, nonempty)
    if (
        isinstance(arg, ast.List | ast.Tuple | ast.Set)
        and arg.elts
        and not any(isinstance(e, ast.Starred) for e in arg.elts)
    ):
        parts = [_entailed_spellings(e, truth, tainted, nonempty) for e in arg.elts]
        return _combine(parts, (name == "all") == truth)
    return set()


def _compare_entailed(
    compare: ast.Compare, truth: bool, tainted: frozenset[str], nonempty: frozenset[str]
) -> set[str]:
    if len(compare.ops) > 1:  # a < b < c is (a < b) and (b < c)
        operands = [compare.left, *compare.comparators]
        parts = [
            _compare_entailed(
                ast.Compare(left=operands[i], ops=[op], comparators=[operands[i + 1]]),
                truth,
                tainted,
                nonempty,
            )
            for i, op in enumerate(compare.ops)
        ]
        return _combine(parts, all_must_hold=truth)
    left, op, right = compare.left, compare.ops[0], compare.comparators[0]
    op_type = type(op)

    # (a) a boolean-valued operand compared with a True/False literal: ``(x in s) is False``
    if isinstance(op, ast.Eq | ast.NotEq | ast.Is | ast.IsNot):
        for value, literal in ((left, right), (right, left)):
            wanted = _truth_literal(literal, value)
            if wanted is not None:
                positive = isinstance(op, ast.Eq | ast.Is)
                inner = wanted if positive == truth else (not wanted)
                return _entailed_spellings(value, inner, tainted, nonempty)

    # (b) a count compared with a number: presence is entailed only if the claim excludes zero
    for quantity_side, number_side, mirrored in ((left, right, False), (right, left, True)):
        quantity = _quantity_spellings(quantity_side, tainted, nonempty)
        if quantity is None:
            continue
        cmp_type = _MIRRORED.get(op_type) if mirrored else op_type
        if (
            cmp_type not in _NUMERIC_COMPARE
            or not isinstance(number_side, ast.Constant)
            or type(number_side.value) not in (int, float)
        ):
            return set()
        zero_is_consistent = _NUMERIC_COMPARE[cmp_type](0, number_side.value) == truth
        return set() if zero_is_consistent else quantity

    # (c) membership / equality: credited only when the comparison effectively says "equal" or
    # "contained", and one side is a hand-written needle while the other is derived from the
    # committed source
    if not isinstance(op, ast.In | ast.NotIn | ast.Eq | ast.NotEq | ast.Is | ast.IsNot):
        return set()
    if isinstance(op, ast.In | ast.Eq | ast.Is) != truth:
        return set()
    if isinstance(op, ast.In | ast.NotIn):
        needle = _literal_text(left)
        if needle and _credible_source_operand(right, needle, tainted):
            return needle
        return set()
    found: set[str] = set()
    for value, literal in ((left, right), (right, left)):
        text = _literal_text(literal)
        if text and _literal_text(value) is None and _credible_source_operand(value, text, tainted):
            found |= text
    return found


def _locally_defined_function_names(tree: ast.AST) -> set[str]:
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _extraction_helper_names(tree: ast.AST) -> set[str]:
    """Local helpers whose literal strings cannot supply an objective fallback.

    Refuse every definition of a name if any definition holds a whole-token objective
    spelling, including a docstring, default or unreachable branch. This conservative
    check does not try to prove which branch runs or follow computed/global strings.
    A direct assertion remains available for helpers outside this extraction shape.
    """
    refused: set[str] = set()
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if any(
                _objective_token_present(spelling, node.value)
                for spelling in ALL_OBJECTIVE_SPELLINGS
            ):
                refused.add(function.name)
                break
    return _locally_defined_function_names(tree) - refused


def _extraction_checked(name: str, func: ast.FunctionDef, after: int = -1) -> bool:
    """True if ``func.body`` has, as a top-level statement later than ``func.body[after]``, the
    bare statement ``assert <name> is not None`` (either operand order: ``name is not None`` or
    ``None is not name``). One side must be exactly the Name ``name`` and the other exactly the
    constant ``None``; a wrapped operand such as ``(a or b) is not None``, ``(a, b) is not
    None``, ``str(a) is not None`` or ``[a] is not None`` is not the idiom (the last three are
    always true, the first holds whichever name matched). Not merely referenced in some assert,
    which an unrelated ``not in`` comparison or a disconnected ``assert len(x) > 0`` would
    satisfy. An assert nested under ``if``, ``try``, a loop or ``with`` does not count (it may
    not run), and neither does one after a statement that can end the test (``return``,
    ``raise``, ``pytest.skip``/``xfail``/``exit``/``fail``, including under an ``if``): only an
    assert in ``_unconditional_asserts(func.body)`` is credited."""
    always_runs = {id(assertion) for assertion in _unconditional_asserts(func.body)}
    for node in func.body[after + 1 :]:
        if id(node) not in always_runs:
            continue
        if not (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)):
            continue
        test = node.test
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.IsNot):
            continue
        left, right = test.left, test.comparators[0]
        for value, none in ((left, right), (right, left)):
            if (
                isinstance(value, ast.Name)
                and value.id == name
                and isinstance(none, ast.Constant)
                and none.value is None
            ):
                return True
    return False


def _binding_count(name: str, func: ast.FunctionDef) -> int:
    """How many times ``name`` is bound anywhere in ``func`` (nested scopes included, which
    only makes the count higher and the check stricter): every Name in a Store/Del context
    (assignment, augmented and annotated assignment, tuple unpacking, ``:=``, ``for`` targets,
    ``with ... as``, comprehension targets), ``except ... as``, nested ``def``/``class`` names,
    import aliases, ``match`` captures and parameters."""
    count = 0
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and node.id == name:
            count += isinstance(node.ctx, ast.Store | ast.Del)
        elif isinstance(node, ast.ExceptHandler):
            count += node.name == name
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            count += node is not func and node.name == name
        elif isinstance(node, ast.alias):
            count += (node.asname or node.name.split(".")[0]) == name
        elif isinstance(node, ast.MatchAs | ast.MatchStar):
            count += node.name == name
        elif isinstance(node, ast.MatchMapping):
            count += node.rest == name
        elif isinstance(node, ast.arg):
            count += node.arg == name
    return count


def _extraction_literals(call: ast.Call, tainted: set[str]) -> list[str] | None:
    """The string literals an extracting call names, or ``None`` when the call is not the
    credited shape: the first positional argument must be a tainted Name (the source), every
    other argument a plain positional string ``Constant``, and there must be no keyword
    argument at all (not even ``**kwargs``). Anything else, such as a literal first argument, a
    Name, a concatenation, an f-string, a nested call or a keyword, could carry a second
    objective spelling this check cannot see."""
    if call.keywords or not call.args:
        return None
    first = call.args[0]
    if not (isinstance(first, ast.Name) and first.id in tainted):
        return None
    literals: list[str] = []
    for extra in call.args[1:]:
        if not (isinstance(extra, ast.Constant) and isinstance(extra.value, str)):
            return None
        literals.append(extra.value)
    return literals


def _extraction_spelling(
    statement: ast.stmt,
    index: int,
    func: ast.FunctionDef,
    tainted: set[str],
    locally_defined: set[str],
) -> str | None:
    """The one objective spelling ``func.body[index]`` extracts and ties to an
    ``assert <name> is not None``, or ``None`` when the statement is not credited. See
    ``_spellings_pinned_by_assertions`` for the three rules."""
    if not (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id in tainted
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id in locally_defined
    ):
        return None
    target = statement.targets[0].id
    # Rule 1: bound exactly once, by this top-level statement, checked by a later top-level assert
    # that always runs: nothing before the assignment or between it and the assert may end the
    # test (a ``return``, ``raise`` or ``pytest.skip``, also under an ``if``).
    if any(_may_leave_the_test(earlier) for earlier in func.body[:index]):
        return None
    if _binding_count(target, func) != 1 or not _extraction_checked(target, func, index):
        return None
    # Rule 2: the call's shape.
    literals = _extraction_literals(statement.value, tainted)
    if literals is None:
        return None
    # Rule 3: the literals name exactly one objective spelling, by the matcher the pin check uses.
    named = {
        spelling
        for spelling in ALL_OBJECTIVE_SPELLINGS
        if any(_objective_token_present(spelling, literal) for literal in literals)
    }
    return next(iter(named)) if len(named) == 1 else None


def _spellings_pinned_by_assertions(
    func: ast.FunctionDef, tainted: set[str], locally_defined: set[str]
) -> set[str]:
    """Objective spellings this one function's assertions pin, by two routes:

    * **Direct.** An unconditional ``assert`` whose EFFECTIVE CLAIM, derived by
      ``_entailed_spellings`` (the truth sense carried through ``not``, ``and``/``or``,
      ``is False``, ``if``-expressions, count thresholds and ``all``/``any``/``len`` over
      comprehensions), is that a spelling is present in a value traced to the real committed
      source. Each comparison is gated on its OWN operands -- the spelling must be a
      hand-written needle compared against a tainted operand -- so an unrelated tainted
      reference elsewhere in the same ``assert`` cannot license a hand-typed literal comparison
      that never touches it. This is what a reviewer's ``.count('objective="f1"') == 2`` (41,
      44), ``objective == "f1"`` (42), and ``f"min_coverage={MIN_COVERAGE}"`` f-string (46) all
      need, and what the mutation findings in #244 and #276 exist to close: crediting the wrong
      side of a negative claim, and crediting a spelling that merely co-occurs with taint.
    * **Extraction.** ``name = _helper(source, "lit", ...)`` through a LOCALLY DEFINED function
      (``locally_defined`` -- never a built-in string/list method such as ``.replace(...)``,
      which would let a mutation-proof's own ``source.replace(pinned, "target_accuracy=1.0")``
      donate its literal as if it were a real pin), followed by ``assert name is not None``
      (either operand order; recipe 42's ``min_coverage = _call_keyword_value(source,
      "select_confidence_threshold", "min_coverage")``). The keyword being pinned is never
      re-stated as a literal in the later assert, so the direct route alone misses it. The
      route fails closed: an extraction is credited only when ALL of these hold.

      1. ``name`` is bound exactly once in the test function (every kind of binding counts),
         by an unconditional top-level statement of its body, and the ``assert name is not
         None`` is a later top-level statement. An ``if``/``try`` fallback into the same name,
         an assignment under ``if False:``, a loop rebinding, or an assert placed before the
         assignment is therefore not credited.
      2. The first positional argument is a tainted Name (the source), every other argument is
         a plain positional string literal, and the call has no keyword argument at all.
      3. By ``_objective_token_present`` (the matcher ``_objective_pin_violations`` uses), the
         literals together name exactly ONE distinct objective spelling across every spelling
         of both threshold functions. Zero or several name nothing, so ``"f1"`` with
         ``"min_coverage"``, or ``"f1-gate"`` (which contains the token f1) with another
         spelling, is refused. Only that one spelling is credited, never the raw literals.

      The recipe-level caller supplies only ``_extraction_helper_names``: a local helper
      holding an objective token in a literal string is refused, even in a dead branch or
      docstring. This prevents a literal fallback inside the helper from donating a false
      pin. Computed strings and transitive calls are outside this bounded analysis."""
    pinned: set[str] = set()
    frozen_taint = _Taint(tainted, _embedded_texts(func, tainted))
    nonempty = _asserted_nonempty_names(func)

    for node in _unconditional_asserts(func.body):
        pinned |= _entailed_spellings(node.test, True, frozen_taint, nonempty)

    for index, statement in enumerate(func.body):
        spelling = _extraction_spelling(statement, index, func, tainted, locally_defined)
        if spelling is not None:
            pinned.add(spelling)

    return pinned


def _spellings_pinned_by_production_discrimination(
    func: ast.FunctionDef, production_wrapper_names: set[str], aliases: dict[str, str]
) -> set[str]:
    """Recipe 28's shape, which fits neither route in ``_spellings_pinned_by_assertions``: no
    source text is read at all, and the real call is made inline
    (``helpers.select_margin_threshold(safe, margin)``), never bound to a name the taint tracer
    above can see at all. Pins an objective by tying the REAL production call's own result, via
    ``==``, to a LOCAL re-derivation computed with an explicit keyword -- valid only once a
    separate ``!=`` assert proves that re-derivation differs from a sibling computed with a
    DIFFERENT objective, so the equality could not hold under a keyword swap to that sibling's
    objective (recipe 28's own ``assert by_min_coverage != by_target_accuracy``, immediately
    followed by ``assert helpers.select_margin_threshold(safe, margin) == by_min_coverage``, is
    exactly this non-degeneracy-then-tie shape)."""
    re_derivations: dict[str, str] = {}
    for node in ast.walk(func):
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
        ):
            continue
        resolved = _resolved_call_name(node.value, aliases)
        if resolved is None:
            continue
        objective = _threshold_call_objective(node.value, resolved)
        if objective:
            re_derivations[node.targets[0].id] = objective

    unconditional = _unconditional_asserts(func.body)
    distinguished: set[str] = set()
    for node in unconditional:
        if not (
            isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.NotEq)
        ):
            continue
        left_objs = {re_derivations[n] for n in _ast_names(node.test.left) if n in re_derivations}
        right_objs = {
            re_derivations[n] for n in _ast_names(node.test.comparators[0]) if n in re_derivations
        }
        if left_objs and right_objs and left_objs != right_objs:
            distinguished |= left_objs | right_objs

    pinned: set[str] = set()
    for node in unconditional:
        if not (
            isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
        ):
            continue
        sides = (node.test.left, node.test.comparators[0])
        has_production_call = any(
            isinstance(n, ast.Call) and _call_func_name(n) in production_wrapper_names
            for side in sides
            for n in ast.walk(side)
        )
        if not has_production_call:
            continue
        for side in sides:
            for name in _ast_names(side):
                if name in re_derivations and re_derivations[name] in distinguished:
                    pinned.add(re_derivations[name])
    return pinned


def _ignored_by_conftest(directory: Path, path: Path) -> bool:
    """True if ``directory/conftest.py`` sets ``collect_ignore`` / ``collect_ignore_glob`` so that
    pytest skips ``path``. Anything but one plain literal list of strings per name (a ``.append``,
    ``+=``, annotation, tuple target, nested or repeated assignment) ignores everything (the
    fail-closed side). A ``pytest_ignore_collect`` hook is not read (accepted)."""
    conftest = directory / "conftest.py"
    if not conftest.is_file():
        return False
    try:
        tree = ast.parse(conftest.read_text("utf-8"))
    except SyntaxError:
        return False
    names = ("collect_ignore", "collect_ignore_glob")
    mentions = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in names]
    if not mentions:
        return False
    # Any binding other than ONE plain top-level ``collect_ignore = [<str literals>]`` per name
    # (``.append``, ``+=``, an annotation, a tuple target, a nested or repeated assignment, ``del``)
    # leaves a value this cannot read: ignore everything (the fail-closed side).
    plain: list[ast.Assign] = [
        stmt
        for stmt in tree.body
        if isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and stmt.targets[0].id in names
        and isinstance(stmt.value, ast.List | ast.Tuple)
        and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in stmt.value.elts)
    ]
    if len(plain) != len(mentions) or len({s.targets[0].id for s in plain}) != len(plain):
        return True
    for stmt in plain:
        value = stmt.value
        relative = path.relative_to(directory).as_posix() if path.is_relative_to(directory) else ""
        for element in value.elts:
            pattern = element.value
            if (
                relative == Path(pattern).as_posix()
                or relative.startswith(Path(pattern).as_posix().rstrip("/") + "/")
                or fnmatch.fnmatch(relative, pattern)
            ):
                return True
    return False


def _pytest_collected_files(tests_dir: Path) -> list[Path]:
    """The ``*.py`` files in ``tests_dir`` pytest's default ``python_files`` collects
    (``test_*.py`` and ``*_test.py``): a ``def test_*`` in ``conftest.py`` or a helper module is
    never run, so its asserts pin nothing (#320). The repo sets no ``python_files``."""
    return [
        p
        for p in tests_dir.glob("*.py")
        if (p.name.startswith("test_") or p.stem.endswith("_test"))
        and not _ignored_by_conftest(tests_dir, p)
        and not _ignored_by_conftest(tests_dir.parent, p)
    ]


def _pinned_objective_spellings(recipe_dir_: Path) -> set[str]:
    """Every objective spelling this recipe's ``tests/*.py`` pin, by any of the shapes this
    check recognises, pooled across every test function in every test file. Pooling recipe-wide
    rather than per-obligation is a deliberate scope simplification: every published recipe's
    own threshold calls use one objective per function consistently (no recipe mixes, say,
    ``min_coverage`` in one ``select_confidence_threshold`` call with ``target_accuracy`` in
    another), so there is no live case where pooling lets one call's pin stand in for a
    different call's missing one -- see the pull request body for how this was checked."""
    pinned: set[str] = set()
    tests_dir = recipe_dir_ / "tests"
    if not tests_dir.is_dir():
        return pinned
    production_wrapper_names = _production_wrapper_names(recipe_dir_ / "helpers.py")
    for path in sorted(_pytest_collected_files(tests_dir)):
        text = path.read_text("utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        aliases = _import_aliases(tree)
        module_aliases = _module_aliases(tree)
        taint_producing_names = (
            _locally_source_reading_function_names(tree, module_aliases) | production_wrapper_names
        )
        locally_defined = _extraction_helper_names(tree)
        for func in _test_function_defs(tree):
            tainted = _tainted_names_in_function(func, taint_producing_names, module_aliases)
            pinned |= _spellings_pinned_by_assertions(func, tainted, locally_defined)
            pinned |= _spellings_pinned_by_production_discrimination(
                func, production_wrapper_names, aliases
            )
    return pinned


def _objective_token_present(objective: str, needle: str) -> bool:
    """True if ``objective`` appears in ``needle`` as a whole token -- bounded by the start/end
    of the string or a non-identifier character on either side -- not merely as a substring.
    Bare ``objective in needle`` would credit ``"min_coverage"`` from a needle that happens to
    contain it inside a longer, unrelated identifier; no published recipe does this today, but
    the obligation match should not rely on that remaining true by accident, especially for a
    short spelling like ``"f1"``."""
    return re.search(rf"(?<!\w){re.escape(objective)}(?!\w)", needle) is not None


# --------------------------------------------------------------------------------------------
# regression tests for the threshold_objective_pin detection itself, each proving a property
# a recipe's own test suite cannot see: the pin detector's own correctness. All four were
# found by a reviewer's synthetic probes, each isolating one way an earlier draft of the
# detector could be fooled; each is reproduced here as a committed test, not only a hand-run
# probe, per the standing house rule that a fixed defect needs its own regression test.
# --------------------------------------------------------------------------------------------


def _single_test_function(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))


def test_a_credited_spelling_must_be_compared_against_a_tainted_operand():
    """A reviewer isolated the gap synthetically: an earlier version of this detector credited
    a spelling the moment ANY tainted name appeared ANYWHERE in the same ``assert`` statement,
    not specifically compared against it. ``assert len(source) > 0 and "min_coverage" in
    "<hand-typed literal>"`` has a tainted name (``source``) in its first half and the spelling
    in its second, but the two never touch: the ``in`` comparison's own two operands are a bare
    string constant and an unrelated hand-typed string, neither derived from ``source`` at all.
    That must NOT be credited. The positive control alongside it -- ``"min_coverage" in
    source`` -- must still be, so this also proves the fix does not merely refuse everything."""
    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    assert len(source) > 0 and "min_coverage" in "<hand-typed literal>"
"""
    )
    tainted = {"source"}
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "min_coverage" not in pinned, "credited a spelling never compared against taint"

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    assert len(source) > 0 and "min_coverage" in source
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "min_coverage" in pinned, "the positive control (genuinely compared) was not credited"


def test_polarity_through_not_is_tracked():
    """``assert not ("target_accuracy" in source)`` asserts the spelling is ABSENT -- a
    reviewer's synthetic probe found an earlier version of this detector had no handling for
    ``not`` at all, so it credited the spelling as PINNED regardless, exactly backwards and
    exactly the mistake the ``NotIn``/``NotEq`` exclusion exists to prevent one level up the
    tree. Double negation must flip back to positive: ``not ("target_accuracy" not in
    source)`` asserts the spelling IS present, so it must be credited the same as a bare ``in``
    would be."""
    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    assert not ("target_accuracy" in source)
"""
    )
    tainted = {"source"}
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "target_accuracy" not in pinned, "credited a spelling asserted ABSENT via not(x in y)"

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    assert not ("target_accuracy" not in source)
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "target_accuracy" in pinned, "double negation should read positive and be credited"


def test_the_extraction_route_requires_a_locally_defined_function_and_a_real_check():
    """Two findings, both from the same reviewer, about ``_spellings_pinned_by_assertions``'s
    extraction route:

    1. **Not any referencing assert.** An earlier version credited an extracted, tainted name
       the moment it was referenced in ANY assert -- satisfied by an unrelated ``not in`` check
       or a wholly disconnected ``assert len(x) > 0``, neither of which actually verifies the
       extraction succeeded. Only ``assert <name> is not None`` is trusted.
    2. **Not any tainted call.** A recipe's own mutation-proof code can legitimately build a
       tainted string via a built-in method (``source.replace(pinned, "target_accuracy=1.0")``)
       for the specific purpose of testing what a keyword swap *would* look like -- that literal
       must never be credited as a real pin. Restricting the route to calls through a LOCALLY
       DEFINED function (never a bare attribute/method call like ``.replace(``) closes this."""
    tainted = {"source", "extracted", "swapped"}

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    extracted = _call_keyword_value(source, "select_confidence_threshold", "min_coverage")
    assert "nope" not in extracted
    assert len(extracted) > 0
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined={"_call_keyword_value"})
    assert "min_coverage" not in pinned, "credited an extraction checked only by unrelated asserts"

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    swapped = source.replace("min_coverage=min_coverage", "target_accuracy=1.0")
    assert swapped != source
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined=set())
    assert "target_accuracy" not in pinned, "credited a literal built via a built-in method call"

    func = _single_test_function(
        """
def test_probe():
    source = read_the_real_notebook()
    extracted = _call_keyword_value(source, "select_confidence_threshold", "min_coverage")
    assert extracted is not None
"""
    )
    pinned = _spellings_pinned_by_assertions(func, tainted, locally_defined={"_call_keyword_value"})
    assert "min_coverage" in pinned, "the genuine extraction idiom was not credited"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # shapes the rule refuses
        (
            'a = _pull(source, "min_coverage")\n    b = _pull(source, "target_accuracy")\n'
            "    assert (a or b) is not None",
            set(),
        ),
        (
            'a = _pull(source, "min_coverage")\n    b = _pull(source, "target_accuracy")\n'
            "    assert (a, b) is not None",
            set(),
        ),
        ('a = _pull(source, "min_coverage")\n    assert str(a) is not None', set()),
        ('a = _pull(source, "min_coverage")\n    assert [a] is not None', set()),
        ('a = _pull(source, "min_coverage", OTHER)\n    assert a is not None', set()),
        ('a = _pull(source, "min_coverage", *OTHERS)\n    assert a is not None', set()),
        (
            'a = _pull(source, "min_coverage", "target" + "_accuracy")\n    assert a is not None',
            set(),
        ),
        ('a = _pull(source, "min_coverage", fallback=FALLBACK)\n    assert a is not None', set()),
        ('a = _pull(source, "min_coverage", **OTHERS)\n    assert a is not None', set()),
        (
            'a = _pull(source, "min_coverage", cell("precision_at_recall-notes"))\n'
            "    assert a is not None",
            set(),
        ),
        # rule 3: two spellings, whole-token matches
        (
            'a = _pull(source, "min_coverage", "target_accuracy")\n    assert a is not None',
            set(),
        ),
        ('a = _pull(source, "f1-gate", "min_coverage")\n    assert a is not None', set()),
        ('a = _pull(source, "f1", "min_coverage")\n    assert a is not None', set()),
        ('a = _pull(source, "min_coverage", "target_accuracy=")\n    assert a is not None', set()),
        (
            'a = _pull(source, "min_coverage", "select_confidence_threshold(target_accuracy")\n'
            "    assert a is not None",
            set(),
        ),
        ('a = _pull(source, "select_confidence_threshold")\n    assert a is not None', set()),
        # rule 2: keyword names and a literal first argument
        ('a = _pull(source, "min_coverage", target_accuracy="")\n    assert a is not None', set()),
        ('a = _pull("target_accuracy", "min_coverage")\n    assert a is not None', set()),
        # rule 1: one unconditional top-level binding, then a top-level assert
        (
            'a = _pull(source, "min_coverage")\n    if a is None:\n'
            '        a = _pull(source, "target_accuracy")\n    assert a is not None',
            set(),
        ),
        (
            'try:\n        a = _pull(source, "min_coverage")\n    except KeyError:\n'
            '        a = _pull(source, "target_accuracy")\n    assert a is not None',
            set(),
        ),
        ('if False:\n        a = _pull(source, "min_coverage")\n    assert a is not None', set()),
        (
            'a = _pull(source, "min_coverage")\n    for a in OTHERS:\n        pass\n'
            "    assert a is not None",
            set(),
        ),
        ('assert a is not None\n    a = _pull(source, "min_coverage")', set()),
        (
            'a = _pull(source, "min_coverage")\n    if True:\n        assert a is not None',
            set(),
        ),
        # rule 1: nothing before the assert may end the test
        (
            'a = _pull(source, "min_coverage")\n    return\n    assert a is not None',
            set(),
        ),
        (
            'a = _pull(source, "min_coverage")\n    pytest.skip("x")\n    assert a is not None',
            set(),
        ),
        (
            'return\n    a = _pull(source, "min_coverage")\n    assert a is not None',
            set(),
        ),
        (
            'a = _pull(source, "min_coverage")\n    if a is None:\n        raise KeyError\n'
            "    assert a is not None",
            set(),
        ),
        (
            'a = _pull(source, "min_coverage")\n    if a is None:\n        pytest.skip("x")\n'
            "    assert a is not None",
            set(),
        ),
        # credited: one spelling, either assert order
        (
            'a = _pull(source, "select_confidence_threshold", "min_coverage")\n'
            "    assert a is not None",
            {"min_coverage"},
        ),
        (
            'a = _pull(source, "select_confidence_threshold", "min_coverage")\n'
            "    assert None is not a",
            {"min_coverage"},
        ),
        ('a = _pull(source, "min_coverage")\n    assert a is not None', {"min_coverage"}),
        ('a = _pull(source, "f1-gate")\n    assert a is not None', {"f1"}),
    ],
)
def test_extraction_route_credits_only_one_literal_spelling(body, expected):
    """#338: the extraction route credits ``a = _pull(source, "lit", ...)`` only when ``a`` is
    bound exactly once by a top-level statement before a top-level bare ``assert a is not None``
    (either operand order), the first argument is the tainted source and every other argument a
    plain positional string literal (no keywords), and the literals name exactly one objective
    spelling by whole-token match; only that spelling is credited."""
    func = _single_test_function(
        f"def test_probe():\n    source = read_the_real_notebook()\n    {body}\n"
    )
    pinned = _spellings_pinned_by_assertions(func, {"source", "a", "b"}, locally_defined={"_pull"})
    assert pinned == expected, pinned


def test_flipping_recipe_42s_objective_turns_its_extraction_pin_red(tmp_path):
    """#338's flip-mutation test for the extraction route, on the recipe that uses it (42): the
    copy passes; with the notebook's confidence gate flipped from ``min_coverage`` to
    ``target_accuracy`` its genuine extraction pin goes red; and with that pin rewritten into the
    pooled two-spelling shape (the one that used to pass a flipped notebook) it stays red."""
    folder = _copy_recipe(tmp_path, "42-outbound-disclosure-screening")
    assert _objective_pin_violations(folder) == []
    _edit_notebook_code(folder, "min_coverage=0.75", "target_accuracy=1.0")
    assert _objective_pin_violations(folder), "the flipped objective still passed"

    tests_file = folder / "tests" / "test_helpers.py"
    text = tests_file.read_text("utf-8")
    genuine = (
        'min_coverage = _call_keyword_value(source, "select_confidence_threshold", "min_coverage")'
    )
    assert text.count(genuine) == 1
    pooled = 'min_coverage = _pull(source, "min_coverage", "target_accuracy")'
    helper = (
        "\n\ndef _pull(source, *keywords):\n"
        "    for keyword in keywords:\n"
        '        value = _call_keyword_value(source, "select_confidence_threshold", keyword)\n'
        "        if value is not None:\n"
        "            return value\n"
        "    return None\n"
    )
    # Precondition: the helper is seen as locally defined, so the same pin with ONE spelling
    # (the helper appended, the genuine call kept) is still credited.
    tests_file.write_text(text + helper, "utf-8")
    assert "min_coverage" in _pinned_objective_spellings(folder)
    tests_file.write_text(text.replace(genuine, pooled) + helper, "utf-8")
    pinned = _pinned_objective_spellings(folder)
    assert not {"min_coverage", "target_accuracy"} & pinned, pinned
    assert _objective_pin_violations(folder), "the pooled extraction passed a flipped notebook"


def test_flipping_recipe_42s_objective_stays_red_when_the_extraction_asserts_are_skipped(
    tmp_path,
):
    """Two skip-guarded extractions (one per spelling, each ``if x is None: pytest.skip(...)``
    before its ``assert x is not None``) must not pool both spellings: the asserts may never run,
    so the flipped notebook has to stay red."""
    folder = _copy_recipe(tmp_path, "42-outbound-disclosure-screening")
    tests_file = folder / "tests" / "test_helpers.py"
    text = tests_file.read_text("utf-8")
    start = text.index("def test_notebook_pins_the_confidence_gate_keyword_and_value")
    end = text.index("def _decide_cache_guard_present")
    template = (
        "def test_pins_{keyword}():\n"
        '    source = _notebook_cell_source("python-rule")\n'
        '    value = _call_keyword_value(source, "select_confidence_threshold", "{keyword}")\n'
        "    if value is None:\n"
        '        pytest.skip("absent")\n'
        "    assert value is not None\n\n\n"
    )
    two = "".join(template.format(keyword=k) for k in ("min_coverage", "target_accuracy"))
    tests_file.write_text(text[:start] + two + text[end:], "utf-8")
    assert not {"min_coverage", "target_accuracy"} & _pinned_objective_spellings(folder)
    _edit_notebook_code(folder, "min_coverage=0.75", "target_accuracy=1.0")
    assert _objective_pin_violations(folder), "skip-guarded extractions passed a flipped notebook"


def test_flipping_recipe_28s_objective_turns_its_production_tie_pin_red(tmp_path):
    """#338's flip-mutation test for the production-tie route, on the recipe that uses it (28)."""
    folder = _copy_recipe(tmp_path, "28-skill-selection")
    assert _objective_pin_violations(folder) == []
    _edit_notebook_code(folder, "min_coverage=helpers.MARGIN_MIN_COVERAGE", "target_accuracy=1.0")
    assert _objective_pin_violations(folder), "the flipped objective still passed"


def test_import_alias_is_resolved_across_notebook_cells_not_per_cell(tmp_path):
    """A notebook's ``from jev_cookbook.evaluation import select_confidence_threshold as X``
    import and the cell that calls ``X(...)`` are essentially never the same cell in practice
    (the import lives in an early setup cell; the call lives in the evaluation cell). A
    reviewer measured that resolving aliases against one cell's own parse tree alone -- what an
    earlier version of ``_threshold_pin_obligations`` did -- means the alias route can never
    actually fire for any notebook: 0 of 46 published recipes have the import and the call in
    the same cell.

    This goes through ``_threshold_pin_obligations`` itself, on a throwaway copy of a real
    recipe's notebook, rather than composing ``_import_aliases``/``_real_threshold_calls`` by
    hand -- an earlier version of this test did exactly that, which meant it kept passing when
    a reviewer reverted the merged-alias loop in ``_threshold_pin_obligations`` (the function
    the bug actually lived in) and replaced it with the old per-cell resolution: the hand-
    composed functions still worked correctly in isolation, so the test proved nothing about
    whether the fix was actually wired into the code path CI runs. Mutating recipe 38's own
    ``setup`` cell (the import) and ``python-rule`` cell (the call) into exactly this alias
    shape, on a throwaway copy, exercises the real function end to end."""
    recipe_dir = tmp_path / "38-abstention-and-review-queues"
    shutil.copytree(REPO / "recipes" / "38-abstention-and-review-queues", recipe_dir)
    nb_path = recipe_dir / "notebook.ipynb"
    notebook = json.loads(nb_path.read_text("utf-8"))
    setup_cell = next(c for c in notebook["cells"] if c.get("id") == "setup")
    rule_cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")

    import_source = cell_source(setup_cell)
    aliased_import = import_source.replace(
        "select_confidence_threshold,", "select_confidence_threshold as _sct,"
    )
    assert aliased_import != import_source, "mutation did not take -- the replace found nothing"
    setup_cell["source"] = [aliased_import]

    call_source = cell_source(rule_cell)
    aliased_call = call_source.replace(
        "threshold = select_confidence_threshold(", "threshold = _sct("
    )
    assert aliased_call != call_source, "mutation did not take -- the replace found nothing"
    rule_cell["source"] = [aliased_call]

    nb_path.write_text(json.dumps(notebook), encoding="utf-8")

    obligations = _threshold_pin_obligations(recipe_dir)
    assert ("cell python-rule", "select_confidence_threshold", "min_coverage") in obligations, (
        f"the aliased call was not resolved by _threshold_pin_obligations itself: {obligations}"
    )


# --------------------------------------------------------------------------------------------
# mutation tests for the EFFECTIVE TRUTH SENSE of an objective pin (#276). Each one runs the
# same ``_objective_pin_violations`` CI runs, on a throwaway copy of a published recipe that
# passes today (49, whose only pin is a ``"min_coverage" in source`` assertion), with that
# recipe's pin rewritten into the shape under test. A shape that says the spelling is ABSENT
# must make the check go red; a shape that says it is PRESENT must keep it green; and flipping
# the copy's objective (so the committed call no longer uses the pinned spelling) must turn every
# green shape red again, proving the pin is really tied to the committed call.
# --------------------------------------------------------------------------------------------

_POLARITY_BASE_RECIPE = "49-multi-agent-task-assignment"

_POLARITY_PREAMBLE = """\
import json
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parent.parent
"""

_NOTEBOOK_READ = """\
notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
cell = next(c for c in notebook["cells"] if c.get("id") == "threshold-code")
source = "".join(cell["source"])
cells = ["".join(c["source"]) for c in notebook["cells"]]
"""


def _polarity_violations(
    tmp_path: Path,
    assertions: str,
    *,
    read: str = _NOTEBOOK_READ,
    flip_objective: bool = False,
    decorators: str = "",
    nested: bool = False,
    class_header: str | None = None,
    module_prefix: str = "",
    test_file: str = "test_threshold_pin.py",
    module_suffix: str = "",
    conftest: str | None = None,
) -> list[str] | None:
    """Copy recipe 49 into ``tmp_path``, replace its ``tests/`` with a single test whose body is
    ``read`` followed by ``assertions`` (optionally decorated, nested inside a helper function
    pytest would not collect, made a method of the class ``class_header`` opens, or preceded by
    ``module_prefix`` at module level), optionally flip the committed notebook's objective from
    ``min_coverage`` to ``target_accuracy``, and return the check's verdict for the copy."""
    target = tmp_path / _POLARITY_BASE_RECIPE
    shutil.copytree(REPO / "recipes" / _POLARITY_BASE_RECIPE, target)
    for old in (target / "tests").glob("*.py"):
        old.unlink()
    body = textwrap.indent(read + assertions, "    ")
    signature = "(self)" if class_header else "()"
    test_text = f"{decorators}def test_pin{signature}:\n{body}"
    if class_header:  # the test becomes a method of the class the header opens
        test_text = f"{class_header}\n" + textwrap.indent(test_text, "    ")
    if nested:
        test_text = "def _helper():\n" + textwrap.indent(test_text, "    ")
    (target / "tests" / test_file).write_text(
        f"{_POLARITY_PREAMBLE}\n\n{module_prefix}{test_text}{module_suffix}", encoding="utf-8"
    )
    if conftest is not None:
        (target / "tests" / "conftest.py").write_text(conftest, encoding="utf-8")
    if flip_objective:
        nb_path = target / "notebook.ipynb"
        notebook = json.loads(nb_path.read_text("utf-8"))
        flipped = 0
        for cell in notebook["cells"]:
            if cell.get("id") in ("threshold-code", "sweep-code"):
                text = cell_source(cell)
                swapped = text.replace("min_coverage=", "target_accuracy=")
                assert swapped != text, "mutation did not take -- the replace found nothing"
                cell["source"] = [swapped]
                flipped += 1
        assert flipped == 2
        nb_path.write_text(json.dumps(notebook), encoding="utf-8")
    return _objective_pin_violations(target)


def test_the_unmutated_polarity_baseline_passes_and_a_hand_typed_pin_does_not(tmp_path):
    """The baseline every mutation below departs from: recipe 49's own pin shape passes on the
    copy, and the SAME assertion against a hand-typed duplicate of the source (not a read of the
    committed notebook) does not."""
    assert _polarity_violations(tmp_path / "a", 'assert "min_coverage" in source\n') == []
    typed = "source = 'select_confidence_threshold(min_coverage=0.5)'\nassert \"min_coverage\" in source\n"
    violations = _polarity_violations(tmp_path / "b", typed, read="")
    assert violations and "min_coverage" in violations[0]


# Each spelling says the objective is NOT in the committed source (or says nothing that proves
# it is), so a recipe whose only pin is this shape is unpinned.
_ABSENT_OR_UNPROVEN_SHAPES = {
    # the four spellings #276 names
    "is False": 'assert ("min_coverage" in source) is False\n',
    "count == 0": 'assert source.count("min_coverage") == 0\n',
    "len of filtered comprehension == 0": (
        'assert len([s for s in cells if "min_coverage" in s]) == 0\n'
    ),
    "if-expression with a vacuous branch": (
        'assert ("min_coverage" in source) if len(source) > 0 else True\n'
    ),
    # the same property in other clothes
    "== False": 'assert ("min_coverage" in source) == False  # noqa: E712\n',
    "is not True": 'assert ("min_coverage" in source) is not True\n',
    "not in is True": 'assert ("min_coverage" not in source) is True\n',
    "not in": 'assert "min_coverage" not in source\n',
    "not (x in y)": 'assert not ("min_coverage" in source)\n',
    "count < 1": 'assert source.count("min_coverage") < 1\n',
    "count <= 0": 'assert source.count("min_coverage") <= 0\n',
    "0 == count": 'assert 0 == source.count("min_coverage")\n',
    "not bare count": 'assert not source.count("min_coverage")\n',
    "not (count > 0)": 'assert not (source.count("min_coverage") > 0)\n',
    "len of comprehension is 0": ('assert len([s for s in cells if "min_coverage" in s]) < 1\n'),
    "sum of matches == 0": ('assert sum(1 for s in cells if "min_coverage" in s) == 0\n'),
    "not any": 'assert not any("min_coverage" in s for s in cells)\n',
    "all(not in)": 'assert all("min_coverage" not in s for s in cells)\n',
    "any(not in)": 'assert any("min_coverage" not in s for s in cells)\n',
    "not all(in)": 'assert not all("min_coverage" in s for s in cells)\n',
    "or with a vacuous operand": 'assert ("min_coverage" in source) or len(source) > 0\n',
    "or True": 'assert ("min_coverage" in source) or True\n',
    "chained comparison to zero": 'assert 0 == source.count("min_coverage") == 0\n',
    "count compared with a non-number": ('assert source.count("min_coverage") == len(cells)\n'),
    "all over a possibly-empty iterable (vacuous)": (
        'assert all("min_coverage" in s for s in cells)\n'
    ),
    "assert under pytest.raises (claims absence)": (
        'with pytest.raises(AssertionError):\n    assert "min_coverage" in source\n'
    ),
    "assert under an if": 'if len(source) > 0:\n    assert "min_coverage" in source\n',
    "assert in a loop": 'for s in cells:\n    assert "min_coverage" in s\n',
    # review of the first head: comprehension scoping and vacuous non-emptiness
    "any rebinding the tainted name": (
        'assert any("min_coverage" in source for source in ["min_coverage"])\n'
    ),
    "all rebinding the tainted name": (
        'assert all("min_coverage" in source for source in ["min_coverage"])\n'
    ),
    "any over a display mixing the read with a typed needle": (
        'assert any("min_coverage" in s for s in [source, "min_coverage"])\n'
    ),
    "all over a name emptied after a non-empty assignment": (
        'sources = [source]\nsources = []\nassert all("min_coverage" in s for s in sources)\n'
    ),
    "all over a name emptied in place": (
        'sources = [source]\nsources.clear()\nassert all("min_coverage" in s for s in sources)\n'
    ),
    "all over a name asserted non-empty then rebound": (
        "sources = [source]\nassert sources\nsources = []\n"
        'assert all("min_coverage" in s for s in sources)\n'
    ),
    "all over a generator asserted truthy": (
        'sources = (s for s in cells if "zzz" in s)\nassert sources\n'
        'assert all("min_coverage" in s for s in sources)\n'
    ),
    # an assert that may never run
    "assert after an early return": ('if source:\n    return\nassert "min_coverage" in source\n'),
    "assert after pytest.skip": 'pytest.skip("later")\nassert "min_coverage" in source\n',
    "assert after a conditional skip": (
        'if not source:\n    pytest.skip("later")\nassert "min_coverage" in source\n'
    ),
    "assert after a raise": 'raise RuntimeError("x")\nassert "min_coverage" in source\n',
    "assert in a loop with a continue before it": (
        'for cid in ("threshold-code", "sweep-code"):\n    if cid:\n        continue\n'
        '    assert "min_coverage" in source\n'
    ),
    "assert in a loop with a break": (
        'for cid in ("threshold-code", "sweep-code"):\n    assert "min_coverage" in source\n'
        "    break\n"
    ),
    # the needle is compared against a value that carries a hand-typed copy of it
    "needle smuggled into a default": (
        'kws = {"a": source}\nassert kws.get("objective", "min_coverage") == "min_coverage"\n'
    ),
    "needle smuggled through or": 'assert (source or "min_coverage") == "min_coverage"\n',
    "needle appended to the source": 'assert "min_coverage" in source + " min_coverage"\n',
    "needle substituted into the source": (
        'assert "min_coverage" in source.replace("target_accuracy", "min_coverage")\n'
    ),
    "needle in a display with the source": 'assert "min_coverage" in [source, "min_coverage"]\n',
    "count of the needle in a padded source": (
        'assert (source + "min_coverage").count("min_coverage") >= 1\n'
    ),
    # taint ignoring reassignment
    "source rebound to a typed string": (
        "source = 'select_confidence_threshold(s, min_coverage=0.75)'\n"
        'assert "min_coverage" in source\n'
    ),
    # re-review of the second head, finding 1: a name is tainted only if EVERY binding of it is,
    # whatever the binding FORM (the rule used to look at ``name = ...`` and ``with ... as`` only)
    "source extended in place": 'source += " min_coverage"\nassert "min_coverage" in source\n',
    "source rebound as a for target (assert inside the loop)": (
        'for source in ("min_coverage",):\n    assert "min_coverage" in source\n'
    ),
    "source rebound as a for target (assert after the loop)": (
        'for source in ("min_coverage",):\n    pass\nassert "min_coverage" in source\n'
    ),
    "source rebound by tuple unpacking": (
        'source, _ = "min_coverage", 1\nassert "min_coverage" in source\n'
    ),
    "source rebound by a walrus": (
        'assert (source := "min_coverage")\nassert "min_coverage" in source\n'
    ),
    "source rebound by an annotated assignment": (
        'source: str = "min_coverage"\nassert "min_coverage" in source\n'
    ),
    "source rebound by with-as unpacking": (
        'with open(RECIPE / "notebook.ipynb") as (source, _):\n'
        '    assert "min_coverage" in source\n'
    ),
    "source deleted and rebound": (
        'del source\nsource = "min_coverage"\nassert "min_coverage" in source\n'
    ),
    # re-review of the second head, finding 2: the needle typed into the compared value is seen
    # through an intermediate variable, not only when spelled inline in the assert
    "needle appended through a variable": (
        'padded = source + " min_coverage"\nassert "min_coverage" in padded\n'
    ),
    "needle appended by rebinding the source itself": (
        'source = source + " min_coverage"\nassert "min_coverage" in source\n'
    ),
    "needle substituted through a variable": (
        'swapped = source.replace("target_accuracy", "min_coverage")\n'
        'assert "min_coverage" in swapped\n'
    ),
    "needle substituted through two variables": (
        'swapped = source.replace("target_accuracy", "min_coverage")\n'
        'again = swapped.strip()\nassert "min_coverage" in again\n'
    ),
    "needle smuggled through or in a variable": (
        'val = source or "min_coverage"\nassert val == "min_coverage"\n'
    ),
    "needle in a dict value beside the source": (
        'kws = {"objective": "min_coverage", "s": source}\n'
        'assert kws["objective"] == "min_coverage"\n'
    ),
    "needle as a dict key of a dict of the source": (
        'kws = {"min_coverage": source}\nassert "min_coverage" in kws\n'
    ),
    "needle counted in a padded variable": (
        'padded = source + "min_coverage"\nassert padded.count("min_coverage") >= 1\n'
    ),
    # re-review of the third head: the needle is put into, or spelled around, the compared value
    # without ever appearing in a binding value or as one constant
    "needle appended to a container in place": (
        'parts = [source, source]\nparts.append("min_coverage")\njoined = "".join(parts)\n'
        'assert "min_coverage" in joined\n'
    ),
    "needle extended into a container in place": (
        'parts = [source, source]\nparts.extend(["min_coverage"])\njoined = "".join(parts)\n'
        'assert "min_coverage" in joined\n'
    ),
    "needle stored into a dict in place": (
        'kws = {"a": source}\nkws["b"] = "min_coverage"\nassert "min_coverage" in kws["b"]\n'
    ),
    "needle updated into a dict in place": (
        'kws = {"a": source}\nkws.update(b="min_coverage")\nassert "min_coverage" in kws["b"]\n'
    ),
    "needle spelled as a split literal": (
        'assert "min_coverage" in source.replace("select", "min" + "_coverage")\n'
    ),
    "needle spelled as a split literal through a variable": (
        'swapped = source.replace("select", "min" + "_coverage")\n'
        'assert "min_coverage" in swapped\n'
    ),
    "needle held in an untainted local variable": (
        'needle = "min_coverage"\nswapped = source.replace("select", needle)\n'
        'assert "min_coverage" in swapped\n'
    ),
    "needle carried into a comprehension variable": (
        'parts = [source.replace("a", "min_coverage")]\n'
        'assert all("min_coverage" in p for p in parts)\n'
    ),
}

# Shapes that need the whole test function around them rather than a body: a decorator or a
# nesting that stops pytest from running the asserts.
_NOT_RUN_WRAPPERS = {
    "skip marker": {"decorators": '@pytest.mark.skip(reason="x")\n'},
    "skipif marker": {"decorators": '@pytest.mark.skipif(True, reason="x")\n'},
    "xfail marker": {"decorators": "@pytest.mark.xfail\n"},
    "test nested in a helper (never collected)": {"nested": True},
    # re-review of the third head: the same axis one scope out (class and module)
    "class-level skip marker": {"class_header": '@pytest.mark.skip(reason="x")\nclass TestPin:'},
    "class-level skipif marker": {
        "class_header": '@pytest.mark.skipif(True, reason="x")\nclass TestPin:'
    },
    "class-level xfail marker": {"class_header": "@pytest.mark.xfail\nclass TestPin:"},
    "class-body pytestmark": {
        "class_header": 'class TestPin:\n    pytestmark = pytest.mark.skip(reason="x")'
    },
    "class not named Test* (pytest does not collect it)": {"class_header": "class Helper:"},
    "class defining __init__ (pytest does not collect it)": {
        "class_header": "class TestPin:\n    def __init__(self):\n        self.x = 1\n"
    },
    "module-level importorskip": {
        "module_prefix": 'pytest.importorskip("no_such_module_for_the_guard")\n\n\n'
    },
    "module-level importorskip bound to a name": {
        "module_prefix": 'np = pytest.importorskip("no_such_module_for_the_guard")\n\n\n'
    },
    "module-level skip(allow_module_level=True)": {
        "module_prefix": 'pytest.skip("x", allow_module_level=True)\n\n\n'
    },
    "module-level skip under an if": {
        "module_prefix": 'if RECIPE:\n    pytest.skip("x", allow_module_level=True)\n\n\n'
    },
    "module-level pytestmark skip": {
        "module_prefix": 'pytestmark = pytest.mark.skip(reason="x")\n\n\n'
    },
}

# What pytest DOES collect: the same assertion in these is credited (so the refusals above are
# about the wrapper, not about the shape of the file).
_COLLECTED_WRAPPERS = {
    "plain function": {},
    "method of a Test* class": {"class_header": "class TestPin:"},
    "method of a Test* class marked only by an unrelated mark": {
        "class_header": "@pytest.mark.slow\nclass TestPin:"
    },
    "importorskip inside a helper function (does not skip the file)": {
        "module_prefix": 'def _later():\n    pytest.importorskip("x")\n\n\n'
    },
}

# Each shape says the objective IS in the committed source.
_PRESENT_SHAPES = {
    "in": 'assert "min_coverage" in source\n',
    "is True": 'assert ("min_coverage" in source) is True\n',
    "== True": 'assert ("min_coverage" in source) == True  # noqa: E712\n',
    "not in is False": 'assert ("min_coverage" not in source) is False\n',
    "not (not in)": 'assert not ("min_coverage" not in source)\n',
    "not (in is False)": 'assert not (("min_coverage" in source) is False)\n',
    "count >= 1": 'assert source.count("min_coverage") >= 1\n',
    "count > 0": 'assert source.count("min_coverage") > 0\n',
    "count != 0": 'assert source.count("min_coverage") != 0\n',
    "count == n": 'assert source.count("min_coverage") == 2\n',
    "1 <= count": 'assert 1 <= source.count("min_coverage")\n',
    "0 < count": 'assert 0 < source.count("min_coverage")\n',
    "bare count": 'assert source.count("min_coverage")\n',
    "not (count == 0)": 'assert not (source.count("min_coverage") == 0)\n',
    "count is positive and bounded": 'assert 1 <= source.count("min_coverage") <= 9\n',
    "len of filtered comprehension > 0": (
        'assert len([s for s in cells if "min_coverage" in s]) > 0\n'
    ),
    "sum of matches >= 1": 'assert sum(1 for s in cells if "min_coverage" in s) >= 1\n',
    "if-expression with the pin in both branches": (
        'assert ("min_coverage" in source) if len(source) > 0 else ("min_coverage" in source)\n'
    ),
    "and with an unrelated absence claim": (
        'assert "min_coverage" in source and "target_accuracy" not in source\n'
    ),
    "or with the pin in both operands": (
        'assert "min_coverage" in source or source.count("min_coverage") > 0\n'
    ),
    "bool()": 'assert bool("min_coverage" in source)\n',
    "any over a tainted source": 'assert any("min_coverage" in s for s in cells)\n',
    "not all(not in)": 'assert not all("min_coverage" not in s for s in cells)\n',
    "all over a literal non-empty display": (
        'assert all("min_coverage" in s for s in (source, source))\n'
    ),
    "all over a name asserted non-empty": (
        "sources = [s for s in cells]\nassert len(sources) > 0\n"
        'assert all("min_coverage" in s for s in sources)\n'
    ),
    "not any(not in) over a literal non-empty display": (
        'assert not any("min_coverage" not in s for s in [source, source])\n'
    ),
    "all([...]) of memberships": (
        'assert all(["min_coverage" in source, source.count("min_coverage") > 0])\n'
    ),
    "any([...]) of identical claims": (
        'assert any(["min_coverage" in source, source.count("min_coverage") > 0])\n'
    ),
    "f-string needle": 'assert f"min_coverage={0.75}" in source\n',
    "assert inside a plain open block": 'with open(RECIPE / "notebook.ipynb") as h:\n    assert "min_coverage" in source\n',
    # review of the first head: idioms the first derivation wrongly refused
    "sum of booleans": 'assert sum(("min_coverage" in s) for s in cells) > 0\n',
    "sum of counts": 'assert sum(s.count("min_coverage") for s in cells) >= 1\n',
    "loop over a literal tuple of cell ids": (
        'for cid in ("threshold-code", "sweep-code"):\n'
        '    src = "".join(next(c for c in notebook["cells"] if c.get("id") == cid)["source"])\n'
        '    assert "min_coverage" in src\n'
    ),
    "assert before an early return": (
        'assert "min_coverage" in source\nif not source:\n    return\n'
    ),
    "all over a name asserted non-empty (list)": (
        "sources = [s for s in cells]\nassert sources\n"
        'assert all("min_coverage" in s for s in sources)\n'
    ),
    # re-review of the second head: carrying taint through names must not refuse a pin that is
    # still wholly derived from the read and types no needle of its own. (#320: ``.lower()`` was
    # listed here as neutral; it rewrites the characters, so it is refused -- see
    # ``test_a_value_whose_characters_were_rewritten_is_not_the_committed_source``.)
    "a neutral transform of the source": 'stripped = source.strip()\nassert "min_coverage" in stripped\n',
    "a name rebound to another value derived from the read": (
        'text = source\ntext = source.strip()\nassert "min_coverage" in text\n'
    ),
    "a chain of neutral transforms": (
        'a = source.strip()\nb = a.rstrip()\nc = b.replace(" ", "")\nassert "min_coverage" in c\n'
    ),
    "a container filled in place with values derived from the read": (
        'parts = [source]\nparts.append(source.strip())\njoined = "".join(parts)\n'
        'assert "min_coverage" in joined\n'
    ),
    "a dict stored into in place with a value derived from the read": (
        'kws = {"a": source}\nkws["b"] = source.strip()\nassert "min_coverage" in kws["b"]\n'
    ),
    "a dict of values all derived from the read": (
        'kws = {"one": source, "two": source.strip()}\nassert "min_coverage" in kws["one"]\n'
    ),
}


@pytest.mark.parametrize("shape", sorted(_ABSENT_OR_UNPROVEN_SHAPES))
def test_a_spelling_asserted_absent_or_unproven_is_not_credited_as_pinned(tmp_path, shape):
    """#276: every shape here says the objective is absent from the committed source (or proves
    nothing about it), so a recipe pinned only that way must FAIL the check. Each is planted in a
    copy of a recipe that passes today. Reverting the polarity derivation (back to crediting any
    comparison whose operands name the spelling) turns every case here green."""
    violations = _polarity_violations(tmp_path, _ABSENT_OR_UNPROVEN_SHAPES[shape])
    assert violations, f"{shape!r}: a spelling that is not asserted present was credited"
    assert "min_coverage" in violations[0]


@pytest.mark.parametrize("shape", sorted(_PRESENT_SHAPES))
def test_a_spelling_asserted_present_is_still_credited_and_tied_to_the_committed_call(
    tmp_path, shape
):
    """The positive half, proved by mutation both ways: the shape passes on the unmodified
    objective, and goes red the moment the committed notebook's objective is flipped to a
    spelling the shape does not mention (so the pin is bound to the committed call, not merely
    accepted). Covers ``all(...)``/``any(...)`` over a tainted source (previously refused because
    taint never reached a comprehension variable)."""
    assertions = _PRESENT_SHAPES[shape]
    assert _polarity_violations(tmp_path / "keep", assertions) == [], (
        f"{shape!r}: a legitimate pin was refused"
    )
    flipped = _polarity_violations(tmp_path / "flip", assertions, flip_objective=True)
    assert flipped and "target_accuracy" in flipped[0], (
        f"{shape!r}: passed although the committed objective no longer matches the pin"
    )


# (read statements, assertion) pairs: a read of the committed notebook spelled without
# ``read_text``. They taint the value they produce, so the pin passes, and flipping the objective
# turns it red. Before #276 each of these produced NO taint and was refused.
_READ_SPELLINGS = {
    "open(...).read()": (
        'source = open(RECIPE / "notebook.ipynb", encoding="utf-8").read()\n',
        'assert "min_coverage" in source\n',
    ),
    "read_bytes()": (
        'raw = (RECIPE / "notebook.ipynb").read_bytes()\n',
        'assert b"min_coverage" in raw\n',
    ),
    "with open() as f: f.read()": (
        'with open(RECIPE / "notebook.ipynb", encoding="utf-8") as handle:\n'
        "    source = handle.read()\n",
        'assert "min_coverage" in source\n',
    ),
    "json.load(open())": (
        'notebook = json.load(open(RECIPE / "notebook.ipynb", encoding="utf-8"))\n'
        'source = "".join(c["source"][0] for c in notebook["cells"] if c.get("id") == "threshold-code")\n',
        'assert "min_coverage" in source\n',
    ),
    "read_text() (unchanged)": (
        'source = (RECIPE / "notebook.ipynb").read_text("utf-8")\n',
        'assert "min_coverage" in source\n',
    ),
    "Path.open().read()": (
        'source = (RECIPE / "notebook.ipynb").open(encoding="utf-8").read()\n',
        'assert "min_coverage" in source\n',
    ),
}


@pytest.mark.parametrize("spelling", sorted(_READ_SPELLINGS))
def test_a_read_of_the_committed_notebook_taints_whatever_call_performs_it(tmp_path, spelling):
    read, assertion = _READ_SPELLINGS[spelling]
    assert _polarity_violations(tmp_path / "keep", assertion, read=read) == [], (
        f"{spelling}: a real read of the committed notebook did not taint its result"
    )
    flipped = _polarity_violations(tmp_path / "flip", assertion, read=read, flip_objective=True)
    assert flipped and "target_accuracy" in flipped[0], (
        f"{spelling}: the pin was not tied to the committed call"
    )


def test_a_read_of_something_else_does_not_taint(tmp_path):
    """The converse of the read-spelling widening: mentioning the committed file's name is not a
    read of it, and reading some OTHER file is not a read of the committed artefact."""
    mentions = 'source = str(RECIPE / "notebook.ipynb")\n'
    elsewhere = 'source = open(RECIPE / "README.md", encoding="utf-8").read()\n'
    for index, read in enumerate((mentions, elsewhere)):
        violations = _polarity_violations(
            tmp_path / str(index), 'assert "min_coverage" in source\n', read=read
        )
        assert violations, (
            f"credited a pin against a value that is not the committed source: {read}"
        )


@pytest.mark.parametrize("wrapper", sorted(_COLLECTED_WRAPPERS))
def test_a_pin_in_a_test_pytest_does_collect_is_credited(tmp_path, wrapper):
    """The converse of the not-run wrappers: a pin pytest really runs is still credited when it
    sits in a collected class, so the class and module rules refuse only what pytest would not run."""
    assertion = 'assert "min_coverage" in source\n'
    assert _polarity_violations(tmp_path, assertion, **_COLLECTED_WRAPPERS[wrapper]) == [], wrapper


def test_a_needle_typed_into_the_read_statement_itself_does_not_pin(tmp_path):
    """The read is a real read of the committed notebook, so the name is tainted -- but the same
    statement also types the needle, so the assert holds whatever the notebook says. The needle is
    recorded against the name (``_Taint.embedded``) and refused; the same read without the
    appended text is credited."""
    plain = 'source = (RECIPE / "notebook.ipynb").read_text("utf-8")\n'
    padded = 'source = (RECIPE / "notebook.ipynb").read_text("utf-8") + " min_coverage"\n'
    assertion = 'assert "min_coverage" in source\n'
    assert _polarity_violations(tmp_path / "plain", assertion, read=plain) == []
    assert _polarity_violations(tmp_path / "padded", assertion, read=padded), (
        "credited a pin whose compared value carries a needle typed in the read statement"
    )


@pytest.mark.parametrize("wrapper", sorted(_NOT_RUN_WRAPPERS))
def test_asserts_of_a_test_pytest_does_not_run_are_not_credited(tmp_path, wrapper):
    """A pin in a test that is marked skip/skipif/xfail, defined inside another function, in a
    class pytest does not collect (not ``Test*``, an ``__init__``, a class-level mark or
    ``pytestmark``) or in a module that skips itself (``importorskip``, ``skip(allow_module_level=
    True)``, ``pytestmark``) never runs, so it is not a pin: the same assertion that passes in a
    normal test is refused."""
    assertion = 'assert "min_coverage" in source\n'
    assert _polarity_violations(tmp_path / "plain", assertion) == []
    violations = _polarity_violations(tmp_path / "wrapped", assertion, **_NOT_RUN_WRAPPERS[wrapper])
    assert violations, f"{wrapper}: credited an assert that does not run"


# --- #320: credit that was wider than the claim -------------------------------------------------
# Each test below fails on the guard as it stood before #320 (the refused shape was credited) and
# passes now; each is paired with a control that must still be credited.

_PIN = 'assert "min_coverage" in source\n'
_COMMITTED = '(RECIPE / "notebook.ipynb")'


@pytest.mark.parametrize(
    "opener",
    [
        'open(RECIPE / "notebook.ipynb", "w", encoding="utf-8")',
        'open(RECIPE / "notebook.ipynb", "a")',
        'open(RECIPE / "notebook.ipynb", "x")',
        'open(RECIPE / "notebook.ipynb", "wb")',
        'open(RECIPE / "notebook.ipynb", mode="w")',
        'open(RECIPE / "notebook.ipynb", MODE)',
        'open(RECIPE / "notebook.ipynb", **kw)',
        f'{_COMMITTED}.open("w", encoding="utf-8")',
        f"{_COMMITTED}.open(mode='w')",
    ],
)
def test_opening_the_committed_file_for_writing_is_not_a_read_of_it(tmp_path, opener):
    """``open(path, "w")`` makes the file; it does not read it. Before #320 any ``open`` call that
    named the committed file seeded taint, whatever its mode, so a value derived from a write
    handle was credited as "the committed source". A mode that cannot be read (a name) is refused
    the same way."""
    read = f"with {opener} as handle:\n    handle.write('')\nsource = handle\n"
    violations = _polarity_violations(tmp_path, _PIN, read=read)
    assert violations, f"credited a pin against a file opened for writing: {opener}"


@pytest.mark.parametrize(
    "opener",
    [
        'open(RECIPE / "notebook.ipynb", encoding="utf-8")',
        'open(RECIPE / "notebook.ipynb", "r", encoding="utf-8")',
        'open(RECIPE / "notebook.ipynb", "rb")',
        'open(RECIPE / "notebook.ipynb", "r+")',
        'open(RECIPE / "notebook.ipynb", mode="rt")',
        f'{_COMMITTED}.open("r")',
        f"{_COMMITTED}.open(encoding='utf-8')",
    ],
)
def test_opening_the_committed_file_for_reading_is_still_a_read_of_it(tmp_path, opener):
    needle = 'b"min_coverage"' if '"rb"' in opener else '"min_coverage"'
    assertion = f"assert {needle} in source\n"
    assert _polarity_violations(tmp_path, assertion, read=f"source = {opener}.read()\n") == [], (
        opener
    )


@pytest.mark.parametrize(
    "read",
    [
        f'source = {_COMMITTED}.read_text("utf-8").lower()\n',
        f'source = {_COMMITTED}.read_text("utf-8").casefold()\n',
        f'source = {_COMMITTED}.read_text("utf-8").upper()\n',
        f'raw = {_COMMITTED}.read_text("utf-8")\nsource = raw.lower()\n',
        f'raw = {_COMMITTED}.read_text("utf-8")\nfolded = raw.lower()\nsource = folded.strip()\n',
        f'source = {_COMMITTED}.read_text("utf-8").title()\n',
        f'source = {_COMMITTED}.read_text("utf-8").translate({{}})\n',
    ],
)
def test_a_value_whose_characters_were_rewritten_is_not_the_committed_source(tmp_path, read):
    """``"min_coverage" in source.lower()`` holds for a comment that says ``MIN_COVERAGE`` while the
    call uses another objective, so a case-rewritten value is not credited (before #320 it was,
    because any value that references a tainted name stayed tainted)."""
    violations = _polarity_violations(tmp_path, _PIN, read=read)
    assert violations, f"credited a pin against a rewritten value: {read!r}"


def test_an_assert_that_rewrites_the_source_inline_is_not_credited(tmp_path):
    violations = _polarity_violations(tmp_path, 'assert "min_coverage" in source.lower()\n')
    assert violations
    assert _polarity_violations(
        tmp_path / "unbound", 'assert "min_coverage" in str.lower(source)\n'
    )
    assert (
        _polarity_violations(tmp_path / "plain", 'assert "min_coverage" in source.strip()\n') == []
    ), "a lossless transform of the committed source must stay credited"


@pytest.mark.parametrize(
    "read",
    [
        "import shutil, tempfile\n"
        "work = Path(tempfile.mkdtemp())\n"
        'shutil.copy(RECIPE / "notebook.ipynb", work / "notebook.ipynb")\n'
        'source = (work / "notebook.ipynb").read_text("utf-8")\n',
        "import shutil, tempfile\n"
        "with tempfile.TemporaryDirectory() as scratch:\n"
        '    shutil.copytree(RECIPE, Path(scratch) / "r")\n'
        '    source = (Path(scratch) / "r" / "notebook.ipynb").read_text("utf-8")\n',
        "import tempfile\n"
        'source = (Path(tempfile.gettempdir()) / "notebook.ipynb").read_text("utf-8")\n',
        "from tempfile import mkdtemp\n"
        "work = mkdtemp()\n"
        'source = open(Path(work) / "notebook.ipynb", encoding="utf-8").read()\n',
        "import shutil\n"
        'work = Path(shutil.copy2(RECIPE / "notebook.ipynb", RECIPE.parent)).parent\n'
        'source = (work / "notebook.ipynb").read_text("utf-8")\n',
    ],
)
def test_a_read_of_a_tempfile_or_shutil_copy_does_not_taint(tmp_path, read):
    """Before #320 only a path rooted in ``tmp_path`` (or ``tmpdir``) was recognised as a
    test-made copy; a copy a test mutates under ``tempfile`` or ``shutil`` tainted like the
    committed file, so the test could pin text it had typed into its own copy."""
    violations = _polarity_violations(tmp_path, _PIN, read=read)
    assert violations, f"credited a read of a test-made copy: {read!r}"


@pytest.mark.parametrize(
    "read",
    [
        'source = (RECIPE.parent / "42-outbound-disclosure-screening" / "notebook.ipynb")'
        '.read_text("utf-8")\n',
        'source = open(RECIPE.parent / "42-outbound-disclosure-screening/notebook.ipynb").read()\n',
        'source = open("../28-some-recipe/helpers.py").read()\n',
        'source = open(RECIPE.parent / "100-some-recipe" / "notebook.ipynb").read()\n',
        'source = open("../100-some-recipe/notebook.ipynb").read()\n',
    ],
)
def test_another_recipes_notebook_is_not_this_recipes_committed_source(tmp_path, read):
    """A pin tied to a hand-named recipe folder cannot notice this recipe's objective changing, so
    it is not credited (before #320 any read that named ``notebook.ipynb`` was). A recipe locates
    its own folder from ``__file__`` (``RECIPE``), which is still credited."""
    violations = _polarity_violations(tmp_path, _PIN, read=read)
    assert violations, f"credited a read of another recipe's artefact: {read!r}"


@pytest.mark.parametrize("name", ["conftest.py", "check_objective.py", "helpers_test_data.py"])
def test_a_test_in_a_file_pytest_does_not_collect_is_not_a_pin(tmp_path, name):
    """``def test_*`` in ``conftest.py`` or any module that is not ``test_*.py`` / ``*_test.py`` is
    never run by pytest, so its asserts pin nothing; before #320 the ``tests/*.py`` glob credited
    them."""
    assert _polarity_violations(tmp_path / "ok", _PIN) == []
    violations = _polarity_violations(tmp_path / "bad", _PIN, test_file=name)
    assert violations, f"{name}: credited a pin in a file pytest does not collect"


def test_a_pin_in_a_star_underscore_test_file_is_credited(tmp_path):
    assert _polarity_violations(tmp_path, _PIN, test_file="objective_test.py") == []


# --- #320 fix round: reviewers' gaps --------------------------------------------------------


@pytest.mark.parametrize(
    "read",
    [
        "import tempfile as tf\n"
        "work = Path(tf.mkdtemp())\n"
        'source = (work / "notebook.ipynb").read_text("utf-8")\n',
        "from tempfile import TemporaryDirectory as TD\n"
        "with TD() as scratch:\n"
        '    source = (Path(scratch) / "notebook.ipynb").read_text("utf-8")\n',
        "import shutil\n"
        'dst = Path("/x")\n'
        'shutil.copy(RECIPE / "notebook.ipynb", dst)\n'
        'source = (dst / "notebook.ipynb").read_text("utf-8")\n',
        "import shutil as sh\n"
        "dst = RECIPE.parent / 'copy'\n"
        "sh.copytree(RECIPE, dst=dst)\n"
        'source = (dst / "notebook.ipynb").read_text("utf-8")\n',
    ],
)
def test_aliased_tempfile_and_a_bare_copy_statement_are_scratch(tmp_path, read):
    violations = _polarity_violations(tmp_path, _PIN, read=read)
    assert violations, f"credited a read of a test-made copy: {read!r}"


@pytest.mark.parametrize(
    "read",
    [
        f'raw = {_COMMITTED}.read_text("utf-8")\nsource = "".join(map(str.lower, raw))\n',
        "import functools\n"
        f'raw = {_COMMITTED}.read_text("utf-8")\n'
        "source = functools.partial(str.lower)(raw)\n",
        "import functools\n"
        f'raw = {_COMMITTED}.read_text("utf-8")\n'
        "source = functools.reduce(lambda a, f: f(a), [str.lower], raw)\n",
        "import operator\n"
        f'raw = {_COMMITTED}.read_text("utf-8")\n'
        'source = operator.methodcaller("lower")(raw)\n',
        f'raw = {_COMMITTED}.read_text("utf-8")\nsource = getattr(raw, "lower")()\n',
        f'raw = {_COMMITTED}.read_text("utf-8")\nsource = str.lower(raw)\n',
        f'source = str.casefold({_COMMITTED}.read_text("utf-8"))\n',
    ],
)
def test_a_case_rewrite_that_is_not_a_method_call_is_not_the_committed_source(tmp_path, read):
    violations = _polarity_violations(tmp_path, _PIN, read=read)
    assert violations, f"credited a pin against a rewritten value: {read!r}"


@pytest.mark.parametrize(
    "read",
    [
        'enc = "UTF-8"\nsource = ' + _COMMITTED + ".read_text(enc.lower())\n",
        'import shutil\nsource = "".join(\n'
        "    l for l in "
        + _COMMITTED
        + '.read_text("utf-8").splitlines(True) if shutil.which("python")\n)\n',
        "nb = json.loads(" + _COMMITTED + '.read_text("utf-8"))\n'
        'source = "".join("".join(c["source"]) for c in nb["cells"] if c.get("id") != "10-threshold")\n',
        '(tmp_path / "notebook.ipynb").write_text("x", "utf-8")\n'
        "source = " + _COMMITTED + '.read_text("utf-8")\n',
    ],
)
def test_narrow_refusals_leave_these_legitimate_reads_credited(tmp_path, read):
    """The refusals above are scoped to the source value: a ``.lower()`` on something else, a
    ``shutil`` call that makes no copy, a slug-shaped cell id compared as data, and a write to a
    scratch copy do not refuse a read of the committed notebook."""
    assert _polarity_violations(tmp_path, _PIN, read=read) == [], read


@pytest.mark.parametrize(
    "read",
    [
        f'{_COMMITTED}.write_text("min_coverage", "utf-8")\n'
        f'source = {_COMMITTED}.read_text("utf-8")\n',
        'with open(RECIPE / "notebook.ipynb", "w") as handle:\n'
        '    handle.write("min_coverage")\n'
        'source = open(RECIPE / "notebook.ipynb", encoding="utf-8").read()\n',
        f'{_COMMITTED}.write_bytes(b"min_coverage")\nsource = {_COMMITTED}.read_text("utf-8")\n',
    ],
)
def test_writing_the_committed_file_then_reading_it_back_pins_nothing(tmp_path, read):
    violations = _polarity_violations(tmp_path, _PIN, read=read)
    assert violations, f"credited a pin against text the test wrote itself: {read!r}"


_NOT_COLLECTED = {
    "class __test__ = False": {"class_header": "class TestPin:\n    __test__ = False"},
    "module __test__ = False": {"module_prefix": "__test__ = False\n\n\n"},
    "inherited __init__ from a local base": {
        "module_prefix": "class Base:\n    def __init__(self):\n        pass\n\n\n",
        "class_header": "class TestPin(Base):",
    },
    "inherited __test__ = False from a local base": {
        "module_prefix": "class Base:\n    __test__ = False\n\n\n",
        "class_header": "class TestPin(Base):",
    },
    "a later def of the same name": {"module_suffix": "\n\ndef test_pin():\n    pass\n"},
    "collect_ignore in conftest.py": {"conftest": 'collect_ignore = ["test_threshold_pin.py"]\n'},
    "collect_ignore appended to": {
        "conftest": 'collect_ignore = []\ncollect_ignore.append("test_threshold_pin.py")\n'
    },
    "collect_ignore extended with +=": {
        "conftest": 'collect_ignore = []\ncollect_ignore += ["test_threshold_pin.py"]\n'
    },
    "collect_ignore annotated": {"conftest": 'collect_ignore: list = ["test_threshold_pin.py"]\n'},
    "collect_ignore bound twice": {
        "conftest": 'collect_ignore = ["a.py"]\ncollect_ignore = ["b.py"]\n'
    },
    "collect_ignore_glob in conftest.py": {"conftest": 'collect_ignore_glob = ["test_thr*.py"]\n'},
    "a collect_ignore pytest cannot be shown to read": {
        "conftest": "collect_ignore = [name for name in ()]\n"
    },
}


@pytest.mark.parametrize("shape", sorted(_NOT_COLLECTED))
def test_a_pin_pytest_does_not_run_through_these_collection_rules_is_not_credited(tmp_path, shape):
    violations = _polarity_violations(tmp_path, _PIN, **_NOT_COLLECTED[shape])
    assert violations, f"{shape}: credited a pin pytest does not run"


_STILL_COLLECTED = {
    "a local base without __init__": {
        "module_prefix": "class Base:\n    helper = 1\n\n\n",
        "class_header": "class TestPin(Base):",
    },
    "__test__ = True": {"class_header": "class TestPin:\n    __test__ = True"},
    "collect_ignore of another file": {"conftest": 'collect_ignore = ["other.py"]\n'},
    "an earlier different-name def": {"module_suffix": "\n\ndef test_other():\n    pass\n"},
}


@pytest.mark.parametrize("shape", sorted(_STILL_COLLECTED))
def test_collection_rules_still_credit_a_pin_pytest_does_run(tmp_path, shape):
    assert _polarity_violations(tmp_path, _PIN, **_STILL_COLLECTED[shape]) == [], shape


_DOCUMENTED_WRONG_REJECTS = {
    "path held in a variable": {
        "read": 'nb = RECIPE / "notebook.ipynb"\nsource = nb.read_text("utf-8")\n'
    },
    "module-level read": {
        "read": "",
        "assertion": 'assert "min_coverage" in SOURCE\n',
        "module_prefix": f'SOURCE = {_COMMITTED}.read_text("utf-8")\n\n\n',
    },
    "fixture that returns the read": {
        "read": "",
        "assertion": 'assert "min_coverage" in source\n',
        "module_prefix": "@pytest.fixture\n"
        f'def source():\n    return {_COMMITTED}.read_text("utf-8")\n\n\n',
    },
    "re.search": {"assertion": 'import re\nassert re.search("min_coverage", source)\n'},
    "find != -1": {"assertion": 'assert source.find("min_coverage") != -1\n'},
    "startswith": {"assertion": 'assert source.startswith("min_coverage")\n'},
    "tuple-unpacked read": {"read": f'source, n = {_COMMITTED}.read_text("utf-8"), 1\n'},
    "annotated read": {"read": f'source: str = {_COMMITTED}.read_text("utf-8")\n'},
    "walrus read": {"read": f'(source := {_COMMITTED}.read_text("utf-8"))\n'},
    "needle held in a name": {"assertion": 'needle = "min_coverage"\nassert needle in source\n'},
    "lower() inside the read statement": {
        "read": 'source = "".join(\n'
        '    "".join(c["source"])\n'
        f'    for c in json.loads({_COMMITTED}.read_text("utf-8"))["cells"]\n'
        '    if c["cell_type"].lower() == "code"\n)\n'
    },
    "assert under if": {"assertion": 'if source:\n    assert "min_coverage" in source\n'},
    "slug-shaped path argument": {
        "read": f'source = {_COMMITTED}.read_text("utf-8") + open("10-threshold").read()\n'
    },
}


@pytest.mark.parametrize("shape", sorted(_DOCUMENTED_WRONG_REJECTS))
def test_the_documented_wrong_rejects_are_refused_and_the_plain_shape_is_credited(tmp_path, shape):
    """docs/recipe-template.md "Limits of the check" lists these as refused, with the shape to use
    instead (#320). Pinning them here keeps that table true: if one starts being credited the docs
    must change, and if the plain shape stops being credited the guard has regressed."""
    options = dict(_DOCUMENTED_WRONG_REJECTS[shape])
    read = options.pop("read", f'source = {_COMMITTED}.read_text("utf-8")\n')
    assertion = options.pop("assertion", _PIN)
    refused = _polarity_violations(tmp_path / "refused", assertion, read=read, **options)
    assert refused, f"{shape}: documented as refused, but credited"
    assert _polarity_violations(tmp_path / "plain", _PIN) == []


def test_a_read_of_a_scratch_copy_or_a_longer_file_name_does_not_taint(tmp_path):
    """``open(tmp_path / "notebook.ipynb").read()`` reads a copy the test made, and
    ``expected_helpers.py`` is not ``helpers.py``: neither is the committed artefact."""
    assertion = 'assert "min_coverage" in source\n'
    reads = {
        "tmp_path copy": 'source = open(tmp_path / "notebook.ipynb", encoding="utf-8").read()\n',
        "tmp_path copy via a local": (
            'copy = tmp_path / "sub"\n'
            'source = (copy / "notebook.ipynb").read_text(encoding="utf-8")\n'
        ),
        "longer file name": 'source = open(RECIPE / "expected_helpers.py").read()\n',
    }
    for label, read in reads.items():
        violations = _polarity_violations(tmp_path / label.replace(" ", "_"), assertion, read=read)
        assert violations, f"{label}: credited a read that is not the committed artefact"


def test_the_effective_truth_sense_unit_cases():
    """Direct unit cases for ``_entailed_spellings``, the derivation the mutation tests above
    exercise end to end: each is (expression, truth the assert needs, spellings it entails)."""
    cases = [
        ('"x" in source', True, {"x"}),
        ('"x" in source', False, set()),
        ('"x" not in source', True, set()),
        ('"x" not in source', False, {"x"}),
        ('("x" in source) is False', True, set()),
        ('("x" in source) is False', False, {"x"}),
        ('not (("x" in source) is False)', True, {"x"}),
        ('source.count("x") == 0', True, set()),
        ('source.count("x") == 0', False, {"x"}),
        ('source.count("x") >= 1', True, {"x"}),
        ('source.count("x") >= 1', False, set()),
        ('"x" in source and "y" in source', True, {"x", "y"}),
        ('"x" in source and "y" in source', False, set()),
        ('"x" in source or "y" in source', True, set()),
        ('"x" in source or "x" in source', True, {"x"}),
        ('"x" not in source or "y" not in source', False, {"x", "y"}),
        ('("x" in source) if flag else True', True, set()),
        ('("x" in source) if flag else ("x" in source)', True, {"x"}),
        ('"x" in "hand typed"', True, set()),
        ('"x" in other', True, set()),
    ]
    for source_text, truth, expected in cases:
        expr = ast.parse(source_text, mode="eval").body
        got = _entailed_spellings(expr, truth, frozenset({"source"}), frozenset())
        assert got == expected, f"{source_text!r} (needs {truth}): {got} != {expected}"


@pytest.mark.parametrize("recipe", guarded("threshold_objective_pin"))
def test_the_threshold_objective_is_pinned_by_source_spelling(recipe):
    """#244: nothing pins a notebook's threshold-selection OBJECTIVE. A printed f-string literal
    beside the call (``print(f"objective: select_confidence_threshold(..., min_coverage=0.75)")``)
    is hand-written and nothing compares it to the call; a test asserting the resulting
    threshold *value* only pins the objective if no other objective can produce that value,
    which recipe 38's own pool demonstrated is not reliable (``min_coverage=0.75`` and
    ``target_accuracy=1.0`` select the identical threshold there, so swapping the call's keyword
    and leaving the value-pinning test in place left the full suite, the recipe guard, and the
    notebook-freshness check all green with the committed, printed objective line now false).

    What this check requires: for every real ``select_confidence_threshold(``/
    ``select_threshold(`` call this recipe's committed notebook or ``helpers.py`` actually makes
    (``_threshold_pin_obligations``, AST-found so a call-shaped string inside an unrelated
    f-string decoration is never mistaken for the real call, and resolved through a straight
    import alias so an aliased call is never silently invisible either), the objective it
    actually selects -- the keyword name, or the objective string -- must be PINNED somewhere in
    this recipe's tests: an assertion whose truth depends on a value that is, by data-flow
    tracing, really tied to the committed call (``_pinned_objective_spellings`` and the
    functions above it), not merely co-located with a string that happens to name the spelling.
    This recognises every shape the published set currently uses (a direct ``in``/``not in``
    against a read of the real source; an AST-extracted keyword value compared with ``==``; a
    ``.count(...) == n``; an f-string literal; a real production call tied, with a
    non-degeneracy check, to a local re-derivation) because it traces the PROPERTY -- "this
    assertion's truth depends on the real committed call" -- rather than enumerating spellings
    of it, which is exactly the defence CONTRIBUTING.md section 6 shows failing five times over
    for the same reason. A call this check cannot identify an objective for (not observed in the
    published set), or a cell/``helpers.py`` that does not parse as plain Python at all, fails
    here too, rather than being silently skipped.

    Limits (#320). CORRECTED, each with a mutation test (the refused shapes are the parametrised
    tests named for them): a write-mode or unreadable-mode ``open`` counted as a read; a value
    whose characters were rewritten (``.lower()`` and kin, also ``map(str.lower, ...)``,
    ``partial``, ``getattr``, ``methodcaller``); copies made by ``tempfile`` (aliased imports
    too) or the ``shutil`` copy family, including a bare ``shutil.copy(src, dst)`` statement;
    another recipe's ``notebook.ipynb`` (two and three digit folders); a ``def test_*`` in a file
    pytest does not collect or a ``collect_ignore`` names; ``__test__ = False``; an earlier def
    shadowed by a later one of the same name; an inherited ``__init__`` or ``__test__`` from a
    base class in the same file; a test that writes the committed file and reads it back. The
    extraction route's pooled literals are #338. RECORDED AS ACCEPTED (wrong-accepts: a bounded
    syntax analysis, and general callback, alias and returned-value tracking would enlarge the
    trusted code; the recipe's own real-call mutation test remains the evidence): needle
    provenance, a value that merely contains a read, a stored mutator callback or stored rewrite,
    a callable returned through ``get``, an alias that empties a collection, ``next(iter(mapping))``
    over values, copies under other roots, another recipe's folder named through a variable or
    a computed string, writes through a variable path, and collection switched off by a plugin or
    command line. DOCUMENTED wrong-rejects, each with the shape to use instead (a loud refusal,
    never a silent pass): a path held in a variable, a module-level read, a fixture that returns
    the read, ``re.search``, ``.find(...) != -1``, ``startswith``/``endswith``, tuple-unpacked,
    annotated and walrus reads, self-referencing rebinds, a hand-typed needle held in a name,
    ``unittest.TestCase`` not named ``Test*``, a nested ``Test*`` class, asserts under
    ``if``/``try``, a ``.lower()`` inside the read statement, a slug-shaped path argument, and a
    copy call in the read statement. The full tables are in docs/recipe-template.md."""
    violations = _objective_pin_violations(recipe_dir(recipe))
    if violations is None:
        pytest.skip(
            f"{recipe['slug']}: no select_confidence_threshold/select_threshold call in the "
            "committed notebook or helpers.py"
        )
    assert not violations, f"{recipe['slug']}: " + "; ".join(violations)


def _objective_pin_violations(recipe_dir_: Path) -> list[str] | None:
    """The whole ``threshold_objective_pin`` verdict for one recipe directory: ``None`` when it
    makes no threshold-selection call (the check does not apply), else the list of violations
    (empty means the recipe passes). Factored out of the parametrised test so the mutation tests
    below can run the SAME code path CI runs on a throwaway copy of a recipe."""
    obligations = _threshold_pin_obligations(recipe_dir_)
    if not obligations:
        return None
    pinned = _pinned_objective_spellings(recipe_dir_)
    violations = []
    for location, func_name, objective in obligations:
        if func_name == "<unparseable>":
            violations.append(
                f"{location}: does not parse as plain Python -- this check cannot verify any "
                "threshold call here (an IPython magic, or a real syntax error?)"
            )
            continue
        if objective is None:
            violations.append(
                f"{location} {func_name}(...): objective not identifiable by this check"
            )
            continue
        if not any(_objective_token_present(objective, needle) for needle in pinned):
            violations.append(
                f"{location} {func_name}(...): objective {objective!r} is not pinned by any "
                "assertion in tests/ that this check can tie to the real committed call. Credited "
                "routes: (1) an assert that CLAIMS the spelling is present in a value derived "
                "from a read of the committed notebook.ipynb / helpers.py (not a tmp_path copy) "
                'or from inspect.getsource(helpers.<fn>); (2) `name = _your_helper(source, "lit", ...)` '
                "through a function defined in the test file, where `name` is bound exactly once "
                "in the test, by an unconditional top-level assignment, and a later top-level "
                "`assert name is not None` (or `None is not name`) that always runs follows (nothing "
                "between the assignment and the assert may end the test: no return, raise or "
                "pytest.skip; an assert inside `with` is not credited here); the first argument is "
                "the tainted source Name, every other argument a plain positional string "
                "literal, and no keyword arguments; and the literals together name exactly ONE "
                'objective spelling by whole-token match (two spellings, such as "f1" with '
                '"min_coverage", or "f1-gate" with another spelling, are refused); '
                "(3) a production call tied by `==` "
                "to a local re-derivation, with a `!=` assert against a sibling objective. "
                "`is False`, `.count(...) == 0` and a hand-typed copy of the needle in the "
                "compared value do not count. Only asserts that run count: directly in a "
                "`test_` function pytest collects (module-level, or in a `Test*` class without "
                "`__init__`; not skip/skipif/xfail-marked, not in a file that skips itself, not "
                "nested), inside `with open(...)`, or in a `for` over a non-empty literal "
                "tuple/list/set, up to the first return/raise/pytest.skip -- not under `if`, "
                "`try`, another loop, or `pytest.raises`. See docs/recipe-template.md "
                '("Pin the threshold\'s OBJECTIVE")'
            )
    return violations


# --------------------------------------------------------------------------------------------
# check: a recipe that gates on confidence freezes the gate through the shared helper (#282)
# --------------------------------------------------------------------------------------------


def _shared_gate_freezes(helpers_tree: ast.Module, notebook: list[ast.Module]) -> list[str]:
    """Locations of every call that freezes a confidence gate through the shared helper: a call to
    ``select_confidence_threshold`` imported by name from ``jev_cookbook.evaluation`` (under any
    alias, and not rebound by a local definition), whose result is used -- returned, passed on, or
    assigned to a name something reads. A bare call statement, a result stored and never read, a
    look-alike defined in the recipe, and a call written through a module attribute are not
    credited. ``select_threshold`` is not credited either: it picks a Noul business threshold,
    not the gate (a Noul gate is ``select_confidence_threshold`` over ``noul_confidence``)."""
    units = {"helpers.py": [helpers_tree], "notebook": notebook}
    everything = [helpers_tree, *notebook]
    read = {
        _identifier(node)
        for tree in everything
        for node in ast.walk(tree)
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load)
    }
    found: list[str] = []
    for unit, trees in units.items():
        selectors = _shared_selector_imports(trees)
        for tree in trees:
            parents = _parents(tree)
            for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
                if not (
                    isinstance(call.func, ast.Name)
                    and selectors.get(call.func.id) == "select_confidence_threshold"
                ):
                    continue
                parent = parents.get(call)
                if isinstance(parent, ast.Expr):
                    continue
                if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                    targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
                    if all(isinstance(t, ast.Name) for t in targets) and not any(
                        t.id in read for t in targets
                    ):
                        continue
                found.append(f"{unit} line {call.lineno}")
    return found


def _gate_freeze_verdict(recipe_dir_: Path, slug: str) -> tuple[str, str]:
    """``("ok" | "not-applicable" | "skip" | "fail", message)`` for one recipe directory: the whole
    ``confidence_gate_from_shared_helper`` verdict, factored out for the mutation and table
    tests, which run the SAME code path CI runs on a throwaway recipe. ``not-applicable`` is a
    recipe with no gate (a pass); ``skip`` is a recipe named in ``GATE_FREE_DESIGNS``, reported
    with its reason exactly as ``review_reason_string`` reports it."""
    try:
        helpers_tree = ast.parse((recipe_dir_ / "helpers.py").read_text("utf-8"))
    except (OSError, SyntaxError) as error:
        return "fail", f"{slug}: helpers.py cannot be read as Python ({error})"
    notebook, unparseable = _notebook_code_trees(recipe_dir_)
    if unparseable:
        return "fail", (
            f"{slug}: notebook code cell(s) {unparseable} do not parse as plain Python, so this "
            "check cannot see whether a confidence gate is frozen through the shared helper"
        )
    gated_in = _live_gate_locations(helpers_tree, notebook)
    named = _gate_free_verdict(slug, gated_in, "this check")
    if named is not None:
        return named
    if not gated_in:
        return "not-applicable", (
            f"{slug}: no confidence is compared with a bound (an argument range check is not one) "
            "in helpers.py or any notebook code cell, and no live branch produces a "
            "confidence-gated review's reason, so nothing is gated and there is no gate to freeze"
        )
    if _shared_gate_freezes(helpers_tree, [tree for _, tree in notebook]):
        return "ok", ""
    return "fail", (
        f"{slug}: this recipe gates on confidence ({', '.join(gated_in)}) but freezes no gate "
        "through the shared helper. Choose the gate with `select_confidence_threshold(...)`, "
        "imported by name (`from jev_cookbook.evaluation import select_confidence_threshold`) and "
        "used, never a constant or a hand-picked number (CONTRIBUTING.md section 4, "
        "docs/evaluation.md 'Selective prediction'). A hardcoded gate, a call through a module "
        "attribute and a look-alike function are invisible to threshold_objective_pin, "
        "stored_answers_strong_form and review_reason_string, which skip when they find no call, "
        "so they would pass the recipe without checking it"
    )


@pytest.mark.parametrize("recipe", guarded("confidence_gate_from_shared_helper"))
def test_a_confidence_gate_is_frozen_through_the_shared_helper(recipe):
    """#282: two checks (``threshold_objective_pin`` and ``stored_answers_strong_form``) key on
    finding a RESOLVABLE ``select_confidence_threshold(``/``select_threshold(`` call and skip when
    they find none -- the quietest possible outcome, which reads as a pass -- and the third
    (``review_reason_string``, before #227) only searched text. A recipe that freezes its gate as
    a bare constant (``GATE = 0.85``) or through a call the finder does not resolve
    (``evaluation.select_...``) therefore removes all three. Widening the finder is the wrong direction (this repository
    has five findings about checks keyed on source idioms, and #276 tracks the same problem in
    the adjacent machinery); making the skips fail closed would turn every genuinely gate-free
    recipe red. The distinction the guard needs is between NO gate and an UNSEEN gate, and only
    a positive requirement supplies it: a recipe that gates on confidence must freeze the gate
    through the shared helper, so "no resolvable call" afterwards means "no gate".

    Whether a recipe gates is decided by what it does, not by how it froze the number: executable
    code that compares a confidence with a bound a recipe chooses, or produces the
    confidence-gated review's reason (``_live_gate_locations``, the predicate
    ``review_reason_string`` applies too; an argument range check such as ``0.0 <= min_confidence
    <= 1.0`` is not a gate). A recipe with neither passes: there is nothing to freeze. A recipe
    named in ``GATE_FREE_DESIGNS`` (published recipe 28, the one recipe with no gate today) is not
    applicable to this check either, a skip carrying the entry's reason, and fails if it has since
    grown a live gate.
    A recipe with one passes by a used call to ``select_confidence_threshold`` imported from
    ``jev_cookbook.evaluation`` in its notebook OR in a wrapper in ``helpers.py``
    (``_shared_gate_freezes``), so factoring the call behind a named function is accepted -- the
    finder the three skipping checks share already reads both files. The three skip conditions
    are deliberately left as they are: this is what makes them sound.

    What it does not establish, said once: that the number frozen is the number the rule's
    confidence parameter receives. A recipe with a shared-helper call AND a separate hardcoded
    gate passes this check; ``threshold_objective_pin`` and the recipe's own consequence tests
    are what bind the objective to the call, and a dataflow from the call to the rule is a
    larger instrument than this positive requirement was filed to be."""
    status, message = _gate_freeze_verdict(recipe_dir(recipe), recipe["slug"])
    if status == "skip":
        pytest.skip(message)
    assert status in ("ok", "not-applicable"), message


# --- #282: a gate that gates must be frozen through the shared helper ----------------------------

_IMPORT_SHARED = "from jev_cookbook.evaluation import select_confidence_threshold"

_FREEZE_PASSES = {
    "call-in-the-notebook": (_GATE_HELPERS, _GATE_CELLS),
    "aliased-import": (
        _GATE_HELPERS,
        [
            (
                "from jev_cookbook.evaluation import select_confidence_threshold as pick\n"
                "gate = pick(ok, conf, min_coverage=0.5)\n"
                "print(gate)\n",
                "",
            )
        ],
    ),
    "wrapper-in-helpers-the-notebook-calls": (
        _GATE_HELPERS
        + """
def choose_gate(correct, confidence):
    return select_confidence_threshold(correct, confidence, min_coverage=0.5)
""",
        [("gate = helpers.choose_gate(ok, conf)\nprint(helpers.route(answer, gate))\n", "")],
    ),
    "result-passed-straight-on": (
        _GATE_HELPERS,
        [
            (
                f"{_IMPORT_SHARED}\n"
                "print(helpers.route(answer, select_confidence_threshold(ok, conf, min_coverage=0.5)))\n",
                "",
            )
        ],
    ),
    "no-gate-anywhere": (
        "def total(xs):\n    return sum(xs)\n",
        [("print(helpers.total([1, 2]))\n", "")],
    ),
}


@pytest.mark.parametrize("shape", sorted(_FREEZE_PASSES))
def test_a_gate_frozen_through_the_shared_helper_or_no_gate_passes(tmp_path, shape):
    helpers, cells = _FREEZE_PASSES[shape]
    folder = _gate_recipe(tmp_path, helpers, cells)
    status, message = _gate_freeze_verdict(folder, "synthetic")
    assert status in ("ok", "not-applicable"), message
    assert (status == "not-applicable") == (shape == "no-gate-anywhere")


_FREEZE_FAILS = {
    "bare-constant": (
        _GATE_HELPERS,
        [("GATE = 0.85\nprint(helpers.route(answer, GATE))\n", "")],
    ),
    "constant-and-the-import-left-unused": (
        _GATE_HELPERS,
        [(f"{_IMPORT_SHARED}\nGATE = 0.85\nprint(helpers.route(answer, GATE))\n", "")],
    ),
    "call-through-a-module-attribute": (
        _GATE_HELPERS,
        [
            (
                "from jev_cookbook import evaluation\n"
                "gate = evaluation.select_confidence_threshold(ok, conf, min_coverage=0.5)\n"
                "print(helpers.route(answer, gate))\n",
                "",
            )
        ],
    ),
    "look-alike-defined-in-the-recipe": (
        _GATE_HELPERS
        + """
def select_confidence_threshold(correct, confidence, **kwargs):
    return 0.85
""",
        [
            (
                "gate = helpers.select_confidence_threshold(ok, conf)\nprint(helpers.route(answer, gate))\n",
                "",
            )
        ],
    ),
    "look-alike-defined-in-the-notebook": (
        _GATE_HELPERS,
        [
            (
                f"{_IMPORT_SHARED}\n"
                "def select_confidence_threshold(correct, confidence, **kwargs):\n"
                "    return 0.85\n"
                "gate = select_confidence_threshold(ok, conf)\n"
                "print(helpers.route(answer, gate))\n",
                "",
            )
        ],
    ),
    "call-result-thrown-away": (
        _GATE_HELPERS,
        [
            (
                f"{_IMPORT_SHARED}\nselect_confidence_threshold(ok, conf, min_coverage=0.5)\nprint(helpers.route(answer, 0.85))\n",
                "",
            )
        ],
    ),
    "call-result-stored-and-never-read": (
        _GATE_HELPERS,
        [
            (
                f"{_IMPORT_SHARED}\nunused = select_confidence_threshold(ok, conf, min_coverage=0.5)\nprint(helpers.route(answer, 0.85))\n",
                "",
            )
        ],
    ),
    "the-business-threshold-function-is-not-the-gate": (
        _GATE_HELPERS,
        [
            (
                "from jev_cookbook.evaluation import select_threshold\n"
                "t = select_threshold(gold, noul, 'f1')\n"
                "print(helpers.route(answer, t))\n",
                "",
            )
        ],
    ),
    "gate-seen-only-through-the-reason-it-produces": (
        # no confidence is compared anywhere in the recipe's code: the gate is a flag the
        # notebook sets from a number that is not named confidence. Only the live reason says
        # that this recipe has a confidence-gated review at all.
        """
        def route(decision):
            if decision.gated:
                return "review", "confidence below the threshold"
            return decision.label, "ok"
        """,
        [("d = helpers.Decision('a', answer.score < 0.85)\nprint(helpers.route(d))\n", "")],
    ),
    "a-real-hardcoded-gate-beside-an-argument-range-check": (
        """
        def route(answer, min_confidence):
            if not 0.0 <= min_confidence <= 1.0:
                raise ValueError("min_confidence out of range")
            if answer.confidence < 0.85:
                return "review", "confidence below the threshold"
            return answer.choice, "ok"
        """,
        [("print(helpers.route(answer, 0.85))\n", "")],
    ),
    "gate-in-the-notebook-only": (
        "def total(xs):\n    return sum(xs)\n",
        [("kept = [a for a in answers if a.confidence >= 0.85]\nprint(kept)\n", "")],
    ),
}


@pytest.mark.parametrize("shape", sorted(_FREEZE_FAILS))
def test_a_gate_not_frozen_through_the_shared_helper_fails_naming_the_requirement(tmp_path, shape):
    helpers, cells = _FREEZE_FAILS[shape]
    folder = _gate_recipe(tmp_path, helpers, cells)
    status, message = _gate_freeze_verdict(folder, "synthetic")
    assert status == "fail", message
    # the message names the requirement, not a shape
    assert "freezes no gate through the shared helper" in message
    assert "select_confidence_threshold" in message and "jev_cookbook.evaluation" in message


def test_a_gate_the_helper_call_in_helpers_never_reaches_is_not_credited_from_another_unit(
    tmp_path,
):
    """An import in one file does not credit a call in the other: each unit is judged against its
    own imports, so a look-alike in ``helpers.py`` is not rescued by the notebook's import."""
    helpers = (
        _GATE_HELPERS
        + """
def select_confidence_threshold(correct, confidence, **kwargs):
    return 0.85

def choose_gate(correct, confidence):
    return select_confidence_threshold(correct, confidence)
"""
    )
    folder = _gate_recipe(
        tmp_path,
        helpers,
        [(f"{_IMPORT_SHARED}\nunused = 1\ngate = helpers.choose_gate(ok, conf)\n", "")],
    )
    status, _ = _gate_freeze_verdict(folder, "synthetic")
    assert status == "fail"


_RANGE_CHECK_ONLY = {
    "chained-between-zero-and-one": "if not 0.0 <= min_confidence <= 1.0:\n        raise ValueError('x')",
    "upper-bound-only": "if min_confidence > 1:\n        raise ValueError('x')",
    "lower-bound-only": "if min_confidence < 0.0:\n        raise ValueError('x')",
    "assert": "assert 0 <= min_confidence <= 1",
    "assert-single-bound": "assert min_confidence >= 0",
}

_GATES_THAT_ARE_NOT_RANGE_CHECKS = {
    "literal-gate-in-a-filter": "kept = [a for a in answers if a.confidence >= 0.85]",
    "literal-gate-that-raises": "if answer.confidence < 0.5:\n        raise ValueError('abstain')",
    "named-gate": "keep = answer.confidence >= gate",
    "gate-in-a-branch": "if answer.confidence < gate:\n        return None",
    "range-check-whose-bound-is-a-name": "if not gate <= answer.confidence <= ceiling:\n        return None",
}


def _function_with(line: str) -> str:
    return (
        f"def check(answer, min_confidence=0.5, gate=0.5, ceiling=1.0, answers=()):\n    {line}\n"
    )


@pytest.mark.parametrize("shape", sorted(_RANGE_CHECK_ONLY))
def test_an_argument_range_check_is_not_a_gate(tmp_path, shape):
    """Recipe 42 validates ``0.0 <= min_confidence <= 1.0`` before it gates, and so can any recipe
    that takes a gate as an argument. A comparison that only bounds a parameter by 0 and 1 is not a
    gate, so a recipe whose only such comparison is a range check has none to freeze -- the
    applicability the two checks share. Before they shared it, ``confidence_gate_from_shared_
    helper`` told a recipe named in ``GATE_FREE_DESIGNS`` to freeze a gate it did not have."""
    source = _function_with(_RANGE_CHECK_ONLY[shape])
    assert _live_gate_locations(ast.parse(source), []) == []
    folder = _gate_recipe(tmp_path, source, [("print(helpers.check(answer))\n", "")])
    # named gate-free: both checks are not applicable, and say why
    for verdict in (_reason_string_verdict, _gate_freeze_verdict):
        status, message = verdict(folder, "28-skill-selection")
        assert status == "skip" and "named gate-free design" in message, (verdict, message)
    # unnamed: no gate to freeze passes; no gate and no named design is the reason check's absence
    assert _gate_freeze_verdict(folder, "some-new-recipe")[0] == "not-applicable"
    status, message = _reason_string_verdict(folder, "some-new-recipe")
    assert status == "fail" and "GATE_FREE_DESIGNS" in message


@pytest.mark.parametrize("shape", sorted(_GATES_THAT_ARE_NOT_RANGE_CHECKS))
def test_a_comparison_that_is_not_a_range_check_is_still_a_gate(tmp_path, shape):
    source = _function_with(_GATES_THAT_ARE_NOT_RANGE_CHECKS[shape])
    assert _live_gate_locations(ast.parse(source), []) == ["helpers.py"]
    folder = _gate_recipe(tmp_path, source, [("print(helpers.check(answer))\n", "")])
    status, message = _gate_freeze_verdict(folder, "some-new-recipe")
    assert status == "fail" and "freezes no gate through the shared helper" in message
    # and a named gate-free design that has grown one is held to the check, not excused by it
    status, message = _gate_freeze_verdict(folder, "28-skill-selection")
    assert status == "fail" and "remove the entry" in message


def test_recipe_42s_own_range_check_does_not_make_a_gate_free_recipe_gated(tmp_path):
    """The mutation on a published recipe the reviewer asked for. Recipe 42 has exactly this line
    in ``verdict_for_rule``. Delete its real gate branch (the confidence comparison and the reason
    it returns), keep the range check, and call the result a named gate-free design: the shared
    predicate finds no gate, so both checks are not applicable. On the previous predicate (any
    ordering comparison naming a confidence) ``confidence_gate_from_shared_helper`` found the
    range check, called it a gate, and failed the recipe for freezing nothing."""
    source = (RECIPES_DIR / "42-outbound-disclosure-screening" / "helpers.py").read_text("utf-8")
    gate = (
        "    confidence = noul_confidence([noul])[0]\n"
        "    if confidence < min_confidence:\n"
        '        return RuleVerdict(rule, REVIEW, noul, "confidence below the threshold")\n'
    )
    assert source.count(gate) == 1
    assert "if not 0.0 <= min_confidence <= 1.0:" in source
    folder = _gate_recipe(
        tmp_path,
        source.replace(gate, ""),
        [("print(helpers.verdict_for_rule('r', 0.5, 0.5, 0.5))\n", "")],
    )
    assert _compares_confidence(ast.parse((folder / "helpers.py").read_text("utf-8")))
    for verdict in (_reason_string_verdict, _gate_freeze_verdict):
        status, message = verdict(folder, "28-skill-selection")
        assert status == "skip" and "named gate-free design" in message, (verdict, message)
    # restore the gate and the same slug is held to both checks
    folder = _gate_recipe(
        tmp_path / "gated", source, [("print(helpers.verdict_for_rule('r', 0.5, 0.5, 0.5))\n", "")]
    )
    for verdict in (_reason_string_verdict, _gate_freeze_verdict):
        status, message = verdict(folder, "28-skill-selection")
        assert status == "fail" and "remove the entry" in message, (verdict, message)


def test_a_hardcoded_gate_in_a_published_recipe_is_caught_where_three_checks_skip(tmp_path):
    """The mutation proof on a published recipe (01), and the FAIL->SKIP conversion the issue
    measured: convert the notebook's helper call to a constant and show what each check says.
    The objective pin skips (no call to find), the strong-form check skips (no frozen
    threshold), the reason-string check is green -- the quietest possible outcome -- and the new
    check is red, naming the requirement."""
    folder = _copy_recipe(tmp_path, "01-sentiment-classification")
    assert _gate_freeze_verdict(folder, "01") == ("ok", "")
    _edit_notebook_code(
        folder,
        "threshold = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)",
        "threshold = 0.85",
    )
    assert _objective_pin_violations(folder) is None  # threshold_objective_pin: skips
    assert _threshold_pin_obligations(folder) == []  # stored_answers_strong_form: skips
    assert _reason_string_verdict(folder, "01")[0] == "ok"  # review_reason_string: green
    status, message = _gate_freeze_verdict(folder, "01")
    assert status == "fail"
    assert "freezes no gate through the shared helper" in message and "helpers.py" in message


def test_a_hardcoded_gate_behind_a_helpers_wrapper_is_caught(tmp_path):
    """Recipe 31 freezes its gate only in a ``helpers.py`` wrapper (its notebook calls the wrapper),
    which the check accepts; replace the wrapper's call with a constant and it fails."""
    folder = _copy_recipe(tmp_path, "31-patch-risk-triage")
    assert _gate_freeze_verdict(folder, "31") == ("ok", "")
    _edit_text(
        folder / "helpers.py",
        "    return select_confidence_threshold(correct, confidence, min_coverage=MIN_COVERAGE)",
        "    return 0.85",
    )
    status, message = _gate_freeze_verdict(folder, "31")
    assert status == "fail" and "freezes no gate through the shared helper" in message


def test_a_genuinely_gate_free_published_recipe_is_not_applicable(tmp_path):
    """Recipe 28 compares no confidence with a bound anywhere, so there is no gate to freeze: under
    an unnamed slug it passes as having none, and under its own it is the named gate-free design,
    skipped with the entry's reason -- the same fact ``GATE_FREE_DESIGNS`` records for the
    reason-string check."""
    status, message = _gate_freeze_verdict(RECIPES_DIR / "28-skill-selection", "28")
    assert status == "not-applicable" and "nothing is gated" in message
    status, message = _gate_freeze_verdict(RECIPES_DIR / "28-skill-selection", "28-skill-selection")
    assert status == "skip" and "named gate-free design" in message


# --------------------------------------------------------------------------------------------
# check: every Noul proposition a recipe's own code builds has a gold-true and gold-false row
# in every scored split (#283)
# --------------------------------------------------------------------------------------------


def _noul_propositions(recipe_dir_: Path) -> dict[str, list[str]]:
    """Every ``Noul`` proposition this route can reach in the recipe's own code, as ``{name: [the
    function(s) that produced it]}``. Not "every proposition the recipe builds": a builder that
    requires an argument is never called (recipe 39's ``build_stage2_questions(which)`` is the
    known case -- see the module docstring). Discovery calls every function ``helpers.py`` defines (not
    one it merely imports) that can be called with no arguments, and keeps the ``Noul``-valued
    entries of any dict it returns. The name is the dict key the recipe's own code assigns --
    the same key ``labels.jsonl`` must carry that proposition's gold value under -- never a
    spelling this check searches for or guesses.

    Calling an arbitrary zero-argument function is safe here only because it was MEASURED to be
    on today's published set, not because any contract says so (CONTRIBUTING.md makes no such
    promise): 51 function calls across 49 published recipes plus the template opened no file,
    wrote no output and raised nothing; the calls took about 0.015s, the whole sweep including
    ``load_helpers`` for all 50 modules about 0.2s. They are not all question
    builders: 36's ``enumerate_game_space`` (a brute-force search over card permutations, the
    one call that does real work -- 13ms at today's ``N_CARDS``, but its cost is bounded by
    nothing this check controls), 43's private ``_new_budget`` and ``worst_case_step_bound``,
    44's ``approve_all_outcome``/``reject_all_outcome``/``always_review_outcome``, 48's
    ``always_consistent_baseline``, and 40's ``build_department_question``/
    ``build_flat_question`` (two builders returning a bare ``Choice``, not a dict) are all
    called, and a function that does not return a ``{name: Noul(...)}`` mapping simply
    contributes nothing. A function that requires an argument is not called. A function that
    raises is skipped, not a failure of this check -- which makes a raising builder
    indistinguishable from a recipe that genuinely builds fewer than two propositions, the same
    root cause as the argument-taking case."""
    helpers = load_helpers(recipe_dir_, reload=True)
    props: dict[str, list[str]] = {}
    for name, obj in vars(helpers).items():
        if not inspect.isfunction(obj) or obj.__module__ != helpers.__name__:
            continue  # imported into helpers.py, not defined there
        try:
            sig = inspect.signature(obj)
        except (TypeError, ValueError):
            continue
        if any(
            param.default is inspect.Parameter.empty
            and param.kind
            in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
            for param in sig.parameters.values()
        ):
            continue  # needs an argument this check does not have -- not a question builder
        try:
            result = obj()
        except Exception:
            continue
        if not isinstance(result, dict):
            continue
        for key, value in result.items():
            if isinstance(value, Noul):
                props.setdefault(key, []).append(name)
    return props


def _noul_gold_value(label: object, prop: str) -> tuple[bool, bool | None]:
    """``(found, value)`` for proposition ``prop``'s gold value under one ``labels.jsonl`` row's
    ``label``. Handles every shape the published multi-proposition ``Noul`` recipes actually
    use: a flat ``{prop: bool, ...}`` mapping (26, 41, 42, 44, 48); one level of nesting,
    ``{"features": {prop: bool, ...}, ...}`` (35); and set-valued gold, a list naming the
    propositions that are true, where membership stands for the value and an absent name is a
    recorded ``False`` (06, 37). Finding none of these shapes reports ``found=False`` rather
    than guessing; such a row contributes nothing to either truth value, which is exactly what
    this check is required to notice (a proposition it cannot read gold for is not evidence that
    a gold-true or gold-false row exists)."""
    if isinstance(label, dict):
        if prop in label:
            return True, bool(label[prop])
        for value in label.values():
            if isinstance(value, dict) and prop in value:
                return True, bool(value[prop])
        return False, None
    if isinstance(label, list):
        return True, prop in label
    return False, None


def _noul_gold_gaps(recipe_dir_: Path) -> tuple[dict[str, list[str]], list[str]]:
    """``(propositions, gaps)`` for one recipe. ``gaps`` names every ``split/proposition`` pair
    among ``jev_cookbook.fixtures.REQUIRED_SPLITS`` (``validation``, ``test`` -- the module's
    own rule that ``demo`` is never scored, not a spelling repeated here) for which
    ``labels.jsonl`` carries no gold-true row, no gold-false row, or neither. Returns
    ``(propositions, [])`` immediately, with no fixture read at all, when fewer than two
    propositions are reached: #283 is about the multi-proposition battery, and a single
    proposition's gold is often recorded with no proposition key for ``_noul_gold_value`` to
    read (see the module docstring)."""
    props = _noul_propositions(recipe_dir_)
    if len(props) < 2:
        return props, []
    inputs = jc_fixtures.load_inputs(recipe_dir_)
    labels = jc_fixtures.load_labels(recipe_dir_)
    split_of = {example.id: example.split for example in inputs}
    seen: dict[tuple[str, str], set[bool]] = {}
    for example_id, label in labels.items():
        split = split_of.get(example_id)
        if split not in jc_fixtures.REQUIRED_SPLITS:
            continue
        for prop in props:
            found, value = _noul_gold_value(label, prop)
            if found:
                seen.setdefault((split, prop), set()).add(value)
    gaps = []
    for split in jc_fixtures.REQUIRED_SPLITS:
        for prop in props:
            values = seen.get((split, prop), set())
            missing = [v for v in (True, False) if v not in values]
            if missing:
                missing_words = "/".join("true" if m else "false" for m in missing)
                gaps.append(
                    f"{split}/{prop}: no gold-{missing_words} row (saw only {sorted(values)})"
                )
    return props, gaps


@pytest.mark.parametrize("recipe", guarded("noul_proposition_gold_coverage"))
def test_every_noul_proposition_has_gold_true_and_false_in_each_scored_split(recipe):
    """#283: recipe 48's review measured, on its merged fixtures, that ``breaks_reference`` had
    zero gold positives in validation -- no row where its tag could change a composed outcome,
    no row from which ``select_threshold`` could choose that proposition's threshold, so the
    recipe's own declared "the F1 sweep is degenerate" limitation was a symptom of the fixture
    gap rather than an independent fact about the task. #283's issue is silent on this: an issue
    that names propositions but not the combinations and polarities their gold must cover left
    it to chance, and it reached a builder only through an orchestration brief rather than
    through the issue itself. This check makes the mechanical half of that requirement --
    "every proposition gets a gold-true and a gold-false row in every scored split" -- a CI
    property instead of a brief.

    A recipe in which fewer than two ``Noul`` propositions are reached is skipped (not passed):
    either it builds fewer than two, so the battery property #283 is about does not reach it, or
    it builds them where zero-argument discovery cannot call (recipe 39), and this check does
    not substitute for whatever the recipe's own evidence requires. See ``_noul_propositions`` for how
    propositions are discovered (by calling the recipe's own code, never by name) and
    ``_noul_gold_value`` for the gold-reading shapes this recognises."""
    props, gaps = _noul_gold_gaps(recipe_dir(recipe))
    if len(props) < 2:
        pytest.skip(
            f"{recipe['slug']}: no two Noul propositions reachable by zero-argument discovery "
            f"(found {sorted(props)}); a recipe whose question builder requires an argument "
            "is not reached, and a builder that raises is not told apart from one that is absent"
        )
    assert not gaps, f"{recipe['slug']}: " + "; ".join(gaps)


# --------------------------------------------------------------------------------------------
# check: the notebook actually executes its simulated side effect (#212)
# --------------------------------------------------------------------------------------------
#
# Check id ``simulated_side_effect_invoked``. The gap it closes: a recipe's helper can be
# well tested while the committed notebook no longer calls it (delete the ``submit_reviews``
# call from recipe 24's ``eval-test`` cell, re-execute, commit: every other check stays green,
# on a notebook whose prose claims a queue its output no longer shows).
#
# Identification rule (written down, because the issue asks for it): the guard parses the
# notebook's code cells with ``ast`` and walks only code that can execute -- it does not see
# comments or strings, skips the body of a function nobody calls, a lambda, an ``if False:`` /
# ``while False:`` branch, a loop over an empty literal, and statements after a top-level
# ``raise``. In that live code it counts CALL SITES (distinct source positions, not runtime
# calls), each under a stable key:
#
# * ``helpers.<fn>``: a call to a function of the recipe's ``helpers.py`` that is a side-effect
#   function -- one whose body, directly or through other ``helpers.py`` functions and methods,
#   calls a mutating method (``submit``, ``resolve``, ``record``, ``put``, ``delete``,
#   ``rollback``, ``run``, ``step``, ``replay``) on a parameter, a local, ``self`` or a
#   module-level object, mutates a ``self.<attr>`` container, writes to module-level state
#   (``NAME[k] = v``, ``NAME.attr = v``, ``NAME.append(...)``, ``del NAME[k]``, or a
#   ``global NAME`` rebinding), or calls one of the shared ``jev_cookbook.simulation`` fill
#   helpers.
# * ``helpers.<Class>.<method>``: a public side-effect method called on a name bound to
#   ``helpers.<Class>(...)`` (or chained on the constructor call). A class is a side-effect
#   class when it subclasses ``Simulator`` / ``ToyGrid`` (``step`` and ``replay`` are then its
#   methods) or one of its public methods is a side-effect function in the sense above. A name
#   bound to a FACTORY holds the same thing: a function (or classmethod) of ``helpers.py``, or
#   one the notebook defines, whose returned value is built by a sink, a simulator or a
#   ``helpers.py`` class (``sim = helpers.new_game(seed)``, then ``sim.step(...)``) is keyed under
#   the class it returns (``helpers.Game.step``), not under the factory's own name.
# * ``<Sink>.<method>``: a mutating method called on a name the notebook bound to a
#   ``jev_cookbook.simulation`` sink (``ReviewQueue.submit``, ``ActionLog.record``,
#   ``Store.put``, ``Transactor.run``) or to a ``Simulator`` subclass (``ToyGrid.step``, or a
#   subclass the notebook itself defines).
# * ``fill_review_queue`` / ``record_actions`` / ``route_outcomes`` called directly.
#
# A function the notebook defines itself counts for what its body calls, but only if live code
# calls it.
#
# The declaration. Every recipe that has a simulated side effect states, in a file inside its
# own folder, ``side_effects.json`` (schema in ``docs/simulation.md``), exactly how many call
# sites of each key its notebook has, or that it has none and why. A recipe pull request can
# edit that file, so the builder's claim is in the diff for the reviewer, and the guard compares
# the notebook with the claim in both directions (fewer sites than declared is M15; more is an
# undeclared side effect). The 50 recipes published before this check keep their declarations
# in ``SIDE_EFFECT_INVENTORY`` below (migration: a published recipe's folder is not touched by
# the foundation pull request that added the check); a ``side_effects.json`` beside a recipe
# overrides its inventory entry.
#
# Fail closed. A recipe with no declaration FAILS when anything is detected (a sink, a side-effect
# function or class, a simulator) or when it is a recipe that needs a simulator
# (``SIMULATOR_RANKS``, from the open ``needs: simulator`` issues): detecting nothing in one of
# those fails too, because an applicable shape the analysis cannot see must be reported, not
# passed. Only a recipe with no declaration, nothing detected and no simulator need is skipped,
# with a message. Every detected side-effect function or class must also be used by the
# notebook (directly or through another helper it uses), every sink or simulator the notebook
# builds must be mutated or handed to a side-effect function, and a code cell that does not
# parse fails. A sink built through a factory that only constructs it (``helpers.new_grid(0)``)
# is held to the same rule as a direct construction. The one exemption: a name bound to the
# result of a ``helpers.py`` side-effect function that returns the object
# (``sim = helpers.run_episode(...)``), or of a notebook function whose body already executed a
# side effect, may only be read, because that function may have done the work. A function the
# notebook defines that builds an object and returns it credits the object to its caller: the
# caller's name must then be mutated (or be such an exempt result).
#
# ``not_side_effects`` (#327). A declaration may exempt a ``helpers.py`` function or class that
# only keeps bookkeeping, each entry with a reason. The exemption is checked mechanically: an
# entry whose code writes to a sink or a simulator (a mutating method on a parameter, a local,
# ``self`` or a module-level object, a shared fill helper, directly or through other
# ``helpers.py`` code) or that subclasses ``Simulator`` / ``ToyGrid`` is refused, and its side
# effect has to be declared under ``sites``. A write to a container of the class's own, or to
# module-level state, stays exemptable.
#
# Known limits: a site reached only through a container of callables, an attribute chain on an
# object that is not ``self``, a module-level name or a name the notebook bound
# (``a.b.queue.submit``), or an alias of a helper (``f = helpers.submit_reviews; f(...)``) is not
# seen -- the last one makes the count smaller than the declaration, so it fails closed -- and a
# condition the analysis cannot evaluate statically is assumed to be taken. Routing callbacks
# passed to the shared helpers are not analysed; they must be free of side effects
# (docs/simulation.md). A write to a container through a parameter or a local alias
# (``g = GRAPH; g[k] = v``, ``def f(d): d[k] = v``) or through ``setattr`` / ``globals()`` is not
# seen; a write to a file or the environment is not a simulated side effect; state kept in a
# container of its own, or in module-level state, that a recipe lists under ``not_side_effects``
# is accepted, because the guard cannot tell a cache from a graph held in a dict, so a reviewer
# reads each entry and its reason; and the exempt factory result above is not checked for
# mutation, so a side-effect function that returns a simulator it never steps goes unnoticed
# (the declared sites are what bind it). For a ``needs: simulator`` recipe the guard requires that a side effect be declared
# and executed, not that the declared key is the recipe's main one: the reviewer checks that the
# declared sites are the trajectory, transaction or actuation the recipe is about.

SIDE_EFFECT_SINKS = {
    "ReviewQueue": frozenset({"submit", "resolve"}),
    "ActionLog": frozenset({"record"}),
    "Store": frozenset({"put", "delete", "rollback"}),
    "Transactor": frozenset({"run"}),
}
SIDE_EFFECT_FILL_HELPERS = frozenset({"fill_review_queue", "record_actions", "route_outcomes"})
SIMULATOR_BASES = frozenset({"Simulator", "ToyGrid"})
SIMULATOR_METHODS = frozenset({"step", "replay"})
HELPER_MUTATING_METHODS = frozenset(
    {"submit", "resolve", "record", "put", "delete", "rollback", "run", "step", "replay"}
)
CONTAINER_MUTATING_METHODS = frozenset(
    {
        "append",
        "extend",
        "update",
        "add",
        "pop",
        "popitem",
        "clear",
        "setdefault",
        "insert",
        "remove",
        "discard",
    }
)
SIMULATION_MODULE = "jev_cookbook.simulation"
SIDE_EFFECT_DECLARATION = "side_effects.json"
SIDE_EFFECT_KEY = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*){0,2}$")
PLACEHOLDER_MARK = "TODO"  # what tools/new_recipe.py writes into the declaration it scaffolds
# Catalog ranks whose open issues carry the ``needs: simulator`` flag: the recipes that are
# applicable by definition, whatever the analysis detects.
SIMULATOR_RANKS = frozenset({36, 43, 45, 46, 48, 57, 58, 59, 60})
SIMULATOR_REQUIRED = frozenset(
    r["slug"] for r in CATALOG["recipes"] if r["rank"] in SIMULATOR_RANKS
)


def _simulation_imports(tree: ast.AST) -> tuple[dict[str, str], set[str]]:
    """``({local name: jev_cookbook.simulation name}, {local names of the module itself})``."""
    names: dict[str, str] = {}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == SIMULATION_MODULE:
            for alias in node.names:
                names[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module == "jev_cookbook":
            for alias in node.names:
                if alias.name == "simulation":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == SIMULATION_MODULE:
                    modules.add(alias.asname or SIMULATION_MODULE)
    return names, modules


def _simulation_symbol(func: ast.expr, names: dict[str, str], modules: set[str]) -> str | None:
    """The ``jev_cookbook.simulation`` name ``func`` refers to, or ``None``."""
    if isinstance(func, ast.Name):
        return names.get(func.id)
    if isinstance(func, ast.Attribute):
        owner = ast.unparse(func.value)
        if owner in modules or owner == SIMULATION_MODULE:
            return func.attr
    return None


def _constant_truth(test: ast.expr) -> bool | None:
    """``True``/``False`` for a test that is a literal constant (or ``not`` of one), else None."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _constant_truth(test.operand)
        return None if inner is None else not inner
    return None


def _is_empty_literal(node: ast.expr) -> bool:
    return (isinstance(node, ast.List | ast.Tuple | ast.Set) and not node.elts) or (
        isinstance(node, ast.Dict) and not node.keys
    )


def _expression_nodes(node: ast.AST):
    """Every node under ``node`` that can run, in source order, not entering a lambda."""
    yield node
    if isinstance(node, ast.Lambda):
        return
    for child in ast.iter_child_nodes(node):
        yield from _expression_nodes(child)


_TRY_STATEMENTS = (ast.Try, getattr(ast, "TryStar", ast.Try))  # TryStar only exists on 3.11+


def _live_nodes(stmts: list[ast.stmt]):
    """Statements and expression nodes of ``stmts`` that can execute, in source order.

    A ``def`` or ``class`` is yielded as itself and not entered (its body is live only if the
    function is called, which the caller decides). Branches are chosen only for literal
    constant conditions; anything else is assumed possible.
    """
    for stmt in stmts:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield stmt
            continue
        if isinstance(stmt, ast.If):
            yield stmt
            yield from _expression_nodes(stmt.test)
            truth = _constant_truth(stmt.test)
            if truth is not False:
                yield from _live_nodes(stmt.body)
            if truth is not True:
                yield from _live_nodes(stmt.orelse)
        elif isinstance(stmt, ast.While):
            yield stmt
            yield from _expression_nodes(stmt.test)
            if _constant_truth(stmt.test) is not False:
                yield from _live_nodes(stmt.body)
            yield from _live_nodes(stmt.orelse)
        elif isinstance(stmt, ast.For | ast.AsyncFor):
            yield stmt
            yield from _expression_nodes(stmt.iter)
            if not _is_empty_literal(stmt.iter):
                yield from _live_nodes(stmt.body)
            yield from _live_nodes(stmt.orelse)
        elif isinstance(stmt, ast.Match):
            yield stmt
            yield from _expression_nodes(stmt.subject)
            for case in stmt.cases:
                if case.guard is not None:
                    yield from _expression_nodes(case.guard)
                yield from _live_nodes(case.body)
        elif isinstance(stmt, _TRY_STATEMENTS):
            yield stmt
            for block in (stmt.body, *(h.body for h in stmt.handlers), stmt.orelse, stmt.finalbody):
                yield from _live_nodes(block)
        elif isinstance(stmt, ast.With | ast.AsyncWith):
            yield stmt
            for item in stmt.items:
                yield from _expression_nodes(item.context_expr)
            yield from _live_nodes(stmt.body)
        else:
            yield stmt
            for child in ast.iter_child_nodes(stmt):
                yield from _expression_nodes(child)
        if isinstance(stmt, ast.Raise | ast.Return | ast.Break | ast.Continue):
            return


def _root_name(node: ast.AST) -> str | None:
    """The name an attribute/subscript chain starts from, or ``None`` when it starts elsewhere
    (a call, a literal)."""
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _simulator_classes(trees: list[ast.AST], names: dict[str, str], modules: set[str]) -> set[str]:
    """Names of the classes defined in ``trees`` (module level) that subclass ``Simulator`` or
    ``ToyGrid``, directly or through another such class."""
    classes = [
        n for tree in trees for n in getattr(tree, "body", []) if isinstance(n, ast.ClassDef)
    ]
    found: set[str] = set()
    changed = True
    while changed:
        changed = False
        for cls in classes:
            if cls.name in found:
                continue
            for base in cls.bases:
                symbol = _simulation_symbol(base, names, modules)
                if symbol in SIMULATOR_BASES or (isinstance(base, ast.Name) and base.id in found):
                    found.add(cls.name)
                    changed = True
                    break
    return found


class HelpersInfo:
    """What ``helpers.py`` offers as simulated side effects (see the section header)."""

    def __init__(self) -> None:
        self.parsed = True
        self.functions: set[str] = set()
        self.classes: set[str] = set()
        self.simulator_classes: set[str] = set()
        self.effect_functions: set[str] = set()
        self.effect_methods: dict[str, frozenset[str]] = {}  # public side-effect methods
        self.uses: dict[str, set[str]] = {}  # "fn:x" / "cls:X" -> symbols its body refers to
        # Names whose code writes to a sink or a simulator (not just to a container of its own).
        self.strong_effects: set[str] = set()
        # Factories: "new_game" or "Class.make" -> what a call to it returns, as
        # ("helpers", ClassName) or ("simulation", <jev_cookbook.simulation name>).
        self.factories: dict[str, tuple[str, str]] = {}

    @property
    def effect_classes(self) -> set[str]:
        return {c for c, methods in self.effect_methods.items() if methods}

    def effect_symbols(self) -> set[str]:
        return {f"fn:{f}" for f in self.effect_functions} | {
            f"cls:{c}" for c in self.effect_classes
        }

    def closure(self, start: set[str]) -> set[str]:
        """``start`` plus every function or class its bodies refer to, transitively."""
        seen = set(start)
        todo = list(start)
        while todo:
            for nxt in self.uses.get(todo.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return seen


def _module_scope_names(tree: ast.Module) -> set[str]:
    """Names bound by assignment in the module's own scope: not inside a function, a class, a
    lambda or a comprehension (their targets are local to them)."""
    found: set[str] = set()
    todo: list[ast.AST] = list(tree.body)
    while todo:
        node = todo.pop()
        if isinstance(
            node,
            ast.FunctionDef
            | ast.AsyncFunctionDef
            | ast.ClassDef
            | ast.Lambda
            | ast.ListComp
            | ast.SetComp
            | ast.DictComp
            | ast.GeneratorExp,
        ):
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            found.add(node.id)
        todo.extend(ast.iter_child_nodes(node))
    return found


def _own_statements(func: ast.FunctionDef):
    """Every node of ``func``'s body, not entering a nested function, class or lambda."""
    todo = list(func.body)
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            todo.extend(ast.iter_child_nodes(node))


def returned_kinds(func: ast.FunctionDef, kind_of_call) -> set[tuple[str, str]] | None:
    """What a call to ``func`` returns, when ``kind_of_call(ast.Call)`` knows the kind of every
    value it returns (``return Cls(...)``, or ``x = Cls(...)`` and later ``return x``): the set of
    kinds, or ``None`` when some returned value is not a call the caller can classify."""
    assigned: dict[str, list[ast.expr]] = {}
    returned: list[ast.expr] = []
    for node in _own_statements(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.Return) and node.value is not None:
            returned.append(node.value)
    if not returned:
        return None
    kinds: set[tuple[str, str]] = set()
    for value in returned:
        candidates = assigned.get(value.id, []) if isinstance(value, ast.Name) else [value]
        found = [kind_of_call(c) for c in candidates if isinstance(c, ast.Call)]
        if not found or None in found:
            return None
        kinds.update(found)
    return kinds


def _factories(
    functions: dict[str, ast.FunctionDef],
    classes: dict[str, ast.ClassDef],
    names: dict[str, str],
    modules: set[str],
) -> dict[str, tuple[str, str]]:
    """Functions (and classmethods or staticmethods) of ``helpers.py`` that hand back a new
    sink, simulator, or instance of one of its classes, so that ``sim = helpers.new_game(seed)``
    is known to hold what ``new_game`` builds. Keys are ``fn`` and ``Class.method``; values are
    ``("helpers", ClassName)`` or ``("simulation", <jev_cookbook.simulation name>)``. A factory
    that calls another factory is resolved by iterating."""
    candidates: dict[str, tuple[ast.FunctionDef, str | None]] = {
        name: (func, None) for name, func in functions.items()
    }
    for cname, cls in classes.items():
        for item in cls.body:
            if isinstance(item, ast.FunctionDef) and any(
                isinstance(d, ast.Name) and d.id in ("classmethod", "staticmethod")
                for d in item.decorator_list
            ):
                candidates[f"{cname}.{item.name}"] = (item, cname)
    known: dict[str, tuple[str, str]] = {}

    def make_kind_of_call(owner: str | None):
        def kind_of_call(call: ast.Call) -> tuple[str, str] | None:
            func = call.func
            symbol = _simulation_symbol(func, names, modules)
            if symbol in SIDE_EFFECT_SINKS or symbol in SIMULATOR_BASES:
                return ("simulation", symbol)
            if isinstance(func, ast.Name):
                if func.id in classes:
                    return ("helpers", func.id)
                if func.id == "cls" and owner is not None:
                    return ("helpers", owner)
                return known.get(func.id)
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                return known.get(f"{func.value.id}.{func.attr}")
            return None

        return kind_of_call

    changed = True
    while changed:
        changed = False
        for key, (func, owner) in candidates.items():
            if key in known:
                continue
            kinds = returned_kinds(func, make_kind_of_call(owner))
            if kinds is not None and len(kinds) == 1:
                known[key] = next(iter(kinds))
                changed = True
    return known


def _helpers_info(helpers_path: Path, ignore: frozenset[str] = frozenset()) -> HelpersInfo:
    """Analyse ``helpers.py`` (no file: nothing offered; unparseable: ``parsed`` is False)."""
    info = HelpersInfo()
    if not helpers_path.is_file():
        return info
    try:
        tree = ast.parse(helpers_path.read_text("utf-8"))
    except SyntaxError:
        info.parsed = False
        return info
    names, modules = _simulation_imports(tree)
    imported = {
        (a.asname or a.name).split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in n.names
    }
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    info.functions, info.classes = set(functions), set(classes)
    info.simulator_classes = _simulator_classes([tree], names, modules)
    info.factories = _factories(functions, classes, names, modules)
    # Names bound at module level (state a function could write to): classes, and every name
    # assigned in module scope, including inside ``try`` / ``if`` / ``for`` / ``with`` blocks.
    module_state = (set(classes) | _module_scope_names(tree)) - imported

    # Graph nodes: "fn:name" and "m:Class.method". Direct effects and call edges per node.
    bodies: dict[str, tuple[ast.FunctionDef, str | None]] = {
        f"fn:{n}": (f, None) for n, f in functions.items() if n not in ignore
    }
    for cname, cls in classes.items():
        if cname in ignore:
            continue
        for item in cls.body:
            if isinstance(item, ast.FunctionDef):
                bodies[f"m:{cname}.{item.name}"] = (item, cname)
    # A direct effect is STRONG when the code writes to a sink or a simulator (a mutating method
    # on a parameter, a local, ``self`` or a module-level object, or a shared fill helper), and
    # WEAK when it only writes to a container of its own (``self.x.append``, ``self.x[k] = v``)
    # or to module-level state. Only the second kind can be called bookkeeping (not_side_effects).
    strong_direct: set[str] = set()
    weak_direct: set[str] = set()
    effect_edges: dict[str, set[str]] = {}
    attr_calls: dict[str, set[str]] = {}
    use_edges: dict[str, set[str]] = {}
    for node_id, (func, owner) in bodies.items():
        args = func.args
        params = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
        for extra in (args.vararg, args.kwarg):
            if extra is not None:
                params.add(extra.arg)
        declared_global = {
            name for n in ast.walk(func) if isinstance(n, ast.Global) for name in n.names
        }
        stored = {
            n.id for n in ast.walk(func) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        }
        local_names = (params | stored) - declared_global
        roots = (local_names | {"self"}) - imported
        # Module-level names this function reaches: bound at module level (or declared
        # ``global``) and not shadowed by a parameter or a local.
        module_roots = ((module_state | declared_global) - local_names - {"self"}) - imported
        effect_edges[node_id], use_edges[node_id] = set(), set()
        attr_calls[node_id] = set()
        for inner in ast.walk(func):
            if isinstance(inner, ast.Assign | ast.AugAssign | ast.AnnAssign | ast.Delete):
                if isinstance(inner, ast.Assign):
                    targets = inner.targets
                elif isinstance(inner, ast.Delete):
                    targets = inner.targets
                else:
                    targets = [inner.target]
                for t in targets:
                    root = _root_name(t)
                    if isinstance(t, ast.Subscript) and root == "self":
                        weak_direct.add(node_id)
                    elif isinstance(t, ast.Subscript | ast.Attribute) and root in module_roots:
                        weak_direct.add(node_id)  # NAME[k] = v, NAME.attr = v, del NAME[k]
                    elif isinstance(t, ast.Name) and t.id in declared_global:
                        weak_direct.add(node_id)  # global NAME; NAME = ...
            if not isinstance(inner, ast.Call):
                continue
            callee = inner.func
            if isinstance(callee, ast.Attribute):
                root = _root_name(callee.value)
                if callee.attr in HELPER_MUTATING_METHODS and (
                    root in roots or root in module_roots
                ):
                    strong_direct.add(node_id)
                elif callee.attr in CONTAINER_MUTATING_METHODS and (
                    root == "self" or root in module_roots
                ):
                    weak_direct.add(node_id)
                else:
                    if owner and isinstance(callee.value, ast.Name) and callee.value.id == "self":
                        effect_edges[node_id].add(f"m:{owner}.{callee.attr}")
                        use_edges[node_id].add(f"m:{owner}.{callee.attr}")
                    if root in roots:
                        attr_calls[node_id].add(callee.attr)
            if _simulation_symbol(callee, names, modules) in SIDE_EFFECT_FILL_HELPERS:
                strong_direct.add(node_id)
            elif isinstance(callee, ast.Name):
                if callee.id in functions:
                    effect_edges[node_id].add(f"fn:{callee.id}")
                    use_edges[node_id].add(f"fn:{callee.id}")
                elif callee.id in classes:
                    effect_edges[node_id].add(f"m:{callee.id}.__init__")
                    use_edges[node_id].add(f"cls:{callee.id}")

    def propagate(seed: set[str]) -> set[str]:
        """``seed`` plus every node that calls (or constructs, or calls a public method of) one."""
        reached = set(seed)
        changed = True
        while changed:
            changed = False
            public = {
                n.split(".", 1)[1] for n in reached if n.startswith("m:") and "._" not in n
            } | (SIMULATOR_METHODS if info.simulator_classes else set())
            for node_id, targets in effect_edges.items():
                if node_id not in reached and (targets & reached or attr_calls[node_id] & public):
                    reached.add(node_id)
                    changed = True
        return reached

    effects = propagate(strong_direct | weak_direct)
    strong = propagate(strong_direct)
    info.strong_effects = {n[3:] for n in strong if n.startswith("fn:")} | {
        n[2:].split(".", 1)[0] for n in strong if n.startswith("m:")
    }
    info.strong_effects |= set(info.simulator_classes)
    info.effect_functions = {n[3:] for n in effects if n.startswith("fn:")}
    for cname in classes:
        public = {
            n.split(".", 1)[1]
            for n in effects
            if n.startswith(f"m:{cname}.") and not n.split(".", 1)[1].startswith("_")
        }
        if cname in info.simulator_classes and cname not in ignore:
            public |= SIMULATOR_METHODS
        info.effect_methods[cname] = frozenset(public)
    # "uses": a function refers to what its body calls; a class to what all its methods call.
    for node_id, targets in use_edges.items():
        func, owner = bodies[node_id]
        key = f"fn:{node_id[3:]}" if owner is None else f"cls:{owner}"
        info.uses.setdefault(key, set()).update(t for t in targets if not t.startswith("m:"))
        for t in targets:
            if t.startswith("m:"):
                info.uses.setdefault(key, set()).add(f"cls:{t[2:].split('.')[0]}")
    return info


class SideEffectReport:
    """What the notebook's live code does with the simulated side effects of its recipe."""

    def __init__(self) -> None:
        self.sites: dict[str, set[tuple[int, int, int]]] = {}
        self.sink_vars: dict[str, str] = {}  # notebook name -> key prefix of the object it holds
        self.touched_vars: set[str] = set()
        # Names the notebook does not have to mutate itself: a name bound to the result of a
        # side-effect function that returns the object (``sim = helpers.run_episode(...)``, which
        # may have done the work), and a name a function the notebook defines builds and returns
        # (the caller's name is checked instead). A pure-construction factory is NOT in here:
        # its result is checked like a direct construction.
        self.handed_over: set[str] = set()
        self.helpers = HelpersInfo()
        self.used: set[str] = set()  # helpers symbols the notebook reaches
        self.problems: list[str] = []  # things the analysis could not read

    @property
    def effect_functions(self) -> set[str]:
        return self.helpers.effect_functions

    def counts(self) -> dict[str, int]:
        return {key: len(places) for key, places in sorted(self.sites.items())}

    def built_vars(self) -> list[str]:
        """Names the notebook built a sink or simulator into that it has to mutate itself."""
        return sorted(v for v in self.sink_vars if v not in self.handed_over)

    def untouched_sink_vars(self) -> list[str]:
        return sorted(v for v in self.built_vars() if v not in self.touched_vars)

    def uncalled_effect_functions(self) -> list[str]:
        """Side-effect functions and classes of ``helpers.py`` the notebook never reaches, even
        through another helper it uses."""
        return sorted(s.split(":", 1)[1] for s in self.helpers.effect_symbols() - self.used)

    def detected(self) -> bool:
        return bool(
            self.sites
            or self.built_vars()
            or self.helpers.effect_functions
            or self.helpers.effect_classes
        )


def side_effect_report(recipe_dir_: Path, ignore: frozenset[str] = frozenset()) -> SideEffectReport:
    """Analyse ``recipe_dir_``'s committed notebook as described in the section header."""
    report = SideEffectReport()
    helpers_info = _helpers_info(recipe_dir_ / "helpers.py", ignore)
    if not helpers_info.parsed:
        report.problems.append("helpers.py does not parse as plain Python")
    report.helpers = helpers_info
    blocks: list[tuple[int, ast.Module]] = []
    for index, cell in enumerate(notebook_cells(recipe_dir_)):
        if cell.get("cell_type") != "code":
            continue
        try:
            blocks.append((index, ast.parse(cell_source(cell))))
        except SyntaxError:
            report.problems.append(
                f"notebook cell {index} does not parse as plain Python (an IPython magic?), "
                "so its side effects cannot be checked"
            )
    names: dict[str, str] = {}
    modules: set[str] = set()
    helper_names = {"helpers"}
    for _, tree in blocks:
        n, m = _simulation_imports(tree)
        names.update(n)
        modules |= m
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and _call_func_name(node.value) == "load_helpers"
            ):
                helper_names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    notebook_simulators = _simulator_classes([t for _, t in blocks], names, modules)

    def resolve(func: ast.expr) -> str | None:
        return _simulation_symbol(func, names, modules)

    def helper_attr(node: ast.expr) -> str | None:
        """``X`` for ``helpers.X``, else ``None``."""
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in helper_names
        ):
            return node.attr
        return None

    def object_kind(value: ast.expr) -> tuple[str, frozenset[str]] | None:
        """``(key prefix, mutating methods)`` of what the call ``value`` builds, if it builds a
        sink, a simulator, or an instance of a side-effect class of ``helpers.py``."""
        if not isinstance(value, ast.Call):
            return None
        symbol = resolve(value.func)
        if symbol in SIDE_EFFECT_SINKS:
            return symbol, SIDE_EFFECT_SINKS[symbol]
        if symbol in SIMULATOR_BASES:
            return symbol, SIMULATOR_METHODS
        if isinstance(value.func, ast.Name) and value.func.id in notebook_simulators:
            return value.func.id, SIMULATOR_METHODS
        attr = helper_attr(value.func)
        if attr in helpers_info.classes and helpers_info.effect_methods.get(attr):
            return f"helpers.{attr}", helpers_info.effect_methods[attr]
        # A factory: helpers.new_game(seed), helpers.Game.from_seed(seed), or a function the
        # notebook defines, that hands back a sink, a simulator or a helpers.py class instance.
        func = value.func
        factory = None
        if attr is not None:
            factory = helpers_info.factories.get(attr)
        elif isinstance(func, ast.Attribute) and (owner_attr := helper_attr(func.value)):
            factory = helpers_info.factories.get(f"{owner_attr}.{func.attr}")
        if factory is not None:
            return built_kind(factory)
        if isinstance(func, ast.Name) and func.id in defs and func.id not in resolving:
            resolving.add(func.id)
            try:
                kinds = returned_kinds(defs[func.id], notebook_kind_of_call)
            finally:
                resolving.discard(func.id)
            if kinds is not None and len(kinds) == 1:
                return built_kind(next(iter(kinds)))
        return None

    def built_by_effect_factory(value: ast.expr) -> bool:
        """Whether ``value`` calls a factory that could itself have done the work: a factory
        that is a side-effect function (or classmethod) of ``helpers.py``. Its result may be only
        read by the notebook. A pure-construction factory (``def new_grid(): return ToyGrid()``)
        does not qualify, so its result must be mutated like a direct construction."""
        if not isinstance(value, ast.Call):
            return False
        func = value.func
        attr = helper_attr(func)
        if attr is not None:
            return attr in helpers_info.factories and attr in helpers_info.effect_functions
        if isinstance(func, ast.Attribute):
            owner_attr = helper_attr(func.value)
            if owner_attr is None or f"{owner_attr}.{func.attr}" not in helpers_info.factories:
                return False
            return func.attr in helpers_info.effect_methods.get(owner_attr, frozenset())
        return False

    def built_kind(kind: tuple[str, str]) -> tuple[str, frozenset[str]] | None:
        """``(key prefix, mutating methods)`` for a factory's ``("helpers", Class)`` or
        ``("simulation", name)`` result."""
        where, name = kind
        if where == "helpers":
            methods = helpers_info.effect_methods.get(name)
            return (f"helpers.{name}", methods) if methods else None
        return name, SIDE_EFFECT_SINKS.get(name, SIMULATOR_METHODS)

    def notebook_kind_of_call(call: ast.Call) -> tuple[str, str] | None:
        """``object_kind(call)`` in the ``("helpers", Class)`` / ``("simulation", name)`` form
        that ``returned_kinds`` collects."""
        kind = object_kind(call)
        if kind is None:
            return None
        if kind[0].startswith("helpers."):
            return "helpers", kind[0][len("helpers.") :]
        return "simulation", kind[0]

    var_methods: dict[str, frozenset[str]] = {}
    defs: dict[str, ast.FunctionDef] = {}
    resolving: set[str] = set()
    entered: set[str] = set()
    effectful_defs: set[str] = set()  # notebook functions whose body executed a side effect
    def_results: dict[str, str] = {}  # notebook name -> the notebook function that returned it
    returned_by: dict[str, set[str]] = {}  # notebook function -> sink names it built and returned
    current_cell = [0]

    def site(key: str, call: ast.Call) -> None:
        place = (current_cell[0], call.lineno, call.col_offset)
        report.sites.setdefault(key, set()).add(place)

    def touch_arguments(call: ast.Call) -> None:
        for arg in [*call.args, *(k.value for k in call.keywords)]:
            if isinstance(arg, ast.Name) and arg.id in report.sink_vars:
                report.touched_vars.add(arg.id)

    def bind(node: ast.Assign, bound_here: set[str]) -> None:
        pairs = []
        for target in node.targets:
            if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                pairs.extend(zip(target.elts, node.value.elts, strict=False))
            else:
                pairs.append((target, node.value))
        for target, value in pairs:
            kind = object_kind(value)
            if kind is not None and isinstance(target, ast.Name):
                report.sink_vars[target.id] = kind[0]
                var_methods[target.id] = kind[1]
                bound_here.add(target.id)
                def_results.pop(target.id, None)
                report.handed_over.discard(target.id)
                if built_by_effect_factory(value):
                    report.handed_over.add(target.id)
                elif (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in defs
                ):
                    def_results[target.id] = value.func.id

    def run(stmts: list[ast.stmt], owner: str | None = None) -> None:
        bound_here: set[str] = set()  # sinks and simulators THIS body built
        for node in _live_nodes(stmts):
            if isinstance(node, ast.FunctionDef):
                defs[node.name] = node
            elif isinstance(node, ast.Assign):
                bind(node, bound_here)
            elif (
                isinstance(node, ast.Return)
                and isinstance(node.value, ast.Name)
                and node.value.id in bound_here
            ):
                # A function the notebook defines builds an object and returns it (a factory).
                # The name is credited below, and only if a caller bound the result to a name
                # that the notebook then mutates. Only a name this very body bound to a sink
                # counts; a `return <name>` of a parameter, a global or an unrelated local
                # does not.
                if owner is not None:
                    returned_by.setdefault(owner, set()).add(node.value.id)
            elif isinstance(node, ast.Attribute):
                attr = helper_attr(node)
                if attr in helpers_info.functions:
                    report.used.add(f"fn:{attr}")
                elif attr in helpers_info.classes:
                    report.used.add(f"cls:{attr}")
            elif isinstance(node, ast.Call):
                handle(node)

    def handle(call: ast.Call) -> None:
        func = call.func
        symbol = resolve(func)
        if symbol in SIDE_EFFECT_FILL_HELPERS:
            site(symbol, call)
            touch_arguments(call)
            return
        attr = helper_attr(func)
        if attr is not None:
            touch_arguments(call)  # a sink handed to a helper function or class constructor
            if attr in helpers_info.effect_functions:
                site(f"helpers.{attr}", call)
            return
        if isinstance(func, ast.Name) and func.id in defs and func.id not in entered:
            entered.add(func.id)
            before = sum(len(places) for places in report.sites.values())
            run(defs[func.id].body, owner=func.id)
            if sum(len(places) for places in report.sites.values()) > before:
                effectful_defs.add(func.id)
        elif isinstance(func, ast.Attribute):
            owner = func.value
            if isinstance(owner, ast.Name) and owner.id in var_methods:
                touch_arguments(call)
                if func.attr in var_methods[owner.id]:
                    site(f"{report.sink_vars[owner.id]}.{func.attr}", call)
                    report.touched_vars.add(owner.id)
            elif isinstance(owner, ast.Call):
                kind = object_kind(owner)
                if kind is not None and func.attr in kind[1]:
                    site(f"{kind[0]}.{func.attr}", call)

    for index, tree in blocks:
        current_cell[0] = index
        run(tree.body)
    # The result of a notebook function whose body executed a side effect may be only read.
    report.handed_over |= {name for name, fn in def_results.items() if fn in effectful_defs}
    # An object a notebook function built and returned is used when the caller's name for it is:
    # the caller either mutated it or only reads what the function already did with it.
    for name, fn in def_results.items():
        if name in report.touched_vars or name in report.handed_over:
            report.touched_vars |= returned_by.get(fn, set())
    report.used = helpers_info.closure(report.used)
    return report


# The 50 recipes published before this check keep their declarations here (migration); a
# ``side_effects.json`` in a recipe's folder overrides its entry here. Each entry has the schema
# of that file: the exact number of live call sites the notebook has under each key, or the
# reason the recipe has no simulated side effect, optionally with the helpers.py names that only
# keep bookkeeping. Built from the audit in the pull request that added this check.
_NO_SINKS = (
    "returns typed outcomes only: the notebook builds no ReviewQueue, ActionLog, Store or "
    "Transactor and helpers.py calls no mutating method"
)


def _sites(sites: dict[str, int], not_side_effects: dict[str, str] | None = None) -> dict:
    return {"schema": 1, "sites": sites, "not_side_effects": not_side_effects or {}}


def _none(reason: str, not_side_effects: dict[str, str] | None = None) -> dict:
    return {"schema": 1, "none": reason, "not_side_effects": not_side_effects or {}}


SIDE_EFFECT_INVENTORY: dict[str, dict] = {
    "01-sentiment-classification": _none(_NO_SINKS),
    "02-refund-intent-detection": _sites({"ReviewQueue.submit": 2}),
    "03-response-clarity-scoring": _none(_NO_SINKS),
    "04-support-ticket-routing": _none(
        "route_ticket returns a Routing value; its 'simulated queue' is a field of that value, not a ReviewQueue or ActionLog, and nothing is written anywhere"
    ),
    "05-document-classification": _none(_NO_SINKS),
    "06-multiple-topic-labels": _sites({"ReviewQueue.submit": 1}),
    "07-word-sense-selection": _none(_NO_SINKS),
    "08-faq-selection": _none(_NO_SINKS),
    "09-file-organization": _none(
        "prints a proposed folder plan; nothing moves, and no ReviewQueue, ActionLog or Store is built"
    ),
    "10-answer-relevance-check": _sites({"ReviewQueue.submit": 3}),
    "11-clarification-selection": _none(
        "select_followup returns the question to ask as a value; no ReviewQueue, ActionLog or Store is built"
    ),
    "12-thesaurus-word-selection": _none(_NO_SINKS),
    "13-candidate-rewrite-selection": _none(_NO_SINKS),
    "14-source-span-selection": _none(_NO_SINKS),
    "15-sensitive-text-triage": _sites({"ReviewQueue.submit": 1}),
    "16-discord-moderation-triage": _sites({"ActionLog.record": 1, "ReviewQueue.submit": 1}),
    "17-passage-reranking": _none(_NO_SINKS),
    "18-duplicate-incident-matching": _sites({"helpers.record_resolution": 1}),
    "19-ci-failure-classification": _sites({"helpers.classify": 3}),
    "20-claim-support-classification": _none(_NO_SINKS),
    "21-quiz-answer-adjudication": _sites({"ReviewQueue.submit": 2}),
    "22-cmdb-asset-matching": _sites({"helpers.record_resolution": 1}),
    "23-pairwise-answer-evaluation": _none(
        "the preference is a returned value and the notebook says it has no side effect; no ReviewQueue, ActionLog or Store is built"
    ),
    "24-incident-priority-composition": _sites({"helpers.submit_reviews": 2}),
    "25-change-evidence-review": _sites({"ReviewQueue.submit": 1}),
    "26-prompt-injection-screening": _sites({"ReviewQueue.submit": 1}),
    "27-function-selection": _sites({"helpers.resolve": 2}),
    "28-skill-selection": _none(_NO_SINKS),
    "29-tool-outcome-verification": _sites({"helpers.classify": 2}),
    "30-citation-verification": _sites({"helpers.classify": 2}),
    "31-patch-risk-triage": _sites({"ReviewQueue.submit": 1}),
    "32-regression-test-selection": _none(_NO_SINKS),
    "33-schema-field-mapping": _sites({"helpers.submit_reviews": 2}),
    "34-evidence-relationship-labels": _sites({"helpers.submit_reviews": 2}),
    "35-semantic-feature-extraction": _none(_NO_SINKS),
    "36-card-game-action-selection": _sites({"helpers.CardDuel.replay": 1, "helpers.play_game": 1}),
    "37-research-domain-tagging": _sites(
        {"ReviewQueue.submit": 1},
        not_side_effects={
            "CountingBackend": "appends each state it is asked to decide to its own sent_states "
            "list so the notebook can print what was sent; it writes to no queue, log, store or "
            "simulator"
        },
    ),
    "38-abstention-and-review-queues": _sites({"ActionLog.record": 1, "ReviewQueue.submit": 1}),
    "39-document-extraction-cascade": _none(_NO_SINKS),
    "40-hierarchical-classification": _sites({"ActionLog.record": 1, "ReviewQueue.submit": 1}),
    "41-approval-scope-review": _sites({"ReviewQueue.submit": 1}),
    "42-outbound-disclosure-screening": _sites({"ActionLog.record": 1, "ReviewQueue.submit": 1}),
    "43-failure-recovery-selection": _sites(
        {"helpers.enforce_recovery": 3, "helpers.run_episode": 3}
    ),
    "44-plan-constraint-assessment": _sites({"ReviewQueue.submit": 1}),
    "45-memory-reconciliation": _sites(
        {"Store.put": 3, "helpers.rebuild_store_from_writes": 1, "helpers.reconcile": 3}
    ),
    "46-semantic-context-paging": _sites({"helpers.rebuild_store": 2, "helpers.run_session": 1}),
    "47-evidence-conflict-diagnosis": _none(_NO_SINKS),
    "48-document-revision-consistency": _sites(
        {"Store.put": 1, "Store.rollback": 1, "helpers.decide": 3}
    ),
    "49-multi-agent-task-assignment": _sites({"helpers.assign": 6}),
    "50-model-comparison-and-calibration": _none(
        _NO_SINKS,
        not_side_effects={
            "MemoisingBackend": "keeps its own dict of answers and two counters so the "
            "notebook can print the distinct requests and the forwarded calls; it writes to no "
            "queue, log, store or simulator"
        },
    ),
}


class SideEffectDeclaration:
    """A recipe's statement of its simulated side effects (``side_effects.json``)."""

    def __init__(
        self, sites: dict[str, int] | None, none: str | None, not_side_effects: dict[str, str]
    ):
        self.sites = sites
        self.none = none
        self.not_side_effects = dict(not_side_effects)  # helpers.py name -> why it is bookkeeping


def parse_side_effect_declaration(data: object) -> tuple[SideEffectDeclaration | None, list[str]]:
    """Validate a declaration object; ``(declaration, [])`` or ``(None, [problems])``. Schema
    (docs/simulation.md)::

        {"schema": 1, "sites": {"helpers.submit_reviews": 2, "ReviewQueue.submit": 1}}
        {"schema": 1, "none": "why this recipe has no simulated side effect"}

    Either form may add ``"not_side_effects": {"MemoisingBackend": "why"}``, the helpers.py
    functions or classes that the analysis would take for a side effect but that only keep
    bookkeeping (a cache, a request counter), each with the reason; each must exist in helpers.py
    and may write to nothing but a container of its own (``_bookkeeping_problems``). A reason
    that still carries the scaffolder's ``TODO`` marker is a placeholder and is rejected.
    """
    if not isinstance(data, dict):
        return None, ["the declaration must be a JSON object"]
    problems = []
    if data.get("schema") != 1:
        problems.append('"schema" must be 1')
    unknown = sorted(set(data) - {"schema", "sites", "none", "not_side_effects"})
    if unknown:
        problems.append(f"unknown field(s) {unknown}")
    if ("sites" in data) == ("none" in data):
        problems.append('exactly one of "sites" and "none" is required')
    sites = None
    none = None
    if "none" in data:
        if not isinstance(data["none"], str) or not data["none"].strip():
            problems.append('"none" must be a non-empty reason string')
        elif PLACEHOLDER_MARK in data["none"]:
            problems.append(
                f'"none" is still the scaffolder\'s {PLACEHOLDER_MARK} placeholder: rewrite the '
                'reason, or replace the file with a "sites" declaration '
                '(docs/simulation.md, "Declaring the side effect")'
            )
        else:
            none = data["none"]
    elif "sites" in data:
        raw = data["sites"]
        if not isinstance(raw, dict) or not raw:
            problems.append('"sites" must be a non-empty object')
        else:
            for key, count in raw.items():
                if not SIDE_EFFECT_KEY.match(key):
                    problems.append(
                        f"{key!r} is not a site key (e.g. helpers.fn, ReviewQueue.submit)"
                    )
                elif type(count) is not int or count < 1:
                    problems.append(f"{key!r}: the count must be an integer >= 1, got {count!r}")
            sites = dict(raw)
    ignored = data.get("not_side_effects", {})
    if not isinstance(ignored, dict):
        problems.append(
            '"not_side_effects" must be an object mapping each helpers.py name to the reason it '
            "only keeps bookkeeping"
        )
        ignored = {}
    for name, reason in ignored.items():
        if not name:
            problems.append('"not_side_effects" has an empty name')
        elif not isinstance(reason, str) or not reason.strip():
            problems.append(f'"not_side_effects": {name!r} needs a non-empty reason string')
        elif PLACEHOLDER_MARK in reason:
            problems.append(
                f'"not_side_effects": {name!r} still has the {PLACEHOLDER_MARK} marker: write the '
                "reason, or remove the entry"
            )
    if problems:
        return None, problems
    return SideEffectDeclaration(sites, none, ignored), []


def read_side_effect_declaration(
    recipe_dir_: Path,
) -> tuple[SideEffectDeclaration | None, list[str]]:
    """The recipe's own ``side_effects.json``: ``(declaration, [])``, ``(None, [])`` when the file
    does not exist, or ``(None, [problems])`` when it exists and is malformed."""
    path = recipe_dir_ / SIDE_EFFECT_DECLARATION
    if not path.is_file():
        return None, []
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as error:
        return None, [f"{SIDE_EFFECT_DECLARATION} is not valid JSON ({error})"]
    declaration, problems = parse_side_effect_declaration(data)
    return declaration, [f"{SIDE_EFFECT_DECLARATION}: {p}" for p in problems]


def _bookkeeping_problems(recipe_dir_: Path, ignore: frozenset[str]) -> list[str]:
    """``not_side_effects`` is for bookkeeping only. Judged on ``helpers.py`` as it is, with
    nothing ignored, an entry fails when its code writes to a ``ReviewQueue``, ``ActionLog``,
    ``Store``, ``Transactor`` or ``Simulator`` (a mutating method on a parameter, a local,
    ``self`` or a module-level object, or one of the shared fill helpers, directly or through
    other ``helpers.py`` code), or when it is a ``Simulator`` subclass. Such a side effect is
    declared under ``sites``. What stays allowed is a write to a container of its own
    (``self.seen.append``, ``self.memo[key] = v``) or to module-level state."""
    if not ignore:
        return []
    strong = _helpers_info(recipe_dir_ / "helpers.py").strong_effects
    return [
        f"not_side_effects names {name!r}, whose code writes to a queue, log, store or "
        "simulator (or subclasses Simulator): that is a side effect, declare its call sites "
        "under sites instead"
        for name in sorted(ignore & strong)
    ]


def _side_effect_violations(slug: str, recipe_dir_: Path) -> list[str] | None:
    """Reasons ``recipe_dir_``'s notebook fails the check, ``[]`` when it passes, or ``None`` when
    nothing applies (no declaration, nothing detected, no simulator need)."""
    declaration, problems = read_side_effect_declaration(recipe_dir_)
    if declaration is None and not problems and slug in SIDE_EFFECT_INVENTORY:
        declaration, problems = parse_side_effect_declaration(SIDE_EFFECT_INVENTORY[slug])
    if problems:
        return problems
    ignore = frozenset(declaration.not_side_effects) if declaration else frozenset()
    report = side_effect_report(recipe_dir_, ignore)
    violations = list(report.problems)
    for name in sorted(ignore - report.helpers.functions - report.helpers.classes):
        violations.append(f"not_side_effects names {name!r}, which helpers.py does not define")
    violations.extend(_bookkeeping_problems(recipe_dir_, ignore))
    counts = report.counts()
    required = slug in SIMULATOR_REQUIRED
    if declaration is None:
        if not (report.detected() or required):
            return violations or None
        what = sorted(
            {*report.sink_vars.values(), *report.effect_functions, *report.helpers.effect_classes}
        )
        violations.append(
            f"no side-effect declaration: add recipes/{slug}/{SIDE_EFFECT_DECLARATION} stating "
            f"the call sites the notebook keeps (detected {what or 'nothing'}; this recipe "
            f"{'needs a simulator' if required else 'has a side effect'}). Observed: {counts}"
        )
    elif declaration.none is not None:
        if report.detected():
            violations.append(
                f"the declaration says this recipe has no simulated side effect "
                f"({declaration.none}) but its notebook builds "
                f"{sorted(set(report.sink_vars.values()))}, executes {sorted(counts)} and "
                f"helpers.py defines "
                f"{sorted(report.effect_functions | report.helpers.effect_classes)}"
                + ("; a recipe that needs a simulator cannot declare none" if required else "")
            )
        elif required:
            violations.append(
                f"the declaration says this recipe has no simulated side effect "
                f"({declaration.none}), but a recipe that needs a simulator cannot declare none: "
                f"declare under sites the trajectory, transaction or actuation it runs "
                f"(nothing is detected yet; docs/simulation.md, 'Declaring the side effect')"
            )
    else:
        declared = declaration.sites or {}
        for key in sorted(set(declared) | set(counts)):
            found, wanted = counts.get(key, 0), declared.get(key, 0)
            if found < wanted:
                violations.append(
                    f"the notebook executes {key} at {found} call site(s), the declaration "
                    f"requires {wanted}"
                )
            elif found > wanted:
                violations.append(
                    f"the notebook executes {key} at {found} call site(s) but the declaration "
                    f"says {wanted}: declare the side effect it performs"
                )
    uncalled = report.uncalled_effect_functions()
    if uncalled:
        violations.append(
            f"helpers.py defines side-effect code {uncalled} that the notebook never uses, "
            "directly or through another helper"
        )
    untouched = report.untouched_sink_vars()
    if untouched:
        violations.append(
            f"the notebook builds {untouched} but never calls a mutating method on it or "
            "passes it to a side-effect function"
        )
    return violations


@pytest.mark.parametrize("recipe", guarded("simulated_side_effect_invoked"))
def test_the_notebook_executes_its_simulated_side_effect(recipe):
    """#212: nothing else verifies that a recipe's notebook actually INVOKES the simulated side
    effect its prose and its helper tests describe. A helper can be thoroughly tested while the
    committed notebook stops calling it, and a notebook re-executed after that edit is fresh and
    faithfully wrong, so the notebook-freshness job, the helper's tests and every other check
    here stay green. The rule, the declaration (``side_effects.json``, or
    ``SIDE_EFFECT_INVENTORY`` for the recipes published before the check) and the known limits
    are in the section header above. A recipe with a side effect and no declaration fails; a code
    cell the analysis cannot parse fails; only a recipe with nothing detected, no declaration and
    no simulator need is skipped, and the skip says so."""
    violations = _side_effect_violations(recipe["slug"], recipe_dir(recipe))
    if violations is None:
        pytest.skip(
            f"{recipe['slug']}: no declaration, no simulated side effect detected and no "
            f"simulator need; add {SIDE_EFFECT_DECLARATION} with a reason if it has none"
        )
    assert not violations, f"{recipe['slug']}: " + "; ".join(violations)


def side_effect_inventory_gaps() -> list[str]:
    """Published recipes with neither a ``side_effects.json`` nor an inventory entry. Informational
    (a recipe with a side effect is already failed by the test above)."""
    return sorted(
        r["slug"]
        for r in PUBLISHED
        if r["slug"] not in SIDE_EFFECT_INVENTORY
        and not (recipe_dir(r) / SIDE_EFFECT_DECLARATION).is_file()
    )


def test_the_side_effect_inventory_names_only_published_recipes_with_well_formed_entries():
    stale = sorted(SIDE_EFFECT_INVENTORY.keys() - PUBLISHED_SLUGS)
    assert not stale, f"SIDE_EFFECT_INVENTORY names recipes that are not published: {stale}"
    for slug, entry in SIDE_EFFECT_INVENTORY.items():
        declaration, problems = parse_side_effect_declaration(entry)
        assert declaration is not None and not problems, f"{slug}: {problems}"


def test_every_declaration_file_under_recipes_is_well_formed():
    """A malformed ``side_effects.json`` is reported by the recipe's own case; this also covers
    the template and any folder the catalog does not list."""
    for path in sorted(RECIPES_DIR.glob(f"*/{SIDE_EFFECT_DECLARATION}")):
        _, problems = read_side_effect_declaration(path.parent)
        assert not problems, f"{path}: {problems}"


# The guard is proved by mutation: each case below takes a real published recipe, edits ONLY its
# committed notebook source, and requires the guard to report it. M15 is the originally reported
# case (recipe 24, delete the ``eval-test`` cell's ``submit_reviews`` call); the others show the
# guard is not satisfied by a mention in a comment, a string, a function nobody calls, a lambda,
# or an ``if False:`` branch, and that the same holds for a recipe that is not published yet.

RECIPE_24 = "24-incident-priority-composition"
RECIPE_24_TEST_CALL = "helpers.submit_reviews(queue, test_examples, test_decisions, test_results)"
UNPUBLISHED = {r["rank"]: r["slug"] for r in CATALOG["recipes"] if r["rank"] >= 57}


def _mutated_recipe(tmp_path: Path, slug: str, edit) -> Path:
    """A copy of the published recipe ``slug`` whose notebook code cells went through
    ``edit(source) -> source``. Only the notebook is touched."""
    target = tmp_path / slug
    shutil.copytree(RECIPES_DIR / slug, target, ignore=shutil.ignore_patterns("__pycache__"))
    path = target / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            cell["source"] = edit(cell_source(cell)).splitlines(keepends=True)
    path.write_text(json.dumps(notebook), "utf-8")
    return target


def _replace_line(old: str, make):
    """An ``edit`` replacing the line that contains ``old`` with ``make(line)``; it must hit once."""
    hits = []

    def edit(source: str) -> str:
        lines = source.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if old in line:
                hits.append(line)
                lines[i] = make(line)
        return "".join(lines)

    edit.hits = hits
    return edit


def _write_declaration(folder: Path, **declaration) -> None:
    (folder / SIDE_EFFECT_DECLARATION).write_text(json.dumps({"schema": 1, **declaration}), "utf-8")


def _declare_observed(folder: Path, **extra) -> dict[str, int]:
    """Write the declaration a builder would write for ``folder`` as it is now."""
    sites = side_effect_report(folder).counts()
    _write_declaration(folder, sites=sites, **extra)
    return sites


def test_the_unmutated_recipe_24_passes_the_guard(tmp_path):
    assert _side_effect_violations(RECIPE_24, RECIPES_DIR / RECIPE_24) == []
    copy = _mutated_recipe(tmp_path, RECIPE_24, lambda source: source)
    assert _side_effect_violations(RECIPE_24, copy) == []


def test_m15_deleting_the_test_split_submit_reviews_call_is_caught(tmp_path):
    edit = _replace_line(RECIPE_24_TEST_CALL, lambda line: "")
    copy = _mutated_recipe(tmp_path, RECIPE_24, edit)
    assert len(edit.hits) == 1, "the mutation must remove exactly the test split's call"
    assert _side_effect_violations(RECIPE_24, copy) == [
        "the notebook executes helpers.submit_reviews at 1 call site(s), the declaration requires 2"
    ]


def test_m15_is_caught_for_a_recipe_that_is_not_published_yet(tmp_path):
    """The case both reviews of the first revision found open: a new recipe, whose pull request
    cannot edit ``tests/``, states its own floor in its folder and M15 fails against it."""
    slug = UNPUBLISHED[57]
    intact = _mutated_recipe(tmp_path / "intact", RECIPE_24, lambda s: s)
    assert _declare_observed(intact) == {"helpers.submit_reviews": 2}
    assert _side_effect_violations(slug, intact) == []
    edit = _replace_line(RECIPE_24_TEST_CALL, lambda line: "")
    mutated = _mutated_recipe(tmp_path / "mutated", RECIPE_24, edit)
    _write_declaration(mutated, sites={"helpers.submit_reviews": 2})
    assert _side_effect_violations(slug, mutated) == [
        "the notebook executes helpers.submit_reviews at 1 call site(s), the declaration requires 2"
    ]
    # Without any declaration the same notebook fails too, intact or not.
    (mutated / SIDE_EFFECT_DECLARATION).unlink()
    assert any("no side-effect declaration" in v for v in _side_effect_violations(slug, mutated))
    (intact / SIDE_EFFECT_DECLARATION).unlink()
    assert any("no side-effect declaration" in v for v in _side_effect_violations(slug, intact))


def test_a_side_effect_the_declaration_does_not_mention_is_reported(tmp_path):
    copy = _mutated_recipe(tmp_path, RECIPE_24, lambda s: s)
    _write_declaration(copy, sites={"helpers.submit_reviews": 1})
    (violation,) = _side_effect_violations(UNPUBLISHED[58], copy)
    assert "at 2 call site(s) but the declaration says 1" in violation


def test_a_declaration_file_overrides_the_inventory_entry(tmp_path):
    copy = _mutated_recipe(tmp_path, RECIPE_24, lambda s: s)
    _write_declaration(copy, sites={"helpers.submit_reviews": 3})
    assert _side_effect_violations(RECIPE_24, copy)


def test_deleting_every_submit_reviews_call_is_caught(tmp_path):
    edit = _replace_line("helpers.submit_reviews(", lambda line: "")
    copy = _mutated_recipe(tmp_path, RECIPE_24, edit)
    assert len(edit.hits) == 2
    assert _side_effect_violations(RECIPE_24, copy)
    # Under an unpublished slug with no declaration: reported, not skipped, and the helper that
    # the notebook never uses is named.
    violations = _side_effect_violations(UNPUBLISHED[57], copy)
    assert any("no side-effect declaration" in v for v in violations)
    assert any("never uses" in v and "submit_reviews" in v for v in violations)


@pytest.mark.parametrize(
    ("name", "make"),
    [
        ("a comment", lambda line: "# " + line.lstrip()),
        ("a string", lambda line: f'"""{line.strip()}"""\n'),
        ("an if False branch", lambda line: f"if False:\n    {line.strip()}\n"),
        ("a while False loop", lambda line: f"while False:\n    {line.strip()}\n"),
        ("a loop over an empty list", lambda line: f"for _ in []:\n    {line.strip()}\n"),
        ("a function never called", lambda line: f"def _never():\n    {line.strip()}\n"),
        ("a lambda never called", lambda line: f"_never = lambda: {line.strip()}\n"),
        ("after a raise", lambda line: f"raise SystemExit\n{line}"),
    ],
)
def test_a_dead_or_inert_mention_of_the_call_does_not_satisfy_the_guard(tmp_path, name, make):
    edit = _replace_line(RECIPE_24_TEST_CALL, make)
    copy = _mutated_recipe(tmp_path, RECIPE_24, edit)
    assert len(edit.hits) == 1
    violations = _side_effect_violations(RECIPE_24, copy)
    assert violations, f"{name} must not count as invoking the side effect"
    assert "the declaration requires 2" in violations[0]


def test_a_call_moved_into_a_function_that_is_called_still_counts(tmp_path):
    """The guard is not tied to the call sitting at cell level: a notebook-defined function that
    live code calls counts for what its body calls."""
    edit = _replace_line(
        RECIPE_24_TEST_CALL,
        lambda line: f"def _fill_test():\n    {line.strip()}\n\n\n_fill_test()\n",
    )
    copy = _mutated_recipe(tmp_path, RECIPE_24, edit)
    assert _side_effect_violations(RECIPE_24, copy) == []


def test_an_inline_recipe_is_caught_when_its_queue_submit_is_deleted(tmp_path):
    slug = "02-refund-intent-detection"
    assert _side_effect_violations(slug, RECIPES_DIR / slug) == []
    edit = _replace_line("queue.submit(", lambda line: line.replace("queue.submit(", "print("))
    copy = _mutated_recipe(tmp_path, slug, edit)
    assert len(edit.hits) == 2
    violations = _side_effect_violations(slug, copy)
    assert "ReviewQueue.submit at 0 call site(s)" in violations[0]
    assert any("never calls a mutating method" in v for v in violations)


def test_an_unlisted_recipe_with_no_side_effect_is_neither_failed_nor_silently_passed():
    """``None`` makes the parametrised test skip with a message; it applies only when nothing is
    detected, no declaration exists and the recipe does not need a simulator."""
    folder = RECIPES_DIR / "01-sentiment-classification"
    assert _side_effect_violations("99-unlisted", folder) is None


def test_the_template_side_effect_check_reports_an_undeclared_queue_write(tmp_path, monkeypatch):
    folder = _copy_recipe(tmp_path, "_template")
    path = folder / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    notebook["cells"].append(
        {
            "cell_type": "code",
            "outputs": [],
            "source": [
                "from jev_cookbook.simulation import ReviewQueue\n",
                "queue = ReviewQueue()\n",
                'queue.submit({"ticket": 7}, "synthetic review")\n',
            ],
        }
    )
    path.write_text(json.dumps(notebook), "utf-8")
    monkeypatch.setitem(globals(), "RECIPES_DIR", tmp_path)
    with pytest.raises(AssertionError, match=r"no side-effect declaration.*ReviewQueue\.submit"):
        test_the_notebook_executes_its_simulated_side_effect({"slug": "_template"})


def test_a_recipe_that_needs_a_simulator_cannot_pass_by_detecting_nothing(tmp_path):
    """57-60 (and 36, 43, 45, 46, 48) are applicable by definition."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    for rank in (57, 58, 59, 60):
        violations = _side_effect_violations(UNPUBLISHED[rank], folder)
        assert any(
            "no side-effect declaration" in v and "needs a simulator" in v for v in violations
        )
    _write_declaration(folder, none="nothing happens")
    violations = _side_effect_violations(UNPUBLISHED[59], folder)
    assert any("cannot declare none" in v for v in violations)
    assert _side_effect_violations("99-unlisted", folder) == []


def test_a_recipe_declared_as_having_no_side_effect_fails_if_it_acquires_one(tmp_path):
    copy = _mutated_recipe(tmp_path, RECIPE_24, lambda s: s)
    _write_declaration(copy, none="pure classification")
    violations = _side_effect_violations("99-unlisted", copy)
    assert any("no simulated side effect" in v for v in violations)


def test_an_unparseable_notebook_cell_fails_rather_than_being_skipped(tmp_path):
    copy = _mutated_recipe(tmp_path, RECIPE_24, lambda source: source)
    path = copy / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    notebook["cells"].append(
        {"cell_type": "code", "metadata": {}, "outputs": [], "source": ["%matplotlib inline\n"]}
    )
    path.write_text(json.dumps(notebook), "utf-8")
    violations = _side_effect_violations(RECIPE_24, copy)
    assert any("does not parse" in v for v in violations)


def test_a_sink_the_notebook_builds_but_never_reaches_is_reported(tmp_path):
    slug = "10-answer-relevance-check"
    edit = _replace_line("queue = ReviewQueue()", lambda line: line + "orphan = ReviewQueue()\n")
    copy = _mutated_recipe(tmp_path, slug, edit)
    violations = _side_effect_violations(slug, copy)
    assert violations == [
        "the notebook builds ['orphan'] but never calls a mutating method on it or passes it "
        "to a side-effect function"
    ]


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ([], "must be a JSON object"),
        ({"sites": {"helpers.f": 1}}, '"schema" must be 1'),
        ({"schema": 1}, 'exactly one of "sites" and "none"'),
        ({"schema": 1, "sites": {"helpers.f": 1}, "none": "x"}, 'exactly one of "sites"'),
        ({"schema": 1, "sites": {}}, "non-empty object"),
        ({"schema": 1, "sites": {"helpers.f": 0}}, "integer >= 1"),
        ({"schema": 1, "sites": {"helpers.f": True}}, "integer >= 1"),
        ({"schema": 1, "sites": {"not a key": 1}}, "is not a site key"),
        ({"schema": 1, "none": " "}, "non-empty reason"),
        ({"schema": 1, "none": "x", "extra": 1}, "unknown field"),
        ({"schema": 1, "none": "x", "not_side_effects": "Cache"}, "must be an object mapping"),
        ({"schema": 1, "none": "x", "not_side_effects": ["Cache"]}, "must be an object mapping"),
        ({"schema": 1, "none": "x", "not_side_effects": {"Cache": ""}}, "needs a non-empty reason"),
        ({"schema": 1, "none": "x", "not_side_effects": {"Cache": 3}}, "needs a non-empty reason"),
        ({"schema": 1, "none": "x", "not_side_effects": {"": "why"}}, "empty name"),
        ({"schema": 1, "none": "TODO: why"}, "placeholder"),
        ({"schema": 1, "none": "x", "not_side_effects": {"Cache": "TODO"}}, "marker"),
    ],
)
def test_a_malformed_declaration_is_rejected(data, fragment):
    declaration, problems = parse_side_effect_declaration(data)
    assert declaration is None and fragment in "; ".join(problems)


def test_a_declaration_that_is_not_json_or_names_a_missing_helper_fails(tmp_path):
    copy = _mutated_recipe(tmp_path, RECIPE_24, lambda s: s)
    (copy / SIDE_EFFECT_DECLARATION).write_text("{not json", "utf-8")
    assert "not valid JSON" in _side_effect_violations("99-unlisted", copy)[0]
    _write_declaration(
        copy, sites={"helpers.submit_reviews": 2}, not_side_effects={"Missing": "a counter"}
    )
    assert any("does not define" in v for v in _side_effect_violations("99-unlisted", copy))


def _synthetic_recipe(tmp_path: Path, cells: list[str], helpers_source: str = "") -> Path:
    """A throwaway recipe folder: a notebook of the given code cells and an optional helpers.py."""
    folder = tmp_path / "99-synthetic"
    folder.mkdir(parents=True, exist_ok=True)
    notebook = {
        "cells": [
            {"cell_type": "code", "metadata": {}, "outputs": [], "source": src.splitlines(True)}
            for src in cells
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (folder / "notebook.ipynb").write_text(json.dumps(notebook), "utf-8")
    if helpers_source:
        (folder / "helpers.py").write_text(helpers_source, "utf-8")
    return folder


SYNTHETIC_HELPERS = """
import subprocess
from pathlib import Path

from jev_cookbook.simulation import fill_review_queue


def leaf(queue, item):
    queue.submit(item, "because")


def via_leaf(queue, items):
    for item in items:
        leaf(queue, item)


def via_shared(queue, outcomes):
    return fill_review_queue(queue, outcomes, needs_review=bool, item=dict, reason="r")


def pure(x):
    return x + 1


def version():
    return subprocess.run(["git", "--version"]).returncode


def here(name):
    return Path(name).resolve()
"""


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        # a helper that reaches a mutating method only through another helper still counts
        (
            ["helpers = load_helpers()\nq = ReviewQueue()\nhelpers.via_leaf(q, [])"],
            {"helpers.via_leaf": 1},
        ),
        (
            ["helpers = load_helpers()\nq = ReviewQueue()\nhelpers.via_shared(q, [])"],
            {"helpers.via_shared": 1},
        ),
        # a pure helper, or one whose mutating-looking call is on a module, is not a side effect
        (["helpers = load_helpers()\nq = ReviewQueue()\nhelpers.pure(1)"], {}),
        (["helpers = load_helpers()\nhelpers.version()\nhelpers.here('x')"], {}),
        # try/with/match bodies and comprehensions are live code
        (
            [
                "helpers = load_helpers()\nq = ReviewQueue()\n"
                "try:\n    helpers.leaf(q, 1)\nexcept ValueError:\n    pass\n"
                "with open('x') as f:\n    helpers.leaf(q, 2)\n"
                "match 1:\n    case 1:\n        helpers.leaf(q, 3)\n"
                "[helpers.leaf(q, i) for i in range(2)]"
            ],
            {"helpers.leaf": 4},
        ),
        # aliases of the simulation module and of a sink class resolve
        (
            [
                "import jev_cookbook.simulation as sim\nfrom jev_cookbook.simulation "
                "import ActionLog as AL\nlog = AL()\nlog.record('k')\nsim.fill_review_queue("
                "sim.ReviewQueue(), [], needs_review=bool, item=dict, reason='r')"
            ],
            {"ActionLog.record": 1, "fill_review_queue": 1},
        ),
        # tuple binding, and a notebook-defined function counts only when live code calls it
        (
            [
                "a, q = ActionLog(), ReviewQueue()\n"
                "def go():\n    q.submit({}, 'r')\n    a.record('k')\ndef unused():\n    q.submit({}, 'r')\ngo()"
            ],
            {"ActionLog.record": 1, "ReviewQueue.submit": 1},
        ),
        # a name that merely looks like a sink method on an unrelated object is not counted
        (["d = {}\nd.put = 1\nclass X:\n    def submit(self): ...\nX().submit()"], {}),
        # a Simulator the notebook defines or imports is a sink for step
        (
            [
                "from jev_cookbook.simulation import Simulator, ToyGrid\n"
                "class Mine(Simulator):\n    pass\n"
                "m = Mine()\nt = ToyGrid()\nm.step('a')\nt.step('b')\nt.step('c')"
            ],
            {"Mine.step": 1, "ToyGrid.step": 2},
        ),
    ],
)
def test_the_site_counter_on_synthetic_notebooks(tmp_path, cells, expected):
    header = "from jev_cookbook.simulation import ActionLog, ReviewQueue\n"
    cells = [header + cells[0], *cells[1:]]
    report = side_effect_report(_synthetic_recipe(tmp_path, cells, SYNTHETIC_HELPERS))
    assert report.effect_functions == {"leaf", "via_leaf", "via_shared"}
    assert report.counts() == expected


# The shapes recipes 57-60 are likely to take (both independent reviews of the first revision
# probed these and found them skipped): each is built intact, declared the way its builder would
# declare it, and must pass; then its side effect is deleted and it must fail, with and without a
# declaration, under the slug of the recipe it stands for.

HDR = (
    "from jev_cookbook import load_helpers\n"
    "from jev_cookbook.simulation import ActionLog, ReviewQueue, Store, Transactor, ToyGrid\n"
    "helpers = load_helpers()\n"
)
SIM_CLASS = """
from jev_cookbook.simulation import Simulator


class Factory(Simulator):
    def _reset(self, rng):
        self.t = 0

    def _observe(self):
        return {"t": self.t}

    def _legal_actions(self):
        return ["build", "wait"]

    def _apply(self, action, rng):
        self.t += 1

    def _snapshot(self):
        return {"t": self.t}

    def _is_done(self):
        return self.t >= 5


def rule_policy(obs, legal):
    return legal[0]
"""
TRAJECTORY = (
    SIM_CLASS
    + """

def play(policy, seed):
    sim = Factory(seed=seed)
    while not sim.done:
        sim.step(policy(sim.observe(), sim.legal_actions()))
    return sim.trajectory()
"""
)
REVIEW_HELPERS = """
def submit_reviews(queue, examples):
    for e in examples:
        queue.submit(e, "low confidence")
"""
GRAPH = """
from jev_cookbook.simulation import Store, Transactor


class GraphStore:
    def __init__(self):
        self.tx = Transactor(Store())

    def apply(self, update):
        return self.tx.run(update.ops, writer="jev")
"""
CONTROLLER = """
class Controller:
    def __init__(self):
        self.events = []

    def actuate(self, cmd):
        self.events.append(cmd)


def supervise(ctrl, response):
    ctrl.actuate(response)
"""
PLANT = """
from jev_cookbook.simulation import ActionLog, ReviewQueue, Simulator


class Plant(Simulator):
    def _reset(self, rng):
        self.t = 0
        self.queue = ReviewQueue()
        self.actions = ActionLog()

    def _observe(self):
        return {"t": self.t}

    def _legal_actions(self):
        return ["hold", "vent"]

    def _apply(self, action, rng):
        self.t += 1
        if action == "vent":
            self.actions.record("vent")
        else:
            self.queue.submit({"t": self.t}, "hold for operator")
        return action

    def _snapshot(self):
        return {"t": self.t}

    def _is_done(self):
        return self.t >= 3
"""

SHAPES = {
    "59 shape: Simulator subclass in helpers.py, step loop inline": (
        59,
        SIM_CLASS,
        HDR + "sim = helpers.Factory(seed=1)\nwhile not sim.done:\n    sim.step('build')\n",
        HDR + "sim = helpers.Factory(seed=1)\n",
        {"helpers.Factory.step": 1},
    ),
    "59 shape: shared ToyGrid, step loop inline": (
        59,
        "",
        HDR + "sim = ToyGrid(seed=0)\nwhile not sim.done:\n    sim.step(sim.legal_actions()[0])\n",
        HDR + "sim = ToyGrid(seed=0)\n",
        {"ToyGrid.step": 1},
    ),
    "60 shape: trajectory helper run for the baseline and the Jev policy": (
        60,
        TRAJECTORY,
        HDR
        + "base = [helpers.play(helpers.rule_policy, s) for s in range(3)]\n"
        + "jev = [helpers.play(helpers.rule_policy, s) for s in range(3)]\n",
        HDR + "base = [helpers.play(helpers.rule_policy, s) for s in range(3)]\n",
        {"helpers.play": 2},
    ),
    "57 shape: Transactor inside a helpers class": (
        57,
        GRAPH,
        HDR + "graph = helpers.GraphStore()\nfor u in updates:\n    graph.apply(u)\n",
        HDR + "graph = helpers.GraphStore()\n",
        {"helpers.GraphStore.apply": 1},
    ),
    "58 shape: controller whose actuation appends to its own state": (
        58,
        CONTROLLER,
        HDR + "ctrl = helpers.Controller()\nhelpers.supervise(ctrl, 'shutdown')\n",
        HDR + "ctrl = helpers.Controller()\n",
        {"helpers.supervise": 1},
    ),
    "58 shape: Simulator subclass that queues and records in _apply": (
        58,
        PLANT,
        HDR + "sim = helpers.Plant(seed=0)\nfor a in ['vent', 'hold']:\n    sim.step(a)\n",
        HDR + "sim = helpers.Plant(seed=0)\n",
        {"helpers.Plant.step": 1},
    ),
    "24 shape: two split submissions of one helper": (
        57,
        REVIEW_HELPERS,
        HDR
        + "queue = ReviewQueue()\nhelpers.submit_reviews(queue, [])\nhelpers.submit_reviews(queue, [])\n",
        HDR + "queue = ReviewQueue()\nhelpers.submit_reviews(queue, [])\n",
        {"helpers.submit_reviews": 2},
    ),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_shapes_of_the_simulator_recipes_pass_intact_and_fail_with_the_effect_deleted(
    tmp_path, shape
):
    rank, helpers_source, intact, deleted, declared = SHAPES[shape]
    slug = UNPUBLISHED[rank]
    whole = _synthetic_recipe(tmp_path / "intact", [intact], helpers_source)
    assert side_effect_report(whole).counts() == declared
    # Not declared: reported (never skipped), even though it is a recipe that needs a simulator.
    assert any("no side-effect declaration" in v for v in _side_effect_violations(slug, whole))
    _write_declaration(whole, sites=declared)
    assert _side_effect_violations(slug, whole) == []
    # The side effect deleted from the notebook: fails against the builder's declaration ...
    broken = _synthetic_recipe(tmp_path / "deleted", [deleted], helpers_source)
    _write_declaration(broken, sites=declared)
    assert _side_effect_violations(slug, broken), "deleting the side effect must fail"
    # ... and also when the builder declares nothing (the deleted notebook has nothing to declare).
    (broken / SIDE_EFFECT_DECLARATION).unlink()
    assert _side_effect_violations(slug, broken)


def test_a_real_side_effect_the_notebook_never_uses_is_reported_even_if_an_unrelated_call_exists(
    tmp_path,
):
    helpers_source = (
        REVIEW_HELPERS
        + "\nimport subprocess\n\n\ndef version():\n    return subprocess.run(['git']).returncode\n"
    )
    folder = _synthetic_recipe(
        tmp_path,
        [HDR + "helpers.version()\n"],
        helpers_source,
    )
    report = side_effect_report(folder)
    assert report.effect_functions == {"submit_reviews"}
    assert report.uncalled_effect_functions() == ["submit_reviews"]
    _write_declaration(folder, none="nothing")
    assert any("never uses" in v for v in _side_effect_violations("99-unlisted", folder))


def test_a_helper_used_only_through_another_helper_counts_as_used(tmp_path):
    helpers_source = REVIEW_HELPERS + "\n\ndef run_all(queue):\n    submit_reviews(queue, [])\n"
    folder = _synthetic_recipe(
        tmp_path, [HDR + "q = ReviewQueue()\nhelpers.run_all(q)\n"], helpers_source
    )
    assert side_effect_report(folder).uncalled_effect_functions() == []


def test_bookkeeping_helpers_are_declared_not_silently_ignored(tmp_path):
    helpers_source = (
        "class Cache:\n    def __init__(self):\n        self.seen = {}\n\n"
        "    def get(self, k):\n        self.seen.setdefault(k, 0)\n        return k\n"
    )
    folder = _synthetic_recipe(
        tmp_path, ["helpers = load_helpers()\nc = helpers.Cache()\n"], helpers_source
    )
    assert side_effect_report(folder).helpers.effect_classes == {"Cache"}
    assert any("no side-effect declaration" in v for v in _side_effect_violations("99-x", folder))
    _write_declaration(folder, none="a cache only", not_side_effects={"Cache": "a lookup memo"})
    assert _side_effect_violations("99-x", folder) == []


# --------------------------------------------------------------------------------------------
# #327: not_side_effects is for bookkeeping only; module-level state; factory-built simulators;
# the scaffolded declaration
# --------------------------------------------------------------------------------------------

SIM_IMPORTS = "from jev_cookbook.simulation import ActionLog, ReviewQueue, Store, Transactor\n"

# helpers.py classes and functions a declaration may exempt: the only state they write is a
# container of their own, or module-level state.
BOOKKEEPING_ALLOWED = {
    "a counter and a list of its own": (
        "Counting",
        "class Counting:\n    def __init__(self, inner):\n        self.inner = inner\n"
        "        self.sent = []\n        self.n = 0\n\n    def decide(self, x):\n"
        "        self.sent.append(x)\n        self.n += 1\n        return self.inner.decide(x)\n",
    ),
    "a memo dict of its own": (
        "Memo",
        "class Memo:\n    def __init__(self):\n        self.answers = {}\n\n"
        "    def get(self, key):\n        self.answers[key] = key\n        return key\n",
    ),
    "a module-level cache written by a function": (
        "cached",
        "_SEEN = {}\n\n\ndef cached(key):\n    _SEEN.setdefault(key, 0)\n    return key\n",
    ),
}

# The same slot used for what is not bookkeeping: each writes to a queue, a log, a store, a
# transaction log or a simulator, in a different way. All of them were accepted before #327.
BOOKKEEPING_REFUSED = {
    "a queue held in self": (
        "Stash",
        SIM_IMPORTS
        + "\n\nclass Stash:\n    def __init__(self):\n        self.queue = ReviewQueue()\n\n"
        "    def add(self, item):\n        self.queue.submit(item, 'r')\n",
    ),
    "an action log held in self": (
        "Journal",
        SIM_IMPORTS
        + "\n\nclass Journal:\n    def __init__(self):\n        self.log = ActionLog()\n\n"
        "    def add(self, item):\n        self.log.record('k', item)\n",
    ),
    "a transactor held in self": (
        "GraphStore",
        GRAPH,
    ),
    "a store written through a parameter": (
        "stash",
        "def stash(store, key, value):\n    store.put(key, value, writer='rule')\n",
    ),
    "a queue built and written in a function": (
        "enqueue",
        SIM_IMPORTS
        + "\n\ndef enqueue(item):\n    queue = ReviewQueue()\n    queue.submit(item, 'r')\n"
        "    return queue\n",
    ),
    "a module-level queue": (
        "enqueue",
        SIM_IMPORTS
        + "\nQUEUE = ReviewQueue()\n\n\ndef enqueue(item):\n    QUEUE.submit(item, 'r')\n",
    ),
    "a shared fill helper": (
        "fill",
        "from jev_cookbook.simulation import fill_review_queue\n\n\ndef fill(queue, outcomes):\n"
        "    return fill_review_queue(queue, outcomes, needs_review=bool, item=dict, reason='r')\n",
    ),
    "a simulator stepped through self": (
        "Runner",
        "class Runner:\n    def __init__(self, sim):\n        self.sim = sim\n\n"
        "    def go(self, action):\n        return self.sim.step(action)\n",
    ),
    "a Simulator subclass": ("Factory", SIM_CLASS),
    "a ToyGrid subclass": (
        "Maze",
        "from jev_cookbook.simulation import ToyGrid\n\n\nclass Maze(ToyGrid):\n    pass\n",
    ),
    "a class that reaches the write through another helper": (
        "Wrapper",
        REVIEW_HELPERS + "\n\nclass Wrapper:\n    def go(self, queue, items):\n"
        "        submit_reviews(queue, items)\n",
    ),
}


@pytest.mark.parametrize("case", sorted(BOOKKEEPING_ALLOWED))
def test_a_bookkeeping_class_may_be_listed_under_not_side_effects_with_a_reason(tmp_path, case):
    name, helpers_source = BOOKKEEPING_ALLOWED[case]
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"], helpers_source)
    assert name in side_effect_report(folder).helpers.effect_functions | (
        side_effect_report(folder).helpers.effect_classes
    ), "the analysis takes it for a side effect, which is why it has to be listed"
    _write_declaration(folder, none="bookkeeping only", not_side_effects={name: "a counter"})
    assert _side_effect_violations("99-x", folder) == []


@pytest.mark.parametrize("case", sorted(BOOKKEEPING_REFUSED))
def test_an_entry_that_writes_to_a_queue_log_store_or_simulator_is_refused(tmp_path, case):
    """The loophole: a recipe's own side_effects.json could list its real side-effect class
    under not_side_effects and blind the guard to it (#327, S1)."""
    name, helpers_source = BOOKKEEPING_REFUSED[case]
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"], helpers_source)
    _write_declaration(folder, none="bookkeeping only", not_side_effects={name: "just a counter"})
    violations = _side_effect_violations("99-x", folder)
    assert any(
        v.startswith(f"not_side_effects names {name!r}, whose code writes to a queue")
        for v in violations
    ), violations


def test_the_refusal_names_what_to_do_and_applies_to_a_sites_declaration_too(tmp_path):
    folder = _synthetic_recipe(
        tmp_path, ["x = 1\n"], BOOKKEEPING_REFUSED["a queue held in self"][1]
    )
    _write_declaration(
        folder, sites={"ReviewQueue.submit": 1}, not_side_effects={"Stash": "bookkeeping"}
    )
    violations = _side_effect_violations("99-x", folder)
    assert any("declare its call sites under sites instead" in v for v in violations)


def test_an_exemption_cannot_hide_the_real_effect_of_a_recipe_that_needs_a_simulator(tmp_path):
    """The reviewers' probe P2: recipe 57 lists the class that applies its graph under
    not_side_effects and declares one trivial queue site. Deleting the apply loop passed."""
    slug = UNPUBLISHED[57]
    helpers_source = GRAPH + "\n" + REVIEW_HELPERS
    intact = HDR + (
        "graph = helpers.GraphStore()\nqueue = ReviewQueue()\nhelpers.submit_reviews(queue, [])\n"
        "for u in updates:\n    graph.apply(u)\n"
    )
    deleted = (
        HDR
        + "graph = helpers.GraphStore()\nqueue = ReviewQueue()\nhelpers.submit_reviews(queue, [])\n"
    )
    hidden = {
        "sites": {"helpers.submit_reviews": 1},
        "not_side_effects": {"GraphStore": "bookkeeping"},
    }
    for notebook in (intact, deleted):
        folder = _synthetic_recipe(tmp_path / str(len(notebook)), [notebook], helpers_source)
        _write_declaration(folder, **hidden)
        assert any(
            "not_side_effects names 'GraphStore'" in v
            for v in _side_effect_violations(slug, folder)
        )
    # Declared honestly it passes while the loop is there and fails once it is deleted.
    honest = {"helpers.GraphStore.apply": 1, "helpers.submit_reviews": 1}
    folder = _synthetic_recipe(tmp_path / "honest", [intact], helpers_source)
    _write_declaration(folder, sites=honest)
    assert _side_effect_violations(slug, folder) == []
    folder = _synthetic_recipe(tmp_path / "honest-deleted", [deleted], helpers_source)
    _write_declaration(folder, sites=honest)
    assert _side_effect_violations(slug, folder)


def test_a_declaration_with_a_list_or_a_reasonless_entry_does_not_load(tmp_path):
    folder = _synthetic_recipe(
        tmp_path, ["x = 1\n"], BOOKKEEPING_ALLOWED["a memo dict of its own"][1]
    )
    for value in (["Memo"], {"Memo": ""}, {"Memo": "TODO"}):
        _write_declaration(folder, none="bookkeeping only", not_side_effects=value)
        violations = _side_effect_violations("99-x", folder)
        assert violations and all(v.startswith("side_effects.json:") for v in violations)


def test_the_parser_accepts_the_reasoned_form():
    declaration, problems = parse_side_effect_declaration(
        {"schema": 1, "none": "x", "not_side_effects": {"Cache": "a lookup memo"}}
    )
    assert not problems and declaration.not_side_effects == {"Cache": "a lookup memo"}


# Module-level state (S2): a helpers.py function that writes to it is a side-effect function.
MODULE_STATE_DETECTED = {
    "a subscript write on a module-level dict": (
        "_G = {}\n\n\ndef put(k, v):\n    _G[k] = v\n",
        {"put"},
    ),
    "an append on a module-level list": (
        "LOG = []\n\n\ndef note(x):\n    LOG.append(x)\n",
        {"note"},
    ),
    "a global rebinding": (
        "COUNT = 0\n\n\ndef bump():\n    global COUNT\n    COUNT += 1\n",
        {"bump"},
    ),
    "an attribute write on a module-level object": (
        "class S:\n    n = 0\n\n\nSTATE = S()\n\n\ndef bump():\n    STATE.n = 1\n",
        {"bump"},
    ),
    "a delete on a module-level dict": ("G = {}\n\n\ndef drop(k):\n    del G[k]\n", {"drop"}),
    "a write to a class attribute": (
        "class Registry:\n    items = []\n\n\ndef reg(x):\n    Registry.items.append(x)\n",
        {"reg"},
    ),
    "a setdefault on an annotated module-level dict": (
        "G: dict = {}\n\n\ndef f(k):\n    G.setdefault(k, 1)\n",
        {"f"},
    ),
    "a module-level queue": (
        SIM_IMPORTS + "Q = ReviewQueue()\n\n\ndef add(i):\n    Q.submit(i, 'r')\n",
        {"add"},
    ),
    "a name bound inside a try block": (
        "try:\n    GRAPH = {}\nexcept Exception:\n    GRAPH = {}\n\n\n"
        "def put(k, v):\n    GRAPH[k] = v\n",
        {"put"},
    ),
    "a name bound inside an if block": (
        "if True:\n    LOG = []\n\n\ndef note(x):\n    LOG.append(x)\n",
        {"note"},
    ),
    "a name bound by a for loop at module level": (
        "for ROWS in ([],):\n    pass\n\n\ndef add(x):\n    ROWS.append(x)\n",
        {"add"},
    ),
    "a function that calls one of those": (
        "G = {}\n\n\ndef a(k):\n    G[k] = 1\n\n\ndef b(k):\n    a(k)\n",
        {"a", "b"},
    ),
}
MODULE_STATE_NOT_DETECTED = {
    "a read of a module-level dict": (
        "T = {'a': 1}\n\n\ndef read(k):\n    return T.get(k), list(T.items())\n"
    ),
    "a compiled pattern": "import re\n\n_R = re.compile('x')\n\n\ndef f(s):\n    return _R.sub('', s)\n",
    "a local that shadows the module-level name": (
        "G = {}\n\n\ndef f(k):\n    G = {}\n    G[k] = 1\n    return G\n"
    ),
    "a parameter that shadows the module-level name": ("G = {}\n\n\ndef f(G, k):\n    return k\n"),
    "a comprehension variable is not module state": (
        "ROWS = [r for r in range(3)]\n\n\ndef f():\n    r.append(1)\n"
    ),
    "a read of a module-level number": "N = 0\n\n\ndef f():\n    n = N + 1\n    return n\n",
    "a read of the environment": "import os\n\n\ndef f():\n    return os.environ.get('X')\n",
    # The documented limits: a write through a parameter or a local alias is not seen.
    "a write through a parameter (documented limit)": ("def f(graph, k, v):\n    graph[k] = v\n"),
    "a write through a local alias (documented limit)": (
        "GRAPH = {}\n\n\ndef f(k, v):\n    g = GRAPH\n    g[k] = v\n"
    ),
}


@pytest.mark.parametrize("case", sorted(MODULE_STATE_DETECTED))
def test_a_write_to_module_level_state_makes_the_function_a_side_effect(tmp_path, case):
    helpers_source, expected = MODULE_STATE_DETECTED[case]
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"], helpers_source)
    assert side_effect_report(folder).effect_functions == expected


@pytest.mark.parametrize("case", sorted(MODULE_STATE_NOT_DETECTED))
def test_a_read_a_shadowed_name_or_an_unseen_alias_is_not_taken_for_a_module_state_write(
    tmp_path, case
):
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"], MODULE_STATE_NOT_DETECTED[case])
    assert side_effect_report(folder).effect_functions == set()


def test_a_recipe_whose_real_effect_is_a_module_level_dict_is_caught_when_it_is_deleted(tmp_path):
    """The reviewers' probe P3: recipe 57's writes go to a module-level dict, plus one declared
    queue site; deleting the write loop passed because the dict write was invisible."""
    slug = UNPUBLISHED[57]
    helpers_source = (
        "GRAPH = {}\n\n\ndef apply_update(update):\n    GRAPH[update['key']] = update['value']\n"
        "\n" + REVIEW_HELPERS
    )
    head = HDR + "queue = ReviewQueue()\nhelpers.submit_reviews(queue, [])\n"
    intact = head + "for u in updates:\n    helpers.apply_update(u)\n"
    declared = {"helpers.apply_update": 1, "helpers.submit_reviews": 1}
    folder = _synthetic_recipe(tmp_path / "intact", [intact], helpers_source)
    assert side_effect_report(folder).counts() == declared
    _write_declaration(folder, sites=declared)
    assert _side_effect_violations(slug, folder) == []
    folder = _synthetic_recipe(tmp_path / "deleted", [head], helpers_source)
    _write_declaration(folder, sites=declared)
    violations = _side_effect_violations(slug, folder)
    assert (
        "the notebook executes helpers.apply_update at 0 call site(s), the declaration requires 1"
        in violations
    )
    # And with only the queue site declared, the deleted notebook looks fine to the old guard but
    # the module-level write is now an undeclared function the notebook never uses.
    _write_declaration(folder, sites={"helpers.submit_reviews": 1})
    assert any(
        "never uses" in v and "apply_update" in v for v in _side_effect_violations(slug, folder)
    )


def test_a_recipe_with_only_a_module_level_effect_and_no_simulator_need_is_no_longer_skipped(
    tmp_path,
):
    """The reviewers' probe P4: an unlisted recipe whose only effect is a module-level dict."""
    folder = _synthetic_recipe(
        tmp_path,
        [HDR + "helpers.apply_update({'key': 1, 'value': 2})\n"],
        "GRAPH = {}\n\n\ndef apply_update(update):\n    GRAPH[update['key']] = update['value']\n",
    )
    violations = _side_effect_violations("99-unlisted", folder)
    assert violations and any("no side-effect declaration" in v for v in violations)


# Factory-built simulators (S3): ``sim = helpers.new_game(seed)`` holds what ``new_game`` builds.
FACTORY_SIM = SIM_CLASS + "\n\ndef new_game(seed):\n    return Factory(seed=seed)\n"
FACTORY_STEP_LOOP = "while not sim.done:\n    sim.step('build')\n"

FACTORY_SHAPES = {
    "59 shape: a function that returns the simulator": (
        59,
        FACTORY_SIM,
        HDR + "sim = helpers.new_game(1)\n" + FACTORY_STEP_LOOP,
        HDR + "sim = helpers.new_game(1)\n",
        {"helpers.Factory.step": 1},
    ),
    "59 shape: a function that builds, names and returns the simulator": (
        59,
        SIM_CLASS + "\n\ndef new_game(seed):\n    sim = Factory(seed=seed)\n    return sim\n",
        HDR + "sim = helpers.new_game(1)\n" + FACTORY_STEP_LOOP,
        HDR + "sim = helpers.new_game(1)\n",
        {"helpers.Factory.step": 1},
    ),
    "59 shape: a factory that calls another factory": (
        59,
        FACTORY_SIM + "\n\ndef new_seeded_game(seed):\n    return new_game(seed + 1)\n",
        HDR + "sim = helpers.new_seeded_game(1)\n" + FACTORY_STEP_LOOP,
        HDR + "sim = helpers.new_seeded_game(1)\n",
        {"helpers.Factory.step": 1},
    ),
    "59 shape: a classmethod that returns cls(...)": (
        59,
        SIM_CLASS.replace(
            "    def _reset(self, rng):",
            "    @classmethod\n    def fresh(cls, seed):\n        return cls(seed=seed)\n\n"
            "    def _reset(self, rng):",
            1,
        ),
        HDR + "sim = helpers.Factory.fresh(1)\n" + FACTORY_STEP_LOOP,
        HDR + "sim = helpers.Factory.fresh(1)\n",
        {"helpers.Factory.step": 1},
    ),
    "59 shape: the factory call chained on the step": (
        59,
        FACTORY_SIM,
        HDR + "helpers.new_game(1).step('build')\n",
        HDR + "helpers.new_game(1)\n",
        {"helpers.Factory.step": 1},
    ),
    "59 shape: a function that returns the shared ToyGrid": (
        59,
        "from jev_cookbook.simulation import ToyGrid\n\n\ndef new_grid(seed):\n"
        "    return ToyGrid(seed=seed)\n",
        HDR
        + "sim = helpers.new_grid(0)\nwhile not sim.done:\n    sim.step(sim.legal_actions()[0])\n",
        HDR + "sim = helpers.new_grid(0)\n",
        {"ToyGrid.step": 1},
    ),
    "57 shape: a function that returns a review queue": (
        57,
        "from jev_cookbook.simulation import ReviewQueue\n\n\ndef new_queue():\n"
        "    return ReviewQueue()\n",
        HDR + "queue = helpers.new_queue()\nqueue.submit({}, 'low confidence')\n",
        HDR + "queue = helpers.new_queue()\n",
        {"ReviewQueue.submit": 1},
    ),
    "59 shape: a factory the notebook defines itself": (
        59,
        "",
        HDR
        + "def new_game(seed):\n    grid = ToyGrid(seed=seed)\n    return grid\n\n\n"
        + "sim = new_game(0)\nwhile not sim.done:\n    sim.step(sim.legal_actions()[0])\n",
        HDR
        + "def new_game(seed):\n    grid = ToyGrid(seed=seed)\n    return grid\n\n\nsim = new_game(0)\n",
        {"ToyGrid.step": 1},
    ),
}


@pytest.mark.parametrize("shape", sorted(FACTORY_SHAPES))
def test_a_factory_built_simulator_is_declarable_and_deleting_its_use_fails(tmp_path, shape):
    """S3: before #327 the intact notebook failed (nothing it could declare matched), so a
    builder had to restructure; now it is declared under the class the factory returns."""
    rank, helpers_source, intact, deleted, declared = FACTORY_SHAPES[shape]
    slug = UNPUBLISHED[rank]
    whole = _synthetic_recipe(tmp_path / "intact", [intact], helpers_source)
    assert side_effect_report(whole).counts() == declared
    _write_declaration(whole, sites=declared)
    assert _side_effect_violations(slug, whole) == []
    broken = _synthetic_recipe(tmp_path / "deleted", [deleted], helpers_source)
    _write_declaration(broken, sites=declared)
    assert _side_effect_violations(slug, broken), "deleting the simulator's use must fail"
    (broken / SIDE_EFFECT_DECLARATION).unlink()
    assert _side_effect_violations(slug, broken)


# The "builds a sink or simulator and never mutates it" rule (#319) must survive a function the
# notebook calls that merely returns a name equal to the sink's (#345 review: a `return <name>`
# of a parameter, a global or an unrelated local used to mark the sink as touched).
SIM_NB = "from jev_cookbook.simulation import Simulator\n\n\nclass Mine(Simulator):\n    pass\n\n\n"
NEW_GAME = "def new_game(seed):\n    g = ToyGrid(seed=seed)\n    return g\n\n\n"
UNTOUCHED_SHAPES = {
    "a Simulator subclass never stepped, a display helper returns its parameter": (
        SIM_NB
        + "sim = Mine()\n\n\ndef summarise(sim):\n    print(sim.observe())\n    return sim\n\n\n"
        "summarise(sim)\n",
        ["sim"],
    ),
    "a baseline run whose step loop was deleted, an unrelated helper returns the name": (
        SIM_NB + "base = Mine()\n\n\ndef show(base):\n    return base\n\n\nshow(base)\n",
        ["base"],
    ),
    "a queue never submitted to, a function returns the global": (
        "queue = ReviewQueue()\n\n\ndef peek():\n    return queue\n\n\npeek()\n",
        ["queue"],
    ),
    "a store never written, a function returns a local string of the same name": (
        "store = Store()\n\n\ndef label():\n    store = 'a string'\n    return store\n\n\n"
        "label()\n",
        ["store"],
    ),
    # the object the factory built is only credited when its caller uses it, so both are reported
    "a notebook factory whose result is never stepped": (
        NEW_GAME + "sim = new_game(0)\n",
        ["g", "sim"],
    ),
    "a notebook factory whose result is thrown away": (NEW_GAME + "new_game(0)\n", ["g"]),
}
UNTOUCHED_CONTROLS = {
    "a notebook factory whose result is stepped": (
        NEW_GAME + "sim = new_game(0)\nsim.step('a')\n",
        {"ToyGrid.step": 1},
    ),
    "a notebook function that steps what it builds, result only read": (
        "def run_episode(seed):\n    g = ToyGrid(seed=seed)\n    g.step('a')\n    return g\n\n\n"
        "ep = run_episode(0)\nprint(ep.done)\n",
        {"ToyGrid.step": 1},
    ),
}


@pytest.mark.parametrize("case", sorted(UNTOUCHED_SHAPES))
def test_a_sink_the_notebook_builds_and_never_mutates_is_still_reported(tmp_path, case):
    cell, untouched = UNTOUCHED_SHAPES[case]
    folder = _synthetic_recipe(tmp_path, [HDR + cell])
    assert side_effect_report(folder).untouched_sink_vars() == untouched
    violations = _side_effect_violations(UNPUBLISHED[59], folder)
    assert any("never calls a mutating method" in v for v in violations), violations


@pytest.mark.parametrize("case", sorted(UNTOUCHED_CONTROLS))
def test_an_object_a_notebook_function_returns_counts_when_the_caller_uses_it(tmp_path, case):
    cell, counts = UNTOUCHED_CONTROLS[case]
    report = side_effect_report(_synthetic_recipe(tmp_path, [HDR + cell]))
    assert report.untouched_sink_vars() == [] and report.counts() == counts


# A factory's result is exempt from that rule only when the factory is itself a side-effect
# function (it may already have done the work, as recipes 43, 45 and 46 read such results). A
# pure-construction factory is checked like a direct construction.
PURE_FACTORY_HELPERS = (
    "from jev_cookbook.simulation import ToyGrid\n\n\ndef new_grid(seed):\n"
    "    return ToyGrid(seed=seed)\n\n" + REVIEW_HELPERS
)
EFFECT_FACTORY_HELPERS = (
    SIM_CLASS + "\n\ndef play_game(seed):\n    sim = Factory(seed=seed)\n    while not sim.done:\n"
    "        sim.step('build')\n    return sim\n"
)


@pytest.mark.parametrize("rank", [57, 59])
def test_a_pure_construction_factory_result_that_is_never_stepped_is_reported(tmp_path, rank):
    """The direct form `ToyGrid()` fails; so does the factory form `helpers.new_grid(0)`."""
    slug = UNPUBLISHED[rank]
    head = HDR + "queue = ReviewQueue()\nhelpers.submit_reviews(queue, [])\n"
    declared = {"helpers.submit_reviews": 1}
    builds = (("direct", "sim = ToyGrid(seed=0)\n"), ("factory", "sim = helpers.new_grid(0)\n"))
    for label, build in builds:
        folder = _synthetic_recipe(tmp_path / label, [head + build], PURE_FACTORY_HELPERS)
        _write_declaration(folder, sites=declared)
        violations = _side_effect_violations(slug, folder)
        assert any("builds ['sim'] but never calls a mutating method" in v for v in violations), (
            label,
            violations,
        )
    stepped = head + "sim = helpers.new_grid(0)\nsim.step('a')\n"
    folder = _synthetic_recipe(tmp_path / "stepped", [stepped], PURE_FACTORY_HELPERS)
    _write_declaration(folder, sites={**declared, "ToyGrid.step": 1})
    assert _side_effect_violations(slug, folder) == []


def test_a_factory_that_is_a_side_effect_function_may_have_its_result_only_read(tmp_path):
    slug = UNPUBLISHED[59]
    cell = HDR + "sim = helpers.play_game(1)\nprint(sim.t)\n"
    folder = _synthetic_recipe(tmp_path, [cell], EFFECT_FACTORY_HELPERS)
    report = side_effect_report(folder)
    assert report.counts() == {"helpers.play_game": 1} and report.handed_over == {"sim"}
    _write_declaration(folder, sites={"helpers.play_game": 1})
    assert _side_effect_violations(slug, folder) == []
    # Delete the call: the declaration is no longer met.
    gone = _synthetic_recipe(tmp_path / "gone", [HDR + "print(1)\n"], EFFECT_FACTORY_HELPERS)
    _write_declaration(gone, sites={"helpers.play_game": 1})
    assert _side_effect_violations(slug, gone)


def test_a_factory_that_returns_something_else_makes_nothing_of_the_name_it_is_bound_to(tmp_path):
    helpers_source = SIM_CLASS + "\n\ndef describe(seed):\n    return {'seed': seed}\n"
    folder = _synthetic_recipe(
        tmp_path, [HDR + "info = helpers.describe(1)\ninfo.step('x')\n"], helpers_source
    )
    assert side_effect_report(folder).counts() == {}


def test_a_factory_with_two_different_returns_is_not_guessed_at(tmp_path):
    helpers_source = (
        SIM_CLASS
        + "\n\ndef new_game(seed, small):\n    if small:\n        return Factory(seed=seed)\n"
        "    return {'seed': seed}\n"
    )
    folder = _synthetic_recipe(
        tmp_path, [HDR + "sim = helpers.new_game(1, True)\nsim.step('x')\n"], helpers_source
    )
    assert side_effect_report(folder).counts() == {}


def test_the_scaffolded_declaration_is_a_placeholder_the_guard_rejects_until_it_is_rewritten(
    tmp_path,
):
    """S4: ``tools/new_recipe.py`` scaffolds ``side_effects.json``. Left as scaffolded it fails the
    guard (it cannot be forgotten); rewritten as ``none`` it passes for a recipe without a
    simulated side effect and still fails for one that needs a simulator."""
    scaffolder = load_tool("new_recipe.py")
    catalog = REPO / "catalog" / "recipes.json"
    for mode in scaffolder.MODES:
        for rank in (31, 57):
            slug = next(r["slug"] for r in CATALOG["recipes"] if r["rank"] == rank)
            folder = scaffolder.scaffold(rank, catalog, tmp_path / mode / str(rank), mode)
            declaration, problems = read_side_effect_declaration(folder)
            assert declaration is None and "placeholder" in problems[0], problems
            assert _side_effect_violations(slug, folder) == problems
            _write_declaration(folder, none="returns typed outcomes only")
            violations = _side_effect_violations(slug, folder)
            if rank == 57:
                assert any("cannot declare none" in v for v in violations), violations
            else:
                assert violations == []


def test_the_inventory_matches_what_the_published_recipes_do_today():
    """Every inventoried recipe passes, with nothing allowlisted and nothing skipped."""
    for slug in SIDE_EFFECT_INVENTORY:
        assert _side_effect_violations(slug, RECIPES_DIR / slug) == [], slug


# --------------------------------------------------------------------------------------------
# checks 12-16: CONTRIBUTING.md section 2, the honesty rule (#218)
# --------------------------------------------------------------------------------------------
#
# Five checks, each keyed on the PRINTED value or the PROVENANCE the fixtures carry, never on
# how the source happens to be spelled. What each can and cannot say is written up for readers
# in docs/offline-and-live.md ("What the recipe guard checks about section 2"); every message
# below cites it, and the module docstring at the top of this file lists the check ids.
#
# * ``reported_provenance_matches_fixtures``: the mode the committed output reports (header,
#   ``Provenance:`` lines, the measured cell's disclosure) agrees with the provenance the stored
#   answers carry.
# * ``readme_states_fixture_provenance``: the README's ``**Mode:**`` line agrees with it too, and a
#   recipe with no live run says "not measured live".
# * ``metric_output_lines_carry_pipeline_check``: in a synthetic or scripted run, every committed
#   output line that names a metric and prints a decimal or percentage carries the label.
# * ``prose_quantities_are_printed``: a number the README or a markdown cell quotes next to a
#   metric, as a price, or as a latency or throughput is a number the run printed.
# * ``no_unhedged_quality_claim_about_jev``: in a recipe whose answers are all synthetic, no
#   sentence says Jev or the model does something correctly, reliably, well ... or is accurate,
#   fast, cheap ... without a negation, a hypothetical or an attribution in the same sentence.
# * ``synthetic_output_prints_no_token_count``: in a synthetic or scripted run, no committed
#   output line prints a token count ("262k tokens", "1,200 input tokens", "input_tokens: 1200"):
#   nothing offline measures tokens, and a character or byte count is not one (#312).

PIPELINE_CHECK_LABEL = "(a pipeline check, not a Jev result)"
SYNTHETIC_RUN_MODES = ("synthetic", "scripted")
# Every message below cites this section, which is also where the limits are written down.
HONESTY_DOC = "docs/offline-and-live.md#what-the-recipe-guard-checks-about-section-2"
HONESTY_CHECKS = (
    "reported_provenance_matches_fixtures",
    "readme_states_fixture_provenance",
    "metric_output_lines_carry_pipeline_check",
    "prose_quantities_are_printed",
    "no_unhedged_quality_claim_about_jev",
    "synthetic_output_prints_no_token_count",
)

_MODE_LINE = re.compile(
    r"^Mode: (?:offline replay of (?P<replay>\w+) fixtures|offline, (?P<scripted>scripted) backend"
    r"|(?P<live>live)\b)"
)
_PROVENANCE_LINE = re.compile(r"^Provenance: (?P<word>\w+)")
_DISCLOSURE_LINE = re.compile(
    r"^Provenance: (?P<mode>\w+)\. Not measured live: a pipeline check, not a Jev result\.$"
)
_CAPTURE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE = r"\b\d{4}-\d{2}-\d{2}\b"
# The four lines a recorded run prints about itself, exactly as ``style.run_header_text``, the
# measured cell and ``style.format_answer`` produce them. Each is matched in full, so a model or
# a date the line states beyond the fixtures' is a line this check cannot read, not a pass.
_RECORDED_HEADER = re.compile(
    r"^The answers were captured from real Jev calls to model (?P<model>\S+) "
    rf"(?:on (?P<first>{_DATE})|between (?P<from>{_DATE}) and (?P<to>{_DATE}))\. "
    r"Any numbers below describe only that recorded sample(?: of \d+ examples?)?\.$"
)
_RECORDED_MODEL_LINE = re.compile(r"^Provenance: recorded, model (?P<model>\S+)$")
_CAPTURED_LINE = re.compile(rf"^Captured: (?P<dates>{_DATE}(?:, {_DATE})*)$")
_RECORDED_ANSWER_LINE = re.compile(
    rf"^Provenance: recorded(?: \((?P<model>[^,()]+)(?:, (?P<date>{_DATE}))?\))?$"
)
_MODEL_TOKEN = re.compile(r"\bjev-\d+(?:\.\d+)+\b", re.IGNORECASE)
_README_MODE = re.compile(r"\*\*Mode:\*\*\s+(\w+)")


def _committed_output_lines(recipe_dir_: Path) -> list[tuple[str, str]]:
    """``(cell id, line)`` for every line of every code cell's committed output (printed text and
    the text/plain of a displayed value). The printed value, not the source that produced it: a
    check on these lines does not care whether a number was formatted with ``:.4f``, ``:.2f``, an
    aligned spec, or in a helper the ``print`` only mentions by name."""
    return [
        (str(cell.get("id", "?")), line)
        for cell in notebook_cells(recipe_dir_)
        if cell["cell_type"] == "code"
        for line in _output_text(cell).splitlines()
    ]


def _scripted_recipe(recipe_dir_: Path) -> bool:
    """A recipe with no stored responses whose ``helpers.py`` defines the ``script`` function and
    ``SEED`` that ``tools/new_recipe.py --mode scripted`` scaffolds (docs/recipe-template.md)."""
    try:
        tree = ast.parse((recipe_dir_ / "helpers.py").read_text("utf-8"))
    except (OSError, SyntaxError):
        return False
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assigned = {
        t.id
        for n in tree.body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    return "script" in functions and "SEED" in assigned


def _fixture_provenance(recipe_dir_: Path) -> tuple[str | None, list[str], list[str], list[str]]:
    """``(mode, models, dates, problems)`` read from what the fixtures themselves carry: the
    ``source`` of every stored answer's provenance (``responses.json -> <replay key> -> answers ->
    <question> -> provenance.source``, one level deeper than the response, which carries only its
    ``model``). ``mode`` is ``None`` when the fixtures cannot be read as one honest set, and then
    ``problems`` says why: a file that cannot be read, or an answer without provenance, is a
    problem rather than an empty set that every notebook would trivially agree with."""
    path = recipe_dir_ / "fixtures" / "responses.json"
    if not path.is_file():
        if _scripted_recipe(recipe_dir_):
            return "scripted", [], [], []
        return (
            None,
            [],
            [],
            ["no fixtures/responses.json, and helpers.py defines no `script` and `SEED`"],
        )
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        return None, [], [], [f"fixtures/responses.json cannot be read: {exc}"]
    if not isinstance(data, dict) or not data:
        return None, [], [], ["fixtures/responses.json holds no stored responses"]
    problems: list[str] = []
    sources: set[str] = set()
    models: set[str] = set()
    dates: set[str] = set()
    answers_seen = 0
    for key, response in data.items():
        answers = response.get("answers") if isinstance(response, dict) else None
        if not isinstance(answers, dict) or not answers:
            problems.append(f"response {key[:12]} stores no answers")
            continue
        for name, answer in answers.items():
            provenance = answer.get("provenance") if isinstance(answer, dict) else None
            source = provenance.get("source") if isinstance(provenance, dict) else None
            if source not in ("synthetic", "recorded"):
                problems.append(f"answer {name!r} of response {key[:12]} has provenance {source!r}")
                continue
            answers_seen += 1
            sources.add(source)
            if source == "recorded":
                model, date = provenance.get("model"), provenance.get("date")
                if isinstance(model, str) and model and model != "synthetic":
                    models.add(model)
                else:
                    problems.append(f"recorded answer {name!r} names no model")
                if isinstance(date, str) and _CAPTURE_DATE.match(date):
                    dates.add(date)
                else:
                    problems.append(f"recorded answer {name!r} has no capture date")
    if not answers_seen:
        problems.append("no stored answer carries a readable provenance")
    if len(sources) > 1:
        problems.append("the stored answers mix synthetic and recorded provenance")
    if len(models) > 1:
        problems.append(f"the recorded answers come from more than one model: {sorted(models)}")
    if problems:
        return None, sorted(models), sorted(dates), problems
    return sources.pop(), sorted(models), sorted(dates), []


def _provenance_violations(recipe_dir_: Path) -> list[str]:
    """What the committed output REPORTS about provenance, held against what the fixtures CARRY.

    Fails closed in both directions: fixtures that cannot be read, a header or a provenance line
    the parser does not find, and a mode the output states that the fixtures do not carry are all
    violations, so a reader that finds nothing cannot pass for a recipe that agrees."""
    mode, models, dates, problems = _fixture_provenance(recipe_dir_)
    violations = [f"fixtures: {problem}" for problem in problems]
    if mode is None:
        return violations
    lines = _committed_output_lines(recipe_dir_)
    reported = []
    for cell_id, line in lines:
        if line.startswith("Mode:"):
            match = _MODE_LINE.match(line)
            if match is None:
                violations.append(
                    f"cell {cell_id}: a `Mode:` line this check cannot read: {line!r}"
                )
            else:
                word = match.group("replay") or match.group("scripted") or "live"
                reported.append((cell_id, word))
    if not reported:
        violations.append("the committed output has no `Mode:` header line (`run_header`)")
    for cell_id, word in reported:
        if word != mode:
            violations.append(
                f"cell {cell_id}: the header reports {word!r} but the fixtures carry {mode!r} answers"
            )
    words = [
        (cell_id, match.group("word"), line)
        for cell_id, line in lines
        if (match := _PROVENANCE_LINE.match(line))
    ]
    if not words:
        violations.append("the committed output has no `Provenance:` line")
    allowed = {"synthetic": {"synthetic"}, "scripted": {"scripted", "synthetic"}}.get(
        mode, {"recorded"}
    )
    for cell_id, word, line in words:
        if word not in allowed:
            violations.append(
                f"cell {cell_id}: {line!r} reports {word!r} but the fixtures carry {mode!r} answers"
            )
    text = "\n".join(line for _, line in lines)
    disclosed = {m.group("mode") for _, line in lines if (m := _DISCLOSURE_LINE.match(line))}
    if mode in SYNTHETIC_RUN_MODES:
        if mode not in disclosed:
            violations.append(
                f"no `Provenance: {mode}. Not measured live: a pipeline check, not a Jev result.` "
                "line in the committed output (the measured cell's offline branch)"
            )
        for marker in ("Captured:", "captured from real Jev calls"):
            if marker in text:
                violations.append(
                    f"the committed output says {marker!r}, a recorded run's wording, "
                    f"but the fixtures carry only {mode!r} answers"
                )
    else:
        violations += _recorded_run_violations(lines, models[0], dates)
    return violations


def _recorded_run_violations(
    lines: list[tuple[str, str]], model: str, dates: list[str]
) -> list[str]:
    """A recorded run states, in its committed output, exactly the model and the capture dates the
    fixtures carry: the header (``on D`` or ``between FIRST and LAST``), every ``Provenance:
    recorded`` line (the measured cell's ``, model M`` and each answer's ``(M, D)``), and the
    ``Captured:`` lines (every date, comma separated). Two-directional: a line missing, a line
    this check cannot read, a model or a date the fixtures do not carry, and a ``jev-N.N.N`` model
    string anywhere in the output other than the fixtures' are each a violation."""
    text = "\n".join(line for _, line in lines)
    out: list[str] = []
    if "a pipeline check, not a Jev result" in text:
        out.append(
            "the committed output carries the pipeline-check disclosure but the fixtures hold "
            "recorded answers"
        )
    span = f"{dates[0]} to {dates[-1]}"
    headers = [(c, line) for c, line in lines if "captured from real Jev calls" in line]
    if not headers:
        out.append("the committed output has no recorded-run header (`run_header`)")
    for cell_id, line in headers:
        match = _RECORDED_HEADER.match(line)
        if match is None:
            out.append(f"cell {cell_id}: a recorded header this check cannot read: {line!r}")
            continue
        first = match.group("first") or match.group("from")
        last = match.group("first") or match.group("to")
        if (match.group("model"), first, last) != (model, dates[0], dates[-1]):
            out.append(
                f"cell {cell_id}: the header says model {match.group('model')} from {first} to "
                f"{last}, but the fixtures carry model {model} from {span}"
            )
    stated_model_lines = 0
    for cell_id, line in lines:
        if not line.startswith("Provenance: recorded"):
            continue
        if line.startswith("Provenance: recorded,"):
            match = _RECORDED_MODEL_LINE.match(line)
            if match is None:
                out.append(f"cell {cell_id}: a `Provenance:` line this check cannot read: {line!r}")
            elif match.group("model") != model:
                out.append(
                    f"cell {cell_id}: {line!r} names model {match.group('model')!r}, not {model!r}"
                )
            else:
                stated_model_lines += 1
            continue
        match = _RECORDED_ANSWER_LINE.match(line)
        if match is None:
            out.append(f"cell {cell_id}: a `Provenance:` line this check cannot read: {line!r}")
            continue
        if match.group("model") not in (None, model):
            out.append(
                f"cell {cell_id}: {line!r} names model {match.group('model')!r}, not {model!r}"
            )
        if match.group("date") not in (None, *dates):
            out.append(
                f"cell {cell_id}: {line!r} names date {match.group('date')!r}, not one of {dates}"
            )
    if not stated_model_lines:
        out.append(f"no `Provenance: recorded, model {model}` line in the committed output")
    stated: set[str] = set()
    captured = [(c, line) for c, line in lines if line.startswith("Captured:")]
    if not captured:
        out.append(f"no `Captured:` line naming the capture dates {dates}")
    for cell_id, line in captured:
        match = _CAPTURED_LINE.match(line)
        if match is None:
            out.append(f"cell {cell_id}: a `Captured:` line this check cannot read: {line!r}")
        else:
            stated |= set(match.group("dates").split(", "))
    if captured and stated != set(dates):
        out.append(
            f"the `Captured:` lines state capture dates {sorted(stated)} but the fixtures carry {dates}"
        )
    out += [
        f"the committed output states model {token!r} but the fixtures carry {model!r}"
        for token in sorted(set(_MODEL_TOKEN.findall(text)) - {model})
    ]
    return out


def _readme_provenance_violations(recipe_dir_: Path) -> list[str]:
    """The README's statement of the run, held against the fixtures (CONTRIBUTING.md section 2:
    "If no live run was made, the recipe README says 'not measured live'"; a recorded recipe
    names the model and the capture date)."""
    mode, models, dates, problems = _fixture_provenance(recipe_dir_)
    violations = [f"fixtures: {problem}" for problem in problems]
    if mode is None:
        return violations
    readme = recipe_dir_ / "README.md"
    if not readme.is_file():
        return [*violations, "no README.md"]
    text = " ".join(readme.read_text("utf-8").split())
    match = _README_MODE.search(text)
    if match is None:
        violations.append(
            "the README has no `**Mode:**` line under 'What was and was not measured'"
        )
    elif match.group(1) != mode:
        violations.append(
            f"the README states mode {match.group(1)!r} but the fixtures carry {mode!r}"
        )
    if mode in SYNTHETIC_RUN_MODES:
        if "not measured live" not in text.lower():
            violations.append(
                "the README never says 'not measured live' for a recipe with no live run"
            )
    else:
        violations += [
            f"the README does not state {needle!r}, a recorded recipe's model or capture date"
            for needle in (*models, *dates)
            if needle not in text
        ]
        violations += [
            f"the README states the date {extra}, which the fixtures do not carry"
            for extra in sorted(set(re.findall(_DATE, text)) - set(dates))
        ]
        violations += [
            f"the README states model {extra!r}, which the fixtures do not carry"
            for extra in sorted({t.lower() for t in _MODEL_TOKEN.findall(text)} - set(models))
        ]
    return violations


# What a printed metric is, by the words and numbers on the committed line. It needs no source at
# all, which is the point: ``METRIC_KEYWORD`` and ``FLOAT_FORMAT`` above key on a `print(` whose
# call spells a rounded float (an aligned spec is read since #270), and a format hoisted into a
# variable (#234) leaves ``test_every_printed_metric_line_carries_at_least_check`` with nothing to
# say.
OUTPUT_METRIC_WORD = re.compile(
    r"\b(coverage|accuracy|risk|precision|recall|f1|ndcg|agreement|auc|mrr|brier|"
    r"error rate|hit rate)\b",
    re.IGNORECASE,
)
# A decimal such as 0.8750 or 3.8, or a percentage; not a bare integer. A count ("15 of 19") is not
# a metric by this check's reading: the unlabelled counts of recipes 07 and 47 are #326's.
OUTPUT_NUMBER = re.compile(r"(?<![\w.])\d+\.\d+(?!\w|\.\w)|(?<![\w.])\d+(?:\.\d+)?\s?%")


def _unlabelled_metric_output_lines(recipe_dir_: Path) -> list[str]:
    """In a synthetic or scripted run, every committed output line that names a metric and prints
    a decimal or a percentage must carry ``(a pipeline check, not a Jev result)`` on the same line
    (CONTRIBUTING.md section 2: "any metric is a check that the pipeline works, and the notebook
    says so next to the number"). Whether the run is synthetic is read from the fixtures, never
    from the output's own say-so."""
    if _fixture_provenance(recipe_dir_)[0] not in SYNTHETIC_RUN_MODES:
        return []
    return [
        f"cell {cell_id}: {line.strip()[:110]!r}"
        for cell_id, line in _committed_output_lines(recipe_dir_)
        if OUTPUT_METRIC_WORD.search(line)
        and OUTPUT_NUMBER.search(line)
        and PIPELINE_CHECK_LABEL not in line
    ]


# --- prose: a quantity quoted next to a metric, a price or a latency must have been printed -------

_METRIC_NOUN = (
    r"(?:accuracy|precision|recall|f1|f-score|ndcg|coverage|risk|agreement|auc|mrr|brier|"
    r"error rate|hit rate|top-\d+|pass rate|false[- ]positive rate|false[- ]negative rate)"
)
_AMOUNT = r"(?:\d[\d,]*(?:\.\d+)?\s?%|(?<![\w.])\d[\d,]*\.\d+(?!\w|\.\w))"
_CONNECTIVES = (
    r"(?:[\s,:=()`*_~]|\b(?:is|are|was|were|be|been|would|will|could|should|can|of|at|to|in|up|down"
    r"|from|only|just|about|around|roughly|nearly|exactly|reaches|reached|rises|rose|falls|fell"
    r"|drops|dropped|climbs|climbed|stays|stayed|remains|remained|equals|becomes|became|comes)\b)*"
)
_METRIC_THEN_AMOUNT = re.compile(
    rf"\b(?P<n>{_METRIC_NOUN})\b{_CONNECTIVES}(?P<q>{_AMOUNT})", re.IGNORECASE
)
_AMOUNT_THEN_METRIC = re.compile(
    rf"(?P<q>{_AMOUNT})[\s`*_~]*\b(?P<n>{_METRIC_NOUN})\b", re.IGNORECASE
)
# Risk is one minus accuracy among the answered (``evaluate_selective``), so a quoted risk is
# backed by a printed accuracy and the other way round (recipe 05 quotes a validation risk of
# 0.0526 beside a printed accuracy of 0.9474).
_COMPLEMENTARY_RATES = frozenset({"risk", "accuracy", "error rate"})
_RATE_LINE = re.compile(r"\b(?:accuracy|risk|error rate)\b", re.IGNORECASE)
# A digit run glued on its left to an ASCII letter or an underscore, with its thousands-group and
# decimal tails (``sku1.93``, ``sku1.2.93``, ``x1,250``), is part of an identifier, not a
# quantity (#542).
# ``_mask_glued`` replaces every digit of such a token by ``#`` before any pattern below reads the
# text, so the patterns need no boundary of their own and cannot restart inside a refused token:
# ``sku93%``, ``sku1.93%`` and ``v1.180ms`` offer nothing, while ``180ms``, ``accuracy,93%``,
# ``0.5,93%`` and a cell after a glued id (``t01,0.93``, ``F1,93%``) are read as before. The tail
# takes a comma only as a thousands group (``,`` and exactly three digits), so a following CSV
# cell is not swallowed; a cell of exactly three digits right after an id (``t01,930``) is.
_GLUED_TOKEN = re.compile(r"(?<=[A-Za-z_])\d+(?:,\d{3}(?!\d))*(?:\.\d+)*")


def _mask_glued(text: str, *, keep_f1: bool = False) -> str:
    """``text`` with the digits of every glued token (``_GLUED_TOKEN``) replaced by ``#``, one
    for one, so positions are unchanged. ``keep_f1`` leaves the metric word ``F1`` readable, for
    the prose side, whose metric nouns include ``f1``."""

    def mask(m: re.Match) -> str:
        if keep_f1 and m.group(0) == "1" and text[m.start() - 1] in "fF":
            before = text[m.start() - 2] if m.start() >= 2 else " "
            if not (before.isalnum() or before == "_"):
                return m.group(0)
        return re.sub(r"\d", "#", m.group(0))

    return _GLUED_TOKEN.sub(mask, text)


_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# A price, as a price per unit of work ("$0.0004 a call"), or as a price in a sentence that talks
# about cost and about Jev, the model or the API. A bare "$500" in a sentence about a fixture's
# invoice is a number in the example, not a claim about Jev.
_PRICE_AMOUNT = (
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?"
    r"(?:USD|EUR|GBP|cents?|dollars?)\b)"
)
_UNIT_OF_WORK = (
    r"(?:call|request|token|query|queries|inference|decision|answer|question|example|prediction"
    r"|1k|1,000|1m|million)s?\b"
)
_PRICE_PER_UNIT = re.compile(
    rf"(?P<q>{_PRICE_AMOUNT}\s?(?:per|a|an|each|every|/)\s?{_UNIT_OF_WORK})", re.IGNORECASE
)
_COST_WORD = re.compile(
    r"\b(?:cost|costs|costing|price|prices|priced|pricing|charge|charges|charged|billing|bills?)\b",
    re.IGNORECASE,
)
_ABOUT_JEV = re.compile(r"\b(?:Jev|the model|the API|System One|inference)\b", re.IGNORECASE)
_LATENCY_MS = re.compile(r"(?P<q>\d[\d,]*(?:\.\d+)?\s?(?:ms|milliseconds?)\b)", re.IGNORECASE)
_THROUGHPUT = re.compile(
    r"(?P<q>\d[\d,]*(?:\.\d+)?\s?(?:calls?|requests?|tokens?)\s?(?:/|per )\s?"
    r"(?:s|sec|second|minute)\b)",
    re.IGNORECASE,
)
_SECONDS = re.compile(r"(?P<q>\d[\d,]*(?:\.\d+)?\s?(?:seconds?|secs?|minutes?)\b)", re.IGNORECASE)
# A duration is a claim about Jev when the sentence says latency or response time, or says slow,
# fast, speed or takes AND names Jev, the model, the API, inference or a live run. A sentence about
# how long the notebook, an install or the offline replay takes names none of these, and a recipe
# pull request, which cannot edit this file, would have no way to answer a failure on it.
_SERVICE_SPEED_WORD = re.compile(r"\b(?:latency|response time)\b", re.IGNORECASE)
_SPEED_WORD = re.compile(r"\b(?:slow|fast|speed|takes?)\b", re.IGNORECASE)
_LIVE_RUN = re.compile(r"\blive\b", re.IGNORECASE)
# The pool's tokenizer (#542). A digit run glued on its left to an ASCII letter or an underscore is
# part of an identifier (a 7-character git short SHA, a base64 or base32 id, a mixed-case id,
# ``run_42``), not a quantity, and so is the thousands-group and decimal tails of that run
# (``v1.5``, ``x1,250``). The ``glued`` alternative matches the whole token and ``_number_matches``
# drops it, so the scan resumes after it and cannot restart at one of its later digits. ``180ms``
# keeps its trailing unit: only the left boundary matters. A digit run separated from its letters
# by other punctuation (``id-42``) is still read, and so is one glued to a non-ASCII letter
# (``\u00e993``).
_NUMBER = re.compile(
    r"(?P<glued>(?<=[A-Za-z_])\d+(?:,\d{3}(?!\d))*(?:\.\d+)*)"
    r"|(?P<n>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
)


def _number_matches(text: str) -> list[re.Match]:
    return [m for m in _NUMBER.finditer(text) if m.group("n") is not None]


def _decimals(text: str) -> list[Decimal]:
    return [Decimal(m.group("n").replace(",", "")) for m in _number_matches(text)]


def _quoted_candidates(quote: str) -> list[tuple[Decimal, int]]:
    """``(value, decimal places)`` readings of a quoted amount: a percentage is read as itself
    and as the fraction it stands for (97.4% as 97.4 and as 0.974)."""
    digits = _number_matches(quote)
    if not digits:
        return []
    value = Decimal(digits[0].group("n").replace(",", ""))
    places = max(0, -value.as_tuple().exponent)
    if "%" in quote:
        return [(value, places), (value / 100, places + 2)]
    return [(value, places)]


def _is_printed(quote: str, printed: list[Decimal]) -> bool:
    """Whether some printed number is ``quote``'s value at the quote's own precision: the same
    number, or a longer printed number that rounds to it (0.9167 printed, 0.92 quoted; 0.974
    printed, 97.4% quoted). Precision-independent on purpose: a ``:.2f`` and a ``:.4f`` print of
    one value are one value. Rounds half up and half even, so a printed 0.8650 backs 0.87 and
    0.86. A quoted percentage is read only as the fraction it stands for (93% as 0.93), so its
    pool holds fractions, never bare magnitudes: a printed 93 does not back 93% (#536). What may
    enter that pool is decided by ``_percentage_fractions``."""
    candidates = _quoted_candidates(quote)
    if "%" in quote:
        candidates = candidates[-1:]
    for value, places in candidates:
        step = Decimal(1).scaleb(-places)
        for number in printed:
            if number == value:
                return True
            if -number.as_tuple().exponent > places and value in (
                number.quantize(step, ROUND_HALF_UP),
                number.quantize(step, ROUND_HALF_EVEN),
            ):
                return True
    return False


# A link's text may hold one level of brackets and code spans (``[`review`](...)``). An image
# (``![alt](...)``) is not a link: its alt text is left as it was, with the target dropped (#713).
_LINK_TEXT = r"((?:[^\[\]]|\[[^\]]*\])*)"
_INLINE_LINK = re.compile(r"(?<!!)\[" + _LINK_TEXT + r"\]\([^)]*\)")
_REFERENCE_LINK = re.compile(r"(?<!!)\[" + _LINK_TEXT + r"\]\[[^\]]*\]")
_REFERENCE_DEFINITION = re.compile(r"^ {0,3}\[([^\]]+)\]:[ \t]*\S+.*$", re.MULTILINE)
_SHORTCUT_LINK = re.compile(r"(?<!!)\[([^\[\]]+)\](?![\[(:])")


def _unwrap_links(text: str) -> str:
    """``[text](target)``, ``[text][ref]``, ``[text][]`` and ``[text]`` (when a ``[text]: url``
    definition exists) become ``text``: the target is a URL, not a claim, and a closing ``]`` is
    not a connective between a linked metric word and its figure (#713)."""
    text = _INLINE_LINK.sub(r"\1", text)
    labels = {m.group(1).strip().lower() for m in _REFERENCE_DEFINITION.finditer(text)}
    text = _REFERENCE_LINK.sub(r"\1", text)
    if labels:
        text = _SHORTCUT_LINK.sub(
            lambda m: m.group(1) if m.group(1).strip().lower() in labels else m.group(0), text
        )
    return re.sub(r"(!\[[^\]]*\])\([^)]*\)", r"\1", text)


def _clean_markdown(text: str) -> str:
    """``text`` less fenced code, HTML comments and link targets, which hold commands and URLs,
    not claims, with each link reduced to its text. Line breaks are kept: they are what
    ``_markdown_units`` splits on."""
    text = re.sub(r"^\s*(```|~~~).*?^\s*\1", " ", text, flags=re.DOTALL | re.MULTILINE)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    return _unwrap_links(text)


_MD_HEADING = re.compile(r"\s*#{1,6}\s")
_MD_TABLE_ROW = re.compile(r"\s*\|")
_MD_LIST_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)])\s")


def _markdown_units(text: str) -> list[str]:
    """The statements a markdown block makes, each whitespace-collapsed: a heading, a table row,
    a list item (with its wrapped continuation lines) and a paragraph are separate units, so a
    hedge word in a heading or in the next bullet can never excuse a sentence in another unit.
    Sentence punctuation then splits a unit further (``_sentences``)."""
    units: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            units.append(" ".join(" ".join(current).split()))
            current.clear()

    for line in text.splitlines():
        if not line.strip():
            flush()
        elif _MD_HEADING.match(line) or _MD_TABLE_ROW.match(line):
            flush()
            current.append(line)
            flush()
        elif _MD_LIST_ITEM.match(line):
            flush()
            current.append(line)
        else:
            current.append(line)
    flush()
    return units


def _prose_blocks(recipe_dir_: Path) -> list[tuple[str, str]]:
    """``(where, markdown)`` for the README and every notebook markdown cell, cleaned but with
    its line structure intact."""
    blocks = []
    readme = recipe_dir_ / "README.md"
    if readme.is_file():
        blocks.append(("README.md", readme.read_text("utf-8")))
    for cell in notebook_cells(recipe_dir_):
        if cell["cell_type"] == "markdown":
            blocks.append((f"notebook.ipynb cell {cell.get('id', '?')}", cell_source(cell)))
    return [(where, _clean_markdown(text)) for where, text in blocks]


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", text)


_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_BLOCKQUOTE_MARKER = re.compile(r"^ {0,3}>[ \t]?")
_DELIMITER_CELL = re.compile(r":?-+:?")


def _table_cells(row: str) -> list[str]:
    """The cells of one markdown table row: the text between unescaped pipes, each stripped. An
    outer pipe at either end of the row is not a cell boundary, so ``| a | b |`` and ``a | b``
    both give ``[a, b]``."""
    row = row.strip()
    cells = [c.strip() for c in _UNESCAPED_PIPE.split(row)]
    if row.startswith("|"):
        cells = cells[1:]
    if len(cells) > 1 and row.endswith("|") and not row.endswith("\\|"):
        cells = cells[:-1]
    return cells


def _table_line(line: str) -> tuple[str, int]:
    """``(line, depth)``: ``line`` with its blockquote markers removed, and how many there were.
    Indentation is kept and is not a reason to skip the line: a table indented four spaces is a
    table inside a list item, or an indented code block that a reader may still take for one, and
    reading it can only add a flag, never hide a claim."""
    depth = 0
    while _BLOCKQUOTE_MARKER.match(line):
        line = _BLOCKQUOTE_MARKER.sub("", line, count=1)
        depth += 1
    return line, depth


# The names of GFM's type 6 HTML blocks (CommonMark 4.6): a line opening with one of these tags is a
# block-level HTML opener.
_HTML_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details"
    "|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head"
    "|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p"
    "|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul"
)
# A line that opens a block of its own, which ends a table (GFM: a table ends at a blank line or
# at the start of another block): a heading, a fence, a list item, a thematic break, or an HTML
# block of types 1 to 6 (``<script``, ``<pre``, ``<style``, ``<textarea``, ``<!--``, ``<?``,
# ``<!X``, ``<![CDATA[`` and a block-level tag from ``_HTML_BLOCK_TAGS``). Type 7, a complete tag
# alone on its line, cannot interrupt a paragraph, so a line such as ``<span>note</span>``, ``<b>``
# or ``<sup>`` is not an opener and does not end the table. Applied to a line without a pipe only
# (a line with a pipe is always read as a row).
_BLOCK_START = re.compile(
    r"\s*(?:#{1,6}(?:\s|$)|(?:[-*+]|\d{1,9}[.)])(?:\s|$)|`{3,}|~{3,}"
    r"|<(?:script|pre|style|textarea)(?:[\s>]|$)|<!--|<\?|<![A-Za-z]|<!\[CDATA\["
    rf"|</?(?:{_HTML_BLOCK_TAGS})(?:[\s>]|/>|$)"
    r"|(?:-\s*){3,}$|(?:\*\s*){3,}$|(?:_\s*){3,}$)",
    re.IGNORECASE,
)


def _is_delimiter_row(line: str) -> bool:
    """A table's delimiter (separator) row: a pipe and cells that are all dashes, with optional
    alignment colons."""
    return bool(_UNESCAPED_PIPE.search(line)) and all(
        _DELIMITER_CELL.fullmatch(cell) for cell in _table_cells(line)
    )


class _HtmlTableReader(HTMLParser):
    """The rows of one HTML ``<table>``: each row is ``(in_thead, cells)`` and each cell is
    ``(is_header_cell, text)``, a cell with ``colspan=n`` repeated n times so the columns stay
    where they are. Inline tags in a cell are read as a space (``accuracy<br>(%)`` is two words)."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[bool, list[tuple[bool, str]]]] = []
        self._cell: list[str] | None = None
        self._is_th = False
        self._span = 1
        self._in_thead = False
        self.loose: list[str] = []

    def _close_cell(self) -> None:
        if self._cell is not None and self.rows:
            text = " ".join("".join(self._cell).split())
            self.rows[-1][1].extend([(self._is_th, text)] * self._span)
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if self._cell is None:
            self.loose.append(" ")
        if tag == "thead":
            self._close_cell()
            self._in_thead = True
        elif tag in ("tbody", "tfoot"):
            self._close_cell()
            self._in_thead = False
        elif tag == "tr":
            self._close_cell()
            self.rows.append((self._in_thead, []))
        elif tag in ("td", "th"):
            self._close_cell()
            if not self.rows:
                self.rows.append((self._in_thead, []))
            self._cell, self._is_th = [], tag == "th"
            span = dict(attrs).get("colspan") or "1"
            self._span = min(int(span), 20) if span.isdigit() and int(span) > 0 else 1
        elif self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if self._cell is None:
            self.loose.append(" ")
        if tag in ("td", "th"):
            self._close_cell()
        elif tag == "thead":
            self._close_cell()
            self._in_thead = False
        elif self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        else:
            self.loose.append(data)

    def close(self):
        super().close()
        self._close_cell()


_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)", re.DOTALL)
# An HTML ``<table>`` is read in two cases. A table that a ``</table>`` ends counts wherever its
# ``<table`` is on a line (``<div><table>``, ``Results: <table>``, a list item's indented table) and
# runs up to that end tag, across any blank line inside it; the nearest ``<table`` before the end
# tag opens it, so a ``<table`` mentioned earlier in the text does not pull in everything up to the
# next table. A table with no end tag counts only where an HTML block starts (at the start of a
# line, after any indentation and blockquote markers) and ends at the first blank line, so a
# mention in the middle of a sentence, or an unclosed table, hides no paragraph after it.
_CLOSED_HTML_TABLE = re.compile(
    r"<table\b(?:(?!<table\b).)*?</table\s*>", re.IGNORECASE | re.DOTALL
)
_OPEN_HTML_TABLE = re.compile(
    r"^(?:[ \t]*>)*[ \t]*<table\b.*?(?=\n[ \t]*\n|\Z)", re.IGNORECASE | re.DOTALL | re.MULTILINE
)


def _is_table_header_row(row: list[tuple[bool, str]]) -> bool:
    """A header row: at least one ``<th>`` cell, and every other cell empty (the corner of a
    transposed table is an empty ``<td>``). A single cell spanning the table is a title, not a
    header, and the caller passes it over."""
    return any(is_th for is_th, _ in row) and all(is_th or not text for is_th, text in row)


def _html_table_rows(reader: _HtmlTableReader) -> list[tuple[list[str], list[str]]]:
    """``(column headers, cells)`` per data row of one parsed table. The column headers are the
    last row of the ``<thead>`` when the table has one (its cells may be ``<td>`` or ``<th>``),
    otherwise the first row that is a header row (``_is_table_header_row``). Empty rows and every
    row above the header (a title row) are passed over; every row below it is a data row, ``<th>``
    or ``<td>`` cells alike (a row header is a label like a markdown table's first cell). A table
    with no header row has no column headers and every non-empty row is a data row."""
    rows = [(thead, [text for _, text in cells], cells) for thead, cells in reader.rows if cells]
    head = None
    thead_rows = [i for i, (thead, _, _) in enumerate(rows) if thead]
    if thead_rows:
        head = thead_rows[-1]
    else:
        for i, (_, _, cells) in enumerate(rows):
            title = len({id(c) for c in cells}) == 1 and len(cells) > 1
            if _is_table_header_row(cells) and not title:
                head = i
                break
    columns = rows[head][1] if head is not None else []
    return [(columns, texts) for i, (_, texts, _) in enumerate(rows) if head is None or i > head]


def _html_tables(text: str) -> tuple[list[tuple[list[str], list[str]]], str]:
    """``(rows, remaining text)`` for the HTML ``<table>`` elements of a markdown block (#698):
    each is replaced by the text it holds outside its cells (a sentence between a bare
    ``<table>`` and a later ``</table>`` is read as prose) and its rows are returned as ``(column headers, cells)``
    (``_html_table_rows``). Inline code is masked before the search, so a ``<table>`` mentioned in
    backticks is prose. Which ``<table`` counts is decided by ``_CLOSED_HTML_TABLE`` and
    ``_OPEN_HTML_TABLE``. Blockquote markers in front of a line are dropped. Nested tables are not
    told apart: the innermost one is read, and the text around it stays prose; an unclosed table
    that meets a blank line ends there, so the rows after the blank line are not read as its."""
    masked = _CODE_SPAN.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    spans = [m.span() for m in _CLOSED_HTML_TABLE.finditer(masked)]
    blanked = list(masked)
    for start, end in spans:
        blanked[start:end] = [c if c == "\n" else " " for c in masked[start:end]]
    spans += [m.span() for m in _OPEN_HTML_TABLE.finditer("".join(blanked))]
    rows: list[tuple[list[str], list[str]]] = []
    kept: list[str] = []
    end = 0
    for start, stop in sorted(spans):
        kept.append(text[end:start])
        block = "\n".join(_table_line(line)[0] for line in text[start:stop].split("\n"))
        reader = _HtmlTableReader()
        reader.feed(block)
        reader.close()
        rows += _html_table_rows(reader)
        # the text the table holds outside its cells is ordinary text, as GitHub shows it
        kept.append("\n" + "".join(reader.loose).strip() + "\n")
        end = stop
    kept.append(text[end:])
    return rows, "".join(kept)


def _scan_tables(text: str) -> tuple[list[tuple[list[str], list[str]]], str]:
    """``((column headers, data row) for each data row, remaining text)`` of a markdown block
    (#691, #698). An HTML ``<table>`` is read first (``_html_tables``) and blanked out. A markdown
    table is read as follows. A table starts at a line with
    an unescaped pipe whose next line is a delimiter row (GFM: only that second line is the
    delimiter; the cell counts of the two lines are not compared, so a delimiter of another width
    still starts a table: reading more only adds a flag). That header line and the delimiter stay
    in the remaining text, read as prose. Every line after them is a data row, returned as a cell
    list and blanked out of it, until a blank line or, for a line without a pipe, until a line
    that opens another block (``_BLOCK_START``) or sits at another blockquote depth. A line
    without a pipe in between (a filler line, an inline-tag line, a wrapped sentence) is not
    turned into a row: it stays in the remaining text, read as prose with the lines around it, and
    it does not end the table, so it hides nothing below it and is never split from its
    paragraph. A later row of dashes is a data row too, never a second delimiter. Rows may omit the outer pipes, may
    sit in a blockquote and may be indented, a list item's table included."""
    rows, text = _html_tables(text)
    lines = text.splitlines()
    plain = [_table_line(line) for line in lines]
    kept = list(lines)
    i = 0
    while i < len(lines):
        header = plain[i][0]
        if (
            i + 1 < len(lines)
            and _UNESCAPED_PIPE.search(header)
            and _is_delimiter_row(plain[i + 1][0])
        ):
            depth = plain[i][1]
            columns = _table_cells(header)
            i += 2
            while i < len(lines):
                line, line_depth = plain[i]
                if not line.strip():
                    break
                if not _UNESCAPED_PIPE.search(line) and (
                    line_depth != depth or _BLOCK_START.match(line)
                ):
                    break
                if _UNESCAPED_PIPE.search(line):
                    rows.append((columns, _table_cells(line)))
                    kept[i] = ""
                i += 1
        else:
            i += 1
    return rows, "\n".join(kept)


_BARE_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
# A cell that is only a unit, the tail of a figure split across two cells (``| 93 | % |``).
_UNIT_ONLY_CELL = re.compile(r"%|percent|pct|ms|milliseconds?|s|secs?|seconds?", re.IGNORECASE)
# Words of a column header that name the unit of the cells below it, and how a bare number of
# that column is written out with it.
_HEADER_UNITS = {
    "%": "{n}%",
    "percent": "{n}%",
    "pct": "{n}%",
    "ms": "{n} ms",
    "millisecond": "{n} ms",
    "milliseconds": "{n} ms",
    "s": "{n} seconds",
    "sec": "{n} seconds",
    "secs": "{n} seconds",
    "second": "{n} seconds",
    "seconds": "{n} seconds",
    "$": "${n}",
    "usd": "{n} USD",
    "eur": "{n} EUR",
    "gbp": "{n} GBP",
    "€": "€{n}",
    "£": "£{n}",
}
_HEADER_RATE_UNIT = re.compile(
    r"\b(calls?|requests?|tokens?)\s?(?:/|per )\s?(s|sec|second|minute)\b", re.IGNORECASE
)
_HEADER_TOKEN = re.compile(r"[%$€£]|[^\s()\[\]{}<>,;:|/]+")


def _header_unit(header: str) -> str | None:
    """The format (``"{n}%"``) that writes a bare number of the column ``header`` heads with the
    unit the header names (``value (%)``, ``latency ms``, ``cost ($)``, ``rate (calls/s)``), or
    ``None``. A header naming no unit is not a unit header."""
    rate = _HEADER_RATE_UNIT.search(header)
    if rate:
        return "{n} " + rate.group(1) + "/" + rate.group(2)
    for token in _HEADER_TOKEN.findall(header):
        if token.lower() in _HEADER_UNITS:
            return _HEADER_UNITS[token.lower()]
    return None


_INLINE_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
_FIGURE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?\s?%|(?<![\w.])\d[\d,]*\.\d+(?!\w|\.\w)")


def _plain_cell(cell: str) -> str:
    """A cell without its inline HTML tags (``accuracy<br>(%)`` is ``accuracy (%)``), the words
    whitespace-collapsed."""
    return " ".join(_INLINE_TAG.sub(" ", cell).split())


def _header_words(header: str) -> str:
    """A column header, or a label cell, as a context for the figures it heads: its words,
    without a bracketed unit (``accuracy (%)`` is ``accuracy``), a lone ``%`` or a figure. The
    unit would stand between the metric word and the figure; a figure in a header row is already
    read once as prose and is not read again for every row below it."""
    header = _FIGURE.sub(" ", _plain_cell(header))
    return " ".join(re.sub(r"[(\[][^)\]]*[)\]]|(?<!\w)%", " ", header).split())


# A cell that is itself a metric name: a metric noun (or a latency or price word) with at most two
# short qualifier words around it (``accuracy``, ``top-1 accuracy``, ``mean error rate``). A phrase
# that only ends in a metric word (``raises coverage``, ``caps risk``) is not one: prose has no
# adjacency between such a phrase and a figure in another cell either.
_METRIC_NAME_WORD = rf"(?:{_METRIC_NOUN}|latency|response time|price|cost|throughput|speed)"
_NOT_A_QUALIFIER = re.compile(
    r"^(?:the|a|an|of|to|for|and|or|in|on|at|by|with|raises?|lowers?|caps?|sets?|controls?"
    r"|limits?|improves?|reduces?|increases?|decreases?|drops?|keeps?|targets?|affects?|is|are"
    r"|must|should|can|may|if|when|than|vs|per|higher|lower|more|less|better|worse)$",
    re.IGNORECASE,
)


def _is_metric_name(cell: str) -> bool:
    if _FIGURE.search(_plain_cell(cell)):
        return False
    words = _header_words(cell).split()
    if not 1 <= len(words) <= 3:
        return False
    if any(_NOT_A_QUALIFIER.match(w) for w in words):
        return False
    return bool(re.search(rf"\b{_METRIC_NAME_WORD}\b", " ".join(words), re.IGNORECASE))


def _merge_split_figures(cells: list[str]) -> list[tuple[int, str]]:
    """``(column index, text)`` for each cell of a row, a unit-only cell (``%``, ``ms``) joined to
    the bare number before it: ``| 93 | % |`` is the one figure ``93%`` and keeps the column of
    its number."""
    merged: list[tuple[int, str]] = []
    for index, cell in enumerate(cells):
        if merged and _UNIT_ONLY_CELL.fullmatch(cell) and _BARE_NUMBER.fullmatch(merged[-1][1]):
            column, number = merged[-1]
            joined = "%" if cell.lower() in ("%", "percent", "pct") else " " + cell
            merged[-1] = (column, number + joined)
        else:
            merged.append((index, cell))
    return merged


def _table_row_quantities(
    cells: list[str], header: list[str] | None = None
) -> list[tuple[str, str]]:
    """The quotes a table data row makes (#691, #698). Every cell is read as ``<context>: <cell>``
    for each context it has, so ``| accuracy | 93% |`` quotes ``93%`` next to ``accuracy`` and
    ``| median latency | 180 ms |`` quotes a latency under the row's own words. A cell's contexts
    are the header of its column (``header``, the table's header row: ``| model | accuracy |``
    over ``| jev | 93% |``), the row's first cell (its label) and any other cell that is itself a
    metric name (``_is_metric_name``: ``| jev | accuracy | 93% |``, ``| 93% | accuracy |``), so a
    metric word in any column counts; another cell that only ends in a metric word does not
    (``| threshold | 0.65 | raises coverage |``). A bare number under a header that names a unit
    (``value (%)``, ``latency (ms)``), or in a row whose label names one
    (``| accuracy (%) | 93 |``), is read with that unit (the header's first), and a unit in its
    own cell (``| accuracy | 93 | % |``) is joined to the number before it. A cell that already
    has a unit keeps it. Inline HTML tags in a cell are read as spaces. Every cell is also read
    alone, for a cell that carries its own figure in a sentence.
    Limits: a cell with several figures quotes only the ones the prose patterns reach
    (``0.93 / 0.91`` under ``precision / recall`` quotes ``0.93``); one figure under two metric
    words (a header and a metric cell) is quoted once for each, which only adds a flag; and a
    header that is not the table's header row (a second header block) is not a context."""
    cells = [_plain_cell(c) for c in cells]
    header = [_plain_cell(h) for h in header or []]
    figures = _merge_split_figures(cells)
    label_unit = _header_unit(cells[0]) if cells else None
    found: list[tuple[str, str]] = []
    for position, (column, cell) in enumerate(figures):
        head = header[column] if column < len(header) else ""
        unit = _header_unit(head) or (label_unit if position else None)
        text = unit.format(n=cell) if unit and _BARE_NUMBER.fullmatch(cell) else cell
        contexts = [_header_words(head)] + [
            _header_words(c)
            for k, (_, c) in enumerate(figures)
            if k != position and (k == 0 or _is_metric_name(c))
        ]
        found += _quoted_quantities(text)
        for context in dict.fromkeys(c for c in contexts if c):
            found += _quoted_quantities(f"{context}: {text}")
    return list(dict.fromkeys(found))


def _table_scan(text: str) -> tuple[list[list[str]], str]:
    """``_scan_tables`` without the column headers: ``(data rows, remaining text)``."""
    rows, prose = _scan_tables(text)
    return [cells for _, cells in rows], prose


def _quoted_quantities(text: str) -> list[tuple[str, str]]:
    """``(kind, quote)`` for every quantity ``text`` quotes next to a metric word (``metric``, or
    ``rate`` for risk, accuracy and error rate, which are each other's complement), as a price
    (``price``), or as a latency or a throughput (``speed``). Plain prose: a table row is read
    through ``_table_row_quantities``."""
    found = []
    for sentence in _sentences(_mask_glued(text, keep_f1=True)):
        for pattern in (_METRIC_THEN_AMOUNT, _AMOUNT_THEN_METRIC):
            found += [
                ("rate" if m.group("n").lower() in _COMPLEMENTARY_RATES else "metric", m.group("q"))
                for m in pattern.finditer(sentence)
            ]
        found += [("price", m.group("q")) for m in _PRICE_PER_UNIT.finditer(sentence)]
        if _COST_WORD.search(sentence) and _ABOUT_JEV.search(sentence):
            found += [("price", m.group(0)) for m in re.finditer(_PRICE_AMOUNT, sentence, re.I)]
        for pattern in (_LATENCY_MS, _THROUGHPUT):
            found += [("speed", m.group("q")) for m in pattern.finditer(sentence)]
        if _SERVICE_SPEED_WORD.search(sentence) or (
            _SPEED_WORD.search(sentence)
            and (_ABOUT_JEV.search(sentence) or _LIVE_RUN.search(sentence))
        ):
            found += [("speed", m.group("q")) for m in _SECONDS.finditer(sentence)]
    return found


def _without_audit_lines(text: str) -> str:
    """``text`` with every line starting with ``AUDIT_PREFIX`` replaced by a literal ``"\\n"``,
    line by line: the line stays (so a line before it and a line after it are never spliced
    together), only its content is gone. The replacement is a literal ``"\\n"``, not necessarily
    that line's own original terminator: a ``\\r\\n``-terminated matched line is replaced by a
    one-character ``"\\n"`` instead of its own two-character terminator, and an unterminated final
    matched line (one with no terminator at all) is replaced by a ``"\\n"`` it never had. Neither
    case can fuse the text on either side: the line before the match, when there is one, keeps its
    own terminator untouched, so the two line boundaries together are still at least two
    characters; an unterminated final line gains a terminator rather than losing one, adding
    separation instead of removing any."""
    return "".join(
        "\n" if line.startswith(AUDIT_PREFIX) else line for line in text.splitlines(keepends=True)
    )


# A hash-like token: a UUID (8-4-4-4-12) or a run of at least 16 hexadecimal characters, in either
# case a mix of at least one letter and, for a UUID, at least one digit (a replay key, a SHA-256
# or SHA-1 content hash, a full git SHA, a cache key). Its digit runs are not quantities, but read
# as numbers they back almost any figure: 22 replay keys offered 71 of the integers 0 to 100
# (#376, #378). The token is bounded by hex characters, not by word characters, so a digest glued
# to ``_``, ``0x``, ``.`` or a non-hex letter (``cache_<sha>.json``) is still found. A run of 16 or
# more digits alone has no letter and stays: it is a number. A hex run of only letters carries no
# digit to back anything, so replacing it changes no pool and needs no digit requirement. One
# exception: the digits and trailing ``e`` of a float printed in scientific notation
# (``1.2345678901234567e-05``) are a quantity, so a run that is only digits plus that ``e``, with
# a signed exponent after it, is kept. A shorter digest (a 7-character git short SHA) and
# base64-style identifiers are not recognised.
_HASH_LIKE = re.compile(
    r"(?<![0-9a-f])(?=[0-9a-f-]{0,35}[a-f])(?=[0-9a-f-]{0,35}[0-9])"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"
    r"|(?<![0-9a-f])(?!\d+e[+-]\d)(?=[0-9a-f]*[a-f])[0-9a-f]{16,}(?![0-9a-f])",
    re.IGNORECASE,
)


def _without_hash_like_tokens(text: str) -> str:
    """``text`` with every hash-like token replaced by ``<hash>``, which holds no digit: the
    token's own digit runs leave the pool, and every other character of its line, a genuine
    number beside it included, stays exactly where it was (#378)."""
    return _HASH_LIKE.sub("<hash>", text)


def _pool_text(text: str) -> str:
    """``text`` as the metric pool reads it: audit-prefix lines blanked, hash-like tokens
    replaced, then the digits of every glued token masked (#542). Both pool sources (committed
    output and the recipe's own tests) go through this one chain."""
    return _mask_glued(_without_hash_like_tokens(_without_audit_lines(text)))


def _scanned_output(recipe_dir_: Path) -> str:
    """The exact text ``_printed_numbers`` scans: every code cell's committed output
    (``_output_text``) with its audit lines blanked by ``_without_audit_lines`` and its hash-like
    tokens replaced (``_pool_text``, #378), the cells joined
    by one ``"\\n"`` between their texts. Line structure is kept (a blanked audit line is still a
    line). It is the join's ``"\\n"`` that keeps two cells apart: a cell's committed text may end
    with a newline of its own, or (``print(..., end="")``) with none. Kept as one function so the
    tests can pin the join and the blanking directly."""
    return "\n".join(
        _pool_text(_output_text(cell))
        for cell in notebook_cells(recipe_dir_)
        if cell["cell_type"] == "code"
    )


# A slash starts a rate unit when a unit word follows it. The word ends at a character that is not
# an ASCII letter, digit or underscore (not ``\b``), so ``/sec²`` ends its unit while ``/step`` and
# ``/secure`` do not start one.
_RATE_DENOMINATOR = (
    r"/\s?(?:s(?:ec(?:ond)?s?)?|min(?:ute)?s?|h(?:rs?|ours?)?|days?|ms|req(?:uests?)?|calls?"
    r"|tok(?:en)?s?|samples?|quer(?:y|ies)|items?|1k)(?![A-Za-z\d_])"
)
# What follows a number that makes it something other than a fraction: a percent sign (ASCII or
# full-width U+FF05, after any run of spaces), a per-mille sign (U+2030), the word percent, per cent
# or pct,
# or a rate unit.
_PERCENT_FRACTION = re.compile(
    r"(?<![\w.])(?:0\.\d+|1\.0+)"
    rf"(?!\w|\.\w|\s*(?:[%％‰]|(?:per\s?cent|percent|pct)\b)|\s*{_RATE_DENOMINATOR})",
    re.IGNORECASE,
)


def _percentage_fractions(line: str, *, percent: bool = True) -> list[Decimal]:
    """The fractions one physical line can back a quoted percentage with (#536): a printed
    percentage (its number and ``%`` on this line) as number / 100, and an explicit unitless
    decimal fraction (0.0 to 1.0, with a decimal point). A bare integer is a count and backs
    nothing, and a number inside a price, latency, throughput or seconds figure, or followed by
    a rate unit, carries another unit: a printed ``92.6 seconds`` or ``0.926 ms`` does not back
    93%. Other unit words are not recognised, so ``0.926 widgets`` still counts as a fraction.
    A number followed by ``%`` (ASCII or full-width, after any spaces), a per-mille sign or the
    word ``percent``, ``per cent`` or ``pct`` is a percentage, never a fraction (``0.93%`` is
    0.0093). A slash
    excludes only when it starts a rate unit (``0.93/s``, ``/min``, ``/day``, ``/sample``,
    ``/query``, ``/item``, ``/tok``, ``/1k``, ``/sec`` with a superscript 2); ``0.93/0.91`` and
    ``0.93/step`` are fractions.
    Signs are ignored (``-0.93`` reads as 0.93) and a fraction needs its leading digit (``.93``
    is not read)."""
    units = [m.span() for m in re.finditer(_PRICE_AMOUNT, line, re.IGNORECASE)]
    units += [m.span() for p in (_LATENCY_MS, _THROUGHPUT, _SECONDS) for m in p.finditer(line)]
    values = [Decimal(m.group(1)) / 100 for m in _PERCENT.finditer(line)] if percent else []
    for m in _PERCENT_FRACTION.finditer(line):
        if not any(start < m.end() and m.start() < end for start, end in units):
            values.append(Decimal(m.group(0)))
    return values


def _printed_numbers(recipe_dir_: Path) -> dict[str, list[Decimal]]:
    """The numbers a quote of each kind can be backed by. A ``metric`` quote: any number a code
    cell's committed output prints, or the recipe's own ``tests/`` type (CONTRIBUTING.md section
    6: a quoted figure is allowed when "a test re-derives it through the shared helpers"). A
    ``rate`` quote (risk, accuracy, error rate): those numbers, or the complement of a number
    printed on a line that names accuracy, risk or error rate (a decimal in [0, 1] with two or more
    places, or a printed percentage). A printed percentage also backs its fraction. A ``price``
    or ``speed`` quote: only a price, a latency or a throughput the output prints with its unit,
    so a printed sample size of 180 does not back "180 ms".

    A number and its unit are read on one output line and never across a line break: a
    ``price``, latency, throughput or seconds figure, and a quoted fraction backed through a
    printed percentage, are backed only when the number and its unit sit on the same committed
    output line, so output printed on two lines (or a segment committed with no trailing newline,
    followed by one that opens with the unit) backs nothing (#380). A quoted percentage has its
    own pools, ``metric_percentage`` and ``rate_percentage`` (#536): fractions from a printed
    percentage on one line or an explicit decimal fraction (``_percentage_fractions``), read from
    committed output and from the recipe's tests; a bare printed number or a number with another
    unit backs none. The rate variant adds the complement on a line naming accuracy, risk or error
    rate. Prose may wrap a quote across lines; committed output is read line by line.

    The audited route's one committed ``AUDIT_PREFIX`` line (#213, #376) is a machine-readable
    ledger, not a printed quantity: its 64-character hex replay keys are excluded here, per line,
    before any digit scan sees them, so they cannot back a fabricated prose figure --
    ``_without_audit_lines`` blanks a matched line's content rather than deleting it, so the line
    stays a line (``_scanned_output`` keeps that structure, pinned directly by a test). This is
    symmetric across both sources of the ``metric`` pool: the same blanking is applied to the
    committed output and to the recipe's own ``tests/*.py`` text, matching
    ``line.startswith(AUDIT_PREFIX)`` on each physical line of either source. That match requires
    the prefix at the very first character of the line, so it only reaches the ledger reproduced
    alone on its own line (e.g. a triple-quoted ``EXPECTED`` assignment); an indented occurrence or
    a one-line assignment where a quote character precedes the prefix is a different shape this
    match does not reach on either arm (#378 measures this). Since #378, every hash-like token
    (``_HASH_LIKE``) is replaced by a digit-free placeholder in both sources as well, wherever it
    sits on a line, which also takes the replay keys of an indented or mid-line ledger out of the
    pool; the line-prefix exclusion stays, for the ledger's other fields. A cell that prints the
    audit line alongside a genuine metric line still has the metric line counted. The ledger's own
    integrity is checked separately, and far more strictly, by
    ``readme_budget_note_matches_request_audit`` against ``request_budget.json``, for every
    published recipe and for ``recipes/_template`` (#381); this exclusion removes nothing that check
    relies on."""
    output = _scanned_output(recipe_dir_)
    metric = _decimals(output)
    fractions = [f for line in output.splitlines() for f in _percentage_fractions(line)]
    tests_dir = recipe_dir_ / "tests"
    if tests_dir.is_dir():
        for path in sorted(tests_dir.glob("*.py")):
            test_text = _pool_text(path.read_text("utf-8"))
            metric += _decimals(test_text)
            fractions += [f for line in test_text.splitlines() for f in _percentage_fractions(line)]
    # (#380): the unit patterns bind them with ``\s?``, which a newline satisfies, and a segment
    # committed without its own trailing newline would otherwise fuse to the next one.
    output_lines = output.splitlines()
    price = [
        n
        for line in output_lines
        for m in re.finditer(_PRICE_AMOUNT, line, re.IGNORECASE)
        for n in _decimals(m.group(0))
    ]
    speed = [
        n
        for line in output_lines
        for pattern in (_LATENCY_MS, _THROUGHPUT, _SECONDS)
        for m in pattern.finditer(line)
        for n in _decimals(m.group("q"))
    ]
    percentages = [Decimal(m.group(1)) for line in output_lines for m in _PERCENT.finditer(line)]
    metric += [pct / 100 for pct in percentages]
    complements: list[Decimal] = []
    fraction_complements: list[Decimal] = []
    for line in output_lines:
        if not _RATE_LINE.search(line):
            continue
        fraction_complements += [1 - Decimal(m.group(1)) / 100 for m in _PERCENT.finditer(line)]
        fraction_complements += [
            1 - f for f in _percentage_fractions(line, percent=False) if -f.as_tuple().exponent >= 2
        ]
        complements += [
            1 - n for n in _decimals(line) if 0 <= n <= 1 and -n.as_tuple().exponent >= 2
        ]
        complements += [100 - Decimal(m.group(1)) for m in _PERCENT.finditer(line)]
    return {
        "metric": metric,
        "rate": metric + complements,
        "price": price,
        "speed": speed,
        "metric_percentage": fractions,
        "rate_percentage": fractions + fraction_complements,
    }


def _prose_quotes(recipe_dir_: Path) -> list[tuple[str, str, str]]:
    """``(where, kind, quote)`` for every quantity the README and the notebook markdown quote.
    Table data rows are read cell by cell under their row label (``_table_scan``); everything
    else, a table's header row included, is read as prose."""
    found = []
    for where, text in _prose_blocks(recipe_dir_):
        rows, prose = _scan_tables(text)
        for columns, row in rows:
            found += [(where, kind, quote) for kind, quote in _table_row_quantities(row, columns)]
        for unit in _markdown_units(prose):
            found += [(where, kind, quote) for kind, quote in _quoted_quantities(unit)]
    return found


def _unprinted_quantities(recipe_dir_: Path) -> list[str]:
    printed = _printed_numbers(recipe_dir_)
    return [
        f"{where}: {quote.strip()!r} is quoted but no committed output of the notebook prints it"
        for where, kind, quote in _prose_quotes(recipe_dir_)
        if not _is_printed(quote, printed[f"{kind}_percentage" if "%" in quote else kind])
    ]


# --- prose: Jev or the model, said to do something well, with nothing hedging the sentence ---------

_SUBJECT = r"(?:Jev|the model|System One)(?!['’]s)\b"
_ADVERB = (
    r"(?<!how )(?<!as )\b(?:correctly|reliably|accurately|robustly|consistently|perfectly"
    r"|flawlessly|properly|well)\b(?!-)"
)
_ADJECTIVE = (
    r"(?:very |highly |extremely |quite |always )?(?:accurate|reliable|robust|fast|quick|cheap"
    r"|inexpensive|affordable|precise|dependable|trustworthy|good|excellent|better|best|superior"
    r"|right|correct|perfect)\b"
)
_QUALITY_CLAIMS = (
    # ``_sentences`` has already split on a full stop followed by space, so a "." left inside a
    # sentence is a decimal point, a version or a file name; the span may cross it ("Jev handles
    # 97.4% of these messages reliably"). It still stops at "!" and "?".
    re.compile(rf"\b{_SUBJECT}[^!?]{{0,80}}?{_ADVERB}", re.IGNORECASE),
    re.compile(
        rf"\b{_SUBJECT}\s+(?:is|are|was|were|gets?|got|stays?|remains?)\s+{_ADJECTIVE}",
        re.IGNORECASE,
    ),
    re.compile(rf"\b{_SUBJECT}\s+(?:outperforms?|beats?|surpass\w*|exceeds?)\b", re.IGNORECASE),
)
# What makes a sentence about Jev not an assertion that Jev does well: a negation or a disclosure
# ("not measured live"), a hypothetical, or an attribution to documentation.
_HEDGES = re.compile(
    r"\b(?:not|nothing|never|cannot|without|whether|if|would|could|may|might|unless"
    r"|says?|said|according)\b|n['’]t\b",
    re.IGNORECASE,
)


def _excerpt(sentence: str, match: re.Match) -> str:
    """The sentence, or, for a long one, the stretch around the match: what a builder must change
    is always in what is printed."""
    if len(sentence) <= 240:
        return sentence
    start, end = max(0, match.start() - 100), match.end() + 100
    return ("..." if start else "") + sentence[start:end] + ("..." if end < len(sentence) else "")


def _claims_in_markdown(text: str) -> list[str]:
    """Each sentence of ``text`` (a markdown block) that says Jev or the model does something
    well and has no hedge in its OWN sentence, heading, list item or table row."""
    found = []
    for unit in _markdown_units(_clean_markdown(text)):
        for sentence in _sentences(unit):
            for pattern in _QUALITY_CLAIMS:
                match = pattern.search(sentence)
                if match:
                    if not _HEDGES.search(sentence):
                        found.append(_excerpt(sentence, match))
                    break
    return found


def _unhedged_quality_claims(recipe_dir_: Path) -> list[str]:
    """In a recipe whose stored answers are all synthetic (or scripted), each sentence of the
    README or a markdown cell that says Jev or the model does something correctly, reliably,
    well ... or is accurate, fast, cheap ..., or outperforms something, and carries no negation,
    hypothetical or attribution in that same sentence (a heading, a bullet and a table row are
    each their own unit). Synthetic answers were written, so no sentence may say how well the
    model does. Does not apply to a recorded recipe, which the reviewer holds to its model, date
    and N."""
    if _fixture_provenance(recipe_dir_)[0] not in SYNTHETIC_RUN_MODES:
        return []
    return [
        f"{where}: {claim!r}"
        for where, text in _prose_blocks(recipe_dir_)
        for claim in _claims_in_markdown(text)
    ]


def _honesty_failure(check: str, violations: list[str]) -> str:
    return f"{check}: " + "; ".join(violations) + f" (see {HONESTY_DOC})"


@pytest.mark.parametrize("recipe", guarded("reported_provenance_matches_fixtures"))
def test_the_reported_provenance_agrees_with_what_the_fixtures_carry(recipe):
    """CONTRIBUTING.md section 2 (#218 item 3): "The notebook states near the top which mode it
    ran in." The vocabulary form of this check (a notebook that says ``recorded`` must have a
    non-synthetic response) is rejected: all 50 published recipes and the template say
    ``recorded`` (143 times across 35 of them when #218 measured it), in the contract's own
    counterfactual and for a simulated action logged as recorded, so it would reject every
    one. The structural form is exact: ``backend.mode`` is derived from the fixtures and printed
    into the committed output (``Mode:`` header, ``Provenance:`` lines, the measured cell's
    disclosure), and this check asserts that what is printed is what the fixtures carry. It reads
    the fixtures one level below the response, at ``answers -> <name> -> provenance.source``
    (``test_the_provenance_reader_agrees_with_the_replay_backend`` proves the reader against the
    shared backend), and fails closed: nothing found is a violation, not a pass. It cannot tell
    whether the prose around an honestly declared synthetic run overclaims."""
    violations = _provenance_violations(recipe_dir(recipe))
    assert not violations, _honesty_failure("provenance", violations)


@pytest.mark.parametrize("recipe", guarded("readme_states_fixture_provenance"))
def test_the_readme_states_the_mode_the_fixtures_carry(recipe):
    """CONTRIBUTING.md section 2: the README says "not measured live" when no live run was made,
    and a recorded recipe names the model and the capture dates. Its ``**Mode:**`` line must name
    the mode the fixtures carry. The README is published material in exactly the way a notebook is
    (#218's second reproduction put a fabricated claim in both)."""
    violations = _readme_provenance_violations(recipe_dir(recipe))
    assert not violations, _honesty_failure("README provenance", violations)


@pytest.mark.parametrize("recipe", guarded("metric_output_lines_carry_pipeline_check"))
def test_every_metric_line_of_a_synthetic_run_carries_the_pipeline_check_label(recipe):
    """CONTRIBUTING.md section 2: "In a synthetic run, any metric is a check that the pipeline
    works, and the notebook says so next to the number." Read off the committed output, so it
    holds whatever precision (``:.2f``, ``:.4f``), alignment or hoisting produced the number.

    What ``test_every_printed_metric_line_carries_at_least_check`` (check 4b) does not cover, and
    this does: that check keys on a ``print(`` whose call spells ``{x:.Nf}`` together with a
    metric keyword, so a hoisted format string (#234), a helper that prints, or ``%``/``round()``
    formatting is outside it (an aligned spec such as ``{x:>13.4f}`` is inside it since #270). It also does not cover a label that is in the source but absent from the committed
    output. The limits of this one: a count with no decimal ("15 of 15") is not a metric here
    (#326 owns those), the label must be on the same line as the number, and a metric whose line
    names none of ``OUTPUT_METRIC_WORD`` is invisible."""
    violations = _unlabelled_metric_output_lines(recipe_dir(recipe))
    assert not violations, _honesty_failure(
        f"a metric printed without {PIPELINE_CHECK_LABEL}", violations
    )


@pytest.mark.parametrize("recipe", guarded("prose_quantities_are_printed"))
def test_a_quantity_quoted_in_prose_is_a_number_the_run_printed(recipe):
    """CONTRIBUTING.md section 2: no sentence about Jev's quality, latency or cost appears unless
    it comes from recorded live inference. The decidable part of that is a NUMBER: a percentage or
    decimal quoted next to a metric word, a price, a latency or a throughput in the README or a
    markdown cell is a number the notebook's committed output printed (rounding, a percentage
    for a fraction and a thousands separator are the same number), or one the recipe's own tests
    type. A fabricated "97.4% accuracy, 180 ms median latency, $0.0004 a call" quotes numbers
    nothing printed, in both places. Limits: it checks that the number EXISTS in the output, not
    that it is the right number in the right place (a quoted 1.0000 is backed by any printed
    1.0000), and it reads no number that is not next to a metric word, a price or a latency, and no
    number spelled in words."""
    violations = _unprinted_quantities(recipe_dir(recipe))
    assert not violations, _honesty_failure("quoted quantity", violations)


@pytest.mark.parametrize("recipe", guarded("no_unhedged_quality_claim_about_jev"))
def test_no_sentence_says_jev_does_well_in_a_synthetic_recipe(recipe):
    """CONTRIBUTING.md section 2 (#218 item 1, the narrow form): where every stored answer is
    synthetic, no README or markdown sentence says Jev or the model does something correctly,
    reliably, well ... or is accurate, fast, cheap ..., unless the same sentence negates,
    hedges or attributes it ("not measured live", "would", "TypeSafe's notes say ..."). The wider
    form, any evaluative word in a sentence that mentions Jev, is rejected: see the module
    docstring. This is a floor: a synonym passes, and so does a claim with no evaluative word at
    all ("Jev judges from the evidence as a whole"); the reviewer reads for those."""
    violations = _unhedged_quality_claims(recipe_dir(recipe))
    assert not violations, _honesty_failure("claim about Jev", violations)


# A number printed as a count of tokens: "262k tokens", "1,200 input tokens", "a 64k-token
# request", or a token field printed with its value ("input_tokens: 1200", "'tokens': 37").
# Prose about authentication tokens ("a refresh token stays valid for 30 days") puts no number
# directly in front of the word, and a field printed as ``None`` or ``not measured`` has no digit.
_TOKEN_COUNT = re.compile(
    r"\b\d[\d,]*(?:\.\d+)?(?:\s?[km]\b)?[\s-]?"
    r"(?:(?:input|output|prompt|completion|context|total)[\s-])?tokens?\b"
    r"|(?<![a-z])tokens?\b['\"]?\s*[:=]\s*\d",
    re.IGNORECASE,
)


def _printed_token_counts(recipe_dir_: Path) -> list[str]:
    """In a run whose stored answers are synthetic or scripted, every committed output line that
    prints a token count. Every cell is read, the measured cell included: offline, that cell
    prints the not-measured disclosure, and nothing an offline run computes is a token count (a
    locally computed context size is characters or bytes). A recorded run is out of scope here;
    the reviewer holds its numbers to its model, date and N."""
    if _fixture_provenance(recipe_dir_)[0] not in SYNTHETIC_RUN_MODES:
        return []
    return [
        f"cell {cell_id}: {line.strip()!r}"
        for cell_id, line in _committed_output_lines(recipe_dir_)
        if _TOKEN_COUNT.search(line)
    ]


@pytest.mark.parametrize("recipe", guarded("synthetic_output_prints_no_token_count"))
def test_a_synthetic_run_prints_no_token_count(recipe):
    """#312 (CONTRIBUTING.md section 2, docs/multimodal-track.md): a character count or an offline
    run does not demonstrate a token count, so a synthetic or scripted notebook that prints "262k
    tokens", "1,200 input tokens" or "input_tokens: 1200" states a measurement nobody made. Keyed
    on the committed output and on the provenance the fixtures carry. Limits: it reads output, not
    prose (``prose_quantities_are_printed`` and the reviewer cover a quoted figure); a count
    spelled without a digit ("two hundred tokens") passes; and an in-fiction count of
    authentication tokens printed with a number in front ("3 tokens revoked") fails, so such a
    recipe says "3 credentials revoked" instead."""
    violations = _printed_token_counts(recipe_dir(recipe))
    assert not violations, _honesty_failure("a token count printed by an offline run", violations)


# --- the tests for checks 12-16 ----------------------------------------------------------------
#
# Every case below runs against a throwaway copy of the template (or of a published recipe), is
# built by one mutation of what was committed, and asserts the mutation took effect exactly where
# intended (``_edit_streams``/``_edit_markdown``/``_edit_text`` insist on the expected number of
# hits), so a mutation that silently missed its target cannot pass for a check that caught it.

_RECORDED_MODEL = "jev-1.13.0"
_RECORDED_DATE = "2026-03-02"


def _edit_streams(folder: Path, old: str, new: str, count: int | None = 1) -> None:
    """Replace ``old`` with ``new`` in every committed stream output of the notebook; exactly
    ``count`` occurrences must exist (``None``: at least one)."""
    path = folder / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    hits = 0
    for cell in notebook["cells"]:
        for output in cell.get("outputs", []):
            if output.get("output_type") == "stream":
                text = "".join(output["text"])
                hits += text.count(old)
                output["text"] = text.replace(old, new).splitlines(keepends=True)
    assert hits >= 1 if count is None else hits == count, f"{old!r}: found {hits}"
    path.write_text(json.dumps(notebook), "utf-8")


def _append_cell(
    folder: Path,
    cell_type: str,
    text: str,
    cell_id: str = "honesty-probe",
    *,
    terminated: bool = True,
    segments: list[str] | None = None,
    outputs: list[dict] | None = None,
) -> None:
    """A markdown cell with ``text``, or a code cell with committed output. Code cells default
    to one stdout stream containing ``text`` plus a newline. ``segments`` supplies exact stream
    parts before ``terminated`` adds each part's newline; explicit ``outputs`` overrides them.
    Unterminated probes keep the ``sys.stdout.write`` source used for that fixture shape."""
    if segments and outputs is not None:
        raise ValueError("pass segments or outputs, not both: outputs would silently win")
    path = folder / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    cell = {"cell_type": cell_type, "id": cell_id, "metadata": {}, "source": [text]}
    if cell_type == "code":
        if segments is None:
            segments = [text]
        if outputs is None:
            suffix = "\n" if terminated else ""
            outputs = [
                {"name": "stdout", "output_type": "stream", "text": [segment + suffix]}
                for segment in segments
            ]
        cell["execution_count"] = None
        cell["outputs"] = outputs
        cell["source"] = (
            ["print('probe')\n"] if terminated else ["import sys\n", "sys.stdout.write('probe')\n"]
        )
    notebook["cells"].append(cell)
    path.write_text(json.dumps(notebook), "utf-8")


def _edit_markdown(folder: Path, old: str, new: str) -> None:
    """Replace ``old`` (which occurs in exactly one markdown cell, once) with ``new``."""
    path = folder / "notebook.ipynb"
    notebook = json.loads(path.read_text("utf-8"))
    hits = 0
    for cell in notebook["cells"]:
        if cell["cell_type"] == "markdown":
            source = cell_source(cell)
            hits += source.count(old)
            cell["source"] = source.replace(old, new).splitlines(keepends=True)
    assert hits == 1, f"{old!r}: found {hits} in markdown"
    path.write_text(json.dumps(notebook), "utf-8")


def _edit_readme(folder: Path, pattern: str, replacement: str, count: int = 1) -> None:
    """Regex-replace in the README, case-insensitively; exactly ``count`` matches must exist."""
    path = folder / "README.md"
    text, hits = re.subn(pattern, replacement, path.read_text("utf-8"), flags=re.IGNORECASE)
    assert hits == count, f"{pattern!r}: matched {hits} times in README.md"
    path.write_text(text, "utf-8")


def _rewrite_responses(folder: Path, change) -> None:
    """Apply ``change(index, answer)`` to every stored answer of the fixtures."""
    path = folder / "fixtures" / "responses.json"
    data = json.loads(path.read_text("utf-8"))
    index = 0
    for response in data.values():
        for answer in response["answers"].values():
            change(index, answer)
            index += 1
    path.write_text(json.dumps(data), "utf-8")


def _record(index: int, answer: dict) -> None:
    answer["provenance"] = {"source": "recorded", "model": _RECORDED_MODEL, "date": _RECORDED_DATE}


def _make_recorded(folder: Path, dates: tuple[str, ...] = (_RECORDED_DATE,)) -> None:
    """Turn a copy of the template into the recipe it would be if its answers had been captured
    live on ``dates``: recorded fixtures, and the committed output and README that such a run
    states (``run_header``'s recorded form, ``Provenance: recorded, model ...``, ``Captured:``
    and the ``recorded (model, date)`` line ``show_answer`` prints, no pipeline-check label)."""
    _rewrite_responses(
        folder,
        lambda i, a: a.update(
            provenance={
                "source": "recorded",
                "model": _RECORDED_MODEL,
                "date": dates[i % len(dates)],
            }
        ),
    )
    when = f"on {dates[0]}" if len(dates) == 1 else f"between {dates[0]} and {dates[-1]}"
    _edit_streams(
        folder,
        "Mode: offline replay of synthetic fixtures, pipeline check on a fixture sample of 20 "
        "examples\nMetrics in this run are checks that the pipeline works. They are not Jev "
        "results.",
        "Mode: offline replay of recorded fixtures\nThe answers were captured from real Jev calls "
        f"to model {_RECORDED_MODEL} {when}. Any numbers below describe only that "
        "recorded sample of 20 examples.",
    )
    _edit_streams(
        folder,
        "Provenance: synthetic. Not measured live: a pipeline check, not a Jev result.",
        f"Provenance: recorded, model {_RECORDED_MODEL}\nCaptured: {', '.join(dates)}",
    )
    _edit_streams(
        folder,
        "Provenance: synthetic\n",
        f"Provenance: recorded ({_RECORDED_MODEL}, {dates[0]})\n",
    )
    _edit_streams(folder, f" {PIPELINE_CHECK_LABEL}", "", count=None)
    _edit_readme(
        folder,
        r"- \*\*Mode:\*\* synthetic \(offline replay of hand-written answers\)\. Not measured live\.",
        f"- **Mode:** recorded (answers captured from {_RECORDED_MODEL} {when}).",
    )


def _violations(folder: Path) -> dict[str, list[str]]:
    return {
        "provenance": _provenance_violations(folder),
        "readme": _readme_provenance_violations(folder),
        "metric": _unlabelled_metric_output_lines(folder),
        "quantity": _unprinted_quantities(folder),
        "claim": _unhedged_quality_claims(folder),
    }


def _all_clear(folder: Path) -> bool:
    return not any(_violations(folder).values())


def test_the_published_set_and_the_template_are_clear_of_all_five_honesty_checks():
    """The sweep the issue asks for, in one place: no published recipe is allowlisted for any of
    checks 12-16, so none of them is in ``tests/recipe_guard_known_failures.py``."""
    assert not {check for _, check in KNOWN_FAILURES} & set(HONESTY_CHECKS)
    dirty = {
        recipe["slug"]: {k: v for k, v in _violations(recipe_dir(recipe)).items() if v}
        for recipe in RECIPES_WITH_TEMPLATE
    }
    assert not {slug: found for slug, found in dirty.items() if found}


def test_each_detector_sees_something_across_the_published_set():
    """A parser that finds nothing and a tree that is clean print the same output (the hazard the
    #218 thread's own self-report names), so each detector must have examined a real number of
    things: the lines are not empty, the metric lines exist, the prose quotes quantities, and the
    provenance lines are found in every notebook. The floors are well below today's counts (6548
    output lines, 1190 metric lines, 213 quoted quantities, measured when this landed)."""
    recipes = RECIPES_WITH_TEMPLATE
    lines = [_committed_output_lines(recipe_dir(r)) for r in recipes]
    assert sum(len(x) for x in lines) > 3000
    metric = [
        line
        for per_recipe in lines
        for _, line in per_recipe
        if OUTPUT_METRIC_WORD.search(line) and OUTPUT_NUMBER.search(line)
    ]
    assert len(metric) > 500
    assert all(any(_PROVENANCE_LINE.match(line) for _, line in per_recipe) for per_recipe in lines)
    assert all(any(line.startswith("Mode:") for _, line in per_recipe) for per_recipe in lines)
    quoted = [q for r in recipes for _, _, q in _prose_quotes(recipe_dir(r))]
    assert len(quoted) > 100


def test_the_provenance_reader_agrees_with_the_replay_backend():
    """The fixture reader looks one level deeper than the response (``answers -> name ->
    provenance``). A reader one level too shallow finds nothing in every recipe, and "found
    nothing" and "every recipe agrees" look identical, so the reader is held to the shared
    backend's own answer for every published replay recipe."""
    from jev_cookbook.backends import ReplayBackend

    checked = 0
    for recipe in RECIPES_WITH_TEMPLATE:
        path = recipe_dir(recipe) / "fixtures" / "responses.json"
        if not path.is_file():
            assert _fixture_provenance(recipe_dir(recipe))[0] == "scripted", recipe["slug"]
            continue
        backend = ReplayBackend.from_json(path)
        mode, models, dates, problems = _fixture_provenance(recipe_dir(recipe))
        assert (mode, problems) == (backend.mode, []), recipe["slug"]
        if mode == "recorded":
            assert models == [backend.model] and tuple(dates) == backend.recorded_dates
        checked += 1
    assert checked >= 40


def test_a_recorded_recipe_built_from_the_template_is_clear(tmp_path):
    """The other side of every provenance case below: a recipe whose fixtures, committed output
    and README all say recorded passes, and carries no pipeline-check label anywhere."""
    folder = _copy_recipe(tmp_path, "_template")
    _make_recorded(folder)
    assert _fixture_provenance(folder) == ("recorded", [_RECORDED_MODEL], [_RECORDED_DATE], [])
    assert _violations(folder) == {
        k: [] for k in ("provenance", "readme", "metric", "quantity", "claim")
    }


def test_the_scripted_published_recipe_is_read_as_scripted():
    assert _fixture_provenance(RECIPES_DIR / "36-card-game-action-selection") == (
        "scripted",
        [],
        [],
        [],
    )
    assert _provenance_violations(RECIPES_DIR / "36-card-game-action-selection") == []


# Each case mutates a throwaway template copy so that the committed output or the README no
# longer agrees with the fixtures; the check must name what is wrong. The first four are #218's
# own worst case ("a recipe claiming measured results it never measured") in the four places a
# reader meets it.
_REPLAY_HEADER = "Mode: offline replay of synthetic fixtures"
_DISCLOSURE = "Provenance: synthetic. Not measured live: a pipeline check, not a Jev result."
_PROVENANCE_FAILS = {
    "header-says-recorded": (
        lambda f: _edit_streams(f, _REPLAY_HEADER, "Mode: offline replay of recorded fixtures"),
        "the header reports 'recorded' but the fixtures carry 'synthetic'",
    ),
    "measured-cell-says-recorded": (
        lambda f: _edit_streams(f, _DISCLOSURE, "Provenance: recorded. Not measured live."),
        "reports 'recorded' but the fixtures carry 'synthetic'",
    ),
    "answer-provenance-line-says-recorded": (
        lambda f: _edit_streams(
            f, "Provenance: synthetic\n", f"Provenance: recorded ({_RECORDED_MODEL})\n"
        ),
        "reports 'recorded' but the fixtures carry 'synthetic'",
    ),
    "captured-line-and-model-added": (
        lambda f: _edit_streams(
            f, _DISCLOSURE, f"{_DISCLOSURE}\nCaptured: {_RECORDED_DATE}\nmodel {_RECORDED_MODEL}"
        ),
        "a recorded run's wording",
    ),
    "header-says-live": (
        lambda f: _edit_streams(f, _REPLAY_HEADER, "Mode: live"),
        "the header reports 'live'",
    ),
    "disclosure-sentence-dropped": (
        lambda f: _edit_streams(f, _DISCLOSURE, "Provenance: synthetic."),
        "Not measured live: a pipeline check, not a Jev result.` line",
    ),
    "header-removed": (
        lambda f: _edit_streams(
            f,
            "Mode: offline replay of synthetic fixtures, pipeline check on a fixture sample of 20 "
            "examples",
            "Offline run",
        ),
        "no `Mode:` header line",
    ),
    "header-unreadable": (
        lambda f: _edit_streams(f, _REPLAY_HEADER, "Mode: replayed offline from synthetic data"),
        "a `Mode:` line this check cannot read",
    ),
    "every-provenance-line-renamed": (
        lambda f: _edit_streams(f, "Provenance:", "Origin:", count=2),
        "no `Provenance:` line",
    ),
    "all-fixtures-recorded-output-still-synthetic": (
        lambda f: _rewrite_responses(f, _record),
        "the header reports 'synthetic' but the fixtures carry 'recorded'",
    ),
    "one-fixture-answer-recorded": (
        lambda f: _rewrite_responses(f, lambda i, a: _record(i, a) if i == 0 else None),
        "mix synthetic and recorded provenance",
    ),
    "recorded-answer-without-a-model": (
        lambda f: _rewrite_responses(
            f, lambda i, a: a.update(provenance={"source": "recorded", "date": _RECORDED_DATE})
        ),
        "names no model",
    ),
    "recorded-answer-without-a-date": (
        lambda f: _rewrite_responses(
            f, lambda i, a: a.update(provenance={"source": "recorded", "model": _RECORDED_MODEL})
        ),
        "has no capture date",
    ),
    "answer-without-provenance": (
        lambda f: _rewrite_responses(f, lambda i, a: a.pop("provenance") if i == 0 else None),
        "has provenance None",
    ),
    "provenance-source-misspelt": (
        lambda f: _rewrite_responses(
            f, lambda i, a: a["provenance"].update(source="recordd") if i == 0 else None
        ),
        "has provenance 'recordd'",
    ),
    "fixtures-unreadable": (
        lambda f: (f / "fixtures" / "responses.json").write_text("{", "utf-8"),
        "cannot be read",
    ),
    "fixtures-empty": (
        lambda f: (f / "fixtures" / "responses.json").write_text("{}", "utf-8"),
        "holds no stored responses",
    ),
    "no-fixtures-and-no-script": (
        lambda f: (f / "fixtures" / "responses.json").unlink(),
        "defines no `script` and `SEED`",
    ),
}


@pytest.mark.parametrize("case", sorted(_PROVENANCE_FAILS))
def test_a_reported_provenance_that_disagrees_with_the_fixtures_fails_closed(tmp_path, case):
    mutate, needle = _PROVENANCE_FAILS[case]
    folder = _copy_recipe(tmp_path, "_template")
    assert _provenance_violations(folder) == []
    mutate(folder)
    violations = _provenance_violations(folder)
    assert violations, f"{case}: the mutation went unnoticed"
    assert any(needle in v for v in violations), (needle, violations)


_RECORDED_FAILS = {
    "pipeline-check-disclosure-kept": (
        lambda f: _edit_streams(
            f, "Captured:", "Captured: (kept) a pipeline check, not a Jev result."
        ),
        "carries the pipeline-check disclosure",
    ),
    "captured-line-removed": (
        lambda f: _edit_streams(f, f"Captured: {_RECORDED_DATE}\n", ""),
        "no `Captured:` line",
    ),
    "header-names-another-model": (
        lambda f: _edit_streams(f, f"to model {_RECORDED_MODEL}", "to model jev-9.9.9"),
        "the header says model jev-9.9.9",
    ),
    "provenance-line-names-another-model": (
        lambda f: _edit_streams(
            f, f"Provenance: recorded, model {_RECORDED_MODEL}", "Provenance: recorded, model jev-9"
        ),
        "no `Provenance: recorded, model",
    ),
    "header-says-synthetic": (
        lambda f: _edit_streams(f, "Mode: offline replay of recorded fixtures", _REPLAY_HEADER),
        "the header reports 'synthetic' but the fixtures carry 'recorded'",
    ),
    # Two-directional: what the output states must equal what the fixtures carry, so a fabricated
    # EXTRA date or model fails as surely as a missing one.
    "extra-capture-date-in-the-captured-line": (
        lambda f: _edit_streams(
            f, f"Captured: {_RECORDED_DATE}", f"Captured: {_RECORDED_DATE}, 2026-12-25"
        ),
        "state capture dates",
    ),
    "extra-date-in-the-header": (
        lambda f: _edit_streams(
            f,
            f"calls to model {_RECORDED_MODEL} on {_RECORDED_DATE}.",
            f"calls to model {_RECORDED_MODEL} between {_RECORDED_DATE} and 2026-12-25.",
        ),
        "the header says",
    ),
    "extra-model-in-the-header": (
        lambda f: _edit_streams(
            f, f"to model {_RECORDED_MODEL} on", f"to model {_RECORDED_MODEL} and jev-9.9.9 on"
        ),
        "cannot read",
    ),
    "extra-model-in-the-provenance-line": (
        lambda f: _edit_streams(
            f,
            f"Provenance: recorded, model {_RECORDED_MODEL}",
            f"Provenance: recorded, model {_RECORDED_MODEL} and jev-9.9.9",
        ),
        "cannot read",
    ),
    "another-model-in-an-answer-line": (
        lambda f: _edit_streams(f, f"recorded ({_RECORDED_MODEL},", "recorded (jev-9.9.9,"),
        "names model 'jev-9.9.9'",
    ),
    "another-date-in-an-answer-line": (
        lambda f: _edit_streams(
            f, f"({_RECORDED_MODEL}, {_RECORDED_DATE})", f"({_RECORDED_MODEL}, 2026-12-25)"
        ),
        "names date '2026-12-25'",
    ),
    "a-model-stated-elsewhere-in-the-output": (
        lambda f: _edit_streams(f, "N: 10 validation", "answered by jev-9.9.9; N: 10 validation"),
        "jev-9.9.9",
    ),
    "captured-line-with-extra-words": (
        lambda f: _edit_streams(
            f, f"Captured: {_RECORDED_DATE}", f"Captured: {_RECORDED_DATE} (approximately)"
        ),
        "cannot read",
    ),
    "header-reworded": (
        lambda f: _edit_streams(
            f,
            "Any numbers below describe only that recorded sample",
            "These numbers describe Jev in general; the recorded sample",
        ),
        "cannot read",
    ),
}


@pytest.mark.parametrize("case", sorted(_RECORDED_FAILS))
def test_a_recorded_run_must_say_so_and_state_exactly_its_model_and_dates(tmp_path, case):
    mutate, needle = _RECORDED_FAILS[case]
    folder = _copy_recipe(tmp_path, "_template")
    _make_recorded(folder)
    assert _provenance_violations(folder) == []
    mutate(folder)
    violations = _provenance_violations(folder)
    assert any(needle in v for v in violations), (case, violations)


_README_MODE_BULLET = r"- \*\*Mode:\*\* synthetic"
_README_FAILS = {
    "mode-says-recorded": (
        lambda f: _edit_readme(f, _README_MODE_BULLET, "- **Mode:** recorded"),
        "the README states mode 'recorded' but the fixtures carry 'synthetic'",
    ),
    "mode-says-live": (
        lambda f: _edit_readme(f, _README_MODE_BULLET, "- **Mode:** live"),
        "the README states mode 'live'",
    ),
    "no-mode-line": (
        lambda f: _edit_readme(f, r"\*\*Mode:\*\*", "**How:**"),
        "no `**Mode:**` line",
    ),
    "never-says-not-measured-live": (
        lambda f: _edit_readme(f, r"not\s+measured\s+live", "unmeasured", count=2),
        "never says 'not measured live'",
    ),
    "no-readme": (lambda f: (f / "README.md").unlink(), "no README.md"),
}


@pytest.mark.parametrize("case", sorted(_README_FAILS))
def test_a_readme_that_disagrees_with_the_fixtures_fails(tmp_path, case):
    mutate, needle = _README_FAILS[case]
    folder = _copy_recipe(tmp_path, "_template")
    assert _readme_provenance_violations(folder) == []
    mutate(folder)
    assert any(needle in v for v in _readme_provenance_violations(folder))


def test_a_recorded_readme_must_name_the_model_and_the_dates(tmp_path):
    folder = _copy_recipe(tmp_path, "_template")
    _make_recorded(folder)
    assert _readme_provenance_violations(folder) == []
    _edit_readme(folder, _RECORDED_MODEL, "a model", count=1)
    _edit_readme(folder, _RECORDED_DATE, "some day", count=1)
    violations = _readme_provenance_violations(folder)
    assert any(_RECORDED_MODEL in v for v in violations)
    assert any(_RECORDED_DATE in v for v in violations)


def test_a_recorded_run_may_print_unlabelled_metrics_and_bare_vocabulary(tmp_path):
    """The converse of the vocabulary rule #218 item 3 rejected: ``recorded`` in prose is
    allowed anywhere (the template itself explains what a recorded recipe states), and a recorded
    run prints no pipeline-check label, so the metric rule leaves it alone."""
    folder = _copy_recipe(tmp_path, "_template")
    _make_recorded(folder)
    _append_cell(folder, "code", "accuracy of the choice: 0.80")
    _append_cell(
        folder,
        "markdown",
        "A recorded recipe states the model version the API returned, the capture date and N.",
        cell_id="honesty-probe-md",
    )
    assert _all_clear(folder)
    template = _copy_recipe(tmp_path / "again", "_template")
    assert "recorded" in (template / "README.md").read_text("utf-8")
    assert _all_clear(template)


# --- metric lines in a synthetic run -----------------------------------------------------------

_UNLABELLED_METRICS = {
    "plain": "accuracy of the choice: 0.95",
    "two-decimals": "accuracy 0.95",
    "four-decimals": "accuracy 0.9500",
    "percent": "accuracy 95.0%",
    "aligned-table-row": f"{'always retry':<28} {0:>8} {0.95:>13.4f} {'accuracy':>20}  {0.9:>8.4f}",
    "a-hoisted-format": "wrongly selected anyway: recall 0.9000",
    "mixed-case": "Precision: 0.9167",
    "f1": "f1 0.9474",
    "ndcg": "ndcg@3 0.8812",
    "label-misspelt": "accuracy 0.95 (a pipeline probe, not a Jev result)",
    "selection-label-only": "recall 0.9000 (a selection step, not a reported result)",
    "disclosure-prose-is-not-a-label": (
        "accuracy 0.95. Not measured live: a pipeline check, not a Jev result."
    ),
}


@pytest.mark.parametrize("case", sorted(_UNLABELLED_METRICS))
def test_a_metric_line_without_the_pipeline_check_label_fails_whatever_printed_it(tmp_path, case):
    folder = _copy_recipe(tmp_path, "_template")
    assert _unlabelled_metric_output_lines(folder) == []
    _append_cell(folder, "code", _UNLABELLED_METRICS[case])
    violations = _unlabelled_metric_output_lines(folder)
    assert len(violations) == 1, violations
    assert "honesty-probe" in violations[0]


_NOT_A_METRIC_LINE = {
    "labelled": f"accuracy 0.95 {PIPELINE_CHECK_LABEL}",
    "labelled-and-selection": (
        f"accuracy 0.95 (a selection step, not a reported result) {PIPELINE_CHECK_LABEL}"
    ),
    "per-example-confidence": "  t09-mixed: gold account, answered billing (confidence 0.71)",
    "a-probability-bar": "  billing  0.80  ################",
    "fixture-composition-share": "a first among 11 comparisons: 0.727",
    "a-count": "accuracy: 8 of 10",
    "a-threshold": "chosen threshold, frozen from here on: 0.69",
    "the-fixed-disclosure": "Not measured live: a pipeline check, not a Jev result.",
    "a-version-in-a-name": "answered by jev-1.13.0, 12 of 20 right",
}


@pytest.mark.parametrize("case", sorted(_NOT_A_METRIC_LINE))
def test_a_line_that_is_not_an_unlabelled_metric_does_not_fail(tmp_path, case):
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "code", _NOT_A_METRIC_LINE[case])
    assert _unlabelled_metric_output_lines(folder) == []


def test_stripping_the_label_off_one_committed_line_of_the_template_fails(tmp_path):
    """Red-before on the real thing: the template's own test-split accuracy line, unlabelled."""
    folder = _copy_recipe(tmp_path, "_template")
    _edit_streams(
        folder,
        f"accuracy of the choice: 0.80 {PIPELINE_CHECK_LABEL}\nrouted automatically: 6 of 10",
        "accuracy of the choice: 0.80\nrouted automatically: 6 of 10",
    )
    violations = _unlabelled_metric_output_lines(folder)
    assert len(violations) == 1 and "accuracy of the choice: 0.80" in violations[0]
    assert "evaluation-test" in violations[0]


# --- quantities in prose ----------------------------------------------------------------------

# The two reproductions #218 records, as the text each reviewer inserted. The quantified claim is
# the one in comment 6105811015 (recipe 27's review): all three quantities section 2 names.
_FABRICATED_TRIPLE = "Jev reaches 97.31% accuracy at a 180 ms median latency and $0.0004 a call."
_UNPRINTED = {
    "percentage-after-the-metric": "The accuracy was 97.4% on the test split.",
    "percentage-before-the-metric": "That is 97.4% accuracy on the test split.",
    "decimal-after-the-metric": "Accuracy 0.974 on the test split.",
    "decimal-with-a-connective": "precision of about 0.9731 on the test split.",
    "recall-and-f1": "recall: 0.92, f1: 0.91",
    "latency-in-milliseconds": "A median latency of 180 ms per call.",
    "latency-in-seconds": "A latency of 2.5 seconds per call.",
    "jev-takes-seconds": "Jev takes 2.5 seconds per call.",
    "the-api-is-slow-in-seconds": "The API is slow: 3 seconds a request.",
    "a-live-call-takes-seconds": "In a live run each call takes under 1.5 seconds.",
    "response-time-in-minutes": "The response time is 2 minutes.",
    "price-per-call": "It costs $0.0004 a call.",
    "price-per-1k-tokens": "Priced at $0.002 per 1k tokens.",
    "price-in-a-sentence-about-the-api": "The API charges $12 for the whole run.",
    "throughput": "It handles 300 requests per second.",
    "the-fabricated-triple": _FABRICATED_TRIPLE,
    "close-to-a-printed-number-but-not-it": "accuracy 0.81 on the test split",
    "a-thousands-separator": "about 1,250 tokens per second",
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("case", sorted(_UNPRINTED))
def test_a_quantity_nothing_printed_fails_in_the_readme_and_in_a_markdown_cell(
    tmp_path, case, where
):
    folder = _copy_recipe(tmp_path, "_template")
    assert _unprinted_quantities(folder) == []
    if where == "readme":
        (folder / "README.md").write_text(
            (folder / "README.md").read_text("utf-8") + "\n" + _UNPRINTED[case] + "\n", "utf-8"
        )
    else:
        _append_cell(folder, "markdown", _UNPRINTED[case])
    violations = _unprinted_quantities(folder)
    assert violations, f"{case}: nothing was noticed in the {where}"
    assert ("README.md" if where == "readme" else "honesty-probe") in violations[0]


def test_the_fabricated_triple_is_caught_in_recipe_26s_measured_cell_where_it_was_planted(tmp_path):
    """#218's first reproduction: a fabricated claim in recipe 26's ``measured-md`` cell, with
    every guard that existed passing. The checks that existed see nothing; this one does."""
    folder = _copy_recipe(tmp_path, "26-prompt-injection-screening")
    cells = notebook_cells(folder)
    measured = next(c for c in cells if c.get("id") == "measured-md")
    _edit_markdown(folder, cell_source(measured), cell_source(measured) + " " + _FABRICATED_TRIPLE)
    notebook_code = [cell_source(c) for c in notebook_cells(folder) if c["cell_type"] == "code"]
    assert _recipe_citation_hits(folder) == []
    assert not any(_metric_lines_missing_check(source) for source in notebook_code)
    assert _provenance_violations(folder) == [] and _readme_provenance_violations(folder) == []
    violations = _unprinted_quantities(folder)
    assert len(violations) == 3, violations
    assert all("measured-md" in v for v in violations)


_PRINTED_UNDER_ANOTHER_SPELLING = {
    "same-digits": "accuracy 0.80",
    "trailing-zeros-dropped": "accuracy 0.8",
    "trailing-zeros-added": "accuracy 0.8000",
    "as-a-percentage": "accuracy 80%",
    "as-a-percentage-with-a-decimal": "80.0% accuracy",
    "backticked": "`accuracy` is `0.80`",
    "bold": "**accuracy** of **0.80**",
    "with-a-connective": "accuracy of about 0.80",
}


@pytest.mark.parametrize("case", sorted(_PRINTED_UNDER_ANOTHER_SPELLING))
def test_a_printed_number_quoted_under_another_spelling_is_the_same_number(tmp_path, case):
    """The template prints ``accuracy of the choice: 0.80``. Quoting it as 0.8, 0.8000, 80% or
    80.0% is quoting that number (#218: changing ``:.4f`` to ``:.2f`` must not defeat the check)."""
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", _PRINTED_UNDER_ANOTHER_SPELLING[case])
    assert _unprinted_quantities(folder) == []


# (what the notebook prints, what the prose quotes, how many quotes nothing backs). A minimal
# notebook, so no other printed number can back a quote by coincidence.
_BACKED_AND_UNBACKED = {
    "rounded-to-two-places": ("coverage 0.9286", "coverage 0.93", 0),
    "as-a-percentage-to-one-place": ("coverage 0.9286", "coverage 92.9%", 0),
    "as-a-percentage-before-the-word": ("coverage 0.9286", "92.86% coverage", 0),
    "the-same-figures": ("coverage 0.9286", "coverage 0.9286", 0),
    "a-different-fourth-place": ("coverage 0.9286", "coverage 0.9287", 1),
    "a-different-percentage": ("coverage 0.9286", "coverage 92.8%", 1),
    "truncated-rather-than-rounded": ("coverage 0.9286", "coverage 0.92", 1),
    "risk-backed-by-a-printed-accuracy": ("accuracy 0.9474", "the risk was 0.0526", 0),
    "accuracy-backed-by-a-printed-risk": ("risk 0.0526", "the accuracy was 0.9474", 0),
    "risk-backed-in-percent": ("accuracy 0.9474", "a risk of 5.26%", 0),
    "recall-is-not-a-complement": ("accuracy 0.9474", "the recall was 0.0526", 1),
    "risk-that-is-not-the-complement": ("accuracy 0.9474", "the risk was 0.0527", 1),
    "a-price-is-not-backed-by-a-sample-size": ("N: 180 examples", "It costs $180 a call.", 1),
    "a-latency-is-not-backed-by-a-sample-size": ("N: 180 examples", "A latency of 180 ms.", 1),
    "a-latency-printed-with-its-unit": ("median 180 ms per call", "A latency of 180 ms.", 0),
    "a-price-printed-with-its-unit": ("estimated spend $0.0004", "It costs $0.0004 a call.", 0),
}


@pytest.mark.parametrize("case", sorted(_BACKED_AND_UNBACKED))
def test_a_printed_number_backs_the_quotes_it_rounds_to_and_complements_only_as_documented(
    tmp_path, case
):
    printed, prose, unbacked = _BACKED_AND_UNBACKED[case]
    folder = _synthetic_recipe(tmp_path, ["print('probe')\n"])
    _append_cell(folder, "code", printed, cell_id="printed")
    _append_cell(folder, "markdown", prose, cell_id="prose")
    assert len(_unprinted_quantities(folder)) == unbacked, _unprinted_quantities(folder)


_IS_PRINTED = [
    ("0.8", ["0.80"], True),
    ("0.800", ["0.8"], True),
    ("0.92", ["0.9167"], True),
    ("0.91", ["0.9167"], False),
    ("97.4%", ["0.9744"], True),
    ("97.4%", ["0.9754"], False),
    ("90%", ["0.9"], True),
    ("90%", ["90"], False),
    ("100%", ["1.0000"], True),
    ("1,250.5", ["1250.5"], True),
    ("0.87", ["0.8650"], True),
    ("0.86", ["0.8650"], True),
    ("0.88", ["0.8650"], False),
    ("0.5", ["5"], False),
]


@pytest.mark.parametrize(("quote", "printed", "expected"), _IS_PRINTED)
def test_is_printed_rounding_percentage_and_separator_tolerances(quote, printed, expected):
    assert _is_printed(quote, [Decimal(p) for p in printed]) is expected


_NOT_A_QUANTITY_CLAIM = {
    "a-disclosure-with-no-number": (
        "Nothing here says anything about Jev's accuracy, latency or cost: not measured live."
    ),
    "the-template-sentence": (
        "A recorded recipe states the model version the API returned, the capture date and N."
    ),
    "a-fixture-invoice-in-a-sentence-about-the-example": 'The message says "I refunded $8.00 to your card".',
    "a-fixture-estimate": "The plan's own estimated cost, $5200, is above the $3000 budget.",
    "a-version-number": "TypeSafe's notes on Jev 1.13 (S07) document a real failure.",
    "a-threshold-name": "`min_coverage=0.7` is a business choice.",
    "a-parameter-name": "Set `target_accuracy` to a looser value.",
    "a-count-of-requests": "This notebook makes exactly one call for each of the 22 examples.",
    "a-budget": "The default request budget is 25 requests.",
    "n": "N: 10 validation and 10 test examples.",
    "a-link-target": "See [the docs](https://example.com/accuracy-0.974-benchmark).",
    "a-shell-command": "```bash\npytest --accuracy 0.974\n```",
    # About the notebook's own run, not about Jev: no way for a recipe pull request to answer a
    # failure on these, so they must not fail.
    "the-notebook-takes-minutes": "Running this notebook takes about 2 minutes on a laptop.",
    "the-run-takes-seconds": "The whole run takes 30 seconds offline.",
    "installing-takes-seconds": "Installing the dependencies takes about 45 seconds.",
    "the-offline-replay-is-fast": "The offline replay is fast: 3 seconds for all 22 examples.",
}


@pytest.mark.parametrize("case", sorted(_NOT_A_QUANTITY_CLAIM))
def test_prose_that_quotes_no_unprinted_quantity_about_jev_passes(tmp_path, case):
    """Legitimately disclosed statements and numbers that are not performance claims: the check
    must not fire on "not measured live", on a fixture's own prices, or on a parameter's name."""
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", _NOT_A_QUANTITY_CLAIM[case])
    assert _unprinted_quantities(folder) == []


def test_a_number_typed_in_the_recipes_own_tests_backs_a_quote(tmp_path):
    """CONTRIBUTING.md section 6 lets a quoted counterfactual stand when "a test re-derives it":
    a quoted figure a recipe test types is backed, one nothing types or prints is not."""
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", "At a looser target the coverage would be 0.9137.")
    assert _unprinted_quantities(folder)
    (folder / "tests" / "test_counterfactual.py").write_text(
        "def test_it():\n    assert round(0.9137, 4) == 0.9137\n", "utf-8"
    )
    assert _unprinted_quantities(folder) == []


# --- sentences that say Jev does well -----------------------------------------------------------

_UNHEDGED_CLAIMS = {
    "judges-correctly": "Jev judges these tickets correctly.",
    "handles-reliably": "Jev handles ambiguous messages reliably.",
    "performs-well": "The model performs well on the hard cases.",
    "is-accurate": "Jev is accurate on this task.",
    "is-fast-and-cheap": "Jev is fast and cheap enough for every message.",
    "outperforms": "Jev outperforms the keyword baseline here.",
    "always-right": "Jev is always right when it is confident.",
    "reads-the-evidence-properly": "Given the whole record, the model reads the evidence properly.",
    # A decimal point between the subject and the adverb (the span used to stop at it).
    "a-percentage-then-reliably": "Jev handles 97.4% of these messages reliably.",
    "a-percentage-then-well": "Jev answers 97.4% of the hard cases well.",
    "a-fraction-then-correctly": "Jev judges 0.9 of these tickets correctly.",
    "a-version-then-reliably": "Jev v1.2 handles these tickets reliably.",
    # Words that name a source are not attributions: only a verb of saying hedges.
    "typesafes-jev": "TypeSafe's Jev judges these tickets correctly.",
    "see-the-docs": "Jev judges these tickets correctly; see the docs for the question definition.",
    "a-link-to-the-docs": (
        "Jev judges these tickets correctly, as [the docs](../../docs/glossary.md) define it."
    ),
    "a-cited-source-id": "Jev is accurate on these tickets (S07).",
    "the-documentation-describes": "Jev is accurate, as the documentation describes it.",
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("case", sorted(_UNHEDGED_CLAIMS))
def test_a_sentence_saying_jev_does_well_fails_in_a_synthetic_recipe(tmp_path, case, where):
    folder = _copy_recipe(tmp_path, "_template")
    assert _unhedged_quality_claims(folder) == []
    if where == "readme":
        (folder / "README.md").write_text(
            (folder / "README.md").read_text("utf-8") + "\n" + _UNHEDGED_CLAIMS[case] + "\n",
            "utf-8",
        )
    else:
        _append_cell(folder, "markdown", _UNHEDGED_CLAIMS[case])
    violations = _unhedged_quality_claims(folder)
    assert len(violations) == 1, (case, violations)
    assert ("README.md" if where == "readme" else "honesty-probe") in violations[0]


_HEDGED_OR_DESCRIPTIVE = {
    "not-measured-live": "How well Jev does here is not measured live.",
    "negated": "Nothing here shows that Jev judges these tickets correctly.",
    "hypothetical": "If Jev reliably named the queue, the review rate would fall.",
    "a-recorded-run-would-show": "A recorded run would show how accurately Jev reads them.",
    "attributed": "TypeSafe's notes say the model judges each level on its own.",
    "a-description-of-the-task": "Jev reads one message and picks exactly one of four options.",
    "a-description-of-the-instruction": (
        "Jev is asked to judge from the evidence as a whole, not from the reported status alone."
    ),
    "how-well": "Jev scores how well that skill's own description fits the task.",
    "the-stored-answers": "The model's stored answers agree with each other, confidently and correctly.",
    "a-baseline": "The lexical baseline does better than pure position.",
    "a-compound-word": "Jev returns a well-formed answer for every question.",
    "the-pipeline": "The pipeline checks that the catalog is read correctly.",
    # Sentence-final periods, decimals and versions inside a sentence do not join two sentences.
    "a-decimal-then-a-new-sentence": "Jev reads 97.4 tickets. The pipeline runs well.",
    "a-version-then-a-new-sentence": "Jev v1.2 reads the ticket. The rule is checked correctly.",
    "a-decimal-claim-with-its-hedge": (
        "Jev handles 97.4% of these messages reliably, which is not measured live."
    ),
    "an-attribution-with-a-verb": "TypeSafe's documentation says Jev judges each level on its own.",
}


@pytest.mark.parametrize("case", sorted(_HEDGED_OR_DESCRIPTIVE))
def test_a_hedged_or_descriptive_sentence_about_jev_passes(tmp_path, case):
    """False positives on legitimately disclosed statements are avoided and tested: the rule's
    own wording ("not measured live"), a hypothetical, an attribution, and a plain description of
    what Jev is asked to do all pass."""
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", _HEDGED_OR_DESCRIPTIVE[case])
    assert _unhedged_quality_claims(folder) == []


def test_the_vocabulary_check_does_not_apply_to_a_recorded_recipe(tmp_path):
    """A recorded recipe names its model, date and N, and its claims are the reviewer's: the
    synthetic-only rule leaves it alone (#218 item 1 is conditioned on provenance)."""
    folder = _copy_recipe(tmp_path, "_template")
    _make_recorded(folder)
    _append_cell(folder, "markdown", "Jev judges these tickets correctly.")
    assert _unhedged_quality_claims(folder) == []


# --- #218's three real instances and #221's six findings, reconstructed ---------------------------

# What no mechanical check can reach, written as cases that PASS every honesty check. They are
# pinned so the limits stay honest: a later check that starts to catch one must move it to a
# must-fail table on purpose, and docs/offline-and-live.md says each is the reviewer's alone.
_REVIEWER_ONLY = {
    # PR #204: the README asserted how Jev judges, contradicted by the recipe's own fixture.
    "a-claim-about-how-jev-judges": (
        "Jev judges from the evidence as a whole rather than trusting the tool's own reported "
        "status."
    ),
    # PR #204: a first-listed-option share, which offline measures only the fixture author, offered
    # as a check on the model's position bias. 0.52 is a printed number about the fixtures.
    "a-fixture-statistic-offered-as-evidence-about-the-model": (
        "The first-listed option is chosen in 0.52 of cases, so the model shows no position bias."
    ),
    # PR #206: a per-label F1 of 1.0000, perfect by construction, printed with its pipeline-check
    # label and no word that it is perfect because the fixtures are.
    "a-construction-perfect-metric-with-its-label-and-no-caveat": (
        "Every label reaches an F1 of 1.0000, so the rule separates the classes."
    ),
    "a-true-number-given-a-false-interpretation": "The accuracy of 0.80 shows the routing is sound.",
    "a-claim-with-no-number-and-no-evaluative-word": "Jev handles these messages the way a person would.",
    "a-claim-in-a-synonym": "Jev is flawless on the hard cases.",
    # PR #221: the six statements about the notebook's own committed output.
    "221-1-all-1.0000-above-a-line-printing-0.9474": "Precision, recall and F1 are all 1.0000 here.",
    "221-2-each-misses-one-record": "Each proposition misses one record.",
    "221-3-every-answer-on-the-correct-side-of-the-threshold": (
        "Every stored answer lands on the correct side of its threshold."
    ),
    "221-4-two-confidently-wrong-records": "There are two confidently wrong records.",
    "221-5-the-two-demo-records": "The two demo records lack a rollback description.",
    "221-6-well-clear-of-the-gate": "The record is well clear of the gate.",
}


def test_what_only_a_reviewer_can_judge_passes_every_honesty_check(tmp_path):
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "code", f"F1 per label: 1.0000 {PIPELINE_CHECK_LABEL}", cell_id="ev-code")
    # the numbers these statements cite are printed, as in the real notebooks
    _append_cell(folder, "code", "first-listed share 0.52", cell_id="share-code")
    for case, sentence in sorted(_REVIEWER_ONLY.items()):
        _append_cell(folder, "markdown", sentence, cell_id=f"md-{case}")
    assert _all_clear(folder), _violations(folder)


def test_the_construction_perfect_metric_is_caught_only_when_it_is_also_unlabelled(tmp_path):
    """PR #206's per-label F1 of 1.0000: the label is what a mechanical check can require. With
    it the line passes (that it is perfect by construction is the reviewer's); without it, fails."""
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "code", f"F1 per label: 1.0000 {PIPELINE_CHECK_LABEL}", cell_id="a")
    assert _unlabelled_metric_output_lines(folder) == []
    _append_cell(folder, "code", "F1 per label: 1.0000", cell_id="b")
    assert len(_unlabelled_metric_output_lines(folder)) == 1


def test_a_fabricated_number_in_the_221_shape_is_caught_but_its_misdescriptions_are_not(tmp_path):
    """PR #221's six statements describe the notebook's own output wrongly. What a check can
    decide there is a quoted NUMBER the output never printed; "all 1.0000" above a line that
    printed 1.0000 / 0.9000 / 0.9474 quotes a number the output did print, so it is not decidable
    by this check, and the others quote no metric value at all. Of the six, none is caught as
    worded; the nearest decidable form is a metric value the run never produced."""
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(
        folder,
        "code",
        f"precision 1.0000 recall 0.9000 f1 0.9474 {PIPELINE_CHECK_LABEL}",
        cell_id="ev-code",
    )
    _append_cell(folder, "markdown", "Precision, recall and F1 are all 1.0000.", cell_id="ev-md")
    assert _unprinted_quantities(folder) == []
    _append_cell(folder, "markdown", "Recall 0.9500, f1 0.9700.", cell_id="ev-md-2")
    assert len(_unprinted_quantities(folder)) == 2


def test_the_honesty_doc_anchor_resolves_and_the_doc_names_every_check_and_its_limits():
    """Every failure message cites ``HONESTY_DOC``; the section must exist under that anchor,
    name each of the five checks, and say what is the reviewer's alone."""
    doc = (REPO / "docs" / "offline-and-live.md").read_text("utf-8")
    path, _, anchor = HONESTY_DOC.partition("#")
    assert path == "docs/offline-and-live.md"
    slugs = {
        re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        for heading in re.findall(r"^#+ (.+)$", doc, re.MULTILINE)
    }
    assert anchor in slugs
    section = doc.split("## What the recipe guard checks about section 2")[1].split("\n## ")[0]
    for check in HONESTY_CHECKS:
        assert f"`{check}`" in section, check
    assert "the reviewer's alone" in section
    for check in ("metric_lines_carry_check", "validation_lines_carry_selection_and_check"):
        assert f"`{check}`" in section and "Their existence is not evidence" in section


_TOKEN_COUNTS_THAT_FAIL = {
    "k-suffix": "context: 262k tokens",
    "thousands-separator": "the request used 1,200 input tokens",
    "hyphenated-adjective": "a 64k-token request fits the limit",
    "field-and-value": "input_tokens: 1200",
    "dict-repr": "{'tokens': 37, 'characters': 180}",
    "singular": "1 token per word",
}
_LINES_THAT_ARE_NOT_TOKEN_COUNTS = {
    "an-auth-token": "A refresh token stays valid for 30 days unless the password changes.",
    "a-character-count": "context: 262,144 characters (11,904 UTF-8 bytes)",
    "a-field-not-measured": "input_tokens: None (not measured)",
    "a-field-label-only": "Access tokens issued by the login service expire after 3600 seconds.",
    "a-tokenizer-word": "tokenizer 3 is not used offline",
    "a-digit-glued-to-a-word": "sha256 tokens are hashed with a salt before they are stored",
}


@pytest.mark.parametrize("case", sorted(_TOKEN_COUNTS_THAT_FAIL))
def test_a_token_count_printed_by_a_synthetic_run_fails(tmp_path, case):
    folder = _copy_recipe(tmp_path, "_template")
    assert _printed_token_counts(folder) == []
    _append_cell(folder, "code", _TOKEN_COUNTS_THAT_FAIL[case])
    violations = _printed_token_counts(folder)
    assert len(violations) == 1 and "honesty-probe" in violations[0], violations


@pytest.mark.parametrize("case", sorted(_LINES_THAT_ARE_NOT_TOKEN_COUNTS))
def test_a_line_that_counts_no_tokens_passes(tmp_path, case):
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "code", _LINES_THAT_ARE_NOT_TOKEN_COUNTS[case])
    assert _printed_token_counts(folder) == [], case


def test_a_token_count_in_the_measured_cell_of_a_synthetic_run_fails_too(tmp_path):
    """The measured cell is not exempt offline: its offline branch prints the not-measured
    disclosure, so a token count there is the same unmeasured claim as anywhere else."""
    folder = _copy_recipe(tmp_path, "_template")
    _edit_streams(
        folder,
        "Provenance: synthetic. Not measured live: a pipeline check, not a Jev result.",
        "Provenance: synthetic. Not measured live: a pipeline check, not a Jev result.\n"
        "input tokens: 4,096",
    )
    violations = _printed_token_counts(folder)
    assert len(violations) == 1 and "cell measured" in violations[0], violations


def test_a_recorded_run_may_print_its_token_count(tmp_path):
    """The other direction: the check keys on the provenance the fixtures carry, so the same line
    in a recorded run is not this check's business (the recorded ledger records tokens)."""
    folder = _copy_recipe(tmp_path, "_template")
    _make_recorded(folder)
    _append_cell(folder, "code", _TOKEN_COUNTS_THAT_FAIL["thousands-separator"])
    assert _printed_token_counts(folder) == []
    _append_cell(folder, "code", "input_tokens: 1200", cell_id="second-probe")
    assert _printed_token_counts(folder) == []


def _strip_labels_from_outputs(folder: Path) -> None:
    for old in (f" {PIPELINE_CHECK_LABEL}", PIPELINE_CHECK_LABEL):
        path = folder / "notebook.ipynb"
        notebook = json.loads(path.read_text("utf-8"))
        for cell in notebook["cells"]:
            for output in cell.get("outputs", []):
                if output.get("output_type") == "stream":
                    text = "".join(output["text"]).replace(old, "")
                    output["text"] = text.splitlines(keepends=True)
        path.write_text(json.dumps(notebook), "utf-8")


@pytest.mark.parametrize("recipe", RECIPES_WITH_TEMPLATE, ids=_slug)
def test_every_honesty_check_fails_on_each_recipe_when_that_recipe_is_made_to_overclaim(
    tmp_path, recipe
):
    """The can-speak proof across the whole set (#218: "make it produce a hit you can see"): the
    checks pass on all 51 folders, and each one fails on every folder when that folder is made to
    do what the check is for. A check that passes because it reads nothing in one recipe's
    layout cannot hide here."""
    folder = _copy_recipe(tmp_path, recipe["slug"])
    assert _all_clear(folder), _violations(folder)

    # (1) the committed output reports a mode the fixtures do not carry
    wrong = "recorded" if _fixture_provenance(folder)[0] != "recorded" else "synthetic"
    header = next(line for _, line in _committed_output_lines(folder) if line.startswith("Mode:"))
    _edit_streams(folder, header, f"Mode: offline replay of {wrong} fixtures", count=None)
    assert any("the header reports" in v for v in _provenance_violations(folder))
    _edit_streams(folder, f"Mode: offline replay of {wrong} fixtures", header, count=None)
    assert _provenance_violations(folder) == []

    # (2) every metric line loses its pipeline-check label
    lines = _committed_output_lines(folder)
    metric_lines = [
        line for _, line in lines if OUTPUT_METRIC_WORD.search(line) and OUTPUT_NUMBER.search(line)
    ]
    assert metric_lines
    _strip_labels_from_outputs(folder)
    assert len(_unlabelled_metric_output_lines(folder)) == len(metric_lines)

    # (3) the README and a markdown cell quote the fabricated triple
    triple = "Jev reaches 97.31% accuracy at a 180 ms median latency and $0.0004 a call."
    readme = folder / "README.md"
    readme.write_text(readme.read_text("utf-8") + "\n\n" + triple + "\n", "utf-8")
    _append_cell(folder, "markdown", triple)
    violations = _unprinted_quantities(folder)
    # One failure per fabricated quote and place. A recipe that already prints one of these numbers
    # would back it, which is why this asserts each quote rather than an exact total.
    for quote in ("97.31%", "180 ms", "$0.0004 a call"):
        assert any("README.md" in v and quote in v for v in violations), (quote, violations)
        assert any("honesty-probe" in v and quote in v for v in violations), (quote, violations)

    # (4) the README names another mode than the fixtures carry, and drops "not measured live"
    mode = _fixture_provenance(folder)[0]
    text = readme.read_text("utf-8")
    assert _readme_provenance_violations(folder) == []
    readme.write_text(text.replace(f"**Mode:** {mode}", "**Mode:** recorded", 1), "utf-8")
    assert any("states mode 'recorded'" in v for v in _readme_provenance_violations(folder))

    # (5) a sentence saying Jev does well, written the way a builder writes it: as a bullet with
    # no terminator after whatever the README ends with, and as the first line under the heading
    # of the "What was and was not measured" cell, whose heading says "not".
    folder2 = _copy_recipe(tmp_path / "second", recipe["slug"])
    assert _unhedged_quality_claims(folder2) == []
    readme2 = folder2 / "README.md"
    readme2.write_text(
        readme2.read_text("utf-8") + "\n- Jev judges these tickets correctly\n", "utf-8"
    )
    violations = _unhedged_quality_claims(folder2)
    assert len(violations) == 1 and "Jev judges these tickets correctly" in violations[0], (
        violations
    )
    folder3 = _copy_recipe(tmp_path / "third", recipe["slug"])
    heading_cell = next(
        cell.get("id")
        for cell in notebook_cells(folder3)
        if cell["cell_type"] == "markdown"
        and "## What was and was not measured\n" in cell_source(cell)
    )
    _edit_markdown(
        folder3,
        "## What was and was not measured\n",
        "## What was and was not measured\nJev judges these tickets correctly\n",
    )
    violations = _unhedged_quality_claims(folder3)
    assert len(violations) == 1 and f"cell {heading_cell}:" in violations[0], violations
    assert "Jev judges these tickets correctly" in violations[0]


def test_a_claim_is_caught_in_every_markdown_block_of_every_recipe_wherever_it_is_put():
    """Reviewer 1 of PR #351 put ``Jev judges these tickets correctly`` first in each of the 955
    markdown blocks of the 50 recipes and the template and 75 were missed, 51 of them the
    ``measured`` cell whose heading says "not". At the top, at the bottom, as a bullet, as a
    table row and with no terminator, none may be."""
    placements = {
        "first": lambda block, claim: claim + "\n\n" + block,
        "last": lambda block, claim: block + "\n\n" + claim,
        "first-as-a-bullet": lambda block, claim: "- " + claim + "\n\n" + block,
        "last-as-a-bullet": lambda block, claim: block + "\n\n- " + claim,
        "a-bullet-straight-after-text": lambda block, claim: block + "\n- " + claim,
        "as-a-table-row": lambda block, claim: block + "\n\n| " + claim + " | x |",
    }
    claim = "Jev judges these tickets correctly"
    blocks = 0
    missed = []
    for recipe in RECIPES_WITH_TEMPLATE:
        for where, raw in _prose_blocks(recipe_dir(recipe)):
            blocks += 1
            before = len(_claims_in_markdown(raw))
            for name, place in placements.items():
                if len(_claims_in_markdown(place(raw, claim))) != before + 1:
                    missed.append((recipe["slug"], where, name))
    assert blocks > 900
    assert not missed, missed[:10]


_CLAIMS_IN_STRUCTURE = {
    "a-bullet-beside-a-hedged-bullet": (
        "- Notes: the gate is frozen on validation\n- Jev judges these tickets correctly"
    ),
    "a-bullet-after-a-nothing-bullet": (
        "- Nothing else to note here.\n- Jev is accurate on these tickets"
    ),
    "under-a-heading-containing-not": (
        "## What was and was not measured\nJev judges these tickets correctly."
    ),
    "under-a-heading-and-no-terminator": (
        "## What was and was not measured\n\nJev judges these tickets correctly"
    ),
    "under-a-notes-heading": "## Notes\nJev is accurate on these tickets.",
    "under-a-document-heading": "# Document classification\nJev judges these tickets correctly.",
    "after-the-verb-note": "Jev is accurate on these tickets, so note the review rate falls.",
    "a-table-row": "| a | b |\n| Jev handles ambiguous tickets reliably | x |",
    "a-table-row-under-a-hedged-header-row": (
        "| not measured | x |\n| Jev handles ambiguous tickets reliably | y |"
    ),
    "a-wrapped-bullet": "- Jev judges these tickets\n  correctly every time\n- fine",
    "after-a-hedged-sentence-on-the-same-line": (
        "This is not measured live. Jev judges these tickets correctly."
    ),
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("case", sorted(_CLAIMS_IN_STRUCTURE))
def test_a_claim_in_a_list_or_under_a_heading_is_not_hedged_by_its_neighbours(
    tmp_path, case, where
):
    """The unit a hedge word covers is one sentence, a heading, a list item or a table row, never
    the block around it (PR #351, both reviews)."""
    folder = _copy_recipe(tmp_path, "_template")
    assert _unhedged_quality_claims(folder) == []
    text = _CLAIMS_IN_STRUCTURE[case]
    if where == "readme":
        (folder / "README.md").write_text(
            (folder / "README.md").read_text("utf-8") + "\n" + text + "\n", "utf-8"
        )
    else:
        _append_cell(folder, "markdown", text)
    violations = _unhedged_quality_claims(folder)
    assert len(violations) == 1, (case, violations)
    assert ("README.md" if where == "readme" else "honesty-probe") in violations[0]


_HEDGED_WITHIN_ITS_OWN_UNIT = {
    "same-bullet-hedge": "- Jev judges these tickets correctly, which is not measured live",
    "wrapped-bullet-hedge": "- Jev judges these tickets\n  correctly only if the gate is frozen",
    "hedged-sentence-then-plain-text": "Whether Jev judges these correctly is not measured live.",
    "a-heading-that-is-only-a-hedge": "## Not measured\n- The pipeline reads the catalog correctly.",
    "an-attribution": "According to the documentation, the model judges each level on its own.",
    "typesafe-notes": "TypeSafe's notes say Jev judges each level on its own.",
}


@pytest.mark.parametrize("case", sorted(_HEDGED_WITHIN_ITS_OWN_UNIT))
def test_a_hedge_in_the_claims_own_sentence_or_list_item_still_hedges_it(tmp_path, case):
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", _HEDGED_WITHIN_ITS_OWN_UNIT[case])
    assert _unhedged_quality_claims(folder) == []


def test_the_failure_message_prints_the_offending_sentence_not_the_start_of_its_block(tmp_path):
    folder = _copy_recipe(tmp_path, "01-sentiment-classification")
    readme = folder / "README.md"
    readme.write_text(
        readme.read_text("utf-8") + "\n- Jev outperforms atlas-compact on every ticket\n", "utf-8"
    )
    (message,) = _unhedged_quality_claims(folder)
    assert "Jev outperforms atlas-compact on every ticket" in message
    assert "README.md" in message and len(message) < 400


def test_the_claim_planted_in_recipe_26s_measured_cell_is_caught_inside_the_cell(tmp_path):
    """#218's first reproduction used this cell; its heading says "not" and every claim in it used
    to be hedged by that word."""
    folder = _copy_recipe(tmp_path, "26-prompt-injection-screening")
    assert _unhedged_quality_claims(folder) == []
    _edit_markdown(
        folder,
        "## What was and was not measured\n",
        "## What was and was not measured\n\nJev judges these prompts correctly\n",
    )
    (message,) = _unhedged_quality_claims(folder)
    assert "measured-md" in message and "Jev judges these prompts correctly" in message


def test_an_attributed_quality_claim_is_a_known_pass_that_section_2_forbids(tmp_path):
    """Section 2 holds even when a figure is attributed to someone else, and the claim check treats
    an attribution as a hedge, so "TypeSafe says Jev is accurate" passes. Pinned, and listed as the
    reviewer's alone in docs/offline-and-live.md."""
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", "TypeSafe says Jev is accurate on tickets like these.")
    assert _unhedged_quality_claims(folder) == []


# --- the rate pool: the complement of a RATE, not of every printed number -------------------------

_BACKED_PLUS = {
    "a-bare-integer-does-not-back-a-complement": ("N: 7 examples", "the accuracy was 93%", 1),
    "a-probability-does-not-back-a-complement": ("probability 0.05", "accuracy 0.95", 1),
    "a-threshold-does-not-back-a-complement": ("threshold 0.30", "risk 0.70", 1),
    "a-rate-line-backs-its-complement": ("risk among the answered: 0.0526", "accuracy 0.9474", 0),
    "a-percentage-line-backs-its-complement": ("accuracy 94.74%", "risk 5.26%", 0),
    "a-printed-percentage-backs-the-fraction": ("accuracy 77.0%", "accuracy 0.77", 0),
    "one-decimal-is-not-complemented": ("accuracy 0.9", "risk 0.1", 1),
    "the-complement-needs-a-rate-word-on-its-line": ("recall 0.9474", "risk 0.0526", 1),
}


@pytest.mark.parametrize("case", sorted(_BACKED_PLUS))
def test_only_a_number_printed_on_a_rate_line_has_its_complement_backed(tmp_path, case):
    printed, prose, unbacked = _BACKED_PLUS[case]
    folder = _synthetic_recipe(tmp_path, ["print('probe')\n"])
    _append_cell(folder, "code", printed, cell_id="printed")
    _append_cell(folder, "markdown", prose, cell_id="prose")
    assert len(_unprinted_quantities(folder)) == unbacked, _unprinted_quantities(folder)


# What each recipe's own printed numbers back by coincidence differs, so each folder is held to the
# round quotes that were measured to be unbacked there (reviewer 2 measured the template and 01).
_ROUND_QUOTES = {
    "_template": [
        "Jev reaches 97% accuracy.",
        "accuracy 95%",
        "accuracy 0.95",
        "The accuracy is 93%.",
    ],
    "01-sentiment-classification": ["Jev reaches 97% accuracy.", "The accuracy is 93%."],
}


@pytest.mark.parametrize(
    ("slug", "claim"),
    [(slug, claim) for slug, claims in _ROUND_QUOTES.items() for claim in claims],
)
def test_a_round_fabricated_accuracy_is_caught_where_it_used_to_be_backed_by_a_complement(
    tmp_path, slug, claim
):
    """Reviewer 2 of PR #351: with the complement of every printed number in the pool, these four
    passed in the template and in recipe 01 (and ``97%`` in recipe 26)."""
    folder = _copy_recipe(tmp_path, slug)
    assert _unprinted_quantities(folder) == []
    _append_cell(folder, "markdown", claim)
    assert _unprinted_quantities(folder), claim


def _real_audit_line(n: int = 22) -> str:
    """A genuine committed ``AUDIT_PREFIX`` line (#213, #376): a real ``AuditedBackend`` over
    ``n`` distinct synthetic requests, not a hand-typed stand-in, so its hex ``replay_key``
    runs are the real defect's shape -- the same shape and length as the 2,267-character line
    measured at 22 requests in PR #375's migrated template (342 spurious numbers there, 346
    here: the hex depends on the requests, so this function's synthetic states cannot and do
    not reproduce that digit count exactly)."""
    from jev_cookbook import AuditedBackend, Noul, ScriptedBackend

    def script(state, questions, rng):
        return {"q": 0.9}

    backend = AuditedBackend(ScriptedBackend(script, 0))
    for i in range(n):
        backend.decide({"i": i}, {"q": Noul()})
    return backend.audit_json()


def test_the_audit_line_is_excluded_from_the_quantity_pool_per_line_not_per_cell(tmp_path):
    """#376: the committed ``AUDIT_PREFIX`` line's 64-character hex ``replay_key`` runs must not
    back a fabricated prose quantity (the defect: a hex run containing ``093``, so
    "The accuracy is 93%." used to pass; the figure pinned below is 94, see the precondition).
    Excluding it must not cost a cell's other, genuine
    output line its own numbers -- one code cell carries both lines here. This is defensive scope
    for any cell of any recipe that prints the prefix, not a claim about a real audited recipe's
    final cell: ``tests/request_audit.py``'s ``audited_evidence`` requires that final cell to hold
    exactly one statement, printing either ``backend.audit_json()`` (only when exactly one backend
    is audited) or ``audit_json(<every audited backend, in creation order>)`` (the only accepted
    form for a multi-backend recipe), so on the audited route itself the ledger never actually
    shares a cell with another line. The genuine figure stays backed; the round number
    the ledger's hex alone used to supply is caught.

    The precondition below pins the defect to the hex rather than to an accident of it: the
    states this builds the line from must actually produce a literal ``94`` that the tokenizer
    still reads (a key's leading digit run, in front of any letter: since #542 the digit runs
    glued to a letter are not read at all), or this test could silently stop being a regression
    test for #376 (a schema bump or a different request count can change which digits a hash
    produces)."""
    audit_line = _real_audit_line()
    assert audit_line.startswith(AUDIT_PREFIX)
    assert Decimal(94) in _decimals(audit_line), (
        "the synthetic audit line no longer reads a literal '94' this test pins -- "
        "its states must be changed so the defect it guards against is still exercised"
    )
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(
        folder,
        "code",
        "validation accuracy: 0.9500 (a pipeline check, not a Jev result)\n" + audit_line,
        cell_id="ledger-and-metric",
    )
    _append_cell(folder, "markdown", "The accuracy is 95%.", cell_id="genuine")
    assert _unprinted_quantities(folder) == []
    _append_cell(folder, "markdown", "The accuracy is 94%.", cell_id="fabricated")
    # Since #536 the percent quote alone no longer shows audit exclusion (a bare 94 cannot back it
    # anyway); the ordinary decimal 94.0 can, so it pins the exclusion on its own.
    _append_cell(folder, "markdown", "The accuracy is 94.0.", cell_id="fabricated-decimal")
    unbacked = _unprinted_quantities(folder)
    assert any("fabricated-decimal" in m and "94.0" in m for m in unbacked), unbacked
    assert any("94" in message for message in unbacked), unbacked


def test_a_number_and_its_unit_split_by_the_ledger_inside_one_cell_still_catches_a_fabrication(
    tmp_path,
):
    """#376 round 2: excluding the audit line must not fuse the text either side of it. A cell
    whose stdout holds a number, then the ledger, then that very number's unit -- a shape
    ``_append_cell`` never otherwise exercises, since every other test here puts the ledger last
    in its cell rather than between two lines. Dropping the whole line (rather than blanking its
    content) used to splice "180" and "ms" together across the one optional whitespace
    character ``_LATENCY_MS`` (and ``_SECONDS``, ``_THROUGHPUT``, ``_PRICE_AMOUNT``; ``_PERCENT``
    has allowed any run of spaces since #542, always within one line) allow, backing a latency the
    recipe never printed. Since #380 the units are also read per
    line, so this test alone no longer fails for a mutant that deletes the audit line; the
    scanned text is therefore pinned directly too: the blanked line must remain a line between
    its neighbours (``_scanned_output``), and the end-to-end result must still catch the claim."""
    audit_line = _real_audit_line()
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(
        folder,
        "code",
        "median latency 180\n" + audit_line + "\nms over the sample\n",
        cell_id="number-ledger-unit",
    )
    assert "median latency 180\n\nms over the sample\n" in _scanned_output(folder), (
        "the audit line must be blanked in place, not deleted"
    )
    _append_cell(
        folder,
        "markdown",
        "Jev answers with a median latency of 180 ms.",
        cell_id="fabricated-speed",
    )
    unbacked = _unprinted_quantities(folder)
    assert any("180" in message for message in unbacked), unbacked


def test_a_number_and_its_unit_split_across_two_cells_still_catches_a_fabrication(tmp_path):
    """#376 round 1's defect, pinned for the *terminated* shape: joining cells as a sequence of
    *lines* rather than as a sequence of *cell texts* collapses the two-newline gap
    ``origin/main`` leaves between a cell's own trailing newline and the outer join's separator
    down to one, which is exactly the one optional whitespace character ``_LATENCY_MS`` (and
    ``_SECONDS``, ``_THROUGHPUT``, ``_PRICE_AMOUNT``; ``_PERCENT`` allows any run of spaces) allow
    between a number and its
    unit -- no audit line is even needed to exercise this shape. One cell's output ends ``median
    latency 180``, terminated by its own trailing newline (as every cell built by ``_append_cell``
    is); the next cell's output begins ``ms over the sample``. Round 2 repaired the join itself
    (cell texts, not lines) for exactly this, terminated, shape, but nothing before this test
    pinned that repair as a regression test: a mutant that keeps this round's per-line blanking
    exactly as shipped and only collapses the inter-cell gap (``.rstrip("\\n")`` on each filtered
    cell's text before the outer join) is caught by the direct assertion on ``_scanned_output``
    below (the per-line scan of #380 no longer notices it end to end). This does not pin the
    *unterminated* shape (a cell whose committed stdout carries no trailing newline at all, e.g.
    ``print(..., end="")``): that one was pre-existing, and #380's own test,
    ``test_an_unterminated_output_segment_does_not_fuse_a_number_to_the_next_unit``, pins it."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(folder, "code", "median latency 180", cell_id="ends-with-number")
    _append_cell(folder, "code", "ms over the sample", cell_id="begins-with-unit")
    assert "median latency 180\n\nms over the sample\n" in _scanned_output(folder), (
        "two cells must stay separated by their own trailing newline plus the join's newline"
    )
    _append_cell(
        folder,
        "markdown",
        "Jev answers with a median latency of 180 ms.",
        cell_id="fabricated-speed",
    )
    unbacked = _unprinted_quantities(folder)
    assert any("180" in message for message in unbacked), unbacked


# #378: a digest whose only "93" is a digit run inside the hex, so before the fix it alone backed
# "The accuracy is 93%."; and a UUID with the same property.
_DIGEST_WITH_93 = "f" * 30 + "a93b" + "e" * 30
_UUID_WITH_93 = "deadbeef-cafe-4a93-bead-facefacefeed"
# Since #542 the tokenizer refuses the "93" glued to letters in the two above, so the filter is
# pinned by digests whose first digit run is the 93 itself, in front of any letter.
_DIGEST_LEADING_93 = "93" + "f" * 30 + "e" * 32
_UUID_LEADING_93 = "93adbeef-cafe-4aab-bead-facefacefeed"


@pytest.mark.parametrize(
    ("where", "line"),
    [
        ("output", f"fixture digest (sha256): {_DIGEST_WITH_93}"),
        ("output", f"run id: {_UUID_WITH_93}"),
        ("output", f"fixture digest (sha256): {_DIGEST_LEADING_93}"),
        ("output", f"run id: {_UUID_LEADING_93}"),
        ("output", f"cache key {_DIGEST_LEADING_93.upper()}"),
        ("tests", f'    assert \'"replay_key":"{_DIGEST_LEADING_93}"\' in out\n'),
        ("output", f"cache key {_DIGEST_WITH_93.upper()}"),
        # A digest glued to a word character, ``0x`` or a dot is still a digest.
        ("output", f"fixture cache file: cache_{_DIGEST_WITH_93}.json"),
        ("output", f"replay key: 0x{_DIGEST_WITH_93}"),
        ("output", f"artifact: model-v2_{_DIGEST_WITH_93}"),
        ("output", f"fixture_{_DIGEST_WITH_93}.json"),
        ("output", f"file.{_DIGEST_WITH_93}"),
        # An indented ledger pinned in the recipe's own tests: the line-prefix exclusion does not
        # reach it (#378's second comment), the hash filter does.
        ("tests", f'    assert \'"replay_key":"{_DIGEST_WITH_93}"\' in out\n'),
        ("tests", f'EXPECTED = "{AUDIT_PREFIX}{{\\"replay_key\\":\\"{_DIGEST_WITH_93}\\"}}"\n'),
    ],
)
def test_a_hash_like_token_does_not_back_a_fabricated_figure(tmp_path, where, line):
    """#378 option A. A recipe has ordinary reasons to print a digest (a fixture hash, a run id, a
    cache key) or to pin one in its tests; its hex digit runs are not quantities. Before: the
    token's own digits hold the quoted 93 (asserted on the raw text, which is what the pool read).
    After: the fabricated sentence is reported."""
    assert _without_hash_like_tokens(line) != line
    legacy_runs = [Decimal(m) for m in re.findall(r"\d+", line)]
    assert Decimal("93") in legacy_runs
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    if where == "output":
        _append_cell(folder, "code", line, cell_id="prints-a-digest")
    else:
        (folder / "tests").mkdir(exist_ok=True)
        (folder / "tests" / "test_digest.py").write_text(line, "utf-8")
    _append_cell(folder, "markdown", "The accuracy is 93%.", cell_id="fabricated")
    # Since #536 the percent quote alone no longer shows audit exclusion (a bare 93 cannot back it
    # anyway); the ordinary decimal 93.0 can, so it pins the exclusion on its own.
    _append_cell(folder, "markdown", "The accuracy is 93.0.", cell_id="fabricated-decimal")
    unbacked = _unprinted_quantities(folder)
    assert any("fabricated-decimal" in m and "93.0" in m for m in unbacked), unbacked
    assert any("fabricated" in message for message in unbacked), unbacked


def test_a_genuine_number_beside_a_hash_like_token_still_backs_its_quote(tmp_path):
    """The false-positive direction of #378: only the token is replaced, so a real figure on the
    same line stays in the pool, and so does a figure the recipe's own tests derive beside a
    pinned key."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(
        folder,
        "code",
        f"digest {_DIGEST_WITH_93} validation accuracy: 0.8800 (a pipeline check, not a Jev result)",
        cell_id="digest-and-metric",
    )
    (folder / "tests").mkdir(exist_ok=True)
    (folder / "tests" / "test_digest.py").write_text(
        f'    assert "{_DIGEST_WITH_93}" in out and total == 0.41\n', "utf-8"
    )
    for i, sentence in enumerate(
        (
            "The accuracy is 0.88 (a pipeline check, not a Jev result).",
            "The suite recomputes an accuracy of 41% from the fixtures.",
        )
    ):
        _append_cell(folder, "markdown", sentence, cell_id=f"genuine-{i}")
    assert [m for m in _unprinted_quantities(folder) if "genuine-" in m] == []


def test_a_long_pure_digit_number_is_not_hash_like_and_still_backs_its_quote(tmp_path):
    """A run of 16 or more digits has no letter, so it is a number and stays in the pool. The
    quotes below are in a form ``_AMOUNT`` reads (a decimal with 16 or more digits in a part):
    without the letter lookahead of ``_HASH_LIKE`` the run is replaced and the quote is reported."""
    assert _without_hash_like_tokens("12345678901234567.25 0.1234567890123456789") == (
        "12345678901234567.25 0.1234567890123456789"
    )
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(folder, "code", "total rows read: 12345678901234567.25", cell_id="long-int")
    _append_cell(folder, "code", "validation accuracy 0.1234567890123456789", cell_id="long-frac")
    for i, sentence in enumerate(
        (
            "It read 12345678901234567.25 rows.",
            "The accuracy is 0.1234567890123456789 (a pipeline check, not a Jev result).",
        )
    ):
        _append_cell(folder, "markdown", sentence, cell_id=f"genuine-{i}")
    assert [m for m in _unprinted_quantities(folder) if "genuine-" in m] == []


def test_a_digit_free_hex_run_has_no_effect_on_the_pool():
    """``_HASH_LIKE`` needs no digit requirement: a run of 16 or more letters from a to f holds no
    digit, so replacing it (as the pattern does) or keeping it leaves every number of the text,
    and its neighbours (a hex run cannot touch a digit, the lookarounds forbid it), unchanged."""
    text = "n 7 deadbeefdeadbeef 8.5 cafebabecafebabe.9 x1"
    assert _decimals(_without_hash_like_tokens(text)) == _decimals(text)


# #542: a digit run glued on its left to a letter or an underscore is part of an identifier. Each
# shape below carries a "93" inside the identifier (so before the fix it alone backed a fabricated
# "93.0"), in a form no hash-like or audit-line filter reaches: the docs listed the first four as
# leaks.
_IDENTIFIERS_WITH_93 = {
    "git-short-sha": "commit e4b7a93",
    "base64-id": "object QWJj93RlZg==",
    "base32-id": "ticket MFRGG93DFEBRW63",
    "mixed-case-id": "session Xk93Qz",
    "underscore-id": "fixture run_93",
}


@pytest.mark.parametrize("where", ["output", "tests"])
@pytest.mark.parametrize("shape", sorted(_IDENTIFIERS_WITH_93))
def test_a_digit_run_inside_an_identifier_does_not_back_a_fabricated_figure(tmp_path, shape, where):
    """#542: the tokenizer, not another filter, refuses a digit run glued to a letter or an
    underscore, from committed output and from the recipe's own tests. Each identifier is
    ASCII-clean and no hash-like or audit-line rule touches it."""
    line = _IDENTIFIERS_WITH_93[shape]
    assert _without_hash_like_tokens(line) == line
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    if where == "output":
        _append_cell(folder, "code", line, cell_id="prints-an-identifier")
    else:
        (folder / "tests").mkdir(exist_ok=True)
        (folder / "tests" / "test_identifier.py").write_text(f"ID = {line!r}\n", "utf-8")
    _append_cell(folder, "markdown", "The accuracy is 93.0.", cell_id="fabricated-decimal")
    unbacked = _unprinted_quantities(folder)
    assert any("fabricated-decimal" in m and "93.0" in m for m in unbacked), unbacked


def test_a_genuine_figure_beside_an_identifier_still_backs_its_quote(tmp_path):
    """#542: ``run_93`` backs nothing, but the genuine ``93ms`` after it (a trailing unit) is
    still a latency, so its quote is backed."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(folder, "code", "run_93 median latency 93ms", cell_id="printed")
    _append_cell(folder, "markdown", "Jev answers with a median latency of 93 ms.", cell_id="q")
    assert [m for m in _unprinted_quantities(folder) if "'93 ms'" in m] == []


@pytest.mark.parametrize(
    ("printed", "sentence"),
    [
        ("sku93ms", "Jev answers with a median latency of 93 ms."),
        ("sku93%", "Jev reaches an accuracy of 93%."),
        ("sku93 USD", "Jev costs 93 USD per call."),
        ("sku93 tokens/s", "Jev reaches 93 tokens/s."),
        ("sku93 seconds", "Jev is slow: the live run takes 93 seconds."),
    ],
)
def test_a_glued_unit_figure_does_not_back_its_quote(tmp_path, printed, sentence):
    """#542: an identifier whose digits are followed by a unit (``sku93ms``, ``sku93%``) is not a
    printed latency, percentage, price, throughput or seconds figure: the left boundary also
    holds in the unit patterns, which read their own digits."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(folder, "code", printed, cell_id="printed")
    _append_cell(folder, "markdown", sentence, cell_id="quote")
    unbacked = _unprinted_quantities(folder)
    assert any("quote" in m for m in unbacked), unbacked


@pytest.mark.parametrize("text", ["token Qx931", "id Qx9314Zk", "run_8801 x"])
def test_the_scan_does_not_restart_at_a_later_digit_of_a_refused_run(text):
    """#542: a lookbehind alone would refuse the run at its first digit and then read it again
    from its second (``931`` as ``31``); the whole run is consumed instead."""
    assert _decimals(text) == []


@pytest.mark.parametrize(
    ("printed", "sentence"),
    [
        ("sku1.93%", "Jev reaches an accuracy of 93%."),
        ("build v1.180ms", "Jev answers with a median latency of 180 ms."),
        ("ver v1.93", "The accuracy is 93.0."),
        ("commit e4b7a1.93", "The accuracy is 93.0."),
        ("sku1,093", "The accuracy is 1093.0."),
        ("x1,250", "The accuracy is 1250.0."),
        ("sku1.2.93%", "Jev reaches an accuracy of 93%."),
        ("build v1.2.180ms", "Jev answers with a median latency of 180 ms."),
    ],
)
def test_the_decimal_tail_of_a_glued_token_does_not_back_its_quote(tmp_path, printed, sentence):
    """#542 review: the scan must not restart after the ``.`` of a refused token. Each row is
    unbacked on main (which reads the whole ``1.93`` or ``1.180ms``) and was backed by the first
    head of this change, which refused the ``1`` and then read the tail."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(folder, "code", printed, cell_id="printed")
    _append_cell(folder, "markdown", sentence, cell_id="quote")
    unbacked = _unprinted_quantities(folder)
    assert any("quote" in m for m in unbacked), unbacked


@pytest.mark.parametrize(
    ("printed", "sentence"),
    [
        ("accuracy,93%", "Jev reaches an accuracy of 93%."),
        ("jev,93.0%", "Jev reaches an accuracy of 93%."),
        ("0.5,93%", "Jev reaches an accuracy of 93%."),
        ("tok/s,93 tokens/s", "Jev reaches 93 tokens/s."),
        ("latency,180ms", "Jev answers with a median latency of 180 ms."),
        ("model,accuracy,93.0", "The accuracy is 93.0."),
        ("t01,0.93", "The accuracy is 0.93."),
        ("t01,93%", "Jev reaches an accuracy of 93%."),
        ("t01,0.9474", "Jev reaches an accuracy of 95%."),
        ("case_7,0.93", "The accuracy is 0.93."),
        ("F1,0.93", "The accuracy is 0.93."),
        ("metric,F1,0.93", "The accuracy is 0.93."),
        ("top5,93%", "Jev reaches an accuracy of 93%."),
        ("top5,0.93", "Jev reaches an accuracy of 93%."),
        ("gpt4,93%", "Jev reaches an accuracy of 93%."),
        ("run_1,93%", "Jev reaches an accuracy of 93%."),
        ("R2,0.93", "The accuracy is 0.93."),
    ],
)
def test_a_figure_after_a_comma_is_still_backed(tmp_path, printed, sentence):
    """#542 review: only a token glued to a letter is refused, with its own thousands-group and
    decimal tails.
    A figure after a plain ``,`` (a CSV row without spaces) is a printed figure, as on main; the
    first version of the tail rule, a lookbehind on ``[A-Za-z_\\d][.,]``, refused all of these."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(folder, "code", printed, cell_id="printed")
    _append_cell(folder, "markdown", sentence, cell_id="quote")
    assert [m for m in _unprinted_quantities(folder) if "quote" in m] == []


def test_the_mask_replaces_digits_one_for_one():
    """#542: ``_mask_glued`` keeps every position (digits become ``#``, nothing is deleted), so a
    span found in the masked text is a span of the original."""
    text = "sku1.93% t01,0.93 x1,250 F1 0.9"
    masked = _mask_glued(text)
    assert masked == "sku#.##% t##,0.93 x#,### F# 0.9"
    assert len(masked) == len(text)
    assert _mask_glued("t01,1234 x1,2500") == "t##,1234 x#,2500"


def test_the_f1_metric_word_is_still_read_beside_a_quote():
    """#542: the prose side keeps the digit of the metric word ``F1`` (masking it would hide every
    F1 quote)."""
    assert _quoted_quantities("The F1 is 0.9474.") == [("metric", "0.9474")]
    assert _quoted_quantities("The F1,0.93 holds.") == [("metric", "0.93")]


_TABLE = "| Metric | Value |\n| --- | --- |\n| {label} | {value} |\n"


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("accuracy", "93%"),
        ("accuracy", "0.93"),
        ("**Median latency**", "180 ms"),
        ("cost per call", "$0.0004 a call"),
        ("precision", "`0.93`"),
    ],
)
def test_a_table_row_quoting_an_unprinted_figure_is_flagged(tmp_path, where, label, value):
    """#691: a figure in a table cell is a quote, read under its row label, in the README and in
    a notebook markdown cell alike."""
    folder = _copy_recipe(tmp_path, "_template")
    assert _unprinted_quantities(folder) == []
    table = _TABLE.format(label=label, value=value)
    if where == "readme":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + table, "utf-8")
    else:
        _append_cell(folder, "markdown", table)
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1, violations
    assert ("README.md" if where == "readme" else "honesty-probe") in violations[0]


@pytest.mark.parametrize(
    ("label", "value"),
    [("accuracy", "80%"), ("accuracy", "0.8000"), ("accuracy", "80.0%"), ("risk", "0.20")],
)
def test_a_table_row_quoting_a_printed_figure_is_not_flagged(tmp_path, label, value):
    """#691: the template prints ``accuracy of the choice: 0.80``, so the same figure in a table
    row is backed by the same pools as prose, and a risk by the printed accuracy's complement."""
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", _TABLE.format(label=label, value=value))
    assert _unprinted_quantities(folder) == []


# #713: a Markdown link around a metric word hid the word from the quote reader, because the
# closing ``]`` is not a connective. Each shape below is the same sentence or row with the metric
# word linked; the template prints ``accuracy of the choice: 0.80``, so 93% is not printed.
_LINKED_METRIC = [
    pytest.param("The [accuracy](../../docs/glossary.md#accuracy) is {value}.", id="inline"),
    pytest.param("The [`accuracy`](../../docs/glossary.md#accuracy) is {value}.", id="code-span"),
    pytest.param(
        "The [accuracy][glossary] is {value}.\n\n[glossary]: ../../docs/glossary.md", id="reference"
    ),
    pytest.param(
        "The [accuracy][] is {value}.\n\n[accuracy]: ../../docs/glossary.md", id="collapsed"
    ),
    pytest.param("The [accuracy] is {value}.\n\n[accuracy]: ../../docs/glossary.md", id="shortcut"),
    pytest.param("| [accuracy](../../docs/glossary.md#accuracy) | {value} |", id="table-inline"),
    pytest.param(
        "| [accuracy][glossary] | {value} |\n\n[glossary]: ../../docs/glossary.md",
        id="table-reference",
    ),
]


def _linked_text(shape: str, value: str) -> str:
    text = shape.format(value=value)
    if shape.startswith("|"):
        text = "| Metric | Value |\n| --- | --- |\n" + text
    return text


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("shape", _LINKED_METRIC)
def test_a_linked_metric_word_next_to_an_unprinted_figure_is_flagged(tmp_path, where, shape):
    folder = _copy_recipe(tmp_path, "_template")
    assert _unprinted_quantities(folder) == []
    text = _linked_text(shape, "93%")
    if where == "readme":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + text + "\n", "utf-8")
    else:
        _append_cell(folder, "markdown", text)
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "'93%'" in violations[0], violations


@pytest.mark.parametrize("shape", _LINKED_METRIC)
def test_a_linked_metric_word_next_to_a_printed_figure_is_not_flagged(tmp_path, shape):
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", _linked_text(shape, "80%"))
    assert [q for _, _, q in _prose_quotes(folder) if q == "80%"], "the linked figure is read"
    assert _unprinted_quantities(folder) == []


def test_link_text_is_kept_and_link_targets_and_images_are_not_read_as_claims():
    cleaned = _clean_markdown(
        "[a `b`](x.md#y) [c][r] [d][] ![alt text](p.png)\n\n[r]: u.md\n[d]: v.md"
    )
    assert cleaned.startswith("a `b` c d ![alt text]"), cleaned
    # an image is not a link: its alt text is neither unwrapped nor given a target to read
    assert "p.png" not in cleaned and "x.md" not in cleaned
    # brackets that are no link stay as written
    assert _clean_markdown("see [1] and [note]") == "see [1] and [note]"


def _row_quotes(row: str) -> list[tuple[str, str]]:
    """What ``_table_scan`` makes of ``row`` as the one data row of a table, as quotes."""
    rows, _ = _table_scan(f"| Metric | Value |\n| --- | --- |\n{row}\n")
    assert len(rows) == 1, rows
    return _table_row_quantities(rows[0])


def test_a_table_row_is_read_cell_by_cell_under_its_row_label():
    assert _row_quotes("| accuracy | 93% |") == [("rate", "93%")]
    assert _row_quotes("| Coverage | 0.92 | 0.88 |") == [("metric", "0.92"), ("metric", "0.88")]
    assert _row_quotes("| median latency | 180 ms |") == [("speed", "180 ms")]
    # a label that is no metric word makes no quote of a figure, as in prose
    assert _row_quotes("| rows | 93% |") == []
    assert _row_quotes("| rows | 1,250 |") == []
    # a figure glued to an identifier stays an identifier
    assert _row_quotes("| accuracy | sku93% |") == []


def test_a_second_figure_in_a_cell_is_the_documented_limit():
    # a cell with several figures quotes the one next to the metric word
    assert _row_quotes("| precision / recall | 0.93 / 0.91 |") == [("metric", "0.93")]


def test_an_escaped_pipe_does_not_split_a_cell():
    assert _table_cells(r"| accuracy \| risk | 93% |") == [r"accuracy \| risk", "93%"]
    assert _row_quotes(r"| accuracy \| risk | 93% |") == [("rate", "93%")]
    assert _table_cells(r"| accuracy | 93% \| x |") == ["accuracy", r"93% \| x"]


_TABLE_SHAPES = {
    "outer-pipes": "| Metric | Value |\n| --- | --- |\n| accuracy | 93% |\n",
    "no-outer-pipes": "Metric | Value\n--- | ---\naccuracy | 93%\n",
    "blockquote": "> | Metric | Value |\n> | --- | --- |\n> | accuracy | 93% |\n",
    "blockquote-no-space": ">| Metric | Value |\n>| --- | --- |\n>| accuracy | 93% |\n",
    "nested-blockquote": "> > Metric | Value\n> > --- | ---\n> > accuracy | 93%\n",
    "alignment-colons": "| Metric | Value |\n|:---|---:|\n| accuracy | 93% |\n",
    "after-a-paragraph": "Results follow.\n\n| Metric | Value |\n| --- | --- |\n| accuracy | 93% |\n",
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("shape", sorted(_TABLE_SHAPES))
def test_every_gfm_table_shape_is_read_in_the_readme_and_in_a_markdown_cell(tmp_path, shape, where):
    """#691: a table without outer pipes or inside a blockquote is a table too."""
    folder = _copy_recipe(tmp_path, "_template")
    assert _unprinted_quantities(folder) == []
    table = _TABLE_SHAPES[shape]
    if where == "readme":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + table, "utf-8")
    else:
        _append_cell(folder, "markdown", table)
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "'93%'" in violations[0], violations


# --- #698: a cell's context is its column header and every other cell of its row -------------------

_LAYOUTS = {
    # the metric word is in another column than the first
    "metric-in-another-column": (
        "| model | metric | value |\n| --- | --- | --- |\n| jev | accuracy | 93% |\n"
    ),
    "label-cell-holds-the-figure": "| value | metric |\n| --- | --- |\n| 93% | accuracy |\n",
    # transposed: the metric names sit in the column header
    "transposed": "| model | accuracy | rows |\n| --- | --- | --- |\n| jev | 93% | 4 |\n",
    "milliseconds-in-the-header": "| model | latency (ms) |\n| --- | --- |\n| jev | 93 |\n",
    "transposed-no-outer-pipes": "model | accuracy\n--- | ---\njev | 93%\n",
    "transposed-blockquote": "> | model | accuracy |\n> | --- | --- |\n> | jev | 93% |\n",
    # the unit is only in the column header
    "percent-in-the-header": "| metric | value (%) |\n| --- | --- |\n| accuracy | 93 |\n",
    "percent-sign-in-the-header": "| metric | % |\n| --- | --- |\n| accuracy | 93 |\n",
    "unit-and-metric-in-the-header": "| model | accuracy (%) |\n| --- | --- |\n| jev | 93 |\n",
    # a figure split across cells
    "split-percent": "| metric | value |\n| --- | --- | --- |\n| accuracy | 93 | % |\n",
    # an HTML table
    "html": (
        "<table><tr><th>metric</th><th>value</th></tr>"
        "<tr><td>accuracy</td><td>93%</td></tr></table>\n"
    ),
    "html-multiline": (
        "<table>\n<thead>\n<tr><th>model</th><th>accuracy</th></tr>\n</thead>\n"
        "<tbody>\n<tr>\n<td>jev</td>\n<td>93%</td>\n</tr>\n</tbody>\n</table>\n"
    ),
    "html-unit-in-the-header": (
        "<table><tr><th>metric</th><th>value (%)</th></tr>"
        "<tr><td>accuracy</td><td>93</td></tr></table>\n"
    ),
    "html-row-header": (
        "<table><tr><th>model</th><th>accuracy</th></tr><tr><th>jev</th><td>93%</td></tr></table>\n"
    ),
}


def _with_markdown(folder: Path, where: str, markdown: str) -> None:
    if where == "readme":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + markdown, "utf-8")
    else:
        _append_cell(folder, "markdown", markdown)


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("layout", sorted(_LAYOUTS))
def test_a_figure_the_header_or_the_row_gives_a_metric_word_is_checked(tmp_path, layout, where):
    """#698: ``93%`` is not printed by the template, so every layout of a table that quotes it
    under a metric word, whichever cell or header carries the word, is flagged once."""
    folder = _copy_recipe(tmp_path, "_template")
    assert _unprinted_quantities(folder) == []
    _with_markdown(folder, where, _LAYOUTS[layout])
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "93" in violations[0], violations


_PRINTED_LAYOUTS = {
    # the template prints ``accuracy of the choice: 0.80``
    "metric-in-another-column": (
        "| model | metric | value |\n| --- | --- | --- |\n| jev | accuracy | 80% |\n"
    ),
    "transposed": "| model | accuracy |\n| --- | --- |\n| jev | 0.80 |\n",
    "percent-in-the-header": "| metric | value (%) |\n| --- | --- |\n| accuracy | 80 |\n",
    "split-percent": "| metric | value |\n| --- | --- | --- |\n| accuracy | 80 | % |\n",
    "html": (
        "<table><tr><th>model</th><th>accuracy</th></tr><tr><td>jev</td><td>80%</td></tr></table>\n"
    ),
}


@pytest.mark.parametrize("layout", sorted(_PRINTED_LAYOUTS))
def test_a_printed_figure_in_any_table_layout_is_not_flagged(tmp_path, layout):
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", _PRINTED_LAYOUTS[layout])
    assert _unprinted_quantities(folder) == []


@pytest.mark.parametrize(
    "table",
    [
        # a header or another cell with no metric word gives a figure no context
        "| run | value (%) |\n| --- | --- |\n| a | 93 |\n",
        "| model | count |\n| --- | --- |\n| jev | 93 |\n",
        "| model | rows |\n| --- | --- |\n| jev | 93% |\n",
        "| parameter | value |\n| --- | --- |\n| threshold | 0.85 |\n| seed | 42 |\n",
        # a bare number under a header that names no unit has no unit
        "| metric | value |\n| --- | --- |\n| accuracy | 93 |\n",
        "<table><tr><th>run</th><th>rows</th></tr><tr><td>a</td><td>93%</td></tr></table>\n",
    ],
)
def test_a_table_with_no_metric_word_in_its_header_or_row_quotes_nothing(tmp_path, table):
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", table)
    assert _unprinted_quantities(folder) == []


def test_each_cell_is_read_under_its_own_column_header():
    columns = ["model", "accuracy", "latency (ms)", "risk (%)"]
    row = ["jev", "0.93", "180", "5"]
    assert _table_row_quantities(row, columns) == [
        ("rate", "0.93"),
        ("speed", "180 ms"),
        ("rate", "5%"),
    ]
    # a metric word in another cell of the row is context without any header
    assert _table_row_quantities(["jev", "accuracy", "93%"], ["model", "metric", "value"]) == [
        ("rate", "93%")
    ]
    assert _table_row_quantities(["93%", "accuracy"]) == [("rate", "93%")]
    # a row longer than its header: the extra cell has no column header
    assert _table_row_quantities(["accuracy", "93%", "91%"], ["metric", "value"]) == [
        ("rate", "93%"),
        ("rate", "91%"),
    ]


def test_a_header_unit_is_read_from_the_header_words():
    assert _header_unit("value (%)") == "{n}%"
    assert _header_unit("accuracy %") == "{n}%"
    assert _header_unit("latency, ms") == "{n} ms"
    assert _header_unit("latency (s)") == "{n} seconds"
    assert _header_unit("price ($)") == "${n}"
    assert _header_unit("throughput (calls/s)") == "{n} calls/s"
    assert _header_unit("accuracy") is None
    assert _header_unit("users") is None


def test_a_unit_in_its_own_cell_joins_the_number_before_it():
    assert _merge_split_figures(["accuracy", "93", "%"]) == [(0, "accuracy"), (1, "93%")]
    assert _merge_split_figures(["latency", "180", "ms"]) == [(0, "latency"), (1, "180 ms")]
    # a unit word after a word is not a split figure
    assert _merge_split_figures(["accuracy", "s"]) == [(0, "accuracy"), (1, "s")]
    assert _table_row_quantities(["accuracy", "93", "%"]) == [("rate", "93%")]
    assert _table_row_quantities(["latency", "180", "ms"]) == [("speed", "180 ms")]


def test_a_markdown_table_scan_keeps_each_rows_column_headers():
    rows, _ = _scan_tables("| model | accuracy |\n| --- | --- |\n| jev | 93% |\n| x | 1 |\n")
    assert rows == [(["model", "accuracy"], ["jev", "93%"]), (["model", "accuracy"], ["x", "1"])]


def test_an_html_table_is_read_into_rows_and_blanked_out_of_the_prose():
    text = (
        "Before.\n<TABLE border=1>\n<tr><th>model</th><th>accuracy</th></tr>\n"
        "<tr><td>jev</td><td>93%</td></tr>\n<tr><th>row</th><td>1 <b>x</b></td></tr>\n"
        "</TABLE>\nAfter.\n"
    )
    rows, prose = _scan_tables(text)
    assert rows == [
        (["model", "accuracy"], ["jev", "93%"]),
        (["model", "accuracy"], ["row", "1 x"]),
    ]
    assert "93%" not in prose and "Before." in prose and "After." in prose


def test_an_html_table_without_a_header_row_or_closing_tag_still_gives_its_rows():
    rows, _ = _scan_tables("<table><tr><td>accuracy</td><td>93%</td></tr>")
    assert rows == [([], ["accuracy", "93%"])]
    rows, _ = _scan_tables("<table><td>accuracy</td><td>93%</td></table>")
    assert rows == [([], ["accuracy", "93%"])]


# --- #698 review round: an HTML block, an over-eager context, a header figure, a header rule ---

_TABLE_MENTIONS = {
    "inline-code-mention": "Render it as a `<table>` element.\n\nOverall accuracy is 93% on the set.\n",
    "unclosed-table": "<table><tr><td>a</td><td>b</td></tr>\n\nOverall accuracy is 93% on the set.\n",
    "mention-mid-line": "Use <table> markup here. Overall accuracy is 93% on the set.\n",
    "mention-after-a-table": (
        "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>\n\n"
        "Render it as a `<table>` element. Overall accuracy is 93% on the set.\n"
    ),
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("case", sorted(_TABLE_MENTIONS))
def test_a_table_mention_or_an_unclosed_table_hides_no_sentence_after_it(tmp_path, case, where):
    """A ``<table`` in inline code or mid-line opens no HTML block, and an unclosed table ends at
    the first blank line (GFM), so the sentence below is still read, as on main."""
    folder = _copy_recipe(tmp_path, "_template")
    _with_markdown(folder, where, _TABLE_MENTIONS[case])
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "'93%'" in violations[0], violations


def test_a_table_inside_an_inline_code_span_is_prose():
    """The code span is masked before the search, whatever line of it the tag sits on."""
    text = "Write `a\n<table><tr><td>x</td><td>1</td></tr></table> b` here.\n"
    rows, prose = _scan_tables(text)
    assert rows == [] and prose == text.rstrip()
    text = "<table><tr><td>x</td><td>1</td></tr>\n`</table>` inside\n\nafter\n"
    rows, prose = _scan_tables(text)
    assert rows == [([], ["x", "1"])] and "inside" in prose and "after" in prose


def test_an_html_block_starts_at_a_line_and_ends_at_the_close_tag_or_a_blank_line():
    rows, prose = _scan_tables("Use `<table>` here.\n\nafter\n")
    assert rows == [] and "after" in prose
    rows, prose = _scan_tables("<table><tr><td>a</td><td>1</td></tr>\n\nafter\n")
    assert rows == [([], ["a", "1"])] and prose.strip() == "after"
    rows, prose = _scan_tables("> <table><tr><td>a</td><td>1</td></tr></table>\nafter\n")
    assert rows == [([], ["a", "1"])] and "after" in prose and "<table" not in prose
    rows, _ = _scan_tables("   <table><tr><td>a</td><td>1</td></tr></table>\n")
    assert rows == [([], ["a", "1"])]
    # indented four spaces it is a list item's table or a code block that a reader may take
    # for one: read, so a figure is never hidden
    rows, _ = _scan_tables("    <table><tr><td>a</td><td>1</td></tr></table>\n")
    assert rows == [([], ["a", "1"])]


_T = "<table><tr><th>model</th><th>accuracy</th></tr><tr><td>jev</td><td>93%</td></tr></table>"
_TABLE_PLACES = {
    "div-wrapper": f'<div align="center">{_T}</div>\n',
    "after-text": f"Results: {_T}\n",
    "list-item-indented-four": f"-   Results\n\n    {_T}\n",
    "numbered-item-indented": f"1. Results\n\n   {_T}\n",
    "blank-line-inside": (
        "<table><tr><th>model</th><th>accuracy</th></tr>"
        "<tr><td>jev</td>\n\n<td>93%</td></tr></table>\n"
    ),
    "blank-line-inside-in-a-div": (
        "<div><table><tr><th>model</th><th>accuracy</th></tr>\n\n"
        "<tr><td>jev</td><td>93%</td></tr></table></div>\n"
    ),
    "blockquote-after-text": f"> Results: {_T}\n",
    "mention-then-a-table": f"Use <table> markup here.\n\n{_T}\n",
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("place", sorted(_TABLE_PLACES))
def test_a_closed_html_table_is_read_wherever_it_sits_on_its_line(tmp_path, place, where):
    """GitHub renders each of these as a table, so ``93%`` is a quote under ``accuracy``."""
    folder = _copy_recipe(tmp_path, "_template")
    assert _unprinted_quantities(folder) == []
    _with_markdown(folder, where, _TABLE_PLACES[place])
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "'93%'" in violations[0], violations


def test_which_html_table_text_is_a_table():
    # a closed table: wherever its tag is, and across a blank line
    rows, prose = _scan_tables(f"<div>{_T}</div> tail\n")
    assert len(rows) == 1 and prose.split() == ["<div>", "</div>", "tail"]
    rows, _ = _scan_tables("<table><tr><td>a</td>\n\n<td>1</td></tr></table>\n")
    assert rows == [([], ["a", "1"])]
    # a mention earlier on the line is not what opens the table
    rows, prose = _scan_tables("see <table> markup, then " + _T + "\n")
    assert len(rows) == 1 and "see <table> markup" in prose
    # no end tag: only at a line start, ending at the blank line
    assert _scan_tables("Use <table> markup here.\n\nafter\n")[0] == []
    rows, prose = _scan_tables("Results: <table><tr><td>a</td><td>1</td></tr>\n\nafter\n")
    assert rows == [] and "after" in prose
    rows, prose = _scan_tables("  <table><tr><td>a</td><td>1</td></tr>\n\nafter\n")
    assert rows == [([], ["a", "1"])] and prose.strip() == "after"
    rows, prose = _scan_tables("    <table><tr><td>a</td><td>1</td></tr>\n\nafter\n")
    assert rows == [([], ["a", "1"])] and prose.strip() == "after"
    # an unclosed table that meets a blank line drops the rows after it
    rows, _ = _scan_tables(
        "<table><tr><td>a</td><td>1</td></tr>\n\n<tr><td>b</td><td>2</td></tr>\n"
    )
    assert rows == [([], ["a", "1"])]


@pytest.mark.parametrize("where", ["readme", "markdown"])
def test_a_table_in_a_fence_is_not_read(tmp_path, where):
    folder = _copy_recipe(tmp_path, "_template")
    _with_markdown(folder, where, f"```html\n{_T}\n```\n")
    assert _unprinted_quantities(folder) == []


_LOOSE_TEXT = {
    "bare-table-and-end-tag-in-a-sentence": (
        "Wrap it in <table> tags: overall accuracy is 93% here, then end with </table>.\n"
    ),
    "paragraph-between-a-bare-tag-and-a-later-end-tag": (
        "Use <table> markup.\n\nOverall accuracy is 93% on the set.\n\nEnd it with </table>.\n"
    ),
    "unclosed-table-at-a-line-start": "<table> is the tag to use; overall accuracy is 93% here.\n",
    "text-before-the-rows": (
        "<table>Overall accuracy is 93%.<tr><td>a</td><td>b</td></tr></table>\n"
    ),
    "text-between-the-rows": (
        "<table><tr><td>a</td><td>b</td></tr>Overall accuracy is 93%.<tr><td>c</td></tr></table>\n"
    ),
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("case", sorted(_LOOSE_TEXT))
def test_text_an_html_table_holds_outside_its_cells_is_still_read(tmp_path, case, where):
    """GitHub shows text outside a cell as ordinary text, so a claim there is checked."""
    folder = _copy_recipe(tmp_path, "_template")
    _with_markdown(folder, where, _LOOSE_TEXT[case])
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "'93%'" in violations[0], violations


def test_text_outside_the_cells_goes_back_to_the_prose_and_the_cells_stay_rows():
    rows, prose = _scan_tables("<table>Note 93%.<tr><td>a</td><td>1</td></tr></table>\n")
    assert rows == [([], ["a", "1"])]
    assert "Note 93%." in prose and "<td>" not in prose
    rows, prose = _scan_tables("Wrap in <table> tags, then </table>.\n")
    assert rows == [] and prose.split() == ["Wrap", "in", "tags,", "then", "."]
    # the cells' own text is a row, not prose
    rows, prose = _scan_tables(f"{_T}\n")
    assert len(rows) == 1 and "93%" not in prose


def test_a_directional_word_is_no_metric_name_qualifier():
    for word in ("higher", "lower", "more", "less", "better", "worse"):
        assert not _is_metric_name(f"{word} coverage"), word
    assert _table_row_quantities(["gate", "0.70", "higher coverage"]) == []
    assert _table_row_quantities(["gate", "0.70", "coverage"]) == [("metric", "0.70")]


_PARAMETER_TABLE = (
    "| parameter | value | effect |\n| --- | --- | --- |\n"
    "| threshold | 0.65 | raises coverage |\n| budget | 0.50 | caps risk |\n"
)


@pytest.mark.parametrize("where", ["readme", "markdown"])
def test_a_phrase_that_only_ends_in_a_metric_word_is_no_context_for_another_cell(tmp_path, where):
    """Prose quotes nothing for "The threshold 0.65 raises coverage.", so a neighbouring cell
    counts as context only when it is itself a metric name."""
    folder = _copy_recipe(tmp_path, "_template")
    _with_markdown(folder, where, _PARAMETER_TABLE)
    assert _unprinted_quantities(folder) == []


@pytest.mark.parametrize(
    ("cell", "is_name"),
    [
        ("accuracy", True),
        ("Top-1 accuracy", True),
        ("error rate", True),
        ("mean error rate", True),
        ("latency", True),
        ("**accuracy**", True),
        ("accuracy (%)", True),
        ("raises coverage", False),
        ("caps risk", False),
        ("the accuracy of the run", False),
        ("accuracy 93%", False),
        ("accuracy on the held-out split", False),
        ("threshold", False),
        ("", False),
    ],
)
def test_a_metric_name_cell_is_a_metric_noun_with_a_short_qualifier(cell, is_name):
    assert _is_metric_name(cell) is is_name


def test_the_label_cell_is_always_context_and_a_metric_name_cell_is_context():
    assert _table_row_quantities(["threshold", "0.65", "raises coverage"]) == []
    assert _table_row_quantities(["budget", "0.50", "caps risk"]) == []
    assert _table_row_quantities(["median latency", "1.2 seconds"]) == [("speed", "1.2 seconds")]
    assert _table_row_quantities(["jev", "accuracy", "0.93"]) == [("rate", "0.93")]
    assert _table_row_quantities(["jev", "mean accuracy", "0.93"]) == [("rate", "0.93")]


@pytest.mark.parametrize("where", ["readme", "markdown"])
def test_a_figure_in_a_header_row_is_read_once_not_once_per_data_row(tmp_path, where):
    table = "| accuracy 93% | value |\n| --- | --- |\n| a | 1 |\n| b | 2 |\n"
    folder = _copy_recipe(tmp_path, "_template")
    _with_markdown(folder, where, table)
    assert len(_unprinted_quantities(folder)) == 1
    assert _table_row_quantities(["a", "1"], ["accuracy 93%", "value"]) == []
    assert _header_words("accuracy 93% (%)") == "accuracy"
    assert _header_words("top-5 accuracy") == "top-5 accuracy"
    assert _header_words("accuracy 0.93") == "accuracy"


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize(
    "table",
    [
        "| model | accuracy<br>(%) |\n| --- | --- |\n| jev | 93 |\n",
        "| model | accuracy<br/>(%) |\n| --- | --- |\n| jev | 93 |\n",
        "| model | accuracy |\n| --- | --- |\n| jev | 93%<br> |\n",
        "| model | <b>accuracy</b> |\n| --- | --- |\n| jev | 93% |\n",
        "| model | accuracy |\n| --- | --- |\n| jev | <b>93%</b> |\n",
        "<table><tr><th>model</th><th>accuracy<br>(%)</th></tr><tr><td>jev</td><td>93</td></tr></table>\n",
    ],
)
def test_an_inline_tag_in_a_cell_does_not_hide_the_header(tmp_path, table, where):
    folder = _copy_recipe(tmp_path, "_template")
    _with_markdown(folder, where, table)
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "93" in violations[0], violations


_LABEL_UNITS = {
    "percent-label": "| accuracy (%) | 93 |\n| --- | --- |\n| accuracy (%) | 93 |\n",
    "percent-label-transposed": "| metric | a | b |\n| --- | --- | --- |\n| accuracy (%) | 93 | 91 |\n",
    "percent-label-fraction": "| metric | value |\n| --- | --- |\n| accuracy (%) | 0.93 |\n",
    "percent-label-fraction-printed": "| metric | value |\n| --- | --- |\n| accuracy (%) | 0.80 |\n",
    "ms-label": "| metric | value |\n| --- | --- |\n| latency (ms) | 93 |\n",
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("case", sorted(_LABEL_UNITS))
def test_a_unit_in_the_row_label_is_applied_to_a_bare_number(tmp_path, case, where):
    """``| accuracy (%) | 0.80 |`` claims 0.80 %, a 100x error next to the printed 0.80: flagged."""
    folder = _copy_recipe(tmp_path, "_template")
    _with_markdown(folder, where, _LABEL_UNITS[case])
    assert _unprinted_quantities(folder), case


def test_a_label_unit_backs_a_printed_percentage_and_never_a_fraction(tmp_path):
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", "| metric | value |\n| --- | --- |\n| accuracy (%) | 80 |\n")
    assert _unprinted_quantities(folder) == []
    assert _table_row_quantities(["accuracy (%)", "93"]) == [("rate", "93%")]
    assert _table_row_quantities(["accuracy (%)", "93", "91"]) == [("rate", "93%"), ("rate", "91%")]
    # the header's unit comes first
    assert _table_row_quantities(["latency (ms)", "93"], ["metric", "value (%)"]) == []
    assert _table_row_quantities(["accuracy (%)", "93"], ["metric", "value (%)"]) == [
        ("rate", "93%")
    ]


def test_a_header_or_label_unit_is_applied_to_a_bare_number_only():
    columns = ["metric", "value (%)"]
    assert _table_row_quantities(["accuracy", "93%"], columns) == [("rate", "93%")]
    assert _table_row_quantities(["accuracy", "93 %"], columns) == [("rate", "93 %")]
    assert _table_row_quantities(["accuracy", "0.93"], columns) == [("rate", "0.93%")]
    assert _table_row_quantities(["latency", "0.18 seconds"], ["metric", "value (ms)"]) == [
        ("speed", "0.18 seconds")
    ]
    assert _table_row_quantities(["accuracy (%)", "93%"]) == [("rate", "93%")]
    # a cell that is words, not a number, gets no unit
    assert _table_row_quantities(["accuracy", "about 93"], columns) == []


def _html_rows(markup: str) -> list[tuple[list[str], list[str]]]:
    rows, _ = _scan_tables(markup)
    return rows


def test_the_html_header_row_is_the_last_thead_row_or_the_first_row_of_th_cells():
    # a <thead> row of <td> cells is the header
    assert _html_rows(
        "<table><thead><tr><td>model</td><td>accuracy</td></tr></thead>"
        "<tbody><tr><td>jev</td><td>93%</td></tr></tbody></table>"
    ) == [(["model", "accuracy"], ["jev", "93%"])]
    # the last row of a <thead> is the header; a title row above it is dropped
    assert _html_rows(
        "<table><thead><tr><td colspan=2>Results</td></tr><tr><th>model</th><th>accuracy</th></tr>"
        "</thead><tbody><tr><td>jev</td><td>93%</td></tr></tbody></table>"
    ) == [(["model", "accuracy"], ["jev", "93%"])]
    # no <thead>: the first all-<th> row, after an empty row
    assert _html_rows(
        "<table><tr></tr><tr><th>model</th><th>accuracy</th></tr><tr><td>jev</td><td>93%</td></tr>"
        "</table>"
    ) == [(["model", "accuracy"], ["jev", "93%"])]
    # a title row spanning the table is not a header, and is not a data row
    assert _html_rows(
        "<table><tr><th colspan=2>Results</th></tr><tr><th>model</th><th>accuracy</th></tr>"
        "<tr><td>jev</td><td>93%</td></tr></table>"
    ) == [(["model", "accuracy"], ["jev", "93%"])]
    # a transposed table's empty corner cell does not make its header row a data row
    assert _html_rows(
        "<table><tr><td></td><th>accuracy</th></tr><tr><th>jev</th><td>93%</td></tr></table>"
    ) == [(["", "accuracy"], ["jev", "93%"])]
    # a row of <td> cells is a header only inside a <thead>
    assert _html_rows(
        "<table><tr><td>model</td><td>accuracy</td></tr><tr><td>jev</td><td>1</td></tr></table>"
    ) == [
        ([], ["model", "accuracy"]),
        ([], ["jev", "1"]),
    ]
    # the rows above the header are passed over, the rows below are data
    assert _html_rows(
        "<table><tr><th>a</th><th>b</th></tr><tr><th>c</th><th>d</th></tr></table>"
    ) == [(["a", "b"], ["c", "d"])]


def test_an_html_colspan_keeps_the_columns_in_place():
    assert _html_rows(
        "<table><tr><th colspan=2>model</th><th>accuracy</th></tr>"
        "<tr><td>jev</td><td>v2</td><td>93%</td></tr></table>"
    ) == [(["model", "model", "accuracy"], ["jev", "v2", "93%"])]
    assert _html_rows(
        "<table><tr><th>model</th><th colspan=2>accuracy</th></tr>"
        "<tr><td>jev</td><td>93%</td><td>91%</td></tr></table>"
    ) == [(["model", "accuracy", "accuracy"], ["jev", "93%", "91%"])]
    # a nonsense span is one column
    assert _html_rows(
        "<table><tr><th colspan=x>a</th><th colspan=0>b</th></tr><tr><td>1</td><td>2</td></tr></table>"
    ) == [(["a", "b"], ["1", "2"])]


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize(
    "table",
    [
        "<table><thead><tr><td>model</td><td>accuracy</td></tr></thead>"
        "<tbody><tr><td>jev</td><td>93%</td></tr></tbody></table>\n",
        "<table><tr></tr><tr><th>model</th><th>accuracy</th></tr>"
        "<tr><td>jev</td><td>93%</td></tr></table>\n",
        "<table><tr><th colspan=2>Results</th></tr><tr><th>model</th><th>accuracy</th></tr>"
        "<tr><td>jev</td><td>93%</td></tr></table>\n",
        "<table><tr><td></td><th>accuracy</th></tr><tr><th>jev</th><td>93%</td></tr></table>\n",
        "<table><tr><th colspan=2>model</th><th>accuracy</th></tr>"
        "<tr><td>jev</td><td>v2</td><td>93%</td></tr></table>\n",
        "<table><tr><th>model</th><th colspan=2>accuracy</th></tr>"
        "<tr><td>jev</td><td>0.1</td><td>93%</td></tr></table>\n",
    ],
)
def test_an_html_table_is_read_under_its_header_row_whatever_its_shape(tmp_path, table, where):
    folder = _copy_recipe(tmp_path, "_template")
    _with_markdown(folder, where, table)
    violations = _unprinted_quantities(folder)
    assert any("'93%'" in v for v in violations), violations


_LATER_DASH_ROWS = {
    "three-dashes": "| --- | --- |",
    "one-dash": "| - | - |",
    "aligned": "|:---:|---:|",
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("dashes", sorted(_LATER_DASH_ROWS))
def test_a_later_row_of_dashes_does_not_hide_the_data_row_above_it(tmp_path, dashes, where):
    """Only the delimiter directly under the header counts. A later dash row is a data row, so
    the row above it is still a row of data and still checked."""
    folder = _copy_recipe(tmp_path, "_template")
    table = "| Metric | Value |\n| --- | --- |\n| accuracy | 93% |\n" + _LATER_DASH_ROWS[dashes]
    if where == "readme":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + table + "\n", "utf-8")
    else:
        _append_cell(folder, "markdown", table)
    assert len(_unprinted_quantities(folder)) == 1


def test_a_table_scan_reads_the_header_as_prose_and_the_rows_as_rows():
    text = "| accuracy | 93% |\n| --- | --- |\n| run | a |\n| - | - |\n| risk | 5% |\n"
    rows, prose = _table_scan(text)
    assert rows == [["run", "a"], ["-", "-"], ["risk", "5%"]]
    assert prose.splitlines()[:2] == ["| accuracy | 93% |", "| --- | --- |"]
    assert not any(line for line in prose.splitlines()[2:])
    # the header is read as prose: its figure has no label above it, so nothing is quoted
    assert _quoted_quantities(prose) == []


@pytest.mark.parametrize(
    "text",
    [
        "| accuracy | 93% |\n",  # no delimiter row: not a table
        "| accuracy | 93% |\n| run | a |\n",  # no delimiter row: not a table
        "| Metric | Value |\n| --- | --- |\n\n| accuracy | 93% |\n",  # a blank line ends it
        "| Metric | Value |\n| --- | --- |\n\n\n| accuracy | 93% |\n| --- | --- |\n",
    ],
)
def test_text_that_is_not_a_table_row_yields_no_data_rows(text):
    rows, prose = _table_scan(text)
    assert rows == []
    assert prose.startswith(text.splitlines()[0])


def test_a_lone_pipe_row_with_no_delimiter_is_prose_and_quotes_nothing(tmp_path):
    """GFM shows ``| accuracy | 93% |`` with no delimiter row as paragraph text, not as a table,
    so it takes the prose path, where a pipe is not a connective between a metric word and a
    figure: it is not flagged (documented in docs/offline-and-live.md)."""
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", "| accuracy | 93% |\n")
    assert _unprinted_quantities(folder) == []


_PIPELESS_FILLER = {
    "between-rows": "| Metric | Value |\n| --- | --- |\n| run | a |\nsee note\n| accuracy | 93% |\n",
    "right-under-the-delimiter": "| Metric | Value |\n| --- | --- |\nnote\n| accuracy | 93% |\n",
    "two-lines": "a | b\n- | -\nx | 1\nsee\nthe note\naccuracy | 93%\n",
    "in-a-blockquote": "> | Metric | Value |\n> | --- | --- |\n> note\n> | accuracy | 93% |\n",
    "inline-span": "| Metric | Value |\n| --- | --- |\n| run | a |\n<span>note</span>\n| accuracy | 93% |\n",
    "inline-sup": "| Metric | Value |\n| --- | --- |\n| run | a |\n<sup>\n| accuracy | 93% |\n",
    "inline-b": "| Metric | Value |\n| --- | --- |\n<b>note</b>\n| accuracy | 93% |\n",
    "inline-link": '| Metric | Value |\n| --- | --- |\n<a href="x">see</a>\n| accuracy | 93% |\n',
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("case", sorted(_PIPELESS_FILLER))
def test_a_line_without_a_pipe_inside_a_table_does_not_hide_the_rows_below_it(
    tmp_path, case, where
):
    """GFM: a pipe-less line in a table is a one-cell row, and the table runs on to a blank line
    or the start of another block."""
    folder = _copy_recipe(tmp_path, "_template")
    table = _PIPELESS_FILLER[case]
    if where == "readme":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + table, "utf-8")
    else:
        _append_cell(folder, "markdown", table)
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "'93%'" in violations[0], violations


@pytest.mark.parametrize(
    "block",
    [
        "# Next",
        "## Next",
        "- item",
        "* item",
        "+ item",
        "1. item",
        "10) item",
        "```",
        "~~~",
        "<div>",
        "</div>",
        "<div class='x'>",
        "<p>",
        "<table>",
        "<pre>",
        "<script>",
        "<style>",
        "<textarea>",
        "<!-- note -->",
        "<?php",
        "<!DOCTYPE html>",
        "<![CDATA[",
        "---",
        "***",
        "___",
        "- - -",
    ],
)
def test_a_line_that_opens_another_block_ends_the_table(block):
    rows, _ = _table_scan(f"a | b\n- | -\nx | 1\n{block}\naccuracy | 93%\n")
    assert rows == [["x", "1"]]


@pytest.mark.parametrize(
    "line",
    [
        "<span>note</span>",
        "<sup>",
        "<b>",
        "<em>note</em>",
        "<br>",
        '<a href="x">see</a>',
        "<code>x</code> and more",
        "<divider>",
        "<pretty>",
    ],
)
def test_an_inline_tag_line_does_not_end_the_table(line):
    """GFM ends a table only at an HTML block of type 1 to 6; an inline-tag line is a row."""
    rows, _ = _table_scan(f"a | b\n- | -\nx | 1\n{line}\naccuracy | 93%\n")
    assert rows == [["x", "1"], ["accuracy", "93%"]]


_WRAPPED_SENTENCE = (
    "| Metric | Value |\n| --- | --- |\n| run | a |\nOverall accuracy is\n93% on the set.\n"
)


@pytest.mark.parametrize("where", ["readme", "markdown"])
def test_a_sentence_that_wraps_under_a_table_is_read_as_one_paragraph(tmp_path, where):
    """A pipe-less line stays in the prose, joined with its neighbours, so the metric word and the
    figure of a wrapped sentence are still read together (a one-cell row each would split them)."""
    folder = _copy_recipe(tmp_path, "_template")
    if where == "readme":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + _WRAPPED_SENTENCE, "utf-8")
    else:
        _append_cell(folder, "markdown", _WRAPPED_SENTENCE)
    before = _prose_quotes(_copy_recipe(tmp_path / "plain", "_template"))
    new = [t for t in _prose_quotes(folder) if t not in before]
    assert [(kind, quote) for _, kind, quote in new] == [("rate", "93%")], new
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "'93%'" in violations[0], violations


def test_what_a_table_scan_quotes_is_the_row_text_not_the_prose_text():
    rows, prose = _table_scan(_WRAPPED_SENTENCE)
    assert rows == [["run", "a"]]
    assert _table_row_quantities(["accuracy", "93%"]) == [("rate", "93%")]
    assert [q for u in _markdown_units(prose) for q in _quoted_quantities(u)] == [("rate", "93%")]
    rows, prose = _table_scan(_PIPELESS_FILLER["inline-span"])
    assert rows == [["run", "a"], ["accuracy", "93%"]]
    assert [q for row in rows for q in _table_row_quantities(row)] == [("rate", "93%")]
    assert "<span>note</span>" in prose


def test_a_pipeless_line_at_another_blockquote_depth_ends_the_table():
    rows, _ = _table_scan("> a | b\n> - | -\n> x | 1\nplain\n> accuracy | 93%\n")
    assert rows == [["x", "1"]]
    rows, _ = _table_scan("> a | b\n> - | -\n> x | 1\n> > deeper\n> accuracy | 93%\n")
    assert rows == [["x", "1"]]


_LIST_TABLES = {
    "dash-four-space-body": "-   Results\n\n    | Metric | Value |\n    | --- | --- |\n    | accuracy | 93% |\n",
    "numbered": "10. Results\n\n    | Metric | Value |\n    | --- | --- |\n    | accuracy | 93% |\n",
    "nested": "- a\n  - b\n\n      | Metric | Value |\n      | --- | --- |\n      | accuracy | 93% |\n",
    "two-space": "- Results\n\n  | Metric | Value |\n  | --- | --- |\n  | accuracy | 93% |\n",
    "indented-without-pipes": "    Metric | Value\n    --- | ---\n    accuracy | 93%\n",
    "tab": "-\tResults\n\n\t| Metric | Value |\n\t| --- | --- |\n\t| accuracy | 93% |\n",
}


@pytest.mark.parametrize("where", ["readme", "markdown"])
@pytest.mark.parametrize("case", sorted(_LIST_TABLES))
def test_an_indented_table_is_read(tmp_path, case, where):
    """A table nested in a list item is a table however deep it is indented. A table indented
    four spaces outside a list is an indented code block in GFM and is read anyway: an extra flag
    is safe, a hidden claim is not."""
    folder = _copy_recipe(tmp_path, "_template")
    table = _LIST_TABLES[case]
    if where == "readme":
        readme = folder / "README.md"
        readme.write_text(readme.read_text("utf-8") + "\n" + table, "utf-8")
    else:
        _append_cell(folder, "markdown", table)
    violations = _unprinted_quantities(folder)
    assert len(violations) == 1 and "'93%'" in violations[0], violations


def test_a_delimiter_of_another_width_still_starts_a_table(tmp_path):
    """GFM does not make a table of a header and a delimiter with different cell counts, and
    shows the lines as paragraph text, where the figure is still readable. The guard does not
    compare the counts: it reads the rows below, and an extra flag is safe."""
    for text in (
        "| Metric | Value |\n| --- |\n| accuracy | 93% |\n",
        "| Metric |\n| --- | --- |\n| accuracy | 93% |\n",
        "Metric | Value\n--- | --- | ---\naccuracy | 93%\n",
    ):
        rows, _ = _table_scan(text)
        assert rows == [["accuracy", "93%"]], text
    folder = _copy_recipe(tmp_path, "_template")
    _append_cell(folder, "markdown", "| Metric | Value |\n| --- |\n| accuracy | 93% |\n")
    assert len(_unprinted_quantities(folder)) == 1


def test_a_percentage_glued_to_an_identifier_is_not_a_quoted_quantity():
    """#542: the prose side reads the same left boundary, so ``sku93%`` is not a quote of 93%
    while a spaced ``93%`` is."""
    assert _quoted_quantities("It reaches sku93% accuracy.") == []
    assert _quoted_quantities("It reaches 93% accuracy.") == [("rate", "93%")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("latency 180ms", [Decimal(180)]),
        ("p50 latency 180ms", [Decimal(180)]),
        ("rows=1,250 x1", [Decimal(1250)]),
        ("sha e4b7a93 then 12,3456 .5", [Decimal(12345), Decimal(6), Decimal(5)]),
        ("run_1.5 x1,250 QWx1.93Q F1 0.93", [Decimal("0.93")]),
        ("a\u00e993 id-42", [Decimal(93), Decimal(42)]),
        ("accuracy,93 0.5,93 x,1.93", [Decimal(93), Decimal("0.5"), Decimal(93), Decimal("1.93")]),
        ("t01,0.93 F1,0.93 top5,93", [Decimal("0.93"), Decimal("0.93"), Decimal(93)]),
        ("sku1,093 x1,250.5 t01,930", []),
        ("v1.2.93 sku1.2.3.4 x1,250.5.6", []),
        ("t01,1234 x1,2500", [Decimal(1234), Decimal(2500)]),
    ],
)
def test_the_tokenizer_keeps_trailing_units_and_a_punctuation_separated_run(text, expected):
    """#542: only the left boundary matters, so ``180ms`` stays; a comma group and a number after
    a dot are read as before."""
    assert _decimals(text) == expected


@pytest.mark.parametrize(
    "mantissa_and_exponent",
    [
        "1.0416666666666667e-05",
        "0.8347222222222222e+00",
        "1.2345678901234567e-05",
        "1.2345678901234567e+16",
        "12345678901234567e+3",
    ],
)
def test_a_float_in_scientific_notation_keeps_its_mantissa(tmp_path, mantissa_and_exponent):
    """A float printed with 16 or more mantissa digits and an exponent is a quantity: the
    mantissa digits and the ``e`` after them look like a hex run, but ``_HASH_LIKE`` leaves
    them. A prose quote of the printed value stays backed, and ``name.<digest>`` (a dot before a
    real digest) is still replaced."""
    assert (
        _without_hash_like_tokens(f"p = {mantissa_and_exponent}") == f"p = {mantissa_and_exponent}"
    )
    mantissa = mantissa_and_exponent.split("e")[0]
    if "." not in mantissa:
        return
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(folder, "code", f"validation error rate: {mantissa_and_exponent}", cell_id="sci")
    _append_cell(
        folder,
        "markdown",
        f"The error rate is {mantissa} (a pipeline check, not a Jev result).",
        cell_id="genuine",
    )
    assert [m for m in _unprinted_quantities(folder) if "genuine" in m] == []


def test_a_pure_digit_dashed_id_is_not_a_uuid_and_stays_in_the_pool():
    """The UUID branch needs a letter and a digit, like the hex branch: a pure-digit 8-4-4-4-12
    id (a date-and-sequence batch id) is a run of numbers and stays."""
    batch = "batch 20261114-0236-1000-0000-000000000042"
    assert _without_hash_like_tokens(batch) == batch
    assert _without_hash_like_tokens("run id: deadbeef-cafe-4a93-bead-facefacefeed") == (
        "run id: <hash>"
    )
    assert _without_hash_like_tokens("id deadbeef-cafe-dead-beef-facefacefeed") == (
        "id deadbeef-cafe-dead-beef-facefacefeed"
    )


@pytest.mark.parametrize("where", ["output", "tests"])
def test_a_plain_number_on_an_audit_line_does_not_back_a_figure(tmp_path, where):
    """The line-prefix rule still has a job once hash-like tokens are replaced: the ledger's other
    fields, here a plain, non-hash number, stay out of the pool. Removing ``_without_audit_lines``
    from ``_pool_text`` makes this fail, on either pool source."""
    line = AUDIT_PREFIX + '{"requests":2,"spend_ratio":0.5123}'
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    if where == "output":
        _append_cell(folder, "code", line, cell_id="ledger")
    else:
        (folder / "tests").mkdir(exist_ok=True)
        (folder / "tests" / "test_ledger.py").write_text(
            'EXPECTED = """\n' + line + '\n"""\n', "utf-8"
        )
    _append_cell(folder, "markdown", "The error rate is 0.5123.", cell_id="fabricated")
    unbacked = _unprinted_quantities(folder)
    assert any("0.5123" in message for message in unbacked), unbacked


# #380: committed output whose number-ending segment carries no trailing newline. The last shape is
# a quoted *fraction* backed through a printed percentage (a quoted percentage needs a printed percentage
# or fraction, see #536 below). Each shape is
# (the segment that ends with the number, the segment that opens with the unit, a prose sentence
# that quotes the fused quantity as a claim about Jev, the unit pattern that binds them, the quote
# the guard reports for that sentence). The four unit patterns bind a number to its unit with
# ``\s?`` (``_PERCENT``, with ``\s*`` since #542, the same way), so before #380 the one newline the
# output joins put
# between the two segments fused them and backed the sentence.
_UNTERMINATED_SHAPES = {
    "latency": (
        "median latency 180",
        "ms over the sample",
        "Jev answers with a median latency of 180 ms.",
        _LATENCY_MS,
        "'180 ms'",
    ),
    "throughput": (
        "the replay handled 40",
        "requests per second offline",
        "Jev handles 40 requests per second.",
        _THROUGHPUT,
        "'40 requests per second'",
    ),
    "seconds": (
        "replay rows: 12",
        "seconds is the offline wall time",
        "A live Jev call takes 12 seconds of latency.",
        _SECONDS,
        "'12 seconds'",
    ),
    "price": (
        "budget line $",
        "0.25 per call, from the fixture invoice",
        "Each Jev call costs $0.25 per call.",
        re.compile(_PRICE_AMOUNT, re.IGNORECASE),
        "'$0.25 per call'",
    ),
    "fraction-via-percent": (
        "rows checked: 93",
        "% of the fixture file was read",
        # A printed percentage also backs its fraction, so the fused "93\n%" backed "0.93".
        "Jev reaches an accuracy of 0.93 on this task.",
        _PERCENT,
        "'0.93'",
    ),
}


def _append_unterminated_output(
    folder: Path, segments: list[str], cell_id: str, outputs: list[dict] | None = None
) -> None:
    """A code cell whose committed outputs are ``segments`` exactly as given: one stdout stream
    each, with no trailing newline added (unlike ``_append_cell``), the shape a cell that ends in
    ``print(..., end="")`` or ``sys.stdout.write(...)`` commits. ``outputs`` replaces them with
    explicit nbformat output dicts."""
    _append_cell(
        folder,
        "code",
        "",
        cell_id=cell_id,
        terminated=False,
        segments=segments,
        outputs=outputs,
    )


def _stdout(text: str) -> dict:
    return {"name": "stdout", "output_type": "stream", "text": [text]}


def _stderr(text: str) -> dict:
    return {"name": "stderr", "output_type": "stream", "text": [text]}


def _execute_result(text: str) -> dict:
    return {
        "output_type": "execute_result",
        "execution_count": 1,
        "metadata": {},
        "data": {"text/plain": [text]},
    }


def _display_data(text: str) -> dict:
    return {"output_type": "display_data", "metadata": {}, "data": {"text/plain": [text]}}


# Shapes for one cell's second output after a stdout stream: a displayed value, a stderr stream,
# display_data (what Jupyter really saves) and a second stdout stream. The guard reads each
# committed output part as its own line, the same way ``_committed_output_lines`` does for every
# other output check, so all checks agree on what one printed line is; that is why stdout+stdout
# stays a fusion case. ``tools/execute_notebook.py`` runs with ``coalesce_streams=True``, which
# merges consecutive same-name streams before it commits, so a committed notebook does not hold
# that shape (the pools are identical over all 52 recipe folders).
_SECOND_OUTPUT = {
    "execute-result": _execute_result,
    "stderr": _stderr,
    "display-data": _display_data,
    "stdout": _stdout,
}


@pytest.mark.parametrize("where", ["across two cells", *sorted(_SECOND_OUTPUT)])
@pytest.mark.parametrize("shape", sorted(_UNTERMINATED_SHAPES))
def test_an_unterminated_output_segment_does_not_fuse_a_number_to_the_next_unit(
    tmp_path, shape, where
):
    """#380. The number ends one committed output segment with no trailing newline and its unit
    opens the next, either in the next cell or in the same cell's next output part. Before the
    fix the fused text was scanned as one and backed the fabricated sentence; the first assertion
    shows the case reaches that fusion (the joined output really does hold ``number\\nunit`` and
    the unit pattern really does match across it), the second that the guard now catches the
    sentence anyway."""
    ends_with_number, begins_with_unit, sentence, pattern, quote = _UNTERMINATED_SHAPES[shape]
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    if where == "across two cells":
        _append_unterminated_output(folder, [ends_with_number], "ends-with-number")
        _append_unterminated_output(folder, [begins_with_unit + "\n"], "begins-with-unit")
    else:
        _append_unterminated_output(
            folder,
            [],
            "split",
            outputs=[_stdout(ends_with_number), _SECOND_OUTPUT[where](begins_with_unit + "\n")],
        )
    fused = _scanned_output(folder)
    assert any("\n" in m.group(0) for m in pattern.finditer(fused)), fused
    _append_cell(folder, "markdown", sentence, cell_id="fabricated-quantity")
    unbacked = _unprinted_quantities(folder)
    assert any("fabricated-quantity" in m and quote in m for m in unbacked), unbacked


def test_a_quoted_percentage_is_not_backed_by_a_bare_number_on_another_line(tmp_path):
    """#536 closes the exception #380 left: a quoted percentage is not backed by a bare printed
    number, so ``93%`` quoted is not backed by a ``93`` printed on one line with its ``%`` on
    another. Pre-existing before #536, which removed it."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_unterminated_output(folder, ["rows checked: 93"], "number")
    _append_unterminated_output(folder, ["% of the fixture file was read\n"], "unit")
    sentence = "Jev reaches an accuracy of 93% on this task."
    assert ("rate", "93%") in _quoted_quantities(sentence), _quoted_quantities(sentence)
    _append_cell(folder, "markdown", sentence, cell_id="q")
    assert [m for m in _unprinted_quantities(folder) if "'93%'" in m]


# #536: (committed output or recipe test text, quoted sentence, is it backed). Each unbacked row
# is a number that backed the quote before #536 (or, for a unit row, that the ruling excludes).
_PERCENTAGE_BACKING = {
    "issue-count": ("rows checked: 93", "Jev reaches an accuracy of 93%.", False),
    "rounded-count": ("rows checked: 92.6", "Jev reaches an accuracy of 93%.", False),
    "seconds": ("latency: 92.6 seconds", "Jev reaches an accuracy of 93%.", False),
    "fractional-seconds": ("latency: 0.926 seconds", "Jev reaches an accuracy of 93%.", False),
    "fractional-ms": ("latency: 0.926 ms", "Jev reaches an accuracy of 93%.", False),
    "price": ("cost: $0.926 per call", "Jev reaches an accuracy of 93%.", False),
    "per-second": ("rate: 0.926/s", "Jev reaches an accuracy of 93%.", False),
    "tiny-percentage": ("error rate 0.93%", "Jev reaches an accuracy of 93%.", False),
    "tiny-percentage-spaced": ("error rate 0.93 %", "Jev reaches an accuracy of 93%.", False),
    "per-second-fraction": ("accuracy 0.93/s", "Jev reaches an accuracy of 93%.", False),
    # The leftover percentage-pattern gaps of the #689 reviews (#542). A number that is a
    # percentage or carries a rate unit is not a fraction, however the sign or unit is written.
    "percent-word": ("error rate 0.93 percent", "Jev reaches an accuracy of 93%.", False),
    "pct-word": ("error rate 0.93 pct", "Jev reaches an accuracy of 93%.", False),
    "two-spaces-before-percent": ("error rate 0.93  %", "Jev reaches an accuracy of 93%.", False),
    "full-width-percent": ("error rate 0.93\uff05", "Jev reaches an accuracy of 93%.", False),
    "per-mille": ("error rate 0.93\u2030", "Jev reaches an accuracy of 93%.", False),
    "per-sample": ("rate: 0.926/sample", "Jev reaches an accuracy of 93%.", False),
    "per-day": ("rate: 0.926/day", "Jev reaches an accuracy of 93%.", False),
    "per-query": ("rate: 0.926/query", "Jev reaches an accuracy of 93%.", False),
    "per-item": ("rate: 0.926/item", "Jev reaches an accuracy of 93%.", False),
    "per-tok": ("rate: 0.926/tok", "Jev reaches an accuracy of 93%.", False),
    "per-1k": ("rate: 0.926/1k", "Jev reaches an accuracy of 93%.", False),
    "per-sec-squared": ("accel: 0.926/sec\u00b2", "Jev reaches an accuracy of 93%.", False),
    # Kills the two surviving ``_RATE_DENOMINATOR`` mutants: without its closing boundary ``/step``
    # starts the unit ``/s`` and the backed row fails; without ``re.IGNORECASE`` ``/S`` is no unit
    # and the unbacked row fails.
    "slash-step-is-no-rate-unit": ("accuracy 0.93/step", "Jev reaches an accuracy of 93%.", True),
    "per-capital-s": ("accuracy 0.93/S", "Jev reaches an accuracy of 93%.", False),
    "per-cent-words": ("error rate 0.93 per cent", "Jev reaches an accuracy of 93%.", False),
    # Only a token glued to a letter is refused, never a figure after a comma (#542 review): a CSV
    # row without spaces still prints a real percentage.
    "csv-word-comma-percent": ("accuracy,93%", "Jev reaches an accuracy of 93%.", True),
    "csv-row-percent": ("jev,93.0%", "Jev reaches an accuracy of 93%.", True),
    "csv-number-comma-percent": ("0.5,93%", "Jev reaches an accuracy of 93%.", True),
    # A cell after a glued id is a figure, not the id's thousands tail (#542 review round 3).
    "id-comma-fraction": ("t01,0.93", "Jev reaches an accuracy of 93%.", True),
    "id-comma-percent": ("t01,93%", "Jev reaches an accuracy of 93%.", True),
    "id-comma-long-fraction": ("t01,0.9474", "Jev reaches an accuracy of 95%.", True),
    "metric-id-comma-fraction": ("F1,0.93", "Jev reaches an accuracy of 93%.", True),
    "digit-id-comma-percent": ("top5,93%", "Jev reaches an accuracy of 93%.", True),
    "r2-comma-fraction": ("R2,0.93", "Jev reaches an accuracy of 93%.", True),
    # Pins ``_PERCENT``'s ``\s*``: a printed percentage after two spaces is still a percentage.
    "printed-percentage-two-spaces": ("accuracy 93  %", "Jev reaches an accuracy of 93%.", True),
    "slash-pair": ("precision/recall: 0.93/0.91", "Jev reaches a precision of 93%.", True),
    "slash-pair-second": ("precision/recall: 0.91/0.93", "Jev reaches a recall of 93%.", True),
    "spaced-slash-pair": (
        "accuracy (val / test): 0.93 / 0.95",
        "Jev reaches an accuracy of 93%.",
        True,
    ),
    "bare-one": ("N: 1", "Jev reaches an accuracy of 100%.", False),
    "unit-rate-complement": ("accuracy timing: 0.074 seconds", "Jev has a risk of 93%.", False),
    "percentage": ("accuracy 93%", "Jev reaches an accuracy of 93%.", True),
    "rounded-percentage": ("accuracy 92.6%", "Jev reaches an accuracy of 93%.", True),
    "fraction": ("accuracy 0.93", "Jev reaches an accuracy of 93%.", True),
    "rounded-fraction": ("accuracy 0.926", "Jev reaches an accuracy of 93%.", True),
    "explicit-one": ("accuracy 1.0000", "Jev reaches an accuracy of 100%.", True),
    "unit-and-fraction": ("latency 0.926 seconds; accuracy 0.93", "an accuracy of 93%", True),
    "percentage-complement": ("accuracy 7.4%", "Jev has a risk of 93%.", True),
    "fraction-complement": ("accuracy 0.074", "Jev has a risk of 93%.", True),
}


@pytest.mark.parametrize("source", ["output", "tests"])
@pytest.mark.parametrize("case", sorted(_PERCENTAGE_BACKING))
def test_a_quoted_percentage_needs_a_printed_percentage_or_fraction(tmp_path, case, source):
    """#536: only a printed percentage or fraction backs a quoted percentage, from committed
    output or from the recipe's tests; a count or a number with another unit does not."""
    printed, sentence, backed = _PERCENTAGE_BACKING[case]
    if source == "tests" and case.endswith("complement"):
        pytest.skip("a complement is read from committed output lines only")
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_cell(folder, "markdown", sentence, cell_id="percentage-quote")
    assert _unprinted_quantities(folder), "the quote must start unbacked"
    if source == "output":
        _append_cell(folder, "code", printed, cell_id="percentage-evidence")
    else:
        (folder / "tests").mkdir(exist_ok=True)
        (folder / "tests" / "test_evidence.py").write_text(f"VALUE = {printed!r}\n", "utf-8")
    assert bool(_unprinted_quantities(folder)) is not backed, _unprinted_quantities(folder)


def test_a_digit_split_across_unterminated_cells_does_not_back_the_joined_number(tmp_path):
    """Review finding on #479: ``rows: 9`` then ``3 ms``, both unterminated, are two output lines,
    so the 9 and the 3 never fuse into the ``93 ms`` the sentence quotes."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    _append_unterminated_output(folder, ["rows: 9"], "digit-head")
    _append_unterminated_output(folder, ["3 ms"], "digit-tail")
    _append_cell(folder, "markdown", "Jev answers with a median latency of 93 ms.", cell_id="q")
    unbacked = _unprinted_quantities(folder)
    assert any("q" in m and "'93 ms'" in m for m in unbacked), unbacked


def test_append_cell_refuses_segments_and_outputs_together(tmp_path):
    """``outputs`` replaces ``segments``; passing both used to drop ``segments`` silently."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    with pytest.raises(ValueError, match="not both"):
        _append_cell(folder, "code", "", segments=["a"], outputs=[_stdout("b")])


@pytest.mark.parametrize("terminated", [True, False], ids=["terminated", "unterminated"])
@pytest.mark.parametrize(
    "separator", ["", " ", "\t", "\u00a0"], ids=["none", "space", "tab", "nonbreaking-space"]
)
@pytest.mark.parametrize("shape", sorted(_UNTERMINATED_SHAPES))
def test_a_number_and_its_unit_printed_on_one_line_is_still_backed(
    tmp_path, shape, separator, terminated
):
    """The other direction of #380: each metric, price or time quantity is backed by its own
    printed line with any supported horizontal separator, with or without a trailing newline.
    Each case starts unbacked, so another shape's output cannot mask a missing unit match."""
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    number, unit, sentence, _, quote = _UNTERMINATED_SHAPES[shape]
    _append_cell(folder, "markdown", sentence, cell_id=f"backed-{shape}")
    unbacked = _unprinted_quantities(folder)
    assert any("backed-" in m and quote in m for m in unbacked), unbacked
    joined = separator.join((number, unit))
    _append_cell(folder, "code", joined, cell_id="printed", terminated=terminated)
    assert _scanned_output(folder).endswith(joined + ("\n" if terminated else ""))
    assert [m for m in _unprinted_quantities(folder) if "backed-" in m] == []


def test_the_audit_line_pinned_in_the_recipes_own_tests_does_not_back_a_fabrication(tmp_path):
    """#376's second door: ``_printed_numbers`` also pools ``_decimals()`` over the recipe's own
    ``tests/*.py`` text (CONTRIBUTING.md section 6's "a test re-derives it" route), and that arm
    must be exempted from the audit line's hex the same way the committed-output arm is. An
    audited recipe pinning the ledger a notebook cell prints as its own expected value, in a
    triple-quoted ``EXPECTED`` assignment with the audit line reproduced verbatim on its own
    physical line (exactly as a cell's committed stdout carries it) in ``tests/test_ledger.py``,
    must not reopen the door the committed-output exclusion closes. The rule the match follows is
    ``line.startswith(AUDIT_PREFIX)``: only a line whose very first character begins the prefix is
    excluded, on either arm, so a one-line assignment whose quote character precedes the prefix
    (``EXPECTED = "<ledger line>"``) or an indented occurrence (``    assert "<ledger line>" in
    out``) is a different shape this test does not exercise and this match does not reach (#378
    measures both)."""
    audit_line = _real_audit_line()
    assert Decimal(94) in _decimals(audit_line), (
        "the synthetic audit line no longer reads a literal '94' this test pins -- "
        "its states must be changed so the defect it guards against is still exercised"
    )
    folder = _synthetic_recipe(tmp_path, ["x = 1\n"])
    (folder / "tests").mkdir(exist_ok=True)
    (folder / "tests" / "test_ledger.py").write_text(
        'EXPECTED = """\n' + audit_line + '\n"""\n', "utf-8"
    )
    _append_cell(folder, "markdown", "The accuracy is 94%.", cell_id="fabricated")
    # Since #536 the percent quote alone no longer shows audit exclusion (a bare 94 cannot back it
    # anyway); the ordinary decimal 94.0 can, so it pins the exclusion on its own.
    _append_cell(folder, "markdown", "The accuracy is 94.0.", cell_id="fabricated-decimal")
    unbacked = _unprinted_quantities(folder)
    assert any("fabricated-decimal" in m and "94.0" in m for m in unbacked), unbacked
    assert any("94" in message for message in unbacked), unbacked


_TWO_DATES = ("2026-03-02", "2026-03-09")


def test_a_recording_over_several_dates_states_the_first_and_last_in_the_header_and_all_in_captured(
    tmp_path,
):
    """``run_header`` says "between FIRST and LAST" and the measured cell lists every date: both
    are exact, in both directions."""
    folder = _copy_recipe(tmp_path, "_template")
    _make_recorded(folder, _TWO_DATES)
    assert _fixture_provenance(folder)[2] == list(_TWO_DATES)
    assert _all_clear(folder), _violations(folder)
    _edit_streams(folder, "Captured: 2026-03-02, 2026-03-09", "Captured: 2026-03-02")
    assert any("state capture dates" in v for v in _provenance_violations(folder))
    _edit_streams(folder, "Captured: 2026-03-02", "Captured: 2026-03-02, 2026-03-09, 2026-04-01")
    assert any("state capture dates" in v for v in _provenance_violations(folder))
    _edit_streams(
        folder, "Captured: 2026-03-02, 2026-03-09, 2026-04-01", "Captured: 2026-03-02, 2026-03-09"
    )
    _edit_streams(folder, "between 2026-03-02 and 2026-03-09", "on 2026-03-02")
    assert any("the header says" in v for v in _provenance_violations(folder))


_RECORDED_README_FAILS = {
    "an-extra-capture-date": ("a model captured on 2026-12-25 too", "2026-12-25"),
    "an-extra-model": ("compared with jev-9.9.9 elsewhere", "jev-9.9.9"),
}


@pytest.mark.parametrize("case", sorted(_RECORDED_README_FAILS))
def test_a_recorded_readme_may_not_state_a_date_or_a_model_the_fixtures_do_not_carry(
    tmp_path, case
):
    sentence, needle = _RECORDED_README_FAILS[case]
    folder = _copy_recipe(tmp_path, "_template")
    _make_recorded(folder)
    assert _readme_provenance_violations(folder) == []
    readme = folder / "README.md"
    readme.write_text(readme.read_text("utf-8") + "\nThe run was " + sentence + ".\n", "utf-8")
    assert any(needle in v for v in _readme_provenance_violations(folder))


def test_a_recorded_answer_with_a_malformed_date_is_a_fixture_problem(tmp_path):
    """The date pattern is load-bearing: a recorded answer dated "yesterday" is not a capture date."""
    folder = _copy_recipe(tmp_path, "_template")
    for n, bad in enumerate(("yesterday", "2026-3-2", "2026-03-02T10:00:00Z", "")):
        folder_i = _copy_recipe(tmp_path / f"case{n}", "_template")
        _rewrite_responses(
            folder_i,
            lambda i, a, bad=bad: a.update(
                provenance={"source": "recorded", "model": _RECORDED_MODEL, "date": bad}
            ),
        )
        mode, _, _, problems = _fixture_provenance(folder_i)
        assert mode is None and any("no capture date" in p for p in problems), bad
    assert _fixture_provenance(folder)[0] == "synthetic"


@pytest.mark.parametrize(
    "separator", ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
)
def test_cell_id_citations_preserve_non_line_separators(separator):
    text = f"Intro{separator}~~~\n`python-rule`\n~~~"
    assert _cell_id_citations(text, {"python-rule"}, "prose") == [
        "prose: `python-rule` is a cell id, which only the .ipynb JSON shows"
    ]
    fenced = f"~~~\ncontent{separator}~~~\n`python-rule`\n~~~"
    assert _cell_id_citations(fenced, {"python-rule"}, "prose") == []


@pytest.mark.parametrize("ending", ["\n", "\r", "\r\n"])
def test_cell_id_citations_recognize_real_fence_line_endings(ending):
    text = ending.join(["Intro", "~~~", "`python-rule`", "~~~", "`python-rule`"])
    assert _cell_id_citations(text, {"python-rule"}, "prose") == [
        "prose: `python-rule` is a cell id, which only the .ipynb JSON shows"
    ]
    unclosed = ending.join(["Intro", "~~~", "`python-rule`"])
    assert _cell_id_citations(unclosed, {"python-rule"}, "prose") == []


@pytest.mark.parametrize(
    "suffix,expected_count",
    [
        ("\v", 0),
        ("\f", 0),
        ("\x85", 0),
        ("\u2028", 0),
        ("\u2029", 0),
        ("\xa0", 0),
        ("\u2003", 0),
        (" ", 1),
        ("\t", 1),
    ],
)
def test_cell_id_citations_require_ascii_fence_closing_whitespace(suffix, expected_count):
    text = f"~~~\n~~~{suffix}\n`python-rule`"
    hits = _cell_id_citations(text, {"python-rule"}, "prose")
    assert len(hits) == expected_count, hits


@pytest.mark.parametrize(
    "case,text,expected_count",
    [
        ("html-comment-followed-by-prose", "<!--\n~~~\n-->\n\nSee `python-rule`.", 1),
        ("list-closer-followed-by-prose", "- ~~~\n  example\n  ~~~\n\nRead `python-rule`.", 1),
        ("list-contained-id", "- ~~~\n  `python-rule`\n  ~~~", 0),
        ("ordered-list-contained-id", "1. ```text\n   `python-rule`\n   ```", 0),
        ("quote-contained-id", "> ~~~\n> `python-rule`\n> ~~~", 0),
        ("nested-list-quote", "> - ~~~\n>   `python-rule`\n>   ~~~\n\nRead `python-rule`.", 1),
        (
            "unclosed-list-fence-ends-at-container",
            "- ~~~\n  `python-rule`\n\nRead `python-rule`.",
            1,
        ),
        (
            "unclosed-quote-fence-ends-at-container",
            "> ~~~\n> `python-rule`\n\nRead `python-rule`.",
            1,
        ),
        ("unclosed-document-fence", "~~~\n`python-rule`", 0),
        ("raw-html-block-fence-lookalike", "<div>\n~~~\n</div>\n\nRead `python-rule`.", 1),
        ("raw-pre-block-fence-lookalike", "<pre>\n~~~\n</pre>\n\nRead `python-rule`.", 1),
        ("comment-in-list", "- <!--\n  ~~~\n  -->\n\nRead `python-rule`.", 1),
        (
            "genuine-fence-contains-comment-marker",
            "~~~\n<!--\n`python-rule`\n~~~\n\nRead `python-rule`.",
            1,
        ),
        (
            "html-comment-followed-by-real-fence",
            "<!--\n~~~\n-->\n\n~~~\n`python-rule`\n~~~\nRead `python-rule`.",
            1,
        ),
    ],
)
def test_cell_id_citations_respect_commonmark_block_context(case, text, expected_count):
    hits = _cell_id_citations(text, {"python-rule"}, "prose")
    assert len(hits) == expected_count, (case, hits)
    assert all("`python-rule`" in hit for hit in hits)


def test_cell_id_citations_explicitly_select_context_on_their_private_scope_module():
    assert _cell_id_scope.COMMONMARK_FENCE_CONTEXT is True
    assert without_code_fences is _cell_id_scope.without_code_fences


def test_cell_id_citations_conservatively_retain_text_beyond_parser_nesting_limit():
    text = "> " * 25 + "~~~\n" + "> " * 25 + "`python-rule`"
    assert len(_cell_id_citations(text, {"python-rule"}, "prose")) == 1


# --------------------------------------------------------------------------------------------
# Fixture arithmetic: a bounded AST policy, not whole-program numeric type inference.
# --------------------------------------------------------------------------------------------


def _fixture_builtin_aliases(tree: ast.Module) -> dict[str, str]:
    """Resolve builtin spellings/imports conservatively; any other binding disables credit.

    Binding discovery spans the whole file, including nested scopes. This may deny an integer
    or rounding exemption unnecessarily, but a locally shadowed ``len``/``round`` cannot grant
    one. Assignment aliases, getattr, star imports and other modules are not resolved.
    """
    names = {name: name for name in ("sum", "round", "len", "int", "bool", "range", "pow")}
    bindings: dict[str, list[str | None]] = {}
    type_parameter_nodes = tuple(
        getattr(ast, name)
        for name in ("TypeVar", "ParamSpec", "TypeVarTuple")
        if hasattr(ast, name)
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bindings.setdefault(node.id, []).append(None)
        elif isinstance(node, ast.arg):
            bindings.setdefault(node.arg, []).append(None)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.setdefault(node.name, []).append(None)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar, ast.ExceptHandler)):
            if node.name is not None:
                bindings.setdefault(node.name, []).append(None)
        elif isinstance(node, ast.MatchMapping):
            if node.rest is not None:
                bindings.setdefault(node.rest, []).append(None)
        elif isinstance(node, type_parameter_nodes):
            bindings.setdefault(node.name, []).append(None)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                kind = "builtins" if alias.name == "builtins" else None
                bindings.setdefault(alias.asname or alias.name.split(".")[0], []).append(kind)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                kind = (
                    alias.name
                    if node.level == 0 and node.module == "builtins" and alias.name in names
                    else None
                )
                bindings.setdefault(alias.asname or alias.name, []).append(kind)
    for name, kinds in bindings.items():
        names.pop(name, None)
        if len(kinds) == 1 and kinds[0] is not None:
            names[name] = kinds[0]
    return names


def _fixture_builtin(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and aliases.get(node.value.id) == "builtins"
    ):
        return node.attr
    return None


def _fixture_integer_expr(node: ast.AST, aliases: dict[str, str]) -> bool:
    """Integer literals, builtin integer results and integer-only arithmetic; no name inference."""
    if isinstance(node, ast.Constant):
        return type(node.value) in (int, bool)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Invert)):
        return _fixture_integer_expr(node.operand, aliases)
    if isinstance(node, ast.Call):
        return _fixture_builtin(node.func, aliases) in {"len", "int", "bool"}
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Pow):
            # int ** negative-int returns float; a name's sign is not inferred.
            if not (
                isinstance(node.right, ast.Constant)
                and type(node.right.value) is int
                and node.right.value >= 0
            ):
                return False
        elif not isinstance(
            node.op,
            (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.BitAnd, ast.BitOr, ast.BitXor),
        ):
            return False
        return _fixture_integer_expr(node.left, aliases) and _fixture_integer_expr(
            node.right, aliases
        )
    return False


def _fixture_integer_iterable(node: ast.AST, aliases: dict[str, str]) -> bool:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_fixture_integer_expr(item, aliases) for item in node.elts)
    if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        return _fixture_integer_expr(node.elt, aliases)
    return (
        isinstance(node, ast.Call)
        and _fixture_builtin(node.func, aliases) == "range"
        and not node.keywords
        and 1 <= len(node.args) <= 3
        and all(_fixture_integer_expr(arg, aliases) for arg in node.args)
    )


def _fixture_integer_sum(node: ast.Call, aliases: dict[str, str]) -> bool:
    if not 1 <= len(node.args) <= 2 or not _fixture_integer_iterable(node.args[0], aliases):
        return False
    starts = node.args[1:] + [kw.value for kw in node.keywords if kw.arg == "start"]
    return (
        len(starts) <= 1
        and all(kw.arg == "start" for kw in node.keywords)
        and all(_fixture_integer_expr(start, aliases) for start in starts)
    )


def _fixture_directly_rounded(
    node: ast.AST, parents: dict[ast.AST, ast.AST], aliases: dict[str, str]
) -> bool:
    """Only arithmetic between sum and a builtin round(expr, literal 0..10) is credited.

    This is an explicit syntactic concession for existing rounded generators, not proof that
    rounding any magnitude removes an ulp difference. No credit through another function,
    a binding, round(..., 100), a shadowed builtin or a round call in a sibling expression.
    """
    while node in parents:
        parent = parents[node]
        if isinstance(parent, (ast.BinOp, ast.UnaryOp)):
            node = parent
            continue
        return (
            isinstance(parent, ast.Call)
            and _fixture_builtin(parent.func, aliases) == "round"
            and not parent.keywords
            and len(parent.args) == 2
            and parent.args[0] is node
            and isinstance(parent.args[1], ast.Constant)
            and type(parent.args[1].value) is int
            and 0 <= parent.args[1].value <= 10
        )
    return False


def _fixture_literal_numeric_kind(node: ast.AST) -> str | None:
    """Recognize int/float literal arithmetic only; names, annotations and calls stay unknown."""
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return type(node.value).__name__
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _fixture_literal_numeric_kind(node.operand)
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
    ):
        left = _fixture_literal_numeric_kind(node.left)
        right = _fixture_literal_numeric_kind(node.right)
        if left is not None and right is not None:
            return "float" if "float" in (left, right) or isinstance(node.op, ast.Div) else "int"
    return None


def _fixture_arithmetic_violations(source: str) -> list[str]:
    """Check every expression, including unused functions, without importing the builder.

    Sum is denied unless its iterable AND start are mechanically integer-producing, or the
    result is directly rounded (defined above). Unknown collections fail conservatively;
    annotations never certify them. Powers are flagged only with literal-arithmetic float
    evidence in either operand, for ** and builtin pow. This deliberately does not infer types
    through names, attributes, imports of numeric libraries, annotations or function returns.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"line {exc.lineno}: cannot parse build_fixtures.py: {exc.msg}"]
    aliases = _fixture_builtin_aliases(tree)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    problems = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and _fixture_builtin(node.func, aliases) == "sum"
            and not _fixture_integer_sum(node, aliases)
            and not _fixture_directly_rounded(node, parents, aliases)
        ):
            problems.append(
                f"line {node.lineno}: sum() requires a left-to-right accumulation loop unless "
                "the iterable/start use recognized integer syntax (integer/bool literals, "
                "builtin len/int/bool calls, integer-only arithmetic; literal collections, "
                "comprehensions or range) or the result is directly rounded by builtin "
                "round(expr, literal 0..10); unknown types are not certified"
            )
        operands = []
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            operands = [node.left, node.right]
        elif isinstance(node, ast.Call) and _fixture_builtin(node.func, aliases) == "pow":
            operands = node.args[:2] + [
                keyword.value for keyword in node.keywords if keyword.arg in {"base", "exp"}
            ]
        if any(_fixture_literal_numeric_kind(operand) == "float" for operand in operands):
            problems.append(
                f"line {node.lineno}: float power with literal-arithmetic evidence requires "
                "repeated multiplication; **/builtin pow may depend on platform libm"
            )
    return sorted(problems)


@pytest.mark.parametrize(
    "builder", sorted(RECIPES_DIR.glob("*/build_fixtures.py")), ids=lambda p: p.parent.name
)
def test_fixture_arithmetic_uses_deterministic_operations(builder):
    """All builders, including unpublished recipes and _template; no legacy exemptions."""
    problems = _fixture_arithmetic_violations(builder.read_text(encoding="utf-8"))
    assert not problems, (
        f"{builder.relative_to(REPO)}: fixture arithmetic must be deterministic across CI "
        "interpreters (docs/fixtures.md#floats-in-a-generator):\n  " + "\n  ".join(problems)
    )


@pytest.mark.parametrize(
    "source",
    [
        "result = sum([1.0, .35, .1225, .042875])",
        "def dist(**given: float):\n    return 1.0 - sum(given.values())",
        "result = sum(probabilities)",
        "result = sum([1, 2], 0.0)",
        "result = sum([1, 2], start=.5)",
        "result = sum([1 / 2, 3 / 4])",
        "result = sum([2 ** -1, 3])",
        "result = sum(x for x in values)",
        "result = sum(float(x) for x in values)",
        "result = sum(*args)",
        "result = round(sum(values), 100)",
        "result = round(sum(values), places)",
        "result = round(transform(sum(values)), 2)",
        "result = round(other, 2) + sum(values)",
        "def round(value, digits):\n    return value\nresult = round(sum(values), 2)",
        "def len(value):\n    return .5\nresult = sum(len(x) for x in items)",
        "def f(int):\n    return sum(int(x) for x in values)",
        "import builtins as b\nresult = b.sum(values)",
        "from builtins import sum as total\nresult = total(values)",
        "def unused():\n    return sum([1.0, 2.0])",
    ],
)
def test_fixture_arithmetic_rejects_float_and_uncertified_sums(source):
    problems = _fixture_arithmetic_violations(source)
    assert len(problems) == 1
    assert "sum() requires a left-to-right accumulation loop" in problems[0]
    assert "recognized integer syntax" in problems[0]
    assert "unknown types are not certified" in problems[0]


@pytest.mark.parametrize(
    "source",
    [
        "result = sum([1, 2, -3])",
        "result = sum((1, 2), start=3)",
        "result = sum({1, 2}, -3)",
        "result = sum(range(3))",
        "result = sum(len(r['passages']) for r in ROWS)",
        "result = sum([int(x) + bool(x) for x in values])",
        "result = sum([2 ** 3, 6 // 2, 3 * 4, 7 % 2])",
        "result = round(remainder * w / sum(weights), 2)",
        "result = round(remainder - sum(shares[:-1]), 2)",
        "result = round(1.0 - peak - sum(shares.values()), 10)",
        "result = round(remainder - sum(probs[o] for o in rest[:-1]), 10)",
        "import builtins as b\nresult = b.sum(b.len(x) for x in items)",
        "from builtins import len as size, sum as total\nresult = total(size(x) for x in items)",
        "text = 'sum([1.0, .35]) and .35 ** k'\n# sum(probabilities)",
        "total = 0.0\nfor value in values:\n    total += value",
        "result = 2 ** 5",
    ],
)
def test_fixture_arithmetic_accepts_integer_sums_rounding_strings_and_loops(source):
    assert _fixture_arithmetic_violations(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "result = .35 ** k",
        "result = (-.08) ** k",
        "result = (1 / 3) ** k",
        "result = (1.0 - .65) ** k",
        "result = 2 ** .5",
        "result = pow(.35, k)",
        "result = pow(base=.35, exp=k)",
        "import builtins as b\nresult = b.pow(.35, k)",
        "from builtins import pow as power\nresult = power(.35, k)",
        "result = round(.35 ** k, 10)",
    ],
)
def test_fixture_arithmetic_rejects_powers_with_literal_float_evidence(source):
    problems = _fixture_arithmetic_violations(source)
    assert len(problems) == 1
    assert "literal-arithmetic evidence requires repeated multiplication" in problems[0]


@pytest.mark.parametrize(
    "source",
    [
        "def f(decay: float, k: int):\n    return decay ** k",
        "decay = .35\nresult = decay ** k",
        "result = math.pow(.35, k)",
        "result = np.sum(probabilities)",
        "reducer = sum\nresult = reducer(probabilities)",
        "def sum(values):\n    return .5\nresult = sum(values)",
        "import builtins as b\nb = other\nresult = b.sum(values)",
        "result = len([.5]) ** 2",
    ],
)
def test_fixture_arithmetic_numeric_inference_and_alias_limits_are_explicit(source):
    # These are reviewer work, not a claim that arbitrary numeric Python is deterministic.
    assert _fixture_arithmetic_violations(source) == []


def test_fixture_arithmetic_parse_errors_name_the_builder_requirement():
    problems = _fixture_arithmetic_violations("result = sum(\n")
    assert len(problems) == 1
    assert "line 1: cannot parse build_fixtures.py" in problems[0]


@pytest.mark.parametrize("level", [1, 2])
@pytest.mark.parametrize("use_alias", [False, True])
@pytest.mark.parametrize(
    ("builtin", "expression"),
    [
        ("len", "sum({call}(x) for x in values)"),
        ("int", "sum({call}(x) for x in values)"),
        ("bool", "sum({call}(x) for x in values)"),
        ("range", "sum({call}(3))"),
        ("round", "{call}(sum(values), 2)"),
    ],
)
def test_fixture_arithmetic_relative_builtins_cannot_grant_exemptions(
    level, use_alias, builtin, expression
):
    name = "credited" if use_alias else builtin
    imported = f"{builtin} as {name}" if use_alias else builtin
    statement = "result = " + expression.format(call=name)
    absolute = f"from builtins import {imported}\n{statement}"
    relative = f"from {'.' * level}builtins import {imported}\n{statement}"
    assert _fixture_arithmetic_violations(absolute) == []
    problems = _fixture_arithmetic_violations(relative)
    assert len(problems) == 1
    assert "sum() requires a left-to-right accumulation loop" in problems[0]


@pytest.mark.parametrize(
    "binding_source",
    [
        "match value:\n    case {name}:\n        pass\n",
        "match values:\n    case [*{name}]:\n        pass\n",
        "match mapping:\n    case {{**{name}}}:\n        pass\n",
        "try:\n    pass\nexcept Exception as {name}:\n    pass\n",
        # Type parameter syntax and AST nodes exist on Python 3.12+ only.
        *(
            [
                "def f[{name}]():\n    pass\n",
                "def f[*{name}]():\n    pass\n",
                "def f[**{name}]():\n    pass\n",
            ]
            if hasattr(ast, "TypeVar")
            else []
        ),
    ],
)
@pytest.mark.parametrize("spelling", ["bare", "imported", "module"])
@pytest.mark.parametrize(
    ("builtin", "expression"),
    [
        ("len", "sum({call}(x) for x in values)"),
        ("int", "sum({call}(x) for x in values)"),
        ("bool", "sum({call}(x) for x in values)"),
        ("range", "sum({call}(3))"),
        ("round", "{call}(sum(values), 2)"),
    ],
)
def test_fixture_arithmetic_string_binders_cannot_grant_exemptions(
    binding_source, spelling, builtin, expression
):
    if spelling == "bare":
        prefix, name, call = "", builtin, builtin
    elif spelling == "imported":
        prefix = f"from builtins import {builtin} as credited\n"
        name, call = "credited", "credited"
    else:
        prefix, name, call = "import builtins as b\n", "b", f"b.{builtin}"
    statement = "result = " + expression.format(call=call)
    unshadowed = prefix + binding_source.format(name="unrelated") + statement
    shadowed = prefix + binding_source.format(name=name) + statement
    assert _fixture_arithmetic_violations(unshadowed) == []
    problems = _fixture_arithmetic_violations(shadowed)
    assert len(problems) == 1
    assert "sum() requires a left-to-right accumulation loop" in problems[0]


@pytest.mark.parametrize("prefix", ["../", "../../recipes/", "recipes/"])
@pytest.mark.parametrize("angle", [False, True], ids=["bare-destination", "angle-destination"])
@pytest.mark.parametrize("punctuation", [".", "…"])
@pytest.mark.parametrize("tail", [")", " )", ' "Next")', " 'Next')", " (Next))", '\n "Next")'])
def test_citation_link_destinations_keep_folder_punctuation_with_titles_and_whitespace(
    prefix, angle, punctuation, tail
):
    """Link syntax never grants the sentence-punctuation exception to a real folder name."""

    def linked(slug):
        destination = prefix + slug
        if angle:
            destination = "<" + destination + ">"
        return "see [next](" + destination + tail

    published = "30-citation-verification"
    assert not _citation_hits(linked(published), "prose")
    assert _citation_hits(linked(published + punctuation), "prose")
    assert _citation_hits(linked("99-not-a-recipe"), "prose")


@pytest.mark.parametrize("wrapper", ["{}", "`{}`", "[next]({})", '[next]({} "Next")'])
@pytest.mark.parametrize("prefix", ["./../", "../30-citation-verification/../"])
def test_citation_relative_segments_cannot_hide_an_unpublished_recipe(wrapper, prefix):
    """A slash before a later relative segment cannot suppress a recipe reference."""
    assert _citation_hits(wrapper.format(prefix + "99-not-a-recipe/"), "prose")
    assert not _citation_hits(wrapper.format(prefix + "01-sentiment-classification/"), "prose")


@pytest.mark.parametrize(
    "sentence",
    [
        "the PR in docs/glossary.md",
        "batch 3 of docs/glossary.md",
        "the brief from docs/glossary.md",
        "the orchestrator in docs/glossary.md",
        "acceptance criteria in docs/glossary.md",
    ],
)
def test_the_committed_file_carve_out_belongs_to_rule_numbers_alone(sentence):
    """A tracked path after any other process pointer is not a rule's target (#471)."""
    assert _citation_hits(sentence, "prose")
    assert not _citation_hits("rule 4 of docs/glossary.md", "prose")


@pytest.mark.parametrize("sentence", ["send batch 3 of 5 to review", "ship wave 3 of 5 first"])
def test_a_batch_number_is_ordinary_only_after_the_word_process(sentence):
    """Only "process batch N of M" is input batching; the same number elsewhere is a pointer."""
    assert _citation_hits(sentence, "prose")
    assert not _citation_hits("process batch 3 of 5", "prose")


# --------------------------------------------------------------------------------------------
# check: a fixed-order Choice prints no first-option-lean or position statistic (#208)
# --------------------------------------------------------------------------------------------

_SHUFFLE_HELPERS = ("stable_permutation", "stable_shuffle")
_POSITION_IDENTIFIER = re.compile(
    r"first_?(listed_?|shown_?)?(option|choice)|first_?listed_?(share|rate|fraction|lean)|gold_?(match_?)?pos|position_?(count|share|bias|stat)"
    r"|option_?position|^lean$|_lean$|^lean_",
    re.IGNORECASE,
)
_POSITION_PRINT_TEXT = re.compile(
    r"gold[-_ ]+(match[-_ ]+)?positions?\b|position[-_ ]+of[-_ ]+the[-_ ]+gold\b(?![-_ ]+standard)|first[- ](listed[- ])?(option|choice)[- ](share|lean|rate|fraction)"
    r"|first[- ]listed[- ](share|rate|fraction|lean)|position(al)?[- ]bias|lean toward the first",
    re.IGNORECASE,
)


def _cell_position_statistic_hits(source: str) -> list[str]:
    """What in one code cell computes or labels a position statistic: an identifier named for a
    first-option share or gold position, or a literal that prints one. A retriever's rank of the
    gold item (``candidates.index(gold)``) is a retrieval measure, not a position statistic.
    Prose that explains why a recipe prints none is markdown, so it is not read here. A cell that
    does not parse (a ``%magic``) is skipped, and a string used as a dict key is not read."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    hits: list[str] = []
    for node in ast.walk(tree):
        identifier = None
        if isinstance(node, ast.Name):
            identifier = node.id
        elif isinstance(node, ast.Attribute):
            identifier = node.attr
        elif isinstance(node, ast.keyword | ast.arg):
            identifier = node.arg
        if identifier and _POSITION_IDENTIFIER.search(identifier):
            hits.append(f"the name {identifier!r}")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _POSITION_PRINT_TEXT.search(node.value)
        ):
            hits.append(f"the text {node.value.strip()[:40]!r}")
    return hits


def _cell_output_text(cell: dict) -> str:
    parts = []
    for output in cell.get("outputs", []):
        text = output.get("text", "") or output.get("data", {}).get("text/plain", "")
        parts.append("".join(text) if isinstance(text, list) else text)
    return "\n".join(parts)


def _uses_shuffle_helper(source: str) -> bool:
    """True when ``source`` imports or calls ``stable_permutation`` or ``stable_shuffle``. Parsed
    with ``ast``, so a comment, a docstring or a string that only names one does not count."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in _SHUFFLE_HELPERS:
                return True
        if isinstance(node, ast.Import | ast.ImportFrom) and any(
            alias.name.rsplit(".", 1)[-1] in _SHUFFLE_HELPERS for alias in node.names
        ):
            return True
    return False


def _fixed_order_position_statistic_hits(cells: list[dict], py_sources: list[str]) -> list[str]:
    """Hits for a recipe whose ``Choice`` options keep one fixed order. A recipe whose notebook
    code or ``*.py`` files really call or import ``stable_permutation``/``stable_shuffle`` is
    exempt as a whole, even if it also lists another ``Choice`` in a fixed order:
    ``docs/fixtures.md`` lets it print where the gold option landed after shuffling, as a
    statement about the fixtures."""
    code = [cell_source(c) for c in cells if c["cell_type"] == "code"]
    if any(_uses_shuffle_helper(source) for source in [*code, *py_sources]):
        return []
    hits = []
    for cell in cells:
        if cell["cell_type"] != "code":
            continue
        where = f"cell {cell.get('id', '?')}"
        hits += [f"{where}: {what}" for what in _cell_position_statistic_hits(cell_source(cell))]
        match = _POSITION_PRINT_TEXT.search(_cell_output_text(cell))
        if match:
            hits.append(f"{where}: printed output {match.group(0)!r}")
    return hits


@pytest.mark.parametrize("recipe", guarded("fixed_order_choice_position_statistic"))
def test_fixed_order_choice_prints_no_position_statistic(recipe):
    """#208, ``docs/fixtures.md`` ("Per-item option order"): a ``Choice`` listed in one fixed,
    meaningful order prints no first-option-lean or gold-position statistic, because offline it
    measures only the fixture author, never a model. Detected in code cells and their stored
    output (not markdown, which may say why none is printed), for recipes that never use
    ``stable_permutation``/``stable_shuffle`` (a real call or import, see
    ``_uses_shuffle_helper``). Not seen: a statistic computed under other names, other wording or
    in a helper the notebook only calls; a string dict key; an unparseable cell; output that is
    only ``text/html``; and one printed by a shuffled recipe. Read as "gold position" (#684):
    printed text with ``-``, ``_`` or repeated spaces between "gold", an optional "match" and
    "position(s)", the phrase "position of the gold" (not "gold standard", "goldfish" or
    "golden"), and the names ``gold_pos...`` and ``gold_match_pos...``."""
    directory = TEMPLATE if recipe["slug"] == "_template" else recipe_dir(recipe)
    sources = [p.read_text("utf-8") for p in sorted(directory.glob("*.py"))]
    hits = _fixed_order_position_statistic_hits(notebook_cells(directory), sources)
    assert not hits, (
        "a fixed-order Choice prints no position statistic (docs/fixtures.md, 'Per-item option "
        "order'): " + "; ".join(hits)
    )


@pytest.mark.parametrize(
    "source",
    [
        "first_option_share = sum(a == options[0] for a in gold) / len(gold)",
        "gold_positions = [o.index(g) for o, g in rows]",
        'print("gold positions   rows")',
        "lean = share_first(rows)",
        "print('first-option lean:', 0.4)",
        "print('first-listed share:', 0.4)",
        "x = stats.first_option_share",
        "report(gold_pos=1)",
    ],
)
def test_position_statistic_in_code_is_a_hit(source):
    cells = [{"cell_type": "code", "id": "c", "source": source, "outputs": []}]
    assert _fixed_order_position_statistic_hits(cells, [])


@pytest.mark.parametrize(
    "source",
    [
        "rank = candidates.index(top)",
        "rank_counts[f'position {candidates.index(gold) + 1}'] += 1",
        "ordered = sorted(options)",
        "print('accuracy', sum(a == g for a, g in pairs) / len(pairs))",
    ],
)
def test_ordinary_option_code_is_not_a_position_statistic(source):
    cells = [{"cell_type": "code", "id": "c", "source": source, "outputs": []}]
    assert not _fixed_order_position_statistic_hits(cells, [])


def test_position_statistic_is_read_from_stored_output_and_not_from_markdown():
    printed = {
        "cell_type": "code",
        "id": "o",
        "source": "show()",
        "outputs": [{"output_type": "stream", "text": ["gold positions   rows\n"]}],
    }
    prose = {
        "cell_type": "markdown",
        "id": "m",
        "source": "No first-option lean is printed; offline it would measure only the fixtures.",
    }
    assert _fixed_order_position_statistic_hits([printed], [])
    assert not _fixed_order_position_statistic_hits([prose], [])


def test_a_recipe_that_shuffles_per_item_may_print_where_gold_landed():
    cells = [{"cell_type": "code", "id": "g", "source": 'print("gold positions")', "outputs": []}]
    assert _fixed_order_position_statistic_hits(cells, [])
    assert not _fixed_order_position_statistic_hits(cells, ["order = stable_shuffle(key, items)"])


@pytest.mark.parametrize(
    "py_source",
    [
        "# we do not use stable_shuffle here",
        '"""Seeds the way stable_permutation does."""',
        'NOTE = "stable_shuffle"',
    ],
)
def test_a_mention_of_a_shuffle_helper_does_not_exempt_a_recipe(py_source):
    cells = [{"cell_type": "code", "id": "g", "source": 'print("gold positions")', "outputs": []}]
    assert _fixed_order_position_statistic_hits(cells, [py_source])


@pytest.mark.parametrize(
    "py_source",
    [
        "from jev_cookbook.fixtures import stable_permutation",
        "import jev_cookbook.fixtures as f\norder = f.stable_shuffle(key, items)",
    ],
)
def test_a_real_import_or_call_of_a_shuffle_helper_exempts_a_recipe(py_source):
    cells = [{"cell_type": "code", "id": "g", "source": 'print("gold positions")', "outputs": []}]
    assert not _fixed_order_position_statistic_hits(cells, [py_source])


# The code and stored output of recipe 22's cell 23, abridged from main's cell 23 before #684 (it
# omits the AssertionError guard and two output lines): a count of
# ``candidates.index(gold) + 1`` over a Choice whose options are never shuffled, printed as a
# "gold-match position" table. The guard missed it on its wording alone.
_RECIPE_22_OLD_POSITION_CELL = {
    "cell_type": "code",
    "id": "rank",
    "source": (
        "rank_counts = Counter()\n"
        "for e in scored:\n"
        "    gold = labels[e.id]\n"
        "    if gold == helpers.NO_MATCH:\n"
        '        rank_counts["no_match"] += 1\n'
        "        continue\n"
        "    candidates, _answer = decide(e)\n"
        '    rank_counts[f"position {candidates.index(gold) + 1}"] += 1\n'
        "\n"
        'print(f"gold-match position across {len(scored)} scored assets{check}:")\n'
        "for position, count in sorted(rank_counts.items()):\n"
        '    print(f"  {position}: {count}")'
    ),
    "outputs": [
        {
            "name": "stdout",
            "output_type": "stream",
            "text": [
                "gold-match position across 40 scored assets (a pipeline check, not a Jev result):\n",
                "  no_match: 10\n",
                "  position 1: 24\n",
            ],
        }
    ],
}


def test_the_old_recipe_22_gold_match_position_cell_is_a_hit():
    """#684: the cell recipe 22 printed before it dropped the table is flagged, from its code
    and, separately, from its stored output alone."""
    cell = _RECIPE_22_OLD_POSITION_CELL
    assert _fixed_order_position_statistic_hits([cell], [])
    assert _cell_position_statistic_hits(cell["source"])
    output_only = {**cell, "source": "show()"}
    hits = _fixed_order_position_statistic_hits([output_only], [])
    assert any("printed output" in hit for hit in hits)


def test_the_old_recipe_22_cell_is_exempt_when_the_recipe_shuffles_per_item():
    cells = [_RECIPE_22_OLD_POSITION_CELL]
    assert not _fixed_order_position_statistic_hits(cells, ["order = stable_shuffle(key, items)"])


@pytest.mark.parametrize("source", ["gold_match_position = 1", "print('gold match positions')"])
def test_gold_match_position_wording_variants_are_hits(source):
    cells = [{"cell_type": "code", "id": "c", "source": source, "outputs": []}]
    assert _fixed_order_position_statistic_hits(cells, [])


@pytest.mark.parametrize(
    "text",
    [
        "gold_position",
        "gold  match__position",
        "position of the gold match",
        "Position of the gold record",
    ],
)
def test_the_widened_position_wording_is_a_hit(text):
    """#684: ``_`` and repeated separators, and the phrase "position of the gold", are read."""
    cells = [{"cell_type": "code", "id": "c", "source": f"print({text!r})", "outputs": []}]
    assert _fixed_order_position_statistic_hits(cells, [])


@pytest.mark.parametrize(
    "text",
    [
        "position of the goldfish",
        "position of the golden retriever",
        "gold-standard positions",
        "position of the gold standard in the table",
    ],
)
def test_ordinary_gold_wording_is_not_a_position_statistic(text):
    cells = [{"cell_type": "code", "id": "c", "source": f"print({text!r})", "outputs": []}]
    assert not _fixed_order_position_statistic_hits(cells, [])
