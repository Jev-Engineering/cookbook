"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 22.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every response is synthetic (written by hand as probabilities, not produced by a model) and
deliberately imperfect in several different ways, on purpose. Five fixtures retrieve no candidate
at all -- four scored (``v14-zero-candidate``, ``v15-zero-candidate``, ``t12-zero-candidate``,
``t18-zero-candidate``) and one ``demo`` (``d02-zero-candidate``): ``helpers.shortlist`` returns an
empty list for each of them, so ``helpers.build_questions`` is never called and no request is ever
sent (a forced answer belongs to Python, not a request -- a single-option Choice, offering only
the fallback, is never built). Those five rows carry no ``replay_keys`` and no entry in
``responses.json``.

Several assets exercise the Microsoft SQL Server major-version family (CMDB-01/02/03, 2016/2019/
2022): because retrieval ranks on vendor/product wording alone, all three always tie in similarity
and so always appear together, tie-broken by id -- this is also why the gold match for this family
is sometimes the shortlist's second or third entry rather than its first (``v10-sql-2019``,
``t09-sql-2019``: second; ``v11-sql-2022-lowconf``, ``t08-sql-2022``: third), the opposite of every
other real match in this recipe, whose shortlist always ranks the true match first because nothing
else in the catalog shares its vendor and product as closely. ``t10-sql-missing-version-wrong`` has
no version reported at all: this recipe's policy is that Python never asks Jev to guess a major
version it cannot see, so the gold label is ``no_match`` -- but the stored answer confidently names
CMDB-03 anyway, which is this recipe's one false link (an accepted link to the wrong record): a
real, wrong candidate at a confidence that clears the gate chosen below. ``v13-lookalike-wrong`` is
the validation set's own wrong answer, placed there on purpose: a lexical look-alike (Acrobat
Reader is a different, free product from the paid Acrobat the catalog holds, but shares enough
wording to be retrieved as a candidate) that the stored answer confidently names anyway, at a
confidence low enough to still be excluded by the gate ``select_confidence_threshold`` picks --
without a wrong answer inside validation itself, that selection would have nothing real to cut on
(docs/fixtures.md). ``t14-jira-missed`` is a real match (CMDB-09) the stored answer reports as
``no_match`` instead, at a confidence (0.58) *below* the gate chosen below -- wrong, and accepted
anyway, because ``no_match`` bypasses the confidence gate entirely regardless of its own confidence
(the same shape as recipe 18's ``t11-dup-auth-missed``). ``t15-sql-2016-lowconf`` is a real match
(CMDB-01) the stored answer names as the wrong sibling (CMDB-02) at a low confidence: wrong, and
caught (sent to review). ``v11-sql-2022-lowconf``, ``t16-rhel-lowconf`` and ``t17-photoshop-lowconf``
are each correct but held back by a confidence below the gate -- the coverage cost of excluding the
two wrong-but-confident answers above. ``v20-rhel-workstation`` and ``t20-rhel-workstation`` exercise
the instructions' "a different edition ... is not a match" clause directly: CMDB-08 and CMDB-16
are the same vendor, product and major version, differing only by edition (Server vs. Workstation),
so getting either of these two right needs an edition read, not just a version or product read.

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


def _fields(asset_id: str, vendor: str, product: str, version: str, edition: str) -> dict[str, str]:
    return {
        "asset_id": asset_id,
        "vendor": vendor,
        "product": product,
        "version": version,
        "edition": edition,
    }


# (id, split, fields, gold label or None for demo, {option: probability} or None for a
# zero-candidate asset that is never asked -- see candidates_for/answers_for below)
ROWS = [
    # --- validation: 20 examples, one wrong on purpose, two held back by low confidence -------
    ("v01-acrobat", "validation", _fields(
        "AST-1001", "Adobe Systems Incorporated", "Acrobat", "11.0.23", "Professional"),
     "CMDB-04", {"CMDB-04": 0.86}),
    ("v02-photoshop", "validation", _fields(
        "AST-1002", "Adobe Inc.", "Photoshop", "25.1", "Standard"),
     "CMDB-05", {"CMDB-05": 0.84}),
    ("v03-oracle-db", "validation", _fields(
        "AST-1003", "Oracle Corp", "Database", "19.3.0.0.0 (19c)", "Enterprise Edition"),
     "CMDB-06", {"CMDB-06": 0.86}),
    ("v04-sap-ecc", "validation", _fields(
        "AST-1004", "SAP SE", "ECC", "6.0 EHP8", "Enterprise"),
     "CMDB-07", {"CMDB-07": 0.84}),
    ("v05-rhel", "validation", _fields(
        "AST-1005", "Red Hat, Inc.", "RHEL", "8.6", "Server"),
     "CMDB-08", {"CMDB-08": 0.87}),
    ("v06-jira", "validation", _fields(
        "AST-1006", "Atlassian", "Jira Software", "9.4.1", "Data Center"),
     "CMDB-09", {"CMDB-09": 0.83}),
    ("v07-sales-cloud", "validation", _fields(
        "AST-1007", "salesforce.com, inc.", "Sales Cloud", "Spring '24", "Enterprise"),
     "CMDB-10", {"CMDB-10": 0.85}),
    ("v08-java-se", "validation", _fields(
        "AST-1008", "Oracle", "Java SE", "17.0.9", "Enterprise"),
     "CMDB-11", {"CMDB-11": 0.84}),
    ("v09-sql-2016", "validation", _fields(
        "AST-1009", "MSFT", "SQL Server", "13.0.1601.5 (SQL Server 2016)", "Standard"),
     "CMDB-01", {"CMDB-01": 0.86}),
    ("v10-sql-2019", "validation", _fields(
        "AST-1010", "Microsoft Corporation", "SQL Server", "15.0.2000.5 (2019)", "Standard Edition"),
     "CMDB-02", {"CMDB-02": 0.84}),
    # Correct (CMDB-03, the shortlist's third entry -- see the module docstring), but held back
    # by a confidence below the gate chosen below: the coverage cost of excluding v13 below.
    ("v11-sql-2022-lowconf", "validation", _fields(
        "AST-1011", "Microsoft", "SQL Server", "2022 (16.0.1050.5)", "Standard"),
     "CMDB-03", {"CMDB-03": 0.30}),
    # The version Python never asks Jev to guess: no observed version at all, so this recipe's
    # policy makes the gold label no_match, and the stored answer agrees (no_match is never
    # gated on confidence, so its own confidence here does not matter).
    ("v12-sql-missing-version", "validation", _fields(
        "AST-1012", "Microsoft", "SQL Server", "not reported", "Standard"),
     "no_match", {"no_match": 0.55}),
    # The validation set's own wrong answer (see the module docstring): Acrobat Reader is a
    # different, free product from the paid Acrobat the catalog holds, but is retrieved as a
    # candidate because the wording overlaps; the stored answer confidently (but wrongly) links
    # it there anyway, at a confidence below the gate the next section freezes.
    ("v13-lookalike-wrong", "validation", _fields(
        "AST-1013", "Adobe", "Acrobat Reader DC", "2023.008.20470", "Standard"),
     "no_match", {"CMDB-04": 0.40}),
    ("v14-zero-candidate", "validation", _fields(
        "AST-1014", "Zoom Video Communications", "Zoom Workplace", "6.1.0", "Business"),
     "no_match", None),
    ("v15-zero-candidate", "validation", _fields(
        "AST-1015", "AgileBits", "1Password Business", "8.10.25", "Business"),
     "no_match", None),
    # A near duplicate of CMDB-01/02/03's own wording (shares "microsoft" only): retrieved
    # alongside all three SQL Server records, correctly read as no_match.
    ("v16-teams-decoy", "validation", _fields(
        "AST-1016", "Microsoft", "Teams", "1.7.00.1061", "Business"),
     "no_match", {"no_match": 0.80}),
    ("v17-openshift", "validation", _fields(
        "AST-1017", "Red Hat", "OpenShift", "4.14", "Server"),
     "CMDB-13", {"CMDB-13": 0.84}),
    ("v18-confluence", "validation", _fields(
        "AST-1018", "Atlassian", "Confluence", "8.5.4", "Data Center"),
     "CMDB-14", {"CMDB-14": 0.85}),
    ("v19-service-cloud", "validation", _fields(
        "AST-1019", "Salesforce", "Service Cloud", "2024", "Enterprise"),
     "CMDB-15", {"CMDB-15": 0.83}),
    # CMDB-08 and CMDB-16 are the same vendor, product and major version, differing only by
    # edition (Server vs. Workstation); gold is CMDB-16, the shortlist's second entry (tied with
    # CMDB-08 in retrieval, tie-broken by id) -- getting this right needs an edition read, the
    # instructions' "a different edition ... is not a match" clause, which no other fixture in
    # this recipe exercises.
    ("v20-rhel-workstation", "validation", _fields(
        "AST-1020", "Red Hat", "Enterprise Linux", "8.6", "Workstation"),
     "CMDB-16", {"CMDB-16": 0.85}),
    # --- test: 20 examples, three wrong in three different ways ------------------------------
    ("t01-acrobat", "test", _fields(
        "AST-2001", "Adobe", "Acrobat", "v11.0.09 Continuous", "Pro (2023 release)"),
     "CMDB-04", {"CMDB-04": 0.87}),
    ("t02-photoshop", "test", _fields(
        "AST-2002", "Adobe", "Photoshop", "25.9.1", "Std"),
     "CMDB-05", {"CMDB-05": 0.85}),
    ("t03-oracle-db", "test", _fields(
        "AST-2003", "Oracle Corporation", "Database", "19c Release 21", "Enterprise"),
     "CMDB-06", {"CMDB-06": 0.84}),
    ("t04-sap-ecc", "test", _fields(
        "AST-2004", "SAP", "ERP Central Component", "6.0 EHP7", "Enterprise Edition"),
     "CMDB-07", {"CMDB-07": 0.85}),
    ("t05-rhel", "test", _fields(
        "AST-2005", "Red Hat Inc", "Enterprise Linux", "8.4", "Server Edition"),
     "CMDB-08", {"CMDB-08": 0.84}),
    ("t06-sales-cloud", "test", _fields(
        "AST-2006", "SFDC", "Sales Cloud", "Winter '24", "Enterprise Edition"),
     "CMDB-10", {"CMDB-10": 0.86}),
    ("t07-s4hana", "test", _fields(
        "AST-2007", "SAP SE", "S4HANA", "2023 FPS01", "Enterprise"),
     "CMDB-12", {"CMDB-12": 0.85}),
    ("t08-sql-2022", "test", _fields(
        "AST-2008", "Microsoft", "SQL Server", "16.0.1000.6, SQL 2022", "Standard"),
     "CMDB-03", {"CMDB-03": 0.88}),
    ("t09-sql-2019", "test", _fields(
        "AST-2009", "MS Corp", "SQL Server", "SQL2019 CU18 (15.0.4261.1)", "Standard"),
     "CMDB-02", {"CMDB-02": 0.85}),
    # The one false link this recipe's fixtures contain (see the module docstring): no version
    # is reported, so the gold label is no_match under this recipe's policy, but the stored
    # answer confidently names CMDB-03 anyway, at a confidence that clears the gate below.
    ("t10-sql-missing-version-wrong", "test", _fields(
        "AST-2010", "Microsoft", "SQL Server", "not reported", "Standard Edition"),
     "no_match", {"CMDB-03": 0.85}),
    # The same look-alike trap as v13, worded differently, read correctly this time: the
    # contrast shows the same trap landing both ways.
    ("t11-lookalike-correct", "test", _fields(
        "AST-2011", "Adobe Inc.", "Acrobat Reader", "2024.001.00000", "Reader"),
     "no_match", {"no_match": 0.75}),
    ("t12-zero-candidate", "test", _fields(
        "AST-2012", "Docker Inc", "Docker Desktop", "4.32", "Business"),
     "no_match", None),
    # A near duplicate of all three SQL Server records plus CMDB-08 and CMDB-16's own wording
    # ("enterprise", "server"): retrieved alongside several real candidates (candidates_for
    # below reports exactly how many), correctly read as no_match.
    ("t13-github-decoy", "test", _fields(
        "AST-2013", "GitHub", "GitHub Enterprise Server", "3.11.0", "Enterprise"),
     "no_match", {"no_match": 0.78}),
    # A real match (CMDB-09), but the stored answer confidently calls it no_match instead:
    # wrong, and no_match is never checked by any confidence gate at all, so this missed match
    # is not caught by anything (the same shape as recipe 18's t11-dup-auth-missed).
    ("t14-jira-missed", "test", _fields(
        "AST-2014", "Atlassian", "Jira Software", "9.12.0", "Data Center"),
     "CMDB-09", {"no_match": 0.72}),
    # A real match (CMDB-01, 2016), but the stored answer names the wrong sibling (CMDB-02,
    # 2019) at a low confidence: wrong, and caught (sent to review).
    ("t15-sql-2016-lowconf", "test", _fields(
        "AST-2015", "Microsoft", "SQL Server", "13.0.6300.2 (2016 SP3)", "Standard"),
     "CMDB-01", {"CMDB-02": 0.30}),
    ("t16-rhel-lowconf", "test", _fields(
        "AST-2016", "Red Hat", "Enterprise Linux", "8.9", "Server"),
     "CMDB-08", {"CMDB-08": 0.38}),
    ("t17-photoshop-lowconf", "test", _fields(
        "AST-2017", "Adobe", "Photoshop", "25.12", "Standard Edition"),
     "CMDB-05", {"CMDB-05": 0.35}),
    ("t18-zero-candidate", "test", _fields(
        "AST-2018", "Notion Labs", "Notion", "2.0.44", "Team"),
     "no_match", None),
    ("t19-s4hana", "test", _fields(
        "AST-2019", "SAP", "S4HANA", "2023 FPS02", "Enterprise Edition"),
     "CMDB-12", {"CMDB-12": 0.86}),
    # The test-split twin of v20: CMDB-16 again, worded differently, exercising the same
    # edition-disqualifying clause.
    ("t20-rhel-workstation", "test", _fields(
        "AST-2020", "Red Hat Inc", "Enterprise Linux", "8.7", "Workstation Edition"),
     "CMDB-16", {"CMDB-16": 0.86}),
    # --- demo: 3 examples, shown but never scored -----------------------------------------------
    ("d01-lookalike", "demo", _fields(
        "AST-3001", "Adobe", "Acrobat Reader", "2022.003.20282", "Standard"),
     None, {"no_match": 0.70}),
    ("d02-zero-candidate", "demo", _fields(
        "AST-3002", "Figma", "Figma Design", "2024.10", "Organization"),
     None, None),
    # Shown up close in the notebook as the asset whose candidate list is longest: a near
    # duplicate of all three SQL Server records plus CMDB-08 and CMDB-16's own wording, worded
    # differently from t13 above. Kept out of validation/test on purpose, so "test is reported
    # once, not peeked at here" stays literally true in the up-close section.
    ("d03-decoy-many", "demo", _fields(
        "AST-3003", "GitLab", "GitLab Enterprise Server", "16.5", "Enterprise"),
     None, {"no_match": 0.56}),
]  # fmt: skip


def candidates_for(vendor: str, product: str) -> list[str]:
    """The shortlist for this asset's vendor/product, matching ``helpers.build_questions``."""
    return helpers.shortlist(vendor, product)


def answers_for(spec: dict[str, float], provenance: Provenance) -> dict:
    """{question name: answer} for one row: a single Choice answer over that asset's own
    shortlist plus no_match."""
    return {"match": ChoiceAnswer.from_probabilities(spec, provenance)}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded.

    A row whose ``spec`` is ``None`` retrieves no candidate at all (``candidates_for`` returns an
    empty list): no request is ever made for it, so its ``replay_keys`` is empty, matching
    docs/fixtures.md's "Replay and scripted recipes" (``replay_keys`` may be empty for an
    example).
    """
    inputs, labels = [], []
    for ident, split, fields, label, spec in rows:
        candidates = candidates_for(fields["vendor"], fields["product"])
        if spec is None:
            if candidates:
                raise ValueError(f"{ident}: expected a zero-candidate asset, got {candidates}")
            keys = []
        else:
            if not candidates:
                raise ValueError(f"{ident}: expected real candidates, retrieval returned none")
            questions = helpers.build_questions(candidates)
            keys = [replay_key(helpers.build_state(fields), questions)]
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": keys})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response. A row with no candidates (``spec`` is
    ``None``) contributes no entry at all."""
    responses = {}
    for _ident, _split, fields, _label, spec in rows:
        if spec is None:
            continue
        candidates = candidates_for(fields["vendor"], fields["product"])
        questions = helpers.build_questions(candidates)
        key = replay_key(helpers.build_state(fields), questions)
        full_spec = dist(candidates, **spec)
        answers = answers_for(full_spec, Provenance.synthetic())
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
