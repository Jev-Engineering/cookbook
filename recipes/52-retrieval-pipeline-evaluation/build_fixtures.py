"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 52.

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
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import (
    ChoiceAnswer,
    DecisionResult,
    Provenance,
    ScoreAnswer,
    dump_responses,
    load_helpers,
    replay_key,
)

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
SUPPORTED, CONTRADICTED, NOT_ENOUGH = helpers.SUPPORTED, helpers.CONTRADICTED, helpers.NOT_ENOUGH

# Each ROWS entry is (id, split, fields, gold label or None for a demo example, how the stored
# answers are written). The stored answers are written per passage role and per evidence state,
# not per request, and each request's key comes from the state the pipeline really builds.

# How each kind of passage reads to a synthetic stage-one answer: the probability that the filter
# keeps it, and the relevance level the reranker's answer peaks at. A row may override either for
# one passage (``{"keep": ..., "level": ...}``). These are the numbers a fixture author writes, so
# the offline ablation checks the pipeline's plumbing; it does not measure how Jev reads passages.
ROLES = {
    "K": (0.92, 3),  # decisive: states enough on its own to show the claim true or false
    "P": (0.88, 2),  # one of two facts the claim needs together
    "W": (0.30, 1),  # the second fact, which reads as tangential on its own
    "D": (0.22, 1),  # a decoy: shares words with the claim, states nothing it depends on
    "F": (0.72, 2),  # a decoy that reads as if it bears on the claim
    "O": (0.06, 0),  # about something else
}
LEVEL_PROBABILITIES = {  # a Score answer's distribution over the four levels, by its peak
    0: [0.70, 0.20, 0.07, 0.03],
    1: [0.15, 0.70, 0.12, 0.03],
    2: [0.03, 0.12, 0.70, 0.15],
    3: [0.03, 0.07, 0.20, 0.70],
}
# What a synthetic verifier says, (supported, contradicted, not_enough_evidence), by how much of
# the gold evidence reached it: "complete" (all of it, or none was needed), "partial" (some) or
# "absent" (none of it). A row may replace any of them, and "fooled" applies when a passage that
# only reads as relevant (role F) is in the evidence and the row gives that state.
VERIFY_DEFAULTS = {
    SUPPORTED: {
        "complete": (0.82, 0.06, 0.12),
        "partial": (0.32, 0.10, 0.58),
        "absent": (0.14, 0.10, 0.76),
    },
    CONTRADICTED: {
        "complete": (0.06, 0.80, 0.14),
        "partial": (0.10, 0.30, 0.60),
        "absent": (0.10, 0.12, 0.78),
    },
    NOT_ENOUGH: {
        "complete": (0.10, 0.07, 0.83),
        "partial": (0.10, 0.07, 0.83),
        "absent": (0.10, 0.07, 0.83),
    },
}


def row(ident, split, claim, passages, verdict, evidence, verify=None):
    """One example. ``passages`` is ``[(role, text)]`` or ``[(role, text, overrides)]`` in
    retrieval order; ``evidence`` lists the 1-based positions of the gold evidence passages."""
    listed = [
        {"passage_id": f"{ident}-p{i}", "text": p[1]} for i, p in enumerate(passages, start=1)
    ]
    roles = {
        f"{ident}-p{i}": (p[0], p[2] if len(p) > 2 else {}) for i, p in enumerate(passages, start=1)
    }
    gold = None
    if split != "demo":
        gold = {"verdict": verdict, "evidence": [f"{ident}-p{i}" for i in evidence]}
    spec = {"gold": (verdict, [f"{ident}-p{i}" for i in evidence]), "roles": roles}
    spec["verify"] = verify or {}
    return (ident, split, {"claim": claim, "passages": listed}, gold, spec)


