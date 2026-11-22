"""Recipe 44 compares dates and amounts in Python, never in a Noul proposition.

TypeSafe says Jev reads dates as text and cannot reliably judge whether two numbers are near
each other, so "does the completion fall after the deadline" and "does the cost exceed the
limit" are computed by ``helpers.timeline_check`` and ``helpers.budget_check`` and only the
named bucket reaches Jev. These tests pin that: no proposition contains a raw date or currency
amount or asks Jev to compare one, no state carries one, the computed buckets are right at
every boundary, and the gold labels agree with the code.
"""

import re
from pathlib import Path

import pytest

from jev_cookbook import load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, load_labels

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
# A raw date or amount written as text: a currency symbol or code beside a number, a number
# with a currency word, an ISO or numeric date, or a month name beside a day number.
RAW_VALUE = re.compile(
    rf"[$€£]\s?\d|\d\s?(?:dollars?|USD|EUR|GBP)\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b|"
    rf"\b\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b|\b(?:{MONTHS})\.?\s+\d{{1,2}}\b|"
    rf"\b\d{{1,2}}\s+(?:{MONTHS})\b",
    re.IGNORECASE,
)
# The quantities a comparison is about. A proposition that names one of them is asking about a
# comparison, so it must read a computed check rather than compare the quantities itself.
QUANTITY = re.compile(
    r"\b(?:cost|costs|budget|limit|deadline|completion|completes|date|dates|price|amount|total)\b",
    re.IGNORECASE,
)


def comparison_problems(question) -> list[str]:
    """Why one Noul proposition (its instructions and both criteria) asks Jev to compare a
    date or an amount; an empty list when it does not."""
    texts = [question.instructions, *question.criteria.values()]
    problems = []
    for text in texts:
        found = RAW_VALUE.search(text)
        if found:
            problems.append(f"raw date or currency value {found.group(0)!r} in {text!r}")
        if QUANTITY.search(text) and not re.search(r"\bcomputed\b.*\bcheck\b", text, re.I):
            problems.append(f"names a quantity without reading a computed check: {text!r}")
    return problems


def test_no_noul_proposition_contains_a_raw_date_or_currency_comparison():
    questions = helpers.build_questions()
    assert set(questions) == set(helpers.CONSTRAINTS)
    for name, question in questions.items():
        assert comparison_problems(question) == [], name


def test_budget_and_timeline_propositions_read_the_computed_checks():
    questions = helpers.build_questions()
    for name in (helpers.BUDGET, helpers.TIMELINE):
        question = questions[name]
        assert f"computed {name} check" in question.instructions
        assert all(f"computed {name} check" in text for text in question.criteria.values())
    # The two buckets each proposition's criteria name are the ones Python actually returns.
    budget = questions[helpers.BUDGET].criteria
    assert helpers.BUDGET_OVER in budget["true"] and helpers.BUDGET_WITHIN in budget["false"]
    timeline = questions[helpers.TIMELINE].criteria
    assert helpers.TIMELINE_LATE in timeline["true"]
    assert helpers.TIMELINE_ON_TIME in timeline["false"]


@pytest.mark.parametrize(
    "instructions",
    [
        # recipe 44's wording before the comparisons moved into code
        "The plan violates the user's stated timeline constraint: its own described "
        "completion falls after the deadline the constraint states.",
        "The plan violates the user's stated budget constraint: its own described costs "
        "exceed the limit the constraint states.",
        # the same comparison with the values spelled out
        "The plan finishes on March 10, which is after the March 14 deadline.",
        "The plan completes 2026-03-10, after the deadline of 2026-03-14.",
        "The plan costs $4200, which exceeds the $5000 limit.",
        "The plan costs 4200 dollars against a limit of 5000 dollars.",
    ],
)
def test_the_comparison_detector_flags_the_wordings_this_recipe_removed(instructions):
    from jev_cookbook import Noul

    question = Noul(instructions=instructions, criteria={"true": "Yes.", "false": "No."})
    assert comparison_problems(question)


def test_the_comparison_detector_passes_a_judgment_that_is_not_a_comparison():
    from jev_cookbook import Noul

    question = Noul(
        instructions="The plan uses a vendor that is not on the pre-approved list.",
        criteria={"true": "An unlisted vendor is used.", "false": "Only listed vendors are used."},
    )
    assert comparison_problems(question) == []


def test_no_state_carries_a_raw_date_or_amount():
    for example in load_inputs(RECIPE):
        state = helpers.build_state(example.fields)
        flat = repr(state)
        assert RAW_VALUE.search(flat) is None, example.id
        # the constraint statements that hold the limit and deadline stay out of the state
        assert set(state["user_constraints"]) == {helpers.VENDOR, helpers.DATA_HANDLING}
        assert set(state["computed_checks"]) == {helpers.BUDGET, helpers.TIMELINE}
        assert state["computed_checks"][helpers.BUDGET] in (
            helpers.BUDGET_OVER,
            helpers.BUDGET_WITHIN,
        )
        assert state["computed_checks"][helpers.TIMELINE] in (
            helpers.TIMELINE_LATE,
            helpers.TIMELINE_ON_TIME,
        )


