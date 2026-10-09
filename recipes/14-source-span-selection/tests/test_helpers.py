"""Tests for recipe 14's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# A small, fixed document used by every test below that does not need the full fixture set:
# two candidate spans (a decoy "Bill To" line and the real "Supplier" line) plus "not_stated".
DOCUMENT = (
    "Purchase Confirmation #0001. Bill To: Keystone Retail Group, 1 Example Way. Supplier: "
    "Riverton Hardware Inc., 2 Example Way. Items: a box of nails."
)
FIELDS = {
    "doc_id": "D-TEST",
    "document": DOCUMENT,
    "spans": [
        {"id": "s1", "start": DOCUMENT.index("Bill To"), "end": DOCUMENT.index("Supplier")},
        {"id": "s2", "start": DOCUMENT.index("Supplier"), "end": DOCUMENT.index("Items:")},
    ],
}


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def _confident(choice, options):
    """A clearly confident answer naming ``choice``, the rest spread evenly over ``options``."""
    others = [o for o in options if o != choice]
    rest = (1.0 - 0.9) / len(others)
    return answer({choice: 0.9, **{o: rest for o in others}})


def _low_confidence(choice, options):
    """A low-confidence answer naming ``choice``: just barely ahead of an even split, so it
    stays the top option (required by ``ChoiceAnswer``) whatever ``len(options)`` is."""
    others = [o for o in options if o != choice]
    top = 1.0 / len(options) + 0.03
    rest = (1.0 - top) / len(others)
    return answer({choice: top, **{o: rest for o in others}})


# --- build_state / build_questions ------------------------------------------------------------


def test_the_state_hides_the_document_and_the_offsets():
    state = helpers.build_state(FIELDS)
    assert state == {
        "spans": {
            "s1": "Bill To: Keystone Retail Group, 1 Example Way. ",
            "s2": "Supplier: Riverton Hardware Inc., 2 Example Way. ",
        }
    }
    # Only the sliced text crosses; "document", "doc_id" and the offsets never do.
    assert "document" not in state
    assert "doc_id" not in state


def test_questions_are_built_from_this_documents_own_spans():
    questions = helpers.build_questions(FIELDS)
    assert list(questions) == ["supplier_span"]
    span = questions["supplier_span"]
    assert list(span.criteria) == ["s1", "s2", helpers.NOT_STATED]
    assert isinstance(span.instructions, str) and span.instructions


def test_a_document_with_no_candidate_spans_has_only_the_fallback_option():
    fields = {"doc_id": "D-EMPTY", "document": "No organisation is named here.", "spans": []}
    questions = helpers.build_questions(fields)
    assert list(questions["supplier_span"].criteria) == [helpers.NOT_STATED]
    assert helpers.build_state(fields) == {"spans": {}}


def test_the_option_list_is_per_document_so_the_replay_key_changes_with_it():
    # Two documents with the same number of candidate spans still ask a different question,
    # because a Choice's replay key depends on its criteria (here, the span ids) -- the same
    # consequence recipe 07's per-word sense inventory has for its options.
    other_fields = {
        "doc_id": "D-OTHER",
        "document": "Vendor: Example Co. Items: one widget.",
        "spans": [{"id": "s1", "start": 0, "end": len("Vendor: Example Co.")}],
    }
    key_a = replay_key(helpers.build_state(FIELDS), helpers.build_questions(FIELDS))
    key_b = replay_key(helpers.build_state(other_fields), helpers.build_questions(other_fields))
    assert key_a != key_b


# --- span_text -----------------------------------------------------------------------------


def test_span_text_slices_by_offset():
    assert helpers.span_text("hello world", 0, 5) == "hello"
    assert helpers.span_text("hello world", 6, 11) == "world"


@pytest.mark.parametrize("start,end", [(-1, 5), (0, 100), (5, 2)])
def test_span_text_rejects_offsets_out_of_range(start, end):
    with pytest.raises(ValueError, match="out of range"):
        helpers.span_text("hello world", start, end)


def test_spans_by_id_slices_every_span_in_fields():
    assert helpers.spans_by_id(FIELDS) == {
        "s1": "Bill To: Keystone Retail Group, 1 Example Way. ",
        "s2": "Supplier: Riverton Hardware Inc., 2 Example Way. ",
    }


# --- select_span -----------------------------------------------------------------------------


def test_a_confident_real_span_is_supported():
    spans = helpers.spans_by_id(FIELDS)
    a = _confident("s2", ["s1", "s2", helpers.NOT_STATED])
    result = helpers.select_span("D1", a, spans, 0.3)
    assert (result.doc_id, result.choice, result.outcome, result.span_text) == (
        "D1",
        "s2",
        helpers.SUPPORTED,
        spans["s2"],
    )
    assert result.reason == "confident match"


@pytest.mark.parametrize("choice", ["s1", "s2"])
def test_a_low_confidence_span_goes_to_review_whatever_the_span(choice):
    spans = helpers.spans_by_id(FIELDS)
    a = _low_confidence(choice, ["s1", "s2", helpers.NOT_STATED])
    assert a.choice == choice
    result = helpers.select_span("D1", a, spans, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.span_text is None
    assert result.reason == "confidence below the threshold"


@pytest.mark.parametrize("top_probability", [0.95, 0.36])
def test_not_stated_is_never_gated_on_confidence_whatever_its_value(top_probability):
    # top_probability=0.36 keeps not_stated as the top option (just ahead of an even third,
    # ~0.333, over two other options) while its confidence, (0.36 - 1/3) / (2/3) =~ 0.04, is
    # well below the 0.3 threshold used here. A mutation that exempted not_stated from the
    # gate only when it is also confident would still fail this case, because it is checked
    # at both ends.
    spans = helpers.spans_by_id(FIELDS)
    others = ["s1", "s2"]
    rest = (1.0 - top_probability) / len(others)
    a = answer({helpers.NOT_STATED: top_probability, **{o: rest for o in others}})
    assert a.choice == helpers.NOT_STATED
    result = helpers.select_span("D1", a, spans, 0.3)
    assert result.outcome == helpers.NOT_STATED_OUTCOME
    assert result.span_text is None
    assert result.choice == helpers.NOT_STATED


def test_a_choice_naming_no_candidate_span_of_this_document_goes_to_review():
    # Defensive: build_questions never offers an option outside this document's own spans plus
    # not_stated, but the rule does not trust that silently.
    spans = helpers.spans_by_id(FIELDS)
    a = ChoiceAnswer(
        "s7",
        {"s1": 0.1, "s2": 0.1, helpers.NOT_STATED: 0.1, "s7": 0.7},
        0.6,
        Provenance.synthetic(),
    )
    result = helpers.select_span("D1", a, spans, 0.3)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "not a candidate span for this document"


def test_the_threshold_is_inclusive():
    a = _confident("s2", ["s1", "s2", helpers.NOT_STATED])
    spans = helpers.spans_by_id(FIELDS)
    t = a.confidence
    assert helpers.select_span("D1", a, spans, t).outcome == helpers.SUPPORTED
    assert helpers.select_span("D1", a, spans, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    a = _confident("s2", ["s1", "s2", helpers.NOT_STATED])
    spans = helpers.spans_by_id(FIELDS)
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.select_span("D1", a, spans, bad)


# --- matches_gold / is_correct -----------------------------------------------------------------


def test_matches_gold_for_not_stated():
    spans = helpers.spans_by_id(FIELDS)
    assert helpers.matches_gold(helpers.NOT_STATED, spans, helpers.NOT_STATED) is True
    assert helpers.matches_gold(helpers.NOT_STATED, spans, "Riverton Hardware Inc.") is False


def test_matches_gold_for_a_real_span_checks_the_text_not_the_id():
    spans = helpers.spans_by_id(FIELDS)
    assert helpers.matches_gold("s2", spans, "Riverton Hardware Inc.") is True
    assert helpers.matches_gold("s2", spans, "Keystone Retail Group") is False
    assert helpers.matches_gold("s1", spans, "Riverton Hardware Inc.") is False


def test_matches_gold_rejects_a_choice_outside_this_documents_spans():
    spans = helpers.spans_by_id(FIELDS)
    assert helpers.matches_gold("s9", spans, "Riverton Hardware Inc.") is False


def test_is_correct_for_each_outcome():
    spans = helpers.spans_by_id(FIELDS)
    supported = helpers.select_span(
        "D1", _confident("s2", ["s1", "s2", helpers.NOT_STATED]), spans, 0.3
    )
    assert helpers.is_correct(supported, "Riverton Hardware Inc.") is True
    assert helpers.is_correct(supported, "Keystone Retail Group") is False

    not_stated = helpers.Selection("D1", helpers.NOT_STATED, helpers.NOT_STATED_OUTCOME, None, "x")
    assert helpers.is_correct(not_stated, helpers.NOT_STATED) is True
    assert helpers.is_correct(not_stated, "Riverton Hardware Inc.") is False

    reviewed = helpers.Selection("D1", "s2", helpers.REVIEW, None, "confidence below the threshold")
    assert helpers.is_correct(reviewed, "Riverton Hardware Inc.") is False
    assert helpers.is_correct(reviewed, helpers.NOT_STATED) is False


# --- fixtures ----------------------------------------------------------------------------------


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example;
    # the option list (and so the question) is built fresh per document.
    for example in load_inputs(RECIPE):
        questions = helpers.build_questions(example.fields)
        key = replay_key(helpers.build_state(example.fields), questions)
        assert example.replay_keys == (key,)


def test_stored_answers_are_not_all_right():
    """The fixtures must contain some wrong answers, and at least one of them must be wrong
    while confident enough to clear the frozen threshold on ``test`` -- otherwise the
    selective-prediction numbers this recipe reports would all be a perfect, untaught story."""
    from jev_cookbook import get_backend
    from jev_cookbook.fixtures import responses_path, select_split

    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    inputs = load_inputs(RECIPE)

    val_examples = select_split(inputs, "validation")
    named = []  # (correct, confidence) for validation answers that name a real span
    for e in val_examples:
        questions = helpers.build_questions(e.fields)
        spans = helpers.spans_by_id(e.fields)
        a = backend.decide(helpers.build_state(e.fields), questions)["supplier_span"]
        if a.choice != helpers.NOT_STATED:
            named.append((helpers.matches_gold(a.choice, spans, labels[e.id]), a.confidence))
    threshold = select_confidence_threshold(
        [c for c, _ in named], [conf for _, conf in named], target_accuracy=1.0
    )

    wrong = []
    wrong_above_threshold = []
    for e in select_split(inputs, "test"):
        questions = helpers.build_questions(e.fields)
        spans = helpers.spans_by_id(e.fields)
        a = backend.decide(helpers.build_state(e.fields), questions)["supplier_span"]
        if not helpers.matches_gold(a.choice, spans, labels[e.id]):
            wrong.append(e.id)
            if a.choice != helpers.NOT_STATED and a.confidence >= threshold:
                wrong_above_threshold.append(e.id)
    assert wrong, "the test fixtures should contain some wrong answers"
    assert wrong_above_threshold, (
        "the test fixtures should contain a wrong answer confident enough to clear the "
        "frozen threshold, or the selective risk this recipe reports would always be zero"
    )


def test_summarize_outcomes_follow_up_uses_the_shared_evaluate_outcomes():
    # jev_cookbook.evaluation.evaluate_outcomes (#160) now covers the coverage/accuracy/risk
    # this recipe reports from select_span's own outcomes; this recipe has no recipe-local
    # OutcomeSummary/summarize_outcomes of its own, unlike recipe 08 (built before #160 landed).
    assert not hasattr(helpers, "summarize_outcomes")
    assert not hasattr(helpers, "OutcomeSummary")
