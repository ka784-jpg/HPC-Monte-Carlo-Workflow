# Command-Line Reference

Use `python -m mcflow --help` or the installed `mcflow` entry point. All commands accept paths containing spaces.

For actual shell and batch scripts, see [scripts/](../scripts/), [slurm/](../slurm/), and the [Slurm/sleeper walkthrough](SLURM.md). The Python CLI below is the underlying worker interface, not the only way to operate the workflow.

| Command | Purpose |
| --- | --- |
| `init CONFIG RUN` | Validate configuration and create a fresh run directory |
| `run RUN --workers K` | Run or resume all tasks locally, default one worker |
| `task RUN --task-id I` | Run or resume exactly one task |
| `status RUN` | Report complete, checkpointed, pending, locked, and invalid task counts |
| `aggregate RUN` | Validate all tasks and write CSV/JSON analysis |
| `plot RUN` | Revalidate, aggregate, and render PNG/PDF plots; requires `.[plots]` |
| `slurm RUN` | Write a batch script and print a submission command, without submitting |

## Options

- `run`, `task`, and `slurm`: `--min-free-mb M` sets the filesystem free-space floor, default 64 MiB. Zero disables this floor; it does not disable OS write errors.
- `task`: `--max-chunks K` intentionally pauses after K additional chunks if unfinished, useful for recovery demonstrations. `--expect-manifest HASH` rejects a run whose manifest differs from a queued job's frozen identity.
- `slurm`: `--concurrency K` (default 4), `--walltime HH:MM:SS` (default `00:10:00`), `--memory-mb M` (default 256), `--python EXECUTABLE` (default `python3`), and `--pending` to exclude completed tasks.

## Exit Codes

| Code | Meaning |
| --- | --- |
| 0 | Successful command; a completed task may have been validated and skipped |
| 1 | Validation, resource, lock, or I/O failure |
| 2 | Command-line usage error |
| 75 | Paused work; resume is required |

`status` returns 1 for invalid records, but 0 for a well-formed incomplete run. Use `aggregate` as the strict completion check. Unexpected programming errors produce a traceback and a nonzero exit status.

## Python Interfaces

```python
from mcflow.manifest import initialize
from mcflow.runner import run_task, run_local
from mcflow.analysis import aggregate

initialize("configs/quickstart.json", "runs/api-demo")
state = run_task("runs/api-demo", 0)  # "complete", "skipped", or "paused"
counts = run_local("runs/api-demo", workers=1)
summary = aggregate("runs/api-demo")
assert summary["status"] == "PASS"
```

Put multi-process calls inside `if __name__ == "__main__":` when writing an executable Python script. The CLI already does this. The package's small interfaces are intended for examples, not a compatibility promise for external production systems.
