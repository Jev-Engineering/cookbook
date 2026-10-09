"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 18.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect. The hard cases the issue names all appear: true duplicates (several,
across most of the eight open incidents), near duplicates that read almost the same as an open
incident but name a different affected service (the use case's central trap: text similarity
alone is not enough, and the shared ``shortlist`` retrieval in ``helpers.py`` ranks on text
alone, on purpose, so a look-alike on the wrong service is retrieved right next to the real
incident it echoes), and tickets that match nothing in the open pool at all.

Four examples are wrong on purpose, in four different ways, so the lesson is honest about what a
confidence gate can and cannot catch. On `validation`: `v08-near-search-wrong` reports a
confident, real (but wrong) candidate for a ticket that actually names a different service, so
the gate chosen below excludes it -- this is the one wrong `validation` answer that gives
`select_confidence_threshold` a real cut to make (see docs/fixtures.md's note that a fixture set
where every answer is right models nothing). Two ambiguous-but-correct `validation` tickets
(`v12`, `v13`) sit at a lower confidence than that wrong one, so excluding it also means losing
them to review -- the coverage cost of the gate, not a flaw in it. On `test`: `t07-near-cart-wrong`
is the same trap as `v08`, but confident enough to clear the frozen gate -- a real, wrong link the
confidence gate lets through (this is this recipe's false merge: Python's simulated side effect,
linking two incidents together, actually fires on a wrong pair). `t11-dup-auth-missed` is a real
duplicate reported as `no_match`, confidently -- wrong, and never checked by any confidence gate at
all, because `no_match` bypasses the gate entirely, the same way it does in recipe 08. `t12-dup-search-
lowconf` is wrong and caught (low confidence, sent to review). `t13-ambiguous-billing` is correct
but held back by the same low confidence. The replay keys come from the same ``build_state`` and
``build_questions`` the notebook uses, via ``helpers.py``; because the option list depends on the
shortlist Python retrieves for that ticket's own symptoms, each row's key is computed from that
ticket's own question.

Generating inputs and labels is kept separate from generating responses, on purpose (the pattern
``recipes/_template/build_fixtures.py`` sets): once responses.json holds even one recorded answer
(provenance "recorded", captured from a real Jev call), running this script again must not
silently replace it with a synthetic probability. inputs.jsonl and labels.jsonl are always
rewritten from ROWS, because neither ever holds a model's answer; responses.json is rewritten only
when it does not yet exist, holds only synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)


def dist(candidates: list[str], **given: float) -> dict[str, float]:
    """A full probability mapping over ``candidates + [no_match]``: ``given`` names the
    option(s) that carry real mass; every other option shares the remainder evenly."""
    options = [*candidates, helpers.NO_MATCH]
    missing = [o for o in options if o not in given]
    remainder = 1.0 - sum(given.values())
    share = remainder / len(missing) if missing else 0.0
    result = {o: share for o in missing}
    result.update(given)
    return result


def _fields(ticket_id: str, service: str, symptoms: str) -> dict[str, str]:
    return {"ticket_id": ticket_id, "service": service, "symptoms": symptoms}