ROWS = [
    row(
        "d01",
        "demo",
        "Each adult in a group pays the full 7 dollars for a day pass at the Marlowe Park pool.",
        [
            (
                "D",
                "Day passes for the Marlowe Park pool can be bought at the front desk or online until 4 pm.",
            ),
            ("P", "The Marlowe Park pool charges 7 dollars per person for an adult day pass."),
            (
                "D",
                "Marlowe Park pool offers a family day pass for 20 dollars that covers up to four people.",
            ),
            (
                "W",
                "No group discount applies to adult day passes at the Marlowe Park pool.",
                {"level": 2},
            ),
        ],
        SUPPORTED,
        [2, 4],
    ),
    row(
        "d02",
        "demo",
        "The Marlowe Park farmers market runs on Saturdays.",
        [
            ("D", "The Marlowe Park quilt fair is held every Saturday in June near the bandstand."),
            ("D", "Farmers market vendors must register by the first day of each month."),
            ("K", "The Marlowe Park farmers market takes place every Saturday from 8 am to noon."),
            ("O", "Bicycle racks stand beside the north gate of Marlowe Park."),
        ],
        SUPPORTED,
        [3],
    ),
    row(
        "d03",
        "demo",
        "The Marlowe Park pool has a diving board.",
        [
            ("F", "The Marlowe Park pool has six lap lanes and a shallow wading area."),
            ("D", "A diving club meets at the Elmgate Aquatic Centre on Monday evenings."),
            ("D", "Lifeguards at the Marlowe Park pool renew their certificates every spring."),
            ("O", "Lockers at the Marlowe Park pool take a one dollar coin."),
        ],
        NOT_ENOUGH,
        [],
        verify={"complete": (0.38, 0.17, 0.45)},
    ),
    row(
        "v01",
        "validation",
        "The Kestrel Line express to Dunmere leaves at 07:40 on weekdays.",
        [
            (
                "D",
                "The Kestrel Line local service to Dunmere leaves at 07:55 and stops at every station.",
            ),
            ("D", "Kestrel Line tickets to Dunmere can be bought on the platform or on the train."),
            (
                "K",
                "On weekdays the Kestrel Line express to Dunmere departs at 07:40 from platform two.",
            ),
            ("O", "The Dunmere market square has a fountain and a bakery."),
        ],
        SUPPORTED,
        [3],
    ),
    row(
        "v02",
        "validation",
        "Bicycles travel on the Kestrel Line outside the weekday rush hours at no extra charge.",
        [
            ("D", "Kestrel Line carriages have space for luggage, prams and wheelchairs."),
            (
                "P",
                "Bicycles are allowed on every Kestrel Line train outside the weekday rush hours.",
            ),
            (
                "D",
                "Kestrel Line sells a weekly bicycle locker pass for 6 dollars at Dunmere station.",
            ),
            ("W", "Carried equipment of any kind travels free on a standard Kestrel Line ticket."),
        ],
        SUPPORTED,
        [2, 4],
    ),
    row(
        "v03",
        "validation",
        "The Elmgate library opens at 8 am on Sundays.",
        [
            (
                "D",
                "The Elmgate library offers free reading rooms and a children's corner every weekend.",
            ),
            ("D", "Elmgate library staff answer phone enquiries from 8 am on weekdays."),
            ("K", "The Elmgate library is closed on Sundays and opens at 10 am on Saturdays."),
            ("O", "Elmgate's recycling depot accepts glass on the first Tuesday of the month."),
        ],
        CONTRADICTED,
        [3],
    ),
    row(
        "v04",
        "validation",
        "The Elmgate library lends board games.",
        [
            ("D", "The Elmgate library lends books, audiobooks and magazines for three weeks."),
            ("D", "Board games are sold at the Elmgate toy shop on Alder Street."),
            ("D", "The Elmgate library hosts a chess club on Thursday evenings."),
            ("O", "Alder Street is closed to traffic during the spring parade."),
        ],
        NOT_ENOUGH,
        [],
    ),
    row(
        "v05",
        "validation",
        "Harbour Ferry crossings to Skerry Island take 25 minutes.",
        [
            ("D", "Harbour Ferry sells a family ticket for crossings to Skerry Island."),
            ("K", "A Harbour Ferry crossing to Skerry Island takes 25 minutes in normal weather."),
            ("K", "Harbour Ferry: a crossing to Skerry Island takes 25 minutes in normal weather."),
            ("D", "Crossings to Skerry Island are cancelled when winds exceed gale force."),
            ("O", "Skerry Island has a lighthouse open to visitors in summer."),
        ],
        SUPPORTED,
        [2],
    ),
    row(
        "v06",
        "validation",
        "Parking at Quillon station is free after 6 pm.",
        [
            ("K", "Parking at Quillon station is free after 6 pm and all day on Sundays."),
            ("D", "Quillon station has 120 parking spaces and four spaces for disabled drivers."),
            ("D", "Parking permits for Quillon station cost 30 dollars per month."),
            ("O", "The Quillon station cafe opens at 6 am."),
        ],
        SUPPORTED,
        [1],
        verify={"complete": (0.70, 0.10, 0.20)},
    ),
    row(
        "v07",
        "validation",
        "The Quillon skate park is open to scooters.",
        [
            ("F", "The Quillon skate park is open to skateboards and in-line skates every day."),
            ("D", "The Quillon skate park was resurfaced last autumn."),
            ("K", "Scooters are not allowed at the Quillon skate park at any time."),
            ("O", "The Quillon town hall holds council meetings on the second Monday."),
        ],
        CONTRADICTED,
        [3],
    ),
    row(
        "v08",
        "validation",
        "The Quillon skate park has floodlights.",
        [
            ("F", "The Quillon skate park stays open until 9 pm in summer."),
            ("D", "The Quillon skate park has a concrete bowl and two rails."),
            ("D", "The Quillon car park beside the skate park has bright lamps."),
            ("O", "Quillon's swimming lake is unsupervised in winter."),
        ],
        NOT_ENOUGH,
        [],
        verify={"fooled": (0.50, 0.08, 0.42)},
    ),
    row(
        "t01",
        "test",
        "The Brindle Cove ferry carries cars on the 9 am sailing.",
        [
            ("D", "The Brindle Cove ferry offers a quiet cabin and a snack bar on every sailing."),
            ("D", "Brindle Cove ferry tickets for cars must be booked 24 hours ahead."),
            (
                "K",
                "Cars are carried on the 9 am Brindle Cove ferry sailing, which has room for 18 vehicles.",
            ),
            ("O", "Brindle Cove's lifeboat station holds an open day each August."),
        ],
        SUPPORTED,
        [3],
    ),
    row(
        "t02",
        "test",
        "A day ticket at Brindle Cove harbour costs 6 dollars and stays valid for 12 hours.",
        [
            ("D", "Brindle Cove harbour car park has 80 spaces and is lit at night."),
            ("P", "A day ticket for the Brindle Cove harbour car park costs 6 dollars."),
            ("D", "Brindle Cove harbour car park is closed to caravans between May and September."),
            (
                "W",
                "Day tickets bought at Brindle Cove harbour stay valid for 12 hours from purchase.",
                {"level": 2},
            ),
        ],
        SUPPORTED,
        [2, 4],
    ),
    row(
        "t03",
        "test",
        "The Brindle Cove ferry runs every day of the year.",
        [
            ("D", "The Brindle Cove ferry timetable is printed at the harbour office."),
            ("D", "The Brindle Cove ferry has run since 1962 and is owned by the harbour trust."),
            ("K", "The Brindle Cove ferry does not run on Christmas Day or New Year's Day."),
            ("D", "Ferry tickets are sold at the harbour kiosk on the day of travel."),
        ],
        CONTRADICTED,
        [3],
    ),
    row(
        "t04",
        "test",
        "The Brindle Cove ferry accepts pets in the cabin.",
        [
            ("D", "The Brindle Cove ferry cabin has forty seats and a snack bar."),
            ("D", "Pets must be kept on a lead on Brindle Cove harbour quay."),
            ("D", "The Brindle Cove ferry crew carry a first aid kit and life jackets."),
            ("O", "The Brindle Cove tourist office sells maps and postcards."),
        ],
        NOT_ENOUGH,
        [],
    ),
    row(
        "t05",
        "test",
        "A season ticket for the Elmgate baths costs 45 dollars with no couple discount.",
        [
            ("D", "Elmgate baths season tickets can be renewed at the front desk each January."),
            ("P", "A season ticket for the Elmgate baths costs 45 dollars per person."),
            ("P", "Elmgate baths: a season ticket costs 45 dollars per person."),
            ("D", "Elmgate baths hold a family swim on Sunday mornings."),
            (
                "W",
                "Elmgate baths season tickets are sold singly and carry no couple discount.",
                {"keep": 0.80},
            ),
        ],
        SUPPORTED,
        [2, 5],
    ),
    row(
        "t06",
        "test",
        "The Alder Street clinic opens at 9 am on Mondays.",
        [
            ("K", "The Alder Street clinic opens at 9 am on Mondays and closes at 5 pm."),
            ("D", "The Alder Street clinic has a ramp and a lift at the side entrance."),
            ("D", "Alder Street clinic appointments can be booked by phone or online."),
            ("O", "The Alder Street bakery sells bread from 7 am."),
        ],
        SUPPORTED,
        [1],
    ),
    row(
        "t07",
        "test",
        "The Alder Street clinic offers vaccinations without an appointment.",
        [
            ("D", "The Alder Street clinic offers vaccinations for adults and children."),
            ("D", "Vaccination records can be requested from the Alder Street clinic reception."),
            ("D", "The Alder Street clinic is a short walk from the Quillon bus stop."),
            ("K", "Vaccinations at the Alder Street clinic are by appointment only."),
        ],
        CONTRADICTED,
        [4],
    ),
    row(
        "t08",
        "test",
        "The Alder Street clinic has a dentist.",
        [
            ("F", "The Alder Street clinic employs two nurses and a visiting physiotherapist."),
            ("D", "Dentists in Elmgate can be booked through the county health line."),
            ("D", "The Alder Street clinic has a waiting room with a children's corner."),
            ("O", "Alder Street is lined with plane trees."),
        ],
        NOT_ENOUGH,
        [],
        verify={"fooled": (0.84, 0.04, 0.12)},
    ),
    row(
        "t09",
        "test",
        "The Kestrel Line night bus to Dunmere runs hourly.",
        [
            ("D", "The Kestrel Line night bus replaces trains after midnight."),
            ("D", "Kestrel Line night bus stops are marked with a blue sign."),
            (
                "K",
                "The Kestrel Line night bus to Dunmere leaves every hour on the hour from 00:00 to 05:00.",
            ),
            ("O", "Dunmere station has a lost property office."),
        ],
        SUPPORTED,
        [3],
        verify={"complete": (0.46, 0.20, 0.34)},
    ),
    row(
        "t10",
        "test",
        "The 08:10 Kestrel Line train from Dunmere takes 45 minutes to reach Quillon.",
        [
            ("D", "Kestrel Line trains from Dunmere run every ten minutes at peak times."),
            ("D", "Quillon station is a five minute walk from the Alder Street clinic."),
            ("P", "The 08:10 Kestrel Line train from Dunmere runs non-stop to Quillon."),
            (
                "P",
                "The non-stop Kestrel Line service between Dunmere and Quillon takes 45 minutes.",
            ),
        ],
        SUPPORTED,
        [3, 4],
    ),
]


