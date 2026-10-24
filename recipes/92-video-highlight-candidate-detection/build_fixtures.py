"""Author original illustrated clips and independently written event annotations.

All answer distributions are synthetic. ROWS defines visible scenarios and human-readable
labels separately from the three answer profiles. No image or answer comes from an API.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from jev_cookbook import DecisionResult, Provenance, ScoreAnswer, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()
PROFILES = {
    "zero": (0.96, 0.02, 0.01, 0.01),
    "one": (0.01, 0.96, 0.02, 0.01),
    "two": (0.01, 0.02, 0.96, 0.01),
    "three": (0.01, 0.01, 0.02, 0.96),
    "soft_three": (0.02, 0.03, 0.07, 0.88),
    "wrong_three": (0.08, 0.02, 0.10, 0.80),
    "uncertain": (0.20, 0.25, 0.35, 0.20),
}
# id, split, illustration scenario, event, visible event note, independent answer profiles
ROWS = [
    ("v01", "validation", "arms_up", True, "Both hands move above shoulders and stay there.", ("three", "zero", "zero")),
    ("v02", "validation", "victory", True, "A trophy and VICTORY card persist over the game.", ("zero", "zero", "three")),
    ("v03", "validation", "reveal", True, "The desk room is replaced by an outdoor stage.", ("zero", "three", "zero")),
    ("v04", "validation", "ordinary", False, "The seated person stays at the desk with arms down.", ("zero", "zero", "zero")),
    ("v05", "validation", "already_raised", False, "Both arms are already raised throughout; no new transition occurs.", ("zero", "zero", "zero")),
    ("v06", "validation", "camera_cut", False, "A reverse angle retains the same person, desk and room.", ("zero", "one", "zero")),
    ("v07", "validation", "flash", False, "One exposure flash returns to the original room.", ("zero", "two", "zero")),
    ("v08", "validation", "occluded", False, "A foreground panel prevents verifying a sustained posture.", ("uncertain", "uncertain", "zero")),
    ("v09", "validation", "brief_arms", False, "Both arms rise in the middle sample only, then drop.", ("two", "zero", "zero")),
    ("v10", "validation", "advert", False, "The trophy advert says SHOP; it is not a victory result.", ("zero", "zero", "wrong_three")),
    ("v11", "validation", "arms_up", True, "Both raised arms persist with a lower seated posture.", ("soft_three", "zero", "zero")),
    ("v12", "validation", "already_victory", False, "The victory card is already visible at the start; no new result appears.", ("zero", "zero", "zero")),
    ("t01", "test", "arms_up", True, "Both hands stay above shoulder height after rising.", ("three", "zero", "zero")),
    ("t02", "test", "victory", True, "A new trophy and VICTORY card persist.", ("zero", "zero", "three")),
    ("t03", "test", "reveal", True, "A persistent outdoor stage replaces the room.", ("zero", "three", "zero")),
    ("t04", "test", "ordinary", False, "Arms and desk display remain unchanged.", ("zero", "zero", "zero")),
    ("t05", "test", "camera_cut", False, "A camera cut shows the same room and desk from the other side.", ("zero", "one", "zero")),
    ("t06", "test", "flash", False, "A bright middle frame is a flash, not a persistent reveal.", ("zero", "two", "zero")),
    ("t07", "test", "occluded", False, "A passing panel hides the arms; the signal cannot be established.", ("uncertain", "zero", "zero")),
    ("t08", "test", "brief_victory", False, "The result card appears in one sample only.", ("zero", "zero", "two")),
    ("t09", "test", "advert", False, "A trophy SHOP advertisement is not a game result.", ("zero", "zero", "one")),
    ("t10", "test", "one_arm", False, "Only one hand rises; the two-arm transition is absent.", ("three", "zero", "zero")),
    ("t11", "test", "arms_up", True, "Both arms remain raised in the final two sampled frames.", ("zero", "zero", "zero")),
    ("t12", "test", "pause", False, "PAUSED is an ordinary game overlay, without a trophy.", ("zero", "zero", "zero")),
    ("d01", "demo", "arms_up", None, "Unscored posture demonstration.", ("three", "zero", "zero")),
    ("d02", "demo", "flash", None, "Unscored exposure-flash demonstration.", ("zero", "two", "zero")),
]  # fmt: skip


def person(draw, *, raised=False, one_arm=False, shift=0, small=False, variant=0):
    """Draw visible arms, hands, shoulders, face and desk; no emotion labels."""
    x, y = 240 + shift, 156 + (12 if small else 0)
    skin = (206 + variant % 25, 154 + variant % 18, 111 + variant % 20)
    shirt = (56 + variant % 60, 105, 151 + variant % 40)
    draw.ellipse((x - 34, y - 63, x + 34, y + 4), fill=skin, outline="#1E1E1E", width=3)
    draw.pieslice((x - 35, y - 68, x + 35, y - 10), 180, 355, fill="#44372C")
    for eye in (-13, 13):
        draw.ellipse((x + eye - 3, y - 36, x + eye + 3, y - 30), fill="#1E1E1E")
    draw.line((x - 11, y - 14, x + 11, y - 14), fill="#6A422D", width=2)
    draw.rounded_rectangle(
        (x - 38, y + 1, x + 38, y + 111), radius=18, fill=shirt, outline="#1E1E1E", width=3
    )
    for side in (-1, 1):
        up = raised or (one_arm and side == 1)
        shoulder = (x + 32 * side, y + 20)
        elbow = (x + 68 * side, y - 5 if up else y + 62)
        hand = (x + 96 * side, y - 61 if up else y + 82)
        draw.line((shoulder, elbow, hand), fill="#1E1E1E", width=19)
        draw.line((shoulder, elbow, hand), fill=shirt, width=13)
        draw.ellipse(
            (hand[0] - 10, hand[1] - 11, hand[0] + 10, hand[1] + 11),
            fill=skin,
            outline="#1E1E1E",
            width=2,
        )
    draw.rectangle((25, 271, 455, 293), fill="#A97B55", outline="#4C3729", width=3)
    draw.rectangle((58, 294, 75, 359), fill="#73533D")
    draw.rectangle((402, 294, 420, 359), fill="#73533D")
    draw.rounded_rectangle(
        (143, 239, 337, 276), radius=5, fill="#495461", outline="#1E1E1E", width=3
    )
    draw.rectangle((165, 248, 315, 262), fill="#A8BDCC")


def draw_frame(scenario, index, variant):
    image = Image.new("RGB", (480, 360), (230 + variant % 16, 224 + variant % 20, 216))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=24)
    game = scenario in {
        "victory",
        "brief_victory",
        "advert",
        "confetti",
        "pause",
        "already_victory",
    }
    if game:
        draw.rectangle((0, 0, 479, 359), fill=(24, 39 + variant % 30, 69))
        draw.rectangle((0, 250, 479, 359), fill="#496551")
        for x in (20, 180, 350):
            draw.polygon(((x, 250), (x + 55, 130), (x + 120, 250)), fill="#2C4B49")
        draw.rounded_rectangle((20, 16, 175, 44), radius=6, fill="#F2E6CD")
        draw.text((30, 20), "ROUND 3", fill="#1E1E1E", font=ImageFont.load_default(size=18))
        draw.ellipse((78 + index * 5, 208, 110 + index * 5, 240), fill="#F386A1")
        draw.rectangle((85 + index * 5, 236, 108 + index * 5, 286), fill="#F386A1")
        active = scenario == "already_victory" or (
            index >= 2 and (scenario != "brief_victory" or index == 2)
        )
        if active and scenario in {
            "victory",
            "brief_victory",
            "advert",
            "pause",
            "already_victory",
        }:
            draw.rounded_rectangle(
                (130, 63, 375, 265), radius=12, fill="#FEFEFE", outline="#E8A33D", width=5
            )
            text = (
                "SHOP" if scenario == "advert" else "PAUSED" if scenario == "pause" else "VICTORY"
            )
            draw.text((181 if text == "SHOP" else 163, 216), text, fill="#1E1E1E", font=font)
            if scenario != "pause":
                draw.arc((161, 91, 228, 157), 60, 285, fill="#C38F23", width=8)
                draw.arc((279, 91, 346, 157), 250, 120, fill="#C38F23", width=8)
                draw.polygon(
                    ((207, 89), (303, 89), (290, 151), (272, 166), (240, 166), (220, 151)),
                    fill="#E8B53D",
                    outline="#8C6416",
                )
                draw.rectangle((247, 161, 263, 187), fill="#C38F23")
                draw.rectangle((224, 187, 289, 199), fill="#C38F23")
        if active and scenario in {"victory", "confetti"}:
            for k in range(28):
                x = (k * 53 + variant * 17) % 470
                y = (k * 31) % 220 + 50
                draw.rectangle((x, y, x + 5, y + 8), fill=("#F386A1", "#E8A33D", "#FEFEFE")[k % 3])
    elif scenario == "reveal" and index >= 2:
        shift = (variant % 5) * 7
        draw.rectangle((0, 0, 479, 260), fill=(140 + variant, 192 + variant, 218))
        draw.ellipse((350 + shift, 22, 412 + shift, 84), fill="#F5D36C")
        draw.polygon(((0, 260), (100 + shift, 120), (230, 260)), fill="#688C86")
        draw.polygon(((200, 260), (350 + shift, 128), (480, 260)), fill="#759C79")
        draw.rectangle((0, 260, 479, 359), fill=(60 + variant, 104 + variant, 84))
        draw.rectangle(
            (65 + shift, 276, 415 - shift, 316),
            fill=(155 + variant, 115 + variant, 81),
            outline="#1E1E1E",
            width=3,
        )
        draw.line((105, 276, 105, 140, 375, 140, 375, 276), fill="#72553C", width=9)
        draw.polygon(((110, 144), (148, 144), (129, 177)), fill="#F386A1")
        draw.polygon(((203, 144), (241, 144), (222, 177)), fill="#E8A33D")
        draw.polygon(((298, 144), (336, 144), (317, 177)), fill="#F386A1")
    else:
        cut = scenario == "camera_cut" and index >= 2
        if cut:
            draw.rectangle((0, 0, 479, 270), fill="#9AA9B6")
        shift = 45 if cut else 0
        window_x = 320 if cut else 24
        draw.rectangle(
            (window_x, 23, window_x + 110, 134), fill="#91BACD", outline="#FEFEFE", width=8
        )
        draw.line((window_x + 55, 24, window_x + 55, 134), fill="#FEFEFE", width=5)
        draw.line((window_x, 79, window_x + 110, 79), fill="#FEFEFE", width=5)
        draw.rectangle((344 if not cut else 20, 172, 447 if not cut else 112, 180), fill="#A97B55")
        for j in range(5):
            bx = (350 if not cut else 25) + j * 14
            draw.rectangle(
                (bx, 130 + j % 2 * 5, bx + 10, 171), fill=("#F386A1", "#1F78A8", "#E8A33D")[j % 3]
            )
        raised = (
            scenario == "already_raised"
            or (scenario == "arms_up" and index >= 2)
            or (scenario == "brief_arms" and index == 2)
        )
        person(
            draw,
            raised=raised,
            one_arm=scenario == "one_arm" and index >= 2,
            shift=shift,
            small=variant in (10, 22),
            variant=variant,
        )
        if scenario == "occluded" and index >= 2:
            draw.rounded_rectangle(
                (100, 53, 385, 258), radius=12, fill="#B9B8B5", outline="#71706E", width=5
            )
            draw.line((125, 80, 360, 230), fill="#94938E", width=6)
        if scenario == "flash" and index == 2:
            image = ImageEnhance.Brightness(image).enhance(1.9)
    return image


def fields_for(index):
    start = float(index * 4)
    return {
        "frames": [
            {"timestamp_seconds": start + offset, "path": f"assets/clip-{index:02d}-frame-{j}.png"}
            for j, offset in enumerate((0.0, 0.45, 0.95, 1.55, 2.05))
        ]
    }


def build_assets(rows):
    (HERE / "assets").mkdir(exist_ok=True)
    for index, row in enumerate(rows):
        for frame in range(5):
            draw_frame(row[2], frame, index).save(HERE / fields_for(index)["frames"][frame]["path"])


def build_inputs_and_labels(rows):
    build_assets(rows)
    inputs, labels = [], []
    for index, (ident, split, scenario, event, note, _profiles) in enumerate(rows):
        fields = fields_for(index)
        state, questions, assets = helpers.request(fields)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if event is not None:
            labels.append(
                {
                    "id": ident,
                    "label": {
                        "event": "candidate" if event else "none_suitable",
                        "signal": {
                            "arms_up": "reaction",
                            "reveal": "scene_change",
                            "victory": "victory",
                        }.get(scenario)
                        if event
                        else None,
                        "event_interval": [index * 4 + 0.95, index * 4 + 2.05] if event else None,
                        "annotation": note,
                    },
                }
            )
    return inputs, labels


def build_responses(rows):
    responses = {}
    for index, row in enumerate(rows):
        state, questions, assets = helpers.request(fields_for(index))
        answers = {
            name: ScoreAnswer.from_probabilities(
                PROFILES[profile], questions[name].criteria, Provenance.synthetic()
            )
            for name, profile in zip(helpers.SIGNALS, row[-1], strict=True)
        }
        responses[replay_key(state, questions, assets=assets)] = DecisionResult(
            answers, "synthetic"
        ).to_dict()
    return responses


def protected_responses(path):
    """Only a fully valid, entirely synthetic response mapping is safe to regenerate."""
    if not path.exists():
        return False
    try:
        stored = json.loads(path.read_text("utf-8"))
        if not isinstance(stored, dict) or not stored:
            return True
        return any(
            DecisionResult.from_dict(value).source != "synthetic" for value in stored.values()
        )
    except (ValueError, TypeError, KeyError, AttributeError, OSError, UnicodeError):
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="replace recorded responses explicitly"
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, data in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text(
            "".join(json.dumps(row) + "\n" for row in data), encoding="utf-8"
        )
    path = folder / "responses.json"
    if not args.force and protected_responses(path):
        raise SystemExit(
            "refusing to overwrite recorded or malformed responses; inputs and labels rebuilt; use --force explicitly"
        )
    data = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(data.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {len(inputs)} windows, {len(labels)} labels, {len(data)} responses and {5 * len(inputs)} frames"
    )


if __name__ == "__main__":
    main()
