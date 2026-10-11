"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 32.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic: written by hand as probabilities over the four relevance levels,
not produced by a model. Nineteen patches (nineteen tasks) are scored per split
(`validation`/`test`), each carrying a small candidate set of tests -- the same cohort size as
this repository's other Level 3 recipes. Two more patches are `demo` (never scored), used only
to show a few typed answers up close.

Three task shapes recur across both splits, so that two separate Python mechanisms are each
shown to matter on their own:

- "easy" (12 of the 19 tasks per split): one gold-relevant candidate (`direct_regression`)
  among three or four irrelevant ones. The confidence gate and the size budget (`SUITE_BUDGET`,
  2) never bind here: recall is 1.0 once the gate is cleared.
- "budget" (4 of the 19): three gold-relevant candidates (one `direct_regression`, two
  `exercises_change`), all stored at high confidence, so the confidence gate never excludes any
  of them -- but `SUITE_BUDGET` (2) can only ever hold two, so recall here is capped at 2/3
  regardless of the gate. Removing the budget (proposing every eligible candidate) recovers
  1.0; removing the confidence gate changes nothing on these tasks, because nothing here is
  low-confidence.
- "gate" (3 of the 19): exactly `SUITE_BUDGET` (2) gold-relevant candidates, but one of them
  (`exercises_change`) is stored at low confidence, so the confidence gate -- not the budget --
  is what keeps it out of the proposed suite. Loosening the budget changes nothing on these
  tasks, because only one candidate is ever eligible; removing the confidence gate recovers the
  second.

One `validation` task (`v-session-refresh`) also stores a wrong answer at low confidence (the
`same_area` candidate, levelled `unrelated` with no trace of real confidence behind it), so the
confidence gate this notebook selects on `validation` is a real choice, not a vacuous one that
happens to cover every answer the selector sees. Two `test` tasks store a wrong answer that IS
confident, a candidate that advertises full coverage in its own name but exercises nothing the
patch changes, levelled `direct_regression` at high confidence though its gold level is
`unrelated`: `t-query-parser`'s copy shows up as a non-zero per-candidate risk on its own, and
`t-ticket-router`'s copy, scored high enough to compete for a budget slot, costs that task a
truly relevant candidate's place in the proposed suite -- the one place in this fixture set
where `validation` and `test` diverge in the proposed suite's own composition, not only in which
candidate happens to be wrong. `discount-engine`'s candidates (both splits) are written so the
lexical half of the baseline is defeated on purpose: the gold-relevant, direct-regression
candidate is phrased with none of the patch description's own words, while the (irrelevant)
same_area candidate echoes several of them, so the file-path-and-lexical baseline ranks the
irrelevant candidate first.

Generating inputs and labels is kept separate from generating responses, on purpose (the pattern
`recipes/_template/build_fixtures.py` sets): once responses.json holds even one recorded answer
(provenance "recorded", captured from a real Jev call), running this script again must not
silently replace it with a synthetic probability. inputs.jsonl and labels.jsonl are always
rewritten from ROWS, because neither ever holds a model's answer; responses.json is rewritten
only when it does not yet exist, holds only synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, Provenance, ScoreAnswer, load_helpers, replay_key
from jev_cookbook.fixtures import stable_permutation

HERE = Path(__file__).resolve().parent
RECIPE_SLUG = "32-regression-test-selection"
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
LEVELS = list(helpers.RELEVANCE_LEVELS)

# Stored probability vectors by level (0..3) and confidence tier, ordered level 0 to level 3.
# "HIGH" answers are clean and confident; "LOWCONF" answers are stored with a near-tied, spread
# distribution so their confidence is low whatever level they peak on.
L3_HIGH = (0.02, 0.03, 0.10, 0.85)  # direct_regression, confident
L3_MILD = (0.06, 0.10, 0.14, 0.70)  # direct_regression, less sharply confident
L2_HIGH_A = (0.03, 0.08, 0.80, 0.09)  # exercises_change, confident
L2_HIGH_B = (0.04, 0.10, 0.76, 0.10)  # exercises_change, confident (a second, slightly different)
L2_LOWCONF = (0.04, 0.09, 0.42, 0.45)  # peaks at level 3 but nearly tied with level 2; low conf
L1_HIGH = (0.08, 0.78, 0.09, 0.05)  # same_area, confident
L1_LOWCONF_WRONG = (0.42, 0.28, 0.18, 0.12)  # peaks at level 0; gold is same_area (1); conf 0
L0_HIGH_A = (0.75, 0.15, 0.07, 0.03)  # unrelated, confident
L0_HIGH_B = (0.78, 0.14, 0.05, 0.03)  # unrelated, confident (a second, slightly different)
ADVERSARIAL_WRONG = (0.04, 0.05, 0.07, 0.84)  # peaks at level 3; gold is unrelated (0)

# A small pool of candidate tests from entirely different feature areas, used for the
# `unrelated` candidate in several tasks. Reusing one of these across two different patches is
# not a fixture leak: a (patch, test) pair's full state always differs because the patch text
# differs, and docs/fixtures.md's leak rule compares the complete state, not one field of it.
FOREIGN = [
    (
        "analytics",
        "analytics/dashboard_export.py",
        "test_dashboard_export_includes_all_widgets",
        "def test_dashboard_export_includes_all_widgets():\n"
        '    dashboard = build_dashboard(widgets=["funnel", "retention", "revenue"])\n'
        "    exported = export_dashboard(dashboard)\n"
        '    assert {w.name for w in exported.widgets} == {"funnel", "retention", "revenue"}',
    ),
    (
        "teams",
        "teams/timezone_picker.py",
        "test_timezone_picker_lists_all_regions",
        "def test_timezone_picker_lists_all_regions():\n"
        "    options = list_timezone_options()\n"
        '    assert "Pacific/Auckland" in options and "Europe/Lisbon" in options',
    ),
    (
        "files",
        "files/thumbnail_cache.py",
        "test_thumbnail_cache_evicts_oldest_entry",
        "def test_thumbnail_cache_evicts_oldest_entry():\n"
        "    cache = ThumbnailCache(capacity=2)\n"
        '    cache.put("a", b"img-a"); cache.put("b", b"img-b"); cache.put("c", b"img-c")\n'
        '    assert cache.get("a") is None and cache.get("c") is not None',
    ),
    (
        "notifications",
        "notifications/sms_gateway.py",
        "test_sms_gateway_retries_on_timeout",
        "def test_sms_gateway_retries_on_timeout():\n"
        "    gateway = SmsGateway(transport=FlakyTransport(failures=1))\n"
        '    result = gateway.send("+15550000000", "your code is 123456")\n'
        "    assert result.delivered and gateway.transport.attempts == 2",
    ),
    (
        "search",
        "search/autocomplete_cache.py",
        "test_autocomplete_cache_warms_on_startup",
        "def test_autocomplete_cache_warms_on_startup():\n"
        "    cache = AutocompleteCache()\n"
        '    cache.warm(["invoice", "inventory", "invite"])\n'
        '    assert cache.suggest("inv") == ["invoice", "inventory", "invite"]',
    ),
    (
        "billing",
        "billing/invoice_pdf.py",
        "test_invoice_pdf_includes_company_logo",
        "def test_invoice_pdf_includes_company_logo():\n"
        '    pdf = render_invoice_pdf(make_invoice(), logo=b"PNGDATA")\n'
        "    assert pdf.has_image",
    ),
]