def stage_one_answers(spec, passage_id, config, provenance: Provenance):
    """``{question name: answer}`` the synthetic stage-one request for one passage stores."""
    role, overrides = spec["roles"][passage_id]
    p_keep, level = ROLES[role]
    p_keep = overrides.get("keep", p_keep)
    level = overrides.get("level", level)
    answers = {}
    if "keep" in helpers.stage_names(config):
        answers["keep"] = ChoiceAnswer.from_probabilities(
            {helpers.KEEP: p_keep, helpers.DROP: round(1 - p_keep, 4)}, provenance
        )
    if "relevance" in helpers.stage_names(config):
        answers["relevance"] = ScoreAnswer.from_probabilities(
            LEVEL_PROBABILITIES[level], helpers.RELEVANCE_LEVELS, provenance
        )
    return answers


def verdict_answer(spec, evidence_ids, roles_in_evidence, provenance: Provenance):
    """The synthetic verdict for one evidence set, written from how much of the gold evidence
    it holds (see ``VERIFY_DEFAULTS``)."""
    verdict, gold_ids = spec["gold"]
    overlap = set(gold_ids) & set(evidence_ids)
    if not gold_ids or overlap == set(gold_ids):
        state = "complete"
    elif overlap:
        state = "partial"
    else:
        state = "absent"
    if "F" in roles_in_evidence and "fooled" in spec["verify"]:
        state = "fooled"
    probs = spec["verify"].get(state) or VERIFY_DEFAULTS[verdict][state]
    return ChoiceAnswer.from_probabilities(
        dict(zip(helpers.VERDICTS, probs, strict=True)), provenance
    )


