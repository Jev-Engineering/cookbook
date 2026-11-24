"""Tests for recipe 62's helpers. They load the helpers by file path."""

import ast
import inspect
import itertools
import json
from collections import Counter
from pathlib import Path

import pytest

from jev_cookbook import NoulAnswer, Provenance, ScoreAnswer, get_backend, load_helpers, replay_key
from jev_cookbook import synthetic_images as si
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

CATEGORIES = ("missing_element", "misalignment", "clipping", "overlap")
SEVERITIES = (
    "missing_element_severity",
    "misalignment_severity",
    "clipping_severity",
    "overlap_severity",
)


def noul(probability):
    return NoulAnswer(probability, Provenance.synthetic())


def score(*weights):
    total = 0
    for weight in weights:
        total += weight
    return ScoreAnswer.from_probabilities(
        [weight / total for weight in weights], list(helpers.LEVELS), Provenance.synthetic()
    )


LOW = score(80, 10, 5, 5)  # most probable level 0, position about 0.10, confidence about 0.65
MAJOR_SURE = score(4, 6, 80, 10)  # most probable level 2, position about 0.65, confidence 0.80
MAJOR_UNSURE = score(4, 40, 44, 12)  # most probable level 2, position about 0.55, confidence 0.4


def answers(**overrides):
    """Eight answers: every Noul a clear no and every Score low, then ``overrides``."""
    result = {name: noul(0.05) for name in CATEGORIES}
    result.update({name: LOW for name in SEVERITIES})
    result.update(overrides)
    return result


POLICY = helpers.Policy(dict.fromkeys(CATEGORIES, 0.5), 0.5, 0.6)


def all_results(split):
    backend = get_backend(fixtures=responses_path(RECIPE), images=True)
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    chosen = [e for e in load_inputs(RECIPE) if e.split == split]
    results = []
    for example in chosen:
        state, assets = helpers.build_request(example.fields)
        results.append(backend.decide(state, questions, assets=assets))
    return chosen, results, [labels[e.id] for e in chosen]


def frozen_policy():
    _examples, results, golds = all_results("validation")
    thresholds = helpers.choose_noul_thresholds(results, golds)
    cutoff = helpers.choose_severity_cutoff(results, golds)
    gate, _candidates = helpers.choose_gate(results, golds, thresholds, cutoff, target_accuracy=1.0)
    return helpers.Policy(thresholds, cutoff, gate)


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == [*CATEGORIES, *SEVERITIES]
    kinds = [question.to_dict()["type"] for question in questions.values()]
    assert kinds == ["noul"] * 4 + ["score"] * 4
    assert questions["missing_element"].instructions.endswith(
        "Comparing the two, an element that is visible in `before` is not visible anywhere in "
        "`after`."
    )
    assert "A different colour on its own" in questions["overlap"].instructions
    assert questions["clipping_severity"].criteria == [
        "Visible only on close comparison: every piece of text is still present and readable, "
        "and every control looks and works as it did.",
        "Plainly visible and looks wrong, but nothing a person needs is lost: all text can still "
        "be read and every control can still be found and used.",
        "Some text a person reads is gone, cut off, covered or placed beside the wrong field, so "
        "part of the page can no longer be read correctly, while the page's main action can "
        "still be found and used.",
        "The page's main action is gone, covered or cannot be used, so a person cannot complete "
        "what the page is for.",
    ]
    assert helpers.LEVEL_NAMES == ("cosmetic", "minor", "major", "blocking")
    assert helpers.MAJOR == 2


def test_no_proposition_is_worded_negatively():
    # A high noul must mean the change is there: no "free of", "no", "not changed" proposition.
    for category in CATEGORIES:
        statement = helpers.DESCRIPTIONS[category]
        assert "free of" not in statement
        assert not statement.startswith(("no ", "nothing", "not "))


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # One request per pair: the eight questions are independent, so they share it. The key
    # covers the images' bytes, so a changed picture fails here.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        state, assets = helpers.build_request(example.fields)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)