def test_the_gold_labels_for_budget_and_timeline_are_what_the_code_computes():
    labels = load_labels(RECIPE)
    seen = 0
    for example in load_inputs(RECIPE):
        if example.id not in labels:
            continue
        seen += 1
        checks = helpers.computed_checks(example.fields)
        assert labels[example.id][helpers.BUDGET] == (checks[helpers.BUDGET] == helpers.BUDGET_OVER)
        assert labels[example.id][helpers.TIMELINE] == (
            checks[helpers.TIMELINE] == helpers.TIMELINE_LATE
        )
    assert seen == 30


def test_the_structured_fields_agree_with_the_display_text_in_user_constraints():
    for example in load_inputs(RECIPE):
        constraints = example.fields["user_constraints"]
        assert constraints[helpers.BUDGET].endswith(f"${example.fields['budget_limit']}.")
        assert example.fields["deadline"][:4] == example.fields["completion"][:4]


def test_the_checks_change_the_replay_key_so_a_stale_fixture_cannot_replay():
    questions = helpers.build_questions()
    fields = dict(load_inputs(RECIPE)[0].fields)
    base = replay_key(helpers.build_state(fields), questions)
    over = replay_key(
        helpers.build_state({**fields, "cost": fields["budget_limit"] + 1}), questions
    )
    late = replay_key(
        helpers.build_state({**fields, "completion": "2026-12-31", "deadline": "2026-01-01"}),
        questions,
    )
    assert len({base, over, late}) == 3


@pytest.mark.parametrize(
    ("cost", "limit", "expected"),
    [
        (4200, 5000, "within"),
        (5000, 5000, "within"),  # "must not exceed": spending exactly the limit is allowed
        (5001, 5000, "over"),
        (4999.99, 5000, "within"),
        (5000.01, 5000, "over"),
        (0, 0, "within"),
        (1, 0, "over"),
        (900, 1000, "within"),  # text order would call "900" greater than "1000"
        (10000, 9000, "over"),  # text order would call "10000" smaller than "9000"
    ],
)
def test_budget_check_compares_numbers_not_text(cost, limit, expected):
    result = helpers.budget_check(cost, limit)
    assert result == (helpers.BUDGET_OVER if expected == "over" else helpers.BUDGET_WITHIN)


@pytest.mark.parametrize(
    ("completion", "deadline", "expected"),
    [
        ("2026-03-10", "2026-03-14", "on time"),
        ("2026-03-14", "2026-03-14", "on time"),  # "completed by": the deadline day is on time
        ("2026-03-15", "2026-03-14", "late"),
        ("2026-05-09", "2026-05-01", "late"),
        ("2026-09-09", "2026-09-10", "on time"),  # text order would call "9" after "10"
        ("2026-04-02", "2026-03-30", "late"),  # across a month end
        ("2026-12-31", "2027-01-01", "on time"),  # across a year end
        ("2027-01-01", "2026-12-31", "late"),
        ("2028-02-29", "2028-02-28", "late"),  # a leap day exists
        ("2028-03-01", "2028-02-29", "late"),
    ],
)
def test_timeline_check_orders_real_dates_not_text(completion, deadline, expected):
    result = helpers.timeline_check(completion, deadline)
    assert result == (helpers.TIMELINE_LATE if expected == "late" else helpers.TIMELINE_ON_TIME)


@pytest.mark.parametrize(
    ("cost", "limit"),
    [
        ("4200", 5000),  # an amount written as text is refused, not coerced
        (4200, "$5000"),
        (None, 5000),
        (True, 5000),
        (-1, 5000),
        (float("nan"), 5000),
        (float("inf"), 5000),
        (4200, -5000),
    ],
)
def test_budget_check_refuses_anything_that_is_not_a_plain_number(cost, limit):
    with pytest.raises(ValueError, match="must "):
        helpers.budget_check(cost, limit)


@pytest.mark.parametrize(
    ("completion", "deadline"),
    [
        ("March 10", "2026-03-14"),  # a date written as text is refused, not guessed
        ("2026-03-10", "by March 14"),
        ("2026-3-10", "2026-03-14"),
        ("20260310", "2026-03-14"),
        ("2026-02-30", "2026-03-14"),
        ("2026-13-01", "2026-03-14"),
        (None, "2026-03-14"),
        (20260310, "2026-03-14"),
    ],
)
def test_timeline_check_refuses_anything_that_is_not_an_iso_date(completion, deadline):
    with pytest.raises(ValueError, match="ISO date"):
        helpers.timeline_check(completion, deadline)


def test_no_row_has_its_completion_and_deadline_far_apart_so_the_fixed_year_is_safe():
    """The prose dates carry no year, so build_fixtures reads them all in one fixed year. A pair
    that crosses a year end (a December deadline, a January completion) would be misordered and
    judged on time, so every pair must be close enough that it cannot have wrapped."""
    from datetime import date

    for example in load_inputs(RECIPE):
        gap = abs(
            (
                date.fromisoformat(example.fields["completion"])
                - date.fromisoformat(example.fields["deadline"])
            ).days
        )
        assert gap <= 60, f"{example.id}: completion and deadline are {gap} days apart"


def test_the_fixed_year_limit_is_real_a_year_wrapping_pair_is_misjudged():
    """Documents the limit the previous test guards: read in one year, a completion of January 5
    after a deadline of December 28 compares as early, so the check says on time."""
    module = load_build_fixtures()
    assert helpers.timeline_check(module._iso("January 5"), module._iso("December 28")) == (
        helpers.TIMELINE_ON_TIME
    )


def load_build_fixtures():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "recipe44_build_fixtures_for_comparison_test", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
