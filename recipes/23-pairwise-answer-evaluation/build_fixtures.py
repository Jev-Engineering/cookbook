"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe 23.

    python build_fixtures.py          # from anywhere; it writes next to this file
    python build_fixtures.py --force  # also overwrite a responses.json holding a recorded answer

Every comparison makes two requests: the candidates in one order, then the same two candidates
with the order swapped (``helpers.build_state(fields, swap=True)``), so every row below
contributes two entries to ``responses.json`` and two replay keys, listed in request order, to
its row in ``inputs.jsonl``. Which candidate is shown first in the *first* request
(``fields["a_shown_first"]``) is decided once by ``helpers.assign_first_shown``, which hashes
each row's id on its own (never its position in ``ROWS``, which is grouped by gold label here,
and never the gold label or the candidate text itself). That rules out the one correlation a
sequential random draw over this list could otherwise have smuggled in; it does not by itself
prove the result is balanced -- see the printed table in "The questions" and the comment next to
``helpers.ORDER_SEED``.

Every response here is synthetic, authored directly in the comparison's own vocabulary
(``a``, ``b``, ``tie``, ``insufficient_evidence``) rather than as positional probabilities:
``_positional_probabilities`` converts a row's intended label and confidence into the
``first``/``second``/``tie``/``insufficient_evidence`` probabilities Jev is actually asked for,
using which candidate is first in that specific request. That keeps the hard cases legible in
``ROWS`` (what each request is *supposed* to say about ``a`` versus ``b``) while still exercising
the real, positional question the notebook asks.

Several rows are deliberately imperfect on purpose, and fall into the shapes CONTRIBUTING.md and
the issue's build notes ask for:

- most rows: both requests agree with each other and with the gold label (the ordinary case);
- ``v04``/``t04``: both requests agree with each other but *not* with the gold label. Both use
  the ``honest`` criterion, and in both the losing candidate makes a flat, unqualified claim
  ("generally fine", "it will definitely arrive by Friday") where the winning candidate names a
  concrete, specific reason for its own uncertainty -- that is the shape CONTRIBUTING.md's
  "unearned confidence" language is pointing at, not a hedge-versus-confidence judgment call that
  a reasonable reader could take either way. ``t04``'s confidence is well above the threshold
  this recipe freezes on ``validation``, so it is the fixture responsible for this recipe's
  non-zero risk on ``test``; ``v04``'s own confidence is deliberately just below that frozen
  threshold, so the same kind of mistake is instead the fixture that sets the threshold in the
  first place;
- ``v19``, ``t19`` and ``v05``, ``v10``, ``v15``, ``t05``, ``t09``, ``t10``, ``t14``: the two
  requests disagree with each other (position bias), split between cases where the *first*
  request happens to be the one that agrees with gold and cases where the *second* one does, so
  neither request is the reliable one to trust alone;
- ``t20``: both requests agree with each other, confidently, on ``insufficient_evidence`` --
  while the gold label is a plainly judgeable ``a``. CONTRIBUTING.md section 4 lets
  ``judge_pair`` accept an agreed ``insufficient_evidence`` with no confidence gate, because
  choosing it has no side effect; this row shows that exemption is not free: it costs exactly
  this comparison in ``test``'s risk, the same way an ungated wrong answer would anywhere else.

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

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
OPTIONS = list(QUESTIONS["verdict"].criteria)  # first, second, tie, insufficient_evidence

# A small, reused library of rubric criteria. Each comparison names exactly one of these; the
# notebook shows the criterion text alongside the two candidates it was judged against.
CRITERIA = {
    "direct": (
        "Which candidate answer more directly and specifically answers the exact question that "
        "was asked, rather than a related but different one?"
    ),
    "precise": (
        "Which candidate answer is more factually precise about the specific number, date, or "
        "name the question asks for?"
    ),
    "actionable": (
        "Which candidate answer gives the reader steps they could actually follow, rather than "
        "a vague description of what to do?"
    ),
    "honest": (
        "Which candidate answer is more honest about what it does not know, rather than "
        "guessing with unearned confidence?"
    ),
    "ontopic": (
        "Which candidate answer stays on the one topic the question raises, rather than "
        "drifting into unrelated advice?"
    ),
}

