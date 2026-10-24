"""Command-line interface; exit 75 means a task paused with resumable work."""

import argparse
import json
from pathlib import Path
import sys
import threading

from .analysis import aggregate, inspect_run
from .manifest import initialize, load_manifest
from .runner import run_local, run_task, stop_on_signal
from .slurm import prepare_slurm
from .storage import WorkflowError, digest


def parser():
    root = argparse.ArgumentParser(description="Reproducible quarter-circle Monte Carlo workflow")
    commands = root.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a fresh run with an immutable task manifest")
    init.add_argument("config", type=Path)
    init.add_argument("run", type=Path)
    for name in ("run", "task", "status", "aggregate", "plot", "slurm"):
        command = commands.add_parser(name)
        command.add_argument("run", type=Path)
        if name in ("run", "task", "slurm"):
            command.add_argument("--min-free-mb", type=int, default=64)
        if name == "run":
            command.add_argument("--workers", type=int, default=1)
        if name == "task":
            command.add_argument("--task-id", type=int, required=True)
            command.add_argument("--max-chunks", type=int)
            command.add_argument("--expect-manifest")
        if name == "slurm":
            command.add_argument("--concurrency", type=int, default=4)
            command.add_argument("--pending", action="store_true")
            command.add_argument("--python", default="python3")
            command.add_argument("--walltime", default="00:10:00")
            command.add_argument("--memory-mb", type=int, default=256)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            manifest = initialize(args.config, args.run)
            result = {"tasks": len(manifest["tasks"]), "manifest_sha256": digest(manifest)}
        elif args.command == "run":
            result = run_local(args.run, args.workers, args.min_free_mb)
            print(json.dumps(result, indent=2))
            return 75 if result.get("paused") else 0
        elif args.command == "task":
            if args.expect_manifest and digest(load_manifest(args.run)) != args.expect_manifest:
                raise WorkflowError("The queued job's manifest differs from this run")
            stop = threading.Event()
            with stop_on_signal(stop):
                state = run_task(args.run, args.task_id, max_chunks=args.max_chunks,
                                 min_free_mb=args.min_free_mb, stop=stop.is_set)
            print(json.dumps({"task_id": args.task_id, "status": state}))
            return 75 if state == "paused" else 0
        elif args.command == "status":
            result, _ = inspect_run(args.run)
            result.pop("states")
            print(json.dumps(result, indent=2))
            return 1 if result["errors"] else 0
        elif args.command == "aggregate":
            result = aggregate(args.run)
        elif args.command == "plot":
            from .plotting import plot
            result = {"plot": str(plot(args.run))}
        else:
            print(prepare_slurm(args.run, concurrency=args.concurrency, pending=args.pending,
                                python=args.python, walltime=args.walltime,
                                memory_mb=args.memory_mb, min_free_mb=args.min_free_mb))
            return 0
        print(json.dumps(result, indent=2))
        return 0
    except (WorkflowError, OSError) as exc:
        print(f"mcflow: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
