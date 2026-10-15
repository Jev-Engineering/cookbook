"""Author screenshots and deliberately imperfect synthetic responses; never calls a model."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, visual scenario, variant, gold, synthetic winner, winner probability.
# Visual scenarios and gold stay in this authoring file, never in inference state.
ROWS = [
    ("v01", "validation", "dashboard", 1, "normal", "normal", 0.94),
    ("v02", "validation", "login", 2, "normal", "normal", 0.86),
    ("v03", "validation", "auth_red", 3, "authentication_failure", "authentication_failure", 0.93),
    ("v04", "validation", "spinner", 4, "loading", "loading", 0.91),
    ("v05", "validation", "crash", 5, "crash", "crash", 0.96),
    ("v06", "validation", "empty", 6, "normal", "normal", 0.82),
    ("v07", "validation", "promotion", 7, "normal", "crash", 0.56),
    ("v08", "validation", "auth_muted", 8, "authentication_failure", "normal", 0.61),
    ("v09", "validation", "skeleton", 9, "loading", "loading", 0.84),
    ("v10", "validation", "crop", 10, "uncertain", "uncertain", 0.93),
    ("v11", "validation", "blur", 11, "uncertain", "normal", 0.48),
    ("v12", "validation", "help", 12, "normal", "normal", 0.79),
    ("t01", "test", "dashboard", 21, "normal", "normal", 0.92),
    ("t02", "test", "login", 22, "normal", "normal", 0.89),
    ("t03", "test", "auth_red", 23, "authentication_failure", "authentication_failure", 0.95),
    ("t04", "test", "spinner", 24, "loading", "loading", 0.90),
    ("t05", "test", "crash", 25, "crash", "crash", 0.95),
    ("t06", "test", "empty", 26, "normal", "loading", 0.87),
    ("t07", "test", "promotion", 27, "normal", "normal", 0.83),
    ("t08", "test", "auth_muted", 28, "authentication_failure", "authentication_failure", 0.62),
    ("t09", "test", "skeleton", 29, "loading", "loading", 0.86),
    ("t10", "test", "crop", 30, "uncertain", "uncertain", 0.94),
    ("t11", "test", "blur", 31, "uncertain", "uncertain", 0.51),
    ("t12", "test", "help", 32, "normal", "normal", 0.81),
    ("d01", "demo", "login", 41, None, "normal", 0.90),
    ("d02", "demo", "auth_red", 42, None, "authentication_failure", 0.93),
    ("d03", "demo", "empty", 43, None, "normal", 0.82),
    ("d04", "demo", "spinner", 44, None, "loading", 0.92),
    ("d05", "demo", "crash", 45, None, "crash", 0.94),
    ("d06", "demo", "promotion", 46, None, "normal", 0.75),
]  # fmt: skip

INK = "#24304A"
MUTED = "#68758C"
BLUE = "#3969D8"
RED = "#CA3C49"


def font(size):
    """Pillow's embedded font avoids a dependency on workstation font paths."""
    return ImageFont.load_default(size=size)