# (id, split, criterion key, question, candidate_a, candidate_b, gold label or None for demo,
#  label the first request is written to agree on, that request's confidence,
#  label the second (swapped) request is written to agree on, that request's confidence)
#
# A label is "a", "b", "tie" or "insufficient_evidence" -- the comparison's own vocabulary, not
# the positional "first"/"second" Jev is actually asked for; build_responses converts.
ROWS = [  # fmt: skip
    # ---------------------------------------------------------------- validation: 19 examples
    ("v01", "validation", "direct",
     "What time does the downtown branch close on Saturdays?",
     "The downtown branch closes at 4pm on Saturdays; it's open until 6pm on weekdays.",
     "Most of our branches follow standard banking hours, so check the branch locator for exact times.",
     "a", "a", 0.95, "a", 0.92),
    ("v02", "validation", "precise",
     "How many ounces are in a standard coffee mug?",
     "A standard coffee mug holds about 8 to 12 ounces, with 12 ounces being the most common size sold today.",
     "Coffee mugs come in all kinds of sizes depending on the brand and style you prefer.",
     "a", "a", 0.80, "a", 0.78),
    ("v03", "validation", "actionable",
     "How do I reset a tripped circuit breaker?",
     "Find the breaker panel, locate the switch that is in the middle position (not fully on or off), and flip it fully off, then fully on.",
     "Circuit breakers trip for safety reasons when there's too much electrical load on a circuit.",
     "a", "a", 0.60, "a", 0.58),
    ("v04", "validation", "honest",
     "Does this medication need to be taken with food?",
     "Yes, taking it with food reduces stomach upset; the label recommends taking it with a meal.",
     "I'm not certain, but taking most medications on an empty stomach is generally fine.",
     "a", "b", 0.55, "b", 0.52),
    ("v05", "validation", "ontopic",
     "What's the best way to remove a red wine stain from a white shirt?",
     "Blot (don't rub) the stain, then rinse with cold water from the back of the fabric, and apply a bit of dish soap before washing as usual.",
     "Red wine stains are notoriously hard to remove, and some fabrics hide stains better than others depending on the weave.",
     "a", "b", 0.70, "a", 0.65),
    ("v06", "validation", "direct",
     "Which bus route goes from the airport to the convention center?",
     "Several bus routes connect major parts of the city, and most run every 20 to 30 minutes.",
     "Route 42 goes directly from the airport to the convention center, running every 15 minutes.",
     "b", "b", 0.93, "b", 0.90),
    ("v07", "validation", "precise",
     "How long is the warranty on this blender?",
     "Kitchen appliances typically come with a warranty that covers manufacturing defects for a period of time.",
     "This blender has a 2-year warranty covering the motor and a 1-year warranty on the blades.",
     "b", "b", 0.75, "b", 0.72),
    ("v08", "validation", "actionable",
     "How do I pair these headphones with my phone?",
     "Bluetooth headphones usually pair easily with most modern smartphones once both devices are turned on.",
     "Hold the power button for 5 seconds until the light flashes blue, then select the headphones' name in your phone's Bluetooth settings.",
     "b", "b", 0.58, "b", 0.56),
    ("v09", "validation", "honest",
     "Will this paint color look the same on my living room wall as it does on the sample card?",
     "Yes, the paint will look exactly like the sample card once it's applied and dried.",
     "It can look noticeably different depending on your room's lighting, so I'd recommend testing a small patch before committing to the whole wall.",
     "b", "b", 0.85, "b", 0.83),
    ("v10", "validation", "ontopic",
     "What's the quickest way to get from the hotel to the museum downtown?",
     "Downtown areas often have a mix of walking paths, bike lanes, and public transit options.",
     "Take the number 6 tram from outside the hotel; it drops you two blocks from the museum in about 10 minutes.",
     "b", "a", 0.68, "b", 0.66),
    ("v11", "validation", "direct",
     "Can I return this item if I no longer have the receipt?",
     "Yes, as long as the item was purchased within 30 days, we can look up the purchase using the card you paid with.",
     "Yes, we can process the return without a receipt if you show the card you used, as long as it's within 30 days.",
     "tie", "tie", 0.90, "tie", 0.88),
    ("v12", "validation", "precise",
     "What's the boiling point of water at sea level?",
     "Water boils at 100 degrees Celsius, which is 212 degrees Fahrenheit, at sea level.",
     "At sea level, water reaches its boiling point at 212 degrees Fahrenheit, or 100 Celsius.",
     "tie", "tie", 0.70, "tie", 0.68),
    ("v13", "validation", "actionable",
     "How do I defrost a frozen chicken breast quickly and safely?",
     "Seal it in a bag and submerge it in cold water, changing the water every 30 minutes until thawed.",
     "Place it in a sealed bag in cold water, swapping the water out every half hour until it's no longer frozen.",
     "tie", "tie", 0.55, "tie", 0.53),
    ("v14", "validation", "honest",
     "Is it definitely going to rain during the festival this weekend?",
     "The forecast shows a decent chance of rain Saturday afternoon, but it's not certain this far out.",
     "There's a real possibility of rain on Saturday afternoon, though forecasts this far ahead can still change.",
     "tie", "tie", 0.65, "tie", 0.60),
    ("v15", "validation", "ontopic",
     "Do both of these hiking trails have good views of the lake?",
     "Both the north and south trails run along the ridge and have clear lake views for most of the route.",
     "Both trails stay close to the ridge line, so the lake is visible for the majority of each hike.",
     "tie", "tie", 0.72, "a", 0.50),
    ("v16", "validation", "precise",
     "What's a thoughtful gift for a coworker who's moving to a new city?",
     "A local coffee shop gift card is a nice way to help them explore their new neighborhood.",
     "A subscription box tailored to their hobbies can be a fun surprise in a new place.",
     "insufficient_evidence", "insufficient_evidence", 0.60, "insufficient_evidence", 0.55),
    ("v17", "validation", "actionable",
     "Which color scheme feels more calming for a home office, blue tones or green tones?",
     "Blue tones are often associated with focus and calm in color psychology.",
     "Green tones tend to feel more natural and less sterile than blue in a work space.",
     "insufficient_evidence", "insufficient_evidence", 0.75, "insufficient_evidence", 0.70),
    ("v18", "validation", "honest",
     "What does the abbreviation 'FYI' stand for?",
     "It stands for 'for your information.'",
     "It's used to share something the recipient might find useful or relevant.",
     "insufficient_evidence", "insufficient_evidence", 0.58, "insufficient_evidence", 0.56),
    ("v19", "validation", "precise",
     "What should I keep in mind when choosing a houseplant for a shaded room?",
     "Look for plants labeled as low-light tolerant, like a pothos or a snake plant.",
     "Avoid plants that need direct sun, and check how often the specific variety needs watering.",
     "insufficient_evidence", "insufficient_evidence", 0.55, "b", 0.60),
    # ---------------------------------------------------------------- test: 20 examples
    ("t01", "test", "direct",
     "What's the Wi-Fi password for the guest network at this cafe?",
     "The guest network password is posted on a sign near the register: 'coffeebeans2024'.",
     "Most cafes change their Wi-Fi password periodically for security reasons.",
     "a", "a", 0.93, "a", 0.91),
    ("t02", "test", "precise",
     "How many calories are in one medium banana?",
     "A medium banana has about 105 calories.",
     "Bananas are a healthy snack with natural sugars and potassium.",
     "a", "a", 0.78, "a", 0.74),
    ("t03", "test", "actionable",
     "How do I unclog a slow bathroom sink drain?",
     "Remove the stopper, pull out any hair clogs with a bent wire hanger, then flush with hot water.",
     "Slow drains are usually caused by a buildup of hair, soap, and grime over time.",
     "a", "a", 0.58, "a", 0.56),
    ("t04", "test", "honest",
     "Will my package definitely arrive by Friday?",
     "It should arrive by Friday based on the current tracking estimate, but carriers occasionally run a day behind during holiday weeks.",
     "Yes, it will definitely arrive by Friday.",
     "a", "b", 0.88, "b", 0.84),
    ("t05", "test", "ontopic",
     "What's the fastest way to thaw frozen ground beef for dinner tonight?",
     "Submerge the sealed package in cold water, changing the water every 30 minutes; it thaws in under an hour.",
     "Ground beef can be frozen for several months without losing much quality.",
     "a", "a", 0.65, "tie", 0.60),
    ("t06", "test", "direct",
     "Which aisle has the batteries in this store?",
     "Stores usually group small electronics and batteries together near the checkout area.",
     "Batteries are in aisle 7, next to the light bulbs.",
     "b", "b", 0.90, "b", 0.87),
    ("t07", "test", "precise",
     "How much does standard shipping cost for this order?",
     "Shipping costs vary based on the size and weight of your order.",
     "Standard shipping for this order is $4.99 and takes 3 to 5 business days.",
     "b", "b", 0.72, "b", 0.70),
    ("t08", "test", "actionable",
     "How do I update the firmware on this router?",
     "Keeping router firmware current helps with security and performance.",
     "Log into the router's admin page at 192.168.1.1, go to Settings, then Firmware, and click Check for Updates.",
     "b", "b", 0.55, "b", 0.52),
    ("t09", "test", "honest",
     "Is this hiking trail safe to do alone at dusk?",
     "Hiking alone always carries some risk, so it's good to let someone know your plans either way.",
     "This particular trail has no lighting and several loose-rock sections, so I'd avoid it alone at dusk.",
     "b", "tie", 0.66, "b", 0.70),
    ("t10", "test", "ontopic",
     "Which of these two parking garages is closer to the stadium entrance?",
     "Both garages charge a flat event-day rate regardless of how long you stay.",
     "The west garage is about a two-minute walk from the stadium's main entrance; the east one is closer to ten.",
     "b", "a", 0.66, "b", 0.60),
    ("t11", "test", "direct",
     "Can I bring a reusable water bottle into the stadium?",
     "Yes, empty reusable bottles are allowed through the gate; you can fill them at the stations inside.",
     "Yes, you're allowed to bring an empty reusable bottle in and refill it at the water stations.",
     "tie", "tie", 0.85, "tie", 0.80),
    ("t12", "test", "precise",
     "How many feet are in a mile?",
     "A mile is 5,280 feet.",
     "There are 5,280 feet in one mile.",
     "tie", "tie", 0.62, "tie", 0.58),
    ("t13", "test", "actionable",
     "How do I clean a cast iron skillet after cooking?",
     "Wipe it out while still warm, scrub with a bit of coarse salt if needed, dry completely, then rub on a thin layer of oil.",
     "While it's still warm, scrub out any residue with coarse salt, dry it fully, and coat it lightly with oil.",
     "tie", "tie", 0.70, "tie", 0.65),
    ("t14", "test", "honest",
     "Will both of these laptop models last through a full workday on battery?",
     "Both are rated for around 9 hours of battery life under typical office use.",
     "Each one is rated at roughly 9 hours of use, which should cover most of a workday.",
     "tie", "b", 0.60, "tie", 0.55),
    ("t15", "test", "actionable",
     "Is it better to name a startup after its product or after its founder?",
     "A product name can make the brand easier to search for online.",
     "A founder's name can build personal trust, especially in service businesses.",
     "insufficient_evidence", "insufficient_evidence", 0.55, "insufficient_evidence", 0.50),
    ("t16", "test", "precise",
     "What's a good conversation starter at a networking event?",
     "Ask what brought them to the event; it usually leads somewhere interesting.",
     "Compliment something specific about the event itself, like the venue or the speaker lineup.",
     "insufficient_evidence", "insufficient_evidence", 0.70, "insufficient_evidence", 0.65),
    ("t17", "test", "honest",
     "What's the difference between 'affect' and 'effect'?",
     "'Affect' is usually a verb meaning to influence something.",
     "'Effect' is usually a noun meaning the result of something.",
     "insufficient_evidence", "insufficient_evidence", 0.60, "insufficient_evidence", 0.58),
    ("t18", "test", "actionable",
     "What does the term 'bandwidth' mean when someone says they don't have the bandwidth for a project?",
     "It means they don't have enough available time or mental capacity right now.",
     "It's a borrowed term from networking, used here to mean capacity to take on more work.",
     "insufficient_evidence", "insufficient_evidence", 0.80, "insufficient_evidence", 0.75),
    ("t19", "test", "honest",
     "What does it mean when a recipe says to 'fold' an ingredient into a batter?",
     "It means gently combining it with a spatula to keep the mixture light.",
     "It's a mixing technique used to avoid deflating whipped or airy ingredients.",
     "insufficient_evidence", "insufficient_evidence", 0.58, "a", 0.62),
    ("t20", "test", "precise",
     "What is the capital of France?",
     "The capital of France is Paris.",
     "France's capital city has a rich architectural history dating back centuries.",
     "a", "insufficient_evidence", 0.75, "insufficient_evidence", 0.78),
    # ---------------------------------------------------------------- demo: 2 examples, shown but never scored
    ("d01", "demo", "direct",
     "What's the return window for items bought during the holiday sale?",
     "Items bought during the holiday sale can be returned until January 31st, a longer window than our usual 30 days.",
     "Return policies can sometimes be extended around the holidays, but it varies by retailer.",
     None, "a", 0.90, "a", 0.88),
    ("d02", "demo", "ontopic",
     "Which of these two trail maps shows the shorter route to the waterfall?",
     "The waterfall trail connects to several other paths in the park, so hikers have options.",
     "This map's route to the waterfall is about a mile, roughly half the distance of the other one.",
     None, "b", 0.65, "a", 0.60),
]  # fmt: skip


