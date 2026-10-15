"""Author deterministic screenshots and imperfect synthetic responses; never call a model."""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import (
    DecisionResult,
    NoulAnswer,
    Provenance,
    ScoreAnswer,
    load_helpers,
    replay_key,
)
from jev_cookbook.vision import image_reference

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)

# id, split, rendered change, gold labels, gold severity, synthetic labels, severity, certainty
# Neutral project numbers visible on the page distinguish the examples across splits.
ROWS = [
    ("v01", "validation", "same", (), 0, (), 0, .94),
    ("v02", "validation", "theme", (), 0, (), 0, .90),
    ("v03", "validation", "accent", (), 0, (), 0, .86),
    ("v04", "validation", "round", (), 0, (), 0, .82),
    ("v05", "validation", "save_missing", ("missing",), 3, ("missing",), 3, .90),
    ("v06", "validation", "row_missing", ("missing",), 2, ("missing",), 2, .84),
    ("v07", "validation", "shift", ("misaligned",), 1, ("misaligned",), 1, .78),
    ("v08", "validation", "clip", ("clipped",), 2, ("clipped",), 2, .74),
    ("v09", "validation", "overlay", ("unexpected",), 3, ("unexpected",), 3, .82),
    ("v10", "validation", "tiny_shift", ("misaligned",), 1, (), 0, .42),
    ("v11", "validation", "subtle_clip", ("clipped",), 2, (), 0, .56),
    ("v12", "validation", "same", (), 0, ("unexpected",), 0, .98),
    ("t01", "test", "same", (), 0, (), 0, .90),
    ("t02", "test", "theme", (), 0, (), 0, .86),
    ("t03", "test", "accent", (), 0, ("unexpected",), 1, .92),
    ("t04", "test", "round", (), 0, (), 0, .48),
    ("t05", "test", "save_missing", ("missing",), 3, ("missing",), 3, .88),
    ("t06", "test", "row_missing", ("missing",), 2, ("missing",), 2, .80),
    ("t07", "test", "shift", ("misaligned",), 1, ("misaligned",), 1, .84),
    ("t08", "test", "clip", ("clipped",), 2, ("clipped",), 2, .78),
    ("t09", "test", "overlay", ("unexpected",), 3, ("unexpected",), 3, .90),
    ("t10", "test", "subtle_clip", ("clipped",), 2, (), 0, .88),
    ("t11", "test", "mixed", ("missing", "misaligned"), 3,
     ("missing", "misaligned"), 3, .52),
    ("t12", "test", "tiny_shift", ("misaligned",), 1, ("misaligned",), 0, .96),
    ("d01", "demo", "save_missing", None, None, ("missing",), 3, .90),
    ("d02", "demo", "theme", None, None, (), 0, .90),
]  # fmt: skip


def render_page(project, change="same"):
    """All assets are authored here; Pillow's bundled font avoids host font drift."""
    dark = change == "theme"
    paper, panel, ink, muted = (
        ("#20242d", "#343b49", "#f7f8fa", "#b8c1d1")
        if dark
        else ("#f5f6fa", "#ffffff", "#242936", "#626d80")
    )
    accent = "#1f78a8" if change == "accent" else "#a82567"
    image = Image.new("RGB", (480, 360), paper)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=14)

    def text(xy, value, fill=ink):
        draw.text(xy, value, fill=fill, font=font)

    draw.rectangle((0, 0, 480, 45), fill="#242936")
    text((20, 16), "FOLIO / Workspace", "#ffffff")
    text((25, 65), f"Project {project}")
    text((25, 88), "Project settings", muted)
    draw.rounded_rectangle((24, 112, 456, 280), radius=10, fill=panel)
    text((40, 129), "Display name")
    draw.rounded_rectangle((40, 150, 437, 180), radius=4, outline=muted)
    text((51, 160), f"Field notes {project}")
    shift = 22 if change in ("shift", "mixed") else 4 if change == "tiny_shift" else 0
    text((40 + shift, 197), "Notification frequency", muted)
    if change != "row_missing":
        draw.rectangle((40 + shift, 219, 437, 248), outline=muted)
        text((51 + shift, 229), "Daily summary")
        if change in ("clip", "subtle_clip"):
            end = 109 if change == "clip" else 138
            draw.rectangle((end, 222, 160, 246), fill=panel)
            draw.line((end, 220, end, 247), fill=muted)
    if change not in ("save_missing", "mixed"):
        draw.rounded_rectangle(
            (294, 301, 456, 338), radius=18 if change == "round" else 4, fill=accent
        )
        text((325, 314), "Save changes", "#ffffff")
    text((25, 314), "Changes stay local", muted)
    if change == "overlay":
        draw.rectangle((272, 286, 467, 349), fill="#dedede", outline="#e551ba", width=3)
        text((289, 309), "Panel unavailable", "#1e1e1e")
    return image


