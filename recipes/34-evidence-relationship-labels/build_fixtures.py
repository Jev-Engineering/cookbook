"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 34.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic and deliberately imperfect. See docs/fixtures.md and
recipes/_template/build_fixtures.py for the pattern this follows.

Generating inputs and labels is kept separate from generating responses, on purpose: once
responses.json holds even one recorded answer (provenance "recorded", captured from a real Jev
call), running this script again must not silently replace it with a synthetic probability.
inputs.jsonl and labels.jsonl are always rewritten from ROWS, because neither ever holds a
model's answer; responses.json is rewritten only when it does not yet exist, holds only
synthetic answers, or --force is given.

Each row is one knowledge-graph *task*: an ordered entity pair with one or more evidence
passages. Every passage gets its own replay key (one Choice request per passage -- the state
differs, so the request differs) and its own independently authored gold label; the task also
carries its own independently authored gold label, the composed relationship the whole evidence
bundle supports, which is never derived from the passages' gold labels by formula (two passages
can be authored to disagree with each other, and the task's own gold is simply the fact the
fixture author knows to be true of that task's bundle).

Each passage's ``predicted`` names the option the stored, synthetic probability distribution
actually peaks at; ``_probs`` takes it as a required argument (never defaulted), so a row cannot
silently mislabel its own stored answer, and ``tests/test_build_fixtures.py`` asserts every
committed response's top choice against it directly. ``predicted`` may differ from ``gold`` --
that is how a deliberately wrong stored answer is written.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
OPTIONS = helpers.OPTIONS


def _probs(predicted: str, p_top: float) -> dict[str, float]:
    """The stored probability distribution for one passage: ``p_top`` on ``predicted`` (always
    supplied, never defaulted -- see the module docstring), the remainder split evenly across
    every other option."""
    if predicted not in OPTIONS:
        raise ValueError(f"predicted must be one of {OPTIONS}, got {predicted!r}")
    remainder = (1.0 - p_top) / (len(OPTIONS) - 1)
    return {opt: (p_top if opt == predicted else remainder) for opt in OPTIONS}


def _passage(passage_id: str, text: str, gold: str | None, predicted: str, p_top: float) -> dict:
    return {
        "passage_id": passage_id,
        "text": text,
        "gold": gold,
        "predicted": predicted,
        "probs": _probs(predicted, p_top),
    }


W, F, A, S, N = (
    helpers.WORKS_FOR,
    helpers.FOUNDER_OF,
    helpers.ACQUIRED_BY,
    helpers.SUPPLIER_OF,
    (helpers.NO_SUPPORTED_RELATION),
)

