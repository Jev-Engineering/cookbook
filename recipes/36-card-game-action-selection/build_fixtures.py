"""Write fixtures/inputs.jsonl and labels.jsonl for recipe 36 (scripted).

    python build_fixtures.py        # from anywhere; it writes next to this file

A scripted recipe has nothing to replay: every example has empty ``replay_keys`` and there is no
responses.json, because ``helpers.script`` answers (see docs/simulation.md and
docs/fixtures.md, "Replay and scripted recipes").

Each example is one DECIDED turn (a turn with two or more legal actions) of one seeded game of
``helpers.CardDuel``, rolled out once by the rule-based baseline (``helpers.rule_based_action``):
the game's own sequence of prizes and the opponent's replies depend only on the seed, never on
which policy is driving the player's bids (``helpers._opponent_card`` never reads the player's
hand), so every policy this recipe evaluates sees the identical sequence of prizes and opponent
cards for a given seed, which is what makes a same-seed comparison between policies fair. The
player's own hand and running score are not identical across policies: both depend on what that
policy actually bid, and once a policy's own choice differs from the rule-based action recorded
here, its later turns can see a hand and a score this rollout never produced. The gold label
recorded for each turn is exactly the action the rule-based baseline took there, which is what
lets the notebook score a model's own per-turn choice against it later without re-deriving the
rule in two places.
"""

import json
from pathlib import Path

from jev_cookbook import load_helpers

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# Seeds are committed so every baseline and the model policy are reproducible from here on;
# docs/fixtures.md asks for "tens of examples, small enough to read" at levels 1 and 2, and this
# Level 3 recipe sizes its two different quantities separately (CONTRIBUTING.md's examples-vs-
# units distinction): VALIDATION_SEEDS and TEST_SEEDS are task-level units (seeded games), each
# contributing helpers.N_CARDS - 1 decided turns (one forced single-card turn per game is
# resolved directly in Python and is never a scored example -- see helpers.play_game).
VALIDATION_SEEDS = tuple(range(100, 110))  # 10 games
TEST_SEEDS = tuple(range(200, 214))  # 14 games
DEMO_SEED = 999  # shown, never scored


def _rollout_labelled_turns(seed: int, split: str, max_turns: int | None = None) -> list[tuple]:
    """Play one game seed with the rule-based baseline and return one ``ROWS`` row per decided
    turn (``max_turns`` caps how many turns of the game are recorded, for the demo split)."""
    sim = helpers.CardDuel(seed=seed, n_cards=helpers.N_CARDS)
    rows = []
    turns_recorded = 0
    while not sim.done and (max_turns is None or turns_recorded < max_turns):
        legal = sim.legal_actions()
        observation = sim.observe()
        if len(legal) >= 2:
            hand = [int(a.split("_", 1)[1]) for a in legal]
            gold = helpers.rule_based_action(observation["prize"], hand)
            fields = {
                "game_seed": seed,
                "turn": observation["turn"],
                "prize": observation["prize"],
                "hand": observation["hand"],
                "cards_remaining": observation["cards_remaining"],
                "player_score": observation["player_score"],
                "opponent_score": observation["opponent_score"],
            }
            label = gold if split != "demo" else None
            rows.append((f"g{seed}-t{observation['turn']}", split, fields, label))
            turns_recorded += 1
            action = gold
        else:
            action = legal[0]  # the forced, single-card turn: never a scored example
        sim.step(action)
    return rows


def _build_rows() -> list[tuple]:
    rows: list[tuple] = []
    for seed in VALIDATION_SEEDS:
        rows += _rollout_labelled_turns(seed, "validation")
    for seed in TEST_SEEDS:
        rows += _rollout_labelled_turns(seed, "test")
    rows += _rollout_labelled_turns(DEMO_SEED, "demo", max_turns=2)
    return rows


ROWS = _build_rows()  # (id, split, fields, gold label or None for a demo example)


def main() -> None:
    if not ROWS:
        raise SystemExit("no rows to write: _build_rows() produced an empty ROWS")
    inputs, labels = [], []
    for ident, split, fields, label in ROWS:
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": []})
        if label is not None:
            labels.append({"id": ident, "label": label})
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\n" for row in rows)
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    (folder / "responses.json").unlink(missing_ok=True)  # a scripted recipe has none
    print(f"wrote {len(inputs)} examples and {len(labels)} labels")


if __name__ == "__main__":
    main()