def draw_screen(kind, variant):
    """Plausible application UI pixels, including real visible text and controls."""
    image = Image.new("RGB", (640, 440), "#F3F5FA")
    draw = ImageDraw.Draw(image)

    def text(x, y, value, size=15, color=INK):
        draw.text((x, y), value, fill=color, font=font(size))

    def panel(bounds, fill="white", outline=None, radius=10):
        draw.rounded_rectangle(bounds, radius=radius, fill=fill, outline=outline)

    def button(bounds, label, fill=BLUE):
        panel(bounds, fill)
        text(bounds[0] + 13, bounds[1] + 10, label, 14, "white")

    workspace = ("Studio", "Research", "Planning")[variant % 3]
    draw.rectangle((0, 0, 639, 34), fill="#E2E7F0")
    for x, color in [(16, "#D97E87"), (32, "#E2BA65"), (48, "#80B8A7")]:
        draw.ellipse((x, 12, x + 7, 19), fill=color)
    panel((166, 6, 533, 28), "#F8FAFD", radius=5)
    text(184, 10, "app.example.test / workspace", 12, MUTED)
    draw.rectangle((0, 35, 156, 439), fill="#25344C")
    text(19, 56, "NORTHSTAR", 17, "white")
    text(19, 85, workspace + " workspace", 12, "#A7B6CC")
    for i, label in enumerate(("Overview", "Inbox", "Projects", "Reports", "Settings")):
        if i == variant % 3:
            panel((12, 123 + i * 42, 145, 155 + i * 42), "#3D506F", radius=5)
        draw.rectangle((23, 136 + i * 42, 31, 144 + i * 42), outline="#9AAEC8")
        text(42, 131 + i * 42, label, 14, "#E7ECF4")
    text(18, 409, "Help & shortcuts", 12, "#B3C1D6")
    text(180, 54, workspace, 22)
    text(180, 82, f"Workspace activity / view {variant}", 12, MUTED)
    draw.ellipse((593, 50, 620, 77), fill="#D9E5F8")
    text(601, 56, "S", 14, BLUE)
    panel((177, 113, 620, 416))

    if kind in ("login", "auth_red", "auth_muted"):
        text(280, 131, "Sign in to continue", 23)
        text(278, 163, "Use your workspace account", 13, MUTED)
        text(228, 198, "Email address", 13)
        panel((226, 219, 572, 254), "#FAFBFE", "#CCD4E2", 5)
        text(239, 229, "person@example.test", 14, MUTED)
        text(228, 265, "Password", 13)
        panel(
            (226, 285, 572, 320),
            "#FAFBFE",
            RED if kind == "auth_red" else "#CCD4E2",
            5,
        )
        text(239, 296, "********", 14, MUTED)
        button((226, 364, 572, 401), "Sign in")
        if kind == "auth_red":
            text(229, 333, "Incorrect password. Please try again.", 14, RED)
        elif kind == "auth_muted":
            text(229, 333, "Session expired. Sign in again.", 14, MUTED)
        else:
            text(229, 333, "Forgot your password?", 14, BLUE)
    elif kind == "spinner":
        draw.arc((369, 172, 411, 214), 30, 300, fill=BLUE, width=5)
        text(296, 238, "Preparing your workspace", 18)
        text(291, 270, "Retrieving the latest changes...", 13, MUTED)
        panel((264, 306, 520, 312), "#E5EAF3", radius=3)
        panel((264, 306, 340 + variant % 60, 312), BLUE, radius=3)
    elif kind == "skeleton":
        text(199, 135, "Recent activity", 18)
        for y in (185, 250, 315):
            panel((201, y, 238, y + 37), "#DFE5EF", radius=6)
            panel((252, y, 556, y + 10), "#DFE5EF", radius=5)
            panel((252, y + 22, 463, y + 31), "#EBEFF5", radius=4)
        text(201, 382, "Syncing changes...", 13, MUTED)
    elif kind == "empty":
        draw.rounded_rectangle((365, 178, 417, 219), radius=5, outline="#A7B7CF", width=2)
        draw.line((366, 193, 378, 207, 403, 207, 416, 193), fill="#A7B7CF", width=2)
        text(313, 245, "You're all caught up", 20)
        text(271, 277, "New updates will appear in your inbox.", 13, MUTED)
        button((330, 321, 461, 360), "View projects")
    elif kind == "help":
        text(198, 134, "Troubleshooting guide", 21)
        text(198, 173, "Example messages you might encounter", 13, MUTED)
        panel((195, 209, 601, 310), "#F2F5FA", radius=6)
        text(209, 224, '"Application crashed" means reload the page.', 14)
        text(209, 253, '"Incorrect password" means check your login.', 14)
        text(209, 282, "These are examples, not current alerts.", 13, MUTED)
        text(198, 337, "Article feedback", 15)
        button((198, 365, 300, 403), "Helpful")
    else:
        text(198, 135, "Project overview", 20)
        for i, label in enumerate(("Design review", "Sprint notes", "Launch checklist")):
            y = 181 + i * 64
            panel((198, y, 599, y + 46), "#F6F8FC", radius=6)
            draw.ellipse((213, y + 16, 226, y + 29), fill="#71A892")
            text(240, y + 13, label, 15)
            text(511, y + 16, f"{variant + i} items", 12, MUTED)
        text(198, 389, "All changes saved", 12, MUTED)

    if kind in ("crash", "promotion"):
        image = Image.blend(image, Image.new("RGB", image.size, "#0B1324"), 0.57)
        draw = ImageDraw.Draw(image)
        panel((202, 138, 592, 351), "white", radius=12)
        draw.ellipse((229, 160, 268, 199), fill="#FAE6E9")
        text(244, 169, "!" if kind == "crash" else "+", 23, RED)
        if kind == "crash":
            text(284, 166, "Something went wrong", 21)
            text(228, 217, "The application stopped unexpectedly.", 15)
            text(228, 245, "Reload to restore this workspace.", 14, MUTED)
            button((228, 290, 356, 329), "Reload app")
            text(380, 302, "Copy error details", 13, MUTED)
        else:
            text(284, 166, "Meet the new workspace", 21)
            text(228, 217, "Try our updated project templates.", 15)
            text(228, 245, "Your work is saved and ready.", 14, MUTED)
            button((228, 290, 356, 329), "Take a tour")
            text(386, 302, "Maybe later", 13, MUTED)
    if kind == "crop":
        # The surviving pixels show part of a card; no current-state evidence survives.
        image = image.crop((445, 188, 530, 247)).resize((640, 440))
    elif kind == "blur":
        image = image.resize((32, 22)).resize((640, 440)).filter(ImageFilter.GaussianBlur(7))
    return image


