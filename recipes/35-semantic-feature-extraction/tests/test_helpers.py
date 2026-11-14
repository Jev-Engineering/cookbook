"""Tests for recipe 35's helpers. They load the helpers by file path.

Three things this recipe's methodology depends on being frozen before any test-split number
is looked at -- the feature list, the split assignment and the baseline -- are pinned here
against literal expected values, so an edit to any of them fails a test rather than silently
producing a different reported number without anyone noticing the change.
"""

import math
from pathlib import Path

import pytest

from jev_cookbook import NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import pool_label_decisions, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# --------------------------------------------------------------------------- the feature list, frozen

EXPECTED_FEATURES = (
    "mentions_price",
    "expresses_frustration",
    "requests_refund_or_cancellation",
    "mentions_competitor",
    "reports_technical_issue",
    "expresses_satisfaction",
)


def test_the_feature_list_is_frozen():
    # A frozen thing nothing pins is not actually frozen: pinning the
    # exact tuple of names (not just the count) means adding, removing or reordering a feature
    # fails here, rather than silently producing a differently-shaped feature vector that every
    # other number in the notebook would still happily compute over.
    assert tuple(helpers.FEATURES) == EXPECTED_FEATURES
    for name in EXPECTED_FEATURES:
        assert isinstance(helpers.FEATURES[name], str) and helpers.FEATURES[name]


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert tuple(questions) == EXPECTED_FEATURES
    for name, statement in helpers.FEATURES.items():
        question = questions[name]
        assert question.instructions == statement
        assert question.criteria == {
            "true": statement,
            "false": "The feedback does not do this at all.",
        }


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# --------------------------------------------------------------------------- the split assignment, frozen

EXPECTED_TRAIN_IDS = frozenset({f"tr{n:02d}" for n in range(1, 17)})
EXPECTED_VALIDATION_IDS = frozenset({f"v{n:02d}" for n in range(1, 17)})
EXPECTED_TEST_IDS = frozenset({f"t{n:02d}" for n in range(1, 17)})
EXPECTED_DEMO_IDS = frozenset({"d01", "d02"})


def test_the_split_assignment_is_frozen():
    # Pins which examples sit in which split, not merely how many: swapping one id between
    # validation and test (which would silently change which examples a threshold is chosen
    # from, and which it is later evaluated on) fails this test even though the counts alone
    # would not catch it.
    examples = load_inputs(RECIPE)
    by_split = {
        "train": EXPECTED_TRAIN_IDS,
        "validation": EXPECTED_VALIDATION_IDS,
        "test": EXPECTED_TEST_IDS,
        "demo": EXPECTED_DEMO_IDS,
    }
    for split, expected_ids in by_split.items():
        ids = frozenset(e.id for e in select_split(examples, split))
        assert ids == expected_ids, f"{split} split ids changed"
    assert len(examples) == 50


def test_every_train_validation_and_test_example_has_both_gold_labels():
    # Two independent gold sets, each from an explicit argument, never one derived
    # from the other. This checks both are present (and shaped right) for every scored
    # example; test_every_feature_has_all_four_present_absent_by_escalate_cases below checks
    # they can genuinely disagree (every feature has a committed example where it is True with
    # escalate False and one where it is False with escalate True, so escalate is provably not
    # a function of the six features).
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    for split in ("train", "validation", "test"):
        for e in select_split(examples, split):
            label = labels[e.id]
            assert set(label) == {"features", "escalate"}
            assert set(label["features"]) == set(EXPECTED_FEATURES)
            assert isinstance(label["escalate"], bool)
            for v in label["features"].values():
                assert isinstance(v, bool)
    for e in select_split(examples, "demo"):
        assert e.id not in labels


# --------------------------------------------------------------------------- no feature is a mechanical
# --------------------------------------------------------------------------- function of another


