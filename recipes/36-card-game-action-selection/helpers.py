"""Python's half of recipe 36: the card-game simulator, the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.

**The game ("Card Duel").** Both the player and a fixed opponent start holding one card of each
value ``1`` to ``N_CARDS``. A hidden prize deck -- a seeded random permutation of the same values
-- is revealed one card at a time, one per turn. Each turn the player bids one remaining card from
hand; the opponent's own card is picked by a fixed rule (below). Whoever bids higher wins the
turn's prize value as points; a tie wins nobody anything. The game ends once every card has been
bid (``N_CARDS`` turns). Python enumerates the player's remaining hand as the legal actions each
turn -- ``CardDuel`` (a ``jev_cookbook.simulation.Simulator``) rejects anything else -- so a model
can never bid a card it does not hold or has already played.
"""

import random
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice
from jev_cookbook.simulation import IllegalActionError, Simulator

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

RECIPE_SLUG = "36-card-game-action-selection"
N_CARDS = 5  # cards 1..N_CARDS in every hand; also the number of turns in one game

REVIEW = "review"  # docs/glossary.md#review: the outcome value itself is the string "review"
REASON_LOW_CONFIDENCE = "confidence below the threshold"  # docs/glossary.md#review, exact text
ANSWERED = "answered"


# --------------------------------------------------------------------------------------------
# The simulator
# --------------------------------------------------------------------------------------------


def _fisher_yates(values: range, rng: random.Random) -> tuple[int, ...]:
    """A Durstenfeld shuffle of ``values``, drawing only from ``rng.random()``.

    ``random.Random.shuffle`` is not used: the ``random`` module's own documentation commits
    only ``random()`` itself to producing the same sequence for the same seed across Python
    versions (``docs/simulation.md``, "Simulator"), so a *new* simulator's own random choices --
    this prize-order shuffle is the only one ``CardDuel`` makes -- are built from ``random()``
    directly rather than from ``shuffle()`` or ``randrange()``.
    """
    items = list(values)
    for i in range(len(items) - 1, 0, -1):
        j = int(rng.random() * (i + 1))
        items[i], items[j] = items[j], items[i]
    return tuple(items)


def _opponent_card(hand: tuple[int, ...], prize: int) -> int:
    """The fixed opponent rule: bid the card closest in value to the prize, ties to the higher
    card. Deterministic given the opponent's own remaining hand and the current prize, so the
    opponent's whole sequence of bids depends only on the game's seed, never on what the player
    bids -- which is what makes it fair to compare several player policies on the same seed."""
    return min(hand, key=lambda c: (abs(c - prize), -c))


