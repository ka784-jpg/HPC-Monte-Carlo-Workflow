# Run on Slurm

The same `task` command used locally runs once per array element. Scheduler job IDs never enter the random seed. Slurm supplies `SLURM_ARRAY_TASK_ID`; the array's `%K` suffix limits concurrent elements. See the official [job-array documentation](https://slurm.schedmd.com/job_array.html).

## Prepare on the Cluster

Clone the repository onto a filesystem visible to compute nodes, create a Python 3.11+ virtual environment there, and install the package. Use your site's supported Python module or environment. Installing the core package is sufficient for workers:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m mcflow init configs/quickstart.json runs/slurm-demo
python -m mcflow slurm runs/slurm-demo --python "$PWD/.venv/bin/python" --concurrency 4
```

Generate this script **on the cluster**, not on Windows: it embeds absolute paths to the run and Python environment. The command writes `runs/slurm-demo/submit.sbatch` and prints an `sbatch` command. It does not contact Slurm or submit anything.

## Review and Submit Explicitly

Review both the script and printed command. Defaults are one CPU, 256 MiB, ten minutes per array element, and at most four simultaneous tasks. These are example settings, not tuned resource recommendations for every site. Add your site's required `--account`, `--partition`, or QoS options before the script filename in the printed command.

Run that reviewed command explicitly. It uses array-aware log names (`%A_%a`), separate stdout/stderr logs, and `--signal=B:TERM@60`. The script replaces its shell with the Python worker using `exec`, so the advance batch-process signal requests a checkpointed pause. Scheduling, time limits, and signal delivery remain subject to site policy; consult [`sbatch`](https://slurm.schedmd.com/sbatch.html).

This tiny example is deliberately laptop-friendly. Job-launch overhead can dominate; it is a workflow demonstration, not a claim that a cluster is needed to estimate pi.

## Observe and Collect

Use your scheduler's `squeue` and `sacct` tools to inspect the array and its exit codes, and inspect the run's `logs/` directory. Then check the files:

```bash
python -m mcflow status runs/slurm-demo
python -m mcflow aggregate runs/slurm-demo
```

Aggregation fails if any task is missing, locked, or invalid. File validation does not replace scheduler-accounting checks: inspect both before considering a campaign finished. A paused worker exits 75; this is not success and does not automatically request requeue.

To plot after collection, install `.[plots]` in an appropriate analysis environment and run `python -m mcflow plot runs/slurm-demo`. Small analysis can also be performed on a workstation after transferring the complete run directory.

## Retry Only Unfinished Tasks

After all jobs in the relevant array have terminated, investigate failures and resolve any confirmed stale locks as described in [Recovery](WORKFLOW.md#recovery). Then:

```bash
python -m mcflow slurm runs/slurm-demo --pending --python "$PWD/.venv/bin/python" --concurrency 4
```

This generates a new command containing only incomplete task IDs, including resumable checkpoints. Review and submit it manually. The same task IDs retain their original seeds. Corrupted outputs block this operation instead of being silently rerun.

The generator does not cancel, modify, or submit jobs; bypass site limits; inspect private scheduler accounts; or automatically remove data. Verify the site's maximum array size, quota, shared-filesystem behavior, and Python availability before scaling up.
