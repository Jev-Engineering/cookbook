"""Tests for recipe 37's helpers. They load the helpers by file path."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from jev_cookbook import NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import (
    multilabel_from_noul,
    multilabel_metrics,
    pool_label_decisions,
    select_confidence_threshold,
    select_threshold,
)
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

DOMAINS = list(helpers.DOMAINS)
THRESHOLDS = {domain: 0.5 for domain in DOMAINS}  # a fixed, simple rule for the isolated tests


def answer(noul):
    return NoulAnswer(noul, Provenance.synthetic())


def answers(**by_domain):
    """``{domain: NoulAnswer}`` for every domain in DOMAINS; domains not passed default to a
    clear, confident "no" (0.05) so a test only has to name the domains it cares about. Every
    call names its positive domain(s) explicitly -- never a bare default that could silently
    mislabel a row (the fixture-shorthand rule: the label-bearing argument is required, never
    defaulted)."""
    return {domain: answer(by_domain.get(domain, 0.05)) for domain in DOMAINS}


# `helpers.CountingBackend` is the shared instrument the notebook also uses (not redefined
# here): one copy of this wrapper, used by both, so the notebook's own access-control proof and
# this test's are the same mechanism, not two implementations that could silently disagree.


# --------------------------------------------------------------------------------------------
# the questions
# --------------------------------------------------------------------------------------------


def test_questions_are_built_by_python():
    assert set(helpers.DOMAINS) == {"biomedical", "computational", "economics"}
    questions = helpers.build_questions()
    assert list(questions) == DOMAINS
    for domain in DOMAINS:
        question = questions[domain]
        assert question.type == "noul"
        assert isinstance(question.instructions, str) and question.instructions
        assert set(question.criteria) == {"true", "false"}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per
    # *accessible* example (every domain's Noul question is sent together); a restricted
    # example lists no key at all, because it is never decided.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        if helpers.is_accessible(example.fields["access"]):
            expected = (replay_key(helpers.build_state(example.fields), questions),)
        else:
            expected = ()
        assert example.replay_keys == expected


def test_the_state_hides_the_passage_id_and_the_access_classification():
    fields = {"passage_id": "RP-9", "text": "A fabricated passage.", "access": "open"}
    assert helpers.build_state(fields) == {"passage": "A fabricated passage."}


# --------------------------------------------------------------------------------------------
# tag_domains: the per-domain three-path rule, in isolation
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("domain", DOMAINS)
def test_a_confident_yes_is_tagged_yes_whatever_the_domain(domain):
    decisions = helpers.tag_domains(answers(**{domain: 0.90}), THRESHOLDS, confidence_gate=0.3)
    assert decisions[domain].outcome == helpers.YES
    assert domain in helpers.compose("x", decisions).tags
    assert helpers.compose("x", decisions).review == ()


@pytest.mark.parametrize("domain", DOMAINS)
def test_a_confident_no_is_tagged_no_whatever_the_domain(domain):
    decisions = helpers.tag_domains(answers(**{domain: 0.05}), THRESHOLDS, confidence_gate=0.3)
    assert decisions[domain].outcome == helpers.NO
    assert domain not in helpers.compose("x", decisions).tags
    assert helpers.compose("x", decisions).review == ()


@pytest.mark.parametrize("domain", DOMAINS)
def test_a_low_confidence_answer_is_sent_to_review_whatever_the_domain_or_business_tag(domain):
    # noul = 0.52: just above the 0.5 threshold (a "yes" by the business rule alone), but its
    # confidence |2*0.52 - 1| = 0.04 is well below any reasonable gate, so the three-path rule
    # must still send it to review rather than report it as a tag either way.
    decisions = helpers.tag_domains(answers(**{domain: 0.52}), THRESHOLDS, confidence_gate=0.3)
    assert decisions[domain].outcome == helpers.REVIEW
    assert decisions[domain].tag is True  # the business rule alone would have said yes
    assert domain not in helpers.compose("x", decisions).tags
    assert domain in helpers.compose("x", decisions).review


def test_the_business_threshold_is_inclusive():
    decisions = helpers.tag_domains(answers(biomedical=0.5), THRESHOLDS, confidence_gate=0.0)
    assert decisions["biomedical"].outcome == helpers.YES
    just_below = helpers.tag_domains(answers(biomedical=0.4999999), THRESHOLDS, confidence_gate=0.0)
    assert just_below["biomedical"].outcome == helpers.NO


def test_the_confidence_gate_is_inclusive():
    # noul = 0.75: |2*0.75 - 1| = 0.5 exactly.
    at_gate = helpers.tag_domains(answers(biomedical=0.75), THRESHOLDS, confidence_gate=0.5)
    assert at_gate["biomedical"].outcome == helpers.YES
    above_gate = helpers.tag_domains(
        answers(biomedical=0.75), THRESHOLDS, confidence_gate=0.5 + 1e-9
    )
    assert above_gate["biomedical"].outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_business_threshold_outside_zero_to_one_is_an_error(bad):
    bad_thresholds = {**THRESHOLDS, "biomedical": bad}
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.tag_domains(answers(), bad_thresholds, confidence_gate=0.3)


def test_thresholds_missing_a_domain_is_an_error():
    incomplete = {domain: 0.5 for domain in DOMAINS[:-1]}
    with pytest.raises(ValueError, match="exactly DOMAINS"):
        helpers.tag_domains(answers(), incomplete, confidence_gate=0.3)


def test_thresholds_with_an_unknown_domain_is_an_error():
    extra = {**THRESHOLDS, "not_a_domain": 0.5}
    with pytest.raises(ValueError, match="exactly DOMAINS"):
        helpers.tag_domains(answers(), extra, confidence_gate=0.3)


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_confidence_gate_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.tag_domains(answers(), THRESHOLDS, confidence_gate=bad)


def test_provenance_is_carried_from_the_answer_onto_the_tag():
    recorded = {
        domain: NoulAnswer(0.9, Provenance.recorded("jev-1.13.0", "2026-01-01"))
        if domain == "biomedical"
        else answer(0.05)
        for domain in DOMAINS
    }
    decisions = helpers.tag_domains(recorded, THRESHOLDS, confidence_gate=0.3)
    assert decisions["biomedical"].provenance == "recorded"
    assert decisions["computational"].provenance == "synthetic"


def test_tag_before_the_confidence_gate_matches_multilabel_from_noul():
    # decide_tags's .tag field (the business rule alone, before the confidence gate) must agree
    # with jev_cookbook.evaluation.multilabel_from_noul, since the notebook's "Evaluation"
    # section uses that shared helper to build the business-rule tag set and nothing here
    # should drift from it. confidence_gate=0.0 means nothing is sent to review, so .tag and
    # .outcome agree, which keeps this assertion directly checkable against compose() too.
    sample = answers(biomedical=0.9, computational=0.3, economics=0.6)
    decisions = helpers.tag_domains(sample, THRESHOLDS, confidence_gate=0.0)
    noul_by_domain = {domain: [sample[domain].noul] for domain in DOMAINS}
    predicted = multilabel_from_noul(noul_by_domain, THRESHOLDS)[0]
    assert {domain for domain in DOMAINS if decisions[domain].tag} == set(predicted)
    assert helpers.compose("x", decisions).tags == frozenset(predicted)


# --------------------------------------------------------------------------------------------
# compose(): the deterministic composition, and its own tests
# --------------------------------------------------------------------------------------------


def test_compose_can_tag_nothing_or_every_domain():
    all_no = helpers.tag_domains(answers(), THRESHOLDS, confidence_gate=0.3)
    assert helpers.compose("x", all_no).tags == frozenset()
    all_yes = helpers.tag_domains(
        answers(**{domain: 0.9 for domain in DOMAINS}), THRESHOLDS, confidence_gate=0.3
    )
    assert helpers.compose("x", all_yes).tags == frozenset(DOMAINS)


def test_compose_rejects_decisions_naming_the_wrong_domains():
    decisions = helpers.tag_domains(answers(), THRESHOLDS, confidence_gate=0.3)
    incomplete = {k: v for k, v in decisions.items() if k != "biomedical"}
    with pytest.raises(ValueError, match="exactly DOMAINS"):
        helpers.compose("x", incomplete)


def test_task_correct_matches_two_empty_sets():
    decisions = helpers.tag_domains(answers(), THRESHOLDS, confidence_gate=0.3)
    result = helpers.compose("x", decisions)
    assert result.tags == frozenset()
    assert helpers.task_correct(result, ())


@pytest.mark.parametrize("domain", DOMAINS)
def test_each_domain_is_independently_consequential_on_a_real_fixture(domain):
    """Rule: flipping one domain's stored decision must change at least one composed outcome,
    and the proof must come from a real committed fixture, not a fabricated answer built inside
    this test. ``v15-all-clean`` is a real row from fixtures/inputs.jsonl and
    fixtures/responses.json whose gold set is every domain and whose three stored answers are
    all confidently "yes": `tag_domains` reports YES on every domain for it today, and composing
    those three real decisions tags every domain. Swapping any ONE domain's real decision to NO
    (holding the other two exactly as decided) must remove exactly that domain from the composed
    tag set and change the composed result -- which is what makes that domain's own question
    load-bearing rather than redundant with the other two or with the task-level outcome."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = {e.id: e for e in load_inputs(RECIPE)}
    labels = load_labels(RECIPE)
    example = examples["v15-all-clean"]
    assert labels[example.id] == sorted(DOMAINS)  # the real gold set this fixture carries

    real_answers = backend.decide(helpers.build_state(example.fields), questions)
    decisions = helpers.tag_domains(real_answers, THRESHOLDS, confidence_gate=0.3)
    baseline = helpers.compose(example.id, decisions)
    assert decisions[domain].outcome == helpers.YES  # real, decided, not fabricated
    assert baseline.tags == frozenset(DOMAINS)

    flipped = dict(decisions)
    flipped[domain] = replace(decisions[domain], tag=False, outcome=helpers.NO)
    mutated = helpers.compose(example.id, flipped)
    assert domain not in mutated.tags
    assert mutated.tags != baseline.tags
    assert helpers.task_correct(mutated, labels[example.id]) != helpers.task_correct(
        baseline, labels[example.id]
    )


