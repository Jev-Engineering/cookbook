"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 57.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic: hand-written probabilities, not produced by a model, and some are
wrong on purpose (a confidently wrong person match, a missed conflict, a missed relationship, an
over-read "ended"), so the evaluation has something to find. The replay keys come from the same
state and question builders the notebook uses.

Each example lists one or two replay keys. Request 1 is asked for every example. Request 2
depends on request 1's answer, so it is asked only when the rule lets request 1 through
(``helpers.decide_first`` returns ``None``) under the first-stage settings frozen on
``validation`` (``helpers.freeze_stage_one``); this script runs that same selection on the stored
answers to know which examples have a second key, and refuses a row whose second-stage answer
is present when it is not needed or missing when it is.

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
    NoulAnswer,
    Provenance,
    dump_responses,
    load_helpers,
    replay_key,
)

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)


def _fields(mention, target, *excerpts):
    return {
        "mention": mention,
        "target": target,
        "excerpts": [{"source": s, "text": t} for s, t in excerpts],
    }


def _replace(person, old, new):
    return [["delete", f"edge:{person}|works_at|{old}"], ["put", f"edge:{person}|works_at|{new}"]]


NOTHING = []

# (id, split, fields, gold label or None for demo, (entity probabilities, conflict noul,
#  (supported noul, ended noul) or None when request 2 is not asked); the whole spec is None for
#  a mention with no candidate, which has no request at all)
ROWS = [
    # ---- validation -------------------------------------------------------------------------
    ("v01", "validation", _fields(
        "Mira Okafor", "O2",
        ("Staff newsletter", "Mira Okafor, the chemist, left Brightwater Labs in March."),
        ("Press note", "Halden Institute welcomed chemist Mira Okafor to its staff this spring.")),
     {"entity": "P01", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P01", "O1", "O2")},
     ({"P01": 0.86, "P02": 0.06, "no_match": 0.08}, 0.06, (0.91, 0.88))),
    ("v02-initial", "validation", _fields(
        "M. Okafor", "O4",
        ("Trade bulletin", "Engineer M. Okafor has joined Tessaly Foundry's furnace team."),
        ("Team blog", "Quillmoor Analytics said goodbye to its engineer Okafor last month.")),
     {"entity": "P02", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P02", "O3", "O4")},
     ({"P02": 0.71, "P01": 0.17, "no_match": 0.12}, 0.10, (0.87, 0.74))),
    ("v03-no-match", "validation", _fields(
        "Lena Okafor", "O6",
        ("Clinic notice", "Lena Okafor, a pharmacist, starts at Vantrell Clinic next week.")),
     {"entity": "no_match", "conflict": False, "update": NOTHING},
     ({"P01": 0.48, "P02": 0.12, "no_match": 0.40}, 0.05, None)),
    ("v04-unsupported", "validation", _fields(
        "Ines Varga", "O2",
        ("Event listing", "Astronomer Ines Varga gave a guest lecture at Halden Institute."),
        ("Observatory page", "Ines Varga remains on the staff of Orrin Bay Observatory.")),
     {"entity": "P03", "conflict": False, "supported": False, "ended": False,
      "update": NOTHING},
     ({"P03": 0.93, "P04": 0.02, "no_match": 0.05}, 0.12, (0.18, 0.09))),
    ("v05-invariant", "validation", _fields(
        "Tomas Varga", "O1",
        ("Staff newsletter", "Tomas Varga now also keeps the books for Brightwater Labs two days a week."),
        ("Directory page", "He continues as an accountant at Tessaly Foundry.")),
     {"entity": "P04", "conflict": False, "supported": True, "ended": False,
      "update": NOTHING},
     ({"P04": 0.88, "P03": 0.05, "no_match": 0.07}, 0.35, (0.84, 0.22))),
    ("v06-left-only", "validation", _fields(
        "Ada Lindqvist", "O3",
        ("Clinic notice", "Dr. Ada Lindqvist retired from Vantrell Clinic in June."),
        ("Local paper", "Lindqvist has not announced any new position.")),
     {"entity": "P05", "conflict": False, "supported": False, "ended": True,
      "update": NOTHING},
     ({"P05": 0.90, "no_match": 0.10}, 0.08, (0.12, 0.93))),
    ("v07-conflict", "validation", _fields(
        "Jonah Pell", "O5",
        ("Observatory page", "Jonah Pell joined Orrin Bay Observatory as a data analyst."),
        ("Press note", "A Quillmoor Analytics spokesperson said Jonah Pell still works there and has not moved.")),
     {"entity": "P06", "conflict": True, "update": NOTHING},
     ({"P06": 0.84, "P07": 0.06, "no_match": 0.10}, 0.81, None)),
    ("v08", "validation", _fields(
        "Sami Ekwueme", "O6",
        ("Clinic notice", "Biologist Sami Ekwueme moved from Halden Institute to Vantrell Clinic."),
        ("Directory page", "Vantrell Clinic lists Ekwueme in its new research unit.")),
     {"entity": "P08", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P08", "O2", "O6")},
     ({"P08": 0.95, "no_match": 0.05}, 0.07, (0.89, 0.58))),
    ("v09-initial", "validation", _fields(
        "N. Haddad", "O5",
        ("Staff newsletter", "Statistician N. Haddad has left Halden Institute."),
        ("Observatory page", "N. Haddad now runs the visitor surveys at Orrin Bay Observatory.")),
     {"entity": "P09", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P09", "O2", "O5")},
     ({"P09": 0.66, "P10": 0.22, "no_match": 0.12}, 0.09, (0.80, 0.83))),
    ("v10", "validation", _fields(
        "Clara Moss", "O1",
        ("Staff newsletter", "Nurse Clara Moss transferred from Vantrell Clinic to the Brightwater Labs health office.")),
     {"entity": "P11", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P11", "O6", "O1")},
     ({"P11": 0.89, "P12": 0.04, "no_match": 0.07}, 0.05, (0.76, 0.41))),
    ("v11-invariant", "validation", _fields(
        "Yara Sato", "O3",
        ("Trade bulletin", "Geologist Yara Sato has signed a part-time contract with Quillmoor Analytics."),
        ("Directory page", "Sato keeps her post at Tessaly Foundry.")),
     {"entity": "P13", "conflict": False, "supported": True, "ended": False,
      "update": NOTHING},
     ({"P13": 0.87, "P14": 0.05, "no_match": 0.08}, 0.28, (0.82, 0.46))),
    ("v12-no-match", "validation", _fields(
        "H. Brekke", "O3",
        ("Local paper", "H. Brekke, the pastry chef, is opening a cafe beside Quillmoor Analytics.")),
     {"entity": "no_match", "conflict": False, "update": NOTHING},
     ({"no_match": 0.42, "P15": 0.38, "P16": 0.20}, 0.04, None)),
    # ---- test -------------------------------------------------------------------------------
    ("t01", "test", _fields(
        "Felix Moss", "O2",
        ("Team blog", "Software developer Felix Moss left Quillmoor Analytics in May."),
        ("Press note", "Halden Institute hired Felix Moss to build its archive tools.")),
     {"entity": "P12", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P12", "O3", "O2")},
     ({"P12": 0.90, "P11": 0.04, "no_match": 0.06}, 0.06, (0.88, 0.79))),
    ("t02-initial", "test", _fields(
        "R. Pell", "O1",
        ("Trade bulletin", "Metallurgist R. Pell has moved from Tessaly Foundry to Brightwater Labs.")),
     {"entity": "P07", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P07", "O4", "O1")},
     ({"P07": 0.74, "P06": 0.16, "no_match": 0.10}, 0.11, (0.85, 0.90))),
    ("t03-left-only", "test", _fields(
        "Owen Sato", "O4",
        ("Local paper", "Optician Owen Sato will open an eyewear shop of his own."),
        ("Clinic notice", "Sato is leaving Vantrell Clinic at the end of the month.")),
     {"entity": "P14", "conflict": False, "supported": False, "ended": True,
      "update": NOTHING},
     ({"P14": 0.91, "P13": 0.03, "no_match": 0.06}, 0.09, (0.21, 0.86))),
    ("t04-invariant", "test", _fields(
        "Hana Brekke", "O1",
        ("Staff newsletter", "Physicist Hana Brekke has taken a second, part-time post at Brightwater Labs."),
        ("Observatory page", "She keeps her full-time position at Orrin Bay Observatory.")),
     {"entity": "P15", "conflict": False, "supported": True, "ended": False,
      "update": NOTHING},
     ({"P15": 0.92, "P16": 0.03, "no_match": 0.05}, 0.24, (0.86, 0.19))),
    ("t05-unsupported", "test", _fields(
        "Leo Haddad", "O3",
        ("Event listing", "Leo Haddad, a lab technician at Brightwater Labs, visited Quillmoor Analytics for a demonstration.")),
     {"entity": "P10", "conflict": False, "supported": False, "ended": False,
      "update": NOTHING},
     ({"P10": 0.89, "P09": 0.05, "no_match": 0.06}, 0.07, (0.78, 0.12))),
    ("t06-conflict", "test", _fields(
        "Dev Brekke", "O6",
        ("Clinic notice", "Radiographer Dev Brekke started at Vantrell Clinic on Monday."),
        ("Press note", "Halden Institute says Dev Brekke is still on its payroll and never left.")),
     {"entity": "P16", "conflict": True, "update": NOTHING},
     ({"P16": 0.86, "P15": 0.05, "no_match": 0.09}, 0.88, None)),
    ("t07-no-match", "test", _fields(
        "Ina Okafor", "O4",
        ("Local paper", "Ina Okafor, a violinist, joined the Tessaly Foundry works band.")),
     {"entity": "no_match", "conflict": False, "update": NOTHING},
     ({"no_match": 0.81, "P01": 0.10, "P02": 0.09}, 0.05, None)),
    ("t08-wrong-match", "test", _fields(
        "B. Calloway", "O2",
        ("Press note", "Former Orrin Bay Observatory telescope engineer B. Calloway has joined Halden Institute.")),
     {"entity": "P18", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P18", "O5", "O2")},
     ({"P17": 0.78, "P18": 0.15, "no_match": 0.07}, 0.10, (0.81, 0.55))),
    ("t09", "test", _fields(
        "Edda Rhee", "O5",
        ("Staff newsletter", "Archivist Edda Rhee left Halden Institute after nine years."),
        ("Observatory page", "Orrin Bay Observatory announced Edda Rhee as its new archivist.")),
     {"entity": "P19", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P19", "O2", "O5")},
     ({"P19": 0.88, "P20": 0.05, "no_match": 0.07}, 0.05, (0.90, 0.80))),
    ("t10-missed", "test", _fields(
        "Milo Rhee", "O6",
        ("Clinic notice", "Pharmacist Milo Rhee will run the Vantrell Clinic dispensary from June."),
        ("Team blog", "Quillmoor Analytics confirmed that May was Milo Rhee's last month there.")),
     {"entity": "P20", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P20", "O3", "O6")},
     ({"P20": 0.85, "P19": 0.06, "no_match": 0.09}, 0.12, (0.70, 0.85))),
    ("t11-conflict", "test", _fields(
        "Gwen Tallis", "O5",
        ("Observatory page", "Gwen Tallis now works at Orrin Bay Observatory as its safety officer."),
        ("Trade bulletin", "This week's Tessaly Foundry bulletin quotes Tallis as its current safety lead.")),
     {"entity": "P21", "conflict": True, "update": NOTHING},
     ({"P21": 0.94, "no_match": 0.06}, 0.38, (0.83, 0.66))),
    ("t12-low-confidence", "test", _fields(
        "Calloway", "O3",
        ("Team blog", "Calloway, the architect, joined Quillmoor Analytics after leaving Brightwater Labs.")),
     {"entity": "P17", "conflict": False, "supported": True, "ended": True,
      "update": _replace("P17", "O1", "O3")},
     ({"P17": 0.52, "P18": 0.33, "no_match": 0.15}, 0.08, None)),
    # ---- demo -------------------------------------------------------------------------------
    ("d01", "demo", _fields(
        "P. Lund", "O3",
        ("Staff newsletter", "Survey designer P. Lund has left Halden Institute."),
        ("Team blog", "Quillmoor Analytics introduced P. Lund, who will design its customer surveys.")),
     None,
     ({"P22": 0.80, "P23": 0.08, "no_match": 0.12}, 0.07, (0.88, 0.84))),
    ("d02", "demo", _fields(
        "Lund", "O4",
        ("Event listing", "Lund will demonstrate a new instrument at Tessaly Foundry on Friday.")),
     None,
     ({"P23": 0.45, "P22": 0.35, "no_match": 0.20}, 0.06, None)),
]  # fmt: skip


def first_answers(spec, provenance: Provenance):
    """Request 1's typed answers for one row."""
    entity, conflict, _second = spec
    return {
        "entity": ChoiceAnswer.from_probabilities(dict(entity), provenance),
        "conflict": NoulAnswer(conflict, provenance),
    }


def second_answers(spec, provenance: Provenance):
    """Request 2's typed answers for one row."""
    supported, ended = spec[2]
    return {
        "supported": NoulAnswer(supported, provenance),
        "ended": NoulAnswer(ended, provenance),
    }


def _first_results(rows):
    """Request 1's result per row, as ``ask_first`` stores it: a mention with no candidate has no
    request and no answer (``UNMATCHED``), and its spec is ``None``."""
    return {
        ident: (
            DecisionResult(first_answers(spec, Provenance.synthetic()), "synthetic")
            if helpers.candidates(fields["mention"])
            else helpers.UNMATCHED
        )
        for ident, _split, fields, _label, spec in rows
    }


def stage_one_settings(rows, first=None):
    """The first-stage settings the notebook freezes, computed with the same helper."""
    first = _first_results(rows) if first is None else first
    validation = [r for r in rows if r[1] == "validation"]
    return helpers.freeze_stage_one([first[r[0]] for r in validation], [r[3] for r in validation])


def requests_for(rows):
    """``[(id, [(state, questions), ...]), ...]``: every request the notebook makes per row.
    The stage-one answers and settings are computed once here."""
    first = _first_results(rows)
    settings = stage_one_settings(rows, first)
    out = []
    for ident, _split, fields, _label, spec in rows:
        if first[ident] == helpers.UNMATCHED:
            if spec is not None:
                raise ValueError(f"{ident}: the mention has no candidate, so it has no answers")
            out.append((ident, []))
            continue
        requests = [
            (helpers.build_first_state(fields), helpers.build_first_questions(ident, fields))
        ]
        asked = helpers.decide_first(first[ident], settings) is None
        if asked != (spec[2] is not None):
            raise ValueError(
                f"{ident}: request 2 is {'asked' if asked else 'not asked'} under the frozen "
                "first-stage settings, so its stored answer must be "
                f"{'present' if asked else 'absent'}"
            )
        if asked:
            person = first[ident]["entity"].choice
            requests.append(
                (helpers.build_second_state(fields, person), helpers.build_second_questions())
            )
        out.append((ident, requests))
    return out


def build_inputs_and_labels(rows, requests=None):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded. ``requests`` is
    ``dict(requests_for(rows))``, passed in by ``main`` so it is computed once."""
    inputs, labels = [], []
    requests = dict(requests_for(rows)) if requests is None else requests
    for ident, split, fields, label, _spec in rows:
        keys = [replay_key(state, questions) for state, questions in requests[ident]]
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows, requests=None):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response. ``requests`` as in
    ``build_inputs_and_labels``."""
    responses = {}
    requests = dict(requests_for(rows)) if requests is None else requests
    for ident, _split, _fields, _label, spec in rows:
        builders = (first_answers, second_answers)
        for (state, questions), build in zip(requests[ident], builders, strict=False):
            answers = build(spec, Provenance.synthetic())
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
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    requests = dict(requests_for(ROWS))
    inputs, labels = build_inputs_and_labels(ROWS, requests)
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
    responses = build_responses(ROWS, requests)
    # dump_responses is the serialization the recorder writes with (top-level keys sorted, each
    # response keeping the field order DecisionResult.to_dict() emits), so a recording's diff
    # stays limited to the values that actually changed.
    responses_file.write_text(dump_responses(responses), encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
