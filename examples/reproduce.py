"""Reproduce the documented Monte Carlo gallery without cluster access."""

import argparse
import json
from pathlib import Path

from mcflow.analysis import aggregate
from mcflow.manifest import initialize, load_manifest, make_manifest
from mcflow.plotting import plot
from mcflow.runner import run_local
from mcflow.storage import WorkflowError, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=Path("runs/gallery"))
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    config = Path(__file__).resolve().parents[1] / "configs" / "gallery.json"
    if args.run.exists():
        if load_manifest(args.run) != make_manifest(read_json(config)):
            raise WorkflowError("Existing run has a different gallery configuration")
    else:
        initialize(config, args.run)
    counts = run_local(args.run, args.workers)
    if counts.get("paused"):
        return 75
    summary = aggregate(args.run)
    figure = plot(args.run)
    print(json.dumps({"tasks": summary["task_count"], "samples": summary["total_samples"],
                      "status": summary["status"], "plot": str(figure)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