# --------------------------------------------------------------------------------------------
# access control: filtered before any request, and never in the output
# --------------------------------------------------------------------------------------------


def test_is_accessible_rejects_an_unknown_classification():
    with pytest.raises(ValueError, match="open.*restricted|restricted.*open"):
        helpers.is_accessible("secret")


def test_accessible_and_restricted_examples_partition_the_input():
    class _Row:
        def __init__(self, id_, access):
            self.id = id_
            self.fields = {"access": access}

    rows = [_Row("a", "open"), _Row("b", "restricted"), _Row("c", "open")]
    accessible = helpers.accessible_examples(rows)
    restricted = helpers.restricted_examples(rows)
    assert [r.id for r in accessible] == ["a", "c"]
    assert [r.id for r in restricted] == ["b"]
    assert {r.id for r in accessible} | {r.id for r in restricted} == {"a", "b", "c"}


def test_a_restricted_passage_is_never_sent():
    """The hard half of the access-control proof (CONTRIBUTING.md section 3's access-control
    requirement): not merely that a restricted passage's text never appears in the output
    (checkable from committed artefacts alone -- see the next test), but that Python never
    issues a request containing it in the first place. This instruments the actual decide path
    (`helpers.decide_passages`, the one function this recipe routes every request through) with
    a counting wrapper and asserts there is exactly one request per accessible passage and zero
    requests whose state is a restricted passage's -- rather than inferring "never sent" from
    where the filter happens to sit in the code.

    Deleting the ``accessible_examples(examples)`` call inside `decide_passages` (replacing it
    with the bare `examples`) makes this test fail: that substitution was run by hand while
    writing this test. Against the fixtures as committed, where no restricted passage has a
    stored response, the failure is a `ReplayMiss` whose state is `v17-restricted`'s own text
    verbatim -- attempting to send a passage with no stored answer fails loudly rather than
    silently succeeding. That failure's *shape* depends on the fixtures (a world where every
    restricted passage also had a stored response would raise nothing); the `leaked` assertion
    below is what holds either way, which is why it is checked, and named, before the plain
    count comparison that follows it.
    """
    counting = helpers.CountingBackend(get_backend(fixtures=responses_path(RECIPE)))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    candidates = [e for e in examples if e.split not in ("train", "demo")]
    restricted = helpers.restricted_examples(candidates)
    accessible = helpers.accessible_examples(candidates)
    assert restricted, "fixtures must include at least one restricted passage"
    assert accessible, "fixtures must include at least one accessible passage"

    decisions = helpers.decide_passages(candidates, counting, questions)

    # The identifying check runs FIRST: if a restricted passage's state is ever sent, this
    # names it directly. A world where every restricted passage also has a stored response (so
    # no ReplayMiss is reachable) would otherwise fail on the count assertion below first, with
    # no passage named at all -- `len(counting.sent_states) == len(accessible)` alone cannot
    # say which extra request was the problem, only that there was one.
    restricted_states = {e.id: helpers.build_state(e.fields) for e in restricted}
    leaked = [eid for eid, state in restricted_states.items() if state in counting.sent_states]
    assert not leaked, f"a restricted passage's state was sent to decide(): {leaked}"

    assert len(counting.sent_states) == len(accessible)
    assert set(decisions) == {e.id for e in accessible}


