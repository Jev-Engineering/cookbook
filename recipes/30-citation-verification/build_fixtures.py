"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 30.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic and deliberately imperfect: some are wrong, including some wrong
*and* confident, so the evaluation in the notebook has something real to find. Unlike every
other recipe's ``build_fixtures.py``, not every row asks Jev anything at all: a row whose
citation does not resolve against ``helpers.CORPUS`` (an unknown document, an unknown section,
or both) never reaches the model, so it carries no replay key and no stored response --
``docs/fixtures.md`` ("Replay and scripted recipes") allows ``replay_keys`` to be empty for an
example. ``spec`` is ``None`` for exactly those rows; every other row's ``spec`` is a target
confidence, written as the number a reader of the notebook will see, from which ``_dist`` below
derives the probabilities that reproduce it exactly through
``jev_cookbook.answers.choice_confidence``'s published formula.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from ROWS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
OPTIONS = helpers.OPTIONS  # (supported, unsupported, contradicted)
SUPPORTED, UNSUPPORTED, CONTRADICTED = OPTIONS


def _fields(claim, doc, section):
    return {"claim": claim, "doc": doc, "section": section}


def _dist(top, confidence):
    """Probabilities over OPTIONS whose Choice confidence is exactly ``confidence``.

    ``jev_cookbook.answers.choice_confidence`` rescales the top probability by the number of
    options: ``confidence = (p_max - 1/3) / (1 - 1/3)``, so ``p_max = (confidence + 0.5) / 1.5``
    for these three options. Writing the target confidence directly, rather than a probability
    a reader would have to run through that formula themselves, keeps every number ROWS states
    the same one the notebook and this file's own docstring report. The remaining probability
    is split evenly between the other two options.
    """
    p_max = (confidence + 0.5) / 1.5
    rest = (1.0 - p_max) / 2.0
    return {name: (p_max if name == top else rest) for name in OPTIONS}


