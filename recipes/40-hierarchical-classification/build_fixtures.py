"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 40.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic and deliberately imperfect: include some wrong answers and the
hard cases the use case names. See docs/fixtures.md and recipes/_template/build_fixtures.py.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from ROWS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.

This recipe asks four independent requests for every example -- the department, a topic
question for each of the two real departments its own department probabilities rank highest
(CONTRIBUTING.md section 3: a question that depends on an earlier answer goes in a later
request, so topic can never share a request with department), and the flat baseline's single
combined question -- so every row's ``spec`` below carries all four, and ``requests_for``
replaces the template's one-request-per-row ``answers_for``.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

DEPARTMENT_QUESTION = helpers.build_department_question()
FLAT_QUESTION = helpers.build_flat_question()
TOPIC_QUESTIONS = {d: helpers.build_topic_question(d) for d in helpers.REAL_DEPARTMENTS}


def _top2_real_departments(department_probs: dict) -> list[str]:
    """The two real departments ``helpers.rank_real_departments`` would rank highest for this
    distribution, computed the identical way (probability descending, ties by name) so a row's
    authored ``topics`` spec can be checked against it instead of hand-counted."""
    return sorted(helpers.REAL_DEPARTMENTS, key=lambda d: (-department_probs[d], d))[:2]


def _lean(options, correct, high):
    """A probability dict leaning on ``correct`` at ``high``; every other name in ``options``
    splits the remainder evenly. A small, transparent spread used for the "clear" rows below,
    not a hidden default: every call names its own ``correct`` explicitly, and the gold label
    a row is scored against is always a separate argument in ``ROWS``, never read back out of
    this spread (CONTRIBUTING.md's "never derive one gold label from another", applied to a
    stored answer instead of a second label)."""
    others = [o for o in options if o != correct]
    remainder = (1.0 - high) / len(others)
    return {correct: high} | {o: remainder for o in others}


def _generic_topics(*departments):
    """A plausible, low-stakes topic answer for each of ``departments``: never the winning
    path on a clear row (see ``clear_spec``), so only its validity, not its content, matters."""
    return {
        department: _lean(
            helpers.LEAVES_BY_DEPARTMENT[department],
            helpers.LEAVES_BY_DEPARTMENT[department][0],
            0.5,
        )
        for department in departments
    }


def clear_spec(department, topic, path_high=0.80):
    """The stored-answer spec for a document that is a clear, correctly-answered example of
    ``department``/``topic``: a confident department answer; for a real department, a
    confident topic answer for the department that answer ranks highest (which ``_lean`` makes
    ``department`` itself) and a generic, low-stakes topic answer for the second-ranked real
    department; for the fallback department (``topic`` ignored, by convention also the
    fallback), two generic topic answers for whichever two real departments rank highest below
    it, since the fallback itself is terminal and never has one of its own. Hard and
    adversarial rows below are written out by hand instead: nothing about a close call, a
    shared topic name, or a rescue should come from a shared helper's own judgement."""
    department_probs = _lean(helpers.DEPARTMENTS, department, 0.84)
    rank1, rank2 = _top2_real_departments(department_probs)
    if department == helpers.UNCLASSIFIED:
        topics = _generic_topics(rank1, rank2)
        path = helpers.UNCLASSIFIED
    else:
        assert rank1 == department, (department, rank1)
        topics = {
            rank1: _lean(helpers.LEAVES_BY_DEPARTMENT[rank1], topic, 0.85),
            **_generic_topics(rank2),
        }
        path = f"{department}.{topic}"
    flat = _lean(helpers.FLAT_LEAVES, path, path_high)
    return {"department": department_probs, "topics": topics, "flat": flat}


AB = helpers.ACCOUNT_BILLING
PT = helpers.PRODUCT_TECHNICAL
PP = helpers.PEOPLE_POLICY
UNC = helpers.UNCLASSIFIED