def write_assets(rows):
    (HERE / "assets").mkdir(exist_ok=True)
    for ident, _split, scenario, variant, *_rest in rows:
        draw_screen(scenario, variant).save(HERE / "assets" / f"{ident}.png")


def build_inputs_and_labels(rows):
    inputs, labels = [], []
    for ident, split, _scenario, _variant, gold, *_rest in rows:
        fields = {"image": f"assets/{ident}.png"}
        state, assets = helpers.build_state(fields, HERE)
        key = replay_key(state, helpers.build_questions(), assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if gold is not None:
            labels.append({"id": ident, "label": gold})
    return inputs, labels


def build_responses(rows):
    responses = {}
    for ident, _split, _scenario, _variant, _gold, winner, probability in rows:
        state, assets = helpers.build_state({"image": f"assets/{ident}.png"}, HERE)
        probabilities = {
            option: probability if option == winner else (1 - probability) / 4
            for option in helpers.OPTIONS
        }
        answer = ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())
        key = replay_key(state, helpers.build_questions(), assets=assets)
        responses[key] = DecisionResult({"screen_state": answer}, "synthetic").to_dict()
    return responses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    target = folder / "responses.json"
    recorded = False
    if target.exists():
        existing = json.loads(target.read_text("utf-8"))
        recorded = any(entry.get("model") != "synthetic" for entry in existing.values())
    # Preserve the exact image bytes underpinning any recorded answers on a refused run.
    # Inputs/labels still follow the scaffold contract and rebuild against preserved assets.
    if not recorded or args.force:
        write_assets(ROWS)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
        )
    if recorded and not args.force:
        raise SystemExit(
            "refusing to overwrite recorded responses; use --force explicitly. "
            "Inputs and labels were regenerated; recorded responses and image bytes preserved."
        )
    responses = build_responses(ROWS)
    target.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(inputs)} screenshots, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
