"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 46.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic and deliberately imperfect: most rows predict the gold level
correctly, a few are confidently wrong (the lexical-overlap trap a purely keyword-driven judge
would fall into), and a few are genuinely unsure (they land below the confidence gate the
notebook freezes on validation). See docs/fixtures.md and recipes/_template/build_fixtures.py.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from ROWS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.

**Reading ROWS.** Each task is one pool of chunks: a task description, then chunks oldest-last
(index 0 is the most recently added chunk in that task's pool, so ``recency_rank`` is just the
chunk's position). Each chunk carries its gold rubric level (0 NOT_RELEVANT .. 3 NEEDED), the
level the synthetic answer is built to *peak* at (equal to gold except where the comment says
"wrong"), and a confidence tier ("high" ~0.85-0.91, "medium" ~0.48-0.52, "low" ~0.27-0.33, from
:func:`level_probs`'s geometric decay around the peak). A pool whose gold-NEEDED chunk sits at
index 0 is a task where the recency baseline (keep the most recently added chunks) finds the
needed chunk for free; a pool whose gold-NEEDED chunk sits at the *oldest* index is one where it
does not -- both shapes are built on purpose, so the recall comparison in the notebook is earned
rather than assumed (see the notebook's evaluation section for why this matters).
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, Provenance, ScoreAnswer, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
LEVELS = list(helpers.RELEVANCE_LEVELS)


def _int_pow(base: float, exponent: int) -> float:
    """``base ** exponent`` for a non-negative int ``exponent``, by repeated multiplication
    only, never Python's ``**``: CPython routes ``float.__pow__`` to the platform's libm
    ``pow()``, whose last-bit result is not guaranteed stable across interpreter builds or
    libm versions, where a single IEEE-754 multiply has no such gap."""
    result = 1.0
    for _ in range(exponent):
        result *= base
    return result


def _float_sum(values: list[float]) -> float:
    """Left-to-right ``a + b + c + ...``, by hand, never the builtin ``sum()``.

    Verified directly (not merely argued) to matter here: for the raw, un-normalized levels
    this recipe's "medium", peak-0 tier produces (``[1.0, 0.35, 0.1225, 0.042875]``), Python
    3.10's ``sum()`` returns ``1.5153750000000001`` while 3.14's returns ``1.515375`` -- CPython
    changed the builtin's float-summation algorithm between those versions, and a plain
    left-to-right loop (confirmed identical on both) is what ``build_fixtures.py``'s own
    comment, before this fix, mistakenly assumed ``sum`` already was. ``float ** int`` (see
    :func:`_int_pow`) was a real, necessary fix for a second, independent nondeterminism and is
    not sufficient on its own: both had to go for the committed fixtures to reproduce byte for
    byte across the Python versions this repository tests
    (``tests/test_build_fixtures.py``'s byte-identical check, run on both).
    """
    total = 0.0
    for v in values:
        total += v
    return total


def level_probs(peak: int, tier: str) -> list[float]:
    """A probability distribution over the 4 rubric levels, peaked at ``peak``, shaped by
    ``tier`` ("high", "medium" or "low") through a geometric decay away from the peak: probs[i]
    is proportional to ``decay ** |i - peak|`` (computed by :func:`_int_pow` and
    :func:`_float_sum`, never Python's ``**`` or builtin ``sum``). This lands the published
    Score confidence formula (``1 - spread/even``, ``even == 1.0`` for 4 levels) in a
    predictable band per tier without hand-solving the formula for every row: roughly 0.85-0.91
    for "high", 0.48-0.52 for "medium", 0.27-0.33 for "low", over the four possible peaks.
    """
    decay = {"high": 0.08, "medium": 0.35, "low": 0.5}[tier]
    raw = [_int_pow(decay, abs(i - peak)) for i in range(4)]
    total = _float_sum(raw)
    return [r / total for r in raw]


def _pool(task_id: str, split: str, task: str, chunks: list[tuple]) -> list[tuple]:
    """``chunks``: ``(chunk_id, content, source, gold_level, peak_level, tier)``, newest first
    (index 0). Returns ROWS entries: ``(id, split, fields, label, spec)``."""
    rows = []
    for rank, (chunk_id, content, source, gold, peak, tier) in enumerate(chunks):
        fields = {
            "task_id": task_id,
            "task": task,
            "chunk_id": chunk_id,
            "chunk": content,
            "source": source,
            "recency_rank": rank,
        }
        rows.append((f"{task_id}-{chunk_id}", split, fields, gold, (peak, tier)))
    return rows


# -- validation: 6 independent tasks, 5 chunks each (30 rows), 3 domains x (recency-right,
# recency-wrong). "recency-right" means the single NEEDED chunk sits at recency_rank 0 (the
# recency baseline finds it for free); "recency-wrong" means it sits at the oldest rank (the
# recency baseline misses it, however the semantic judgment does).

V1 = _pool(  # domain: refunds, recency-right
    "v1", "validation",
    "Confirm to the customer why order ORD-5521's refund was $18.40 instead of the full $23.00 "
    "they paid, and cite the policy that applies.",
    [
        ("r0", "Refund policy v3 (effective this month): a $4.60 restocking fee applies to any "
               "opened-box return, deducted automatically before the refund is issued.",
         "runbook:refund-policy-v3#step4", 3, 3, "high"),
        ("r1", "Order ORD-5521 shows the box was marked 'opened' at receiving, received "
               "2026-10-09.", "ticket:5521#msg2", 2, 2, "medium"),
        ("r2", "General note: refund processing usually completes within 3-5 business days of "
               "approval.", "runbook:refund-policy-v3#step1", 1, 1, "medium"),
        ("r3", "Customer also asked, in the same message, about changing their shipping address "
               "for a future order.", "ticket:5521#msg4", 0, 0, "high"),
        ("r4", "Unrelated: order ORD-5519's package was marked delivered but the customer says "
               "it never arrived.", "ticket:5519#msg1", 0, 0, "medium"),
    ],
)  # fmt: skip

V2 = _pool(  # domain: refunds, recency-wrong, plus one confidently-wrong lexical-overlap row
    "v2", "validation",
    "Confirm to the customer why order ORD-6680's refund was declined entirely, and cite the "
    "policy that applies.",
    [
        ("r0", "Customer also mentioned, in the same message, that they want to subscribe to "
               "the newsletter.", "ticket:6680#msg5", 0, 0, "high"),
        ("r1", "Unrelated: a separate customer asked about gift-wrapping options this week.",
         "ticket:6711#msg1", 0, 0, "medium"),
        # Wrong, confidently: this chunk is BACKGROUND (level 1), but its own words -- "declined
        # refunds" -- lexically echo the task's "declined" word, which is exactly the lookalike a
        # purely keyword-driven judge would fall for. The synthetic answer is built to fall for it
        # (peak 3, high confidence) on purpose.
        ("r2", "General note: declined refunds are logged in the billing system under reason "
               "code R-07.", "runbook:refund-policy-v3#step7", 1, 3, "high"),
        ("r3", "Order ORD-6680 was placed using a promotional gift card, not a standard payment "
               "method.", "ticket:6680#msg2", 2, 2, "medium"),
        ("r4", "Refund policy v3: items purchased with a non-refundable promotional gift card "
               "are final sale and cannot be refunded, no exceptions.",
         "runbook:refund-policy-v3#step9", 3, 3, "high"),
    ],
)  # fmt: skip

V3 = _pool(  # domain: auth/session, recency-right, plus one low-confidence (review) row
    "v3", "validation",
    "Explain to the on-call engineer why user sessions for tenant ACME-12 are being logged out "
    "every 10 minutes instead of the usual 8 hours.",
    [
        ("r0", "Deploy 2026-10-12 changed the default session TTL for SSO tenants from 8h to "
               "10m in config/session.yaml; tenants not explicitly overridden inherit the new "
               "default.", "code:config/session.yaml#commit-a91", 3, 3, "high"),
        ("r1", "Tenant ACME-12 uses SSO login, confirmed in the tenant settings table.",
         "ticket:9002#msg1", 2, 2, "medium"),
        # Wrong, unsurely: BACKGROUND (level 1), but a reader could plausibly mistake "signed
        # against the auth service's public key" for part of the TTL explanation above -- the
        # synthetic answer is built to make exactly that mistake, at low confidence.
        ("r2", "General note: session tokens are signed JWTs validated against the auth "
               "service's public key.", "runbook:auth-overview#step2", 1, 2, "low"),
        ("r3", "Unrelated: tenant ACME-12 also reported a slow dashboard load time last week.",
         "ticket:8990#msg3", 0, 0, "high"),
        ("r4", "Unrelated: a different tenant, GLOBEX-3, asked about enabling two-factor "
               "authentication.", "ticket:8850#msg1", 0, 0, "medium"),
    ],
)  # fmt: skip

V4 = _pool(  # domain: auth/session, recency-wrong
    "v4", "validation",
    "Explain to the on-call engineer why user ID u-77231 cannot log in at all, even once, this "
    "morning.",
    [
        ("r0", "Unrelated: the on-call channel also discussed this morning's standup schedule "
               "change.", "slack:#oncall#msg88", 0, 0, "medium"),
        ("r1", "General note: failed logins are rate-limited after 5 attempts within a minute.",
         "runbook:auth-overview#step5", 1, 1, "medium"),
        ("r2", "Unrelated: user u-77231 opened a separate ticket last month about a billing "
               "question.", "ticket:7701#msg1", 0, 0, "high"),
        ("r3", "User u-77231's account was flagged for a password reset after a "
               "suspicious-login alert two days ago.", "ticket:9050#msg1", 2, 2, "medium"),
        ("r4", "A password reset flag blocks all login attempts, including correct passwords, "
               "until the user completes the reset flow; this is documented as the single known "
               "cause of a 'cannot log in at all' report with no error shown.",
         "runbook:auth-overview#step9", 3, 3, "high"),
    ],
)  # fmt: skip

V5 = _pool(  # domain: deploys, recency-right
    "v5", "validation",
    "Determine whether last night's deploy of the checkout service is safe to leave running, or "
    "must be rolled back.",
    [
        ("r0", "Checkout service deploy 2026-10-13 23:40 UTC: error rate on /checkout/submit "
               "rose from 0.2% to 6.1% within 10 minutes of rollout and has not recovered.",
         "monitor:checkout-errors#alert-441", 3, 3, "high"),
        ("r1", "The deploy's changelog lists a change to the payment-provider timeout from 3s "
               "to 1s.", "code:CHANGELOG.md#entry-2026-10-13", 2, 2, "medium"),
        ("r2", "General note: checkout service deploys are gated behind a canary stage before "
               "full rollout.", "runbook:deploy-process#step3", 1, 1, "medium"),
        ("r3", "Unrelated: the search service had a scheduled maintenance window last night, "
               "unaffected by this deploy.", "runbook:deploy-process#step11", 0, 0, "high"),
        ("r4", "Unrelated: last month's checkout deploy was rolled back for an unrelated "
               "styling bug.", "ticket:4410#msg1", 0, 0, "medium"),
    ],
)  # fmt: skip

V6 = _pool(  # domain: deploys, recency-wrong, plus one low-confidence (review) row
    "v6", "validation",
    "Determine whether the search service's deploy from three days ago is still the cause of "
    "today's slow search results.",
    [
        ("r0", "Unrelated: today's on-call handoff notes mention the checkout service, not "
               "search.", "slack:#oncall#msg120", 0, 0, "medium"),
        # Wrong, unsurely: BACKGROUND (level 1), but a reader could plausibly mistake a latency
        # metric's definition for evidence the deploy under discussion changed that metric --
        # the synthetic answer is built to make exactly that mistake, at low confidence.
        ("r1", "General note: search latency is measured as p95 response time on "
               "/search/query.", "runbook:deploy-process#step7", 1, 2, "low"),
        ("r2", "Unrelated: three days ago the checkout service also deployed, in a separate "
               "pipeline.", "code:CHANGELOG.md#entry-2026-10-10", 0, 0, "high"),
        ("r3", "The search service's deploy from three days ago added a new relevance-ranking "
               "model.", "code:CHANGELOG.md#entry-2026-10-10b", 2, 2, "medium"),
        ("r4", "The search service's p95 latency returned to baseline the day after that "
               "deploy, per the dashboard; today's slowness started only this morning, four "
               "hours ago, well after the deploy stabilized.",
         "monitor:search-latency#report-2026-10-13", 3, 3, "high"),
    ],
)  # fmt: skip

# -- test: 4 independent tasks of varying pool size (20 rows), plus one 3-turn stateful session
# over a shared, persistent chunk pool (15 rows) -- deliberately a different shape from
# validation (different task count, different pool sizes, different mix of recency-right and
# recency-wrong, and the session has no validation counterpart at all), so freezing the
# confidence gate on validation and applying it here tests the gate against a split it could not
# have been shaped to match.

T1 = _pool(  # domain: rate limits, recency-right, pool of 4
    "t1", "test",
    "Determine the correct rate limit tier for API key key-884 before increasing a customer's "
    "quota.",
    [
        ("r0", "API key key-884 was upgraded to the 'partner' tier yesterday, which allows "
               "5000 requests/minute instead of the default 100.", "ticket:9500#msg3", 3, 3, "high"),
        ("r1", "Customer asked for their quota to be doubled from the current limit.",
         "ticket:9500#msg1", 2, 2, "medium"),
        ("r2", "General note: tier changes take effect within 15 minutes of being applied.",
         "runbook:rate-limits#step4", 1, 1, "medium"),
        ("r3", "Unrelated: a different customer asked about webhook retry behavior last week.",
         "ticket:9112#msg1", 0, 0, "high"),
    ],
)  # fmt: skip

T2 = _pool(  # domain: rate limits, recency-wrong, pool of 6
    "t2", "test",
    "Determine why API key key-991 is being rate-limited at only 100 requests/minute despite "
    "being on the 'partner' tier.",
    [
        ("r0", "Unrelated: this morning's status page update was about a scheduled database "
               "maintenance.", "slack:#status#msg201", 0, 0, "high"),
        ("r1", "Unrelated: a different partner-tier key, key-770, is rate-limiting correctly at "
               "5000/minute.", "ticket:9600#msg1", 0, 0, "medium"),
        ("r2", "General note: rate limits are enforced per API key, not per account.",
         "runbook:rate-limits#step1", 1, 1, "medium"),
        ("r3", "Key-991's tier field reads 'partner' in the account dashboard.",
         "ticket:9601#msg1", 2, 2, "medium"),
        ("r4", "Unrelated: the customer also asked about invoice formatting in the same "
               "message.", "ticket:9601#msg2", 0, 0, "high"),
        ("r5", "A known bug (unresolved): the rate limiter reads a cached tier value that is "
               "only refreshed on login, so a tier upgrade has no effect for a key that has not "
               "logged in since the upgrade.", "runbook:rate-limits#step9", 3, 3, "high"),
    ],
)  # fmt: skip

T3 = _pool(  # domain: refunds, recency-right, pool of 5
    "t3", "test",
    "Confirm whether order ORD-7342 qualifies for a full refund under the holiday return "
    "policy.",
    [
        ("r0", "Holiday return policy: orders placed between Nov 1 and Dec 24 qualify for a "
               "full refund with no restocking fee through Jan 31, regardless of box "
               "condition.", "runbook:refund-policy-v3#step12", 3, 3, "high"),
        ("r1", "Order ORD-7342 was placed on 2026-11-15.", "ticket:7342#msg1", 2, 2, "medium"),
        ("r2", "General note: the holiday policy supersedes the standard restocking-fee rule "
               "for its date range.", "runbook:refund-policy-v3#step11", 1, 1, "medium"),
        ("r3", "Unrelated: the customer also asked about gift receipts.", "ticket:7342#msg3",
         0, 0, "high"),
        ("r4", "Unrelated: a different order, ORD-7300, was already fully refunded last week.",
         "ticket:7300#msg2", 0, 0, "medium"),
    ],
)  # fmt: skip

T4 = _pool(  # domain: auth/session, recency-wrong, plus one confidently-wrong lexical-overlap row
    "t4", "test",
    "Explain why tenant GLOBEX-3's SSO login now redirects to an error page instead of signing "
    "users in.",
    [
        ("r0", "Unrelated: GLOBEX-3 also asked about exporting usage reports this week.",
         "ticket:9700#msg1", 0, 0, "medium"),
        # Wrong, confidently: BACKGROUND (level 1), but "SSO redirect errors" and "error code"
        # echo the task's own "redirects to an error page" -- the test-split lexical-overlap trap
        # the strong-form test needs (recipes/46.../tests/test_helpers.py).
        ("r1", "General note: SSO redirect errors are logged with an error code in the auth "
               "service's access log.", "runbook:auth-overview#step7", 1, 3, "high"),
        ("r2", "Unrelated: a different tenant's SSO integration was set up successfully "
               "yesterday.", "ticket:9680#msg1", 0, 0, "high"),
        ("r3", "GLOBEX-3's SSO certificate was due to expire at the end of this month.",
         "ticket:9650#msg2", 2, 2, "medium"),
        ("r4", "GLOBEX-3's SSO certificate expired at midnight last night; the auth service "
               "rejects the SAML assertion and redirects to the generic error page whenever the "
               "tenant's certificate has expired.", "runbook:auth-overview#step12", 3, 3, "high"),
    ],
)  # fmt: skip

# -- the stateful session: one shared pool of chunks (ORD-8800), paged across three turns with
# the SAME jev_cookbook.simulation.Store, as the task in front of the engineer changes. Chunk ids
# are shared across turns on purpose (s-c1..s-c6), so the notebook can show the same chunk's
# status changing turn to turn -- paged out, later rehydrated -- while its content and source
# never do. ``recency_rank`` is recomputed each turn over the chunks known as of that turn.

S1 = _pool(  # turn 1: 4 chunks, the NEEDED chunk is the OLDEST (recency-wrong)
    "s-t1", "test",
    "Figure out why order ORD-8800's refund amount shown to the customer doesn't match what "
    "was approved.",
    [
        ("s-c4", "Unrelated: the customer also asked about tracking a different order, "
                 "ORD-8777.", "ticket:8800#msg5", 0, 0, "high"),
        ("s-c3", "General note: refund confirmation emails are generated by a separate billing "
                 "microservice.", "runbook:refund-policy-v3#step14", 1, 1, "medium"),
        ("s-c2", "Customer's refund confirmation email shows $37.50.", "ticket:8800#msg4",
         2, 2, "medium"),
        ("s-c1", "Approved refund for ORD-8800: $42.00, approved 2026-10-11 by agent review.",
         "ticket:8800#msg2", 3, 3, "high"),
    ],
)  # fmt: skip

S2 = _pool(  # turn 2: a new chunk (s-c5) arrives; the task sharpens; recency is RIGHT this turn
    "s-t2", "test",
    "Now explain to the customer specifically why the emailed amount ($37.50) differs from the "
    "approved amount ($42.00).",
    [
        ("s-c5", "The billing microservice applies a $4.50 payment-processor fee to the emailed "
                 "confirmation amount but not to the internally approved amount; this is a "
                 "known display inconsistency, not a billing error.",
         "code:billing/refund_email.py#L142", 3, 3, "high"),
        ("s-c1", "Approved refund for ORD-8800: $42.00, approved 2026-10-11 by agent review.",
         "ticket:8800#msg2", 2, 2, "medium"),
        ("s-c2", "Customer's refund confirmation email shows $37.50.", "ticket:8800#msg4",
         2, 2, "medium"),
        ("s-c3", "General note: refund confirmation emails are generated by a separate billing "
                 "microservice.", "runbook:refund-policy-v3#step14", 1, 1, "medium"),
        ("s-c4", "Unrelated: the customer also asked about tracking a different order, "
                 "ORD-8777.", "ticket:8800#msg5", 0, 0, "high"),
    ],
)  # fmt: skip

S3 = _pool(  # turn 3: a new, conflicting chunk (s-c6) arrives; s-c3 is rehydrated; recency-wrong
    "s-t3", "test",
    "A second customer now reports the same $37.50-vs-$42.00 discrepancy on a different order; "
    "confirm whether the same explanation still applies or whether something changed.",
    [
        # Conflicting / adversarial: newest, on-topic by its own words, and still correctly
        # judged NOT_RELEVANT -- an unreviewed draft that contradicts the documented behaviour is
        # not something the task's answer should depend on, whatever its age.
        ("s-c6", "A customer-support macro drafted this week suggests telling customers the "
                 "discrepancy is 'typically a bank processing delay, not a fee' -- this macro "
                 "has not been reviewed by billing and contradicts the documented fee "
                 "behaviour.", "slack:#support-macros#msg55", 0, 0, "high"),
        ("s-c5", "The billing microservice applies a $4.50 payment-processor fee to the emailed "
                 "confirmation amount but not to the internally approved amount; this is a "
                 "known display inconsistency, not a billing error.",
         "code:billing/refund_email.py#L142", 2, 2, "medium"),
        ("s-c1", "Approved refund for ORD-8800: $42.00, approved 2026-10-11 by agent review.",
         "ticket:8800#msg2", 1, 1, "medium"),
        ("s-c2", "Customer's refund confirmation email shows $37.50.", "ticket:8800#msg4",
         1, 1, "medium"),
        # Rehydrated: paged out on turns 1 and 2 (BACKGROUND both times), now the single
        # reusable explanation a second, different customer's case depends on.
        ("s-c3", "General note: refund confirmation emails are generated by a separate billing "
                 "microservice.", "runbook:refund-policy-v3#step14", 3, 3, "high"),
        ("s-c4", "Unrelated: the customer also asked about tracking a different order, "
                 "ORD-8777.", "ticket:8800#msg5", 0, 0, "medium"),
    ],
)  # fmt: skip

# -- demo: shown individually in "One answer up close", never scored (no label). Mirrors
# recipe 17's not-relevant / supporting / needed / adversarial sequence.
DEMO = _pool(
    "d1", "demo",
    "Decide whether it's safe to deploy the invoicing service right now.",
    [
        ("not-relevant",
         "Unrelated: the marketing team asked about updating the homepage banner copy this "
         "week.", "slack:#marketing#msg12", None, 0, "high"),
        ("supporting",
         "The invoicing service's last deploy was three days ago and has been stable since.",
         "monitor:invoicing-errors#report-2026-10-11", None, 2, "medium"),
        ("needed",
         "A company-wide deploy freeze is in effect from 2026-10-13 18:00 UTC through "
         "2026-10-14 09:00 UTC for the quarter-end billing close; no production deploys are "
         "permitted during that window.", "runbook:deploy-process#step1", None, 3, "high"),
        # Adversarial: contains the word "freeze" twice, by name, and states nothing about any
        # freeze being in effect -- the keyword-overlap trap the notebook discusses by hand.
        ("adversarial",
         "The invoicing service's deploy pipeline is named "
         "'invoicing-deploy-freeze-check' after an old incident; the name does not reflect any "
         "current freeze.", "code:ci/pipelines.yml#L4", None, 3, "high"),
    ],
)  # fmt: skip

ROWS = V1 + V2 + V3 + V4 + V5 + V6 + T1 + T2 + T3 + T4 + S1 + S2 + S3 + DEMO


def answers_for(spec, provenance: Provenance):
    """{question name: answer} for one row. ``spec`` is ``(peak_level, confidence_tier)``."""
    peak, tier = spec
    probs = level_probs(peak, tier)
    answer = ScoreAnswer.from_probabilities(probs, LEVELS, provenance)
    return {"relevance": answer}


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
    parser = argparse.ArgumentParser(description="Write this recipe's fixtures/.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite responses.json even if it holds a recorded (non-synthetic) answer",
    )
    args = parser.parse_args()
    if not ROWS:
        raise SystemExit("TODO: add examples to ROWS in build_fixtures.py")
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