# Every task below is one ordered entity pair with one or more evidence passages. Entities and
# events are all fabricated; no name belongs to a real company or person (CONTRIBUTING.md
# section 5). "entity_a" and "entity_b" play the roles each relationship description names --
# see helpers.py's OPTIONS descriptions for exactly which role is which.
#
# v05 and t05 are this recipe's hard case (the use case names it explicitly): each reuses an
# entity pair whose relationship is established by a *different* task's evidence passage
# elsewhere in this very file (v01's and t02's passages respectively, both committed fixtures a
# reader can open), but gives that pair a second passage that does not state the relationship --
# so the task's own gold is no_supported_relation even though the pair is related elsewhere in
# this recipe's own fixtures. v11 and t11 are the two-passage disagreement case: one passage
# correctly names the task's real relation, a second, unrelated-sounding passage about the same
# pair is stored with a confidently *wrong* real-relation guess, so the two accepted passages
# name two different relations and the composed task goes to review rather than Python silently
# preferring one passage over the other.
ROWS: list[dict[str, Any]] = [
    dict(
        id="v01",
        split="validation",
        entity_a="Priya Oduya",
        entity_b="Thornwell Systems",
        task_gold=W,
        passages=[
            _passage(
                "v01-ev1",
                "Priya Oduya has worked as a senior engineer at Thornwell Systems since "
                "March 2019, leading its platform reliability team.",
                W, W, 0.90,
            ),
        ],
    ),
    dict(
        id="v02",
        split="validation",
        entity_a="Marcus Bellweather",
        entity_b="Vexam Analytics",
        task_gold=F,
        passages=[
            _passage(
                "v02-ev1",
                "Marcus Bellweather founded Vexam Analytics in 2015 after leaving his "
                "previous role in market research.",
                F, F, 0.88,
            ),
        ],
    ),
    dict(
        id="v03",
        split="validation",
        entity_a="Baskerly Robotics",
        entity_b="Corrigan Freight",
        task_gold=A,
        passages=[
            _passage(
                "v03-ev1",
                "Baskerly Robotics was acquired by Corrigan Freight in a deal announced "
                "last quarter, folding its warehouse-automation line into Corrigan "
                "Freight's logistics division.",
                A, A, 0.85,
            ),
        ],
    ),
    dict(
        id="v04",
        split="validation",
        entity_a="Halvorsen Materials",
        entity_b="Baskerly Robotics",
        task_gold=S,
        passages=[
            _passage(
                "v04-ev1",
                "Halvorsen Materials supplies the structural alloys that Baskerly "
                "Robotics uses in its warehouse robots.",
                S, S, 0.84,
            ),
        ],
    ),
    dict(
        id="v05-hard",
        split="validation",
        entity_a="Priya Oduya",
        entity_b="Thornwell Systems",
        task_gold=N,
        passages=[
            _passage(
                "v05-ev1",
                "Priya Oduya was one of several panelists at the Northfield Data "
                "Summit, an event Thornwell Systems helped sponsor that year.",
                N, N, 0.78,
            ),
        ],
    ),
    dict(
        id="v06",
        split="validation",
        entity_a="Elena Castillo",
        entity_b="Vexam Analytics",
        task_gold=W,
        passages=[
            _passage(
                "v06-ev1",
                "Elena Castillo joined Vexam Analytics two years ago and now manages "
                "its client-analytics team.",
                W, W, 0.83,
            ),
        ],
    ),
    dict(
        id="v07-wrong",
        split="validation",
        entity_a="Nadia Okonkwo",
        entity_b="Corrigan Freight",
        task_gold=W,
        passages=[
            _passage(
                "v07-ev1",
                "Nadia Okonkwo has been a logistics coordinator at Corrigan Freight for "
                "the past four years.",
                W, F, 0.73,
            ),
        ],
    ),
    dict(
        id="v08-agree",
        split="validation",
        entity_a="Tomas Reyes",
        entity_b="Petrel Logistics",
        task_gold=F,
        passages=[
            _passage(
                "v08-ev1",
                "Tomas Reyes founded Petrel Logistics in 2011, starting with a single "
                "delivery van.",
                F, F, 0.89,
            ),
            _passage(
                "v08-ev2",
                "Petrel Logistics' own company history page credits Tomas Reyes as its "
                "founder and first driver.",
                F, F, 0.81,
            ),
        ],
    ),
    dict(
        id="v09-low",
        split="validation",
        entity_a="Dunmore Chemicals",
        entity_b="Ashgrove Capital",
        task_gold=A,
        passages=[
            _passage(
                "v09-ev1",
                "Industry newsletters mentioned that Ashgrove Capital had been in talks "
                "with Dunmore Chemicals, though the exact nature of any deal was not "
                "detailed.",
                A, A, 0.42,
            ),
        ],
    ),
    dict(
        id="v10",
        split="validation",
        entity_a="Rookwood Traders",
        entity_b="Quillon Media",
        task_gold=S,
        passages=[
            _passage(
                "v10-ev1",
                "Rookwood Traders has supplied raw newsprint to Quillon Media's "
                "regional papers for over a decade.",
                S, S, 0.80,
            ),
        ],
    ),
    dict(
        id="v11-disagree",
        split="validation",
        entity_a="Ines Alderman",
        entity_b="Dunmore Chemicals",
        task_gold=F,
        passages=[
            _passage(
                "v11-ev1",
                "Ines Alderman founded Dunmore Chemicals in 2003 and still sits on its "
                "board.",
                F, F, 0.87,
            ),
            _passage(
                "v11-ev2",
                "Ines Alderman also spent a year on secondment to Dunmore Chemicals' "
                "regional office before returning to lead the company she started.",
                N, W, 0.74,
            ),
        ],
    ),
    dict(
        id="v12-fallback-wrong",
        split="validation",
        entity_a="Sven Larkspur",
        entity_b="Rookwood Traders",
        task_gold=F,
        passages=[
            _passage(
                "v12-ev1",
                "Sven Larkspur started Rookwood Traders from his garage in 1998 and "
                "remains its majority owner.",
                F, N, 0.75,
            ),
        ],
    ),
    dict(
        id="t01",
        split="test",
        entity_a="Joss Fenwick",
        entity_b="Halvorsen Materials",
        task_gold=W,
        passages=[
            _passage(
                "t01-ev1",
                "Joss Fenwick has handled procurement at Halvorsen Materials for six "
                "years.",
                W, W, 0.86,
            ),
        ],
    ),
    dict(
        id="t02",
        split="test",
        entity_a="Dara Quince",
        entity_b="Marlstone Devices",
        task_gold=F,
        passages=[
            _passage(
                "t02-ev1",
                "Dara Quince founded Marlstone Devices in 2017 to build sensors for "
                "industrial robots.",
                F, F, 0.91,
            ),
        ],
    ),
    dict(
        id="t03",
        split="test",
        entity_a="Marlstone Devices",
        entity_b="Ferrow Shipping",
        task_gold=A,
        passages=[
            _passage(
                "t03-ev1",
                "Marlstone Devices was acquired by Ferrow Shipping last year, becoming "
                "Ferrow Shipping's sensor division.",
                A, A, 0.83,
            ),
        ],
    ),
    dict(
        id="t04",
        split="test",
        entity_a="Halvorsen Materials",
        entity_b="Marlstone Devices",
        task_gold=S,
        passages=[
            _passage(
                "t04-ev1",
                "Halvorsen Materials supplies the sensor-grade polymers that Marlstone "
                "Devices uses in its products.",
                S, S, 0.82,
            ),
        ],
    ),
    dict(
        id="t05-hard",
        split="test",
        entity_a="Dara Quince",
        entity_b="Marlstone Devices",
        task_gold=N,
        passages=[
            _passage(
                "t05-ev1",
                "Dara Quince appeared on a conference panel about sensor "
                "manufacturing, where Marlstone Devices was mentioned as one of the "
                "companies exhibiting.",
                N, N, 0.77,
            ),
        ],
    ),
    dict(
        id="t06",
        split="test",
        entity_a="Victor Amsel",
        entity_b="Ferrow Shipping",
        task_gold=W,
        passages=[
            _passage(
                "t06-ev1",
                "Victor Amsel has worked in Ferrow Shipping's fleet operations "
                "department since 2020.",
                W, W, 0.85,
            ),
        ],
    ),
    dict(
        id="t07-wrong",
        split="test",
        entity_a="Renata Voss",
        entity_b="Ashgrove Capital",
        task_gold=W,
        passages=[
            _passage(
                "t07-ev1",
                "Renata Voss has been an analyst at Ashgrove Capital since the start "
                "of last year.",
                W, S, 0.75,
            ),
        ],
    ),
    dict(
        id="t08-agree",
        split="test",
        entity_a="Callum Ashby",
        entity_b="Ferrow Shipping",
        task_gold=F,
        passages=[
            _passage(
                "t08-ev1",
                "Callum Ashby founded Ferrow Shipping in 1998 with two cargo trucks.",
                F, F, 0.86,
            ),
            _passage(
                "t08-ev2",
                "A profile piece on Ferrow Shipping's thirtieth anniversary credited "
                "founder Callum Ashby with the company's early growth.",
                F, F, 0.79,
            ),
        ],
    ),
    dict(
        id="t09-low",
        split="test",
        entity_a="Quillon Media",
        entity_b="Ashgrove Capital",
        task_gold=A,
        passages=[
            _passage(
                "t09-ev1",
                "There were unconfirmed reports that Ashgrove Capital was nearing a "
                "deal for Quillon Media, though neither side had commented publicly.",
                A, A, 0.38,
            ),
        ],
    ),
    dict(
        id="t10",
        split="test",
        entity_a="Dunmore Chemicals",
        entity_b="Marlstone Devices",
        task_gold=S,
        passages=[
            _passage(
                "t10-ev1",
                "Marlstone Devices sources specialty resins from Dunmore Chemicals for "
                "its sensor housings.",
                S, S, 0.81,
            ),
        ],
    ),
    dict(
        id="t11-disagree",
        split="test",
        entity_a="Imogen Sarkis",
        entity_b="Baskerly Robotics",
        task_gold=F,
        passages=[
            _passage(
                "t11-ev1",
                "Imogen Sarkis founded Baskerly Robotics in 2008, long before its "
                "acquisition by Corrigan Freight.",
                F, F, 0.84,
            ),
            _passage(
                "t11-ev2",
                "Imogen Sarkis later took a seat on Baskerly Robotics' advisory board "
                "after an unrelated executive post at a different firm.",
                N, W, 0.74,
            ),
        ],
    ),
    dict(
        id="t12-fallback-wrong",
        split="test",
        entity_a="Petrel Logistics",
        entity_b="Dunmore Chemicals",
        task_gold=S,
        passages=[
            _passage(
                "t12-ev1",
                "Petrel Logistics has handled freight forwarding for Dunmore "
                "Chemicals' import shipments since 2016.",
                S, N, 0.76,
            ),
        ],
    ),
    dict(
        id="d01",
        split="demo",
        entity_a="Omar Delacroix",
        entity_b="Thornwell Systems",
        task_gold=None,
        passages=[
            _passage(
                "d01-ev1",
                "Omar Delacroix joined Thornwell Systems as a product manager earlier "
                "this year.",
                None, W, 0.88,
            ),
        ],
    ),
    dict(
        id="d02",
        split="demo",
        entity_a="Omar Delacroix",
        entity_b="Vexam Analytics",
        task_gold=None,
        passages=[
            _passage(
                "d02-ev1",
                "Omar Delacroix attended a product conference where Vexam Analytics "
                "also had a booth.",
                None, N, 0.80,
            ),
        ],
    ),
]  # fmt: skip


