"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 37.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (three hand-written probabilities per passage, one per domain in
``helpers.DOMAINS``, never produced by a model) and deliberately imperfect. The gold label for
each scored passage is the *set* of research domains it actually raises: some passages raise
none, most raise one or two, and a few raise all three -- a full sweep of the eight possible
domain combinations (CONTRIBUTING.md section 5's "mixed" and "ambiguous" hard cases), repeated
with a second, harder variant of each so the fixture set also carries a benign look-alike per
combination: a passage that uses a domain's vocabulary ("cost", "algorithm", "patient") without
its subject actually belonging to that domain. A handful of passages are marked
``access: "restricted"``; their domain content is authored the same way as any other passage's,
on purpose, so being restricted is never predictable from what a passage is about.

The replay keys come from the same ``build_state`` and ``build_questions`` the notebook uses, via
``helpers.py``. Generating inputs and labels is kept separate from generating responses, on
purpose: once ``responses.json`` holds even one recorded answer (provenance ``"recorded"``,
captured from a real Jev call), running this script again must not silently replace it with a
synthetic probability. ``inputs.jsonl`` and ``labels.jsonl`` are always rewritten from ``ROWS``,
because neither ever holds a model's answer; ``responses.json`` is rewritten only when it does
not yet exist, holds only synthetic answers, or ``--force`` is given.

A restricted passage is never decided (CONTRIBUTING.md section 3 and the use case's own access
control requirement), so it lists no replay key and gets no entry in ``responses.json`` at all:
its row's probability spec is ``None``, and both generators below treat that as "nothing to
replay" rather than "a response of all zeros".
"""

import argparse
import json
from pathlib import Path

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
DOMAINS = list(helpers.DOMAINS)  # biomedical, computational, economics -- the probs tuple order
OPEN = helpers.ACCESS_OPEN
RESTRICTED = helpers.ACCESS_RESTRICTED


def _fields(passage_id, text, access):
    return {"passage_id": passage_id, "text": text, "access": access}


# (id, split, passage_id, text, access, gold domains (tuple, () for none; None for a demo
# example that is never scored), stored probabilities in DOMAINS order, or None for a restricted
# passage that is never decided and so never gets a response)
ROWS = [
    # --- validation: 16 scored passages, the full 8-combination sweep, two variants each ------
    ("v01-none-clean", "validation", "RP-101",
     "Our fieldwork catalogs variation in surface decoration on ceramic sherds recovered from "
     "six Bronze Age settlement sites, compared against regional museum collections.",
     OPEN, (), (0.04, 0.05, 0.03)),
    ("v02-none-lookalike", "validation", "RP-102",
     "The clinic's new appointment-scheduling software automatically emails patients a "
     "reminder and logs the time saved for the front-desk budget report.",
     OPEN, (), (0.30, 0.38, 0.22)),
    ("v03-biomedical-clean", "validation", "RP-103",
     "We report a randomized trial comparing two dosing schedules of a lipid-lowering compound "
     "in 220 adult patients with elevated cholesterol, measuring LDL reduction at twelve weeks.",
     OPEN, ("biomedical",), (0.88, 0.05, 0.06)),
    ("v04-biomedical-lookalike", "validation", "RP-104",
     "We describe the clinical course of a rare autoimmune skin condition in 40 patients, "
     "noting that most reported the condition's daily cost of managing flare-ups but offering "
     "no economic analysis of that burden.",
     OPEN, ("biomedical",), (0.86, 0.04, 0.83)),  # economics: wrong and confident on purpose
    ("v05-computational-clean", "validation", "RP-105",
     "We propose a new attention-sparsification method for transformer language models that "
     "cuts inference memory by 40 percent while matching baseline accuracy on three public "
     "benchmarks.",
     OPEN, ("computational",), (0.05, 0.90, 0.04)),
    ("v06-computational-lookalike", "validation", "RP-106",
     "We design a constraint-based scheduling algorithm for operating-room time slots and "
     "show, in simulation, a 15 percent reduction in average patient wait time compared to the "
     "hospital's existing heuristic.",
     OPEN, ("computational",), (0.46, 0.84, 0.10)),  # biomedical: low-confidence correct "no"
    ("v07-economics-clean", "validation", "RP-107",
     "Using a difference-in-differences design across fourteen states, we estimate the effect "
     "of a minimum-wage increase on small-business employment over three years.",
     OPEN, ("economics",), (0.04, 0.07, 0.89)),
    ("v08-economics-lookalike", "validation", "RP-108",
     "We build a simple rule-of-thumb forecasting procedure, described in one paragraph with "
     "no code or formal algorithm, to estimate quarterly retail sales, and evaluate it against "
     "a naive baseline using out-of-sample forecast error.",
     OPEN, ("economics",), (0.03, 0.34, 0.85)),
    ("v09-biocomp-clean", "validation", "RP-109",
     "We train a convolutional neural network on whole-slide histopathology images to "
     "classify tumor subtypes, validated against pathologist annotations from 400 biopsy "
     "samples.",
     OPEN, ("biomedical", "computational"), (0.85, 0.87, 0.05)),
    ("v10-biocomp-lookalike", "validation", "RP-110",
     "We develop a graph neural network that predicts protein-protein interactions from "
     "sequence data, and note in passing that faster discovery could eventually lower "
     "drug-development costs industry-wide.",
     OPEN, ("biomedical", "computational"), (0.80, 0.86, 0.33)),
    ("v11-bioecon-clean", "validation", "RP-111",
     "We build a cost-effectiveness model comparing two diabetes treatment regimens, "
     "estimating quality-adjusted life years and total healthcare spending over a ten-year "
     "horizon.",
     OPEN, ("biomedical", "economics"), (0.83, 0.06, 0.87)),
    ("v12-bioecon-lookalike", "validation", "RP-112",
     "We use a standard actuarial life-table approach, without any machine-learning "
     "component, to project the long-term healthcare costs and survival of patients starting "
     "a new hypertension therapy.",
     OPEN, ("biomedical", "economics"), (0.81, 0.11, 0.84)),
    ("v13-compecon-clean", "validation", "RP-113",
     "We develop a reinforcement-learning trading agent and backtest its portfolio-allocation "
     "strategy against historical market-index returns to measure risk-adjusted excess "
     "return.",
     OPEN, ("computational", "economics"), (0.05, 0.88, 0.86)),
    ("v14-compecon-lookalike", "validation", "RP-114",
     "We model investors as patient, boundedly rational agents in an agent-based market "
     "simulation, and compare the resulting price volatility against a reinforcement-learning "
     "trading baseline.",
     OPEN, ("computational", "economics"), (0.12, 0.83, 0.81)),
    ("v15-all-clean", "validation", "RP-115",
     "We combine a machine-learning model of hospital-readmission risk with a cost model to "
     "estimate the budget impact of a predictive discharge-planning algorithm across a "
     "regional hospital network.",
     OPEN, ("biomedical", "computational", "economics"), (0.86, 0.85, 0.84)),
    ("v16-all-lookalike", "validation", "RP-116",
     "We build a microsimulation that uses a trained classifier to flag high-risk diabetic "
     "patients for early intervention, and estimate the resulting change in total insurer "
     "spending under three policy scenarios.",
     OPEN, ("biomedical", "computational", "economics"), (0.82, 0.79, 0.80)),
    # A third, harder economics-only variant each: pure policy-economics passages that use
    # vocabulary associated with a different domain ("patients", "algorithm") without actually
    # reporting a biomedical or computational finding, so every domain -- not only economics --
    # carries at least one confidently wrong stored tag on this split (see the module docstring
    # above and the notebook's "Evaluation" section for why this matters).
    ("v19-economics-biomedical-wrong", "validation", "RP-119",
     "We evaluate how a new drug-pricing regulation affects patients' out-of-pocket costs and "
     "manufacturers' research spending, using a structural model of pharmaceutical demand.",
     OPEN, ("economics",), (0.81, 0.05, 0.85)),  # biomedical: wrong and confident on purpose
    ("v20-economics-computational-wrong", "validation", "RP-120",
     "We propose a simple step-by-step rule, analogous to an algorithm, for a central bank to "
     "adjust interest rates in response to inflation, and evaluate its historical performance "
     "against discretionary policy.",
     OPEN, ("economics",), (0.04, 0.80, 0.86)),  # computational: wrong and confident on purpose
    # --- validation: 2 restricted passages, domains authored independently of access ----------
    ("v17-restricted", "validation", "RP-117",
     "We report unpublished interim results from an ongoing trial of a new anticoagulant in "
     "high-risk surgical patients.",
     RESTRICTED, ("biomedical",), None),
    ("v18-restricted", "validation", "RP-118",
     "We benchmark a proprietary high-frequency trading model against three competitor "
     "algorithms using a vendor's licensed intraday order-book dataset.",
     RESTRICTED, ("computational", "economics"), None),
    # --- test: 16 scored passages, the same 8-combination sweep, different wording ------------
    ("t01-none-clean", "test", "RP-201",
     "The symposium program committee finalized the schedule of poster sessions and assigned "
     "reviewers to monitor each session room.",
     OPEN, (), (0.03, 0.04, 0.03)),
    ("t02-none-lookalike", "test", "RP-202",
     "The lab's new inventory-tracking app logs reagent stock levels and flags low supplies "
     "for the next purchase order.",
     OPEN, (), (0.28, 0.40, 0.20)),
    ("t03-biomedical-clean", "test", "RP-203",
     "We present a phase II trial of an inhaled bronchodilator in 150 adults with moderate "
     "asthma, reporting change in forced expiratory volume at eight weeks.",
     OPEN, ("biomedical",), (0.87, 0.04, 0.05)),
    ("t04-biomedical-lookalike", "test", "RP-204",
     "We summarize nursing-reported outcomes for 60 hospice patients, noting that families "
     "often raised concerns about the cost of at-home care, with no formal cost analysis "
     "performed in this study.",
     OPEN, ("biomedical",), (0.85, 0.05, 0.80)),  # economics: wrong and confident on purpose
    ("t05-computational-clean", "test", "RP-205",
     "We introduce a quantization scheme for large language models that reduces model size by "
     "half with less than one point of accuracy loss on standard benchmarks.",
     OPEN, ("computational",), (0.04, 0.89, 0.05)),
    ("t06-computational-lookalike", "test", "RP-206",
     "We build a priority-queueing algorithm for emergency-room triage order and simulate its "
     "effect on average time-to-first-assessment, without modeling any clinical outcome.",
     OPEN, ("computational",), (0.47, 0.83, 0.09)),  # biomedical: low-confidence correct "no"
    ("t07-economics-clean", "test", "RP-207",
     "We use an event-study design around a corporate-tax-rate change to estimate its effect "
     "on firms' capital investment over the following two years.",
     OPEN, ("economics",), (0.05, 0.06, 0.88)),
    ("t08-economics-lookalike", "test", "RP-208",
     "We tally, by hand with a spreadsheet and no predictive model, the historical frequency "
     "of supply disruptions reported by a regional distributor, and compare the counts across "
     "years.",
     OPEN, ("economics",), (0.04, 0.31, 0.84)),
    ("t09-biocomp-clean", "test", "RP-209",
     "We fine-tune a deep-learning model on retinal images to detect diabetic retinopathy, "
     "validated against ophthalmologist grades on an independent test set.",
     OPEN, ("biomedical", "computational"), (0.84, 0.88, 0.04)),
    ("t10-biocomp-lookalike", "test", "RP-210",
     "We build a natural-language-processing pipeline that extracts adverse-drug-event "
     "mentions from clinical notes, and note the pipeline could someday reduce the cost of "
     "manual chart review.",
     OPEN, ("biomedical", "computational"), (0.82, 0.85, 0.35)),
    ("t11-bioecon-clean", "test", "RP-211",
     "We estimate the lifetime medical cost and survival gain of a new hepatitis-C treatment "
     "regimen using a Markov cost-effectiveness model calibrated to trial data.",
     OPEN, ("biomedical", "economics"), (0.85, 0.05, 0.86)),
    ("t12-bioecon-lookalike", "test", "RP-212",
     "We compile a simple cost ledger, without any statistical or machine-learning model, "
     "comparing two wound-care supply regimens' total spend across a single hospital ward.",
     OPEN, ("biomedical", "economics"), (0.80, 0.10, 0.82)),
    ("t13-compecon-clean", "test", "RP-213",
     "We train a gradient-boosted model to predict loan default and evaluate, in backtests, "
     "the change in a lender's expected losses under three underwriting policies.",
     OPEN, ("computational", "economics"), (0.05, 0.87, 0.85)),
    ("t14-compecon-lookalike", "test", "RP-214",
     "We simulate a market of patient (slow-trading) and impatient (fast-trading) algorithmic "
     "agents and measure the resulting bid-ask spread under each population mix.",
     OPEN, ("computational", "economics"), (0.14, 0.82, 0.79)),
    ("t15-all-clean", "test", "RP-215",
     "We combine a trained risk model for post-surgical complications with a hospital cost "
     "model to estimate the net savings of a new predictive-monitoring program across a "
     "hospital system.",
     OPEN, ("biomedical", "computational", "economics"), (0.85, 0.84, 0.83)),
    ("t16-all-lookalike", "test", "RP-216",
     "We build a classifier that flags patients likely to skip follow-up appointments and "
     "estimate, under a simple budget model, the insurer savings from a targeted outreach "
     "algorithm.",
     OPEN, ("biomedical", "computational", "economics"), (0.81, 0.80, 0.78)),
    # The matching third economics-only variants on test (different wording from validation,
    # per the leak rule): one with a confident wrong biomedical tag, one with a confident wrong
    # computational tag, so test carries the same per-domain lesson validation does.
    ("t19-economics-biomedical-wrong", "test", "RP-219",
     "We evaluate how a change in vaccine-procurement contracts affects national governments' "
     "negotiated unit prices and manufacturers' production investment, using a bargaining "
     "model of the vaccine market.",
     OPEN, ("economics",), (0.84, 0.04, 0.84)),  # biomedical: wrong and confident on purpose
    ("t20-economics-computational-wrong", "test", "RP-220",
     "We describe a fixed, published step-by-step procedure, similar to an algorithm, that a "
     "finance ministry follows when revising its annual budget forecast, and compare its "
     "historical accuracy against discretionary revisions.",
     OPEN, ("economics",), (0.05, 0.84, 0.85)),  # computational: wrong and confident on purpose
    # --- test: 2 restricted passages, domains authored independently of access ----------------
    ("t17-restricted", "test", "RP-217",
     "Internal draft notes summarize a funding panel's closed-door discussion of next year's "
     "research priorities.",
     RESTRICTED, (), None),
    ("t18-restricted", "test", "RP-218",
     "We present not-yet-public cost and outcome data from a pharmaceutical co-funded "
     "diabetes-management trial, including unaudited financial figures.",
     RESTRICTED, ("biomedical", "economics"), None),
    # --- demo: 2 examples, shown but never scored ----------------------------------------------
    ("d01-all-demo", "demo", "RP-301",
     "We pair a machine-learning readmission-risk model with a cost-accounting framework to "
     "estimate the five-year budget effect of a hospital's new post-discharge nurse-call "
     "program.",
     OPEN, None, (0.87, 0.84, 0.82)),
    ("d02-restricted-demo", "demo", "RP-302",
     "We evaluate an unreleased internal fraud-detection model using the vendor's confidential "
     "production logs, which the data-sharing agreement does not permit disclosing "
     "externally.",
     RESTRICTED, None, None),
]  # fmt: skip


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded.

    A restricted passage lists no replay key at all (``docs/fixtures.md``'s "replay_keys may be
    empty for an example" applies per example, not only per recipe): the access-control filter
    means it is never decided, so there is no request for it to list a key for. A gold label is
    still written for every ``validation``/``test`` passage, restricted ones included, because
    the fixture schema requires exactly one label per scored example and the domains a
    restricted passage actually raises are still a fact about it -- they are simply never the
    thing this recipe asks Jev about.
    """
    inputs, labels = [], []
    for ident, split, passage_id, text, access, gold, _spec in rows:
        fields = {"passage_id": passage_id, "text": text, "access": access}
        keys = [] if access == RESTRICTED else [replay_key(helpers.build_state(fields), QUESTIONS)]
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if gold is not None:
            labels.append({"id": ident, "label": sorted(gold)})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response. A restricted passage's ``_spec`` is
    ``None`` and contributes no entry: it is never decided, so there is nothing to store."""
    responses = {}
    for _ident, _split, passage_id, text, access, _gold, spec in rows:
        if spec is None:
            continue
        fields = {"passage_id": passage_id, "text": text, "access": access}
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = {
            domain: NoulAnswer(p, Provenance.synthetic())
            for domain, p in zip(DOMAINS, spec, strict=True)
        }
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
        raise SystemExit("ROWS is empty; add examples to it in build_fixtures.py")
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
