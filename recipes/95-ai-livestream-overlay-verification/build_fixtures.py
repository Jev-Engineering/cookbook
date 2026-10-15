"""Author deterministic synthetic game diagrams and deliberately imperfect replay answers."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jev_cookbook import DecisionResult, NoulAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.live import _dump

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()


def episode(
    ident, split, game, claims=None, *, telemetry=None, hidden=(), timing="fresh", error=None
):
    return {
        "id": ident,
        "split": split,
        "game": game,
        "claims": claims or game,
        "telemetry": telemetry or game,
        "hidden": hidden,
        "timing": timing,
        "error": error,
    }


# No actual game, OBS, Twitch, player data, or model inference is used.
ROWS = [
    episode("v01", "validation", ("combat", "attack", "ready")),
    episode("v02", "validation", ("rewards", "collect", "ready"),
            ("combat", "collect", "ready"), telemetry=("combat", "collect", "ready")),
    episode("v03", "validation", ("combat", "block", "complete"), ("combat", "attack", "complete")),
    episode("v04", "validation", ("map", "choose_route", "ready"), timing="overlay_delayed"),
    episode("v05", "validation", ("combat", "block", "ready")),
    episode("v06", "validation", ("combat", "attack", "executing"), hidden=("action", "status")),
    episode("v07", "validation", ("menu", "none", "paused"), ("menu", "none", "ready")),
    episode("v08", "validation", ("loading", "none", "loading"), hidden=("action",)),
    episode("v09", "validation", ("combat", "attack", "ready"), timing="invalid_timestamps"),
    episode("v10", "validation", ("combat", "block", "ready"), ("mystery", "block", "ready")),
    episode("v11", "validation", ("combat", "block", "complete"),
            ("combat", "attack", "complete"), error="weak_false_support"),
    episode("v12", "validation", ("map", "choose_route", "ready"), timing="stream_stale"),
    episode("t01", "test", ("combat", "block", "executing")),
    episode("t02", "test", ("map", "choose_route", "ready"),
            ("combat", "choose_route", "ready"), telemetry=("combat", "choose_route", "ready")),
    episode("t03", "test", ("combat", "block", "complete"), ("combat", "attack", "complete")),
    episode("t04", "test", ("rewards", "collect", "ready"),
            ("combat", "collect", "ready"), timing="overlay_delayed"),
    episode("t05", "test", ("combat", "attack", "ready"), error="confident_false_alarm"),
    episode("t06", "test", ("combat", "block", "executing"), hidden=("action", "status")),
    episode("t07", "test", ("menu", "none", "paused"), ("menu", "none", "ready")),
    episode("t08", "test", ("loading", "none", "loading"), hidden=("action",)),
    episode("t09", "test", ("combat", "block", "ready"), timing="invalid_timestamps"),
    episode("t10", "test", ("combat", "attack", "ready"), ("unknown", "attack", "ready")),
    episode("t11", "test", ("combat", "block", "complete"),
            ("combat", "attack", "complete"), error="confident_false_support"),
    episode("t12", "test", ("map", "choose_route", "ready"), timing="stream_stale"),
    episode("d01", "demo", ("rewards", "collect", "ready"), ("combat", "collect", "ready")),
    episode("d02", "demo", ("combat", "attack", "executing"),
            hidden=("action",), error="inconsistent"),
]  # fmt: skip


def draw_frame(row, index):
    """A readable 512x384 diagram; every claim corresponds to a game HUD field."""
    image = Image.new("RGB", (512, 384), "#FEFEFE")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=15)
    seed = int(hashlib.sha256(row["id"].encode()).hexdigest()[:6], 16)
    game = row["game"]
    if index == 0 and row["claims"][0] in helpers.KNOWN["phase"]:
        game = (row["claims"][0], *game[1:])
    draw.rectangle((0, 0, 511, 271), fill="#DCE8ED")
    draw.rectangle((0, 0, 511, 36), fill="#1E1E1E")
    draw.text((14, 8), "ORBIT GARDEN / GAMEPLAY", fill="#FEFEFE", font=font)
    draw.text((342, 118), f"Zone: {seed:06X}", fill="#1E1E1E", font=small)
    draw.rectangle((14, 48, 326, 166), fill="#FEFEFE", outline="#1E1E1E", width=2)
    for number, (name, value) in enumerate(zip(helpers.CLAIMS, game, strict=True)):
        y = 59 + number * 34
        text = {"phase": "Phase", "action": "Selected action", "status": "Action status"}[name]
        draw.text((25, y), f"{text}: {value}", fill="#1E1E1E", font=font)
        if name in row["hidden"]:
            draw.rectangle((20, y - 1, 322, y + 25), fill="#77838D")
            if name != "action" or game[0] != "loading":
                draw.text((32, y + 1), "HUD COVERED", fill="#FEFEFE", font=small)
    if game[0] in ("menu", "loading"):
        draw.rectangle((60, 187, 451, 247), fill="#1E1E1E")
        draw.text(
            (99, 206),
            "PAUSED MENU" if game[0] == "menu" else "LOADING WORLD",
            fill="#FEFEFE",
            font=font,
        )
    else:
        for column in range(7):
            x = 18 + column * 68
            draw.rectangle((x, 190, x + 50, 242), fill="#ADC7A2", outline="#1E1E1E")
        x = 26 + (seed % 6) * 68
        draw.ellipse((x, 196, x + 30, 226), fill="#F386A1", outline="#1E1E1E", width=2)
        # A moving ambient light changes pixels without changing the claim.
        x = 352 + (seed % 70) + index * 12
        draw.ellipse((x, 60, x + 16, 76), fill="#E8A33D")
    draw.rectangle((0, 272, 511, 383), fill="#1E1E1E")
    draw.text((14, 280), "AGENT OVERLAY / claims to verify", fill="#F386A1", font=font)
    for number, (name, value) in enumerate(zip(helpers.CLAIMS, row["claims"], strict=True)):
        draw.text((16, 308 + number * 23), f"{name}: {value}", fill="#FEFEFE", font=small)
    draw.text((342, 315), "Strategy:", fill="#F386A1", font=small)
    draw.text((342, 338), "steady progress", fill="#FEFEFE", font=small)
    return image


def build_inputs_and_labels(rows):
    assets_dir = HERE / "assets"
    assets_dir.mkdir(exist_ok=True)
    inputs, labels = [], []
    for number, row in enumerate(rows):
        current = 100000 + number * 10000
        previous = current - 500
        if row["timing"] == "invalid_timestamps":
            previous = current + 100
        fields = {
            "frames": [],
            "agent_claims": dict(zip(helpers.CLAIMS, row["claims"], strict=True)),
            "game_telemetry": dict(zip(helpers.CLAIMS, row["telemetry"], strict=True)),
            "overlay_updated_ms": current - (5000 if row["timing"] == "overlay_delayed" else 250),
            "observed_ms": current + (4000 if row["timing"] == "stream_stale" else 100),
        }
        for index, timestamp in enumerate((previous, current)):
            path = assets_dir / f"{row['id']}-{index}.png"
            draw_frame(row, index).save(path, optimize=False)
            fields["frames"].append({"path": f"assets/{path.name}", "captured_ms": timestamp})
        state, assets = helpers.build_request(fields, HERE)
        key = replay_key(state, QUESTIONS, assets=assets)
        inputs.append(
            {"id": row["id"], "split": row["split"], "fields": fields, "replay_keys": [key]}
        )
        if row["split"] == "demo":
            continue
        claims = {}
        for name, actual, claimed in zip(helpers.CLAIMS, row["game"], row["claims"], strict=True):
            if (
                name in row["hidden"]
                or claimed not in helpers.KNOWN[name]
                or row["timing"] == "invalid_timestamps"
            ):
                claims[name] = "unresolved"
            else:
                claims[name] = "supported" if actual == claimed else "unsupported"
        # Independent author annotations: never produced from the model answers.
        flags = [] if row["timing"] == "fresh" else [row["timing"]]
        labels.append(
            {
                "id": row["id"],
                "label": {
                    "claims": claims,
                    "semantic_mismatch": "unsupported" in claims.values(),
                    "time_flags": flags,
                    "review": bool(flags) or any(value != "supported" for value in claims.values()),
                },
            }
        )
    return inputs, labels


def build_responses(rows, inputs=None):
    if inputs is None:
        inputs, _ = build_inputs_and_labels(rows)
    responses = {}
    for row, example in zip(rows, inputs, strict=True):
        answers = {}
        for name, actual, claimed in zip(helpers.CLAIMS, row["game"], row["claims"], strict=True):
            resolvable = name not in row["hidden"] and claimed in helpers.KNOWN[name]
            r, s = (0.97, 0.96 if actual == claimed else 0.04) if resolvable else (0.03, 0.08)
            if name == "action" and row["error"] == "weak_false_support":
                s = 0.68
            if name == "action" and row["error"] == "confident_false_support":
                s = 0.96
            if name == "status" and row["error"] == "confident_false_alarm":
                s = 0.04
            if name == "action" and row["error"] == "inconsistent":
                r, s = 0.02, 0.98
            answers[f"{name}_resolvable"] = NoulAnswer(noul=r, provenance=Provenance.synthetic())
            answers[f"{name}_supported"] = NoulAnswer(noul=s, provenance=Provenance.synthetic())
        responses[example["replay_keys"][0]] = DecisionResult(answers, "synthetic").to_dict()
    return responses


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    inputs, labels = build_inputs_and_labels(ROWS)
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    for filename, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        (folder / filename).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
        )
    path = folder / "responses.json"
    if path.exists() and not args.force:
        existing = json.loads(path.read_text("utf-8"))
        if any(
            not isinstance(entry, dict) or entry.get("model") != "synthetic"
            for entry in existing.values()
        ):
            raise SystemExit("Refusing to overwrite recorded responses; use --force explicitly.")
    path.write_text(_dump(build_responses(ROWS, inputs)), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