# (id, split, ticket_id, service, symptoms, gold label or None for demo, stored probabilities
# given as {option: p} -- see `dist` above; remaining options share what is left)
ROWS = [
    # --- validation: 14 examples, one of them wrong -----------------------------------------
    ("v01-dup-checkout", "validation", _fields(
        "TCK-1001", "checkout-api",
        "Customers see a 500 error at payment confirmation when they apply a promo code during checkout."),
     "INC-101", {"INC-101": 0.88}),
    ("v02-dup-auth", "validation", _fields(
        "TCK-1002", "auth-service",
        "Several users report being signed out in the middle of their session without any error message."),
     "INC-102", {"INC-102": 0.88}),
    ("v03-dup-search", "validation", _fields(
        "TCK-1003", "search-index",
        "Searches that returned results yesterday now return zero results for the exact same queries."),
     "INC-103", {"INC-103": 0.88}),
    ("v04-dup-email", "validation", _fields(
        "TCK-1004", "email-notifications",
        "Order confirmation emails are taking well over two hours to arrive after checkout."),
     "INC-104", {"INC-104": 0.88}),
    ("v05-dup-billing", "validation", _fields(
        "TCK-1005", "billing-gateway",
        "Some valid cards with available funds are being declined intermittently at checkout."),
     "INC-105", {"INC-105": 0.88}),
    # Near duplicate of INC-102 (auth-service), but this ticket is about the admin-dashboard
    # service: correctly read as no_match.
    ("v06-near-auth-wrongservice", "validation", _fields(
        "TCK-1006", "admin-dashboard",
        "Several admin-dashboard users are signed out mid-session without any error message shown."),
     "no_match", {"no_match": 0.75}),
    # Near duplicate of INC-103 (search-index), but this ticket is about the internal support
    # tool: correctly read as no_match.
    ("v07-near-search-wrongservice", "validation", _fields(
        "TCK-1007", "internal-support-tool",
        "Searches in the internal support tool return zero results for queries that matched yesterday."),
     "no_match", {"no_match": 0.78}),
    # The same trap as v07, worded closer to INC-103's own text -- and here the stored answer
    # gets it wrong: a confident, real candidate (INC-103) for a ticket that names a different
    # service. This is the one wrong validation answer (see the module docstring): without it,
    # select_confidence_threshold would have nothing real to cut on.
    ("v08-near-search-wrong", "validation", _fields(
        "TCK-1008", "internal-support-tool",
        "Searches on the partner portal return zero results for terms that matched items yesterday."),
     "no_match", {"INC-103": 0.42}),
    ("v09-nomatch-rss", "validation", _fields(
        "TCK-1009", "blog-cms",
        "The company blog's RSS feed has stopped validating and readers cannot subscribe to new posts."),
     "no_match", {"no_match": 0.80}),
    ("v10-nomatch-pdf", "validation", _fields(
        "TCK-1010", "billing-documents",
        "The printable PDF invoice template renders with the wrong logo color in the header."),
     "no_match", {"no_match": 0.82}),
    ("v11-nomatch-status", "validation", _fields(
        "TCK-1011", "status-page",
        "The public status page does not reflect scheduled maintenance windows correctly."),
     "no_match", {"no_match": 0.76}),
    # Correct, but at a low confidence (0.38 -> (0.38-0.25)/0.75 = 0.1733): below the gate the
    # evaluation freezes, so it is held for review despite naming the right incident.
    ("v12-ambiguous-checkout-cart", "validation", _fields(
        "TCK-1012", "checkout-api",
        "Checkout throws an error when a promo code is applied, and the cart subtotal also looks off."),
     "INC-101", {"INC-101": 0.38}),
    # Correct, at an even lower confidence (0.33 -> 0.1067): held for review for the same reason.
    ("v13-ambiguous-mobile", "validation", _fields(
        "TCK-1013", "mobile-app",
        "A few users mention the app behaving oddly right after opening it since the latest update."),
     "INC-107", {"INC-107": 0.33}),
    ("v14-dup-autocomplete", "validation", _fields(
        "TCK-1014", "search-index",
        "Autocomplete keeps suggesting items from a completely different product category as you type."),
     "INC-108", {"INC-108": 0.88}),
    # --- test: 14 examples, four of them wrong in four different ways -----------------------
    ("t01-dup-cart", "test", _fields(
        "TCK-2001", "checkout-api",
        "After a second item is added to the cart, the subtotal shown on screen does not update."),
     "INC-106", {"INC-106": 0.90}),
    ("t02-dup-mobile", "test", _fields(
        "TCK-2002", "mobile-app",
        "The app crashes right after opening on every phone that just updated to the newest OS."),
     "INC-107", {"INC-107": 0.90}),
    ("t03-dup-autocomplete", "test", _fields(
        "TCK-2003", "search-index",
        "Autocomplete is suggesting items from the wrong product category as soon as you start typing."),
     "INC-108", {"INC-108": 0.90}),
    ("t04-dup-checkout", "test", _fields(
        "TCK-2004", "checkout-api",
        "A 500 error appears at payment confirmation whenever a promo code is applied during checkout."),
     "INC-101", {"INC-101": 0.90}),
    # Near duplicate of INC-104 (email-notifications), but this ticket is about SMS: correctly
    # read as no_match (its exact confidence does not matter: no_match bypasses the gate).
    ("t05-near-email-wrongservice", "test", _fields(
        "TCK-2005", "sms-notifications",
        "Order confirmation text messages are taking more than two hours to arrive after checkout."),
     "no_match", {"no_match": 0.78}),
    # Near duplicate of INC-105 (billing-gateway), but this ticket is about refunds: correctly
    # read as no_match.
    ("t06-near-billing-wrongservice", "test", _fields(
        "TCK-2006", "refunds-service",
        "Some valid refund requests with available funds are being declined intermittently."),
     "no_match", {"no_match": 0.80}),
    # Near duplicate of INC-106 (checkout-api cart), but this ticket is about a wishlist, worded
    # close enough to INC-106 that the stored answer wrongly links it there, confidently (0.90
    # -> 0.8667, above the frozen gate). This is this recipe's false merge: the one case where
    # the simulated side effect (linking two incidents) actually fires on a wrong pair.
    ("t07-near-cart-wrong", "test", _fields(
        "TCK-2007", "wishlist-service",
        "After a second item is added to the wishlist, the subtotal count shown on screen does not update."),
     "no_match", {"INC-106": 0.90}),
    ("t08-nomatch-timeoff", "test", _fields(
        "TCK-2008", "hr-portal",
        "The employee time-off request form fails to submit whenever it is filed on a Friday."),
     "no_match", {"no_match": 0.82}),
    ("t09-nomatch-newsletter", "test", _fields(
        "TCK-2009", "marketing-site",
        "The marketing newsletter unsubscribe link redirects readers to a broken page."),
     "no_match", {"no_match": 0.74}),
    ("t10-nomatch-slack", "test", _fields(
        "TCK-2010", "internal-tools",
        "The internal Slack integration stopped posting deploy notifications to the team channel."),
     "no_match", {"no_match": 0.80}),
    # A real duplicate of INC-102, but the stored answer confidently says no_match -- wrong, and
    # no_match is never checked by any threshold, so this missed duplicate is not caught by
    # anything (unlike t07 above, it is not a false merge either: no_match triggers no side
    # effect at all, so nothing is linked to anything here).
    ("t11-dup-auth-missed", "test", _fields(
        "TCK-2011", "auth-service",
        "A growing number of users get signed out partway through a session with nothing shown on screen."),
     "INC-102", {"no_match": 0.75}),
    # A real duplicate of INC-103, but the stored answer names a different real candidate
    # (INC-101), and only at a low confidence: wrong, and caught by the gate (sent to review).
    ("t12-dup-search-lowconf", "test", _fields(
        "TCK-2012", "search-index",
        "A couple of searches that worked fine yesterday are coming back empty today."),
     "INC-103", {"INC-101": 0.30}),
    # Correct, but at a low confidence (0.35 -> 0.1333): held for review despite naming the
    # right incident, the same shape as v12/v13 above.
    ("t13-ambiguous-billing", "test", _fields(
        "TCK-2013", "billing-gateway",
        "A handful of customers mention their card being charged oddly around checkout this week."),
     "INC-105", {"INC-105": 0.35}),
    # A second, differently-worded near duplicate of INC-106, read correctly as no_match this
    # time -- the contrast with t07 above shows the same underlying trap landing both ways.
    ("t14-near-cart-wrongservice", "test", _fields(
        "TCK-2014", "wishlist-service",
        "After a second item is added to the wishlist, the item count shown on screen does not update."),
     "no_match", {"no_match": 0.76}),
    # --- demo: 2 examples, shown but never scored --------------------------------------------
    ("d01-near-billing-wrongservice", "demo", _fields(
        "TCK-3001", "wallet-service",
        "Some wallet balance transfers with available funds are being declined intermittently."),
     None, {"no_match": 0.70}),
    ("d02-nomatch-clean", "demo", _fields(
        "TCK-3002", "docs-site",
        "The documentation site's search bar highlights the wrong section when you click a result."),
     None, {"no_match": 0.85}),
]  # fmt: skip


def candidates_for(symptoms: str) -> list[str]:
    """The shortlist order for this ticket's symptoms, matching ``helpers.build_questions``."""
    return helpers.shortlist(symptoms)


def answers_for(symptoms: str, spec: dict[str, float], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over that ticket's own
    shortlist plus no_match."""
    return {"match": ChoiceAnswer.from_probabilities(spec, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, label, _spec in rows:
        candidates = candidates_for(fields["symptoms"])
        questions = helpers.build_questions(candidates)
        key = replay_key(helpers.build_state(fields), questions)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, fields, _label, given in rows:
        candidates = candidates_for(fields["symptoms"])
        questions = helpers.build_questions(candidates)
        key = replay_key(helpers.build_state(fields), questions)
        spec = dist(candidates, **given)
        answers = answers_for(fields["symptoms"], spec, Provenance.synthetic())
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
