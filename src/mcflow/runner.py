"""Single-writer tasks, resumable RNG state, and bounded local parallelism."""

from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import multiprocessing
import os
from pathlib import Path
import platform
import random
import shutil
import signal
import threading

from .engine import count_hits
from .manifest import integer, load_manifest, task_at, task_path
from .storage import WorkflowError, digest, read_record, write_record

_worker_stop = None


def check_free_space(run, min_free_mb):
    integer(min_free_mb, "min_free_mb", 0)
    if shutil.disk_usage(run).free < min_free_mb * 1024**2:
        raise WorkflowError(f"Less than {min_free_mb} MiB free; leaving existing data intact")


@contextmanager
def task_lock(run, task_id):
    lock = Path(run) / "locks" / f"{task_id:06d}.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise WorkflowError(f"Task locked: {lock}; never remove a lock while its worker is alive") from exc
    try:
        write_record(lock / "owner.json", {"pid": os.getpid()})
        yield
    finally:
        (lock / "owner.json").unlink(missing_ok=True)
        lock.rmdir()


@contextmanager
def stop_on_signal(event):
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda number, frame: event.set())
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def validate_payload(payload, manifest, task, checkpoint=False):
    base_keys = {"manifest_sha256", "task", "completed", "hits", "python"}
    expected = base_keys | ({"rng_state"} if checkpoint else set())
    if not isinstance(payload, dict) or set(payload) != expected:
        raise WorkflowError(f"Malformed {'checkpoint' if checkpoint else 'result'} for task {task['id']}")
    if payload["manifest_sha256"] != digest(manifest) or payload["task"] != task:
        raise WorkflowError(f"Manifest/task identity mismatch for task {task['id']}")
    integer(payload["completed"], "completed", 0 if checkpoint else task["samples"], task["samples"])
    integer(payload["hits"], "hits", 0, payload["completed"])
    if not isinstance(payload["python"], str):
        raise WorkflowError("Missing Python version")
    if checkpoint:
        state = payload["rng_state"]
        if (not isinstance(state, list) or len(state) != 3 or state[0] != 3
                or not isinstance(state[1], list) or len(state[1]) != 625 or state[2] is not None):
            raise WorkflowError("Invalid RNG checkpoint")
        for value in state[1][:-1]:
            integer(value, "RNG word", 0, 2**32 - 1)
        integer(state[1][-1], "RNG index", 0, 624)
    return payload


def run_task(run, task_id, *, max_chunks=None, min_free_mb=64, stop=None):
    run = Path(run)
    manifest = load_manifest(run)
    task = task_at(manifest, task_id)
    if max_chunks is not None:
        integer(max_chunks, "max_chunks", 1)
    result_path = task_path(run, "results", task_id)
    checkpoint_path = task_path(run, "checkpoints", task_id)
    if result_path.exists():
        validate_payload(read_record(result_path), manifest, task)
        return "skipped"
    if stop is not None and stop():
        return "paused"
    check_free_space(run, min_free_mb)
    with task_lock(run, task_id):
        # Another worker may have finished between the first check and lock acquisition.
        if result_path.exists():
            validate_payload(read_record(result_path), manifest, task)
            return "skipped"
        rng = random.Random(int(task["seed"]))
        completed = hits = 0
        if checkpoint_path.exists():
            saved = validate_payload(read_record(checkpoint_path), manifest, task, checkpoint=True)
            if saved["python"].split(".")[:2] != platform.python_version().split(".")[:2]:
                raise WorkflowError("Resume checkpoints with the same Python major.minor version")
            completed, hits = saved["completed"], saved["hits"]
            state = saved["rng_state"]
            rng.setstate((state[0], tuple(state[1]), state[2]))
        chunks = 0
        while completed < task["samples"]:
            if stop is not None and stop():
                return "paused"
            count = min(manifest["config"]["chunk_size"], task["samples"] - completed)
            hits += count_hits(rng, count)
            completed += count
            payload = {"manifest_sha256": digest(manifest), "task": task,
                       "completed": completed, "hits": hits, "python": platform.python_version()}
            check_free_space(run, min_free_mb)
            write_record(checkpoint_path, {**payload, "rng_state": rng.getstate()})
            chunks += 1
            if completed < task["samples"] and max_chunks is not None and chunks >= max_chunks:
                return "paused"
        payload = {"manifest_sha256": digest(manifest), "task": task,
                   "completed": completed, "hits": hits, "python": platform.python_version()}
        check_free_space(run, min_free_mb)
        write_record(result_path, payload)
        checkpoint_path.unlink(missing_ok=True)
    return "complete"


def _initialize_worker(event):
    global _worker_stop
    _worker_stop = event


def _local_task(arguments):
    run, task_id, min_free_mb = arguments
    with stop_on_signal(_worker_stop):
        return run_task(run, task_id, min_free_mb=min_free_mb, stop=_worker_stop.is_set)


def run_local(run, workers=1, min_free_mb=64):
    integer(workers, "workers", 1)
    limit = int(os.environ.get("SLURM_CPUS_PER_TASK", os.cpu_count() or 1))
    if workers > limit:
        raise WorkflowError(f"Requested {workers} workers but CPU limit is {limit}")
    manifest = load_manifest(run)
    arguments = [(str(Path(run).resolve()), task["id"], min_free_mb) for task in manifest["tasks"]]
    if workers == 1:
        stop = threading.Event()
        with stop_on_signal(stop):
            states = [run_task(path, task, min_free_mb=space, stop=stop.is_set)
                      for path, task, space in arguments]
    else:
        context = multiprocessing.get_context("spawn")
        stop = context.Event()
        with stop_on_signal(stop):
            with ProcessPoolExecutor(max_workers=workers, mp_context=context,
                                     initializer=_initialize_worker, initargs=(stop,)) as pool:
                states = list(pool.map(_local_task, arguments, chunksize=1))
    return {state: states.count(state) for state in sorted(set(states))}