def test_no_feature_is_the_complement_or_duplicate_of_another_on_committed_fixtures():
    # A multi-label Noul set where one label is the mechanical complement
    # of another cannot change any composed outcome by itself, however its own test looks.
    # Checked directly against every scored fixture's gold feature labels, not merely argued
    # in prose.
    labels = load_labels(RECIPE)
    scored = [e for e in load_inputs(RECIPE) if e.split in ("train", "validation", "test")]
    assert scored  # sanity: the check below is vacuous on an empty list
    columns = {name: [labels[e.id]["features"][name] for e in scored] for name in EXPECTED_FEATURES}
    for i, a in enumerate(EXPECTED_FEATURES):
        for b in EXPECTED_FEATURES[i + 1 :]:
            assert columns[a] != columns[b], f"{a} duplicates {b} on every committed example"
            assert columns[a] != [not v for v in columns[b]], f"{a} is the complement of {b}"


def test_every_feature_has_all_four_present_absent_by_escalate_cases():
    # "Cover every feature's four cases individually": present/absent crossed with the
    # classifier label it should move, across the fixtures as a whole (train, validation and
    # test together) -- not necessarily within one split. This is the mechanical form of the
    # coverage claim the notebook and README state in prose.
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    scored = [e for e in examples if e.split in ("train", "validation", "test")]
    for name in EXPECTED_FEATURES:
        cases = {(labels[e.id]["features"][name], labels[e.id]["escalate"]) for e in scored}
        assert cases == {(True, True), (True, False), (False, True), (False, False)}, (
            f"{name} is missing a (present, escalate) combination: has {sorted(cases)}"
        )


# --------------------------------------------------------------------------- the deterministic composition


def _answers(values: dict[str, float]) -> dict[str, NoulAnswer]:
    return {name: NoulAnswer(p, Provenance.synthetic()) for name, p in values.items()}


_FLAT_THRESHOLDS = {name: 0.5 for name in EXPECTED_FEATURES}


def test_compose_features_applies_each_threshold_independently():
    # Flipping one feature's own answer must change only that feature's own entry: the
    # composition is six independent comparisons, not a rule that lets one answer influence
    # another's tag.
    base = _answers({name: 0.2 for name in EXPECTED_FEATURES})
    decisions = helpers.compose_features(base, _FLAT_THRESHOLDS)
    assert all(not d.present for d in decisions.values())
    for name in EXPECTED_FEATURES:
        flipped = dict(base)
        flipped[name] = NoulAnswer(0.8, Provenance.synthetic())
        decisions = helpers.compose_features(flipped, _FLAT_THRESHOLDS)
        for other in EXPECTED_FEATURES:
            assert decisions[other].present == (other == name), (
                f"flipping {name!r} changed {other!r}'s composed tag"
            )


@pytest.mark.parametrize("name", EXPECTED_FEATURES)
def test_compose_features_threshold_crossing_per_feature(name):
    # Each of the six features gets its own test, failing for its own cause: a threshold of
    # 0.60 reads 0.59 as absent and 0.61 as present, for this feature and no other.
    thresholds = dict(_FLAT_THRESHOLDS, **{name: 0.60})
    answers = _answers({n: 0.59 for n in EXPECTED_FEATURES})
    assert helpers.compose_features(answers, thresholds)[name].present is False
    answers[name] = NoulAnswer(0.61, Provenance.synthetic())
    assert helpers.compose_features(answers, thresholds)[name].present is True


def test_compose_features_rejects_a_threshold_set_that_is_not_exactly_the_features():
    answers = _answers({name: 0.5 for name in EXPECTED_FEATURES})
    with pytest.raises(ValueError):
        helpers.compose_features(answers, {n: 0.5 for n in EXPECTED_FEATURES[:-1]})
    with pytest.raises(ValueError):
        helpers.compose_features(answers, dict(_FLAT_THRESHOLDS, extra=0.5))


def test_compose_features_rejects_an_out_of_range_threshold():
    answers = _answers({name: 0.5 for name in EXPECTED_FEATURES})
    bad = dict(_FLAT_THRESHOLDS)
    bad[EXPECTED_FEATURES[0]] = 1.5
    with pytest.raises(ValueError):
        helpers.compose_features(answers, bad)


