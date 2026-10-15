"""Explicitly record the same image requests to a new, external capture directory."""

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
helpers = load_helpers(HERE)


class TimedBackend(LiveBackend):
    """Time actual successful inference calls, with returned provenance and optional usage."""

    def __init__(self, accounting_path, **kwargs):
        super().__init__(**kwargs)
        self.accounting_path, self.accounting = accounting_path, {}

    def decide(self, state, questions, *, assets=None):
        started = time.perf_counter()
        result = super().decide(state, questions, assets=assets)
        elapsed = time.perf_counter() - started
        key = replay_key(state, questions, assets=assets)
        row = run_record(result, mode="recorded", measured_latency_seconds=elapsed)
        row["date"] = next(iter(result.answers.values())).provenance.date
        self.accounting[key] = row
        self.accounting_path.write_text(json.dumps(self.accounting, indent=2) + "\n", "utf-8")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if os.environ.get("JEV_COOKBOOK_LIVE") != "1":
        raise SystemExit("set JEV_COOKBOOK_LIVE=1 explicitly before recording")
    destination = args.output_dir.resolve()
    if destination.is_relative_to(HERE):
        raise SystemExit("capture outside this recipe to preserve synthetic fixtures")
    destination.mkdir(parents=True, exist_ok=False)
    fixtures = destination / "fixtures"
    fixtures.mkdir()
    for name in ("inputs.jsonl", "labels.jsonl"):
        shutil.copyfile(HERE / "fixtures" / name, fixtures / name)
    backend = TimedBackend(
        destination / "accounting.json",
        model="jev-1.14.0",
        images=True,
        max_requests=helpers.MAX_REQUESTS,
        max_retries=0,
    )
    try:
        report = record(
            backend,
            (helpers.build_request(e.fields) for e in load_inputs(HERE)),
            fixtures / "responses.json",
            ledger_path=destination / "requests.json",
        )
        print(f"recorded {len(report.written)} requests; model={report.model}")
    finally:
        backend.close()


if __name__ == "__main__":
    main()
