"""Tests for recipe 37's helpers. They load the helpers by file path."""

from dataclasses import replace
from pathlib import Path

import pytest

from jev_cookbook import NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import (
    multilabel_from_noul,
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


class _CountingBackend:
    """Wraps a backend and records the state of every request it is actually asked to decide.
    Used only to prove what was sent, rather than inferring it from where a filter happens to
    sit in the code: a backend has no `.sent_states` of its own, so this is the instrument, not
    the thing under test."""

    def __init__(self, inner):
        self._inner = inner
        self.sent_states = []
        self.mode = inner.mode
        self.model = inner.model

    def decide(self, state, questions):
        self.sent_states.append(state)
        return self._inner.decide(state, questions)


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
    writing this test, and the failure was a `ReplayMiss` whose state is `v17-restricted`'s own
    text verbatim -- fixtures/responses.json holds no stored answer for a restricted passage, so
    attempting to send one fails loudly rather than silently succeeding -- before the filter was
    restored.
    """
    counting = _CountingBackend(get_backend(fixtures=responses_path(RECIPE)))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    candidates = [e for e in examples if e.split not in ("train", "demo")]
    restricted = helpers.restricted_examples(candidates)
    accessible = helpers.accessible_examples(candidates)
    assert restricted, "fixtures must include at least one restricted passage"
    assert accessible, "fixtures must include at least one accessible passage"

    decisions = helpers.decide_passages(candidates, counting, questions)

    assert len(counting.sent_states) == len(accessible)
    assert set(decisions) == {e.id for e in accessible}

    restricted_states = {e.id: helpers.build_state(e.fields) for e in restricted}
    leaked = [eid for eid, state in restricted_states.items() if state in counting.sent_states]
    assert not leaked, f"a restricted passage's state was sent to decide(): {leaked}"


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
        d: select_threshold(val_gold_by_domain[d], val_noul_by_domain[d], "f1") for d in DOMAINS
    }
    val_correct, val_confidence, _ = pool_label_decisions(
        [e.id for e in validation], DOMAINS, val_gold_by_domain, val_noul_by_domain, thresholds
    )
    confidence_gate = select_confidence_threshold(val_correct, val_confidence, min_coverage=0.7)

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
