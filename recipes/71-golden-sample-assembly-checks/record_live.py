"""Opt-in capture of the same image request triples into a separate response file.

Run from this recipe folder with JEV_COOKBOOK_LIVE=1 and the configured API key.
No calls are made by importing this file. Existing synthetic fixtures are protected.
"""

import argparse
from pathlib import Path

from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.output.resolve() == (root / "fixtures/responses.json").resolve():
        raise SystemExit("capture to a separate file; preserve synthetic fixtures")
    helpers = load_helpers(root)
    backend = get_backend(
        fixtures=root / "fixtures/responses.json", images=True, model="jev-1.14.0"
    )
    if backend.mode != "live":
        raise SystemExit("recording requires explicit JEV_COOKBOOK_LIVE=1")
    requests = [helpers.build_request(example.fields, root) for example in load_inputs(root)]
    report = record(
        backend,
        requests,
        args.output,
        ledger_path=args.output.parent / "capture-ledger.json",
    )
    print(f"Captured {len(report.written)} responses; returned model: {report.model}")


if __name__ == "__main__":
    main()