def test_feature_vector_is_fixed_order():
    decisions = helpers.compose_features(
        _answers({name: 0.9 if i == 0 else 0.1 for i, name in enumerate(EXPECTED_FEATURES)}),
        _FLAT_THRESHOLDS,
    )
    vector = helpers.feature_vector(decisions)
    assert vector == (True,) + (False,) * (len(EXPECTED_FEATURES) - 1)


# --------------------------------------------------------------------------- the fixed baseline, frozen


def test_majority_baseline_predicts_the_majority_class_of_train():
    assert helpers.fit_majority_baseline([True, True, False]).majority is True
    assert helpers.fit_majority_baseline([True, False, False]).majority is False


def test_majority_baseline_ties_go_to_true():
    # The tie rule is a stated choice, not an accident of argmax order: pinned directly.
    assert helpers.fit_majority_baseline([True, False]).majority is True


def test_majority_baseline_never_reads_a_feature_vector():
    baseline = helpers.fit_majority_baseline([True, False, False])
    predictions = helpers.predict_majority_baseline(baseline, 3)
    assert predictions == [False, False, False]


def test_majority_baseline_rejects_empty_targets():
    with pytest.raises(ValueError):
        helpers.fit_majority_baseline([])


def test_the_baseline_fit_on_committed_train_matches_trains_own_majority():
    # A literal expected value, not a restatement of fit_majority_baseline's own
    # n_true >= n_false expression: committed train is 7 escalate / 9 not, so the majority is
    # False. test_majority_baseline_ties_go_to_true (above) is what proves the tie rule itself;
    # this one is not tied (9 != 7), so it could not catch a >= -> > regression on its own.
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    train_targets = [labels[e.id]["escalate"] for e in select_split(examples, "train")]
    assert (sum(train_targets), len(train_targets)) == (7, 16)
    baseline = helpers.fit_majority_baseline(train_targets)
    assert baseline.majority is False
    # The pinned pair above is also what carries "not construction-perfect": 7 escalate of 16
    # means the two classes are neither tied nor unanimous, so the baseline's own accuracy on
    # train is below 1.0. A different mix of train examples is all it would take to move that,
    # which is worth naming beside a number that otherwise looks construction-perfect.


# --------------------------------------------------------------------------- the classifier


def test_naive_bayes_uses_a_fixed_never_tuned_smoothing_constant():
    assert helpers.LAPLACE_ALPHA == 1.0


# The nine candidate smoothing constants the `python-md` sweep sentence is about. The grid is
# spelled here rather than only in prose, so the sentence has something that fails when it stops
# being true of the committed fixtures.
ALPHA_GRID = (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 5.0, 10.0)


def test_the_frozen_smoothing_constant_was_not_picked_by_looking_at_test():
    """`python-md` makes three claims about ``LAPLACE_ALPHA``, each a property of the committed
    fixtures rather than of any function here, and so each silently falsifiable by a fixture
    edit: that it is among the best of nine candidates on ``test``, that it is NOT uniquely best
    there (larger constants tie it), and that the constants ``validation``'s own sweep favours
    are different ones that score worse on ``test``. All three are recomputed from the committed
    fixtures and asserted, rather than left to the sentence."""
    assert len(ALPHA_GRID) == 9
    assert helpers.LAPLACE_ALPHA in ALPHA_GRID
    thresholds, _confidence_gate, _model, decide = _fit_from_fixtures()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)

    def rows(split):
        split_examples = select_split(examples, split)
        vectors = [
            helpers.feature_vector(helpers.compose_features(decide(e), thresholds))
            for e in split_examples
        ]
        return vectors, [labels[e.id]["escalate"] for e in split_examples]

    train_vectors, train_targets = rows("train")
    val_vectors, val_targets = rows("validation")
    test_vectors, test_targets = rows("test")

    def accuracy_at(alpha, vectors, targets):
        model = helpers.fit_naive_bayes(train_vectors, train_targets, alpha=alpha)
        predicted = [helpers.predict_naive_bayes(model, vector) for vector in vectors]
        return sum(p == t for p, t in zip(predicted, targets, strict=True)) / len(targets)

    on_test = {alpha: accuracy_at(alpha, test_vectors, test_targets) for alpha in ALPHA_GRID}
    on_validation = {alpha: accuracy_at(alpha, val_vectors, val_targets) for alpha in ALPHA_GRID}
    frozen = helpers.LAPLACE_ALPHA

    assert on_test[frozen] == max(on_test.values())
    tied_on_test = [a for a, value in on_test.items() if value == on_test[frozen]]
    assert len(tied_on_test) > 1, tied_on_test  # best on test, but not uniquely so
    favoured = [a for a, value in on_validation.items() if value == max(on_validation.values())]
    assert len(favoured) == 2, favoured
    assert frozen not in favoured, favoured
    for alpha in favoured:
        assert on_test[alpha] < on_test[frozen], (alpha, on_test)


