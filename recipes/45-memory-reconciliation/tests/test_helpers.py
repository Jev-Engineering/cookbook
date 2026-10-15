"""Tests for recipe 45's helpers. They load the helpers by file path.

The acceptance criterion this file exists to satisfy is narrower than "the store works" --
``jev_cookbook.simulation.Store`` already has its own tests in ``tests/test_simulation.py``, and
a test that only re-proves "the store never deletes" would pass whether or not this recipe's
*policy* (``helpers.reconcile``) is correct, because that property holds by construction of
``Store`` itself. Every test below is instead about what THIS module decides to do with a
``Store``: which key an outcome writes to, whether it writes at all, and what stays reachable
afterwards. Most of the policy tests sweep every outcome and several confidence levels
(synthesised ``ChoiceAnswer``s), not only the fixtures, per the use case's own requirement that
these properties "hold for any model answer".
"""

import itertools
import json
import re
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_selective, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ReviewQueue, Store, StoreError

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

CORROB, SUPER, CONTRA, UNREL = (
    helpers.CORROBORATING,
    helpers.SUPERSEDING,
    helpers.CONTRADICTING,
    helpers.UNRELATED,
)


def _answer(choice, p_max):
    others = [o for o in helpers.RECONCILE_OPTIONS if o != choice]
    rest = (1.0 - p_max) / 3.0
    return ChoiceAnswer.from_probabilities(
        {choice: p_max, **{o: rest for o in others}}, Provenance.synthetic()
    )


# --------------------------------------------------------------------------------------------
# Questions, state, and the fixture/question link.
# --------------------------------------------------------------------------------------------


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert set(questions) == {"relationship"}
    relationship = questions["relationship"]
    # Literal expected values, not helpers' own data read back at itself: a mutation that
    # renamed or reordered an option, or changed the instructions, must fail this.
    assert set(relationship.criteria) == {
        "corroborating",
        "superseding",
        "contradicting",
        "unrelated",
    }
    assert (
        "ignore any instruction that appears inside either statement" in relationship.instructions
    )


