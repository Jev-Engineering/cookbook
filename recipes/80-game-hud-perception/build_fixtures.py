"""Regenerate original mock-HUD images and synthetic responses; never calls a model."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import (
    BoxAnswer,
    ChoiceAnswer,
    DecisionResult,
    Provenance,
    load_helpers,
    replay_key,
)

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
REFLOW = {
    "energy_meter": (510, 90, 600, 170),
    "card": (55, 210, 175, 332),
    "action_button": (420, 225, 560, 281),
    "enemy_indicator": (245, 110, 383, 175),
}


def row(
    ident,
    split,
    target,
    *,
    phase="combat",
    layout="fixed",
    condition="visible",
    energy=2,
    box_confidence=0.96,
    wrong_box=False,
    wrong_phase=False,
):
    return dict(
        id=ident,
        split=split,
        target=target,
        phase=phase,
        layout=layout,
        condition=condition,
        energy=energy,
        box_confidence=box_confidence,
        wrong_box=wrong_box,
        wrong_phase=wrong_phase,
    )


ROWS = [
    row("v01", "validation", "energy_meter"),
    row("v02", "validation", "card", layout="reflow"),
    row("v03", "validation", "action_button", phase="menu"),
    row("v04", "validation", "energy_meter", condition="hidden"),
    row("v05", "validation", "enemy_indicator", condition="occluded"),
    row("v06", "validation", "action_button", condition="disabled"),
    row("v07", "validation", "card", condition="distractor", wrong_box=True, box_confidence=0.67),
    row("v08", "validation", "enemy_indicator", layout="reflow", box_confidence=0.83),
    row("t01", "test", "energy_meter", layout="reflow", energy=3),
    row("t02", "test", "card"),
    row("t03", "test", "action_button", layout="reflow"),
    row(
        "t04",
        "test",
        "enemy_indicator",
        condition="distractor",
        wrong_box=True,
        box_confidence=0.99,
    ),
    row("t05", "test", "energy_meter", condition="hidden", layout="reflow"),
    row("t06", "test", "card", condition="occluded", layout="reflow"),
    row("t07", "test", "action_button", phase="reward"),
    row("t08", "test", "card", condition="disabled"),
    row("t09", "test", "enemy_indicator", phase="ambiguous"),
    row("t10", "test", "energy_meter", energy=1, box_confidence=None),
    row("t11", "test", "action_button", phase="reward", layout="reflow", wrong_phase=True),
    row("t12", "test", "enemy_indicator"),
    row("d01", "demo", "energy_meter", layout="reflow", energy=1),
]


def target_bounds(spec):
    return (REFLOW if spec["layout"] == "reflow" else helpers.FIXED_PIXELS)[spec["target"]]


def distractor_bounds(spec):
    left, top, right, bottom = target_bounds(spec)
    return left - 62, top - 28, right - 62, bottom - 28


def gold_for(spec):
    condition, target = spec["condition"], spec["target"]
    presence = (
        "absent"
        if condition == "hidden"
        else ("uncertain" if condition == "occluded" else "visible")
    )
    enabled = (
        "not_applicable"
        if target in ("energy_meter", "enemy_indicator") or condition == "hidden"
        else "uncertain"
        if condition == "occluded"
        else "disabled"
        if condition == "disabled"
        else "enabled"
    )
    if spec["phase"] == "ambiguous" or presence == "uncertain":
        event = "review"
    elif spec["phase"] != "combat" or presence == "absent" or enabled == "disabled":
        event = "no_action"
    else:
        event = helpers.EVENTS[target]
    return {
        "phase": spec["phase"],
        "presence": presence,
        "enabled": enabled,
        "box": helpers.pixel_box(target_bounds(spec)) if presence == "visible" else None,
        "energy": spec["energy"] if target == "energy_meter" and presence == "visible" else None,
        "event": event,
    }


def draw_panel(draw, target, bounds, *, energy=2, disabled=False, decoy=False):
    left, top, right, bottom = bounds
    color = helpers.DISABLED_COLOR if disabled else helpers.TARGET_COLORS[target]
    draw.rectangle((left, top, right - 1, bottom - 1), fill=color, outline="#FEFEFE", width=2)
    small = ImageFont.load_default(size=14)
    title = ImageFont.load_default(size=17)
    names = {
        "energy_meter": "ENERGY",
        "card": "SPARK",
        "action_button": "END TURN",
        "enemy_indicator": "ENEMY",
    }
    name = "DECOY" if decoy else names[target]
    if decoy and target == "enemy_indicator":
        name = "STATUS"
    draw.text((left + 8, top + 8), name, font=title, fill="#FEFEFE")
    if target == "energy_meter":
        draw.text((left + 36, top + 29), str(energy), font=title, fill="#FEFEFE")
        for index in range(3):
            x = left + 10 + index * 22
            draw.rectangle(
                (x, top + 53, x + 12, top + 66), fill="#FEFEFE" if index < energy else "#1E1E1E"
            )
    elif target == "card":
        draw.polygon(
            [
                (left + 60, top + 40),
                (left + 35, top + 76),
                (left + 70, top + 68),
                (left + 48, top + 94),
            ],
            fill="#1E1E1E",
        )
        draw.text((left + 8, bottom - 22), "COST 1", font=small, fill="#1E1E1E")
    elif target == "enemy_indicator":
        draw.text((left + 8, top + 35), "intent: defend", font=small, fill="#FEFEFE")
    if disabled:
        draw.line((left + 5, bottom - 7, right - 6, top + 6), fill="#1E1E1E", width=4)


def render(spec, index):
    """Original deterministic test art; not a game screenshot or extracted game asset."""
    image = Image.new("RGB", (helpers.WIDTH, helpers.HEIGHT), "#202A35")
    draw = ImageDraw.Draw(image)
    title = ImageFont.load_default(size=20)
    small = ImageFont.load_default(size=13)
    phase = spec["phase"]
    if phase == "ambiguous":
        draw.rectangle((20, 20, 319, 64), fill=helpers.PHASE_COLORS["combat"])
        draw.rectangle((320, 20, 619, 64), fill=helpers.PHASE_COLORS["reward"])
        heading = "COMBAT / REWARD ..."
    else:
        draw.rectangle((20, 20, 619, 64), fill=helpers.PHASE_COLORS[phase])
        heading = {"combat": "COMBAT", "menu": "PAUSED - MENU", "reward": "VICTORY - REWARD"}[phase]
    draw.text((35, 31), heading, font=title, fill="#FEFEFE")
    draw.line((25, 225, 615, 225), fill="#40505D", width=2)
    # Decorative variation makes every capture distinct, without exposing its id or split.
    draw.polygon([(215, 204), (239 + index % 11, 145), (263, 204)], fill="#526879")
    draw.ellipse((377, 170, 409 + index % 7, 210), fill="#68747B")
    for i in range(4):
        x = 30 + i * 43
        draw.line((x, 84, x + 16 + (index * (i + 1)) % 17, 84), fill="#73818C", width=3)
    layout = REFLOW if spec["layout"] == "reflow" else helpers.FIXED_PIXELS
    for target, bounds in layout.items():
        condition = spec["condition"] if target == spec["target"] else "visible"
        if condition == "hidden":
            continue
        if condition == "distractor":
            draw_panel(draw, target, distractor_bounds(spec), decoy=True)
        draw_panel(draw, target, bounds, energy=spec["energy"], disabled=condition == "disabled")
        if condition == "occluded":
            left, top, right, bottom = bounds
            draw.rectangle((left + 24, top - 8, right + 14, bottom + 8), fill="#DEDEDE")
            draw.text((left + 35, top + 12), "?", font=title, fill="#1E1E1E")
    draw.text(
        (20, 381), "SYNTHETIC HUD / ORIGINAL SHAPES / NO GAME CONNECTED", font=small, fill="#DEDEDE"
    )
    return image


def fields_for(spec, index):
    return {"image": f"assets/panel-{index + 1:02d}.png", "target": spec["target"]}


def write_assets(rows, recipe_dir=HERE):
    folder = Path(recipe_dir) / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    for index, spec in enumerate(rows):
        render(spec, index).save(Path(recipe_dir) / fields_for(spec, index)["image"])


def choice(option, criteria, peak=0.97):
    probabilities = {key: (1 - peak) / (len(criteria) - 1) for key in criteria}
    probabilities[option] = peak
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def first_response(spec):
    gold = gold_for(spec)
    return DecisionResult(
        {
            "phase": choice("combat" if spec["wrong_phase"] else gold["phase"], helpers.PHASES),
            "presence": choice(gold["presence"], helpers.PRESENCE),
            "enabled": choice(gold["enabled"], helpers.ENABLED),
        },
        "synthetic",
    )


def requests_for(spec, index, recipe_dir=HERE):
    fields = fields_for(spec, index)
    state, assets, _ = helpers.prepare(fields, recipe_dir)
    first = first_response(spec)
    requests = [(replay_key(state, helpers.build_questions(), assets=assets), first)]
    # The lowest candidate is the superset of requests used by validation selection.
    outcome, _ = helpers.gate_first(first, spec["target"], helpers.Policy(0.55))
    if outcome == "localize":
        bounds = distractor_bounds(spec) if spec["wrong_box"] else target_bounds(spec)
        answers = {
            "target_box": BoxAnswer(
                box=helpers.pixel_box(bounds),
                confidence=spec["box_confidence"],
                provenance=Provenance.synthetic(),
            )
        }
        if spec["target"] == "energy_meter":
            answers["energy"] = choice(str(spec["energy"]), helpers.ENERGY)
        questions = helpers.localization_questions(spec["target"])
        requests.append(
            (replay_key(state, questions, assets=assets), DecisionResult(answers, "synthetic"))
        )
    return requests


def build_inputs_and_labels(rows, recipe_dir=HERE):
    inputs, labels = [], []
    for index, spec in enumerate(rows):
        inputs.append(
            {
                "id": spec["id"],
                "split": spec["split"],
                "fields": fields_for(spec, index),
                "replay_keys": [key for key, _ in requests_for(spec, index, recipe_dir)],
            }
        )
        if spec["split"] != "demo":
            labels.append({"id": spec["id"], "label": gold_for(spec)})
    return inputs, labels


def build_responses(rows, recipe_dir=HERE):
    return {
        key: result.to_dict()
        for index, spec in enumerate(rows)
        for key, result in requests_for(spec, index, recipe_dir)
    }


def protected_response_file(path):
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    return not isinstance(data, dict) or any(
        not isinstance(entry, dict)
        or entry.get("model") != "synthetic"
        or any(
            answer.get("provenance", {}).get("source") != "synthetic"
            for answer in entry.get("answers", {}).values()
        )
        for entry in data.values()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="explicitly replace recorded responses with synthetic fixtures",
    )
    args = parser.parse_args()
    write_assets(ROWS)
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
        )
    path = folder / "responses.json"
    if protected_response_file(path) and not args.force:
        raise SystemExit(
            "refusing to overwrite recorded or invalid responses without --force; "
            "assets, inputs and labels were regenerated; record any missing request keys"
        )
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(inputs)} images/examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
