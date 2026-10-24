"""Opt-in recording into a separate replayable recipe copy; never run by the notebook."""

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from jev_cookbook import LiveBackend, load_helpers, record, replay_key
from jev_cookbook.fixtures import load_inputs
from jev_cookbook.vision import run_record

HERE = Path(__file__).resolve().parent


class TimedBackend:
    """Recorder-compatible proxy retaining actual call duration and returned usage only."""

    def __init__(self, backend, measurements):
        self.backend = backend
        self.measurements = measurements
        self.rows = {}

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def decide(self, state, questions, *, assets=None):
        started = time.perf_counter()
        result = self.backend.decide(state, questions, assets=assets)
        elapsed = time.perf_counter() - started
        row = run_record(result, mode="live", measured_latency_seconds=elapsed)
        row["date"] = next(iter(result.answers.values())).provenance.date
        self.rows[replay_key(state, questions, assets=assets)] = row
        self.measurements.write_text(json.dumps(self.rows, indent=2) + "\n", encoding="utf-8")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="a new directory outside this recipe"
    )
    args = parser.parse_args()
    if os.environ.get("JEV_COOKBOOK_LIVE") != "1":
        raise SystemExit("recording requires explicit JEV_COOKBOOK_LIVE=1")
    output = args.output.resolve()
    if output == HERE or HERE in output.parents or output in HERE.parents:
        raise SystemExit("choose a new output directory outside this recipe")
    if output.exists():
        raise SystemExit("recording output must be new; existing evidence is never overwritten")
    helpers = load_helpers(HERE)
    examples = load_inputs(HERE)
    requests = [helpers.build_request(e.fields, HERE) for e in examples]
    backend = LiveBackend(
        "jev-1.14.0", images=True, max_requests=helpers.MAX_REQUESTS, max_retries=0
    )
    shutil.copytree(
        HERE,
        output,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "responses.json"),
    )
    timed = TimedBackend(backend, output / "measurements.json")
    report = record(
        timed,
        requests,
        output / "fixtures" / "responses.json",
        ledger_path=output / "capture-ledger.json",
    )
    print(f"Recorded {len(report.written)} requests. Re-execute the copied notebook offline.")


if __name__ == "__main__":
    main()