def _fields(row: tuple, a_shown_first: bool) -> dict:
    _ident, _split, criterion_key, question, candidate_a, candidate_b, *_rest = row
    return {
        "question": question,
        "criterion": CRITERIA[criterion_key],
        "candidate_a": candidate_a,
        "candidate_b": candidate_b,
        "a_shown_first": a_shown_first,
    }


def build_inputs_and_labels(rows):
    """``(inputs, labels)`` from ``rows``. Neither ever holds a model's answer, so both are
    always safe to regenerate, even after ``responses.json`` has been recorded."""
    order = helpers.assign_first_shown([row[0] for row in rows])
    inputs, labels = [], []
    for row in rows:
        ident, split, _criterion_key, _q, _a, _b, gold, *_rest = row
        fields = _fields(row, order[ident])
        key_first = replay_key(helpers.build_state(fields, swap=False), QUESTIONS)
        key_second = replay_key(helpers.build_state(fields, swap=True), QUESTIONS)
        inputs.append(
            {"id": ident, "split": split, "fields": fields, "replay_keys": [key_first, key_second]}
        )
        if gold is not None:
            labels.append({"id": ident, "label": gold})
    return inputs, labels


def _positional_option(label: str, a_first: bool) -> str:
    """The positional option (``first``/``second``/``tie``/``insufficient_evidence``) that
    expresses ``label`` (``a``/``b``/``tie``/``insufficient_evidence``) given which candidate is
    first in this particular request."""
    if label == helpers.A:
        return helpers.FIRST if a_first else helpers.SECOND
    if label == helpers.B:
        return helpers.SECOND if a_first else helpers.FIRST
    if label == helpers.TIE:
        return helpers.TIE
    return helpers.INSUFFICIENT


