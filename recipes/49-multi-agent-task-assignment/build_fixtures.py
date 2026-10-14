"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 49.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every row is one (agent, subtask) pair: one suitability ``Score`` request. The stored answers
are deliberately imperfect -- some wrong, one deliberately adversarial (an agent with none of
the required skill, written up so confidently that its stored score is high anyway) -- so the
scheduler in ``helpers.py`` has real hard cases to filter, and the evaluation has real wrong
answers to find. See docs/fixtures.md and recipes/_template/build_fixtures.py.

Every probability tuple below is a hand-typed literal, never computed with ``sum()`` or ``**``:
both are not guaranteed bit-identical across the Python versions this repository tests (3.10 and
3.14), and this script's output is asserted byte-identical to the committed fixtures on both.

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

from jev_cookbook import DecisionResult, Provenance, load_helpers, replay_key
from jev_cookbook.answers import ScoreAnswer

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# Stored-probability shapes over the five suitability levels (0..4), hand-typed so each tuple's
# own digits sum to 1.00 -- no runtime float arithmetic builds them. SHARP is a confident peak;
# MEDIUM a moderate one; ADVERSARIAL is a single, extreme-confidence peak used once, for the one
# pair where an incapable agent's stored answer is written to look better than any capable
# agent's, specifically to test whether the capability filter holds regardless.
SHARP = {
    0: (0.90, 0.04, 0.03, 0.02, 0.01),
    1: (0.03, 0.90, 0.04, 0.02, 0.01),
    2: (0.02, 0.03, 0.90, 0.03, 0.02),
    3: (0.01, 0.02, 0.04, 0.90, 0.03),
    4: (0.01, 0.02, 0.03, 0.04, 0.90),
}
MEDIUM = {
    0: (0.70, 0.15, 0.08, 0.04, 0.03),
    1: (0.10, 0.65, 0.13, 0.07, 0.05),
    2: (0.06, 0.12, 0.60, 0.14, 0.08),
    3: (0.05, 0.07, 0.13, 0.65, 0.10),
    4: (0.03, 0.04, 0.08, 0.15, 0.70),
}
ADVERSARIAL = {4: (0.00, 0.00, 0.01, 0.01, 0.98)}
SHAPES = {"SHARP": SHARP, "MEDIUM": MEDIUM, "ADVERSARIAL": ADVERSARIAL}

_REGISTRY = {
    "validation": (helpers.VALIDATION_AGENTS, helpers.VALIDATION_SUBTASKS),
    "test": (helpers.TEST_AGENTS, helpers.TEST_SUBTASKS),
    "demo": (helpers.VALIDATION_AGENTS, (helpers.DEMO_SUBTASK,)),
}


def _fields(split: str, agent_id: str, subtask_id: str) -> dict:
    agents, subtasks = _REGISTRY[split]
    agent = helpers.agents_by_id(agents)[agent_id]
    subtask = helpers.subtasks_by_id(subtasks)[subtask_id]
    return {
        "scenario": split,
        "agent_id": agent.id,
        "subtask_id": subtask.id,
        "agent_profile": agent.profile,
        "subtask_description": subtask.description,
    }