# --------------------------------------------------------------------------------------
# Claims against a small corpus of fabricated internal documentation (helpers.CORPUS). No
# fixture here names a real product, vendor or policy. A citation is a (doc, section) pair;
# Python resolves it before any claim reaches the model (helpers.resolve_citation).
#
# (id, split, fields, gold label or None for a demo example, target confidence or None)
# ``None`` for the last element means the citation does not resolve: no question is ever
# built for this row, so there is nothing to answer and no response to store.
# ======================================================================================
# validation -- 19 examples: 3 citations that do not resolve (forced unsupported, no model
# call), 6 supported, 5 contradicted (one -- v-c5-wrong-low -- wrong and hedged below the
# gate), 5 unsupported (two off-topic, three citing a real but wrong passage for an
# otherwise correct claim -- the hard case this use case names -- one of which,
# v-u3-wrongpassage, the stored answer gets wrong and confident).
# ======================================================================================
ROWS = [
    (
        "v-broken-01",
        "validation",
        _fields(
            "API keys with partner status automatically receive a 20% discount on monthly "
            "billing.",
            "BILLING-TERMS",
            "1",
        ),
        UNSUPPORTED,
        None,
    ),
    (
        "v-broken-02",
        "validation",
        _fields(
            "Access tokens can be revoked immediately by calling the logout endpoint.",
            "AUTH-TOKENS",
            "9",
        ),
        UNSUPPORTED,
        None,
    ),
    (
        "v-broken-03",
        "validation",
        _fields(
            "Workspace administrators can restore a permanently erased file within 24 hours "
            "of deletion.",
            "STORAGE-QUOTAS",
            "5",
        ),
        UNSUPPORTED,
        None,
    ),
    (
        "v-s1",
        "validation",
        _fields(
            "The public API's default rate limit is 100 requests per minute for each API key.",
            "RATE-LIMITS",
            "1",
        ),
        SUPPORTED,
        0.88,
    ),
    (
        "v-s2",
        "validation",
        _fields(
            "An access token issued by the login endpoint expires 15 minutes after it is "
            "issued.",
            "AUTH-TOKENS",
            "1",
        ),
        SUPPORTED,
        0.80,
    ),
    (
        "v-s3",
        "validation",
        _fields(
            "After a 503 response, a client should wait at least 2 seconds before retrying, "
            "doubling the wait each time, for up to 5 attempts.",
            "RETRY-POLICY",
            "1",
        ),
        SUPPORTED,
        0.75,
    ),
    (
        "v-s4",
        "validation",
        _fields(
            "A workspace on the standard plan can store up to 50 GB of attached files.",
            "STORAGE-QUOTAS",
            "1",
        ),
        SUPPORTED,
        0.70,
    ),
    (
        "v-s5",
        "validation",
        _fields(
            "A verified partner can request a rate limit as high as 1,000 requests per "
            "minute through the partner portal.",
            "RATE-LIMITS",
            "3",
        ),
        SUPPORTED,
        0.64,
    ),
    (
        "v-s6",
        "validation",
        _fields(
            "Refresh tokens expire 30 days after they are issued, or sooner if the account's "
            "password changes.",
            "AUTH-TOKENS",
            "2",
        ),
        SUPPORTED,
        0.58,
    ),
    (
        "v-c1",
        "validation",
        _fields(
            "The public API's default rate limit is 500 requests per minute for each API key.",
            "RATE-LIMITS",
            "1",
        ),
        CONTRADICTED,
        {CONTRADICTED: 0.82},
    ),
    (
        "v-c2",
        "validation",
        _fields(
            "An expired access token can be renewed directly, without requesting a new one "
            "from the login endpoint.",
            "AUTH-TOKENS",
            "1",
        ),
        CONTRADICTED,
        {CONTRADICTED: 0.77},
    ),
    (
        "v-c3",
        "validation",
        _fields(
            "A client should automatically retry a 400 response, since the problem might be "
            "transient.",
            "RETRY-POLICY",
            "2",
        ),
        CONTRADICTED,
        {CONTRADICTED: 0.68},
    ),
    (
        "v-c4",
        "validation",
        _fields(
            "The enterprise plan's storage limit for attached files is the same 50 GB as the "
            "standard plan.",
            "STORAGE-QUOTAS",
            "1",
        ),
        CONTRADICTED,
        {CONTRADICTED: 0.60},
    ),
    (
        "v-c5-wrong-low",
        "validation",
        _fields(
            "A client should retry a 503 response immediately, with no wait, as many times "
            "as needed.",
            "RETRY-POLICY",
            "1",
        ),
        CONTRADICTED,
        # Wrong (hedged to unsupported) and below the gate: caught by the confidence threshold
        # either way, so this is the mistake the gate is built to catch, not the one that gets
        # through.
        {UNSUPPORTED: 0.30},
    ),
    (
        "v-u1",
        "validation",
        _fields(
            "Partner accounts receive a discount on their monthly subscription fee.",
            "RATE-LIMITS",
            "3",
        ),
        UNSUPPORTED,
        {UNSUPPORTED: 0.55},
    ),
    (
        "v-u2",
        "validation",
        _fields(
            "Access tokens are signed using a 2048-bit RSA key.",
            "AUTH-TOKENS",
            "3",
        ),
        UNSUPPORTED,
        {UNSUPPORTED: 0.50},
    ),
    (
        "v-u3-wrongpassage",
        "validation",
        _fields(
            # Correct claim, wrong passage: the true, supporting content is AUTH-TOKENS§2,
            # not the access-token expiry section this cites. The stored answer gets this
            # wrong and confident -- exactly the hard case this use case names.
            "Refresh tokens expire 30 days after they are issued.",
            "AUTH-TOKENS",
            "1",
        ),
        UNSUPPORTED,
        {SUPPORTED: 0.72},
    ),
    (
        "v-u4-wrongpassage",
        "validation",
        _fields(
            # Correct claim, wrong passage: the true content is RATE-LIMITS§1, not the
            # partner quota-increase section this cites.
            "The default rate limit for the public API is 100 requests per minute.",
            "RATE-LIMITS",
            "3",
        ),
        UNSUPPORTED,
        {UNSUPPORTED: 0.62},
    ),
    (
        "v-u5-wrongpassage",
        "validation",
        _fields(
            # Correct claim, wrong passage: the true content is STORAGE-QUOTAS§3, not the
            # upload-size section this cites.
            "Deleted files are retained for 14 days before being permanently erased.",
            "STORAGE-QUOTAS",
            "2",
        ),
        UNSUPPORTED,
        {UNSUPPORTED: 0.45},
    ),
    # ======================================================================================
    # test -- 19 examples, the same shape as validation: 3 citations that do not resolve, 6
    # supported, 5 contradicted (one -- t-c5-wrong -- wrong and confidently above the frozen
    # gate: the costly mistake this recipe is built to show), 5 unsupported (two off-topic,
    # three wrong-passage, one of which -- t-u3-wrongpassage -- is also wrong and confident).
    # ======================================================================================
    (
        "t-broken-01",
        "test",
        _fields(
            "Partner accounts are exempt from the workspace storage quota entirely.",
            "PARTNER-TERMS",
            "2",
        ),
        UNSUPPORTED,
        None,
    ),
    (
        "t-broken-02",
        "test",
        _fields(
            "A refresh token can be used to mint a new refresh token with a fresh 30-day "
            "expiry.",
            "AUTH-TOKENS",
            "8",
        ),
        UNSUPPORTED,
        None,
    ),
    (
        "t-broken-03",
        "test",
        _fields(
            "An uploaded file can be split automatically to get under the 2 GB upload limit.",
            "STORAGE-QUOTAS",
            "6",
        ),
        UNSUPPORTED,
        None,
    ),
    (
        "t-s1",
        "test",
        _fields(
            "Each API key is limited to 100 requests per minute by default.",
            "RATE-LIMITS",
            "1",
        ),
        SUPPORTED,
        0.86,
    ),
    (
        "t-s2",
        "test",
        _fields(
            "Once issued, a login access token is valid for 15 minutes and must then be "
            "replaced by a new one from the login endpoint.",
            "AUTH-TOKENS",
            "1",
        ),
        SUPPORTED,
        0.78,
    ),
    (
        "t-s3",
        "test",
        _fields(
            "A 503 response should trigger a retry no sooner than 2 seconds later, with the "
            "wait doubling each time, up to 5 tries.",
            "RETRY-POLICY",
            "1",
        ),
        SUPPORTED,
        0.73,
    ),
    (
        "t-s4",
        "test",
        _fields(
            "Standard-plan workspaces can store up to 50 GB of attached files.",
            "STORAGE-QUOTAS",
            "1",
        ),
        SUPPORTED,
        0.68,
    ),
    (
        "t-s5",
        "test",
        _fields(
            "Three API keys on one account each get their own 100-requests-per-minute "
            "limit, rather than sharing one.",
            "RATE-LIMITS",
            "4",
        ),
        SUPPORTED,
        0.61,
    ),
    (
        "t-s6",
        "test",
        _fields(
            "A password change immediately expires any outstanding refresh token, even "
            "before its normal 30-day limit.",
            "AUTH-TOKENS",
            "2",
        ),
        SUPPORTED,
        0.56,
    ),
    (
        "t-c1",
        "test",
        _fields(
            "Each API key may make up to 500 requests per minute by default.",
            "RATE-LIMITS",
            "1",
        ),
        CONTRADICTED,
        {CONTRADICTED: 0.84},
    ),
    (
        "t-c2",
        "test",
        _fields(
            "A 422 response should be retried automatically a few times before giving up.",
            "RETRY-POLICY",
            "2",
        ),
        CONTRADICTED,
        {CONTRADICTED: 0.79},
    ),
    (
        "t-c3",
        "test",
        _fields(
            "A 3 GB file upload is accepted as long as the workspace still has quota "
            "remaining.",
            "STORAGE-QUOTAS",
            "2",
        ),
        CONTRADICTED,
        {CONTRADICTED: 0.66},
    ),
    (
        "t-c4",
        "test",
        _fields(
            "The rate limit resets exactly on the calendar minute, so a 100-request burst "
            "just before the minute and another just after cannot both succeed.",
            "RATE-LIMITS",
            "2",
        ),
        CONTRADICTED,
        {CONTRADICTED: 0.59},
    ),
    (
        "t-c5-wrong",
        "test",
        _fields(
            "A payment submission is retried automatically without needing any idempotency "
            "key.",
            "RETRY-POLICY",
            "3",
        ),
        CONTRADICTED,
        # Wrong and confidently above the frozen gate (chosen on validation, below): the
        # costly mistake this recipe is built to show, not caught by the threshold.
        {SUPPORTED: 0.52},
    ),
    (
        "t-u1",
        "test",
        _fields(
            "Tokens are encoded using a proprietary binary format for faster parsing.",
            "AUTH-TOKENS",
            "3",
        ),
        UNSUPPORTED,
        {UNSUPPORTED: 0.54},
    ),
    (
        "t-u2",
        "test",
        _fields(
            "Idempotency keys must be valid UUIDs.",
            "RETRY-POLICY",
            "3",
        ),
        UNSUPPORTED,
        {UNSUPPORTED: 0.48},
    ),
    (
        "t-u3-wrongpassage",
        "test",
        _fields(
            # Correct claim, wrong passage: the true content is RATE-LIMITS§3, not the
            # per-key-counter section this cites. Wrong and confidently above the gate.
            "A verified partner can request a rate limit increase up to 1,000 requests per "
            "minute.",
            "RATE-LIMITS",
            "4",
        ),
        UNSUPPORTED,
        {SUPPORTED: 0.60},
    ),
    (
        "t-u4-wrongpassage",
        "test",
        _fields(
            # Correct claim, wrong passage: the true content is AUTH-TOKENS§1, not the
            # audience-claim section this cites.
            "Access tokens expire 15 minutes after being issued.",
            "AUTH-TOKENS",
            "3",
        ),
        UNSUPPORTED,
        {UNSUPPORTED: 0.49},
    ),
    (
        "t-u5-wrongpassage",
        "test",
        _fields(
            # Correct claim, wrong passage: the true content is STORAGE-QUOTAS§3, not the
            # standard/enterprise capacity section this cites. Low confidence: this is one the
            # gate itself catches, sent to review rather than answered either way.
            "Deleted files remain recoverable for 14 days before permanent erasure.",
            "STORAGE-QUOTAS",
            "1",
        ),
        UNSUPPORTED,
        {UNSUPPORTED: 0.44},
    ),
    # -- demo: shown to the reader, never scored. ------------------------------------------
    (
        "demo-01-no-document",
        "demo",
        _fields(
            "Backups of deleted files are kept for 90 days before being purged.",
            "BACKUP-POLICY",
            "1",
        ),
        None,
        None,
    ),
    (
        "demo-02-wrong-passage",
        "demo",
        _fields(
            "A refresh token stays valid for 30 days unless the account's password changes "
            "first.",
            "AUTH-TOKENS",
            "1",
        ),
        None,
        {UNSUPPORTED: 0.60},
    ),
]  # fmt: skip


