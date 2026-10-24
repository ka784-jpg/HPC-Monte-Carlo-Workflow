"""Generate a reviewable Slurm submission command; never submit jobs."""

from pathlib import Path
import re
import shlex

from .analysis import inspect_run
from .manifest import integer, load_manifest
from .storage import WorkflowError, atomic_text, digest


def index_ranges(indices):
    groups = []
    start = previous = None
    for value in sorted(set(indices)):
        if previous is not None and value != previous + 1:
            groups.append(str(start) if start == previous else f"{start}-{previous}")
            start = None
        if start is None:
            start = value
        previous = value
    if start is not None:
        groups.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(groups)


def prepare_slurm(run, *, concurrency=4, pending=False, python="python3",
                  walltime="00:10:00", memory_mb=256, min_free_mb=64):
    integer(concurrency, "concurrency", 1, 100000)
    integer(memory_mb, "memory_mb", 64)
    integer(min_free_mb, "min_free_mb", 0)
    if not re.fullmatch(r"\d{2,3}:[0-5]\d:[0-5]\d", walltime):
        raise WorkflowError("walltime must be HH:MM:SS (hours may have three digits)")
    run = Path(run).resolve()
    if any(character in str(run) + python for character in "\n\r\x00") or not python:
        raise WorkflowError("Invalid path or Python executable")
    manifest = load_manifest(run)
    status, _ = inspect_run(run)
    if status["errors"] or status["counts"]["locked"]:
        raise WorkflowError("Resolve invalid records or active/stale locks before preparing a submission")
    indices = [index for index, state in status["states"].items()
               if not pending or state != "complete"]
    if not indices:
        raise WorkflowError("No unfinished tasks remain")
    script = run / "submit.sbatch"
    invocation = shlex.join([python, "-m", "mcflow", "task", str(run),
                             "--expect-manifest", digest(manifest), "--min-free-mb", str(min_free_mb)])
    atomic_text(script, "#!/usr/bin/env bash\nset -euo pipefail\n"
                + "export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1\n"
                + f'exec {invocation} --task-id "${{SLURM_ARRAY_TASK_ID:?Submit as a job array}}"\n')
    command = ["sbatch", f"--array={index_ranges(indices)}%{concurrency}", "--job-name=mcflow",
               "--ntasks=1", "--cpus-per-task=1", f"--mem={memory_mb}M", f"--time={walltime}",
               "--signal=B:TERM@60", f"--output={run / 'logs' / '%A_%a.out'}",
               f"--error={run / 'logs' / '%A_%a.err'}", str(script)]
    return shlex.join(command)