def test_every_scene_can_be_redrawn_from_its_manifest_entry():
    # A shared scene is rebuilt from the generator and parameters its entry records and compared
    # with the committed file. A function in build_fixtures.py is covered by the emitted test
    # that reruns that script and compares every fixture, manifest and image byte. A different
    # script requires extending that regeneration test and this coverage assertion together.
    manifest = json.loads((RECIPE / "assets-manifest.json").read_text("utf-8"))
    assert manifest["assets"], "the image recipe must have manifest entries"
    for entry in manifest["assets"]:
        module, separator, function = entry["generator"].partition(":")
        assert separator and function, "each entry must name a generator function"
        if module == "jev_cookbook.synthetic_images":
            assert si.check_reproducible(RECIPE, entry) in ("unchanged", "kept-committed-bytes")
        else:
            assert module == "build_fixtures.py", "extend the regeneration test for this script"
            script = RECIPE / module
            assert script.is_file(), "the declared generator script must exist"
            definitions = ast.parse(script.read_text("utf-8")).body
            assert any(
                isinstance(node, ast.FunctionDef) and node.name == function for node in definitions
            )
            coverage = RECIPE / "tests" / "test_build_fixtures.py"
            assert coverage.is_file(), "custom scenes need the fixture/image regeneration test"
            checks = ast.parse(coverage.read_text("utf-8")).body
            assert any(
                isinstance(node, ast.FunctionDef)
                and node.name == "test_the_generator_reproduces_the_committed_fixtures_and_images"
                for node in checks
            )


def test_an_unchanged_pair_sends_one_distinct_image_twice():
    fields = {"pair": "P-1", "before": "assets/before-a.png", "after": "assets/after-v01.png"}
    state, assets = helpers.build_request(fields)
    assert state["before"] == state["after"]
    assert len(assets) == 1
    changed = {"pair": "P-2", "before": "assets/before-a.png", "after": "assets/after-v03.png"}
    state, assets = helpers.build_request(changed)
    assert state["before"] != state["after"] and len(assets) == 2


def test_the_gold_label_is_read_from_the_changes_drawn():
    assert helpers.gold_label(["save_missing", "field_nudged"]) == {
        "missing_element": True,
        "misalignment": True,
        "clipping": False,
        "overlap": False,
        "severity": {"missing_element": 3, "misalignment": 0},
    }
    # A benign look-alike changes pixels but is none of the categories.
    assert helpers.gold_label(["accent_colour", "timestamp_updated"]) == {
        "missing_element": False,
        "misalignment": False,
        "clipping": False,
        "overlap": False,
        "severity": {},
    }
    with pytest.raises(ValueError, match="is not one of"):
        helpers.gold_label(["button_wobble"])
    with pytest.raises(ValueError, match="two clipping changes"):
        helpers.gold_label(["help_clipped_edge", "help_clipped_half"])


def test_the_boundary_cut_is_under_half_the_rows_and_labelled_minor():
    # The help line is drawn at scale 2, so it is 14 pixel rows tall. A cut of fewer than half of
    # them leaves it readable (minor); the boundary case cuts 6.
    assert si.GLYPH_HEIGHT * 2 == 14
    assert helpers.CHANGES["help_clipped_boundary"] == ("clipping", 1)
    assert helpers.CHANGES["help_clipped_half"] == ("clipping", 2)


def test_the_gold_verdict_fails_at_major_and_above():
    assert helpers.gold_verdict({"severity": {}}) == "pass"
    assert helpers.gold_verdict({"severity": {"clipping": 1, "overlap": 0}}) == "pass"
    assert helpers.gold_verdict({"severity": {"clipping": 2}}) == "fail"
    assert helpers.gold_verdict({"severity": {"overlap": 3, "clipping": 1}}) == "fail"


