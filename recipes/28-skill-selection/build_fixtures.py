"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 28.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic: written by hand as probabilities over the four suitability
levels, not produced by a model. Fifty tasks total (24 `validation`, 23 `test`, 3 `demo`), each
retrieved against the same fixed skill catalog ``helpers.SKILL_CATALOG`` with
``helpers.retrieve_candidates`` -- the same real retrieval step the notebook calls -- so this
script can never hand-pick a task's candidates behind the rule's back.

Most tasks per scored split are clear-cut: one retrieved skill's description plainly states it
performs the task (levels 2 or 3; the stored score is spread over a real range, 1.65 to 2.78,
not one repeated value) and the other two plainly do not. Among the rest, each hard case the
use case names, or needed to show a check is not a dead one, appears at least twice per scored
split, worded differently each time so the two splits do not mirror each other digit for
digit:

- **Cutoff-only** (`v03`/`t03`): every retrieved skill's description is only in the same
  general area as the task, never stating the specific action, so no candidate reaches the
  business cutoff, whatever the margin among them turns out to be. Read a different way, this
  is also a retrieval miss: the catalog may hold no skill that genuinely does this task, or the
  retriever's lexical overlap may simply not be surfacing one that does -- either way, the
  lesson is the same (nothing retrieved is trustworthy enough to act on), which is why the two
  gold labels these three retrieved skills carry are tied at the same, low level: none of them
  is "the best fit", only "the least unrelated".
