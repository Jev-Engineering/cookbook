"""Opt-in capture of the unchanged requests to a NEW directory, never committed fixtures."""

import argparse
import json
import os
from pathlib import Path
from time import perf_counter

from jev_cookbook import LiveBackend, load_helpers, record, replay_key
from jev_cookbook.fixtures import load_inputs
from jev_cookbook.vision import run_record

HERE = Path(__file__).resolve().parent


class TimedBackend(LiveBackend):
    """Record actual call latency and returned usage; no cost estimate is invented."""

    def __init__(self, measurement_path):
        super().__init__("jev-1.14.0", images=True, max_requests=26, max_retries=0)
        self.measurement_path = measurement_path
        self.measurements = {}

    def decide(self, state, questions, *, assets=None):
        started = perf_counter()
        result = super().decide(state, questions, assets=assets)
        elapsed = perf_counter() - started
        self.measurements[replay_key(state, questions, assets=assets)] = run_record(
            result, mode="live", measured_latency_seconds=elapsed
        )
        return result

    def save_measurements(self):
        """Write only after the recorder has persisted successful answers."""
        temporary = self.measurement_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.measurements, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.measurement_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new capture directory")
    args = parser.parse_args()
    if os.environ.get("JEV_COOKBOOK_LIVE") != "1":
        raise SystemExit("recording requires explicit JEV_COOKBOOK_LIVE=1")
    destination = args.output.resolve()
    if destination == HERE or HERE in destination.parents:
        raise SystemExit("capture outside the recipe to preserve committed fixtures")
    destination.mkdir(parents=True, exist_ok=False)
    helpers = load_helpers(HERE)
    requests = [helpers.build_request(e.fields, HERE) for e in load_inputs(HERE)]
    backend = TimedBackend(destination / "measurements.json")
    try:
        report = record(
            backend,
            requests,
            destination / "responses.json",
            ledger_path=destination / "ledger.json",
        )
        print(f"captured {len(report.written)} requests; returned model: {report.model}")
    finally:
        try:
            backend.save_measurements()
        finally:
            backend.close()


if __name__ == "__main__":
    main()