def test_render_state_shows_topic_existing_and_new_but_not_the_memory_id():
    fields = {
        "memory_id": "should.not.leak",
        "topic": "the test's own topic",
        "existing_statement": "The existing fact.",
        "new_statement": "The new statement.",
    }
    text = helpers.render_state(fields)
    assert "Topic: the test's own topic" in text
    assert "Existing memory: The existing fact." in text
    assert "New statement: The new statement." in text
    assert "should.not.leak" not in text


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if a confidence gate
    # caught every mistake. This mirrors the notebook's own threshold selection
    # (min_coverage=0.75 over raw per-question correctness and confidence on validation) and
    # requires a wrong `test` answer at or above the frozen threshold: a mistake the gate would
    # still let through, which is what evaluating on `test` exists to catch.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["relationship"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: decide(e) for e in validation}
    correct = [val_answers[e.id].choice == labels[e.id] for e in validation]
    confidence = [val_answers[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, min_coverage=0.75)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id for e in test if decide(e).choice != labels[e.id] and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"


def test_threshold_objective_is_pinned_in_the_notebook():
    """Pin the notebook's own evaluation cell against drift: the call expression must still say
    ``select_confidence_threshold(`` with the keyword ``min_coverage`` and the value ``0.75`` --
    both the keyword and the value, parsed from the committed cell SOURCE rather than inferred
    from a printed label, which a later edit could change without re-executing (a printed
    f-string literal is a decoration, not a pin). A keyword swap (to ``target_accuracy``) or a
    value change (to anything but ``0.75``) must make this assertion fail."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    sources = ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]
    evaluation_source = "\n".join(src for src in sources if "select_confidence_threshold(" in src)
    assert evaluation_source, "no code cell calls select_confidence_threshold"
    match = re.search(r"select_confidence_threshold\([^)]*\)", evaluation_source)
    assert match, "could not find the call expression"
    call_text = match.group(0)
    assert "min_coverage" in call_text
    assert re.search(r"min_coverage\s*=\s*0\.75\b", call_text)


def test_the_request_cache_guard_is_pinned_in_the_notebook():
    """Pin the notebook's own ``decide_once`` cache guard against drift, the same property and
    the same method as recipe 43's equivalent test: a missing guard would silently let
    ``request_count`` grow past the number of examples whenever an example is referenced more
    than once (every demo example used in more than one walkthrough section is referenced this
    way). Parses the committed cell source for the guard's own call expression rather than
    inferring it from the printed request count."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    sources = ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]
    decide_once_source = "\n".join(src for src in sources if "def decide_once" in src)
    assert decide_once_source, "no code cell defines decide_once"
    assert re.search(r"if\s+example\.id\s+not in\s+answer_cache\s*:", decide_once_source)
    assert "request_count += 1" in decide_once_source


def test_request_count_equals_one_decide_per_example_not_per_reference():
    """A worked, independent proof of the same property the notebook's own guard enforces:
    build a ``decide_once``-shaped cache by hand here, reference the same example more than
    once, and show the underlying backend is only ever called once for it."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    demo = [e for e in examples if e.split == "demo"]
    assert demo

    calls = 0
    cache: dict[str, object] = {}

    def decide_once(example):
        nonlocal calls
        if example.id not in cache:
            calls += 1
            cache[example.id] = backend.decide(helpers.build_state(example.fields), questions)[
                "relationship"
            ]
        return cache[example.id]

    first = decide_once(demo[0])
    second = decide_once(demo[0])
    third = decide_once(demo[0])
    assert first is second is third
    assert calls == 1


# --------------------------------------------------------------------------------------------
# Baselines: on real, balanced fixture counts (not a formula). Two of the three baselines are
# constant predictions; on a pool balanced k ways a constant prediction scores exactly 1/k by
# arithmetic alone, so a test asserting that figure is pinning a STRUCTURAL FLOOR, not guarding
# against a baseline that could have matched or beaten Jev -- nothing cheaper-and-constant ever
# could, on a balanced pool, whatever the mechanism's own accuracy is. The one baseline capable
# of actually tying or beating Jev is keyword_overlap_baseline, whose accuracy is earned from
# the statements' own text rather than fixed by the label distribution; the test that follows it
# below is the one that can fail, and is the real rule-19 guard.
# --------------------------------------------------------------------------------------------


def test_majority_class_baseline_breaks_ties_by_option_order():
    # Every scored split is built four-per-outcome (balanced), so this is a genuine tie; the
    # function must be deterministic rather than depend on dict iteration order by accident.
    gold = [CORROB, SUPER, CONTRA, UNREL]
    assert helpers.majority_class_baseline(gold) == CORROB  # first in RECONCILE_OPTIONS
    assert helpers.majority_class_baseline([SUPER, SUPER, CORROB]) == SUPER  # a real majority


def test_always_unrelated_baseline_is_constant():
    for fields in ({}, {"anything": "ignored"}):
        assert helpers.always_unrelated_baseline(fields) == UNREL


def test_fixture_gold_counts_are_four_per_outcome_per_scored_split():
    """Pins the balanced-class design the baseline comparison depends on: if a future fixture
    edit skews the class balance, the constant baselines stop sitting at a shared 1/k floor and
    this test is what would catch it."""
    labels = load_labels(RECIPE)
    examples = {e.id: e for e in load_inputs(RECIPE)}
    for split in ("validation", "test"):
        split_labels = [labels[i] for i in labels if examples[i].split == split]
        assert len(split_labels) == 16
        counts = {name: split_labels.count(name) for name in helpers.RECONCILE_OPTIONS}
        assert counts == {CORROB: 4, SUPER: 4, CONTRA: 4, UNREL: 4}


def test_constant_baselines_sit_at_the_structural_floor_not_a_checked_comparison():
    """On a pool balanced k ways (k=4 here, pinned by the test above), every constant-prediction
    baseline scores exactly 1/k: this is arithmetic, true of ANY mechanism's own accuracy and
    any constant prediction, so it cannot distinguish an above-chance mechanism from one at
    chance. Swept here over every constant option, not only the two the notebook names, to show
    the floor is not particular to `corroborating`/`unrelated`: every one of the four scores the
    same 0.2500 on both scored splits, because that is what "balanced four ways" means."""
    labels = load_labels(RECIPE)
    examples = {e.id: e for e in load_inputs(RECIPE)}
    for split in ("validation", "test"):
        gold = [labels[e.id] for e in examples.values() if e.split == split and e.id in labels]
        for option in helpers.RECONCILE_OPTIONS:
            accuracy = sum(g == option for g in gold) / len(gold)
            assert accuracy == 0.25, (split, option)
    # And the two baselines the notebook prints are exactly two readings of that one floor:
    majority = helpers.majority_class_baseline(
        [labels[e.id] for e in examples.values() if e.id in labels]
    )
    assert majority == helpers.CORROBORATING  # first in RECONCILE_OPTIONS, a genuine four-way tie


def test_keyword_overlap_baseline_does_not_beat_jev_on_test():
    """The one baseline here whose score is NOT fixed by the pool's balance: it is capable of
    tying or beating Jev in principle (a mechanism that just restates cue-words could score
    arbitrarily well or badly depending on the fixtures), so this assertion is a real guard
    against a dominated headline, not a floor check. Computed by counting over the real
    committed `test` split, both sides: a tamper that made `keyword_overlap_baseline` score 1.0
    (for example, by reading `fields` for the gold label directly) would turn this red, which is
    the property `test_constant_baselines_sit_at_the_structural_floor_not_a_checked_comparison`
    structurally cannot show for either constant baseline."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    test = [e for e in examples if e.split == "test" and e.id in labels]
    gold = [labels[e.id] for e in test]

    jev_correct = [
        backend.decide(helpers.build_state(e.fields), questions)["relationship"].choice
        == labels[e.id]
        for e in test
    ]
    jev_accuracy = sum(jev_correct) / len(jev_correct)

    overlap_correct = [
        helpers.keyword_overlap_baseline(e.fields) == g for e, g in zip(test, gold, strict=True)
    ]
    overlap_accuracy = sum(overlap_correct) / len(overlap_correct)

    assert 0.0 < overlap_accuracy < 1.0  # a real, non-degenerate baseline on this split
    assert jev_accuracy > overlap_accuracy


# --------------------------------------------------------------------------------------------
# The TUNED surface-form family behind `baselines-md`'s margin paragraph. That paragraph makes
# quantitative claims about objects that do not exist in `helpers.py` -- that a zero-request
# surface rule can be fitted until it matches Jev on `test`, that it does not hold that score on
# `validation`, and that nothing in the enumerated family holds it on both -- so the family is
# built and measured here. Prose does not re-run.
#
# An earlier version of this family held the capitalised-value rule in one unfiltered form, which
# misfired on sentence-initial function words (`The`, `It`, `For` are not values) and so made the
# family's own negative come out true for the wrong reason. Five formulations of that rule are
# swept here, including the unfiltered one, so no single formulation decides the extrema.
#
# The variants deliberately reuse `helpers._SUPERSEDING_CUES`, `helpers._STOPWORDS` and
# `helpers._content_words` rather than copies of them: the point of the pin is that these claims
# move when the recipe's own tokenizer, cue list or fixtures move, and a private-name copy here
# would hold them still. Nothing below reads a gold label, an example id or a split: every
# variant sees the two statements and nothing else.
# --------------------------------------------------------------------------------------------

HEDGE_CUES = ("might be changing", "might be moving", "not sure to who")
_CAPITALISED = re.compile(r"\b[A-Z][a-z]+")
CAPITALISED_MODES = ("off", "raw", "stopword-filtered", "non-sentence-initial", "content-word")
LOW_CUTS = (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35)
CORROBORATING_CUTS = (0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75)
FAMILY_SIZE = 2 * len(CAPITALISED_MODES) * len(LOW_CUTS) * len(CORROBORATING_CUTS)  # 630
JEV_BOTH_SPLITS = 0.9375  # printed in the notebook for both splits
SURFACE_BEST_ON_VALIDATION = 0.875


def _capitalised(text, mode):
    """The capitalised tokens a variant treats as candidate *values*. ``raw`` is the unfiltered
    form whose misfire on `The`/`It`/`For` is the reason this is swept rather than fixed."""
    if mode == "raw":
        return set(_CAPITALISED.findall(text))
    if mode == "stopword-filtered":
        return {w for w in _CAPITALISED.findall(text) if w.lower() not in helpers._STOPWORDS}
    if mode == "non-sentence-initial":
        found = set()
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            opener = re.match(r"\s*([A-Z][a-z]+)", sentence)
            found |= {
                token
                for token in _CAPITALISED.findall(sentence)
                if not (opener and token == opener.group(1))
            }
        return found
    if mode == "content-word":
        content = helpers._content_words(text)
        return {w for w in _CAPITALISED.findall(text) if w.lower() in content}
    raise AssertionError(f"unknown capitalised-token mode {mode!r}")


def _surface_variant(hedge, capitalised_mode, low_cut, corroborating_cut):
    """One member of the family, reading only ``new_statement`` and ``existing_statement``.
    ``hedge`` adds ``HEDGE_CUES`` to the committed correction cues; ``capitalised_mode`` selects
    how a swapped-value rule decides what counts as a value (``"off"`` disables the rule); the
    two cuts are ``keyword_overlap_baseline``'s own bands, swept.

    With ``hedge=False, capitalised_mode="off", 0.2, 0.5`` it reproduces the committed baseline,
    which ``test_the_swept_surface_family_reproduces_the_committed_baseline`` checks."""

    def variant(fields):
        new = fields["new_statement"]
        lowered = new.lower()
        cues = tuple(helpers._SUPERSEDING_CUES) + (HEDGE_CUES if hedge else ())
        if any(cue in lowered for cue in cues):
            return SUPER
        new_words = helpers._content_words(new)
        existing_words = helpers._content_words(fields["existing_statement"])
        if not new_words or not existing_words:
            return UNREL
        overlap = len(new_words & existing_words) / len(existing_words)
        if capitalised_mode != "off" and overlap >= low_cut:
            new_caps = _capitalised(new, capitalised_mode)
            old_caps = _capitalised(fields["existing_statement"], capitalised_mode)
            if (new_caps - old_caps) and (old_caps - new_caps):
                return CONTRA
        if overlap < low_cut:
            return UNREL
        return CORROB if overlap >= corroborating_cut else CONTRA

    return variant


def _swept_family():
    """Every combination: hedge cues on/off, five formulations of the swapped-value rule, seven
    low cuts, nine corroborating cuts. ``FAMILY_SIZE`` is the number `baselines-md` quotes."""
    return [
        (
            (hedge, mode, low_cut, corroborating_cut),
            _surface_variant(hedge, mode, low_cut, corroborating_cut),
        )
        for hedge in (False, True)
        for mode in CAPITALISED_MODES
        for low_cut in LOW_CUTS
        for corroborating_cut in CORROBORATING_CUTS
    ]


def _scored_rows(split):
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    return [e for e in examples if e.split == split and e.id in labels], labels


def _accuracy(predict, rows, labels):
    return sum(predict(e.fields) == labels[e.id] for e in rows) / len(rows)


def _misses(predict, rows, labels):
    return {e.id for e in rows if predict(e.fields) != labels[e.id]}


def _jev_accuracy(rows, labels):
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    return sum(
        backend.decide(helpers.build_state(e.fields), questions)["relationship"].choice
        == labels[e.id]
        for e in rows
    ) / len(rows)


def test_the_swept_surface_family_reproduces_the_committed_baseline():
    """The family's calibration check: the member with no hedge cues, no swapped-value rule and
    `keyword_overlap_baseline`'s committed cuts must agree with that function on every scored
    row of both splits. Without it the extrema below could be measured over a family that has
    drifted away from the baseline they are compared against, and still look green."""
    committed_member = _surface_variant(False, "off", 0.2, 0.5)
    for split in ("validation", "test"):
        rows, labels = _scored_rows(split)
        for e in rows:
            assert committed_member(e.fields) == helpers.keyword_overlap_baseline(e.fields), e.id


def test_jev_holds_the_same_accuracy_on_both_splits():
    """The positive half of `baselines-md`'s claim, and the half that needs no family at all:
    Jev reads 0.9375 on `validation` and 0.9375 on `test`, missing exactly the designated
    confidently-wrong row in each. Asserted per split AND as an equality between them, because
    the claim is cross-split stability rather than either number alone."""
    scores = {}
    for split, wrong_row in (("validation", "v-contra-04-wrong"), ("test", "t-contra-04-wrong")):
        rows, labels = _scored_rows(split)
        scores[split] = _jev_accuracy(rows, labels)
        assert scores[split] == JEV_BOTH_SPLITS, (split, scores[split])
        backend = get_backend(fixtures=responses_path(RECIPE))
        questions = helpers.build_questions()
        missed = {
            e.id
            for e in rows
            if backend.decide(helpers.build_state(e.fields), questions)["relationship"].choice
            != labels[e.id]
        }
        assert missed == {wrong_row}, (split, missed)
    assert scores["validation"] == scores["test"]


def test_a_surface_variant_ties_jev_on_test_and_none_holds_both_splits():
    """`baselines-md`'s comparison, computed over the whole family on BOTH splits rather than
    argued. Four properties, each separately falsifiable:

    1. the best variant on `test` **ties** Jev there -- a zero-request rule matching the
       mechanism on the reported split, which rule 19 counts as a loss, so the recipe says it
       rather than reporting only its margin over the committed rule;
    2. it misses exactly the one row Jev misses on `test`;
    3. **no** variant reaches Jev's accuracy on `validation`, and the family's maximum there is
       0.8750 -- so the tie does not transfer;
    4. therefore no variant holds 0.9375 on both splits, which is the claim.

    The tie is not one formulation's knife edge: a tying member is required from each of the
    three filtered formulations of the swapped-value rule, so a single mis-specified formulation
    can neither manufacture nor suppress the result. That is the defect this family had in an
    earlier round -- the unfiltered rule alone, misfiring on `The`/`It`/`For`, made the family's
    negative true for the wrong reason -- and these assertions are what would catch it again.

    Every claim here is bounded by the family: it is a statement about these variants, not about
    what any surface heuristic could do."""
    family = _swept_family()
    assert len(family) == FAMILY_SIZE == 630

    by_split = {}
    for split in ("validation", "test"):
        rows, labels = _scored_rows(split)
        by_split[split] = {
            "jev": _jev_accuracy(rows, labels),
            "scores": {key: _accuracy(variant, rows, labels) for key, variant in family},
            "rows": rows,
            "labels": labels,
        }

    test = by_split["test"]
    validation = by_split["validation"]

    # 1 and 2: the tie on `test`, and the row it leaves
    best_on_test = max(test["scores"].values())
    assert best_on_test == test["jev"], (best_on_test, test["jev"])
    tying = [key for key, score in test["scores"].items() if score == test["jev"]]
    assert tying
    for key in tying:
        variant = dict(family)[key]
        assert _misses(variant, test["rows"], test["labels"]) == {"t-contra-04-wrong"}, key

    # 3: it does not transfer
    assert max(validation["scores"].values()) == SURFACE_BEST_ON_VALIDATION
    assert max(validation["scores"].values()) < validation["jev"]
    assert [key for key, score in validation["scores"].items() if score >= validation["jev"]] == []
    for key in tying:
        assert validation["scores"][key] == SURFACE_BEST_ON_VALIDATION, key

    # 4: the claim
    both = [
        key
        for key in test["scores"]
        if test["scores"][key] >= test["jev"] and validation["scores"][key] >= validation["jev"]
    ]
    assert both == [], both

    # robustness: the tie survives each filtered formulation, not just one
    for mode in ("stopword-filtered", "non-sentence-initial", "content-word"):
        assert any(key[1] == mode for key in tying), mode


def test_keyword_overlap_baseline_predicts_superseding_on_an_explicit_correction_cue():
    fields = {
        "topic": "x",
        "existing_statement": "The value is one.",
        "new_statement": "Correction: the value is two.",
    }
    assert helpers.keyword_overlap_baseline(fields) == SUPER


def test_keyword_overlap_baseline_predicts_unrelated_on_disjoint_statements():
    fields = {
        "topic": "x",
        "existing_statement": "The parking garage charges eight dollars on weekends.",
        "new_statement": "The orientation starts at ten on Wednesday.",
    }
    assert helpers.keyword_overlap_baseline(fields) == UNREL


# --------------------------------------------------------------------------------------------
# reconcile(): the confidence gate -- swept over every outcome and several confidence levels,
# not only hand-picked fixtures, because the policy must hold for any model answer.
# --------------------------------------------------------------------------------------------


def _fresh_store(key="k", value="the existing fact"):
    store = Store()
    store.put(key, value, writer="rule:seed", step=0, rule="initial")
    return store


def test_min_confidence_out_of_range_raises():
    store, queue, conflicts = _fresh_store(), ReviewQueue(), helpers.ConflictLog()
    with pytest.raises(ValueError):
        helpers.reconcile(
            "e", "k", "x", _answer(CORROB, 0.9), 1.5, store, queue=queue, conflicts=conflicts
        )


def test_a_below_gate_answer_writes_no_state_change_for_any_outcome():
    """Swept over all four outcomes and a grid of confidences, all below a fixed gate: in every
    case, store.version is unchanged, the live value is unchanged, no conflict is recorded, and
    exactly one item lands in the review queue. This is the property, not a sample of it: the
    outcome space is exactly four values and the confidence grid below is dense enough that a
    policy bug gating on the wrong side of the comparison, or on the wrong field, would show up
    on at least one point."""
    for outcome in helpers.RECONCILE_OPTIONS:
        for p_max in (0.25, 0.30, 0.40, 0.55, 0.69):  # confidence 0.0, 0.067, 0.2, 0.4, 0.587
            store = _fresh_store()
            queue, conflicts = ReviewQueue(), helpers.ConflictLog()
            answer = _answer(outcome, p_max)
            version_before, value_before = store.version, store.get("k")
            result = helpers.reconcile(
                "e",
                "k",
                "a candidate statement",
                answer,
                0.7,
                store,
                queue=queue,
                conflicts=conflicts,
            )
            assert store.version == version_before, (outcome, p_max)
            assert store.get("k") == value_before
            assert len(conflicts) == 0
            assert len(queue) == 1
            assert result.outcome is None
            assert result.applied is False
            assert result.reason == helpers.REASON_LOW_CONFIDENCE


def test_unrelated_writes_nothing_once_it_clears_the_gate():
    for p_max in (0.70, 0.80, 0.95, 1.0 - 1e-9):
        store = _fresh_store()
        queue, conflicts = ReviewQueue(), helpers.ConflictLog()
        version_before, value_before = store.version, store.get("k")
        result = helpers.reconcile(
            "e",
            "k",
            "an unrelated statement",
            _answer(UNREL, p_max),
            0.6,
            store,
            queue=queue,
            conflicts=conflicts,
        )
        assert store.version == version_before
        assert store.get("k") == value_before
        assert len(conflicts) == 0
        assert len(queue) == 0
        assert result.outcome == UNREL
        assert result.applied is False
        assert result.version is None


def test_corroborating_and_superseding_both_write_a_new_live_value_and_keep_the_old_one_in_history():
    """The provenance property this use case names for superseding, swept for both outcomes (corroborating
    legitimately overwrites with the same fact restated, superseding with a changed one -- both
    are a `put`, never a `delete`, so both have this property): the OLD write stays reachable
    through `store.history(key)` after the new one lands, and the live value becomes the new
    statement. A policy that routed either outcome through a different key, or that tombstoned
    the old value first, would fail this."""
    for outcome in (CORROB, SUPER):
        for p_max in (0.65, 0.80, 0.97):
            store = _fresh_store(value="the original fact")
            queue, conflicts = ReviewQueue(), helpers.ConflictLog()
            history_before = store.history("k")
            assert len(history_before) == 1 and history_before[0].value == "the original fact"

            result = helpers.reconcile(
                "e",
                "k",
                "a new statement",
                _answer(outcome, p_max),
                0.5,
                store,
                queue=queue,
                conflicts=conflicts,
            )

            assert result.outcome == outcome
            assert result.applied is True
            assert store.get("k") == "a new statement"
            history_after = store.history("k")
            assert len(history_after) == 2
            assert (
                history_after[0].value == "the original fact"
            )  # the superseded value: still there
            assert history_after[1].value == "a new statement"
            assert len(conflicts) == 0  # neither outcome ever raises a conflict
            assert len(queue) == 0


def test_contradicting_leaves_the_original_key_live_and_records_a_conflict():
    """The provenance property this use case names for contradicting: the memory's own live value is
    UNCHANGED (provably: store.get(key) before and after is identical, and store.version does
    not advance past the one new write), while the contested candidate is written under a
    parallel key and stays reachable there, and exactly one ConflictRecord documents both
    sides. Swept over several confidence levels above the gate."""
    for p_max in (0.65, 0.78, 0.93):
        store = _fresh_store(value="the original fact")
        queue, conflicts = ReviewQueue(), helpers.ConflictLog()
        version_before = store.version

        result = helpers.reconcile(
            "e",
            "k",
            "a contradicting statement",
            _answer(CONTRA, p_max),
            0.5,
            store,
            queue=queue,
            conflicts=conflicts,
        )

        assert result.outcome == CONTRA
        assert result.applied is True
        assert store.get("k") == "the original fact"  # untouched
        assert store.version == version_before + 1  # exactly one new write: the candidate's own
        assert result.conflict_key is not None
        assert store.get(result.conflict_key) == "a contradicting statement"  # reachable too
        assert len(conflicts) == 1
        entry = conflicts.to_dicts()[0]
        assert entry["key"] == "k"
        assert entry["conflict_key"] == result.conflict_key
        assert entry["statement"] == "a contradicting statement"
        assert len(queue) == 0


def test_two_separate_contradictions_against_the_same_key_do_not_collide():
    """conflict_key_for includes the store version, so a second, later contradiction against a
    key that already has one unresolved conflict gets its own conflict_key rather than
    overwriting the first candidate's entry."""
    store = _fresh_store(value="the original fact")
    queue, conflicts = ReviewQueue(), helpers.ConflictLog()

    first = helpers.reconcile(
        "e1",
        "k",
        "first contradiction",
        _answer(CONTRA, 0.8),
        0.5,
        store,
        queue=queue,
        conflicts=conflicts,
    )
    second = helpers.reconcile(
        "e2",
        "k",
        "second contradiction",
        _answer(CONTRA, 0.8),
        0.5,
        store,
        queue=queue,
        conflicts=conflicts,
    )

    assert first.conflict_key != second.conflict_key
    assert store.get(first.conflict_key) == "first contradiction"
    assert store.get(second.conflict_key) == "second contradiction"
    assert store.get("k") == "the original fact"  # still untouched by either
    assert len(conflicts) == 2


def test_conflict_key_for_is_order_sensitive_in_the_version_it_names():
    assert helpers.conflict_key_for("k", 3) == "k::conflict:3"
    assert helpers.conflict_key_for("k", 3) != helpers.conflict_key_for("k", 4)


# --------------------------------------------------------------------------------------------
# Order-dependence: the same statement text, compared against two different live states, is a
# real property of `reconcile` (it never reads anything but the current store state and the
# answer), demonstrated here on the recipe's own committed hard-case fixtures.
# --------------------------------------------------------------------------------------------


def test_order_dependent_case_is_superseding_then_contradicting_on_the_committed_fixtures():
    """`demo-order-01` superseded "email" to "SMS"; `demo-order-02`'s existing_statement is
    written, byte for byte, to equal `demo-order-01`'s new_statement -- i.e. it is exactly what
    the store holds live after step 1, not an independently authored description of "now". The
    same underlying claim ("the user gets emails") would have CORROBORATED the memory before
    step 1 and CONTRADICTS it after: this is what "the right answer depends on which version
    the state supplies" means for a real pair of committed fixtures, not merely an assertion
    about helpers.reconcile in isolation."""
    examples = {e.id: e for e in load_inputs(RECIPE)}
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    step1, step2 = examples["demo-order-01"], examples["demo-order-02"]
    assert step2.fields["existing_statement"] == step1.fields["new_statement"]

    store = Store()
    store.put(
        "user.notification_channel", step1.fields["existing_statement"], writer="rule:seed", step=0
    )
    queue, conflicts = ReviewQueue(), helpers.ConflictLog()

    answer1 = backend.decide(helpers.build_state(step1.fields), questions)["relationship"]
    result1 = helpers.reconcile(
        step1.id,
        "user.notification_channel",
        step1.fields["new_statement"],
        answer1,
        0.5,
        store,
        queue=queue,
        conflicts=conflicts,
        step=1,
    )
    assert result1.outcome == SUPER
    assert (
        store.get("user.notification_channel") == "The user asked to switch notifications to SMS."
    )

    answer2 = backend.decide(helpers.build_state(step2.fields), questions)["relationship"]
    result2 = helpers.reconcile(
        step2.id,
        "user.notification_channel",
        step2.fields["new_statement"],
        answer2,
        0.5,
        store,
        queue=queue,
        conflicts=conflicts,
        step=2,
    )
    assert result2.outcome == CONTRA
    # The live value is still step 1's SMS write -- untouched by the contradiction.
    assert (
        store.get("user.notification_channel") == "The user asked to switch notifications to SMS."
    )
    # But the ORIGINAL "email" value, and the new "email works great" candidate, are both
    # still reachable: nothing about this sequence lost either one.
    history = store.history("user.notification_channel")
    assert history[0].value == "The user receives notifications by email."
    assert store.get(result2.conflict_key) == step2.fields["new_statement"]


def test_mutual_supersession_order_flip_produces_different_final_live_values():
    """The second hard case: two statements that would each read as a clean, acknowledged
    correction of whatever is currently live. Run A-then-B, A supersedes the original and then
    B supersedes A's write; run B-then-A, the mirror. Both orders look locally correct at every
    step (each is a confident, acknowledged "superseding" against whatever was live when it
    arrived) -- the only way to see the two statements actually conflict with each other is
    that the two final live values DIFFER depending on which arrived first. This is what "an
    unresolved conflict rather than a resolution" means: chaining two mutually-exclusive
    corrections resolves to a different, order-dependent answer each time, which is the
    opposite of a resolution. The full history of each run keeps every step, so a reader can
    recover the disagreement either way."""
    examples = {e.id: e for e in load_inputs(RECIPE)}
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    a_vs_base = examples["demo-mutual-a-vs-base"]
    b_vs_after_a = examples["demo-mutual-b-vs-after-a"]
    b_vs_base = examples["demo-mutual-b-vs-base"]
    a_vs_after_b = examples["demo-mutual-a-vs-after-b"]
    base = a_vs_base.fields["existing_statement"]
    assert base == b_vs_base.fields["existing_statement"]

    def run(first, second):
        store = Store()
        store.put("helios.deadline", base, writer="rule:seed", step=0)
        queue, conflicts = ReviewQueue(), helpers.ConflictLog()
        for example in (first, second):
            answer = backend.decide(helpers.build_state(example.fields), questions)["relationship"]
            helpers.reconcile(
                example.id,
                "helios.deadline",
                example.fields["new_statement"],
                answer,
                0.5,
                store,
                queue=queue,
                conflicts=conflicts,
            )
        return store

    a_then_b = run(a_vs_base, b_vs_after_a)
    b_then_a = run(b_vs_base, a_vs_after_b)

    assert (
        a_then_b.get("helios.deadline") == "Correction: the Helios launch deadline is now March 22."
    )
    assert (
        b_then_a.get("helios.deadline") == "Correction: the Helios launch deadline is now March 15."
    )
    assert a_then_b.get("helios.deadline") != b_then_a.get("helios.deadline")
    # Neither run lost the base value or either correction: both histories have all 3 writes.
    assert len(a_then_b.history("helios.deadline")) == 3
    assert len(b_then_a.history("helios.deadline")) == 3


# --------------------------------------------------------------------------------------------
# Replay: the write log alone reconstructs the final snapshot, for any sequence of outcomes.
# --------------------------------------------------------------------------------------------


def test_rebuild_store_from_writes_reconstructs_the_same_snapshot_for_any_outcome_sequence():
    """Exhaustive sweep, not a sample: every length-3 sequence of the four outcomes (4**3 = 64)
    applied to two different keys in turn, confidently (above any realistic gate). After each
    sequence, rebuilding a fresh store from `store.writes()` through `helpers.rebuild_store_from_writes`
    must reproduce the exact same snapshot AND the exact same write history (every field of
    every WriteRecord, not only the live values) as the original store that accumulated them
    one call at a time."""
    sequences = list(itertools.product(helpers.RECONCILE_OPTIONS, repeat=3))
    assert len(sequences) == 4**3 == 64
    for sequence in sequences:
        store = Store()
        store.put("k1", "base one", writer="rule:seed", step=0)
        store.put("k2", "base two", writer="rule:seed", step=0)
        queue, conflicts = ReviewQueue(), helpers.ConflictLog()
        for i, outcome in enumerate(sequence, start=1):
            key = "k1" if i % 2 else "k2"
            helpers.reconcile(
                f"e{i}",
                key,
                f"statement {i}",
                _answer(outcome, 0.9),
                0.5,
                store,
                queue=queue,
                conflicts=conflicts,
                step=i,
            )
        rebuilt = helpers.rebuild_store_from_writes(store.writes())
        assert rebuilt.snapshot() == store.snapshot(), sequence
        assert rebuilt.to_dicts() == store.to_dicts(), sequence


def test_the_replay_comparison_can_actually_fail():
    """Fail-open discipline: before trusting the equality above, prove it can be false. Rebuild
    from a write log missing its last entry and confirm the rebuilt snapshot differs from the
    original -- so the comparison above is a real check, not a tautology that would pass no
    matter what `rebuild_store_from_writes` did."""
    store = _fresh_store(value="v1")
    store.put("k", "v2", writer="model:x", step=1)
    store.put("k", "v3", writer="model:x", step=2)
    truncated = helpers.rebuild_store_from_writes(store.writes()[:-1])
    assert truncated.snapshot() != store.snapshot()
    assert truncated.get("k") == "v2"
    assert store.get("k") == "v3"


def test_replay_of_a_contradicting_write_also_round_trips():
    """The replay property specifically for a store that holds an unresolved conflict (a write
    under a conflict_key, with the original key's live value unmoved): rebuilt from writes, the
    rebuilt store must still show both the original value and the conflicting candidate."""
    store = _fresh_store(value="the original fact")
    queue, conflicts = ReviewQueue(), helpers.ConflictLog()
    result = helpers.reconcile(
        "e",
        "k",
        "a contradicting statement",
        _answer(CONTRA, 0.8),
        0.5,
        store,
        queue=queue,
        conflicts=conflicts,
    )
    rebuilt = helpers.rebuild_store_from_writes(store.writes())
    assert rebuilt.get("k") == "the original fact"
    assert rebuilt.get(result.conflict_key) == "a contradicting statement"
    assert rebuilt.snapshot() == store.snapshot()


def test_replaying_a_delete_in_the_history_round_trips_too():
    """`rebuild_store_from_writes` must handle a tombstoned record correctly, even though
    `reconcile` itself never deletes -- a `Store` used by this recipe can still hold a `delete`
    from elsewhere (for example a human correction applied directly), and the replay helper's
    job is to reproduce ANY write history, not only the ones `reconcile` itself produces."""
    store = _fresh_store(value="v1")
    store.delete("k", writer="rule:expire", step=1)
    store.put("k", "v2", writer="rule:restate", step=2)
    rebuilt = helpers.rebuild_store_from_writes(store.writes())
    assert rebuilt.snapshot() == store.snapshot()
    assert rebuilt.to_dicts() == store.to_dicts()


def test_reconcile_never_calls_store_delete():
    """A mutation-style structural guard: `reconcile` must never remove a live key from the
    store, for any outcome. A `Store` raises `StoreError` if something tries to delete a key
    that is not live; this test instead proves the stronger property directly, by checking that
    every key ever written during a full outcome sweep is STILL live at the end (nothing this
    module writes is ever later tombstoned), which would be false if any branch called
    `store.delete`."""
    store = _fresh_store(value="base")
    queue, conflicts = ReviewQueue(), helpers.ConflictLog()
    written_keys = {"k"}
    for i, outcome in enumerate(helpers.RECONCILE_OPTIONS, start=1):
        result = helpers.reconcile(
            f"e{i}",
            "k",
            f"statement {i}",
            _answer(outcome, 0.9),
            0.5,
            store,
            queue=queue,
            conflicts=conflicts,
            step=i,
        )
        if result.conflict_key:
            written_keys.add(result.conflict_key)
    for key in written_keys:
        assert key in store  # live, never tombstoned
    with pytest.raises(StoreError):
        store.get("no-such-key")  # sanity: StoreError is for a genuinely absent key, not this


# --------------------------------------------------------------------------------------------
# Evaluation shape: the selective view uses the confidence gate alone (no further branch), so
# evaluate_selective is the right helper here, not evaluate_outcomes -- pin that this stays true.
# --------------------------------------------------------------------------------------------


def test_selective_view_agrees_with_reconcile_s_own_gate():
    """`evaluate_selective` reapplies `confidence >= threshold` itself rather than calling the
    rule (see its own docstring): that is only correct when the rule's one and only review
    branch is the confidence gate, with nothing else able to send an example to review. This
    test proves that is true of `reconcile`: for a grid of (outcome, confidence) pairs, whether
    `evaluate_selective` would count an example as answered agrees exactly with whether
    `reconcile` actually wrote anything or sent it to review."""
    threshold = 0.5
    for outcome in helpers.RECONCILE_OPTIONS:
        for p_max in (0.30, 0.45, 0.55, 0.70, 0.90):
            store = _fresh_store()
            queue, conflicts = ReviewQueue(), helpers.ConflictLog()
            answer = _answer(outcome, p_max)
            result = helpers.reconcile(
                "e", "k", "s", answer, threshold, store, queue=queue, conflicts=conflicts
            )
            selective = evaluate_selective([True], [answer.confidence], threshold)
            rule_answered = result.outcome is not None
            selective_answered = selective.n_answered == 1
            assert rule_answered == selective_answered, (outcome, p_max)
