"""Explicit opt-in recording to a separate destination; never run by the notebook."""

import argparse
import os
from pathlib import Path

from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

HERE = Path(__file__).resolve().parent


def capture(output, ledger):
    if os.environ.get("JEV_COOKBOOK_LIVE") != "1":
        raise RuntimeError("recording requires explicit JEV_COOKBOOK_LIVE=1")
    output, ledger = Path(output).resolve(), Path(ledger).resolve()
    if output == (HERE / "fixtures" / "responses.json").resolve():
        raise ValueError("record to a separate destination; preserve the synthetic fixtures")
    helpers = load_helpers(HERE)
    backend = get_backend(
        fixtures=HERE / "fixtures" / "responses.json",
        model="jev-1.14.0",
        images=True,
        long_context=True,
    )
    requests = [helpers.build_request(e.fields, HERE) for e in load_inputs(HERE)]
    return record(backend, requests, output, overwrite=False, ledger_path=ledger)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    report = capture(args.output, args.ledger)
    print(f"recorded={len(report.written)} skipped={len(report.skipped)} model={report.model}")


if __name__ == "__main__":
    main()