def test_a_restricted_passage_never_appears_in_the_composed_output():
    """The other half of the proof: checkable from committed artefacts alone. No restricted
    passage's id appears in any composed tag set, any review list, or the decisions dict
    `decide_passages` returns."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    candidates = [e for e in examples if e.split not in ("train", "demo")]
    restricted_ids = {e.id for e in helpers.restricted_examples(candidates)}
    assert restricted_ids

    decisions = helpers.decide_passages(candidates, backend, questions)
    assert not (set(decisions) & restricted_ids)

    results = {
        eid: helpers.compose(eid, helpers.tag_domains(answer_set, THRESHOLDS, 0.3))
        for eid, answer_set in decisions.items()
    }
    assert not (set(results) & restricted_ids)
    for eid in results:
        assert eid not in restricted_ids  # no composed result belongs to a restricted passage


# --------------------------------------------------------------------------------------------
# stored answers are not all right (the strong form)
# --------------------------------------------------------------------------------------------


def test_stored_answers_are_not_all_right():
    """A wrong (passage, domain) pair anywhere is a weak guard: it would still pass even if the
    confidence gate caught every mistake, which would hide the exact lesson this fixture set
    exists to teach. Re-derive both frozen settings the way the notebook does -- the three
    per-domain business thresholds by F1 on `validation`, then the pooled confidence gate at
    `min_coverage=0.7` over every (passage, domain) pair -- and require a wrong `test` pair at
    or above that gate: a mistake it would still let through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    candidates = [e for e in examples if e.split not in ("train", "demo")]
    accessible = helpers.accessible_examples(candidates)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)

    validation = [e for e in accessible if e.split == "validation" and e.id in labels]
    val_gold_by_domain = {d: [d in labels[e.id] for e in validation] for d in DOMAINS}
    val_noul_by_domain = {d: [decide(e)[d].noul for e in validation] for d in DOMAINS}
    thresholds = {
        d: select_threshold(val_gold_by_domain[d], val_noul_by_domain[d], objective="f1")
        for d in DOMAINS
    }
    val_correct, val_confidence, _ = pool_label_decisions(
        [e.id for e in validation], DOMAINS, val_gold_by_domain, val_noul_by_domain, thresholds
    )
    confidence_gate = select_confidence_threshold(val_correct, val_confidence, min_coverage=0.70)

    test = [e for e in accessible if e.split == "test" and e.id in labels]
    test_gold_by_domain = {d: [d in labels[e.id] for e in test] for d in DOMAINS}
    test_noul_by_domain = {d: [decide(e)[d].noul for e in test] for d in DOMAINS}
    test_correct, test_confidence, test_keys = pool_label_decisions(
        [e.id for e in test], DOMAINS, test_gold_by_domain, test_noul_by_domain, thresholds
    )
    wrong_and_confident = [
        key
        for key, ok, conf in zip(test_keys, test_correct, test_confidence, strict=True)
        if not ok and conf >= confidence_gate
    ]
    assert wrong_and_confident, "expected at least one confidently wrong (passage, domain) pair"


