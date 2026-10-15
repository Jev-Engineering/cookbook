"""Prepare a larger local workload with a caller-supplied whole-request token counter."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from jev_cookbook import load_helpers
from jev_cookbook.fixtures import load_inputs

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--counter", required=True, help="module:function(state, questions, assets)"
    )
    parser.add_argument(
        "--counter-id", required=True, help="tokenizer/version and image assumptions"
    )
    parser.add_argument("--target-tokens", type=int, default=250_000)
    parser.add_argument(
        "--out", type=Path, required=True, help="new JSON manifest outside fixtures/"
    )
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("output already exists; choose a new workload manifest")
    if "fixtures" in args.out.resolve().parts:
        raise SystemExit("scaled manifests belong outside fixtures/")
    module, function = args.counter.rsplit(":", 1)
    counter = getattr(importlib.import_module(module), function)
    rows, metadata = [], {}
    for example in load_inputs(HERE):
        fields, manifest = helpers.scale_to_external_budget(
            example.fields,
            HERE,
            target_tokens=args.target_tokens,
            counter=counter,
            counter_id=args.counter_id,
        )
        rows.append({"id": example.id, "split": example.split, "fields": fields})
        metadata[example.id] = manifest
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"examples": rows, "preflight": metadata}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Prepared {len(rows)} tasks; counts are external preflight counts, not server usage.")
    print("No requests sent. Preserve this manifest with the eventual recorded comparison.")


if __name__ == "__main__":
    main()