# (id, split, fields, gold leaf or None for a demo example, spec)
#
# spec = {
#     "department": {name: probability, ...} over helpers.DEPARTMENTS (sums to 1),
#     "topics": {department: {topic: probability, ...}, ...} for exactly the two real
#         departments the department probabilities above rank highest -- checked below against
#         _top2_real_departments, the same ranking helpers.rank_real_departments uses, so a row
#         can never silently disagree with the policy about which departments it explored,
#     "flat": {path: probability, ...} over helpers.FLAT_LEAVES (sums to 1),
# }
#
# "Clear" rows (one per real topic, plus two unclassified) use clear_spec and are confidently
# right throughout. The rest are written out by hand:
#
# - v11/t11/d01 ("branching rescues a department-uncertain case"): the department answer is
#   genuinely torn between two real departments, and the WRONG one edges out narrowly on raw
#   department probability alone -- so taking only the single top-ranked department (the
#   greedy baseline, branch_margin=0.0) commits to the wrong one and, within it, lands on a
#   topic that happens to share its bare name with the correct answer's own topic
#   ("general_question" in both account_billing and product_technical). Carrying both
#   departments forward and comparing path_confidence = department_probability * topic_
#   probability lets the second-ranked department's higher topic confidence win out, landing
#   on the correct full path. d01 is the same shape, shown in "Python's part".
# - v12/t12 ("branching rescues the second-ranked department"): the same shape as v11/t11 --
#   the department answer's top choice by raw probability is wrong, and the second-ranked real
#   department is correct -- except here the wrong top choice's own best topic is so unclear
#   that even the single-request GREEDY baseline ends up preferring the fallback over it
#   (candidate score = department probability * topic probability, which can never exceed the
#   department probability alone, and the fallback is always a candidate at its own raw
#   probability, so a department whose best topic is unclear loses to the fallback on its own).
#   Branching still gets there, because exploring the correct second department directly gives
#   it a real candidate score to compete with the fallback's.
# - v13 ("wrong within the right department"): the department answer is confidently and
#   correctly account_billing, but the topic answer inside it is confidently wrong -- a
#   mistake path_confidence cannot see as a department-level error, since the department really
#   was right; only the full-path gold label catches it. This keeps validation's own leaf
#   accuracy below 1.0, not only test's.
# - v14/d02 ("genuinely unclear, sent to review"): the message mixes signals from two
#   departments with no dominant one; even after branching, the best path_confidence stays low
#   enough that the frozen review gate sends it to review rather than guess.
# - t13 ("the shared-topic-name trap"): account_billing wins the department stage confidently,
#   and wrongly -- the gold department is product_technical -- and, within account_billing, the
#   topic answer confidently names "general_question", the same bare name the correct answer
#   would have carried in product_technical. A reader who compared bare topic names alone would
#   call this right; comparing the full path (this recipe's only comparison, see
#   tests/test_helpers.py::test_the_shared_topic_name_would_be_a_false_match) calls it wrong, as
#   it should be.
ROWS = [
    # ---------------------------------------------------------------------------- validation: 14
    ("v01-ab-invoice", "validation", {"doc_id": "D001",
     "text": "Can you tell me the amount on invoice #4821 and when it is due?"},
     f"{AB}.invoice_question", clear_spec(AB, "invoice_question")),
    ("v02-ab-refund", "validation", {"doc_id": "D002",
     "text": "I was charged twice for last month's plan. Please refund the duplicate charge."},
     f"{AB}.refund_request", clear_spec(AB, "refund_request")),
    ("v03-ab-general", "validation", {"doc_id": "D003",
     "text": "How does proration work if I upgrade my plan partway through the month?"},
     f"{AB}.general_question", clear_spec(AB, "general_question")),
    ("v04-pt-bug", "validation", {"doc_id": "D004",
     "text": "The export button spins forever and the file never downloads."},
     f"{PT}.bug_report", clear_spec(PT, "bug_report")),
    ("v05-pt-howto", "validation", {"doc_id": "D005",
     "text": "Is there a way to schedule a report to send every Monday morning?"},
     f"{PT}.how_to_question", clear_spec(PT, "how_to_question")),
    ("v06-pt-general", "validation", {"doc_id": "D006",
     "text": "The dashboard feels slower than it used to be lately; is that expected?"},
     f"{PT}.general_question", clear_spec(PT, "general_question")),
    ("v07-pp-leave", "validation", {"doc_id": "D007",
     "text": "How many vacation days do I have left to use before the end of the year?"},
     f"{PP}.leave_policy", clear_spec(PP, "leave_policy")),
    ("v08-pp-security", "validation", {"doc_id": "D008",
     "text": "Do we need to rotate our laptop passwords every quarter under the current policy?"},
     f"{PP}.security_policy", clear_spec(PP, "security_policy")),
    ("v09-unclassified", "validation", {"doc_id": "D009",
     "text": "Loved the new office photos on the newsletter, the plants look great!"},
     UNC, clear_spec(UNC, UNC)),
    ("v10-unclassified", "validation", {"doc_id": "D010",
     "text": "Just wanted to say thanks for the quick reply last week, really appreciated it."},
     UNC, clear_spec(UNC, UNC)),
    ("v11-branch-rescue-shared-name", "validation", {"doc_id": "D011",
     "text": "Our monthly plan summary looks off this cycle but I can't point to one line item "
     "or a specific invoice -- can someone take a general look?"},
     f"{AB}.general_question", {
         "department": {PT: 0.37, AB: 0.35, PP: 0.16, UNC: 0.12},
         "topics": {
             PT: {"general_question": 0.42, "bug_report": 0.30, "how_to_question": 0.28},
             AB: {"general_question": 0.78, "invoice_question": 0.12, "refund_request": 0.10},
         },
         "flat": {
             f"{AB}.general_question": 0.46, f"{PT}.general_question": 0.30,
             f"{AB}.invoice_question": 0.04, f"{AB}.refund_request": 0.04,
             f"{PT}.bug_report": 0.04, f"{PT}.how_to_question": 0.04,
             f"{PP}.leave_policy": 0.04, f"{PP}.security_policy": 0.04, UNC: 0.04,
         },
     }),
    ("v12-branch-rescue-second-department", "validation", {"doc_id": "D012",
     "text": "Does IT need to turn on disk encryption for a work laptop, or does that come from "
     "a separate security policy instead?"},
     f"{PP}.security_policy", {
         "department": {PT: 0.34, PP: 0.32, AB: 0.19, UNC: 0.15},
         "topics": {
             PT: {"bug_report": 0.36, "general_question": 0.34, "how_to_question": 0.30},
             PP: {"security_policy": 0.80, "leave_policy": 0.20},
         },
         "flat": {
             f"{PP}.security_policy": 0.42, f"{PT}.bug_report": 0.30,
             f"{PP}.leave_policy": 0.07, f"{AB}.general_question": 0.05,
             f"{AB}.invoice_question": 0.04, f"{AB}.refund_request": 0.04,
             f"{PT}.how_to_question": 0.03, f"{PT}.general_question": 0.03, UNC: 0.02,
         },
     }),
    ("v13-wrong-topic-right-department", "validation", {"doc_id": "D013",
     "text": "I'd like the $60 I was charged back on my card, the service never worked for me."},
     f"{AB}.refund_request", {
         "department": {AB: 0.86, PT: 0.06, PP: 0.04, UNC: 0.04},
         "topics": {
             AB: {"invoice_question": 0.79, "refund_request": 0.15, "general_question": 0.06},
             PT: {"bug_report": 0.5, "how_to_question": 0.3, "general_question": 0.2},
         },
         "flat": {
             f"{AB}.invoice_question": 0.70, f"{AB}.refund_request": 0.18,
             f"{AB}.general_question": 0.03, f"{PT}.bug_report": 0.02,
             f"{PT}.how_to_question": 0.02, f"{PT}.general_question": 0.02,
             f"{PP}.leave_policy": 0.01, f"{PP}.security_policy": 0.01, UNC: 0.01,
         },
     }),
    ("v14-genuinely-unclear", "validation", {"doc_id": "D014",
     "text": "Things have been off since last week, can someone look into it."},
     UNC, {
         "department": {UNC: 0.30, AB: 0.26, PT: 0.25, PP: 0.19},
         "topics": {
             AB: {"general_question": 0.40, "invoice_question": 0.30, "refund_request": 0.30},
             PT: {"general_question": 0.40, "bug_report": 0.30, "how_to_question": 0.30},
         },
         "flat": {
             UNC: 0.22, f"{AB}.general_question": 0.17, f"{PT}.general_question": 0.17,
             f"{AB}.invoice_question": 0.09, f"{AB}.refund_request": 0.09,
             f"{PT}.bug_report": 0.09, f"{PT}.how_to_question": 0.09,
             f"{PP}.leave_policy": 0.04, f"{PP}.security_policy": 0.04,
         },
     }),
    # ---------------------------------------------------------------------------------- test: 15
    ("t01-ab-invoice", "test", {"doc_id": "D101",
     "text": "What is the due date on invoice #5190 and how much is owed?"},
     f"{AB}.invoice_question", clear_spec(AB, "invoice_question")),
    ("t02-ab-refund", "test", {"doc_id": "D102",
     "text": "I cancelled on the 2nd but was still billed for the full month. Refund please."},
     f"{AB}.refund_request", clear_spec(AB, "refund_request")),
    ("t03-ab-general", "test", {"doc_id": "D103",
     "text": "If I add three more seats mid-cycle, how does that change this month's bill?"},
     f"{AB}.general_question", clear_spec(AB, "general_question")),
    ("t04-pt-bug", "test", {"doc_id": "D104",
     "text": "Search results come back empty even for a term I know exists in my documents."},
     f"{PT}.bug_report", clear_spec(PT, "bug_report")),
    ("t05-pt-howto", "test", {"doc_id": "D105",
     "text": "How do I share a saved view with a teammate on a different workspace?"},
     f"{PT}.how_to_question", clear_spec(PT, "how_to_question")),
    ("t06-pt-general", "test", {"doc_id": "D106",
     "text": "Any plans to add a dark mode? Not urgent, just curious about the roadmap."},
     f"{PT}.general_question", clear_spec(PT, "general_question")),
    ("t07-pp-leave", "test", {"doc_id": "D107",
     "text": "Does unused vacation time roll over into next year, or does it reset?"},
     f"{PP}.leave_policy", clear_spec(PP, "leave_policy")),
    ("t08-pp-security", "test", {"doc_id": "D108",
     "text": "Are personal phones allowed to access the work email under the security policy?"},
     f"{PP}.security_policy", clear_spec(PP, "security_policy")),
    ("t09-unclassified", "test", {"doc_id": "D109",
     "text": "Congrats on the product launch, the demo video was really well made!"},
     UNC, clear_spec(UNC, UNC)),
    ("t10-unclassified", "test", {"doc_id": "D110",
     "text": "Random thought: your support team has been lovely every time I've written in."},
     UNC, clear_spec(UNC, UNC)),
    ("t11-branch-rescue-shared-name", "test", {"doc_id": "D111",
     "text": "Something feels wrong with this cycle's charges but I can't tie it to one invoice "
     "line -- could someone take a general look at the account?"},
     f"{AB}.general_question", {
         "department": {PT: 0.36, AB: 0.34, PP: 0.17, UNC: 0.13},
         "topics": {
             PT: {"general_question": 0.40, "bug_report": 0.32, "how_to_question": 0.28},
             AB: {"general_question": 0.80, "invoice_question": 0.11, "refund_request": 0.09},
         },
         "flat": {
             f"{AB}.general_question": 0.45, f"{PT}.general_question": 0.29,
             f"{AB}.invoice_question": 0.05, f"{AB}.refund_request": 0.04,
             f"{PT}.bug_report": 0.04, f"{PT}.how_to_question": 0.04,
             f"{PP}.leave_policy": 0.03, f"{PP}.security_policy": 0.03, UNC: 0.03,
         },
     }),
    ("t12-branch-rescue-second-department", "test", {"doc_id": "D112",
     "text": "Is the laptop encryption requirement something the app enforces automatically, "
     "or is that governed separately by security policy?"},
     f"{PP}.security_policy", {
         "department": {PT: 0.33, PP: 0.31, AB: 0.20, UNC: 0.16},
         "topics": {
             PT: {"bug_report": 0.37, "general_question": 0.33, "how_to_question": 0.30},
             PP: {"security_policy": 0.78, "leave_policy": 0.22},
         },
         "flat": {
             f"{PP}.security_policy": 0.40, f"{PT}.bug_report": 0.28,
             f"{PP}.leave_policy": 0.08, f"{AB}.general_question": 0.06,
             f"{AB}.invoice_question": 0.05, f"{AB}.refund_request": 0.05,
             f"{PT}.how_to_question": 0.03, f"{PT}.general_question": 0.03, UNC: 0.02,
         },
     }),
    ("t13-shared-name-trap", "test", {"doc_id": "D113",
     "text": "Something about this month's charges on my account looks off overall; can billing "
     "take a general look rather than one specific line?"},
     f"{PT}.general_question", {
         "department": {AB: 0.84, PT: 0.06, PP: 0.05, UNC: 0.05},
         "topics": {
             AB: {"general_question": 0.81, "invoice_question": 0.11, "refund_request": 0.08},
             PT: {"general_question": 0.45, "bug_report": 0.30, "how_to_question": 0.25},
         },
         "flat": {
             f"{AB}.general_question": 0.63, f"{PT}.general_question": 0.17,
             f"{AB}.invoice_question": 0.05, f"{AB}.refund_request": 0.05,
             f"{PT}.bug_report": 0.03, f"{PT}.how_to_question": 0.03,
             f"{PP}.leave_policy": 0.02, f"{PP}.security_policy": 0.01, UNC: 0.01,
         },
     }),
    ("t14-genuinely-unclear", "test", {"doc_id": "D114",
     "text": "Not sure who handles this but something has felt off since the update, can "
     "someone check."},
     UNC, {
         "department": {AB: 0.28, PT: 0.27, UNC: 0.26, PP: 0.19},
         "topics": {
             AB: {"general_question": 0.40, "invoice_question": 0.30, "refund_request": 0.30},
             PT: {"general_question": 0.40, "bug_report": 0.30, "how_to_question": 0.30},
         },
         "flat": {
             UNC: 0.20, f"{AB}.general_question": 0.18, f"{PT}.general_question": 0.18,
             f"{AB}.invoice_question": 0.09, f"{AB}.refund_request": 0.09,
             f"{PT}.bug_report": 0.09, f"{PT}.how_to_question": 0.09,
             f"{PP}.leave_policy": 0.04, f"{PP}.security_policy": 0.04,
         },
     }),
    ("t15-wrong-topic-right-department", "test", {"doc_id": "D115",
     "text": "Please send the $45 I paid last week back to my card, the trial never actually "
     "unlocked the feature I needed."},
     f"{AB}.refund_request", {
         "department": {AB: 0.85, PT: 0.06, PP: 0.05, UNC: 0.04},
         "topics": {
             AB: {"invoice_question": 0.77, "refund_request": 0.17, "general_question": 0.06},
             PT: {"bug_report": 0.5, "how_to_question": 0.3, "general_question": 0.2},
         },
         "flat": {
             f"{AB}.invoice_question": 0.68, f"{AB}.refund_request": 0.20,
             f"{AB}.general_question": 0.03, f"{PT}.bug_report": 0.02,
             f"{PT}.how_to_question": 0.02, f"{PT}.general_question": 0.02,
             f"{PP}.leave_policy": 0.01, f"{PP}.security_policy": 0.01, UNC: 0.01,
         },
     }),
    # --------------------------------------------------------------------------------- demo: 2
    ("d01-branch-rescue", "demo", {"doc_id": "D901",
     "text": "This cycle's totals look a bit strange to me but I can't point at one invoice -- "
     "could someone take a general look?"},
     None, {
         "department": {PT: 0.37, AB: 0.35, PP: 0.16, UNC: 0.12},
         "topics": {
             PT: {"general_question": 0.42, "bug_report": 0.30, "how_to_question": 0.28},
             AB: {"general_question": 0.78, "invoice_question": 0.12, "refund_request": 0.10},
         },
         "flat": {
             f"{AB}.general_question": 0.46, f"{PT}.general_question": 0.30,
             f"{AB}.invoice_question": 0.04, f"{AB}.refund_request": 0.04,
             f"{PT}.bug_report": 0.04, f"{PT}.how_to_question": 0.04,
             f"{PP}.leave_policy": 0.04, f"{PP}.security_policy": 0.04, UNC: 0.04,
         },
     }),
    ("d02-genuinely-unclear", "demo", {"doc_id": "D902",
     "text": "Not totally sure who owns this, but things have felt off since last week."},
     None, {
         "department": {AB: 0.28, PT: 0.27, UNC: 0.25, PP: 0.20},
         "topics": {
             AB: {"general_question": 0.40, "invoice_question": 0.30, "refund_request": 0.30},
             PT: {"general_question": 0.40, "bug_report": 0.30, "how_to_question": 0.30},
         },
         "flat": {
             UNC: 0.20, f"{AB}.general_question": 0.18, f"{PT}.general_question": 0.18,
             f"{AB}.invoice_question": 0.09, f"{AB}.refund_request": 0.09,
             f"{PT}.bug_report": 0.09, f"{PT}.how_to_question": 0.09,
             f"{PP}.leave_policy": 0.04, f"{PP}.security_policy": 0.04,
         },
     }),
]  # fmt: skip


