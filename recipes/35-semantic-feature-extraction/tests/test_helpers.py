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
from jev_cookbook.evaluation import select_threshold
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
    # example; test_naive_bayes_matches_hand_computed_posterior below checks they can
    # genuinely disagree.
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
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    train_targets = [labels[e.id]["escalate"] for e in select_split(examples, "train")]
    baseline = helpers.fit_majority_baseline(train_targets)
    n_true = sum(train_targets)
    n_false = len(train_targets) - n_true
    assert baseline.majority == (n_true >= n_false)
    # Not construction-perfect: the two classes are not tied and neither is unanimous, so the
    # baseline's own accuracy on train itself is below 1.0: what would make this number come
    # out differently is simply a different mix of train examples, which is worth naming beside
    # a number that otherwise looks construction-perfect.
    assert 0 < n_true < len(train_targets)


# --------------------------------------------------------------------------- the classifier


def test_naive_bayes_uses_a_fixed_never_tuned_smoothing_constant():
    assert helpers.LAPLACE_ALPHA == 1.0


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
    """Thresholds (chosen on validation) and a classifier (fit on train), from the real
    committed fixtures -- the same two frozen objects the notebook builds."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)

    def decide(e):
        return backend.decide(helpers.build_state(e.fields), questions)

    validation = select_split(examples, "validation")
    val_answers = {e.id: decide(e) for e in validation}
    thresholds = {
        name: select_threshold(
            [labels[e.id]["features"][name] for e in validation],
            [val_answers[e.id][name].noul for e in validation],
            "f1",
        )
        for name in EXPECTED_FEATURES
    }
    train = select_split(examples, "train")
    train_vectors = [
        helpers.feature_vector(helpers.compose_features(decide(e), thresholds)) for e in train
    ]
    train_targets = [labels[e.id]["escalate"] for e in train]
    model = helpers.fit_naive_bayes(train_vectors, train_targets)
    return thresholds, model, decide


@pytest.mark.parametrize("name", EXPECTED_FEATURES)
def test_each_feature_is_independently_consequential_for_the_trained_classifier(name):
    # Each proposition must be independently consequential: flipping one feature's own
    # composed bit, on a real committed fixture, must
    # change at least one composed outcome -- here, the trained classifier's predicted label,
    # the strongest form of "consequential" this recipe has (stronger than merely toggling the
    # feature's own tag, which is true by construction of compose_features). This fits the
    # classifier fresh from the committed train/validation fixtures, so an edit to either
    # split that removed the feature's effect would fail this test.
    thresholds, model, decide = _fit_from_fixtures()
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
    thresholds, model, decide = _fit_from_fixtures()
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


@pytest.mark.parametrize("name", EXPECTED_FEATURES)
def test_each_features_frozen_threshold_is_not_all_right_on_test(name):
    # Mirrors the notebook's own threshold selection: chosen on validation with select_threshold
    # (objective "f1"), then frozen and applied to test. A Noul has no confidence field
    # (CONTRIBUTING.md section 3), so unlike a confidence-gated recipe this is the plain
    # business-threshold comparison, not a separate review gate -- requiring a wrong test
    # answer here is what stands in for that recipe pattern's stronger guard: a fixture set
    # that is merely "not all correct" but happens to have every mistake land on the same side
    # of this frozen threshold as the gold label would still pass a weaker check.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)

    def noul(e):
        return backend.decide(helpers.build_state(e.fields), questions)[name].noul

    validation = select_split(examples, "validation")
    threshold = select_threshold(
        [labels[e.id]["features"][name] for e in validation],
        [noul(e) for e in validation],
        "f1",
    )
    test = select_split(examples, "test")
    wrong = [e.id for e in test if (noul(e) >= threshold) != labels[e.id]["features"][name]]
    assert wrong, f"{name}: expected at least one wrong test answer at the frozen threshold"
