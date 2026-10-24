# Slurm and Sleeper Scripts

This workflow has actual [Slurm batch files](../slurm/) and [Bash orchestration scripts](../scripts/). The Python script generator remains available as an alternative; this walkthrough uses the checked-in files.

```text
init -> preflight -> submit.sh -> monte_carlo.sbatch array
                          |
                          +-- afterok dependency -> collect.sbatch -> tables + plots

sleeper.sh: check files / queue / accounting -> sleep -> repeat, finish, fail, or timeout
retry.sh:   select unfinished task IDs -> review -> explicit resubmission
```

## 1. Prepare

Use Bash 4+ on a Linux cluster, Python 3.11+, and a shared filesystem visible to compute nodes. Clone the repository there and install the package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[plots]"
export PYTHON="$PWD/.venv/bin/python"
python -m mcflow init configs/quickstart.json runs/slurm-demo
bash scripts/preflight.sh runs/slurm-demo --slurm --plots
```

Paths with spaces are supported. The batch jobs receive absolute paths and the expected manifest hash. No usernames, hosts, partitions, accounts, modules, or credentials are hardcoded. The plotting extra is needed for collection; workers alone need only the core package.

## 2. Review and Submit

```bash
bash scripts/submit.sh runs/slurm-demo --collect
```

This is a **dry run**: it checks inputs and prints quoted commands, but never calls `sbatch`. To submit explicitly:

```bash
bash scripts/submit.sh runs/slurm-demo --collect --submit
```

The submitter schedules [monte_carlo.sbatch](../slurm/monte_carlo.sbatch) as an array and prints `ARRAY_JOB_ID`. With `--collect`, it schedules [collect.sbatch](../slurm/collect.sbatch) using `--dependency=afterok:ARRAY_JOB_ID` and prints `COLLECTOR_JOB_ID`. A checksummed receipt in `RUN/submissions/job-ID.json` records the manifest, submitted task IDs, and collector ID when available.

The `afterok` dependency defers collection until the array succeeds. The collector's `--kill-on-invalid-dep=yes` prevents a failed dependency from leaving it pending forever. A paused worker exits 75 rather than success; that array needs recovery before a new collector can run. See Slurm's [dependency options](https://slurm.schedmd.com/sbatch.html#OPT_dependency) and [array behavior](https://slurm.schedmd.com/job_array.html).

If collector submission fails, the array is **not cancelled or resubmitted**. Its ID and receipt remain available. Investigate, then collect manually after completion or explicitly submit a collector. If any `sbatch` outcome is unknown, inspect the scheduler before retrying: submission is not a distributed transaction. These scripts target one local Slurm cluster, not federated multi-cluster submissions.

### Site Settings

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `PYTHON` | `python3` | Interpreter; use an absolute path to a shared environment |
| `MC_CONCURRENCY` | `4` | Maximum simultaneous array elements |
| `MC_WALLTIME` | `00:10:00` | Time limit per sampling job |
| `MC_MEMORY_MB` | `256` | Memory request per sampling job |
| `MC_MIN_FREE_MB` | `64` | Filesystem free-space floor, not a quota reservation |
| `MC_ACCOUNT` | unset | Optional Slurm account |
| `MC_PARTITION` | unset | Optional Slurm partition |
| `MC_QOS` | unset | Optional Slurm QoS |

The collector has separate checked-in defaults: one CPU, 1 GiB, and five minutes. These are illustrative settings, not cluster-specific tuning. Both jobs limit common numerical-library thread counts to one. The sampling job uses `exec` and an advance termination signal so the worker can checkpoint. This small example demonstrates the workflow; launch overhead can dominate its runtime.

## 3. Use the Sleeper

The sleeper is an ordinary monitoring process with a `sleep` loop. It does **not** occupy a Slurm allocation simply to wait, and it never submits, cancels, or requeues jobs. Run it only where site policy permits monitoring processes.

```bash
bash scripts/sleeper.sh runs/slurm-demo --job-id ARRAY_JOB_ID --interval 60 --timeout 86400
```

Replace the placeholder with the array ID printed by the submitter. Each poll validates task files and checks `squeue`. Once the array leaves the queue, it checks `sacct` states and exit codes for every submitted element. Receipts identify the elements of retry arrays; without a receipt it expects the complete manifest's array. Missing accounting records mean waiting, not success. Accounting failures, corrupted outputs, and timeouts return nonzero status.

File-only mode works without Slurm, for example while another terminal runs the local worker:

```bash
bash scripts/sleeper.sh runs/slurm-demo --interval 10 --timeout 600
```

File-only success means the files validate, not that scheduler accounting was checked. The array monitor does not wait for the separate collector; inspect its ID/log to confirm the plots are complete.

For background monitoring on a site-approved login/utility node:

```bash
nohup bash scripts/sleeper.sh runs/slurm-demo --job-id ARRAY_JOB_ID \
  --interval 60 --timeout 86400 > runs/slurm-demo/logs/monitor.log 2>&1 &
```

Choose a unique log filename to preserve prior logs. Exit codes are 0 for completion, 1 for failure, 124 for timeout, and 130/143 for interruption/termination. Stopping the monitor does not cancel simulations. The timeout bounds the polling loop, not a scheduler command that itself hangs; use site command-timeout facilities if needed. Poll conservatively to avoid hammering Slurm. References: [`squeue`](https://slurm.schedmd.com/squeue.html), [`sacct`](https://slurm.schedmd.com/sacct.html).

## 4. Recover and Collect

After all old jobs stop, inspect logs and resolve only confirmed stale locks as described in [Recovery](WORKFLOW.md#recovery). Then:

```bash
bash scripts/retry.sh runs/slurm-demo --collect           # Review unfinished IDs
bash scripts/retry.sh runs/slurm-demo --collect --submit  # Explicit retry + new collector
```

Original task IDs, seeds, and checkpoints are retained. Completed tasks are excluded; corrupted records stop the operation. There is no automatic retry loop. The submission lock prevents simultaneous wrapper invocations, but does not track queued jobs after submission: do not launch overlapping arrays or retry live jobs.

To collect a completed run without a scheduled collector, use `bash scripts/collect.sh runs/slurm-demo`. For a local end-to-end run after initialization, use `bash scripts/run_local.sh runs/slurm-demo 2`. Both reject incomplete or invalid results.

Check site quotas, inode limits, maximum array sizes, shared-filesystem semantics, and scheduler accounting before scaling up. Tests execute batch bodies and mock scheduler interactions; no real cluster deployment or scaling benchmark is claimed.

## Alternative: Generated Script

`python -m mcflow slurm RUN --python /path/to/venv/bin/python` still writes a run-specific batch script and prints a command without submitting. Choose one submission path to avoid duplicate jobs.
