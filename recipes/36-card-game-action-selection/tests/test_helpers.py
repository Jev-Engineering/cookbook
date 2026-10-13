"""Tests for recipe 36's helpers. They load the helpers by file path."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import ScriptedBackend, load_helpers
from jev_cookbook.evaluation import accuracy, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, select_split
from jev_cookbook.simulation import IllegalActionError

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# The same min_coverage objective the notebook freezes its confidence gate with (CONTRIBUTING.md
# lesson on pinning the objective and its keyword on both the notebook and the test side): this
# test re-derives the threshold independently of the notebook, from the committed fixtures alone,
# so the two must agree on what they are choosing for the comparison below to mean anything.
MIN_COVERAGE = 0.75


def _questions_for(fields):
    legal = helpers.legal_actions_from_hand(fields["hand"])
    return helpers.build_questions(legal)


def _decide_turn(fields):
    legal = helpers.legal_actions_from_hand(fields["hand"])
    backend = ScriptedBackend(helpers.script, helpers.SEED)
    return helpers.decide_turn(backend, fields, legal)


def _turns(split):
    examples = [e for e in select_split(load_inputs(RECIPE), split)]
    labels = load_labels(RECIPE)
    answers = [_decide_turn(e.fields) for e in examples]
    gold = [labels[e.id] for e in examples]
    return examples, answers, gold


def test_questions_are_built_by_python():
    legal = ["bid_2", "bid_5", "bid_9"]
    questions = helpers.build_questions(legal)
    assert set(questions) == {"bid"}
    assert list(questions["bid"].criteria) == legal
    with pytest.raises(ValueError):
        helpers.build_questions(["bid_1"])  # a Choice needs at least two options


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # A scripted recipe replays nothing: no example lists a key, and helpers.script must give
    # the same answer to the same request every time (a fresh backend each time, same seed).
    for example in load_inputs(RECIPE):
        assert example.replay_keys == ()
        state = helpers.build_state(example.fields)
        questions = _questions_for(example.fields)
        first = ScriptedBackend(helpers.script, helpers.SEED).decide(state, questions)
        second = ScriptedBackend(helpers.script, helpers.SEED).decide(state, questions)
        assert first.to_dict() == second.to_dict()


# --------------------------------------------------------------------------------------------
# The simulator: legal actions shrink, illegal ones are rejected, replays reproduce
# --------------------------------------------------------------------------------------------


def test_card_duel_enforces_legal_actions_and_shrinks_each_turn():
    sim = helpers.CardDuel(seed=7, n_cards=5)
    seen_sizes = []
    played = []
    while not sim.done:
        legal = sim.legal_actions()
        seen_sizes.append(len(legal))
        action = legal[0]
        played.append(int(action.split("_", 1)[1]))
        sim.step(action)
    assert seen_sizes == [5, 4, 3, 2, 1]
    assert sorted(played) == [1, 2, 3, 4, 5]  # every card bid exactly once

    sim2 = helpers.CardDuel(seed=7, n_cards=5)
    with pytest.raises(IllegalActionError):
        sim2.step("bid_999")  # never in any hand
    with pytest.raises(IllegalActionError):
        sim2.step("bid_3")
        sim2.step("bid_3")  # already played


def test_play_game_rejects_a_policy_that_names_an_illegal_action():
    def bad_policy(observation, legal):
        return "bid_999"  # never a member of any legal-action list this game offers

    with pytest.raises(IllegalActionError):
        helpers.play_game(bad_policy, seed=0)


def test_card_duel_trajectories_replay_byte_identically():
    sim = helpers.CardDuel(seed=42, n_cards=5)
    trajectory = []
    while not sim.done:
        legal = sim.legal_actions()
        action = legal[-1]
        trajectory.append(sim.step(action))
    fresh = helpers.CardDuel(seed=42, n_cards=5)
    snapshot = fresh.replay(trajectory, seed=42)  # raises on any divergence (ReplayMismatch
    # or IllegalActionError); see docs/simulation.md, "Simulator"
    assert snapshot == sim.snapshot()


# --------------------------------------------------------------------------------------------
# The rule-based baseline and the confidence gate: the rules Python enforces
# --------------------------------------------------------------------------------------------


def test_rule_based_action_prefers_the_cheapest_winning_card_else_sacrifices_the_cheapest():
    assert helpers.rule_based_action(prize=3, hand=[1, 2, 4, 5]) == "bid_4"  # cheapest winner
    assert (
        helpers.rule_based_action(prize=5, hand=[1, 2, 3, 4]) == "bid_1"
    )  # nothing wins: sacrifice


def test_gate_turn_plays_the_models_choice_when_confident_and_the_fallback_otherwise():
    confident = SimpleNamespace(choice="bid_3", confidence=0.9)
    decision = helpers.gate_turn(confident, fallback_action="bid_1", min_confidence=0.5)
    assert decision.action == "bid_3"
    assert decision.outcome == helpers.ANSWERED
    assert decision.reason is None

    unsure = SimpleNamespace(choice="bid_3", confidence=0.2)
    decision = helpers.gate_turn(unsure, fallback_action="bid_1", min_confidence=0.5)
    assert decision.action == "bid_1"  # the fallback is played, not the model's own pick
    assert decision.outcome == helpers.REVIEW
    assert decision.reason == helpers.REASON_LOW_CONFIDENCE
    assert decision.raw_choice == "bid_3"  # the model's choice is kept for reporting


def test_make_random_policy_is_seed_reproducible_and_differs_from_another_seed_key():
    legal = ["bid_1", "bid_2", "bid_3", "bid_4", "bid_5"]
    observation = {"prize": 3}
    a = helpers.make_random_policy("36-card-game-action-selection:g1")
    b = helpers.make_random_policy("36-card-game-action-selection:g1")
    c = helpers.make_random_policy("36-card-game-action-selection:g2")
    picks_a = [a(observation, legal) for _ in range(8)]
    picks_b = [b(observation, legal) for _ in range(8)]
    picks_c = [c(observation, legal) for _ in range(8)]
    assert picks_a == picks_b  # same seed key: identical sequence
    assert picks_a != picks_c  # a different seed key gives a different sequence


# --------------------------------------------------------------------------------------------
# The composed task-level outcome
# --------------------------------------------------------------------------------------------


def test_make_gated_policy_falls_back_below_the_gate_and_plays_the_model_above_it():
    # A gate set to 0.0 never withholds anything: the raw model choice is always played.
    always_answer = helpers.make_gated_policy(ScriptedBackend(helpers.script, helpers.SEED), 0.0)
    raw = helpers.make_raw_policy(ScriptedBackend(helpers.script, helpers.SEED))
    observation = {
        "turn": 0,
        "prize": 3,
        "hand": [1, 2, 4, 5],
        "cards_remaining": 4,
        "player_score": 0,
        "opponent_score": 0,
    }
    legal = helpers.legal_actions_from_hand(observation["hand"])
    assert always_answer(observation, legal) == raw(observation, legal)

    # A gate of 1.0 can never be cleared (confidence is always < 1.0 away from a single peak
    # option here, since the script always spreads some weight to the other legal actions), so
    # every decided turn falls back to the rule-based action.
    always_fallback = helpers.make_gated_policy(ScriptedBackend(helpers.script, helpers.SEED), 1.0)
    fallback = helpers.rule_based_action(observation["prize"], observation["hand"])
    assert always_fallback(observation, legal) == fallback


def test_play_game_composes_turns_into_one_task_outcome():
    # A regression pin on the composed function, not merely on the simulator underneath: this
    # is the deterministic composition CONTRIBUTING.md's Level 3 pattern asks to be tested,
    # exercised end to end under the rule-based policy on a fixed seed.
    result = helpers.play_game(helpers.rule_based_policy, seed=100)
    assert result.n_turns_checked == helpers.N_CARDS
    assert len(result.trajectory) == helpers.N_CARDS
    assert (result.winner, result.player_score, result.opponent_score) == ("player", 10, 5)


# --------------------------------------------------------------------------------------------
# Rule-11 analog: every committed gold label matches its own generating spec, not a default
# --------------------------------------------------------------------------------------------


def test_every_committed_label_matches_the_rule_based_action_from_its_own_fields():
    inputs = {e.id: e for e in load_inputs(RECIPE)}
    labels = load_labels(RECIPE)
    for example_id, label in labels.items():
        fields = inputs[example_id].fields
        expected = helpers.rule_based_action(fields["prize"], fields["hand"])
        assert label == expected, (
            f"{example_id}: committed label {label!r} does not match the rule-based action "
            f"{expected!r} its own recorded fields would produce"
        )


def test_flipping_one_gold_label_changes_measured_accuracy_on_committed_fixtures():
    # CONTRIBUTING.md lesson: every stored label must be independently consequential, proved on
    # real committed fixtures rather than a synthetic in-test row. Find a test-split turn where
    # the scripted model's own raw choice agrees with the committed gold label, then show that
    # swapping only that one label changes the measured accuracy over the whole split.
    examples, answers, gold = _turns("test")
    legal_by_index = [helpers.legal_actions_from_hand(e.fields["hand"]) for e in examples]
    target = next(
        i
        for i, (a, g, legal) in enumerate(zip(answers, gold, legal_by_index, strict=True))
        if a.choice == g and len(legal) > 1 and any(opt != g for opt in legal)
    )
    original_accuracy = accuracy(gold, [a.choice for a in answers])
    swapped_gold = list(gold)
    swapped_gold[target] = next(opt for opt in legal_by_index[target] if opt != gold[target])
    swapped_accuracy = accuracy(swapped_gold, [a.choice for a in answers])
    assert swapped_accuracy != original_accuracy


# --------------------------------------------------------------------------------------------
# Strong form: the fixture set is not so tidy that every wrong answer hides below the gate
# --------------------------------------------------------------------------------------------


def test_scripted_answers_are_not_all_right_above_the_frozen_confidence_gate():
    # Independent of the notebook's own threshold selection on purpose (docs/evaluation.md,
    # "Choose on validation, report on test"; the Wave 3 guidance on this guard's ast shape):
    # re-derives the confidence gate here, from validation turns alone, with the same
    # min_coverage objective and keyword the notebook uses, then requires at least one wrong
    # test-split turn whose confidence still clears that gate -- so this fixture set is not
    # merely "mostly right" but actually exercises the gate's risk on `test`.
    _, val_answers, val_gold = _turns("validation")
    val_correct = [a.choice == g for a, g in zip(val_answers, val_gold, strict=True)]
    val_confidence = [a.confidence for a in val_answers]
    threshold = select_confidence_threshold(val_correct, val_confidence, min_coverage=MIN_COVERAGE)

    _, test_answers, test_gold = _turns("test")
    test_correct = [a.choice == g for a, g in zip(test_answers, test_gold, strict=True)]
    test_confidence = [a.confidence for a in test_answers]
    wrong_above_gate = [
        c for ok, c in zip(test_correct, test_confidence, strict=True) if not ok and c >= threshold
    ]
    assert wrong_above_gate, (
        "every wrong test-split turn falls below the frozen confidence gate "
        f"({threshold:.4f}); the fixture set is too tidy for the gate's risk to be non-zero"
    )
