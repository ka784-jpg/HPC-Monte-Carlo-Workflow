"""Structured run metadata for Bash wrappers; simulation logic stays in mcflow."""

import argparse
import json
import os
from pathlib import Path
import re
import sys

from mcflow.analysis import inspect_run
from mcflow.manifest import load_manifest
from mcflow.runner import check_free_space
from mcflow.slurm import index_ranges
from mcflow.storage import WorkflowError, digest, read_record, write_record

WAIT = 3


def task_ids(spec):
    if not re.fullmatch(r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*", spec):
        raise WorkflowError("Invalid array index specification")
    result = []
    for group in spec.split(","):
        pair = [int(value) for value in group.split("-")]
        if len(pair) == 2 and (pair[0] > pair[1] or pair[1] - pair[0] > 100000):
            raise WorkflowError("Invalid array index range")
        result.extend(range(pair[0], pair[-1] + 1))
    if len(result) != len(set(result)):
        raise WorkflowError("Duplicate array indices")
    return result


def accounting(run, job_id, text):
    manifest = load_manifest(run)
    receipt = run / "submissions" / f"job-{job_id}.json"
    if receipt.exists():
        saved = read_record(receipt)
        if saved["manifest_sha256"] != digest(manifest) or saved["array_job_id"] != job_id:
            raise WorkflowError("Submission receipt identity mismatch")
        expected = set(saved["task_ids"])
    else:
        expected = {task["id"] for task in manifest["tasks"]}
    completed = set()
    waiting = False
    live = {"PENDING", "RUNNING", "COMPLETING", "CONFIGURING", "SUSPENDED", "RESIZING",
            "REQUEUED", "REQUEUE_FED", "REQUEUE_HOLD", "SIGNALING", "STAGE_OUT", "STOPPED"}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split("|")]
        if len(fields) != 3:
            raise WorkflowError("Malformed sacct output")
        identifier, state, exit_code = fields
        if not re.fullmatch(re.escape(job_id) + r"(?:_\d+)?(?:\.[A-Za-z0-9_-]+)?", identifier):
            raise WorkflowError(f"Unexpected sacct job identity: {identifier}")
        if state in live:
            waiting = True
        elif state != "COMPLETED" or exit_code != "0:0":
            raise WorkflowError(f"Scheduler failure: {identifier}: {state}, exit={exit_code}")
        elif re.fullmatch(re.escape(job_id) + r"_\d+", identifier):
            completed.add(int(identifier.split("_")[1]))
    if waiting or not expected.issubset(completed):
        print("Waiting for complete scheduler accounting for all submitted array elements.")
        return WAIT
    print(f"Scheduler accounting verified for {len(expected)} array elements.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preflight", "plan", "status", "receipt", "accounting"])
    parser.add_argument("run", type=Path)
    parser.add_argument("--pending", action="store_true")
    parser.add_argument("--plots", action="store_true")
    parser.add_argument("--job-id")
    parser.add_argument("--collector")
    parser.add_argument("--indices")
    args = parser.parse_args()
    try:
        run = args.run.resolve()
        manifest = load_manifest(run)
        if args.command in ("receipt", "accounting"):
            if not args.job_id or not re.fullmatch(r"[0-9]+", args.job_id):
                raise WorkflowError("A numeric array job ID is required")
        if args.command == "accounting":
            return accounting(run, args.job_id, sys.stdin.read())
        status, _ = inspect_run(run)
        if status["errors"]:
            raise WorkflowError("; ".join(status["errors"]))
        if args.command == "status":
            print(json.dumps(status["counts"], sort_keys=True))
            return 0 if status["counts"]["complete"] == status["tasks"] else WAIT
        if args.command == "preflight":
            check_free_space(run, int(os.environ.get("MC_MIN_FREE_MB", "64")))
            for name in ("results", "checkpoints", "locks", "logs", "analysis"):
                if not (run / name).is_dir() or not os.access(run / name, os.W_OK):
                    raise WorkflowError(f"Required writable directory missing: {run / name}")
            if args.plots:
                import matplotlib
            print(f"Preflight passed: {len(manifest['tasks'])} tasks; Python {sys.version.split()[0]}")
        elif args.command == "plan":
            if status["counts"]["locked"]:
                raise WorkflowError("Resolve active or stale task locks before submission")
            indices = [i for i, state in status["states"].items() if not args.pending or state != "complete"]
            if not indices:
                raise WorkflowError("No unfinished tasks remain")
            if "\n" in str(run) or "\r" in str(run):
                raise WorkflowError("Run path must not contain a newline")
            print(run)
            print(digest(manifest))
            print(index_ranges(indices))
        else:
            if not args.indices:
                raise WorkflowError("Array indices are required")
            indices = task_ids(args.indices)
            if not set(indices).issubset({task["id"] for task in manifest["tasks"]}):
                raise WorkflowError("Receipt contains unknown task IDs")
            if args.collector and not re.fullmatch(r"[0-9]+", args.collector):
                raise WorkflowError("Collector job ID must be numeric")
            directory = run / "submissions"
            directory.mkdir(exist_ok=True)
            path = directory / f"job-{args.job_id}.json"
            base = {"manifest_sha256": digest(manifest), "array_job_id": args.job_id, "task_ids": indices}
            if path.exists():
                old = read_record(path)
                if any(old.get(key) != value for key, value in base.items()):
                    raise WorkflowError("Refusing to replace a different submission receipt")
            write_record(path, {**base, "collector_job_id": args.collector})
            print(f"Submission receipt: {path}")
        return 0
    except (WorkflowError, OSError, ImportError, ValueError) as exc:
        print(f"workflow: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