# --------------------------------------------------------------------------------------------
# the threshold-selection objective is pinned (M3): a swap that keeps every other test and
# guard check green must still turn something here red
# --------------------------------------------------------------------------------------------


def test_the_threshold_objective_is_pinned():
    """Pin the per-domain business-threshold objective (`select_threshold(...,
    objective="f1")`) and the pooled confidence-gate objective
    (`select_confidence_threshold(..., min_coverage=0.70)`) to the specific numbers they
    produce on real fixtures, so a change to either objective or parameter -- even one that
    leaves every other test and guard check in this recipe green -- is caught here. Measured:
    swapping the gate's objective to `target_accuracy=...`-style selection, or changing
    `min_coverage`, changes the resulting frozen numbers asserted below."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    candidates = [e for e in examples if e.split not in ("train", "demo")]
    accessible = helpers.accessible_examples(candidates)
    validation = [e for e in accessible if e.split == "validation"]

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)

    val_gold_by_domain = {d: [d in labels[e.id] for e in validation] for d in DOMAINS}
    val_noul_by_domain = {d: [decide(e)[d].noul for e in validation] for d in DOMAINS}
    thresholds = {
        d: select_threshold(val_gold_by_domain[d], val_noul_by_domain[d], objective="f1")
        for d in DOMAINS
    }
    assert thresholds == {"biomedical": 0.8, "computational": 0.79, "economics": 0.8}

    val_correct, val_confidence, _ = pool_label_decisions(
        [e.id for e in validation], DOMAINS, val_gold_by_domain, val_noul_by_domain, thresholds
    )
    confidence_gate = select_confidence_threshold(val_correct, val_confidence, min_coverage=0.70)
    assert confidence_gate == pytest.approx(0.6399999999999999)


def test_the_notebooks_threshold_objective_matches_this_files_pinned_keywords():
    """Nothing ties a notebook cell's source to an importable value: an edit that changed only
    the notebook's own objective or parameter (swapping `objective="f1"` for `"accuracy"`, or
    `min_coverage=0.70` for a different value) would otherwise leave every test in this file
    green while the notebook ran a different selection than the one they describe. Parse the
    committed notebook's own cells and pin the exact keyword text, not only the value it
    produces."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cells = {c.get("id"): "".join(c["source"]) for c in notebook["cells"]}
    assert 'objective="f1"' in cells["python-thresholds"]
    assert "min_coverage=0.70" in cells["python-cutoff-choose"]


