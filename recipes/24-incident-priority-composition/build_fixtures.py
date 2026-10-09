"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 24.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic: written by hand as probabilities over the four levels of each
rubric, not produced by a model. Validation tickets v01 through v16 and test tickets t01 through
t16 each cover one of the sixteen (business impact level, urgency level) pairs exactly once, so
every cell of ``helpers.PRIORITY_MATRIX`` is exercised by a realistic ticket on both splits, not
only by the unit tests in ``tests/test_helpers.py``. Both splits also carry the hard cases the
issue names: a divergent ticket where impact and urgency pull in different directions (v05/t05:
low impact, critical urgency; v06/t06: critical impact, low urgency), and a ticket where one
question is confidently answered and the other is not (v17/t17: impact confident, urgency
ambiguous; v19/t18: urgency confident, impact ambiguous). v18 is wrong at moderate confidence on
`validation` -- confident enough to matter, but not as confident as the tickets answered
correctly -- so the threshold this recipe's notebook selects on `validation` actually has to
exclude something, rather than finding every answer trustworthy by default. t19 is wrong *and*
confident on `test`, at the same confidence as several correctly-answered tickets, so it clears
whatever gate `validation` chose and the selective-prediction numbers on `test` show a real,
non-zero risk. The replay keys come from the same `build_state` and `build_questions` the
notebook uses, via `helpers.py`.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, Provenance, ScoreAnswer, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
IMPACT_LEVELS = list(helpers.IMPACT_LEVELS)
URGENCY_LEVELS = list(helpers.URGENCY_LEVELS)

# Four-level probability vectors reused across many tickets, named by what they are meant to
# show rather than repeated as bare literals. CONFIDENT peaks hard on one level (confidence
# 0.76-0.78 under the published Score confidence formula); AMBIGUOUS is nearly even, peaked
# gently on one level (confidence 0.00-0.06); MEDIUM_WRONG_IMPACT peaks at level 2 ("major") at a
# moderate confidence (0.58), used once, for the one ticket whose stored answer is wrong at a
# confidence the threshold selection must still learn to exclude.
CONFIDENT = {
    0: (0.85, 0.10, 0.03, 0.02),
    1: (0.08, 0.80, 0.08, 0.04),
    2: (0.04, 0.08, 0.80, 0.08),
    3: (0.02, 0.03, 0.10, 0.85),
}
AMBIGUOUS = {
    0: (0.28, 0.26, 0.24, 0.22),
    1: (0.24, 0.28, 0.26, 0.22),
    2: (0.22, 0.24, 0.28, 0.26),
    3: (0.22, 0.24, 0.26, 0.28),
}
MEDIUM_WRONG_IMPACT = (0.07, 0.08, 0.65, 0.20)

