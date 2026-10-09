"""Python's half of recipe 12: the state, the questions and the rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# Short, context-free dictionary glosses for every candidate synonym this recipe's fixtures use.
# A gloss says what a word means on its own; it never says whether that word fits a particular
# sentence, which is exactly the judgment this recipe asks Jev to make. KeyError on a candidate
# missing from this dict (see `candidate_options`) means Jev would otherwise be asked to choose
# from an option it was told nothing about.
SYNONYM_DEFINITIONS: dict[str, str] = {
    "joyful": "full of happiness; feeling great pleasure.",
    "content": "satisfied with what one has; not needing anything more.",
    "cheerful": "noticeably happy and good-humoured.",
    "pleased": "feeling satisfaction about one particular thing that happened.",
    "glad": "pleased about a particular event or piece of news.",
    "large": "great in size or extent.",
    "enormous": "extremely large in size or amount.",
    "huge": "extremely large; enormous.",
    "sizable": "fairly large; big enough to be worth noting.",
    "massive": "very large, heavy and solid.",
    "fast": "moving or acting at high speed.",
    "swift": "happening or moving quickly.",
    "speedy": "done or occurring with great speed.",
    "hasty": "done too quickly, often carelessly.",
    "brisk": "quick and energetic in movement or action.",
    "furious": "extremely angry.",
    "irritated": "annoyed, especially by something persistent or minor.",
    "annoyed": "slightly angry about something bothersome.",
    "livid": "extremely angry; furiously enraged.",
    "cross": "fairly angry or irritable.",
}

# The fallback every sentence's option list carries, on top of its own candidate synonyms: the
# use case names a sentence whose supplied candidates do not preserve the target word's meaning,
# and Python must still offer a way to say so rather than forcing a pick among words that do not
# fit. Unlike a Choice option that only ever means "the model could not decide" (recipe 07's
# "unclear"), `keep_original` is a real, final answer: it is the correct, scorable
# outcome whenever a fixture's gold set says no candidate fits, and it triggers no side effect
# of its own (nothing is sent, moved or changed; the sentence is simply left as written), so it
# never has to be routed to review just for being chosen -- it is held to the same confidence
# gate as every other option (`resolve`, below).
KEEP_ORIGINAL = "keep_original"

ACCEPTED = "accepted"
REVIEW = "review"


def candidate_options(word: str, candidates: list[str]) -> dict[str, str]:
    """The fixed option set for one sentence: its own supplied candidates, each with its
    dictionary gloss, plus the shared ``keep_original`` fallback.

    ``candidates`` is assembled by Python per sentence (see ``build_fixtures.py``), not shared
    across every sentence that happens to use ``word``: two sentences about the same word may be
    given different candidate lists, so the option set -- and therefore the replay key -- follows
    the sentence, not the word. Raises ``KeyError`` naming any candidate this module has no gloss
    for, rather than asking Jev to choose from an option it was told nothing about.
    """
    missing = [c for c in candidates if c not in SYNONYM_DEFINITIONS]
    if missing:
        raise KeyError(f"no definition for {missing!r} in SYNONYM_DEFINITIONS")
    criteria = {c: SYNONYM_DEFINITIONS[c] for c in candidates}
    criteria[KEEP_ORIGINAL] = (
        f"None of the words above preserve the sentence's meaning in place of {word!r} here; "
        "keep the original word unchanged."
    )
    return criteria


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one sentence: the target word and the sentence, nothing else.

    ``fields`` also carries ``item_id`` and ``candidates``. Python keeps the identifier and
    attaches it to the outcome, so it never needs to pass through the model; ``candidates``
    shapes the question (below), not the state.
    """
    return {"word": fields["word"], "sentence": fields["sentence"]}


def build_questions(word: str, candidates: list[str]) -> dict[str, Choice]:
    """The one question asked about a sentence containing ``word``.

    Every sentence shares one question shape (name the best replacement), but the option list is
    built fresh per sentence from ``candidates``, so two sentences about the same word can be
    asked to choose among different sets of candidates, and changing one sentence's candidates
    changes only that sentence's replay key, never another sentence's.

    ``candidates`` must be non-empty: with none, the only possible option would be the fallback
    ``keep_original`` alone, a single-option ``Choice`` that is never built at all -- a sentence
    with no supplied candidates is resolved directly by ``no_candidates_resolution`` instead,
    before any question is built and before any request is spent. Unreachable from this recipe's
    committed fixtures (every sentence lists at least one real candidate), but kept so the
    single-option guard is uniform with recipes 14 and 22.
    """
    if not candidates:
        raise ValueError(
            "build_questions needs at least one real candidate; a sentence with none is "
            "resolved directly by no_candidates_resolution and never reaches this function"
        )
    return {
        "synonym": Choice(
            instructions=(
                f"The word {word!r} appears in the sentence below. Choose the option that could "
                f"replace {word!r} without changing the sentence's meaning. If none of the "
                f"supplied words preserve the meaning, choose {KEEP_ORIGINAL!r}."
            ),
            criteria=candidate_options(word, candidates),
        )
    }


@dataclass(frozen=True)
class Resolution:
    """What Python decided: the option Jev chose, and whether it is accepted or sent to review."""

    item_id: str
    choice: str
    outcome: str
    reason: str


def no_candidates_resolution(item_id: str) -> Resolution:
    """The forced resolution for a sentence with no supplied candidates at all: with no real
    candidate, the only possible option would be the fallback ``keep_original`` alone, a
    single-option ``Choice`` ``build_questions`` refuses to build, so no request is ever sent to
    Jev for this sentence. ``keep_original`` is final here exactly as it is when Jev itself names
    it, since it triggers no side effect either way. Unreachable from this recipe's committed
    fixtures -- every sentence supplies at least one real candidate -- but kept so this recipe
    makes the same single-option decision recipes 14 and 22 make."""
    return Resolution(
        item_id, KEEP_ORIGINAL, ACCEPTED, "no candidates were supplied for this sentence"
    )


def resolve(item_id: str, answer: Any, candidates: list[str], min_confidence: float) -> Resolution:
    """Accept the chosen option only when it is one Jev was actually offered and it is confident
    enough; otherwise send it to an explicit ``review`` outcome instead of a reported result.

    Two things send a sentence to review: choosing something that is not one of ``candidates`` or
    ``keep_original`` -- defensive: the backend already restricts an answer to the question's own
    options (`docs/backends.md`), so this branch cannot fire through replay or live, but the rule
    does not trust that silently -- and confidence below
    ``min_confidence``, whatever option was named, ``keep_original`` included: a confident
    ``keep_original`` is accepted exactly like a confident candidate, because it is as final an
    answer as any of them. The rule is code, so it holds whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    valid = {*candidates, KEEP_ORIGINAL}
    if answer.choice not in valid:
        return Resolution(item_id, answer.choice, REVIEW, "not a supplied option")
    if answer.confidence < min_confidence:
        return Resolution(item_id, answer.choice, REVIEW, "confidence below the threshold")
    return Resolution(item_id, answer.choice, ACCEPTED, "confident")