# --------------------------------------------------------------------------------------------
# a per-domain F1 actually moves when a real wrong answer is corrected (M4): the
# consequentiality claim in the notebook's "Evaluation" section needs a test that computes an
# F1, not only one that flips a DomainTag's outcome
# --------------------------------------------------------------------------------------------


def _test_noul_and_gold(backend, questions, labels, accessible):
    validation = [e for e in accessible if e.split == "validation"]
    test = [e for e in accessible if e.split == "test"]

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)

    val_gold_by_domain = {d: [d in labels[e.id] for e in validation] for d in DOMAINS}
    val_noul_by_domain = {d: [decide(e)[d].noul for e in validation] for d in DOMAINS}
    thresholds = {
        d: select_threshold(val_gold_by_domain[d], val_noul_by_domain[d], objective="f1")
        for d in DOMAINS
    }
    test_noul_by_domain = {d: [decide(e)[d].noul for e in test] for d in DOMAINS}
    test_gold_sets = [frozenset(labels[e.id]) for e in test]
    return test, thresholds, test_noul_by_domain, test_gold_sets


@pytest.mark.parametrize(
    "example_id, domain, corrected_noul",
    [
        ("t19-economics-biomedical-wrong", "biomedical", 0.10),
        ("t20-economics-computational-wrong", "computational", 0.10),
        ("t04-biomedical-lookalike", "economics", 0.10),
    ],
)
def test_correcting_a_real_wrong_answer_changes_its_domains_f1(example_id, domain, corrected_noul):
    """The notebook's "Evaluation" section claims that each of the three domains' `test` F1 is
    falsifiable: flipping any one of the real, committed wrong stored probabilities named there
    to the other side of its domain's threshold would change that domain's own F1. This test is
    what actually establishes that claim by computing `multilabel_metrics` twice -- once on the
    real stored `test` probabilities, once with exactly one real row's one probability
    corrected to the right side of its domain's frozen threshold -- and asserting the resulting
    F1 differs, for each of the three domains in turn. (`tests/test_helpers.py`'s own
    `test_each_domain_is_independently_consequential_on_a_real_fixture` proves a related but
    different claim -- that `compose`'s tag set changes -- and does not itself compute an F1;
    this test is the one the notebook's F1 claim actually needs.)"""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    candidates = [e for e in examples if e.split not in ("train", "demo")]
    accessible = helpers.accessible_examples(candidates)

    test, thresholds, test_noul_by_domain, test_gold_sets = _test_noul_and_gold(
        backend, questions, labels, accessible
    )

    def f1_for(noul_by_domain):
        predicted = multilabel_from_noul(noul_by_domain, thresholds)
        metrics = multilabel_metrics(test_gold_sets, predicted, labels=DOMAINS)
        return metrics["per_label"][domain].f1

    baseline_f1 = f1_for(test_noul_by_domain)

    corrected = {d: list(values) for d, values in test_noul_by_domain.items()}
    index = next(i for i, e in enumerate(test) if e.id == example_id)
    corrected[domain][index] = corrected_noul
    corrected_f1 = f1_for(corrected)

    assert corrected_f1 != pytest.approx(baseline_f1), (
        f"correcting {example_id}'s {domain} probability did not change {domain}'s own F1"
    )