def test_a_tag_is_decisive_only_when_no_other_change_fails_the_pair():
    assert helpers.decisive_categories(helpers.gold_label(["help_missing"])) == ["missing_element"]
    assert helpers.decisive_categories(helpers.gold_label(["avatar_missing"])) == []
    both = helpers.gold_label(["help_missing", "labels_shifted"])
    assert helpers.decisive_categories(both) == []
    mixed = helpers.gold_label(["field_nudged", "help_clipped_half"])
    assert helpers.decisive_categories(mixed) == ["clipping"]


def test_nothing_detected_is_a_pass():
    verdict = helpers.decide("P-1", answers(), POLICY)
    assert (verdict.kind, verdict.reason, verdict.changes) == (
        "pass",
        "no predefined change detected",
        (),
    )


def test_a_severity_is_ignored_when_its_category_is_not_detected():
    # A blocking severity under a Noul below its threshold is never read.
    verdict = helpers.decide("P-1", answers(overlap_severity=score(2, 2, 6, 90)), POLICY)
    assert verdict.kind == "pass"


def test_a_confident_change_at_or_above_the_cutoff_fails_whatever_else_is_unsure():
    result = answers(
        clipping=noul(0.9),
        clipping_severity=MAJOR_SURE,
        overlap=noul(0.9),
        overlap_severity=MAJOR_UNSURE,
    )
    verdict = helpers.decide("P-1", result, POLICY)
    assert (verdict.kind, verdict.reason) == (
        "fail",
        "a confident change at or above the severity cutoff",
    )
    assert [c.category for c in verdict.changes] == ["clipping", "overlap"]


def test_an_unsure_detected_change_is_a_review_never_a_pass_or_a_fail():
    verdict = helpers.decide(
        "P-1", answers(clipping=noul(0.9), clipping_severity=MAJOR_UNSURE), POLICY
    )
    assert (verdict.kind, verdict.reason) == ("review", "confidence below the threshold")
    assert verdict.changes[0].level == 2 and not verdict.changes[0].confident


def test_confident_changes_below_the_cutoff_pass():
    verdict = helpers.decide("P-1", answers(misalignment=noul(0.7)), POLICY)
    assert (verdict.kind, verdict.reason) == (
        "pass",
        "every detected change is below the severity cutoff",
    )


def test_with_no_validated_gate_every_detected_change_is_a_review():
    policy = helpers.Policy(dict.fromkeys(CATEGORIES, 0.5), 0.5, None)
    verdict = helpers.decide(
        "P-1", answers(clipping=noul(0.9), clipping_severity=MAJOR_SURE), policy
    )
    assert (verdict.kind, verdict.reason) == ("review", "no validated threshold")


def test_a_setting_outside_zero_to_one_is_an_error():
    with pytest.raises(ValueError, match="gate"):
        helpers.decide("P-1", answers(), helpers.Policy(dict.fromkeys(CATEGORIES, 0.5), 0.5, 1.5))
    with pytest.raises(ValueError, match="cutoff"):
        helpers.decide("P-1", answers(), helpers.Policy(dict.fromkeys(CATEGORIES, 0.5), -0.1, 0.5))


def test_the_rule_holds_over_a_grid_of_answers():
    # Every combination of three probabilities of yes per category and three severities per
    # category for two categories (the other two held at a clear no): the verdict follows the
    # rule whatever the answers are.
    severities = (LOW, MAJOR_SURE, MAJOR_UNSURE)
    for p_clip, p_over, s_clip, s_over in itertools.product(
        (0.1, 0.5, 0.9), (0.1, 0.5, 0.9), severities, severities
    ):
        result = answers(
            clipping=noul(p_clip),
            overlap=noul(p_over),
            clipping_severity=s_clip,
            overlap_severity=s_over,
        )
        verdict = helpers.decide("grid", result, POLICY)
        detected = [(p, s) for p, s in ((p_clip, s_clip), (p_over, s_over)) if p >= 0.5]
        if not detected:
            assert verdict.kind == "pass"
        elif any(s is MAJOR_SURE for _, s in detected):
            assert verdict.kind == "fail"
        elif any(s is MAJOR_UNSURE for _, s in detected):
            assert verdict.kind == "review"
        else:
            assert verdict.kind == "pass"


