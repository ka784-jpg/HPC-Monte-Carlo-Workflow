# Workflow Design

## Experiment to Validated Results

```text
configuration -> frozen manifest -> independent tasks -> validated collection -> plots
                                        |
                                 durable checkpoints
                                        |
                                  resume same task
```

The manifest is the contract between these stages. A worker cannot quietly change its sample budget, seed, or task identity; aggregation checks those fields against the manifest before accepting an output.

## Configuration

```json
{
  "samples": [1000, 10000],
  "replicates": 4,
  "master_seed": 2026,
  "chunk_size": 2000
}
```

Each `(samples, replicate)` pair creates one task. Sample budgets must be positive, unique, increasing integers. Unknown fields, booleans in integer fields, duplicate budgets, and zero-sized workloads are rejected. Configuration limits prevent accidentally creating an unbounded task manifest; they are not a guarantee that a chosen workload fits a time allocation.

`init` requires a new run directory. It records the configuration, engine identifier, and ordered task map in `manifest.json`. Changing the configuration requires a separate run. Changing simulation behavior requires a new engine identifier and appropriate tests.

## Random Streams and Checkpoints

A task's integer seed is the SHA-256 digest of the engine identifier, master seed, sample budget, and replicate number. It does not depend on the operating-system process ID, execution order, worker count, or scheduler job number. Seeds are stored as decimal strings to avoid loss of precision in JSON readers.

Each task owns a `random.Random` instance. The kernel consumes exactly two `random()` values per sampled point. A checkpoint records the count of completed points, hits, complete generator state, Python version, and task/manifest identities. Resume uses the saved generator state rather than reseeding. See Python's documentation for [`Random`, `getstate`, and `setstate`](https://docs.python.org/3/library/random.html).

Checkpoints resume only under the same Python major/minor version. Task results are deterministic for the tested Python/runtime combination and independent of chunk boundaries. Distinct hashed seeds are a practical stream-separation convention, **not a mathematical proof of non-overlapping or statistically independent PRNG streams**. This is not a cryptographic generator.

## Task Lifecycle

1. Validate the manifest and task ID.
2. Validate and skip an existing final result, if present.
3. Check free space and acquire an exclusive per-task lock directory.
4. Restore a valid checkpoint, or initialize a new stream.
5. Sample one chunk, then atomically checkpoint progress.
6. Write a final result only after exactly the prescribed number of samples.
7. Remove the now-unnecessary checkpoint and release the lock.

Writes use a temporary file in the same directory, flush and `fsync` it, then replace the destination. Records carry checksums. The final result is written before the checkpoint is removed, so a crash between those operations leaves a valid final result that can be reused.

On Windows, transient access-denied/sharing errors during replacement get at most six short retries (1.575 seconds of backoff in total). Persistent errors still fail without replacing the old record. This is a bounded filesystem-operation retry, not a simulation rerun or seed change.

SIGINT/SIGTERM requests pause at a chunk boundary. Completed chunks remain valid, and a pause returns exit code 75 rather than falsely signaling success. Hard termination may lose the current chunk; replaying it from the last saved RNG state gives the same final result. A hard kill can leave a lock requiring manual review.

## Recovery

For a deliberate checkpoint demonstration:

```bash
python -m mcflow init configs/quickstart.json runs/recovery
python -m mcflow task runs/recovery --task-id 4 --max-chunks 1
python -m mcflow status runs/recovery
python -m mcflow run runs/recovery
python -m mcflow aggregate runs/recovery
```

The second command intentionally returns 75. Run the subsequent commands separately if your shell stops on nonzero status. Task 4 checkpoints 2,000 of its 10,000 points; the next invocation resumes it exactly.

A leftover `locks/000004.lock` is not automatically deleted. First verify that the worker and its scheduler job are no longer running. The PID in `owner.json` alone is not sufficient proof, especially across nodes or after PID reuse. Preserve diagnostic logs, then remove only the confirmed stale task lock and retry the same task. **Do not delete a live lock or edit a checkpoint to make validation pass.**

Damaged or foreign results stop validation. Preserve them for diagnosis. A clean, separately named run is the simplest way to recompute a demonstration. No command silently overwrites an invalid result with a plausible replacement.

## Aggregation

The collector requires exactly one valid result for every expected task. It checks record checksums, manifest/task identity, integer sample and hit counts, unexpected JSON outputs, and unresolved task locks. Missing data do not become zeros. Seeds are not rerolled when a task fails.

`tasks.csv` contains one row per replicate. `summary.json` pools counts within each sample budget and includes the manifest hash and a hash of the ordered validated result payloads. Analysis files are derived artifacts and may be regenerated. `plot` revalidates the raw results instead of trusting an old summary. Do not aggregate while workers are still changing the run directory.

## Guarantees and Limits

- **CPU allocation:** local workers are explicitly bounded by `SLURM_CPUS_PER_TASK` when present, otherwise the reported logical CPU count. The default is one. This is not automatic scheduler/cgroup/affinity discovery; choose an appropriate limit for your environment.
- **Memory:** the sampling kernel is constant-memory. Slurm memory requests bound the allocation; the Python program is not an RSS watchdog.
- **Storage:** free-space checks use filesystem-reported capacity, not user/group quotas or inode quotas. Check site limits separately. Checks and writes are not a storage reservation.
- **Filesystem semantics:** locks rely on exclusive directory creation and updates rely on same-filesystem atomic replacement. Validate these semantics on your shared filesystem. File `fsync` plus replacement is not a promise of survival through every power loss; parent directories are not explicitly fsynced.
- **Concurrency:** per-task locking protects writers. There is no distributed submission coordinator, automatic stale-lock reclamation, or automatic job resubmission. Run one collector after jobs finish.
- **Integrity:** checksums detect accidental changes. They are not signatures, and cannot authenticate records against an adversary who can rewrite both data and checksums. Use trusted run directories only.
- **Statistics:** Wilson intervals are approximate binomial confidence intervals, not guaranteed bounds on any individual run. The toy example assumes independent uniform samples.

The cluster path has generated-script and integration tests, but this repository does not claim a production Slurm deployment or cluster-scaling benchmark. CI executes the same worker locally on Linux and Windows.