def test_t04s_economics_probability_sits_exactly_at_the_frozen_threshold():
    """`t04-biomedical-lookalike`'s false positive is not merely wrong, it is wrong by the
    narrowest possible margin: its stored `economics` probability (0.80) sits exactly at the
    frozen `economics` threshold (also 0.80), the inclusive boundary `tag_domains`'s `noul >=
    threshold` comparison resolves in favor of a tag. Pin both numbers directly, on the real
    committed fixture, so a future fixture edit that moves either one off the boundary -- and
    so changes the lesson this specific row teaches -- is caught here rather than silently."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    candidates = [e for e in examples if e.split not in ("train", "demo")]
    accessible = helpers.accessible_examples(candidates)
    validation = [e for e in accessible if e.split == "validation"]
    val_gold_by_domain = {d: [d in labels[e.id] for e in validation] for d in DOMAINS}
    val_noul_by_domain = {
        d: [backend.decide(helpers.build_state(e.fields), questions)[d].noul for e in validation]
        for d in DOMAINS
    }
    threshold = select_threshold(
        val_gold_by_domain["economics"], val_noul_by_domain["economics"], objective="f1"
    )
    assert threshold == 0.8

    t04 = next(e for e in accessible if e.id == "t04-biomedical-lookalike")
    t04_economics = backend.decide(helpers.build_state(t04.fields), questions)["economics"].noul
    assert t04_economics == 0.8
    assert t04_economics == threshold
    assert "economics" not in labels["t04-biomedical-lookalike"]  # the tag is a false positive
