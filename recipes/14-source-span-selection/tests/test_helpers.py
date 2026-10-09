"""Tests for recipe 14's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# A small, fixed document used by most tests below: two candidate spans (a decoy "Bill To"
# line and the real "Supplier" line) plus "not_stated".
DOCUMENT = (
    "Purchase Confirmation #0001. Bill To: Keystone Retail Group, 1 Example Way. Supplier: "
    "Riverton Hardware Inc., 2 Example Way. Items: a box of nails."
)
FIELDS = {"doc_id": "D-TEST", "document": DOCUMENT}


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


# --- split_sentences -----------------------------------------------------------------------


def test_split_sentences_splits_on_period_exclamation_question():
    assert helpers.split_sentences("One. Two! Three?") == [(0, 5), (5, 10), (10, 16)]


def test_split_sentences_does_not_split_after_a_known_abbreviation():
    # "Co." is a company-name abbreviation, not a sentence end, so this is one sentence.
    doc = "Riverside Packaging Co. was our vendor last year. Timberline Goods supplies it now."
    bounds = helpers.split_sentences(doc)
    assert len(bounds) == 2
    assert doc[bounds[0][0] : bounds[0][1]] == (
        "Riverside Packaging Co. was our vendor last year. "
    )


def test_split_sentences_includes_a_final_sentence_with_no_trailing_punctuation():
    assert helpers.split_sentences("Only one sentence here") == [(0, 22)]


# --- extract_spans ---------------------------------------------------------------------------


def test_extract_spans_finds_every_organisation_bearing_sentence_in_order():
    spans = helpers.extract_spans(DOCUMENT)
    assert [s["id"] for s in spans] == ["s1", "s2"]
    texts = [DOCUMENT[s["start"] : s["end"]] for s in spans]
    assert texts == [
        "Bill To: Keystone Retail Group, 1 Example Way. ",
        "Supplier: Riverton Hardware Inc., 2 Example Way. ",
    ]


def test_extract_spans_is_empty_when_no_sentence_names_an_organisation():
    doc = "Delivery Note #1. Contents: a box of nails. No further details were given."
    assert helpers.extract_spans(doc) == []


def test_extract_spans_does_not_split_a_company_suffix_out_of_its_own_sentence():
    # "Co." must not be mistaken for a sentence end; the whole sentence is one candidate span.
    doc = "Riverside Packaging Co. was our vendor last year. Timberline Goods supplies it now."
    spans = helpers.extract_spans(doc)
    assert len(spans) == 2
    assert doc[spans[0]["start"] : spans[0]["end"]].strip() == (
        "Riverside Packaging Co. was our vendor last year."
    )


# --- build_state / build_questions ------------------------------------------------------------


def test_the_state_hides_the_document_and_the_offsets():
    state = helpers.build_state(FIELDS)
    assert state == {
        "spans": {
            "s1": "Bill To: Keystone Retail Group, 1 Example Way. ",
            "s2": "Supplier: Riverton Hardware Inc., 2 Example Way. ",
        }
    }
    assert "document" not in state
    assert "doc_id" not in state


def test_questions_are_built_from_this_documents_own_spans():
    questions = helpers.build_questions(FIELDS)
    assert list(questions) == ["supplier_span"]
    span = questions["supplier_span"]
    assert list(span.criteria) == ["s1", "s2", helpers.NOT_STATED]
    assert isinstance(span.instructions, str) and span.instructions


def test_the_option_list_is_per_document_so_the_replay_key_changes_with_it():
    other_fields = {
        "doc_id": "D-OTHER",
        "document": "Vendor: Example Co, 9 Main St. Items: one widget.",
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


# --- no_candidates (the zero-span short circuit: no question, no call) -----------------------


def test_no_candidates_reports_not_stated_with_no_choice_and_no_span_text():
    result = helpers.no_candidates("D1")
    assert result.choice is None
    assert result.outcome == helpers.NOT_STATED_OUTCOME
    assert result.span_text is None
    assert result.reason == helpers.NO_CANDIDATES_REASON


def test_no_candidates_is_correct_only_when_gold_is_also_not_stated():
    result = helpers.no_candidates("D1")
    assert helpers.is_correct(result, helpers.NOT_STATED) is True
    assert helpers.is_correct(result, "Example Corp") is False


# --- select_span -----------------------------------------------------------------------------


def test_a_confident_real_span_is_supported():
    spans = helpers.spans_by_id(FIELDS)
    a = _confident("s2", ["s1", "s2", helpers.NOT_STATED])
    result = helpers.select_span("D1", a, spans, 0.3)
    assert result.doc_id == "D1"
    assert result.choice == "s2"
    assert result.outcome == helpers.SUPPORTED
    assert result.span_text == "Supplier: Riverton Hardware Inc., 2 Example Way. "
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


# --- gold_positions --------------------------------------------------------------------------


def test_gold_positions_finds_every_span_naming_the_supplier():
    spans = helpers.spans_by_id(FIELDS)
    assert helpers.gold_positions(spans, "Riverton Hardware Inc.") == [2]
    assert helpers.gold_positions(spans, "Keystone Retail Group") == [1]
    assert helpers.gold_positions(spans, helpers.NOT_STATED) == []
    assert helpers.gold_positions(spans, "No Such Company") == []


def test_gold_positions_lists_every_matching_span_when_the_supplier_is_named_twice():
    doc = (
        "Prepared by Example Fixtures Co, our supplier. Please remit payment to Example "
        "Fixtures Co, Accounts. Items: one widget."
    )
    spans = helpers.spans_by_id({"doc_id": "D1", "document": doc})
    assert helpers.gold_positions(spans, "Example Fixtures Co") == [1, 2]


# --- baselines --------------------------------------------------------------------------------


def test_last_and_first_span_baselines_pick_by_position_not_content():
    spans = helpers.spans_by_id(FIELDS)
    assert helpers.last_span_baseline(spans) == "s2"
    assert helpers.first_span_baseline(spans) == "s1"


def test_position_baselines_report_not_stated_with_no_candidates():
    assert helpers.last_span_baseline({}) == helpers.NOT_STATED
    assert helpers.first_span_baseline({}) == helpers.NOT_STATED


def test_cue_regex_baseline_picks_the_last_cue_bearing_span():
    spans = helpers.spans_by_id(FIELDS)  # "Supplier:" is the cue, on s2
    assert helpers.cue_regex_baseline(spans) == "s2"


def test_cue_regex_baseline_is_fooled_by_a_cue_word_in_a_decoy():
    doc = (
        "Supplier: Example Fixtures Co, 1 Main St. Remit any shipping inquiries to Crestline "
        "Shipping Co, our courier partner. Items: one widget."
    )
    spans = helpers.spans_by_id({"doc_id": "D1", "document": doc})
    # The real supplier is s1; "remit" in the later decoy (s2) fools the naive cue baseline.
    assert helpers.cue_regex_baseline(spans) == "s2"
    assert helpers.matches_gold("s1", spans, "Example Fixtures Co") is True


def test_cue_regex_baseline_reports_not_stated_with_no_cue_anywhere():
    doc = "Bill To: Keystone Retail Group, 1 Main St. Shipped via Crestline Shipping."
    spans = helpers.spans_by_id({"doc_id": "D1", "document": doc})
    assert helpers.cue_regex_baseline(spans) == helpers.NOT_STATED


# --- fixtures ----------------------------------------------------------------------------------


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example
    # that has at least one candidate span; a zero-span example lists no key at all.
    for example in load_inputs(RECIPE):
        spans = helpers.extract_spans(example.fields["document"])
        if not spans:
            assert example.replay_keys == ()
            continue
        questions = helpers.build_questions(example.fields)
        key = replay_key(helpers.build_state(example.fields), questions)
        assert example.replay_keys == (key,)


def test_every_labelled_fixture_is_answerable_from_its_own_spans():
    # The whole correctness story rests on the gold name actually appearing in the spans
    # extract_spans finds: a document with no supplier should have none, and a document
    # naming a supplier should have it in at least one span (two, for the "named twice" rows).
    labels = load_labels(RECIPE)
    for example in load_inputs(RECIPE):
        if example.id not in labels:
            continue
        gold = labels[example.id]
        spans = helpers.spans_by_id(example.fields)
        positions = helpers.gold_positions(spans, gold)
        if gold == helpers.NOT_STATED:
            assert positions == [], f"{example.id}: not_stated but a span names a supplier"
        else:
            assert positions, f"{example.id}: gold {gold!r} is not in any extracted span"


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
        spans = helpers.spans_by_id(e.fields)
        if not spans:
            continue
        questions = helpers.build_questions(e.fields)
        a = backend.decide(helpers.build_state(e.fields), questions)["supplier_span"]
        if a.choice != helpers.NOT_STATED:
            named.append((helpers.matches_gold(a.choice, spans, labels[e.id]), a.confidence))
    threshold = select_confidence_threshold(
        [c for c, _ in named], [conf for _, conf in named], target_accuracy=1.0
    )

    wrong = []
    wrong_above_threshold = []
    for e in select_split(inputs, "test"):
        spans = helpers.spans_by_id(e.fields)
        if not spans:
            if not helpers.matches_gold(helpers.NOT_STATED, spans, labels[e.id]):
                wrong.append(e.id)
            continue
        questions = helpers.build_questions(e.fields)
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