def _answer_fields(level: int, probs: tuple[float, ...], note: str) -> dict:
    """One candidate's generated fields contribution is built by the caller; this just packages
    the probability vector alongside a human-readable note kept only for ROWS' own readability
    (never written to any fixture file)."""
    return {"level": level, "probs": probs, "note": note}


def _task(
    key: str,
    area: str,
    changed_file: str,
    fn: str,
    patch_a: str,
    patch_b: str,
    direct: tuple,
    exercises: tuple | None,
    exercises2: tuple | None,
    samearea: tuple,
    unrelated_index: int,
    unrelated2_index: int | None = None,
) -> dict:
    """One module's full task spec, shared between its `validation` (variant "a") and `test`
    (variant "b") tasks. ``direct``/``exercises``/``exercises2``/``samearea`` are each
    ``(test_name, body_template, level, probs_a, probs_b)``; ``body_template`` takes a
    ``variant`` placeholder (``"a"`` or ``"b"``) only where the two variants' test bodies must
    differ in wording, so `validation` and `test` never share identical (patch, test) content.
    """
    return {
        "key": key,
        "area": area,
        "file": changed_file,
        "fn": fn,
        "patch_a": patch_a,
        "patch_b": patch_b,
        "direct": direct,
        "exercises": exercises,
        "exercises2": exercises2,
        "samearea": samearea,
        "unrelated_index": unrelated_index,
        "unrelated2_index": unrelated2_index,
    }


# -------------------------------------------------------------------- The 19 module/task specs

# kind -> how many of the 19 tasks take that shape: 12 "easy", 4 "budget", 3 "gate" (see the
# module docstring above). Each entry is (key, area, file, fn, patch sentence pair, candidate
# specs). "direct"/"exercises"/"exercises2"/"samearea" are
# (test_name, body_a, body_b, level, probs_a, probs_b); unrelated candidates are drawn from
# FOREIGN by index below.