# (id, split, ticket_id, report text, gold label or None for demo, impact probs, urgency probs)
# Gold label is {"impact": category, "urgency": category}; the notebook derives the gold
# priority by applying the same fixed PRIORITY_MATRIX to these two gold categories, so the
# matrix is never duplicated as a separate stored value that could drift from helpers.py.
ROWS = [
    # --- validation: 19 tickets, v01-v16 cover each of the 16 matrix cells once -------------
    ("v01", "validation", "INC-7001",
     "catalog-sync is returning stale thumbnails for about 40 products in one seldom-browsed "
     "category. Checkout and pricing are unaffected, and no customer has reported it; this can "
     "be scheduled into the normal backlog with no special handling.",
     {"impact": "minor", "urgency": "low"}, CONFIDENT[0], CONFIDENT[0]),
    ("v02", "validation", "INC-7002",
     "feed-aggregator is dropping about 15% of personalized recommendation entries for "
     "logged-in users on the home feed; browsing and purchasing both still work normally. The "
     "growth team wants this fixed before the release planned for later this week.",
     {"impact": "moderate", "urgency": "medium"}, CONFIDENT[1], CONFIDENT[1]),
    ("v03", "validation", "INC-7003",
     "checkout-gateway is failing roughly 35% of card payments across every region; customers "
     "who hit the failure cannot complete a purchase at all. The failure rate has climbed twice "
     "in the last hour and support tickets are piling up.",
     {"impact": "major", "urgency": "high"}, CONFIDENT[2], CONFIDENT[2]),
    ("v04", "validation", "INC-7004",
     "auth-broker is rejecting every login attempt across the entire platform; no customer can "
     "sign in at all. The outage started eight minutes ago and is getting worse by the minute "
     "as cached sessions expire.",
     {"impact": "critical", "urgency": "critical"}, CONFIDENT[3], CONFIDENT[3]),
    ("v05-divergent", "validation", "INC-7005",
     "media-transcoder failed to prepare the one highlight video an account manager needs for "
     "a live demo to a single external partner starting in four minutes; no other customer or "
     "workflow is touched. The demo cannot proceed without it and there is no time left to "
     "reschedule.",
     {"impact": "minor", "urgency": "critical"}, CONFIDENT[0], CONFIDENT[3]),
    ("v06-divergent", "validation", "INC-7006",
     "audit-log has been silently dropping write records for every customer account for the "
     "past three weeks, leaving a required compliance audit trail incomplete platform-wide and "
     "creating real regulatory exposure. The next audit review is not scheduled for several "
     "months, so there is no immediate deadline to fix it by.",
     {"impact": "critical", "urgency": "low"}, CONFIDENT[3], CONFIDENT[0]),
    ("v07", "validation", "INC-7007",
     "notif-dispatcher is delaying password-reset emails for about a quarter of requests by up "
     "to twenty minutes; other notifications are unaffected. The delay is getting worse as the "
     "queue backs up, so a fix is needed within hours.",
     {"impact": "moderate", "urgency": "high"}, CONFIDENT[1], CONFIDENT[2]),
    ("v08", "validation", "INC-7008",
     "pricing-engine is showing the wrong discount on about half of cart totals platform-wide, "
     "undercharging customers; checkout itself still completes normally. Finance wants it "
     "corrected before this week's billing run.",
     {"impact": "major", "urgency": "medium"}, CONFIDENT[2], CONFIDENT[1]),
    ("v09", "validation", "INC-7009",
     "report-exporter's weekly CSV export is missing one optional column used only by internal "
     "analysts; no customer-facing feature is affected. The analytics team would like it back "
     "before their report is due later this week.",
     {"impact": "minor", "urgency": "medium"}, CONFIDENT[0], CONFIDENT[1]),
    ("v10", "validation", "INC-7010",
     "upload-pipeline is compressing uploaded photos more than intended for a subset of "
     "customers, reducing image quality; uploads still succeed and no revenue is affected. "
     "There is no deadline: it can go into the normal sprint.",
     {"impact": "moderate", "urgency": "low"}, CONFIDENT[1], CONFIDENT[0]),
    ("v11", "validation", "INC-7011",
     "quota-service has mis-set storage limits for a large share of accounts on one legacy "
     "plan, so many of those customers cannot upload new files at all; that plan was deprecated "
     "last year and support is not fielding active complaints yet, so there is no pressing "
     "deadline.",
     {"impact": "major", "urgency": "low"}, CONFIDENT[2], CONFIDENT[0]),
    ("v12", "validation", "INC-7012",
     "tax-calculator has been applying the wrong tax rate on every order platform-wide for the "
     "past two days, creating significant regulatory and financial exposure; finance wants it "
     "corrected within this work week as part of the scheduled billing reconciliation.",
     {"impact": "critical", "urgency": "medium"}, CONFIDENT[3], CONFIDENT[1]),
    ("v13", "validation", "INC-7013",
     "geo-router is sending a small number of requests from one minor region to the wrong data "
     "center, adding minor latency for a handful of customers; the regional on-call wants it "
     "fixed within the next few hours before their peak traffic window starts.",
     {"impact": "minor", "urgency": "high"}, CONFIDENT[0], CONFIDENT[2]),
    ("v14", "validation", "INC-7014",
     "webhook-relay has stopped delivering order-confirmation webhooks to about a third of "
     "partner integrations; those partners' systems are actively falling out of sync right now "
     "and are already escalating, so this needs a response immediately.",
     {"impact": "moderate", "urgency": "critical"}, CONFIDENT[1], CONFIDENT[3]),
    ("v15", "validation", "INC-7015",
     "session-cache is evicting active sessions for a large share of logged-in customers, "
     "logging them out mid-task across the platform; the eviction rate is climbing minute by "
     "minute and needs an immediate response.",
     {"impact": "major", "urgency": "critical"}, CONFIDENT[2], CONFIDENT[3]),
    ("v16", "validation", "INC-7016",
     "sso-gateway is issuing session tokens that never expire for every customer platform-wide, "
     "a severe security exposure; the fix needs to ship within the next few hours before the "
     "exposure is discovered more widely.",
     {"impact": "critical", "urgency": "high"}, CONFIDENT[3], CONFIDENT[2]),
    ("v17-one-confident", "validation", "INC-7017",
     "invoice-renderer is attaching the wrong line items to about forty percent of invoices "
     "sent to customers platform-wide, a clear and ongoing effect on customer trust and support "
     "load. The ticket does not yet say how quickly the team wants this handled.",
     {"impact": "major", "urgency": "medium"}, CONFIDENT[2], AMBIGUOUS[1]),
    ("v18-wrong", "validation", "INC-7018",
     "search-index is returning slightly stale results for about a fifth of searches "
     "platform-wide for the last day; most searches still return current results and customers "
     "can still find what they need. There is no deadline: the search team can pick this up in "
     "normal planning.",
     {"impact": "moderate", "urgency": "low"}, MEDIUM_WRONG_IMPACT, CONFIDENT[0]),
    ("v19-one-confident", "validation", "INC-7019",
     "ledger-api has started rejecting a growing share of payout requests to sellers, and the "
     "rejection rate is climbing by the minute; this needs an immediate response. The team is "
     "still assessing exactly how many sellers and how much revenue this affects.",
     {"impact": "major", "urgency": "critical"}, AMBIGUOUS[2], CONFIDENT[3]),
    # --- test: 19 tickets, t01-t16 cover each of the 16 matrix cells once --------------------
    ("t01", "test", "INC-8001",
     "catalog-sync is showing an outdated badge icon for about 25 products in one niche "
     "category; no other feature or customer workflow is affected. There's no rush: it can "
     "wait for the normal backlog.",
     {"impact": "minor", "urgency": "low"}, CONFIDENT[0], CONFIDENT[0]),
    ("t02", "test", "INC-8002",
     "feed-aggregator is missing secondary images for roughly 10% of listings in the "
     "recommendation carousel; the main feed and purchasing flow work normally. The growth team "
     "wants it fixed sometime this week.",
     {"impact": "moderate", "urgency": "medium"}, CONFIDENT[1], CONFIDENT[1]),
    ("t03", "test", "INC-8003",
     "checkout-gateway is timing out on about 30% of checkout attempts across every region, "
     "and affected customers cannot finish buying anything. The failure rate has been rising "
     "for the last hour, so this needs attention within hours.",
     {"impact": "major", "urgency": "high"}, CONFIDENT[2], CONFIDENT[2]),
    ("t04", "test", "INC-8004",
     "auth-broker just started rejecting every sign-in attempt platform-wide with no "
     "workaround; the outage began minutes ago and is actively spreading as more sessions "
     "expire, so a response is needed right now.",
     {"impact": "critical", "urgency": "critical"}, CONFIDENT[3], CONFIDENT[3]),
    ("t05-divergent", "test", "INC-8005",
     "media-transcoder failed to render the one sizzle reel an account manager needs for a "
     "client pitch starting in five minutes; no other customer or workflow is touched. There is "
     "no time left to work around it.",
     {"impact": "minor", "urgency": "critical"}, CONFIDENT[0], CONFIDENT[3]),
    ("t06-divergent", "test", "INC-8006",
     "audit-log has been missing write records for every customer account for over a month, "
     "leaving a platform-wide compliance gap with real regulatory exposure. The next scheduled "
     "compliance review is not for several months, so there's no immediate deadline.",
     {"impact": "critical", "urgency": "low"}, CONFIDENT[3], CONFIDENT[0]),
    ("t07", "test", "INC-8007",
     "notif-dispatcher is delaying shipping-confirmation emails for about a fifth of orders by "
     "up to half an hour; other notification types are unaffected. The backlog is growing, so "
     "this needs a fix within hours.",
     {"impact": "moderate", "urgency": "high"}, CONFIDENT[1], CONFIDENT[2]),
    ("t08", "test", "INC-8008",
     "pricing-engine is applying the wrong currency conversion on about 40% of international "
     "orders platform-wide, overcharging customers; checkout still completes normally "
     "otherwise. Finance wants it fixed before this week's reconciliation.",
     {"impact": "major", "urgency": "medium"}, CONFIDENT[2], CONFIDENT[1]),
    ("t09", "test", "INC-8009",
     "report-exporter's monthly internal summary is missing one chart used only by one "
     "analyst; no customer-facing system is touched. The analyst would like it restored "
     "sometime this week.",
     {"impact": "minor", "urgency": "medium"}, CONFIDENT[0], CONFIDENT[1]),
    ("t10", "test", "INC-8010",
     "upload-pipeline is adding a faint watermark to a subset of uploaded photos by mistake; "
     "uploads still succeed and no revenue is affected. There's no deadline: it can go into the "
     "normal queue.",
     {"impact": "moderate", "urgency": "low"}, CONFIDENT[1], CONFIDENT[0]),
    ("t11", "test", "INC-8011",
     "quota-service has set storage limits far too low for a large share of accounts on one "
     "retired plan, blocking many of those customers from uploading anything; that plan has "
     "almost no active users left and nobody has escalated, so there's no pressing deadline.",
     {"impact": "major", "urgency": "low"}, CONFIDENT[2], CONFIDENT[0]),
    ("t12", "test", "INC-8012",
     "tax-calculator has been using an expired tax table for every order platform-wide for the "
     "past three days, creating significant regulatory and financial exposure; finance wants it "
     "corrected within this work week alongside the scheduled reconciliation.",
     {"impact": "critical", "urgency": "medium"}, CONFIDENT[3], CONFIDENT[1]),
    ("t13", "test", "INC-8013",
     "geo-router is adding a small amount of extra latency for a handful of customers in one "
     "minor region; the regional on-call wants it fixed within the next few hours before their "
     "peak traffic window.",
     {"impact": "minor", "urgency": "high"}, CONFIDENT[0], CONFIDENT[2]),
    ("t14", "test", "INC-8014",
     "webhook-relay has stopped delivering shipment-update webhooks to about a third of partner "
     "integrations; those partners' systems are falling out of sync right now and are already "
     "escalating, so this needs an immediate response.",
     {"impact": "moderate", "urgency": "critical"}, CONFIDENT[1], CONFIDENT[3]),
    ("t15", "test", "INC-8015",
     "session-cache is evicting active sessions for a large share of customers platform-wide, "
     "logging them out mid-checkout; the eviction rate is climbing minute by minute and needs "
     "an immediate response.",
     {"impact": "major", "urgency": "critical"}, CONFIDENT[2], CONFIDENT[3]),
    ("t16", "test", "INC-8016",
     "sso-gateway is accepting expired session tokens for every customer platform-wide, a "
     "severe security exposure; the fix needs to ship within the next few hours before this is "
     "discovered more widely.",
     {"impact": "critical", "urgency": "high"}, CONFIDENT[3], CONFIDENT[2]),
    ("t17-one-confident", "test", "INC-8017",
     "invoice-renderer is attaching the wrong line items to about forty percent of invoices "
     "sent to customers platform-wide, a clear and ongoing effect on customer trust and support "
     "load. It isn't clear from the ticket yet how quickly the team wants this handled.",
     {"impact": "major", "urgency": "high"}, CONFIDENT[2], AMBIGUOUS[2]),
    ("t18-one-confident", "test", "INC-8018",
     "ledger-api has started rejecting a growing share of refund requests, and the rejection "
     "rate is climbing by the minute; this needs an immediate response. The team does not yet "
     "know how many customers or how much revenue this touches.",
     {"impact": "moderate", "urgency": "critical"}, AMBIGUOUS[1], CONFIDENT[3]),
    ("t19-wrong", "test", "INC-8019",
     "search-index is returning results a few minutes out of date for about one in twenty "
     "searches platform-wide; nearly every search still returns current results and no "
     "checkout or account flow is touched. There's no deadline: the team can schedule this "
     "into normal planning.",
     {"impact": "minor", "urgency": "low"}, CONFIDENT[2], CONFIDENT[0]),
    # --- demo: 2 tickets, shown but never scored ---------------------------------------------
    ("d01-divergent", "demo", "INC-9001",
     "media-transcoder failed to generate the one highlight clip an account manager needs for "
     "a sponsor call starting in three minutes; no other customer or workflow is affected. "
     "There is no time left to find a workaround.",
     None, CONFIDENT[0], CONFIDENT[3]),
    ("d02-aligned", "demo", "INC-9002",
     "auth-broker is rejecting every login attempt platform-wide right now, with no workaround "
     "available; the outage began two minutes ago and is actively getting worse as more "
     "sessions expire.",
     None, CONFIDENT[3], CONFIDENT[3]),
]  # fmt: skip


def answers_for(impact_probs, urgency_probs, provenance: Provenance) -> dict:
    """{question name: answer} for one row: two independent Score answers, one per rubric."""
    return {
        "business_impact": ScoreAnswer.from_probabilities(
            list(impact_probs), IMPACT_LEVELS, provenance
        ),
        "urgency": ScoreAnswer.from_probabilities(list(urgency_probs), URGENCY_LEVELS, provenance),
    }


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, ticket_id, text, label, _impact_probs, _urgency_probs in rows:
        fields = {"ticket_id": ticket_id, "report": text}
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, ticket_id, text, _label, impact_probs, urgency_probs in rows:
        fields = {"ticket_id": ticket_id, "report": text}
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(impact_probs, urgency_probs, Provenance.synthetic())
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
    # The same serialization jev_cookbook.live._dump writes: only the top-level keys are
    # sorted; each response keeps the field order DecisionResult.to_dict() emits. Matching the
    # recorder exactly, rather than json.dumps(..., sort_keys=True) (which also sorts every
    # nested dict alphabetically), keeps a recording's diff to the values that actually changed.
    text = json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n"
    responses_file.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
