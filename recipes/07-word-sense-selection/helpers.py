"""Python's half of recipe 07: the state, the questions and the rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed sense inventory, one entry per target word this recipe covers. Each word's senses
# are a fixed, supplied set; Jev never invents a sense, and a sense not in this dict for its
# word can never be asked about or answered. Descriptions say what each sense covers so the two
# senses of a word, which can look alike out of context, are told apart by what they each name.
SENSE_INVENTORY: dict[str, dict[str, str]] = {
    "bank": {
        "financial_institution": (
            "A business that holds money for people, offers loans and manages accounts."
        ),
        "river_edge": ("The sloped land along the side of a river, lake or other body of water."),
    },
    "crane": {
        "machine": (
            "A machine with a tall arm that lifts and moves heavy loads, used on construction "
            "sites and docks."
        ),
        "bird": ("A tall wading bird with a long neck and long legs, usually found near water."),
    },
    "spring": {
        "season": ("The season between winter and summer, when plants begin to grow again."),
        "coil": (
            "A coiled strip or wire of metal that stores mechanical energy when compressed or "
            "stretched."
        ),
    },
    "bat": {
        "animal": "A small flying nocturnal mammal with wings made of skin.",
        "equipment": "A solid club used to hit a ball in a game such as baseball or cricket.",
    },
}

# The fallback every word's option list carries, on top of its own senses: the use case names a
# sentence whose context is too thin to tell the senses apart, and a Choice that had to pick one
# of the real senses anyway would hide that honestly. `unclear` is never a gold label (a fixture
# always has one intended sense), but it is always an option the model may choose, and it is
# never accepted as a reported result (see `resolve` below).
UNCLEAR = "unclear"

ACCEPTED = "accepted"
REVIEW = "review"


def senses_for(word: str) -> dict[str, str]:
    """The fixed option set for ``word``: its own senses, plus the shared ``unclear`` fallback.

    Raises ``KeyError`` naming the word if it is not in the inventory, rather than asking Jev to
    choose from nothing.
    """
    if word not in SENSE_INVENTORY:
        raise KeyError(f"{word!r} is not in SENSE_INVENTORY")
    criteria = dict(SENSE_INVENTORY[word])
    criteria[UNCLEAR] = (
        f"The sentence does not give enough context to tell which sense of {word!r} is "
        "intended here."
    )
    return criteria


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one sentence: the target word and the sentence, nothing else.

    ``fields`` also carries ``sentence_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the outcome, so it never needs to pass through the model.
    """
    return {"word": fields["word"], "sentence": fields["sentence"]}


def build_questions(word: str) -> dict[str, Choice]:
    """The one question asked about a sentence containing ``word``.

    Every target word shares one question shape (name it the intended sense), but the option
    list is built fresh per word from ``senses_for``, so a sentence about "crane" is never asked
    to choose a "bank" sense, and the replay key changes with the word as a result.
    """
    return {
        "sense": Choice(
            instructions=(f"In the sentence below, which sense of the word {word!r} is intended?"),
            criteria=senses_for(word),
        )
    }


@dataclass(frozen=True)
class Resolution:
    """What Python decided: the sense Jev chose, and whether it is accepted or sent to review."""

    sentence_id: str
    word: str
    sense: str
    outcome: str
    reason: str


def resolve(sentence_id: str, word: str, answer: Any, min_confidence: float) -> Resolution:
    """Accept the chosen sense only when it is a real sense of ``word`` and confident enough.

    Three things send a sentence to an explicit ``review`` outcome instead of a reported result:
    choosing ``unclear`` (whatever its confidence: a model that says "I can't tell" should never
    be overridden into picking a side because it happened to sound sure of "unclear" itself),
    choosing anything else that is not one of ``word``'s own senses (defensive: the criteria
    ``build_questions`` asks with never offer such an option, but the rule does not trust that
    silently), and confidence below ``min_confidence`` for an answer that did name a real sense.
    The rule is code, so it holds whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == UNCLEAR:
        return Resolution(sentence_id, word, answer.choice, REVIEW, "chose unclear")
    if answer.choice not in SENSE_INVENTORY[word]:
        return Resolution(sentence_id, word, answer.choice, REVIEW, "not a sense of this word")
    if answer.confidence < min_confidence:
        return Resolution(
            sentence_id, word, answer.choice, REVIEW, "confidence below the threshold"
        )
    return Resolution(sentence_id, word, answer.choice, ACCEPTED, "confident")
