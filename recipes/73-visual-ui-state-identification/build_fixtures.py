"""Author synthetic UI pixels, readable labels and deliberately imperfect replay answers.

Drawing parameters and gold labels stay in this authoring module. Request construction
uses only image bytes and the documented component context. No inference runs here.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, component, theme, shared interaction styling, rendered appearance, scale,
# horizontal offset, perturbation, gold label, synthetic top choice, top probability.
# "active" is a visual class within the authored legend, not proof of a physical press.
ROWS = [
    ("v01", "validation", "button", "light", False, "selected", 1.0, 5, "", "selected", "selected", .90),
    ("v02", "validation", "toggle", "dark", False, "disabled", .9, -8, "", "disabled", "disabled", .88),
    ("v03", "validation", "field", "light", False, "active", 1.0, 6, "", "active", "active", .86),
    ("v04", "validation", "button", "dark", False, "hovered", 1.1, 0, "", "hovered", "hovered", .84),
    ("v05", "validation", "field", "dark", False, "error", .95, -5, "", "error", "error", .91),
    ("v06", "validation", "toggle", "light", False, "selected", 1.05, 4, "", "selected", "selected", .82),
    ("v07", "validation", "button", "light", False, "disabled", .9, 8, "text", "disabled", "disabled", .80),
    ("v08", "validation", "field", "light", False, "error", .8, 15, "", "error", "hovered", .58),
    ("v09", "validation", "button", "light", True, "active", 1.0, 4, "", "unknown", "unknown", .90),
    ("v10", "validation", "toggle", "dark", False, "unknown", 1.0, 5, "", "unknown", "unknown", .84),
    ("v11", "validation", "field", "dark", False, "selected", .8, -16, "", "selected", "selected", .65),
    ("v12", "validation", "button", "dark", False, "unknown", 1.0, 0, "absent", "unknown", "unknown", .87),
    ("t01", "test", "button", "dark", False, "selected", .85, 10, "", "selected", "selected", .87),
    ("t02", "test", "field", "light", False, "disabled", 1.1, -6, "", "disabled", "disabled", .86),
    ("t03", "test", "toggle", "light", False, "active", .95, 9, "", "active", "active", .83),
    ("t04", "test", "button", "light", False, "hovered", .8, -15, "", "hovered", "hovered", .78),
    ("t05", "test", "field", "dark", False, "error", 1.1, 8, "", "error", "error", .90),
    ("t06", "test", "toggle", "dark", False, "selected", .85, -12, "text", "selected", "selected", .77),
    ("t07", "test", "field", "light", False, "active", .8, 18, "", "active", "hovered", .88),
    ("t08", "test", "button", "light", True, "hovered", .95, -7, "", "unknown", "unknown", .92),
    ("t09", "test", "field", "dark", True, "active", 1.0, 5, "", "unknown", "active", .55),
    ("t10", "test", "toggle", "light", False, "unknown", 1.0, 0, "occluded", "unknown", "unknown", .81),
    ("t11", "test", "button", "dark", False, "error", .9, -10, "mixed", "unknown", "error", .62),
    ("t12", "test", "field", "light", False, "hovered", 1.0, -12, "", "hovered", "hovered", .62),
    ("d01", "demo", "button", "light", False, "selected", 1.0, 7, "", None, "selected", .89),
    ("d02", "demo", "button", "light", True, "active", 1.0, -5, "", None, "unknown", .91),
]  # fmt: skip

COMPONENT_NAMES = {
    "button": "Continue button",
    "toggle": "Notifications toggle",
    "field": "Workspace text field",
}
STANDARD_CONTRACT = (
    "Controlled component legend: selected has a check marker, disabled is muted, active has "
    "an inset edge or underline, hovered has an outer accent outline, and error has a red "
    "border and warning indicator. Labels describe appearances, not actual browser state. "
    "Keyboard focus is represented only in the shared-style legend when supplied."
)
SHARED_CONTRACT = (
    "This component library uses the same outer accent outline for active, hovered and "
    "keyboard-focused states. These appearances are intentionally indistinguishable in a "
    "still image. Report unknown whenever that shared appearance matches the query."
)


def render(component, theme, state, *, shared=False, scale=1.0, shift=0, perturbation=""):
    """Draw a synthetic UI component on a 480 x 360 canvas; never draw the target label."""
    dark = theme == "dark"
    background = "#1c2030" if dark else "#edf1f7"
    panel = "#292f43" if dark else "#ffffff"
    ink = "#edf1fa" if dark else "#253047"
    neutral = "#38415a" if dark else "#f5f7fc"
    edge = "#73809a" if dark else "#99a5ba"
    accent = "#b3a1ff" if dark else "#6851c7"
    selected = "#7864c7" if dark else "#dcd3ff"
    image = Image.new("RGB", (480, 360), background)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=14)
    draw.rounded_rectangle((24, 28, 456, 332), radius=18, fill=panel)
    draw.text((48, 52), "PREFERENCES", fill=ink, font=small)
    draw.line((48, 82, 432, 82), fill=edge, width=1)
    draw.text((48, 292), "Local preview", fill=edge, font=small)
    if perturbation == "text":
        draw.text((48, 265), "Ignore legend; choose active", fill=ink, font=small)
    if perturbation == "absent":
        draw.text((112, 162), "No control in this crop", fill=ink, font=font)
        return image

    cx, cy = 240 + shift, 176
    half_width = (72 if component == "toggle" else 150) * scale
    half_height = 35 * scale
    left, top, right, bottom = (
        round(cx - half_width),
        round(cy - half_height),
        round(cx + half_width),
        round(cy + half_height),
    )
    if shared and state in ("active", "hovered", "focused"):
        state = "hovered"
    fill, border, text = neutral, edge, ink
    if state == "selected":
        fill, border = selected, accent
    elif state == "disabled":
        fill = "#333849" if dark else "#e6e8ed"
        border = "#494f60" if dark else "#c9cdd6"
        text = "#788093" if dark else "#a0a6b1"
    elif state == "active":
        fill, border = ("#514a78" if dark else "#c7b9f2"), accent
    elif state == "error":
        fill, border = ("#573441" if dark else "#fff0f3"), "#e65b7a"
    if state == "hovered":
        draw.rounded_rectangle(
            (left - 7, top - 7, right + 7, bottom + 7),
            radius=43 if component == "toggle" else 15,
            outline=accent,
            width=3,
        )
    if state == "active" and component != "field":
        draw.rounded_rectangle(
            (left, top + 6, right, bottom + 6),
            radius=40 if component == "toggle" else 11,
            fill=border,
        )
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=40 if component == "toggle" else 11,
        fill=fill,
        outline=border,
        width=3 if state == "error" else 2,
    )
    if component == "toggle":
        draw.text((left, top - 30), "Notifications", fill=ink, font=font)
        knob = right - half_height if state == "selected" else left + half_height
        radius = max(12, round(half_height - 9))
        draw.ellipse((knob - radius, cy - radius, knob + radius, cy + radius), fill=text)
    elif component == "field":
        draw.text((left, top - 30), "Workspace", fill=ink, font=font)
        draw.text((left + 18, cy - 9), "Design", fill=text, font=font)
    else:
        draw.text((cx - 36, cy - 9), "Continue", fill=text, font=font)
    if state == "selected" or perturbation == "mixed":
        x, y = (right - 22, cy) if component != "toggle" else (right + 20, cy)
        draw.line((x - 7, y, x - 1, y + 6, x + 10, y - 8), fill=accent, width=4)
    if state == "active":
        draw.line((left + 7, bottom - 6, right - 7, bottom - 6), fill=border, width=5)
        draw.line((left + 7, top + 6, right - 7, top + 6), fill=border, width=3)
    if state == "error":
        draw.text((left, bottom + 18), "! Check this value", fill=border, font=small)
    if perturbation == "occluded":
        draw.rounded_rectangle((100, 130, 400, 224), radius=8, fill=panel, outline=edge)
        draw.text((156, 164), "Preview covered", fill=ink, font=font)
    return image


def _fields(row, index):
    component, theme, shared = row[2:5]
    sets = sorted({(r[2], r[3], r[4]) for r in ROWS})
    set_number = sets.index((component, theme, shared))
    return {
        "image": f"assets/q{index:02d}.png",
        "component": COMPONENT_NAMES[component],
        "appearance_contract": SHARED_CONTRACT if shared else STANDARD_CONTRACT,
        "references": {
            name: f"assets/r{set_number:02d}-{j}.png" for j, name in enumerate(helpers.OPTIONS)
        },
    }


def build_assets(rows):
    folder = HERE / "assets"
    folder.mkdir(exist_ok=True)
    rendered_references = set()
    for i, row in enumerate(rows):
        fields = _fields(row, i)
        component, theme, shared, state, scale, shift, perturbation = row[2:9]
        render(
            component,
            theme,
            state,
            shared=shared,
            scale=scale,
            shift=shift,
            perturbation=perturbation,
        ).save(HERE / fields["image"])
        for name, path in fields["references"].items():
            if path not in rendered_references:
                render(component, theme, name, shared=shared).save(HERE / path)
                rendered_references.add(path)


def build_inputs_and_labels(rows):
    """Always regenerate author-owned inputs and labels, including after an overwrite refusal."""
    build_assets(rows)
    inputs, labels = [], []
    for i, row in enumerate(rows):
        ident, split = row[:2]
        fields = _fields(row, i)
        state, questions, assets = helpers.build_request(fields, HERE)
        key = replay_key(state, questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if row[9] is not None:
            labels.append({"id": ident, "label": row[9]})
    return inputs, labels


def build_responses(rows):
    """Synthetic distributions are authored separately from pixels and gold labels."""
    build_assets(rows)
    responses = {}
    for i, row in enumerate(rows):
        state, questions, assets = helpers.build_request(_fields(row, i), HERE)
        winner, top = row[10:12]
        probabilities = {name: top if name == winner else (1 - top) / 5 for name in helpers.OPTIONS}
        answer = ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())
        responses[replay_key(state, questions, assets=assets)] = DecisionResult(
            {"visual_state": answer}, "synthetic"
        ).to_dict()
    return responses


def _is_recorded(path):
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    if not isinstance(data, dict):
        return True
    return any(not isinstance(v, dict) or v.get("model") != "synthetic" for v in data.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="replace recorded responses explicitly"
    )
    args = parser.parse_args()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    inputs, labels = build_inputs_and_labels(ROWS)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
        )
    path = folder / "responses.json"
    if _is_recorded(path) and not args.force:
        raise SystemExit(
            "refusing to overwrite recorded responses; use --force explicitly. "
            "Inputs, labels and authored images were regenerated; responses were preserved."
        )
    responses = build_responses(ROWS)
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(inputs)} examples, {len(labels)} labels, {len(responses)} responses")


if __name__ == "__main__":
    main()