def _fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair_id": row["id"],
        "entity_a": row["entity_a"],
        "entity_b": row["entity_b"],
        "passages": [{"passage_id": p["passage_id"], "text": p["text"]} for p in row["passages"]],
    }


def build_inputs_and_labels(rows: list[dict[str, Any]]):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for row in rows:
        fields = _fields(row)
        keys = [
            replay_key(state, QUESTIONS) for _passage_id, state in helpers.passage_states(fields)
        ]
        inputs.append(
            {"id": row["id"], "split": row["split"], "fields": fields, "replay_keys": keys}
        )
        if row["task_gold"] is not None:
            label = {
                "task": row["task_gold"],
                "passages": {p["passage_id"]: p["gold"] for p in row["passages"]},
            }
            labels.append({"id": row["id"], "label": label})
    return inputs, labels


def build_responses(rows: list[dict[str, Any]]):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for row in rows:
        fields = _fields(row)
        for (passage_id, state), passage in zip(
            helpers.passage_states(fields), row["passages"], strict=True
        ):
            assert passage_id == passage["passage_id"]
            key = replay_key(state, QUESTIONS)
            answer = ChoiceAnswer.from_probabilities(passage["probs"], Provenance.synthetic())
            responses[key] = DecisionResult({"relation": answer}, "synthetic").to_dict()
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
    n_passages = sum(len(r["passages"]) for r in ROWS)
    print(
        f"wrote {len(inputs)} tasks ({n_passages} passages), {len(labels)} labels, "
        f"{len(responses)} responses"
    )


if __name__ == "__main__":
    main()