def test_the_gate_is_none_when_no_cutoff_reaches_the_target():
    result = answers(clipping=noul(0.9), clipping_severity=MAJOR_SURE)
    gold = helpers.gold_label(["help_clipped_edge"])  # minor, so failing it is wrong
    thresholds = dict.fromkeys(CATEGORIES, 0.5)
    assert helpers.choose_gate([result], [gold], thresholds, 0.5, target_accuracy=1.0) == (None, 1)
    assert helpers.choose_gate([answers()], [gold], thresholds, 0.5, target_accuracy=1.0) == (
        None,
        0,
    )


def test_queue_reviews_writes_only_the_reviews_of_the_test_split():
    policy = frozen_policy()
    examples, results, _golds = all_results("test")
    verdicts = [
        helpers.decide(e.fields["pair"], r, policy) for e, r in zip(examples, results, strict=True)
    ]
    queue = ReviewQueue()
    helpers.queue_reviews(queue, verdicts)
    pending = [(item.item, item.reason) for item in queue.pending()]
    assert pending == [
        (
            {"pair": "P-2013", "changes": {"missing_element": "minor", "clipping": "major"}},
            "confidence below the threshold",
        ),
        (
            {
                "pair": "P-2022",
                "changes": {
                    "missing_element": "minor",
                    "misalignment": "cosmetic",
                    "clipping": "minor",
                    "overlap": "minor",
                },
            },
            "confidence below the threshold",
        ),
    ]


def test_the_fixture_set_covers_every_combination_and_every_decisive_tag():
    labels = load_labels(RECIPE)
    examples = [e for e in load_inputs(RECIPE) if e.split in ("validation", "test")]
    combinations = Counter(helpers.truth_combination(labels[e.id]) for e in examples)
    assert len(combinations) == 16  # every truth combination of the four propositions
    for split in ("validation", "test"):
        rows = [labels[e.id] for e in examples if e.split == split]
        for category in CATEGORIES:
            assert any(r[category] for r in rows) and not all(r[category] for r in rows)
            assert any(category in helpers.decisive_categories(r) for r in rows), (split, category)


def test_the_named_hard_cases_are_in_both_scored_splits():
    rows = {}
    for example in load_inputs(RECIPE):
        if example.split in ("validation", "test"):
            rows.setdefault(example.split, []).append(example.id)
    labels = load_labels(RECIPE)
    for split, ids in rows.items():
        unchanged = [i for i in ids if helpers.truth_combination(labels[i]) == (False,) * 4]
        assert len(unchanged) >= 2, split  # the unchanged pair and a benign look-alike
        mixed = [
            i
            for i in ids
            if len(set(labels[i]["severity"].values())) >= 2
            and helpers.gold_verdict(labels[i]) == "fail"
        ]
        assert mixed, split  # two simultaneous changes of different severity


def test_stored_answers_are_not_all_right_above_the_frozen_gate():
    # Re-derive the gate on validation with the selection written out, then require a detected
    # test change on the wrong side of the cutoff at a confidence at or above it: a mistake the
    # gate lets through, which is what evaluating on test exists to catch.
    _examples, val_results, val_golds = all_results("validation")
    thresholds = helpers.choose_noul_thresholds(val_results, val_golds)
    cutoff = helpers.choose_severity_cutoff(val_results, val_golds)
    right, confidence = [], []
    for result, gold in zip(val_results, val_golds, strict=True):
        for category in CATEGORIES:
            if result[category].noul >= thresholds[category]:
                right.append(helpers.detected_change_is_right(result, gold, category, cutoff))
                confidence.append(result[f"{category}_severity"].confidence)
    gate = select_confidence_threshold(right, confidence, target_accuracy=1.0)

    examples, test_results, test_golds = all_results("test")
    wrong_and_confident = [
        (e.id, category)
        for e, result, gold in zip(examples, test_results, test_golds, strict=True)
        for category in CATEGORIES
        if result[category].noul >= thresholds[category]
        and not helpers.detected_change_is_right(result, gold, category, cutoff)
        and result[f"{category}_severity"].confidence >= gate
    ]
    assert wrong_and_confident == [("t08", "clipping")]