- **Cutoff-consequential** (`v23`/`t22`, plus `v24`/`t23` supplying the lower-scoring "clearly
  correct" examples that make this possible): a *single* retrieved skill is related but not
  suitable (gold level 1, scored near the highest a genuinely modal-level-1 answer can reach),
  against two retrieved skills confidently scored as not suitable at all. The margin here is
  wide enough to clear the frozen margin threshold on its own: only the business cutoff sends
  these to review, and deleting the cutoff check and re-running the evaluation changes their
  outcome, not just their reason string (`tests/test_helpers.py` proves this on the committed
  fixtures).
- **The "two skills equally plausible" hard case** (`v04`/`t04`): two retrieved skills whose
  descriptions are both genuinely plausible for the task, carrying the same highest gold
  level, scored close together on purpose. Deleting the margin check (not just loosening the
  threshold) flips this one to an automatic, unreviewed guess -- also proved on the committed
  fixtures.
- **Deliberately wrong, margin catches it** (`v05`): the skill that actually fits is scored
  low and the skill that only sounds related is scored confidently high, but not high enough
  to clear the margin threshold -- it is still held for review, for the right reason, on
  `validation`.
- **Deliberately wrong, nothing catches it** (`v22`/`t05`): the same shape as `v05`, but
  scored confidently enough to clear every check anyway. `v22` is on `validation`, so the
  frozen margin threshold is chosen knowing at least one wrong example will pass it; `t05` is
  the matching case on `test`, giving the evaluation a real, non-zero risk to report.

Three more tasks are `demo`: one of each shape (a confident correct pick, the ambiguous pair,
and a cutoff failure), shown up close before any aggregate and never scored. Every row names
the level its own stored answer is written to land on (``intended_level``), separately from
the task's gold level (``gold_level``), so the two can disagree on purpose where a row is
deliberately wrong, and ``tests/test_build_fixtures.py`` checks every committed stored
answer's modal level against its row's own ``intended_level``.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from TASK_SPECS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, Provenance, ScoreAnswer, load_helpers, replay_key
from jev_cookbook.evaluation import score_level

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
LEVELS = list(helpers.SUITABILITY_LEVELS)

# Probability vectors over the four levels (not_suitable, related, suitable, ideal), each
# summing to 1. Reused across tasks on purpose, the same way recipes/17-passage-reranking reuses
# one vector per rubric level for every passage at that level: the *level* a row is written to
# land on is what the row names (below), not the particular vector. Every vector here is given
# directly as a full distribution, with the level it lands on named separately in each row (see
# ``intended_level``), so nothing about a stored answer's label is defaulted or inferred from a
# shorthand.
IDEAL_CONFIDENT = (0.02, 0.03, 0.10, 0.85)  # modal level 3, score 2.78
# Five more modal-level-3 vectors, each less peaked than the last: a clear-cut task's stored
# score is not always the same number. Spreading the "confidently correct" picks over a real
# range (2.35 to 2.78), rather than one repeated value, is what lets the margin threshold
# chosen below reflect a real distribution instead of a single point every correct answer and
# no wrong one happens to sit on.
IDEAL_2 = (0.02, 0.04, 0.14, 0.80)  # modal level 3, score 2.72
IDEAL_3 = (0.03, 0.05, 0.22, 0.70)  # modal level 3, score 2.59
IDEAL_4 = (0.03, 0.07, 0.25, 0.65)  # modal level 3, score 2.52
IDEAL_5 = (0.04, 0.08, 0.28, 0.60)  # modal level 3, score 2.44
IDEAL_6 = (0.05, 0.10, 0.30, 0.55)  # modal level 3, score 2.35
IDEAL_7 = (0.05, 0.12, 0.33, 0.50)  # modal level 3, score 2.28
IDEAL_8 = (0.06, 0.14, 0.35, 0.45)  # modal level 3, score 2.19
SUITABLE_CONFIDENT = (0.03, 0.09, 0.73, 0.15)  # modal level 2, score 2.00
SUITABLE_MED = (0.15, 0.25, 0.40, 0.20)  # modal level 2, score 1.65
RELATED_A = (0.09, 0.71, 0.14, 0.06)  # modal level 1
RELATED_B = (0.14, 0.58, 0.20, 0.08)  # modal level 1, a different vector for the same level
RELATED_C = (0.12, 0.60, 0.21, 0.07)  # modal level 1, a third vector for the same level
# Near the ceiling a modal-level-1 answer can reach (level 1 and level 2 tied would score 1.5;
# a tie goes to the lower level, so this is as high as a genuinely modal-1 score gets).
RELATED_HIGH = (0.02, 0.49, 0.47, 0.02)  # modal level 1, score 1.49
NOT_SUITABLE_CONFIDENT = (0.72, 0.16, 0.08, 0.04)  # modal level 0
# A skill whose description shares essentially nothing with the task: near-certain level 0.
NOT_SUITABLE_AT_ALL = (0.95, 0.03, 0.01, 0.01)  # modal level 0, score 0.08
IDEAL_LOW_CONFIDENCE = (0.08, 0.15, 0.30, 0.47)  # modal level 3, spread enough to read as unsure
# Close-scoring pairs for the "two skills equally plausible" tasks: both land on modal level 3,
# with a small enough gap between their expected scores that the margin check should not let
# either one through automatically. Four distinct vectors (not one pair reused twice) so the
# two ambiguous tasks do not mirror each other digit for digit.
TIE_HIGH_1 = (0.03, 0.10, 0.35, 0.52)
TIE_LOW_1 = (0.03, 0.12, 0.38, 0.47)
TIE_HIGH_2 = (0.02, 0.08, 0.33, 0.57)
TIE_LOW_2 = (0.02, 0.11, 0.40, 0.47)
TIE_HIGH_3 = (0.04, 0.09, 0.32, 0.55)
TIE_LOW_3 = (0.03, 0.13, 0.39, 0.45)

# One entry per task: (task_id, split, task text, {skill_id: (gold_level_or_None, intended_level,
# probabilities)}). `gold_level` is this skill's true suitability level for this task, written
# by the fixture author from the rubric; it is `None` for a `demo` task, which carries no label.
# `intended_level` is the modal level the row's own `probabilities` are written to land on --
# equal to `gold_level` everywhere the stored answer is right, and deliberately different on the
# two rows that are not (both skills of v05, and both skills of t05).
TASK_SPECS = [
    (
        "v01",
        "validation",
        "Book a flight and hotel for next week's trip to the Denver sales conference.",
        {
            "travel_booking": (3, 3, IDEAL_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v02",
        "validation",
        "Summarize the changes in this pull request before our team reviews it.",
        {
            "code_review_summary": (3, 3, IDEAL_6),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v03",
        "validation",
        "Set up a recurring reminder to log my travel expenses every Friday afternoon.",
        {
            # No retrieved skill's description states the specific action this task asks for
            # (a recurring reminder); all three are only in the same general area. The business
            # cutoff sends this to review on its own, whatever the margin among them turns out
            # to be.
            "travel_booking": (1, 1, RELATED_A),
            "calendar_scheduling": (1, 1, RELATED_B),
            "expense_report": (1, 1, RELATED_C),
        },
    ),
    (
        "v04",
        "validation",
        "Arrange the calendar slot and travel plans for next week's trip to the Chicago "
        "conference.",
        {
            # The hard case: both calendar_scheduling and travel_booking plausibly fit ("the
            # calendar slot" is scheduling; "travel plans" is booking), so both carry the
            # highest gold level and the stored scores are written close together.
            "calendar_scheduling": (3, 3, TIE_HIGH_1),
            "travel_booking": (3, 3, TIE_LOW_1),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v05",
        "validation",
        "Pull up the internal doc on how travel booking approvals work for the finance team.",
        {
            # Deliberately wrong: the task only asks to find a document, which is exactly
            # doc_search's job (gold level 3), but the stored answer scores travel_booking
            # instead (gold level 1: the same general area, mentioned by name, but the task
            # never asks to book anything) -- and under-scores doc_search to match. The wrong
            # pick's own distribution is also written spread enough to read as genuinely unsure
            # (confidence 0.16), and this is also one of the examples the margin threshold is
            # chosen from -- two independent facts, not one causing the other.
            # pool_for_margin_selection's only filter is the top skill's modal level clearing
            # BUSINESS_CUTOFF; it reads no confidence at all, this rule has no confidence gate,
            # and nothing in select_skill reads an answer's own confidence.
            "travel_booking": (1, 3, IDEAL_LOW_CONFIDENCE),
            "doc_search": (3, 1, RELATED_A),
            "code_review_summary": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v06",
        "validation",
        "Schedule a status meeting with the whole engineering team for Monday morning.",
        {
            "calendar_scheduling": (3, 3, IDEAL_7),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v07",
        "validation",
        "Find a free slot on my calendar for a sync with legal next week.",
        {
            "calendar_scheduling": (3, 3, IDEAL_8),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v08",
        "validation",
        "Check everyone's availability and book a 1:1 with my manager this afternoon.",
        {
            "calendar_scheduling": (3, 3, IDEAL_2),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v09",
        "validation",
        "Book a hotel room near the venue for next month's industry conference.",
        {
            "travel_booking": (3, 3, IDEAL_2),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v10",
        "validation",
        "Reserve a rental car for the site visit to the Austin warehouse next week.",
        {
            "travel_booking": (3, 3, IDEAL_2),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v11",
        "validation",
        "Arrange the flight itinerary for my trip to the London office next quarter.",
        {
            "travel_booking": (3, 3, IDEAL_3),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v12",
        "validation",
        "Submit the receipt for last night's client dinner for reimbursement.",
        {
            "expense_report": (3, 3, IDEAL_3),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v13",
        "validation",
        "Check the status of the expense claim I submitted for my taxi rides last week.",
        {
            "expense_report": (3, 3, IDEAL_3),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v14",
        "validation",
        "File a reimbursement claim for the parking fees from the offsite.",
        {
            "expense_report": (3, 3, IDEAL_4),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v15",
        "validation",
        "Find the internal article that explains our vacation accrual policy.",
        {
            "doc_search": (3, 3, IDEAL_4),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v16",
        "validation",
        "Search the knowledge base for the document on password reset procedures.",
        {
            "doc_search": (3, 3, IDEAL_4),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v17",
        "validation",
        "Look up the internal documentation that answers how VPN access is granted.",
        {
            "doc_search": (3, 3, IDEAL_5),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v18",
        "validation",
        "Summarize the diff in this pull request so the reviewer knows what changed.",
        {
            "code_review_summary": (3, 3, IDEAL_5),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v19",
        "validation",
        "List what this code change touches and which tests it affects for the reviewer.",
        {
            "code_review_summary": (3, 3, IDEAL_5),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v20",
        "validation",
        "Summarize the pull request's changes before the team looks at the review.",
        {
            "code_review_summary": (3, 3, IDEAL_6),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v21",
        "validation",
        "Summarize what tests this pull request's diff changes for the code review.",
        {
            "code_review_summary": (3, 3, IDEAL_6),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v22",
        "validation",
        "Find the internal article explaining how to categorize client parking fees for "
        "reimbursement.",
        {
            # A second deliberately wrong pair, this one on validation: the task asks to find
            # an article (doc_search, gold level 3), but the stored answer scores
            # expense_report confidently instead (gold level 1), written exactly as confidently
            # as t05's wrong pick (not spread out), so it clears the margin threshold too.
            # validation's own "selected" accuracy is therefore not 1.0 by construction: at
            # least one task validation itself would auto-answer is wrong.
            "expense_report": (1, 3, IDEAL_CONFIDENT),
            "doc_search": (3, 0, NOT_SUITABLE_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "v23",
        "validation",
        "I am curious whether our calendar tool shows how busy my teammates are without "
        "asking them directly.",
        {
            # The business cutoff's own case to be consequential on, independent of the
            # margin: calendar_scheduling is the only retrieved skill anywhere in the same
            # area (gold level 1, related -- it checks availability, but for booking a slot,
            # not for showing a passive busy/free view), and the stored answer scores it near
            # the highest a genuinely modal-level-1 answer can reach. The two fillers are
            # written as confidently unrelated as a stored answer gets, so the margin between
            # this top skill and its closest retrieved rival is wide: 0.4700, well above the
            # frozen margin threshold. Only the business cutoff sends this to review.
            "calendar_scheduling": (1, 1, RELATED_HIGH),
            "travel_booking": (0, 0, NOT_SUITABLE_AT_ALL),
            "expense_report": (0, 0, NOT_SUITABLE_AT_ALL),
        },
    ),
    (
        "v24",
        "validation",
        "I need something booked for my upcoming business trip.",
        {
            # A genuinely level-2 (suitable) easy task, scored less peaked than the
            # level-3 ones above: travel_booking states the general booking action the task
            # asks for, but the task itself never names which of flight, hotel, or car it
            # means, so the description's own extra named detail is not something this task
            # calls on. This is what pulls the margin threshold chosen below down from the
            # level-3 cluster, rather than every "clearly correct" example sharing one score.
            "travel_booking": (2, 2, SUITABLE_MED),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t01",
        "test",
        "Set up a 30 minute meeting with the design team for Thursday afternoon.",
        {
            "calendar_scheduling": (3, 3, IDEAL_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t02",
        "test",
        "Find the article that explains how two-factor authentication works for our account.",
        {
            "doc_search": (3, 3, IDEAL_6),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t03",
        "test",
        "I want to understand how expense categories map to our department budgets this quarter.",
        {
            "expense_report": (1, 1, RELATED_A),
            "calendar_scheduling": (1, 1, RELATED_B),
            "travel_booking": (1, 1, RELATED_C),
        },
    ),
    (
        "t04",
        "test",
        "Put this on the calendar and sort out travel arrangements for next month's trip to "
        "the Austin summit.",
        {
            "travel_booking": (3, 3, TIE_HIGH_2),
            "calendar_scheduling": (3, 3, TIE_LOW_2),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t05",
        "test",
        "Find the internal article explaining how to categorize client dinner expenses for "
        "reimbursement.",
        {
            # Deliberately wrong, the case the frozen margin threshold does not catch: the task
            # asks to find an article (doc_search, gold level 3), but the stored answer scores
            # expense_report confidently instead (gold level 1) and scores doc_search as near-
            # certainly not suitable at all -- the same confidently-wrong-per-question shape
            # tests/test_helpers.py's stored-answers guard requires on `test`.
            "expense_report": (1, 3, IDEAL_CONFIDENT),
            "doc_search": (3, 0, NOT_SUITABLE_AT_ALL),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t06",
        "test",
        "Set up a kickoff meeting with the new vendor for Wednesday afternoon.",
        {
            "calendar_scheduling": (3, 3, IDEAL_7),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t07",
        "test",
        "Find an open slot on my calendar for a 1:1 with the new hire tomorrow.",
        {
            "calendar_scheduling": (3, 3, IDEAL_8),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t08",
        "test",
        "Check attendee availability and book a planning session for the roadmap review.",
        {
            "calendar_scheduling": (3, 3, IDEAL_2),
            "code_review_summary": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t09",
        "test",
        "Book a flight and rental car for the trip to the Seattle regional office.",
        {
            "travel_booking": (3, 3, IDEAL_2),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t10",
        "test",
        "Reserve a hotel for the team's offsite retreat next month.",
        {
            "travel_booking": (3, 3, IDEAL_2),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t11",
        "test",
        "Arrange travel for the sales trip to the Chicago trade show in May.",
        {
            "travel_booking": (3, 3, IDEAL_3),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t12",
        "test",
        "Submit my meal and taxi receipts from last week for reimbursement.",
        {
            "expense_report": (3, 3, IDEAL_3),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t13",
        "test",
        "Check the status of the reimbursement claim I filed for my mileage.",
        {
            "expense_report": (3, 3, IDEAL_3),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t14",
        "test",
        "File an expense report for the client lunch I paid for yesterday.",
        {
            "expense_report": (3, 3, IDEAL_4),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t15",
        "test",
        "Find the internal article explaining our parental leave policy.",
        {
            "doc_search": (3, 3, IDEAL_4),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t16",
        "test",
        "Search the knowledge base for the document on badge access requests.",
        {
            "doc_search": (3, 3, IDEAL_4),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t17",
        "test",
        "Look up the internal documentation that answers how to request a new laptop.",
        {
            "doc_search": (3, 3, IDEAL_5),
            "code_review_summary": (0, 0, NOT_SUITABLE_CONFIDENT),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t18",
        "test",
        "Summarize the changes in this diff so the reviewer understands the pull request.",
        {
            "code_review_summary": (3, 3, IDEAL_5),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t19",
        "test",
        "List which tests this pull request's code change touches for the reviewer.",
        {
            "code_review_summary": (3, 3, IDEAL_5),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t20",
        "test",
        "Summarize this pull request's diff before the review meeting.",
        {
            "code_review_summary": (3, 3, IDEAL_6),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t21",
        "test",
        "Summarize what this code change modifies and which tests it touches.",
        {
            "code_review_summary": (3, 3, IDEAL_6),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "travel_booking": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "t22",
        "test",
        "Does our calendar system let me see how busy my teammates are without messaging them.",
        {
            # test's own business-cutoff-is-consequential case, worded differently from
            # v23 so the two splits do not mirror each other: same shape (a related-only top
            # skill scored near the modal-level-1 ceiling, against two confidently unrelated
            # fillers, margin far above the frozen threshold), different wording and skills
            # retrieved in a different order.
            "calendar_scheduling": (1, 1, RELATED_HIGH),
            "travel_booking": (0, 0, NOT_SUITABLE_AT_ALL),
            "expense_report": (0, 0, NOT_SUITABLE_AT_ALL),
        },
    ),
    (
        "t23",
        "test",
        "Something needs to be booked for my upcoming work trip next week.",
        {
            # test's own level-2 (suitable) easy task, worded differently from v24.
            "travel_booking": (2, 2, SUITABLE_MED),
            "calendar_scheduling": (0, 0, NOT_SUITABLE_CONFIDENT),
            "expense_report": (0, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "d01",
        "demo",
        "Submit my taxi and hotel receipts from last week's client visit for reimbursement.",
        {
            "expense_report": (None, 3, IDEAL_CONFIDENT),
            "travel_booking": (None, 0, NOT_SUITABLE_CONFIDENT),
            "calendar_scheduling": (None, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "d02",
        "demo",
        "Handle the calendar schedule and travel logistics for next week's trip to the "
        "Seattle offsite.",
        {
            "travel_booking": (None, 3, TIE_HIGH_3),
            "calendar_scheduling": (None, 3, TIE_LOW_3),
            "expense_report": (None, 0, NOT_SUITABLE_CONFIDENT),
        },
    ),
    (
        "d03",
        "demo",
        "Set up a recurring reminder to track my conference travel expenses.",
        {
            "travel_booking": (None, 1, RELATED_A),
            "calendar_scheduling": (None, 1, RELATED_B),
            "expense_report": (None, 1, RELATED_C),
        },
    ),
]


def _fields(task_id: str, task: str, skill_id: str) -> dict:
    return {
        "task_id": task_id,
        "task": task,
        "skill_id": skill_id,
        "skill": helpers.SKILL_CATALOG[skill_id],
    }


def _rows(tasks):
    """Flatten ``TASK_SPECS`` into one row per (task, retrieved skill) pair, in retrieval order,
    calling the same ``retrieve_candidates`` the notebook calls -- so this script can never
    hand-pick a task's candidates behind the rule's back. Each row is
    ``(id, split, fields, gold_level, intended_level, probabilities)``.
    """
    rows = []
    for task_id, split, task, specs in tasks:
        candidates = helpers.retrieve_candidates(task)
        if set(candidates) != set(specs):
            raise SystemExit(
                f"{task_id}: retrieve_candidates returned {candidates}, "
                f"but TASK_SPECS names {sorted(specs)}"
            )
        for skill_id in candidates:
            gold_level, intended_level, probabilities = specs[skill_id]
            ident = f"{task_id}-{skill_id}"
            rows.append(
                (ident, split, _fields(task_id, task, skill_id), gold_level, intended_level,
                 probabilities)
            )  # fmt: skip
    return rows


# The flat row list every guard test and tool (tests/test_recipe_guard.py,
# tools/new_recipe.py's own scaffolded test_build_fixtures.py) expects a recipe's
# build_fixtures.py to expose as ``ROWS``: one row per (task, retrieved skill) pair, computed
# once here by calling the real ``retrieve_candidates`` against ``TASK_SPECS`` -- so ``ROWS``
# itself can never silently hand-pick a task's candidates behind the rule's back, even though
# it is a flat list by the time anything downstream (``build_responses``,
# ``build_inputs_and_labels``, the guard's own generated tests) reads it.
ROWS = _rows(TASK_SPECS)


def answers_for(probabilities: tuple[float, ...], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Score answer over the four levels."""
    return {"relevance": ScoreAnswer.from_probabilities(list(probabilities), LEVELS, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, gold_level, _intended_level, _probabilities in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if gold_level is not None:
            labels.append({"id": ident, "label": gold_level})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, _split, fields, _gold_level, _intended_level, probabilities in rows:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for(probabilities, Provenance.synthetic())
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def check_intended_levels(rows) -> None:
    """Every row's stored answer must land on the level the row itself names
    (``intended_level``), never a level silently drifting from what the row's own
    ``probabilities`` actually produce. Raises if any row disagrees with its own
    ``probabilities``."""
    for ident, _split, _fields, _gold_level, intended_level, probabilities in rows:
        answers = answers_for(probabilities, Provenance.synthetic())
        level = score_level(answers["relevance"])
        if level != intended_level:
            raise SystemExit(
                f"{ident}: probabilities land on level {level}, but TASK_SPECS names "
                f"intended_level {intended_level}"
            )


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
    used only to warn when a TASK_SPECS edit has desynchronised the two."""
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
        raise SystemExit("add tasks to TASK_SPECS in build_fixtures.py")
    check_intended_levels(ROWS)
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, items in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\n" for row in items)
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    responses_file = folder / "responses.json"
    if _is_recorded(responses_file) and not args.force:
        message = (
            f"refusing to overwrite {responses_file}: it holds a recorded response "
            "(pass --force to overwrite it anyway)"
        )
        if _unresolved_keys(inputs, responses_file):
            message += (
                "\ninputs.jsonl and labels.jsonl above were rewritten from TASK_SPECS; "
                "responses.json was not, and at least one of the keys the rewritten inputs "
                "ask for is missing from it. The three files are desynchronised until you "
                "--force a rewrite or record the missing answers."
            )
        raise SystemExit(message)
    responses = build_responses(ROWS)
    # The same serialization jev_cookbook.dump_responses writes: only the top-level keys are
    # sorted; each response keeps the field order DecisionResult.to_dict() emits. Matching the
    # recorder exactly, rather than json.dumps(..., sort_keys=True) (which also sorts every
    # nested dict alphabetically), keeps a recording's diff to the values that actually changed.
    text = json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n"
    responses_file.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