# (id, split, agent_id, subtask_id, gold suitability level or None for a demo row, shape, peak)
ROWS = [
    # -- validation: "sprint-1" (6 agents x 6 subtasks = 36 requests) --------------------------
    ("v-nova-s1-api-schema", "validation", "nova", "s1-api-schema", 4, "SHARP", 4),
    ("v-iris-s1-api-schema", "validation", "iris", "s1-api-schema", 2, "MEDIUM", 2),
    ("v-orin-s1-api-schema", "validation", "orin", "s1-api-schema", 1, "SHARP", 1),
    ("v-wren-s1-api-schema", "validation", "wren", "s1-api-schema", 0, "SHARP", 0),
    ("v-sable-s1-api-schema", "validation", "sable", "s1-api-schema", 0, "SHARP", 0),
    ("v-zephyr-s1-api-schema", "validation", "zephyr", "s1-api-schema", 3, "MEDIUM", 3),
    ("v-nova-s2-api-implementation", "validation", "nova", "s2-api-implementation", 3, "MEDIUM", 3),
    ("v-iris-s2-api-implementation", "validation", "iris", "s2-api-implementation", 4, "MEDIUM", 4),
    ("v-orin-s2-api-implementation", "validation", "orin", "s2-api-implementation", 2, "SHARP", 4),
    (
        "v-wren-s2-api-implementation",
        "validation",
        "wren",
        "s2-api-implementation",
        1,
        "ADVERSARIAL",
        4,
    ),
    (
        "v-sable-s2-api-implementation",
        "validation",
        "sable",
        "s2-api-implementation",
        0,
        "SHARP",
        0,
    ),
    (
        "v-zephyr-s2-api-implementation",
        "validation",
        "zephyr",
        "s2-api-implementation",
        2,
        "SHARP",
        2,
    ),
    ("v-nova-s3-release-notes", "validation", "nova", "s3-release-notes", 0, "SHARP", 0),
    ("v-iris-s3-release-notes", "validation", "iris", "s3-release-notes", 0, "SHARP", 0),
    ("v-orin-s3-release-notes", "validation", "orin", "s3-release-notes", 0, "SHARP", 0),
    ("v-wren-s3-release-notes", "validation", "wren", "s3-release-notes", 4, "SHARP", 4),
    ("v-sable-s3-release-notes", "validation", "sable", "s3-release-notes", 1, "SHARP", 1),
    ("v-zephyr-s3-release-notes", "validation", "zephyr", "s3-release-notes", 3, "MEDIUM", 3),
    ("v-nova-s4-onboarding-guide", "validation", "nova", "s4-onboarding-guide", 0, "SHARP", 0),
    ("v-iris-s4-onboarding-guide", "validation", "iris", "s4-onboarding-guide", 0, "SHARP", 0),
    ("v-orin-s4-onboarding-guide", "validation", "orin", "s4-onboarding-guide", 0, "SHARP", 0),
    ("v-wren-s4-onboarding-guide", "validation", "wren", "s4-onboarding-guide", 3, "MEDIUM", 3),
    ("v-sable-s4-onboarding-guide", "validation", "sable", "s4-onboarding-guide", 2, "MEDIUM", 2),
    ("v-zephyr-s4-onboarding-guide", "validation", "zephyr", "s4-onboarding-guide", 4, "MEDIUM", 4),
    ("v-nova-s5-perf-tuning", "validation", "nova", "s5-perf-tuning", 2, "SHARP", 2),
    ("v-iris-s5-perf-tuning", "validation", "iris", "s5-perf-tuning", 3, "SHARP", 3),
    ("v-orin-s5-perf-tuning", "validation", "orin", "s5-perf-tuning", 1, "SHARP", 1),
    ("v-wren-s5-perf-tuning", "validation", "wren", "s5-perf-tuning", 0, "SHARP", 0),
    ("v-sable-s5-perf-tuning", "validation", "sable", "s5-perf-tuning", 0, "SHARP", 0),
    ("v-zephyr-s5-perf-tuning", "validation", "zephyr", "s5-perf-tuning", 4, "SHARP", 4),
    ("v-nova-s6-load-test", "validation", "nova", "s6-load-test", 4, "SHARP", 4),
    ("v-iris-s6-load-test", "validation", "iris", "s6-load-test", 3, "MEDIUM", 3),
    ("v-orin-s6-load-test", "validation", "orin", "s6-load-test", 2, "SHARP", 2),
    ("v-wren-s6-load-test", "validation", "wren", "s6-load-test", 0, "SHARP", 0),
    ("v-sable-s6-load-test", "validation", "sable", "s6-load-test", 0, "SHARP", 0),
    ("v-zephyr-s6-load-test", "validation", "zephyr", "s6-load-test", 1, "SHARP", 1),
    # -- test: "sprint-2" (6 agents x 6 subtasks = 36 requests) --------------------------------
    ("t-cora-u1-db-migration", "test", "cora", "u1-db-migration", 4, "SHARP", 4),
    ("t-juno-u1-db-migration", "test", "juno", "u1-db-migration", 3, "MEDIUM", 3),
    ("t-milo-u1-db-migration", "test", "milo", "u1-db-migration", 1, "SHARP", 1),
    ("t-astra-u1-db-migration", "test", "astra", "u1-db-migration", 0, "SHARP", 0),
    ("t-reed-u1-db-migration", "test", "reed", "u1-db-migration", 0, "SHARP", 0),
    ("t-pike-u1-db-migration", "test", "pike", "u1-db-migration", 2, "MEDIUM", 2),
    ("t-cora-u2-service-integration", "test", "cora", "u2-service-integration", 2, "SHARP", 2),
    ("t-juno-u2-service-integration", "test", "juno", "u2-service-integration", 4, "SHARP", 4),
    ("t-milo-u2-service-integration", "test", "milo", "u2-service-integration", 2, "SHARP", 2),
    ("t-astra-u2-service-integration", "test", "astra", "u2-service-integration", 0, "SHARP", 0),
    ("t-reed-u2-service-integration", "test", "reed", "u2-service-integration", 0, "SHARP", 0),
    ("t-pike-u2-service-integration", "test", "pike", "u2-service-integration", 3, "MEDIUM", 3),
    ("t-cora-u3-metrics-dashboard", "test", "cora", "u3-metrics-dashboard", 1, "SHARP", 1),
    ("t-juno-u3-metrics-dashboard", "test", "juno", "u3-metrics-dashboard", 1, "SHARP", 1),
    ("t-milo-u3-metrics-dashboard", "test", "milo", "u3-metrics-dashboard", 2, "SHARP", 4),
    ("t-astra-u3-metrics-dashboard", "test", "astra", "u3-metrics-dashboard", 0, "SHARP", 0),
    ("t-reed-u3-metrics-dashboard", "test", "reed", "u3-metrics-dashboard", 0, "SHARP", 0),
    ("t-pike-u3-metrics-dashboard", "test", "pike", "u3-metrics-dashboard", 4, "MEDIUM", 4),
    ("t-cora-u4-user-guide", "test", "cora", "u4-user-guide", 0, "SHARP", 0),
    ("t-juno-u4-user-guide", "test", "juno", "u4-user-guide", 0, "SHARP", 0),
    ("t-milo-u4-user-guide", "test", "milo", "u4-user-guide", 0, "SHARP", 0),
    ("t-astra-u4-user-guide", "test", "astra", "u4-user-guide", 4, "SHARP", 4),
    ("t-reed-u4-user-guide", "test", "reed", "u4-user-guide", 1, "SHARP", 1),
    ("t-pike-u4-user-guide", "test", "pike", "u4-user-guide", 3, "MEDIUM", 3),
    ("t-cora-u5-faq-update", "test", "cora", "u5-faq-update", 0, "SHARP", 0),
    ("t-juno-u5-faq-update", "test", "juno", "u5-faq-update", 0, "SHARP", 0),
    ("t-milo-u5-faq-update", "test", "milo", "u5-faq-update", 0, "SHARP", 0),
    ("t-astra-u5-faq-update", "test", "astra", "u5-faq-update", 0, "SHARP", 0),
    ("t-reed-u5-faq-update", "test", "reed", "u5-faq-update", 2, "MEDIUM", 2),
    ("t-pike-u5-faq-update", "test", "pike", "u5-faq-update", 4, "SHARP", 4),
    ("t-cora-u6-launch-checklist", "test", "cora", "u6-launch-checklist", 0, "SHARP", 0),
    ("t-juno-u6-launch-checklist", "test", "juno", "u6-launch-checklist", 0, "SHARP", 0),
    ("t-milo-u6-launch-checklist", "test", "milo", "u6-launch-checklist", 0, "SHARP", 0),
    ("t-astra-u6-launch-checklist", "test", "astra", "u6-launch-checklist", 3, "SHARP", 3),
    ("t-reed-u6-launch-checklist", "test", "reed", "u6-launch-checklist", 2, "SHARP", 2),
    ("t-pike-u6-launch-checklist", "test", "pike", "u6-launch-checklist", 4, "SHARP", 4),
    # -- demo: a subtask nobody is capable of (2 requests, unscored) ---------------------------
    ("d-nova-security-review", "demo", "nova", "d1-security-review", None, "SHARP", 3),
    ("d-zephyr-security-review", "demo", "zephyr", "d1-security-review", None, "MEDIUM", 2),
]


def answers_for(spec, provenance: Provenance) -> dict:
    """``{"suitability": ScoreAnswer}`` for one row's ``(shape, peak)`` spec."""
    shape, peak = spec
    probabilities = SHAPES[shape][peak]
    answer = ScoreAnswer.from_probabilities(
        probabilities, list(helpers.SUITABILITY_LEVELS), provenance
    )
    return {"suitability": answer}


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    inputs, labels = [], []
    for ident, split, agent_id, subtask_id, label, _shape, _peak in rows:
        fields = _fields(split, agent_id, subtask_id)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
    return inputs, labels


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    responses = {}
    for _ident, split, agent_id, subtask_id, _label, shape, peak in rows:
        fields = _fields(split, agent_id, subtask_id)
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        answers = answers_for((shape, peak), Provenance.synthetic())
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