def test_the_selections_use_the_f1_objective_and_the_target_accuracy():
    # The value a test re-derives pins an objective only if no other objective reaches the same
    # value on this pool, so the committed sources are what pin it.
    noul_source = inspect.getsource(helpers.choose_noul_thresholds)
    assert 'objective="f1"' in noul_source
    cutoff_source = inspect.getsource(helpers.choose_severity_cutoff)
    assert 'objective="f1"' in cutoff_source
    gate_source = inspect.getsource(helpers.choose_gate)
    assert "target_accuracy=target_accuracy" in gate_source
    assert "min_coverage" not in gate_source
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source


def _help_line_ink_rows(path):
    """How many pixel rows of the help line's band (y 300 to 313) hold any non-white pixel."""
    picture = helpers.open_image(path)
    rows = 0
    for y in range(300, 314):
        if any(picture.getpixel((x, y)) != (255, 255, 255) for x in range(44, 400)):
            rows += 1
    return rows


def test_the_clipping_cuts_remove_2_6_and_10_of_the_14_rows():
    # The quantities the notebook's hard-case prose states, read from the committed pictures:
    # the help line is 14 rows tall, and the boundary cut removes 6, leaving 8.
    assert _help_line_ink_rows("assets/before-a.png") == 14
    assert _help_line_ink_rows("assets/after-v07.png") == 14 - 2  # help_clipped_edge
    assert _help_line_ink_rows("assets/after-v09.png") == 14 - 6  # help_clipped_boundary
    assert _help_line_ink_rows("assets/after-v08.png") == 14 - 10  # help_clipped_half


def test_the_next_steps_exercise_turns_both_test_reviews_into_verdicts():
    # Next steps: target_accuracy 1.0 -> 0.95 lowers the gate, the two test reviews become
    # verdicts, coverage rises and so does the risk among delivered verdicts (t22 is failed
    # against a gold pass).
    _examples, val_results, val_golds = all_results("validation")
    thresholds = helpers.choose_noul_thresholds(val_results, val_golds)
    cutoff = helpers.choose_severity_cutoff(val_results, val_golds)
    examples, test_results, test_golds = all_results("test")

    def run(target):
        gate, _n = helpers.choose_gate(
            val_results, val_golds, thresholds, cutoff, target_accuracy=target
        )
        policy = helpers.Policy(thresholds, cutoff, gate)
        verdicts = {
            e.id: helpers.decide(e.fields["pair"], r, policy).kind
            for e, r in zip(examples, test_results, strict=True)
        }
        delivered = [i for i, kind in verdicts.items() if kind != "review"]
        gold = {e.id: helpers.gold_verdict(g) for e, g in zip(examples, test_golds, strict=True)}
        wrong = sum(verdicts[i] != gold[i] for i in delivered)
        return gate, verdicts, len(delivered), wrong

    gate_1, verdicts_1, delivered_1, wrong_1 = run(1.0)
    gate_95, verdicts_95, delivered_95, wrong_95 = run(0.95)
    assert gate_95 < gate_1
    assert [i for i, kind in verdicts_1.items() if kind == "review"] == ["t13", "t22"]
    assert (verdicts_95["t13"], verdicts_95["t22"]) == ("fail", "fail")
    assert delivered_95 > delivered_1
    assert wrong_95 / delivered_95 > wrong_1 / delivered_1
