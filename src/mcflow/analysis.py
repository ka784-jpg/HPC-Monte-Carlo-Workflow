"""Strict collection, binomial uncertainty, and reproducible derived tables."""

import csv
import io
import math
from pathlib import Path
from statistics import NormalDist

from .manifest import integer, load_manifest, task_path
from .runner import validate_payload
from .storage import WorkflowError, atomic_text, digest, read_record, write_record


def wilson(hits, samples, confidence=0.95):
    integer(samples, "samples", 1)
    integer(hits, "hits", 0, samples)
    if not 0 < confidence < 1:
        raise WorkflowError("confidence must lie strictly between zero and one")
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = hits / samples
    denominator = 1 + z * z / samples
    center = (p + z * z / (2 * samples)) / denominator
    half = z * math.sqrt(p * (1 - p) / samples + z * z / (4 * samples**2)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def inspect_run(run):
    run = Path(run)
    manifest = load_manifest(run)
    expected = {f"{task['id']:06d}.json" for task in manifest["tasks"]}
    errors = []
    for kind in ("results", "checkpoints"):
        for path in (run / kind).glob("*.json"):
            if path.name not in expected:
                errors.append(f"Unexpected file: {kind}/{path.name}")
    states = {}
    records = []
    for task in manifest["tasks"]:
        task_id = task["id"]
        result = task_path(run, "results", task_id)
        checkpoint = task_path(run, "checkpoints", task_id)
        try:
            if result.exists():
                records.append(validate_payload(read_record(result), manifest, task))
                state = "complete"
            elif checkpoint.exists():
                validate_payload(read_record(checkpoint), manifest, task, checkpoint=True)
                state = "checkpointed"
            else:
                state = "pending"
            if (run / "locks" / f"{task_id:06d}.lock").exists():
                state = "locked"
        except WorkflowError as exc:
            state = "invalid"
            errors.append(str(exc))
        states[task_id] = state
    counts = {state: list(states.values()).count(state)
              for state in ("complete", "checkpointed", "pending", "locked", "invalid")}
    return {"tasks": len(states), "counts": counts, "errors": errors, "states": states}, records


def aggregate(run):
    run = Path(run)
    manifest = load_manifest(run)
    status, records = inspect_run(run)
    if status["errors"] or status["counts"]["complete"] != status["tasks"]:
        raise WorkflowError(f"Aggregation requires every task complete and valid: {status['counts']}; "
                            + "; ".join(status["errors"]))
    rows = []
    for record in records:
        task = record["task"]
        low, high = wilson(record["hits"], task["samples"])
        rows.append({"task_id": task["id"], "samples": task["samples"],
                     "replicate": task["replicate"], "seed": task["seed"], "hits": record["hits"],
                     "pi_estimate": 4 * record["hits"] / task["samples"],
                     "ci95_low": 4 * low, "ci95_high": 4 * high})
    groups = []
    for samples in manifest["config"]["samples"]:
        subset = [row for row in rows if row["samples"] == samples]
        total = samples * len(subset)
        hits = sum(row["hits"] for row in subset)
        low, high = wilson(hits, total)
        groups.append({"samples_per_replicate": samples, "replicates": len(subset),
                       "total_samples": total, "hits": hits, "pi_estimate": 4 * hits / total,
                       "ci95_low": 4 * low, "ci95_high": 4 * high,
                       "replicate_rmse": math.sqrt(sum((row["pi_estimate"] - math.pi)**2
                                                       for row in subset) / len(subset)),
                       "theoretical_single_run_se": math.sqrt((4 * math.pi - math.pi**2) / samples)})
    summary = {"status": "PASS", "engine": manifest["engine"],
               "manifest_sha256": digest(manifest), "result_payloads_sha256": digest(records),
               "task_count": len(records), "total_samples": sum(r["completed"] for r in records),
               "python_versions": sorted({r["python"] for r in records}),
               "interval": "95% Wilson score, pooled within each sample budget", "groups": groups}
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(run / "analysis" / "tasks.csv", stream.getvalue())
    write_record(run / "analysis" / "summary.json", summary)
    return summary