class CardDuel(Simulator):
    """A seeded two-player prize-bidding card game; see the module docstring for the rules.

    The opponent's hand is hidden: ``_observe`` never reveals it, so a policy knows only the
    current prize, its own remaining hand, and the running score -- consistent with "structured
    state ... while Python enforces game rules" (the use case this recipe builds).
    """

    def __init__(self, seed: int = 0, n_cards: int = N_CARDS) -> None:
        if type(n_cards) is not int or n_cards < 2:
            raise ValueError("n_cards must be an int >= 2")
        self.n_cards = n_cards
        self.player_hand: tuple[int, ...] = ()
        self.opponent_hand: tuple[int, ...] = ()
        self.prize_order: tuple[int, ...] = ()
        self.turn = 0
        self.player_score = 0
        self.opponent_score = 0
        super().__init__(seed)

    def _reset(self, rng: random.Random) -> None:
        full = tuple(range(1, self.n_cards + 1))
        self.player_hand = full
        self.opponent_hand = full
        self.prize_order = _fisher_yates(range(1, self.n_cards + 1), rng)
        self.turn = 0
        self.player_score = 0
        self.opponent_score = 0

    def _observe(self) -> Any:
        prize = self.prize_order[self.turn] if self.turn < len(self.prize_order) else None
        return {
            "turn": self.turn,
            "prize": prize,
            "hand": sorted(self.player_hand),
            "cards_remaining": len(self.player_hand),
            "player_score": self.player_score,
            "opponent_score": self.opponent_score,
        }

    def _legal_actions(self) -> list[str]:
        return [f"bid_{card}" for card in sorted(self.player_hand)]

    def _apply(self, action: Any, rng: random.Random) -> Any:
        card = int(action.split("_", 1)[1])
        self.player_hand = tuple(c for c in self.player_hand if c != card)
        prize = self.prize_order[self.turn]
        opponent_card = _opponent_card(self.opponent_hand, prize)
        self.opponent_hand = tuple(c for c in self.opponent_hand if c != opponent_card)
        if card > opponent_card:
            winner = "player"
            self.player_score += prize
        elif opponent_card > card:
            winner = "opponent"
            self.opponent_score += prize
        else:
            winner = "tie"
        self.turn += 1
        return {
            "played": card,
            "opponent_played": opponent_card,
            "prize": prize,
            "winner": winner,
            "player_score": self.player_score,
            "opponent_score": self.opponent_score,
        }

    def _snapshot(self) -> Any:
        return {
            "player_hand": sorted(self.player_hand),
            "opponent_hand": sorted(self.opponent_hand),
            "prize_order": list(self.prize_order),
            "turn": self.turn,
            "player_score": self.player_score,
            "opponent_score": self.opponent_score,
        }

    def _is_done(self) -> bool:
        return len(self.player_hand) == 0


# --------------------------------------------------------------------------------------------
# The state and the questions
# --------------------------------------------------------------------------------------------


def build_state(fields: dict[str, Any]) -> dict[str, Any]:
    """The state Jev sees for one turn: everything ``CardDuel._observe`` shows except the game
    seed, which is a Python bookkeeping identifier used to reproduce the example and never a
    judgment input."""
    return {
        "turn": fields["turn"],
        "prize": fields["prize"],
        "hand": fields["hand"],
        "cards_remaining": fields["cards_remaining"],
        "player_score": fields["player_score"],
        "opponent_score": fields["opponent_score"],
    }


def legal_actions_from_hand(hand: list[int]) -> list[str]:
    """The fixed action-name convention (``bid_<card>``), reused everywhere a hand becomes a
    legal-action list: by ``CardDuel._legal_actions`` (as plain cards, mapped here) is not
    reused directly since the simulator already returns the ``bid_<card>`` strings -- this
    helper exists for building the same option list from fixture ``fields`` (where only the
    hand, not a live simulator, is available)."""
    return [f"bid_{card}" for card in hand]


def build_questions(legal: list[str]) -> dict[str, Choice]:
    """One ``Choice`` over exactly the legal actions Python enumerated for this turn.

    ``legal`` is already sorted ascending by card value (``CardDuel.legal_actions()`` and
    ``legal_actions_from_hand`` both build it that way): low cards first is a fixed, meaningful
    order (cheapest sacrifice to most valuable card), not an arbitrary authored order, so this
    recipe reports no option-position statistic (``docs/fixtures.md``, "Per-item option order";
    CONTRIBUTING.md lesson on position statistics computed from hand-written fixtures).
    """
    if len(legal) < 2:
        raise ValueError(
            "a Choice needs at least two options; a single remaining card is resolved "
            "directly in Python (see play_game) and never reaches this function"
        )
    criteria = {
        action: f"Bid your {int(action.split('_', 1)[1])}-point card for this round's prize."
        for action in legal
    }
    return {
        "bid": Choice(
            instructions=(
                "You are bidding cards, one per round, to win prize points. This round's prize "
                "and your remaining hand are given below; pick the card to bid this round that "
                "gives you the best chance of winning the most prize points over the whole game."
            ),
            criteria=criteria,
        )
    }


# --------------------------------------------------------------------------------------------
# Policies: random, rule-based, and the scripted stand-in for Jev
# --------------------------------------------------------------------------------------------