def encode_image(image, recipe_dir=None):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    data = buffer.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    relative = f"assets/{digest}.png"
    if recipe_dir is not None:
        path = recipe_dir / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
    asset = {
        "type": "image",
        "format": "png",
        "data_base64": base64.b64encode(data).decode("ascii"),
    }
    return relative, image_reference(asset), asset


def build_data(recipe_dir=None, rows=ROWS):
    """Labels and authored changes never enter fields, state, or the opaque references."""
    questions = helpers.build_questions()
    inputs, labels, responses = [], [], {}
    for index, (ident, split, change, gold, level, predicted, pred_level, certainty) in enumerate(
        rows
    ):
        project = 701 + index
        before_path, before_ref, before_asset = encode_image(render_page(project), recipe_dir)
        after_path, after_ref, after_asset = encode_image(render_page(project, change), recipe_dir)
        fields = {
            "before_path": before_path,
            "after_path": after_path,
            "before_ref": before_ref,
            "after_ref": after_ref,
        }
        assets = {before_ref: before_asset, after_ref: after_asset}
        key = replay_key(helpers.build_state(fields), questions, assets=assets)
        inputs.append({"id": ident, "split": split, "fields": fields, "replay_keys": [key]})
        if gold is not None:
            labels.append({"id": ident, "label": {"defects": list(gold), "severity": level}})
        provenance = Provenance.synthetic()
        answers = {
            name: NoulAnswer(
                (1 + certainty) / 2 if name in predicted else (1 - certainty) / 2, provenance
            )
            for name in helpers.LABELS
        }
        # Put remaining probability on a neighboring severity: its spread equals 1 - certainty.
        probs = {i: 0.0 for i in range(4)}
        probs[pred_level] = (1 + certainty) / 2
        neighbor = pred_level + 1 if pred_level < 3 else 2
        probs[neighbor] = (1 - certainty) / 2
        answers["severity"] = ScoreAnswer.from_probabilities(
            probs, dict(enumerate(helpers.LEVELS)), provenance
        )
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    return inputs, labels, responses


def build_inputs_and_labels(rows):
    """Pure reconstruction used by the shared fixture guard, without rewriting images."""
    inputs, labels, _ = build_data(rows=rows)
    return inputs, labels


def build_responses(rows):
    """Reconstruct only authored answers; never read or replace recorded responses."""
    return build_data(rows=rows)[2]


def write_fixtures(recipe_dir=HERE, *, force=False):
    recipe_dir = Path(recipe_dir)
    inputs, labels, responses = build_data(recipe_dir)
    fixtures = recipe_dir / "fixtures"
    fixtures.mkdir(exist_ok=True)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (fixtures / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
        )
    path = fixtures / "responses.json"
    if path.exists() and not force:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or any(
            not isinstance(value, dict) or value.get("model") != "synthetic"
            for value in existing.values()
        ):
            raise ValueError("refusing to overwrite recorded responses; pass --force explicitly")
    path.write_text(
        json.dumps(dict(sorted(responses.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(inputs), len(labels), len(responses)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace recorded answers explicitly")
    args = parser.parse_args()
    print("wrote examples, labels, responses:", write_fixtures(force=args.force))