def test_naive_bayes_matches_a_hand_computed_posterior():
    # A tiny, fully worked dataset: two features, four examples, by hand.
    #   vector  target
    #   (T, F)  True
    #   (T, T)  True
    #   (F, F)  False
    #   (F, T)  False
    # class True: prior 2/4; P(f0=T|True) = (2+1)/(2+2) = 0.75; P(f1=T|True) = (1+1)/(2+2) = 0.50
    # class False: prior 2/4; P(f0=T|False) = (0+1)/(2+2) = 0.25; P(f1=T|False) = (1+1)/(2+2) = 0.50
    vectors = [(True, False), (True, True), (False, False), (False, True)]
    targets = [True, True, False, False]
    model = helpers.fit_naive_bayes(vectors, targets, feature_names=("f0", "f1"))
    assert model.log_prior[True] == pytest.approx(math.log(0.5))
    assert model.log_prior[False] == pytest.approx(math.log(0.5))
    assert model.log_true[True] == pytest.approx((math.log(0.75), math.log(0.50)))
    assert model.log_false[True] == pytest.approx((math.log(0.25), math.log(0.50)))
    assert model.log_true[False] == pytest.approx((math.log(0.25), math.log(0.50)))
    assert model.log_false[False] == pytest.approx((math.log(0.75), math.log(0.50)))
    # (T, F): log-odds True = log(.5)+log(.75)+log(.50); False = log(.5)+log(.25)+log(.50)
    # True has the higher f0 term and an equal f1 term, so True wins.
    assert helpers.predict_naive_bayes(model, (True, False)) is True
    # (F, T): mirror image on f0, equal f1 -> False wins.
    assert helpers.predict_naive_bayes(model, (False, True)) is False


def test_naive_bayes_predict_ties_go_to_true():
    # Balanced priors (two examples per class) and a feature equally likely to read True under
    # either class (one of each class's two rows reads True): the posteriors tie exactly
    # (log(0.5) + log(0.5) on both sides), and the rule names which way a tie falls.
    vectors = [(True,), (False,), (True,), (False,)]
    targets = [True, True, False, False]
    model = helpers.fit_naive_bayes(vectors, targets, feature_names=("f0",))
    assert model.log_prior[True] == pytest.approx(model.log_prior[False])
    assert model.log_true[True] == pytest.approx(model.log_true[False])
    assert helpers.predict_naive_bayes(model, (True,)) is True


def test_naive_bayes_rejects_a_train_split_missing_a_class():
    with pytest.raises(ValueError):
        helpers.fit_naive_bayes([(True,), (False,)], [True, True], feature_names=("f0",))


def test_naive_bayes_rejects_empty_input():
    with pytest.raises(ValueError):
        helpers.fit_naive_bayes([], [], feature_names=("f0",))


def test_naive_bayes_is_deterministic():
    vectors = [(True, False), (True, True), (False, False), (False, True), (True, True)]
    targets = [True, True, False, False, True]
    first = helpers.fit_naive_bayes(vectors, targets, feature_names=("f0", "f1"))
    second = helpers.fit_naive_bayes(vectors, targets, feature_names=("f0", "f1"))
    assert first == second
    for v in ((True, True), (False, False), (True, False), (False, True)):
        assert helpers.predict_naive_bayes(first, v) == helpers.predict_naive_bayes(second, v)