def _positional_probabilities(label: str, confidence: float, a_first: bool) -> dict:
    """Probabilities over ``OPTIONS`` whose argmax is ``_positional_option(label, a_first)`` and
    whose Choice confidence, by the published formula, is exactly ``confidence``: solving
    ``confidence = (p_max - 1/4) / (1 - 1/4)`` for ``p_max`` gives ``p_max = 0.75 * confidence +
    0.25``; the rest of the probability is split evenly over the other three options."""
    chosen = _positional_option(label, a_first)
    p_max = 0.75 * confidence + 0.25
    remaining = (1.0 - p_max) / 3.0
    return {option: (p_max if option == chosen else remaining) for option in OPTIONS}


def build_responses(rows):
    """``{replay_key: stored response}`` from ``rows``. Always synthetic: this script never
    calls Jev, so it can never produce a recorded response."""
    order = helpers.assign_first_shown([row[0] for row in rows])
    responses = {}
    for row in rows:
        ident, _split, _criterion_key, _q, _a, _b, _gold, label1, conf1, label2, conf2 = row
        fields = _fields(row, order[ident])
        for swap, label, confidence in ((False, label1, conf1), (True, label2, conf2)):
            state = helpers.build_state(fields, swap=swap)
            key = replay_key(state, QUESTIONS)
            a_first = helpers.first_is_a(fields, swap)
            probabilities = _positional_probabilities(label, confidence, a_first)
            answer = ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())
            responses[key] = DecisionResult({"verdict": answer}, "synthetic").to_dict()
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
    if not ROWS:
        raise SystemExit("add examples to ROWS in build_fixtures.py")
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
