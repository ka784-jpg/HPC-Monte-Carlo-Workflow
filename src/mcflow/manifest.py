"""Validate configuration and freeze deterministic task identities."""

from pathlib import Path

from .storage import WorkflowError, digest, read_json, read_record, write_record

ENGINE = "quarter-disk-mt19937-v1"
SCHEMA = 1


def integer(value, name, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise WorkflowError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def validate_config(config):
    keys = {"samples", "replicates", "master_seed", "chunk_size"}
    if not isinstance(config, dict) or set(config) != keys:
        raise WorkflowError(f"Configuration must contain exactly: {sorted(keys)}")
    samples = config["samples"]
    if not isinstance(samples, list) or not samples:
        raise WorkflowError("samples must be a nonempty list")
    for value in samples:
        integer(value, "samples entry", 1, 10**9)
    if samples != sorted(set(samples)):
        raise WorkflowError("samples must be unique and increasing")
    integer(config["replicates"], "replicates", 1, 10000)
    integer(config["master_seed"], "master_seed", 0, 2**64 - 1)
    integer(config["chunk_size"], "chunk_size", 1, 10**7)
    if len(samples) * config["replicates"] > 100000:
        raise WorkflowError("At most 100000 tasks are supported per manifest")
    return config


def make_manifest(config):
    validate_config(config)
    tasks = []
    for samples in config["samples"]:
        for replicate in range(config["replicates"]):
            identity = [ENGINE, config["master_seed"], samples, replicate]
            tasks.append({"id": len(tasks), "samples": samples, "replicate": replicate,
                          "seed": str(int(digest(identity), 16))})
    return {"schema": SCHEMA, "engine": ENGINE, "config": config, "tasks": tasks}


def initialize(config_path, run):
    payload = make_manifest(read_json(config_path))
    run = Path(run)
    try:
        run.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise WorkflowError(f"Run already exists; use run/task to resume: {run}") from exc
    for directory in ("results", "checkpoints", "locks", "logs", "analysis"):
        (run / directory).mkdir()
    write_record(run / "manifest.json", payload)
    return payload


def load_manifest(run):
    payload = read_record(Path(run) / "manifest.json")
    if not isinstance(payload, dict) or "config" not in payload:
        raise WorkflowError("Malformed manifest")
    if payload != make_manifest(payload["config"]):
        raise WorkflowError("Manifest does not match the supported engine and task map")
    return payload


def task_at(manifest, task_id):
    integer(task_id, "task_id", 0, len(manifest["tasks"]) - 1)
    return manifest["tasks"][task_id]


def task_path(run, kind, task_id):
    return Path(run) / kind / f"{task_id:06d}.json"