def answers_for(spec, provenance: Provenance):
    """``(department_answer, {department: topic_answer}, flat_answer)`` for one row."""
    department_answer = ChoiceAnswer.from_probabilities(spec["department"], provenance)
    topic_answers = {
        department: ChoiceAnswer.from_probabilities(probs, provenance)
        for department, probs in spec["topics"].items()
    }
    flat_answer = ChoiceAnswer.from_probabilities(spec["flat"], provenance)
    return department_answer, topic_answers, flat_answer


def requests_for(spec, provenance: Provenance):
    """``[(questions, {name: answer})]`` for one row, in the order the notebook replays them:
    the department question; a topic question for each of the two real departments the
    department probabilities rank highest, higher-ranked first; the flat baseline's question.
    """
    department_answer, topic_answers, flat_answer = answers_for(spec, provenance)
    ranked = _top2_real_departments(spec["department"])
    requests = [({"department": DEPARTMENT_QUESTION}, {"department": department_answer})]
    for department in ranked:
        requests.append(
            ({"topic": TOPIC_QUESTIONS[department]}, {"topic": topic_answers[department]})
        )
    requests.append(({"flat_topic": FLAT_QUESTION}, {"flat_topic": flat_answer}))
    return requests


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, label, spec in rows:
        state = helpers.build_state(fields)
        keys = [
            replay_key(state, questions)
            for questions, _answers in requests_for(spec, Provenance.synthetic())
        ]
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, fields, _label, spec in rows:
        state = helpers.build_state(fields)
        for questions, answers in requests_for(spec, Provenance.synthetic()):
            key = replay_key(state, questions)
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
    for ident, _split, _fields, _label, spec in ROWS:
        expected = set(_top2_real_departments(spec["department"]))
        actual = set(spec["topics"])
        if expected != actual:
            raise SystemExit(
                f"{ident}: spec['topics'] has {sorted(actual)}, but the department "
                f"probabilities rank {sorted(expected)} highest among the real departments"
            )
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