def test_naive_bayes_predict_rejects_a_mismatched_vector_length():
    model = helpers.fit_naive_bayes([(True,), (False,)], [True, False], feature_names=("f0",))
    with pytest.raises(ValueError):
        helpers.predict_naive_bayes(model, (True, False))


# --------------------------------------------------------------------------- consequentiality, end to end


def _fit_from_fixtures():
    """Thresholds, the pooled confidence gate (both chosen on validation) and a classifier (fit
    on train), from the real committed fixtures -- the same frozen objects the notebook builds,
    via the same helpers.select_feature_thresholds / helpers.select_pooled_confidence_gate the
    notebook calls, so a test here and the notebook's own choice cannot silently diverge."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)

    def decide(e):
        return backend.decide(helpers.build_state(e.fields), questions)

    validation = select_split(examples, "validation")
    val_answers = {e.id: decide(e) for e in validation}
    val_gold_by_label = {
        name: [labels[e.id]["features"][name] for e in validation] for name in EXPECTED_FEATURES
    }
    val_noul_by_label = {
        name: [val_answers[e.id][name].noul for e in validation] for name in EXPECTED_FEATURES
    }
    thresholds = helpers.select_feature_thresholds(val_gold_by_label, val_noul_by_label)
    confidence_gate = helpers.select_pooled_confidence_gate(
        [e.id for e in validation], val_gold_by_label, val_noul_by_label, thresholds
    )
    train = select_split(examples, "train")
    train_vectors = [
        helpers.feature_vector(helpers.compose_features(decide(e), thresholds)) for e in train
    ]
    train_targets = [labels[e.id]["escalate"] for e in train]
    model = helpers.fit_naive_bayes(train_vectors, train_targets)
    return thresholds, confidence_gate, model, decide


@pytest.mark.parametrize("name", EXPECTED_FEATURES)
def test_each_feature_is_independently_consequential_for_the_trained_classifier(name):
    # Each proposition must be independently consequential: flipping one feature's own
    # composed bit, on a real committed fixture, must
    # change at least one composed outcome -- here, the trained classifier's predicted label,
    # the strongest form of "consequential" this recipe has (stronger than merely toggling the
    # feature's own tag, which is true by construction of compose_features). This fits the
    # classifier fresh from the committed train/validation fixtures, so an edit to either
    # split that removed the feature's effect would fail this test.
    thresholds, _confidence_gate, model, decide = _fit_from_fixtures()
    examples = load_inputs(RECIPE)
    candidates = select_split(examples, "validation") + select_split(examples, "test")
    for e in candidates:
        vector = helpers.feature_vector(helpers.compose_features(decide(e), thresholds))
        flipped = list(vector)
        j = EXPECTED_FEATURES.index(name)
        flipped[j] = not flipped[j]
        if helpers.predict_naive_bayes(model, vector) != helpers.predict_naive_bayes(
            model, tuple(flipped)
        ):
            return
    pytest.fail(f"flipping {name!r} alone never changed the trained classifier's prediction")


def test_classifier_and_baseline_disagree_on_at_least_one_real_test_example():
    # If they never disagreed, the comparison the notebook reports could not come out any
    # other way than "tied", and a comparison that could not come out any other way is worth
    # naming rather than presenting as a finding.
    thresholds, _confidence_gate, model, decide = _fit_from_fixtures()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    train_targets = [labels[e.id]["escalate"] for e in select_split(examples, "train")]
    baseline = helpers.fit_majority_baseline(train_targets)
    test = select_split(examples, "test")
    disagreements = [
        e.id
        for e in test
        if helpers.predict_naive_bayes(
            model, helpers.feature_vector(helpers.compose_features(decide(e), thresholds))
        )
        != baseline.majority
    ]
    assert disagreements, "the classifier never differs from the constant baseline on test"


# --------------------------------------------------------------------------- business thresholds are not
# --------------------------------------------------------------------------- all right on test


def _thresholds_from_validation(backend, questions, labels, validation):
    gold_by_label = {
        name: [labels[e.id]["features"][name] for e in validation] for name in EXPECTED_FEATURES
    }
    noul_by_label = {
        name: [
            backend.decide(helpers.build_state(e.fields), questions)[name].noul for e in validation
        ]
        for name in EXPECTED_FEATURES
    }
    return (
        gold_by_label,
        noul_by_label,
        helpers.select_feature_thresholds(gold_by_label, noul_by_label),
    )


@pytest.mark.parametrize("name", EXPECTED_FEATURES)
def test_each_features_frozen_threshold_is_not_all_right_on_test(name):
    # Mirrors the notebook's own threshold selection (helpers.select_feature_thresholds:
    # select_threshold on validation, objective "f1"), then frozen and applied to test. A Noul
    # has no confidence field (CONTRIBUTING.md section 3), so unlike a confidence-gated recipe
    # this is the plain business-threshold comparison, not a separate review gate -- requiring
    # a wrong test answer here is what stands in for that recipe pattern's stronger guard: a
    # fixture set that is merely "not all correct" but happens to have every mistake land on the
    # same side of this frozen threshold as the gold label would still pass a weaker check.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = select_split(examples, "validation")
    _gold_by_label, _noul_by_label, thresholds = _thresholds_from_validation(
        backend, questions, labels, validation
    )
    threshold = thresholds[name]

    def noul(e):
        return backend.decide(helpers.build_state(e.fields), questions)[name].noul

    test = select_split(examples, "test")
    wrong = [e.id for e in test if (noul(e) >= threshold) != labels[e.id]["features"][name]]
    assert wrong, f"{name}: expected at least one wrong test answer at the frozen threshold"


def test_the_scored_feature_pair_error_count_is_pinned():
    # README.md states how many (text, feature) pairs are wrong at the frozen business
    # thresholds, restricted to the two SCORED splits (validation and test; train fits the
    # classifier and is never scored, consistent with "N counts scored examples only"
    # elsewhere in this cookbook). That count is exactly the two pooled-accuracy complements
    # the notebook already prints (96 - correct, per split), so it is pinned here independently
    # through the same shared helper the notebook calls, not retyped by hand -- a fixture edit
    # that changed it would fail this test rather than leaving a stale number in prose.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = select_split(examples, "validation")
    val_gold_by_label, val_noul_by_label, thresholds = _thresholds_from_validation(
        backend, questions, labels, validation
    )
    val_correct, _c, _k = pool_label_decisions(
        [e.id for e in validation],
        list(EXPECTED_FEATURES),
        val_gold_by_label,
        val_noul_by_label,
        thresholds,
    )
    test = select_split(examples, "test")
    test_gold_by_label = {
        name: [labels[e.id]["features"][name] for e in test] for name in EXPECTED_FEATURES
    }
    test_noul_by_label = {
        name: [backend.decide(helpers.build_state(e.fields), questions)[name].noul for e in test]
        for name in EXPECTED_FEATURES
    }
    test_correct, _c2, _k2 = pool_label_decisions(
        [e.id for e in test],
        list(EXPECTED_FEATURES),
        test_gold_by_label,
        test_noul_by_label,
        thresholds,
    )
    wrong_validation = len(val_correct) - sum(val_correct)
    wrong_test = len(test_correct) - sum(test_correct)
    assert (wrong_validation, wrong_test) == (3, 6)
    assert wrong_validation + wrong_test == 9


# --------------------------------------------------------------------------- the confidence gate,
# --------------------------------------------------------------------------- a diagnostic alongside the vector


def test_confidence_outcome_names_review_below_the_gate():
    outcome, reason = helpers.confidence_outcome(0.5, 0.5)  # noul_confidence(0.5) == 0.0
    assert outcome == helpers.REVIEW
    assert outcome == "review"
    assert reason == "confidence below the threshold"


def test_confidence_outcome_names_confident_at_or_above_the_gate():
    outcome, reason = helpers.confidence_outcome(0.95, 0.5)  # noul_confidence(0.95) == 0.9
    assert outcome == helpers.CONFIDENT
    assert reason == "confidence at or above the threshold"


def test_confidence_outcome_rejects_out_of_range_input():
    with pytest.raises(ValueError):
        helpers.confidence_outcome(1.5, 0.5)
    with pytest.raises(ValueError):
        helpers.confidence_outcome(0.5, -0.1)


def test_confidence_outcome_boundary_counts_an_exact_match_as_confident():
    # Pins "<" rather than "<=": the committed pooled gate is 0.78, and noul_confidence(0.89)
    # is exactly 0.78 (|2*0.89 - 1|) -- the same value as the gate itself, and the value at
    # least one real committed test pair sits at. "At or above the threshold" (the reason
    # string's own wording) must count that exact match as confident, matching the ">="
    # convention select_threshold and evaluate_threshold both use for the business threshold
    # elsewhere in this file: a tie goes to the more automated outcome, not to review.
    outcome, reason = helpers.confidence_outcome(0.89, 0.78)
    assert outcome == helpers.CONFIDENT
    assert reason == "confidence at or above the threshold"
    # One tick below the gate: now it is a review.
    outcome, reason = helpers.confidence_outcome(0.885, 0.78)
    assert outcome == helpers.REVIEW


def test_confidence_outcome_never_changes_the_feature_vector():
    # The diagnostic is read-only with respect to the classifier's own input: compose_features
    # and feature_vector never call confidence_outcome, and a feature's business tag is the
    # same whatever confidence_outcome would separately report for it.
    answers = _answers({name: 0.95 for name in EXPECTED_FEATURES})
    decisions = helpers.compose_features(
        answers, dict(_FLAT_THRESHOLDS, **{EXPECTED_FEATURES[0]: 0.99})
    )
    # EXPECTED_FEATURES[0] is present=False here (0.95 < 0.99) despite being highly confident,
    # which is exactly the case confidence_outcome and compose_features must answer
    # independently: a confident answer on the wrong side of its own business threshold.
    assert decisions[EXPECTED_FEATURES[0]].present is False
    outcome, _reason = helpers.confidence_outcome(0.95, 0.5)
    assert outcome == helpers.CONFIDENT


def test_stored_answers_are_not_all_right():
    """Strong form: re-derive the pooled confidence gate independently from validation --
    pool_label_decisions then select_confidence_threshold, called directly here rather than
    through helpers.select_pooled_confidence_gate, so this test is a genuine second
    computation of the gate and not merely a call into the same production path the notebook
    uses -- and require a wrong, confidently-scored test (text, feature) decision at or above
    it, not merely "some wrong answer exists somewhere", which a gate that happened to catch
    every mistake would still pass."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = select_split(examples, "validation")
    val_gold_by_label, val_noul_by_label, val_thresholds = _thresholds_from_validation(
        backend, questions, labels, validation
    )
    val_correct, val_confidence, _val_keys = pool_label_decisions(
        [e.id for e in validation],
        list(EXPECTED_FEATURES),
        val_gold_by_label,
        val_noul_by_label,
        val_thresholds,
    )
    confidence_gate = select_confidence_threshold(val_correct, val_confidence, min_coverage=0.5)

    def decide(e):
        return backend.decide(helpers.build_state(e.fields), questions)

    test = select_split(examples, "test")
    test_gold_by_label = {
        name: [labels[e.id]["features"][name] for e in test] for name in EXPECTED_FEATURES
    }
    test_noul_by_label = {name: [decide(e)[name].noul for e in test] for name in EXPECTED_FEATURES}
    test_correct, test_confidence, test_keys = pool_label_decisions(
        [e.id for e in test],
        list(EXPECTED_FEATURES),
        test_gold_by_label,
        test_noul_by_label,
        val_thresholds,
    )
    wrong_above_gate = [
        key
        for key, correct, confidence in zip(test_keys, test_correct, test_confidence, strict=True)
        if confidence >= confidence_gate and not correct
    ]
    assert wrong_above_gate, "expected at least one wrong, confidently-scored test answer"