def rule_based_action(prize: int, hand: list[int]) -> str:
    """The rule-based baseline: bid the cheapest card that still wins the prize; if none can
    win, sacrifice the cheapest card instead. A minimal-overkill, cut-your-losses heuristic that
    needs no knowledge of the opponent's hand."""
    winning = [card for card in hand if card > prize]
    card = min(winning) if winning else min(hand)
    return f"bid_{card}"


def make_random_policy(seed_key: str) -> Any:
    """A random legal policy, seeded once per game from ``seed_key`` (a string, hashed by
    ``random.Random`` the same documented-stable way ``jev_cookbook.fixtures.stable_permutation``
    seeds a per-item order) so the same key always plays the same random game."""
    rng = random.Random(seed_key)

    def policy(observation: dict[str, Any], legal: list[str]) -> str:
        return legal[int(rng.random() * len(legal))]

    return policy


def rule_based_policy(observation: dict[str, Any], legal: list[str]) -> str:
    """The rule-based baseline policy, over an observation (see ``rule_based_action``)."""
    hand = [int(a.split("_", 1)[1]) for a in legal]
    return rule_based_action(observation["prize"], hand)


SEED = 0  # the scripted backend's own seed; committed so the offline run is reproducible


def script(state: dict[str, Any], questions: dict[str, Choice], rng: random.Random) -> dict:
    """Stand in for the model: mostly agree with the rule-based baseline, sometimes not.

    A pipeline check, not a Jev result (CONTRIBUTING.md section 2): the weights below come from
    this seeded script, never from a model. With probability ``1 - P_MISTAKE`` the script is
    confident and names the rule-based action; otherwise it spreads most of its weight onto a
    different legal action (deliberately a plausible but non-optimal bid: the next cheapest
    card above the rule-based choice, wrapping to the cheapest option), so this recipe's fixture
    set is not so tidy that every synthetic answer is right (``docs/fixtures.md``, "Responses and
    provenance").
    """
    legal = list(questions["bid"].criteria)
    hand = [int(a.split("_", 1)[1]) for a in legal]
    gold = rule_based_action(state["prize"], hand)
    if rng.random() >= P_MISTAKE:
        weights = {name: (0.85 if name == gold else 0.15 / (len(legal) - 1)) for name in legal}
    else:
        wrong = legal[(legal.index(gold) + 1) % len(legal)]
        weights = {name: (0.70 if name == wrong else 0.30 / (len(legal) - 1)) for name in legal}
    return {"bid": weights}


P_MISTAKE = 0.3  # the fraction of decided turns the script answers with a non-gold peak


# --------------------------------------------------------------------------------------------
# The confidence gate: Python's rule, whatever the model answers
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDecision:
    """What the confidence gate decided for one turn: the action actually played, and why."""

    action: str
    outcome: str  # ANSWERED or REVIEW
    reason: str | None  # None when outcome is ANSWERED
    raw_choice: str  # the model's own choice, whatever the gate decided


def gate_turn(answer: Any, fallback_action: str, min_confidence: float) -> GateDecision:
    """Python's one rule for a decided turn (``len(legal) >= 2``): play the model's own choice
    when its confidence clears the gate, otherwise play the (always legal) fallback action and
    record the turn for review. This is the recipe's only review branch -- nothing else ever
    withholds a turn from being auto-answered -- so it is a confidence-only rule: the selective
    prediction functions that reapply ``confidence >= threshold`` themselves
    (``evaluate_selective``) describe it exactly, with no need for ``evaluate_outcomes``.

    ``fallback_action`` must itself be legal (the rule-based action always is, since it is drawn
    from the same hand): whichever action this function returns, the simulator still enforces
    legality once more when it is actually played, so an uncertain turn never risks becoming an
    illegal one.
    """
    if answer.confidence < min_confidence:
        return GateDecision(fallback_action, REVIEW, REASON_LOW_CONFIDENCE, answer.choice)
    return GateDecision(answer.choice, ANSWERED, None, answer.choice)


