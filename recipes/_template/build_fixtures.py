"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for the template recipe.

    python build_fixtures.py        # from anywhere; it writes next to this file

Every response here is synthetic: written by hand as probabilities, not produced by a model.
Some are deliberately wrong, so the evaluation in the notebook has something to find. The
replay keys come from the same ``build_state`` and ``build_questions`` the notebook uses.
"""

import json
from pathlib import Path

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# (id, split, ticket, subject, message, gold label or None, stored probabilities)
# Probabilities are in the order billing, bug, account, none and sum to 1.
ROWS = [
    ("v01", "validation", "T-1001", "Charged twice", "I was charged twice for the same order.",
     "billing", (0.86, 0.05, 0.03, 0.06)),
    ("v02", "validation", "T-1002", "Export", "The export button does nothing when I click it.",
     "bug", (0.06, 0.84, 0.04, 0.06)),
    ("v03", "validation", "T-1003", "Locked out", "I cannot sign in and the reset email never comes.",
     "account", (0.04, 0.10, 0.79, 0.07)),
    ("v04", "validation", "T-1004", "Card on file", "Please update the card on file before the next renewal.",
     "billing", (0.81, 0.04, 0.09, 0.06)),
    ("v05", "validation", "T-1005", "Freezing", "The app freezes whenever I open the settings page.",
     "bug", (0.05, 0.88, 0.04, 0.03)),
    ("v06", "validation", "T-1006", "Profile", "How do I change the email address on my profile?",
     "account", (0.05, 0.06, 0.77, 0.12)),
    ("v07", "validation", "T-1007", "Opening hours", "What time does your office open on holidays?",
     "none", (0.10, 0.05, 0.10, 0.75)),
    ("v08-lookalike", "validation", "T-1008", "Invoice page", "My invoice page shows an error when I open it.",
     "bug", (0.46, 0.41, 0.06, 0.07)),
    ("v09", "validation", "T-1009", "Colours", "I love the new colour theme.",
     "none", (0.12, 0.18, 0.14, 0.56)),
    ("v10", "validation", "T-1010", "Refund policy", "Can you tell me about your refund policy for annual plans?",
     "billing", (0.28, 0.04, 0.06, 0.62)),
    ("t01", "test", "T-2001", "Higher charge", "The charge on my statement is higher than the quote.",
     "billing", (0.83, 0.06, 0.04, 0.07)),
    ("t02", "test", "T-2002", "Crash on upload", "The mobile app crashes when I upload a photo.",
     "bug", (0.04, 0.89, 0.03, 0.04)),
    ("t03", "test", "T-2003", "Too many attempts", "I am locked out after too many password attempts.",
     "account", (0.03, 0.09, 0.80, 0.08)),
    ("t04", "test", "T-2004", "Invoice copy", "Please send me a copy of last month's invoice.",
     "billing", (0.78, 0.05, 0.08, 0.09)),
    ("t05", "test", "T-2005", "Search", "Search returns an empty page for every query.",
     "bug", (0.07, 0.82, 0.04, 0.07)),
    ("t06", "test", "T-2006", "Second user", "How do I add a second user to my account?",
     "account", (0.05, 0.05, 0.76, 0.14)),
    ("t07", "test", "T-2007", "Baking", "Do you have a recipe for banana bread?",
     "none", (0.05, 0.04, 0.06, 0.85)),
    ("t08-lookalike", "test", "T-2008", "Invoices", "The page that lists my invoices will not load.",
     "bug", (0.52, 0.35, 0.06, 0.07)),
    ("t09-mixed", "test", "T-2009", "Closing account", "I need to close my account and stop all charges.",
     "account", (0.78, 0.02, 0.17, 0.03)),
    ("t10", "test", "T-2010", "Thanks", "Thanks, that was quick!",
     "none", (0.08, 0.06, 0.16, 0.70)),
    ("d01", "demo", "T-3001", "Wrong amount", "My invoice shows the wrong amount for March.",
     None, (0.80, 0.07, 0.05, 0.08)),
    ("d02", "demo", "T-3002", "Locked and charged", "I cannot sign in, and I think I was charged anyway.",
     None, (0.34, 0.06, 0.52, 0.08)),
]  # fmt: skip


def main() -> None:
    options = list(QUESTIONS["route"].criteria)
    inputs, labels, responses = [], [], {}
    for ident, split, ticket, subject, message, label, probs in ROWS:
        fields = {"ticket": ticket, "subject": subject, "message": message}
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if label is not None:
            labels.append({"id": ident, "label": label})
        answer = ChoiceAnswer.from_probabilities(
            dict(zip(options, probs, strict=True)), Provenance.synthetic()
        )
        responses[key] = DecisionResult({"route": answer}, "synthetic").to_dict()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\n" for row in rows)
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    text = json.dumps(responses, indent=2) + "\n"
    (folder / "responses.json").write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