def answers_for(spec, provenance: Provenance):
    """``{"relation": ChoiceAnswer}`` from a row's ``spec``.

    ``spec`` is a target confidence (the stored answer's top choice is ``supported``) or a
    one-entry ``{top: confidence}`` mapping when the stored answer is wrong (its top choice is
    not the gold label, named explicitly so a reader does not have to infer it)."""
    if isinstance(spec, dict):
        (top, confidence) = next(iter(spec.items()))
    else:
        top, confidence = SUPPORTED, spec
    return {"relation": ChoiceAnswer.from_probabilities(_dist(top, confidence), provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded.

    A row whose ``spec`` is ``None`` is a citation that does not resolve: ``helpers.build_state``
    must never be called for it (it raises for exactly this case), so its replay keys are the
    empty list, not a key derived from a state that was never built -- ``docs/fixtures.md``
    allows this ("Replay and scripted recipes")."""
    inputs, labels = [], []
    for ident, split, fields, label, spec in rows:
        keys = [] if spec is None else [replay_key(helpers.build_state(fields), QUESTIONS)]
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response. A row whose ``spec`` is ``None``
    contributes no entry at all: there is no request to answer."""
    responses = {}
    for _ident, _split, fields, _label, spec in rows:
        if spec is None:
            continue
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
        raise SystemExit("add examples to ROWS in build_fixtures.py")
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