def decide_turn(backend: Any, observation: dict[str, Any], legal: list[str]) -> Any:
    """Ask one ``Choice`` about one turn and return the ``bid`` answer: the state and the
    question are built from exactly ``observation`` and ``legal``, so this is the one place a
    per-turn request is assembled, reused by the fixture generator, the notebook and every
    policy below."""
    state = build_state(observation)
    questions = build_questions(legal)
    return backend.decide(state, questions)["bid"]


def make_gated_policy(backend: Any, min_confidence: float) -> Any:
    """The confidence-gated model policy: ``gate_turn`` applied to a live ``decide_turn`` call,
    falling back to the rule-based action on a low-confidence turn (see ``gate_turn``)."""

    def policy(observation: dict[str, Any], legal: list[str]) -> str:
        answer = decide_turn(backend, observation, legal)
        hand = [int(a.split("_", 1)[1]) for a in legal]
        fallback = rule_based_action(observation["prize"], hand)
        return gate_turn(answer, fallback, min_confidence).action

    return policy


def make_raw_policy(backend: Any) -> Any:
    """The model's own raw choice, never gated: shown only as a counterfactual beside the
    confidence-gated policy, to disclose what the gate buys (never reported as a baseline in
    its own right -- this recipe's two baselines are the random legal policy and the
    rule-based policy)."""

    def policy(observation: dict[str, Any], legal: list[str]) -> str:
        return decide_turn(backend, observation, legal).choice

    return policy


# --------------------------------------------------------------------------------------------
# The composed, task-level game: many Choice-shaped decisions into one win/lose/tie outcome
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GameResult:
    """One played-out game: who won, and the full trajectory for an independent replay check."""

    seed: int
    winner: str  # "player", "opponent" or "tie"
    player_score: int
    opponent_score: int
    n_turns_checked: int
    trajectory: tuple[dict[str, Any], ...]


def play_game(policy: Any, seed: int, n_cards: int = N_CARDS) -> GameResult:
    """Play one seeded game end to end under ``policy(observation, legal) -> action``.

    The deterministic composition CONTRIBUTING.md's Level 3 pattern asks for: many per-turn
    Choice-shaped decisions (whatever ``policy`` is -- a random pick, the rule-based baseline, or
    a confidence-gated model policy) composed by Python into one task-level outcome. A turn with
    only one legal action (the last card in hand) is resolved directly, never asking ``policy``
    at all, matching ``docs/backends.md``'s "Single-option Choice" rule.

    Every action ``policy`` returns is checked against ``CardDuel.legal_actions()`` *before* it
    is played, raising ``IllegalActionError`` otherwise (the same exception
    ``CardDuel.step`` itself would raise, so the two checks cannot silently disagree about what
    counts as legal): this is the cheap half of the zero-illegal-actions guarantee, proven
    directly by a test that feeds this function a policy that never names a legal action. The
    valuable half -- that every action a *real* policy actually chose really was legal, over
    every seeded game -- is in the notebook's evaluation section, which independently replays
    every trajectory this function returns with ``Simulator.replay`` and counts the result.
    """
    sim = CardDuel(seed=seed, n_cards=n_cards)
    n_checked = 0
    while not sim.done:
        legal = sim.legal_actions()
        observation = sim.observe()
        action = legal[0] if len(legal) == 1 else policy(observation, legal)
        if action not in legal:
            raise IllegalActionError(
                f"policy chose {action!r}, not among the legal actions {legal!r} for turn "
                f"{observation['turn']}"
            )
        n_checked += 1
        sim.step(action)
    snapshot = sim.snapshot()
    if snapshot["player_score"] > snapshot["opponent_score"]:
        winner = "player"
    elif snapshot["opponent_score"] > snapshot["player_score"]:
        winner = "opponent"
    else:
        winner = "tie"
    return GameResult(
        seed,
        winner,
        snapshot["player_score"],
        snapshot["opponent_score"],
        n_checked,
        tuple(sim.trajectory()),
    )