def requests_for(split, fields, spec):
    """``[(state, questions, answers)]`` for every request the notebook makes for one example,
    in the order it makes them. The pure functions the notebook runs choose the evidence, so a
    stored verdict is keyed by the evidence the pipeline really reads."""
    provenance = Provenance.synthetic()
    out = []
    claim = fields["claim"]
    for config in helpers.RUN_CONFIGS[split]:
        questions = helpers.stage_one_questions(config)
        cands = helpers.candidates(fields)
        keep, relevance = {}, {}
        if questions:
            for c in cands:
                answers = stage_one_answers(spec, c.passage_id, config, provenance)
                out.append((helpers.stage_one_state(claim, c.text), questions, answers))
                if "keep" in answers:
                    keep[c.passage_id] = answers["keep"]
                if "relevance" in answers:
                    relevance[c.passage_id] = answers["relevance"]
        evidence = helpers.select_evidence(cands, config, keep, relevance)
        if evidence:
            roles = {spec["roles"][c.passage_id][0] for c in evidence}
            answer = verdict_answer(spec, [c.passage_id for c in evidence], roles, provenance)
            state = helpers.verify_state(claim, [c.text for c in evidence])
            out.append((state, helpers.verdict_questions(), {"verdict": answer}))
    return out


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, fields, label, spec in rows:
        keys = []
        for state, questions, _answers in requests_for(split, fields, spec):
            key = replay_key(state, questions)
            if key not in keys:
                keys.append(key)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, split, fields, _label, spec in rows:
        for state, questions, answers in requests_for(split, fields, spec):
            responses[replay_key(state, questions)] = DecisionResult(answers, "synthetic").to_dict()
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
    # dump_responses is the serialization the recorder writes with (top-level keys sorted, each
    # response keeping the field order DecisionResult.to_dict() emits), so a recording's diff
    # stays limited to the values that actually changed.
    responses_file.write_text(dump_responses(responses), encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