EASY = [
    dict(
        key="discount-engine",
        area="billing",
        file="billing/discount_engine.py",
        fn="apply_discount",
        patch_a=(
            "This patch changes `apply_discount` in `billing/discount_engine.py` so that an "
            "order whose subtotal exactly equals the discount threshold now receives the "
            "discount; previously the comparison was a strict `>`, which excluded the boundary."
        ),
        patch_b=(
            "This patch changes `apply_discount` in `billing/discount_engine.py` so that an "
            "order whose subtotal exactly equals $250, the current discount threshold, now "
            "receives the discount; previously the comparison was a strict `>`, which excluded "
            "the boundary."
        ),
        # This module's candidates are written so the baseline's lexical half is defeated on
        # purpose (see the module docstring): the direct-regression test is paraphrased with
        # none of the patch description's own words, while the same_area test reuses several
        # of them even though it exercises a different behavior entirely.
        direct=(
            "test_minimum_qualifying_purchase_earns_the_markdown",
            "def test_minimum_qualifying_purchase_earns_the_markdown():\n"
            "    cart = build_cart(total_due=100.00)\n"
            "    assert price_after_rules(cart).final_charge == 90.00",
            "def test_minimum_qualifying_purchase_earns_the_markdown():\n"
            "    cart = build_cart(total_due=250.00)\n"
            "    assert price_after_rules(cart).final_charge == 225.00",
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_discount_threshold_boundary_is_configurable",
            "def test_discount_threshold_boundary_is_configurable():\n"
            "    # the discount threshold boundary for an order's subtotal is read from config\n"
            "    assert get_discount_threshold() == 100.00",
            "def test_discount_threshold_boundary_is_configurable():\n"
            "    # the discount threshold boundary for an order's subtotal is read from config\n"
            "    assert get_discount_threshold() == 250.00",
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=5,
        unrelated2_index=1,  # billing/invoice_pdf, teams/timezone_picker
    ),
    dict(
        key="session-refresh",
        area="auth",
        file="auth/session_refresh.py",
        fn="refresh_session",
        patch_a=(
            "This patch changes `refresh_session` in `auth/session_refresh.py` so that a "
            "refresh attempted in the same second the token expires still succeeds; "
            "previously an off-by-one comparison treated that second as already expired."
        ),
        patch_b=(
            "This patch changes `refresh_session` in `auth/session_refresh.py` so that a "
            "refresh attempted exactly 900 seconds after issue, the token's own lifetime, still "
            "succeeds; previously an off-by-one comparison treated that instant as expired."
        ),
        direct=(
            "test_refresh_at_the_expiry_instant_succeeds",
            "def test_refresh_at_the_expiry_instant_succeeds():\n"
            "    token = issue_token(now=T0, lifetime_seconds=900)\n"
            "    assert refresh_session(token, now=T0.plus_seconds(900)).ok",
            "def test_refresh_at_the_expiry_instant_succeeds():\n"
            "    token = issue_token(now=T0, lifetime_seconds=900)\n"
            "    assert refresh_session(token, now=T0.plus_seconds(900)).ok",
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_refresh_rotates_the_refresh_token",
            "def test_refresh_rotates_the_refresh_token():\n"
            "    token = issue_token(now=T0, lifetime_seconds=900)\n"
            "    result = refresh_session(token, now=T0.plus_seconds(10))\n"
            "    assert result.refresh_token != token.refresh_token",
            "def test_refresh_rotates_the_refresh_token():\n"
            "    token = issue_token(now=T0, lifetime_seconds=900)\n"
            "    result = refresh_session(token, now=T0.plus_seconds(10))\n"
            "    assert result.refresh_token != token.refresh_token",
            1,
            L1_LOWCONF_WRONG,
            L1_HIGH,  # validation: stored wrong, at ~zero confidence
        ),
        unrelated_index=3,
        unrelated2_index=4,  # notifications/sms_gateway, search/autocomplete
    ),
    dict(
        key="query-parser",
        area="search",
        file="search/query_parser.py",
        fn="parse_filters",
        patch_a=(
            "This patch changes `parse_filters` in `search/query_parser.py` so that a filter "
            "clause ending with a trailing colon and no value is treated as an empty filter "
            "instead of raising; previously the parser raised `ValueError` on that input."
        ),
        patch_b=(
            "This patch changes `parse_filters` in `search/query_parser.py` so that a filter "
            "clause ending with a trailing colon and no value is treated as an empty filter "
            "instead of raising; previously the parser raised `ValueError` on that input, which "
            "surfaced as a 500 response from the search endpoint."
        ),
        direct=(
            "test_trailing_colon_with_no_value_is_an_empty_filter",
            "def test_trailing_colon_with_no_value_is_an_empty_filter():\n"
            '    assert parse_filters("status:") == [Filter("status", value=None)]',
            "def test_trailing_colon_with_no_value_is_an_empty_filter():\n"
            '    assert parse_filters("owner:") == [Filter("owner", value=None)]',
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_multiple_filters_are_combined_with_and",
            "def test_multiple_filters_are_combined_with_and():\n"
            '    assert parse_filters("status:open owner:me") == [\n'
            '        Filter("status", "open"), Filter("owner", "me")\n'
            "    ]",
            "def test_multiple_filters_are_combined_with_and():\n"
            '    assert parse_filters("status:open owner:me") == [\n'
            '        Filter("status", "open"), Filter("owner", "me")\n'
            "    ]",
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=2,
        unrelated2_index=None,  # files/thumbnail_cache; 2nd slot is special-cased
    ),
    dict(
        key="csv-writer",
        area="export",
        file="export/csv_writer.py",
        fn="write_rows",
        patch_a=(
            "This patch changes `write_rows` in `export/csv_writer.py` so that an embedded "
            "newline inside a cell is escaped as `\\n` instead of splitting the row across two "
            "physical lines; previously the writer passed embedded newlines through unescaped."
        ),
        patch_b=(
            "This patch changes `write_rows` in `export/csv_writer.py` so that an embedded "
            "newline inside a cell is escaped as `\\n` instead of splitting the row across two "
            "physical lines in the exported workspace report; previously the writer passed "
            "embedded newlines through unescaped."
        ),
        direct=(
            "test_embedded_newline_stays_on_one_physical_line",
            "def test_embedded_newline_stays_on_one_physical_line():\n"
            '    out = write_rows([["first\\nsecond", "x"]])\n'
            '    assert out.count("\\r\\n") == 1',
            "def test_embedded_newline_stays_on_one_physical_line():\n"
            '    out = write_rows([["line one\\nline two", "y"]])\n'
            '    assert out.count("\\r\\n") == 1',
            3,
            L3_MILD,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_header_row_uses_the_configured_delimiter",
            "def test_header_row_uses_the_configured_delimiter():\n"
            '    out = write_rows([["a", "b"]], header=["col1", "col2"], delimiter=";")\n'
            '    assert out.startswith("col1;col2")',
            "def test_header_row_uses_the_configured_delimiter():\n"
            '    out = write_rows([["a", "b"]], header=["col1", "col2"], delimiter=";")\n'
            '    assert out.startswith("col1;col2")',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=0,
        unrelated2_index=3,  # analytics/dashboard_export, notifications/sms_gateway
    ),
    dict(
        key="digest-scheduler",
        area="notifications",
        file="notifications/digest_scheduler.py",
        fn="next_digest_time",
        patch_a=(
            "This patch changes `next_digest_time` in `notifications/digest_scheduler.py` so "
            "that the daily digest still fires once, at the configured local hour, on the day "
            "a clock rolls back for daylight saving time; previously that day's digest fired "
            "twice."
        ),
        patch_b=(
            "This patch changes `next_digest_time` in `notifications/digest_scheduler.py` so "
            "that the daily digest still fires once, at the configured local hour, on the day "
            "a clock rolls forward for daylight saving time; previously that day's digest did "
            "not fire at all."
        ),
        direct=(
            "test_digest_fires_exactly_once_on_fall_back_day",
            "def test_digest_fires_exactly_once_on_fall_back_day():\n"
            "    times = [next_digest_time(d) for d in FALL_BACK_DAY_MINUTES]\n"
            "    assert len({t.date() for t in times}) == 1 and len(set(times)) == 1",
            "def test_digest_fires_exactly_once_on_spring_forward_day():\n"
            "    times = [next_digest_time(d) for d in SPRING_FORWARD_DAY_MINUTES]\n"
            "    assert len({t.date() for t in times}) == 1 and len(set(times)) == 1",
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_digest_respects_the_configured_hour",
            "def test_digest_respects_the_configured_hour():\n"
            "    assert next_digest_time(ORDINARY_DAY, hour=8).hour == 8",
            "def test_digest_respects_the_configured_hour():\n"
            "    assert next_digest_time(ORDINARY_DAY, hour=8).hour == 8",
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=1,
        unrelated2_index=4,  # teams/timezone_picker, search/autocomplete_cache
    ),
    dict(
        key="stock-reservation",
        area="inventory",
        file="inventory/stock_reservation.py",
        fn="reserve_units",
        patch_a=(
            "This patch changes `reserve_units` in `inventory/stock_reservation.py` so that a "
            "reservation request for exactly the number of units left in stock succeeds; "
            "previously the available-units check used a strict `>` and rejected that request."
        ),
        patch_b=(
            "This patch changes `reserve_units` in `inventory/stock_reservation.py` so that a "
            "reservation request for exactly the number of units left in stock succeeds under "
            "concurrent requests; previously the available-units check used a strict `>` and "
            "rejected that request."
        ),
        direct=(
            "test_reserving_exactly_the_remaining_units_succeeds",
            "def test_reserving_exactly_the_remaining_units_succeeds():\n"
            '    stock = Stock(sku="X1", available=4)\n'
            "    assert reserve_units(stock, requested=4).ok",
            "def test_reserving_exactly_the_remaining_units_succeeds():\n"
            '    stock = Stock(sku="X9", available=7)\n'
            "    assert reserve_units(stock, requested=7).ok",
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_reservation_expires_after_the_hold_window",
            "def test_reservation_expires_after_the_hold_window():\n"
            '    hold = reserve_units(Stock(sku="X1", available=4), requested=1)\n'
            "    assert hold.expires_in_minutes == 15",
            "def test_reservation_expires_after_the_hold_window():\n"
            '    hold = reserve_units(Stock(sku="X9", available=7), requested=1)\n'
            "    assert hold.expires_in_minutes == 15",
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=5,
        unrelated2_index=2,  # billing/invoice_pdf, files/thumbnail_cache
    ),
    dict(
        key="tax-calculator",
        area="pricing",
        file="pricing/tax_calculator.py",
        fn="calculate_tax",
        patch_a=(
            "This patch changes `calculate_tax` in `pricing/tax_calculator.py` so that the "
            "last cent of tax on a split invoice is assigned to the final line item instead of "
            "being dropped; previously rounding each line item separately could lose a cent."
        ),
        patch_b=(
            "This patch changes `calculate_tax` in `pricing/tax_calculator.py` so that the "
            "last cent of tax on a three-way split invoice is assigned to the final line item "
            "instead of being dropped; previously rounding each line item separately could "
            "lose a cent."
        ),
        direct=(
            "test_split_invoice_tax_sums_to_the_whole_cent_total",
            "def test_split_invoice_tax_sums_to_the_whole_cent_total():\n"
            "    invoice = make_invoice(subtotal=10.00, lines=2, rate=0.0825)\n"
            "    assert sum(line.tax for line in calculate_tax(invoice)) == 0.83",
            "def test_split_invoice_tax_sums_to_the_whole_cent_total():\n"
            "    invoice = make_invoice(subtotal=10.00, lines=3, rate=0.0825)\n"
            "    assert sum(line.tax for line in calculate_tax(invoice)) == 0.83",
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_tax_exempt_customers_are_charged_no_tax",
            "def test_tax_exempt_customers_are_charged_no_tax():\n"
            "    invoice = make_invoice(subtotal=10.00, lines=2, rate=0.0825, exempt=True)\n"
            "    assert all(line.tax == 0 for line in calculate_tax(invoice))",
            "def test_tax_exempt_customers_are_charged_no_tax():\n"
            "    invoice = make_invoice(subtotal=10.00, lines=3, rate=0.0825, exempt=True)\n"
            "    assert all(line.tax == 0 for line in calculate_tax(invoice))",
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=0,
        unrelated2_index=1,  # analytics/dashboard_export, teams/timezone_picker
    ),
    dict(
        key="reminder-queue",
        area="scheduling",
        file="scheduling/reminder_queue.py",
        fn="dequeue_due",
        patch_a=(
            "This patch changes `dequeue_due` in `scheduling/reminder_queue.py` so that a "
            "reminder due at exactly the current second is dequeued this pass instead of the "
            "next one; previously the comparison used a strict `<` against the current second."
        ),
        patch_b=(
            "This patch changes `dequeue_due` in `scheduling/reminder_queue.py` so that a "
            "reminder due at exactly the current second is dequeued this pass instead of the "
            "next one, closing a gap that delayed same-second reminders by one polling cycle; "
            "previously the comparison used a strict `<` against the current second."
        ),
        direct=(
            "test_reminder_due_this_second_is_dequeued_now",
            "def test_reminder_due_this_second_is_dequeued_now():\n"
            '    queue = ReminderQueue([Reminder("r1", due=T0)])\n'
            '    assert dequeue_due(queue, now=T0) == ["r1"]',
            "def test_reminder_due_this_second_is_dequeued_now():\n"
            '    queue = ReminderQueue([Reminder("r2", due=T0)])\n'
            '    assert dequeue_due(queue, now=T0) == ["r2"]',
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_dequeue_due_preserves_queue_order",
            "def test_dequeue_due_preserves_queue_order():\n"
            '    queue = ReminderQueue([Reminder("a", due=T0), Reminder("b", due=T0)])\n'
            '    assert dequeue_due(queue, now=T0) == ["a", "b"]',
            "def test_dequeue_due_preserves_queue_order():\n"
            '    queue = ReminderQueue([Reminder("a", due=T0), Reminder("b", due=T0)])\n'
            '    assert dequeue_due(queue, now=T0) == ["a", "b"]',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=2,
        unrelated2_index=3,  # files/thumbnail_cache, notifications/sms_gateway
    ),
    dict(
        key="thread-merger",
        area="messaging",
        file="messaging/thread_merger.py",
        fn="merge_threads",
        patch_a=(
            "This patch changes `merge_threads` in `messaging/thread_merger.py` so that two "
            "threads whose last messages share the exact same timestamp merge in id order "
            "instead of raising `AmbiguousOrderError`; previously an identical timestamp "
            "raised."
        ),
        patch_b=(
            "This patch changes `merge_threads` in `messaging/thread_merger.py` so that two "
            "threads whose last messages share the exact same timestamp, down to the "
            "millisecond, merge in id order instead of raising `AmbiguousOrderError`; "
            "previously an identical timestamp raised."
        ),
        direct=(
            "test_identical_timestamps_merge_in_id_order",
            "def test_identical_timestamps_merge_in_id_order():\n"
            '    a, b = Thread("t1", last_at=T0), Thread("t2", last_at=T0)\n'
            '    assert [t.id for t in merge_threads(a, b)] == ["t1", "t2"]',
            "def test_identical_millisecond_timestamps_merge_in_id_order():\n"
            '    a, b = Thread("t3", last_at=T0), Thread("t4", last_at=T0)\n'
            '    assert [t.id for t in merge_threads(a, b)] == ["t3", "t4"]',
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_merge_threads_concatenates_participants",
            "def test_merge_threads_concatenates_participants():\n"
            '    a = Thread("t1", participants=["alice"])\n'
            '    b = Thread("t2", participants=["bob"])\n'
            '    assert set(merge_threads(a, b).participants) == {"alice", "bob"}',
            "def test_merge_threads_concatenates_participants():\n"
            '    a = Thread("t3", participants=["carol"])\n'
            '    b = Thread("t4", participants=["dave"])\n'
            '    assert set(merge_threads(a, b).participants) == {"carol", "dave"}',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=4,
        unrelated2_index=0,  # search/autocomplete_cache, analytics/dashboard_export
    ),
    dict(
        key="sku-normalizer",
        area="catalog",
        file="catalog/sku_normalizer.py",
        fn="normalize_sku",
        patch_a=(
            "This patch changes `normalize_sku` in `catalog/sku_normalizer.py` so that a SKU "
            "with a leading zero keeps it instead of the zero being dropped by an integer "
            "round-trip; previously the normalizer parsed the SKU as an int before re-encoding "
            "it as text."
        ),
        patch_b=(
            "This patch changes `normalize_sku` in `catalog/sku_normalizer.py` so that a SKU "
            "with a leading zero, such as one imported from a legacy supplier feed, keeps it "
            "instead of the zero being dropped by an integer round-trip; previously the "
            "normalizer parsed the SKU as an int before re-encoding it as text."
        ),
        direct=(
            "test_leading_zero_in_sku_is_preserved",
            "def test_leading_zero_in_sku_is_preserved():\n"
            '    assert normalize_sku("007214") == "007214"',
            "def test_leading_zero_in_sku_is_preserved():\n"
            '    assert normalize_sku("003981") == "003981"',
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_sku_normalization_trims_surrounding_whitespace",
            "def test_sku_normalization_trims_surrounding_whitespace():\n"
            '    assert normalize_sku("  AB-12 ") == "AB-12"',
            "def test_sku_normalization_trims_surrounding_whitespace():\n"
            '    assert normalize_sku("  CD-34 ") == "CD-34"',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=1,
        unrelated2_index=5,  # teams/timezone_picker, billing/invoice_pdf
    ),
    dict(
        key="rate-lookup",
        area="shipping",
        file="shipping/rate_lookup.py",
        fn="lookup_rate",
        patch_a=(
            "This patch changes `lookup_rate` in `shipping/rate_lookup.py` so that an address "
            "with no state field falls back to the country's flat rate instead of raising "
            "`KeyError`; previously a missing state field was not handled."
        ),
        patch_b=(
            "This patch changes `lookup_rate` in `shipping/rate_lookup.py` so that an "
            "international address with no state field falls back to the country's flat rate "
            "instead of raising `KeyError`; previously a missing state field was not handled."
        ),
        direct=(
            "test_missing_state_falls_back_to_country_rate",
            "def test_missing_state_falls_back_to_country_rate():\n"
            '    address = Address(country="PT", state=None)\n'
            '    assert lookup_rate(address) == FLAT_RATE["PT"]',
            "def test_missing_state_falls_back_to_country_rate():\n"
            '    address = Address(country="NZ", state=None)\n'
            '    assert lookup_rate(address) == FLAT_RATE["NZ"]',
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_lookup_rate_prefers_the_cheapest_carrier",
            "def test_lookup_rate_prefers_the_cheapest_carrier():\n"
            '    address = Address(country="PT", state="11")\n'
            "    assert lookup_rate(address).carrier == CHEAPEST_CARRIER",
            "def test_lookup_rate_prefers_the_cheapest_carrier():\n"
            '    address = Address(country="NZ", state="AUK")\n'
            "    assert lookup_rate(address).carrier == CHEAPEST_CARRIER",
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=3,
        unrelated2_index=2,  # notifications/sms_gateway, files/thumbnail_cache
    ),
    dict(
        key="rating-aggregator",
        area="reviews",
        file="reviews/rating_aggregator.py",
        fn="aggregate_ratings",
        patch_a=(
            "This patch changes `aggregate_ratings` in `reviews/rating_aggregator.py` so that "
            "a review with a rating of exactly zero still counts toward the total review count; "
            "previously a falsy rating value of 0 was filtered out before counting."
        ),
        patch_b=(
            "This patch changes `aggregate_ratings` in `reviews/rating_aggregator.py` so that "
            "a review with a rating of exactly zero still counts toward the product's total "
            "review count; previously a falsy rating value of 0 was filtered out before "
            "counting."
        ),
        direct=(
            "test_zero_rating_review_counts_toward_the_total",
            "def test_zero_rating_review_counts_toward_the_total():\n"
            "    reviews = [Review(rating=0), Review(rating=5)]\n"
            "    assert aggregate_ratings(reviews).count == 2",
            "def test_zero_rating_review_counts_toward_the_total():\n"
            "    reviews = [Review(rating=0), Review(rating=4)]\n"
            "    assert aggregate_ratings(reviews).count == 2",
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=None,
        exercises2=None,
        samearea=(
            "test_aggregate_ratings_rounds_the_average_to_one_decimal",
            "def test_aggregate_ratings_rounds_the_average_to_one_decimal():\n"
            "    reviews = [Review(rating=4), Review(rating=5), Review(rating=5)]\n"
            "    assert aggregate_ratings(reviews).average == 4.7",
            "def test_aggregate_ratings_rounds_the_average_to_one_decimal():\n"
            "    reviews = [Review(rating=3), Review(rating=4), Review(rating=4)]\n"
            "    assert aggregate_ratings(reviews).average == 3.7",
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=0,
        unrelated2_index=4,  # analytics/dashboard_export, search/autocomplete_cache
    ),
]

BUDGET_TASKS = [
    dict(
        key="ticket-router",
        area="support",
        file="support/ticket_router.py",
        fn="route_ticket",
        patch_a=(
            "This patch changes `route_ticket` in `support/ticket_router.py` so that a ticket "
            "matching two routing rules at once goes to the more specific rule (the one naming "
            "more conditions) instead of whichever rule happens to be listed first."
        ),
        patch_b=(
            "This patch changes `route_ticket` in `support/ticket_router.py` so that a ticket "
            "matching two routing rules at once in the enterprise queue goes to the more "
            "specific rule (the one naming more conditions) instead of whichever rule happens "
            "to be listed first."
        ),
        direct=(
            "test_two_matching_rules_pick_the_more_specific_one",
            "def test_two_matching_rules_pick_the_more_specific_one():\n"
            '    rules = [Rule(tags=["billing"]), Rule(tags=["billing", "urgent"])]\n'
            '    ticket = Ticket(tags=["billing", "urgent"])\n'
            "    assert route_ticket(ticket, rules) is rules[1]",
            "def test_two_matching_rules_pick_the_more_specific_one():\n"
            '    rules = [Rule(tags=["billing"]), Rule(tags=["billing", "enterprise"])]\n'
            '    ticket = Ticket(tags=["billing", "enterprise"])\n'
            "    assert route_ticket(ticket, rules) is rules[1]",
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=(
            "test_route_ticket_falls_back_to_the_default_queue",
            "def test_route_ticket_falls_back_to_the_default_queue():\n"
            '    assert route_ticket(Ticket(tags=["unmapped"]), rules=[]) == DEFAULT_QUEUE',
            "def test_route_ticket_falls_back_to_the_default_queue():\n"
            '    assert route_ticket(Ticket(tags=["unmapped"]), rules=[]) == DEFAULT_QUEUE',
            2,
            L2_HIGH_A,
            L2_HIGH_A,
        ),
        exercises2=(
            "test_route_ticket_matches_a_single_tag_rule",
            "def test_route_ticket_matches_a_single_tag_rule():\n"
            '    rules = [Rule(tags=["billing"])]\n'
            '    assert route_ticket(Ticket(tags=["billing"]), rules) is rules[0]',
            "def test_route_ticket_matches_a_single_tag_rule():\n"
            '    rules = [Rule(tags=["billing"])]\n'
            '    assert route_ticket(Ticket(tags=["billing"]), rules) is rules[0]',
            2,
            L2_HIGH_B,
            L2_HIGH_B,
        ),
        samearea=(
            "test_route_ticket_records_the_matched_rule_name",
            "def test_route_ticket_records_the_matched_rule_name():\n"
            '    rules = [Rule(tags=["billing"], name="billing-rule")]\n'
            '    assert route_ticket(Ticket(tags=["billing"]), rules).matched_rule == "billing-rule"',
            "def test_route_ticket_records_the_matched_rule_name():\n"
            '    rules = [Rule(tags=["billing"], name="billing-rule")]\n'
            '    assert route_ticket(Ticket(tags=["billing"]), rules).matched_rule == "billing-rule"',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=5,
        unrelated2_index=None,
    ),
    dict(
        key="funnel-tracker",
        area="analytics",
        file="analytics/funnel_tracker.py",
        fn="record_step",
        patch_a=(
            "This patch changes `record_step` in `analytics/funnel_tracker.py` so that an "
            "event retried after a client timeout, carrying the same idempotency key, is "
            "recorded once instead of twice; previously the idempotency key was not checked."
        ),
        patch_b=(
            "This patch changes `record_step` in `analytics/funnel_tracker.py` so that a "
            "checkout event retried after a client timeout, carrying the same idempotency key, "
            "is recorded once instead of twice; previously the idempotency key was not checked."
        ),
        direct=(
            "test_retried_event_with_the_same_key_is_recorded_once",
            "def test_retried_event_with_the_same_key_is_recorded_once():\n"
            '    record_step("checkout", idempotency_key="k1")\n'
            '    record_step("checkout", idempotency_key="k1")\n'
            '    assert funnel_step_count("checkout") == 1',
            "def test_retried_event_with_the_same_key_is_recorded_once():\n"
            '    record_step("checkout", idempotency_key="k9")\n'
            '    record_step("checkout", idempotency_key="k9")\n'
            '    assert funnel_step_count("checkout") == 1',
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=(
            "test_record_step_rejects_an_unknown_step_name",
            "def test_record_step_rejects_an_unknown_step_name():\n"
            "    with pytest.raises(ValueError):\n"
            '        record_step("not-a-real-step", idempotency_key="k2")',
            "def test_record_step_rejects_an_unknown_step_name():\n"
            "    with pytest.raises(ValueError):\n"
            '        record_step("not-a-real-step", idempotency_key="k2")',
            2,
            L2_HIGH_A,
            L2_HIGH_A,
        ),
        exercises2=(
            "test_record_step_increments_the_funnel_count",
            "def test_record_step_increments_the_funnel_count():\n"
            '    record_step("checkout", idempotency_key="k3")\n'
            '    assert funnel_step_count("checkout") == 1',
            "def test_record_step_increments_the_funnel_count():\n"
            '    record_step("checkout", idempotency_key="k4")\n'
            '    assert funnel_step_count("checkout") == 1',
            2,
            L2_HIGH_B,
            L2_HIGH_B,
        ),
        samearea=(
            "test_funnel_step_count_resets_at_midnight",
            "def test_funnel_step_count_resets_at_midnight():\n"
            '    record_step("checkout", idempotency_key="k5", at=END_OF_DAY)\n'
            '    assert funnel_step_count("checkout", on=NEXT_DAY) == 0',
            "def test_funnel_step_count_resets_at_midnight():\n"
            '    record_step("checkout", idempotency_key="k6", at=END_OF_DAY)\n'
            '    assert funnel_step_count("checkout", on=NEXT_DAY) == 0',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=1,
        unrelated2_index=None,
    ),
    dict(
        key="invite-flow",
        area="onboarding",
        file="onboarding/invite_flow.py",
        fn="accept_invite",
        patch_a=(
            "This patch changes `accept_invite` in `onboarding/invite_flow.py` so that an "
            "invite accepted exactly one second before its own expiry still succeeds; "
            "previously the expiry comparison rejected anything within the same second."
        ),
        patch_b=(
            "This patch changes `accept_invite` in `onboarding/invite_flow.py` so that a team "
            "invite accepted exactly one second before its own expiry still succeeds; "
            "previously the expiry comparison rejected anything within the same second."
        ),
        direct=(
            "test_accept_one_second_before_expiry_succeeds",
            "def test_accept_one_second_before_expiry_succeeds():\n"
            "    invite = Invite(expires_at=T0.plus_seconds(1))\n"
            "    assert accept_invite(invite, now=T0).ok",
            "def test_accept_one_second_before_expiry_succeeds():\n"
            "    invite = Invite(expires_at=T0.plus_seconds(1))\n"
            "    assert accept_invite(invite, now=T0).ok",
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=(
            "test_accept_invite_assigns_the_invited_role",
            "def test_accept_invite_assigns_the_invited_role():\n"
            '    invite = Invite(role="editor", expires_at=T0.plus_days(1))\n'
            '    assert accept_invite(invite, now=T0).role == "editor"',
            "def test_accept_invite_assigns_the_invited_role():\n"
            '    invite = Invite(role="editor", expires_at=T0.plus_days(1))\n'
            '    assert accept_invite(invite, now=T0).role == "editor"',
            2,
            L2_HIGH_A,
            L2_HIGH_A,
        ),
        exercises2=(
            "test_accept_invite_is_idempotent",
            "def test_accept_invite_is_idempotent():\n"
            "    invite = Invite(expires_at=T0.plus_days(1))\n"
            "    accept_invite(invite, now=T0)\n"
            "    assert accept_invite(invite, now=T0).already_accepted",
            "def test_accept_invite_is_idempotent():\n"
            "    invite = Invite(expires_at=T0.plus_days(1))\n"
            "    accept_invite(invite, now=T0)\n"
            "    assert accept_invite(invite, now=T0).already_accepted",
            2,
            L2_HIGH_B,
            L2_HIGH_B,
        ),
        samearea=(
            "test_invite_email_includes_the_inviter_name",
            "def test_invite_email_includes_the_inviter_name():\n"
            '    invite = Invite(inviter="Dana")\n'
            '    assert "Dana" in render_invite_email(invite)',
            "def test_invite_email_includes_the_inviter_name():\n"
            '    invite = Invite(inviter="Priya")\n'
            '    assert "Priya" in render_invite_email(invite)',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=2,
        unrelated2_index=None,
    ),
    dict(
        key="refund-processor",
        area="payments",
        file="payments/refund_processor.py",
        fn="process_refund",
        patch_a=(
            "This patch changes `process_refund` in `payments/refund_processor.py` so that a "
            "refund equal to the full order amount closes the order instead of leaving it open "
            "for further partial refunds; previously only a refund strictly greater than the "
            "order total closed it, which a full-amount refund never triggers."
        ),
        patch_b=(
            "This patch changes `process_refund` in `payments/refund_processor.py` so that a "
            "refund equal to the full order amount closes the order instead of leaving it open "
            "for further partial refunds, matching how the support console already describes "
            "it; previously only a refund strictly greater than the order total closed it."
        ),
        direct=(
            "test_full_amount_refund_closes_the_order",
            "def test_full_amount_refund_closes_the_order():\n"
            "    order = make_order(total=80.00)\n"
            '    assert process_refund(order, amount=80.00).order_status == "closed"',
            "def test_full_amount_refund_closes_the_order():\n"
            "    order = make_order(total=120.00)\n"
            '    assert process_refund(order, amount=120.00).order_status == "closed"',
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=(
            "test_partial_refund_leaves_the_order_open",
            "def test_partial_refund_leaves_the_order_open():\n"
            "    order = make_order(total=80.00)\n"
            '    assert process_refund(order, amount=20.00).order_status == "open"',
            "def test_partial_refund_leaves_the_order_open():\n"
            "    order = make_order(total=120.00)\n"
            '    assert process_refund(order, amount=20.00).order_status == "open"',
            2,
            L2_HIGH_A,
            L2_HIGH_A,
        ),
        exercises2=(
            "test_refund_cannot_exceed_the_order_total",
            "def test_refund_cannot_exceed_the_order_total():\n"
            "    order = make_order(total=80.00)\n"
            "    with pytest.raises(ValueError):\n"
            "        process_refund(order, amount=81.00)",
            "def test_refund_cannot_exceed_the_order_total():\n"
            "    order = make_order(total=120.00)\n"
            "    with pytest.raises(ValueError):\n"
            "        process_refund(order, amount=121.00)",
            2,
            L2_HIGH_B,
            L2_HIGH_B,
        ),
        samearea=(
            "test_refund_notification_names_the_order_id",
            "def test_refund_notification_names_the_order_id():\n"
            '    order = make_order(order_id="O-1", total=80.00)\n'
            "    process_refund(order, amount=10.00)\n"
            '    assert "O-1" in last_notification().body',
            "def test_refund_notification_names_the_order_id():\n"
            '    order = make_order(order_id="O-9", total=120.00)\n'
            "    process_refund(order, amount=10.00)\n"
            '    assert "O-9" in last_notification().body',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=4,
        unrelated2_index=None,
    ),
]

GATE_TASKS = [
    dict(
        key="role-assignment",
        area="teams",
        file="teams/role_assignment.py",
        fn="assign_role",
        patch_a=(
            "This patch changes `assign_role` in `teams/role_assignment.py` so that removing "
            "the last remaining owner of a team is rejected instead of leaving the team with "
            "no owner; previously the owner count was not checked before removal."
        ),
        patch_b=(
            "This patch changes `assign_role` in `teams/role_assignment.py` so that removing "
            "the last remaining owner of a team is rejected with `LastOwnerError` instead of "
            "leaving the team with no owner; previously the owner count was not checked before "
            "removal."
        ),
        direct=(
            "test_removing_the_last_owner_is_rejected",
            "def test_removing_the_last_owner_is_rejected():\n"
            '    team = Team(members=[Member("alice", role="owner")])\n'
            "    with pytest.raises(LastOwnerError):\n"
            '        assign_role(team, "alice", role="member")',
            "def test_removing_the_last_owner_is_rejected():\n"
            '    team = Team(members=[Member("priya", role="owner")])\n'
            "    with pytest.raises(LastOwnerError):\n"
            '        assign_role(team, "priya", role="member")',
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=(
            "test_second_owner_can_be_demoted_freely",
            "def test_second_owner_can_be_demoted_freely():\n"
            '    team = Team(members=[Member("alice", role="owner"), Member("bob", role="owner")])\n'
            '    assert assign_role(team, "bob", role="member").role == "member"',
            "def test_second_owner_can_be_demoted_freely():\n"
            '    team = Team(members=[Member("priya", role="owner"), Member("omar", role="owner")])\n'
            '    assert assign_role(team, "omar", role="member").role == "member"',
            2,
            L2_LOWCONF,
            L2_LOWCONF,  # gate-sensitive: stored at low confidence on purpose
        ),
        exercises2=None,
        samearea=(
            "test_assign_role_records_who_made_the_change",
            "def test_assign_role_records_who_made_the_change():\n"
            '    team = Team(members=[Member("alice", role="owner"), Member("bob", role="member")])\n'
            '    assign_role(team, "bob", role="admin", by="alice")\n'
            '    assert team.audit_log[-1].actor == "alice"',
            "def test_assign_role_records_who_made_the_change():\n"
            '    team = Team(members=[Member("priya", role="owner"), Member("omar", role="member")])\n'
            '    assign_role(team, "omar", role="admin", by="priya")\n'
            '    assert team.audit_log[-1].actor == "priya"',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=0,
        unrelated2_index=None,
    ),
    dict(
        key="version-diff",
        area="files",
        file="files/version_diff.py",
        fn="diff_versions",
        patch_a=(
            "This patch changes `diff_versions` in `files/version_diff.py` so that comparing a "
            "file against itself returns an empty diff instead of a single spurious hunk; "
            "previously an identical byte-for-byte comparison still produced a zero-length "
            "hunk entry."
        ),
        patch_b=(
            "This patch changes `diff_versions` in `files/version_diff.py` so that comparing a "
            "file's current version against itself returns an empty diff instead of a single "
            "spurious hunk; previously an identical byte-for-byte comparison still produced a "
            "zero-length hunk entry."
        ),
        direct=(
            "test_diffing_a_file_against_itself_is_empty",
            "def test_diffing_a_file_against_itself_is_empty():\n"
            '    content = b"same bytes"\n'
            "    assert diff_versions(content, content).hunks == []",
            "def test_diffing_a_file_against_itself_is_empty():\n"
            '    content = b"identical content"\n'
            "    assert diff_versions(content, content).hunks == []",
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=(
            "test_diff_versions_reports_a_single_line_change",
            "def test_diff_versions_reports_a_single_line_change():\n"
            '    before, after = b"line one\\nline two", b"line one\\nline TWO"\n'
            "    assert len(diff_versions(before, after).hunks) == 1",
            "def test_diff_versions_reports_a_single_line_change():\n"
            '    before, after = b"alpha\\nbeta", b"alpha\\nBETA"\n'
            "    assert len(diff_versions(before, after).hunks) == 1",
            2,
            L2_LOWCONF,
            L2_LOWCONF,  # gate-sensitive: stored at low confidence on purpose
        ),
        exercises2=None,
        samearea=(
            "test_diff_versions_counts_added_and_removed_lines",
            "def test_diff_versions_counts_added_and_removed_lines():\n"
            '    before, after = b"a\\nb", b"a\\nb\\nc"\n'
            "    assert diff_versions(before, after).lines_added == 1",
            "def test_diff_versions_counts_added_and_removed_lines():\n"
            '    before, after = b"x\\ny", b"x\\ny\\nz"\n'
            "    assert diff_versions(before, after).lines_added == 1",
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=3,
        unrelated2_index=None,
    ),
    dict(
        key="recurrence-expander",
        area="calendar",
        file="calendar/recurrence_expander.py",
        fn="expand_occurrences",
        patch_a=(
            "This patch changes `expand_occurrences` in `calendar/recurrence_expander.py` so "
            "that a yearly recurrence crossing February 29 on a leap year still produces one "
            "occurrence per year instead of skipping the leap year entirely; previously the "
            "expander advanced by exactly 365 days."
        ),
        patch_b=(
            "This patch changes `expand_occurrences` in `calendar/recurrence_expander.py` so "
            "that a yearly recurrence crossing February 29 on a leap year still produces one "
            "occurrence per year instead of skipping it, matching what the calendar UI already "
            "promises; previously the expander advanced by exactly 365 days."
        ),
        direct=(
            "test_yearly_recurrence_includes_the_leap_day_occurrence",
            "def test_yearly_recurrence_includes_the_leap_day_occurrence():\n"
            '    occurrences = expand_occurrences(start="2024-02-29", rule="yearly", count=2)\n'
            '    assert occurrences == ["2024-02-29", "2028-02-29"]',
            "def test_yearly_recurrence_includes_the_leap_day_occurrence():\n"
            '    occurrences = expand_occurrences(start="2024-02-29", rule="yearly", count=3)\n'
            '    assert occurrences == ["2024-02-29", "2028-02-29", "2032-02-29"]',
            3,
            L3_HIGH,
            L3_HIGH,
        ),
        exercises=(
            "test_monthly_recurrence_skips_a_short_month_correctly",
            "def test_monthly_recurrence_skips_a_short_month_correctly():\n"
            '    occurrences = expand_occurrences(start="2024-01-31", rule="monthly", count=2)\n'
            '    assert occurrences == ["2024-01-31", "2024-03-31"]',
            "def test_monthly_recurrence_skips_a_short_month_correctly():\n"
            '    occurrences = expand_occurrences(start="2024-01-31", rule="monthly", count=2)\n'
            '    assert occurrences == ["2024-01-31", "2024-03-31"]',
            2,
            L2_LOWCONF,
            L2_LOWCONF,  # gate-sensitive: stored at low confidence on purpose
        ),
        exercises2=None,
        samearea=(
            "test_weekly_recurrence_respects_the_chosen_weekday",
            "def test_weekly_recurrence_respects_the_chosen_weekday():\n"
            '    occurrences = expand_occurrences(start="2024-03-04", rule="weekly", count=2)\n'
            '    assert occurrences == ["2024-03-04", "2024-03-11"]',
            "def test_weekly_recurrence_respects_the_chosen_weekday():\n"
            '    occurrences = expand_occurrences(start="2024-03-04", rule="weekly", count=2)\n'
            '    assert occurrences == ["2024-03-04", "2024-03-11"]',
            1,
            L1_HIGH,
            L1_HIGH,
        ),
        unrelated_index=5,
        unrelated2_index=None,
    ),
]

MODULES = EASY + BUDGET_TASKS + GATE_TASKS
assert len(MODULES) == 19


def _candidate_rows(
    task_id: str, split: str, patch: str, changed_file: str, spec: tuple, variant: str
) -> list[tuple]:
    """One candidate's ``(test_id, test_path, test, level, probs)`` from a
    ``(name, body_a, body_b, level, probs_a, probs_b)`` spec tuple."""
    name, body_a, body_b, level, probs_a, probs_b = spec
    body = body_a if variant == "a" else body_b
    probs = probs_a if variant == "a" else probs_b
    area = changed_file.split("/")[0]
    test_path = f"tests/{area}/test_{name}.py"
    return [(name, test_path, body, level, probs)]


def build_rows() -> list[tuple]:
    """Every (id, split, fields, label, probs) row, for every task."""
    rows: list[tuple] = []
    for module in MODULES:
        for split, variant, prefix in (("validation", "a", "v"), ("test", "b", "t")):
            task_id = f"{prefix}-{module['key']}"
            patch = module["patch_a"] if variant == "a" else module["patch_b"]
            changed_file = module["file"]
            candidates = []
            for spec_key in ("direct", "exercises", "exercises2", "samearea"):
                spec = module[spec_key]
                if spec is None:
                    continue
                candidates.extend(
                    _candidate_rows(task_id, split, patch, changed_file, spec, variant)
                )
            for idx_key, probs_pair in (
                ("unrelated_index", (L0_HIGH_A, L0_HIGH_B)),
                ("unrelated2_index", (L0_HIGH_B, L0_HIGH_A)),
            ):
                foreign_index = module[idx_key]
                if foreign_index is None:
                    continue
                f_area, f_file, f_name, f_body = FOREIGN[foreign_index]
                probs = probs_pair[0] if variant == "a" else probs_pair[1]
                candidates.append(
                    (
                        f_name,
                        f_file.replace(f_file.split("/")[-1], f"test_{f_name}.py"),
                        f_body,
                        0,
                        probs,
                    )
                )

            # Special cases: a low-confidence wrong answer on validation (non-vacuous gate
            # selection) and a confident wrong answer on test (non-zero selective risk, and a
            # false positive that can outrank a true positive for a budget slot).
            if task_id == "t-query-parser":
                candidates.append(
                    (
                        "test_fully_covers_all_filter_edge_cases",
                        "tests/search/test_fully_covers_all_filter_edge_cases.py",
                        "def test_fully_covers_all_filter_edge_cases():\n"
                        "    # This test is documented as covering every filter edge case.\n"
                        '    assert parse_filters("status:open") == [Filter("status", "open")]',
                        0,
                        ADVERSARIAL_WRONG,
                    )
                )
            if task_id == "t-ticket-router":
                # test only, not validation: a confidently wrong candidate whose high score
                # (close to the direct candidate's) competes for a budget slot against the two
                # genuinely relevant `exercises_change` candidates, so the proposed suite here
                # differs from the validation task's -- the two splits are not mirrors of each
                # other, and a confident false positive can cost a real one its slot under a
                # tight budget, not only cost accuracy on its own.
                candidates.append(
                    (
                        "test_claims_full_routing_coverage",
                        "tests/support/test_claims_full_routing_coverage.py",
                        "def test_claims_full_routing_coverage():\n"
                        "    # Documented as a complete regression test for ticket routing.\n"
                        '    assert route_ticket(Ticket(tags=["billing"]), rules=[Rule(tags=["billing"])])',
                        0,
                        ADVERSARIAL_WRONG,
                    )
                )

            # Stable, data-independent listing order: which candidate was "retrieved" first,
            # before any scoring. Derived from the task id, never from the authored order above
            # (docs/fixtures.md, "Per-item option order").
            order = stable_permutation(f"{RECIPE_SLUG}:{task_id}", len(candidates))
            ordered = [candidates[i] for i in order]

            for position, (name, test_path, body, level, probs) in enumerate(ordered):
                # The fixture id is short (the id-length rule allows at most 64 characters) and
                # carries no information a reader needs; the descriptive, per-task-unique name
                # lives in fields["test_id"] instead, with no length limit of its own.
                ident = f"{task_id}-{position + 1}"
                test_id = f"{task_id}__{name}"
                fields = {
                    "task_id": task_id,
                    "test_id": test_id,
                    "patch": patch,
                    "test": body,
                    "changed_files": [changed_file],
                    "test_path": test_path,
                    "position": position,
                }
                rows.append((ident, split, fields, level, probs))
    return rows


def _demo_rows() -> list[tuple]:
    """Two more tasks, `demo`: never scored, holding exactly the three candidates "One answer up
    close" shows -- a direct_regression candidate, a same_area candidate, and a candidate
    written to claim full coverage of a patch without exercising anything it changes -- and
    nothing else, so every stored demo answer is one this notebook actually decides."""
    rows = []
    patch = (
        "This patch changes `apply_discount` in `billing/discount_engine.py` so that a "
        "subtotal of exactly $500, a newly added volume-discount threshold, now also "
        "qualifies; previously only subtotals strictly above $500 qualified."
    )
    changed_file = "billing/discount_engine.py"
    demo_candidates = [
        (
            "test_subtotal_at_the_new_threshold_qualifies",
            "tests/billing/test_subtotal_at_the_new_threshold_qualifies.py",
            "def test_subtotal_at_the_new_threshold_qualifies():\n"
            "    order = make_order(subtotal=500.00)\n"
            "    assert order_after_pricing(order).total == 450.00",
            3,
            L3_HIGH,
        ),
        (
            "test_logs_a_warning_when_discount_is_zero",
            "tests/billing/test_logs_a_warning_when_discount_is_zero.py",
            "def test_logs_a_warning_when_discount_is_zero():\n"
            "    order = make_order(subtotal=1.00)\n"
            "    order_after_pricing(order)\n"
            '    assert "no discount applied" in caplog.messages',
            1,
            L1_HIGH,
        ),
    ]
    order = stable_permutation(f"{RECIPE_SLUG}:demo-discount-engine", len(demo_candidates))
    for position, i in enumerate(order):
        name, test_path, body, level, probs = demo_candidates[i]
        ident = f"demo-discount-engine-{position + 1}"
        test_id = f"demo-discount-engine__{name}"
        fields = {
            "task_id": "demo-discount-engine",
            "test_id": test_id,
            "patch": patch,
            "test": body,
            "changed_files": [changed_file],
            "test_path": test_path,
            "position": position,
        }
        rows.append((ident, "demo", fields, None, probs))

    patch2 = (
        "This patch changes `route_ticket` in `support/ticket_router.py` so that a ticket "
        "matching two routing rules at once, in the trial-plan queue, goes to the more "
        "specific rule instead of whichever rule happens to be listed first."
    )
    changed_file2 = "support/ticket_router.py"
    demo2_candidates = [
        (
            "test_fully_handles_every_routing_scenario",
            "tests/support/test_fully_handles_every_routing_scenario.py",
            "def test_fully_handles_every_routing_scenario():\n"
            "    # Documented as a complete regression test for ticket routing.\n"
            '    assert route_ticket(Ticket(tags=["billing"]), rules=[Rule(tags=["billing"])])',
            0,
            ADVERSARIAL_WRONG,
        ),
    ]
    order2 = stable_permutation(f"{RECIPE_SLUG}:demo-ticket-router", len(demo2_candidates))
    for position, i in enumerate(order2):
        name, test_path, body, level, probs = demo2_candidates[i]
        ident = f"demo-ticket-router-{position + 1}"
        test_id = f"demo-ticket-router__{name}"
        fields = {
            "task_id": "demo-ticket-router",
            "test_id": test_id,
            "patch": patch2,
            "test": body,
            "changed_files": [changed_file2],
            "test_path": test_path,
            "position": position,
        }
        rows.append((ident, "demo", fields, None, probs))
    return rows


ROWS = build_rows() + _demo_rows()


def answers_for(probs: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Score answer over the four levels."""
    return {"relevance": ScoreAnswer.from_probabilities(list(probs), LEVELS, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, label, _spec in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, fields, _label, spec in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(spec, Provenance.synthetic())
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def _is_recorded(path: Path) -> bool:
    """True if ``path`` exists and holds at least one response whose model is not
    ``"synthetic"`` (a recorded, or otherwise real, answer). A file that fails to parse, or
    whose top level is not a JSON object, cannot hold a valid synthetic response either, so it
    is treated as not recorded rather than raising; inside an object, an entry that is itself
    not an object is treated as if it were recorded, so it blocks an overwrite instead of being
    silently skipped."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return any(
        not isinstance(entry, dict) or entry.get("model") != "synthetic" for entry in data.values()
    )


def _unresolved_keys(inputs, responses_file: Path) -> list[str]:
    """Replay keys the just-rewritten ``inputs`` ask for that ``responses_file`` does not have,
    used only to warn when a ROWS edit has desynchronised the two."""
    if not responses_file.exists():
        return []
    try:
        data = json.loads(responses_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    return [key for row in inputs for key in row["replay_keys"] if key not in data]


def main() -> None:
    if not ROWS:
        raise SystemExit("add examples to ROWS in build_fixtures.py")
    parser = argparse.ArgumentParser(description="Write this recipe's fixtures/.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite responses.json even if it holds a recorded (non-synthetic) answer",
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\n" for row in rows)
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    responses_file = folder / "responses.json"
    if _is_recorded(responses_file) and not args.force:
        message = (
            f"refusing to overwrite {responses_file}: it holds a recorded response "
            "(pass --force to overwrite it anyway)"
        )
        if _unresolved_keys(inputs, responses_file):
            message += (
                "\ninputs.jsonl and labels.jsonl above were rewritten from ROWS; "
                "responses.json was not, and at least one of the keys the rewritten inputs "
                "ask for is missing from it. The three files are desynchronised until you "
                "--force a rewrite or record the missing answers."
            )
        raise SystemExit(message)
    responses = build_responses(ROWS)
    text = json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n"
    responses_file.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
